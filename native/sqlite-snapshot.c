#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <sys/statvfs.h>
#endif

#include "sqlite3.h"

#define MAX_BYTES (UINT64_C(32) << 30)
#define SPACE_RESERVE (UINT64_C(2) << 30)
#define DEADLINE_MS (UINT64_C(30) * 60 * 1000)

struct scope {
    const char *authority;
    const char *service;
    const char *database;
    const char *request_epoch;
    const char *control_epoch;
    int schema;
    int application;
};

static uint64_t now_ms(void) {
#ifdef _WIN32
    LARGE_INTEGER ticks, frequency;
    if (!QueryPerformanceCounter(&ticks) || !QueryPerformanceFrequency(&frequency) || frequency.QuadPart <= 0)
        return UINT64_MAX;
    const uint64_t hz = (uint64_t)frequency.QuadPart, value = (uint64_t)ticks.QuadPart;
    return value / hz * 1000 + value % hz * 1000 / hz;
#else
    struct timespec time;
    if (clock_gettime(CLOCK_MONOTONIC, &time) != 0) return UINT64_MAX;
    return (uint64_t)time.tv_sec * 1000 + (uint64_t)time.tv_nsec / 1000000;
#endif
}

static int expired(void *deadline) {
    return now_ms() >= *(uint64_t *)deadline;
}

static bool pause_batches(void) {
    const uint64_t before = now_ms();
    if (before == UINT64_MAX) return false;
    do {
#ifdef _WIN32
        Sleep(51);
#else
        struct timespec wait = {0, 51000000};
        while (nanosleep(&wait, &wait) != 0) {
            if (errno != EINTR) return false;
        }
#endif
    } while (now_ms() < before + 51);
    return true;
}

static bool disk_has_space(const char *directory, uint64_t bytes) {
#ifdef _WIN32
    const int length = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, directory, -1, NULL, 0);
    if (length <= 0) return false;
    wchar_t *wide = malloc((size_t)length * sizeof(*wide));
    if (!wide) return false;
    ULARGE_INTEGER available;
    const bool ok = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, directory, -1, wide, length) &&
        GetDiskFreeSpaceExW(wide, &available, NULL, NULL) && available.QuadPart >= bytes;
    free(wide);
    return ok;
#else
    struct statvfs space;
    return statvfs(directory, &space) == 0 && space.f_frsize != 0 &&
        (uint64_t)space.f_bavail >= (bytes + space.f_frsize - 1) / space.f_frsize;
#endif
}

static bool number(sqlite3 *db, const char *sql, int *value) {
    sqlite3_stmt *query = NULL;
    bool ok = false;
    if (sqlite3_prepare_v2(db, sql, -1, &query, NULL) == SQLITE_OK &&
        sqlite3_step(query) == SQLITE_ROW && sqlite3_column_type(query, 0) == SQLITE_INTEGER) {
        *value = sqlite3_column_int(query, 0);
        ok = sqlite3_step(query) == SQLITE_DONE;
    }
    return sqlite3_finalize(query) == SQLITE_OK && ok;
}

static bool text_column(sqlite3_stmt *query, int column, const char *expected) {
    if (sqlite3_column_type(query, column) != SQLITE_TEXT) return false;
    const unsigned char *value = sqlite3_column_text(query, column);
    return value && (size_t)sqlite3_column_bytes(query, column) == strlen(expected) &&
        memcmp(value, expected, strlen(expected)) == 0;
}

static bool mode_or_integrity(sqlite3 *db, const char *sql, const char *value) {
    sqlite3_stmt *query = NULL;
    bool ok = sqlite3_prepare_v2(db, sql, -1, &query, NULL) == SQLITE_OK &&
        sqlite3_step(query) == SQLITE_ROW && text_column(query, 0, value) && sqlite3_step(query) == SQLITE_DONE;
    return sqlite3_finalize(query) == SQLITE_OK && ok;
}

static bool matches(sqlite3 *db, const struct scope *scope) {
    int application, schema;
    if (!number(db, "PRAGMA application_id", &application) || application != scope->application ||
        !number(db, "PRAGMA user_version", &schema) || schema != scope->schema) return false;
    const char *sql = scope->control_epoch[0]
        ? "SELECT singleton,authority,service_id,database_instance_id,request_epoch,schema_revision,control_epoch FROM service_state"
        : "SELECT singleton,authority,service_id,database_instance_id,request_epoch,schema_revision,'' FROM service_state";
    char revision[16];
    snprintf(revision, sizeof(revision), "%d", schema);
    sqlite3_stmt *query = NULL;
    bool ok = sqlite3_prepare_v2(db, sql, -1, &query, NULL) == SQLITE_OK &&
        sqlite3_step(query) == SQLITE_ROW && sqlite3_column_int(query, 0) == 1 &&
        text_column(query, 1, scope->authority) && text_column(query, 2, scope->service) &&
        text_column(query, 3, scope->database) && text_column(query, 4, scope->request_epoch) &&
        text_column(query, 5, revision) && text_column(query, 6, scope->control_epoch) &&
        sqlite3_step(query) == SQLITE_DONE;
    return sqlite3_finalize(query) == SQLITE_OK && ok;
}

static bool foreign_keys_valid(sqlite3 *db) {
    sqlite3_stmt *query = NULL;
    bool ok = sqlite3_prepare_v2(db, "PRAGMA foreign_key_check", -1, &query, NULL) == SQLITE_OK &&
        sqlite3_step(query) == SQLITE_DONE;
    return sqlite3_finalize(query) == SQLITE_OK && ok;
}

static bool open_database(sqlite3 **db, const char *file, int mode, uint64_t *deadline) {
    if (sqlite3_open_v2(file, db, mode | SQLITE_OPEN_NOFOLLOW, NULL) != SQLITE_OK) return false;
    sqlite3_progress_handler(*db, 10000, expired, deadline);
    return sqlite3_db_config(*db, SQLITE_DBCONFIG_DEFENSIVE, 1, NULL) == SQLITE_OK &&
        sqlite3_db_config(*db, SQLITE_DBCONFIG_TRUSTED_SCHEMA, 0, NULL) == SQLITE_OK &&
        sqlite3_busy_timeout(*db, 0) == SQLITE_OK;
}

static const char *copy_snapshot(sqlite3 *source, sqlite3 *target, const char *directory, int page_size, uint64_t *deadline) {
    sqlite3_backup *copy = sqlite3_backup_init(target, "main", source, "main");
    if (!copy) return "snapshot_backup_init";
    int step = SQLITE_OK, finish;
    const char *error = NULL;
    while (step != SQLITE_DONE) {
        if (!disk_has_space(directory, SPACE_RESERVE)) {
            error = "snapshot_disk_space";
            break;
        }
        const uint64_t batch = now_ms();
        if (batch >= *deadline) {
            error = "snapshot_deadline";
            break;
        }
        do {
            step = sqlite3_backup_step(copy, 100);
            const int pages = sqlite3_backup_pagecount(copy);
            if (pages < 0 || (uint64_t)pages * (unsigned)page_size > MAX_BYTES) {
                error = "snapshot_capacity";
                break;
            }
        } while (step == SQLITE_OK && now_ms() < batch + 10);
        if (error || step == SQLITE_DONE) break;
        if (step != SQLITE_OK && step != SQLITE_BUSY && step != SQLITE_LOCKED) {
            error = "snapshot_backup_step";
            break;
        }
        if (!pause_batches()) {
            error = "snapshot_clock";
            break;
        }
    }
    finish = sqlite3_backup_finish(copy);
    if (error) return error;
    if (step != SQLITE_DONE || finish != SQLITE_OK) return "snapshot_backup_finish";
    return expired(deadline) ? "snapshot_deadline" : NULL;
}

static int snapshot(int argc, char **argv) {
    if (argc != 10) return 1;
    const bool controller = strcmp(argv[4], "controller") == 0, seamer = strcmp(argv[4], "seamer") == 0;
    char *end = NULL;
    errno = 0;
    long revision = strtol(argv[9], &end, 10);
    if ((!controller && !seamer) || controller != (argv[8][0] != '\0') ||
        errno || !end || *end || revision < 1 || revision > INT32_MAX) return 1;
    const struct scope scope = {argv[4], argv[5], argv[6], argv[7], argv[8], (int)revision,
        controller ? 0x4c53434c : 0x4c53534d};
    sqlite3 *source = NULL, *target = NULL;
    int pages = 0, page_size = 0, target_pages = 0, target_close, source_close;
    const char *error = "snapshot_source";
    uint64_t deadline = now_ms();
    if (deadline == UINT64_MAX) goto done;
    deadline += DEADLINE_MS;
    if (!open_database(&source, argv[1], SQLITE_OPEN_READONLY, &deadline) || !matches(source, &scope) ||
        !mode_or_integrity(source, "PRAGMA journal_mode", "wal") ||
        !number(source, "PRAGMA page_size", &page_size) || page_size < 512 || page_size > 65536 ||
        !number(source, "PRAGMA page_count", &pages) || pages <= 0) goto done;
    const uint64_t declared = (uint64_t)pages * (unsigned)page_size;
    error = "snapshot_capacity";
    if (declared > MAX_BYTES) goto done;
    error = "snapshot_disk_space";
    if (!disk_has_space(argv[3], SPACE_RESERVE + declared)) goto done;
    error = "snapshot_destination";
    if (!open_database(&target, argv[2], SQLITE_OPEN_READWRITE, &deadline) ||
        sqlite3_exec(target, "PRAGMA synchronous=FULL; PRAGMA journal_mode=DELETE", NULL, NULL, NULL) != SQLITE_OK)
        goto done;
    error = copy_snapshot(source, target, argv[3], page_size, &deadline);
    if (error) goto done;
    error = "snapshot_validation";
    if (!mode_or_integrity(target, "PRAGMA journal_mode=DELETE", "delete") || !matches(target, &scope) ||
        !mode_or_integrity(target, "PRAGMA integrity_check(1)", "ok") || !foreign_keys_valid(target) ||
        !number(target, "PRAGMA page_count", &target_pages) || target_pages <= 0 ||
        !number(target, "PRAGMA page_size", &page_size) || page_size < 512 || page_size > 65536 ||
        (uint64_t)target_pages * (unsigned)page_size > MAX_BYTES || expired(&deadline)) goto done;
    error = NULL;
done:
    target_close = sqlite3_close(target);
    source_close = sqlite3_close(source);
    if (target_close != SQLITE_OK || source_close != SQLITE_OK) error = "snapshot_close";
    if (error) {
        fprintf(stderr, "%s\n", error);
        return 1;
    }
    printf("{\"page_count\":%d,\"page_size\":%d}\n", target_pages, page_size);
    return fflush(stdout) == 0 ? 0 : 1;
}

#ifdef _WIN32
int wmain(int argc, wchar_t **native_args) {
    if (argc != 10) return 1;
    char *args[10] = {0};
    int result = 1;
    for (int i = 0; i < argc; i++) {
        const int bytes = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, native_args[i], -1, NULL, 0, NULL, NULL);
        if (bytes <= 0 || !(args[i] = malloc((size_t)bytes)) ||
            !WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, native_args[i], -1, args[i], bytes, NULL, NULL))
            goto done;
    }
    result = snapshot(argc, args);
done:
    for (int i = 0; i < argc; i++) free(args[i]);
    return result;
}
#else
int main(int argc, char **argv) {
    return snapshot(argc, argv);
}
#endif
