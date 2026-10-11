#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/m5-vm-common.sh"
m5_phase_preflight
[[ $# -eq 0 ]] || m5_die "run-m5-tamper.sh accepts no arguments"
trap 'm5_phase_exit $?' EXIT

readonly phase_expected_capacity_bytes=$((M5_DEFAULT_MB * 1024 * 1024))

m5_begin_checks 'Ciphertext tamper' 'Tag tamper' 'Relocation protection' 'Integrity-failure recovery'
m5_build_module tamper M5_TEST=1 M4_TEST=1
m5_build_helper
m5_prove_test_build
m5_load_module "$M5_DEFAULT_MB"
m5_assert_query 0 0 "$phase_expected_capacity_bytes"
m5_identity_guard "$phase_expected_capacity_bytes"
python3 tests/m5-integrity.py tamper
m5_assert_query 0 6 "$phase_expected_capacity_bytes"
m5_record 'Ciphertext tamper' PASS 'EIO, untouched failed-unit buffer, state=4, recovery'
m5_record 'Tag tamper' PASS 'EIO, untouched failed-unit buffer, state=4, recovery'
m5_record 'Relocation protection' PASS 'unit-index binding rejected relocated valid pair'
m5_record 'Integrity-failure recovery' PASS 'transitions rejected; destroy then fresh load restored I/O'
m5_complete_checks
m5_destroy_key "$phase_expected_capacity_bytes"
m5_unload_owned
trap - EXIT

