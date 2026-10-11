# Developer workflow and learning notes

M1-M5 runtime acceptance is recorded in their reports. The
[M4 report](m4-report.md) separates compile/static results from the completed
VM runtime checks. Older procedures apply to their historical
versions. M5 adds integrity; its [report](m5-report.md) and
[VM procedure](m5-testing.md) separate compile/static evidence from the completed
runtime acceptance.

## Current M6 implementation

M6 is version 0.6.0 on `m6-cli-observability`, with ABI 1 and feature mask 15.
Runtime acceptance passed on commit `50e11e6ddce88a986719ae2ef7ce972377a69e49`
using Ubuntu 24.04.5 LTS and Linux 7.0.0-38-generic. `make tools` builds the C
management utility with C11 and strict warnings; no userspace dependency is
added to the kernel build.
`make tools-clean` cleans just that binary. Use the [CLI guide](../tools/README.md)
and [M6 acceptance procedure](m6-testing.md) for the accepted implementation.

Reproducible local verification in the existing WSL compile environment:

```sh
python3 tests/check-m6-local.py \
  --kdir /home/rishik_grandhi/.cache/secureram-m2-20261010/root/usr/src/linux-headers-7.0.0-38-generic \
  --checkpatch /home/rishik_grandhi/.cache/secureram-m2-20261010/root/usr/src/linux-hwe-7.0-headers-7.0.0-38/scripts/checkpatch.pl
```

This builds all variants, checks ABI/native+compat layouts, executes CLI syscall
mocks and the full mocked harness, checks each shell script separately, compiles
all Python helpers and inspects production imports/test exclusion. It does not
load a module or establish runtime acceptance. ShellCheck is optional if already
installed. Older commands below remain useful historical M4/M5 workflows.

## Target and prerequisites

Use the disposable Ubuntu VirtualBox VM, currently recorded as Ubuntu 24.04.5,
Linux 7.0.0-38-generic, x86-64. Recheck its running release and compiler. Kernel
internal APIs are not stable; compilation does not imply universal compatibility.

```sh
uname -r
gcc --version
sudo apt-get update
sudo apt-get install build-essential kmod "linux-headers-$(uname -r)"
```

Build as an ordinary user. Root is needed only for explicitly authorized VM
device/lifecycle operations. Follow the distribution's module-signing policy.
Never force load/unload or redirect destructive tests to another block device.

From Windows, `wsl -d Ubuntu` opens the installed Linux environment. The project
is available there as `/mnt/c/Coding/Projects/SecureRAM`. Keep files LF-terminated.
A Linux-home checkout may build faster; do not use spaces in kernel build paths.
WSL's Microsoft kernel is separate from Ubuntu generic headers. The WSL kernel
used for local M4 development lacked a matching build tree, so prepared Ubuntu
headers provided **compile-only** verification there. M4 runtime acceptance was
completed separately in the matching VirtualBox VM.

## Build and static inspection

```sh
make check-env
make clean
make W=1
modinfo ./secureram.ko
mkdir -p .cache
gcc -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Iinclude \
  tests/m4-control.c -o .cache/m4-control
sh -n scripts/check-environment.sh
python3 -m py_compile tests/m2-raw-io.py tests/m4-raw-io.py tests/m5-raw-io.py tests/m5-integrity.py
gcc -std=c11 -Wall -Wextra -Werror -Wconversion -m64 -Iinclude \
  -DSECURERAM_M5_TEST -c tests/abi-layout.c -o .cache/m5-abi64.o
gcc -std=c11 -Wall -Wextra -Werror -Wconversion -m32 -Iinclude \
  -I/usr/include/x86_64-linux-gnu -DSECURERAM_M5_TEST \
  -c tests/abi-layout.c -o .cache/m5-abi32.o
git diff --check
```

The Makefile delegates to Kbuild's external-module machinery. The composite
module links main, block, security, store and control. Use the same `KDIR` for
cleaning and building. A prepared tree needs generated config and Module.symvers;
`modules_prepare` alone does not supply symbol versions. See
[external-module documentation](https://docs.kernel.org/kbuild/modules.html).

Current local compile-only example (Bash in WSL):

```bash
m5_headers=/home/rishik_grandhi/.cache/secureram-m2-20261010/root/usr/src
m5_target="$m5_headers/linux-headers-7.0.0-38-generic"
make KDIR="$m5_target" check-env
make KDIR="$m5_target" clean
set -o pipefail
make KDIR="$m5_target" CC=gcc W=1 2>&1 | tee build-m5-production.log
perl "$m5_headers/linux-hwe-7.0-headers-7.0.0-38/scripts/checkpatch.pl" \
  --no-tree --strict --file src/*.c include/*.h include/uapi/*.h tests/m4-control.c
perl "$m5_headers/linux-hwe-7.0-headers-7.0.0-38/scripts/checkpatch.pl" \
  --no-tree --strict --ignore CAMELCASE --file tests/abi-layout.c
nm -u src/secureram_security.o
/usr/sbin/modinfo ./secureram.ko
```

Read the whole compiler/MODPOST/link log. Local GCC 15 differs from the target's
GCC 13; this environmental warning must remain recorded. Missing pahole/vmlinux
prevents BTF generation. Any new driver-source warning is a failure to fix.
The default target compiler may be absent locally, hence the explicit CC=gcc.

For integrity verification, clean then build with `M5_TEST=1` and the same
target/compiler arguments. Optionally combine `M4_TEST=1` for backing/cursor
regression. Clean again before production. M5 exposes a bounded privileged
corruption ioctl only in that build; it exports no data or arbitrary addresses.
Inspect `strings` and `nm` to confirm production contains no M4/M5 test strings,
tamper functions or command case. Runtime also probes ENOTTY.
Build success does not execute tests. Keep build products/logs ignored, clean
generated module artifacts after inspection. Compile-only results remain distinct
from the completed matching-kernel M6 runtime acceptance.

The ABI compile test preserves all five M4 command numbers and layouts, and
checks the 80-byte M6 statistics payload plus the 40-byte M5 test payload on LP64/ILP32. The -m32 object test uses the
available x86 UAPI include directory and requires no 32-bit libc or executable.
It does not prove compat runtime behavior.
The ABI-only fixture uses C11 `_Static_assert` without libc headers; checkpatch's
CamelCase heuristic flags that standard keyword. Only that check is excluded
for this fixture; kernel code and the control helper use the unmodified strict
workflow. Do not hide actual driver warnings behind this exception.

## Manual runtime smoke check

Follow [the M6 procedure](m6-testing.md) to reproduce the accepted
implementation's checks: matching-kernel load, keyless denial, valid key
installation, raw/filesystem I/O, safe key destruction, unload and inspection
of fresh kernel logs. The M1 and M2 reports linking here describe their
historical version's behavior. M4 through M6 runtime acceptance are recorded in
their respective reports.
Load the target's `hkdf` dependency with `sudo modprobe hkdf` before insmod.
Device tests are never run by the build itself.

## API choices and debugging

Use target headers and official
[skcipher documentation](https://docs.kernel.org/crypto/api-skcipher.html).
The target headers expose skcipher_request_zero for clearing a completed
request; reattach its transform before reuse. Completion waits must finish
before clearing/freeing buffers. Each 4096-byte kmalloc staging buffer fits
inside one page/SG entry, independent of a request's segmentation. Excluding
allocating and kernel-only hardware providers narrows reclaim/DMA assumptions.
Provider execution was observed in the VM with `xts-aes-aesni-avx`; controlled
provider-unavailability and injected-failure tests remain separate coverage.

M5 uses the synchronous `hmac(sha256)` shash API and exported `hkdf_extract` /
`hkdf_expand` helpers. Target config has CRYPTO_HKDF=m, HMAC=y, SHA256=y.
Check exact function signatures and symbol exports in the prepared target;
do not replace missing helpers with an ad-hoc KDF. Preallocate the shash
descriptor before ACTIVE, clear it with shash_desc_zero after each MAC, then
reattach its transform. Store both tag and ciphertext only after crypto success;
compare with crypto_memneq before decrypting. The [M5 report](m5-report.md)
documents the exact binary encoding, lifetime and updated state synchronization.

The modern char endpoint uses nonseekable_open, unlocked_ioctl and
compat_ptr_ioctl. The fixed-width/aligned UAPI has identical intended ILP32/LP64
layout. Capability checks run per operation, including on passed descriptors.
Read [ioctl guidance](https://docs.kernel.org/driver-api/ioctl.html) before ABI
changes; unknown commands must be ENOTTY and output must not contain padding leaks.

| Observation | Interpretation |
| --- | --- |
| Block open fails ENOKEY | Expected in NO_KEY/LOCKED; inspect privileged query. |
| Block I/O/open fails EIO, query state 4 | Integrity failure is latched; close/unmount users, destroy, then install a fresh key. Never unlock to bypass it. |
| Key change fails EBUSY | Close/unmount block users, or check that transition is valid. |
| Key load fails EINVAL | Check exact length, distinct halves, ABI version/size/reserved fields and provider geometry. |
| Key load reports provider/allocation error | Remains fail closed; inspect configuration/provider availability and memory pressure. |
| Module format/signature rejection | Rebuild for running kernel and follow signing policy; never bypass it. |
| Module busy | Open block/control files pin it; close legitimate users. |
| Test log absent | Confirm the current insertion's build flags and tested path; M5 binding checks run on load, M4 real-write check needs a write. Old logs prove nothing. |
| Unknown HKDF symbols on insertion | Load the matching kernel's hkdf dependency; verify running-kernel build/configuration. |

Watch fresh `dmesg --follow-new` in the VM. Never log keys, plaintext, backing
bytes, sensitive ioctl contents or pointers. Out-of-tree/signature taints are
distinct from Oops, BUG, warning backtraces and driver correctness failures.

## Learn before M2

These foundational topics remain relevant to every subsequent milestone.

Trace VFS -> page cache -> bio/request -> blk-mq -> pending worker -> crypto
unit -> store. Distinguish 512-byte sectors, 4096-byte logical units, 16-byte AES
blocks and pages. Explain why segment boundaries cannot select tweaks, why
encrypted zeros must be initialized, and why encryption does not authenticate.

## M4 viva preparation

Identify every resource owner, partial-failure unwind, request completion and
zeroization point. Explain spinlocks versus mutexes, gate-before-drain, why the
worker cannot take the control mutex, final-close cache flushing, and module
references on both endpoints. Separate locked access gating from destruction,
confidentiality from integrity/freshness, and compiled evidence from observed
runtime behavior. See [M4 viva notes](m4-report.md#viva-concepts).

For M5, also explain Encrypt-then-MAC, HKDF key separation, fixed-width domain/
generation/index binding, full tags, the failure latch and recovery, same-unit
replay limits, and test-build exclusion. See [M5 viva notes](m5-report.md#viva-preparation).

## M6 viva preparation

Explain the difference between application syscalls, block requests, crypto units
and cached I/O. Trace success accounting before request recycling and why a
partially failed multi-unit request counts zero. Explain why a separate spinlock
makes snapshots coherent on 32-bit kernels, why it must not cover crypto/user-copy,
why counters survive key destruction, and why saturation is diagnostic only.
Trace the unchanged ioctl capability check, the new output-only payload, reserved
zeroing, compat_ptr_ioctl, and the difference between ABI and module version.
Explain getrandom short reads/EINTR, mlock, dump disabling and explicit erasure,
including the limits against malicious root and unrecoverability of demo keys.
Distinguish static builds/mocks from observed VM evidence and explain harness
ownership, full commit pinning, fail-fast reporting and safe cleanup refusal.
