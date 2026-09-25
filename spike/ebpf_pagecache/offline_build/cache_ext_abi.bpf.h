/* SPDX-License-Identifier: GPL-2.0 */
/*
 * cache_ext BPF ABI shim for OFFLINE (non-cache_ext-kernel) compilation.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * hotset_protect.bpf.c is written against the cache_ext kernel fork
 * (cache-ext/linux-cache-ext @ 7442a927, base v6.6.8). On that kernel the
 * types below are in the kernel's own BTF, so upstream's Makefile gets them
 * for free out of a locally generated vmlinux.h and this file is NEVER used.
 *
 * On a stock kernel (this WSL2 host, 6.18.33.2-microsoft-standard-WSL2+)
 * those types are absent from /sys/kernel/btf/vmlinux -- verified
 * 2026-09-25: zero hits for cache_ext_ops / cache_ext_list_node /
 * cache_ext_eviction_ctx / cache_ext_iterate_opts / sampling_options in the
 * bpftool-dumped vmlinux.h, and zero bpf_cache_ext_* symbols in
 * /proc/kallsyms. So the policy source cannot even be PARSED here without
 * these declarations.
 *
 * PROVENANCE (every definition below is transcribed verbatim, 2026-09-25,
 * from the pinned kernel commit, not invented):
 *   struct cache_ext_eviction_ctx  linux-cache-ext@7442a927 include/linux/mm_types.h:1379
 *   struct cache_ext_admission_ctx linux-cache-ext@7442a927 include/linux/mm_types.h:1388
 *   struct cache_ext_ops           linux-cache-ext@7442a927 include/linux/mm_types.h:1395
 *   struct cache_ext_list_node     linux-cache-ext@7442a927 include/linux/cache_ext.h:41
 *   struct sampling_options        linux-cache-ext@7442a927 include/linux/cache_ext.h:51
 *   enum cache_ext_iter_callback_ret / iter_ret / iterate_mode /
 *     iterate_list, struct cache_ext_iterate_opts
 *                                  linux-cache-ext@7442a927 mm/cache_ext_ds.c:160-245
 *
 * WHAT THIS DOES *NOT* BUY YOU
 * ----------------------------
 * A .bpf.o built with this shim carries the cache_ext types in the OBJECT's
 * BTF only. Loading a struct_ops map still requires the *kernel* to carry
 * `struct cache_ext_ops` in its BTF and to have registered the cache_ext
 * struct_ops type; it does not, so this object can never load here. The shim
 * proves the source compiles and that libbpf can relocate all five hooks --
 * nothing about runtime behaviour.
 *
 * Define CACHE_EXT_ABI_IN_VMLINUX when building on a real cache_ext kernel
 * to make this header a no-op (the vmlinux.h definitions then win).
 */
#ifndef _CACHE_EXT_ABI_BPF_H
#define _CACHE_EXT_ABI_BPF_H 1

#include "vmlinux.h"

#ifndef CACHE_EXT_ABI_IN_VMLINUX

struct cache_ext_eviction_ctx {
	/* Input */
	unsigned long request_nr_folios_to_evict;
	/* Output */
	unsigned long nr_folios_to_evict;
	struct folio *folios_to_evict[32];
	s64 scores[32];
};

struct cache_ext_admission_ctx {
	u64 ino;
	u64 offset;
	u64 size;
};

struct cache_ext_ops {
	s32  (*init)(struct mem_cgroup *memcg);
	void (*evict_folios)(struct cache_ext_eviction_ctx *ctx, struct mem_cgroup *memcg);
	void (*folio_added)(struct folio *folio);
	void (*folio_accessed)(struct folio *folio);
	void (*folio_evicted)(struct folio *folio);
	bool (*admit_folio)(struct cache_ext_admission_ctx *ctx);
};

struct cache_ext_list_node {
	struct folio *folio;
	struct list_head node;
};

struct sampling_options {
	__u32 sample_size;
	__u32 select_size;
};

enum cache_ext_iter_callback_ret {
	CACHE_EXT_CONTINUE_ITER = 0,
	CACHE_EXT_STOP_ITER = 1,
	CACHE_EXT_EVICT_NODE = 2,
};

enum cache_ext_iter_ret {
	CACHE_EXT_DONE_ITER = 0,
	CACHE_EXT_MAX_ITER_REACHED = 8,
	CACHE_EXT_EVICT_ARRAY_FILLED = 9,
};

enum cache_ext_iterate_mode {
	CACHE_EXT_ITERATE_SKIP = 0,
	CACHE_EXT_ITERATE_HEAD,
	CACHE_EXT_ITERATE_TAIL,
	CACHE_EXT_ITERATE_MAX,
};

enum cache_ext_iterate_list {
	CACHE_EXT_ITERATE_SELF = 0,
};

struct cache_ext_iterate_opts {
	/* Options for CACHE_EXT_CONTINUE_ITER nodes */
	u64 continue_list;
	u64 continue_mode;

	/* Options for CACHE_EXT_EVICT_NODE nodes */
	u64 evict_list;
	u64 evict_mode;

	/* Output */
	u64 nr_folios_continue;
	u64 nr_folios_evict;
};

#endif /* CACHE_EXT_ABI_IN_VMLINUX */

/*
 * COLLISION FIX (stock-kernel build only).
 *
 * upstream policies/cache_ext_lib.bpf.h declares the iterate kfuncs with a
 * parameter of FUNCTION type literally named `iter_fn`:
 *
 *     int bpf_cache_ext_list_iterate(..., int(iter_fn)(int, struct ...*), ...)
 *
 * A stock 6.18 vmlinux.h contains, from dm-bufio,
 *
 *     typedef enum it_action (*iter_fn)(struct dm_buffer *, void *);
 *
 * Once `iter_fn` is a typedef name, `int (iter_fn)(int idx, ...)` re-parses
 * as "function taking (iter_fn) returning a function type", and clang errors
 * with `function cannot return function type`. Renaming the token before
 * cache_ext_lib.bpf.h is read costs nothing and touches no upstream file.
 * The cache_ext kernel's BTF does not carry that dm-bufio typedef, which is
 * why upstream never hit this.
 */
#define iter_fn ce_iter_fn_param

/*
 * PG_hugetlb was removed from enum pageflags upstream (folios carry it as a
 * page type now), so it is absent from a 6.18 vmlinux.h while
 * cache_ext_lib.bpf.h's folio_test_hugetlb() still references it. Value 26 is
 * its slot in the v6.6.8 enum. Nothing in hotset_protect calls
 * folio_test_hugetlb(); this only keeps the header parseable.
 */
#ifndef PG_hugetlb
#define PG_hugetlb 26
#endif

#endif /* _CACHE_EXT_ABI_BPF_H */
