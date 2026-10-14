#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly script_dir
export SR_MILESTONE=9
source "$script_dir/m5-vm-common.sh"
source "$script_dir/m6-vm-phases.sh"
source "$script_dir/m7-vm-phases.sh"
source "$script_dir/m8-vm-phases.sh"
source "$script_dir/m9-vm-phases.sh"
m5_require_root
[[ $# -eq 0 ]] || m5_die 'no device paths or arguments accepted'
cd -- "$M5_ROOT"
export M5_EXPECTED_BRANCH=m9-stress-hardening
export M5_EXPECTED_COMMIT=${M9_EXPECTED_COMMIT:-}
m9_parameters
[[ $(uname -r) != *[Mm]icrosoft* ]] || m5_die 'VM acceptance is forbidden on WSL'

readonly run_root="$M5_ROOT/.cache/m9-vm"
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
	'Dashboard startup' 'Loopback-only binding' 'HTTP authorization' 'Static UI'
	'Status API' 'Stats API' 'HTTP adversarial' 'Integrity-failure API'
	'Snapshot rollback/lifecycle/UAPI' 'Snapshot HTTP' 'Snapshot unload/reload'
	'Snapshot integrity latch' 'Final production regression' 'Dashboard cleanup'
	'Concurrent I/O and busy controls' 'Control-plane races' 'Snapshot stress'
	'Key lifecycle stress' 'Invalid UAPI' 'Fault handling' 'Load/unload stress'
	'Integrity corruption' 'Existing regressions' 'Kernel health' 'Final cleanup'
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
printf 'M9 evidence: %s\n' "$M5_VM_RUN_DIR"
m5_run_as_builder python3 tests/check-m7-dashboard.py
m5_run_as_builder python3 tests/check-m8-dashboard.py
command -v timeout >/dev/null
{
	uname -a
	printf 'mode=%s io=%s cycles=%s reloads=%s\n' "${M9_MODE:-quick}" "$M9_IO_ROUNDS" "$M9_CYCLES" "$M9_RELOADS"
	m5_run_as_builder git rev-parse HEAD
} > "$M5_VM_RUN_DIR/environment.txt"
m5_start_dmesg
# The existing process owner selects the composed M9 phases.
python3 tests/m7-vm-session.py
