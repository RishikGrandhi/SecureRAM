/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SECURERAM_BLOCK_H
#define SECURERAM_BLOCK_H

#include <linux/types.h>

struct secureram_device;

/* Set *device only on success; destroy requires a successfully created disk. */
int secureram_block_create(struct secureram_device **device, u64 capacity);
void secureram_block_destroy(struct secureram_device *device);

#endif /* SECURERAM_BLOCK_H */
