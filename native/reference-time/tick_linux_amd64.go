package collector

import (
	"math"
	"time"

	"golang.org/x/sys/unix"
)

func nativeTick() (uint64, error) {
	var value unix.Timespec
	const units = uint64(time.Second)
	if err := unix.ClockGettime(unix.CLOCK_BOOTTIME, &value); err != nil ||
		value.Sec < 0 || value.Nsec < 0 || value.Nsec >= int64(units) ||
		uint64(value.Sec) > (math.MaxUint64-uint64(value.Nsec))/units {
		return 0, errClock
	}
	return uint64(value.Sec)*units + uint64(value.Nsec), nil
}
