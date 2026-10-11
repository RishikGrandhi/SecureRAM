#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/m5-vm-common.sh"
m5_phase_preflight
[[ $# -eq 0 ]] || m5_die "run-m5-final.sh accepts no arguments"
trap 'm5_phase_exit $?' EXIT

readonly phase_expected_capacity_bytes=$((M5_DEFAULT_MB * 1024 * 1024))
M5_MOUNT_POINT="$M5_VM_RUN_DIR/final-mount"
m5_run_as_builder mkdir -- "$M5_MOUNT_POINT"
m5_register_ephemeral_dir "$M5_MOUNT_POINT"

m5_begin_checks 'Final production regression'
m5_build_module final-production
m5_build_helper
m5_prove_production final-production
m5_load_module "$M5_DEFAULT_MB"
m5_assert_query 0 0 "$phase_expected_capacity_bytes"
python3 tests/m5-integrity.py production
m5_run_raw "$phase_expected_capacity_bytes" denied
m5_load_key "$phase_expected_capacity_bytes"
m5_assert_query 2 1 "$phase_expected_capacity_bytes"
m5_run_raw "$phase_expected_capacity_bytes" active

m5_identity_guard "$phase_expected_capacity_bytes"
mkfs.ext4 -q -E nodiscard "$M5_DEVICE"
mount "$M5_DEVICE" "$M5_MOUNT_POINT"
M5_MOUNTED_BY_HARNESS=1
m5_assert_mounted_identity "$phase_expected_capacity_bytes" "$M5_MOUNT_POINT"
printf '%s\n' 'SecureRAM M5 final production smoke' > "$M5_MOUNT_POINT/check.txt"
m5_register_ephemeral_file "$M5_VM_RUN_DIR/final-expected.txt"
printf '%s\n' 'SecureRAM M5 final production smoke' > "$M5_VM_RUN_DIR/final-expected.txt"
sync -f "$M5_MOUNT_POINT/check.txt"
cmp -- "$M5_VM_RUN_DIR/final-expected.txt" "$M5_MOUNT_POINT/check.txt"
m5_safe_unmount
m5_identity_guard "$phase_expected_capacity_bytes"
mount "$M5_DEVICE" "$M5_MOUNT_POINT"
M5_MOUNTED_BY_HARNESS=1
m5_assert_mounted_identity "$phase_expected_capacity_bytes" "$M5_MOUNT_POINT"
cmp -- "$M5_VM_RUN_DIR/final-expected.txt" "$M5_MOUNT_POINT/check.txt"
m5_safe_unmount
rm -f -- "$M5_VM_RUN_DIR/final-expected.txt"

m5_record 'Final production regression' PASS 'production ENOTTY, raw regression, ext4 sync/remount'
m5_complete_checks

m5_begin_checks 'Final cleanup'
m5_destroy_key "$phase_expected_capacity_bytes"
m5_assert_query 0 1 "$phase_expected_capacity_bytes"
m5_run_raw "$phase_expected_capacity_bytes" denied
m5_unload_owned
m5_assert_module_absent
rmdir -- "$M5_MOUNT_POINT"
m5_record 'Final cleanup' PASS 'destroyed, unloaded, all nodes/sysfs/module absent'
m5_complete_checks
trap - EXIT

