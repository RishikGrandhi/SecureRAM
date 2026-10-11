#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# One-command, fail-fast M5 acceptance for the disposable Ubuntu VM.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly script_dir
source "$script_dir/m5-vm-common.sh"
m5_require_root
[[ $# -eq 0 ]] || m5_die "run-m5-vm-acceptance.sh accepts no arguments or device paths"
cd -- "$M5_ROOT"

run_id=$(date -u +'%Y%m%dT%H%M%SZ')-$$
readonly run_id
readonly run_root="$M5_ROOT/.cache/m5-vm"
export M5_VM_RUN_DIR="$run_root/$run_id"
export M5_STATUS_FILE="$M5_VM_RUN_DIR/status.tsv"
m5_prepare_evidence_directory "$run_root" "$M5_VM_RUN_DIR"
: > "$M5_STATUS_FILE"
exec > >(tee -a "$M5_VM_RUN_DIR/main.log") 2>&1

readonly result_labels=(
	'Production build'
	'Initial NO_KEY'
	'ABI/features'
	'Raw I/O'
	'Lock/unlock'
	'Destroy/rekey'
	'ext4'
	'Ciphertext tamper'
	'Tag tamper'
	'Relocation protection'
	'Integrity-failure recovery'
	'1 MiB capacity'
	'256 MiB capacity'
	'Final production regression'
	'Kernel health'
	'Final cleanup'
)

for label in "${result_labels[@]}"; do
	m5_record "$label" 'NOT RUN' 'assertion group was not reached'
done

M5_DMESG_PID=
M5_DMESG_STARTED=0
M5_FINALIZED=0

m5_start_dmesg()
{
	stdbuf -oL -eL dmesg --follow-new --color=never > "$M5_VM_RUN_DIR/dmesg.log" 2>&1 &
	M5_DMESG_PID=$!
	local attempt
	for attempt in {1..50}; do
		kill -0 "$M5_DMESG_PID" 2>/dev/null || m5_die "fresh dmesg capture exited"
		if [[ -e "/proc/$M5_DMESG_PID/fd/1" ]]; then
			M5_DMESG_STARTED=1
			return 0
		fi
		sleep 0.05
	done
	m5_die "fresh dmesg capture did not start"
}

m5_stop_dmesg()
{
	[[ -n $M5_DMESG_PID ]] || return 0
	if kill -0 "$M5_DMESG_PID" 2>/dev/null; then
		kill -TERM "$M5_DMESG_PID"
		wait "$M5_DMESG_PID" 2>/dev/null || true
	fi
	M5_DMESG_PID=
}

m5_check_kernel_health()
{
	local log="$M5_VM_RUN_DIR/dmesg.log"
	local failures="$M5_VM_RUN_DIR/kernel-health-failures.log"
	local faults='Oops|BUG:|kernel panic|general protection fault|use-after-free|KASAN'
	local attributed="secureram.*($faults|WARNING:)|($faults|WARNING:).*secureram"
	if [[ $M5_DMESG_STARTED -ne 1 || ! -f $log ]]; then
		m5_record 'Kernel health' 'NOT RUN' 'fresh dmesg capture did not start'
		printf '%s\n' 'NOT RUN: kernel health; fresh dmesg capture did not start' >&2
		return 1
	fi
	grep -E 'secureram:|EXT4-fs' "$log" > "$M5_VM_RUN_DIR/kernel-relevant.log" || true
	if [[ ! -s $M5_VM_RUN_DIR/kernel-relevant.log ]]; then
		m5_record 'Kernel health' 'NOT RUN' 'no SecureRAM/ext4 runtime evidence was captured'
		printf '%s\n' 'NOT RUN: kernel health; no SecureRAM/ext4 runtime evidence was captured' >&2
		return 1
	fi
	m5_record 'Kernel health' FAIL 'runtime evidence captured; health review did not complete'
	: > "$failures"
	grep -Ein 'secureram:.*(test.*FAILED|FAILED.*test)' "$log" >> "$failures" || true
	grep -Ein "$attributed|secureram_[[:alnum:]_]+\\+0x" "$log" \
		>> "$failures" || true
	grep -Ein "$faults|WARNING:|Call Trace:" \
		"$log" > "$M5_VM_RUN_DIR/kernel-unrelated-review.log" || true
	if [[ -s $failures ]]; then
		m5_record 'Kernel health' FAIL 'SecureRAM-attributable fault or failed diagnostic found'
		printf '%s\n' 'Kernel health failure signatures:' >&2
		cat "$failures" >&2
		return 1
	fi
	m5_record 'Kernel health' PASS 'no fatal or SecureRAM-attributable warning/test-failure signature'
	printf '%s\n' 'PASS: kernel health; unrelated warning indicators retained separately for review'
}

m5_print_summary()
{
	local label line status detail overall=PASS
	{
		printf '%-32s | %-13s | %s\n' CHECK RESULT DETAIL
		printf '%-32s-+-%-13s-+-%s\n' '--------------------------------' '-------------' '------'
		for label in "${result_labels[@]}"; do
			line=$(awk -F '\t' -v wanted="$label" '$1 == wanted { found=$0 } END { print found }' \
				"$M5_STATUS_FILE")
			if [[ -z $line ]]; then
				status='NOT RUN'
				detail='no status record was written'
			else
				IFS=$'\t' read -r _ status detail <<< "$line"
			fi
			[[ $status == PASS ]] || overall=FAIL
			printf '%-32s | %-13s | %s\n' "$label" "$status" "$detail"
		done
		printf '%-32s | %-13s | %s\n' OVERALL "$overall" "$M5_VM_RUN_DIR"
	} > "$M5_VM_RUN_DIR/summary.txt"
	cat "$M5_VM_RUN_DIR/summary.txt"
	[[ $overall == PASS ]]
}

m5_finalize()
{
	local original=$1 health=0 release=0 summary=0
	[[ $M5_FINALIZED -eq 0 ]] || return "$original"
	M5_FINALIZED=1
	set +e
	m5_stop_dmesg
	if ! m5_check_kernel_health; then
		health=1
	fi
	if ! m5_release_evidence_directory "$M5_VM_RUN_DIR"; then
		release=1
		m5_record 'Final cleanup' FAIL 'could not return evidence ownership to the build user'
	fi
	if ! m5_print_summary; then
		summary=1
	fi
	if ! m5_release_evidence_directory "$M5_VM_RUN_DIR"; then
		release=1
	fi
	set -e
	if [[ $original -ne 0 || $health -ne 0 || $release -ne 0 || $summary -ne 0 ]]; then
		return 1
	fi
	return 0
}

m5_on_exit()
{
	local original=$?
	trap - EXIT
	if m5_finalize "$original"; then
		exit 0
	fi
	exit 1
}
trap m5_on_exit EXIT

m5_require_tools
m5_assert_checkout
m5_assert_headers
m5_assert_module_absent
printf 'Evidence directory: %s\n' "$M5_VM_RUN_DIR"
m5_start_dmesg

bash tests/run-m5-production.sh 2>&1 | tee "$M5_VM_RUN_DIR/production.log"
bash tests/run-m5-tamper.sh 2>&1 | tee "$M5_VM_RUN_DIR/tamper.log"
bash tests/run-m5-capacity.sh 2>&1 | tee "$M5_VM_RUN_DIR/capacity.log"
bash tests/run-m5-final.sh 2>&1 | tee "$M5_VM_RUN_DIR/final-production.log"
