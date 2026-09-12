# Convergence-repro Tier-1 + early-sort arm — RESULTS (2026-08-31 host run)

**Verdict recorded 2026-08-31 by the dev-container session lead, from the raw
cells in commit `6ee8a982` (SCALE=1, caps enforced, swap_confounded=false on
every cell, WSL2 6.18.33.2 classic-LRU / `lru_gen` absent, cgroup v2).**
Judged strictly against `PREREGISTRATION.md` and
`PREREGISTRATION_EARLYSORT.md`; the calibration gate was used and exhausted
(see §3). Analyze reproduced in-container 2026-08-31 with an explicit
file list (see defect D1):

```
ls data/eval_results/convrepro_*_20260831.json | grep -v smoke \
  | xargs .venv/bin/python3 spike/convergence_repro/analyze.py
```

## 1. Headline verdicts

- **Tier-1 (PREREGISTRATION.md): OVERALL FAIL** — bars 1, 3, 4 FAIL; 2, 5
  PASS. Publication-gate item 1 (index-independent synthetic repro) is **not
  passed**; the standalone-repo spin-off stays blocked pending Tier-1b (§5).
- **Early-sort arm (PREREGISTRATION_EARLYSORT.md): OVERALL FAIL** — ES-1,
  ES-3, ES-4 PASS; ES-2 NO DATA (no baseline transient existed to remove).
  This does **not** refute §5.3: with a zero-fault baseline the arm never got
  to test the claim. ES-5 (exploratory) produced the run's best data (§4).

This is a **negative result recorded, not a tuned-away one** — exactly the
discrepancy class PREREGISTRATION.md's validation section pre-declared: "if
the synthetic FAILS while the real stack reproduces, that discrepancy is
itself a finding (access-structure dependence) and must be recorded."

## 2. The mechanism (why the synthetic cannot show the artifact)

The cell protocol loads **L then R sequentially, once**. R is therefore the
most-recently-loaded population, so for **any cap > R (5 GiB)** the kernel's
eviction victims during R's load come from L, and pass 1 starts with R at
100% residency — the load itself performs the "sort." Measured (marginal cell
log, cap 6.64g): after load **R=100.0000% resident, L=93.4152%** (cap is only
~0.11 GiB below D, so L barely shrinks — but R is untouched); passes 1–3
majflt = 0/0/0. Same zero-fault start at fits and boundary. Below the cliff
(thrash 3.75g, deep 2.75g) R cannot fit at all → immediate hard thrash
(~0.6M and ~1.3M majflt/pass, flat).

Result: **three zero-fault rungs, two hard-thrash rungs, no intermediate
converging regime** — there is no lazy-sort transient to invert. The real
system's artifact requires pass 1 to begin with R partially non-resident
(a convergence trajectory to truncate); the synthetic's load order
structurally prevents that on this classic-LRU host. Refined finding: the
artifact is **load-order / access-structure dependent**, not reproducible by
naive two-population sequential load + uniform-random repeat.

## 3. Calibration gate (tuned values, reported as tuned)

Pre-authorized knob (PREREGISTRATION.md): move the marginal cap toward
1.00×D. Steps taken on-host: **7.00g → 6.74g → 6.64g** (last pre-authorized
value), each flat at majflt=0 across all passes — as §2 predicts, since any
cap > R leaves R fully resident. **Marginal ends TUNED at 6.64g** (committed
in `run_ladder.sh` RUNG_GIB); pre-tune cells preserved in
`data/eval_results/tuning_history/convrepro_marginal_fixed3_cap{7.00,6.74}g_20260831.json`.
The gate is exhausted: no pre-authorized tuning can produce a transient, per
the mechanism.

## 4. Bar-by-bar notes (session-lead reading)

Tier-1:
- **Bar 1 FAIL — the substantive failure.** No transient exists: marginal
  majflt 0→0→0; pass-3 "inversion ratio" 0.87× is noise between two
  zero-fault cells.
- **Bar 2 PASS — vacuous.** Both rungs "converge" instantly at zero; spread
  9.5% is p50 noise at ~0.3 µs (all cache hits).
- **Bar 3 FAIL — partly bar-design.** Thrash flat-and-large held (p3/p2 =
  1.15) but steady p50 = 3.4× converged (bar ≥10×): at 0.75×R most reads are
  still page-cache hits, so the **median** barely moves — faults live in the
  tail. The ≥10×-p50 bar transplanted the real system's fault-dominated-p50
  assumption; deep passed it at 536×.
- **Bar 4 FAIL — ordering noise at zero pressure.** Pass-1 pgscan: fits=0,
  marginal=2,048, boundary=1,536, thrash=576,512, deep=999,328. The macro
  trend is monotone; the strict bar failed on a 512-page wiggle between two
  effectively-pressure-free rungs.
- **Bar 5 PASS — genuinely clean.** active_file = 1.1 MiB (0.000×R) through
  all fits passes: the 24 GB / 0.2 GB analogue reproduced exactly.

Early-sort: ES-1/ES-3 pass but are vacuous against a zero-fault baseline;
ES-4 held (guided changed nothing at fits, did not rescue thrash). **ES-5
(recorded, not judged) is the run's real datum:** first-ever exercise of the
blind arm (`memory.reclaim` under `--privileged`, all writes clean —
requested 1792 MiB, freed 1791–1793 MiB at every rung). Post-reclaim
residency shows inactive-list ORDER protecting the repeat set, degrading
with cap slack: R survival **100% (fits) → 97.7% (marginal) → 79.9%
(boundary) → 39.8% (thrash)**, L→0% at every rung. Cost ledger overturned
one prediction: blind cost **~8 ms**, not "far larger" than guided's ~5 ms
(BUILD_NOTES.md cost-asymmetry note) — at these sizes both are negligible.

## 5. Next step (requires fresh pre-registration — Tier-1b)

The fix is a load protocol that leaves R cold or partially resident at
pass 1 — e.g. load **R first, then L** (L's load evicts the head of R), or
interleave R/L loads to mimic the real load's intermixing. That is a harness
redesign, **outside** the pre-authorized tuning knob, so it must be
pre-registered as Tier-1b before any cell runs; bars 3 (tail metric, not
p50) and 4 (magnitude-weighted monotonicity) should be re-specified there.
Publication-gate items 2–3 (native Linux, MGLRU) unchanged, still pending.
**Tier-1b pre-registration drafted 2026-08-31: `PREREGISTRATION_TIER1B.md`**
(interleaved load, rungs repositioned below D, p95 bars, ES arm re-run,
defect fixes D1–D3).

## 6. Harness defects found on this run (record; fix in Tier-1b, not retroactively)

- **D1** — `HOST_RUN.md` analyze glob cannot meet its own acceptance
  criterion: committed smoke files share the `20260831` date tag, so the
  documented glob pulls MECHANICS-CHECK cells into the bar run. Worked
  around with an explicit file list (§ top). Fix: exclude `*smoke*` in the
  glob, or date-tag smoke cells distinctly.
- **D2** — `run_ladder.sh --build-only` exits before the volume laydown
  despite its "image + volume" label.
- **D3** — the plateau convergence rule marks a *thrashing* plateau
  converged: deep's `converged=True` is ±10%-plateau firing at ~1.31M
  majflt/pass, not a steady state. Fix: `converged` should also require
  final majflt < 1% of pass-1. Verified: applying that rule flips **no** bar
  verdict on this dataset (bars 2/3 reference marginal+boundary only).
- **Host gotchas (Windows, solved on-run, keep for future host runs):**
  `python3` Windows-Store stub shadowing real python; `/c/`-style path
  translation; MSYS path mangling vs the docker build context.

## 7. Result files

Raw cells (committed `6ee8a982`): `data/eval_results/convrepro_*_20260831.json`
(20 non-smoke cells: 5 rungs × {fixed3, converge-where-run} baseline + 4
rungs × {guided, blind} ES fixed3 + guided converge at marginal/boundary).
Cell logs: same paths + `.json.log`. Pre-tune marginal cells:
`data/eval_results/tuning_history/`. Verdict tool:
`spike/convergence_repro/analyze.py` **as of commit `571069b4`** (this file
records its 2026-08-31 output). Note added 2026-08-31, same day: analyze.py
was subsequently re-specified for Tier-1b (commit `73ec114c` — p95 bars,
D3 convergence rule) and no longer reproduces the frozen Tier-1 verdicts
above by design; to re-reproduce them, check out the tool at `571069b4`
(BUILD_NOTES §10.6 records the divergence explicitly). Smoke/mechanics
cells (`*_smoke_nocap_*`, `convrepro_mech_*`) are NOT bar evidence.

---
---

# Tier-1b (2026-08-31 host run) — RESULTS

> **This part supersedes the Tier-1 verdicts above as the current state of
> publication-gate item 1.** Tier-1 (§1–§7) is retained unchanged as the
> record of the failed first protocol; its verdicts are still reproducible
> only with `analyze.py` at commit `571069b4`.

**Verdict recorded 2026-08-31 by the dev-container session lead, from the raw
cells in commit `3729df30`** (21 cells, SCALE=1, caps enforced, WSL2
6.18.33.2 classic-LRU / `lru_gen` absent, cgroup v2). Judged strictly against
`PREREGISTRATION_TIER1B.md` (bars 1b–4b + unchanged bar 5) and
`PREREGISTRATION_EARLYSORT.md` (ES-1..ES-5, now on p95). Cells produced by a
host session per `HOST_RUN.md`; verdicts written here, not there.

## 8. Headline verdicts

- **Tier-1b: OVERALL FAIL** — bars 1b, 2b, 3b FAIL; 4b, 5 PASS.
  Publication-gate item 1 is **not passed**; the standalone-repo spin-off
  stays blocked.
- **Early-sort arm: OVERALL FAIL** — ES-1 NO DATA, ES-2 NO DATA, ES-3 FAIL,
  ES-4 PASS.
- **The calibration gate was NOT used.** The frozen 6.25g default produced
  the required precondition on the first try (marginal pass-1 majflt 159,641,
  falling 159,641 → 113,034 → 61,130, post-load R = 92.34%). Zero tuning
  steps consumed, `RUNG_GIB` untouched, nothing added to `tuning_history/`.
  Every rung below `fits` had post-load R strictly < 100% (92.34 / 84.84 /
  54.96 / 40.00) — **Tier-1's failure mode did not return.** The Change-1
  interleaved load did exactly what it was designed to do.

**Tier-1b therefore failed for a different, and much more informative,
reason than Tier-1: the harness worked and the hypothesis did not.**

## 9. Harness soundness (checked in-container before judging)

- `analyze.py` re-run in the dev container over the committed cells
  reproduces `data/eval_results/HOST_ANALYZE_t1b_20260831.txt`
  **byte-identically** (modulo the host's CRLF line endings). The report is
  not a host-only artifact.
- Full per-cell validity checklist passes on all 21 cells: `protocol:
  tier1b`, `cap_enforced: true`, `cap_bytes_in_force` matching the rung,
  `swap_confounded: false`, `post_evict_resident_pct_{R,L} = 0.0`,
  `load_order: interleaved` with `n_chunks_R/L = 80/28` and a 108-character
  schedule containing exactly 28 `L`s (the one `r_then_l` cell is the
  order arm, excluded from every bar by construction).
- Independent cross-check of the load accounting: at every guided ES cell,
  pass-1 majflt equals the post-load *deficit in R* to the page —
  marginal (100 − 92.3438)% × 1,310,720 = **100,351.7 → measured 100,352**;
  boundary (100 − 84.8438)% × 1,310,720 = **198,655.5 → measured 198,656**.
  `majflt` is an exact miss counter, as the `repeat.fio` header claims.

## 10. Bar-by-bar (session-lead reading)

**Bar 1b — FAIL, and it is the substantive result.** Precondition satisfied
(marginal pass-1 majflt 159,641 > 0, trajectory falling). At the pass-3
window boundary p95 = 0.1567 ms vs marginal p95 = 0.0055 ms — inversion
ratio **0.04×** against a predicted 2–20×. Marginal converges *faster* than
boundary, not slower. Pre-registration Change 2 named this outcome in
advance: *"if convergence speed turns out to be deficit-dominated instead,
that is a FAIL and a finding, recorded."* It is deficit-dominated. Evidence:

| pass | marginal majflt | boundary majflt | ratio |
|---|---|---|---|
| 1 | 159,547 | 305,665 | 1.92 |
| 2 | 113,327 | 210,368 | 1.86 |
| 3 | 61,055 | 124,656 | 2.04 |
| 4 | 36,328 | 69,820 | 1.92 |

The two trajectories are **self-similar, scaled by the initial deficit**
(198,655 / 100,351 = 1.98). Pressure-scaled aging is present but
second-order: boundary's geometric per-pass decay is 0.582 vs marginal's
0.646 (halving time 1.28 vs 1.59 passes) — ~10% faster per pass, enough that
boundary reaches its first zero-fault pass at **8** while marginal needs
**10** despite twice the deficit, but nowhere near enough to invert a 2×
head start inside a 3-pass window. **Recovery rate is not what governs the
fixed-window outcome here; deficit size is.**

**Bar 2b — FAIL, but on a sub-resolution criterion.** The substantive half
holds (both rungs are inside 12 passes; marginal converges cleanly). It
fails on two things:
1. boundary reaches majflt = 0 at pass 8 and then shows a residual tail
   (126 / 128 / 66 / 160), so the D3 rule scores it not-converged. That
   single behaviour propagates into 2b, 3b, ES-1 and ES-3 (the tool flags
   those references "read with care").
2. steady-p95 spread 12.8% vs the ≤10% bar — that is 820 ns (marginal)
   vs 932 ns (boundary). **The bar is inside the harness's own noise
   floor:** across all 26 zero-majflt passes in this run the p95 of a
   fully-cached pass ranges 692–964 ns, a spread of **32.8% of the mean**
   (σ = 67 ns, 8%). A ±10% agreement bar on that quantity has no
   discriminating power. Note also the 160-fault tail cannot be what moves
   boundary's p95: 160 faults out of 1,310,720 ops is 0.012%, two orders of
   magnitude below the p95 point.

**Bar 3b — FAIL on one clause only.** The cliff clauses all hold and hold
strongly: thrash p3/p2 = 1.51 and deep = 1.00 (bar ≥ 0.80); steady p95
223.5× and 248.5× the converged reference (bar ≥ 10×) — the Tier-1 Bar-3
p50 defect is fixed, the tail metric sees the cliff exactly as intended;
neither converges. The bar fails **solely** on "every rung ≥ boundary
converges", broken by boundary's residual tail (above). This is a
consequence of the 2b finding, not independent evidence.

**Bar 4b — PASS, cleanly.** Pass-1 pgscan 0 / 162,988 / 308,712 / 887,992 /
1,112,316 fits→deep, monotone non-decreasing with no reliance on the 4096-page
clamp (the clamp was needed only for `fits`). Tier-1's Bar-4 512-page-wiggle
failure was correctly diagnosed as a noise-floor problem and is fixed.

**Bar 5 — PASS, genuinely clean.** `active_file` = 0.0 MiB (0.000 × R)
through all `fits` passes, bar < 0.25 × R. The 24 GB / 0.2 GB analogue
reproduces exactly, as in Tier-1.

## 11. The metric finding: clat p95 is a threshold detector, not a tail metric

Tier-1 moved every bar from p50 → p95 because the median could not see
faults. The Tier-1b data shows **p95 saturates instead**, and the bars
inherit that.

A percentile p_X reads fault latency iff the fault fraction f exceeds
(100−X)%. At bs = 4k over a 5120 MiB R, one pass is 1,310,720 ops, so p95
flips at f = 5% = 65,536 faults. Measured, every row in the run obeys it:

| cell / pass | majflt | f | p95 |
|---|---|---|---|
| boundary conv p3 | 124,656 | 9.51% | 154,624 ns |
| boundary conv p4 | 69,820 | 5.33% | 122,368 ns |
| boundary conv p5 | 36,068 | 2.75% | **4,640 ns** |
| marginal conv p2 | 113,327 | 8.65% | 162,816 ns |
| marginal conv p3 | 61,055 | 4.66% | **5,664 ns** |

So bar 1b's "inversion ratio 0.04×" is not a graded latency comparison at
all — it is a step function reading *"did this cell cross below 5% fault
fraction by pass 3?"* Marginal did (4.66%), boundary did not (9.38%).
Raising the percentile makes this worse, not better (p99 flips at f = 1%).
The metric that stays graded is `clat_ns_mean`, which tracks majflt almost
linearly (boundary converge: 38,298 → 26,463 → 15,501 → 9,012 → 5,279 →
3,660 ns over passes 1–6) — or majflt itself.

**This does not change any verdict.** Bars are frozen and judged as written;
Tier-1b is FAIL. It matters because the conclusion is robust to the metric
and the bar design is not: judged on `clat` **mean**, pass-3 boundary
(15,451 ns) is still 1.98× *slower* than marginal (7,822 ns). **There is no
inversion under any metric available in this dataset.** Bar 1b's failure is
real; bars 2b/ES-3's failures are metric artifacts.

## 12. Early-sort arm — the bars fail, the lever works

ES verdicts as judged: **ES-1 NO DATA** (boundary's steady reference is a
fallback), **ES-2 NO DATA** (marginal/boundary p95-excess reductions 52.1% /
65.6%, under the 80% bar), **ES-3 FAIL** (12.7% / 11.2% vs ±10%),
**ES-4 PASS** (guided changes nothing at `fits`, 2.1% deviation; does not
rescue thrash, p3/p2 = 1.46). **ES OVERALL FAIL.**

`analyze.py`'s footer asserts that ES-1/ES-2 failing with a sound harness
refutes §5.3. **As session lead I do not adopt that reading, and the raw
cells are why.** Judged on fault work — the graded metric — guided attains
the *theoretical optimum*:

| rung | baseline majflt to convergence | guided | reduction | irreducible floor (load deficit) |
|---|---|---|---|---|
| marginal | 423,700 (10 passes to zero) | 105,268 (2) | **75.2%** | 105,268 — floor hit exactly |
| boundary | 785,176 (8 passes to zero) | 198,656 (2) | **74.7%** | 198,656 — floor hit exactly |

Guided removes **100% of the removable fault work**. The residue it cannot
remove is the load deficit itself: those 100k / 199k R pages were never
loaded, and something must read them from disk once. The maximum achievable
reduction is therefore ~75%, and **ES-2's 80% bar was set above what the
mechanism can physically deliver.** ES-2 is unreachable by construction, on
any metric, for any implementation of the lever.

ES-3's FAIL is the same sub-resolution problem as bar 2b — 924 ns vs 820 ns
— compounded by a comparison defect: the fixed convergence rule lets the
guided cells stop at 4 passes while `none` runs to 12, so the two "steady"
values are read at different points on a drifting sub-microsecond baseline
(guided marginal's own p95 rises 820 → 860 → 924 ns across its passes 2–4).

**Net: §5.3 ("the sorting can be skipped") is NOT refuted by this run.** It
is supported on the fault metric — convergence in 1 pass instead of 8–10,
75% less fault work, at the theoretical optimum — and untested by the ES
bars as written, which are unreachable (ES-2) or below the noise floor
(ES-3). Re-judging it requires a new pre-registration on a graded metric;
it is **not** re-scored here.

## 13. ES-5 (exploratory, not judged) — the map-blind lever is net-harmful here

The Tier-1 morning result (inactive-list ORDER protecting R: 100 → 39.8%
survival) was a **load-order artifact and does not survive the interleaved
load.** Under Tier-1b, blind `memory.reclaim` cuts R and L proportionally —
R survival 73.9 / 66.2 / 58.7 / 28.7% descending caps, always within ~3
points of L. Mechanics were clean at every rung (`--privileged`, rc = 0,
caps still enforced, requested 1792 MiB, freed 1791–1794 MiB, no §9.5.2
signature).

Scored on total 3-pass fault work rather than p95-excess, blind is worse
than doing nothing at **every** rung:

| rung | baseline | blind | Δ |
|---|---|---|---|
| fits | 0 | 342,016 | **pure harm** (guided: 61) |
| marginal | 333,805 | 443,392 | +32.8% |
| boundary | 636,176 | 706,816 | +11.1% |
| thrash | 2,191,148 | 3,599,182 | +64.3% |

The one thing blind buys is *speed to steady state*: at marginal it takes
443,392 faults in pass 1 and then zero, so over a full convergence horizon
(vs baseline's 423,700 over 10 passes) it is roughly break-even on work and
8 passes faster. That is the honest design input for the real-stack
map-blind lever: **blind trades a larger one-shot fault bill for immediate
convergence, and destroys value wherever the working set already fits.**
Guided dominates it at every rung.

## 14. Exploratory order arm (recorded, not judged) — load order is the initial-state selector

The triptych is now complete, all three at the marginal rung, fixed3:

| load order | post-load R% | post-load L% | majflt p1→p3 | shape |
|---|---|---|---|---|
| L→R (Tier-1) | 100.00 | 93.42 | 0 → 0 | pre-sorted, no transient |
| interleaved (Tier-1b) | 92.34 | 92.75 | 159,641 → 61,130 | **decaying** |
| R→L (order arm) | 89.88 | 100.00 | 233,448 → 275,840 | **rising**, p95 pinned 185–189 µs |

Load order alone selects between "no transient", "converging" and
"diverging" at an unchanged cap, unchanged working set and unchanged access
pattern. This upgrades RESULTS.md §2's load-order dependence from an
explanation of one failure to a **measured, three-point finding**, and it is
the strongest result of the Tier-1b run.

## 15. Harness defects found on this run

- **D4 (new, found by the host session)** — `run_ladder.sh` skipped the
  image build whenever the `convrepro:latest` tag existed
  (`if [ -z "$(docker images -q "$IMAGE")" ]`), with no staleness check.
  `cell.sh` and `jobs/` are baked in via `COPY`, so the Tier-1b run would
  have silently executed the **Tier-1** `cell.sh`. The host caught it,
  hand-rebuilt (`3801e4026241` → `c1689cfc2775`) and proved the new
  `cell.sh` in-image before any cell ran; every committed cell carries
  `protocol: tier1b`, which confirms the run is clean. **Fixed in this
  commit**: the build inputs (`Dockerfile`, `cell.sh`, `jobs/*`) are hashed
  into a `convrepro.build_hash` image label and the image is rebuilt
  whenever the hash differs.
- **D1/D2/D3 (Tier-1) — all three verified fixed by this run.** D1: the
  `convrepro_t1b_*` glob matched 21 cells and no mechanics cell; header read
  `scale(s) : [1.0]  caps enforced: True` with no MECHANICS CHECK label.
  D2: `--build-only` laid down the volume. D3: the strengthened rule
  correctly refused to call deep's 1.31M-majflt plateau "converged".
- **New (bar design, for the next pre-registration, not fixed here):**
  (a) every single-percentile latency bar is a threshold detector on fault
  fraction (§11) — use `clat` mean or majflt; (b) ES-2's 80% bar exceeds the
  mechanism's physical ceiling of ~75% (§12); (c) bar 2b / ES-3's ±10%
  agreement bars sit inside a ±16% noise floor (§10); (d) ES-3 compares
  cells that stopped at different pass counts (§12).

## 16. Where this leaves the publication gate

> **Update 2026-09-05:** superseded on item 1 — the index-independent
> synthetic reproduction is now **PASSED** by Tier-1d (access skew was the
> missing variable). See the Tier-1d section, §23–25.

Item 1 (index-independent synthetic repro) is **not passed, and this is now
a substantive negative result rather than a harness failure.** Tier-1 failed
because the protocol prevented the phenomenon from appearing; Tier-1b built
the transient the phenomenon requires, and the inversion still did not
appear under any metric in the dataset. On this WSL2 classic-LRU host with
naive two-population interleaved load and uniform-random repeat, **fixed-window
convergence outcome is deficit-dominated**, with pressure-scaled aging a
~10%-per-pass second-order effect.

What that does *not* establish: that the real stack's observation is wrong.
The real index's access structure (skewed, structured, fault-around active,
multi-slab) differs from a uniform-random single-file repeat in exactly the
ways that would matter. The load-order triptych (§14) shows the initial
state is decisive, and the synthetic's initial state is a design choice, not
a measurement of the real one.

Recommended next step, requiring **fresh pre-registration** (Tier-1c or a
real-stack test — session lead's call, not taken here): the cheapest
discriminating experiment is no longer another synthetic ladder. It is to
measure the real stack's *post-load residency profile* and reproduce that as
the synthetic's initial state, rather than continuing to guess at load
orders. Items 2–3 (native Linux, MGLRU) unchanged, still pending.

## 17. Result files (Tier-1b)

Raw cells (committed `3729df30`):
`data/eval_results/convrepro_t1b_*_20260831.json` — 21 cells (5 rungs ×
fixed3, 4 rungs × converge, 4 guided + 4 blind ES cells, 2 guided converge,
1 exploratory order arm), plus `.json.log` per cell. Verbatim host
`analyze.py` output: `data/eval_results/HOST_ANALYZE_t1b_20260831.txt`
(332 lines, CRLF, reproduced byte-identically in-container 2026-08-31 —
§9). Verdict tool: `spike/convergence_repro/analyze.py` at commit
`73ec114c`. No tuning-history entries were created by this run (§8).

---

# Tier-2/3 (real stack, native Linux + MGLRU) — RESULTS (2026-09-01 phase B)

**Verdicts recorded 2026-09-01 by the dev-container session lead, from the
16 valid phase-B cells `data/eval_results/t23b_*_20260901.json` (OCI serve
box, x86_64 kernel 6.17.0-1018-oracle, real 150M index + real 40-query
workload, `prefault_gate: "1"` on every cell). Judged strictly against the
B1–B5 bars frozen at `1a87aac3` (`PREREGISTRATION_TIER23.md` §7); the
protocol-violated run 1 (`t23b0_noprefault_*`) is excluded from every bar.**
Bar inputs: `.venv/bin/python3 scripts/seismic_testbed/t23b_bar_inputs.py
20260901`.

## 18. Headline verdicts (Tier-2/3)

- **B2 (classic transient) PASS** — publication-gate item 2's transient is
  confirmed with pre-registered replicates on the real stack, native Linux.
- **B3 (classic fixed-window inversion) PASS** — the artifact itself
  (smaller cap ≥2× faster at the fixed window, fewer faults, same steady
  state) replicates: 5.8× / 5.6× at 26-vs-28 GB.
- **B1, B4, B5 OPEN** — every bar naming the deadline-cut cell
  (`mglru:28:1`) stays open per the frozen rule; B1's cliff definition
  additionally binds to no phase-B cell (no rung plateaus — 16/16 converge
  near-zero in 3 passes). *Superseded 2026-09-01 22:06 UTC: the cell ran
  in a resume window and B1/B4/B5 are judged — see §21.*
- Window 19:47–21:28 UTC, 16/17 cells before the 100-min deadline; N4
  health gate passed both sides; restore trap clean.

## 19. Bar-by-bar (Tier-2/3 phase B)

- **B2 PASS.** Classic 26 G majflt decays over 3 passes to near-zero in
  both replicates: `31,642→5,072→0` / `31,523→5,100→0`. Corroborating
  single cells: 25 G `34,307→2,771→0`, 27 G `26,627→8,699→0`.
- **B3 PASS.** Fixed pass-2 window, pair (26 G, 28 G): p50 63.9 vs
  372.6 ms (5.8×, rep1) and 62.4 vs 352.3 ms (5.6×, rep2); small-cap
  majflt lower in both (5,072 < 22,535; 5,100 < 22,598); both rungs reach
  the same steady state (19.5–21.2 ms, majflt ≤604). This is the phase-A
  4.1× signal, now replicated under frozen bars.
- **B1 OPEN.** All 16 cells satisfy the near-zero clause (converged ≤4
  passes); the plateau clause and the cliff itself are uncomputable — no
  phase-B rung plateaus (classic's plateau is below the 25 G ladder
  floor; MGLRU's phase-A plateau rung 28 G was not run).
- **B4 OPEN** (names mglru 28). Classic inputs: pass-1 pgscan strictly
  monotone in pressure, 6.15M/5.20M/3.96M/0.93M/0.13M/0 across 25→30 G;
  active_file 31–38× at pressured rungs 25–28, 1.25× at marginal rung 29.
  Hazard recorded pre-judgment: MGLRU holds ~14.35 G active_file at zero
  pressure, so the ≥10× clause cannot separate MGLRU cells.
- **B5 OPEN** (names mglru 28; classic cliff unbracketed by the frozen
  ladder — displacement will remain uncomputable as frozen; if 28 G
  plateaus as in phase A the displacement is ≥ ~4 GB, lower bound only).

Replication note: the three classic rungs shared with phase A reproduce
nearly bit-for-bit (28 G: A `12,730→22,127→577` vs B `12,283→22,535→565`);
between-replicate spread ≤1% on every judged quantity.

## 20. Result files (Tier-2/3)

Phase A raw (committed `29d58b89`): `data/eval_results/t23a_*_20260901.json`
(14 cells + 2 no-prefault exploratory). Phase-B run 1, protocol-violated,
quarantined (committed `5feddead`):
`data/eval_results/t23b0_noprefault_*_20260901.json` (17 cells, excluded
from all bars, kept as the accidental no-prefault A/B). Phase-B run 2,
valid (this commit): `data/eval_results/t23b_*_20260901.json` (16 cells) +
run log `_t23b_run_20260901.log`. Extractor:
`scripts/seismic_testbed/t23b_bar_inputs.py`. Missing: `mglru:28:1` (one
~30 min window; any-date resume SKIP shipped this commit).

## 21. Phase-B completion: mglru:28:1 + judgment of B1/B4/B5 (2026-09-01 22:06 UTC)

`mglru:28:1` ran 21:46–22:06 UTC in a ~20 min resume window (16 any-date
SKIPs verified; `prefault_gate=1`; N4 passed both sides): **plateau in 5
passes**, majflt `12,325 → 41,321 → 46,446 → 48,948 → 49,315`, p50 2.5 →
5.2 → 5.4 → 4.3 → 4.7 s — phase A's plateau replicated at the rung where
classic converges to ~21 ms in both reps. Full 17/17 judgment:

- **B1 NOT PASSED (half-computable).** MGLRU: cliff 28.5 G, rungs ≥
  cliff+2 (31/32) near-zero in 3 passes, no rung ≤ cliff−2 in the ladder
  (vacuous). Classic: no plateau rung in 25–30 → the frozen cliff
  definition binds to nothing; ladder floor sits above classic's cliff.
- **B4 FAIL as frozen.** pgscan strictly monotone holds for classic
  (6.15M > 5.20M > 3.96M > 0.93M > 0.13M > 0), fails for MGLRU on
  zero-ties (891,816 > 86,877 > 0 = 0 = 0). active_file ≥10× holds at
  classic 25–28 (31–38×), fails at classic 29 (1.25×) and every MGLRU
  cell (~1.0×; MGLRU holds ~13.4 G active at zero pressure). Tier-1b's
  bar-design failure classes again; mechanism supported (§22), bar
  arithmetic not.
- **B5 NOT PASSED (direction established, magnitude lower-bounded).**
  MGLRU cliff 28.5 G at 1 G resolution; classic cliff below the 25 G
  floor → displacement ≥ ~4 G upward for MGLRU, which at equal caps
  replaces the classic transient with sustained thrash (28 G: 4.6 s vs
  ~21 ms, ~220×).

**Final tally: B2/B3 PASS, B1/B5 not-passed on uncomputable components,
B4 FAIL on bar arithmetic.** Tightening B1/B5 requires a ladder extension
below 25 G under a new pre-registration.

## 22. Exploratory mechanism reading (not judged): reclaim timing explains the non-monotonicity; MGLRU's missing refault-activation explains the thrash

Probe: `scripts/seismic_testbed/t23b_mechanism_probe.py` over all valid
t23a/t23b cells. Recorded 2026-09-01; exploratory, no bars.

- **Load invariance (the index is not the variable):** all 28 valid cells
  load identically — 165 s, 4,100 majflt, 15.14 G file / 13.56 G mapped,
  zero reclaim scan — at every cap, both arms, both phases. Everything
  that differs happens after an identical initial state. (Phase A's
  classic-cap32 load anomaly, 13.19 G / 175 s, did not recur in any
  phase-B cell; unexplained, isolated, touches no judged cell.)
- **Band placement is footprint arithmetic:** two-population file
  footprint after pass 1 ≈ 28.1 G + ~1.0 G anon ≈ 29.1 G. 30 G fits
  (zero scan); 29 G barely trims (130k pages); ≤28 G forces the one-time
  cache sort. The band's RAM position is an index/workload property
  (footprint), not a kernel one.
- **The non-monotonicity is sort scheduling:** the sort's timing is
  pressure-proportional. 25 G: pass-1 scan 6.15M, active_file 16.1 G by
  pass-1 end — sorted before the window — pass-2 p50 26 ms. 28 G: pass-1
  scan 0.93M, active_file 2.5 G — unsorted — the sort lands inside pass 2
  (scan 3.3M, refault 3.0M, active_file 2.5 → 13.7 G), p50 373 ms.
  Pass-2 refaults rise monotonically with cap: 0.19M / 0.34M / 0.43M /
  3.02M across 25→28 G. Smallest deficit = latest sort = slowest window.
- **Classic sorts via refault-activation:** ws_activate ≈ ws_refault on
  every pressured classic pass — refaulting hot pages are promoted,
  residue demoted, converging in ≤3 passes everywhere down to 25 G.
- **MGLRU thrash anatomy (28 G):** active_file pins at 13.55 G from pass
  1 and never moves; ws_activate falls to literally 0 by pass 4 while
  ws_refault holds 4.5–5.9M/pass — refaulting pages are never
  re-promoted, the load-time promotion mistake persists, and scan ≈
  steal ≈ refault ≈ 4.5M/pass indefinitely. The zero-pressure tell:
  MGLRU marks 13.36 G active where classic marks 0.44 G — harmless when
  memory fits, fatal when the initial promotion is wrong under pressure.
- **Cap-free levers implied:** no-residue load kills the artifact at
  every cap (measured — the quarantined run-1 accident); a warmup pass
  before the window reaches the ~19.5 ms floor regardless of history
  (measured — every converged cell from pass 3); one-shot
  `memory.reclaim`/`MADV_PAGEOUT` of the residue at startup (*est.*,
  unmeasured — candidate for the §5.3/5.4-style follow-up).

---

# Tier-1d (synthetic ACCESS SKEW, WSL2 local) — RESULTS (2026-09-05 judged window)

**Verdicts recorded 2026-09-05 by the session lead (dev container), from the
8 judged cells `data/eval_results/t1d_*_seed{2027,8128}_20260905.json`
(user's WSL2 box, kernel 6.18.33.2+, `.wslconfig` 56 GB fixed experiment
profile, windows W1–W3 15:11:47–16:42:16 local; evidence package committed
`47f0a7c3`, incl. `_t1d_JUDGED_report_20260905.md`). Judged strictly against
the §5 bars frozen at `5f55fb32` (`PREREGISTRATION_TIER1D.md`; calibration
recorded `db11dc44`). Bar inputs: `.venv/bin/python3
spike/convergence_repro/t1d_bar_inputs.py 20260905` (extractor pinned
pre-data at `6e9e5612`). Judged seeds 2027/8128 only; calibration seed 1729
is burned and appears as corroboration.**

## 23. Headline verdicts (Tier-1d)

- **T1d-1 PASS** — the real stack's LRU-arm asymmetry is **reproduced
  index-independently**: at cap 1.5 GiB (`hot-set < cap < |R|`,
  `hotset:0.20:0.80`, frac92) the MGLRU/classic steady-floor ratio is
  **1.443 (seed 2027) and 1.443 (seed 8128)** against the frozen bar ≥1.30.
  **Publication-gate item 1 is PASSED**: the artifact's arm asymmetry needs
  only skewed access over a pressured mapping — no seismic index, no real
  workload. *Citation per the frozen ±16% rule: 1.443/1.30 = +11%, within
  the margin, so this verdict cites the §4 pageReporting caveat — the
  control cell (ratio 1.000, identity exact, bit-identical arms) and the
  in-band 4 GiB cell bound any balloon interference below the noise floor.*
- **T1d-1b PASS** — mechanism shape confirmed in both replicates: classic
  descends (floor/pass-1 = 0.643 / 0.644, bar ≤0.75 — cites the caveat,
  within margin) while MGLRU pins (max pass-2–12 deviation 1.1% / 0.7%,
  bar ≤5%).
- **T1d-3 PASS** — regime specificity: 8 GiB control ratio **1.000** (band
  [0.84, 1.16]), both arms converged (floors 1,581.3 ≤ 2,500, converged
  pass 10, trajectories bit-identical); 4 GiB band ratio **1.038** (bar
  ≤1.20, inside Tier-1c's uniform 1.013–1.034). Both cite the caveat per
  the ±16% arithmetic as frozen. The divergence exists only where skew
  creates the third regime.
- **T1d-5 PASSED (validity)** — both `STRICT_SOUNDNESS=1` control cells:
  reachable identity exact (pass-1 majflt 39,160 == reachable deficit).
  The window is valid in toto.
- **T1d-2 recorded:** only h=0.20 ran (the optional cells 9+ were not run —
  the verdict set consumed the window budget). The skew-threshold sweep
  stays open, non-gating: at h=0.20 the ratio clause holds in both seeds.
- **T1d-4 recorded:** S-inversion cells not run (cells 9+). Trajectory
  shape recorded: classic shows a majflt **minimum at pass 5** (~305–306k,
  coinciding with the hot-residency transient peak ~95% at pass 4) before
  settling at ~335k — non-monotone, same shape as calibration.

## 24. The numbers + the first hot-set-residency capture

Steady floor = mean majflt of last 3 of 12 passes:

| cap | seed | classic floor | mglru floor | MGLRU/classic |
|---|---|---|---|---|
| 1.5 GiB | 2027 | 334,678 | 482,884 | **1.443** |
| 1.5 GiB | 8128 | 334,868 | 483,204 | **1.443** |
| 8 GiB (control) | 2027 | 1,581 | 1,581 | 1.000 |
| 4 GiB | 2027 | 105,628 | 109,591 | 1.038 |

Replication is tight everywhere: classic 1.5 GiB floors within 0.06% across
seeds, MGLRU within 0.07%, and all four rungs land within 0.1% of the
calibration values (1.442 / 1.000 / 1.037 at seed 1729).

Per-pass `hot_resident_pct` (T1d-7 readout 4, first capture — the field
landed in `b3a9377a` after the calibration window): **classic climbs
~73% → ~90%** (transient peak ~95% at pass 4, the majflt minimum following
at pass 5) while **MGLRU pins at 75.0% flat from pass 2**, identically in
both seeds (after-seed hot residency ~28%, matching whole-R — the seed is
skew-independent as designed). This is the Tier-2/3 §22 mechanism
photographed in the synthetic: classic re-promotes refaulting hot pages
(ws_activate ≈ ws_refault on the real stack), MGLRU never does.

Deviations (full list in `_t1d_JUDGED_report_20260905.md`): the three-window
`systemd-run` split for `STRICT_SOUNDNESS` scoping (structural, pre-flagged);
the 4 GiB pass-11/12 uptick **recurred both arms in the calibration's shape**
(passes 3–10 plateau ~89k/~90k; the last-3 floor definition includes the
uptick, inflating both floors together — the ratio bar is insensitive to it,
but any future *absolute*-floor use of the 4 GiB cells must exclude passes
11–12); environment matched calibration (all containers running); no reboot
(boot verified carrying the profile); dmesg pageReporting line still present
(the §4 standing caveat, cited above where the ±16% rule requires).

## 25. Result files (Tier-1d)

Judged cells (committed `47f0a7c3`): 8 × `t1d_{classic,mglru}_hotset-0.20-0.80_frac92_cap{1.5g,8g,4g}_seed{2027,8128}_20260905.json`
+ 16 `.log`/`.status` + runlog `_t1d_runWSL2_20260905.log` + evidence report
`_t1d_JUDGED_report_20260905.md`. Calibration (seed 1729, exploratory):
committed `9ac830a3`/`3cf39d7c`, recorded in the pre-reg §4 (`db11dc44`).
Verdict tool: `spike/convergence_repro/t1d_bar_inputs.py` at `6e9e5612`
(committed before any judged cell existed). Bars: `PREREGISTRATION_TIER1D.md`
§5 frozen at `5f55fb32`. Still open in the Tier-1d line, non-gating:
S-realprofile (§3.6, severed pending §6 gap 3 + the OCI billing decision) and
the recorded-only cells 9+ (T1d-2 sweep, sub-hot-set rung, fault-around pair,
S-inversion) — available to a later window, none gates a verdict above.

> **Update 2026-09-06:** the recorded-only cells 9+ have now run
> (characterization windows T1d-11/13/14/15/16, 2026-09-05/06) — readouts
> recorded in §26–29 below. T1d-12 (clustered × readahead) remains the one
> deferred window. S-realprofile unchanged, still severed.
> **Update 2026-09-06 (later):** T1d-12 and T1d-17 have now also run —
> readouts §30–31; **the Tier-1d line is settled** (§31), no window queued.

---

# Tier-1d CHARACTERIZATION windows (recorded-only) — readouts recorded 2026-09-06

**Recorded 2026-09-06 by the session lead (dev container), from the evidence
package committed `226adecc` (host-ops session, user's WSL2 box, same 12:50
boot and 56 GB experiment profile as the judged window; windows W1–W7b,
17:07 2026-09-05 → 00:19 2026-09-06 local; seed 2027 only). Everything in
§26–29 is recorded-only under the frozen §5 — no bar verdict in §23 changes.
Full per-window detail, freshness tokens, wall times and the complete
deviation list: `data/eval_results/_t1d_CHAR_report_20260905.md`. 20 of 26
attempted cells completed with JSONs; the 6 sheds are all six fault-around
cells, rc=124 at exactly `CELL_TIMEOUT=1800 s`, and that uniform shed is
itself the S-faultaround readout (§28).**

## 26. T1d-2 sweep + sub-hot-set rung: the divergence is a peaked curve

Steady floors (mean majflt, last 3 of 12 passes), frac92, m=0.80, seed 2027:

| h (hot set) | cap | classic floor | mglru floor | MGLRU/classic |
|---|---|---|---|---|
| 0.05 (256 MiB) | 1.5G | 212,056.3 | 242,654.7 | 1.144 |
| 0.10 (512 MiB) | 1.5G | 220,041.0 | 310,562.7 | 1.411 |
| 0.20 (1 GiB) — judged §24 | 1.5G | 334,678.3 | 482,884.0 | 1.443 |
| 0.40 (2 GiB > cap) | 1.5G | 678,079.0 | 765,387.3 | 1.129 |
| 0.20 (1 GiB > cap) | 0.75G | 747,213.0 | 834,555.0 | 1.117 |

The arm asymmetry needs a hot set **big enough to be contested, small enough
to fit**. `hot_resident_pct` carries the mechanism: classic climbs to
~90–100% wherever the hot set fits (h ≤ 0.20) while MGLRU churns lower;
where the hot set exceeds the cap (h=0.40, or cap 0.75G) both arms sit at
~44–58% residency and the ratio collapses into the ±16% noise band. On the
skew-threshold question this brackets the rise between h=0.05 (1.144,
borderline vs ±16%) and h=0.10 (1.411, clearly out) at this cap —
narrowed, not closed. Caveat from the CHAR report: the h=0.05 pair is the
least stable measurement in the sweep (end-of-run upticks, classic pass-12
238,128 against a ~198k plateau; mglru noisy 210k–259k with no plateau), so
1.144 is soft in a way the other rows are not.

## 27. S-inversion: closed NEGATIVE in all three forms attempted

The synthetic inversion gap was chased through three successive forms in one
night, each triggered by the previous readout, and every form came back
negative:

1. **Deficit form (T1d-11 pri 1):** `classic:70:1.5` ≡ the judged
   `classic:92:1.5` — floor 334,564.7 vs 334,678.3, fixed-pass trajectories
   identical within noise. Under a binding cap both frac settings seed to
   the same cap-determined ~28.6% residency; the deficit-size manipulation
   is **inoperative**.
2. **Cap-pair form, no residue (T1d-13):** classic at 6.5/7/7.5 GiB all
   bit-identical to the 8 GiB control (floor 1,581.3, converged pass 10) —
   at any cap > |R| with L cold there is **no transient at all**; the cap
   never binds.
3. **Residue form (T1d-15, `--warm-l`, the closest analog to B3):** L warmed
   to 100% as a 1.75 GiB residue before R's seed. The residue IS displaced,
   in a clean cap ladder (end-of-run `l_resident_pct` ~23.1% @5.5G, ~51.7%
   @6G, ~80.2% @6.5G, 100% @8G control) — but the displacement is
   **costless to R**: majflt trajectories and per-pass walls bit-identical
   to the control at every cap. No B3 signature; the tighter cap neither
   sorts earlier nor converges faster at the fixed window. Arm contrast
   near-nil, and slightly *contra* the §22 expectation: MGLRU holds
   ~0.9–1.0 points **less** of the residue than classic at both caps.

Mechanistic reading (recorded, not judged): in this synthetic the residue
sort lands **during R's seed** — pass-1 `l_resident_pct` is already at the
cap-determined level — so the sort's work is finished before the first
measured pass, and L, never re-touched, refaults nothing. B3 on the real
stack is the opposite arrangement: §22 measured the sort landing **inside
the fixed window** (28 G: pass-2 scan 3.3M / refault 3.0M), which is what
made the smaller cap faster. Reproducing the inversion synthetically would
require a form in which the displacement work is deferred into the measured
passes (e.g. a residue that is itself re-referenced, or a seed that leaves
the sort incomplete) — a new driver design, for a future pre-registration if
ever; no current form supports it.

## 28. S-faultaround + the amplification chain: the first factor is ≳30× per-fault cost

All six fault-around cells (frac92 seeded 1.5G, cold-start 1.5G, cold-start
2.5G fallback; both arms) failed rc=124 at exactly 1800 s with **zero
completed passes** — the seeded pair hung in the seed loop, the cold pairs
seeded cleanly and never finished pass 1. The same cells under
`MADV_RANDOM` run ~40–75 s/pass. Recorded readout: **with readahead on,
under a binding cap, per-pass wall is amplified >30× before any arm
asymmetry enters.** This is the night's principal input to the 1.44×→220×
amplification-chain gap: the real stack's ~220× (§21) has the shape
(fault-count ratio ~1.44×) × (per-fault cost amplification of this order),
and the second factor is now measured to exist at the right magnitude in
the synthetic. Per the T1d-14 rule the timeout was never raised; the branch
closed at the fallback rung with `.log`/`.status` as the evidence (no JSONs
exist for any fa cell). The remaining piece of the chain is the T1d-12
clustered-hot-set 2×2 (does clustering alone move the 1.44×; does
clustered+readahead compound), deferred — its driver prerequisite
(`7bc29b30`, `hotsetc`) is already in this checkout.

## 29. T1d-16: stock MGLRU is not rescuable by `min_ttl_ms` at the divergence rung

`mglru:92:1.5:2027` re-run under window-level `MIN_TTL_MS` 1000 and 4000
(sysfs boot value 0 restored and echoed after each window): floors 483,013.7
and 483,021.7 vs the judged 482,884.0 baseline — no effect, either
direction, and the 75.0% `hot_resident_pct` pin is untouched (71.98% pass 1
→ 75.0 flat, both values). The knob neither rescues nor backfires at this
rung: the divergence is not a configuration artifact of generation
lifetimes, consistent with the §22/§24 mechanism (the missing
refault-activation is what pins the hot set, and `min_ttl_ms` does not
touch promotion). Run under the user's explicit no-time-cap instruction,
superseding HOST_RUN.md T1d-16's 3-hour-budget line (deviation recorded in
the CHAR report).

**Where this leaves the Tier-1d line (recorded 2026-09-06):** all §23
verdicts stand unchanged. Of the three characterization gaps: the
**skew threshold** is narrowed to a measured peaked curve (§26); the
**synthetic inversion** is closed negative in every form the current driver
supports (§27); the **amplification chain** has its first factor measured
(§28) with the T1d-12 corners as the one remaining queued window.
S-realprofile stays severed behind §6 gap 3 (real-access-histogram probe,
OCI billing decision). Host note: the user's `.wslconfig` still carries the
56 GB experiment profile; the revert to the everyday 32 GB block is pending
until the Tier-1d window is declared settled (T1d-12 would reuse the same
profile).

Result files (all committed `226adecc`): 21 cell JSONs
(`..._20260905.json` × 20 + `..._ttl4000_20260906.json` — the ttl4000
window crossed midnight, so its files carry the 20260906 stamp),
`.log`/`.status` pairs for all 26 attempted cells (the six fa logs are the
fa evidence), runlogs `_t1d_runWSL2_20260905.log` (appended) and
`_t1d_runWSL2_20260906.log`, and the evidence report
`data/eval_results/_t1d_CHAR_report_20260905.md`.

## 30. T1d-17: the synthetic inversion is closed NEGATIVE in its final form — the in-window, pressure-proportional sort costs R nothing

**Recorded 2026-09-06 by the session lead (dev container), from the evidence
package committed `00a528ea` (host-ops session, windows W1/W2,
12:08–14:09 local 2026-09-06, same 56 GB experiment-profile boot; seed 2027
only; recorded-only under the frozen §5 — no §23 verdict changes). Full
detail: `data/eval_results/_t1d_CHAR_report_20260906.md`.**

T1d-17 ran the corrected cold-start residue form (`frac0` + `wl:` — R 5 GiB
laid down cold through the skewed draw, L 1.75 GiB pre-warmed to 100% as
residue, displacement scheduled by pressure inside the measured window):
6/6 cells DONE, walls 255–276 s, no sheds. The §27 defect is fixed **and
observably so**: `l_resident_pct` now declines in-window and
pressure-proportionally (8 GiB control flat at 100%; 6.5 GiB → 90.7%;
6 GiB → 62.5%; 5.5 GiB → ~33% by pass 12) — the sort happens where the
fixed window can see it. And still no inversion: the majflt trajectories
are **bit-identical across all four caps and both arms** (pass 1→12:
488,890 / 185,803 / 140,584 / … / 14,938; walls identical within noise), so
at the fixed pass-2/pass-3 window the tighter cap looks neither better nor
worse. Mechanism: reclaim — classic AND mglru — victimizes the
never-retouched L pages exclusively and never evicts R, so the residue sort
has zero majflt/wall cost to the measured workload. The arm contrast on
residue sorting is null too (~1 pp; mglru DOES demote the residue here,
unlike the real stack's §22 behavior — the missing-refault-activation
asymmetry needs re-touched pages to bite, and a pure residue never
re-touches).

**Where this leaves the inversion:** closed negative in every form the
current driver can express — cap-pair (§26/T1d-13), warm-residue (§27
/T1d-15), cold-start (T1d-14), and now cold-start+residue with the sort
in-window (this section). The B3 real-stack observation (§1) stands as an
observation; a synthetic reproduction, if pursued at all, requires
ingredients beyond this harness (plausibly the real stack's re-touched
residue) and a fresh pre-registration (Tier-1e) per HOST_RUN.md T1d-17.
Nothing judged.

## 31. T1d-12: clustering alone moves nothing — the four-corner table closes, and the Tier-1d line is SETTLED

Same evidence package (`00a528ea`, W2). The two clustered/no-readahead
corners: floors classic **334,788.3** / mglru **482,963.0** → ratio
**1.443**, replicating the scattered judged floors (334,678.3 / 482,884.0 →
1.443) to **0.03%** in both arms; fixed-pass values and end-state hot
residency match likewise (classic ~90%, mglru pinned 75.0%). **Reclaim on
this kernel is layout-blind at this rung under MADV_RANDOM** — clustering
contributes nothing to the 1.44×→~220× amplification chain on its own.

The compounding corner (clustered + readahead) is **unmeasurable in this
harness at this rung**: both `fa:hotsetc` cells shed rc=124 at exactly
1800 s inside the seeding loop, zero pass lines — the identical signature
as all six 20260905 fa sheds. Fault-around sheds are now **8-for-8 uniform
across layouts (scattered/clustered), frac forms (92/0), and caps
(1.5/2.5 G)**, and that uniformity is itself the S-faultaround readout
(§28): readahead under a binding cap thrashes before measurement can begin,
dominating any layout effect.

Four-corner table (rung 1.5 GiB, frac92, h=0.20 m=0.80, seed 2027):

| layout \ readahead | MADV_RANDOM | fault-around |
|---|---|---|
| scattered | 1.443 (judged T1d-10) | SHED ×2 (20260905) |
| clustered | 1.443 (this window) | SHED ×2 (20260906) |

**Tier-1d line declared SETTLED (2026-09-06).** All §23 verdicts stand
unchanged; every queued window (T1d-11 through T1d-17) has run and its
readout is recorded (§26–31); no window remains queued. Still open,
non-gating, outside the line: S-realprofile (severed behind §6 gap 3 + the
OCI billing decision) and any Tier-1e pre-registration a future inversion
pursuit would need. Host follow-up now unblocked: the `.wslconfig` revert
from the 56 GB experiment profile to the everyday 32 GB block (needs a
`wsl --shutdown` hygiene-reboot slot; user timing).

Result files (all committed `00a528ea`): 8 cell JSONs + `.log`/`.status`
for all 10 attempted cells (the two fa sheds have `.log`/`.status` only),
runlog `_t1d_runWSL2_20260906.log` (appended), and the evidence report
`data/eval_results/_t1d_CHAR_report_20260906.md`.

## 32. T1d-probe (2026-09-12): the real index's access histogram — gap 3 CLOSED, real skew is `hotset:0.10:0.80` on forward pages, hot set barely clustered

Recorded 2026-09-12 from `PREREGISTRATION_T1D_PROBE.md` §7 (frozen) / §8
(results); raw `data/eval_results/t1dprobe_*_20260912.*` (commit
`14ceea4d`); chart
https://claude.ai/code/artifact/e0be4531-9061-43bc-8c5b-95cfe1d62eaa.
Counting probe, local, no OCI cost; two 1,000-draw replays byte-identical
(determinism PASS). Readouts: hot-80 = **10.4%** of forward pages / 3.21 GB
(Q12b 2026-07-14: 3.07 GB); mass at synthetic h = 0.05/0.10/0.20 →
0.589/0.789/0.961 — the judged `hotset:0.20:0.80` cells drew a *softer*
skew than the real index shows on the forward-page denominator (real ≈
`0.10:0.80`, the T1d-11 sweep rung); hot-80 clustering 446,508 extents,
run p50 1 / p90 3 / max 266, only 1.57× tighter than random placement, so
the T1d-12 `hotsetc` E=8 arm over-models contiguity. No verdict moves;
S-realprofile stays severed only on the driver import mode and the
initial-residency profile (§8.3 there).
