# 03 · Measurement tables — everything measured this session

All numbers cite their result file. Latency semantics vary by table — noted
per table. Dates: baselines 2026-07-13, everything else 2026-07-14.

## T1 — E8 v2 serving status (the session's starting point)

End-to-end (encode + traverse), 100 queries, federated 8-shard, E8 v2,
`_e8s2_q7_federated_v2_20260713.json` (+ its cell files):

| mode | cold p50 | cold p95 | warm p50 | warm p95 |
|---|---|---|---|---|
| hybrid | 783–899 ms | 4.58–4.93 s | 115–120 ms | 177–182 ms |
| parallel | 768–779 ms | 4.44–4.45 s | 112–113 ms | 177 ms |
| sequential | 975–1009 ms | 4.60–6.00 s | 328–332 ms | 455–475 ms |

Quality: overlap@10 0.993–0.997 all 8 shards (bar ≥0.99), size +0.67%,
T1 20/20 federated. Attention-span mapping: warm = sub-Doherty (<400 ms)
even at p95; cold p50 just under the 1 s line; cold p95 far over it.

## T2 — F6 prefault: INVALID vs corrected (the session's core correction)

| | invalid record (0b4e9c3) | corrected (43c090e) |
|---|---|---|
| gate ON cold p50 | "25–27 ms" | **373–490 ms** |
| gate ON cold p95 | "28–32 ms (median 30)" | **1464–1884 ms (median 1674)** |
| gate ON warm p50 | "24.8 ms" | 54–55 ms |
| failed queries | 300/300 (unrecorded) | **0** (guarded) |
| claim | "~150× cold-p95" | **~2.8× cold-p95, ~1.5× cold-p50, warm unchanged** |

Paired same-day gate-OFF baseline (`f6_gateoff_baseline_20260714.json`):
cold p50 666–676 ms, cold p95 4656–4686 ms, warm 52–54 ms — cold p95 matches
the 2026-07-13 baseline (disk-bound, condition-immune), anchoring the 2.8×
to the prefault alone. Result parity ON vs OFF: **10/10 identical** (top-10
ids + scores, `seismic_result_parity.py`).

## T3 — Trust audit of "today's numbers" (operator-requested)

| number | trust | reason |
|---|---|---|
| cold p95 4.66→1.67 s (2.8×) | HIGH | same-session paired A/B, real RSS (17.5–18.9 GB), reps agree, parity 10/10, disk-bound (condition-immune) |
| cold p50 666→430 ms (1.5×) | HIGH | same pairing |
| warm 117→54 ms | LOW as a module claim | encode (pure ONNX) also halved 30.4→16.7 ms — impossible for the .so rebuild; old-.so rebench under co-load still 115–126 ms; no target-cpu flags. Verdict: **CPU-contention confound.** Quiet-host ≈54 ms, co-loaded ≈120 ms (both real). Docs corrected in 1919855 |
| correctness | HIGH | parity 10/10, T1 20/20, no truncation paths exist |

## T4 — R1 RAM-ladder (full 150M, 8-shard hybrid, prefault ON, pin OFF)

**Traversal-only** (pre-encoded queries — no ORT in the capped process), 40
queries × 3 passes, sibling containers `--memory=X --memory-swap=X`, all
cells swap 0 / 0 failed queries. Files `r1_cap{48,32,24,16,12,8,6}g_20260714.json`,
driver `scripts/seismic_testbed/r1_ram_ladder.py`.

| cap | cold pass p50/p95 | pass-2 p50 (majflt) | pass-3 "steady" p50 (majflt) | regime |
|---|---|---|---|---|
| 48 GB | 576 / 1227 ms | 19 ms (0) | 18 ms (0) | fits |
| 32 GB | 605 / 1275 ms | 20 ms (0) | 18 ms (0) | fits |
| 24 GB | 584 / 1279 ms | 22 ms (0) | 19 ms (0) | fits |
| 16 GB | 942 / 2176 ms | 463 ms (56k) | 135 ms (15k) | marginal — still converging at pass 3 (see 04_) |
| 12 GB | 1855 / 4589 ms | 1381 ms (187k) | **22 ms (2.4k)** | boundary w/ hysteresis — converged |
| 8 GB | 3392 / 7211 ms | 1997 ms (272k) | **2135 ms (261k)** | sustained thrash |
| 6 GB | 4802 / 10949 ms | 5449 ms (560k) | **4924 ms (550k)** | sustained thrash |

Key derived facts: workload working set = **14.3 GB file-backed + 1.1 GB
anon ≈ 15.5 GB** (not the 44 GB index); thrash floor between 12 GB
(converges) and 8 GB (cannot); fault-count → latency arithmetic checks out
(261k faults / 40 q × ~0.3 ms/fault ≈ 2 s ≈ measured 2.1 s).

Scope note (operator asked): R1 = the **entire 150M corpus**, every query
fanned to all 8 shards. The 2026-07-03 E7b sweep was the single-shard one.

## T5 — Cells pending at time of writing

Pin-ON (F3, `SFU_SEISMIC_PIN_BUDGET_GB=1.6`) at 8/6 GB after the defect-#6
fix, and the F5 release-except cell at 16 GB — each dumping last-pass top-10
results for quality-parity vs `r1_results_uncapped_ref.json`. Outcomes land
in `11_EXPERIMENT_BACKLOG.md` (R1 section); this file intentionally does not
pre-record them.
