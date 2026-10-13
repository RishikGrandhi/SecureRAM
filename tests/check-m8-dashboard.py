#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""M8 real HTTP/CLI-boundary tests; no device access or snapshot implementation."""
import json
from pathlib import Path
import runpy
import subprocess
import unittest
from unittest.mock import patch

BASE = runpy.run_path(str(Path(__file__).with_name("check-m7-dashboard.py")))
SERVER = BASE["SERVER"]
request = BASE["request"]


class FakeCLI(BASE["FakeCLI"]):
    def __init__(self):
        super().__init__()
        self.exists = False
        self.created = self.restored = self.deleted = 0

    def run(self, argv, **kwargs):
        if argv[1] != "snapshot":
            result = super().run(argv, **kwargs)
            if argv[1] == "status" and not result.returncode:
                data = json.loads(result.stdout)
                data.update(version="0.8.0", cli_version="0.8.0", features=31)
                result.stdout = json.dumps(data).encode()
            if argv[1] == "destroy" and not result.returncode:
                self.exists = False
            return result
        assert argv[0] == str(SERVER.CLI) and kwargs["shell"] is False
        assert kwargs["timeout"] == SERVER.CLI_TIMEOUT and kwargs["close_fds"] is True
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
        command = argv[2]
        assert command in ("status", "create", "restore", "delete")
        assert argv[3:] == (["--json"] if command == "status" else [])
        assert kwargs["stdout"] == (subprocess.PIPE if command == "status" else subprocess.DEVNULL)
        self.calls.append(argv)
        error = None
        if command == "delete":
            self.deleted += int(self.exists)
            self.exists = False
        elif command in ("create", "restore"):
            if self.state != 2:
                error = b"Device or resource busy"
            elif command == "create" and self.exists:
                error = b"snapshot slot occupied"
            elif command == "restore" and not self.exists:
                error = b"no snapshot exists"
            elif command == "create":
                self.exists = True
                self.created += 1
            else:
                self.restored += 1
        if error:
            return subprocess.CompletedProcess(argv, 1, None, error)
        data = dict(abi=1, exists=self.exists, state=self.state,
                    data_bytes=67108864 if self.exists else 0,
                    tag_bytes=524288 if self.exists else 0,
                    generation=self.generation if self.exists else 0,
                    created=self.created, restored=self.restored, deleted=self.deleted, failures=0)
        return subprocess.CompletedProcess(argv, 0, json.dumps(data).encode() if command == "status" else None, b"")


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeCLI()
        self.patches = [patch.object(SERVER, "CLI", Path(__file__).resolve()),
                        patch.object(SERVER.subprocess, "run", self.fake.run)]
        for item in self.patches:
            item.start()
        self.context = BASE["running_server"]()
        self.server = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)
        for item in reversed(self.patches):
            item.stop()

    def action(self, name, code=200):
        confirmation = SERVER.CONFIRMATIONS.get(name)
        body = json.dumps({"confirm": confirmation} if confirmation else {})
        self.assertEqual(request(self.server, "/api/actions/" + name, "POST", body)[0], code)

    def test_full_flow_and_fixed_argv(self):
        self.action("snapshot-create", 409)
        self.action("snapshot-restore", 409)
        self.action("load-random")
        self.action("snapshot-restore", 409)
        self.action("snapshot-create")
        self.action("snapshot-create", 409)
        status, _, raw = request(self.server, "/api/snapshot")
        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertTrue(data["exists"])
        self.assertEqual(data["data_bytes"], "67108864")
        self.assertEqual(data["generation"], "1")
        self.action("snapshot-restore")
        self.action("lock")
        self.action("snapshot-restore", 409)
        self.action("snapshot-create", 409)
        self.action("snapshot-delete")
        self.action("snapshot-delete")
        self.action("unlock")
        self.action("snapshot-create")
        self.action("destroy")
        self.assertFalse(json.loads(request(self.server, "/api/snapshot")[2])["exists"])
        self.assertIn([str(SERVER.CLI), "snapshot", "status", "--json"], self.fake.calls)

    def test_confirmation_and_security_all_routes(self):
        for action in ("snapshot-create", "snapshot-restore", "snapshot-delete"):
            route = "/api/actions/" + action
            self.assertEqual(request(self.server, route)[0], 405)
            for headers, expected in (({"Authorization": ""}, 401),
                                      ({"Origin": "null"}, 403), ({"Host": "evil.test"}, 403),
                                      ({"Sec-Fetch-Site": "cross-site"}, 403)):
                self.assertEqual(request(self.server, route, "POST", headers=headers)[0], expected)
            if action != "snapshot-create":
                for body in ("{}", '{"confirm":"wrong"}', '{"confirm":true}',
                             '{"confirm":"RESTORE","x":1}', '{"confirm":"DELETE","confirm":"DELETE"}'):
                    self.assertEqual(request(self.server, route, "POST", body)[0], 400)
        self.assertEqual(request(self.server, "/api/snapshot", headers={"Authorization": ""})[0], 401)
        self.assertEqual(request(self.server, "/api/actions/snapshot-create;id", "POST")[0], 404)
        self.assertEqual(self.fake.calls, [])

    def test_strict_schema_precision_and_errors(self):
        data = dict(abi=1, exists=False, state=0, **dict.fromkeys(SERVER.SNAPSHOT_VALUES, 0))
        data["created"] = 2**64 - 1
        valid = SERVER.validate_json("snapshot", json.dumps(data).encode())
        self.assertEqual(valid["created"], str(2**64 - 1))
        for changes in ({"exists": 1}, {"data_bytes": 1}, {"generation": 1}, {"x": 1},
                        {"created": -1}, {"created": 2**64}, {"state": True},
                        {"exists": True, "generation": 1, "data_bytes": 67108864, "tag_bytes": 1}):
            with self.assertRaises(SERVER.APIError):
                SERVER.validate_json("snapshot", json.dumps(data | changes).encode())
        for error, code in ((b"snapshot generation is incompatible", "snapshot_stale"),
                            (b"Cannot allocate memory", "snapshot_memory"),
                            (b"INTEGRITY_FAILED; operation completed", "action_uncertain")):
            result = subprocess.CompletedProcess([], 1, None, error)
            with patch.object(SERVER.subprocess, "run", return_value=result):
                status, _, body = request(self.server, "/api/actions/snapshot-create", "POST")
                self.assertGreaterEqual(status, 400)
                self.assertEqual(json.loads(body)["error"]["code"], code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
