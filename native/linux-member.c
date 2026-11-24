#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/capability.h>
#include <linux/magic.h>
#include <linux/openat2.h>
#include <linux/sched.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/vfs.h>
#include <sys/wait.h>
#include <sys/xattr.h>
#include <unistd.h>
#include <grp.h>

static const char cgroup_root[] = "/sys/fs/cgroup";
static const char cgroup_prefix[] = "/sys/fs/cgroup/";
enum { boot_fd = 3, timeout_ms = 10000 };

static bool decimal(const char *text, uint64_t *out) {
  if (!*text || (*text == '0' && text[1]) || strspn(text, "0123456789") != strlen(text)) return false;
  errno = 0;
  *out = strtoull(text, NULL, 10);
  return errno == 0;
}

static int open_relative(int root, const char *path, uint64_t flags, bool same_mount) {
  struct open_how how = {
    .flags = flags | O_CLOEXEC,
    .resolve = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | (same_mount ? RESOLVE_NO_XDEV : 0),
  };
  return (int)syscall(SYS_openat2, root, path, &how, sizeof(how));
}

static bool identified(int fd, uint64_t device, uint64_t inode, struct stat *info) {
  return fd >= 0 && fstat(fd, info) == 0 && info->st_nlink > 0 &&
    (uint64_t)info->st_dev == device && (uint64_t)info->st_ino == inode;
}

static bool checked_group(int root, const char *path, uint64_t device, uint64_t inode) {
  int fd = open_relative(root, path, O_RDONLY | O_DIRECTORY, true);
  struct stat info;
  bool matches = identified(fd, device, inode, &info);
  if (fd >= 0) close(fd);
  return matches;
}

static bool protected_controls(int directory, uid_t uid) {
  struct stat group, procs;
  return fstat(directory, &group) == 0 && group.st_uid != uid && !(group.st_mode & 0022) &&
    (group.st_uid == 0 || group.st_uid == geteuid()) &&
    fstatat(directory, "cgroup.procs", &procs, AT_SYMLINK_NOFOLLOW) == 0 &&
    S_ISREG(procs.st_mode) && procs.st_uid != uid && !(procs.st_mode & 0022) &&
    (procs.st_uid == 0 || procs.st_uid == geteuid());
}

static bool protected_ancestors(int root, const char *group, uid_t uid) {
  char path[PATH_MAX];
  size_t length = strlen(group);
  if (length >= sizeof(path) || !protected_controls(root, uid)) return false;
  memcpy(path, group, length + 1);
  for (char *part = path; ; ++part) {
    if (*part != '/' && *part != '\0') continue;
    char separator = *part;
    *part = '\0';
    int directory = open_relative(root, path, O_RDONLY | O_DIRECTORY, true);
    bool valid = directory >= 0 && protected_controls(directory, uid);
    if (directory >= 0) close(directory);
    if (!valid || separator == '\0') return valid;
    *part = separator;
  }
}

static bool no_file_capabilities(int fd) {
  return fgetxattr(fd, "security.capability", NULL, 0) < 0 && (errno == ENODATA || errno == EOPNOTSUPP);
}

static bool inherited_socket(int fd, struct stat *identity) {
  int type, domain;
  socklen_t size = sizeof(int);
  if (getsockopt(fd, SOL_SOCKET, SO_TYPE, &type, &size) < 0 || type != SOCK_STREAM) return false;
  size = sizeof(int);
  struct sockaddr_storage peer;
  socklen_t peer_size = sizeof(peer);
  return getsockopt(fd, SOL_SOCKET, SO_DOMAIN, &domain, &size) == 0 && domain == AF_UNIX &&
    getpeername(fd, (struct sockaddr *)&peer, &peer_size) == 0 && peer.ss_family == AF_UNIX &&
    fstat(fd, identity) == 0 && S_ISSOCK(identity->st_mode);
}

static bool member_channels(int last_fd) {
  struct stat identities[3];
  for (int fd = boot_fd; fd <= last_fd; ++fd) {
    struct stat *current = &identities[fd - boot_fd];
    if (!inherited_socket(fd, current)) return false;
    for (int prior = boot_fd; prior < fd; ++prior)
      if (current->st_dev == identities[prior - boot_fd].st_dev && current->st_ino == identities[prior - boot_fd].st_ino)
        return false;
  }
  return true;
}

static bool child_identity(uid_t uid, gid_t gid, pid_t parent) {
  struct __user_cap_header_struct header = { .version = _LINUX_CAPABILITY_VERSION_3 };
  struct __user_cap_data_struct caps[2] = {{0}};
  return setgroups(0, NULL) == 0 && setresgid(gid, gid, gid) == 0 && setresuid(uid, uid, uid) == 0 &&
    prctl(PR_SET_PDEATHSIG, SIGKILL, 0L, 0L, 0L) == 0 && getppid() == parent &&
    syscall(SYS_capset, &header, caps) == 0 && prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL, 0L, 0L, 0L) == 0 &&
    prctl(PR_SET_NO_NEW_PRIVS, 1L, 0L, 0L, 0L) == 0;
}

static _Noreturn void child_run(int image, int null_fd, int release, int status, int last_fd, uid_t uid, gid_t gid,
                               pid_t parent, char **args) {
  if (prctl(PR_SET_PDEATHSIG, SIGKILL, 0L, 0L, 0L) < 0 || getppid() != parent ||
      !child_identity(uid, gid, parent) ||
      syscall(SYS_close_range, (unsigned)last_fd + 1U, ~0U, CLOSE_RANGE_CLOEXEC) < 0 ||
      dup2(null_fd, STDIN_FILENO) < 0 ||
      dup2(null_fd, STDOUT_FILENO) < 0 || dup2(null_fd, STDERR_FILENO) < 0 ||
      chdir("/") < 0 || signal(SIGPIPE, SIG_DFL) == SIG_ERR) _exit(125);
  for (int fd = boot_fd; fd <= last_fd; ++fd)
    if (fcntl(fd, F_SETFD, 0) < 0) _exit(125);
  umask(077);
  char go;
  if (write(status, "C", 1) != 1 || read(release, &go, 1) != 1 || go != 'R') _exit(125);
  close(release);
  char *const environment[] = {"LANG=C", "LC_ALL=C", "PATH=/usr/bin:/bin", NULL};
  syscall(SYS_execveat, image, "", args, environment, AT_EMPTY_PATH);
  if (write(status, "E", 1) < 0) _exit(126);
  _exit(126);
}

static bool member_in_group(pid_t pid, const char *group) {
  char filename[64], actual[4096], expected[4096];
  snprintf(filename, sizeof(filename), "/proc/%jd/cgroup", (intmax_t)pid);
  int length = snprintf(expected, sizeof(expected), "0::/%s\n", group);
  if (length < 0 || (size_t)length >= sizeof(expected)) return false;
  int file = open(filename, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
  if (file < 0) return false;
  ssize_t count = read(file, actual, sizeof(actual));
  close(file);
  return count == length && memcmp(actual, expected, (size_t)length) == 0;
}

static bool poll_member(int channel, int pidfd) {
  struct pollfd readiness[] = {{ .fd = channel, .events = POLLIN }, { .fd = pidfd, .events = POLLIN }};
  return poll(readiness, 2, timeout_ms) > 0 && readiness[1].revents == 0 &&
    (readiness[0].revents & (POLLIN | POLLHUP)) != 0;
}

static bool populated(int group, bool expected_empty) {
  int file = openat(group, "cgroup.events", O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
  if (file < 0) return false;
  char events[256];
  ssize_t count = read(file, events, sizeof(events) - 1);
  close(file);
  if (count <= 0) return false;
  events[count] = '\0';
  return strncmp(events, expected_empty ? "populated 0\n" : "populated 1\n", 12) == 0;
}

static bool report_member(const char *phase, pid_t pid, const struct stat *group, const struct stat *image) {
  return printf("{\"phase\":\"%s\",\"pid\":%jd,\"group_device\":\"%ju\",\"group_inode\":\"%ju\","
      "\"image_device\":\"%ju\",\"image_inode\":\"%ju\"}\n", phase, (intmax_t)pid,
      (uintmax_t)group->st_dev, (uintmax_t)group->st_ino, (uintmax_t)image->st_dev, (uintmax_t)image->st_ino) > 0 &&
    fflush(stdout) == 0;
}

static int reject(const char *phase) {
  fprintf(stderr, "%s\n", phase);
  return 1;
}

int main(int argc, char **argv) {
  uint64_t group_device, group_inode, image_device, image_inode, uid, gid;
  const size_t prefix_length = sizeof(cgroup_prefix) - 1;
  bool worker = argc > 10 && strcmp(argv[9], "--device-worker") == 0;
  int delimiter = worker ? 10 : 9, last_fd = worker ? 5 : boot_fd;
  if (argc <= delimiter || argc > delimiter + 65 || strncmp(argv[1], cgroup_prefix, prefix_length) != 0 ||
      !argv[1][prefix_length] || argv[4][0] != '/' || !argv[4][1] ||
      !decimal(argv[2], &group_device) || !decimal(argv[3], &group_inode) ||
      !decimal(argv[5], &image_device) || !decimal(argv[6], &image_inode) ||
      !decimal(argv[7], &uid) || !decimal(argv[8], &gid) ||
      uid == 0 || uid >= UINT32_MAX || gid == 0 || gid >= UINT32_MAX || strcmp(argv[delimiter], "--") != 0 ||
      !member_channels(last_fd) || signal(SIGCHLD, SIG_DFL) == SIG_ERR ||
      signal(SIGPIPE, SIG_IGN) == SIG_ERR) return reject("linux_member_inputs");

  int root = open(cgroup_root, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  int fs_root = open("/", O_DIRECTORY | O_RDONLY | O_CLOEXEC);
  if (root < 0 || fs_root < 0) return reject("linux_member_open");
  const char *group_path = argv[1] + prefix_length;
  int group = open_relative(root, group_path, O_RDONLY | O_DIRECTORY, true);
  int image = open_relative(fs_root, argv[4] + 1, O_RDONLY | O_NONBLOCK, false);
  int null_fd = open("/dev/null", O_RDWR | O_NOFOLLOW | O_CLOEXEC);
  struct stat group_info, image_info;
  struct statfs fs;
  if (!identified(group, group_device, group_inode, &group_info) || fstatfs(group, &fs) != 0 ||
      (unsigned long)fs.f_type != CGROUP2_SUPER_MAGIC || group_info.st_uid != geteuid() ||
      group_info.st_uid == uid || (group_info.st_mode & 0022) || flock(group, LOCK_EX | LOCK_NB) < 0 ||
      !protected_ancestors(root, group_path, (uid_t)uid) || !populated(group, true)) return reject("linux_member_group");
  unsigned char magic[4];
  if (!identified(image, image_device, image_inode, &image_info) || !S_ISREG(image_info.st_mode) || image_info.st_uid != 0 ||
      (image_info.st_mode & (S_ISUID | S_ISGID | 0022)) || !no_file_capabilities(image) ||
      pread(image, magic, sizeof(magic), 0) != (ssize_t)sizeof(magic) ||
      memcmp(magic, "\x7f" "ELF", sizeof(magic)) != 0 || null_fd < 0) return reject("linux_member_image");

  int release[2], status[2], pidfd = -1;
  if (pipe2(release, O_CLOEXEC) < 0 || pipe2(status, O_CLOEXEC) < 0) return reject("linux_member_channel");
  struct clone_args request = { .flags = CLONE_INTO_CGROUP | CLONE_PIDFD, .exit_signal = SIGCHLD,
    .pidfd = (uint64_t)(uintptr_t)&pidfd, .cgroup = (uint64_t)group };
  pid_t parent = getpid();
  pid_t pid = (pid_t)syscall(SYS_clone3, &request, sizeof(request));
  if (pid < 0) return reject("linux_member_clone");
  if (pid == 0) {
    close(release[1]);
    close(status[0]);
    argv[delimiter] = argv[4];
    child_run(image, null_fd, release[0], status[1], last_fd, (uid_t)uid, (gid_t)gid, parent, argv + delimiter);
  }
  for (int fd = boot_fd; fd <= last_fd; ++fd) close(fd);
  close(release[0]);
  close(status[1]);
  char message;
  bool released = false;
  if (poll_member(status[0], pidfd) && read(status[0], &message, 1) == 1 && message == 'C' &&
      member_in_group(pid, group_path) && populated(group, false) && checked_group(root, group_path, group_device, group_inode) &&
      report_member("created_closed", pid, &group_info, &image_info) &&
      poll_member(STDIN_FILENO, pidfd) && read(STDIN_FILENO, &message, 1) == 1 && message == 'R' &&
      member_in_group(pid, group_path) && checked_group(root, group_path, group_device, group_inode) &&
      protected_ancestors(root, group_path, (uid_t)uid))
    released = write(release[1], "R", 1) == 1;
  close(release[1]);
  if (!released) return reject("linux_member_closed");
  if (!poll_member(status[0], pidfd) || read(status[0], &message, 1) != 0 ||
      !member_in_group(pid, group_path) || !checked_group(root, group_path, group_device, group_inode) ||
      !report_member("executed", pid, &group_info, &image_info)) return reject("linux_member_exec");
  close(status[0]);
  struct pollfd live[] = {{ .fd = STDIN_FILENO, .events = POLLIN }, { .fd = pidfd, .events = POLLIN }};
  if (poll(live, 2, -1) < 0 || !live[1].revents) return reject("linux_member_control_closed");
  int result;
  if (waitpid(pid, &result, 0) != pid || !WIFEXITED(result)) return reject("linux_member_exit");
  return WEXITSTATUS(result);
}
