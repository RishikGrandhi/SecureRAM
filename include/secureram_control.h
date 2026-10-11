/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SECURERAM_CONTROL_H
#define SECURERAM_CONTROL_H

#include <linux/miscdevice.h>

struct secureram_device;

struct secureram_control {
	struct miscdevice misc;
	struct secureram_device *device;
};

int secureram_control_register(struct secureram_control *control,
			       struct secureram_device *device);
void secureram_control_unregister(struct secureram_control *control);

#endif /* SECURERAM_CONTROL_H */
