#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Execute the new phase functions with explicit mocks; no device/root operations.
set -Eeuo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly script_dir
source "$script_dir/m8-vm-phases.sh"
m5_die() { printf 'FAIL: %s\n' "$*" >&2; return 1; }
for bad_pin in '' 1234567 invalid; do
	if (M8_EXPECTED_COMMIT=$bad_pin; m8_assert_commit_pin) 2>/dev/null; then exit 1; fi
done
M8_EXPECTED_COMMIT=$(git rev-parse HEAD)
m8_assert_commit_pin
trace= loaded=0 suites=0 fail_suite=0
m5_begin_checks() { trace+="|begin $*"; }
m6_done() { trace+='|done'; }
m5_load_module() { [[ $loaded == 0 && $1 == 64 ]]; loaded=1; trace+='|load'; }
m5_identity_guard() { [[ $loaded == 1 && $1 == 67108864 ]]; trace+='|identity'; }
m5_unload_owned() { [[ $loaded == 1 ]]; loaded=0; trace+='|unload'; }
m8_snapshot_suite()
{
	[[ $loaded == 1 && ( $1 == production || $1 == tamper ) ]]
	[[ $fail_suite == 0 ]] || return 1
	suites=$((suites + 1)); trace+="|suite $1"
}
m7_cli()
{
	[[ $* == 'snapshot status --json' && $loaded == 1 ]]
	printf '%s\n' '{"exists":false,"state":0,"data_bytes":0,"tag_bytes":0,"generation":0,"created":0,"restored":0,"deleted":0,"failures":0}'
}
m8_snapshot
[[ $loaded == 0 && $suites == 1 ]]
[[ $trace == *'|suite production|done|begin Snapshot unload/reload|identity|unload|load|unload|done' ]]
m8_snapshot_tamper
[[ $loaded == 0 && $suites == 2 && $trace == *'|suite tamper|unload|done' ]]
# Errexit applies in the real standalone shell, not an if/function conditional.
export -f m5_begin_checks m6_done m5_load_module m5_identity_guard m5_unload_owned m8_snapshot_suite m7_cli m8_snapshot
if bash -ec 'loaded=0; suites=0; trace=; fail_suite=1; m8_snapshot; echo BAD-SUCCESS' >/dev/null; then
	m5_die 'snapshot phase failure was swallowed'
fi
printf '%s\n' 'PASS: M8 full-SHA gate, real phase ordering, unload/reload, latch phase and fail-fast behavior'
