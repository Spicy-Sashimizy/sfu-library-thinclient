# BMP→Qdrant Validation Report — Go / No-Go Gate

> **CLOSED SUPERSEDED 2026-07-06** — the BMP->Qdrant decommission was overtaken by the SEISMIC promotion (`docs/archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md`; SEISMIC is the served SPLADE engine since 2026-07-06). Its DigitalOcean SKU/price tables are additionally unrunnable as of 2026-09-25 (cloud access ended, no droplet will ever be rented); only the measured RAM->latency model survives as evidence. Not current; do not resume.

**Status:** CLOSED SUPERSEDED 2026-07-06

**Status: B1 parity ✅ GREEN, B2 RRF quality ✅ GREEN (both 150M-live), D artifact
deletion ✅ DONE (2026-06-25). The BMP→Qdrant decommission gate is fully
cleared.** This report is the single gate table the BMP decommission (Workstream
D) waited on. Filled from Workstream B's runs (B1 parity, B2 RRF quality, B3 ops)
plus the D dry-run + deletion. Every cell cites its source file; `measured` /
`est.` / `unmeasured` per the CLAUDE.md efficacy rule. BMP-decommission plan
Workstream B / D.

**Host constraint:** validation runs within the 24 GB host's limits via the
OOM-safe wave methodology; the 150M numbers are reported honestly as RAM-bound
where they are, *plus* a 30M fitting-tier reference that projects what a
correctly-sized droplet delivers (see `DO_SIZING.md`).

## B1 — Retrieval parity (BMP vs Qdrant)

Gate: **overlap@10 ≥ 0.98 AND Kendall-τ ≥ 0.97 AND |NDCG@10 Δ| ≤ 0.005.**
Qdrant sparse search is exact (posting-list dot product); BMP is block-max
approximate (WAND pruning), so recall(qdrant) ≥ recall(bmp) by construction.

| Check | 30M in-memory gate (baseline) | 150M **live** index (B1) | Pass? | Source |
|---|---|---|---|---|
| overlap@10 | 0.9875 | **1.0000** | ✅ | `quant_fidelity_30mscan.json` / `quant_fidelity_live_150m_20260624_2345.json` |
| overlap@50 | 0.9885 | **1.0000** | ✅ | (same) |
| Kendall-τ | 0.9716 | **1.0000** | ✅ | (same) |
| \|NDCG@10 Δ\| f32−quant | 0.0000 (tie) | **0.0000** (f32 0.6039 = quant 0.6039, 14 judged-coverage queries) | ✅ | (same) |

**30M baseline:** PASSES. **150M-live (2026-06-24):** PASSES — the BMP ×70 8-bit
quant and Qdrant f32 produce **identical** orderings (overlap@10/50 = 1.0, τ = 1.0)
on the live `splade_150m` index's own retrieved set, across all 40 eval queries.
The live run scores both legs (f32 exact vs ×70-quant) over the SAME live top-k
hits' stored vectors, isolating the quantization-reordering risk against the exact
production index. Structural backstop holds: Qdrant exact ≥ BMP approximate.

## B2 — End-to-end RRF quality, 150M, both backends

Goal: RRF NDCG@10/MRR@10/P@10 statistically indistinguishable between
`SFU_SPLADE_BACKEND=bmp` and `=qdrant`, and still beating the OpenSearch
baseline. Cache-backed LLM judge ($0).

Run 2026-06-25: the thin-client retriever was pointed at the live Qdrant
`splade_150m` on_disk sparse collection (`SFU_SPLADE_BACKEND=qdrant`,
`scripts/eval_thinclient_parity.py record-tc` — now OOM-safe, since the
qdrant leg serves from disk rather than loading the ~211 GB BMP set),
recording BM25F+SPLADE ids over the SAME 40 diverse queries / corpus /
judge cache as the BMP baseline, then compared offline against the
OpenSearch record (`parity_record_os_20260618_0028.json`, RRF k=60).

**Two valid denominators (both reported — see `docs/BENCHMARK_METHODOLOGY.md`
§"150M parity"): the common-34 subset (queries judged in BOTH engines,
apples-to-apples, equal denominator) and the full tc-judged headline (39
queries; each query's IDCG uses only its own judged docs).**

| Backend | RRF NDCG@10 (34-common) | RRF NDCG@10 (39-judged headline) | vs OpenSearch 0.449 | Pass? | Source |
|---|---|---|---|---|---|
| thin-client (bmp SPLADE) | 0.5606→**0.561** (wins 29/34) | 0.5368 | **+0.112** | ✅ | `thinclient_parity_waves_150m.json` (2026-06-18) |
| thin-client (qdrant SPLADE) | 0.5597→**0.560** (wins 29/34) | **0.5378** | **+0.111** | ✅ | `thinclient_parity_qdrant_20260625_0001.json` (2026-06-25) |

**B2 gate PASS — qdrant vs bmp |Δ| < 0.001 on BOTH judged subsets**
(+0.0010 on the 39-judged headline, −0.0009 on the 34-common subset) → the
two SPLADE backends are RRF-indistinguishable at 150M. The OpenSearch win is
identical (29/34 on the common subset, +0.111–0.112) on both backends, so
the qdrant backend preserves the quality advantage the thin-client holds
over OpenSearch. (Per-leg overlap@50 vs OpenSearch is also unchanged within
noise: bm25f 0.532, splade 0.395, rrf 0.475 — see the catalog.) Latency is
not a head-to-head here (tc splade is RAM-bound on the 24 GB host, OS ran on
different hardware); the ops envelope is Workstream B3 below.

## B3 — Ops envelope

| Metric | 150M (host, RAM-bound) | 30M (fitting-tier) | Pass? | Source |
|---|---|---|---|---|
| SPLADE p50 | 545.8–861.5 ms | ~66 ms (65.6–67.4) | 30M ✅ / 150M honest | `measure_150m_postfix…log`, `measure_par30_warm.log` |
| SPLADE p95 | 3.4–4.5 s | ~86 ms (83.4–88.6) | 30M ✅ / 150M tail | (same) |
| Qdrant resident RAM (rest) | ~6.55 GB anon (+page cache to ~17 GB under load) | 1.44 GB | <5 GB host floor at 30M ✅ | `THIN_CLIENT_SWAP.md` Off-BMP |
| On-disk index | 205 GB | ~40 GB | — (disk cost) | (same) |
| Failure-mode: BM25F fallback | degrades on encode/Qdrant error (same as BMP, phase 5) | — | ✅ wired | `retriever._splade_leg_qdrant` |

**Ops gate:** Qdrant resident RAM < 5 GB on the host at the demo tier ✅; latency
recorded at both 150M (RAM-bound) and 30M (fitting-tier) with p50/p95 ✅.

## B4 — Fitting-tier reference (30M)

The number that represents a correctly-sized droplet and de-risks the demo
latency story (NOT host RAM-bound): **p50 ~66 ms, p95 ~86 ms, 1.44 GB resident at
rest** — `measure_par30_warm.log`, 2026-06-19. See `DO_SIZING.md`.

## B5 — Failure-mode check

`SFU_SPLADE_BACKEND=qdrant` degrades the SPLADE leg to **BM25F** on any
encode/Qdrant error (same contract as the BMP encoder-failure path — RRF still
fuses BM25F + dense). `SFU_LOAD_MEM_FLOOR_GB` + the serve-only supervisor
(`scripts/archive/qdrant-serve.supervisor.conf`, `autorestart=true`) guard RAM pressure
and auto-recover on crash. ✅ wired (phase 5, 2026-06-19 + serve conf 2026-06-21).

## D — Dry-run safety check + artifact deletion (COMPLETED 2026-06-25)

| Check | Status | Notes |
|---|---|---|
| `SFU_SPLADE_BACKEND=qdrant` default serves end-to-end | ✅ A1 (default flipped 2026-06-24) | retriever.py line 162 |
| Zero code refs to `.bmp` files on the qdrant path | ✅ re-verified 2026-06-25 | the `.bmp` glob (retriever.py) sits in the `skip_bmp=False` branch — on the qdrant default `skip_bmp=True`, so the serving path makes zero `.bmp` file refs; BMP code stays gated behind `SFU_SPLADE_BACKEND=bmp` |
| `import bmp` deferred to the BMP branch (no qdrant-path pisa dependency) | ✅ 2026-06-25 (commit 0b7ca48) | the qdrant serving path no longer requires the pisa wheel installed — `import bmp` runs only inside the BMP branch; verified via meta_path tracker that qdrant `_load()` does not import `bmp` |
| BMP artifacts snapshotted before deletion | ✅ 2026-06-25 | `data/eval_results/bmp_artifacts_deleted_manifest_20260625.json` (192 `.bmp` + 192 `.vocab.zst`, 68.66 GB, all paths recorded) |
| **Artifacts DELETED** | ✅ 2026-06-25 | 68.66 GB reclaimed (192 `data/thinclient_index/sections/*/splade_*.bmp` + `*.vocab.zst`); `data/thinclient_index` 298 GB → 230 GB; all 10 sections' tantivy BM25F indexes + abstracts + dense + meta.sqlite intact |
| **Post-deletion serving smoke test** | ✅ 2026-06-25 | `SFU_SPLADE_BACKEND=qdrant`: BM25F leg 5 hits, SPLADE leg 5 hits (live `splade_150m`), RRF fuses both — end-to-end serves; with Qdrant stopped the SPLADE leg gracefully degrades to BM25F (no crash), RRF still fuses |
| BMP kept as `SFU_SPLADE_BACKEND=bmp` fallback | ✅ | code + builder (`src/lib/thinclient/builder.py`) retained behind the env flag for small-tier (1M/15M) rebuilds; only the 150M *artifacts* removed |

## Go / No-Go

**Decision: B1 parity ✅ GREEN + B2 RRF quality ✅ GREEN + D deletion ✅ DONE
(all 2026-06-24 / 2026-06-25). The BMP→Qdrant decommission is COMPLETE — BMP
is retired as the default, the 68.66 GB of 150M `.bmp` artifacts are deleted,
and the BMP *code* + builder stay behind `SFU_SPLADE_BACKEND=bmp` for small-tier
rebuilds.**

- **B1 parity:** PASSES at 150M on the live index (overlap@10=1.0, τ=1.0,
  NDCG Δ=0.0). Combined with the 30M in-memory gate (0.9875 / 0.9716 / 0.0) and
  the structural backstop (Qdrant exact ≥ BMP approximate), Qdrant is a faithful,
  sufficient replacement for BMP on the parity axis.
- **B2 RRF quality:** PASSES at 150M-live. `SFU_SPLADE_BACKEND=qdrant` RRF
  NDCG@10 = 0.5378 (39 judged) / 0.560 (34-common subset) vs the BMP baseline
  0.5368 / 0.561 — |Δ| < 0.001 on **both** judged subsets, so the qdrant and
  bmp backends are RRF-indistinguishable. The OpenSearch win is preserved
  identically (tc beats OS +0.111, wins 29/34) on the qdrant backend.
- **D deletion:** DONE 2026-06-25. Deleted 192 `splade_*.bmp` + 192
  `splade_*.vocab.zst` (68.66 GB); `data/thinclient_index` 298 GB → 230 GB. All
  10 sections' tantivy BM25F indexes + abstracts + dense + meta.sqlite intact.
  Code hardening (commit 0b7ca48): `import bmp` deferred to the BMP branch, so a
  qdrant-only deploy no longer needs the pisa wheel installed. Post-deletion
  smoke test: qdrant default serves BM25F+SPLADE+RRF end-to-end; with Qdrant
  stopped the SPLADE leg gracefully degrades to BM25F (no crash). Manifest:
  `data/eval_results/bmp_artifacts_deleted_manifest_20260625.json`.

_B1 + B2 + D complete as of 2026-06-25 — the BMP→Qdrant decommission gate is
fully cleared and the demo deployment is no longer blocked on it._
