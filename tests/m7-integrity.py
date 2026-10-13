#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""All M5/M6 tamper checks, with HTTP recovery and failed-state observations."""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
M6 = runpy.run_path(str(ROOT / "tests/m6-integrity.py"))
M5 = M6["M5"]
HTTP = runpy.run_path(str(ROOT / "tests/m7-http.py"))
before = None
failed = None
original_change = M5["change"]


def change(fd, command):
    if command == M5["DESTROY"]:
        # Preserve the original direct-ioctl EBUSY check while a block fd is open.
        # That check expects OSError; final recovery calls occur with zero openers.
        M5["BASE"]["identity"](HTTP["VERSION"])
        if M5["query"](fd)[0] == 4:
            # The first destroy check is inside the failed read's open block fd.
            # /proc/self/fd inspection is unnecessary: use the real ioctl for that
            # negative check, then the failed observer below performs HTTP destroy.
            original_change(fd, command)
        else:
            HTTP["action"]("destroy")
    else:
        original_change(fd, command)


def observe(event, fd):
    global before, failed
    M6["observe"](event, fd)
    current = HTTP["get"]("stats")
    if event == "before-failure":
        before = current
    elif event == "failed":
        failed = current
        assert current["integrity_failures"] == before["integrity_failures"] + 1
        assert all(current[k] == before[k] for k in HTTP["COUNTERS"][:4])
        state, generation, capacity = M5["query"](fd)
        HTTP["status"](4, generation, capacity)
        HTTP["rapid_invalid_actions"]()
        HTTP["action"]("destroy")
        HTTP["status"](0, generation, capacity)
        # M5's following two destroys remain idempotent through HTTP.
    elif event == "destroyed":
        assert current == failed
    elif event == "reloaded":
        state, generation, capacity = M5["query"](fd)
        HTTP["status"](2, generation, capacity)
        assert current["integrity_failures"] == failed["integrity_failures"]
        assert current["write_requests"] == failed["write_requests"]
        assert current["write_bytes"] == failed["write_bytes"]
    print(f"PASS: M7 HTTP integrity observation {event}")


if __name__ == "__main__":
    # Reuse the actual functions' globals, not a copied runpy dictionary.
    M5["main"].__globals__["change"] = change
    M5["main"](version=HTTP["VERSION"], features=HTTP["FEATURES"], observer=observe,
               load_command=[sys.executable, str(ROOT / "tests/m7-http.py"), "action", "load-random"])
