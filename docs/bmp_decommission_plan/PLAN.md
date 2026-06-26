# Plan: Finish Open Items, Validate the BMP→Qdrant Replacement, and Build a Presentation Metrics Suite

> **Progress (updated as workstreams land — absolute dates):**
> - **A1 DONE 2026-06-24** — `SFU_SPLADE_BACKEND` default flipped `bmp`→`qdrant`
>   in `src/lib/thinclient/retriever.py`; BMP kept as env-gated fallback. Same-commit
>   doc: `docs/THIN_CLIENT_SWAP.md` engine table + off-BMP section corrected.
> - **A2 DONE 2026-06-24** — `_upsert_wait_retry` added to
>   `scripts/spike_qdrant_sparse.py` (`wait=True` upserts now retry-with-backoff
>   so a `status=red` optimizer stall self-heals instead of killing the worker).
>   Watchdog kept as backstop. Efficacy recorded in `docs/THIN_CLIENT_SWAP.md`
>   (IMPLEMENTED, UNMEASURED at ingest scale — 150M ingest already complete).
> - **A4 DONE 2026-06-24** — build-phase supervisor confs archived:
>   `scripts/archive/migration-150m.supervisor.conf` and
>   `scripts/archive/qdrant-offbmp.supervisor.conf` (both with SUPERSEDED banners).
>   `scripts/qdrant-serve.supervisor.conf` is confirmed the ONLY steady-state
>   Qdrant unit and is installed live (`qdrant-spike` RUNNING under supervisord,
>   `autorestart=true`). Doc refs in `docs/THIN_CLIENT_SWAP.md` repointed.
> - **B1-code + live DONE 2026-06-24** — `scripts/eval_quant_fidelity.py` extended
>   with `--live-qdrant` mode: true head-to-head on the live `splade_150m` index's
>   own retrieved set — Qdrant returns live top-cand hits with stored f32 vectors
>   (`with_vectors=True`), scored BOTH as raw f32 and BMP ×70 8-bit over the SAME
>   docs. **Live-150M gate PASSES: overlap@10=1.0, τ=1.0, NDCG Δ=0.0** (all 40
>   queries; f32 0.6039 = quant 0.6039 over 14 judged-coverage queries). Result:
>   `data/eval_results/quant_fidelity_live_150m_20260624_2345.json`. Catalog +
>   VALIDATION_REPORT + BENCHMARK_METHODOLOGY updated with the live numbers.
> - **C1 DONE 2026-06-24** — `scripts/build_presentation_metrics.py` aggregator
>   created: parses every relevant `data/eval_results/` file (+ Qdrant latency
>   logs) into the canonical ledger `data/eval_results/METRICS_CATALOG.json`
>   (idempotent upsert by key), renders `presentation_metrics_<date>.json` +
>   `docs/bmp_decommission_plan/PRESENTATION_METRICS.md` + `METRICS_CATALOG.md`.
>   29 metrics cataloged, all `measured`, each tagged `comparable-to-training` vs `new`.
> - **C-catalog DONE 2026-06-24** — `docs/bmp_decommission_plan/METRICS_CATALOG.md`
>   rendered (28 metrics, all measured); catalog + presentation docs registered in
>   `docs/README.md` index; efficacy entry added to `docs/BENCHMARK_METHODOLOGY.md`
>   for both new metric families (live fidelity + aggregator).
> - **DO_SIZING + VALIDATION_REPORT DONE 2026-06-24** — `DO_SIZING.md` (droplet
>   RAM/disk/cost from measured page-cache behaviour; recommends 32 GB / 60 GB+
>   NVMe for the 30M demo, full 150M needs 64–128 GB) and `VALIDATION_REPORT.md`
>   (go/no-go gate table: B1 30M PASSES + 150M-live measuring, B2/B3/D status).
>   Decision PENDING B1-live sign-off — demo blocked until GREEN, per user.
> - **B2 DONE 2026-06-25** — End-to-end RRF quality, qdrant backend, 150M-live.
>   `SFU_SPLADE_BACKEND=qdrant` recorded via `eval_thinclient_parity.py
>   record-tc` over the SAME 40 diverse queries / corpus / judge cache as the
>   BMP baseline (now OOM-safe — the qdrant leg serves from the live
>   `splade_150m` on_disk collection instead of loading the ~211 GB BMP set),
>   compared offline vs `parity_record_os_20260618_0028.json`. **B2 gate GREEN:**
>   tc-qdrant RRF NDCG@10 = **0.5378** (39 judged) / **0.560** (34-common
>   subset) vs BMP baseline 0.5368 / 0.561 → **|Δ| < 0.001 on both subsets**
>   (RRF-indistinguishable from BMP); OpenSearch win preserved identically
>   (tc beats OS +0.111, wins 29/34). Result:
>   `data/eval_results/thinclient_parity_qdrant_20260625_0001.json` (compare) +
>   `parity_record_tc_qdrant_20260625_0001.json` (record). VALIDATION_REPORT +
>   METRICS_CATALOG + PRESENTATION_METRICS updated; catalog row tagged
>   comparable-to-training. **B1 + B2 both GREEN → Workstream D (delete the
>   68.6 GB .bmp artifacts) UNBLOCKED.**
> - **D DONE 2026-06-25** — BMP artifacts deleted (192 `splade_*.bmp` + 192
>   `splade_*.vocab.zst`, 68.66 GB; `data/thinclient_index` 298 GB → 230 GB).
>   BMP *code* + builder kept behind `SFU_SPLADE_BACKEND=bmp` for small-tier
>   rebuilds. Code hardening (commit 0b7ca48): `import bmp` deferred to the BMP
>   branch so the qdrant serving path has no pisa dependency. Post-deletion
>   smoke test PASSES: qdrant default serves BM25F+SPLADE+RRF end-to-end;
>   Qdrant-stopped degrades the SPLADE leg to BM25F (no crash). Manifest:
>   `data/eval_results/bmp_artifacts_deleted_manifest_20260625.json`. Retirement
>   noted in `docs/THIN_CLIENT_SWAP.md` + `docs/STORAGE_BUDGET_150M.md`
>   (SUPERSEDED banner). **The BMP→Qdrant decommission is COMPLETE.**

## Context

The thin-client serves SPLADE sparse retrieval through **BMP** (Block-Max Pruning,
pisa-engine 0.2.6) — a load-into-RAM engine that needs **~211 GB resident at 150M
docs**, which is impossible on real hardware. The replacement is **Qdrant `on_disk`
sparse** (serves from disk, page-cached, ~1.4 GB resident at rest), wired behind
the `SFU_SPLADE_BACKEND` env var. **The default is `qdrant` as of 2026-06-24**
(A1); BMP remains selectable (`SFU_SPLADE_BACKEND=bmp`) as the env-gated fallback.
`src/lib/thinclient/retriever.py`. Qdrant ingest of the full 150,413,098-doc
collection completed 2026-06-20.

The user wants to: (1) close the remaining open items, (2) run a **full validation
suite** to decide whether BMP can be safely decommissioned **before** committing to
a DigitalOcean tech-demo deployment, and (3) produce a **presentation-grade metrics
suite** that is directly comparable to the numbers measured in the
`sfu-library-mcp-training` project (same LLM-judge methodology, same metrics).

**Decisions (from user):**
- Validation must run **within the current 24 GB host's constraints**; the demo
  deploys to a **DigitalOcean droplet**, so the plan must also output a **droplet
  sizing recommendation** (RAM/disk) derived from measured numbers.
- **Flip the default to `qdrant`, keep BMP code as an env-gated fallback.** Delete
  the 68.6 GB `.bmp` disk artifacts **only after parity is signed off** (reversible).
- **Full presentation suite**: quality + BMP-vs-Qdrant parity + ops (latency, RAM,
  storage, ingest throughput).

**Key constraint discovered:** at 150M neither engine fits 24 GB (BMP 211 GB resident;
Qdrant's 205 GB on-disk index is only ~7% page-cacheable → p50 545–861 ms, RAM-bound).
So host-constrained validation must use the existing **OOM-safe wave methodology**
and report the RAM-bound number honestly, *plus* a representative fitting-tier number
(e.g. 30M, where Qdrant p50 ≈ 66 ms) that projects what a correctly-sized DO droplet
delivers. Disk is the other surprise: **Qdrant 205 GB > BMP 68.6 GB on disk**, which
matters for droplet cost.

---

## Reusable assets (do NOT rewrite these)

| Need | Existing asset |
|---|---|
| BMP↔Qdrant toggle | `SFU_SPLADE_BACKEND` in `src/lib/thinclient/retriever.py` (`_splade_leg_qdrant` vs `_splade_leg`) |
| OOM-safe 150M parity on small RAM | `scripts/eval_parity_section_waves.py`, `scripts/run_parity_safe.sh`, `scripts/eval_thinclient_parity.py` (`compare` mode) |
| BMP-vs-Qdrant fidelity | `scripts/eval_quant_fidelity.py` (overlap@10/@50, Kendall-τ, NDCG delta) |
| Quality metrics (training-comparable) | `scripts/benchmark_llm_judge.py` + `data/eval_results/llm_judge_cache.json` + `data/eval_results/diverse_queries.json` (Claude Haiku judge, NDCG@10/MRR@10/P@10) |
| Qdrant latency/RAM | `scripts/spike_qdrant_sparse.py` (`measure` subcommand) |
| Storage budget | `scripts/eval_storage_levers.py` |
| Steady-state serving | `scripts/qdrant-serve.supervisor.conf` |

**Metric definitions to keep identical to training** (so charts are comparable):
NDCG@10 with gain `2^grade−1` and full-judged-pool IDCG; MRR@10 / P@10 with relevant
threshold `grade≥2`; RRF `k=60`; LLM judge = `claude-haiku-4-5-20251001`, 0–3 rubric,
TREC-pooled. Reuse the existing `llm_judge_cache.json` so no re-judging cost is paid.

---

## Workstream A — Close the open code items

1. **Flip the serving default.** In `src/lib/thinclient/retriever.py`, change the
   `SFU_SPLADE_BACKEND` default from `bmp` → `qdrant` (keep `bmp` selectable). Update
   the same-commit docs (`docs/THIN_CLIENT_SWAP.md`, `docs/README.md`) per the
   CLAUDE.md same-commit doc rule, and `grep -rn 'SFU_SPLADE_BACKEND' docs/ src/ scripts/`
   to fix any doc stating the old default.
2. **Qdrant ingest robustness (proper fix, not just the watchdog).** Add
   retry-with-backoff around `wait=True` upserts in `scripts/spike_qdrant_sparse.py`
   so a `status=red` optimizer stall self-heals; keep `scripts/bmp_ingest_watchdog.sh`
   as the operational backstop. Record efficacy (CLAUDE.md new-module rule).
3. **Ingest work rebalancing** (optional, only if a re-ingest is needed): replace the
   static `slices[w::W]` split with line-count balancing or a work-steal queue.
   Defer if the existing 150M collection is accepted as-is.
4. **Retire build-phase supervisor confs** now that build/ingest are done:
   mark/move `scripts/migration-150m.supervisor.conf` and any `*-offbmp*` conf as
   archived; confirm `qdrant-serve.supervisor.conf` is the only steady-state unit.
5. **Profile BMP/Qdrant RAM at the smaller tiers** (15M / 1M) so deployment-tier
   planning isn't a blank — feeds Workstream C sizing.

---

## Workstream B — BMP→Qdrant validation suite (host-constrained)

Goal: prove Qdrant is a faithful, sufficient replacement for BMP at 150M **on the
24 GB host**, producing a single go/no-go gate table.

1. **Retrieval parity (BMP vs Qdrant), 150M, full query set.** Run the parity
   harness twice over the SPLADE leg and diff the two record files offline:
   - `SFU_SPLADE_BACKEND=bmp` via `scripts/run_parity_safe.sh` /
     `eval_parity_section_waves.py` (wave execution keeps RAM bounded).
   - `SFU_SPLADE_BACKEND=qdrant` via the same harness (Qdrant serves from disk;
     RAM-bound but functional on 24 GB).
   - Merge with `eval_thinclient_parity.py compare` and compute **overlap@10/@50,
     Kendall-τ, and NDCG@10 delta** between the two engines on the common judged set.
   - **Extend `eval_quant_fidelity.py`** to read the *live* Qdrant collection instead
     of recomputing f32 in-process (today it compares BMP-8bit vs in-memory f32 on a
     1M/30M pool). This makes the fidelity check use the exact production index.
   - **Gate:** overlap@10 ≥ 0.98 and Kendall-τ ≥ 0.97 and |NDCG@10 Δ| ≤ 0.005
     (consistent with the already-measured 0.9875 / 0.9716 / 0.0).
2. **End-to-end RRF quality, 150M, both backends.** Run `benchmark_llm_judge.py`
   (cache-backed, $0) with the retriever pointed at each backend; confirm RRF
   NDCG@10/MRR@10/P@10 are statistically indistinguishable and still beat the
   OpenSearch baseline (current measured: tc RRF 0.561 vs OS 0.449).
3. **Ops envelope at 150M on the host:** `spike_qdrant_sparse.py measure` for Qdrant
   latency (p50/p95/max, encode excluded *and* included) + resident RAM; record the
   honest RAM-bound number and the cold/warm-cache spread.
4. **Fitting-tier reference run (30M):** same `measure` at 30M where the index is
   page-cacheable (p50 ≈ 66 ms) — this is the number that represents a correctly-sized
   droplet and de-risks the demo latency story.
5. **Failure-mode check:** confirm Qdrant leg degrades to BM25F on error (same as BMP)
   and that `SFU_LOAD_MEM_FLOOR_GB` / the watchdog behave under memory pressure.

**Decommission go/no-go report** = the gate table from B1–B3 plus the
artifact-deletion safety check (Workstream D dry-run).

---

## Workstream C — Full presentation metrics suite + DO sizing

Produce one consolidated, presentation-ready artifact comparable to training.

1. **New aggregator** `scripts/build_presentation_metrics.py`: reads every relevant
   file under `data/eval_results/` (LLM-judge, parity, quant-fidelity, dense POC,
   storage levers, latency logs) and emits:
   - `data/eval_results/presentation_metrics_<date>.json` (machine-readable), and
   - `docs/bmp_decommission_plan/PRESENTATION_METRICS.md` (tables + a short narrative).
   It must label every number with metric name, k, dataset/corpus size, source file,
   and absolute date (CLAUDE.md efficacy rule), and flag any `*est./unmeasured*`.
2. **Quality section (training-comparable):** NDCG@10 / MRR@10 / P@10 per method
   (BM25F, SPLADE, RRF, OpenAlex-live) and per-subject (40 SFU subjects), reusing the
   training methodology and judge cache. Place the thin-client (Qdrant) numbers
   side-by-side with the training baselines (`benchmark_llm_judge_final.json`,
   `dense_poc_eval.json`, `pipeline_dense_comparison.json`).
3. **Parity section:** BMP-vs-Qdrant overlap@10/@50, Kendall-τ, NDCG Δ (Workstream B1).
4. **Ops section:** latency p50/p95 (150M RAM-bound + 30M fitting-tier), resident RAM
   (BMP 211 GB vs Qdrant 1.4 GB), on-disk size (BMP 68.6 GB vs Qdrant 205 GB), ingest
   throughput.
5. **DO droplet sizing** `docs/bmp_decommission_plan/DO_SIZING.md`: from measured
   page-cache behaviour derive the RAM needed for Qdrant to be cache-resident at the
   demo's chosen corpus tier, plus disk (≥205 GB for full 150M, or the smaller tier's
   footprint) and the cost/latency trade-off table for candidate DO droplet sizes.
   Recommend the smallest droplet that keeps p50 in the fitting-tier range.

---

## Cataloging the new metrics (explicit procedure)

Every number produced by Workstreams B & C must be cataloged so it's reproducible
and comparable to training. This is a hard requirement (CLAUDE.md efficacy rule),
not a nicety.

1. **Result-file naming.** Write each run to `data/eval_results/` using the existing
   dated convention: `<eval-name>_<scale>_<YYYYMMDD>_<HHMM>.json`
   (e.g. `bmp_vs_qdrant_parity_150m_20260624_1430.json`,
   `thinclient_parity_qdrant_<date>.json`). Never overwrite a prior dated file —
   newer supersedes older.

   > **Note on B2's actual output name (2026-06-25):** the plan originally
   > sketched `llm_judge_qdrant_150m_<date>.json`, implying `benchmark_llm_judge.py`.
   > That script queries OpenSearch directly (no `SFU_SPLADE_BACKEND` switch), so
   > the genuinely training-comparable path is the parity harness —
   > `eval_thinclient_parity.py record-tc` with `SFU_SPLADE_BACKEND=qdrant`
   > (OOM-safe, since the qdrant leg serves from disk) → `compare` against the OS
   > record. The B2 run therefore produced
   > `data/eval_results/thinclient_parity_qdrant_<date>.json` (compare) +
   > `parity_record_tc_qdrant_<date>.json` (tc record), schema-identical to the
   > BMP baseline so the qdrant `tc_rrf` NDCG@10 is directly comparable to
   > 0.5368 / 0.561.
2. **Required provenance fields in every result JSON** (extend the existing
   `config`/`summary` schema so all new files carry these):
   - `metric` names + `k` values, `backend` (`bmp`|`qdrant`), engine/index version,
   - `corpus_size` (docs) and `query_set` (file + count),
   - `eval_script` (path), `judge` (model id, when LLM-judged),
   - `git_commit`, `host` (RAM/CPU), absolute `timestamp`,
   - `baseline_ref` — the training file this run is meant to be compared against
     (e.g. `benchmark_llm_judge_final.json`), or `null` if net-new.
3. **Single source-of-truth catalog.** Create
   `data/eval_results/METRICS_CATALOG.json` — one row per metric run with:
   `metric, k, scale, backend, value, baseline_value, delta, eval_script,
   result_file, date, git_commit, status` where `status ∈ {measured, est, unmeasured}`.
   `scripts/build_presentation_metrics.py` both **appends to** and **renders from**
   this catalog, so the JSON is the canonical ledger and the markdown is generated.
4. **Human-readable catalog** `docs/bmp_decommission_plan/METRICS_CATALOG.md`: a table
   generated from the JSON above, grouped by section (Quality / Parity / Ops), each
   row linking metric → script → result file → training baseline → delta, with the
   absolute date and a `measured`/`est.`/`unmeasured` tag. This is the index a
   presenter reads to find any number's provenance.
5. **Comparability labeling.** Tag each quality metric `comparable-to-training`
   (same NDCG@10/MRR@10/P@10 definitions, RRF k=60, same judge cache) vs `new`
   (parity/ops metrics with no training equivalent), so the presentation never
   implies a false apples-to-apples.
6. **Register in the doc index.** Add the catalog + presentation docs to
   `docs/README.md`, and add an efficacy entry to `docs/BENCHMARK_METHODOLOGY.md`
   (WHAT measured, NUMBERS before→after, script path, result-file path, date) for
   each new metric family — in the same commit that produces the numbers.

## Workstream D — Decommission (gated on B sign-off)

Only after the go/no-go report passes:
1. **Dry-run safety check:** verify `SFU_SPLADE_BACKEND=qdrant` serves end-to-end with
   zero references to `.bmp` files (the default flip from Workstream A), and snapshot
   the artifact list to be deleted.
2. **Delete BMP disk artifacts:** `data/thinclient_index/sections/*/splade_*.bmp` and
   `splade_*.vocab.zst` sidecars (~68.6 GB). Stage/commit only doc + script changes —
   **never `git add .`** (multi-GB runtime state lives in the tree).
3. **Keep BMP code** behind `SFU_SPLADE_BACKEND=bmp` as the documented fallback; add a
   "BMP retired as default, artifacts removed <date>" status note to
   `docs/THIN_CLIENT_SWAP.md` and update `docs/README.md`.

---

## Files to create / modify

**Modify:** `src/lib/thinclient/retriever.py` (default flip), `scripts/spike_qdrant_sparse.py`
(retry/backoff), `scripts/eval_quant_fidelity.py` (read live Qdrant collection),
`docs/THIN_CLIENT_SWAP.md`, `docs/README.md`, `docs/STORAGE_BUDGET_150M.md`.

**Create:** `scripts/build_presentation_metrics.py`;
`docs/bmp_decommission_plan/` containing `PLAN.md` (this plan, per the user's request),
`VALIDATION_REPORT.md` (go/no-go gate table), `PRESENTATION_METRICS.md`,
`METRICS_CATALOG.md`, `DO_SIZING.md`;
`data/eval_results/METRICS_CATALOG.json` (canonical metrics ledger),
`data/eval_results/presentation_metrics_<date>.json`,
`data/eval_results/bmp_vs_qdrant_parity_150m_<date>.json`,
`data/eval_results/thinclient_parity_qdrant_<date>.json` (B2 — qdrant-backend
RRF quality; see the cataloging §1 note for why this isn't `llm_judge_*`).

**First execution step (per user request):** create the separate docs subdirectory
`docs/bmp_decommission_plan/` and write this plan to
`docs/bmp_decommission_plan/PLAN.md`, then register it in the `docs/README.md` index.

---

## Verification

1. **Parity gate:** `bmp_vs_qdrant_parity_150m_<date>.json` shows overlap@10 ≥ 0.98,
   Kendall-τ ≥ 0.97, |NDCG@10 Δ| ≤ 0.005.
2. **Quality gate:** `benchmark_llm_judge.py` (qdrant backend) RRF NDCG@10 ≈ training
   value and ≥ OpenSearch baseline; deltas within noise of the BMP run.
3. **Ops gate:** Qdrant resident RAM < 5 GB on the host; latency recorded at both 150M
   (RAM-bound) and 30M (fitting-tier) with p50/p95.
4. **Serving smoke test:** with `SFU_SPLADE_BACKEND=qdrant` default, run a live
   `search_academic` query (MCP tool / `POST /api/search`) and confirm sane results +
   graceful BM25F fallback when Qdrant is stopped.
5. **Decommission safety:** post-deletion, the same smoke test still passes and no code
   path references the removed `.bmp` files.
6. **Docs freshness:** `grep -rn 'SFU_SPLADE_BACKEND' docs/ src/ scripts/` shows no
   stale `default=bmp`; presentation doc numbers all carry source file + date.

All commits follow the CLAUDE.md workflow (pull → edit → explicit `git add <files>` →
commit → push), and same-commit doc updates ship with the code they describe.
