# 11 · Experiment backlog — pre-registered hypotheses for the G8b/G8c host session and beyond

**Status:** ACTIVE

**Created 2026-07-04. Status: PRE-REGISTERED, UNMEASURED (every row).**

> **Status note 2026-08-10:** the header above is the creation-time state and
> is now stale — most rows carry inline MEASURED verdicts (through
> 2026-07-28). Where a row here disagrees with
> `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` §4's decision ledger, that ledger wins (the roadmap itself is CLOSED
> SUPERSEDED 2026-09-25 and archived — a record, not a queue).

> **Reconciled 2026-09-25** — 15 items: 12 DONE, 1 CLOSED, 0 SUPERSEDED, 2 STILL OPEN.
> This aggregates the three pre-registered tables below (Tier 1 H1–H4, Tier 2
> H5–H7, Tier 3 E5/M2b/E3/M7/M6/M8/E7/E8), each of which carries its own
> reconciled line and per-row dated tags. The dated narrative sections that
> follow the tables (Q12/Q12b, F3–F6, R1–R3, WI-1…WI-18, Q11-C4) already carry
> their own inline MEASURED verdicts and are not re-tagged here. STILL OPEN:
> **H5** (sequential dv at a 6 GB cap — never run) and **E3** (n_postings-down —
> blocked on build budget). Neither appears as open work in `docs/README.md`'s
> Active tables or in this folder's `README.md`.

This is
the testbed registry for "if we're paying for a 58 GB host session, extract
every cheap answer while the cache is hot." Each hypothesis has a prediction
and a decision rule written BEFORE the run (the E7/E7b discipline). Results
get recorded here + in the parent doc for each track, with result-file paths
and absolute dates — a row without numbers stays marked UNMEASURED.

Parents: `10_FORWARD_COMPRESSION_DESIGN.md` §7.5 (E7b verdict + owed
follow-ups), `08_LATENCY_RESEARCH.md` §A1 (flat-then-cliff RAM economics),
`docs/seismic_sequential_serving/` (mechanism A/B, efficacy MEASURED 2026-07-16
deployprep WI-1 — see §WI-1 below + `04_BENCHMARKING.md`), `docs/math_optimization/03_INTERACTION_MAP.md` (M-track gating).

## Why a warm-state matrix (the economics of the session)

Cold-filling the 41.4 GiB f16 working set from the drvfs mount is the
expensive step (tens of minutes). Once resident, **every additional
warm-state cell costs ~1–3 minutes** (new process, same page cache — file
cache survives process exit). So the session runs each codec's cold fill
ONCE, then sweeps every query-time knob against the hot cache before touching
the next cache-state-destroying cell. Driver:
`scripts/seismic_testbed/g8c_warm_matrix.sh`.

## Tier 1 — host warm-matrix cells (G8c, run inside the G8b session)

> **Reconciled 2026-09-25** — 4 items: 4 DONE, 0 CLOSED, 0 SUPERSEDED, 0 STILL OPEN.
> All four cells ran in the G8c warm matrix on 2026-07-05 and their result files
> are committed. What is stale here is the write-back: the prediction cells were
> never replaced by verdict cells, so these rows read as pending when they are not.

All latency-only: the quality side of each knob is already measured (E1
k′=100 recall-safe; C1 query_cut=10 overlap@10 0.995 versus all-terms;
heap_factor swept in `seismic_sweep_c1_querycut_heapfactor_20260630.json`).
40 queries, 1 pass, NO drop_caches (that's the point), parallel federation
unless stated. f16 AND dv arms each.

| id | hypothesis | prediction (*est.*, write-before-run) | decision rule |
|---|---|---|---|
| **H1 k′** | k′=100 halves candidates → shrinks dv's decode-proportional warm cost more than f16's (doc 10 §7 owed follow-up) | both arms speed up; dv warm Δ(k′200→100) ≥ f16's Δ; dv/f16 warm ratio moves toward ≤1.0 | if dv ratio at k′=100 ≤ 1.0, record "k′=100 erases the dv warm penalty" in doc 10; else record the residual | — **DONE 2026-07-05 (G8c warm matrix; `data/eval_results/g8c_{dv,f16}_warm_kp100_qcall_hf08_20260705.json` against the `kp200_qcall_hf08` twins). Verdict row never written back into this table — stale, not pending.**
| **H2 query_cut** | qc=10 (C1 lever) gives ~4× traverse speedup at full corpus, same as the 2026-06-30 container sweep | fed warm p50 drops ~3–4× versus all-terms in BOTH arms | the clean full-corpus C1 number goes in `08_LATENCY_RESEARCH.md` §C1 (currently container-scale only) | — **DONE 2026-07-05 (`data/eval_results/g8c_{dv,f16}_warm_kp200_qc10_hf08_20260705.json` — the C1 lever of `08_LATENCY_RESEARCH.md` §C1 re-measured at full corpus). Verdict row never written back — stale, not pending.**
| **H3 heap_factor** | hf 0.7/0.8/1.0 moves warm p50 ≤ ±15% at full corpus (it was mild in the container sweep) | monotone mild trend | record; if >±25% at any point, flag for a quality re-check before adopting | — **DONE 2026-07-05 (`data/eval_results/g8c_{dv,f16}_warm_kp200_qcall_hf{07,08,10}_20260705.json` — the three-point hf sweep). Verdict row never written back — stale, not pending.**
| **H4 warm scaling** | A1 #4 said 8× docs → 1.6× warm p50; the 150M federated warm p50 should be ~1.5–2× the E7b single-shard 2.9 ms once encode is subtracted | traverse-only warm p50 / single-shard warm ∈ [1.3, 2.5] | outside range → the fan-out merge or GIL is a bigger cost than modeled; profile before optimizing anything else | — **DONE 2026-07-05 / 2026-07-08 (G8c warm matrix plus the G8e split, `g8e_encode_traverse_split_20260708.json`: federated warm p50 64.2 ms = encode 20.0 + traverse/fan-out/merge 43.7 ms, single-shard kernel only ~3–6 ms — that is, the fan-out merge IS the dominant cost, H4's 'profile before optimizing anything else' branch). Verdict row never written back — stale, not pending.**

## Tier 2 — host capped cells beyond G8b's core (deploy-shape hypotheses)

> **Reconciled 2026-09-25** — 3 items: 2 DONE, 0 CLOSED, 0 SUPERSEDED, 1 STILL OPEN.
> STILL OPEN: **H5** (sequential + dv at a 6 GB cap) — never run in any form, and
> not listed as open work in `docs/README.md` or this folder's `README.md`. It is
> still runnable here (a 6 GB cap fits well inside the surviving 31 GB WSL2 host,
> and `scripts/seismic_testbed/r1_ram_ladder.py` already drives capped sibling
> containers against the served shards).

| id | hypothesis | prediction (*est.*) | decision rule |
|---|---|---|---|
| **H5 sequential + dv @6G cap** | THE localized-deploy cell: sequential federation (one shard resident, mechanism release) over dv shards (3.10 GiB each) serves the FULL 150M corpus inside a 6 GB cap — the thing parallel/f16 needs 41+ GiB for | no OOM, no thrash *within* a shard; per-query cost ≈ Σ per-shard cold-ish traverses (tens of seconds/query, the mechanism-B trade measured 2026-07-01: warm≈cold 15.9 s at 32 GB) | if it completes clean at 6G, record in `docs/LOCALIZED_DEPLOYMENT_PLAN.md` + sequential-serving docs as the measured RAM floor for full-corpus serving; if it thrashes, sequential's real floor is >1 shard | — **STILL OPEN 2026-09-25 (never run; no capped sequential cell exists in `data/eval_results/`)**. Bounded but not answered by deployprep WI-1 (2026-07-16, `docs/seismic_sequential_serving/04_BENCHMARKING.md`): sequential peak RssFile 0.023× parallel (0.27 versus 11.74 GB) with anon ~1.1 GB — far inside 6 GB, but measured uncapped, so the no-thrash-at-6G claim is still untested. Not listed as open work in `docs/README.md`'s Active tables or this folder's `README.md`.
| **H6 sequential @58 uncapped** | sequential's page-release makes it pay ~cold cost per shard even with free RAM (mechanism, not RAM, bound) | p50 ≫ parallel warm; similar to its 32 GB number | quantifies what sequential mode costs when RAM is NOT scarce (its only regime advantage is the floor) | — **DONE 2026-07-05 (`data/eval_results/g8c_{dv,f16}_seq_uncapped_20260705.json`)**, and superseded in substance by deployprep WI-1 2026-07-16 (warm p50 5.29× parallel, 248 versus 47 ms — sequential's value is the RAM floor, not warm speed).
| **H7 dv @24G** (already in G8b core) | locates dv's own full-corpus cliff | 24G < ~25 GiB working set → cliff or near-cliff | brackets the dv deploy floor between 24 and 28 GB | — **DONE 2026-07-04 (`data/eval_results/g8b_fullcorpus_dv_cap24G.json`; verdict in `10_FORWARD_COMPRESSION_DESIGN.md` §7.5 — dv serves at the 24–32 GB caps where f16 thrashes).**

Sequential cells use `--queries 10 --passes 2` (each query costs ~8 shard
traverses; 40×3 would take hours for no extra information).

## Tier 3 — container-side backlog (NOT host-RAM-bound; do not spend session time)

> **Reconciled 2026-09-25** — 8 items: 6 DONE, 1 CLOSED, 0 SUPERSEDED, 1 STILL OPEN.
> STILL OPEN: **E3** (n_postings-down) — blocked on build budget, parked in
> `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` §Parked, and not listed as open work in
> `docs/README.md` or this folder's `README.md`. CLOSED: **E7 readahead on ext4**.

| id | hypothesis | method | status |
|---|---|---|---|
| **E5 co-access reordering** | docs scored together share pages after a co-access permute of the forward index → majflt ↓ beyond dv's 0.560 (the one remaining fault-count lever, doc 10 §7.4) | SIMULATE FIRST at page-touch granularity with the §7.4 pack-walk method (`e7_straddle_analysis.py` lineage) using real query candidate sets; only build the converter/id-indirection if the sim clears ~0.45 | PRE-REGISTERED, sim not written | — **DONE 2026-07-09 (Q6 sim GO — buildable order 0.376–0.400, worst shard 0.393 versus the 0.45 bar, `q6_e5_coaccess_sim_20260709.json`; converter + 8-shard rollout SERVED, commits `6170e1d` and `8f05aeb`; doc 13 §5, `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` Q6). E5 is the served forward layout.**
| **M2b i32-widen** | M2's gate-a fail (0.984 @ n=100) is i16 accumulator saturation; widening to i32 recovers ≥0.99 at ~half of M2's projected speedup | kernel variant behind the existing `SFU_SEISMIC_M2_INT6` plumbing; gate a at n=100 FIRST (the n=40→100 lesson, `math_optimization/07`) | **KILLED 2026-07-10** — gate a FAIL 0.987/0.983 < 0.99 (Q4, `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` ledger) | — **DONE 2026-07-10 (measured KILL: gate a 0.987/0.983 < 0.99 at n=100, `q4_m2b_pregate_20260710.json`; roadmap Q4).**
| **E3 n_postings-down** | n_postings below default shrinks the index at zero quality cost (the UP direction proved inert 2026-06-27; DOWN was never run) | one rebuilt shard0 variant + parity versus f16 baseline | BLOCKED on build budget (shard rebuild ~hours; /tmp sources gone — needs spool re-derivation) | — **STILL OPEN 2026-09-25** (unchanged: needs a shard rebuild from `data/thinclient_index/spool_backup`; parked in `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` §Parked as "do not re-derive"). Not listed as open work in `docs/README.md`'s Active tables or this folder's `README.md`.
| **M7 bitmap/intersection sim** (2026-07-05) | moving the query-membership test *before* the gather (3.6 KB L1 bitmap versus 115 KB L2 dense table) skips most packs — the 76.7% zero-lane waste has enough pack-level clustering to matter | Stage-0 Python lane-accounting sim on real candidate sets: distribution of query-hits per 8-lane pack; bars pre-registered in `math_optimization/08_FURTHER_MATH_CANDIDATES.md` (all-miss-pack rate ≥0.5 GO / <0.3 KILL); dv shards serve as-is either way | **KILLED 2026-07-08** — all-miss-pack rate **0.194** (shard1 0.197, shard2 0.190; bar <0.3 = KILL): hits anti-cluster, ~80% of packs contain ≥1 query hit. Per-lane zero rate 0.7646 reproduces 06's 76.7% anchor. `scripts/seismic_testbed/m7_pack_membership_sim.py`, `data/eval_results/m7_pack_membership_sim_20260708.json`; verdict details `math_optimization/08` §M7 | — **DONE 2026-07-08 (measured KILL: all-miss-pack rate 0.194 < the 0.3 bar, `m7_pack_membership_sim_20260708.json`; roadmap Q2).**
| **M6 VNNI/UDOT pre-gates** (2026-07-05) | `vpdpbusd`/`UDOT` i32 accumulation removes the i16 saturation that capped M2 at 6-bit → 7-bit query clears the 0.99 quality bar at n=100 (pre-gate model exists; 0.995 at n=40) | (1) cpuid inventory across dev/host/DO CPUs (`lscpu \| grep vnni`, ARM `asimddp`); (2) `m2_pregate_query_integer_dot.py` at 7-bit, n=100; gated behind M2b's verdict — see `math_optimization/08` §M6 | **KILLED 2026-07-10** — transitively by M2b's Q4 gate-a FAIL (Q5, `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` ledger); cpuid inventory never run (moot) | — **DONE 2026-07-10 (killed transitively by Q4's FAIL — same arithmetic width; the cpuid inventory was moot and never run; roadmap Q5).**
| **M8 survivors-per-block instrument** (2026-07-05) | surviving posting blocks contribute ≥4 candidates on average → batched (register-blocked) scoring has material batch width | 20-line counter in the traverse path (or offline from posting-block stats); if typical batch <2, M8 dies on paper — `math_optimization/08` §M8 | PRE-REGISTERED, not run | — **DONE: instrument 2026-07-10 (GO — median 18 candidates/block versus the bar of 4, `q3_m8_survivors_per_block_20260710.json`) and the register-blocked kernel BUILT + MEASURED 2026-08-10 — gate a bit-identity 100/100, gate c warm 1.0223×/1.0435× ⇒ REVERT; ships in-tree DEFAULT-OFF behind `SFU_SEISMIC_M8_BATCH` (`m8_batch_kernel_gate{a,c}_20260810.json`, `math_optimization/08` §M8). The 'PRE-REGISTERED, not run' status cell is stale.**
| **E7 readahead on ext4** | gate-c's 0.560 is partly drvfs; on a native ext4 host the fault profile may differ | would need shards copied to ext4 — **violates Rule Zero on this host** (no space guarantee); only for a future machine with a second SSD | PARKED | — **CLOSED-UNRUNNABLE 2026-09-25** — the row's own precondition ("only for a future machine with a second SSD") can no longer be met: cloud access ended 2026-09-25 (the OCI E5 host and every DigitalOcean droplet are gone) and the only surviving machine is the 31 GB local WSL2 host whose `data/` is the same 9p mount Rule Zero protects (`docs/infrastructure/README.md` banner).
| **E8 dv-v2 per-doc value scale** (2026-07-05) | the accepted marginal parity (G8d: corpus 0.9906, shards 1–2 = 0.985, doc 10 §7.6) is recoverable at zero serve-time cost — SFR1's per-doc linear u8 scale (doc 10 §2.4: rel-L2 0.329%, ~4× better than global schemes) grafted into the dv container as format v2 lifts shards 1–2 ≥0.99 and corpus mean ≥0.995 (*est.*) at ≤±2% size (*est.*, SFR1 suggests ~−6%) | Stage-0 FIRST (zero Rust): e6b-lineage proxy re-scored under per-doc-u8 on shard-1/2 candidates, n=100 (bars pre-registered in `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` Q1); on GO → version-bumped encoder/loader in `spike/vectorium_fork`, convert shards 1–2 only, gate-a n=100 versus f16 twins; full 8-shard re-conversion only after both pass | **Stage-0 GO 2026-07-08** — per-doc overlap@10 **0.997 (shard1) / 0.993 (shard2)** versus FixedU8Q 0.985/0.984 on the same n=100 candidates (both bars cleared; the FixedU8Q proxy reproduces G8d's measured 0.985 on these shards, validating the method). `scripts/seismic_testbed/e8_stage0_perdoc_scale.py`, `data/eval_results/e8_stage0_perdoc_scale_20260708.json`. **Stage-1 GO 2026-07-10** — v2 codec/converter/reader shipped (format version 2, per-doc f16 vmax record head); all 4 pre-registered bars PASS on both shards: overlap@10 **0.997/0.993** (= the Stage-0 proxy exactly), size **+0.67%** (the *est.* −6% did NOT materialize — the u8 re-distribution compresses the same, the f16 heads add ~+0.7%), warm p50 **0.985×/1.039×**, T1 bit-identity 0/0. `scripts/seismic_testbed/e8_dvv2_gates.py`, `data/eval_results/e8_dvv2_stage1_shard{1,2}_20260710.json`. **Stage 2 COMPLETE 2026-07-13** (8/8 shards re-converted, corpus-mean 0.9955) + **served-default flip 2026-07-14** — see `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` Q1 | — **DONE 2026-07-14 (Stage 0 GO 2026-07-08 → Stage 1 GO 2026-07-10 → Stage 2 8/8 shards 2026-07-13 at corpus mean 0.9955 → served-default flip 2026-07-14, commit `fcfcfb2`; `THIN_CLIENT_SWAP.md` §SPLADE leg).**

### Q12 access-skew / hot-set telemetry probe (2026-07-13, disk_streaming_research candidate #1)

**PRE-REGISTERED before run (this commit); container-side, read-only, no serving
change.** Parent: `docs/disk_streaming_research/01_CROSS_PROJECT_RESEARCH.md`
candidate #1 (the colibrì `eusage`/pin premise — "a small hot set exists" —
transferred to SPLADE query traffic). Method: for n=120 topic-independent
queries (1 paraphrase per `original_query` from `diverse_queries.json`, served
shape k′=100/hf=0.8, E5 dv manifest), collect each query's `search_visited`
forward-range starts per shard (word offsets ×8 = bytes → 4 KiB page ids;
dv records average ~165 B ≪ page, so start-page ≈ touched page), histogram page
touches across queries. Secondary stat: within-topic overlap on a 20-topic ×
3-paraphrase subset (repeat-traffic upper bound).

- **Prediction (*est.*, write-before-run):** touched-page distribution is
  Zipf-ish — top 10% of touched pages carry ≥50% of touches; cross-topic
  repeat fraction (pages touched by ≥2 of 120 queries, weighted by touches)
  ≥25%; hot-set-80 (pages covering 80% of touches) ≤ ~4 GB across 8 shards
  (versus ~25 GB dv forward total).
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

- **Production shape:** real library traffic repeats *subjects*
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
- **Scope amended 2026-08-17 (the pre-registration above assumed the whole floor
  slabs):** `=1` now locks the posting-list navigation runs only, budget-capped
  (`SFU_SEISMIC_MLOCK_FLOOR_MB`, default 160 MB total ≈ 20 MB/shard); `=full`
  keeps the original whole-slab arm. The three bars are UNCHANGED and still
  pre-registered — only the pinned byte set (and hence the RAM cost of a PASS)
  shrank ~671×. Residency + parity legs already measured (see the F4/F5 build-
  state section below); the latency/pressure legs remain unrun.

### F3 mlock_ranges pin tier (2026-07-14, disk-streaming Phase 3)

**PRE-REGISTERED before build/run.** New pyo3 hook
`MmapSeismicIndex.mlock_ranges(extents)` pins page extents in the
`forward_data.bin` slab, budget-capped: pin ≤
min(`SFU_SEISMIC_PIN_BUDGET_GB`, `MemAvailable` − ~1.5 GB floor − headroom),
largest-coverage (touch-count) extents first. A/B versus pin-off on the 32 GB
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
  doc-mapping 0.35). **RESCOPED 2026-08-17 (WS-C)** — `SFU_SEISMIC_MLOCK_FLOOR=1`
  now runs `sharded_seismic_backend.mlock_structural_floor`, which locks ONLY
  the posting-list navigation runs (per list: block_offsets + Elias-Fano
  offsets + DArray inventories) inside `posting_lists.bin`, budget-capped by
  `SFU_SEISMIC_MLOCK_FLOOR_MB` (TOTAL across shards, default 160 = ~20 MB/shard)
  under the F3 no-OOM guard (`MemAvailable − 1.0 GB`) and a ≤2048-ranges/shard
  VMA cap; `=full` reproduces the old whole-slab pin; `=0` stays the default.
  Implemented pure-Python (`/proc/self/maps` base + `ctypes` `mlock`), so the
  served .so is unchanged. **MEASURED 2026-08-17** (shard0,
  `data/eval_results/f4_floor_mlock_rescope_20260817.json`,
  `scripts/seismic_testbed/f4_floor_mlock_smoke.py`): **19,980,288 B locked in
  929 ranges in 1.6 s**, `VmLck` delta equal to the reported bytes; the shard's
  whole navigation floor is 153.1 MB of the 1,159.2 MB slab (13.2%); parity
  gate-ON versus OFF **5/5 bit-identical**. **Also corrected:** the "Q9 ~5,000
  pages = 20 MB constant floor" this backlog cited as the rescope target was a
  unit error — doc 10 §7.3 measured 5,093 major FAULTS carrying ~1.27 GB of
  readahead pages; there is no 20 MB slab. F4 LATENCY EFFICACY still
  **UNMEASURED** at 150M (host busy with the WS-A parity eval on 2026-08-17);
  A/B command in doc `disk_streaming_research/03` §5 step 2.
- **F3 `mlock_ranges`**: hook works; the manual 8-shard pin path (load via
  `_load_one_shard` + `mlock_ranges` per shard, 0.2 GB/shard = 1.6 GB budget)
  pinned **0.782 GB across all 8 shards** cleanly (mlock returns 0 past the
  sudo memlock ceiling at ~shard 4, no crash — the no-op fallback). The
  `load_hotset_and_pin` budget check (min(dial, MemAvailable − 1.5 − 1.0))
  works. F3 EFFICACY (latency) HOST-GATED: the 15.8 s warm≈cold regime is a
  32 GB HOST phenomenon (62 GB index > 32 GB RAM); this development container has 54 GB
  MemAvailable → warm p50 is already RAM-speed → pin-tier latency uplift is
  NOT measurable here. Latency A/B requires the operator's constrained-host run.
- **F5 `release_pages_except`**: hook built; NOT exercised (only relevant in
  the sequential-cold arm under memory pressure — host-gated). EFFICACY
  UNMEASURED. **2026-08-31: the hook's SCOPE BUG (forward slab only) is FIXED
  IN CODE + synthetically verified (4.43× dv / 9.85× f16 more bytes covered);
  real-stack efficacy still UNMEASURED — see the R1 F5 cell entry below.**
- **Phase 5 T1 (correctness re-gate with pinning ON) — 20/20 BIT-IDENTICAL
  2026-07-14** (`_t1_pin_off.json` / `_t1_pin_on.json`):
  `ParallelSeismicBackend` (2 shards, E8 v2) with `SFU_SEISMIC_PIN_BUDGET_GB=1.6`
  (0.4 GB pinned) produces bit-identical top-50 oaid-order on 20/20 diverse
  queries versus pin-OFF. The pin tier is residency-only (`_merge_topk`/scoring/
  decode untouched) → T1 by construction; asserted empirically. Run
  out-of-process (1 backend, 2 subprocesses) because 3 backends × 2 shards
  exceeds the development container's ~50 GB VmSize ceiling.
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

**MEASURED 2026-07-14 (corrected)** (`f6_prefault_hotset_20260714.json` versus
`f6_gateoff_baseline_20260714.json`; paired same-.so A/B, q7 hybrid
fadvise-DONTNEED protocol, 100 q × 3 passes × 2 reps per arm, 0 failed
queries): at load, prefault (NOT mlock) the F2 sidecar's hot extents into
the page cache via the `prefault_ranges` .so hook (gate
`SFU_SEISMIC_PREFLOOR_HOTSET=1`, extents gap-coalesced to ≤2048/shard).
Gate OFF: cold p50 666-676 ms, cold p95 **4656-4686 ms**. Gate ON: cold p50
373-490 ms, cold p95 **1464-1884 ms (median 1674)**. → **~2.8× cold-p95,
~1.5× cold-p50, warm unchanged** (52-55 ms both arms). VmSwap 0.
Attribution (corrected 2026-07-14 audit): warm improving 117→54 ms versus the
2026-07-13 baseline is an operating-conditions confound (CPU contention),
not a module win — encode (pure ONNX) also halved 30.4→16.7 ms, the 01:00
old-.so rebench under co-load still showed warm 115-126 ms, and the .so
rebuild used no target-cpu flags. Quiet-host warm ≈54 ms; co-loaded ≈120 ms.
Not prefault either way (warm identical in both arms). The gate-OFF cold
p95 matches the 2026-07-13 baseline (4576-4896 ms) — cold p95 is disk-bound
and immune to the confound — so the cold-p95 gain is genuinely the
prefault's. Result parity ON versus OFF:
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
| 12G | 1855 / 4589 ms | 22 ms | 2.4k | boundary with hysteresis (converges pass 3) |
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
prefault effect at 8G (pass 1 3.09 s versus 3.39 s). Remaining untested pin
value: protection against EXTERNAL cache competitors (not self-thrash) — a
different regime, pre-registered here as an open question, plus the
F4 navigation-floor pin (RESCOPED 2026-08-17 to ~20 MB/shard, ~160 MB total;
built + residency-measured, latency UNMEASURED — see the F4 entry above).

**F5 release-except cell (2026-07-14, `r1_cap16g_f5rel_20260714.json`) —
NULL RESULT as built, with a diagnosed scope bug.** Pass-for-pass identical
to the plain 16G cell (966/460/125 ms versus 942/463/135 ms; majflt 104k/56k/15k
both). Tell: post-release RssFile UNCHANGED (14.32 GB) despite "released
16.45 GB" — the hook only covers the **forward_data slab**, whose pages were
mostly non-resident at that moment anyway; the actual load residue lives in
the structural slabs (posting lists, doc mapping, token maps) which
`release_pages_except` does not touch. The pre-sorted-cache hypothesis
(doc `session_2026-07-14.../04_CONVERGENCE_ARTIFACT.md` §5.3) is therefore
UNTESTED, not refuted — a meaningful test needs whole-shard
fadvise-DONTNEED-except-hot or extending the hook beyond the forward slab.

> **2026-08-31 — SCOPE BUG FIXED IN CODE; EFFICACY STILL UNMEASURED ON THE
> REAL STACK.** The hook now covers every slab the mmap reader maps, not just
> the forward codec slab. Fork commit `2c4d863`; patches
> `spike/seismic_upstream_fork.patch` (umbrella, regenerated from upstream base
> `7782a13` — it had been stale since the E5 commit) +
> `spike/seismic_upstream_f5_scope_fix.patch` (focused).
>
> Two defects were behind the null, both fixed:
> 1. **Scope.** `release_pages_except` released only `_fwd_data_mmap`
>    (dv) / `_forward_values_mmap` (f16). It now releases the same slab set as
>    `release_pages()` — forward offsets, posting lists, doc-mapping
>    strings/offsets — minus the hot extents. A new `keep_structural=True`
>    argument gives an *intentional* floor-preserving arm for when F4's
>    `mlock_floor` is on; that is **not** the 2026-07-14 scope, which also
>    skipped `forward_offsets`.
> 2. **Accounting.** `os_madvise` now returns the syscall status and
>    `release_bytes` / `release_bytes_except` credit bytes **only when madvise
>    returned 0**. `MADV_DONTNEED` EINVALs over `mlock`ed ranges; the pre-fix
>    code counted those bytes regardless, which is precisely how "released
>    16.45 GB" coexisted with an unchanged RssFile. New
>    `release_pages_except_by_slab()` (Rust + pyo3) returns
>    `[(slab_name, bytes_released)]` so the same failure mode cannot hide inside
>    one aggregate again; `r1_ram_ladder.py` records it as
>    `released_by_slab_gb` in the cell JSON and warns loudly if the loaded `.so`
>    predates the fix.
>
> **Synthetic verification (no 150M index touched)** — Rust unit test
> `release_pages_except_covers_all_slabs` in
> `spike/seismic_upstream/src/mmap_io.rs` (600-doc index, both layouts, built
> + converted in-test):
>
> | layout | BEFORE (forward slab only = pre-fix scope) | AFTER (all slabs) | ratio |
> |---|---|---|---|
> | dotvbyte (served) | 9,600 B | 42,554 B | **4.43×** |
> | f16 (rollback) | 4,200 B | 41,354 B | **9.85×** |
>
> Per-slab, dotvbyte: `forward_data` 9,600 / `forward_offsets` 4,808 /
> `postings` 19,848 / `doc_strings` 3,490 / `doc_offsets` 4,808 B. The test also
> asserts pinned extents survive, that `keep_structural=True` narrows the scope
> back to the forward slab, and that search still returns results after a full
> release (residency-only, T1 unaffected). All 11 fork tests green
> (`cargo test --no-default-features --lib -- --test-threads=1`); `cargo check
> --lib` clean with the pyo3 default features.
>
> **NOT measured:** no `.so` was rebuilt and no real-stack cell was run — the
> served production `.so` still carries the pre-fix hook until an operator
> rebuilds the portable v3 target (doc 10 §7.7; never `-C target-cpu=native`
> for a shippable build). Re-running the 16 GB F5 cell requires its own
> pre-registration.

**Quality under squeeze: 40/40 bit-identical (ids + scores) versus the uncapped
reference in ALL THREE stressed cells** (8G-pin, 6G-pin, 16G-F5;
`r1_results_*.json` versus `r1_results_uncapped_ref.json`) — pressure is
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
REPRODUCED (12g p50 21 ms versus 16g 124 ms; R1 read 22 versus 135) with a refined
mechanism — the inversion is carried by residual-fault distribution across
queries, not by the smaller cap finishing the whole sort first; (3)
pressure-scaled aging — CONFIRMED by direct cgroup observation (pass-1
pgscan monotone 24g:0 → 17g:0.56M → 11g:3.5M → 6g:7.1M; ws_refault → 0 at
convergence above the cliff; active_file ends 0.2 GB at 24g — no pressure,
no promotion — versus 7.5–8.8 GB at 11g); (4) replicate spread — CONFIRMED
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

1. Converged p50 versus cap is a monotonic step; the cliff (jump from ~20 ms to
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
   that is, per-query residual-fault concentration is markedly higher at 12 GB
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
     is convergence-trajectory position at the fixed window (12g mid-sort versus
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
     **1.8%** at 12g (6538 sampled ×512 = 3.35M versus cgroup 3.29M) and **0.3%**
     at 16g (1.27M versus 1.26M) — so the *count* is sound, only the *distance*
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
     pressure-sorting) versus 16g=**0.0 GB** (held the full ~14.3 GB working set,
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
     low count, for example, the pre-fix REQ-3g 12g had lost=62,145 explicitly).
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
— sequential versus parallel federation over the served e5_v2 shards, warm AND cold,
reporting p50/p95 latency, peak RSS bound per mode, and T1 result parity.

- **Why this container, not the 31.6 GB box:** the 64 GB container (54.8 GB
  MemAvailable, 16 cores) hosts a *clean* A/B: the ~15.5 GB file-backed working
  set fits without swap in BOTH modes, so the VmSwap==0 mechanism check (H2 of
  `04_BENCHMARKING.md`) is trivially true here and not the measured verdict. What
  IS measurable here, cleanly and swap-free: (a) the latency shape of each mode
  (parallel ≈ max-shard, sequential ≈ Σ-shards) on real 150M shards warm+cold;
  (b) the peak-RssFile bound (sequential mechanism B `release_pages` keeps ~1
  shard resident versus parallel's full working set — the resident-set ratio is the
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
baseline) variants, re-run the established gates versus native on the served e5_v2
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
  computes overlap@10 (variant-top10 versus native-top10) + warm-traverse ratio.
- **Gates (the established E7 bars, math/05 worst-case-shard + n≥100):**
  - **gate a (parity):** overlap@10 ≥ **0.99**, n=100, on shard 1 AND shard 2
    (both worst-case per G8d §7.6 — never shard0-only). A CPU-target change that
    reorders FMA could alter float rounding → different top-k; this gate must
    hold. *est.*: v3 uses the SAME packed SIMD as native (objdump v3 100 vfmadd/
    13979 ymm versus native 76/15392) → parity should hold near bit-identical; v2
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

**MEASURED 2026-07-16 — v3 SHIPS (both gates PASS); v2 too slow (gate b FAIL).**
(`wi4_verdict_{v3,v2}_global_shard{1,2}*.json` + `wi4_topk_{variant,native}_
shard{1,2}.json`; 6-cell matrix, n=100, worst-case shards 1+2, E7 `run_pass`
cold+warm). Parity **BIT-IDENTICAL (overlap@10 = 1.0, min 1.0) for ALL variants
on BOTH shards** — the CPU-target change does not alter float results (v2's no-FMA
SSE path included; stronger than the pre-registration's "marginal" prediction).
v3: warm ratio **0.956 / 0.968** (≤1.07 ✅, slightly faster than native — keeps the
AVX2+FMA win while portable to any x86-64-v3 / Haswell-class CPU). v2: warm ratio
**2.20 / 2.25** (gate b ❌ — no FMA + no 256-bit → the §7.1 SSE2-baseline floor).
**v3 is the shippable portable target**; v2 stands as the pre-Haswell last-resort
fallback (parity-safe but slow). objdump: native 76 vfmadd/15392 ymm; v3 100/13979
(same FMA path); v2 2/288 (SSE-only). No served-default flip (owner-gated; the
production .so stays `native` until an operator swaps v3 in via explicit-path
load). Full write-up + the buildable recipe: doc 10 §7.7; driver
`scripts/seismic_testbed/wi4_portable_cpu_gates.py` + `wi4_run_all_gates.sh`.

### WI-6 startup-warmup hook + recovery-to-first-good-QUERY (2026-07-17, deployprep wave 2 — PRE-REGISTERED before run)

Context: WI-3 (`docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md`) measured the gap the
demo's unattended survival turns on — the watchdog restores a *healthy*
`/health` in 2.4 s after a SIGKILLed serve, but `first_client_recovery` within
the 30 s load window was **null** (829 dead-window errors, 0 client OK): the
seismic backend lazy-loads on first `/search`, so the first stranger's query
pays the cold-mmap-fault floor (WI-1 parallel cold p50 ~2.6 s seismic leg
alone, +BM25F/dense/hydration). `/health` being up ≠ `/search` being warm.

Prior art REUSED (not reinvented — per drive-prompt instruction):
- **F6 hotset prefault** (`SFU_SEISMIC_PREFLOOR_HOTSET=1`, `prefault_ranges`
  pyo3 hook over the F2 hotset sidecar) — COLD p95 4600→1674 ms (−2.9 s,
  ~2.75×) measured 2026-07-14 (`f6_prefault_hotset_20260714.json`); cold p50
  ~431 ms. Its own caveat flags the win is the **first cold query of a fresh
  process WITHOUT eviction** — that is, exactly the cold-restart scenario.
- **Q9 floor prefault** (`SFU_SEISMIC_PREFLOOR_AT_LOAD=1`) — REFUTED 2026-07-10
  (`q9_floor_prefault_20260710.json`): cold p50 ratio ON/OFF 1.025 (ON
  *slower*), load +104 s, warm 1.097, anon +0.06 GB → all bars FAIL. The
  structural-floor touch is NOT a lever in this 9p cold regime. WI-6 therefore
  builds on F6 (hotset) + a warmup query set, NOT on Q9 floor.

Hypotheses (write-before-run):
- **H1 (warmup query set):** replaying a fixed warmup query set at startup
  faults the forward pages real queries touch → first-post-restart `/search`
  p50 drops below the cold floor; recovery-to-first-good-QUERY (not just
  healthy /health) lands inside the load window (versus null in WI-3).
- **H2 (F6 hotset composition):** composing the F6 hotset prefault with the
  warmup queries shifts the cold-tail (p95) more than warmup queries alone
  (F6 targets structural hot extents; warmup queries target forward data).
- **H3 (no result drift):** warmup is read-only page-touching + real queries;
  recall parity versus the unwarmmed serve is bit-identical (overlap@10 = 1.0).

Bars:
- recovery-to-first-good-QUERY after SIGKILL < WI-3's window (which = ∞ / null)
  and ≤ 2× the watchdog's health-recovery (2.4 s) → that is, first real `/search`
  completes warm in ≤ ~5 s of the kill.
- warmup-set size bounded (≤ ~64 queries · low top_k) so startup (re)start
  cost stays < ~60 s (F6 load ~ +1 s in-container; warmup queries dominate).
- warm p50 unchanged by the hook once warm (hook is startup-only).
- overlap@10 warmup-on versus warmup-off = 1.0 (no drift) on the probe set.
- If H1 returns a smaller win than the bar, record honestly and escalate the
  remaining cold gap (a non-staging, owner-gated mlock/pin tier) — don't claim it closed.

Verdict goes here + `docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md` (append to the
existing induced-failure section, before versus after the hook). Result JSONs:
`data/eval_results/wi6_*{before,after}*.json`. **No served-default flip**
(the hook is staging-env-gated, off by default; the served path is unchanged).

**MEASURED 2026-07-17 (9p cold-load regime):** the hook is CORRECT but the
container's 9p mount keeps the bar unmet here.
- **H1 (warmup → first-good-query in window): PARTIAL / bar NOT met on 9p.**
  The hook makes the INITIAL startup warm — `/health` flips to `warm=true` after
  a 302 s warmup (24 queries fault the forward pages; result
  `wi6_recover_after_20260717_005541.json`, `ready after 302s`). BEFORE arm
  reproduced WI-3 exactly: **1147 dead-window errors, 0 client OK,
  first_client_recovery=null**, watchdog health-recovery **2724 ms**
  (`wi6_recover_before_20260717_005541.json` + `_wi6_watchdog_report_before.json`).
  The **360 s-window AFTER run** (`wi6_recover_after_long_20260717_010457.json`)
  flipped `first_client_recovery` from null to a measured **323998 ms (~5.4 min)**
  with **73 client OKs** (p50 4878 ms) + watchdog warm-recovery **319215 ms**
  (`_wi6_watchdog_report_after_long`) — the hook IS correct (the restarted serve
  re-warms + answers warm queries), but the re-warm takes ~5.4 min on 9p (the
  process-cold page cache re-faults the whole working set), so **the bar (first
  good query ≤~5 s post-kill) is NOT met on 9p.** It IS met on a native-ext4
  host (ms cold faults) + with an mlock'd hot set (hotset prefault = reclaimable;
  mlock = non-reclaimable, survives restart).
- **H2 (F6 composition): not cleanly separable** — the onnxruntime-on-9p
  transient made the warmup run BM25F-fallback, so the F6 hotset's cold-tail
  contribution to the warmup wasn't isolated. F6's own 4600→1674 ms cold-p95
  (re-measured under its own protocol) stands as the lever's number.
- **H3 (no drift): N/A this run** — the warmup fell back to BM25F (seismic leg
  skipped), so the drift check wasn't exercised; design says read-only, no drift.
- **Honest escalation (per the bar's own clause):** the remaining cold gap is a
  **host-tier mlock/pin tier** (owner-gated, not done here) — F6 prefault makes
  pages reclaimable, so a process restart re-faults; mlock makes them
  non-reclaimable, surviving a restart without re-faulting. **The bar WOULD be
  met on a native-ext4 host** (cold faulting ms-scale there versus 9p's seconds) and
  with an mlock'd hot set on 9p. A longer-window (360 s) re-run is in flight to
  capture the real 9p warm-recovery number; that lands in
  `DEMO_DEPENDABILITY.md` + here.

### WI-7 warm-state concurrent capacity sweep (2026-07-17, deployprep wave 2 — PRE-REGISTERED before run)

Context: WI-3's baseline sweep measured the COLD floor (~4–6 s p50 over a
20-query diverse working set — honest but NOT the demo's steady state; a
warmed serve answers at sub-100 ms, WI-1 parallel warm p50 47 ms). This is the
demo's real capacity figure + the input the DO-sizing doc needs.

Hypotheses:
- **H1:** a pre-warmed serve (majflt quiet, working set resident) holds p50
  ≤ ~150 ms and p95 ≤ ~500 ms at concurrency 1–16 under steady strangers'
  traffic, with 0% errors (versus the cold 4–6 s p50 / graceful-degradation shape).
- **H2:** throughput scales near-linearly with concurrency up to the GIL/pyseismic
  fan-out ceiling, then flattens (the ThreadingHTTPServer concurrency story).

Bars:
- warm p50 ≤ 250 ms AND error rate 0% at every level (1/4/8/16, +32 if stable).
- warm majflt over the sweep ≈ 0 (verify warm state, not cold re-faulting).
- throughput monotone non-decreasing across levels (no regression cliff).
- If p50 stays high (warm ≠ cold here means the working set didn't fit), record
  that the demo's real capacity is working-set-bound, NOT compute-bound, and
  flag the sizing implication for `docs/archive/bmp_decommission_plan/DO_SIZING.md`.

Verdict goes here + `docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md` (a new
warm-capacity section). Result JSON: `data/eval_results/wi7_warm_capacity_*.json`.
**Numbers only — no provisioning.** If the warm figures change DO_SIZING's
assumptions (the doc is Qdrant-era 545–861 ms cold; the served stack is now
SEISMIC), a pointer row is added to DO_SIZING — no served-default flip.

**MEASURED 2026-07-17** (`wi7_warm_capacity_20260717_011753.json` + per-cell
`_wi7_cell_c{1,4,8,16,32}_20260717_011753.json`; serve pre-warmed via WI-6 hook,
warmup 310.5 s → /health warm=true; 40 reqs/level, 20-query diverse set,
top_k=10, 3-leg RRF over served e5_v2, watchdog-supervised):

| c | p50 ms | p95 ms | errors | qps | majflt Δ |
|---|---|---|---|---|---|
| 1 | 3327 | 4058 | 0/40 (0%) | 0.4 | 4608 |
| 4 | 3767 | 4566 | 0/40 (0%) | 1.2 | 7321 |
| 8 | 4304 | 5361 | 0/40 (0%) | 2.1 | 8172 |
| 16 | 6111 | 8309 | 0/40 (0%) | 2.7 | 16552 |
| 32 | 10344 | 13562 | 0/40 (0%) | 2.9 | 23908 |

- **H1 (warm p50 ≤250 ms, 0% errors): PARTIAL on 9p.** 0% errors at every level
  (200/200 succeeded) ✅, BUT warm p50 3.3–10.3 s on 9p — the bar's ≤250 ms is
  **NOT met on 9p**. Reason: the 20-query diverse working set (~15 GB forward
  index) is NOT fully resident — majflt Δ rises with concurrency (4608→23908),
  proving cold re-faulting under contention, not compute-bound latency. This is
  exactly the bar's own fallback clause: "the demo's real capacity is working-
  set-bound, NOT compute-bound on 9p." **On a native-ext4 host (RAM ≥ ~16 GB
  working set)** the warm p50 drops to WI-1's tens-of-ms (47 ms) — the page
  cache holds the working set without 9p's fault penalty; the 0%-error +
  monotone-throughput transfer.
- **H2 (near-linear throughput to the GIL ceiling): CONFIRMED.** Throughput
  monotone non-decreasing 0.4→2.9 qps across 1→32, no regression cliff — the
  ThreadingHTTPServer + GIL-releasing pyseismic fan-out gives real parallelism.
- **Bars:** error 0% ✅; throughput monotone ✅; warm p50 ≤250 ms ❌ on 9p (the
  working-set-bound clause); majflt ≈0 ❌ (9p re-faults under contention).
- **DO_SIZING pointer ADDED** (the served stack is SEISMIC not Qdrant; the
  Qdrant-era 545–861 ms figures don't apply to the SEISMIC path): a banner row
  at the top of `docs/archive/bmp_decommission_plan/DO_SIZING.md` points at this WI-7
  result. **No served-default flip** (numbers only; SEISMIC has been the served
  default since 2026-07-06, this just records the SEISMIC capacity figure).


## WI-9..WI-12 system-wide reliability + graceful degradation (2026-07-17, deployprep wave 3 — PRE-REGISTERED before run)

**Parent:** `docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md` (the WI-3/6/7 harness).
Wave 3 is system-wide: not one leg — the WHOLE served search path
(BM25F/tantivy + SPLADE/SEISMIC-8-shard federation + dense/usearch + RRF +
hydration + the WI-3/6 staging serve/watchdog). All four ship env-gated OFF by
default (no served-default flip; off = byte-identical to wave 1/2 behavior).
Owner constraints identical to wave 1: NO deploy / NO DO spend / NO TrueNAS /
NO served-default flips; `data/seismic_150m/` READ-ONLY — fault injection NEVER
corrupts/renames real shards (via mocks/env/wrappers/small FIXTURE copies only).

### WI-9 leg-level graceful degradation + fault-injection proof (system)
| field | value |
|---|---|
| hypothesis | Today a dead/hung leg fails the whole query (BM25F leg throws → 5xx; encoder hang → client timeout storm). A per-leg timeout budget + a circuit breaker (N consecutive leg failures → skip leg, retry-probe after cooldown) + RRF over surviving legs with a `degraded:[legs]` flag + `/health` `degraded` state between ok/dead + encoder-failure→lexical degrade lets a dependable demo SERVE DEGRADED RESULTS instead of failing the query. |
| prediction (*est.*) | Under each induced single-leg fault (SPLADE hung, dense erroring, encoder down): 0% 5xx on the faulted queries (degraded instead), results still returned (BM25F leg still answers), `degraded` flag names the right leg, breaker recovers (re-admits the leg) within cooldown after the fault clears. p50 of ACCEPTED queries during the fault ≤ ~2× the unfaulted p50. |
| decision rule | bars PASS if all four hold: (a) no 5xx storm under any single-leg fault, (b) >0 results returned for every fault class, (c) `degraded:[…]` names exactly the injected leg, (d) breaker re-admits the leg (degrade clears) after cooldown once the fault clears. FAIL otherwise (record which bar broke). |
| gate environment variables | `SFU_DEMO_LEG_BREAKER=1`, `SFU_DEMO_LEG_TIMEOUT_S` (default 30), `SFU_DEMO_LEG_BREAKER_N` (default 3 consecutive fails), `SFU_DEMO_LEG_BREAKER_COOLDOWN_S` (default 8). All default OFF = wave-1 behavior. |
| result | `data/eval_results/wi9_*.json`; verdict → `DEMO_DEPENDABILITY.md` §WI-9. |

**MEASURED 2026-07-17** (`wi9_fault_injection_20260717_022742.json`): **PASS — 20/20
bars** (all 5 fault classes × all 4 bars). SPLADE-hung DURING p50=30 002 ms (the
abandoned timeout) but `degraded=['splade']` ONLY (isolation works: bm25f+dense
healthy — the dedicated-thread-per-leg fix); bm25f_error degrades to 115 ms p50
instead of a 5xx; encoder_down `degraded=[]` (graceful mirror, breaker correctly
NOT tripped). All cells recover after cooldown. `degraded` flag + `/health`
`degraded` state wired into `staging_serve.py` (env-gated OFF). Verdict +
per-fault p50/p95 → `DEMO_DEPENDABILITY.md` §WI-9.

### WI-10 shard-failure isolation: one shard down, seven serve (system, OWNER ASK 2026-07-17)
| field | value |
|---|---|
| hypothesis | The owner requires: if ANY one of the 8 SEISMIC shards fails (missing/truncated/unreadable file, search exception, hang/timeout), the OTHER 7 keep working independently. Per-shard LOAD AND per-shard SEARCH fault boundaries in BOTH federation classes (`ParallelSeismicBackend` + `SequentialSeismicBackend`): a failed-to-load or failed-to-search or timed-out shard is marked failed + skipped; the federation merges surviving shards' results with `degraded_shards:[…]`; `/health` reports it; a retry-probe re-admits on recovery. Hash sharding ⇒ a lost shard costs a BOUNDED ~1/8 of recall with no score-comparability issue (doc 09: calibration unnecessary by construction). |
| prediction (*est.*) | Under each single-shard fault class (absent file, truncated fixture, search exception, hang/timeout): the other 7 shards load+serve (0% 5xx), overlap@10 + recall retention versus the full 8-shard federation ≈ 7/8 (=0.875, the bounded-loss claim), latency during the fault ≤ ~the full-federation p95 (no pileup), and re-admission works (the shard rejoins after the fault clears). The PARALLEL + SEQUENTIAL classes both isolate (the cascade design: _fan_out is the only per-method behavior). |
| decision rule | bars PASS if all hold: (a) other 7 serve under every fault class with 0% throw-ups, (b) recall retention@10 ∈ [0.80, 0.95] for a dropped shard (≈7/8 bounded), (c) `degraded_shards:[shard]` names the right shard, (d) re-admission clears the flag after the fault clears, (e) BOTH parallel + sequential classes pass. |
| gate environment variables | `SFU_SEISMIC_SHARD_FAULT_BOUNDARY=1` (load+search fault isolation), `SFU_SEISMIC_SHARD_SEARCH_TIMEOUT_S` (default 30), re-admit cooldown `SFU_SEISMIC_SHARD_REPROBE_S` (default 10). Default OFF = bit-identical federation (T1 unaffected: a non-faulted shard set has zero behavioral change). **READ-ONLY shards:** fault injection via tiny COPY fixtures under `data/eval_results/_fixtures/` or manifest-override environment variables, NEVER the real `data/seismic_150m/` files. |
| result | `data/eval_results/wi10_*.json`; verdict → `DEMO_DEPENDABILITY.md` §WI-10. |

**MEASURED 2026-07-17** (`wi10_shard_isolation_20260717_023630.json`): **PASS — all
5 cells, all bars. The owner-ask property HOLDS.** Search-exception, search-hang,
load-absent, load-truncated (parallel) + search-exception (sequential): every
fault → the other shards load+serve (0 throw-ups, 7/8 load on the load faults),
`degraded_shards` names the failed shard, re-admission clears it. Recall
retention@10 = **0.850 across every cell** (in the [0.80, 0.95] bar, = the bounded
~7/8 hash-sharding loss, measured exactly as predicted — a dropped shard is a
disjoint doc-id hash partition, no score-comparability issue). Fault p50 98–270 ms
(no pileup). `_FaultyShard` wrapper used for the search faults (pyo3 `.search` is
read-only); manifest-override + corrupt fixture under `_fixtures/` for load faults.

### WI-11 overload protection: shed, don't collapse (system)
| field | value |
|---|---|
| hypothesis | WI-3/7 measured capacity (~2.9 qps warm knee). Past capacity the serve must degrade gracefully — bounded in-flight concurrency + bounded accept queue, clean HTTP 429 + `Retry-After` on shed, NEVER an unbounded pileup (the cliff where p95 → ∞ + connection resets). |
| prediction (*est.*) | Driving load at 2–4× the WI-7 warm knee: p95 of ACCEPTED requests stays within ~2× the WI-7 warm p95 (no collapse), shed requests get clean 429s (no timeouts/connection resets), and the serve returns to WI-7 baseline within one bar after load drops. |
| decision rule | bars PASS if: (a) accepted-request p95 during overload ≤ ~3× the WI-7 warm p95 (bounded tail, not ∞), (b) shed fraction returns clean 429 (no `socket.timeout`/ConnectionResetError among sheds), (c) post-overload p50 returns to within ~1.5× the pre-overload baseline within the recovery bar. |
| gate environment variables | `SFU_DEMO_OVERLOAD_SHED=1`, `SFU_DEMO_MAX_INFLIGHT` (default 2× WI-7 knee workers), `SFU_DEMO_ACCEPT_QUEUE` (default 64). Default OFF = unbounded (wave-2 behavior). |
| result | `data/eval_results/wi11_*.json`; verdict → `DEMO_DEPENDABILITY.md` §WI-11. |

**MEASURED 2026-07-17** (`wi11_overload_20260717_030631.json`): **PASS — all 3
bars.** c=128 (8× the 16-slot gate depth, 4× the c=32 knee): **175 clean 429 sheds**,
21 accepted, 4 collapses (2% ≤ the 5% documented socket-edge bar). Accepted p95
11 917 ms ≤ 3× baseline (bounded, not ∞); post-overload p50 4381 ≤ 1.5× the 4186
baseline (recovery). The gate sheds cleanly via 429+Retry-After instead of an
unbounded pileup; raised socket backlog kept collapses a small minority.

### WI-12 repeatable reliability soak job — the pre-launch gate (system)
| field | value |
|---|---|
| hypothesis | A single runnable job `scripts/archive/demo_dependability/reliability_soak.sh` the owner can run before any demo launch: ~40-min soak at modest QPS with a SCHEDULED fault timeline injected mid-soak (a WI-9 leg fault, a WI-10 shard fault, a WI-11 overload burst, a WI-3/6 watchdog SIGKILL/restart) emits one timeline report JSON + markdown summary: availability %, error budget, per-phase p50/p95, every degradation/recovery event with timestamps, PASS/FAIL versus pre-registered bars. |
| prediction (*est.*) | End-to-end run: availability ≥ 95% over the soak (degraded-ok counts as available; 5xx counts against), every injected fault surfaces a `degraded`/`degraded_shards` event + a recovery event on its timeline, the per-phase p95 within each fault window stays bounded (no collapse across faults). |
| decision rule | bars PASS if: (a) availability ≥ 95% (5xx + timeouts ≤ 5% of accepted), (b) every injected fault produces a degradation event + a recovery event with both timestamps recorded, (c) the soak's worst-phase p95 ≤ ~5× the warm baseline (no cascade collapse across compounded faults). Run ONCE end-to-end tonight (bars pre-registered first). |
| gate environment variables | compose WI-9/10/11 + WI-6 + watchdog all ON for the soak; the job itself is staging-only. `SFU_DEMO_SOAK_QPS` (default 0.3), `SFU_DEMO_SOAK_MIN` (default 40). |
| result | `data/eval_results/wi12_soak_*.json` + `.md`; verdict → `DEMO_DEPENDABILITY.md` §WI-12 + this row. Named the **pre-launch reliability gate** in `docs/README.md`. |

**MEASURED 2026-07-17** (`wi12_soak_20260717_032757.json` + `.md`; 30 min @ 0.3
qps, 540 requests, all WI mechanisms ON): **FAIL on bar (a); PASS on (b) + (c).**
The single end-to-end run ran cleanly — the scheduled fault timeline fired on
schedule (phase-1 baseline → phase-2 overload burst → phase-3 watchdog
SIGKILL/restart → phase-4 final), every injected fault produced a degradation +
recovery event timestamped (b ✅), worst-phase p95 3405 ms ≤ 5× baseline (c ✅).
**Bar (a) FAILS at 82.2% availability** = the documented WI-6 finding in soak
form, NOT a new failure: the 96 fails are the ~5.2-min SIGKILL-re-warm dead-
window (`recovery_ms_warm = 312 856 ms`, the 9p cold-fault floor — the same WI-6
re-warm number). 5.2 min dead-window / 30-min soak = ~17.8% fail. On a native-
ext4 host (ms-scale re-warm per WI-6) the dead-window collapses to seconds →
availability ≥ 95% passes. The gate is runnable + correct + measured; the owner
runs `reliability_soak.sh` before any demo launch on the demo's REAL host. Bar (a)
needs the host-tier mlock/pin (owner-gated) to pass on this 9p container — the
same gap WI-6 already owns.

**MEASURED 2026-07-28 — route B, ext4-overlay attempt (SMOKE-GATE STOPPED,
full soak NOT run):** moved the served SEISMIC shard set (42 GB, 8 shards) off
9p onto container-local ext4-overlay via `SFU_SEISMIC_STAGE_DIR` (the existing
`retriever._stage_shards_local()` lever — better than a hand-edited manifest,
which was the original plan). Smoke induced-failure cell (SIGKILL + watchdog
wait-warm, alt port 8261): warm-recovery **319 215 ms (9p) → 159 124 ms
(ext4-overlay)**, a real ~2× improvement, but **above the pre-registered ~85 s
smoke go/no-go gate**, so the full 30-min soak was not run (it would predictably
still fail bar (a): ~91.2% projected availability, short of ≥95%, though closer
than 9p's 82.2%). Root cause (direct in-process timing,
`wi12_ext4_diagnosis_20260728.json`): the 9p per-fault penalty IS fixed
(federation auto-selects `parallel`, confirming the path is no longer flagged
slow), but first-touching 42 GB on *this sandboxed container's* WSL2-virtualized
overlay still costs ~80–95 s under memory pressure (served working set ~85 GB+
versus 56 GB container RAM) plus a ~18 s non-disk encoder/hydration overhead
present in both arms. Verdict: MEASURED, NOT PASSED here — the ext4 hypothesis
is confirmed in direction; a real droplet's native NVMe (the deploy shape this
was proxying) is expected to clear the bar where this sandbox does not. Full
detail → `DEMO_DEPENDABILITY.md` §WI-12 route B.

## WI-13/WI-14 update mechanisms for the demo + portable build (2026-07-17, deployprep wave 4 — PRE-REGISTERED before run)

**Parent:** `docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md` (WI-13) +
`docs/infrastructure/PORTABLE_STACK_MANIFEST.md` (WI-14). The demo and the
portable build must each have a METHOD OF BEING UPDATED — pending upgrades and
research (E8 stages, encoder work, index rebuilds, .so rebuilds) WILL change
code and artifacts after deploy/handout. Wave 4 codifies the update unit and
proves the update + auto-rollback flow against FIXTURE artifacts (STAGING ONLY;
never a real remote, never the real served shard set). Owner constraints
identical to wave 1: NO deploy / NO DO spend / NO TrueNAS / NO served-default
flips; `data/seismic_150m/` READ-ONLY.

### WI-13 versioned update + rollback for the demo host (system)
| field | value |
|---|---|
| hypothesis | The demo's update unit is the 4-tuple (code rev, seismic .so variant, index manifest, model files). The repository ALREADY serves off an immutable-artifact + manifest-flip pattern with one-env rollback (E5/E8 rollouts — `THIN_CLIENT_SWAP.md` §+retriever `_seismic_backend`). Codifying it: (a) a `deploy_versions.json` capturing the four components with sha256 + absolute date, generated by script; (b) an `update_demo.sh` staging flow: git pull → verify artifact checksums → stage new beside old (never in-place) → flip manifest/env → warm-restart via the WI-3/6 watchdog (wait-warm) → health+smoke gate → AUTO-ROLLBACK on gate failure (flip back, warm-restart, verify). (c) PROOF against the staging serve with FIXTURE artifacts. |
| prediction (*est.*) | One successful fixture update: a stable serve is running; the updater stages a *new* fixture manifest + .so, flips, the watchdog warm-restarts (WI-6 wait-warm), the post-flip health+smoke gate passes, downtime = the warm-restart window (seconds-to-minutes on 9p), no rollback. One deliberately-broken fixture update (corrupt fixture .so or a failing smoke): the gate FAILS, the updater AUTO-ROLLS BACK to the prior manifest/env (old files still present under the stage-beside discipline), warm-restarts, and the post-rollback gate passes → serve ends in a SERVING state (the rollback is not itself a failure). Both timelines recorded with per-step timestamps. |
| decision rule | bars PASS if all hold: (a) the success arm flips to the new version with a passing post-flip gate + no rollback, (b) the broken arm's gate FAILS and the auto-rollback restores a serving state whose post-rollback health+smoke gate PASSES (serve answers real queries on the rolled-back version), (c) the stage-beside discipline means the pre-update artifacts survive the broken flip (rollback does not depend on re-fetch), (d) `deploy_versions.json` checksums verify before + after for each arm (a checksum mismatch aborts BEFORE the flip). |
| gate environment variables | the flow exercises the EXISTING WI-3/6 watchdog + staging serve + manifest ladder; the only new environment is the updater's own: `SFU_DEMO_UPDATE_PORT` (staging port), `SFU_DEMO_UPDATE_GATE_QUERIES` (smoke count), `SFU_DEMO_UPDATE_NO_ROLLBACK=1` (debug kill-switch). No served-default flip — the updater points a *staging* serve at a *staging* manifest, never the promoted e5_v2 default. |
| result | `data/eval_results/wi13_update_*.json`; verdict → `DEMO_DEPENDABILITY.md` §WI-13. |

**MEASURED 2026-07-17** (`wi13_update_success_20260717_045419.json` +
`wi13_update_broken_20260717_045419.json`): **PASS — all 4 bars.**
- Success arm: checksum-verify OK → flip → warm-restart (wait-warm) →
  `new_gate smoke=pass (seismic_loaded=True)` → committed, NO rollback.
  Downtime 226 585 ms (bar a ✅). Bar (d) ✅ — checksums verified before+after.
- Broken arm (truncated shard0 fixture): the serve comes up via the silent BM25F
  fallback (`wait_warm=ok`) BUT the strengthened `/verify` gate catches
  `seismic_loaded=False` (the SEISMIC shard set did NOT load; `/health` alone
  reports `splade.configured="seismic"` either way — the retriever falls back to
  BM25F on a broken shard) → gate FAILS → AUTO-ROLLBACK → `rollback_gate
  smoke=pass (seismic_loaded=True)` → serve re-serving on the prior version
  (bar b ✅ — broken update auto-rolls back to a SERVING state). Bar (c) ✅ —
  stage-beside keeps the pre-update artifacts (old manifest + shards untouched;
  rollback needs no re-fetch). `overall=PASS_ROLLED_BACK, rolled_back=True`,
  downtime-before-rollback 186 913 ms.
- **Gate-strengthening finding (recorded, not papered):** the FIRST broken-arm
  run surfaced that `/health` + a 200 `/search` (from BM25F) would COMMIT a
  silently-degraded SEISMIC update — the exact failure auto-rollback prevents.
  Fix: `staging_serve.py` `/verify` endpoint (`SFU_DEMO_UPDATE_VERIFY_SEISMIC=1`,
  OFF by default = byte-identical serve) forces `_seismic_backend()` + reports
  `seismic_loaded`; the gate asserts it. Verified directly: good manifest →
  `seismic_loaded=True`; broken → `_seismic_backend()` raises `OSError` →
  `seismic_loaded=False` → gate fail → rollback. Verdict →
  `DEMO_DEPENDABILITY.md` §WI-13.

### WI-14 update path for the handout bundle (portable)
| field | value |
|---|---|
| hypothesis | A 20–185 GB bundle can't be re-downloaded per update; the WI-8 `portable_stack_manifest.json` becomes the UPDATE CONTRACT once it carries per-artifact sha256 + version + byte size (shard-granular for indexes — immutable shards mean an index update = replace the CHANGED shard files + flip the bundle manifest). (a) extend the WI-8 generator with sha256+version+bytes per artifact; (b) `updater_check.py`: given a local bundle manifest + a "remote" manifest FILE (simulated locally, NO network), emit the delta plan (files to fetch, total download bytes, files unchanged, apply order: artifacts first, manifest flip last, old files kept until verify — crash-safe); (c) `updater_apply.py` staging proof on a small FIXTURE bundle: apply a delta (one changed shard fixture + one changed model fixture), verify checksums, flip, prove the pre-update bundle is restorable (rollback = re-flip to old manifest, old files present). |
| prediction (*est.*) | (a) the versioned manifest lists every artifact with a stable sha256 (shards + .so + models + tantivy segments); (b) for a delta with 1 changed shard fixture + 1 changed model fixture: `updater_check.py` reports exactly those 2 files to fetch, the rest unchanged, total download bytes = sum of the 2 changed, apply order = changed-artifacts → verify → manifest-flip-last; (c) `updater_apply.py` applies the delta, post-apply checksums verify, the flipped bundle serves; rollback re-flips to the old manifest + the old shard/model files are STILL present (kept by the keep-old-until-verify discipline) → pre-update bundle restorable crash-safely. Different update classes cost wildly different bytes (E8 re-conversion = all shards change ~26 GB; encoder distill = models only ~1 GB; .so rebuild = 2.7 MB). |
| decision rule | bars PASS if all hold: (a) every manifest artifact carries sha256+version+bytes (the contract is machine-checkable), (b) the delta plan names exactly the changed files + a crash-safe apply order (manifest flip last, old files retained), (c) the apply proof verifies post-apply checksums AND proves rollback by re-flipping to the old manifest with old files present, (d) the per-class delta-byte expectations (all-shards versus models-only versus .so-only) are recorded in the doc with the known pending-upgrade mapping. DESIGN-ONLY (no build here): the `semantic_docid_ingest` LSM track is flagged as the eventual incremental-DATA path, not built this wave. |
| gate environment variables | no served path touched; the fixture bundle lives under `data/eval_results/_fixtures/`. `SFU_PORTABLE_BUNDLE_FIXTURE_DIR` (default the _fixtures directory). |
| result | `data/eval_results/portable_stack_manifest.json` (versioned) + `wi14_delta_plan_*.json`; verdict → `PORTABLE_STACK_MANIFEST.md` §(e). |

**MEASURED 2026-07-17** (`wi14_apply_proof_20260717.json` +
`portable_bundle_versions.json`): **PASS — all 4 bars.**
- Versioned manifest (bar a): 123 artifacts, each with sha256 + version + bytes.
  8 seismic shard entries shard-granular in POINTER-mode (each shard's
  `manifest.json` pointer that flips on a re-conversion — NOT 66 GB of shard
  data re-checksummed, which would contend with the live serve on the 9p mount);
  `.so` + model weights full-sha256. `channel=stable, bundle_version=1.0.0`.
- check delta plan (bar b): for a v1→v2 delta with 2 changed files (shard1
  `data.bin` + splade `model.onnx`), names EXACTLY those 2 (per-file precision),
  the rest unchanged; crash-safe apply order (artifacts-first → verify →
  manifest-flip-LAST → keep-old-until-verify); rollback = re-flip to old manifest
  (old files retained, no re-fetch). `wi14_apply_delta_20260717.json`.
- apply proof (bars c+d): PASS — 2 files staged beside old (old untouched),
  sha256-verified before the flip, manifest flipped v1→v2, then rollback re-flips
  to v1 with old shard0 directory + old shard1/data.bin + old splade weight ALL still
  present (keep-old-until-verify → crash-safe, no re-fetch). `overall=PASS`,
  bars `{b_fetch_exact, c_applied_and_verified, d_rollback_old_files_present}`
  all True.
- Per-class delta-byte expectations recorded (bar d): `.so` rebuild ~2.7 MB,
  encoder distill ~1 GB, E8 dv-v2 re-conversion ~26 GB, manifest-flip-only
  ~7.5 KB (the pointer; shards resident → 0 data). DESIGN-ONLY:
  `semantic_docid_ingest` LSM track = the eventual incremental-DATA path (new
  docs without a re-shard), flagged not built. Verdict →
  `PORTABLE_STACK_MANIFEST.md` §(e).

## WI-16 GUI full-interaction testbed (2026-07-17, deployprep wave 6 — PRE-REGISTERED before run)

Plan: `docs/infrastructure/GUI_INTERACTION_TESTBED_PLAN.md` (architecture §1,
oracle §2, four generator layers §3, verdict/regression contract §4). The
model is `GUI_BAREBONES_PROGRESS_SPEC.md` §2 (the Interface toggles ARE the
model). No serving-path/API changes — `scripts/gui_testbed/` + docs only; `web/`
touched ONLY to fix a defect the testbed found (commit `3836f64`, see bar L-D).

| field | value |
|---|---|
| hypothesis | A layered action-generation testbed over one shared invariant oracle (zero pageerror + zero console.error + zero overflow + event-loop alive + honesty floor) catches GUI regressions the 4-static-viewport `e2e_sweep.mjs` misses — especially across the width axis and under chaos (backend-dead, hang, 429-storm, storage-corrupt). Vendored gremlins.js + seeded Chance ⇒ every failure replays deterministically. |
| prediction (*est.*) | L-A: every interactive element enumerates green (zero pageerror/console.error/overflow). L-B: 100% of the spec-§2 states + events reached/fired. L-C: zero pageerror across N=10 seeds × 5 modes × 60 s. L-D: zero overflow across the 320→1920 w-sweep + mid-skeleton resize no-shift. Total runtime ≤ 20 min. |
| decision rule | bars PASS if all hold: (a) L-A zero pageerror/console.error/overflow, (b) L-B all_states_reached AND all_events_fired, (c) L-C zero pageerror across the matrix AND every failing seed replay-confirmed then in `regression_seeds.json` (runs first, forever), (d) L-D mid_skeleton_no_shift AND zero overflow across the w-sweep (the 4px-tolerance bar). A bar that can't pass is recorded honestly with the failing seed/action — refuted expectations are valid results (drive-prompt rule). |
| gate environment variables | `PW=/home/vscode/.npm/_npx/e41f203b7505f1fb/node_modules` (Playwright in the npx cache, NOT node_modules — the e2e_sweep pattern); `GUITB_SEEDS`, `GUITB_ATTACK_MS` scale L-C; the static server is `scripts/gui_testbed/static_server.mjs` (no backend; app boots to mock+banner). |
| result | `data/eval_results/gui_testbed_2026-07-17.json` (roll-up) + `gui_testbed_l{a,b,c,d}_*_2026-07-17.json`; `scripts/gui_testbed/regression_seeds.json`; verdict → `GUI_INTERACTION_TESTBED_PLAN.md` §0 "MEASURED 2026-07-17". |

**MEASURED 2026-07-17** (`gui_testbed_la_enum_2026-07-17.json` + lb/ld +
roll-up): **bars by-layer — L-A PASS, L-B PASS, L-D partial (1/101 widths).**
- L-A enum (bar a): PASS — 304 actions / 298 states, zero pageerror/console
  error/overflow. Every interactive element across search/analytics/
  index_manager + keyboard Tab pass + garbage-type pass (unicode, 10 kB,
  `<script>`, RTL, SQL-probe).
- L-B model (bar b): PASS — 8 states reached (6 search screens + analytics +
  index_manager), 23 events fired, **100% state + event coverage**, 0 failures.
- L-C monkey (bar c): per-roll-up JSON — seeded reproducibility host-verified
  (same Chance seed ⇒ identical click-coord streams); N=10 seeds × 5 modes
  with replay-confirmed regression seeds. Zero pageerror is the L-C bar;
  gremlins-induced transient overflow is tracked + recorded (not a stable
  defect — the per-action oracle catches it mid-reflow).
- L-D resize (bar d): **PARTIAL — found + fixed a real defect.** The continuous
  w-sweep caught a 242px `main`-overflow at 320px that the ≥1280px e2e_sweep
  viewports never exercise (search-bar flex row lacked `minWidth:0` + landing
  hardcoded `0 60px` padding). Fix commit `3836f64`: 242px@320 → 14px@320,
  **zero overflow 336→1920px** (100/101 widths); mid_skeleton_no_shift TRUE.
  The residual 14px@320 is the honest recorded FAIL at an extreme edge below
  any viewport this desktop-sidebar suite targets (html `overflow:hidden` ⇒ a
  clip, not a visible scrollbar). No regression at ≥1280px (e2e_sweep +
  verify_web_jsdom 14/14 + verify_web_progress 18/18 unchanged).
- Live `e2e_sweep.mjs` baseline run (WI-16a precondition — first live run in
  this container): search + index_manager clean; analytics logs 7× `404`
  console.error on the static-only serve (graceful mock fallback, no crash — a
  backend-absence condition covered by the L-C backend-dead chaos arm, not a
  `web/` defect).

### WI-16f vendored axe-core a11y scan (stretch, 2026-07-17 deployprep wave 6)

| field | value |
|---|---|
| hypothesis | A vendored axe-core a11y scan per screen extends the invariant oracle with WCAG 2.1 AA findings the functional layers (pageerror/console/overflow) don't cover; recording them honestly surfaces remediation debt without blocking the gate. |
| prediction (*est.*) | a handful of contrast + label + ARIA violations, mostly in the icon-button + dark-sidebar styling; the role="switch" toggles may trip aria-allowed/required-attr (aria-pressed versus aria-checked). |
| decision rule | MEASUREMENT-ONLY (not a gate) — record every violation: id, impact, count, node target + failure summary. Fix NOTHING outside web/ defect rules (drive-prompt WI-16f). Verdict goes to `gui_testbed_lf_a11y_2026-07-17.json` + the plan §0 table. |
| result | `data/eval_results/gui_testbed_lf_a11y_2026-07-17.json`; verdict → `GUI_INTERACTION_TESTBED_PLAN.md` §0. |

**MEASURED 2026-07-17** (`gui_testbed_lf_a11y_2026-07-17.json`): 5 screens,
174 violations, 5 distinct rules — color-contrast (serious, 149; the
`--text-muted`/light tokens on the dark sidebar), button-name (critical, 11;
icon-only buttons missing `aria-label`), label (critical, 2; the Ollama URL
input), aria-allowed-attr (critical, 6) + aria-required-attr (critical, 6; the
`role="switch"` Interface toggles use `aria-pressed` but the switch role
REQUIRES `aria-checked` — `search.jsx:2088`). Recorded for future remediation;
NO fixes this wave (WI-16f is measurement-only by directive).

## WI-17 read-through result cache + pre-seed primer (2026-07-18, deployprep wave 7 — PRE-REGISTERED before run)

Owner decision 2026-07-18: wire the existing `lib/cache.ResponseCache` into the
GUI `/api/search` path as a read-through result cache and pre-seed it with the
demo's own queries. Keystroke speculation is OUT of scope. Contract terms are
owner-audited 2026-07-18 (binding — see `source/lib/result_cache.py` docstring
header) — the bars below check them.

| field | value |
|---|---|
| hypothesis | A read-through result cache on `/api/search` (normalized+versioned key; never cache errors/degraded/cold; cache-failure fall-through; TTL hours, max_size ≥ 200) makes repeat demo queries land as cache hits (retrieval+cross-encoder skipped) with byte-identical results, while adding no measurable miss-path regression — so a live reviewer clicking the planted seed queries gets instant results. |
| prediction (*est.*) | A: cache-hit p50 < cold-miss p50 for every seed query (the cache removes the cross-encoder re-rank + retrieval; even warm the hit is visibly faster). B: cached response == fresh-uncached (parsed equality) for every seed query. C: cache-ON-first-hit p50 within noise of cache-OFF p50 (the miss path adds sub-ms dict-lookup overhead; no throughput regression). D (pre-seed): after serve start + warmup + primer, all seed queries are cache-resident (counters: resident ≥ seed count, no stores after the primer on re-prime). |
| decision rule | bars PASS if all hold: (a) A — every seed query's hit p50 < cold-miss latency; (b) B — byte-parity holds for every seed query; (c) C — miss-path p95 not pathologically elevated (< 60 s, that is, no regression versus the known warm-search floor); (d) D — the post-primer `/health` `result_cache.resident` ≥ seed-list size AND a re-prime via `scripts/prime_result_cache.py` is idempotent (resident count stable, hits incremented, no new stores). A bar that can't pass is recorded honestly with the failing query. |
| gate environment variables | `SFU_RESULT_CACHE=1` (default ON staging; `=0` one-env rollback), `SFU_CACHE_PRESEED=1` (default ON; `=0` disables the primer), `SFU_HTTP_WARMUP=1` (the primer waits for warmup); staging serve launched via `scripts/serve_http.sh`. |
| result | WI-17a wiring: `source/lib/result_cache.py` + `source/sfu_library_mcp_http.py` (`api_search`/`/health`/`lifespan`); tests `source/tests/test_result_cache.py` (26/26). WI-17b primer: on-start `_run_cache_preseed` + standalone `scripts/prime_result_cache.py` + seed list `data/eval_results/demo_seed_queries.txt` (landing examples from `web/source/search.jsx`). WI-17c efficacy: `scripts/experiments/eval_result_cache_ab.py` → `data/eval_results/result_cache_ab_2026-07-18.json`. |

**MEASURED 2026-07-18** (`result_cache_ab_2026-07-18.json`, warm+primed staging
serve): **all 4 bars PASS** (HOST-NOTE-W7-2 fix applied same session — the
arithmetic + OFF-vs-ON parity leg both added).
- A (cold-miss versus cache-hit, n=20/leg, 6 seed queries): hit p50 **3.7–4.1 ms**
  versus genuine cold-miss p50 **0.2–3.0 s** (warm-search floor; variance = SEISMIC
  working-set warmth — ~0.2 s for already-paged queries, ~2.5–3.0 s for
  cold-region queries) = **50×–776× speedup** per seed query. **F6: every
  `speedup_p50x` reproduces exactly from the stored `cold_miss_p50_ms`/
  `hit_p50_ms` fields** (raw per-sample arrays also stored for full
  re-derivation). The cache removes the cross-encoder re-rank + federated
  retrieval; a repeat demo query is instant. ✅
- B (byte-parity, round-trip): cached response == stored response (round-trip
  identity) for all 6 seed queries. ✅
- **B2 (byte-parity, OFF-vs-ON — the genuine contract bar):** serve restart
  `SFU_RESULT_CACHE=0` (fresh path) versus `=1` (cache hit); parsed-JSON equality
  of result set + meta + notes for all 6 seed queries → **PASS**. A cached
  response is byte-identical to a fresh uncached run of the same query
  (`scripts/experiments/eval_result_cache_parity.py`). (HOST-NOTE-W7-2: the original
  measure_B only proved round-trip identity, not OFF-vs-ON — this B2 leg closes
  that gap; the pre-registered bar is now genuinely met.) ✅
- C (miss-path no-regression): fresh-nonce queries (genuine misses) latencies
  0.26–3.0 s = the known warm-search floor; the cache wrapper's
  get→None→search→put overhead is sub-ms versus the seconds-scale retrieval → no
  measurable miss-path regression. ✅
- D (pre-seed, WI-17b): after serve start + warmup (151.2 s) + primer, all 6
  seed queries cache-resident (`/health result_cache.resident=6`); re-prime via
  the standalone script idempotent (resident stable 6→6, hits +6, stores +0).
  ✅
- Side-finding: `resident` reached the `max_size=256` cap mid-eval (LRU evicted
  2 oldest across the stores) — the size bound works as designed (≥ 200 per
  the contract; the LRU keeps the hot demo set resident under a synthetic
  miss-heavy load larger than any real demo).

## WI-18 searchbar speculation three-arm benchmark (2026-07-18, deployprep wave 8 — PRE-REGISTERED before run)

Owner decision 2026-07-18: keystroke speculation now AUTHORIZED (wave 7
deferred it). Build a minimal searchbar-prediction prefetch and run a
three-arm benchmark: (A) cold/regular latency, (B) wave-7 pre-seed cache
hit, (C) speculation-primed hit. The benchmark is the product; the feature
exists to be measured. Speculation primes the SAME read-through cache +
key recipe as wave 7 (contract term 1 — a speculated result lands under the
exact key a real submit produces). Default OFF (`SFU_SEARCH_SPECULATE`);
the owner flips the default, not the build.

| field | value |
|---|---|
| hypothesis | A debounced searchbar prediction that speculatively primes the read-through result cache (predictor-before-literal, single-slot, guard-suppressed) lets a real Enter-submit land a cache HIT instead of a cold retrieval — so Enter→response approaches the wave-7 ~4 ms hit floor rather than the 0.2–3.0 s warm-retrieval floor — at an acceptable GPU cost (≤ a few speculative backend executions per completed search) and without regressing concurrent real searches. |
| prediction (*est.*) | (a) arm B pre-seed hit p50 ≤ 10 ms (wave-7 reproduced); (b) arm C medium-profile predictor-mode hit-rate ≥ 80% with hit latency ≤ 2× arm-B p50; (c) parity 6/6 (speculation-primed response byte-identical to a fresh cache-OFF run of the same normalized query); (d) arm D (cache-ON miss) within 10% of arm A AND arm E (interference) within 15% of arm A; (e) waste ≤ 3 speculative backend executions per completed search at medium profile. |
| decision rule | bars PASS if ALL hold. A miss is recorded honestly (not renegotiated). Interleaved A/Bs only — trials interleaved across arms within each cell (never all-A-then-all-B). Arm-C trial hygiene: valid only if its query was NOT cache-resident before the typing simulation began (probed before each trial; contaminated trials discarded + logged). F6: every headline recomputed from the raw per-trial samples in the results JSON. |
| gate environment variables | `SFU_SEARCH_SPECULATE=1` enables (default OFF); the benchmark enables it explicitly per arm. `SFU_RESULT_CACHE=1`, `SFU_CACHE_PRESEED=1`, `SFU_HTTP_WARMUP=1` for the warm+primed cells. Speculation guards suppress when: warming, degraded (WI-9/WI-13), cache disabled, overload/shed (WI-11), or typed text < min length (default ≥ 8 chars after normalize). |
| MEASURED (2026-07-28, WI-19b) | **NOT ALL PASS (3 of 6 bars FAIL) — recommend speculation OFF.** Bars recomputed from `data/eval_results/speculation_ab_2026-07-28.json` raw per-trial samples: (a) B preseed p50 **4.98 ms — PASS**; (b) C-medium predictor hit-rate **0.20 — FAIL** (<0.80) and hit latency **2493.41 ms — FAIL** (>2× B); (c) G parity **5/6 — FAIL** (<6, single-query byte divergence on "digital divide broadband access" — REAL and UNEXPLAINED, possible retrieval nondeterminism under differing warm state; not a cache-hit artifact since OFF baselines were on a cache-OFF serve; wave-7 OFF-vs-ON was 6/6); (d) D within-10% of A **FAIL** but directional: D p50 1978.76 ms is 36% *faster* than A 3080.57 ms (warm-miss beats cold-OFF; miss path does not regress beyond warm floor — D-all-genuine-miss check PASS); D-all-genuine-miss **PASS** (W9-3 contamination fixed); (e) E interference p50 1324.69 ms within 15% of A **PASS**; (e') waste 1.1 specification execs/search at medium **PASS**. C-predictor per-profile hit-rate slow 1.00 / medium 0.20 / fast 0.15 (n_valid=20/profile, 0 anomalies); C-literal 0.0 across profiles (structural: prefix-key store ≠ full-query Enter key). Owner recommendation: OFF — predictor value confined to the slow-profile known/in-pool scenario, not demo-representative profiles; waste bounded so OFF is low-regret. Feature ships built+wired (tests 24/24); default stays OFF. Bar (b) is a refuted pre-registered bar, recorded not renegotiated. |
| result | WI-18a build: `source/lib/speculation.py` + `/api/speculate` route in `source/sfu_library_mcp_http.py` + SearchBar debounce helper in `web/source/search.jsx`; tests `source/tests/test_speculation.py`. WI-18b/via WI-19b benchmark: `scripts/experiments/eval_speculation_ab.py` → `data/eval_results/speculation_ab_2026-07-28.json` (raw per-trial samples + event timelines, merged A-G; WI-19a real-time playback protocol, HOST-NOTE-W8-3 fix option a); query pool `data/eval_results/speculation_bench_queries.txt`. (The 2026-07-18 file holds arm A only and is historical after the 2026-07-28 container rebuild + serve restart.) See MEASURED row above for bar PASS/FAIL. |

## Q11-C4 layer-truncated student distillation build (2026-07-28 — PRE-REGISTERED before run)

Parent: `14_ENCODER_UPGRADE_PATH.md` §5.1 precheck 1 — the LAST live
same-space encoder candidate (cheap tier closed 2026-07-10: C1 0.533 / C2
0.357 / C3 skipped / C5 0.006; C4 untrained pre-gate L4 **0.464** with L12
harness control 0.999 — alive, decidable only by an actual distillation
build). Unblocked container-side by the 2026-07-28 doc-14 correction: the
development container has CUDA on the host's RTX 4070 Ti SUPER (16 GB). Rule Zero:
shards/index untouched; every artifact is a new file; worst outcome is a
KILL verdict in a JSON.

| field | value |
|---|---|
| method | **Teacher:** the served 12-layer SPLADE reconstructed as a torch `BertForMaskedLM` from `models/splade_onnx/model.onnx` initializers (HF parameter names are preserved in the export — verified 2026-07-28); MANDATORY parity gate versus the ONNX session on real queries BEFORE any training (sparse-qvec agreement in log1p-ReLU-maxpool space). **Distill set:** pseudo-queries = doc titles sampled from `data/thinclient_index/meta.sqlite` via random-rowid probing (sparse OpenAlex-style rowids, no full scans over 9p) + real query pools in-repo; the n=100 `diverse_queries.json` gate set is EXCLUDED from training (holdout — the gate must never score on training data). **Student:** teacher layers 1–4 + embeddings + MLM head, warm-started from teacher weights (the pre-gate's L4 truncation as init). **Loss v1:** MSE on the sparse query vector in `log(1+ReLU(logits))` space (activation-space distill against the frozen teacher; retrieval score is linear in the qvec, so qvec error bounds every doc-score error). **Pre-registered escalation (one round):** if v1 plateaus under the bar, add margin-MSE on sampled doc pairs (doc 14 §5.1 wording) and/or more titles+epochs — then the verdict is final. |
| gate (inherited doc 14 §4, unchanged) | n=100 real queries; merged 8-shard AND worst-case shards 1–2 overlap@10 versus the served fused encoder **≥ 0.99**; overlap@50 recorded as tail check; `SequentialSeismicBackend`, e5 manifest, same harness lineage as `q11_c4_pregate.py` (whose L12 control measured 0.999 — harness exact). Student runs as ONNX export at gate time (the serving shape). |
| prediction (*est.*, write-before-run) | KALE retained 92.5% at 2 layers with distillation; a 4-layer warm-started activation-space distill of OUR model on in-domain titles lands merged overlap@10 **0.95–0.99** — near the bar, genuinely uncertain either side. Encode speedup **3–6×** versus the served fused path (pre-gate L4 timing was contended; this run records a clean number). Wall-clock per doc 14 correction: teacher qvecs minutes-to-tens-of-minutes, training a few hours/epoch-set, gate ~1 h. |
| decision rule | merged AND shards 1–2 ≥ 0.99 → **PASS** → doc 14 §4.3 ship-gate path (env-gated `SFU_SPLADE_QUERY_ENCODER`-style, D2 promotion pattern; default NOT flipped by this work item). In [0.97, 0.99) → run the single pre-registered escalation round, then final verdict. < 0.97 after escalation (or < 0.97 with no plausible escalation lever) → **KILL, and the encoder book closes** (doc 14 §4: ~20 ms is the price of this doc space until a corpus re-encode). A miss is recorded, not renegotiated. F6: every headline recomputed from the raw per-query samples in the results JSON. |
| planned artifacts | scripts `scripts/seismic_testbed/q11_c4_teacher_from_onnx.py`, `q11_c4_build_distill_set.py`, `q11_c4_train_student.py`, `q11_c4_gate_student.py`; models `models/sfu-splade-teacher-torch/` (reconstructed teacher), `models/sfu-splade-student-l4/` (+ ONNX export); training telemetry `data/eval_results/_q11_c4_train_status.json` + `_q11_c4_train.log` (hourly-report source); results `data/eval_results/q11_c4_teacher_parity_<date>.json`, `q11_c4_distill_gate_<date>.json`; verdict rows here + doc 14 §6 (same-commit rule). |
| MEASURED round 1 (2026-07-28) | **FAIL — below the 0.97 escalation band; escalation round authorized by owner and launched.** Teacher parity PASS (max|Δ| 6.7e-5 log-space, top-64 overlap 1.0, n=100; `q11_c4_teacher_parity_20260728_1905.json`). Distill set 480,097 (480k titles + 97 real; gate/judge held out). Loss-v1 training (3 epochs, batch 256, 43 min on the 4070 Ti Super, ~99% GPU util): qvec dev MSE floored at 1.5e-4 but development top-64 term overlap plateaued **0.670** (from 0.32 untrained). Stage-0 gate on `best`: **merged overlap@10 0.690, shard1 0.643, shard2 0.667** (overlap@50 0.662–0.674; per-query min 0.1) versus bar 0.99 — `q11_c4_distill_gate_20260728_2007.json`. Encode p50 16.84 versus fused-ref 29.26 ms (**1.74×**, conservative: student ONNX unfused — D2 fusion not yet applied). Diagnostic: dev top-64 proxy (0.670) tracks the backend gate (0.64–0.69) almost 1:1 — qvec-MSE recovers bulk energy, not ranking order. Escalation (the single pre-registered round, `q11_c4_train_student_v2.py`): + margin-MSE over REAL doc vectors sampled from shards 1–2 f16 forward (40k-doc pool, λ auto-balanced then frozen), init from round-1 `best`, 6 epochs. **Verdict after escalation is FINAL.** |
| MEASURED round 2 / FINAL (2026-07-28) | **KILL — the encoder book closes (doc 14 §4).** Escalation trained 72 min (14,940 steps, 6 epochs, ~100% GPU): margin loss 0.45 → 0.13, dev top-64 proxy 0.670 → **0.765**, plateaued flat for the last ~2 epochs (objective ceiling, not undertraining). FINAL gate on `v2-best`: **merged overlap@10 0.760, shard1 0.726, shard2 0.752** (overlap@50 0.741–0.750; per-query min 0.3) versus bar 0.99 — `q11_c4_distill_gate_20260728_2127.json`; encode p50 17.65 versus fused 29.90 ms (1.69×, student unfused). Margin-MSE moved the number (+0.083 worst-arm over round 1) but a 4-layer student cannot hold the bar. Method finding worth keeping: the offline development top-64 term-overlap proxy predicted the backend gate ~1:1 in BOTH rounds (0.670→0.643–0.690; 0.765→0.726–0.760) — future encoder candidates can be triaged without touching shards. Same-space encoder candidates are now ALL measured dead (C1 0.533, C2 0.357, C3 skipped-static, C4 distilled 0.726–0.760, C5 0.006): **~20 ms encode is the price of this doc space until a corpus re-encode** (doc 14 §5 branch). Rule Zero: shards untouched throughout. |

## Recording rules (same-commit doc rule applies)

- Every executed cell: result JSON under `data/eval_results/g8c_*.json`
  (host commits JSONs only; the container session writes the doc rows).
- A Tier-1/2 row's outcome goes HERE (replace its prediction cell with
  measured numbers + result path + date) AND in its parent doc.
- Rows never executed stay PRE-REGISTERED — do not delete them; they are the
  queue for the next session.
