# M10 performance evaluation: design and evidence

## Baseline and experimental contract

Started from clean `main` at `35babfa96367296b8e2451a3d028fb4a88610f99`.
The complete M9 local runner passed before creating `m10-performance-evaluation`;
`.cache/m10-baseline.log` retains the transcript. M9's accepted 45/45 real-VM
campaign is inherited, not repeated. No production change is planned.

This design was written before benchmark implementation and measurements.
Runtime acceptance and measured results are pending until recorded below.
Version 0.8.0, ABI 1 and production features 31 remain unchanged.

## Questions, variables and controls

All I/O uses fio psync, depth 1 per job, monotonic clock, deterministic seed
10000+trial, identical aggregate regions and disjoint worker slices. Production
SecureRAM uses raw O_DIRECT; tmpfs uses buffered pread/pwrite because its page
cache is its RAM storage. No drop_caches, filesystem formatting or real-disk
benchmarking. All trials are retained; no automatic outlier exclusion.

| Question | Independent variable | Controls | Measurement / interpretation |
| --- | --- | --- | --- |
| Sequential speed and request overhead? | read/write; 4/128 KiB requests | 1 job; default capacity; same region | MiB/s, latency, duration; larger requests amortize submission but retain per-unit crypto |
| Working-set sensitivity? | capacity/4, capacity/2, capacity | 128 KiB sequential read/write, 1 job | MiB/s; distinguish working set from transferred bytes in time-based loops |
| Random and mixed cost? | randread/randwrite/randrw 70% reads | 4 KiB, full region, 1 job | IOPS, MiB/s, weighted mean latency; all units initialized |
| Concurrency saturation? | 1/2/4 jobs, capped by vCPUs | random 4 KiB read/write; fixed aggregate size | aggregate throughput/IOPS, latency; no expectation of linear scaling |
| Practical RAM baseline gap? | SecureRAM vs private tmpfs file | same parameters except required direct mode | paired throughput ratio; includes different layers, never isolated crypto overhead |
| Snapshot cost vs capacity? | default/4 and default capacities | full A -> snapshot -> B -> restore -> full exact A | monotonic ioctl create/restore/delete milliseconds, correctness outside timing |
| Key lifecycle cost? | same two capacities | no open block users, protected CLI-generated keys | load CLI wall ms (includes process/random/HKDF/full encrypted-zero initialization); destroy ioctl ms |
| Resource cost? | same I/O configurations | record before/after /proc/stat and vmstat | guest busy/steal, swap deltas; includes worker and background guest activity, not crypto attribution |
| Memory cost? | capacity; snapshot absent/present | exact implementation allocations | C + C/4096*32, doubled with slot, plus 8192 staging and metadata/provider costs |
| Security properties observable? | existing M4/M5 test build | bounded private hooks only, no keys/backing export | internal backing comparison, EIO/latch, exact rollback, destroy/generation denial |

Full mode: 5 trials, 5 measured seconds plus 1-second warmup per fio case.
Quick mode: 3 trials, 2 measured seconds plus 1-second warmup, same matrix.
At 4 vCPUs there are 15 configurations per target (150 full I/O trials).
Case order alternates target order by trial; configurations are seeded-shuffled.
Each fio process has a 45-second timeout; whole runtime has a 35-minute timeout.
Control operations use 5 (full) or 3 (quick) repetitions per capacity.

## Environment and sizing rationale

Preflight observed SecureRAM-Ubuntu with 4 vCPUs, 6144 MiB configured RAM,
5920 MiB guest-visible RAM, approximately 4737 MiB available, zero swap used,
Linux 7.0.0-38-generic. Capture these again for each campaign. Default capacity
comes from include/secureram_config.h (64 MiB); use it only if a conservative
eight-capacity memory budget fits within one quarter of MemAvailable and tmpfs
has twice-capacity free. Otherwise reduce by powers of two, minimum 4 MiB.
Current expected regions: 16/32/64 MiB, lifecycle capacities: 16/64 MiB.
These are derived from actual limits, not arbitrary transfer volumes.

fio was absent; its Ubuntu package is justified for established JSON throughput,
latency and worker accounting. Capture installed version. See the primary
[fio documentation](https://fio.readthedocs.io/en/latest/fio_doc.html) for psync,
numjobs, offset_increment, runtime, ramp_time and JSON semantics. brd is present,
but tmpfs is selected to keep writes confined to the existing fixed SecureRAM
device and a newly created private file. It is a practical use-case baseline,
not a block-stack equivalent. Never label the gap encryption-only overhead.

## Security and memory boundaries

There is no supported encryption-only configuration in the current production
architecture. Component isolation is SKIP: no security-disable switch or altered
crypto build will be added. Normal benchmark builds exclude all test hooks.
Separate M4/M5 builds demonstrate internal comparisons and bounded corruption.
Successful writes with M4_TEST prove actual stored bytes equal cipher staging
and differ from plaintext; bytes are never exported. This is a deterministic
demonstration, not a cryptographic proof or defense against a hostile kernel.

`secureram_store_init` allocates C ciphertext bytes and 32 bytes per 4096-byte
unit with vzalloc. Snapshot create allocates and copies another complete pair,
even for logically empty units. Restore copies the pair; delete explicitly zeros
then frees it. Two kzalloc staging units add 8192 bytes. Tag overhead is exactly
0.78125% of C; one snapshot adds 100.78125% of C. The live security/device structs
embed slot metadata, counters, locks and pointers. blk-mq allocates 64 requests
with `sizeof(struct secureram_request)` private bytes each, plus kernel request,
tag, disk/queue and ordered-workqueue allocations. Crypto transform/request and
shash descriptor costs depend on the chosen provider and kernel configuration;
the latter is `sizeof(struct shash_desc)+crypto_shash_descsize(mac)`. Allocator
rounding, vmalloc page arrays/page tables and slab overhead are additional.
These formulas are accounted payload allocations, not a claim of total resident
footprint. Guest MemAvailable deltas are noisy context, not per-driver accounting.

## Evidence policy

Use `.cache/m10-benchmarks/<run-id>/`: environment and parameters, every fio JSON,
resource snapshots, lifecycle JSON, security logs, fresh kernel log and status,
derived CSV/statistics and graphs. Record failed campaigns unchanged. Report mean,
median, min, max, sample standard deviation and sample count. Flag coefficient
of variation above 10%; never silently exclude it. Host load/swap is observed
from the host separately; guest counters cannot rule out host contention.
No timing, PASS, security claim or final conclusion is entered before execution.
