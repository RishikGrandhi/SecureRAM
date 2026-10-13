#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Unprivileged, visibly labelled M8 UI fixture. No module or devices."""
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parent
fixture = runpy.run_path(str(ROOT / "check-m8-dashboard.py"))
preview = runpy.run_path(str(ROOT / "m7-preview.py"))
preview["main"].__globals__.update(FIXTURE=fixture, SERVER=fixture["SERVER"])
if __name__ == "__main__":
    preview["main"]()
