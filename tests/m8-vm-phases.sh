#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Definitions are safe to source; direct execution is by the session owner only.
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
	set -Eeuo pipefail
	script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
	readonly script_dir
	export SR_MILESTONE=8
	source "$script_dir/m5-vm-common.sh"
	source "$script_dir/m6-vm-phases.sh"
	source "$script_dir/m7-vm-phases.sh"
fi

m8_assert_commit_pin()
{
	[[ ${M8_EXPECTED_COMMIT:-} =~ ^[0-9a-f]{40}$ ]] || {
		m5_die 'M8_EXPECTED_COMMIT must be the full reviewed git rev-parse HEAD value'
		return 1
	}
}

m8_snapshot_suite()
{
	python3 "$M5_ROOT/tests/m8-snapshot.py" "$@"
}

m8_snapshot()
{
	# Production from the preceding m7_production phase has already been proved.
	m5_begin_checks 'Snapshot rollback/lifecycle/UAPI' 'Snapshot HTTP'
	m5_load_module 64
	m5_identity_guard 67108864
	m8_snapshot_suite production
	m6_done
	m5_begin_checks 'Snapshot unload/reload'
	m5_identity_guard 67108864
	# The test deliberately left ACTIVE and a populated slot; unload must clear it.
	m5_unload_owned
	m5_load_module 64
	m7_cli snapshot status --json | python3 -c 'import json,sys; s=json.load(sys.stdin); assert not s["exists"]; assert all(s[k] == 0 for k in ("state","data_bytes","tag_bytes","generation","created","restored","deleted","failures"))'
	m5_unload_owned
	m6_done
}

m8_snapshot_tamper()
{
	# Combined test build from m7_tamper; no new production corruption hook.
	m5_begin_checks 'Snapshot integrity latch'
	m5_load_module 64
	m5_identity_guard 67108864
	m8_snapshot_suite tamper
	m5_unload_owned
	m6_done
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
	[[ $# -eq 0 ]] || m5_die 'no phase arguments accepted'
	[[ -n ${M7_ORIGIN:-} && -n ${M7_TOKEN:-} ]] || m5_die 'run through the session owner'
	m8_assert_commit_pin
	m6_run_phase m7_production 2>&1 | tee "$M5_VM_RUN_DIR/production.log"
	m6_run_phase m8_snapshot 2>&1 | tee "$M5_VM_RUN_DIR/snapshot.log"
	m6_run_phase m7_tamper 2>&1 | tee "$M5_VM_RUN_DIR/tamper.log"
	m6_run_phase m8_snapshot_tamper 2>&1 | tee "$M5_VM_RUN_DIR/snapshot-tamper.log"
	m6_run_phase m6_capacity 2>&1 | tee "$M5_VM_RUN_DIR/capacity.log"
	m6_run_phase m6_final 2>&1 | tee "$M5_VM_RUN_DIR/final-production.log"
fi
