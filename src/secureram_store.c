// SPDX-License-Identifier: GPL-2.0-only
#include <linux/errno.h>
#include <linux/limits.h>
#include <linux/sched.h>
#include <linux/string.h>
#include <linux/vmalloc.h>

#include "secureram_store.h"
#include "uapi/secureram.h"
#ifdef SECURERAM_M5_TEST
#include "uapi/secureram_test.h"
#endif

int secureram_store_init(struct secureram_store *store, u64 size)
{
	if (!size || size > SIZE_MAX || size % SECURERAM_UNIT_BYTES)
		return -EINVAL;

	store->data = vzalloc((size_t)size);
	if (!store->data)
		return -ENOMEM;

	store->size = (size_t)size;
	/* Division first: tag bytes per unit are smaller than the unit itself. */
	store->tag_size = store->size / SECURERAM_UNIT_BYTES * SECURERAM_TAG_BYTES;
	store->tags = vzalloc(store->tag_size);
	if (!store->tags) {
		secureram_store_destroy(store);
		return -ENOMEM;
	}
	return 0;
}

void secureram_store_destroy(struct secureram_store *store)
{
	secureram_store_clear(store);
	vfree(store->tags);
	store->tags = NULL;
	store->tag_size = 0;
	vfree(store->data);
	store->data = NULL;
	store->size = 0;
}

void secureram_store_clear(struct secureram_store *store)
{
	if (store->data)
		memzero_explicit(store->data, store->size);
	if (store->tags)
		memzero_explicit(store->tags, store->tag_size);
}

bool secureram_store_contains(const struct secureram_store *store,
			      u64 offset, size_t length)
{
	/* Subtraction after the offset check avoids offset + length overflow. */
	return store->data && offset <= store->size &&
		length <= store->size - offset;
}

int secureram_store_copy(struct secureram_store *destination,
			 const struct secureram_store *source)
{
	size_t offset;

	if (!source->data || !source->tags || !destination->data ||
	    !destination->tags || !source->size ||
	    source->size % SECURERAM_UNIT_BYTES ||
	    source->tag_size != source->size / SECURERAM_UNIT_BYTES * SECURERAM_TAG_BYTES ||
	    destination->size != source->size || destination->tag_size != source->tag_size)
		return -EINVAL;

	/* No fallible operation after validation; no observer can see either half.
	 * Chunk/reschedule so large copies do not monopolize a nonpreemptible CPU.
	 */
	for (offset = 0; offset < source->size; offset += SECURERAM_UNIT_BYTES) {
		memcpy(destination->data + offset, source->data + offset, SECURERAM_UNIT_BYTES);
		memcpy(destination->tags + offset / SECURERAM_UNIT_BYTES * SECURERAM_TAG_BYTES,
		       source->tags + offset / SECURERAM_UNIT_BYTES * SECURERAM_TAG_BYTES,
		       SECURERAM_TAG_BYTES);
		cond_resched();
	}
	return 0;
}

static bool secureram_store_unit(const struct secureram_store *store, u64 offset)
{
	return store->tags && !(offset % SECURERAM_UNIT_BYTES) &&
		secureram_store_contains(store, offset, SECURERAM_UNIT_BYTES) &&
		offset / SECURERAM_UNIT_BYTES < store->tag_size / SECURERAM_TAG_BYTES;
}

int secureram_store_read_unit(const struct secureram_store *store, u64 offset,
			      void *cipher, u8 *tag)
{
	if (!secureram_store_unit(store, offset))
		return -ERANGE;

	memcpy(cipher, store->data + (size_t)offset, SECURERAM_UNIT_BYTES);
	memcpy(tag, store->tags + offset / SECURERAM_UNIT_BYTES * SECURERAM_TAG_BYTES,
	       SECURERAM_TAG_BYTES);
	return 0;
}

int secureram_store_commit_unit(struct secureram_store *store, u64 offset,
				const void *cipher, const u8 *tag)
{
	if (!secureram_store_unit(store, offset))
		return -ERANGE;

	/* Both ranges validated; no fallible operation between the two copies. */
	memcpy(store->data + (size_t)offset, cipher, SECURERAM_UNIT_BYTES);
	memcpy(store->tags + offset / SECURERAM_UNIT_BYTES * SECURERAM_TAG_BYTES,
	       tag, SECURERAM_TAG_BYTES);
	return 0;
}

#ifdef SECURERAM_M5_TEST
int secureram_store_tamper(struct secureram_store *store,
			   const struct secureram_ioc_tamper *input)
{
	u64 units = store->size / SECURERAM_UNIT_BYTES;

	if (!store->tags || input->unit >= units)
		return -ERANGE;
	switch (input->operation) {
	case SECURERAM_TEST_CIPHER:
		if (input->other_unit || input->byte_offset >= SECURERAM_UNIT_BYTES)
			return -EINVAL;
		store->data[input->unit * SECURERAM_UNIT_BYTES + input->byte_offset] ^= 1;
		break;
	case SECURERAM_TEST_TAG:
		if (input->other_unit || input->byte_offset >= SECURERAM_TAG_BYTES)
			return -EINVAL;
		store->tags[input->unit * SECURERAM_TAG_BYTES + input->byte_offset] ^= 1;
		break;
	case SECURERAM_TEST_RELOCATE:
		if (input->byte_offset || input->other_unit >= units ||
		    input->other_unit == input->unit)
			return -EINVAL;
		return secureram_store_commit_unit(store,
			input->other_unit * SECURERAM_UNIT_BYTES,
			store->data + input->unit * SECURERAM_UNIT_BYTES,
			store->tags + input->unit * SECURERAM_TAG_BYTES);
	default:
		return -EINVAL;
	}
	return 0;
}
#endif
