# SFU_* / DEMO_* env-gate reference (consolidated 2026-09-01)

**Status:** ACTIVE

Every serving/build gate, its default, and its parsing quirk, in one
grep-able place. The code is authoritative; this table is the index.
Coverage in both directions is enforced by `scripts/tests/test_env_gates_doc.py` (2026-10-12).
Every name is written in full (no `_SUFFIX` shorthand); a struck-through name
(`~~...~~`) is retired and lives only in "Retired gates" at the end.
Details and provenance: `CODE_INVARIANTS.md`, `CODE_INVARIANTS_SCRIPTS.md`,
`THIN_CLIENT_SWAP.md`, `archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md`
(CLOSED KILLED 2026-10-12; history of the `SFU_SPLADE_BACKEND` promotion).

## Parsing quirks (read first)

- **Literal-`1`-only gates**: `SFU_DENSE_LEG`, `SFU_ABSTRACTS_PREFAULT`,
  `SFU_CE_ONNX`, `SFU_DENSE_ENCODER_ONNX`,
  `SFU_SEARCH_SPECULATIVE_RERANK` — ONLY the literal string `1`
  enables; any other value (including typos) leaves the default OFF.
- **Tri-state**: `SFU_SEISMIC_MLOCK_FLOOR` — `1` = rescoped navigation
  floor (~20 MB/shard, 2026-08-17); `full` = the 2026-07-14 whole-slab pin
  (~13.4 GB, measurement reproduction only). `SFU_SEISMIC_PREFLOOR_AT_LOAD` (name corrected 2026-10-11) — `1`
  = Fix #4 footing; `2` = also forward_offsets.bin.
- **Inverted staging defaults**: `SFU_SERVE_QUERY_LOG`, `SFU_RESULT_CACHE`,
  `SFU_CACHE_PRESEED` — unset ⇒ ON in staging; an explicit `production`
  profile is the only thing that defaults them OFF (production must opt in).
- **Set-always-wins**: `SFU_SEISMIC_SHARD_MANIFEST` — a set value always
  overrides the promotion ladder (the one-env rollback); a set-but-missing
  path fails loudly.

## Serving backends & index

| Gate | Default | Meaning |
|---|---|---|
| `SFU_SEARCH_BACKEND` | `thinclient` | `thinclient` only; any other value raises (OpenSearch decommissioned 2026-06-11, code archived 2026-10-11) |
| `SFU_SPLADE_BACKEND` | `seismic` (since 2026-07-06) | `seismic` is the only supported value. Any other value raises `ValueError` on the first SPLADE query, including the retired `bmp` (code path removed 2026-10-11) and `qdrant` (the one-env rollback leg, removed 2026-10-12 by owner decision); both live on branch `archive/bmp-qdrant` |
| `SFU_SEISMIC_SHARD_MANIFEST` | unset ⇒ promotion ladder (E8 dv-v2 → E5 dv-v1 → plain dv) | one-env rollback to any prior served shard set |
| `SFU_SEISMIC_FEDERATION` | unset ⇒ FS-aware (sequential on 9p/NFS, parallel on local disk) | `parallel` / `sequential`; environment always overrides the heuristic |
| `SFU_SEISMIC_K_PRIME` | unset ⇒ max(2×top_k, 100) | do NOT set in parity runs — the default is the served behavior |
| `SFU_SEISMIC_QUERY_CUT` | unset = all terms (recall-first) | §C1 lever: 10 ⇒ 4× traverse at overlap 0.995 |
| `SFU_THINCLIENT_ORDINALS` | unset (OFF) | ordinal filter arrays directory; FAILS CLOSED if configured and unusable. **Also read by the delta-ingest `publish()`** (`spike/delta_ingest/generation.py`, since 2026-09-29, item C) when no `ordinal_dir` argument is passed: a relative value resolves against the base index root; when set, deletes and superseded base copies go into the livedocs bitset `<delta_root>/livedocs/base-<stamp>.liv` and `mask.deleted` keeps only ids without a base ordinal; unset → JSON mask lists exactly as before. No CLI flag exists for it yet. Keep the arrays on local disk (9p lookups ~0.7 s per 100 ids, `docs/delta_ingest/02_DESIGN.md` §4 item 3) |
| `SFU_OA_BITMAP` | unset (OFF, 2026-10-01) | O17 option (a): base-side `is_oa` override. Non-blank value = a bitmap directory built by `spike/delta_ingest/oa_bitmap.py` (relative values resolve against the index root); blank/unset = no-op (gate-off code path unchanged). FAILS CLOSED (raises at `_load`) when the directory, its ordinal directory, the `ordinal_space_id` pair, the served `meta.sqlite` size+mtime, or the bit-array lengths do not match. When ON: `open_access_only` keeps base docs the bitmap marks known-OA (BM25F base sections drop the tantivy `is_oa` clause, over-fetch `OVERFETCH_FILTERED`x and post-filter; SPLADE/dense post-filter and hydration read the override through `_meta_rows`; the ordinal post-filter is bypassed for `is_oa` queries); hydrated `is_oa` is True/False/None (None = unknown); delta copies win; the result-cache key gains `@oa=<bitmap_id>`. Also read by `spike/delta_ingest/seed.py` `BaseSeeder` when no `oa_overlay` is passed. Keep the bitmap and its ordinal `wids.npy` on local disk. Invariants: `CODE_INVARIANTS.md` §oa_overlay. Tests: `scripts/tests/test_oa_bitmap.py` |
| `SFU_THINCLIENT_INDEX_ROOT` | `data/thinclient_index` | empty value silently targets the REAL serving root — beware in staging; also read by lib/analytics.py index_shape (manifest.json, read-only, 2026-10-12) |
| `SFU_DELTA_ROOT` | unset (OFF, 2026-09-29) | delta-ingest layer (`docs/delta_ingest/`): literal `1` = `<index_root>/delta`, any other value = that path; a missing directory logs a warning and stays OFF. When ON and `SFU_SEISMIC_SHARD_MANIFEST` is unset, the composed manifest that `delta/generations.json` names is served (`delta/shard_manifests/shard_manifest-<stamp>.json` since 2026-10-08, a new file per publish; roots published earlier name `delta/shard_manifest.json` until their next publish) (a set environment manifest still wins — delta SEISMIC shards then NOT served, warning logged). Put the delta root on local disk (delta meta/shards are not covered by the staging levers). Resolution is shared by serving and writers (`delta_layer.resolve_delta_root`, O16 2026-10-01): explicit `--delta-root` > this variable > `<index_root>/delta`; writers using it refuse `data/seismic_150m` and an implicit default under the repository `data/` tree (serving resolution unchanged) |
| `SFU_DELTA_ABS_ROUTE` | unset (OFF, 2026-10-01) | 09 lever L3: literal `1` = `fetch_abstracts` skips the delta-generation abstract stores in its store loop and probes, for the ids the base stores did not answer, only the owning `(generation, section)` store from `DeltaLayer.abstract_owner` (meta rows of the loaded generations, newest copy per `superseded`); unowned ids probe no delta store. Inert without `SFU_DELTA_ROOT`. Read once per retriever at `_load`. Differs from OFF only for an id held by more than one generation (ON returns the newest copy's abstract, OFF the oldest generation's). Tests: `scripts/tests/test_delta_abs_route.py`. Latency efficacy UNMEASURED until 09 runs P/R1/R2 |
| `SFU_DELTA_FOLDIN_FRAC`, `SFU_DELTA_FOLDIN_DEAD_FRAC`, `SFU_DELTA_FOLDIN_MAX_AGE` | unset (OFF, 2026-10-08) | doc 10 §1 fold-in trigger thresholds (a) live-routed fraction, (d) masked fraction, (c) age in days, read by the delta-ingest WRITER at every `publish()` (`spike/delta_ingest/trigger.py`), never by serving. Unset or empty = that threshold never fires; the per-shard (a)/(d)/(c) record is written to `<delta_root>/trigger.json` + `trigger_log.jsonl` regardless. A firing threshold only marks the shard in the record (`fire`); nothing builds or publishes a fold. 24 h hysteresis after a fold publish of the shard. The (b) tax-ms dial is NOT implemented and ignored (needs F0; listed under Retired gates). No profile default until doc 10 F7. Exactness: F1 PASS 2026-10-08 (`spike/delta_ingest/FOLDIN_FINDINGS.md`) |
| `SFU_SEISMIC_DELTA_GROUP` | unset (OFF, 2026-10-01) | 09 lever L5: literal `1` = `ParallelSeismicBackend` searches every delta-generation shard (manifest `shards` records with a non-null `delta_generation`) serially inside ONE pool task; base shards keep one task each; per-shard result lists and `_merge_topk` unchanged. Read once per backend at `from_manifest`; inert for the sequential/hybrid classes, for manifests without delta records, and when the record count differs from the loaded shard count. Under `SFU_SEISMIC_SHARD_FAULT_BOUNDARY=1` each grouped shard is still guarded individually. Tests: `scripts/tests/test_seismic_delta_group.py`. Latency efficacy UNMEASURED until 09 runs P/R1/R2 |
| `SFU_BM25F_PARSE_ONCE` | unset (OFF, 2026-10-01) | 09 lever L4 (`docs/delta_ingest/09_M4_FOLLOWUP_PREREGISTRATION.md`): literal `1` = `_bm25f_leg` parses `bm25f_query_text` once per distinct tantivy schema per query (2 `parse_query` calls per schema) and reuses the two `Query` objects across sections, instead of 2 calls per section. Read once per retriever at `_load`. Premise (a `Query` parsed by one `Index` is valid on another with an equal schema) pinned by `scripts/tests/test_bm25f_parse_once.py`. Latency efficacy UNMEASURED until 09 runs P/R1/R2 (`spike/delta_ingest/M4F_FINDINGS.md`) |
| `SFU_DENSE_LEG` | **OFF since 2026-08-18** (ablation: harmful at 0.4% coverage) | literal `1` enables the whole leg (seed + warm cache) |
| `SFU_DENSE_WARMCACHE` | on when leg on | `0` disables the cache only; inert while the leg is off |
| `SFU_DENSE_DELTA_USEARCH_MIN` | unset/`0` ⇒ RAM Hamming brute force (v1 behaviour, byte-identical) | row count above which the warm-cache delta is also kept in a mutable usearch b1 index and queried through it (4× over-fetch, then the same exact int8 rescore). A non-integer value logs and stays at brute force; any usearch error disables the lever for the process and brute force continues. Measured 2026-09-25: `DENSE_WARMCACHE_RESEARCH.md` §"Deferred to v2" |

## Staging / residency levers (dev-container; production no-ops)

| Gate | Default | Meaning |
|---|---|---|
| `SFU_SEISMIC_STAGE_DIR` | unset | copy shards off 9p/NFS to local disk (~160–240× fault speedup); no-op on a droplet |
| `SFU_META_STAGE_DIR` | unset | stage meta.sqlite into this directory (55× filter-stage win on 9p); no-op on a local-FS source unless `SFU_META_STAGE_FORCE=1` (`thinclient/retriever.py` `_stage_meta_local`) |
| `SFU_STAGE_META` | unset | literal `1` with `SFU_META_STAGE_DIR` unset = stage meta.sqlite into `SFU_SEISMIC_STAGE_DIR` (one directory for both artifacts) |
| `SFU_META_STAGE_FORCE` | off | literal `1` = stage even when the source is already on a local FS (tests) |
| `SFU_META_STAGE_VERIFY` | `fingerprint` | `size` \| `fingerprint` (size + head/tail 64 KiB sha256) \| `sha256` |
| `SFU_ABSTRACTS_PREFAULT` | OFF (J1: costs load time; 0.919× cold-start regression otherwise absorbed) | literal `1` prefaults the 421 MB flat locator |

## Disk-streaming pin tier (all default OFF = byte-identical; kill-switch discipline)

| Gate | Meaning |
|---|---|
| `SFU_SEISMIC_MLOCK_FLOOR` | `1` navigation floor / `full` whole-slab reproduction |
| `SFU_SEISMIC_MLOCK_FLOOR_MB` | floor budget, default 160 MB total |
| `SFU_SEISMIC_PIN_BUDGET_GB` | F3 hot-set pin budget (aliases: 1.6→hot50, 4.2→hot80) |
| `SFU_SEISMIC_PREFLOOR_HOTSET` | F6 prefault-at-load (reclaimable, not locked); budget = PIN_BUDGET_GB or 1.6 GB |
| `SFU_SEISMIC_PREFLOOR_AT_LOAD` (row corrected 2026-10-11: no `source/` code reads a bare `SFU_SEISMIC_PREFLOOR`; that name is a harness-side knob, see "Ingest / eval") | 1 = Fix #4 floor; 2 = + forward_offsets.bin |

## Serve app (HTTP)

| Gate | Default | Meaning |
|---|---|---|
| `SFU_HTTP_WARMUP` | on | `0` disables the startup warmup battery (then `warm` reports true immediately) |
| `SFU_RESULT_CACHE` | staging-on | WI-17 read-through cache; `0` = the one-env rollback |
| `SFU_RESULT_CACHE_TTL` | `21600` (6 h) | entry TTL in seconds (`lib/result_cache.py`, read once at import) |
| `SFU_RESULT_CACHE_MAX_SIZE` | `256` | max cached responses |
| `SFU_RESULT_CACHE_MAX_MEM_MB` | `64` | cache memory cap in MB |
| `SFU_CACHE_PRESEED` | on (no-op when cache off) | WI-17b post-warmup primer (`source/sfu_library_mcp_http.py`, `scripts/prime_result_cache.py`) |
| `SFU_SEARCH_SPECULATE` | **OFF** (owner flips defaults, not builds) | WI-18 keystroke speculation (`lib/speculation.py`); truthy `1`/`true`/`on`/`yes` enables |
| `SFU_SPECULATE_MIN_RATIO` | `0.35` | the predicted query must be ≥ (1 + ratio) × the typed length to count as unambiguous; negative or unparsable ⇒ 0.35 |
| `SFU_SPECULATE_LITERAL` | OFF | truthy = speculate on the literal typed text when no unambiguous prediction matches |
| `SFU_SPECULATE_MIN_LEN` | `8` | minimum normalized chars before speculating (floor 1; unparsable ⇒ 8) |
| `SFU_SEARCH_DRAFT_STREAM` | **OFF** (IMPLEMENTED 2026-09-25; stays OFF: measurement (a) overlap@10 = 0.433 < ~0.7 bar, 2026-09-25, DEFERRED) | lever #2 of `SPECULATIVE_RETRIEVAL_UPGRADES.md`: truthy (`1`/`true`/`yes`/`on`) enables `POST /api/search_stream` (SSE BM25F draft → final) and advertises `search_draft_stream: true` on `/health`, which switches the GUI's first-page search to the stream. Forced off (404, `false`) while `SFU_SEQUENTIAL_MODE` is on. Off ⇒ route 404s, GUI uses `/api/search` unchanged |
| `SFU_SEARCH_SPECULATIVE_RERANK` | **OFF** (IMPLEMENTED 2026-09-25, PARITY MEASURED 360/360; multi-pass A/B 2026-09-25: −80 ms/miss attributable < 128 ms bar, total p50 not reduced, stays OFF) | lever #1 of `SPECULATIVE_RETRIEVAL_UPGRADES.md`: literal `1` starts a background draft of the rerank pipeline on the BM25F leg's pool while the SPLADE leg runs (`lib/speculative_rerank.py`); the real `_maybe_rerank` reuses the drafted stage-1/CE score of every candidate that is also in the fused pool and scores only the rest; byte-identical to OFF because both paths use fixed-shape scoring (`CODE_INVARIANTS.md` §reranker "Fixed-shape scoring", 2026-09-25). Off/absent ⇒ no thread, no context, pipeline unchanged. Counters: `speculative_rerank.counters()` (module dict, not yet on `/health`) |
| `SFU_METRICS_LOG_PATH` | unset (off) | per-tool-call JSONL metrics log (both transports), for example, `logs/mcp_metrics.jsonl`. Line: `{ts, tool, latency_ms, success, server_version, session, ids}` — `session`/`ids` added 2026-09-25 (`THIN_CLIENT_SWAP.md` §Serving swap; `CODE_INVARIANTS.md` §tools.py "Metrics log ids/session"). Write failures swallowed |
| `SFU_SERVE_QUERY_LOG` | staging-on | WI-2 query log (`lib/serve_query_log.py`); explicit `0`/`1` wins over the staging default |
| `SFU_SERVE_QUERY_LOG_STAGING` | unset | `1`/`true` forces the log ON when `SFU_SERVE_QUERY_LOG` is unset, whatever the profile |
| `SFU_SERVE_QUERY_LOG_PATH` | `data/eval_results/serve_query_log.jsonl` | JSONL path; relative values resolve against the repository root |
| `SFU_SERVE_QUERY_LOG_MAX_BYTES` | `67108864` (64 MiB) | per-file cap; overflow rotates to `.1` |
| `SFU_SERVE_QUERY_LOG_BUFFER` | `8192` | queue depth before lines are dropped (counted), never blocking a query |
| `SFU_SERVE_QUERY_LOG_RAW` | `0` (hash-only) | `1`/`true` also stores the normalized, truncated query text; `lib/speculation.py` reads it to know whether historical queries can exist |
| `SFU_SERVE_QUERY_LOG_SESSION` | random id per process | session id stamped on every line |
| `SFU_QUERY_LOG_PATH` | `""` (no log) | MCP-tool JSONL query log path (`lib/tools.py` `_log_query`); written only when `SFU_FEATURE_QUERY_LOG_ENABLED` is on AND this is non-empty |
| `SFU_ENGAGEMENT_LOG_PATH` | `logs/engagement_log.jsonl` (repository root) | append-only engagement log (`lib/engagement.py`), two writers: the search GUI posts its own query/impression/result_click/action rows to `POST /engagement` (always, one session id per tab, never in mock mode; 2026-10-12), and the MCP text path writes impression rows under session `"server"` only when `SFU_FEATURE_ENGAGEMENT_LOG_ENABLED` is on. `lib/analytics.py` `position_bias` / `session_replay` drop the `"server"` rows whenever any GUI impression exists (panel `"source"`: `gui` / `server` / `none`) |
| `SFU_SEQUENTIAL_MODE` | absent | set by the Windows START.bat; advertises on /health so the GUI queues searches |
| `OPENALEX_MAILTO` | unset | already the polite-pool mailto for OpenAlex/Crossref calls (`config.openalex_mailto`); since 2026-10-10 it is ALSO the only source of the contact in the outbound `User-Agent` (`lib/openalex.py` `_USER_AGENT`): set ⇒ `SFULibraryMCP/1.0 (mailto:<value>)`, unset ⇒ `SFULibraryMCP/1.0` with no contact. The product token is still an open rebrand decision (`infrastructure/REBRAND_DUCK_LIBRARY_2026-10-10.md`) |

## Models

| Gate | Default | Meaning |
|---|---|---|
| `SFU_SPLADE_MODEL_PATH` | bert-FUSED local export (D2, 2026-07-09) | bare HF hub ids don't work air-gapped |
| `SFU_EMBEDDING_MODEL_PATH` | repo-relative v5 | dense/rerank embedding checkpoint |
| `SFU_CE_MODEL_PATH` | v1 (base-flip DECISION PENDING; base measured +0.0165 better 2026-08-19) | torch CE checkpoint |
| `SFU_CE_ONNX` | OFF | literal `1`: int8 ONNX CE — slower at serve shape with CUDA (52 versus 11.8 ms batch-20); single-stream fallback only. On a CPU-only host (CUDA absent, 2026-09-27) it is faster than the torch CE (CE stage p50 219 versus 337 ms) but NOT ranking-equivalent: top-10 order changes on 108/120 topics versus torch v1 (`cpu_only_serve_path_2026-09-27.json`; `THIN_CLIENT_SWAP.md` §Rerank) |
| `SFU_ORT_INTRA_THREADS` | small | keep tiny/non-spinning with the TRT EP (full-width pool starved the GPU 3.5k→960 docs/s) |
| `SFU_SEISMIC_M2_INT6` | OFF | M2 integer-dot kernel (NOT promoted — gate a failed at n=100). Read by the Rust fork, not by Python: `spike/vectorium_fork/src/encoders/dotvbyte_fixedu8.rs` `int6_query_enabled` (`1`/`true`, per evaluator construction) |
| `SFU_DENSE_ENCODER_ONNX` | OFF | literal `1`: int8 ONNX v5 bi-encoder for the dense warm cache's background doc encoding. **Fails OPEN** — an enabled gate with an unusable export logs an ERROR and falls back to torch (same embeddings, slower). Inert while `SFU_DENSE_LEG` is off |
| `SFU_DENSE_ENCODER_ONNX_PATH` | `models/sfu-academic-embed-v5-onnx-int8` | export directory (`model_quantized.onnx`, else `model.onnx`); built by `scripts/experiments/export_dense_encoder_onnx_int8.py` |
| `SFU_DENSE_ENCODER_ONNX_THREADS` | `0` ⇒ onnxruntime default | intra-op threads for that session (inter-op pinned to 1 when set) |

## Demo broker (DEMO_*) — LIVE again since 2026-10-06 (dormant 2026-09-25 → 2026-10-06)

> **STATUS 2026-09-25: CLOUD ACCESS ENDED.** No OCI/DO host exists; every gate
> in this section is inert. "Live since" dates below are historical.
>
> **UPDATE 2026-10-06:** the broker box turned out to be alive and its gates are live again on it
> (tenancy on Pay As You Go and the serve instance rebuilt 2026-10-06 19:45 UTC). Values set
> on the live broker 2026-10-06: `DEMO_BUSINESS_DAYS=` (empty ⇒ no hot window, wake only on an invite
> click), `DEMO_IDLE_MINUTES=60`, `DEMO_MAX_SESSION_MINUTES=60`, `DEMO_PIN_RUNNING=0`, `DEMO_MAX_RUNTIME_HOURS_PER_DAY=10`,
> `DEMO_MAX_RUNTIME_HOURS_PER_MONTH=55`. See `infrastructure/DEMO_PAYG_PLAN.md` (dated note).

| Gate | Default | Meaning |
|---|---|---|
| `DEMO_BROKER_LIVE` | `0` | **the dry-run/spend gate** |
| `DEMO_CLOUD` | `do` | `oci` = the live OCI deploy |
| `OCI_STOP_ACTION` | SOFTSTOP | ACPI shutdown; `STOP` = hard power-off fallback |
| `DEMO_WATCHDOG_HEARTBEAT_HOUR` / `_FAIL_THRESHOLD` / `_STATE_PATH` | `9` / `2` / `watchdog.json` | `watchdog.py` (systemd timer, read-only): ntfy on instance-state change, health failures, recovery, daily heartbeat. Live 2026-09-07 → 2026-09-25 (host gone) |
| `DEMO_PIN_RUNNING` | `0` | `1` = `_destroy` is a no-op (reaper + killswitch log `reap_suppressed`, never stop). Live 2026-09-07 → 2026-09-25 (host gone) |
| `OCI_INSTANCE_IP` | set | private-IP proxy path, no control-plane call per request |
| `DEMO_MAX_SESSION_MINUTES` | `0` (off) | fixed session length (added 2026-10-06, owner request): an on-demand wake is stopped this many minutes after the wake call, whatever the activity (`session limit: …`); also ends a boot that never turns healthy. Outside a hot window only. `/health` reports `session_minutes`. Live value 60 ⇒ one wake = one billed hour. Unit-tested 2026-10-06 (`test_scheduler.py` 24, `test_state.py` 6 pass); first real stop pending |
| `DEMO_MAX_RUNTIME_HOURS_PER_MONTH` | `0` (off) | calendar-month runtime cap (added 2026-10-06): at the cap the scheduler stops the compute (`killswitch: … monthly cap`), `/start` refuses to wake (503, `start_refused_budget`) and a hot window will not boot. The same wake refusal now also applies once the daily cap is spent. `/health` reports `runtime_hours_month`. Live value 55 = CAD 40/month at the measured CAD 0.4823/h + CAD 0.359/day storage. Unit-tested 2026-10-06 (`test_scheduler.py` 19, `test_state.py` 5, `test_app.py` 7 — all pass); **not yet exercised against a real instance** |
| `DEMO_MCP_RESERVED_SLOTS` | 2 | MCP-priority slots of the 6 global billable slots |
| `DEMO_DIAL_BACKEND` | off | `systemd` / `cgroup`; off ⇒ /admin/dial 404s |
| WI-9/10/11 gates | all OFF | leg breaker / shard isolation / overload shed — byte-identical when off |

## Ingest / eval

Rows marked harness-only are read by a research/eval harness, never by `source/`.

| Gate | Meaning |
|---|---|
| `SFU_MEMCOMPRESSION_REGIME` | harness-only (`scripts/seismic_testbed/serve_footprint_bench.py`): operator assertion ∈ {zram, zswap, windows_compression, disk_swap, off, unknown} — changes the G8 latency-caveat verdict |
| `SFU_SEISMIC_PREFLOOR` | harness-only: the prefloor footing (`0`/`2`) the SEISMIC gate harnesses read and record themselves (`scripts/seismic_testbed/e5_shard_gates.py`, `e7_dotvbyte_gates.py`, `e8_dvv2_gates.py`, `wi4_portable_cpu_gates.py`, `wi1_seq_vs_par_federation.py`) and the delta-ingest evals set (`scripts/experiments/eval_delta_ingest_*.py`). Product code does NOT read it: the served lever is `SFU_SEISMIC_PREFLOOR_AT_LOAD`, so setting this name on a serving process changes nothing |
| `SFU_SEISMIC_INDEX` | harness-only (`scripts/seismic_testbed/g6_rrf_parity.py`): fallback for `--index-path`, the persona SEISMIC index stem. The served retriever's single-index branch that also read it was removed 2026-10-11 |
| `GUITB_HOST` | gui_testbed static server bind; default loopback-only |

## Feature flags (`SFU_FEATURE_<KEY>`, `lib/config.py` `load_config`)

Built as `f"SFU_FEATURE_{key.upper()}"` over the `default_features` keys; a set
value is truthy only for `1`/`true`/`yes`/`on` (case-insensitive), anything else
is OFF. Measured provenance: `BENCHMARK_METHODOLOGY.md`.

| Gate | Default | Meaning |
|---|---|---|
| `SFU_FEATURE_RERANK_ENABLED` | ON | the whole rerank pipeline (`tools._maybe_rerank`); OFF = fused order truncated |
| `SFU_FEATURE_CROSSENCODER_ENABLED` | ON | stage-2 cross-encoder pass after stage 1 |
| `SFU_FEATURE_RRF_ENABLED` | OFF | stage-1 rerank fuses embedding cosine with RRF (`use_rrf`) |
| `SFU_FEATURE_LOCAL_RRF_ENABLED` | ON | passed to the federated router as `local_rrf_enabled` |
| `SFU_FEATURE_FEDERATED_SEARCH_ENABLED` | ON | route searches through the federated (live OpenAlex versus local) router |
| `SFU_FEATURE_ZOTERO_ENABLED` | ON | Zotero tools; OFF ⇒ they answer "Zotero integration is disabled." |
| `SFU_FEATURE_EUROPE_PMC_ENABLED` | OFF | biomedical search via Europe PMC; OFF ⇒ falls back to the academic search |
| `SFU_FEATURE_QUERY_LOG_ENABLED` | OFF | MCP-tool query log (needs `SFU_QUERY_LOG_PATH`) |
| `SFU_FEATURE_ENGAGEMENT_LOG_ENABLED` | OFF | server-side impression rows (session `"server"`, `tools._log_query`, MCP text path and `/api/search`) into `SFU_ENGAGEMENT_LOG_PATH`; does NOT gate the GUI's own `POST /engagement` rows; the click-fed analytics panels ignore the server rows once GUI impressions exist (2026-10-12) |

## Process config and credentials (not serving levers)

All read by `lib/config.py` `load_config`. Credentials are read from the Docker
secret `/run/secrets/<name>` first, then the environment var; never put values in docs.

| Gate | Read at | Default | Meaning |
|---|---|---|---|
| `SFU_LOG_LEVEL` | `config.py` → both entry points' `setup_logging` | `INFO` | log level |
| `SFU_LOG_FILE` | `config.py` → `setup_logging` | `/tmp/sfu-library-mcp.log` | persistent log file; empty = no file handler |
| `SFU_ACTIVE_PROFILE` | `config.py`, `result_cache.py`, `serve_query_log.py` | `default` | profile name (reported by the sections tool); `production` turns the staging-on gates (`SFU_RESULT_CACHE`, `SFU_SERVE_QUERY_LOG`) OFF by default |
| `SFU_ENV` | `result_cache.py`, `serve_query_log.py` | unset | `production` has the same effect on the staging-on gates as the production profile |
| `SFU_CB_THRESHOLD` | `config.py` → `lib/zotero.py` | `5` | failures before the Zotero client's circuit breaker opens |
| `SFU_CB_TIMEOUT` | `config.py` → `lib/zotero.py` | `60.0` (s) | Zotero circuit-breaker open time |
| `SFU_DB_REGISTRY_CACHE_TTL` | `config.py` → `tools._get_registry` | `86400` (s) | SFU database-registry cache TTL |
| `SFU_DB_REGISTRY_CACHE_FILE` | `config.py` → `tools._get_registry` | `/tmp/sfu_databases_cache.json` | SFU database-registry cache file |
| `SFU_FEDERATED_RECENCY_DAYS` | `config.py` → federated router | `30` | queries about the last N days route to the live OpenAlex API |
| `SFU_ZOTERO_API_KEY` | `config.py` (secret `zotero_api_key`) → `zotero.py` | unset | Zotero API credential; empty ⇒ Zotero tools fail (configuration warning) |
| `SFU_ZOTERO_USER_ID` | `config.py` (secret `zotero_user_id`) → `zotero.py` | unset | Zotero library user id; empty ⇒ Zotero tools fail |
| `SFU_SEMANTIC_SCHOLAR_API_KEY` | `config.py` (secret `semantic_scholar_api_key`) | unset | Semantic Scholar credential; empty ⇒ unauthenticated, lower rate limit |

## Gates read by `source/` that this file did not list (added 2026-10-11, codebase triage)

Found by the codebase triage's gate table for the thin-client package; every
row below is read by code at HEAD. The gates removed the same day are
in "Retired gates" below.

| Gate | Read at | Default | Meaning |
|---|---|---|---|
| `SFU_SEISMIC_LOAD_MODE` | `thinclient/retriever.py` | `mmap` | shard load mode of the served SEISMIC leg (`archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md` §3, Phase A) |
| `SFU_SEISMIC_HEAP_FACTOR` | `thinclient/retriever.py` | `0.8` | SEISMIC query heap factor, alongside `SFU_SEISMIC_K_PRIME` / `SFU_SEISMIC_QUERY_CUT` |
| `SFU_SEISMIC_SHARD_SEARCH_TIMEOUT_S`, `SFU_SEISMIC_SHARD_REPROBE_S` | `thinclient/sharded_seismic_backend.py` | `30` / `10` | per-shard search timeout and re-probe interval of the fault boundary (`SFU_SEISMIC_SHARD_FAULT_BOUNDARY`) |
| `SFU_SEISMIC_HYBRID_SIGNAL`, `SFU_SEISMIC_HYBRID_WARM_FRAC`, `SFU_SEISMIC_HYBRID_FLIP_N`, `SFU_SEISMIC_HYBRID_WARMUP`, `SFU_SEISMIC_HYBRID_CONSEC`, `SFU_SEISMIC_HYBRID_DISABLE` | `thinclient/sharded_seismic_backend.py` (`HybridSeismicBackend`) | `adaptive` / `0.25` / `3` / `2` / `2` / `0` | knobs of the harness-only hybrid federation (doc 12 Q7): signal `adaptive`\|`count`; warm/cold traverse ratio threshold; count-arm query count; cold queries that seed the threshold; consecutive warm queries to flip; `1` = force parallel from query 1. **`SFU_SEISMIC_FEDERATION=hybrid` is not wired in the retriever: it silently serves the parallel backend** (owner decision: wire it or document it as harness-only) |
| `SFU_META_WAL_TRUNCATE_DOCS` | `thinclient/builder.py` | `250000` | build-side WAL truncation cadence for `meta.sqlite` |

## Retired gates (set them and nothing happens)

No product code (`source/` outside `source/tests/`) reads any name below; the test
fails if one comes back. "Last reader" names where a closed-track copy still
mentions it, if anywhere.

| Gate | Removed | Why / what replaced it |
|---|---|---|
| ~~`SFU_BLOCK_PREFETCH`~~ | 2026-09-25 | lever #4 term-prefix WILLNEED prefetch, **CLOSED MEASURED 2026-09-25**: cold traverse p50 1658.9 → 1590.3 ms (paired median −4.4%, bar ≥ 20%), RAM-resident arm slower (27.9 → 35.6 ms). Module archived at `spike/archive/block_prefetch/block_prefetch.py` (harness `scripts/archive/eval_block_prefetch.py`, results `data/eval_results/block_prefetch_ab_2026-09-25.json`) |
| ~~`SFU_BLOCK_PREFETCH_MAX_MB`~~ | 2026-09-25 | budget of the same closed lever #4 |
| ~~`SFU_DEMO_UPDATE_VERIFY_SEISMIC`~~ | 2026-09-25 | WI-13 update gate: `/verify` forced the lazy seismic load. Its only reader, `scripts/archive/demo_dependability/staging_serve.py`, was archived with the OCI demo code (c8fcb6b0); the reopened broker (2026-10-06) does not read it |
| ~~`SFU_DELTA_FOLDIN_TAX_MS`~~ | never implemented | doc 10 §1 fold-in threshold (b); needs F0's size coefficient. `spike/delta_ingest/trigger.py` ignores it and says so in every trigger record (`tax_hook`) |
| ~~`SFU_SKIP_BMP`~~ | 2026-10-11 | BMP shard skip; removed with the BMP SPLADE leg (317cbf83). Last readers: `scripts/archive/bmp_era/`, `scripts/archive/demo_dependability/` |
| ~~`SFU_LOAD_MEM_FLOOR_GB`~~ | 2026-10-11 | BMP load RAM floor; removed with the BMP leg (`scripts/eval_thinclient_parity.py` docstring records the history) |
| ~~`SFU_SPLADE_QDRANT_URL`~~ | 2026-10-12 | endpoint of the Qdrant rollback SPLADE leg (default `http://localhost:6333`); leg removed by owner decision (no Qdrant binary, service or collection in this container; code kept by the owner). `SFU_SPLADE_BACKEND=qdrant` now raises. No reader left on this branch |
| ~~`SFU_SPLADE_QDRANT_COLLECTION`~~ | 2026-10-12 | collection (`splade_150m`) of the same removed Qdrant leg; only `scripts/archive/qdrant-offbmp.supervisor.conf` still mentions it (comment) |
| ~~`SFU_FEATURE_LOCAL_OPENSEARCH_ENABLED`~~ | 2026-10-11 | OpenAlex→OpenSearch push; OpenSearch decommissioned 2026-06-11, push removed (61590ad8) |
| ~~`SFU_OPENSEARCH_URL`~~ | 2026-10-11 | OpenSearch endpoint; product backend archived (61590ad8). Still read by OpenSearch-era `scripts/experiments/` harnesses (`dense_indexer_poc.py`, `eval_cross_encoder.py`, `eval_dense_*.py`, `benchmark_llm_judge.py`) that cannot run without OpenSearch |
| ~~`SFU_OPENSEARCH_INDEX`~~ | 2026-10-11 | OpenSearch index name; removed with the backend |
| ~~`SFU_FEATURE_SPLADE_ENABLED`~~ | 2026-10-11 | feature key nothing read; SPLADE is always served via `SFU_SPLADE_BACKEND` |
| ~~`SFU_FEATURE_LAMBDAMART_ENABLED`~~ | 2026-10-11 | LambdaMART rerank tier removed (61590ad8) |
| ~~`SFU_LAMBDAMART_MODEL_PATH`~~ | 2026-10-11 | model path of the removed LambdaMART tier |
| ~~`SFU_FEATURE_CACHE_ENABLED`~~, ~~`SFU_FEATURE_RETRY_ENABLED`~~, ~~`SFU_FEATURE_CIRCUIT_BREAKER_ENABLED`~~, ~~`SFU_FEATURE_METRICS_ENABLED`~~, ~~`SFU_FEATURE_SEMANTIC_SCHOLAR_ENABLED`~~, ~~`SFU_FEATURE_LOCAL_EMBEDDING_ENABLED`~~ | 2026-10-11 | six `default_features` keys nothing read, dropped from `load_config` |
