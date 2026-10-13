#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""M9 compile and local regression entry point. Never loads a module or device."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*command):
    subprocess.run(command, cwd=ROOT, check=True)


def capture(label, command):
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (ROOT / f"build-m9-{label}.log").write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(f"{label} failed:\n{result.stdout}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kdir", required=True)
    parser.add_argument("--checkpatch", required=True)
    args = parser.parse_args()
    run(sys.executable, "tests/check-m9-stress.py")
    run("bash", "tests/check-m9-vm-harness.sh")
    make = ["make", "KDIR=" + args.kdir, "CC=gcc"]
    for name, flags in (("fault", ["M9_TEST=1"]), ("all-test", ["M9_TEST=1", "M5_TEST=1", "M4_TEST=1"])):
        capture(name + "-clean", make + ["clean"])
        output = capture(name, make + ["W=1", *flags])
        assert not re.search(r"(?m)^(?:.*/)?(?:src|include)/.*(?:warning:|error:)", output)
        symbols = capture(name + "-nm", ["nm", "secureram.ko"])
        assert "secureram_fault_pending" in symbols and "__param_m9_fault" in symbols
        print(f"PASS: {name} W=1 build and one-shot selector linkage", flush=True)
    # Includes all old build/static/core/CLI/HTTP/UI/harness assertions, ending
    # in a clean production build, then explicitly proves M9 object exclusion.
    run(sys.executable, "tests/check-m8-local.py", "--kdir", args.kdir, "--checkpatch", args.checkpatch)
    symbols = capture("production-nm", ["nm", "secureram.ko"])
    assert not re.search(r"secureram_fault|m9_fault", symbols)
    assert not (ROOT / "src/secureram_fault.o").exists()
    capture("production-preprocess", ["make", "-C", args.kdir, f"M={ROOT}", "CC=gcc", "src/secureram_control.i"])
    source = ROOT / "src/secureram_control.i"
    try:
        assert re.search(r"static inline[^;{}]*bool secureram_fault\([^)]*\)\s*"
                         r"\{\s*\(void\)site;\s*return false;\s*\}", source.read_text())
        assert "bool secureram_fault(enum secureram_fault_site site);" not in source.read_text()
    finally:
        source.unlink()
    run("git", "diff", "--check")
    print("PASS: M9 local checks and production exclusion; VM kernel stress remains separate")


if __name__ == "__main__":
    main()
