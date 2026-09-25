# 00 — Concept & Context

**Status:** DEFERRED 2026-09-25 (DESIGN ONLY / UNMEASURED since 2026-06-30; no code was ever written) — **DESIGN ONLY / UNMEASURED (2026-06-30).**

This document records the full idea trail, in the order it was reasoned out, so
the conclusions in `03_GO_NO_GO.md` can be audited against their premises.

## 0. The system these ideas have to fit

The thin-client stack (see `../THIN_CLIENT_SWAP.md`) is a 150M-doc academic
search engine whose whole thesis is: **large total footprint, tiny resident
working set, CPU-served, page-cache-resident, no JVM/GPU in the serving path.**

Four constraints decide whether any new idea is applicable:

1. **Memory/storage-bound, not compute-bound.** BMP at 150M is ~211 GB resident
   ("unservable on real hardware"). Everything is built to *avoid* loading the
   corpus into RAM.
2. **Incremental ingest.** OpenAlex monthly rebuilds + a query-driven warm cache.
   Documents arrive continuously.
3. **Exact match + structured filters are non-negotiable.** year/type/is_oa
   fast-field filters, exact lexical (tantivy positions-off lossless), exact
   posting-list dot products. A catalog cannot run on fuzzy recall alone.
4. **Auditability.** The Analytics app discloses corpus provenance per result.

Two further constraints were added by the user during this discussion:

5. **Must run on any hardware, scaling up *and* down.** Laptop → big server, same
   code.
6. **The sparse leg engine is fully immutable** (SEISMIC/BMP-class: built
   offline, served read-only). It cannot accept an in-place insert.

## 1. Autoregressive / generative *retrieval* (DSI / NCI / SEAL) — rejected as a replacement

Generative retrieval replaces the inverted index with a decoder that **generates
document IDs autoregressively** from the query, constrained by a trie/FM-index
of valid IDs (DSI = Differentiable Search Index, Tay 2022; NCI; SEAL grounds
generated n-grams in an FM-index).

Appeal: it folds "the index" into fixed-size model weights, seemingly dissolving
the 211 GB postings problem.

Why it fails **as a replacement** here — it breaks all four base constraints:

- **Scale.** No convincing results past ~few-million docs (MS MARCO 8.8M is the
  usual ceiling, where it *underperforms* dense/sparse). 150M is far out of
  proven range — capacity & catastrophic-forgetting walls.
- **Updates.** Adding a doc = finetune/retrain (DSI++ is the open problem).
- **No exact match / filters.** Loses year/type filters and exact dot-product
  guarantees.
- **Latency/hardware.** Constrained beam search wants a GPU; it is the opposite
  of the cheap CPU posting-list scan this stack optimized.

Where it *could* live (steelman, not a recommendation): a **bounded generative
leg** over a small hot subset (e.g. the warm-cache cap, not the 150M), fused via
the existing RRF k=60; or **generative rerank** of a small candidate set (but a
cross-encoder reranker already exists).

## 2. MoE with a specified set of active params — already realised structurally

MoE = large total params, a router activates only top-k experts per token → big
capacity at fixed *active* FLOPs.

Key observation: **this system already implements a hand-routed MoE at the index
layer.** `lib/thinclient/sections.py` is a 5-way disjoint-vocabulary router;
personas + era sub-sections are the experts; hot/cold packing + section-unpack
is conditional activation (only the relevant partition is paged in).

So MoE applicability splits:

- **As a model:** the only place it fits is a **per-domain MoE reranker/encoder
  routed by the existing section classifier** (med vs CS vs social-science
  experts). Strongest concrete fit, but small payoff.
- **Constraint mismatch:** MoE reduces *compute/FLOPs*; this stack is bound by
  *RAM/storage*. The full expert set still has to be resident or paged. MoE
  helps when GPU/compute-bound — which the serving path deliberately is not.

## 3. Autoregressive doc-ID assignment — "Meaning A vs Meaning B"

The user then narrowed to the update problem: *"could we build an auto-updater
that autoregressively creates document IDs for new incoming information?"* Two
very different readings:

- **Meaning A — autoregressive *retrieval* that learns new docs.** A decoder
  that memorises the corpus, taught new docs by updating weights. This is
  DSI++, the unsolved problem (forgetting, retrain-to-add). **Do not build.**

- **Meaning B — autoregressive *ID assignment* at ingest.** The ID is not an
  arbitrary integer; it is a **hierarchical semantic address generated
  token-by-token** by walking a learned tree (NCI hierarchical k-means, or
  RQ-VAE residual quantization). "Autoregressive" = each level conditions on the
  one above; similar docs get similar prefixes. **Assignment is forward-only** —
  run the new doc through the *frozen* quantizer, it falls into the right leaf.
  No retrain, no forgetting. **This is the buildable auto-updater.**

The user confirmed the target is the **extension of Meaning B**: autoregressive
ID assignment at ingest, *on the host*.

### You already built the hand-coded version of Meaning B

`sections.py` + the era axis already emit a 2-token semantic address:

```
<subject>__<era>      e.g.  med_bio__recent
   ↑          ↑
 token 1    token 2          ← a depth-2 semantic document address, by hand
```

The autoregressive doc-ID is the **generalisation**: replace the hand-coded
vocab rules with a learned tree and let the address go deeper
(`med_bio · recent · oncology · immunotherapy · …`), each level emitted from the
doc's SPLADE/dense vector.

### Honest decoupling (important)

The immutability / scalability / hardware properties come from the ID being a
**deterministic hierarchical address** — *not* from it being *learned*. The
learned part is purely a **quality** lever (better locality than vocab rules).
This permits a two-stage path: ship the architecture with the existing
rule-based router first (zero ML risk), swap in the learned tree later.

## 4. The two added constraints select *for* this design

- **Immutable sparse leg** → the only sane pattern for "immutable index + new
  data" is **LSM / segment-append + merge**, and the recurring question there is
  *"which segment does this doc belong to, and which segments must a query
  touch?"* — which is **exactly what a semantic ID answers, computed at ingest,
  forward-only, on the host CPU.** Immutability is the *reason* the ID is the
  right primitive, not an obstacle.

- **Any hardware / scale up & down** → because the ID is hierarchical, you cut
  shards at **any prefix depth**: depth-2 = a few big segments (laptop), depth-5
  = many small segments (big host). Same ID scheme, different cut depth.
  Resharding = "re-bucket by a different prefix length," not "recompute IDs."
  The current depth-2 hand-coded sections cannot do this.

See `01_ARCHITECTURE.md` for the resulting design and the Lucene reality-check
that bounds what is actually novel.
