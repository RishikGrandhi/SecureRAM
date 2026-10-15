#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Guarded convenience commands for a reviewed production module artifact.
set -eu

if [ "$#" -ne 1 ]; then
	printf 'Usage: sh %s load|status|unload\n' "$0" >&2
	exit 2
fi

action=$1
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
root=$(CDPATH= cd -- "$script_dir/.." && pwd -P)
module=$root/secureram.ko
control=$root/tools/secureramctl
capacity=${CAPACITY_MB:-64}
path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
PATH=$path
export PATH LC_ALL=C

fail()
{
	printf 'SecureRAM %s: FAIL: %s\n' "$action" "$1" >&2
	exit 1
}

[ "$(uname -s)" = Linux ] || fail 'Linux is required'
[ "$(id -u)" -eq 0 ] || fail 'run this lifecycle command through sudo'
case $capacity in
	''|*[!0-9]*) fail 'CAPACITY_MB must be an integer from 1 through 256' ;;
esac
[ "$capacity" -ge 1 ] && [ "$capacity" -le 256 ] || fail 'CAPACITY_MB must be from 1 through 256'

case $action in
	load)
		if [ -d /sys/module/secureram ]; then
			printf '%s\n' 'SecureRAM load: already loaded; no change made.'
			exit 0
		fi
		[ ! -e /dev/secureram0 ] && [ ! -e /dev/secureramctl ] ||
			fail 'stale device node exists while the module is absent; inspect it manually'
		[ -r "$module" ] || fail 'secureram.ko is missing; build as the ordinary checkout owner first'
		sh "$script_dir/check-production-build.sh" "$module"
		modprobe hkdf || fail 'could not load the matching-kernel hkdf dependency'
		insmod "$module" "capacity_mb=$capacity" || fail 'insmod failed; inspect fresh kernel logs and signature policy'
		udevadm settle --timeout=10 || fail 'udev did not settle'
		[ -b /dev/secureram0 ] && [ -c /dev/secureramctl ] || fail 'expected device nodes did not appear'
		printf 'SecureRAM load: PASS (%s MiB, production build).\n' "$capacity"
		;;
	status)
		if [ ! -d /sys/module/secureram ]; then
			[ ! -e /dev/secureram0 ] && [ ! -e /dev/secureramctl ] ||
				fail 'module is absent but a stale SecureRAM node exists'
			printf '%s\n' 'SecureRAM status: UNLOADED'
			exit 0
		fi
		[ -x "$control" ] || fail 'management CLI is missing; build it with make tools'
		"$control" status
		;;
	unload)
		if [ ! -d /sys/module/secureram ]; then
			[ ! -e /dev/secureram0 ] && [ ! -e /dev/secureramctl ] ||
				fail 'module is absent but a stale SecureRAM node exists; refusing automatic deletion'
			printf '%s\n' 'SecureRAM unload: already unloaded; no change made.'
			exit 0
		fi
		if findmnt -rn -S /dev/secureram0 >/dev/null 2>&1; then
			fail '/dev/secureram0 is mounted; unmount it explicitly before unload'
		fi
		rmmod secureram || fail 'rmmod failed; close block/control users and never force unload'
		udevadm settle --timeout=10 || fail 'udev did not settle after unload'
		[ ! -e /sys/module/secureram ] && [ ! -e /dev/secureram0 ] && [ ! -e /dev/secureramctl ] ||
			fail 'module or device nodes remain after unload'
		printf '%s\n' 'SecureRAM unload: PASS; volatile keys, snapshot and storage were discarded.'
		;;
	*)
		printf 'Usage: sh %s load|status|unload\n' "$0" >&2
		exit 2
		;;
esac
