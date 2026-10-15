# SecureRAM troubleshooting

| Symptom | Class | Meaning and remedy |
| --- | --- | --- |
| `Kernel headers ... REQUIRED` | Fatal for build/runtime | Install headers for `uname -r`, or use `KDIR` only for an explicitly compile-only build. |
| Header/kernel mismatch | Fatal for runtime; informational for compile-only | Rebuild against `/lib/modules/$(uname -r)/build`. Never load an Ubuntu-generic module in WSL. |
| `Skipping BTF generation ... vmlinux` | Expected warning | Common for external modules when usable BTF input/pahole is absent. It is not a driver warning; inspect the rest of the build log. |
| Compiler command/version differs from kernel build | Warning requiring review | Use the target distribution compiler where practical. A warning is not runtime acceptance. |
| Module already loaded | Benign state | `sudo make load` reports this without reinsertion. Use `sudo make status`; do not stack another load. |
| Module absent on unload | Benign state | `sudo make unload` reports already unloaded if no nodes remain. |
| Device node missing after load | Fatal setup problem | Run `udevadm settle`, inspect fresh `dmesg`, module signature policy and `/sys/class/block/secureram0`. Do not create a substitute node manually. |
| Module absent but node remains | Safety stop | The lifecycle script refuses deletion. Inspect major/minor and udev ownership manually; never assume an ambiguous node is SecureRAM-owned. |
| `Permission denied` / CAP_SYS_ADMIN | Fatal for operation | Invoke device commands through sudo from the ordinary checkout owner. Do not weaken `/dev/secureramctl` mode 0600. |
| `Device or resource busy` | Expected state rejection or real holder | Unmount and close block users; inspect `findmnt -S /dev/secureram0` and legitimate processes. Never force unload. |
| `Required key not available` | Expected in NO_KEY/LOCKED | Load a fresh key in NO_KEY or unlock from LOCKED. Query status before retrying. |
| `Input/output error` and state 4 | Security failure | `INTEGRITY_FAILED` is latched. Close users, destroy, then load a fresh key; unlock cannot bypass it. |
| No snapshot / snapshot occupied | Expected state rejection | Create only when absent; explicitly delete before replacement. Restore requires ACTIVE. |
| Dashboard `module_absent`/`cli_missing` | Clear integration failure | Build the CLI and load the matching module; refresh after fixing. The UI intentionally shows no mock state. |
| Dashboard unavailable/stale | Recoverable service issue | Confirm the backend still runs, use the exact printed URL/token and do not reuse a URL after restart. Controls disable on stale state. |
| VirtualBox shared-folder execute/build issue | Environment issue | Copy the Git bundle or checkout into the VM user's Linux home; shared folders can have ownership/executable semantics unsuitable for kernel builds. |
| `rmmod: Module secureram is in use` | Safety stop | Close block/control descriptors, unmount, stop the dashboard, then retry. Never use forced removal. |

For acceptance failures, inspect the earliest FAIL in `summary.txt`, then its
named log, `kernel-health-failures.log`, `kernel-unrelated-review.log` and cleanup
status. Later NOT RUN entries are expected after fail-fast and must not be called
PASS. Preserve evidence before changing the candidate.
