# 04 · The non-monotonic convergence artifact (R1, 2026-07-14)

**The canonical write-up of the observation** referenced from
`11_EXPERIMENT_BACKLOG.md` §R1. Status: MEASURED (the observation);
literature-anchored (the mechanism); the composite phenomenon appears to be
undocumented as such (checked 2026-07-14, see §4).

## §1 The observation

In the R1 RAM-ladder (fixed 3-pass cells, identical repeating 40-query
workload, `r1_cap{16,12}g_20260714.json`):

| cap | pass 1 (majflt) | pass 2 (majflt) | pass 3 (majflt) |
|---|---|---|---|
| 16 GB | 942 ms (104k) | 463 ms (56k) | **135 ms (15k)** |
| 12 GB | 1855 ms (243k) | 1381 ms (187k) | **22 ms (2.4k)** |

At the fixed pass-3 snapshot, the **smaller** cap is 6× faster with 6× fewer
faults — apparent non-monotonicity in cap size. Meanwhile 24 GB+ sits at
18–19 ms / 0 faults from pass 2 onward, and 8 GB/6 GB never improve at all.

## §2 The mechanism (two working sets × pressure-scaled aging × fixed window)

1. **Two working sets.** The load leaves ~14.3 GB file-backed resident, of
   which only a *per-pass repeat set* (est. ~10–11 GB) is re-touched by the
   queries; the rest is load residue (touched once, never again). Steady
   state requires only the repeat set to be resident.
2. **Eviction is a sorting process whose speed scales with pressure.** The
   kernel cannot know residue from repeat set a priori; its two-list
   LRU/second-chance machinery learns by reference bits, and it only does
   that aging work during reclaim — whose scan rate is proportional to
   memory pressure. 16 GB = demand exceeds cap by a sliver ⇒ lazy reclaim ⇒
   slow sort (104k→56k→15k, an asymptote to ~0 caught mid-flight). 12 GB =
   ~3.5 GB over ⇒ reclaim runs hot ⇒ sort completes within 2 passes ⇒ pass 3
   clean (the repeat set just fits in ~10.9 GB of available cache).
3. **A fixed observation window turns convergence-speed differences into an
   apparent latency inversion.** Both 16 GB and 12 GB converge to the same
   ~19–22 ms steady state; only their time-to-converge differs. Pass-3
   sampling is a truncated view.
4. **Below the repeat set (8/6 GB) the phenomenon disappears** — no sorting
   can fit 10–11 GB into 6.9 GB; the deficit re-faults every pass regardless
   of policy (261k/550k majflt steady). That regime is capacity arithmetic,
   not transient behavior.

## §3 Why this is NOT Belady's anomaly

Belady's anomaly is *steady-state* fault-count non-monotonicity under
non-stack policies (FIFO, second-chance-as-FIFO, random). LRU is a stack
algorithm with the inclusion property and provably cannot exhibit it — and
our data complies: **steady states are monotonic** (every cap ≥12 GB reaches
~19–22 ms; every cap ≤8 GB thrashes proportionally). The inversion lives
entirely in the transient, which the stack property does not constrain.

## §4 Literature anchoring (searched 2026-07-14)

- **Capacity-scaled convergence time — documented (theory).** "Analysis of
  the LRU Cache StartUp Phase and Convergence Time and Error Bounds on
  Approximations by Fagin and Che" (WiOpt 2022,
  https://ieeexplore.ieee.org/document/9930556/ , PDF
  https://dl.ifip.org/db/conf/wiopt/wiopt2022/1570811601.pdf ) and Li et
  al.'s mixing-time estimates for LRU/FIFO/RANDOM/CLIMB under Zipf (survey:
  https://arxiv.org/pdf/2308.02875 ). The Che/Fagin characteristic time
  grows with cache capacity ⇒ bigger caches take longer to reach steady
  state ⇒ any fixed-horizon measurement can catch a big cache mid-transient
  while a small one has settled. Our §1 table is a real-system instance.
- **Pressure-scaled aging — documented (kernel).** Reclaim scan rates scale
  with reclaim priority/pressure (https://kernel-internals.org/mm/reclaim/);
  the sluggishness of two-list aging under light pressure is part of the
  stated motivation for the multi-generational LRU
  (https://lwn.net/Articles/851184/ , merged 6.1). The theory papers model
  request-driven aging only; the kernel adds this second, pressure-driven
  clock — which *amplifies* the inversion (12 GB got a shorter
  characteristic time AND a faster aging clock).
- **The below-cliff regime — documented (databases).** Cyclic access
  patterns larger than cache = "sequential flooding," LRU's known worst case
  (https://tinkeringwithdata.wordpress.com/2019/04/14/understanding-sequential-flooding/ ,
  https://cs186berkeley.net/notes/note5/ ). Corollary worth recording: the
  known-optimal policy for a cyclic pattern is "keep a fixed subset resident,
  miss on the rest" — **the F3 mlock pin tier is exactly that policy**, so
  pinning under thrash is theory-optimal, not merely pragmatic.
- **The composite — apparently NOT documented.** No source was found that
  instruments the Linux page cache with per-pass fault counts and reports
  the fixed-window inversion ("smaller cap converges first") as an
  observable. The WiOpt line is synthetic-trace theory; kernel discussions
  describe mechanisms, not this measurement. Treat the R1 observation as a
  potentially novel (small) empirical note.

> **Prior-art re-check 2026-08-31** (web sweep: kernel docs/LKML/LWN, cache
> literature, HN/StackExchange/forums): still no source found reporting the
> composite observable ("smaller cap converges first" as a fixed-window
> latency/majflt inversion on the Linux page cache). Closest new adjacent
> find: Zhang & Yang, *"When is the Cache Warm? Manufacturing a Rule of
> Thumb"* (USENIX HotCloud '20,
> https://www.usenix.org/system/files/hotcloud20_paper_zhang-lei.pdf ) —
> warmup *time as a function of cache size* for application caches
> (larger caches take longer to warm), but at the hit-ratio/app-cache
> level, with no kernel pressure-scaled-aging clock and no fixed-window
> inversion. The §1 observation remains unclaimed as such.

## §4b Addendum (same day): what the F3 pin refutation adds

The pin-ON cells (`r1_cap{8,6}g_pin16_20260714.json`) landed after this note
was first written and bear on it two ways:

1. **Independent corroboration of the §2 mechanism.** The refutation's root
   cause — "the most-touched pages are exactly the ones the kernel's active
   list already protects under churn, so the pin insured the wrong pages" —
   is the same reference-bit promotion machinery §2 credits with the
   sorting. The pin experiment proves that machinery works *even in the
   sustained-thrash regime* (hot pages self-protect at 550k faults/pass):
   mlock added almost no residency the two-list LRU wasn't already
   providing. The artifact's mechanism now has two independent measurements
   behind it (the convergence trajectories AND the pin null-protection).

2. **Fault COUNTS are a state metric, not a cost metric.** At 6 GB, pin-ON
   raised majflt only +7% (550k→587k) but latency +35% (4.9→6.6 s) — i.e.
   per-fault service cost rose **0.358 → 0.452 ms (+26%)**. Interpretation:
   ~1.6 GB of mlocked extents interleaved through the forward slab fragment
   the fault runs — the kernel's readahead can no longer coalesce
   contiguous-miss windows across locked (never-faulting) ranges, so more
   faults become discrete random reads. Methodology rule derived:
   **majflt trajectories remain the right convergence indicator (§5.2), but
   cross-configuration latency comparisons must not assume constant
   per-fault cost — report ms/fault alongside counts.** (At 8 GB the effect
   was mild: 0.327 → 0.338 ms/fault — the fragmentation penalty scales with
   how starved the cache is.)

## §5 Practical consequences

1. **Never quote a pass-k latency as "steady state" near the working-set
   boundary** without checking the fault trajectory for convergence (16 GB's
   135 ms is NOT its steady state; the backlog table marks it accordingly).
2. **Bounded-pass benchmarks under-report marginal-fit configurations** —
   they charge the whole sorting transient to the measurement window. Either
   run to convergence (fault count → ~0 or plateau) or report the trajectory.
3. **The sorting can be skipped entirely**: with the hot-set sidecar, F5
   `release_pages_except` evicts the residue by name at load — jumping
   straight to the sorted state without any pressure or observation passes
   (the F5 16 GB cell tests exactly this claim).

   > **STATUS 2026-08-31 (b) — SUPPORTED ON THE SYNTHETIC, still UNTESTED on
   > the real stack.** The Tier-1b early-sort arm finally had a real baseline
   > transient to remove, and the map-guided lever removed **all of the
   > removable part**: at the marginal rung fault work to convergence fell
   > 423,700 -> 105,268 majflt (**-75.2%**, 10 passes to zero -> 2), at
   > boundary 785,176 -> 198,656 (**-74.7%**, 8 -> 2). Both land exactly on
   > the irreducible floor — the pages that were never loaded must be read
   > once — so ~75% is the mechanism's physical ceiling, not a shortfall.
   > The pre-registered ES-2 bar asked for >=80% and is therefore
   > **unreachable by construction**; the ES arm is scored OVERALL FAIL and
   > that FAIL does **not** refute this section. Judged on p95 the arm is
   > blind to the effect (see the Tier-1b addendum). Evidence:
   > `spike/convergence_repro/RESULTS.md` Tier-1b section 12; cells
   > `data/eval_results/convrepro_t1b_es_guided_*_20260831.json`.
   >
   > **STATUS 2026-08-31 (a) — this claim is still UNTESTED on the real stack.**
   > The 2026-07-14 F5 16 GB cell that was supposed to test it was a NULL with
   > a diagnosed scope bug: the hook released only the forward codec slab,
   > while the load residue this section is about lives in the structural
   > slabs. **The scope bug is now FIXED IN CODE, EFFICACY UNMEASURED ON THE
   > REAL STACK** (pending its own pre-registration). Fork commit `2c4d863`;
   > `spike/seismic_upstream/src/mmap_io.rs` +
   > `src/pylib/mmap_index.rs`; patches `spike/seismic_upstream_fork.patch` and
   > `spike/seismic_upstream_f5_scope_fix.patch`. Synthetic verification (Rust
   > test `release_pages_except_covers_all_slabs`, 600-doc index, no 150M index
   > touched): released-byte coverage went from the forward slab only to all
   > mapped slabs — dotvbyte 9,600 B → 42,554 B (4.43×), f16 4,200 B →
   > 41,354 B (9.85×). The byte accounting was also corrected (madvise failures
   > now count 0, which is why the old cell could report "released 16.45 GB"
   > with RssFile unchanged). **No `.so` was rebuilt** — the served binary
   > still carries the pre-fix hook. Full record:
   > `docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md`, R1 "F5 release-except
   > cell" entry. The synthetic early-sort arm testing the same claim under a
   > controlled residue is `spike/convergence_repro/PREREGISTRATION_EARLYSORT.md`.
4. On the operator question "can we trigger the forced reclaim manually to
   get the benefit without scaling the host": yes — that is F5 (map-guided,
   this repo), or map-blind equivalents documented in production elsewhere
   (cgroup `memory.reclaim` / Meta TMO-senpai / DAMON_RECLAIM — see
   `05_EXTERNAL_PRECEDENTS.md`). Where it helps: the marginal band only
   (cap ≈ WS). Above: unnecessary. Below the repeat set: nothing but pinning
   or shrinking the working set helps.

## §6 Metrics glossary (added 2026-07-14)

Working name for the composite phenomenon: **non-monotonic convergence
artifact**, also referred to in-session as the **fixed-window convergence
inversion** — both name the same observation (§1).

Directly measured:

- **Major page fault (majflt)** — a memory access whose page is not in the
  page cache, so servicing it requires disk I/O (here: reading the mmap'd
  index back from disk). Read per pass from `/proc/<pid>/stat`. Each costs
  roughly one SSD read (~0.3–0.5 ms in these cells).
- **Minor page fault (minflt)** — a fault satisfied without disk: the page is
  already in the page cache and only the mapping is created. Near-free
  (microseconds); tracked to confirm latency movement is majflt-driven.
- **Pass latency** — wall-clock time for one complete pass of the fixed
  40-query workload. The user-visible cost; majflt is the mechanism under it.
- **Cap** — the cgroup memory limit imposed on the container for a cell
  (48/32/24/16/12/8/6 GB). Bounds resident page cache + anon memory;
  exceeding it triggers reclaim.

Derived:

- **Per-fault service cost (ms/fault)** — pass latency ÷ majflt. First-class
  metric per §4b: fault counts are a *state* metric (how much of the repeat
  set is resident); cost per fault varies with I/O pattern (readahead
  fragmentation moved it 0.358 → 0.452 ms at 6 GB pin-ON). Never compare
  cross-configuration latencies assuming constant fault cost.
- **Fault trajectory** — the majflt sequence across passes (16 GB:
  104k → 56k → 15k). Shape is the diagnostic: falling toward ~0 = kernel
  still sorting (transient); flat and large = capacity thrash; flat at ~0 =
  converged. A single pass-k value cannot distinguish these.
- **Steady state / convergence** — the regime where the fault trajectory has
  plateaued and pass latency stops changing. Pass 3 is steady state for
  12 GB but NOT for 16 GB — the artifact in one sentence.

Memory-population concepts the metrics describe:

- **Working set** — all file-backed pages the process ever touches; the load
  leaves ~14.3 GB of it resident.
- **Repeat set** — the ~10–11 GB subset the queries re-touch every pass;
  steady state requires only this to stay cached.
- **Load residue** — working set minus repeat set: pages touched once at
  load, never again, which reclaim must identify and evict (the "sorting" of
  §2).
- **Residency** — how much file-backed data is actually in RAM at an instant.
  Residency is the state; majflt is how we observe it change.

Theory-side:

- **Characteristic time (Che/Fagin T_C)** — from the WiOpt-line literature
  (§4): roughly how long a page survives in an LRU cache before eviction;
  grows with capacity, which is why bigger caches provably take longer to
  converge. Not measured directly here — it is the concept connecting our
  fault trajectories to the published convergence-time results.

## §7 The fine ladder (R2, measured 2026-07-14)

Backlog §R2: 1 GB rungs 17→9 GB + anchors 24/6 + replicates at 16/13/11,
convergence-terminated (min 3 / max 12 passes), per-pass cgroup-v2
`memory.stat` deltas. Cells `r2_cap*_20260714.json`; verified table in
`data/eval_results/_r2_ladder_summary.md`. What it adds to §1–§5:

1. **The cliff is measured, not estimated: between 10 and 11 GB.** Every
   cap ≥ 11 GB converges to a flat 17.9–18.9 ms with faults → ~0; every cap
   ≤ 10 GB plateaus in sustained thrash. The §2.1 repeat-set estimate
   (~10–11 GB) is now an empirical boundary.
2. **The §1 inversion replicates — but the §2 mechanism needs one
   refinement.** At a fixed pass-3 window, 12 GB reads p50 21 ms vs 16 GB's
   124 ms (R1: 22 vs 135) — yet 12 GB carried MORE residual faults at that
   snapshot (26k vs 15k). The inversion is therefore carried by *where* the
   residual faults land across queries (12 GB's residue misses the median
   query; 16 GB's is spread, lifting p50), not by the smaller cap having
   finished the whole sort. Meanwhile passes-to-full-convergence is flat
   (4–5, ±1 between replicates) across the whole 11–17 GB band — the
   capacity-scaled convergence-time prediction (§4, Che/Fagin) is NOT
   resolvable at pass granularity in this narrow band. §2.3's
   "only time-to-converge differs" is thus too strong: total drain time
   differs little; the p50-visible portion of the transient is what differs.
3. **§2.2 (pressure-scaled aging) upgrades from inference to direct
   observation.** Pass-1 cgroup pgscan is monotone in pressure: 24g 0 →
   17g 0.56M → 16g 1.1M → 12g 2.8M → 11g 3.5M → 10g 4.0M → 6g 7.1M scanned
   pages. workingset_refault_file → 0 at convergence above the cliff and
   stays at 1.6–4.7M/pass below it. Cleanest single datum: at 24 GB the
   active_file gauge ends at **0.2 GB** (reclaim never runs ⇒ the kernel
   never promotes anything ⇒ the sort literally does not happen because it
   is not needed), versus 7.5–8.8 GB at 11 GB where the repeat set must
   earn active-list protection under churn.
4. **Methodology confirmations.** The §5.1 rule is quantified: cells stopped
   by the near-zero rule with 0.5–2k residual faults still read 21–36 ms —
   steady-state p50 may only be quoted from a majflt≈0 pass. Replicates are
   cheap insurance: one host-noise event (13g rep1 mid-run fault bounce on
   the shared WSL2 page cache) was caught and arbitrated by its replicate.

## §8 Per-page attribution (R3, measured 2026-07-16)

R3 (`docs/seismic_150m_testbed/15_R3_KERNEL_LEDGER_SPIKE.md`; pre-registration +
measured bars in `11_EXPERIMENT_BACKLOG.md` §R3) took the §2/§7.2 mechanism
statement — "the inversion is carried by *where* the residual faults land
across queries, not by the smaller cap having finished the sort" — and asked
the kernel to show its work per page: which shard extents were evicted when,
which came back, at what refault count, and which of the 40 queries touch
exactly those extents. A bpftrace eviction/refault ledger
(`mm_filemap_{add,delete}_from_page_cache`, 1/512 extent-downsampled, filtered
in-probe to the 8 shard-file inodes) + a `workingset_refault` kprobe + between-pass
`cachestat()` (syscall 451) residency maps, joined on `(ino, pgoff→extent)` and
pass-boundary CLOCK_MONOTONIC windows against a per-query extent-touch map from
the `search_visited` pyo3 surface. Cells: the 12/16 GB inversion pair, each with
an uninstrumented control (latency quoted only from controls). G-R3-0 capability
gate PASS 7/7 on the WSL2 6.18.33 kernel.

What the ledger adds to §2/§4/§7:

1. **The §7.2 refinement is directly observed, and its "where the faults land"
   half is REFUTED.** §7.2 inferred "12 GB's residue misses the median query;
   16 GB's is spread, lifting p50" from per-pass aggregates. The per-page join
   shows the opposite: residual faults are **uniformly spread** across all 40
   queries in BOTH caps (pass-3 per-query DEL-extent skew max/mean 1.14 at 12g,
   1.32 at 16g — both ~1.0, no slow tail). The structural reason: the repeat
   set's extents are shared across all queries (19.6% of the 10,471 extents
   touch all 40 queries; only 1.8% touch one) — so residual faults *cannot*
   concentrate in a per-query slow tail. The inversion is carried SOLELY by the
   §7.2 *first* half — convergence-trajectory position at the fixed window
   (12g's pass-3 is mid-sort at majflt~140k while 16g's is near-converged at
   ~15k) — NOT by per-query fault distribution. This sharpens §2.3 ("only
   time-to-converge differs"): the per-query-distribution qualifier drops; the
   fixed-window-truncation-of-the-transient is the whole story.

2. **The §2.2 pressure-scaled-aging picture, at page granularity — CONFIRMED.**
   §2.2 (and §7.3) inferred the "16 GB not yet sorting / 12 GB sorting"
   asymmetry from cgroup `pgscan`. The between-pass cachestat maps picture it
   directly: at pass-0 (post-load) 16 GB holds the full ~14.3 GB working set
   (evicted **0.0 GB** — kernel not yet sorting) while 12 GB is already shedding
   (evicted **3.17 GB** — sort in flight). Both drain toward the ~10–11 GB
   repeat set (12g → 10.13 GB) by convergence — the §2.1 estimate, now an
   extent-residency map not a single number. (Caveat honestly recorded: 16g's
   *live-tracer* drain stops at 13.43 GB — the bpftrace probes + cachestat
   snapshots added pressure that perturbed 16g's reclaim timing, the very
   observer effect §4/'doc 15 §4' warn about; the pre-fix dead-tracer 16g cell
   corroborates the 10.93 GB drain in the un-perturbed regime. This is WHY
   latency is only quoted from controls.)

3. **§4's Che/Fagin link, watched per pass — half-CONFIRMED, half-UNCLEAR.** The
   §4 capacity-scaled characteristic-time prediction (bigger cache ⇒ longer
   convergence ⇒ fixed-window catches it mid-transient) is corroborated by the
   per-pass refault COUNT (the `workingset_refault` kprobe's ×512-scaled count
   matches the kernel's own `workingset_refault_file` cgroup counter within
   **1.8%** at 12g / **0.3%** at 16g — a 1/512 sample reconstructing the
   kernel's own event count within ~1%). But the per-event refault DISTANCE
   (the local in `mm/workingset.c::workingset_refault()` that encodes the
   LRU slot, where §4's "distance exceeds active_file ⇒ activation flips"
   decision lives) is NOT extractable under the WSL2 kernel's BTF → emitted -1,
   the §R3-documented downgrade (activation inferred downstream). So §4's link
   is watched at per-pass count granularity, not per-event distance — the
   distance-vs-active_file decision site remains inferred, not directly
   observed. (Activating the BTF function-local extraction would require either
   a kernel with the local exposed or a manual shadow-entry decoder — out of
   scope here, recorded as the open next step.)

4. **§5.1 / §7.4 methodology, hardened.** The observer-effect bar (instrumented
   steady-state p50 ≤ 1.10× control) is measured: the clean-probe 12g cell reads
   **1.006×** (within bar); the 16g cell reads 1.120× steady-state / 1.072× at
   the symmetric pass-3 transient. The lesson reaffirmed: the overhead must be
   compared at each cell's *most-converged* pass (the steady-state regime it
   actually reached), NOT a fixed pass-index — the two cells converge in
   different pass counts (12g took 5 vs ctrl's 4, tracing-pressure-delayed), so
   a fixed index is apples-to-oranges (12g pass-3 = mid-sort 824 ms vs ctrl
   near-converged 20 ms ⇒ a bogus 40× ratio). And the refault-ratio verifier
   heuristic, written pre-sampling, compared the 1/512-sampled probe against
   `majflt` (~7× too few) — flagging a designed property as a defect; corrected
   to reference the kernel's own `workingset_refault_file` (1–2%), a recursion
   of the §4b "fault count is a state metric; pick the right denominator"
   lesson at the probe layer.

The headline upgrade: §7.2's "where the faults land across queries" inference
is REFUTED by direct per-page observation (faults land uniformly; the repeat
set is shared) — the inversion's *entire* per-query story is the fixed-window
truncation of the convergence transient, nothing more. The §2.2/§7.3
pressure-scaled-aging picture and the §4 characteristic-time prediction are
CONFIRMED at page granularity (the count half) or corroborated (the distance
half stays inferred). Result files: `data/eval_results/r3_cap{12,16}g_instr_*.json`
+ `_r3_cap*_instr_*_ledger.log` / `_refault.log` + `_r3_cachestat_cap*_instr_*_pass*.json`
+ `_r3_query_extent_map.json` + `_r3_inode_map.json`; join +
verdicts in `data/eval_results/_r3_join_analysis.json` and
`data/eval_results/_r3_ledger_summary.md`.

---

## Addendum 2026-08-31 — Tier-1 synthetic repro: FAIL (negative result, recorded)

> **SUPERSEDED the same day by the Tier-1b addendum below.** Tier-1's failure
> was a protocol artifact (the load pre-sorted the data). Tier-1b fixed that
> and reached a substantive negative result. Read both; act on Tier-1b.

The pre-registered index-independent synthetic repro
(`spike/convergence_repro/PREREGISTRATION.md`, publication-gate item 1) ran
at SCALE=1 on the WSL2 host 2026-08-31 and **FAILED its bars** (1/3/4 FAIL,
2/5 PASS; the early-sort arm's ES-2 came back NO DATA because no baseline
transient existed, so the §5.3 claim remains UNTESTED — not refuted).
Mechanism: the harness loads L then R sequentially, so R is always fully
resident at pass 1 under any cap > R — the load itself performs the "sort,"
leaving three zero-fault rungs and two hard-thrash rungs with no converging
regime to invert. This is the pre-declared access-structure-dependence
discrepancy class, recorded per protocol. The ES-5 exploratory datum
(inactive-list order protecting R: 100%→97.7%→79.9%→39.8% survival as caps
descend; blind `memory.reclaim` cost ~8 ms ≈ guided's ~5 ms, overturning the
"far larger" cost prediction) is the run's keeper. Full verdicts, calibration
trail (marginal TUNED 7g→6.64g, flat), harness defects, and the Tier-1b
redesign requirement: **`spike/convergence_repro/RESULTS.md`**. Raw cells:
`data/eval_results/convrepro_*_20260831.json` (commit `6ee8a982`).
Publication gate stays closed; spin-off blocked pending Tier-1b.

---

## Addendum 2026-08-31 (b) — Tier-1b synthetic repro: FAIL, and this one is substantive

Tier-1b (`spike/convergence_repro/PREREGISTRATION_TIER1B.md`) rebuilt the
harness around an **interleaved** L/R load and re-positioned the rungs below
total demand D. It worked: post-load residency of R was strictly below 100% at
every rung under the cap (92.34 / 84.84 / 54.96 / 40.00% for marginal /
boundary / thrash / deep), so the convergence transient the artifact needs
**existed** this time, and the pre-authorized calibration gate was never used —
the frozen 6.25g marginal cap produced it on the first try.

**The inversion still did not appear.** At the pass-3 window boundary p95 =
0.157 ms vs marginal p95 = 0.006 ms, an inversion ratio of **0.04x** against a
predicted 2–20x: the *smaller*-deficit rung converges faster, not slower.
Marginal and boundary majflt trajectories are self-similar, scaled by their
initial deficits (ratio 1.92 / 1.86 / 2.04 / 1.92 over passes 1–4, vs a load
deficit ratio of 1.98). Pressure-scaled aging is real but second-order:
boundary's per-pass geometric decay is 0.582 vs marginal's 0.646 (~10% faster,
enough to reach zero faults at pass 8 vs pass 10 with twice the deficit — not
enough to invert a 2x head start inside three passes). **Verdict: on this WSL2
classic-LRU host, with a naive two-population interleaved load and
uniform-random repeat, the fixed-window convergence outcome is
deficit-dominated.** Bars 1b/2b/3b FAIL, 4b/5 PASS, OVERALL FAIL. The
publication gate stays closed and the spin-off stays blocked.

The conclusion is **robust to the metric** (on `clat` mean, pass-3 boundary is
still 1.98x slower than marginal), but two of the three failing bars are not
about the hypothesis at all — Tier-1b's bars moved p50 -> p95 to see faults,
and p95 turns out to be a *threshold detector*: a percentile p_X reads fault
latency only while the fault fraction exceeds (100-X)%, so at 1,310,720 ops per
pass p95 flips hard at 65,536 faults. Bars 2b and ES-3 then fail on ~100 ns
differences inside a +/-16% cache-hit noise floor. Recorded in
`spike/convergence_repro/RESULTS.md` sections 11 and 15 as bar-design findings;
no verdict was re-scored.

**Two results worth carrying forward regardless of the gate:**

1. **Load order is the initial-state selector** (exploratory order arm, plus
   the two baselines). Same cap, same working set, same access pattern, three
   load orders, three qualitatively different regimes: L->R (Tier-1) leaves R
   100% resident and produces **no transient**; interleaved (Tier-1b) gives a
   **decaying** one (159,641 -> 61,130 majflt); R->L gives a **rising** one
   (233,448 -> 275,840, p95 pinned at 185–189 us). This upgrades the Tier-1
   load-order explanation into a measured three-point finding, and it is why
   the next experiment should measure the *real* stack's post-load residency
   profile rather than guessing at another synthetic load order.
2. **The map-blind lever (section 5.4) looks bad here.** Tier-1's apparent
   inactive-list order-protection of R (100 -> 39.8% survival) was a
   **load-order artifact** and does not survive the interleaved load: blind
   `memory.reclaim` cuts R and L proportionally (R survival 73.9 / 66.2 / 58.7
   / 28.7% descending caps, always within ~3 points of L). Scored on total
   3-pass fault work it is worse than doing nothing at every rung — including
   +342,016 faults at `fits`, where the working set already fits and guided
   costs 61. What it does buy is speed to steady state (one pass instead of
   ~10 at marginal, roughly break-even on total work over that horizon).
   Map-guided dominates it everywhere.

Raw cells: `data/eval_results/convrepro_t1b_*_20260831.json` (commit
`3729df30`, 21 cells + logs); verbatim tool output
`data/eval_results/HOST_ANALYZE_t1b_20260831.txt`; verdict tool
`spike/convergence_repro/analyze.py` at `73ec114c`. Full bar-by-bar reading,
harness-soundness checks and defect D4:
**`spike/convergence_repro/RESULTS.md`, Tier-1b sections 8–17.**

## Addendum 2026-09-01 — publication-gate items 2–3: pre-registered, phase A in flight

Items 2–3 (native-Linux + MGLRU real-stack repro) are no longer "pending,
unstarted": **`spike/convergence_repro/PREREGISTRATION_TIER23.md`** (DRAFT,
commits `28a00215`/`0b3c7e2d`) targets the OCI demo serve box (E5.Flex
x86_64, Ubuntu 24.04 kernel 6.17.0-1018-oracle, 62 GiB, MGLRU present and
runtime-toggleable — one box runs both tiers as a toggle A/B). Harness:
`scripts/seismic_testbed/t23_convergence_ladder.py` + orchestrator (commit
`3a8f2722`; adapted from the R2 driver, which remains untouched at its
judged commits). **IMPLEMENTED, EFFICACY UNMEASURED — phase A (exploratory
calibration ladder, both arms) launched 2026-09-01 00:00 UTC**; results will
land in `data/eval_results/t23a_*.json` with verdict bars frozen only after
phase A per the pre-registration. Until then the item-2/3 status here is:
in measurement, no numbers yet.

## Addendum 2026-09-01 (b) — Tier-2/3 phase A MEASURED: the artifact's dynamic exists on native Linux; MGLRU displaces the cliff upward

Phase A (exploratory calibration, 14 cells, raw commit `29d58b89`) on the
OCI serve box (x86_64, kernel 6.17, real stack + real 40-query workload,
prefault protocol matched to R1/R2):

- **Classic LRU (item 2): the convergence transient and the fixed-window
  inversion are PRESENT.** Transient band 26–28 GB (repeat set ≈27.5 GB on
  the deployed dotvbyte index): both rungs converge to the same ~19–20 ms
  steady state through multi-pass sorts, and at the fixed pass-2 window
  the smaller cap wins — 26 GB p50 64.3 ms vs 28 GB 262.8 ms (4.1×) —
  pressure-dominated convergence with pass-1 pgscan monotone in pressure
  (0 → 1.0M → 5.2M). The dynamic the Tier-1b synthetic could not produce
  reproduces on the real stack outside WSL2.
- **MGLRU (item 3): does NOT eliminate the artifact by converging faster —
  it replaces the transient with sustained thrash.** Same box, same index,
  toggle-controlled: at 28 GB MGLRU plateaus at 44–49k faults/pass (p50
  4–5 s, never converges); at 26 GB ~160k faults/pass, p50 ~24.5 s
  (~1000× classic's 19.4 ms at the same cap). Cliff: classic < 26 GB,
  MGLRU ≈ 29–30 GB. Above 30 GB the arms are indistinguishable.

Single cells, no replicates — signals, not verdicts. Confirmatory bars
(B1–B5) are drafted in `spike/convergence_repro/PREREGISTRATION_TIER23.md`
§7 and freeze before phase B runs.

## Addendum 2026-09-01 (c) — Tier-2/3 phase B JUDGED: item 2 CONFIRMED under frozen bars (B2/B3 PASS); item 3 one cell short

Phase B (confirmatory, 16/17 pre-registered cells with replicates, valid
run 2 after the quarantined no-prefault run 1) judged against the B1–B5
bars frozen at `1a87aac3`:

- **Item 2 (native-Linux classic repro): CONFIRMED.** B2 PASS — the
  multi-pass convergence transient replicates (classic 26 GB:
  `31,642→5,072→0` and `31,523→5,100→0` majflt/pass). B3 PASS — the
  fixed-window inversion, the artifact this whole line of work is about,
  replicates on the real stack: at the pass-2 window the 26 GB cap is
  5.8×/5.6× faster than the 28 GB cap (p50 63.9/62.4 ms vs 372.6/352.3
  ms) with fewer faults, both converging to the same ~19.5 ms steady
  state. Phase-B trajectories reproduce phase A's single cells to ~1%.
- **Item 3 (MGLRU A/B): still open, one cell short.** The deadline cut
  `mglru:28:1` (phase A's plateau-thrash rung), and B1/B4/B5 all name it,
  so they stay open per the frozen rules. Recorded for the resumption:
  no phase-B rung plateaus in either arm, so the frozen cliff definition
  binds to no cell (classic's cliff sits below the 25 GB ladder floor),
  and B5's displacement can only be lower-bounded (~≥4 GB if 28 GB
  plateaus as in phase A) without a pre-registered ladder amendment.

Verdict detail + bar inputs: `spike/convergence_repro/RESULTS.md` §§18–20;
raw cells `data/eval_results/t23b_*_20260901.json`.

## Addendum 2026-09-01 (d) — phase B COMPLETE (17/17): item 3 MEASURED — MGLRU displaces the cliff upward ≥ ~4 GB and replaces the transient with sustained thrash

The final cell (`mglru:28:1`, 21:46–22:06 UTC resume window) plateaus in 5
passes (41–49k majflt/pass, p50 4.3–5.4 s), replicating phase A at the rung
where classic converges to ~21 ms in both replicates (~220× at equal cap).
Full-set judgment: **B2/B3 PASS (item 2 confirmed); B1/B5 not passed on
uncomputable-as-frozen components** (no classic rung plateaus above the
25 GB ladder floor, so the frozen cliff/displacement definitions bind to
nothing on the classic side — MGLRU's cliff measures cleanly at 28.5 GB,
displacement lower-bounded ≥ ~4 GB upward); **B4 FAIL on bar arithmetic**
(zero-ties defeat "strictly monotone"; the ≥10× active_file clause assumed
classic activation semantics) while the mechanism it targeted is directly
observed: classic re-sorts the polluted cache via refault-activation
(ws_activate ≈ ws_refault), MGLRU never re-promotes refaulting pages
(ws_activate → 0 while ws_refault holds ~4.5–5.9M/pass) so the load-time
promotion mistake persists indefinitely. Exploratory mechanism reading
with the full reclaim anatomy: `spike/convergence_repro/RESULTS.md` §22;
judgment detail §21; pre-reg s7 final tally.

## Addendum 2026-09-12 — item 1 PASSED by Tier-1d (2026-09-05); the synthetic line is SETTLED (2026-09-06)

> Supersedes the "publication gate stays closed / spin-off blocked" lines in
> the 2026-08-31 addenda above. Recorded 2026-09-12 from
> `spike/convergence_repro/RESULTS.md` §23–31 (Tier-1d, WSL2 local, both
> LRU arms available since the 2026-09-05 kernel work in `HOST_RUN.md`).

Tier-1b's negative result identified the missing variable: **access skew**.
Tier-1d (`PREREGISTRATION_TIER1D.md`, bars frozen `5f55fb32`) replaced the
uniform-random repeat with a hot-set draw (`hotset:0.20:0.80`, frac92) over
a pressured mapping and judged 2026-09-05:

- **T1d-1 PASS** — the real stack's MGLRU/classic arm asymmetry reproduces
  index-independently: steady-floor ratio **1.443** in both seeds (2027,
  8128) at cap 1.5 GiB (`hot-set < cap < |R|`) against the frozen bar
  ≥1.30. **Publication-gate item 1 is PASSED.** No seismic index, no real
  workload — skewed access over a pressured mapping is sufficient.
- **T1d-1b PASS** — mechanism shape: classic descends (floor/pass-1 ≈ 0.64,
  bar ≤0.75), MGLRU pins (≤1.1% pass-2–12 deviation, bar ≤5%).
- **T1d-3 PASS** — regime specificity: 8 GiB control ratio 1.000, 4 GiB
  band ratio 1.038; the divergence exists only where skew creates the
  third regime.
- **T1d-5 PASSED (validity)** — both strict-soundness control cells exact.

Verdicts T1d-1/1b/3 sit within the ±16% margin and cite the §4
pageReporting caveat as frozen. Characterization windows T1d-11 through
T1d-17 (2026-09-05/06, recorded-only, RESULTS.md §26–31) then closed the
remaining questions on the synthetic: the divergence is a peaked curve in
cap (§26); the **synthetic fixed-window inversion itself closed NEGATIVE in
every form the driver can express** — cap-pair, warm-residue, cold-start,
and cold-start+residue-in-window (§27, §30) — reclaim never victimizes the
re-touched population, so the residue sort costs the measured workload
nothing; readahead under a binding cap thrashes before measurement begins
(§28, 8-for-8 sheds); stock MGLRU is not rescued by `min_ttl_ms` (§29);
reclaim is layout-blind under `MADV_RANDOM` at the divergence rung (§31).
**Tier-1d line declared SETTLED 2026-09-06**; nothing queued.

Where the artifact stands across the three gate items:

| item | status | evidence |
|---|---|---|
| 1 — index-independent synthetic repro | **PASSED** (arm asymmetry); the inversion form is real-stack-only so far | RESULTS.md §23–25, §30 |
| 2 — native Linux, real stack | **CONFIRMED** (B2/B3 PASS, 5.8×/5.6× at 26-vs-28 GB) | addendum 2026-09-01 (c)/(d) |
| 3 — MGLRU arm | **MEASURED**: cliff displaced ≥ ~4 GB upward, transient replaced by sustained thrash (~220× at 28 GB); B1/B5 not-passed on uncomputable-as-frozen components, B4 FAIL on bar arithmetic | addendum 2026-09-01 (d), RESULTS.md §21–22 |

Open, non-gating: a synthetic reproduction of the *inversion* (as opposed
to the arm asymmetry) needs ingredients beyond the current driver
(plausibly the real stack's re-touched residue) and a fresh Tier-1e
pre-registration; S-realprofile stays severed behind §6 gap 3; the
MGLRU-FG RFC test (`PREREGISTRATION_T1D_FG.md`) and the access-histogram
probe (`PREREGISTRATION_T1D_PROBE.md`) are drafted, not run. The spin-off
decision (standalone public repo on item-1 PASS, recorded 2026-08-31) is
now unblocked and awaits the owner.
