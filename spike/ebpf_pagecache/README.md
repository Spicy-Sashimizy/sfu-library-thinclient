# eBPF page-cache policy spike (cache_ext) — hot-set-aware eviction

> Test battery (what gets measured, phased): `TEST_SITUATIONS.md`.

**Status 2026-09-06: CODE STAGED, NEVER COMPILED, NOTHING MEASURED.** No
cache_ext kernel exists in this container (no clang/bpftool/libbpf either);
the bar met is source-idiom fidelity against the pinned upstream tree, not
buildability. Every claim below marked *code-read* is from reading the
upstream source at a pinned commit; nothing here is a runtime measurement.

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
| `hotset_protect.bpf.c` | The policy: two lists (cold drained first; hot touched only when the eviction request is still unfilled), hot membership via a `{ino, pgoff>>6}` → 64-page-bitmap hash map, always-on stats array for the visibility probe. Idioms copied from upstream `cache_ext_fifo`/`cache_ext_s3fifo` (nearest structural models — upstream has no extent-based policy). | NEVER COMPILED |
| `hotset_protect.c` | Userspace loader, structural clone of upstream `cache_ext_fifo.c`; adds `--hot_chunks FILE` and pins the stats map. | NEVER COMPILED |
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
