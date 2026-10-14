# Repository reorganization + dead-code audit — 2026-10-10 (ledger)

**Status:** ACTIVE

**What this is.** The record of the 2026-10-10 session that made the repository
navigable for human readers without changing any working module: file moves
(all `git mv`, history preserved), signpost READMEs, an evidence index, root
files (README/CONTRIBUTING/CITATION), two doc-drift fixes, and a line-by-line
dead-code audit of the product code by seven Opus agents. Every step is its own
commit so any one of them can be reverted alone. Owner request: "re-organize the
repository into something cleaner … without changing the functions or any working
modules", with "recovery options in the case of worst-case failure".

## Restore point

The state before the session is the restore tag `pre-reorg-2026-10-10`, kept by
the owner. Every commit in the tables below is self-contained and can be
reverted alone; `git log --follow --oneline -- <new path>` or the moves table
says where a file went. The deployed demo broker runs its own copy; nothing
changes there until it is redeployed (`scripts/demo_broker/README.md`).

Verification that nothing working changed: each audit commit records its
targeted test counts before and after (identical); the full-suite baseline is
in §5.

## 1. Moves (`git mv`; references repointed in the same commit)

| Old path | New path | Commit | References repointed |
|---|---|---|---|
| `start_sfu_library_mcp.{ps1,bat}`, `start_sfu_library_mcp_clone.ps1`, `claude_desktop_config.json` (root) | `launchers/` (+ README) | f295071e | `docs/deprecated/MCP_SETUP.md` (dated note) |
| `src/test_mcp_tools.py` | `src/tests/manual_smoke_mcp_tools.py` (docstring updated) | 16169de0 | — |
| `results/` (10 files, May 2026) | `data/eval_results/archive/training_era_results/` (+ README) | bff98ce8 | `scripts/experiments/eval_compare.py`, `evaluate_sfu_queries.py` defaults |
| `reports/…`, `research_notes/Updatable sparse index alternatives/` (6 docs, 2026-10-02) | `docs/delta_ingest/research_2026-10-02_updatable_sparse_index/` (numbered, Status lines, README) | 983e8c3d | row added to `docs/delta_ingest/README.md` |
| `languages/` (Pommel tree-sitter configurations) | `.claudebox/languages/` | 7926e724 | `docs/deprecated/POMMEL_SETUP_GUIDE.md` |
| `scripts/{build_presentation_metrics,eval_result_cache_ab,eval_result_cache_parity,eval_speculation_ab,arxiv_fetcher}.py`, `scripts/eval_speculation_playwright.mjs` (the `.mjs` moved on to `scripts/gui_testbed/` 2026-10-11 — it imports `gui_testbed/lib.mjs`; `SCRIPT_TRIAGE_2026-10-11.md`) | `scripts/experiments/` (REPO roots → `parents[2]`, Playwright import → `../gui_testbed/`) | 10ca509b + 65f1096b | `docs/BENCHMARK_METHODOLOGY.md`, `THIN_CLIENT_SWAP.md`, `delta_ingest/02_DESIGN.md`, `seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md`, `CODE_INVARIANTS_SCRIPTS.md` (bullets re-homed), three archive records |

Left in place on purpose: `scripts/data/demo_payload_manifest.json` (a dated
2026-08-19 payload snapshot; its paths are as they were that day);
`deploy/` (banner README instead of a move — `deploy/mcp_http.supervisor.conf`
is still cited by a live doc); `docker-compose.pommel.yml` (development harness, with
uncommitted local edits that are not this session's); `scripts/serve_http.sh`
and `stage_seismic_local.sh` (operator entry points, and `serve_http.sh` is the
systemd `ExecStart` on the broker box and the payload manifest's listed path).

Outside version control (ignored files, no commit): `benchmark_results.json`
and `benchmark_optimization_results.json` moved from the root to
`data/eval_results/archive/`; stale `__pycache__/` directories removed.

## 2. Additions

| Path | What | Commit |
|---|---|---|
| `src/README.md`, `src/lib/README.md`, `scripts/README.md`, `deploy/README.md`, `data/README.md`, `models/README.md`, `scaffold/README.md`, `spike/README.md`, `.claude/README.md`, `launchers/README.md` | signpost READMEs (serving stack versus build side versus legacy; root = operator entry points; deploy = LEGACY; .claude = how the work was run) | 0df5c75e, f295071e |
| `scripts/CLAUDE.md` | trimmed to agent rules; stale `archive/demo_broker/` bullet dropped (directory no longer exists) | 0df5c75e |
| `scripts/repo_tools/build_eval_results_index.py` → `data/eval_results/INDEX.md` | generated evidence index: 1,515 tracked files, date, size, citing docs (365 cited) | 451c7b4e |
| `README.md` (rewritten), `CONTRIBUTING.md`, `CITATION.cff` | human map, house rules in contributor form, citation metadata. **No LICENSE** — owner sign-off still open (`PORTABLE_LICENSING_INVENTORY.md`) | fb0c1554 |
| `docs/README.md`, `docs/CODE_INVARIANTS_SCRIPTS.md` | drift fixes: module map had `scripts/demo_broker/` and `deploy/` as "closed 2026-09-25" although the index's own subdirectory table recorded the 2026-10-06 reopening; demo_broker invariants heading said DORMANT | 0e697e2f |

## 3. Dead-code audit (line by line, product code only)

Method: `vulture --min-confidence 60` + `ruff --select F` as seeds, then every
file read top to bottom; a symbol was removed only when a reference search over
`src/ scripts/ spike/ web/ .devcontainer/ docs/ .claude/` (bare name and quoted
string) returned nothing outside its definition. Test-only symbols stayed (the
tests are the specification); anything named in a live doc stayed (documented API);
FastAPI routes, MCP handlers, `getattr` reads, dataclass/serialised fields and
ONNX option setters are dynamic and stayed. Evidence harnesses
(`scripts/seismic_testbed/`, `scripts/experiments/`, `*/archive/`) were out of
scope by policy. Agents did not commit; the coordinator committed per module.

| Scope (agent) | Lines read | Removed | Kept although flagged | Tests before → after | Commit |
|---|---|---|---|---|---|
| `src/lib/tools.py`, `sfu_library_mcp_http.py`, `sfu_library_mcp_server.py`, `formatters.py`, `validators.py` (A) | 3,608 | 4 lines: unused AccessResolver import, `_Path` import, `_CACHE_HIT_TOKEN`, `import sys` | `get_metrics` (test-only) | 327 → 327 | beb4d20d |
| external clients: `openalex`, `zotero`, `semantic_scholar`, `sfu_databases`, `citations`, `access_resolver`, `federated_search`, `retry` (B) | 3,541 | 87 lines: `get_work`, `get_works_batch`, `get_paper_by_doi`, unused client methods, one import | `retry_with_backoff` and other test-only helpers; `circuit_open`/`last_degraded` (getattr) | 326 → 326 | 8ae6e6b5 |
| glue: `opensearch_retriever`, `reranker`, `speculation`, `speculative_rerank`, `result_cache`, `embedding`, `lambdamart_features`, `config`, `cache`, `analytics`, `engagement`, `serve_query_log`, `logging_setup`, `model_registry`, `hf_load_lock` (C) | 3,871 | 11 lines: 3 imports, local `total`, `_stop` attr, `QueryLogger.stats()` | 4 env-parsed unused `ServerConfig` fields (constructor contract), `ev` lambda parameters, `show_progress_bar` kwarg, test-only helpers | 484 → 484 | 3d23278e |
| thin-client serving: `retriever`, `sharded_seismic_backend`, `seismic_backend`, `sections`, `ordinals`, `livedocs`, `oa_overlay`, `__init__` (D) | 3,937 | 7 lines: unused pathlib import, local `pos`, never-read `_shard_paths`, `sections.base_section()`. A 5th removal (`_backend_proto` + its eager import) was REVERTED: load-bearing for a test module stub | `search_rrf*`, `_leg_*_for_log` (tools.py), `ShardedSeismicBackend`+`__new__` (seismic_federated re-export), `_floor_mlocked`/`search_with_timing`/`degraded_shards`/`fault_status` (harnesses, docs), `write_stamp`/`pack_header` (spike writers) | 187 → 187 | 61715fa8 |
| thin-client build: `abstracts`, `builder`, `delta_layer`, `dense_cache`, `dense_delta_merge`, `doc_encoder`, `packer` (E) | 2,830 | 4 lines: `abstracts._is_cyrillic` (orphaned by v3 per-script compression) | `SectionBuilder`/`slice_checkpoint`/`build_dense_leg` (build_thinclient_index.py), `build_flat_sidecar`/`build_ordinal_locator` (build_flat_blocks.py), every `DeltaLayer` method (retriever._delta), `encode_batch` (delta_ingest/encode.py), ORT setters | 297 → 297 | 515cb5b2 |
| `scripts/demo_broker/` (F) | ~5,000 | 2 lines: two unused `import time` | all 13 app.py functions (FastAPI decorators), Session fields, `capture_output` kwarg | 110 → 110 | 9a81b3c3 |
| `spike/delta_ingest/` (G) | ~4,000 | 15 lines: `ENCODE_FIELDS`, `DocRecord.meta_row`, `IngestLedger.buffer_signature` | serialised fields, `decode_content`, `mark_fold_ready`, `ExactSparseBuffer`, `probe_deleted` (documented) | 241 → 241 | f3e158ae |

Post-audit docstring/comment fixes on closed files: 58b9c260.

## 4. Owner decisions surfaced (not acted on)

- Retire `retry.retry_with_backoff` (no production user; `test_retry` pins the one-failure rule EXTERNAL_API_CONTRACT cites). — *Settled 2026-10-11 by the codebase triage: removed; the rule is pinned by the OpenAlex/S2 client breaker tests.*
- Remove the four unread `ServerConfig` fields — changes environment parsing. — *Settled 2026-10-11 by the codebase triage: removed, together with five more inert fields and six unread feature keys (see CODE_INVARIANTS.md §ServerConfig).*
- `scripts/demo_broker/config.py` `DEMO_BEARER_TOKEN` is parsed but unused; `README.md:199` still says it is required on `/mcp`. `app.py` is missing a `Response` import used only in annotations (ruff F821, harmless).
- `spike/delta_ingest`: `ExactSparseBuffer` and `probe_deleted` have no callers but are named in docstrings/design docs; `02_DESIGN.md:21` says buffers freeze on `flush_bytes` but nothing enforces it; `routing.py` cites a non-existent `test_foldin_gates.py` (real file: `test_foldin_routing.py`). — *2026-10-11 (codebase triage): `ExactSparseBuffer` and `probe_deleted` removed.*
- Duplicated code worth a deliberate refactor (not dead): the year/OA/type filter builder (×3 in tools.py/http), `_handle_search_academic` versus `search_academic_structured`, `_proxy` versus `_proxy_web` in the broker, `_int_env` helpers, query normalisers (`casefold` versus `lower` — must NOT be unified silently).
- `sharded_seismic_backend`: `_floor_prefaulted` / `_floor_mlocked_bytes` are write-only (5 lines; kept as mlock bookkeeping beside `_floor_mlocked`, which a harness reads). `degraded_shards` / `fault_status` docstrings and `seismic_sequential_serving/01_ARCHITECTURE.md:108` say they feed `/health`, but nothing in `src/` calls them. — *2026-10-11 (codebase triage): the two write-only attributes and `fault_status` were removed; `degraded_shards` stays.*
- Possible defects found while reading (not changed): `SFU_SEISMIC_FEDERATION=hybrid` silently serves the parallel backend (the retriever only checks for "sequential"); the hybrid backend's `search_encoded` skips the per-shard fault isolation `SFU_SEISMIC_SHARD_FAULT_BOUNDARY=1` turns on.
- Stale docstrings (report only): `src/lib/thinclient/__init__.py` and the `retriever.py` module/class docstrings still describe the tantivy+BMP+usearch era and an `abstracts.sqlite` layout; `abstracts.AbstractLocatorMismatch` points at a deleted comment; `_open_flat` says dictionaries come from SQLite. — *2026-10-11 (codebase triage): the `__init__.py` re-exports were removed and its docstring rewritten.*
- `dense_delta_merge.py:183` ruff F821 is a known false positive (closure reads `rescore` before the outer `del`); do not restructure.

## 5. Test baseline

Full suite on the pristine tree (tag `pre-reorg-2026-10-10`, 2026-10-10,
`.venv/bin/python3 -m pytest -q`): **1,107 passed, 25 failed, 2 errors in
709 s**. Every failure/error is `MemoryError: RSS 4.0–4.1 GB > profile max
3.0 GB` from the delta-ingest memory guard when the whole suite runs in one
process (`test_delta_*`, `test_delta_abs_route`); the same files pass when run
on their own (agent E's before-pass: 297 passed over the 24 thinclient/delta
test files). This is a host/profile effect, not a code defect; it predates the
session. **Final run after every commit of this session (HEAD cc081b83): 1,107 passed, 25 failed, 2 errors in 197 s — the identical set of tests, all the same `MemoryError` guard; no test changed outcome.** Each audit commit additionally records its targeted-file counts (identical before/after).

## 6. Method and sources

Guides converge on a root with README, LICENSE, CITATION.cff and CONTRIBUTING,
a `docs/` folder, source with tests beside it, data only where needed, and a
per-folder README; none prescribes deeper folder names. The cleanup order
followed the practitioner consensus: tag a restore point, dead-code and
import-graph tools first (vulture, ruff), tests before and after, `git mv`
for history, repoint references in the same commit, one commit per move.

- Maastricht University, research software documentation (README / CONTRIBUTING / CITATION.cff at the root): https://library.maastrichtuniversity.nl/?p=4221382
- The Turing Way, advanced repository structure (separate input, methods, output; README/CONTRIBUTING/LICENSE/CODE_OF_CONDUCT at root): https://book.the-turing-way.org/project-design/pd-overview/project-repo/project-repo-advanced
- pyOpenSci packaging guide layout as reproduced by the CCN template (`src/` layout, top-level `tests/`, `docs/`): https://ccn-template.readthedocs.io/en/latest/notes/01-structure/
- UCSB research data guide to GitHub repositories (logical hierarchy, permissive license, contributing file): https://rcd.ucsb.edu/sites/default/files/2024-09/DLS-202409-GitHubRepos-navy.pdf
- Cookiecutter Data Science rationale (a standard skeleton so a newcomer can navigate without reading all the code): https://cookiecutter-data-science.drivendata.org/
- vulture (static dead-code finder; iterate, whitelist false positives, confidence levels): https://pypi.org/project/vulture/
- `git mv` + reference-update checklist: https://smithery.ai/skills/brianmjohnson/git-move

## Addendum 2026-10-13 — `src/` → `source/`, `web/src/` → `web/source/`

Owner decision 2026-10-13 (no abbreviated names in the tree). Executed with
`git mv`; restore tag `pre-src-to-source-2026-10-13`.

| Old | New | What else changed |
|---|---|---|
| `src/` (serving code, `lib/`, `tests/`) | `source/` | `pytest.ini` (`testpaths`, `pythonpath`), the `sys.path` inserts of every script and spike that imports the serving code, `scripts/repo_tools/` scopes (`symbol_inventory.py` and `preflight.py` keep `src/` as well so inventories against older tags still resolve), `dead_code_guard.py`, `check_script_placement.py`, the recovery and hygiene tests, `.claude/hooks/doc_sync_check.sh`, `scripts/serve_http.sh`, the portable-bundle builders (bundle-internal `app/src` layout unchanged), every live doc and README |
| `web/src/*.jsx` (GUI sources) | `web/source/*.jsx` | `scripts/build_web.mjs` (input directory and the generated-file header), `scripts/verify_web_jsdom.mjs`, `scripts/prime_result_cache.py`, `source/lib/speculation.py`, `source/sfu_library_mcp_http.py` (they read `search.jsx` for the persona list); `web/*.js` rebuilt, output identical apart from the header line |

Left as they were, on purpose: `docs/archive/`, `docs/deprecated/`, the dated
ledgers of 2026-10-10..12, `.claude/plans/done/`,
`data/eval_results/` records, the vendored Rust forks (their own `src/` is a
Cargo convention), the fork patches, `scripts/archive/deploy_opensearch_era/`
(the earlier deployment's paths), and `scripts/data/demo_payload_manifest.json`
(a dated snapshot). Not in this repository and still to be updated by the
owner: the Claude Desktop MCP launch command on the host and any local
launcher that names `src/sfu_library_mcp_server.py`.
