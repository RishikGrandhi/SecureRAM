/* SPDX-License-Identifier: GPL-2.0-only WITH Linux-syscall-note */
#ifndef _UAPI_SECURERAM_H
#define _UAPI_SECURERAM_H

#include <linux/ioctl.h>
#include <linux/types.h>

#define SECURERAM_ABI_VERSION 1U
#define SECURERAM_KEY_BYTES 64U
#define SECURERAM_UNIT_BYTES 4096U
#define SECURERAM_F_DESTROY 1U
#define SECURERAM_FEATURE_XTS 1U
#define SECURERAM_FEATURE_LOCK 2U

#define SECURERAM_NO_KEY 0U
#define SECURERAM_PREPARING 1U
#define SECURERAM_ACTIVE 2U
#define SECURERAM_LOCKED 3U
#define SECURERAM_DYING 4U

struct secureram_ioc_header {
	__u32 version;
	__u32 size;
	__u32 flags;
	__u32 reserved;
};

struct secureram_ioc_key {
	struct secureram_ioc_header header;
	__u32 key_length;
	__u32 reserved;
	__u8 key[SECURERAM_KEY_BYTES];
};

/* QUERY is output-only. All padding/reserved fields are returned as zero. */
struct secureram_ioc_status {
	struct secureram_ioc_header header;
	__aligned_u64 capacity;
	__aligned_u64 generation;
	__u32 state;
	__u32 unit_size;
	__u32 features;
	__u32 reserved;
};

/* Project-local ioctl namespace, not an upstream-assigned global number. */
#define SECURERAM_IOC_QUERY _IOR(0xb7, 0x00, struct secureram_ioc_status)
#define SECURERAM_IOC_LOAD_KEY _IOW(0xb7, 0x01, struct secureram_ioc_key)
#define SECURERAM_IOC_LOCK _IOW(0xb7, 0x02, struct secureram_ioc_header)
#define SECURERAM_IOC_UNLOCK _IOW(0xb7, 0x03, struct secureram_ioc_header)
#define SECURERAM_IOC_DESTROY_KEY _IOW(0xb7, 0x04, struct secureram_ioc_header)

#endif /* _UAPI_SECURERAM_H */
