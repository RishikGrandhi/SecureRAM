// SPDX-License-Identifier: GPL-2.0-only
#include "secureram_security.h"

/* M3 deliberately preserves plaintext storage; there is no crypto fallback. */
int secureram_security_init(struct secureram_security *security, u64 capacity)
{
	return secureram_store_init(&security->store, capacity);
}

void secureram_security_destroy(struct secureram_security *security)
{
	/* Ordinary M2 release semantics; no secure-erasure guarantee. */
	secureram_store_destroy(&security->store);
}

u64 secureram_security_capacity(const struct secureram_security *security)
{
	return security->store.size;
}

bool secureram_security_contains(const struct secureram_security *security,
				 u64 offset, size_t length)
{
	return secureram_store_contains(&security->store, offset, length);
}

int secureram_security_read(const struct secureram_security *security, u64 offset,
			    void *buffer, size_t length)
{
	return secureram_store_read(&security->store, offset, buffer, length);
}

int secureram_security_write(struct secureram_security *security, u64 offset,
			     const void *buffer, size_t length)
{
	return secureram_store_write(&security->store, offset, buffer, length);
}
