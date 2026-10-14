"""> **CLOSED MEASURED 2026-09-30** — the pre-registered GO rule of `06_INPLACE_SPIKE_PLAN.md` read NO-GO: bar S0-1 measured a long-list dead-slot coverage of **0.019** (95 % CI 0.018–0.020) against 0.80. In one quarter 27 % of shard 0's docs are updated and 15 % more are new while deletions free 6 %, and a list cannot grow, so dead-slot reuse cannot absorb the churn (`inplace_s0_20260930.json`). Nothing in-place replaces it: updates stay with delta generations (`docs/delta_ingest/`). The v3 encoder/decoder is exact (B1 460/460, +1.3 % per query) and the +tail variant was built, but they remove the wrong obstacle. Full record: `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` results table and §"NO-GO 2026-09-30". Not current; do not resume.

In-place bit-updater spike (docs/delta_ingest/05_INPLACE_BIT_UPDATE_BRIEF_2026-09-29.md).

Stage 0 is Python-only and READ-ONLY over data/seismic_150m/: it decodes one
f16 twin shard's posting lists / block summaries and simulates the brief's
mechanisms B (bounded lists with dead-slot reuse + eviction) and C (monotone
block-bound loosening) in memory. Nothing here writes a shard file.

Modules:
  shard      -- read-only decoder for the c1a mmap layout (posting_lists.bin,
                forward, doc mapping, token map).
  search     -- a Python re-implementation of the MmapSeismicIndex traversal
                (first term sort_and_search, then natural block order,
                heap_factor skip, visited set), over an optionally modified
                list/summary state.
  churn      -- churn inputs: OpenAlex deleted_ids, snapshot partition ids,
                SPLADE vectors of touched works (from the M6 generation jsonl).
  mechanisms -- slot reuse / eviction / drop and summary loosening.
"""
