#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Opt-in M5 VM regression; preserves M4's default historical version guard."""

from pathlib import Path
import runpy
import subprocess
import sys


if __name__ == "__main__":
    try:
        suite = runpy.run_path(str(Path(__file__).with_name("m4-raw-io.py")))
        suite["main"](version="0.5.0")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
