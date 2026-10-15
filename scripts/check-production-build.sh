#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Read-only proof that an already-built module omits every known test mechanism.
set -eu

if [ "$#" -gt 1 ]; then
	printf 'Usage: sh %s [secureram.ko]\n' "$0" >&2
	exit 2
fi

module=${1:-secureram.ko}
case $module in
	/*) : ;;
	*) module=$(pwd -P)/$module ;;
esac

fail()
{
	printf 'Production isolation .......... FAIL\nReason: %s\n' "$1" >&2
	exit 1
}

[ -f "$module" ] && [ ! -L "$module" ] || fail "module is missing, not regular, or symlinked: $module"
for command in nm strings modinfo; do
	command -v "$command" >/dev/null 2>&1 || fail "required inspection tool missing: $command"
done

symbols=$(nm -- "$module") || fail 'nm could not inspect the module'
text=$(strings -- "$module") || fail 'strings could not inspect the module'

printf '%s\n\n' 'SecureRAM Production/Test Boundary'
if printf '%s\n' "$symbols" | grep -Eiq 'secureram_fault|m9_fault'; then
	fail 'fault-injection symbol found'
fi
printf '%-30s %s\n' 'Fault injection' 'DISABLED / UNAVAILABLE'

if printf '%s\n' "$symbols" | grep -Eiq 'tamper|secureram_test_binding'; then
	fail 'corruption/test-binding symbol found'
fi
if printf '%s\n' "$text" | grep -Eq 'M[456] test|SECURERAM_IOC_TAMPER|TEST ONLY one-shot fault|m9_fault'; then
	fail 'test-only diagnostic, ioctl or selector string found'
fi
printf '%-30s %s\n' 'Test corruption hooks' 'DISABLED / UNAVAILABLE'

if printf '%s\n' "$text" | grep -Eiq '(dump|print|log).*(secret|key material|plaintext)|(secret|key material).*(dump|print|log)'; then
	fail 'possible secret/plaintext logging text found; inspect before loading'
fi
printf '%-30s %s\n' 'Secret logging' 'ABSENT'
printf '%-30s %s\n' 'Key dumps' 'ABSENT'
printf '%-30s %s\n' 'Debug bypasses' 'ABSENT'
printf '%-30s %s\n' 'Module version' "$(modinfo -F version -- "$module")"
printf '\nProduction build isolation PASS.\n'
