// SPDX-License-Identifier: GPL-2.0-only
"use strict";
const assert = require("node:assert/strict");
const {snapshotEnabled} = require("../dashboard/static/app.js");
assert.deepEqual(snapshotEnabled(2, 31, true, false, {state:2, exists:false}), ["snapshot-create"]);
assert.deepEqual(snapshotEnabled(2, 31, true, false, {state:2, exists:true}), ["snapshot-restore", "snapshot-delete"]);
for (const state of [0, 3, 4]) {
  assert.deepEqual(snapshotEnabled(state, 31, true, false, {state, exists:true}), ["snapshot-delete"]);
  assert.deepEqual(snapshotEnabled(state, 31, true, false, {state, exists:false}), []);
}
for (const args of [[2, 15, true, false], [2, 31, false, false], [2, 31, true, true], [1, 31, true, false], [99, 31, true, false]]) {
  assert.deepEqual(snapshotEnabled(...args, {state:2, exists:true}), []);
}
assert.deepEqual(snapshotEnabled(2, 31, true, false, {state:3, exists:true}), []);
assert.deepEqual(snapshotEnabled(2, 31, true, false, null), []);
console.log("PASS: snapshot UI state, feature, stale, busy and mismatched observation gating");
