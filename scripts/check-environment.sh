#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Read-only preflight. Run with sh; no executable-bit dependency on Windows.
set -eu

if [ "$#" -gt 1 ]; then
	printf 'Usage: sh %s [kernel-build-directory]\n' "$0" >&2
	exit 2
fi

if [ "$(uname -s)" != Linux ]; then
	printf '%s\n' 'ERROR: build inside Linux, a Linux VM, or configured WSL2.' >&2
	exit 1
fi

kernel_release=$(uname -r)
kernel_dir=${1:-${KDIR:-/lib/modules/$kernel_release/build}}
compiler=${CC:-cc}
failed=0

printf 'Running kernel: %s\nKernel build tree: %s\n' \
	"$kernel_release" "$kernel_dir"

for tool in make "$compiler" ld; do
	if command -v "$tool" >/dev/null 2>&1; then
		printf 'OK: %s available\n' "$tool"
	else
		printf 'ERROR: %s missing from PATH\n' "$tool" >&2
		failed=1
	fi
done

for file in Makefile include/config/auto.conf include/generated/autoconf.h \
	include/generated/utsrelease.h Module.symvers; do
	if [ -r "$kernel_dir/$file" ]; then
		printf 'OK: %s\n' "$file"
	else
		printf 'ERROR: missing %s/%s\n' "$kernel_dir" "$file" >&2
		failed=1
	fi
done

if [ -r "$kernel_dir/include/config/auto.conf" ]; then
	if ! grep -q '^CONFIG_MODULES=y$' "$kernel_dir/include/config/auto.conf"; then
		printf '%s\n' 'ERROR: target kernel does not enable CONFIG_MODULES.' >&2
		failed=1
	fi
fi

if [ -r "$kernel_dir/include/generated/utsrelease.h" ]; then
	target_release=$(sed -n 's/^#define UTS_RELEASE "\(.*\)"/\1/p' \
		"$kernel_dir/include/generated/utsrelease.h")
	printf 'Target kernel: %s\n' "$target_release"
	if [ "$target_release" != "$kernel_release" ]; then
		printf '%s\n' 'NOTE: compile-only target; do not load it into this kernel.'
	fi
fi

for tool in insmod rmmod modinfo lsmod dmesg; do
	if command -v "$tool" >/dev/null 2>&1; then
		printf 'OK: runtime tool %s available\n' "$tool"
	elif [ -x "/usr/sbin/$tool" ] || [ -x "/sbin/$tool" ]; then
		printf 'NOTE: %s exists in sbin; add /usr/sbin:/sbin to PATH.\n' "$tool"
	else
		printf 'NOTE: %s missing; needed for manual runtime verification.\n' "$tool"
	fi
done

if [ -r /proc/sys/kernel/modules_disabled ]; then
	if [ "$(cat /proc/sys/kernel/modules_disabled)" = 1 ]; then
		printf '%s\n' 'NOTE: this running kernel has disabled module loading.'
	fi
fi

printf '%s\n' 'Loading also requires matching kernel ABI, module privileges, and an accepted signature policy.'
if [ "$failed" -ne 0 ]; then
	printf '%s\n' 'Build prerequisites incomplete; see docs/development.md.' >&2
else
	printf '%s\n' 'Build prerequisites found; compilation is the definitive check.'
fi
exit "$failed"
