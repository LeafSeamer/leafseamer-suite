package collector

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/netip"
	"strconv"
	"time"
)

const providerCaptureMaximum = 98304

func serveProviderPolls(ctx context.Context, auth *providerAuthentication, serviceBoot string) error {
	retained := make(map[string]retainedProviderPoll)
	var lastSequence uint64
	defer func() {
		for _, original := range retained {
			clear(original.frame)
		}
	}()
	for {
		line, err := auth.reader.ReadSlice('\n')
		if err != nil || auth.reader.Buffered() != 0 {
			return errProviderLink
		}
		request := canonicalObject(line[:len(line)-1])
		if request["type"] == "POLL_STORED" || request["type"] == "POLL_CONTROL_STORED" {
			id, ack, err := acceptProviderStored(request, auth.bindingDigest, retained)
			if err != nil {
				return err
			}
			clear(retained[id].frame)
			delete(retained, id)
			if err := writeProviderResult(auth, ack); err != nil {
				return err
			}
			continue
		}
		poll, err := parseProviderPoll(request, auth.bindingDigest, serviceBoot)
		if _, used := retained[poll.id]; err != nil || used || len(retained) >= maxSources || poll.sequence != lastSequence+1 {
			return errProviderLink
		}
		lastSequence = poll.sequence
		reply := runProviderPoll(ctx, poll, auth.read)
		reply["version"], reply["type"], reply["binding_digest"] = providerLinkVersion, "POLL_RESULT", auth.bindingDigest
		reply["attempt_id"], reply["poll_ref"] = poll.attempt, poll.ref
		reply["poll_sequence"] = strconv.FormatUint(poll.sequence, 10)
		encoded, err := json.Marshal(reply)
		if err != nil || len(encoded) > providerCaptureMaximum {
			return errProviderLink
		}
		saved := retainedProviderPoll{poll: poll, frame: append(encoded, '\n')}
		if candidate, ok := reply["candidate"].(map[string]any); ok {
			plaintext, err := json.Marshal(candidate)
			if err != nil {
				return errProviderLink
			}
			saved.digest = hashWire(plaintext)
			clear(plaintext)
			saved.m1, _ = candidate["m1_tick_ns"].(string)
			saved.m4, _ = candidate["m4_tick_ns"].(string)
		}
		if control, ok := reply["control"].(map[string]any); ok && poll.persistentControl {
			encoded, err := json.Marshal(control)
			if err != nil {
				return errProviderLink
			}
			saved.controlDigest = hashWire(encoded)
		}
		retained[poll.id] = saved
		if err := writeProviderResult(auth, saved.frame); err != nil {
			return err
		}
	}
}

type retainedProviderPoll struct {
	poll           providerPoll
	frame          []byte
	digest, m1, m4 string
	controlDigest  string
}

func acceptProviderStored(frame wireObject, binding string, retained map[string]retainedProviderPoll) (string, []byte, error) {
	receipt, _ := frame["receipt"].(map[string]any)
	ref, _ := receipt["poll_ref"].(map[string]any)
	id, _ := ref["id"].(string)
	sequence, sequenceOK := bootstrapUint(frame["poll_sequence"])
	saved, present := retained[id]
	if !fields(frame, "binding_digest poll_sequence receipt type version") || frame["version"] != providerLinkVersion ||
		frame["binding_digest"] != binding || !present || !sequenceOK || sequence != saved.poll.sequence ||
		!sameWire(ref, saved.poll.ref) || receipt["attempt_id"] != saved.poll.attempt {
		return "", nil, errProviderLink
	}
	switch frame["type"] {
	case "POLL_STORED":
		_, captureOK := authReference(receipt["capture_ref"])
		if saved.digest == "" || !captureOK || !fields(receipt, "attempt_id capture_ref m1_tick_ns m4_tick_ns plaintext_digest poll_ref") ||
			receipt["m1_tick_ns"] != saved.m1 || receipt["m4_tick_ns"] != saved.m4 || receipt["plaintext_digest"] != saved.digest {
			return "", nil, errProviderLink
		}
		frame["type"] = "POLL_STORED_ACK"
	case "POLL_CONTROL_STORED":
		controlRef, controlOK := authReference(receipt["control_ref"])
		if saved.controlDigest == "" || !controlOK || !fields(receipt, "attempt_id control_digest control_ref poll_ref") ||
			controlRef.ID != id || controlRef.Revision != "1" || receipt["control_digest"] != saved.controlDigest {
			return "", nil, errProviderLink
		}
		frame["type"] = "POLL_CONTROL_STORED_ACK"
	default:
		return "", nil, errProviderLink
	}
	ack, err := json.Marshal(frame)
	if err != nil || len(ack) > providerAuthMaximum {
		return "", nil, errProviderLink
	}
	return id, append(ack, '\n'), nil
}

func writeProviderResult(auth *providerAuthentication, frame []byte) error {
	if err := auth.file.SetDeadline(time.Now().Add(providerAuthTimeout)); err != nil {
		return err
	}
	if n, err := auth.file.Write(frame); err != nil || n != len(frame) {
		return errProviderLink
	}
	return auth.file.SetDeadline(time.Time{})
}

type providerPoll struct {
	id, attempt       string
	ref               wireObject
	start, end        uint64
	sequence          uint64
	endpoint          netip.AddrPort
	nts               *NTSSourceConfig
	minimum           uint64
	persistentControl bool
}

func parseProviderPoll(frame wireObject, bindingDigest, serviceBoot string) (providerPoll, error) {
	reservation, _ := frame["reservation"].(map[string]any)
	attempt, _ := frame["attempt"].(map[string]any)
	ref, _ := attempt["poll_ref"].(map[string]any)
	network, _ := frame["network"].(map[string]any)
	authorization, _ := reservation["authorization"].(map[string]any)
	endpointRef, endpointOK := authReference(authorization["endpoint_ref"])
	pollID, _ := reservation["poll_id"].(string)
	attemptID, _ := attempt["attempt_id"].(string)
	_, acquisitionOK := authReference(attempt["acquisition_ref"])
	issued, issuedOK := bootstrapUint(reservation["issued_tick_ns"])
	expires, expiresOK := bootstrapUint(reservation["expires_tick_ns"])
	start, startOK := bootstrapUint(attempt["attempted_tick_ns"])
	end, endOK := bootstrapUint(attempt["valid_before_tick_ns"])
	sequence, sequenceOK := bootstrapUint(frame["poll_sequence"])
	original, originalErr := json.Marshal(reservation)
	config, configErr := json.Marshal(network)
	reservationFields := "acquisition_ref authorization expires_tick_ns issued_tick_ns poll_id reserved_bytes runtime_digest service_boot_id source_slot"
	configuredMinimum, configuredOK := bootstrapUint(authorization["minimum_poll_interval_ns"])
	var minimum uint64
	_, persistentControl := reservation["effective_poll_interval_ns"]
	if persistentControl {
		var minimumOK bool
		minimum, minimumOK = bootstrapUint(reservation["effective_poll_interval_ns"])
		if !minimumOK || !configuredOK || configuredMinimum < pollIntervalNS || minimum < configuredMinimum {
			return providerPoll{}, errProviderLink
		}
		reservationFields = "acquisition_ref authorization effective_poll_interval_ns expires_tick_ns issued_tick_ns poll_id reserved_bytes runtime_digest service_boot_id source_slot"
	}
	if !fields(frame, "attempt binding_digest network poll_sequence reservation type version") || frame["type"] != "POLL" ||
		frame["version"] != providerLinkVersion || frame["binding_digest"] != bindingDigest ||
		!fields(reservation, reservationFields) ||
		reservation["service_boot_id"] != serviceBoot || reservation["runtime_digest"] != bindingDigest ||
		!fields(attempt, "acquisition_ref attempt_id attempted_tick_ns expires_tick_ns poll_ref runtime_digest valid_before_tick_ns") ||
		attempt["runtime_digest"] != bindingDigest || !ids(attempt, "attempt_id") || !ids(reservation, "poll_id source_slot") ||
		!fields(ref, "digest id") || ref["id"] != pollID || originalErr != nil || ref["digest"] != hashWire(original) ||
		!issuedOK || !expiresOK || !startOK || !endOK || start < issued || end <= start || end > expires ||
		attempt["expires_tick_ns"] != reservation["expires_tick_ns"] || !acquisitionOK ||
		!endpointOK || configErr != nil || endpointRef.Digest != hashWire(config) || !sequenceOK || sequence == 0 {
		return providerPoll{}, errProviderLink
	}
	poll := providerPoll{id: pollID, attempt: attemptID, ref: ref, start: start, end: end, sequence: sequence,
		minimum: minimum, persistentControl: persistentControl}
	switch network["authentication"] {
	case "trusted_network":
		poll.endpoint = wireEndpoint(network["endpoint"])
		if !fields(network, "authentication endpoint") || !poll.endpoint.IsValid() {
			return providerPoll{}, errProviderLink
		}
	case "nts":
		config, ok := wireNTSConfig(network)
		if !ok {
			return providerPoll{}, errProviderLink
		}
		poll.nts = &config
	default:
		return providerPoll{}, errProviderLink
	}
	return poll, nil
}

func wireEndpoint(value any) netip.AddrPort {
	text, _ := value.(string)
	endpoint, err := netip.ParseAddrPort(text)
	endpoint = numericEndpoint(endpoint)
	if err != nil || endpoint.String() != text {
		return netip.AddrPort{}
	}
	return endpoint
}

func wireNTPTarget(object wireObject) NTPTarget {
	name, _ := object["name"].(string)
	port, ok := object["port"].(float64)
	if name == "" || !ok || port < 1 || port > 65535 || float64(uint16(port)) != port {
		return NTPTarget{}
	}
	return NTPTarget{Name: name, Port: uint16(port)}
}

func wireNTSConfig(object wireObject) (NTSSourceConfig, bool) {
	var config NTSSourceConfig
	roots, _ := object["root_der"].([]any)
	targets, _ := object["targets"].([]any)
	preferred, _ := object["default_target"].(map[string]any)
	if !fields(object, "authentication default_target key_endpoint root_der server_name targets") ||
		len(roots) < 1 || len(roots) > 8 || len(targets) < 1 || len(targets) > 16 || !fields(preferred, "name port") {
		return config, false
	}
	config.KeyEndpoint = wireEndpoint(object["key_endpoint"])
	config.ServerName, _ = object["server_name"].(string)
	config.DefaultTarget = wireNTPTarget(preferred)
	config.Targets = make(map[NTPTarget]netip.AddrPort, len(targets))
	for _, item := range roots {
		text, _ := item.(string)
		der, err := base64.RawURLEncoding.Strict().DecodeString(text)
		if err != nil || len(der) == 0 || base64.RawURLEncoding.EncodeToString(der) != text {
			return config, false
		}
		config.RootDER = append(config.RootDER, der)
	}
	for _, item := range targets {
		value, _ := item.(map[string]any)
		target, endpoint := wireNTPTarget(value), wireEndpoint(value["endpoint"])
		if !fields(value, "endpoint name port") || target.Port == 0 || !endpoint.IsValid() || config.Targets[target].IsValid() {
			return config, false
		}
		config.Targets[target] = endpoint
	}
	return config, config.KeyEndpoint.IsValid() && config.Targets[config.DefaultTarget].IsValid()
}

func runProviderPoll(ctx context.Context, poll providerPoll, auth AuthenticationSource) wireObject {
	reply := wireObject{"status": "unavailable", "candidate": nil, "control": nil}
	now, err := nativeTick()
	if err != nil || now < poll.start || now >= poll.end || poll.end-now > uint64(5*time.Second) {
		return reply
	}
	ctx, cancel := context.WithTimeout(ctx, time.Duration(poll.end-now))
	defer cancel()
	read := func(ctx context.Context) (AuthenticationInterval, error) {
		sample, err := auth(ctx)
		sample.ExpiresTickNS = min(sample.ExpiresTickNS, poll.end)
		return sample, err
	}
	var result Exchange
	var keyReply, keyReplyDigest any
	if poll.nts == nil {
		collector, createErr := NewTrustedNetworkCollector(map[string]netip.AddrPort{poll.id: poll.endpoint})
		if createErr != nil {
			return reply
		}
		collector.sources[poll.id].minimum = poll.minimum
		result, err = collector.poll(ctx, poll.id, func() (uint64, error) {
			sample, err := authenticationNow(ctx, read, nativeTick)
			return sample.ExpiresTickNS, err
		})
	} else {
		collector, createErr := NewNTSCollector(map[string]NTSSourceConfig{poll.id: *poll.nts}, read)
		if createErr != nil {
			return reply
		}
		collector.sources[poll.id].udp.minimum = poll.minimum
		defer collector.sources[poll.id].forgetKeys()
		var observed NTSObservation
		observed, err = collector.Poll(ctx, poll.id)
		result = observed.Exchange
		if err == nil {
			keyReply = base64.RawURLEncoding.EncodeToString(observed.KeyReply)
			keyReplyDigest = hashWire(observed.KeyReply)
		}
		clear(observed.KeyReply)
	}
	var kiss KissError
	switch {
	case errors.As(err, &kiss):
		reply["status"] = "control"
		reply["control"] = wireObject{"code": kiss.Code, "observed_tick_ns": strconv.FormatUint(kiss.ObservedTickNS, 10),
			"wait_ns": strconv.FormatUint(kiss.WaitNS, 10)}
	case errors.Is(err, errBootstrap) || errors.Is(err, errClock) || errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded):
	case err != nil:
		reply["status"] = "failed"
	default:
		reply["status"] = "candidate"
		reply["candidate"] = wireObject{"endpoint": result.Endpoint.String(), "m1_tick_ns": strconv.FormatUint(result.SendBeforeTickNS, 10),
			"m4_tick_ns": strconv.FormatUint(result.ReceiveAfterTickNS, 10), "key_reply": keyReply, "key_reply_digest": keyReplyDigest,
			"request": base64.RawURLEncoding.EncodeToString(result.Request), "response": base64.RawURLEncoding.EncodeToString(result.Response)}
	}
	return reply
}
