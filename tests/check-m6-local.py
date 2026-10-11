#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reproducible compile/static/mocked checks. Never loads or accesses a device."""
import argparse
from pathlib import Path
import py_compile
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(label, command):
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    (ROOT / f"build-m6-{label}.log").write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(f"{label} failed ({result.returncode}):\n{result.stdout}")
    print(f"PASS: {label}", flush=True)
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kdir", type=Path, required=True)
    parser.add_argument("--checkpatch", type=Path, required=True)
    args = parser.parse_args()
    target = args.kdir.resolve()
    (ROOT / ".cache").mkdir(exist_ok=True)
    make = ["make", f"KDIR={target}", "CC=gcc"]
    run("environment", make + ["check-env"])
    for variant, flags in (("combined", ["M5_TEST=1", "M4_TEST=1"]),
                           ("test", ["M5_TEST=1"]), ("production", [])):
        run(f"{variant}-clean", make + ["clean"])
        build = run(variant, make + ["W=1", *flags])
        assert "MODPOST" in build and "secureram.ko" in build
        assert not re.search(r"(?m)^(?:.*/)?(?:src|include)/.*(?:warning:|error:)", build)
        symbols = run(f"{variant}-nm", ["nm", "secureram.ko"])
        strings = run(f"{variant}-strings", ["strings", "secureram.ko"])
        assembly = run(f"{variant}-dispatch", ["objdump", "-dr", "src/secureram_control.o"])
        run(f"{variant}-preprocess", ["make", "-C", str(target), f"M={ROOT}",
                                     "CC=gcc", "W=1", *flags, "src/secureram_control.i"])
        preprocessed = (ROOT / "src/secureram_control.i").read_text()
        (ROOT / f"build-m6-{variant}-control.i.log").write_text(preprocessed)
        (ROOT / "src/secureram_control.i").unlink()
        assert ("secureram_block_tamper" in symbols) == bool(flags)
        assert ("secureram_block_tamper" in preprocessed) == bool(flags)
        assert ("4028b770" in assembly) == bool(flags)
        assert "8050b705" in assembly  # Positive evidence for the new dispatch.
        assert ("M5 test: unit and generation binding PASS" in strings) == bool(flags)
        assert ("M4 test:" in strings) == ("M4_TEST=1" in flags)
        if not flags:
            assert not re.search(r"tamper|secureram_test_binding", symbols)
            assert not re.search(r"M[456] test|secureram_.*tamper|SECURERAM_IOC_TAMPER", strings)
    info = run("modinfo", ["/usr/sbin/modinfo", "secureram.ko"])
    assert re.search(r"version:\s+0.6.0", info) and re.search(r"depends:\s+hkdf", info)
    imports = run("imports", ["nm", "-u", "secureram.ko"])
    exported = {line.split()[1] for line in (target / "Module.symvers").read_text().splitlines()}
    assert {line.split()[-1] for line in imports.splitlines()} <= exported
    block = run("block-imports", ["nm", "-u", "src/secureram_block.o"])
    assert not re.search(r"U (crypto_|hkdf_|secureram_store_)", block)
    run("cli", ["python3", "tests/check-m6-cli.py"])
    cc = ["gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Iinclude"]
    run("m4-helper", cc + ["tests/m4-control.c", "-o", ".cache/m4-control"])
    for bits in (32, 64):
        for test in (False, True):
            flags = ["-DSECURERAM_M5_TEST"] if test else []
            if bits == 32:
                flags += ["-I/usr/include/x86_64-linux-gnu"]
            run(f"abi-{bits}-{test}", cc + [f"-m{bits}", *flags, "-c", "tests/abi-layout.c",
                                           "-o", f".cache/m6-abi-{bits}-{test}.o"])
    kernel = [str(p.relative_to(ROOT)) for pattern in ("src/*.c", "include/*.h", "include/uapi/*.h")
              for p in sorted(ROOT.glob(pattern))]
    checker = ["perl", str(args.checkpatch), "--no-tree", "--strict"]
    existing_caches = set(ROOT.glob(".checkpatch-camelcase.*"))
    try:
        run("checkpatch", checker + ["--file", *kernel, "tools/secureramctl.c", "tests/m4-control.c"])
        run("abi-checkpatch", checker + ["--ignore", "CAMELCASE", "--file", "tests/abi-layout.c"])
    finally:
        for cache in set(ROOT.glob(".checkpatch-camelcase.*")) - existing_caches:
            cache.unlink()
    for path in sorted((ROOT / "tests").glob("*.py")):
        py_compile.compile(str(path), doraise=True)
    print("PASS: all Python bytecode checks", flush=True)
    shell_files = sorted(ROOT.glob("tests/*.sh")) + sorted(ROOT.glob("scripts/*.sh"))
    for index, path in enumerate(shell_files):
        run(f"shell-{index}-{path.stem}", ["bash", "-n", str(path)])
    run("harness-selftest", ["bash", "tests/check-m6-vm-harness.sh"])
    if shutil.which("shellcheck"):
        run("shellcheck", ["shellcheck", "-x", *map(str, shell_files)])
    else:
        print("NOT RUN: ShellCheck is not installed (no packages installed)", flush=True)
    run("diff-check", ["git", "diff", "--check"])
    print("PASS: local verification; VM/runtime acceptance remains NOT RUN", flush=True)


if __name__ == "__main__":
    main()
