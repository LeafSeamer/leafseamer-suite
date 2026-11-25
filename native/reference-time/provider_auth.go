package collector

import (
	"bufio"
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"io"
	"math/big"
	"strconv"
	"sync"
	"time"
)

const (
	providerAuthVersion = "time-provider-auth/1"
	providerAuthMaximum = 2048
	providerAuthTimeout = 2 * time.Second
)

// AuthenticationReference identifies an immutable authentication-clock original.
type AuthenticationReference struct {
	ID, Revision, Digest string
}

type authenticationProjection struct {
	lower, upper, tick, quantization uint64
	drift                            int64
}

// The core interval is valid at its read tick. Enclose both ends of the elapsed
// monotonic duration before using it for TLS or an outgoing poll.
func (p authenticationProjection) at(now uint64) (time.Time, time.Time, error) {
	if now < p.tick {
		return time.Time{}, time.Time{}, errBootstrap
	}
	const billion = 1000000000
	delta := new(big.Int).SetUint64(now - p.tick)
	margin := new(big.Int).Lsh(new(big.Int).SetUint64(p.quantization), 1)
	floor := new(big.Int).Sub(delta, margin)
	if floor.Sign() < 0 {
		floor.SetUint64(0)
	}
	ceiling := new(big.Int).Add(delta, margin)
	floor.Mul(floor, big.NewInt(billion-p.drift)).Quo(floor, big.NewInt(billion)).Add(floor, new(big.Int).SetUint64(p.lower))
	ceiling.Mul(ceiling, big.NewInt(billion+p.drift)).Add(ceiling, big.NewInt(billion-1))
	ceiling.Quo(ceiling, big.NewInt(billion)).Add(ceiling, new(big.Int).SetUint64(p.upper))
	if !floor.IsUint64() || !ceiling.IsUint64() {
		return time.Time{}, time.Time{}, errBootstrap
	}
	utc := func(ns uint64) time.Time { return time.Unix(int64(ns/billion), int64(ns%billion)).UTC() }
	return utc(floor.Uint64()), utc(ceiling.Uint64()), nil
}

type providerAuthentication struct {
	mu   sync.Mutex
	file interface {
		io.ReadWriteCloser
		SetDeadline(time.Time) error
	}
	reader        *bufio.Reader
	bindingDigest string
	domain        wireObject
}

// read implements AuthenticationSource for a collector using this bound stream.
// A declined qualification may be retried with an entirely new read.
func (p *providerAuthentication) read(ctx context.Context) (sample AuthenticationInterval, failure error) {
	if !p.mu.TryLock() {
		return AuthenticationInterval{}, errBootstrap
	}
	defer p.mu.Unlock()
	defer func() {
		if failure == errProviderLink {
			p.file.Close()
		}
	}()
	deadline := time.Now().Add(providerAuthTimeout)
	if earlier, ok := ctx.Deadline(); ok && earlier.Before(deadline) {
		deadline = earlier
	}
	if ctx.Err() != nil || p.file.SetDeadline(deadline) != nil {
		return AuthenticationInterval{}, errProviderLink
	}
	stop := context.AfterFunc(ctx, func() { p.file.Close() })
	defer stop()
	var rawID [16]byte
	rand.Read(rawID[:])
	rawID[6] = rawID[6]&15 | 64
	rawID[8] = rawID[8]&63 | 128
	id := fmt.Sprintf("%x-%x-%x-%x-%x", rawID[:4], rawID[4:6], rawID[6:8], rawID[8:10], rawID[10:])
	sent, err := nativeTick()
	if err != nil {
		return AuthenticationInterval{}, errProviderLink
	}
	request, err := json.Marshal(wireObject{"version": providerAuthVersion, "type": "AUTH_READ", "request_id": id,
		"binding_digest": p.bindingDigest, "tick_ns": strconv.FormatUint(sent, 10)})
	if err != nil {
		return AuthenticationInterval{}, errProviderLink
	}
	if _, err := p.file.Write(append(request, '\n')); err != nil {
		return AuthenticationInterval{}, errProviderLink
	}
	line, err := p.reader.ReadSlice('\n')
	if err != nil || len(line) > providerAuthMaximum+1 || p.reader.Buffered() != 0 ||
		ctx.Err() != nil || p.file.SetDeadline(time.Time{}) != nil {
		return AuthenticationInterval{}, errProviderLink
	}
	received, err := nativeTick()
	if err != nil || received < sent {
		return AuthenticationInterval{}, errProviderLink
	}
	return readProviderAuthentication(line[:len(line)-1], id, p.bindingDigest, p.domain, sent, received)
}

func authReference(value any) (AuthenticationReference, bool) {
	object, _ := value.(map[string]any)
	id, _ := object["id"].(string)
	revision, _ := object["revision"].(string)
	digest, _ := object["digest"].(string)
	n, ok := bootstrapUint(revision)
	return AuthenticationReference{id, revision, digest}, fields(object, "digest id revision") &&
		ids(object, "id") && ok && n > 0 && validDigest(digest)
}

func readProviderAuthentication(raw []byte, id, bindingDigest string, domain wireObject, sent, received uint64) (AuthenticationInterval, error) {
	frame := canonicalObject(raw)
	if !fields(frame, "binding_digest reply_to sample type version") || frame["reply_to"] != id ||
		frame["binding_digest"] != bindingDigest || frame["type"] != "AUTH_RESULT" || frame["version"] != providerAuthVersion {
		return AuthenticationInterval{}, errProviderLink
	}
	if frame["sample"] == nil {
		return AuthenticationInterval{}, errBootstrap
	}
	sample, _ := frame["sample"].(map[string]any)
	if !fields(sample, "acquisition_ref drift_ppb lower_ns monotonic_quantization_ns policy_ref runtime_domain_ref runtime_ref source_ref tick_ns upper_ns valid_before_tick_ns") ||
		!sameWire(sample["runtime_domain_ref"], domain) {
		return AuthenticationInterval{}, errProviderLink
	}
	lower, lowerOK := bootstrapUint(sample["lower_ns"])
	upper, upperOK := bootstrapUint(sample["upper_ns"])
	tick, tickOK := bootstrapUint(sample["tick_ns"])
	expires, expiresOK := bootstrapUint(sample["valid_before_tick_ns"])
	quantization, quantizationOK := bootstrapUint(sample["monotonic_quantization_ns"])
	drift, driftOK := sample["drift_ppb"].(float64)
	if !lowerOK || !upperOK || lower > upper || !tickOK || !expiresOK || sent > tick || tick > received ||
		expires <= tick || expires-tick > uint64(5*time.Second) ||
		!quantizationOK || quantization == 0 || !driftOK || drift < 0 || drift > 1000000 || float64(int64(drift)) != drift {
		return AuthenticationInterval{}, errProviderLink
	}
	acquisition, acquisitionOK := authReference(sample["acquisition_ref"])
	policy, policyOK := authReference(sample["policy_ref"])
	runtime, runtimeOK := authReference(sample["runtime_ref"])
	source, sourceOK := authReference(sample["source_ref"])
	if !acquisitionOK || !policyOK || !runtimeOK || !sourceOK {
		return AuthenticationInterval{}, errProviderLink
	}
	if received >= expires {
		return AuthenticationInterval{}, errBootstrap
	}
	authority, err := json.Marshal(selectFields(sample, "policy_ref runtime_domain_ref runtime_ref source_ref"))
	if err != nil {
		return AuthenticationInterval{}, errProviderLink
	}
	projection := authenticationProjection{lower: lower, upper: upper, tick: tick, quantization: quantization, drift: int64(drift)}
	lo, hi, err := projection.at(received)
	if err != nil {
		return AuthenticationInterval{}, err
	}
	return AuthenticationInterval{
		Lower: lo, Upper: hi, ObservedTickNS: received, ExpiresTickNS: expires, Binding: hashWire(authority), Acquisition: acquisition.ID,
		SourceReadTickNS: tick, providerReadID: id, AcquisitionRef: acquisition, PolicyRef: policy, RuntimeRef: runtime, SourceRef: source, projection: &projection,
	}, nil
}
