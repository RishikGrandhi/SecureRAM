# M10 reproduction and verification

M10 is isolated on `m10-performance-evaluation`, from main `35babfa`. Never
run this campaign on WSL or a machine holding needed SecureRAM data. All device
I/O is fixed to `/dev/secureram0`; the only other write target is an owned private
tmpfs regular file. No mkfs, discard, real disk target or drop_caches is used.

## Entry point

Install the Ubuntu `fio` package if absent (the recorded VM uses fio 3.36).
Build tools and running-kernel headers are inherited prerequisites. Authenticate
with `sudo -v` in the guest terminal. Transfer a Git bundle from the host via the
existing `Transfer` shared folder; verify it and switch the clean guest checkout
to the M10 branch. The reviewed full commit must match the delivered candidate.

```bash
sudo -n env M10_EXPECTED_COMMIT=<reviewed-40-character-SHA> \
  bash scripts/run-m10-benchmarks.sh --full
```

The default is full (5 trials, 5 seconds measured + 1 second warmup each).
`--quick` uses the same experiments with 3 trials and 2 measured seconds. The
runner refuses dirty/wrong-branch/wrong-commit checkouts, WSL, missing headers,
pre-existing nodes/module/fio and insufficient RAM. It does not install packages.
Whole campaign deadline is 45 minutes, fio stage 35 minutes, each fio process
45 seconds, lifecycle/demo stages 5 minutes. Timeout means failure, not partial
acceptance. Uninterruptible kernel faults can prevent userspace cleanup; never
force unload. Do not concurrently administer the device or run other benchmarks.

If I/O completed but a later stage failed, preserve the failed run and resume
only the remaining stages after the narrow fix:

```bash
sudo -n env M10_EXPECTED_COMMIT=<reviewed-fixed-SHA> \
  bash scripts/run-m10-benchmarks.sh --resume <original-run-id>
```

Resume requires a complete validated I/O matrix and passing original kernel
health, unchanged kernel/driver/ABI/CLI/inherited I/O helpers, identical benchmark
parameters and identical I/O function ASTs. It creates a new evidence directory,
copies raw I/O without modification, retains origin environment/commit/provenance,
and runs lifecycle/demos/final production/analysis/health/cleanup. The failed run
is never rewritten as PASS. This is not a general partial-trial resume facility.

`--confirm` is the separately designed 18-trial random-read scaling check:
1/2/4 jobs, 3 trials, 10 seconds measured plus 2 seconds warmup. It performs
production build, inherited raw checks, the focused I/O matrix, analysis,
kernel-health and cleanup only. Its summary never marks unexecuted lifecycle or
security stages PASS, and its results are not pooled with the primary campaign.

The entry point builds normal production, runs inherited direct raw-I/O checks,
initializes all data, runs a balanced seeded workload order, verifies exact
contents after each timed workload, measures lifecycle at two capacities,
executes existing test-only security demonstrations, restores a production build,
processes results, unloads and checks fresh kernel logs. It reuses the existing
M9 marker/health scanner (marker names retain `M9` for compatibility).

## Local checks

```bash
python3 tests/check-m10-local.py
bash -n scripts/run-m10-benchmarks.sh
bash tests/check-m9-health.sh
SR_MILESTONE=10 bash tests/check-m9-health.sh
bash tests/check-m9-vm-harness.sh
git diff --check
```

These are statistical/safety oracle and inherited harness tests, not runtime
acceptance. The complete M9 local build/static suite passed at the baseline.
No production kernel source changes require another full M9 VM campaign.

## Evidence and chart processing

Each private `.cache/m10-benchmarks/<run-id>/` contains `environment.json`,
`parameters.json`, `queue.json`, all `fio/*.json` and command/resource metadata,
stderr, lifecycle raw JSON, security logs, build logs, inherited raw log, fresh
`dmesg.log`, `status.tsv`, `summary.txt`, derived CSV and `analysis.md`.
`source-sha256.json` identifies raw inputs. STARTED/incomplete/error/missing or
duplicate trials cannot become accepted statistics. All outliers are retained.

The guest processor is standard-library-only. Generate the four report figures
from the copied run on a machine with matplotlib (no device/root access):

```bash
python3 tests/m10-analyze.py .cache/m10-benchmarks/<run-id> --plots
```

This regenerates all statistics from raw JSON and produces SVG and PNG pairs:
`sequential`, `concurrency-baseline`, `baseline-cpu`, `lifecycle`. The recorded
host workflow installs matplotlib into ignored `.cache/m10-plot-packages` and
uses the bundled Python with that directory on PYTHONPATH. No plotting dependency
is installed in the VM. The agent performs this postprocessing automatically
after copying evidence; it is not a manual benchmark step for the user.

Retain the complete raw run outside Git. Selected CSV, analysis, graphs and
raw-file hashes may be retained under `docs/evidence/m10/` for review. Graphs are
derived artifacts, never manually entered data. A replay needs the retained raw
run; CSV and raw hashes allow independent audit of the selected report.
After the concise evidence is retained, regenerate its figures independently:

```bash
python3 tests/m10-analyze.py docs/evidence/m10 --plot-csv
```

This mode renders the retained statistics and does not claim to revalidate raw
trial completeness. The full raw-JSON replay above performs that validation.

## Interpretation boundaries

Raw SecureRAM direct I/O avoids the block page cache. Buffered tmpfs is an
explicitly different architecture; its page cache is its storage. No comparison
isolates XTS, HMAC or blk-mq individually. Both targets have identical aggregate
regions, psync depth 1, requests, workers, seed and runtime. Regions are split
among jobs; total bytes transferred are time-based and deliberately differ.
fio's process CPU excludes the driver's worker; guest-wide CPU includes it and
unrelated work. Host contention remains a confounder. Sample SD across trials is
not a confidence interval. Detailed formulas and controls are in the report.
