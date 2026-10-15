# M11 final acceptance and evidence

## Local checks

Run in Linux/WSL without root or device access:

```sh
python3 tests/check-m11-local.py
```

This checks shell/Python syntax, M10 local measurement oracles, dashboard/backend
contracts, Markdown links, whitespace, fixed-device/clean-worktree guards and the
absence of M11 production kernel/UAPI/Kbuild changes. Local PASS is not runtime
acceptance.

## One Ubuntu VM command

Use a clean committed `m11-production-readiness` checkout at the reviewed full
candidate SHA. Ensure no SecureRAM module/nodes/mount/backend is already active,
authenticate sudo, then run:

```sh
cd ~/SecureRAM
sudo env M11_EXPECTED_COMMIT=<reviewed-40-character-SHA> \
  bash tests/run-m11-final-acceptance.sh
```

The public runner verifies branch/SHA/cleanliness, creates a detached Git
worktree at that exact commit and executes the campaign there. The internal
worker refuses WSL, mismatched headers, pre-existing module/nodes and missing
prerequisites. No device argument is accepted; destructive I/O remains fixed to
`/dev/secureram0`.

The representative suite performs:

```text
runtime environment and exact clean source
-> local integration checks
-> quick nine-stage demo
-> production module/CLI build
-> key lifecycle, raw I/O and ext4
-> real dashboard backend/API
-> snapshot rollback/API/reload
-> bounded test-only integrity corruption and recovery
-> final production build/exclusion regression
-> fresh kernel-health scan
-> module/node/mount/backend cleanup
```

It does not run M9's full stress/fault campaign or M10's benchmark matrices.
Those accepted results remain applicable because M11 does not change production
kernel/security/UAPI behavior.

## Summary contract

`summary.txt` reports PASS/FAIL/NOT RUN for environment, clean-checkout
reproducibility, build, lifecycle, block I/O, key lifecycle, integrity,
snapshots, CLI, dashboard, statistics, quick demo, production/test isolation,
cleanup and kernel health. Every item starts NOT RUN. A started failure remains
FAIL or NOT COMPLETED and makes OVERALL fail; unexecuted work never becomes PASS.

Fresh kernel capture is bracketed by acknowledged markers. The scanner rejects
Oops, BUG, panic, KASAN/KCSAN, lockdep, hung task, free/sleep diagnostics,
WARNING/Call Trace and SecureRAM test failures. Unrelated warnings are retained
for operator classification and cannot silently become PASS.

## Evidence to return

The runner prints the exact directory under:

```text
.cache/m11-final/<UTC-run-id>/
```

Return at minimum:

- `summary.txt`
- `environment.txt`
- `main.log`
- `production.log`
- `snapshot.log`
- `tamper.log`
- `final-production.log`
- `dmesg.log`
- `kernel-relevant.log`
- `kernel-health-failures.log`
- `kernel-unrelated-review.log`
- the sibling `demo-*/demo.log` referenced by the run output

Do not return dashboard startup stdout; the session owner keeps its bearer token
only in memory. Keys, plaintext backing bytes and credentials are never evidence.

After a failure, preserve the run and report the earliest failed stage. A narrow
fix should request only the smallest affected rerun unless shared lifecycle,
security, kernel-health or cleanup behavior was invalidated.
