#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Deterministic professor-facing demonstration. Destructive only to /dev/secureram0.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly script_dir
readonly root=$(cd -- "$script_dir/.." && pwd -P)
export SR_MILESTONE=11
source "$root/tests/m5-vm-common.sh"

mode=${1:---quick}
case $mode in
	--quick) capacity_mb=8 ;;
	--full) capacity_mb=64 ;;
	--help)
		printf '%s\n' \
			'Usage: sudo ./scripts/demo-secureram.sh --quick|--full' \
			'  --quick  bounded professor demo using an 8 MiB device' \
			'  --full   same demo plus the inherited full direct-I/O oracle at 64 MiB'
		exit 0
		;;
	*) printf '%s\n' 'Use --quick, --full or --help.' >&2; exit 2 ;;
esac

m5_require_root
[[ $(uname -r) != *[Mm]icrosoft* ]] || m5_die 'demo is forbidden on WSL; use the disposable Ubuntu VM'
m5_require_tools
m5_assert_headers
m5_assert_module_absent

run_id="demo-$(date -u +'%Y%m%dT%H%M%SZ')-$$"
readonly run_root="$root/.cache/m11-final"
export M5_VM_RUN_DIR="$run_root/$run_id"
export M5_STATUS_FILE="$M5_VM_RUN_DIR/status.tsv"
m5_prepare_evidence_directory "$run_root" "$M5_VM_RUN_DIR"
readonly demo_log="$M5_VM_RUN_DIR/demo.log"
exec > >(tee -a "$demo_log") 2>&1

demo_dmesg_pid=
cleanup()
{
	local original=$? cleanup_result=0
	trap - EXIT INT TERM
	if [[ -n $demo_dmesg_pid ]] && kill -0 "$demo_dmesg_pid" 2>/dev/null; then
		kill -TERM "$demo_dmesg_pid" 2>/dev/null || true
		wait "$demo_dmesg_pid" 2>/dev/null || true
	fi
	if ! m5_cleanup_runtime; then cleanup_result=1; fi
	m5_release_evidence_directory "$M5_VM_RUN_DIR" || cleanup_result=1
	if [[ $original -ne 0 || $cleanup_result -ne 0 ]]; then
		printf '%s\n' 'SECURERAM DEMONSTRATION FAILED; cleanup/evidence details are above.' >&2
		exit 1
	fi
}
trap cleanup EXIT INT TERM

step=0
pass()
{
	step=$((step + 1))
	printf '[%d/9] %-42s PASS\n' "$step" "$1"
}

capacity_bytes=$((capacity_mb * 1024 * 1024))
expected="$M5_VM_RUN_DIR/recognizable-a.bin"
overwrite="$M5_VM_RUN_DIR/recognizable-b.bin"
readback="$M5_VM_RUN_DIR/readback.bin"
m5_register_ephemeral_file "$expected"
m5_register_ephemeral_file "$overwrite"
m5_register_ephemeral_file "$readback"
m5_run_as_builder python3 -c \
	'from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes((b"SecureRAM professor demo: authenticated encrypted block storage\n" * 80)[:4096].ljust(4096, b".")); Path(sys.argv[2]).write_bytes((b"SecureRAM snapshot overwrite stage\n" * 120)[:4096].ljust(4096, b"!"))' \
	"$expected" "$overwrite"

m5_build_module demo-production
m5_run_as_builder make tools-clean
m5_run_as_builder make tools
sh "$root/scripts/check-production-build.sh" "$root/secureram.ko"
pass 'Production build and test isolation'

m5_load_module "$capacity_mb"
"$root/tools/secureramctl" load-random
pass 'Load device and install ephemeral key'

m5_identity_guard "$capacity_bytes"
if [[ $mode == --full ]]; then
	python3 "$root/tests/m6-raw-io.py" active
fi
dd if="$expected" of=/dev/secureram0 bs=4096 count=1 oflag=direct conv=fsync status=none
dd if=/dev/secureram0 of="$readback" bs=4096 count=1 iflag=direct status=none
cmp -- "$expected" "$readback"
pass 'Authenticated block write and exact readback'

"$root/tools/secureramctl" snapshot create --json
dd if="$overwrite" of=/dev/secureram0 bs=4096 count=1 oflag=direct conv=fsync status=none
"$root/tools/secureramctl" snapshot restore --json
dd if=/dev/secureram0 of="$readback" bs=4096 count=1 iflag=direct status=none
cmp -- "$expected" "$readback"
pass 'Encrypted snapshot overwrite and rollback'

"$root/tools/secureramctl" lock
if dd if=/dev/secureram0 of=/dev/null bs=4096 count=1 iflag=direct status=none 2>/dev/null; then
	m5_die 'block read unexpectedly succeeded while LOCKED'
fi
"$root/tools/secureramctl" unlock
dd if=/dev/secureram0 of="$readback" bs=4096 count=1 iflag=direct status=none
cmp -- "$expected" "$readback"
pass 'Key lock denial and unlock retention'

"$root/tools/secureramctl" status
"$root/tools/secureramctl" stats
pass 'Status, generation and statistics'

"$root/tools/secureramctl" destroy
m5_unload_owned
pass 'Production lifecycle cleanup'

printf '%s\n' '      TEST-ONLY: enabling bounded M4/M5 verification hooks; never a production build.'
m5_build_helper
m5_build_module demo-test M4_TEST=1 M5_TEST=1
m5_prove_test_build
stdbuf -oL -eL dmesg --follow-new --color=never > "$M5_VM_RUN_DIR/test-dmesg.log" 2>&1 &
demo_dmesg_pid=$!
demo_marker="secureram: M11-demo-start-$$"
marker_seen=0
for _attempt in {1..100}; do
	kill -0 "$demo_dmesg_pid" 2>/dev/null || m5_die 'fresh demo kernel-log capture exited'
	printf '<6>%s\n' "$demo_marker" > /dev/kmsg
	sleep 0.05
	if grep -Fq "$demo_marker" "$M5_VM_RUN_DIR/test-dmesg.log"; then
		marker_seen=1
		break
	fi
done
[[ $marker_seen -eq 1 ]] || m5_die 'fresh demo kernel-log capture did not acknowledge its marker'
m5_load_module "$capacity_mb"
python3 "$root/tests/m11-demo-integrity.py"
for _attempt in {1..100}; do
	if grep -Fq 'M4 test: real WRITE backing equals ciphertext and differs from plaintext' \
		"$M5_VM_RUN_DIR/test-dmesg.log"; then
		break
	fi
	sleep 0.05
done
kill -TERM "$demo_dmesg_pid"
wait "$demo_dmesg_pid" 2>/dev/null || true
demo_dmesg_pid=
grep -Fq 'M4 test: real WRITE backing equals ciphertext and differs from plaintext' \
	"$M5_VM_RUN_DIR/test-dmesg.log"
pass 'TEST-ONLY confidentiality and integrity checks'

m5_unload_owned
m5_build_module demo-final-production
sh "$root/scripts/check-production-build.sh" "$root/secureram.ko"
m5_assert_module_absent
pass 'Restore production artifact and final cleanup'

printf '\n%s\nEvidence: %s\n' 'SECURERAM DEMONSTRATION COMPLETE' "$M5_VM_RUN_DIR"
