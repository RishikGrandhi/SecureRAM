# SecureRAM professor demonstration

## Exact command

Use a clean, reviewed checkout in the disposable Ubuntu VM. Ensure SecureRAM is
not already loaded, authenticate sudo, then run:

```sh
cd ~/SecureRAM
sudo ./scripts/demo-secureram.sh --quick
```

`--quick` uses 8 MiB and is intended for a review. `--full` uses 64 MiB and also
runs the inherited direct-I/O oracle; neither mode runs M9 stress or M10
benchmarks. The command returns nonzero on a real failure and retains a log under
`.cache/m11-final/demo-*/demo.log` without keys, backing bytes or credentials.

## What the nine stages prove

| Stage | Demonstration | OS/security point |
| --- | --- | --- |
| Production build | Builds module/CLI and scans the artifact | Test mechanisms are not silently present in normal use |
| Load and key | Loads a bounded RAM device and generates an ephemeral key | Module lifecycle, privileged UAPI, protected key handling |
| Exact block I/O | Writes recognizable data and compares direct readback | Real block path, request processing and authenticated storage |
| Snapshot rollback | Captures A, overwrites with B, restores exact A | Snapshot owns ciphertext/tags for the same generation |
| Lock/unlock | Denies block access while locked, then reads exact A | Access state changes without discarding the resident key |
| Status/statistics | Shows geometry, generation and counters | Observable deterministic management surface |
| Production cleanup | Destroys key and unloads | Ordered teardown and volatile data loss |
| **TEST-ONLY** security checks | Builds bounded M4/M5 hooks, proves stored bytes differ from plaintext, corrupts ciphertext/tag/placement | Confidentiality observation, verify-before-decrypt, EIO latch and recovery; not a production interface |
| Restore production | Rebuilds/scans the default module and leaves it unloaded | Demo cannot accidentally leave a test artifact active |

The key is never printed or saved. The recognizable demo payload is public and
temporary. The corruption mechanism accepts only bounded unit-level operations,
is available only in the labelled test build and is absent from the final
production artifact.

## Expected finish

```text
[1/9] Production build and test isolation        PASS
...
[9/9] Restore production artifact and final cleanup PASS

SECURERAM DEMONSTRATION COMPLETE
```

Point out that AES-XTS provides confidentiality while HMAC provides integrity;
encryption alone would not detect tampering. Explain that the demo intentionally
switches to a test build only after production cleanup, then rebuilds production.
Also state the limits: volatile storage, filesystem/application plaintext caches,
no protection from malicious root/kernel/hypervisor, and same-unit same-generation
valid-pair replay.

## Interrupted demo recovery

Do not force unload. First inspect the fixed device and holders:

```sh
findmnt -rn -S /dev/secureram0
lsmod | grep '^secureram '
sudo ./tools/secureramctl status
```

If no block user is open, destroy and unload, then rebuild production:

```sh
sudo ./tools/secureramctl destroy
sudo make unload
make clean
make W=1
make check-production
```

If cleanup still fails, preserve the newest demo log and fresh kernel messages;
do not delete ambiguous nodes or retry destructive operations blindly.
