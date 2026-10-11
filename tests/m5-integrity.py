#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Manual destructive M5 VM tests, only /dev/secureram0; no alternate target.

production: require test ioctl ENOTTY, no media changes.
tamper: require NO_KEY; corruption, latch, rejection and recovery; ends NO_KEY.
Uses native-endian fixed-width ABI layouts, checked in abi-layout.c.
"""

import errno
import fcntl
import mmap
import os
from pathlib import Path
import runpy
import stat
import struct
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
BASE = runpy.run_path(str(ROOT / "tests/m4-raw-io.py"))
require = BASE["require"]
read_exact = BASE["read_exact"]
write_exact = BASE["write_exact"]
DEVICE = "/dev/secureram0"
UNIT = 4096
QUERY, LOAD, LOCK, UNLOCK, DESTROY = (
    0x8030B700, 0x4058B701, 0x4010B702, 0x4010B703, 0x4010B704)
TAMPER = 0x4028B770
HEADER = struct.Struct("=IIII")
STATUS = struct.Struct("=IIIIQQIIII")
INJECT = struct.Struct("=IIIIQQII")


def header(size=16, flags=0):
    return HEADER.pack(1, size, flags, 0)


def expect_error(operation, expected):
    try:
        operation()
    except OSError as error:
        require(error.errno == expected, f"Expected errno {expected}, got {error}")
    else:
        raise RuntimeError(f"Operation unexpectedly succeeded; expected errno {expected}")


def query(fd):
    raw = bytearray(STATUS.size)
    fcntl.ioctl(fd, QUERY, raw, True)
    version, size, flags, reserved, capacity, generation, state, unit, features, tail = (
        STATUS.unpack(raw))
    require((version, size, flags, reserved, unit, features, tail) ==
            (1, 48, 0, 0, 4096, 7, 0), "Unexpected query ABI/geometry/features")
    return state, generation, capacity


def inject(fd, operation, unit, byte=0, other=0):
    BASE["identity"]("0.5.0")
    fcntl.ioctl(fd, TAMPER, INJECT.pack(1, 40, 0, 0, unit, other, operation, byte))


def open_block(number):
    fd = os.open(DEVICE, os.O_RDWR | os.O_DIRECT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC)
    if os.fstat(fd).st_rdev != number:
        os.close(fd)
        raise RuntimeError("Block identity changed on open")
    return fd


def change(fd, command):
    BASE["identity"]("0.5.0")
    fcntl.ioctl(fd, command, header(flags=1 if command == DESTROY else 0))


def load_key():
    BASE["identity"]("0.5.0")
    subprocess.run([str(ROOT / ".cache/m4-control"), "load-test-key"], check=True)


def zero_scan(number, capacity):
    block = open_block(number)
    try:
        for offset in range(0, capacity, 1024 * 1024):
            length = min(1024 * 1024, capacity - offset)
            require(read_exact(block, offset, length) == bytes(length),
                    f"Recovery medium is not zero at {offset}")
    finally:
        os.close(block)


def negative_hooks(fd, units):
    expect_error(lambda: inject(fd, 1, units), errno.ERANGE)
    expect_error(lambda: inject(fd, 1, 2**64 - 1), errno.ERANGE)
    expect_error(lambda: inject(fd, 1, 0, byte=UNIT), errno.EINVAL)
    expect_error(lambda: inject(fd, 2, 0, byte=32), errno.EINVAL)
    expect_error(lambda: inject(fd, 1, 0, other=1), errno.EINVAL)
    expect_error(lambda: inject(fd, 3, 0, other=units), errno.EINVAL)
    expect_error(lambda: inject(fd, 3, 0, other=0), errno.EINVAL)
    expect_error(lambda: inject(fd, 99, 0), errno.EINVAL)
    for field, value in ((0, 2), (1, 39), (2, 1), (3, 1)):
        fields = [1, 40, 0, 0, 0, 0, 1, 0]
        fields[field] = value
        expect_error(lambda: fcntl.ioctl(fd, TAMPER, INJECT.pack(*fields)), errno.EINVAL)
    # A passed root-opened descriptor must still check host administration rights.
    child = os.fork()
    if child == 0:
        try:
            os.setgroups([])
            os.setgid(65534)
            os.setuid(65534)
            expect_error(lambda: fcntl.ioctl(fd, TAMPER,
                         INJECT.pack(1, 40, 0, 0, 0, 0, 1, 0)), errno.EPERM)
        except (OSError, RuntimeError):
            os._exit(1)
        os._exit(0)
    _, result = os.waitpid(child, 0)
    require(os.waitstatus_to_exitcode(result) == 0, "Passed-fd tamper privilege test failed")


def tamper_case(fd, number, capacity, operation, source, target, byte):
    before = query(fd)
    require(before[0] == 0, "Each case must start NO_KEY")
    load_key()
    active = query(fd)
    require(active == (2, before[1] + 1, capacity), "Activation/generation mismatch")
    zero_scan(number, capacity)
    negative_hooks(fd, capacity // UNIT)
    block = open_block(number)
    payload = os.urandom(UNIT)
    try:
        write_exact(block, source * UNIT, payload)
        require(read_exact(block, source * UNIT, UNIT) == payload, "Pre-tamper I/O failed")
        if target != source:
            write_exact(block, target * UNIT, os.urandom(UNIT))
        expect_error(lambda: inject(fd, operation, source, byte, target if operation == 3 else 0),
                     errno.EBUSY)
    finally:
        os.close(block)
    # Last close drains/invalidates caches. No block fd or mount at injection.
    inject(fd, operation, source, byte, target if operation == 3 else 0)
    require(query(fd) == active, "Injection should not latch until a read verifies")
    block = open_block(number)
    try:
        with mmap.mmap(-1, UNIT) as buffer:
            sentinel = bytes([0xA6]) * UNIT
            buffer[:] = sentinel
            expect_error(lambda: os.preadv(block, [buffer], target * UNIT), errno.EIO)
            require(buffer[:] == sentinel, "Failing unit modified the caller's read buffer")
            require(query(fd) == (4, active[1], capacity), "Missing integrity latch")
            # Already-open descriptor, including an otherwise valid unit.
            expect_error(lambda: os.preadv(block, [buffer], UNIT * 2), errno.EIO)
            require(buffer[:] == sentinel, "Latched read modified output")
            expect_error(lambda: os.pwrite(block, buffer, UNIT * 2), errno.EIO)
            expect_error(lambda: change(fd, DESTROY), errno.EBUSY)
    finally:
        os.close(block)
    for mode in (os.O_RDONLY, os.O_WRONLY):
        expect_error(lambda: os.open(DEVICE, mode | os.O_DIRECT | os.O_NOFOLLOW), errno.EIO)
    for command in (LOCK, UNLOCK):
        expect_error(lambda: change(fd, command), errno.EBUSY)
    # Non-secret dummy input: state rejects before key validation/setup.
    expect_error(lambda: fcntl.ioctl(fd, LOAD, header(88) +
                 struct.pack("=II", 64, 0) + bytes(64)), errno.EBUSY)
    expect_error(lambda: inject(fd, 1, 0), errno.EBUSY)
    require(query(fd) == (4, active[1], capacity), "Rejected control cleared latch")
    change(fd, DESTROY)
    change(fd, DESTROY)
    require(query(fd) == (0, active[1], capacity), "Destroy must be idempotent")
    load_key()
    require(query(fd) == (2, active[1] + 1, capacity), "Recovery generation mismatch")
    zero_scan(number, capacity)
    block = open_block(number)
    try:
        write_exact(block, target * UNIT, payload)
        require(read_exact(block, target * UNIT, UNIT) == payload, "Recovery I/O failed")
    finally:
        os.close(block)
    change(fd, DESTROY)
    print(f"PASS: operation={operation}, EIO, untouched output, latch, rejection, recovery")


def main():
    require(len(sys.argv) == 2 and sys.argv[1] in ("production", "tamper"),
            "Use production or tamper; target is /dev/secureram0 only")
    require(HEADER.size == 16 and STATUS.size == 48 and INJECT.size == 40, "ABI sizes")
    number, capacity = BASE["identity"]("0.5.0")
    fd = os.open("/dev/secureramctl", os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        major, minor = map(int, Path("/sys/class/misc/secureramctl/dev").read_text().split(":"))
        require(stat.S_ISCHR(info.st_mode) and info.st_rdev == os.makedev(major, minor),
                "Control identity mismatch")
        require(query(fd)[2] == capacity, "Control/data capacity mismatch")
        if sys.argv[1] == "production":
            expect_error(lambda: inject(fd, 1, 0), errno.ENOTTY)
            print("PASS: production rejects M5 corruption ioctl with ENOTTY")
            return
        require(query(fd)[0] == 0, "Tamper suite requires NO_KEY")
        expect_error(lambda: inject(fd, 1, 0), errno.EBUSY)
        for args in ((1, 0, 0, 0), (2, capacity // UNIT // 2, capacity // UNIT // 2, 31),
                     (3, 1, capacity // UNIT - 1, 0)):
            tamper_case(fd, number, capacity, *args)
        print("PASS: ciphertext, tag, relocation and recovery; final NO_KEY")
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
