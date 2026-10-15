#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Local M10 measurement/oracle checks. Synthetic fixtures are NOT results."""
import copy
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BENCH = runpy.run_path(str(ROOT / "tests/m10-benchmarks.py"))
ANALYZE = runpy.run_path(str(ROOT / "tests/m10-analyze.py"))


class MeasurementTests(unittest.TestCase):
    def test_cli_actions_do_not_request_unsupported_json(self):
        commands = []
        def fake_run(command):
            commands.append(command)
            return '{}' if '--json' in command else 'action succeeded'
        with patch.dict(BENCH['cli'].__globals__, run=fake_run):
            self.assertEqual(BENCH['cli']('load-random'), 'action succeeded')
            self.assertEqual(BENCH['cli']('destroy'), 'action succeeded')
            self.assertEqual(BENCH['cli']('status'), {})
            self.assertEqual(BENCH['cli']('snapshot', 'status'), {})
        self.assertEqual(commands[0], [BENCH['CLI'], 'load-random'])
        self.assertNotIn('--json', commands[1])
        self.assertIn('--json', commands[2])

    def fixture(self):
        direction = dict(total_ios=256, bw_bytes=1048576, iops=256,
                         lat_ns=dict(mean=100000), io_bytes=1048576)
        empty = dict(total_ios=0, bw_bytes=0, iops=0, lat_ns=dict(mean=0), io_bytes=0)
        job = dict(error=0, read=direction, write=empty, usr_cpu=2, sys_cpu=3)
        before = dict(cpu=[0]*8, monotonic_ns=0, pswpin=0, pswpout=0)
        after = dict(cpu=[10, 0, 20, 65, 0, 0, 0, 5], monotonic_ns=2000000000, pswpin=0, pswpout=0)
        meta = dict(status="PASS", target="secureram", rw="read", bs=4096,
                    region_bytes=1048576, jobs=2, trial=1, before=before, after=after)
        return meta, dict(jobs=[job, copy.deepcopy(job)])

    def test_aggregate_units_cpu_and_latency_weighting(self):
        meta, result = self.fixture()
        row = ANALYZE["parse_trial"](meta, result)
        self.assertEqual(row["mib_s"], 2)
        self.assertEqual(row["iops"], 512)
        self.assertEqual(row["latency_us"], 100)
        self.assertEqual(row["guest_busy_pct"], 30)
        self.assertEqual(row["guest_steal_pct"], 5)
        self.assertEqual(row["fio_cpu_core_pct"], 10)
        self.assertEqual(row["elapsed_s"], 2)
        result["jobs"][1]["read"].update(total_ios=768, lat_ns=dict(mean=200000))
        self.assertEqual(ANALYZE["parse_trial"](meta, result)["latency_us"], 175)

    def test_failures_and_swap_never_become_results(self):
        for kind in ("status", "error", "swap", "job_count", "zero"):
            meta, result = self.fixture()
            if kind == "status": meta["status"] = "STARTED"
            if kind == "error": result["jobs"][0]["error"] = 5
            if kind == "swap": meta["after"]["pswpout"] = 1
            if kind == "job_count": result["jobs"].pop()
            if kind == "zero":
                for job in result["jobs"]: job["read"]["total_ios"] = 0
            with self.assertRaises(AssertionError): ANALYZE["parse_trial"](meta, result)

    def test_statistics_preserve_extreme_values(self):
        result = ANALYZE["describe"]([1, 2, 100])
        self.assertEqual(result["n"], 3)
        self.assertEqual(result["median"], 2)
        self.assertEqual(result["maximum"], 100)
        self.assertGreater(result["stdev"], 50)

    def test_matrix_and_fixed_device_commands(self):
        cases = BENCH["configurations"](64*1048576, 4)
        self.assertEqual(len(cases), 15)
        self.assertEqual(len(set(cases)), 15)
        self.assertTrue(all(c[3] == 1 for c in BENCH["configurations"](64*1048576, 1)))
        params = dict(runtime_s=5, ramp_s=1)
        for case in cases:
            command = BENCH["fio_command"]("secureram", "/dev/secureram0", case, 2, params, "/tmp/output")
            self.assertIn("--direct=1", command)
            self.assertIn("--filename=/dev/secureram0", command)
            self.assertIn("--randseed=10002", command)
        with self.assertRaises(AssertionError):
            BENCH["fio_command"]("secureram", "/dev/sda", cases[0], 1, params, "/tmp/output")
        with self.assertRaises(AssertionError):
            BENCH["fio_command"]("tmpfs", "/tmp/unsafe", cases[0], 1, params, "/tmp/output")

    def test_analysis_rejects_missing_or_duplicate_trials(self):
        # Synthetic fixture stops before lifecycle analysis; never retained as evidence.
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "fio").mkdir()
            params = dict(configurations=[["read", 4096, 1048576, 2]], trials=1)
            (directory / "parameters.json").write_text(json.dumps(params))
            meta, result = self.fixture()
            (directory / "fio/one.meta.json").write_text(json.dumps(meta))
            (directory / "fio/one.json").write_text(json.dumps(result))
            with self.assertRaisesRegex(AssertionError, "missing/duplicate/unplanned"):
                ANALYZE["analyze"](directory)
            (directory / "fio/duplicate.meta.json").write_text(json.dumps(meta))
            (directory / "fio/duplicate.json").write_text(json.dumps(result))
            with self.assertRaisesRegex(AssertionError, "missing/duplicate/unplanned"):
                ANALYZE["analyze"](directory)


if __name__ == "__main__":
    unittest.main()
