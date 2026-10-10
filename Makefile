# SPDX-License-Identifier: GPL-2.0-only
KDIR ?= /lib/modules/$(shell uname -r)/build
MODULE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

.DEFAULT_GOAL := all
.PHONY: all modules clean check-env help

all: modules

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

help:
	@printf '%s\n' \
		'make                 Build secureram.ko for the running kernel' \
		'make W=1             Build with extra kernel compiler warnings' \
		'make KDIR=/path      Build against a selected prepared kernel tree' \
		'make check-env       Inspect build prerequisites without changing the system' \
		'make clean           Remove build products using the same KDIR' \
		'Load/unload commands are documented in README.md (never automatic).'
