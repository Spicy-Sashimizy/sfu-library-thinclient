# Plan: G6 full-corpus RRF parity — federated mmap'd 150M SEISMIC leg

## Goal

Measure the gate that the entire C2.5 / Plan-01 effort was built to enable:
**G6 RRF system-level parity at full-corpus scale** — `RRF(BM25F, SEISMIC-150M-splade)`
vs the stored `RRF(BM25F, Qdrant-150M-splade)` baseline, NDCG@10 LLM-judged,
paired mean |Δ| < ±0.005 (bar vs the 0.560 anchor).

This is the **full-corpus escape** from the persona-2M run's INCONCLUSIVE
(2026-06-27) verdict. That run was unmeasurable because a 2M slice holds only
~4% of the 3958 judged docs (med_bio 0.8%, social_sciences 4.1%); the matched
client-filter baseline was degenerate (ov@10 → 1.0, SEISMIC-vs-(mostly)-SEISMIC).
The 8 mmap'd shards search all 150M → the SEISMIC leg CAN return any judged
doc → the degenerate-baseline failure mode vanishes by construction.

## Why this is real work, not a re-run

`g6_rrf_parity.py` (the existing Persona-2M script) is hardwired to:
- a single-slice `SeismicBackend` (one index, `SFU_SEISMIC_INDEX`)
- a `oaid_set` = the 2M slice's docs → BM25F leg is *client-filtered* to the
  slice (the degenerate baseline)
- degenerate/overlap-unity detection that exists *only* because of the slice

The full-corpus run needs the **federated** 8-shard mmap'd backend as the SPLADE
leg, with **no scope filtering** (BM25F + SEISMIC both see all 150M). None of the
persona-2M degenerate logic applies.

## Verified preconditions (this session)

- 8 mmap'd shards: `/tmp/seismic_testbed/index/plan01/global_shard{0..7}of8.mmap/`
  — all OK, bit-identical parity, C2.5 150M_MMAP_READY (`seismic_c25_shards_150m_mmap.json`)
- baseline Qdrant record: `parity_record_tc_qdrant_20260625_0001.json` — 40 queries,
  each with full-corpus `bm25f` (50) + `splade` (50) top-50 → the 0.560 anchor
- judge cache: `llm_judge_cache.json` — 3958 judged docs (120 queries)
- diverse queries: `diverse_queries.json` — the 40-query set (judge_key join)
- 150M corpus = OpenAlex `W...` ids (same id space + same `spool_backup` source
  as the served Qdrant `splade_150m` collection) → genuinely apples-to-apples
- `ShardedSeismicBackend` ships `--load-mode mmap` + `CF` `search()` returning
  `[(doc_id, score)]` — drop-in for the SPLADE leg, loads all 8 shards at startup
- RAM: 8 mmap shards ≈ 0 anon floor + page cache; one shard's C2.5 validation
  was anon Δ 0.000 GB / 96% file-resident; 8 concurrent = ~66 GB page-cacheable
  on the 32 GB host (page cache is reclaimable, not a hard budget). k_prime=200
  per shard → SEISMIC faults only the posting-list pages each query touches
  (deep residency not required for correctness).

## Open question (resolved below)

**Does loading all 8 mmap shards at once OOM the 32 GB host?** mmap anon floor
is ~0/shard (validated), but the 8 `MmapSeismicIndex` objects each hold Rust-side
bookkeeping + the mmap slab descriptors. Worst case if it stacks: fall back to
**serial-per-query fan-out** (load → search → drop is too slow per query; instead
keep all 8 loaded but guard RSS and abort if process RSS > ~24 GB, reporting the
shard count that fit). Plan: load all 8, watch `/proc/self/status` VmRSS during
load, log per-shard RSS. If load exceeds budget, that itself is a G8 finding.

## Implementation

### 1. New script: `scripts/seismic_testbed/g6_rrf_parity_fullcorpus.py`

A focused full-corpus variant of `g6_rrf_parity.py`. Reuses the same RRF + NDCG
math (`rrf()`, `ndcg_at_k()`, `load_judge()`) and the same baseline-record +
diverse-queries join — copied so the persona-2M script stays bit-for-bit
reproducible (its degenerate-baseline logic is the artifact of record for that
regime; do not mutate it).

Differences vs persona-2M:
- SPLADE leg = `ShardedSeismicBackend(index_paths, load_mode="mmap")` over all 8
  shards (from the C2.5 manifest's `index_path` list), NOT single `SeismicBackend`.
- **No `oaid_set` / no scope filtering.** BM25F leg = the baseline record's
  `bm25f` (50) verbatim (full corpus, as Qdrant saw it). SEISMIC leg = federated
  top-50. RRF treatment = `rrf([bm25f, seismic_ids])`; RRF baseline =
  `rrf([bm25f, splade_ids])` (the stored Qdrant SPLADE).
- Three lanes reported (honest, mirrors persona-2M's structure):
  (1) baseline full-corpus `RRF(bm25f, qdrant-splade)` — the 0.560 regime
  (2) treatment full-corpus `RRF(bm25f, seismic-150m-splade)`
  (3) **paired Δ on queries where BOTH register a judged NDCG@10** — the gate
- Verdict: PASS iff `|paired Δ| < 0.005` AND `SEM(Δ) < 0.005` (n large enough)
  AND no degeneracy. The persona-2M degenerate-detector does NOT run (full
  corpus → no client-filtered baseline). Keep the under-power SEM guard.
- Per-query `leg_overlap@10` SEISMIC-vs-Qdrant (now full-corpus, not slice) =
  the G2-style overlap at scale — informative, NOT the gate (G2's 0.479 was the
  strict leg bar; G6 asks if RRF absorbs it).

### 2. Args

```
--shard-manifest data/eval_results/seismic_c25_shards_150m_mmap.json  (index_path list)
--baseline-record data/eval_results/parity_record_tc_qdrant_20260625_0001.json
--queries 40
--result-file data/eval_results/seismic_g6_rrf_fullcorpus_150m.json
--top-k 50 --k-prime 200 --heap-factor 0.8
```

### 3. RSS guard during 8-shard load

After each shard load, read `VmRSS` from `/proc/self/status`; log per-shard. If
process RSS > 24 GB mid-load, STOP loading further shards, run G6 on the subset
loaded, and record `n_shards_loaded` + the RSS budget hit as a G8-adjacent
finding (the run is still a valid latency/quality point on a partial federation).
Expect ~0 anon + page cache (~reclaimable) — should load all 8 clean.

### 4. Run (background, ~40 queries × 8 shards × mmap fault)

```
SFU_SEISMIC_LOAD_MODE=mmap .venv/bin/python3 \
  scripts/seismic_testbed/g6_rrf_parity_fullcorpus.py \
  --shard-manifest data/eval_results/seismic_c25_shards_150m_mmap.json \
  --baseline-record data/eval_results/parity_record_tc_qdrant_20260625_0001.json \
  --result-file data/eval_results/seismic_g6_rrf_fullcorpus_150m.json
```
Background + tee log `data/eval_results/seismic_g6_fullcorpus_150m.log`.
Monitor: per-query progress every 5 q, VmRSS during load, paired-n growth.

## Outputs + doc sync (same-commit, per efficacy rule)

- `data/eval_results/seismic_g6_rrf_fullcorpus_150m.json` (the result-file slot)
- `data/eval_results/seismic_g6_fullcorpus_150m.log`
- Docs updated same commit:
  - `02_GO_NO_GO_GATES.md` G6 row: full-corpus result (replaces the
    INCONCLUSIVE persona note with the full-corpus measurement, keeping persona
    as the recorded-history caveat)
  - `06_FINDINGS.md`: new dated row
  - `03_BENCHMARK_METHODOLOGY.md`: the full-corpus regime + result-file pointer
  - `docs/seismic_150m_testbed/README.md`: result-file index entry if needed
- Memory file `seismic-testbed-p1-p2-results.md`: update the G6 line with the
  full-corpus number.

## What success / failure look like

- **PASS** (|Δ| < 0.005, n large, SEM < 0.005): RRF absorbs the 0.479 leg gap at
  the system level → SEISMIC-150M is system-quality-safe to serve. The C2.5 +
  Plan-01 chain delivered its quality goal.
- **FAIL** (|Δ| ≥ 0.005, non-degenerate, n large enough): RRF does NOT absorb the
  leg gap at scale → G6 fails for the same structural reason G2 did; the quality
  floor is the live open risk, independent of serving.
- **INCONCLUSIVE-under-powered** (n too small / SEM > bar): the full corpus still
  under-covers the judged set → record honestly, the measured Δ is directional.

Either way the measurement is the point — the long-deferred full-corpus G6
finally runs. Nothing about G2's 0.479 changes; serving unblock (C2.5) is done.
