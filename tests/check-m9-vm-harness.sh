#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$script_dir/m9-vm-phases.sh"
m5_die() { printf 'FAIL: %s\n' "$*" >&2; return 1; }
for bad in '' short invalid; do
	if (M9_EXPECTED_COMMIT=$bad; m9_parameters) 2>/dev/null; then exit 1; fi
done
M9_EXPECTED_COMMIT=$(git rev-parse HEAD)
m9_parameters
[[ $M9_IO_ROUNDS == 32 && $M9_CYCLES == 12 && $M9_RELOADS == 10 ]]
for bad in 0 -1 02 2049 text; do
	if (M9_CYCLES=$bad; m9_parameters) 2>/dev/null; then exit 1; fi
done
(unset M9_IO_ROUNDS M9_CYCLES M9_RELOADS; M9_MODE=extended; m9_parameters
 [[ $M9_IO_ROUNDS == 256 && $M9_CYCLES == 100 && $M9_RELOADS == 50 ]])
trace= loaded=0 fail_suite=0
m5_begin_checks() { trace+="|begin $*"; }
m6_done() { trace+='|done'; }
m5_load_module() { [[ $loaded == 0 && $1 == 8 ]]; loaded=1; trace+='|load'; }
m5_identity_guard() { [[ $loaded == 1 && $1 == 8388608 ]]; trace+='|identity'; }
m5_unload_owned() { [[ $loaded == 1 ]]; loaded=0; trace+='|unload'; }
m9_suite() { [[ $fail_suite == 0 ]]; trace+="|suite $1"; }
m9_stress
[[ $loaded == 0 && $trace == *'|suite io|done'* && $trace == *'|suite races|done'* &&
   $trace == *'|suite snapshots|done'* && $trace == *'|suite keys|done'* &&
   $trace == *'|suite invalid|done|unload' ]]
export -f m5_load_module m5_identity_guard m5_unload_owned m5_begin_checks m6_done m9_suite m9_stress
if bash -ec 'trace=; loaded=0; fail_suite=1; m9_stress; echo BAD-SUCCESS' >/dev/null; then
	m5_die 'stress failure was swallowed'
fi
bash "$script_dir/check-m9-health.sh"
printf '%s\n' 'PASS: M9 pin/config validation, phase execution/order and failure propagation (mocked)'
