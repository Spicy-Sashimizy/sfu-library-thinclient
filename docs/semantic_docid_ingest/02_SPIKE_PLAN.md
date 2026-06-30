# 02 — Spike Plan (Stage 1)

**Status: PROPOSED / NOT STARTED (2026-06-30).**

## Goal of the spike

Answer the **one question that can kill the idea** before writing any ML:
**does an LSM tier of immutable segments survive the mmap page-cache that the
thin-client thesis depends on?** Everything else (the learned tree, recall
gains) is downstream and only worth doing if this passes.

So Stage 1 deliberately uses **no machine learning**: the ID assigner is the
existing rule-based `sections.py` address, optionally extended one level by a
cheap deterministic hash. We are testing the *architecture*, not the ID quality.

## What to build (minimal)

1. **Deterministic hierarchical ID** from existing section rules
   (`<subject>__<era>[__<hashbucket>]`); bit-reproducible across hosts
   (integer/fixed-point, deterministic tie-break).
2. **Warm buffer** — reuse the dense-warm-cache pattern (RAM + SQLite
   durability) for the mutable, instantly-searchable delta.
3. **Flush** — buffer fills (RAM-triggered, per `04_LUCENE_BORROW.md` §2) →
   build one small immutable SEISMIC segment keyed by id-prefix.
4. **Compaction** — port `TieredMergePolicy` constants
   (`04_LUCENE_BORROW.md` §3) as a localised per-prefix SEISMIC rebuild.
5. **Generationed manifest + NRT swap** — atomic-rename commit + ref-counted
   reader (§1, §5). Wire the swap through the existing `reload_index` MCP tool.
6. **mmap hints** — `posix_madvise(MADV_RANDOM)` on posting regions (§5).

Tombstone deletes (§4) are **out of scope for Stage 1** — add only if the
architecture passes.

## What to measure (the success surface)

Run against a fixed corpus slice (suggest the existing 20M/30M build used by the
seismic testbed) replaying a realistic ingest stream, at two cut depths.

| Metric | Why | Compare against |
|---|---|---|
| **Resident set (RSS) vs. segment count** | the core mmap tension | the current full-rebuild single-segment-per-section baseline |
| **Query fan-out** (segments touched/query) | does prefix-locality bound it? | depth-2 vs deeper cut |
| **p50/p95 query latency** under N segments | tail latency is where LSM hurts | baseline immutable build |
| **Flush latency** (ingest→searchable-in-immutable-leg) | the honest NRT cost | n/a (new capability) |
| **Compaction cost** (localised rebuild wall-time + write-amp) | SEISMIC has no byte-merge | n/a |
| **Cross-host ID reproducibility** | the any-hardware guarantee | same doc on 2 different CPUs → identical ID |

Reuse the existing Kimi-judge NDCG harness **only** as a *non-regression guard*
(quality must not drop vs. the single-segment baseline) — Stage 1 is **not**
chasing a recall win.

## Go / No-Go gates for the spike itself

- **PASS** if, at the big-host cut depth, RSS stays within ~1.2× of the
  single-segment baseline *and* p95 latency within ~1.5×, with bounded fan-out —
  i.e. TieredMergePolicy + prefix-locality keep the small-segment cost in check.
- **KILL** if RSS or p95 blows past those with no policy setting recovering it →
  LSM-on-mmap is incompatible with the page-cache thesis; stop, document, do not
  proceed to Stage 2.

## Stage 2 (only if Stage 1 passes)

Swap the rule-based assigner for a **learned RQ / hierarchical-k-means tree** fit
on a SPLADE sample; re-measure locality (should *improve* fan-out and RSS) and
*now* chase a recall delta. Add tombstone deletes. Pin tree re-fit to the
monthly-rebuild boundary with `tree_vN` versioning.

## Explicitly out of scope (any stage)

- Generative *retrieval* at serving time (Meaning A) — see
  `00_CONCEPT_AND_CONTEXT.md` §1/§3.
- Replacing the W-id provenance key.
- Touching the lexical (tantivy) or dense (usearch) legs — this is sparse-leg
  only.
