package collector

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"errors"
	"math"
	"math/big"
	"net/netip"
	"time"

	"github.com/facebook/time/ntp/protocol"
	"github.com/facebook/time/ntp/protocol/nts"
)

var errKEBackoff = errors.New("reference NTS key establishment backoff active")

// NTSSourceConfig is the source's configured endpoint and dedicated trust set.
type NTSSourceConfig struct {
	KeyEndpoint   netip.AddrPort
	ServerName    string
	RootDER       [][]byte
	DefaultTarget NTPTarget
	Targets       map[NTPTarget]netip.AddrPort
}

// NTSObservation includes secret-bearing wire bytes for protected storage only.
// Authentication proves protocol origin, independently of service UTC qualification.
type NTSObservation struct {
	Exchange
	KeyEndpoint                 netip.AddrPort
	ServerName                  string
	TLSAuthentication           AuthenticationInterval
	KeyCompletionAuthentication AuthenticationInterval
	PollAuthentication          AuthenticationInterval
	RootDigests, ChainDigests   [][32]byte
	KeyReply                    []byte
}

type ntsSource struct {
	operation chan struct{}
	udp       sourceState
	config    keConfig
	session   *ntsSession
	seen      map[[32]byte]struct{}
	nextKE    uint64
	backoff   time.Duration
}

// NTSCollector establishes keys and sends only authenticated polls for its configured sources.
type NTSCollector struct {
	sources map[string]*ntsSource
	keySlot chan struct{}
	auth    AuthenticationSource
	tick    func() (uint64, error)
}

func NewNTSCollector(configs map[string]NTSSourceConfig, auth AuthenticationSource) (*NTSCollector, error) {
	if len(configs) == 0 || len(configs) > maxSources || auth == nil {
		return nil, errSource
	}
	sources := make(map[string]*ntsSource, len(configs))
	for id, config := range configs {
		serverName := canonicalHost(config.ServerName)
		keyEndpoint := numericEndpoint(config.KeyEndpoint)
		if id == "" || serverName == "" || !keyEndpoint.IsValid() ||
			len(config.RootDER) == 0 || len(config.RootDER) > 8 || len(config.Targets) == 0 || len(config.Targets) > 16 {
			return nil, errSource
		}
		if _, err := netip.ParseAddr(serverName); err == nil {
			return nil, errSource
		}
		pool := x509.NewCertPool()
		var digests [][32]byte
		for _, raw := range config.RootDER {
			root, err := x509.ParseCertificate(bytes.Clone(raw))
			if err != nil || !root.IsCA {
				return nil, errSource
			}
			digests = append(digests, sha256.Sum256(root.Raw))
			pool.AddCert(root)
		}
		targets := make(map[NTPTarget]netip.AddrPort, len(config.Targets))
		for target, endpoint := range config.Targets {
			target.Name, endpoint = canonicalHost(target.Name), numericEndpoint(endpoint)
			if target.Name == "" || target.Port != endpoint.Port() || !endpoint.IsValid() || targets[target].IsValid() {
				return nil, errSource
			}
			if ip, err := netip.ParseAddr(target.Name); err == nil && ip != endpoint.Addr().WithZone("") {
				return nil, errSource
			}
			targets[target] = endpoint
		}
		defaultTarget := NTPTarget{canonicalHost(config.DefaultTarget.Name), config.DefaultTarget.Port}
		if !targets[defaultTarget].IsValid() {
			return nil, errSource
		}
		sources[id] = &ntsSource{operation: make(chan struct{}, 1), config: keConfig{
			endpoint: keyEndpoint, serverName: serverName, roots: pool, rootDigests: digests,
			defaultTarget: defaultTarget, targets: targets,
		}}
	}
	return &NTSCollector{sources: sources, keySlot: make(chan struct{}, 1), auth: auth, tick: nativeTick}, nil
}

func (source *ntsSource) forgetKeys() {
	if source.session != nil {
		clear(source.session.c2s)
		clear(source.session.s2c)
		clear(source.session.observation.reply)
		eraseCookies(source.session.cookies)
		source.session = nil
		source.seen = nil
	}
}

func eraseCookies(cookies [][]byte) {
	for _, cookie := range cookies {
		clear(cookie)
	}
}

func (source *ntsSource) addCookies(cookies [][]byte, max int) error {
	if len(cookies) > max || len(source.session.cookies)+len(cookies) > maxCookies {
		return errPacket
	}
	for _, cookie := range cookies {
		hash := sha256.Sum256(cookie)
		if _, seen := source.seen[hash]; seen || len(cookie) == 0 || len(cookie) > maxCookieBytes {
			return errPacket
		}
		source.seen[hash] = struct{}{}
		source.session.cookies = append(source.session.cookies, cookie)
	}
	return nil
}

func (c *NTSCollector) keys(ctx context.Context, source *ntsSource) error {
	if source.session != nil && len(source.session.cookies) > 0 {
		return nil
	}
	source.forgetKeys()
	now, err := c.tick()
	if err != nil {
		return errBootstrap
	}
	if now < source.nextKE {
		return errKEBackoff
	}
	select {
	case c.keySlot <- struct{}{}:
		defer func() { <-c.keySlot }()
	default:
		return errConcurrent
	}
	session, keErr := establishKeys(ctx, source.config, c.auth, c.tick)
	if keErr == nil {
		cookies := session.cookies
		session.cookies = nil
		source.session, source.seen = session, make(map[[32]byte]struct{})
		keErr = source.addCookies(cookies, maxCookies)
		if keErr != nil {
			source.forgetKeys()
		}
	}
	source.backoff = nextBackoff(source.backoff, keErr != nil)
	delay := source.backoff
	if delay == 0 {
		delay = time.Minute
	}
	if end, err := c.tick(); err != nil || end < now || math.MaxUint64-end < uint64(time.Hour) {
		source.forgetKeys()
		source.nextKE = math.MaxUint64
		return errBootstrap
	} else {
		source.nextKE = end + uint64(jitter(delay))
	}
	return keErr
}

func nextBackoff(previous time.Duration, failed bool) time.Duration {
	if !failed {
		return 0
	}
	return min(time.Hour, max(time.Minute, 2*previous))
}

func jitter(delay time.Duration) time.Duration {
	extra := min(delay/10, time.Hour-delay)
	if extra <= 0 {
		return delay
	}
	random, err := rand.Int(rand.Reader, big.NewInt(int64(extra)+1))
	if err != nil {
		return delay
	}
	return delay + time.Duration(random.Int64())
}

func (c *NTSCollector) currentSession(ctx context.Context, session *ntsSession) (AuthenticationInterval, error) {
	value, err := authenticationNow(ctx, c.auth, c.tick)
	now, clockErr := c.tick()
	if err != nil || clockErr != nil || value.Binding != session.observation.atCompletion.Binding ||
		value.ObservedTickNS < session.observation.atCompletion.ObservedTickNS ||
		now < session.issuedTickNS || now-session.issuedTickNS >= ntsLifetimeNS ||
		now >= value.ExpiresTickNS || !coversInterval(session.chain, value) {
		return AuthenticationInterval{}, errBootstrap
	}
	return value, nil
}

// Poll uses one fresh UID and consumes a cookie before each attempted send.
func (c *NTSCollector) Poll(ctx context.Context, sourceID string) (NTSObservation, error) {
	if err := ctx.Err(); err != nil {
		return NTSObservation{}, err
	}
	source := c.sources[sourceID]
	if source == nil {
		return NTSObservation{}, errSource
	}
	select {
	case source.operation <- struct{}{}:
		defer func() { <-source.operation }()
	default:
		return NTSObservation{}, errConcurrent
	}
	if err := source.udp.checkEligibility(c.tick); err != nil {
		if errors.Is(err, errInterval) && source.session != nil {
			if _, authErr := c.currentSession(ctx, source.session); authErr != nil {
				source.forgetKeys()
				return NTSObservation{}, authErr
			}
		}
		return NTSObservation{}, err
	}
	if err := c.keys(ctx, source); err != nil {
		return NTSObservation{}, err
	}
	session := source.session
	if _, err := c.currentSession(ctx, session); err != nil {
		source.forgetKeys()
		return NTSObservation{}, err
	}
	request, _, err := makeRequest()
	if err != nil {
		return NTSObservation{}, err
	}
	var uid [nts.MinUniqueIdentifierLen]byte
	if _, err := rand.Read(uid[:]); err != nil {
		return NTSObservation{}, err
	}
	cookie := session.cookies[0]
	// Header, UID extension and the fixed AES-SIV authenticator form the base.
	const baseWireBytes = 48 + 36 + 40
	cookieWireBytes := nts.NewCookie(cookie).EncodedSize()
	placeholders := min(maxCookies-len(session.cookies), max(0, (maxPacketBytes-baseWireBytes)/cookieWireBytes-1))
	raw, err := nts.BuildNTSRequest(*request, nts.RequestParams{
		AEAD: ntsAlgorithm, C2S: session.c2s, Cookie: cookie, UniqueID: uid[:], Placeholders: placeholders,
	})
	if err != nil || len(raw) > maxPacketBytes {
		source.forgetKeys()
		return NTSObservation{}, errPacket
	}
	result, err := source.udp.exchange(ctx, session.observation.ntpEndpoint, c.tick, raw, func() (uint64, error) {
		value, err := c.currentSession(ctx, session)
		if err != nil {
			return 0, err
		}
		clear(cookie)
		session.cookies[0] = nil
		session.cookies = session.cookies[1:]
		return min(value.ExpiresTickNS, session.issuedTickNS+ntsLifetimeNS), nil
	})
	if err != nil {
		if errors.Is(err, errBootstrap) || errors.Is(err, errClock) {
			source.forgetKeys()
		}
		return NTSObservation{}, err
	}
	reply, cookies, err := verifyNTSReply(result.Response, request, session.s2c, uid[:])
	if err != nil {
		source.forgetKeys()
		return NTSObservation{}, errPacket
	}
	current, err := c.currentSession(ctx, session)
	if err != nil {
		eraseCookies(cookies)
		source.forgetKeys()
		return NTSObservation{}, err
	}
	if reply.Stratum == 0 {
		eraseCookies(cookies)
		err := source.udp.applyKiss(reply, result.ReceiveAfterTickNS)
		if errors.Is(err, errKissStop) {
			source.forgetKeys()
		}
		return NTSObservation{}, err
	}
	if err := source.addCookies(cookies, placeholders+1); err != nil {
		eraseCookies(cookies)
		source.forgetKeys()
		return NTSObservation{}, errPacket
	}
	result.Reply = *reply
	evidence := session.observation
	return NTSObservation{Exchange: result, KeyEndpoint: evidence.keEndpoint, ServerName: evidence.serverName,
		TLSAuthentication: evidence.atTLS, KeyCompletionAuthentication: evidence.atCompletion, PollAuthentication: current,
		RootDigests: append([][32]byte(nil), evidence.roots...), ChainDigests: append([][32]byte(nil), evidence.chain...),
		KeyReply: bytes.Clone(evidence.reply),
	}, nil
}

func verifyNTSReply(raw []byte, request *protocol.Packet, key, uid []byte) (*protocol.Packet, [][]byte, error) {
	if len(raw) > maxPacketBytes {
		return nil, nil, errPacket
	}
	reply, err := protocol.BytesToPacket(raw)
	if err != nil || !admissibleReplyHeader(reply, request) || len(reply.MAC) != 0 {
		return nil, nil, errPacket
	}
	foundUID := false
	foundAuth := false
	for i, field := range reply.ExtensionFields {
		switch field.Type {
		case protocol.UniqueIdentifier:
			if foundUID || !bytes.Equal(field.Body, uid) {
				return nil, nil, errPacket
			}
			foundUID = true
		case protocol.NTSAuthenticator:
			if i != len(reply.ExtensionFields)-1 {
				return nil, nil, errPacket
			}
			auth, err := nts.ParseAuthenticatorBody(field.Body)
			if err != nil {
				return nil, nil, errPacket
			}
			canonical, err := nts.MarshalAuthenticatorBody(auth.Nonce, auth.Ciphertext)
			if err != nil || !bytes.Equal(canonical, field.Body) {
				return nil, nil, errPacket
			}
			foundAuth = true
		case protocol.NTSCookie, protocol.NTSCookiePlaceholder:
			return nil, nil, errPacket
		}
	}
	encoded, err := reply.Bytes()
	if !foundUID || !foundAuth || err != nil || !bytes.Equal(encoded, raw) {
		return nil, nil, errPacket
	}
	reply, cookies, err := nts.VerifyNTSResponse(raw, ntsAlgorithm, key, uid)
	if err != nil {
		return nil, nil, errPacket
	}
	return reply, cookies, nil
}
