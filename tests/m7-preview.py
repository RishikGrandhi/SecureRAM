#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""NON-PRIVILEGED UI test fixture. Never calls the real CLI or opens devices.

This is deliberately separate from the production server's entry point and has
an unavoidable visible fixture banner. For local browser QA only, not VM acceptance.
"""
import argparse
import os
from pathlib import Path
import runpy
import signal
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = runpy.run_path(str(ROOT / "tests/check-m7-dashboard.py"))
SERVER = FIXTURE["SERVER"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=int, choices=(0, 2, 3, 4), default=0)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        parser.error("fixture must run unprivileged")
    fixture = FIXTURE["FakeCLI"]()
    fixture.state = args.state
    fixture.generation = 0 if args.state == 0 else 1
    with patch.object(SERVER, "CLI", Path(__file__).resolve()), patch.object(SERVER.subprocess, "run", fixture.run):
        server = SERVER.DashboardServer(args.port)
        content, mime = server.assets["/"]
        content = content.replace(b"<main>", b'<main><p class="notice"><b>UI TEST FIXTURE</b> - synthetic observations; no kernel or device access.</p>')
        server.assets["/"] = content, mime
        def stop(_signal, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        print(f"UI fixture only: {server.origin}/#token={server.token}", flush=True)
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    sys.exit(main())
