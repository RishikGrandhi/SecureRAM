// SPDX-License-Identifier: GPL-2.0-only
#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/blk-mq.h>
#include <linux/blkdev.h>
#include <linux/err.h>
#include <linux/highmem.h>
#include <linux/list.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/workqueue.h>

#include "secureram_block.h"
#include "secureram_config.h"
#include "secureram_store.h"

struct secureram_device {
	struct secureram_store store;
	struct blk_mq_tag_set tag_set;
	struct gendisk *disk;
	struct workqueue_struct *workqueue;
	struct work_struct io_work;
	/* Protects pending against concurrent dispatch and worker dequeue. */
	spinlock_t pending_lock;
	struct list_head pending;
};

/* Allocated by blk-mq with each request; never allocated during dispatch. */
struct secureram_request {
	struct list_head entry;
};

static blk_status_t secureram_transfer(struct secureram_device *device,
				       struct request *request)
{
	struct secureram_store *store = &device->store;
	struct req_iterator iter;
	struct bio_vec bvec;
	u64 sector = blk_rq_pos(request);
	size_t length = blk_rq_bytes(request);
	size_t remaining = length;
	bool write = req_op(request) == REQ_OP_WRITE;
	u64 offset;

	if (request->cmd_flags & REQ_ATOMIC)
		return BLK_STS_NOTSUPP;

	/* Check before multiplying, even though normal block I/O is bounded. */
	if (sector > store->size / SECURERAM_SECTOR_SIZE)
		return BLK_STS_IOERR;
	offset = sector * SECURERAM_SECTOR_SIZE;
	if (offset % SECURERAM_LOGICAL_BLOCK_SIZE ||
	    length % SECURERAM_LOGICAL_BLOCK_SIZE ||
	    !secureram_store_contains(store, offset, length))
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
		void *mapping;
		void *buffer;
		int ret;

		if (write)
			flush_dcache_page(bvec.bv_page);
		mapping = kmap_local_page(bvec.bv_page);
		buffer = (u8 *)mapping + bvec.bv_offset;
		if (write)
			ret = secureram_store_write(store, offset, buffer,
						    bvec.bv_len);
		else
			ret = secureram_store_read(store, offset, buffer,
						   bvec.bv_len);
		kunmap_local(mapping);
		if (!write)
			flush_dcache_page(bvec.bv_page);
		if (ret)
			return BLK_STS_IOERR;
		offset += bvec.bv_len;
	}

	return BLK_STS_OK;
}

static blk_status_t secureram_process_request(struct secureram_device *device,
					      struct request *request)
{
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

	blk_mq_start_request(data->rq);
	spin_lock_irqsave(&device->pending_lock, flags);
	list_add_tail(&command->entry, &device->pending);
	/* Already queued/running work drains this same protected list. */
	queue_work(device->workqueue, &device->io_work);
	spin_unlock_irqrestore(&device->pending_lock, flags);

	return BLK_STS_OK;
}

static const struct blk_mq_ops secureram_mq_ops = {
	.queue_rq = secureram_queue_rq,
};

static const struct block_device_operations secureram_fops = {
	.owner = THIS_MODULE,
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
	const char *stage = "backing allocation";
	int ret;

	device = kzalloc_obj(*device);
	if (!device)
		return -ENOMEM;

	ret = secureram_store_init(&device->store, capacity);
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
		goto free_store;
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

	*result = device;
	return 0;

put_disk:
	/* Never-published disks release their owned queue through put_disk. */
	put_disk(device->disk);
free_tags:
	blk_mq_free_tag_set(&device->tag_set);
destroy_workqueue:
	destroy_workqueue(device->workqueue);
free_store:
	secureram_store_destroy(&device->store);
free_device:
	pr_err("%s failed: %d\n", stage, ret);
	kfree(device);
	return ret;
}

void secureram_block_destroy(struct secureram_device *device)
{
	/* del_gendisk drains the owned queue; workers must still be runnable. */
	del_gendisk(device->disk);
	destroy_workqueue(device->workqueue);
	put_disk(device->disk);
	blk_mq_free_tag_set(&device->tag_set);
	secureram_store_destroy(&device->store);
	kfree(device);
}
