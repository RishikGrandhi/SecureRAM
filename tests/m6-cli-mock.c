// SPDX-License-Identifier: GPL-2.0-only
/* Link-time syscall fixture. Never built into or loaded by the production CLI. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#include "uapi/secureram.h"

static unsigned int state;
static unsigned long long generation;
static int dumped, locked;
static size_t generated;
static unsigned int random_calls;
static unsigned int snapshot_exists;

static int scenario(const char *name)
{
	const char *value = getenv("M6_MOCK");

	return value && !strcmp(value, name);
}

static int fail(int error)
{
	errno = error;
	return -1;
}

int __wrap_open(const char *path, int flags, ...)
{
	assert(!strcmp(path, "/dev/secureramctl"));
	assert(flags == (O_RDWR | O_CLOEXEC | O_NOFOLLOW));
	if (scenario("missing"))
		return fail(ENOENT);
	if (scenario("permission"))
		return fail(EACCES);
	state = getenv("M6_STATE") ? (unsigned int)strtoul(getenv("M6_STATE"), NULL, 10) : 0;
	generation = state ? 1 : 0;
	snapshot_exists = scenario("m8-present") ? 1U : 0U;
	return 123;
}

int __wrap_close(int fd)
{
	assert(fd == 123);
	return 0;
}

int __wrap_fstat(int fd, struct stat *info)
{
	assert(fd == 123);
	memset(info, 0, sizeof(*info));
	info->st_mode = S_IFCHR | 0600;
	info->st_rdev = makedev(10, scenario("identity") ? 124U : 123U);
	return 0;
}

FILE *__wrap_fopen(const char *path, const char *mode)
{
	FILE *file;

	assert(!strcmp(mode, "r"));
	if (scenario("version-missing") && !strcmp(path, "/sys/module/secureram/version")) {
		errno = ENOENT;
		return NULL;
	}
	/* Fixture metadata only; random/key material never goes into this file. */
	file = tmpfile();
	assert(file);
	if (!strcmp(path, "/sys/class/misc/secureramctl/dev"))
		fputs("10:123\n", file);
	else {
		assert(!strcmp(path, "/sys/module/secureram/version"));
		fputs(scenario("version-invalid") ? "bad\"version\n" : "0.6.0\n", file);
	}
	rewind(file);
	return file;
}

int __wrap_prctl(int option, ...)
{
	va_list args;

	assert(option == PR_SET_DUMPABLE);
	va_start(args, option);
	assert(va_arg(args, long) == 0);
	va_end(args);
	if (scenario("dump-fail"))
		return fail(EPERM);
	dumped = 1;
	return 0;
}

int __wrap_mlock(const void *buffer, size_t length)
{
	assert(buffer && dumped && length == sizeof(struct secureram_ioc_key));
	if (scenario("mlock-fail"))
		return fail(ENOMEM);
	locked = 1;
	return 0;
}

int __wrap_munlock(const void *buffer, size_t length)
{
	const unsigned char *bytes = buffer;
	size_t index;

	assert(locked && length == sizeof(struct secureram_ioc_key));
	for (index = 0; index < length; index++)
		assert(bytes[index] == 0); /* All fields wiped, including short/error paths. */
	locked = 0;
	return scenario("munlock-fail") ? fail(EIO) : 0;
}

ssize_t __wrap_getrandom(void *buffer, size_t length, unsigned int flags)
{
	size_t count = length > 7 ? 7 : length;

	assert(locked && dumped && !flags && generated + length == 64);
	random_calls++;
	if (random_calls == 1)
		return fail(EINTR);
	if (scenario("random-fail") && generated)
		return fail(EIO);
	if (scenario("random-zero") && generated)
		return 0;
	/* Non-secret fixture bytes; do not emit or persist their values. */
	memset(buffer, (int)random_calls, count);
	generated += count;
	return (ssize_t)count;
}

int __wrap_ioctl(int fd, unsigned long command, ...)
{
	va_list args;
	void *payload;
	struct secureram_ioc_header *header;

	assert(fd == 123);
	va_start(args, command);
	payload = va_arg(args, void *);
	va_end(args);
	if (scenario("unsupported"))
		return fail(ENOTTY);
	if (command == SECURERAM_IOC_QUERY) {
		struct secureram_ioc_status *status = payload;

		memset(status, 0, sizeof(*status));
		status->header.version = scenario("abi") ? 2U : 1U;
		status->header.size = sizeof(*status);
		status->capacity = 67108864;
		status->generation = generation;
		status->state = state;
		status->unit_size = 4096;
		status->features = scenario("old-driver") ? 7U : 15U;
		if (getenv("M6_MOCK") && !strncmp(getenv("M6_MOCK"), "m8-", 3))
			status->features = 31;
		status->reserved = scenario("query-reserved") ? 1U : 0U;
		return 0;
	}
	if (command == SECURERAM_IOC_SNAPSHOT_STATUS) {
		struct secureram_ioc_snapshot *snapshot = payload;

		if (scenario("m8-followup"))
			return fail(EIO);
		memset(snapshot, 0, sizeof(*snapshot));
		snapshot->header.version = 1;
		snapshot->header.size = scenario("m8-size") ? 95U : (unsigned int)sizeof(*snapshot);
		snapshot->exists = snapshot_exists;
		snapshot->state = state;
		snapshot->data_bytes = snapshot_exists ? 67108864U : 0U;
		snapshot->tag_bytes = snapshot_exists ? 524288U : 0U;
		snapshot->generation = snapshot_exists ? generation : 0;
		snapshot->created = UINT64_MAX;
		if (scenario("m8-reserved"))
			snapshot->reserved[1] = 1;
		if (scenario("m8-metadata"))
			snapshot->data_bytes = 7;
		return 0;
	}
	if (command == SECURERAM_IOC_GET_STATS) {
		struct secureram_ioc_stats *stats = payload;

		memset(stats, 0, sizeof(*stats));
		stats->header.version = 1;
		stats->header.size = scenario("stats-size") ? 79U : (unsigned int)sizeof(*stats);
		stats->read_requests = 3;
		stats->write_requests = 2;
		stats->read_bytes = UINT64_MAX;
		stats->write_bytes = 8192;
		stats->integrity_failures = state == 4 ? 1U : 0U;
		stats->reserved[2] = scenario("stats-reserved") ? 1U : 0U;
		return 0;
	}
	header = payload;
	assert(header->version == 1 && !header->reserved);
	if (command == SECURERAM_IOC_LOAD_KEY) {
		struct secureram_ioc_key *key = payload;

		assert(dumped && locked && generated == 64 && key->key_length == 64);
		assert(header->size == sizeof(*key) && !header->flags && !key->reserved);
		if (state || scenario("load-fail"))
			return fail(EBUSY);
		state = 2;
		generation++;
		return 0;
	}
	assert(header->size == 16);
	if (command == SECURERAM_IOC_SNAPSHOT_CREATE ||
	    command == SECURERAM_IOC_SNAPSHOT_RESTORE || command == SECURERAM_IOC_SNAPSHOT_DELETE) {
		assert(!header->flags);
		if (scenario("m8-busy"))
			return fail(EBUSY);
		if (command == SECURERAM_IOC_SNAPSHOT_DELETE) {
			snapshot_exists = 0;
			return 0;
		}
		if (state != 2)
			return fail(EBUSY);
		if (scenario("m8-stale"))
			return fail(ESTALE);
		if (command == SECURERAM_IOC_SNAPSHOT_CREATE) {
			if (snapshot_exists)
				return fail(EEXIST);
			if (scenario("m8-memory"))
				return fail(ENOMEM);
			snapshot_exists = 1;
			return 0;
		}
		return snapshot_exists ? 0 : fail(ENODATA);
	}
	if (scenario("busy"))
		return fail(EBUSY);
	if (command == SECURERAM_IOC_DESTROY_KEY) {
		assert(header->flags == 1);
		state = 0;
	} else if (command == SECURERAM_IOC_LOCK && state == 2) {
		assert(!header->flags);
		state = 3;
	} else if (command == SECURERAM_IOC_UNLOCK && state == 3) {
		assert(!header->flags);
		state = 2;
	} else {
		return fail(EBUSY);
	}
	return 0;
}
