# M10 machine-derived results

18 I/O trials; 3 per configuration. All retained.

Means below use sample standard deviation; no exclusions. MiB = 1048576 bytes.

Fastest SecureRAM: randread, 4 KiB, 64 MiB region, 1 jobs: 88.46 MiB/s (SD 73.87).
Slowest SecureRAM: randread, 4 KiB, 64 MiB region, 2 jobs: 8.61 MiB/s (SD 1.81).

| Target | Workload | KiB | Region MiB | Jobs | Mean MiB/s | SD | Mean us | Guest busy % |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| secureram | randread | 4 | 64 | 1 | 88.46 | 73.87 | 103.26 | 7.08 |
| secureram | randread | 4 | 64 | 2 | 8.61 | 1.81 | 927.42 | 19.79 |
| secureram | randread | 4 | 64 | 4 | 9.00 | 0.73 | 1735.33 | 24.55 |
| tmpfs | randread | 4 | 64 | 1 | 1339.61 | 136.96 | 2.35 | 5.96 |
| tmpfs | randread | 4 | 64 | 2 | 2038.42 | 53.27 | 3.01 | 5.92 |
| tmpfs | randread | 4 | 64 | 4 | 2609.15 | 414.38 | 4.85 | 30.34 |

## Comparison and scaling

Paired tmpfs/SecureRAM throughput ratios include filesystem/direct-mode and block-stack differences. They do not isolate encryption or HMAC.
- randread 4 KiB / 64 MiB / 1 jobs: 37.90x (SD 46.47).
- randread 4 KiB / 64 MiB / 2 jobs: 243.08x (SD 45.12).
- randread 4 KiB / 64 MiB / 4 jobs: 288.78x (SD 28.93).
randread: 1 jobs 88.46 MiB/s (1.00x 1-job), 2 jobs 8.61 MiB/s (0.10x 1-job), 4 jobs 9.00 MiB/s (0.10x 1-job). Highest observed mean at 1 jobs; this is not a proven global saturation point.

## Lifecycle (milliseconds)

| Capacity MiB | Operation | n | Mean | Median | Min | Max | SD |
|---:|---|---:|---:|---:|---:|---:|---:|

## Variability and limitations

Throughput CV >10% configurations (retained, no exclusions):
- secureram randread 4096 bytes, region 67108864, 1 jobs: CV 83.5%
- secureram randread 4096 bytes, region 67108864, 2 jobs: CV 21.1%
- tmpfs randread 4096 bytes, region 67108864, 1 jobs: CV 10.2%
- tmpfs randread 4096 bytes, region 67108864, 4 jobs: CV 15.9%

Snapshot create allocates/copies the whole ciphertext/tag pair; restore copies it; delete wipes/frees it. Load includes CLI startup, protected randomness, key setup and whole-medium authenticated-zero initialization. Destroy timing includes a populated snapshot. Lock/unlock is a batch mean for a pair, not isolated syscall latency.

Guest CPU uses /proc/stat deltas over fio startup, ramp and measurement, excluding later validation. It includes kernel worker and unrelated guest work. fio CPU excludes the asynchronous kernel worker. No per-crypto CPU attribution is supported. Guest steal may underreport host contention in VirtualBox. No swap deltas were accepted. Host observations and short virtualized windows limit precision.

Memory CSV accounts ciphertext, tags, snapshot and two staging buffers only; kernel metadata, provider context, allocator rounding and page tables are extra. No exact resident memory claim is made.

Sequential IOPS are retained in CSV but throughput is the primary interpretation. Mean latency is weighted by operation counts, not an average of percentiles. Timed loops reuse initialized regions; working-set size is distinct from total bytes transferred. All security guarantees remain those of M9.
