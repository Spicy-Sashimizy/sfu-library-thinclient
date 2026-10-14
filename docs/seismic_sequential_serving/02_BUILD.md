# 02 · Build & Artifacts — INDEPENDENT of the parallel path

**Status:** DEFERRED 2026-07-16 (measured WI-1 but never promoted; parallel federation is still the served path)

**Created 2026-06-30, implemented 2026-06-30 (mechanisms A + B).** This doc is
**self-contained**: you can follow the sequential track from here without reading
the parallel federation build docs. The mode flag + the `release_pages` hook are
shipped (mechanism (B) needs the rebuilt `.so`); the 150M latency/RAM win is
unmeasured per `04`.

## Headline: there is no separate build

Sequential serving is a **runtime mode over the exact same immutable shards** the
parallel path uses. "Build once, serve many" is a standard immutable-index pattern
— the expensive offline organisation happens once; multiple query-execution modes
read the same artifacts `[literature]`
([IVF two-phase build-once](https://mbrenndoerfer.com/writing/ivf-index-clustering-vector-search-partitioning),
[Milvus multi-mode execution](https://www.cs.purdue.edu/homes/csjgwang/pubs/SIGMOD21_Milvus.pdf)).
So this doc's job is to (1) state exactly which artifacts sequential consumes, and
(2) prove sequential adds **no new build state** and **no coupling** to the
parallel path.

## Artifacts sequential consumes (the only inputs)

1. **8 stock SEISMIC shards** — the G7 build, 150,413,098 docs, ~8.28 GB each,
   `global_shard{0..7}of8.index.seismic`.
2. **8 converted C2 mmap directories** — `global_shard{0..7}of8.mmap/` (flat doc-mapping
   layout: `document_mapping_strings.bin` + `document_mapping_offsets.bin`), one
   sibling directory per shard, produced by `convert_shard_to_mmap.py`.
3. **A shard manifest** — JSON listing each shard's `index_path` + `mmap_dir`
   (same shape as `data/eval_results/seismic_c25_shards_150m_mmap.json`).
4. **The SPLADE encoder** — `models/splade_onnx_fused` since 2026-07-09 D2
   (bert-fused export of the same fp32 weights, shared by both serving
   methods; was `models/splade_onnx_fp16`).

**Sequential requires zero artifacts the parallel path doesn't already produce.**
It does not re-shard, re-convert, or re-encode anything.

## If you are starting from nothing (self-contained build recipe)

Run with the project venv (`/workspaces/sfu-library-thinclient/.venv/bin/python3`):

1. **Build the 8 stock shards** (serial, fits 32 GB):
   `scripts/seismic_testbed/build_plan01_150m_shards.py`
   → `global_shard{0..7}of8.index.seismic` + a build manifest.
2. **Convert each to the C2 mmap layout** (serial, ~7 min total, peak ~9.9 GB):
   `scripts/seismic_testbed/convert_shard_to_mmap.py`
   → `global_shard{0..7}of8.mmap/` + `seismic_c25_shards_150m_mmap.json`.
   *Load-bearing:* the `.mmap/` directories MUST be from the **current C2 writer**
   (strings+offsets). A stale C1a `document_mapping.bin` makes the C2 reader load
   `doc_mapping=None` → ids collapse to numeric → wrong results. (Same constraint
   the parallel path documents — restated here so this doc stands alone.)
3. **Point the serve at the manifest** — set `SFU_SEISMIC_SHARD_MANIFEST` to the
   manifest path and `SFU_SEISMIC_LOAD_MODE=mmap` (Path C; never stock at 150M).

Steps 1–2 are the *shared* immutable build. Step 3 + the mode flag (next section)
is all that's sequential-specific.

## The only sequential-specific knob

```
SFU_SPLADE_BACKEND=seismic            # use the SEISMIC SPLADE leg
SFU_SEISMIC_SHARD_MANIFEST=<path>     # the 8-shard manifest
SFU_SEISMIC_LOAD_MODE=mmap            # Path C (bounded anon floor) — never stock @150M
SFU_SEISMIC_FEDERATION=sequential     # <-- SHIPPED 2026-06-30 (default: parallel)
```

`SFU_SEISMIC_FEDERATION=sequential` is the entire build-time/config surface of this
feature. **Shipped** (mechanisms A + B): wired into `retriever._seismic_backend()`,
which picks `SequentialSeismicBackend` directly; the serial branch (A) + the
`--federation` CLI flag on the bench/testbed probe are live. Mechanism (B)
(`MADV_DONTNEED` `release_pages`) requires the **rebuilt `.so`** —
`cd spike/seismic_upstream && sudo environment "PATH=$PATH" CARGO_HOME=/usr/local/cargo
RUSTUP_HOME=/usr/local/rustup <venv>/python -m maturin develop --release` — which
adds `MmapSeismicIndex.release_pages()` additively (parallel never calls it). If the
rebuilt `.so` is absent, `_fan_out`'s `hasattr` guard skips (B) and logs a debug
line — correct results, just the soft (kernel-reclaim) bound. Absent or `parallel` →
the existing behaviour, byte-for-byte (T1 result-equivalence + the mechanism-(B)
re-fault test verified on a synthetic shard; 150M latency unmeasured per `04`).

## Independence guarantees (why this can't destabilise the parallel build)

- **Shared inputs are immutable.** The shards + mmap directories are read-only at serve
  time; a serving mode cannot mutate them.
- **No new persisted state.** Sequential writes nothing to disk that parallel reads
  (or vice-versa). No shared lock, spool, checkpoint, or sidecar.
- **No concurrency assumption.** The parallel path's `ThreadPoolExecutor` is
  untouched; the serial branch introduces no thread/GIL coupling.
- **Mode is process-local and exclusive.** Chosen once at `_seismic_backend()`
  load from one environment var; the two modes are never co-active in a process.
- **Mmap-only, no silent fallback.** A missing `.mmap/` directory raises `RuntimeError`
  (never a silent stock Path-A reload that would re-introduce the ~137 GB anon
  floor) — identical safety contract to the parallel path, asserted in
  `03_TESTING.md`.

## What a future *true* sequential-optimised build could add (out of scope now)

Only if benchmarking (`04`) shows per-shard fault cost dominates: re-converting
shards so each shard's hot inverted+summary side is **laid out contiguously** for
sequential pre-fault. This is an *optional* future artifact change, explicitly NOT
required for the first sequential serve, and would get its own versioned mmap directory
so it never overwrites the shared artifacts. Tracked here as design-only.
</content>
