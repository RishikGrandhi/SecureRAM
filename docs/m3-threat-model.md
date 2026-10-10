# M3 threat model and security invariants

Date: 2026-10-10 (Asia/Calcutta). This is a design for later milestones, with
the current implementation distinguished throughout. **M3 still stores
plaintext.** Its security layer only forwards checked transfers to the M2 RAM
store. M1/M2 VM acceptance remains recorded in [the M2 report](m2-report.md),
and M3's successful plaintext regression is recorded in
[the M3 report](m3-report.md). None establishes a cryptographic guarantee.

## Assets, trust, and protection boundary

The future confidentiality target is user data in the driver-owned backing
allocation when that allocation alone is disclosed, without the key or other
plaintext copies. Future integrity targets unauthorized changes to stored
units and their metadata. Keys, expanded key schedules, transient plaintext,
device state, request completion, and kernel memory safety are also assets.

Trust the kernel, Crypto API/provider, boot configuration, administrators,
hardware, and hypervisor. Device-node and filesystem permissions determine
who may receive plaintext through legitimate reads. Being inside the kernel
does not itself establish security. A process allowed to read a mounted file
or the block device receives plaintext by design, even after encryption.

The boundary is **not all RAM**. Applications, page cache, filesystem buffers,
copies made by the crypto provider, and external VM facilities are separate.
No persistence or recovery after unload/crash is promised. This is an
educational design, not an audited replacement for dm-crypt.

## Threat assessment

"In scope" means a future design requirement, not a capability delivered by
M3. "Partial" identifies a narrower mitigation, with a residual exposure.

| Threat | Classification | M3 evidence and future treatment |
| --- | --- | --- |
| Ordinary unauthorized userspace process | Partial | Linux device/filesystem permissions apply now. Later restrict the management endpoint to host administration. Encryption does not replace data-path permissions or revoke already copied plaintext. |
| Accidental disclosure of backing RAM alone | In scope for future confidentiality | M3 exposes plaintext if its backing bytes leak. Future backing must contain ciphertext only; isolate keys and metadata from that allocation. A leak including keys defeats this protection. |
| Raw backing RAM contains recognizable user data | In scope for future confidentiality | Present in M3. Later encrypt every written unit and initialize valid encrypted zero units before activation; no plaintext bypass. |
| Stale bytes after orderly teardown/replacement | Partial | M3 uses ordinary `vfree()`, with no secure-wipe guarantee. Later explicitly clear driver-owned keys, staging buffers, and backing before release. Copies outside driver ownership and hardware remanence remain. |
| Unauthorized control operations | In scope for future control | M3 exposes no control ABI. Later check permissions on every ioctl, including status; validate state transitions. A passed control fd must not bypass capability checks. |
| Malicious or buggy userspace clients | In scope for interface robustness | Preserve capacity, arithmetic, segment and opcode validation. Later validate fixed-size ABI input, reserved bits, copy faults and key lengths. Allocation failure must unwind. No guarantee against arbitrary kernel bugs or resource-exhaustion denial of service. |
| Concurrent I/O and administration | In scope for correctness | M3 retains the pending-list lock and sole ordered worker. Later gate admission, drain accepted work, and only then change keys. No mixing key generations in one request. |
| Invalid block requests | In scope for memory safety | Check entire request geometry and segment totals before any copy; store rechecks byte ranges. Unsupported requests fail. Ordinary user tests may be rejected by the block core before reaching these guards. |
| Ciphertext tampering, substitution or replay | Future integrity; currently unmitigated | Neither M3 nor the selected future XTS mode authenticates bytes. Later tags must bind address and generation. Full rollback needs trusted freshness outside replayable RAM. |
| Kernel crash, panic, power loss | Out of scope for cleanup/durability | Cleanup callbacks may never execute. Contents can disappear or remain in dumps/remanent RAM. No crash-safe transactions, persistence, or assured erasure. |
| Privileged/root attacker | Out of scope | A hostile administrator can change permissions, inspect memory, load code, or capture plaintext/key input. Checking host `CAP_SYS_ADMIN` constrains ordinary callers, not hostile root. |
| Malicious kernel module or compromised kernel | Out of scope | Kernel code can read keys, change state, bypass checks, or redirect I/O. |
| Physical memory acquisition | Out of scope for whole-system protection | A backing-only sample may benefit from future encryption; physical access to keys/plaintext elsewhere defeats it. |
| Cold-boot/remanence | Out of scope | Volatility is not erasure; explicit clearing after orderly teardown is not a hardware remanence guarantee. |
| VM/hypervisor compromise, snapshots, host swap | Out of scope | The host may capture or restore all guest RAM, including keys and counters. Guest encryption cannot defend against that trust boundary. |
| Guest swap and hibernation | Partial | `vzalloc()` backing is kernel memory, not ordinary swappable userspace pages. Application plaintext/key input may swap, and hibernation can capture kernel secrets. Do not use SecureRAM as swap; no dedicated anti-swap or hibernation policy exists in M3. |
| DMA-capable devices | Out of scope | Platform IOMMU/device isolation is an external defense. No DMA buffers are introduced by M3; future provider/hardware copies require review. |
| Crash dumps/core dumps | Partial operational mitigation | Kernel dumps can include backing/keys; user core dumps can include input secrets/plaintext. Restrict or disable relevant dumping operationally; the driver cannot promise exclusion. |
| Debuggers, tracing, `/proc/kcore`, debug interfaces | Partial operational mitigation | No backing/key debug export is planned. Privileged memory/debug/tracing facilities remain trusted and can defeat confidentiality. |
| Secrets accidentally logged | In scope for driver behavior | M3 logs lifecycle metadata and errors, never request bytes. Later prohibit key, IV-buffer dumps containing adjacent secrets, plaintext, and secret-bearing ioctl dumps. Log bounded status/errno only. |
| Traffic patterns, timing, sizes, availability | Out of scope for confidentiality guarantees | XTS does not hide access patterns or prevent denial of service. Capacity and tags bound resources, not an attacker's ability to occupy the device. |

## Invariants enforced by M3

1. Every data-bearing READ/WRITE goes through the security interface before
   reaching the store. A delivered FLUSH has no data and remains an ordered no-op.
2. The device still has 4096-byte logical blocks, 512-byte sector accounting,
   default 64 MiB, and bounded configurable capacity of 1-256 MiB.
3. Validate full request alignment, bounds and page-segment totals before
   transfer; preserve overflow-safe store checks and explicit error statuses.
4. One ordered worker owns runtime transfers. Each accepted request is started
   once and completed once; it is never accessed after completion.
5. Initialization precedes publication; drain requests/work before freeing
   backing state. Unwind only resources acquired successfully.
6. The code contains no cipher, keys, crypto execution, custom authorization,
   or misleading encrypted/active flag. Pass-through is the only M3 behavior,
   not a fallback selected after a crypto error.
7. No user data is logged. Ordinary memory release is not claimed as erasure.

These implementation properties were reviewed statically, and the preserved
plaintext device behavior was exercised in the M3 VM regression; see
[the report](m3-report.md). That evidence does not activate or verify crypto.

## Invariants required when crypto is introduced

| Requirement | Enforcement point / acceptance evidence needed |
| --- | --- |
| Backing contains no persistent plaintext user data | Security layer must transform complete units before store writes; inspect backing in a controlled test without adding a production export. |
| No plaintext fallback | Remove M3 pass-through as the encryption implementation lands. Missing/invalid key, allocation/provider/setup failure, locked state, or failed operation must reject I/O. |
| Keys separate from backing | Private security context/crypto transform; no raw key in data units, module parameters, query output, logs, or permanent driver copies. |
| Explicit key lifecycle | State machine and exclusive transition ownership from [the design](m3-security-design.md); test invalid transitions and failure paths. |
| Clear secrets before destruction/replacement | Use explicit clearing and allocation-matched sensitive frees, including setkey failure and partially copied input. Provider cleanup must finish before memory is released. |
| Bounded plaintext lifetime | Reusable unit buffers cleared after each operation/error; no borrowed request mapping retained across asynchronous completion. |
| Stable cryptographic addressing | One fixed 4096-byte unit convention; checked unit index, correctly encoded XTS input, and new key for each destructive generation. AEAD, if adopted, needs its own unique-nonce protocol. |
| No key/state race | Close admission and drain old operations before replacing/freeing transform, scratch, or metadata; do not set a key on an in-use transform. |
| Orderly unload removes sensitive state | Stop both entry points, finish requests and callbacks, clear owned secrets, then free storage/state. Crash cleanup is excluded. |
| Authentication before release (later integrity milestone) | Verify each unit in private staging before copying plaintext into request pages. A failed tag is an I/O error; never return that unit's unauthenticated output. |
| Coherent ciphertext/metadata updates (later integrity milestone) | Serialize unit commits; no reader sees mixed generations. No promise of multi-unit atomic writes or crash recovery. |

Changing milestones does not silently turn these future requirements into
verified guarantees. Encryption must be implemented with the Kernel Crypto API
and runtime-tested before the project is described as encrypted; authentication
requires separate implementation and evidence.
