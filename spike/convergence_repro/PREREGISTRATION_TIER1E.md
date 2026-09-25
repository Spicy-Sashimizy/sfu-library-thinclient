# Pre-registration DRAFT — Tier-1e: the RE-TOUCHED residue (the one ingredient the inversion is missing)

**Date:** 2026-09-25 · **Status: DRAFT — awaiting the operator's freeze; no
cell may run.** Freeze requires, each in its own commit: (a) the §6 gaps
closed (the `--l-touch-rate` driver knob plus its default-path identity
proof), (b) the §5 calibration window executed and recorded **here**, (c) the
§7 bars frozen. Nothing in §7 is judgeable before that.

**Host.** Local only — this WSL2 machine (31 GB RAM, 16 cores, kernel
`6.18.33.2-microsoft-standard-WSL2+`, `lru_gen` `0x0007`, cgroup v2). Caps
≤ 8 GiB, footprint 6.75 GiB, so the 2026-09-25 loss of the OCI host touches
**nothing** in this document. There is no OCI clause; see §8 N7.

---

## 1. Why Tier-1e (what Tier-1d closed, and the one hole it left)

Tier-1d **passed** publication-gate item 1: the real stack's MGLRU/classic
**arm asymmetry** reproduces index-independently (steady-floor ratio
**1.443** in both seeds at cap 1.5 GiB, frozen bar ≥ 1.30 —
`RESULTS.md` §23–25). What it never reproduced is the artifact's *other*
half: the **fixed-window inversion** itself (`04_CONVERGENCE_ARTIFACT.md` §1
— at the pass-3 snapshot the 12 GB cap is 6× faster than the 16 GB cap).

The inversion was chased through **four** successive forms and closed
NEGATIVE in every one (`RESULTS.md` §27, §30):

| form | cell | outcome |
|---|---|---|
| deficit (frac 70 vs 92) | T1d-11 | inoperative — under a binding cap both frac settings seed to the same cap-determined ~28.6% residency |
| cap-pair, no residue | T1d-13 | classic 6.5/7/7.5 GiB **bit-identical** to the 8 GiB control — at any cap > \|R\| with L cold the cap never binds |
| warm residue (`--warm-l`) | T1d-15 | the residue **is** displaced (end `l_resident_pct` 23.1% @5.5G → 100% @8G) but **costlessly**: majflt trajectories bit-identical to control at every cap |
| cold-start + residue, sort **in-window** | T1d-17 | the §27 defect fixed and observably so (`l_resident_pct` declines in-window, pressure-proportionally: 8 GiB flat 100%, 6.5 → 90.7%, 6.0 → 62.5%, 5.5 → ~33%) — **and still no inversion**: majflt trajectories bit-identical across all four caps and both arms |

**The diagnosis is already in the record, stated twice.** §30: *"reclaim —
classic AND mglru — victimizes the never-retouched L pages exclusively and
never evicts R, so the residue sort has zero majflt/wall cost to the measured
workload"*, and *"the arm contrast on residue sorting is null too… the
missing-refault-activation asymmetry needs re-touched pages to bite, and a
pure residue never re-touches."* §27 named the required ingredient outright:
*"a residue that is itself re-referenced."*

**That is the single untested variable, and it is now measurable rather than
guessed.** The T1d-probe (2026-09-12, `RESULTS.md` §32, gap 3 CLOSED)
measured the real index's access histogram: the real skew is
**`hotset:0.10:0.80`** on forward pages — hot-80 = **10.4%** of forward pages
/ **3.21 GB** — with mass at h = 0.05 / 0.10 / 0.20 →
**0.589 / 0.789 / 0.961**. Read the complement: on the real index the
**remaining ~90% of pages carry ~20% of the touches.** The real stack's
"residue" is **not a never-touched population**. The synthetic's L is touched
exactly once, at warm time, and never again — which is exactly why reclaim's
choice there is trivially correct and the sort is free.

**Tier-1e's hypothesis, stated before any cell runs:** *the fixed-window
inversion requires a residue that is re-touched at a non-zero rate, because
only then must reclaim **learn** which population to victimize, and only then
does the learning cost land inside the measured window.*

---

## 2. The design change (exactly one moved variable)

Tier-1d's driver, `t1d_cell.py`, already carries every knob this needs except
one. **Existing knobs, unchanged:** `--r-size-mib` (default 5120),
`--l-size-mib` (default 1792), `--resident-frac`, `--passes`, `--near-zero`,
`--seed`, `--skew hotset:h:m | hotsetc:h:m[:E] | zipf:s`, `--warm-l`,
`--fault-around`, `--hotset-switch-pass/-seed/-skew`, `--arm`, `--cap-label`,
`--self-check`, `--skip-laydown` / `--laydown-only`.

**The one new knob (§6 gap 1):**

```
--l-touch-rate f     # 0.0 <= f <= 1.0, default 0.0
```

During **each measured pass**, in addition to R's skewed draw, the cell issues
`round(f * |L_pages|)` touches into **L**, drawn uniformly from the *same*
replayable RNG stream that drives R's draw, so a pass remains reproducible
from `--seed` alone. `f = 0.0` is the default and **must reproduce today's
cells bit-identically** — the same default-path invariant that
`--hotset-switch-pass` was built to satisfy (`t1d_cell.py`: *"0 = off
(default), in which case the cell is bit-identical to before this flag
existed"*). That invariant is a **hard validity control**, not a nicety: see
E2 below.

**Calibrating `f` to the measured real index.** With the probe's
`hotset:0.10:0.80` curve, the cold 90% of pages carries 20% of touches, i.e.
a relative per-page touch rate of `(0.20/0.90) / (0.80/0.10)` = **0.028×** the
hot rate. Expressed against L's page count at R = 5 GiB / L = 1.75 GiB, the
draft grid is `f ∈ {0, 0.01, 0.05, 0.15}` — bracketing the real index's
coordinate from both sides. The exact grid is fixed at freeze from §5.

**Skew defaults move to the measured value.** Tier-1d's judged cells drew
`hotset:0.20:0.80`; the probe showed that is a **softer** skew than the real
index (real ≈ `0.10:0.80`, which is the T1d-11 sweep rung). Tier-1e runs at
**`hotset:0.10:0.80`** throughout — the measured coordinate, not the guessed
one.

**Everything else is held fixed at the T1d-17 corrected form:** cold-start
laydown (`frac0`) so the residue displacement is scheduled by pressure
*inside* the measured window, `--warm-l` residue, `MADV_RANDOM` mapping.

---

## 3. Situations (arms)

### E1 — the inversion pair (the headline)

Arm **classic**, `hotset:0.10:0.80`, frac0 + `--warm-l`, `--l-touch-rate` at
the §5-calibrated value, **cap pair 5.5 GiB (tight) vs 6.5 GiB (loose)**,
seeds {4177, 20260925}. The pair is chosen so that at the loose cap the sort
lands **late** and at the tight cap it lands **early** — the §22 arrangement
that makes the smaller cap faster on the real stack ("smallest deficit =
latest sort = slowest window"). T1d-17 already measured that these two caps
sit on opposite sides of that scheduling boundary (`l_resident_pct` ~33% vs
90.7% by pass 12).

### E1b — convergence equality (the stack-property control)

The same cells, read at pass 12 instead of pass 3. Both caps must reach the
**same steady floor**. Without this, a "faster tight cap" is just a different
deficit, not an inversion (`04_CONVERGENCE_ARTIFACT.md` §3: the inversion
lives *entirely* in the transient; steady states are monotone and LRU's stack
property forbids otherwise).

### E2 — touch-rate sweep (the mechanism)

`f ∈ {0, 0.01, 0.05, 0.15}` at the **tight** cap, classic, seed 4177. Two
questions: is the inversion **monotone in f**, and does **`f = 0` reproduce
§30's null exactly**? The `f = 0` cell must be **bit-identical** to the
committed T1d-17 cell of the same spec — that is the validity control for the
whole document. If it is not, the new knob perturbed the default path and
**every E1 reading is void.**

### E3 — arm contrast

E1's pair repeated on **mglru**. §22's mechanism predicts the asymmetry only
bites once the residue is re-touched (that is precisely what §30 found
missing): classic should sort via refault-activation and show the inversion;
MGLRU should fail to re-promote and show sustained thrash instead. Recorded
**whichever way it falls**, no threshold — a null here is a finding about the
mechanism, not a failure of the window.

### E4 — strict-soundness control

Cap **8 GiB** (> R + L = 6.75 GiB) STRICT pair, both arms, seed 4177:
identity exact, arm ratio **1.000**, no transient, `l_resident_pct` flat at
100%. Same control as T1d-5 / T1d-17's 8 GiB cell. A window whose uncapped
control moves is invalid, and that invalidates the window, not the hypothesis.

### E5 — pre-declared negative outcome (bound now so it cannot be post-hoc)

**If no value of `f` in the frozen grid produces E1's direction at either
cap**, the synthetic inversion is declared **closed NEGATIVE permanently**,
and the write-up reframes in these words: *the artifact's fixed-window
inversion requires the real index's access structure and has not been
reproduced in a synthetic harness across five successive designs
(Tier-1, 1b, 1c, 1d's four forms, Tier-1e).* Item 1 of the publication gate
stays PASSED on the arm asymmetry, which is what it was passed on. No further
Tier-1f is opened on the current driver.

### Explicitly OUT OF SCOPE

- **Fault-around / readahead cells.** `--fault-around` sheds are **8-for-8
  uniform** across layouts, frac forms and caps (`RESULTS.md` §28, §31):
  readahead under a binding cap thrashes before measurement can begin. No
  `fa:` cell appears in this document; the shed is already the readout.
- **`hotsetc` clustering arms.** §31 measured reclaim as **layout-blind** at
  the divergence rung under `MADV_RANDOM` (clustered floors 334,788.3 /
  482,963.0 → ratio 1.443, replicating the scattered 1.443 to **0.03%**), and
  §32 measured the real hot set as only **1.57×** tighter than random
  placement — so the E=8 arm over-models contiguity. Clustering is settled
  and is not re-opened.
- **S-realprofile.** The probe's exported ranking (readout 2) is a *separate*
  severed item with its own two driver prerequisites
  (`PREREGISTRATION_T1D_PROBE.md` §8.3). Tier-1e uses the probe's measured
  **coordinate** (`hotset:0.10:0.80`), not its exported ranking. The two do
  not block each other.

---

## 4. Ladder, seeds, and the draw ("query mix")

**Populations (Tier-1d constants, unchanged):** R = **5 GiB**,
L = **1.75 GiB**, footprint R + L = **6.75 GiB**. Hot set at h = 0.10 is
**0.5 GiB**.

| cap | regime | role |
|---|---|---|
| **5.5 GiB** | band, deep pressure (T1d-17: `l_resident_pct` → ~33%) | **E1 tight** |
| 6.0 GiB | band, mid (→ 62.5%) | informative midpoint, recorded |
| **6.5 GiB** | band, shallow (→ 90.7%) | **E1 loose** |
| **8 GiB** | above footprint | **E4 strict control** (flat 100%) |

Peak host RAM per cell = 8 GiB cap + laydown files, trivially inside 31 GB;
no host-budget clause is needed.

**Seeds: {4177, 20260925}.** Fresh — **neither is used by any committed
Tier-1d cell** (Tier-1d froze on {2027, 8128}). Verified at freeze by
`grep -rl '"seed": 4177\|"seed": 20260925' data/eval_results/` returning
nothing; the check and its date are recorded in the freeze commit.

**The draw (the synthetic's "query mix"), pinned:** per measured pass,
`|R_pages|` touches drawn from `SkewDraw(seed, hotset:0.10:0.80)` over R's
seeded page ranking, **plus** `round(f * |L_pages|)` uniform touches into L,
both consuming the **same** RNG stream in a fixed order (R first, then L), so
the entire pass sequence replays from `--seed` alone. `--passes 12`,
`--near-zero 2500`, `MADV_RANDOM`, no `--hotset-switch-pass`. Ranking
construction is fixed at laydown, exactly as today.

---

## 5. Calibration window (exploratory; bars NOT frozen)

One window, single cells, no replicates. **No bar may be quoted from it.**
Output lands in a dated `### §5 RECORD` subsection **here**; the §4 cap pair
and the §2 `f` grid may each be adjusted **once**, recorded, before freeze
(the Tier-1d one-shot rule).

1. **`f = 0` identity** — one cell at 5.5 GiB, classic, seed 4177, `f = 0`,
   compared **byte for byte** against the committed T1d-17 cell of the same
   spec. Anything but exact equality stops the window and sends gap 1 back.
2. **`f` placement** — 5.5 GiB, classic, `f ∈ {0.01, 0.05, 0.15}`: at which
   `f` does L start refaulting (non-zero L-attributable majflt) and at which
   does it begin to displace R? The grid is fixed from this.
3. **Pair verification** — that 5.5 and 6.5 GiB still sit on opposite sides
   of the sort-scheduling boundary at `hotset:0.10:0.80` (T1d-17 measured it
   at 0.20:0.80; the harder skew moves the hot set from 1.0 GiB to 0.5 GiB
   and the pair must be re-verified, not assumed).
4. **Wall budgeting** — T1d-17's walls were 255–276 s/cell; re-measure with
   the L touches added.

---

## 6. Gaps to close before freeze (each its own commit)

1. **`--l-touch-rate` landed in `t1d_cell.py`**, with: the default-path
   bit-identity proof (§5 check 1), the touches recorded per pass in the
   result JSON, and an `--self-check` extension so a cell whose realised L
   touch count deviates from `round(f * |L_pages|)` exits non-zero.
2. **L-attributable fault accounting.** The per-pass record must separate, or
   at minimum bound, majflt attributable to L from majflt attributable to R
   (per-mapping `mincore` deltas across the pass boundary are sufficient and
   are already how `l_resident_pct` / `hot_resident_pct` are computed). Without
   it, E2's mechanism reading is unsupported and only E1's headline survives.
3. **Orchestrator cell specs** extended for the `f` tail in the spec string
   (the `t1d_wsl2_orchestrator.sh` pattern: `arm:frac:cap:seed:tail`), with
   trap-restore of `lru_gen=0x0007` and any-date SKIP resume.
4. **§5 calibration executed** and recorded here.
5. **§7 bars frozen** in their own commit, after 1–4.

*Optional, not required for freeze:* `--skew three:h:m:r`, a single-population
three-tier spec calibrated directly to the probe's mass curve
(0.589/0.789/0.961 at h = 0.05/0.10/0.20). If E1 passes with the simple
`--l-touch-rate` knob, this is unnecessary; if E1 is marginal, it is the first
follow-up.

---

## 7. Bars (TO BE FROZEN after §5 — drafted intent only)

Bar-design lessons adopted verbatim: **no strictly-monotone clauses**
(zero-ties killed Tier-2/3's B4), **no gauge thresholds with arm-dependent
semantics**, **±16% noise floor**, every bar names its cells and its
denominator, magnitude-weighted claims only, and **no bar may demand more
than the mechanism can physically deliver** (the ES-2 lesson).

### E1 — the inversion exists (the one that decides the document)

At the frozen fixed window (**pass 3**, the R1 snapshot), in **both** seeds:

> tight-cap (5.5 GiB) `p50_ms` **≤ 0.60 ×** loose-cap (6.5 GiB) `p50_ms`,
> **and** tight-cap pass-3 `majflt` ≤ 0.60 × loose-cap pass-3 `majflt`.

Both clauses, both seeds. **Why 0.60 and not the real stack's 6×:** R1
measured 135 ms vs 22 ms (≈6×) on the real stack, but this bar tests the
**existence and direction** of the effect with margin clear of the ±16% noise
floor, not the real stack's magnitude — a synthetic that reproduces the
direction at any measurable magnitude is the result. The magnitude is
**recorded** whatever it is.

### E1b — same floor (validity clause on E1)

Both caps' `converged` floors within **±16%** of each other by pass 12. If the
floors differ by more, E1's pass-3 difference is a deficit difference and
**E1 does not count as an inversion**, whatever its ratio.

### E2 — `f = 0` identity (hard validity control)

The `f = 0` cell is **bit-identical** to the committed T1d-17 cell of the same
spec: identical majflt trajectory, identical `l_resident_pct` and
`hot_resident_pct` series. **Not a threshold — exact equality.** Failure voids
every other reading in the window.

### E2b — monotonicity in `f` (recorded, no threshold)

The E1 ratio reported at each `f` in the frozen grid. A monotone trend
supports the §1 hypothesis mechanistically; a non-monotone one is recorded as
measured and read in the §22 language (sort scheduling), never smoothed. **No
pass/fail** — Tier-1b's lesson is that monotonicity clauses in bars fail on
ties, not on physics.

### E3 — arm contrast (recorded, no threshold)

`ratio_mglru / ratio_classic` at the E1 pair, plus per-pass
`hot_resident_pct` for both arms. The §22/§24 prediction is classic's hot set
climbs while MGLRU's pins; recorded whichever way it falls.

### E4 — strict control (validity)

8 GiB pair: identity **exact**, arm ratio **1.000**, `l_resident_pct` flat at
100%, no visible transient. A moved control invalidates the window.

### Margin and caveat, carried forward

All E-bar verdicts are read within the **±16%** margin and cite the
`04_CONVERGENCE_ARTIFACT.md` §4 **pageReporting caveat** as frozen, exactly as
the Tier-1d verdicts do.

---

## 8. Non-interference (HARD BARS)

- **N1 — synthetic data only.** R and L laydown files live in a dedicated
  scratch directory passed via `--data-dir`. **`data/seismic_150m/` is
  IRREPLACEABLE and READ-ONLY, always**; `data/thinclient_index/` is not
  touched by any cell in this document. Result JSONs are the only thing
  written under `data/`.
- **N2 — caps.** No cap above **8 GiB**. The orchestrator refuses a cap
  outside the §4 list.
- **N3 — single-window exclusivity.** This working tree is shared by several
  agents. A Tier-1e window may start only when **no page-cache-heavy run is in
  flight against `data/thinclient_index`**; the orchestrator takes a lock file
  and refuses to start if one is held. Two concurrent cgroup-cap ladders
  corrupt both.
- **N4 — restore.** Trap-restore `lru_gen` to **`0x0007`** and remove the cell
  scope on every exit path including SIGINT and deadline shed. (The everyday
  boot policy on this host is MGLRU; `classic` is the arm that deviates —
  `HOST_RUN.md` T1d-1.)
- **N5 — timeouts are never raised mid-window.** `CELL_TIMEOUT` fixed at
  freeze (draft intent **1,800 s**, the Tier-1d value). A shed cell is
  recorded with its `.log`/`.status` and **never retried at a raised
  timeout** (the T1d-14 rule).
- **N6 — swap.** This host has 16 GB of swap. Any cell with `VmSwap > 0` at a
  pass boundary is **quarantined and excluded from every bar**.
- **N7 — single-host clause.** There is no cloud host and no fallback. If this
  host is lost, this line **closes** — recorded as closed-unrunnable, never
  deferred to a host that does not exist. (This replaces Tier-1d's N7 trial-
  horizon clause, which is now void.)
- **N8 — protocol pin.** Every cell JSON records `arm`, `cap_label`,
  `lru_gen` readback, `memory.max` readback, `skew` spec, `seed`,
  `l_touch_rate` and the realised L-touch count. Mismatch → quarantine the
  cell and abort the window.

---

## 9. Output schema (to be pinned at freeze)

One JSON per cell, committed, at:

```
data/eval_results/t1e_<arm>_frac<F>_cap<C>_<seed>_f<rate>_<YYYYMMDD>.json
```

Schema = the `t1d_cell.py` cell schema unchanged (per-pass `majflt`,
`minflt`, `wall_s`, latency summary, `hot_resident_pct`, `l_resident_pct`,
the converged floor and `converged_kind`, the laydown/identity block, the
`skew` block), **plus**:

```json
"l_touch": {
  "rate": 0.05,
  "touches_per_pass": 5734,
  "realised_touches_per_pass": [5734, 5734, "..."],
  "l_majflt_per_pass": [0, 0, "..."],
  "r_majflt_per_pass": [488890, 185803, "..."]
},
"tier1e": {
  "cap_gib": 5.5, "pair_role": "tight|loose|control",
  "skew_source": "T1d-probe 2026-09-12, RESULTS.md 32 (hotset:0.10:0.80)",
  "baseline_cell": "<path to the T1d-17 cell this is compared against>"
}
```

`f = 0` cells additionally carry `"identity_baseline_sha256"` — the digest of
the committed T1d-17 cell whose trajectory E2 requires them to match.

---

## 10. Determinism bar

**T1e-D — bit-identical replay.** Two runs of the same spec with the same
seed must produce **bit-identical** `majflt` trajectories and identical
`hot_resident_pct` / `l_resident_pct` series. **Exact equality, not a
tolerance:** the Tier-1d harness is deterministic enough that its cells came
out bit-identical *across caps and arms* (§30), so any replay divergence here
is a harness defect, not noise. A divergent replay **voids the window** and is
recorded in `RESULTS.md` as a defect.

The determinism bar is run **once per window, on the E4 8 GiB control**,
before any E1 cell — cheapest cell in the family, and the one whose result is
already known.

---

## 11. Budget

Against T1d-17's measured 255–276 s/cell (6/6 DONE, no sheds), plus the L
touches:

| block | cells | est. wall |
|---|---|---|
| §5 calibration | 5 | ~30 min |
| T1e-D determinism (8 GiB control ×2) | 2 | ~10 min |
| E1 + E1b (2 caps × 2 seeds, classic) | 4 | ~25 min |
| E2 + E2b (`f` grid at tight cap) | 4 | ~25 min |
| E3 (2 caps × 2 seeds, mglru) | 4 | ~25 min |
| E4 (8 GiB strict pair, both arms) | 2 | ~10 min |
| midpoint 6.0 GiB, recorded | 2 | ~10 min |

**≈ 18 judged/recorded cells, ~1.5–2 h — one standard window**, plus the
calibration window. Deadline-bounded orchestrator, verdict-critical first
(T1e-D → E4 → E2 identity → E1), any-date SKIP resume.

---

## 12. Efficacy recording (per `.claude/CLAUDE.md`)

Cells land in `data/eval_results/t1e_*.json` (committed). Verdicts, numbers
and **absolute dates** go into a new `RESULTS.md` section (numbered after §32)
and into a dated addendum of
`docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`,
in the same push as the cells. Every quoted number names its cell file and its
denominator.

Until a window runs, the synthetic inversion stays exactly where §30 and §31
left it: **closed NEGATIVE in every form the current driver can express**, and
Tier-1e is **"DRAFTED, UNMEASURED"** wherever it is mentioned — including in
the 2026-09-12 and 2026-09-25 addenda, which name it as open and non-gating.
The write-up's figure set gains nothing from this document until cells exist.

---

## 13. What this document does not do

- It does **not** re-open any Tier-1d verdict. The Tier-1d line is **SETTLED
  (2026-09-06)**; §23's verdicts stand, the frozen §5 bars are never edited
  retroactively, and no Tier-1e cell is judged against them.
- It does **not** bear on publication-gate items 2 or 3. Those are real-stack
  items, and as of 2026-09-25 item 3's bars are **final as recorded** because
  their tightening path (`PREREGISTRATION_TIER23_AMEND1.md`) is
  closed-unrunnable with the OCI host.
- It does **not** discharge **S-realprofile**, which needs the probe's
  exported ranking and its own two driver prerequisites
  (`PREREGISTRATION_T1D_PROBE.md` §8.3).
- It is **independent of** `PREREGISTRATION_WSL2_REHOST.md` (real stack, this
  host's 11.3–19.4 GB band). Neither blocks the other; they share only the
  host and the §8 N3 exclusivity lock.
