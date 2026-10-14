# Completed plans — ledger (moved here 2026-07-10)

Every plan in this directory is FINISHED (executed and recorded) or
SUPERSEDED (its content promoted into the docs tree). The canonical record
of each outcome lives in the docs named below — these plans are kept for
history only and are NOT current. Do not answer questions from them without
checking the named doc first (house source-of-truth hierarchy applies).

Active plans stay in `.claude/plans/` (the parent directory).

| Plan | Verdict | Canonical record |
|---|---|---|
| `seismic-testbed-p1-p2.md` | DONE — P1 persona build + P2 deciding gates measured | `docs/seismic_150m_testbed/04`, `06_FINDINGS.md` |
| `seismic-c1-mmap-spike.md` | DONE — C1a mmap validation spike passed | `docs/seismic_150m_testbed/07_G3_RAM_FIX_PLAN.md` §4 |
| `seismic-c2-metadata-mmap-close.md` | DONE — C1a metadata floor gaps closed | doc 07 §4 |
| `seismic-c25-pyo3-mmap-binding.md` | DONE — `MmapSeismicIndex` pyo3 reader shipped; 150M serve unblocked | doc 07, `docs/THIN_CLIENT_SWAP.md` |
| `seismic-g6-rrf-parity.md` | DONE — G6 RRF system-level parity recorded | doc 06 |
| `seismic-centroid-sweep-and-ram-verify.md` | DONE — G2 centroid sweep + G7 RAM requirement verified | doc 06 |
| `seismic-plan01-sharded-federation.md` | DONE — 8-shard build + federated query shipped | `build_plans/01_*`, doc 06 |
| `seismic-g6-fullcorpus-federated-150m.md` | DONE — full-corpus federated G6 parity measured | doc 06 |
| `seismic-promote-sharded-backend-and-run-g8.md` | DONE — backend promoted into served package; G8 recorded; `SFU_SPLADE_BACKEND` default flipped 2026-07-06 | doc 12 §4, `docs/THIN_CLIENT_SWAP.md` |
| `seismic-sequential-serving-impl.md` | DONE — sequential serving mechanism A shipped | `docs/seismic_sequential_serving/` |
| `seismic-two-method-split-opt3.md` | DONE — `ParallelSeismicBackend`/`SequentialSeismicBackend` class split shipped | `docs/seismic_sequential_serving/01` |
| `seismic-sequential-mechanism-B-rebuild.md` | DONE — mechanism B (`MADV_DONTNEED`) .so rebuild shipped, parallel path intact | `docs/seismic_sequential_serving/` |
| `seismic-completion-tier0-first.md` | DONE — Tier 0 items + rebuild completed | doc 06 |
| `seismic-e7-reclear-fixes.md` | DONE — gate b PASS (native rebuild); gate c CLOSED as superseded by E7b dv promotion | `docs/math_optimization/00`, doc 10 §7.4–7.5 |
| `seismic-open-items-and-compression.md` | SUPERSEDED — tracker role replaced by the execution roadmap | `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` |
| `seismic-only-dev-container-and-archive-split.md` | SUPERSEDED (own banner, 2026-07-06) — promoted into the docs tree | `docs/archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md` |
| `q1-e8-dvv2-perdoc-scale.md` | DONE — E8 dv-v2 Stage 1 GO 2026-07-10, all 4 bars PASS + post-GO validation (NaN guard) | doc 12 §3 Q1; successor: `e8-stage2-host-dvv2-serve.md` |
| `e8-stage2-host-dvv2-serve.md` | DONE — E8 dv-v2 Stage 2 full-corpus rollout + operator-signed serve flip, served since 2026-07-14 (moved here 2026-10-11) | `docs/THIN_CLIENT_SWAP.md` §SPLADE leg; `data/eval_results/_e8s2_q7_federated_v2_20260713.json` |
| `m8-register-blocked-kernel.md` | CLOSED 2026-08-10 — M8 MEASURED: gate c REVERT; kernel stays in-tree default OFF (row added 2026-10-11) | `docs/math_optimization/08_FURTHER_MATH_CANDIDATES.md` §M8 |
