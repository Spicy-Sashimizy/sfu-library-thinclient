// SPDX-License-Identifier: GPL-2.0
/*
 * hotset_protect: a cache_ext (SOSP'25) page-cache eviction policy that
 * protects a *statically declared* set of (inode, page-offset) extents.
 *
 * WHY THIS SHAPE (read this before changing anything)
 * ---------------------------------------------------
 * The Tier-1d workload is an mmap'd file touched through PTEs. On the
 * cache_ext kernel (linux-cache-ext @ 7442a927, based on v6.6.8) the
 * `folio_accessed` hook is invoked from exactly ONE place:
 *
 *     mm/swap.c:459-464   folio_mark_accessed()
 *
 * and `folio_mark_accessed()` is NOT called anywhere on the mmap fault path:
 * `filemap_fault()` (mm/filemap.c:3383) and `filemap_map_pages()`
 * (mm/filemap.c:3686) never call it, and rmap/PTE-young discovery
 * (mm/rmap.c) carries no cache_ext hook at all (grep: 0 hits).
 * Its only file-backed callers are read()/splice()/readahead-completion
 * paths (mm/filemap.c:1918, 2800, 2813, 3076, 3879) and
 * `zap_pte_range()` (mm/memory.c:1452), i.e. munmap teardown.
 *
 * => For an mmap-driven workload, a cache_ext policy receives NO recency
 *    signal. `folio_accessed` is effectively dead. Any policy that derives
 *    hotness from that hook degenerates to insertion-order FIFO.
 *
 * What *is* visible for mmap is insertion and removal:
 *   - `folio_added`   from __filemap_add_folio()  (mm/filemap.c:938-941),
 *     which DOES fire for mmap major faults (filemap_fault ->
 *     __filemap_get_folio(FGP_CREAT|FGP_FOR_MMAP) -> filemap_add_folio).
 *   - `folio_evicted` from __filemap_remove_folio() (mm/filemap.c:222-227)
 *     and page_cache_delete_batch() (mm/filemap.c:339-344).
 *   - `evict_folios`  from shrink_lruvec() (mm/vmscan.c:6465-6469).
 *
 * So this policy substitutes an EXTERNALLY SUPPLIED hotness oracle for the
 * missing recency signal: userspace pushes the t1d hot-extent table into
 * `hot_chunks`, and `folio_added` files each folio onto the hot or the cold
 * list based on (inode, pgoff) alone. `evict_folios` then drains cold before
 * it ever touches hot. `folio_accessed` is still implemented (and counted)
 * so that (a) the same object serves as the mmap-visibility probe, and
 * (b) the policy behaves sensibly for read()-driven workloads.
 *
 * IDIOMS: modelled on policies/cache_ext_s3fifo.bpf.c (two lists +
 * iterate_extended) and policies/cache_ext_fifo.bpf.c (relevance gate).
 * Enums/structs used without local definition (CACHE_EXT_CONTINUE_ITER,
 * CACHE_EXT_EVICT_NODE, CACHE_EXT_ITERATE_SELF, CACHE_EXT_ITERATE_TAIL,
 * struct cache_ext_iterate_opts) come from vmlinux.h, exactly as they do in
 * cache_ext_s3fifo.bpf.c.
 *
 * BUILD: drop this next to the upstream policies and build with their
 * Makefile; see spike/ebpf_pagecache/cache_ext_hotset.patch.
 */
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>

#include "cache_ext_lib.bpf.h"
#include "dir_watcher.bpf.h"

char _license[] SEC("license") = "GPL";

// #define DEBUG
#ifdef DEBUG
#define dbg_printk(fmt, ...) bpf_printk(fmt, ##__VA_ARGS__)
#else
#define dbg_printk(fmt, ...)
#endif

/******************************************************************************
 * Hot-extent table ***********************************************************
 *****************************************************************************/

/*
 * The hot set is expressed to the kernel as a chunk bitmap rather than as a
 * list of extents, because BPF hash maps only do exact-match lookups: a
 * range query ("which extent contains pgoff?") would need a loop over every
 * extent on every folio_added. One chunk covers HOTSET_CHUNK_PAGES
 * consecutive pages of one inode and carries a 64-bit membership bitmap, so
 * the hot/cold decision is a single O(1) lookup plus a shift.
 *
 * Userspace (load_hotset.py) expands the t1d `skew.hot_extents` table into
 * these chunks. A scattered hot set (skew kind `hotset`) expands to roughly
 * one chunk per 64 pages of R; a clustered one (`hotsetc`) to far fewer.
 *
 * Sizing: 2^18 chunks * 64 pages * 4 KiB = 64 GiB of addressable hot extent,
 * which covers Tier-1d's 5 GiB R with a ~20 KiB-entry occupancy. BPF hash
 * maps preallocate, so this map costs ~=18 MiB of loader-side kernel memory;
 * it is allocated by the loader process, NOT inside the benchmark cgroup.
 *
 * Phase-2 (production, 8 shards of forward_data.bin) occupancy, computed
 * 2026-09-06 from the real F1 sidecars by `load_hotset.py stack-chunks`:
 *   hot50_1.6gb   390,632 pages (1,525.9 MiB) -> 57,672 chunks
 *   hot80_4.2gb 1,025,392 pages (4,005.4 MiB) -> 70,856 chunks
 *   full_touched 1,855,728 pages (7,248.9 MiB) -> 77,648 chunks
 * Worst case is 30% of max_entries, so NO resize is needed for phase 2. The
 * multi-inode case needs no change either: the key already carries the ino.
 */
#define HOTSET_CHUNK_SHIFT 6
#define HOTSET_CHUNK_PAGES (1ULL << HOTSET_CHUNK_SHIFT)
#define HOTSET_CHUNK_MASK  (HOTSET_CHUNK_PAGES - 1)

struct hot_chunk_key {
	__u64 ino;
	__u64 chunk; /* pgoff >> HOTSET_CHUNK_SHIFT */
};

struct {
	__uint(type, BPF_MAP_TYPE_HASH);
	__type(key, struct hot_chunk_key);
	__type(value, __u64); /* bit i set => page (chunk << SHIFT) + i is hot */
	__uint(max_entries, 1 << 18);
} hot_chunks SEC(".maps");

/******************************************************************************
 * Stats **********************************************************************
 *****************************************************************************/

/*
 * These counters exist for bench_mmap_visibility.sh. Upstream has no trivial
 * counting policy (cache_ext_get_scan.bpf.c has a `stats` map but every
 * update is compiled out unless DEBUG is defined, and it is keyed by string),
 * so we carry our own always-on array map and let the loader pin it.
 *
 * The decisive counter is STAT_ACCESSED_CALLS: it is bumped at the very top
 * of folio_accessed BEFORE any relevance filtering, so a zero delta across an
 * mmap touch pass proves the hook never fired at all (as opposed to firing
 * and being filtered out, which would show up as ACCESSED_CALLS > 0 with
 * ACCESSED_RELEVANT == 0).
 */
enum hotset_stat {
	STAT_ADDED_CALLS = 0,
	STAT_ADDED_RELEVANT,
	STAT_ADDED_HOT,
	STAT_ADDED_COLD,
	STAT_ACCESSED_CALLS,
	STAT_ACCESSED_RELEVANT,
	STAT_ACCESSED_HOT,
	STAT_EVICTED_CALLS,
	STAT_EVICTED_RELEVANT,
	STAT_EVICTED_HOT,
	STAT_EVICT_FOLIOS_CALLS,
	STAT_EVICT_FROM_COLD,
	STAT_EVICT_FROM_HOT,
	STAT_EVICT_HOT_FALLBACK,
	STAT_SCAN_COLD,
	STAT_SCAN_HOT,
	HOTSET_NR_STATS,
};

struct {
	__uint(type, BPF_MAP_TYPE_ARRAY);
	__type(key, __u32);
	__type(value, __u64);
	__uint(max_entries, HOTSET_NR_STATS);
} hotset_stats SEC(".maps");

static __always_inline void stat_add(__u32 idx, __u64 delta)
{
	__u64 *counter = bpf_map_lookup_elem(&hotset_stats, &idx);

	if (counter)
		__sync_fetch_and_add(counter, delta);
}

/******************************************************************************
 * Lists **********************************************************************
 *****************************************************************************/

static __u64 hot_list;
static __u64 cold_list;

/*
 * Approximate, in the same sense as cache_ext_s3fifo.bpf.c's list sizes:
 * updated from the hooks, not reconciled against the kernel lists.
 */
static __s64 hot_list_size = 0;
static __s64 cold_list_size = 0;

/******************************************************************************
 * Helpers ********************************************************************
 *****************************************************************************/

/* Same gate as cache_ext_fifo.bpf.c / cache_ext_s3fifo.bpf.c. */
static inline bool is_folio_relevant(struct folio *folio)
{
	if (!folio || !folio->mapping || !folio->mapping->host)
		return false;

	return inode_in_watchlist(folio->mapping->host->i_ino);
}

/*
 * Caller must have passed is_folio_relevant() first: this dereferences
 * folio->mapping->host unconditionally, exactly as s3fifo_folio_evicted()
 * does upstream.
 */
static inline bool folio_is_hot(struct folio *folio)
{
	pgoff_t index = folio_index(folio);
	struct hot_chunk_key key = {
		.ino = folio->mapping->host->i_ino,
		.chunk = (__u64)index >> HOTSET_CHUNK_SHIFT,
	};
	__u64 *bitmap = bpf_map_lookup_elem(&hot_chunks, &key);

	if (!bitmap)
		return false;

	return (*bitmap >> ((__u64)index & HOTSET_CHUNK_MASK)) & 1ULL;
}

/* Shared eligibility test, identical to the upstream FIFO/S3-FIFO callbacks. */
static __always_inline bool folio_is_evictable(struct folio *folio)
{
	if (!folio_test_uptodate(folio) || !folio_test_lru(folio))
		return false;

	if (folio_test_dirty(folio) || folio_test_writeback(folio))
		return false;

	return true;
}

/******************************************************************************
 * struct_ops *****************************************************************
 *****************************************************************************/

s32 BPF_STRUCT_OPS_SLEEPABLE(hotset_init, struct mem_cgroup *memcg)
{
	cold_list = bpf_cache_ext_ds_registry_new_list(memcg);
	if (cold_list == 0) {
		bpf_printk("cache_ext: init: Failed to create cold_list\n");
		return -1;
	}
	bpf_printk("cache_ext: Created cold_list: %llu\n", cold_list);

	hot_list = bpf_cache_ext_ds_registry_new_list(memcg);
	if (hot_list == 0) {
		bpf_printk("cache_ext: init: Failed to create hot_list\n");
		return -1;
	}
	bpf_printk("cache_ext: Created hot_list: %llu\n", hot_list);

	return 0;
}

/*
 * Insertion decides hotness. For the mmap workload this is the ONLY place the
 * decision can be made, because folio_accessed never fires (see the file
 * header). Both lists are maintained FIFO (add at tail, evict from head).
 */
void BPF_STRUCT_OPS(hotset_folio_added, struct folio *folio)
{
	__u64 list_to_add;
	bool hot;

	stat_add(STAT_ADDED_CALLS, 1);

	if (!is_folio_relevant(folio))
		return;

	stat_add(STAT_ADDED_RELEVANT, 1);

	hot = folio_is_hot(folio);
	if (hot) {
		list_to_add = hot_list;
		stat_add(STAT_ADDED_HOT, 1);
		__sync_fetch_and_add(&hot_list_size, 1);
	} else {
		list_to_add = cold_list;
		stat_add(STAT_ADDED_COLD, 1);
		__sync_fetch_and_add(&cold_list_size, 1);
	}

	if (bpf_cache_ext_list_add_tail(list_to_add, folio)) {
		bpf_printk("cache_ext: added: Failed to add folio to list\n");
		if (hot)
			__sync_fetch_and_sub(&hot_list_size, 1);
		else
			__sync_fetch_and_sub(&cold_list_size, 1);
		return;
	}

	dbg_printk("cache_ext: added folio, hot=%d\n", (int)hot);
}

/*
 * Recency refresh WITHIN a list. Never promotes cold -> hot: hotness here is
 * the userspace oracle's, not the kernel's, so an access to a cold page is
 * just a cold page that was read once.
 *
 * On an mmap workload this hook is never called (mm/swap.c:459 is only
 * reachable via folio_mark_accessed, which the fault path does not call), so
 * both lists stay pure FIFO. That is the intended degradation, and
 * STAT_ACCESSED_CALLS records it.
 */
void BPF_STRUCT_OPS(hotset_folio_accessed, struct folio *folio)
{
	stat_add(STAT_ACCESSED_CALLS, 1);

	if (!is_folio_relevant(folio))
		return;

	stat_add(STAT_ACCESSED_RELEVANT, 1);

	if (folio_is_hot(folio)) {
		stat_add(STAT_ACCESSED_HOT, 1);
		if (bpf_cache_ext_list_move(hot_list, folio, true))
			dbg_printk("cache_ext: accessed: hot move failed\n");
		return;
	}

	if (bpf_cache_ext_list_move(cold_list, folio, true))
		dbg_printk("cache_ext: accessed: cold move failed\n");
}

/*
 * Bookkeeping only. We deliberately do NOT call bpf_cache_ext_list_del()
 * here: valid_folios_del() (mm/memcontrol.c:387-405) already unlinks the
 * node right after this hook returns, and cache_ext_fifo.bpf.c /
 * cache_ext_s3fifo.bpf.c both have the list_del commented out for that
 * reason.
 */
void BPF_STRUCT_OPS(hotset_folio_evicted, struct folio *folio)
{
	stat_add(STAT_EVICTED_CALLS, 1);

	if (!is_folio_relevant(folio))
		return;

	stat_add(STAT_EVICTED_RELEVANT, 1);

	if (folio_is_hot(folio)) {
		stat_add(STAT_EVICTED_HOT, 1);
		__sync_fetch_and_sub(&hot_list_size, 1);
	} else {
		__sync_fetch_and_sub(&cold_list_size, 1);
	}
}

/*
 * Two distinct callbacks, one per iterate call site. This mirrors s3fifo's
 * MAIN_ITER_FN(id) macro expansion: bpf_cache_ext_list_iterate_extended is a
 * callback-calling kfunc, and upstream duplicates the callback per call site
 * rather than reusing one function across calls.
 *
 * The per-node stat bump also keeps the two bodies textually distinct so no
 * function-merging pass can collapse them back into one symbol. It costs one
 * array lookup + one atomic per scanned node, which is inside the cost
 * envelope of upstream's own callbacks (s3fifo does a hash lookup plus an
 * atomic per node); drop STAT_SCAN_* if this policy is ever used for a CPU
 * overhead measurement. Scan depth is genuinely useful here: it says how much
 * of each list the policy walked to fill one 32-folio eviction batch.
 */
static int hotset_evict_cold_cb(int idx, struct cache_ext_list_node *a)
{
	stat_add(STAT_SCAN_COLD, 1);

	if (!folio_is_evictable(a->folio))
		return CACHE_EXT_CONTINUE_ITER;

	return CACHE_EXT_EVICT_NODE;
}

static int hotset_evict_hot_cb(int idx, struct cache_ext_list_node *a)
{
	stat_add(STAT_SCAN_HOT, 1);

	if (!folio_is_evictable(a->folio))
		return CACHE_EXT_CONTINUE_ITER;

	return CACHE_EXT_EVICT_NODE;
}

/*
 * Cold first, hot only as a fallback.
 *
 * `continue_mode = TAIL` rotates skipped (dirty/writeback/non-LRU) folios to
 * the tail so a subsequent iterate does not re-scan them, and `evict_mode =
 * TAIL` does the same for folios handed back for eviction (the kernel's
 * __cache_ext_isolate_and_reclaim may still fail to isolate them, in which
 * case they stay in the list but at the back). Both are the exact opts
 * cache_ext_s3fifo.bpf.c::evict_main_iter() uses.
 */
void BPF_STRUCT_OPS(hotset_evict_folios, struct cache_ext_eviction_ctx *eviction_ctx,
		    struct mem_cgroup *memcg)
{
	struct cache_ext_iterate_opts cold_opts = {
		.continue_list = CACHE_EXT_ITERATE_SELF,
		.continue_mode = CACHE_EXT_ITERATE_TAIL,
		.evict_list = CACHE_EXT_ITERATE_SELF,
		.evict_mode = CACHE_EXT_ITERATE_TAIL,
	};
	struct cache_ext_iterate_opts hot_opts = {
		.continue_list = CACHE_EXT_ITERATE_SELF,
		.continue_mode = CACHE_EXT_ITERATE_TAIL,
		.evict_list = CACHE_EXT_ITERATE_SELF,
		.evict_mode = CACHE_EXT_ITERATE_TAIL,
	};

	stat_add(STAT_EVICT_FOLIOS_CALLS, 1);

	if (bpf_cache_ext_list_iterate_extended(memcg, cold_list,
						hotset_evict_cold_cb,
						&cold_opts, eviction_ctx) < 0) {
		bpf_printk("cache_ext: evict: Failed to iterate cold_list\n");
	} else {
		stat_add(STAT_EVICT_FROM_COLD, cold_opts.nr_folios_evict);
	}

	/*
	 * THE POLICY: hot extents are only surrendered once the cold list has
	 * no evictable candidate left to give.
	 */
	if (eviction_ctx->nr_folios_to_evict >=
	    eviction_ctx->request_nr_folios_to_evict)
		return;

	stat_add(STAT_EVICT_HOT_FALLBACK, 1);

	if (bpf_cache_ext_list_iterate_extended(memcg, hot_list,
						hotset_evict_hot_cb,
						&hot_opts, eviction_ctx) < 0) {
		bpf_printk("cache_ext: evict: Failed to iterate hot_list\n");
		return;
	}

	stat_add(STAT_EVICT_FROM_HOT, hot_opts.nr_folios_evict);
}

SEC(".struct_ops.link")
struct cache_ext_ops hotset_ops = {
	.init = (void *)hotset_init,
	.evict_folios = (void *)hotset_evict_folios,
	.folio_accessed = (void *)hotset_folio_accessed,
	.folio_evicted = (void *)hotset_folio_evicted,
	.folio_added = (void *)hotset_folio_added,
};
