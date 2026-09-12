# Pre-registration DRAFT — Tier-1c: residency-seeded synthetic on a real Linux / MGLRU host

**Date:** 2026-09-03 · **Status: DRAFT — bars NOT frozen.** Freeze requires one
calibration window (§4) recorded here, then the inversion bar (§5) frozen in its
own commit before any confirmatory cell. The harness (`t1c_cell.py`) and
orchestrator (`t1c_host_orchestrator.sh`) are built and the soundness identity
is validated (§3); the *design* is on trial here, not the code.

## 1. Why Tier-1c (what Tier-1 and Tier-1b established)

- **Tier-1 (L→R load): OVERALL FAIL** — the load pre-sorted R to 100% resident,
  so no transient could exist (RESULTS.md §2).
- **Tier-1b (interleaved load + R→L order arm): OVERALL FAIL, informatively.**
  Load order is the initial-state selector (the §14 triptych: L→R no-transient /
  interleaved decaying / R→L rising), and the interleave produced a genuine
  partial-residency start (R 92.3 / 84.8 / 55.0 / 40.0% down the ladder). Yet the
  real system's non-monotonic **inversion** still did not appear on ANY metric:
  fixed-window convergence was **deficit-dominated** (trajectories self-similar,
  scaled ×1.98 by initial deficit; pressure-scaled aging only ~10%/pass, second
  order). Measured inversion ratio 0.04× vs a predicted 2–20× (RESULTS.md §§8–11).
- **Two things the synthetic has NEVER had** (publication-gate items 2–3, still
  open): it has only ever run on a **WSL2 classic-LRU** kernel with `lru_gen`
  **absent** (`# CONFIG_LRU_GEN is not set`, confirmed 2026-09-03), and its
  initial state was always a *load-order side effect*, never a direct target.

RESULTS.md §16 names the next experiment precisely: *"measure the real stack's
post-load residency profile and reproduce that as the synthetic's initial state,
rather than continuing to guess at load orders."* Tier-1c does that, on the OCI
serve box — a real Linux 6.17 host where MGLRU **is** available and memory caps
**are** enforceable (the only such host we have; local WSL2 can do neither).

## 2. The design change (the Tier-1c move)

`t1c_cell.py` sets R's pass-1 residency **directly** to a target fraction,
decoupled from load order: on a cold file it warms only a seeded-random
`frac × |R|` subset (MADV_RANDOM ⇒ no readahead ⇒ the untouched `(1−frac)` pages
stay non-resident and take one MAJOR fault each on first touch in pass 1). This
makes two knobs **independent** for the first time:

- **deficit** = `(1 − frac)` — the initial non-resident fraction of R;
- **cap** = the cgroup `MemoryMax` under which the repeat passes run.

Tier-1b conflated them (the cap determined the deficit via the load). Tier-1c can
hold the cap fixed and sweep the deficit, or hold the deficit fixed and sweep the
cap. Metric = **majflt** per pass (kernel-measured, `/proc/self/stat`; RESULTS.md
§11 established it as the clean graded metric and it is immune to Python
overhead). Per-pass wall time is recorded but is NOT the fio clat.

**Arms:** `classic` (`lru_gen=n`) and `mglru` (`lru_gen=0x0007`), set per cell by
the orchestrator — the first time the synthetic runs on MGLRU at all.

## 3. Soundness identity (built-in, checked every cell)

Uncapped, pass-1 majflt MUST equal the seeded deficit (one major fault per
missing page, nothing evicts resident pages without a cap). `t1c_cell.py`
records `soundness_pass1_majflt_eq_deficit`; the orchestrator quarantines any
cell where it is false. **Validated 2026-09-03** on the dev container (uncapped,
R=256 MiB, frac=0.90): seeded 89.9994% resident, pass-1 majflt **6554 =** deficit
**6554**, passes 2–5 majflt 0. Harness is sound before any capped cell runs.

## 4. Calibration window (exploratory, single cells; bars NOT frozen yet)

`t1c_host_orchestrator.sh`, OCI box, one ~90 min window. R=5 GiB, L=1.75 GiB
(Tier-1b sizes), 12 passes, `CELL_TIMEOUT=900`. Default matrix (priority order):

`mglru:92:8 classic:92:8 mglru:85:8 classic:85:8 mglru:92:6 classic:92:6`
(`arm:fracPct:capGiB`). Questions:

1. **The inversion question, both arms, at an UNPRESSURED cap (8 G > R+L).**
   Two deficits (marginal 8% vs boundary 15%) with the cap large enough that R
   fits once faulted — isolates recovery-rate from ongoing eviction pressure.
   Does the smaller-deficit cell converge *slower* in a fixed 3-pass window
   (inversion) on EITHER arm? Tier-1b said no on classic/WSL2; MGLRU is the new
   variable, and Tier-2/3 measured MGLRU as the arm that "never re-promotes
   refaulting pages" — precisely the asymmetry that could produce non-monotonic
   behaviour.
2. **Cliff confirmation at a PRESSURED cap (6 G < R+L).** Both arms thrash?
   Does MGLRU thrash differently from classic (the sml arm-asymmetry finding,
   PREREGISTRATION_SMALLMACHINE run 3, predicts it will)?

Facts land in a dated section here; rungs/fractions may be adjusted **once**,
recorded, before freeze (same one-shot rule as every prior tier).

### Calibration run 1 (2026-09-03 01:30–02:22 UTC) — harness validated; matrix MIS-CALIBRATED (cap never pressured); inversion UNTESTED

Full 6-cell matrix DONE, clean RESTORED (scratch removed, lru back to 0x0007,
demo healthy). **First time the synthetic ever ran on MGLRU.** Results
(`data/eval_results/t1c_{arm}_frac{92,85}_cap{8,6}g_seed1729_20260903.json`):

| arm | frac | cap | deficit (pages) | majflt/pass | conv |
|---|---|---|---|---|---|
| mglru | 0.92 | 8G | 104,858 | 104858, 0, 0, … | @2 |
| classic | 0.92 | 8G | 104,858 | 104858, 0, 0, … | @2 |
| mglru | 0.85 | 8G | 196,608 | 196608, 0, 0, … | @2 |
| classic | 0.85 | 8G | 196,608 | 196608, 0, 0, … | @2 |
| mglru | 0.92 | 6G | 104,858 | 104858, 0, 0, … | @2 |
| classic | 0.92 | 6G | 104,858 | 104858, 0, 0, … | @2 |

Soundness identity holds on all 6 (pass-1 majflt == seed deficit exactly;
104858 = 8.0% × 1,310,720, 196608 = 15.0%). **But every cell is pure one-pass
deficit-decay with zero arm difference — because the cap was never pressured.**
The repeat passes touch ONLY R (5 GiB); R fits under both the 8 G and the 6 G
cap, so once the seeded deficit is faulted in nothing is ever evicted and pass 2
is trivially zero. The "pressured" 6 G cap is not pressured relative to R alone
(R = 5 G < 6 G), and L (1.75 G) is laid down but never warmed, so it never
competes. **The inversion (T1c-1) and arm-asymmetry (T1c-2) questions were not
tested by this matrix — they require ongoing inter-pass eviction of R, which
this cap scheme never induced.** This reproduces Tier-1b's unpressured-cap
behaviour exactly (pass1 = deficit, pass2 = 0), now confirmed on a real Linux
host and on MGLRU: with no eviction pressure both arms are identical, as
expected.

**One-shot design correction (bound here, before freeze).** To induce the
eviction pressure the artifact needs, the cap must bind on R itself. The
faithful, arm-discriminating regime is **cap < |R|** (so R cannot fully fit
regardless of L or seed, and every pass must re-fault the shortfall): this is
where classic LRU's refault-activation (re-promotes the hot subset → a lower
steady floor) and MGLRU's "never re-promotes refaulting pages" (→ sustained
thrash) diverge — the Tier-2/3 / sml arm asymmetry, at synthetic scale.
Convergence is therefore redefined for this regime as **the steady majflt
FLOOR** (not zero): T1c-2 becomes "MGLRU's steady floor ≥ classic's by a
magnitude-weighted margin". Calibration run 2 matrix (caps below R = 5 G, one
seed, both arms): `classic:92:4 mglru:92:4 classic:92:4.5 mglru:92:4.5
classic:92:3.5 mglru:92:3.5`. The seeded deficit is now the transient only;
the steady floor is the graded metric. (T1c-1's zero-crossing inversion needs a
marginal regime where convergence-to-zero is still possible but paced, which a
single-file R-only repeat cannot sustain without L competing in-loop; deferred
to a Tier-1d note, not chased here.)

### Calibration run 2 (2026-09-03 02:34–04:08 UTC) — pressured cap achieved; NO arm asymmetry; cause is access structure, not the LRU arm

Corrected matrix (caps below |R|=5 G), both arms, frac 0.92, seed 1729. Clean
RESTORED. All 6 cells **TIMED OUT** (FAIL 124, no JSON): under cap < R the cell
never reaches near-zero, so it runs the full 12 passes, and at ~100–280 s/pass
that exceeds the 900 s cell cap — same "evidence lives in the per-pass logs, not
a JSON" shape as sml run 4 (logs committed, `_t1c_*_seed1729_20260903.log`).
The pressure regime WAS achieved this time: R residency stabilises at the
cap-implied fit and stays there, and every pass re-faults the shortfall.

| cap | arm | steady R resident | majflt (pass 1 → …) |
|---|---|---|---|
| 4.0 G | classic | ~78.1 % | 487,776 → 559,084 |
| 4.0 G | mglru | ~77.7 % | 496,746 → 568,180 |
| 4.5 G | classic | ~88.1 % | 263,314 → 302,794 → 310,356 → 309,215 |
| 4.5 G | mglru | ~87.7 % | 272,193 → 313,015 → 320,907 → 312,155 |
| 3.5 G | classic | ~68.2 % | 712,771 → 575,633 |
| 3.5 G | mglru | ~67.7 % | 721,937 (1 pass before timeout) |

**Result — the predicted arm asymmetry (T1c-2) does NOT appear.** At every cap,
classic and MGLRU stabilise at the *same* cap-bound residency (78 / 88 / 68 %,
tracking cap/|R|) and thrash to *near-identical* majflt floors: MGLRU/classic =
1.016 (4 G, pass 2), 1.034 (4.5 G, pass 2), 1.013 (3.5 G, pass 1) — a 1.3–3.4 %
spread, far inside the ±16 % noise floor. Both arms plateau (4.5 G: classic
~310 k, mglru ~317 k), neither converges toward zero, neither "re-promotes" a
hot set the other cannot. **On a real Linux host with MGLRU genuinely engaged,
the two arms are equal within noise under a pressured cap.**

**Reading — the cause is ACCESS STRUCTURE, not the LRU arm.** The synthetic's
repeat is **uniform-random over a single file**, so there is no hot subset for
classic's refault-activation to protect: every R page is equally warm, so once
the 5 G working set exceeds the cap the shortfall must miss every pass
regardless of arm. The Tier-2/3 real-stack asymmetry (classic re-sorts via
refault-activation, MGLRU never re-promotes) needs a **skewed** access
distribution — a stable hot subset that fits under the cap while a cold tail
churns — which a uniform single-file repeat structurally lacks. This is exactly
the residual candidate RESULTS.md §16 named ("the real index's access structure
— skewed, structured, fault-around active — differs in exactly the ways that
would matter"). Tier-1c thus **closes the LRU-arm hypothesis with a negative
result** and localises the remaining cause to access skew.

**Harness note (recorded):** the soundness identity (pass-1 majflt == seed
deficit) holds ONLY uncapped, as §3 states — under cap < R, pass-1 majflt
(e.g. 487,776) exceeds the seed deficit (281,173) because faulting the deficit
evicts already-resident pages within the same pass (the thrash). The
orchestrator's soundness gate is therefore an **uncapped-cell** check; capped
cells are judged on the majflt-floor trajectory, not the identity. No code
change needed — capped cells time out and write no JSON, so the gate never
mis-fires — but a future confirmatory Tier-1c run wanting a *written* steady
floor must raise CELL_TIMEOUT (≥ ~2500 s at 4 G) or cut max-passes, and gate
soundness only on uncapped arms.

**Tier-1c verdict (both calibration runs): publication-gate item 1 remains a
NEGATIVE result, now on a real MGLRU host.** Load order (1b) sets the initial
state but does not create the inversion; a genuinely pressured cap on MGLRU
(1c) does not create the asymmetry. The one untested variable is **access
skew** — a Tier-1d (skewed/zipfian repeat, or the real index's measured access
histogram) requiring its own pre-registration. Bars §5 are NOT frozen; T1c-2 is
judged FAIL-as-drafted by run 2 (arms equal within noise) and T1c-1 was never
reachable in the uniform-access design.

## 5. Bars (TO BE FROZEN after §4 — drafted intent only)

- **T1c-1 (inversion, per arm):** at the unpressured cap, comparing marginal vs
  boundary deficit, the smaller-deficit cell reaches near-zero (majflt ≤ 2500) in
  *more* passes than the larger-deficit cell — i.e. recovery-rate-dominated, not
  deficit-dominated. Pre-declared: **classic is expected to FAIL this** (Tier-1b
  result reproduced on a real host = the harness-portability control); **MGLRU is
  the live hypothesis.** If neither inverts, the artifact is not an LRU-arm
  effect and the remaining candidates are access structure / fault-around (a
  Tier-1d, out of scope here).
- **T1c-2 (arm asymmetry at the cliff):** at the pressured cap, MGLRU's steady
  majflt ≥ classic's by a magnitude-weighted margin (the sml prediction), both
  seeds. Denominator + margin frozen at §4.
- **T1c-3 (soundness, non-negotiable):** every judged cell has
  `soundness_pass1_majflt_eq_deficit = true`. (A gate, not a finding.)

## 6. Non-interference (adopt the sml/​Tier-2-3 window discipline verbatim)

N1–N8 as in PREREGISTRATION.md §3 / the sml pre-reg: single-live-instance lock
(`/run/t1c-orch.lock`), apt-timer freeze + trap-restore, `sfu-serve` stopped for
a quiet page cache and restored in the trap, `lru_gen` restored to `0x0007` on
exit, priority-ordered CELLS shed at `WINDOW_DEADLINE_S`, any-date SKIP resume,
per-cell protocol verification (§3 soundness + `protocol==tier1c`). Additional:
the R/L scratch (`data/t1c_scratch`, ~6.75 GiB) is created at window start and
**removed in the trap** — it never touches `data/seismic_150m/` (irreplaceable,
read-only) and is not committed. N7 trial-horizon note: OCI trial ended
2026-09-03; a window after that requires the post-trial billing decision first.

## 7. Efficacy recording (per CLAUDE.md)

Cells → `data/eval_results/t1c_*.json` (committed). Verdicts + numbers + absolute
dates → a Tier-1c section of RESULTS.md. If MGLRU reproduces the inversion, that
is the publication-gate item-1 result and goes to `docs/THIN_CLIENT_SWAP.md`
(the deployment-facing conclusion) in the same push; if it does not, that is an
equally-recorded negative result narrowing the cause to access structure.
Unmeasured bars stay marked DRAFT until §4 runs.
