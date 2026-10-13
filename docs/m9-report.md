# M9 reliability design, audit and evidence

## Baseline and scope

Started on `main`, exactly `232862e06130b7e9ae3b6b10612717ed72ba0d94`
(M8 merge), on 13 October 2026. Tracked files were clean. The pre-existing
untracked `Transfer/m8-secure-snapshots.bundle` is operator-owned and preserved.
Before creating `m9-stress-hardening`, the complete `check-m8-local.py` runner
passed in WSL, exit 0, transcript `build-m9-baseline.log`. It includes three W=1
kernel builds, ABI, strict checkpatch, sanitizer core, CLI, HTTP/UI and harness
checks. ShellCheck is absent. GCC 15 versus target GCC 13, missing pahole and
unavailable vmlinux/BTF remain environment limitations. No kernel was loaded.

M9 keeps version 0.8.0, ABI 1, feature mask 31 and the M8 architecture. This is
reliability validation, not a user-visible feature release or M10 evaluation.
M8 runtime evidence remains historical; M9 VM acceptance is **NOT RUN**.

## Invariants defined before implementation

| Area | Invariant and observable test oracle |
| --- | --- |
| I/O | Last completed write is returned when no intervening writer exists. Disjoint regions have exact independent expected data. Racing writes may win in either order; each aligned unit must match a complete submitted pattern. Never assert a multi-unit syscall is atomic. |
| Bounds | First/last units stay intact after invalid offsets, lengths and end-of-device operations. Buffered unaligned writes are verified after final close using direct reads. Kernel-core rejection is distinct from driver dispatch coverage. |
| Confidentiality | Only encrypted data goes to the store. Reuse M4 internal comparisons in combined builds; no backing/key export. |
| Failure atomicity | A unit commits ciphertext and tag only after encryption and MAC success. Earlier units in a failed multi-unit request may commit; tests do not promise whole-request rollback. |
| Integrity | Ciphertext/tag/relocation corruption produces EIO, untouched failing-unit output and a failure latch. Snapshot restoration is authenticated by normal direct reads. |
| Keys | Only NO_KEY loads; failed load remains NO_KEY without incrementing generation. Destroy clears slot, transforms, descriptors, staging and store. New generation exposes authenticated zeros, never previous content. |
| Snapshots | One complete data/tag pair store publishes only after successful allocation/copy. Restore requires ACTIVE, slot and matching nonzero generation. Delete is idempotent. Destroy/unload clear the slot. |
| Concurrency | Open block users force EBUSY for all lifecycle mutations. Control mutex serializes valid closed-device operations. Worker never takes that mutex. Tests enumerate permitted serial orders instead of accepting arbitrary errors. |
| UAPI | Wrong command encodings return ENOTTY; malformed headers/lengths/flags/reserved fields EINVAL; bad pointers EFAULT; passed-fd unprivileged callers EPERM. Rejection leaves data/state/generation unchanged. |
| Cleanup | Every accepted request completes once. Teardown removes nodes and queue/worker/control resources, then wipes/frees crypto, live store and snapshot. Repeated unload must never be forced or ignored. |

## Test design and fault boundary

Use the existing M5 identity guards, M6 phase ledger/cleanup and M7 dashboard
process owner; compose all M8 VM regressions with additional M9 phases in one
entry point. All block targets are literally `/dev/secureram0`. Quick and
extended modes share test implementations and bounded iteration counts.

Concurrent direct I/O uses page-aligned mmap buffers and positional operations.
Disjoint writers verify exact per-region patterns; overlapping writers/readers
validate individual units against deterministic allowed patterns, followed by
an exclusive final overwrite/readback. Barriers ensure competing threads start
together. Statistics are read during activity and must remain monotonic.
Snapshot loops compare small and large regions before/after rollback and require
no authentication failures. Key loops check zero data, state, generation and
snapshot invalidation. Module loops leave a slot on selected unloads.

Existing `M5_TEST=1` bounded ciphertext/tag corruption is reused, including
sentinel read buffers and fail-closed recovery. No production corruption API is
added. Proposed `M9_TEST=1` is a separate opt-in build: a root/host-admin-only
one-shot fault selector identifies only fixed allocation/crypto call sites.
It cannot address memory, read data, export keys or change state directly.
Atomic compare/exchange consumes a matching site once; zero disarms it.
Production preprocesses the calls to constant false and omits the selector
object/sysfs parameter. Clean builds and symbol/string/preprocessed checks prove
exclusion. Faults enter existing error/unwind paths, not alternative algorithms.

Fault coverage: live/snapshot data and tag allocations; crypto request allocation
after key setup; encryption, decryption and MAC errors; control input allocation.
Tests verify consumed faults, exact errno, unchanged live unit/slot where
promised, unchanged generation on failed load, recovery and subsequent I/O.
These are call-boundary failures, not faults inside a Crypto API provider.
Global failslab/fail_page_alloc would risk unrelated VM allocations and depend
on optional debugfs/kernel configuration; they are not mandatory. No custom
kernel rebuild is required. KASAN/KCSAN/lockdep/kmemleak and compat runtime are
separate optional campaigns; ordinary stress cannot prove absence of all leaks
or races or forensically prove physical erasure.

## Focused ownership and locking audit

Reviewed main, block, security, store, snapshot, control, stats, all headers and
build rules, CLI, dashboard boundaries and existing tests at the baseline.
Capacity is bounded at 256 MiB before multiplication; store range validation
uses subtraction after offset validation; tag division precedes multiplication.
Block requests prevalidate all fragments, gather/scatter units, complete once
and never use recycled requests. Pending spinlock covers gate/list/queue_work;
ordered worker owns staging. Control mutex -> pending spinlock, release spinlock
-> drain avoids worker/control inversion. Stats has an independent bounded lock.
Snapshot copy validates both geometries before non-fallible paired copies.

User-copy lengths are fixed compile-time structure sizes, never attacker-chosen
allocation sizes. Output structures are initialized including reserved fields.
Key input is sensitive-freed even on partial copy. Load fails through common
clear without advancing generation; request/transform/descriptors and temporary
HKDF secrets use established wiping APIs. Target headers confirm
skcipher_request_free uses kfree_sensitive and request_zero wipes provider
context. Awaited crypto completion precedes wiping/reuse. Snapshot clear
invalidates publication then clears/frees both stores under exclusion.

Partial init unwinds control publication, disk, tags, workqueue and security in
reverse order. Normal exit deregisters control, gates/drains I/O, removes disk
while the worker exists, then frees queue/worker/security. Open files pin the
module. The audit has not established a production driver bug; no speculative
refactor is justified. Test/evidence infrastructure findings and observed
verification results will be recorded here after execution.
