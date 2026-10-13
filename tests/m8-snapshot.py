#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Destructive, opt-in VM acceptance; ONLY the verified /dev/secureram0.

production starts NO_KEY, ends ACTIVE with a slot for unload cleanup testing.
tamper requires the M5 test build, starts/ends NO_KEY. No key/data output.
"""
from concurrent.futures import ThreadPoolExecutor
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import stat
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = runpy.run_path(str(ROOT / "tests/m5-integrity.py"))
HTTP = runpy.run_path(str(ROOT / "tests/m7-http.py"))
CLI = str(ROOT / "tools/secureramctl")
CREATE, RESTORE, DELETE, STATUS = 0x4010B706, 0x4010B707, 0x4010B708, 0x8060B709
HEADER = struct.pack("=IIII", 1, 16, 0, 0)


def identity():
    assert "microsoft" not in os.uname().release.lower(), "never run VM acceptance in WSL"
    number, capacity = BASE["BASE"]["identity"]("0.8.0")
    node = os.lstat("/dev/secureramctl")
    assert stat.S_ISCHR(node.st_mode) and node.st_uid == node.st_gid == 0
    assert stat.S_IMODE(node.st_mode) == 0o600
    assert Path("/sys/class/misc/secureramctl/dev").read_text().strip() == f"{os.major(node.st_rdev)}:{os.minor(node.st_rdev)}"
    for line in Path("/proc/swaps").read_text().splitlines()[1:]:
        swap = os.stat(line.split()[0])
        assert not (stat.S_ISBLK(swap.st_mode) and swap.st_rdev == number), "device is swap"
    return number, capacity


def cli(*args, code=0):
    result = subprocess.run([CLI, *args], text=True, capture_output=True)
    assert result.returncode == code, (args, result.returncode, result.stderr)
    return json.loads(result.stdout) if "--json" in args and not code else result.stdout


def snapshot():
    value = cli("snapshot", "status", "--json")
    assert value["abi"] == 1 and type(value["exists"]) is bool
    assert all(type(value[key]) is int for key in ("state", "data_bytes", "tag_bytes", "generation",
                                                  "created", "restored", "deleted", "failures"))
    return value


def change(fd, command, error=None):
    if error is None:
        fcntl.ioctl(fd, command, HEADER)
    else:
        BASE["expect_error"](lambda: fcntl.ioctl(fd, command, HEADER), error)


def http_action(action):
    word = {"restore": "RESTORE", "delete": "DELETE"}.get(action)
    body = json.dumps({"confirm": word} if word else {})
    code, _, raw = HTTP["request"]("/api/actions/snapshot-" + action, "POST", body)
    assert code == 200, (action, code)
    assert json.loads(raw) == dict(ok=True, action="snapshot-" + action, refresh_required=True)


def check_http():
    code, _, raw = HTTP["request"]("/api/snapshot")
    assert code == 200
    data = json.loads(raw)
    expected = snapshot()
    for key in ("data_bytes", "tag_bytes", "generation", "created", "restored", "deleted", "failures"):
        expected[key] = str(expected[key])
    assert data == expected


def negative(fd):
    before = snapshot()
    for command in (CREATE, RESTORE, DELETE, STATUS):
        for pointer in (0, 1):
            BASE["expect_error"](lambda: fcntl.ioctl(fd, command, pointer), errno.EFAULT)
        BASE["expect_error"](lambda: fcntl.ioctl(fd, command ^ (1 << 16), HEADER), errno.ENOTTY)
    for command in (CREATE, RESTORE, DELETE):
        for bad in ((2, 16, 0, 0), (1, 15, 0, 0), (1, 16, 1, 0), (1, 16, 0, 1)):
            BASE["expect_error"](lambda: fcntl.ioctl(fd, command, struct.pack("=IIII", *bad)), errno.EINVAL)
    raw = bytearray(b"\xff" * 96)
    fcntl.ioctl(fd, STATUS, raw, True)
    assert struct.unpack_from("=IIII", raw) == (1, 96, 0, 0) and raw[80:] == bytes(16)
    child = os.fork()
    if child == 0:
        try:
            os.setgroups([])
            os.setgid(65534)
            os.setuid(65534)
            for command in (CREATE, RESTORE, DELETE, STATUS):
                BASE["expect_error"](lambda: fcntl.ioctl(fd, command, raw, True), errno.EPERM)
        except BaseException:
            os._exit(1)
        os._exit(0)
    assert os.waitstatus_to_exitcode(os.waitpid(child, 0)[1]) == 0
    assert snapshot() == before, "malformed/unauthorized requests must not mutate slot or counters"
    print("PASS: new ioctl layouts/reserved output, EFAULT, EINVAL, ENOTTY and passed-fd EPERM")


def pattern(label, offset, length):
    seed = hashlib.sha256(f"SecureRAM-M8-{label}-{offset}".encode()).digest()
    return (seed * ((length + 31) // 32))[:length]


def disk(label=None):
    number, capacity = identity()
    fd = BASE["open_block"](number)
    digest = hashlib.sha256()
    try:
        for offset in range(0, capacity, 1048576):
            length = min(1048576, capacity - offset)
            if label is not None:
                BASE["write_exact"](fd, offset, pattern(label, offset, length))
            digest.update(BASE["read_exact"](fd, offset, length))
        os.fsync(fd)
    finally:
        os.close(fd)
    return digest.hexdigest()


def busy_io(fd):
    number, _ = identity()
    block = BASE["open_block"](number)
    try:
        def writer():
            for index in range(32):
                data = pattern("concurrent", index, 4096)
                BASE["write_exact"](block, 0, data)
                assert BASE["read_exact"](block, 0, 4096) == data
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(writer)
            for _ in range(8):
                for command in (CREATE, RESTORE, DELETE):
                    change(fd, command, errno.EBUSY)
                assert snapshot()["exists"]
            future.result()
    finally:
        os.close(block)
    print("PASS: concurrent direct I/O, coherent status, all mutations reject open users")


def production(fd):
    assert cli("status", "--json")["state"] == 0
    assert not snapshot()["exists"] and snapshot()["created"] == 0
    negative(fd)
    change(fd, CREATE, errno.EBUSY)
    change(fd, RESTORE, errno.EBUSY)
    change(fd, DELETE)
    cli("load-random")
    assert cli("status", "--json")["state"] == 2
    change(fd, RESTORE, errno.ENODATA)
    sha_a = disk("A")
    http_action("create")
    saved = snapshot()
    assert saved["exists"] and saved["generation"] == 1
    assert saved["data_bytes"] == identity()[1] and saved["tag_bytes"] == saved["data_bytes"] // 128
    change(fd, CREATE, errno.EEXIST)
    check_http()
    sha_b = disk("B")
    assert sha_a != sha_b
    before = cli("stats", "--json")["integrity_failures"]
    http_action("restore")
    sha_restored = disk()
    assert sha_restored == sha_a
    assert cli("stats", "--json")["integrity_failures"] == before == 0
    print(f"SHA_A={sha_a}\nSHA_B={sha_b}\nSHA_RESTORED={sha_restored}")
    print("PASS: full-device deterministic rollback and authenticated reads without mismatches")
    busy_io(fd)  # Also verifies subsequent writes after restoration.
    change(fd, RESTORE)
    assert disk() == sha_a
    cli("lock")
    assert snapshot()["generation"] == saved["generation"] and snapshot()["state"] == 3
    change(fd, CREATE, errno.EBUSY)
    change(fd, RESTORE, errno.EBUSY)
    cli("unlock")
    change(fd, RESTORE)
    assert disk() == sha_a
    cli("lock")
    http_action("delete")  # Cleanup while LOCKED; no data change.
    change(fd, DELETE)
    cli("unlock")
    assert disk() == sha_a
    for index in range(8):
        digest = disk(f"cycle-{index}")
        change(fd, CREATE)
        disk(f"changed-{index}")
        change(fd, RESTORE)
        assert disk() == digest
        change(fd, DELETE)
        change(fd, DELETE)
    # Administrators race for the one empty slot; exactly one may publish it.
    def create_race(_):
        try:
            change(fd, CREATE)
            return 0
        except OSError as error:
            return error.errno
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(create_race, range(8)))
    assert results.count(0) == 1 and results.count(errno.EEXIST) == 7
    saved = snapshot()
    assert (saved["created"], saved["restored"], saved["deleted"]) == (10, 11, 9)
    # 2 NO_KEY + 1 absent + 1 occupied + 24 busy + 2 LOCKED + 7 race losers.
    assert saved["failures"] == 37, saved
    cli("destroy")
    assert cli("status", "--json")["state"] == 0
    cleared = snapshot()
    assert not cleared["exists"] and cleared["generation"] == cleared["data_bytes"] == cleared["tag_bytes"] == 0
    assert all(cleared[key] == saved[key] for key in ("created", "restored", "deleted", "failures"))
    change(fd, RESTORE, errno.EBUSY)
    cli("load-random")
    assert cli("status", "--json")["generation"] == 2
    change(fd, RESTORE, errno.ENODATA)
    assert disk() == hashlib.sha256(bytes(identity()[1])).hexdigest()
    change(fd, CREATE)
    assert snapshot()["generation"] == 2
    check_http()
    print("PASS: counters, LOCKED cleanup, 8 full cycles, racing create, destroy/rekey invalidation")
    print("ACTIVE snapshot left for the harness's orderly unload-with-slot test")


def tamper(fd):
    assert cli("status", "--json")["state"] == 0
    cli("load-random")
    change(fd, CREATE)
    number, _ = identity()
    fcntl.ioctl(fd, BASE["TAMPER"], struct.pack("=IIIIQQII", 1, 40, 0, 0, 0, 0, 1, 0))
    block = BASE["open_block"](number)
    try:
        BASE["expect_error"](lambda: BASE["read_exact"](block, 0, 4096), errno.EIO)
    finally:
        os.close(block)
    assert snapshot()["state"] == 4 and snapshot()["exists"]
    change(fd, CREATE, errno.EBUSY)
    change(fd, RESTORE, errno.EBUSY)
    check_http()
    http_action("delete")
    assert not snapshot()["exists"] and cli("status", "--json")["state"] == 4
    cli("destroy")
    print("PASS: snapshot restore cannot clear integrity latch; deletion remains available")


def main():
    assert len(sys.argv) == 2 and sys.argv[1] in ("production", "tamper")
    assert os.environ.get("SR_MILESTONE") in ("8", "9") and os.environ.get("M7_TOKEN"), "use the M8/M9 harness"
    identity()
    fd = os.open("/dev/secureramctl", os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        (production if sys.argv[1] == "production" else tamper)(fd)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
