// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/random.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#include "secureram_config.h"
#include "uapi/secureram.h"

#define ARRAY_SIZE(array) (sizeof(array) / sizeof((array)[0]))

enum { EXIT_OPERATION = 1, EXIT_USAGE = 2, EXIT_ABI = 3 };

static const char *state_name(unsigned int state)
{
	switch (state) {
	case SECURERAM_NO_KEY: return "NO_KEY";
	case SECURERAM_PREPARING: return "PREPARING";
	case SECURERAM_ACTIVE: return "ACTIVE";
	case SECURERAM_LOCKED: return "LOCKED";
	case SECURERAM_INTEGRITY_FAILED: return "INTEGRITY_FAILED";
	default: return "UNKNOWN";
	}
}

static int operation_error(const char *operation)
{
	int error = errno;
	const char *hint = "";

	switch (error) {
	case ENOENT:
		hint = "; load the SecureRAM module first";
		break;
	case EPERM:
	case EACCES:
		hint = "; requires host CAP_SYS_ADMIN and root device access";
		break;
	case EBUSY:
		hint = "; close/unmount block users; check status and the state rules in 'help'";
		break;
	case ENOKEY:
		hint = "; no usable key in the current state";
		break;
	case EIO:
		hint = "; inspect status for INTEGRITY_FAILED";
		break;
	case ENOTTY:
		hint = "; ioctl unsupported by the loaded driver";
		break;
	}
	fprintf(stderr, "secureramctl: %s: %s%s\n", operation, strerror(error), hint);
	return error == ENOTTY ? EXIT_ABI : EXIT_OPERATION;
}

static int valid_header(const struct secureram_ioc_header *header, unsigned int size)
{
	if (header->version == SECURERAM_ABI_VERSION && header->size == size &&
	    !header->flags && !header->reserved)
		return 0;
	fputs("secureramctl: incompatible ABI version, size or reserved fields\n", stderr);
	return EXIT_ABI;
}

static int query(int fd, struct secureram_ioc_status *status)
{
	if (ioctl(fd, SECURERAM_IOC_QUERY, status))
		return operation_error("QUERY");
	if (valid_header(&status->header, sizeof(*status)))
		return EXIT_ABI;
	if (status->reserved || status->unit_size != SECURERAM_UNIT_BYTES) {
		fputs("secureramctl: incompatible QUERY geometry/reserved field\n", stderr);
		return EXIT_ABI;
	}
	return 0;
}

static int open_control(void)
{
	unsigned int major_number, minor_number;
	struct stat info;
	FILE *identity;
	int fd, fields, saved;

	fd = open("/dev/secureramctl", O_RDWR | O_CLOEXEC | O_NOFOLLOW);
	if (fd < 0)
		return -1;
	identity = fopen("/sys/class/misc/secureramctl/dev", "r");
	if (!identity)
		goto fail;
	fields = fscanf(identity, "%u:%u", &major_number, &minor_number);
	if (fclose(identity))
		goto fail;
	if (fields != 2) {
		errno = ENODEV;
		goto fail;
	}
	if (fstat(fd, &info))
		goto fail;
	if (!S_ISCHR(info.st_mode) ||
	    info.st_rdev != makedev(major_number, minor_number) ||
	    info.st_uid || info.st_gid || (info.st_mode & 0777) != 0600) {
		errno = ENODEV;
		goto fail;
	}
	return fd;
fail:
	saved = errno;
	close(fd);
	errno = saved;
	return -1;
}

/* Only a restricted, JSON-safe version alphabet; unavailable is never guessed. */
static bool module_version(char *version, size_t size)
{
	FILE *file = fopen("/sys/module/secureram/version", "r");
	size_t used = 0;
	int ch;
	bool valid = true;

	if (!file)
		return false;
	while ((ch = fgetc(file)) != EOF && ch != '\n') {
		if (used + 1 >= size ||
		    !(isalnum((unsigned char)ch) || ch == '.' ||
		      ch == '-' || ch == '_' || ch == '+')) {
			valid = false;
			break;
		}
		version[used++] = (char)ch;
	}
	if (ferror(file))
		valid = false;
	if (fclose(file))
		valid = false;
	version[used] = '\0';
	return valid && used != 0;
}

static const char *json_bool(unsigned int features, unsigned int bit)
{
	return features & bit ? "true" : "false";
}

static void print_status(const struct secureram_ioc_status *status, bool json)
{
	char version[64];
	bool known = module_version(version, sizeof(version));
	unsigned int features = status->features;

	if (json) {
		printf("{\"version\":%s%s%s,\"cli_version\":\"%s\",\"abi\":%u,\n"
		       "\"state\":%u,\"state_name\":\"%s\",\"capacity_bytes\":%llu,\n"
		       "\"unit_bytes\":%u,\"generation\":%llu,\"features\":%u,\n"
		       "\"xts\":%s,\"lock\":%s,\"integrity\":%s,\"stats\":%s}\n",
		       known ? "\"" : "", known ? version : "null", known ? "\"" : "",
		       SECURERAM_VERSION, status->header.version, status->state,
		       state_name(status->state), (unsigned long long)status->capacity,
		       status->unit_size, (unsigned long long)status->generation, features,
		       json_bool(features, SECURERAM_FEATURE_XTS),
		       json_bool(features, SECURERAM_FEATURE_LOCK),
		       json_bool(features, SECURERAM_FEATURE_INTEGRITY),
		       json_bool(features, SECURERAM_FEATURE_STATS));
		return;
	}
	printf("SecureRAM %s (CLI %s)\nABI: %u\nState: %s (%u)\n"
	       "Capacity: %.2f MiB (%llu bytes)\nCrypto unit: %u bytes\n"
	       "Generation: %llu\nFeatures: %u%s%s%s%s\n"
	       "Confidentiality: %s\nIntegrity: %s\n",
	       known ? version : "version unavailable", SECURERAM_VERSION,
	       status->header.version, state_name(status->state), status->state,
	       (double)status->capacity / 1048576.0, (unsigned long long)status->capacity,
	       status->unit_size, (unsigned long long)status->generation, features,
	       features & SECURERAM_FEATURE_XTS ? " XTS" : "",
	       features & SECURERAM_FEATURE_LOCK ? " LOCK" : "",
	       features & SECURERAM_FEATURE_INTEGRITY ? " INTEGRITY" : "",
	       features & SECURERAM_FEATURE_STATS ? " STATS" : "",
	       features & SECURERAM_FEATURE_XTS ? "AES-256-XTS" : "not advertised",
	       features & SECURERAM_FEATURE_INTEGRITY ? "HMAC-SHA-256" : "not advertised");
}

static int print_stats(int fd, bool json)
{
	struct secureram_ioc_stats stats;
	size_t i;

	if (ioctl(fd, SECURERAM_IOC_GET_STATS, &stats))
		return operation_error("GET_STATS");
	if (valid_header(&stats.header, sizeof(stats)))
		return EXIT_ABI;
	for (i = 0; i < ARRAY_SIZE(stats.reserved); i++) {
		if (stats.reserved[i]) {
			fputs("secureramctl: incompatible GET_STATS reserved fields\n", stderr);
			return EXIT_ABI;
		}
	}
	if (json)
		printf("{\"abi\":%u,\"read_requests\":%llu,\"write_requests\":%llu,\n"
		       "\"read_bytes\":%llu,\"write_bytes\":%llu,\"integrity_failures\":%llu}\n",
		       stats.header.version, (unsigned long long)stats.read_requests,
		       (unsigned long long)stats.write_requests,
		       (unsigned long long)stats.read_bytes,
		       (unsigned long long)stats.write_bytes,
		       (unsigned long long)stats.integrity_failures);
	else
		printf("Successful read requests: %llu\nSuccessful write requests: %llu\n"
		       "Successful read bytes: %llu\nSuccessful write bytes: %llu\n"
		       "Integrity authentication failures: %llu\n",
		       (unsigned long long)stats.read_requests,
		       (unsigned long long)stats.write_requests,
		       (unsigned long long)stats.read_bytes, (unsigned long long)stats.write_bytes,
		       (unsigned long long)stats.integrity_failures);
	return 0;
}

static int load_random(int fd)
{
	struct secureram_ioc_key key = {
		.header = { .version = SECURERAM_ABI_VERSION, .size = sizeof(key) },
		.key_length = SECURERAM_KEY_BYTES,
	};
	bool locked = false;
	size_t done = 0;
	const char *operation = "protect ephemeral key buffer";
	int result = -1, saved;

	if (prctl(PR_SET_DUMPABLE, 0L, 0L, 0L, 0L) || mlock(&key, sizeof(key)))
		goto wipe;
	locked = true;
	operation = "getrandom";
	while (done < sizeof(key.key)) {
		ssize_t count = getrandom(key.key + done, sizeof(key.key) - done, 0);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			if (!count)
				errno = EIO;
			goto wipe;
		}
		done += (size_t)count;
	}
	operation = "LOAD_KEY";
	result = ioctl(fd, SECURERAM_IOC_LOAD_KEY, &key);
wipe:
	saved = errno;
	explicit_bzero(&key, sizeof(key));
	if (locked && munlock(&key, sizeof(key)) && !result) {
		/* The load already succeeded; do not imply that retrying is safe. */
		fputs("secureramctl: key loaded and wiped; munlock failed\n", stderr);
		return EXIT_OPERATION;
	}
	errno = saved;
	return result ? operation_error(operation) : 0;
}

static void print_help(void)
{
	puts("Usage: secureramctl status|stats [--json]\n"
	     "       secureramctl load-random|lock|unlock|destroy\n"
	     "       secureramctl help|version\n"
	     "Device commands require root/host CAP_SYS_ADMIN; invoke sudo externally.\n"
	     "load-random creates an unrecoverable ephemeral key; destroy discards all data.\n"
	     "Load needs NO_KEY; lock needs ACTIVE; unlock needs LOCKED.\n"
	     "INTEGRITY_FAILED requires destroy then a fresh load. All changes need zero block users.\n"
	     "Exit codes: 0 success, 1 operation/access failure, 2 usage, 3 ABI/feature mismatch.");
}

int main(int argc, char **argv)
{
	struct secureram_ioc_header header = {
		.version = SECURERAM_ABI_VERSION, .size = sizeof(header),
	};
	struct secureram_ioc_status status;
	unsigned long command = 0;
	bool json = false;
	int fd, result;
	const char *name;

	if (argc < 2 || argc > 3)
		goto bad_usage;
	name = argv[1];
	if (argc == 3) {
		if (strcmp(argv[2], "--json") ||
		    (strcmp(name, "status") && strcmp(name, "stats")))
			goto bad_usage;
		json = true;
	}
	if (!strcmp(name, "help")) {
		print_help();
		return fflush(stdout) ? EXIT_OPERATION : 0;
	}
	if (!strcmp(name, "version")) {
		printf("secureramctl %s (ABI %u)\n", SECURERAM_VERSION, SECURERAM_ABI_VERSION);
		return fflush(stdout) ? EXIT_OPERATION : 0;
	}
	if (!strcmp(name, "lock")) {
		command = SECURERAM_IOC_LOCK;
	} else if (!strcmp(name, "unlock")) {
		command = SECURERAM_IOC_UNLOCK;
	} else if (!strcmp(name, "destroy")) {
		command = SECURERAM_IOC_DESTROY_KEY;
		header.flags = SECURERAM_F_DESTROY;
	} else if (strcmp(name, "status") && strcmp(name, "stats") && strcmp(name, "load-random")) {
		goto bad_usage;
	}
	fd = open_control();
	if (fd < 0)
		return operation_error("open/verify /dev/secureramctl");
	result = query(fd, &status);
	if (result)
		goto out;
	if (!strcmp(name, "status")) {
		print_status(&status, json);
	} else if (!strcmp(name, "stats")) {
		if (!(status.features & SECURERAM_FEATURE_STATS)) {
			fputs("secureramctl: loaded driver does not advertise STATS\n", stderr);
			result = EXIT_ABI;
		} else {
			result = print_stats(fd, json);
		}
	} else {
		unsigned int needed = command == SECURERAM_IOC_LOCK ||
			command == SECURERAM_IOC_UNLOCK ?
			SECURERAM_FEATURE_LOCK : SECURERAM_FEATURE_XTS;

		if (!(status.features & needed)) {
			fputs("secureramctl: operation feature is not advertised\n", stderr);
			result = EXIT_ABI;
			goto out;
		}
		if (!command)
			result = load_random(fd);
		else if (ioctl(fd, command, &header))
			result = operation_error(name);
		if (!result) {
			result = query(fd, &status);
			if (result)
				fputs("secureramctl: operation completed; status unavailable\n",
				      stderr);
			else
				printf("%s succeeded: state=%s (%u) generation=%llu\n", name,
				       state_name(status.state), status.state,
				       (unsigned long long)status.generation);
		}
	}
out:
	if (close(fd) && !result)
		result = operation_error("close control device");
	if (fflush(stdout) && !result)
		result = operation_error("write output");
	return result;
bad_usage:
	fputs("secureramctl: invalid arguments; use 'secureramctl help'\n", stderr);
	return EXIT_USAGE;
}
