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

### Phase A′ run 1 (2026-09-01 22:22 – 2026-09-02 00:22 UTC) — 2 cells, both TIMEOUT; major calibration corrections

Window ran the priority list head only: both attempted cells hit the
3600 s cell timeout with no result JSON (logs committed,
`_sml_L1_*_cap16g_rep1_20260901.log`); deadline then cut the window;
restore + N4 clean both sides. Facts (pass 1, from cell logs):

- **L1/mglru/16 G:** load 1.5 s / 0.24 GB (no-residue gate honored);
  pass-1 wall 3,010 s — p50 43.7 s, majflt 202,183, pgscan 72.2M,
  ws_refault 64.9M. FAIL(124) mid-pass-2.
- **L1/classic/16 G:** pass-1 wall 2,343 s — p50 46.0 s, majflt 182,749,
  pgscan 55.2M, ws_refault 48.9M. FAIL(124).

**Reading (exploratory):** the 16 GB cold-start thrash is NOT
arm-specific — classic and MGLRU are equally destroyed. The cold pass's
effective working set is far larger than the steady 13.76 GB hot set
(tens of GB re-scanned within one pass), so §1's "hard floor ≈ 14.8 GB"
model is wrong for COLD serving: it describes the converged state, not
the convergence path. Both cells' hybrid adaptive flipped seq→par at
query 3; the parallel fan-out inflating the instantaneous touch set is
the candidate mechanism (unverified).

**Design corrections bound for the redesign (one-shot rule):**

1. Priority-order cost model was inverted: L1@16 G cells are the most
   expensive, not the cheapest. Next window resumes with
   `CELLS="L3:classic:20:1 L0:mglru:20:1 L0:classic:18:1 L0:classic:14:1"`
   (env override) — the failed 16 G cells are NOT re-run until redesigned
   (no JSON exists, so the SKIP will not protect against an accidental
   default-CELLS rerun; the override is mandatory).
2. 16 G cold cells need either a raised timeout (≥3 full passes ≈ 3 h,
   likely unaffordable) or a converge-then-judge protocol change;
   candidate S1 rungs move up pending L0 18/20 G baselines.
3. **New candidate lever L4 — sequential federation** (already built and
   measured 2026-07-16, WI-1: peak RssFile 0.023× parallel, warm p50
   5.29× parallel): for caps where parallel cold-start cannot converge,
   sequential serving bounds the instantaneous working set by
   construction. To be added to §2 at redesign with its own env gate;
   its 5.29× warm cost makes it a small-machine-only lever.

### Phase A′ run 2 (2026-09-02 02:48 – 05:41 UTC) — 1 DONE + 2 TIMEOUT; L3 mechanism VALIDATED; the band is parallel-cold-unserveable

Resume window with the bound CELLS override. N4 clean both sides;
restore clean; `L0:classic:14:1` deadline-cut (not run).

- **L3/classic/20 G DONE (52 min): the reclaim lever works exactly as
  designed** — requested 14.00 GiB, freed 14.01 GiB in 2.9 s,
  `write_status: ok`; gauges show it evicted precisely the residue
  (file 15.14 → 1.14 GB while the hot set was not yet resident). §2's
  *est.* on the L3 mechanism is hereby lifted for the write/free step.
  **But the cell still plateaued**: passes 1–3 at 121–133k majflt, p50
  20.4–24.0 s, pgscan 20–23M/pass (`sml_L3_classic_cap20g_rep1_20260902.json`).
- **L0/mglru/20 G TIMEOUT: pass 1 never completed in 60 min** (only the
  seq→par flip logged) — the worst cell measured in the entire research
  line.
- **L0/classic/18 G TIMEOUT mid-pass-3**: pass 1 wall 1,458 s (p50
  31.7 s, majflt 160k, pgscan 35.0M), pass 2 wall 1,496 s and *worse*
  (p50 35.5 s, majflt 181k) — no sign of convergence.

### Phase A″ plan (bound 2026-09-02, before any cell runs) — L4 calibration

Levers added to the orchestrator (same commit as this section): **L4** =
`SFU_SEISMIC_FEDERATION=sequential` + residue load (gate 1); **L41** =
sequential + no-residue (gate 0). N8 extension: an L4/L41 cell whose log
shows a `seq→par` flip is quarantined (the env must override the hybrid
heuristic per ENV_GATES.md). Driver unchanged — the gate acts at backend
init.

Cells, priority order (2 h user window, `CELL_TIMEOUT=2700`,
`WINDOW_DEADLINE_S=4500` so worst-case end = deadline + one timeout =
120 min): `L41:classic:16:1 L41:mglru:16:1 L4:classic:20:1
L41:classic:14:1 L41:mglru:20:1`. Questions each answers: does
sequential cold-start converge at 16 G (both arms, the deployment case);
does sequential handle residue + sort at 20 G (unchanged prod load
path); does sequential move the true floor below the 14.8 G steady
arithmetic (14 G probe, expected fail); arm symmetry at 20 G.

### Phase A″ run 1 (2026-09-02 05:47–06:14 UTC) — ABORTED, two harness defects found and fixed (3104f14c)

- **D-sml-1 — wrong gate layer:** `SFU_SEISMIC_FEDERATION` governs the
  retriever; the driver builds `HybridSeismicBackend` directly, whose own
  `SFU_SEISMIC_HYBRID_*` knobs decide seq/par — the L41 cell flipped
  seq→par at query 3 (count backstop) despite the env. Fix: L4/L41 now
  export `SFU_SEISMIC_HYBRID_SIGNAL=count` + `FLIP_N=999999` (never
  flips). Observed before abort: sequential cold queries ~260 s geomean
  (first 2) at 16 G clean load.
- **D-sml-2 — stop-anytime was broken mid-cell:** bash defers traps while
  a foreground command runs, so `systemctl stop` during a cell let
  systemd KILL the trap before restore ran (box left lru_gen=0x0000,
  serve down; manually restored, N-gate re-verified). Fix: cell runs
  backgrounded + `wait`; the trap kills the cell scope; launches add
  `TimeoutStopSec=300`. Applies to this family only — the judged t23b
  harness is not edited retroactively (its stops were only ever exercised
  between cells).
- Lesson also recorded: per-cell CLOG is truncate-on-open, so run 1's
  partial cell log was overwritten by run 2 (its key numbers are quoted
  here and in commit 3104f14c).

### Phase A″ run 2 (2026-09-02 06:19 UTC) — HEADLINE RESULT: sequential federation serves the full index at 16 G

One cell completed before an unattended-upgrades event interrupted the
window (see D-sml-3 below); it is the decisive one.

**L41 (sequential + no-residue) / classic / 16 G — `sml_L41_classic_cap16g_rep1_20260902.json`:**
converges **near-zero in 3 passes** — the healthy pattern the 16 G
PARALLEL cells (both arms, phase A″ run-source data) never reached.

| pass | majflt | p50 ms | pgscan | wall s | rssfile |
|---|---|---|---|---|---|
| 1 | 9,841 | 518.6 | **0** | 255 | 0.02 G |
| 2 | 0 | 221.8 | 0 | 8 | 0.02 G |
| 3 | 0 | 221.3 | 0 | 8 | 0.02 G |

Reading: pass 1 pays only compulsory (cold) faults; `pgscan=0` means the
cap was **never pressured** — the sequential per-shard `release_pages()`
holds resident-file at ~0.02 G (WI-1's 0.023×-parallel confirmed at full
150M scale). Warm p50 ~221 ms is the known sequential trade (WI-1: 5.29×
parallel's ~19.5 ms). **Because the 16 G cap was never touched, 16 G is
not the floor** — this mode plausibly serves in single-digit GB; the
floor-finding descent is the next cells.

Consequence for the spike and the PAYG plan: the small-machine goal is
achievable with L4/L41 (sequential during cold-start), lifting the TrueNAS
launch-site option (~6 G free) and always-free A1 (24 G) into range and
re-opening Stage-2 phone-class. The parallel-cold-start failure (§ phase
A′ synthesis) stands; sequential is the answer to it.

### D-sml-3 — unattended-upgrades interrupted the window (2026-09-02 06:39)

Ubuntu `unattended-upgrades` fired at 06:39:03 (30 pkgs incl. util-linux,
systemd libs), whose dpkg-driven daemon-reloads re-registered and
re-started the transient `sml-orch` unit twice AFTER it had exited —
each restart re-stopped sfu-serve. **The restore trap (D-sml-2 fix)
fired correctly on every stop** (three `RESTORED: lru_gen=0x0007
sfu-serve=active` lines, including mid-cell), so the box self-healed each
cycle; the demo only stayed down because the external relaunch loop
outran the trap until the unit was masked. L4/classic/20 was lost
(no JSON); L41/mglru/16 never started. Guard added (next commit): the
window stops `apt-daily*.timer` at start + restores in the trap, and a
`/run/sml-orch.lock` PID guard makes a re-spawned instance exit without
touching sfu-serve.

### Phase A″ run 3 (2026-09-02 20:29–22:29 UTC) — guard validated; arm + residue + floor findings

First window under the D-sml-3 upgrade guard: it worked end-to-end — the
final `RESTORED` logged `apt-timers=[apt-daily.timer apt-daily-upgrade.timer]`
restored, `/run/sml-orch.lock` removed, no interruption. Demo healthy
after (public /health 200, live /api/search round-trip OK, box re-warmed).
Deadline shed `L41:classic:8:1` (carries to next window via SKIP). Three
cells ran; all three TIMED OUT, and each timeout is a clean finding:

- **L41/mglru/16 G — TIMEOUT (arm asymmetry).** Same clean load (1.4 s,
  no-residue) and same sequential `release_pages()` path that let
  L41/classic/16 G converge in 4.6 min with `pgscan=0`, but pass 1 never
  completed in 40 min. **Sequential federation rescues the small-cap case
  under classic LRU, NOT under MGLRU** — MGLRU evidently does not reclaim
  the per-shard released pages promptly, so residency builds across shards
  even in sequential mode (consistent with Tier-2/3's "MGLRU never
  re-promotes/handles refaulting pages"). Direct edge for Stage-2:
  **MGLRU is Android's default**, so phone-class deployment needs classic
  LRU forced or a hardened release path.
- **L4/classic/20 G — TIMEOUT (sequential alone is insufficient; the
  levers must compose).** L4 = sequential + residue. Loaded 14.2 G
  residue (165 s), pass 1 wall 1,082 s, p50 18.9 s, pgscan 20.1M,
  ws_refault 17.4M — the cap IS pressured because the residue fills
  cache, vs L41/16 G's `pgscan=0`. Even 4 G MORE memory than the winning
  L41/16 G cell does not help while the residue is present. **The winning
  lever is specifically L41 = sequential + no-residue**; the production
  load path (which uses the prefloor residue) must pair sequential with
  L1 (clean load) or L3 (one-shot reclaim) to serve small.
- **L41/classic/12 G — TIMEOUT (floor bracketed).** Sequential + clean at
  12 G: pass 1 never completed in 40 min. Since L41/classic/16 G
  converged with the cap unpressured (`pgscan=0`), **the classic
  sequential floor is between 12 and 16 GB** — a single cold-pass shard
  traverse needs >12 G but <16 G of headroom. This CORRECTS the run-2
  speculation that the floor might be single-digit GB: it is not; 12 G
  fails. Finer bisection (13/14/15 G) is a next-window item.

Net after run 3: the small-machine lever is **L41 (sequential +
no-residue), classic LRU, ~16 GB**. Open: exact classic floor (12–16 G
bisection), MGLRU rescue path (or its impossibility), L3-vs-L1 for the
residue-bearing prod path, and replicates before any S-bar freeze.

### Phase A″ run 4 plan (bound 2026-09-02, before any cell runs) — headline replicate, prod-path composition, floor bisection, MGLRU probe

New lever, added to the orchestrator in the same commit as this section:
**L43 = L4 ∘ L3** — sequential federation + residue load (gate 1) +
one-shot post-load reclaim (`SFU_SEISMIC_HYBRID_SIGNAL=count` +
`FLIP_N=999999`, `--postload-reclaim-bytes 15032385536`). This is the
production-load-path composition candidate that run 3 demands: L4
(sequential + residue) fails even at 20 G while L41 (sequential + clean)
converges at 16 G, so the open question is whether L3's reclaim restores
a clean-enough state for the residue-bearing production load path to
serve small. N8 for L43 = union of L4's check (quarantine on seq→par
flip) and L3's (freed > 1 GiB), gate 1.

Cells, priority order (`CELL_TIMEOUT=2400`, `WINDOW_DEADLINE_S=5400`;
worst-case window end = deadline + one timeout = 130 min, the run-3
shape): `L41:classic:16:2 L43:classic:16:1 L41:classic:14:1
L41:mglru:20:1 L41:classic:15:1 L41:classic:13:1`. Questions, in order:
replicate the headline cell (cheapest cell in the family, ~5 min,
protects the one converging result before anything is frozen on it);
prod-path composition at the winning rung; floor-bisection midpoint of
run 3's 12–16 G bracket; MGLRU rescue probe at 20 G (carried from the A″
plan — does +4 G headroom rescue MGLRU sequential, or is the arm
unrescuable?); tail = bisection refinements, deadline-shed as needed
(15 G is informative iff 14 G fails; 13 G iff 14 G passes). Dropped as
superseded by run 3: `L41:classic:8:1` (12 G already fails) and
`L41:mglru:12:1` (mglru 16 G already fails). Run-3 FAIL(124) cells left
no JSON, so the SKIP cannot protect them — this CELLS override
deliberately excludes them (no re-runs this window).

### Phase A″ run 4 (2026-09-02 23:20 – 2026-09-03 01:20 UTC) — headline NON-REPRODUCTION; composition fails; thrash confirmed disk-independent

Window ran under the D-sml-3 guard (clean RESTORED: lru_gen=0x0007,
sfu-serve active, apt-timers restored, lock removed, demo healthy after).
A per-minute `iostat` sampler (`_sml_iostat_20260903.log`) ran alongside.
**All three cells that ran TIMED OUT (FAIL 124, no result JSON); the MGLRU
20 G probe and 15/13 G bisection were deadline-shed.** Each timeout is a
finding:

- **L41/classic/16 G rep 2 — TIMEOUT: the headline does NOT reproduce.**
  Same lever/arm/cap as run-3 rep 1 (which converged near-zero in 4.6 min,
  `pgscan=0`). Clean no-residue load (1.3 s, rssfile 16 MB), gate held (no
  seq→par flip), then pass 1 never emitted a single query line in 40 min.
  **So L41/classic/16 G is NON-DETERMINISTIC — converged once, hung once.**
  This directly threatens S1 (both replicates must converge near-zero);
  no S-bar can be frozen on a rung that converges only sometimes.
- **L43/classic/16 G — TIMEOUT: the reclaim works, the composition does
  not rescue.** Residue load 166 s (rssfile 14.2 G), one-shot reclaim
  requested 14.00 GiB / **freed 15.04 GB in 2.81 s, status=ok** (L3
  mechanism re-confirmed at 16 G). But pass 1 then thrashed for the full
  40 min. So L4∘L3 = sequential + residue + reclaim still fails at 16 G:
  the reclaim evicts the residue but does not restore the clean-load state
  that lets L41 converge. **The prod load path is not rescued by adding
  reclaim; the winning lever remains specifically L41 = sequential +
  no-residue (L1-style clean load), not residue-then-evict.**
- **L41/classic/14 G — TIMEOUT: floor bisection, 14 G is on the fail
  side.** Clean load (1.4 s), pass 1 never completed — same thrash as 12 G
  (run 3). So the classic sequential floor is now **between 14 and 16 GB**
  (12 G fails, 14 G fails, 16 G converges sometimes), tightening run-3's
  12–16 G bracket.

- **Disk-throughput correction (recorded honestly).** An intra-window spot
  `iostat` reading of 21 MB/s prompted a mid-session hypothesis that the
  16 G timeouts were block-volume bandwidth starvation. **The full sampler
  refutes it:** sdb delivered a steady **~92–99 MB/s at ~97 % util** across
  the entire L43+14 G span (00:24–01:20). ~95 MB/s sustained for 40 min is
  ~90 GB moved against a 15 GB hot set — a genuine **thrash/refault**
  pattern, not a starved cold read. The 21 MB/s figure was a single
  cell-boundary sample and is retired. Consequence: the rep-2
  non-reproduction is **not** explained by disk speed; 16 G is a genuinely
  marginal / ragged-edge rung whose cold pass-1 sometimes converges and
  sometimes enters sustained thrash. Root cause of the coin-flip is not yet
  isolated (candidate: cold-fault ordering / transient working-set spikes
  in the sequential per-shard traverse at a cap only ~2 G above the hot
  set) — a next-window item.

Net after run 4: the run-3 headline is downgraded from "L41 serves at 16 G"
to **"L41 serves at 16 G non-deterministically"** — one converge, one
thrash. Floor bracket tightened to 14–16 G. Open, carried to the next
window (SKIP-unprotected — all run-4 cells left no JSON): a third+ 16 G
replicate to quantify the converge/thrash split, the 15 G rung, the MGLRU
20 G rescue probe, and isolating the pass-1 thrash trigger.

**Phase A′ synthesis (both runs):** every lever/arm combination tried in
the 16–20 GB band fails to converge through the PARALLEL cold path —
L1@16 both arms, L3@20 classic, L0@20 mglru, L0@18 classic. The levers
demonstrably fix the residue (L1 loads clean; L3 evicts 14 GiB of it in
3 s) and the failure persists, so the binding constraint is the parallel
cold-start working set itself (every cell flips seq→par at query 3 via
the count-backstop; `SFU_SEISMIC_FEDERATION` env can force
`sequential`). **The drafted S1–S3 bars are unfreezable as designed**;
the redesign must make L4 (forced sequential federation during
cold-start/convergence, optionally flipping to parallel once converged)
the primary small-cap lever, with L1/L3 as state-hygiene complements,
and re-derive rungs from an L4 calibration cell before any bar freezes.

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
