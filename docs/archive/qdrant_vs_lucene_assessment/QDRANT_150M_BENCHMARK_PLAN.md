# Qdrant 150M Benchmark Plan — the gap that remains

> **CLOSED SUPERSEDED 2026-07-06** — the "should we swap off Qdrant back to Lucene?" question was answered instead by promoting SEISMIC federated mmap (`docs/SEISMIC_ARCHIVE_SPLIT.md`). The RAM analysis and OOM findings remain the recorded evidence base for that move. Not current; do not resume.

**Status:** CLOSED SUPERSEDED 2026-07-06

**Date:** 2026-06-25

## What's already been benchmarked (don't redo)

Qdrant at 150M is **not** un-benchmarked — these gates are GREEN
(`docs/archive/bmp_decommission_plan/VALIDATION_REPORT.md`, 2026-06-25):

- **B1 parity** (vs BMP): overlap@10/@50 = 1.0, Kendall-τ = 1.0, NDCG Δ = 0.0 on
  the live `splade_150m` index.
- **B2 RRF quality:** tc-qdrant NDCG@10 0.5378/0.560, RRF-indistinguishable from
  BMP, +0.111 over OpenSearch.
- **B3 ops:** latency p50/p95, resident RAM, on-disk size, ingest throughput.

## The actual gap

**Every 150M Qdrant latency number is RAM-bound on the 24 GB dev host** (p50
545–861 ms). That measures the *host*, not the engine. Two things are genuinely
owed:

1. **A non-RAM-bound 150M latency curve** on a correctly-sized host (64 / 128 GB).
2. **A matched-hardware head-to-head vs OpenSearch** — every prior tc-vs-OS
   comparison carried "latency NOT comparable, different hardware."

Plus two resilience items not yet measured at scale:

3. The `_upsert_wait_retry` backoff (IMPLEMENTED, UNMEASURED — no `status=red` to
   heal against since the 150M ingest predated the code).
4. Concurrent-load behaviour — the existing `measure` harness is **single-threaded**
   (`cmd_measure`: one sequential `client.query_points`, no pool). Real serving is
   concurrent; the true OOM ceiling under concurrency is unmeasured.

---

## Plan

### Phase 0 — provision + restore (no re-ingest)
- Stand up a **64 GB** and a **128 GB** NVMe box (`DO_SIZING.md` tiers).
- Move `splade_150m` via Qdrant **snapshot** (`POST /collections/splade_150m/
  snapshots`) → restore on the target. Avoids the ~9.8 h re-ingest. Verify
  `points_count = 150,413,098`, `optimizer_status: ok`, and that the persisted
  PATCH (`max_optimization_threads=1`, `max_segment_size=5_000_000`) carried over.
- Pre-warm: one boot-time sweep query per segment so page cache is warm before
  timing (cold first-touch is page-cache warm-up, not steady cost — proven at 30M).

### Phase 1 — latency vs RAM curve (the headline)
Run the existing harness unchanged at each host size:
```bash
.venv/bin/python3 scripts/archive/spike_qdrant_sparse.py measure \
    --collection splade_150m --queries 40   # Qdrant-search-only, encode excluded
```
- Record p50/p95/max at **24 GB (have it), 64 GB, 128 GB**.
- Plot **p50 vs page-cache fraction of the 205 GB index**. Hypothesis from
  `DO_SIZING.md`: p50 crosses back under ~100 ms once a large fraction of 205 GB is
  cacheable. This is the number that tells you what a real serving box costs.
- Also capture `RssAnon` / `RssFile` from `/proc/<pid>/status` at each tier to
  confirm the ~43 B/point anon floor (~6.55 GB) is host-independent.

### Phase 2 — matched head-to-head vs OpenSearch (first fair latency comparison)
On the **same box class**, with `openalex_works` restored into OpenSearch 3.7
(currently absent — the operator **archived** the 150M index, so this phase is
**blocked until it's restored from that archive**; see FINDINGS §0):
```bash
# thin-client (Qdrant SPLADE leg), OOM-safe since it serves from disk:
SFU_SPLADE_BACKEND=qdrant .venv/bin/python3 scripts/eval_thinclient_parity.py \
    record-tc --queries 40 --output tc_qdrant_<box>.json
# OpenSearch baseline on the same box:
.venv/bin/python3 scripts/eval_thinclient_parity.py \
    record-os --baseline-url http://<os>:9200 --queries 40 --output os_<box>.json
# join (quality already known GREEN; this run is for matched latency):
.venv/bin/python3 scripts/eval_thinclient_parity.py compare \
    --tc-record tc_qdrant_<box>.json --os-record os_<box>.json --output cmp_<box>.json
```
- Report **latency side-by-side** (p50/p95 per leg + RRF), now hardware-matched,
  alongside the already-GREEN quality (NDCG@10) and per-leg overlap@50.
- Capture both engines' resident RAM during the run — this is the live version of
  the `QDRANT_VS_LUCENE_RAM.md` table.

### Phase 3 — ingest-resilience replay (measures item 3)
- On a scratch collection, seed `status=red` (drive the optimizer hot or set a low
  `indexing_threshold`) and run `build-spool-par`. Confirm `_upsert_wait_retry`
  catches the timeout, logs the `red`, and retries the idempotent batch with
  backoff (10 s→120 s, ≤20 attempts) **instead of the worker dying**. Record
  retry-heals vs worker-deaths and throughput under sustained red.

### Phase 4 — concurrency / soak (measures item 4)
- Extend the harness (or wrap with a small async pool) to issue **C concurrent
  queries** (C = 2, 4, 8, 16). Record p50/p95/throughput and watch RssAnon +
  RssFile + swap. Find the concurrency at which each host size OOMs or tails out.
  This is the missing "real serving" signal — all current numbers are serial.

### Phase 5 — report
- One table: **host RAM → {p50, p95, peak RSS, OOM?}** at 150M, plus the matched
  OpenSearch column. This replaces every "RAM-bound on the 24 GB host" caveat with
  a clean engine-vs-engine, hardware-matched result and pins the real
  cost/latency knee for production sizing.

---

## Acceptance criteria
- **Fitting-tier confirmed:** a host size where 150M Qdrant p50 ≤ ~100 ms warm
  (validates the DO_SIZING extrapolation from 30M).
- **Matched latency vs OpenSearch** reported on identical hardware (closes the
  "different hardware" caveat).
- **Resilience measured:** retry-heal rate under seeded red; OOM ceiling under
  concurrency per host size.
- All results land in `data/eval_results/` with absolute dates and feed
  `scripts/build_presentation_metrics.py --rebuild` (so `METRICS_CATALOG.json`
  carries the correctly-sized-host numbers, not just the RAM-bound ones).

## Reuse — scripts that already exist
- `scripts/archive/spike_qdrant_sparse.py measure` — Qdrant-search-only latency.
- `scripts/eval_thinclient_parity.py {record-tc,record-os,compare}` — RRF quality
  + per-leg overlap + latency.
- `scripts/experiments/eval_quant_fidelity.py --live-qdrant` — parity re-check post-restore.
- `scripts/archive/qdrant-serve.supervisor.conf` — serve-only auto-restart on the target.
- `scripts/build_presentation_metrics.py --rebuild` — fold results into the catalog.
</content>
