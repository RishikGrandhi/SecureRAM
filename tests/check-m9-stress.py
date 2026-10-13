#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Test stress oracles against public in-memory fixtures, never a block device."""
import errno
import io
import os
import runpy
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
M9 = runpy.run_path(str(ROOT / "tests/m9-stress.py"))
G = M9["torture"].__globals__


class Oracles(unittest.TestCase):
    def test_complete_and_mixed_units(self):
        data = M9["pattern"](0, 3, 0) + M9["pattern"](1, 2, 1)
        M9["validate_units"](data, 0, range(2), 3)
        # A larger read can contain different complete units; only a torn unit fails.
        for broken in (data[:100] + bytes([data[100] ^ 1]) + data[101:], data[4096:] + data[:4096]):
            with self.assertRaises(AssertionError):
                M9["validate_units"](broken, 0, range(2), 3)
        for owners, maximum in (((0,), 3), (range(2), 1)):
            with self.assertRaises(AssertionError):
                M9["validate_units"](data, 0, owners, maximum)

    def test_thread_failure_propagates(self):
        def fail():
            raise RuntimeError("deliberate worker failure")
        with self.assertRaisesRegex(RuntimeError, "deliberate"):
            M9["burst"]([lambda: 1, fail, lambda: 2])

    def test_snapshot_oracle_rejects_missing_restore(self):
        def run(broken):
            live = bytearray(1024 * 1024)
            slot = None
            def write(_fd, offset, data):
                live[offset:offset + len(data)] = data
            def change(_fd, command, error=None):
                nonlocal slot
                observed = None
                if command == M9["CREATE"]:
                    if slot is None:
                        slot = bytes(live)
                    else:
                        observed = errno.EEXIST
                elif command == M9["RESTORE"]:
                    if slot is None:
                        observed = errno.ENODATA
                    elif not broken:
                        live[:] = slot
                elif command in (M9["DELETE"], M9["DESTROY"]):
                    slot = None
                assert observed == error
            with patch.dict(G, cli=lambda *_: None, block_open=lambda *_: 999,
                            WRITE=write, READ=lambda _f, o, n: bytes(live[o:o + n]),
                            status=lambda _: (2, 1, len(live)), stats=lambda _: (0,) * 5,
                            change=change), patch.object(G["os"], "close"):
                M9["torture"](1, 1, 4)
        run(False)
        with self.assertRaises(AssertionError):
            run(True)

    def test_m9_session_timeout_cleans_process_group(self):
        session = runpy.run_path(str(ROOT / "tests/m7-vm-session.py"))
        globals_ = session["run_session"].__globals__
        server = MagicMock()
        server.stdout = io.BytesIO()
        phases = MagicMock()
        phases.__enter__.return_value = phases
        phases.pid = 12345
        phases.wait.side_effect = [subprocess.TimeoutExpired([], 7200), 0]
        records = []
        stop = MagicMock()
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, SR_MILESTONE="9", M5_VM_RUN_DIR=directory), \
                patch.dict(globals_, record=lambda *args: records.append(args),
                           read_startup=lambda _: ("http://127.0.0.1:32123", "t" * 43),
                           assert_loopback=MagicMock(), stop_server=stop), \
                patch.object(subprocess, "Popen", side_effect=[server, phases]) as popen, \
                patch.object(os, "killpg") as kill:
            with self.assertRaises(subprocess.TimeoutExpired):
                session["run_session"]()
            self.assertTrue(popen.call_args_list[1].kwargs["start_new_session"])
            self.assertTrue(popen.call_args_list[1].args[0][1].endswith("m9-vm-phases.sh"))
            kill.assert_called_once_with(12345, signal.SIGTERM)
            stop.assert_called_once_with(server, 32123)
            self.assertTrue(server.stdout.closed)
            self.assertIn(("Final cleanup", "FAIL", "M7 session aborted; no runtime acceptance claimed"), records)
            self.assertNotIn("t" * 43, str(records))


if __name__ == "__main__":
    unittest.main(verbosity=2)
