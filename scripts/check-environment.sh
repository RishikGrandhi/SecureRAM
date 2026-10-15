#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Read-only M11 preflight. It never installs packages, loads modules or writes files.
set -u

usage()
{
	printf 'Usage: sh %s [--runtime] [kernel-build-directory]\n' "$0" >&2
}

mode=build
kernel_dir=
for argument in "$@"; do
	case $argument in
		--runtime) mode=runtime ;;
		-*) usage; exit 2 ;;
		*)
			if [ -n "$kernel_dir" ]; then usage; exit 2; fi
			kernel_dir=$argument
			;;
	esac
done

kernel_release=$(uname -r 2>/dev/null || printf unknown)
if [ -z "$kernel_dir" ]; then
	kernel_dir=${KDIR:-/lib/modules/$kernel_release/build}
fi
compiler=${CC:-cc}
required_failures=0
optional_missing=0

row()
{
	label=$1
	result=$2
	detail=$3
	printf '%-30s %-10s %s\n' "$label" "$result" "$detail"
}

require_command()
{
	label=$1
	command=$2
	if command -v "$command" >/dev/null 2>&1; then
		row "$label" PASS "$(command -v "$command")"
	else
		row "$label" REQUIRED "missing '$command'; install the corresponding system package"
		required_failures=$((required_failures + 1))
	fi
}

optional_command()
{
	label=$1
	command=$2
	detail=$3
	if command -v "$command" >/dev/null 2>&1; then
		row "$label" PASS "$(command -v "$command")"
	else
		row "$label" OPTIONAL "$detail"
		optional_missing=$((optional_missing + 1))
	fi
}

printf '%s\n\n' 'SecureRAM Environment Check'
row 'Mode' INFO "$mode readiness (read-only)"

if [ "$(uname -s 2>/dev/null || printf unknown)" = Linux ]; then
	row 'Linux' PASS "$kernel_release"
else
	row 'Linux' REQUIRED 'build and runtime checks require Linux or configured WSL2'
	required_failures=$((required_failures + 1))
fi

architecture=$(uname -m 2>/dev/null || printf unknown)
case $architecture in
	x86_64|amd64) row 'Architecture' PASS "$architecture (validated project target)" ;;
	*)
		row 'Architecture' REQUIRED "$architecture is not the validated x86-64 target"
		required_failures=$((required_failures + 1))
		;;
esac

if printf '%s' "$kernel_release" | grep -qi microsoft; then
	if [ "$mode" = runtime ]; then
		row 'Runtime kernel' REQUIRED 'WSL cannot run an Ubuntu-generic SecureRAM module; use the project VM'
		required_failures=$((required_failures + 1))
	else
		row 'Runtime kernel' INFO 'WSL is compile-only; never load an Ubuntu-generic module here'
	fi
else
	row 'Runtime kernel' PASS 'non-WSL Linux kernel'
fi

require_command 'Compiler' "$compiler"
require_command 'Make' make
require_command 'Linker' ld
require_command 'Python' python3

python_result=$(python3 -c 'import sys; print("PASS" if sys.version_info >= (3, 10) else "FAIL")' 2>/dev/null || printf FAIL)
if [ "$python_result" = PASS ]; then
	row 'Python version' PASS "$(python3 -c 'import platform; print(platform.python_version())')"
else
	row 'Python version' REQUIRED 'Python 3.10 or newer is required for dashboard/tests'
	required_failures=$((required_failures + 1))
fi

headers_ok=1
for file in Makefile include/config/auto.conf include/generated/autoconf.h \
	include/generated/utsrelease.h Module.symvers; do
	[ -r "$kernel_dir/$file" ] || headers_ok=0
done
if [ "$headers_ok" -eq 1 ]; then
	target_release=$(sed -n 's/^#define UTS_RELEASE "\(.*\)"/\1/p' \
		"$kernel_dir/include/generated/utsrelease.h")
	if [ -n "$target_release" ]; then
		row 'Kernel headers' PASS "$target_release at $kernel_dir"
	else
		row 'Kernel headers' REQUIRED 'prepared tree has no readable UTS_RELEASE'
		required_failures=$((required_failures + 1))
	fi
	if [ "${target_release:-}" = "$kernel_release" ]; then
		row 'Header/kernel match' PASS "$kernel_release"
	elif [ "$mode" = runtime ]; then
		row 'Header/kernel match' REQUIRED "headers ${target_release:-unknown}; running $kernel_release"
		required_failures=$((required_failures + 1))
	else
		row 'Header/kernel match' INFO "compile-only target ${target_release:-unknown}; running $kernel_release"
	fi
	if grep -q '^CONFIG_MODULES=y$' "$kernel_dir/include/config/auto.conf"; then
		row 'Kernel modules' PASS 'target enables CONFIG_MODULES'
	else
		row 'Kernel modules' REQUIRED 'target kernel does not enable CONFIG_MODULES'
		required_failures=$((required_failures + 1))
	fi
else
	row 'Kernel headers' REQUIRED "incomplete tree: $kernel_dir"
	row 'Remediation' INFO 'install build-essential kmod and linux-headers-$(uname -r), or set KDIR'
	required_failures=$((required_failures + 1))
fi

runtime_missing=0
for command in awk bash blockdev cat chmod chown cmp date dd dmesg env find findmnt \
	git grep id insmod kill mkdir mkfs.ext4 modinfo modprobe mount mountpoint nm \
	pgrep rm rmdir rmmod runuser sed sleep stdbuf strings sync tee timeout touch \
	udevadm umount; do
	if command -v "$command" >/dev/null 2>&1 || [ -x "/usr/sbin/$command" ] || [ -x "/sbin/$command" ]; then
		:
	else
		runtime_missing=$((runtime_missing + 1))
	fi
done
if [ "$runtime_missing" -eq 0 ]; then
	row 'Required runtime tools' PASS 'kmod, udev, mount/device inspection available'
elif [ "$mode" = runtime ]; then
	row 'Required runtime tools' REQUIRED "$runtime_missing missing; install kmod/udev/util-linux packages"
	required_failures=$((required_failures + 1))
else
	row 'Required runtime tools' INFO "$runtime_missing missing; needed only for VM runtime use"
fi

if [ -r /proc/sys/kernel/modules_disabled ] && [ "$(cat /proc/sys/kernel/modules_disabled)" = 1 ]; then
	if [ "$mode" = runtime ]; then
		row 'Module loading policy' REQUIRED 'this running kernel has permanently disabled module loading'
		required_failures=$((required_failures + 1))
	else
		row 'Module loading policy' INFO 'running-kernel module loading is disabled'
	fi
else
	row 'Module loading policy' PASS 'not globally disabled; signature policy still applies'
fi

if command -v sudo >/dev/null 2>&1 || [ "$(id -u 2>/dev/null || printf 1)" -eq 0 ]; then
	row 'Runtime privilege path' PASS 'root or sudo is available; authentication is never attempted here'
elif [ "$mode" = runtime ]; then
	row 'Runtime privilege path' REQUIRED 'run as root through sudo from the checkout owner'
	required_failures=$((required_failures + 1))
else
	row 'Runtime privilege path' INFO 'sudo/root is needed only for load, demo and acceptance'
fi

optional_command 'Optional fio' fio 'install fio only to reproduce the separate M10 benchmarks'
optional_command 'Optional ShellCheck' shellcheck 'static shell lint is useful but not required to build/run'

printf '\n'
if [ "$required_failures" -ne 0 ]; then
	printf 'Environment NOT ready: %d required check(s) failed; %d optional item(s) missing.\n' \
		"$required_failures" "$optional_missing"
	exit 1
fi
printf 'Environment ready for %s use; %d optional item(s) missing.\n' "$mode" "$optional_missing"
exit 0
