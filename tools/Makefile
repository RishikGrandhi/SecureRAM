# SPDX-License-Identifier: GPL-2.0-only
CC ?= cc
CPPFLAGS += -I../include
CFLAGS ?= -O2
STRICT := -std=c11 -Wall -Wextra -Werror -Wconversion

.PHONY: all clean
all: secureramctl

secureramctl: secureramctl.c ../include/uapi/secureram.h ../include/secureram_config.h
	$(CC) $(CPPFLAGS) $(CFLAGS) $(STRICT) $< $(LDFLAGS) -o $@

clean:
	rm -f secureramctl
