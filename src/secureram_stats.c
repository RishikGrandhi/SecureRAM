// SPDX-License-Identifier: GPL-2.0-only
#include <linux/limits.h>
#include <linux/string.h>

#include "secureram_stats.h"

static u64 secureram_stats_add(u64 value, u64 increment)
{
	return increment > U64_MAX - value ? U64_MAX : value + increment;
}

void secureram_stats_init(struct secureram_stats *stats)
{
	spin_lock_init(&stats->lock);
	memset(&stats->counters, 0, sizeof(stats->counters));
	stats->counters.header.version = SECURERAM_ABI_VERSION;
	stats->counters.header.size = sizeof(stats->counters);
}

void secureram_stats_io(struct secureram_stats *stats, bool write, u64 bytes)
{
	struct secureram_ioc_stats *counters = &stats->counters;
	unsigned long flags;

	spin_lock_irqsave(&stats->lock, flags);
	if (write) {
		counters->write_requests = secureram_stats_add(counters->write_requests, 1);
		counters->write_bytes = secureram_stats_add(counters->write_bytes, bytes);
	} else {
		counters->read_requests = secureram_stats_add(counters->read_requests, 1);
		counters->read_bytes = secureram_stats_add(counters->read_bytes, bytes);
	}
	spin_unlock_irqrestore(&stats->lock, flags);
}

void secureram_stats_failure(struct secureram_stats *stats)
{
	unsigned long flags;

	spin_lock_irqsave(&stats->lock, flags);
	stats->counters.integrity_failures =
		secureram_stats_add(stats->counters.integrity_failures, 1);
	spin_unlock_irqrestore(&stats->lock, flags);
}

void secureram_stats_snapshot(struct secureram_stats *stats,
			      struct secureram_ioc_stats *output)
{
	unsigned long flags;

	spin_lock_irqsave(&stats->lock, flags);
	*output = stats->counters;
	spin_unlock_irqrestore(&stats->lock, flags);
}
