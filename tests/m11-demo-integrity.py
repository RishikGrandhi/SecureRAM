#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reuse the accepted M5 corruption oracle against the current 0.8.0 ABI.

This helper is test-only. It accepts no device path and operates exclusively on
/dev/secureram0 after the shell harness has proved its identity.
"""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
M5 = runpy.run_path(str(ROOT / "tests/m5-integrity.py"))


if __name__ == "__main__":
    if sys.argv != [sys.argv[0]]:
        raise SystemExit("no arguments accepted")
    sys.argv = [sys.argv[0], "tamper"]
    try:
        M5["main"](
            version="0.8.0",
            features=31,
            load_command=[str(ROOT / "tools/secureramctl"), "load-random"],
        )
    except (OSError, RuntimeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1) from error
