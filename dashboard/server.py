#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Local, explicitly privileged adapter for the existing SecureRAM CLI.

No device access, state machine, key handling, shell or runtime mock mode here.
See docs/m7-report.md for the trust boundary and bounded resource policy.
"""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
from socketserver import ThreadingMixIn
import stat
import subprocess
import sys
import threading

VERSION = "0.7.0"
ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "dashboard/static"
CLI = ROOT / "tools/secureramctl"
ACTIONS = frozenset(("load-random", "lock", "unlock", "destroy"))
COUNTERS = ("read_requests", "write_requests", "read_bytes", "write_bytes",
            "integrity_failures")
NAMES = {0: "NO_KEY", 1: "PREPARING", 2: "ACTIVE", 3: "LOCKED", 4: "INTEGRITY_FAILED"}
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8")}
BODY_LIMIT = 128
CLI_TIMEOUT = 15
WORKERS = 8
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; "
                               "connect-src 'self'; img-src 'self'; base-uri 'none'; "
                               "form-action 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
}


class APIError(Exception):
    def __init__(self, status, code, message, cli_exit=None):
        super().__init__(code)
        self.status, self.code, self.message, self.cli_exit = status, code, message, cli_exit

    def payload(self):
        result = {"error": {"code": self.code, "message": self.message}}
        if self.cli_exit is not None:
            result["error"]["cli_exit"] = self.cli_exit
        return result


def invalid_json():
    return APIError(502, "malformed_cli_json", "CLI returned invalid JSON or an unexpected schema.")


def strict_json(raw):
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError("duplicate field")
            obj[key] = value
        return obj

    def constant(_):
        raise ValueError("non-finite number")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def validate_json(command, raw):
    """Validate M6 JSON before selecting fields; preserve u64s as decimal strings."""
    try:
        if len(raw) > 8192:
            raise ValueError("output too large")
        obj = strict_json(raw.decode("utf-8"))
        fields = ({"abi", *COUNTERS} if command == "stats" else
                  {"version", "cli_version", "abi", "state", "state_name", "capacity_bytes",
                   "unit_bytes", "generation", "features", "xts", "lock", "integrity", "stats"})
        if type(obj) is not dict or set(obj) != fields:
            raise ValueError("fields")

        def uint(key, bits):
            if type(obj[key]) is not int or not 0 <= obj[key] < 2**bits:
                raise ValueError("integer")

        uint("abi", 32)
        if obj["abi"] != 1:
            raise APIError(502, "abi_mismatch", "SecureRAM ABI 1 is required.")
        if command == "stats":
            for key in COUNTERS:
                uint(key, 64)
                obj[key] = str(obj[key])
            return obj
        for key in ("state", "features", "unit_bytes"):
            uint(key, 32)
        for key in ("capacity_bytes", "generation"):
            uint(key, 64)
        for key in ("version", "cli_version"):
            if key == "version" and obj[key] is None:
                continue
            if type(obj[key]) is not str or not re.fullmatch(r"[A-Za-z0-9._+\-]{1,63}", obj[key]):
                raise ValueError("version")
        if obj["state_name"] != NAMES.get(obj["state"], "UNKNOWN"):
            raise ValueError("state name")
        if not 1048576 <= obj["capacity_bytes"] <= 268435456 or obj["capacity_bytes"] % 1048576:
            raise ValueError("capacity")
        if obj["unit_bytes"] != 4096:
            raise APIError(502, "abi_mismatch", "Unsupported SecureRAM crypto unit size.")
        for key, bit in (("xts", 1), ("lock", 2), ("integrity", 4), ("stats", 8)):
            if type(obj[key]) is not bool or obj[key] != bool(obj["features"] & bit):
                raise ValueError("feature flag")
        # Preserve unknown bits/state for diagnosis without enabling GUI actions.
        obj["compatible"] = obj["features"] == 15 and obj["state"] in NAMES
        obj["compatibility_message"] = (None if obj["compatible"] else
                                        "Unsupported state or feature mask; M7 expects features 15.")
        obj["generation"] = str(obj["generation"])
        obj["capacity_bytes"] = str(obj["capacity_bytes"])
        obj["dashboard_version"] = VERSION
        return obj
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
        raise invalid_json() from error


def cli_error(result):
    """Classify fixed C-locale diagnostics; never forward raw stderr or stdout."""
    error = result.stderr[:8192].decode("utf-8", errors="replace")
    status, code, message = 502, "cli_failure", "CLI operation failed. Refresh status before retrying."
    if result.returncode == 3:
        code, message = "abi_mismatch", "CLI reports an unsupported ioctl, feature or incompatible ABI."
    elif "load the SecureRAM module first" in error:
        status, code, message = 503, "module_absent", "SecureRAM module is absent. Load it in the VM."
    elif "requires host CAP_SYS_ADMIN" in error:
        status, code, message = 503, "permission_denied", "Backend needs root access and host CAP_SYS_ADMIN."
    elif "Device or resource busy" in error:
        status, code, message = 409, "device_busy", "Device is open/mounted or the lifecycle transition is invalid."
    elif "no usable key" in error:
        status, code, message = 409, "no_key", "No usable key in the current state."
    elif "INTEGRITY_FAILED" in error:
        status, code, message = 409, "integrity_failed", "I/O failed. Check for an INTEGRITY_FAILED latch."
    elif "key loaded and wiped" in error or "operation completed" in error:
        code, message = "action_uncertain", "Action completed but CLI follow-up failed. Refresh before any retry."
    return APIError(status, code, message, result.returncode)


class Controller:
    def __init__(self):
        self.lock = threading.Lock()

    def call(self, command):
        if command not in ACTIONS | {"status", "stats"}:
            raise APIError(404, "unknown_action", "Unsupported operation.")
        # A busy response is preferable to an unbounded queue of privileged work.
        if not self.lock.acquire(timeout=0.2):
            raise APIError(503, "controller_busy", "Another CLI operation is running. Refresh shortly.")
        try:
            try:
                # No PATH search; refuse replaced/symlinked tools and directories.
                if CLI.resolve(strict=True) != CLI or not stat.S_ISREG(CLI.stat().st_mode):
                    raise APIError(503, "cli_unsafe", "Expected a regular repository CLI executable.")
                result = subprocess.run(
                    [str(CLI), command] + (["--json"] if command in ("status", "stats") else []),
                    shell=False, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE if command in ("status", "stats") else subprocess.DEVNULL,
                    stderr=subprocess.PIPE, timeout=CLI_TIMEOUT, check=False, cwd=str(ROOT),
                    env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}, close_fds=True)
            except FileNotFoundError as error:
                raise APIError(503, "cli_missing", "CLI missing. Build it with make tools.") from error
            except PermissionError as error:
                raise APIError(503, "permission_denied", "Cannot execute the repository CLI.") from error
            except subprocess.TimeoutExpired as error:
                raise APIError(504, "cli_timeout", "CLI timed out; action outcome may be unknown. Refresh before retrying.") from error
            except OSError as error:
                raise APIError(502, "cli_failure", "Could not execute the repository CLI.") from error
            if result.returncode != 0:
                raise cli_error(result)
            if command in ("status", "stats"):
                return validate_json(command, result.stdout)
            return {"ok": True, "action": command, "refresh_required": True}
        finally:
            self.lock.release()


def load_assets():
    """Read only three fixed regular files, once; never serve the filesystem."""
    assets = {}
    if STATIC.is_symlink() or STATIC.resolve(strict=True) != STATIC:
        raise ValueError("static root must not be symlinked")
    for route, (name, content_type) in ASSETS.items():
        path = STATIC / name
        if path.is_symlink() or path.resolve(strict=True).parent != STATIC:
            raise ValueError("asset must stay inside static root")
        # Linux O_NOFOLLOW closes the final-component check/open race. The whole
        # repository and its parent directories must still be administrator-trusted.
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("asset must be a regular file")
            content = stream.read(262145)
        if len(content) > 262144:
            raise ValueError("asset too large")
        assets[route] = (content, content_type)
    return assets


class DashboardServer(ThreadingMixIn, HTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False
    request_queue_size = WORKERS

    def __init__(self, port=0):
        self.token = secrets.token_urlsafe(32)
        self.controller = Controller()
        self.assets = load_assets()
        self.slots = threading.BoundedSemaphore(WORKERS)
        super().__init__(("127.0.0.1", port), Handler)
        self.host = f"127.0.0.1:{self.server_port}"
        self.origin = f"http://{self.host}"

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        print("dashboard: request handler failed", file=sys.stderr)

    def server_close(self):
        super().server_close()  # Wait for owned workers before dropping token.
        self.token = ""
        self.assets.clear()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # One request per connection, no pipelining.
    server_version = "SecureRAMDashboard/" + VERSION
    sys_version = ""

    def setup(self):
        self.request.settimeout(3)
        super().setup()
        self.body_consumed = False
        # Absolute header/body deadline also bounds slow-drip clients.
        self.read_deadline = threading.Timer(5, self.abort_read)
        self.read_deadline.daemon = True
        self.read_deadline.start()

    def abort_read(self):
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def finish(self):
        self.read_deadline.cancel()
        super().finish()

    def log_message(self, format, *args):
        pass  # Never log URLs, headers, tokens, request text or CLI output.

    def send_error(self, code, message=None, explain=None):
        # Even a malformed request line gets an HTTP status, never HTTP/0.9 output.
        self.request_version = "HTTP/1.0"
        self.reply(code, {"error": {"code": "http_error", "message": "HTTP request rejected."}})

    def reply(self, status, payload, content_type="application/json; charset=utf-8"):
        # Drain only a small, validly framed rejected body. This avoids a TCP reset
        # racing the JSON error on platforms that close with unread input. Hostile
        # slow/large/ambiguous bodies still get a bounded close, never a CLI call.
        if status >= 400 and not self.body_consumed and hasattr(self, "headers"):
            lengths = self.headers.get_all("Content-Length", [])
            if (len(lengths) == 1 and re.fullmatch(r"[0-9]{1,6}", lengths[0]) and
                    not self.headers.get_all("Transfer-Encoding") and not self.headers.get_all("Expect")):
                count = min(int(lengths[0]), BODY_LIMIT + 1)
                self.connection.settimeout(0.1)
                try:
                    self.rfile.read(count)
                except (OSError, TimeoutError):
                    pass
                self.connection.settimeout(3)
                self.body_consumed = True
        content = payload if isinstance(payload, bytes) else json.dumps(payload, allow_nan=False).encode("utf-8")
        self.send_response(status)
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(content)

    def single_header(self, name):
        values = self.headers.get_all(name, [])
        if len(values) > 1:
            raise APIError(400, "duplicate_header", "Duplicate security or framing header.")
        return values[0] if values else None

    def route(self, method):
        try:
            if self.single_header("Host") != self.server.host:
                raise APIError(403, "invalid_host", "Use the exact printed loopback address.")
            origin = self.single_header("Origin")
            if origin is not None and origin != self.server.origin:
                raise APIError(403, "cross_origin", "Cross-origin requests are forbidden.")
            site = self.single_header("Sec-Fetch-Site")
            if site is not None and site not in ("same-origin", "none"):
                raise APIError(403, "cross_origin", "Cross-site requests are forbidden.")
            # Fixed raw paths: no decoding, query, normalization, directory lookup or redirects.
            is_api = self.path in ("/api/status", "/api/stats") or self.path.startswith("/api/actions/")
            if self.path not in ASSETS and not is_api:
                raise APIError(404, "not_found", "Route not found.")
            if self.single_header("Transfer-Encoding") is not None or self.single_header("Expect") is not None:
                raise APIError(400, "invalid_framing", "Unsupported request framing.")
            length = self.single_header("Content-Length")
            if length is not None and not re.fullmatch(r"[0-9]{1,6}", length):
                raise APIError(400, "invalid_length", "Invalid Content-Length.")
            count = int(length or "0")
            if count > BODY_LIMIT:
                raise APIError(413, "body_too_large", "Request body exceeds 128 bytes.")
            if is_api:
                auth = self.single_header("Authorization") or ""
                expected = "Bearer " + self.server.token
                if not self.server.token or not secrets.compare_digest(auth.encode("utf-8"), expected.encode("ascii")):
                    raise APIError(401, "unauthorized", "Open the startup access URL to authorize this session.")
            if method == "GET":
                if count:
                    raise APIError(400, "unexpected_body", "GET must not have a body.")
                if self.path.startswith("/api/actions/"):
                    raise APIError(405, "method_not_allowed", "Lifecycle actions require POST.")
                self.read_deadline.cancel()
                if self.path in ASSETS:
                    self.reply(200, *self.server.assets[self.path])
                else:
                    self.reply(200, self.server.controller.call(self.path.rsplit("/", 1)[1]))
            elif method == "POST":
                action = self.path.removeprefix("/api/actions/")
                if not self.path.startswith("/api/actions/") or action not in ACTIONS:
                    raise APIError(404, "unknown_action", "Unsupported action.")
                # Required on POST, including non-browser clients; bearer is still mandatory.
                if origin != self.server.origin:
                    raise APIError(403, "origin_required", "Actions require the exact same Origin.")
                if self.single_header("Content-Type") != "application/json":
                    raise APIError(415, "content_type", "Use application/json.")
                if length is None:
                    raise APIError(411, "length_required", "Content-Length is required.")
                try:
                    raw = self.rfile.read(count)
                    self.body_consumed = True
                    if len(raw) != count:
                        raise ValueError("short body")
                    body = strict_json(raw.decode("utf-8"))
                except (ValueError, UnicodeError, RecursionError) as error:
                    raise APIError(400, "invalid_body", "Malformed JSON body.") from error
                wanted = {"confirm": "DESTROY"} if action == "destroy" else {}
                if type(body) is not dict or body != wanted:
                    raise APIError(400, "confirmation_required" if action == "destroy" else "invalid_body",
                                   'Destroy requires {"confirm":"DESTROY"}.' if action == "destroy" else "Action body must be {}.")
                self.read_deadline.cancel()
                self.reply(200, self.server.controller.call(action))
        except APIError as error:
            if error.status >= 500:
                print(f"dashboard: {error.code}", file=sys.stderr)
            self.reply(error.status, error.payload())
        except (TimeoutError, ConnectionError, OSError):
            self.close_connection = True
        except Exception:
            print("dashboard: internal_error", file=sys.stderr)
            self.reply(500, {"error": {"code": "internal_error", "message": "Internal request failure."}})

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")


def main():
    parser = argparse.ArgumentParser(description="SecureRAM local dashboard (explicit sudo launch on Linux).")
    parser.add_argument("--port", type=int, default=0, help="loopback port, 0 chooses an ephemeral port")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    if sys.platform != "linux" or os.geteuid() != 0:
        parser.error("launch explicitly as root in Linux: sudo python3 -I dashboard/server.py")
    try:
        server = DashboardServer(args.port)
    except (OSError, ValueError):
        print("dashboard: startup failed; verify the port and trusted static assets", file=sys.stderr)
        return 1

    def stop(_signum, _frame):
        # serve_forever is on this thread; shutdown() here would deadlock.
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    print(f"SecureRAM Dashboard {VERSION}\nListening only on 127.0.0.1\n"
          f"Open: {server.origin}/#token={server.token}", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("Dashboard stopped; SecureRAM state was not changed.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
