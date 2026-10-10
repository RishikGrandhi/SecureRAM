# SecureRAM

SecureRAM is a university Operating Systems project building a volatile,
RAM-backed Linux block device with a planned kernel security layer.

**Current milestone: M1, version 0.1.0. There is no functional storage yet.**
The module only logs its initialization and cleanup and exposes module metadata.
It does **not** create `/dev/secureram0`, allocate a RAM disk, or encrypt anything.

Read [the architecture](docs/architecture.md) for the data-flow diagram,
component boundaries, security model, and milestone gates. See
[the M1 verification report](docs/m1-report.md) for what was actually tested.

## Layout

```text
SecureRAM/
  Kbuild                         Kernel module object list and include path
  Makefile                       Linux build/check/clean entry points
  src/secureram_main.c            Module lifecycle and metadata
  include/secureram_config.h      Names, version, future geometry defaults
  scripts/check-environment.sh    Read-only environment check
  docs/                          Architecture, workflow, M1 report
  tests/                         Verification guidance; future test home
  tools/                         Future management utility home
```

The existing workspace is the project root; no redundant nested `secureram/`
directory is needed. Later C components will link into the same `secureram.ko`.

## Prerequisites

Use a Linux 6.x development VM with a recoverable snapshot for runtime testing.
You need GNU Make, a suitable C compiler/binutils, `kmod`, and the **matching
build/header tree for the kernel you intend to load into**. The kernel must
enable modules; loading needs administrative privileges and must satisfy its
module-signature policy. Ordinary Windows GCC cannot build a Linux kernel module.

On a Debian/Ubuntu Linux development system, install dependencies manually:

```sh
sudo apt-get update
sudo apt-get install build-essential kmod "linux-headers-$(uname -r)"
```

WSL's Microsoft kernel usually needs a separately prepared matching kernel
build tree; Ubuntu's generic headers do not match it. See
[Windows/WSL details and troubleshooting](docs/development.md).

## Build

Run these commands **inside Linux**, from the project directory:

```sh
make check-env
make W=1
modinfo ./secureram.ko
```

The result is `secureram.ko`. `W=1` asks Kbuild for extra warnings. To select a
different prepared kernel/header tree, pass it explicitly to each command:

```sh
make KDIR=/path/to/kernel/build check-env
make KDIR=/path/to/kernel/build W=1
make KDIR=/path/to/kernel/build clean
```

A successful build against another kernel is a **compile-only** result. Rebuild
for the running kernel before attempting to load. No build target uses `sudo`,
installs packages, or automatically inserts/removes modules.

## Load, inspect, and unload

After building for the running kernel, use these manual commands:

```sh
uname -r
modinfo -F vermagic ./secureram.ko
sudo insmod ./secureram.ko
lsmod | grep '^secureram '
test -d /sys/module/secureram && echo 'SecureRAM is loaded'
sudo dmesg --color=never | grep -F 'secureram:'
sudo rmmod secureram
test ! -d /sys/module/secureram && echo 'SecureRAM is unloaded'
sudo dmesg --color=never | grep -F 'secureram:'
```

The release at the start of `vermagic` must match `uname -r`; this is necessary
but does not replace configuration, symbol-version, or signature compatibility.
Stop on any failed command. Never force insertion or removal.

Expected module messages (kernel timestamps omitted):

```text
secureram: SecureRAM v0.1.0: M1 module loaded (no storage device yet)
secureram: SecureRAM: M1 module unloaded
```

`modinfo` should show version `0.1.0`, license `GPL`, and the SecureRAM project
description. `insmod`/`rmmod` normally print nothing on success. Kernel messages
may include the standard out-of-tree or unsigned-module notices.

Clean generated build products using the same kernel tree as the build:

```sh
make clean
```

## Limitations and roadmap

M1 owns no driver allocations or registered devices. There are no storage I/O
callbacks, keys, access-control interface, integrity tags, statistics, or CLI.
Do not run `mkfs`, mount, or storage benchmarks for this milestone.

| Milestone | Planned outcome |
| --- | --- |
| M1 (this change) | Architecture, buildable module skeleton, documented workflow. |
| M2 | Real plaintext RAM-backed block device using modern blk-mq APIs. |
| M3 | Encryption, key lifecycle, privileged control interface and utility. |
| M4 | Authenticated storage and corruption detection. |
| M5 | Hardening, access-control review, statistics, automated stress coverage. |
| M6 | Benchmarks, security demonstrations, final evaluation documentation. |

Security is a future engineering goal, not a property of the M1 skeleton.
Even the final design will trust the kernel and cannot hide plaintext from
authorized applications or a compromised kernel.

## Learning and license

The [developer guide](docs/development.md) explains Kbuild, lifecycle annotations,
metadata, logs, and the concepts to learn before M2. Source code is licensed
under **GPL-2.0-only**; see [LICENSE](LICENSE).
