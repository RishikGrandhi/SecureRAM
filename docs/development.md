# Developer workflow and learning notes

M1-M3 runtime acceptance is recorded in their reports. M4 is the current
implementation candidate; [the M4 report](m4-report.md) separates compile/static
results from pending runtime checks. Older procedures apply to their historical
versions. Use [the M4 procedure](m4-testing.md) for the encrypted driver.

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
WSL's Microsoft kernel is separate from Ubuntu generic headers. The current WSL
kernel lacks a matching build tree, so the existing prepared Ubuntu headers
provide **compile-only** verification. No runtime test is run in WSL.

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
python3 -m py_compile tests/m2-raw-io.py tests/m4-raw-io.py
git diff --check
```

The Makefile delegates to Kbuild's external-module machinery. The composite
module links main, block, security, store and control. Use the same `KDIR` for
cleaning and building. A prepared tree needs generated config and Module.symvers;
`modules_prepare` alone does not supply symbol versions. See
[external-module documentation](https://docs.kernel.org/kbuild/modules.html).

Current local compile-only example (Bash in WSL):

```bash
m4_headers=/home/rishik_grandhi/.cache/secureram-m2-20261010/root/usr/src
m4_target="$m4_headers/linux-headers-7.0.0-38-generic"
make KDIR="$m4_target" check-env
make KDIR="$m4_target" clean
set -o pipefail
make KDIR="$m4_target" CC=gcc W=1 2>&1 | tee build-m4-production.log
perl "$m4_headers/linux-hwe-7.0-headers-7.0.0-38/scripts/checkpatch.pl" \
  --no-tree --strict --file src/*.c include/*.h include/uapi/*.h
nm -u src/secureram_security.o
/usr/sbin/modinfo ./secureram.ko
```

Read the whole compiler/MODPOST/link log. Local GCC 15 differs from the target's
GCC 13; this environmental warning must remain recorded. Missing pahole/vmlinux
prevents BTF generation. Any new driver-source warning is a failure to fix.
The default target compiler may be absent locally, hence the explicit CC=gcc.

For the internal verification variant, clean then build with `M4_TEST=1` and
the same target/compiler arguments. Clean again before a production build.
The option adds actual backing comparisons and split-unit checks without a
debug memory interface. Build success does not execute these checks. Keep
build products and logs ignored, and clean generated module artifacts after
inspection. Leave requested M4 source changes uncommitted for review.

## Manual runtime smoke check

Follow [the M4 procedure](m4-testing.md) for the current encrypted version:
matching-kernel load, keyless denial, valid key installation, raw/filesystem
I/O, safe key destruction, unload and inspection of fresh kernel logs. The M1
and M2 reports linking here describe their historical version's behavior; they
do not establish M4 runtime acceptance. Device tests are never run by the build.

## API choices and debugging

Use target headers and official
[skcipher documentation](https://docs.kernel.org/crypto/api-skcipher.html).
The current headers expose skcipher_request_zero for clearing a completed
request; reattach its transform before reuse. Completion waits must finish
before clearing/freeing buffers. Each 4096-byte kmalloc staging buffer fits
inside one page/SG entry, independent of a request's segmentation. Excluding
allocating and kernel-only hardware providers narrows reclaim/DMA assumptions;
provider availability/progress still needs VM evidence.

The modern char endpoint uses nonseekable_open, unlocked_ioctl and
compat_ptr_ioctl. The fixed-width/aligned UAPI has identical intended ILP32/LP64
layout. Capability checks run per operation, including on passed descriptors.
Read [ioctl guidance](https://docs.kernel.org/driver-api/ioctl.html) before ABI
changes; unknown commands must be ENOTTY and output must not contain padding leaks.

| Observation | Interpretation |
| --- | --- |
| Block open fails ENOKEY | Expected in NO_KEY/LOCKED; inspect privileged query. |
| Key change fails EBUSY | Close/unmount block users, or check that transition is valid. |
| Key load fails EINVAL | Check exact length, distinct halves, ABI version/size/reserved fields and provider geometry. |
| Key load reports provider/allocation error | Remains fail closed; inspect configuration/provider availability and memory pressure. |
| Module format/signature rejection | Rebuild for running kernel and follow signing policy; never bypass it. |
| Module busy | Open block/control files pin it; close legitimate users. |
| Test log absent | Confirm the current insertion uses M4_TEST=1 and a real write occurred; old logs prove nothing. |

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
