#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# One-command, fail-fast M5 acceptance for the disposable Ubuntu VM.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly script_dir
SR_MILESTONE=5
source "$script_dir/m5-vm-common.sh"
m5_require_root
[[ $# -eq 0 ]] || m5_die "run-m5-vm-acceptance.sh accepts no arguments or device paths"
cd -- "$M5_ROOT"

run_id=$(date -u +'%Y%m%dT%H%M%SZ')-$$
readonly run_id
readonly run_root="$M5_ROOT/.cache/m5-vm"
export M5_VM_RUN_DIR="$run_root/$run_id"
export M5_STATUS_FILE="$M5_VM_RUN_DIR/status.tsv"
m5_prepare_evidence_directory "$run_root" "$M5_VM_RUN_DIR"
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
	m5_record "$label" 'NOT RUN' 'assertion group was not reached'
done

M5_DMESG_PID=
M5_DMESG_STARTED=0
M5_FINALIZED=0

source "$script_dir/vm-report.sh"
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
