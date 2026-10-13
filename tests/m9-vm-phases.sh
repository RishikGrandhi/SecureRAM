#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Definitions only when sourced by tests. The session owner runs this directly.
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
	set -Eeuo pipefail
	script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
	readonly script_dir
	export SR_MILESTONE=9
	source "$script_dir/m5-vm-common.sh"
	source "$script_dir/m6-vm-phases.sh"
	source "$script_dir/m7-vm-phases.sh"
	source "$script_dir/m8-vm-phases.sh"
fi

m9_parameters()
{
	[[ ${M9_EXPECTED_COMMIT:-} =~ ^[0-9a-f]{40}$ ]] || {
		m5_die 'M9_EXPECTED_COMMIT must be the full reviewed commit'; return 1;
	}
	case ${M9_MODE:-quick} in
		quick) : "${M9_IO_ROUNDS:=32}" "${M9_CYCLES:=12}" "${M9_RELOADS:=10}" ;;
		extended) : "${M9_IO_ROUNDS:=256}" "${M9_CYCLES:=100}" "${M9_RELOADS:=50}" ;;
		*) m5_die 'M9_MODE must be quick or extended'; return 1 ;;
	esac
	local value
	for value in "$M9_IO_ROUNDS" "$M9_CYCLES" "$M9_RELOADS"; do
		[[ $value =~ ^[1-9][0-9]{0,3}$ ]] && ((value <= 2048)) || {
			m5_die 'M9 iterations must be integers in 1..2048'; return 1;
		}
	done
	export M9_IO_ROUNDS M9_CYCLES M9_RELOADS
}

m9_suite()
{
	timeout --signal=TERM --kill-after=15s 1200s python3 "$M5_ROOT/tests/m9-stress.py" "$1"
}

m9_stress()
{
	local phase label
	m5_load_module 8
	for phase in io races snapshots keys invalid; do
		case $phase in
			io) label='Concurrent I/O and busy controls' ;;
			races) label='Control-plane races' ;;
			snapshots) label='Snapshot stress' ;;
			keys) label='Key lifecycle stress' ;;
			invalid) label='Invalid UAPI' ;;
		esac
		m5_begin_checks "$label"
		m5_identity_guard 8388608
		m9_suite "$phase"
		m6_done
	done
	m5_unload_owned
}

m9_faults()
{
	m5_begin_checks 'Fault handling'
	m5_build_module m9-fault M9_TEST=1
	nm secureram.ko > "$M5_VM_RUN_DIR/fault-nm.log"
	grep -q 'secureram_fault_pending' "$M5_VM_RUN_DIR/fault-nm.log"
	# Failed init must publish neither device nor control objects. insmod errno
	# is rendered by kmod; live ioctl failures below assert exact numeric errno.
	local site output result
	modprobe hkdf
	for site in 1 2; do
		result=0
		output=$(insmod ./secureram.ko capacity_mb=8 "m9_fault=$site" 2>&1) || result=$?
		if [[ $result -eq 0 || -e /sys/module/secureram ]]; then
			M5_RUNTIME_OWNED=1
			m5_die 'injected store allocation failure unexpectedly loaded module'
		fi
		[[ $output == *'Cannot allocate memory'* ]]
		m5_assert_module_absent
	done
	m5_load_module 8
	m9_suite faults
	m5_unload_owned
	m6_done
}

m9_reload()
{
	m5_begin_checks 'Load/unload stress'
	m5_build_module m9-reload
	m5_prove_production m9-reload
	local cycle
	for ((cycle=1; cycle<=M9_RELOADS; cycle++)); do
		m5_load_module 1
		[[ ! -e /sys/module/secureram/parameters/m9_fault ]]
		m7_cli snapshot status --json | python3 -c 'import json,sys; s=json.load(sys.stdin); assert not s["exists"]; assert all(s[k] == 0 for k in ("state","data_bytes","tag_bytes","generation","created","restored","deleted","failures"))'
		m9_suite reload
		# Alternate explicit key cleanup with exit-owned populated-slot cleanup.
		if ((cycle % 2 == 0)); then m5_destroy_key 1048576; fi
		m5_unload_owned
		m5_assert_module_absent
		printf 'PASS: load/use/unload cycle %d/%d\n' "$cycle" "$M9_RELOADS"
	done
	m6_done
}

m9_run_phase()
(
	set -Eeuo pipefail
	trap 'm5_phase_exit $?' EXIT
	trap 'exit 124' TERM INT
	m5_phase_preflight
	"$@"
)

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
	[[ $# -eq 0 && -n ${M7_ORIGIN:-} && -n ${M7_TOKEN:-} ]] || m5_die 'run through M9 session owner'
	m9_parameters
	m9_run_phase m7_production 2>&1 | tee "$M5_VM_RUN_DIR/production.log"
	m9_run_phase m8_snapshot 2>&1 | tee "$M5_VM_RUN_DIR/snapshot.log"
	m9_run_phase m9_stress 2>&1 | tee "$M5_VM_RUN_DIR/stress.log"
	m9_run_phase m7_tamper 2>&1 | tee "$M5_VM_RUN_DIR/tamper.log"
	m9_run_phase m8_snapshot_tamper 2>&1 | tee "$M5_VM_RUN_DIR/snapshot-tamper.log"
	m5_record 'Integrity corruption' PASS 'inherited ciphertext/tag/relocation/latch/snapshot checks passed'
	m9_run_phase m9_faults 2>&1 | tee "$M5_VM_RUN_DIR/faults.log"
	m9_run_phase m9_reload 2>&1 | tee "$M5_VM_RUN_DIR/reload.log"
	m9_run_phase m6_capacity 2>&1 | tee "$M5_VM_RUN_DIR/capacity.log"
	m9_run_phase m6_final 2>&1 | tee "$M5_VM_RUN_DIR/final-production.log"
	m5_record 'Existing regressions' PASS 'all inherited M6/M7/M8 runtime phases passed'
fi
