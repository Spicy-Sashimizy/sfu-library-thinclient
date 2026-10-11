# 01 — Module triage: what can be Rust-cored now, what later, what stays Python

**Status:** ACTIVE (classification 2026-10-11; effort cells are `*est.*`, nothing measured)

Line counts are `wc -l` on 2026-10-11. "Crate" names the Rust dependency that
replaces the Python binding. Effort is a one-person-plus-Claude estimate and is
not a measurement. Tier A is in scope for `02_SPIKE_PLAN.md` Step 2; Tier B only
after Step 2 passes; Tier C is not ported.

## Tier A — Rust-core now (crate-native or trivial logic; low ranking risk)

| Module / function | LOC | What it does today | Rust replacement | Effort `*est.*` | Risk |
|---|---|---|---|---|---|
| `thinclient/sharded_seismic_backend.py` — `search_encoded`, `_search_one`, `_prepare_query`, `_merge_topk`, `_load_manifest`, `_load_one_shard` | ~400 of 1,561 | fan-out of an encoded query to 8 mmap shards, per-shard top-k, merge | already the fork crate; the fan-out becomes a Rust loop over `MmapSeismicIndex` (rayon) | small | none: same engine; thread-pool semantics must match `SFU_SEISMIC_FEDERATION_MODE` |
| `thinclient/retriever.py` — `_rrf_fuse` | 27 | RRF k=60 over per-leg lists | 20 lines of Rust | trivial | tie-order: Python sorts stable by (score desc, insertion); replicate exactly |
| `thinclient/retriever.py` — `_bm25f_leg`, `bm25f_query_text`, `_era_skip`, `_normalize_filters` | ~120 | tantivy BM25F over 8 sections, title^3 + abstract, fast-field filters | `tantivy` crate 0.26 (same index format as tantivy-py 0.26; pin both) | small-medium | query-parser escaping in `bm25f_query_text` must be ported character for character |
| `opensearch_retriever.py` — `_get_splade_model`, `encode_splade`, `_resolve_tokenizer_dir` | ~80 | SPLADE query encode, ORT CPU session over `models/splade_onnx_fused/model.onnx`, bert-base tokenizer | `ort` + `tokenizers` crates | small | the tokenizer must ship inside the SPLADE dir (measured trap 2026-09-27); fp32 ORT on both sides ⇒ identical logits expected, verify |
| `thinclient/retriever.py` — `_meta_rows`, `_post_filter_sqlite`, `_connect_meta` | ~90 | `meta.sqlite` lookups (year/type/is_oa/doi) + post-filter | `rusqlite` (bundled SQLite) | small | staged-copy identity check (`_meta_stage_identity`) is ops; keep in Python shell |
| `thinclient/livedocs.py` | 122 | tombstone bitset over base ordinals | DONE on fork branch `livedocs-skip` (O10, parity 220/220, cost unmeasured) | done | semantics differ from the Python filter (k′ live per shard) — O10 findings |
| `thinclient/abstracts.py` — `AbstractLocator.lookup`, `_encode_wid` | ~130 | flat sidecar + ordinal locator (N5) lookups | `memmap2` + `zerocopy` slices | small | identity check `AbstractLocatorMismatch` must stay |
| `federated_search.py` — `_rrf_merge` | ~40 | RRF across local + remote sources | same RRF as above | trivial | remote sources stay Python (Tier C); the merge is shared logic |

## Tier B — after Tier A proves out (moderate effort, or ranking/semantics risk)

| Module / function | LOC | Why not now | Rust path | Effort `*est.*` |
|---|---|---|---|---|
| `embedding.py` + `reranker._compute_semantic_scores` (embed-rerank, `sfu-academic-embed-v5`) | ~250 | torch + sentence-transformers today; needs the ONNX export first (Step 1) and its own parity bar | `ort` session + mean-pooling in Rust | medium |
| `reranker.rerank_with_crossencoder` (torch CE v1) | ~100 | int8 ONNX CE was NOT parity-preserving (overlap@10 0.968, 108/120 orders changed); fp32 ONNX unmeasured | `ort` fp32 session; bar = byte-identical top-10 | medium |
| `reranker.rerank_results` stage-1 heuristics (title/recency/type/completeness, RRF of semantic scores) | ~200 | pure logic but entangled with Python dict shapes | port after the candidate struct exists | medium |
| `thinclient/abstracts.py` — `AbstractStore` v3 zstd-dict blocks, script buckets | ~300 | per-bucket dictionaries, sqlite + sidecar dual source | `zstd` crate with dictionaries | medium |
| `thinclient/retriever.py` — `_hydrate`, `_hydrate_lookup`, `fetch_abstracts` (local part) | ~120 | depends on the two rows above; remote fallback stays Python | after abstracts | small once A lands |
| `thinclient/delta_layer.py` READ side (generations, masks, routed abstracts) | ~250 of 486 | gate default OFF (`SFU_DELTA_ROOT`), M4 FAIL open; porting a gated-off path first is wasted motion | after a promotion decision | medium |
| `sharded_seismic_backend.py` residency ops — mlock floor, hotset pin, prefault, `_ShardFaultTracker` | ~700 | operator/ops tuning with Linux-only syscalls; the CLI handout does not need them | keep as Python shell calls, or `libc` crate behind `#[cfg(unix)]` | medium |
| `result_cache.py`, `serve_query_log.py` | 308 + 330 | server concerns; a CLI needs neither | later, if the CLI grows a daemon mode | small |
| `thinclient/ordinals.py` (opt-in addressing) | 216 | opt-in; `meta.sqlite` is the default filter stage | with the meta row | small |

## Tier C — stays Python / not ported

| Module | LOC | Why |
|---|---|---|
| `tools.py` (MCP tool surface, Zotero/OpenAlex/S2 orchestration, citations, jobs) | 2,322 | integration surface; its value is the Python ecosystem it calls |
| `sfu_library_mcp_http.py`, `sfu_library_mcp_server.py` (starlette/uvicorn, SSE draft stream, MCP, cache preseed) | 662 + 44 | the server shell; calls the core through pyo3 |
| `openalex.py`, `semantic_scholar.py`, `zotero.py`, `citations.py`, `access_resolver.py`, `sfu_databases.py`, `formatters.py`, `validators.py`, `retry.py`, `federated_search.FederatedSearchRouter` | ~3,900 | remote clients, breakers, formatting; no portability or latency case |
| `speculation.py`, `speculative_rerank.py` | 1,035 | gated levers measured below their bars (`SPECULATIVE_RETRIEVAL_UPGRADES.md`); not on the default path |
| `thinclient/dense_cache.py`, `dense_delta_merge.py`, the usearch dense leg | 624 | **not ported, dropped from handouts**: default OFF since 2026-08-18, ablation DROP, 0.4 % coverage (`DENSE_PARTITION_AND_ABLATION.md`) |
| `thinclient/builder.py`, `packer.py`, `sections.py`, `doc_encoder.py`, `oa_overlay.py`; `spike/delta_ingest/` write side | ~1,100 + spike | build tier (GPU encode, cuDF snapshot ingest); the handout is serve-only |
| `thinclient/seismic_backend.py` (single-index testbed adapter), Qdrant/OpenSearch rollback backends | 92 + 450 | rollback ladders selected by env; stay as they are |
| `analytics.py`, `engagement.py`, `cache.py`, `config.py`, `logging_setup.py`, `model_registry.py`, `hf_load_lock.py`, `lambdamart_features.py` | ~900 | server plumbing |

## What the numbers say about the split

- Tier A is ≈ 1,000 lines of Python whose Rust equivalents are mostly crate
  calls; it is the whole of "encoded query → fused, filtered, hydrated ids".
- Tier B is ≈ 2,500 lines and carries the only ranking risk (the two rerank
  models); Step 1 of the plan removes torch there before any Rust is written.
- Tier C is ≈ 11,000 lines that a compiled handout does not need.
