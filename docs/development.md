# Developer workflow and kernel learning notes

## Choose a runtime test environment

Use the project's Ubuntu 24.04.5 LTS VirtualBox VM running
**Linux 7.0.0-38-generic** as the M2 runtime target. Record `uname -r`, the
distribution, architecture, and compiler version with results. M1's VM runtime
verification and M2's VM runtime acceptance are complete. M2 uses this target's
modern block interfaces; a build on one kernel does not establish compatibility
with all kernel versions.

M3 preserves those interfaces through a plaintext security boundary. Its VM
regression is pending; use [the M3 procedure](m3-testing.md) for current version
expectations and keep prior M2 evidence separate.

Build as an ordinary user. Use administrative privileges only for explicit
dependency installation and module lifecycle operations. If `sudo` requires a
password, run those steps yourself in a terminal; no script collects passwords.

### Debian/Ubuntu prerequisites

```sh
uname -r
gcc --version
sudo apt-get update
sudo apt-get install build-essential kmod "linux-headers-$(uname -r)"
```

This requires a distribution-packaged running kernel whose matching headers are
available. If you upgrade the kernel, reboot into the intended kernel and check
the header match again. Follow your distribution's signing/enrollment procedure
if module signature enforcement is enabled; do not bypass that policy.

### Windows and WSL2

From this project's Windows host, enter the installed WSL distribution:

```powershell
wsl -d Ubuntu
```

Then use Linux commands:

```sh
cd /mnt/c/Coding/Projects/SecureRAM
make check-env
```

Keep source files LF-terminated; `.gitattributes` and `.editorconfig` declare
this. Invoke the checker through `sh` so it does not depend on executable bits
on a Windows mount. A Linux-home checkout usually builds faster than `/mnt/c`.
Keep the build path free of spaces because kernel build paths do not reliably
support them.

The running WSL kernel is supplied separately from Ubuntu user space. Installing
Ubuntu's generic headers does not supply the matching Microsoft kernel build
tree. WSL is not inherently incapable of loading modules, but runtime validation
requires matching build artifacts and privileges. For this project, a normal
Linux VM is the simplest reproducible route. If intentionally developing against
a custom WSL kernel, follow Microsoft's [WSL kernel build instructions](https://github.com/microsoft/WSL2-Linux-Kernel)
and retain its exact configuration and generated artifacts. SecureRAM does not replace
or reconfigure the user's WSL kernel.

## Build and inspect

```sh
make help
make check-env
make clean
make W=1
modinfo ./secureram.ko
```

For a build log with the correct failure exit status, use **Bash**:

```bash
set -o pipefail
make W=1 2>&1 | tee build-m3.log
```

Inspect the complete log, including compiler messages, MODPOST, and final link.
`W=1` enables additional diagnostics; it is not a substitute for code review.
Use `make clean` first when changing header trees or toolchains; incremental
builds may otherwise reuse objects. Pass the same `KDIR` when cleaning.

The top-level Makefile delegates compilation to the kernel's Kbuild system;
`Kbuild` links the main, block, security, and storage objects into a composite
`secureram.o` and adds the local include directory. There is no hand-written
compiler command with guessed kernel flags.
See [Building External Modules](https://docs.kernel.org/kbuild/modules.html).

An alternate `KDIR` is useful for compile-only checks. It must be a prepared
build/header tree with generated configuration and symbol information, not
`/usr/include/linux` and not an unpacked, unconfigured source tarball. In
particular, `modules_prepare` alone does not produce `Module.symvers`.

`sh scripts/check-environment.sh [KDIR]` reports missing tools/files, the selected
target release when known, and basic runtime constraints. It makes no changes
and does not claim to prove ABI compatibility or loading permissions. Its `CC`
override accepts one compiler executable name/path (e.g. `CC=clang`), not a
compound wrapper command. Kbuild's own compiler selection remains authoritative.

## Manual runtime smoke check

Use the [M3 regression procedure](m3-testing.md) on the matching kernel. It reuses
the [M2 VM test procedure](m2-testing.md). The full
sequence includes direct raw I/O, bounds, concurrency, optional ext4, module
ownership, unload/reload, and parameter checks. In a second terminal watch new
messages without clearing logs:

```sh
sudo dmesg --follow --color=never
```

Acceptance criteria:

1. `modinfo` reports the expected author, description, version, and license.
2. `insmod ./secureram.ko` succeeds and `/sys/module/secureram` exists.
3. A **new** prefixed M3 load message appears. Old matching messages alone do
   not prove the current load worked; correlate timestamps and module state.
4. `/sys/class/block/secureram0` and `/dev/secureram0` appear with correct
   capacity/geometry. The raw tests pass; optional whole-device ext4 works.
5. After unmounting/closing users, `rmmod secureram` succeeds, the module and
   device disappear, and a new unload message
   appears without an oops, warning backtrace, or other lifecycle error.
6. Reload and rerun the initial-zero check to verify fresh storage.

M2's disk-owned queue must drain before backing/tag memory is freed. Keep its
worker running during `del_gendisk()`, then destroy the workqueue, release the
disk and tags, and free backing/state. See [the design](m2-design.md) for failure
unwinding. Leave the module unloaded after checking. Do not use `rmmod -f`,
`insmod -f`, or create a device node manually.

## Troubleshooting

| Symptom | Interpretation and next action |
| --- | --- |
| Missing `/lib/modules/.../build` | Matching headers/build tree are absent. Supply them or select an explicit compile-only `KDIR`. |
| `gcc`, `cc`, `make`, or linker missing | Install the build toolchain in Linux. A Windows compiler is insufficient. |
| `modinfo`/`insmod` missing from PATH | Check `/usr/sbin`, `/sbin`, and the `kmod` package. A non-login WSL command may have a different PATH. |
| Kernel/compiler version warning | Compare target build compiler and current compiler; use a matching toolchain for definitive runtime validation. Do not hide warnings. |
| `Skipping BTF generation ... unavailability of vmlinux` | The headers lack the kernel's BTF input. The module may still compile/link; record this diagnostic. |
| `Invalid module format` | Read the kernel log; check release, configuration, architecture, and symbol versions. Rebuild for the exact target. |
| `Key was rejected by service` / signing error | Use a module signed with a key trusted by that kernel. |
| `Operation not permitted` | Check module capability, signature/lockdown policy, container restrictions, and `/proc/sys/kernel/modules_disabled`. |
| `File exists` at insertion | A module with that name is already loaded; inspect it before acting. |
| `Module is in use` at removal | Unmount SecureRAM and close legitimate holders; its module owner protects active users. Never force removal. |
| No visible `pr_info` on console | Informational logs may be filtered on the console. Read the kernel ring buffer with adequate permission. |

An out-of-tree module can set the kernel's out-of-tree taint flag even with a
GPL license. Unsigned modules may also taint a permissive kernel. These notices
are distinct from compiler warnings and kernel faults; report them accurately.

## Understand the module foundation

- `module_init()` and `module_exit()` register loader callbacks, not a user-space
  `main()`. Initialization returns zero on success and a negative errno on
  failure. M2 unwinds each successful acquisition when a later step fails.
- `__init` marks initialization-only code so the kernel can reclaim it after
  successful initialization. `__exit` describes the unload path for a module.
  Persistent runtime code must not call code that has already been discarded.
- `static` keeps these function names private to this translation unit.
- `pr_info()` writes to the kernel log. `pr_fmt()` consistently prefixes messages
  with `secureram:`. Logs must never contain future key/plaintext material.
- `MODULE_*` declarations embed metadata inspected by `modinfo`.
  `MODULE_LICENSE("GPL")` is the kernel's recognized license marker; SPDX and
  the repository license specify GPL version 2 only. A license marker is not
  a security check or module signature.
- `(u64)capacity_mb * SZ_1M` converts the validated parameter to bytes without
  narrow-integer overflow. The header centralizes geometry and bounds, while
  storage allocation and disk publication are explicit lifecycle steps.

## Learn before M2

1. User versus kernel address spaces; why user pointers need safe copy helpers
   at a control boundary and are not ordinary kernel pointers.
2. VFS, a filesystem, the page cache, a block device, and the block layer;
   distinguish a `bio` from a `request` and a `/dev` name from actual storage.
3. Linux's 512-byte sector accounting versus a device's logical block size;
   byte offsets, alignment, overflow-safe bounds checks, and advertised capacity.
4. Virtual versus physical contiguity, pages, allocation failure, `kmalloc`
   versus `vmalloc`, and mapping request segments without assuming contiguity.
5. Sleepable versus atomic context, worker ownership, mutex/spinlock rules, and
   why one blk-mq hardware queue does not eliminate races.
6. Publishing a device only after initialization, returning correct I/O status,
   completing each request exactly once, failure unwinding, and draining work
   before freeing storage.

M2 implements the plaintext device within these boundaries; its VM runtime
acceptance is recorded in [the M2 report](m2-report.md). Cryptography and its
control ABI remain later milestones.

For M3, also understand why the pass-through layer adds no confidentiality,
why request segments are not crypto units, why XTS does not authenticate bytes,
and why key changes must close admission and drain work before freeing secrets.
See [the security design](m3-security-design.md) and
[M3 viva notes](m3-report.md#18-viva-concepts).
