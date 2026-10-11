# SecureRAM

SecureRAM is a university Operating Systems project implementing a volatile
Linux block device backed by memory owned by a kernel driver.

**M5 candidate, version 0.5.0:** AES-256-XTS confidentiality plus full
HMAC-SHA-256 integrity tags for 4096-byte units, using Encrypt-then-MAC.
Reads authenticate ciphertext before decryption; a mismatch latches a failure
requiring destructive recovery. **M5 VM runtime acceptance is pending.**
See [the M5 design/report](docs/m5-report.md) for encoding, key separation,
ABI, synchronization, verification evidence and security limits.

M1, M2, M3 and M4 are complete and runtime verified in the user's Ubuntu VirtualBox
VM. Their [M1](docs/m1-report.md), [M2](docs/m2-report.md) and
[M3](docs/m3-report.md) reports remain historical evidence. M2/M3 stored plaintext;
their successful tests do not verify this new crypto implementation.

## Data and control paths

```text
application/filesystem -> Linux block layer -> blk-mq
  -> bounded pending list -> ordered worker -> whole-unit gather/scatter
  -> Kernel Crypto API AES-XTS + HMAC -> checked ciphertext/tag RAM store

privileged test helper -> /dev/secureramctl -> validated ioctl
  -> close I/O admission -> drain -> change key/state -> reopen if ACTIVE
```

`/dev/secureram0` defaults to **64 MiB**, with a load-time `capacity_mb=1..256`
parameter (MiB). It has no partitions. Unload/reboot loses the medium. The
module starts in **NO_KEY**: block opens fail with ENOKEY. A valid 64-byte XTS
key installs two 256-bit AES keys and derives a separate 32-byte integrity key
with kernel HKDF-SHA-256. The entire medium becomes authenticated encrypted
logical zeros before enabling I/O. Tags consume **512 KiB** at default capacity.

`/dev/secureramctl` is root-owned 0600. Every ioctl, including status, checks
CAP_SYS_ADMIN in the initial user namespace. It supports query, load, lock,
unlock and explicit destructive key removal. Status contains no keys or data.
All administrative state changes require an unmounted, closed block device;
otherwise EBUSY. An integrity failure can latch during open I/O.
Lock retains both keys; unlock only reopens access. Destroy clears both key
states, tags and contents. A replacement requires destroy followed by load and
produces a new empty medium. There is no online rekey or password handling.
INTEGRITY_FAILED (state 4) rejects ordinary I/O with EIO and rejects lock/unlock/
load. Query works; close/unmount all users, destroy, then load a fresh key.

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

Follow [the M5 procedure](docs/m5-testing.md) for safe identity checks, production
regression, tamper tests, fail-closed recovery, ext4 and clean unload. Runtime
operations occur only through its explicitly invoked VM harness or manual commands;
ordinary builds never load or access the device. M4's completed evidence remains in
[its report](docs/m4-report.md).

After confirming a disposable VM and building for its running kernel:

```sh
sudo modprobe hkdf
sudo insmod ./secureram.ko capacity_mb=64
sudo udevadm settle
sudo .cache/m4-control query
sudo .cache/m4-control load-test-key
sudo .cache/m4-control query
```

`load-test-key` generates a random, ephemeral 64-byte key inside the test helper;
it prints/stores none of it. It is verification tooling, not the final CLI.
Only after successful activation may normal block reads/writes or ext4 operate.
The opt-in `M5_TEST=1` build enables privileged, bounded ciphertext/tag corruption
and relocation tests, plus internal index/generation binding checks. `M4_TEST=1`
still enables the earlier ciphertext/cursor checks. Clean between variants.
Production omits both test interfaces and test-only comparisons.

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
| `src/secureram_control.c`, `include/uapi/secureram.h` | Privileged ioctl adapter and fixed-width ABI. |
| `tests/m4-control.c`, `tests/m5-*.py`, `tests/run-m5-*.sh`, `tests/abi-layout.c` | Shared helper, M5 VM suites/harness and compile-only ABI checks. |
| `docs/` | Designs, evidence, procedures and viva notes. |

No polished CLI, GUI, dashboard, benchmarking, persistence or networking is
included. Stop after M5 review; no commit/merge/push is authorized yet.
Source is **GPL-2.0-only**; see [LICENSE](LICENSE).
