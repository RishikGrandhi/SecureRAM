/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SECURERAM_CONFIG_H
#define SECURERAM_CONFIG_H

#define SECURERAM_DRIVER_NAME		"secureram"
#define SECURERAM_DEVICE_NAME		"secureram0"
#define SECURERAM_VERSION		"0.6.0"

/* capacity_mb is measured in MiB and is immutable after module insertion. */
#define SECURERAM_DEFAULT_CAPACITY_MB	64U
#define SECURERAM_MAX_CAPACITY_MB		256U

/* Block-layer sector accounting is independent of the logical block size. */
#define SECURERAM_SECTOR_SIZE		512U
#define SECURERAM_LOGICAL_BLOCK_SIZE	4096U

#define SECURERAM_QUEUE_DEPTH		64U
#define SECURERAM_MAX_HW_SECTORS		256U
#define SECURERAM_MAX_SEGMENTS		128U

#endif /* SECURERAM_CONFIG_H */
