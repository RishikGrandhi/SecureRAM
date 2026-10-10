# User-space tools

Reserved for a later administrative utility. M3 exposes `/dev/secureram0` as a
plaintext block device, but has no management CLI, ioctl ABI, or key interface.
Build/load/unload instructions are in the root README; opt-in VM checks live
under `tests/`. No user-space buffer substitutes for the kernel backing store.

The [M3 security design](../docs/m3-security-design.md) proposes a future
`/dev/secureramctl` misc device for privileged key/state operations. The name
is a design decision only: no control device, CLI or GUI is implemented in M3.
