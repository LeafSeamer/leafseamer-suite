#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/close_range.h>
#include <poll.h>
#include <signal.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/un.h>
#include <unistd.h>

static int number(const char *text, uint32_t *value) {
  if (*text < '0' || *text > '9') return 0;
  char *end;
  errno = 0;
  uintmax_t parsed = strtoumax(text, &end, 10);
  if (errno || *end || parsed >= UINT32_MAX) return 0;
  *value = (uint32_t)parsed;
  return 1;
}

static socklen_t address(struct sockaddr_un *endpoint, const char *name) {
  size_t length = strlen(name);
  if (name[0] != '/' || length >= sizeof(endpoint->sun_path)) return 0;
  *endpoint = (struct sockaddr_un){.sun_family = AF_UNIX};
  memcpy(endpoint->sun_path, name, length + 1);
  return (socklen_t)(offsetof(struct sockaddr_un, sun_path) + length + 1);
}

static int credentials(int fd, struct ucred *value) {
  socklen_t length = sizeof(*value);
  return getsockopt(fd, SOL_SOCKET, SO_PEERCRED, value, &length) == 0 && length == sizeof(*value);
}

static int wait_poll(struct pollfd *fds, nfds_t count) {
  int n;
  do { n = poll(fds, count, -1); } while (n < 0 && errno == EINTR);
  return n;
}

struct buffer {
  unsigned char bytes[16384];
  size_t position, length;
};

static void relay(int peer) {
  const int streams[2] = {3, peer};
  struct buffer outgoing[2] = {0};
  for (;;) {
    struct pollfd waiting[3] = {{.fd = STDIN_FILENO, .events = POLLIN}};
    for (int i = 0; i < 2; i++) {
      waiting[i + 1].fd = streams[i];
      waiting[i + 1].events = POLLRDHUP | (outgoing[1-i].length == 0 ? POLLIN : 0) |
        (outgoing[i].length > 0 ? POLLOUT : 0);
    }
    if (wait_poll(waiting, 3) < 0 || waiting[0].revents) return;
    for (int i = 1; i <= 2; i++) if (waiting[i].revents & (POLLERR|POLLHUP|POLLRDHUP|POLLNVAL)) return;
    for (int i = 0; i < 2; i++) {
      struct buffer *write_to = &outgoing[i], *read_into = &outgoing[1-i];
      if (waiting[i + 1].revents & POLLOUT) {
        ssize_t n = send(streams[i], write_to->bytes + write_to->position,
          write_to->length - write_to->position, MSG_DONTWAIT | MSG_NOSIGNAL);
        if (!n || (n < 0 && errno != EAGAIN && errno != EINTR)) return;
        if (n > 0) {
          write_to->position += (size_t)n;
          if (write_to->position == write_to->length) write_to->position = write_to->length = 0;
        }
      }
      if (waiting[i + 1].revents & POLLIN) {
        ssize_t n = recv(streams[i], read_into->bytes, sizeof(read_into->bytes), MSG_DONTWAIT);
        if (!n || (n < 0 && errno != EAGAIN && errno != EINTR)) return;
        if (n > 0) read_into->length = (size_t)n;
      }
    }
  }
}

static int listen_channel(const char *name, uint32_t uid, uint32_t gid) {
  struct sockaddr_un endpoint;
  socklen_t length = address(&endpoint, name);
  struct ucred control;
  if (!length || !uid || !gid || !credentials(3, &control)) return 1;
  int server = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
  if (server < 0) return 1;
  umask(0177);
  if (bind(server, (struct sockaddr *)&endpoint, length) < 0 || chown(name, geteuid(), (gid_t)gid) < 0 ||
      chmod(name, 0660) < 0 || listen(server, 1) < 0 || dprintf(STDOUT_FILENO, "ready\n") < 0) return 1;
  struct pollfd pending[] = {{.fd = STDIN_FILENO, .events = POLLIN}, {.fd = 3, .events = POLLRDHUP},
                             {.fd = server, .events = POLLIN}};
  if (wait_poll(pending, 3) < 0 || pending[0].revents || pending[1].revents || pending[2].revents != POLLIN) return 1;
  int peer = accept4(server, NULL, NULL, SOCK_CLOEXEC);
  close(server);
  struct ucred identity;
  if (peer < 0 || !credentials(peer, &identity) || identity.pid <= 1 || identity.uid != uid || identity.gid != gid ||
      dprintf(STDOUT_FILENO, "peer %jd\n", (intmax_t)identity.pid) < 0) return 1;
  pending[2] = (struct pollfd){.fd = peer, .events = POLLIN | POLLRDHUP};
  if (wait_poll(pending, 3) < 0 || pending[0].revents != POLLIN || pending[1].revents || pending[2].revents) return 1;
  char decision;
  if (read(STDIN_FILENO, &decision, 1) != 1 || decision != 'A' || dprintf(STDOUT_FILENO, "opened\n") < 0) return 1;
  relay(peer);
  return 0;
}

static int protected_path(const char *name, uint32_t owner) {
  struct sockaddr_un endpoint;
  if (!address(&endpoint, name)) return 0;
  char *component = endpoint.sun_path + 1;
  for (;;) {
    char *slash = strchr(component, '/');
    if (slash) *slash = '\0';
    if (!*component || !strcmp(component, ".") || !strcmp(component, "..")) return 0;
    if (!slash) return 1;
    struct stat parent;
    if (lstat(endpoint.sun_path, &parent) < 0 || !S_ISDIR(parent.st_mode) ||
        (parent.st_uid && parent.st_uid != owner) || (parent.st_mode & 0022)) return 0;
    *slash = '/';
    component = slash + 1;
  }
}

static int connect_channel(const char *name, uint32_t owner, char **program) {
  struct sockaddr_un endpoint;
  socklen_t length = address(&endpoint, name);
  struct stat file;
  if (getpid() != 1 || !getuid() || !getgid() || !length || !protected_path(name, owner) || lstat(name, &file) < 0 ||
      !S_ISSOCK(file.st_mode) || file.st_uid != owner || (file.st_mode & 0007) || program[0][0] != '/') return 1;
  int connection = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
  struct ucred peer;
  struct stat current;
  if (connection < 0 || connect(connection, (struct sockaddr *)&endpoint, length) < 0 ||
      !credentials(connection, &peer) || peer.uid != owner || lstat(name, &current) < 0 ||
      current.st_dev != file.st_dev || current.st_ino != file.st_ino ||
      dup2(connection, 3) < 0 || fcntl(3, F_SETFD, 0) < 0 ||
      syscall(SYS_close_range, 4U, ~0U, CLOSE_RANGE_CLOEXEC) < 0) return 1;
  execv(program[0], program);
  return 1;
}

int main(int argc, char **argv) {
  uint32_t uid, gid;
  if (argc == 5 && strcmp(argv[1], "listen") == 0 && number(argv[3], &uid) && number(argv[4], &gid))
    return listen_channel(argv[2], uid, gid);
  if (argc >= 6 && strcmp(argv[1], "connect") == 0 && number(argv[3], &uid) && strcmp(argv[4], "--") == 0)
    return connect_channel(argv[2], uid, argv + 5);
  return 1;
}
