/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SECURERAM_STORE_H
#define SECURERAM_STORE_H

#include <linux/types.h>

/* Runtime access is serialized by the block component's ordered worker. */
struct secureram_store {
	u8 *data;
	size_t size;
};

int secureram_store_init(struct secureram_store *store, u64 size);
void secureram_store_destroy(struct secureram_store *store);
void secureram_store_clear(struct secureram_store *store);
bool secureram_store_contains(const struct secureram_store *store,
			      u64 offset, size_t length);
int secureram_store_read(const struct secureram_store *store, u64 offset,
			 void *buffer, size_t length);
int secureram_store_write(struct secureram_store *store, u64 offset,
			  const void *buffer, size_t length);

#endif /* SECURERAM_STORE_H */
