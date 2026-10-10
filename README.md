# SecureRAM

SecureRAM is a university Operating Systems project implementing a volatile
Linux block device backed by memory owned by a kernel driver.

**M2, version 0.2.0:** the driver implements `/dev/secureram0`, with a default
capacity of **64 MiB** and **4096-byte logical blocks**. It supports real block
reads/writes and whole-device filesystems. **M2 storage is plaintext and exists
only in RAM.** Unloading the module loses all contents; reload creates zeroed
storage. Encryption and other security features are later milestones.

M1 and M2 are complete and runtime-verified in the user's Ubuntu VirtualBox VM.
M2's compile/static evidence and successful VM acceptance results are recorded
in [the M2 report](docs/m2-report.md). M2 remains plaintext, volatile storage;
runtime acceptance is not a claim of encryption or other later security features.

## Architecture and layout

```text
Applications / filesystem -> Linux block layer -> blk-mq
  -> bounded pending list -> ordered worker -> checked RAM byte store

SecureRAM/
  Makefile, Kbuild                External-module build
  src/secureram_main.c            Module parameters and lifecycle
  src/secureram_block.c           Disk, queue, request worker, cleanup
  src/secureram_store.c           RAM allocation and bounded byte transfers
  include/                       Internal interfaces and central constants
  scripts/check-environment.sh    Read-only prerequisite inspection
  tests/m2-raw-io.py              Opt-in VM raw/direct I/O checks
  docs/                          Architecture, design, workflow, test plan, reports
  tools/                         Reserved for later administration tools
```

The [M2 design](docs/m2-design.md) explains resource ownership, concurrency,
overflow checks, multi-segment transfers, supported operations, and failure
unwinding. The [overall architecture](docs/architecture.md) preserves the planned
security-layer boundary without implementing it prematurely.

## Prerequisites and build

Primary runtime target: **Ubuntu 24.04.5 LTS, Linux 7.0.0-38-generic, x86-64**, in
the user's VirtualBox VM. Use the exact running kernel's build/header tree and
its suitable compiler. Current APIs include queue limits supplied at disk
allocation and disk-owned queue cleanup; there are no ancient-kernel shims.

Inside Linux, from the checkout:

```sh
sudo apt-get update
sudo apt-get install build-essential kmod "linux-headers-$(uname -r)"
make check-env
make clean
make W=1
modinfo ./secureram.ko
```

Build as an ordinary user. Root is needed only for explicit installation and
device operations. Kernel signature policy must permit the module. For an
alternate prepared target tree:

```sh
make KDIR=/path/to/kernel/build check-env
make KDIR=/path/to/kernel/build clean
make KDIR=/path/to/kernel/build W=1
```

An alternate-target build is compile-only unless it matches the running kernel.
WSL's Microsoft kernel is separate from Ubuntu's generic kernels; do not load
a generic-kernel module into WSL. See [the developer workflow](docs/development.md).
Build commands never load modules or write to a device automatically.

## Load, inspect, and unload

After building for the running kernel:

```sh
uname -r
modinfo -F vermagic ./secureram.ko
sudo insmod ./secureram.ko capacity_mb=64
sudo udevadm settle
lsmod | grep '^secureram '
lsblk -b -o NAME,MAJ:MIN,SIZE,TYPE,LOG-SEC,PHY-SEC /dev/secureram0
sudo blockdev --getsize64 /dev/secureram0
sudo dmesg --color=never | grep -F 'secureram:'
```

Expect **67108864 bytes** and a fresh message:

```text
secureram: SecureRAM v0.2.0: /dev/secureram0 ready, 64 MiB, 4096-byte logical blocks (plaintext RAM)
```

`capacity_mb` means MiB and accepts **1-256**, default 64. It is read-only after
load, is checked before allocation, and does not guarantee allocation succeeds
under memory pressure. The kernel assigns major/minor numbers dynamically.
There are no partitions; format/mount the whole device if desired.

To unload, first unmount SecureRAM and close every user of the device:

```sh
findmnt --source /dev/secureram0
# If mounted, unmount the displayed mountpoint before continuing.
sudo rmmod secureram
sudo udevadm settle
test ! -e /sys/module/secureram && echo 'Module removed'
test ! -e /dev/secureram0 && echo 'Device removed'
sudo dmesg --color=never | grep -F 'secureram:'
make clean
```

Expected message: `secureram: SecureRAM: M2 module unloaded; device removed and
RAM released`. A mounted/open device pins the module, so a busy-unload failure
is expected. Never force unload. Use the same `KDIR` when cleaning an alternate
build.

## Verify in the VM

Follow [the exact M2 test procedure](docs/m2-testing.md) for identity/capacity
checks, direct raw I/O with exact comparison, end-of-device behavior, concurrent
requests, optional ext4, busy-unload protection, parameter validation, and reload.
On a fresh, unmounted device, its opt-in raw test is:

```sh
sudo python3 tests/m2-raw-io.py
```

This overwrites **only `/dev/secureram0`**, takes no alternative device argument,
and expects initially zeroed storage. It uses exclusive/direct I/O with aligned
buffers and fails if the device identity or geometry is unexpected. Reload
before repeating it. Formatting commands in the guide are optional and manual.

## Supported behavior and limitations

| Operation | Behavior |
| --- | --- |
| READ / WRITE | Bounds-checked transfers through all request page segments. |
| FLUSH | Ordered no-op if delivered; no separate write-back cache is advertised. |
| DISCARD / native WRITE_ZEROES / other opcodes | Not advertised; rejected if dispatched. |

There is one device, one hardware queue, up to 64 driver tags, and a single
ordered worker. Geometry/capacity are immutable while loaded. No persistence,
encryption, keys, authentication, ioctl control ABI, CLI, GUI, custom statistics,
secure-wipe controls, or benchmark framework exists. Ordinary `vfree()` cleanup
does not establish secure erasure, and a flush does not make RAM persistent.
Linux's ordinary device permissions apply; there is no custom access-control
policy in M2. VM host swap/snapshots are outside the driver-owned RAM boundary.

## Roadmap and learning

| Milestone | Outcome |
| --- | --- |
| M1 (complete) | Module foundation, architecture, verified VM lifecycle. |
| M2 (complete) | Runtime-verified plaintext RAM block device and reusable VM test procedure. |
| M3 | Reviewed encryption design, key lifecycle, privileged control and utility. |
| M4 | Authenticated storage and corruption detection. |
| M5 | Hardening, access-control review, statistics, broader automated stress coverage. |
| M6 | Benchmarks, security demonstrations, final evaluation documentation. |

Read [the M2 design](docs/m2-design.md) and [viva notes](docs/m2-report.md#19-viva-concepts)
to connect request completion, memory mappings, locks, and teardown to OS
concepts. Source code is **GPL-2.0-only**; see [LICENSE](LICENSE).
