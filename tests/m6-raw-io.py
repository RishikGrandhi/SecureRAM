#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""M6 uses the unchanged M4/M2 raw assertions with an explicit version guard."""
from pathlib import Path
import os
import runpy
import subprocess
import sys

if __name__ == "__main__":
    try:
        version = "0.8.0" if os.environ.get("SR_MILESTONE") in ("8", "9", "10", "11") else "0.6.0"
        runpy.run_path(str(Path(__file__).with_name("m4-raw-io.py")))["main"](version)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
