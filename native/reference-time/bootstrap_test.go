package collector

import (
	"bufio"
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"
)

const providerFixtureFlag = "LEAFSEAMER_PROVIDER_BOOTSTRAP_TEST_CHILD"

func fixtureProviderLaunch() ProviderLaunch {
	backend, namespace, containment := "windows_interrupt_precise", "windows-global", "windows_job"
	if runtime.GOOS == "linux" {
		backend, namespace, containment = "linux_boottime", "test-clock-namespace", "linux_cgroup_v2"
	}
	intent := wireObject{"launch_id": "time-launch-1", "service_id": "service-1", "supervisor_instance_id": "supervisor-1",
		"runtime_generation": "generation-1", "member_id": "provider-1", "role": "time_provider", "device_ids": []any{},
		"artifact_manifest_ref": wireObject{"manifest_id": "provider-manifest", "revision": "1", "digest": "sha256:" + strings.Repeat("1", 64)},
		"containment_ref":       wireObject{"backend": containment, "group_id": "contained-1", "generation": "generation-1"}, "policy_revision": "1"}
	descriptor := wireObject{"descriptor_version": "clock-domain/1", "domain_kind": "supervised_runtime",
		"authority_service_id": "service-1", "runtime_generation": "generation-1", "supervisor_instance_id": "supervisor-1",
		"clock_backend_id": backend, "clock_backend_revision": "native-v1", "tick_unit": "ns", "suspend_accounting": "included",
		"namespace_identity": namespace, "os_boot_identity": wireObject{"status": "unavailable"},
		"platform_profile_id": "fixture-profile", "platform_profile_revision": "1"}
	raw, _ := json.Marshal(descriptor)
	digest := hashWire(raw)
	descriptor["descriptor_digest"], descriptor["clock_domain_id"] = digest, "clock_"+digest[7:]
	intentBytes, _ := json.Marshal(intent)
	descriptorBytes, _ := json.Marshal(descriptor)
	return ProviderLaunch{intentBytes, descriptorBytes, 5 * time.Second}
}

// Invoked only as a separately owned process in the inherited-pipe tests below.
func TestProviderBootstrapChild(t *testing.T) {
	if os.Getenv(providerFixtureFlag) != "1" {
		t.Skip("child process entry")
	}
	launch := fixtureProviderLaunch()
	admission, err := BootstrapTimeProvider(t.Context(), os.Stdin, os.Stdout, launch)
	if errors.Is(err, errProviderBootstrap) {
		os.Exit(3)
	}
	if err != nil || !bytes.Equal(admission.Intent, launch.Intent) || !bytes.Equal(admission.Descriptor, launch.Descriptor) ||
		canonicalObject(admission.Receipt)["gate_state"] != "closed" || bytes.Contains(admission.Receipt, []byte("secret")) ||
		bytes.Contains(admission.Receipt, []byte("challenge_nonce")) {
		os.Exit(4)
	}
	os.Exit(0)
}

func testWriteBootstrap(t *testing.T, writer io.Writer, name string, payload wireObject) {
	t.Helper()
	raw, err := json.Marshal(wireObject{"version": bootstrapVersion, "type": name, "payload": payload})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := writer.Write(append(raw, '\n')); err != nil {
		t.Fatal(err)
	}
}

func TestProviderBootstrapOverInheritedProcessPipes(t *testing.T) {
	launch := fixtureProviderLaunch()
	intent, descriptor := canonicalObject(launch.Intent), canonicalObject(launch.Descriptor)
	for _, variant := range []string{"closed admission", "different provider role", "wrong descriptor", "expired assignment", "different channel receipt", "future admission"} {
		t.Run(variant, func(t *testing.T) {
			child := exec.CommandContext(t.Context(), os.Args[0], "-test.run=^TestProviderBootstrapChild$")
			child.Env = append(os.Environ(), providerFixtureFlag+"=1")
			in, err := child.StdinPipe()
			if err != nil {
				t.Fatal(err)
			}
			out, err := child.StdoutPipe()
			if err != nil {
				t.Fatal(err)
			}
			if err := child.Start(); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() {
				in.Close()
				if child.ProcessState == nil {
					child.Process.Kill()
					child.Wait()
				}
			})
			now, err := nativeTick()
			if err != nil {
				t.Fatal(err)
			}
			key, nonce := bytes.Repeat([]byte{0x31}, 32), bytes.Repeat([]byte{0x42}, 32)
			common := wireObject{"bootstrap_version": bootstrapVersion, "bootstrap_id": "bootstrap-1",
				"launch_id": intent["launch_id"], "launch_intent_digest": hashWire(launch.Intent), "member_id": intent["member_id"],
				"member_boot_id": "provider-boot-1", "role": intent["role"], "artifact_manifest_ref": intent["artifact_manifest_ref"],
				"channel_binding_id": "channel-1", "challenge_id": "challenge-1"}
			assignment := wireObject{}
			for field, value := range common {
				assignment[field] = value
			}
			assignment["clock_domain_descriptor"] = descriptor
			assignment["issued_tick_ns"] = strconv.FormatUint(now, 10)
			assignment["expires_tick_ns"] = strconv.FormatUint(now+uint64(launch.Timeout), 10)
			assignment["secret"] = base64.RawURLEncoding.EncodeToString(key)
			assignment["challenge_nonce"] = base64.RawURLEncoding.EncodeToString(nonce)
			switch variant {
			case "different provider role":
				assignment["role"] = "worker"
			case "wrong descriptor":
				assignment["clock_domain_descriptor"] = wireObject{"clock_domain_id": descriptor["clock_domain_id"]}
			case "expired assignment":
				if now < uint64(launch.Timeout) {
					t.Skip("native clock has not reached five seconds")
				}
				assignment["issued_tick_ns"] = strconv.FormatUint(now-uint64(launch.Timeout), 10)
				assignment["expires_tick_ns"] = strconv.FormatUint(now, 10)
			}
			testWriteBootstrap(t, in, "ASSIGNMENT", assignment)
			reader := bufio.NewReader(out)
			if variant == "different provider role" || variant == "wrong descriptor" || variant == "expired assignment" {
				if raw, err := reader.ReadBytes('\n'); !errors.Is(err, io.EOF) || len(raw) != 0 {
					t.Fatal("wrong assignment produced a proof")
				}
				wantBootstrapExit(t, child, 3)
				return
			}
			proof, err := readBootstrap(reader, "PROOF")
			if err != nil {
				t.Fatal(err)
			}
			want := make(wireObject)
			for field, value := range common {
				want[field] = value
			}
			want["clock_domain_id"], want["descriptor_digest"] = descriptor["clock_domain_id"], descriptor["descriptor_digest"]
			for _, name := range []string{"challenge_nonce", "issued_tick_ns", "expires_tick_ns"} {
				want[name] = assignment[name]
			}
			projection, _ := json.Marshal(want)
			expected := hmac.New(sha256.New, key)
			expected.Write([]byte("leafseamer-bootstrap-proof/v1\x00"))
			expected.Write(projection)
			tag, valid := bootstrapSecret(proof["proof"])
			if !valid || !hmac.Equal(tag, expected.Sum(nil)) || proof["role"] != "time_provider" || proof["clock_domain_id"] != descriptor["clock_domain_id"] {
				t.Fatal("invalid provider proof")
			}
			delete(common, "bootstrap_version")
			delete(common, "challenge_id")
			common["receipt_id"] = "receipt-1"
			common["domain_ref"] = wireObject{"clock_domain_id": descriptor["clock_domain_id"], "descriptor_digest": descriptor["descriptor_digest"]}
			common["containment_ref"] = intent["containment_ref"]
			common["os_observation_ref"] = "observation-1"
			common["admitted_tick_ns"] = strconv.FormatUint(now, 10)
			common["gate_state"] = "closed"
			if variant == "different channel receipt" {
				common["channel_binding_id"] = "other-channel"
			}
			if variant == "future admission" {
				common["admitted_tick_ns"] = assignment["expires_tick_ns"]
			}
			testWriteBootstrap(t, in, "ADMISSION", common)
			if variant == "closed admission" {
				wantBootstrapExit(t, child, 0)
			} else {
				wantBootstrapExit(t, child, 3)
			}
		})
	}
}

func wantBootstrapExit(t *testing.T, child *exec.Cmd, code int) {
	t.Helper()
	err := child.Wait()
	if child.ProcessState == nil || child.ProcessState.ExitCode() != code {
		t.Fatalf("wanted child exit %d, got %v", code, err)
	}
}

func TestLaunchRejectsNonCanonicalAndNonEmptyDeviceSet(t *testing.T) {
	launch := fixtureProviderLaunch()
	intent := canonicalObject(launch.Intent)
	intent["device_ids"] = []string{"device-1"}
	deviceIntent, _ := json.Marshal(intent)
	for _, raw := range [][]byte{deviceIntent, append(append([]byte(nil), launch.Intent...), ' ')} {
		if _, _, err := checkedLaunch(raw, launch.Descriptor); !errors.Is(err, errProviderBootstrap) {
			t.Fatal("accepted invalid protected launch intent")
		}
	}
}
