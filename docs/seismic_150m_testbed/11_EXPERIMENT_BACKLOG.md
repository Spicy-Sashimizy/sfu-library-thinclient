# 11 · Experiment backlog — pre-registered hypotheses for the G8b/G8c host session and beyond

**Created 2026-07-04. Status: PRE-REGISTERED, UNMEASURED (every row).** This is
the testbed registry for "if we're paying for a 58 GB host session, extract
every cheap answer while the cache is hot." Each hypothesis has a prediction
and a decision rule written BEFORE the run (the E7/E7b discipline). Results
get recorded here + in the parent doc for each track, with result-file paths
and absolute dates — a row without numbers stays marked UNMEASURED.

Parents: `10_FORWARD_COMPRESSION_DESIGN.md` §7.5 (E7b verdict + owed
follow-ups), `08_LATENCY_RESEARCH.md` §A1 (flat-then-cliff RAM economics),
`docs/seismic_sequential_serving/` (mechanism A/B, EFFICACY UNMEASURED at
150M), `docs/math_optimization/03_INTERACTION_MAP.md` (M-track gating).

## Why a warm-state matrix (the economics of the session)

Cold-filling the 41.4 GiB f16 working set from the drvfs mount is the
expensive step (tens of minutes). Once resident, **every additional
warm-state cell costs ~1–3 minutes** (new process, same page cache — file
cache survives process exit). So the session runs each codec's cold fill
ONCE, then sweeps every query-time knob against the hot cache before touching
the next cache-state-destroying cell. Driver:
`scripts/seismic_testbed/g8c_warm_matrix.sh`.

## Tier 1 — host warm-matrix cells (G8c, run inside the G8b session)

All latency-only: the quality side of each knob is already measured (E1
k′=100 recall-safe; C1 query_cut=10 overlap@10 0.995 vs all-terms;
heap_factor swept in `seismic_sweep_c1_querycut_heapfactor_20260630.json`).
40 queries, 1 pass, NO drop_caches (that's the point), parallel federation
unless stated. f16 AND dv arms each.

| id | hypothesis | prediction (*est.*, write-before-run) | decision rule |
|---|---|---|---|
| **H1 k′** | k′=100 halves candidates → shrinks dv's decode-proportional warm cost more than f16's (doc 10 §7 owed follow-up) | both arms speed up; dv warm Δ(k′200→100) ≥ f16's Δ; dv/f16 warm ratio moves toward ≤1.0 | if dv ratio at k′=100 ≤ 1.0, record "k′=100 erases the dv warm penalty" in doc 10; else record the residual |
| **H2 query_cut** | qc=10 (C1 lever) gives ~4× traverse speedup at full corpus, same as the 2026-06-30 container sweep | fed warm p50 drops ~3–4× vs all-terms in BOTH arms | the clean full-corpus C1 number goes in `08_LATENCY_RESEARCH.md` §C1 (currently container-scale only) |
| **H3 heap_factor** | hf 0.7/0.8/1.0 moves warm p50 ≤ ±15% at full corpus (it was mild in the container sweep) | monotone mild trend | record; if >±25% at any point, flag for a quality re-check before adopting |
| **H4 warm scaling** | A1 #4 said 8× docs → 1.6× warm p50; the 150M federated warm p50 should be ~1.5–2× the E7b single-shard 2.9 ms once encode is subtracted | traverse-only warm p50 / single-shard warm ∈ [1.3, 2.5] | outside range → the fan-out merge or GIL is a bigger cost than modeled; profile before optimizing anything else |

## Tier 2 — host capped cells beyond G8b's core (deploy-shape hypotheses)

| id | hypothesis | prediction (*est.*) | decision rule |
|---|---|---|---|
| **H5 sequential + dv @6G cap** | THE localized-deploy cell: sequential federation (one shard resident, mechanism release) over dv shards (3.10 GiB each) serves the FULL 150M corpus inside a 6 GB cap — the thing parallel/f16 needs 41+ GiB for | no OOM, no thrash *within* a shard; per-query cost ≈ Σ per-shard cold-ish traverses (tens of seconds/query, the mechanism-B trade measured 2026-07-01: warm≈cold 15.9 s at 32 GB) | if it completes clean at 6G, record in `docs/LOCALIZED_DEPLOYMENT_PLAN.md` + sequential-serving docs as the measured RAM floor for full-corpus serving; if it thrashes, sequential's real floor is >1 shard |
| **H6 sequential @58 uncapped** | sequential's page-release makes it pay ~cold cost per shard even with free RAM (mechanism, not RAM, bound) | p50 ≫ parallel warm; similar to its 32 GB number | quantifies what sequential mode costs when RAM is NOT scarce (its only regime advantage is the floor) |
| **H7 dv @24G** (already in G8b core) | locates dv's own full-corpus cliff | 24G < ~25 GiB working set → cliff or near-cliff | brackets the dv deploy floor between 24 and 28 GB |

Sequential cells use `--queries 10 --passes 2` (each query costs ~8 shard
traverses; 40×3 would take hours for no extra information).

## Tier 3 — container-side backlog (NOT host-RAM-bound; do not spend session time)

| id | hypothesis | method | status |
|---|---|---|---|
| **E5 co-access reordering** | docs scored together share pages after a co-access permute of the forward index → majflt ↓ beyond dv's 0.560 (the one remaining fault-count lever, doc 10 §7.4) | SIMULATE FIRST at page-touch granularity with the §7.4 pack-walk method (`e7_straddle_analysis.py` lineage) using real query candidate sets; only build the converter/id-indirection if the sim clears ~0.45 | PRE-REGISTERED, sim not written |
| **M2b i32-widen** | M2's gate-a fail (0.984 @ n=100) is i16 accumulator saturation; widening to i32 recovers ≥0.99 at ~half of M2's projected speedup | kernel variant behind the existing `SFU_SEISMIC_M2_INT6` plumbing; gate a at n=100 FIRST (the n=40→100 lesson, `math_optimization/07`) | PRE-REGISTERED, not built |
| **E3 n_postings-down** | n_postings below default shrinks the index at zero quality cost (the UP direction proved inert 2026-06-27; DOWN was never run) | one rebuilt shard0 variant + parity vs f16 baseline | BLOCKED on build budget (shard rebuild ~hours; /tmp sources gone — needs spool re-derivation) |
| **M7 bitmap/intersection sim** (2026-07-05) | moving the query-membership test *before* the gather (3.6 KB L1 bitmap vs 115 KB L2 dense table) skips most packs — the 76.7% zero-lane waste has enough pack-level clustering to matter | Stage-0 Python lane-accounting sim on real candidate sets: distribution of query-hits per 8-lane pack; bars pre-registered in `math_optimization/08_FURTHER_MATH_CANDIDATES.md` (all-miss-pack rate ≥0.5 GO / <0.3 KILL); dv shards serve as-is either way | PRE-REGISTERED, sim not written |
| **M6 VNNI/UDOT pre-gates** (2026-07-05) | `vpdpbusd`/`UDOT` i32 accumulation removes the i16 saturation that capped M2 at 6-bit → 7-bit query clears the 0.99 quality bar at n=100 (pre-gate model exists; 0.995 at n=40) | (1) cpuid inventory across dev/host/DO CPUs (`lscpu \| grep vnni`, ARM `asimddp`); (2) `m2_pregate_query_integer_dot.py` at 7-bit, n=100; gated behind M2b's verdict — see `math_optimization/08` §M6 | PRE-REGISTERED, not run |
| **M8 survivors-per-block instrument** (2026-07-05) | surviving posting blocks contribute ≥4 candidates on average → batched (register-blocked) scoring has material batch width | 20-line counter in the traverse path (or offline from posting-block stats); if typical batch <2, M8 dies on paper — `math_optimization/08` §M8 | PRE-REGISTERED, not run |
| **E7 readahead on ext4** | gate-c's 0.560 is partly drvfs; on a native ext4 host the fault profile may differ | would need shards copied to ext4 — **violates Rule Zero on this host** (no space guarantee); only for a future machine with a second SSD | PARKED |
| **E8 dv-v2 per-doc value scale** (2026-07-05) | the accepted marginal parity (G8d: corpus 0.9906, shards 1–2 = 0.985, doc 10 §7.6) is recoverable at zero serve-time cost — SFR1's per-doc linear u8 scale (doc 10 §2.4: rel-L2 0.329%, ~4× better than global schemes) grafted into the dv container as format v2 lifts shards 1–2 ≥0.99 and corpus mean ≥0.995 (*est.*) at ≤±2% size (*est.*, SFR1 suggests ~−6%) | Stage-0 FIRST (zero Rust): e6b-lineage proxy re-scored under per-doc-u8 on shard-1/2 candidates, n=100 (bars pre-registered in `12_EXECUTION_ROADMAP.md` Q1); on GO → version-bumped encoder/loader in `spike/vectorium_fork`, convert shards 1–2 only, gate-a n=100 vs f16 twins; full 8-shard re-conversion only after both pass | PRE-REGISTERED, not run |

## Recording rules (same-commit doc rule applies)

- Every executed cell: result JSON under `data/eval_results/g8c_*.json`
  (host commits JSONs only; the container session writes the doc rows).
- A Tier-1/2 row's outcome goes HERE (replace its prediction cell with
  measured numbers + result path + date) AND in its parent doc.
- Rows never executed stay PRE-REGISTERED — do not delete them; they are the
  queue for the next session.
