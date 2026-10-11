#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly script_dir
SR_MILESTONE=6
source "$script_dir/m5-vm-common.sh"
source "$script_dir/m6-vm-phases.sh"
m5_require_root
[[ $# -eq 0 ]] || m5_die 'no device paths or arguments accepted'
cd -- "$M5_ROOT"
export M5_EXPECTED_BRANCH=m6-cli-observability
export M5_EXPECTED_COMMIT=${M6_EXPECTED_COMMIT:-}
m6_assert_commit_pin
[[ $(uname -r) != *[Mm]icrosoft* ]] || m5_die 'VM acceptance is forbidden on WSL'

readonly run_root="$M5_ROOT/.cache/m6-vm"
export M5_VM_RUN_DIR="$run_root/$(date -u +'%Y%m%dT%H%M%SZ')-$$"
export M5_STATUS_FILE="$M5_VM_RUN_DIR/status.tsv"
m5_prepare_evidence_directory "$run_root" "$M5_VM_RUN_DIR"
exec > >(tee -a "$M5_VM_RUN_DIR/main.log") 2>&1
readonly result_labels=(
	'Production build' 'CLI build' 'CLI help/version' 'Version/features'
	'Human status' 'JSON status' 'Stats baseline' 'Random key load' 'Raw I/O'
	'Stats accounting' 'Lock/unlock' 'Destroy/rekey' 'ext4' 'Mounted busy rejection'
	'Integrity-failure observability' 'Tamper regression' 'Recovery'
	'Capacity parameter rejection' '1 MiB capacity' '256 MiB capacity'
	'Final production regression' 'Kernel health' 'Final cleanup'
)
for label in "${result_labels[@]}"; do
	m5_record "$label" 'NOT RUN' 'assertion group not reached'
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
printf 'M6 evidence: %s\n' "$M5_VM_RUN_DIR"
m5_start_dmesg
m6_run_phase m6_production 2>&1 | tee "$M5_VM_RUN_DIR/production.log"
m6_run_phase m6_tamper 2>&1 | tee "$M5_VM_RUN_DIR/tamper.log"
m6_run_phase m6_capacity 2>&1 | tee "$M5_VM_RUN_DIR/capacity.log"
m6_run_phase m6_final 2>&1 | tee "$M5_VM_RUN_DIR/final-production.log"
