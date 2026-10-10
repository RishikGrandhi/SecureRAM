# M2 runtime test procedure (Ubuntu VirtualBox VM)

Target: Ubuntu 24.04.5 LTS, `7.0.0-38-generic`, x86-64. Execute these commands
manually **inside that VM**, from your SecureRAM checkout. The current agent's
WSL build does not verify these runtime outcomes. M2 storage is plaintext and
exists only in RAM. Unloading loses every byte.

M2 runtime acceptance is complete; its observed results are recorded in
[the M2 report](m2-report.md). This procedure remains the reusable, broader
regression checklist for future builds and kernel targets.

All device writes and formatting below target **only `/dev/secureram0`**. Use a
fresh load with no valuable data. Never substitute another disk path. Run each
section in order and stop on unexpected failures. Keep a second terminal open
with `sudo dmesg --follow --color=never` to correlate new messages.

## 1. Build against the running kernel

```sh
uname -r
sudo apt-get update
sudo apt-get install build-essential kmod python3 e2fsprogs util-linux \
  "linux-headers-$(uname -r)"
make check-env
make clean
make W=1
modinfo ./secureram.ko
modinfo -F vermagic ./secureram.ko
```

Expect version `0.2.0`. The first word in `vermagic` must equal `uname -r`.
Stop if it does not. Use the matching compiler if Kbuild requests a different
one; signature policy may require signing with a trusted key. Never force load.

## 2. Load and inspect

```sh
sudo insmod ./secureram.ko capacity_mb=64
sudo udevadm settle
lsmod | grep '^secureram '
sudo dmesg --color=never | grep -F 'secureram:'
test -b /dev/secureram0
ls -l /dev/secureram0
lsblk -b -o NAME,MAJ:MIN,SIZE,TYPE,LOG-SEC,PHY-SEC,MOUNTPOINTS /dev/secureram0
sudo blockdev --getsize64 /dev/secureram0
cat /sys/class/block/secureram0/size
cat /sys/class/block/secureram0/queue/logical_block_size
cat /sys/class/block/secureram0/queue/physical_block_size
```

Expected capacity: **67108864 bytes**, sysfs size **131072 sectors**; logical and
physical block sizes **4096**. The major/minor are allocated dynamically, so do
not hard-code them. Expected fresh driver message:

```text
secureram: SecureRAM v0.2.0: /dev/secureram0 ready, 64 MiB, 4096-byte logical blocks (plaintext RAM)
```

If the node is absent after udev settles, inspect logs/sysfs and stop; do not
work around a registration bug by creating a node manually.

## 3. Automated raw/direct I/O smoke test

On this **fresh, unmounted** device:

```sh
sudo python3 tests/m2-raw-io.py
```

This opt-in test accepts no device argument. It verifies module version, the
sysfs/device-number match, geometry/capacity, and exclusive opening before any
write. It uses page-aligned buffers and `O_DIRECT`, checks every initial byte
is zero, round-trips a temporary 1 MiB file, checks first/middle/last blocks,
overwrites a block between guard blocks, runs four concurrent streams, and
checks end-of-device behavior and `fsync()`. Every stage must print `PASS` and
the command must exit zero. The device is left containing test data.

Read at EOF may return zero, and a beyond-end write must not transfer data.
These syscalls may be rejected in the generic block layer; they do not directly
prove the driver's defensive range guards were reached. Do not interpret a
userspace test as fault injection of malformed kernel requests.

To run the script again, unload/reload first so its initial-zero check is valid.

## 4. Readable manual round trip using dd and cmp

This independently demonstrates normal tools. It also overwrites the start of
SecureRAM. Run in Bash; temporary paths are quoted and never used as device
targets. `oflag=direct`/`iflag=direct` avoid satisfying the comparison from cache.

```bash
(
  set -euo pipefail
  test -b /dev/secureram0
  test -z "$(lsblk -n -o MOUNTPOINTS /dev/secureram0 | tr -d '[:space:]')"
  test -z "$(ls -A /sys/class/block/secureram0/holders)"
  test_dir=$(mktemp -d /tmp/secureram-m2.XXXXXX)
  echo "Temporary input/readback files: $test_dir"
  dd if=/dev/urandom of="$test_dir/input.bin" bs=4096 count=256 status=none
  sudo dd if="$test_dir/input.bin" of=/dev/secureram0 bs=4096 count=256 \
    oflag=direct conv=fsync,notrunc status=progress
  sudo dd if=/dev/secureram0 of="$test_dir/readback.bin" bs=4096 count=256 \
    iflag=direct status=progress
  sudo cmp "$test_dir/input.bin" "$test_dir/readback.bin"
  sudo sha256sum "$test_dir/input.bin" "$test_dir/readback.bin"
)
```

`cmp` must exit zero with no output; both SHA-256 values must match. The temporary
files are retained at the printed path for inspection. This is not a benchmark.

## 5. Module ownership and unsupported operation checks

With SecureRAM unmounted, hold an open file while attempting **normal** unload:

```sh
sudo python3 - <<'PY'
from pathlib import Path
import subprocess
with open('/dev/secureram0', 'rb', buffering=0):
    result = subprocess.run(['rmmod', 'secureram'], capture_output=True, text=True)
    print(result.stderr.strip())
    if result.returncode == 0 or not Path('/sys/module/secureram').exists():
        raise SystemExit('FAIL: module was removable with an open device')
print('PASS: an open device prevents normal unload')
PY
```

Expect a module-in-use error. Do not use `-f`. Then inspect unsupported discard:

```sh
cat /sys/class/block/secureram0/queue/discard_max_bytes
sudo blkdiscard --offset 0 --length 4096 /dev/secureram0
```

Expect a zero limit and a nonzero exit with "Operation not supported". A failure
such as "device busy" does not establish unsupported-operation behavior. The
driver also rejects native WRITE_ZEROES and other unrecognized opcodes, but
generic zeroing tools can emulate those with WRITE; do not infer native support
from a successful zero-fill command.

## 6. Optional ext4 filesystem smoke test

**Destructive to the contents of `/dev/secureram0` only.** Run after raw tests
pass. M2 uses the whole device, with no partition table. Formatting is never
executed automatically by the build or test script. In Bash:

```bash
(
  set -euo pipefail
  test -b /dev/secureram0
  test -z "$(lsblk -n -o MOUNTPOINTS /dev/secureram0 | tr -d '[:space:]')"
  test -z "$(ls -A /sys/class/block/secureram0/holders)"
  sudo mkfs.ext4 -b 4096 -E nodiscard /dev/secureram0
  mount_dir=$(mktemp -d /tmp/secureram-mount.XXXXXX)
  echo "SecureRAM mount point: $mount_dir"
  sudo mount /dev/secureram0 "$mount_dir"
  trap 'sudo umount "$mount_dir" || true' EXIT
  printf 'SecureRAM M2 filesystem check\n' | sudo tee "$mount_dir/check.txt" >/dev/null
  sync
  sudo umount "$mount_dir"
  trap - EXIT
  sudo mount /dev/secureram0 "$mount_dir"
  trap 'sudo umount "$mount_dir" || true' EXIT
  printf 'SecureRAM M2 filesystem check\n' | sudo cmp - "$mount_dir/check.txt"
  sudo umount "$mount_dir"
  trap - EXIT
  rmdir "$mount_dir"
)
```

`cmp` must succeed after unmount/remount. `nodiscard` prevents mkfs from trying
the intentionally unsupported discard feature. If any step fails, inspect
`findmnt --source /dev/secureram0`, unmount its displayed mountpoint, and close
all users before unloading. The filesystem survives a mount cycle while the
module stays loaded; it does not survive module unload/reload.

## 7. Unload and confirm complete removal

```sh
findmnt --source /dev/secureram0
# No output is expected here; unmount first if a mount is listed.
sudo rmmod secureram
sudo udevadm settle
test ! -e /sys/module/secureram && echo 'Module gone'
test ! -e /sys/class/block/secureram0 && echo 'Disk sysfs gone'
test ! -e /dev/secureram0 && echo 'Device node gone'
sudo dmesg --color=never | grep -F 'secureram:'
```

Expected new message:

```text
secureram: SecureRAM: M2 module unloaded; device removed and RAM released
```

Inspect the full kernel log for oopses, backtraces, or use-after-free diagnostics,
not only prefixed lines. This message describes the cleanup path; it is not a
memory-leak detector. Allocation-failure injection and comprehensive kmemleak/
KASAN/lockdep testing are not claimed by this smoke test.

## 8. Repeat and validate parameters

Reload with a different small capacity and rerun the full raw test. This checks
reinitialization, fresh zeroes, and changed geometry without needing a filesystem:

```sh
sudo insmod ./secureram.ko capacity_mb=32
sudo udevadm settle
sudo blockdev --getsize64 /dev/secureram0
sudo python3 tests/m2-raw-io.py
sudo rmmod secureram
sudo udevadm settle
```

Expected size is 33554432 bytes. Finally, on the unloaded module:

```sh
sudo insmod ./secureram.ko capacity_mb=0
sudo insmod ./secureram.ko capacity_mb=257
sudo insmod ./secureram.ko capacity_mb=4294967296
test ! -e /sys/module/secureram
test ! -e /dev/secureram0
sudo dmesg --color=never | grep -F 'secureram:'
make clean
```

All three insertions must fail. The first two are rejected by driver validation;
the last is rejected by the kernel's unsigned-int parameter parser. If any
unexpectedly succeeds, stop, unload it normally, and record the failure.
Do not allocate maximum capacity just to test parameter limits in a small VM.

For future regression runs, record kernel/compiler versions, build diagnostics,
PASS/FAIL output, raw hashes, and fresh lifecycle logs. A clean compilation alone
does not establish runtime behavior on a new kernel or build.
