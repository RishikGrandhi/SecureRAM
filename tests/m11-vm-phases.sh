#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Representative final integration: accepted helpers, no M9 stress or M10 benchmarks.
set -Eeuo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly script_dir
export SR_MILESTONE=11
source "$script_dir/m5-vm-common.sh"
source "$script_dir/m6-vm-phases.sh"
source "$script_dir/m7-vm-phases.sh"
source "$script_dir/m8-vm-phases.sh"

[[ $# -eq 0 ]] || m5_die 'no phase arguments accepted'
[[ -n ${M7_ORIGIN:-} && -n ${M7_TOKEN:-} ]] || m5_die 'run through the M11 dashboard session owner'
[[ ${M11_EXPECTED_COMMIT:-} =~ ^[0-9a-f]{40}$ ]] || m5_die 'M11_EXPECTED_COMMIT must be the reviewed full commit'

m6_run_phase m7_production 2>&1 | tee "$M5_VM_RUN_DIR/production.log"
m5_record 'Build' PASS 'production module and CLI built with inherited warning checks'
m5_record 'Module lifecycle' PASS 'NO_KEY/load/key transitions/ext4/unload completed'
m5_record 'Block I/O' PASS 'direct raw and ext4 assertions completed'
m5_record 'Encryption/key lifecycle' PASS 'load, lock, unlock, destroy and rekey assertions completed'
m5_record 'CLI' PASS 'help/version/human/JSON/error contracts completed'
m5_record 'Dashboard backend' PASS 'real loopback backend/API/security assertions completed'
m5_record 'Statistics' PASS 'baseline, accounting and retention assertions completed'

m6_run_phase m8_snapshot 2>&1 | tee "$M5_VM_RUN_DIR/snapshot.log"
m5_record 'Snapshots' PASS 'rollback, UAPI, HTTP and reload assertions completed'

m6_run_phase m7_tamper 2>&1 | tee "$M5_VM_RUN_DIR/tamper.log"
m5_record 'Integrity' PASS 'bounded test-only corruption, latch and recovery assertions completed'

m6_run_phase m6_final 2>&1 | tee "$M5_VM_RUN_DIR/final-production.log"
m5_record 'Production/test isolation' PASS 'final artifact excludes M4/M5/M9 hooks and passed production regression'
