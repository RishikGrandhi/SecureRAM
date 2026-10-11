#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/m5-vm-common.sh"
m5_phase_preflight
[[ $# -eq 0 ]] || m5_die "run-m5-production.sh accepts no arguments"
trap 'm5_phase_exit $?' EXIT

readonly phase_expected_capacity_bytes=$((M5_DEFAULT_MB * 1024 * 1024))
M5_MOUNT_POINT="$M5_VM_RUN_DIR/production-mount"
m5_run_as_builder mkdir -- "$M5_MOUNT_POINT"
m5_register_ephemeral_dir "$M5_MOUNT_POINT"

m5_begin_checks 'Production build'
m5_build_module production
m5_build_helper
m5_prove_production production
m5_record 'Production build' PASS 'clean matching-kernel W=1 build; test surface absent'
m5_complete_checks

m5_begin_checks 'Initial NO_KEY' 'ABI/features'
m5_load_module "$M5_DEFAULT_MB"
m5_assert_query 0 0 "$phase_expected_capacity_bytes"
python3 tests/m5-integrity.py production
m5_run_raw "$phase_expected_capacity_bytes" denied
m5_identity_guard "$phase_expected_capacity_bytes"
"$M5_CONTROL_HELPER" negative
m5_assert_query 0 0 "$phase_expected_capacity_bytes"
m5_record 'Initial NO_KEY' PASS 'state=0 generation=0; read/write opens denied ENOKEY'
m5_record 'ABI/features' PASS 'ABI=1 unit=4096 features=7 capacity=64 MiB; negative ABI passed'
m5_complete_checks

m5_begin_checks 'Raw I/O'
m5_load_key "$phase_expected_capacity_bytes"
m5_assert_query 2 1 "$phase_expected_capacity_bytes"
m5_run_raw "$phase_expected_capacity_bytes" active
m5_record 'Raw I/O' PASS 'full-zero, segmented/direct, boundaries, neighbors, concurrency, SHA-256/cmp'
m5_complete_checks

m5_begin_checks 'Lock/unlock'
m5_identity_guard "$phase_expected_capacity_bytes"
m5_expect_control_busy load-test-key 2 1 "$phase_expected_capacity_bytes"
lock_dir=$(mktemp -d "$M5_VM_RUN_DIR/lock-data.XXXXXX")
m5_register_ephemeral_dir "$lock_dir"
m5_register_ephemeral_file "$lock_dir/before.bin"
m5_register_ephemeral_file "$lock_dir/after.bin"
dd if="$M5_DEVICE" of="$lock_dir/before.bin" bs=4096 count=256 iflag=direct status=none
m5_identity_guard "$phase_expected_capacity_bytes"
"$M5_CONTROL_HELPER" lock
m5_assert_query 3 1 "$phase_expected_capacity_bytes"
m5_run_raw "$phase_expected_capacity_bytes" denied
m5_expect_control_busy load-test-key 3 1 "$phase_expected_capacity_bytes"
m5_identity_guard "$phase_expected_capacity_bytes"
"$M5_CONTROL_HELPER" unlock
m5_assert_query 2 1 "$phase_expected_capacity_bytes"
dd if="$M5_DEVICE" of="$lock_dir/after.bin" bs=4096 count=256 iflag=direct status=none
cmp -- "$lock_dir/before.bin" "$lock_dir/after.bin"
rm -f -- "$lock_dir/before.bin" "$lock_dir/after.bin"
rmdir -- "$lock_dir"
m5_record 'Lock/unlock' PASS 'LOCKED=3, denied I/O, ACTIVE=2, generation/data retained'
m5_complete_checks

m5_begin_checks 'Destroy/rekey'
m5_destroy_key "$phase_expected_capacity_bytes"
m5_assert_query 0 1 "$phase_expected_capacity_bytes"
m5_run_raw "$phase_expected_capacity_bytes" denied
m5_destroy_key "$phase_expected_capacity_bytes"
m5_assert_query 0 1 "$phase_expected_capacity_bytes"
m5_load_key "$phase_expected_capacity_bytes"
m5_assert_query 2 2 "$phase_expected_capacity_bytes"
m5_run_raw "$phase_expected_capacity_bytes" active
m5_record 'Destroy/rekey' PASS 'idempotent destroy; fresh generation=2 zero medium and raw regression'
m5_complete_checks

m5_begin_checks 'ext4'
m5_identity_guard "$phase_expected_capacity_bytes"
mkfs.ext4 -q -E nodiscard "$M5_DEVICE"
mount "$M5_DEVICE" "$M5_MOUNT_POINT"
M5_MOUNTED_BY_HARNESS=1
m5_assert_mounted_identity "$phase_expected_capacity_bytes" "$M5_MOUNT_POINT"
printf '%s\n' 'SecureRAM M5 authenticated backing, normal filesystem I/O' >
	"$M5_MOUNT_POINT/check.txt"
m5_register_ephemeral_file "$M5_VM_RUN_DIR/expected-check.txt"
printf '%s\n' 'SecureRAM M5 authenticated backing, normal filesystem I/O' >
	"$M5_VM_RUN_DIR/expected-check.txt"
sync -f "$M5_MOUNT_POINT/check.txt"
cmp -- "$M5_VM_RUN_DIR/expected-check.txt" "$M5_MOUNT_POINT/check.txt"
m5_assert_mounted_identity "$phase_expected_capacity_bytes" "$M5_MOUNT_POINT"
"$M5_CONTROL_HELPER" busy
m5_assert_query 2 2 "$phase_expected_capacity_bytes"
cmp -- "$M5_VM_RUN_DIR/expected-check.txt" "$M5_MOUNT_POINT/check.txt"
m5_safe_unmount
m5_identity_guard "$phase_expected_capacity_bytes"
mount "$M5_DEVICE" "$M5_MOUNT_POINT"
M5_MOUNTED_BY_HARNESS=1
m5_assert_mounted_identity "$phase_expected_capacity_bytes" "$M5_MOUNT_POINT"
cmp -- "$M5_VM_RUN_DIR/expected-check.txt" "$M5_MOUNT_POINT/check.txt"
m5_safe_unmount
rm -f -- "$M5_VM_RUN_DIR/expected-check.txt"
m5_record 'ext4' PASS 'nodiscard format, file sync/read, mounted EBUSY, remount/read, clean unmount'
m5_complete_checks

m5_destroy_key "$phase_expected_capacity_bytes"
m5_assert_query 0 2 "$phase_expected_capacity_bytes"
m5_run_raw "$phase_expected_capacity_bytes" denied
m5_unload_owned
rmdir -- "$M5_MOUNT_POINT"
trap - EXIT

