# M8 design and evidence: secure snapshots and rollback

Starting evidence: clean `main` and local `origin/main` at M7 merge `be43792`.
M7's automated VM and Firefox acceptance are recorded in its report. M8 work
is confined to `m8-secure-snapshots`; no merge or push is authorized by this task.

## Design reviewed before implementation

One optional volatile slot belongs to the existing security context. It owns a
second `secureram_store` (ciphertext plus matching 32-byte HMAC tags), the successful
key-load generation, and a publication flag. No key copy or full-device plaintext
buffer is introduced. The existing XTS/HMAC format, lifecycle and worker remain.

Create requires ACTIVE and an empty slot (EEXIST otherwise). Allocate a temporary
store with the established checked `vzalloc` strategy, copy both arrays, and only
then publish. Allocation failure frees partial resources and leaves no slot.
Restore requires ACTIVE, a published slot, equal nonzero generation and matching
geometry; all checks precede either live copy. Copies of valid kernel allocations
cannot return a recoverable copy error. Restore retains the slot. This is logical
atomicity against I/O/control observers, not crash atomicity.

All mutations use the existing control mutex, reject open block users (EBUSY),
close admission under the pending spinlock, release that lock, drain the ordered
worker, then operate and reopen only if ACTIVE. The worker never takes the
control mutex. No new lock or block-core freeze/open call is introduced. Status
takes only the control mutex. Snapshot counters share that mutex and saturate at
U64_MAX. They survive key destruction, reset on module reload, and do not alter
the existing five M6 counters or GET_STATS layout.

LOCKED/NO_KEY reject create/restore (EBUSY); status and explicit delete are
available, including INTEGRITY_FAILED. Delete is idempotent and still requires
zero block users. An integrity latch cannot be cleared by restore. Lock/unlock
retain association. Key clear frees the slot before freeing crypto, and unload
uses the same path. Store destruction uses `memzero_explicit` then `vfree` on
both arrays. Generation never wraps; existing load rejects U64_MAX. Reload loses
both slot and keys, so identifiers need not be globally unique.

ABI 1's existing structures, command encodings and JSON fields stay unchanged.
New commands 0x06..0x09 implement create, restore, delete and output-only status;
mutations use the existing 16-byte header with zero flags/reserved. A new feature
bit 16 advertises snapshots. Status carries only presence, lifecycle state,
sizes, generation and diagnostic counters, with aligned fixed-width fields and
zeroed reserved fields. Every ioctl retains the initial-namespace CAP_SYS_ADMIN
check and compat_ptr_ioctl translation.

The CLI adds `snapshot create|restore|delete|status [--json]`. The dashboard adds
fixed CLI arguments/routes, strict JSON validation and typed RESTORE/DELETE
confirmation through the existing same-origin/token protections. It owns no
snapshot implementation. Existing M6 status/stats JSON schemas remain stable.

```text
browser -> localhost adapter -> secureramctl -> privileged snapshot ioctl
  -> control mutex -> zero openers -> close gate -> drain worker
  -> security-owned slot <-> ciphertext RAM + HMAC tag RAM
  -> reopen admission only in ACTIVE
```

Default additional allocation: 64 MiB ciphertext + 512 KiB tags, plus bounded
bookkeeping/allocator overhead. Maximum at capacity_mb=256 is 258 MiB additional.
Create refuses replacement, so there is never a second candidate beside an
existing slot. No disk persistence, multi-slot manager, COW or later milestone.

## Security and consistency limits

A snapshot captures one coherent internal block-device state after prior I/O
drains. It is not an application/filesystem transaction, cache checkpoint or
filesystem freeze. Unmount/close users before capture or rollback; acceptance
uses direct raw I/O. Normal restored reads still verify HMAC before decryption.
Copying a snapshot is not an integrity scrub: latent corruption is copied and
detected on subsequent authenticated reads. Metadata/control memory and kernel
remain trusted, as in M5. Authorized rollback intentionally permits older data
within the same generation; there is no new freshness/anti-replay guarantee.
Snapshots reveal ciphertext equality at an address across time. Explicit wiping
does not promise removal of external copies, crash dumps, hypervisor snapshots,
CPU caches or physical RAM remanence.

## Verification status

Implemented on 13 October 2026. No M8 real-kernel/VM runtime PASS is claimed.

| Check | Observed result |
| --- | --- |
| Complete `check-m8-local.py` in WSL | PASS; transcript `build-m8-local.log`. No module insertion or block access. |
| Three clean W=1 kernel builds | PASS: production, M5 test, combined M4/M5 test; MODPOST/link, imported exports and production test-hook exclusion passed. |
| C/ABI/static | PASS: strict CLI/helper compilation; all old/new LP64 and ILP32 ABI assertions; strict checkpatch with zero source errors/warnings/checks (standard `_Static_assert` CamelCase exception retained). |
| Actual store/snapshot C under ASan/UBSan | PASS: both allocation failures, stale/zero generation, invalid geometry before copies, whole data/tag comparisons, 100 cycles, idempotence, counter saturation, wipe-before-free and balanced allocations. This is userspace execution with allocator/scheduler shims, not kernel synchronization evidence. |
| CLI | PASS: all inherited M6 parser/syscall tests and new snapshot syntax, feature/ABI/schema checks, u64, lifecycle errors, no-memory/stale/occupied/absent and follow-up failure cases. |
| M7 backend/HTTP | PASS: 24 tests on Linux; Windows 22 pass and two platform skips. Includes bounded concurrency, authorization, exact Origin policy, shutdown and symlinks on Linux. |
| M8 backend/HTTP | PASS: three tests, fixed CLI argv, complete synthetic lifecycle, security/confirmation rejection, strict schema/u64 and sanitized error categories. |
| UI/static | PASS: Node syntax and M7/M8 pure display/state helpers; offline assets, IDs/accessibility references, prohibited sinks/storage and CSP checks. |
| Harness tests | PASS: inherited M5/M6/M7 mocked phases/ledger/cleanup; five M7 observer/session tests; actual M8 phase ordering/full-SHA gate/fail-fast/unload/reload mocks; individual syntax for all 19 shell files. |
| Browser fixture | PASS: actual in-app browser on Windows against a labelled, unprivileged mock. NO_KEY -> ACTIVE, create, lowercase RESTORE rejected, exact RESTORE succeeds/retains slot; lock blocks create/restore, Cancel retains slot, exact DELETE works while locked; unlock/create, disconnect disables controls, fresh URL reconnects. 390px layout has no horizontal overflow. No console warnings/errors before intentional disconnect. Screenshots `.cache/m8-dashboard.jpg`, `.cache/m8-mobile.jpg`; not Ubuntu Firefox or real-device evidence. |
| Real Ubuntu M8 kernel/HTTP/SHA/cleanup acceptance | NOT RUN. Prepared harness and exact commands in [M8 testing](m8-testing.md). |
| Real Ubuntu Firefox M8 acceptance | NOT RUN. M7's historical PASS does not accept M8. |
| ShellCheck / lockdep / KASAN / kmemleak / compat runtime / kernel allocation fault injection | NOT RUN. ShellCheck not installed; no new dependency installed. Userspace allocation failure tests are not kernel fault injection. |

Local host is Windows with WSL `6.18.33.2-microsoft-standard-WSL2`; headers target
Ubuntu `7.0.0-38-generic`. Build warnings remain GCC 15.2 versus target GCC 13.3,
unavailable local pahole (target 125), skipped BTF because vmlinux is unavailable.
This does not establish support for every Linux 6.x/7.x internal API or runtime.
The installed target headers were inspected for `vzalloc`, `flush_workqueue`
and `memzero_explicit`; existing block-core release/cache assumptions are
unchanged from the accepted architecture.

During verification, strict checkpatch found six overlong CLI lines; those were
wrapped and the complete runner passed afterward. The Windows excess-connection
fixture returned ConnectionAbortedError instead of ConnectionResetError. Both
mean the excess socket was closed; the test now accepts either while preserving
the actual bounded-slot assertion. The full Windows test rerun passed with its
two existing platform skips. No driver defect or runtime acceptance is inferred
from either of these local test adjustments.

## UAPI and compatibility detail

Old QUERY/LOAD/LOCK/UNLOCK/DESTROY/GET_STATS encodings, payloads, states and JSON
field sets remain unchanged. ABI stays 1; the extensible feature mask becomes
31. A current CLI can still run old commands on the previous mask-15 driver;
snapshot commands fail with feature-mismatch exit 3. The updated dashboard
accepts masks 15 and 31; unsupported masks disable actions. An old strict M7
dashboard must be updated together with the M8 driver to recognize bit 16.

| Command | x86 LP64/ILP32 encoding | Payload |
| --- | --- | --- |
| SNAPSHOT_CREATE | `0x4010b706` | 16-byte version/size/zero flags/zero reserved input. |
| SNAPSHOT_RESTORE | `0x4010b707` | Same header. |
| SNAPSHOT_DELETE | `0x4010b708` | Same header. |
| SNAPSHOT_STATUS | `0x8060b709` | 96-byte output, completely initialized. |

Status offsets: header 0..15; exists u32 at 16; state u32 at 20; aligned u64
data_bytes/tag_bytes/generation at 24/32/40; created/restored/deleted/failures at
48/56/64/72; reserved u64[2] at 80. Sizes and snapshot generation are zero when
absent. Kernel addresses, keys, plaintext and tags never cross this interface.
EFAULT is returned on bad user copy, EINVAL on malformed headers, ENOTTY on unknown
encodings and EPERM before any copy on unauthorized calls, including passed fds.

| State | Status | Create / Restore | Delete |
| --- | --- | --- | --- |
| ACTIVE | Available | Allowed with zero openers; EEXIST / ENODATA for occupied / absent slot. | Allowed with zero openers; repeated absence succeeds. |
| LOCKED | Available; slot retained | EBUSY | Allowed with zero openers; no live-medium/key/state change. |
| NO_KEY | Available; slot absent after destruction | EBUSY | Idempotent cleanup with zero openers. |
| INTEGRITY_FAILED | Available; preexisting slot may remain | EBUSY; cannot bypass latch | Allowed once block users close, without clearing latch. |
| DYING | Not reachable via a pinned live control handle | ENODEV defensively | ENODEV defensively. |

Generation mismatch/zero returns ESTALE before copying. Geometry errors return
EINVAL before copying. Allocation failure returns ENOMEM and leaves the live
store untouched and slot absent. Only initial create allocates, and occupied
create returns before allocating. Restore/delete allocate no device-sized buffer.
Successful restore leaves ACTIVE and unchanged generation; all future reads and
writes use the existing crypto path. Snapshot copies neither decrypt nor perform
a MAC scan; a corrupted image fails normal authenticated reads, not a background
validation pass. An integrity-failed live device cannot use a good earlier slot
as a recovery shortcut.

Four counters are updated under `control_lock` and saturate at U64_MAX. Counts
survive automatic slot invalidation. `deleted` counts only explicit present-slot
deletes. `failures` includes well-formed mutation failures reaching the block
layer, including EBUSY, but excludes user-copy/header/capability/unknown-ioctl
rejections and read-only status. Snapshot bytes are internal copies, so M6 I/O
counters remain unchanged. Mutating CLI JSON is a later status observation;
another administrator can intervene. CLI follow-up failure says the action
already completed. HTTP/CLI timeouts must not trigger automatic retries.

## Locking, ownership and viva review

Trace browser -> fixed server argv -> CLI -> safe user-copy and capability check
-> block adapter -> security-owned snapshot -> store. Explain why ciphertext
alone cannot roll back HMAC tags, why key generation is lifetime identity and
not replay protection, and why the snapshot has no copy of the encryption key.

The existing order is block-core open mutex -> control mutex -> pending spinlock.
Snapshot mutation takes control_lock, rejects nonzero openers, closes accepting
under pending_lock, releases the spinlock and waits for workqueue completion.
Dispatch cannot append accepted work after gate closure. Already accepted work
retains its original key/store until completion; worker and crypto callbacks
never acquire control_lock. The state check happens after drain, preserving a
possible integrity latch. The mutex remains held through allocation/copy/free
and counter updates. New open callbacks and administrators wait; status sees
either absent or fully published storage. Reopen requires ACTIVE. No sleeping
operation is done under pending_lock; no freeze/open/close is called under the
control mutex. Existing final-close flushing/invalidation prevents stale cached
writes after successful rollback. Applications and mounted filesystems must
still be closed; no fsfreeze or application checkpoint protocol was added.

The slot owns exactly two allocations. A temporary candidate owns them until
publication transfers ownership to the slot. Partial init/copy validation
failure destroys the candidate. Explicit delete, key clear and orderly module
unload converge on the same idempotent clear routine. Publication is invalidated
before wiping/freeing, under exclusion. The security context, not the HTTP
server or ioctl stack, owns the lifetime. Restores copy only after all fallible
checks, so no ordinary return path leaves half-restored storage. A malicious
kernel, invalid internal pointers, power loss or hardware fault is outside this
logical atomicity guarantee.

## Scope remaining for manual acceptance

Run the committed M8 harness and review its preserved ledger/logs, then use real
Ubuntu Firefox for the new controls and confirmations. The prepared suite tests
invalidation through destroy/rekey; direct stale-generation and allocation
failure branches are exercised locally in the actual C core. Do not describe
the prepared runtime tests as passed until the guest output is observed.
Kernel allocator/provider failures, in-flight kernel race instrumentation,
lockdep/KASAN/kmemleak and 32-bit compat ioctl execution remain additional campaigns.
No M9 implementation, push or merge was performed.
