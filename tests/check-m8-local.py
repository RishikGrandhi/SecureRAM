#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""M8 compile, sanitized core, CLI, HTTP, UI and harness regression; no devices."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*command):
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kdir", required=True)
    parser.add_argument("--checkpatch", required=True)
    args = parser.parse_args()
    run(sys.executable, "tests/check-m6-local.py", "--kdir", args.kdir, "--checkpatch", args.checkpatch)
    run(sys.executable, "tests/check-m8-core.py")
    run(sys.executable, "tests/check-m8-cli.py")
    run(sys.executable, "tests/check-m7-local.py")
    run(sys.executable, "tests/check-m8-dashboard.py")
    run("bash", "tests/check-m8-vm-harness.sh")
    node = shutil.which("node") or shutil.which("node.exe")
    if not node:
        raise RuntimeError("Existing Node runtime required for M8 UI assertions")
    run(node, "tests/check-m8-ui.js")
    print("PASS: M8 local checks; real VM/kernel and Ubuntu browser acceptance remain separate")


if __name__ == "__main__":
    main()
