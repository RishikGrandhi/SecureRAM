# M3 security architecture and integration foundation report

Started: 2026-10-10. Completed: 2026-10-11 (Asia/Calcutta).
Scope: **M3 only**, version **0.3.0**, branch **`m3-security-architecture`**.

The security architecture and plaintext pass-through scaffolding are complete.
The final target-header build and strict source-style checks pass. **M3 stores
plaintext; its own VM runtime regression is pending.** No encryption, keys or
control endpoint is implemented. Changes are left uncommitted for review.

## 1. Objective and baseline

Prepare the verified M2 block device for future kernel encryption and key
management without implementing either. The original inspection found clean
`main` at `6be414b` (the completed M2 merge), then created the M3 branch without
rewriting history. [The M2 report](m2-report.md) already records successful user
VM acceptance; no reconciliation or repeat of M1/M2 implementation was needed.

The continuation inspected all existing uncommitted M3 changes. Threat/security
design, pass-through code, metadata, test version allowlist, README and overall
architecture changes already existed and were preserved. It completed the
developer/test/tool guidance, regression procedure, this report and final
checks. Existing M1/M2 design, reports and VM procedure remain unchanged.

## 2. Files changed

| Files | Change |
| --- | --- |
| `docs/m3-threat-model.md` (new) | Assets/trust, threat classifications, current versus future invariants. |
| `docs/m3-security-design.md` (new) | Data path, construction comparison, units/tweaks, integrity direction, key lifecycle, control ABI, memory and concurrency design, primary references. |
| `docs/m3-testing.md` (new) | M3 version/log expectations and safe reuse of the existing VM regression procedure. |
| `docs/m3-report.md` (new) | Scope, implementation, evidence, limitations and viva notes. |
| `include/secureram_security.h`, `src/secureram_security.c` (new) | Small internal context owning the store and synchronous plaintext forwarding interface. |
| `src/secureram_block.c` | Use security lifecycle/capacity/range/read/write calls; preserve request handling and resource order. |
| `Kbuild` | Link the security object into the existing composite module. |
| `include/secureram_config.h`, `src/secureram_main.c` | Version 0.3.0, M3 metadata/unload label; load log still explicitly says plaintext RAM. |
| `tests/m2-raw-io.py` | Permit exactly plaintext versions 0.2.0 and 0.3.0; retain fixed target and other safety/behavior checks. |
| `README.md`, `docs/architecture.md`, `docs/development.md` | Current boundary, evidence status, build/lifecycle guidance and revised milestone scope. |
| `tests/README.md`, `tools/README.md` | Regression reuse and future-only management endpoint. |

The store implementation/header, block public header, Makefile and environment
checker are unchanged. No management tool, cipher test, extra runtime allocation
or locking infrastructure was added. Git-ignored `build-m3*.log` files retain
local build/style evidence; `.cache/` holds local validation scratch only.

## 3. Threat-model summary

The future protection target is backing-store disclosure without keys or
plaintext copies elsewhere. Interface validation, ordered lifetime handling,
secret-free logs and eventual privileged control are in scope. Orderly
zeroization can cover owned buffers, but not external copies or crash cleanup.
Root/kernel compromise, malicious modules, hostile hypervisors, whole-RAM
physical/cold-boot/DMA attacks, rollback of all trusted state and durability
are outside the promised boundary. Swap/hibernation, dumps, debugging and host
snapshots require explicit operational assumptions. Ordinary authorized reads
necessarily return plaintext. See [the threat table](m3-threat-model.md).

## 4. Security invariants

Now: all data-bearing block transfers cross the security interface; checked
geometry/ranges, full segment prevalidation, one ordered worker, exact-once
completion, publication-last initialization and drain-before-free remain.
There are no fake key/encrypted states or secret-bearing logs.

Future: no plaintext backing or fallback after crypto introduction, keys outside
backing, explicit key state and zeroization, bounded plaintext lifetime, stable
unit/tweak rules, no key changes during accepted I/O, and authentication before
unit release once integrity exists. These requirements are not M3 guarantees.

## 5. Future encryption construction

Choose Linux Kernel Crypto API `xts(aes)`, **64 combined key bytes** (two
independent 256-bit AES keys). It fits length-preserving rewritable storage.
Reject equal key halves and check provider/setkey errors. XTS provides
confidentiality only: no cryptographic integrity, authentication, wrong-key
detection or replay protection. CTR requires a safe new stream on every rewrite;
GCM requires unique nonces and tag metadata, making it a later integrity option.
The [construction comparison](m3-security-design.md#3-construction-choice)
contains the primary kernel/NIST sources and rationale.

## 6. Crypto data-unit and tweak design

Keep 512-byte kernel sector accounting and the 4096-byte logical block. The
future crypto unit is **4096 bytes**, not one bvec and not one 512-byte sector.
For validated byte offset `b`, index `u = b / 4096`; the XTS input is
`LE64(u)` followed by eight zero bytes. This uses the established large-sector
`plain64` convention. Offsets 0, 4096, 8192 map to indices 0, 1, 2.

Future gather/scatter must assemble full units across arbitrary page segments.
Do not pass local mappings to async providers, or treat vmalloc backing as a
linear scatterlist buffer. No partial logical-block crypto is planned. Rewrites
reuse the same XTS address input intentionally, with equality/history leakage;
that is not a valid GCM nonce policy. Initialize each backing unit as encrypted
zero plaintext before activation; zero-filled RAM is not valid encrypted zeros.

## 7. Integrity strategy direction

Reserve private per-unit tags and generation/address metadata outside advertised
capacity. Compare XTS plus independently keyed encrypt-then-MAC with AEAD before
the integrity milestone. Verify in private staging before READ scatter and
serialize data/tag commits. A Merkle tree adds complexity and still needs a
trusted root/freshness anchor. Tags and replayable counters alone cannot prevent
full rollback. No tag storage, MAC, AEAD execution or tree exists in M3.

## 8. Key lifecycle design

Future states: NO_KEY -> PREPARING -> ACTIVE, ACTIVE <-> LOCKED, destruction
back to NO_KEY, and terminal DYING during unload. Setup failure wipes candidate
state and remains inaccessible. NO_KEY/LOCKED/PREPARING reject I/O; active
crypto failure never falls back to plaintext.

LOCKED deliberately retains the transform/key for reversible access gating.
It is not eviction. Explicit destroy wipes owned sensitive state and discards
the medium; replacement is destroy then load a fresh key and encrypted-zero
medium. Live rekey is unsupported. None of these states is a flag implemented
in M3. The current plaintext behavior is not an exception to a key-state check.

## 9. Privileged control-interface decision

Propose **`/dev/secureramctl`**, a separate root-owned 0600 misc character device
with versioned, fixed-width binary ioctl messages. Check host/initial-user-
namespace `CAP_SYS_ADMIN` on every operation. Planned operations are query,
load, lock, unlock and destroy. The bounded key input is inline, copied once,
validated and wiped; no keys through sysfs, argv, logs or query output.

Block-device ioctl, sysfs and configfs alternatives are evaluated in the design.
Numbers/layouts are not frozen. No UAPI header, ioctl handler, key loader,
control node, CLI or GUI was created. All proposed future tools use the ABI,
not kernel structure layouts.

## 10. Sensitive-memory handling

The design inventories userspace input, kernel key copies, transforms/schedules,
crypto requests, plaintext/ciphertext staging, IV/metadata, backing, request
pages, page cache, provider copies and external dumps/snapshots. It specifies
`memzero_explicit()` and allocation-matched sensitive frees, plus provider
request/transform destruction only after completion. All setup/error/reset/
unload paths must clear owned sensitive state; ordinary end-of-life `memset()`
is insufficient when optimized away. M3 adds no such buffers and retains
ordinary `vfree()` without an erasure claim.

## 11. Concurrency design

Current request synchronization is unchanged: pending-list spinlock and one
ordered reclaim-capable worker; a single hardware queue alone is insufficient.
Future transitions use control mutex -> pending lock. Close admission under
the pending lock, drain accepted work while old key state remains alive, then
change/wipe state and reopen only for ACTIVE. The worker never takes the control
mutex, and no spinlock spans crypto or a wait. Future block-open accounting
must serialize against administration; require unmounted/closed users and
validate core callback/cache behavior before implementation. No live-filesystem
key change or whole-system cache erasure is promised.

## 12. Scaffolding and preserved data path

```text
blk-mq -> bounded pending list -> ordered worker -> validated page segments
       -> secureram_security_read/write (plaintext)
       -> secureram_store_read/write -> RAM (plaintext)
```

The security context embeds the store. Six small functions handle init, destroy,
capacity, range validation, read and write. Return values propagate unchanged;
the adapter still maps errors to block status. No crypto is mixed into request
parsing. The interface retains no buffer references and adds no allocations or
locks. Every store call in the block component was replaced by its boundary
equivalent, including initialization failure unwind and unload.

Creation still acquires state, backing, workqueue, tags and disk before
publication. Teardown keeps the worker runnable through `del_gendisk()`, destroys
the workqueue, releases disk/tags, then destroys security/store and frees state.
The future full-unit transfer loop is explicitly designed, not prematurely
implemented. Geometry and supported operations are unchanged.

## 13. Exact current guarantees and evidence limits

M3 implements the same checked plaintext volatile block-storage semantics as
M2 through an explicit internal boundary: default 64 MiB, 1-256 MiB parameter,
4096-byte logical blocks, full segment iteration, ordered RAM copies, delivered
flush as a no-op, unsupported operations rejected, and fresh zero allocation.
Linux's existing device permissions apply. Source/symbol review and the final
build support this preservation; only M2 has observed VM acceptance so far.
M3 runtime equivalence is not yet an observed result.

## 14. Exact current non-guarantees

No encryption, confidentiality of backing, key loading/derivation/rotation,
authentication, tamper/replay detection, custom access control, secure deletion,
lock/unlock, crash-safe recovery or persistence. No cryptographic guarantee
against root, kernel modules, physical memory acquisition or a hostile VM host.
The name "security" on a source file changes none of these facts. No cipher,
key, ioctl, CLI/GUI, statistics, benchmarks or M4 functionality was added.

## 15. Build and static verification

Final checks: 2026-10-11. Local host: Windows with Ubuntu 26.04 WSL2,
`6.18.33.2-microsoft-standard-WSL2`, GCC 15.2.0. Compile-only target: the existing
Ubuntu `7.0.0-38-generic` prepared headers from M2's user-owned cache. The WSL
running kernel has no matching build tree. No system packages were installed.

Commands from the project root inside WSL (Bash):

```bash
m3_headers=/home/rishik_grandhi/.cache/secureram-m2-20261010/root/usr/src
m3_target="$m3_headers/linux-headers-7.0.0-38-generic"
make KDIR="$m3_target" check-env
make KDIR="$m3_target" clean
set -o pipefail
make KDIR="$m3_target" CC=gcc W=1 2>&1 | tee build-m3-final.log
perl "$m3_headers/linux-hwe-7.0-headers-7.0.0-38/scripts/checkpatch.pl" \
  --no-tree --strict --file src/secureram_main.c src/secureram_block.c \
  src/secureram_security.c src/secureram_store.c include/secureram_block.h \
  include/secureram_config.h include/secureram_security.h include/secureram_store.h
/usr/sbin/modinfo ./secureram.ko
file ./secureram.ko
nm -u src/secureram_block.o
nm -u src/secureram_security.o
nm -u ./secureram.ko
sh -n scripts/check-environment.sh
python3 -m py_compile tests/m2-raw-io.py
git diff --check
# After symbol/metadata inspection:
make KDIR="$m3_target" clean
```

The actual final build was invoked from PowerShell through `wsl --exec` with
the same arguments and its exit code retained. No module/device operation was
invoked. The initial `make KDIR=... W=1` attempt on October 10 failed because
Kbuild selected missing `gcc-13`; the explicit `CC=gcc` build succeeded. The
final continuation repeated a clean build after all source formatting fixes.

| Check | Observed result |
| --- | --- |
| Target preflight | PASS; target release/configuration/symbol files found; explicitly compile-only. |
| Final clean `W=1` build | PASS, all four source objects, MODPOST and module link; no driver-source warnings. |
| Strict target checkpatch | PASS: zero errors, warnings or checks in all eight C/header files. |
| Module metadata / ELF | PASS: version 0.3.0, plaintext description, GPL, uint capacity parameter, x86-64 ELF; vermagic `7.0.0-38-generic`. |
| Boundary symbol inspection | PASS: block object references security functions, security object references store functions; module has no Crypto API imports. |
| Shell/Python syntax | PASS for the existing environment checker and revised raw-test script; the device test was not run. |
| Documentation validation | PASS: 13 Markdown files, 49 local links/anchors, and 27 shell snippets parsed without executing them. |
| Target symbol table | PASS: all 32 imported module symbols found in the target `Module.symvers`. |
| Repository/text checks | PASS: Git diff whitespace, LF/final newlines, no trailing whitespace; M1/M2 evidence and unchanged store/build files match the baseline. No staged changes or new commits. |

Local documentation/import checks used `.cache/validate_m3.py` (Git-ignored)
and wrote `build-m3-static.log`. No test executes documentation commands or
accesses a block device. Build products are cleaned after inspection; rebuild
on the VM for runtime testing.

API research inspected target skcipher/XTS, crypto-wait, block and memory helper
headers, along with official kernel documentation/source and NIST references
linked from the design. Target config has AES, XTS, GCM and SKCIPHER enabled;
this is configuration evidence, not proof that a provider works at runtime.

## 16. Warnings and interpretation

- The target kernel used GCC 13.3.0 (`13.3.0-6ubuntu2~24.04.1`); local GCC is
  15.2.0 (`15.2.0-16ubuntu1`). Kbuild reports the mismatch. Rebuild in the VM
  with the compiler suitable for its running kernel before loading.
- Target pahole version is 125; local version is reported as 0 (absent).
- BTF generation is skipped because the extracted headers lack `vmlinux`.
- The earlier missing-GCC-13 failure is an environment failure, not a passing
  default-toolchain build. Warnings were recorded, not suppressed.
- Earlier continuation-alignment checkpatch findings were corrected; the final
  strict run has no findings. No runtime fault-injection or exhaustive race
  testing has been performed for M3.

## 17. Future VM verification

Follow [the M3 regression procedure](m3-testing.md) on the VM's then-running
kernel: rebuild, load, inspect geometry, run the existing raw/direct test,
check bounds/concurrency and optional ext4, busy unload, invalid parameters,
clean unload/reload and fresh logs. Only `/dev/secureram0` may be a destructive
target, after identity/mount/holder checks. None was executed here.

Record M3 results separately; do not carry M2 PASS into this report. Kernel
health, runtime I/O equivalence, extended error paths and concurrency remain
unverified for this version. Future crypto/key/control/integrity behavior is
not implemented and cannot yet be tested as a SecureRAM feature.

## 18. Viva concepts

- Trace a read/write from VFS/block layer to blk-mq, pending list, worker,
  security boundary and store. Explain why plaintext forwarding is useful
  architecture but provides no encryption.
- Distinguish a 512-byte accounting sector, 4096-byte logical/crypto unit,
  16-byte AES block and a kernel page/bvec. Explain split-unit gather/scatter.
- Explain XTS's two AES keys, address input, safe storage rewrite semantics
  and equality leakage; distinguish that input from GCM's unique nonce rule.
- Separate confidentiality, integrity, freshness, access control, volatility
  and erasure. State exactly which are implemented and which are only designed.
- Explain why zero-filled allocation is not encrypted zero data, and why a
  failed AEAD output must stay private until authentication succeeds.
- Trace one accepted request to one completion; identify the pending lock,
  worker, resource owners, publication point, failure unwind and unload order.
- Explain gate-then-drain before key mutation, why the worker cannot need the
  control mutex during drain, and why lock retaining a key differs from destroy.
- Explain user-copy validation, fixed-width ioctl fields, per-call host
  privilege checks, explicit zeroing and limits involving caches/dumps/VMs.
- Distinguish a clean build, static review, past M2 acceptance and a new M3
  runtime observation. None is interchangeable with the others.

## 19. Recommended M4 direction and stop boundary

After M3 regression/review and an explicit new request, implement real XTS via
the Kernel Crypto API with whole-unit transfers, fail-closed key lifecycle,
minimum privileged control, encrypted-zero initialization and owned-secret
cleanup. Validate offsets, split segments, repeated writes, setup/crypto errors,
locked/keyless behavior, transitions and unload. Authentication remains a
separately specified milestone; later tools/hardening are proposals, not scope
added to M3. **Stop after M3. No automatic commit, push or M4 work.**
