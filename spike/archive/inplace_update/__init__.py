"""In-place bit-updater spike (docs/delta_ingest/05_INPLACE_BIT_UPDATE_BRIEF_2026-09-29.md).

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
