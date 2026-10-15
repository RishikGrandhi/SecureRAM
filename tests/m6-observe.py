#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Opt-in M6 VM assertions. Data access is only to verified /dev/secureram0."""
import errno
import fcntl
import json
import os
from pathlib import Path
import runpy
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CLI = str(ROOT / "tools/secureramctl")
BASE = runpy.run_path(str(ROOT / "tests/m5-integrity.py"))
GET_STATS = 0x8050B705
COUNTERS = ("read_requests", "write_requests", "read_bytes", "write_bytes", "integrity_failures")
NAMES = {0: "NO_KEY", 1: "PREPARING", 2: "ACTIVE", 3: "LOCKED", 4: "INTEGRITY_FAILED"}
VERSION = "0.8.0" if os.environ.get("SR_MILESTONE") in ("8", "9", "10", "11") else "0.6.0"
FEATURES = 31 if VERSION == "0.8.0" else 15


def cli(command, json_output=False):
    args = [CLI, command] + (["--json"] if json_output else [])
    text = subprocess.check_output(args, text=True)
    return json.loads(text) if json_output else text


def stats():
    result = cli("stats", True)
    assert set(result) == {"abi", *COUNTERS} and result["abi"] == 1
    assert all(type(result[key]) is int and 0 <= result[key] < 2**64 for key in COUNTERS)
    return result


def status(state, generation, capacity):
    result = cli("status", True)
    assert result == dict(version=VERSION, cli_version=VERSION, abi=1, state=state,
                          state_name=NAMES[state], capacity_bytes=capacity, unit_bytes=4096,
                          generation=generation, features=FEATURES, xts=True, lock=True,
                          integrity=True, stats=True), result
    human = cli("status")
    assert f"State: {NAMES[state]} ({state})" in human
    assert "AES-256-XTS" in human and "HMAC-SHA-256" in human
    assert f"{FEATURES} XTS LOCK INTEGRITY STATS" in human
    print(human, end="")
    print(json.dumps(result, sort_keys=True))


def baseline():
    assert all(stats()[key] == 0 for key in COUNTERS), "reload must reset counters"
    print(cli("stats"), end="")
    fd = os.open("/dev/secureramctl", os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        # Validate every output byte independently of the CLI's interpretation.
        raw = bytearray(80)
        fcntl.ioctl(fd, GET_STATS, raw, True)
        assert struct.unpack("=IIII8Q", raw) == (1, 80, 0, 0) + (0,) * 8
        BASE["expect_error"](lambda: fcntl.ioctl(fd, GET_STATS, 0), errno.EFAULT)
        child = os.fork()
        if child == 0:
            try:
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)
                BASE["expect_error"](lambda: fcntl.ioctl(fd, GET_STATS, raw, True), errno.EPERM)
            except (OSError, RuntimeError):
                os._exit(1)
            os._exit(0)
        _, result = os.waitpid(child, 0)
        assert os.waitstatus_to_exitcode(result) == 0
    finally:
        os.close(fd)
    assert all(stats()[key] == 0 for key in COUNTERS), "queries must not count as I/O"
    print("PASS: zero counters, reserved output, EFAULT and passed-fd GET_STATS privilege")


def accounting():
    number, _ = BASE["BASE"]["identity"](VERSION)
    fd = BASE["open_block"](number)
    try:
        before = stats()
        payload = os.urandom(4096)
        BASE["write_exact"](fd, 0, payload)
        assert BASE["read_exact"](fd, 0, 4096) == payload
        after = stats()
        for field in ("read_requests", "write_requests"):
            assert after[field] - before[field] == 1, (field, before, after)
        for field in ("read_bytes", "write_bytes"):
            assert after[field] - before[field] == 4096, (field, before, after)
        assert after["integrity_failures"] == before["integrity_failures"] == 0
    finally:
        os.close(fd)
    print("PASS: quiescent single-unit direct read/write each add one request and 4096 bytes")


def main():
    mode, *args = sys.argv[1:]
    if mode == "status":
        status(*map(int, args))
    elif mode == "baseline":
        baseline()
    elif mode == "accounting":
        accounting()
    elif mode == "save":
        Path(args[0]).write_text(json.dumps(stats()))
    elif mode in ("equal", "increased", "retained"):
        before, after = json.loads(Path(args[0]).read_text()), stats()
        if mode == "equal":
            assert before == after, (before, after)
        else:
            for field in COUNTERS:
                assert after[field] >= before[field], (field, before, after)
            if mode == "increased":
                for field in COUNTERS[:4]:
                    assert after[field] > before[field], (field, before, after)
        print(f"PASS: statistics {mode}")
    else:
        raise RuntimeError("unknown M6 observation mode")


if __name__ == "__main__":
    main()
