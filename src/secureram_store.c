// SPDX-License-Identifier: GPL-2.0-only
#include <linux/errno.h>
#include <linux/limits.h>
#include <linux/string.h>
#include <linux/vmalloc.h>

#include "secureram_store.h"

int secureram_store_init(struct secureram_store *store, u64 size)
{
	if (!size || size > SIZE_MAX)
		return -EINVAL;

	store->data = vzalloc((size_t)size);
	if (!store->data)
		return -ENOMEM;

	store->size = (size_t)size;
	return 0;
}

void secureram_store_destroy(struct secureram_store *store)
{
	vfree(store->data);
	store->data = NULL;
	store->size = 0;
}

bool secureram_store_contains(const struct secureram_store *store,
			      u64 offset, size_t length)
{
	/* Subtraction after the offset check avoids offset + length overflow. */
	return store->data && offset <= store->size &&
		length <= store->size - offset;
}

int secureram_store_read(const struct secureram_store *store, u64 offset,
			 void *buffer, size_t length)
{
	if (!secureram_store_contains(store, offset, length))
		return -ERANGE;

	memcpy(buffer, store->data + (size_t)offset, length);
	return 0;
}

int secureram_store_write(struct secureram_store *store, u64 offset,
			  const void *buffer, size_t length)
{
	if (!secureram_store_contains(store, offset, length))
		return -ERANGE;

	memcpy(store->data + (size_t)offset, buffer, length);
	return 0;
}
