# Tier-1b: convergence-artifact synthetic repro, second attempt — pre-registration

**Written 2026-08-31, BEFORE any Tier-1b code was built or any cell run**
(repo write-before-run convention). Parents: `PREREGISTRATION.md` (Tier-1 —
**FAILED 2026-08-31**, verdict in `RESULTS.md`), `PREREGISTRATION_EARLYSORT.md`
(ES arm — ES-2 NO DATA on the same run), and
`docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`
(the observation + the 2026-08-31 addendum). Purpose unchanged: publication-gate
item 1 — prove the fixed-window convergence inversion is a kernel-reclaim
property, not a search-engine property. The spin-off stays blocked until this
passes.

## Why Tier-1 failed, and what Tier-1b changes

Tier-1's protocol loaded **L then R sequentially**, so R was always the
most-recently-loaded population: under any cap > R, load-time evictions fell
on L and pass 1 began with R at 100% residency — the load itself performed
the "sort" (measured: marginal post-load R=100.0%, L=93.4%; majflt 0/0/0).
Additionally, the marginal cap (7g = 1.04×D) sat **above** total file demand
D, so nothing was ever evicted there at all. Three structural fixes follow.
Everything not listed here (files, sizes, R/L ratio, fio job, seeds,
eviction protocol, per-pass metrics, cgroup counters, swap-forbidden rule,
docker sibling-container method, SCALE=1 host-side execution) is inherited
from `PREREGISTRATION.md` unchanged.

### Change 1 — interleaved load (the fix for the structural flaw)

The load phase becomes a **single sweep that interleaves L and R chunks**:
both files read in 64-MiB chunks, merged into one deterministic
proportional round-robin schedule (Bresenham-style, so L's 28 chunks are
spread evenly among R's 80 — mimicking the real index load, where
residue pages and future-repeat-set pages are read intermixed in one
sequential pass). Chunk size 64 MiB is a **declared constant, not a tuning
knob**. Consequence: under any cap < D, load-time evictions hit the sweep
head — a proportional *mix* of L and R — so pass 1 starts with R partially
non-resident and a convergence transient exists. The cell JSON records
`load_order: "interleaved"` plus post-load residency of both files.

### Change 2 — rungs repositioned below D (marginal must actually evict)

D ≈ 6.75 GiB unchanged. New ladder (tuned marginal 6.64g from Tier-1 is
retired — it was calibrated against the broken load order):

| rung | cap | deficit D−cap | rationale |
|---|---|---|---|
| fits | 10g | none (1.48×D) | control; bar 5 unchanged |
| marginal | 6.25g | 0.5 GiB (0.93×D) | small deficit, LOW pressure — the lazy-sort cell |
| boundary | 5.75g | 1.0 GiB (1.15×R) | larger deficit, HIGHER pressure — the fast-sort winner |
| thrash | 3.75g | 3.0 GiB (0.75×R) | below-R cliff |
| deep | 2.75g | 4.0 GiB (0.55×R) | deep cliff |

Note the artifact's shape under this design: marginal starts with the
*smaller* deficit yet must converge *slower* than boundary for bar 1' to
hold — recovery rate, not deficit size, is what pressure-scaled aging
governs. That is precisely the claim under test; if convergence speed turns
out to be deficit-dominated instead, that is a FAIL and a finding, recorded.

**Calibration gate (pre-authorized, exhaustive list):** marginal may move
within [6.0g, 6.5g], at most 3 steps; if the marginal transient is still
< 2 passes at the gate's end, L may be grown once to 2.5 GiB (D → 7.5 GiB;
caps re-derived from the ratios above, all cells re-run fresh). Every tuned
value is reported as tuned; pre-tune cells go to
`data/eval_results/tuning_history/`. Nothing else may be tuned.

### Change 3 — bars re-specified on tail metrics (Tier-1 lesson: the median can't see faults)

Tier-1 showed the synthetic's p50 is page-cache-hit-dominated even while
thrashing (thrash p50 was 3.4× converged with 600k faults/pass; faults live
in the tail). All latency comparisons therefore move from clat **p50 → p95**.
Bars, judged by `analyze.py` on SCALE=1 capped cells only:

1. **Bar 1b — inversion.** Precondition (the thing Tier-1 lacked): marginal
   pass-1 majflt > 0. Then at the fixed pass-3 window: boundary clat p95 <
   marginal clat p95, while marginal's majflt is still falling
   (pass3 < pass2 < pass1 and pass3 > 1% of pass1).
2. **Bar 2b — same destination, not Belady.** Marginal and boundary both
   reach steady state in ≤ 12 passes with steady p95 within ±10% of each
   other. "Converged" uses the FIXED rule (see D3 below): plateau ±10%
   across 2 passes **and** final-pass majflt < 1% of pass-1 (or = 0).
3. **Bar 3b — cliff.** Thrash and deep: pass-3 majflt ≥ 0.8× pass-2
   (flat-and-large) and steady p95 ≥ 10× the converged reference p95
   (mean of converged marginal+boundary); neither may satisfy the
   convergence rule; every rung above boundary converges.
4. **Bar 4b — pressure-scaled aging, with a noise floor.** Pass-1 cgroup
   pgscan monotone non-decreasing fits → deep, where values < 4096 pages
   (16 MiB) are clamped to a single "≈0" tier before comparison (Tier-1
   failed this bar on a 512-page wiggle between two zero-pressure rungs).
5. **Bar 5 — sort-not-needed datum.** Unchanged: at fits, active_file
   < 0.25×R through all passes (Tier-1 passed at 0.000×R).

**PASS = all five.** Any FAIL with a sound harness is recorded, not tuned
(beyond the Change-2 gate). PASS additionally requires the validity
checklist inherited from HOST_RUN.md: caps enforced, swap_confounded=false
everywhere, quiet box, no MECHANICS CHECK label.

### Predictions (*est.*, write-before-run)

Marginal pass-1: ~0.37 GiB of R missing (~95k majflt). Marginal converges
in 3–7 passes, boundary in 2–3; pass-3 p95 inversion ratio 2–20×. Blind
ES-5 R-survival (below) degrades vs Tier-1's — low confidence.

## Early-sort arm re-run (ES bars finally judgeable)

The full ES matrix from `PREREGISTRATION_EARLYSORT.md` re-runs against the
Tier-1b baselines, bars ES-1..ES-4 unchanged in structure but with the same
p50 → **p95** substitution and the fixed convergence rule; ES-2 (transient
eliminated ≥ 80%) becomes judgeable because a baseline transient now exists.
ES-5 stays exploratory — and gains significance: under interleaved load the
inactive-list order no longer cleanly favors L, so blind
`memory.reclaim`'s R-survival here is the honest synthetic predictor for
the real-stack map-blind lever (§5.4 of the parent doc). Tier-1's ES-5
(R-survival 100→39.8% descending caps, blind cost ~8 ms ≈ guided ~5 ms)
is the order-protected upper bound to compare against.

## Exploratory order arm (recorded, NOT judged)

One extra cell, marginal rung, fixed3, load order **R then L** — completing
the load-order triptych (Tier-1's L→R = pre-sorted; interleaved = this
design; R→L = residue-most-recent). Informational only: it measures how
much the artifact's visibility depends on load order, which is itself now a
documented finding (RESULTS.md §2).

## Harness fixes shipped with Tier-1b (defects D1–D3, RESULTS.md §6)

- **D1:** smoke/mechanics cells get a distinct tag that the documented
  analyze glob excludes by construction; HOST_RUN.md's acceptance criterion
  updated to match.
- **D2:** `run_ladder.sh --build-only` performs image **and** volume
  laydown, as its label claims.
- **D3:** the convergence rule requires final majflt < 1% of pass-1 in
  addition to the plateau (a thrashing plateau is not "converged").
  Verified on Tier-1 data: flips no Tier-1 bar verdict.
- HOST_RUN.md gains the Windows host gotchas (python3 Store stub, `/c/`
  path translation, MSYS path mangling vs build context).

These are harness-soundness fixes specified before the run; none touches a
judged Tier-1 artifact retroactively.

## Environment, execution, deliverables

Same WSL2 host and constraints as Tier-1 (6.18.33.2, classic LRU /
`lru_gen` absent, cgroup v2, 56 GB pool, quiet box; validates the
WSL2/classic-LRU regime only — native-Linux + MGLRU remain gate items 2–3).
Build + local smoke in the dev container; SCALE=1 capped ladder host-side
per updated HOST_RUN.md. Results:
`data/eval_results/convrepro_t1b_*_<date>.json` (+ `.log`), verdicts
appended to `RESULTS.md` with dates and file paths per the efficacy rule.
Build may be delegated to a subagent; review, run coordination, verdicts,
and docs by the session lead.

## Out of scope (pre-registered separately when picked up)

The **real-stack** §5.3/§5.4 test — re-running the F5 guided cell with the
hook-scope bug fixed, plus a blind `memory.reclaim` arm on the serving
container at the 16 GB marginal band — is NOT part of Tier-1b. It gets its
own pre-registration; Tier-1b's interleaved ES-5 datum is its design input.
