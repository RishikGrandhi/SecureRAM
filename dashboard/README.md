# SecureRAM Dashboard 0.7.0

An offline, local browser console for the existing SecureRAM 0.6.0 CLI and
driver. Python 3.10+ standard library, HTML, CSS and JavaScript only. No install,
package manager, CDN, font download, database or Internet connection is needed.

## Start in the Ubuntu VM

Build `make tools` as the ordinary checkout owner. Use a trusted checkout whose
code, CLI, static files and parent directories cannot be modified by an untrusted
user while it runs as root. After the separately authorized matching-kernel module
load, launch the backend explicitly:

```sh
sudo python3 -I dashboard/server.py
# Optional fixed port; the address remains 127.0.0.1:
sudo python3 -I dashboard/server.py --port 8765
```

`-I` enables Python isolated mode, excluding user site packages and Python
environment overrides. It is recommended for the privileged launch. The plain
`sudo python3 dashboard/server.py` invocation also works, but relies on the
administrator's Python environment. The server never invokes sudo itself.

The default port is ephemeral. Open the **exact URL printed by this process** in
the VM's ordinary desktop browser, not a browser launched as root. Example shape:

```text
SecureRAM Dashboard 0.7.0
Listening only on 127.0.0.1
Open: http://127.0.0.1:<port>/#token=<random-session-token>
```

The fragment token is removed immediately from the address bar and retained only
in page memory. A reload or new tab needs the original URL again. Do not save or
share that credential or redirect startup stdout into an evidence file. The
server never opens a browser. It can start with the module/CLI absent; API errors
explain the missing prerequisite. No demo values are substituted.

Ctrl+C (or SIGTERM) stops HTTP service and waits for bounded owned work. It does
not lock, destroy, unload or otherwise change SecureRAM. Key destruction remains
a separate explicit operation. Python reference removal is not secure erasure.

## Use

NO_KEY offers Load Random Key; ACTIVE offers Lock and Destroy; LOCKED offers
Unlock and Destroy. INTEGRITY_FAILED shows a prominent red warning and offers
only Destroy. Destroy requires typing `DESTROY` in a dialog; it discards the
key and all data. A fresh load creates an empty medium. All changes require
unmounted/closed block users. The CLI/kernel validates every request, including
stale, overlapping or hand-written HTTP requests. The dashboard has no key input,
export or recovery facility. Lock retains resident keys.

Status and statistics are polled sequentially, about once per second, only while
visible. Failed refreshes mark observations stale and disable controls. An action
failure or timeout can have an uncertain outcome; the UI refreshes state and never
automatically retries an action. Charts subtract exact integer counters before
computing sampled bytes/second and retain up to 60 points. Session activity keeps
the latest 40 events in browser memory. Neither is a benchmark or persistent log.

## Fixed API

Every API request requires `Authorization: Bearer <startup-token>`. Host must be
exactly `127.0.0.1:<actual-port>`. POST also requires the matching
`Origin: http://127.0.0.1:<actual-port>`, `Content-Type: application/json`, and a
single valid Content-Length of at most 128 bytes. No query-string tokens/cookies,
cross-origin access, chunked bodies or arbitrary commands are supported.

The response header and HTML metadata both select `Referrer-Policy: same-origin`.
This lets a standards-compliant browser serialize the exact local Origin on the
same-origin POST while still suppressing referrer information on cross-origin
requests. It does not relax authorization: missing, `null` and nonmatching POST
Origins remain rejected, as do a wrong Host/token or cross-site fetch metadata.
The fragment token is removed before requests and fragments are never included
in HTTP referrer values.

| Method and path | Body | Result |
| --- | --- | --- |
| `GET /api/status` | None | Validated CLI status and dashboard version/compatibility metadata. |
| `GET /api/stats` | None | Validated ABI and five module-lifetime counters. |
| `POST /api/actions/load-random` | `{}` | Existing CLI action. |
| `POST /api/actions/lock` | `{}` | Existing CLI action. |
| `POST /api/actions/unlock` | `{}` | Existing CLI action. |
| `POST /api/actions/destroy` | `{"confirm":"DESTROY"}` | Existing destructive CLI action. |

Actions return `{"ok":true,"action":"lock","refresh_required":true}` (with the
requested action). Read status afterward; success does not freeze the kernel
state against another administrator. Errors have
`{"error":{"code":"device_busy","message":"…","cli_exit":1}}`; `cli_exit` is
present only for CLI nonzero exits. CLI stdout/stderr are never passed through.

The HTTP status object preserves M6 fields, except `capacity_bytes` and
`generation` are decimal **strings**; all five HTTP statistics are decimal
**strings** too. This preserves U64_MAX in JavaScript without rounding.
`abi`, `state`, `unit_bytes`, and `features` remain JSON numbers. The browser uses
BigInt for exact display/deltas. Added status fields are `dashboard_version`,
`compatible`, `compatibility_message`. Unknown state/feature values remain visible
with controls disabled. Versions are reported from the CLI, never invented;
loaded driver version can be null. Missing features or ABI problems are explicit.

Unauthenticated static routes are only `/`, `/app.js`, `/styles.css`, with a fixed
startup-loaded asset allowlist. They contain no device data or token. No directory
listing, arbitrary path lookup, kernel logs, filesystem browsing or device reads
are exposed by HTTP. See [the design and review](../docs/m7-report.md) for resource
limits, security headers, exact error handling and trust assumptions.

## Verification and limits

Run `python3 tests/check-m7-local.py` from the repository root. The standalone
UI fixture `python3 tests/m7-preview.py` is **unprivileged test code**, visibly
labelled, with a mocked CLI and no device access. It is never enabled by the
production server. `--state 4` can preview an integrity failure for UI testing.

M7 does not change cryptography, ioctl values, state numbers, feature bits or
device permissions. Driver/CLI remain 0.6.0, ABI 1, production features 15.
This is not AEAD; there is no same-unit same-generation replay prevention,
whole-request atomic plaintext release, malicious root/kernel/hypervisor
protection, crash-persistent anti-replay or physical RAM-erasure guarantee.
The token protects the local HTTP interface, not OS privilege isolation. Do not
use port forwarding, reverse proxies, remote administration or LAN exposure.
Local denial of service and a compromised authorized browser/extension remain
outside this educational dashboard's protection.

Automated M7 VM acceptance first passed on commit `08d1ade`. A subsequent real
Firefox check found that the original `no-referrer` policy produced `Origin: null`
for lifecycle POSTs; GET status/stats still worked and the driver remained NO_KEY.
Final candidate `ff1b6df2444b134a3ee7005bc0a97b02a20b5fb5` changed only the policy
to `same-origin`, retained every backend validation, and passed both the complete
automated VM suite and the real Firefox regression re-test. The manual session
also passed load/lock/unlock/destroy, exact Destroy confirmation, responsive and
disconnect/reconnect behavior, real direct-I/O statistics refresh, and clean
unload. [The testing record](../docs/m7-testing.md) keeps the historical defect
separate from the final accepted evidence.
