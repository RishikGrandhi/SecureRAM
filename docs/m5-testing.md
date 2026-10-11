# M5 Ubuntu VM verification procedure

Status: **PASS**. Automated M5 acceptance completed on full commit
`5fabe544a3969732647e7d9962beed974b667901` in Ubuntu 24.04.5 LTS,
Linux 7.0.0-38-generic. The retained VM evidence directory is
`.cache/m5-vm/20261011T140342Z-10296`.
Local Windows/WSL builds do not establish VM runtime acceptance. Use only the
disposable Ubuntu VirtualBox VM and `/dev/secureram0`; stop at every unexpected
result. Do not force unload, change target devices, or run raw tests over a
mounted filesystem. The procedure remains reusable; the result above comes from
the completed target-VM run, not from these instructions alone.

## Automated VM acceptance

The preferred normal acceptance path is one command from a clean checkout on
the `m5-integrity-tamper-detection` branch in the disposable VM:

```sh
export M5_EXPECTED_COMMIT=$(git rev-parse HEAD)
sudo --preserve-env=M5_EXPECTED_COMMIT bash tests/run-m5-vm-acceptance.sh
```

This pins the run to the exact full commit hash exported by the invoking user.
For the accepted run it expanded to
`5fabe544a3969732647e7d9962beed974b667901`.

The final automated summary was:

```text
Production build                 PASS
Initial NO_KEY                   PASS
ABI/features                     PASS
Raw I/O                          PASS
Lock/unlock                      PASS
Destroy/rekey                    PASS
ext4                             PASS
Ciphertext tamper                PASS
Tag tamper                       PASS
Relocation protection            PASS
Integrity-failure recovery       PASS
1 MiB capacity                   PASS
256 MiB capacity                 PASS
Final production regression      PASS
Kernel health                    PASS
Final cleanup                    PASS
OVERALL                          PASS
```

Two earlier runs stopped in the harness: `093ca58` before module insertion due
to ownership/scope defects, and `2d2816f` after production destroy/rekey due to
an ext4 redirection defect. Neither was a SecureRAM driver/runtime failure. The
complete `5fabe54` run is the acceptance result.

The runner refuses root-without-sudo invocation so compilation can run as the
ordinary checkout owner. It verifies a clean expected branch, optional expected
commit, the running kernel's exact header tree, required offline tools and an
initially absent SecureRAM module/device. It then runs these fail-fast phases:

| Script | Automated scope |
| --- | --- |
| `run-m5-production.sh` | Clean production W=1 build and exclusion proof; initial QUERY/ENOTTY/negative ABI; complete raw suite; lock retention; destroy/rekey; ext4, mounted EBUSY and remount; teardown. |
| `run-m5-tamper.sh` | Clean combined M5_TEST/M4_TEST build, positive build proof, ciphertext/tag/relocation cases, failed-unit untouched-buffer guarantee, latch/rejection/recovery and teardown. |
| `run-m5-capacity.sh` | Fresh production build; explicit failure for capacity 0/257; exact 1 MiB and 256 MiB full raw lifecycles. |
| `run-m5-final.sh` | Clean production rebuild/exclusion proof, ENOTTY, core raw suite, ext4 sync/remount smoke, destroy/unload and node/sysfs disappearance. |

Shared `m5-vm-common.sh` code accepts no device argument and names only
`/dev/secureram0`. Before raw I/O, mkfs, key load/destroy and corruption it
independently verifies node types, sysfs major:minor, root ownership and 0600
mode, version 0.5.0, 4096-byte logical size, exact phase capacity, no holders,
no mount and no swap use. Mounted checks bind the harness-owned mount point to
that same major:minor. Bounded udev polling replaces arbitrary lifecycle sleeps.
Each phase tracks whether it inserted the module and mounted the filesystem;
its EXIT trap only unmounts that revalidated mount and only destroys/unloads its
owned SecureRAM instance. Cleanup errors remain visible and fail the run.

Logs go to a unique ignored `.cache/m5-vm/<UTC-time>-<pid>/` directory. The
harness restricts this subtree to the checkout owner, creates each run as that
ordinary user, permits root to write privileged-test evidence, and returns all
run files to that user during finalization. A new run also repairs ownership of
this exact evidence subtree from older sudo runs without deleting historical
evidence; it does not open permissions to group or other users. It holds
the main transcript, production/tamper/capacity/final phase logs, build output,
fresh `dmesg --follow-new` capture, relevant kernel lines, separate unrelated
warning indicators, production symbol/string evidence, status ledger and concise
summary. Generated comparison files are deleted and no key, tag or data bytes
are printed. Every requested result begins `NOT RUN`, changes to `NOT COMPLETED`
when its assertion group starts, and reaches PASS only after that group completes;
a trapped command failure marks its active group FAIL. Kernel health remains
`NOT RUN` when no fresh SecureRAM/ext4 runtime evidence was captured. When runtime
evidence exists, it rejects SecureRAM-attributable fault/warning/backtrace
signatures and failed internal diagnostics; all fatal/warning markers are retained
separately so unrelated VM messages can be classified by a human.

If the original failed harness left evidence root-owned and a one-time repair is
needed before using the fixed runner, execute these commands from the verified
repository root. They retain the evidence and keep it private to the ordinary
checkout owner:

```sh
test "$(git rev-parse --show-toplevel)" = "$PWD"
test -d .cache/m5-vm && test ! -L .cache/m5-vm
sudo chown -hR -- "$USER:$(id -gn)" .cache/m5-vm
sudo chmod -R u+rwX,go-rwx -- .cache/m5-vm
```

The non-destructive helper regression can be run without sudo or a loaded module:

```sh
bash tests/check-m5-vm-harness.sh
```

Human supervision remains required to choose/snapshot the disposable VM, verify
that the intended commit was brought into it, grant sudo, observe storage/memory
pressure, and review the transcript and unrelated warning context. The advanced
fault campaigns in section 9 remain manual diagnostic work. The automated
failed-read check fills one aligned unit with a sentinel and requires it remain
unchanged on EIO: this verifies the documented failed-unit guarantee, not atomic
release for every earlier unit in a multi-unit request.

Sections 1-9 remain the manual troubleshooting and evidence-reference path. M5
was marked accepted only after the harness completed in the target VM and its
summary and retained evidence were reviewed.

## 1. Production build and fresh logs

Inspect the VM's actual kernel. The last recorded VM was Ubuntu 24.04.5 LTS,
Linux 7.0.0-38-generic, x86-64; do not assume it remains unchanged. Check out the
candidate branch/commit after it is available; record its hash and clean status.
Use its matching headers/compiler. All builds are unprivileged.

```sh
cat /etc/os-release
uname -a
gcc --version
git branch --show-current
git rev-parse HEAD
git status --short
make check-env
make clean
make W=1
modinfo ./secureram.ko
mkdir -p .cache
gcc -std=c11 -O2 -Wall -Wextra -Werror -Wconversion -Iinclude \
  tests/m4-control.c -o .cache/m4-control
strings secureram.ko | grep -E 'M[45] test|secureram_.*tamper|SECURERAM_IOC_TAMPER'
```

Expect version 0.5.0, GPL, correct vermagic, dependency `hkdf`, no driver
warnings/errors and successful MODPOST/link. The production grep must find
nothing (exit 1). Inspect diagnostics rather than hiding them. In another VM
terminal capture only fresh messages, keeping it running across all insertions:

```sh
sudo dmesg --follow-new --color=never | tee build-m5-vm-dmesg.log
```

The exported HKDF helper is a module on the inspected target. Load that
dependency explicitly before insmod; this is the only new module dependency.
If unavailable, stop and inspect matching kernel modules/configuration.

```sh
sudo modprobe hkdf
sudo insmod ./secureram.ko
sudo udevadm settle
lsmod | grep '^secureram '
ls -l /dev/secureram0 /dev/secureramctl
cat /sys/module/secureram/version
cat /sys/class/block/secureram0/size
cat /sys/class/block/secureram0/queue/logical_block_size
sudo .cache/m4-control query
```

Both nodes must be root-owned 0600. Default capacity is 67108864 bytes,
131072 kernel sectors, logical size 4096; query must show ABI=1, state=0,
generation=0 and features=7. The banner identifies XTS plus HMAC integrity;
production has no M4/M5 test banner. Keyless block opens fail, so inspect sysfs
geometry before activation. No plaintext, ciphertext, key or tag is logged.

## 2. Identity guard before every destructive phase

Run this guard before each raw suite, key load/destroy, corruption suite or
format. All Python suites repeat identity/mount/holder checks; direct raw fds
use O_EXCL. The kernel independently rejects administrative transitions and
injection with block openers, including mounts in other namespaces. Other open
users must close.

```sh
sudo python3 - <<'PY'
import os, stat
from pathlib import Path
p = Path('/sys/class/block/secureram0')
s = os.lstat('/dev/secureram0')
assert stat.S_ISBLK(s.st_mode)
assert s.st_uid == 0 and s.st_gid == 0 and stat.S_IMODE(s.st_mode) == 0o600
n = f'{os.major(s.st_rdev)}:{os.minor(s.st_rdev)}'
assert p.joinpath('dev').read_text().strip() == n
assert Path('/sys/module/secureram/version').read_text().strip() == '0.5.0'
assert int(p.joinpath('queue/logical_block_size').read_text()) == 4096
assert not list(p.joinpath('holders').iterdir())
assert all(line.split()[2] != n for line in Path('/proc/self/mountinfo').read_text().splitlines())
c = os.lstat('/dev/secureramctl')
assert stat.S_ISCHR(c.st_mode)
assert c.st_uid == 0 and c.st_gid == 0 and stat.S_IMODE(c.st_mode) == 0o600
assert Path('/sys/class/misc/secureramctl/dev').read_text().strip() == f'{os.major(c.st_rdev)}:{os.minor(c.st_rdev)}'
print('PASS: M5 identity, permissions, unmounted, no holders')
PY
findmnt --source /dev/secureram0
ls -A /sys/class/block/secureram0/holders
sudo fuser -v /dev/secureram0
```

`findmnt` and `fuser` normally return nonzero with no matching users; inspect
their output. Nothing here grants permission to target another disk.

## 3. Production keyless, ABI and raw regression

After the guard:

```sh
sudo python3 tests/m5-integrity.py production
sudo python3 tests/m5-raw-io.py denied
sudo .cache/m4-control negative
sudo .cache/m4-control query
sudo .cache/m4-control load-test-key
sudo .cache/m4-control query
sudo blockdev --getsize64 /dev/secureram0
sudo python3 tests/m5-raw-io.py active
```

Expect tamper command ENOTTY, initial read/write opens ENOKEY, negative ABI/
user-copy/privilege/equal-half checks PASS and unchanged NO_KEY. Loading uses
an ephemeral random 64-byte key, never printed/stored; it reaches ACTIVE (2),
generation 1, features 7. The production raw suite must pass:

- Every initially logical-zero byte (all 64 MiB), verified through HMAC + XTS.
- Direct segmented I/O, first/nonzero/middle/final blocks and neighbor isolation.
- Four concurrent disjoint streams, repeated overwrites, end-of-device behavior
  and flush (the core may elide an empty flush; this is not driver fault injection).
- A 1 MiB random SHA-256/cmp round trip and all four key transitions returning
  EBUSY while an exclusive block descriptor stays open.

The M5 wrapper reuses M4/M2 I/O checks with version 0.5.0. Running M4 directly
still requires 0.4.0; M2's plaintext-only allowlist is unchanged.

## 4. Lock, retained data, destruction and generation

Run the guard with all block descriptors closed. The following two load attempts
are expected failures (EBUSY); verify their result and state explicitly.

```sh
sudo .cache/m4-control load-test-key
sudo dd if=/dev/secureram0 of=.cache/m5-before-lock.bin bs=4096 count=256 iflag=direct status=none
sudo .cache/m4-control lock
sudo .cache/m4-control query
sudo python3 tests/m5-raw-io.py denied
sudo .cache/m4-control load-test-key
sudo .cache/m4-control unlock
sudo .cache/m4-control query
sudo dd if=/dev/secureram0 of=.cache/m5-after-lock.bin bs=4096 count=256 iflag=direct status=none
cmp .cache/m5-before-lock.bin .cache/m5-after-lock.bin
sudo .cache/m4-control destroy
sudo .cache/m4-control query
sudo python3 tests/m5-raw-io.py denied
sudo .cache/m4-control destroy
sudo .cache/m4-control load-test-key
sudo .cache/m4-control query
sudo python3 tests/m5-raw-io.py active
```

LOCKED=3 then ACTIVE=2 must preserve generation 1 and byte-identical data.
Destroy gives NO_KEY generation 1 and is idempotent. The next load must give
generation 2 and pass the full zero scan again. These checks exercise retained
XTS/HMAC state and newly initialized ciphertext/tags.

## 5. ext4 and mounted-device transition rejection

After the guard, format only the named volatile device. No other mkfs target
is acceptable. `nodiscard` avoids unsupported native discard.

```sh
sudo mkfs.ext4 -E nodiscard /dev/secureram0
sudo mkdir -p /mnt/secureram-m5
sudo mount /dev/secureram0 /mnt/secureram-m5
printf '%s\n' 'SecureRAM M5 authenticated backing, normal filesystem I/O' | \
  sudo tee /mnt/secureram-m5/check.txt
sudo sync -f /mnt/secureram-m5/check.txt
cat /mnt/secureram-m5/check.txt
sudo .cache/m4-control busy
sudo .cache/m4-control query
cat /mnt/secureram-m5/check.txt
sudo umount /mnt/secureram-m5
sudo mount /dev/secureram0 /mnt/secureram-m5
cat /mnt/secureram-m5/check.txt
sudo umount /mnt/secureram-m5
```

Require exact content before/after remount and every state-changing ioctl
rejected EBUSY by `busy`, with state/generation unchanged. Never bypass the
opener guard or inject corruption into a mounted filesystem. Do not use swap.

## 6. Clean teardown

After unmounting, closing users and the identity guard:

```sh
sudo .cache/m4-control destroy
sudo .cache/m4-control query
sudo python3 tests/m5-raw-io.py denied
sudo rmmod secureram
sudo udevadm settle
test ! -e /dev/secureram0
test ! -e /dev/secureramctl
test ! -e /sys/class/block/secureram0
test ! -e /sys/class/misc/secureramctl
test ! -e /sys/module/secureram
```

Require the M5 unload log. Do not force unload or remove a dependency used by
other modules. Inspect fresh logs as described in section 9.

## 7. M5 tamper build and recovery acceptance

Only after production has been unloaded:

```sh
make clean
make W=1 M5_TEST=1 M4_TEST=1
modinfo ./secureram.ko
strings secureram.ko | grep -F 'M5 test:'
sudo insmod ./secureram.ko capacity_mb=64
sudo udevadm settle
sudo .cache/m4-control query
```

This combined diagnostic build also preserves M4's actual-backing comparisons
and synthetic 512/4096/3584-byte gather/scatter checks. `M5_TEST=1` alone enables
all integrity hooks independently. Run the identity guard, then:

```sh
sudo python3 tests/m5-integrity.py tamper
sudo .cache/m4-control query
```

The suite requires NO_KEY, accepts no alternative device and ends NO_KEY. It
executes three independent cases, each with fresh activation and full zero scan:

1. Write random data to unit 0, flip ciphertext byte 0, then direct-read unit 0.
2. Fresh key/medium: write the middle unit, flip tag byte 31, direct-read it.
3. Fresh key/medium: write unit 1 and the final unit, copy the **whole valid
   ciphertext/tag pair** from 1 to the final unit, direct-read the final unit.

For every case require EIO, the sentinel-filled aligned caller read buffer
**unchanged**, state=4, unchanged generation, and continued read/write failures
through the already-open descriptor even at an undamaged unit. New opens must
fail EIO. Query remains usable. While that block fd is open, destroy returns
EBUSY; after close, lock/unlock/load/test-mutation all reject, preserving the
latch. Destroy twice must yield NO_KEY with unchanged generation, then a new
key must advance it once, pass a full fresh-zero scan and normal random I/O.
Finally destroy returns NO_KEY. Across three cases, generation advances by six.

The suite also rejects invalid indices (including U64_MAX), offsets, operation,
header version/size/flags/reserved, self-relocation, and injection while a block
fd is open. A passed control descriptor is tested after dropping all privileges;
tamper must still return EPERM. No kernel memory addresses or bytes are exported.

For this insertion expect test metadata lines:

```text
M5 test: unit and generation binding PASS
M4 test: equal zero units at indices 0/1 have different ciphertext
M4 test: 512/4096/3584-byte split-unit gather/scatter PASS
M4 test: real WRITE backing equals ciphertext and differs from plaintext
```

The M5 internal check holds ciphertext fixed, verifies the correct metadata,
then changes only index or generation and requires different tags. It executes
before ACTIVE; test failure rejects activation. For each tamper read, the
rate-limited integrity log should identify only the failed unit and latch.
Rate limiting may suppress repeated lines; userspace EIO/state/buffer assertions
remain mandatory. The three corruption operations and PASS records are metadata,
never secrets. The accepted VM run observed all three cases, their failure latch
and recovery.

Finish test-build ext4/regression on another fresh key: repeat sections 3-6,
omitting `m5-integrity.py production` (it must only run on a production build).
Use the current generation 6 as the baseline: the next loads yield 7 and 8,
rather than the fresh-insertion values 1 and 2 used in those sections.

## 8. Final production, capacities and invalid parameters

After unloading the test variant, clean and rebuild `make W=1`, confirm the
production string/symbol grep is empty, and repeat sections 1-6. The runtime
production ENOTTY probe must also pass. Record this separately from test evidence.

Then, one insertion at a time with a clean destroy/unload between runs:

```sh
sudo insmod ./secureram.ko capacity_mb=1
sudo udevadm settle
sudo .cache/m4-control query
sudo .cache/m4-control load-test-key
sudo python3 tests/m5-raw-io.py active
sudo .cache/m4-control destroy
sudo rmmod secureram
sudo udevadm settle
sudo insmod ./secureram.ko capacity_mb=256
sudo udevadm settle
sudo .cache/m4-control query
sudo .cache/m4-control load-test-key
sudo python3 tests/m5-raw-io.py active
sudo .cache/m4-control destroy
sudo rmmod secureram
sudo udevadm settle
```

Run the guard for each new insertion before load/raw I/O/destroy. Each load
begins generation 0 and succeeds to 1; check the full zero scan at both limits.
At 1 MiB tags cost 8 KiB; at 256 MiB, 2 MiB. With no module loaded, invalid
parameter attempts must fail EINVAL and leave both nodes absent:

```sh
sudo insmod ./secureram.ko capacity_mb=0
test ! -e /dev/secureram0
test ! -e /dev/secureramctl
sudo insmod ./secureram.ko capacity_mb=257
test ! -e /dev/secureram0
test ! -e /dev/secureramctl
```

Those two insmod commands are expected failures, not steps to ignore blindly.

## 9. Kernel health, evidence and unverified diagnostics

Stop the fresh dmesg capture and inspect the entire log plus this search:

```sh
grep -Ein 'Oops|BUG:|kernel panic|general protection fault|use-after-free|KASAN|WARNING:|Call Trace:' build-m5-vm-dmesg.log
grep -E 'secureram:|EXT4-fs' build-m5-vm-dmesg.log
```

The first search must produce no driver fault signatures. Expected injected
integrity errors and their ordinary block I/O errors are not crash signatures.
Record unrelated messages, signing/out-of-tree taints and build/BTF diagnostics
separately. Require clean teardown and no FAILED internal-check messages.
Update the M5 report only with observed commit, kernel/compiler, variants,
provider/geometry, query generations, suite PASS outputs, ext4/remount and logs.

Additional diagnostic coverage, not implied by the acceptance suite: allocation
failure for tags/shash/descriptor/XTS/request, provider absence, setkey/crypto
errors midway through activation or I/O, generation exhaustion, pending-request
failure races, compat **runtime** ioctls, lockdep/KASAN/kmemleak and cache behavior
after failed mounted I/O. On an appropriate diagnostic kernel, require failed
activation to leave NO_KEY with unchanged generation and cleared partial medium;
failed writes must leave the failing unit's pair unchanged, and failed reads
must not scatter it. Do not claim these fault campaigns from source review or
normal round trips. M5 does not claim physical erasure or persistent anti-replay.
