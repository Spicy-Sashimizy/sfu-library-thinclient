/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Offline stub for bpf_map__attach_cache_ext_ops().
 *
 * The cache_ext artifact ships a PATCHED libbpf that adds this entry point
 * (upstream libbpf has only bpf_map__attach_struct_ops(), which takes no
 * cgroup fd -- cache_ext's whole point is per-cgroup policy). Stock libbpf
 * therefore cannot link hotset_protect.c.
 *
 * This stub exists so the loader LINKS on a stock box and its load path can
 * be exercised up to the point where the kernel refuses. It deliberately
 * does NOT fall back to bpf_map__attach_struct_ops(): that would silently
 * attach with different (cgroup-less) semantics and make a failed experiment
 * look like a successful one. It fails loudly instead.
 *
 * In practice control never reaches here on this host: the load fails first.
 */
#include "cache_ext_attach_shim.h"
#include <errno.h>
#include <stdio.h>

struct bpf_link *bpf_map__attach_cache_ext_ops(struct bpf_map *map, int cgroup_fd)
{
	(void)map;
	(void)cgroup_fd;
	fprintf(stderr,
		"cache_ext_attach_shim: bpf_map__attach_cache_ext_ops() is a "
		"cache_ext-patched-libbpf entry point and is NOT implemented by "
		"upstream libbpf. This offline build stubs it so the loader links; "
		"attaching a cache_ext policy is impossible on a stock kernel.\n");
	errno = ENOSYS;
	return NULL;
}
