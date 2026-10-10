# Verification by milestone

M1's successful VM lifecycle check is recorded in [its report](../docs/m1-report.md).
M2's exact manual commands and acceptance criteria are in
[the M2 VM test procedure](../docs/m2-testing.md).

`m2-raw-io.py` is an opt-in destructive raw-I/O test **only for a freshly loaded,
unmounted `/dev/secureram0`**. It accepts no other path. Run it in the VM using
`sudo python3 tests/m2-raw-io.py` after following the identity/build checks.

It checks geometry, every initially zeroed byte, a temporary-file round trip,
page-aligned direct I/O at multiple offsets, neighboring-block isolation,
concurrent disjoint transfers, EOF/beyond-end behavior, and flush. `O_EXCL`
refuses a mounted or exclusively held device. Runtime testing is not executed
by `make` or by the read-only environment checker. Reload before repeating it.

The guide additionally covers module ownership, unsupported discard, optional
ext4, unload/reload, and invalid capacity parameters. M2's completed acceptance
results are recorded in [the M2 report](../docs/m2-report.md); the guide remains
available for broader regression runs. Broad failure injection,
crypto/corruption tests, stress, and benchmarking remain later milestones.
