# SPDX-License-Identifier: GPL-2.0-only
obj-m := secureram.o
secureram-y := src/secureram_main.o src/secureram_block.o \
	      src/secureram_security.o src/secureram_store.o src/secureram_control.o

ccflags-y += -I$(src)/include

# Opt-in verification only. No backing data is exported, even in this build.
ifeq ($(M4_TEST),1)
ccflags-y += -DSECURERAM_M4_TEST
endif
