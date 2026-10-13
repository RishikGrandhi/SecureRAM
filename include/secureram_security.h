/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SECURERAM_SECURITY_H
#define SECURERAM_SECURITY_H

#include "secureram_store.h"
#include "secureram_stats.h"
#include "secureram_snapshot.h"

#include "uapi/secureram.h"

struct crypto_skcipher;
struct skcipher_request;
struct crypto_shash;
struct shash_desc;

/* One worker, or a control caller after admission closes and work drains. */
struct secureram_security {
	/* Borrowed from the enclosing device; survives every key transition. */
	struct secureram_stats *stats;
	struct secureram_store store;
	struct secureram_snapshot snapshot;
	struct crypto_skcipher *tfm;
	struct skcipher_request *request;
	struct crypto_shash *mac;
	struct shash_desc *mac_desc;
	u8 tag[SECURERAM_TAG_BYTES];
	u8 stored_tag[SECURERAM_TAG_BYTES];
	u8 *plain;
	u8 *cipher;
	u8 iv[16] __aligned(16);
	u64 generation;
	/* Worker can latch failure concurrently with query/open: use *_ONCE. */
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

#ifdef SECURERAM_M5_TEST
int secureram_security_tamper(struct secureram_security *security,
			      const struct secureram_ioc_tamper *input);
#endif

#endif /* SECURERAM_SECURITY_H */
