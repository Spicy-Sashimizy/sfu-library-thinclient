# Early-sort arm (the §5.3 "skip the sort" claim) — pre-registration

**Written 2026-08-31, BEFORE the arm was built or any cell run.** Extends
`PREREGISTRATION.md` (the Tier-1 fio harness) — same files, sizes, rungs,
protocol, metrics, environment, and caveats unless stated. Parent claim:
`04_CONVERGENCE_ARTIFACT.md` §5.3 — "the sorting can be skipped entirely" by
evicting the load residue by name at load, jumping straight to the sorted
state without pressure or observation passes. Status of that claim on the
real stack: **UNTESTED** (the 2026-07-14 F5 cell was a null with a diagnosed
scope bug — hook covered only the forward slab). This arm tests it cleanly:
in the synthetic, the residue is exactly `L.bin`, so eviction-by-name is
trivial and unambiguous.

## Design

One new cell knob, `EARLY_SORT` (default `none`), applied between the load
phase and pass 1:

- **`guided`** — `vmtouch -e L.bin` (+ verify ≤1% resident): the map-guided
  F5 analogue — the application names the residue.
- **`blind`** — write `L_bytes` to the cell cgroup's `memory.reclaim`
  (cgroup v2 proactive reclaim): the map-blind analogue (`memory.reclaim` /
  TMO-style). The kernel must pick victims itself. Genuinely open
  sub-question, both outcomes informative: at that moment residue and repeat
  set have IDENTICAL reference bits (each touched once), so success would
  come only from inactive-list ORDER (L was loaded before R). Prediction
  (*est.*, low confidence): partially effective — between `none` and
  `guided`. If `memory.reclaim` is unwritable in the capped container, the
  arm is recorded BLOCKED, not failed.

Cells: rungs {fits, marginal, boundary, thrash} × EARLY_SORT {guided, blind},
fixed3 mode for the headline + converge mode at marginal and boundary.
Baselines = the Tier-1 ladder's `none` cells from the same host run (same
date, same box — never cross-run comparisons). Early-sort actions and their
wall time are recorded in the cell JSON (the cost side of the ledger).

## Pre-registered bars

- **ES-1 (the claim):** at marginal and boundary rungs, `guided` pass-1 p50
  ≤ 2× that rung's converged steady p50 (baseline pass-1 measured ~50–84×
  steady on the real stack; prediction *est.* here: pass-1 ≈ steady, majflt
  ≈ 0 since after evicting L the repeat set fits under both caps).
- **ES-2 (transient eliminated):** guided transient excess — Σ over passes
  1–3 of (p50 − steady) — is reduced ≥ 80% vs the same rung's `none` cell.
- **ES-3 (no free lunch at steady state):** guided converged steady p50
  within ±10% of the `none` steady p50 (early sort buys the transient only).
- **ES-4 (the boundaries hold):** at fits, guided changes nothing (pass-1
  p50 within ±25% of `none` pass-1 — the sort never needed to happen); at
  thrash, guided does NOT rescue (pass-3 majflt ≥ 0.8× pass-2 still — the
  cliff is capacity arithmetic, not transient behavior).
- **ES-5 (blind, exploratory — recorded, not pass/fail):** blind's transient
  reduction as a fraction of guided's, plus post-reclaim residency of R vs L
  (did inactive-list order save it?). Whatever the number, it ships in the
  write-up.

PASS = ES-1..ES-4 all hold. ES-1/ES-2 failing while the harness is sound
would REFUTE §5.3 for the synthetic — recorded as such, not tuned away.
Same execution constraint as Tier 1: capped cells require the host-side
docker position; build + smoke here, SCALE=1 run host-side.

## Deliverables

`EARLY_SORT` support in `cell.sh` (+ JSON fields), `--early-sort` flag and
cell matrix in `run_ladder.sh`, ES-bar section in `analyze.py` (auto-skipped
when no early-sort cells present), BUILD_NOTES update. Build by an Opus 5
subagent; review, run, verdicts, and docs by the session lead. Results →
`data/eval_results/convrepro_es_*.json` + RESULTS.md alongside Tier 1's.
