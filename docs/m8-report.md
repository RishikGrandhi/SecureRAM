# M8 design and evidence: secure snapshots and rollback

Starting evidence: clean `main` and local `origin/main` at M7 merge `be43792`.
M7's automated VM and Firefox acceptance are recorded in its report. M8 work
is confined to `m8-secure-snapshots`; no merge or push is authorized by this task.

## Design reviewed before implementation

One optional volatile slot belongs to the existing security context. It owns a
second `secureram_store` (ciphertext plus matching 32-byte HMAC tags), the successful
key-load generation, and a publication flag. No key copy or full-device plaintext
buffer is introduced. The existing XTS/HMAC format, lifecycle and worker remain.

Create requires ACTIVE and an empty slot (EEXIST otherwise). Allocate a temporary
store with the established checked `vzalloc` strategy, copy both arrays, and only
then publish. Allocation failure frees partial resources and leaves no slot.
Restore requires ACTIVE, a published slot, equal nonzero generation and matching
geometry; all checks precede either live copy. Copies of valid kernel allocations
cannot return a recoverable copy error. Restore retains the slot. This is logical
atomicity against I/O/control observers, not crash atomicity.

All mutations use the existing control mutex, reject open block users (EBUSY),
close admission under the pending spinlock, release that lock, drain the ordered
worker, then operate and reopen only if ACTIVE. The worker never takes the
control mutex. No new lock or block-core freeze/open call is introduced. Status
takes only the control mutex. Snapshot counters share that mutex and saturate at
U64_MAX. They survive key destruction, reset on module reload, and do not alter
the existing five M6 counters or GET_STATS layout.

LOCKED/NO_KEY reject create/restore (EBUSY); status and explicit delete are
available, including INTEGRITY_FAILED. Delete is idempotent and still requires
zero block users. An integrity latch cannot be cleared by restore. Lock/unlock
retain association. Key clear frees the slot before freeing crypto, and unload
uses the same path. Store destruction uses `memzero_explicit` then `vfree` on
both arrays. Generation never wraps; existing load rejects U64_MAX. Reload loses
both slot and keys, so identifiers need not be globally unique.

ABI 1's existing structures, command encodings and JSON fields stay unchanged.
New commands 0x06..0x09 implement create, restore, delete and output-only status;
mutations use the existing 16-byte header with zero flags/reserved. A new feature
bit 16 advertises snapshots. Status carries only presence, lifecycle state,
sizes, generation and diagnostic counters, with aligned fixed-width fields and
zeroed reserved fields. Every ioctl retains the initial-namespace CAP_SYS_ADMIN
check and compat_ptr_ioctl translation.

The CLI adds `snapshot create|restore|delete|status [--json]`. The dashboard adds
fixed CLI arguments/routes, strict JSON validation and typed RESTORE/DELETE
confirmation through the existing same-origin/token protections. It owns no
snapshot implementation. Existing M6 status/stats JSON schemas remain stable.

```text
browser -> localhost adapter -> secureramctl -> privileged snapshot ioctl
  -> control mutex -> zero openers -> close gate -> drain worker
  -> security-owned slot <-> ciphertext RAM + HMAC tag RAM
  -> reopen admission only in ACTIVE
```

Default additional allocation: 64 MiB ciphertext + 512 KiB tags, plus bounded
bookkeeping/allocator overhead. Maximum at capacity_mb=256 is 258 MiB additional.
Create refuses replacement, so there is never a second candidate beside an
existing slot. No disk persistence, multi-slot manager, COW or later milestone.

## Security and consistency limits

A snapshot captures one coherent internal block-device state after prior I/O
drains. It is not an application/filesystem transaction, cache checkpoint or
filesystem freeze. Unmount/close users before capture or rollback; acceptance
uses direct raw I/O. Normal restored reads still verify HMAC before decryption.
Copying a snapshot is not an integrity scrub: latent corruption is copied and
detected on subsequent authenticated reads. Metadata/control memory and kernel
remain trusted, as in M5. Authorized rollback intentionally permits older data
within the same generation; there is no new freshness/anti-replay guarantee.
Snapshots reveal ciphertext equality at an address across time. Explicit wiping
does not promise removal of external copies, crash dumps, hypervisor snapshots,
CPU caches or physical RAM remanence.

## Verification status

Design recorded before implementation. Build/static, local automated, VM and
browser evidence will be recorded separately; no M8 runtime PASS is claimed.
