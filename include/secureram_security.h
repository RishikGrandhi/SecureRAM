/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SECURERAM_SECURITY_H
#define SECURERAM_SECURITY_H

#include "secureram_store.h"

#include "uapi/secureram.h"

struct crypto_skcipher;
struct skcipher_request;

/* One worker, or a control caller after admission closes and work drains. */
struct secureram_security {
	struct secureram_store store;
	struct crypto_skcipher *tfm;
	struct skcipher_request *request;
	u8 *plain;
	u8 *cipher;
	u8 iv[16] __aligned(16);
	u64 generation;
	u32 state;
};

/* Init before disk publication; destroy only after all I/O/work has drained. */
int secureram_security_init(struct secureram_security *security, u64 capacity);
void secureram_security_destroy(struct secureram_security *security);
u64 secureram_security_capacity(const struct secureram_security *security);
bool secureram_security_contains(const struct secureram_security *security,
				 u64 offset, size_t length);

/* Load consumes/clears the temporary key; the caller still sensitive-frees it. */
int secureram_security_load(struct secureram_security *security, u8 *key);
void secureram_security_clear(struct secureram_security *security);
void secureram_security_clear_unit(struct secureram_security *security);
/* Exactly one aligned unit: WRITE consumes plain, READ produces plain. */
int secureram_security_read(struct secureram_security *security, u64 offset);
int secureram_security_write(struct secureram_security *security, u64 offset);

#endif /* SECURERAM_SECURITY_H */
