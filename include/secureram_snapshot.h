/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SECURERAM_SNAPSHOT_H
#define SECURERAM_SNAPSHOT_H

#include "secureram_store.h"

/* All access under control_lock; mutations also require gate/drain exclusion. */
struct secureram_snapshot {
	struct secureram_store store;
	u64 generation;
	bool valid;
	/* Device lifetime: never reset by slot cleanup or key destruction. */
	u64 created;
	u64 restored;
	u64 deleted;
	u64 failures;
};

void secureram_snapshot_clear(struct secureram_snapshot *snapshot);
void secureram_snapshot_failure(struct secureram_snapshot *snapshot);
int secureram_snapshot_change(struct secureram_snapshot *snapshot,
			      struct secureram_store *live, u64 generation,
			      u32 state, unsigned int command);

#endif /* SECURERAM_SNAPSHOT_H */
