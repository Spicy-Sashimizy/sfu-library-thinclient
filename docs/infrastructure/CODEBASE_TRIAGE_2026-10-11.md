# Codebase triage 2026-10-11 — ledger, verdicts, applied changes

**Status:** ACTIVE

**What this is.** The record of the 2026-10-11/12 codebase-wide triage: every
tracked file under `src/ web/ spike/ deploy/ .claude/ models/ scaffold/` and the
root (416 files at the restore tag; the 400 under `scripts/` were done the same
morning, `SCRIPT_TRIAGE_2026-10-11.md`), read and classified at file AND symbol
level under deliberately aggressive rules (`SCRIPT_HYGIENE_POLICY.md` §7):
test-only product code and gates whose rollback target no longer exists in this
container are removal candidates, not automatic keeps; explicit pending owner
decisions are not touched. Division of labour (owner instruction 2026-10-11): six
**Opus** agents read and classified (one row per file, a symbol row for
everything not plainly active, a gate row for every `SFU_*` read — 438 file rows,
133 symbol rows, ~35 gate rows); two Opus and two Sonnet
agents applied the accepted rows in groups (Opus for the served retriever,
Sonnet for the rest, per owner instruction 2026-10-12); every verdict, every diff
review, the mechanical re-derivation (`scripts/repo_tools/triage_audit.py`, run
against the restore tag) and every commit ran on **Fable**.

## Restore point and checks

The state before the wave is the restore tag `pre-codebase-triage-2026-10-11`,
kept by the owner (2,543 files, 5,369 functions/classes, 681 fast tests passing).
Each group commit below is self-contained.
`scripts/tests/test_dead_code_guard.py` keeps the product tree free of
unreferenced symbols. `scripts/tests/test_env_gates_doc.py` (2026-10-12) ties
environment gates to `ENV_GATES.md`: every `SFU_*` name product code reads has
a live row there, no retired (struck-through) name is read again, and every live
row has a reader outside `archive/`. `src/tests` 669 → 534 (every removed test
exercised only removed code; the scripts half re-run per file at every group),
`verify_web_jsdom` 74/74, `verify_web_progress` 18/18.

## Commits (every one through `preflight.py run`)

| # | Commit | Group |
|---|---|---|
| 0 | 21d4da55 | tooling: `triage_audit.py` generalized (any ledger directory, symbol rows), `dead_code_guard.py`, policy §7 |
| 1 | 021cbce1 | DEAD symbols in `src/` (7 defs + inert fields, parameters, keys); `preflight.py run --accept-removals` and `symbol_inventory.py diff --accept` — the only sanctioned way a protected symbol leaves |
| 2 | 69ddb269 | DEAD files deleted (14); `deploy/` + `requirements.prod.txt` archived to `scripts/archive/deploy_opensearch_era/`, `deploy/ntfy` → `scripts/demo_broker/ntfy`, `spike/n2_mphf` → `spike/archive/`, E8 plan → `plans/done/` |
| 3 | 300e4104 | web dead code removed and bundles rebuilt (`?v=duck8`); CLOSED banners on 16 archived spike files + patches README |
| 4 | dc9efb9f | TEST-ONLY product code removed with its tests (149 symbols) |
| 5 | 61590ad8 | GATED-ORPHAN: OpenAlex→OpenSearch push (default-ON, posting to a nonexistent `localhost:9200` on every non-federated search), `SFU_SEARCH_BACKEND=opensearch`, `OpenSearchRetriever` → archive, LambdaMART tier, `SFU_SEISMIC_INDEX` branch |
| 6 | 317cbf83 | GATED-ORPHAN: the BMP SPLADE leg out of the served retriever, the builder and the build script; `bmp` + `rank_bm25` pins dropped |
| 7 | this commit | `test_dead_code_guard.py`, the guard allowlist, docs sync, this ledger |

## Result

| Scope | Files (ledger classes at the tag) | Applied |
|---|---|---|
| `src/` (85) | ACTIVE 80 · GATED/OWNER-DECISION 15 (thinclient) · MISPLACED 4 · GATED-ORPHAN 5 · TEST-ONLY 1 | 2 files deleted (`lambdamart_features.py`, `test_openalex_push.py`), 2 test files gone with their subjects (`test_formatters.py`, `conftest.py`), 1 test renamed (`test_query_encoders.py`), `OpenSearchRetriever` archived, 1 test archived (`test_build_resume.py`) |
| `web/` (22) | ACTIVE 21 · DEAD 1 | `tweaks-panel.jsx` deleted; 34 JS symbols removed; bundles byte-rebuilt |
| `deploy/` (18) + `requirements.prod.txt` | MISPLACED 13 · DEAD 2 · GATED-ORPHAN 3 | directory gone: 12 archived, 2 moved to the broker, 5 deleted |
| `.claude/` (27), `models/` (3), `scaffold/` (5), root (9) | ACTIVE/EVIDENCE except 1 MISPLACED plan, 1 DEAD `.gitkeep` | plan moved to `done/`, `.gitkeep` deleted, index rows fixed |
| `spike/` live tracks (127) | EVIDENCE 98 · ACTIVE 22 · MISPLACED 5 (N2) · DUPLICATE 1 · GATED 1 | N2 archived; 3 delta_ingest symbols removed; 3 evidence files made traceable from docs 17/18 |
| `spike/archive` + forks (120) | ACTIVE 58 (forks are path dependencies of the live seismic crate) · EVIDENCE 55 · DEAD 7 | 7 artefacts deleted; 47 banner gaps closed where the file type allows |
| Symbols (133 rows) | DEAD 42 · TEST-ONLY 40 · DUPLICATE 21 · GATED-ORPHAN 11 · DYNAMIC 9 · OWNER-DECISION 4 · GATED 2 · REVIEW 2 · ACTIVE 2 | 288 keys removed; DUPLICATE rows reported only |
| Gates | ~35 read by the thin-client package alone | 26 removed; 8 undocumented ones added to `ENV_GATES.md`; `SFU_SEISMIC_PREFLOOR` row corrected to `_AT_LOAD`. 2026-10-12: the remaining 37 undocumented product reads documented (93 distinct names read by `src/` at HEAD), 27 names struck as retired, abbreviated cells written out, a Retired-gates table added, both directions enforced by `scripts/tests/test_env_gates_doc.py` |
| Dead-code guard | 675 symbols, 16 TEST-ONLY + 2 DEAD before | 619 symbols, 0 unreferenced, 2 allowlisted (`scripts/repo_tools/dead_code_allow.json`) |

The mechanical re-derivation of every ledger claim against the restore tag
flagged 4 DEAD file rows and 43 symbol rows, every one a generic-name grep hit, a
docstring mention, a built bundle or a dated snapshot; each was settled by hand.

## Verdicts the auditor took beyond or against a ledger row

- `src/lib/opensearch_retriever.py` is NOT legacy: it holds the SPLADE/dense
  query encoders the served SEISMIC leg imports (clients ledger Q1). Only the
  `OpenSearchRetriever` class moved; the module stays, docstring rewritten.
- `fault_status` (sharded backend): removed although a CLOSED-track harness
  (`scripts/archive/demo_dependability/wi10_shard_isolation.py`) calls it; an
  archive-only caller keeps nothing alive. That harness no longer runs at HEAD
  (it already could not: its deployment is gone).
- `pairs_from_adapter` (OA bitmap writer) kept although test-only: it is the
  code behind the "works with any adapter" claim in a dated findings record.
  `reset_for_test` / `reset_counters_for_test` kept as explicit test seams.
- `ExactSparseBuffer` and `OpenAlexApiAdapter.probe_deleted` (open since the
  2026-10-10 reorg §4): removed; no caller, no test, live twin in `delta_layer`.
- `SFU_SEISMIC_INDEX` single-index branch: removed (persona index absent; the
  G6 harness builds `SeismicBackend` itself).
- `deploy/ntfy/` went to `scripts/demo_broker/ntfy/` (its only consumer) so
  `deploy/` could disappear entirely.
- `deploy/demo_droplet/` deleted rather than archived (never run; its targets,
  DigitalOcean and Qdrant, are gone; recoverable from the tag).
- Web `SearchProvenanceCard` degraded branches left in place and unreachable:
  their copy describes a 3-engine layout that no longer serves (owner call below).
- Group 3's apply agent found one caller the ledger missed
  (`ResponseCache.clear` in the `test_speculation.py` autouse fixture); the
  fixture now drops the cache singleton, which both production callers rebuild.

## Owner decisions still pending (not agent work)

Reconciled 2026-10-12 (end of the wave). None of these is agent work; each needs the owner's call.
Owner calls of 2026-10-12 on items 1-4, 6, 7, 9: wave record `OWNER_DECISIONS_2026-10-12.md`.

1. **Dense leg keep-or-remove** (already pending; `DENSE_PARTITION_AND_ABLATION.md`).
   Size if removed: `dense_cache.py` 367 lines, `dense_delta_merge.py` 257,
   `builder.build_dense_leg` 32, ~75 retriever lines, `encode_dense`/`_get_dense_model`
   in the encoder module, `test_dense_cache_v2.py` + five stack tests, six gates.
   **RESOLVED 2026-10-12: KEEP** (owner); code stays, default OFF; ablation verdict stands.
2. **Qdrant rollback leg** (`_splade_leg_qdrant` + helpers, `SFU_SPLADE_BACKEND=qdrant`,
   `SFU_SPLADE_QDRANT_URL/_COLLECTION`): the target is not reachable here (no binary,
   nothing on :6333, no collection) and `archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md` has listed the
   archival container as planned since 2026-07-06. Build it (keep) or close the line.
   **RESOLVED 2026-10-12: removed** (owner-decisions wave). `SFU_SPLADE_BACKEND=qdrant`
   now raises; both gates are in the ENV_GATES.md "Retired gates" table; the split doc
   is CLOSED KILLED and archived.
3. **CE base flip** (`SFU_CE_MODEL_PATH`), pending since 2026-08-19.
   **DEFERRED 2026-10-12 (owner: leave)**
4. **Speculation levers** (`SFU_SEARCH_SPECULATE`: 4/7 bars FAIL 2026-07-28;
   `SFU_SEARCH_SPECULATIVE_RERANK`: p50 bar FAIL 2026-09-25): CLOSE MEASURED or name
   the follow-up; both stay GATED (targets exist) until then.
   **DEFERRED 2026-10-12 (owner: leave)**
5. **`SFU_SEISMIC_FEDERATION=hybrid`** silently serves the parallel backend: wire
   `HybridSeismicBackend` or document the value as harness-only.
6. **MCP tool surface**: nine advertised tools are named by no doc but this one
   (now listed in `THIN_CLIENT_SWAP.md`); trim or keep.
   **RESOLVED 2026-10-12: trimmed** (owner-decisions wave). `generate_citation`, `batch_generate_citations`,
   `export_search_results`, `list_zotero_collections`, `search_zotero`,
   `get_zotero_collection_items`, `get_zotero_status`, `get_openalex_budget` and
   `record_engagement` are gone from `TOOL_DEFINITIONS`, the dispatch dict and their
   handlers (18 tools remain); helpers that only they reached went too
   (`tools._format_single_citation`, the seven `citations.format_*` functions,
   `ZoteroClient.search_items` / `get_collection_items`) with their tests
   (`src/tests/test_citations.py` deleted; export/citation/budget tests removed from
   `test_tools_unit.py` and `test_tools_export_misc.py`).
   `test_tools_unit.py::TestOwnerToolTrim20261012` pins the absence. `save_to_zotero` /
   `batch_save_to_zotero`, `lib/engagement.py` and `POST /engagement` stay.
7. **`/analytics` panels**: the GUI consumes 2 of 9; **engagement events**: the GUI
   never posts one, so the click-fed panels say "awaiting click data" forever —
   wire the GUI or drop the route and the MCP twin. (2026-10-12: the MCP twin
   `record_engagement` was removed under decision 6; the route stays.)
   **RESOLVED 2026-10-12 (owner: "write the GUI for analytics and engagement"): GUI
   wired.** The search app posts query/impression/result_click/action events
   (`SFUApi.engagement`, re-introduced WITH callers after the 2026-10-11 removal of the
   unused stub), the analytics app renders all nine panels plus a new `index_shape`
   panel and no prototype figure, and the two click-fed panels exclude session
   `"server"` when GUI rows exist. The `/engagement` route stays; the MCP twin
   (`record_engagement` tool) was removed from `src/lib/tools.py` by the separate
   MCP-surface work of the same day (owner decision 2026-10-12), so `POST /engagement`
   is the only write entry point. Record: `docs/THIN_CLIENT_SWAP.md` "Engagement + analytics GUI".
8. **`REMOTE_MCP_ACCESS.md`** (ACTIVE) describes two access paths whose state is
   unverified (supervisor paths never existed here; NAS container unknown).
9. **`src/requirements.txt`** is not a serving set (the real locks are under
   `scripts/portable_linux/` and `scripts/portable_socsci/windows/`): regenerate or delete.
   **RESOLVED 2026-10-12:** deleted; root `requirements.txt` regenerated from code imports and pinned by `scripts/tests/test_requirements_cover_imports.py`; the platform locks under `scripts/portable_linux/` and `scripts/portable_socsci/windows/` are host-generated and untouched.
10. **Fork checkout**: `spike/seismic_upstream` is on branch `livedocs-skip` (620f1d2),
    not `main` (2c4d863); a rebuild from this checkout includes the O10 skip that no
    doc describes. Put it back on `main` or record the intended state.
11. **Degraded provenance UI** (web): drop the unreachable branches or feed them
    from the real `degraded` flag with rewritten copy.
12. **`manual_smoke_mcp_tools.py`**: keep as the documented manual smoke, or delete.

## Not done (by design)

- DUPLICATE rows (21 symbol rows, for example, the OpenAlex / Semantic Scholar retry
  loops, three filter builders, `_normalize_doi` twins) are reported, not
  consolidated: consolidation changes behaviour and needs its own parity run.
- `scripts/data/demo_payload_manifest.json` (2026-08-19 snapshot) still lists
  paths that moved or vanished today; it is a dated record, regenerate before the
  next payload build.
- Evidence harnesses that imported removed constants (`scripts/archive/bmp_era/
  eval_parity_section_waves.py`, `spike/archive/mmap_bmp/build_persona_bmp.py`) and
  `scripts/experiments/eval_storage_levers.py` (`import bmp`; the package is still
  in this venv but no longer pinned) do not run at HEAD; re-runs use the tag.
- `scripts/` was not re-triaged (done the same morning); `docs/` content was
  touched only where a claim became false.
