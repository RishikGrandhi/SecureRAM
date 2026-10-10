# User-space tools

Reserved for a later administrative utility. M2 exposes `/dev/secureram0` as a
plaintext block device, but has no management CLI, ioctl ABI, or key interface.
Build/load/unload instructions are in the root README; opt-in VM checks live
under `tests/`. No user-space buffer substitutes for the kernel backing store.
