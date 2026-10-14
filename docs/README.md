# docs/ — documentation index

**Status:** ACTIVE

This index routes; it does not hold detail. Every subdirectory's `README.md`
is that track's entry point and status ledger, and every number lives in the
doc that measured it. If a doc and the code disagree, the code wins and the
doc gets fixed in the same session (`.claude/CLAUDE.md`, source-of-truth
rules). Nothing under `archive/` or `deprecated/` is current.

**Pending-work triage reads ONLY the tables whose heading says "Active".**
"Deferred" is parked by decision; "Closed tracks" is dead and never pending.
`scripts/tests/test_doc_status.py` enforces both.

## 1. Start here

| Want to… | Read |
|---|---|
| understand what runs today (engines, index layout, serving path, gates, GUI, MCP tools) | `THIN_CLIENT_SWAP.md` — the canonical architecture doc |
| rebuild a servable index from public data, or re-score a headline number | `REPRODUCIBILITY.md` |
| see how relevance and parity are measured | `BENCHMARK_METHODOLOGY.md` |
| find the evidence file behind a number | `data/eval_results/INDEX.md` (generated; file → date → citing docs) |
| know what is open, parked or dead | sections 5–7 of this index |

## 2. Rules for agents and contributors — the CLAUDE.md section

`.claude/CLAUDE.md` is the rule file every contributor and every agent loads.
It is short on purpose; the rules it makes binding live in these docs. They
are reference material, not research: read them before changing code.

| Doc | Rule set |
|---|---|
| `.claude/CLAUDE.md` | the house rules themselves: git workflow (pull → edit → stage explicitly → commit → push), doc freshness and measured-claims discipline, project venv, closed-tracks policy, no inline comments, Pommel-first code search |
| `CODE_INVARIANTS.md` | every constraint, invariant and workaround for `source/` — migrated out of code comments under the 2026-09-01 no-comments policy; test conventions and pinned invariants for `source/tests/` |
| `CODE_INVARIANTS_SCRIPTS.md` | the same ledger for `scripts/` (and the archived deploy tooling), plus knowledge mirrored from the evidence harnesses; test-suite baseline counts |
| `ENV_GATES.md` | every `SFU_*` / `DEMO_*` environment gate: default, parsing quirk, retired gates. Coverage both ways is enforced by `scripts/tests/test_env_gates_doc.py` (2026-10-12) |
| `EXTERNAL_API_CONTRACT.md` | OpenAlex / Semantic Scholar / arXiv client rules: circuit-breaker semantics, rate limits, the SPLADE-index write policy |
| `infrastructure/SCRIPT_HYGIENE_POLICY.md` | script placement and `Lifecycle:` header rules, the substantial-change gate (restore tag + fast tests + function inventory before any commit of ≥10 files / ≥500 lines / any code delete or rename), the three hook layers |
| directory `CLAUDE.md` files | local rules that load automatically when working there: `source/lib/thinclient/`, `data/`, `scripts/`, `web/`, `spike/` |

## 3. Architecture and measurements — Active docs (this folder)

| Doc | One-line hook |
|---|---|
| `THIN_CLIENT_SWAP.md` | **Canonical architecture**: engines, index layout, serving path, environment gates, web GUI (`/app`, `/api/*`), MCP tools |
| `REPRODUCIBILITY.md` | What an outside reader can reproduce (2026-10-10): one-command rebuild from the OpenAlex snapshot (`scripts/reproduce/`), MEASURED 50,000 works → served in 182 s; prerequisites, limits, how each headline number is re-scored |
| `BENCHMARK_METHODOLOGY.md` | LLM-judged NDCG@10 harness and the thin-client-vs-OpenSearch parity method; served E8 dv-v2 shards MEASURED 2026-09-27 (Haiku 0.9426 / Kimi 0.9249, n=120) |
| `STORAGE_BUDGET_150M.md` | Whole-database storage budget: measured levers and status, all-levers totals (300.9 → 188.8 GB) |
| `LEXICAL_STORAGE_RESEARCH.md` | Storage and compression research with measured results (sidecar variants, multilingual, all-levers matrix) |
| `DENSE_PARTITION_AND_ABLATION.md` | Dense leg as optional payload; ablation VERDICT 2026-08-18: DROP from payload (Δ nDCG@10 −0.0077, CI negative); the leg stays in code |
| `DENSE_WARMCACHE_RESEARCH.md` | Query-driven dense warm cache (v1 in `lib/thinclient/dense_cache.py`); success metrics MEASURED 2026-09-25 (dense-leg recall@50 0.107 → 0.348, cache hit 0 → 0.592) |
| `ORDINALS_RESIDENCY_CLIFF.md` | Does the filter stage fall off a cliff as the page cache shrinks? MEASURED 2026-09-25 — REFUTED; the SQLite stage's hot set is 122.7 MB; 55–90× cold-start win found |
| `SPECULATIVE_RETRIEVAL_UPGRADES.md` | Draft/verify levers on the search path (byte-identical output). Lever #1 IMPLEMENTED 2026-09-25 behind `SFU_SEARCH_SPECULATIVE_RERANK` (default OFF, ~92 ms p50 saving per miss, below the bar); #0 kept (free); #2 gate OFF; #4 closed measured; #5/#6 deferred — details and results files in the doc |
| `THIN_CLIENT_STACK_RESEARCH.md` | Engine selection proof of concept (tantivy + BMP + usearch), per-engine survey, abstract policy |
| `LOCALIZED_DEPLOYMENT_PLAN.md` | Deployment tiers (15M laptop / warm cache / 150M server); partially superseded, see its 2026-06-11 note |

## 4. Repository ledgers — Active (`infrastructure/`)

Dated records of what was changed in the repository and why. Full list in
`infrastructure/README.md`.

| Doc | What it records |
|---|---|
| `infrastructure/PUBLIC_PREP.md` | Publication note: **repository public since 2026-10-13**, published as a single-commit snapshot |
| `infrastructure/REBRAND_DUCK_LIBRARY_2026-10-10.md` | "SFU Library" → "Duck Library": revert table, compatibility aliases, what still says `sfu` and why |
| `infrastructure/REPO_REORG_2026-10-10.md` | The 2026-10-10 reorganization: every move, per-module audit table |
| `infrastructure/SCRIPT_TRIAGE_2026-10-11.md` | 402/402 files under `scripts/` classified; 12 moves, 3 deletions, 36 banners |
| `infrastructure/CODEBASE_TRIAGE_2026-10-11.md` | Every tracked file under `source/ web/ spike/ deploy/ .claude/ models/ scaffold/` classified at file and symbol level; per-group commits |
| `infrastructure/OWNER_DECISIONS_2026-10-12.md` | Owner's calls on seven triage items (Qdrant leg removed, MCP tools 27 → 18, analytics and engagement GUI wired, requirements regenerated, dense KEEP, speculation and cross-encoder flip DEFERRED); items still pending |
| `infrastructure/PORTABLE_LICENSING_INVENTORY.md` | INVENTORY ONLY, no legal clearance (2026-09-29): per-component licensing facts for the handout; no LICENSE file in the repository yet, sign-off open |

## 5. Research tracks — Active subdirectories

Each directory's `README.md` is the entry point and carries the full status
ledger (dates, verdicts, open items). This table only says what the track is.

| Directory | Track | State (date) |
|---|---|---|
| `infrastructure/` | running, reaching and deploying the system: public OCI demo (reopened 2026-10-06), portable and handout bundles, index write protection, access runbooks, GUI specifications, repository ledgers | ACTIVE; see `infrastructure/README.md` |
| `seismic_150m_testbed/` | SEISMIC at 150M: gates, mmap serving, forward-data compression, E5/E8 reorder (served default), docs 17–18 spikes | ACTIVE; served engine since 2026-07-06 |
| `delta_ingest/` | source-agnostic trickle updates over the immutable base (L0 buffer → immutable delta generations → compaction → fold-in); code `spike/delta_ingest/` + `source/lib/thinclient/delta_layer.py`, gate `SFU_DELTA_ROOT` default OFF | IMPLEMENTED; serving gate NOT eligible as of 2026-10-09 (M4 growth, F3/F8 fold-in bars FAIL); full ledger in `delta_ingest/README.md` |
| `rust_core/` | which serve-path modules can move into the seismic fork crate (pyo3 face for the server, CLI face for Windows/Android handouts); pre-registered bars, golden fixtures | opened 2026-10-11, DESIGN ONLY, nothing ported or measured |
| `session_2026-07-14_f6_corrections_r1_ladder/` | session record: F6 correction (2.8×), R1 RAM ladder, the convergence artifact (`04_` + dated addenda; repro harness `spike/convergence_repro/`) | cloud access ended 2026-09-25: gate item 1 PASSED (re-runnable here), items 2–3 archival-only; re-hostable work DRAFT in `spike/convergence_repro/PREREGISTRATION_WSL2_REHOST.md` + `PREREGISTRATION_TIER1E.md` |

## 6. Still open — Active backlog

**Reconciled 2026-10-13** (previous reconciliations 2026-09-29, 2026-09-25;
no item changed state since 2026-10-09). Open items that live inside a doc,
re-homed here so triage sees them without opening the doc. "Runnable here" =
on the local WSL2 host (54 GB RAM since 2026-10-03, 16 cores), no cloud, no
new hardware. Verified 2026-09-29: `/sys/fs/cgroup` is read-only and there is
no `docker` or `systemd-run`, so no memory-capped cell can run here; the
OpenSearch source index is gone, so no spool re-export is possible.

| Item | Source | State | Runnable here |
|---|---|---|---|
| H5 — sequential dv federation at a 6 GB cap | `seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` Tier 2 | pre-registered, never run | **no** (needs a memory cap) |
| E3 — `n_postings` down-sweep | `seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` Tier 3 | needs a shard rebuild from `spool_backup` first | not as-is (rebuild required) |
| Q10 — delta side-shard ingest | `delta_ingest/` (opened 2026-09-29; `semantic_docid_ingest/` stays DEFERRED for the learned-id half) | ingest is real behind `SFU_DELTA_ROOT` (default OFF). Measured through 2026-10-09: M1/M2/M3/M5 PASS, M4 growth bar FAIL, M7 FAIL, M9 FAIL explained as build noise; `09` levers L1–L5 kept (R1/R2/R3/P3 run); `10` fold-in F1/F2/F4/F5/F6 PASS, F0/F3/F8 FAIL, F7 flagged → not promotable. Remaining: owner ruling on the `per_base_section` fallback stack (doc 11 bar A FAIL for `single`), the `SFU_OA_BITMAP` rerank-quality decision, hot-section base-hash seed (owner), O10 lock timing + operator `.so` swap, O2 two-freeze residual, O14 CPU-profile saving and shard 1–7 locators, M2 on a second section, 9-shard pilot M10 NOT RUN, section-fold / full-rebuild triggers of doc `13` (design only). Dated detail: `delta_ingest/README.md` | yes, except the owner decisions |
| Portable stack §(d) rows 1–3, 5 | `infrastructure/PORTABLE_STACK_MANIFEST.md` §(d) | row 1 Windows/mmap serving UNMEASURED; row 2 subset spool re-export; row 3 licensing (inventory DONE 2026-09-29, sign-off open); row 5 macOS/ARM. Row 4 DONE for Linux x86-64 2026-09-27 (`infrastructure/PORTABLE_LINUX_BUNDLE.md`); row 6 CPU-only serve path DONE 2026-09-27 (top-10 byte-identical to GPU on 120/120, total p50 +823 ms, `cpu_only_serve_path_2026-09-27.json`) | row 1 needs a Windows host; row 2 **no** (source index gone); row 3 is a human call; row 5 no (no ARM hardware) |
| Q7 follow-up — doc 14 §5 re-encode branch (§5.1 prechecks 1–3) | `seismic_150m_testbed/14_ENCODER_UPGRADE_PATH.md` §5 | never pre-registered; the encoder book is CLOSED and §5 is "NOT scheduled" — opens only if a corpus rebuild is forced anyway | GPU-feasible (RTX 4070 Ti SUPER), multi-day; not without an operator decision |
| F5 — real-stack efficacy after the 2026-08-31 scope fix | `spike/convergence_repro/PREREGISTRATION_WSL2_REHOST.md` (DRAFT) | pre-registration not frozen. §6 gaps 2–3 DONE 2026-09-29 (no cell ran); §6 gap 1 MEASURED 2026-09-29 (`data/eval_results/wslrh_f5_gap1_verify_2026-09-29.json`): the rebuilt F5 hook drops RssFile 8.24 GB versus an 8.52 GB residue, the served pre-fix hook 7.07 GB; the 2026-07-14 NULL is explained. Served `.so` NOT swapped (operator step). Follow-up: gap 2's flag must pass the RAW sidecar extents. §5 calibration + §7 bars remain | prep work yes; the ladder and calibration cells **no** (need a memory cap) |

Operator decisions still waiting on a human (not agent work):

| Decision | Source | State |
|---|---|---|
| Cross-encoder base flip (`SFU_CE_MODEL_PATH`) | `THIN_CLIENT_SWAP.md` §Rerank | DEFERRED by the owner 2026-10-12 (`infrastructure/OWNER_DECISIONS_2026-10-12.md`) |
| Dense leg: keep in code or remove | `DENSE_PARTITION_AND_ABLATION.md` | ablation says DROP from payload; owner decision 2026-10-12: KEEP in code |
| Speculative rerank default (`SFU_SEARCH_SPECULATIVE_RERANK`) | `SPECULATIVE_RETRIEVAL_UPGRADES.md` | DEFERRED by the owner 2026-10-12 |
| `SFU_DELTA_ROOT` eligibility on the fallback stack | `delta_ingest/11_P2_MULTISECTION_PREREGISTRATION.md` | waiting on the owner since 2026-10-04 |
| `SFU_OA_BITMAP` (open-access filter versus rerank quality) | `delta_ingest/02_DESIGN.md` §3.1 O17 | gate OFF by owner decision; re-decision open |
| Convergence write-up: spin off to its own repository | `session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md` | undecided |
| MGLRU-FG kernel test: go / no-go | `spike/convergence_repro/PREREGISTRATION_T1D_FG.md` | undecided |
| Freeze the two DRAFT pre-registrations | `spike/convergence_repro/PREREGISTRATION_WSL2_REHOST.md`, `PREREGISTRATION_TIER1E.md` | both DRAFT, unfrozen |
| Licence for the repository | `infrastructure/PORTABLE_LICENSING_INVENTORY.md` | no LICENSE file; owner sign-off open |

## 7. Deferred

Parked by decision or by a missing prerequisite — not closed, not pending.

| Path | Deferred | Why |
|---|---|---|
| `ABSTRACT_SIDECAR_BACKFILL.md` | 2026-08-18 | operator: the OpenAlex polite-pool live fetch is sufficient; design only, nothing built |
| `seismic_sequential_serving/` | 2026-07-16 | measured (WI-1: peak RssFile 0.023×, warm p50 5.29× parallel) but never promoted; parallel federation is still served |
| `disk_streaming_research/` | 2026-09-25 | F1–F6 hooks built and gated OFF; no promotion decision taken |
| `math_optimization/` | 2026-09-25 | M2 measured but NOT promoted (failed its pre-registered bar); M6–M10 pre-registered, unfrozen |
| `semantic_docid_ingest/` | 2026-09-25 | DESIGN ONLY / UNMEASURED since 2026-06-30; no code. Frames the still-open Q10 |
| `seismic_150m_testbed/build_plans/02–04` | 2026-09-25 | DESIGN since 2026-06-28, unbuilt |
| `spike/ebpf_pagecache/` | 2026-09-25 | compiles, but LOAD IMPOSSIBLE here — no `cache_ext` kernel and no `CAP_BPF` in the container |

## 8. Closed tracks

Dead. Never pending, never dispatched, never quoted as current without saying so.

> **2026-10-06 — REOPENED:** `OCI_DEMO_DEPLOYMENT.md`, `DEMO_PAYG_PLAN.md` and `scripts/demo_broker/` left this table (owner moved the tenancy to Pay As You Go; serve instance rebuilt, click-wake and one-hour stop measured). The other three demo docs below stay closed on their own grounds.

| Path | Closed | What replaced it | Now lives in |
|---|---|---|---|
| `infrastructure/OCI_FREE_TIER_RESIDENT_DEMO.md` | DEAD 2026-09-25 | nothing — the Always-Free A1 allotment and the E5 x86 box are gone | `deprecated/oci_demo/` |
| slack-space posting-list format for in-place updates (PMA / Büttcher–Clarke gaps; entry in `delta_ingest/02_DESIGN.md` §4 item 10, no doc of its own) | DEAD 2026-09-29 | nothing — updates go to delta generations + livedocs masks; weeks of Rust, ~1.5–2× space *est.*, E5 Fix #5A measured padding dilutes page sharing | `delta_ingest/04_IMMUTABILITY_RESEARCH.md` conclusion 5(b) (research record) |
| `infrastructure/HYBRID_DEMO_DEPLOYMENT.md` | DEAD 2026-09-25 | superseded 2026-08 by the OCI E5 plan, which is itself dead | `deprecated/oci_demo/` |
| `infrastructure/DEMO_DEPENDABILITY.md` | DEAD 2026-09-25 | nothing — the cloud tier has no host; the in-container half and its measured numbers stand as a local record | `deprecated/oci_demo/` |
| `bmp_decommission_plan/` | SUPERSEDED 2026-07-06 | the SEISMIC promotion (`archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md`); DO SKU/price tables additionally unrunnable 2026-09-25, only the RAM→latency model survives | `archive/bmp_decommission_plan/` |
| `SEISMIC_ARCHIVE_SPLIT.md` (moved 2026-10-12) | KILLED 2026-10-12 | Phase A (SEISMIC default, 2026-07-06) stands; Phases B–E, the dev/archival container split, are dead: BMP leg removed 2026-10-11, Qdrant rollback leg removed 2026-10-12 (owner decision). SEISMIC-only serving is the only SPLADE line; forensic code on branch `archive/bmp-qdrant` | `archive/seismic_archive_split/` |
| `qdrant_vs_lucene_assessment/` | SUPERSEDED 2026-07-06 | SEISMIC federated mmap took the slot; the RAM/OOM findings remain the evidence base | `archive/qdrant_vs_lucene_assessment/` |
| `qdrant_uint8_sparse/` | SUPERSEDED 2026-09-25 | SEISMIC promoted 2026-07-06; Qdrant was then the gated rollback only (leg removed 2026-10-12), so the f32→uint8 fallback is moot. Scaffold code left inert, unmeasured | `archive/qdrant_uint8_sparse/` |
| `sparse_engine_project/` | MEASURED 2026-06-26 | SEISMIC federated mmap; FORMAT-WALL kept as the result (verdict STOP, `07_INTEGRATION_PLAN.md` §8) | `archive/sparse_engine_project/` |
| `seismic_150m_testbed/12_EXECUTION_ROADMAP.md` | SUPERSEDED 2026-09-25 | this index's Active tables — its Q1–Q11 queue is fully decided and its four STILL-OPEN items were re-homed into "Still open — Active backlog" above | `archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` |
| `MASTER_TODO.md` | SUPERSEDED 2026-09-25 | this index — its Active tables are the only list of open work | `archive/MASTER_TODO.md` |
| `spike/archive/smallmachine_levers/` (moved from `spike/smallmachine_levers/` 2026-09-25) | DEAD 2026-09-25 | nothing — bars S1–S5 derive from the gone OCI 14.8 GB floor and the 34 GB S4 control exceeds the 31 GB host; the one re-hostable question is re-posed at 11/12 GB in `PREREGISTRATION_WSL2_REHOST.md` (DRAFT) | `spike/archive/smallmachine_levers/` |
| `spike/archive/mmap_bmp/` | MEASURED 2026-06-26 | SEISMIC; kept as evidence for `archive/sparse_engine_project/` | `spike/archive/mmap_bmp/` |
| `spike/archive/n2_mphf/` (moved from `spike/n2_mphf/` 2026-10-11) | MEASURED 2026-09-27 | MPHF viability for ordinal addressing: verdict FAIL (its README; doc 18 §7 N2); ordinals stay array-addressed | `spike/archive/n2_mphf/` |
| `deploy/` (OpenSearch-era droplet + TrueNAS deploy tooling, `requirements.prod.txt`) | SUPERSEDED 2026-10-11 | `scripts/demo_broker/` (OCI demo, reopened 2026-10-06) and `scripts/serve_http.sh` locally; `deploy/ntfy/` moved to `scripts/demo_broker/ntfy/` (live relay) | `scripts/archive/deploy_opensearch_era/` |
| `scripts/demo_dependability/` | DEAD 2026-09-25 | nothing — the deployment it gated is gone; the in-container harness still runs locally | `scripts/archive/demo_dependability/` |
| `archive/inplace_update/05..07_INPLACE_*` + `spike/archive/inplace_update/` (+ `patches/seismic_upstream_inplace_v3*.patch`) + `scripts/archive/inplace_update/eval_inplace_*.py` (in-place bit-update spike: custom format-v3 encoder/decoder, Rust bit updater, +tail) | MEASURED 2026-09-30 | nothing in-place — updates stay with delta generations (`delta_ingest/`); the frozen GO rule read NO-GO on S0-1 (long-list dead-slot coverage 0.019 versus 0.80: a quarter updates 27 % of a shard and adds 15 % new docs while deletions free 6 %); v3 decoder exact (B1 460/460), A2 apply 2.6× the device bytes of one delta generation while placing 0 docs, A2b heap exhausted after 1.06 batches; fork `main` reset to 2c4d863 on 2026-09-30; the spike commits a3173d1..328bf51 live on fork branch `inplace-v3` (c7b4b54 on `b1-guard`); the installed `.so` (built 2026-08-10) never contained them; do not merge `inplace-v3` into `main` (owner decision 2026-09-30: the +1.3 % B1 per-query cost is not acceptable on the serving path) | `archive/inplace_update/` (docs), `spike/archive/inplace_update/` (code, specification, findings, patches), `scripts/archive/inplace_update/` (harnesses); fork branches `inplace-v3` and `b1-guard` in `spike/seismic_upstream` |

## 9. Code → documentation maps

Spikes:

| Code | Documentation |
|---|---|
| `spike/convergence_repro/` | Pre-registrations + RESULTS.md live in the spike itself (judged records); write-up: `session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`. T1d access-histogram probe (2026-09-12, `PREREGISTRATION_T1D_PROBE.md` §7–8, script `scripts/seismic_testbed/t1dprobe_access_histogram.py`, results `data/eval_results/t1dprobe_*_20260912.*`). Figure set: `spike/convergence_repro/figures/` (2026-09-13) |
| `spike/ebpf_pagecache/` | `README.md` in the spike (2026-09-25: COMPILES on clang 14.0.6 via `offline_build/`; LOAD IMPOSSIBLE on this host; nothing measured — §7); runnable-vs-blocked matrix in `TEST_SITUATIONS.md`; ties to `convergence_repro/PREREGISTRATION_T1D_FG.md` and `_T1D_PROBE.md` |
| `spike/bm25_seismic/` | `seismic_150m_testbed/17_BM25_THROUGH_SEISMIC_SPIKE.md` |
| `spike/meta_consolidation/` | `seismic_150m_testbed/18_ORDINAL_ADDRESSING_DESIGN.md` |
| `spike/delta_ingest/` | `delta_ingest/` (design `02_DESIGN.md`, measurements `03_SPIKE_PLAN.md` addenda, fold-in `spike/delta_ingest/FOLDIN_FINDINGS.md`) |
| `spike/seismic_upstream/` (+ `*.patch`) | Build recipes: `seismic_150m_testbed/10_FORWARD_COMPRESSION_DESIGN.md` §7.7; portability rules: `spike/CLAUDE.md` |
| `spike/toolkit_fork/`, `spike/vectorium_fork/`, `spike/seismic_testbed_instrumented/` | Vendored/instrumented forks — see `spike/CLAUDE.md` and their READMEs |
| `spike/archive/smallmachine_levers/` | CLOSED — see the Closed tracks table |
| `spike/archive/mmap_bmp/` | `archive/sparse_engine_project/` (decision record) + `archive/qdrant_vs_lucene_assessment/MMAP_BMP_SPIKE.md` — CLOSED |
| `spike/archive/inplace_update/` (+ `patches/`, `scripts/archive/inplace_update/`) | `archive/inplace_update/` — CLOSED MEASURED 2026-09-30, see the Closed tracks table |
| `spike/archive/n2_mphf/` | its `README.md` + `seismic_150m_testbed/18_ORDINAL_ADDRESSING_DESIGN.md` §7 N2 — CLOSED MEASURED 2026-09-27 (moved 2026-10-11) |

Modules and script families:

| Code | Documentation |
|---|---|
| `source/sfu_library_mcp_server.py`, `source/sfu_library_mcp_http.py`, `source/lib/` | `THIN_CLIENT_SWAP.md`; constraints in `CODE_INVARIANTS.md` |
| `source/lib/thinclient/` | `THIN_CLIENT_SWAP.md` + `seismic_150m_testbed/` + `seismic_sequential_serving/`; `delta_layer.py` → `delta_ingest/` |
| `scripts/seismic_testbed/` | `seismic_150m_testbed/` (+ `math_optimization/`, `disk_streaming_research/`) |
| `scripts/experiments/` | `BENCHMARK_METHODOLOGY.md`, `DENSE_PARTITION_AND_ABLATION.md`, `delta_ingest/` (the fold-in and lever evals) |
| `scripts/reproduce/` | `REPRODUCIBILITY.md` |
| `scripts/gui_testbed/` | `infrastructure/GUI_INTERACTION_TESTBED_PLAN.md` |
| `scripts/portable_socsci/` | `infrastructure/PORTABLE_SOCSCI_WINDOWS_BUNDLE.md` |
| `scripts/portable_linux/` | `infrastructure/PORTABLE_LINUX_BUNDLE.md` |
| `scripts/demo_broker/` (+ `ntfy/`, the live NAS notification relay) | `infrastructure/OCI_DEMO_DEPLOYMENT.md` + `DEMO_PAYG_PLAN.md` — REOPENED 2026-10-06 |
| `scripts/repo_tools/` | `infrastructure/SCRIPT_HYGIENE_POLICY.md` (checker, symbol inventory, preflight gate, tracked hooks) + `infrastructure/REPO_REORG_2026-10-10.md` (`build_eval_results_index.py`) |
| `web/` | `THIN_CLIENT_SWAP.md` §Web GUI + `infrastructure/GUI_BAREBONES_PROGRESS_SPEC.md` / `GUI_INTERACTION_TESTBED_PLAN.md` (`infrastructure/GUI_REFERENCE.md` is historical UI research, nothing of it built) |
| `scripts/archive/demo_dependability/` | `deprecated/oci_demo/` — CLOSED DEAD 2026-09-25, see the Closed tracks table |
| `scripts/archive/deploy_opensearch_era/` (was `deploy/` until 2026-10-11) | its README + `deprecated/`; the current deployment is the OCI demo, `scripts/demo_broker/` |
| `scripts/archive/opensearch_era/`, `scripts/archive/qdrant_uint8_sparse/`, `scripts/archive/bmp_era/`, `scripts/archive/smallmachine_levers/` | `infrastructure/SCRIPT_TRIAGE_2026-10-11.md` (moved there 2026-10-11; each directory's banner names its closed track) |

## 10. Conventions

- Absolute dates only; no "today"/"recently".
- Unmeasured claims are marked `*est.*` or "IMPLEMENTED, EFFICACY UNMEASURED".
- Every live doc carries a `**Status:**` line in its first 8 lines, from the
  vocabulary `ACTIVE` / `DEFERRED <date> (<why>)` /
  `CLOSED <MEASURED|SUPERSEDED|DEAD|KILLED> <date>`.
- A closed track gets a dated `> **CLOSED …**` banner and moves to `archive/`
  (research record) or `deprecated/` (obsolete infrastructure), with its row
  moved into the Closed-tracks table above, in the same commit.
- Code comments are not documentation: constraints and gotchas recorded from
  code live in the module's doc (section 2 and the maps above), per the
  2026-09-01 no-internal-comments policy.
- `src/` became `source/` and `web/src/` became `web/source/` on 2026-10-13
  (`infrastructure/REPO_REORG_2026-10-10.md` §Addendum 2026-10-13). Every doc
  and record dated before that names the old
  paths; read `src/` as `source/` there.
- `archive/` holds research records (how a decision was reached);
  `deprecated/` holds obsolete infrastructure docs (OpenSearch era, closed
  demo plans). Their READMEs list what is there and why it is kept.
