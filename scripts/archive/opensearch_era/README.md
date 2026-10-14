# opensearch_era/ — OpenSearch-era evaluation scripts (superseded)

> **CLOSED SUPERSEDED 2026-06-11** — these four scripts drove OpenSearch 3.7 or the
> OpenSearch-era SPLADE indexer; OpenSearch was removed from this container on
> 2026-06-11 (`docs/THIN_CLIENT_SWAP.md`). Moved here from `scripts/experiments/` on
> 2026-10-11 by the script triage (`docs/infrastructure/SCRIPT_TRIAGE_2026-10-11.md`).
> Their tracked results stay under `data/eval_results/` and are the only record of
> those runs; no live doc cites them.

| Script | Results |
|---|---|
| `benchmark_topic_export.py` | `benchmark_topic_export_{local_only,with_live}.json` |
| `eval_splade_finetune_subset.py` | `splade_finetune_subset.json` (the fine-tune itself: PREP-ONLY, never run — `docs/deprecated/SPLADE_OPTIMIZATION_ROADMAP.md`) |
| `prune_topk_experiment.py` | `prune_topk_experiment.json` |
| `benchmark_splade_optimizations.py` | none tracked (encoder-throughput benchmark; the encoder book is CLOSED, `docs/seismic_150m_testbed/14_ENCODER_UPGRADE_PATH.md`) |

Added 2026-10-11 (codebase triage group 4):

| File | What it is |
|---|---|
| `opensearch_retriever.py` | the `OpenSearchRetriever` class (BM25/SPLADE rank_feature/k-NN over the decommissioned index), moved out of `source/lib/opensearch_retriever.py`; imports the live encoders from `lib.opensearch_retriever`. The `scripts/experiments/eval_{dense_compression,dense_poc,lexical_lossless,pipeline,sectioned_index}.py` harnesses load it by path |
| `test_opensearch_retriever.py` | the class's unit tests (20+1), split from `source/tests/test_opensearch_retriever.py` (whose live-encoder tests are now `source/tests/test_query_encoders.py`); run with `cd src && ../.venv/bin/python3 -m pytest ../scripts/archive/opensearch_era/test_opensearch_retriever.py` |
