# M10 machine-derived results

150 I/O trials; 5 per configuration. All retained.

Means below use sample standard deviation; no exclusions. MiB = 1048576 bytes.

Fastest SecureRAM: write, 128 KiB, 16 MiB region, 1 jobs: 237.59 MiB/s (SD 138.65).
Slowest SecureRAM: randread, 4 KiB, 64 MiB region, 2 jobs: 6.63 MiB/s (SD 2.72).

| Target | Workload | KiB | Region MiB | Jobs | Mean MiB/s | SD | Mean us | Guest busy % |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| secureram | randread | 4 | 64 | 1 | 69.15 | 57.02 | 201.28 | 9.12 |
| secureram | randread | 4 | 64 | 2 | 6.63 | 2.72 | 1394.54 | 18.85 |
| secureram | randread | 4 | 64 | 4 | 9.08 | 1.62 | 1752.62 | 30.78 |
| secureram | randrw | 4 | 64 | 1 | 93.29 | 65.77 | 106.89 | 5.77 |
| secureram | randwrite | 4 | 64 | 1 | 58.29 | 53.52 | 262.23 | 8.62 |
| secureram | randwrite | 4 | 64 | 2 | 7.31 | 1.93 | 1117.92 | 19.83 |
| secureram | randwrite | 4 | 64 | 4 | 9.58 | 2.54 | 1707.80 | 27.76 |
| secureram | read | 4 | 64 | 1 | 112.78 | 50.76 | 43.82 | 5.65 |
| secureram | read | 128 | 16 | 1 | 149.46 | 122.13 | 1377.58 | 10.09 |
| secureram | read | 128 | 32 | 1 | 222.02 | 114.52 | 741.58 | 8.49 |
| secureram | read | 128 | 64 | 1 | 167.29 | 111.58 | 1110.81 | 9.75 |
| secureram | write | 4 | 64 | 1 | 80.03 | 61.30 | 99.65 | 7.16 |
| secureram | write | 128 | 16 | 1 | 237.59 | 138.65 | 922.30 | 6.99 |
| secureram | write | 128 | 32 | 1 | 206.40 | 108.21 | 906.77 | 8.57 |
| secureram | write | 128 | 64 | 1 | 208.64 | 90.27 | 747.42 | 9.62 |
| tmpfs | randread | 4 | 64 | 1 | 1032.65 | 218.06 | 3.13 | 12.00 |
| tmpfs | randread | 4 | 64 | 2 | 2071.17 | 188.10 | 3.03 | 6.42 |
| tmpfs | randread | 4 | 64 | 4 | 3103.46 | 977.84 | 4.34 | 15.43 |
| tmpfs | randrw | 4 | 64 | 1 | 1054.67 | 175.30 | 3.00 | 6.72 |
| tmpfs | randwrite | 4 | 64 | 1 | 965.54 | 242.57 | 3.43 | 11.90 |
| tmpfs | randwrite | 4 | 64 | 2 | 1441.23 | 470.79 | 5.10 | 19.14 |
| tmpfs | randwrite | 4 | 64 | 4 | 995.69 | 217.63 | 15.03 | 13.71 |
| tmpfs | read | 4 | 64 | 1 | 1393.00 | 355.66 | 2.42 | 7.15 |
| tmpfs | read | 128 | 16 | 1 | 2575.22 | 797.52 | 51.01 | 8.56 |
| tmpfs | read | 128 | 32 | 1 | 2833.33 | 460.56 | 43.94 | 5.49 |
| tmpfs | read | 128 | 64 | 1 | 3039.12 | 806.75 | 43.12 | 3.69 |
| tmpfs | write | 4 | 64 | 1 | 1425.62 | 85.81 | 2.25 | 3.74 |
| tmpfs | write | 128 | 16 | 1 | 2597.98 | 698.56 | 50.94 | 5.36 |
| tmpfs | write | 128 | 32 | 1 | 2405.33 | 755.68 | 55.38 | 10.82 |
| tmpfs | write | 128 | 64 | 1 | 2701.51 | 798.64 | 48.82 | 9.79 |

## Comparison and scaling

Paired tmpfs/SecureRAM throughput ratios include filesystem/direct-mode and block-stack differences. They do not isolate encryption or HMAC.
- read 4 KiB / 64 MiB / 1 jobs: 16.60x (SD 13.30).
- read 128 KiB / 64 MiB / 1 jobs: 23.57x (SD 11.23).
- write 4 KiB / 64 MiB / 1 jobs: 36.42x (SD 38.06).
- write 128 KiB / 64 MiB / 1 jobs: 14.85x (SD 5.78).
- read 128 KiB / 16 MiB / 1 jobs: 25.46x (SD 13.45).
- write 128 KiB / 16 MiB / 1 jobs: 15.86x (SD 10.58).
- read 128 KiB / 32 MiB / 1 jobs: 15.92x (SD 8.67).
- write 128 KiB / 32 MiB / 1 jobs: 15.33x (SD 9.31).
- randread 4 KiB / 64 MiB / 1 jobs: 51.57x (SD 58.05).
- randwrite 4 KiB / 64 MiB / 1 jobs: 51.36x (SD 53.48).
- randrw 4 KiB / 64 MiB / 1 jobs: 31.54x (SD 40.83).
- randread 4 KiB / 64 MiB / 2 jobs: 378.38x (SD 217.07).
- randwrite 4 KiB / 64 MiB / 2 jobs: 217.75x (SD 105.85).
- randread 4 KiB / 64 MiB / 4 jobs: 351.83x (SD 130.99).
- randwrite 4 KiB / 64 MiB / 4 jobs: 109.11x (SD 34.70).
randread: 1 jobs 69.15 MiB/s (1.00x 1-job), 2 jobs 6.63 MiB/s (0.10x 1-job), 4 jobs 9.08 MiB/s (0.13x 1-job). Highest observed mean at 1 jobs; this is not a proven global saturation point.
randwrite: 1 jobs 58.29 MiB/s (1.00x 1-job), 2 jobs 7.31 MiB/s (0.13x 1-job), 4 jobs 9.58 MiB/s (0.16x 1-job). Highest observed mean at 1 jobs; this is not a proven global saturation point.

## Lifecycle (milliseconds)

| Capacity MiB | Operation | n | Mean | Median | Min | Max | SD |
|---:|---|---:|---:|---:|---:|---:|---:|
| 16 | load_cli_ms | 5 | 50.4050 | 50.3877 | 32.4587 | 62.9674 | 11.5885 |
| 16 | create_ms | 5 | 12.9283 | 13.9392 | 6.7617 | 20.3248 | 5.5233 |
| 16 | restore_ms | 5 | 5.2437 | 5.2183 | 3.7034 | 6.9158 | 1.3342 |
| 16 | delete_ms | 5 | 4.1579 | 4.6034 | 3.3441 | 4.7421 | 0.7311 |
| 16 | destroy_with_snapshot_ms | 5 | 15.5054 | 12.6589 | 7.8806 | 28.6577 | 8.5874 |
| 16 | lock_unlock_pair_ms | 5 | 0.0118 | 0.0056 | 0.0027 | 0.0343 | 0.0130 |
| 64 | load_cli_ms | 5 | 205.5460 | 184.7411 | 102.6623 | 355.9927 | 92.9510 |
| 64 | create_ms | 5 | 126.5610 | 90.6488 | 34.6391 | 373.6279 | 141.3879 |
| 64 | restore_ms | 5 | 24.5491 | 23.4288 | 18.8661 | 30.9286 | 4.4624 |
| 64 | delete_ms | 5 | 20.2622 | 18.8938 | 16.5148 | 25.1081 | 3.9884 |
| 64 | destroy_with_snapshot_ms | 5 | 37.5886 | 37.4749 | 27.3046 | 43.3855 | 6.5042 |
| 64 | lock_unlock_pair_ms | 5 | 0.0081 | 0.0077 | 0.0043 | 0.0113 | 0.0029 |

## Variability and limitations

Throughput CV >10% configurations (retained, no exclusions):
- secureram randread 4096 bytes, region 67108864, 1 jobs: CV 82.5%
- secureram randread 4096 bytes, region 67108864, 2 jobs: CV 41.0%
- secureram randread 4096 bytes, region 67108864, 4 jobs: CV 17.8%
- secureram randrw 4096 bytes, region 67108864, 1 jobs: CV 70.5%
- secureram randwrite 4096 bytes, region 67108864, 1 jobs: CV 91.8%
- secureram randwrite 4096 bytes, region 67108864, 2 jobs: CV 26.4%
- secureram randwrite 4096 bytes, region 67108864, 4 jobs: CV 26.5%
- secureram read 4096 bytes, region 67108864, 1 jobs: CV 45.0%
- secureram read 131072 bytes, region 16777216, 1 jobs: CV 81.7%
- secureram read 131072 bytes, region 33554432, 1 jobs: CV 51.6%
- secureram read 131072 bytes, region 67108864, 1 jobs: CV 66.7%
- secureram write 4096 bytes, region 67108864, 1 jobs: CV 76.6%
- secureram write 131072 bytes, region 16777216, 1 jobs: CV 58.4%
- secureram write 131072 bytes, region 33554432, 1 jobs: CV 52.4%
- secureram write 131072 bytes, region 67108864, 1 jobs: CV 43.3%
- tmpfs randread 4096 bytes, region 67108864, 1 jobs: CV 21.1%
- tmpfs randread 4096 bytes, region 67108864, 4 jobs: CV 31.5%
- tmpfs randrw 4096 bytes, region 67108864, 1 jobs: CV 16.6%
- tmpfs randwrite 4096 bytes, region 67108864, 1 jobs: CV 25.1%
- tmpfs randwrite 4096 bytes, region 67108864, 2 jobs: CV 32.7%
- tmpfs randwrite 4096 bytes, region 67108864, 4 jobs: CV 21.9%
- tmpfs read 4096 bytes, region 67108864, 1 jobs: CV 25.5%
- tmpfs read 131072 bytes, region 16777216, 1 jobs: CV 31.0%
- tmpfs read 131072 bytes, region 33554432, 1 jobs: CV 16.3%
- tmpfs read 131072 bytes, region 67108864, 1 jobs: CV 26.5%
- tmpfs write 131072 bytes, region 16777216, 1 jobs: CV 26.9%
- tmpfs write 131072 bytes, region 33554432, 1 jobs: CV 31.4%
- tmpfs write 131072 bytes, region 67108864, 1 jobs: CV 29.6%

Snapshot create allocates/copies the whole ciphertext/tag pair; restore copies it; delete wipes/frees it. Load includes CLI startup, protected randomness, key setup and whole-medium authenticated-zero initialization. Destroy timing includes a populated snapshot. Lock/unlock is a batch mean for a pair, not isolated syscall latency.

Guest CPU uses /proc/stat deltas over fio startup, ramp and measurement, excluding later validation. It includes kernel worker and unrelated guest work. fio CPU excludes the asynchronous kernel worker. No per-crypto CPU attribution is supported. Guest steal may underreport host contention in VirtualBox. No swap deltas were accepted. Host observations and short virtualized windows limit precision.

Memory CSV accounts ciphertext, tags, snapshot and two staging buffers only; kernel metadata, provider context, allocator rounding and page tables are extra. No exact resident memory claim is made.

Sequential IOPS are retained in CSV but throughput is the primary interpretation. Mean latency is weighted by operation counts, not an average of percentiles. Timed loops reuse initialized regions; working-set size is distinct from total bytes transferred. All security guarantees remain those of M9.
