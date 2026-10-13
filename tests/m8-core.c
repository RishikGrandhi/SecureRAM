// SPDX-License-Identifier: GPL-2.0-only
/* Execute the actual store/snapshot sources with allocation/scheduling shims.
 * This tests data/ownership/error paths, not kernel locking or crypto execution.
 */
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "secureram_snapshot.h"
#include "uapi/secureram.h"

static int allocation, fail_at, outstanding;

void *vzalloc(size_t size)
{
	size_t *memory;

	if (++allocation == fail_at)
		return NULL;
	memory = calloc(1, size + sizeof(size_t));
	assert(memory);
	*memory = size;
	outstanding++;
	return memory + 1;
}

void vfree(const void *pointer)
{
	const unsigned char *bytes = pointer;
	size_t *memory, index;

	if (!pointer)
		return;
	memory = (size_t *)pointer - 1;
	for (index = 0; index < *memory; index++)
		assert(bytes[index] == 0); /* Every owned byte cleared before free. */
	free(memory);
	outstanding--;
}

int main(void)
{
	struct secureram_snapshot snapshot = {0};
	struct secureram_store live = {0};
	unsigned int state, cycle;
	int index;

	assert(!secureram_store_init(&live, 1048576));
	memset(live.data, 0xa3, live.size);
	memset(live.tags, 0xb7, live.tag_size);
	for (state = 0; state <= 5; state++) {
		if (state == SECURERAM_ACTIVE)
			continue;
		assert(secureram_snapshot_change(&snapshot, &live, 1, state,
			SECURERAM_IOC_SNAPSHOT_CREATE) == -EBUSY);
		assert(secureram_snapshot_change(&snapshot, &live, 1, state,
			SECURERAM_IOC_SNAPSHOT_RESTORE) == -EBUSY);
	}
	assert(secureram_snapshot_change(&snapshot, &live, 1, SECURERAM_ACTIVE,
		SECURERAM_IOC_SNAPSHOT_RESTORE) == -ENODATA);
	for (index = 1; index <= 2; index++) {
		allocation = 0;
		fail_at = index;
		assert(secureram_snapshot_change(&snapshot, &live, 1, SECURERAM_ACTIVE,
			SECURERAM_IOC_SNAPSHOT_CREATE) == -ENOMEM);
		assert(!snapshot.valid && !snapshot.store.data && !snapshot.store.tags);
		assert(outstanding == 2 && live.data[0] == 0xa3 && live.tags[0] == 0xb7);
	}
	fail_at = 0;
	for (cycle = 0; cycle < 100; cycle++) {
		assert(!secureram_snapshot_change(&snapshot, &live, 1, SECURERAM_ACTIVE,
			SECURERAM_IOC_SNAPSHOT_CREATE));
		assert(outstanding == 4 && snapshot.valid && snapshot.generation == 1);
		assert(!memcmp(live.data, snapshot.store.data, live.size));
		assert(!memcmp(live.tags, snapshot.store.tags, live.tag_size));
		memset(live.data, 0x42, live.size);
		memset(live.tags, 0x53, live.tag_size);
		assert(secureram_snapshot_change(&snapshot, &live, 1, SECURERAM_ACTIVE,
			SECURERAM_IOC_SNAPSHOT_CREATE) == -EEXIST);
		assert(secureram_snapshot_change(&snapshot, &live, 2, SECURERAM_ACTIVE,
			SECURERAM_IOC_SNAPSHOT_RESTORE) == -ESTALE);
		assert(secureram_snapshot_change(&snapshot, &live, 0, SECURERAM_ACTIVE,
			SECURERAM_IOC_SNAPSHOT_RESTORE) == -ESTALE);
		snapshot.store.tag_size--;
		assert(secureram_snapshot_change(&snapshot, &live, 1, SECURERAM_ACTIVE,
			SECURERAM_IOC_SNAPSHOT_RESTORE) == -EINVAL);
		snapshot.store.tag_size++;
		assert(live.data[0] == 0x42 && live.tags[0] == 0x53);
		assert(!secureram_snapshot_change(&snapshot, &live, 1, SECURERAM_ACTIVE,
			SECURERAM_IOC_SNAPSHOT_RESTORE));
		assert(!memcmp(live.data, snapshot.store.data, live.size));
		assert(!memcmp(live.tags, snapshot.store.tags, live.tag_size));
		assert(live.data[0] == 0xa3 && live.tags[0] == 0xb7);
		assert(!secureram_snapshot_change(&snapshot, &live, 1, SECURERAM_ACTIVE,
			SECURERAM_IOC_SNAPSHOT_RESTORE));
		assert(!secureram_snapshot_change(&snapshot, &live, 1, SECURERAM_LOCKED,
			SECURERAM_IOC_SNAPSHOT_DELETE));
		assert(!snapshot.valid && !snapshot.generation && outstanding == 2);
		assert(!secureram_snapshot_change(&snapshot, &live, 1, SECURERAM_NO_KEY,
			SECURERAM_IOC_SNAPSHOT_DELETE));
	}
	assert(snapshot.created == 100 && snapshot.restored == 200 && snapshot.deleted == 100);
	snapshot.created = snapshot.restored = snapshot.deleted = snapshot.failures = UINT64_MAX;
	assert(!secureram_snapshot_change(&snapshot, &live, 1, SECURERAM_ACTIVE,
		SECURERAM_IOC_SNAPSHOT_CREATE));
	assert(!secureram_snapshot_change(&snapshot, &live, 1, SECURERAM_ACTIVE,
		SECURERAM_IOC_SNAPSHOT_RESTORE));
	assert(!secureram_snapshot_change(&snapshot, &live, 1, SECURERAM_INTEGRITY_FAILED,
		SECURERAM_IOC_SNAPSHOT_DELETE));
	secureram_snapshot_failure(&snapshot);
	secureram_snapshot_clear(&snapshot);
	assert(snapshot.created == UINT64_MAX && snapshot.restored == UINT64_MAX &&
	       snapshot.deleted == UINT64_MAX && snapshot.failures == UINT64_MAX);
	secureram_store_destroy(&live);
	assert(!outstanding);
	puts("PASS: real snapshot/store code, state/generation/geometry, paired copies, 100 cycles,");
	puts("allocation failures, publication, saturation, idempotence, wipe-before-free and no leaks");
	return 0;
}
