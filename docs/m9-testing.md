# M9 verification: local candidate, Ubuntu acceptance pending

M9 starts at M8 merge `232862e06130b7e9ae3b6b10612717ed72ba0d94` and stays
on `m9-stress-hardening`. Driver/CLI/dashboard remain 0.8.0, ABI 1, features 31.
The [design/report](m9-report.md) defines invariants and evidence limits.
Nothing here claims an unexecuted VM test passed.

## Local checks (no root or device access)

From WSL, `/mnt/c/Coding/Projects/SecureRAM`:

```sh
python3 tests/check-m9-local.py \
  --kdir /home/rishik_grandhi/.cache/secureram-m2-20261010/root/usr/src/linux-headers-7.0.0-38-generic \
  --checkpatch /home/rishik_grandhi/.cache/secureram-m2-20261010/root/usr/src/linux-hwe-7.0-headers-7.0.0-38/scripts/checkpatch.pl
```

This composes `check-m8-local.py`, all inherited suites and M9 builds, stress
oracle self-tests, mocked phase/config/failure checks and kernel-log fixtures.
ASan/UBSan exercise the actual store/snapshot code with allocator shims; this
is not a kernel allocator, locking or crypto-provider test. Production must
omit the M9 object, symbols and parameter; runtime checks also require the
parameter absent. No packages, custom kernel or benchmark framework are added.
Never insert a generic Ubuntu module in the WSL Microsoft kernel.

## Transfer the committed candidate without pushing

Use the established Git bundle workflow. The delivery supplies
`.cache/m9-stress-hardening.bundle`; copy it to
`~/Downloads/m9-stress-hardening.bundle` in the disposable Ubuntu VM.
Regeneration on the development machine, after committing:

```sh
git bundle create .cache/m9-stress-hardening.bundle m9-stress-hardening
git bundle verify .cache/m9-stress-hardening.bundle
```

In the Ubuntu VM, as the checkout's ordinary owner:

```sh
cd ~/SecureRAM
git status --short --branch
git bundle verify ~/Downloads/m9-stress-hardening.bundle
git fetch ~/Downloads/m9-stress-hardening.bundle \
  m9-stress-hardening:m9-stress-hardening
git switch m9-stress-hardening
git status --short --branch
git rev-parse HEAD
uname -r
```

Stop if the initial checkout is dirty or the branch is divergent. Do not
force-update, discard local work or merge. Compare the full SHA with the
delivery message before running. On a later fast-forward delivery, fetch into
an unchecked-out branch or fetch the bundle branch into FETCH_HEAD and use
`git merge --ff-only FETCH_HEAD` while on M9, after inspecting the commits.

## One VM entry point

No pre-existing module, SecureRAM nodes, mount or dashboard may be present.
Use the disposable Ubuntu VirtualBox VM, its running-kernel headers, and an
ordinary checkout owner invoking sudo. The harness rejects WSL, wrong branch,
wrong/full-missing commit, dirty checkout and mismatched headers. It accepts
no positional arguments or alternate disk. It builds as the ordinary owner.
Invocation authorizes destruction only of volatile `/dev/secureram0` contents.
Do not run another administrator or backend during acceptance.

After comparing HEAD with the reviewed delivery SHA:

```sh
export M9_EXPECTED_COMMIT="$(git rev-parse HEAD)"
sudo --preserve-env=M9_EXPECTED_COMMIT bash tests/run-m9-vm-acceptance.sh
```

Prefer the delivery's literal 40-character SHA in
`sudo env M9_EXPECTED_COMMIT=<reviewed-full-sha> bash tests/run-m9-vm-acceptance.sh`
when copying directly. The normal quick profile runs 32 I/O rounds per worker,
12 snapshot/key/race/invalid rounds and 10 load/use/unload cycles. The inherited
full M8 suite additionally verifies full 64 MiB snapshot rollback, HTTP, ext4,
corruption, capacity extremes and final production behavior.

Optional extended run of the same implementations:

```sh
sudo env M9_EXPECTED_COMMIT="$M9_EXPECTED_COMMIT" M9_MODE=extended \
  bash tests/run-m9-vm-acceptance.sh
```

Extended uses 256 I/O rounds, 100 lifecycle rounds and 50 reloads. Optional
`M9_IO_ROUNDS`, `M9_CYCLES`, `M9_RELOADS` overrides must be decimal 1..2048;
no leading zeros. A stress subprocess has a 20-minute deadline, CLI calls a
60-second deadline, and the composed runtime session a two-hour deadline.
Timeout is FAIL; it never becomes PASS because some work completed. Signal
cleanup attempts owned-resource removal; an uninterruptible kernel hang can
prevent userspace cleanup and requires operator recovery, never forced unload.

## What the stages assert

| Stage | Method and permitted result |
| --- | --- |
| Existing regressions | All M8 phases, including M6 CLI/stats/raw/ext4/UAPI/privilege/capacity and M7 HTTP authorization/malformed requests; unchanged assertions. |
| Concurrent I/O and busy controls | Four writers and four readers share positional direct I/O, with a ninth control observer. Disjoint streams assert exact data; overlap asserts complete deterministic units from known writers/iterations, including mixed larger reads. Final exclusive overwrite is exact. Lifecycle calls while open must return EBUSY; stats remain monotonic. |
| Boundaries | Aligned first/last guards, out-of-range/huge offsets, EOF, rejected unaligned direct requests, buffered unaligned bytes followed by final-close/direct readback. |
| Control-plane races | Four creates have exactly one winner; create/delete permit both serial orders; restore/delete results determine the exact final data; create/destroy leaves NO_KEY and no slot, permitting only success or state EBUSY. |
| Snapshot stress | Alternating 4 KiB/1 MiB deterministic A -> create -> B -> restore -> exact A, duplicate EEXIST, absent ENODATA, idempotent delete. Direct reads verify restored tags; integrity failures remain zero. |
| Key lifecycle | Random keys generated only by protected CLI. Full zero scan after every successful generation; known unit write; lock denial; retained same-generation snapshot; unlock exact data; destroy clears slot and denies open. No key material is logged. |
| Integrity corruption | Existing combined M4/M5 build tests ciphertext, tag and relocation corruption; unchanged sentinel buffer, EIO, latch, rejected bypass, correct counters and fresh-generation recovery. M8 proves snapshot restore cannot clear the latch. |
| Fault handling | M9 test build: store allocation init failures publish no nodes; seven one-shot call-site failures; failed loads retain generation/NO_KEY, failed snapshot leaves live state, failed crypto write leaves old unit/tag, failed read leaves output untouched, retry works. |
| Invalid UAPI | Every mutation: version/size/flags/reserved, invalid pointers; key lengths zero/short/oversize; unknown commands and altered encodings; output pointers; protected-page partial copies; unchanged state/slot/stats and malformed CLI. Inherited tests retain passed-fd EPERM and HTTP abuse. |
| Load/unload stress | New NO_KEY/empty slot/reset snapshot counters after each load, full zero scan and representative I/O/key/snapshot; alternate explicit destroy with unload while a slot exists; nodes/sysfs must disappear. |
| Kernel health | Start/end markers acknowledged in follow-new capture, then scan all new Oops/BUG/panic/KASAN/KCSAN/lockdep/hung-task/free/sleep/WARNING/trace signatures. Any warning stays FAIL for operator classification; expected integrity-latch messages are not warnings. |

Unknown or unexpected errno fails. Tests do not require impossible transitions
to succeed and do not weaken existing tests. Slot generation mismatch is covered
by actual C core tests; the public destroy transition removes the slot, so the
real kernel oracle after rekey is ENODATA, not an invented ESTALE response.

## Fault selector and limitations

Clean before `make M9_TEST=1`. Only that build links `src/secureram_fault.c` and
publishes root 0600 `/sys/module/secureram/parameters/m9_fault`; writes also
require CAP_SYS_ADMIN in the initial namespace. The acceptance harness owns
the selector. Values: 0 disarm, 1 next store data allocation, 2 tags allocation,
3 crypto request allocation, 4 encryption, 5 decryption, 6 MAC, 7 control key
input allocation. A matching site atomically consumes the value to zero.
Out-of-range values fail EINVAL. There is no address, key, data or length input.

The harness checks consumption rather than treating an armed but unreached
fault as success. Allocation sites return ENOMEM, crypto sites EIO, through
normal existing cleanup. M9 error injection is independent of M5 corruption.
Final acceptance rebuilds production and checks exclusion again.

These cover representative partial initialization and unit failure paths;
they do not instrument every allocator, HKDF step, provider-internal callback,
module publication failure or late unit of a multi-unit write. The normal VM
does not certify absence of all leaks/races or physical memory remanence.
Optional KASAN/KCSAN/lockdep/kmemleak runs require an appropriately configured
kernel; collect only fresh reports and do not suppress splats. Global Linux
failslab/fail_page_alloc campaigns are not enabled by this harness because
they can disrupt unrelated privileged services and depend on kernel config.
No custom kernel rebuild is mandatory for M9.

## Evidence and interpretation

The printed `.cache/m9-vm/<UTC-time>-<pid>/` directory is private (0700) and
returned to the invoking owner. `environment.txt` records SHA/kernel/parameters;
`summary.txt` and `status.tsv` contain stage results; `main.log`, build logs,
`stress.log`, `faults.log`, `reload.log`, inherited regression logs and fresh
`dmesg.log`/kernel-health context retain diagnostics. Cache artifacts are ignored.
Only public deterministic test data/hashes are allowed. Keys and the dashboard
startup credential remain in process memory/pipes, never evidence.

Every stage starts NOT RUN, transitions through NOT COMPLETED and becomes PASS
only after its assertions. A worker failure, timeout, bad kernel log, lost log
capture, cleanup failure or skipped stage makes OVERALL FAIL and exit nonzero.
Inspect the earliest failed stage; later NOT RUN is expected after fail-fast.
Do not mark runtime acceptance from local tests, mocks or compilation.

Return the exact SHA, `summary.txt`, `environment.txt`, and failing stage/kernel
diagnostics if any. An accepted M9 completion report and manual merge commands
will be issued only after actual Ubuntu results satisfy the definition of done.
No M10 work, push or merge is authorized here.
