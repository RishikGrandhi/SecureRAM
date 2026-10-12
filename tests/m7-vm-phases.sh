#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Source after M5 common and M6 phases; direct execution is only by the session owner.
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
	set -Eeuo pipefail
	script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
	readonly script_dir
	SR_MILESTONE=7
	source "$script_dir/m5-vm-common.sh"
	source "$script_dir/m6-vm-phases.sh"
fi

m7_assert_commit_pin()
{
	[[ ${M7_EXPECTED_COMMIT:-} =~ ^[0-9a-f]{40}$ ]] || {
		m5_die 'M7_EXPECTED_COMMIT must be the full reviewed git rev-parse HEAD value'
		return 1
	}
}

m7_http()
{
	python3 "$M5_ROOT/tests/m7-http.py" "$@"
}

m7_cli()
{
	"$M5_ROOT/tools/secureramctl" "$@"
}

# Reuse every M6 phase and its identity checks, route lifecycle through HTTP.
# Metadata/help/version still exercise the real production CLI independently.
m5_management()
{
	case $1 in
		load-random|lock|unlock|destroy) m7_http action "$1" ;;
		*) m7_cli "$@" ;;
	esac
}

m6_expect_busy()
{
	m7_http busy "$1"
	# Retain the M6 CLI EBUSY assertion in addition to HTTP rejection.
	local busy_output busy_result=0
	busy_output=$(m7_cli "$1" 2>&1) || busy_result=$?
	[[ $busy_result -eq 1 && $busy_output == *'Device or resource busy'* ]] ||
		m5_die 'CLI did not reject the busy/invalid transition'
}

m6_observe()
{
	python3 "$M5_ROOT/tests/m6-observe.py" "$@"
	m7_http observe "$@"
}

m6_integrity()
{
	python3 "$M5_ROOT/tests/m7-integrity.py" "$@"
}

m7_production()
{
	m6_production
	m5_begin_checks 'HTTP authorization' 'Static UI' 'Status API' 'Stats API' 'HTTP adversarial'
	# Absent-module responses also prove the server survived an unload.
	m7_http security
	m6_done
}

m7_tamper()
{
	m5_begin_checks 'Integrity-failure API'
	m6_tamper
	# Only reached after all three actual HTTP failed-state/recovery observers passed.
	m5_begin_checks 'Integrity-failure API'
	m6_done
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
	[[ $# -eq 0 ]] || m5_die 'no phase arguments accepted'
	[[ -n ${M7_ORIGIN:-} && -n ${M7_TOKEN:-} ]] || m5_die 'run through M7 session owner'
	m7_assert_commit_pin
	m6_run_phase m7_production 2>&1 | tee "$M5_VM_RUN_DIR/production.log"
	m6_run_phase m7_tamper 2>&1 | tee "$M5_VM_RUN_DIR/tamper.log"
	m6_run_phase m6_capacity 2>&1 | tee "$M5_VM_RUN_DIR/capacity.log"
	m6_run_phase m6_final 2>&1 | tee "$M5_VM_RUN_DIR/final-production.log"
fi
