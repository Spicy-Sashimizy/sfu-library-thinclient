# eBPF page-cache policy spike (cache_ext) — hot-set-aware eviction

> Test battery (what gets measured, phased): `TEST_SITUATIONS.md`.

**Status 2026-09-25: COMPILES on clang 14.0.6 (offline harness); LOAD
IMPOSSIBLE on this host — no cache_ext kernel AND no CAP_BPF in the
container; NOTHING MEASURED.** The build/load record is §7. This supersedes
the 2026-09-06 status ("CODE STAGED, NEVER COMPILED, NOTHING MEASURED").

`offline_build/build_offline.sh` now compiles `hotset_protect.bpf.c` to BPF
bytecode and links the loader on the stock WSL2 kernel by supplying the
cache_ext kernel ABI from a transcribed header, so source-level buildability
is a demonstrated fact rather than a claim. Runtime behaviour remains
entirely unknown: every claim below marked *code-read* is from reading the
upstream source at a pinned commit, and nothing in this spike is a runtime
measurement.

Upstream: `cache_ext` (SOSP 2025), cloned at `cache_ext_upstream/`
(commit `c50236c`, gitignored nested repo per the `spike/seismic_upstream`
convention; its `linux` submodule — the kernel fork
`cache-ext/linux-cache-ext @ 7442a927`, base v6.6.8 — is NOT initialized).
Code files authored by an Opus agent under session-lead direction
2026-09-06; this README and all judgments are the session lead's.

## 1. The two findings that reshape the route (code-read, cited)

**(a) cache_ext is BLIND to mmap recency.** The `folio_accessed` hook has
exactly one call site — the top of `folio_mark_accessed()`
(`mm/swap.c:459`) — and nothing on the mmap path ever calls it:
`filemap_fault()` takes its folio without `FGP_ACCESSED`
(`mm/filemap.c:3383–3512`), the fault-around path sets no reference
markings (`filemap_map_pages`, `mm/filemap.c:3604–3748`), and there is no
hook in `mm/rmap.c` (grep: zero) — so PTE-young discovery at reclaim scan
time is never surfaced either. The only `folio_mark_accessed` callers that
reach the hook are the `read()`/`splice()` paths. One trap: `zap_pte_range`
(`mm/memory.c:1452`) marks young pages at **munmap/teardown**, so a
visibility probe must sample counters before teardown (the bench script
does).

What IS visible for mmap: `folio_added` (fires on every fault-in and
readahead insertion, carrying `(ino, pgoff)` — `mm/filemap.c:938`),
`folio_evicted`, and `evict_folios`. **Consequence: on an mmap workload a
cache_ext policy degenerates to insertion-order FIFO unless hotness is
supplied from outside.** The framework can *apply* a hot set; it cannot
*learn* one from our traffic.

**(b) cache_ext requires MGLRU OFF.** `shrink_lruvec()` short-circuits into
`lru_gen_shrink_lruvec()` *before* the cache_ext block
(`mm/vmscan.c:6439` vs `:6465`). So cache_ext is a replacement for
classic LRU, never a third arm beside MGLRU — and the bar it must clear on
our workload is **beating classic** (whose refault-activation Tier-1d
measured as already good), not beating MGLRU.

## 2. What this means for the project

- The Tier-1d line's testing order stands: **MGLRU-FG first**
  (`../convergence_repro/PREREGISTRATION_T1D_FG.md`) — it fixes the arm we
  actually measured failing, kernel-natively. cache_ext is the
  app-informed-policy demonstration, second.
- Finding (a) upgrades the gap-3 access-histogram probe
  (`../convergence_repro/PREREGISTRATION_T1D_PROBE.md`) from
  characterization to **the production input**: the measured hot-extent
  table is exactly what a deployed `hotset_protect` policy would be fed.
  The probe output format and the policy's map format are designed to meet
  (t1d `skew.hot_extents` → chunk bitmaps via `load_hotset.py chunks`).
- Overhead if adopted (paper §6.3, their hardware, `pread()` workloads —
  *not* re-measured here): folio-registry memory 0.4–1.2% of the policy
  cgroup (≈64–192 MB at our 16 GB tier), no-op CPU ≤1.7% per I/O, ~1%
  whole-app mean. Our warm path serves at ~0 faults, so the CPU term
  multiplies against nearly nothing; the cost concentrates under pressure,
  where it would be buying back a measured ≥1.44× fault-floor penalty.
- Uplift/exposure map if a hot-set policy (or MGLRU-FG) works, *est.*, all
  unmeasured: direct uplift to the mmap serving path at near-critical RAM
  (the 16 GB tier, the SML 14–16 GB bracket, the laptop/portable tiers,
  the co-loaded demo box) and to `meta.sqlite`'s hot pages; exposure for
  sequential-scan build/rebuild jobs sharing a policy cgroup (hot-set
  protection deprioritizes streaming), for every RAM-sizing number in the
  docs (measured under stock policy — adoption triggers re-measurement +
  supersession), and — for the FG route only — a VM-global kernel swap that
  all containers share (cache_ext confines policy to the serving cgroup).

## 2b. Phase 2 — the stack-specific findings (code-read + sidecar-read, 2026-09-06)

- **The production hot tables already exist in the right units.** The F1
  sidecars (`<shard>.mmap/hotset_*.json`, schema `seismic.hotset.v1`,
  generated 2026-07-14) carry extents as **4 KiB file-relative page
  indexes** of `forward_data.bin` — exactly the `pgoff` that cache_ext's
  `folio_added` sees. Zero unit conversion; `load_hotset.py stack-chunks`
  only applies the `>>6` chunk shift (provenance cites in its docstring).
- **The real hot set fits the 16 GB tier with room** (computed from the
  actual 24 sidecars): hot50 **1.49 GiB** / hot80 **3.91 GiB** /
  full_touched **7.08 GiB**, against 41.14 GiB mmap'd across the 8 shards
  (5 files per shard; sidecars cover `forward_data.bin` only —
  `posting_lists.bin` at 8.64 GiB and the doc-mapping files have no hot
  map and are policy-managed-but-cold under the default watch dir, a
  measured-not-engineered confound recorded in the bench header).
- **No policy change was needed for production scale:** worst-case map
  occupancy 77,648 chunks of 262,144 (30%).
- **Replay reuses `scripts/seismic_testbed/t23_convergence_ladder.py`
  unchanged** — the serving process is the measuring process, keeping
  phase-2 numbers comparable with every t23a/t23b/sml cell on record.
  `stack_replay.py` exists only for what t23 cannot do (S4 weighting +
  `--hydrate` for sqlite traffic, S6 drift mixture).
- **Comparability caveats (all deliberate, all recorded in the bench):**
  `SFU_SEISMIC_PREFLOOR_HOTSET` defaults **0** here to isolate the policy
  (t23 protocol exports 1 — the two settings' numbers are NOT
  interchangeable); inode tables are host-specific and are regenerated on
  the target box every run; `meta.sqlite` shares the cgroup but sits
  outside the policy's watch tree (measured, not separated, per the
  phase-2 design); a `refresh` affects only folios faulted after it.

## 3. Files

| file | what | status |
|---|---|---|
| `offline_build/` | Stock-kernel build harness added 2026-09-25: `build_offline.sh`, `cache_ext_abi.bpf.h` (cache_ext types transcribed from linux-cache-ext@7442a927), `cache_ext_attach_shim.c` (loud stub for the patched-libbpf attach entry point), `BUILD_LOG_20260925.txt`. Does NOT touch `cache_ext_upstream/`. | BUILD OK; load refused (§7) |
| `hotset_protect.bpf.c` | The policy: two lists (cold drained first; hot touched only when the eviction request is still unfilled), hot membership via a `{ino, pgoff>>6}` → 64-page-bitmap hash map, always-on stats array for the visibility probe. Idioms copied from upstream `cache_ext_fifo`/`cache_ext_s3fifo` (nearest structural models — upstream has no extent-based policy). | COMPILES 2026-09-25 (clang 14.0.6, 1 warning); NEVER LOADED |
| `hotset_protect.c` | Userspace loader, structural clone of upstream `cache_ext_fifo.c`; adds `--hot_chunks FILE` and pins the stats map. | COMPILES + LINKS 2026-09-25 (libbpf 1.6.2 + attach stub); NEVER RUN PAST `__load()` |
| `cache_ext_hotset.patch` | One hunk wiring the policy into upstream `policies/Makefile`. | `git apply --check` PASSES against the clone |
| `load_hotset.py` | `chunks` (t1d result JSON → chunk table; ranking reconstruction self-checked, `--limit-mib` truncation, `--corrupt-frac/--corrupt-seed`, `--epoch 1` for the post-switch hot set of an E8 cell), `stack-chunks` (production sidecars → multi-inode table + per-file summary, page_size asserted, extents bounds-checked), `refresh` (rewrites the pinned map at runtime), `attach`, `stats`. | `chunks`/`stack-chunks`/knobs EXERCISED against real sidecars and a real t1d result; `attach`/`stats`/`refresh` untested (need the kernel) |
| `bench_mmap_visibility.sh` | Three arms (baseline / empty-table FIFO control / hot table) reusing `../convergence_repro/t1d_cell.py` unchanged; samples stats before and after teardown to separate the `zap_pte_range` burst; guards on a `-cache-ext` kernel and disables MGLRU. | `bash -n` clean; runnable only on a cache_ext kernel |
| `bench_stack_phase2.sh` | Phase-2 bench: real-stack replay (t23 ladder) in a policy cgroup, 3 arms, sidecar table regenerated on-box, env gates per THIN_CLIENT_SWAP, optional antagonist, `sfu-serve` stopped. | `bash -n` clean; cache_ext kernel only |
| `bench_matrix.sh` + `situations_battery.conf` | Situations runner for the E-battery (23 rows E7/E1/E3/E2/E4/E6): drives upstream policy loaders (fifo/s3fifo/sampling/lhd/mru/mglru) and ours, `table=auto|none|path` + knob passthrough, E8 refresh trigger keyed on the driver's pass lines, E8 workload switch passed through to the driver (`switch_at=`/`switch_seed=`/`switch_skew=`, `refresh_table=auto-epoch1`). | `bash -n` + parser dry-run clean |
| `stack_replay.py` | S4/S6 driver: query weighting (proxy documented in-file), `--hydrate` (sqlite traffic — t23 never touches meta.sqlite), S6 drift mixture (`step`/`ramp` schedules between two REAL pre-encoded query lists, realized mixture logged per replay; convergence early-stop disabled under a schedule). | `py_compile` + offline scheduler exercise |
| `antagonist_scan.sh` | Rate-limited sequential scan for S2 (outside cgroup) / S3 (inside); read-only. | `bash -n` clean |

Known comparability caveat: the bench uses `cgcreate` + `memory.max`
(cache_ext attaches to an opened cgroup path; a `systemd-run` transient
scope's path isn't known pre-launch), while every t1d cell to date ran
under `systemd-run --scope -p MemoryMax=`. Cross-comparisons between bench
arms are clean; comparisons against historical t1d cells carry this delta.

## 4. Build path (code-read from upstream scripts; NOT attempted here)

Their fork of v6.6.8 (`LOCALVERSION=-cache-ext`, BTF on), the **in-tree
patched libbpf + bpftool** (stock libbpf lacks
`bpf_map__attach_cache_ext_ops`), clang-14 for policies, and `vmlinux.h`
generated from the *running* cache_ext kernel — so policies build only on
the target box. Runtime: cgroup v2 memory controller, swap off, MGLRU off.

WSL2 risk list (flagged, unverified): no grub — boot via `.wslconfig
kernel=` with a hand-built bzImage; the kernel config is a real merge of
Microsoft's WSL2 config onto their 6.6.8 tree (not a fragment append);
pahole/dwarves needed for BTF; WSL2's balloon shares reclaim pressure with
the host. Bare-metal Linux (or a Cloudlab-style box) is the low-risk route
for first light.

## 5. Open assumptions inherited from authoring (verify before trusting)

The full list lives in the authoring agent's report (session
2026-09-06); the load-bearing ones: kernel enums assumed present in BTF
(as upstream s3fifo also requires); per-callsite callback duplication
assumed a verifier requirement; `folio_evicted` assumed safe to
dereference `folio->mapping->host` (upstream s3fifo does); no
`list_del` in `folio_evicted` (follows FIFO/S3-FIFO, not MRU); chunk-map
sizing (2^18 entries ≈ 64 GiB addressable hot set, ~18 MiB loader-side);
inode stability requires `--skip-laydown` (the bench enforces and logs it).

## 6. Efficacy (per CLAUDE.md)

Nothing here has measured efficacy. First measurement is the
`bench_mmap_visibility.sh` run on a cache_ext kernel: (1) does the
`folio_added` counter advance during mmap passes (predicted yes) and
`folio_accessed` stay flat until teardown (predicted yes, per §1a); (2)
does the hot-table arm's steady floor beat the FIFO-control arm at the
t1d divergence rung. Until then every performance statement in this spike
is *est.* / design-only.

## 7. Build & load record — 2026-09-25 (WSL2, the only host left)

Raw log: `offline_build/BUILD_LOG_20260925.txt`. Reproduce with
`offline_build/build_offline.sh --load`. Host: Linux
`6.18.33.2-microsoft-standard-WSL2+`, Debian 12 container, 16 cores, 31 GB,
BTF present at `/sys/kernel/btf/vmlinux`.

### 7.1 What the host actually offers

| Requirement | This host | Verdict |
|---|---|---|
| `CONFIG_BPF_SYSCALL`, `CONFIG_BPF_JIT`, `CONFIG_DEBUG_INFO_BTF`, `CONFIG_CGROUPS`, `CONFIG_MEMCG` | all `=y` (`/proc/config.gz`) | fine |
| `struct cache_ext_ops` / `cache_ext_list_node` / `cache_ext_eviction_ctx` / `cache_ext_iterate_opts` / `sampling_options` in kernel BTF | **0 hits** in the 184,425-line `vmlinux.h` dumped from `/sys/kernel/btf/vmlinux` | **BLOCKER** |
| `bpf_cache_ext_*` kfuncs | **0 hits** in `/proc/kallsyms` | **BLOCKER** |
| struct_ops types registered in this kernel | `tcp_congestion_ops` only (no `sched_ext_ops` either) | **BLOCKER** |
| `CAP_BPF` (39) / `CAP_SYS_ADMIN` (21) / `CAP_PERFMON` (38) | all CLEAR — `CapBnd 0x00000000a80425fb`, the stock Docker set; `sudo` gives uid 0 with the same bounding set | **BLOCKER (independent)** |
| `kernel.unprivileged_bpf_disabled` | `2` (unprivileged bpf(2) disabled outright) | consistent with the above |
| `MGLRU` | `CONFIG_LRU_GEN_ENABLED=y` — cache_ext needs it OFF (§1b) | moot while the above hold |

`CONFIG_CACHE_EXT` does not exist as a symbol: cache_ext is an out-of-tree
research patch against v6.6.8, not an upstream config option. Nothing short
of booting WSL2 on a hand-built `-cache-ext` bzImage (§4) changes rows 2–4.

### 7.2 Toolchain installed (container only; host kernel untouched)

`clang`/`clang-14` 14.0.6, `llvm` 14, `libbpf-dev` 1.1.2, `bpftool` 7.1.0,
`libelf-dev`, `zlib1g-dev` — all from Debian bookworm apt.

**Debian's bpftool/libbpf are unusable for this policy.** bpftool 7.1.0
(libbpf 1.1) prints

```
libbpf: elf: skipping unrecognized data section(18) .struct_ops.link
libbpf: elf: skipping relo section(19) .rel.struct_ops.link for section(18) .struct_ops.link
```

and emits a skeleton with **no struct_ops member at all**, so the loader
cannot compile. `.struct_ops.link` (BPF_F_LINK struct_ops) needs libbpf
≥ 1.2. `build_offline.sh` therefore builds libbpf **v1.6.2** and bpftool
**v7.6.0** from GitHub into `offline_build/build/toolchain/` (gitignored).

### 7.3 Compile result — PASS

`hotset_protect.bpf.c` → `hotset_protect.bpf.o` (880,864 B) with clang
14.0.6, `-O2 -target bpf -D__TARGET_ARCH_x86 -g -Wall`. **One warning, no
errors:**

```
./cache_ext_lib.bpf.h:128:9: warning: incompatible pointer types returning
    'memdesc_flags_t *' from a function with result type 'unsigned long *'
        return &page[n].flags;
```

That is upstream's `folio_flags()`, not our code: v6.18 wraps page flags in
`memdesc_flags_t` (a one-`unsigned long` struct), where v6.6.8 had a bare
`unsigned long`. Same address, so the `generic_test_bit()` calls still read
the right word; it disappears on the 6.6.8 cache_ext kernel.

All five struct_ops hooks plus the dir_watcher probe are present in the
object: `struct_ops.s/hotset_init`, `struct_ops/hotset_folio_added`,
`struct_ops/hotset_folio_accessed`, `struct_ops/hotset_folio_evicted`,
`struct_ops/hotset_evict_folios`, `fexit/vfs_open`, plus `.struct_ops.link`,
`.maps`, `license`. `bpftool gen skeleton` (7.6.0) succeeds and libbpf
relocates every hook by name against the object's BTF:

```
libbpf: struct_ops reloc hotset_ops: ... name 252 ('hotset_init')
libbpf: struct_ops reloc hotset_ops: ... name 369 ('hotset_evict_folios')
libbpf: struct_ops reloc hotset_ops: ... name 794 ('hotset_folio_added')
libbpf: struct_ops reloc hotset_ops: ... name 721 ('hotset_folio_accessed')
libbpf: struct_ops reloc hotset_ops: ... name 685 ('hotset_folio_evicted')
```

`hotset_protect.c` compiles and links (2,348,736 B) against libbpf 1.6.2 +
the attach stub.

**Scope of this result.** The cache_ext ABI came from
`offline_build/cache_ext_abi.bpf.h`, transcribed verbatim from
`linux-cache-ext@7442a927` (`include/linux/mm_types.h:1379–1404`,
`include/linux/cache_ext.h:41,51`, `mm/cache_ext_ds.c:160–245`), because the
stock kernel's BTF has none of it. So this validates the **policy source**,
not the pinned-commit build. It does confirm the §5 assumption "kernel enums
assumed present in BTF" is about the *kernel*, not about our spelling: every
enum and field name the policy uses (`CACHE_EXT_CONTINUE_ITER`,
`CACHE_EXT_EVICT_NODE`, `CACHE_EXT_ITERATE_SELF`, `CACHE_EXT_ITERATE_TAIL`,
`nr_folios_evict`, `nr_folios_to_evict`, `request_nr_folios_to_evict`)
matches the pinned kernel exactly. The five hooks we implement are also
exactly five of the six members of `struct cache_ext_ops`; the sixth,
`admit_folio`, is deliberately unimplemented.

### 7.4 Load result — FAILS, and would fail twice over

Exact text, identical as `vscode` and under `sudo`:

```
libbpf: Error in bpf_object__probe_loading(): -EPERM. Couldn't load trivial BPF program.
        Make sure your kernel supports BPF (CONFIG_BPF_SYSCALL=y) and/or that
        RLIMIT_MEMLOCK is set to big enough value.
libbpf: failed to load BPF skeleton 'hotset_protect_bpf': -EPERM
Failed to load BPF skeleton: Operation not permitted
```

Read that carefully: the program that got `-EPERM` is libbpf's own
**trivial** probe program (`r0 = 0; exit`), not ours. The container cannot
call `bpf(2)` at all — `CapBnd 0x00000000a80425fb` clears CAP_BPF,
CAP_SYS_ADMIN and CAP_PERFMON, and `sudo` inherits the same bounding set, so
uid 0 buys nothing. `kernel.unprivileged_bpf_disabled=2` closes the
unprivileged door as well. Granting those caps needs `--cap-add` on the
container (or `--privileged`) at *creation* time, which is a host-side change
outside this spike's remit.

**Even with CAP_BPF the load would still fail**, one step later and for the
real reason: `BPF_MAP_CREATE` of a `BPF_MAP_TYPE_STRUCT_OPS` map resolves
the struct_ops type by name in **kernel** BTF, and this kernel has no
`cache_ext_ops` (§7.1). The three cache_ext kfuncs the policy calls
(`bpf_cache_ext_ds_registry_new_list`, `bpf_cache_ext_list_add_tail`,
`bpf_cache_ext_list_iterate_extended`) are likewise absent from kallsyms, so
the verifier would reject every hook. That second failure is **predicted,
not observed** — the capability wall comes first. Do not cite it as measured.

### 7.5 Status transition

`CODE STAGED, NEVER COMPILED` (2026-09-06) → **`COMPILES; LOAD STATUS
KNOWN`** (2026-09-25). Still `NOTHING MEASURED`, and the first measurement
(§6) is unchanged and still needs a `-cache-ext` kernel.

### 7.6 Changelog

- **2026-09-25** — `offline_build/` added (harness, ABI shim, attach stub,
  build log). **No change to `hotset_protect.bpf.c` or `hotset_protect.c`
  was required to make them compile**: both built as authored 2026-09-06.
  The two portability fixes live in the shim, outside the policy sources,
  and are `#define`s that vanish on the cache_ext kernel:
  1. `#define iter_fn ce_iter_fn_param`. Upstream's
     `cache_ext_lib.bpf.h` declares the iterate kfuncs with a parameter of
     *function* type literally named `iter_fn`. A stock 6.18 `vmlinux.h`
     contains `typedef enum it_action (*iter_fn)(struct dm_buffer *, void *)`
     from dm-bufio; once `iter_fn` is a typedef name, `int (iter_fn)(int
     idx, ...)` re-parses as "function returning a function type" and clang
     errors. Their 6.6.8 BTF lacks that typedef, which is why upstream never
     saw it. Cost of the fix: zero — it renames a parameter.
  2. `#define PG_hugetlb 26` when absent. v6.18 removed `PG_hugetlb` from
     `enum pageflags`; `cache_ext_lib.bpf.h::folio_test_hugetlb()` still
     names it. `hotset_protect` never calls that function.
- **2026-09-06** — sources authored; `git apply --check` of
  `cache_ext_hotset.patch` passes; nothing compiled.
