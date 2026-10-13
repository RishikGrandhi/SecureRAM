#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bounded destructive M9 phases, only through the VM harness; no alternate device."""
from concurrent.futures import ThreadPoolExecutor
import ctypes
import errno
import fcntl
import hashlib
import mmap
import os
from pathlib import Path
import runpy
import stat
import struct
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
M8 = runpy.run_path(str(ROOT / "tests/m8-snapshot.py"))
BASE = M8["BASE"]
UNIT = 4096
CREATE, RESTORE, DELETE = M8["CREATE"], M8["RESTORE"], M8["DELETE"]
QUERY, LOAD, LOCK, UNLOCK, DESTROY = (BASE[k] for k in ("QUERY", "LOAD", "LOCK", "UNLOCK", "DESTROY"))
STATS, SNAPSHOT = 0x8050B705, M8["STATUS"]
READ, WRITE = BASE["read_exact"], BASE["write_exact"]
ERROR = BASE["expect_error"]
SEED = 0x9A17
FAULT = Path("/sys/module/secureram/parameters/m9_fault")


def cli(*args, code=0, diagnostic=None):
    result = subprocess.run([M8["CLI"], *args], capture_output=True, text=True, timeout=60)
    assert result.returncode == code, (args, result.returncode, result.stderr)
    if diagnostic is not None:
        assert diagnostic in result.stderr, "unexpected CLI fault errno diagnostic"
    return result.stdout


def status(fd):
    raw = bytearray(48)
    fcntl.ioctl(fd, QUERY, raw, True)
    values = struct.unpack("=IIIIQQIIII", raw)
    assert values[:4] == (1, 48, 0, 0) and values[7:] == (4096, 31, 0)
    return values[6], values[5], values[4]  # state, generation, capacity


def stats(fd):
    raw = bytearray(80)
    fcntl.ioctl(fd, STATS, raw, True)
    assert struct.unpack_from("=IIII", raw) == (1, 80, 0, 0) and raw[56:] == bytes(24)
    return struct.unpack_from("=QQQQQ", raw, 16)


def snapshot(fd):
    raw = bytearray(96)
    fcntl.ioctl(fd, SNAPSHOT, raw, True)
    assert struct.unpack_from("=IIII", raw) == (1, 96, 0, 0) and raw[80:] == bytes(16)
    return struct.unpack_from("=IIQQQQQQQ", raw, 16)


def change(fd, command, error=None):
    payload = struct.pack("=IIII", 1, 16, int(command == DESTROY), 0)
    call = lambda: fcntl.ioctl(fd, command, payload)
    if error is None:
        call()
    else:
        ERROR(call, error)


def block_open(number, direct=True):
    fd = os.open("/dev/secureram0", os.O_RDWR | os.O_EXCL | os.O_NOFOLLOW |
                 os.O_CLOEXEC | (os.O_DIRECT if direct else 0))
    if os.fstat(fd).st_rdev != number:
        os.close(fd)
        raise RuntimeError("block identity changed")
    return fd


def pattern(owner, iteration, unit):
    header = struct.pack("=IIIII", SEED, owner, iteration, unit, UNIT)
    digest = hashlib.sha256(header).digest()
    return header + (digest * 128)[:UNIT - len(header)]


def validate_units(data, first, owners, iterations):
    assert len(data) % UNIT == 0
    for offset in range(0, len(data), UNIT):
        actual = data[offset:offset + UNIT]
        seed, owner, iteration, unit, size = struct.unpack_from("=IIIII", actual)
        assert (seed, unit, size) == (SEED, first + offset // UNIT, UNIT), "misdirected unit"
        assert owner in owners and 0 <= iteration <= iterations, "unknown write pattern"
        assert actual == pattern(owner, iteration, unit), "torn/corrupt unit"


def burst(functions):
    barrier = threading.Barrier(len(functions), timeout=30)
    def start(function):
        barrier.wait()
        return function()
    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        return [future.result(timeout=180) for future in [pool.submit(start, f) for f in functions]]


def concurrent(fd, number, count):
    cli("load-random")
    block = block_open(number)
    try:
        for overlap in (False, True):
            for owner in range(4):
                first = 0 if overlap else owner * 32
                WRITE(block, first * UNIT, b"".join(pattern(owner, 0, u) for u in range(first, first + 32)))
            def writer(owner):
                first = 0 if overlap else owner * 32
                for iteration in range(1, count + 1):
                    units = 1 if iteration % 2 else 32
                    data = b"".join(pattern(owner, iteration, u) for u in range(first, first + units))
                    WRITE(block, first * UNIT, data)
                    if not overlap:
                        assert READ(block, first * UNIT, len(data)) == data
            def reader(owner):
                first = 0 if overlap else owner * 32
                for _ in range(count):
                    validate_units(READ(block, first * UNIT, 32 * UNIT), first,
                                   range(4) if overlap else (owner,), count)
            def control():
                previous = stats(fd)
                before = status(fd)
                for _ in range(count):
                    for command in (CREATE, RESTORE, DELETE, LOCK, UNLOCK, DESTROY):
                        change(fd, command, errno.EBUSY)
                    dummy = struct.pack("=IIIIII", 1, 88, 0, 0, 64, 0) + bytes(64)
                    ERROR(lambda: fcntl.ioctl(fd, LOAD, dummy), errno.EBUSY)
                    current = stats(fd)
                    assert all(a <= b for a, b in zip(previous, current))
                    assert current[-1] == 0 and status(fd) == before
                    assert snapshot(fd)[0] == 0
                    previous = current
            burst([lambda i=i: writer(i) for i in range(4)] +
                  [lambda i=i: reader(i) for i in range(4)] + [control])
            for owner in range(4):
                first = 0 if overlap else owner * 32
                validate_units(READ(block, first * UNIT, 32 * UNIT), first,
                               range(4) if overlap else (owner,), count)
            print("PASS:", "overlap" if overlap else "disjoint", "4 writers + 4 readers + control; exact unit patterns", flush=True)
        final = b"".join(pattern(7, 0, u) for u in range(128))
        WRITE(block, 0, final)
        assert READ(block, 0, len(final)) == final
    finally:
        os.close(block)
    boundaries(number, status(fd)[2])
    assert stats(fd)[-1] == 0
    change(fd, DESTROY)


def boundaries(number, capacity):
    block = block_open(number)
    guards = pattern(8, 0, 0) + pattern(8, 0, 1) + pattern(8, 0, 2)
    last = pattern(8, 0, capacity // UNIT - 1)
    try:
        WRITE(block, 0, guards)
        WRITE(block, capacity - UNIT, last)
        with mmap.mmap(-1, UNIT) as buffer:
            for offset, length in ((1, UNIT), (0, 1), (512, 512)):
                view = memoryview(buffer)[:length]
                try:
                    ERROR(lambda: os.pwrite(block, view, offset), errno.EINVAL)
                finally:
                    view.release()
            for offset in (capacity, capacity + UNIT, (1 << 63) - UNIT):
                assert os.preadv(block, [buffer], offset) == 0
                try:
                    count = os.pwrite(block, buffer, offset)
                except OSError as error:
                    assert error.errno in (errno.ENOSPC, errno.EIO, errno.EINVAL, errno.ENXIO, errno.EFBIG)
                else:
                    assert count == 0
        assert READ(block, 0, len(guards)) == guards
        assert READ(block, capacity - UNIT, UNIT) == last
    finally:
        os.close(block)
    # Buffered byte-granularity I/O is permitted. Final close invalidates caches;
    # direct readback below verifies actual driver storage, including neighbors.
    block = block_open(number, direct=False)
    patch = b"M9-public-pattern" * 301
    try:
        assert os.pwrite(block, patch, 17) == len(patch)
        os.fsync(block)
    finally:
        os.close(block)
    block = block_open(number)
    try:
        assert READ(block, 0, len(guards)) == guards[:17] + patch + guards[17 + len(patch):]
        assert READ(block, capacity - UNIT, UNIT) == last
    finally:
        os.close(block)
    print("PASS: direct alignment, EOF/huge offsets, guard units, buffered unaligned persistence", flush=True)


def torture(fd, number, count):
    cli("load-random")
    for cycle in range(count):
        length = UNIT if cycle % 2 else min(status(fd)[2], 1024 * 1024)
        data = b"".join(pattern(10, cycle, u) for u in range(length // UNIT))
        replacement = b"".join(pattern(11, cycle, u) for u in range(length // UNIT))
        block = block_open(number)
        try:
            WRITE(block, 0, data)
        finally:
            os.close(block)
        change(fd, RESTORE, errno.ENODATA)
        change(fd, CREATE)
        change(fd, CREATE, errno.EEXIST)
        block = block_open(number)
        try:
            WRITE(block, 0, replacement)
        finally:
            os.close(block)
        change(fd, RESTORE)
        block = block_open(number)
        try:
            assert READ(block, 0, length) == data
        finally:
            os.close(block)
        change(fd, DELETE)
        change(fd, DELETE)
    assert stats(fd)[-1] == 0
    change(fd, DESTROY)
    print(f"PASS: {count} snapshot A/B/restore cycles; direct authenticated data verified", flush=True)


def outcome(fd, command):
    try:
        change(fd, command)
        return 0
    except OSError as error:
        return error.errno


def races(fd, number, count):
    cli("load-random")
    for _ in range(count):
        results = burst([lambda: outcome(fd, CREATE) for _ in range(4)])
        assert sorted(results) == [0, errno.EEXIST, errno.EEXIST, errno.EEXIST]
        change(fd, DELETE)
        # Both serial orders succeed; final slot presence reflects the last call.
        assert burst([lambda: outcome(fd, CREATE), lambda: outcome(fd, DELETE)]) == [0, 0]
        assert snapshot(fd)[0] in (0, 1)
        change(fd, DELETE)
        block = block_open(number)
        try:
            WRITE(block, 0, pattern(12, 0, 0))
        finally:
            os.close(block)
        change(fd, CREATE)
        block = block_open(number)
        try:
            WRITE(block, 0, pattern(13, 0, 0))
        finally:
            os.close(block)
        results = burst([lambda: outcome(fd, RESTORE), lambda: outcome(fd, DELETE)])
        assert results in ([0, 0], [errno.ENODATA, 0])
        block = block_open(number)
        try:
            assert READ(block, 0, UNIT) == pattern(12 if results[0] == 0 else 13, 0, 0)
        finally:
            os.close(block)
        results = burst([lambda: outcome(fd, CREATE), lambda: outcome(fd, DESTROY)])
        assert results in ([0, 0], [errno.EBUSY, 0])
        assert status(fd)[0] == 0 and snapshot(fd)[0] == 0
        cli("load-random")
        change(fd, RESTORE, errno.ENODATA)
    change(fd, DESTROY)
    print(f"PASS: {count} competing create/delete/restore/destroy rounds and serial-order data oracles", flush=True)


def key_cycles(fd, number, count, leave_slot=False):
    generation = status(fd)[1]
    for cycle in range(count):
        change(fd, LOCK, errno.EBUSY)
        change(fd, UNLOCK, errno.EBUSY)
        cli("load-random")
        generation += 1
        assert status(fd)[:2] == (2, generation)
        assert snapshot(fd)[0] == 0
        change(fd, RESTORE, errno.ENODATA)
        block = block_open(number)
        try:
            capacity = status(fd)[2]
            for offset in range(0, capacity, 1024 * 1024):
                length = min(1024 * 1024, capacity - offset)
                assert READ(block, offset, length) == bytes(length)
            WRITE(block, 0, pattern(14, cycle, 0))
        finally:
            os.close(block)
        change(fd, CREATE)
        change(fd, LOCK)
        ERROR(lambda: block_open(number), errno.ENOKEY)
        change(fd, CREATE, errno.EBUSY)
        change(fd, RESTORE, errno.EBUSY)
        assert snapshot(fd)[4] == generation
        change(fd, UNLOCK)
        block = block_open(number)
        try:
            assert READ(block, 0, UNIT) == pattern(14, cycle, 0)
        finally:
            os.close(block)
        if leave_slot and cycle == count - 1:
            return  # Real unload owns wiping this ACTIVE slot.
        change(fd, DESTROY)
        assert status(fd)[:2] == (0, generation)
        assert snapshot(fd)[:5] == (0, 0, 0, 0, 0)
        ERROR(lambda: block_open(number), errno.ENOKEY)
        change(fd, DESTROY)
    print(f"PASS: {count} key cycles, generations, full zero scans, lock retention and slot destruction", flush=True)


def invalid(fd, number, count):
    cli("load-random")
    before = status(fd), snapshot(fd), stats(fd)
    mutations = ((LOAD, 88), (LOCK, 16), (UNLOCK, 16), (DESTROY, 16),
                 (CREATE, 16), (RESTORE, 16), (DELETE, 16))
    for _ in range(count):
        for command, size in mutations:
            for field, values in ((0, (0, 2, 0xffffffff)), (1, (0, size - 1, size + 1, 0xffffffff)),
                                  (2, (2, 0xffffffff)), (3, (1, 0xffffffff))):
                for value in values:
                    header = [1, size, int(command == DESTROY), 0]
                    header[field] = value
                    payload = struct.pack("=IIII", *header) + bytes(size - 16)
                    ERROR(lambda: fcntl.ioctl(fd, command, payload), errno.EINVAL)
            ERROR(lambda: fcntl.ioctl(fd, command, 1), errno.EFAULT)
        for length in (0, 1, 63, 65, 0xffffffff):
            payload = struct.pack("=IIIIII", 1, 88, 0, 0, length, 0) + bytes(64)
            ERROR(lambda: fcntl.ioctl(fd, LOAD, payload), errno.EINVAL)
        for command in (QUERY, STATS, SNAPSHOT):
            ERROR(lambda: fcntl.ioctl(fd, command, 1), errno.EFAULT)
        for command in (0, 0xffffffff, QUERY ^ (1 << 16), LOAD ^ (1 << 30)):
            ERROR(lambda: fcntl.ioctl(fd, command, bytes(96)), errno.ENOTTY)
    # A readable prefix crossing into PROT_NONE exercises partial user copies.
    libc = ctypes.CDLL(None, use_errno=True)
    libc.ioctl.argtypes = (ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p)
    libc.mprotect.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
    with mmap.mmap(-1, 2 * mmap.PAGESIZE) as memory:
        address = ctypes.addressof(ctypes.c_char.from_buffer(memory))
        assert libc.mprotect(address + mmap.PAGESIZE, mmap.PAGESIZE, 0) == 0
        try:
            for command in (LOAD, LOCK, DESTROY, CREATE, RESTORE, DELETE, QUERY, STATS, SNAPSHOT):
                assert libc.ioctl(fd, command, address + mmap.PAGESIZE - 8) == -1
                assert ctypes.get_errno() == errno.EFAULT
        finally:
            assert libc.mprotect(address + mmap.PAGESIZE, mmap.PAGESIZE, 3) == 0
    assert (status(fd), snapshot(fd), stats(fd)) == before
    for args in ((), ("snapshot",), ("load-random", "--json"), ("destroy", "--force"),
                 ("snapshot", "restore", "--force"), ("status", "--json", "extra")):
        cli(*args, code=2)
    # Existing M4/M8 helpers additionally test EPERM with passed root descriptors.
    change(fd, DESTROY)
    print("PASS: invalid command/header/length/flags/reserved, partial copy EFAULT and CLI usage", flush=True)


def arm(site):
    FAULT.write_text(str(site))
    assert int(FAULT.read_text()) == site


def consumed():
    assert FAULT.read_text().strip() == "0", "intended fault site was not reached"


def faults(fd, number, _count):
    assert stat.S_IMODE(FAULT.stat().st_mode) == 0o600
    ERROR(lambda: arm(8), errno.EINVAL)
    parameter = os.open(FAULT, os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        child = os.fork()
        if child == 0:
            try:
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)
                ERROR(lambda: os.write(parameter, b"4"), errno.EPERM)
            except BaseException:
                os._exit(1)
            os._exit(0)
        assert os.waitstatus_to_exitcode(os.waitpid(child, 0)[1]) == 0
    finally:
        os.close(parameter)
    consumed()
    generation = status(fd)[1]
    for site in (7, 3, 4, 6):
        arm(site)
        output = cli("load-random", code=1, diagnostic=("Cannot allocate memory" if site in (7, 3)
                                                     else "Input/output error"))
        assert not output
        consumed()
        assert status(fd)[:2] == (0, generation) and snapshot(fd)[0] == 0
        ERROR(lambda: block_open(number), errno.ENOKEY)
        cli("load-random")
        generation += 1
        assert status(fd)[:2] == (2, generation)
        block = block_open(number)
        try:
            capacity = status(fd)[2]
            for offset in range(0, capacity, 1024 * 1024):
                length = min(1024 * 1024, capacity - offset)
                assert READ(block, offset, length) == bytes(length)
        finally:
            os.close(block)
        change(fd, DESTROY)
    cli("load-random")
    block = block_open(number)
    data = pattern(15, 0, 0)
    try:
        WRITE(block, 0, data)
    finally:
        os.close(block)
    for site in (1, 2):
        saved = snapshot(fd)
        arm(site)
        change(fd, CREATE, errno.ENOMEM)
        consumed()
        after = snapshot(fd)
        assert after[:8] == saved[:8] and after[8] == saved[8] + 1
        change(fd, CREATE)
        change(fd, RESTORE)
        change(fd, DELETE)
    # Existing valid slot and live unit must survive all operational crypto faults.
    change(fd, CREATE)
    saved = snapshot(fd)
    block = block_open(number)
    try:
        for site in (4, 6):
            arm(site)
            ERROR(lambda: WRITE(block, 0, pattern(16, 0, 0)), errno.EIO)
            consumed()
            assert READ(block, 0, UNIT) == data
        for site in (5, 6):
            with mmap.mmap(-1, UNIT) as buffer:
                buffer[:] = bytes([0xa6]) * UNIT
                arm(site)
                ERROR(lambda: os.preadv(block, [buffer], 0), errno.EIO)
                consumed()
                assert buffer[:] == bytes([0xa6]) * UNIT
            assert READ(block, 0, UNIT) == data
        assert status(fd)[0] == 2 and stats(fd)[-1] == 0
        assert snapshot(fd) == saved
    finally:
        os.close(block)
    change(fd, RESTORE)
    block = block_open(number)
    try:
        assert READ(block, 0, UNIT) == data
    finally:
        os.close(block)
    arm(0)
    change(fd, DESTROY)
    print("PASS: seven one-shot allocation/crypto fault sites, unwind, unit/slot preservation and recovery", flush=True)


def main():
    assert os.environ.get("SR_MILESTONE") == "9", "use run-m9-vm-acceptance.sh"
    assert len(sys.argv) == 2
    phases = {"io": concurrent, "snapshots": torture, "races": races, "keys": key_cycles,
              "invalid": invalid, "faults": faults, "reload": lambda f, n, c: key_cycles(f, n, 1, True)}
    mode = sys.argv[1]
    assert mode in phases
    count = int(os.environ["M9_IO_ROUNDS"] if mode == "io" else os.environ["M9_CYCLES"])
    assert 1 <= count <= 2048
    number, _ = M8["identity"]()
    fd = os.open("/dev/secureramctl", os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        assert status(fd)[0] == 0
        print(f"M9 phase={mode} rounds={count} seed={SEED}", flush=True)
        phases[mode](fd, number, count)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
