package collector

import (
	"context"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/binary"
	"errors"
	"io"
	"net/netip"
	"strings"
	"time"

	"github.com/facebook/time/ntp/ntske"
	"github.com/facebook/time/ntp/protocol"
)

const (
	ntsAlgorithm   = protocol.AEADAESSIVCMAC256
	exporterLabel  = "EXPORTER-network-time-security"
	maxKEBytes     = 64 * 1024
	maxKERecords   = 64
	maxCookies     = 8
	maxCookieBytes = 1024
	keTimeout      = 5 * time.Second
	ntsLifetimeNS  = uint64(time.Hour)
)

var (
	errKE          = errors.New("reference NTS key establishment failed")
	errKERecords   = errors.New("reference NTS key establishment records inadmissible")
	errBootstrap   = errors.New("reference NTS authentication clock unavailable")
	errNTSEndpoint = errors.New("reference NTS endpoint outside approved set")
)

// AuthenticationInterval must be read from the independent authentication clock.
// Binding identifies the authority, runtime domain, and policy used for the acquisition.
type AuthenticationInterval struct {
	Lower, Upper                  time.Time
	ObservedTickNS, ExpiresTickNS uint64
	Binding, Acquisition          string
	SourceReadTickNS              uint64
	AcquisitionRef, PolicyRef     AuthenticationReference
	RuntimeRef, SourceRef         AuthenticationReference
	projection                    *authenticationProjection
}

type AuthenticationSource func(context.Context) (AuthenticationInterval, error)

// NTPTarget names a permitted server and port. Its destination IP is fixed by configuration.
type NTPTarget struct {
	Name string
	Port uint16
}

type keConfig struct {
	endpoint      netip.AddrPort
	serverName    string
	roots         *x509.CertPool
	rootDigests   [][32]byte
	defaultTarget NTPTarget
	targets       map[NTPTarget]netip.AddrPort
}

type keObservation struct {
	keEndpoint, ntpEndpoint netip.AddrPort
	serverName              string
	atTLS, atCompletion     AuthenticationInterval
	roots, chain            [][32]byte
	reply                   []byte // protected material containing initial cookies
}

type ntsSession struct {
	c2s, s2c     []byte
	cookies      [][]byte
	chain        []*x509.Certificate
	issuedTickNS uint64
	observation  keObservation
}

func authenticationNow(ctx context.Context, read AuthenticationSource, tick func() (uint64, error)) (AuthenticationInterval, error) {
	sample, err := read(ctx)
	now, clockErr := tick()
	if err != nil || clockErr != nil || ctx.Err() != nil || sample.Binding == "" || sample.Acquisition == "" ||
		sample.Lower.IsZero() || sample.Upper.Before(sample.Lower) ||
		sample.ObservedTickNS > now || now >= sample.ExpiresTickNS {
		return AuthenticationInterval{}, errBootstrap
	}
	if sample.projection != nil {
		sample.Lower, sample.Upper, err = sample.projection.at(now)
		if err != nil {
			return AuthenticationInterval{}, err
		}
		sample.ObservedTickNS = now
	}
	return sample, nil
}

func coversInterval(chain []*x509.Certificate, intervals ...AuthenticationInterval) bool {
	if len(chain) == 0 {
		return false
	}
	for _, certificate := range chain {
		for _, interval := range intervals {
			if interval.Lower.Before(certificate.NotBefore) || !interval.Upper.Before(certificate.NotAfter) {
				return false
			}
		}
	}
	return true
}

func readKEResponse(r io.Reader) ([]byte, error) {
	var raw []byte
	for range maxKERecords {
		var header [4]byte
		if _, err := io.ReadFull(r, header[:]); err != nil {
			return nil, errKERecords
		}
		length := int(binary.BigEndian.Uint16(header[2:]))
		if len(raw)+len(header)+length > maxKEBytes {
			return nil, errKERecords
		}
		raw = append(raw, header[:]...)
		start := len(raw)
		raw = append(raw, make([]byte, length)...)
		if _, err := io.ReadFull(r, raw[start:]); err != nil {
			return nil, errKERecords
		}
		if binary.BigEndian.Uint16(header[:2])&0x7fff == ntske.RecordEndOfMessage {
			// The server closes the TLS connection after its finite response.
			var extra [1]byte
			if n, err := r.Read(extra[:]); n != 0 || err != io.EOF {
				return nil, errKERecords
			}
			return raw, nil
		}
	}
	return nil, errKERecords
}

func parseKE(raw []byte, config keConfig) (netip.AddrPort, [][]byte, error) {
	if len(raw) > maxKEBytes {
		return netip.AddrPort{}, nil, errKERecords
	}
	records, err := ntske.Parse(raw)
	if err != nil || len(records) == 0 || len(records) > maxKERecords {
		return netip.AddrPort{}, nil, errKERecords
	}
	seen := [8]bool{}
	target := config.defaultTarget
	var cookies [][]byte
	for i, record := range records {
		if record.Type < uint16(len(seen)) && record.Type != ntske.RecordNewCookie {
			if seen[record.Type] {
				return netip.AddrPort{}, nil, errKERecords
			}
			seen[record.Type] = true
		}
		switch record.Type {
		case ntske.RecordNextProtocol:
			if !record.Critical || len(record.Body) != 2 || binary.BigEndian.Uint16(record.Body) != ntske.NextProtocolNTPv4 {
				return netip.AddrPort{}, nil, errKERecords
			}
		case ntske.RecordAEADAlgorithm:
			if len(record.Body) != 2 || binary.BigEndian.Uint16(record.Body) != uint16(ntsAlgorithm) {
				return netip.AddrPort{}, nil, errKERecords
			}
		case ntske.RecordEndOfMessage:
			if !record.Critical || len(record.Body) != 0 || i != len(records)-1 {
				return netip.AddrPort{}, nil, errKERecords
			}
		case ntske.RecordNewCookie:
			if len(record.Body) == 0 || len(record.Body) > maxCookieBytes || len(cookies) == maxCookies {
				return netip.AddrPort{}, nil, errKERecords
			}
			cookies = append(cookies, record.Body)
		case ntske.RecordServerNegotiation:
			target.Name = canonicalHost(string(record.Body))
			if target.Name == "" {
				return netip.AddrPort{}, nil, errKERecords
			}
		case ntske.RecordPortNegotiation:
			if len(record.Body) != 2 || binary.BigEndian.Uint16(record.Body) == 0 {
				return netip.AddrPort{}, nil, errKERecords
			}
			target.Port = binary.BigEndian.Uint16(record.Body)
		case ntske.RecordError, ntske.RecordWarning, ntske.RecordCompliant128GCMExport:
			return netip.AddrPort{}, nil, errKERecords
		default:
			if record.Critical {
				return netip.AddrPort{}, nil, errKERecords
			}
		}
	}
	if !seen[ntske.RecordNextProtocol] || !seen[ntske.RecordAEADAlgorithm] || !seen[ntske.RecordEndOfMessage] || len(cookies) == 0 {
		return netip.AddrPort{}, nil, errKERecords
	}
	endpoint, allowed := config.targets[target]
	if !allowed {
		return netip.AddrPort{}, nil, errNTSEndpoint
	}
	return endpoint, cookies, nil
}

func canonicalHost(name string) string {
	for _, c := range name {
		if c > 127 {
			return ""
		}
	}
	if ip, err := netip.ParseAddr(name); err == nil && ip.Zone() == "" {
		return ip.Unmap().String()
	}
	name = strings.TrimSuffix(strings.ToLower(name), ".")
	if len(name) > 253 {
		return ""
	}
	for label := range strings.SplitSeq(name, ".") {
		if len(label) == 0 || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
			return ""
		}
		for _, c := range label {
			if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '-') {
				return ""
			}
		}
	}
	return name
}

func establishKeys(ctx context.Context, config keConfig, read AuthenticationSource, tick func() (uint64, error)) (*ntsSession, error) {
	ctx, cancel := context.WithTimeout(ctx, keTimeout)
	defer cancel()
	start, err := tick()
	if err != nil {
		return nil, errBootstrap
	}
	initial, err := authenticationNow(ctx, read, tick)
	if err != nil {
		return nil, err
	}
	var readings []AuthenticationInterval
	var verifiedChain []*x509.Certificate
	var clockErr error
	lastObserved := initial.ObservedTickNS
	readBound := func() AuthenticationInterval {
		if clockErr != nil {
			return AuthenticationInterval{}
		}
		value, err := authenticationNow(ctx, read, tick)
		if err != nil || value.Binding != initial.Binding || value.ObservedTickNS < lastObserved {
			clockErr = errBootstrap
			cancel()
			return AuthenticationInterval{}
		}
		lastObserved = value.ObservedTickNS
		return value
	}
	tlsConfig := &tls.Config{
		RootCAs: config.roots, ServerName: config.serverName,
		MinVersion: tls.VersionTLS13, MaxVersion: tls.VersionTLS13,
		NextProtos: []string{ntske.ALPNProtocol}, SessionTicketsDisabled: true,
		Time: func() time.Time {
			value := readBound()
			readings = append(readings, value)
			return value.Upper
		},
		VerifyConnection: func(state tls.ConnectionState) error {
			latest := readBound()
			if clockErr != nil {
				return clockErr
			}
			readings = append(readings, latest)
			for _, chain := range state.VerifiedChains {
				if coversInterval(chain, readings...) {
					verifiedChain = chain
					return nil
				}
			}
			return errBootstrap
		},
	}
	dialer := tls.Dialer{Config: tlsConfig}
	conn, err := dialer.DialContext(ctx, "tcp", config.endpoint.String())
	if err != nil {
		if clockErr != nil {
			return nil, clockErr
		}
		return nil, errKE
	}
	defer conn.Close()
	closeOnCancel := context.AfterFunc(ctx, func() { _ = conn.Close() })
	defer closeOnCancel()
	deadline, _ := ctx.Deadline()
	if err := conn.SetDeadline(deadline); err != nil {
		return nil, errKE
	}
	state := conn.(*tls.Conn).ConnectionState()
	if state.NegotiatedProtocol != ntske.ALPNProtocol || state.DidResume || len(verifiedChain) == 0 {
		return nil, errKE
	}
	request, err := ntske.MarshalRecords([]ntske.Record{
		ntske.NewNextProtocol(ntske.NextProtocolNTPv4), ntske.NewAEADAlgorithm(uint16(ntsAlgorithm)), ntske.NewEndOfMessage(),
	})
	if err != nil {
		return nil, errKERecords
	}
	if n, err := conn.Write(request); err != nil || n != len(request) {
		return nil, errKE
	}
	raw, err := readKEResponse(conn)
	if err != nil {
		return nil, err
	}
	endpoint, cookies, err := parseKE(raw, config)
	if err != nil {
		return nil, err
	}
	latest := readBound()
	issued, err := tick()
	if clockErr != nil || err != nil || issued < start || issued-start >= uint64(keTimeout) ||
		issued >= latest.ExpiresTickNS || !coversInterval(verifiedChain, latest) {
		return nil, errBootstrap
	}
	c2s, err := state.ExportKeyingMaterial(exporterLabel, []byte{0, 0, 0, byte(ntsAlgorithm), 0}, 32)
	if err != nil {
		return nil, errKE
	}
	s2c, err := state.ExportKeyingMaterial(exporterLabel, []byte{0, 0, 0, byte(ntsAlgorithm), 1}, 32)
	if err != nil {
		clear(c2s)
		return nil, errKE
	}
	var chainDigests [][32]byte
	for _, certificate := range verifiedChain {
		chainDigests = append(chainDigests, sha256.Sum256(certificate.Raw))
	}
	return &ntsSession{c2s: c2s, s2c: s2c, cookies: cookies, chain: verifiedChain,
		issuedTickNS: issued, observation: keObservation{
			keEndpoint: config.endpoint, ntpEndpoint: endpoint, serverName: config.serverName,
			atTLS: readings[len(readings)-1], atCompletion: latest, roots: config.rootDigests, chain: chainDigests, reply: raw,
		}}, nil
}
