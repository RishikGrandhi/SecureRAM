// SPDX-License-Identifier: GPL-2.0-only
#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <crypto/algapi.h>
#include <crypto/skcipher.h>
#include <linux/err.h>
#include <linux/mm.h>
#include <linux/scatterlist.h>
#include <linux/slab.h>
#include <linux/unaligned.h>

#include "secureram_security.h"

void secureram_security_clear_unit(struct secureram_security *security)
{
	if (security->plain)
		memzero_explicit(security->plain, SECURERAM_UNIT_BYTES);
	if (security->cipher)
		memzero_explicit(security->cipher, SECURERAM_UNIT_BYTES);
	memzero_explicit(security->iv, sizeof(security->iv));
}

void secureram_security_clear(struct secureram_security *security)
{
	/* Admission is closed and all requests/callbacks have completed. */
	skcipher_request_free(security->request);
	security->request = NULL;
	crypto_free_skcipher(security->tfm);
	security->tfm = NULL;
	secureram_security_clear_unit(security);
	secureram_store_clear(&security->store);
	security->state = SECURERAM_NO_KEY;
}

int secureram_security_init(struct secureram_security *security, u64 capacity)
{
	int ret;

	BUILD_BUG_ON(PAGE_SIZE < SECURERAM_UNIT_BYTES);
	if (capacity % SECURERAM_UNIT_BYTES)
		return -EINVAL;
	ret = secureram_store_init(&security->store, capacity);
	if (ret)
		return ret;
	security->plain = kzalloc(SECURERAM_UNIT_BYTES, GFP_KERNEL);
	security->cipher = kzalloc(SECURERAM_UNIT_BYTES, GFP_KERNEL);
	if (!security->plain || !security->cipher) {
		secureram_security_destroy(security);
		return -ENOMEM;
	}
	security->state = SECURERAM_NO_KEY;
	return 0;
}

void secureram_security_destroy(struct secureram_security *security)
{
	secureram_security_clear(security);
	security->state = SECURERAM_DYING;
	kfree_sensitive(security->cipher);
	kfree_sensitive(security->plain);
	security->cipher = NULL;
	security->plain = NULL;
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

static int secureram_crypt(struct secureram_security *security, u64 offset,
			   bool encrypt)
{
	DECLARE_CRYPTO_WAIT(wait);
	struct scatterlist source, destination;
	int ret;

	memset(security->iv, 0, sizeof(security->iv));
	put_unaligned_le64(offset / SECURERAM_UNIT_BYTES, security->iv);
	sg_init_one(&source, encrypt ? security->plain : security->cipher,
		    SECURERAM_UNIT_BYTES);
	sg_init_one(&destination, encrypt ? security->cipher : security->plain,
		    SECURERAM_UNIT_BYTES);
	skcipher_request_set_callback(security->request,
				      CRYPTO_TFM_REQ_MAY_SLEEP |
				      CRYPTO_TFM_REQ_MAY_BACKLOG,
				      crypto_req_done, &wait);
	skcipher_request_set_crypt(security->request, &source, &destination,
				   SECURERAM_UNIT_BYTES, security->iv);
	ret = encrypt ? crypto_skcipher_encrypt(security->request) :
		crypto_skcipher_decrypt(security->request);
	ret = crypto_wait_req(ret, &wait);
	/* No provider may retain these pointers after final completion. */
	skcipher_request_zero(security->request);
	skcipher_request_set_tfm(security->request, security->tfm);
	memzero_explicit(security->iv, sizeof(security->iv));
	return ret;
}

int secureram_security_load(struct secureram_security *security, u8 *key)
{
	struct crypto_skcipher *tfm;
	u64 offset;
	int ret = -EINVAL;

	if (security->state != SECURERAM_NO_KEY) {
		ret = -EBUSY;
		goto wipe_key;
	}
	if (security->generation == U64_MAX) {
		ret = -EOVERFLOW;
		goto wipe_key;
	}
	/* Enforce unequal halves even if a provider ignores the weak-key flag. */
	if (!crypto_memneq(key, key + SECURERAM_KEY_BYTES / 2,
			   SECURERAM_KEY_BYTES / 2))
		goto wipe_key;

	security->state = SECURERAM_PREPARING;
	tfm = crypto_alloc_skcipher("xts(aes)", 0,
				    CRYPTO_ALG_ALLOCATES_MEMORY |
				    CRYPTO_ALG_KERN_DRIVER_ONLY);
	if (IS_ERR(tfm)) {
		ret = PTR_ERR(tfm);
		goto fail;
	}
	security->tfm = tfm;
	/* Each aligned kmalloc unit fits within one page and one SG element. */
	if (crypto_skcipher_ivsize(tfm) != sizeof(security->iv) ||
	    crypto_skcipher_blocksize(tfm) != 16 ||
	    crypto_skcipher_alignmask(tfm) > 15) {
		ret = -EINVAL;
		goto fail;
	}
	crypto_skcipher_set_flags(tfm, CRYPTO_TFM_REQ_FORBID_WEAK_KEYS);
	ret = crypto_skcipher_setkey(tfm, key, SECURERAM_KEY_BYTES);
	memzero_explicit(key, SECURERAM_KEY_BYTES);
	if (ret)
		goto fail;
	security->request = skcipher_request_alloc(tfm, GFP_KERNEL);
	if (!security->request) {
		ret = -ENOMEM;
		goto fail;
	}

	/* No old plaintext/ciphertext is ever exposed under this new key. */
	secureram_security_clear_unit(security);
	for (offset = 0; offset < security->store.size;
	     offset += SECURERAM_UNIT_BYTES) {
		ret = secureram_crypt(security, offset, true);
		if (ret)
			goto fail;
		ret = secureram_store_write(&security->store, offset,
					    security->cipher, SECURERAM_UNIT_BYTES);
		if (ret)
			goto fail;
		cond_resched();
	}
#ifdef SECURERAM_M4_TEST
	/* Equal zero plaintext at different addresses must use distinct inputs. */
	if (!memcmp(security->store.data,
		    security->store.data + SECURERAM_UNIT_BYTES,
		    SECURERAM_UNIT_BYTES)) {
		ret = -EIO;
		goto fail;
	}
	pr_info("M4 test: equal zero units at indices 0/1 have different ciphertext\n");
#endif
	secureram_security_clear_unit(security);
	security->generation++;
	security->state = SECURERAM_ACTIVE;
	pr_info("XTS key prepared using provider %s\n",
		crypto_skcipher_driver_name(tfm));
	return 0;

fail:
	secureram_security_clear(security);
wipe_key:
	memzero_explicit(key, SECURERAM_KEY_BYTES);
	return ret;
}

static bool secureram_unit_ready(struct secureram_security *security, u64 offset)
{
	return security->state == SECURERAM_ACTIVE && security->tfm &&
		security->request && !(offset % SECURERAM_UNIT_BYTES) &&
		secureram_security_contains(security, offset, SECURERAM_UNIT_BYTES);
}

int secureram_security_read(struct secureram_security *security, u64 offset)
{
	int ret = -EIO;

	if (!secureram_unit_ready(security, offset))
		goto fail;
	ret = secureram_store_read(&security->store, offset, security->cipher,
				   SECURERAM_UNIT_BYTES);
	if (!ret)
		ret = secureram_crypt(security, offset, false);
	if (ret)
		goto fail;
	memzero_explicit(security->cipher, SECURERAM_UNIT_BYTES);
	/* The adapter clears plain after scattering the complete unit. */
	return 0;
fail:
	secureram_security_clear_unit(security);
	return ret;
}

int secureram_security_write(struct secureram_security *security, u64 offset)
{
	int ret = -EIO;

	if (!secureram_unit_ready(security, offset))
		goto out;
	ret = secureram_crypt(security, offset, true);
	if (ret)
		goto out;
	ret = secureram_store_write(&security->store, offset, security->cipher,
				    SECURERAM_UNIT_BYTES);
#ifdef SECURERAM_M4_TEST
	/* Inspect actual backing after real writes; never export bytes/hashes. */
	if (!ret) {
		const u8 *stored = security->store.data + (size_t)offset;

		if (!memcmp(stored, security->plain, SECURERAM_UNIT_BYTES) ||
		    memcmp(stored, security->cipher, SECURERAM_UNIT_BYTES)) {
			pr_err("M4 test: backing ciphertext comparison FAILED\n");
			ret = -EIO;
		}
	}
#endif
out:
	secureram_security_clear_unit(security);
	return ret;
}
