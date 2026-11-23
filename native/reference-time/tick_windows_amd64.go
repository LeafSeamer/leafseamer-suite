package collector

import (
	"fmt"
	"math"
	"unsafe"

	"golang.org/x/sys/windows"
)

// Match the API set used by the existing native clock.
var interruptTime = windows.NewLazySystemDLL("api-ms-win-core-realtime-l1-1-1.dll").NewProc("QueryInterruptTimePrecise")

func nativeTick() (uint64, error) {
	if err := interruptTime.Find(); err != nil {
		return 0, fmt.Errorf("%w: %v", errClock, err)
	}
	// QueryInterruptTimePrecise returns no status and writes units of 100 ns.
	var count uint64
	interruptTime.Call(uintptr(unsafe.Pointer(&count)))
	if count > math.MaxUint64/100 {
		return 0, errClock
	}
	return count * 100, nil
}
