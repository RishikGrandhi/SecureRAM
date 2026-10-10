# M2: plaintext RAM-backed block device

This design precedes the M2 implementation. The primary target is the user's
Ubuntu 24.04.5 LTS VirtualBox VM, **Linux 7.0.0-38-generic**. M1 is complete,
including the recorded VM runtime check. M2 introduces storage, not security.

## Data path and component boundaries

```text
 User process / filesystem
            |
            v
 Linux VFS / filesystem / page cache (or raw block I/O)
            |
            v
 Linux block layer: bios become requests
            |
            v
 blk-mq: one hardware queue, at most 64 driver tags
            |
            v
 SecureRAM queue_rq: start request, append to protected pending list
            |
            v
 One ordered, reclaim-capable worker: validate and transfer all segments
            |                [future security layer belongs here]
            v
 Storage component: checked byte-range copies
            |
            v
 Zero-initialized vzalloc backing store (64 MiB default)
```

`src/secureram_main.c` validates the capacity parameter and controls module
lifetime. `src/secureram_block.c` owns the device, queue, requests and worker.
`src/secureram_store.c` owns a byte-addressed allocation with checked read/write
functions, independent of block request parsing. There is no crypto, control
ABI, management CLI, or custom statistics infrastructure.

## Registration and selected API

Allocate a blk-mq tag set, then call the current three-argument
`blk_mq_alloc_disk(&tag_set, &limits, device)`. Supply queue geometry in
`struct queue_limits` before allocation. Set the disk name to `secureram0`,
`fops->owner = THIS_MODULE`, capacity in sectors, and `GENHD_FL_NO_PART`.
M2 supports a filesystem on the whole device, without partition scanning.

Leave `major` and `minors` zero: `add_disk()` allocates a dynamic device number
from the block layer's extended device-number space. This avoids a hard-coded
major and a separate major registration resource. Check `add_disk()`'s integer
return value. Successful publication produces sysfs state and a device event;
Ubuntu's devtmpfs/udev creates `/dev/secureram0`. Never create a node with guessed
device numbers. Ordinary block openers pin `THIS_MODULE`, so normal `rmmod`
fails while the disk is mounted/open. Forced unload is not supported.

APIs and ownership were inspected in Ubuntu's extracted target headers and the
official [Linux v7.0 block implementation](https://github.com/torvalds/linux/blob/v7.0/block/genhd.c)
and [blk-mq implementation](https://github.com/torvalds/linux/blob/v7.0/block/blk-mq.c).
In particular, this disk owns its queue: `del_gendisk()` handles its registered
queue teardown, and `put_disk()` handles the never-published failure case and
final queue reference. Do **not** additionally call `blk_mq_destroy_queue()` on
that same queue. No old-kernel compatibility branch is introduced.

## Units, capacity, and backing allocation

| Unit | Meaning in M2 |
| --- | --- |
| Byte | Store offsets and transfer lengths. |
| Sector | Always 512 bytes for block-layer positions and `set_capacity()`. |
| Logical block | 4096 bytes; advertised minimum I/O alignment/unit. |
| Physical block | Advertised as 4096 bytes; no mechanical hardware is implied. |
| Page | Kernel memory mapping unit (`PAGE_SIZE`); do not hard-code it to 4096 in segment handling. |
| MiB | 1048576 bytes. `capacity_mb` uses MiB despite its conventional parameter name. |

The read-only-at-runtime `capacity_mb` parameter defaults to 64 and accepts
integers from **1 through 256**. Validate the range before multiplying in `u64`.
The store checks that its byte size is nonzero and representable as `size_t`.
Default geometry is 67108864 bytes, 131072 sectors, or 16384 logical blocks.
No live resizing is supported. Allocation can still fail below the limit.

Use `vzalloc()` for zeroed virtually contiguous memory with physically scattered
pages; a large contiguous `kmalloc()` allocation is not appropriate. Record the
size only after successful allocation. Free with `vfree()`. All memory is
allocated before the disk is published. No allocation is needed in the I/O path.
Kernel backing is not process swap, but a VM host can still page/snapshot guest
RAM. Memory allocation cleanup is not a secure-erasure guarantee.

## Request lifecycle and data transfer

A request groups one or more bios and potentially many page segments. It is not
one contiguous user buffer. blk-mq allocates a small driver-private list node
with every request via `tag_set.cmd_size`, including the core's internal request
allocation paths. We do not allocate a separate work item for each submission.

1. `queue_rq()` starts the request once with `blk_mq_start_request()`.
2. Under the pending-list spinlock, append its private node and schedule the
   device's single work item. Return `BLK_STS_OK`: the driver now owns completion.
   Dispatch never sleeps or allocates memory. A work item already scheduled is
   sufficient; the worker drains the list, so no request is lost or duplicated.
3. The worker removes one node under the same lock and releases the lock before
   parsing/mapping/copying. Recover the request with `blk_mq_rq_from_pdu()`.
4. Explicitly switch on `req_op()`. READ/WRITE follow the checks below; FLUSH
   succeeds without touching RAM; other operations return `BLK_STS_NOTSUPP`.
5. Finish with **one** `blk_mq_end_request()`. Nothing accesses that request or
   its private node after completion because the block layer may reuse/free it.

Validate the starting sector against `store.size / 512` **before** multiplying
it by 512 in `u64`. Reject unaligned offsets/lengths. Then check
`offset <= size && length <= size - offset`, never an unchecked `offset + length`.
This validates the complete transfer before any write. Pre-walk the page-sized
segments, checking lengths and their sum against `blk_rq_bytes()`; malformed
segment geometry becomes `BLK_STS_IOERR` before changing backing bytes.

Use `rq_for_each_segment()` (the page-sized iterator, not the multi-page bvec
iterator), `kmap_local_page()`, and `kunmap_local()` for each page. READ copies
backing bytes into the mapped request buffer. WRITE copies the request buffer
into backing bytes. Advance a byte offset by each segment's actual length;
individual segments need not be logical-block sized. Perform the architecture's
page-cache maintenance with `flush_dcache_page()` before consuming WRITE data
and after producing READ data. These are kernel-owned block buffers: no
`copy_to_user()`/`copy_from_user()` or userspace pointer dereferencing is involved.

The store independently checks every byte range and returns negative errno for
an invalid range. The block adapter translates transfer failures to I/O status.
Backend calls are made without holding the pending-list lock. Request limits
(128 KiB maximum transfer and 128 segments) bound each worker iteration.

## Supported operations and flush semantics

| Operation | M2 behavior |
| --- | --- |
| READ | Checked, segmented RAM-to-request transfer. Initially unwritten bytes are zero. |
| WRITE | Checked, segmented request-to-RAM transfer, complete only after copying. |
| FLUSH | A delivered zero-data flush succeeds as an ordered no-op. |
| DISCARD / WRITE_ZEROES / SECURE_ERASE | Not advertised; if delivered, return `BLK_STS_NOTSUPP`. |
| Passthrough, zoned commands, other opcodes | `BLK_STS_NOTSUPP`; never interpreted as a read/write. |
| Atomic-write request flag | Unsupported; no atomic-write capability is advertised. |

There is no separate write-back cache: a completed write already reached the
RAM medium. Leave WRITE_CACHE/FUA feature bits unset; the block layer may remove
unneeded flush/FUA work before dispatch. The ordered worker orders delivered
requests but does not promise application syscall order across competing
submitters. `fsync`/flush cannot make RAM survive unload, VM termination, or power
loss. Upper layers may emulate zeroing with ordinary writes even though native
WRITE_ZEROES is unsupported. No discard/zeroing limits are advertised.

## Synchronization

Concurrent `queue_rq()` calls protect **only the pending list** using
`spin_lock_irqsave()`/`spin_unlock_irqrestore()`. This is safe in dispatch
context and also protects against local interrupt reentry. The critical section
contains list operations and non-sleeping work scheduling, never data copying.

`alloc_ordered_workqueue(..., WQ_MEM_RECLAIM)` serializes every store access and
provides a reclaim progress path. No store mutex is needed: the worker is its
sole runtime caller, and teardown keeps the allocation alive until work ends.
The single hardware queue alone would not provide that guarantee. Immutable
geometry and pointers are initialized before publication. blk-mq tags bound the
number of accepted outstanding requests; there is no growing per-I/O allocation.
Later sleepable crypto can run in this worker, but concurrent control operations
will need a separately designed device-state/locking protocol in M3.

## Resource ownership and initialization failures

| Resource | Acquisition/owner | Release |
| --- | --- | --- |
| Device state | `kzalloc_obj()`, module holds pointer after success | `kfree()` last |
| Backing store | Store init / device | Store destroy (`vfree()`) after I/O stops |
| Pending list, spinlock, work item | Embedded in device state | No separate allocation/free |
| Ordered workqueue | Block component | `destroy_workqueue()` while state/backing still live |
| Tags and request-private nodes | `blk_mq_alloc_tag_set()` | `blk_mq_free_tag_set()` after disk/queue and work are finished |
| Gendisk and its owned request queue | `blk_mq_alloc_disk()` | `del_gendisk()` for a published disk, then `put_disk()` |
| Dynamic device number / sysfs / device node | Block core through `add_disk()` | Block core on publication failure or disk removal/final release |

Acquisition order: state, backing, workqueue, tag set, disk/queue, publication.
Every failure releases only successfully acquired resources. An allocation error
pointer must be converted to errno and never passed to `put_disk()`. Tag-set
allocation failure is already unwound by blk-mq; do not free an unallocated set.
If disk allocation or publication fails, the reverse unwind releases disk (if
allocated), tags, workqueue, backing, state. Log the failing stage and errno.
Only successful creation publishes the module's device pointer. No fallible
setup follows successful `add_disk()`.

## Normal unload order

1. Normal module ownership first requires that user openers/mounts are gone.
2. `del_gendisk()` withdraws the disk, stops new admission, drains the owned
   queue, and detaches it from blk-mq. Keep the worker alive throughout this
   call so accepted requests can complete; do not quiesce it into a deadlock.
3. `destroy_workqueue()` waits for the worker's tail after its last request
   completion. The device-global work item remains allocated during this wait.
4. `put_disk()` drops the disk/queue reference, then free the tag set.
5. Free the backing allocation and device state; clear the module pointer.

This uses the target kernel's disk-owned queue lifecycle rather than mixing
cleanup recipes from older tutorials. The worker must not touch a request after
completion. No lock is held while waiting for block work or worker completion.

## Evidence required

Compile against the target headers, inspect warnings/MODPOST and metadata,
run checkpatch and script syntax checks, then use the separate
[VM test procedure](m2-testing.md). The VM must demonstrate raw/direct I/O,
zero initialization, boundaries, parallel requests, optional whole-device ext4,
busy-unload protection, and fresh zeroed storage after reload. Compile-only
checks do not establish runtime correctness. Allocation-failure injection and
exhaustive lock/memory diagnostics remain later hardening work.
