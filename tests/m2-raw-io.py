#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Destructive VM-only smoke test, hard-coded to a fresh /dev/secureram0.

Run manually as root after loading M2. This never loads, unloads, or formats a
device. O_EXCL refuses a mounted/exclusively held block device. O_DIRECT and
page-aligned mmap buffers exercise the driver instead of the page cache.
"""

import errno
import mmap
import os
from pathlib import Path
import stat
import sys
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory


DEVICE = "/dev/secureram0"
SYSFS = Path("/sys/class/block/secureram0")
BLOCK = 4096
MIB = 1024 * 1024


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_exact(fd, offset, length):
    with mmap.mmap(-1, length) as buffer:
        count = os.preadv(fd, [buffer], offset)
        require(count == length, f"Short read at {offset}: {count}/{length}")
        return buffer[:]


def write_exact(fd, offset, data):
    with mmap.mmap(-1, len(data)) as buffer:
        buffer[:] = data
        count = os.pwrite(fd, buffer, offset)
        require(count == len(data), f"Short write at {offset}: {count}/{len(data)}")


def check_identity():
    require(sys.platform == "linux", "Run inside the Linux test VM")
    require(os.geteuid() == 0, "Run manually with sudo in the test VM")
    device_stat = os.lstat(DEVICE)
    require(stat.S_ISBLK(device_stat.st_mode), "Expected a block device, not a symlink")
    expected_dev = SYSFS.joinpath("dev").read_text().strip()
    actual_dev = f"{os.major(device_stat.st_rdev)}:{os.minor(device_stat.st_rdev)}"
    require(actual_dev == expected_dev, "Device number does not match SecureRAM sysfs")
    version = Path("/sys/module/secureram/version").read_text().strip()
    require(version == "0.2.0", f"Expected M2 version 0.2.0, found {version}")
    logical = int(SYSFS.joinpath("queue/logical_block_size").read_text())
    physical = int(SYSFS.joinpath("queue/physical_block_size").read_text())
    require(logical == physical == BLOCK, "Unexpected block geometry")
    require(mmap.PAGESIZE % BLOCK == 0, "Test requires page-aligned 4 KiB buffers")
    capacity = int(SYSFS.joinpath("size").read_text()) * 512
    capacity_mb = int(Path("/sys/module/secureram/parameters/capacity_mb").read_text())
    require(1 <= capacity_mb <= 256, "Unexpected capacity parameter")
    require(capacity == capacity_mb * MIB, "Advertised capacity disagrees with parameter")
    return device_stat.st_rdev, capacity


def test_device(fd, capacity):
    # Full zero scan must precede every write; this requires a fresh module load.
    for offset in range(0, capacity, MIB):
        length = min(MIB, capacity - offset)
        require(read_exact(fd, offset, length) == bytes(length),
                f"Fresh storage is not zero at offset {offset}; reload before testing")
    print(f"PASS: {capacity} bytes, geometry, and full initial-zero scan", flush=True)

    with TemporaryDirectory(prefix="secureram-m2-") as directory:
        source = Path(directory, "input.bin")
        output = Path(directory, "readback.bin")
        source.write_bytes(os.urandom(MIB))
        write_exact(fd, 0, source.read_bytes())
        os.fsync(fd)
        output.write_bytes(read_exact(fd, 0, MIB))
        require(source.read_bytes() == output.read_bytes(), "1 MiB readback mismatch")
    print("PASS: temporary-file round trip through direct, segmented I/O", flush=True)

    for offset in (0, BLOCK, capacity // 2, capacity - BLOCK):
        data = os.urandom(BLOCK)
        write_exact(fd, offset, data)
        require(read_exact(fd, offset, BLOCK) == data, f"Block mismatch at {offset}")
    print("PASS: first, nonzero-offset, middle, and final logical blocks", flush=True)

    # Adjacent guard blocks detect accidental overwrite of neighboring data.
    guard = os.urandom(3 * BLOCK)
    write_exact(fd, 0, guard)
    replacement = os.urandom(BLOCK)
    write_exact(fd, BLOCK, replacement)
    require(read_exact(fd, 0, 3 * BLOCK) == guard[:BLOCK] + replacement + guard[2 * BLOCK:],
            "Overwriting one block changed a neighbor")

    # Disjoint ranges permit deterministic verification under competing writers.
    def parallel_round(index):
        length = min(128 * 1024, capacity // 16)
        offset = index * length
        for _ in range(4):
            data = os.urandom(length)
            write_exact(fd, offset, data)
            require(read_exact(fd, offset, length) == data,
                    f"Concurrent I/O mismatch in region {index}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(parallel_round, range(4)))
    print("PASS: neighboring-block isolation and four concurrent I/O streams", flush=True)

    first_block = read_exact(fd, 0, BLOCK)
    final_block = read_exact(fd, capacity - BLOCK, BLOCK)
    with mmap.mmap(-1, BLOCK) as buffer:
        require(os.preadv(fd, [buffer], capacity) == 0, "Read at end did not return EOF")
        buffer[:] = os.urandom(BLOCK)
        try:
            count = os.pwrite(fd, buffer, capacity)
        except OSError as error:
            require(error.errno in (errno.ENOSPC, errno.EIO, errno.EINVAL, errno.ENXIO),
                    f"Unexpected end-of-device error: {error}")
        else:
            require(count == 0, f"Out-of-range write unexpectedly wrote {count} bytes")
    require(read_exact(fd, 0, BLOCK) == first_block, "Out-of-range write wrapped to start")
    require(read_exact(fd, capacity - BLOCK, BLOCK) == final_block,
            "Out-of-range write changed the final valid block")
    os.fsync(fd)
    print("PASS: end-of-device read/write behavior and flush", flush=True)
    print("Boundary syscalls may be rejected by the block core before driver dispatch.")


def main():
    require(len(sys.argv) == 1, "No device argument accepted; target is /dev/secureram0 only")
    expected_dev, capacity = check_identity()
    flags = os.O_RDWR | os.O_EXCL | os.O_DIRECT | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(DEVICE, flags)
    try:
        actual = os.fstat(fd)
        require(stat.S_ISBLK(actual.st_mode) and actual.st_rdev == expected_dev,
                "Device identity changed during open")
        test_device(fd, capacity)
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
