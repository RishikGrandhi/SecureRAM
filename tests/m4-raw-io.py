#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Opt-in destructive M4 VM checks; only /dev/secureram0, never auto-run.

Usage: sudo python3 tests/m4-raw-io.py denied|active
The active mode requires a newly installed key and logical zero contents.
The control helper must be compiled to .cache/m4-control first.
"""

import errno
import hashlib
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parent.parent
BASE = runpy.run_path(str(ROOT / "tests/m2-raw-io.py"))
require = BASE["require"]
read_exact = BASE["read_exact"]
write_exact = BASE["write_exact"]
DEVICE = "/dev/secureram0"
SYSFS = Path("/sys/class/block/secureram0")


def identity(version="0.4.0"):
    require(sys.platform == "linux" and os.geteuid() == 0,
            "Run manually as root in the disposable Ubuntu VM")
    require(Path("/sys/module/secureram/version").read_text().strip() == version,
            f"Expected SecureRAM version {version}")
    node = os.lstat(DEVICE)
    require(stat.S_ISBLK(node.st_mode), "Expected block node, not a symlink")
    number = f"{os.major(node.st_rdev)}:{os.minor(node.st_rdev)}"
    require(SYSFS.joinpath("dev").read_text().strip() == number,
            "Block node/sysfs device numbers differ")
    require(not list(SYSFS.joinpath("holders").iterdir()), "Block holders exist")
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        require(line.split()[2] != number, "SecureRAM is mounted")
    for field in ("logical_block_size", "physical_block_size"):
        require(int(SYSFS.joinpath("queue", field).read_text()) == 4096,
                "Unexpected geometry")
    capacity = int(SYSFS.joinpath("size").read_text()) * 512
    mib = int(Path("/sys/module/secureram/parameters/capacity_mb").read_text())
    require(1 <= mib <= 256 and capacity == mib * 1024 * 1024, "Unexpected capacity")
    return node.st_rdev, capacity


def main(version="0.4.0"):
    require(len(sys.argv) == 2 and sys.argv[1] in ("denied", "active"),
            "Use denied or active; target is /dev/secureram0 only")
    number, capacity = identity(version)
    if sys.argv[1] == "denied":
        for mode in (os.O_RDONLY, os.O_WRONLY):
            try:
                fd = os.open(DEVICE, mode | os.O_DIRECT | os.O_NOFOLLOW | os.O_CLOEXEC)
            except OSError as error:
                require(error.errno == errno.ENOKEY, f"Unexpected denial: {error}")
            else:
                os.close(fd)
                raise RuntimeError("Keyless/locked block open unexpectedly succeeded")
        print("PASS: read and write opens fail closed with ENOKEY")
        print("Open denial prevents userspace I/O; it does not inject queue_rq directly.")
        return

    flags = os.O_RDWR | os.O_EXCL | os.O_DIRECT | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(DEVICE, flags)
    try:
        require(os.fstat(fd).st_rdev == number, "Device identity changed during open")
        subprocess.run([str(ROOT / ".cache/m4-control"), "busy"], check=True)
        BASE["test_device"](fd, capacity)
        with TemporaryDirectory(prefix="secureram-m4-") as directory:
            source = Path(directory, "input.bin")
            output = Path(directory, "readback.bin")
            payload = os.urandom(1024 * 1024)
            source.write_bytes(payload)
            write_exact(fd, 0, payload)
            os.fsync(fd)
            output.write_bytes(read_exact(fd, 0, len(payload)))
            first = hashlib.sha256(source.read_bytes()).hexdigest()
            second = hashlib.sha256(output.read_bytes()).hexdigest()
            print(f"SHA-256 input:    {first}\nSHA-256 readback: {second}")
            require(first == second, "SHA-256 mismatch")
            subprocess.run(["cmp", "--", str(source), str(output)], check=True)
        print("PASS: SHA-256 and cmp for 1 MiB random direct I/O")
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
