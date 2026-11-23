package collector

import (
	"os"
	"syscall"

	"golang.org/x/sys/windows"
)

func openProviderLink(boot string) (*os.File, error) {
	return os.OpenFile(`\\.\pipe\LeafSeamer.TimeCollector.`+boot+".provider",
		os.O_RDWR|windows.FILE_FLAG_OVERLAPPED|syscall.O_CLOEXEC, 0)
}
