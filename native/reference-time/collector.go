// Package collector receives reference-clock observations for later qualification by the service.
package collector

import (
	"context"
	"crypto/rand"
	"encoding/binary"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"sync"
	"time"

	"github.com/facebook/time/ntp/protocol"
)

const (
	pollIntervalNS = uint64(16 * time.Second)
	pollTimeout    = 2 * time.Second
	maxKissWaitNS  = uint64(time.Hour)
	maxPacketBytes = 1232
	maxSources     = 4
	clientSettings = 4<<3 | 3
	serverSettings = 4<<3 | 4
	kissRateCode   = 0x52415445 // RATE
)

var (
	errSource     = errors.New("reference source unavailable")
	errConcurrent = errors.New("reference poll already active")
	errInterval   = errors.New("reference poll interval has not elapsed")
	errKissRate   = errors.New("reference server requested a longer poll interval")
	errKissStop   = errors.New("reference server requires source review")
	errClock      = errors.New("reference elapsed clock unavailable or regressed")
	errDeadline   = errors.New("reference poll deadline reached")
	errPacket     = errors.New("reference reply is inadmissible")
)

// Exchange is a bounded observation of raw datagrams and their local elapsed-clock bracket.
// It carries no assertion about the server's identity, UTC accuracy, or clock qualification.
type Exchange struct {
	Endpoint           netip.AddrPort
	SendBeforeTickNS   uint64
	ReceiveAfterTickNS uint64
	Request            []byte
	Response           []byte
	Reply              protocol.Packet
}

// KissError records a correlated stop or backoff without admitting a time sample.
// A zero wait means that the source requires review.
type KissError struct {
	Code           uint32
	ObservedTickNS uint64
	WaitNS         uint64
}

func (k KissError) Error() string { return k.Unwrap().Error() }

func (k KissError) Unwrap() error {
	if k.WaitNS == 0 {
		return errKissStop
	}
	return errKissRate
}

type sourceState struct {
	endpoint netip.AddrPort
	mu       sync.Mutex
	inFlight bool
	lastSend uint64
	sent     bool
	kiss     *KissError
	minimum  uint64
}

// TrustedNetworkCollector polls fixed IP endpoints from the service's source configuration.
type TrustedNetworkCollector struct {
	sources map[string]*sourceState
	tick    func() (uint64, error)
}

func NewTrustedNetworkCollector(endpoints map[string]netip.AddrPort) (*TrustedNetworkCollector, error) {
	if len(endpoints) == 0 || len(endpoints) > maxSources {
		return nil, errSource
	}
	sources := make(map[string]*sourceState, len(endpoints))
	seen := make(map[netip.AddrPort]bool, len(endpoints))
	for id, endpoint := range endpoints {
		endpoint = numericEndpoint(endpoint)
		if id == "" || !endpoint.IsValid() || seen[endpoint] {
			return nil, errSource
		}
		seen[endpoint] = true
		sources[id] = &sourceState{endpoint: endpoint}
	}
	return &TrustedNetworkCollector{sources: sources, tick: nativeTick}, nil
}

func numericEndpoint(endpoint netip.AddrPort) netip.AddrPort {
	addr := endpoint.Addr().Unmap()
	if !addr.IsValid() || addr.IsUnspecified() || addr.IsMulticast() ||
		(addr.Is6() && addr.IsLinkLocalUnicast() && addr.Zone() == "") || endpoint.Port() == 0 {
		return netip.AddrPort{}
	}
	return netip.AddrPortFrom(addr, endpoint.Port())
}

func (s *sourceState) begin(tick func() (uint64, error)) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.inFlight {
		return errConcurrent
	}
	if err := s.checkEligibility(tick); err != nil {
		return err
	}
	s.inFlight = true
	return nil
}

func (s *sourceState) finish() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.inFlight = false
}

func (s *sourceState) checkEligibility(tick func() (uint64, error)) error {
	if s.kiss != nil && s.kiss.WaitNS == 0 {
		return *s.kiss
	}
	if !s.sent {
		return nil
	}
	now, err := tick()
	if err != nil {
		return errClock
	}
	return s.checkInterval(now)
}

func (s *sourceState) checkInterval(now uint64) error {
	if now < s.lastSend || s.kiss != nil && now < s.kiss.ObservedTickNS {
		return errClock
	}
	minimum := max(pollIntervalNS, s.minimum)
	if s.kiss != nil {
		minimum = max(minimum, s.kiss.WaitNS)
		if now-s.kiss.ObservedTickNS < s.kiss.WaitNS {
			return errInterval
		}
	}
	if s.sent && now-s.lastSend < minimum {
		return errInterval
	}
	return nil
}

// Only called while holding the poll slot and after origin and transport checks.
func (s *sourceState) applyKiss(reply *protocol.Packet, received uint64) error {
	kiss := KissError{Code: reply.ReferenceID, ObservedTickNS: received}
	priorWait := max(pollIntervalNS, s.minimum)
	if s.kiss != nil {
		priorWait = max(priorWait, s.kiss.WaitNS)
	}
	// Poll is a signed base-2 exponent in seconds. 2^12 already exceeds one hour.
	if reply.ReferenceID == kissRateCode && reply.Poll <= 11 && priorWait <= maxKissWaitNS/2 {
		wait := 2 * priorWait
		if reply.Poll >= 4 {
			wait = max(wait, uint64(time.Second)<<reply.Poll)
		}
		if wait <= maxKissWaitNS {
			kiss.WaitNS = wait
		}
	}
	s.kiss = &kiss
	return kiss
}

func makeRequest() (*protocol.Packet, []byte, error) {
	var correlation [8]byte
	if _, err := rand.Read(correlation[:]); err != nil {
		return nil, nil, err
	}
	request := &protocol.Packet{
		Settings:   clientSettings,
		TxTimeSec:  binary.BigEndian.Uint32(correlation[:4]),
		TxTimeFrac: binary.BigEndian.Uint32(correlation[4:]),
	}
	if request.TxTimeSec == 0 && request.TxTimeFrac == 0 {
		return nil, nil, errPacket
	}
	raw, err := request.Bytes()
	return request, raw, err
}

func parseReply(raw []byte, request *protocol.Packet) (*protocol.Packet, error) {
	// The trusted-network policy admits the 48-byte header only.
	if len(raw) != protocol.PacketSizeBytes {
		return nil, errPacket
	}
	reply, err := protocol.BytesToPacket(raw)
	if err != nil || !admissibleReplyHeader(reply, request) {
		return nil, errPacket
	}
	return reply, nil
}

func admissibleReplyHeader(reply, request *protocol.Packet) bool {
	if reply.Settings&0x3f != serverSettings ||
		reply.OrigTimeSec != request.TxTimeSec || reply.OrigTimeFrac != request.TxTimeFrac {
		return false
	}
	if reply.Stratum == 0 {
		return true
	}
	return reply.Settings == serverSettings && reply.Stratum <= 15 && (reply.RefTimeSec != 0 || reply.RefTimeFrac != 0) &&
		(reply.RxTimeSec != 0 || reply.RxTimeFrac != 0) &&
		(reply.TxTimeSec != 0 || reply.TxTimeFrac != 0)
}

// Poll performs a single non-retried UDP exchange on the socket connected to the fixed source.
func (c *TrustedNetworkCollector) Poll(ctx context.Context, sourceID string) (Exchange, error) {
	return c.poll(ctx, sourceID, nil)
}

func (c *TrustedNetworkCollector) poll(ctx context.Context, sourceID string, beforeSend func() (uint64, error)) (Exchange, error) {
	if err := ctx.Err(); err != nil {
		return Exchange{}, err
	}
	source := c.sources[sourceID]
	if source == nil {
		return Exchange{}, errSource
	}
	if err := source.begin(c.tick); err != nil {
		return Exchange{}, err
	}
	defer source.finish()
	request, outgoing, err := makeRequest()
	if err != nil {
		return Exchange{}, err
	}
	result, err := source.exchange(ctx, source.endpoint, c.tick, outgoing, beforeSend)
	if err != nil {
		return Exchange{}, err
	}
	reply, err := parseReply(result.Response, request)
	if err != nil {
		return Exchange{}, err
	}
	if reply.Stratum == 0 {
		return Exchange{}, source.applyKiss(reply, result.ReceiveAfterTickNS)
	}
	result.Reply = *reply
	return result, nil
}

func (source *sourceState) exchange(ctx context.Context, endpoint netip.AddrPort, tick func() (uint64, error),
	outgoing []byte, beforeSend func() (uint64, error)) (Exchange, error) {
	conn, err := net.DialUDP("udp", nil, net.UDPAddrFromAddrPort(endpoint))
	if err != nil {
		return Exchange{}, fmt.Errorf("open reference socket: %w", err)
	}
	defer conn.Close()
	stop := context.AfterFunc(ctx, func() { _ = conn.Close() })
	defer stop()
	// Go's clock bounds the I/O wait. Only the system elapsed clock supplies evidence ticks.
	if err := conn.SetDeadline(time.Now().Add(pollTimeout)); err != nil {
		return Exchange{}, fmt.Errorf("set reference socket deadline: %w", err)
	}
	var incoming [maxPacketBytes + 1]byte
	var authorizationDeadline uint64
	if beforeSend != nil {
		authorizationDeadline, err = beforeSend()
		if err != nil {
			return Exchange{}, err
		}
	}
	if err := ctx.Err(); err != nil {
		return Exchange{}, err
	}
	sendTick, err := tick()
	if err != nil {
		return Exchange{}, errClock
	}
	if err := source.checkInterval(sendTick); err != nil {
		return Exchange{}, err
	}
	if beforeSend != nil && sendTick >= authorizationDeadline {
		return Exchange{}, errBootstrap
	}
	source.sent, source.lastSend = true, sendTick
	written, err := conn.Write(outgoing)
	if err != nil || written != len(outgoing) {
		return Exchange{}, ioFailure(ctx, "send reference request", err)
	}
	length, readErr := conn.Read(incoming[:])
	if readErr != nil {
		return Exchange{}, ioFailure(ctx, "read reference reply", readErr)
	}
	receiveTick, err := tick()
	if err != nil || receiveTick < sendTick {
		return Exchange{}, errClock
	}
	if receiveTick-sendTick >= uint64(pollTimeout) || beforeSend != nil && receiveTick >= authorizationDeadline {
		return Exchange{}, errDeadline
	}
	if err := ctx.Err(); err != nil {
		return Exchange{}, err
	}
	return Exchange{Endpoint: endpoint, SendBeforeTickNS: sendTick, ReceiveAfterTickNS: receiveTick,
		Request: outgoing, Response: incoming[:length:length]}, nil
}

func ioFailure(ctx context.Context, action string, err error) error {
	if canceled := ctx.Err(); canceled != nil {
		return canceled
	}
	if failure, ok := err.(net.Error); ok && failure.Timeout() {
		return errDeadline
	}
	if err == nil {
		return errors.New(action + ": incomplete datagram")
	}
	return fmt.Errorf("%s: %w", action, err)
}
