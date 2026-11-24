package collector

import (
	"bufio"
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"runtime"
	"strconv"
	"strings"
	"time"
)

const (
	bootstrapVersion = "bootstrap/0.1.0-draft.1"
	bootstrapRole    = "time_provider"
	bootstrapLimit   = 16384
)

var errProviderBootstrap = errors.New("reference time provider bootstrap refused")

// ProviderLaunch is populated by protected startup independently of the assignment.
// Intent and Descriptor are the exact canonical originals pinned by the launcher.
type ProviderLaunch struct {
	Intent, Descriptor []byte
	Timeout            time.Duration
}

// ProviderAdmission preserves the admitted-closed launch originals.
// Runtime adoption and collector-channel authorization are separate steps.
type ProviderAdmission struct {
	Intent, Descriptor, Receipt []byte
}

type wireObject = map[string]any

// BootstrapTimeProvider takes the dedicated pipes inherited from the supervisor.
// Neither pipe is suitable for the subsequent collector channel.
func BootstrapTimeProvider(ctx context.Context, input, output *os.File, expected ProviderLaunch) (result ProviderAdmission, err error) {
	if input == nil || output == nil || input == output || expected.Timeout < time.Millisecond ||
		expected.Timeout > time.Minute || expected.Timeout%time.Millisecond != 0 {
		return result, errProviderBootstrap
	}
	if !validBootstrapStreams(input, output) {
		return result, errProviderBootstrap
	}
	defer func() {
		if err != nil {
			input.Close()
			output.Close()
		}
	}()
	intentBytes, descriptorBytes := bytes.Clone(expected.Intent), bytes.Clone(expected.Descriptor)
	intent, descriptor, err := checkedLaunch(intentBytes, descriptorBytes)
	if err != nil {
		return result, err
	}
	ctx, cancel := context.WithTimeout(ctx, expected.Timeout)
	defer cancel()
	closeOnTimeout := context.AfterFunc(ctx, func() {
		input.Close()
		output.Close()
	})
	defer closeOnTimeout()
	reader := bufio.NewReaderSize(input, bootstrapLimit+2)
	assignment, err := readBootstrap(reader, "ASSIGNMENT")
	if err != nil {
		return result, err
	}
	domain, valid := assignment["clock_domain_descriptor"].(map[string]any)
	start, startOK := bootstrapUint(assignment["issued_tick_ns"])
	end, endOK := bootstrapUint(assignment["expires_tick_ns"])
	key, keyOK := bootstrapSecret(assignment["secret"])
	defer clear(key)
	nonce, nonceOK := bootstrapSecret(assignment["challenge_nonce"])
	defer clear(nonce)
	if !fields(assignment, "bootstrap_version bootstrap_id launch_id launch_intent_digest member_id member_boot_id role artifact_manifest_ref channel_binding_id challenge_id clock_domain_descriptor challenge_nonce issued_tick_ns expires_tick_ns secret") ||
		!valid || !startOK || !endOK || !keyOK || !nonceOK || end <= start || end-start != uint64(expected.Timeout) ||
		assignment["bootstrap_version"] != bootstrapVersion || assignment["role"] != bootstrapRole ||
		!ids(assignment, "bootstrap_id member_boot_id channel_binding_id challenge_id") ||
		!sameWire(domain, descriptor) || assignment["launch_id"] != intent["launch_id"] || assignment["member_id"] != intent["member_id"] ||
		assignment["launch_intent_digest"] != hashWire(intentBytes) || !sameWire(assignment["artifact_manifest_ref"], intent["artifact_manifest_ref"]) {
		return result, errProviderBootstrap
	}
	checkTime := func() (uint64, error) {
		now, tickErr := nativeTick()
		if ctx.Err() != nil || tickErr != nil || now < start || now >= end {
			return 0, errProviderBootstrap
		}
		return now, nil
	}
	if _, err := checkTime(); err != nil {
		return result, err
	}
	if err := writeProof(output, assignment, descriptor, key); err != nil {
		return result, err
	}
	clear(key)
	delete(assignment, "secret")
	delete(assignment, "challenge_nonce")
	receipt, err := readBootstrap(reader, "ADMISSION")
	if err != nil {
		return result, err
	}
	now, err := checkTime()
	admitted, admittedOK := bootstrapUint(receipt["admitted_tick_ns"])
	if err != nil || !admittedOK || admitted < start || admitted > now ||
		!fields(receipt, "bootstrap_id launch_id launch_intent_digest member_id member_boot_id role artifact_manifest_ref channel_binding_id receipt_id domain_ref containment_ref os_observation_ref admitted_tick_ns gate_state") ||
		!ids(receipt, "receipt_id os_observation_ref") || receipt["gate_state"] != "closed" ||
		!sameWire(receipt["containment_ref"], intent["containment_ref"]) ||
		!sameWire(receipt["domain_ref"], selectFields(descriptor, "clock_domain_id descriptor_digest")) {
		return result, errProviderBootstrap
	}
	const bindingFields = "bootstrap_id launch_id launch_intent_digest member_id member_boot_id role artifact_manifest_ref channel_binding_id"
	if !sameWire(selectFields(receipt, bindingFields), selectFields(assignment, bindingFields)) {
		return result, errProviderBootstrap
	}
	receiptBytes, err := json.Marshal(receipt)
	if err != nil {
		return result, errProviderBootstrap
	}
	if _, err := checkTime(); err != nil || !closeOnTimeout() {
		return result, errProviderBootstrap
	}
	return ProviderAdmission{intentBytes, descriptorBytes, receiptBytes}, nil
}

func bootstrapPipes(input, output *os.File) bool {
	first, firstErr := input.Stat()
	second, secondErr := output.Stat()
	return firstErr == nil && secondErr == nil && first.Mode()&os.ModeNamedPipe != 0 && second.Mode()&os.ModeNamedPipe != 0
}

func checkedLaunch(intentBytes, descriptorBytes []byte) (wireObject, wireObject, error) {
	intent, descriptor := canonicalObject(intentBytes), canonicalObject(descriptorBytes)
	manifest, _ := intent["artifact_manifest_ref"].(map[string]any)
	containment, _ := intent["containment_ref"].(map[string]any)
	devices, validDevices := intent["device_ids"].([]any)
	manifestDigest, _ := manifest["digest"].(string)
	bootIdentity, _ := descriptor["os_boot_identity"].(map[string]any)
	bootValid := fields(bootIdentity, "status") && bootIdentity["status"] == "unavailable" ||
		fields(bootIdentity, "status source value evidence_ref") && bootIdentity["status"] == "verified" && publicIDs(bootIdentity, "source value evidence_ref")
	backend, container := "windows_interrupt_precise", "windows_job"
	if runtime.GOOS == "linux" {
		backend, container = "linux_boottime", "linux_cgroup_v2"
	}
	if !fields(intent, "launch_id service_id supervisor_instance_id runtime_generation member_id role artifact_manifest_ref containment_ref device_ids policy_revision") ||
		!ids(intent, "launch_id service_id supervisor_instance_id runtime_generation member_id") ||
		intent["role"] != bootstrapRole || !validDevices || len(devices) != 0 || !bootstrapRevision(intent["policy_revision"]) ||
		!fields(manifest, "manifest_id revision digest") || !ids(manifest, "manifest_id") || !bootstrapRevision(manifest["revision"]) || !validDigest(manifestDigest) ||
		!fields(containment, "group_id generation backend") || !ids(containment, "group_id generation") || containment["backend"] != container ||
		containment["generation"] != intent["runtime_generation"] ||
		!fields(descriptor, "descriptor_version domain_kind authority_service_id runtime_generation supervisor_instance_id clock_backend_id clock_backend_revision tick_unit suspend_accounting namespace_identity os_boot_identity platform_profile_id platform_profile_revision clock_domain_id descriptor_digest") ||
		!publicIDs(descriptor, "authority_service_id runtime_generation supervisor_instance_id clock_backend_revision namespace_identity platform_profile_id") ||
		!bootstrapRevision(descriptor["platform_profile_revision"]) || !bootValid ||
		descriptor["descriptor_version"] != "clock-domain/1" || descriptor["domain_kind"] != "supervised_runtime" ||
		descriptor["clock_backend_id"] != backend || descriptor["tick_unit"] != "ns" || descriptor["suspend_accounting"] != "included" ||
		descriptor["authority_service_id"] != intent["service_id"] || descriptor["runtime_generation"] != intent["runtime_generation"] ||
		descriptor["supervisor_instance_id"] != intent["supervisor_instance_id"] ||
		(runtime.GOOS == "windows" && descriptor["namespace_identity"] != "windows-global") {
		return nil, nil, errProviderBootstrap
	}
	body := selectFields(descriptor, "descriptor_version domain_kind authority_service_id runtime_generation supervisor_instance_id clock_backend_id clock_backend_revision tick_unit suspend_accounting namespace_identity os_boot_identity platform_profile_id platform_profile_revision")
	raw, err := json.Marshal(body)
	digest := hashWire(raw)
	if err != nil || descriptor["descriptor_digest"] != digest || descriptor["clock_domain_id"] != "clock_"+digest[7:] {
		return nil, nil, errProviderBootstrap
	}
	return intent, descriptor, nil
}

func writeProof(output *os.File, assignment, descriptor wireObject, key []byte) error {
	proof := selectFields(assignment, "bootstrap_version bootstrap_id launch_id launch_intent_digest member_id member_boot_id role artifact_manifest_ref channel_binding_id challenge_id")
	proof["clock_domain_id"], proof["descriptor_digest"] = descriptor["clock_domain_id"], descriptor["descriptor_digest"]
	projection := selectFields(proof, "bootstrap_version bootstrap_id launch_id launch_intent_digest member_id member_boot_id role artifact_manifest_ref channel_binding_id challenge_id clock_domain_id descriptor_digest")
	for _, name := range []string{"challenge_nonce", "issued_tick_ns", "expires_tick_ns"} {
		projection[name] = assignment[name]
	}
	raw, err := json.Marshal(projection)
	if err != nil {
		return errProviderBootstrap
	}
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte("leafseamer-bootstrap-proof/v1\x00"))
	mac.Write(raw)
	proof["proof"] = base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	wire, err := json.Marshal(wireObject{"version": bootstrapVersion, "type": "PROOF", "payload": proof})
	if err != nil {
		return errProviderBootstrap
	}
	wire = append(wire, '\n')
	if written, err := output.Write(wire); err != nil || written != len(wire) {
		return errProviderBootstrap
	}
	return nil
}

func readBootstrap(reader *bufio.Reader, messageType string) (wireObject, error) {
	line, err := reader.ReadSlice('\n')
	if err != nil || len(line) < 2 || len(line) > bootstrapLimit+1 || reader.Buffered() != 0 {
		return nil, errProviderBootstrap
	}
	frame := canonicalObject(line[:len(line)-1])
	value, valid := frame["payload"].(map[string]any)
	if !valid || !fields(frame, "version type payload") || frame["version"] != bootstrapVersion || frame["type"] != messageType {
		return nil, errProviderBootstrap
	}
	return value, nil
}

func canonicalObject(raw []byte) wireObject {
	if len(raw) == 0 || len(raw) > bootstrapLimit {
		return nil
	}
	var value wireObject
	if err := json.Unmarshal(raw, &value); err != nil || value == nil {
		return nil
	}
	canonical, err := json.Marshal(value)
	if err != nil || !bytes.Equal(raw, canonical) {
		return nil
	}
	return value
}

func fields(value wireObject, names string) bool {
	if len(value) != strings.Count(names, " ")+1 {
		return false
	}
	for name := range strings.SplitSeq(names, " ") {
		if _, ok := value[name]; !ok {
			return false
		}
	}
	return true
}

func selectFields(value wireObject, names string) wireObject {
	selected := wireObject{}
	for name := range strings.SplitSeq(names, " ") {
		selected[name] = value[name]
	}
	return selected
}

func ids(value wireObject, names string) bool       { return validIDs(value, names, false) }
func publicIDs(value wireObject, names string) bool { return validIDs(value, names, true) }

func validIDs(value wireObject, names string, public bool) bool {
	for name := range strings.SplitSeq(names, " ") {
		id, _ := value[name].(string)
		if len(id) == 0 || len(id) > 128 {
			return false
		}
		for i, c := range id {
			alphanumeric := c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9'
			punctuation := c == '.' || c == '-' || c == '_' || (!public && c == ':')
			if !alphanumeric && (!(public || i > 0) || !punctuation) {
				return false
			}
		}
	}
	return true
}

func bootstrapUint(value any) (uint64, bool) {
	text, _ := value.(string)
	parsed, err := strconv.ParseUint(text, 10, 64)
	return parsed, err == nil && strconv.FormatUint(parsed, 10) == text
}

func bootstrapRevision(value any) bool {
	text, _ := value.(string)
	return len(text) >= 1 && len(text) <= 20 && (len(text) == 1 || text[0] != '0') &&
		strings.IndexFunc(text, func(c rune) bool { return c < '0' || c > '9' }) < 0
}

func bootstrapSecret(value any) ([]byte, bool) {
	text, _ := value.(string)
	if len(text) != 43 {
		return nil, false
	}
	decoded, err := base64.RawURLEncoding.Strict().DecodeString(text)
	return decoded, err == nil && len(decoded) == 32
}

func validDigest(text string) bool {
	if len(text) != 71 || !strings.HasPrefix(text, "sha256:") || strings.ToLower(text) != text {
		return false
	}
	_, err := hex.DecodeString(text[7:])
	return err == nil
}

func hashWire(raw []byte) string { return fmt.Sprintf("sha256:%x", sha256.Sum256(raw)) }

func sameWire(a, b any) bool {
	left, leftErr := json.Marshal(a)
	right, rightErr := json.Marshal(b)
	return leftErr == nil && rightErr == nil && bytes.Equal(left, right)
}
