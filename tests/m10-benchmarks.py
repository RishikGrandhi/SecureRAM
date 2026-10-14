#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""M10 VM experiments. Only the fixed SecureRAM device and owned tmpfs file.

No keys enter this process: load-random uses the established protected C CLI.
Importing this file performs no privileged operations.
"""
import errno
import fcntl
import json
import os
from pathlib import Path
import random
import re
import runpy
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
MIB = 1048576
CLI = str(ROOT / "tools/secureramctl")
BASE = runpy.run_path(str(ROOT / "tests/m8-snapshot.py"))
RAW = BASE["BASE"]


def run(command, timeout=60):
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout).stdout


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def cli(*args):
    return json.loads(run([CLI, *args, "--json"]))


def resources():
    values = {}
    for name in ("meminfo", "vmstat"):
        for line in Path("/proc/" + name).read_text().splitlines():
            fields = line.replace(":", "").split()
            if fields[0] in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree", "pswpin", "pswpout"):
                values[fields[0]] = int(fields[1])
    values["cpu"] = list(map(int, Path("/proc/stat").read_text().splitlines()[0].split()[1:9]))
    values["monotonic_ns"] = time.monotonic_ns()
    values["loadavg"] = Path("/proc/loadavg").read_text().split()[:3]
    return values


def configurations(capacity, cpus):
    # Request size and region effects share the full-size 128 KiB cases.
    cases = [(rw, bs, capacity, 1) for rw in ("read", "write") for bs in (4096, 131072)]
    cases += [(rw, 131072, size, 1) for size in (capacity // 4, capacity // 2) for rw in ("read", "write")]
    cases += [(rw, 4096, capacity, 1) for rw in ("randread", "randwrite", "randrw")]
    cases += [(rw, 4096, capacity, jobs) for jobs in (2, 4) if jobs <= cpus for rw in ("randread", "randwrite")]
    return cases


def plan(directory, mode):
    snapshot = resources()
    source = (ROOT / "include/secureram_config.h").read_text()
    capacity = int(re.search(r"SECURERAM_DEFAULT_CAPACITY_MB\s+(\d+)U", source)[1])
    assert run(["findmnt", "-n", "-o", "FSTYPE", "--target", "/dev/shm"]).strip() == "tmpfs"
    fs = os.statvfs("/dev/shm")
    while capacity >= 4 and (capacity * MIB * 8 > snapshot["MemAvailable"] * 1024 // 4 or
                            capacity * MIB * 2 > fs.f_bavail * fs.f_frsize):
        capacity //= 2
    assert capacity >= 4, "insufficient memory for conservative campaign budget"
    assert snapshot["SwapTotal"] == snapshot["SwapFree"], "guest swap already used"
    params = dict(mode=mode, capacity_mib=capacity, trials=5 if mode == "full" else 3,
                  runtime_s=5 if mode == "full" else 2, ramp_s=1, cpus=os.cpu_count(),
                  ioengine="psync", iodepth=1, rwmixread=70, seed_base=10000,
                  configurations=configurations(capacity * MIB, os.cpu_count()))
    save(directory / "parameters.json", params)
    environment = dict(date_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       kernel=os.uname().release, architecture=os.uname().machine,
                       ubuntu=Path("/etc/os-release").read_text(), resources=snapshot,
                       cpu=run(["lscpu"]), fio=run(["fio", "--version"]).strip(),
                       python=sys.version, gcc=run(["gcc", "--version"]).splitlines()[0],
                       commit=run(["runuser", "-u", os.environ["SUDO_USER"], "--", "git", "rev-parse", "HEAD"]).strip(),
                       branch="m10-performance-evaluation", vcpus=os.cpu_count())
    save(directory / "environment.json", environment)
    print(f"Plan: {capacity} MiB, {len(params['configurations'])} configurations/target, {params['trials']} trials", flush=True)


def identity():
    return BASE["identity"]()


def disk_pattern(byte, verify=False):
    number, capacity = identity()
    fd = RAW["open_block"](number)
    try:
        payload = bytes([byte]) * MIB
        for offset in range(0, capacity, MIB):
            if not verify:
                RAW["write_exact"](fd, offset, payload)
            assert RAW["read_exact"](fd, offset, MIB) == payload, f"data mismatch at {offset}"
    finally:
        os.close(fd)


def fio_command(target, path, case, trial, params, output):
    rw, bs, region, jobs = case
    assert region % jobs == 0 and (region // jobs) % bs == 0
    assert target in ("secureram", "tmpfs")
    if target == "secureram":
        assert path == "/dev/secureram0"
    else:
        assert Path(path).parent.parent == Path("/dev/shm") and Path(path).name == "baseline"
    return ["fio", "--name=m10", f"--filename={path}", f"--rw={rw}", f"--bs={bs}",
            f"--size={region // jobs}", f"--offset_increment={region // jobs}", f"--numjobs={jobs}",
            "--ioengine=psync", "--iodepth=1", f"--direct={int(target == 'secureram')}",
            "--invalidate=0", "--allow_file_create=0", "--fallocate=none", "--time_based=1",
            f"--runtime={params['runtime_s']}", f"--ramp_time={params['ramp_s']}",
            "--rwmixread=70", f"--randseed={10000 + trial}", "--randrepeat=1",
            "--buffer_pattern=0x5a", "--scramble_buffers=0", "--refill_buffers=0",
            "--clocksource=clock_gettime", "--eta=never", "--output-format=json", f"--output={output}"]


def execute_fio(command, stderr_path):
    # Dedicated process group makes timeout/signals clean up fio workers too.
    with stderr_path.open("w") as errors:
        child = subprocess.Popen(command, stdout=errors, stderr=errors, start_new_session=True)
        try:
            code = child.wait(timeout=45)
            assert code == 0, f"fio failed ({code}); see {stderr_path}"
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()


def io(directory, params):
    _, capacity = identity()
    assert capacity == params["capacity_mib"] * MIB
    assert cli("status")["features"] == 31
    queue = Path("/sys/class/block/secureram0/queue")
    save(directory / "queue.json", {p: (queue / p).read_text().strip() for p in
                                  ("logical_block_size", "physical_block_size", "max_hw_sectors_kb", "nr_requests", "write_cache")})
    disk_pattern(0x5a)
    rawdir = directory / "fio"
    rawdir.mkdir()
    with tempfile.TemporaryDirectory(prefix="secureram-m10-", dir="/dev/shm") as temp:
        baseline = Path(temp) / "baseline"
        with baseline.open("xb") as stream:
            for _ in range(params["capacity_mib"]):
                stream.write(b"Z" * MIB)
        assert stat.S_ISREG(baseline.lstat().st_mode) and baseline.stat().st_size == capacity
        for trial in range(1, params["trials"] + 1):
            cases = list(params["configurations"])
            random.Random(700 + trial).shuffle(cases)
            for case in cases:
                rw, bs, region, jobs = case
                targets = ("secureram", "tmpfs") if trial % 2 else ("tmpfs", "secureram")
                for target in targets:
                    name = f"{target}-{rw}-{bs}-{region}-{jobs}-t{trial}"
                    path = "/dev/secureram0" if target == "secureram" else str(baseline)
                    identity()
                    before_stats = cli("stats") if target == "secureram" else None
                    before = resources()
                    command = fio_command(target, path, case, trial, params, rawdir / (name + ".json"))
                    meta = dict(target=target, rw=rw, bs=bs, region_bytes=region, jobs=jobs,
                                trial=trial, command=command, before=before, before_stats=before_stats,
                                status="STARTED")
                    save(rawdir / (name + ".meta.json"), meta)
                    execute_fio(command, rawdir / (name + ".stderr.txt"))
                    meta["after"] = resources()
                    result = json.loads((rawdir / (name + ".json")).read_text())
                    assert len(result["jobs"]) == jobs and all(j["error"] == 0 for j in result["jobs"])
                    assert all(sum(j[d]["io_bytes"] for d in ("read", "write")) > 0 for j in result["jobs"])
                    if target == "secureram":
                        after_stats = cli("stats")
                        meta["after_stats"] = after_stats
                        assert after_stats["integrity_failures"] == before_stats["integrity_failures"] == 0
                        for direction in ("read", "write"):
                            measured = sum(j[direction]["io_bytes"] for j in result["jobs"])
                            assert after_stats[direction + "_bytes"] - before_stats[direction + "_bytes"] >= measured
                        disk_pattern(0x5a, verify=True)
                    else:
                        with baseline.open("rb") as stream:
                            for _ in range(params["capacity_mib"]):
                                assert stream.read(MIB) == b"Z" * MIB
                    assert all(meta["after"][k] == before[k] for k in ("pswpin", "pswpout")), "swap contaminated trial"
                    meta["status"] = "PASS"
                    save(rawdir / (name + ".meta.json"), meta)
                    print("PASS " + name, flush=True)
    assert not Path(temp).exists(), "tmpfs resource cleanup failed"


def timed_ioctl(fd, command):
    header = struct.pack("=IIII", 1, 16, int(command == RAW["DESTROY"]), 0)
    start = time.monotonic_ns()
    fcntl.ioctl(fd, command, header)
    return (time.monotonic_ns() - start) / 1e6


def denied():
    RAW["expect_error"](lambda: os.open("/dev/secureram0", os.O_RDONLY | os.O_DIRECT), errno.ENOKEY)


def lifecycle(directory, params):
    _, capacity = identity()
    assert cli("status")["state"] == 0
    records = []
    output = directory / f"lifecycle-{capacity}.json"
    fd = os.open("/dev/secureramctl", os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for trial in range(1, params["trials"] + 1):
            old = cli("status")["generation"]
            denied()
            start = time.monotonic_ns()
            cli("load-random")
            load_ms = (time.monotonic_ns() - start) / 1e6
            assert cli("status")["generation"] == old + 1
            number, _ = identity()
            RAW["zero_scan"](number, capacity)
            disk_pattern(0x41)
            create_ms = timed_ioctl(fd, BASE["CREATE"])
            slot = cli("snapshot", "status")
            assert slot["data_bytes"] == capacity and slot["tag_bytes"] == capacity // 128
            disk_pattern(0x42)
            restore_ms = timed_ioctl(fd, BASE["RESTORE"])
            disk_pattern(0x41, verify=True)
            delete_ms = timed_ioctl(fd, BASE["DELETE"])
            assert not cli("snapshot", "status")["exists"]
            # Batch tiny lock/unlock calls to reduce timer granularity effects.
            start = time.monotonic_ns()
            for _ in range(100):
                fcntl.ioctl(fd, RAW["LOCK"], BASE["HEADER"])
                fcntl.ioctl(fd, RAW["UNLOCK"], BASE["HEADER"])
            lock_pair_ms = (time.monotonic_ns() - start) / 1e6 / 100
            timed_ioctl(fd, BASE["CREATE"])
            destroy_ms = timed_ioctl(fd, RAW["DESTROY"])
            denied()
            assert not cli("snapshot", "status")["exists"]
            cli("load-random")
            RAW["expect_error"](lambda: fcntl.ioctl(fd, BASE["RESTORE"], BASE["HEADER"]), errno.ENODATA)
            RAW["zero_scan"](number, capacity)
            timed_ioctl(fd, RAW["DESTROY"])
            assert cli("stats")["integrity_failures"] == 0
            records.append(dict(trial=trial, capacity_bytes=capacity, load_cli_ms=load_ms,
                                create_ms=create_ms, restore_ms=restore_ms, delete_ms=delete_ms,
                                destroy_with_snapshot_ms=destroy_ms, lock_unlock_pair_ms=lock_pair_ms,
                                status="PASS"))
            save(output, records)
            print(f"PASS lifecycle capacity={capacity} trial={trial}: exact A/B/A, zero/rekey/denial", flush=True)
    finally:
        os.close(fd)


def demo(directory):
    number, capacity = identity()
    cli("load-random")
    fd = RAW["open_block"](number)
    try:
        payload = (b"SecureRAM M10 recognizable plaintext demonstration. " * 100)[:4096]
        RAW["write_exact"](fd, 0, payload)
        assert RAW["read_exact"](fd, 0, 4096) == payload
    finally:
        os.close(fd)
    print("PASS confidentiality: successful recognizable write traversed M4 internal stored!=plain and stored==cipher comparisons; no bytes exported")
    cli("destroy")
    # Reuse all inherited bounded corruption, sentinel, latch and recovery assertions.
    original = sys.argv
    sys.argv = ["m5-integrity.py", "tamper"]
    try:
        RAW["main"](version="0.8.0", features=31, load_command=[CLI, "load-random"])
    finally:
        sys.argv = original
    print("PASS inherited M5 integrity demonstrations and generation recovery")
    save(directory / "security-demo.json", dict(confidentiality="PASS", integrity="PASS",
         snapshot="see repeated lifecycle exact full-device A/B/A", generation="see lifecycle zero-scan and ENODATA",
         component_isolation="SKIP: no safe existing encryption-only mode"))


def main():
    assert len(sys.argv) == 4 and sys.argv[1] in ("plan", "io", "lifecycle", "demo")
    assert os.geteuid() == 0 and "microsoft" not in os.uname().release.lower()
    assert os.environ.get("SR_MILESTONE") == "10", "use the M10 shell harness"
    directory = Path(sys.argv[2]).resolve()
    assert directory.parent == ROOT / ".cache/m10-benchmarks"
    mode = sys.argv[3]
    assert mode in ("quick", "full")
    def interrupted(signum, _frame):
        raise RuntimeError(f"campaign interrupted by signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    if sys.argv[1] == "plan":
        plan(directory, mode)
    elif sys.argv[1] == "demo":
        demo(directory)
    else:
        params = json.loads((directory / "parameters.json").read_text())
        assert params["mode"] == mode
        (io if sys.argv[1] == "io" else lifecycle)(directory, params)


if __name__ == "__main__":
    main()
