# Pre-registration DRAFT — Small-machine serving levers (cap-free artifact mitigation + big-RAM regression controls)

**Date:** 2026-09-01 · **Status:** **DRAFT — NOT FROZEN. No cells may run
against this document.** Freeze requires: (a) the L3 driver support shipped
(§5 gap 1), (b) the calibration phase (§4 phase A′) executed and the thrash
floor + lever-verification facts recorded here, (c) bars frozen (§6) — each
its own commit before any confirmatory cell.

**Question under test.** Tier-2/3 established (PREREGISTRATION_TIER23.md
§7, RESULTS.md §§18–22) that the fixed-window artifact is lazy-reclaim
scheduling of a one-time cache sort, and that three cap-free levers should
eliminate it. This spike tests whether those levers make the real stack
serve well on a **genuinely small memory budget** (the thin-client stretch
goal — phone-class is Stage 2, §8), and whether they **regress nothing**
when memory is plentiful. This is an optimization/efficacy spike, not an
artifact-reproduction tier: the phenomenon is established; the levers are
on trial.

## 1. Measured constants this design builds on (Tier-2/3, 2026-09-01)

All from the 28 valid t23a/t23b cells (probe:
`scripts/seismic_testbed/t23b_mechanism_probe.py`); OCI serve box, 62 GiB,
kernel 6.17.0-1018-oracle, no swap:

- Post-load state (identical in every cell): 165 s load, 15.14 GB file /
  13.56 GB mapped resident, ~1.0 GB anon; residue population inactive.
- Two-population footprint after pass 1: **≈28.1 GB file + 1.0 GB anon ≈
  29.1 GB** — fits at ≥29–30 GB caps.
- Converged hot set: **rssfile 13.76 GB**; steady p50 **~19.5 ms**;
  near-zero threshold 2,500 majflt/pass (driver rule, unchanged).
- **Predicted hard floor: cap < hot set + anon ≈ 14.8 GB** cannot converge
  under any lever (the useful pages don't fit). Never measured on classic;
  MGLRU corroboration at 24 GB (plateau, exploratory straggler log) and
  26 GB (phase A deep thrash, ~24.5 s p50).
- MGLRU cliff 28.5 GB; classic cliff below 25 GB (unbracketed). MGLRU
  never re-promotes refaulting pages (ws_activate → 0), classic re-sorts
  via refault-activation — the lever most likely to rescue MGLRU is the
  one that prevents the wrong initial state (L1/L3), not warmup (L2).

## 2. Levers (the arms)

- **L0 — baseline:** residue load (`SFU_SEISMIC_PREFLOOR_HOTSET=1`), no
  mitigation. The Tier-2/3 protocol as-is.
- **L1 — no-residue load:** `SFU_SEISMIC_PREFLOOR_HOTSET=0`. Efficacy
  already observed accidentally at 25–32 GB (quarantined t23b0 run: load
  1.4 s / 0.21 GB, every cell near-zero in 3 passes, replicates
  bit-identical) — but NEVER at small caps, where the hot set itself no
  longer trivially fits. Production analogue: don't pollute at startup.
- **L2 — warmup pass:** serve the repeat set once before the measurement
  window. **Analysis-level lever, no new cells:** judged by re-windowing
  existing per-pass data (window at pass k+1 instead of pass 2). Included
  in bars only as the comparison floor.
- **L3 — one-shot post-load reclaim:** after load, before pass 1, write
  `<bytes>` to the cell scope's `memory.cgroup/memory.reclaim` (one nudge,
  no standing limit; production analogue: startup hygiene eviction).
  **Unmeasured (est.); needs driver support (§5 gap 1).** Reclaim request
  size fixed at phase A′ from measured residue (footprint − hot set ≈
  14 GB request; exact value recorded at freeze).

## 3. Non-interference (HARD BARS)

**N1–N6 of PREREGISTRATION_TIER23.md §3 adopted verbatim** (user-approved
windows, stop-anytime orchestrator with trap-restore of `sfu-serve` +
`lru_gen=0x0007`, N4 public-health + live-search gate both sides of every
window, caps ≤ 32 GB… amended: **caps ≤ 34 GB**, ≥20 GB free on idxvol,
dev-container isolation). Additional:

- **N7 — trial horizon.** OCI trial ends 2026-09-03; windows after that
  date require the user's post-trial billing decision first.
- **N8 — protocol pin.** Every cell JSON must record `prefault_gate`
  matching its lever arm (L0 `"1"`, L1 `"0"`) and, for L3, the reclaim
  bytes requested + freed; the orchestrator quarantines + aborts on
  mismatch (mechanism shipped at 5feddead, extended for L3).

## 4. Design — two phases on the 150M index (Stage 1)

**Rungs.** Small-machine band **16 / 18 / 20 GB** (between the ~14.8 GB
floor and the 25 GB Tier-2/3 ladder floor), floor-falsification probe
**14 GB**, big-RAM regression control **34 GB** (footprint + ~5 GB slack).

**Phase A′ (calibration, exploratory, single cells, ~one 2 h window):**

1. L0 at 14/16/18/20 GB, one arm each alternating classic/mglru — place
   the small-cap baseline (expected: plateau or deep thrash everywhere in
   band for at least one arm; phase A saw mglru 26 GB at ~24.5 s).
2. L1 at 16 GB both arms — does no-residue converge when the hot set
   nearly fills the cap?
3. L3 mechanism check at 20 GB classic: verify the reclaim write frees
   ≈ requested bytes (Tier-1 ES-5 measured 1791–1793 MiB freed of 1792
   requested on the synthetic; never on the real stack) and that residue,
   not hot set, is what leaves (post-reclaim residency).
4. Re-measure cell wall-times to budget phase B (plateau cells at 14–16 GB
   may run long; cell timeout stays 2700 s, plateau detection cuts at
   5–7 passes).

Phase A′ facts land HERE in a dated section; rungs/request-sizes may be
adjusted once, recorded, before freeze (same one-shot rule as Tier-2/3).

**Phase B (confirmatory, replicates ×2 on every judged cell):** the
S1–S5 cells named at freeze, priority-ordered verdict-critical-first,
deadline-bounded orchestrator (t23b pattern: any-date SKIP resume,
per-cell protocol verification, trap-restore).

## 5. Gaps to close before freeze (each its own commit)

1. **L3 driver support:** `t23_convergence_ladder.py` flag
   `--postload-reclaim-bytes N` (write to the scope's `memory.reclaim`
   between load and pass 1; record requested/freed/failed in the JSON).
2. **Orchestrator variant** `sml_host_orchestrator.sh` (t23b clone: lever
   env per cell, N8 checks, any-date SKIP).
3. **Phase A′ executed** and recorded here.

## 6. Bars (TO BE FROZEN after phase A′ — drafted intent only)

Per Tier-1b/Tier-2/3 bar-design lessons: no "strictly monotone" clauses
(zero-ties), no gauge thresholds with arm-dependent semantics
(active_file), ±16% noise floor, every bar names its cells + denominator,
magnitude-weighted claims.

- **S1 (small-cap rescue, per arm):** at each band rung ≥ floor+2 GB where
  L0 fails to converge near-zero, **L1 converges near-zero ≤ 4 passes in
  both replicates**, steady p50 within ±16% of the 19.5 ms reference.
- **S2 (one-shot reclaim):** at the same rungs, **L3 pass-2 majflt ≤ 0.1×
  the L0 pass-2 majflt** in both replicates (magnitude-weighted; denominators
  named at freeze).
- **S3 (MGLRU rescue):** at the lowest rung where L0-MGLRU plateaus, L1
  and/or L3 convert plateau → near-zero ≤ 4 passes, both replicates
  (which lever(s) is recorded whichever way it falls).
- **S4 (no big-RAM regression):** at 34 GB, every lever arm: steady p50
  within ±16% of L0-34G, and no pass slower than L0's same pass by >16%.
  (L1's 1.4 s load vs 165 s is an expected improvement, recorded, not a
  bar.)
- **S5 (floor falsification):** at 14 GB (< hot set + anon), **no lever
  achieves near-zero** — pre-declared expected outcome; if a lever DOES
  rescue 14 GB the floor model is wrong and that is the headline finding.

## 7. Efficacy recording

Per CLAUDE.md: cells land in `data/eval_results/sml_*.json` (committed),
verdicts + numbers + absolute dates in a section of
`spike/convergence_repro/RESULTS.md` (the levers are the same research
line), and the deployment-facing conclusion (which lever ships for
small-memory serving, or none) goes to `docs/THIN_CLIENT_SWAP.md` +
`docs/LOCALIZED_DEPLOYMENT_PLAN.md` in the same push. Unmeasured levers
stay marked *est.* until their cells exist.

## 8. Stage 2 (phone-class) — explicitly OUT OF SCOPE here

Phone-class budgets (2–6 GB) cannot hold this index's 13.76 GB hot set;
no lever changes that arithmetic. Stage 2 requires a small index build
(portable corpus or sharded subset) whose footprint/hot-set must be
measured first, then ITS own pre-registration (this document's design
transfers; the constants do not). Android relevance recorded now: MGLRU
is the default on modern Android kernels, and Tier-2/3 measured MGLRU as
the arm that cannot recover from a polluted initial state — the strongest
motivation for Stage 2.
