#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Test-only extension to the M6 fixture; production runners never source this.
source "$script_dir/m7-vm-phases.sh"
M7_EXPECTED_COMMIT=$(git -C "$M5_ROOT" rev-parse HEAD)
m7_assert_commit_pin
for m7_bad_pin in '' "${M7_EXPECTED_COMMIT:0:7}" invalid; do
	if (M7_EXPECTED_COMMIT=$m7_bad_pin; m7_assert_commit_pin) 2>/dev/null; then
		m5_die 'non-full M7 commit pin accepted'
	fi
done
m7_cli() { mock_management "$@"; }
m7_mock_http()
{
	trace "http $*"
	local http_mode=$1 http_result=0
	shift
	case $http_mode in
		action) mock_management "$@" ;;
		busy)
			mock_management "$@" >/dev/null 2>&1 || http_result=$?
			mock_check test "$http_result" -eq 1 ;;
		observe) mock_observe "$@" ;;
		security) mock_check test "$mock_loaded" -eq 0 ;;
		*) m5_die 'unexpected HTTP test route' ;;
	esac
}
