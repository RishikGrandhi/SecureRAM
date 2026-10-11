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

#ifdef SECURERAM_M5_TEST
_Static_assert(sizeof(struct secureram_ioc_tamper) == 40, "tamper size");
_Static_assert(__builtin_offsetof(struct secureram_ioc_tamper, unit) == 16, "unit offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_tamper, other_unit) == 24, "other offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_tamper, operation) == 32,
	       "operation offset");
_Static_assert(__builtin_offsetof(struct secureram_ioc_tamper, byte_offset) == 36, "byte offset");
_Static_assert(SECURERAM_IOC_TAMPER == 0x4028b770U, "tamper number");
#endif
