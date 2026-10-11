#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Shared safety and lifecycle functions for the M5 Ubuntu VM acceptance scripts.
set -Eeuo pipefail

umask 077
export LC_ALL=C
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PYTHONDONTWRITEBYTECODE=1

M5_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
readonly M5_ROOT
readonly M5_DEVICE=/dev/secureram0
readonly M5_CONTROL=/dev/secureramctl
readonly M5_VERSION=0.5.0
readonly M5_UNIT=4096
readonly M5_DEFAULT_MB=64
readonly M5_CONTROL_HELPER="$M5_ROOT/.cache/m4-control"

M5_VM_RUN_DIR=${M5_VM_RUN_DIR:-}
M5_STATUS_FILE=${M5_STATUS_FILE:-}
M5_BUILD_USER=${M5_BUILD_USER:-${SUDO_USER:-}}
M5_BUILD_GROUP=${M5_BUILD_GROUP:-}
M5_MOUNT_POINT=${M5_MOUNT_POINT:-}
M5_MOUNTED_BY_HARNESS=0
M5_RUNTIME_OWNED=0
M5_EPHEMERAL_FILES=()
M5_EPHEMERAL_DIRS=()
M5_ACTIVE_CHECKS=()

m5_die()
{
	printf 'FAIL: %s\n' "$*" >&2
	return 1
}

m5_require_root()
{
	[[ ${EUID:-$(id -u)} -eq 0 ]] || m5_die "run with sudo inside the disposable Ubuntu VM"
	[[ -n $M5_BUILD_USER && $M5_BUILD_USER != root ]] ||
		m5_die "invoke with sudo from the ordinary user who owns the checkout"
	id "$M5_BUILD_USER" >/dev/null 2>&1 || m5_die "build user does not exist: $M5_BUILD_USER"
	M5_BUILD_GROUP=$(id -gn "$M5_BUILD_USER")
	[[ -n $M5_BUILD_GROUP ]] || m5_die "could not determine build user's primary group"
}

m5_require_run_context()
{
	m5_require_root
	[[ -n $M5_VM_RUN_DIR && -d $M5_VM_RUN_DIR ]] || m5_die "missing harness run directory"
	[[ -n $M5_STATUS_FILE && -f $M5_STATUS_FILE ]] || m5_die "missing harness status file"
	cd -- "$M5_ROOT"
}

m5_phase_preflight()
{
	m5_require_run_context
	m5_require_tools
	m5_assert_checkout
	m5_assert_headers
	m5_assert_module_absent
}

m5_require_tools()
{
	local tool
	for tool in awk bash cat chown chmod cmp date dd dmesg env find findmnt gcc git grep id \
		insmod kill make mkdir mkfs.ext4 mktemp modinfo modprobe mount mountpoint nm \
		python3 rm rmdir rmmod runuser sed sleep stdbuf strings sync tee touch udevadm \
		umount uname; do
		command -v "$tool" >/dev/null 2>&1 || m5_die "required VM tool missing: $tool"
	done
}

m5_record()
{
	local label=$1 status=$2 detail=${3:-}
	case $status in
		PASS|FAIL|'NOT RUN'|'NOT COMPLETED') ;;
		*) m5_die "invalid result status: $status" ;;
	esac
	[[ $detail != *$'\t'* && $detail != *$'\n'* ]] || m5_die "result detail contains a separator"
	printf '%s\t%s\t%s\n' "$label" "$status" "$detail" >> "$M5_STATUS_FILE"
}

m5_run_as_builder()
{
	runuser -u "$M5_BUILD_USER" -- env \
		PATH="$PATH" LC_ALL=C PYTHONDONTWRITEBYTECODE=1 \
		KDIR="/lib/modules/$(uname -r)/build" "$@"
}

m5_prepare_evidence_directory()
{
	local evidence_root=$1 run_directory=$2 expected_root="$M5_ROOT/.cache/m5-vm"
	local owner

	[[ $evidence_root == "$expected_root" ]] || m5_die "refusing unexpected evidence root: $evidence_root"
	[[ $run_directory == "$evidence_root/"* && $run_directory != "$evidence_root/" ]] ||
		m5_die "refusing unexpected evidence run directory: $run_directory"
	[[ ! -L $M5_ROOT/.cache ]] || m5_die "refusing symlinked repository cache directory"
	m5_run_as_builder mkdir -p -- "$M5_ROOT/.cache"
	[[ -d $M5_ROOT/.cache ]] || m5_die "repository cache path is not a directory"
	[[ ! -L $evidence_root ]] || m5_die "refusing symlinked M5 evidence root"
	[[ ! -e $evidence_root || -d $evidence_root ]] || m5_die "M5 evidence root is not a directory"

	if [[ -d $evidence_root ]]; then
		owner=$(find "$evidence_root" -maxdepth 0 -printf '%U\n')
		if [[ $owner != "$(id -u "$M5_BUILD_USER")" ]]; then
			printf 'Repairing prior M5 evidence ownership for %s\n' "$M5_BUILD_USER"
		fi
		chown -hR -- "$M5_BUILD_USER:$M5_BUILD_GROUP" "$evidence_root"
		chmod -R u+rwX,go-rwx -- "$evidence_root"
	else
		m5_run_as_builder mkdir -- "$evidence_root"
	fi

	[[ ! -e $run_directory && ! -L $run_directory ]] ||
		m5_die "evidence run directory already exists: $run_directory"
	m5_run_as_builder mkdir -- "$run_directory"
	m5_run_as_builder chmod 0700 -- "$evidence_root" "$run_directory"
	m5_run_as_builder touch -- \
		"$run_directory/status.tsv" \
		"$run_directory/main.log" \
		"$run_directory/summary.txt" \
		"$run_directory/dmesg.log" \
		"$run_directory/production.log" \
		"$run_directory/tamper.log" \
		"$run_directory/capacity.log" \
		"$run_directory/final-production.log"
}

m5_release_evidence_directory()
{
	local run_directory=$1 expected_root="$M5_ROOT/.cache/m5-vm"

	[[ $run_directory == "$expected_root/"* && $run_directory != "$expected_root/" ]] ||
		m5_die "refusing ownership change outside the M5 evidence root"
	[[ -d $run_directory && ! -L $run_directory ]] ||
		m5_die "M5 evidence run directory is unavailable or symlinked"
	chown -hR -- "$M5_BUILD_USER:$M5_BUILD_GROUP" "$run_directory"
	chmod -R u+rwX,go-rwx -- "$run_directory"
}

m5_begin_checks()
{
	local label
	[[ $# -gt 0 ]] || m5_die "m5_begin_checks requires at least one label"
	M5_ACTIVE_CHECKS=("$@")
	for label in "${M5_ACTIVE_CHECKS[@]}"; do
		m5_record "$label" 'NOT COMPLETED' 'assertion group started'
	done
}

m5_complete_checks()
{
	M5_ACTIVE_CHECKS=()
}

m5_capacity_bytes_from_mb()
{
	local requested_capacity_mb
	[[ $# -eq 1 ]] || m5_die "capacity conversion requires exactly one argument"
	requested_capacity_mb=$1
	[[ $requested_capacity_mb =~ ^[0-9]+$ ]] ||
		m5_die "capacity is not an unsigned integer: $requested_capacity_mb"
	printf '%d\n' "$((requested_capacity_mb * 1024 * 1024))"
}

m5_assert_checkout()
{
	local branch commit expected_branch=${M5_EXPECTED_BRANCH:-m5-integrity-tamper-detection}
	[[ $(uname -s) == Linux ]] || m5_die "run inside the Linux VM"
	branch=$(m5_run_as_builder git -C "$M5_ROOT" branch --show-current)
	commit=$(m5_run_as_builder git -C "$M5_ROOT" rev-parse HEAD)
	[[ $branch == "$expected_branch" ]] ||
		m5_die "expected branch $expected_branch, found $branch"
	[[ -z $(m5_run_as_builder git -C "$M5_ROOT" status --porcelain --untracked-files=normal) ]] ||
		m5_die "VM acceptance requires a clean committed checkout"
	if [[ -n ${M5_EXPECTED_COMMIT:-} ]]; then
		[[ $commit == "$M5_EXPECTED_COMMIT" ]] ||
			m5_die "expected commit $M5_EXPECTED_COMMIT, found $commit"
	fi
	printf 'Checkout: branch=%s commit=%s\n' "$branch" "$commit"
}

m5_assert_headers()
{
	local release build target
	release=$(uname -r)
	build="/lib/modules/$release/build"
	for target in Makefile include/config/auto.conf include/generated/autoconf.h \
		include/generated/utsrelease.h Module.symvers; do
		[[ -r "$build/$target" ]] || m5_die "missing running-kernel header artifact: $build/$target"
	done
	target=$(sed -n 's/^#define UTS_RELEASE "\(.*\)"/\1/p' \
		"$build/include/generated/utsrelease.h")
	[[ $target == "$release" ]] || m5_die "headers target $target, running kernel $release"
	printf 'Kernel/header match: %s\n' "$release"
}

m5_assert_module_absent()
{
	[[ ! -e /sys/module/secureram ]] || m5_die "secureram is already loaded"
	[[ ! -e $M5_DEVICE && ! -e $M5_CONTROL ]] || m5_die "stale SecureRAM device node exists"
	[[ ! -e /sys/class/block/secureram0 && ! -e /sys/class/misc/secureramctl ]] ||
		m5_die "stale SecureRAM sysfs object exists"
}

m5_wait_present()
{
	local attempt
	udevadm settle --timeout=10
	for attempt in {1..100}; do
		if [[ -b $M5_DEVICE && -c $M5_CONTROL && -e /sys/class/block/secureram0 &&
		      -e /sys/class/misc/secureramctl ]]; then
			return 0
		fi
		sleep 0.05
	done
	m5_die "SecureRAM device/control nodes did not appear"
}

m5_wait_absent()
{
	local attempt
	udevadm settle --timeout=10
	for attempt in {1..100}; do
		if [[ ! -e $M5_DEVICE && ! -e $M5_CONTROL &&
		      ! -e /sys/class/block/secureram0 && ! -e /sys/class/misc/secureramctl &&
		      ! -e /sys/module/secureram ]]; then
			return 0
		fi
		sleep 0.05
	done
	m5_die "SecureRAM nodes/sysfs/module did not disappear"
}

# Hard-coded identity guard. It accepts only /dev/secureram0 and must precede
# every raw, format, key-load, key-destroy and corruption phase.
m5_identity_guard()
{
	local expected_bytes=$1
	python3 - "$expected_bytes" <<'PY'
import os
from pathlib import Path
import stat
import sys

device = Path('/dev/secureram0')
control = Path('/dev/secureramctl')
block = Path('/sys/class/block/secureram0')
expected = int(sys.argv[1])

info = os.lstat(device)
assert stat.S_ISBLK(info.st_mode), 'SecureRAM node is not a block device'
assert not stat.S_ISLNK(info.st_mode), 'SecureRAM node must not be a symlink'
number = f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}'
assert block.joinpath('dev').read_text().strip() == number, 'block major:minor mismatch'
assert info.st_uid == 0 and info.st_gid == 0, 'block node ownership is not root:root'
assert stat.S_IMODE(info.st_mode) == 0o600, 'block node mode is not 0600'
assert Path('/sys/module/secureram/version').read_text().strip() == '0.5.0', 'wrong module version'
assert int(block.joinpath('queue/logical_block_size').read_text()) == 4096, 'wrong logical block size'
assert int(block.joinpath('size').read_text()) * 512 == expected, 'wrong advertised capacity'
assert int(Path('/sys/module/secureram/parameters/capacity_mb').read_text()) * 1024 * 1024 == expected
assert not list(block.joinpath('holders').iterdir()), 'block holders exist'
for line in Path('/proc/self/mountinfo').read_text().splitlines():
    assert line.split()[2] != number, 'SecureRAM is mounted'
for line in Path('/proc/swaps').read_text().splitlines()[1:]:
    try:
        swap = os.stat(line.split()[0])
    except FileNotFoundError:
        continue
    assert not stat.S_ISBLK(swap.st_mode) or swap.st_rdev != info.st_rdev, 'SecureRAM is swap'

ctl = os.lstat(control)
assert stat.S_ISCHR(ctl.st_mode), 'control node is not a character device'
assert not stat.S_ISLNK(ctl.st_mode), 'control node must not be a symlink'
ctl_number = f'{os.major(ctl.st_rdev)}:{os.minor(ctl.st_rdev)}'
assert Path('/sys/class/misc/secureramctl/dev').read_text().strip() == ctl_number
assert ctl.st_uid == 0 and ctl.st_gid == 0, 'control node ownership is not root:root'
assert stat.S_IMODE(ctl.st_mode) == 0o600, 'control node mode is not 0600'
print(f'PASS: identity version=0.5.0 dev={number} bytes={expected} unit=4096 unmounted no-holders no-swap')
PY
}

m5_assert_mounted_identity()
{
	local expected_bytes=$1 mount_point=$2 number mounted_number
	[[ -b $M5_DEVICE ]] || m5_die "SecureRAM block node disappeared while mounted"
	number=$(< /sys/class/block/secureram0/dev)
	mounted_number=$(findmnt -rn -o MAJ:MIN --target "$mount_point")
	[[ $mounted_number == "$number" ]] || m5_die "mount point is not the verified SecureRAM device"
	[[ $(< /sys/module/secureram/version) == "$M5_VERSION" ]] || m5_die "wrong mounted module version"
	[[ $(( $(< /sys/class/block/secureram0/size) * 512 )) -eq expected_bytes ]] ||
		m5_die "mounted capacity changed"
	[[ -z $(find /sys/class/block/secureram0/holders -mindepth 1 -maxdepth 1 -print -quit) ]] ||
		m5_die "mounted SecureRAM has an unexpected holder"
}

m5_register_ephemeral_file()
{
	M5_EPHEMERAL_FILES+=("$1")
}

m5_register_ephemeral_dir()
{
	M5_EPHEMERAL_DIRS+=("$1")
}

m5_query()
{
	local output token key value count=0
	M5_Q_ABI= M5_Q_STATE= M5_Q_BYTES= M5_Q_UNIT= M5_Q_GENERATION= M5_Q_FEATURES=
	output=$($M5_CONTROL_HELPER query)
	printf '%s\n' "$output"
	for token in $output; do
		key=${token%%=*}
		value=${token#*=}
		[[ $value =~ ^[0-9]+$ ]] || m5_die "malformed query token: $token"
		case $key in
		ABI) M5_Q_ABI=$value ;;
		state) M5_Q_STATE=$value ;;
		bytes) M5_Q_BYTES=$value ;;
		unit) M5_Q_UNIT=$value ;;
		generation) M5_Q_GENERATION=$value ;;
		features) M5_Q_FEATURES=$value ;;
		*) m5_die "unknown query token: $token" ;;
		esac
		((count += 1))
	done
	[[ $count -eq 6 ]] || m5_die "query returned $count fields, expected 6"
	[[ $M5_Q_ABI == 1 && $M5_Q_UNIT == 4096 && $M5_Q_FEATURES == 7 ]] ||
		m5_die "unexpected ABI/unit/features in query"
}

m5_assert_query()
{
	local expected_state=$1 expected_generation=$2 expected_bytes=$3
	m5_query
	[[ $M5_Q_STATE == "$expected_state" ]] ||
		m5_die "expected state $expected_state, found $M5_Q_STATE"
	[[ $M5_Q_GENERATION == "$expected_generation" ]] ||
		m5_die "expected generation $expected_generation, found $M5_Q_GENERATION"
	[[ $M5_Q_BYTES == "$expected_bytes" ]] ||
		m5_die "expected capacity $expected_bytes, found $M5_Q_BYTES"
}

m5_build_helper()
{
	m5_run_as_builder mkdir -p -- "$M5_ROOT/.cache"
	m5_run_as_builder gcc -std=c11 -O2 -Wall -Wextra -Werror -Wconversion \
		-Iinclude tests/m4-control.c -o .cache/m4-control
	[[ -x $M5_CONTROL_HELPER ]] || m5_die "control helper was not built"
}

m5_build_module()
{
	local label=$1
	shift
	m5_assert_module_absent
	m5_run_as_builder make clean
	m5_run_as_builder make W=1 "$@" 2>&1 | tee "$M5_VM_RUN_DIR/build-$label.log"
	[[ -f secureram.ko ]] || m5_die "module build did not produce secureram.ko"
	[[ $(modinfo -F version ./secureram.ko) == "$M5_VERSION" ]] || m5_die "wrong module metadata version"
	[[ $(modinfo -F vermagic ./secureram.ko) == "$(uname -r) "* ]] ||
		m5_die "module vermagic does not match running kernel"
	modinfo -F depends ./secureram.ko | grep -Eq '(^|,)hkdf(,|$)' || m5_die "module lacks hkdf dependency"
	if grep -E '(^|/)(src|include)/.*warning:' "$M5_VM_RUN_DIR/build-$label.log"; then
		m5_die "driver source warning in $label build"
	fi
}

m5_prove_production()
{
	local label=$1
	nm secureram.ko > "$M5_VM_RUN_DIR/$label-nm.log"
	strings secureram.ko > "$M5_VM_RUN_DIR/$label-strings.log"
	if grep -Ei 'tamper|secureram_test_binding' "$M5_VM_RUN_DIR/$label-nm.log"; then
		m5_die "production module contains a tamper/test-binding symbol"
	fi
	if grep -E 'M[45] test|secureram_.*tamper|SECURERAM_IOC_TAMPER' \
		"$M5_VM_RUN_DIR/$label-strings.log"; then
		m5_die "production module contains a test string/handler name"
	fi
	printf '%s\n' 'PASS: production module has no M4/M5 test strings or tamper symbols'
}

m5_prove_test_build()
{
	nm secureram.ko > "$M5_VM_RUN_DIR/test-nm.log"
	strings secureram.ko > "$M5_VM_RUN_DIR/test-strings.log"
	grep -q 'secureram_block_tamper' "$M5_VM_RUN_DIR/test-nm.log" ||
		m5_die "test build lacks tamper handler"
	grep -q 'M5 test: unit and generation binding PASS' "$M5_VM_RUN_DIR/test-strings.log" ||
		m5_die "test build lacks M5 binding diagnostic"
	grep -q 'M4 test:' "$M5_VM_RUN_DIR/test-strings.log" ||
		m5_die "combined test build lacks M4 diagnostics"
	printf '%s\n' 'PASS: combined M5/M4 test handlers and diagnostics are present'
}

m5_load_module()
{
	local requested_capacity_mb calculated_capacity_bytes
	requested_capacity_mb=$1
	calculated_capacity_bytes=$(m5_capacity_bytes_from_mb "$requested_capacity_mb")
	m5_assert_module_absent
	modprobe hkdf
	insmod ./secureram.ko "capacity_mb=$requested_capacity_mb"
	M5_RUNTIME_OWNED=1
	m5_wait_present
	m5_identity_guard "$calculated_capacity_bytes"
}

m5_load_key()
{
	local expected_bytes=$1
	m5_identity_guard "$expected_bytes"
	"$M5_CONTROL_HELPER" load-test-key
}

m5_destroy_key()
{
	local expected_bytes=$1
	m5_identity_guard "$expected_bytes"
	"$M5_CONTROL_HELPER" destroy
}

m5_run_raw()
{
	local expected_bytes=$1 mode=$2
	m5_identity_guard "$expected_bytes"
	python3 tests/m5-raw-io.py "$mode"
}

m5_expect_control_busy()
{
	local command=$1 expected_state=$2 expected_generation=$3 expected_bytes=$4 output result
	m5_identity_guard "$expected_bytes"
	set +e
	output=$($M5_CONTROL_HELPER "$command" 2>&1)
	result=$?
	set -e
	printf '%s\n' "$output"
	[[ $result -ne 0 ]] || m5_die "$command unexpectedly succeeded"
	grep -q 'Device or resource busy' <<< "$output" || m5_die "$command failed without EBUSY"
	m5_assert_query "$expected_state" "$expected_generation" "$expected_bytes"
}

m5_assert_mounted_transitions_busy()
{
	local expected_capacity_bytes=$1
	"$M5_CONTROL_HELPER" busy
	m5_assert_query 2 2 "$expected_capacity_bytes"
}

m5_run_production_ext4()
{
	local expected_capacity_bytes=$1 mount_point=$2
	local expected_file="$M5_VM_RUN_DIR/expected-check.txt"
	local content='SecureRAM M5 authenticated backing, normal filesystem I/O'

	m5_identity_guard "$expected_capacity_bytes"
	mkfs.ext4 -q -E nodiscard "$M5_DEVICE"
	mount "$M5_DEVICE" "$mount_point"
	M5_MOUNTED_BY_HARNESS=1
	m5_assert_mounted_identity "$expected_capacity_bytes" "$mount_point"
	printf '%s\n' "$content" > "$mount_point/check.txt"
	m5_register_ephemeral_file "$expected_file"
	printf '%s\n' "$content" > "$expected_file"
	sync -f "$mount_point/check.txt"
	cmp -- "$expected_file" "$mount_point/check.txt"
	m5_assert_mounted_identity "$expected_capacity_bytes" "$mount_point"
	m5_assert_mounted_transitions_busy "$expected_capacity_bytes"
	cmp -- "$expected_file" "$mount_point/check.txt"
	m5_safe_unmount
	m5_identity_guard "$expected_capacity_bytes"
	mount "$M5_DEVICE" "$mount_point"
	M5_MOUNTED_BY_HARNESS=1
	m5_assert_mounted_identity "$expected_capacity_bytes" "$mount_point"
	cmp -- "$expected_file" "$mount_point/check.txt"
	m5_safe_unmount
	rm -f -- "$expected_file"
}

m5_unload_owned()
{
	[[ $M5_RUNTIME_OWNED -eq 1 ]] || return 0
	rmmod secureram
	M5_RUNTIME_OWNED=0
	m5_wait_absent
}

m5_safe_unmount()
{
	local number mounted_number
	[[ $M5_MOUNTED_BY_HARNESS -eq 1 ]] || return 0
	[[ -n $M5_MOUNT_POINT ]] || m5_die "mount ownership set without mount point"
	if mountpoint -q -- "$M5_MOUNT_POINT"; then
		[[ -b $M5_DEVICE && -r /sys/class/block/secureram0/dev ]] ||
			m5_die "refusing unmount: SecureRAM identity unavailable"
		number=$(< /sys/class/block/secureram0/dev)
		mounted_number=$(findmnt -rn -o MAJ:MIN --target "$M5_MOUNT_POINT")
		[[ $mounted_number == "$number" ]] ||
			m5_die "refusing unmount: harness mount point identity changed"
		umount -- "$M5_MOUNT_POINT"
	fi
	M5_MOUNTED_BY_HARNESS=0
}

m5_cleanup_runtime()
{
	local result=0 cleanup_capacity_bytes
	set +e
	if ! m5_safe_unmount; then
		printf '%s\n' 'CLEANUP FAIL: could not safely unmount harness mount' >&2
		result=1
	fi
	if ((${#M5_EPHEMERAL_FILES[@]})); then
		rm -f -- "${M5_EPHEMERAL_FILES[@]}" || result=1
	fi
	if ((${#M5_EPHEMERAL_DIRS[@]})); then
		local ephemeral_dir
		for ephemeral_dir in "${M5_EPHEMERAL_DIRS[@]}"; do
			[[ -e $ephemeral_dir || -L $ephemeral_dir ]] || continue
			rmdir -- "$ephemeral_dir" 2>/dev/null || result=1
		done
	fi
	if [[ $M5_RUNTIME_OWNED -eq 1 && -e /sys/module/secureram ]]; then
		cleanup_capacity_bytes=0
		if [[ -r /sys/class/block/secureram0/size ]]; then
			cleanup_capacity_bytes=$(( $(< /sys/class/block/secureram0/size) * 512 ))
		fi
		if [[ $cleanup_capacity_bytes -gt 0 ]] &&
		   m5_identity_guard "$cleanup_capacity_bytes"; then
			if [[ -x $M5_CONTROL_HELPER ]]; then
				"$M5_CONTROL_HELPER" destroy || result=1
			else
				result=1
			fi
			rmmod secureram || result=1
			udevadm settle --timeout=10 || result=1
		else
			printf '%s\n' 'CLEANUP FAIL: refusing key destruction/unload after identity failure' >&2
			result=1
		fi
	fi
	set -e
	return "$result"
}

m5_phase_exit()
{
	local original=$1 cleanup=0 label
	trap - EXIT
	if [[ $original -ne 0 ]] && ((${#M5_ACTIVE_CHECKS[@]})); then
		for label in "${M5_ACTIVE_CHECKS[@]}"; do
			m5_record "$label" FAIL 'phase aborted during this assertion group'
		done
	fi
	if ! m5_cleanup_runtime; then
		cleanup=1
	fi
	if [[ $original -ne 0 || $cleanup -ne 0 ]]; then
		printf 'Phase failed: command_status=%d cleanup_status=%d\n' "$original" "$cleanup" >&2
		exit 1
	fi
	exit 0
}

