package collector

import (
	"bytes"
	"context"
	"errors"
	"net"
	"net/netip"
	"testing"
	"time"

	"github.com/facebook/time/ntp/protocol"
)

func localSource(t *testing.T) (*net.UDPConn, *TrustedNetworkCollector) {
	t.Helper()
	server, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = server.Close() })
	collector, err := NewTrustedNetworkCollector(map[string]netip.AddrPort{
		"local": server.LocalAddr().(*net.UDPAddr).AddrPort(),
	})
	if err != nil {
		t.Fatal(err)
	}
	return server, collector
}

func oneReply(server *net.UDPConn, reply func([]byte) []byte) <-chan error {
	result := make(chan error, 1)
	go func() {
		var raw [protocol.PacketSizeBytes + 1]byte
		n, peer, err := server.ReadFromUDP(raw[:])
		if err == nil {
			_, err = server.WriteToUDP(reply(raw[:n]), peer)
		}
		result <- err
	}()
	return result
}

func makeReply(request []byte) []byte {
	reply := make([]byte, protocol.PacketSizeBytes)
	reply[0], reply[1] = serverSettings, 1
	reply[19], reply[35], reply[43] = 1, 2, 3
	copy(reply[24:32], request[40:48])
	return reply
}

func TestNativeExchangeRetainsRawDatagramsAndTicks(t *testing.T) {
	server, collector := localSource(t)
	sent := oneReply(server, makeReply)
	before, err := nativeTick()
	if err != nil {
		t.Fatal(err)
	}
	result, err := collector.Poll(t.Context(), "local")
	if err != nil {
		t.Fatal(err)
	}
	after, err := nativeTick()
	if err != nil {
		t.Fatal(err)
	}
	if err := <-sent; err != nil {
		t.Fatal(err)
	}
	if result.Endpoint != server.LocalAddr().(*net.UDPAddr).AddrPort() ||
		result.SendBeforeTickNS < before || result.ReceiveAfterTickNS < result.SendBeforeTickNS ||
		result.ReceiveAfterTickNS > after || result.ReceiveAfterTickNS-result.SendBeforeTickNS >= uint64(pollTimeout) {
		t.Fatalf("unexpected native exchange bracket: %+v", result)
	}
	t.Logf("native bracket: %d %d", result.SendBeforeTickNS, result.ReceiveAfterTickNS)
	if len(result.Request) != 48 || result.Request[0] != clientSettings ||
		bytes.Equal(result.Request[40:], make([]byte, 8)) ||
		!bytes.Equal(result.Response, makeReply(result.Request)) || result.Reply.RxTimeSec != 2 {
		t.Fatalf("unexpected exchange bytes: %+v", result)
	}
	if _, err := collector.Poll(t.Context(), "local"); !errors.Is(err, errInterval) {
		t.Fatalf("rapid second poll: %v", err)
	}
}

func TestPacketValidationRejectsTrailingDataAndBadClockFields(t *testing.T) {
	request, raw, err := makeRequest()
	if err != nil {
		t.Fatal(err)
	}
	for _, invalid := range []struct {
		name   string
		change func([]byte) []byte
	}{
		{"trailing byte", func(b []byte) []byte { return append(b, 0) }},
		{"short header", func(b []byte) []byte { return b[:47] }},
		{"wrong correlation", func(b []byte) []byte { b[31] ^= 1; return b }},
		{"wrong version", func(b []byte) []byte { b[0] = 3<<3 | 4; return b }},
		{"wrong mode", func(b []byte) []byte { b[0] = 4<<3 | 5; return b }},
		{"leap warning", func(b []byte) []byte { b[0] |= 1 << 6; return b }},
		{"unmatched kiss of death", func(b []byte) []byte { b[1] = 0; b[31] ^= 1; return b }},
		{"stratum too high", func(b []byte) []byte { b[1] = 16; return b }},
		{"zero reference", func(b []byte) []byte { clear(b[16:24]); return b }},
		{"zero receive", func(b []byte) []byte { clear(b[32:40]); return b }},
		{"zero transmit", func(b []byte) []byte { clear(b[40:48]); return b }},
	} {
		t.Run(invalid.name, func(t *testing.T) {
			if _, err := parseReply(invalid.change(makeReply(raw)), request); !errors.Is(err, errPacket) {
				t.Fatalf("unexpected result: %v", err)
			}
		})
	}
}

func TestPollDropsOversizedDatagramAndRetainsRateLimit(t *testing.T) {
	server, collector := localSource(t)
	sent := oneReply(server, func(request []byte) []byte {
		return append(makeReply(request), make([]byte, maxPacketBytes+1-48)...)
	})
	if _, err := collector.Poll(t.Context(), "local"); !errors.Is(err, errPacket) {
		t.Fatalf("oversized reply: %v", err)
	}
	if err := <-sent; err != nil {
		t.Fatal(err)
	}
	if _, err := collector.Poll(t.Context(), "local"); !errors.Is(err, errInterval) {
		t.Fatalf("rate limit after malformed packet: %v", err)
	}
}

func TestTrustedNetworkKissControlsTheSourceWithoutPublishingTime(t *testing.T) {
	server, collector := localSource(t)
	now := uint64(100)
	collector.tick = func() (uint64, error) { return now, nil }
	for index, test := range []struct {
		exponent int8
		wait     uint64
	}{
		{10, uint64(1024 * time.Second)}, {-1, uint64(2048 * time.Second)}, {4, 0},
	} {
		done := oneReply(server, func(request []byte) []byte {
			reply := makeReply(request)
			reply[0] |= 3 << 6
			reply[1], reply[2] = 0, byte(test.exponent)
			copy(reply[12:16], "RATE")
			return reply
		})
		result, err := collector.Poll(t.Context(), "local")
		if failure := <-done; failure != nil {
			t.Fatal(failure)
		}
		var kiss KissError
		if !errors.As(err, &kiss) || kiss.Code != kissRateCode || kiss.ObservedTickNS != now || kiss.WaitNS != test.wait || result.Response != nil {
			t.Fatalf("unexpected server control outcome: %+v / %v", result, err)
		}
		if test.wait == 0 {
			now += maxKissWaitNS
			if _, err := collector.Poll(t.Context(), "local"); err != kiss {
				t.Fatal("stopped source was readmitted")
			}
			break
		}
		now += test.wait - 1
		if _, err := collector.Poll(t.Context(), "local"); !errors.Is(err, errInterval) {
			t.Fatalf("poll was not deferred to the requested interval: %v", err)
		}
		now++
		if index == 0 {
			good := oneReply(server, makeReply)
			if _, err := collector.Poll(t.Context(), "local"); err != nil {
				t.Fatal(err)
			}
			if failure := <-good; failure != nil {
				t.Fatal(failure)
			}
			now += test.wait - 1
			if _, err := collector.Poll(t.Context(), "local"); !errors.Is(err, errInterval) {
				t.Fatalf("a successful exchange cleared the server's poll interval: %v", err)
			}
			now++
		}
	}
}

func TestExchangeRetainsTheOriginalSendAuthorizationDeadline(t *testing.T) {
	server, _ := localSource(t)
	endpoint := server.LocalAddr().(*net.UDPAddr).AddrPort()
	_, raw, err := makeRequest()
	if err != nil {
		t.Fatal(err)
	}
	source := sourceState{endpoint: endpoint}
	ticks := []uint64{100, 200}
	done := oneReply(server, makeReply)
	tick := func() (uint64, error) {
		value := ticks[0]
		ticks = ticks[1:]
		return value, nil
	}
	result, err := source.exchange(t.Context(), endpoint, tick, raw, func() (uint64, error) { return 200, nil })
	if failure := <-done; failure != nil {
		t.Fatal(failure)
	}
	if !errors.Is(err, errDeadline) || result.Response != nil || !source.sent || source.lastSend != 100 {
		t.Fatalf("expired response was admitted or the send refunded: %+v / %v", result, err)
	}
}

func TestPollCancelsWithoutStartingParallelExchange(t *testing.T) {
	server, collector := localSource(t)
	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	poll := make(chan error, 1)
	go func() {
		_, err := collector.Poll(ctx, "local")
		poll <- err
	}()
	if err := server.SetReadDeadline(time.Now().Add(pollTimeout)); err != nil {
		t.Fatal(err)
	}
	var request [protocol.PacketSizeBytes]byte
	if _, _, err := server.ReadFromUDP(request[:]); err != nil {
		t.Fatal(err)
	}
	if _, err := collector.Poll(t.Context(), "local"); !errors.Is(err, errConcurrent) {
		t.Fatalf("parallel poll: %v", err)
	}
	cancel()
	select {
	case err := <-poll:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("cancelled poll: %v", err)
		}
	case <-time.After(pollTimeout):
		t.Fatal("cancelled poll left the socket waiting")
	}
}

func TestNativeDeadlineIsExclusiveAndRegressedClockFails(t *testing.T) {
	for _, sample := range []struct {
		receive uint64
		want    error
	}{{99, errClock}, {100 + uint64(pollTimeout), errDeadline}} {
		server, collector := localSource(t)
		calls := 0
		collector.tick = func() (uint64, error) {
			calls++
			if calls == 1 {
				return 100, nil
			}
			return sample.receive, nil
		}
		sent := oneReply(server, makeReply)
		if _, err := collector.Poll(t.Context(), "local"); !errors.Is(err, sample.want) {
			t.Fatalf("clock result at tick %d: %v", sample.receive, err)
		}
		if err := <-sent; err != nil {
			t.Fatal(err)
		}
	}
}
