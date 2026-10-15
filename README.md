# SecureRAM

SecureRAM is a university Operating Systems project that exposes volatile,
authenticated encrypted RAM as a real Linux block device at `/dev/secureram0`.
It demonstrates the Linux block layer, `blk-mq`, kernel resource lifetimes,
privileged control, AES-256-XTS confidentiality, HMAC-SHA-256 integrity,
single-slot secure snapshots, statistics, a management CLI and a local dashboard.

SecureRAM is educational software, not an audited replacement for dm-crypt.
Data disappears on unload or reboot. Filesystem caches still contain plaintext,
root/kernel/hypervisor compromise is outside the threat model, and a valid
ciphertext/tag pair can be replayed within the same unit and key generation.

## Architecture

```text
applications / filesystem                 management user
            |                                   |
     Linux block layer                 CLI / local dashboard
            |                                   |
          blk-mq                         privileged control UAPI
            |                                   |
            +---------- SecureRAM kernel module-+
                       | AES-256-XTS
                       | HMAC-SHA-256
                       | key lifecycle
                       | encrypted snapshots
                       | statistics
                       v
                 volatile secured RAM
```

The data and control paths meet only inside the driver. Test-only corruption
and fault-injection mechanisms are compile-time opt-ins and are absent from the
normal artifact. See the definitive [architecture](docs/architecture.md) and
[M11 production-boundary audit](docs/m11-report.md).

## Capabilities

- configurable 1–256 MiB RAM-backed block storage (64 MiB default)
- AES-256-XTS confidentiality in 4096-byte units
- Encrypt-then-MAC integrity with full HMAC-SHA-256 tags
- fail-closed integrity latch and destructive recovery
- ephemeral random key load, lock, unlock and destroy lifecycle
- one volatile ciphertext/tag snapshot with restore and delete
- coherent module-lifetime I/O and integrity counters
- dependency-free C CLI and offline localhost dashboard
- deterministic quick demo and clean-worktree final acceptance

## Prerequisites

The validated runtime target is x86-64 Ubuntu 24.04.5 LTS in the disposable
VirtualBox VM, with headers matching its running kernel. The recorded M9/M10
runtime used Linux `7.0.0-38-generic`; always inspect the current kernel rather
than hard-coding that release. Install the distribution equivalents of
`build-essential`, `kmod`, `linux-headers-$(uname -r)`, Python 3.10+, udev and
util-linux. `fio` is optional and needed only to reproduce M10 benchmarks.

The checker is read-only and never installs packages:

```sh
make check-env             # build/compile readiness; WSL may be compile-only
make check-runtime         # matching non-WSL runtime readiness
```

See the [installation guide](docs/installation.md) for exact setup and safety
checks.

## Quick start

Build as the ordinary checkout owner, then use explicit sudo only for lifecycle
operations:

```sh
make check-runtime
make build W=1
make check-production
sudo make load
sudo make status
sudo ./tools/secureramctl load-random
sudo ./tools/secureramctl status
```

`load-random` creates an unrecoverable ephemeral 64-byte XTS key, protects and
wipes its userspace buffer, and never prints or persists it. The medium begins in
`NO_KEY`; block opens are denied until a key is active.

Unmount and close all users before cleanup:

```sh
sudo ./tools/secureramctl destroy
sudo make unload
make clean tools-clean
```

`make load` accepts `CAPACITY_MB=1..256`, refuses known test builds, and succeeds
clearly if the module is already loaded. `make unload` succeeds clearly if it is
already unloaded, refuses mounted/busy devices, never forces unload and never
deletes ambiguous stale nodes.

## CLI

```sh
./tools/secureramctl help
./tools/secureramctl version
sudo ./tools/secureramctl status [--json]
sudo ./tools/secureramctl stats [--json]
sudo ./tools/secureramctl load-random
sudo ./tools/secureramctl lock
sudo ./tools/secureramctl unlock
sudo ./tools/secureramctl snapshot create|status|restore|delete [--json]
sudo ./tools/secureramctl destroy
```

Human diagnostics go to stderr; JSON goes to stdout. Exit codes are 0 success,
1 operation/access failure, 2 usage error and 3 ABI/feature mismatch. See the
[CLI contract](tools/README.md).

## Dashboard

After building the CLI and loading the matching-kernel module:

```sh
sudo python3 -I dashboard/server.py
```

Open the exact printed loopback URL in the VM's ordinary (non-root) browser.
The backend binds only `127.0.0.1`, uses a fresh in-memory bearer token, accepts
only fixed CLI operations and never handles keys or block data. Ctrl+C stops the
backend without changing driver state. See the [dashboard guide](dashboard/README.md).

## One-command demonstration

From a clean VM state with no loaded SecureRAM module:

```sh
sudo ./scripts/demo-secureram.sh --quick
```

The bounded nine-stage demo builds and proves a production artifact, exercises
keyed I/O, snapshot rollback, lock/unlock and statistics, clearly labels a
separate test-only confidentiality/integrity demonstration, restores a production
artifact and cleans up. `--full` additionally runs the inherited direct-I/O
oracle; it does not run M9 stress or M10 benchmarks. See the [demo guide](docs/demo.md).

## Testing and final acceptance

Local checks never load a module:

```sh
python3 tests/check-m11-local.py
```

The final VM command creates a detached clean worktree at the reviewed commit,
runs the environment checker, quick demo and representative inherited
CLI/dashboard/block/integrity/snapshot regressions, inspects fresh kernel logs,
cleans up and writes private evidence under `.cache/m11-final/`:

```sh
sudo env M11_EXPECTED_COMMIT=<reviewed-40-character-SHA> \
  bash tests/run-m11-final-acceptance.sh
```

It never runs the full M9 stress or M10 benchmark campaigns. A stage is PASS only
after its real assertions complete; skipped/unreached work cannot become PASS.
The final Ubuntu run passed every group and `OVERALL` from detached clean
candidate `8f8288602b220d15c90a6b27a5039a23a3885b80`; see the
[M11 testing procedure](docs/m11-testing.md) and
[retained M11 evidence](docs/evidence/m11/README.md). Historical M9 reliability
and M10 evaluation remain documented in [M9](docs/m9-report.md) and
[M10](docs/m10-report.md), with selected M10 evidence in
[`docs/evidence/m10/`](docs/evidence/m10/README.md).

## Security model and limitations

Reads authenticate ciphertext before decryption. An HMAC mismatch returns EIO,
leaves the failed unit's caller buffer untouched and latches
`INTEGRITY_FAILED`; recovery requires closing users, destroying the key and
loading a fresh key. Snapshots contain ciphertext, tags and their key generation,
not plaintext, and are invalidated by destroy/unload.

Encryption does not hide plaintext held by applications or filesystem/page
caches. There is no persistence, online rekey, password storage, remote
administration, AEAD claim, crash-persistent anti-replay, protection from
malicious privileged code or physical-erasure guarantee. Multi-unit requests are
not atomic. See the [M5 threat model](docs/m5-report.md#threat-model-and-claims).

## Documentation index

| Guide | Purpose |
| --- | --- |
| [Installation](docs/installation.md) | Supported environment, dependencies, build and lifecycle setup |
| [Demo](docs/demo.md) | Professor-facing stages, talking points and recovery |
| [Troubleshooting](docs/troubleshooting.md) | Real recurring failures, warnings and remedies |
| [Architecture](docs/architecture.md) | Data/control paths, ownership, key/snapshot/test boundaries |
| [Development](docs/development.md) | Build/static workflow and kernel engineering notes |
| [M11 report](docs/m11-report.md) | Audit decisions and feature/validation matrix |
| [M11 testing](docs/m11-testing.md) | Local checks, VM acceptance and evidence contract |
| [CLI](tools/README.md) | Commands, JSON schema, exit codes and errors |
| [Dashboard](dashboard/README.md) | Local service, API, trust model and UI behavior |
| [Tests](tests/README.md) | Milestone verification inventory |
| [M10 evaluation](docs/m10-report.md) | Performance methodology, results, graphs and limitations |

Source is GPL-2.0-only; see [LICENSE](LICENSE).
