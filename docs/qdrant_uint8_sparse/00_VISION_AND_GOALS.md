# 00 · Vision & Goals — Qdrant sparse uint8 quantization ("move 1")

**Opened:** 2026-06-27 · Scope: the SPLADE sparse leg only (BM25F/dense unchanged).

## What we are deciding

Whether quantizing the **Qdrant sparse (SPLADE) leg from float32 → uint8** (the
`datatype` knob on the sparse index) eases the 150M RAM/latency wall **on a host we
already have**, while holding RRF NDCG@10 at the current **0.560**.

This is the cheapest fallback identified after the SEISMIC spike arced toward KILL
(quality: G2 leg overlap frozen at 0.479, non-tunable; G6 unmeasurable at persona
scale — see `../seismic_150m_testbed/06_FINDINGS.md`). Unlike SEISMIC it needs **no
new engine, no JVM, no fork** — only a build-time config change on the stack already
in production. The cost matrix lists it as "move 1 (proposed)"
(`../qdrant_vs_lucene_assessment/STACK_COST_MATRIX.md` Tables 1–3).

## Verified starting state (2026-06-27)

**uint8 is confirmed UN-ACTIONED in this codebase:**

- The only Qdrant sparse-collection build, `scripts/spike_qdrant_sparse.py:159`,
  creates the collection with `models.SparseVectorParams(index=models.SparseIndexParams(on_disk=True))`
  and **no `datatype=` argument** → values default to **float32**.
- No `Datatype.UINT8` / `datatype=` appears anywhere in `src/` or `scripts/` for the
  Qdrant sparse path.
- The only "8-bit" actually implemented in the repo is **BMP impact quantization**
  (`src/lib/thinclient/builder.py:34` `QUANT_SCALE=70`) — a property of the *retired*
  BMP engine, NOT of the live Qdrant sparse leg. Do not conflate the two.

So `on_disk=True` already pushes the posting **lists** to mmap, but the stored
**values are full f32** — the uint8 lever has never been pulled.

## How it works (cross-referenced against Qdrant's own docs, 2026-06-27)

| Fact | Source |
|---|---|
| Sparse vectors accept `datatype`: **uint8 \| float16 \| float32 (default)**, set under the sparse **index** config | [Qdrant — Vectors](https://qdrant.tech/documentation/manage-data/vectors/); [Python client models](https://python-client.qdrant.tech/_modules/qdrant_client/http/models/models) |
| f32 → uint8 scalar quantization cuts the searchable representation memory by **~75% (≈4×)**; float16 = ~50% (2×) | [Qdrant — Quantization](https://qdrant.tech/documentation/manage-data/quantization/); [What is Vector Quantization?](https://qdrant.tech/articles/what-is-vector-quantization/) |
| **The original values are still stored on disk regardless of the datatype** — so `datatype` shrinks the *in-memory / searchable* index, not the full-precision on-disk copy. This is exactly why it eases page-cache pressure without a quality floor change to the stored data. | [DeepWiki — Vector Storage Formats](https://deepwiki.com/qdrant/qdrant/3.1-vector-storage-formats) |
| **Sparse vectors "can be quantized in-flight"** — unlike *dense* uint8 (which requires inputs pre-scaled to 0–255), sparse uint8 does **not** require us to re-scale SPLADE weights ourselves. This removes the biggest implementation risk the generic uint8 caveat implies. | [Qdrant — Vectors](https://qdrant.tech/documentation/manage-data/vectors/) |
| Scalar-quantization error is typically **< 1%**, smaller for high-dim vectors | [What is Vector Quantization?](https://qdrant.tech/articles/what-is-vector-quantization/) |

**Net mechanism:** set `datatype=uint8` (or `float16`) on the sparse index → the
RAM-resident/searchable index shrinks ~4× (uint8) or ~2× (float16); full-precision
values remain on disk; the 6.55 GB **per-point anon floor is structural and does NOT
change** (`../qdrant_vs_lucene_assessment/FINDINGS.md:89`) — but the page-cache the
index *wants* (the real driver of the 64–128 GB host requirement at 150M) drops hard.

## Goals (must-hit, priority order)

1. **G-QUALITY — no regression.** RRF NDCG@10 within ±0.005 of **0.560** (the 34-common
   LLM-judge bar, identical regime as `../seismic_150m_testbed/03_BENCHMARK_METHODOLOGY.md`);
   leg overlap@10 vs the f32 collection ≥ 0.95. *Currently UNMEASURED for Qdrant sparse
   uint8 — proven only for BMP 8-bit impacts; this gate is the whole point of the spike.*
2. **G-RAM — ease the wall on the host we have.** Measure the drop in RssFile/page-cache
   demand and warm/active RSS at a fixed corpus size (30M persona first), f32 → float16 →
   uint8. Report per-doc so 150M extrapolation is honest.
3. **G-LATENCY — no regression (ideally a win).** Warm p50/p95 should hold or improve
   (smaller cacheable index + SIMD on 8-bit). Compare against the f32 baseline on the
   same host.
4. **G-OPS — zero new moving parts.** A build-config change only; no JVM, no new engine,
   reuse the stored SPLADE `sparse_field` (no re-encode).

## Non-goals

- Removing the 6.55 GB anon floor (structural; `datatype` cannot touch it — only fewer
  points/sharding or a different engine can).
- Touching BM25F (tantivy) or dense (usearch) legs.
- Re-encoding SPLADE.

## Definition of success / kill

- **GO:** G-QUALITY holds (±0.005) AND G-RAM shows a material page-cache reduction at
  persona scale → roll uint8 (or float16 if uint8 regresses quality) into the live build;
  update `STACK_COST_MATRIX.md` move-1 row from *est.* to **measured**, and
  `THIN_CLIENT_SWAP.md` + `STORAGE_BUDGET_150M.md`.
- **FALLBACK within this spike:** if uint8 regresses quality past ±0.005, test **float16**
  (2× instead of 4×, no quantization error of consequence) before abandoning.
- **NO-GO:** both uint8 and float16 regress quality past the bar → document the number,
  fall back to the broader ladder (bigger Qdrant host / OpenSearch+SEISMIC), sunk cost
  capped at the failed gate.

## Evidence ledger (to fill as measured — CLAUDE.md efficacy rule)

| Gate | Metric | Instrument | Result file | Status |
|---|---|---|---|---|
| G-QUALITY | RRF NDCG@10 (34-common) + overlap@10 vs f32 | (reuse `eval_thinclient_parity.py` against a uint8 collection) | `data/eval_results/qdrant_uint8_parity_<ts>.json` | **UNMEASURED** |
| G-RAM | RssAnon/RssFile + page-cache demand, f32→fp16→uint8 @30M | Qdrant `/metrics` + `/proc/<pid>/status` | `data/eval_results/qdrant_uint8_ram_<ts>.json` | **UNMEASURED** |
| G-LATENCY | warm p50/p95 @30M, uint8 vs f32 | existing measure cadence | `data/eval_results/qdrant_uint8_latency_<ts>.json` | **UNMEASURED** |

> All three are **IMPLEMENTED: NONE; EFFICACY: UNMEASURED** as of 2026-06-27. No claim
> here is a result until its row above carries a measured number, an absolute date, the
> eval script, and the result-file path.
