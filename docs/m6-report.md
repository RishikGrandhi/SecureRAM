# M6 — Management CLI, runtime statistics and observability

## Design and acceptance status

Baseline: clean `main` at `7763df1f9eb324bc3c8cb50a61d3afab3165eca3`.
M1-M5 runtime evidence remains in the historical reports. M6 is an uncommitted
0.6.0 candidate on `m6-cli-observability`; VM acceptance is **NOT RUN**.

Preserve the M5 block/security/store/control boundaries and all state/ioctl
numbers. Add a read-only GET_STATS command, leaving the 48-byte QUERY unchanged.
ABI stays 1; STATS=8 makes the normal feature mask 15. No GUI or new test ioctl.

The device owns a separate statistics object, initialized before publication and
freed after work drains. A short independent spinlock protects five u64 counters
and provides coherent snapshots on both 32-bit and 64-bit kernels. This is chosen
over independent atomic64 counters so request/byte pairs cannot be torn across
a snapshot. No allocation, user-copy, crypto, completion or sleeping occurs under
this lock. It is never held while acquiring any other lock. The security context
borrows the object for actual MAC mismatch accounting; key clear does not clear it.

Successful READ/WRITE requests are accounted once, after the final transfer
result is known and immediately before blk_mq_end_request. All their bytes count;
a failed request counts neither requests nor bytes, including earlier successful
units in that failed request. FLUSH, rejected dispatch/open, ioctls and fresh-zero
initialization do not count. A MAC mismatch increments integrity_failures exactly
where detected, before latching INTEGRITY_FAILED. Subsequent rejected I/O does not
increment it. Each counter saturates at U64_MAX instead of wrapping. Counters
survive lock/destroy/rekey and reset on module reload. They are diagnostic only.

GET_STATS returns an 80-byte, output-only payload: the existing 16-byte header,
five aligned u64 counters and three reserved u64 fields, all reserved bytes zero.
It is available in NO_KEY, ACTIVE, LOCKED and INTEGRITY_FAILED, without mutating
state or draining I/O. QUERY and GET_STATS are separate snapshots.

The dependency-free C CLI uses the public UAPI and the existing root-only control
device. It validates the opened character device against sysfs. Help/version
need no device. Status reads the loaded module version from sysfs (or reports it
unavailable), separately from the compiled CLI version. JSON uses fixed fields.
load-random disables dumps and locks its buffer before getrandom, handles EINTR
and short reads, and explicitly wipes the whole key payload immediately after
the ioctl and on every error exit. Failure to protect memory aborts before key
generation. No key input/export/persistence or internal sudo/setuid is added.

The VM harness reuses M5 identity/lifecycle/ext4 and raw/tamper regression logic,
with historical defaults retained. M6 adds CLI, JSON, counter, failed-state and
module-lifetime assertions. A local mocked suite must exercise orchestration,
early failure, cleanup and evidence handling before a real VM invocation.

## Security limits

M6 changes no cryptographic guarantee. M5 remains Encrypt-then-MAC, not AEAD;
there is no same-unit same-generation replay prevention, whole-request atomic
plaintext release, malicious root/kernel/hypervisor protection, crash-persistent
anti-replay or physical RAM erasure guarantee. Userspace key protection cannot
exclude a malicious privileged observer or every transient CPU/compiler copy.
Statistics neither authorize I/O nor clear the failure latch.

## Public UAPI and compatibility

| Command | Value (x86 ILP32/LP64) | Payload |
| --- | --- | --- |
| QUERY | `0x8030b700` unchanged | 48-byte output status. |
| LOAD_KEY | `0x4058b701` unchanged | 88-byte key input. |
| LOCK | `0x4010b702` unchanged | 16-byte header. |
| UNLOCK | `0x4010b703` unchanged | 16-byte header. |
| DESTROY_KEY | `0x4010b704` unchanged | 16-byte header with DESTROY flag. |
| GET_STATS | `0x8050b705` new | 80-byte output-only statistics. |

GET_STATS uses `_IOR(0xb7, 0x05, struct secureram_ioc_stats)`. Header offsets
0/4/8/12 hold ABI version=1, size=80, flags=0 and reserved=0. Aligned u64 values
start at offsets 16/24/32/40/48 for read_requests/write_requests/read_bytes/
write_bytes/integrity_failures; reserved u64[3] occupies offsets 56..79. There
are no pointers, native `long`, variable lengths or uninitialized padding.
`compat_ptr_ioctl` remains sufficient because layouts and ioctl values match.
Unauthorized callers receive EPERM before dispatch; failed output copy is EFAULT.
There is no stats-reset/set ioctl and no counter in the state-transition logic.

NO_KEY=0, PREPARING=1, ACTIVE=2, LOCKED=3, INTEGRITY_FAILED=4 and internal DYING=5
are unchanged. Feature bits XTS=1, LOCK=2, INTEGRITY=4 remain, with STATS=8 added.
QUERY remains 48 bytes, including zero reserved fields. New CLI status works with
older compatible responses; stats returns exit 3 if STATS is not advertised.
Loaded module version is read from sysfs rather than inserted into an old payload.
The existing M5_TEST tamper ioctl `0x4028b770` remains opt-in and unchanged.

The design follows official [ioctl compatibility guidance](https://docs.kernel.org/driver-api/ioctl.html)
and [spinlock guidance](https://docs.kernel.org/locking/spinlocks.html), checked
alongside the installed prepared target headers. Compatibility assertions are
compiled for both -m32 and -m64; this is not compat runtime testing.

## Counter definitions and observation limits

| Field | Meaning |
| --- | --- |
| read_requests | READ requests whose complete SecureRAM transfer succeeded. |
| write_requests | WRITE requests whose complete SecureRAM transfer succeeded. |
| read_bytes | Sum of full request lengths for those successful READs. |
| write_bytes | Sum of full request lengths for those successful WRITEs. |
| integrity_failures | Actual ciphertext/tag authentication mismatches detected in security_read. |

The accounting point is immediately before successful blk-mq completion, after
every unit succeeds. There is a small interval before the block core is notified;
no request is dereferenced after completion. Request bytes widen to u64 before
accumulation. Subtraction-before-add saturation prevents wrap or narrowing loss.
GET_STATS takes a snapshot across all counters. A mismatch update and the ensuing
state latch are distinct operations, so separate status/statistics reads are not
a combined atomic observation. All security decisions continue to use M5 state,
admission and control synchronization, never a counter.

Filesystem/page-cache activity may avoid or add requests. One userspace read/write
does not generally equal one block request. Delivered FLUSH succeeds without
counting; initialization, control calls, failed/rejected I/O and denied opens do
not count. Later units failing in a multi-unit request suppress accounting for
that entire request, without promising rollback of earlier unit transfers.

Counters and their lock are embedded in the device; there is no allocation on
increment/query, timer, worker, reset interface or new teardown resource. The
security pointer remains valid until worker drain and security teardown finish.
All values survive key destroy/rekey, reset only on module reload and saturate
independently at U64_MAX. They are not persistent telemetry or a security boundary.

## CLI and test architecture

[The tool guide](../tools/README.md) records every exact command, human/JSON
example, schema and exit code. Exit codes are 0 success, 1 operation/access error,
2 invalid usage, and 3 ABI/unsupported-feature error. The CLI never needs Python.
Its only production device is the existing root-only `/dev/secureramctl`.
The separate historical helper remains useful for negative ABI/passed-fd tests;
it is not called by the production CLI. The new CLI sends existing key ioctls.

The four VM phases are production CLI/raw/ext4, combined M4/M5 tamper plus M6
observations, production capacity boundaries, and final production regression.
M5 guards, identity checks, lifecycle, ext4 and reporting are reused. Historical
version/features defaults stay 0.5.0/7; M6 explicitly selects 0.6.0/15. M5's Python
tamper assertions accept a version/features/loader/observer extension, preserving
all original checks. M6 observers run at mismatch, destruction and recovery.
No additional kernel tamper hook is introduced. See [the full procedure](m6-testing.md).

The mocked shell test executes those actual phase functions, substituting only
the environment/device operations. It also calls a Python test that executes the
actual statistics assertions with good and deliberately bad observations. The
CLI has a separately linked syscall fixture for identity/ABI/random/error/wipe
checks; no fixture selection is compiled into the production binary.

## M5 harness defect audit

| Previous defect / risk | M6 treatment and local evidence |
| --- | --- |
| Short/full SHA mismatch | Full `git rev-parse HEAD`; mandatory 40-hex M6 pin; full comparison. Self-test rejects empty/short/invalid pins. |
| Root-owned cache/evidence | Builder creates cache/run directories; builds use runuser SUDO_USER. Logs are returned to that user. Repeated runs retain separate directories; evidence roots/symlinks are guarded. Real sudo ownership still awaits VM validation. |
| `set -u` use before assignment | Dependent local assignments split; capacity supplied explicitly. Self-test runs under nounset. |
| Readonly/local collisions and dynamic scope | Distinct function-local capacity/result names; historical collision self-test retained. |
| Dangling redirections | Each shell file parsed separately; actual shared ext4 redirections/comparisons execute on temporary files in the mock. |
| Misleading early PASS | Ledger starts NOT RUN, marks started groups, and requires every category PASS. Phase/cleanup/orchestration errors force failure. Finalization failure has its own mock. |
| Missing/truncated dmesg | Missing capture is NOT RUN; lost capture is FAIL; never grep a nonexistent log. M6 rejects warning/fault signatures. Synthetic missing/lost/warning cases execute locally. |
| `bash -n file1 file2` mistake | Loop invokes a separate `bash -n` process for each of all shell scripts. |
| Dynamic shell parsing | No eval, bash -c, sh -c or generated shell-command strings added. Fixed Python JSON assertions use ordinary argv. |
| Conditional errexit trap | Guard/unsafe-unmount failures explicitly return, including when called under if/cleanup with errexit disabled. Self-test requires no unmount after refusal. |

## Adversarial source review

Two source-review passes covered the implementation and the final integrated
candidate. Concrete findings were fixed before handoff: a post-load munlock error
could report success; shared Bash guards relied on errexit inside conditionals;
cleanup errors after completed groups could leave misleading PASS output; and a
lost dmesg collector needed to invalidate kernel-health evidence. The new tests
exercise these paths. CLI prctl arguments use explicit long values, and generated
preprocessed/checkpatch-cache artifacts are cleaned after inspection.

| Review area | Conclusion and limit |
| --- | --- |
| Numeric compatibility/layout | Existing ioctl values, QUERY/key/header sizes and state values unchanged; additive aligned 80-byte stats payload. Four ABI object builds validate x86 ILP32/LP64. |
| Accounting/concurrency | Only final successful READ/WRITE results count; the actual mismatch branch counts failures. Independent spinlock protects all u64 access, saturation and coherent pairs. No lock is nested beneath it. |
| Fail-closed behavior | M5 crypto, gate/drain, transition validation and failure latch are preserved. GET_STATS cannot reactivate or mutate state. |
| Secrets/JSON | Protected key generation precedes no secret input/output. Entire key payload cleared after ioctl and all ordinary error exits. Fixed JSON fields/version alphabet expose only metadata; fixture parses all states and u64 limits. |
| Privileges | Root 0600 control mode, initial-namespace CAP_SYS_ADMIN check and passed-fd check remain. No setuid, embedded sudo or runtime mock/test option. |
| Ownership/cleanup | Stats lifetime follows the enclosing device. Borrowed pointer outlives all users; no new allocation/unwind path. Harness cleanup refuses identity changes and retains original failure. |
| M5 regression | Raw suites reused; all ciphertext/tag/relocation, denial, buffer-sentinel, negative-hook and recovery assertions retained with historical defaults. No weakening of M5 crypto claims. |
| Production exclusion | Production symbols, strings, preprocessed source and object dispatch exclude M4/M5 hooks; test builds provide positive controls. Runtime ENOTTY still requires the VM. |
| Current assumptions | Current docs/CLI/harness use 0.6.0/features 15. Remaining 0.5.0/7 references belong to explicitly historical M5 defaults/evidence. |

This is source/build/mock evidence, not proof of runtime races, fault injection,
kernel crypto operation, physical erasure, compat runtime or VM acceptance.

## Recovery of the interrupted work

At the continuation request, the existing branch already contained kernel stats,
the additive UAPI/version/feature changes, the complete C CLI, M6 phase functions,
M5 reuse, CLI mocks, shell self-tests and most documentation. The full local build
suite had passed. No changes were discarded or restarted.

The remaining work completed after resumption was an additional stdlib-mocked
test of the actual Python statistics/tamper assertions, generation-artifact
cleanup in the local runner, the final UAPI/review/evidence documentation and
the final integrated verification/working-tree handoff. Runtime remains NOT RUN;
no commit, push, merge or real module/device operation was performed.

## Files changed

| Files | Purpose |
| --- | --- |
| `include/secureram_stats.h`, `src/secureram_stats.c` | Device-owned coherent, saturating counters. |
| `include/uapi/secureram.h`, `tests/abi-layout.c` | Additive GET_STATS/STATS and native/compat compatibility checks. |
| `include/secureram_block.h`, `src/secureram_block.c`, `src/secureram_control.c` | Success accounting, snapshot routing and privileged copy-out. |
| `include/secureram_security.h`, `src/secureram_security.c` | Borrowed stats pointer and actual mismatch increment. |
| `include/secureram_config.h`, `src/secureram_main.c`, `Kbuild` | Version/lifecycle metadata 0.6.0 and stats object linkage. |
| `tools/secureramctl.c`, `tools/Makefile`, `Makefile`, `.gitignore` | Production CLI and independent strict build/clean. |
| `tests/m5-vm-common.sh`, `tests/run-m5-vm-acceptance.sh`, `tests/vm-report.sh` | Reused profile, guards, ownership, cleanup and reporting. |
| `tests/m5-integrity.py`, `tests/m6-integrity.py`, `tests/m6-raw-io.py` | Retained regressions with explicit M6 observers/identity. |
| `tests/run-m6-vm-acceptance.sh`, `tests/m6-vm-phases.sh`, `tests/m6-observe.py` | Pinned VM phases and CLI/statistics assertions. |
| `tests/check-m6-local.py`, `tests/check-m6-cli.py`, `tests/m6-cli-mock.c`, `tests/check-m6-vm-harness.sh`, `tests/check-m6-observe.py` | Reproducible builds/static checks, CLI mocks, harness/statistics self-tests. |
| `README.md`, `docs/architecture.md`, `docs/development.md`, `docs/m6-report.md`, `docs/m6-testing.md`, `tools/README.md`, `tests/README.md` | Design, usage, UAPI, evidence and viva-ready explanations. |

## Observed local verification — 11 October 2026

Codex executed the local suite in Ubuntu under WSL2, kernel
`6.18.33.2-microsoft-standard-WSL2`. Compiled target: existing prepared Ubuntu
`7.0.0-38-generic` headers; compiler GCC 15.2.0. No module was inserted in WSL
or a VM and no real block/control device was accessed.

| Check | Observed result |
| --- | --- |
| Clean production W=1, MODPOST and link | PASS; version 0.6.0, hkdf dependency, matching target vermagic. |
| Clean M5-only and combined M4/M5 W=1 builds | PASS; positive controls for guarded hooks/diagnostics. |
| Strict real CLI and separate syscall fixture | PASS with C11, Wall/Wextra/Werror/Wconversion. |
| Real help/version/argument tests | PASS without a control device. |
| CLI fixture/JSON tests | PASS for public/unknown states, numeric u64 bounds, null version, access/identity/ABI/feature/state errors, short/EINTR random reads, protection and wipe paths. |
| Old C control helper | PASS strict build; runtime negative tests not run locally. |
| UAPI layout | PASS -m32 and -m64, each production/test headers; existing values and new 80-byte stats layout. |
| Checkpatch | PASS strict kernel/UAPI/CLI/helper; ABI fixture ignores only CAMELCASE for C11 `_Static_assert`. |
| Shell syntax | PASS; separate bash -n for every one of 12 shell files. |
| Python syntax | PASS; bytecode compilation of every Python helper. |
| M5 and M6 mocked harness | PASS; all four real M6 phase functions, capacities, CLI routes, mount/busy/remount, fail-fast, cleanup/refusal, early evidence/summary and pin guards. The printed synthetic phase failure is an expected assertion, not a VM failure. |
| Statistics assertion self-test | PASS; real schema/baseline/accounting/lifetime/tamper-observer code accepts valid fixtures and rejects injected invalid observations. |
| Production imports/surface | PASS; all unresolved kernel symbols exported by target Module.symvers. No crypto/store import added to block adaptation. No test strings/tamper symbols/dispatch in production; source and object code inspected. |
| ShellCheck | NOT RUN: not installed. No package installation attempted. |
| git diff --check | PASS, no output. |
| Ubuntu VM acceptance | NOT RUN; requires a reviewed, committed, clean checkout and disposable matching-kernel VM. |

Environmental warnings retained: target built with GCC 13.3.0 versus local
15.2.0; target pahole version 125 versus local unavailable/0; BTF skipped because
vmlinux is unavailable. No driver-source compiler warnings or MODPOST errors.
These warnings are not hidden and compilation is not runtime acceptance.

Evidence remains in ignored `build-m6-*.log` files: production/test/combined
builds, symbols, strings, object/preprocessed dispatch, imports/modinfo, CLI,
four ABI compilations, checkpatch, individual shell checks and harness self-test.
Generated preprocessed/checkpatch caches are removed after inspection; no
fixture/tamper interface is linked into the production management utility.
