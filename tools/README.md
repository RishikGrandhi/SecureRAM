# User-space tools

Reserved for a later administrative utility. M4 implements an ioctl key-control
ABI but does not include a production management CLI or GUI.
Build/load/unload instructions are in the root README; opt-in VM checks live
under `tests/`. No user-space buffer substitutes for the kernel backing store.

The [M3 security design](../docs/m3-security-design.md) selected the separate
`/dev/secureramctl` misc device now implemented in M4. The narrowly scoped
`tests/m4-control.c` helper verifies that interface using a random ephemeral key.
It does not accept passwords, derive keys or store production secrets. Follow
[the M4 procedure](../docs/m4-testing.md) only in the disposable VM.
