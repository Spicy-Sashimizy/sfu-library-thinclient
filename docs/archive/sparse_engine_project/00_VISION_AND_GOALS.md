# 00 · Vision & Goals

> **CLOSED MEASURED 2026-06-26** — the bespoke sparse engine was MEASURED & STOPPED 2026-06-26 (verdict STOP in `07_INTEGRATION_PLAN.md` §8: pruning linear in corpus, ~50 GB inverted side at 150M). SEISMIC federated mmap took the slot (promoted 2026-07-06, `docs/archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md`); the FORMAT-WALL result is kept. Not current; do not resume.

**Status:** CLOSED MEASURED 2026-06-26

> **CLOSED — line MEASURED & STOPPED 2026-06-26.** Written while the mmap-BMP /
> `immsparse` engine was a live option. At the 150M target scale the bespoke engine
> loses to FOSS (pruning linear in corpus; inverted-side RAM ~7.6× the Qdrant floor).
> Historical design context only — current verdict in `README.md` + `07_INTEGRATION_PLAN.md` §8.

## Vision

A single **no-JVM, immutable, mmap-backed** retrieval engine that serves the
lexical (BM25F), learned-sparse (SPLADE), and dense legs from **one store**, with
**zero per-document resident RAM floor** — so a 150M-doc index serves on commodity
RAM the way a memory-mapped inverted index already does, and a persona-sized subset
runs on a laptop. It must preserve the quality this stack already measured
(**+0.111 NDCG@10 over OpenSearch**, BMP≡Qdrant parity) and add no new recurring
operational overhead (no JVM, no cluster).

## Why now / why this shape
The assessment established the root cause and the gap:
- **Root cause of the 150M pain:** Qdrant's *mutable / MVCC* store keeps per-point
  bookkeeping in non-reclaimable anonymous RAM (~43 B/point → 6.55 GB at 150M,
  rising). Immutable-segment engines (Lucene/tantivy) bake that on disk → ~0 floor.
- **The gap:** no production **no-JVM** engine unifies lexical + *indexed* sparse +
  dense on immutable mmap'd storage. tantivy lacks a sparse field; LanceDB stores
  sparse but has no sparse index; Seismic/BMP are load-into-RAM; OpenSearch+SEISMIC
  cures it but is JVM.
- **The opening:** BMP's Block-Max algorithm is measured-good and its postings are
  **term-major + contiguous** — i.e. already mmap-shaped (source-checked). Loading
  into RAM is an engineering choice, not an algorithmic need.

## Goals (must-hit, in priority order)
1. **G-RAM — cure the floor.** Sparse leg RssAnon ~0; serving RAM = reclaimable
   hot working set, flat in corpus size (not 43 B/point rising).
2. **G-QUALITY — no regression.** Top-k byte-identical to stock BMP; system RRF
   NDCG@10 within noise of today (and still > OpenSearch by ~0.11).
3. **G-LATENCY — acceptable cold + competitive warm.** Warm p50 ≤ Qdrant on equal
   hardware; cold p95 within ~2–3× warm at section scale.
4. **G-NOJVM — no JVM, embeddable.** Runs as a library on a laptop and a server.
5. **G-UNIFIED — one store** for lexical+sparse+dense (fewer engines than today's 3).
6. **G-DISK — no worse than today**, ideally ~3× better on the sparse leg
   (BMP b256 68.6 GB vs Qdrant f32 205 GB).
7. **G-OPS — low overhead.** Immutable build artifacts; reuse the stored SPLADE
   `sparse_field` (no re-encoding); fits the existing hot/cold persona packaging.

## Non-goals (explicitly out of scope)
- **Live high-rate updates / true mutability.** Immutable rebuild + segment swap is
  the model (monthly cadence, like today's build). If you need live upserts at
  scale, that's a different engine (Qdrant/OpenSearch) — don't build this.
- **Beating SOTA on raw sparse QPS.** Parity with the measured stack is the bar,
  not winning benchmarks.
- **Replacing the laptop/demo Qdrant tier *if* it already meets goals.** Per-persona
  Qdrant (~1 GB floor) is fine locally; this project's prize is the **150M server**
  (and a unified engine that *could* also serve local).
- **A general-purpose vector DB.** Scope is exactly this corpus's three legs + RRF.

## Definition of success / failure
- **Success (fully realize):** P0–P5 gates all green → an `immsparse` engine that
  serves 150M on a right-sized-but-JVM-free box at today's quality with ~0 anon
  floor, packaged for both tiers. Spin off to its own repo at P2.
- **Kill (cheaply):** any HARD gate fails (correctness, RssAnon, or cold-p95 blows
  up) → stop, document the number, fall back to the pragmatic paths (per-persona
  Qdrant local; Infinity or OpenSearch+SEISMIC server). Sunk cost capped at the
  phase that failed.
</content>
