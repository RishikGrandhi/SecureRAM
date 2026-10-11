// SPDX-License-Identifier: GPL-2.0-only
#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/blk-mq.h>
#include <linux/blkdev.h>
#include <linux/err.h>
#include <linux/highmem.h>
#include <linux/list.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/workqueue.h>

#include "secureram_block.h"
#include "secureram_config.h"
#include "secureram_control.h"
#include "secureram_security.h"

struct secureram_device {
	struct secureram_security security;
	struct secureram_control control;
	/* Serializes administrators and block open/release; worker never takes it. */
	struct mutex control_lock;
	unsigned int openers;
	struct blk_mq_tag_set tag_set;
	struct gendisk *disk;
	struct workqueue_struct *workqueue;
	struct work_struct io_work;
	/* Protects pending and accepting against dispatch, drain and shutdown. */
	spinlock_t pending_lock;
	struct list_head pending;
	bool accepting;
};

/* Allocated by blk-mq with each request; never allocated during dispatch. */
struct secureram_request {
	struct list_head entry;
};

/* Fragment boundaries may split a unit, and a fragment may cross units. */
static int secureram_transfer_segment(struct secureram_security *security,
				      const struct bio_vec *bvec, bool write,
				      u64 *offset, size_t *used)
{
	size_t position = 0;
	int ret;

	while (position < bvec->bv_len) {
		size_t count = min_t(size_t, bvec->bv_len - position,
				     SECURERAM_UNIT_BYTES - *used);
		void *mapping;
		u8 *buffer;

		if (!write && !*used) {
			ret = secureram_security_read(security, *offset);
			if (ret)
				return ret;
		}
		if (write)
			flush_dcache_page(bvec->bv_page);
		mapping = kmap_local_page(bvec->bv_page);
		buffer = (u8 *)mapping + bvec->bv_offset + position;
		if (write)
			memcpy(security->plain + *used, buffer, count);
		else
			memcpy(buffer, security->plain + *used, count);
		kunmap_local(mapping);
		if (!write)
			flush_dcache_page(bvec->bv_page);
		*used += count;
		position += count;
		if (*used == SECURERAM_UNIT_BYTES) {
			if (write) {
				ret = secureram_security_write(security, *offset);
				if (ret)
					return ret;
			} else {
				secureram_security_clear_unit(security);
			}
			*offset += SECURERAM_UNIT_BYTES;
			*used = 0;
		}
	}
	return 0;
}

static blk_status_t secureram_transfer(struct secureram_device *device,
				       struct request *request)
{
	struct secureram_security *security = &device->security;
	struct req_iterator iter;
	struct bio_vec bvec;
	u64 sector = blk_rq_pos(request);
	size_t length = blk_rq_bytes(request);
	size_t remaining = length;
	size_t used = 0;
	bool write = req_op(request) == REQ_OP_WRITE;
	u64 offset;
	int ret;

	if (request->cmd_flags & REQ_ATOMIC)
		return BLK_STS_NOTSUPP;

	/* Check before multiplying, even though normal block I/O is bounded. */
	if (sector > secureram_security_capacity(security) / SECURERAM_SECTOR_SIZE)
		return BLK_STS_IOERR;
	offset = sector * SECURERAM_SECTOR_SIZE;
	if (offset % SECURERAM_LOGICAL_BLOCK_SIZE ||
	    length % SECURERAM_LOGICAL_BLOCK_SIZE ||
	    !secureram_security_contains(security, offset, length))
		return BLK_STS_IOERR;

	/* Validate all segments before a write can change any backing bytes. */
	rq_for_each_segment(bvec, request, iter) {
		if (!bvec.bv_len || bvec.bv_len > remaining ||
		    bvec.bv_offset >= PAGE_SIZE ||
		    bvec.bv_len > PAGE_SIZE - bvec.bv_offset)
			return BLK_STS_IOERR;
		remaining -= bvec.bv_len;
	}
	if (remaining)
		return BLK_STS_IOERR;

	rq_for_each_segment(bvec, request, iter) {
		ret = secureram_transfer_segment(security, &bvec, write,
						 &offset, &used);
		if (ret) {
			secureram_security_clear_unit(security);
			return BLK_STS_IOERR;
		}
	}
	secureram_security_clear_unit(security);
#ifdef SECURERAM_M4_TEST
	if (write && length)
		pr_info_once("M4 test: real WRITE backing equals ciphertext and differs from plaintext\n");
#endif
	return BLK_STS_OK;
}

static blk_status_t secureram_process_request(struct secureram_device *device,
					      struct request *request)
{
	/* Includes queued requests accepted just before the failure latch. */
	if (READ_ONCE(device->security.state) != SECURERAM_ACTIVE)
		return BLK_STS_IOERR;

	switch (req_op(request)) {
	case REQ_OP_READ:
	case REQ_OP_WRITE:
		return secureram_transfer(device, request);
	case REQ_OP_FLUSH:
		/* Completed writes already reached RAM; this is not persistence. */
		return blk_rq_bytes(request) ? BLK_STS_IOERR : BLK_STS_OK;
	default:
		return BLK_STS_NOTSUPP;
	}
}

static void secureram_io_work(struct work_struct *work)
{
	struct secureram_device *device =
		container_of(work, struct secureram_device, io_work);
	struct secureram_request *command;
	struct request *request;
	unsigned long flags;
	blk_status_t status;

	for (;;) {
		spin_lock_irqsave(&device->pending_lock, flags);
		if (list_empty(&device->pending)) {
			spin_unlock_irqrestore(&device->pending_lock, flags);
			break;
		}
		command = list_first_entry(&device->pending,
					   struct secureram_request, entry);
		list_del(&command->entry);
		spin_unlock_irqrestore(&device->pending_lock, flags);

		request = blk_mq_rq_from_pdu(command);
		status = secureram_process_request(device, request);
		if (READ_ONCE(device->security.state) == SECURERAM_INTEGRITY_FAILED) {
			spin_lock_irqsave(&device->pending_lock, flags);
			device->accepting = false;
			spin_unlock_irqrestore(&device->pending_lock, flags);
		}
		blk_mq_end_request(request, status);
		/* Completion can recycle the request; do not touch it again. */
		cond_resched();
	}
}

static blk_status_t secureram_queue_rq(struct blk_mq_hw_ctx *hctx,
				       const struct blk_mq_queue_data *data)
{
	struct secureram_device *device = hctx->queue->queuedata;
	struct secureram_request *command = blk_mq_rq_to_pdu(data->rq);
	unsigned long flags;

	spin_lock_irqsave(&device->pending_lock, flags);
	if (!device->accepting) {
		spin_unlock_irqrestore(&device->pending_lock, flags);
		return BLK_STS_IOERR;
	}
	blk_mq_start_request(data->rq);
	list_add_tail(&command->entry, &device->pending);
	/* Already queued/running work drains this same protected list. */
	queue_work(device->workqueue, &device->io_work);
	spin_unlock_irqrestore(&device->pending_lock, flags);

	return BLK_STS_OK;
}

static const struct blk_mq_ops secureram_mq_ops = {
	.queue_rq = secureram_queue_rq,
};

static int secureram_open(struct gendisk *disk, blk_mode_t mode)
{
	struct secureram_device *device = disk->private_data;
	u32 state;
	int ret = 0;

	mutex_lock(&device->control_lock);
	state = READ_ONCE(device->security.state);
	if (state == SECURERAM_INTEGRITY_FAILED)
		ret = -EIO;
	else if (state != SECURERAM_ACTIVE)
		ret = -ENOKEY;
	else if (device->openers == UINT_MAX)
		ret = -EBUSY;
	else
		device->openers++;
	mutex_unlock(&device->control_lock);
	return ret;
}

static void secureram_release(struct gendisk *disk)
{
	struct secureram_device *device = disk->private_data;

	/* Target block core flushes/invalidates final mapping before this call. */
	mutex_lock(&device->control_lock);
	device->openers--;
	mutex_unlock(&device->control_lock);
}

static void secureram_admission(struct secureram_device *device, bool accepting)
{
	unsigned long flags;

	spin_lock_irqsave(&device->pending_lock, flags);
	device->accepting = accepting;
	spin_unlock_irqrestore(&device->pending_lock, flags);
}

#ifdef SECURERAM_M4_TEST
/* Exercise the real cursor with deliberately sub-unit/cross-unit fragments. */
static int secureram_test_segments(struct secureram_security *security)
{
	struct bio_vec vectors[3];
	u8 *first = kmalloc(SECURERAM_UNIT_BYTES, GFP_KERNEL);
	u8 *second = kmalloc(SECURERAM_UNIT_BYTES, GFP_KERNEL);
	u64 offset = 0;
	size_t used = 0;
	int i, ret = -ENOMEM;

	if (!first || !second)
		goto out;
	memset(first, 0x35, SECURERAM_UNIT_BYTES);
	memset(second, 0xa7, SECURERAM_UNIT_BYTES);
	bvec_set_virt(&vectors[0], first, 512);
	bvec_set_virt(&vectors[1], second, SECURERAM_UNIT_BYTES);
	bvec_set_virt(&vectors[2], first + 512, SECURERAM_UNIT_BYTES - 512);
	for (i = 0; i < ARRAY_SIZE(vectors); i++) {
		ret = secureram_transfer_segment(security, &vectors[i], true,
						 &offset, &used);
		if (ret)
			goto out;
	}
	memzero_explicit(first, SECURERAM_UNIT_BYTES);
	memzero_explicit(second, SECURERAM_UNIT_BYTES);
	offset = 0;
	used = 0;
	for (i = 0; i < ARRAY_SIZE(vectors); i++) {
		ret = secureram_transfer_segment(security, &vectors[i], false,
						 &offset, &used);
		if (ret)
			goto out;
	}
	if (used || offset != 2 * SECURERAM_UNIT_BYTES ||
	    memchr_inv(first, 0x35, SECURERAM_UNIT_BYTES) ||
	    memchr_inv(second, 0xa7, SECURERAM_UNIT_BYTES)) {
		ret = -EIO;
		goto out;
	}
	/* Restore freshly initialized logical zeros before admitting any opens. */
	for (offset = 0; offset < 2 * SECURERAM_UNIT_BYTES;
	     offset += SECURERAM_UNIT_BYTES) {
		secureram_security_clear_unit(security);
		ret = secureram_security_write(security, offset);
		if (ret)
			goto out;
	}
	pr_info("M4 test: 512/4096/3584-byte split-unit gather/scatter PASS\n");
out:
	secureram_security_clear_unit(security);
	kfree_sensitive(second);
	kfree_sensitive(first);
	return ret;
}
#endif

int secureram_block_query(struct secureram_device *device,
			  struct secureram_ioc_status *status)
{
	mutex_lock(&device->control_lock);
	memset(status, 0, sizeof(*status));
	status->header.version = SECURERAM_ABI_VERSION;
	status->header.size = sizeof(*status);
	status->capacity = secureram_security_capacity(&device->security);
	status->generation = device->security.generation;
	status->state = READ_ONCE(device->security.state);
	status->unit_size = SECURERAM_UNIT_BYTES;
	status->features = SECURERAM_FEATURE_XTS | SECURERAM_FEATURE_LOCK |
		SECURERAM_FEATURE_INTEGRITY;
	mutex_unlock(&device->control_lock);
	return 0;
}

int secureram_block_change(struct secureram_device *device, unsigned int command,
			   u8 *key)
{
	struct secureram_security *security = &device->security;
	int ret = 0;

	mutex_lock(&device->control_lock);
	if (READ_ONCE(security->state) == SECURERAM_DYING) {
		ret = -ENODEV;
		goto out;
	}
	if (device->openers) {
		ret = -EBUSY;
		goto out;
	}
	secureram_admission(device, false);
	flush_workqueue(device->workqueue);
	/* Worker may latch failure while draining: validate only after it ends. */
	if ((command == SECURERAM_IOC_LOAD_KEY &&
	     READ_ONCE(security->state) != SECURERAM_NO_KEY) ||
	    (command == SECURERAM_IOC_LOCK &&
	     READ_ONCE(security->state) != SECURERAM_ACTIVE) ||
	    (command == SECURERAM_IOC_UNLOCK &&
	     READ_ONCE(security->state) != SECURERAM_LOCKED)) {
		ret = -EBUSY;
		goto reopen;
	}
	switch (command) {
	case SECURERAM_IOC_LOAD_KEY:
		ret = secureram_security_load(security, key);
#ifdef SECURERAM_M4_TEST
		if (!ret) {
			ret = secureram_test_segments(security);
			if (ret) {
				security->generation--;
				secureram_security_clear(security);
			}
		}
#endif
		break;
	case SECURERAM_IOC_LOCK:
		WRITE_ONCE(security->state, SECURERAM_LOCKED);
		break;
	case SECURERAM_IOC_UNLOCK:
		WRITE_ONCE(security->state, SECURERAM_ACTIVE);
		break;
	case SECURERAM_IOC_DESTROY_KEY:
		secureram_security_clear(security);
		break;
	default:
		ret = -ENOTTY;
	}
reopen:
	secureram_admission(device, READ_ONCE(security->state) == SECURERAM_ACTIVE);
out:
	mutex_unlock(&device->control_lock);
	return ret;
}

#ifdef SECURERAM_M5_TEST
int secureram_block_tamper(struct secureram_device *device,
			   const struct secureram_ioc_tamper *input)
{
	int ret;

	mutex_lock(&device->control_lock);
	if (device->openers) {
		ret = -EBUSY;
		goto out;
	}
	secureram_admission(device, false);
	flush_workqueue(device->workqueue);
	ret = secureram_security_tamper(&device->security, input);
	secureram_admission(device, READ_ONCE(device->security.state) == SECURERAM_ACTIVE);
out:
	mutex_unlock(&device->control_lock);
	return ret;
}
#endif

static const struct block_device_operations secureram_fops = {
	.owner = THIS_MODULE,
	.open = secureram_open,
	.release = secureram_release,
};

int secureram_block_create(struct secureram_device **result, u64 capacity)
{
	struct queue_limits limits = {
		.logical_block_size = SECURERAM_LOGICAL_BLOCK_SIZE,
		.physical_block_size = SECURERAM_LOGICAL_BLOCK_SIZE,
		.io_min = SECURERAM_LOGICAL_BLOCK_SIZE,
		.max_hw_sectors = SECURERAM_MAX_HW_SECTORS,
		.max_segments = SECURERAM_MAX_SEGMENTS,
	};
	struct secureram_device *device;
	const char *stage = "security/backing allocation";
	int ret;

	device = kzalloc_obj(*device);
	if (!device)
		return -ENOMEM;
	mutex_init(&device->control_lock);

	ret = secureram_security_init(&device->security, capacity);
	if (ret)
		goto free_device;

	spin_lock_init(&device->pending_lock);
	INIT_LIST_HEAD(&device->pending);
	INIT_WORK(&device->io_work, secureram_io_work);
	stage = "workqueue allocation";
	device->workqueue = alloc_ordered_workqueue(SECURERAM_DRIVER_NAME,
						    WQ_MEM_RECLAIM);
	if (!device->workqueue) {
		ret = -ENOMEM;
		goto free_security;
	}

	device->tag_set.ops = &secureram_mq_ops;
	device->tag_set.nr_hw_queues = 1;
	device->tag_set.queue_depth = SECURERAM_QUEUE_DEPTH;
	device->tag_set.numa_node = NUMA_NO_NODE;
	device->tag_set.cmd_size = sizeof(struct secureram_request);
	device->tag_set.flags = BLK_MQ_F_NO_SCHED_BY_DEFAULT;
	stage = "tag-set allocation";
	ret = blk_mq_alloc_tag_set(&device->tag_set);
	if (ret)
		goto destroy_workqueue;

	stage = "disk/queue allocation";
	device->disk = blk_mq_alloc_disk(&device->tag_set, &limits, device);
	if (IS_ERR(device->disk)) {
		ret = PTR_ERR(device->disk);
		goto free_tags;
	}

	device->disk->fops = &secureram_fops;
	device->disk->private_data = device;
	device->disk->flags |= GENHD_FL_NO_PART;
	strscpy(device->disk->disk_name, SECURERAM_DEVICE_NAME,
		sizeof(device->disk->disk_name));
	set_capacity(device->disk, capacity / SECURERAM_SECTOR_SIZE);
	/* major/minors stay zero: add_disk allocates an extended device number. */
	stage = "disk publication";
	ret = add_disk(device->disk);
	if (ret)
		goto put_disk;
	stage = "control publication";
	ret = secureram_control_register(&device->control, device);
	if (ret)
		goto delete_disk;

	*result = device;
	return 0;

delete_disk:
	del_gendisk(device->disk);
put_disk:
	/* Never-published disks release their owned queue through put_disk. */
	put_disk(device->disk);
free_tags:
	blk_mq_free_tag_set(&device->tag_set);
destroy_workqueue:
	destroy_workqueue(device->workqueue);
free_security:
	secureram_security_destroy(&device->security);
free_device:
	pr_err("%s failed: %d\n", stage, ret);
	kfree(device);
	return ret;
}

void secureram_block_destroy(struct secureram_device *device)
{
	/* Open control/block files pin THIS_MODULE; normal unload has no users. */
	secureram_control_unregister(&device->control);
	mutex_lock(&device->control_lock);
	secureram_admission(device, false);
	flush_workqueue(device->workqueue);
	WRITE_ONCE(device->security.state, SECURERAM_DYING);
	mutex_unlock(&device->control_lock);
	/* del_gendisk drains the owned queue; workers must still be runnable. */
	del_gendisk(device->disk);
	destroy_workqueue(device->workqueue);
	put_disk(device->disk);
	blk_mq_free_tag_set(&device->tag_set);
	secureram_security_destroy(&device->security);
	kfree(device);
}
