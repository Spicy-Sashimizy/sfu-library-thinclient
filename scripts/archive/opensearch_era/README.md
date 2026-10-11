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
