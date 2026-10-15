# M11 production-readiness design and audit

## Baseline and scope

M11 started from clean `main` commit
`99030972967317628bdbab587dfcaf09d697f5dd` on branch
`m11-production-readiness`. M10 was already merged and accepted. M11 does not
redesign crypto, UAPI, queueing or storage, and does not optimize benchmark
results. Production files under `src/`, `include/` and `Kbuild` remain unchanged.

## Integration audit findings

The kernel, CLI and dashboard already had strong accepted behavior and clear
failure handling. The real usability/reproducibility gaps were:

1. the preflight was accurate but build-centric and did not separately enforce a
   matching non-WSL runtime target or present required/optional results clearly;
2. build was simple, but load/status/unload were scattered manual commands with
   no guarded, idempotent project entry point;
3. production exclusion existed inside milestone harnesses but not as a normal
   user-facing artifact check;
4. no bounded professor demo composed existing confidentiality, integrity,
   snapshot, statistics and lifecycle capabilities while clearly labelling test
   instrumentation;
5. no final command proved a clean exact-commit checkout, representative
   end-to-end integration, fresh kernel health and cleanup without repeating the
   full M9/M10 campaigns;
6. the top-level README led with historical milestone detail rather than a
   clean-checkout user's path.

No production kernel, crypto, UAPI, CLI or dashboard defect was found during the
audit. Repository hygiene was already sound: build products, `.cache`, Python
caches, CLI binaries and editor state are ignored; retained M10 evidence is
intentional. No historical evidence or generated report figure was removed.

## M11 design

- `check-environment.sh` has read-only build and runtime modes, explicit
  REQUIRED/OPTIONAL remediation and no package installation.
- `secureram-lifecycle.sh` backs Make targets for load/status/unload. It refuses
  test artifacts, mounted unload, ambiguous stale nodes and forced removal.
- `check-production-build.sh` scans the actual module for known fault, corruption,
  test-binding and diagnostic surfaces before normal loading.
- the demo uses fixed `/dev/secureram0`, protected random CLI keys, deterministic
  public data and accepted bounded test helpers. Test hooks are enabled only in a
  labelled phase; the final artifact is rebuilt and proved production.
- final acceptance creates a detached worktree at the reviewed full commit, runs
  there, copies private evidence back, then removes the temporary checkout. It
  composes accepted M6–M8 production/dashboard/snapshot/integrity helpers, not M9
  stress or M10 benchmarks.
- version remains 0.8.0. M11 changes integration/docs/test tooling rather than the
  driver/ABI/dashboard product; inventing 1.0 would create needless production
  churn and invalidate otherwise applicable evidence.

## Production/test boundary

Normal `make` does not define `SECURERAM_M4_TEST`, `SECURERAM_M5_TEST` or
`SECURERAM_M9_TEST`. The M9 fault object is linked only with `M9_TEST=1`; the M5
tamper ioctl and M4 diagnostics are preprocessor-excluded by default. The
production scanner and inherited runtime ENOTTY/parameter checks verify the
artifact boundary. No key/plaintext dump or debug bypass exists.

## Capability and validation matrix

| Capability | Implemented | Validation source |
| --- | --- | --- |
| RAM-backed `blk-mq` block storage | Yes | M2–M9; M11 block I/O |
| AES-256-XTS confidentiality | Yes | M4/M5 design; labelled M11 test observation |
| HMAC-SHA-256 integrity | Yes | M5/M9; M11 corruption/latch recovery |
| Key lifecycle | Yes | M4–M10; M11 CLI/integration |
| Secure volatile snapshot | Yes | M8/M9/M10; M11 rollback/API |
| CLI and deterministic JSON | Yes | M6/M9; M11 local/VM integration |
| Local dashboard | Yes | M7/M8/M9; M11 backend/API integration |
| Fault/error handling | Yes, bounded evidence | M9 fault/stress acceptance; not rerun by M11 |
| Concurrency/stress | Yes, bounded evidence | M9 45/45 accepted campaign; inherited |
| Performance evaluation | Yes, descriptive | M10 retained trials, analysis and limitations |
| Production/test isolation | Yes | M9/M10 plus M11 artifact scan/runtime checks |
| Clean-checkout reproducibility | Pending VM until executed | M11 detached-worktree acceptance |
| Professor demo | Implemented; pending VM until executed | M11 quick demo and evidence log |

## Evidence status

Local checks and real VM acceptance are recorded only after execution. Until the
user returns a passing M11 run, the quick demo, clean-worktree reproduction,
kernel health and final cleanup remain **implemented but not runtime accepted**.
See [M11 testing](m11-testing.md) for the exact evidence contract.
