#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Non-destructive strict-shell regression checks for M5 harness helpers.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly script_dir
source "$script_dir/m5-vm-common.sh"

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

printf '%s\n' 'PASS: M5 harness parameter, scope, cleanup and status helpers'
