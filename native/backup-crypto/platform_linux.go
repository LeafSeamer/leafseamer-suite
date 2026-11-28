package main

import (
	"os"
	"unsafe"

	"golang.org/x/sys/unix"
)

func syncArchiveDirectory(root *os.Root) error {
	file, err := root.Open(".")
	if err != nil {
		return err
	}
	defer file.Close()
	return file.Sync()
}

func inheritedLocalStream(file *os.File, mode os.FileMode) bool {
	if mode&os.ModeSocket == 0 {
		return false
	}
	raw, err := file.SyscallConn()
	if err != nil {
		return false
	}
	var accepted bool
	err = raw.Control(func(descriptor uintptr) {
		kind, kindError := unix.GetsockoptInt(int(descriptor), unix.SOL_SOCKET, unix.SO_TYPE)
		accepted = kindError == nil && kind == unix.SOCK_STREAM &&
			unnamedUnix(descriptor, unix.SYS_GETSOCKNAME) && unnamedUnix(descriptor, unix.SYS_GETPEERNAME)
	})
	return err == nil && accepted
}

func unnamedUnix(descriptor, operation uintptr) bool {
	var address unix.RawSockaddrUnix
	size := uint32(unsafe.Sizeof(address))
	_, _, err := unix.Syscall(operation, descriptor, uintptr(unsafe.Pointer(&address)), uintptr(unsafe.Pointer(&size)))
	// An unnamed endpoint returns just the family; even an empty abstract name has a path byte.
	return err == 0 && address.Family == unix.AF_UNIX && size == uint32(unsafe.Offsetof(address.Path))
}
