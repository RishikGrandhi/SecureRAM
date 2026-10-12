#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Real loopback HTTP with a mocked CLI boundary; never opens a device."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stderr
import copy
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dashboard_server", ROOT / "dashboard/server.py")
SERVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SERVER)
STATUS = dict(version="0.6.0", cli_version="0.6.0", abi=1, state=0, state_name="NO_KEY",
              capacity_bytes=67108864, unit_bytes=4096, generation=0, features=15,
              xts=True, lock=True, integrity=True, stats=True)
STATS = dict(abi=1, **dict.fromkeys(SERVER.COUNTERS, 0))


class FakeCLI:
    """Only a test fixture. All production requests still execute Controller.call."""
    def __init__(self):
        self.calls = []
        self.state = 0
        self.generation = 0
        self.active = self.maximum = 0
        self.delay = 0
        self.guard = threading.Lock()

    def run(self, argv, **kwargs):
        assert kwargs["shell"] is False
        assert argv[0] == str(SERVER.CLI)
        assert kwargs["timeout"] == SERVER.CLI_TIMEOUT
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
        assert kwargs["stdin"] == subprocess.DEVNULL and kwargs["close_fds"] is True
        command = argv[1]
        assert command in SERVER.ACTIONS | {"status", "stats"}
        assert argv[2:] == (["--json"] if command in ("status", "stats") else [])
        with self.guard:
            self.calls.append(argv)
            self.active += 1
            self.maximum = max(self.maximum, self.active)
        try:
            time.sleep(self.delay)
            if command in SERVER.ACTIONS:
                assert kwargs["stdout"] == subprocess.DEVNULL
                if ((command == "load-random" and self.state != 0) or
                        (command == "lock" and self.state != 2) or
                        (command == "unlock" and self.state != 3)):
                    return subprocess.CompletedProcess(argv, 1, None, b"Device or resource busy")
                if command == "load-random":
                    self.generation += 1
                self.state = {"load-random": 2, "lock": 3, "unlock": 2, "destroy": 0}[command]
                return subprocess.CompletedProcess(argv, 0, None, b"")
            data = dict(STATS) if command == "stats" else dict(
                STATUS, state=self.state, state_name=SERVER.NAMES[self.state], generation=self.generation)
            return subprocess.CompletedProcess(argv, 0, json.dumps(data).encode(), b"")
        finally:
            with self.guard:
                self.active -= 1


@contextmanager
def running_server():
    server = SERVER.DashboardServer()
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        assert not thread.is_alive()
        assert server.token == ""


def request(server, path="/api/status", method="GET", body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=20)
    values = {"Authorization": "Bearer " + server.token, "Origin": server.origin}
    values.update(headers or {})
    if method == "POST":
        values.setdefault("Content-Type", "application/json")
        body = "{}" if body is None else body
    try:
        conn.request(method, path, body=body, headers=values)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeCLI()
        # Executable checks use a real regular file, never a production fixture switch.
        self.patches = [patch.object(SERVER, "CLI", Path(__file__).resolve()),
                        patch.object(SERVER.subprocess, "run", self.fake.run)]
        for item in self.patches:
            item.start()
        self.context = running_server()
        self.server = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)
        for item in reversed(self.patches):
            item.stop()

    def test_loopback_token_and_static_headers(self):
        self.assertEqual(self.server.socket.getsockname()[0], "127.0.0.1")
        self.assertRegex(self.server.token, r"^[A-Za-z0-9_-]{43}$")
        for path, (name, content_type) in SERVER.ASSETS.items():
            status, headers, raw = request(self.server, path)
            self.assertEqual(status, 200)
            self.assertEqual(raw, (SERVER.STATIC / name).read_bytes())
            self.assertEqual(headers["Content-Type"], content_type)
            for key, value in SERVER.SECURITY_HEADERS.items():
                self.assertEqual(headers[key], value)
            self.assertNotIn("Access-Control-Allow-Origin", headers)
            self.assertNotIn(self.server.token.encode(), raw)
        self.assertEqual(self.fake.calls, [])

    def test_referrer_policy_preserves_exact_post_origin(self):
        status, headers, page = request(self.server, "/")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Referrer-Policy"], "same-origin")
        self.assertIn(b'<meta name="referrer" content="same-origin">', page)
        self.assertNotIn(b'content="no-referrer"', page)

        # Fetch specifies that same-origin preserves the serialized Origin for
        # this POST, while no-referrer serializes it as null. Only the exact
        # browser contract may reach the mocked lifecycle command.
        self.assertEqual(request(self.server, "/api/actions/load-random", "POST",
                                 headers={"Sec-Fetch-Site": "same-origin"})[0], 200)
        rejected = (
            ({"Origin": "null"}, 403),
            ({"Origin": "http://evil.test"}, 403),
            ({"Host": "evil.test"}, 403),
            ({"Authorization": ""}, 401),
            ({"Authorization": "Bearer wrong"}, 401),
            ({"Sec-Fetch-Site": "cross-site"}, 403),
        )
        for request_headers, wanted in rejected:
            with self.subTest(headers=request_headers):
                self.assertEqual(request(self.server, "/api/actions/load-random", "POST",
                                         headers=request_headers)[0], wanted)
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request("POST", "/api/actions/load-random", "{}", headers={
            "Authorization": "Bearer " + self.server.token,
            "Content-Type": "application/json",
        })
        self.assertEqual(conn.getresponse().status, 403)
        conn.close()
        self.assertEqual([call[1] for call in self.fake.calls], ["load-random"])

    def test_auth_missing_wrong_empty_and_query_substitution(self):
        for path, method in (("/api/status", "GET"), ("/api/stats", "GET"),
                             ("/api/actions/load-random", "POST")):
            for auth in ("", "Bearer ", "Bearer wrong", "Basic abc", "Bearer " + self.server.token + " "):
                self.assertEqual(request(self.server, path, method, headers={"Authorization": auth})[0], 401)
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request("GET", "/api/status")  # Truly absent header.
        self.assertEqual(conn.getresponse().status, 401)
        conn.close()
        self.assertEqual(request(self.server, "/api/status?token=" + self.server.token)[0], 404)
        self.assertEqual(self.fake.calls, [])

    def test_host_origin_and_fetch_metadata(self):
        for host in ("localhost", "localhost:" + str(self.server.server_port), "evil.test", "127.0.0.1", "127.0.0.1:1", ""):
            self.assertEqual(request(self.server, headers={"Host": host})[0], 403)
        for origin in ("null", "http://evil.test", "http://localhost:" + str(self.server.server_port), ""):
            self.assertEqual(request(self.server, headers={"Origin": origin})[0], 403)
        for site in ("cross-site", "same-site", "bad"):
            self.assertEqual(request(self.server, headers={"Sec-Fetch-Site": site})[0], 403)
        for site in ("same-origin", "none"):
            self.assertEqual(request(self.server, headers={"Sec-Fetch-Site": site})[0], 200)

    def test_post_requires_origin(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request("POST", "/api/actions/load-random", "{}", headers={
            "Authorization": "Bearer " + self.server.token, "Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().status, 403)
        conn.close()
        self.assertEqual(self.fake.calls, [])

    def test_read_routes_and_lossless_json(self):
        for command in ("status", "stats"):
            status, _, raw = request(self.server, "/api/" + command)
            self.assertEqual(status, 200)
            data = json.loads(raw)
            self.assertEqual(type(data["abi"]), int)
            self.assertNotIn(self.server.token.encode(), raw)
        self.assertEqual(json.loads(request(self.server)[2])["generation"], "0")

    def test_get_cannot_change_state_and_unknown_actions(self):
        for action in SERVER.ACTIONS:
            self.assertEqual(request(self.server, "/api/actions/" + action)[0], 405)
        for action in ("", "load", "status", "tamper", "run-command", "lock;id", "$(id)", "lock%3Bid", "../destroy", "destroy?x=1"):
            with self.subTest(action=action):
                self.assertEqual(request(self.server, "/api/actions/" + action, "POST")[0], 404)
        for method in ("PUT", "DELETE", "HEAD", "OPTIONS", "PATCH", "TRACE"):
            self.assertEqual(request(self.server, "/api/actions/destroy", method)[0], 501)
        self.assertEqual(self.fake.calls, [])

    def test_actions_destroy_confirmation_and_failure_latch(self):
        for action in ("load-random", "lock", "unlock"):
            status, _, body = request(self.server, "/api/actions/" + action, "POST")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), {"ok": True, "action": action, "refresh_required": True})
        for body in ('{}', '{"confirm":true}', '{"confirm":"destroy"}', '{"confirm":"DESTROY","extra":1}'):
            self.assertEqual(request(self.server, "/api/actions/destroy", "POST", body)[0], 400)
        self.fake.state = 4
        for action in ("unlock", "lock", "load-random"):
            self.assertEqual(request(self.server, "/api/actions/" + action, "POST")[0], 409)
            self.assertEqual(self.fake.state, 4)
        self.assertEqual(request(self.server, "/api/actions/destroy", "POST", '{"confirm":"DESTROY"}')[0], 200)
        self.assertEqual(self.fake.state, 0)
        self.assertEqual(request(self.server, "/api/actions/load-random", "POST")[0], 200)
        self.assertEqual(self.fake.state, 2)

    def test_malformed_size_type_and_schema(self):
        for body in ("", "{", "[]", "null", "true", '"test"', '{"x":1}', '{"x":NaN}', '{"x":1,"x":2}', '\ud800'):
            if body == '\ud800':
                body = b'"\xff"'
            self.assertEqual(request(self.server, "/api/actions/lock", "POST", body)[0], 400)
        self.assertEqual(request(self.server, "/api/actions/lock", "POST", "x" * 129)[0], 413)
        for ctype in ("text/plain", "application/x-www-form-urlencoded", "", "application/json; charset=utf-8"):
            self.assertEqual(request(self.server, "/api/actions/lock", "POST", headers={"Content-Type": ctype})[0], 415)
        self.assertEqual(request(self.server, body="{}")[0], 400)
        self.assertEqual(self.fake.calls, [])

    def test_traversal_fixed_asset_allowlist(self):
        for path in ("/../README.md", "/../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd",
                     "/%252e%252e/etc/passwd", "/static/../server.py", "/static/", "/server.py",
                     "/dev/secureramctl", "/dev/secureram0", "/.git/config", "/styles.css/..",
                     "/%2fetc%2fpasswd", "/..\\README.md", "/styles.css?x=1", "/index.html"):
            status, _, raw = request(self.server, path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"root:", raw)
            self.assertNotIn(str(ROOT).encode(), raw)
        self.assertEqual(self.fake.calls, [])

    def test_raw_duplicate_framing_and_bad_request(self):
        port = self.server.server_port
        def raw_request(data):
            with socket.create_connection(("127.0.0.1", port), timeout=4) as conn:
                conn.sendall(data.encode())
                conn.shutdown(socket.SHUT_WR)
                return conn.recv(8192)
        prefix = f"POST /api/actions/lock HTTP/1.1\r\nHost: {self.server.host}\r\n"
        headers = f"Authorization: Bearer {self.server.token}\r\nOrigin: {self.server.origin}\r\nContent-Type: application/json\r\n"
        for extra in ("Host: evil.test\r\n", "Content-Length: 2\r\nContent-Length: 2\r\n",
                      "Transfer-Encoding: chunked\r\n", "Expect: 100-continue\r\n", "Content-Length: -1\r\n",
                      "Content-Length: 2x\r\n", "Authorization: Bearer wrong\r\n", "Origin: null\r\n"):
            self.assertIn(b" 400 ", raw_request(prefix + headers + extra + "\r\n{}"))
        self.assertIn(b" 411 ", raw_request(prefix + headers + "\r\n"))
        self.assertIn(b" 400 ", raw_request(prefix + headers + "Content-Length: 8\r\n\r\n{}"))
        self.assertIn(b" 400 ", raw_request("BAD REQUEST LINE EXTRA\r\n\r\n"))
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(request(self.server)[0], 200)

    def test_errors_are_sanitized_and_non_success(self):
        cases = [(FileNotFoundError("private path"), 503, "cli_missing"),
                 (PermissionError("private path"), 503, "permission_denied"),
                 (subprocess.TimeoutExpired("private", 15, output=b"secret"), 504, "cli_timeout")]
        for error, expected, code in cases:
            with patch.object(SERVER.subprocess, "run", side_effect=error):
                status, _, body = request(self.server)
                self.assertEqual(status, expected)
                self.assertEqual(json.loads(body)["error"]["code"], code)
                self.assertNotIn(b"private", body)
                self.assertNotIn(b"secret", body)
        failures = [(3, b"ABI secret", "abi_mismatch"), (1, b"load the SecureRAM module first", "module_absent"),
                    (1, b"requires host CAP_SYS_ADMIN", "permission_denied"), (1, b"Device or resource busy", "device_busy"),
                    (1, b"operation completed; status unavailable", "action_uncertain"), (2, b"bad usage secret", "cli_failure")]
        for code, stderr, expected in failures:
            result = subprocess.CompletedProcess([], code, b"", stderr)
            with patch.object(SERVER.subprocess, "run", return_value=result):
                status, _, body = request(self.server, "/api/actions/lock", "POST")
                self.assertGreaterEqual(status, 400)
                self.assertEqual(json.loads(body)["error"]["code"], expected)
                self.assertEqual(json.loads(body)["error"]["cli_exit"], code)
                self.assertNotIn(b"secret", body)

    def test_malformed_cli_json_and_internal_error_no_traceback(self):
        for raw in (b"not json", b"{}", b'"str"', b'{"abi":NaN}', b"x" * 8193, b"\xff"):
            with patch.object(SERVER.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, raw, b"")):
                self.assertEqual(request(self.server)[0], 502)
        with patch.object(self.server.controller, "call", side_effect=RuntimeError("secret private path")):
            capture = io.StringIO()
            with redirect_stderr(capture):
                status, _, raw = request(self.server)
            self.assertEqual(status, 500)
            for marker in ("Traceback", "secret", str(ROOT), self.server.token):
                self.assertNotIn(marker, raw.decode() + capture.getvalue())

    def test_concurrent_polling_and_actions_serialized(self):
        self.fake.delay = 0.035
        paths = ["/api/status", "/api/stats", "/api/actions/load-random", "/api/actions/lock"] * 3
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda p: request(self.server, p, "POST" if "/actions/" in p else "GET")[0], paths))
        self.assertTrue(all(code in (200, 409, 503) for code in results))
        self.assertEqual(self.fake.maximum, 1)
        self.assertIn(200, results)

    def test_rapid_load_does_not_bypass_cli_state(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: request(self.server, "/api/actions/load-random", "POST")[0], range(8)))
        self.assertEqual(results.count(200), 1)
        self.assertEqual(self.fake.generation, 1)

    def test_busy_bound_and_timeout_releases_lock(self):
        self.server.controller.lock.acquire()
        started = time.monotonic()
        try:
            self.assertEqual(request(self.server)[0], 503)
        finally:
            self.server.controller.lock.release()
        self.assertLess(time.monotonic() - started, 1)
        with patch.object(SERVER.subprocess, "run", side_effect=subprocess.TimeoutExpired([], 15)):
            self.assertEqual(request(self.server)[0], 504)
        self.assertEqual(request(self.server)[0], 200)

    def test_token_not_logged_even_in_rejected_url(self):
        capture = io.StringIO()
        with redirect_stderr(capture):
            request(self.server, "/bad?token=" + self.server.token)
            request(self.server, headers={"Authorization": "Bearer bad"})
        self.assertNotIn(self.server.token, capture.getvalue())


class ContractTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux", "signal/entrypoint check requires Linux")
    def test_real_entrypoint_signals_and_no_state_change(self):
        session = runpy.run_path(str(ROOT / "tests/m7-vm-session.py"))
        # Simulate only the UID gate, not OS privileges, in an unprivileged child.
        # Never call an authorized API route: no CLI or device is touched.
        code = ("import os,runpy; os.geteuid=lambda:0; "
                f"app=runpy.run_path({str(ROOT / 'dashboard/server.py')!r}); app['main']()")
        for signum in (signal.SIGINT, signal.SIGTERM):
            child = subprocess.Popen([sys.executable, "-I", "-u", "-c", code],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                origin, token = session["read_startup"](child)
                conn = http.client.HTTPConnection("127.0.0.1", int(origin.rsplit(":", 1)[1]), timeout=5)
                conn.request("GET", "/")
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
                conn.close()
                child.send_signal(signum)
                stdout, stderr = child.communicate(timeout=5)
                self.assertEqual(child.returncode, 0)
                self.assertEqual(stderr, b"")
                self.assertIn(b"SecureRAM state was not changed", stdout)
                self.assertNotIn(token.encode(), stdout)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=5)

    def test_entrypoint_refuses_unprivileged_or_non_linux_launch(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("this check is for an ordinary user")
        result = subprocess.run([sys.executable, "-I", str(ROOT / "dashboard/server.py")],
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"launch explicitly as root in Linux", result.stderr)

    def test_u64_max_and_unknown_state_feature(self):
        result = SERVER.validate_json("stats", json.dumps(dict(STATS, **dict.fromkeys(SERVER.COUNTERS, 2**64 - 1))).encode())
        self.assertTrue(all(result[k] == "18446744073709551615" for k in SERVER.COUNTERS))
        for state in SERVER.NAMES:
            result = SERVER.validate_json("status", json.dumps(dict(STATUS, state=state, state_name=SERVER.NAMES[state])).encode())
            self.assertTrue(result["compatible"])
        result = SERVER.validate_json("status", json.dumps(dict(STATUS, state=99, state_name="UNKNOWN", features=31)).encode())
        self.assertFalse(result["compatible"])
        self.assertEqual(result["features"], 31)
        self.assertIsNone(SERVER.validate_json("status", json.dumps(dict(STATUS, version=None)).encode())["version"])

    def test_bad_types_ranges_duplicates_and_mismatch(self):
        for field in STATS:
            for value in (-1, True, 1.0, "1", None, 2**64):
                with self.subTest(field=field, value=value), self.assertRaises(SERVER.APIError):
                    SERVER.validate_json("stats", json.dumps(dict(STATS, **{field: value})).encode())
        for field, value in (("state", True), ("features", -1), ("generation", 2**64),
                             ("capacity_bytes", 0), ("unit_bytes", 512), ("abi", 2),
                             ("state_name", "ACTIVE"), ("xts", 1), ("lock", False),
                             ("cli_version", None), ("version", "<script>")):
            with self.subTest(field=field), self.assertRaises(SERVER.APIError):
                SERVER.validate_json("status", json.dumps(dict(STATUS, **{field: value})).encode())
        with self.assertRaises(SERVER.APIError):
            SERVER.validate_json("stats", json.dumps(STATS).replace('"abi": 1', '"abi": 1,"abi": 1').encode())

    def test_allowlist_before_spawn(self):
        with patch.object(SERVER.subprocess, "run") as run:
            for command in ("status;id", "$(id)", "sudo", "tamper", "help", "/bin/sh"):
                with self.assertRaises(SERVER.APIError):
                    SERVER.Controller().call(command)
            run.assert_not_called()

    def test_symlink_static_escape_and_cli_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            static = root / "static"
            static.mkdir()
            for name, _ in SERVER.ASSETS.values():
                (static / name).write_text("fixture")
            outside = root / "private.txt"
            outside.write_text("not public")
            (static / "app.js").unlink()
            try:
                (static / "app.js").symlink_to(outside)
            except OSError:
                self.skipTest("symlink privilege unavailable; run this test in WSL/Linux")
            with patch.object(SERVER, "STATIC", static), self.assertRaises(ValueError):
                SERVER.load_assets()
            with patch.object(SERVER, "CLI", static / "app.js"), self.assertRaises(SERVER.APIError):
                SERVER.Controller().call("status")
            root_link = root / "linked-static"
            root_link.symlink_to(static, target_is_directory=True)
            with patch.object(SERVER, "STATIC", root_link), self.assertRaises(ValueError):
                SERVER.load_assets()

    def test_worker_bound_and_shutdown_idle_connections(self):
        with running_server() as server:
            sockets = []
            try:
                for _ in range(SERVER.WORKERS):
                    conn = socket.create_connection(("127.0.0.1", server.server_port), timeout=2)
                    conn.sendall(b"GET / HTTP/1.1\r\n")
                    sockets.append(conn)
                time.sleep(0.1)
                with socket.create_connection(("127.0.0.1", server.server_port), timeout=2) as extra:
                    try:
                        extra.sendall(b"GET / HTTP/1.1\r\n\r\n")
                        self.assertEqual(extra.recv(32), b"")
                    except ConnectionResetError:
                        pass
                self.assertFalse(server.slots.acquire(blocking=False))
            finally:
                for conn in sockets:
                    conn.close()
        self.assertEqual(server.token, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
