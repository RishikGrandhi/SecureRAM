# M10 retained evidence

Primary results are 150 real fio trials (five per configuration) from
`20261014T185015Z-5889`, imported byte-for-byte into completed run
`20261014T191200Z-7182`. Lifecycle/security evidence belongs to the latter.
The separate `confirmation/` directory is run `20261014T191843Z-8451`:
18 real random-read trials, three per configuration, with longer windows.
No trials are deleted or pooled. See [the report](../../m10-report.md) for
exact commits, controls, results, interpretation and limitations.

`status.tsv` is an append-only transition log. Its initial NOT RUN records and
the health scanner's temporary fail-closed `FAIL: health review did not complete`
sentinel are expected before the final PASS record. `summary.txt` resolves the
last status per group. The initial aborted campaign remains an actual FAIL.

## Inventory

| Files | Meaning |
| --- | --- |
| `raw-results.csv`, `confirmation/raw-results.csv` | One parsed row per actual I/O trial; these are derived from fio JSON, not a replacement for it |
| `summary.csv`, `confirmation/summary.csv` | n/mean/median/min/max/sample SD for each metric and configuration |
| `comparison.csv`, `confirmation/comparison.csv` | Paired tmpfs/SecureRAM throughput-ratio descriptive statistics |
| `analysis.md`, `confirmation/analysis.md` | Automatically generated campaign tables; confirmation did not execute lifecycle operations |
| `lifecycle-raw.csv`, `lifecycle-summary.csv` | Ten raw timing records and all operation/capacity statistics |
| `memory.csv`, `structure-sizes.json` | Exact accounted allocation formulas and final production DWARF sizeof values |
| `environment.json`, `io-origin-environment.json`, `confirmation/environment.json` | Candidate, Ubuntu/kernel, tool versions and resource/CPU context; primary I/O origin is explicitly separate |
| `parameters.json`, `queue.json`, corresponding `confirmation/` files | Workload matrix, repetitions, windows, capacity and actual block queue settings |
| `io-provenance.json`, `initial-failed-summary.txt` | Preserved failed campaign and explicit validated reuse record |
| `source-sha256.json`, `confirmation/source-sha256.json` | SHA-256 of every raw fio JSON/meta input and primary lifecycle JSON |
| `raw-audit.json` | Verified 450 original/reused files identical; hash, matrix, command, units and driver-counter audit |
| `confirmation-comparison.csv`, `confirmation-comparison.md` | Separate primary/confirmation statistics plus every SecureRAM random-read sample |
| `summary.txt`, `status.tsv`, corresponding `confirmation/` files | Real VM stage results, not inferred runtime success |
| `dmesg.log`, `kernel-relevant.log`, `kernel-health-failures.log`, `kernel-unrelated-review.log`, corresponding `confirmation/` files | Scoped kernel-health evidence; empty failure/review files mean no entries |
| `inherited-raw.log`, `production.log`, `final-production.log`, corresponding `confirmation/` files | Inherited raw checks and exclusion phase logs; successful silent commands can have empty logs |
| `security-demo.json`, `security-demo.log` | Existing bounded confidentiality/integrity demonstrations; rollback/generation checked in lifecycle trials |
| `host-primary.csv`, `host-lifecycle.csv`, `host-confirmation.csv` | Periodic Windows resource observations across each campaign, including preparation; page input is not proof of pagefile swapping |
| `postcheck.txt`, `keeper-cleanup.txt` | Independent guest state check after confirmation and owned sudo keeper exit |
| `local-baseline.log`, `local-inherited-harness.log`, `local-final.log` | Previously completed baseline/harness checks and final targeted postprocessing verification |
| `archive-sha256.json` | Names, sizes and SHA-256 of preserved local bulk transfer archives |
| `figures/sequential.{svg,png}` | Working region and request-size effects |
| `figures/concurrency-baseline.{svg,png}` | Primary read/write 1/2/4-job behavior, separate target axes |
| `figures/baseline-cpu.{svg,png}` | Practical baseline gap and qualified whole-guest CPU context |
| `figures/lifecycle.{svg,png}` | Snapshot and selected key-operation timings |
| `figures/confirmation.{svg,png}` | Every primary/confirmation random-read trial with separate median lines |

Bulk fio JSON, per-trial command/resource metadata, stderr, lifecycle JSON and
build logs remain outside Git in host `.cache/m10-real-vm/m10-benchmarks/<run-id>`
and guest `.cache/m10-benchmarks/<run-id>`. Host `Transfer/m10-evidence.tar`,
`Transfer/m10-resumed-evidence.tar` and `Transfer/m10-confirm-evidence.tar`
preserve original exports. The original failed campaign remains available;
the last archive contains all three run directories. Keep these archives to
reproduce statistics from raw inputs, rather than only rerendering selected CSV.
No keys, plaintext buffers, password or arbitrary kernel-memory export is retained.

## Reproduction without rerunning the VM

From the repository root with Python and matplotlib installed:

```bash
python3 tests/m10-analyze.py docs/evidence/m10 --plot-csv
python3 tests/m10-compare.py docs/evidence/m10 --plots
```

These render from retained machine-readable data. Primary figures use mean ±
sample SD, n=5; confirmation shows all samples plus medians, n=5 versus n=3.
Zero-origin axes and separately labeled target scales are used. SD bars may
extend below zero mathematically and are clipped by the physical zero axis;
CSV retains their complete values. No confidence interval is implied.

For the stronger raw replay/audit, use the extracted archive:

```bash
root=.cache/m10-real-vm/m10-benchmarks
python3 tests/m10-analyze.py "$root/20261014T191200Z-7182"
python3 tests/m10-analyze.py "$root/20261014T191843Z-8451" --io-only
python3 tests/m10-compare.py docs/evidence/m10 --audit \
  "$root/20261014T185015Z-5889" "$root/20261014T191200Z-7182" \
  "$root/20261014T191843Z-8451"
```

The comparison helper is deliberately specific to this 64 MiB, 1/2/4-job
confirmation design; it is not a general benchmark acceptance framework.
Plotting used host Python, matplotlib 3.11.2 and NumPy 2.5.4 in an ignored local
package directory; the VM statistics processor needs only Python's standard library.
