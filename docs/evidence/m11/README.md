# M11 final acceptance evidence

The final Ubuntu acceptance ran on 2026-10-15 from a detached, clean worktree
at candidate commit `8f8288602b220d15c90a6b27a5039a23a3885b80`. The main run ID is
`20261015T131116Z-13747`; the nested quick-demo run ID is
`demo-20261015T131119Z-14342`. Every row in `summary.txt`, including `OVERALL`,
is PASS.

The returned source archive is
`m11-final-evidence-20261015T131116Z-13747.tar`, 983040 bytes, SHA-256
`bf28450307f1ded7e38f06ff29c7297d1c92de08dc4ffe9e4114f8966966bfd4`.
It contained 44 regular files under `m11-final/`, with no absolute paths,
parent traversal, or link entries. `source-sha256.csv` records every archived
file's byte count and SHA-256. The bulk archive remains in the operator's local
Transfer folder; this directory retains the review-critical text evidence.

## Validation notes

- `environment.txt` identifies Ubuntu kernel 7.0.0-38-generic, the exact
  candidate SHA, detached mode and a clean worktree.
- `status.tsv` is append-only. Its temporary kernel-health FAIL is the designed
  fail-closed sentinel written before review; the last kernel-health record and
  the resolved summary are PASS.
- `kernel-health-failures.log` and `kernel-unrelated-review.log` are empty. The
  raw `dmesg.log` contains no Oops, BUG, panic, sanitizer, lockdep, hung-task,
  WARNING or Call Trace signature. `kernel-relevant.log` retains the expected
  SecureRAM lifecycle, labelled M4/M5 test activity, ext4 mounts/unmounts and
  final unload.
- Cleanup passed only after the module, both device nodes, SecureRAM mount and
  owned dashboard process were absent. The public runner also removed its
  detached temporary worktree before reporting success.
- The final production `nm`/`strings` evidence has no M4/M5/M9 fault,
  corruption, binding or tamper surface. The test artifact contains the expected
  bounded hooks, and `final-production.log` records the rebuilt production
  regression and ENOTTY rejection.
- `demo/demo.log` contains nine PASS stages, the explicit test-only boundary,
  production restoration, final cleanup and the completion marker.
- The only build diagnostics are the known compiler-command spelling warning,
  unavailable matching pahole metadata and skipped BTF generation. The GCC
  version itself matches the kernel's GCC 13.3.0; no source-compilation warning
  or error is present.
- A credential/key/private-key pattern scan over every returned file found no
  retained bearer token, password, API key or private key.

M11 did not modify production `src/`, `include/`, `Kbuild`, CLI or dashboard
files relative to baseline `99030972967317628bdbab587dfcaf09d697f5dd`.
Consequently the accepted M9 reliability and M10 evaluation evidence remains
applicable; neither full campaign was repeated.

## Retained files

| File | Purpose |
| --- | --- |
| `summary.txt`, `status.tsv`, `environment.txt` | Resolved outcome, transition history and exact-source/runtime identity |
| `main.log` | Combined final acceptance transcript |
| `production.log`, `snapshot.log`, `tamper.log` | Representative production, snapshot and bounded integrity phases |
| `final-production.log` | Final production rebuild, isolation and regression evidence |
| `dmesg.log`, `kernel-relevant.log` | Fresh raw and scoped kernel evidence |
| `kernel-health-failures.log`, `kernel-unrelated-review.log` | Empty health/review outputs; empty means no matching entry |
| `demo/demo.log` | Nine-stage professor-demo transcript |
| `source-sha256.csv` | Hash manifest for all 44 files in the returned archive |
