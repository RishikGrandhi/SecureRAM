/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SECURERAM_CONFIG_H
#define SECURERAM_CONFIG_H

#define SECURERAM_DRIVER_NAME		"secureram"
#define SECURERAM_DEVICE_NAME		"secureram0"
#define SECURERAM_VERSION		"0.1.0"

/* M2 defaults only: M1 allocates no backing storage and registers no disk. */
#define SECURERAM_DEFAULT_CAPACITY_BYTES	(64ULL * 1024 * 1024)

/* Block-layer sector accounting is independent of the logical block size. */
#define SECURERAM_SECTOR_SIZE		512U
#define SECURERAM_LOGICAL_BLOCK_SIZE	4096U

#endif /* SECURERAM_CONFIG_H */
