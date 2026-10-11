/* SPDX-License-Identifier: GPL-2.0-only WITH Linux-syscall-note */
#ifndef _UAPI_SECURERAM_TEST_H
#define _UAPI_SECURERAM_TEST_H

/* Opt-in VM test ABI. Production has no handler for this command. */
#ifdef SECURERAM_M5_TEST
#include "secureram.h"

#define SECURERAM_TEST_CIPHER 1U
#define SECURERAM_TEST_TAG 2U
#define SECURERAM_TEST_RELOCATE 3U

struct secureram_ioc_tamper {
	struct secureram_ioc_header header;
	__aligned_u64 unit;
	__aligned_u64 other_unit;
	__u32 operation;
	__u32 byte_offset;
};

#define SECURERAM_IOC_TAMPER _IOW(0xb7, 0x70, struct secureram_ioc_tamper)
#endif

#endif /* _UAPI_SECURERAM_TEST_H */
