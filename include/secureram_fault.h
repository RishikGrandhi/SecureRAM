/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SECURERAM_FAULT_H
#define SECURERAM_FAULT_H

#include <linux/types.h>

enum secureram_fault_site {
	SECURERAM_FAULT_DATA = 1,
	SECURERAM_FAULT_TAGS,
	SECURERAM_FAULT_REQUEST,
	SECURERAM_FAULT_ENCRYPT,
	SECURERAM_FAULT_DECRYPT,
	SECURERAM_FAULT_MAC,
	SECURERAM_FAULT_CONTROL,
};

#ifdef SECURERAM_M9_TEST
bool secureram_fault(enum secureram_fault_site site);
#else
static inline bool secureram_fault(enum secureram_fault_site site)
{
	(void)site;
	return false;
}
#endif

#endif /* SECURERAM_FAULT_H */
