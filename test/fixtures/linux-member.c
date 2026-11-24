#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

static int deny_creation(char **argv) {
  struct sock_filter filter[] = {
    BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_clone3, 0, 1),
    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EACCES),
    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
  };
  struct sock_fprog program = { .len = sizeof(filter) / sizeof(filter[0]), .filter = filter };
  if (prctl(PR_SET_NO_NEW_PRIVS, 1L, 0L, 0L, 0L) < 0 ||
      prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program) < 0) return 2;
  execv(argv[0], argv);
  return 2;
}

static int cannot_write(const char *filename) {
  int fd = open(filename, O_WRONLY | O_CLOEXEC);
  if (fd < 0) return errno == EACCES || errno == EPERM;
  close(fd);
  return 0;
}

int main(int argc, char **argv) {
  if (argc > 3 && strcmp(argv[1], "deny-clone3") == 0) return deny_creation(argv + 2);
  int fork_child = argc == 4 && strcmp(argv[3], "keep-descendant") == 0;
  if ((argc != 3 && !fork_child) || !cannot_write(argv[1]) || !cannot_write(argv[2])) return 3;
  for (int fd = 4; fd < 64; ++fd)
    if (fcntl(fd, F_GETFD) >= 0 || errno != EBADF) return 4;
  if (fork_child) {
    pid_t child = fork();
    if (child < 0) return 5;
    if (child == 0) {
      close(3);
      for (;;) pause();
    }
    if (dprintf(3, "descendant %ld\n", (long)child) < 0) return 5;
  } else if (write(3, "application_entered\n", 20) != 20) return 5;
  char done;
  return read(3, &done, 1) == 1 && done == 'Q' ? 0 : 6;
}
