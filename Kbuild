# SPDX-License-Identifier: GPL-2.0-only
obj-m := secureram.o
secureram-y := src/secureram_main.o src/secureram_block.o \
	      src/secureram_security.o src/secureram_store.o src/secureram_control.o \
	      src/secureram_stats.o src/secureram_snapshot.o

ccflags-y += -I$(src)/include

# Opt-in verification only. No backing data is exported, even in this build.
ifeq ($(M4_TEST),1)
ccflags-y += -DSECURERAM_M4_TEST
endif

# Fixed one-shot call-boundary failures; absent from the production module.
ifeq ($(M9_TEST),1)
ccflags-y += -DSECURERAM_M9_TEST
secureram-y += src/secureram_fault.o
endif

# Privileged bounded corruption hooks; never enabled by a production build.
ifeq ($(M5_TEST),1)
ccflags-y += -DSECURERAM_M5_TEST
endif
