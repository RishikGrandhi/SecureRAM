#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Own one privileged dashboard process across all M7 VM module reloads.

Startup stdout is a pipe read only in memory. Never print or save its access URL.
Only the fixed test children inherit the HTTP credential via their environment.
"""
import os
from pathlib import Path
import re
import selectors
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def record(label, result, detail):
    assert result in ("PASS", "FAIL", "NOT RUN", "NOT COMPLETED")
    assert not any(char in label + detail for char in "\t\n")
    with open(os.environ["M5_STATUS_FILE"], "a", encoding="utf-8") as output:
        output.write(f"{label}\t{result}\t{detail}\n")


def read_startup(process):
    deadline = time.monotonic() + 8
    data = b""
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while data.count(b"\n") < 3:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise RuntimeError("dashboard startup timeout")
            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk or len(data) + len(chunk) > 4096:
                raise RuntimeError("dashboard startup failed")
            data += chunk
    match = re.fullmatch(rb"SecureRAM Dashboard 0\.8\.0\nListening only on 127\.0\.0\.1\n"
                         rb"Open: (http://127\.0\.0\.1:([0-9]+)/)#token=([A-Za-z0-9_-]{43})\n", data)
    if not match:
        raise RuntimeError("unexpected dashboard startup protocol")
    return match[1].decode().rstrip("/"), match[3].decode()


def assert_loopback(pid, port):
    """Inspect the owned process's listening socket, including IPv6 exclusion."""
    inodes = set()
    for entry in Path(f"/proc/{pid}/fd").iterdir():
        try:
            target = os.readlink(entry)
        except FileNotFoundError:
            continue
        if target.startswith("socket:["):
            inodes.add(target[8:-1])
    listeners = []
    for family in ("tcp", "tcp6"):
        for line in Path(f"/proc/{pid}/net/{family}").read_text().splitlines()[1:]:
            fields = line.split()
            if fields[3] == "0A" and fields[9] in inodes:
                listeners.append((family, fields[1]))
    assert listeners == [("tcp", f"0100007F:{port:04X}")], "dashboard must own exactly one IPv4 loopback listener"


def stop_server(process, port):
    if process.poll() is not None:
        raise RuntimeError("dashboard exited unexpectedly before shutdown")
    process.terminate()  # SIGTERM follows the same orderly close as Ctrl+C.
    try:
        result = process.wait(timeout=22)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        raise RuntimeError("dashboard required forced process cleanup") from None
    assert result == 0, "dashboard shutdown was not clean"
    if port is not None:
        with socket.socket() as probe:
            probe.settimeout(1)
            assert probe.connect_ex(("127.0.0.1", port)) != 0, "dashboard listener survived shutdown"


def run_session():
    server = None
    origin = token = None
    port = None
    success = False
    try:
        record("Dashboard startup", "NOT COMPLETED", "starting explicit privileged backend")
        # stderr contains only fixed diagnostics. stdout's URL must never enter logs.
        with open(Path(os.environ["M5_VM_RUN_DIR"]) / "dashboard-stderr.log", "wb") as diagnostics:
            server = subprocess.Popen([sys.executable, "-I", "-u", str(ROOT / "dashboard/server.py")],
                                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=diagnostics,
                                      cwd=ROOT, env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"})
            origin, token = read_startup(server)
            port = urlsplit(origin).port
            record("Dashboard startup", "PASS", "backend 0.8.0 started; credential retained only in memory")
            assert_loopback(server.pid, port)
            record("Loopback-only binding", "PASS", "owned /proc socket is exclusively 127.0.0.1")
            env = dict(os.environ, M7_ORIGIN=origin, M7_TOKEN=token)
            try:
                # Child shell owns all device cleanup; Popen context waits on unwind.
                profile = os.environ.get("SR_MILESTONE")
                script = {"9": "m9-vm-phases.sh", "8": "m8-vm-phases.sh"}.get(profile, "m7-vm-phases.sh")
                with subprocess.Popen(["bash", str(ROOT / "tests" / script)], cwd=ROOT, env=env,
                                      start_new_session=profile == "9") as phases:
                    try:
                        result = phases.wait(timeout=7200 if profile == "9" else None)
                    except (subprocess.TimeoutExpired, KeyboardInterrupt):
                        if profile == "9":
                            os.killpg(phases.pid, signal.SIGTERM)
                            try:
                                phases.wait(timeout=30)
                            except subprocess.TimeoutExpired:
                                os.killpg(phases.pid, signal.SIGKILL)
                        raise
                if result:
                    raise RuntimeError("M7 runtime phase failed; inspect retained phase logs")
            finally:
                env.pop("M7_TOKEN", None)
            success = True
    finally:
        cleanup = False
        try:
            if server is not None:
                try:
                    # Startup may fail before its port is known. Still bound the
                    # stop/reap path; never leave a privileged listener behind.
                    if port is not None or server.poll() is None:
                        stop_server(server, port)
                    cleanup = True
                finally:
                    if server.stdout is not None:
                        server.stdout.close()
        finally:
            origin = token = None
            record("Dashboard cleanup", "PASS" if cleanup else "FAIL",
                   "owned backend stopped; no key operation on shutdown" if cleanup else "backend cleanup incomplete")
            if not success:
                record("Final cleanup", "FAIL", "M7 session aborted; no runtime acceptance claimed")


def main():
    if sys.platform != "linux" or os.geteuid() != 0 or len(sys.argv) != 1:
        raise RuntimeError("run only through the explicitly privileged M7 VM harness")
    def interrupted(_signal, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        run_session()
    except (Exception, KeyboardInterrupt):
        # No exception interpolation: even an unexpected error cannot print a token.
        print("FAIL: M7 session or backend cleanup failed; inspect phase evidence", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
