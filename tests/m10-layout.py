#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read structure sizes from the current production module's DWARF (no device access)."""
import json, re, subprocess
text = subprocess.check_output(['readelf', '--debug-dump=info', 'secureram.ko'], text=True)
wanted = {'secureram_device', 'secureram_request', 'secureram_security', 'secureram_store', 'secureram_snapshot', 'secureram_stats', 'secureram_control', 'shash_desc', 'skcipher_request'}
sizes = {}
for block in re.split(r'(?m)^\s*<\d+><[0-9a-f]+>:', text):
    if 'DW_TAG_structure_type)' not in block:
        continue
    name = re.search(r'DW_AT_name\s*:\s*(?:.*:\s*)?(\w+)\s*\n', block)
    size = re.search(r'DW_AT_byte_size\s*:\s*(\d+)', block)
    if name and name[1] in wanted and size:
        value = int(size[1])
        assert name[1] not in sizes or sizes[name[1]] == value
        sizes[name[1]] = value
assert wanted <= sizes.keys(), (wanted - sizes.keys())
print(json.dumps({'source':'final production secureram.ko DWARF; sizeof payload only, not allocator overhead', 'bytes':sizes}, indent=2))