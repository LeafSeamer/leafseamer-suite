package collector

import (
	"bufio"
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

const linuxLinkChild = "LEAFSEAMER_TEST_LINUX_REFERENCE_LINK_CHILD"

func TestLinuxProviderLinkChild(t *testing.T) {
	if os.Getenv(linuxLinkChild) != "1" {
		t.Skip("child process entry")
	}
	admission, err := BootstrapTimeProvider(t.Context(), os.Stdin, os.Stdout, fixtureProviderLaunch())
	if err != nil {
		os.Exit(2)
	}
	err = RunProviderLink(t.Context(), admission, "core-1", "database-1", 2*time.Second)
	if !errors.Is(err, errProviderLink) {
		os.Exit(3)
	}
	os.Exit(0)
}

func TestLinuxProviderLinkUsesInheritedSocketAndProcessesPoll(t *testing.T) {
	for _, variant := range []string{"poll", "missing link", "pipe substitution", "image substitution", "start time substitution", "pid substitution", "core substitution", "legacy binding"} {
		t.Run(variant, func(t *testing.T) {
			var core, inherited *os.File
			if variant == "pipe substitution" {
				var err error
				inherited, core, err = os.Pipe()
				if err != nil {
					t.Fatal(err)
				}
			} else if variant != "missing link" {
				pair, err := unix.Socketpair(unix.AF_UNIX, unix.SOCK_STREAM|unix.SOCK_CLOEXEC|unix.SOCK_NONBLOCK, 0)
				if err != nil {
					t.Fatal(err)
				}
				core = os.NewFile(uintptr(pair[0]), "fixture-reference-core")
				inherited = os.NewFile(uintptr(pair[1]), "fixture-reference-provider")
			}
			child := exec.CommandContext(t.Context(), os.Args[0], "-test.run=^TestLinuxProviderLinkChild$")
			child.Env = append(os.Environ(), linuxLinkChild+"=1")
			input, err := child.StdinPipe()
			if err != nil {
				t.Fatal(err)
			}
			output, err := child.StdoutPipe()
			if err != nil {
				t.Fatal(err)
			}
			defer input.Close()
			if inherited != nil {
				defer core.Close()
				defer inherited.Close()
				child.ExtraFiles = []*os.File{inherited}
			}
			if err := child.Start(); err != nil {
				t.Fatal(err)
			}
			defer func() {
				if child.ProcessState == nil {
					child.Process.Kill()
					child.Wait()
				}
			}()
			if inherited != nil {
				inherited.Close()
			}
			observed := linuxLinkObserve(t, child.Process.Pid)
			admission := linuxLinkAdmit(t, input, output)
			if variant == "missing link" || variant == "pipe substitution" {
				wantBootstrapExit(t, child, 0)
				return
			}
			if err := core.SetDeadline(time.Now().Add(4 * time.Second)); err != nil {
				t.Fatal(err)
			}
			binding, digest := linuxLinkBinding(t, admission, observed, variant)
			writeLinuxLinkFrame(t, core, wireObject{"version": providerLinkVersion, "type": "BIND", "request_id": "request-1",
				"binding_digest": digest, "binding": binding})
			reader := bufio.NewReader(core)
			if variant != "poll" {
				if raw, err := reader.ReadBytes('\n'); len(raw) != 0 || !errors.Is(err, io.EOF) {
					t.Fatalf("invalid binding produced a response: %v", err)
				}
				wantBootstrapExit(t, child, 0)
				return
			}
			request := readLinuxLinkFrame(t, reader, "AUTH_READ", digest)
			writeLinuxLinkFrame(t, core, wireObject{"version": providerAuthVersion, "type": "AUTH_RESULT",
				"reply_to": request["request_id"], "binding_digest": digest, "sample": nil})
			if reply := readLinuxLinkFrame(t, reader, "BOUND", digest); reply["reply_to"] != "request-1" {
				t.Fatal("binding acknowledgement selected the wrong request")
			}
			exerciseLinuxProviderPoll(t, core, reader, digest, canonicalObject(admission.Receipt)["domain_ref"])
			core.Close()
			wantBootstrapExit(t, child, 0)
		})
	}
}

func TestLinuxProviderLinkRejectsNamedSocketAndWrongParent(t *testing.T) {
	pair, err := unix.Socketpair(unix.AF_UNIX, unix.SOCK_STREAM|unix.SOCK_CLOEXEC, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer unix.Close(pair[0])
	defer unix.Close(pair[1])
	if !privateSupervisorLink(pair[0], os.Getpid()) || privateSupervisorLink(pair[0], os.Getpid()+1) {
		t.Fatal("private link ignored the kernel peer process identity")
	}
	address := &net.UnixAddr{Name: filepath.Join(t.TempDir(), "link"), Net: "unix"}
	listener, err := net.ListenUnix("unix", address)
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	conn, err := net.DialUnix("unix", nil, address)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	file, err := conn.File()
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	if privateSupervisorLink(int(file.Fd()), os.Getpid()) {
		t.Fatal("provider accepted a named socket from its parent")
	}
}

func linuxLinkObserve(t *testing.T, pid int) wireObject {
	t.Helper()
	proc := fmt.Sprintf("/proc/%d", pid)
	stat, err := os.ReadFile(proc + "/stat")
	if err != nil {
		t.Fatal(err)
	}
	var image unix.Stat_t
	if err := unix.Stat(proc+"/exe", &image); err != nil {
		t.Fatal(err)
	}
	start := strings.Fields(string(stat[strings.LastIndexByte(string(stat), ')')+1:]))[19]
	tick, err := nativeTick()
	if err != nil {
		t.Fatal(err)
	}
	return wireObject{"observation_id": "observation-1", "observed_tick_ns": strconv.FormatUint(tick, 10), "provider_pid": pid,
		"start_ticks": start, "image_device": strconv.FormatUint(uint64(image.Dev), 10), "image_inode": strconv.FormatUint(image.Ino, 10)}
}

func linuxLinkAdmit(t *testing.T, input io.Writer, output io.Reader) ProviderAdmission {
	t.Helper()
	launch := fixtureProviderLaunch()
	intent, domain := canonicalObject(launch.Intent), canonicalObject(launch.Descriptor)
	tick, err := nativeTick()
	if err != nil {
		t.Fatal(err)
	}
	key := bytes.Repeat([]byte{0x41}, 32)
	common := wireObject{"bootstrap_id": "bootstrap-1", "launch_id": intent["launch_id"], "launch_intent_digest": hashWire(launch.Intent),
		"member_id": intent["member_id"], "member_boot_id": strings.Repeat("a", 32), "role": intent["role"],
		"artifact_manifest_ref": intent["artifact_manifest_ref"], "channel_binding_id": "channel-1"}
	assignment := selectFields(common, "bootstrap_id launch_id launch_intent_digest member_id member_boot_id role artifact_manifest_ref channel_binding_id")
	assignment["bootstrap_version"], assignment["challenge_id"] = bootstrapVersion, "challenge-1"
	assignment["clock_domain_descriptor"] = domain
	assignment["secret"] = base64.RawURLEncoding.EncodeToString(key)
	assignment["challenge_nonce"] = base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{0x42}, 32))
	assignment["issued_tick_ns"] = strconv.FormatUint(tick, 10)
	assignment["expires_tick_ns"] = strconv.FormatUint(tick+uint64(launch.Timeout), 10)
	testWriteBootstrap(t, input, "ASSIGNMENT", assignment)
	proof, err := readBootstrap(bufio.NewReaderSize(output, bootstrapLimit+2), "PROOF")
	if err != nil {
		t.Fatal(err)
	}
	projection := selectFields(assignment, "artifact_manifest_ref bootstrap_id bootstrap_version challenge_id challenge_nonce channel_binding_id expires_tick_ns issued_tick_ns launch_id launch_intent_digest member_boot_id member_id role")
	projection["clock_domain_id"], projection["descriptor_digest"] = domain["clock_domain_id"], domain["descriptor_digest"]
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte("leafseamer-bootstrap-proof/v1\x00"))
	mac.Write(linuxLinkJSON(t, projection))
	tag, ok := bootstrapSecret(proof["proof"])
	if !ok || !hmac.Equal(tag, mac.Sum(nil)) {
		t.Fatal("invalid provider bootstrap proof")
	}
	common["receipt_id"], common["os_observation_ref"], common["gate_state"] = "receipt-1", "observation-1", "closed"
	common["admitted_tick_ns"], common["containment_ref"] = assignment["issued_tick_ns"], intent["containment_ref"]
	common["domain_ref"] = selectFields(domain, "clock_domain_id descriptor_digest")
	testWriteBootstrap(t, input, "ADMISSION", common)
	return ProviderAdmission{launch.Intent, launch.Descriptor, linuxLinkJSON(t, common)}
}

func linuxLinkBinding(t *testing.T, admission ProviderAdmission, observed wireObject, variant string) (wireObject, string) {
	t.Helper()
	format := "leafseamer-time-provider-runtime-binding/2"
	switch variant {
	case "image substitution":
		observed["image_inode"] = "0"
	case "start time substitution":
		observed["start_ticks"] = "0"
	case "pid substitution":
		observed["provider_pid"] = os.Getpid()
	case "legacy binding":
		format = "leafseamer-time-provider-runtime-binding/1"
	}
	binding := wireObject{"format": format, "service_id": "service-1", "database_instance_id": "database-1",
		"service_boot_id": "service-boot-1", "core_receipt_id": "core-1", "launch_intent": canonicalObject(admission.Intent),
		"clock_domain_descriptor": canonicalObject(admission.Descriptor), "admission_receipt": canonicalObject(admission.Receipt),
		"process_observation": observed, "gate_state": "closed"}
	if variant == "core substitution" {
		binding["core_receipt_id"] = "wrong-core"
	}
	binding["runtime_binding_id"] = "time-runtime." + hashWire(linuxLinkJSON(t, binding))[7:]
	return binding, hashWire(linuxLinkJSON(t, binding))
}

func exerciseLinuxProviderPoll(t *testing.T, core *os.File, reader *bufio.Reader, digest string, domain any) {
	t.Helper()
	server, _ := localSource(t)
	if err := server.SetDeadline(time.Now().Add(3 * time.Second)); err != nil {
		t.Fatal(err)
	}
	udp := oneReply(server, makeReply)
	network := wireObject{"authentication": "trusted_network", "endpoint": server.LocalAddr().String()}
	acquisition := wireObject{"id": "acquisition-1", "revision": "1", "digest": digest}
	start, err := nativeTick()
	if err != nil {
		t.Fatal(err)
	}
	startText, endText := strconv.FormatUint(start, 10), strconv.FormatUint(start+uint64(2*time.Second), 10)
	reservation := wireObject{"poll_id": "poll-1", "source_slot": "local", "runtime_digest": digest,
		"service_boot_id": "service-boot-1", "reserved_bytes": "16384", "acquisition_ref": acquisition,
		"issued_tick_ns": startText, "expires_tick_ns": endText,
		"authorization": wireObject{"endpoint_ref": wireObject{"id": "endpoint-1", "revision": "1", "digest": hashWire(linuxLinkJSON(t, network))}}}
	pollRef := wireObject{"id": "poll-1", "digest": hashWire(linuxLinkJSON(t, reservation))}
	attempt := wireObject{"attempt_id": "attempt-1", "runtime_digest": digest, "poll_ref": pollRef, "acquisition_ref": acquisition,
		"attempted_tick_ns": startText, "expires_tick_ns": endText, "valid_before_tick_ns": endText}
	writeLinuxLinkFrame(t, core, wireObject{"version": providerLinkVersion, "type": "POLL", "binding_digest": digest, "poll_sequence": "1",
		"network": network, "reservation": reservation, "attempt": attempt})
	request := readLinuxLinkFrame(t, reader, "AUTH_READ", digest)
	tick, err := nativeTick()
	if err != nil {
		t.Fatal(err)
	}
	sample := wireObject{"acquisition_ref": acquisition, "source_ref": acquisition, "policy_ref": acquisition, "runtime_ref": acquisition,
		"runtime_domain_ref": domain, "tick_ns": strconv.FormatUint(tick, 10), "valid_before_tick_ns": endText,
		"lower_ns": "1800000000000000000", "upper_ns": "1800000000000100000", "monotonic_quantization_ns": "100", "drift_ppb": 1000}
	writeLinuxLinkFrame(t, core, wireObject{"version": providerAuthVersion, "type": "AUTH_RESULT",
		"reply_to": request["request_id"], "binding_digest": digest, "sample": sample})
	result := readLinuxLinkFrame(t, reader, "POLL_RESULT", digest)
	candidate, ok := result["candidate"].(map[string]any)
	if !ok || result["status"] != "candidate" || candidate["endpoint"] != network["endpoint"] || !sameWire(result["poll_ref"], pollRef) {
		t.Fatal("Linux provider did not return the bound UDP capture")
	}
	sent, sendErr := base64.RawURLEncoding.DecodeString(candidate["request"].(string))
	m1, m1OK := bootstrapUint(candidate["m1_tick_ns"])
	m4, m4OK := bootstrapUint(candidate["m4_tick_ns"])
	if sendErr != nil || len(sent) != 48 || !m1OK || !m4OK || m1 < start || m1 > m4 || m4 >= start+uint64(2*time.Second) ||
		candidate["response"] != base64.RawURLEncoding.EncodeToString(makeReply(sent)) {
		t.Fatal("Linux provider changed the UDP bytes or monotonic bounds")
	}
	if err := <-udp; err != nil {
		t.Fatal(err)
	}
	stored := wireObject{"attempt_id": "attempt-1", "poll_ref": pollRef, "m1_tick_ns": candidate["m1_tick_ns"], "m4_tick_ns": candidate["m4_tick_ns"],
		"plaintext_digest": hashWire(linuxLinkJSON(t, candidate)), "capture_ref": wireObject{"id": "capture-1", "revision": "1", "digest": digest}}
	writeLinuxLinkFrame(t, core, wireObject{"version": providerLinkVersion, "type": "POLL_STORED", "binding_digest": digest, "poll_sequence": "1", "receipt": stored})
	if ack := readLinuxLinkFrame(t, reader, "POLL_STORED_ACK", digest); !sameWire(ack["receipt"], stored) {
		t.Fatal("provider changed the stored capture acknowledgement")
	}
}

func linuxLinkJSON(t *testing.T, frame wireObject) []byte {
	t.Helper()
	raw, err := json.Marshal(frame)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func writeLinuxLinkFrame(t *testing.T, file *os.File, frame wireObject) {
	t.Helper()
	if _, err := file.Write(append(linuxLinkJSON(t, frame), '\n')); err != nil {
		t.Fatal(err)
	}
}

func readLinuxLinkFrame(t *testing.T, reader *bufio.Reader, kind, digest string) wireObject {
	t.Helper()
	raw, err := reader.ReadBytes('\n')
	if err != nil {
		t.Fatal(err)
	}
	frame := canonicalObject(raw[:len(raw)-1])
	if frame["type"] != kind || frame["binding_digest"] != digest {
		t.Fatalf("unexpected reference link frame, expected %s", kind)
	}
	return frame
}
