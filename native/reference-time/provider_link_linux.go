package collector

import (
	"os"
	"strconv"
	"strings"
	"unsafe"

	"golang.org/x/sys/unix"
)

const providerRuntimeFormat = "leafseamer-time-provider-runtime-binding/2"
const providerLinkFD = 3

// The supervisor creates a private socketpair before launching the provider and
// retains its end for the PID-bound relay. There is no pathname to reconnect to.
func openProviderLink(string) (*os.File, error) {
	if !privateSupervisorLink(providerLinkFD, os.Getppid()) {
		return nil, errProviderLink
	}
	unix.CloseOnExec(providerLinkFD)
	if unix.SetNonblock(providerLinkFD, true) != nil {
		return nil, errProviderLink
	}
	return os.NewFile(uintptr(providerLinkFD), "reference-provider-link"), nil
}

func privateSupervisorLink(fd, parentPID int) bool {
	if parentPID <= 1 {
		return false
	}
	kind, err := unix.GetsockoptInt(fd, unix.SOL_SOCKET, unix.SO_TYPE)
	if err != nil || kind != unix.SOCK_STREAM {
		return false
	}
	peer, err := unix.GetsockoptUcred(fd, unix.SOL_SOCKET, unix.SO_PEERCRED)
	if err != nil || int(peer.Pid) != parentPID {
		return false
	}
	return unnamedUnixAddress(fd, unix.SYS_GETSOCKNAME) && unnamedUnixAddress(fd, unix.SYS_GETPEERNAME)
}

func unnamedUnixAddress(fd int, operation uintptr) bool {
	var address unix.RawSockaddrUnix
	size := uint32(unsafe.Sizeof(address))
	// Check the returned length to distinguish an unnamed socket from an empty
	// abstract address, which starts with a NUL byte and has a longer sockaddr.
	_, _, err := unix.Syscall(operation, uintptr(fd), uintptr(unsafe.Pointer(&address)), uintptr(unsafe.Pointer(&size)))
	return err == 0 && address.Family == unix.AF_UNIX && size == uint32(unsafe.Offsetof(address.Path))
}

func validProviderObservation(observation wireObject) bool {
	if !fields(observation, "image_device image_inode observation_id observed_tick_ns provider_pid start_ticks") {
		return false
	}
	var image unix.Stat_t
	if unix.Stat("/proc/self/exe", &image) != nil {
		return false
	}
	stat, err := os.ReadFile("/proc/self/stat")
	if err != nil {
		return false
	}
	// The parenthesized executable name can contain both spaces and parentheses.
	end := strings.LastIndexByte(string(stat), ')')
	if end < 0 {
		return false
	}
	fieldsAfterName := strings.Fields(string(stat[end+1:]))
	return len(fieldsAfterName) > 19 && observation["start_ticks"] == fieldsAfterName[19] &&
		observation["image_device"] == strconv.FormatUint(uint64(image.Dev), 10) &&
		observation["image_inode"] == strconv.FormatUint(image.Ino, 10)
}
