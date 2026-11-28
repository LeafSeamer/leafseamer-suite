package main

import (
	"os"

	"golang.org/x/sys/windows"
)

func syncArchiveDirectory(root *os.Root) error {
	expected, err := root.Stat(".")
	if err != nil {
		return err
	}
	name, err := windows.UTF16PtrFromString(root.Name())
	if err != nil {
		return err
	}
	handle, err := windows.CreateFile(name, windows.GENERIC_WRITE|windows.FILE_READ_ATTRIBUTES,
		windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE|windows.FILE_SHARE_DELETE, nil, windows.OPEN_EXISTING,
		windows.FILE_FLAG_BACKUP_SEMANTICS|windows.FILE_FLAG_OPEN_REPARSE_POINT, 0)
	if err != nil {
		return err
	}
	file := os.NewFile(uintptr(handle), root.Name())
	defer file.Close()
	actual, err := file.Stat()
	if err != nil || !actual.IsDir() || !os.SameFile(expected, actual) {
		return errDirectory
	}
	return file.Sync()
}

func inheritedLocalStream(*os.File, os.FileMode) bool {
	return false
}
