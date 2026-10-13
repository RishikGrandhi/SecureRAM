#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build the actual two C modules with narrow userspace shims; no device access."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SHIM = ROOT / ".cache/m8-shim/linux"
SHIM.mkdir(parents=True, exist_ok=True)
headers = {
    "types.h": "#include <stdbool.h>\n#include <stddef.h>\n#include <stdint.h>\n#include_next <linux/types.h>\ntypedef uint8_t u8;\ntypedef uint32_t u32;\ntypedef uint64_t u64;\n",
    "limits.h": "#include <stdint.h>\n#define U64_MAX UINT64_MAX\n",
    "string.h": "#include <string.h>\n#define memzero_explicit(p, n) explicit_bzero(p, n)\n",
    "vmalloc.h": "#include <stddef.h>\nvoid *vzalloc(size_t);\nvoid vfree(const void *);\n",
    "sched.h": "#define cond_resched() ((void)0)\n",
}
for name, content in headers.items():
    (SHIM / name).write_text(content)
subprocess.run(["gcc", "-std=c11", "-D_DEFAULT_SOURCE", "-g", "-O1", "-Wall", "-Wextra",
                "-Werror", "-Wconversion", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                "-I" + str(SHIM.parent), "-Iinclude", "tests/m8-core.c",
                "src/secureram_store.c", "src/secureram_snapshot.c", "-o", ".cache/m8-core"],
               cwd=ROOT, check=True)
subprocess.run([str(ROOT / ".cache/m8-core")], cwd=ROOT, check=True)
