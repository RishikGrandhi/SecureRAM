# M7 — Dashboard and demo UI

## Baseline, design and status

Started from clean `main` at full commit
`02701a3fd75cb7bb1444d859e6b17d17833ad865` (M6 merge), inspected the CLI,
UAPI, block/control implementation, M6 design/testing, shared M5/M6 harnesses and
build conventions, presented the design before edits, then worked only on
`m7-dashboard`. M1–M6 remain complete and runtime verified as recorded in their
reports. Automated M7 Ubuntu VM acceptance subsequently passed on exact commit
`08d1ade75215dc237342569f9c9c3dc2fd2957a3`. A later manual real-Firefox check
loaded the UI and read status/stats, but lifecycle POSTs failed because Firefox
sent `Origin: null` under the original `no-referrer` policy. The minimal policy
fix below is locally verified in the current patch; real Firefox re-verification is
still pending. No push or merge is part of this handoff.

Dashboard version is **0.7.0**. Kernel and CLI remain **0.6.0**, ABI **1**, production
features **15**. No file in `src/`, `include/` or `tools/`, no ioctl/state/feature
number and no build rule is changed. No new privilege or kernel capability is
needed. This milestone adds usability and observation only.

On resuming after the interrupted implementation, `git status --short --branch`,
`git diff --stat` and `git diff --check` were read before editing. The valid
backend/static UI, local tests, HTTP client/VM harness, dashboard guide and this
report draft already existed; saved M7 local and complete M6 regression logs
were PASS. No partial implementation was discarded. The remaining work completed
on resumption was the M7 testing procedure, root/architecture/development/test
guide integration, failed-state/mobile/reconnect browser checks, final review and
rerun evidence. Browser testing found and fixed same-tab fragment reauthorization;
cleanup review added bounded backend cleanup even when startup has not revealed
the port. That implementation became candidate commit `08d1ade` before its
automated VM acceptance.

## Architecture and ownership

```text
ordinary browser (HTML/CSS/JS; memory-only token, activity, samples)
  -> IPv4 loopback HTTP / exact Host / bearer token / same-origin policy
  -> bounded Python stdlib server, one serialized CLI invocation
  -> absolute repository tools/secureramctl, explicit argv, shell=False
  -> root:root 0600 /dev/secureramctl + host CAP_SYS_ADMIN on every ioctl
  -> unchanged SecureRAM control, statistics and security layers

application/filesystem -> Linux block layer -> blk-mq -> existing worker
  -> existing AES-XTS/HMAC security -> checked ciphertext/tag RAM store
```

The data path never traverses the dashboard. Python owns only the loopback
socket, fixed asset bytes, session token, bounded worker slots and CLI mutex.
The C CLI owns its existing protected random-key buffer; the kernel retains its
existing device/crypto ownership. There is no crypto, key input/output, ioctl
packing or duplicated lifecycle state machine in the server. Browser button
availability is only a convenience; the kernel remains authoritative.

The implementation uses Python 3.10+ standard library and three offline static
files. HTTPServer is the transport parser, with a purpose-built handler rather
than SimpleHTTPRequestHandler/CGI. This is a constrained local demo service, not
a general-purpose production HTTP server or remote administration platform.
The Python documentation's [HTTP server security considerations](https://docs.python.org/3.12/library/http.server.html#security-considerations)
motivate the explicit filesystem, logging and resource restrictions here.

## Privileged HTTP boundary

| Area | Implementation and practical limit |
| --- | --- |
| Explicit launch | Administrator runs `sudo python3 -I dashboard/server.py`. No embedded sudo, setuid, chmod or browser launch. Linux/root entrypoint gate; capability/device checks still occur in the CLI/kernel. `-I` excludes Python environment/user-site overrides. |
| Trusted code | The administrator must trust the checkout, interpreter, executable and parent directories. No root-ownership change is made to the student's checkout. A repository writer can change code that an administrator elects to execute; this design does not sandbox malicious local code. |
| Network | Bind is a literal `127.0.0.1`; no host argument or IPv6/LAN listener. Default port 0 asks the OS for a free ephemeral port; `--port` accepts only 0..65535. No port-forward/proxy support. |
| Token | `secrets.token_urlsafe(32)` per start. Only intentional startup stdout includes it. URL **fragment**, not query, removes it from HTTP request targets; JS calls history.replaceState and stores it only in memory. No cookie/localStorage/sessionStorage/file. Startup URLs remain credentials and may still be visible to trusted browser/OS tooling; reference removal is not memory erasure. |
| Authorization | Every API route requires a nonempty exact bearer value, compared with compare_digest; duplicate Authorization headers fail. Wrong/empty/missing/query tokens fail. Static assets reveal no token or device metadata. |
| Rebinding/cross-site | Exactly one Host, equal to `127.0.0.1:port`. Present Origin must match; POST requires it. Sec-Fetch-Site, when present, must be same-origin or none; same-site is rejected too. A raw client can forge Origin but still needs the token. No CORS grants or preflight support. See [fetch-metadata semantics](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Sec-Fetch-Site). |
| Methods/body | Lifecycle POST only, four literal actions. JSON content type, valid single Content-Length, 128-byte cap; no Transfer-Encoding or Expect. Duplicate fields, non-finite constants, invalid UTF-8, unknown fields, wrong types and missing typed Destroy confirmation are rejected. GET never calls an action. |
| Headers | CSP permits only own scripts/styles/connects/images; no inline code, base, forms, embedding or other resources. nosniff, `same-origin` referrer policy, frame denial, same-origin resource policy, disabled camera/microphone/geolocation, no-store. The same policy is present in HTML metadata. |
| Static files | Three exact raw routes. No percent-decoding, normalization, dynamic filename join, directory browsing or redirection. Startup verifies root containment and regular files, rejects symlink roots/files, reads at most 256 KiB each and preloads bytes. O_NOFOLLOW closes Linux final-component symlink races; O_NONBLOCK prevents a replaced FIFO blocking open. Trusted parent directories remain an assumption. |
| CLI | Fixed absolute repository executable; reject symlinked/nonregular path, no PATH lookup. Explicit argv and `shell=False`; no browser strings become arguments except a member of the hardcoded action set. Empty stdin, close_fds, minimal C-locale environment (no inherited LD/Python/shell settings). Action stdout discarded. No filesystem/environment/kernel-log endpoints. |
| Errors/logging | Small fixed JSON messages and CLI exit codes; never raw stderr, output, exception strings or traceback. C-locale diagnostics are classified into module absent, permission, ABI, busy/invalid transition, no key, integrity, uncertain action and generic failure. Request logging is disabled, including parser errors. Stderr logs fixed diagnostic codes only. |

Frontend code uses textContent and DOM nodes, not HTML interpolation. The token
cannot protect a compromised same-origin page, malicious browser extension,
privileged local observer, or user who receives the startup URL. Do not share it.
There is no multi-user authorization, TLS or Internet/LAN exposure. Loopback and
token authentication complement, and never replace, OS privilege isolation.

## Bounded concurrency and failure behavior

Eight worker slots and an eight-connection listen backlog bound HTTP work.
Excess accepted connections close without starting a worker. HTTP/1.0 closes
each connection after one request. Socket I/O has a three-second idle timeout;
a separate five-second absolute header/body deadline closes slow-drip clients.
Bodies are capped at 128 bytes. For rejected requests, at most 129 bytes of a
validly framed body are drained for at most 0.1 seconds to avoid a TCP reset
racing an error response. Framing errors/large bodies still get a bounded close.

One mutex serializes all CLI queries and actions. Waiters get `controller_busy`
503 after 0.2 seconds instead of accumulating work. Each subprocess has a
15-second timeout; Python terminates/reaps a normal hung child before releasing
the slot. A kernel task stuck in uninterruptible sleep cannot be forcibly made
healthy by an HTTP server; kernel health and VM supervision remain necessary.
CLI output is from a trusted, fixed small-output executable; the 8 KiB JSON
validation limit is not a sandbox for a malicious replacement executable.

Ordinary polling uses only two sequential CLI calls per completed refresh,
then waits about one second; hidden pages pause. No parallel polling loops or
unbounded action retries exist. The page cancels the polling timer during an
action, waits for any ongoing refresh, then makes one POST and re-queries.
Another administrator may still change state between any observations; server
serialization is neither a kernel lock nor a transaction across status/stats.

HTTP failure categories: 401 unauthorized; 403 Host/Origin/fetch policy; 404
unknown route/action; 405 GET action; 400 malformed body/framing/confirmation;
411 missing POST length; 413 oversized body; 415 wrong content type; 409 CLI
busy/invalid transition, no key or integrity I/O failure; 502 CLI/ABI/JSON error;
503 missing CLI/module, privilege or controller contention; 504 CLI timeout.
Unsupported methods return 501 with JSON. No CLI nonzero result becomes HTTP
success. EBUSY deliberately preserves its two M6 meanings instead of guessing
whether the cause is a mount or a raced invalid transition.

An ioctl may have changed state before CLI follow-up, output or timeout failure.
Neither backend nor UI retries actions automatically. The outcome is explicitly
uncertain, and fresh status is required before deciding what to do next.
Backend loss leaves visible last-observed values with a stale warning and disables
controls. A returned INTEGRITY_FAILED observation is displayed immediately even
if the subsequent stats request fails. Closing the browser/backend changes no
driver state. SIGINT/SIGTERM stop acceptance, wait for owned workers and drop
token references; no destroy call is added to any server teardown path.

## API, exact numbers and interface

The [dashboard guide](../dashboard/README.md#fixed-api) is the exact six-route
contract. Status/stats execute only the existing `status --json` and
`stats --json`. Parsing rejects duplicates, invalid UTF-8, non-finite values,
unexpected fields and bool-as-int mistakes; checks u32/u64 bounds, versions,
capacity/unit geometry, state-name agreement and boolean/mask consistency.
ABI incompatibility fails; unknown states/feature bits remain visible with
`compatible=false`. Device/CLI versions come from M6 output, including a null
module version. Security labels appear only for advertised capabilities.

HTTP converts capacity, generation and counters to decimal strings so JavaScript
can use BigInt. Small u32 fields remain numbers. M6's CLI JSON contract itself is
unchanged. All five counters display exact values; byte counters also show IEC
units. Sampled read/write bytes per second subtract BigInts before floating-point
rate conversion. Missing observations, decreasing counters/generation, hidden
tabs and gaps longer than five seconds reset the chart. An unobserved reload
whose counters already exceed the previous values is inherently indistinguishable
without a module-instance ID; charts are diagnostic and never security-critical.

The responsive layout has a dark state card, separate lifecycle controls, five
counter cards, read/write activity graph, confidentiality/integrity layers,
device metadata and bounded session history. NO_KEY is neutral, ACTIVE green,
LOCKED amber, INTEGRITY_FAILED red with an additional full-width warning. The
typed Destroy dialog explains unrecoverable data loss. Enabled states are:

| Observed state | Available controls when fresh/compatible/idle |
| --- | --- |
| NO_KEY (0) | Load Random Key. |
| PREPARING (1) | None. |
| ACTIVE (2) | Lock, Destroy. |
| LOCKED (3) | Unlock, Destroy. |
| INTEGRITY_FAILED (4) | Destroy only, then fresh load from NO_KEY. |
| Unknown, stale, unavailable or incompatible | None. |

The API still passes allowed actions to the CLI/kernel instead of inventing state.
Typed confirmation is an intentional UI/API contract, not a new authorization
boundary against a token holder who can construct the confirmation object.

## Harness reuse and defect audit

M7 reuses the actual M6 production, tamper, capacity and final functions, with
small override functions that route lifecycle actions through HTTP, add HTTP
observations and retain independent real CLI checks. M6 gained one default
integrity-runner function; its default behavior remains unchanged. Shared M5
code gained only profile 7 (0.6.0/15, m7-vm evidence); shared health reporting
applies M6's warning policy to M7. No large test suite was copied.

A Python session owner captures backend startup stdout **in memory**, checks
its /proc listening socket, and gives only test children a memory-only environment
credential. Backend stderr is a separate fixed-diagnostic log. One backend
survives all expected module unload/reload cycles. All original M5 ciphertext,
tag, relocation, passed-fd, failed-buffer and full-zero-scan assertions remain;
M7 adds rapid rejected failed-state actions and destroy/fresh-load recovery via
HTTP. No arbitrary device argument is introduced. The actual suite later passed
on `08d1ade`; successful mocks alone still verify orchestration/assertions, not
kernel behavior.

| Previous defect/risk | M7 treatment and local exercise |
| --- | --- |
| SHA mismatch | Required 40-character lower-case M7 pin; shared full HEAD comparison and exact m7-dashboard branch/clean checkout guard. Empty/short/malformed pins rejected in mocks. |
| SUDO_USER and .cache | Existing builder-owned evidence preparation, ordinary-user builds and final ownership release retained. M7 evidence is .cache/m7-vm; no token files. The accepted `08d1ade` VM run exercised the real sudo/runuser path. |
| Nounset / dynamic scope | Shared initialized ownership/cleanup variables retained. New locals do not collide with readonly capacity names; actual functions run under set -Eeuo pipefail in mocks. |
| Redirections / shell parsing | Shared actual ext4 redirections/comparisons/remount flow executed with temporary files; separate bash -n for every shell file. No eval, bash -c, sh -c or generated shell command string. |
| False PASS / missing logs | NOT RUN ledger initialization, explicit assertion groups, failure-preserving phase EXIT traps and shared finalization. Missing/no-runtime dmesg is NOT RUN; lost collection/warnings FAIL. Synthetic failure, aborted session and final ownership failure must not yield OVERALL PASS. |
| Cleanup/device identity | Literal /dev/secureram0 in inherited raw/format commands; guards before destructive work; only owned/revalidated mounts/modules cleaned. Unsafe-unmount refusal retained. Session-owner mocks test startup failure, phase failure, clean stop and forced-stop failure. |
| Production regression | Final clean production build, symbols/strings/ENOTTY, CLI/raw/ext4 checks retained, then node/sysfs/module disappearance and fresh log review. |

## Second adversarial review

The final pass examined all 20 requested areas: privileged attack surface,
loopback/Host/token/Origin/CORS, static and symlink traversal, injection/argv,
timeouts/allowlists/JSON, concurrency, logs and response leakage, shutdown,
M5/M6 preservation, kernel/UAPI diff, version/feature assumptions, harness
orchestration and ignored artifacts. Concrete fixes included malformed request
line status responses, bounded rejection-body draining for reliable errors,
Linux O_NOFOLLOW/nonblocking static opens, and explicit process-owner cleanup
failure tests. Resumed browser testing additionally found that opening the startup
URL in an already loaded tab caused only a fragment navigation; a token fragment
now reloads the document to consume the credential and start a fresh observation
session. Old tokens were observed rejected after restart. The harness now applies
the normal bounded stop/kill-and-fail path even if startup fails before its port
is parsed, and closes its startup pipe on every cleanup outcome. Remaining
practical limits are stated above, not upgraded into
security guarantees.

## Post-acceptance Firefox integration defect

The full automated M7 VM suite passed on `08d1ade`. Its HTTP client intentionally
sent the exact expected Origin itself, so it verified backend enforcement but did
not reproduce a browser's Origin-header generation. The later Ubuntu desktop
Firefox check used the printed `http://127.0.0.1:<port>/#token=...` URL against
the real 0.6.0 driver in NO_KEY at 64 MiB, ABI 1 and features 15. Static UI,
`GET /api/status` and `GET /api/stats` worked. Clicking Load Random Key failed
with the dashboard message “Cross-origin requests are forbidden”; DevTools showed
`Origin: null` and `Sec-Fetch-Site: same-origin`. Direct CLI status remained
NO_KEY, generation 0, proving the rejected request did not change driver state.

This behavior follows the Fetch Standard's algorithm to
[append a request Origin header](https://fetch.spec.whatwg.org/#append-a-request-origin-header):
for a non-CORS, non-GET/HEAD request, `no-referrer` sets the serialized Origin to
`null`; `same-origin` leaves it intact when request origin and target match, and
sets it to `null` when they do not. The page supplied `no-referrer` through both
the HTTP header and HTML metadata. Both now use `same-origin`.

The fix changes only outgoing-browser policy. It does not accept `Origin: null`
or change server routing. POST still requires the exact `http://127.0.0.1:port`
Origin; missing/null/cross-origin values fail. Exact Host, bearer token,
Sec-Fetch-Site, no-CORS and loopback-only checks remain. Cross-origin referrer
information stays suppressed, and the startup token remains a URL fragment that
is removed with `history.replaceState`; fragments are stripped from referrers.
Regression tests assert the response/header metadata contract, exact-origin POST
success and rejection of null/cross-origin/missing Origin, wrong Host/token and
cross-site fetch metadata. Python clients cannot reproduce Firefox's header
generation, so the real Firefox re-test remains explicitly pending.

## Observed local evidence — 12 October 2026

| Check | Result |
| --- | --- |
| Python syntax / static HTML/CSS/JS integrity | PASS on Windows Python 3.13 and WSL Python 3.14; all asset references/IDs and offline/CSP constraints checked. |
| Backend/HTTP tests | Original candidate PASS: 23 tests. After the policy patch, all 24 pass in WSL; Windows passes 22 with the two Linux/symlink checks skipped. The added regression binds `same-origin` response/HTML policy to exact-origin POST success while retaining null/cross-origin/Host/token/fetch-metadata rejection. |
| JavaScript | PASS with the existing Node runtime: syntax plus BigInt/u64 maximum, state availability, reset/gap handling and delta-rate assertions. |
| M7 mocked VM harness | PASS: real M7-overridden phase functions; all capacities, ext4/busy/remount, early abort/cleanup/refusal/ledger guards; five Python HTTP/integrity/session tests reject bad fixtures and exercise clean, aborted and forced-stop paths, including an unknown startup port. |
| Existing M6 compile/static regressions | PASS for the complete runner: production, M5-only and combined W=1 builds, strict real CLI/syscall fixture, four ABI object builds, checkpatch, symbol/import/test-exclusion checks. Retain compiler/pahole/BTF environmental warnings, detailed in m7-testing.md. |
| Shell syntax | Separate bash -n for all 16 shell files. ShellCheck NOT RUN: not installed; no package installed. |
| Browser rendering | Observed in the Codex browser with a visibly labelled unprivileged fixture: NO_KEY, load/ACTIVE, lock/LOCKED, unlock, exact typed Destroy, return to NO_KEY, 1440-pixel desktop and 390-pixel narrow layouts, counter/chart refresh and visible disconnection/staleness. Failed-state warning/Destroy-only behavior and destroy/fresh-load recovery were observed; reload requires authorization, same-tab startup URL restores it and an old token fails after restart. This is synthetic browser evidence, not Ubuntu/device runtime acceptance. |
| Patched-policy browser smoke | PASS in the Codex in-app browser: emitted meta policy was `same-origin`, Load Random Key reached ACTIVE, no console warning/error appeared, then Destroy returned the fixture to NO_KEY. This is not Firefox and does not close the real-browser re-test. |
| M7 Ubuntu VM | PASS on committed candidate `08d1ade`; the current policy patch has not been rerun in the VM. |
| Manual Ubuntu Firefox | PARTIAL/DEFECT OBSERVED on `08d1ade`: layout and GET observation worked; lifecycle POST failed with `Origin: null`. Post-fix Firefox re-test NOT RUN. |

The source and procedure preserve every M5/M6 limit: **not AEAD**, no same-unit
same-generation replay prevention, no whole-request atomic plaintext-release
guarantee, no malicious root/kernel/hypervisor protection, no crash-persistent
anti-replay and no physical RAM-erasure guarantee. M7 strengthens none of those.

## File inventory and handoff

| Files | Change |
| --- | --- |
| `dashboard/server.py` | New privileged local CLI adapter, parser, resource bounds and security boundary. |
| `dashboard/static/index.html`, `styles.css`, `app.js` | New offline responsive UI and memory-only observer/session behavior. |
| `dashboard/README.md` | New launch, API and trust-boundary guide. |
| `tests/check-m7-dashboard.py`, `check-m7-local.py`, `check-m7-ui.js` | New local HTTP/static/JS checks. |
| `tests/check-m7-vm-harness.sh`, `m7-harness-mocks.sh`, `check-m7-observe.py` | New phase, observation and process-owner self-tests. |
| `tests/run-m7-vm-acceptance.sh`, `m7-vm-session.py`, `m7-vm-phases.sh` | New opt-in M7 VM orchestration and server owner. |
| `tests/m7-http.py`, `m7-integrity.py`, `m7-preview.py` | New fixed HTTP assertion client, reused tamper adapter and isolated browser fixture. |
| `tests/m5-vm-common.sh`, `m6-vm-phases.sh`, `vm-report.sh`, `check-m6-vm-harness.sh` | Small shared profile/override/health/mock reuse changes; historical defaults retained. |
| `README.md`, `docs/architecture.md`, `docs/development.md`, `tests/README.md` | Current M7 navigation, control path, verification and viva integration. |
| `docs/m7-report.md`, `docs/m7-testing.md` | Design/review/evidence, accepted automated VM result, browser defect and pending post-fix manual procedure. |

The post-acceptance patch audit checks whitespace, local Markdown targets,
ignored generated artifacts, unchanged kernel/UAPI/CLI/build paths and the empty
index. No staging, commit, push, merge, VM execution or next-milestone work is
included. Review this patch, then repeat the exact real Firefox sequence in
[m7-testing.md](m7-testing.md).

## Viva points

Explain why a browser needs a privileged local adapter while the device remains
0600; why localhost alone is not authorization; what Host, bearer, Origin and CSP
each defend; why the fragment avoids HTTP URL logging; why allowed argv without
a shell closes injection paths; and why root-trusted code/browser compromise
remain outside the token boundary. Trace resource ownership from accepted socket
through worker slot, CLI lock, child timeout and response/cleanup.

Explain that GUI state is an observation, button disabling is not access control,
separate query/statistics are not a transaction, and timeout is not rollback.
Distinguish 64-bit counters from JavaScript Number, exact deltas from cumulative
totals, browser charts from benchmarks, and mocks/rendering from kernel acceptance.
Finally, show why INTEGRITY_FAILED only recovers through destructive key removal
and fresh load, and why dashboard shutdown does not imply destruction.
