# SEISMIC 150M — Build Plans (RAM-escape engineering)

**Created 2026-06-28.** These are the *implementation* plans that came out of the
2026-06-28 design session on "can we run a full-corpus SEISMIC leg on the 32 GB
WSL2 box without the JVM." They are build/engineering plans, NOT new gate
decisions — the quality verdict is unchanged (see below). Each plan exists to make
a 150M SEISMIC leg **buildable and servable on the hardware we have**, so the one
unresolved gate (G6 RRF parity) can finally be measured.

## The forcing facts (measured this session, do not re-derive)

- **Forward index is the build-RAM floor and it is LINEAR in non-zeros:**
  4.10 bytes/nnz (constant across the 8M and 20M builds), 76.7 nnz/doc (constant).
  → 150M ≈ 11.5B nnz ≈ **~47 GB forward index, resident during a stock build.**
- **Measured build peak RSS:** 929k→1.91 GB, 2M→2.83 GB, 8M→5.11 GB, 20M→9.54 GB.
  Refined 150M projection (forward-floor + sub-linear scratch) ≈ **55–63 GB peak**.
  The earlier "25 GB power-law" lower band is NOT credible (it ignored the linear
  forward floor) — corrected here.
- **Host:** WSL2 dev container = 32 GB RAM + 16 GB swap (48 GB addressable);
  Windows host total = 64 GB. → a stock monolithic 150M build does **not** fit.
- **Serving is already solvable:** Path C (mmap) measured **+0.041 GB anonymous
  RAM, 96 % file-backed**. The forward index can live on disk; page cache hydrates
  candidate vectors on demand (this is exactly how OpenSearch serves SEISMIC at
  billion-scale: forward on disk, pruned inverted index in RAM).
- **Quality verdict is NOT changed by any plan here:** G2 overlap@10 vs Qdrant =
  **0.479**, fails the 0.95 bar on all three index levers (`02_GO_NO_GO_GATES.md`).
  These plans change *feasibility*, not whether SEISMIC beats Qdrant on quality.
  Their only job is to unblock the **G6 RRF system-level** measurement.

## The plans (pick by constraint)

| # | Plan | Solves | JVM? | Lossy? | Fits 32 GB build? | Effort |
|---|------|--------|------|--------|-------------------|--------|
| [01](01_SHARDED_BUILD_FEDERATED_QUERY.md) | Sharded build + federated query (OpenSearch segment-model ported to pure Rust) | **build RAM** | no | **no** (lossless per shard) | **yes** | high (build a shard manager + query fan-out) |
| [02](02_BUILD_ONCE_SERVE_MMAP.md) | Build-once on a bigger host, serve mmap on 32 GB | build RAM (one-time) | no | no | n/a (build elsewhere) | low |
| [03](03_COMPRESSION_AND_NNZ_REDUCTION.md) | Forward-index compression (DotVByte) + source nnz reduction | serve RAM + (lossy) build RAM | no | mixed | partial | medium |
| [04](04_CROSS_ENGINE_METADATA_DEDUP.md) | Cross-engine metadata externalization (store-once, hydrate-by-id) | serve RAM / storage only | no | no | n/a (orthogonal) | low |

## Recommended sequencing

1. **02 first** if any ≥56 GB box (or a bumped `.wslconfig`) is reachable — it is
   the cheapest path to a measurable G6 and needs no new code.
2. **01** if the build host is *permanently* capped at 32 GB — it is the only
   *lossless* way to dissolve the build wall on this hardware, and it ports the one
   missing OpenSearch idea (segmented build) into the Rust stack without the JVM.
3. **03** only as an adjunct — it mostly helps serving (already handled by mmap),
   and its build-RAM help is *lossy* (pushes on the failing 0.479 quality axis).
4. **04** any time — orthogonal serving-RAM win, applies even if SEISMIC is killed
   (it benefits the live Qdrant deployment too).

> **Honest framing for all four:** none of these make SEISMIC's 0.479 quality beat
> Qdrant's exact scoring. They are the cheapest paths to *resolving* the SEISMIC
> question (run G6) on our own box. If G6 also fails, the KILL basis is complete.
