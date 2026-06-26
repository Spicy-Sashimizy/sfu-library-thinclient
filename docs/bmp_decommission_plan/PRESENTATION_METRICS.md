# Presentation Metrics Suite — thin-client (BMP→Qdrant)

Presentation-ready numbers comparable to the `sfu-library-mcp-training` baselines (same LLM-judge methodology, same metric definitions). Every number below is sourced — see `METRICS_CATALOG.md` for the metric → script → result-file → training-baseline → delta provenance.

_Generated 2026-06-25T00:14:28Z, git commit `17e0d00`._

## 1. Quality (training-comparable)

NDCG@10 / MRR@10 / P@10 per retrieval method, LLM-judged (`claude-haiku-4-5-20251001`, 0-3 rubric, TREC-pooled; judge cache reused, $0). The thin-client numbers sit beside the OpenAlex-live baseline:

| method | NDCG@10 | MRR@10 | P@10 | date | source |
|---|---|---|---|---|---|
| OpenAlex relevance sort | 0.5391 | 0.5648 | 0.3217 | 2026-05-16 | `data/eval_results/benchmark_llm_judge_final.json` |
| thinclient RRF | 0.5368 | — | — | 2026-06-18 | `data/eval_results/thinclient_parity_waves_150m.json` |
| OpenSearch 150M RRF (baseline) | 0.4487 | — | — | 2026-06-25 | `data/eval_results/thinclient_parity_qdrant_20260625_0001.json` |
| Qdrant f32 (leg) | 0.6039 | — | — | 2026-06-24 | `data/eval_results/quant_fidelity_live_150m_20260624_2345.json` |
| BMP quant (leg) | 0.6039 | — | — | 2026-06-24 | `data/eval_results/quant_fidelity_live_150m_20260624_2345.json` |
| thinclient RRF (qdrant) | 0.5378 | — | — | 2026-06-25 | `data/eval_results/thinclient_parity_qdrant_20260625_0001.json` |

## 2. BMP↔Qdrant parity (150M where measured)

| metric | scale | backend | value | δ | gate | date | source |
|---|---|---|---|---|---|---|---|
| overlap@50 | 150M (40q) | thinclient bm25f | 0.532 | — | — | 2026-06-18 | `data/eval_results/thinclient_parity_waves_150m.json` |
| overlap@50 | 150M (40q) | thinclient splade | 0.399 | — | — | 2026-06-18 | `data/eval_results/thinclient_parity_waves_150m.json` |
| overlap@50 | 150M (40q) | thinclient rrf | 0.476 | — | — | 2026-06-18 | `data/eval_results/thinclient_parity_waves_150m.json` |
| overlap@10 | 1000032-pool | BMP-8bit vs Qdrant-f32 | 0.9875 | — | — | 2026-06-19 | `data/eval_results/quant_fidelity_30mscan.json` |
| overlap@50 | 1000032-pool | BMP-8bit vs Qdrant-f32 | 0.9885 | — | — | 2026-06-19 | `data/eval_results/quant_fidelity_30mscan.json` |
| overlap@10 | 150M-LIVE | BMP-8bit vs Qdrant-live-f32 | 1.0 | — | PASS | 2026-06-24 | `data/eval_results/quant_fidelity_live_150m_20260624_2345.json` |
| overlap@50 | 150M-LIVE | BMP-8bit vs Qdrant-live-f32 | 1.0 | — | — | 2026-06-24 | `data/eval_results/quant_fidelity_live_150m_20260624_2345.json` |
| overlap@50 | 150M-live (40q) | thinclient bm25f (qdrant) | 0.532 | — | — | 2026-06-25 | `data/eval_results/thinclient_parity_qdrant_20260625_0001.json` |
| overlap@50 | 150M-live (40q) | thinclient splade (qdrant) | 0.395 | — | — | 2026-06-25 | `data/eval_results/thinclient_parity_qdrant_20260625_0001.json` |
| overlap@50 | 150M-live (40q) | thinclient rrf (qdrant) | 0.475 | — | — | 2026-06-25 | `data/eval_results/thinclient_parity_qdrant_20260625_0001.json` |

**Gate (PLAN.md B1):** overlap@10 ≥ 0.98, Kendall-τ ≥ 0.97, |NDCG@10 Δ| ≤ 0.005. Qdrant sparse search is exact; BMP is block-max approximate (WAND), so recall(qdrant) ≥ recall(bmp) by construction.


## 3. Ops envelope (latency, RAM, storage, ingest)

| metric | scale | backend | value | unit | date | source |
|---|---|---|---|---|---|---|
| on-disk GB (all-levers total) | 150M all-levers | thinclient | 300.9 | GB | 2026-06-15 | `data/eval_results/storage_levers_eval.json` |
| on-disk GB (all-levers after levers) | 150M all-levers | thinclient | 188.8 | GB | 2026-06-15 | `data/eval_results/storage_levers_eval.json` |
| latency p50 | 150M (OOM-churn, red) | Qdrant on_disk | 1004.8 | ms | 2026-06-21 | `data/eval_results/measure_150m_red_baseline.log` |
| latency p95 | 150M (OOM-churn, red) | Qdrant on_disk | 5535.9 | ms | 2026-06-21 | `data/eval_results/measure_150m_red_baseline.log` |
| resident RSS rest | 150M (OOM-churn, red) | Qdrant on_disk | 3377 | MB | 2026-06-21 | `data/eval_results/measure_150m_red_baseline.log` |
| latency p50 | 150M (warm, post-fix) | Qdrant on_disk | 703.6 | ms | 2026-06-21 | `data/eval_results/measure_150m_postfix_20260620_230514.log` |
| latency p95 | 150M (warm, post-fix) | Qdrant on_disk | 3947.8 | ms | 2026-06-21 | `data/eval_results/measure_150m_postfix_20260620_230514.log` |
| resident RSS rest | 150M (warm, post-fix) | Qdrant on_disk | 17240 | MB | 2026-06-21 | `data/eval_results/measure_150m_postfix_20260620_230514.log` |
| latency p50 | 30M fitting-tier (warm) | Qdrant on_disk | 208.4 | ms | 2026-06-19 | `data/qdrant_spike/measure_par30.log` |
| latency p95 | 30M fitting-tier (warm) | Qdrant on_disk | 1333.4 | ms | 2026-06-19 | `data/qdrant_spike/measure_par30.log` |
| resident RSS rest | 30M fitting-tier (warm) | Qdrant on_disk | 1441 | MB | 2026-06-19 | `data/qdrant_spike/measure_par30.log` |
| resident RAM | 150M | BMP (8-bit) | 211.0 | GB | 2026-06-17 | `docs/THIN_CLIENT_SWAP.md` |
| resident RAM rest | 30M | Qdrant on_disk sparse | 1.44 | GB | 2026-06-19 | `data/qdrant_spike/measure_par30.log` |
| on-disk size | 150M | BMP SPLADE shards | 68.6 | GB | 2026-06-17 | `docs/THIN_CLIENT_SWAP.md` |
| on-disk size | 150M | Qdrant on_disk index | 205.0 | GB | 2026-06-21 | `docs/THIN_CLIENT_SWAP.md` |
| ingest throughput | 30M gate | Qdrant (8 workers, wait=True) | 4234.0 | docs/s | 2026-06-19 | `data/qdrant_spike/measure_par30.log` |
| latency p50 | 30M fitting-tier (warm steady-state) | Qdrant on_disk | 66.5 | ms | 2026-06-19 | `data/qdrant_spike/measure_par30_warm.log` |
| latency p95 | 30M fitting-tier (warm steady-state) | Qdrant on_disk | 86.0 | ms | 2026-06-19 | `data/qdrant_spike/measure_par30_warm.log` |
| resident RSS rest | 30M fitting-tier (warm steady-state) | Qdrant on_disk | 5262 | MB | 2026-06-19 | `data/qdrant_spike/measure_par30_warm.log` |

> ⚠ **On-disk ≠ resident RAM.** At 150M the Qdrant index is 205 GB on disk but RAM-bound (~7% page-cacheable on 23 GB host → p50 ~546–861 ms). The **30M fitting-tier (p50 ~66 ms, 1.44 GB resident)** is what a correctly-sized DO droplet delivers — see `DO_SIZING.md`.
