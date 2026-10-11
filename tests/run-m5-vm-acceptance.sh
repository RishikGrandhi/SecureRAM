#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# One-command, fail-fast M5 acceptance for the disposable Ubuntu VM.
set -Eeuo pipefail

readonly script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$script_dir/m5-vm-common.sh"
m5_require_root
[[ $# -eq 0 ]] || m5_die "run-m5-vm-acceptance.sh accepts no arguments or device paths"
cd -- "$M5_ROOT"

readonly run_id=$(date -u +'%Y%m%dT%H%M%SZ')-$$
readonly run_root="$M5_ROOT/.cache/m5-vm"
export M5_VM_RUN_DIR="$run_root/$run_id"
export M5_STATUS_FILE="$M5_VM_RUN_DIR/status.tsv"
m5_run_as_builder mkdir -p -- "$M5_ROOT/.cache"
mkdir -p -- "$M5_VM_RUN_DIR"
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
	m5_record "$label" FAIL 'not completed'
done

M5_DMESG_PID=
M5_FINALIZED=0

m5_start_dmesg()
{
	stdbuf -oL -eL dmesg --follow-new --color=never > "$M5_VM_RUN_DIR/dmesg.log" 2>&1 &
	M5_DMESG_PID=$!
	local attempt
	for attempt in {1..50}; do
		kill -0 "$M5_DMESG_PID" 2>/dev/null || m5_die "fresh dmesg capture exited"
		[[ -e "/proc/$M5_DMESG_PID/fd/1" ]] && return 0
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
	[[ -f $log ]] || m5_die "fresh dmesg capture was not created"
	: > "$failures"
	grep -Ein 'secureram:.*(test.*FAILED|FAILED.*test)' "$log" >> "$failures" || true
	grep -Ein "$attributed|secureram_[[:alnum:]_]+\\+0x" "$log" \
		>> "$failures" || true
	grep -Ein "$faults|WARNING:|Call Trace:" \
		"$log" > "$M5_VM_RUN_DIR/kernel-unrelated-review.log" || true
	grep -E 'secureram:|EXT4-fs' "$log" > "$M5_VM_RUN_DIR/kernel-relevant.log" || true
	[[ -s $M5_VM_RUN_DIR/kernel-relevant.log ]] || m5_die "fresh dmesg capture has no SecureRAM/ext4 evidence"
	[[ ! -s $failures ]] || {
		printf '%s\n' 'Kernel health failure signatures:' >&2
		cat "$failures" >&2
		return 1
	}
	m5_record 'Kernel health' PASS 'no fatal or SecureRAM-attributable warning/test-failure signature'
	printf '%s\n' 'PASS: kernel health; unrelated warning indicators retained separately for review'
}

m5_print_summary()
{
	local label line status detail overall=PASS
	{
		printf '%-32s | %-4s | %s\n' CHECK RESULT DETAIL
		printf '%-32s-+-%-4s-+-%s\n' '--------------------------------' '----' '------'
		for label in "${result_labels[@]}"; do
			line=$(awk -F '\t' -v wanted="$label" '$1 == wanted { found=$0 } END { print found }' \
				"$M5_STATUS_FILE")
			IFS=$'\t' read -r _ status detail <<< "$line"
			[[ $status == PASS ]] || overall=FAIL
			printf '%-32s | %-4s | %s\n' "$label" "$status" "$detail"
		done
		printf '%-32s | %-4s | %s\n' OVERALL "$overall" "$M5_VM_RUN_DIR"
	} > "$M5_VM_RUN_DIR/summary.txt"
	cat "$M5_VM_RUN_DIR/summary.txt"
	[[ $overall == PASS ]]
}

m5_finalize()
{
	local original=$1 health=0 summary=0
	[[ $M5_FINALIZED -eq 0 ]] || return "$original"
	M5_FINALIZED=1
	set +e
	m5_stop_dmesg
	if ! m5_check_kernel_health; then
		health=1
	fi
	if ! m5_print_summary; then
		summary=1
	fi
	set -e
	if [[ $original -ne 0 || $health -ne 0 || $summary -ne 0 ]]; then
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

m5_stop_dmesg
m5_check_kernel_health
m5_print_summary
M5_FINALIZED=1
trap - EXIT
