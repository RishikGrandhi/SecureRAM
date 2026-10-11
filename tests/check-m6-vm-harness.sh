#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Executes the actual phases with explicit shell-function mocks; never root/device I/O.
set -Eeuo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly script_dir
SR_MILESTONE=6
source "$script_dir/m5-vm-common.sh"
source "$script_dir/m6-vm-phases.sh"
source "$script_dir/vm-report.sh"

for shell_file in "$script_dir"/*.sh "$M5_ROOT"/scripts/*.sh; do
	bash -n "$shell_file"
done
bash "$script_dir/check-m5-vm-harness.sh"
python3 "$script_dir/check-m6-observe.py"
for rejected_capacity in '' 0 257 064 -1 invalid 999999999999999999999999; do
	if (m5_capacity_bytes_from_mb "$rejected_capacity" >/dev/null 2>&1); then
		m5_die "invalid capacity accepted: $rejected_capacity"
	fi
done
[[ $(m5_capacity_bytes_from_mb 1) == 1048576 ]]
[[ $(m5_capacity_bytes_from_mb 256) == 268435456 ]]
M6_EXPECTED_COMMIT=$(git -C "$M5_ROOT" rev-parse HEAD)
m6_assert_commit_pin
for rejected_pin in '' "${M6_EXPECTED_COMMIT:0:7}" invalid; do
	if (M6_EXPECTED_COMMIT=$rejected_pin; m6_assert_commit_pin) 2>/dev/null; then
		m5_die 'non-full commit pin accepted'
	fi
done

test_directory=$(mktemp -d)
readonly test_directory
trap 'rm -rf -- "$test_directory"' EXIT
M5_VM_RUN_DIR="$test_directory"
M5_STATUS_FILE="$test_directory/status.tsv"
mock_trace="$test_directory/trace"
: > "$M5_STATUS_FILE"
: > "$mock_trace"
mock_loaded=0 mock_capacity=0 mock_state=0 mock_generation=0 mock_mount=0 mock_failures=0
mock_refuse_unmount=0
trace() { printf '%s\n' "$*" >> "$mock_trace"; }
mock_check() { if ! "$@"; then m5_die "mock assertion: $*"; return 1; fi; }

# Fail closed: every external command reachable from phase functions is replaced
# or explicitly allowed to act only on files beneath this temporary directory.
m5_phase_preflight() { m5_assert_module_absent; }
m5_assert_module_absent() { mock_check test "$mock_loaded" -eq 0; }
m5_module_present() { [[ $mock_loaded -eq 1 ]]; }
m5_current_capacity() { printf '%s\n' "$mock_capacity"; }
m5_assert_headers() { :; }
m5_assert_checkout() { :; }
m5_build_module() { m5_assert_module_absent; trace "build $*"; }
m5_build_helper() { trace helper; }
m5_prove_production() { trace "production-proof $*"; }
m5_prove_test_build() { trace test-proof; }
m5_run_as_builder()
{
	case $1 in
		make) trace "builder $*" ;;
		mkdir) shift; command mkdir "$@" ;;
		*) m5_die "unexpected builder command $*" ;;
	esac
}
modprobe() { mock_check test "$*" = hkdf; }
insmod()
{
	mock_check test "$1" = ./secureram.ko
	case $2 in
		capacity_mb=0|capacity_mb=257) printf '%s\n' 'Invalid parameters' >&2; return 1 ;;
		capacity_mb=1|capacity_mb=64|capacity_mb=256) ;;
		*) m5_die "unexpected insmod args $*"; return 1 ;;
	esac
	mock_loaded=1 mock_state=0 mock_generation=0 mock_failures=0
	mock_capacity=$(m5_capacity_bytes_from_mb "${2#capacity_mb=}")
	trace "load $mock_capacity"
}
rmmod() { mock_check test "$*" = secureram; mock_loaded=0; trace unload; }
m5_wait_present() { mock_check test "$mock_loaded" -eq 1; }
m5_wait_absent() { mock_check test "$mock_loaded" -eq 0; }
m5_identity_guard()
{
	mock_check test "$mock_loaded" -eq 1
	mock_check test "$mock_mount" -eq 0
	mock_check test "$1" -eq "$mock_capacity"
	trace "identity $1"
}
m5_assert_query()
{
	mock_check test "$1:$2:$3" = "$mock_state:$mock_generation:$mock_capacity"
}
m5_control()
{
	case $1 in
		negative) mock_check test "$mock_state" -eq 0 ;;
		busy) mock_check test "$mock_mount" -eq 1 ;;
		destroy) mock_state=0; trace cleanup-destroy ;;
		*) m5_die "unexpected helper $*" ;;
	esac
}
m5_management()
{
	case $1 in
		help) printf '%s\n' Usage ;;
		version) printf '%s\n' 'secureramctl 0.6.0 (ABI 1)' ;;
		stats) printf '{"read_requests":0,"write_requests":0,"read_bytes":0,"write_bytes":0,"integrity_failures":%d}\n' "$mock_failures" ;;
		load-random|lock|unlock|destroy)
			if [[ $mock_mount -eq 1 || ($1 == load-random && $mock_state -ne 0) ||
			      ($1 == lock && $mock_state -ne 2) || ($1 == unlock && $mock_state -ne 3) ]]; then
				printf '%s\n' 'Device or resource busy' >&2
				return 1
			fi
			case $1 in
				load-random) mock_state=2; ((mock_generation += 1)) ;;
				lock) mock_state=3 ;;
				unlock) mock_state=2 ;;
				destroy) mock_state=0 ;;
			esac
			trace "cli $1" ;;
		*) m5_die "unexpected CLI $*" ;;
	esac
}
m6_observe()
{
	trace "observe $*"
	case $1 in
		status) m5_assert_query "$2" "$3" "$4" ;;
		baseline) mock_check test "$mock_generation:$mock_state:$mock_failures" = 0:0:0 ;;
		save) printf '{}\n' > "$2" ;;
		equal|retained|increased) mock_check test -f "$2" ;;
		accounting) mock_check test "$mock_state" -eq 2 ;;
		*) m5_die "unexpected observer $*" ;;
	esac
}
m5_run_raw()
{
	m5_identity_guard "$1"
	if [[ $2 == active ]]; then mock_check test "$mock_state" -eq 2
	else mock_check test "$mock_state" -ne 2; fi
	trace "raw $*"
}
python3()
{
	if [[ $1 == -c ]]; then
		command python3 "$@"
	elif [[ $1 == tests/m6-integrity.py && $2 == production ]]; then
		trace production-enotty
	elif [[ $1 == tests/m6-integrity.py && $2 == tamper ]]; then
		mock_check test "$mock_state" -eq 0
		mock_generation=6 mock_failures=3
		trace tamper
	else
		m5_die "unexpected python invocation $*"
	fi
}
dd()
{
	mock_check test "$1" = if=/dev/secureram0
	[[ $2 == "of=$test_directory/"* ]] || return 1
	printf 'mock block data\n' > "${2#of=}"
}
mkfs.ext4()
{
	mock_check test "$*" = '-q -E nodiscard /dev/secureram0'
	mock_check test "$mock_mount" -eq 0
	trace format
}
mount()
{
	mock_check test "$1" = /dev/secureram0
	mock_check test "$2" = "$M5_MOUNT_POINT"
	mock_mount=1
	trace mount
}
mountpoint() { [[ $mock_mount -eq 1 ]]; }
m5_assert_mounted_identity()
{
	mock_check test "$1:$2" = "$mock_capacity:$M5_MOUNT_POINT"
	mock_check test "$mock_mount" -eq 1
}
m5_assert_unmount_identity() { [[ $mock_refuse_unmount -eq 0 && $mock_mount -eq 1 ]]; }
umount()
{
	mock_check test "$*" = "-- $M5_MOUNT_POINT"
	mock_mount=0
	# Simulate unmounted directory; real ext4 contents live elsewhere.
	if [[ $M5_MOUNT_POINT == "$test_directory/"* ]]; then
		cp "$M5_MOUNT_POINT/check.txt" "$test_directory/persisted.txt"
	fi
	trace unmount
}
sync() { mock_check test "$1" = -f; }
# Actual comparisons/files exercise the complete redirections and persistence flow.
# Remove simulated on-mount files only once the phase exits, before real rmdir.
rmdir()
{
	local path
	for path in "$@"; do
		[[ $path == -- ]] && continue
		[[ $path == "$test_directory/"* ]] || return 1
		rm -f -- "$path/check.txt"
	done
	command rmdir "$@"
}

# Every real M6 phase, full capacity range, shared ext4 and phase EXIT cleanup.
for phase in m6_production m6_tamper m6_capacity m6_final; do
	m6_run_phase "$phase"
done
grep -q 'load 1048576' "$mock_trace"
grep -q 'load 268435456' "$mock_trace"
[[ $(grep -c '^format$' "$mock_trace") -eq 2 ]]
[[ $(grep -c '^mount$' "$mock_trace") -eq 4 ]]
[[ $(grep -c '^unmount$' "$mock_trace") -eq 4 ]]

# A failing phase must stop before its next command, mark FAIL and clean owned I/O.
mock_failing_phase()
{
	m5_begin_checks 'Synthetic failure'
	m5_load_module 1
	m5_load_key 1048576
	false
	trace MUST-NOT-RUN
}
set +e
m6_run_phase mock_failing_phase
expected_failure=$?
set -e
[[ $expected_failure -ne 0 ]]
! grep -q MUST-NOT-RUN "$mock_trace"
grep -q cleanup-destroy "$mock_trace"
grep -q $'Synthetic failure\tFAIL' "$M5_STATUS_FILE"

# Refusing unmount must retain ownership and must never call umount afterward,
# including inside an if condition where Bash disables errexit in called functions.
M5_MOUNT_POINT="$test_directory/refused-mount"
M5_MOUNTED_BY_HARNESS=1 mock_mount=1 mock_refuse_unmount=1
unmount_count=$(grep -c '^unmount$' "$mock_trace")
if m5_safe_unmount; then m5_die 'unsafe unmount was accepted'; fi
[[ $M5_MOUNTED_BY_HARNESS -eq 1 ]]
[[ $(grep -c '^unmount$' "$mock_trace") -eq $unmount_count ]]
M5_MOUNTED_BY_HARNESS=0 mock_mount=0 mock_refuse_unmount=0

# Early abort: no fabricated kernel PASS and no grep of missing dmesg.
M5_DMESG_STARTED=0
if m5_check_kernel_health 2> "$test_directory/early-stderr"; then
	m5_die 'kernel health passed without runtime capture'
fi
! grep -q 'No such file' "$test_directory/early-stderr"
# A real log must still fail if collection died, or a warning appears.
printf 'secureram: synthetic runtime message\n' > "$test_directory/dmesg.log"
M5_DMESG_STARTED=1 M5_DMESG_LOST=1
if m5_check_kernel_health; then m5_die 'lost capture passed'; fi
M5_DMESG_LOST=0
printf 'WARNING: synthetic environment warning\n' >> "$test_directory/dmesg.log"
if m5_check_kernel_health > /dev/null 2>&1; then m5_die 'warning passed'; fi
M5_DMESG_STARTED=0
m5_check_kernel_health > /dev/null 2>&1 || true
result_labels=('Synthetic failure' 'Never reached' 'Kernel health')
m5_record 'Never reached' 'NOT RUN'
if m5_print_summary > "$test_directory/summary-output"; then
	m5_die 'incomplete summary passed'
fi
grep -q 'NOT RUN' "$test_directory/summary.txt"
grep -q 'OVERALL.*FAIL' "$test_directory/summary.txt"

# Evidence guards must reject bad paths before ownership/filesystem operations.
if (m5_prepare_evidence_directory /unexpected /unexpected/run) 2>/dev/null; then
	m5_die 'unexpected evidence root accepted'
fi
if (m5_release_evidence_directory /unexpected/run) 2>/dev/null; then
	m5_die 'unexpected release path accepted'
fi
[[ $(stat -c %u "$M5_VM_RUN_DIR") -eq $(id -u) ]]

# Finalization cannot print PASS after an orchestration/ownership failure.
# Nothing privileged occurs: only these leaf functions are replaced here.
result_labels=('Kernel health' 'Final cleanup')
M5_FINALIZED=0 M5_DMESG_PID=
m5_stop_dmesg() { :; }
m5_check_kernel_health() { m5_record 'Kernel health' PASS 'synthetic'; }
m5_release_evidence_directory() { return 1; }
if m5_finalize 1 > "$test_directory/finalize-output"; then
	m5_die 'failed finalization passed'
fi
grep -q 'OVERALL.*FAIL' "$test_directory/summary.txt"
! grep -q 'OVERALL.*PASS' "$test_directory/finalize-output"
printf '%s\n' 'PASS: M6 full mocked phases, capacities, ext4/busy/remount, fail-fast, owned cleanup, refusal, summary, early abort and evidence guards'
