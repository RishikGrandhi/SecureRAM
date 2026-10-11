# SecureRAM

SecureRAM is a university Operating Systems project implementing a volatile
Linux block device backed by memory owned by a kernel driver.

**M4, version 0.4.0:** AES-256-XTS encrypted RAM-backed storage, with
4096-byte logical/crypto units and a separate privileged key-control interface.
**Confidentiality only; cryptographic integrity/authentication is not implemented.**
**M4 Ubuntu VM runtime acceptance is complete**, including direct internal
evidence that backing RAM contains ciphertext and a final production regression.
See [the M4 report](docs/m4-report.md) for exact build/static/runtime evidence
and limits.

M1, M2, M3 and M4 are complete and runtime verified in the user's Ubuntu VirtualBox
VM. Their [M1](docs/m1-report.md), [M2](docs/m2-report.md) and
[M3](docs/m3-report.md) reports remain historical evidence. M2/M3 stored plaintext;
their successful tests do not verify this new crypto implementation.

## Data and control paths

```text
application/filesystem -> Linux block layer -> blk-mq
  -> bounded pending list -> ordered worker -> whole-unit gather/scatter
  -> Kernel Crypto API AES-XTS -> checked ciphertext RAM store

privileged test helper -> /dev/secureramctl -> validated ioctl
  -> close I/O admission -> drain -> change key/state -> reopen if ACTIVE
```

`/dev/secureram0` defaults to **64 MiB**, with a load-time `capacity_mb=1..256`
parameter (MiB). It has no partitions. Unload/reboot loses the medium. The
module starts in **NO_KEY**: block opens fail with ENOKEY. A valid 64-byte XTS
key installs two 256-bit AES keys and initializes the entire medium to encrypted
logical zeros before enabling I/O. There is no plaintext fallback.

`/dev/secureramctl` is root-owned 0600. Every ioctl, including status, checks
CAP_SYS_ADMIN in the initial user namespace. It supports query, load, lock,
unlock and explicit destructive key removal. Status contains no keys or data.
All state changes require an unmounted, closed block device; otherwise EBUSY.
Lock retains the key; unlock only reopens access. Destroy clears the key and
contents. A replacement requires destroy followed by load and produces a new
empty medium. There is no online rekey or password/KDF handling.

## Build

Primary recorded runtime target: **Ubuntu 24.04.5 LTS, Linux
7.0.0-38-generic, x86-64**, in VirtualBox. Inspect its current running kernel
and use matching headers/compiler. Build as an ordinary user inside Linux:

```sh
make check-env
make clean
make W=1
modinfo ./secureram.ko
mkdir -p .cache
gcc -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Iinclude \
  tests/m4-control.c -o .cache/m4-control
```

An alternate prepared target tree can be selected with `KDIR=/path/to/build`.
An alternate-kernel build is compile-only; never load an Ubuntu generic module
into the Microsoft WSL kernel. See [development](docs/development.md).

## VM verification and use

Follow [the M4 procedure](docs/m4-testing.md) for safe identity checks, fail-closed
tests, key activation, raw SHA-256/cmp verification, internal ciphertext evidence,
ext4, key removal and unload. No runtime/device commands run automatically.

After confirming a disposable VM and building for its running kernel:

```sh
sudo insmod ./secureram.ko capacity_mb=64
sudo udevadm settle
sudo .cache/m4-control query
sudo .cache/m4-control load-test-key
sudo .cache/m4-control query
```

`load-test-key` generates a random, ephemeral 64-byte key inside the test helper;
it prints/stores none of it. It is verification tooling, not the final CLI.
Only after successful activation may normal block reads/writes or ext4 operate.
For direct backing evidence use the guide's opt-in `M4_TEST=1` build; it reports
internal comparisons without exposing backing memory. The production build
contains no such checks or debug export.

Before key destruction or unload, unmount and close every block/control user:

```sh
sudo .cache/m4-control destroy
sudo rmmod secureram
sudo udevadm settle
test ! -e /dev/secureram0
test ! -e /dev/secureramctl
```

Never force unload. Open block/control files pin the module. Destroy irreversibly
discards the volatile medium; do not use it as swap.

## Limits and layout

READ/WRITE handle segmented requests as complete 4096-byte crypto units. A
delivered FLUSH is an ordered no-op; no write-back cache or persistence is
advertised. Native DISCARD, WRITE_ZEROES and atomic writes are unsupported.
There is one hardware queue, 64 tags, a 128 KiB request limit and one ordered
worker. Multi-unit requests are not atomic: earlier units can complete before
a later unit fails. Errors never trigger plaintext retry.

The threat boundary is disclosure of backing bytes alone, without the key or
other plaintext copies. Applications, filesystem caches and successful normal
reads contain plaintext. There is no authentication, tamper/wrong-key/replay
detection, protection against root/kernel/hypervisor compromise, whole-RAM or
cold-boot guarantee, persistence, or password security. Explicit clearing covers
named driver-owned buffers during orderly cleanup, not external copies or crashes.
See [the threat model](docs/m3-threat-model.md) and [architecture](docs/architecture.md).

| Location | Responsibility |
| --- | --- |
| `src/secureram_main.c` | Module parameters, lifecycle, version/logs. |
| `src/secureram_block.c` | blk-mq, bounds/segments, worker, opens and transition synchronization. |
| `src/secureram_security.c` | XTS, units/tweaks, state, staging, key lifecycle. |
| `src/secureram_store.c` | Checked byte copies, allocation and explicit clearing. |
| `src/secureram_control.c`, `include/uapi/secureram.h` | Privileged ioctl adapter and fixed-width ABI. |
| `tests/m4-control.c`, `tests/m4-raw-io.py` | Opt-in VM verification helpers. |
| `docs/` | Designs, evidence, procedures and viva notes. |

M5 may add authenticated storage after a separate design/request. No M5 code,
polished CLI, GUI, dashboard, benchmarking, persistence or networking is included.
Stop after M4. Source is **GPL-2.0-only**; see [LICENSE](LICENSE).
