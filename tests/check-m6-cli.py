#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build/run CLI with link-time mocks. No devices, root, module or network."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MOCK = ROOT / ".cache/m6-cli-mock"
FLAGS = ["-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Iinclude"]
WRAPS = ("open", "close", "fstat", "fopen", "prctl", "mlock", "munlock", "getrandom", "ioctl")


def run(args, code=0, scenario="", state=0, mock=True):
    env = dict(os.environ, M6_MOCK=scenario, M6_STATE=str(state))
    result = subprocess.run([str(MOCK if mock else ROOT / "tools/secureramctl"), *args],
                            env=env, text=True, capture_output=True)
    assert result.returncode == code, (args, scenario, result)
    if code:
        assert result.stderr and not result.stdout, result
    return result.stdout


def main():
    os.chdir(ROOT)
    MOCK.parent.mkdir(exist_ok=True)
    subprocess.run(["make", "tools-clean"], check=True)
    subprocess.run(["make", "tools"], check=True)
    subprocess.run(["gcc", *FLAGS, "tools/secureramctl.c", "tests/m6-cli-mock.c",
                    *[f"-Wl,--wrap={name}" for name in WRAPS], "-o", str(MOCK)], check=True)
    for mock in (False, True):
        assert "Usage:" in run(["help"], mock=mock)
        assert run(["version"], mock=mock) == "secureramctl 0.8.0 (ABI 1)\n"
        for args in ([], ["oops"], ["--json"], ["help", "--json"],
                     ["load-random", "--json"], ["status", "extra"],
                     ["stats", "--json", "extra"], ["destroy", "yes"]):
            run(args, 2, mock=mock)
    for state, name in ((0, "NO_KEY"), (1, "PREPARING"), (2, "ACTIVE"),
                        (3, "LOCKED"), (4, "INTEGRITY_FAILED"), (99, "UNKNOWN")):
        status = json.loads(run(["status", "--json"], state=state))
        assert status["state"] == state and status["state_name"] == name
        assert status["features"] == 15 and status["capacity_bytes"] == 67108864
        assert all(status[key] is True for key in ("xts", "lock", "integrity", "stats"))
        assert name in run(["status"], state=state)
        stats = json.loads(run(["stats", "--json"], state=state))
        assert stats["read_bytes"] == 2**64 - 1 and stats["write_bytes"] == 8192
        assert "Successful read requests: 3" in run(["stats"], state=state)
    for scenario in ("version-missing", "version-invalid"):
        assert json.loads(run(["status", "--json"], scenario=scenario))["version"] is None
    for scenario in ("missing", "permission", "identity"):
        run(["status"], 1, scenario)
    for scenario in ("abi", "unsupported", "query-reserved"):
        run(["status"], 3, scenario)
    for scenario in ("old-driver", "stats-size", "stats-reserved"):
        run(["stats", "--json"], 3, scenario)
    assert "ACTIVE (2) generation=1" in run(["load-random"])
    for scenario in ("dump-fail", "mlock-fail", "random-fail", "random-zero", "load-fail", "munlock-fail"):
        run(["load-random"], 1, scenario)
    for state in (2, 3, 4):
        run(["load-random"], 1, state=state)
    assert "LOCKED" in run(["lock"], state=2)
    assert "ACTIVE" in run(["unlock"], state=3)
    for state in (0, 2, 3, 4):
        assert "NO_KEY" in run(["destroy"], state=state)
        for command in ("lock", "unlock", "destroy"):
            run([command], 1, "busy", state)
    for command, state in (("lock", 0), ("unlock", 0), ("lock", 4), ("unlock", 4)):
        run([command], 1, state=state)
    print("PASS: CLI parsing, JSON/all states/u64/null version, errors, ABI/features, transitions")
    print("PASS: protected 64-byte random load, EINTR/short reads, wipe before munlock on all generated-key exits")


if __name__ == "__main__":
    main()
