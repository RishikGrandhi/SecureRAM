# M1 implementation and verification report

Date: 2026-10-09 (Asia/Calcutta). Scope: **M1 only**.

Result: the skeleton compiled and linked successfully for Linux
`6.18.0-061800-generic` on x86-64 using GCC 15.2.0 with `W=1`.
**Runtime loading, kernel-log output, and unloading remain unverified.**
The running WSL kernel is different and has no matching build/header tree.
The compile-only module was cleaned after metadata inspection.

## 1. Repository inspection and files created

The initial `C:\Coding\Projects\SecureRAM` directory was empty, with no Git
repository or applicable ancestor `AGENTS.md`. Architecture documentation was
written before implementation. A local Git repository was initialized on `main`;
no commit, remote, push, or system-wide installation was made.

| File | Purpose |
| --- | --- |
| `docs/architecture.md` | Architecture, ASCII diagram, component boundaries, threat model, lifecycle and future milestones. |
| `src/secureram_main.c` | Minimal module entry/exit, prefixed messages, metadata. |
| `include/secureram_config.h` | Driver/device names, version, future capacity and geometry constants. |
| `Kbuild` | Composite external-module object list and include path. |
| `Makefile` | Build, clean, help, and environment-check targets. |
| `scripts/check-environment.sh` | Read-only Linux/tool/header preflight and target mismatch reporting. |
| `README.md` | Current status, prerequisites, expected output, basic workflow and roadmap. |
| `docs/development.md` | Setup, troubleshooting, manual smoke check, kernel concepts. |
| `docs/m1-report.md` | This report and reproducible validation details. |
| `tests/README.md` | Meaningful M1 checks and later testing scope. |
| `tools/README.md` | Reserved scope of the future management utility. |
| `.gitignore` | Generated kernel objects, local logs, editor files. |
| `.gitattributes`, `.editorconfig` | LF text files and kernel-style source indentation. |
| `LICENSE` | GPL version 2 license text; source SPDX identifiers specify GPL-2.0-only. |

`build-m1.log` is a preserved local build transcript, intentionally Git-ignored.
The private compile-only header cache is outside the repository at
`/home/rishik_grandhi/.cache/secureram-m1-20261009` in WSL. It contains extracted
headers, downloaded packages, the build log, and captured `modinfo` output.

## 2. Architecture decisions

- Keep the existing directory as the project root and link future source files
  into one `secureram.ko` using Kbuild.
- M1 owns no driver allocations and registers no device; a successful init and
  an unload log are its only behaviors.
- Plan a real blk-mq block device in M2 with bounded request resources and an
  ordered worker to serialize backing-store operations in sleepable context.
- Reserve defaults of 64 MiB, 4096-byte logical blocks, and 512-byte block-layer
  sector accounting. The capacity macro uses a 64-bit unsigned expression.
- Separate block routing, RAM storage, crypto, control, and statistics as they
  become real components; do not add unused implementations now.
- Future security protects driver-owned backing under a documented threat
  model. It cannot hide plaintext from an authorized reader, page cache, or
  compromised kernel. Nonce uniqueness, authenticated reads, key removal,
  metadata lifetime, and erasure need deliberate later implementation.

## 3. Commands executed

Commands below group the work by purpose. Linux commands ran through
`wsl -d Ubuntu` from PowerShell; the Linux project path is
`/mnt/c/Coding/Projects/SecureRAM`.

Repository/environment inspection included `Get-ChildItem -Force`, `rg --files`,
reading the applicable ancestor paths, `git status --short --branch`,
`wsl --list --verbose`, `uname -a`, `id`, `/etc/os-release`, tool discovery,
`gcc --version`, `apt-cache policy`, `dpkg-query -W`, listing `/usr/src` and
`/lib/modules`, `capsh --print`, `/proc/config.gz`, and `sudo -n true`.
The latter reported that interactive authentication is required.

The normal build path was attempted first:

```sh
make check-env
make W=1
```

Both failed because `/lib/modules/6.18.33.2-microsoft-standard-WSL2/build`
does not exist. No source compilation was possible through that default path.

For a real compile-only check, two header packages were fetched over HTTPS from
Ubuntu's [Linux 6.18 mainline build](https://kernel.ubuntu.com/mainline/v6.18/).
The commands were equivalent to the following in the private cache directory:

```sh
base=https://kernel.ubuntu.com/mainline/v6.18/amd64
curl -fL -o headers-common.deb \
  "$base/linux-headers-6.18.0-061800_6.18.0-061800.202511302339_all.deb"
curl -fL -o headers-amd64.deb \
  "$base/linux-headers-6.18.0-061800-generic_6.18.0-061800.202511302339_amd64.deb"
curl -fL -o CHECKSUMS "$base/CHECKSUMS"
sha256sum headers-common.deb headers-amd64.deb
dpkg-deb -x headers-common.deb root
dpkg-deb -x headers-amd64.deb root
```

The actual downloads also used connection/total timeouts and retries. Their
SHA-256 hashes matched the published values:

```text
common: e4acd50a9a224c96f74bae7d0b67b0524728eef8e7d6fbaa87013f8fdb4d210f
amd64:  e278840f185f1793097d6947f8fe1f7e49429ab57dd5df707e18f6ceba261cfa
```

These were extracted with `dpkg-deb -x`, not installed with `dpkg -i` or `apt`.
An initial extraction under `/tmp` was no longer present in the next WSL
invocation, causing another missing-tree failure before compilation. Repeating
the extraction under the user's persistent `.cache` resolved that issue.

The successful validation sequence, expressed in Bash from the project root:

```bash
headers=/home/rishik_grandhi/.cache/secureram-m1-20261009/root/usr/src
target="$headers/linux-headers-6.18.0-061800-generic"
make KDIR="$target" check-env
set -o pipefail
make KDIR="$target" CC=gcc W=1 2>&1 | tee build-m1.log
/usr/sbin/modinfo ./secureram.ko
file ./secureram.ko
nm ./secureram.ko
perl "$headers/linux-headers-6.18.0-061800/scripts/checkpatch.pl" \
  --no-tree --strict --file src/secureram_main.c include/secureram_config.h
sh -n scripts/check-environment.sh
make help
make KDIR="$target" clean
```

The original compile log was captured in the cache with `tee` and subsequently
copied to `build-m1.log`. Additional file checks inspected text encoding, final
newlines, local documentation links, whitespace, and generated-file cleanup.
Git commands included `git init -b main`, `git status --short --branch`,
`git check-ignore` for generated module files, and `git diff --no-index --check`
against the new source/header. No-index diff's difference status is not itself
a whitespace diagnostic.

## 4. Build and verification results

| Check | Result |
| --- | --- |
| Host and Linux environment | Windows host; WSL2 Ubuntu 26.04 LTS, x86-64. |
| Running kernel | `6.18.33.2-microsoft-standard-WSL2`. |
| Default header/build tree | Absent; default preflight/build correctly failed. |
| Alternate-header preflight | Passed; correctly reported a compile-only target mismatch. |
| Compile and module link, `W=1` | Passed, exit 0; produced `secureram.ko`. |
| Source compiler diagnostics | No source-code warnings or errors. |
| `modinfo` | Name `secureram`, version `0.1.0`, license `GPL`, expected author/description. |
| `vermagic` | `6.18.0-061800-generic SMP preempt mod_unload modversions`. |
| ELF/symbol inspection | x86-64 relocatable module; init/cleanup symbols and logging dependencies present. |
| Kernel `checkpatch.pl --strict` | Source: 0 errors/warnings/checks (30 lines); header: 0 errors/warnings/checks (16 lines). |
| Shell syntax | `sh -n` passed. |
| Help and generated-file ignore rules | Passed. |
| Text/whitespace/docs inspection | Passed. |
| Kbuild cleanup | Passed using the same alternate `KDIR`; no compiled module left to load accidentally. |
| Load/log/unload | Not attempted: no matching module could be built for the running kernel. Runtime remains unverified. |

## 5. Warnings, errors, and limitations

The successful build printed this toolchain warning:

```text
warning: the compiler differs from the one used to build the kernel
  The kernel was built by: x86_64-linux-gnu-gcc-15 (Ubuntu 15.2.0-4ubuntu4) 15.2.0
  You are using:           gcc (Ubuntu 15.2.0-16ubuntu1) 15.2.0
```

Both identify GCC 15.2.0 but differ in executable name and Ubuntu packaging.
This warning was recorded, not suppressed. The build also reported:

```text
Skipping BTF generation for secureram.ko due to unavailability of vmlinux
```

The ELF module linked successfully, but BTF metadata was not generated. The
running-kernel and vanished-temporary-tree failures occurred before compilation.
The initial multi-tool probe under-reported available compiler/runtime tools;
direct checks and the environment script confirmed they are installed.

The active Linux user is unprivileged and noninteractive `sudo` requires a
password. No runtime privilege elevation, insertion, kernel reconfiguration,
or system package installation was performed. A successful cross-kernel build
does not demonstrate that the module loads, logs, or unloads on this WSL kernel.

## 6. What to run manually

On a Linux 6.x development VM with headers matching its running kernel:

```sh
sudo apt-get update
sudo apt-get install build-essential kmod "linux-headers-$(uname -r)"
make check-env
make W=1
modinfo ./secureram.ko
sudo insmod ./secureram.ko
lsmod | grep '^secureram '
sudo dmesg --color=never | grep -F 'secureram:'
sudo rmmod secureram
test ! -d /sys/module/secureram && echo 'SecureRAM is unloaded'
sudo dmesg --color=never | grep -F 'secureram:'
make clean
```

Use the [full smoke-check acceptance criteria](development.md#manual-runtime-smoke-check),
stop on failures, and record fresh logs. Do not use the alternate-header cache
to produce a module for loading into the current WSL kernel.

## 7. What SecureRAM currently does

The implementation registers init/exit callbacks, embeds project metadata, and
contains clearly prefixed load/unload log messages. The loader owns its static
module memory. There are no driver-owned resources to leak or concurrent public
entry points to protect in M1. Actual callback execution still needs the manual
runtime test above.

## 8. What it deliberately does not do

No block-device registration or `/dev/secureram0`, read/write handling, backing
RAM allocation, crypto, keys, ioctl, authentication tags, management CLI,
advanced statistics, stress infrastructure, or benchmarks were implemented.
M2 and later milestones have not been started.

## 9. Concepts to understand before M2

Understand module lifetime and error unwinding; VFS/filesystem/page-cache/block
layer responsibilities; `bio` versus `request`; sector versus logical block
units; virtual versus physical memory; overflow-safe bounds; sleepable versus
atomic context; safe buffer access; concurrency; and request ownership through
completion and teardown. The [developer guide](development.md#learn-before-m2)
explains how these connect to the planned driver.

## 10. Recommended next milestone

First close the outstanding M1 runtime check on a matching Linux environment.
Then, in a separate M2 request, implement a single plaintext RAM-backed block
device using blk-mq, modular block/store components, bounded ordered work,
validated geometry/bounds, and correct failure/unload paths. Verify raw I/O,
filesystem use, concurrency, and lifetime before adding security features.

**Stop here: M1 code and documentation are complete; runtime verification is
explicitly outstanding.**

## Runtime verification completed

Runtime verification was successfully completed inside an Ubuntu 24.04.5 LTS VirtualBox VM running kernel 7.0.0-38-generic.

Verified successfully:

- module compiled against matching kernel headers
- `sudo insmod ./secureram.ko` succeeded
- initialization message appeared in `dmesg`
- `sudo rmmod secureram` succeeded
- cleanup message appeared in `dmesg`
- `lsmod | grep secureram` returned no result after unloading

Observed initialization message:

`SecureRAM v0.1.0: M1 module loaded (no storage device yet)`

Observed cleanup message:

`SecureRAM: M1 module unloaded`

M1 compile-time and runtime verification is therefore complete.
