# M3 plaintext regression procedure

Date: 2026-10-11 (Asia/Calcutta). Status: **not run for M3 in the VM**.
M1/M2 runtime acceptance remains recorded in their reports. The M3 version is
**0.3.0** and storage is still **plaintext and volatile**. This procedure checks
that the new pass-through boundary preserves the M2 block-device behavior;
it cannot establish encryption, authentication or key lifecycle guarantees.

## Non-destructive local checks

Build against a prepared target header tree using `make check-env`, `make clean`
and `make W=1`, with an explicit `KDIR` and compiler override if needed. Use
the same `KDIR` for cleaning. A build for another kernel is compile-only.
[The M3 report](m3-report.md) records exact commands, diagnostics and results.
Inspect `modinfo`, strict target-kernel checkpatch, source/diff, script syntax,
and documentation links. None of these checks loads a module or writes a device.

## VM regression using the existing procedure

Use the disposable Ubuntu VirtualBox VM. Inspect its **current** `uname -r`,
architecture, compiler and matching headers; do not assume its release has
remained `7.0.0-38-generic`. Rebuild there before loading. Follow
[all sections of the M2 procedure](m2-testing.md) in order with these changes:

| M2 instruction | M3 expectation |
| --- | --- |
| Module version `0.2.0` | `modinfo` and `/sys/module/secureram/version` must report `0.3.0`. |
| M2 description | `SecureRAM M3: plaintext RAM device with security scaffolding`. |
| Fresh load message | `secureram: SecureRAM v0.3.0: /dev/secureram0 ready, 64 MiB, 4096-byte logical blocks (plaintext RAM)` for default capacity. |
| Fresh unload message | `secureram: SecureRAM: M3 module unloaded; device removed and RAM released`. |
| `tests/m2-raw-io.py` | Reuse unchanged commands. Its explicit version allowlist now accepts plaintext M2/M3; its fixed device, identity, geometry and exclusive-open checks remain. |
| Text written by the manual filesystem test | The M2 sample text is merely a payload; it can remain unchanged. |

Before **any destructive action**, confirm `/dev/secureram0` is the intended
SecureRAM block device: match its device number with
`/sys/class/block/secureram0/dev`, check module version and geometry, confirm
it is unmounted and has no holders, and close unrelated openers. The test's
exclusive open is an additional guard, not a substitute for these checks.
Every destructive command must keep the literal target `/dev/secureram0`.
Never substitute the VM's system disk or use force-load/force-unload options.
No destructive/device test was run from the Codex environment for M3.

Record these results separately from the older M2 results:

1. Clean running-kernel build, metadata, successful load and device registration;
   default 67108864-byte capacity and 4096-byte logical/physical blocks.
2. Full initially-zero scan, 1 MiB direct I/O round trip, first/middle/last
   blocks, neighboring-block isolation, concurrent disjoint I/O, EOF/beyond-end
   behavior and flush from the existing raw test.
3. The manual round trip if desired, busy-unload protection, unsupported discard,
   and optional whole-device ext4 create/mount/write/unmount/remount comparison.
4. Clean unload with module/device/sysfs removal and fresh kernel logs. Reload
   and rerun the zero/read-write check on fresh storage, then unload again.
5. Invalid capacity parameters as documented. Recheck a smaller supported
   capacity (e.g. `capacity_mb=1`) with the same identity/raw-test guard if
   validating configurable geometry; avoid unnecessary maximum allocations.

Stop on unexpected errors and record them. Capture command exit statuses,
test PASS/FAIL output, raw comparison evidence, kernel/compiler versions, and
new dmesg messages covering the tested load through unload. Historical matching
log lines are not evidence for this build. Leave the device unmounted and the
module unloaded. Update the M3 report only with actually observed results.

The reusable raw test exercises multi-segment I/O, but does not prove every
possible fragmented bvec layout, allocation failure, or internal malformed
request was injected. Those limits must stay visible in any acceptance record.
Crypto-unit, key-state and tamper tests belong to later implemented milestones.
