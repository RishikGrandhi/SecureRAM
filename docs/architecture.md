# SecureRAM architecture

M1-M4 are complete and runtime verified. M4 implements AES-256-XTS and privileged
key management. Its exact compile/static and VM runtime evidence is in
[the M4 report](m4-report.md). Historical designs and results remain in the
[M2 design](m2-design.md), [M3 security design](m3-security-design.md) and
[M3 threat model](m3-threat-model.md).

## Purpose and boundary

A real Linux block driver exposes `/dev/secureram0` so ordinary storage tools
and filesystems exercise VFS, bios, blk-mq, kernel memory and request lifetimes.
This is an educational project, not an audited replacement for dm-crypt.
Unlike malloc it supplies a kernel block interface; unlike tmpfs it sits below
a filesystem. Kernel placement alone is not a security property.

```text
application / filesystem / page cache
                |
       Linux block layer, blk-mq
                |
     admission + bounded pending list       /dev/secureramctl
                |                                 |
        ordered sleepable worker          user-copy + host capability check
                |                                 |
       validated page fragments             control mutex
                |                          gate -> drain -> transition
       gather/scatter 4096-byte units              |
                +--------- security context ------+
                          XTS key state
                          plain/cipher staging
                          Kernel Crypto API
                                  |
                         checked RAM byte store
                          ciphertext while ACTIVE
```

Normal data reads return plaintext. Crypto protects only the backing allocation
under the limited backing-disclosure threat model, assuming keys and plaintext
copies elsewhere remain private. The root administrator, kernel, provider and
hypervisor are trusted. XTS supplies no integrity, authentication or freshness.

## Ownership and responsibilities

| Component | Owned resources and responsibility |
| --- | --- |
| Main | Capacity parameter validation and outer lifecycle pointer. |
| Block | Device context, mutex/opener count, admission/pending spinlock, workqueue/work item, tag set, disk/queue, embedded security/control. Validates requests and gathers/scatters units. |
| Security | Embedded store, two 4096-byte kmalloc buffers, aligned IV, state/generation, skcipher transform and reusable request while keyed. No user pointers or blk-mq parsing. |
| Store | One bounded vzalloc allocation, overflow-safe range/copy helpers and explicit clearing. Knows no cipher or key. |
| Control | Registered misc endpoint and safe fixed-size ABI translation. Does not interpret backing bytes. |
| Block core/filesystem | Request pages, normal plaintext caches and successful read output; the driver does not erase caller-owned data. |

All accepted I/O runs on one ordered WQ_MEM_RECLAIM worker. Dispatch only uses
a spinlock and preallocated request-private list node. No sleeping crypto,
user-copy or allocation occurs there. The worker completes each accepted request
once and never touches it again. Dispatch rejection occurs before start/ownership.

## Geometry and cryptographic layout

The capacity is 1-256 MiB, default 64; kernel addressing still counts 512-byte
sectors. Logical and crypto units are 4096 bytes, independent of page/bvec
boundaries. A 64 MiB medium has 16384 units. No partitions or interleaved metadata.
The request limit is 128 KiB, 128 segments, 64 driver tags and one hardware queue.

For a validated byte offset `b`, XTS input is `LE64(b / 4096) || zero[8]`.
Offsets 0/4096/8192 use indices 0/1/2. The provider derives the actual tweak.
This follows M3's large-sector plain64 convention; it promises no dm-crypt format
compatibility. A 64-byte key is two 256-bit AES keys, not a 512-bit AES cipher.
Equal halves are rejected. Rewriting one unit reuses its address input as XTS
permits, leaking equality at the same location across snapshots. This is not
a safe nonce policy for CTR/GCM.

Before a request changes storage, the block layer validates alignment, complete
bounds and the sum/page validity of all fragments. A cursor then assembles full
units across arbitrary page fragments. Each mapping is released before crypto.
WRITE encrypts private plaintext staging into ciphertext staging, then commits
the ciphertext unit. READ copies ciphertext into staging, decrypts privately,
then scatters that unit's plaintext. Staging and request context are explicitly
cleared after use. No vmalloc memory is passed to sg_init_one.

A failed unit is not copied to READ output or committed after failed encryption.
Earlier units of a request may already have changed; no multi-unit transaction
or rollback is promised. XTS does not detect wrong keys or altered ciphertext.

## States and synchronization

```text
NO_KEY -> PREPARING -> ACTIVE <-> LOCKED
             |          |          |
          failure       +-- destroy+
             +---------------> NO_KEY
normal unload -> DYING -> cleared/freed
```

Load is allowed only in NO_KEY. It sets a private transform and eagerly stores
encrypted zeros at every unit before ACTIVE. Failure frees candidate crypto,
clears partial storage and remains NO_KEY. Replacement requires destroy then
load; no old bytes are reinterpreted under another key. Generation counts
successful loads, survives destroy and resets on module reload; it is not an
anti-replay counter. PREPARING is internal because query waits for the mutex.

LOCKED retains the transform but rejects data opens and dispatched I/O. Unlock
re-enables that same key without password checks. Destroy removes the transform,
request and all owned backing/staging contents, returning NO_KEY. Every
transition, including unlock and idempotent destroy, requires zero block openers.

Lock order: block-core open_mutex (only in core callbacks) -> control mutex ->
pending spinlock. Control never calls back into block-core open/close/freeze
while holding its mutex. The worker and dispatcher never acquire the mutex.
An administrator closes admission under pending_lock, releases the spinlock,
drains the workqueue with old key/state alive, changes state, and reopens only
for ACTIVE. Async crypto callbacks only signal completion; draining therefore
includes their buffer/request lifetime. No spinlock spans sleeping work.

The target core balances successful driver open/release callbacks and flushes/
invalidates the final block mapping before release decrements the driver count.
Thus a transition cannot pass while the last close still flushes old contents.
Fresh opens serialize against transitions. Filesystem mounts remain open users;
key destruction beneath a mount is rejected rather than attempted.

## Lifecycle and failure unwinding

Allocate device, backing/staging, workqueue, tags and disk in that order.
Publish the block disk keyless, then the control endpoint. If control publication
fails, remove/drain the disk before normal reverse cleanup. Earlier failures
release only successfully acquired resources. Crypto allocation happens only
on a key load, while admission is closed and no block user exists.

Open control and block files pin THIS_MODULE. Normal unload cannot start while
such files exist; misc deregistration alone would not revoke an open file.
Unload unregisters control, closes admission, drains and marks DYING, releases
the control mutex, removes the disk while the worker remains available, destroys
the worker, drops disk/tags, and clears/frees security/store/device state.
Do not force unload. Crash/power loss cannot promise orderly cleanup.

## Scope and evidence

The shared UAPI is in `include/uapi/secureram.h`; details and error behavior are
in [the M4 report](m4-report.md). There is no key export, mmap, data debug ioctl,
password handling or production management application. Native discard,
WRITE_ZEROES and atomic writes remain unsupported. FLUSH is an ordered no-op;
no write-back cache is advertised, so the block core may elide empty flushes.

The opt-in test build adds internal backing comparisons and split-unit checks;
the production build omits them. Both require matching-kernel runtime tests.
Explicit memory clearing covers named owned buffers, not all physical copies,
caches, CPU registers, dumps, hibernation, snapshots or root/kernel compromise.
See [the VM procedure](m4-testing.md). M5 authentication and its metadata/freshness
design need a separate request. Stop after M4.
