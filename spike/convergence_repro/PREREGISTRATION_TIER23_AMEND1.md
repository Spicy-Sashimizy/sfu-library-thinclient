# Pre-registration DRAFT — Tier-2/3 Amendment 1: classic ladder extension below 25 GB (t23c cells; bars B1x/B5x)

> **CLOSED-UNRUNNABLE 2026-09-25 — this amendment can never be frozen.**
> As of 2026-09-25 the operator has **no access to any cloud host**; the
> **OCI E5, 62 GiB, kernel 6.17.0-1018-oracle** box that every `t23c_*` cell
> below presumes is **permanently gone**, and the only host is a **31 GB
> WSL2 machine**. The cells cannot be re-hosted: the OCI two-population
> footprint is **29.1 GB = 93.9%** of that host's total RAM; a **28 GB cap
> leaves 3 GB** for the kernel, the dev container and the orchestrator while
> idle already consumes ~5 GB (31 − 5 = **26 GB < 28 GB**, so the cap is
> looser than the RAM available to fill it); and decisively, **cap 28 GB
> sits 8.6 GB above that host's own 19.4 GB footprint** — the entire 16–30 GB
> ladder below lands in its "nothing is evicted, so nothing sorts" regime,
> where every arm looks alike by construction.
>
> **Consequences, recorded:** bars **B1x/B5x** are never frozen and never
> judged; the missing `t23c_mglru_cap28g_rep2` replicate is never run (note
> that the *cell* `mglru:28:1` itself **did** run 2026-09-01 and closed
> phase B at 17/17 — `RESULTS.md` §21; what dies here is only its **rep 2**
> and the classic descent); and the 2026-09-01 verdicts **B1/B5 NOT PASSED
> on uncomputable components** and **B4 FAIL on bar arithmetic** are now the
> **permanent** record of publication-gate item 3, not an interim one.
>
> This document is retired as a **draft that was never frozen** — not as a
> failed test. Nothing in it was ever judged, so nothing in it is refuted.
> Full statement and the per-item classification:
> `docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`,
> **Addendum 2026-09-25**. The re-hostable work that survives the host loss
> is pre-registered separately in `PREREGISTRATION_WSL2_REHOST.md` (DRAFT) —
> which is **not** a replacement for this document: it asks a different
> host's version of a different question.

**Date:** 2026-09-01 · **Status:** **CLOSED-UNRUNNABLE 2026-09-25** (was:
DRAFT — NOT FROZEN). **No cells may run against this document**, and none
ever can. Freeze *would have* required: (a) the exploratory descent
executed and its rung placements recorded here, (b) bars B1x/B5x frozen —
each its own commit before any confirmatory cell. Condition (a) is
unsatisfiable as of 2026-09-25, so (b) never arrives. Everything below this
line is preserved verbatim as the design that was never run.

**Why this amendment exists.** Phase B (PREREGISTRATION_TIER23.md §7,
judged 2026-09-01) recorded **B1 and B5 NOT PASSED on uncomputable
components**: no classic rung plateaus anywhere in the frozen 25–30 GB
ladder, so the frozen cliff definition (midpoint of highest plateau rung
and lowest near-zero rung) binds to nothing on the classic side, and the
MGLRU-vs-classic displacement could only be lower-bounded (≥ ~4 GB). The
original B1/B5 verdicts stand as recorded — judged harnesses and judged
bars are never edited retroactively. This amendment defines NEW cells
(`t23c_*`) and NEW bars (B1x/B5x) that extend the classic ladder downward
until the plateau floor is bracketed.

## 1. Cells

All `t23c_*` cells use the full Tier-2/3 protocol unchanged: L0 lever
only (`SFU_SEISMIC_PREFLOOR_HOTSET=1`, per-cell `prefault_gate: "1"`
verification with quarantine-and-abort), same driver, same convergence
rule (min 3 / max 12 passes, near-zero 2,500 majflt, plateau_rel 0.1),
same arm toggle discipline, any-date SKIP resume.

**Exploratory descent (single cells, run first):** classic at
**24 / 22 / 20 / 18 / 16 GB**, descending, stopping early once a plateau
rung and its adjacent near-zero rung are identified at 2 GB resolution,
then bisecting to 1 GB. Rung placement may be informed by the
archived smallmachine_levers phase A′ L0 cells (classic 18 and 14 GB, running
2026-09-01 under the sml protocol — corroborating context only; sml cells
are named to a different spike and are excluded from every t23 bar).

**Confirmatory bracket (after freeze):** the highest classic plateau rung
and the lowest adjacent near-zero rung, **×2 replicates each** (rep 1 may
be the descent cell itself if its rung survives bisection — recorded
either way). Plus **`t23c_mglru_cap28g_rep2`**: the MGLRU plateau rung's
second replicate, so both cliffs rest on replicated boundary cells.

## 2. Pre-declared alternative outcome (bind the reading now)

It is possible classic **never plateaus above the hot-set floor** (hot set
13.76 GB + ~1.0 GB anon ≈ 14.8 GB, measured): every rung ≥ ~16 GB may
converge via a violent pass-1 sort exactly as 25 GB did. If the descent
reaches 16 GB with no plateau, the recorded outcome is: classic cliff =
the hot-set floor bracket (lowest converging rung, floor), displacement
measured against that bracket (≈ 28.5 − ~15 ≈ **~13–14 GB**, direction
MGLRU-upward), and B1x's plateau clause is judged against the deepest
rung run with the note that classic's plateau regime coincides with the
can't-fit floor. This reading is bound BEFORE any cell runs so it cannot
be post-hoc.

## 3. Bars (TO BE FROZEN after the descent — drafted intent)

Judged over `t23b_*` ∪ `t23c_*` classic cells (and `t23b_*`/`t23c_*`
MGLRU cells for B5x). Tier-1b lessons apply (no strict-monotone clauses,
±16% noise floor, named cells + denominators).

- **B1x (classic regimes):** classic cliff = midpoint(highest plateau
  rung, lowest near-zero rung); every rung ≥ cliff+2 GB converges
  near-zero ≤ 4 passes; every rung ≤ cliff−2 GB (if any exist above the
  hot-set floor) plateaus ≥ 10× the near-zero threshold; both boundary
  rungs replicated ×2 with both replicates classifying identically.
- **B5x (displacement):** |MGLRU cliff − classic cliff| at 1 GB
  resolution, both cliffs' boundary rungs replicated ×2 with identical
  classification; direction and magnitude recorded whichever way they
  fall (MGLRU cliff = 28.5 GB already measured; its plateau rung gains
  rep 2 here).

## 4. Non-interference & windows

N1–N6 of PREREGISTRATION_TIER23.md §3 adopted verbatim; N7 trial horizon
(windows after 2026-09-03 need the post-trial billing decision); N8-style
per-cell gate verification as in the t23b orchestrator. Budget: descent
≈ 5 cells — deep classic cells may run long if they do plateau (plateau
detection cuts at 5–7 passes; est. 20–45 min/cell) — one ~2 h window;
confirmatory bracket ≈ 4–5 cells, one more window. Orchestrator: t23b
clone with `t23c_` naming and the descent list (own commit at freeze).

## 5. Efficacy recording

Per CLAUDE.md: cells in `data/eval_results/t23c_*.json` (committed);
verdicts + numbers + dates appended to `RESULTS.md` (Tier-2/3 block) and
the 04_CONVERGENCE_ARTIFACT.md addendum chain in the same push; the
superseding relationship (B1/B5 recorded → B1x/B5x measured) stated
explicitly wherever either is quoted.
