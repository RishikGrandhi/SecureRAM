# SPDX-License-Identifier: GPL-2.0-only
KDIR ?= /lib/modules/$(shell uname -r)/build
MODULE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

.DEFAULT_GOAL := all
.PHONY: all build modules clean tools tools-clean check-env check-runtime \
	check-production load status unload help

all: modules

build: modules tools

modules:
	@test -f "$(KDIR)/Makefile" || { \
		printf '%s\n' 'Missing kernel build tree: $(KDIR)' \
		'Install matching kernel headers or set KDIR; see docs/development.md.' >&2; \
		exit 1; \
	}
	$(MAKE) -C "$(KDIR)" M="$(MODULE_DIR)" modules

clean:
	$(MAKE) -C "$(KDIR)" M="$(MODULE_DIR)" clean

check-env:
	sh "$(MODULE_DIR)/scripts/check-environment.sh" "$(KDIR)"

check-runtime:
	sh "$(MODULE_DIR)/scripts/check-environment.sh" --runtime "$(KDIR)"

check-production:
	sh "$(MODULE_DIR)/scripts/check-production-build.sh" "$(MODULE_DIR)/secureram.ko"

load:
	sh "$(MODULE_DIR)/scripts/secureram-lifecycle.sh" load

status:
	sh "$(MODULE_DIR)/scripts/secureram-lifecycle.sh" status

unload:
	sh "$(MODULE_DIR)/scripts/secureram-lifecycle.sh" unload

tools:
	$(MAKE) -C "$(MODULE_DIR)/tools"

tools-clean:
	$(MAKE) -C "$(MODULE_DIR)/tools" clean

help:
	@printf '%s\n' \
		'make                 Build secureram.ko for the running kernel' \
		'make build           Build the module and management CLI' \
		'make W=1             Build with extra kernel compiler warnings' \
		'make tools           Build the dependency-free management CLI' \
		'make tools-clean     Remove the userspace binary' \
		'make KDIR=/path      Build against a selected prepared kernel tree' \
		'make check-env       Inspect build prerequisites without changing the system' \
		'make check-runtime   Require a matching non-WSL runtime environment' \
		'make check-production  Prove the built module omits known test hooks' \
		'make clean           Remove build products using the same KDIR' \
		'sudo make load       Load a proved production module (CAPACITY_MB=64 default)' \
		'sudo make status     Show loaded state; succeeds clearly when unloaded' \
		'sudo make unload     Unload only after explicit unmount/close; never forced'
