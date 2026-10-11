// SPDX-License-Identifier: GPL-2.0-only
/* VM verification helper only. No password/KDF or production key persistence. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/random.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/wait.h>
#include <unistd.h>

#include "uapi/secureram.h"

#define ARRAY_SIZE(array) (sizeof(array) / sizeof((array)[0]))

static_assert(sizeof(struct secureram_ioc_header) == 16, "header ABI");
static_assert(sizeof(struct secureram_ioc_key) == 88, "key ABI");
static_assert(sizeof(struct secureram_ioc_status) == 48, "status ABI");

static struct secureram_ioc_header header(unsigned int size, unsigned int flags)
{
	return (struct secureram_ioc_header) {
		.version = SECURERAM_ABI_VERSION, .size = size, .flags = flags,
	};
}

static int expect_error(int fd, unsigned long cmd, void *arg, int expected)
{
	if (ioctl(fd, cmd, arg) == -1 && errno == expected)
		return 0;
	fprintf(stderr, "FAIL: expected ioctl errno %d\n", expected);
	return -1;
}

static int negative_tests(int fd, struct secureram_ioc_key *key)
{
	struct secureram_ioc_status status;
	struct secureram_ioc_header control = header(sizeof(control), 0);
	unsigned int lengths[] = { 0, 32, 63, 65 };
	long page_size = sysconf(_SC_PAGESIZE);
	void *mapping;
	pid_t child;
	int result;
	size_t i;

	if (ioctl(fd, SECURERAM_IOC_QUERY, &status) ||
	    status.state != SECURERAM_NO_KEY) {
		fprintf(stderr, "negative tests require NO_KEY\n");
		return -1;
	}
	key->header = header(sizeof(*key), 0);
	for (i = 0; i < ARRAY_SIZE(lengths); i++) {
		key->key_length = lengths[i];
		if (expect_error(fd, SECURERAM_IOC_LOAD_KEY, key, EINVAL))
			return -1;
	}
	key->key_length = SECURERAM_KEY_BYTES;
	/* Equal zero halves must be rejected, even outside FIPS mode. */
	if (expect_error(fd, SECURERAM_IOC_LOAD_KEY, key, EINVAL))
		return -1;
	key->header.version++;
	if (expect_error(fd, SECURERAM_IOC_LOAD_KEY, key, EINVAL))
		return -1;
	key->header = header(sizeof(*key), 0);
	key->header.reserved = 1;
	if (expect_error(fd, SECURERAM_IOC_LOAD_KEY, key, EINVAL))
		return -1;
	key->header = header(sizeof(*key) - 1, 0);
	if (expect_error(fd, SECURERAM_IOC_LOAD_KEY, key, EINVAL))
		return -1;
	key->header = header(sizeof(*key), 2);
	if (expect_error(fd, SECURERAM_IOC_LOAD_KEY, key, EINVAL))
		return -1;
	key->header = header(sizeof(*key), 0);
	key->reserved = 1;
	if (expect_error(fd, SECURERAM_IOC_LOAD_KEY, key, EINVAL))
		return -1;
	if (expect_error(fd, SECURERAM_IOC_QUERY, (void *)1, EFAULT) ||
	    expect_error(fd, SECURERAM_IOC_LOAD_KEY, (void *)1, EFAULT) ||
	    expect_error(fd, _IO(0xb7, 0x7f), &control, ENOTTY) ||
	    expect_error(fd, SECURERAM_IOC_DESTROY_KEY, &control, EINVAL) ||
	    expect_error(fd, SECURERAM_IOC_LOCK, &control, EBUSY) ||
	    expect_error(fd, SECURERAM_IOC_UNLOCK, &control, EBUSY))
		return -1;
	if (page_size <= 0)
		return -1;
	mapping = mmap(NULL, (size_t)page_size * 2, PROT_READ | PROT_WRITE,
		       MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	if (mapping == MAP_FAILED)
		return -1;
	if (mprotect((char *)mapping + page_size, (size_t)page_size, PROT_NONE)) {
		munmap(mapping, (size_t)page_size * 2);
		return -1;
	}
	result = expect_error(fd, SECURERAM_IOC_LOAD_KEY,
			      (char *)mapping + page_size - 40, EFAULT);
	munmap(mapping, (size_t)page_size * 2);
	if (result)
		return result;
	/* The inherited root-opened fd must not confer administration authority. */
	child = fork();
	if (child < 0)
		return -1;
	if (!child) {
		if (setgroups(0, NULL) || setresgid(65534, 65534, 65534) ||
		    setresuid(65534, 65534, 65534))
			_exit(2);
		_exit(expect_error(fd, SECURERAM_IOC_QUERY, &status, EPERM) ? 1 : 0);
	}
	if (waitpid(child, &result, 0) != child || !WIFEXITED(result) ||
	    WEXITSTATUS(result))
		return -1;
	if (ioctl(fd, SECURERAM_IOC_QUERY, &status) ||
	    status.state != SECURERAM_NO_KEY)
		return -1;
	puts("PASS: malformed ABI, weak key, user-copy faults, passed-fd privilege");
	return 0;
}

int main(int argc, char **argv)
{
	struct secureram_ioc_key key = { 0 };
	struct secureram_ioc_status status;
	struct secureram_ioc_header control = header(sizeof(control), 0);
	struct stat info;
	FILE *identity;
	unsigned int device_major, device_minor;
	unsigned long command = 0;
	int fd, ret = -1;

	if (argc != 2) {
		fprintf(stderr, "Usage: %s query|load-test-key|lock|unlock|destroy|negative|busy\n",
			argv[0]);
		return 2;
	}
	if (strcmp(argv[1], "query") && strcmp(argv[1], "load-test-key") &&
	    strcmp(argv[1], "lock") && strcmp(argv[1], "unlock") &&
	    strcmp(argv[1], "destroy") && strcmp(argv[1], "negative") &&
	    strcmp(argv[1], "busy"))
		return 2;
	if (prctl(PR_SET_DUMPABLE, 0) || mlock(&key, sizeof(key))) {
		perror("protect test key buffer");
		return 1;
	}
	fd = open("/dev/secureramctl", O_RDWR | O_CLOEXEC | O_NOFOLLOW);
	if (fd < 0) {
		perror("open /dev/secureramctl");
		goto wipe;
	}
	identity = fopen("/sys/class/misc/secureramctl/dev", "r");
	if (!identity)
		goto close_fd;
	ret = fscanf(identity, "%u:%u", &device_major, &device_minor);
	fclose(identity);
	if (ret != 2 || fstat(fd, &info) || !S_ISCHR(info.st_mode) ||
	    info.st_rdev != makedev(device_major, device_minor)) {
		fprintf(stderr, "control identity mismatch\n");
		ret = -1;
		goto close_fd;
	}
	ret = -1;
	if (!strcmp(argv[1], "query")) {
		ret = ioctl(fd, SECURERAM_IOC_QUERY, &status);
		if (!ret)
			printf("ABI=%u state=%u bytes=%llu unit=%u generation=%llu features=%u\n",
			       status.header.version, status.state,
			       (unsigned long long)status.capacity, status.unit_size,
			       (unsigned long long)status.generation, status.features);
	} else if (!strcmp(argv[1], "negative")) {
		ret = negative_tests(fd, &key);
	} else if (!strcmp(argv[1], "busy")) {
		/* Caller must keep an ACTIVE block fd or mount open throughout. */
		key.header = header(sizeof(key), 0);
		key.key_length = SECURERAM_KEY_BYTES;
		ret = expect_error(fd, SECURERAM_IOC_LOAD_KEY, &key, EBUSY) ||
			expect_error(fd, SECURERAM_IOC_LOCK, &control, EBUSY) ||
			expect_error(fd, SECURERAM_IOC_UNLOCK, &control, EBUSY);
		control.flags = SECURERAM_F_DESTROY;
		ret = ret || expect_error(fd, SECURERAM_IOC_DESTROY_KEY,
					 &control, EBUSY);
		if (!ret)
			puts("PASS: all key transitions rejected while block device is open");
	} else if (!strcmp(argv[1], "load-test-key")) {
		size_t done = 0;

		key.header = header(sizeof(key), 0);
		key.key_length = SECURERAM_KEY_BYTES;
		while (done < sizeof(key.key)) {
			ssize_t count = getrandom(key.key + done, sizeof(key.key) - done, 0);

			if (count < 0 && errno == EINTR)
				continue;
			if (count <= 0)
				goto close_fd;
			done += (size_t)count;
		}
		ret = ioctl(fd, SECURERAM_IOC_LOAD_KEY, &key);
		explicit_bzero(&key, sizeof(key));
	} else {
		if (!strcmp(argv[1], "lock"))
			command = SECURERAM_IOC_LOCK;
		if (!strcmp(argv[1], "unlock"))
			command = SECURERAM_IOC_UNLOCK;
		if (!strcmp(argv[1], "destroy")) {
			command = SECURERAM_IOC_DESTROY_KEY;
			control.flags = SECURERAM_F_DESTROY;
		}
		ret = ioctl(fd, command, &control);
	}
	if (ret)
		perror("M4 control operation");
close_fd:
	close(fd);
wipe:
	explicit_bzero(&key, sizeof(key));
	munlock(&key, sizeof(key));
	return ret ? 1 : 0;
}
