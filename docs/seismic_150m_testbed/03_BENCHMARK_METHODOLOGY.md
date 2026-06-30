# 03 · Benchmark Methodology

Full, reproducible benchmarking spec for the SEISMIC go/no-go. Every gate in
`02_GO_NO_GO_GATES.md` maps to a measurement here. **Measured unless marked `est.`**
This doc reuses the canonical project methodology (`docs/BENCHMARK_METHODOLOGY.md`
for quality/LLM-judging; `docs/bmp_decommission_plan/METRICS_CATALOG.md` for the
metric→script→result-file ledger) and adds the SEISMIC-specific RAM/pruning probes.

## 1. Corpus & tiers

| Tier | Docs | Source | Use |
|---|---|---|---|
| Persona (med_bio) | ~23.4M (16 shards) | `data/thinclient_index/spool_backup` SPLADE `sparse_field` | P1–P3 — quality, RAM/doc, pruning, RRF parity (no 150M host needed) |
| Corpus-jump pair | ~0.93M vs ~2.0M | two persona sub-shards | **G4 sub-linearity** — same query set, two corpus sizes ≥2× apart |
| Full | 150,413,098 | full `spool_backup` | P4 — G7 build, G8 150M RAM+latency |

**No re-encoding.** SEISMIC is fed the *already-stored* SPLADE vectors (int8 impacts,
`QUANT_SCALE=70`). Any quality delta is then attributable to SEISMIC's
approximation/pruning, not a different encoder.

## 2. Query set & encoder

- **Queries:** the established 34-common / 120-query LLM-judge benchmark set
  (`scripts/benchmark_llm_judge.py`), plus the parity query set used by
  `eval_thinclient_parity.py`. SPLADE queries are real (~64 active terms), *not*
  short — this is what broke BMP's pruning and is the honest stress for G4.
- **Encoder:** `lib.opensearch_retriever.encode_splade` + `models/splade_onnx_fp16`
  (identical to serving). Boot-time warm-up query so cold encoder load (6.1 s) never
  contaminates latency samples.
- **Serving constants (identical-compute guarantee):** `QUANT_SCALE=70`, α=0.8, β=1.0,
  k-overfetch as in the live retriever. SEISMIC params (λ truncation, n-postings,
  block size, query cut) are tuned to **match Qdrant recall@k first**, then latency is
  read off — never the reverse.

## 3. Metrics & how each is measured

| Gate | Metric | Instrument | Result file |
|---|---|---|---|
| G2 | **overlap@10** & per-leg NDCG@10 vs Qdrant | `eval_thinclient_parity.py` (B1 overlap, B2 RRF) | `data/eval_results/seismic_parity_persona_<ts>.json` |
| G3 | **resident RAM / doc, split forward vs inverted/block/summary** | `/proc/self/status` RssAnon + `/proc/self/smaps_rollup` Pss_Anon, before/after loading *each side* of the index (forward index vs inverted+blocks+summaries) so the dominant consumer is known; for Path B, Qdrant `/metrics` jemalloc gauges (`memory_resident/active/retained_bytes`). The split decides whether the cheap Path C (Lance-ify the forward index only) suffices — see `01_ARCHITECTURE.md` Path C and `02_GO_NO_GO_GATES.md` G3 | `data/eval_results/seismic_ram_floor_<ts>.json` |
| G4 | **candidates_scored / corpus** at two corpus sizes | SEISMIC instrumented to emit #blocks/#candidates touched per query (mirror of `spike/mmap_bmp/measure_p3b_pruning.py`) | `data/eval_results/seismic_pruning_<ts>.json` |
| G5/G8 | **warm p50/p95, cold p95** | the established measure cadence (warm-up → N timed queries; cold via `posix_fadvise`/`drop_caches` where sudo allows) — same harness shape as `measure_p2_cold.py` | `data/eval_results/seismic_latency_<ts>.json` |
| G6 | **RRF NDCG@10** (system) | **persona-2M**: `scripts/seismic_testbed/g6_rrf_parity.py` — RRF(BM25F, SPLADE-leg) NDCG@10 SEISMIC-leg vs Qdrant-leg, scored via the cached `llm_judge_cache.json` (the SAME regime that produced the 0.560 baseline, so the ±0.005 bar is apples-to-apples). **(persona-2M was INCONCLUSIVE / unmeasurable 2026-06-27: a 2M slice holds ~4% of judged docs + a degenerate client-filter baseline — a real verdict needs a full-corpus run.)** **full-corpus 150M**: `scripts/seismic_testbed/g6_rrf_parity_fullcorpus.py` — same RRF/NDCG math, but the SEISMIC leg = `ShardedSeismicBackend` over all 8 mmap'd Plan-01 shards (150,413,098 docs, `SFU_SEISMIC_LOAD_MODE=mmap`), no slice filter, no degenerate-detector (full corpus → SEISMIC can return any judged doc). Measured 2026-06-28: Δ=−0.0076 (n=38, SEM 0.0059) → INCONCLUSIVE (under-powered; full-corpus escape succeeded but the point estimate straddles the bar). `benchmark_llm_judge.py` (fresh Haiku 0–3, TREC pooling) is an optional stronger cross-check — it needs `ANTHROPIC_API_KEY` + OpenSearch for abstract pooling AND would require re-judging the 0.560 baseline under the same fresh regime (±0.005 is NOT comparable across judging regimes). | persona `data/eval_results/seismic_g6_rrf_persona_<ts>.json`; **full-corpus `data/eval_results/seismic_g6_rrf_fullcorpus_150m.json`** |
| G7 | **build time, on-disk size, peak build RAM** | wrap the SEISMIC builder; watch `MemAvailable` + RssAnon during build (the OOM risk) | `data/eval_results/seismic_build_150m_<ts>.json` |

### RAM measurement is the load-bearing one — do it right

The prior session proved process RSS is **too coarse** (it lingers post-free and is
dominated by co-resident collections). For G3/G8 record **both lenses**:
1. **OS view** — RssAnon (`/proc/self/status`) and Pss_Anon (`smaps_rollup`):
   non-reclaimable private-dirty resident, the floor that causes OOM.
2. **Allocator view** — jemalloc `memory_resident/active/retained_bytes` (Qdrant
   `/metrics`; for a Rust SEISMIC process, `jemalloc-ctl` stats): collection-agnostic,
   drops immediately when pages return to the OS — no OS-reclaim lag.
Report RssAnon **per doc** (divide by corpus) so persona → 150M extrapolation is honest.

## 4. The parity bars (carried from the decommission plan — do not move them)

| Bar | Threshold | Meaning |
|---|---|---|
| **B1 overlap@10** | ≥ 0.95 (target 1.0) | SEISMIC returns ~the same top-10 as Qdrant on the same vectors |
| **B2 RRF NDCG@10** | within **±0.005** of 0.560 | no system-level quality regression. **Provenance:** 0.560 = 0.5597, the qdrant-SPLADE **34-common-subset** mean (verified reproduces from `parity_record_tc_qdrant_20260625_0001.json`); the all-39 headline is 0.5378, the BMP-SPLADE twin is 0.561/0.5368 — do not conflate (the ±0.005 bar is narrower than the 0.024 spread between the subset numbers → regime + scope must match). |
| **vs OpenSearch** | RRF NDCG@10 stays **> 0.449** (i.e. keeps the +0.111) | the quality reason we left OpenSearch must survive |

## 5. Baselines to beat / match (all measured, from existing docs)

| Stack | RAM floor @150M | p50 | RRF NDCG@10 | JVM |
|---|---|---|---|---|
| Qdrant f32 (present) | 6.55 GB anon (+ wants ~half of 205 GB cache) | 545–861 ms @150M RAM-bound / 66 ms @30M | 0.560 | no |
| BMP (retired) | 211 GB | fast in-RAM | 0.561 | no |
| OpenSearch (past) | ~2 GB heap | 19.7 ms/q @100k | 0.449 | **yes** |
| **SEISMIC (target)** | **flat, < 6.55 GB (Path C) / TBD (Path A)** | **TBD** | **≈0.560 (target)** | **no** |

## 6. Reproduction (per phase)

```
# P1/P2 — persona, on the 31.6 GB host (no 150M needed)
sudo /workspaces/sfu-library-thinclient/.venv/bin/python3 -m pip install pyseismic-lsr  # throwaway venv preferred
# build persona SEISMIC index from spool_backup sparse_field (no re-encode)
# run eval_thinclient_parity.py with SFU_SPLADE_BACKEND=seismic   (G2/G6)
# run the RAM probe before/after load                              (G3)
# run the pruning probe on the 0.93M vs 2.0M shards                (G4)
```

Every result lands under `data/eval_results/seismic_*` and is logged in
`06_FINDINGS.md` with absolute date, the eval script path, and the result-file path —
per the project's "measured, not flagged; numbers, not adjectives" rule.
