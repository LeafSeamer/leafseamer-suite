package collector

import (
	"bytes"
	"context"
	"encoding/base64"
	"net"
	"strings"
	"testing"
	"time"

	"github.com/facebook/time/ntp/ntske"
)

func TestProviderStoredConfirmationMatchesRetainedCapture(t *testing.T) {
	digest := "sha256:" + strings.Repeat("a", 64)
	ref := wireObject{"id": "poll.test", "digest": digest}
	saved := retainedProviderPoll{poll: providerPoll{id: "poll.test", ref: ref, attempt: "attempt.test", sequence: 1},
		digest: digest, m1: "100", m4: "101"}
	retained := map[string]retainedProviderPoll{"poll.test": saved}
	receipt := wireObject{"attempt_id": "attempt.test", "capture_ref": wireObject{"id": "capture.test",
		"revision": "1", "digest": digest}, "m1_tick_ns": "100", "m4_tick_ns": "101", "plaintext_digest": digest, "poll_ref": ref}
	frame := wireObject{"version": providerLinkVersion, "type": "POLL_STORED", "binding_digest": digest,
		"poll_sequence": "1", "receipt": receipt}
	for _, field := range []string{"plaintext_digest", "m4_tick_ns", "attempt_id"} {
		original := receipt[field]
		receipt[field] = "changed"
		if _, _, err := acceptProviderStored(frame, digest, retained); err == nil {
			t.Fatalf("confirmation with wrong %s accepted", field)
		}
		receipt[field] = original
	}
	id, encoded, err := acceptProviderStored(frame, digest, retained)
	if err != nil || id != "poll.test" {
		t.Fatalf("matching receipt was refused: %v", err)
	}
	ack := canonicalObject(encoded[:len(encoded)-1])
	if ack["type"] != "POLL_STORED_ACK" || !sameWire(ack["receipt"], receipt) {
		t.Fatal("confirmation changed the durable receipt")
	}
}

func TestProviderStoredControlRequiresTheExactRetainedDecision(t *testing.T) {
	binding := "sha256:" + strings.Repeat("a", 64)
	decision := "sha256:" + strings.Repeat("b", 64)
	ref := wireObject{"id": "poll.test", "digest": binding}
	retained := map[string]retainedProviderPoll{"poll.test": {
		poll: providerPoll{id: "poll.test", ref: ref, attempt: "attempt.test", sequence: 1}, controlDigest: decision,
	}}
	receipt := wireObject{"attempt_id": "attempt.test", "poll_ref": ref, "control_digest": binding,
		"control_ref": wireObject{"id": "poll.test", "revision": "1", "digest": binding}}
	frame := wireObject{"version": providerLinkVersion, "type": "POLL_CONTROL_STORED", "binding_digest": binding,
		"poll_sequence": "1", "receipt": receipt}
	if _, _, err := acceptProviderStored(frame, binding, retained); err == nil {
		t.Fatal("a different decision was accepted")
	}
	receipt["control_digest"] = decision
	controlRef := receipt["control_ref"].(wireObject)
	controlRef["id"] = "poll.other"
	if _, _, err := acceptProviderStored(frame, binding, retained); err == nil {
		t.Fatal("a different control reference was accepted")
	}
	controlRef["id"] = "poll.test"
	frame["poll_sequence"] = "2"
	if _, _, err := acceptProviderStored(frame, binding, retained); err == nil {
		t.Fatal("a different poll sequence was accepted")
	}
	frame["poll_sequence"] = "1"
	_, encoded, err := acceptProviderStored(frame, binding, retained)
	if err != nil {
		t.Fatal(err)
	}
	ack := canonicalObject(encoded[:len(encoded)-1])
	if ack["type"] != "POLL_CONTROL_STORED_ACK" || !sameWire(ack["receipt"], receipt) {
		t.Fatal("acknowledgement changed the stored decision")
	}
}

func TestProviderPollUsesTheBoundNTSConfiguration(t *testing.T) {
	udp, _ := localSource(t)
	certificate, root := fixtureTLS(t)
	tcp := fixtureKE(t)
	config := testNTSConfig(t, tcp, udp, root)
	configuration, ok := wireNTSConfig(wireObject{
		"authentication": "nts", "key_endpoint": config.KeyEndpoint.String(), "server_name": config.ServerName,
		"root_der":       []any{base64.RawURLEncoding.EncodeToString(root)},
		"default_target": wireObject{"name": config.DefaultTarget.Name, "port": float64(config.DefaultTarget.Port)},
		"targets": []any{wireObject{"name": config.DefaultTarget.Name, "port": float64(config.DefaultTarget.Port),
			"endpoint": config.Targets[config.DefaultTarget].String()}},
	})
	if !ok {
		t.Fatal("bound NTS configuration refused")
	}
	initial, next := bytes.Repeat([]byte{1}, 32), bytes.Repeat([]byte{2}, 32)
	records := keRecords(initial)
	expected, err := ntske.MarshalRecords(records)
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() {
		c2s, s2c, err := serveKE(tcp, certificate, records)
		if err == nil {
			err = serveAuthenticatedUDP(udp, initial, next, c2s, s2c)
		}
		done <- err
	}()
	start, err := nativeTick()
	if err != nil {
		t.Fatal(err)
	}
	poll := providerPoll{id: "test", start: start, end: start + uint64(3*time.Second), nts: &configuration}
	result := runProviderPoll(t.Context(), poll, fixtureProviderAuthentication(t))
	candidate, _ := result["candidate"].(map[string]any)
	if result["status"] != "candidate" || candidate["key_reply_digest"] != hashWire(expected) ||
		candidate["key_reply"] != base64.RawURLEncoding.EncodeToString(expected) ||
		candidate["endpoint"] != config.Targets[config.DefaultTarget].String() {
		t.Fatal("bound NTS poll did not return the associated candidate")
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}

func TestProviderPollCannotReadAuthorityAtItsExpiredDeadline(t *testing.T) {
	udp, _ := localSource(t)
	end, err := nativeTick()
	if err != nil {
		t.Fatal(err)
	}
	poll := providerPoll{id: "expired", start: 0, end: end, endpoint: numericEndpoint(udp.LocalAddr().(*net.UDPAddr).AddrPort())}
	read := func(context.Context) (AuthenticationInterval, error) {
		t.Fatal("authorization read started for an already expired poll")
		return AuthenticationInterval{}, errBootstrap
	}
	if result := runProviderPoll(t.Context(), poll, read); result["status"] != "unavailable" || result["candidate"] != nil {
		t.Fatal("expired poll supplied a candidate")
	}
}
