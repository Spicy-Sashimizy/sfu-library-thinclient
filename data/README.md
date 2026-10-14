# data/ — runtime artifacts and measurement evidence

**Status:** ACTIVE

Mostly NOT in git. Rules for agents are in `CLAUDE.md` here; this file is the
human map.

| Path | In git? | What |
|---|---|---|
| `eval_results/` | yes (1,525 tracked files at 2026-10-13, 136 of them under `archive/`) | every measurement the docs cite as evidence, plus campaign scratch. Conventions in `eval_results/README.md`; a generated browse table (file, date, size, citing docs) in `eval_results/INDEX.md` (`scripts/repo_tools/build_eval_results_index.py`) |
| `eval_results/archive/` | yes | unreferenced campaign scratch (logs, status files, probe JSONs) and the training-era eval outputs under `archive/training_era_results/` |
| `eval_results/serve_query_log.jsonl`, `eval_results/llm_judge_cache.json`, `eval_results/_q11_c4_distill_set.jsonl` | no | serve-time query log, LLM-judge cache and the KILLED (2026-07-28) distillation set — runtime/regenerable, gitignored |
| `sfu_eval_queries.json` | yes | the 120-topic LLM-judged query set (`docs/BENCHMARK_METHODOLOGY.md`) |
| `generation_checkpoints/`, `text_compression_sample.jsonl.gz` | yes | small fixtures |
| `seismic_150m/` | no | the served 8-shard SEISMIC index (66 GB+). **Irreplaceable, read-only** — `docs/infrastructure/INDEX_WRITE_PROTECTION.md` |
| `thinclient_index/` | no | meta.sqlite (24.9 GB), per-section tantivy + sidecars (`sections/`), packed cold sections (`packed/`), dense leg (`dense/`), `spool/`, `manifest.json`, `build_status.json` |
| `openalex_*_cache.json`, `watchdog_status.json`, `solr_cache.json`, `qdrant_spike/` | no | runtime caches and the dead Qdrant-spike outputs (gitignored; Qdrant leg deleted 2026-10-12) |
| `bmp_size_eval/` | no | empty local directory left by the BMP SPLADE leg (removed 2026-10-11); not gitignored, but git tracks no empty directory |
