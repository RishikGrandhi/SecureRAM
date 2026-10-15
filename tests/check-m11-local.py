#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Non-root M11 integration checks; never load or access a device."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*command):
    subprocess.run(command, cwd=ROOT, check=True)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def check_contracts():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("build:", "check-runtime:", "check-production:", "load:", "status:", "unload:"):
        require(target in makefile, f"missing Make target {target}")

    lifecycle = (ROOT / "scripts/secureram-lifecycle.sh").read_text(encoding="utf-8")
    demo = (ROOT / "scripts/demo-secureram.sh").read_text(encoding="utf-8")
    acceptance = (ROOT / "tests/run-m11-final-acceptance.sh").read_text(encoding="utf-8")
    require("/dev/secureram0" in lifecycle and "CAPACITY_MB" in lifecycle,
            "lifecycle lacks fixed device/capacity guard")
    require("/dev/secureram0" in demo and "--quick" in demo and "--full" in demo,
            "demo mode or fixed-device contract missing")
    require("git worktree add --detach" in acceptance and "M11_EXPECTED_COMMIT" in acceptance,
            "acceptance lacks exact-commit clean-worktree contract")
    require("run-m9-vm-acceptance" not in acceptance and "run-m10-benchmarks" not in acceptance,
            "M11 must not embed expensive M9/M10 campaigns")

    production_diff = subprocess.run(
        ["git", "diff", "9903097", "--", "src", "include", "Kbuild"],
        cwd=ROOT, check=True, stdout=subprocess.PIPE, text=True,
    ).stdout
    require(not production_diff, "M11 unexpectedly changes production kernel/UAPI/Kbuild code")

    kernel_sources = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src").glob("*.c"))
    suspicious = re.compile(r"pr_(?:info|err|warn)\([^\n]*(?:key material|key bytes|plaintext bytes)", re.I)
    require(not suspicious.search(kernel_sources), "possible secret/plaintext logging added")


def check_markdown_links():
    for path in [ROOT / "README.md", *(ROOT / "docs").glob("*.md")]:
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
            if target.startswith(("http://", "https://", "#")):
                continue
            local = target.split("#", 1)[0]
            if local:
                require((path.parent / local).resolve().exists(), f"broken link in {path}: {target}")


def main():
    if sys.platform != "linux":
        raise RuntimeError("run M11 local checks in Linux/WSL")
    shell_files = [
        "scripts/check-environment.sh",
        "scripts/check-production-build.sh",
        "scripts/secureram-lifecycle.sh",
        "scripts/demo-secureram.sh",
        "tests/m11-vm-phases.sh",
        "tests/run-m11-final-acceptance.sh",
    ]
    for shell_file in shell_files:
        run("bash", "-n", shell_file)
    run(sys.executable, "-m", "py_compile", "tests/check-m11-local.py", "tests/m11-demo-integrity.py")
    run(sys.executable, "tests/check-m10-local.py")
    run(sys.executable, "tests/check-m7-dashboard.py")
    run(sys.executable, "tests/check-m8-dashboard.py")
    run("bash", "scripts/demo-secureram.sh", "--help")
    run("git", "diff", "--check")
    check_contracts()
    check_markdown_links()
    print("PASS: M11 syntax, integration contracts, dashboard regressions, links and production-code boundary")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1) from error
