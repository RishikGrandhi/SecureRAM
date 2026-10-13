#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Fixture logs only: no kernel log/device access, no privileged commands.
set -Eeuo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$script_dir/vm-report.sh"
M5_VM_RUN_DIR=$(mktemp -d)
trap 'rm -rf -- "$M5_VM_RUN_DIR"' EXIT
M5_DMESG_STARTED=1
M5_DMESG_LOST=0
SR_MILESTONE=9
m5_record() { printf '%s\t%s\t%s\n' "$@" >> "$M5_VM_RUN_DIR/status.tsv"; }
for fault in 'BUG: bad state' 'WARNING: unsafe' 'Oops: bad' 'Kernel panic' \
	'KCSAN: data-race' 'INFO: task stress:123 blocked for more than 120 seconds' \
	'possible circular locking dependency detected' 'KASAN: use-after-free' 'double free'; do
	printf 'secureram: test window\n%s\n' "$fault" > "$M5_VM_RUN_DIR/dmesg.log"
	if m5_check_kernel_health >/dev/null 2>&1; then
		printf 'FAIL: kernel-health accepted %s\n' "$fault"; exit 1
	fi
done
printf 'secureram: ready\nsecureram: integrity failure at unit 0; device latched INTEGRITY_FAILED\n' > "$M5_VM_RUN_DIR/dmesg.log"
m5_check_kernel_health >/dev/null
M5_DMESG_LOST=1
if m5_check_kernel_health >/dev/null; then exit 1; fi
M5_DMESG_LOST=0
: > "$M5_VM_RUN_DIR/dmesg.log"
if m5_check_kernel_health >/dev/null 2>&1; then exit 1; fi
# Marker fixture: simulate a late dmesg exec dropping the first two writes.
M5_DMESG_PID=$$
marker_attempts=0
sleep() { :; }
m5_die() { printf 'FAIL: %s\n' "$*" >&2; return 1; }
m9_write_marker()
{
	marker_attempts=$((marker_attempts + 1))
	if ((marker_attempts > 2)); then printf '%s\n' "$1" >> "$M5_VM_RUN_DIR/dmesg.log"; fi
}
m9_log_marker start
[[ $marker_attempts == 3 ]]
# Markers alone cannot substitute for real module runtime evidence.
if m5_check_kernel_health >/dev/null 2>&1; then exit 1; fi
m9_log_marker end
m9_write_marker() { return 1; }
if m9_log_marker end 2>/dev/null; then exit 1; fi
[[ $M5_DMESG_LOST == 1 ]]
printf '%s\n' 'PASS: health rejects KCSAN/hung-task/lockdep/memory faults and lost/empty capture'
