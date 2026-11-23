package collector

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"net"
	"strconv"
	"strings"
	"testing"
	"time"
)

func fixtureProviderAuthentication(t *testing.T) AuthenticationSource {
	t.Helper()
	provider, core := net.Pipe()
	t.Cleanup(func() { provider.Close(); core.Close() })
	digest := "sha256:" + strings.Repeat("a", 64)
	domain := wireObject{"clock_domain_id": "clock_" + digest[7:], "descriptor_digest": digest}
	ref := wireObject{"id": "9966b9ab-efc7-48ba-a195-6e371a8a49d7", "revision": "1", "digest": digest}
	bridge := &providerAuthentication{file: provider, reader: bufio.NewReaderSize(provider, bootstrapLimit+2), bindingDigest: digest, domain: domain}
	go func() {
		defer core.Close()
		reader := bufio.NewReaderSize(core, providerAuthMaximum+1)
		for {
			raw, err := reader.ReadSlice('\n')
			if err != nil {
				return
			}
			request := canonicalObject(raw[:len(raw)-1])
			at, err := nativeTick()
			if request["binding_digest"] != digest || request["type"] != "AUTH_READ" || request["version"] != providerAuthVersion || err != nil {
				return
			}
			sample := wireObject{"acquisition_ref": ref, "source_ref": ref, "policy_ref": ref, "runtime_ref": ref, "runtime_domain_ref": domain,
				"tick_ns": strconv.FormatUint(at, 10), "valid_before_tick_ns": strconv.FormatUint(at+uint64(time.Second), 10),
				"lower_ns": strconv.FormatInt(fixtureUTC.Add(-time.Second).UnixNano(), 10), "upper_ns": strconv.FormatInt(fixtureUTC.Add(time.Second).UnixNano(), 10),
				"monotonic_quantization_ns": "100", "drift_ppb": 1000000}
			reply, err := json.Marshal(wireObject{"binding_digest": digest, "reply_to": request["request_id"], "sample": sample,
				"type": "AUTH_RESULT", "version": providerAuthVersion})
			if err != nil {
				return
			}
			if _, err := core.Write(append(reply, '\n')); err != nil {
				return
			}
		}
	}()
	return bridge.read
}

func TestProviderAuthenticationCurrentInterval(t *testing.T) {
	digest := "sha256:" + strings.Repeat("a", 64)
	domain := wireObject{"clock_domain_id": "clock_" + digest[7:], "descriptor_digest": digest}
	ref := wireObject{"id": "9966b9ab-efc7-48ba-a195-6e371a8a49d7", "revision": "1", "digest": digest}
	sample := wireObject{"acquisition_ref": ref, "source_ref": ref, "policy_ref": ref, "runtime_ref": ref, "runtime_domain_ref": domain,
		"tick_ns": "500", "valid_before_tick_ns": "800", "lower_ns": "1000", "upper_ns": "2000", "monotonic_quantization_ns": "10", "drift_ppb": 1000000}
	frame := wireObject{"binding_digest": digest, "reply_to": "request", "sample": sample, "type": "AUTH_RESULT", "version": providerAuthVersion}
	read := func(id string, sent, received uint64) (AuthenticationInterval, error) {
		t.Helper()
		raw, err := json.Marshal(frame)
		if err != nil {
			t.Fatal(err)
		}
		return readProviderAuthentication(raw, id, digest, domain, sent, received)
	}
	first, err := read("request", 450, 600)
	if err != nil {
		t.Fatal(err)
	}
	if first.Lower.UnixNano() != 1079 || first.Upper.UnixNano() != 2121 ||
		first.ObservedTickNS != 600 || first.SourceReadTickNS != 500 || first.ExpiresTickNS != 800 ||
		first.AcquisitionRef.ID != ref["id"] || first.PolicyRef.Digest != digest || first.SourceRef.ID != ref["id"] {
		t.Fatalf("unexpected protected interval: %+v", first)
	}
	source := func(context.Context) (AuthenticationInterval, error) { return first, nil }
	next, err := authenticationNow(t.Context(), source, func() (uint64, error) { return 650, nil })
	if err != nil || next.Lower.UnixNano() != 1129 || next.Upper.UnixNano() != 2171 || next.SourceReadTickNS != 500 ||
		next.ObservedTickNS != 650 || next.ExpiresTickNS != 800 || next.Binding != first.Binding {
		t.Fatalf("unexpected use-time interval: %+v / %v", next, err)
	}
	if _, err := authenticationNow(t.Context(), source, func() (uint64, error) { return 800, nil }); !errors.Is(err, errBootstrap) {
		t.Fatal("expired interval remained usable")
	}
	for _, test := range []struct {
		id             string
		sent, received uint64
		want           error
	}{
		{"other-request", 450, 600, errProviderLink}, {"request", 501, 600, errProviderLink},
		{"request", 450, 499, errProviderLink}, {"request", 450, 800, errBootstrap},
	} {
		if _, err := read(test.id, test.sent, test.received); !errors.Is(err, test.want) {
			t.Errorf("%+v: %v", test, err)
		}
	}
	sample["runtime_domain_ref"] = wireObject{"clock_domain_id": "other", "descriptor_digest": digest}
	if _, err := read("request", 450, 600); !errors.Is(err, errProviderLink) {
		t.Fatal("accepted unrelated clock domain")
	}
	frame["sample"] = nil
	if _, err := read("request", 450, 600); !errors.Is(err, errBootstrap) {
		t.Fatal("unavailable reply granted authentication")
	}
}
