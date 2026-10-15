# SecureRAM installation and setup

## Supported environment

Use the disposable x86-64 Ubuntu VM with a non-WSL Linux kernel, matching
running-kernel headers and enough free RAM for the selected capacity, tags and
optional snapshot. The project has been runtime validated on Ubuntu 24.04.5 LTS;
kernel APIs are not stable, so a successful build and final acceptance on the
current target are required. WSL is suitable only for compile/static checks
against a prepared target tree; never load an Ubuntu-generic module into WSL.

## Dependencies

Install distribution packages as an administrator; SecureRAM scripts never
install them automatically:

```sh
sudo apt-get update
sudo apt-get install build-essential kmod "linux-headers-$(uname -r)" python3 e2fsprogs
```

udev and util-linux supply the device/mount inspection commands used by the
guarded workflow. Python 3.10+ standard library is sufficient for the dashboard
and integration helpers. Node is used only by optional local UI tests. `fio` is
optional and belongs only to M10 benchmark reproduction.

Check without changing the machine:

```sh
make check-env
make check-runtime
```

`check-env` may accept a different prepared `KDIR` as compile-only. `check-runtime`
requires the header release to match `uname -r` and rejects WSL.

## Build

Build as the ordinary checkout owner:

```sh
make clean
make build W=1
modinfo ./secureram.ko
make check-production
```

`make build` creates `secureram.ko` and `tools/secureramctl`. The production
check scans the built artifact for every known M4/M5/M9 test symbol, selector
and diagnostic. Do not load an artifact if it fails.

## Load and verify

The convenience target is explicit, root-only and refuses a known test build:

```sh
sudo make load
sudo make status
```

The default is 64 MiB. To select another supported capacity at insertion:

```sh
sudo make load CAPACITY_MB=8
```

The module starts in `NO_KEY`. Verify the nodes and install an ephemeral key:

```sh
test -b /dev/secureram0
test -c /dev/secureramctl
sudo ./tools/secureramctl status
sudo ./tools/secureramctl load-random
sudo ./tools/secureramctl status
```

Normal block I/O is allowed only in `ACTIVE`. Never use `/dev/secureram0` as
swap and never redirect project test commands to another device.

## Dashboard

With the module loaded and the CLI built:

```sh
sudo python3 -I dashboard/server.py
```

Open the exact printed loopback URL in the VM's ordinary browser. Do not save or
share the URL token, redirect startup stdout to evidence, forward the port or run
the browser as root. Ctrl+C stops only the backend.

## Unload and cleanup

Unmount and close every block/control user first. Key destruction is irreversible:

```sh
sudo ./tools/secureramctl destroy
sudo make unload
test ! -e /dev/secureram0
test ! -e /dev/secureramctl
make clean tools-clean
```

`make unload` never forces removal or deletes stale nodes. If it reports busy,
identify and close the legitimate holder. See [troubleshooting](troubleshooting.md).
