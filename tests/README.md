# Verification by milestone

M1 is a lifecycle-only module. Its meaningful checks are a real Kbuild compile,
compiler-warning and metadata inspection, and manual load/log/unload on a
matching Linux kernel. Follow [the developer workflow](../docs/development.md)
and record results in [the M1 report](../docs/m1-report.md). The environment
checker is read-only; it never loads the module.

There are deliberately no fake I/O tests for a device that does not exist and
no test harness duplicating the two lifecycle functions. M2 will add automated
storage tests as it introduces observable block-device behavior. Later milestones
will add crypto, corruption, concurrency, stress, and benchmark coverage.
