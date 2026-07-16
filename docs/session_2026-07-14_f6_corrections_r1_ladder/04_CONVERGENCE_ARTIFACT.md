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
