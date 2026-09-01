# Pre-registration DRAFT — Tier-2 (native Linux, classic LRU) & Tier-3 (MGLRU): real-stack repro of the convergence artifact

**Date:** 2026-08-31 · **Status:** **DRAFT — NOT FROZEN. No cells may run
against this document.** Freeze requires: (a) the shipping gap closed (§5),
(b) the calibration phase (§4 phase A) executed and its cliff/rung positions
recorded here, (c) bars frozen (§6) — each as its own commit before the
confirmatory run.

These are publication-gate items 2–3 (PREREGISTRATION.md §"Known
limitation"): the artifact (04_CONVERGENCE_ARTIFACT.md §1–§8; R1 observed,
R2 replicated, R3 per-page attributed) exists on the WSL2 shared-kernel
classic-LRU host only. Tier-1/1b established the synthetic cannot show it
(access-structure dependence, RESULTS.md §16), so items 2–3 use the **real
stack and real 40-query workload** — the ingredient the synthetic lacked —
and vary only the kernel environment.

## 1. Target host (facts measured over SSH 2026-08-31, read-only)

The OCI demo serve box `SFU-thin-serverhosted-150M` (10.0.0.174 via broker
<broker-ip>, key `~/.ssh/sfu_demo_oci`):

- VM.Standard.E5.Flex, 8 OCPU / 16 vCPU **x86_64**, **62 GiB RAM** — same
  arch and comparable pool to the WSL2 measurements (56 GB shared pool).
- Ubuntu 24.04, kernel **6.17.0-1018-oracle**, page size 4096, cgroup v2
  (`nsdelegate,memory_recursiveprot`), **no swap** (swapon empty — the
  VmSwap confound is structurally absent), no docker.
- **MGLRU present and ENABLED: `/sys/kernel/mm/lru_gen/enabled = 0x0007`**
  (runtime-toggleable). Baseline state of the box is MGLRU.
- Real stack deployed and serving (`sfu-serve` active): payload 126.33 GB on
  `/mnt/idxvol` (196 GB vol, 58 GB free), cp311 venv at `/mnt/idxvol/.venv`,
  repo mirror at `/opt/sfu-library-thinclient → /mnt/idxvol`, manifest
  `seismic_c25_shards_150m_mmap_e5_v2.json` present.

One box therefore serves both tiers as a toggle-controlled A/B:
**Tier-2 = `echo 0 > lru_gen/enabled`** (classic two-list LRU, native
kernel), **Tier-3 = `0x0007`** (MGLRU, the box's own baseline). Record
`uname -r` + `lru_gen/enabled` in every cell JSON; verify the toggle stuck.

Recorded confounds vs the WSL2 measurements (not defects; note in verdicts):
KVM guest not bare metal; block-volume (network) storage vs local NVMe —
fault *latency* magnitudes will differ, fault-count trajectories are the
primary metric; kernel 6.17 vs 6.6-WSL2; demo payload (126 GB) is the
deployed subset, not the dev tree's 187 GB — same shards the R1/R2 workload
touches (verify extent coverage in phase A before any bar is judged).

## 2. What reproduces (claims under test)

Per tier, at a re-found ladder (§4):

- **C1 (regime ordering):** converged / transient / thrash regimes appear in
  cap order, cliff at the repeat-set size (WSL2: 10–11 GB).
- **C2 (the transient):** at least one rung shows a monotone-decaying majflt
  trajectory to ≈0 across passes (the lazy sort, R2 §7).
- **C3 (the inversion):** at a fixed pass-3 window there exists a cap pair
  (bigger, smaller) with the smaller cap converged and the bigger cap
  mid-transient — smaller cap faster at pass 3 (R1 §1: 12 vs 16 GB).
- **C4 (mechanism telemetry):** pass-1 pgscan monotone in pressure;
  `workingset_refault_file` → 0 above the cliff, sustained below (R2 §7.3).
  Tier-3 note: MGLRU exposes different counters (`lru_gen` stats); record
  both, judge C4 on the cgroup counters that exist under MGLRU.

**Pre-declared asymmetric outcome (Tier-3):** MGLRU eliminating C3 (or C2's
window shrinking below pass resolution) is a *remediation finding*, recorded
with the same rigor as a reproduction — not a failure of the tier.

## 3. Non-interference constraints (HARD BARS — violating any voids the run)

The box is the live public demo (demo.vancitylandscaper.com, invite-gated;
OCI trial ends 2026-09-03). Measurement validity *requires* exclusive use of
the page cache (first-toucher charging + pre-cell cache drop — R2's poisoned
pass-1 lesson), so cells and the live demo cannot share the box. Therefore:

- **N1 — maintenance window only.** Runs happen in a user-approved window.
  Protocol: snapshot state (`systemctl is-active sfu-serve`, `lru_gen`
  value) → `systemctl stop sfu-serve` → run cells → restore. The broker is
  NEVER touched; during the window the demo shows its degraded/waiting
  state, which is its designed failure mode.
- **N2 — auto-restore trap.** The orchestrator traps EXIT/INT/TERM and
  unconditionally: restarts `sfu-serve`, restores `lru_gen/enabled` to
  **0x0007**, removes its transient systemd scope. A wedged cell may cost
  the window, never the demo. Per-cell hard timeout (100 min, Tier-1
  precedent) + whole-run ceiling sized to the window.
- **N3 — additive files only.** Index/payload files opened read-only (the
  harness never writes into shard dirs); new files limited to: the shipped
  driver + queries JSON (§5), result JSONs under
  `/mnt/idxvol/data/eval_results/`, and one orchestrator script. No package
  installs, no venv modification, no unit-file edits, nothing on the boot
  volume, nothing on the broker.
- **N4 — health gate.** Before opening and after closing every window:
  `https://demo.vancitylandscaper.com/health` returns `status:ok` and a live
  `/api/search` round-trip succeeds (post-restore re-warm query). A failed
  post-check is a stop-everything defect, fixed before any further cells.
- **N5 — capacity guard.** Cell caps ≤ 32 GB on the 62 GiB box (ladder max
  24 GB + margin); ≥ 20 GB free disk maintained on idxvol.
- **N6 — dev-container isolation.** Nothing in this tier's work modifies the
  dev container's infra: no edits to judged harnesses (Tier-1 spike files,
  `r2_convergence_ladder.py` at its judged commits), no src/ or MCP-server
  changes, no local venv installs. New scripts/docs only.

## 4. Design (two phases, mirroring R1→R2)

**Phase A — calibration (exploratory, no bars):** on each tier arm, a coarse
ladder (24/16/12/10/8 GB + free-run baseline) of convergence-terminated
cells (R2 rule: min 3 / max 12 passes, near-zero OR plateau) to (a) verify
the workload runs on the box's payload, (b) find the cliff and the transient
band, (c) measure per-pass wall time to size windows. Outputs recorded here
as measured rung positions. No verdicts.

**Phase B — confirmatory (bars frozen first):** fine rungs around the
measured cliff + the candidate inversion pair + replicates at the two
verdict-bearing rungs (R2's host-noise lesson), per tier arm. Order within a
window: complete one tier's cells before toggling (never interleave toggle
states between passes of one cell). Cache drop (`echo 3 >
/proc/sys/vm/drop_caches` — no privileged container needed, native root)
before every cell.

Driver: `r2_convergence_ladder.py` logic reused via a thin Tier-2/3 launcher
(new file; judged R2 driver untouched) — same convergence rule, same
per-pass cgroup deltas, plus `lru_gen/enabled` + MGLRU stat capture. Capped
via `systemd-run --scope -p MemoryMax=` (no docker on the box); the launcher
resolves its own cgroup from `/proc/self/cgroup` instead of assuming
namespace-root `/sys/fs/cgroup`.

## 5. Gaps to close before freeze (each its own commit)

- **G1:** ship `data/eval_results/e7b_encoded_queries.json` (46 KB, local)
  to the box (additive, per N3).
- **G2:** write + review the launcher and orchestrator
  (`scripts/seismic_testbed/t23_*`), including the N2 trap; dry-run the trap
  logic locally.
- **G3:** phase-A extent-coverage check: the 40 queries' touched extents all
  exist in the deployed 126 GB payload (else record the delta).
- **G4:** freeze §6 bars with phase-A numbers filled in.

## 6. Bars (TO BE FROZEN at G4 — drafted intent only)

Lessons already binding (Tier-1b RESULTS.md §15): no single-percentile
latency bars (threshold-detector defect) — judge on majflt trajectories and
`clat`/p50-from-converged-pass only where fault fraction supports it; ±16%
noise floor respected via replicates; magnitude-weighted comparisons, not
sign-only; every bar names its cell files and its denominator.

## 7. Gap closure & phase-A execution log (2026-08-31)

- **G1 CLOSED:** `e7b_encoded_queries.json` shipped to
  `/mnt/idxvol/data/eval_results/`, sha256 `a5b5e435…` identical to local.
- **G2 CLOSED:** `scripts/seismic_testbed/t23_convergence_ladder.py` +
  `t23_host_orchestrator.sh` (commit `3a8f2722`), shipped to the box; N2
  trap dry-run verified locally (failing cell mid-classic-arm → lru_gen
  restored to baseline, serve restarted, sentinel written).
- **G3 CLOSED (phase-A level):** manifest sha256 identical
  (`3459b4f1…`); all 8 mmap shard dirs: file counts identical (12 each),
  shard0 per-file sizes byte-identical; per-dir `du -sb` deltas are exactly
  4096 B (directory-inode metadata, not content). Backend import OK in the
  box venv. Full extent-map coverage deferred to phase-A cell telemetry.
- **Pre-flight:** passwordless sudo OK; broker has NO cron/timer/OCI-API
  reaper — its poll loop only reconciles displayed state (no instance
  actions mid-window). Disk 58 GB free. Demo health `ok` pre-window.
- **G4 OPEN** by design: bars freeze after phase A per §5.
- **Phase A window opened 2026-08-31** (user-approved, this session): arms
  `mglru` then `classic`, rungs `free 24 16 12 10 8`, launched as transient
  unit `t23a-orch` on the box. ETA estimate at launch: ~3–5 h.

### Phase-A mid-course adjustment (2026-09-01, ~01:20 UTC — exploratory phase, no bars involved)

The first two MGLRU cells invalidated the launch parameters, exactly what
phase A exists to catch:

1. **Protocol mismatch found and fixed:** R1/R2 cells ran with
   `SFU_SEISMIC_PREFLOOR_HOTSET=1` (`r2_cap16g_20260714.json` records
   `prefault_gate: 1`, load 177.3 s leaving **13.76 GB** resident — the L
   population of §2's two-working-set mechanism). The launched cells ran
   with it unset: load was a bare mmap-open (1.5 s, 0.21 GB) — no residue
   population, no two-population initial state. Orchestrator now exports it.
2. **Repeat set on the deployed dotvbyte index ≈ 27.5 GB, not WSL2's
   ~10–11:** free-run cell converged near-zero in 3 passes at p50 19.35 ms
   (strikingly close to WSL2's 18–19 ms) with final `file` gauge 27.55 GB
   (27.37 active). The cap-24 GB cell — WSL2's clean anchor — is *below the
   cliff here*: plateau thrash, majflt 30k→50k/pass, p50 ~5 s. The whole
   `24…8` descent was under-cliff and would only have measured thrash at
   ~100 min/cell. Both cells kept as exploratory data, renamed
   `t23a0_noprefault_mglru_{free,cap24g}_20260901.json`.
3. **Rungs repositioned around measured D≈27.5:** `free 48 36 32 30 28 26`.
   **N5 amendment:** cap ceiling raised from 32 → **48 GB** — still ≥ 12 GB
   headroom on the 62 GiB box with the ~2 GB non-cell footprint; the 32 GB
   ceiling was derived from the WSL2 repeat-set estimate that item 1b of
   this list just falsified.
4. Relaunched with the fixed protocol; the two `t23a0_noprefault_*` cells
   are protocol-mismatched vs the relaunch and must never be compared
   against `t23a_*` cells in any bar.

### Phase-A results (2026-09-01, complete — exploratory, no verdicts)

14 cells (7 rungs × 2 arms) + 2 no-prefault exploratory; raw cells commit
`29d58b89`, `data/eval_results/t23a_*_20260901.json`. Windows 01:37–02:11
(classic) and 02:21–04:06 UTC (MGLRU); N4 health gate PASSED after each
window (public 200/0.18 s, live `/api/search` round-trip OK). Execution
defects hit and fixed en route (all before any valid cell): transient-unit
cwd broke the PREFLOOR encoder init (`41e4b496`); the box was missing the
SPLADE tokenizer fallback files (shipped `sfu-academic-embed-v1`
tokenizer.json/config, vocab 30522 verified); a kill mid-arm polluted the
lru_gen baseline — the driver's arm-verify guard refused every mislabeled
cell as designed, and the baseline is now pinned (`e37ca75e`).

Measured (all majflt per pass; p50 ms):

- **C1/C2, classic (0x0000):** ≥30 GB clean (one cold pass ~9.9k, then
  19.3–19.8 ms / 0 faults, pgscan 0, active_file 0.2–0.4 GB). Transient
  band 26–28 GB: 28 G `12,730 → 22,127 → 577` (p50 2702 → 263 → 20.2);
  26 G `31,521 → 5,100 → 0` (p50 4717 → 64.3 → 19.4). Same ~19–20 ms
  destination; active_file ends 13.7–15.1 GB (sort earns protection).
- **C3 signal, classic:** fixed pass-2 window — 26 G p50 **64.3 ms** vs
  28 G **262.8 ms** (4.1×, fault-count corroborated 5.1k vs 22.1k): the
  smaller cap wins mid-transient. Pressure-dominated convergence, the
  dynamic Tier-1b's synthetic could not produce.
- **C4, classic:** pass-1 pgscan monotone in pressure: 0 (30 G) → 1.02M
  (28 G) → 5.18M (26 G).
- **MGLRU (0x0007):** ≥30 GB identical to classic. 28 G does NOT converge:
  `12.9k → 44.0k → 46.7k → 49.0k` plateau, p50 4.3–5.3 **s**. 26 G deep
  thrash: `49.2k → 159.9k → 158.3k → 162.9k` plateau, p50 ~24.5 s
  (~1000× classic's 19.4 ms at the same cap).
- **Cliff placement:** classic < 26 GB; MGLRU ≈ 29–30 GB. The pre-declared
  §2 asymmetric outcome materialized in the *opposite* direction: MGLRU
  does not eliminate the transient — at these rungs it replaces it with
  sustained thrash (a regression-class finding, recorded not judged).
- **Anomalies for phase B to control:** PREFLOOR load branches on the cap
  (free run: 41 s / 1.4 GB post-load vs 165 s / 15.1 GB capped; cap32g
  13.2 GB) — pin down before any cross-rung residency bar.

### G4 bars — **FROZEN 2026-09-01 (this commit), before any phase-B cell runs**

The B1–B5 bars below are frozen as drafted, with these definitions bound
now: the **fixed window is pass 2** (phase-A measured); **replicates are
phase-B cells only** (`t23b_*`; exploratory `t23a_*`/`t23a0_*` cells are
excluded from every bar); the convergence rule is unchanged from R2/phase
A; **cliff** (per arm) = the midpoint between the highest plateau rung and
the lowest near-zero rung; a bar is judged **only when every cell it names
exists** — cells missing because a window was cut short are "not run", the
bar stays open, and a later window resumes them via the orchestrator's
existing-result SKIP (never re-running completed cells).

**Windowing/interruptibility protocol (user constraint: ~2 h window):**
phase B runs via `t23b_host_orchestrator.sh` — priority-ordered cells
(B2/B3/B1 replicate pairs → B5 MGLRU bracket → ladder fill), per-cell
timeout 2700 s, and a **window deadline (100 min): no new cell starts after
it**, so trap + restore complete inside the window. The run may be stopped
at any moment (`sudo systemctl stop t23b-orch`, or killing it any other
way): finished cells are already on disk, the trap restores
`sfu-serve` + `lru_gen=0x0007`, and nothing is lost but the in-flight cell.

Frozen phase-B cell list, in run order: classic 26/28/30 ×2 reps →
mglru 30/31/29 ×2 reps → fill classic 27/25/29, mglru 32/28 (×1).

Phase B (confirmatory): classic rungs 25–30 at 1 GB steps + replicates at
26/28/30; MGLRU rungs 28–32 + replicates at 29/30/31. Proposed bars, per
the Tier-1b bar-design lessons (no single-percentile threshold detectors;
±16% noise floor; magnitude-weighted; every bar names cells + denominator):

- **B1 (regimes, per arm):** every rung ≥ cliff+2 GB converges near-zero
  ≤ 4 passes; every rung ≤ cliff−2 GB plateaus ≥ 10× near-zero threshold.
- **B2 (transient, classic):** ≥ 1 rung with a decaying majflt trajectory
  spanning ≥ 3 passes to near-zero, in both replicates.
- **B3 (inversion, classic):** at the fixed pass-2 window there exists a
  cap pair (small < big, both converging to the same steady state) with
  small-cap p50 ≥ 2× faster AND small-cap majflt < big-cap majflt, in both
  replicates.
- **B4 (mechanism):** pass-1 pgscan strictly monotone in pressure across
  each arm's ladder; converged-cell active_file ≥ 10× the no-pressure
  cells'.
- **B5 (MGLRU A/B):** cliff displacement |MGLRU − classic| measured with
  1 GB resolution and replicate agreement; direction and magnitude
  recorded whichever way it falls.

### Phase-B run 1 (2026-09-01 04:55–06:23 UTC) — PROTOCOL-VIOLATED, quarantined, bars NOT judged

All 17 cells completed inside the window (88 min, deadline never reached,
N4 gates passed before/after), but the phase-B orchestrator omitted the
`SFU_SEISMIC_PREFLOOR_HOTSET=1` export the phase-A adjustment pinned —
every cell records `prefault_gate: "0"` (load 1.4 s / 0.21 GB; the
no-prefault signature, pass-1 majflt 19,038 bit-identical to
`t23a0_noprefault_mglru_free`). **No bar is judged on this run.** Cells
renamed `t23b0_noprefault_*` (kept), box statuses cleared so a valid run
starts clean. Orchestrator fixed: the export restored + a per-cell
`prefault_gate` check that quarantines the result and aborts the window
(exit 5) on any future violation.

Kept because the accidental A/B is itself informative (exploratory, no
verdicts): **without the prefault L population, the transient AND the
MGLRU/classic divergence both vanish** across 25–32 GB — every cell
converges near-zero in 3 passes, replicates bit-identical, and MGLRU 28 GB
(a 17-min plateau-thrash WITH the L population in phase A) converges
cleanly. Third independent line of evidence — after Tier-1's load-order
result and Tier-1b's synthetic failure — that the artifact requires the
two-population initial state, now shown on the real stack itself.

**Phase B (valid) still requires a fresh ~2 h user-approved window.**

### Phase-B run 2 (2026-09-01 19:47–21:28 UTC) — VALID; B2/B3 PASS, B1/B4/B5 open

16/17 cells DONE (`data/eval_results/t23b_*_20260901.json`), every cell
`prefault_gate: "1"` with the pinned load signature (165–167 s, ~16 GB
file-resident; verified per-cell by the hardened orchestrator). Window
deadline (100 min) hit at 6,041 s: `mglru:28:1` — last in the frozen
priority order — never started; per the frozen rule it is "not run" and
every bar naming it stays open. N4 gate PASSED before and after (public
`/health` 200/0.28 s; live `/api/search` round-trip on the box
post-restore). Restore trap clean (lru_gen=0x0007, sfu-serve active).

Replication quality: the three classic rungs shared with phase A reproduce
almost bit-for-bit (26 G: A `31,521→5,100→0` vs B `31,642→5,072→0` /
`31,523→5,100→0`; 28 G: A `12,730→22,127→577` vs B `12,283→22,535→565` /
`12,207→22,598→604`; 30 G: identical `9,854→0→0`), and between-replicate
spread is ≤1% on every judged quantity. Bar-input extractor:
`scripts/seismic_testbed/t23b_bar_inputs.py`.

Verdicts (frozen bars, phase-B cells only):

- **B2 PASS.** Classic 26 GB decays ≥3 passes to near-zero in both
  replicates: `31,642→5,072→0` and `31,523→5,100→0` (25 G and 27 G single
  cells corroborate: `34,307→2,771→0`, `26,627→8,699→0`).
- **B3 PASS.** Pair (26 G, 28 G) at the fixed pass-2 window: p50 63.9 ms
  vs 372.6 ms (5.8×) rep1, 62.4 vs 352.3 ms (5.6×) rep2 — the smaller cap
  ≥2× faster with fewer faults (5,072 < 22,535; 5,100 < 22,598) — and
  both rungs converge to the same steady state (19.5–21.2 ms, majflt
  ≤604).
- **B1 OPEN — cliff uncomputable as frozen.** The frozen cliff definition
  (midpoint of highest plateau rung and lowest near-zero rung) binds to
  no phase-B cell: all 16 cells converge near-zero in 3 passes (≤4 ✓),
  no rung plateaus — classic's plateau lies below the 25 GB ladder floor,
  and MGLRU's candidate plateau rung (28 G, the phase-A plateau) is the
  not-run cell. The near-zero clause is satisfied 16/16; the plateau
  clause has no cells to bind to.
- **B4 OPEN** (names mglru 28). Classic inputs recorded: pass-1 pgscan
  strictly monotone in pressure — 6.15M / 5.20M / 3.96M / 0.93M / 0.13M /
  0 across 25→30 GB (replicates within 0.5%). active_file: pressured
  rungs 25–28 end 14.7–17.9 GB = 31–38× the no-pressure cells' 0.475 GB;
  rung 29 (marginal pressure, pgscan 130k) ends 0.596 GB = 1.25×.
  Judgment hazard recorded now, before the missing cell exists: the MGLRU
  arm holds ~14.35 GB active_file even at zero pressure (gen-based aging
  classifies the prefaulted file pages active), so the ≥10× clause cannot
  separate pressured from unpressured MGLRU cells.
- **B5 OPEN** (names mglru 28). Also recorded: classic's cliff is not
  bracketed by the frozen ladder (25 G, its floor, converges), so the
  displacement |MGLRU − classic| at 1 GB resolution stays uncomputable
  even once mglru 28 exists — if 28 plateaus as in phase A, displacement
  is lower-bounded at ~4 GB (MGLRU cliff 28.5 vs classic < 24.5).
  Extending the ladder below 25 GB would be a new pre-registered
  amendment, not a phase-B resumption.

Remaining phase-B work: one cell (`mglru:28:1`; the phase-A analogue
plateau-thrashed 17 min, cell timeout 2700 s covers it — a ~30 min window
suffices). Orchestrator resume hardened in the same push: the
existing-result SKIP now matches any date (`t23b_<arm>_<label>_*.json`),
so a later-day window resumes instead of silently re-running all 16
cells.

### Phase-B COMPLETE (2026-09-01 22:06 UTC): mglru:28:1 DONE — 17/17; B1/B4/B5 judged

`mglru:28:1` ran 21:46:29–22:06:02 UTC in a resume window (16 SKIPs,
any-date SKIP verified in the run log), `prefault_gate=1`, N4 passed both
sides. Result: **plateau in 5 passes** — majflt
`12,325 → 41,321 → 46,446 → 48,948 → 49,315`, p50 2.5 → 5.2 → 5.4 → 4.3 →
4.7 s — replicating phase A's plateau (44–49k) at the same rung, where
classic 28 G converges near-zero in both reps (~21 ms). All 17 frozen
cells exist; the three open bars judge:

- **B1 NOT PASSED — half-computable.** MGLRU half satisfied: cliff =
  28.5 G (highest plateau rung 28, lowest near-zero 29); rungs ≥ cliff+2
  (31, 32) converge near-zero in 3 passes; rungs ≤ cliff−2: none in the
  ladder (vacuous). Classic half uncomputable: no classic rung plateaus
  in 25–30, so the frozen cliff definition binds to no cell. A
  ladder-design miss (floor above classic's cliff), not evidence against
  the phenomenon.
- **B4 FAIL as frozen.** Clause 1: classic pass-1 pgscan strictly
  monotone (6.15M > 5.20M > 3.96M > 0.93M > 0.13M > 0) but MGLRU fails on
  zero-ties (891,816 > 86,877 > 0 = 0 = 0 across 28→32). Clause 2:
  classic pressured rungs 25–28 are 31–38× the no-pressure cells'
  0.443–0.475 G, but classic 29 is 1.25× and every MGLRU cell ~1.0×
  (MGLRU holds ~13.4 G active_file at zero pressure). These are the
  Tier-1b bar-design failure classes again (ties defeat "strictly"; a
  gauge threshold assuming classic activation semantics). The mechanism
  itself is strongly supported — see the exploratory reading, RESULTS.md
  §22 — the bar's arithmetic is not.
- **B5 NOT PASSED — displacement uncomputable as frozen; direction
  established.** MGLRU cliff = 28.5 G at 1 G resolution (bracket rungs
  29–31 replicated ×2, all near-zero; plateau rung 28 single-rep per the
  frozen cell list). Classic cliff lies below the 25 G ladder floor, so
  |MGLRU − classic| ≥ ~4 G, lower bound only. Direction recorded per the
  bar: MGLRU displaces the cliff UPWARD (needs ≥ ~4 G more memory before
  the artifact clears) and at equal caps replaces the classic transient
  with sustained thrash (28 G: plateau p50 4.6 s vs classic ~21 ms
  converged, ~220×).

**Final phase-B tally: B2, B3 PASS; B1, B5 not passed on
uncomputable-as-frozen components (ladder floor above classic's cliff);
B4 FAIL (bar arithmetic; mechanism supported).** Tightening B1/B5 needs a
ladder extension below 25 G — a new pre-registration, explicitly not a
phase-B change.

## 8. Efficacy recording

Per CLAUDE.md: results land in `data/eval_results/t23_*.json` (committed),
verdicts + numbers + dates in a Tier-2/3 section of RESULTS.md, and
04_CONVERGENCE_ARTIFACT.md gets the items-2–3 addendum in the same push.
