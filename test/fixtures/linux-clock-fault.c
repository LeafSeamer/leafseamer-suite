#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/timerfd.h>
#include <time.h>
#include <unistd.h>

// The isolated test process injects an error only into its absolute realtime monitor.
static int monitored = -1;
static unsigned checks = 0;
static unsigned boot_reads = 0;

int clock_gettime(clockid_t clock, struct timespec *value) {
  int (*next)(clockid_t, struct timespec *) = dlsym(RTLD_NEXT, "clock_gettime");
  if (clock != CLOCK_BOOTTIME)
    return next(clock, value);

  ++boot_reads;
  const char *mode = getenv("LEAFSEAMER_TEST_SUSPEND_MONITOR");
  if (mode && boot_reads == 1 && strcmp(mode, "read") == 0) {
    errno = EIO;
    return -1;
  }
  const int result = next(clock, value);
  if (result == 0 && mode &&
      ((boot_reads == 7 && strcmp(mode, "before") == 0) || (boot_reads == 10 && strcmp(mode, "after") == 0)))
    value->tv_sec += 1;
  return result;
}

int timerfd_settime(int fd, int flags, const struct itimerspec *value, struct itimerspec *old_value) {
  int (*next)(int, int, const struct itimerspec *, struct itimerspec *) = dlsym(RTLD_NEXT, "timerfd_settime");
  if (flags == (TFD_TIMER_ABSTIME | TFD_TIMER_CANCEL_ON_SET)) {
    const char *mode = getenv("LEAFSEAMER_TEST_WALL_MONITOR");
    if (mode && strcmp(mode, "arm") == 0) {
      errno = EPERM;
      return -1;
    }
    monitored = fd;
  }
  return next(fd, flags, value, old_value);
}

ssize_t read(int fd, void *bytes, size_t count) {
  ssize_t (*next)(int, void *, size_t) = dlsym(RTLD_NEXT, "read");
  if (fd == monitored) {
    ++checks;
    const char *mode = getenv("LEAFSEAMER_TEST_WALL_MONITOR");
    if (mode && ((checks == 3 && strcmp(mode, "before") == 0) || (checks == 4 && strcmp(mode, "after") == 0))) {
      errno = ECANCELED;
      return -1;
    }
    if (mode && checks == 3 && strcmp(mode, "read") == 0) {
      errno = EIO;
      return -1;
    }
  }
  return next(fd, bytes, count);
}
