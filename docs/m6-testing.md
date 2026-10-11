# M6 testing and VM acceptance

**M6 runtime acceptance: NOT RUN.** M1-M5's completed VM results remain historical
evidence. WSL builds and local mocks do not establish M6 kernel runtime behavior.

## Local checks

Run from a Linux checkout. The local runner never loads a module, opens a device,
formats a filesystem or requests sudo. Provide an existing prepared header tree
and its official checkpatch script; no package installation is performed:

```sh
python3 tests/check-m6-local.py --kdir /path/to/prepared/headers \
  --checkpatch /path/to/kernel/scripts/checkpatch.pl
```

The runner builds clean combined M4/M5, M5-only and production variants with W=1,
requires MODPOST/link success, inspects symbols/strings/preprocessed control
dispatch/object code, and checks imports against Module.symvers. Production is
last. It strictly builds the CLI and old helper, runs real help/version/argument
tests plus a separately linked syscall fixture, parses JSON with Python's json,
and checks UAPI sizes/offsets/numbers for LP64/ILP32 with and without M5_TEST.
The mocks verify missing/permission/identity/ABI/feature errors, all state names,
u64 JSON bounds, malformed/missing version handling, transition errors and random
key protection/wiping after short reads, EINTR, getrandom and ioctl failures.

Strict checkpatch covers kernel/UAPI/CLI and the historical C helper. The ABI
fixture excludes only the known C11 `_Static_assert` CAMELCASE false positive.
Every shell file receives its own `bash -n`; all Python helpers are byte-compiled.
ShellCheck runs if installed. Logs are ignored `build-m6-*.log` files. The runner
ends with `git diff --check`; inspect environmental build warnings separately.

`bash tests/check-m6-vm-harness.sh` runs all actual M6 phase functions with explicit
mocks for device/module/build operations. It exercises parameter propagation,
1/64/256 MiB conversion, invalid/missing/oversized capacity, literal device
targets, ext4 redirections, mounted busy failures, unmount/remount and comparison,
generation flow, production/test/final phases, owned cleanup after an injected
failure, refusal of an unsafe unmount, ledger transitions, missing dmesg, summary
failure and evidence path guards. Real file operations use a temporary directory;
no device operation is executed. It also runs the historical M5 self-test.
Ownership guard/command routing is mocked; real sudo/runuser permissions still
need VM validation. The mocks do not verify real kernel ioctls or crypto.

The harness self-test also invokes `check-m6-observe.py`, which runs the actual
Python statistics assertions against synthetic observations. It requires invalid
schemas, missing counter increments, counted failed I/O, counter resets on destroy,
and initialization WRITE accounting to fail. This tests the assertion code as well
as shell routing; it does not substitute for real kernel accounting evidence.

## One command for the disposable Ubuntu VM

After review and a separately authorized commit/push, check out that exact M6
commit on `m6-cli-observability` in the disposable Ubuntu VM. The tree must be
clean, including nonignored untracked files; use the ordinary checkout owner.
Confirm this is the intended snapshot/disposable VM and no SecureRAM module,
nodes or mounts already exist. Headers must match its current running kernel.
From the reviewed checkout root, the one acceptance command is:

```sh
sudo env M6_EXPECTED_COMMIT="$(git rev-parse HEAD)" bash tests/run-m6-vm-acceptance.sh
```

The command substitutes the full SHA before sudo. The script requires 40 lower-case
hex characters and compares it with the full checked-out SHA. It rejects WSL.
This uncommitted candidate deliberately cannot pass the clean-checkout preflight.
The runner builds as SUDO_USER and uses root only for privileged VM operations;
neither the CLI nor the build embeds sudo. No automatic patch/retry exists.

## Phases and safety

1. Preflight verifies tools, branch, clean full commit, kernel/header match and
   absence of existing SecureRAM objects. Create builder-owned evidence under a
   unique `.cache/m6-vm/<UTC-time>-<pid>/`; start fresh dmesg capture.
2. Production: clean W=1 build and production-exclusion proof; strict CLI/helper
   builds; help/version; human/JSON NO_KEY; version 0.6.0, ABI 1, features 15;
   old malformed-ABI tests and production ENOTTY; stats zero/reserved output,
   EFAULT and passed-fd privilege. CLI load-random advances generation, without
   initialization WRITE accounting. Run the complete M4/M2 raw regression with
   M6 identity. Require all data counters to rise; an isolated direct 4096-byte
   read/write each adds exactly one request and 4096 bytes. Then check lock denial
   and data retention, destroy/idempotence/counter retention, rekey/full zero scan,
   ext4 sync/remount, and mounted EBUSY through both CLI and the ABI helper.
3. Combined test build: reuse every M5 ciphertext/tag/relocation assertion and
   its internal index/generation and M4 cursor/ciphertext diagnostics. Observe
   CLI human/JSON INTEGRITY_FAILED at each latch, exactly one new mismatch per
   case, no successful accounting for failed/rejected I/O, queryable stats,
   counter retention across destroy/fresh load, and full recovery zero scans.
   Three corruption cases finish NO_KEY at generation 6 with three failures.
4. Production capacity build: reject 0/257 MiB, then separate 1/256 MiB lifecycles
   with zero counters after each insertion, CLI status/load, full raw regression,
   exact single-unit accounting, destroy and unload.
5. Final clean production rebuild/exclusion proof and runtime ENOTTY, CLI/stats,
   raw/ext4/mounted busy regression, destroy and unload. Verify both device nodes,
   both sysfs objects and the module disappear. Inspect fresh kernel logs.

All raw/format commands bind to `/dev/secureram0`. There is no device argument.
Before destructive phases, shared M5 guards verify block/control type, major:minor,
root ownership/mode, version, size/unit, no holders, no mounts and no swap. Python
raw tests repeat identity checks and use O_EXCL/O_DIRECT. The ext4 helper uses
`nodiscard`; only its own mount is unmounted after major:minor revalidation.
Cleanup destroys/unloads only a module inserted by its phase, and refuses to
proceed after failed identity checks. It never forces unload.

Expect counter deltas at the driver request boundary, not one per application
syscall in general. The exact single-unit check uses synchronous, aligned direct
I/O in a quiescent disposable VM. Udev/filesystem probes and caches may contribute
other READ requests outside that interval. A counter mismatch stops the suite;
inspect evidence instead of weakening assertions or retrying until it passes.

## Evidence and failure classification

The final ledger prints PASS/FAIL/NOT RUN (an interrupted group can remain NOT
COMPLETED). A group becomes PASS only after its assertions finish. An unexpected
failure stops the phase sequence, retains logs, marks reached failures and attempts
safe cleanup. Kernel health cannot pass without captured runtime messages. M6
fails on any Oops/BUG/panic/KASAN/warning/call trace signature, retaining context
for classification. Expected injected integrity errors are not crash signatures.
Missing preflight/evidence prerequisites can reject before a ledger exists; no
runtime success is claimed in that case. A nonzero orchestration/cleanup result
cannot produce OVERALL PASS.

Review `main.log`, phase/build logs, `status.tsv`, `summary.txt`, `dmesg.log`,
kernel health logs and production symbols/strings. Evidence files are returned
to the checkout user; repeat runs use new directories and retain old logs.
Classify failures as driver, CLI, harness, or environment issues before any repair
and separately authorized rerun. Do not silently patch and rerun a failing VM.

Still outside normal acceptance: compat **runtime** ioctls, allocation/provider/
crypto fault campaigns, generation/counter exhaustion in a live kernel, targeted
pending-request races, lockdep/KASAN/kmemleak and physical memory erasure. Do not
infer these from compilation, source review, mocks, or normal round trips.
