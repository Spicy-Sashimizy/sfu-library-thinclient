# 04 · The non-monotonic convergence artifact (R1, 2026-07-14)

**Status:** ACTIVE

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
   raised majflt only +7% (550k→587k) but latency +35% (4.9→6.6 s) — that is,
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
   >
   > **ADDENDUM 2026-09-29 — MEASURED on the real stack (uncapped mechanism
   > check, served binary NOT swapped):** the fork `2c4d863` `.so` was rebuilt
   > portable (x86-64-v3) and run against the 8 served shards versus the served
   > pre-fix `.so`. After one query pass the fixed hook takes all three
   > structural slabs (1.36 GB) to Rss 0 and drops RssFile 8.24 of 8.52 GB
   > residue (0.968); the served hook drops 7.07 GB (0.789) and leaves the
   > structural slabs untouched. The 2026-07-14 "released 16.45 GB" is
   > reproduced to the byte as *advised* (not resident) forward-slab bytes —
   > at load nothing outside the prefaulted keep-set was resident, which is
   > why RssFile did not move. Record, caveats (page cache is the ceiling on
   > this 31 GB host; not the §5-check-3 capped cell) and what remains:
   > `spike/convergence_repro/PREREGISTRATION_WSL2_REHOST.md` §6 "gap 1
   > RECORD 2026-09-29"; JSON
   > `data/eval_results/wslrh_f5_gap1_verify_2026-09-29.json`.
4. On the operator question "can we trigger the forced reclaim manually to
   get the benefit without scaling the host": yes — that is F5 (map-guided,
   this repository), or map-blind equivalents documented in production elsewhere
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
   refinement.** At a fixed pass-3 window, 12 GB reads p50 21 ms versus 16 GB's
   124 ms (R1: 22 versus 135) — yet 12 GB carried MORE residual faults at that
   snapshot (26k versus 15k). The inversion is therefore carried by *where* the
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
   different pass counts (12g took 5 versus ctrl's 4, tracing-pressure-delayed), so
   a fixed index is apples-to-oranges (12g pass-3 = mid-sort 824 ms versus ctrl
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
0.157 ms versus marginal p95 = 0.006 ms, an inversion ratio of **0.04x** against a
predicted 2–20x: the *smaller*-deficit rung converges faster, not slower.
Marginal and boundary majflt trajectories are self-similar, scaled by their
initial deficits (ratio 1.92 / 1.86 / 2.04 / 1.92 over passes 1–4, versus a load
deficit ratio of 1.98). Pressure-scaled aging is real but second-order:
boundary's per-pass geometric decay is 0.582 versus marginal's 0.646 (~10% faster,
enough to reach zero faults at pass 8 versus pass 10 with twice the deficit — not
enough to invert a 2x head start inside three passes). **Verdict: on this WSL2
classic-LRU host, with a naive two-population interleaved load and
uniform-random repeat, the fixed-window convergence outcome is
deficit-dominated.** Bars 1b/2b/3b FAIL, 4b/5 PASS, OVERALL FAIL. The
publication gate stays closed and the spin-off stays blocked.

The conclusion is **robust to the metric** (on `clat` mean, pass-3 boundary is
still 1.98x slower than marginal), but two of the three failing bars are not
about the hypothesis at all — Tier-1b's bars moved p50 -> p95 to see faults,
and p95 turns out to be a *threshold detector*: a percentile p_X reads fault
latency only while the fault fraction exceeds (100-X)%, so at 1,310,720 operations per
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
  the smaller cap wins — 26 GB p50 64.3 ms versus 28 GB 262.8 ms (4.1×) —
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
  5.8×/5.6× faster than the 28 GB cap (p50 63.9/62.4 ms versus 372.6/352.3
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
decision (standalone public repository on item-1 PASS, recorded 2026-08-31) is
now unblocked and awaits the owner.

> **CORRECTION 2026-09-25 — two clauses of the paragraph above were already
> false on the day it was written.** The paragraph was drafted against the
> 2026-09-06 state; the probe ran later the same day (2026-09-12) and the
> paragraph was not re-read before it shipped. Corrected against
> `spike/convergence_repro/RESULTS.md` §32 and
> `PREREGISTRATION_T1D_PROBE.md` §7/§8:
>
> - **"the access-histogram probe … drafted, not run" is WRONG.** The probe's
>   method, query mix (N=1,000 draws, seed 20260912) and output schema were
>   **FROZEN 2026-09-12** (§7) and the probe **RAN 2026-09-12** (§8; raw
>   `data/eval_results/t1dprobe_*_20260912.*`, commit `14ceea4d`; readouts
>   recorded in commit `33f016a2`). Determinism bar PASS — two 1,000-draw
>   replays byte-identical. Readouts: hot-80 = **10.4%** of forward pages /
>   **3.21 GB**; mass at synthetic h = 0.05/0.10/0.20 → 0.589/0.789/0.961, so
>   the real index's skew is ≈ **`hotset:0.10:0.80`** on the forward-page
>   denominator (a *harder* skew than the judged `hotset:0.20:0.80` cells
>   drew); hot-80 clustering 446,508 extents, run p50 1 / p90 3 / max 266 —
>   only 1.57× tighter than random placement, so the T1d-12 `hotsetc` E=8 arm
>   over-models contiguity. The probe was re-scoped to a **local counting**
>   measurement (`PREREGISTRATION_T1D_PROBE.md` header, 2026-09-06), which is
>   why it never needed the OCI box and why N7 never bound it.
> - **"S-realprofile stays severed behind §6 gap 3" is WRONG.**
>   `PREREGISTRATION_TIER1D.md` §6 **gap 3 is CLOSED** (RESULTS.md §32
>   headline). S-realprofile (§3.6) remains severed, but now only on the two
>   *driver* prerequisites named in `PREREGISTRATION_T1D_PROBE.md` §8.3 — the
>   ranking-import mode for `t1d_cell.py` and the initial-residency profile —
>   neither of which is host-gated. No verdict moved: §23's Tier-1d verdicts
>   and the gate table above stand exactly as recorded.
> - **Still accurate as written:** the MGLRU-FG RFC test
>   (`PREREGISTRATION_T1D_FG.md`) is DRAFT and un-run, and the Tier-1e
>   inversion pre-registration did not exist. Tier-1e is drafted
>   2026-09-25 as `spike/convergence_repro/PREREGISTRATION_TIER1E.md`
>   (DRAFT, un-frozen, no cell may run).

## Figure set (2026-09-13) — the write-up's figures, built from committed cells

https://claude.ai/code/artifact/1b60d178-4b25-440c-b1c9-9a12bdfdc898 — seven
figures, each mark a field of a recorded result file (no re-measurement):
(1) R1 ladder per-pass p50 + majflt by cap, the observation; (2) R2 fine
ladder, pass-3 p50 versus converged p50 by cap (non-monotone versus monotone);
(3) R3 between-pass cachestat residency + active_file, 12 versus 16 GB;
(4) Tier-2/3 real stack, per-pass p50 and converged state by cap, classic versus
MGLRU (the cliff displacement); (5) Tier-2/3 reclaim anatomy at 28 GB,
workingset activate versus refault; (6) Tier-1d hot-set residency + majflt per
pass, both arms, both seeds, plus the 8 GiB control; (7) Tier-1d
characterization, floor ratio versus h and versus cap. Companion: the 2026-09-12
access-histogram probe chart (§ above). Source and data:
`spike/convergence_repro/figures/` (`extract.py` → `figures_data.json`,
`figures_template.html` + `build.py`); rebuild after any cited cell changes.
Not yet drawable from committed data: the small-machine 16 GB
converge/thrash split (run-4 timeouts left no JSON) and the F5
residue-eviction lever on the real stack (unmeasured).

## Regime map definitions (2026-09-13) — pinned before figure 8 was drawn

The map plots cap ÷ measured hot set (log axis) with one lane per host. Its
three regimes are defined by two measured quantities per host, recorded here
so the drawing is auditable:

- **Lower boundary = hot set + anon.** Below it the pages the workload
  re-touches do not fit; no reclaim policy converges (capacity arithmetic).
- **Upper boundary = post-pass-1 footprint** (both populations resident +
  anon). Above it nothing is evicted, so nothing sorts; every cap looks alike.
- **The band between** is where the one-time cache sort happens under
  pressure, at a pressure-proportional speed — the artifact regime. MGLRU's
  cliff is a fourth line inside the band, on that arm only.

| host | hot set | anon | lower | footprint (upper) | evidence |
|---|---|---|---|---|---|
| WSL2 6.18 classic (R1/R2/R3, 2026-07-14/15) | **10.1 GB** | 1.2 GB | 11.3 GB | **19.4 GB** (bracketed: 17 GB sorts, 24 GB fits, nothing between) | R3 12 GB cell drained to 10.13 GB; R2 12 GB converged rssfile 9.94 GB; R2 24 GB after pass 1: cgroup file 18.17 GB + anon 1.2 GB; R2 11 GB converges (18 ms), 10 GB plateaus (1.42 s) — the lower boundary lands where the arithmetic says |
| OCI E5 62 GiB, 6.17 (Tier-2/3, 2026-09-01) | **13.76 GB** | 1.0 GB | 14.8 GB (*predicted*; classic ladder floor 25 GB) | **29.1 GB** (measured: 30 GB zero scan, 29 GB barely trims) | RESULTS.md §22; smallmachine PREREGISTRATION §1; MGLRU cliff **28.5 GB** at 1 GB resolution |
| Synthetic Tier-1d (WSL2, both arms, 2026-09-05/06) | **1.0 GiB** (h=0.20 of R=5 GiB) | ~0 | 1.0 GiB | **6.75 GiB** (R + L) | by construction; cap sweep 0.75/1.5/2.5/4/8 GiB |

Point outcome classes (per cell): *fits* (near-zero within 3 passes, no
visible transient), *transient* (near-zero after a visible sort in the
window), *plateau* (never near-zero), and for the Tier-1d sweep *divergent*
(arm ratio > 1.16) / *pressured* (hot set does not fit, or loose cap). Cells
without a result JSON (small-machine run-4 timeouts at 16 GB) appear as an
annotation, never as a point. The classic lower boundary on the OCI host is
drawn dashed as a prediction because the ladder never went below 25 GB.

**Figure 8 DRAWN 2026-09-13** (commit `28891f97`, same figure-set URL as
above, figure 8 card): 60 cells placed — WSL2 21 (4 fits / 12 transient /
5 plateau), OCI 29 (23 / 3 / 3), Tier-1d 10 (2 fits / 4 divergent /
4 pressured). The classifier, told nothing about where the artifact is,
isolates it: the only OCI transients are the three classic 28 GB cells
(pass-2 p50 13–17.6× the floor) and the only OCI plateaus are MGLRU 26 and
28 GB; on WSL2 every R2 near-zero cell from 11 to 17 GB is a transient
(4–5 passes to converge) and only 24 GB is a clean fit; the 6–10 GB
plateaus all sit below the 11.3 GB lower boundary, the 11 GB cell just
above it. Rule constants: near-zero 2,500 majflt/pass, visible sort = a
pass ≥ 2 above 5× the converged p50, Tier-1d divergence = ratio > 1.16
(`figures/extract.py` `FIG8_HOSTS` + `classify()`).

## Addendum 2026-09-25 — host change: the OCI box is gone; what that closes and what re-hosts

**The fact.** As of **2026-09-25** the operator has **no access to any cloud
host**. The **OCI E5, 62 GiB, kernel 6.17.0-1018-oracle, no swap** box that
produced every Tier-2/3 and small-machine cell
(`spike/convergence_repro/PREREGISTRATION_TIER23.md`, RESULTS.md §§18–22;
`spike/archive/smallmachine_levers/PREREGISTRATION.md` phases A′/A″) is **permanently
gone**. The only host is this WSL2 machine — the same one that ran R1/R2/R3
and all of Tier-1d.

| | OCI E5 (gone 2026-09-25) | this WSL2 host (measured 2026-09-25) |
|---|---|---|
| RAM | 62 GiB | **31 GB total**, 26 GB available at idle (~5 GB used before any cell) |
| swap | none | 16 GB |
| cores | — | 16 |
| kernel | 6.17.0-1018-oracle | `6.18.33.2-microsoft-standard-WSL2+` (custom build) |
| MGLRU | present | `/sys/kernel/mm/lru_gen/enabled` = **`0x0007`**, both arms toggleable |
| cgroup | v2 | v2 |

Note the second host change: RESULTS.md §31 recorded the `.wslconfig` revert
from the 56 GB Tier-1d experiment profile to the everyday block as *pending*.
It has happened — **31 GB is the current boot**, not 56 GB. Tier-1d's judged
cells (caps ≤ 8 GiB) are unaffected; nothing below is argued from 56 GB.

### The arithmetic that decides every item

Three independent facts, each sufficient on its own, and all three drawn from
the regime-map constants pinned in the section above:

1. **The OCI upper boundary does not fit in this host's total RAM.** The
   two-population footprint on the OCI stack is **29.1 GB** (28.1 GB file +
   1.0 GB anon, RESULTS.md §22) = **93.9% of this host's 31 GB total**. An
   "everything fits" control needs a cap ≥ 29–30 GB; the small-machine
   big-RAM regression control (sml §4, bar S4) needs **34 GB**, which is
   **3 GB above this host's entire RAM**. Neither control can exist here, and
   without the upper boundary the band has no top.
2. **A 28 GB cap is not meaningfully reachable on a 31 GB host.** The missing
   boundary cells sit at cap 28 GB. 31 − 28 = **3 GB** left for the WSL2
   kernel, init, the development container, the orchestrator and every page the cap
   does not own; measured idle usage before any cell is **~5 GB**, so
   31 − 5 = **26 GB < 28 GB** — the cap is looser than the RAM actually
   available to fill it. A cgroup limit that the host cannot make bind does
   not measure reclaim policy; it measures host RAM. Same for AMEND1's top
   rungs 24/22 GB once the ~5 GB floor is charged (26 GB usable).
3. **The decisive one: the same cap number is not the same regime on this
   host.** This host's real stack (R1/R2/R3 constants, regime-map table
   above) has **hot set 10.1 GB + 1.2 GB anon = 11.3 GB lower boundary** and
   **19.4 GB footprint (upper boundary)**. Cap 28 GB is **8.6 GB above this
   host's upper boundary** — squarely in the "nothing is evicted, so nothing
   sorts, every cap looks alike" regime. The **entire OCI ladder, 25–30 GB,
   lies above this host's footprint.** There is **no cap on this host at
   which the OCI cells' question can be posed at all**, regardless of how
   much RAM the machine had. (The hot sets themselves differ 13.76 / 10.1 =
   **1.36×** on the same 150M manifest; the record does not establish whether
   that is host, codec or serving configuration, which is a second independent
   reason a same-numbered cap here would not be a replication.)

**Consequence, stated once:** every OCI-derived cell is **CLOSED-UNRUNNABLE**
— same-host replication is impossible and same-cap re-hosting would measure a
different regime. Everything whose question lives in *this* host's own band
(11.3–19.4 GB) or in the synthetic (caps ≤ 8 GiB) is **RE-HOSTABLE**.

### Item-by-item classification (2026-09-25)

| open item | where it lived | classification | one-line reason |
|---|---|---|---|
| `t23c_mglru_cap28g_rep2` — replicate of the 28 GB MGLRU plateau boundary cell (AMEND1 §1) | OCI | **CLOSED-UNRUNNABLE** | cap 28 GB is above this host's 19.4 GB footprint and above its 26 GB usable RAM; the rung cannot be made to bind or to sit in the band |
| AMEND1 classic descent 24/22/20/18/16 GB + confirmatory bracket → **B1x/B5x** | OCI | **CLOSED-UNRUNNABLE** | the descent exists to bracket a classic plateau below 25 GB on a stack whose floor is 14.8 GB; on this host every one of those rungs is a *different* regime against an 11.3 GB floor |
| **B1 / B5** (not passed on uncomputable components) and **B4** (FAIL on bar arithmetic) | OCI | **CLOSED-UNRUNNABLE — now FINAL AS RECORDED** | the only path to tightening them was AMEND1; with that closed, the 2026-09-01 verdicts are the permanent record, not an interim one |
| `PREREGISTRATION_TIER23_AMEND1.md` (DRAFT, **never frozen**) | OCI | **CLOSED-UNRUNNABLE** | it defines only `t23c_*` cells on the OCI protocol; it can never be frozen, so it is retired as a draft, not as a failed test |
| `spike/archive/smallmachine_levers/PREREGISTRATION.md` phase B, bars **S1–S5** (DRAFT, never frozen; already unfreezable as designed per its phase-A′ synthesis) | OCI | **CLOSED-UNRUNNABLE** | rungs 14/16/18/20 GB and the 34 GB S4 control are derived from OCI constants; S4's control alone exceeds this host's total RAM |
| **Figure: small-machine 16 GB converge/thrash split** (not drawable — run-4 cells timed out leaving no JSON) | OCI | **CLOSED-UNRUNNABLE as a figure** | the cells left no result JSON and the host that would back-fill them is gone; nothing can be recovered for the OCI lane of figure 8 |
| The *question* behind that figure — is there a ragged-edge rung just above the hot set where the real stack converges sometimes and thrashes sometimes, and what is the split? | re-posed | **RE-HOSTABLE** | this host has its own ragged edge already bracketed (R2: 11 GB converges at 18 ms, 10 GB plateaus at 1.42 s); rungs 10–13 GB bind hard under 31 GB. **Re-posed, not replicated** — a new n>2 split measurement on this host's constants |
| **Figure: F5 residue-eviction lever on the real stack** (unmeasured) | never ran on OCI | **RE-HOSTABLE** | F5's scope fix (fork `2c4d863`) and the index are both on this host, and the lever's target band is 11.3–19.4 GB — the only blocker is that no `.so` carrying the fix has been rebuilt and served |
| **S-realprofile** (`PREREGISTRATION_TIER1D.md` §3.6) | local | **RE-HOSTABLE** | never host-gated after the probe went local (§6 gap 3 CLOSED 2026-09-12); blocked only on two driver prerequisites (ranking-import mode, initial-residency profile), `PREREGISTRATION_T1D_PROBE.md` §8.3 |
| **T1d-FG** — the MGLRU-FG RFC test (`PREREGISTRATION_T1D_FG.md`, DRAFT) | local | **UNAFFECTED / RE-HOSTABLE** | WSL2 kernel work with caps ≤ 8 GiB; the host loss touches nothing in it. Still DRAFT, still un-run |
| **Tier-1e** — synthetic inversion reproduction (drafted 2026-09-25) | local | **RE-HOSTABLE by construction** | synthetic, `t1d_cell.py`, caps ≤ 8 GiB, R=5 GiB + L=1.75 GiB — fits this host with ~22 GB to spare |

New DRAFT pre-registrations written 2026-09-25 for the re-hostable work (both
**DRAFT — awaiting the operator's freeze; no cell may run**):
`spike/convergence_repro/PREREGISTRATION_WSL2_REHOST.md` (the ragged-edge
split + F5 on the real stack, on this host's constants) and
`spike/convergence_repro/PREREGISTRATION_TIER1E.md` (the synthetic inversion).

### Publication gate — current status of all three items + the spin-off (2026-09-25)

Supersedes the gate table in the 2026-09-12 addendum above for *status*; the
evidence citations there stand unchanged.

| item | status 2026-09-25 | can it still move? | evidence |
|---|---|---|---|
| 1 — index-independent synthetic repro | **PASSED** (arm asymmetry, steady-floor ratio 1.443 in both seeds, bar ≥1.30). The *inversion* form remains real-stack-only. | **Yes** — synthetic, fully re-runnable on this host; Tier-1e is drafted for the inversion form | RESULTS.md §23–25, §30 |
| 2 — native Linux, real stack | **CONFIRMED** (B2/B3 PASS, 5.8×/5.6× at 26-vs-28 GB) | **No new OCI cell is possible.** The verdict stands as a closed, judged record; a reader cannot re-run it | addendum 2026-09-01 (c)/(d) |
| 3 — MGLRU arm | **MEASURED and now FINAL AS RECORDED**: cliff displaced ≥ ~4 GB upward, transient replaced by sustained thrash (~220× at 28 GB); **B1/B5 not-passed on uncomputable-as-frozen components, B4 FAIL on bar arithmetic — permanently, because AMEND1 is CLOSED-UNRUNNABLE** | **No** | addendum 2026-09-01 (d), RESULTS.md §21–22; AMEND1 retired |
| spin-off decision (standalone public repository on item-1 PASS, recorded 2026-08-31) | **Still unblocked; still awaits the owner** — but its honest shape changed on 2026-09-25 | — | this addendum |

**What the host loss does to the spin-off.** The synthetic tier (item 1) is
the part a reader can reproduce: `t1d_cell.py`, frozen bars, fresh seeds,
commodity hardware, ≤8 GiB caps. The real-stack tiers (items 2–3) become
**archival evidence** — measured, judged, fully recorded, and not reproducible
by anyone, including us. Any write-up must say that in those words rather than
implying the real-stack cells are re-runnable, and must not describe B1/B4/B5
as "to be tightened": they are final. The one thing that *can* still be added
on the real stack is on **this** host, in **its** band (11.3–19.4 GB), which
is a different machine's version of the same phenomenon and must be labelled
as such.
