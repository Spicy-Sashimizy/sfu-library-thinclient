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
| **M7 bitmap/intersection sim** (2026-07-05) | moving the query-membership test *before* the gather (3.6 KB L1 bitmap vs 115 KB L2 dense table) skips most packs — the 76.7% zero-lane waste has enough pack-level clustering to matter | Stage-0 Python lane-accounting sim on real candidate sets: distribution of query-hits per 8-lane pack; bars pre-registered in `math_optimization/08_FURTHER_MATH_CANDIDATES.md` (all-miss-pack rate ≥0.5 GO / <0.3 KILL); dv shards serve as-is either way | **KILLED 2026-07-08** — all-miss-pack rate **0.194** (shard1 0.197, shard2 0.190; bar <0.3 = KILL): hits anti-cluster, ~80% of packs contain ≥1 query hit. Per-lane zero rate 0.7646 reproduces 06's 76.7% anchor. `scripts/seismic_testbed/m7_pack_membership_sim.py`, `data/eval_results/m7_pack_membership_sim_20260708.json`; verdict details `math_optimization/08` §M7 |
| **M6 VNNI/UDOT pre-gates** (2026-07-05) | `vpdpbusd`/`UDOT` i32 accumulation removes the i16 saturation that capped M2 at 6-bit → 7-bit query clears the 0.99 quality bar at n=100 (pre-gate model exists; 0.995 at n=40) | (1) cpuid inventory across dev/host/DO CPUs (`lscpu \| grep vnni`, ARM `asimddp`); (2) `m2_pregate_query_integer_dot.py` at 7-bit, n=100; gated behind M2b's verdict — see `math_optimization/08` §M6 | PRE-REGISTERED, not run |
| **M8 survivors-per-block instrument** (2026-07-05) | surviving posting blocks contribute ≥4 candidates on average → batched (register-blocked) scoring has material batch width | 20-line counter in the traverse path (or offline from posting-block stats); if typical batch <2, M8 dies on paper — `math_optimization/08` §M8 | PRE-REGISTERED, not run |
| **E7 readahead on ext4** | gate-c's 0.560 is partly drvfs; on a native ext4 host the fault profile may differ | would need shards copied to ext4 — **violates Rule Zero on this host** (no space guarantee); only for a future machine with a second SSD | PARKED |
| **E8 dv-v2 per-doc value scale** (2026-07-05) | the accepted marginal parity (G8d: corpus 0.9906, shards 1–2 = 0.985, doc 10 §7.6) is recoverable at zero serve-time cost — SFR1's per-doc linear u8 scale (doc 10 §2.4: rel-L2 0.329%, ~4× better than global schemes) grafted into the dv container as format v2 lifts shards 1–2 ≥0.99 and corpus mean ≥0.995 (*est.*) at ≤±2% size (*est.*, SFR1 suggests ~−6%) | Stage-0 FIRST (zero Rust): e6b-lineage proxy re-scored under per-doc-u8 on shard-1/2 candidates, n=100 (bars pre-registered in `12_EXECUTION_ROADMAP.md` Q1); on GO → version-bumped encoder/loader in `spike/vectorium_fork`, convert shards 1–2 only, gate-a n=100 vs f16 twins; full 8-shard re-conversion only after both pass | **Stage-0 GO 2026-07-08** — per-doc overlap@10 **0.997 (shard1) / 0.993 (shard2)** vs FixedU8Q 0.985/0.984 on the same n=100 candidates (both bars cleared; the FixedU8Q proxy reproduces G8d's measured 0.985 on these shards, validating the method). `scripts/seismic_testbed/e8_stage0_perdoc_scale.py`, `data/eval_results/e8_stage0_perdoc_scale_20260708.json`. **Stage-1 GO 2026-07-10** — v2 codec/converter/reader shipped (format version 2, per-doc f16 vmax record head); all 4 pre-registered bars PASS on both shards: overlap@10 **0.997/0.993** (= the Stage-0 proxy exactly), size **+0.67%** (the *est.* −6% did NOT materialize — the u8 re-distribution compresses the same, the f16 heads add ~+0.7%), warm p50 **0.985×/1.039×**, T1 bit-identity 0/0. `scripts/seismic_testbed/e8_dvv2_gates.py`, `data/eval_results/e8_dvv2_stage1_shard{1,2}_20260710.json`. Next: Stage 2 (host-tier full 8-shard re-conversion + E5-perm fold + G8d re-run; only that serves v2) |

### Q12 access-skew / hot-set telemetry probe (2026-07-13, disk_streaming_research candidate #1)

**PRE-REGISTERED before run (this commit); container-side, read-only, no serving
change.** Parent: `docs/disk_streaming_research/01_CROSS_PROJECT_RESEARCH.md`
candidate #1 (the colibrì `eusage`/pin premise — "a small hot set exists" —
transferred to SPLADE query traffic). Method: for n=120 topic-independent
queries (1 paraphrase per `original_query` from `diverse_queries.json`, served
shape k′=100/hf=0.8, E5 dv manifest), collect each query's `search_visited`
forward-range starts per shard (word offsets ×8 = bytes → 4 KiB page ids;
dv records avg ~165 B ≪ page, so start-page ≈ touched page), histogram page
touches across queries. Secondary stat: within-topic overlap on a 20-topic ×
3-paraphrase subset (repeat-traffic upper bound).

- **Prediction (*est.*, write-before-run):** touched-page distribution is
  Zipf-ish — top 10% of touched pages carry ≥50% of touches; cross-topic
  repeat fraction (pages touched by ≥2 of 120 queries, weighted by touches)
  ≥25%; hot-set-80 (pages covering 80% of touches) ≤ ~4 GB across 8 shards
  (vs ~25 GB dv forward total).
- **Decision rule:** hot-set-80 ≤ 4 GB AND repeat ≥25% → disk_streaming
  candidates #2/#3 (software LRU/pin, PILOT-analog prefetch) stay live —
  register their full experiments here before building. hot-set-80 > 8 GB OR
  repeat <10% → the colibrì premise does NOT transfer to this workload; close
  #2/#3, remediation stays Tier-2 #5 (no-swap host / mlock). Between → gray
  zone; re-run with a production-shaped query log before deciding.
- **Caveat (recorded before run):** 120 judged-eval queries are broader-topic
  than production library traffic (real users repeat subjects far more), so a
  skew finding here is *conservative* — a uniform finding here is decisive for
  closure, a skewed finding still needs the within-topic stat for sizing.

Script: `scripts/seismic_testbed/q12_access_skew_probe.py`; results →
`data/eval_results/q12_access_skew_probe_<date>.json`.

**MEASURED 2026-07-13 — GRAY ZONE (live-leaning)**
(`q12_access_skew_probe_20260713.json`, n=120+60, 400 s): repeat_touch_frac
**0.852** (≥0.25 ✅, far exceeded), hot-set-80 **4.20 GB** (bar ≤4 GB missed by
5%; close-bar >8 GB nowhere near), top-10% share **0.342** (prediction ≥0.50
MISSED — skew real but moderate, Gini 0.442), hot-set-50 **1.59 GB**, distinct
touched 27.2% of the 30.5 GB dv forward, within-topic paraphrase warm-hit
**0.621**. Per the pre-registered rule: candidates #2/#3 neither closed nor
green-lit — **next gate = re-run on a production-shaped query log** (recorded
caveat cuts favorably: eval set is diversity-maximized, production repeats
subjects more). Full read: `disk_streaming_research/02_…` §5.

### Q12b access-skew / hot-set probe — PRODUCTION-SHAPED query log (2026-07-14)

**PRE-REGISTERED before run (this row); the gating Phase 0b cell of the
disk-streaming research program (drive prompt Phase 0b).** Parent:
`docs/disk_streaming_research/03_MIN_RAM_DESIGN_MAP.md` (build gate G-a) +
the Q12 GRAY-zone caveat (eval set is diversity-maximized → production
repeats subjects more → a skew finding here is conservative). Method:
re-run the Q12 telemetry against (1) the served **E8 v2 manifest**
(`seismic_c25_shards_150m_mmap_e5_v2.json`, flipped 2026-07-14 — the v2
reconversion invalidated any Q12 sidecar, hence the rerun) and (2) a
**production-shaped** query log replacing Q12's 120-diverse set.

- **Production shape:** real SFU library traffic repeats *subjects*
  Zipf-ishly (a few hot subjects dominate; the same query recurs within a
  subject). The probe synthesizes this from `data/sfu_eval_queries.json`
  (120 real queries, 49 subjects) — sample N queries with a Zipf-weighted
  subject distribution (s=1.0 exponent) + within-subject repeat (each
  sampled subject contributes its own queries multiple times), emulating
  the documented production property (Q12 §caveat: "real users repeat
  subjects far more"). N=400 (≥3× Q12's 120 for tighter bars). Same
  served shape (top_k=50→k'=100, hf=0.8, query_cut=all-terms); same
  `search_visited` instrument; same page-touch histogram + coverage curve.
- **Prediction — write-before-run:** production skew ≥ the diverse set's
  (repeat_touch_frac already 0.852 on the diverse set, so the bar
  *should* lift further); hot-set-80 **≤ 4 GB** (the bar Q12 missed by
  0.2 GB — production repeat concentrates touches onto fewer pages, so the
  same 80% of touches should fit in less RAM, not more). If production
  skew moves the *opposite* way (hot-set-80 grows), the colibrì premise
  weakens.
- **Decision rule (unchanged from Q12):** hot-set-80 ≤ 4 GB AND repeat ≥25%
  → **GO** (disk-streaming Phase 1+ live). hot-set-80 > 8 GB OR repeat <10%
  → **hard NO-GO** (stop after Phase 1+2, park F3, write up why). Between
  → **GRAY** (proceed per the drive prompt: GO or GRAY-live-leaning →
  proceed; the program continues to Phase 3+).
- **Result records HERE (MEASURED row replaces this prediction) + doc 03 §5.**

**MEASURED 2026-07-14 — GO** (`q12b_access_skew_production_20260714.json`,
n=400 draws, 351 s, E8 v2 shards): repeat_touch_frac **0.9875** (≥0.25 ✅ —
Q12's 0.852 elevated by production repeat), hot-set-80 **3.07 GB** (bar ≤4 GB
**PASS** — Q12's 4.20 GB miss inverted: production repeat concentrates touches
onto fewer pages, exactly as the Q12 caveat predicted), hot-set-50 1.09 GB,
top-10% share 0.411 (Q12 0.342), Gini 0.550 (Q12 0.442), distinct touched
24.6% of the 30.5 GB v2 forward. Verdict **GO** under the pre-registered rule
(unchanged from Q12): the colibrì hot-set premise transfers to production-
shaped SPLADE traffic → F1/F2/F3 (disk-streaming Phase 1/2/3) green-lit.
Production shape = Zipf-weighted 49 subjects (top: Health Sciences 92/400) +
within-subject-with-replacement (75 queries drawn ≥2×, max repeat 23) over
`data/sfu_eval_queries.json`. Full read: `disk_streaming_research/03_…` §5.

Script: `scripts/seismic_testbed/q12b_access_skew_production.py`; results →
`data/eval_results/q12b_access_skew_production_<date>.json`.

### F4 floor-mlock (2026-07-14, disk-streaming Phase 2)

**PRE-REGISTERED before build/run.** Extends `prefault_floor` (Q9,
`SFU_SEISMIC_PREFLOOR_AT_LOAD`, E7 Fix #4) with an optional `mlock_floor` flag
that locks the SAME floor slabs it prefaults (posting_lists + doc-mapping
strings/offsets + optionally forward_offsets, ~1.5 GB structural floor).
Residency-only: `mlock` makes the floor un-evictable but does not touch the
scoring path → T1 bit-identical by construction.

- **Prediction — write-before-run:** floor pages show **zero** re-faults
  across a memory-pressure pass on the capped host (kswapd cannot steal them);
  warm p50 with floor-lock ON ≤ **1.05×** the pin-OFF warm p50 (mlock adds no
  per-query work, only a one-time load cost); T1 identical (0 mismatches).
- **Decision rule:** all three (zero floor re-faults under pressure AND warm
  ≤1.05× AND T1 0/0) = PASS → floor-pin is durable, promote to the localized +
  32 GB deploy combos. Any fault under pressure OR warm >1.10× = the mlock
  cost isn't free → keep it opt-in only.
- Kill-switch: `SFU_SEISMIC_MLOCK_FLOOR=1` (=0 → today's behavior, byte-identical).

### F3 mlock_ranges pin tier (2026-07-14, disk-streaming Phase 3)

**PRE-REGISTERED before build/run.** New pyo3 hook
`MmapSeismicIndex.mlock_ranges(extents)` pins page extents in the
`forward_data.bin` slab, budget-capped: pin ≤
min(`SFU_SEISMIC_PIN_BUDGET_GB`, `MemAvailable` − ~1.5 GB floor − headroom),
largest-coverage (touch-count) extents first. A/B vs pin-off on the 32 GB
host regime (the 15.8 s warm≈cold cell, measured 2026-07-01). The doc-02 §6
*est.* uplift to beat is ~1.5–3× p50 — treat as *est.*, NOT a bar; the bars
below are the actual pre-registration.

- **Dials:** `SFU_SEISMIC_PIN_BUDGET_GB` ∈ {0 (off, kill-switch), 1.6 (hot-50),
  4.2 (hot-80)} — the F1 sidecar budgets (doc 03 §3).
- **Prediction — write-before-run:**
  - 1.6 GB pin → covers ~50% of touches (Q12 curve) → warm p50 **~1.3–2×**
    pin-off on the capped 32 GB host (*est.*, doc 03 §3);
  - 4.2 GB pin → ~80% of touches → warm p50 **~1.5–3×** (*est.*, doc 02 §6);
  - 1.6 GB on a 6 GB cap → still fits (floor 1.5 + pin 1.6 + anon 1.1 + enc 0.7
    ≈ 4.9 GB locked; ~1 shard transient on top → ≤6 GB).
- **Decision rule (the no-OOM guarantee is the bar):**
  - **PASS** if EVERY dial cell shows VmSwap ≈ 0 AND no OOM-killer events
    (dmesg) AND T1 bit-identical (0/100 mismatches with pin-on). Latency
    uplift is *reported*, not gated (the program's goal is min-RAM with no
    OOM + no quality break; latency is the secondary win).
  - **NO-GO** if any dial OOMs or swaps (the budget check failed) → revert,
    F3 not viable at that dial; record the dial that OOM'd.
- **Result records HERE + doc 03 §5 status (DESIGN ONLY → MEASURED).**

Hooks: `mmap_index.rs` `mlock_ranges` + `release_pages_except` (Phase 4 F5);
`sharded_seismic_backend.py` loads the F2 sidecar at construction + the budget.

### F3/F4/F5 BUILD STATE + Phase 5 (2026-07-14)

**All three hooks BUILT + mechanism-verified; latency A/B HOST-GATED.**

- **F4 `mlock_floor`** (spike fork 6d21c5b, .so rebuilt sudo-native): hook works
  (`mlock_floor(True)` returned 1.67 GB on shard 0). **DESIGN ISSUE FOUND:**
  `mlock_floor` locks the FULL `_postings_mmap` slab (posting_lists.bin,
  1.16 GB/shard) × 8 = **~13.4 GB floor pin total**, NOT the doc-03 "~1.5 GB".
  The doc-03 "~1.5 GB structural floor" is PER SHARD (posting_lists 1.16 +
  doc-mapping 0.35); the Q9 "~5,000 pages = 20 MB constant floor" is the true
  small floor, NOT what `mlock_floor` locks (it locks the whole slab, like
  `prefault_floor`). For min-RAM, `mlock_floor` needs rescoping to the ~20 MB
  true structural floor; **default-off (kill-switch `SFU_SEISMIC_MLOCK_FLOOR=0`)
  is correct** until then. F4 EFFICACY UNMEASURED (and over-scoped).
- **F3 `mlock_ranges`**: hook works; the manual 8-shard pin path (load via
  `_load_one_shard` + `mlock_ranges` per shard, 0.2 GB/shard = 1.6 GB budget)
  pinned **0.782 GB across all 8 shards** cleanly (mlock returns 0 past the
  sudo memlock ceiling at ~shard 4, no crash — the no-op fallback). The
  `load_hotset_and_pin` budget check (min(dial, MemAvailable − 1.5 − 1.0))
  works. F3 EFFICACY (latency) HOST-GATED: the 15.8 s warm≈cold regime is a
  32 GB HOST phenomenon (62 GB index > 32 GB RAM); this dev container has 54 GB
  MemAvailable → warm p50 is already RAM-speed → pin-tier latency uplift is
  NOT measurable here. Latency A/B requires the operator's constrained-host run.
- **F5 `release_pages_except`**: hook built; NOT exercised (only relevant in
  the sequential-cold arm under memory pressure — host-gated). EFFICACY
  UNMEASURED.
- **Phase 5 T1 (correctness re-gate with pinning ON) — 20/20 BIT-IDENTICAL
  2026-07-14** (`_t1_pin_off.json` / `_t1_pin_on.json`):
  `ParallelSeismicBackend` (2 shards, E8 v2) with `SFU_SEISMIC_PIN_BUDGET_GB=1.6`
  (0.4 GB pinned) produces bit-identical top-50 oaid-order on 20/20 diverse
  queries vs pin-OFF. The pin tier is residency-only (`_merge_topk`/scoring/
  decode untouched) → T1 by construction; asserted empirically. Run
  out-of-process (1 backend, 2 subprocesses) because 3 backends × 2 shards
  exceeds the dev container's ~50 GB VmSize ceiling.
- **Dev-container VmSize ceiling (~50 GB, WSL2)**: 8-shard mmap = 44 GB +
  SPLADE ONNX = 6 GB; the full `from_manifest` pin path (ONNX eager + 8 shards
  + mlock + sidecar manifest read) MemoryErrors reading the 22 MB shard
  manifest. HOST-GATED: the production host (58 GB, Docker-exec root) and the
  32 GB constrained host don't hit this (different memory accounting). The
  no-OOM + T1 bar IS verifiable container-side (mechanism + T1 above); the
  latency + pressure A/B needs the constrained-host operator run.

### F6 cold-start prefault-hotset-at-load (2026-07-14, disk-streaming Phase 6)

> **CORRECTION 2026-07-14**: the result originally recorded here ("cold p95
> 30 ms median, ~150×", commit 0b4e9c3) was **INVALID**. Every one of the 300
> bench queries had silently failed — the F6 gate skipped the eager SPLADE
> load (encoder ImportError per query), and MADV_SEQUENTIAL over ~33k
> extents/shard saturated vm.max_map_count (262,144 measured), killing the
> parallel arm ("can't start new thread") — and the harness scored each
> failure as a ~0 ms no-op. Five defects fixed in commit 2203d9b; the numbers
> below are the corrected re-measurement.

**MEASURED 2026-07-14 (corrected)** (`f6_prefault_hotset_20260714.json` vs
`f6_gateoff_baseline_20260714.json`; paired same-.so A/B, q7 hybrid
fadvise-DONTNEED protocol, 100 q × 3 passes × 2 reps per arm, 0 failed
queries): at load, prefault (NOT mlock) the F2 sidecar's hot extents into
the page cache via the `prefault_ranges` .so hook (gate
`SFU_SEISMIC_PREFLOOR_HOTSET=1`, extents gap-coalesced to ≤2048/shard).
Gate OFF: cold p50 666-676 ms, cold p95 **4656-4686 ms**. Gate ON: cold p50
373-490 ms, cold p95 **1464-1884 ms (median 1674)**. → **~2.8× cold-p95,
~1.5× cold-p50, warm unchanged** (52-55 ms both arms). VmSwap 0.
Attribution (corrected 2026-07-14 audit): warm improving 117→54 ms vs the
2026-07-13 baseline is an operating-conditions confound (CPU contention),
not a module win — encode (pure ONNX) also halved 30.4→16.7 ms, the 01:00
old-.so rebench under co-load still showed warm 115-126 ms, and the .so
rebuild used no target-cpu flags. Quiet-host warm ≈54 ms; co-loaded ≈120 ms.
Not prefault either way (warm identical in both arms). The gate-OFF cold
p95 matches the 2026-07-13 baseline (4576-4896 ms) — cold p95 is disk-bound
and immune to the confound — so the cold-p95 gain is genuinely the
prefault's. Result parity ON vs OFF:
**10/10 identical** (top-10 ids + scores,
`scripts/seismic_testbed/seismic_result_parity.py`).

**Caveat (recorded honestly):** the win is the **process-cold warmup** — the
first queries of a fresh process after prefault, with no intervening eviction.
Under sustained memory pressure (the 32 GB-host warm=cold re-fault regime) the
prefaulted pages get evicted and need F3 mlock to stay resident. Prefault is
the cold-start lever; mlock is the durability lever. The constrained-host run
would measure both together (F3+F6).

### R1 RAM-ladder stress sweep (2026-07-14, E7b method on the served stack)

**MEASURED 2026-07-14** (`r1_cap{48,32,24,16,12,8,6}g_20260714.json`, driver
`scripts/seismic_testbed/r1_ram_ladder.py`): descending external caps via
sibling containers (`docker run --memory=X --memory-swap=X`, swap forbidden),
8-shard E8 v2 hybrid, prefault ON, 40 pre-encoded queries (E7b pattern — no
ORT in-cap) × 3 passes. All cells swap 0, 0 empty results. Latencies are
TRAVERSAL-ONLY (encode excluded by design).

| cap | cold pass p50/p95 | steady p50 (pass 3) | steady majflt/pass | regime |
|---|---|---|---|---|
| 48G | 576 / 1227 ms | **18 ms** | 0 | fits |
| 32G | 605 / 1275 ms | **18 ms** | 0 | fits |
| 24G | 584 / 1279 ms | **19 ms** | 0 | fits |
| 16G | 942 / 2176 ms | 135 ms | 15k | marginal (WS ≈ cap) |
| 12G | 1855 / 4589 ms | 22 ms | 2.4k | boundary w/ hysteresis (converges pass 3) |
| 8G | 3392 / 7211 ms | **2135 ms** | 261k | sustained thrash (warm≈cold) |
| 6G | 4802 / 10949 ms | **4924 ms** | 550k | sustained thrash, ~5 s/query |

> **Convergence caveat (2026-07-14):** the 16G pass-3 value (135 ms) is NOT
> a steady state — that cell was still converging (majflt 104k→56k→15k), and
> the 12G-beats-16G pass-3 inversion is a fixed-window transient artifact
> (capacity-scaled convergence time × pressure-scaled aging), not Belady's
> anomaly. Full write-up + literature:
> `docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`.

Findings: (1) this workload's working set = **~14.3 GB file-backed + 1.1 GB
anon ≈ 15.5 GB** — NOT the 44 GB index; above it the ladder is flat. (2) The
thrash floor starts between 12G (recovers by pass 3) and 8G (never recovers);
at ≤8G every pass re-faults the full touch set — the 32 GB-host warm≈cold
disease reproduced in a controlled cell. (3) Prefault-at-load does NOT help
under sustained pressure (as pre-registered: the kernel evicts the hot set
mid-pass).

**F3 pin-ON arm (2026-07-14, `r1_cap{8,6}g_pin16_20260714.json`) — the
pre-registered pin hypothesis is REFUTED in the self-thrash regime.**
Predicted (*est.*, doc 03 §3): pin 1.6 GB hot-50 → ~60% of touches become RAM
hits → 1.5–3× p50. Measured (pin engaged correctly: 1.64 GB locked, 8 shards,
coalesced extents, no VMA issues):

| cap | steady p50 OFF | steady p50 PIN-1.6 | majflt/pass OFF → ON |
|---|---|---|---|
| 8G | 2135 ms | 2229–2461 ms | 261k → 264k (neutral/slightly worse) |
| 6G | 4924 ms | **6631–6791 ms (~35% WORSE)** | 550k → ~590k |

Why the hypothesis failed: (a) touch coverage ≠ fault mass — the most-touched
pages are exactly the ones the kernel's active list already keeps under
churn, so the pin insured the wrong pages; (b) the locked 1.64 GB came out of
the same budget the un-pinned remainder streams through (at 6G: usable cache
~4.9 → ~3.3 GB → bigger per-pass deficit). Doc 02 §3.2's own "cannot beat
capacity math" bound applied. Only benefit observed: a modest cold-pass
prefault effect at 8G (pass 1 3.09 s vs 3.39 s). Remaining untested pin
value: protection against EXTERNAL cache competitors (not self-thrash) — a
different regime, pre-registered here as an open question, plus the
F4-rescoped ~20 MB floor pin.

**F5 release-except cell (2026-07-14, `r1_cap16g_f5rel_20260714.json`) —
NULL RESULT as built, with a diagnosed scope bug.** Pass-for-pass identical
to the plain 16G cell (966/460/125 ms vs 942/463/135 ms; majflt 104k/56k/15k
both). Tell: post-release RssFile UNCHANGED (14.32 GB) despite "released
16.45 GB" — the hook only covers the **forward_data slab**, whose pages were
mostly non-resident at that moment anyway; the actual load residue lives in
the structural slabs (posting lists, doc mapping, token maps) which
`release_pages_except` does not touch. The pre-sorted-cache hypothesis
(doc `session_2026-07-14.../04_CONVERGENCE_ARTIFACT.md` §5.3) is therefore
UNTESTED, not refuted — a meaningful test needs whole-shard
fadvise-DONTNEED-except-hot or extending the hook beyond the forward slab.

**Quality under squeeze: 40/40 bit-identical (ids + scores) vs the uncapped
reference in ALL THREE stressed cells** (8G-pin, 6G-pin, 16G-F5;
`r1_results_*.json` vs `r1_results_uncapped_ref.json`) — pressure is
latency-only, empirically confirmed at up to ~590k faults/pass.

### R2 fine convergence ladder (pre-registered AND MEASURED 2026-07-14)

**MEASURED 2026-07-14** — 14/14 cells clean (swap 0, real cold fills, no
F6-class failures); full table + per-cell verification in
`data/eval_results/_r2_ladder_summary.md`, cells `r2_cap*_20260714.json`.
Headline: **converged steady state is a flat 17.9–18.9 ms at every cap
≥ 11 GB and sustained thrash at every cap ≤ 10 GB (10g ~1.4 s, 9g ~1.8 s,
6g ~5.8 s) — the cliff between 10 and 11 GB is the empirical repeat-set
size.** Verdicts on the four pre-registered expectations: (1) cliff —
CONFIRMED; (2) passes-to-converge rising with cap — NOT CONFIRMED at pass
granularity (flat 4–5, ±1 rep-to-rep), but the pass-3 fixed-window inversion
REPRODUCED (12g p50 21 ms vs 16g 124 ms; R1 read 22 vs 135) with a refined
mechanism — the inversion is carried by residual-fault distribution across
queries, not by the smaller cap finishing the whole sort first; (3)
pressure-scaled aging — CONFIRMED by direct cgroup observation (pass-1
pgscan monotone 24g:0 → 17g:0.56M → 11g:3.5M → 6g:7.1M; ws_refault → 0 at
convergence above the cliff; active_file ends 0.2 GB at 24g — no pressure,
no promotion — vs 7.5–8.8 GB at 11g); (4) replicate spread — CONFIRMED
small (converged p50 18.1–18.9 ms across all drained cells). Caveat: the
near-zero stop rule (majflt ≤ 2,500) can leave 0.5–2k residual faults that
inflate the final-pass p50 to 21–36 ms (14/16/17g rep-1 cells) — quote
steady state only from a majflt≈0 pass. Original pre-registration follows.

Purpose: turn the R1 convergence artifact
(`docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`)
into a graphable dataset and upgrade its mechanism from fault-count inference
to direct kernel observation. Driver
`scripts/seismic_testbed/r2_convergence_ladder.py`; host-side orchestrator
`scripts/seismic_testbed/r2_host_orchestrator.sh` (sibling containers
`docker run --memory=X --memory-swap=X`, shared WSL2 page cache dropped
before every cell for cold-start purity); in-container GLM 5.2 drive session
verifies + commits per rung (`data/eval_results/_r2_convergence_drive_prompt.md`).

Design (differences from R1): **1 GB rungs 17→9 GB** (the marginal band
around repeat set ~10–11 GB and working set ~15.5 GB — R1's coarse ladder
had only 12/16 in-band), anchors 24 and 6 GB, replicates (`_rep2`) at
16/13/11. **Convergence-terminated, not fixed-window**: min 3 / max 12
passes; converged when pass majflt ≤ 2,500 ("near_zero") or per-pass change
< 10% twice in a row ("plateau"); `maxpass` = unconverged, its latency is
NOT quotable as steady state. Per-pass cgroup-v2 `memory.stat` deltas
(pgscan/pgsteal, workingset_refault_file, workingset_activate_file,
active_file/inactive_file gauges) + global `/proc/vmstat` (noisy — shared
WSL2 kernel). Same 40 pre-encoded queries / top-50 / prefault-ON as R1;
latencies remain TRAVERSAL-ONLY.

Pre-registered expectations (*est.* until measured):

1. Converged p50 vs cap is a monotonic step; the cliff (jump from ~20 ms to
   seconds) sits in [9, 12] GB, and its location is an empirical measurement
   of the repeat set (current estimate ~10–11 GB).
2. Passes-to-converge RISES with cap inside the marginal band (Che/Fagin
   capacity-scaled convergence time — 04 doc §4; R1 gives two points:
   12 GB ≤3 passes, 16 GB >3).
3. Per-pass pgscan/pgsteal falls as cap rises (pressure-scaled aging, 04 doc
   §2.2); workingset_refault_file → ~0 at convergence for caps above the
   cliff, stays high below it.
4. Replicate spread at 16/13/11 GB is small relative to the cap-to-cap
   differences (else single-sample rungs are not graphable).

Discard rules (any → cell INVALID, recorded not concluded): swap > 0; empty
results (driver exit 3); pass-1 majflt < 50k at cap ≤ 17g (pre-cell
drop_caches failed → residency contamination); converged p50 < 10 ms or
majflt ≈ 0 at cap ≤ 12g (broken cell, the F6 lesson).

### R3 kernel-ledger attribution spike (PRE-REGISTERED 2026-07-15; MEASURED 2026-07-16 — design doc `15_R3_KERNEL_LEDGER_SPIKE.md`)

Purpose: upgrade the R2 inversion mechanism ("residual-fault distribution
across queries") from per-pass aggregate inference to direct per-page kernel
observation, via (1) a bpftrace eviction/refault ledger
(`mm_filemap_delete_from_page_cache` / `mm_filemap_add_to_page_cache`),
(2) a `workingset_refault()` probe capturing refault distance + activation
decision, (3) between-pass `cachestat()` extent-residency maps — all joined
against a per-query extent-touch map from the `search_visited` pyo3 surface.
Cells: the 12/16 GB inversion pair, convergence-terminated per R2, each cap
paired with an uninstrumented control. Execution: GLM 5.2 drive session
authors ALL scripts and analysis (doc 15 §6 division of labor is binding);
host actions via `_r3_host_queue.md`. Capability gate G-R3-0 (WSL2 kernel:
BTF, tracepoints, bpftrace, cachestat ≥ 6.5) must pass before any cell; a hard
miss PARKS the spike with probe output committed.

**(the original vmscan tracepoints in instrument 1 — `mm_vmscan_memcg_reclaim_*`
+ `mm_vmscan_lru_shrink_inactive` — were DROPPED at REQ-3h 2026-07-16: they
carry no page index so the 1/512 extent-downsample can't gate them, and at the
reclaim-storm 12g cap they were 95% of ledger volume → 11.8% perf-ring drop
(INVALID); the join never keyed on them and the reclaim-pressure signal already
lives in per-pass cgroup `pgscan`/`pgsteal`. Drop cut 12g volume ~21× → drop=0.)**

Pre-registered expectations (predictions retain their original wording; measured
verdicts + numbers + paths below each, as of 2026-07-16):

1. **Attribution of the inversion.** At the fixed pass-3 window, the
   ledger × query-map join shows 12 GB's residual faults concentrated in
   extents touched only by its slow-tail queries (median query untouched),
   while 16 GB's residual faults land in extents shared by the median query —
   i.e. per-query residual-fault concentration is markedly higher at 12 GB
   than at 16 GB, and the specific slow queries are nameable with their
   extents.
   - **MEASURED 2026-07-16 — REFUTED.** pass-3 per-query DEL extents: 12g
     min/max=(1508, 2140) across **40/40** queries, skew(max/mean)=**1.14**;
     16g min/max=(68, 171) across 40/40, skew=**1.32**. BOTH uniform spread
     (skew ~1.0–1.4), NOT a slow-tail concentration. The prediction is
     informatively wrong: the repeat set's extents are shared across all 40
     queries (the query-extent map shows 19.6% of extents — 2050/10471 — touch
     all 40 queries; only 1.8% touch a single query), so residual faults
     *cannot* concentrate per-query. The inversion mechanism (artifact §7.2)
     is convergence-trajectory position at the fixed window (12g mid-sort vs
     16g near-converged at pass-3), not per-query fault concentration. Files:
     `r3_join_analysis.json` (cells.12g_instr / 16g_instr `(b)_*`); join
     `scripts/seismic_testbed/r3_join_analysis.py`; cells
     `r3_cap12g_instr_r3h_20260715.json` + `r3_cap16g_instr_r3fix_20260715.json`.
2. **The decision site.** Refault distances during the transient are smaller
   at 12 GB than 16 GB (shorter characteristic time), and the
   activation decision flips where distance exceeds the concurrent
   `active_file` size — the 04-doc §4 Che/Fagin link watched being made,
   per event, not inferred.
   - **MEASURED 2026-07-16 — UNCLEAR (documented downgrade, not silent).** The
     refault-distance local is NOT extractable under the WSL2 6.18.33 kernel's
     BTF (the shadow-entry encoding / `mm/workingset.c` `refault_distance`
     local is opaque to bpftrace) → emitted as -1 per the §R3 discard rule.
     The `workingset_refault` kprobe DID attach and stream correctly (BTF field
     walk `$folio->mapping->host->i_ino` + `$folio->index` resolved — verified
     real inodes + extent-aligned pgoffs), and the probe's ×512-scaled count
     matches the kernel's OWN `workingset_refault_file` cgroup counter within
     **1.8%** at 12g (6538 sampled ×512 = 3.35M vs cgroup 3.29M) and **0.3%**
     at 16g (1.27M vs 1.26M) — so the *count* is sound, only the *distance*
     half is downgraded. Activation is inferred downstream (a refault event is
     an inactive→evaluation event; true activation deduced by whether an ADD
     follows for the same (ino,pgoff) in the reclaim batch). The Che/Fagin link
     is therefore watched at *count* granularity per-pass, not per-event
     distance. Files: `_r3_cap{12,16}g_instr_*_refault.log`; the downgraded
     distance column.
3. **The sort, pictured.** Between-pass cachestat maps show 16 GB still
   holding load-residue extents at pass 3 that 12 GB has already evicted
   (the "kernel still sorting" state of 04-doc §2 as a drawable map), with
   residue draining to ~0 by each cell's converged pass.
   - **MEASURED 2026-07-16 — CONFIRMED (the asymmetry pictured; the 16g
     live-tracer drain is observer-perturbed, the pre-fix dead-tracer run
     corroborates).** pass-0 (post-load) evicted: 12g=**3.17 GB** (already
     pressure-sorting) vs 16g=**0.0 GB** (held the full ~14.3 GB working set,
     not yet sorting) — the artifact §2.2 "16g not yet sorting / 12g sorting"
     asymmetry pictured at page granularity. 12g drains to cache **10.13 GB**
     (the ~10–11 GB repeat set) by convergence. 16g's *live-tracer* drain
     stops at 13.43 GB (NOT drained) — a recorded observer effect (the live
     bpftrace probes + between-pass cachestat snapshots added pressure that
     perturbed 16g's reclaim timing, doc 15 §4); the **pre-fix REQ-2 dead-tracer
     16g cell** (tracer failed to attach → ~zero overhead) DID drain to
     **10.93 GB**, corroborating the drain in the un-perturbed regime. Files:
     `_r3_cachestat_cap{12,16}g_instr_r3fix_pass0..5.json` (live-tracer) +
     `_r3_cachestat_cap{12,16}g_instr_pass0..4.json` (pre-fix dead-tracer).
4. **Observer effect within bars.** Instrumented converged p50 ≤ 1.10× its
   uninstrumented control; ledger perf-buffer drop rate ≤ 1%.
   - **MEASURED 2026-07-16 — CONFIRMED on drop + the clean-probe (12g r3h)
     overhead; the 16g r3fix overhead 1.120× is a recorded-FAIL.** Ledger
     drop=0 both cells (no "Lost N events" line in clean streams of 31,620 /
     174,992 ADD-DEL events; an overrun would show a Lost line or anomalously
     low count, e.g. the pre-fix REQ-3g 12g had lost=62,145 explicitly).
     Overhead at steady-state (min-majflt pass, the pass-shape-invariant
     reference): 12g r3h **1.006×** PASS (instr 18.42 / ctrl 18.31 ms); 16g
     r3fix **1.120×** FAIL (16g's converged regime IS a ~2000-fault residual
     tail per its near_zero rule; the 12% over is likely the pre-drop heavier
     probe — 16g r3fix ran with the vmscan printf firehose still active, ~162k
     context events 16g bore that the post-fix 12g r3h did not; pass-3
     symmetric-transient was 1.072×, within bar). Verifier
     `scripts/seismic_testbed/r3_verify_cell.py`.

Discard rules (additions to R2's, which are inherited wholesale): ledger drop
rate > 1% → that cell's ledger INVALID (residency maps may still be used;
latency never — latency is only ever quoted from control cells); a control
cell failing any R2 check → the whole cap pair INVALID; refault-distance
extraction downgraded to activation-only must be recorded as a downgrade, not
silently substituted; G-R3-0 failure → park, record, stop.

### R3 instruments BUILD STATE + MEASURED (2026-07-16)

**All 7 instruments authored, committed, AND exercised on the host (G-R3-0
PASS 7/7 via REQ-1b; 4 control + 2 instrumented cells via REQ-2/3g/3h).** The
two R3-instrument corrections land live: (a) the **vmscan tracepoints DROPPED**
from the ledger probe (REQ-3h, above) — the 1/512 extent-downsample cannot
gate them and they overran the 12g perf ring; (b) the refault probe uses
**kprobe:workingset_refault** (bookworm bpftrace 0.17 has no fentry/kfunc),
with the BTF field walk resolving the inode + pgoff (distance stays -1, the
documented downgrade). Scripts under `scripts/seismic_testbed/` (committed as
built per doc 15 §6): `r3_inode_map.py` (2), `r3_ledger.bt` (1),
`r3_refault_probe.bt` (3), `r3_cachestat_map.py` (4),
`r3_query_extent_map.py` (5), `r3_kernel_ledger_driver.py` (6, extends
`r2_convergence_ladder.py`), `r3_host_orchestrator.sh` (7, extends
`r2_host_orchestrator.sh`); plus `r3_capability_probe.sh` (G-R3-0 gate),
`r3_verify_cell.py` (Phase C checklist, corrected denom + steady-state pass),
`r3_join_analysis.py` (Phase D join), `r3_splice_probes.py` (the pre-splice
fix that killed the 4-defect `sed` load-path). MEASURED in-container
verification: inode map → 8 forward-data inodes; query-extent map → 40
queries, 10471 distinct 2 MiB extents, 19.6%-touch-all-40 sharing profile;
ledger probe verified clean (12g r3h 31620 events drop=0, 16g r3fix 174992
drop=0); refault probe verified 1.003–1.018× the kernel's own refault counter.
Recorded limitations (unchanged, now empirically confirmed): inst-3
`workingset_refault`'s refault-distance is a function local not
probe-readable → -1 + the §R3 downgrade (the count half is sound, 1–2% of the
kernel counter). No served-path code, env-var gate, or default changed —
research scripts only, so `THIN_CLIENT_SWAP.md` / `STORAGE_BUDGET_150M.md` /
`docs/README.md` untouched (doc 15 + this row are the live record; README
already indexes doc 15).

### WI-1 clean sequential-vs-parallel federation A/B (2026-07-16, deployprep — PRE-REGISTERED before run)

**PRE-REGISTERED before run (this commit).** Parent: `docs/seismic_sequential_serving/`
(`SequentialSeismicBackend`, **EFFICACY UNMEASURED** at 150M per its README — the
only prior attempt was G8 swap-contaminated), `04_BENCHMARKING.md` (method ready,
150M numbers unmeasured), doc 13 §5 (the E5 A/B cold method — fresh-process mmaps
on 9p are naturally Linux-cold; `posix_fadvise(DONTNEED)` forces real faults;
pass 0 = cold, passes ≥1 = warm). Purpose: the clean head-to-head the README owes
— sequential vs parallel federation over the served e5_v2 shards, warm AND cold,
reporting p50/p95 latency, peak RSS bound per mode, and T1 result parity.

- **Why this container, not the 31.6 GB box:** the 64 GB container (54.8 GB
  MemAvailable, 16 cores) hosts a *clean* A/B: the ~15.5 GB file-backed working
  set fits without swap in BOTH modes, so the VmSwap==0 mechanism check (H2 of
  `04_BENCHMARKING.md`) is trivially true here and not the measured verdict. What
  IS measurable here, cleanly and swap-free: (a) the latency shape of each mode
  (parallel ≈ max-shard, sequential ≈ Σ-shards) on real 150M shards warm+cold;
  (b) the peak-RssFile bound (sequential mechanism B `release_pages` keeps ~1
  shard resident vs parallel's full working set — the resident-set ratio is the
  deliverable here even when RAM is ample); (c) T1 bit-identical parity at the
  served k'=100 shape. The swap-avoidance story (the 31.6 GB demo case) stays a
  literature+prior-evidence claim, clearly marked — this run does NOT re-prove it.
- **Method:** two concrete classes constructed directly
  (`ParallelSeismicBackend`, `SequentialSeismicBackend`), served e5_v2 manifest,
  mmap load_mode, top_k=50 / k'=100 (served default G8f) / hf=0.8 / all-terms
  (query_cut unset = recall-first served default). 40 diverse queries × 3 passes,
  arms alternating ×2 reps (the E5 protocol). Cold = each invocation's pass 0
  (fresh-process mmap = naturally Linux-cold on 9p; `posix_fadvise(DONTNEED)`
  per-shard after release enforces real faults, the E5 confound guard). Warm =
  passes ≥1. Per-query majflt tracked via `resource.getrusage(RUSAGE_SELF)`
  ru_minflt deltas (vmtouch unavailable in-container). Peak RssFile via
  `/proc/self/status` high-water each query. Driver: a new
  `scripts/seismic_testbed/wi1_seq_vs_par_federation.py` (built on the
  `serve_footprint_bench.py` + E5 `e5_shard_gates.py` lineage; out-of-process per
  arm so the cold cell is uncontaminated).
- **Predictions (*est.*, write-before-run):**
  - **P1 (warm latency):** parallel warm p50 ≈ 50–110 ms (doc 06's e5 warm band;
    encode ~17–30 ms paid once + max-of-8 traverse). Sequential warm p50 = Σ
    per-shard traverse + one encode ≈ parallel + ~7× single-shard traverse ≈
    **1.5–4× parallel** (the cost of losing max-of-shards; traverse is the small
    term so the multiple is modest).
  - **P2 (cold latency):** from doc 13 §5, sequential-e5 cold p50 **2159 ms** beat
    parallel-e5 **2687 ms** (1.24×) — 8-way cold fan-out contends on the 9p
    channel. Re-confirm: **sequential cold ≤ parallel cold** (≤1.0× ratqio).
  - **P3 (peak RSS):** parallel peak RssFile approaches the full ~15.5 GB
    working set (all 8 shards live); sequential peak ≈ 1 shard's file pages
    (~2–4 GB with mechanism B) → **sequential:parallel peak ratio ≪ 1** (the
    resident-bounding deliverable, measurable here even though RAM is ample).
  - **P4 (parity, T1):** bit-identical top-50 (oaid order + score within 1e-6)
    across all 40 queries, both reps — `hard==0, tie-swaps==0`.
- **Decision rule:** P4 PASS is mandatory (any parity mismatch = a real bug,
  KILL the latency claim). On P1–P3: record the clean measured ratios (no 31.6 GB
  swap-storm baseline here — the GO/KILL fork of `04_BENCHMARKING.md` needs the
  constrained box, recorded as the open host-queue item; this WI's verdict is the
  CLEAN swap-free shape). Verdict goes here + `docs/seismic_sequential_serving/
  04_BENCHMARKING.md` (a MEASURED row), + a pointer in doc 06. Result JSONs →
  `data/eval_results/wi1_seq_vs_par_<date>_{parallel,sequential}_rep{1,2}.json`.

**MEASURED 2026-07-16 — P4 (parity) PASS, P2/P3 PASS, P1 modestly exceeded.**
(`wi1_seq_vs_par_20260716_213857_{parallel,sequential}_rep{1,2}.json`; 4 cells, all
VmSwap 0.0, all `cache_confounded=False` — `release_pages()` + `posix_fadvise
DONTNEED` per shard forced real major faults, the E5 confound guard sound). Clean
swap-free A/B on the 64 GB container — the VmSwap==0 mechanism check (H2) is
trivially true here and NOT the verdict; the swap-avoidance 31.6 GB story stays
literature+prior-evidence (open host-queue item for the H1 GO/KILL fork).

| pred | metric | measured (mean 2 reps) | seq/par | verdict |
|---|---|---|---|---|
| P4 | T1 parity (top-50) | 0 hard mismatches / 2000 tuples × 2 reps | — | ✅ BIT_IDENTICAL (mandatory) |
| P1 | warm p50 (total) | par 47 ms / seq 248 ms | **5.29×** | prediction 1.5–4× → exceeded |
| — | warm traverse p50 | par 28 ms / seq 226 ms | 8.05× | the Σ-shards cost (small term ×8) |
| — | warm encode p50 | par 19 ms / seq 22 ms | 1.16× | H3 ✅ encode once, near-neutral |
| P2 | cold p50 | par 2623 / seq 2572 ms | **0.98×** | ✅ ≤1.0 (reaffirms doc 13 §5) |
| P3 | peak RssFile | par 11.74 / seq 0.27 GB | **0.023×** | ✅ ≪1 (~44× less resident) |

Headline read: on a host where parallel CAN run swap-free (≥ ~16 GB), parallel is
the faster-serving choice (warm 5.29× cheaper) and sequential's value is
exclusively the RAM floor (measured 0.023× resident) — sequential earns its keep
ONLY where parallel can't fit (the original motivation, vindicated on the resident
axis, measured at last). Open lever for the warm gap: the H4 free dials
(query_cut=10 ~4× traverse, C1; k′ down) which sequential multiplies 8× — re-
measure P1 with `query_cut=10` before any flip. `SequentialSeismicBackend`
efficacy: **MEASURED** (was UNMEASURED); NOT promoted to a served default (parallel
stays default on the ≥16 GB box). Full write-up: `seismic_sequential_serving/
04_BENCHMARKING.md` "MEASURED 2026-07-16".


### WI-4 portable-CPU build gate reclear (2026-07-16, deployprep — PRE-REGISTERED before run)

**PRE-REGISTERED before run (this commit).** Parent: `10_FORWARD_COMPRESSION_DESIGN.md`
§7.1 (native rebuild history: SSE2 baseline FAILED gate b 1.223×, native
`target-cpu=native` PASSED 0.957; objdump-verified +54 vfmadd/+14k ymm),
`math_optimization/05_TESTING_PROTOCOL.md` (worst-case-shard + n≥100 ISA-portability
discipline), doc 12's asset map (the fork at `spike/seismic_upstream/`). Purpose:
today's served `.so` is `target-cpu=native` (this exact CPU; SIGILL on a host
lacking the instructions) → it cannot ship to end users. Build portable
`x86-64-v3` (AVX2+FMA+BMI1/2) and `x86-64-v2` (SSE4.2+SSSE3, the broadest x86-64
baseline) variants, re-run the established gates vs native on the served e5_v2
shards. **The production .so is NEVER overwritten/unlinked** — variants live
beside it at `spike/seismic_upstream/target/portable_so/{v3,v2}/seismic/*.so`,
loadable by explicit `sys.path` prepend (an explicit path, never the venv default).

- **Method:** build each variant via `RUSTFLAGS='-C target-cpu=x86-64-v{3,2}'
  maturin build --release -i <venv-python>` (build, NOT `develop` — the latter
  installs into the venv and overwrites the production .so). Extract the `.so`
  from the wheel into a side-loadable `seismic/` package. Gate driver:
  `scripts/seismic_testbed/wi4_portable_cpu_gates.py` runs each variant (and
  native) in its own subprocess (the variant + native `seismic` can't coexist
  in one process), reusing the E7 `run_pass` cold+warm helper. Then a join step
  computes overlap@10 (variant-top10 vs native-top10) + warm-traverse ratio.
- **Gates (the established E7 bars, math/05 worst-case-shard + n≥100):**
  - **gate a (parity):** overlap@10 ≥ **0.99**, n=100, on shard 1 AND shard 2
    (both worst-case per G8d §7.6 — never shard0-only). A CPU-target change that
    reorders FMA could alter float rounding → different top-k; this gate must
    hold. *est.*: v3 uses the SAME packed SIMD as native (objdump v3 100 vfmadd/
    13979 ymm vs native 76/15392) → parity should hold near bit-identical; v2
    (SSE, no FMA) is the riskier one (different rounding path).
  - **gate b (warm latency):** variant warm traverse p50 / native ≤ **1.07×**.
    *est.:* v3 ≈ native (same FMA path, maybe slightly different scheduling); v2
    (no 256-bit, no FMA) expected measurably slower — may FAIL gate b.
- **Predictions (*est.*, write-before-run):** v3 PASSes both gates (parity ≥0.99,
  warm ≤1.07×) — the shippable portable target; v2 gate a marginal (rounding),
  gate b likely FAIL (slower). If v3 FAILs, build v2 as the fallback; if both
  fail parity, the portable handout ships with a documented quality caveat.
- **Decision rule:** a variant is **shippable** iff gate a PASS (≥0.99) on BOTH
  shards AND gate b PASS (≤1.07×). Record PASS/FAIL with numbers per target in
  doc 10 (§7.7 or a new §8) + the buildable recipe committed here. Verdict JSONs →
  `data/eval_results/wi4_verdict_{v3,v2}_shard{1,2}.json` + the per-variant top-k
  `wi4_topk_{variant}_shard{1,2}.json`.

**MEASURED 2026-07-16** — [FILLED IN BELOW once the gate matrix completes this
session; result JSONs land + the verdict table writes into doc 10 §7.7]. [To be
completed in the same commit as the gate results per the same-commit doc rule.]

## Recording rules (same-commit doc rule applies)

- Every executed cell: result JSON under `data/eval_results/g8c_*.json`
  (host commits JSONs only; the container session writes the doc rows).
- A Tier-1/2 row's outcome goes HERE (replace its prediction cell with
  measured numbers + result path + date) AND in its parent doc.
- Rows never executed stay PRE-REGISTERED — do not delete them; they are the
  queue for the next session.
