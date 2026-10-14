# source/lib/ — module map

**Status:** ACTIVE

Which files are the serving stack, which are clients of external services,
and which are kept from earlier eras. Names are historical: the project began
as an OpenSearch-backed MCP server, became a "thin client" over local engines
(tantivy + BMP + usearch, 2026-05/06), and then swapped the SPLADE leg to
SEISMIC (2026-07-06). File names were never renamed across those swaps —
`thinclient/retriever.py` is the current retriever, `opensearch_retriever.py`
is the old one. Authoritative description: `docs/THIN_CLIENT_SWAP.md`.

## Serving stack (hot path of every query)

| Module | Role |
|---|---|
| `tools.py` | MCP tool handlers, string-dispatched by tool name (`handle_tool_call`); builds the fused result list |
| `thinclient/retriever.py` | `ThinClientRetriever`: BM25F (tantivy) + SPLADE (SEISMIC) [+ optional dense] legs, RRF fusion k=60, filter stage, delta layer hooks |
| `thinclient/sharded_seismic_backend.py` | the served SPLADE engine: 8 immutable mmap SEISMIC shards queried in parallel, health/fault bookkeeping |
| `thinclient/seismic_backend.py` | single-shard SEISMIC wrapper |
| `thinclient/sections.py` | subject/era section classifier and personas |
| `thinclient/abstracts.py` | abstract sidecar reader/writer (v3 format, flat blocks, ordinal locator; pre-v3 stores refused since 2026-10-11) |
| `thinclient/ordinals.py`, `thinclient/livedocs.py`, `thinclient/oa_overlay.py` | ordinal addressing, live-docs masks, open-access bitmap overlay |
| `thinclient/delta_layer.py` | serving reader for the delta-ingest layer (`SFU_DELTA_ROOT`, default OFF; ingest side in `spike/delta_ingest/`) |
| `reranker.py`, `speculative_rerank.py`, `speculation.py` | cross-encoder rerank, speculative rerank lever, draft/verify speculation |
| `result_cache.py`, `cache.py`, `serve_query_log.py` | read-through result cache, generic TTL cache, PII-safe serve log |
| `config.py`, `retry.py`, `logging_setup.py`, `validators.py`, `formatters.py` | configuration, circuit breaker, logging, query sanitization, text formatting |

## Index build side (not on the query path)

| Module | Role |
|---|---|
| `thinclient/builder.py` | per-section tantivy builds + sidecars with slice checkpoints (driven by `scripts/build_thinclient_index.py`) |
| `thinclient/packer.py` | hot/cold tar+zstd packing of built artifacts |
| `thinclient/doc_encoder.py` | GPU batch SPLADE document encoder for rebuilds |
| `thinclient/dense_cache.py`, `thinclient/dense_delta_merge.py` | the dense leg's query-driven warm cache and its delta merge (dense leg default OFF since the 2026-08-18 ablation) |

## External-service clients

`openalex.py`, `semantic_scholar.py`, `zotero.py`, `citations.py`,
`access_resolver.py`, `sfu_databases.py`, `federated_search.py` — rules for
each (rate limits, breaker semantics) are in `docs/EXTERNAL_API_CONTRACT.md`.

## Kept from earlier eras (importable, not the served path)

| Module | Why it is still here |
|---|---|
| `opensearch_retriever.py` | name is historical: now only the SPLADE/dense query encoders (`encode_splade`, `encode_dense`) the served SEISMIC leg imports; the `OpenSearchRetriever` class was archived 2026-10-11 to `scripts/archive/opensearch_era/opensearch_retriever.py` |
| `embedding.py`, `model_registry.py` | sentence-transformer embedding + cosine similarity for the reranker's embedding stage (imported by `reranker.py`), and the model-versions reader (`models/model_registry.json`, read by `analytics.py`); the LambdaMART feature module and tier were removed 2026-10-11 |
| `analytics.py`, `engagement.py` | GUI analytics/engagement endpoints (`/analytics`, `/engagement` in `sfu_library_mcp_http.py`, wired 2026-10-12) |
| `hf_load_lock.py` | cross-process lock around Hugging Face model loads (used by `embedding.py`, `reranker.py`, `opensearch_retriever.py`) |

Tests: `source/tests/test_<module>.py` where one exists, plus `scripts/tests/` (which holds the `thinclient/` and `serve_query_log.py` suites). As of 2026-10-13 `citations.py`, `formatters.py` and `hf_load_lock.py` have no test of their own.
