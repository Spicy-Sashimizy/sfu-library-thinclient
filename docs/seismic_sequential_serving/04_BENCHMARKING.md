# 04 · Benchmarking — sequential vs parallel, head-to-head

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
1. **Warm vs cold:** run ≥2 passes; report **warm p50** (a one-pass cold number is
   fault-storm noise, the G8 mistake).
2. **`vmtouch`** before each run to record shard residency; optionally pre-warm.
3. **Encode/traverse split on** (`search_with_timing`, already shipped) so a high
   p50 is attributed to the SPLADE encoder vs SEISMIC traversal — not left a
   mystery (the G8 `efce80e` fix).
4. Pin the query set to the existing 40/120-query parity set for comparability.

## Metrics (per mode, per query)

| Metric | Source | Why |
|---|---|---|
| p50 / p95 / mean latency | wall clock, warm pass | the demo-usability verdict |
| encode_ms vs traverse_ms | `search_with_timing` | which term to optimise next |
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
> back **encode ~26–35 ms vs traverse 1.7–6.7 ms** — i.e. the SPLADE fp16 encoder is
> the dominant warm term and SEISMIC traversal is cheap. This **strengthens the
> whole sequential case**: the cost sequential adds is the *traverse* term (sum-of-
> shards), which is the small one; the dominant *encode* (~30 ms) is paid **once per
> query regardless of mode or shard count**. Indicative model: parallel ≈ encode +
> max(traverse) ≈ ~35 ms; sequential ≈ encode + Σ(8×traverse) ≈ ~70 ms — both
> tens-of-ms once swap is gone, not seconds. **Caveat:** 100K testbed traverse does
> NOT transfer to 150M (traverse grows with corpus, sub-linearly per G4); encode
> (~30 ms, corpus-independent) does. The numbers below are the 150M re-measurement.

- **H1:** sequential warm p50 on the 31.6 GB box is **single-digit seconds** (8 ×
  swap-free per-shard), vs parallel's ~76 s swap-storm. *(If false → KILL per `00`.)*
  *(C1 evidence makes the optimistic end likely — traverse is the cheap term.)*
- **H2:** sequential `VmSwap == 0` while parallel `VmSwap > 0` on the same box. *(The
  mechanism check — bounded working set actually avoids swap.)*
- **H3 — SUPPORTED (100K, `[OURS]`):** the encode/traverse split shows the SPLADE
  encoder is the **dominant** warm term (~30 ms vs ~few ms traverse), and it runs
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
</content>
