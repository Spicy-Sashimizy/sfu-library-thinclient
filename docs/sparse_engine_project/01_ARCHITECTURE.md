# 01 · Architecture

> **CLOSED — line MEASURED & STOPPED 2026-06-26.** Written while the mmap-BMP /
> `immsparse` engine was a live option. At the 150M target scale the bespoke engine
> loses to FOSS (pruning linear in corpus; inverted-side RAM ~7.6× the Qdrant floor).
> Historical design context only — current verdict in `README.md` + `07_INTEGRATION_PLAN.md` §8.

## Legs (unchanged retrieval math — only the sparse storage changes)
| Leg | Engine | Property |
|---|---|---|
| Lexical BM25F | tantivy 0.26 | immutable mmap segments, ~0 resident (already have it) |
| **Sparse SPLADE** | **`immsparse` = mmap-backed Block-Max (BMP fork)** | **the new piece** — immutable, mmap'd postings, ~0 anon floor |
| Dense | usearch b1 + int8 rescore (or Lance) | mmap, ~0 resident (already have it) |
| Fusion / rerank | Python RRF k=60 + cross-encoder | unchanged |

## The sparse leg — what changes vs stock BMP
Stock BMP `Searcher` deserializes the `.bmp` into owned `Vec` buffers (anonymous
RAM, 3.07×). The fork backs those buffers with `memmap2::Mmap` and builds
**zero-copy `&[u8]` views/offsets** into the mapped file. Search is unchanged.

```
.bmp file on disk (immutable)
   └─ mmap (Mmap) ──► &[u8]
        ├─ block-max (TERM-MAJOR, contiguous per term)  ← block-filtering streams these
        └─ within-block forward postings                ← block-eval reads a few, pruned
   accumulator (per-block score array, ~0.6–2 MB) stays resident
   RssAnon ≈ 0 ; hot pages = reclaimable page cache
```

Why it works (source-checked, `qdrant_vs_lucene_assessment/ARCHITECTURE_EXPLAINER.md` §6):
`PostingList.range_maxes` is term-major and contiguous, so block-filtering reads
*q* contiguous runs (one per query term) + a small resident accumulator — the same
mmap-friendly access pattern Lucene/tantivy already serve. Only cost: cold-cache
~*q* page faults on first touch (the open risk, measured in P2).

## Storage substrate — two options (decide at P3)
| Option | What | Pros | Cons |
|---|---|---|---|
| **A. Standalone mmap-BMP** | keep `.bmp` files, just mmap them; tantivy + usearch stay separate engines behind the existing retriever interface | smallest change; reuses the whole current build/serve path; spike-native | 3 stores (not unified); no shared columnar format |
| **B. Lance-unified** | store sparse postings (+ lexical + dense) as Lance columns; one immutable versioned store; implements the LanceDB-#1930 sparse index using BMP's algorithm | true unification (G-UNIFIED); versioning; embeddable; community value | much larger build; Lance integration is the bulk of the work |

**Recommended sequencing:** prove the cure with **A** (P0–P2, here), then decide
whether **B** is worth it (P3+, spun-off repo). A already hits G-RAM/G-QUALITY/
G-LATENCY/G-NOJVM/G-DISK; B adds G-UNIFIED at real cost.

## Build & serve
- **Build (immutable):** corpus → SPLADE `sparse_field` (already stored, no
  re-encode) → BMP b256 clustered builder (already in `builder.py`) → `.bmp`
  (option A) or Lance columns (option B). Per-section, fits hot/cold packaging.
- **Serve:** drop-in behind `SFU_SPLADE_BACKEND` (add `immsparse` next to
  `qdrant`/`bmp`); `_load()` mmaps shards; degrade-to-BM25F contract unchanged.
- **Tiers:** server = full 150M (all sections, mmap, ~0 floor); local = per-persona
  hot section (per-section `.bmp`, already how packing works) — same engine.

## What stays identical (de-risks quality)
Quantization (×70 8-bit), alpha/beta (0.8/1.0), query encoder, top-64 query terms,
RRF k=60, rerank. The fork changes *where bytes live*, not *what is computed* —
which is why G-QUALITY is a byte-identical check, not a re-eval.
</content>
