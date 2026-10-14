# SEISMIC instrumentation fork — for G4 pruning-sub-linearity

This is the **minimal Rust-source patch** to `TusKANNy/seismic` that exposes a
per-query candidate counter the FOSS Python bindings don't — the faithful
surrogate for the BMP-style `blocks_scored` the G4 gate measures
(`docs/seismic_150m_testbed/02_GO_NO_GO_GATES.md` G4).

## Why a fork

`seismic.SeismicIndex.search` returns only the top-k. The traversal's
`visited: FxHashSet` (the set of distinct documents the block-prune frontier
actually scored) is Rust-local and not bound. The G4 metric is
**candidates_scored / corpus** at two corpus sizes — the *exact* axis BMP died
on (ratio ~0.95, linear). Without a counter, G4 is unmeasurable directly.

## The patch

Three additions, all mirroring existing `search` paths, sharing a new
`search_inner` so search() and search_with_stats() traverse identically:

- `src/inverted_index.rs`: refactor `search` → `search_inner` returning
  `(Vec<ScoredVectorDotProduct>, usize visited.len())`; add `search_with_stats`
  returning the tuple; `search` drops the count.
- `src/inverted_index_wrapper.rs`: `search_raw_with_stats` + `search_with_stats`
  (mirrors `search_raw`/`search`, returns `(Vec<SearchResult>, usize)`).
- `src/pylib/mod.rs`: Python `search_with_stats(...) -> (results, n_candidates)`
  with the same `#[pyo3(signature)]` as `search`.

`candidates_scored` = `visited.len()` = unique docs whose forwarding postings
blocks the traversal touched. This is the BMP `blocks_scored` analog (a per-query
count, normalized by corpus size for the sub-linearity ratio).

**NOTE on fidelity:** `visited` counts *documents*, not *blocks*. BMP's probe
counted *blocks* (each block = 32 docs). Both are "the work the frontier did";
normalized per-corpus the sub-linearity signal is the same kind. If a finer
per-block count is needed later, instrument `posting_list.rs::search/sort_and_search`
(the block loop); `visited` is the cheaper, faithful-enough one for the gate.

## Build

The throwaway wheel builds into a **separate venv** (NOT the serving `.venv`):

```bash
/usr/bin/python3 -m venv /tmp/seismic_testbed/instr_venv
/tmp/seismic_testbed/instr_venv/bin/pip install maturin numpy
cd /workspaces/sfu-library-thinclient/spike/seismic_upstream
RUSTFLAGS="-C target-cpu=native" /tmp/seismic_testbed/instr_venv/bin/maturin develop --release
```

## vectorium pin (build-environment fix, not instrumentation)

`Cargo.toml` pins `vectorium` at `rev = c484687` — the commit **before**
`74af320 "Introduce FlatIndex and remove Dataset::search"` removed
`SparseDataset::search`, which upstream's `inverted_index_wrapper.rs:792` still
calls (a transient upstream/vectorium version skew; the published 0.5.0 wheel
built against the pre-removal vectorium). This pin restores the API; it is a
build fix, not a behavior change.

## R-OBSOLETE re-check (per `05_RISK_REGISTER.md`)

Before any Path-C work, **re-verify** whether upstream has shipped its own
on-disk/on-counter mode (the ECIR-2025 "future work" names indexes that don't
fit in main memory). If they expose candidate counts natively, drop this fork
and use theirs. This fork is the *measurement* tool for G4, never a serving
dependency — it ships behind the gate, not into the product.

The cloned upstream is a git submodule-free checkout at
`spike/seismic_upstream/`; not committed to this repository (kept out via
`.gitignore`) — redoable from this README + the patch is small enough to
re-apply. Pinned at upstream commit `7782a13` (v0.4.0-tagged line).

## C0.5 bin — real compressed-format decode cost (`c0_5_compressed_decode`)

`src/bin/c0_5_compressed_decode.rs` (+ `[[bin]]` entry in `Cargo.toml`) is a
**second micro-bench**, not part of the G4 search patch. It measures the
`07_G3_RAM_FIX_PLAN.md` §4.1 *caveat* C0 left open: does the REAL upstream
compressed-format decode (`toolkit::EliasFano.select()` → `DArray.select1` block
walk, per query term; `BitField.get_unchecked()` → `get_bits` shift/mask, per
value scored — the literal `QuantizedSummary::distances()` path) re-create the
FORMAT-WALL? It uses the **real `toolkit::EliasFano` + `BitField` structs**
(not a reimplementation) over a faithful-shape synthetic summary slab, three
readers (compressed / zero-decode-floor / materialize), fixed work budget
(30 q × 64 terms) so the G4 confound can't hide.

**Build + run (release, persona scale matching C0):**
```bash
cd /workspaces/sfu-library-thinclient/spike/seismic_upstream
cargo build --release --no-default-features --bin c0_5_compressed_decode
./target/release/c0_5_compressed_decode \
    --n-terms 800000 --n-summaries 2000000 --avg-values-per-term 80 \
    --n-queries 30 --terms-per-query 64
```
(`--no-default-features` drops the pyo3/python feature so the bin links without
the Python extension machinery.)

**Result 2026-06-26:** `COMPRESSED_HOLDS` — compressed p50 4.82 ms is **1.07×**
the zero-decode floor (4.51 ms), within the 1.2× budget. The real
`DArray.select1` + `BitField.get_bits` per-query decode does NOT re-create the
wall → **the fork can mmap the compressed index as-is (cheap R-OWN, no POD
restructure)**. Result JSON:
`data/eval_results/seismic_c0_5_compressed_decode_persona.json`.
Like the G4 patch source, this bin's source is not committed (gitignored
`spike/`); redoable from this section.
