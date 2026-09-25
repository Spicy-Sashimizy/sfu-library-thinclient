# mmap-BMP feasibility spike — prototype HERE (isolated), spin off only after the gate

> **CLOSED SUPERSEDED 2026-07-06** — the "should we swap off Qdrant back to Lucene?" question was answered instead by promoting SEISMIC federated mmap (`docs/SEISMIC_ARCHIVE_SPLIT.md`). The RAM analysis and OOM findings remain the recorded evidence base for that move. Not current; do not resume.

**Status:** CLOSED SUPERSEDED 2026-07-06

**Date:** 2026-06-25 · Decision + runnable plan for the "does mmap-BMP's cold-p95
hold?" spike that gates the whole mmap-BMP-over-Lance idea (`ARCHITECTURE_EXPLAINER.md` §6).

## Decision: prototype HERE on an isolated branch; spin off only if the gate passes

**Prototype here.** Spinning off first would mean re-creating all the comparison
infrastructure for an experiment that may die in 1–2 days. Everything the spike
needs is already in this container (inventoried 2026-06-25):

| Need | Present here? |
|---|---|
| Rust toolchain | ✅ `cargo 1.96.0` / `rustc` (only `maturin` missing — one pip install) |
| Small test `.bmp` indexes | ✅ `data/thinclient_1m/sections/*/splade_000.bmp` (2.3 GB total) + `data/thinclient_test_resume/.../med_bio__recent/splade_00*.bmp` |
| Data to rebuild a persona-sized `.bmp` | ✅ `data/thinclient_index/spool_backup` (123 GB, all 5 sections) |
| Comparison baseline | ✅ live Qdrant `splade_150m` + `splade_par30` |
| Measure harness, parity eval, ×70 quant params | ✅ `scripts/archive/spike_qdrant_sparse.py`, `eval_thinclient_parity.py` |
| Disk headroom | ✅ 811 GB free |

The spike's entire value is **proximity to this exact data** (same SPLADE vectors,
same quant, same Qdrant to race against). Rebuilding that elsewhere is wasted setup.

**Spin off into a dedicated repo/container only AFTER the gate passes** — i.e. once
you're committing to *building and owning* the engine (Lance unification, a
maintained custom wheel, CI, the sparse-index work). That is a product with its own
lifecycle; the spike is a throwaway measurement.

## Isolation rules (non-negotiable — this container serves the MCP)

1. **Branch:** do it on a git branch, never on `sfu-library-thinclient` main state.
2. **Do NOT pip-install the forked `bmp` into the serving `.venv`.** That venv *is*
   the MCP server runtime (CLAUDE.md), and a forked wheel would **shadow the real
   `bmp`** that `SFU_SPLADE_BACKEND=bmp` fallback uses. Build the fork into a
   **separate throwaway venv** and import it explicitly in the spike script.
3. **Keep `target/` out of git** — build under the scratchpad
   (`/tmp/claude-.../scratchpad`) or gitignore it. The repo already fights multi-GB
   state bloat (CLAUDE.md); a Rust `target/` must not land in `.git`.

## The spike (≈1–2 days)

```
# 0. Tooling, isolated
python3 -m venv /tmp/.../mmapbmp-venv && that-venv/bin/pip install maturin

# 1. Fork BMP, swap load_into_memory -> mmap
git clone https://github.com/pisa-engine/BMP   # Apache-2.0
#   in src/index: back the PostingList/BlockData buffers with memmap2 (Mmap)
#   instead of Vec<u8> read-into-RAM. range_maxes is TERM-MAJOR + contiguous
#   (verified, ARCHITECTURE_EXPLAINER §6), so this is a buffer-source swap,
#   not an algorithm change. Build a wheel into the throwaway venv.

# 2. CORRECTNESS first (cheap, decisive): mmap results MUST equal load results
#   run both on data/thinclient_1m/sections/*/splade_000.bmp, assert identical
#   top-k ids+scores for the eval queries. If they differ, stop — the fork is wrong.

# 3. The number that gates everything: COLD vs WARM p50/p95
#   build a persona-sized .bmp from spool_backup (e.g. med_bio ~17M or
#   social_sciences__recent ~26M) so it does NOT fully fit page cache.
#   cold:  sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'  (or a fresh never-touched mmap)
#   then measure first-touch p50/p95; warm = repeat passes.
#   reuse the spike_qdrant_sparse.py measure cadence (40 queries, search-only).

# 4. Head-to-head vs Qdrant on the SAME section's points
#   (Qdrant splade_par30 / a per-section collection): warm p50/p95, resident RAM
#   (RssAnon must be ~0 for mmap-BMP vs Qdrant's anon floor), on-disk size.
```

## Gate (decide build-vs-kill from these numbers)

- **Correctness:** mmap top-k == load-into-RAM top-k, byte-identical. (Hard gate.)
- **RAM:** mmap-BMP `RssAnon` ≈ 0 (reclaimable page cache only) — confirms the
  floor is cured (the whole point).
- **Cold-p95 acceptable:** the open risk. Pass if cold-p95 is within ~2–3× warm and
  warm p50 ≤ Qdrant's on the same data. If cold-p95 blows up (scattered faults),
  the term-major layout wasn't enough and the idea is dead — cheaply.
- **Disk:** confirm the ~3× edge (BMP b256 vs Qdrant f32) holds at section scale.

**If the gate passes** → spin off a dedicated repo/container for the real engine
(Lance unification, maintained wheel, the LanceDB-#1930 sparse index). **If it
fails** → you spent ~2 days and killed "the dream" with data, no new container,
and the pragmatic paths (per-persona Qdrant local / immutable engine server) stand.
</content>
