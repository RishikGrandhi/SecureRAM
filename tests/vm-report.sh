#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Shared evidence reporting. Sourced after the common helpers and result labels.
m5_start_dmesg()
{
	M5_DMESG_LOST=0
	stdbuf -oL -eL dmesg --follow-new --color=never > "$M5_VM_RUN_DIR/dmesg.log" 2>&1 &
	M5_DMESG_PID=$!
	local attempt
	for attempt in {1..50}; do
		kill -0 "$M5_DMESG_PID" 2>/dev/null || {
			m5_die "fresh dmesg capture exited"; return 1;
		}
		if [[ -e "/proc/$M5_DMESG_PID/fd/1" ]]; then
			M5_DMESG_STARTED=1
			if [[ ${SR_MILESTONE:-5} == 9 || ${SR_MILESTONE:-5} == 10 ]]; then
				m9_log_marker start || return 1
			fi
			return 0
		fi
		sleep 0.05
	done
	m5_die "fresh dmesg capture did not start"
}

# A process/fd existing does not mean dmesg has reached follow-new yet. Repeat
# a nonsecret marker until observed before any M9 runtime work. The end marker
# similarly proves the reader drained the complete test window before stopping.
m9_log_marker()
{
	local marker="secureram: M9-$1-$$" attempt
	for attempt in {1..100}; do
		kill -0 "$M5_DMESG_PID" 2>/dev/null || break
		m9_write_marker "$marker" || break
		sleep 0.05
		if grep -Fq "$marker" "$M5_VM_RUN_DIR/dmesg.log"; then return 0; fi
	done
	M5_DMESG_LOST=1
	m5_die 'kernel log marker was not observed; capture incomplete'
}

m9_write_marker()
{
	printf '<6>%s\n' "$1" > /dev/kmsg
}

m5_stop_dmesg()
{
	[[ -n $M5_DMESG_PID ]] || return 0
	if kill -0 "$M5_DMESG_PID" 2>/dev/null; then
		if [[ ${SR_MILESTONE:-5} == 9 || ${SR_MILESTONE:-5} == 10 ]]; then
			m9_log_marker end || M5_DMESG_LOST=1
		fi
		kill -TERM "$M5_DMESG_PID"
		wait "$M5_DMESG_PID" 2>/dev/null || true
	else
		M5_DMESG_LOST=1
	fi
	M5_DMESG_PID=
}

m5_check_kernel_health()
{
	local log="$M5_VM_RUN_DIR/dmesg.log"
	local failures="$M5_VM_RUN_DIR/kernel-health-failures.log"
	local faults='Oops|BUG:|kernel panic|general protection fault|use-after-free|KASAN|KCSAN|blocked for more than|hung task'
	local attributed="secureram.*($faults|WARNING:)|($faults|WARNING:).*secureram"
	if [[ $M5_DMESG_STARTED -ne 1 || ! -f $log ]]; then
		m5_record 'Kernel health' 'NOT RUN' 'fresh dmesg capture did not start'
		printf '%s\n' 'NOT RUN: kernel health; fresh dmesg capture did not start' >&2
		return 1
	fi
	if [[ ${M5_DMESG_LOST:-0} -eq 1 ]]; then
		m5_record 'Kernel health' FAIL 'fresh dmesg capture ended unexpectedly'
		return 1
	fi
	grep -E 'secureram:|EXT4-fs' "$log" | grep -Ev 'secureram: M9-(start|end)-[0-9]+$' \
		> "$M5_VM_RUN_DIR/kernel-relevant.log" || true
	if [[ ! -s $M5_VM_RUN_DIR/kernel-relevant.log ]]; then
		m5_record 'Kernel health' 'NOT RUN' 'no SecureRAM/ext4 runtime evidence was captured'
		printf '%s\n' 'NOT RUN: kernel health; no SecureRAM/ext4 runtime evidence was captured' >&2
		return 1
	fi
	m5_record 'Kernel health' FAIL 'runtime evidence captured; health review did not complete'
	: > "$failures"
	if [[ ${SR_MILESTONE:-5} =~ ^(6|7|8|9|10)$ ]]; then
		# A warning may be environmental; retain it for classification, never
		# declare health PASS before the operator has resolved that evidence.
		grep -Ein "$faults|WARNING:|Call Trace:" "$log" >> "$failures" || true
	fi
	if [[ ${SR_MILESTONE:-5} == 8 || ${SR_MILESTONE:-5} == 9 || ${SR_MILESTONE:-5} == 10 ]]; then
		grep -Ein 'possible.*locking|possible.*deadlock|suspicious RCU|sleeping function called|double free|kmemleak' \
			"$log" >> "$failures" || true
	fi
	grep -Ein 'secureram:.*(test.*FAILED|FAILED.*test)' "$log" >> "$failures" || true
	grep -Ein "$attributed|secureram_[[:alnum:]_]+\\+0x" "$log" \
		>> "$failures" || true
	grep -Ein "$faults|WARNING:|Call Trace:" \
		"$log" > "$M5_VM_RUN_DIR/kernel-unrelated-review.log" || true
	if [[ -s $failures ]]; then
		m5_record 'Kernel health' FAIL 'fault/warning signature or failed diagnostic found'
		printf '%s\n' 'Kernel health failure signatures:' >&2
		cat "$failures" >&2
		return 1
	fi
	m5_record 'Kernel health' PASS 'captured runtime log passed milestone health checks'
	printf '%s\n' 'PASS: kernel health; captured log and warning context retained for review'
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
	if [[ $original -ne 0 ]]; then
		# Preserve a nonzero orchestration/cleanup error even if all reached
		# assertion groups already wrote PASS before that error occurred.
		m5_record 'Final cleanup' FAIL 'suite aborted; inspect phase/build/environment logs'
	fi
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
		m5_record 'Final cleanup' FAIL 'final evidence ownership release failed'
		m5_print_summary || summary=1
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
