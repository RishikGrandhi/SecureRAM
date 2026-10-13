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
#define SECURERAM_FEATURE_INTEGRITY 4U
#define SECURERAM_FEATURE_STATS 8U
#define SECURERAM_FEATURE_SNAPSHOT 16U

#define SECURERAM_NO_KEY 0U
#define SECURERAM_PREPARING 1U
#define SECURERAM_ACTIVE 2U
#define SECURERAM_LOCKED 3U
#define SECURERAM_INTEGRITY_FAILED 4U
/* Internal teardown state; never observable by a live control handle. */
#define SECURERAM_DYING 5U

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

/* GET_STATS is output-only, device-lifetime, saturating, and coherent.
 * READ/WRITE count only whole successful requests, just before completion.
 * integrity_failures counts actual authentication mismatches, not rejections.
 * All reserved fields are returned as zero. See docs/m6-report.md.
 */
struct secureram_ioc_stats {
	struct secureram_ioc_header header;
	__aligned_u64 read_requests;
	__aligned_u64 write_requests;
	__aligned_u64 read_bytes;
	__aligned_u64 write_bytes;
	__aligned_u64 integrity_failures;
	__aligned_u64 reserved[3];
};

/* Output-only. Sizes/generation are zero when absent. Counters are device-life,
 * saturating values, serialized with snapshot operations. Failures count valid
 * mutation requests reaching the block layer, not malformed/unauthorized ioctl.
 * deleted counts explicit deletion of a present slot, not lifecycle cleanup.
 */
struct secureram_ioc_snapshot {
	struct secureram_ioc_header header;
	__u32 exists;
	__u32 state;
	__aligned_u64 data_bytes;
	__aligned_u64 tag_bytes;
	__aligned_u64 generation;
	__aligned_u64 created;
	__aligned_u64 restored;
	__aligned_u64 deleted;
	__aligned_u64 failures;
	__aligned_u64 reserved[2];
};

/* Project-local ioctl namespace, not an upstream-assigned global number. */
#define SECURERAM_IOC_QUERY _IOR(0xb7, 0x00, struct secureram_ioc_status)
#define SECURERAM_IOC_LOAD_KEY _IOW(0xb7, 0x01, struct secureram_ioc_key)
#define SECURERAM_IOC_LOCK _IOW(0xb7, 0x02, struct secureram_ioc_header)
#define SECURERAM_IOC_UNLOCK _IOW(0xb7, 0x03, struct secureram_ioc_header)
#define SECURERAM_IOC_DESTROY_KEY _IOW(0xb7, 0x04, struct secureram_ioc_header)
#define SECURERAM_IOC_GET_STATS _IOR(0xb7, 0x05, struct secureram_ioc_stats)
#define SECURERAM_IOC_SNAPSHOT_CREATE _IOW(0xb7, 0x06, struct secureram_ioc_header)
#define SECURERAM_IOC_SNAPSHOT_RESTORE _IOW(0xb7, 0x07, struct secureram_ioc_header)
#define SECURERAM_IOC_SNAPSHOT_DELETE _IOW(0xb7, 0x08, struct secureram_ioc_header)
#define SECURERAM_IOC_SNAPSHOT_STATUS _IOR(0xb7, 0x09, struct secureram_ioc_snapshot)

#endif /* _UAPI_SECURERAM_H */
