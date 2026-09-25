# Decision Trail

**Status:** DEFERRED 2026-09-25 (DESIGN ONLY / UNMEASURED since 2026-06-30; no code was ever written)

Dated log of how the recommendation in `03_GO_NO_GO.md` was reached.

## 2026-06-30 — origin & reasoning

**Prompted by** a hypothesis exploration: (1) does autoregressive search-engine
tech apply here, (2) does an MoE with a specified active-param set apply, then
(3) could a native auto-updater autoregressively create doc-IDs for incoming
data, under two hard constraints (any-hardware/elastic, immutable sparse leg).

**Reasoning steps (full detail in `00_CONCEPT_AND_CONTEXT.md`):**

1. Generative *retrieval* (DSI/NCI/SEAL) rejected as a replacement — fails on
   scale (>~few-M docs unproven), updates, exact-match/filters, GPU latency.
   Survives only as a bounded fusion leg / rerank. Not pursued.
2. MoE found to be **already realised structurally** by `sections.py` +
   personas (hand-routed experts, conditional activation). As a model it only
   fits a section-routed reranker, and it optimises compute — the wrong axis for
   a storage-bound system.
3. Auto-updater split into **Meaning A** (learn new docs into weights — unsolved,
   rejected) vs **Meaning B** (forward-only semantic ID assignment at ingest —
   buildable). User confirmed target = extension of Meaning B.
4. The two added constraints were found to **select for** the design:
   immutability → LSM with the ID as routing address; any-hardware/elastic →
   elastic prefix-depth sharding.

**The Lucene reality-check (key turning point):** the LSM / segment / flush /
merge / NRT / tombstone / mmap machinery is **Lucene, feature-for-feature** — and
this stack already *left* Lucene (the 150M OpenSearch baseline) for JVM/footprint
reasons. This shrank the defensible novelty to exactly two things Lucene does
**not** do: a **stable hierarchical semantic ID** (Lucene docids are ephemeral
per-segment ordinals) and **elastic prefix-depth resharding** (ES shard count is
fixed at creation). Conclusion: **borrow Lucene's design, don't reinvent it** —
catalogued in `04_LUCENE_BORROW.md`.

**The single decisive risk identified:** mmap is optimised for *few big*
immutable files; LSM produces *many small* ones. The semantic ID's locality is
the proposed mitigation (bounds fan-out + resident set), but it is **unproven**.
This became the kill-gate of the Stage-1 spike.

**Outcome:** GO for a **Stage-1, no-ML spike** that measures
RSS-vs-segment-count, fan-out, p95 latency, flush/compaction cost, and cross-host
ID reproducibility. NO-GO on Meaning A, on a learned tree before the mmap gate
passes, and on borrowing Lucene's docid/routing.

**Status of evidence:** all design-only / unmeasured. No code written. No
numbers exist yet.

## Added 2026-06-30 (same session)

- Per request, extracted the specific beneficial Lucene components into
  `04_LUCENE_BORROW.md` with class pointers, tunables, and SEISMIC adaptations
  (segment commit point, RAM-flush, TieredMergePolicy, liveDocs, NRT/madvise) —
  and the two explicit "do not borrow" items (docid ordinal, hash routing).
