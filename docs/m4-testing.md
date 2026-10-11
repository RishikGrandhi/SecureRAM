# M4 Ubuntu VM verification procedure

Status: **not yet run**. This is an opt-in, destructive procedure for the user's
disposable Ubuntu VirtualBox VM. It is not an automation script. M1-M3 runtime
evidence does not establish M4 correctness. Stop at every unexpected result.
Record commands, exit statuses, tool output and fresh logs. Never force unload.

## 1. Build and identify the environment

Confirm this is the disposable VM and close all previous SecureRAM users. Do
not run these runtime commands in WSL or against an unrelated disk. Inspect the
current running kernel; the recorded target is Ubuntu 24.04.5 LTS, x86-64,
7.0.0-38-generic, but it may change. Build with its matching compiler/headers.

```sh
cat /etc/os-release
uname -a
gcc --version
git status --short --branch
make check-env
make clean
make W=1 M4_TEST=1
modinfo ./secureram.ko
mkdir -p .cache
gcc -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Iinclude \
  tests/m4-control.c -o .cache/m4-control
```

Require version 0.4.0, GPL, matching vermagic and no driver compiler/MODPOST
warnings/errors. `M4_TEST=1` enables internal comparisons and synthetic
fragment checks. It adds no memory-reading ioctl. A clean production rebuild
without this option is required for the final regression below.

In a second VM terminal start fresh log capture before inserting:

```sh
sudo dmesg --follow-new --color=never | tee build-m4-vm-dmesg.log
```

```sh
sudo insmod ./secureram.ko capacity_mb=64
sudo udevadm settle
lsmod | grep '^secureram '
ls -l /dev/secureram0 /dev/secureramctl
cat /sys/module/secureram/version
cat /sys/class/block/secureram0/dev
cat /sys/class/block/secureram0/size
cat /sys/class/block/secureram0/queue/logical_block_size
cat /sys/class/misc/secureramctl/dev
sudo .cache/m4-control query
```

Expect NO_KEY (state 0), generation 0, capacity 67108864, unit 4096 and features
3. Sysfs size is 131072 **512-byte sectors**. Control node must be root-owned
0600. The load log says AES-256-XTS, NO_KEY, confidentiality only and no integrity.
The test-build banner must be present. At NO_KEY a `blockdev` command that opens
the disk can fail with ENOKEY; use sysfs for initial geometry.

## 2. Identity guard before each destructive phase

The following check reads metadata only. Use it before raw writes, each key
load/destroy and formatting. A holder/mount/open user is a reason to stop, not
to bypass the check. The Python tests repeat identity checks and use O_EXCL.
The driver independently rejects transitions with any block openers, including
mounts in other namespaces. Never substitute a different device path.

```sh
sudo python3 - <<'PY'
import os, stat
from pathlib import Path
p = Path('/sys/class/block/secureram0')
s = os.lstat('/dev/secureram0')
assert stat.S_ISBLK(s.st_mode)
n = f'{os.major(s.st_rdev)}:{os.minor(s.st_rdev)}'
assert p.joinpath('dev').read_text().strip() == n
assert Path('/sys/module/secureram/version').read_text().strip() == '0.4.0'
assert int(p.joinpath('queue/logical_block_size').read_text()) == 4096
assert not list(p.joinpath('holders').iterdir())
assert all(line.split()[2] != n for line in Path('/proc/self/mountinfo').read_text().splitlines())
print('SecureRAM identity/unmounted/holder checks PASS')
PY
findmnt --source /dev/secureram0
ls -A /sys/class/block/secureram0/holders
sudo fuser -v /dev/secureram0
```

`findmnt`/`fuser` normally return nonzero when nothing is found. Inspect that
result explicitly. No holder or mounted filesystem is permitted for raw tests.

## 3. Fail closed, malformed ABI, then key activation

```sh
sudo python3 tests/m4-raw-io.py denied
sudo .cache/m4-control negative
sudo .cache/m4-control query
sudo .cache/m4-control load-test-key
sudo .cache/m4-control query
sudo blockdev --getsize64 /dev/secureram0
```

Require read/write opens rejected with ENOKEY initially. This prevents ordinary
I/O before requests exist; it is not direct fault injection into queue_rq.
Negative checks cover lengths 0/32/63/65, equal key halves, version/size/flags/
reserved fields, unknown command, copy faults (including a partial key copy),
invalid transitions and privilege rejection using an inherited control fd.
They must leave NO_KEY unchanged. They do not test every possible ABI byte.

The helper generates exactly 64 random test bytes with getrandom, locks its
input buffer, disables dumps and clears it after ioctl. No key appears in files,
arguments, status or logs. It intentionally cannot recover the key. Successful
load should report ACTIVE (2), generation 1 and the fragment-test PASS log.
That internal test crosses a unit inside one fragment and splits another unit
across fragments, then restores encrypted logical zeros.

## 4. Raw I/O and direct backing evidence

Run the identity guard again, then:

```sh
sudo python3 tests/m4-raw-io.py active
sudo dmesg --color=never | grep -F 'M4 test:'
```

Require full logical-zero scan, 1 MiB random round trip, first/nonzero/middle/
final blocks, neighboring-block isolation, repeated overwrites, concurrent
disjoint streams, end-of-device checks, SHA-256 equality and successful `cmp`.
The helper reuses M2's I/O routines without changing its historical version
allowlist. It also checks EBUSY for every key-changing command while its exclusive
block fd is open. All writes use the hard-coded `/dev/secureram0`.

For the **current module insertion**, require this log after an actual write:

```text
secureram: M4 test: real WRITE backing equals ciphertext and differs from plaintext
```

In this build, every security write compares actual private store bytes with
both staging buffers while access is serialized. A mismatch returns EIO and
logs FAILED; the success line is emitted once only after a successful real
block WRITE. This observes backing ciphertext separately from normal decrypted
reads. No bytes, hashes, pointers or keys are exported. The fragment test alone
does not produce that line. Require both the backing check and plaintext
readback success; compilation of this hook proves neither result. The test
does not certify AES or provide integrity protection in the production driver.

## 5. Lock/unlock, replacement rejection, reset semantics

Close all block fds, run the identity guard, then:

```sh
# Expected failure: replacement in ACTIVE returns EBUSY.
sudo .cache/m4-control load-test-key
sudo .cache/m4-control lock
sudo .cache/m4-control query
sudo python3 tests/m4-raw-io.py denied
# Expected failure: loading directly in LOCKED returns EBUSY.
sudo .cache/m4-control load-test-key
sudo .cache/m4-control unlock
sudo .cache/m4-control query
```

Expect LOCKED (3) then ACTIVE (2), unchanged generation. Lock retains the key;
it does not evict secrets. Confirm content survives locking with an explicit
readback comparison before and after lock (using the fixed-device read below).

```sh
sudo dd if=/dev/secureram0 of=.cache/m4-before-lock.bin bs=4096 count=256 iflag=direct status=none
sudo .cache/m4-control lock
sudo .cache/m4-control unlock
sudo dd if=/dev/secureram0 of=.cache/m4-after-lock.bin bs=4096 count=256 iflag=direct status=none
cmp .cache/m4-before-lock.bin .cache/m4-after-lock.bin
sudo .cache/m4-control destroy
sudo .cache/m4-control query
sudo python3 tests/m4-raw-io.py denied
sudo .cache/m4-control destroy
sudo .cache/m4-control load-test-key
sudo .cache/m4-control query
sudo python3 tests/m4-raw-io.py active
```

Destroy is idempotent in NO_KEY. The next key must give generation 2 and a new
logical-zero medium; the raw test's full zero scan proves old data is not
reinterpreted under a new key. No old filesystem should survive destructive reset.

## 6. ext4 and mounted-device protection

Run the identity guard again. These commands overwrite only the SecureRAM
device. The `-E nodiscard` option avoids asking for unsupported discard.

```sh
sudo mkfs.ext4 -E nodiscard /dev/secureram0
sudo mkdir -p /mnt/secureram-m4
sudo mount /dev/secureram0 /mnt/secureram-m4
printf '%s\n' 'SecureRAM M4 encrypted backing; plaintext filesystem interface' | \
  sudo tee /mnt/secureram-m4/check.txt
sudo sync -f /mnt/secureram-m4/check.txt
cat /mnt/secureram-m4/check.txt
# Expected failure: mounted opener makes LOCK return EBUSY.
sudo .cache/m4-control lock
sudo umount /mnt/secureram-m4
sudo mount /dev/secureram0 /mnt/secureram-m4
cat /mnt/secureram-m4/check.txt
sudo umount /mnt/secureram-m4
```

The lock attempt must receive EBUSY without changing state or contents. The
raw test already exercises all key commands with an exclusive block fd and no
filesystem mounted. Never attempt key destruction under a mounted filesystem;
the same kernel opener guard enforces this rule. Do not use SecureRAM for swap.
Upper-layer plaintext caches and
application copies are outside the encryption/zeroization boundary.

## 7. Destroy, unload and kernel health

Run the identity guard after unmounting and closing all users, then:

```sh
sudo .cache/m4-control destroy
sudo .cache/m4-control query
sudo python3 tests/m4-raw-io.py denied
sudo rmmod secureram
sudo udevadm settle
test ! -e /dev/secureram0
test ! -e /dev/secureramctl
test ! -e /sys/class/block/secureram0
test ! -e /sys/class/misc/secureramctl
test ! -e /sys/module/secureram
sudo dmesg --color=never | tail -n 150
```

Inspect fresh logs from insertion through unload: no Oops, BUG, panic,
protection fault, use-after-free, warning backtrace or ciphertext-check failure.
Report signing/out-of-tree taints and unrelated system messages separately.
The unload message must report both devices removed and owned memory cleared.
That log is not proof of all physical copies being erased.

## 8. Production regression and remaining adversarial checks

After unloading, `make clean; make W=1` (two separate commands) produces the
production driver. Confirm no M4 test strings with `strings secureram.ko`.
Repeat sections 1-7 without expecting test-only banners or comparisons. Record
test-build backing evidence separately from the production functional run.
Test at least one small supported capacity (1 MiB) and another clean lifecycle.

Additional acceptance work: race repeated ordinary opens/closes against lock/
unlock/destroy/load with each result either serialized success or the documented
errno; inspect lockdep/KASAN if available. Keep a block fd open with ongoing I/O
and repeat `busy` to verify rejection; do not forcibly revoke active users.
On a dedicated diagnostic kernel, inject transform/request allocation, setkey
and encryption failures, and check NO_KEY after failed preparation, exact-once
completion, unchanged failed WRITE unit, no failed READ-unit release and clean
unload. Source review does not prove these injected failures or races occurred.
Provider-unavailability behavior also requires a controlled kernel setup.

Record precisely which optional diagnostics ran. Do not mark all fault/race/
zeroization coverage complete from a successful round trip. Update
[the M4 report](m4-report.md) only with observed evidence; stop after M4.
