# Verification by milestone

## M9 reliability acceptance

Use `run-m9-vm-acceptance.sh` only in the disposable Ubuntu VM with a clean
`m9-stress-hardening` checkout and reviewed full `M9_EXPECTED_COMMIT`.
It composes all M8 regressions plus deterministic concurrent I/O, lifecycle
races, snapshot/key torture, malformed UAPI, seven test-only fault sites and
load/unload loops. Quick/extended use the same implementations. See
[exact commands, evidence and limits](../docs/m9-testing.md).

`check-m9-local.py --kdir ... --checkpatch ...` runs all inherited local checks
plus fault-build/exclusion checks, stress oracle tests, mocked harness and fresh
kernel-health fixtures. It never accesses a block device or loads a module.
Local PASS is not real-kernel acceptance. Historical suites follow.

## M8 accepted candidate

Exact implementation commit `564d8bdb42558fc25db1a6648be9b695d424f9fc`
passed the complete automated Ubuntu VM suite and a separate real Firefox/manual
rollback session on Ubuntu 24.04.5 LTS, Linux 7.0.0-38-generic. Automated evidence
is retained in the VM at
`.cache/m8-vm/20261013T105429Z-3183`; its final result was `OVERALL PASS`.
The manual session independently proved a 4096-byte baseline/overwrite/restore
sequence through real dashboard actions, then delete, destroy and clean unload.
See [the M8 procedure](../docs/m8-testing.md) for exact evidence and boundaries.

Run `python3 tests/check-m8-local.py --kdir /path/to/headers --checkpatch
/path/to/scripts/checkpatch.pl` in Linux/WSL. See
[the M8 procedure](../docs/m8-testing.md) for exact commands and the separate
full-SHA VM harness. Local tests never load/access devices or install packages.

| File | Responsibility |
| --- | --- |
| `check-m8-core.py`, `m8-core.c` | Actual snapshot/store C linked to narrow allocator/scheduler shims; ASan/UBSan, two allocation failures, paired copy, stale/geometry rejection, 100 cycles, saturation and wipe-before-free. |
| `check-m8-cli.py` | Real parser and inherited syscall fixtures, fixed new ioctl dispatch, errors, JSON, backwards-compatible status/stats. |
| `check-m8-dashboard.py`, `check-m8-ui.js` | Real HTTP adapter with mocked CLI, strict new JSON/confirmations/authorization and pure UI gating. |
| `m8-preview.py` | Visibly labelled, unprivileged browser fixture. |
| `m8-snapshot.py` | Opt-in real-device full SHA rollback, UAPI/privilege/lock/invalidation/concurrency/repeated cycles, HTTP metadata/actions, integrity-latch check. |
| `run-m8-vm-acceptance.sh`, `m8-vm-phases.sh` | Profile 8 reuses all M6/M7 phases and evidence owner; adds M8 groups and unload with populated slot. |
| `check-m8-vm-harness.sh` | Actual new phase functions with mocks, ordering and fail-fast assertions. |

Only profile 8 changes runtime expectations to 0.8.0/features 31. Earlier
profiles keep exact historical driver expectations; rerun them at their original
commits. Shared local CLI/version checks track the current build. The inherited
Windows socket-bound test now accepts both reset and aborted connection errors
as closed excess connections, retaining its slot-bound assertion.

## M7 dashboard candidate

Dashboard 0.7.0 final tested candidate
`ff1b6df2444b134a3ee7005bc0a97b02a20b5fb5` passed complete automated M7 VM
acceptance and real Ubuntu Firefox acceptance. Kernel/CLI remain 0.6.0, ABI 1,
features 15. The earlier `08d1ade` candidate passed automated acceptance before
Firefox exposed `Origin: null` under the original `no-referrer` policy. The final
`same-origin` correction retained exact backend Origin enforcement and passed the
real regression re-test. See [m7-testing.md](../docs/m7-testing.md) for the evidence.

```sh
python3 tests/check-m7-local.py
# Retain the full M6 build/ABI/CLI regression too:
python3 tests/check-m6-local.py --kdir /path/to/prepared/headers \
  --checkpatch /path/to/kernel/scripts/checkpatch.pl
```

| File | Responsibility |
| --- | --- |
| `check-m7-local.py` | Python/static/JS checks, HTTP tests, mocked harness, individual shell syntax and diff whitespace; no device access. |
| `check-m7-dashboard.py` | Real HTTP server/socket tests with mocked CLI: auth, routes, parsing, exact referrer/Origin contract, fixed argv, deadlines/concurrency, traversal/symlinks, errors and shutdown. |
| `check-m7-ui.js` | Pure BigInt, state availability, sampled-delta and reset/gap assertions using Node. |
| `check-m7-vm-harness.sh`, `m7-harness-mocks.sh` | Actual M7 phase overrides in the M6 mocked harness, retaining historical M5/M6 failure/cleanup tests. |
| `check-m7-observe.py` | Actual HTTP/assertion client, failed-state counters/recovery, /proc loopback inspection and session-owner success/failure fixtures. |
| `m7-preview.py` | Separate unprivileged, labelled synthetic browser fixture; never a production option. |
| `run-m7-vm-acceptance.sh` | Explicit root/SUDO_USER, full M7 commit, clean branch, matching kernel/header, evidence and summary orchestration. |
| `m7-vm-session.py` | Own real backend lifecycle across reloads; capture startup credential only in memory; check listener and shutdown. |
| `m7-vm-phases.sh` | Small overrides of actual M6 phases: lifecycle through HTTP with independent CLI/status/accounting assertions retained. |
| `m7-http.py`, `m7-integrity.py` | Fixed API/host/auth/static/adversarial assertions and HTTP observations/recovery around unchanged M5 tamper cases. |

The shared profile 7 uses 0.6.0/features 15 and `.cache/m7-vm`; historical M5/M6
profiles and entrypoints retain their behavior. Local tests never load a module,
request sudo, open a block device or install dependencies. Browser screenshots
are fixture evidence only. The opt-in VM suite is destructive only to the
hardcoded, repeatedly validated `/dev/secureram0`; it accepts no device arguments.
All build products, screenshots and evidence logs stay ignored. Never save the
dashboard startup token in logs/screenshots. The accepted `08d1ade` VM run remains
historical evidence; `ff1b6df` is the final candidate that passed both its own
complete VM rerun and real Firefox browser acceptance.

## M6 acceptance

M6 runtime acceptance **passed** on commit
`50e11e6ddce88a986719ae2ef7ce972377a69e49` using Ubuntu 24.04.5 LTS and
Linux 7.0.0-38-generic. Evidence is retained at
`.cache/m6-vm/20261011T173837Z-14754` in the VM checkout. Follow
[m6-testing.md](../docs/m6-testing.md) for the procedure and recorded results.
The real CLI is `tools/secureramctl`; Python is used only for test assertions.

| File | Responsibility |
| --- | --- |
| `check-m6-local.py` | All clean compile/static/local mock checks; never loads devices. |
| `check-m6-cli.py`, `m6-cli-mock.c` | Real CLI parsing plus a separate syscall-mocked binary; JSON/errors/key wiping. |
| `check-m6-vm-harness.sh` | All M6 phases with mocked privileged calls; cleanup/failure/summary guards. |
| `check-m6-observe.py` | Actual Python statistics and failed-state assertions against valid/invalid synthetic observations. |
| `run-m6-vm-acceptance.sh`, `m6-vm-phases.sh` | Full-commit-pinned, fail-fast VM orchestration. |
| `m6-observe.py` | CLI JSON/human/state, counter/ABI/privilege and direct-I/O accounting assertions. |
| `m6-raw-io.py`, `m6-integrity.py` | Explicit 0.6.0 wrappers over M4/M2 raw and M5 integrity assertions. |
| `m5-vm-common.sh`, `vm-report.sh` | Shared guards, build/user ownership, ext4, cleanup, logs and summary. |

The shared shell profile preserves the M5 defaults (0.5.0/features 7) and M6
selects fixed 0.6.0/features 15. Historical raw/integrity Python entry points keep
their defaults. M6 injects observers into the existing tamper cases rather than
copying or weakening them. No additional production/test kernel hook was added.
The local harness test also executes the historical M5 mocked regression.

## Historical M1-M5 evidence

M1's successful VM lifecycle check is recorded in [its report](../docs/m1-report.md).
M2's exact manual commands and acceptance criteria are in
[the M2 VM test procedure](../docs/m2-testing.md).

M3 reuses it via [the M3 regression instructions](../docs/m3-testing.md), with
version `0.3.0` and M3 lifecycle messages. The successful M3 VM run is recorded
in [the M3 report](../docs/m3-report.md); the procedure remains reusable.

`m2-raw-io.py` is an opt-in destructive raw-I/O test **only for a freshly loaded,
unmounted `/dev/secureram0`**. It accepts no other path. Run it in the VM using
`sudo python3 tests/m2-raw-io.py` after following the identity/build checks.
The version allowlist is limited to plaintext M2 (`0.2.0`) and M3 (`0.3.0`);
M4 uses the separate state-aware tests below.

It checks geometry, every initially zeroed byte, a temporary-file round trip,
page-aligned direct I/O at multiple offsets, neighboring-block isolation,
concurrent disjoint transfers, EOF/beyond-end behavior, and flush. `O_EXCL`
refuses a mounted or exclusively held device. Runtime testing is not executed
by `make` or by the read-only environment checker. Reload before repeating it.

The guide additionally covers module ownership, unsupported discard, optional
ext4, unload/reload, and invalid capacity parameters. M2's completed acceptance
results are recorded in [the M2 report](../docs/m2-report.md); the guide remains
available for broader regression runs. Broad failure injection,
corruption tests, stress, and benchmarking remain separately scoped work.

For M4, follow [the M4 procedure](../docs/m4-testing.md). Compile `m4-control.c`
against the shared UAPI to `.cache/m4-control`. It supports query, ephemeral
random test-key loading, lock/unlock, destructive key removal and negative/busy
ABI checks. It is a test helper, not the final CLI; no test keys are committed.

`m4-raw-io.py denied` checks ENOKEY read/write-open failures. Its destructive
`active` mode requires a newly keyed, unmounted device, validates M4 identity,
uses exclusive direct I/O, reuses M2's data checks, and adds SHA-256/cmp and
opener-protection tests. Neither mode accepts an alternative device target.

The `M4_TEST=1` module build adds internal comparisons of actual backing bytes
and exercises split/cross-unit fragments during setup. It exports no memory.
Clean before switching variants. The M4 VM run executed all three hooks
successfully and completed a separate final production regression; see
[the report](../docs/m4-report.md).

For M5, follow [the M5 procedure](../docs/m5-testing.md). Runtime acceptance
passed on commit `5fabe544a3969732647e7d9962beed974b667901`. Reuse the
unchanged `m4-control.c` helper against ABI v1 (query now
returns features=7 and can report state=4). `m5-raw-io.py denied|active` reuses
M4/M2 regression functions with an explicit 0.5.0 identity requirement; calling
the M4 script directly retains its original 0.4.0 guard.

`m5-integrity.py production` checks the test ioctl is absent (ENOTTY).
`m5-integrity.py tamper` is destructive, requires NO_KEY on an M5_TEST=1 module,
and tests ciphertext/tag flips, valid-pair relocation, an unchanged caller read
buffer on authentication failure, state latch, continuing denial, invalid hook
inputs and passed-fd privilege, then destroy/reload/full-zero-scan recovery.
It opens only `/dev/secureram0` after mount/holder/identity checks, uses O_EXCL
and O_DIRECT, injects only with zero block openers, and finishes NO_KEY. Never
run the tamper suite on a mounted filesystem. The hook exposes no data/address.

`M5_TEST=1` independently enables these corruption hooks and an internal
index/generation MAC binding check. Combine `M4_TEST=1` to also exercise the
earlier ciphertext/fragment checks; clean before switching builds. A production
build omits every tamper handler, test command case and M4/M5 test string.

Compile-only `abi-layout.c` checks the original command numbers, sizes/offsets
and new test payload for -m64/-m32. Build it with -DSECURERAM_M5_TEST for the
test ABI; omit that define for the production header surface. See
[development commands](../docs/development.md#build-and-static-inspection).
These checks and Python/shell syntax checks do not load a module or establish
runtime crypto, tamper, race, fault-injection or compat behavior.

## Automated M5 VM acceptance

After committing the reviewed candidate and checking it out cleanly in the
disposable Ubuntu VM, run the structured harness from the repository root:

```sh
export M5_EXPECTED_COMMIT=$(git rev-parse HEAD)
sudo --preserve-env=M5_EXPECTED_COMMIT bash tests/run-m5-vm-acceptance.sh
```

The top-level script requires invocation through `sudo` by the ordinary checkout
owner. It builds as that user and performs only lifecycle/device operations as
root. It requires the `m5-integrity-tamper-detection` branch, a clean worktree and
headers matching `uname -r`. The command above pins the reviewed full commit
hash and preserves only that variable through sudo.

The runner calls four readable phases: production, combined M5/M4 tamper,
production capacity limits, and final production regression. Shared identity,
query, build, mount ownership and cleanup functions live in `m5-vm-common.sh`.
Every destructive operation remains hard-coded to `/dev/secureram0`; no device
argument or fallback exists. The guard checks block/control type and major:minor,
root ownership/mode, version 0.5.0, 4096-byte logical size, exact expected
capacity, holders, mounts and swap before raw I/O, formatting, key changes or
corruption. Mounted tests separately bind the owned mount point to the same
major:minor. Cleanup unmounts only a mount created and revalidated by the harness,
then destroys the key and unloads only a module inserted by that phase.

Evidence is retained under a unique `.cache/m5-vm/<UTC-time>-<pid>/` directory:
the main transcript, four phase logs, build logs, fresh dmesg stream, production
symbol/string inspection, relevant kernel messages, unrelated fault/warning indicators,
status ledger and final summary. Ephemeral readback files are compared and removed;
keys, tags and data bytes are never printed. The evidence subtree and new run are
owned by the ordinary checkout user with owner-only permissions; root can write
during privileged phases, and finalization returns generated files to that user.
The runner repairs ownership of this exact subtree from earlier sudo runs without
deleting history. Every summary item starts `NOT RUN`, becomes `NOT COMPLETED`
when reached, and changes to PASS only after its complete assertion group succeeds.
A trapped command failure marks its active group FAIL. Later groups and kernel
health without runtime evidence remain `NOT RUN`.

`check-m5-vm-harness.sh` is a non-destructive, non-root regression for strict
capacity conversion, readonly-scope cleanup, status transitions and shell-syntax
diagnostics. It also executes the production ext4 control-flow helper with mocks,
checking the fixed SecureRAM target, `nodiscard`, mount/busy/unmount/remount order
and file persistence without loading a module or accessing a block device.

The harness automates the production build/absence proof, NO_KEY/ABI checks,
negative control tests, full raw suite, lock/unlock retention, destroy/rekey,
ext4 EBUSY/remount, all three bounded corruption cases and recovery, 1/256 MiB
lifecycles, invalid 0/257 parameters, final production raw/ext4 regression,
node disappearance and fresh kernel-log screening. The failed-unit sentinel test
proves only that the failed unit is not released; it does not claim whole-request
read atomicity.

A human must still select and snapshot the disposable VM, ensure the checkout is
the intended reviewed commit, supply sudo authority, watch for environmental
problems, and review retained warnings/log context before recording acceptance.
The allocation/provider/crypto fault campaigns, pending-request races, compat
runtime ioctls and lockdep/KASAN/kmemleak diagnostics listed in the manual M5
procedure remain outside this normal harness. The normal automated M5 acceptance
completed successfully on Ubuntu 24.04.5 LTS, Linux 7.0.0-38-generic; evidence
was retained in `.cache/m5-vm/20261011T140342Z-10296` in the VM checkout.

The first automated VM attempt on candidate `093ca58` stopped before module
insertion because of harness ownership and Bash scope defects. Its production
build/exclusion result is useful build evidence, but it is not an M5 runtime
failure or an acceptance run.
The second attempt on `2d2816f` passed the production runtime through destroy/
rekey, then stopped at a harness redirection defect before ext4. The completed
run on `5fabe54` supersedes those incomplete attempts for acceptance evidence.
# M10 evaluation tooling

`scripts/run-m10-benchmarks.sh` is the opt-in VM entry point. `m10-benchmarks.py`
collects fio/lifecycle/security evidence; `m10-analyze.py` validates completeness,
generates statistics and optionally renders matplotlib charts. `check-m10-local.py`
tests measurement aggregation, failed-trial rejection and fixed target controls
using explicitly synthetic fixtures. See [the M10 procedure](../docs/m10-testing.md).
