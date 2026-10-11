/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SECURERAM_BLOCK_H
#define SECURERAM_BLOCK_H

#include <linux/types.h>
#include "uapi/secureram.h"

struct secureram_device;

/* Set *device only on success; destroy requires a successfully created disk. */
int secureram_block_create(struct secureram_device **device, u64 capacity);
void secureram_block_destroy(struct secureram_device *device);
int secureram_block_query(struct secureram_device *device,
			  struct secureram_ioc_status *status);
void secureram_block_stats(struct secureram_device *device,
			   struct secureram_ioc_stats *stats);
int secureram_block_change(struct secureram_device *device, unsigned int command,
			   u8 *key);

#ifdef SECURERAM_M5_TEST
struct secureram_ioc_tamper;
int secureram_block_tamper(struct secureram_device *device,
			   const struct secureram_ioc_tamper *input);
#endif

#endif /* SECURERAM_BLOCK_H */
