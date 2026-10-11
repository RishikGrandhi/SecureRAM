/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SECURERAM_STATS_H
#define SECURERAM_STATS_H

#include <linux/spinlock.h>
#include "uapi/secureram.h"

/* Device lifetime, independent of keys. Every counter access holds lock. */
struct secureram_stats {
	/* Protects all five counters and their coherent snapshot. */
	spinlock_t lock;
	struct secureram_ioc_stats counters;
};

void secureram_stats_init(struct secureram_stats *stats);
void secureram_stats_io(struct secureram_stats *stats, bool write, u64 bytes);
void secureram_stats_failure(struct secureram_stats *stats);
void secureram_stats_snapshot(struct secureram_stats *stats,
			      struct secureram_ioc_stats *output);

#endif /* SECURERAM_STATS_H */
