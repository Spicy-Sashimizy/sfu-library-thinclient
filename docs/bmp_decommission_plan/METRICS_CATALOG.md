# METRICS CATALOG — thin-client BMP→Qdrant decommission

One row per measured metric: **metric → script → result file → training baseline → delta**, with the absolute date and a `measured`/`est.`/`unmeasured` tag. Generated from `data/eval_results/METRICS_CATALOG.json` (canonical ledger). This is the index a presenter reads to find any number's provenance.

_Generated 2026-06-25T00:14:28Z, git commit `17e0d00`. 42 metrics._


## Quality

| metric | k | scale | backend | value | δ vs baseline | script → result file | training baseline | date | tag | comparable |
|---|---|---|---|---|---|---|---|---|---|---|
| NDCG@10 | 10 | 1000032-pool | BMP quant (leg) | 0.8681 | +0.0000 | `scripts/experiments/eval_quant_fidelity.py` → `data/eval_results/quant_fidelity_30mscan.json` | Qdrant f32 (same pool) | 2026-06-19 | measured | new |
| NDCG@10 | 10 | 1000032-pool | Qdrant f32 (leg) | 0.8681 | +0.0000 | `scripts/experiments/eval_quant_fidelity.py` → `data/eval_results/quant_fidelity_30mscan.json` | — | 2026-06-19 | measured | new |
| MRR@10 | 10 | 120q-judged | thinclient (BMP SPLADE) | 0.5648 | — | `scripts/experiments/benchmark_llm_judge.py` → `data/eval_results/benchmark_llm_judge_final.json` | training/benchmark_llm_judge_final.json (this… | 2026-05-16 | measured | yes |
| NDCG@10 | 10 | 120q-judged | thinclient (BMP SPLADE) | 0.5391 | — | `scripts/experiments/benchmark_llm_judge.py` → `data/eval_results/benchmark_llm_judge_final.json` | training/benchmark_llm_judge_final.json (this… | 2026-05-16 | measured | yes |
| P@10 | 10 | 120q-judged | thinclient (BMP SPLADE) | 0.3217 | — | `scripts/experiments/benchmark_llm_judge.py` → `data/eval_results/benchmark_llm_judge_final.json` | training/benchmark_llm_judge_final.json (this… | 2026-05-16 | measured | yes |
| NDCG@10 | 10 | 150M (34q judged-subset) | OpenSearch 150M RRF (baseline) | 0.4487 | -0.0881 | `scripts/eval_thinclient_parity.py record-os + compare` → `data/eval_results/thinclient_parity_waves_150m.json` | thinclient RRF (same run) | 2026-06-18 | measured | yes |
| NDCG@10 | 10 | 150M (34q judged-subset) | OpenSearch 150M RRF (baseline) | 0.4487 | -0.0891 | `scripts/eval_thinclient_parity.py record-os + compare` → `data/eval_results/thinclient_parity_qdrant_20260625_0001.json` | thinclient RRF (qdrant) (same run) | 2026-06-25 | measured | yes |
| NDCG@10 | 10 | 150M (40q judged-subset) | thinclient RRF | 0.5368 | +0.0881 | `scripts/eval_parity_section_waves.py + eval_thinclient_parity.py compare` → `data/eval_results/thinclient_parity_waves_150m.json` | OpenSearch 150M RRF (same run) | 2026-06-18 | measured | yes |
| NDCG@10 | 10 | 150M-LIVE | BMP quant (leg) | 0.6039 | +0.0000 | `scripts/experiments/eval_quant_fidelity.py` → `data/eval_results/quant_fidelity_live_150m_20260624_2345.json` | Qdrant f32 (same pool) | 2026-06-24 | measured | new |
| NDCG@10 | 10 | 150M-LIVE | Qdrant f32 (leg) | 0.6039 | +0.0000 | `scripts/experiments/eval_quant_fidelity.py` → `data/eval_results/quant_fidelity_live_150m_20260624_2345.json` | data/eval_results/quant_fidelity_30mscan.json… | 2026-06-24 | measured | new |
| NDCG@10 | 10 | 150M-live (39q judged) | thinclient RRF (qdrant) | 0.5378 | +0.0891 | `scripts/eval_thinclient_parity.py compare (record-tc SFU_SPLADE_BACKEND=qdrant)` → `data/eval_results/thinclient_parity_qdrant_20260625_0001.json` | thinclient RRF (BMP) 0.5368 + OpenSearch 0.44… | 2026-06-25 | measured | yes |

## Parity

| metric | k | scale | backend | value | δ vs baseline | script → result file | training baseline | date | tag | comparable |
|---|---|---|---|---|---|---|---|---|---|---|
| overlap@10 | 10 | 1000032-pool | BMP-8bit vs Qdrant-f32 | 0.9875 | — | `scripts/experiments/eval_quant_fidelity.py` → `data/eval_results/quant_fidelity_30mscan.json` | — | 2026-06-19 | measured | new |
| overlap@50 | 50 | 1000032-pool | BMP-8bit vs Qdrant-f32 | 0.9885 | — | `scripts/experiments/eval_quant_fidelity.py` → `data/eval_results/quant_fidelity_30mscan.json` | — | 2026-06-19 | measured | new |
| overlap@50 | 50 | 150M (40q) | thinclient bm25f | 0.532 | — | `scripts/eval_parity_section_waves.py + compare` → `data/eval_results/thinclient_parity_waves_150m.json` | OpenSearch 150M | 2026-06-18 | measured | new |
| overlap@50 | 50 | 150M (40q) | thinclient rrf | 0.476 | — | `scripts/eval_parity_section_waves.py + compare` → `data/eval_results/thinclient_parity_waves_150m.json` | OpenSearch 150M | 2026-06-18 | measured | new |
| overlap@50 | 50 | 150M (40q) | thinclient splade | 0.399 | — | `scripts/eval_parity_section_waves.py + compare` → `data/eval_results/thinclient_parity_waves_150m.json` | OpenSearch 150M | 2026-06-18 | measured | new |
| overlap@10 | 10 | 150M-LIVE | BMP-8bit vs Qdrant-live-f32 | 1.0 | — | `scripts/experiments/eval_quant_fidelity.py` → `data/eval_results/quant_fidelity_live_150m_20260624_2345.json` | data/eval_results/quant_fidelity_30mscan.json… | 2026-06-24 | measured | new |
| overlap@50 | 50 | 150M-LIVE | BMP-8bit vs Qdrant-live-f32 | 1.0 | — | `scripts/experiments/eval_quant_fidelity.py` → `data/eval_results/quant_fidelity_live_150m_20260624_2345.json` | data/eval_results/quant_fidelity_30mscan.json… | 2026-06-24 | measured | new |
| overlap@50 | 50 | 150M-live (40q) | thinclient bm25f (qdrant) | 0.532 | — | `scripts/eval_thinclient_parity.py compare` → `data/eval_results/thinclient_parity_qdrant_20260625_0001.json` | OpenSearch 150M | 2026-06-25 | measured | new |
| overlap@50 | 50 | 150M-live (40q) | thinclient rrf (qdrant) | 0.475 | — | `scripts/eval_thinclient_parity.py compare` → `data/eval_results/thinclient_parity_qdrant_20260625_0001.json` | OpenSearch 150M | 2026-06-25 | measured | new |
| overlap@50 | 50 | 150M-live (40q) | thinclient splade (qdrant) | 0.395 | — | `scripts/eval_thinclient_parity.py compare` → `data/eval_results/thinclient_parity_qdrant_20260625_0001.json` | OpenSearch 150M | 2026-06-25 | measured | new |

## Ops

| metric | k | scale | backend | value | δ vs baseline | script → result file | training baseline | date | tag | comparable |
|---|---|---|---|---|---|---|---|---|---|---|
| resident RAM | — | 150M | BMP (8-bit) | 211.0 | — | `docs/THIN_CLIENT_SWAP.md (measured 2026-06-17)` → `docs/THIN_CLIENT_SWAP.md` | — | 2026-06-17 | measured | new |
| on-disk size | — | 150M | BMP SPLADE shards | 68.6 | — | `docs/THIN_CLIENT_SWAP.md (measured)` → `docs/THIN_CLIENT_SWAP.md` | — | 2026-06-17 | measured | new |
| on-disk size | — | 150M | Qdrant on_disk index | 205.0 | +136.4000 | `docs/THIN_CLIENT_SWAP.md (measured 2026-06-21)` → `docs/THIN_CLIENT_SWAP.md` | BMP 68.6 GB | 2026-06-21 | measured | new |
| latency p50 | — | 150M (OOM-churn, red) | Qdrant on_disk | 1004.8 | — | `scripts/archive/spike_qdrant_sparse.py measure` → `data/eval_results/measure_150m_red_baseline.log` | — | 2026-06-21 | measured | new |
| latency p95 | — | 150M (OOM-churn, red) | Qdrant on_disk | 5535.9 | — | `scripts/archive/spike_qdrant_sparse.py measure` → `data/eval_results/measure_150m_red_baseline.log` | — | 2026-06-21 | measured | new |
| resident RSS rest | — | 150M (OOM-churn, red) | Qdrant on_disk | 3377 | — | `scripts/archive/spike_qdrant_sparse.py measure` → `data/eval_results/measure_150m_red_baseline.log` | BMP ~211 GB resident at 150M | 2026-06-21 | measured | new |
| latency p50 | — | 150M (warm, post-fix) | Qdrant on_disk | 703.6 | — | `scripts/archive/spike_qdrant_sparse.py measure` → `data/eval_results/measure_150m_postfix_20260620_230514.log` | — | 2026-06-21 | measured | new |
| latency p95 | — | 150M (warm, post-fix) | Qdrant on_disk | 3947.8 | — | `scripts/archive/spike_qdrant_sparse.py measure` → `data/eval_results/measure_150m_postfix_20260620_230514.log` | — | 2026-06-21 | measured | new |
| resident RSS rest | — | 150M (warm, post-fix) | Qdrant on_disk | 17240 | — | `scripts/archive/spike_qdrant_sparse.py measure` → `data/eval_results/measure_150m_postfix_20260620_230514.log` | BMP ~211 GB resident at 150M | 2026-06-21 | measured | new |
| on-disk GB (all-levers after levers) | — | 150M all-levers | thinclient | 188.8 | -112.1000 | `scripts/experiments/eval_storage_levers.py` → `data/eval_results/storage_levers_eval.json` | OpenSearch 150M | 2026-06-15 | measured | new |
| on-disk GB (all-levers total) | — | 150M all-levers | thinclient | 300.9 | — | `scripts/experiments/eval_storage_levers.py` → `data/eval_results/storage_levers_eval.json` | OpenSearch 150M | 2026-06-15 | measured | new |
| resident RAM rest | — | 30M | Qdrant on_disk sparse | 1.44 | — | `scripts/archive/spike_qdrant_sparse.py measure` → `data/qdrant_spike/measure_par30.log` | BMP ~tens of GB at 30M | 2026-06-19 | measured | new |
| latency p50 | — | 30M fitting-tier (warm steady-state) | Qdrant on_disk | 66.5 | — | `scripts/archive/spike_qdrant_sparse.py measure` → `data/qdrant_spike/measure_par30_warm.log` | — | 2026-06-19 | measured | new |
| latency p95 | — | 30M fitting-tier (warm steady-state) | Qdrant on_disk | 86.0 | — | `scripts/archive/spike_qdrant_sparse.py measure` → `data/qdrant_spike/measure_par30_warm.log` | — | 2026-06-19 | measured | new |
| resident RSS rest | — | 30M fitting-tier (warm steady-state) | Qdrant on_disk | 5262 | — | `scripts/archive/spike_qdrant_sparse.py measure` → `data/qdrant_spike/measure_par30_warm.log` | BMP ~211 GB resident at 150M | 2026-06-19 | measured | new |
| latency p50 | — | 30M fitting-tier (warm) | Qdrant on_disk | 208.4 | — | `scripts/archive/spike_qdrant_sparse.py measure` → `data/qdrant_spike/measure_par30.log` | — | 2026-06-19 | measured | new |
| latency p95 | — | 30M fitting-tier (warm) | Qdrant on_disk | 1333.4 | — | `scripts/archive/spike_qdrant_sparse.py measure` → `data/qdrant_spike/measure_par30.log` | — | 2026-06-19 | measured | new |
| resident RSS rest | — | 30M fitting-tier (warm) | Qdrant on_disk | 1441 | — | `scripts/archive/spike_qdrant_sparse.py measure` → `data/qdrant_spike/measure_par30.log` | BMP ~211 GB resident at 150M | 2026-06-19 | measured | new |
| ingest throughput | — | 30M gate | Qdrant (8 workers, wait=True) | 4234.0 | — | `scripts/archive/spike_qdrant_sparse.py build-spool-par` → `data/qdrant_spike/measure_par30.log` | — | 2026-06-19 | measured | new |

## Other

| metric | k | scale | backend | value | δ vs baseline | script → result file | training baseline | date | tag | comparable |
|---|---|---|---|---|---|---|---|---|---|---|
| Kendall-τ | 10 | 1000032-pool | BMP-8bit vs Qdrant-f32 | 0.9716 | — | `scripts/experiments/eval_quant_fidelity.py` → `data/eval_results/quant_fidelity_30mscan.json` | — | 2026-06-19 | measured | new |
| Kendall-τ | 10 | 150M-LIVE | BMP-8bit vs Qdrant-live-f32 | 1.0 | — | `scripts/experiments/eval_quant_fidelity.py` → `data/eval_results/quant_fidelity_live_150m_20260624_2345.json` | data/eval_results/quant_fidelity_30mscan.json… | 2026-06-24 | measured | new |

## Tags & comparability

- **measured** = run against real data/infra this session or a prior one, result file on disk. **est.** = design estimate. **unmeasured** = the module shipped before its eval (CLAUDE.md new-module rule).
- **comparable-to-training (yes)** = same NDCG@10/MRR@10/P@10 definitions, RRF k=60, same `claude-haiku-4-5-20251001` judge + cache. **new** = has no training-project equivalent (parity/ops), so never imply a false apples-to-apples vs the training charts.
