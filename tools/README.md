# SecureRAM management CLI

Build in Linux with `make tools` or `make -C tools`. Only libc and the public
Linux/SecureRAM headers are required. The build always applies C11, `-Wall
-Wextra -Werror -Wconversion`; `make tools-clean` removes the binary. Normal
module builds do not build tools or require Python/JSON libraries.

```sh
./tools/secureramctl help
./tools/secureramctl version
sudo ./tools/secureramctl status
sudo ./tools/secureramctl status --json
sudo ./tools/secureramctl stats
sudo ./tools/secureramctl stats --json
sudo ./tools/secureramctl load-random
sudo ./tools/secureramctl lock
sudo ./tools/secureramctl unlock
sudo ./tools/secureramctl destroy
```

The caller supplies sudo externally. There is no setuid bit, privilege escalation,
password input, device-path override or permission relaxation. Every device ioctl
requires CAP_SYS_ADMIN in the initial user namespace, including QUERY/GET_STATS.
The existing root:root 0600 control node is verified by type, ownership, mode and
sysfs major:minor after opening with O_NOFOLLOW/O_CLOEXEC. Help/version do not open
the device. Version reports the compiled CLI version, not the loaded driver.

All changes require zero block users: unmount/close first. Load requires NO_KEY,
lock requires ACTIVE, unlock requires LOCKED. Destroy is explicitly destructive
and idempotent, returning NO_KEY. ACTIVE replacement requires destroy first.
INTEGRITY_FAILED rejects load/lock/unlock; recovery is destroy then fresh load.
The kernel is the authority on transitions; a preceding status read is not a lock.

`load-random` generates exactly 64 random bytes with getrandom, accommodating
interruptions/short reads. It disables process dumps and requires mlock before
generation. It wipes the entire key ioctl buffer immediately after LOAD_KEY and
on errors, then unlocks memory. Failure to protect the buffer aborts before
generation. Keys never enter argv, stdout, files or JSON. The command reports
only success/failure and resulting state/generation. This is ephemeral/demo key
management: the key cannot be recovered after destroy/unload, and lock retains
the resident kernel key. It is not password storage or protection from root.

Example human output (illustrative, not runtime evidence):

```text
SecureRAM 0.6.0 (CLI 0.6.0)
ABI: 1
State: ACTIVE (2)
Capacity: 64.00 MiB (67108864 bytes)
Crypto unit: 4096 bytes
Generation: 1
Features: 15 XTS LOCK INTEGRITY STATS
Confidentiality: AES-256-XTS
Integrity: HMAC-SHA-256
```

JSON is supported only for status and stats. Success writes one JSON object to
stdout; diagnostics go to stderr, with a nonzero exit status on failure. Do not
parse human output. Stable status fields are:

```json
{"version":"0.6.0","cli_version":"0.6.0","abi":1,
"state":2,"state_name":"ACTIVE","capacity_bytes":67108864,
"unit_bytes":4096,"generation":1,"features":15,
"xts":true,"lock":true,"integrity":true,"stats":true}
```

`version` is read from the loaded module's sysfs version; it is JSON null if
unavailable or malformed. `cli_version` is always the compiled version.
Unknown future state values retain their numeric value with name UNKNOWN.
Unknown feature bits remain visible in the mask. Cipher names in human output
are emitted only when their feature is advertised. ABI version/size/reserved
mismatches fail; STATS must be advertised before GET_STATS is attempted.

Illustrative stats output:

```json
{"abi":1,"read_requests":3,"write_requests":2,
"read_bytes":12288,"write_bytes":8192,"integrity_failures":0}
```

Counters count whole successfully completed driver requests and their bytes,
not application syscalls, pages, units, cache hits or FLUSH. Failed requests add
zero successful requests/bytes, even if earlier units succeeded. The failure
counter counts actual MAC mismatches, not later EIO/denied opens. Zero-medium
initialization and control ioctls do not count. Each GET_STATS is a coherent
snapshot; QUERY and GET_STATS are separate snapshots and are not transactional.
There is a small interval between accounting a finalized successful result and
notifying blk-mq completion. See [the design](../docs/m6-report.md).

Counters survive lock, destroy and rekey for the module lifetime; reload resets
them. Values saturate at 18446744073709551615. JSON integers preserve all 64 bits
in the text; GUI consumers must use an integer-capable parser and avoid converting
large counters to imprecise IEEE-754 numbers. Counters are diagnostic information,
not a security boundary or persistent audit log.

| Exit | Meaning |
| --- | --- |
| 0 | Successful command and output. |
| 1 | Device/access, state/busy, random generation, protection or I/O failure. |
| 2 | Invalid command/arguments. No device opened. |
| 3 | Unsupported ioctl/feature or incompatible ABI response. |

Missing device and permissions have actionable errors. EBUSY can mean open/mounted
users or a forbidden transition; inspect status and the state rules. An action
may complete before its follow-up QUERY, close, or output fails; such an error
does not roll back the action. Re-query before retrying. All commands use the
existing key-control ABI; no production test/tamper command is exposed.

The separate `tests/m4-control.c` remains a regression helper for malformed ABI,
passed descriptors and mounted/busy checks. The production CLI does not depend
on it or on test-build hooks. M6's [testing procedure](../docs/m6-testing.md)
keeps local mocked evidence separate from the successful Ubuntu VM acceptance
of commit `50e11e6ddce88a986719ae2ef7ce972377a69e49`.
