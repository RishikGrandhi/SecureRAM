# M7 testing and VM acceptance

**Automated M7 VM runtime acceptance: PASS on exact commit
`08d1ade75215dc237342569f9c9c3dc2fd2957a3`.** Driver/CLI remain 0.6.0,
ABI 1, features 15; dashboard is 0.7.0. A subsequent real Ubuntu Firefox check
loaded static UI/status/stats but exposed `Origin: null` on lifecycle POSTs under
the original `no-referrer` policy. The current `same-origin` policy correction
is locally tested; its real Firefox re-verification is **NOT RUN**. Preserve the
accepted automated result as historical evidence while keeping the browser defect
and current patch status separate.

## Local checks (no module or device access)

From the repository root, using existing Python 3.10+ and Node if available:

```sh
python3 tests/check-m7-local.py
python3 tests/check-m6-local.py --kdir /path/to/prepared/headers \
  --checkpatch /path/to/kernel/scripts/checkpatch.pl
```

The M7 runner byte-compiles dashboard/test Python, validates local HTML assets,
IDs and labels, checks JavaScript syntax and exact-number/state/rate helpers,
runs the backend HTTP suite and mocked M7 harness, checks every shell script
with its own `bash -n`, and finishes with `git diff --check`. No packages are
installed. ShellCheck runs only if installed. Linux covers symlinks, /proc
listener inspection and signals; Windows covers applicable HTTP/static/JS tests.
The M6 runner additionally supplies clean kernel builds and C/ABI regressions.

Individual entry points for diagnosis:

```sh
python3 tests/check-m7-dashboard.py
node --check dashboard/static/app.js
node tests/check-m7-ui.js
bash tests/check-m7-vm-harness.sh
python3 tests/check-m7-observe.py
```

The HTTP suite runs the actual server on real ephemeral loopback sockets with a
mocked CLI, including captured subprocess arguments. It tests all six routes,
static assets/security headers, missing/wrong/empty/duplicate bearer values,
Host/Origin/fetch metadata, methods, confirmation, framing and body limits,
malformed JSON, unknown actions, literal/encoded traversal and static symlinks.
It asserts `shell=False`, fixed argv/environment/timeout, strict output schemas,
full u64 precision, nonzero-exit and timeout failures, bounded worker/controller
concurrency, rapid failed-state rejection and destroy/load recovery. CLI errors,
exceptions and request logs must not reveal tokens, key-like sentinels, paths or
tracebacks. Linux entrypoint subprocess tests exercise real SIGINT and SIGTERM
with only the UID gate mocked, without invoking a real CLI/device; ordinary-user
production launch is separately rejected.

The browser-policy regression requires `Referrer-Policy: same-origin` in both the
HTTP response and HTML metadata, then proves a POST carrying the exact expected
Origin and `Sec-Fetch-Site: same-origin` reaches the one allowed lifecycle command.
Missing, `null` and cross-origin Origin, wrong Host, missing/wrong token and
cross-site fetch metadata remain rejected before subprocess invocation. Python's
HTTP client supplies headers explicitly; it precisely tests the contract but does
not claim to reproduce Firefox's Origin-generation behavior.

The M7 harness self-test executes actual M7 overrides around all four M6 phase
functions with module/device/build operations mocked. It retains the historical
M5/M6 failure, cleanup, ext4/redirection and reporting tests. Python observer tests
also run the real HTTP assertion client against a fixture server, require invalid
counter/schema/recovery observations to fail, inspect a real /proc listener, and
mock backend start/stop plus phase/startup/cleanup failures. Expected synthetic
FAIL messages are successful negative tests only when the self-test exits zero.
These mocks do not verify real sudo ownership, kernel state transitions or crypto.

## Observed local evidence — 12 October 2026

| Check | Observed result |
| --- | --- |
| M7 local runner, WSL | PASS after policy fix: 24 backend/HTTP tests; five observer/session tests; Python/static checks; Node syntax/helpers; M7 and inherited M5/M6 mocked harness paths. |
| M7 local runner, Windows | PASS after policy fix: 24 backend tests discovered, 22 passed and two Linux/symlink checks skipped; Python/static and Node checks passed. Full Linux coverage is provided by the WSL run. |
| Individual shell syntax | PASS: each of all 16 shell files was passed separately to `bash -n`. |
| ShellCheck | NOT RUN: not installed. No dependency installation performed. |
| M6 complete local runner | PASS: production, M5-only and combined M4/M5 W=1 builds; MODPOST/link; strict CLI/helper build; real CLI argument/help/version and syscall fixtures; LP64/ILP32 production/test ABI objects; strict checkpatch; import/export and production exclusion proofs; historical mocked harness. |
| Browser rendering | PASS for the patched policy in the labelled, unprivileged Codex browser fixture on Windows: same-origin lifecycle Load reached ACTIVE with no console warning/error. This is neither Firefox nor a real device observation. |
| M7 Ubuntu VM acceptance | PASS on exact committed candidate `08d1ade75215dc237342569f9c9c3dc2fd2957a3`; full automated ledger passed before the manual browser defect was found. |
| Ubuntu Firefox against the real driver | PARTIAL/DEFECT OBSERVED on `08d1ade`: UI and GET status/stats worked; Load Random Key was rejected because Firefox sent `Origin: null`; CLI remained NO_KEY/generation 0. Post-fix re-test NOT RUN. |

Reproducible compile target used in WSL:

```sh
python3 tests/check-m6-local.py \
  --kdir /home/rishik_grandhi/.cache/secureram-m2-20261010/root/usr/src/linux-headers-7.0.0-38-generic \
  --checkpatch /home/rishik_grandhi/.cache/secureram-m2-20261010/root/usr/src/linux-hwe-7.0-headers-7.0.0-38/scripts/checkpatch.pl
```

Current ignored transcripts are `build-m7-fix-local.log`,
`build-m7-fix-windows.log` and `build-m7-fix-m6-regression.log`.
The latter ends with the complete M6 local-verification PASS. WSL runs
`6.18.33.2-microsoft-standard-WSL2`; prepared headers target Ubuntu
`7.0.0-38-generic`. Retained environmental warnings are GCC 15.2 versus target
GCC 13.3, unavailable local pahole (target version 125), and skipped BTF because
vmlinux is unavailable. No new driver-source warning or MODPOST error was seen.
This is compile-only evidence; no module was inserted in WSL.

## Browser fixture evidence

`python3 tests/m7-preview.py` starts separate, ordinary-user test code with a
mocked CLI and an unmistakable fixture banner. `--state 4` selects a synthetic
integrity-failed observation. The production entrypoint has no simulation flag.
The fixture's printed URL is an ephemeral credential too; do not retain it in
screenshots or evidence logs.

Observed through actual browser automation: NO_KEY; Load -> ACTIVE; Lock ->
LOCKED; Unlock -> ACTIVE; typed Destroy confirmation -> NO_KEY; live refresh;
desktop and 390-pixel narrow layouts without horizontal overflow; visible stale
state and disabled controls after backend loss. INTEGRITY_FAILED renders its red
state card and full-width warning, with only Destroy enabled. The URL fragment
is removed after startup. This is browser rendering and interaction evidence
using synthetic values, not validation of real I/O or authentication failures.
The failed-state fixture was recovered through exact typed DESTROY -> NO_KEY ->
Load -> ACTIVE; lowercase confirmation remained disabled. Reload required
authorization, reopening the startup URL in the same tab restored it, and an old
token was rejected after a backend restart before the new URL reconnected.
The same-tab check exposed a fragment-navigation bug, fixed by reloading when a
new token fragment arrives; no credential is persisted. Desktop browser console
checks found no JavaScript errors before intentional disconnection.
The existing browser tooling was used without installing a browser package.
Ignored screenshots are `.cache/m7-dashboard.jpg`, `.cache/m7-mobile.jpg` and
`.cache/m7-integrity.jpg`, plus failed-state mobile and recovered-state captures.

## Full-SHA VM invocation

After separate review/authorization to commit the candidate, use a clean checkout
of that exact M7 commit on `m7-dashboard` in the disposable Ubuntu desktop VM.
Snapshot/select the intended VM, verify the reviewed full SHA, running kernel,
matching headers/compiler and ordinary checkout owner. No existing SecureRAM
module, nodes or mounts may be present. Never invoke this suite in WSL, on a real
disk target, or while another dashboard/browser is issuing actions.

From the VM checkout as its ordinary owner:

```sh
git status --short --branch
git rev-parse HEAD
uname -r
# Compare that full SHA to the reviewed M7 candidate before continuing.
export M7_EXPECTED_COMMIT=$(git rev-parse HEAD)
sudo --preserve-env=M7_EXPECTED_COMMIT bash tests/run-m7-vm-acceptance.sh
```

The accepted historical invocation pinned `08d1ade75215dc237342569f9c9c3dc2fd2957a3`.
Any rerun for a committed patch must pin that new reviewed M7 commit, never the
M6 base, the old candidate or a shortened hash.
The harness requires exactly 40 lower-case hex characters, compares full HEAD,
requires branch `m7-dashboard` and a clean checkout, verifies kernel/header match,
rejects WSL and takes no device arguments. Invoke through sudo so SUDO_USER names
the ordinary builder; do not run from a root login or override ownership variables.

## Automated phases and acceptance categories

1. Shared preflight creates an owner-only, builder-owned unique
   `.cache/m7-vm/<UTC-time>-<pid>/` evidence directory. Local HTTP/contract tests run
   as the ordinary builder. Fresh dmesg capture begins before runtime phases.
   The Python session owner explicitly starts the real root backend, captures
   the startup URL only in a memory pipe, checks its /proc listener is exactly
   127.0.0.1 with no IPv6 listener, and supplies the credential only in test-child
   environment memory. The token is never written to a log/file or command argv.
2. Production: clean W=1 build/exclusion proof; CLI/helper builds and real CLI
   help/version; NO_KEY status/stats via both CLI and HTTP; 0.6.0/ABI 1/features
   15; malformed ABI/privilege/reserved/EFAULT and production ENOTTY tests. Load
   via HTTP -> ACTIVE, full raw I/O, increased HTTP counters and exact direct-I/O
   accounting through the existing M6 observer. Lock/unlock, retained contents,
   destroy/idempotence/rekey, ext4 sync/remount and mounted EBUSY all retain M6
   assertions while routing lifecycle through HTTP. After unload, static/auth/
   hostile HTTP checks require an authorized module-absent response, proving the
   same backend remains responsive across module removal.
3. Combined M5/M4 test build: all original ciphertext/tag/relocation, failed-unit
   sentinel, invalid-hook/passed-fd and full-zero-scan assertions. Each latch must
   be visible as HTTP INTEGRITY_FAILED and increment integrity_failures exactly
   once. Rapid load/lock/unlock attempts cannot clear it; HTTP destroy -> NO_KEY,
   HTTP fresh load -> ACTIVE, and counter-retention/zero-medium checks follow.
   Three cases finish NO_KEY at generation 6 with three failures. The automated
   suite verifies the API; the browser warning has separate visual evidence.
4. Clean production capacity build: reject 0/257 MiB, run 1 MiB and 256 MiB
   load/raw/accounting/destroy/unload lifecycles with fresh zero counters and
   actual capacity/status through HTTP after each reload.
5. Final clean production rebuild: symbol/string/dispatch exclusion and ENOTTY,
   final CLI/HTTP/raw/ext4/mounted-busy regression, destroy/unload and absence of
   both nodes, sysfs objects and module. Stop the dashboard normally and prove
   its listener closed. Forced process cleanup is FAIL, never a clean-stop PASS.
   Shared finalization screens fresh kernel logs, returns evidence ownership and
   prints the failure-preserving ledger and OVERALL result.

The ledger retains M6's detailed Production build, CLI build/help/version,
Version/features, Human/JSON status, Stats baseline, Random key load (through the
API), Raw I/O, Stats accounting, Lock/unlock, Destroy/rekey, ext4, Mounted busy
rejection, Integrity-failure observability, Tamper regression, Recovery, Capacity
parameter rejection, 1/256 MiB, Final production regression, Kernel health and
Final cleanup. M7 adds Dashboard startup, Loopback-only binding, HTTP
authorization, Static UI, Status API, Stats API, HTTP adversarial,
Integrity-failure API and Dashboard cleanup. `Static UI` means HTTP asset checks,
not an automatically claimed Ubuntu visual PASS.

Every category starts NOT RUN, becomes NOT COMPLETED when reached, and receives
PASS only after its entire group succeeds. Unexpected failure stops later phases;
unreached groups stay NOT RUN. A preflight rejection before evidence setup has no
ledger and claims no runtime result. Missing/no-runtime dmesg cannot establish
kernel health; lost collection, crash/warning signatures, failed cleanup or
ownership release cannot produce OVERALL PASS. Expected tamper EIO is distinct
from an Oops/BUG/panic/warning/call trace.

## Identity, ownership and cleanup audit

All destructive commands retain literal `/dev/secureram0`, never a caller device
argument. Shared guards validate type, major:minor, root ownership/mode, version,
capacity/unit, mounts, holders and swap. Python raw tests repeat identity checks
and use O_EXCL/O_DIRECT. The actual ext4 helper uses `nodiscard`, compares retained
files, revalidates its owned mount before unmount, and refuses unsafe cleanup.
Only a module inserted by the phase is destroyed/unloaded. No force unload.

The full-SHA, SUDO_USER, `.cache` ownership, nounset initialization, Bash dynamic
scope/readonly names, redirection, individual syntax-check, no-eval, no generated
shell-command, missing-log and fail-fast summary audit is recorded in
[the M7 report](m7-report.md#harness-reuse-and-defect-audit). M7 reuses the accepted
M5/M6 functions and tests their actual overridden flow; the `08d1ade` VM run
exercised real sudo/runuser, ownership and cleanup. OS-level killing, power loss
or an uninterruptible kernel operation is not an orderly-cleanup guarantee.

Review `main.log`, phase/build logs, `status.tsv`, `summary.txt`, `dmesg.log`,
`dashboard-stderr.log`, kernel-health context and production symbol/string proofs.
Do not add the startup URL to evidence. Classify a failure as dashboard, driver,
CLI, harness or environment before any separately authorized repair/rerun. Keep
the failed run; never silently retry until green. All evidence/build products are
ignored by Git. If interrupted, inspect retained cleanup results and actual VM
state before starting anything else.

## Post-fix Ubuntu Firefox re-test — NOT RUN

After automated acceptance and cleanup, use the final production build for the
VM's running kernel. Confirm the disposable VM and that no SecureRAM instance
or mount remains. In the trusted checkout, launch explicitly:

```sh
sudo modprobe hkdf
sudo insmod ./secureram.ko capacity_mb=64
sudo udevadm settle
sudo ./tools/secureramctl status --json
sudo python3 -I dashboard/server.py
```

Use the ordinary user's browser in the same VM to open the printed loopback URL.
Do not launch a root browser, forward the port or save the credential. Record
date, exact M7 SHA, Ubuntu/kernel/browser version, observed results and any layout
defect; screenshots must omit the startup terminal/URL token.

This re-test closes the observed integration defect. Start Firefox DevTools before
the first action and preserve only non-secret header/result notes:

1. Confirm the initial dashboard and direct CLI both report NO_KEY (0), generation
   0, 64 MiB, ABI 1, features 15 and versions 0.6.0/0.7.0.
2. Confirm `/`, `/app.js`, `/api/status` or `/api/stats` responses show
   `Referrer-Policy: same-origin`; the page source has the matching meta policy.
3. Click Load Random Key once. Inspect that POST: Host is the printed
   `127.0.0.1:<port>`, Origin is exactly `http://127.0.0.1:<same-port>` (not
   `null`), and Sec-Fetch-Site is `same-origin`. Do not record the bearer value.
4. Require HTTP success, dashboard ACTIVE (2), generation 1, and matching direct
   CLI status. If the action response is ambiguous, refresh/inspect state; never
   retry automatically.
5. With no block users, click Lock and require LOCKED (3), then Unlock and require
   ACTIVE (2); inspect that both POST Origins remain exact.
6. Open Destroy, verify Cancel is harmless and lowercase text cannot confirm.
   Type exact `DESTROY`, submit once, and require dashboard plus CLI NO_KEY (0),
   generation 1.
7. Repeat the responsive, counter refresh and disconnect/reconnect observations
   below. Restart the backend and verify its old token fails and its new printed
   URL works. Stop the backend normally and complete device cleanup.

Do not mark the patch browser-accepted unless the exact-origin lifecycle POSTs and
driver states above are observed in real Ubuntu Firefox. The Python suite and
other browser automation are supporting evidence only.

| Visual/action check | Required observation (record actual PASS/FAIL/NOT RUN) |
| --- | --- |
| Initial layout | Readable state/lifecycle/statistics/metadata panels; NO_KEY=0, actual geometry, driver/CLI 0.6.0, ABI 1, features 15 and dashboard 0.7.0. |
| Load random key | ACTIVE=2, generation increments, availability changes; no key displayed. |
| Refresh/statistics | Values refresh. To see real read accounting after ACTIVE, a separate VM terminal may run `sudo dd if=/dev/secureram0 of=/dev/null bs=4096 count=16 iflag=direct status=none` after confirming the just-loaded device identity; compare the CLI stats. Cache hits need not reach the driver. |
| Lock/unlock | With no block users, LOCKED=3 then ACTIVE=2; keys/contents are retained. |
| Destroy dialog | Cancel leaves state unchanged; confirm remains disabled until exact DESTROY is typed. Confirm destroys data and returns NO_KEY. |
| Responsive view | Narrow the window (about 390 pixels), check wrapping/order, readable controls and no horizontal clipping. |
| Disconnect/reconnect | Stop the server with Ctrl+C; controls become disabled/stale. Restart and open its new printed URL; old token must not authorize the new session. Server stop itself changes no driver state. |
| Failed-state warning | Use a separately authorized test-build session if demonstrating real tamper. Do not run tamper/raw suites concurrently with browser actions or claim a synthetic fixture is real corruption. The automated harness covers the actual API latch/recovery. |

Stop the backend, close the browser, close/unmount any demo users, then clean the
owned demo instance (never force unload):

```sh
sudo ./tools/secureramctl destroy
sudo rmmod secureram
sudo udevadm settle
test ! -e /dev/secureram0
test ! -e /dev/secureramctl
test ! -e /sys/block/secureram0
test ! -e /sys/class/misc/secureramctl
test ! -e /sys/module/secureram
```

The manual check validates presentation, not additional crypto guarantees.
Compat runtime ioctls, allocation/provider fault campaigns, pending-request races,
lockdep/KASAN/kmemleak and physical memory-erasure claims remain outside normal M7
acceptance, as in M5/M6. The unchanged limitations are in [the report](m7-report.md).
