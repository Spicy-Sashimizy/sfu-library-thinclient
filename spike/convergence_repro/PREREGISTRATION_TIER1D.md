# Pre-registration — Tier-1d: access SKEW (the variable Tier-1c isolated)

**Date:** 2026-09-03 · **Status: BARS FROZEN 2026-09-05 (§5) for
S-skew/S-capband/S-skewsweep/S-faultaround/S-inversion; S-realprofile (§3.6)
severed pending §6 gap 3. Judged cells may now run — fresh seeds {2027, 8128}
only.** Freeze conditions were: (a) the gaps in §6 closed — gaps 1, 2, 4
CLOSED 2026-09-05; gap 3 (real-access-histogram probe) OPEN, blocking only
S-realprofile, which freezes by amendment when the probe exists; (b) one
calibration window (§4) recorded here — DONE 2026-09-05, see §4; (c) bars (§5)
frozen in their own commit — THIS COMMIT (user decision 2026-09-05: freeze on
the measured rungs; the §4 one-shot rung adjustment lapsed unspent). **N7 (trial horizon): Tier-1d's runs moved LOCAL (WSL2, HOST_RUN.md
T1d-0, commit `0e03a470`) — no OCI window is used, so N7 now binds only gap 3's
OCI-side probe, which stays behind the user's post-2026-09-03 billing decision.**

## 1. Why Tier-1d (what Tier-1c isolated)

Across three tiers the synthetic never reproduced the real stack's non-monotonic
artifact or its LRU-arm asymmetry:

- **Tier-1** (L→R load): FAIL — load pre-sorts R to 100% resident, no transient.
- **Tier-1b** (interleaved load, uniform-random repeat): FAIL — fixed-window
  outcome is deficit-dominated; no inversion on any metric.
- **Tier-1c** (residency seeded directly, real Linux + MGLRU, pressured cap):
  FAIL — classic and MGLRU thrash to **near-identical** majflt floors
  (MGLRU/classic 1.013–1.034, inside ±16% noise) at every sub-|R| cap. Cause
  **localised to access structure**: a uniform-random repeat has no hot subset
  for classic's refault-activation to protect, so once R exceeds the cap the
  shortfall must miss every pass regardless of LRU arm.

**The single untested variable is ACCESS SKEW.** The real seismic index is not
touched uniformly — a minority of postings/pages carry the majority of query
traffic. Tier-2/3 measured, on the real stack, exactly the mechanism a hot
subset would drive: **classic re-sorts via refault-activation** (stabilises the
hot set) while **MGLRU never re-promotes refaulting pages** (the hot set keeps
churning). Tier-1d introduces skew into the synthetic repeat and tests whether
that mechanism — hence the arm asymmetry and the non-monotonic transient — now
appears. This is the last synthetic variable before either the artifact
reproduces index-independently or the negative result is final and the write-up
reframes permanently around "requires the real index's access structure."

## 2. The design change

Extend `t1c_cell.py` (→ `t1d_cell.py`, or a `--skew` mode) so the repeat pass
draws page touches from a **skewed distribution** over R instead of a uniform
one-touch-per-page permutation:

- **hot-set model (primary):** partition R into a hot fraction `h` and a cold
  tail `1−h`; draw touches so the hot set receives mass `m` of accesses (e.g.
  `h=0.20, m=0.80` — 20% of pages get 80% of touches). Per-pass touch count
  fixed (= |R| pages' worth of touches) so pass cost is comparable to Tier-1c.
- **zipfian arm (alternative):** touches ~ Zipf(s) over a seeded page ranking;
  `s` sweeps skew strength. (One of the two parameterisations is chosen at
  calibration; both are seeded-deterministic.)

Metric unchanged: **majflt per pass** (kernel-measured, graded — RESULTS.md §11).
Determinism preserved by seeding the ranking and the draw. Arms unchanged:
`classic` (`lru_gen=n`) and `mglru` (`lru_gen=0x0007`), set by the orchestrator.

Crucially, skew makes a **third memory regime** exist that uniform access did
not: `hot-set < cap < |R|`. Under it a hot subset that *fits* can be protected
while the cold tail churns — the precondition for arm divergence.

## 3. Test situations (arms) — the "few useful scenarios"

Each is a pre-registered situation; the calibration window (§4) places the exact
rungs.

1. **S-skew (primary, the mechanism test):** fixed skew (`h=0.20`), cap in the
   critical band `hot-set < cap < |R|` (so the hot 20% ≈ 1 GiB fits with room
   while full R = 5 GiB does not), both arms. **Prediction:** classic converges
   toward a low majflt floor (hot set activates and survives); MGLRU stays at a
   high floor (refaulting hot pages never re-promoted). If the floors diverge
   by a large margin, the arm asymmetry is reproduced index-independently.

2. **S-skewsweep (threshold):** vary `h ∈ {0.05, 0.10, 0.20, 0.40}` (or Zipf `s`)
   at the critical cap, one arm-pair each. Finds the **minimum skew** at which
   the asymmetry emerges — useful in itself (how skewed must traffic be before
   MGLRU hurts?), and it brackets where the real index sits.

3. **S-capband (regime bracket):** fixed skew, three caps — `cap > |R|` (control,
   both converge in 1 pass, reproduces Tier-1c run 1), `hot-set < cap < |R|`
   (the divergence band), `cap < hot-set` (both thrash, reproduces Tier-1c run 2).
   Confirms the divergence is specific to the middle regime, not an artifact.

4. **S-faultaround:** the critical cell with `MADV_NORMAL` (readahead / fault-
   around ON) vs `MADV_RANDOM` (OFF). The real stack does no `fadvise` and gets
   fault-around; if hot pages are also *spatially* clustered, fault-around
   compounds the hot-set advantage. Tests whether spatial clustering matters
   independently of frequency skew (a documented BUILD_NOTES difference from the
   real stack).

5. **S-inversion (the non-monotonic transient):** at the critical cap with skew,
   seed two initial deficits and window at a fixed pass. With a hot set now
   present to re-sort, does the fixed-window **inversion** (smaller initial
   deficit converges in *more* passes) finally appear — the real-stack signature
   Tier-1b/1c could not produce — or is it still deficit-dominated? Recorded
   whichever way.

6. **S-realprofile (bridges to the SML 16 GB question — needs §6 gap 3):** seed
   R's initial residency AND the access ranking from the **measured** seismic
   index page-access histogram, at a cap scaled to the real ragged edge, run
   **N=10 replicates**. Directly probes why the real 16 GB SML cell flips
   converge/thrash (see the sml pre-reg): if the real skew + a near-critical cap
   produces a bimodal converge/thrash split in the synthetic, that *is* the
   mechanism of the 16 GB non-determinism, reproduced cheaply. (This situation
   is the explicit tie to the small-machine line; its rung is derived from the
   sml floor bracket 14–16 GB, not from |R|.)

## 4. Calibration window (exploratory; bars NOT frozen)

`t1d_host_orchestrator.sh` (a t1c clone: native systemd-run cap + lru arm, sml
window discipline — lock, apt-guard, sfu-serve stop/restore, trap, scratch
cleanup, any-date SKIP). One ~90 min window, R=5 GiB, L=1.75 GiB. Purpose: place
`h`/`s`, place the critical cap (measure the hot-set residency under candidate
caps), and confirm a cell completes inside a raised `CELL_TIMEOUT` so a **written
JSON steady floor** exists (Tier-1c's lesson: cap<|R| cells time out at 900 s;
Tier-1d converging cells should finish, but budget ≥1800 s). Adjust rungs **once**,
record here, before freeze.

### §4 RECORD — window run 2026-09-05 (WSL2 local, "SEC-4")

**Where and how (deviation from the paragraph above):** run **locally on the
user's WSL2 box**, not the OCI box — Tier-1d's scope moved local in HOST_RUN.md
T1d-0 (`0e03a470`), and the orchestrator is the local variant
`t1d_wsl2_orchestrator.sh` (§6 gap 4; landed `7e0eb51f`, MGLRU-boot-assumption
fix `79cf8a04`), launched from a host-ops session via `systemd-run` in the
Ubuntu distro with a `wsl.exe` keep-alive client holding the distro.
Environment: `.wslconfig` experiment profile (memory=56GB fixed, processors=8,
`pageReporting=false`, kernel v6), fresh `wsl --shutdown` boot before the
window. Evidence: raw cells `data/eval_results/t1d_*_seed1729_20260905.json`
(committed `9ac830a3`); runlogs/statuses + the host-ops report
`data/eval_results/_t1d_SEC4_report_20260905.md` (committed `3cf39d7c`).

**Step A — soundness/control gate (`STRICT_SOUNDNESS=1`, cap 8 GiB > R+L
6.75 GiB): CLEAN.** Both arms `soundness_pass1_majflt_eq_deficit: true`
(reachable deficit 39,031 == pass-1 majflt, identity kind
`skew_reachable_deficit`), trajectories bit-identical across arms
(39,031 → 1,206 over 12 passes, `converged_first_pass: 10`), hot_touch_frac
0.7996 ≈ m. S-capband `cap > |R|` control point: MGLRU/classic floor ratio
**1.000**.

**Step B — the T1d-6 matrix exactly as proposed** (seed 1729,
`hotset:0.20:0.80`, frac92, 12 passes, `CELL_TIMEOUT=1800 s`): all six cells
finished (max wall 890 s), every JSON written, all arm toggles asserted,
`RESTORED: lru_gen=0x0007` on both windows, no RESIDUE / ARM TOGGLE / shed.
Steady floor = mean majflt of the last 3 passes:

| cap | classic floor | mglru floor | MGLRU/classic | regime reading |
|---|---|---|---|---|
| 4.0 GiB | 105,444 | 109,369 | 1.037 | inside Tier-1c's uniform band (1.013–1.034) — skew alone does not move the already-measured cap |
| 2.5 GiB | 222,994 | 263,316 | 1.181 | marginal — just above the ±16% noise floor; classic's floor is noisy (last-6 range ~170k–270k) |
| 1.5 GiB | 334,614 | 482,621 | **1.442** | **the divergence rung**: classic descends 521k → ~335k (refault-activation stabilises the hot set); MGLRU pins at ~483k from pass 2 (hot-set churn) |

**Calibration readouts (HOST_RUN.md T1d-7):**

1. **The predicted regime structure is real and the divergence is
   regime-specific** — this is the first synthetic appearance of the Tier-2/3
   arm asymmetry in four tiers. T1d-6's risk note for the 1.5 GiB rung
   (possible slide into `cap < hot-set`, both-arm thrash) did **not**
   materialise: the arms separate rather than co-thrash, and nothing timed out.
2. **Critical cap placed at 1.5 GiB** (band centre 2.5 GiB is nearly flat —
   the divergence needs the cap tight against the hot set + driver anon).
   Whole-R residency at 1.5 GiB ~28% both arms.
3. **Readout 4 (hot-set residency) was NOT captured** — the window's JSONs
   carry only whole-R `resident_pct`. Harness gap closed post-window in
   `b3a9377a` (per-pass `hot_resident_pct` + post-seed value; validated
   uncapped, uniform regression trajectory-identical). The judged window
   will carry it; the calibration's placement of the critical cap therefore
   rests on the floor structure, not on a measured hot-set residency.
4. `CELL_TIMEOUT=1800 s` confirmed sufficient (max wall 890 s; Tier-1c's
   truncation did not recur). No change needed.
5. Skew draw matches h/m every pass (hot_touch_frac 0.7996–0.8002 across all
   cells; Step A histogram hot mean 4.00 vs cold 0.25 touches/page).

**The ONE allowed rung adjustment: UNSPENT as of this record.** Its
disposition (spend on a sharper-divergence probe vs. freeze on the measured
rungs) is recorded with the §5 freeze, per T1d-7's "§5 bars are frozen in
their own separate commit, after that".

**Deviations and validity notes:**

1. First Step A attempt died at t+15 s to WSL distro idle-termination (before
   the keep-alive client existed); the trap RESTORED cleanly, no artefacts
   (runlog 13:07). Host-side mechanics are in the host-ops session's notes
   (outside this repo); the substance is in the committed SEC-4 report.
2. **pageReporting caveat.** With `pageReporting=false` verifiably applied
   (the VM size change to 56GB proves `.wslconfig` was read), dmesg still
   prints `Free page reporting enabled` at boot. Session-lead ruling
   2026-09-05: recorded as a **standing environment caveat on every Tier-1d
   WSL2 cell, not an invalidation** — the `cap > |R|` control behaves exactly
   (ratio 1.000, identity exact, bit-identical arms) and the 4.0 GiB cell
   lands inside Tier-1c's uniform band, so any balloon interference sits
   below the readout's noise floor at these rungs. Any judged bar that lands
   within its own margin of the threshold MUST cite this caveat.
3. All claudebox containers (~16, incl. the production stacks) were left
   RUNNING during both windows, per instruction. Suspected attributable
   noise: the pass-11/12 uptick at 4.0 GiB (both arms, ~89k → ~131–135k) and
   the classic 2.5 GiB floor spread. Neither touches the 1.5 GiB reading
   (classic's last-6 there spans 328k–341k; MGLRU's 482k–484k).
4. The checkout the window ran from was not pulled pre-run (git blocked in
   the host-ops session); verified post-`79cf8a04`/`67a282fd` by content.
   `9ac830a3` and this record were pushed from the dev-container session.

## 5. Bars — FROZEN 2026-09-05 (this commit; no edits after this point)

**Freeze scope:** S-skew, S-capband, S-skewsweep, S-faultaround, S-inversion
(§3.1–3.5). S-realprofile (§3.6) is SEVERED — it freezes by amendment when §6
gap 3 closes. **The §4 rung adjustment LAPSED UNSPENT** (user decision
2026-09-05: freeze on the measured rungs rather than probe for a larger
effect). The drafted ≥2× intent for T1d-1 is replaced by a calibrated
threshold: the calibration placed the divergence at 1.442× with within-arm
floor spreads <2%, so the frozen bar sits outside the ±16% noise floor with
margin below the measured point. Judged cells use **fresh seeds {2027, 8128}**
— seed 1729 is calibration-burned and may corroborate but never satisfy a bar.

**Definitions (all bars):** steady floor = mean majflt of the last 3 of 12
passes; ratio = MGLRU floor / classic floor at the same cap+seed;
`near_zero = 2500` (driver default). Judged matrix, in shed-priority order
(the T1d-6 discipline; ~90 min window, `CELL_TIMEOUT=1800 s`):

| # | cells | purpose |
|---|---|---|
| 1–4 | `{classic,mglru}:92:1.5:{2027,8128}:hotset:0.20:0.80` | T1d-1/T1d-1b, both replicates |
| 5–6 | `{classic,mglru}:92:8:2027:hotset:0.20:0.80` | T1d-3 control (`cap > \|R\|`), `STRICT_SOUNDNESS=1` |
| 7–8 | `{classic,mglru}:92:4:2027:hotset:0.20:0.80` | T1d-3 upper band |
| 9+ | if the window allows: `h ∈ {0.05,0.10,0.40}` pairs at 1.5 GiB seed 2027 (T1d-2); a `cap=0.75` GiB pair (sub-hot-set, recorded); a `--fault-around` pair at 1.5 GiB (S-faultaround, recorded); S-inversion cells | recorded, not pass/fail |

- **T1d-1 (headline, PASS/FAIL):** at cap 1.5 GiB, `hotset:0.20:0.80`, frac92:
  ratio ≥ **1.30** in **both** replicates (seeds 2027 AND 8128). PASS = the
  real-stack arm asymmetry reproduced index-independently (publication-gate
  item 1); FAIL = the negative result is final and the write-up reframes
  around real-index access structure. Calibration point: 1.442 at seed 1729.
- **T1d-1b (mechanism shape, PASS/FAIL):** in both T1d-1 replicates:
  (i) classic's steady floor ≤ **0.75×** its own pass-1 majflt (the descent —
  refault-activation is doing work; calibration 0.641); (ii) every MGLRU pass
  2–12 majflt within **±5%** of the MGLRU pass-2–12 mean (pinned churn;
  calibration max dev +1.3%). If T1d-1 passes but T1d-1b fails, T1d-1 stands
  and the mechanism attribution is downgraded to "recorded, shape untested".
- **T1d-2 (skew threshold, recorded whichever way):** the smallest
  `h ∈ {0.05, 0.10, 0.20, 0.40}` at which T1d-1's ratio clause holds at
  1.5 GiB. No pass/fail; brackets where the real index would need to sit.
- **T1d-3 (regime specificity, PASS/FAIL):** at seed 2027: cap 8 GiB — both
  arms converge (steady floor ≤ `near_zero`) and ratio within **[0.84, 1.16]**
  (calibration 1.000); cap 4.0 GiB — ratio ≤ **1.20** (calibration 1.037,
  Tier-1c uniform band 1.013–1.034). PASS = the divergence is specific to the
  tight-cap rung, not an arm artifact. The sub-hot-set (`cap < hot-set`) cell
  is recorded-only: that regime was not calibrated.
- **T1d-4 (non-monotonic transient, recorded whichever way):** S-inversion at
  1.5 GiB classic, two seeded deficits (frac92 vs frac70), fixed pass-3
  window: the inversion either appears or the outcome is recorded as
  deficit-dominated. No pass/fail (Tier-1b's lesson: this shape resists
  synthetic bar arithmetic).
- **T1d-5 (soundness, uncapped-only gate, VALIDITY):** every uncapped cell in
  the judged window must satisfy the **reachable** identity
  (`soundness_pass1_majflt_eq_deficit: true`; §6 gap 1's refinement). A window
  whose control cells fail this is INVALID in toto — no bar may be judged
  from it. Capped and `--fault-around` cells are judged on floor trajectories,
  never the identity.
- **Readout, not a bar:** per-pass `hot_resident_pct` (landed `b3a9377a`,
  after the calibration window — no calibrated value exists, so it grades
  nothing). Expected shape if the mechanism is as claimed: classic hot-set
  residency rises toward ~100% at 1.5 GiB while MGLRU's stays depressed;
  recorded into the write-up either way.
- **Caveat citation rule:** any bar whose judged value lands within ±16% of
  its threshold must cite the §4 pageReporting caveat in the verdict.

## 6. Gaps to close before freeze (each its own commit)

1. ~~**Skew harness**~~ — **CLOSED 2026-09-05** (`spike/convergence_repro/t1d_cell.py`,
   a t1c_cell.py derivative: same laydown, same direct residency seed, same
   MADV_RANDOM, same per-pass majflt from `/proc/self/stat`; protocol tag
   `tier1d`). `--skew hotset:h:m` and `--skew zipf:s`, both seeded-deterministic
   (ranking from `seed ^ 0x5EAB1D`, per-pass draw from `(seed, pass)`); no
   `--skew` = uniform Tier-1c behaviour. Per-pass touch count fixed at |R| pages'
   worth. JSON records skew params, hot-set pages/bytes/MiB, per-pass majflt and
   `hot_touch_frac`, and a pass-1 touches-per-page histogram.

   **Validation** (this dev container, UNCAPPED, R=256 MiB = 65,536 pages,
   L=64 MiB, `--resident-frac 0.90`, seed 1729, 6 passes, `--self-check`;
   `data/eval_results/t1d_validation_*_r256_frac90_seed1729_20260905.json`):

   | cell | seeded deficit | pass-1 reachable deficit | pass-1 majflt | identity |
   |---|---|---|---|---|
   | uniform (no `--skew`, regression) | 6,554 | 6,554 | **6,554** | exact, full Tier-1c form (then majflt 0 on passes 2-6) |
   | `hotset:0.20:0.80` | 6,554 | 2,470 | **2,470** | exact |
   | `zipf:1.1` | 6,554 | 1,181 | **1,181** | exact |

   *Identity refinement (recorded, not a waiver):* a fixed-count skewed draw
   **cannot** cover every page — covering N pages costs N touches, so with
   `m=0.80` on `h=0.20` the cold tail gets 0.25 expected touches/page. The
   Tier-1c identity is therefore evaluated over the pages pass 1 actually
   reaches (`pass1_reachable_deficit_pages`, JSON field
   `soundness_pass1_majflt_eq_deficit`, the field the orchestrator gates on);
   the strict full-deficit form is kept alongside as
   `soundness_pass1_majflt_eq_full_deficit` and is `true` only in uniform mode.
   T1d-5 should be read in the reachable form for skewed cells.

   **Draw histogram vs target** (`hotset:0.20:0.80`, pass 1, tolerance stated
   in advance of the numbers: hot mass within **±0.005 absolute** ≈ 3.2σ of the
   binomial draw at N=65,536, per-page mean touch rates within **±1%**):
   hot set 13,107 pages / 51.199 MiB (target 20.000% of R → 19.9997%);
   hot mass **0.800446** vs 0.80 (dev +4.5e-4 = **0.29σ**, all six passes in
   0.79698-0.80045, max dev 1.9σ); hot mean **4.0023** touches/page vs target
   4.0001 (**+0.06%**); cold mean **0.24944** vs 0.25 (**−0.22%**); hot pages
   reached 12,844 vs the Poisson(4) expectation 12,867 (**−0.18%**); the pass-1
   histogram is the expected Poisson(4)⊕Poisson(0.25) mixture (41,099 pages
   untouched, mode at 1 for the cold tail and 4-5 for the hot set). All inside
   tolerance. `zipf:1.1`: effective hot set (prefix carrying 0.80 of the mass)
   1,689 pages / 6.598 MiB; measured prefix mass **0.800446** vs analytic
   **0.800013** (dev +4.3e-4 = 0.28σ).

   No capped or graded cell was run (bars not frozen).
2. ~~**Fault-around arm**~~ — **CLOSED 2026-09-05** (`t1d_cell.py --fault-around`
   maps R with `MADV_NORMAL`; default stays `MADV_RANDOM`). JSON records
   `madvise`, `fault_around`, and `soundness_identity_applicable` (false under
   fault-around — readahead merges faults, so the one-fault-per-missing-page
   identity cannot hold; such a cell is judged on its floor trajectory, and
   `--self-check` no longer fails it for that reason).

   **Uncapped sanity runs** (this dev container, R=256 MiB, `hotset:0.20:0.80`,
   seed 1729; `data/eval_results/t1d_validation_{faultaround,random}_*_20260905.json`):

   | mapping | `--resident-frac` | R resident after seed | seeded deficit | pass-1 majflt |
   |---|---|---|---|---|
   | `MADV_NORMAL` (`--fault-around`) | 0.90 | **100.0000%** | 0 | 0 |
   | `MADV_RANDOM` (default, from gap 1) | 0.90 | 89.9994% | 6,554 | 2,470 = reachable deficit |
   | `MADV_NORMAL` (`--fault-around`) | 0.01 | **99.6429%** (655 warmed pages → 65,302 resident, ×99.7) | 234 | 1 |
   | `MADV_RANDOM` (control) | 0.01 | 0.9995% (exactly the 655 warmed) | 64,881 | 24,191 = reachable deficit (identity exact) |

   The flag plumbs through unambiguously. **Design consequence to carry into
   S-faultaround (§3.4):** under `MADV_NORMAL` the Tier-1c residency seed is
   *inoperative* — warming a scattered fraction `f` leaves a cluster cold only
   with probability ≈ `(1−f)^32` at a 128 KiB readahead window, so any usable
   `f` reads back ~100% resident and there is no initial deficit to seed. The
   fault-around arm therefore cannot be run as a seeded-deficit cell; it must be
   compared arm-to-arm on the **steady floor under the cap** (which is where §3.4
   asks the question anyway), and its initial state noted as "cap-determined, not
   seeded". Not run capped here (bars not frozen).
3. **Real-access-histogram probe (for S-realprofile):** a real-stack measurement
   of the seismic index's per-page (or per-posting) access frequency under the
   demo query mix — its own small pre-registered probe on the OCI box; until it
   exists, S-realprofile stays *est.* and cannot run. **STILL OPEN 2026-09-05;
   blocks ONLY S-realprofile (§3.6), which is severed from the §5 freeze (see
   header) — the probe is OCI-side and sits behind N7's post-trial billing
   decision.**
   > **CLOSED 2026-09-12** — run locally as a counting probe (the OCI-side
   > assumption was wrong: counts are host-independent). Frozen + measured in
   > `PREREGISTRATION_T1D_PROBE.md` §7–8 (two replays byte-identical): real
   > skew ≈ `hotset:0.10:0.80` on forward pages, hot-80 3.21 GB, 446,508
   > extents. Prior measurement Q12b (2026-07-14) is acknowledged there.
   > S-realprofile remains severed only on the driver import mode (§5 of the
   > probe doc) and an initial-residency profile.
4. ~~**Orchestrator**~~ — **CLOSED 2026-09-05** as the local variant
   `t1d_wsl2_orchestrator.sh` (landed `7e0eb51f`; MGLRU boot-assumption fix
   `79cf8a04`): systemd-run cap + lru arm toggles, window discipline, any-date
   SKIP, `CELL_TIMEOUT=1800 s`, `STRICT_SOUNDNESS` gate. Run book:
   HOST_RUN.md T1d-0…T1d-9 (Tier-1d runs LOCALLY on WSL2; the OCI box is not
   used).

## 7. Non-interference & efficacy

N1–N8 adopted verbatim from the Tier-1c / sml pre-regs (lock, apt-guard,
sfu-serve stop+restore, lru restore to 0x0007, deadline shed, any-date SKIP,
per-cell protocol+soundness checks; scratch under `data/t1d_scratch` removed in
the trap; never touch `data/seismic_150m/`). **N7 binds hardest here: no window
until the post-2026-09-03 billing decision is made.** Efficacy per CLAUDE.md:
cells → `data/eval_results/t1d_*.json` (committed), verdicts + numbers + absolute
dates → a Tier-1d section of RESULTS.md. If T1d-1 PASSES, that is the
index-independent reproduction (publication-gate item 1) and the conclusion goes
to `docs/THIN_CLIENT_SWAP.md` in the same push; if it FAILS, the negative result
is final and the write-up reframes permanently around real-index access
structure. Bars stay DRAFT until §4 runs.

## 8. Relation to the SML line (why the user asked "for the SML run")

Tier-1d and the small-machine (sml) line meet at situation **S-realprofile**:
the sml 16 GB non-determinism (converge once, thrash once — sml pre-reg run 4)
is hypothesised to be a **near-critical-cap + skewed-access** bimodality, i.e.
whether the hot set happens to settle under the cap on a given cold-start. If
S-realprofile reproduces that bimodal split in the cheap synthetic, it both
explains the SML floor's raggedness AND gives a fast rig to test fixes (e.g.
does forcing classic LRU, or a warmup pass that pins the hot set, collapse the
thrash mode?) without burning 40-min real-stack windows. Two SML-side tests that
belong in the **sml** pre-reg, not here, but are the natural companions:
(a) a 16 GB **replicate battery** (N≥10, L41/classic) to quantify the
converge/thrash split empirically; (b) **pass-1 working-set instrumentation**
(what the instantaneous touch set spikes to when it thrashes vs converges).
