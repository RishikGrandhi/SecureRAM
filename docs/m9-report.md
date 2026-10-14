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
M8 runtime evidence remains historical. M9 real-VM acceptance is **PASS** on
14 October 2026 at `fde91b901946a71b0f8fc764c02cce5e57984049`; see the exact
run and limits below. Subsequent acceptance-record changes are documentation only.

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
refactor is justified.

## Implemented reliability coverage

`tests/m9-stress.py` supplies deterministic I/O, bounded barriers, explicit
serial-order race oracles, repeated rollback/rekey and negative UAPI cases.
It uses the existing identity/direct-I/O helpers. Keys are produced solely by
the existing protected CLI; test pattern bytes are public and reproducible.
Small/large writes are 4 KiB/128 KiB, snapshot regions alternate 4 KiB/1 MiB;
the inherited M8 phase separately covers full 64 MiB rollback. The new stress
device is 8 MiB and reload device 1 MiB to keep normal acceptance practical.
Each new key is checked with a full-device authenticated zero scan.

`tests/run-m9-vm-acceptance.sh` composes M8 phases and M9 phases using the
existing ledger, root/owner/commit/header/device guards and cleanup functions.
`M9_MODE=quick|extended` changes counts, not assertions. New phases have a
20-minute subprocess limit, CLI a 60-second limit and the session a two-hour
limit. Failures retain useful evidence and never become PASS; remaining
uninterruptible-kernel limitations are explicit in the procedure.

`src/secureram_fault.c` owns only an atomic site selector in `M9_TEST=1` builds.
Seven fixed call boundaries return allocation/crypto errors through the real
existing cleanup paths. `atomic_cmpxchg` consumes exactly one matching fault;
only 0..7 can be armed, sysfs mode is 0600, and writes check initial-namespace
CAP_SYS_ADMIN even for an already opened descriptor. No key, pointer, offset,
length or backing byte is exposed by the selector. Default code uses an inline
constant false; Kbuild omits the object. No production UAPI or ABI change.

Actual C snapshot/store sanitizer tests retain both allocator failure paths,
publication/geometry/generation guards, 100 cycles, zero-before-free assertions
and balanced allocation accounting. Kernel fault tests additionally check
failed module initialization, control/crypto setup, snapshot allocation and
read/write errors, selector consumption, preservation and usable recovery.
These kernel fault checks passed in the real-VM run recorded below.

## Bugs found and narrow fixes

1. **VM boundary oracle:** the first real Ubuntu run of `b12988c` passed
   disjoint/overlapping concurrent I/O, then failed because the test expected
   EOF for a 4096-byte read at `2^63 - 4096`. Linux
   [`rw_verify_area`](https://github.com/torvalds/linux/blob/master/fs/read_write.c)
   rejects signed offset-plus-length overflow with EINVAL before block EOF
   handling. The oracle now requires EINVAL for that read and write, while
   retaining exact zero-byte EOF checks at capacity and capacity + 4096.
   A regression fixture rejects a positive EOF read and an incorrect overflow
   errno. All five focused stress-oracle tests pass. No driver change was needed.
   First-run evidence: `20261014T135552Z-21598`, overall FAIL, kernel health PASS,
   phase cleanup successful; later groups were NOT RUN. The complete rerun of
   the corrected candidate passed, as recorded below.

2. **Kernel-health false negative:** the existing M8 scanner accepted a fresh
   bare `KCSAN: data-race` diagnostic without another matching stack signature.
   A fixture running the original scanner reproduced this rejection-test
   failure. The scanner now includes KCSAN and blocked/hung task signatures.
   `check-m9-health.sh` verifies these, Oops/BUG/panic/KASAN/locking/free warnings,
   empty/lost capture and expected benign integrity-latch messages.
3. **Log-capture readiness/drain gap:** observing a child stdout fd did not prove
   `dmesg --follow-new` had started reading, and killing it immediately after the
   final phase did not prove all final messages had been read. M9 now requires
   observed start/end markers before testing/stopping capture. A fixture drops
   the first two marker writes to simulate late readiness and checks retry;
   failed marker delivery fails health. Marker-only logs cannot count as module
   runtime evidence. This is a code-audit finding, not a claim that M8's accepted
   VM log actually lost messages.

No production kernel correctness/security defect has been reproduced. There
is no broad refactor or changed security guarantee. During local verification,
the first new preprocess-exclusion assertion expected literal `static inline
bool`; target headers expand inline with attributes. The assertion now matches
the actual expanded constant-false body and independently requires no linked
fault symbols/object. Existing correctness assertions were not relaxed.

## Local evidence

Baseline `check-m8-local.py`: PASS, exit 0, before branch creation. Initial
M9 fault-only W=1 build: PASS. New local stress oracle and mocked harness/log
tests: PASS, including deliberate corrupt/misdirected units, missing restore,
worker failure, configuration rejection and M9 process-group timeout cleanup.
The complete inherited suite also passed during the first M9 run; only the new
preprocess assertion described above failed afterward.

The final combined `check-m9-local.py` run passed, exit 0, on 13 October 2026:
`build-m9-final-local.log`. It exercised implementation through `b0b6923`;
subsequent candidate changes record documentation only.

| Local check | Observed result |
| --- | --- |
| Five clean W=1 module configurations | PASS: M9 only, M4/M5/M9 together, M4/M5, M5, production. No driver-source warnings. |
| Production exclusion | PASS: no fault selector symbols or object; preprocessed constant-false stub; inherited tamper exclusion and imported-symbol checks. |
| C/static/ABI | PASS: strict checkpatch (zero errors/warnings/checks), CLI/helper compilation, native and compat object layouts. Runtime compat remains unexecuted. |
| Real store/snapshot code | PASS under ASan/UBSan: 100 cycles, allocation failures, stale/invalid generation and geometry, paired copies, wipe-before-free and allocation balance. |
| CLI/HTTP/UI | PASS: inherited M6/M8 CLI suites, 24 M7 HTTP/backend tests, three M8 HTTP tests, Node M7/M8 UI checks and static assets. |
| M9 oracles | Four tests PASS: complete/mixed versus corrupted/misdirected units, missing-restore detection, worker failure propagation, session timeout process-group cleanup. |
| Harness/health | PASS: all inherited harness tests, five observer/session tests, M9 full-SHA/config/mode/phase/failure fixtures, KCSAN/hung-task/locking/free/empty/lost-log rejection, marker readiness/drain fixtures. |
| Syntax and tree | PASS: all Python bytecode, each shell script separately, git diff --check. |
| Known environment limits | GCC 15.2 versus target GCC 13.3 warning; pahole unavailable/version warning and BTF skipped without vmlinux. ShellCheck absent, NOT RUN. |

No push or merge occurred. The original M8 bundle in `Transfer/` remains
unchanged; an exact local `.git/info/exclude` entry keeps that unrelated binary
out of candidate status without changing repository-wide ignore rules.

## Changed-file inventory

| Files | Purpose |
| --- | --- |
| `Kbuild`, `include/secureram_fault.h`, `src/secureram_fault.c` | Conditional build, fixed site enum and one-shot privileged selector. |
| `src/secureram_control.c`, `src/secureram_security.c`, `src/secureram_store.c` | Seven guarded error boundaries; production constant false. |
| `tests/m9-stress.py`, `tests/m9-vm-phases.sh`, `tests/run-m9-vm-acceptance.sh` | Actual VM workloads, composed phases and one entry point. |
| `tests/check-m9-local.py`, `tests/check-m9-stress.py`, `tests/check-m9-vm-harness.sh`, `tests/check-m9-health.sh` | Local build/oracle/harness/health regression verification. |
| `tests/m5-vm-common.sh`, `tests/m6-observe.py`, `tests/m6-raw-io.py`, `tests/m7-http.py`, `tests/m8-snapshot.py` | M9 profile using the existing M8 version/features and tests; production fault exclusion. |
| `tests/m7-vm-session.py`, `tests/vm-report.sh` | M9 phase selection, timeout cleanup, marker synchronization and health fixes. |
| `README.md`, `docs/architecture.md`, `docs/development.md`, `tests/README.md` | Current milestone links, M8 merge reconciliation and unchanged production boundary. |
| `docs/m9-report.md`, `docs/m9-testing.md` | Baseline, invariants, audit, observed evidence, limitations and exact VM/bundle procedure. |

## Real Ubuntu VM acceptance: PASS

Executed on 14 October 2026 in the running `SecureRAM-Ubuntu` VirtualBox VM,
Linux `7.0.0-38-generic`, as checkout owner `rishik-grandhi` using sudo.
The Windows host's installed VBoxManage controlled the existing guest terminal;
the established `Transfer` shared folder carried Git bundles and evidence.
The initial safe probes were `whoami`, `uname -a`, `pwd` and `sudo -n true`.
SSH to NAT guest `10.0.2.15:22` timed out, and passwordless guestcontrol login
was rejected. Neither was needed after console access and one manual `sudo -v`.
No package installation, networking or SSH configuration changes were made.

Original candidate `b12988c5d0f2fa5b8c1e0fd5e6c3561d1e6db3f3` genuinely
failed run `20261014T135552Z-21598` at the boundary oracle described above.
The narrow test fix was committed as
`fde91b901946a71b0f8fc764c02cce5e57984049`, transferred by verified bundle,
and fast-forwarded into the clean guest checkout. No production code changed.
The complete entry point was then executed again with that literal expected SHA:

```sh
sudo -n env M9_EXPECTED_COMMIT=fde91b901946a71b0f8fc764c02cce5e57984049 \
  bash tests/run-m9-vm-acceptance.sh
```

Run `20261014T135851Z-23164` returned **exit 0, OVERALL PASS, all 45 groups PASS**.
Profile: quick, 32 I/O rounds, 12 lifecycle/race rounds, 10 load/use/unload cycles.
It includes all inherited M6/M7/M8 phases, raw I/O/ext4, 1/256 MiB capacities,
CLI/HTTP, full snapshot rollback, tamper/latch/recovery, the new concurrent I/O,
control races, key/snapshot stress, malformed UAPI, seven fault sites, production
exclusion and final cleanup. Focused local regression after the fix: five tests
PASS; earlier completed local validation was not repeated.

Fresh `dmesg.log` contains `M9-start-23164` and `M9-end-23164`, successful
mount/unmount and module unload records. Both `kernel-health-failures.log` and
`kernel-unrelated-review.log` are empty: no Oops, BUG, panic, warning, trace,
locking, hung-task or other scanner fault signature. Expected intentional
integrity-latch messages remain in evidence. Final independent guest checks
confirmed a clean checkout, absent module and device nodes, and no SecureRAM
mount. The harness also confirmed owned dashboard cleanup.

VM build warnings were limited to the compiler command-name mismatch
(`x86_64-linux-gnu-gcc-13` versus `gcc-13`, both Ubuntu GCC 13.3.0), unavailable
pahole and skipped BTF without vmlinux. No driver-source warnings were observed.
These are distinct from the prior WSL GCC-version limitation.

Both complete run directories remain in guest `.cache/m9-vm/` and on the host
under `.cache/m9-real-vm-20261014/m9-20261014-evidence/`. The host archive also
retains both launch transcripts, bundles and the independent postcheck. Raw
evidence stays outside Git; this report records its identity and interpretation.
SHA-256 of the passing run's unmodified files:

| Evidence | SHA-256 |
| --- | --- |
| `summary.txt` | `fc8bf4186c9b2250d4440d00faa5c0d62cfe5ecc59cbe9ade2d606b9bc8cde2c` |
| `dmesg.log` | `40018b286c83b324f860241a83070432c9aaff721859f894ee9ba1b289e2ae96` |

M9 satisfies its required quick-profile acceptance. Extended mode and the
optional diagnostic campaigns below were not executed. No push, merge or M10
work was performed.

Advanced KASAN/KCSAN/lockdep/kmemleak instrumentation, 32-bit compat execution,
provider-internal failures and exhaustive allocator/module-publication failures
remain unexecuted optional campaigns. Ordinary stress provides evidence for
the exercised paths, not mathematical race freedom, physical key erasure or
forensic leak absence. Runtime diagnostics must remain warnings/failures until
classified from real evidence; a custom diagnostic kernel is not mandatory.
