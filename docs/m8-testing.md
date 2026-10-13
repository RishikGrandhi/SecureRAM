# M8 verification: local checks and pending Ubuntu acceptance

M8 is implemented on `m8-secure-snapshots`, driver/CLI/dashboard 0.8.0, ABI 1,
features 31. Local compile/static/automated and labelled browser-fixture checks
passed on 13 October 2026. **Real Ubuntu M8 kernel, HTTP and Firefox acceptance
are NOT RUN.** The [report](m8-report.md) records evidence and limitations.

## Reproduce local checks (no device access)

In the existing WSL Ubuntu shell, from `/mnt/c/Coding/Projects/SecureRAM`:

```sh
python3 tests/check-m8-local.py \
  --kdir /home/rishik_grandhi/.cache/secureram-m2-20261010/root/usr/src/linux-headers-7.0.0-38-generic \
  --checkpatch /home/rishik_grandhi/.cache/secureram-m2-20261010/root/usr/src/linux-hwe-7.0-headers-7.0.0-38/scripts/checkpatch.pl
```

This runs clean production/M5/combined builds, old and new native/compat ABI
objects, imported-symbol and production-exclusion checks, strict checkpatch,
CLI tests, actual snapshot/store code under ASan/UBSan, inherited M7 HTTP/UI and
harness tests, new snapshot HTTP/UI and harness tests, and per-file shell syntax.
It uses the installed GCC/Python/Node; no dependencies are downloaded. ShellCheck
is reported NOT RUN when absent. Logs remain ignored, including `build-m8-local.log`
and the reused `build-m6-*.log` files. Compilation for Ubuntu headers in WSL must
never be followed by inserting that module into the Microsoft kernel.

Focused commands after a small change:

```sh
python3 tests/check-m8-core.py
python3 tests/check-m8-cli.py
python3 tests/check-m7-local.py
python3 tests/check-m8-dashboard.py
node tests/check-m8-ui.js
bash tests/check-m8-vm-harness.sh
```

## Transfer the committed branch without pushing

The delivered `.cache/m8-secure-snapshots.bundle` contains the committed branch
and its history, without ignored logs, screenshots, binaries or credentials.
Copy this file into `~/Downloads/m8-secure-snapshots.bundle` in the Ubuntu VM.
It can also be regenerated on the development machine after commits:

```sh
git bundle create .cache/m8-secure-snapshots.bundle m8-secure-snapshots
git bundle verify .cache/m8-secure-snapshots.bundle
```

In the VM, as the ordinary checkout owner, first inspect the working tree and
stop if it contains work you need to preserve:

```sh
cd ~/SecureRAM
git status --short --branch
git bundle verify ~/Downloads/m8-secure-snapshots.bundle
git fetch ~/Downloads/m8-secure-snapshots.bundle \
  m8-secure-snapshots:m8-secure-snapshots
git switch m8-secure-snapshots
git status --short --branch
git log --oneline --graph --decorate -10
git rev-parse HEAD
uname -r
```

Compare the **full HEAD SHA** to the delivery message. Do not force-update an
existing divergent branch, discard work, merge into main, or use a short SHA.
If you later choose to publish the feature branch, ordinary fetch/checkout can
replace the bundle transfer; this implementation did not push it.

## Full automated VM run

Use the disposable Ubuntu VirtualBox guest and its current matching headers.
Run from a clean committed checkout as its ordinary owner, through sudo so
SUDO_USER identifies that builder. No preexisting module, nodes, mount or backend
should be present. The harness rejects WSL, mismatched kernel/header artifacts,
wrong branch/full commit, dirty checkout, ambiguous device arguments and
preexisting device state. It builds as the ordinary user and owns only the
modules/mounts/backend that it starts. All raw/format targets remain literally
`/dev/secureram0`, checked for identity, mount/holder/swap state. No real disk
target is accepted.

After comparing the full SHA above with the reviewed delivery SHA:

```sh
export M8_EXPECTED_COMMIT="$(git rev-parse HEAD)"
sudo --preserve-env=M8_EXPECTED_COMMIT bash tests/run-m8-vm-acceptance.sh
```

The stronger copy/paste alternative is to put the delivery's literal 40-character
SHA in `sudo env M8_EXPECTED_COMMIT=<reviewed-full-sha> bash
tests/run-m8-vm-acceptance.sh`. Do not run another dashboard or administrator
during the suite. The harness does not ask for confirmation after invocation;
it is explicitly destructive to SecureRAM's volatile contents.

Expected phases (prepared, **not observed here**):

1. All M7/M6 production assertions: baseline/status/stats/CLI/UAPI/privilege,
   random key, full raw I/O and accounting, lock/unlock, destroy/rekey, ext4
   sync/remount, mounted EBUSY and HTTP security checks after unload.
2. Fresh production M8: NO_KEY negative create/restore, all new malformed headers,
   EFAULT, ENOTTY, output reserved zeroing, passed-fd EPERM; then ACTIVE full-device
   deterministic DATA_A, snapshot via HTTP, DATA_B, restore via HTTP, full read
   hash comparison (`SHA_A != SHA_B`, `SHA_RESTORED == SHA_A`) and no new MAC failure.
   Post-restore direct writes/reads proceed; concurrent mutations while the block
   fd is open return EBUSY. LOCKED rejects create/restore and allows delete.
   Eight full-device cycles and eight competing creates test single-slot
   publication/counters. Destroy/rekey invalidates generation-1 state; generation-2
   restore reports absent, reads zeros, and a new generation-2 slot is created.
3. Unload with a populated ACTIVE slot, reload and require absent slot, zero
   sizes/generation/counters and NO_KEY; unload again. This proves observed
   lifecycle behavior when run, not forensic physical erasure.
4. All inherited combined M4/M5 tamper/index/generation/failed-read/counter/recovery
   tests with HTTP observations. Then a separate M8 test captures a slot,
   corrupts live ciphertext through the existing M5 test hook, latches failure,
   rejects snapshot restore/create, allows delete without clearing the latch,
   and destroys/unloads cleanly.
5. Inherited 0/257 rejection and 1/256 MiB lifecycle/capacity regressions.
6. Final clean production build, test-hook exclusion, raw/ext4/mounted-busy
   regression, destroy/unload, both nodes/sysfs absent, backend orderly shutdown,
   and fresh kernel-health review. M8 adds locking/sleep/free fault signatures to
   the existing WARN/BUG/Oops/panic/trace checks.

The evidence directory is printed as `.cache/m8-vm/<UTC-time>-<pid>/`. Read
`summary.txt`, `status.tsv`, `main.log`, `snapshot.log`, `snapshot-tamper.log`,
production/tamper/capacity/final logs, build/exclusion proofs, `dmesg.log` and
kernel-health context. Each group starts NOT RUN and becomes PASS only after
all its assertions. Failures stop later phases and preserve failed logs. Lost
dmesg, failed cleanup or a crashed backend cannot produce overall PASS.
The startup URL/token stays in pipes/process memory and is not logged. Never
paste that credential into a report. Send the SHA, summary and three hashes
when requesting manual acceptance.

Kernel ENOMEM/stale-field fault injection, compat ioctl runtime, lockdep/KASAN/
kmemleak and synthetic pending-request races are additional campaigns. Local
C tests cover failure/zeroing/stale guard logic; they do not replace those kernel
campaigns. Snapshot peak memory is live store plus one slot (about 129 MiB at
64 MiB capacity, 516 MiB at maximum, plus allocator/crypto/kernel overhead).

## Real Ubuntu Firefox acceptance after automated PASS

The final automated phase leaves a production module built and unloaded.
In a first terminal, explicitly start a separate manual session:

```sh
sudo modprobe hkdf
sudo insmod ./secureram.ko capacity_mb=64
sudo udevadm settle
sudo ./tools/secureramctl status --json
sudo ./tools/secureramctl snapshot status --json
sudo python3 -I dashboard/server.py
```

Open the freshly printed URL in the ordinary user's Firefox inside this VM.
Confirm driver/CLI/dashboard 0.8.0, ABI 1, features 31, NO_KEY and absent slot.
Load Random Key -> ACTIVE; Create Snapshot -> available, 64 MiB ciphertext +
512 KiB tags, matching generation, created count increments. Create becomes
disabled while occupied. Restore opens a clear destructive dialog: wrong/lowercase
confirmation must not enable Confirm, Cancel must preserve state, exact RESTORE
must succeed and retain the slot. Delete requires exact DELETE; Cancel preserves
it, successful Delete makes it absent. CLI status must agree after each action.

Repeat Create -> Lock: create/restore disabled, slot retained, Delete allowed.
Unlock resumes normal actions; destroy clears the slot and returns NO_KEY.
Check wide and narrow layouts, readable labels, no horizontal overflow or
overlap, and existing statistics/lifecycle behavior. Stop the backend: stale
observations must disable all controls. Restart, reopen its new URL, and confirm
reconnection. These UI actions do not themselves verify rollback bytes; the
automated raw-I/O hashes do. Record browser version, SHA and observed results.

For a minimal independent raw rollback demo, with backend actions paused and no
block users, use the existing safe guard before each destructive operation:

```sh
# Run this block in a fresh Bash terminal at ~/SecureRAM; it sources definitions only.
export SR_MILESTONE=8
source tests/m5-vm-common.sh
sudo ./tools/secureramctl load-random  # only if currently NO_KEY
sudo env SR_MILESTONE=8 bash -c 'source tests/m5-vm-common.sh; m5_identity_guard 67108864'
sudo dd if=/dev/zero of=/dev/secureram0 bs=4096 count=256 oflag=direct status=none
sudo dd if=/dev/secureram0 bs=4096 count=256 iflag=direct status=none | sha256sum
sudo ./tools/secureramctl snapshot create
# Deterministic DATA_B is generated through a pipe, with a literal device target.
sudo env SR_MILESTONE=8 bash -c 'source tests/m5-vm-common.sh; m5_identity_guard 67108864'
python3 -c 'import sys; sys.stdout.buffer.write(bytes([165])*1048576)' | \
  sudo dd of=/dev/secureram0 bs=4096 count=256 iflag=fullblock oflag=direct status=none
sudo dd if=/dev/secureram0 bs=4096 count=256 iflag=direct status=none | sha256sum
sudo ./tools/secureramctl snapshot restore
sudo dd if=/dev/secureram0 bs=4096 count=256 iflag=direct status=none | sha256sum
sudo ./tools/secureramctl stats --json
sudo ./tools/secureramctl snapshot status --json
```

The first and third hashes must match; the second must differ. Reads must not
add integrity_failures. Start with an empty slot; an occupied-slot EEXIST must
not be ignored. No filesystem may be mounted for this demonstration. Snapshots
do not promise filesystem/application consistency or background authentication.

Finish the manual session (close block users and stop the backend with Ctrl+C):

```sh
sudo ./tools/secureramctl destroy
sudo ./tools/secureramctl snapshot status --json
sudo rmmod secureram
sudo udevadm settle
test ! -e /dev/secureram0
test ! -e /dev/secureramctl
test ! -e /sys/module/secureram
```

Review fresh kernel logs for this separate session as well. Never force unload.
M8 remains unmerged until the user accepts the real VM and browser evidence.
