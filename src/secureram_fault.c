// SPDX-License-Identifier: GPL-2.0-only
/* Linked ONLY with M9_TEST=1. Fixed call-boundary failures, never memory access. */
#include <linux/atomic.h>
#include <linux/capability.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/moduleparam.h>
#include <linux/user_namespace.h>

#include "secureram_fault.h"

static atomic_t secureram_fault_pending = ATOMIC_INIT(0);

static int secureram_fault_set(const char *value, const struct kernel_param *parameter)
{
	unsigned int site;
	int ret;

	if (!ns_capable(&init_user_ns, CAP_SYS_ADMIN))
		return -EPERM;
	ret = kstrtouint(value, 0, &site);
	if (ret)
		return ret;
	if (site > SECURERAM_FAULT_CONTROL)
		return -EINVAL;
	atomic_set(&secureram_fault_pending, (int)site);
	return 0;
}

static int secureram_fault_get(char *buffer, const struct kernel_param *parameter)
{
	return scnprintf(buffer, PAGE_SIZE, "%d\n", atomic_read(&secureram_fault_pending));
}

static const struct kernel_param_ops secureram_fault_ops = {
	.set = secureram_fault_set,
	.get = secureram_fault_get,
};

module_param_cb(m9_fault, &secureram_fault_ops, NULL, 0600);
MODULE_PARM_DESC(m9_fault, "TEST ONLY one-shot fault: 0=off 1=data 2=tags 3=request 4=encrypt 5=decrypt 6=MAC 7=control");

bool secureram_fault(enum secureram_fault_site site)
{
	return atomic_cmpxchg(&secureram_fault_pending, (int)site, 0) == (int)site;
}
