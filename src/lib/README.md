# src/lib/ — module map

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
| `thinclient/abstracts.py` | abstract sidecar reader/writer (v1/v2/v3 formats, flat blocks, ordinal locator) |
| `thinclient/ordinals.py`, `thinclient/livedocs.py`, `thinclient/oa_overlay.py` | ordinal addressing, live-docs masks, open-access bitmap overlay |
| `thinclient/delta_layer.py` | serving reader for the delta-ingest layer (`SFU_DELTA_ROOT`, default OFF; ingest side in `spike/delta_ingest/`) |
| `reranker.py`, `speculative_rerank.py`, `speculation.py` | cross-encoder rerank, speculative rerank lever, draft/verify speculation |
| `result_cache.py`, `cache.py`, `serve_query_log.py` | read-through result cache, generic TTL cache, PII-safe serve log |
| `config.py`, `retry.py`, `logging_setup.py`, `validators.py`, `formatters.py` | configuration, circuit breaker/backoff, logging, input validation, text formatting |

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
| `opensearch_retriever.py` | the OpenSearch-era retriever; the parity oracle and gated comparison paths still import it (`docs/THIN_CLIENT_SWAP.md` §"Removed from this container" for what left) |
| `embedding.py`, `lambdamart_features.py`, `model_registry.py` | dense-embedding and learning-to-rank scaffolding from the model-training era (`models/model_registry.json`) |
| `analytics.py`, `engagement.py` | GUI analytics/engagement endpoints (`/analytics`, `/engagement`) |
| `hf_load_lock.py` | cross-process lock around Hugging Face model loads |

Tests for every module: `src/tests/test_<module>.py` and `scripts/tests/`.
