#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""M8 CLI tests against the inherited syscall boundary fixture, never a device."""
import json
from pathlib import Path
import runpy

BASE = runpy.run_path(str(Path(__file__).with_name("check-m6-cli.py")))
BASE["main"]()  # Build real/mocked CLI and run the unchanged M6 behavior assertions.
run = BASE["run"]
for mock in (False, True):
    for args in (["snapshot"], ["snapshot", "wat"], ["snapshot", "status", "bad"],
                 ["snapshot", "create", "--json", "extra"]):
        run(args, 2, mock=mock)
for state in (0, 2, 3, 4):
    absent = json.loads(run(["snapshot", "status", "--json"], scenario="m8-absent", state=state))
    assert set(absent) == {"abi", "exists", "state", "data_bytes", "tag_bytes", "generation",
                           "created", "restored", "deleted", "failures"}
    assert absent["exists"] is False and absent["created"] == 2**64 - 1
    assert absent["data_bytes"] == absent["tag_bytes"] == absent["generation"] == 0
    run(["snapshot", "delete", "--json"], scenario="m8-absent", state=state)
    for command in ("create", "restore"):
        if state != 2:
            run(["snapshot", command], 1, "m8-present", state)
present = json.loads(run(["snapshot", "create", "--json"], scenario="m8-absent", state=2))
assert present["exists"] and present["data_bytes"] == 67108864 and present["tag_bytes"] == 524288
assert present["generation"] == 1
assert "Snapshot: available" in run(["snapshot", "restore"], scenario="m8-present", state=2)
for command, scenario in (("create", "m8-present"), ("create", "m8-memory"),
                           ("restore", "m8-absent"), ("restore", "m8-stale"),
                           ("delete", "m8-busy"), ("create", "m8-followup")):
    run(["snapshot", command], 1, scenario, 2)
for scenario in ("m8-size", "m8-reserved", "m8-metadata", "old-driver", ""):
    run(["snapshot", "status", "--json"], 3, scenario, 2)
assert "Snapshot: absent" in run(["snapshot", "delete"], scenario="m8-present", state=3)
print("PASS: M8 CLI fixed commands, JSON/u64, features/ABI, all states, failure diagnostics and follow-up failure")
