package collector

import (
	"encoding/hex"
	"os"
	"strings"
	"syscall"

	"golang.org/x/sys/windows"
)

const providerRuntimeFormat = "leafseamer-time-provider-runtime-binding/1"

func validBootstrapStreams(input, output *os.File) bool { return bootstrapPipes(input, output) }

func openProviderLink(boot string) (*os.File, error) {
	return os.OpenFile(`\\.\pipe\LeafSeamer.TimeCollector.`+boot+".provider",
		os.O_RDWR|windows.FILE_FLAG_OVERLAPPED|syscall.O_CLOEXEC, 0)
}

func validProviderObservation(observation wireObject) bool {
	created, ok := bootstrapUint(observation["creation_time_filetime"])
	image, _ := observation["image_id"].(string)
	if !fields(observation, "creation_time_filetime image_id observation_id observed_tick_ns provider_pid") ||
		!ok || created == 0 || len(image) != 48 || strings.ToLower(image) != image {
		return false
	}
	_, err := hex.DecodeString(image)
	return err == nil
}
