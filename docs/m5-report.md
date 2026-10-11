# M5 integrity protection and tamper detection report

Date: 2026-10-11 (Asia/Calcutta). Version 0.5.0.
Branch: `m5-integrity-tamper-detection`, based on clean `main` at `5eb07d5`.
M1-M5 runtime acceptance is complete. **M5 automated VM acceptance passed** on
commit `5fabe544a3969732647e7d9962beed974b667901` in Ubuntu 24.04.5 LTS,
Linux 7.0.0-38-generic. The complete evidence and scope are recorded below.

## Design recorded before implementation

Preserve M4's ordered worker, segmented whole-unit cursor, two staging buffers,
XTS key interface, opener protection and gate/drain control synchronization.
Use Encrypt-then-MAC with AES-256-XTS and full HMAC-SHA-256 tags in a separate
store-owned allocation. Stage encryption and MAC before a checked, non-failing
pair of copies under the existing sole-worker/control-after-drain exclusion.
READ verifies ciphertext before decrypting or scattering any failing unit.
There is no partial-unit read-modify-write path or whole-request transaction.

Authenticated input is exactly 4128 bytes:
`ASCII("SecureRAM-M5-MAC") || LE64(generation) || LE64(unit_index) || ciphertext[4096]`.
The domain is exactly 16 bytes without a NUL; numbers are fixed 8-byte unsigned
little-endian encodings, never a C struct. Tags are all 32 bytes, untruncated.
The generation used for initialization is the prospective successful generation;
publish it only after the entire zero medium and tags are ready.

Keep the original 64-byte input as the XTS key. Derive the distinct 32-byte MAC
key with RFC 5869 HKDF-SHA-256: IKM is that input, salt is the exact ASCII bytes
`SecureRAM-M5-HKDF-SHA256`, info is `SecureRAM-M5-integrity`, both without NUL.
Use the exported kernel `hkdf_extract` and `hkdf_expand` helpers, a temporary
HMAC transform, and a separate resident HMAC transform. Wipe PRK/output/input
and free the temporary transform on every exit. This is key separation for
high-entropy input, not a password stretching interface.

An HMAC mismatch publishes INTEGRITY_FAILED (4) using WRITE_ONCE. Readers of
state outside the sole worker use READ_ONCE. The worker closes admission under
the existing pending spinlock before completing the failing request; already
queued requests check ACTIVE before any operation, including FLUSH. The worker
never takes control_lock. Control closes/drains first, then validates transitions
so it cannot overwrite a failure with LOCKED or ACTIVE. QUERY remains available;
DESTROY remains available after all block users close, including in the failed
state. LOCK/UNLOCK/LOAD cannot clear the latch. Recovery is destroy -> NO_KEY ->
fresh key and authenticated zero medium. DYING moves from 4 to 5; it was never
observable through a live control handle. Existing ioctl layouts stay unchanged.

Allocate tags at store initialization, before disk publication: size/4096*32,
512 KiB at 64 MiB (16384 units), 0.78125% of advertised capacity. Allocate the
resident shash descriptor once per activation. No per-request allocation.
Clear tags, backing, staging and transforms on failed activation/destroy/unload.
LOCK retains both transforms, ciphertext and tags, with unchanged generation.

Test-only corruption uses a separate guarded UAPI header and ioctl case compiled
only with M5_TEST=1: flip one bounded ciphertext/tag byte or copy a complete pair
to a different unit. Require host CAP_SYS_ADMIN, ACTIVE, zero block openers,
gate/drain, and validated indices/fields. No arbitrary memory or data export.
Production rejects the test command as ENOTTY and contains no tamper handler.

## API evidence consulted

Local WSL runs `6.18.33.2-microsoft-standard-WSL2`, without matching headers.
Compile-only headers: prepared Ubuntu `7.0.0-38-generic` in the existing M2
cache. Inspected `crypto/hash.h`, `crypto/hkdf.h`, `crypto/algapi.h`,
`linux/crypto.h`, config and Module.symvers. HKDF is configured as a module;
the VM must load `hkdf` before inserting the external driver.

Official references: [digest API](https://docs.kernel.org/crypto/api-digest.html),
[RFC 5869](https://www.rfc-editor.org/rfc/rfc5869),
[Linux v7.0 HKDF](https://github.com/torvalds/linux/blob/v7.0/crypto/hkdf.c),
[HMAC](https://github.com/torvalds/linux/blob/v7.0/crypto/hmac.c), and
[transform destruction](https://github.com/torvalds/linux/blob/v7.0/crypto/api.c).

## Exact format, keys and memory

| MAC input byte offsets | Encoding |
| --- | --- |
| 0-15 | `53 65 63 75 72 65 52 41 4d 2d 4d 35 2d 4d 41 43` (fixed domain) |
| 16-23 | Unsigned LE64 successful key generation |
| 24-31 | Unsigned LE64 byte offset divided by 4096 |
| 32-4127 | Complete 4096-byte ciphertext unit, in store byte order |

Tag = HMAC-SHA-256(Kmac, input), all 256 bits. XTS IV is unchanged:
LE64(unit_index) followed by eight zero bytes. Neither input uses host-endian
layout, textual numbers, implicit padding or variable-length fields. Tag `u`
starts at `tags + u*32`; ciphertext starts at `data + u*4096`.

For the 64-byte secret input K supplied through the public ABI:

```text
Kxts = K
PRK  = HMAC-SHA-256(ASCII("SecureRAM-M5-HKDF-SHA256"), K)
Kmac = HMAC-SHA-256(PRK, ASCII("SecureRAM-M5-integrity") || 0x01)
```

This is full RFC 5869 Extract then one Expand block (L=32). Salt is 24 bytes;
info is 22 bytes, neither includes NUL. XTS uses two 256-bit halves; MAC uses
a separately derived 256-bit value, never either half or K directly. The
domain-separated HKDF output provides separation from XTS key material under
the standard HMAC/HKDF assumptions; the keys remain related through their
common secret input. Exposure of K compromises both. Only high-entropy input
is supported; a fixed public salt does not stretch passwords. Fresh independent
input per load/device remains the provisioning rule. Generation binding is
in the MAC message, not an extra secret or a persistent counter.

The temporary KDF transform holds PRK only during preparation and is freed with
crypto_free_shash. Stack PRK and derived key use memzero_explicit on every exit.
After setkey, only the resident transform's needed keyed state remains. The
copied 64-byte input is cleared after both setups (or on failure) and the ioctl
adapter sensitive-frees it even if rejected before setup. The reusable shash
descriptor is zeroed after every calculation and its transform pointer restored.
Destroy frees that descriptor before the resident transform. The Crypto API's
transform destructor clears its allocation; HMAC owns/frees its child transform.
The kernel/provider remain trusted. No keys, tags or data contents are logged.

| Capacity | Units | Exact tag payload |
| --- | ---: | ---: |
| 1 MiB | 256 | 8192 bytes (8 KiB) |
| 64 MiB | 16384 | 524288 bytes (512 KiB) |
| 256 MiB | 65536 | 2097152 bytes (2 MiB) |

Tag payload is always capacity/128, or 0.78125%. The default backing plus tag
payload is 67633152 bytes (64.5 MiB). This excludes vmalloc mapping metadata,
allocator rounding, the existing 8192-byte staging, 64 bytes of tag scratch,
IV, queue objects, shash descriptor and provider-dependent key schedules.
The 32-byte encoded prefix is bounded stack scratch. No new per-request
allocation; transforms/descriptor allocate only with admission closed.

## Data flow and synchronization audit

WRITE validates the complete request, gathers one whole plaintext unit,
encrypts to private staging, calculates its tag, and calls store_commit_unit.
The store validates ciphertext and tag ranges before either copy; thereafter
both copies are non-failing. Sole-worker exclusion prevents a reader seeing a
half-committed pair. This is concurrency consistency, not CPU-wide atomicity
against arbitrary kernel memory readers or crash persistence. A crypto/store
validation error before commit leaves that unit unchanged; earlier request
units may have committed. Full-unit overwrites do not read old data and can
replace an as-yet-undetected damaged unit. Detection occurs on authenticated
reads, not as a background scrub or audit of every overwritten byte.

READ copies ciphertext and stored tag, computes/compares with crypto_memneq,
and only after success calls XTS decrypt and returns plaintext to the unchanged
block fragment cursor. A mismatch returns -EBADMSG internally, mapped to
BLK_STS_IOERR / userspace EIO. The failed unit is never scattered; plaintext,
ciphertext, IV and both tag scratch buffers are explicitly cleared. Earlier
verified units of a multi-unit read may already have been copied. Other crypto
errors fail that I/O and clear staging but do not assert an HMAC mismatch.

Before M5, only gated control callers mutated state. Now the ordered worker
may publish the one-way failure latch. All state accesses use READ_ONCE or
WRITE_ONCE; state is a naturally sized u32. Generation and transform mutation
remain under control_lock after draining. QUERY holds that mutex, reading one
state snapshot without draining live I/O. A concurrent query/open can linearize
before the latch; a newly opened descriptor still cannot bypass worker checks.
No state read authorizes unsynchronized crypto access.

The worker closes accepting under pending_lock before completing the failed
request. Any dispatch racing between latch publication and gate closure may
have been accepted, but process_request checks ACTIVE and completes it with
I/O error. Remaining accepted requests each complete exactly once. FLUSH also
checks state (the block core can elide a flush on a non-caching device).
No worker waits for control_lock, so a control caller can drain safely while
holding it. No spinlock spans HMAC, XTS, memcpy of a unit, or a wait.

Lock order remains core open_mutex -> control_lock -> pending_lock. Last close
flushes/invalidates before decrementing openers in the driver. Administrative
state changes and test mutation require zero openers; the block device cannot
be mounted. The integrity-failure transition occurs in the worker during I/O.
Control validates legal state after drain, preserving a failure observed there.
No mutex is added to the storage path and no second storage path is exposed.

## State machine and control ABI delta

```text
NO_KEY (0) -> PREPARING (1) -> ACTIVE (2) <-> LOCKED (3)
                 |               |
                 |         HMAC mismatch
                 |               v
                 |        INTEGRITY_FAILED (4)
                 |               |
                 +---- failure   +---- DESTROY ----> NO_KEY
ACTIVE / LOCKED -------- DESTROY -------------------> NO_KEY
unload -> internal DYING (5) -> cleared/freed
```

All five existing ioctl numbers and 16/88/48-byte header/key/status layouts
remain unchanged at ABI version 1. QUERY features is now 7: XTS=1, LOCK=2,
INTEGRITY=4. Query exposes no tags, key material, key fingerprints or addresses.
The M4 header assigned DYING=4, but no live descriptor could observe teardown:
open control files pin the module, and unregister/drain happens before DYING.
M5 assigns observable INTEGRITY_FAILED=4 and moves this private lifecycle marker
to 5. No previously observable state value or input contract changes. An old
client that labels numeric 4 as DYING can mislabel this newly observable failure;
clients need the M5 header/INTEGRITY feature bit to interpret it correctly.
This preserves the existing wire layout and operations, not universal semantic
compatibility with clients that assume the M4 state set is exhaustive.

| Operation/state | Result |
| --- | --- |
| Open in NO_KEY/LOCKED | ENOKEY, unchanged from M4 |
| Open in INTEGRITY_FAILED | EIO |
| Data on existing fd after latch | EIO, including valid undamaged units |
| QUERY after latch | Success, state 4, same generation |
| LOCK/UNLOCK/LOAD after latch | EBUSY; cannot resume access |
| DESTROY with open block users, including failed state | EBUSY; close/unmount first |
| DESTROY with zero openers | Wipe both key states, tags, backing/staging; NO_KEY |
| Repeated DESTROY in NO_KEY | Success, generation unchanged |
| Successful subsequent LOAD | Generation +1, full authenticated zero medium |
| Failed activation | NO_KEY, old generation unchanged; partial state wiped |

Generation advances only for successful key installation, not lock/unlock,
destruction, failed I/O or failed installation. U64_MAX cannot wrap. It resets
to zero on module reload. No persistent anti-replay claim follows from it.
PREPARING is hidden behind the control mutex. Test-only M4 cursor checks run
before admission, and an unsuccessful check rolls back the unpublished load.

The test-only command is `_IOW(0xb7,0x70,40-byte payload)` = `0x4028b770`.
Its separate guarded header is `include/uapi/secureram_test.h`: existing header
at offset 0, aligned u64 unit at 16, aligned u64 other_unit at 24, u32 operation
at 32 and u32 byte_offset at 36. Header requires version=1, size=40 and zero
flags/reserved. Operation 1 flips bit 0 of a ciphertext byte (offset 0..4095);
2 flips bit 0 of a tag byte (0..31); both require other_unit=0. Operation 3 copies
the full ciphertext/tag pair from unit to a different in-range other_unit and
requires byte_offset=0. Invalid fields return EINVAL; source unit outside the
medium returns ERANGE. Capability/user-copy errors remain EPERM/EFAULT.
Non-ACTIVE or any open block users returns EBUSY. No address or data argument.
Production has neither the case nor functions and returns ENOTTY.

## Ownership, unwind and cleanup

Store owns backing and tags, allocated before disk publication. A tag allocation
failure frees backing and resets sizes/pointers. Security owns both XTS request/
transform, HMAC transform/descriptor, staging and tag scratch. Preparation owns
the temporary HKDF transform/PRK/output. Control owns the transient copied input.
The block component retains queue/work/disk/openers ownership and synchronization.

Partial activation calls security_clear: request before XTS transform, sensitive
descriptor free before HMAC transform, explicit staging/tag/backing reset, then
NO_KEY. Failed key setup never admits requests. Tags remain allocated but zero
after destroy, ready for the next initialization. Unload deregisters control,
closes admission, drains work, marks DYING, removes disk with worker still live,
releases worker/disk/tags, and clears/frees all security/store/device resources.
No request callback survives drain. Open control/block fds pin THIS_MODULE.

## Threat model and claims

The construction supplies XTS confidentiality and HMAC authentication of each
stored unit's ciphertext, domain, generation and address under separate keys.
It detects accidental or externally introduced corruption of that authenticated
material when read, assuming security keys, code, control state and verification
path are trusted. The controlled test hook simulates such limited corruption;
it is not a model of all abilities of a privileged attacker. Acceptance now
includes the completed VM results below; compile/static evidence alone would not
have established these runtime claims.

This is Encrypt-then-MAC, **not AEAD**, and XTS itself supplies no integrity.
An attacker able to replace both bytes and tag without the key cannot normally
forge a valid modified unit; moving a valid pair to another address changes the
authenticated index. Moving across generations changes the MAC message (and
fresh independently supplied input also changes keys). A previously valid pair
for the **same unit and same generation can be replayed**: there is no per-write
version or trusted freshness counter. There is also no device-specific random
identity; reusing K with identical generation/index in another instance permits
cross-instance replay. Fresh independent keys are a provisioning requirement,
not something this driver can prove. Module/VM snapshot rollback is unprotected.

No protection against arbitrary root/kernel memory modification, malicious kernel
code/providers, compromised hypervisor, key exposure, crash-persistent replay,
durable storage attacks, cold boot or denial of service. An attacker with kernel
control can bypass verification or restore state. Normal reads, request pages,
filesystem/application caches contain plaintext; a cached read can bypass the
driver entirely and need not detect later backing damage. Detection tests use
O_DIRECT. Cleanup covers named owned allocations during orderly execution,
not physical copies, caches/registers, crashes, snapshots or caller key copies.

## Verification status

**Compile/static verification and automated VM runtime acceptance complete.**
The earlier local checks on
2026-10-11 used Windows + Ubuntu WSL2 (`6.18.33.2-microsoft-standard-WSL2`),
GCC 15.2.0 and prepared Ubuntu `7.0.0-38-generic` headers. No packages, host
services, kernel settings or VM state were changed. No module was inserted.
The [VM harness and manual procedure](m5-testing.md) remain the reproducible
acceptance and troubleshooting path.

| Check | Observed result |
| --- | --- |
| Target preflight | PASS: prepared config/generated headers/Module.symvers; running-kernel mismatch identified as compile-only. |
| Clean production W=1 | PASS: five driver objects, MODPOST, link; no driver-source warnings/errors. |
| Clean M5_TEST=1 W=1 | PASS: same build stages, bounded tamper handlers and binding-test string present, M4 test strings absent. |
| Clean M5_TEST=1 M4_TEST=1 W=1 | PASS: same build stages, both diagnostic features present. Compiling does not execute them. |
| Strict target checkpatch | PASS on 13 kernel/header/control-helper files, zero errors/warnings/checks. ABI fixture separately passes with only CAMELCASE ignored for the standard C11 `_Static_assert` keyword; no driver check suppressed. |
| Control helper | PASS: unchanged shared helper builds C11/O2/Wall/Wextra/Werror/Wconversion. No device operation executed. |
| ABI | PASS: four -m64/-m32 object builds (production and test), original ioctl numbers/layouts preserved and test payload offsets/size checked. Compat runtime remains untested. |
| Metadata and imports | PASS: 0.5.0, GPL, expected XTS/HMAC description, uint capacity, vermagic 7.0.0-38-generic, hkdf dependency; all 65 imports exported by target Module.symvers. Crypto imports remain confined to security; no block-to-store imports. |
| Production exclusion | PASS: no M4/M5 test strings, tamper names/handlers or test-binding function in production strings/symbols. The second partial VM run also observed production ENOTTY. |
| Script checks | PASS: all four Python suites compile; environment script and seven M5 Bash files parse. Root-without-sudo guard fails closed. The harness self-test is non-destructive. |
| Documentation/text/history | PASS: Markdown links/anchors and shell snippets validated without execution; UTF-8/LF/final newlines; all M1-M4 historical docs, original M2 test, M4 control helper and Makefile unchanged. |
| Git | PASS: diff --check empty; HEAD and main still 5eb07d5; milestone branch only; no staged changes/commits/merges/pushes. |

### Partial automated VM evidence

The second automated attempt ran committed harness-fix head `2d2816f` on
Ubuntu 24.04.5 LTS, Linux 7.0.0-38-generic. Its VM evidence directory was
`.cache/m5-vm/20261011T131435Z-6829`; that ignored directory is not present in
this checkout, so this section records the supplied VM output rather than a
local log reinspection.

Before the harness stopped, it observed a clean production W=1 build and no
M4/M5 test surface; the 0.5.0 identity, 64 MiB capacity, 4096-byte unit, ABI 1,
features 7, NO_KEY state/generation 0, production test-ioctl ENOTTY, fail-closed
ENOKEY I/O, and the malformed ABI, weak-key, user-copy and privilege negatives.
The first load reached ACTIVE generation 1 and passed the full initial-zero and
raw suite: direct/segmented and boundary/neighbor cases, four concurrent streams,
end-of-device/flush behavior, 1 MiB SHA-256/cmp, and active replacement EBUSY.
Lock reached state 3, denied I/O and replacement, then unlocked to ACTIVE with
generation 1. Destroy reached NO_KEY generation 1, denied I/O, was idempotent,
and a fresh load reached generation 2 with a fresh-zero medium and a second full
raw regression. Fresh kernel evidence remained clean through the stop point.

The run then stopped before ext4 at `run-m5-production.sh` line 81 because the
harness split an output redirection from its pathname across a newline. The
summary correctly recorded ext4 FAIL, every later phase NOT RUN and OVERALL
FAIL. This is a harness execution defect, not a SecureRAM driver/runtime failure.
No ext4, tamper/relocation/recovery, capacity-boundary or final-production result
from this attempt is accepted. Full M5 runtime acceptance remained pending at
that point; the successful run below supersedes both incomplete attempts.

### Successful automated VM acceptance

The final run tested full commit `5fabe544a3969732647e7d9962beed974b667901`
on Ubuntu 24.04.5 LTS in VirtualBox with Linux 7.0.0-38-generic and SecureRAM
0.5.0. It used the exact-hash-pinned command from the M5 procedure. The retained
VM evidence directory is `.cache/m5-vm/20261011T140342Z-10296`; that ignored
directory is not present in this checkout, so this report records the supplied
final summary and observed facts rather than claiming a local log reinspection.
The combined M5/M4 diagnostics were present in the test build, while both test
surfaces were absent from the production builds.

| Automated result | Observed runtime evidence |
| --- | --- |
| Production build — PASS | Clean matching-kernel W=1 build; no M4/M5 test strings or tamper symbols. |
| Initial NO_KEY — PASS | Version 0.5.0, 64 MiB, 4096-byte unit, state 0/generation 0; ENOKEY block opens and production corruption-command ENOTTY. |
| ABI/features — PASS | ABI 1, features 7; malformed ABI, weak-key, copy-fault and privilege negatives passed. |
| Raw I/O — PASS | ACTIVE state 2/generation 1; full logical-zero scan, direct/segmented and boundary/neighbor cases, four concurrent streams, end-of-device/flush, and 1 MiB SHA-256/cmp. |
| Lock/unlock — PASS | ACTIVE replacement EBUSY; LOCKED state 3 denied I/O/load; unlock restored ACTIVE without changing generation. |
| Destroy/rekey — PASS | Destroy reached NO_KEY generation 1, denied I/O and was idempotent; fresh load reached generation 2 with a zero medium and a second full raw regression. |
| ext4 — PASS | `nodiscard` format, write/sync/read, mounted transition EBUSY with continued readability, unmount/remount/read and final clean unmount. |
| Ciphertext tamper — PASS | Controlled ciphertext corruption returned EIO and latched INTEGRITY_FAILED. |
| Tag tamper — PASS | Controlled tag corruption returned EIO and latched INTEGRITY_FAILED. |
| Relocation protection — PASS | Relocating a valid ciphertext/tag pair to another unit failed authentication. |
| Integrity-failure recovery — PASS | Failed-unit output remained untouched; prohibited transitions stayed rejected; destroy then fresh load recovered. All three lifecycles ended NO_KEY at generation 6. |
| 1 MiB capacity — PASS | Exact bounded lifecycle and raw suite completed. |
| 256 MiB capacity — PASS | Full zero scan and raw lifecycle completed; capacity 0 and 257 were rejected without publishing module/device state. |
| Final production regression — PASS | Clean production rebuild, test-surface exclusion, fresh NO_KEY/ENOTTY, complete raw regression, ext4 sync/remount and destroy/denied-I/O regression. |
| Kernel health — PASS | No fatal or SecureRAM-attributable kernel signature; expected integrity-I/O messages were not crash signatures. |
| Final cleanup — PASS | Key destroyed, module unloaded, and block/control nodes, sysfs objects and module entry disappeared. |
| **OVERALL — PASS** | Every automated acceptance category completed successfully. |

The compiler naming warning and pahole/BTF diagnostics are environmental build
observations, not driver failures or kernel-health failures. This successful run
establishes normal M5 production, integrity-test, capacity and cleanup behavior
within the documented threat model. It does not establish the separate allocation,
provider/crypto-failure, pending-request-race, compat-runtime, lockdep, KASAN or
kmemleak campaigns listed in the procedure.

Environmental diagnostics in all three build logs: target GCC 13.3.0 versus
local GCC 15.2.0, target pahole 125 versus missing local pahole (0), and BTF
skipped because vmlinux is unavailable. These are retained, not reported as a
warning-free environment. The driver itself emits no compiler/MODPOST warnings.
Rebuild for the actual VM kernel with the appropriate compiler before insertion.

Ignored local logs are `build-m5-production.log`, `build-m5-test.log`,
`build-m5-combined-test.log`, checkpatch/helper/ABI logs and
`build-m5-modinfo.log`; `.cache/verify_m5.py` orchestrated compile/static checks.
Generated module artifacts were inspected and then cleaned. The small untracked
checkpatch cache created by the tool was removed. Earlier style checks found
one continuation alignment issue (fixed) and the C11 keyword false positive
(documented); they are not counted as successful final checks.

Manual review traced tag bounds and precommit checks, all crypto error returns,
temporary secret clearing, descriptor reuse, activation/unwind, queued-request
failure, control-after-drain revalidation and teardown. This is source evidence,
not proof of runtime race freedom, physical erasure or injected-failure behavior.
The successful run observed tamper/relocation/recovery, ext4 mounted-busy and
remount behavior, capacity-boundary lifecycles, final production regression and
clean kernel evidence. The source-review-only limits above remain source evidence;
the additional diagnostic fault campaigns remain outside normal acceptance.

## Final adversarial source review

Reviewed the actual candidate again on 2026-10-11 before committing. PASS below
means source review and the stated compile/static evidence, not VM acceptance.
No implementation, ABI, test assertion or key derivation changed in this audit.

| Requested section | Result and source finding |
| --- | --- |
| 1. Version/ABI/features | PASS: 0.5.0, ABI 1, QUERY features 7, stable failure value 4; original header/key/status are 16/88/48 bytes. Test payload is separately guarded and 40 bytes. Both widths compiled. DYING compatibility caveat is documented above. |
| 2. HKDF/key separation | PASS: Linux helper argument order is IKM then salt, but Extract keys HMAC with salt and hashes the 64-byte IKM. Explicitly set PRK before Expand. Salt/info lengths are 24/22, output and resident MAC setkey length are 32. All exits wipe local PRK/output and free the temporary transform; no secret logging. |
| 3. Authenticated encoding | PASS: explicit 32-byte prefix plus all 4096 ciphertext bytes; no struct padding/NUL/native endian. Sector bound precedes multiplication, full range/alignment precede the cursor, and u64 offset/4096 is not narrowed. Generation cannot change during worker I/O. |
| 4. Verify before decrypt | PASS, guarantee A: store copies ciphertext/tag, authenticate computes expected tag, crypto_memneq precedes decrypt. Mismatch skips decrypt and scatter, clears staging and returns an I/O error. Earlier verified units may already be copied; guarantee B is absent. |
| 5. Pair commit | PASS: gather/encrypt/MAC precede backing mutation; one complete range check precedes two non-failing memcpy calls. Sole worker and drained control exclude observers. Precommit failures leave the unit unchanged; no whole-request rollback. |
| 6. Failure concurrency | PASS: single worker publishes the latch; admission closes under pending_lock before completion, queued requests check ACTIVE before data access. Control drains before state validation. QUERY and closed-device DESTROY remain usable; LOCK/UNLOCK/LOAD cannot clear the latch. |
| 7. Generation | PASS: U64_MAX rejects load with EOVERFLOW before PREPARING; initialization uses generation+1 and success publishes it. Destroy does not increment/reset it; module reload resets it. |
| 8. Activation | PASS: tags allocated before publication; key setup, request/descriptor allocation and every zero-unit ciphertext/tag precede externally visible ACTIVE. Every preparation failure clears partial state and keeps the prior generation. |
| 9. Cleanup | PASS: XTS request/transform, temporary HKDF transform and explicit key buffers, resident HMAC descriptor/transform, staging, backing and tags all have cleanup. Provider state destruction relies on Crypto API ownership. No physical RAM erasure claim. |
| 10. Test isolation | PASS: test case, declarations, handlers and banner are compiled out of production. Test operations require initial-namespace CAP_SYS_ADMIN, valid fields/ranges, ACTIVE, zero openers and gate/drain; all addresses derive from owned arrays. |
| 11. Historical M4 test | PASS: only optional version parameters, default 0.4.0, replace the literal identity comparison and are forwarded by main. M5 wrapper supplies 0.5.0; every other identity/I/O assertion is unchanged. |
| 12. Claim audit | PASS after documentation corrections: administrative opener requirement distinguished from worker failure; exact failed-unit release guarantee, old-client label caveat and secret-input wording clarified. Replay/root/kernel/hypervisor/physical-erasure limits retained. |
| 13. Final checks | PASS: clean production, M5-only and combined W=1 rebuilds; strict helper, four ABI builds, checkpatch, script/doc checks and diff --check rerun successfully. Production exclusion has positive controls below. |

Retaining Kxts=K while deriving Kmac is adequate for this project's stated
high-entropy-input, trusted-key/code threat model under the usual AES/HMAC/HKDF
assumptions. The MAC does not reuse K or either AES half as its key. This is not
independent compromise isolation: disclosure of K compromises both functions.
Deriving both keys with separate labels would change M4's established XTS key
mapping; this review found no requirement to make that compatibility change.

The read guarantee is per failed unit, including scatter/gather splits. The
cursor calls security_read before mapping/copying any fragment of that unit.
An earlier verified unit's request pages are not rolled back when a later unit
fails. The triggering request fails as a whole at blk-mq completion; this does
not imply its entire destination buffer stayed untouched.

The write guarantee is an indivisible ciphertext/tag update only with respect
to cooperating SecureRAM paths during normal execution. Neither memcpy has an
ordinary recoverable error after validation, and no second worker/control
mutation can interleave. It is not a hardware atomic transaction or a crash
guarantee. The optional M4 diagnostic may report an error after a completed pair
commit; even that path does not intentionally leave a mixed pair.

Rechecked activation exits: early state/overflow/weak-key rejection wipes the
supplied copy without changing live state. XTS allocation/shape/setkey, HKDF
Extract/PRK-setkey/Expand, resident HMAC allocation/setkey/descriptor, request
allocation, per-unit crypto/commit and optional binding failures all reach
cleanup. Partial resident MAC allocation is owned by security_clear even when
prepare_mac returns an error. Optional M4 cursor checks run with admission closed
and control_lock held; failure rolls back the unpublished generation and state.
READ_ONCE/WRITE_ONCE are not a substitute for exclusion: sole-worker ordering,
control_lock, gate/drain and pending_lock provide it. Normal unload cannot race
live control/block handles because both file operation tables pin THIS_MODULE.

The same ignored verification runner rebuilt each variant from clean with
`make KDIR=<prepared-7.0.0-38-generic-headers> CC=gcc W=1`, adding `M5_TEST=1`
and optionally `M4_TEST=1` for the respective variants. Production was last.
The compiler/pahole/BTF diagnostics listed above remain; there were no driver
compiler or MODPOST warnings. No runtime or fault-injection test was executed as
part of that local source-review pass; the later accepted VM run is recorded above.

After the production build, these exact inspection commands succeeded. Each
of the four grep commands produced no output and exit 1 (no matches); the
producer commands exited 0. The preprocessed log was captured from
`make -C <prepared-headers> M=<repository> CC=gcc W=1 src/secureram_control.i`.

```sh
nm secureram.ko > build-m5-production-nm.log
strings secureram.ko > build-m5-production-strings.log
objdump -dr src/secureram_control.o > build-m5-production-control-disassembly.log
grep -En 'tamper|secureram_test_binding' build-m5-production-nm.log
grep -En 'M[45] test|secureram_.*tamper|SECURERAM_IOC_TAMPER' build-m5-production-strings.log
grep -En 'tamper|4028b770' build-m5-production-control-disassembly.log
grep -En 'tamper|SECURERAM_IOC_TAMPER' build-m5-production-control.i.log
```

Positive control on the preceding M5-only disassembly found the comparison
with `0x4028b770` and a relocation to `secureram_block_tamper` (grep exit 0).
Its symbols also contained block/security/store tamper handlers and its strings
contained the binding-test message. Production modinfo returned version 0.5.0
and dependency hkdf. Exact output is retained in the ignored
`build-m5-production-proof.log`, with variant preprocessing/disassembly logs.
These build/source checks establish that the test dispatch is excluded. The
subsequent successful VM acceptance also confirmed production ENOTTY at runtime.

Audit edits are limited to README, architecture, this report and the M5 test
procedure for the wording fixes and review evidence. No commit, push or merge
was made; generated build artifacts were inspected before cleanup.

## Files changed

| Files | Purpose |
| --- | --- |
| `src/secureram_security.c`, `include/secureram_security.h` | HKDF/HMAC, tag calculation, verify-before-decrypt, failure latch, crypto ownership/cleanup and internal binding check. |
| `src/secureram_store.c`, `include/secureram_store.h` | Separate tag allocation, checked complete pair reads/commits, wipe/free and guarded corruption primitives. |
| `src/secureram_block.c`, `include/secureram_block.h` | Worker failure gate, queued-request rejection, concurrent state reads, transition revalidation and serialized test adapter. |
| `src/secureram_control.c`, `include/uapi/secureram.h`, `include/uapi/secureram_test.h` | Compatible state/feature extension and separate guarded privileged test ioctl. |
| `Kbuild`, `include/secureram_config.h`, `src/secureram_main.c` | M5 build guard, version 0.5.0 and accurate lifecycle messages. |
| `tests/m4-raw-io.py`, `tests/m5-raw-io.py` | Parameterize historical identity check without changing its default; reuse raw suite for M5. |
| `tests/m5-integrity.py`, `tests/abi-layout.c` | VM corruption/recovery/denial suite and persistent compile-only ABI checks. |
| `tests/m5-vm-common.sh`, `tests/run-m5-*.sh` | Guarded production/tamper/capacity/final VM orchestration, cleanup, evidence capture and summary. |
| `README.md`, `docs/architecture.md`, `docs/development.md`, `tests/README.md`, `tools/README.md` | Current behavior, ownership, build/test workflow and honest limits. |
| `docs/m5-report.md`, `docs/m5-testing.md` | Design/ABI/evidence/viva record and automated/manual VM acceptance plan. |

## Viva preparation

- Explain why encrypting and authenticating are separate jobs, why HMAC needs a
  separate key, and why HKDF is a standard KDF but not password stretching.
- Trace the 4128 authenticated bytes and explain how index binding detects
  relocation while same-unit same-generation replay remains possible.
- Explain verify-before-decrypt versus detecting errors after copying plaintext.
- Trace pair commit exclusion, prevalidation, allocation ownership and failure
  unwind; distinguish one unit's consistency from whole-request atomicity.
- Explain the new worker-written state, READ_ONCE/WRITE_ONCE, admission spinlock,
  queued failures and why taking control_lock from the worker would deadlock.
- Distinguish lock retaining both keys, destroy wiping them, and generation
  bookkeeping from persistent anti-replay. Explain failed-state opener protection.
- Separate test-build evidence, production regression, compile/static checks
  and unobserved runtime/fault-injection guarantees.
