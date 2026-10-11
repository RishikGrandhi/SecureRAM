// SPDX-License-Identifier: GPL-2.0-only
#include <linux/capability.h>
#include <linux/compat.h>
#include <linux/fs.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/user_namespace.h>

#include "secureram_block.h"
#include "secureram_control.h"
#ifdef SECURERAM_M5_TEST
#include "uapi/secureram_test.h"
#endif

static bool secureram_valid_header(const struct secureram_ioc_header *header,
				   u32 size, u32 flags)
{
	return header->version == SECURERAM_ABI_VERSION && header->size == size &&
		header->flags == flags && !header->reserved;
}

static long secureram_control_ioctl(struct file *file, unsigned int command,
				    unsigned long argument)
{
	struct secureram_control *control =
		container_of(file->private_data, struct secureram_control, misc);
	void __user *user = (void __user *)argument;
	struct secureram_ioc_status status = {};
	struct secureram_ioc_header header;
	struct secureram_ioc_key *input;
#ifdef SECURERAM_M5_TEST
	struct secureram_ioc_tamper tamper;
#endif
	u32 flags = 0;
	int ret;

	if (!ns_capable(&init_user_ns, CAP_SYS_ADMIN))
		return -EPERM;

	switch (command) {
#ifdef SECURERAM_M5_TEST
	case SECURERAM_IOC_TAMPER:
		if (copy_from_user(&tamper, user, sizeof(tamper)))
			return -EFAULT;
		if (!secureram_valid_header(&tamper.header, sizeof(tamper), 0))
			return -EINVAL;
		return secureram_block_tamper(control->device, &tamper);
#endif
	case SECURERAM_IOC_QUERY:
		ret = secureram_block_query(control->device, &status);
		if (ret)
			return ret;
		return copy_to_user(user, &status, sizeof(status)) ? -EFAULT : 0;
	case SECURERAM_IOC_LOAD_KEY:
		input = kzalloc_obj(*input);
		if (!input)
			return -ENOMEM;
		ret = -EFAULT;
		if (copy_from_user(input, user, sizeof(*input)))
			goto free_input;
		ret = -EINVAL;
		if (!secureram_valid_header(&input->header, sizeof(*input), 0) ||
		    input->key_length != SECURERAM_KEY_BYTES || input->reserved)
			goto free_input;
		ret = secureram_block_change(control->device, command, input->key);
free_input:
		/* Also erases a partially copied key on EFAULT. */
		kfree_sensitive(input);
		return ret;
	case SECURERAM_IOC_DESTROY_KEY:
		flags = SECURERAM_F_DESTROY;
		fallthrough;
	case SECURERAM_IOC_LOCK:
	case SECURERAM_IOC_UNLOCK:
		if (copy_from_user(&header, user, sizeof(header)))
			return -EFAULT;
		if (!secureram_valid_header(&header, sizeof(header), flags))
			return -EINVAL;
		return secureram_block_change(control->device, command, NULL);
	default:
		return -ENOTTY;
	}
}

static const struct file_operations secureram_control_fops = {
	.owner = THIS_MODULE,
	.open = nonseekable_open,
	.unlocked_ioctl = secureram_control_ioctl,
	.compat_ioctl = compat_ptr_ioctl,
};

int secureram_control_register(struct secureram_control *control,
			       struct secureram_device *device)
{
	control->device = device;
	control->misc.minor = MISC_DYNAMIC_MINOR;
	control->misc.name = "secureramctl";
	control->misc.fops = &secureram_control_fops;
	control->misc.mode = 0600;
	return misc_register(&control->misc);
}

void secureram_control_unregister(struct secureram_control *control)
{
	misc_deregister(&control->misc);
}
