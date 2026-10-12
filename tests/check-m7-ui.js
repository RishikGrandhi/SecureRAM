// SPDX-License-Identifier: GPL-2.0-only
"use strict";
const assert = require("node:assert/strict");
const {bytes, enabled, sample, parseStats} = require("../dashboard/static/app.js");
assert.equal(bytes("0"), "0 B");
assert.equal(bytes("67108864"), "64.00 MiB");
assert.equal(bytes("18446744073709551615"), "15.99 EiB");
assert.deepEqual(enabled(4, true, true, false), ["destroy"]);
assert.deepEqual(enabled(2, true, false, false), []);
assert.deepEqual(enabled(2, false, true, false), []);
assert.deepEqual(enabled(2, true, true, true), []);
assert.deepEqual(enabled(99, true, true, false), []);
assert.deepEqual(enabled(0, true, true, false), ["load-random"]);
assert.deepEqual(enabled(3, true, true, false), ["unlock", "destroy"]);
const raw = {read_requests:"1", write_requests:"2", read_bytes:"18446744073709551600", write_bytes:"4096", integrity_failures:"0"};
const before = parseStats(raw), after = {...before, read_bytes: before.read_bytes + 10n, write_bytes: before.write_bytes + 2048n};
assert.deepEqual(sample(before, after, 2000), {read:5, write:1024});
assert.equal(sample(before, after, 6000), null);
assert.equal(sample(before, {...after, read_requests:0n}, 1000), null);
assert.equal(sample(null, after, 1000), null);
for (const value of [123, "-1", "01", "18446744073709551616", "1.2", null]) {
  assert.throws(() => parseStats({...raw, read_bytes:value}));
}
console.log("PASS: UI exact u64 display, delta rates, stale/reset handling and lifecycle availability");
