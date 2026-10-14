# 04 · Benchmarking — sequential vs parallel, head-to-head

**Status:** DEFERRED 2026-07-16 (measured WI-1 but never promoted; parallel federation is still the served path)

**Created 2026-06-30, updated 2026-06-30.** The `--federation {parallel,sequential}`
flag on `serve_footprint_bench.py` is **shipped** (recorded in the result JSON);
the bench already captures VmSwap + cold/warm passes + the encode/traverse split.
The methodology below is ready to run — the 150M latency numbers themselves are
**unmeasured (design-only until a run on the 31.6 GB box)**.

## What we are deciding

Does sequential federation deliver **G-SEQ-3 (demo-usable latency, swap-free)** on
the hardware we already have? The comparison is:

- **Parallel @ 31.6 GB** = the swap-confounded baseline (~76 s/query `[OURS]`).
- **Sequential @ 31.6 GB** = 8 × swap-free per-shard time.

The bet (design-only until measured): `8 × per_shard_swapfree ≪ 76 s`.

## Pre-conditions (or the numbers are noise)

Reuse the clean-measurement discipline from
[`../seismic_150m_testbed/08_LATENCY_RESEARCH.md`](../seismic_150m_testbed/08_LATENCY_RESEARCH.md) §A:
1. **Warm versus cold:** run ≥2 passes; report **warm p50** (a one-pass cold number is
   fault-storm noise, the G8 mistake).
2. **`vmtouch`** before each run to record shard residency; optionally pre-warm.
3. **Encode/traverse split on** (`search_with_timing`, already shipped) so a high
   p50 is attributed to the SPLADE encoder versus SEISMIC traversal — not left a
   mystery (the G8 `efce80e` fix).
4. Pin the query set to the existing 40/120-query parity set for comparability.

## Metrics (per mode, per query)

| Metric | Source | Why |
|---|---|---|
| p50 / p95 / mean latency | wall clock, warm pass | the demo-usability verdict |
| encode_ms versus traverse_ms | `search_with_timing` | which term to optimise next |
| per-shard traverse_ms | serial loop timing | is one shard a straggler? |
| peak RssFile | `/proc/self/status` | G-SEQ-1 (bounded RAM) |
| **VmSwap** | `/proc/self/status` | **G-SEQ-3 precondition — must be 0** |

Driver: extend `scripts/seismic_testbed/serve_footprint_bench.py` with a
`--federation {parallel,sequential}` flag (it already captures VmSwap + cold/warm
passes + the split). Results → `data/eval_results/seismic_seq_vs_par_<date>.json`.

## Hypotheses to test (design-only — labelled, not claimed)

> **Update 2026-06-30 — H3 + H4 now have supporting evidence from the C1 sweep**
> (`08_LATENCY_RESEARCH.md` §C1, `seismic_sweep_c1_querycut_heapfactor_20260630.json`,
> measured on the 100K testbed index `[OURS]`). The warm encode/traverse split came
> back **encode ~26–35 ms versus traverse 1.7–6.7 ms** — that is, the SPLADE fp16 encoder is
> the dominant warm term and SEISMIC traversal is cheap. This **strengthens the
> whole sequential case**: the cost sequential adds is the *traverse* term (sum-of-
> shards), which is the small one; the dominant *encode* (~30 ms) is paid **once per
> query regardless of mode or shard count**. Indicative model: parallel ≈ encode +
> max(traverse) ≈ ~35 ms; sequential ≈ encode + Σ(8×traverse) ≈ ~70 ms — both
> tens-of-ms once swap is gone, not seconds. **Caveat:** 100K testbed traverse does
> NOT transfer to 150M (traverse grows with corpus, sub-linearly per G4); encode
> (~30 ms, corpus-independent) does. The numbers below are the 150M re-measurement.

- **H1:** sequential warm p50 on the 31.6 GB box is **single-digit seconds** (8 ×
  swap-free per-shard), versus parallel's ~76 s swap-storm. *(If false → KILL per `00`.)*
  *(C1 evidence makes the optimistic end likely — traverse is the cheap term.)*
- **H2:** sequential `VmSwap == 0` while parallel `VmSwap > 0` on the same box. *(The
  mechanism check — bounded working set actually avoids swap.)*
- **H3 — SUPPORTED (100K, `[OURS]`):** the encode/traverse split shows the SPLADE
  encoder is the **dominant** warm term (~30 ms versus ~few ms traverse), and it runs
  once/query regardless of mode → the int8 encoder lever (`08` §D) helps **both**
  modes and is the top latency lever after the swap fix; gate on overlap@10 parity.
  Re-confirm the magnitudes at 150M.
- **H4 — SUPPORTED (100K, `[OURS]`):** `query_cut=10` cut traverse **~4×** at
  overlap@10 0.995 (`heap_factor` 0.6–0.8 near-inert within a `query_cut`). Since
  sequential sums the traverse term across 8 shards, this ~4× is the highest-leverage
  *free* sequential speedup — re-verify overlap@10 ≥0.99 holds at 150M before
  flipping the served default (pure query-time knob, no rebuild).

## Expected shape of the result (qualitative, design-only)

Literature `[literature]` says disk-bound serving trades RAM for I/O-bound latency:
DiskANN-class systems see latency climb as the in-RAM fraction shrinks (≈3× from a
50%→10% memory ratio), and I/O dominates query time when memory is tight
([page-aligned DiskANN](https://arxiv.org/html/2509.25487v2)). So we should *expect*
sequential to be slower than a fully-resident parallel run on a big box — the
question here is narrower and demo-specific: **is it fast enough on the small box
where parallel can't run at all without swapping?** That is the only comparison
that decides the demo.

## Decision rule

- **GO (demo on current box):** H1 ✓ AND H2 ✓ AND T1 (result-equivalence) ✓.
- **TUNE-THEN-DECIDE:** H1 ✗ but H4 (free dials) or mechanism (C) (mlock small side)
  brings warm p50 into band → re-measure, then decide.
- **KILL (need provisioned RAM):** swap-free sequential still not demo-usable and no
  free lever closes it → the demo needs the parallel path on a sized host; document
  and route to the `08` provisioning plan.

## MEASURED 2026-07-16 — clean swap-free A/B (deployprep WI-1)

The clean head-to-head this doc pre-armed for. Driver
`scripts/seismic_testbed/wi1_seq_vs_par_federation.py`; 4 cells (parallel ×2,
sequential ×2 alternating, E5 fresh-process-mmap-cold protocol — `release_pages()`
+ `posix_fadvise(POSIX_FADV_DONTNEED)` per shard forces real major faults; the
conflund guard `majflt==0 on cold = page-cache hit` was False in every cell).
Served e5_v2 shards, 40 diverse queries, top_k=50 / k'=100 (served default G8f) /
hf=0.8 / all-terms, mmap load_mode. Results
`data/eval_results/wi1_seq_vs_par_20260716_213857_{parallel,sequential}_rep{1,2}.json`.

**This is the 64 GB container (54.8 GB MemAvailable), NOT the 31.6 GB box.** The
~15.5 GB file-backed working set fits swap-free in BOTH modes → VmSwap was
**0.0 GB in all 4 cells** and `warm ≪ cold` held throughout (the page cache
helped). So the H2 mechanism check (VmSwap==0) is trivially true here, NOT the
measured verdict — the swap-avoidance story (the 31.6 GB demo case, the `08`
provisioning plan) stays literature+prior-evidence, **not** re-proven by this run.
What this run *does* measure cleanly and swap-free is the latency / RSS / parity
shape of each mode:

| metric | parallel (mean 2 reps) | sequential (mean 2 reps) | seq/par ratio | pre-reg prediction |
|---|---|---|---|---|
| **warm p50 (total)** | 47 ms | 248 ms | **5.29×** | P1 1.5–4× (modestly exceeded) |
| warm p95 (total) | 70 ms | 357 ms | 5.10× | — |
| warm traverse p50 | 28 ms | 226 ms | 8.05× | the Σ-shards cost (the small term, amplified 8×) |
| warm encode p50 | 19 ms | 22 ms | 1.16× | H3: encode paid once, near-neutral ✅ |
| **cold p50** | 2623 ms | 2572 ms | **0.98×** | P2 ≤1.0 ✅ (reaffirms doc 13 §5) |
| cold p95 | 8785 ms | 10899 ms | 1.24× | sequential tail slightly worse (Σ variance) |
| **peak RssFile** | **11.74 GB** | **0.27 GB** | **0.023×** | P3 ≪1 ✅ (decisive: ~44× less resident) |
| cold majflt/pass | ~266k | ~275k | 1.04× | neutral (sequential faults ~all shards once too) |
| warm majflt/pass | 0 | 0–1325 | — | mechanism B evicts some warm pages (expected) |
| **T1 parity** | — | — | **BIT_IDENTICAL 0/2000 × 2 reps** | P4 mandatory ✅ |

**Headline numbers (recomputed from the raw JSON, F6 discipline):**
- **P1 (warm latency):** sequential warm p50 **5.29×** parallel (248 versus 47 ms) —
  the cost of sum-of-shards over max-of-shards; **P1 prediction (1.5–4×) modestly
  exceeded.** Encode is once-per-query near-neutral (1.16×, H3 reconfirmed): the
  entire warm gap is the traverse term (8.05×), the small-per-shard cost summed
  over 8 shards. A 50 ms parallel serving budget becomes ~250 ms — still sub-
  second, demo-usable, but the cheaper-and-faster-simultaneously hope from the
  100K testbed model did **not** survive the 150M re-measurement (traverse is no
  longer negligible at full corpus; the doc-04 optimistic model flagged this).
- **P2 (cold latency):** sequential cold p50 **0.98×** parallel (2572 versus 2623 ms)
  — reaffirms doc 13 §5's finding that 8-way cold fan-out contends on the 9p
  channel; sequential (one shard faulting at a time) is not slower and marginally
  faster cold. **P2 PASS.**
- **P3 (peak RSS):** sequential peak RssFile **0.27 GB** versus parallel **11.74 GB**
  — **0.023× (×44 less resident)**. The resident-bounding deliverable, robustly
  measured even with RAM ample: mechanism B (`release_pages` after each shard)
  holds sequential's working set to ~a shard's transient forward pages + the
  structural floor. **P3 PASS decisively.** This is the property that makes
  sequential serve the 31.6 GB box at all.
- **P4 (T1 parity):** bit-identical top-50 (oaid order + f32 score bits),
  **0 hard mismatches / 2000 tuples, both reps.** **P4 PASS** — the mandatory
  correctness gate holds; sequential is a serving change with zero quality impact.

**Decision-rule verdict (this run, clean swap-free shapes — NOT the swap-storm
case):** T1 ✓ (P4), resident-bound ✓ (P3), cold-neutral ✓ (P2). The GO/KILL fork
of the decision rule (H1: single-digit-seconds on the swap-storm box) **needs the
constrained 31.6 GB host** — this container's 64 GB cannot reproduce swap-storm
parallel, so H1's "≪ 76 s" comparison is unmeasured here and recorded as the open
host-queue item. What IS decided: on a host where parallel CAN run swap-free
(≥ ~16 GB), **parallel is the faster-serving choice** (warm 5.29× cheaper) and
sequential's value is **exclusively the RAM floor** (0.023× resident) — that is,
sequential earns its keep ONLY where parallel can't fit (the original motivation,
vindicated on the resident axis, measured at last). Open lever for the warm gap
(P1 exceeded, pending: is 250 ms demo-usable enough?): the H4 free dials — query_cut
(C1, ~4× traverse, recall-safe at 0.995) + k′ down — which sequential multiplies
8×. Re-measure P1 with `query_cut=10` before any flip.

`SequentialSeismicBackend` efficacy: **MEASURED** (was UNMEASURED). Not promoted
to a served default (parallel stays the default for the ≥16 GB serving box);
sequential is the documented RAM-constrained-deploy / failover-cold path.

</content>
