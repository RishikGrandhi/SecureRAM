# Verification by milestone

M1's successful VM lifecycle check is recorded in [its report](../docs/m1-report.md).
M2's exact manual commands and acceptance criteria are in
[the M2 VM test procedure](../docs/m2-testing.md).

M3 reuses it via [the M3 regression instructions](../docs/m3-testing.md), with
version `0.3.0` and M3 lifecycle messages. The successful M3 VM run is recorded
in [the M3 report](../docs/m3-report.md); the procedure remains reusable.

`m2-raw-io.py` is an opt-in destructive raw-I/O test **only for a freshly loaded,
unmounted `/dev/secureram0`**. It accepts no other path. Run it in the VM using
`sudo python3 tests/m2-raw-io.py` after following the identity/build checks.
The version allowlist is limited to plaintext M2 (`0.2.0`) and M3 (`0.3.0`);
M4 uses the separate state-aware tests below.

It checks geometry, every initially zeroed byte, a temporary-file round trip,
page-aligned direct I/O at multiple offsets, neighboring-block isolation,
concurrent disjoint transfers, EOF/beyond-end behavior, and flush. `O_EXCL`
refuses a mounted or exclusively held device. Runtime testing is not executed
by `make` or by the read-only environment checker. Reload before repeating it.

The guide additionally covers module ownership, unsupported discard, optional
ext4, unload/reload, and invalid capacity parameters. M2's completed acceptance
results are recorded in [the M2 report](../docs/m2-report.md); the guide remains
available for broader regression runs. Broad failure injection,
corruption tests, stress, and benchmarking remain separately scoped work.

For M4, follow [the M4 procedure](../docs/m4-testing.md). Compile `m4-control.c`
against the shared UAPI to `.cache/m4-control`. It supports query, ephemeral
random test-key loading, lock/unlock, destructive key removal and negative/busy
ABI checks. It is a test helper, not the final CLI; no test keys are committed.

`m4-raw-io.py denied` checks ENOKEY read/write-open failures. Its destructive
`active` mode requires a newly keyed, unmounted device, validates M4 identity,
uses exclusive direct I/O, reuses M2's data checks, and adds SHA-256/cmp and
opener-protection tests. Neither mode accepts an alternative device target.

The `M4_TEST=1` module build adds internal comparisons of actual backing bytes
and exercises split/cross-unit fragments during setup. It exports no memory.
Clean before switching variants. M4 runtime results, including execution of
these hooks, remain pending; see [the report](../docs/m4-report.md).
