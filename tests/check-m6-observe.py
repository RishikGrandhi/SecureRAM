#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Self-test the actual VM statistics assertions using stdlib mocks only."""
import copy
import json
from pathlib import Path
import runpy
import struct
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SUITE = runpy.run_path(str(ROOT / "tests/m6-observe.py"))
G = SUITE["main"].__globals__
ZERO = dict(abi=1, read_requests=0, write_requests=0, read_bytes=0,
            write_bytes=0, integrity_failures=0)
DATA = dict(abi=1, read_requests=2, write_requests=3, read_bytes=8192,
            write_bytes=12288, integrity_failures=0)


def rejects(operation):
    try:
        operation()
    except (AssertionError, KeyError):
        return
    raise AssertionError("invalid statistics unexpectedly accepted")


def test_schema():
    for fixture in (ZERO, DATA, dict(DATA, read_bytes=2**64 - 1)):
        with patch.dict(G, cli=lambda *args: fixture):
            assert SUITE["stats"]() == fixture
    invalid = [dict(DATA, read_bytes=value) for value in (-1, 2**64, True, 1.5)]
    invalid += [dict(DATA, abi=2), dict(DATA, secret="forbidden")]
    for fixture in invalid:
        with patch.dict(G, cli=lambda *args: fixture):
            rejects(SUITE["stats"])


def test_snapshot_modes():
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "stats.json"

        def mode(name, fixture):
            with patch.dict(G, stats=lambda: fixture), patch("sys.argv", ["mock", name, str(target)]):
                SUITE["main"]()

        mode("save", DATA)
        assert json.loads(target.read_text()) == DATA
        mode("equal", DATA)
        mode("retained", DATA)
        more = {key: value + 4096 if key in SUITE["COUNTERS"][:4] else value
                for key, value in DATA.items()}
        mode("increased", more)
        rejects(lambda: mode("equal", more))
        rejects(lambda: mode("increased", DATA))
        rejects(lambda: mode("retained", ZERO))


def test_accounting():
    expected = dict(DATA, read_requests=3, write_requests=4, read_bytes=12288, write_bytes=16384)
    invalid = [dict(expected, **{key: expected[key] + 1}) for key in SUITE["COUNTERS"]]
    for after in [expected, *invalid]:
        snapshots = iter((DATA, after))
        payload = b"p" * 4096  # Non-secret test data, never used on a real device.
        base = dict(G["BASE"], BASE={"identity": lambda version: (123, 67108864)},
                    open_block=lambda number: 456,
                    write_exact=lambda fd, offset, data: None,
                    read_exact=lambda fd, offset, length: payload)
        with patch.dict(G, stats=lambda: next(snapshots), BASE=base), \
                patch("os.urandom", return_value=payload), patch("os.close") as close:
            if after == expected:
                SUITE["accounting"]()
            else:
                rejects(SUITE["accounting"])
            close.assert_called_once_with(456)


def test_baseline():
    # Execute the real baseline parser/output-zero assertions. The privilege child
    # itself is not simulated as proof of runtime capability enforcement.
    def ioctl(fd, command, payload, mutate=True):
        assert fd == 456 and command == G["GET_STATS"]
        if payload == 0:
            raise OSError(14, "synthetic EFAULT")
        payload[:] = struct.pack("=IIII8Q", 1, 80, 0, 0, *([0] * 8))

    with patch.dict(G, stats=lambda: ZERO, cli=lambda *args: "mock stats\n"), \
            patch("os.open", return_value=456), patch("os.close"), \
            patch("os.fork", return_value=123), patch("os.waitpid", return_value=(123, 0)), \
            patch("fcntl.ioctl", side_effect=ioctl):
        SUITE["baseline"]()
    with patch.dict(G, stats=lambda: DATA):
        rejects(SUITE["baseline"])


def test_integrity_observer():
    suite = runpy.run_path(str(ROOT / "tests/m6-integrity.py"))
    globals_ = suite["observe"].__globals__
    failed = dict(DATA, integrity_failures=1)

    def event(name, fixture):
        m6 = dict(globals_["M6"], stats=lambda: copy.deepcopy(fixture),
                  status=lambda *args: None,
                  cli=lambda command: "Integrity authentication failures: 1")
        m5 = dict(globals_["M5"], query=lambda fd: (4, 1, 67108864))
        saved_m6, saved_m5 = globals_["M6"], globals_["M5"]
        globals_["M6"], globals_["M5"] = m6, m5
        try:
            suite["observe"](name, 456)
        finally:
            globals_["M6"], globals_["M5"] = saved_m6, saved_m5

    event("before-failure", DATA)
    event("failed", failed)
    event("destroyed", failed)
    event("reloaded", failed)
    rejects(lambda: event("failed", DATA))  # A missing mismatch increment.
    rejects(lambda: event("failed", dict(failed, read_requests=3)))
    event("failed", failed)  # Restore the last valid observed snapshot.
    rejects(lambda: event("destroyed", ZERO))
    rejects(lambda: event("reloaded", dict(failed, write_requests=4)))


if __name__ == "__main__":
    test_schema()
    test_snapshot_modes()
    test_accounting()
    test_baseline()
    test_integrity_observer()
    print("PASS: actual statistics schema, baseline, deltas, lifetime and tamper observers with mocks")
