// SPDX-License-Identifier: GPL-2.0-only
/* Compile-only: no libc, device access or executable needed; use -m64/-m32. */
#include "uapi/secureram.h"
#include "uapi/secureram_test.h"

_Static_assert(sizeof(struct secureram_ioc_header) == 16, "header size");
_Static_assert(sizeof(struct secureram_ioc_key) == 88, "key size");
_Static_assert(sizeof(struct secureram_ioc_status) == 48, "status size");
_Static_assert(__builtin_offsetof(struct secureram_ioc_key, key) == 24, "key offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_status, capacity) == 16, "capacity offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_status, generation) == 24,
	       "generation offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_status, state) == 32, "state offset");
_Static_assert(SECURERAM_IOC_QUERY == 0x8030b700U, "query number");
_Static_assert(SECURERAM_IOC_LOAD_KEY == 0x4058b701U, "load number");
_Static_assert(SECURERAM_IOC_LOCK == 0x4010b702U, "lock number");
_Static_assert(SECURERAM_IOC_UNLOCK == 0x4010b703U, "unlock number");
_Static_assert(SECURERAM_IOC_DESTROY_KEY == 0x4010b704U, "destroy number");
_Static_assert(SECURERAM_INTEGRITY_FAILED == 4, "failure state");
_Static_assert(SECURERAM_NO_KEY == 0 && SECURERAM_PREPARING == 1 &&
	       SECURERAM_ACTIVE == 2 && SECURERAM_LOCKED == 3 && SECURERAM_DYING == 5,
	       "existing states");
_Static_assert(sizeof(struct secureram_ioc_stats) == 80, "stats size");
_Static_assert(__builtin_offsetof(struct secureram_ioc_stats, read_requests) == 16,
	       "read requests offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_stats, write_requests) == 24,
	       "write requests offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_stats, read_bytes) == 32,
	       "read bytes offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_stats, write_bytes) == 40,
	       "write bytes offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_stats, integrity_failures) == 48,
	       "failures offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_stats, reserved) == 56,
	       "reserved offset");
_Static_assert(SECURERAM_IOC_GET_STATS == 0x8050b705U, "stats number");
_Static_assert(SECURERAM_FEATURE_STATS == 8, "stats feature");
_Static_assert(sizeof(struct secureram_ioc_snapshot) == 96, "snapshot size");
_Static_assert(__builtin_offsetof(struct secureram_ioc_snapshot, data_bytes) == 24,
	       "snapshot data offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_snapshot, generation) == 40,
	       "snapshot generation offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_snapshot, reserved) == 80,
	       "snapshot reserved offset");
_Static_assert(SECURERAM_IOC_SNAPSHOT_CREATE == 0x4010b706U, "snapshot create number");
_Static_assert(SECURERAM_IOC_SNAPSHOT_RESTORE == 0x4010b707U, "snapshot restore number");
_Static_assert(SECURERAM_IOC_SNAPSHOT_DELETE == 0x4010b708U, "snapshot delete number");
_Static_assert(SECURERAM_IOC_SNAPSHOT_STATUS == 0x8060b709U, "snapshot status number");
_Static_assert(SECURERAM_FEATURE_SNAPSHOT == 16, "snapshot feature");

#ifdef SECURERAM_M5_TEST
_Static_assert(sizeof(struct secureram_ioc_tamper) == 40, "tamper size");
_Static_assert(__builtin_offsetof(struct secureram_ioc_tamper, unit) == 16, "unit offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_tamper, other_unit) == 24, "other offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_tamper, operation) == 32,
	       "operation offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_tamper, byte_offset) == 36, "byte offset");
_Static_assert(SECURERAM_IOC_TAMPER == 0x4028b770U, "tamper number");
#endif
