// SPDX-License-Identifier: GPL-2.0-only
#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/init.h>
#include <linux/module.h>
#include <linux/printk.h>
#include <linux/sizes.h>

#include "secureram_block.h"
#include "secureram_config.h"

static unsigned int capacity_mb = SECURERAM_DEFAULT_CAPACITY_MB;
module_param(capacity_mb, uint, 0444);
MODULE_PARM_DESC(capacity_mb, "RAM capacity in MiB (1-256, default 64)");

static struct secureram_device *secureram;

static int __init secureram_init(void)
{
	u64 capacity;
	int ret;

	if (!capacity_mb || capacity_mb > SECURERAM_MAX_CAPACITY_MB) {
		pr_err("capacity_mb must be between 1 and %u MiB\n",
		       SECURERAM_MAX_CAPACITY_MB);
		return -EINVAL;
	}
	capacity = (u64)capacity_mb * SZ_1M;
	ret = secureram_block_create(&secureram, capacity);
	if (ret) {
		pr_err("SecureRAM initialization failed: %d\n", ret);
		return ret;
	}

	pr_info("SecureRAM v%s: /dev/%s ready, %u MiB, %u-byte logical blocks (AES-256-XTS; NO_KEY)\n",
		SECURERAM_VERSION, SECURERAM_DEVICE_NAME, capacity_mb,
		SECURERAM_LOGICAL_BLOCK_SIZE);
	pr_info("/dev/secureramctl: confidentiality only; no integrity/authentication\n");
#ifdef SECURERAM_M4_TEST
	pr_info("M4 test build: internal ciphertext checks enabled\n");
#endif

	return 0;
}

static void __exit secureram_exit(void)
{
	secureram_block_destroy(secureram);
	secureram = NULL;
	pr_info("SecureRAM: M4 unloaded; devices removed and owned sensitive memory cleared\n");
}

module_init(secureram_init);
module_exit(secureram_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("SecureRAM project contributors");
MODULE_DESCRIPTION("SecureRAM M4: AES-256-XTS RAM storage; no authentication");
MODULE_VERSION(SECURERAM_VERSION);
