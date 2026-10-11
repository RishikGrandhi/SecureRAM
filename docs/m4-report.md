# M4 kernel crypto and encrypted storage report

Date: 2026-10-11 (Asia/Calcutta). Version 0.4.0, branch `m4-kernel-crypto`.
Implementation commit: `3e47300 M4: implement AES-XTS encryption and key control`.
**M4 VM runtime acceptance is complete.** Production and test-only verification
results are recorded separately below. This documentation update remains
uncommitted for review.

## Design reviewed before implementation

Start from clean `main` at `73fdcd3`, containing the M3 merge and runtime report.
Preserve M1-M3 history. M3's path is blk-mq -> pending list -> ordered worker ->
validated page fragments -> plaintext security wrapper -> checked RAM store.
Replace only the transfer boundary and add the M3-designed control lifecycle.

Use `xts(aes)` with 64 key bytes, 4096-byte units and a 16-byte input IV:
little-endian 64-bit (byte offset / 4096), followed by eight zero bytes.
Gather/scatter across page fragments using security-owned preallocated staging;
never submit local page mappings or vmalloc backing to the crypto provider.
Initialize every backing unit as encrypted zeros before ACTIVE. Destroy before
loading a replacement; no migration, plaintext fallback or online rekey.

Retain M3's NO_KEY, PREPARING, ACTIVE, LOCKED and DYING states. LOCKED retains
the transform; unlock is an administrative gate, not password verification.
Every control operation requires initial-user-namespace CAP_SYS_ADMIN.
Fixed-width, versioned ioctls live on root-only `/dev/secureramctl`.

Control mutex -> pending spinlock; close admission before draining the worker.
The worker never takes the control mutex. Block open/release accounting uses
the same mutex; all transitions require zero openers. Target v7.0 `bdev.c`
flushes and invalidates the final block mapping before calling driver release.
No block-core open/close/freeze operation is called under the control mutex.

Select providers excluding CRYPTO_ALG_ALLOCATES_MEMORY and
CRYPTO_ALG_KERN_DRIVER_ONLY. Check IV/alignment/single-page geometry, preallocate the
request, use kmalloc unit buffers, and use crypto_wait_req/crypto_req_done with
backlog support so both synchronous and asynchronous completion are handled.
This constrains allocation and external hardware assumptions; VM provider
execution was verified with provider `xts-aes-aesni-avx`.

An opt-in `M4_TEST=1` build compares actual backing bytes with plaintext and
ciphertext staging after real block writes, reporting no data or addresses.
The production build has no backing export or test hook. The test build's hooks
were executed in the VM and supplied the direct backing-store evidence described
under runtime acceptance; source review or compilation alone would not do so.

API references inspected: installed Ubuntu 7.0.0-38 headers, official
[skcipher API](https://docs.kernel.org/crypto/api-skcipher.html),
[completion example](https://docs.kernel.org/crypto/api-samples.html),
[ioctl guidance](https://docs.kernel.org/driver-api/ioctl.html),
[ioctl numbering](https://docs.kernel.org/userspace-api/ioctl/ioctl-number.html),
[v7.0 block open/release](https://github.com/torvalds/linux/blob/v7.0/block/bdev.c),
[provider flags](https://github.com/torvalds/linux/blob/v7.0/include/linux/crypto.h),
[XTS implementation](https://github.com/torvalds/linux/blob/v7.0/crypto/xts.c),
and [transform destruction](https://github.com/torvalds/linux/blob/v7.0/crypto/api.c).

## Objective and files changed

Replace the M3 plaintext bypass with real kernel XTS, fail-closed key state,
minimum privileged control and encrypted RAM backing. Preserve the established
block queue, capacity, operation limits and ownership discipline. No integrity,
online rekey, KDF, polished CLI, GUI, statistics, benchmarking or persistence.

| Files | M4 changes |
| --- | --- |
| `src/secureram_security.c`, `include/secureram_security.h` | Crypto transform/request, buffers, IV, state/generation, key loading/destruction, unit encryption/decryption, encrypted-zero setup, explicit cleanup. |
| `src/secureram_block.c`, `include/secureram_block.h` | Whole-unit fragment cursor, admission gate, mutex/opener protection, serialized control transitions, control lifetime and test-only cursor verification. |
| `src/secureram_control.c`, `include/secureram_control.h` | New misc adapter with safe copy, strict validation, per-ioctl privilege checks and compat support. |
| `include/uapi/secureram.h` | New versioned fixed-width ioctl ABI. |
| `src/secureram_store.c`, `include/secureram_store.h` | Explicit backing reset/clear before release. |
| `src/secureram_main.c`, `include/secureram_config.h`, `Kbuild` | Version/logs, control object linkage and opt-in test variant. |
| `tests/m4-control.c`, `tests/m4-raw-io.py` | New narrow VM control/negative tests and state-aware raw tests. |
| `README.md`, `docs/architecture.md`, `docs/development.md`, `tests/README.md`, `tools/README.md` | Current behavior, build/use instructions and evidence limits. |
| `docs/m4-testing.md`, `docs/m4-report.md` | New safe acceptance procedure and this design/evidence/viva report. |

M1-M3 reports/design/test procedures and M2's raw test remain unchanged. The
new raw test imports the reusable I/O routines without widening the old test's
plaintext-only version guard. No history, commit or remote is changed.

## Crypto API and data flow

The security context owns a `crypto_skcipher` allocated for `xts(aes)`, a reusable
`skcipher_request`, two preallocated 4096-byte kmalloc buffers and a 16-byte
aligned IV. The key is exactly 64 bytes, data key then tweak key, each 256 bits.
Both a constant-time unequal-half check and FORBID_WEAK_KEYS enforce the weak-key
rule. The algorithm must report a 16-byte IV/AES block and alignmask at most 15.
No AES code, userspace crypto, cipher selection, password derivation or fallback
is implemented by SecureRAM.

The mask excludes providers marked ALLOCATES_MEMORY or KERN_DRIVER_ONLY.
Each power-of-two kmalloc unit is 4096-aligned and fits in one page (the build
requires PAGE_SIZE >= 4096), so no crypto walk chunk crosses a page or SG
boundary. The IV is 16-aligned. These meet the target header's nonallocating
request constraints. Setup allocations can sleep before admission. The selected
provider name is logged as non-secret metadata; its runtime availability and
progress remain to be observed in the VM.

Each crypt operation builds source/destination scatterlists on staging, sets
MAY_SLEEP | MAY_BACKLOG and crypto_req_done, submits encrypt or decrypt, then
uses crypto_wait_req for final synchronous/async status (including EINPROGRESS
and EBUSY backlog). Local SG/wait objects remain alive until completion. It then
clears the full request/private context with skcipher_request_zero and reattaches
the transform for reuse; IV bytes are cleared. No local request-page mapping
survives into crypto. Transform keys are immutable while I/O can run.

The IV is rebuilt for every unit because providers may modify it. Byte offset
`b` maps to unit `b/4096`; put_unaligned_le64 writes this index into IV bytes
0-7, and bytes 8-15 are zero. Offsets 0, 4096 and 8192 map to 0, 1 and 2. XTS
derives its tweak internally. This is deterministic storage addressing, not
random per-write nonces. Rewrites can reveal equality at one address over time.

WRITE first validates the entire request, then gathers fragments into `plain`.
When exactly 4096 bytes are collected, it encrypts into `cipher` and copies
that ciphertext to the checked store. Both buffers are cleared before the next
unit. READ copies a complete stored unit into `cipher`, decrypts into `plain`,
and only on success scatters it into request pages, clearing both staging
buffers by unit completion. Request fragments can split or cross crypto units;
the cursor's unit offset/used count persists independently of bvec boundaries.
Source WRITE pages remain plaintext and are never encrypted in place.

## Key lifecycle, reset and cleanup

States implement M3 unchanged: NO_KEY (0), PREPARING (1), ACTIVE (2), LOCKED (3)
and DYING (4). PREPARING/DYING correspond to actual setup/teardown phases; no
cosmetic loaded/rekey/error state exists. Query serializes behind preparation.
Initial NO_KEY rejects read/write opens with ENOKEY; admission also rejects
dispatched requests with BLK_STS_IOERR. The worker defensively checks ACTIVE
before crypto. There is no path to the old plaintext copy behavior.

LOAD_KEY is permitted only in NO_KEY with zero block openers. The ioctl adapter
allocates a zeroed 88-byte input, copies once from userspace, validates its fixed
header and exact key length, then requests a serialized transition. The security
layer rejects equal halves, allocates/configures the transform, and clears the
raw input immediately after setkey. It allocates the request and encrypts zero
plaintext separately for every backing address. Only complete success increments
generation and publishes ACTIVE. Failure frees crypto, clears partial backing/
scratch and stays NO_KEY. The adapter sensitive-frees input on every exit,
including partial user-copy failure and rejection before setup. No duplicate
raw key is retained alongside the provider's necessary key schedule.

LOCK requires ACTIVE and retains its transform. UNLOCK requires LOCKED and
restores admission without accepting a password or new key. All transitions
require zero openers, including unlock. DESTROY_KEY requires explicit destructive
intent, drains, frees the request before the transform, clears buffers/backing
and enters NO_KEY. It is idempotent there. Replacement while ACTIVE/LOCKED is
EBUSY: destroy then install a fresh independently generated key. This resets
the whole logical medium, never migrates/reinterprets existing data. Generation
wrap is rejected; the counter is informational and is not freshness protection.

Cleanup uses memzero_explicit, kfree_sensitive, skcipher_request_zero/free and
crypto_free_skcipher, plus explicit backing clearing before vfree. Driver-owned
request context and staging are cleared between units. No opaque live transform
is manually overwritten. The documented Crypto API frees its key context; the
provider/kernel remain trusted. These primitives do not prove physical erasure
of caller buffers, registers, external copies, caches, snapshots or crash dumps.

## Control ABI and privilege model

The misc device is `/dev/secureramctl`, separate from data, mode 0600 with
THIS_MODULE ownership. Every ioctl checks ns_capable(init_user_ns, CAP_SYS_ADMIN),
including query on an inherited fd. Container-root capability in a child user
namespace is insufficient. No read/write/mmap/key-export operations exist.

| Command | Encoding/payload | Preconditions/result |
| --- | --- | --- |
| QUERY | `_IOR(0xb7, 0, status)`; 48 bytes, output-only | ABI/version size, state, capacity, unit, generation, features 3; all padding/reserved zero. |
| LOAD_KEY | `_IOW(0xb7, 1, key)`; 88 bytes | 16-byte header, u32 length=64, u32 reserved=0, inline 64 bytes; NO_KEY only. |
| LOCK | `_IOW(0xb7, 2, header)`; 16 bytes | ACTIVE -> LOCKED. |
| UNLOCK | `_IOW(0xb7, 3, header)`; 16 bytes | LOCKED -> ACTIVE; retained key. |
| DESTROY_KEY | `_IOW(0xb7, 4, header)`; 16 bytes | flags exactly SECURERAM_F_DESTROY (1); discard key/medium. |

Headers contain version=1, exact structure size, flags and zero reserved. All
other input flags must be zero. Fields are u32/u8 or explicitly aligned u64,
with no pointers/native longs/bitfields; native and compat command layouts are
intended identical. compat_ptr_ioctl converts only the top-level user pointer.
The project-local magic is **not an upstream reservation**; exact command
matching on this endpoint rejects other commands/sizes. A future incompatible
ABI needs a new command/version, not reinterpretation of v1.

Unknown command: ENOTTY. Wrong size/version/flags/reserved/key length/equal
halves: EINVAL. User-copy fault: EFAULT. Privilege: EPERM. Open users or invalid
busy transition: EBUSY. Allocation/provider errors propagate; dying change:
ENODEV. Queries expose no key, hash, backing data or kernel address.

## Concurrency and ownership audit

Control mutex -> pending spinlock. Core open_mutex precedes the control mutex
in block callbacks; no control path acquires the core mutex in reverse order.
The control mutex serializes administrators with every successful open/release
count. The inspected core flushes/invalidates the final mapping before release,
so zero openers also excludes that final close's writeback. A mounted filesystem
retains an opener; key changes under it receive EBUSY. Operationally unmount,
close every block fd and then change keys. Page-cache copies elsewhere are not
revoked by a lock or key removal.

The pending spinlock protects both acceptance and list insertion. Admission
closes before flush_workqueue; old requests complete under old state, later ones
are rejected without ownership. No worker takes the control mutex. No spinlock
spans crypto, copy, allocation or waiting. State/transform mutation occurs only
after drain, and publication through the admission lock precedes new dispatch.
One hardware queue alone is not the synchronization argument.

| Resource | Acquisition / partial failure / normal release |
| --- | --- |
| Device, mutex and pending/list/work state | kzalloc and init before publication; free outer device last. Locks have no dynamic destructor. |
| Backing and two unit buffers | Init before work/disk; partial buffer allocation sensitive-frees both safely and clears/frees store. Teardown after all work. |
| Workqueue, tags, disk-owned queue | Preserve M2 order; never-published disk put, then tags/worker; published disk removed while worker is live. |
| Control misc device | Register after disk; register failure removes disk before unwind. Normal unload deregisters before disk destruction. |
| Transform and skcipher request | Allocate only during gated load; on failure clear/free request before transform. No outstanding callback survives drain. |
| Kernel key copy | Small zeroed allocation, copied once, sensitive-free on all branches; no dynamic key copy retained. |
| Test-only buffers | Temporary cursor-check buffers sensitive-freed on success/failure; failed setup clears partial medium before returning. |

Normal unload requires both endpoint users to release module references. It
deregisters control, closes/drains admission, sets DYING, releases the mutex,
removes disk, destroys work, puts disk/frees tags, clears/frees security and outer
device. It never relies on misc_deregister alone to invalidate live file handles.
No source references discarded init code persist. No forced unload is supported.

## Failure behavior and guarantees

Full request prevalidation precedes any WRITE. A crypto error fails the request,
does not commit the failing unit's staging, and leaves the active key in place.
A failed READ unit is cleared privately and never scattered. Earlier units can
already have been written/read: whole-request atomicity and rollback are not
promised. Store bounds are rechecked. The backing-write failure cannot expose a
plaintext fallback. A theoretical test-only comparison failure reports EIO after
the committed unit; this debug path is absent from production.

Implemented intent: all successful data writes store XTS ciphertext, logical
reads return decrypted data, keyless/locked operation fails closed, transitions
cannot mix generations, and orderly cleanup explicitly clears named owned
buffers. **Runtime evidence is still required before calling these M4 guarantees
accepted.** The protection target is backing-only disclosure without keys or
plaintext elsewhere, as narrowed in M3's threat model.

No integrity/authentication, tamper or wrong-key detection, replay/rollback
protection, root/kernel/hypervisor defense, whole-memory physical/cold-boot
resistance, persistence after reboot, crash-safe cleanup, password/KDF security,
multi-unit atomicity or denial-of-service guarantee. Encryption alone cannot
establish any of these properties. Ordinary authorized reads intentionally
return plaintext; filesystem/application caches remain outside the boundary.

## Build and static verification

Local environment: Windows host with Ubuntu WSL2 running
6.18.33.2-microsoft-standard-WSL2 and GCC 15.2.0. Compile-only target is the
existing prepared Ubuntu 7.0.0-38-generic headers, under
`/home/rishik_grandhi/.cache/secureram-m2-20261010/root/usr/src/`.
No packages, VM settings, kernel configuration or host services were changed.
Exact commands are in [development](development.md). Build logs are local ignored
`build-m4-production.log` and `build-m4-test.log` files.

Final checks on 2026-10-11:

| Check | Observed result |
| --- | --- |
| Target preflight | PASS: prepared config/generated headers/Module.symvers present; running WSL target mismatch explicitly identified. |
| Clean production `make CC=gcc W=1` with explicit KDIR | PASS: five source objects, MODPOST and module link, no driver warnings/errors. |
| Clean `M4_TEST=1` variant with same settings | PASS: five source objects, MODPOST and link; test comparison/cursor/tweak strings present. Runtime execution is recorded separately below. |
| Strict target checkpatch | PASS: zero errors, warnings or checks for five kernel C files, six headers including UAPI, and the C test helper (12 files). |
| Userspace helper build | PASS: C11, O2, Wall/Wextra/Werror/Wconversion against shared UAPI. No device operation executed. |
| Native/compat ABI compile checks | PASS: x86-64 and `gcc -m32` i386 object builds assert header/key/status sizes 16/88/48, field offsets and all five ioctl numbers. Compat runtime is untested. |
| Module metadata | PASS: version 0.4.0, GPL, AES-256-XTS/no-authentication description, uint capacity, x86-64 ELF and vermagic 7.0.0-38-generic. |
| Symbols and test separation | PASS: crypto calls confined to security object; no block-to-store imports; all 58 module imports found in target Module.symvers; production module has no M4 test strings. |
| Shell/Python syntax | PASS: environment checker and both raw-test scripts; this local check did not access a device. |
| Documentation | PASS: 15 Markdown files, 50 local links/anchors and 33 shell snippets parsed without execution. Historical development anchors preserved. |
| Git/text review | PASS before the implementation commit: diff whitespace, UTF-8/LF/newlines, no staged changes, M1-M3 historical documentation and original M2 test unchanged. The reviewed implementation was then committed as `3e47300`. |

Local `.cache/validate_m4.py` performs the documentation/text/history/symbol
checks; `.cache/m4-abi.c` supplies compile-only ABI assertions. Both are ignored
validation scratch. Manual source/diff review traced full-unit boundaries,
admission/completion, open/close serialization, copied-key failures, allocation
unwind and normal unload. That review does not establish runtime race freedom.

Environmental diagnostics retained in both build logs: target GCC 13.3.0 versus
local GCC 15.2.0, target pahole 125 versus missing local pahole (reported 0), and
BTF generation skipped because headers lack vmlinux. Rebuild in the VM using its
appropriate compiler before loading. No source warning was dismissed as an
environmental warning. Generated module artifacts were cleaned after inspection.

Initial integration builds found unavailable helper names (`skcipher_request_ctx`,
`crypto_skcipher_walksize`, `no_llseek`). These were corrected to the target's
public request-zero helper, the single-page staging constraint and
nonseekable_open. Failed attempts were not counted as successful verification.

## VM runtime acceptance result

Status: **PASS**, manually verified by the user in an Ubuntu 24.04.5 LTS
VirtualBox VM running Linux `7.0.0-38-generic`. The tested implementation was
version 0.4.0 at commit `3e47300`. `/dev/secureram0` and the separate privileged
`/dev/secureramctl` appeared root-owned with mode 0600. The default device was
67108864 bytes (64 MiB) with 4096-byte logical/crypto units.

### Production build and initial fail-closed state

The VM's clean production `make W=1` build after `make clean` succeeded. The
kernel reported compiler name `x86_64-linux-gnu-gcc-13` and the build used
`gcc-13`; both were GCC 13.3.0. This naming/string difference was the only
compiler diagnostic. The pahole/version and skipped-BTF messages were
environmental; BTF was skipped because `vmlinux` was unavailable. There were no
driver-source warnings or MODPOST errors. The production module was confirmed
to contain no test hook strings: `strings secureram.ko | grep -F 'M4 test:'`
produced no output.

The first privileged query returned exactly:

```text
ABI=1 state=0 bytes=67108864 unit=4096 generation=0 features=3
```

Raw read and write opens both failed closed with ENOKEY. The negative helper
passed malformed ABI, invalid-length/equal-half key, user-copy-fault and
passed-file-descriptor privilege checks; state remained NO_KEY at generation 0.
A generated 64-byte test key then loaded successfully, selecting kernel provider
`xts-aes-aesni-avx`, and query returned ACTIVE:

```text
ABI=1 state=2 bytes=67108864 unit=4096 generation=1 features=3
```

### Production encrypted I/O

The complete active raw-I/O regression passed:

- Every key transition was rejected with EBUSY while the block device was open.
- The full 64 MiB logical-zero scan passed after key activation.
- Direct segmented temporary-file round trip and first, nonzero, middle and
  final logical-block tests passed.
- Neighbor isolation, four concurrent disjoint I/O streams, end-of-device
  behavior and delivered flush handling passed.
- A 1 MiB random direct-I/O readback had the same SHA-256 and passed `cmp`.

This demonstrates correct plaintext behavior through the encrypted block path.
The separate test build below supplies direct evidence about backing bytes.

### Direct ciphertext and unit-boundary evidence

The production module was destroyed and unloaded before a clean
`make W=1 M4_TEST=1` build. That build succeeded and loaded. Its internal checks
ran and emitted:

```text
M4 test: equal zero units at indices 0/1 have different ciphertext
M4 test: 512/4096/3584-byte split-unit gather/scatter PASS
M4 test: real WRITE backing equals ciphertext and differs from plaintext
```

The real-WRITE hook compares actual private store bytes against both the
ciphertext and plaintext staging buffers while access is serialized. Together
with successful normal plaintext readback, this is direct internal evidence
that the SecureRAM backing allocation stores AES-XTS ciphertext rather than the
written plaintext, including across deliberately split/cross-unit fragments.
The hooks export no key/data/hash/address and are absent from production. They
are project acceptance evidence, not independent certification of AES and not
evidence of authentication or integrity.

### Key states, reset and filesystem behavior

Runtime transitions matched the documented state machine:

| Check | Observed result |
| --- | --- |
| Replacement in ACTIVE | Rejected with EBUSY. |
| Lock | State 2 -> 3; generation stayed 1. |
| I/O in LOCKED | Raw opens failed closed with ENOKEY. |
| Load in LOCKED | Rejected with EBUSY. |
| Unlock | State 3 -> 2; generation stayed 1. |
| Lock retention | Data read before lock and after lock/unlock compared identical. |
| Destroy from ACTIVE | Returned to state 0, generation 1; I/O again failed ENOKEY. |
| Destroy in NO_KEY | Succeeded idempotently. |
| Fresh key | Entered state 2, generation 2; full initial-zero scan passed. |

The generation-2 zero scan confirms destructive replacement presents a fresh
logical medium rather than interpreting earlier contents under the new key.

`mkfs.ext4 -E nodiscard /dev/secureram0` succeeded. The filesystem mounted;
normal file write/read succeeded; a lock attempt while mounted returned EBUSY;
the filesystem remained readable; and unmount, remount, read and final clean
unmount succeeded. This confirms opener protection prevents a key transition
under the mounted filesystem in the exercised case.

After the test build, destroy returned state 0 at generation 2, denied I/O
passed, repeated destroy succeeded, and `rmmod` removed both device nodes.

### Final production regression and kernel health

A final clean production rebuild passed and again contained no `M4 test:`
strings. A fresh insertion began at NO_KEY generation 0; a new key reached
ACTIVE generation 1. The entire active raw-I/O suite passed again. Its final
1 MiB SHA-256 values were identical, and `cmp` passed:

```text
input    6ec3e5d3c193847e912fcb9f381de3a82a8b5a958905845b6345bcb5912cbb84
readback 6ec3e5d3c193847e912fcb9f381de3a82a8b5a958905845b6345bcb5912cbb84
```

The final production ext4 write/read passed. After clean unmount and destroy,
query returned NO_KEY generation 1; unload succeeded and both device nodes
disappeared. Fresh logs included the selected XTS provider, successful test-only
ciphertext checks, ext4 mount/unmount cycles and:

```text
SecureRAM: M4 unloaded; devices removed and owned sensitive memory cleared
```

The final safety search for `Oops`, `BUG:`, `kernel panic`, `general protection
fault`, `use-after-free` and `KASAN` produced no output. Earlier M3 VirtualBox
workqueue latency messages remain documented in the M3 report as non-fatal
performance observations; the supplied M4 evidence reports no new matching
correctness failure.

### Evidence limits still applicable

Provider-unavailability/allocation/setkey/crypto-operation fault injection,
native/compat runtime ioctl coverage, broad open-transition race campaigns and
diagnostic lockdep/KASAN/kmemleak execution were not reported. The successful
acceptance run must not be extended to those unobserved cases. Physical erasure
of external copies is outside scope rather than an uncompleted test.

Within the documented threat model, M4 now has runtime evidence for AES-256-XTS
confidentiality of the RAM backing store. It still provides no cryptographic
integrity, authentication, tamper/wrong-key/replay detection or protection from
a malicious root, kernel or hypervisor. It is not authenticated encryption.

## Viva concepts

- Explain XTS's two AES keys, the 64-byte combined length, little-endian unit
  numbering and why address inputs are not authentication tags or GCM nonces.
- Trace plaintext WRITE -> full-unit gather -> encryption -> ciphertext RAM,
  and ciphertext READ -> private decrypt -> full-unit scatter -> block completion.
- Explain why zero-filled allocation is not encrypted zeros, and why loading
  a replacement destroys the old logical medium instead of decrypting old bytes.
- Contrast lock's retained transform with destroy's removal; identify each
  explicit clearing primitive and the limits of owned-memory cleanup.
- Explain a request, scatterlist, local page map, kmalloc/vmalloc difference,
  completion callback and why crypto runs in a sleepable bounded worker.
- Trace gate closure/drain/open counting, lock order and final-close flushing;
  explain how both module owners prevent unload during active use.
- Explain fixed-width UAPI, user-copy faults, errno, initial-namespace capability
  checks and why a root-opened fd must not bypass per-operation authorization.
- Distinguish compile/static evidence, actual backing comparisons, normal
  readback, confidentiality, integrity, freshness and persistence.

## Recommended M5 direction

Review authenticated 4096-byte units, independently keyed XTS-plus-MAC versus
AEAD, metadata/address/generation binding, nonce/freshness rules and atomic
ciphertext/metadata updates. Verify before releasing plaintext; volatile
metadata cannot by itself defeat full VM rollback. No M5 implementation is
included. Stop after M4 and leave this candidate uncommitted for review.
