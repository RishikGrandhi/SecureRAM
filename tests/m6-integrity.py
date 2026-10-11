#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reuse every M5 tamper assertion and observe M6 at each failure/recovery."""
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
M5 = runpy.run_path(str(ROOT / "tests/m5-integrity.py"))
M6 = runpy.run_path(str(ROOT / "tests/m6-observe.py"))
before_failure = None
failed = None


def observe(event, fd):
    global before_failure, failed
    current = M6["stats"]()
    if event == "before-failure":
        before_failure = current
    elif event == "failed":
        failed = current
        assert current["integrity_failures"] == before_failure["integrity_failures"] + 1
        for field in M6["COUNTERS"][:4]:
            assert current[field] == before_failure[field], "failed requests must not count"
        state, generation, capacity = M5["query"](fd)
        assert state == 4
        M6["status"](4, generation, capacity)
        assert "Integrity authentication failures:" in M6["cli"]("stats")
    elif event == "destroyed":
        assert current == failed, "destroy must preserve all counters"
    elif event == "reloaded":
        assert current["integrity_failures"] == failed["integrity_failures"]
        assert current["write_bytes"] == failed["write_bytes"], "initialization is not I/O"
        assert current["write_requests"] == failed["write_requests"]
    print(f"PASS: M6 integrity observation {event}")


if __name__ == "__main__":
    M5["main"](version="0.6.0", features=15, observer=observe,
               load_command=[M6["CLI"], "load-random"])
