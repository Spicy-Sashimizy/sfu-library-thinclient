# data/ — runtime artifacts and measurement evidence

**Status:** ACTIVE

Mostly NOT in git. Rules for agents are in `CLAUDE.md` here; this file is the
human map.

| Path | In git? | What |
|---|---|---|
| `eval_results/` | yes (≈1,500 files) | every measurement the docs cite as evidence, plus campaign scratch. Conventions in `eval_results/README.md`; a generated browse table (file, date, size, citing docs) in `eval_results/INDEX.md` (`scripts/repo_tools/build_eval_results_index.py`) |
| `eval_results/archive/` | yes | unreferenced campaign scratch and the training-era `results/` outputs |
| `sfu_eval_queries.json` | yes | the 120-topic LLM-judged query set (`docs/BENCHMARK_METHODOLOGY.md`) |
| `generation_checkpoints/`, `text_compression_sample.jsonl.gz` | yes | small fixtures |
| `seismic_150m/` | no | the served 8-shard SEISMIC index (66 GB+). **Irreplaceable, read-only** — `docs/infrastructure/INDEX_WRITE_PROTECTION.md` |
| `thinclient_index/` | no | meta.sqlite (24.9 GB), per-section tantivy + sidecars, packed cold sections, dense leg |
| `*_cache.json`, `watchdog_status.json`, `solr_cache.json`, `qdrant_spike/`, `bmp_size_eval/` | no | runtime caches and dead-spike outputs (gitignored) |
