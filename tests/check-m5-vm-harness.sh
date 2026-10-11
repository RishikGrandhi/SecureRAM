#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Non-destructive strict-shell regression checks for M5 harness helpers.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly script_dir
source "$script_dir/m5-vm-common.sh"

for shell_file in "$script_dir/m5-vm-common.sh" "$script_dir"/run-m5-*.sh \
	"$script_dir/check-m5-vm-harness.sh"; do
	set +e
	syntax_diagnostic=$(bash -n "$shell_file" 2>&1)
	syntax_result=$?
	set -e
	[[ $syntax_result -eq 0 ]] || m5_die "bash -n failed for $shell_file"
	[[ -z $syntax_diagnostic ]] ||
		m5_die "bash -n emitted a diagnostic for $shell_file: $syntax_diagnostic"
done

actual_capacity_bytes=$(m5_capacity_bytes_from_mb 64)
[[ $actual_capacity_bytes == 67108864 ]] || m5_die "64 MiB conversion was incorrect"
if (m5_capacity_bytes_from_mb >/dev/null 2>&1); then
	m5_die "missing capacity argument was accepted"
fi
if (m5_capacity_bytes_from_mb invalid >/dev/null 2>&1); then
	m5_die "non-numeric capacity argument was accepted"
fi

# Exercise the load helper's parameter handling without touching a module/device.
m5_assert_module_absent() { :; }
modprobe() { :; }
insmod() { :; }
m5_wait_present() { :; }
m5_identity_guard() { [[ $1 == 67108864 ]]; }
readonly phase_expected_capacity_bytes=67108864
m5_load_module 64
[[ $M5_RUNTIME_OWNED -eq 1 ]] || m5_die "mock load did not reach the ownership transition"

# This exact immutable caller name previously collided with cleanup's local
# variable through Bash's dynamic scope. No runtime is owned for cleanup here.
readonly capacity_bytes=67108864
M5_RUNTIME_OWNED=0
M5_MOUNTED_BY_HARNESS=0
m5_cleanup_runtime

test_directory=$(mktemp -d)
trap 'rm -rf -- "$test_directory"' EXIT
M5_STATUS_FILE="$test_directory/status.tsv"
: > "$M5_STATUS_FILE"
m5_record 'self-test' 'NOT RUN' 'initial'
m5_record 'self-test' 'NOT COMPLETED' 'started'
m5_record 'self-test' FAIL 'expected synthetic failure state'
m5_record 'self-test' PASS 'finished'
[[ $(awk -F '\t' '$1 == "self-test" { status=$2 } END { print status }' \
	"$M5_STATUS_FILE") == PASS ]] || m5_die "status ledger did not retain the latest result"

M5_VM_RUN_DIR="$test_directory"
M5_MOUNT_POINT="$test_directory/production-mount"
mkdir -- "$M5_MOUNT_POINT"
ext4_trace=()
m5_identity_guard()
{
	[[ $1 == 67108864 ]] || return 1
	ext4_trace+=(identity)
}
mkfs.ext4()
{
	[[ $# -eq 4 && $1 == -q && $2 == -E && $3 == nodiscard && $4 == "$M5_DEVICE" ]] ||
		return 1
	ext4_trace+=(mkfs)
}
mount()
{
	[[ $# -eq 2 && $1 == "$M5_DEVICE" && $2 == "$M5_MOUNT_POINT" ]] || return 1
	ext4_trace+=(mount)
}
m5_assert_mounted_identity()
{
	[[ $1 == 67108864 && $2 == "$M5_MOUNT_POINT" ]] || return 1
	ext4_trace+=(mounted-identity)
}
m5_register_ephemeral_file()
{
	[[ $1 == "$M5_VM_RUN_DIR/expected-check.txt" ]] || return 1
	ext4_trace+=(register-expected)
}
sync()
{
	[[ $# -eq 2 && $1 == -f && $2 == "$M5_MOUNT_POINT/check.txt" ]] || return 1
	ext4_trace+=(sync)
}
cmp()
{
	command cmp "$@"
	ext4_trace+=(compare)
}
m5_assert_mounted_transitions_busy()
{
	[[ $1 == 67108864 && $M5_MOUNTED_BY_HARNESS -eq 1 ]] || return 1
	ext4_trace+=(mounted-busy)
}
m5_safe_unmount()
{
	[[ $M5_MOUNTED_BY_HARNESS -eq 1 ]] || return 1
	M5_MOUNTED_BY_HARNESS=0
	ext4_trace+=(unmount)
}

m5_run_production_ext4 67108864 "$M5_MOUNT_POINT"
readonly expected_ext4_trace='identity mkfs mount mounted-identity register-expected sync compare mounted-identity mounted-busy compare unmount identity mount mounted-identity compare unmount'
[[ ${ext4_trace[*]} == "$expected_ext4_trace" ]] ||
	m5_die "unexpected mocked ext4 flow: ${ext4_trace[*]}"
[[ $M5_MOUNTED_BY_HARNESS -eq 0 ]] || m5_die "mocked ext4 flow remained mounted"
[[ -f $M5_MOUNT_POINT/check.txt ]] || m5_die "mocked ext4 data file is missing"
[[ ! -e $M5_VM_RUN_DIR/expected-check.txt ]] || m5_die "mocked ext4 comparison file was retained"

printf '%s\n' 'PASS: M5 harness syntax, parameter, scope, cleanup, status and mocked ext4 flow'
