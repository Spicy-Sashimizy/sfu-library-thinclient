# 06 — Spike plan: in-place bit updater + custom encoder/decoder (pre-registration)

> **CLOSED MEASURED 2026-09-30** — the pre-registered GO rule of `06_INPLACE_SPIKE_PLAN.md` read NO-GO: bar S0-1 measured a long-list dead-slot coverage of **0.019** (95 % CI 0.018–0.020) against 0.80. In one quarter 27 % of shard 0's docs are updated and 15 % more are new while deletions free 6 %, and a list cannot grow, so dead-slot reuse cannot absorb the churn (`inplace_s0_20260930.json`). Nothing in-place replaces it: updates stay with delta generations (`docs/delta_ingest/`). The v3 encoder/decoder is exact (B1 460/460, +1.3 % per query) and the +tail variant was built, but they remove the wrong obstacle. Full record: `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` results table and §"NO-GO 2026-09-30". Not current; do not resume.

**Status:** CLOSED MEASURED 2026-09-30

**PRE-REGISTERED 2026-09-29. GO rule read 2026-09-30 04:17Z: S0-1 FAIL
(long-list coverage 0.019 vs 0.80) → NO-GO. Per §"GO rule to Stage 1" the
track is recorded **CLOSED MEASURED 2026-09-30**: the last rows (B7 A2, S0-2/S0-3, A2b read rerun) landed 2026-09-30 23:43Z; see §"NO-GO 2026-09-30" below the results table.** Every bar below was written and
pushed before any number for it existed; a failed bar is recorded as a
FAIL, never re-cut. Stage 1 ran AHEAD of the GO rule at the owner's request
(2026-09-29); its rows are recorded for the closed-track record.

Source brief: `05_INPLACE_BIT_UPDATE_BRIEF_2026-09-29.md` (§2 design, §6
arms and bars, §7 risks), read together with its "Reconciliation note
2026-09-29", which overrides that brief where they disagree. Format and
discipline follow `03_SPIKE_PLAN.md`. The brief marked its thresholds
"proposed; local session finalises before running": they are finalised
here, 2026-09-29. No threshold was loosened. Every place a definition was
tightened or clarified is listed in §"Changes from the brief" with the
reason.

## Fixed inputs (all bars unless a bar says otherwise)

- **Shard.** Shard 0 only: f16 twin
  `data/seismic_150m/index/plan01/global_shard0of8.mmap` (read via
  `scripts/seismic_testbed/stage0_candidates.py::open_forward`) and the
  matching served dv-v2 shard from the served manifest
  (`data/thinclient_index`, E8 dv-v2 manifest). Shard 0 is chosen because
  M9 rebuilt it and measured the rebuild-vs-served ceiling there. Both are
  READ-ONLY.
- **Quarter Q1 of churn.** OpenAlex snapshot works partitions with
  `updated_date` in [2026-06-17, 2026-09-15] inclusive (the 13 weeks after
  the 2026-06-16 base build), read with `spike/delta_ingest`'s
  `OpenAlexSnapshotAdapter`, plus the deletions (`iter_deletions`,
  `deleted_ids`/merged ids) for the same window. Slice filter as M7
  (year ≥ 2010, the base boundary; issue O6 in `02_DESIGN.md` §3.1 is
  corrected in the filter, not inherited). Per the reconciliation note item
  3 (M7 FAIL), **every touched in-base doc counts as re-encoded** (delete of
  its old postings + insert of its new ones); no churn filter is applied.
- **Routing to shard 0.** A base doc belongs to shard 0 iff it is in the
  served shard 0. A new work is routed to shard 0 iff
  `scripts/seismic_testbed/shard_spool.py::shard_id(oaid, "sfu-seismic-plan01", 8) == 0`
  (`blake2b(seed + oaid, digest_size=8)`, big-endian int, `% 8` — the rule
  that built plan01).
- **Doc vectors.** New and updated docs are encoded with the
  `spike/delta_ingest` encoder under profile `desktop_gpu` (same model as
  the base); vectors are cached in a ledger under the work dir and reused by
  every arm, so encoding cost is excluded from every arm's cost.
- **Quarters 2..6** (only where a bar asks for >1 quarter): synthetic.
  Deletions: base docs of shard 0 sampled uniformly without replacement
  (seed `inplace-q<k>`) at Q1's measured deletion + update rate. Inserts:
  real new works from later partitions if downloaded, else Q1's new-work
  vectors re-drawn with fresh ids; the results file records which, and the
  latter is flagged `synthetic_reuse: true`.
- **Query sets** (encoding = E8 conventions: `encode_splade(q,
  "models/splade_onnx_fp16")`, top-64 terms by weight, all passed):
  - **QA** — 240 records (120 topics × keyword + natural form),
    `data/eval_results/dense_ablation_queries.json`, judged by
    `data/eval_results/dense_ablation_qrels_20260817.json` (grade 0–3,
    relevant = grade ≥ 2, gain = 2^grade − 1). This is the "240-query set
    with judged qrels" the brief names.
  - **QT** — the 120 topics, `data/sfu_eval_queries.json`, field `query`
    (the n120 set; M9's first set; every serve-path latency eval).
  - **QD** — 100 diverse queries, `data/eval_results/diverse_queries.json`
    via `e6_forward_codec_proto.load_queries`, first 100 distinct
    paraphrases (M9's second set).
- **overlap@10** = |top10_X ∩ top10_ref| / 10 per query on doc-id strings,
  meaned over the set; reported per set, gated on EACH set named by the bar.
- **NDCG@10** on QA only: per record, unjudged docs = grade 0, `judged@10`
  reported beside it; aggregated per topic (mean of its two forms); CI =
  95 % paired bootstrap over the 120 topics, 10,000 resamples, seed 0.
- **Latency discipline** (reconciliation note item 5, issue O12): every
  latency run holds `flock /tmp/sfu_latency_measure.lock` for its whole
  duration, is quiet-host gated like
  `data/eval_results/warmcache_metric3_isolated_20260925.json`, runs 1
  discarded warm-up pass + 2 measured passes, and asserts before the first
  timed query that the SPLADE encoder, embedding model and cross-encoder all
  loaded (a degraded process aborts the run; it is not recorded as a
  result). A run that overlapped another agent's heavy work records its
  latency fields as INVALID.
- **Scripts:** `scripts/archive/inplace_update/eval_inplace_<bar>.py`, one per bar
  (`eval_inplace_s0_1.py` … `eval_inplace_b7.py`); each copies its bar from
  this file verbatim into its header docstring before its first run.
- **Results:** Stage 0 → `data/eval_results/inplace_s0_<YYYYMMDD>.json`
  (one top-level key per bar: `s0_1`, `s0_2`, `s0_3`); Stage 1 →
  `data/eval_results/inplace_b_<YYYYMMDD>.json` (keys `b1` … `b7`, plus
  `arms` describing A0–A3). Every doc claim cites the file and the commit.

## Reference-arm decision (owner/coordinator, 2026-09-29)

The twin-shard rebuild FAILED its own parity bar: overlap@10 0.9858 (QT) /
0.9870 (QD) vs 0.99 (M9, `data/eval_results/delta_ingest_twin_rebuild_20260929.json`).
Therefore every bar whose reference is a rebuild — **S0-2, B6, and arm A3**
— is ALSO scored against the served base **A0**, and the rebuild path's
0.9858 / 0.9870 is recorded in the results file as the **known ceiling of
that path** (how close a real rebuild of an unchanged doc set gets to the
served shard). How each bar reports under this dual reference is stated in
the bar itself (S0-2, B6).

## Stage 0 — Python only, shard 0, no Rust, zero serving impact

### S0-1 — dead-slot supply vs insert demand

- **Unit:** each posting list L (term t) of the served shard-0 dv-v2 index;
  `slots(L)` = its posting count at build.
- **Supply** `dead(L)` = postings in L whose doc is deleted, merged away, or
  updated in Q1 (an updated doc's old posting is dead; its new vector is
  demand). Also recorded: supply from deletions/merges only.
- **Demand** `new(L)` = number of Q1 new-or-updated docs routed to shard 0
  whose encoded vector has a non-zero weight on t (every new posting, not
  only those that would pass the list's current minimum — the brief's
  literal, stricter reading). Also recorded, not gated: admissible demand
  (weight > the list's current minimum weight, or `slots(L)` below the
  per-list cap).
- **Coverage without eviction** of a set S of lists =
  Σ_{L∈S} min(dead(L), new(L)) / Σ_{L∈S} new(L) (posting-weighted, pooled).
- **Long lists** = lists with `slots(L)` ≥ ⌈cap/2⌉, where cap =
  `n_postings × max_fraction` read from shard 0's build config (3,500 ×
  1.5 = 5,250 at the G2 params per `seismic_150m_testbed/06_FINDINGS.md`;
  the script records the value it read, and the count and total postings
  of the long-list set).
- **Deciles:** lists ranked by `slots(L)`, split into 10 equal-count
  deciles; pooled coverage per decile. **Hybrid cut-off** = scanning from
  the longest decile down, the first decile whose coverage < 0.50;
  recorded with its `slots` range.
- **Thresholds.** PASS: long-list coverage ≥ 0.80 on the full Q1 window.
  If the full window could not be downloaded, a part-file sample (fraction
  f ≥ 0.10, recorded, deletions for the full window) may be used: PASS then
  needs the 95 % bootstrap lower bound (resampling part files, 10,000,
  seed 0) ≥ 0.80; PARTIAL if the point estimate ≥ 0.80 but the lower bound
  < 0.80 (PARTIAL does NOT satisfy the GO rule). FAIL: point estimate
  < 0.80.
- Script `scripts/archive/inplace_update/eval_inplace_s0_1.py` → `inplace_s0_<date>.json` key `s0_1`.

### S0-2 — quality under synthetic churn (Mechanism B, §2.3 of the brief)

- **Simulation:** apply Q1, then Q1–Q3, then Q1–Q6 to shard 0's posting
  lists per brief §2.3 — deletes free slots; each insert posting takes a
  dead slot, else evicts the list's minimum-weight posting if its weight
  exceeds it, else is dropped; inserts in term-sorted batches per quarter;
  list lengths never grow.
- **Scoring procedure (identical in every arm):** list-restricted exact
  retrieval — candidates = union of docs in the (simulated) lists of the
  query's 64 terms; score = exact dot product with the doc's forward vector
  (twin f16 values for base docs, the encoded vector for new docs); top-10.
  This isolates list membership (Mechanism B); block/summary approximation
  is S0-3's job.
- **Rebuild reference R_sim(k):** the same doc set after k quarters, lists
  re-selected by the build's pruning rule (global top `n_postings × dim`
  postings, then per-list cap), same scoring procedure. Deterministic, so
  it carries no build drift.
- **Base reference A0:** the same scoring procedure on the unchurned served
  lists, with deleted/merged/updated-old ids removed from its ranking and
  the top-10 backfilled from deeper ranks.
- **Gated metric:** overlap@10(in-place(k), R_sim(k)) on EACH of QA, QT,
  QD, for k ∈ {1, 3, 6}. NDCG@10 on QA for in-place, R_sim and A0,
  recorded, not gated.
- **Dual-reference reporting:** the verdict comes from R_sim only.
  Recorded beside it for every k: overlap@10(in-place, A0),
  overlap@10(R_sim, A0) (the churn-only gap) and their difference, and the
  real-rebuild ceiling 0.9858 / 0.9870 as context. The ceiling is not
  applied to R_sim (R_sim is a deterministic re-selection, not a real
  SEISMIC build).
- **Thresholds.** "Passes at k" = overlap@10 ≥ 0.99 on each of QA, QT, QD
  at k quarters. PASS: passes at k = 3. PARTIAL: passes at k = 1, fails at
  k = 3. FAIL: fails at k = 1. Record the first k in {1, 3, 6} where it
  breaks.
- Script `scripts/archive/inplace_update/eval_inplace_s0_2.py` → key `s0_2`.

### S0-3 — block visits vs bound inflation (Mechanism C, §2.4 of the brief)

- **Placement:** every insert posting lands in the block that holds the
  slot S0-2 assigned it (dead slot or evicted slot).
- **Inflation rule (per-block inflation byte):** for block b, on each
  insert, recompute b's summary as the build would (α = `summary_energy`
  0.4 over the component-wise max of the block incl. the new doc);
  m_b := max(m_b, max over components c present in the OLD summary of
  new_c / old_c); m_b is quantised UP to 1 + code/32, code ∈ 0..255. A
  block needing code > 255 is "saturated" and counted as visited for every
  query. Components absent from the old summary are not covered by a
  scalar multiplier; their count and summed weight per block are recorded
  as `blind_mass` (not gated).
- **Visit count (static proxy, not the engine's dynamic count):** for
  query q, θ_q = the k′ = 200-th score of q's A0 run (S0-2 procedure);
  block b of a list of one of q's terms is visited iff
  m_b · dot(q, summary_b) ≥ heap_factor · θ_q with heap_factor = 0.8 (the
  E8 recall-max params). V(k) = total visits over the set after k quarters;
  V(0) = the same with m_b = 1 on the unchurned shard.
- **Output:** T* = the largest k in {1, 2, 3, 4, 5, 6} with
  V(k)/V(0) − 1 ≤ 0.10 on each of QA, QT, QD — the proposed compaction
  threshold, also expressed as dead-slot fraction and mean m_b at T*.
- **Thresholds.** PASS: T* ≥ 1 (visits grow ≤ +10 % after one quarter, so
  the compactor runs no more than quarterly). FAIL: > +10 % at k = 1 on any
  set.
- Script `scripts/archive/inplace_update/eval_inplace_s0_3.py` → key `s0_3`.

### M4 and M5 (from `03_SPIKE_PLAN.md`, run as part of this spike)

M4 (read amplification) and M5 (reload cost) are run exactly as defined in
`03_SPIKE_PLAN.md`, with their bars and results files
(`data/eval_results/delta_ingest_M4_<date>.json`,
`delta_ingest_M5_<date>.json`) unchanged; they are not redefined here. M4 is
arm A1 at corpus scale and the GO input. **GO input derived from M4:** the
generation tax = the least-squares slope of `search_rrf` p50 (parallel
backend, the served mode) over N ∈ {0, 1, 4, 8} live generations, in ms per
generation; the sequential-backend slope is recorded beside it.

### GO rule to Stage 1 (brief §6, in substance)

GO to Stage 1 only if **S0-1 meets its threshold for long lists** (PASS as
defined above) **AND S0-2 passes at ≥ 1 quarter** (PASS or PARTIAL) **AND
M4 shows a generation tax ≥ 3 ms p50 per generation.** Otherwise the track
is recorded **CLOSED MEASURED** with the numbers (docs moved per the
closed-tracks policy) and stops. S0-3 does not gate GO; it sets the
compactor threshold.

## Stage 1 — Rust encoder/decoder on a COPY of shard 0, head-to-head (only after GO)

Doc set = Q1 churn routed to shard 0; queries and host discipline as in
§"Fixed inputs". Every arm serves the full 8-shard stack with only shard 0
varied (shards 1–7 = served, unchanged).

- **A0 base** — served dv-v2 shard 0, no updates (reference).
- **A1 delta** — base + the Q1 shard-0 docs as N ∈ {1, 4, 8} delta
  generations, split evenly in ingest order (`updated_date`, then id),
  built by `spike/delta_ingest` into a delta root under the work dir; this
  is current ingest. (Corpus-scale M4 remains the GO input; B3's A1 arm is
  the same mechanism on this doc set, cross-checked against M4, not a
  substitute for it.)
- **A2 in-place** — a COPY of shard 0 re-encoded to format v3, the same
  docs applied in term-sorted batches by the bit updater, one epoch flip.
- **A3 rebuild** — per-shard rebuild of shard 0 from its twin incl. the Q1
  docs (M9 chain, G2 params); quality upper bound and cost baseline, with
  its known 0.9858 / 0.9870 ceiling.

| Bar | Metric (exact) | Threshold | PASS / PARTIAL / FAIL |
|---|---|---|---|
| **B1 parity** | v3 decoder on the v3 copy with ZERO patches vs A0: top-k′ (k′ = 200) doc ids AND f32 score bit patterns, E8 recall-max params, every query of QA ∪ QT ∪ QD (460) | identical on 460/460 | PASS 460/460; anything else FAIL |
| **B2 apply cost** | wall time and device bytes written (`/proc/<pid>/io` `write_bytes`, incl. fsync) to apply Q1: A2 (batches + epoch flip) vs A1 N=1 (generation build from cached vectors, SEISMIC chain + tantivy/meta) vs A3 (dump + build + c1a + dotvbyte); 3 reps, median | A2 ≤ A1(N=1) on BOTH wall time and bytes written | PASS both; PARTIAL one of the two; FAIL neither. A3 recorded |
| **B3 query latency** | `search_rrf` p50 and p95 over QT, top_k = 50, serving flags, per §"Latency discipline", arms A0 / A1 (N = 1, 4, 8) / A2 / A3, parallel AND sequential backend | A2 p50 ≤ 1.05 × A0 p50 AND A2 p95 ≤ 1.05 × A0 p95, on each backend | PASS all four; PARTIAL p50 both backends but a p95 misses; FAIL otherwise. A1 recorded (cross-check vs M4) |
| **B4 storage** | bytes (st_size and allocated st_blocks × 512) of every file the arm serves for shard 0 incl. side files, after Q1 and after Q1–Q4; A1 reported SEISMIC-only and full generation | report | RECORDED (no bar) |
| **B5 publish** | A2: wall time of the epoch flip until a new query sees epoch e+1; A1: `reload_index` drop + re-mmap until the first query returns (= M5's quantity); 5 reps each. Residency of shard-0 files (`mincore`) before vs after publish | timing: report. Residency: A2 keeps ≥ 99 % of resident pages and does not re-mmap | residency PASS/FAIL; timing RECORDED |
| **B6 quality** | overlap@10(A2, A3) on each of QA, QT, QD; NDCG@10 on QA for A1 (N=1), A2, A3; paired bootstrap CI of mean(NDCG_A2 − NDCG_A1) | overlap@10(A2, A3) ≥ 0.99 on each set AND the 95 % CI of ΔNDCG contains 0 or lies above 0 | see "B6 dual reference" |
| **B7 crash safety** | 100 trials on a fresh copy at epoch e: SIGKILL the updater at a uniform-random time in [0, T_apply]; reopen with the v3 decoder; (a) header epoch ∈ {e, e+1}, e+1 only if the flip completed; (b) QT top-k′ ids and scores bit-identical to a clean reference at that epoch; (c) a concurrent reader process querying QT in a loop during the batch returns results identical to the epoch-e reference until the flip, with zero decode errors or crashes | 100/100 trials satisfy (a), (b), (c) | PASS 100/100; otherwise FAIL with the failing trials listed. Process kill only; power loss is NOT tested (page cache survives SIGKILL) |

**B6 dual reference.** Always recorded: overlap@10 of A2, A1 (N=1) and A3
each vs A0, overlap@10(A2, A1), and the rebuild ceiling 0.9858 / 0.9870.
Verdict: **PASS** = the B6 threshold above holds. **PARTIAL** = the
overlap-vs-A3 half fails but overlap@10(A2, A0) ≥ overlap@10(A3, A0) on
each set AND the NDCG half holds (the miss is attributable to rebuild drift
that A3 carries, not to the in-place path). **FAIL** = anything else.

Scripts `scripts/archive/inplace_update/eval_inplace_b1.py` … `eval_inplace_b7.py` →
`inplace_b_<date>.json` keys `b1` … `b7`. The GO/NO-GO of the encoder/
decoder itself is read from B1 (must PASS before any other B bar runs), B2,
B3 and B6.

## Hard rules

- Spike code lives under `spike/archive/inplace_update/` (EXEMPT from the
  no-comments policy as `spike/`); Rust changes to the reader follow the
  vendored patch-chain convention (`seismic_upstream_*.patch`,
  `spike/vectorium_fork`).
- `data/seismic_150m/` is READ-ONLY, always. In-place writes go ONLY to a
  COPY of one shard (shard 0) in a work dir on local disk OUTSIDE the repo:
  `/home/vscode/work/inplace_update/` — never under `/workspaces` (9p:
  55× stage penalty, `THIN_CLIENT_SWAP.md` §Filter; ENOMEM issue O12).
  Delta roots for A1 and the vector ledger also live there.
- Never build a shippable `.so` with `-C target-cpu=native`; use
  `-C target-cpu=x86-64-v3` (`spike/CLAUDE.md`).
- Hybrid rule (brief §2.7): in-place for LONG lists (as defined in S0-1,
  cut-off from S0-1's deciles), the delta L0 buffer for short lists;
  in-place applies updates in term-sorted batches only.
- At most one SEISMIC shard build at a time on this host (A3, A1 builds).
- Promotion to a served gate is OUT of scope. Nothing in this spike changes
  `src/` serving defaults.
- Bars are frozen at this commit; a bar may be clarified only in a dated
  addendum below the results table written BEFORE the affected run, and may
  never be loosened.

## Changes from the brief (finalised 2026-09-29, before any run)

1. **S0-1 "lists ≥ 10 k slots" → lists with slots ≥ ⌈cap/2⌉.** At the G2
   build params each list is capped at `n_postings × max_fraction` = 3,500
   × 1.5 = 5,250 postings (`seismic_150m_testbed/06_FINDINGS.md`,
   `spike/delta_ingest/generation.py` `SEISMIC_PARAMS`), so a ≥ 10 k set is
   empty and the bar would pass vacuously. The script reads the real cap
   from the shard. Coverage is defined pooled, demand counts every new
   posting (stricter than admissible-only), and a sampled window can only
   PASS on its bootstrap lower bound.
2. **"240-query replay set / judged qrels" pinned** to
   `dense_ablation_queries.json` + `dense_ablation_qrels_20260817.json`
   (QA). The delta plan's own set is QT (120 topics), and M9's ceiling was
   measured on QT and QD, so overlap bars gate on all three sets
   (stricter than one set).
3. **S0-2 given a scoring procedure and a deterministic rebuild
   reference** (list-restricted exact retrieval; R_sim), and graded PASS
   (k = 3) / PARTIAL (k = 1 only) / FAIL so that the brief's bar (≥ 0.99
   at 3 quarters) and its GO condition ("passes at ≥ 1 quarter") are both
   well-defined.
4. **S0-3 was self-referential** ("≤ +10 % at the threshold; the threshold
   is an output"). Made decidable: the output is T*, and PASS requires
   T* ≥ 1 quarter. The inflation rule and the static visit proxy are
   specified; the proxy is not the engine's dynamic count.
5. **GO input from M4 defined** as the p50 slope over N ∈ {0, 1, 4, 8},
   parallel backend. M4's own bar is unchanged.
6. **B1 "T1-style 20/20" → 460/460** queries, ids and score bits (stricter).
7. **B2 "GO if A2 ≤ A1"** → on both wall time and bytes written vs A1 N=1.
8. **B3 "within 5 % of A0"** → p50 AND p95, both backends. "A1 numbers ARE
   the M4 result" is replaced by: M4 (corpus scale) is the GO input; B3's A1
   arm is a cross-check on the Stage-1 doc set.
9. **B5** "prefault/mlock state retained" made measurable (≥ 99 % resident
   pages, no re-mmap).
10. **B6 "NDCG within CI of A1"** → paired bootstrap CI of the difference
    contains 0 or lies above 0; PARTIAL added only for the dual-reference
    case, PASS unchanged.
11. **B7** "no torn reads" made measurable (concurrent reader + bit-identity
    after reopen); scope stated (SIGKILL, not power loss).

## Known risks (brief §7, unchanged in substance)

- Rust changes in the vendored reader are comparable to the closed slack
  track's "weeks of Rust" estimate minus the format-wide gap plumbing
  (*est.*); keep the `seismic_upstream_*.patch` chain.
- Lists with no dead slot and no evictable posting silently drop the new
  doc from that term; S0-1 quantifies how often, the hybrid rule bounds it.
- Updated docs written into holes lose the E5 reorder's page locality (E5
  measured 0.376–0.400× pages/query from ordering) — bounded to the changed
  fraction; B3 catches it.
- The per-list minimum side array for eviction costs ≈ #lists × 4 B
  (*est.*); confirm from `manifest.json` list count.
- Windows bundle: no userfaultfd (not used); aligned 8-B writes and mmap
  coherence hold on both platforms (*est.*, untested on Windows).
- The 9p host path: in-place writes must target local-disk copies.
- Added 2026-09-29 from this plan's definitions: SEISMIC summaries are
  α-energy truncated, so a scalar inflation byte cannot bound components
  absent from the old summary (`blind_mass` in S0-3); the "recall cannot
  drop" claim of brief §2.4 is therefore DESIGN ONLY until measured.

## Addendum 2026-09-29 — after the source re-read (before any Stage-1 number)

Written by the coordinator after `04_IMMUTABILITY_RESEARCH.md` §"Addendum
2026-09-29" (commit `3f99a748`). No threshold above is loosened and no
Stage-0 verdict rule changes. State of measurements when this was written:
every row of the results table NOT RUN in the docs; Stage-0 and M4 harness
code committed (`b7456435`, `91d63ca2`, `0f6f6c30`), no results file on origin.

**Stage 1 bars tightened (pre-registered here, Stage 1 has not started):**
- **B7** additionally requires a simulated POWER-LOSS arm: dirty mapped pages
  survive `kill -9`, so SIGKILL alone cannot expose a torn or lost in-place
  write. The arm discards un-synced pages (a block-layer or file-copy
  simulation that drops every write after the last completed sync) at 100
  random points of a batch, then reopens. PASS needs 100/100 on BOTH arms.
  The write order under test is: data writes, sync, header write, sync.
- **B7 / Mechanism D premise.** "A crash mid-batch leaves epoch e serving"
  holds only for writes into slots that were already dead at the published
  epoch. An eviction or a same-batch slot reuse destroys content epoch e
  still serves. The Stage-1 design must therefore either restrict in-place
  writes to dead-at-epoch slots or keep an undo record; the bar tests
  whichever is built and the results file names it.
- **B1 and B3** additionally REPORT the per-query cost of the added mask
  checks and multiply (decoder v3 vs v2 on an unpatched shard). Reported
  only; B3's 1.05 x threshold already bounds it.
- **Scope of the atomicity claim:** local files only. 9p, SMB and mixed
  mmap + `ReadFile`/`WriteFile` access are out of scope and stated as
  unsupported, not as passing.

**Stage 0 supplementary metrics (NOT pre-registered bars; recorded under
`supplementary` in the results file, never part of a verdict):**
- S0-3: overlap@10 of the loosened-bound simulation vs exhaustive scoring,
  and the count of inserted postings whose component is absent from their
  block's summary. Reason: SEISMIC summaries are approximations, not upper
  bounds, so "recall cannot drop" is DESIGN ONLY.
- S0-2: loss from deletions (no refill) reported separately from loss from
  inserts; share of inserted postings placed outside the block a fresh
  clustering would choose, if the simulation can tell.

## Addendum 2026-09-29 (second) — supplementary arm A2b and supplementary demand P1

Written by the coordinator on the owner's relay of the cloud-session addendum
at the end of `05_INPLACE_BIT_UPDATE_BRIEF_2026-09-29.md` (branch commit
`9fbd7972`). State of measurements when this was written: no results file
`inplace_s0_*`, `inplace_b_*`, `delta_ingest_M4_*` or `delta_ingest_M5_*`
exists; format v3 is a DESIGN spec (`spike/archive/inplace_update/FORMAT_V3.md`,
`41d59f93`), no encoder/decoder code committed.

**Everything in this addendum is SUPPLEMENTARY.** No frozen bar, threshold,
arm or verdict rule above changes, and the GO rule reads only the frozen
S0-1, S0-2 and M4. A supplementary number is recorded beside the frozen one
and is never substituted for it. Changing what GO reads needs the owner to
re-pre-register before the affected run.

### Arm A2b — copy-on-write re-encode (DESIGN ONLY)

- **Definition.** A COPY of shard 0 in format v3. No byte reachable from the
  published state is overwritten. The write unit is decoded, the quarter's
  inserts/evictions/deletes applied, its summary REBUILT as the build does
  (not inflated), the new unit written to free space and synced, then the
  one offset that names it is replaced by a single aligned 8-byte store and
  synced. Old bytes stay allocated until compaction. Slot-level in-place
  writes remain only for forward-offset repoints.
- **Write unit = an OUTPUT of measurement W1, fixed before any A2b code.**
  W1 (read-only, shard 0, results
  `data/eval_results/inplace_writeunit_<YYYYMMDD>.json`): distribution
  (min, p50, p90, p99, max, total) of bytes per block and per list for
  packed postings, block offsets and the summary section; and whether one
  block's summary entries can be re-encoded without re-encoding the rest of
  its list's summary section. Rule: BLOCK if separable, else LIST. W1 is a
  structural measurement, not an efficacy result.
- **Scoring.** A2b is scored on the same rows B1–B7 with the same
  thresholds, reported in its own column beside A2. B7's SIGKILL and
  power-loss arms apply unchanged. A2b has no inflation byte, so S0-3 does
  not describe it; its quality question is B6.
- **Extra recorded quantities (A2b only):** bytes written per quarter and
  file growth before compaction (B4), share of lists/blocks rewritten, and
  overlap@10 of A2b vs A0 and vs A3 under the B6 dual reference.
- **A2b does not enter the GO rule.** Stage 1 starts, or not, on the frozen
  rule; if it starts, A2 and A2b are both built and measured.
- **Inference not to be quoted as fact:** that A2b avoids the drift behind
  M9's parity FAIL is an inference from the brief addendum; B6 measures it.
- Precedents cited in the brief addendum (CUBIT, Parquet/Puffin checksums)
  are `[snippet]` until re-read into `04_IMMUTABILITY_RESEARCH.md`.

### P1 — vector-diff change filter (DESIGN ONLY; supplementary demand)

- **Definitions.** For a touched in-base doc, compare the newly encoded
  sparse vector with the stored vector of the f16 twin forward record.
  `unchanged_exact`: identical component set and every value equal after the
  f16 cast. `unchanged_tol`: identical component set and max |Δw| ≤ 1 f16
  ulp.
- **Required control, reported before any P1 number is interpreted.** The
  stored vectors come from the build's encoder runtime, today's from a
  possibly different one (open issue O8). On docs whose title+abstract are
  byte-identical to the base text, the share NOT `unchanged_exact` and NOT
  `unchanged_tol` is measured. If it exceeds 1 %, the vector diff is
  recorded UNRELIABLE AS DEFINED; the smallest tolerance that brings the
  control under 1 % may be reported, labelled post hoc.
- **Recorded, under `supplementary.P1` of the Stage-0 results file:**
  `new_vd(L)` / `dead_vd(L)` (only vector-changed docs count) beside the
  frozen S0-1 pair; M7 touched:must-encode re-scored by vector diff on
  M7's two part files, as a third number beside the two recorded FAILs.
  M7's verdict does not change.
- The brief addendum's "demand inflated ≈4×" is an *est.* from M7's text
  proxy on one hot section (25.3 % of 9,965); P1 measures it.

## Addendum 2026-09-29 (third) — what the safety rule does to arm A2; variant A2-2p

Written by the coordinator before any Stage-1 run (no `inplace_b_*` results
file exists; the updater is at design stage, `UPDATER_DESIGN.md` not yet
committed). Raised by the bit-updater agent and by the review
`spike/archive/inplace_update/FORMAT_V3_REVIEW_2026-09-29.md`.

**Finding (by design reasoning, not measured).** Arm A2 is built with the
rule "write only into slots and holes already dead at the published epoch;
no undo record" (the only rule under which B7 (c) can hold: an eviction or a
same-batch reuse is seen mid-batch by epoch-e readers). A fresh v3 copy has
no dead slot and no hole. Under the frozen definition of A2 ("one epoch
flip") the first batch can therefore mark deletes but absorb ZERO inserts.

**The frozen arm is not redefined.** A2 stays "one epoch flip" and is run as
defined; the number of inserts it absorbs is recorded, and its B2–B7
verdicts are whatever that run gives. If it absorbs none, that is the result
of the pre-registered arm.

**Variant A2-2p (two-phase), SUPPLEMENTARY, own column beside A2 and A2b:**
- Flip 1 publishes e+1 (the FREE epoch): delete marks for true deletions and
  for evictions, tag-only writes.
- Flip 2 publishes e+2 (the FILL epoch): inserts into slots and holes dead
  at e+1, gated on the reader table (content freed at epoch f is reused only
  when f ≤ the oldest registered reader epoch).
- **Where the old version of an UPDATED doc is marked is recorded as a
  sub-variant, both run:** `old-at-free` (marked in flip 1: the updated doc
  is absent from the SEISMIC leg between the two flips) and `old-at-fill`
  (marked in flip 2 together with the insert of its new version: no gap, but
  those slots only become supply for the NEXT batch). For each, the results
  record the gap duration and overlap@10 vs A3 measured AT e+1 as well as at
  e+2.
- Bars read on A2-2p with the same thresholds, with these per-flip
  readings, stated here before any run: B7 (a) header epoch ∈ {e, e+1, e+2},
  each value only if its flip completed; B7 (b), (c) against the clean
  reference of whichever epoch is published; B2 wall time and bytes cover
  both flips including the wait on the reader table; B5 reports each flip
  and the total time from batch start until the inserts are visible.
- The same two-phase structure and per-flip readings apply to A2b where it
  reuses heap space; A2b's first batch needs no freed space (it writes to
  the heap tail), so A2b is ALSO run single-flip as its primary.

**Reader-table protocol requirement (both arms).** A reader registers by
writing its slot and THEN re-reading the header; if the published epoch
changed in between it re-registers. Without the re-read, a reader that read
E just before a flip and registered just after the updater inspected the
table is invisible to the updater. B7 (c) includes a slow reader and a
reader that starts during the flip.

**Decoder scope extension (A2b read path).** B3, B5 and B6 for A2b need the
v3 decoder to read a heap unit: the unit's own scalars are authoritative
(a rewritten list may have a different block count), and the inflation
banks are not applied to a list served from a unit. Assigned to the
encoder/decoder agent AFTER B1 has run; B1 is unchanged.

**B1 mask cost excludes reader registration**; its cost appears first in B3
and is reported there as its own line.

Nothing in this addendum changes a threshold or the GO rule.

## Addendum 2026-09-29 (fourth) — after the updater design review (before any Stage-1 run)

Written by the coordinator; no `inplace_b_*` results file exists and no
updater code is committed. Sources: `spike/archive/inplace_update/UPDATER_DESIGN.md`
(`586e04ab`) and its review
`spike/archive/inplace_update/UPDATER_DESIGN_REVIEW_2026-09-29.md`.

- **Unplaced documents are reported for every arm.** A document whose
  record fits no hole is not served by A2 / A2b / A2-2p. Every results
  file reports, per arm: documents offered, placed, unplaced, and postings
  inserted / dropped / evicted. B6 is scored on the full offered doc set,
  so an unplaced document counts against the arm exactly as a document A1
  failed to ingest would.
- **Variant `+tail` (SUPPLEMENTARY; columns A2+tail, A2b+tail):** records
  that fit no hole are appended to a pre-reserved, pre-mapped tail of
  `forward_data.bin`, with new rows (growth of `forward_offsets.bin`, the
  doc-mapping override and `n_docs` published by the header flip). This is
  the fallback of brief §2.2. It is DESIGN ONLY until the format spec
  defines the region; postings of tail documents still need a slot (A2) or
  a list rewrite (A2b). Frozen A2 stays without tail append.
- **B7 power-loss arm, tightened.** Two models, 100 cut points each, both
  required for PASS: (i) every un-synced write lost; (ii) each un-synced
  4 KiB PAGE independently kept with p = 0.5 (early writeback), seeded.
- **Recorded deviation from §"Hard rules":** the hybrid rule (delta buffer
  for short lists) is NOT applied in the measured runs, because no serving
  path merges a document's short-list postings from the delta layer with
  its long-list postings in the shard. Every list is updated in place; the
  per-list-length breakdown of dropped postings is recorded so the cut-off
  of S0-1 can be read against it.
- **One reader table.** `readers.bin` of the format spec is the only
  reader table; the updater, the decoder and the harness helper use it.
  Dead-reader detection must be valid across pid namespaces (lease) or the
  updater refuses to run when it cannot verify a single namespace.
- **B2 reports two byte counts:** device bytes (`write_bytes`, the bar's
  number, unchanged) and logical bytes written.

Nothing in this addendum changes a threshold or the GO rule.

## Results table

State 2026-09-30 05:30Z. Real-shard numbers are on the Stage-0 ENCODED
SUBSAMPLE (32,155 upserts + 1,131,292 deletions), not the full quarter,
unless a row says otherwise. Queue and chain scripts:
`07_INPLACE_PAUSE_HANDOVER_2026-09-29.md` §0.

| Bar | What | Numbers | Script | Results file | Commit | Verdict |
|---|---|---|---|---|---|---|
| S0-1 | supply vs demand, long-list coverage ≥ 0.80 | sample f = 0.1005 (110 of 1,098 part files, 29.9 M records; deletions full window). Long lists (≥ 2,625 slots): 6,165 lists, 28.2 M postings. **Long-list coverage 0.0192** (bootstrap 95 % CI 0.0180–0.0204, 10,000 part-file resamples); deletions-only supply 0.0037; admissible demand 0.049 (decile 10, the 2,870 capped lists: 0.119); all lists 0.0149. Quarter demand *est.* 988 M new postings (663 M admissible) vs 14.8 M dead slots (3.2 M from deletions, 11.6 M from updated-old). Updated docs = **27.4 %** of shard 0 per quarter (CI 24.6–30.4 %; 5.15 M docs) + 2.83 M new docs routed to shard 0; real deletions 6.0 %. Hybrid cut-off: no decile reaches 0.50 | `eval_inplace_s0_1.py run` | `inplace_s0_20260930.json` key `s0_1` (2026-09-30 04:17Z) | `607545da` | **FAIL** |
| S0-2 | overlap@10 vs R_sim ≥ 0.99 at k = 1 / 3 / 6 (+ vs A0) | full run (scale 1.0), R_sim candidate-pool floor 0.14 × min posting weight (= 0.193; tau0 1.3760; deletion-only tau per quarter 1.224 / 1.052 / 0.862 / 0.654 / 0.433 / 0.211), measured 2026-09-30T23:25:55Z. k = 1: vs R_sim **0.8783 / 0.9150 / 0.9030** (QA / QT / QD; min per query 0.0; fails); vs A0 0.2671 / 0.3175 / 0.3740; R_sim vs A0 0.2179 / 0.2850 / 0.3310; NDCG@10 QA in-place 0.1679 / R_sim 0.1465 / A0 0.4085, Δ(in-place − R_sim) +0.0215 (CI 0.0115–0.0322, 120 topics); k = 3: vs R_sim **0.6992 / 0.7100 / 0.7150** (QA / QT / QD; min per query 0.0; fails); vs A0 0.1450 / 0.1642 / 0.1990; R_sim vs A0 0.0967 / 0.1425 / 0.1460; NDCG@10 QA in-place 0.0703 / R_sim 0.0470 / A0 0.2498, Δ(in-place − R_sim) +0.0233 (CI 0.0100–0.0382, 120 topics); k = 6: vs R_sim **0.6517 / 0.5842 / 0.6020** (QA / QT / QD; min per query 0.0; fails); vs A0 0.0717 / 0.0842 / 0.0930; R_sim vs A0 0.0458 / 0.0642 / 0.0610; NDCG@10 QA in-place 0.0240 / R_sim 0.0131 / A0 0.1048, Δ(in-place − R_sim) +0.0109 (CI 0.0025–0.0210, 120 topics). First break k = 1. Q1 inserts: 7,977,460 docs, 473,897,500 postings in the query lists, 7,886,064 placed (3,476,642 dead slot + 4,409,422 evicting), 466,011,436 dropped (98.3%). R_sim(0) fidelity vs served lists 0.9987. History: smoke 1 crashed 04:18Z (int64 −= float64, fixed `b447ef1e`); smoke 2 stopped 05:21Z on the floor guard (floor 0.8 → `--floor-frac`, `f4d88a83`); chain8 stopped 05:40Z for the night; 17:25Z smoke crashed at the first scoring step (`ranges(start, length)` → fixed `45c5168d`); 18:04Z smoke passed end to end (scale 0.02); 18:12Z full run asserted the floor guard at quarter 6 (deletion-only tau 0.211 < floor 0.413 at `--floor-frac 0.3`) → 0.14; 18:15Z full run peaked at 21 GB, 15.3 GB swapped out (16 GB swap full), scored 80/460 in 84 min, killed 22:38Z; `f6da4a1d` bounds the RSim peak and mlockall's the run, `fcce74ca` reads a cmp-verified local-disk copy of the twin (`INPLACE_TWIN_DIR`) after a 22:29Z ENOMEM over the 9p mount; final run 22:52Z–23:25Z, traversal to 23:43Z | `eval_inplace_s0_2.py run --floor-frac 0.14` | `inplace_s0_20260930.json` key `s0_2` (2026-09-30T23:25:55Z) | `bcc31577` | **FAIL** (for the record; NO-GO stands) |
| S0-3 | block visits ≤ +10 %, T* ≥ 1 quarter | inside the S0-2 run (2026-09-30T23:25:55Z, scale 1.0): block visits V(k)/V(0) − 1 (QA / QT / QD) k = 1: +287.9% / +269.0% / +275.7%; k = 2: +341.7% / +317.9% / +325.9%; k = 3: +364.6% / +338.9% / +347.4%; k = 4: +376.7% / +350.0% / +358.3%; k = 5: +383.9% / +356.7% / +365.3%; k = 6: +388.7% / +361.3% / +369.9%. **T\* = 0**. Supplementary (not pre-registered): engine-traversal replay overlap@10 vs exhaustive exact, QT, k = 0 0.8667 (min 0.2, 49/120 identical); k = 1 0.6800 (min 0.0, 24/120 identical); k = 3 0.4725 (min 0.0, 16/120 identical); k = 6 0.3225 (min 0.0, 15/120 identical) (2026-09-30T23:43:00Z) | `eval_inplace_s0_2.py` (+ `supp-traversal`) | `inplace_s0_20260930.json` keys `s0_3`, `supplementary.s0_3_traversal_vs_exhaustive` | `bcc31577` | **FAIL** (for the record) |
| M4 (`03_SPIKE_PLAN.md`) | read amplification = arm A1, GO input (slope ≥ 3 ms p50/gen) | parallel backend: p50 n0 2306.8 → n8 2535.9 ms; primary OLS slope **27.7 ms/gen** (bootstrap CI 14.8–34.1); paired per-query median slope 14.8 (CI 13.0–16.9). SEISMIC share ≈ 11 ms/gen by means (7 paired). Sequential backend and compaction arms NOT MEASURED | `eval_delta_ingest_m4_read_amp.py` | `delta_ingest_M4_20260929.json` | `60f24f4c` | M4 bar (≤ +8 ms/gen) **FAIL**; GO input (≥ 3 ms) **MET** |
| M5 (`03_SPIKE_PLAN.md`) | reload cost (B5's A1 side) | PASS on both roots (`spike/delta_ingest/M4_M5_FINDINGS.md`) | `eval_delta_ingest_m5_reload.py` | `delta_ingest_M5_20260930.json` | `275c31a4` | PASS |
| GO | S0-1 PASS ∧ S0-2 ≥ 1 quarter ∧ M4 tax ≥ 3 ms | S0-1 FAIL (0.019 vs 0.80; the CI upper bound is 40× below the bar); M4 leg MET; S0-2 FAIL (first break k = 1), recorded after the verdict and unable to change it | — | `inplace_s0_20260930.json` | — | **NO-GO** → CLOSED MEASURED (§"NO-GO 2026-09-30") |
| B1 | v3 zero-patch parity 460/460 | **460/460** identical (QA 240, QT 120, QD 100), ids and f32 score bits; build control 460/460; v2 reader rejects v3. Mask cost (reported, not gated): v3/v2 per-query ratio mean 1.0128 (CI 1.0091–1.0164), p50 2.876 vs 2.837 ms. Spare bits: 28 per posting word | `eval_inplace_b1_parity.py` | `inplace_b_20260929.json` key `B1` | `35a42f26` (guard `dd522d7a`) | **PASS** |
| B2 | apply cost A2 ≤ A1(N=1), wall + bytes | medians of 3 reps, 2026-09-30 03:31–03:47Z under the lock, cores 0-7: **A1(N=1)** (generation build of the same 32,155 docs from cached vectors, SEISMIC chain + tantivy/meta) wall **16.4 s**, device **0.487 GB**, logical 0.450 GB, places all 32,155. **A2** wall 13.3 s, device **1.280 GB**, logical 34.8 MB — places **0** docs (all 2,999,413 postings dropped unplaced). **A2b** 236.7 s / 2.200 GB / 1.098 GB, 0 placed. **A2-2p/old-at-free** 29.3 s / 2.695 GB / 58.5 MB, 29,651 placed, 929,614 postings inserted, 2,069,799 dropped for capacity. **A2-2p/old-at-fill** 27.6 s / 2.709 GB / 58.4 MB, 29,635 placed. A3 NOT RUN | `eval_inplace_bench.py b2` | `inplace_b_updater_20260930.json` key `B2` | `1da6c0e5` | A2 **PARTIAL** (wall ok, bytes 2.6× A1); A2b **FAIL**; A2-2p **FAIL** both |
| B3 | latency A2 ≤ 1.05 × A0, p50 + p95, both backends | HELD by the owner 2026-09-30 pending host-level write protection (`docs/infrastructure/INDEX_WRITE_PROTECTION.md` §4); moot after NO-GO | — | — | — | NOT RUN |
| B4 | storage after 1 and 4 quarters | real shard 0 (Q2–Q4 synthetic reuse of Q1's vectors): **A2** Q1 placed **0 / 32,155** docs; Q2–Q4 29,334 / 29,913 / 29,913 placed but only 0.90–0.98 M of 3.00 M postings inserted (68–70 % dropped for capacity); allocated +0.99 % after Q1–Q4. **A2b** Q1 0 placed, heap units 1.09 GB per batch of a 1.16 GB reserve → **exhausted at Q2 (1.06 batches)**. **A2-2p/old-at-free** Q1 29,651 placed, 13,276 evictions, device 2.53 GB | `eval_inplace_bench.py b4` | `inplace_b_updater_20260929.json` key `B4` | `ef48050d` | RECORDED |
| B5 | publish time; residency ≥ 99 % | 5 reps each, 2026-09-30 03:48–04:10Z. Publish (header write → first header poll seeing e+1): A2 0.32–1.01 ms, A2b 0.24–0.92 ms; batch start → inserts visible A2 9.4–13.1 s, A2b 230–240 s; no re-mmap in any rep. Residency: A2 reps 0–2, 4 kept 1.000, **rep 3 kept 0.643**; A2b reps 0–2 kept 1.000, **reps 3–4 kept 0.988**. The drops coincide with the two build agents copying/reading 5.2 GB shard copies on the same host (v3.1 conversion 03:48–03:49Z; updater pristine copy 04:04Z) — page-cache pressure on a 31 GB host, INFERRED from timestamps, not separately measured; the runs were not on a quiet host as the latency discipline requires | `eval_inplace_bench.py b5` | `inplace_b_updater_20260930.json` key `B5` | `1da6c0e5` | residency **FAIL** as recorded (both arms; confounded, see Numbers); timing RECORDED |
| B6 | overlap vs A3 ≥ 0.99 + NDCG CI (+ vs A0) | HELD (as B3); moot after NO-GO | — | — | — | NOT RUN |
| B7 | crash safety 100/100 | A2 rerun from zero 2026-09-30 17:11Z–21:20Z under the lock, cores 0-7 (the 04:11Z run was stopped at 05:37Z with 77/100 SIGKILL passed, 0 failed — INCOMPLETE, log kept as `b7_A2_partial_stopped_0930T0537Z.log`). **SIGKILL 100/100**: T_apply 15.31 s, kill time 0.02–15.26 s, published epoch after kill (epoch 0: 99, epoch 1: 1; start 0), 4,344 concurrent-reader query results checked, 0 mismatches, 0 reader errors. **Power-loss drop 100/100** (epoch 0: 100), **pages 100/100** (epoch 0: 100); cut points uniform over 3209320 logged ops; recover+verify on every 10th power-loss trial (20 trials, 0 violations). Checker: updater exact reference search (bit-identical f32 scores); v3 decoder NOT used (not available for this arm); per-trial log `stage2/real_logs/b7_0930T171140.log`. The A2-2p and A2b arms were removed from the queue at 05:20Z under the NO-GO rule; their SYNTHETIC 100/100 stands as synthetic only (`inplace_b_updater_synthetic_20260929.json`) | `eval_inplace_bench.py b7 --trials 100 --arms A2` | `inplace_b_updater_20260930.json` key `B7` (2026-09-30T21:20:53Z) | `dfc06e6e` | A2 **PASS** (2026-09-30); others NOT RUN |
| W1 (supplementary) | write-unit byte distribution, block vs list | write unit **LIST**: 0 of 3,203,940 blocks contiguous; whole list p50 21,528 B, p99 159,572 B | `eval_inplace_w1_writeunit.py` | `inplace_writeunit_20260929.json` | `ea264b6a` | RECORDED (LIST) |
| P1 (supplementary) | vector-diff control + demand, M7 vector re-score | control (3,000 byte-identical docs): **100%** not `unchanged_exact`, 100% not `_tol`, max abs Δw p50 1.36 (absolute weight), component set differs 100% → **UNRELIABLE AS DEFINED**, smallest tolerance under 1 % false change = max_ulps 1e+09, set-diff weight 1e+09 (unbounded, i.e. no usable tolerance). M7 re-score (shard-0 routed): `works_updated_date=2026-09-15_part_0001.gz`: 4,294/4,294 in-base docs vector-changed, touched:must-encode 1.00 exact / 1.00 tol (post hoc 1.21); `works_updated_date=2026-09-22_part_0054.gz`: 6,004/6,004 in-base docs vector-changed, touched:must-encode 1.00 exact / 1.00 tol (post hoc 7.77). `new_vd`/`dead_vd`: long-list coverage 0.0193 (CI 0.0180–0.0204), 129,323 / 129,323 encoded updated docs vector-changed | `eval_inplace_p1.py` (`control`, `m7`, `record`) | `inplace_s0_20260930.json` key `supplementary.P1` (`control`, `m7_vector`, `new_vd_dead_vd`) | `ce4e158f` (record at `bcc31577`) | control UNRELIABLE; filter cannot reduce demand |
| A2b (supplementary arm) | B1–B7 in its own column beside A2 | unit encoder identity: **28,702 / 28,702** lists byte-identical (`stage2/identity_full.json`, 2026-09-29 21:51Z, console). B2 FAIL, B4 heap exhausted at Q2, B5 residency FAIL (confounded). Unit read path + reader registration test (2026-09-30 04:11Z): parity unit-vs-oracle **460/460**, but 0 queries changed vs the zero-patch baseline (dropped block held 5 postings, none in any top-200) → **FAIL on the harness's non-vacuity rule**, no wrong result; costs: registration 297 ns per register+unregister, unit build 126 µs (checksum 123 µs of a 122 KB unit), first touch +0.18 ms median, registration on−off +1.8 µs/query median. Non-vacuous rerun 05:21Z (`inplace_a2b_read_20260930b.json`, fixture `853e5b12`, cores 8-15, no lock): **PASS 460/460**, 4 queries changed vs the zero-patch baseline (the 4 predicted), readers free afterwards | `eval_inplace_bench.py`, `eval_inplace_a2b_read.py` | `inplace_b_updater_2026093{0}.json`, `inplace_a2b_read_20260930.json`, `inplace_a2b_read_20260930b.json` (non-vacuous rerun) | `1da6c0e5`, `acb16db9` | B2 FAIL; B4 RECORDED; B5 FAIL; read test PASS on the non-vacuous rerun (first run vacuous) |
| A2-2p (supplementary variant) | two-phase A2, sub-variants old-at-free / old-at-fill, B2–B7 | B2 FAIL both (wall 27.6–29.3 s vs 16.4; device 2.7 GB vs 0.49); B4 recorded (old-at-free); B7 removed from the queue under NO-GO | `eval_inplace_bench.py` | `inplace_b_updater_20260930.json` key `B2` | `1da6c0e5` | B2 FAIL; B4 RECORDED; B7 NOT RUN |
| +tail (supplementary variant) | A2+tail / A2b+tail, forward tail append, B2–B7 | BUILT 2026-09-30 (FORMAT_V3 revision 6; fork `d7cbae1`, patch `spike/archive/inplace_update/patches/seismic_upstream_inplace_v3_tail.patch`; updater `d456f4a3`, harness arms `1d069329`). Read side: synthetic fixture vs native oracle **PASS 460/460** (406 queries with tail docs in their top-200); shard-0 v3.1 zero-patch parity vs A0 **PASS 460/460** (`inplace_tail_read_20260930.json`). Write side (updater `d456f4a3`, findings `cad6fa45`): crate tests 31/31; SYNTHETIC A2b+tail places 2,500/2,500 on batch 1 via the tail, heap reuse ON runs 14/14 synthetic batches where reuse OFF refused the 4th (`inplace_b_updater_synthetic_20260930.json`, `…_r7off_…`). INDICATIVE on the v3.1 copy of shard 0 (host shared, timings invalid, `inplace_b_updater_indicative_v31_20260930.json`): **A2b+tail Q1 places 29,651 / 32,155 docs, all via the tail** (818,900 tail words = 1.7 % of the reserve; 29,651 rows), but still only 929,614 of 2,999,413 postings inserted (**69 % dropped for capacity**, 13,276 evictions), heap bump 1.116 of 1.159 GB, storage +1,136 MB, **Q2 refused (heap exhausted; nothing reusable yet at epoch 2)**; A2+tail Q1 still 0 placed (no dead slot, so every posting is dropped before a record is needed). B2–B7 for +tail NOT RUN (NO-GO): +tail removes the forward-record obstacle only; S0-1 shows the posting-slot supply is the binding one | `eval_inplace_tail_read.py` | `inplace_tail_read_20260930.json` | `e8f85d1c`, `36910b43` | read PASS; write IMPLEMENTED, EFFICACY UNMEASURED; bars NOT RUN |

## NO-GO 2026-09-30 — reading of the frozen GO rule

Read 2026-09-30 04:17Z from `inplace_s0_20260930.json` (S0-1) and
`delta_ingest_M4_20260929.json` (M4). Nothing here loosens or re-cuts a
bar.

- **S0-1 FAIL.** Dead-slot supply covers **1.9 %** of the new-posting
  demand in long lists (CI 1.8–2.0 %), against a bar of 80 %. The gap is
  not a sampling or definition artefact: with the bar's own stricter
  reading replaced by admissible demand the number is 4.9 %; restricted to
  the capped decile it is 11.9 %; with the P1 vector-diff filter (which
  turned out unable to exclude any doc) it is unchanged. The cause is the
  churn itself: in one quarter **27 % of shard 0's docs are updated and
  15 % more are new**, while real deletions free **6 %** and a list
  cannot grow. Fixed-size lists with dead-slot reuse cannot absorb that.
- **M4 leg MET** (27.7 ms/gen ≥ 3 ms), so the generation tax the spike was
  meant to remove is real; but roughly half of it is BM25F sections and
  abstract probes, which an in-place SEISMIC shard would not touch
  (`spike/delta_ingest/M4_M5_FINDINGS.md`).
- **S0-2 FAIL, S0-3 FAIL** (landed 2026-09-30 23:25Z / 23:43Z, for the record: overlap@10 vs R_sim 0.878–0.915 at the first quarter, block visits +269–289 %, T* = 0). They cannot change the verdict (GO needs all three legs).
- Stage 1 evidence, recorded for the closed track: B1 PASS (the v3
  encoder/decoder is exact and costs +1.3 % per query); B2 shows A2 writes
  2.6× the device bytes of a one-generation delta build while placing zero
  documents, and A2b/A2-2p are 4.5–5.6× the bytes; B4 shows 68–70 % of
  offered postings dropped even when holes exist and A2b's heap exhausted
  after one batch; the +tail variant was built and its read side proved
  exact, but it removes the wrong obstacle.
- **Consequence (pre-registered):** the track is recorded **CLOSED
  MEASURED 2026-09-30** and stops. B7 A2 (PASS 300/300, 2026-09-30 21:20Z) and the S0-2
  chain (2026-09-30 23:43Z) finished for the record (no new dispatch); B7 for the supplementary
  arms was dropped from the queue at 05:20Z. The closure commit (banners,
  moves to `docs/archive/inplace_update/` and `spike/archive/` /
  `scripts/archive/`, README rows, repointed references) follows once
  those rows land, per `.claude/CLAUDE.md` §"Closed tracks".
- **What survives for `delta_ingest/`:** the measured quarter churn
  (27 % updated + 15 % new + 6 % deleted of a shard per quarter) and the P1
  result (re-encoding a byte-identical text does not reproduce the stored
  vector, so no vector diff can filter churn) are inputs to the delta
  track's compaction and rebuild cadence; the v3 mask-cost and spare-bit
  measurements are reusable facts about the dv-v2 format.
