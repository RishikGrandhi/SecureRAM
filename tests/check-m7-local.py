#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Dependency-free M7 checks. No root, device access, module load or package installs."""
from html.parser import HTMLParser
from pathlib import Path
import py_compile
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(command):
    subprocess.run(command, cwd=ROOT, check=True)


class StaticCheck(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.references = set()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            assert values["id"] not in self.ids, "duplicate HTML id"
            self.ids.add(values["id"])
        for name, value in attrs:
            assert not name.lower().startswith("on"), "inline event handler"
            assert name != "style", "inline style incompatible with CSP"
            if name in ("href", "src"):
                assert value in ("/", "/styles.css", "/app.js"), "external/unexpected asset"
            if name in ("for", "aria-labelledby"):
                self.references.update(value.split())


def main():
    for path in sorted(ROOT.glob("dashboard/**/*.py")) + sorted(ROOT.glob("tests/*.py")):
        py_compile.compile(str(path), doraise=True)
    print("PASS: all dashboard/test Python bytecode checks", flush=True)
    html = (ROOT / "dashboard/static/index.html").read_text(encoding="utf-8")
    parser = StaticCheck()
    parser.feed(html)
    assert parser.references <= parser.ids
    js = (ROOT / "dashboard/static/app.js").read_text(encoding="utf-8")
    assert set(re.findall(r'(?:el|text)\("([^"$]+)"', js)) <= parser.ids
    assert not re.search(r"innerHTML|localStorage|sessionStorage|document\.cookie|eval\(", js)
    assert "BigInt" in js and 'history.replaceState' in js
    for path in ROOT.glob("dashboard/static/*"):
        assert path.stat().st_size <= 262144
        assert not re.search(r"https?://|@import|url\(", path.read_text(encoding="utf-8")), "remote/unneeded runtime asset"
    print("PASS: static references, unique IDs, accessibility labels, CSP and offline asset integrity", flush=True)
    run([sys.executable, "tests/check-m7-dashboard.py"])
    node = shutil.which("node") or shutil.which("node.exe")
    if node:
        run([node, "--check", "dashboard/static/app.js"])
        run([node, "tests/check-m7-ui.js"])
    else:
        print("NOT RUN: Node syntax/UI helpers (no runtime found)", flush=True)
    if sys.platform == "linux":
        scripts = sorted(ROOT.glob("tests/*.sh")) + sorted(ROOT.glob("scripts/*.sh"))
        for path in scripts:
            run(["bash", "-n", str(path)])
        print(f"PASS: separate bash -n for each of {len(scripts)} shell scripts", flush=True)
        run(["bash", "tests/check-m7-vm-harness.sh"])
        if shutil.which("shellcheck"):
            run(["shellcheck", "-x", *map(str, scripts)])
        else:
            print("NOT RUN: ShellCheck not installed", flush=True)
    else:
        print("NOT RUN here: Linux harness/symlink tests; run this runner in WSL/Linux too", flush=True)
    run(["git", "diff", "--check"])
    print("PASS: M7 local checks; VM acceptance and real-device visual checks are separate", flush=True)


if __name__ == "__main__":
    main()
