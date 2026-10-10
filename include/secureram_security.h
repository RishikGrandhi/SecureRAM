/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SECURERAM_SECURITY_H
#define SECURERAM_SECURITY_H

#include "secureram_store.h"

/*
 * M3 plaintext pass-through boundary, not encryption or a key-state machine.
 * Owns the store; the block component owns this context's lifetime.
 */
struct secureram_security {
	struct secureram_store store;
};

/* Init before disk publication; destroy only after all I/O/work has drained. */
int secureram_security_init(struct secureram_security *security, u64 capacity);
void secureram_security_destroy(struct secureram_security *security);
u64 secureram_security_capacity(const struct secureram_security *security);
bool secureram_security_contains(const struct secureram_security *security,
				 u64 offset, size_t length);

/*
 * Ordered-worker calls only. Synchronous checked byte copies, returning
 * zero or negative errno. Kernel buffers are borrowed only for the call.
 * M3 permits sub-block segments; future crypto requires assembled whole units.
 */
int secureram_security_read(const struct secureram_security *security, u64 offset,
			    void *buffer, size_t length);
int secureram_security_write(struct secureram_security *security, u64 offset,
			     const void *buffer, size_t length);

#endif /* SECURERAM_SECURITY_H */
