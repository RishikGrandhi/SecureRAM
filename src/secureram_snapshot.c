// SPDX-License-Identifier: GPL-2.0-only
#include <linux/errno.h>
#include <linux/limits.h>

#include "secureram_snapshot.h"
#include "uapi/secureram.h"

static void secureram_snapshot_increment(u64 *counter)
{
	if (*counter != U64_MAX)
		(*counter)++;
}

void secureram_snapshot_failure(struct secureram_snapshot *snapshot)
{
	secureram_snapshot_increment(&snapshot->failures);
}

void secureram_snapshot_clear(struct secureram_snapshot *snapshot)
{
	snapshot->valid = false;
	snapshot->generation = 0;
	secureram_store_destroy(&snapshot->store);
}

int secureram_snapshot_change(struct secureram_snapshot *snapshot,
			      struct secureram_store *live, u64 generation,
			      u32 state, unsigned int command)
{
	struct secureram_store candidate = {};
	int ret;

	if (command == SECURERAM_IOC_SNAPSHOT_DELETE) {
		if (snapshot->valid)
			secureram_snapshot_increment(&snapshot->deleted);
		secureram_snapshot_clear(snapshot);
		return 0;
	}
	if (state != SECURERAM_ACTIVE)
		return -EBUSY;
	if (!generation)
		return -ESTALE;
	if (command == SECURERAM_IOC_SNAPSHOT_CREATE) {
		if (snapshot->valid)
			return -EEXIST;
		ret = secureram_store_init(&candidate, live->size);
		if (!ret)
			ret = secureram_store_copy(&candidate, live);
		if (ret) {
			secureram_store_destroy(&candidate);
			return ret;
		}
		snapshot->store = candidate;
		snapshot->generation = generation;
		/* Publish only after both protected arrays and identity are complete. */
		snapshot->valid = true;
		secureram_snapshot_increment(&snapshot->created);
		return 0;
	}
	if (command != SECURERAM_IOC_SNAPSHOT_RESTORE)
		return -ENOTTY;
	if (!snapshot->valid)
		return -ENODATA;
	if (snapshot->generation != generation)
		return -ESTALE;
	ret = secureram_store_copy(live, &snapshot->store);
	if (!ret)
		secureram_snapshot_increment(&snapshot->restored);
	return ret;
}
