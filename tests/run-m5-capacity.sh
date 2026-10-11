#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/m5-vm-common.sh"
m5_phase_preflight
[[ $# -eq 0 ]] || m5_die "run-m5-capacity.sh accepts no arguments"
trap 'm5_phase_exit $?' EXIT

m5_build_module capacity
m5_build_helper
m5_prove_production capacity-production
modprobe hkdf

for invalid in 0 257; do
	set +e
	output=$(insmod ./secureram.ko "capacity_mb=$invalid" 2>&1)
	result=$?
	set -e
	printf '%s\n' "$output"
	if [[ $result -eq 0 || -e /sys/module/secureram ]]; then
		M5_RUNTIME_OWNED=1
		m5_die "invalid capacity_mb=$invalid unexpectedly loaded"
	fi
	grep -Eq 'Invalid (parameters|argument)' <<< "$output" ||
		m5_die "capacity_mb=$invalid failed without EINVAL"
	m5_assert_module_absent
	printf 'PASS: capacity_mb=%d rejected without published module/device\n' "$invalid"
done

for capacity_mb in 1 256; do
	current_capacity_bytes=$(m5_capacity_bytes_from_mb "$capacity_mb")
	if [[ $capacity_mb -eq 1 ]]; then
		m5_begin_checks '1 MiB capacity'
	else
		m5_begin_checks '256 MiB capacity'
	fi
	m5_load_module "$capacity_mb"
	m5_assert_query 0 0 "$current_capacity_bytes"
	m5_load_key "$current_capacity_bytes"
	m5_assert_query 2 1 "$current_capacity_bytes"
	m5_run_raw "$current_capacity_bytes" active
	m5_destroy_key "$current_capacity_bytes"
	m5_assert_query 0 1 "$current_capacity_bytes"
	m5_unload_owned
	if [[ $capacity_mb -eq 1 ]]; then
		m5_record '1 MiB capacity' PASS 'exact capacity, generation 1, full bounded raw suite, teardown'
	else
		m5_record '256 MiB capacity' PASS 'exact capacity, generation 1, full bounded raw suite, teardown'
	fi
	m5_complete_checks
done

trap - EXIT

