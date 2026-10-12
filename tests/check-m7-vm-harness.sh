#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly script_dir
export M7_HARNESS_SELFTEST=1
# Reuse mocks and early-abort/cleanup/ledger audits, execute M7's real overrides.
bash "$script_dir/check-m6-vm-harness.sh"
python3 "$script_dir/check-m7-observe.py"
printf '%s\n' 'PASS: M7 mocked harness, early aborts, process cleanup and HTTP assertion self-tests'
