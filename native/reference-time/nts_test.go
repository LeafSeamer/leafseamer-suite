package collector

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"errors"
	"io"
	"math/big"
	"net"
	"net/netip"
	"testing"
	"time"

	"github.com/facebook/time/ntp/ntske"
	"github.com/facebook/time/ntp/protocol"
	"github.com/facebook/time/ntp/protocol/nts"
)

const fixtureName = "reference.example.test"

var fixtureUTC = time.Date(2036, 2, 8, 12, 0, 0, 0, time.UTC)

func fixtureTLS(t *testing.T) (tls.Certificate, []byte) {
	t.Helper()
	rootPub, rootKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	root := &x509.Certificate{
		SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "Fixture root"},
		NotBefore: fixtureUTC.Add(-24 * time.Hour), NotAfter: fixtureUTC.Add(24 * time.Hour),
		BasicConstraintsValid: true, IsCA: true, KeyUsage: x509.KeyUsageCertSign,
	}
	rootDER, err := x509.CreateCertificate(rand.Reader, root, root, rootPub, rootKey)
	if err != nil {
		t.Fatal(err)
	}
	leafPub, leafKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	leaf := &x509.Certificate{
		SerialNumber: big.NewInt(2), DNSNames: []string{fixtureName},
		NotBefore: fixtureUTC.Add(-time.Minute), NotAfter: fixtureUTC.Add(time.Minute),
		KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}
	leafDER, err := x509.CreateCertificate(rand.Reader, leaf, root, leafPub, rootKey)
	if err != nil {
		t.Fatal(err)
	}
	return tls.Certificate{Certificate: [][]byte{leafDER, rootDER}, PrivateKey: leafKey}, rootDER
}

func fixtureAuth(ctx context.Context) (AuthenticationInterval, error) {
	tick, err := nativeTick()
	return AuthenticationInterval{Lower: fixtureUTC.Add(-time.Second), Upper: fixtureUTC.Add(time.Second),
		ObservedTickNS: tick, ExpiresTickNS: tick + uint64(time.Second), Binding: "fixture-binding", Acquisition: "fixture-acquisition"}, err
}

func fixtureKE(t *testing.T) *net.TCPListener {
	t.Helper()
	listener, err := net.ListenTCP("tcp4", &net.TCPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = listener.Close() })
	return listener
}

func keRecords(cookie []byte, extras ...ntske.Record) []ntske.Record {
	records := []ntske.Record{ntske.NewNextProtocol(0), ntske.NewAEADAlgorithm(15), ntske.NewCookie(cookie)}
	records = append(records, extras...)
	return append(records, ntske.NewEndOfMessage())
}

func serveKE(listener *net.TCPListener, certificate tls.Certificate, records []ntske.Record) (c2s, s2c []byte, err error) {
	conn, err := listener.Accept()
	if err != nil {
		return nil, nil, err
	}
	peer := tls.Server(conn, &tls.Config{Certificates: []tls.Certificate{certificate},
		MinVersion: tls.VersionTLS13, NextProtos: []string{ntske.ALPNProtocol}, SessionTicketsDisabled: true})
	defer peer.Close()
	if err := peer.SetDeadline(time.Now().Add(keTimeout)); err != nil {
		return nil, nil, err
	}
	// The test reads the client's bounded message while leaving TLS available for the reply.
	want, err := ntske.MarshalRecords([]ntske.Record{ntske.NewNextProtocol(0), ntske.NewAEADAlgorithm(15), ntske.NewEndOfMessage()})
	if err != nil {
		return nil, nil, err
	}
	request := make([]byte, len(want))
	if _, err := io.ReadFull(peer, request); err != nil || !bytes.Equal(request, want) {
		return nil, nil, errKERecords
	}
	state := peer.ConnectionState()
	c2s, err = state.ExportKeyingMaterial(exporterLabel, []byte{0, 0, 0, 15, 0}, 32)
	if err != nil {
		return nil, nil, err
	}
	s2c, err = state.ExportKeyingMaterial(exporterLabel, []byte{0, 0, 0, 15, 1}, 32)
	if err != nil {
		return nil, nil, err
	}
	raw, err := ntske.MarshalRecords(records)
	if err != nil {
		return nil, nil, err
	}
	_, err = peer.Write(raw)
	return c2s, s2c, err
}

func authenticatedReply(request *protocol.Packet, uid, cookie, key []byte, duplicateUID bool) ([]byte, error) {
	p := protocol.Packet{Settings: serverSettings, Stratum: 1, RefTimeSec: 1, RxTimeSec: 2, TxTimeSec: 3,
		OrigTimeSec: request.TxTimeSec, OrigTimeFrac: request.TxTimeFrac,
		ExtensionFields: []protocol.ExtensionField{nts.NewUniqueIdentifier(uid)}}
	if duplicateUID {
		p.ExtensionFields = append(p.ExtensionFields, nts.NewUniqueIdentifier(uid))
	}
	return sealFixtureReply(p, cookie, key)
}

func sealFixtureReply(p protocol.Packet, cookie, key []byte) ([]byte, error) {
	ad, err := p.AssociatedData(len(p.ExtensionFields))
	if err != nil {
		return nil, err
	}
	aead, err := nts.NewAEAD(ntsAlgorithm, key)
	if err != nil {
		return nil, err
	}
	var encrypted []byte
	if len(cookie) != 0 {
		encrypted, err = nts.NewCookie(cookie).Encode()
		if err != nil {
			return nil, err
		}
	}
	tag, err := nts.SealAuthenticator(aead, ad, encrypted)
	if err != nil {
		return nil, err
	}
	p.ExtensionFields = append(p.ExtensionFields, tag)
	return p.Bytes()
}

func testNTSConfig(t *testing.T, tcp *net.TCPListener, udp *net.UDPConn, root []byte) NTSSourceConfig {
	t.Helper()
	endpoint := udp.LocalAddr().(*net.UDPAddr).AddrPort()
	target := NTPTarget{Name: fixtureName, Port: endpoint.Port()}
	return NTSSourceConfig{KeyEndpoint: tcp.Addr().(*net.TCPAddr).AddrPort(), ServerName: fixtureName, RootDER: [][]byte{root},
		DefaultTarget: target, Targets: map[NTPTarget]netip.AddrPort{target: endpoint}}
}

func TestNTSAuthenticatedLoopback(t *testing.T) {
	udp, _ := localSource(t)
	cert, root := fixtureTLS(t)
	tcp := fixtureKE(t)
	collector, err := NewNTSCollector(map[string]NTSSourceConfig{"test": testNTSConfig(t, tcp, udp, root)}, fixtureProviderAuthentication(t))
	if err != nil {
		t.Fatal(err)
	}
	initialCookie, nextCookie := bytes.Repeat([]byte{1}, 32), bytes.Repeat([]byte{2}, 32)
	done := make(chan error, 1)
	go func() {
		c2s, s2c, err := serveKE(tcp, cert, keRecords(initialCookie))
		if err == nil {
			err = serveAuthenticatedUDP(udp, initialCookie, nextCookie, c2s, s2c)
		}
		done <- err
	}()
	result, err := collector.Poll(t.Context(), "test")
	if err != nil {
		t.Fatal(err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	session := collector.sources["test"].session
	if result.Reply.RxTimeSec != 2 || result.ReceiveAfterTickNS < result.SendBeforeTickNS ||
		len(result.RootDigests) != 1 || len(result.ChainDigests) != 2 || result.TLSAuthentication.AcquisitionRef.Digest == "" ||
		result.PollAuthentication.SourceRef != result.TLSAuthentication.SourceRef ||
		len(session.cookies) != 1 || !bytes.Equal(session.cookies[0], nextCookie) || len(collector.sources["test"].seen) != 2 {
		t.Fatal("authenticated response and evidence were not retained")
	}
	if _, err := collector.Poll(t.Context(), "test"); !errors.Is(err, errInterval) {
		t.Fatalf("poll interval: %v", err)
	}
	collector.auth = func(context.Context) (AuthenticationInterval, error) { return AuthenticationInterval{}, errBootstrap }
	if _, err := collector.Poll(t.Context(), "test"); !errors.Is(err, errBootstrap) || collector.sources["test"].session != nil {
		t.Fatal("lost independent clock left cached NTS keys usable")
	}
}

func serveAuthenticatedUDP(server *net.UDPConn, initialCookie, nextCookie, c2s, s2c []byte) error {
	return serveNTSPoll(server, initialCookie, c2s, func(request *protocol.Packet) ([]byte, error) {
		return authenticatedReply(request, request.ExtensionFields[0].Body, nextCookie, s2c, false)
	})
}

func serveNTSPoll(server *net.UDPConn, initialCookie, c2s []byte, respond func(*protocol.Packet) ([]byte, error)) error {
	if err := server.SetDeadline(time.Now().Add(pollTimeout)); err != nil {
		return err
	}
	buf := make([]byte, maxPacketBytes+1)
	count, peer, err := server.ReadFromUDP(buf)
	if err != nil {
		return err
	}
	request, err := protocol.BytesToPacket(buf[:count])
	if err != nil || len(request.ExtensionFields) < 3 ||
		request.ExtensionFields[0].Type != protocol.UniqueIdentifier ||
		request.ExtensionFields[1].Type != protocol.NTSCookie ||
		!bytes.Equal(request.ExtensionFields[1].Body, initialCookie) {
		return errPacket
	}
	aead, err := nts.NewAEAD(ntsAlgorithm, c2s)
	if err != nil {
		return err
	}
	tail := len(request.ExtensionFields) - 1
	ad, err := request.AssociatedData(tail)
	if err != nil {
		return err
	}
	plaintext, err := nts.OpenAuthenticator(aead, ad, request.ExtensionFields[tail])
	if err != nil || len(plaintext) != 0 {
		return errPacket
	}
	reply, err := respond(request)
	if err != nil {
		return err
	}
	_, err = server.WriteToUDP(reply, peer)
	return err
}

func TestNTSKissRequiresTheBoundAuthenticationToChangeSourceState(t *testing.T) {
	const deny = uint32(0x44454e59)
	for _, test := range []struct {
		name          string
		code          uint32
		exponent      int8
		authenticated bool
		want          error
	}{
		{"unauthenticated denial", deny, 0, false, errPacket},
		{"authenticated rate", kissRateCode, 5, true, errKissRate},
		{"authenticated denial", deny, 0, true, errKissStop},
	} {
		t.Run(test.name, func(t *testing.T) {
			udp, _ := localSource(t)
			cert, root := fixtureTLS(t)
			tcp := fixtureKE(t)
			collector, err := NewNTSCollector(map[string]NTSSourceConfig{"test": testNTSConfig(t, tcp, udp, root)}, fixtureProviderAuthentication(t))
			if err != nil {
				t.Fatal(err)
			}
			cookie := bytes.Repeat([]byte{1}, 32)
			done := make(chan error, 1)
			go func() {
				c2s, s2c, err := serveKE(tcp, cert, keRecords(cookie))
				if err == nil {
					err = serveNTSPoll(udp, cookie, c2s, func(request *protocol.Packet) ([]byte, error) {
						reply := protocol.Packet{Settings: serverSettings | 3<<6, ReferenceID: test.code, Poll: test.exponent,
							OrigTimeSec: request.TxTimeSec, OrigTimeFrac: request.TxTimeFrac,
							ExtensionFields: []protocol.ExtensionField{nts.NewUniqueIdentifier(request.ExtensionFields[0].Body)}}
						if test.authenticated {
							return sealFixtureReply(reply, nil, s2c)
						}
						return reply.Bytes()
					})
				}
				done <- err
			}()
			result, err := collector.Poll(t.Context(), "test")
			if failure := <-done; failure != nil {
				t.Fatal(failure)
			}
			state := collector.sources["test"]
			if !errors.Is(err, test.want) || result.Response != nil ||
				(state.udp.kiss != nil) != test.authenticated {
				t.Fatalf("unexpected NTS control outcome: %+v / %v", result, err)
			}
			wantNext := errInterval
			if errors.Is(err, errKissStop) {
				wantNext = errKissStop
				if state.session != nil {
					t.Fatal("stopped source retained an NTS session")
				}
			}
			if _, err := collector.Poll(t.Context(), "test"); !errors.Is(err, wantNext) {
				t.Fatalf("source resumed or started a fresh key negotiation: %v", err)
			}
		})
	}
}

func TestNTSRejectsMalformedKeyNegotiation(t *testing.T) {
	approved := netip.MustParseAddrPort("127.0.0.1:123")
	target := NTPTarget{fixtureName, approved.Port()}
	config := keConfig{defaultTarget: target, targets: map[NTPTarget]netip.AddrPort{target: approved}}
	for _, record := range []ntske.Record{
		ntske.NewNextProtocol(0), ntske.NewAEADAlgorithm(15), ntske.NewEndOfMessage(), ntske.NewPortNegotiation(0),
		ntske.NewPortNegotiation(124), ntske.NewServerNegotiation("unapproved.example.test"), ntske.NewWarning(1),
		{Critical: true, Type: 32000}, {Type: ntske.RecordCompliant128GCMExport},
	} {
		raw, err := ntske.MarshalRecords(keRecords([]byte{1}, record))
		if err != nil {
			t.Fatal(err)
		}
		if _, _, err := parseKE(raw, config); err == nil {
			t.Fatalf("accepted inadmissible record type %d", record.Type)
		}
	}
	raw, err := ntske.MarshalRecords(keRecords([]byte{1}, ntske.Record{Type: 32000, Body: []byte{1}}))
	if err != nil {
		t.Fatal(err)
	}
	if endpoint, _, err := parseKE(raw, config); err != nil || endpoint != approved {
		t.Fatalf("unknown noncritical record changed negotiation: %v", err)
	}
	if _, err := readKEResponse(bytes.NewReader(append(raw, 0))); !errors.Is(err, errKERecords) {
		t.Fatal("accepted data after end of message")
	}
}

func TestNTSRejectsCertificateWhenLowerBoundPrecedesValidity(t *testing.T) {
	udp, _ := localSource(t)
	cert, root := fixtureTLS(t)
	tcp := fixtureKE(t)
	config := testNTSConfig(t, tcp, udp, root)
	wide := func(ctx context.Context) (AuthenticationInterval, error) {
		value, err := fixtureAuth(ctx)
		value.Lower = fixtureUTC.Add(-2 * time.Minute)
		return value, err
	}
	collector, err := NewNTSCollector(map[string]NTSSourceConfig{"test": config}, wide)
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() {
		_, _, err := serveKE(tcp, cert, keRecords(bytes.Repeat([]byte{1}, 32)))
		done <- err
	}()
	if _, err := collector.Poll(t.Context(), "test"); !errors.Is(err, errKE) || collector.sources["test"].session != nil {
		t.Fatalf("certificate accepted with only its upper time bound inside validity: %v", err)
	}
	if err := <-done; err == nil {
		t.Fatal("invalid TLS chain interval reached key negotiation")
	}
	if _, err := collector.Poll(t.Context(), "test"); !errors.Is(err, errKEBackoff) {
		t.Fatalf("failed key negotiation did not retain backoff: %v", err)
	}
}

func TestNTSRejectsDuplicateUIDWrongKeyAndLegacyTrailer(t *testing.T) {
	request, _, err := makeRequest()
	if err != nil {
		t.Fatal(err)
	}
	key, uid := bytes.Repeat([]byte{1}, 32), bytes.Repeat([]byte{2}, 32)
	cookie := bytes.Repeat([]byte{3}, 32)
	correct, err := authenticatedReply(request, uid, cookie, key, false)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := verifyNTSReply(correct, request, key, uid); err != nil {
		t.Fatal(err)
	}
	duplicate, err := authenticatedReply(request, uid, cookie, key, true)
	if err != nil {
		t.Fatal(err)
	}
	for _, raw := range [][]byte{duplicate, append(correct, 0, 0, 0, 0)} {
		if _, _, err := verifyNTSReply(raw, request, key, uid); !errors.Is(err, errPacket) {
			t.Fatal("accepted ambiguous UID or a legacy trailer")
		}
	}
	if _, _, err := verifyNTSReply(correct, request, bytes.Repeat([]byte{9}, 32), uid); !errors.Is(err, errPacket) {
		t.Fatal("accepted incorrect authenticator")
	}
}
