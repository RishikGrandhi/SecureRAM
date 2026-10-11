#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Sourced functions: no device operation happens merely by reading this file.

m6_assert_commit_pin()
{
	[[ ${M6_EXPECTED_COMMIT:-} =~ ^[0-9a-f]{40}$ ]] || {
		m5_die 'M6_EXPECTED_COMMIT must be the full reviewed git rev-parse HEAD value'
		return 1
	}
}

m6_cli()
{
	m5_management "$@"
}

m6_observe()
{
	python3 "$M5_ROOT/tests/m6-observe.py" "$@"
}

m6_done()
{
	local check_label
	for check_label in "${M5_ACTIVE_CHECKS[@]}"; do
		m5_record "$check_label" PASS 'all assertions completed'
	done
	m5_complete_checks
}

m6_expect_busy()
{
	local cli_command=$1 cli_output cli_result=0
	cli_output=$(m6_cli "$cli_command" 2>&1) || cli_result=$?
	printf '%s\n' "$cli_output"
	[[ $cli_result -eq 1 && $cli_output == *'Device or resource busy'* ]] ||
		m5_die "CLI $cli_command did not reject with EBUSY/exit 1"
}

# Reuse the real ext4 flow; exercise the production CLI while mounted as well.
m5_assert_mounted_transitions_busy()
{
	local mounted_bytes=$1 cli_command
	m5_control busy
	for cli_command in load-random lock unlock destroy; do
		m6_expect_busy "$cli_command"
	done
	m6_observe status 2 2 "$mounted_bytes"
	m6_cli stats --json
}

m6_production()
{
	local production_bytes
	production_bytes=$(m5_capacity_bytes_from_mb 64)
	M5_MOUNT_POINT="$M5_VM_RUN_DIR/production-mount"
	m5_run_as_builder mkdir -- "$M5_MOUNT_POINT"
	m5_register_ephemeral_dir "$M5_MOUNT_POINT"
	m5_begin_checks 'Production build' 'CLI build'
	m5_build_module production
	m5_prove_production production
	m5_build_helper
	m5_run_as_builder make tools-clean
	m5_run_as_builder make tools
	m6_done
	m5_begin_checks 'CLI help/version'
	m6_cli help
	[[ $(m6_cli version) == 'secureramctl 0.6.0 (ABI 1)' ]]
	m6_done
	m5_begin_checks 'Version/features' 'Human status' 'JSON status' 'Stats baseline'
	m5_load_module 64
	m5_assert_query 0 0 "$production_bytes"
	m6_observe status 0 0 "$production_bytes"
	python3 tests/m6-integrity.py production
	m5_run_raw "$production_bytes" denied
	m5_control negative
	m6_expect_busy lock
	m6_expect_busy unlock
	m6_observe baseline
	m6_done
	m5_begin_checks 'Random key load'
	m5_load_key "$production_bytes"
	m6_observe status 2 1 "$production_bytes"
	# Initialization cannot produce WRITE requests, even if udev probes with READ.
	m6_cli stats --json | python3 -c 'import json,sys; s=json.load(sys.stdin); assert s["write_requests"] == s["write_bytes"] == s["integrity_failures"] == 0'
	m6_done
	m5_begin_checks 'Raw I/O' 'Stats accounting'
	m6_observe save "$M5_VM_RUN_DIR/before-raw.json"
	m5_run_raw "$production_bytes" active
	m6_observe increased "$M5_VM_RUN_DIR/before-raw.json"
	m6_observe accounting
	m6_done
	m5_begin_checks 'Lock/unlock'
	m5_identity_guard "$production_bytes"
	m6_expect_busy load-random
	dd if=/dev/secureram0 of="$M5_VM_RUN_DIR/lock-before.bin" bs=4096 count=16 iflag=direct status=none
	m5_register_ephemeral_file "$M5_VM_RUN_DIR/lock-before.bin"
	m5_register_ephemeral_file "$M5_VM_RUN_DIR/lock-after.bin"
	m6_observe save "$M5_VM_RUN_DIR/before-lock.json"
	m6_cli lock
	m6_observe status 3 1 "$production_bytes"
	m5_run_raw "$production_bytes" denied
	m6_expect_busy load-random
	m6_expect_busy lock
	m6_observe equal "$M5_VM_RUN_DIR/before-lock.json"
	m6_cli unlock
	m6_observe status 2 1 "$production_bytes"
	m5_identity_guard "$production_bytes"
	dd if=/dev/secureram0 of="$M5_VM_RUN_DIR/lock-after.bin" bs=4096 count=16 iflag=direct status=none
	cmp "$M5_VM_RUN_DIR/lock-before.bin" "$M5_VM_RUN_DIR/lock-after.bin"
	m6_done
	m5_begin_checks 'Destroy/rekey'
	m6_observe save "$M5_VM_RUN_DIR/before-destroy.json"
	m5_destroy_key "$production_bytes"
	m6_observe status 0 1 "$production_bytes"
	m6_observe equal "$M5_VM_RUN_DIR/before-destroy.json"
	m5_destroy_key "$production_bytes"
	m6_observe equal "$M5_VM_RUN_DIR/before-destroy.json"
	m5_load_key "$production_bytes"
	m6_observe status 2 2 "$production_bytes"
	m6_observe retained "$M5_VM_RUN_DIR/before-destroy.json"
	m5_run_raw "$production_bytes" active
	m6_done
	m5_begin_checks 'ext4' 'Mounted busy rejection'
	m5_run_production_ext4 "$production_bytes" "$M5_MOUNT_POINT"
	m6_done
	m5_destroy_key "$production_bytes"
	m5_unload_owned
}

m6_tamper()
{
	m5_begin_checks 'Integrity-failure observability' 'Tamper regression' 'Recovery'
	m5_build_module tamper M5_TEST=1 M4_TEST=1
	m5_prove_test_build
	m5_load_module 64
	m6_observe baseline
	m5_identity_guard 67108864
	python3 tests/m6-integrity.py tamper
	m6_observe status 0 6 67108864
	m6_cli stats --json | python3 -c 'import json,sys; assert json.load(sys.stdin)["integrity_failures"] == 3'
	m5_destroy_key 67108864
	m5_unload_owned
	m6_done
}

m6_capacity()
{
	local capacity_mb current_bytes invalid output result
	m5_begin_checks 'Capacity parameter rejection'
	m5_build_module capacity
	m5_prove_production capacity
	modprobe hkdf
	for invalid in 0 257; do
		result=0
		output=$(insmod ./secureram.ko "capacity_mb=$invalid" 2>&1) || result=$?
		if [[ $result -eq 0 || -e /sys/module/secureram ]]; then
			M5_RUNTIME_OWNED=1
			m5_die "invalid capacity $invalid unexpectedly loaded"
		fi
		[[ $output == *'Invalid parameters'* || $output == *'Invalid argument'* ]]
		m5_assert_module_absent
	done
	m6_done
	for capacity_mb in 1 256; do
		current_bytes=$(m5_capacity_bytes_from_mb "$capacity_mb")
		m5_begin_checks "$capacity_mb MiB capacity"
		m5_load_module "$capacity_mb"
		m6_observe status 0 0 "$current_bytes"
		m6_observe baseline
		m5_load_key "$current_bytes"
		m6_observe status 2 1 "$current_bytes"
		m5_run_raw "$current_bytes" active
		m6_observe accounting
		m5_destroy_key "$current_bytes"
		m5_unload_owned
		m6_done
	done
}

m6_final()
{
	m5_begin_checks 'Final production regression'
	m5_build_module final-production
	m5_prove_production final-production
	m5_load_module 64
	m6_observe baseline
	python3 tests/m6-integrity.py production
	m5_load_key 67108864
	m6_observe status 2 1 67108864
	m5_run_raw 67108864 active
	m6_observe accounting
	# ext4 helper expects generation 2 for its mounted transition assertions.
	m5_destroy_key 67108864
	m5_load_key 67108864
	M5_MOUNT_POINT="$M5_VM_RUN_DIR/final-mount"
	m5_run_as_builder mkdir -- "$M5_MOUNT_POINT"
	m5_register_ephemeral_dir "$M5_MOUNT_POINT"
	m5_run_production_ext4 67108864 "$M5_MOUNT_POINT"
	m6_done
	m5_begin_checks 'Final cleanup'
	m5_destroy_key 67108864
	m6_observe status 0 2 67108864
	m5_run_raw 67108864 denied
	m5_unload_owned
	m5_assert_module_absent
	m6_done
}

m6_run_phase()
(
	set -Eeuo pipefail
	trap 'm5_phase_exit $?' EXIT
	m5_phase_preflight
	"$@"
)
