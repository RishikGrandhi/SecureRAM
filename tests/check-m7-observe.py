#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute VM HTTP, integrity-observer and process-owner assertions with fixtures."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = runpy.run_path(str(ROOT / "tests/check-m7-dashboard.py"))
SERVER = FIXTURE["SERVER"]
HTTP = runpy.run_path(str(ROOT / "tests/m7-http.py"))
SESSION = runpy.run_path(str(ROOT / "tests/m7-vm-session.py"))


class ObservationTests(unittest.TestCase):
    def test_real_http_assertions_and_failures(self):
        fake = FIXTURE["FakeCLI"]()
        with patch.object(SERVER, "CLI", Path(__file__).resolve()), patch.object(SERVER.subprocess, "run", fake.run):
            with FIXTURE["running_server"]() as server, patch.dict(os.environ, M7_ORIGIN=server.origin, M7_TOKEN=server.token):
                HTTP["status"](0, 0, 67108864)
                HTTP["observe"]("baseline")
                for action in ("load-random", "lock", "unlock"):
                    HTTP["action"](action)
                HTTP["status"](2, 1, 67108864)
                HTTP["action"]("load-random", busy=True)
                fake.state = 4
                HTTP["rapid_invalid_actions"]()
                HTTP["action"]("destroy")
                HTTP["status"](0, 1, 67108864)
                with tempfile.TemporaryDirectory() as directory:
                    path = str(Path(directory) / "before.json")
                    HTTP["observe"]("save", path)
                    HTTP["observe"]("equal", path)
                    HTTP["observe"]("retained", path)
                    with self.assertRaises(AssertionError):
                        HTTP["observe"]("increased", path)
                with self.assertRaises(AssertionError):
                    HTTP["status"](2, 1, 67108864)
                absent = subprocess.CompletedProcess([], 1, b"", b"load the SecureRAM module first")
                with patch.object(SERVER.subprocess, "run", return_value=absent):
                    HTTP["security"]()
                # Actual Linux /proc lookup, current process owns the real test listener.
                SESSION["assert_loopback"](os.getpid(), server.server_port)

    def test_bad_http_schema_rejected(self):
        globals_ = HTTP["get"].__globals__
        for payload in ({"abi": 1}, {"abi": 1, **dict.fromkeys(HTTP["COUNTERS"], 0)},
                        {"abi": 1, **dict.fromkeys(HTTP["COUNTERS"], "18446744073709551616")}):
            with patch.dict(globals_, request=lambda _: (200, {}, json.dumps(payload).encode())):
                with self.assertRaises(AssertionError):
                    HTTP["get"]("stats")
        with patch.dict(globals_, request=lambda *args: (200, {}, b'{}')):
            with self.assertRaises(AssertionError):
                HTTP["action"]("lock", busy=True)

    def test_integrity_observer_checks_failures_and_recovery(self):
        module = runpy.run_path(str(ROOT / "tests/m7-integrity.py"))
        observer = module["observe"]
        globals_ = observer.__globals__
        current = dict(abi=1, **dict.fromkeys(HTTP["COUNTERS"], 0))
        trace = []
        http = dict(module["HTTP"], get=lambda _: current.copy(),
                    status=lambda *args: trace.append(("status", *args)),
                    action=lambda command: trace.append(("action", command)),
                    rapid_invalid_actions=lambda: trace.append(("rapid",)))
        m5 = dict(module["M5"], query=lambda _: (4, 1, 67108864))
        with patch.dict(globals_, M6={"observe": lambda *args: None}, HTTP=http, M5=m5):
            observer("before-failure", 1)
            with self.assertRaises(AssertionError):
                observer("failed", 1)
            current["integrity_failures"] = 1
            current["write_bytes"] = 4096
            with self.assertRaises(AssertionError):
                observer("failed", 1)
            current["write_bytes"] = 0
            observer("failed", 1)
            self.assertIn(("rapid",), trace)
            self.assertIn(("action", "destroy"), trace)
            observer("destroyed", 1)
            current["integrity_failures"] = 0
            with self.assertRaises(AssertionError):
                observer("destroyed", 1)
            current["integrity_failures"] = 1
            observer("reloaded", 1)
            current["write_requests"] = 1
            with self.assertRaises(AssertionError):
                observer("reloaded", 1)


class SessionTests(unittest.TestCase):
    def run_fixture(self, stage):
        records = []
        server = MagicMock()
        server.stdout = io.BytesIO()
        server.poll.return_value = None
        phases = MagicMock()
        phases.__enter__.return_value = phases
        phases.wait.return_value = 1 if stage == "phase" else 0
        stop = MagicMock(side_effect=RuntimeError("cleanup") if stage == "cleanup" else None)
        read = MagicMock(side_effect=RuntimeError("startup") if stage == "startup" else None,
                         return_value=("http://127.0.0.1:32123", "t" * 43))
        globals_ = SESSION["run_session"].__globals__
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, M5_VM_RUN_DIR=directory), \
                patch.dict(globals_, record=lambda *args: records.append(args), read_startup=read,
                           assert_loopback=MagicMock(), stop_server=stop), \
                patch.object(subprocess, "Popen", side_effect=[server, phases]) as popen:
            if stage == "ok":
                SESSION["run_session"]()
            else:
                with self.assertRaises(RuntimeError):
                    SESSION["run_session"]()
            stop.assert_called_once_with(server, None if stage == "startup" else 32123)
            self.assertTrue(server.stdout.closed)
            if stage != "startup":
                # Startup credential appears in neither backend env nor argv.
                first = popen.call_args_list[0]
                self.assertNotIn("M7_TOKEN", first.kwargs["env"])
                self.assertNotIn("t" * 43, str(first.args))
            if stage != "ok":
                self.assertTrue(any(row[1] == "FAIL" for row in records))
            self.assertNotIn("t" * 43, str(records))

    def test_success_and_early_abort_cleanup(self):
        for stage in ("ok", "startup", "phase", "cleanup"):
            with self.subTest(stage=stage):
                self.run_fixture(stage)

    def test_stop_timeout_is_failure_even_after_kill(self):
        for port in (32123, None):
            with self.subTest(port=port):
                process = MagicMock()
                process.poll.return_value = None
                process.wait.side_effect = [subprocess.TimeoutExpired([], 22), 0]
                with self.assertRaises(RuntimeError):
                    SESSION["stop_server"](process, port)
                process.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
