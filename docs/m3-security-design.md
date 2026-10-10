# M3 security architecture and crypto integration design

Date: 2026-10-10 (Asia/Calcutta). Design written before M3 code restructuring.
**M3 is plaintext pass-through only.** This document chooses future mechanisms;
it implements no cipher, key loading, control ABI, authentication, or rekey.
Read with the [threat model](m3-threat-model.md) and [M2 design](m2-design.md).

## 1. Baseline and responsibility boundary

The clean baseline is `main` at `6be414b`, the completed M2 merge. M1/M2 runtime
acceptance is recorded in the repository. M3 starts on
`m3-security-architecture`, preserving those commits and reports.

Current path after the M3 refactor:

```text
application / filesystem -> Linux block layer -> blk-mq
  -> pending list (short spinlock) -> single ordered worker
  -> validate request -> map each page segment
  -> secureram_security_read/write (PLAINTEXT pass-through)
  -> secureram_store_read/write -> vzalloc backing (PLAINTEXT)
```

| Component | Owns / understands | Must not absorb |
| --- | --- | --- |
| Block adapter | Disk/tags/queue, pending list/worker, request validation, page mapping, eventual unit gather/scatter, block status/completion | Cipher choice, key bytes, tag format, tweak generation |
| Security layer | Embedded store lifecycle and byte-transfer boundary now; later private transform, key state, crypto-unit processing, scratch and metadata | blk-mq request parsing, raw userspace pointers |
| Store | Allocation/free, capacity and overflow-safe byte copies | Ciphers, keys, authorization, request ownership |
| Future control adapter | User-copy/ABI checks, host privilege checks, serialized administrative transitions | Direct access to backing/key internals by CLI/GUI |

M3 adds an embedded `struct secureram_security` containing the store, plus
init/destroy/capacity/range/read/write functions. The block component uses only
these functions; store representation remains an internal header detail, not
UAPI. No virtual methods, configurable crypto backend, state enum, extra
allocation, locking or dummy key is useful yet. Init delegates store allocation;
destroy delegates ordinary `vfree()`. The block component still owns the outer
device and decides when all I/O has ended.

Calls are synchronous: return zero or a negative errno; retain no buffer
pointer. Buffers are valid kernel addresses for the supplied length, with no
overlap with backing. M3 accepts arbitrary in-range byte fragments because a
valid request can contain segments smaller than one logical block. No security
function accepts a `struct request` or user address. Only the ordered worker
calls transfer functions at runtime; lifecycle calls occur before publication
or after drain. Capacity is immutable after successful init.

## 2. Future read and write path

```text
WRITE: request pages (plaintext) -> gather a complete 4096-byte unit
       -> security: encrypt private staging -> checked store write (ciphertext)
READ:  checked store read (ciphertext) -> security: decrypt private staging
       -> scatter complete plaintext unit into request pages -> block completion
```

In the integrity milestone, verify before the READ scatter, and commit WRITE
ciphertext plus tag/metadata as one serialized unit. Scratch is cleared on both
success and failure. Cipher execution and authentication belong in security.c.

M4 will change the transfer loop from per-segment forwarding to a cursor that
gathers/scatters complete units across segments. Keep the existing full-request
prevalidation, page-cache maintenance, queueing and completion logic. It is a
local transfer-loop change, not a rewrite of dispatch/lifetime. The security
read/write signatures can remain byte-addressed; encrypted-mode implementations
must require aligned offsets and whole-unit lengths. The adapter will satisfy
that stronger contract. **Do not encrypt each M3 segment independently.**

Use preallocated, page-backed or suitably aligned kmalloc scratch (at least one
plaintext and one ciphertext unit per serial worker). The block adapter gathers
or scatters only; security owns the scratch lifetime and transformation. Map,
copy, then unmap each request page before starting crypto. A `kmap_local_page()`
address must not be handed to a different execution context or retained by a
callback. Do not use `sg_init_one()` directly on vmalloc backing: use the scratch
pages/scatterlists and store copies. Crypto must not encrypt the caller's WRITE
pages in place. Future direct security-unit tests need no blk-mq request at all.

## 3. Construction choice

| Candidate | Fit for rewritable block storage | Decision |
| --- | --- | --- |
| AES-XTS | Length preserving; deterministic address-based tweaks support random reads and overwrites without nonce/tag storage. Reveals equality at the same position across snapshots; no authentication or replay detection. | Select for the first confidentiality milestone. |
| AES-CTR | Length preserving, but reuse of a key/counter stream across overwrites exposes relationships between plaintexts. Sector address alone cannot give a new stream per write. Requires generation/nonce metadata and careful counter allocation; still unauthenticated. | Reject as the initial storage construction. |
| AES-GCM (AEAD) | Adds authentication and associated data, but needs tags and a nonce unique under the key for every encryption, including overwrites and initialization. Address alone is unsafe. Failed-decrypt output must remain private. | Reconsider in the integrity milestone with a complete metadata/nonce design. |

NIST specifies XTS-AES for storage confidentiality and explicitly excludes
authentication; this matches the first implementation's limited purpose
([SP 800-38E](https://csrc.nist.gov/pubs/sp/800/38/e/final)). Linux dm-crypt uses
the established `xts(aes)`/`plain64` conventions and documents the distinction
between sector accounting and large encryption units
([dm-crypt](https://docs.kernel.org/admin-guide/device-mapper/dm-crypt.html)).
This selection is a SecureRAM design decision, not a claim of certification.

Use the Kernel Crypto API **`xts(aes)` skcipher**, with a **64-byte combined key**:
two independently generated 256-bit AES keys, data key followed by tweak key.
This is AES-256-XTS, not a 512-bit AES cipher. Accept exactly 64 bytes in the
future ABI; reject equal halves using the provider's weak-key rejection flag
and check setkey failure. No passwords, key derivation, fixed keys, automatic
plaintext fallback, or user-selected cipher strings. Input entropy is a trusted
provisioning responsibility; length validation cannot prove randomness.
The inspected [XTS key checks](https://github.com/torvalds/linux/blob/v7.0/include/crypto/xts.h)
explain why equal-half rejection must not depend only on FIPS mode.

## 4. Data units and exact tweak convention

| Quantity | Chosen meaning |
| --- | --- |
| Kernel sector | 512 bytes, unchanged for `blk_rq_pos()` and capacity |
| Logical block and crypto data unit | 4096 bytes (8 kernel sectors; 256 AES blocks) |
| AES block | 16 bytes; not the logical block size |
| Unit index `u` | Validated byte offset / 4096, equivalently aligned starting sector / 8 |
| XTS input IV | 16 bytes: little-endian 64-bit `u`, followed by eight zero bytes |
| Backing location | Byte offset `u * 4096`, length 4096; no interleaved keys/tags |

Examples: byte offsets 0, 4096, 8192 use indices 0, 1, 2 (not 0, 8, 16).
At 64 MiB the final index is 16383; at 256 MiB it is 65535. Validate capacity,
sector multiplication, full request range and unit alignment before conversion.
This is the `plain64` **large-sector numbering** convention described by
dm-crypt's `sector_size:4096` plus `iv_large_sectors`; it does not imply a
dm-crypt container format or interoperability guarantee.

The Crypto API consumes this input and derives the XTS tweak internally.
SecureRAM must not implement AES or tweak multiplication itself. Reset the IV
for each unit because the provider may modify request IV storage. The input
is public address metadata, not a secret or randomly generated nonce. Distinct
units under a key use distinct indices. Rewriting the same unit intentionally
reuses its XTS input: valid XTS storage semantics, with equality/history leakage.
That reasoning **must not be copied to CTR/GCM**. Use a fresh independent key
for each device/destructive generation; the driver cannot prove an externally
supplied key has never been reused elsewhere.

Keep 4096-byte alignment at the external block interface. Small buffered file
writes are assembled by upper layers; unsupported partial logical-block raw
requests are rejected. Segments may split a unit or contain parts of several
units, independent of `PAGE_SIZE`; the future cursor must handle both. There is
no partial-unit crypto or read-modify-write scheme in this design. Ciphertext
stealing is unnecessary for complete 4096-byte units. No native discard,
WRITE_ZEROES or atomic-write capability is added.

An all-zero allocation is **not encrypted zero plaintext**. During future
key setup, with admission closed, encrypt a zero unit at every address before
entering ACTIVE. This eager initialization is simple and bounded at 256 MiB,
preserves fresh-zero read semantics, and avoids an unauthenticated validity
bitmap. Failure leaves the device inaccessible and clears partial state. A
future integrity implementation must also initialize valid tags.

## 5. Kernel API integration plan and inspected environment

On 2026-10-10 the local build host is Ubuntu 26.04 under WSL2, running
`6.18.33.2-microsoft-standard-WSL2`. No matching WSL build tree was found.
The existing M2 cache contains Ubuntu's prepared `7.0.0-38-generic` target
headers, including their common headers. These match the recorded VM release,
but M4 must inspect the VM's then-running kernel again.

Inspected locally under
`/home/rishik_grandhi/.cache/secureram-m2-20261010/root/usr/src/`:

- `linux-headers-7.0.0-38-generic/include/generated/utsrelease.h` and build config.
- Common `include/crypto/skcipher.h`, `include/crypto/xts.h`,
  `include/linux/crypto.h`, `include/linux/string.h`, `include/linux/slab.h`,
  and `include/linux/blkdev.h` in `linux-hwe-7.0-headers-7.0.0-38`.

The future worker allocates a transform and request before activation; checks
allocation, IV size (16), key setup, and operation results; and waits for an
asynchronous provider's final completion before reusing buffers or completing
the block request. Use the documented callback/`crypto_wait_req()` pattern,
including backlog handling; returning `-EINPROGRESS` is not success.
`setkey()` is only used on a new, unpublished transform after old I/O drains.
Provider selection, allocation flags, and reclaim progress must be tested:
preallocate request/scratch and avoid filesystem-recursive allocation from the
worker. `WQ_MEM_RECLAIM` alone cannot guarantee an arbitrary crypto provider's
progress. No provider is allocated, executed, or runtime-tested in M3.

Reference: [skcipher API](https://docs.kernel.org/crypto/api-skcipher.html) and
the target headers above. Prefer the supported software/CPU implementation for
the initial VM target; hardware offload adds DMA and cleanup assumptions.

## 6. Integrity direction, separate from encryption

Reserve private per-unit metadata outside advertised block capacity; only the
security layer may interpret it. M3 allocates none. Candidate approaches:

- **XTS plus encrypt-then-MAC:** independently keyed MAC over a fixed,
  unambiguous encoding of format, device identity, key generation, unit index,
  version and ciphertext. Verify before decryption/scatter. Keeps the chosen
  XTS layout but adds a separate key, tag storage and two primitive operations.
- **AEAD units (e.g. GCM):** one construction supplies confidentiality and
  authentication; address/device/generation are associated data. Requires
  a reviewed per-key unique-nonce allocator, stored nonce/version and tag,
  exhaustion checks, and fresh keys after reset. A possible direction is a
  device-wide monotonic encryption counter under a fresh per-generation key;
  increment for every unit encryption including zero initialization, never
  reset under the same key, and reject wrap. Freeze the exact encoding and
  usage bounds before implementation. VM rollback still defeats volatile
  freshness. See [SP 800-38D](https://csrc.nist.gov/pubs/sp/800/38/d/final).
- **Merkle tree:** can summarize tags and support verification with a trusted
  root, at the cost of tree storage, updates and recovery complexity. A root
  in replayable guest RAM does not prevent whole-device rollback. Unnecessary
  for the first small, serialized volatile device.

Direction: per-4096-byte authenticated units, with XTS plus an independent MAC
as the least disruptive candidate; compare it with AEAD before M5 is frozen.
An unkeyed checksum detects accidents, not malicious alteration. At 64 MiB,
16-byte tags alone cost 256 KiB; nonce/version metadata adds more. The
[dm-integrity design](https://docs.kernel.org/admin-guide/device-mapper/dm-integrity.html)
illustrates why integrity metadata and consistent data/tag updates are separate
storage responsibilities. Its on-disk journal is not needed for this volatile
project's current no-recovery scope.

Stage a complete ciphertext/tag update before committing under the sole worker.
No reader may see new ciphertext with an old tag. On reads use private output:
AEAD implementations may write data before reporting authentication failure.
Reject `-EBADMSG` without scattering that unit's bytes
([AEAD API](https://docs.kernel.org/crypto/api-aead.html)). Earlier verified units
of a multi-unit request may already have been copied; multi-unit atomicity is
not promised. Address binding prevents relocation; version binding alone does
not prevent replay if the attacker can replay the version and trusted state.

## 7. Future key lifecycle

These are design states only; **none exist as flags or ioctls in M3**. M3 is
not NO_KEY with an implicit plaintext exception. The encrypted implementation
must replace pass-through and start with admission closed in NO_KEY.

```text
NO_KEY -- load --> PREPARING -- setup + encrypted-zero initialization --> ACTIVE
                       | failure                                    | lock
                       v                                            v
                    NO_KEY                    ACTIVE <-- unlock -- LOCKED
ACTIVE / LOCKED -- destroy and wipe --> NO_KEY
any live state -- module teardown --> DYING --> freed
```

| State/operation | Future block behavior / key rule |
| --- | --- |
| NO_KEY | Reject READ/WRITE/FLUSH with I/O error; no plaintext fallback. |
| PREPARING | Reject new I/O; candidate key/transform private until all setup succeeds. |
| ACTIVE | Admit I/O under one immutable installed transform/generation. Crypto errors return I/O error, never a plaintext retry. |
| LOCKED | Reject new I/O. Keep the same transform/key resident for a simple reversible access gate. Lock is **not key eviction** or memory confidentiality against root. |
| Unlock | Privileged re-enable of the retained key, after checking state; takes no new key and cannot test a password. |
| Destroy | Gate/drain, erase key/transform and owned scratch/backing; enter NO_KEY. Irrecoverably discards this volatile device's contents. |
| Replacement | No in-place load over ACTIVE/LOCKED. Explicit destroy then load a fresh key; new encrypted-zero medium. This is destructive reset, not re-encryption. |
| REKEYING | Reserved concept only: a future live-rekey design would reject admission and drain first. No transition or command is offered; return unsupported. |
| DYING | Reject I/O/control, finish old users/work, wipe, free. No transition back. |

No externally visible KEY_LOADED state is needed: PREPARING covers uncommitted
setup; ACTIVE means the key and complete medium are ready. On load failure,
wipe input, candidate transform, scratch and partial backing, return the exact
control errno and remain NO_KEY. A failed load in ACTIVE/LOCKED is rejected
before touching the old key. A normal per-unit crypto failure leaves the
installed key in place, fails that request, and never commits that failed
unit's staged ciphertext. Earlier units of a multi-unit write may have changed.

Key bytes enter through a future privileged binary ioctl into a small private
kernel allocation; set the transform key, then explicitly wipe/free the input
copy on every exit. Retain only the transform's needed key schedule, outside
ordinary storage. The user-space caller must protect and clear its own copy.
Destroying driver state cannot erase copies the caller chose to retain.

## 8. Privileged control ABI decision

| Interface | Evaluation |
| --- | --- |
| Ioctl on `/dev/secureram0` | Viable, but mixes data access and administrative lifetime and requires opening the block device while it is locked/keyless. |
| Dedicated misc character device | Select **`/dev/secureramctl`**, one device for the current single disk. Separates administration from filesystem I/O and works before key activation. |
| sysfs | Suitable only for non-secret status/configuration later. Text attributes and their visibility/permissions are a poor key transport; no secret attributes. |
| configfs | Useful for user-created object hierarchies; unnecessary complexity for one fixed device and unsuitable as the initial secret transport. |

Future endpoint: mode 0600, owned by root; check `CAP_SYS_ADMIN` in the initial
user namespace on **every** operation (including query), not merely open.
Container-root capabilities alone must not authorize host-device changes.
Use `.owner = THIS_MODULE`; do not expose read/write/mmap access to keys or
backing. CLI and GUI invoke this ABI; neither knows kernel object layouts.

Planned commands, with numeric values deliberately unassigned until UAPI review:

| Command | Payload / result | Preconditions |
| --- | --- | --- |
| QUERY | ABI version, state, capacity, unit size, non-secret generation and supported features | Privileged; never returns keys, key hashes, addresses or data |
| LOAD_KEY | Fixed header plus inline 64-byte key, explicit length, flags/reserved zeros | NO_KEY, no block openers; validates then activates fresh encrypted-zero storage |
| LOCK | Fixed header, no secret | ACTIVE, no block openers; drain before reporting success |
| UNLOCK | Fixed header, no key | LOCKED, retained transform valid |
| DESTROY_KEY | Fixed header, explicit destructive-intent flag | No block openers; drain and wipe; idempotent in NO_KEY |

Use `_IOW`/`_IOR` as appropriate with fixed-width `__u32`/`__u64`, explicit
alignment/reserved fields and a version/size header, no native longs, bitfields
or pointers. Bounded inline key payload avoids nested pointer/compat hazards.
Never copy arbitrary user-supplied sizes into stack buffers. Copy once into
kernel-owned storage, validate all fields, and wipe even partial-copy failure.
Unknown commands return `-ENOTTY`; unsupported versions/flags/lengths `-EINVAL`;
copy faults `-EFAULT`; permission failures `-EPERM`; active users or invalid busy
transitions `-EBUSY`; allocation/provider errors propagate. Zero query output
and padding before `copy_to_user()`. Query can block behind a transition.

Before ABI freeze check ioctl-number collision guidance and native/compat
layouts, fuzz malformed inputs and confirm no query leaks. This follows
[kernel ioctl guidance](https://docs.kernel.org/driver-api/ioctl.html); it is a
proposal, not a shipped ABI or promise that numbers/layouts are stable today.

## 9. Concurrency and transition ownership

M3 changes no synchronization: pending-list spinlock, single ordered worker,
preallocated request nodes, 64 tags, 128 KiB maximum request, and no per-I/O
allocation. A single hardware queue alone does not serialize callers.

Future design uses a **control mutex plus an admission gate under pending_lock**.
The worker must never acquire the control mutex; it owns runtime crypto/store
access. The control mutex serializes administrators and future block
`.open`/`.release` accounting. Require zero block openers for load, lock,
unlock, destroy/reset; return busy if mounted or held open. This is deliberately
conservative: lock does not evict a live mounted filesystem or its caches.
Recheck the target block core's open/release balancing and lock order when
implementing those callbacks. A userspace mount/holder scan alone is not a
synchronization mechanism. New opens during transition must fail or wait under
the same mutex, and only ACTIVE allows data opens.

Transition protocol (future implementation):

1. Take control mutex, validate command/permissions/state and zero openers.
   No block core open/close/freeze call is made while holding this mutex.
2. Under pending_lock, close I/O admission. `queue_rq()` tests this gate under
   the same lock **before** starting or enqueueing a request. On denial return
   `BLK_STS_IOERR` without taking completion ownership; on acceptance start,
   append and schedule under that lock. No sleeping in dispatch.
3. Drop pending_lock. Drain the workqueue while the old transform/state remains
   alive. A request accepted before gate closure finishes under the old key;
   later requests are rejected. Worker waits for all crypto callbacks before
   returning, so draining covers scratch and provider request lifetime too.
4. With admission closed and worker idle, initialize/change/wipe security state.
   Keep the control mutex; the worker never needs it. No key change can overlap
   an accepted request. Flush alone without the gate would not be sufficient.
5. Publish new state; under pending_lock reopen admission only for ACTIVE.
   Release control mutex. Lock/destroy success is reported only after draining
   and the specified cleanup. A failed setup leaves admission closed.

Lock order is control mutex -> pending_lock. Dispatch/worker take pending_lock
alone; neither obtains the control mutex. No spinlock is held across copying,
crypto, user-copy, allocation, draining or any sleeping call. Crypto completion
callbacks only signal completion and must not wait for either driver lock.
This keeps transition latency bounded by accepted work/provider completion,
not by continuously arriving requests; a hung provider remains a system fault,
not permission to free an in-use transform.

For future shutdown, stop new control entry and mark DYING with admission
closed, then release control mutex before disk removal. Account for existing
control references and callbacks; misc deregistration alone does not invalidate
an open fd. Module ownership and per-operation lifetime must both be reviewed.
Keep workers live through `del_gendisk()`, drain/destroy them, release disk/tags,
then wipe/free security/store/device state. No forced unload. Never wait for
a worker while holding a lock it needs. These future controls are not added
in M3; current M2 teardown ordering is preserved exactly.

## 10. Sensitive-memory inventory and cleanup

| Location | Owner / future cleanup strategy |
| --- | --- |
| User key input and plaintext buffers | User application; privileged tool should avoid argv/environment, lock secret memory where practical, disable dumps and explicitly clear input. The driver cannot guarantee erasure of external copies. No tool is implemented now. |
| Kernel ioctl key copy | Control/security setup; small kmalloc allocation, clear with `kfree_sensitive()` on success and every failure including short copy. No raw key retention after setkey. |
| Transform and expanded key schedule | Security context; no pending crypto before `crypto_free_skcipher()`. Inspected API documents zeroization; review chosen provider's auxiliary/hardware state too. Never memset a live opaque transform. |
| Crypto request/private provider context | Security context; wait for final completion then `skcipher_request_free()`; the inspected header uses `kfree_sensitive()`. Reset/clear reused context according to provider/API requirements. |
| Plaintext unit staging | Security-owned, worker-used buffer; `memzero_explicit()` after each operation, errors, setup and before free. No plaintext retained between requests. |
| Ciphertext scratch, IV and future tag/nonce staging | Security-owned; clear after use and before free as hygiene. IVs/tags are not keys; a buffer may previously have held plaintext. Reinitialize per unit. |
| Backing allocation | Store owned through security; future teardown/reset explicitly clears the full recorded allocation before release (`memzero_explicit()` then `vfree()`, or `kvfree_sensitive(ptr, size)` where appropriate). M3 remains ordinary `vfree()`. |
| Request pages, filesystem/page cache | Block/filesystem ownership; plaintext is expected. Do not erase successful READ output or WRITE source owned by the caller. Future lock requires unmounted/closed users but cannot promise system-wide cache erasure. |
| Stack/registers, provider/DMA copies, dumps and VM snapshots | Minimize stack secrets and copying; audit provider teardown. Explicit clears cover named owned buffers, not all CPU or host copies. External restrictions are operational assumptions. |

The inspected `memzero_explicit()` includes a compiler barrier to prevent dead
store removal; ordinary end-of-life `memset()` is not sufficient for this intent.
Use frees matching the allocation type: `kfree_sensitive()` for kmalloc objects,
`kvfree_sensitive()` with the correct length for appropriate kmalloc/vmalloc
storage; do not pass vmalloc memory to `kfree_sensitive()`. See
[target memory helpers](https://github.com/torvalds/linux/blob/v7.0/mm/util.c)
and the installed `string.h`/`slab.h` declarations.

Acquire resources into an unpublished candidate; on any error unwind only
successful acquisitions in reverse order. Destroy crypto requests before their
transform after callbacks stop; clear scratch/key copies before freeing;
clear partial backing initialization and leave NO_KEY. Destructive replacement
uses the same drained teardown; no live rekey is specified. Module unload must
perform that cleanup while the data/state allocations still exist. Crashes and
power loss do not run these guarantees. M3 needs no generic wipe helper because
it introduces neither secrets nor temporary buffers, and does not claim erasure.

## 11. Acceptance and next milestone boundary

M3: compile with `W=1`, inspect code/checkpatch/symbols/docs, and prepare the
plaintext regression procedure. A wrapper is not proof of encryption or VM
behavior. [The M3 report](m3-report.md) records observed results separately.

Recommended M4, only after explicit authorization: implement real XTS and the
minimum fail-closed key lifecycle/control needed to exercise it, complete-unit
gather/scatter, encrypted-zero initialization and explicit cleanup. Tests must
include split-segment units, multiple offsets, repeated overwrites, no-key and
locked I/O, provider/setup failures, concurrent transitions, wrong setup, and
unload. XTS cannot detect a wrong key by itself; do not invent a success check
by observing plausible decrypted data. Keep authentication for a separately
specified milestone. **Stop after M3; no M4 execution is authorized here.**
