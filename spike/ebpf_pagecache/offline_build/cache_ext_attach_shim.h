/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Declaration for the offline stub of bpf_map__attach_cache_ext_ops().
 * See cache_ext_attach_shim.c. Never used on a cache_ext box: there the
 * symbol comes from the artifact's PATCHED libbpf.
 */
#ifndef _CACHE_EXT_ATTACH_SHIM_H
#define _CACHE_EXT_ATTACH_SHIM_H 1
#include <bpf/libbpf.h>
struct bpf_link *bpf_map__attach_cache_ext_ops(struct bpf_map *map, int cgroup_fd);
#endif /* _CACHE_EXT_ATTACH_SHIM_H */
