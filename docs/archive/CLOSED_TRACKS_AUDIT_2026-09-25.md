# Closed-tracks audit — 2026-09-25

> **CLOSED MEASURED 2026-09-25** — this is the one-shot audit record that drove
> the 2026-09-25 closed-tracks sweep (policy: `.claude/CLAUDE.md` §"MANDATORY:
> Closed tracks"). It is a historical record, not a live tracker; the live index
> is `docs/README.md` and the enforcement is `scripts/tests/test_doc_status.py`.

**Status:** CLOSED MEASURED 2026-09-25

Every `.md` under `docs/` outside `archive/`/`deprecated/` as of the audit, every
folder under `spike/`, and `scripts/demo_broker/` + `scripts/demo_dependability/`,
classified `ACTIVE` / `DEFERRED` / `CLOSED(kind, date)` with one line of evidence.
Paths are the **pre-sweep** paths; the "moved to" column records where the sweep
put them (Phase 2 of the same session).

Vocabulary: `ACTIVE` · `DEFERRED <date> (<why>)` · `CLOSED <MEASURED|SUPERSEDED|DEAD|KILLED> <date>`.

## Counts

Verified after the sweep landed (2026-09-25):

| Class | docs/*.md | spike/ folders | scripts/ dirs | Total |
|---|---|---|---|---|
| ACTIVE | 54 | 6 | 0 | 60 |
| DEFERRED | 32 | 1 | 0 | 33 |
| CLOSED | 36 | 2 | 2 | 40 |
| **Total** | **122** | **9** | **2** | **133** |

`docs/*.md` counts every file including subdirectory `README.md`s. The 122 = 89
live docs (54 ACTIVE + 32 DEFERRED + 3 still owned by agent M and therefore
unlabelled) plus the 33 closed by this sweep (5 to `deprecated/oci_demo/`, 29 to
`archive/<track>/`) — `MASTER_TODO.md` and the pre-existing `archive/` and
`deprecated/` contents are counted once, under CLOSED. `spike/archive/mmap_bmp/`
was already closed before the sweep.

## CLOSED — moved by this sweep

| Path (pre-sweep) | Class | Evidence | Moved to |
|---|---|---|---|
| `docs/infrastructure/OCI_DEMO_DEPLOYMENT.md` | CLOSED DEAD 2026-09-25 | own banner "STATUS 2026-09-25: CLOUD ACCESS ENDED … gone and will not return" | `docs/deprecated/oci_demo/` |
| `docs/infrastructure/OCI_FREE_TIER_RESIDENT_DEMO.md` | CLOSED DEAD 2026-09-25 | own banner: "Every item here is **CLOSED-UNRUNNABLE**, not pending" | `docs/deprecated/oci_demo/` |
| `docs/infrastructure/DEMO_PAYG_PLAN.md` | CLOSED DEAD 2026-09-25 | own banner: "Every open item in this doc is **CLOSED-UNRUNNABLE** … no host left" | `docs/deprecated/oci_demo/` |
| `docs/infrastructure/HYBRID_DEMO_DEPLOYMENT.md` | CLOSED DEAD 2026-09-25 | own banner: DO droplets + the E5 host that superseded this plan are both gone | `docs/deprecated/oci_demo/` |
| `docs/infrastructure/DEMO_DEPENDABILITY.md` | CLOSED DEAD 2026-09-25 | own banner: cloud tier CLOSED-UNRUNNABLE; broker dormant | `docs/deprecated/oci_demo/` |
| `docs/bmp_decommission_plan/` (6 docs) | CLOSED SUPERSEDED 2026-07-06 | its `README.md`: "Historical track … Superseded in spirit by the later SEISMIC promotion"; `DO_SIZING.md` SKU tables CLOSED-UNRUNNABLE 2026-09-25 | `docs/archive/bmp_decommission_plan/` |
| `docs/qdrant_uint8_sparse/` (2 docs) | CLOSED SUPERSEDED 2026-09-25 | its `README.md`: "**SUPERSEDED 2026-09-25** … the question this folder asks is moot. Not current; do not resume" | `docs/archive/qdrant_uint8_sparse/` |
| `docs/qdrant_vs_lucene_assessment/` (10 docs) | CLOSED SUPERSEDED 2026-07-06 | its `README.md` status note 2026-09-01: "predates the SEISMIC promotion — since 2026-07-06 the served SPLADE backend is SEISMIC" | `docs/archive/qdrant_vs_lucene_assessment/` |
| `docs/sparse_engine_project/` (11 docs) | CLOSED MEASURED 2026-06-26 | its `README.md`: "KILLED → RE-OPENED → **MEASURED & STOPPED (2026-06-26)**"; verdict STOP in `07_INTEGRATION_PLAN.md` §8 | `docs/archive/sparse_engine_project/` |
| `spike/smallmachine_levers/` | CLOSED DEAD 2026-09-25 | `PREREGISTRATION.md`: "**CLOSED-UNRUNNABLE 2026-09-25 — this pre-registration can never be frozen**"; bars S1–S5 derive from the gone OCI 14.8 GB floor | `spike/archive/smallmachine_levers/` |
| `scripts/demo_broker/` | CLOSED DEAD 2026-09-25 | `docs/README.md` module map: "**DORMANT 2026-09-25: cloud access ended, no instance to start/stop/pin/reap**"; no live serving path imports it | `scripts/demo_broker/` |
| `scripts/demo_dependability/` | CLOSED DEAD 2026-09-25 | `DEMO_DEPENDABILITY.md` banner: cloud tier dead, broker dormant; only importer is `scripts/tests/test_demo_payload_manifest.py` (kept running, repointed) | `scripts/archive/demo_dependability/` |
| `docs/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` | CLOSED SUPERSEDED 2026-09-25 | Q1-Q11 all decided; `docs/README.md`'s Active tables are the only index of open work. Its four STILL-OPEN items (Q10, H5, absolute nDCG for the dv leg, E3) were re-homed into `docs/README.md` §"Still open — Active backlog" first | `docs/archive/seismic_150m_testbed/` |
| `docs/archive/MASTER_TODO.md` | CLOSED SUPERSEDED 2026-09-25 | already in `archive/` but unbannered and still reads "Last updated: 2026-06-05" like a live tracker | banner added in place |

## Borderline — Status line only, NOT moved

| Path | Class | Evidence |
|---|---|---|
| `docs/THIN_CLIENT_SWAP.md` | ACTIVE | canonical architecture doc; §"What runs here now" is the premise check for all triage |
| `docs/archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md` | ACTIVE | records the promoted engine (SEISMIC default since 2026-07-06) |
| `docs/STORAGE_BUDGET_150M.md` | ACTIVE | measured storage ledger, cited by `docs/README.md` Active table |
| `docs/LEXICAL_STORAGE_RESEARCH.md` | ACTIVE | measured lever matrix behind the storage budget |
| `docs/BENCHMARK_METHODOLOGY.md` | ACTIVE | the LLM-judged NDCG@10 method every quality verdict is judged under |
| `docs/CODE_INVARIANTS.md` | ACTIVE | live constraint ledger for `src/` (no-comments policy 2026-09-01) |
| `docs/CODE_INVARIANTS_SCRIPTS.md` | ACTIVE | same for `scripts/`, `deploy/` |
| `docs/ENV_GATES.md` | ACTIVE | live `SFU_*`/`DEMO_*` gate reference |
| `docs/EXTERNAL_API_CONTRACT.md` | ACTIVE | live OpenAlex/S2/arXiv client rules |
| `docs/THIN_CLIENT_STACK_RESEARCH.md` | ACTIVE | engine-selection evidence base still cited by `THIN_CLIENT_SWAP.md`; not a closed question, a settled one kept as reference |
| `docs/LOCALIZED_DEPLOYMENT_PLAN.md` | ACTIVE | own note: "Partially superseded / partially implemented"; §2 "Subset" tier is the live contract for `infrastructure/PORTABLE_STACK_MANIFEST.md` |
| `docs/ABSTRACT_SIDECAR_BACKFILL.md` | DEFERRED 2026-08-18 | own header: "DESIGN ONLY, NOTHING BUILT — DEFERRED by operator decision 2026-08-18" |
| `docs/math_optimization/` (10 docs) | DEFERRED 2026-09-25 | `07_M2_IMPLEMENTATION_RESULTS.md`: "M2 IMPLEMENTED, CORRECT, FASTER — but FAILS the pre-registered bar" → not promoted; M6–M10 pre-registered, unfrozen |
| `docs/disk_streaming_research/` (4 docs) | DEFERRED 2026-09-25 | `docs/README.md`: "F1–F6 hooks (built, env-gated off)" — built but not promoted |
| `docs/seismic_150m_testbed/` (21 docs + 5 build plans) | ACTIVE / DEFERRED per doc | documents the SERVED engine (E5/E8 dv-v2 layout, docs 13/14); design-only members (`02_`, `10_`, `13_`, `build_plans/02–04`) are DEFERRED |
| `docs/seismic_sequential_serving/` (7 docs) | DEFERRED 2026-07-16 | measured 2026-07-16 (peak RssFile 0.023×, warm p50 5.29× parallel) but not promoted — parallel federation still served |
| `docs/semantic_docid_ingest/` (7 docs) | DEFERRED 2026-09-25 | every member's own header: "Status: DESIGN ONLY" / "PROPOSED"; `docs/README.md`: "DESIGN ONLY, no code" |
| `docs/session_2026-07-14_f6_corrections_r1_ladder/` (7 docs) | ACTIVE | the convergence artifact is the live evidence base the ACTIVE `spike/convergence_repro/` reproduces; `docs/README.md` carries its 2026-09-25 addendum |
| `docs/infrastructure/` non-demo (12 docs) | ACTIVE | GUI specs (wave-5/6 contracts), portable bundles (`PORTABLE_SOCSCI_WINDOWS_BUNDLE.md` = SHIPPED 2026-08-08), `POMMEL_ACCESS.md` (cited by `.claude/CLAUDE.md`) |
| `spike/convergence_repro/` | ACTIVE | DRAFT pre-registrations awaiting freeze (`PREREGISTRATION_WSL2_REHOST.md`, `PREREGISTRATION_TIER1E.md`) |
| `spike/ebpf_pagecache/` | DEFERRED 2026-09-25 | own README: "COMPILES … LOAD IMPOSSIBLE on this host — no cache_ext kernel AND no CAP_BPF … NOTHING MEASURED" — blocked on kernel/caps, not decided against |
| `spike/bm25_seismic/` | ACTIVE | evidence for `seismic_150m_testbed/17_BM25_THROUGH_SEISMIC_SPIKE.md` (spike COMPLETE, measured) |
| `spike/meta_consolidation/` | ACTIVE | evidence for `seismic_150m_testbed/18_ORDINAL_ADDRESSING_DESIGN.md`; ordinals are an opt-in live filter stage |
| `spike/seismic_upstream/` (+ `*.patch`) | ACTIVE | `spike/CLAUDE.md`: "the LIVE seismic Rust fork" — builds the served `.so` |
| `spike/seismic_testbed_instrumented/`, `spike/toolkit_fork/`, `spike/vectorium_fork/` | ACTIVE | `spike/CLAUDE.md`: "live" |
| `spike/archive/mmap_bmp/` | CLOSED MEASURED 2026-06-26 | `spike/CLAUDE.md`: "the killed BMP spike (STOPPED 2026-06-26) … Do not resurrect or delete" — already archived |

## Notes recorded during the audit

- `docs/infrastructure/GUI_REFERENCE.md` is marked HISTORICAL in its own banner
  (early fork research, nothing built) but is a non-demo infrastructure doc
  and was left in place per the sweep's scope. It is a candidate for
  `docs/archive/` in a future pass.
- `docs/infrastructure/REPO_AUDIT_2026-07-17.md` is a point-in-time audit whose
  mass moves were "deliberately deferred to a dedicated session". This sweep is
  part of that deferred work; the doc is kept ACTIVE as the standing plan.
- The **in-container half** of `demo_dependability/` (staging serve, leg breaker,
  load driver, soak) still runs locally — its measured numbers stand. It was
  archived because its deployment target is gone and no live serving path
  imports it, per `.claude/CLAUDE.md` §"Closed tracks" rule (5).
