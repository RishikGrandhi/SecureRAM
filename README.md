# SecureRAM

SecureRAM is a university Operating Systems project implementing a volatile
Linux block device backed by memory owned by a kernel driver.

**M8 runtime and real Firefox acceptance passed** on exact implementation commit
`564d8bdb42558fc25db1a6648be9b695d424f9fc` in Ubuntu 24.04.5 LTS with Linux
7.0.0-38-generic. Driver, CLI and dashboard are 0.8.0, ABI 1, production features
31. The automated suite passed every group; a separate real-browser session proved
snapshot create, restore and delete, with a known 4096-byte block restored to its
baseline SHA-256 and zero authentication failures. One volatile snapshot
captures ciphertext and matching HMAC tags under the current key generation.
Create/restore require ACTIVE and closed, unmounted block users; destroy/unload
wipe the slot. No plaintext disk snapshot, persistence or filesystem-consistency
guarantee is introduced. See the [M8 design/evidence](docs/m8-report.md) and
[accepted verification record](docs/m8-testing.md). M8 remains on
`m8-secure-snapshots`, unmerged. The following milestone evidence is historical.

**M7 final tested candidate: Dashboard 0.7.0 at
`ff1b6df2444b134a3ee7005bc0a97b02a20b5fb5`.** An offline, localhost-only browser
console uses the existing CLI for status, statistics and lifecycle actions. The
original `08d1ade75215dc237342569f9c9c3dc2fd2957a3` candidate passed automated VM
acceptance, after which real Firefox exposed a `Referrer-Policy: no-referrer` /
`Origin: null` incompatibility on lifecycle POSTs. The final candidate changed
the policy to `same-origin` without relaxing backend Origin validation, then
passed a complete automated VM rerun and real Ubuntu Firefox acceptance. See the
[dashboard guide](dashboard/README.md), [M7 report](docs/m7-report.md) and
[M7 testing procedure](docs/m7-testing.md). Kernel/CLI remain 0.6.0, ABI 1 and
production features 15; M7 changes no crypto.

**M6 complete, version 0.6.0:** a dependency-free management CLI, JSON status,
and privileged runtime statistics. **M6 VM runtime acceptance passed** on commit
`50e11e6ddce88a986719ae2ef7ce972377a69e49` using Ubuntu 24.04.5 LTS and
Linux 7.0.0-38-generic. See the
[M6 report](docs/m6-report.md), [CLI guide](tools/README.md) and
[automated acceptance procedure](docs/m6-testing.md).

M5 established AES-256-XTS confidentiality plus full
HMAC-SHA-256 integrity tags for 4096-byte units, using Encrypt-then-MAC.
Reads authenticate ciphertext before decryption; a mismatch latches a failure
requiring destructive recovery. **M5 VM runtime acceptance passed** on commit
`5fabe544a3969732647e7d9962beed974b667901` using Ubuntu 24.04.5 LTS and
Linux 7.0.0-38-generic.
See [the M5 design/report](docs/m5-report.md) for encoding, key separation,
ABI, synchronization, verification evidence and security limits.

M1-M6 are complete and runtime verified in the user's Ubuntu VirtualBox
VM. Their [M1](docs/m1-report.md), [M2](docs/m2-report.md) and
[M3](docs/m3-report.md) reports remain historical evidence. M2/M3 stored plaintext;
their successful tests do not verify this new crypto implementation.

## Data and control paths

```text
application/filesystem -> Linux block layer -> blk-mq
  -> bounded pending list -> ordered worker -> whole-unit gather/scatter
  -> Kernel Crypto API AES-XTS + HMAC -> checked ciphertext/tag RAM store

privileged secureramctl CLI -> /dev/secureramctl -> validated ioctl
  -> close I/O admission -> drain -> change key/state -> reopen if ACTIVE

GET_STATS -> independent counter lock -> coherent read-only snapshot

ordinary browser -> 127.0.0.1 Python backend -> existing secureramctl JSON/actions
  -> unchanged privileged control path above

snapshot ioctl -> existing control mutex -> zero openers -> gate/drain
  -> security-owned slot <-> ciphertext + matching tags (same key generation)
```

`/dev/secureram0` defaults to **64 MiB**, with a load-time `capacity_mb=1..256`
parameter (MiB). It has no partitions. Unload/reboot loses the medium. The
module starts in **NO_KEY**: block opens fail with ENOKEY. A valid 64-byte XTS
key installs two 256-bit AES keys and derives a separate 32-byte integrity key
with kernel HKDF-SHA-256. The entire medium becomes authenticated encrypted
logical zeros before enabling I/O. Tags consume **512 KiB** at default capacity.

`/dev/secureramctl` is root-owned 0600. Every ioctl, including status, checks
CAP_SYS_ADMIN in the initial user namespace. It supports query, statistics, load, lock,
unlock and explicit destructive key removal. Status contains no keys or data.
All administrative state changes require an unmounted, closed block device;
otherwise EBUSY. An integrity failure can latch during open I/O.
Lock retains both keys and any snapshot; unlock only reopens access. Destroy clears both key
states, the snapshot, tags and contents. A replacement requires destroy followed by load and
produces a new empty medium. There is no online rekey or password handling.
INTEGRITY_FAILED (state 4) rejects ordinary I/O with EIO and rejects lock/unlock/
load. Query and statistics work; close/unmount all users, destroy, then load a fresh key.

## Build

Primary recorded runtime target: **Ubuntu 24.04.5 LTS, Linux
7.0.0-38-generic, x86-64**, in VirtualBox. Inspect its current running kernel
and use matching headers/compiler. Build as an ordinary user inside Linux:

```sh
make check-env
make clean
make W=1
modinfo ./secureram.ko
make tools
./tools/secureramctl help
```

An alternate prepared target tree can be selected with `KDIR=/path/to/build`.
An alternate-kernel build is compile-only; never load an Ubuntu generic module
into the Microsoft WSL kernel. See [development](docs/development.md).

## VM verification and use

Follow [the M8 procedure](docs/m8-testing.md) for the accepted snapshot,
dashboard, inherited regression and Firefox evidence. The accepted
[M6 procedure](docs/m6-testing.md) records safe identity checks, production
regression, tamper tests, fail-closed recovery, ext4 and clean unload. Runtime
operations occur only through its explicitly invoked VM harness or manual commands;
ordinary builds never load or access the device. M4's completed evidence remains in
[its report](docs/m4-report.md).

After confirming a disposable VM and building for its running kernel:

```sh
sudo modprobe hkdf
sudo insmod ./secureram.ko capacity_mb=64
sudo udevadm settle
sudo ./tools/secureramctl status
sudo ./tools/secureramctl load-random
sudo ./tools/secureramctl status
```

`load-random` creates an ephemeral 64-byte key that is never printed or persisted.
It requires locked memory, disables process dumps and wipes its key buffer.
The key cannot later be recovered. Use `status --json` and `stats --json` for
machine-readable output. ABI stays 1; SNAPSHOT=16 makes the M8 production feature mask 31.
Counters count successful READ/WRITE requests and bytes, plus actual MAC mismatches.
They survive destroy/rekey, reset on reload and saturate at U64_MAX.
Only after successful activation may normal block reads/writes or ext4 operate.
The opt-in `M5_TEST=1` build enables privileged, bounded ciphertext/tag corruption
and relocation tests, plus internal index/generation binding checks. `M4_TEST=1`
still enables the earlier ciphertext/cursor checks. Clean between variants.
Production omits both test interfaces and test-only comparisons.

Before key destruction or unload, unmount and close every block/control user:

```sh
sudo ./tools/secureramctl destroy
sudo rmmod secureram
sudo udevadm settle
test ! -e /dev/secureram0
test ! -e /dev/secureramctl
```

Never force unload. Open block/control files pin the module. Destroy irreversibly
discards the volatile medium; do not use it as swap.

## Local dashboard

M8 adds Create Snapshot, Restore Snapshot and Delete Snapshot, with typed
RESTORE/DELETE confirmations and live slot metadata/counters. Use
`sudo ./tools/secureramctl snapshot status --json` for the same kernel observation.
`snapshot create`, `snapshot restore` and `snapshot delete` also accept `--json`.
Create rejects an occupied slot; restore keeps it. Default extra memory is
64 MiB + 512 KiB. See [the M8 procedure](docs/m8-testing.md) for the accepted
runtime evidence and reusable verification commands.

After building `make tools` and separately loading the matching-kernel module in
the disposable VM, run from a trusted checkout:

```sh
sudo python3 -I dashboard/server.py
```

Open its printed URL in the ordinary user's browser in the same VM. Python 3.10+
standard library and offline HTML/CSS/JS are sufficient. The backend binds only
127.0.0.1 on an ephemeral port and requires a fresh startup token for every API
request. Host/Origin checks, fixed POST actions and no-shell CLI calls constrain
the privileged HTTP surface. No device permissions are weakened. Do not save or
share the URL credential, redirect startup stdout into logs, forward the port or
launch a root browser. Ctrl+C stops the server without changing driver state.

The UI shows state, geometry, versions/features, exact counters and sampled I/O,
with state-aware controls and typed Destroy confirmation. INTEGRITY_FAILED is a
prominent warning; only destroy followed by fresh load can recover. Stale/lost
connections disable controls. Button state is advisory; the CLI/kernel enforces
every transition. See [the guide](dashboard/README.md) for the API, trust model,
startup/shutdown and limits. This token protects the local HTTP interface only.

## Limits and layout

READ/WRITE handle segmented requests as complete 4096-byte crypto units. A
delivered FLUSH is an ordered no-op; no write-back cache or persistence is
advertised. Native DISCARD, WRITE_ZEROES and atomic writes are unsupported.
There is one hardware queue, 64 tags, a 128 KiB request limit and one ordered
worker. Multi-unit requests are not atomic: earlier authenticated READ units
may already be copied to request buffers before a later unit fails; no plaintext
from the failed unit is decrypted or copied. Earlier WRITE units may already
be committed. Errors never trigger plaintext retry.

The threat boundary assumes trusted keys, kernel code and control state.
HMAC detects changes to authenticated material on reads, including relocation.
Same-unit, same-generation rollback of a valid ciphertext/tag pair remains
possible. This is not AEAD. It does not protect against malicious kernel code,
arbitrary root/kernel memory modification, a compromised hypervisor, key exposure,
crash-persistent replay, cold boot or durable storage attacks. Applications and
filesystem caches contain plaintext; cached reads can bypass the driver.
Explicit clearing covers owned buffers during orderly cleanup, not external
copies or crashes. See [the M5 threat model](docs/m5-report.md#threat-model-and-claims)
and [architecture](docs/architecture.md).

| Location | Responsibility |
| --- | --- |
| `src/secureram_main.c` | Module parameters, lifecycle, version/logs. |
| `src/secureram_block.c` | blk-mq, bounds/segments, worker, opens and transition synchronization. |
| `src/secureram_security.c` | XTS, HKDF/HMAC, verify-before-decrypt, staging, key lifecycle. |
| `src/secureram_store.c` | Ciphertext/tag allocations, checked pair copies and clearing. |
| `src/secureram_snapshot.c`, `include/secureram_snapshot.h` | Single-slot ownership, generation validation, protected copies and lifecycle cleanup. |
| `src/secureram_control.c`, `include/uapi/secureram.h` | Privileged ioctl adapter and fixed-width ABI. |
| `tests/m4-control.c`, `tests/m5-*.py`, `tests/run-m5-*.sh`, `tests/abi-layout.c` | Shared helper, M5 VM suites/harness and compile-only ABI checks. |
| `src/secureram_stats.c`, `include/secureram_stats.h` | Device-lifetime counters, saturation and coherent snapshots. |
| `tools/secureramctl.c`, `tools/Makefile` | C management CLI, protected random key load, human/JSON output. |
| `tests/run-m6-vm-acceptance.sh`, `tests/m6-*`, `tests/check-m6-*` | M6 acceptance, CLI mocks and local static checks. |
| `dashboard/server.py`, `dashboard/static/` | Local privileged CLI adapter and offline browser UI; dashboard 0.8.0. |
| `tests/check-m8-*`, `tests/m8-*`, `tests/run-m8-vm-acceptance.sh` | Sanitized core tests, CLI/HTTP/UI tests and opt-in M8 VM suite. |
| `tests/run-m7-vm-acceptance.sh`, `tests/m7-*`, `tests/check-m7-*` | Prepared M7 VM suite, isolated UI fixture, HTTP/observer/harness checks. |
| `docs/` | Designs, evidence, procedures and viva notes. |

No remote administration, benchmarking or persistent storage is included.
The dashboard's loopback HTTP service is the only new network surface.
The successful M6 acceptance evidence is recorded in [the M6 report](docs/m6-report.md).
Source is **GPL-2.0-only**; see [LICENSE](LICENSE).
