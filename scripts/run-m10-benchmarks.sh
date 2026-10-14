#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Explicitly destructive ONLY to /dev/secureram0. Run in the disposable VM.
set -Eeuo pipefail
if [[ ${M10_BOUNDED:-0} != 1 ]]; then
    export M10_BOUNDED=1
    exec timeout --signal=TERM --kill-after=30s 45m bash "$0" "$@"
fi
export SR_MILESTONE=10
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$script_dir/../tests/m5-vm-common.sh"
m5_require_root
case ${1:---full} in
    --full) mode=full ;;
    --quick) mode=quick ;;
    *) m5_die 'usage: sudo env M10_EXPECTED_COMMIT=<full SHA> bash scripts/run-m10-benchmarks.sh [--quick|--full]'; exit 1 ;;
esac
[[ $# -le 1 ]] || exit 1
[[ $(uname -r) != *[Mm]icrosoft* ]] || { m5_die 'never run on WSL'; exit 1; }
[[ ${M10_EXPECTED_COMMIT:-} =~ ^[0-9a-f]{40}$ ]] || { m5_die 'a reviewed full M10_EXPECTED_COMMIT is required'; exit 1; }
export M5_EXPECTED_BRANCH=m10-performance-evaluation M5_EXPECTED_COMMIT=$M10_EXPECTED_COMMIT
cd "$M5_ROOT"
m5_assert_checkout
m5_assert_headers
m5_assert_module_absent
m5_require_tools
command -v fio >/dev/null || { m5_die 'fio is required; see docs/m10-testing.md'; exit 1; }
command -v timeout >/dev/null
# Prevent two cooperating campaigns and refuse pre-existing benchmark processes.
m5_run_as_builder mkdir -p "$M5_ROOT/.cache"
exec 9>"$M5_ROOT/.cache/m10.lock"
flock -n 9 || { m5_die 'another M10 campaign owns the lock'; exit 1; }
if pgrep -x fio >/dev/null; then m5_die 'pre-existing fio process'; exit 1; fi
readonly run_root="$M5_ROOT/.cache/m10-benchmarks"
export M5_VM_RUN_DIR="$run_root/$(date -u +'%Y%m%dT%H%M%SZ')-$$"
export M5_STATUS_FILE="$M5_VM_RUN_DIR/status.tsv"
m5_prepare_evidence_directory "$run_root" "$M5_VM_RUN_DIR"
exec > >(tee -a "$M5_VM_RUN_DIR/main.log") 2>&1
readonly result_labels=('Production build' 'I/O measurements' 'Lifecycle measurements' 'Security demonstrations' 'Final production exclusion' 'Analysis' 'Kernel health' 'Final cleanup')
for label in "${result_labels[@]}"; do m5_record "$label" 'NOT RUN' 'not reached'; done
M5_DMESG_PID= M5_DMESG_STARTED=0 M5_FINALIZED=0
source "$script_dir/../tests/vm-report.sh"
m10_exit()
{
    local result=$?
    trap - EXIT
    if m5_cleanup_runtime && m5_assert_module_absent; then
        m5_record 'Final cleanup' PASS 'owned module/nodes removed; private tmpfs file cleanup checked by Python'
    else
        result=1
        m5_record 'Final cleanup' FAIL 'owned-resource cleanup failed'
    fi
    if m5_finalize "$result"; then exit 0; else exit 1; fi
}
trap m10_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf 'M10 evidence: %s\n' "$M5_VM_RUN_DIR"
python3 tests/m10-benchmarks.py plan "$M5_VM_RUN_DIR" "$mode"
capacity=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["capacity_mib"])' "$M5_VM_RUN_DIR/parameters.json")
m5_start_dmesg
m5_build_helper
m5_run_as_builder make tools
m5_build_module production
m5_prove_production production
m5_record 'Production build' PASS 'running-kernel W=1, CLI and production exclusion'
m5_load_module "$capacity"
m5_load_key "$((capacity * 1048576))"
SR_MILESTONE=9 timeout 3m python3 tests/m6-raw-io.py active > "$M5_VM_RUN_DIR/inherited-raw.log" 2>&1
timeout --signal=TERM --kill-after=15s 35m python3 tests/m10-benchmarks.py io "$M5_VM_RUN_DIR" "$mode"
m5_record 'I/O measurements' PASS 'all planned fio trials and exact data checks completed'
m5_cleanup_runtime
m5_assert_module_absent
for size in "$((capacity / 4))" "$capacity"; do
    m5_load_module "$size"
    timeout --signal=TERM --kill-after=15s 5m python3 tests/m10-benchmarks.py lifecycle "$M5_VM_RUN_DIR" "$mode"
    m5_cleanup_runtime
    m5_assert_module_absent
done
m5_record 'Lifecycle measurements' PASS 'repeated full-capacity rollback and key/generation checks'
m5_build_module demo M4_TEST=1 M5_TEST=1
m5_prove_test_build
m5_load_module "$((capacity / 4))"
timeout --signal=TERM --kill-after=15s 5m python3 tests/m10-benchmarks.py demo "$M5_VM_RUN_DIR" "$mode" > "$M5_VM_RUN_DIR/security-demo.log" 2>&1
m5_cleanup_runtime
m5_assert_module_absent
m5_record 'Security demonstrations' PASS 'M4 internal backing comparison, M5 corruption/latch/recovery, snapshot/generation checks'
m5_build_module final-production
m5_prove_production final-production
m5_record 'Final production exclusion' PASS 'final artifact excludes all M4/M5/M9 hooks'
m5_release_evidence_directory "$M5_VM_RUN_DIR"
m5_run_as_builder python3 tests/m10-analyze.py "$M5_VM_RUN_DIR"
m5_record 'Analysis' PASS 'raw trials retained; CSV statistics/analysis generated; render figures with --plots in plotting environment'
