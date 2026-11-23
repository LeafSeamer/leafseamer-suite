package collector

import (
	"bufio"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"strings"
	"time"
)

const providerLinkVersion = "time-provider-link/1"

var errProviderLink = errors.New("reference time provider link refused")

// RunProviderLink binds the dedicated connection to the admitted process and
// the core's durable runtime record and waits for individually authorized polls.
func RunProviderLink(ctx context.Context, admission ProviderAdmission, coreReceiptID, databaseInstanceID string, timeout time.Duration) error {
	receipt := canonicalObject(admission.Receipt)
	boot, _ := receipt["member_boot_id"].(string)
	if len(boot) != 32 || strings.ToLower(boot) != boot {
		return errProviderLink
	}
	if _, err := hex.DecodeString(boot); err != nil {
		return errProviderLink
	}
	if !ids(wireObject{"core": coreReceiptID, "database": databaseInstanceID}, "core database") {
		return errProviderLink
	}
	file, err := openProviderLink(boot)
	if err != nil {
		return err
	}
	defer file.Close()
	stop := context.AfterFunc(ctx, func() { file.Close() })
	defer stop()
	if err := file.SetDeadline(time.Now().Add(timeout)); err != nil {
		return err
	}
	reader := bufio.NewReaderSize(file, bootstrapLimit+2)
	line, err := reader.ReadSlice('\n')
	if err != nil || reader.Buffered() != 0 {
		return errProviderLink
	}
	reply, err := providerLinkReply(line[:len(line)-1], admission, coreReceiptID, databaseInstanceID, os.Getpid())
	if err != nil {
		return err
	}
	frame := canonicalObject(line[:len(line)-1])
	binding, _ := frame["binding"].(map[string]any)
	serviceBoot, _ := binding["service_boot_id"].(string)
	bound := canonicalObject(reply)
	digest, _ := bound["binding_digest"].(string)
	auth := providerAuthentication{file: file, reader: reader, bindingDigest: digest,
		domain: selectFields(canonicalObject(admission.Descriptor), "clock_domain_id descriptor_digest")}
	// Confirm the read-only bridge before entering the idle, closed state.
	if _, err := auth.read(ctx); err != nil && !errors.Is(err, errBootstrap) {
		return err
	}
	if err := file.SetWriteDeadline(time.Now().Add(providerAuthTimeout)); err != nil {
		return err
	}
	if _, err := file.Write(append(reply, '\n')); err != nil {
		return err
	}
	return serveProviderPolls(ctx, &auth, serviceBoot)
}

func providerLinkReply(raw []byte, admission ProviderAdmission, coreReceiptID, databaseInstanceID string, pid int) ([]byte, error) {
	frame := canonicalObject(raw)
	body, _ := frame["binding"].(map[string]any)
	digest, _ := frame["binding_digest"].(string)
	intent := canonicalObject(admission.Intent)
	descriptor := canonicalObject(admission.Descriptor)
	receipt := canonicalObject(admission.Receipt)
	if len(intent) == 0 || len(descriptor) == 0 || len(receipt) == 0 ||
		!fields(frame, "binding binding_digest request_id type version") || !ids(frame, "request_id") ||
		frame["version"] != providerLinkVersion || frame["type"] != "BIND" || !validDigest(digest) ||
		!fields(body, "admission_receipt clock_domain_descriptor core_receipt_id database_instance_id format gate_state launch_intent process_observation runtime_binding_id service_boot_id service_id") ||
		!ids(body, "service_boot_id") || body["format"] != "leafseamer-time-provider-runtime-binding/1" ||
		body["gate_state"] != "closed" || body["core_receipt_id"] != coreReceiptID ||
		body["database_instance_id"] != databaseInstanceID || body["service_id"] != intent["service_id"] ||
		!sameWire(body["launch_intent"], intent) || !sameWire(body["clock_domain_descriptor"], descriptor) ||
		!sameWire(body["admission_receipt"], receipt) {
		return nil, errProviderLink
	}
	observation, _ := body["process_observation"].(map[string]any)
	observed, observedOK := bootstrapUint(observation["observed_tick_ns"])
	admitted, admittedOK := bootstrapUint(receipt["admitted_tick_ns"])
	created, createdOK := bootstrapUint(observation["creation_time_filetime"])
	image, _ := observation["image_id"].(string)
	if !fields(observation, "creation_time_filetime image_id observation_id observed_tick_ns provider_pid") ||
		observation["observation_id"] != receipt["os_observation_ref"] || observation["provider_pid"] != float64(pid) ||
		!observedOK || !admittedOK || observed > admitted || !createdOK || created == 0 ||
		len(image) != 48 || strings.ToLower(image) != image {
		return nil, errProviderLink
	}
	if _, err := hex.DecodeString(image); err != nil {
		return nil, errProviderLink
	}
	complete, err := json.Marshal(body)
	if err != nil || hashWire(complete) != digest {
		return nil, errProviderLink
	}
	bindingID := body["runtime_binding_id"]
	delete(body, "runtime_binding_id")
	original, err := json.Marshal(body)
	if err != nil || bindingID != "time-runtime."+strings.TrimPrefix(hashWire(original), "sha256:") {
		return nil, errProviderLink
	}
	return json.Marshal(wireObject{"binding_digest": digest, "reply_to": frame["request_id"], "type": "BOUND", "version": providerLinkVersion})
}
