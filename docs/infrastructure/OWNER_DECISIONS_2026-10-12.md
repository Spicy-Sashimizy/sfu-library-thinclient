# Owner decisions 2026-10-12 — what was decided, what was applied

**Status:** ACTIVE

**What this is.** The record of the 2026-10-12 owner-decisions wave: the owner's
calls on seven of the twelve items the 2026-10-11 codebase triage left pending
(`CODEBASE_TRIAGE_2026-10-11.md` §"Owner decisions still pending"). The owner's
calls, given 2026-10-12: Qdrant rollback leg DELETE; dense leg KEEP; speculation
levers LEAVE; CE base flip LEAVE; MCP tools TRIM; analytics + engagement GUI
WRITE; stale requirements REGENERATE/DELETE; every change with a recovery plan,
an audit and tests. Division of labour: **Opus** applied G1-G3, **Sonnet**
applied G4 and the doc deltas, **Fable** audited every diff and ran every gate.

## Restore point and checks

The state before the wave is the restore tag `pre-owner-decisions-2026-10-12`,
kept by the owner. Each group commit in the decisions table is self-contained;
undo several newest first (G3 docs touch rows G2 wrote). Deleted files:
`src/requirements.txt` and `src/tests/test_citations.py`; by a staging error the
`src/requirements.txt` deletion rode into c7759d76 (G1), not c45c1315 (G4), so
reverting G1 also restores it (harmless: nothing reads it). Moved:
`SEISMIC_ARCHIVE_SPLIT.md` → `docs/archive/seismic_archive_split/` (CLOSED KILLED
2026-10-12 with the Qdrant leg). Removed: 78 symbols, the gates
`SFU_SPLADE_QDRANT_URL` and `SFU_SPLADE_QDRANT_COLLECTION` (both in `ENV_GATES.md`
"Retired gates") and 9 MCP tools.

Every preflight run of the wave: 531 `src` tests passed, 78 removals accepted
(`preflight.py run --accept-removals`). `verify_web_jsdom` 74 → 105 checks,
`verify_web_progress` 18/18, `src/tests/test_engagement_gui.py` 14 passed,
`scripts/tests/test_requirements_cover_imports.py` 24 passed.

## Decisions

| # | Decision | Owner's call | What was done | Commit | Apply / audit | Pinned by | Revert |
|---|---|---|---|---|---|---|---|
| G1 | Qdrant rollback SPLADE leg (triage item 2) | DELETE | `retriever.py::ThinClientRetriever.{_qdrant,_splade_leg_qdrant,_bert_vocab_map,_encode_splade_top}` removed; `SFU_SPLADE_BACKEND=qdrant` now raises; gates `SFU_SPLADE_QDRANT_URL` / `_COLLECTION` retired; `serve_query_log.py` touched; `SEISMIC_ARCHIVE_SPLIT.md` CLOSED KILLED and moved to `docs/archive/seismic_archive_split/`, references repointed; by staging error this commit also carries the `src/requirements.txt` deletion (pre-staged by the G4 agent with `git rm`), so reverting it restores that file too (harmless) | c7759d76 | Opus / Fable | `src/tests/test_thinclient.py::test_qdrant_splade_backend_removed`, `::test_unknown_splade_backend_raises` | `git revert c7759d76` |
| G2 | MCP tool surface (triage item 6) | TRIM | 27 → 18 tools: `generate_citation`, `batch_generate_citations`, `export_search_results`, `list_zotero_collections`, `search_zotero`, `get_zotero_collection_items`, `get_zotero_status`, `get_openalex_budget`, `record_engagement` out of `TOOL_DEFINITIONS` and dispatch; their 10 `tools._handle_*` handlers, `tools._format_single_citation`, the seven `citations.format_*`, `ZoteroClient.search_items` / `get_collection_items` removed; `src/tests/test_citations.py` deleted; export/citation/budget tests removed from `test_tools_unit.py` / `test_tools_export_misc.py` | 386cddc7 | Opus / Fable | `src/tests/test_tools_unit.py::TestOwnerToolTrim20261012` | `git revert 386cddc7` |
| G3 | Analytics + engagement GUI (triage item 7) | WRITE | `SFUApi.engagement` (with callers) posts query / impression / result_click / action events; `ACTION_TYPES` gains `save`; `analytics.engagement_source()`; analytics app renders all nine panels plus a new `index_shape` panel; bundles rebuilt. Efficacy: IMPLEMENTED 2026-10-12, click-fed panels populate from first use. Playwright sweep NOT run | bd72001a | Opus / Fable | `src/tests/test_engagement_gui.py` (14 passed); `scripts/verify_web_jsdom.mjs` 74 → 105; `verify_web_progress` 18/18 (flaky once in three runs on the auditor's machine, passed on rerun) | `git revert bd72001a` |
| G4 | Stale requirements (triage item 9) | REGENERATE / DELETE | `src/requirements.txt` deleted (deletion committed in c7759d76 by staging error, see above); root `requirements.txt` regenerated from code imports, floors at installed major.minor; `seismic` deliberately NOT pinned (local fork wheel); `brotli` / `py3langid` kept as optional evals; demo payload manifest builder + test updated. Platform locks untouched (`scripts/portable_linux/` last commit 2026-09-27, `scripts/portable_socsci/windows/` 2026-08-04) | c45c1315 | Sonnet / Fable | `scripts/tests/test_requirements_cover_imports.py` (24 tests, incl. the no-pyseismic-pin test) | `git revert c45c1315` (does NOT restore `src/requirements.txt`: its deletion rode into c7759d76 by staging error) |
| G5 | Dense leg (triage item 1) | KEEP | Nothing removed; code stays, default OFF since 2026-08-18; the `DENSE_PARTITION_AND_ABLATION.md` verdict DROP stands as the measured answer; dated line added there | (5/5, this ledger) | Opus / Fable | existing dense tests unchanged | n/a (no code change) |
| G5 | Speculation levers (triage item 4) | LEAVE | DEFERRED 2026-10-12 (owner: leave); both levers stay GATED default-OFF; dated line in `SPECULATIVE_RETRIEVAL_UPGRADES.md` | (5/5) | Opus / Fable | existing speculation tests unchanged | n/a |
| G5 | CE base flip `SFU_CE_MODEL_PATH` (triage item 3) | LEAVE | DEFERRED 2026-10-12 (owner: leave); no change | (5/5) | Opus / Fable | n/a | n/a |
| G5 | Ledger + doc sync | — | this doc, triage ledger items 1/3/4/9 reconciled, `docs/README.md` row | (5/5) | Opus / Fable | `scripts/tests/test_doc_status.py` | `git revert <(5/5)>` |

## Findings for the owner (not fixed by this wave)

- **Suspect prefloor footing in the delta-ingest evals.** They set a bare
  `SFU_SEISMIC_PREFLOOR`, which product code never reads (the served lever is
  `SFU_SEISMIC_PREFLOOR_AT_LOAD`), so their recorded prefloor setting did not reach
  the backend. Found 2026-10-12 by the env-gate coverage test work
  (`scripts/tests/test_env_gates_doc.py`).

## Owner decisions still pending after this wave

Reconciled 2026-10-12. Numbering is the triage ledger's (`CODEBASE_TRIAGE_2026-10-11.md`); none is agent work.

- 5. `SFU_SEISMIC_FEDERATION=hybrid` silently serves the parallel backend: wire `HybridSeismicBackend` or document the value as harness-only.
- 8. `REMOTE_MCP_ACCESS.md` describes two access paths whose state is unverified.
- 10. Fork checkout: `spike/seismic_upstream` is on `livedocs-skip`, not `main`.
- 11. Degraded provenance UI (web): drop the unreachable branches or feed them from the real `degraded` flag.
- 12. `manual_smoke_mcp_tools.py`: keep as the documented manual smoke, or delete.
