// SPDX-License-Identifier: GPL-2.0-only
#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/init.h>
#include <linux/module.h>
#include <linux/printk.h>

#include "secureram_config.h"

static int __init secureram_init(void)
{
	pr_info("SecureRAM v%s: M1 module loaded (no storage device yet)\n",
		SECURERAM_VERSION);

	return 0;
}

static void __exit secureram_exit(void)
{
	/* M1 owns no resources; later milestones will unwind them here. */
	pr_info("SecureRAM: M1 module unloaded\n");
}

module_init(secureram_init);
module_exit(secureram_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("SecureRAM project contributors");
MODULE_DESCRIPTION("SecureRAM RAM-backed block storage project: M1 skeleton");
MODULE_VERSION(SECURERAM_VERSION);
