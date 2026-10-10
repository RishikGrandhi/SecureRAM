# M2 implementation and verification report

Date: 2026-10-10 (Asia/Calcutta). Scope: **M2 only**. Version: **0.2.0**.

The plaintext block-device implementation builds against the exact target
`7.0.0-38-generic` headers. **M2 VM runtime acceptance is pending.** The agent
did not load this module, perform device I/O, mount it, or format any filesystem.
M1's successful VM runtime verification remains recorded in its unchanged report.

## 1. Milestone objective

Turn the M1 lifecycle skeleton into one real volatile RAM-backed Linux block
device, `/dev/secureram0`, using the block APIs for the user's Ubuntu 24.04.5 LTS
VirtualBox VM. The working tree was clean at `26555a0` before edits. Work is on
`m2-ram-block-device`; M1 commits `768dff3` and `26555a0` are preserved. Changes
are left uncommitted for review; no push or history rewrite was performed.

## 2. Files created

| File | Purpose |
| --- | --- |
| `src/secureram_block.c` | blk-mq disk registration, request dispatch/worker, transfer validation, cleanup. |
| `src/secureram_store.c` | Zeroed allocation, checked byte reads/writes, allocation release. |
| `include/secureram_block.h` | Internal device create/destroy interface. |
| `include/secureram_store.h` | Internal backing-store interface and state. |
| `tests/m2-raw-io.py` | Opt-in, fixed-device direct/raw I/O smoke test for the VM. |
| `docs/m2-design.md` | Concrete design written before substantial implementation. |
| `docs/m2-testing.md` | Exact manual VM commands, optional ext4 and negative checks. |
| `docs/m2-report.md` | This report. |

`build-m2.log` is local, Git-ignored verification output. Downloaded headers and
reference source are in WSL's user-owned
`/home/rishik_grandhi/.cache/secureram-m2-20261010`, outside the repository.

## 3. Files modified

`Kbuild` links the new components; `src/secureram_main.c` orchestrates their
lifecycle; `include/secureram_config.h` centralizes version, capacity, and queue
limits. `README.md`, `docs/architecture.md`, `docs/development.md`,
`tests/README.md`, and `tools/README.md` describe M2 accurately. `.gitignore`
adds Python bytecode exclusions. The existing Makefile and environment checker
already support the required external-module build and remain unchanged.

## 4. Block-layer architecture

One blk-mq hardware queue, up to 64 driver tags, and a named gendisk use current
queue-limit allocation. `add_disk()` allocates an extended device number rather
than hard-coding a major; devtmpfs/udev creates the node. Partition scanning is
disabled. `block_device_operations.owner = THIS_MODULE` pins normal open users.
The disk owns its queue, so there is no extra manual queue destruction.

## 5. Backing-store design

`vzalloc()` supplies zeroed, virtually contiguous RAM without a large physically
contiguous allocation. The store records a `size_t` size and accepts `u64` byte
offsets. Default capacity is 64 MiB; the load-time, read-only `capacity_mb`
parameter allows 1-256 MiB. Logical/physical blocks are 4096 bytes; sector
accounting is 512 bytes. `vfree()` is ordinary cleanup, not verified erasure.

## 6. Synchronization design

A short IRQ-safe spinlock protects the pending request list. One device-owned
work item on an ordered `WQ_MEM_RECLAIM` workqueue performs all backing accesses,
so no large copy lock is held and no runtime allocation is needed. Request list
nodes are preallocated by blk-mq. A device-global work item also avoids tying
workqueue callback lifetime to memory recycled at request completion.

## 7. Request-processing design

Dispatch starts each request once, appends it once, schedules the worker, and
returns `BLK_STS_OK`. The worker removes a request before processing and calls
`blk_mq_end_request()` once. It never touches that request afterward.

Sector bounds are checked before multiplication; full transfer alignment/range
and segment totals are checked before copying. Page-sized segment iteration and
local page mappings handle noncontiguous buffers. Reads copy store to buffer;
writes copy buffer to store. The store rechecks ranges independently. No unsafe
user-pointer operations are used. Errors become `BLK_STS_IOERR` or
`BLK_STS_NOTSUPP`, never an accidental successful transfer.

## 8. Supported operations

READ and WRITE are implemented. Delivered zero-data FLUSH requests succeed as
ordered no-ops because completed writes already reached RAM. No separate
write-back cache/FUA is advertised, so the block layer may filter flushes.
DISCARD, native WRITE_ZEROES, SECURE_ERASE, passthrough/zoned/unknown opcodes,
and atomic-write requests are unsupported. None of these claims implies power
loss durability or encryption.

## 9. Initialization and cleanup

Acquire state, backing, worker queue, tag set, disk/queue, then publish last.
Normal removal calls `del_gendisk()` while the worker can finish accepted I/O,
destroys the workqueue, calls `put_disk()`, frees tags, and finally frees backing
and device state. No request-list lock is held across waits. The exact ownership
table and rationale are in [the design](m2-design.md).

## 10. Error handling

Validate capacity before allocation. Check every allocation and `add_disk()`
result; convert error pointers to errno without dereferencing/freeing them as
valid objects. Labeled unwind paths release each prior acquisition once. An
unpublished disk releases its owned queue through `put_disk()` before tags are
freed. Driver init returns the failure to the loader and logs the failing stage
where applicable. Partial allocation/publication failures were reviewed in code;
they have not been exhaustively fault-injected at runtime.

## 11. Commands executed

Inspection included `git status --short --branch`, clean tracked/index/untracked
checks, `git log`, `rg --files`, reading all requested documents and source,
checking applicable ancestor instructions, and inspecting WSL/kernel/tool state.
Then `git switch -c m2-ram-block-device` created the development branch.

Ubuntu's target header packages were downloaded with `curl` over HTTPS and
extracted using `dpkg-deb -x` in the private cache, without installing anything
system-wide. The amd64 package's SHA-256 matched the value on Ubuntu's
[download page](https://packages.ubuntu.com/noble-updates/amd64/linux-headers-7.0.0-38-generic/download).
Package version: `7.0.0-38.38~24.04.4`.

```text
linux-headers-7.0.0-38-generic_7.0.0-38.38~24.04.4_amd64.deb
  SHA-256: 44e6fa84a94dc7f8efbb85d48822a0030bd1e0e20f3696924f4d86834239931f
linux-hwe-7.0-headers-7.0.0-38_7.0.0-38.38~24.04.4_all.deb
  SHA-256: 8806dc00159307a485e7608ed52cc2482b0cdb6211550f55354586afef5e7e5e
```

Both came from `https://archive.ubuntu.com/ubuntu/pool/main/l/linux-hwe-7.0/`.
Official v7.0 `genhd.c`, `blk-mq.c`, `blk-flush.c`, and `null_blk` source were
consulted for disk ownership, allocation signatures, flush behavior, and cleanup.
WSL lacked `rg`, so local header/source searches there used `grep`/`sed`.

The normal `make clean` and `make W=1` were attempted first and failed because
the running WSL kernel still lacks its matching build tree. The successful
target-header checks used the following Bash commands from the project root:

```bash
headers=/home/rishik_grandhi/.cache/secureram-m2-20261010/root/usr/src
target="$headers/linux-headers-7.0.0-38-generic"
make KDIR="$target" check-env
make KDIR="$target" clean
set -o pipefail
make KDIR="$target" CC=gcc W=1 2>&1 | tee build-m2.log
/usr/sbin/modinfo ./secureram.ko
file ./secureram.ko
nm -u ./secureram.ko
perl "$headers/linux-hwe-7.0-headers-7.0.0-38/scripts/checkpatch.pl" \
  --no-tree --strict --file src/secureram_main.c src/secureram_block.c \
  src/secureram_store.c include/secureram_block.h include/secureram_store.h \
  include/secureram_config.h
sh -n scripts/check-environment.sh
python3 -m py_compile tests/m2-raw-io.py
git diff --check
make KDIR="$target" clean
```

Additional checks validated documentation shell snippets without executing them,
local links/anchors and text formatting, and compared undefined module symbols
with the target's `Module.symvers`. The raw test was invoked **without root** to
check its refusal path; it exited before opening/writing any device. No real
raw/device/filesystem test was run. Changes and new source files were inspected
directly as well as through Git diff. `docs/m1-report.md` remains identical to
the M1 commit.

## 12. Build results

The x86-64 `secureram.ko` compiled and linked successfully for
**7.0.0-38-generic**, including successful MODPOST. Version `0.2.0`, license
`GPL`, the plaintext description, and the unsigned-int `capacity_mb` parameter
were verified with `modinfo`. Vermagic begins with `7.0.0-38-generic` and includes
SMP, preemption, module unloading, and symbol versioning. Build products were
cleaned afterward; rebuild in the VM before loading.

## 13. Warnings and interpretation

There are **no driver-source compiler warnings or MODPOST errors**. Kbuild
reports these environment differences:

- Target kernel compiler: GCC 13.3.0 (Ubuntu `13.3.0-6ubuntu2~24.04.1`);
  available WSL compiler: GCC 15.2.0 (Ubuntu `15.2.0-16ubuntu1`). Compilation
  passed, but the VM should build with its matching toolchain.
- Target pahole version: 125; available version reported as 0 (absent).
- BTF generation skipped because the extracted headers do not include `vmlinux`.

These diagnostics were retained in the build log, not suppressed. Initial
checkpatch alignment/lock-comment findings and its preference for the current
`kzalloc_obj()` helper were fixed; the final strict check reports zero errors,
warnings, or checks across all six C/header files. The missing WSL build tree
is an environment failure, not a successful build or runtime test.

## 14. What was verified automatically

- Clean starting Git state and preservation of M1 history/report.
- Target-header preflight, compilation with `W=1`, MODPOST, and module link.
- Metadata, x86-64 ELF, and kernel-import/symbol inspection.
- Strict target-kernel checkpatch, existing shell script syntax, and Python syntax.
- The test script's unprivileged refusal path (expected exit 1 before device access).
- Documentation shell syntax, local links, LF/whitespace inspection, Git diff,
  and generated-module cleanup.

Code review also traced acceptance/completion, list ownership, arithmetic,
page mappings, and every partial-initialization/unload path. Static review is
not proof that runtime races or allocation-failure behavior have been tested.

## 15. What requires VM runtime verification

All M2 runtime acceptance remains pending: successful load; device/sysfs
appearance; lsblk/capacity; initial zeroes; exact raw read/write; boundary behavior;
concurrent I/O; busy-unload protection; unsupported discard; optional ext4;
successful removal; reload/zeroing; and invalid-parameter handling. The local
runtime is `6.18.33.2-microsoft-standard-WSL2`, so the target module was not
inserted here. No remote access to the user's VirtualBox VM was assumed.

## 16. Exact VM runtime-test commands

The complete ordered commands, expected outputs, and optional destructive
whole-device ext4 test are in [the M2 runtime procedure](m2-testing.md). Its core
sequence, after installing matching headers/dependencies in the VM, is:

```sh
make check-env
make clean
make W=1
modinfo ./secureram.ko
sudo insmod ./secureram.ko capacity_mb=64
sudo udevadm settle
lsmod | grep '^secureram '
sudo dmesg --color=never | grep -F 'secureram:'
lsblk -b -o NAME,MAJ:MIN,SIZE,TYPE,LOG-SEC,PHY-SEC /dev/secureram0
sudo blockdev --getsize64 /dev/secureram0
sudo python3 tests/m2-raw-io.py
# Unmount first if you performed the optional filesystem test.
sudo rmmod secureram
sudo udevadm settle
test ! -e /sys/module/secureram
test ! -e /sys/class/block/secureram0
test ! -e /dev/secureram0
sudo dmesg --color=never | grep -F 'secureram:'
```

Expect 67108864 bytes. Stop on any unexpected error. Never force load/unload or
change a destructive command's target away from `/dev/secureram0`.

## 17. Implemented capability

The driver now contains a complete plaintext volatile block-device data path,
with validated configurable capacity, zero-initialized backing, multi-segment
reads/writes, serialized access, and explicit cleanup. It is designed to support
normal block tools and a filesystem on the whole disk; those outcomes still
need the VM evidence above.

## 18. Deliberately absent

No encryption/Crypto API, keys, key rotation/derivation, integrity tags, ioctl
management, GUI, management CLI, advanced telemetry, secure-wipe controls,
benchmark framework, persistence, or network functionality was added. The Python
file is a test, not a management interface. M2 is not secure storage yet.

## 19. Viva concepts

Explain how a block device differs from process memory; how VFS, filesystems,
page cache, bios and requests relate; why a sector is not a logical block or
page; why `vzalloc()` fits this backing store; why request segments must be
mapped/iterated; how checked subtraction avoids overflow; and why a short
spinlock plus one sleepable worker is sufficient for this access model.

Trace request ownership from `queue_rq()` to one completion, and resource
ownership from acquisition to error unwind or unload. Explain why `.owner`
prevents normal unload of an open device, why queue draining needs a live worker,
why `put_disk()` participates in queue cleanup, and why flush/volatility do not
equal persistence or secure erasure. Also distinguish a build, a source review,
and an observed runtime test.

## 20. Recommended M3 direction

First run and record M2's VM acceptance checks. In a separate M3 request, review
the threat model and storage crypto construction, then design the key lifecycle,
privileged control ABI, and temporary-buffer cleanup around the existing worker
and store boundary. Finalize nonce/tweak and future authentication requirements
before implementing encryption. **Stop after M2; no M3 code is present.**

## Runtime verification completed

M2 runtime verification was successfully completed in the Ubuntu VirtualBox test VM running Linux 7.0.0-38-generic.

Verified successfully:

- module built against the running kernel
- module loaded with `insmod`
- `/dev/secureram0` was created
- `lsblk` identified SecureRAM as a 64 MiB block device
- 1 MiB of random data was written to `/dev/secureram0`
- the same 1 MiB was read back
- SHA-256 hashes of written and read-back data were identical
- `cmp` confirmed byte-for-byte equality
- an ext4 filesystem was successfully created on `/dev/secureram0`
- the filesystem mounted successfully
- normal filesystem file I/O succeeded
- the filesystem unmounted cleanly
- `rmmod secureram` succeeded
- `/dev/secureram0` disappeared after unload
- kernel log confirmed the backing RAM was released
- no SecureRAM-related kernel Oops, BUG, panic, or protection fault was observed

M2 compile-time and runtime acceptance criteria are therefore complete.
