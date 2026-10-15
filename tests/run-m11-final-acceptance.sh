#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# One-command M11 acceptance. The public entry creates a detached clean worktree.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly script_dir
readonly invocation_root=$(cd -- "$script_dir/.." && pwd -P)
export SR_MILESTONE=11
source "$script_dir/m5-vm-common.sh"

m11_internal()
{
	[[ ${M11_WORKTREE_RUN:-0} == 1 ]] || m5_die 'internal M11 worker requires its clean-worktree guard'
	m5_require_root
	[[ $# -eq 0 ]] || m5_die 'no device paths or arguments accepted'
	cd -- "$M5_ROOT"
	export M5_EXPECTED_BRANCH=DETACHED
	export M5_EXPECTED_COMMIT=${M11_EXPECTED_COMMIT:-}
	[[ $M5_EXPECTED_COMMIT =~ ^[0-9a-f]{40}$ ]] || m5_die 'M11_EXPECTED_COMMIT must be the full reviewed commit'
	[[ $(uname -r) != *[Mm]icrosoft* ]] || m5_die 'VM acceptance is forbidden on WSL'

	readonly run_root="$M5_ROOT/.cache/m11-final"
	export M5_VM_RUN_DIR="$run_root/${M11_RUN_ID:?missing M11_RUN_ID}"
	export M5_STATUS_FILE="$M5_VM_RUN_DIR/status.tsv"
	m5_prepare_evidence_directory "$run_root" "$M5_VM_RUN_DIR"
	exec > >(tee -a "$M5_VM_RUN_DIR/main.log") 2>&1
	readonly result_labels=(
		'Environment' 'Clean-checkout reproducibility' 'Build' 'Module lifecycle'
		'Block I/O' 'Encryption/key lifecycle' 'Integrity' 'Snapshots' 'CLI'
		'Dashboard backend' 'Statistics' 'Quick demo' 'Production/test isolation'
		'Cleanup' 'Kernel health'
	)
	local label
	for label in "${result_labels[@]}"; do
		m5_record "$label" 'NOT RUN' 'assertion group not reached'
	done
	M5_DMESG_PID=
	M5_DMESG_STARTED=0
	M5_FINALIZED=0
	source "$script_dir/vm-report.sh"
	trap m5_on_exit EXIT

	m5_require_tools
	command -v pgrep >/dev/null || m5_die 'required VM tool missing: pgrep'
	m5_assert_checkout
	m5_assert_headers
	m5_assert_module_absent
	printf 'M11 evidence: %s\n' "$M5_VM_RUN_DIR"
	m5_run_as_builder sh scripts/check-environment.sh --runtime
	m5_record 'Environment' PASS 'read-only runtime prerequisite check passed'
	m5_run_as_builder python3 tests/check-m11-local.py
	{
		uname -a
		printf 'source_commit=%s\nsource_mode=detached-clean-worktree\n' "$M5_EXPECTED_COMMIT"
		m5_run_as_builder git status --short --branch
	} > "$M5_VM_RUN_DIR/environment.txt"
	m5_start_dmesg

	bash scripts/demo-secureram.sh --quick
	m5_record 'Quick demo' PASS 'nine-stage production/test-labelled demo completed'

	# The session owner keeps the dashboard credential in memory and dispatches
	# m11-vm-phases.sh for representative production, snapshot and integrity checks.
	python3 tests/m7-vm-session.py
	m5_assert_module_absent
	[[ ! -e /dev/secureram0 && ! -e /dev/secureramctl ]]
	! findmnt -rn -S /dev/secureram0 >/dev/null 2>&1
	if pgrep -f '[d]ashboard/server.py' >/dev/null 2>&1; then
		m5_die 'dashboard process remains after the owned session'
	fi
	m5_record 'Cleanup' PASS 'module, nodes, mount and owned dashboard process are absent'
	m5_record 'Clean-checkout reproducibility' PASS 'detached exact-commit source completed build, demo and final integration'
}

m11_public()
{
	m5_require_root
	[[ $# -eq 0 ]] || m5_die 'no device paths or arguments accepted'
	cd -- "$invocation_root"
	[[ ${M11_EXPECTED_COMMIT:-} =~ ^[0-9a-f]{40}$ ]] ||
		m5_die 'set M11_EXPECTED_COMMIT to the reviewed 40-character candidate commit'
	local branch commit status run_id repro_root checkout inner_result=0 copy_result=0 remove_result=0
	branch=$(m5_run_as_builder git branch --show-current)
	commit=$(m5_run_as_builder git rev-parse HEAD)
	status=$(m5_run_as_builder git status --porcelain --untracked-files=normal)
	[[ $branch == m11-production-readiness ]] || m5_die "expected m11-production-readiness, found $branch"
	[[ $commit == "$M11_EXPECTED_COMMIT" ]] || m5_die "expected $M11_EXPECTED_COMMIT, found $commit"
	[[ -z $status ]] || m5_die 'acceptance requires a clean committed source checkout'
	m5_assert_module_absent

	run_id="$(date -u +'%Y%m%dT%H%M%SZ')-$$"
	repro_root="$invocation_root/.cache/m11-repro/$run_id"
	checkout="$repro_root/checkout"
	case $checkout in
		"$invocation_root/.cache/m11-repro/"*/checkout) : ;;
		*) m5_die 'internal reproducibility path escaped the repository cache' ;;
	esac
	[[ ! -e $repro_root && ! -L $repro_root ]] || m5_die 'fresh-worktree path already exists'
	[[ ! -L $invocation_root/.cache ]] || m5_die 'refusing symlinked repository cache'
	m5_run_as_builder mkdir -p -- "$repro_root"
	m5_run_as_builder git worktree add --detach "$checkout" "$M11_EXPECTED_COMMIT"

	set +e
	env M11_WORKTREE_RUN=1 M11_EXPECTED_COMMIT="$M11_EXPECTED_COMMIT" M11_RUN_ID="$run_id" \
		SUDO_USER="$M5_BUILD_USER" bash "$checkout/tests/run-m11-final-acceptance.sh"
	inner_result=$?
	set -e

	mkdir -p -- "$invocation_root/.cache/m11-final"
	if [[ -d $checkout/.cache/m11-final ]]; then
		cp -a -- "$checkout/.cache/m11-final/." "$invocation_root/.cache/m11-final/" || copy_result=1
		chown -hR -- "$M5_BUILD_USER:$M5_BUILD_GROUP" "$invocation_root/.cache/m11-final" || copy_result=1
	fi
	m5_run_as_builder git -C "$checkout" clean -fdX >/dev/null 2>&1 || true
	m5_run_as_builder git worktree remove --force "$checkout" || remove_result=1
	rmdir -- "$repro_root" 2>/dev/null || remove_result=1
	m5_run_as_builder git worktree prune

	if [[ $inner_result -ne 0 || $copy_result -ne 0 || $remove_result -ne 0 ]]; then
		printf 'M11 acceptance failed: suite=%d evidence-copy=%d worktree-cleanup=%d\n' \
			"$inner_result" "$copy_result" "$remove_result" >&2
		printf 'Evidence (if created): %s/.cache/m11-final/%s\n' "$invocation_root" "$run_id" >&2
		return 1
	fi
	printf 'M11 clean-worktree acceptance evidence: %s/.cache/m11-final/%s\n' "$invocation_root" "$run_id"
}

if [[ ${M11_WORKTREE_RUN:-0} == 1 ]]; then
	m11_internal "$@"
else
	m11_public "$@"
fi
