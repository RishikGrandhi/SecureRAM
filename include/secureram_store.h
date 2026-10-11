/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SECURERAM_STORE_H
#define SECURERAM_STORE_H

#include <linux/types.h>

#define SECURERAM_TAG_BYTES 32U

/* Runtime access is serialized by the block component's ordered worker. */
struct secureram_store {
	u8 *data;
	size_t size;
	u8 *tags;
	size_t tag_size;
};

int secureram_store_init(struct secureram_store *store, u64 size);
void secureram_store_destroy(struct secureram_store *store);
void secureram_store_clear(struct secureram_store *store);
bool secureram_store_contains(const struct secureram_store *store,
			      u64 offset, size_t length);
/* Complete ciphertext/tag pairs only; caller excludes all other access. */
int secureram_store_read_unit(const struct secureram_store *store, u64 offset,
			      void *cipher, u8 *tag);
int secureram_store_commit_unit(struct secureram_store *store, u64 offset,
				const void *cipher, const u8 *tag);

#ifdef SECURERAM_M5_TEST
struct secureram_ioc_tamper;
int secureram_store_tamper(struct secureram_store *store,
			   const struct secureram_ioc_tamper *input);
#endif

#endif /* SECURERAM_STORE_H */
