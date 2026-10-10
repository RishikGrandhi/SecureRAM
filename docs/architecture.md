# SecureRAM architecture

Status: M2 plaintext block storage is implemented; VM runtime acceptance is
pending. M1 is complete, including the user's VM lifecycle verification. This
document preserves the long-term design; the concrete current behavior and
resource lifecycle are specified in [the M2 design](m2-design.md). Security,
key management, and control interfaces below remain future work.

## Objective and problem

SecureRAM will be a volatile Linux block storage device, `/dev/secureram0`, whose
bytes live in memory owned by a kernel driver. It is a university OS project for
learning device lifetimes, the block layer, memory management, concurrency, and
kernel cryptography through a usable storage interface.

The intended problem is temporary storage with an explicit security lifecycle:
later versions will encrypt the backing store, authenticate stored blocks,
restrict administration, and erase driver-owned secrets on teardown. Persistence
across unload or restart is deliberately outside the design. M2 implements
plaintext storage and provides no encryption/authentication guarantees.

### How it differs from other memory storage

| Mechanism | Ownership and interface | Relationship to SecureRAM |
| --- | --- | --- |
| `malloc()` | A process receives virtual addresses in its own address space. | It creates neither a block device nor a filesystem-facing I/O endpoint. SecureRAM will own memory independently of an individual application and service kernel block requests. |
| Ordinary RAM disk | A driver exposes RAM through a block device. | This is the functional baseline for M2. Later SecureRAM milestones add an explicit key lifecycle, encrypted backing, authentication, and verified erasure paths. |
| `tmpfs` | An in-memory filesystem, with swap behavior controlled by its configuration and environment. | SecureRAM is a block device beneath a filesystem, not a filesystem implementation. |

This is an educational design, not a claim to replace established Linux storage
security such as device-mapper encryption. A RAM disk plus existing encryption
can solve real deployment needs; implementing and explaining the integration is
the purpose of this project.

## Why the kernel

The driver must participate in the Linux block layer so ordinary storage tools
and filesystems can use a real device. Kernel ownership also gives us control of
the backing allocation and request lifecycle. Kernel placement alone does not
provide confidentiality or trust: bugs here can crash the machine, and a
compromised kernel can inspect memory and keys.

## Data and control paths

```text
                 USER SPACE                         KERNEL SPACE

 application -- read/write --> system calls --> VFS / filesystem
                                                    | page cache / writeback
 storage utility -- raw block-device I/O ------------+
                                                    v
                                          Linux block layer (bios/requests)
                                                    |
                                          /dev/secureram0
                                                    |
                                  +-----------------v------------------+
                                  | SecureRAM block adapter (blk-mq)   |
                                  | validate / bound / dispatch        |
                                  +-----------------+------------------+
                                                    |
                                  +-----------------v------------------+
                                  | bounded, ordered worker context    |
                                  | M2: plaintext read/write           |
                                  | later: encrypt/authenticate        |
                                  +-----------------+------------------+
                                                    |
                                  +-----------------v------------------+
                                  | driver-owned volatile RAM          |
                                  | later: ciphertext + private tags   |
                                  +------------------------------------+

 future admin tool --> separate control endpoint --> permission checks
                                                    |
                                         device/key state transitions

 M1 ONLY: module loader --> secureram_init() --> kernel log
          module unloader --> secureram_exit() --> kernel log
```

The diagram shows logical routing: the `/dev` node identifies the kernel block
device; it is not a second copy of the data. Filesystem I/O may be buffered, so
an application's successful `write()` need not mean the driver has received the
request yet. A future device flush will order completed RAM writes; it cannot
make volatile memory survive power loss.

## Components and boundaries

| Area | Responsibility | First milestone |
| --- | --- | --- |
| `src/secureram_main.c` | Module entry/exit, metadata, lifecycle orchestration. | M1 |
| `include/secureram_config.h` | Names, version, initial geometry defaults. | M1 |
| Block adapter | Disk registration, queue limits, request validation/completion. | M2 |
| RAM store | Allocate/free capacity; bounded copies using byte offsets. | M2 |
| Security layer | Transform storage units, validate authentication, erase temporary secrets. | M3/M4 |
| Control plane | Privileged key/device transitions, stable userspace interface. | M3 |
| Statistics | Counters and safe readout without secret material. | M5 |
| `tools/`, `tests/`, `scripts/` | Administration, validation, developer workflow. | Incremental |

These are responsibility boundaries, not an instruction to create empty C
files or speculative callback hierarchies. M2 adds block and store source
objects to the existing composite Kbuild target without changing the module name.
Internal shared headers belong in `include/`; a future userspace ABI must have
its own deliberately reviewed UAPI header with fixed-width fields.

## Block interface decision

Use the modern request-based **blk-mq** interface in M2. A bio-based RAM driver
is also valid, but request dispatch through a bounded queue provides a clear
place for future crypto work and completion accounting. Do not use legacy
`request_fn`, `blk_init_queue()`, or old `make_request_fn` tutorials.

M2 uses one disk and one hardware dispatch queue. Accepted requests enter a
spinlock-protected list using their preallocated private list nodes. A single
device-owned work item on an ordered workqueue performs backend operations
and completes each accepted request exactly once. This intentionally favors a
clear concurrency model over peak throughput. No sleeping allocation, mutex,
or potentially sleeping crypto operation belongs in a normal dispatch callback.
The [M2 design](m2-design.md) specifies allocation and shutdown ordering against
the target kernel's disk-owned queue lifecycle.

The API reference is the kernel's [blk-mq documentation](https://www.kernel.org/doc/html/latest/block/blk-mq.html).
Linux has no stable in-kernel driver ABI. The M2 target is now Linux
**7.0.0-38-generic** in the user's Ubuntu VM; its headers and official source
were consulted. Earlier Linux 6.x planning does not imply broad compatibility.

## Geometry and RAM backing

M2's default geometry is **64 MiB**, **4096-byte logical blocks**, and the
Linux block layer's **512-byte sector accounting units**. These are different
concepts: the disk capacity is 131072 sectors or 16384 logical blocks. A larger
logical block gives the future authentication layer a clear 4 KiB protection
unit. M2 advertises these alignment requirements and supports a load-time
`capacity_mb` parameter from 1 through 256 MiB.

M2 uses a zero-initialized `vzalloc()` backing allocation, with physically
scattered pages. This avoids requiring a
large physically contiguous allocation. Allocate the complete initial capacity
before publishing the disk; allocation failure must leave no visible device.
The backing allocation is kernel memory, not ordinary swappable process memory.
In a VM, the host may still page or snapshot guest memory.

Use `sector_t` for block addresses and `u64` for capacity/offset arithmetic where
needed; validate conversions to `size_t` for the target architecture. Bounds
checks must avoid overflowing `offset + length` (check the offset first, then
compare length to remaining capacity). A bio/request may span multiple pages
and segments. M2 must walk and map those segments correctly; neither request
buffers nor the backing pages may be assumed physically contiguous.

There will be no mmap of backing memory into userspace. Later tag, nonce, and
version metadata will occupy private allocations outside advertised capacity.
Only advertise optional operations such as discard or write zeroes when their
semantics have actually been implemented and tested. Unsupported operations
must receive a deliberate block status, not silently succeed.

## Planned security and control

Use the Linux [Kernel Crypto API](https://docs.kernel.org/crypto/index.html),
not a custom cipher. Encryption alone does not authenticate data. Before M3,
choose a reviewed storage construction and document its key/nonce model; before
M4, finalize authentication, associated data, and failure behavior. Reserve room
in the design now for per-unit metadata and serialized updates.

The intended endpoint is authenticated units with a device/key-generation
identity and block address bound into authentication. Nonces must remain unique
under each key across repeated writes. A sector number alone is not a safe
nonce for a construction requiring uniqueness. On reads, verify authentication
before returning plaintext; a failed check becomes an I/O error. Unwritten
units need an explicit initialized/unwritten representation: all-zero bytes are
not automatically valid ciphertext or tags. Ciphertext and its metadata must
change together under the concurrency rules.

A separate administrative endpoint is planned, likely a misc character device
with a small, versioned ioctl ABI. Its name and ABI are not defined in M1.
It will validate lengths, use safe kernel user-copy helpers, enforce privileges
and device permissions, and never return keys in logs or query output. The
block path already receives kernel-managed buffers; it must not treat them as
raw userspace pointers. A later CLI will call the control endpoint.

Keys will be per-device kernel-owned secrets with explicit ownership, cleanup,
and synchronization. No hard-coded keys or secrets in module parameters,
command-line arguments, or logs. Removing a key cannot leave work using freed
key material. The initial key-replacement policy should require an idle,
unmounted device and an explicit destructive reset; live rekeying and persistence
are not assumed. M3 must specify locked-device I/O behavior and temporary buffer
cleanup before adding code. Kernel primitives such as `memzero_explicit()` or
appropriate sensitive-free helpers must be matched to actual allocation types.

## Concurrency and lifetime

M1 owns no allocations, work items, queues, or device registrations, and exposes
no concurrent I/O path. It therefore needs no locks or failure unwinding code.

For M2, the ordered worker serializes backing-store access, including overlapping
writes. A single hardware queue alone does **not** guarantee serialization.
Queue depth bounds work and memory consumption; M2 preallocates request-private
pending-list nodes with blk-mq tags and uses one device-owned work item.

Later control operations will use a device-state mutex in sleepable context.
Key changes must gate admission and drain existing work before changing or
erasing key state. Do not hold a lock required by a worker while draining that
worker. Completion callbacks and teardown need an explicit ownership model;
statistics can later use atomics or short locks appropriate to their context.
Lock ordering and the state machine will be documented with their implementation.

## Security boundaries and honest limitations

- The eventual protection target is driver-owned backing bytes and orderly
  handling of keys, with access checks on the public interfaces.
- Authorized readers necessarily receive plaintext. Plaintext may also exist in
  application buffers, filesystem/page caches, and transient kernel buffers.
  Encrypting the backing allocation does not encrypt all system RAM.
- The kernel, privileged administrators, host/hypervisor, and crypto
  implementation are trusted. This design cannot withstand a compromised
  kernel, arbitrary physical-memory access, or a hostile hypervisor.
- Volatility is not proof of secure deletion. Future explicit erasure can cover
  buffers we own during orderly cleanup; crashes, dumps, hibernation, host swap,
  snapshots, and hardware memory remanence are outside that guarantee.
- Authentication can detect invalid stored units under its stated model. Full
  rollback protection requires trusted freshness state outside the attacker's
  control and is not promised by keeping counters beside ciphertext in RAM.
- Capacity and queue limits bound resource use; encryption does not prevent
  denial of service. M2 bounds storage/queued work but implements no security layer.

## Lifecycle

**M1:** the loader resolves symbols and metadata, runs `secureram_init()`, and
records the loaded module. Initialization logs the version and succeeds. Normal
unload calls `secureram_exit()`, which logs completion. Static metadata is owned
by the module loader. There are no driver resources to release and no `/dev` node.

**M2 onward:** initialize private state, allocate backing and bounded work
resources, configure the disk/queue, and publish the device last. On failure,
unwind only resources acquired, in reverse ownership order. On shutdown, stop
new admission and withdraw the disk, account for open holders, drain all accepted
work/completions, then release queues, workers, and backing state according to
the target kernel's lifetime rules. Later, erase secrets before freeing their
storage. A queue quiesce alone is not evidence that all accepted I/O is finished.
Never free memory while any request or control operation can still reference it.

## Milestones and acceptance gates

| Milestone | Scope | Evidence required before moving on |
| --- | --- | --- |
| M1: foundation | Architecture, module lifecycle, metadata/configuration, Kbuild, workflow. | Compile with warnings inspected; load/log/unload when environment permits, otherwise record the exact blocker. |
| M2: block storage | One plaintext RAM-backed disk, modern blk-mq dispatch, bounds checks, clean failure/unload paths. | Raw I/O round trips, zero-initialized reads, geometry and boundary checks, filesystem smoke test, concurrent I/O and repeated lifecycle checks on a disposable Linux system. |
| M3: confidentiality and key lifecycle | Reviewed crypto construction, encryption, privileged control endpoint, minimal management utility, key and temporary-buffer erasure. | Locked/unlocked behavior, repeated-write nonce/tweak reasoning, failed setup cleanup, safe key removal. No authentication claims until M4 passes. |
| M4: authenticated storage | Integrity metadata, authenticated reads/writes, atomic per-unit updates, tamper demonstration. | Corruption fails closed; no unauthenticated plaintext release; unwritten-unit, failure and concurrency tests. |
| M5: hardening and observability | Access-control review, device statistics, failure injection, automated stress/lifecycle coverage. | Lock/memory diagnostics where available, allocation-failure tests, bounded-resource behavior, teardown during activity. |
| M6: evaluation | Reproducible benchmarks, security demonstrations, final report and viva material. | Measured overhead against a documented RAM-disk baseline and an accurate account of the threat model. |

Stop after each milestone and review its evidence. M2 stops at plaintext block
storage; crypto, keys, ioctl, a CLI, and custom statistics remain later work.
