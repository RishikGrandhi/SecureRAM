# SecureRAM architecture

M1-M5 are complete and runtime verified. M5 adds Encrypt-then-MAC integrity to
M4's XTS and privileged key management. Its successful Ubuntu VM acceptance,
current design and evidence are in [the M5 report](m5-report.md).
M4's completed evidence is in [its report](m4-report.md). Historical designs remain in the
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
                          XTS + HKDF/HMAC key state
                          plain/cipher staging
                          Kernel Crypto API
                                  |
                         checked ciphertext/tag pair store
                          ciphertext + 32-byte tags
```

Normal data reads return plaintext after successful HMAC verification. The kernel,
provider and hypervisor remain trusted. XTS supplies confidentiality; a separate
HMAC supplies integrity, with no same-unit same-generation replay protection.
See the [M5 threat model](m5-report.md#threat-model-and-claims).

## Ownership and responsibilities

| Component | Owned resources and responsibility |
| --- | --- |
| Main | Capacity parameter validation and outer lifecycle pointer. |
| Block | Device context, mutex/opener count, admission/pending spinlock, workqueue/work item, tag set, disk/queue, embedded security/control. Validates requests and gathers/scatters units. |
| Security | Embedded store, two 4096-byte buffers, IV, 64-byte tag scratch, state/generation, XTS transform/request and HMAC transform/descriptor. Temporary HKDF secrets during setup. No user pointers or blk-mq parsing. |
| Store | Bounded ciphertext/tag vzalloc allocations, checked whole-unit pair copies and explicit clearing. Knows sizes but no cipher or key. |
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

Per-unit tags are 32 bytes, in a separate array. Default overhead is 16384*32 =
524288 bytes (512 KiB, 0.78125%). HMAC input is exactly the 16 bytes
`SecureRAM-M5-MAC`, LE64(generation), LE64(unit index), then 4096 ciphertext bytes.
No NUL, host-layout structs, tag truncation or partial-unit MAC. The 32-byte MAC
key is HKDF-SHA-256 of the existing 64-byte input, with fixed domain-separated
salt/info; XTS keeps that input. See [exact format and keys](m5-report.md#exact-format-keys-and-memory).

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
WRITE encrypts private plaintext staging, calculates HMAC, then commits both
ciphertext and tag after validating both ranges. READ copies ciphertext/tag,
verifies with crypto_memneq, decrypts privately only on success, then scatters
that unit's plaintext. Staging and request context are explicitly
cleared after use. No vmalloc memory is passed to sg_init_one.

A failed unit is not copied to READ output or committed after failed encryption.
Earlier units of a request may already have changed; no multi-unit transaction
or rollback is promised. A tag mismatch fails the unit without decrypt/scatter
and latches the entire device. Full-unit overwrites do not use old data; damage
overwritten before any verification may go undetected. There is no background scrub.

## States and synchronization

```text
NO_KEY -> PREPARING -> ACTIVE <-> LOCKED
             |          |          |
          failure       |          +-- destroy -> NO_KEY
             |          +-- mismatch -> INTEGRITY_FAILED
             |          |                     |
             +----------+-- destroy ----------+-> NO_KEY
normal unload -> DYING -> cleared/freed
```

Load is allowed only in NO_KEY. It sets both private transforms and eagerly stores
encrypted zeros and tags at every unit before ACTIVE. Failure frees candidate crypto,
clears partial storage and remains NO_KEY. Replacement requires destroy then
load; no old bytes are reinterpreted under another key. Generation counts
successful loads, survives destroy and resets on module reload; it is not an
anti-replay counter. PREPARING is internal because query waits for the mutex.

LOCKED retains both transforms but rejects data opens and dispatched I/O. Unlock
re-enables that same key without password checks. Destroy removes the transform,
request, HMAC descriptor and all owned tags/backing/staging, returning NO_KEY.
Every administrative transition, including unlock and idempotent destroy,
requires zero block openers. The worker can latch integrity failure during I/O.

HMAC mismatch sets INTEGRITY_FAILED=4 with WRITE_ONCE; all concurrent state
readers use READ_ONCE. The worker closes admission before completion and fails
already queued work, including delivered FLUSH. QUERY works; new opens return
EIO. Only destroy after users close can clear the latch; lock/unlock/load return
EBUSY. Control checks transitions after drain so it cannot overwrite a failure.
DYING is internal value 5; existing ioctl layouts and numbers are unchanged.

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

Allocate device, ciphertext/integrity metadata/staging, workqueue, blk-mq tags
and disk in that order.
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
in [the M5 report](m5-report.md#state-machine-and-control-abi-delta). There is no key export, mmap,
password handling or production management application. Native discard,
WRITE_ZEROES and atomic writes remain unsupported. FLUSH is an ordered no-op;
no write-back cache is advertised, so the block core may elide empty flushes.

M5_TEST=1 adds bounded privileged corruption of a selected ciphertext/tag byte
or relocation of a whole pair, with zero openers and gate/drain exclusion. It
also checks index/generation binding internally. M4_TEST=1 still adds internal
backing comparisons and split-unit checks. Production omits all test handlers
and strings. Both variants require matching-kernel runtime tests.
Explicit memory clearing covers named owned buffers, not all physical copies,
caches, CPU registers, dumps, hibernation, snapshots or root/kernel compromise.
See [the VM procedure](m5-testing.md). Stop after M5 review.
