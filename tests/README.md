# Verification by milestone

## Current M6 candidate

M6 runtime acceptance is **NOT RUN**. Follow [m6-testing.md](../docs/m6-testing.md).
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
