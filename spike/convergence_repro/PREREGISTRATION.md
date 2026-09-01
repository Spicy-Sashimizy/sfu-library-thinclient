# Convergence-artifact synthetic repro (Tier 1) — pre-registration

**Written 2026-08-31, BEFORE the harness was built or any cell was run**
(repo write-before-run convention). Parent:
`docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`
(the observation, mechanism, R2/R3 confirmations) and the publication-gate
list discussed 2026-08-31 (gate item 1: index-independent synthetic repro).

## Purpose

Prove the non-monotonic convergence artifact (fixed-window convergence
inversion) is a property of the kernel's page-reclaim machinery under a
two-population file workload — NOT of the 150M academic-article index, the
SEISMIC engine, or any search-engine-specific access structure. This is the
publication gate for the planned public write-up; on PASS the harness is
lifted into a standalone public repo (spin-off decision recorded 2026-08-31).

## Design (agreed 2026-08-31; field-standard tools only)

Two file-backed populations on LOCAL disk (never 9p — the workspace is v9fs;
data lives in a docker named volume on the overlay/ext4 host disk):

- **Repeat set R = 5 GiB** — mmap random-read every pass via
  `fio ioengine=mmap, rw=randread, direct=0, invalidate=0, randrepeat=1`
  with a fixed `randseed` (the seeded-synthetic determinism mechanism).
- **Load residue L = 1.75 GiB** (L/R = 0.35, matching the real system's
  ~3.8/10.5) — sequential buffered read ONCE at cell start, never again.
- Total file demand D ≈ 6.75 GiB. fio process anon is negligible (unlike the
  real stack's 1.1 GB) — caps are sized against file demand only (recorded
  as a deliberate difference).

Cells = sibling containers `docker run --memory=X --memory-swap=X` (the R1
method; swap forbidden, `VmSwap > 0` ⇒ cell recorded-not-concluded). Rungs,
positioned by ratio to R and D exactly as the real ladder's regimes:

| rung | cap | real-system analogue (R1) |
|---|---|---|
| fits | 10g (1.48×D) | 24–48 GB |
| marginal | 7g (1.04×D) | 16 GB — the lazy-sort cell |
| boundary | 5.75g (1.15×R) | 12 GB — the fast-sort winner |
| thrash | 3.75g (0.75×R) | 8 GB |
| deep | 2.75g (0.55×R) | 6 GB |

Protocol per cell: evict the data files (per-file eviction, e.g.
`vmtouch -e`, verified re-read as ~0% resident — no global `drop_caches`
dependence), sequential read of L then R once (the "load"), then fio passes:
**fixed 3-pass window** for the headline table plus a
**convergence-terminated mode** (max 12 passes; stop when per-pass majflt
falls below 1% of pass-1 or plateaus ±10% across 2 passes).

Per-pass metrics: fio `clat` p50/p95, pass wall time, process majflt
(`/proc/<pid>/stat` field 12 or `time -v`), ms/fault, and cgroup
`memory.stat` deltas — `pgscan`, `workingset_refault_file`, `active_file` —
plus `vmtouch` residency of R and L files between passes.

## Pre-registered bars (ALL must hold for PASS)

1. **Inversion (the artifact):** at the fixed pass-3 window, boundary's
   fio clat p50 < marginal's, while marginal's majflt trajectory is still
   falling (pass3 < pass2 < pass1, not yet ≈0).
2. **Same destination (not Belady):** in convergence mode, marginal and
   boundary both reach steady state (majflt ≈ 0 plateau) with steady p50s
   within ±10% of each other, in ≤12 passes.
3. **Cliff:** both thrash rungs show flat-and-large majflt (pass-3 majflt
   ≥ 0.8× pass-2) with steady p50 ≥ 10× the converged p50; both rungs ≥
   boundary converge. The cliff brackets R.
4. **Pressure-scaled aging observed:** pass-1 cgroup `pgscan` is monotone
   non-decreasing as caps descend fits → deep.
5. **The sort-not-needed datum:** at the fits rung, `active_file` stays
   ≪ R (prediction *est.*: < 0.25×R) through all passes — reclaim never
   runs, nothing is promoted (the 24 GB / 0.2 GB analogue).

**Predictions (*est.*, write-before-run):** marginal converges in ~4–7
passes, boundary in ~2–4; pass-3 inversion ratio between 2× and 20×. If
marginal converges before pass 3 (artifact invisible in the fixed window),
the pre-declared tuning knob is: grow L and/or move the marginal cap toward
exactly 1.00×D — tuning is legitimate calibration, but any tuned values are
reported as tuned, and the bars above are then re-judged on fresh cells.

## Validation against the 150M measurements (the "not search-engine-specific" claim)

PASS on bars 1–5 reproduces, on content-free seeded files, every signature
R1/R2/R3 measured on the real index: the fixed-window inversion (R1 §1),
identical regime ordering fits/marginal/boundary/thrash, the same-steady-state
convergence (R2), the cliff at ≈R (R2's 10–11 GB), monotone pgscan and the
active_file gauge (R2 §7.3), and majflt-trajectory shape as the diagnostic.
The comparison is QUALITATIVE (signature match) by design — absolute
latencies differ (SSD-backed overlay vs the staged index path) and ms/fault
is reported, not compared. Access structure is uniform-random here vs the
engine's traversal; R3's finding (the inversion is carried solely by
convergence-trajectory position, per-query fault distribution refuted) is
what licenses this simplification — if the synthetic FAILS while the real
stack reproduces, that discrepancy is itself a finding (access-structure
dependence) and must be recorded, not tuned away.

## Environment (recorded before run)

WSL2 kernel 6.18.33.2-microsoft-standard-WSL2, `lru_gen` expected absent
(classic two-list — verify and record), 56 GB shared pool, quiet box
required (R2's host-noise lesson: replicate at marginal + boundary rungs).
Known limitation, recorded now: this validates the WSL2/classic-LRU regime
only; native-Linux + MGLRU arms are publication-gate items 2–3, not this
spike.

## Deliverables

`spike/convergence_repro/`: `Dockerfile` (debian-slim + fio + vmtouch),
`jobs/*.fio`, `run_ladder.sh` (orchestrator, host side), `cell.sh`
(in-container), `analyze.py` (bars verdict from raw JSON), results under
`data/eval_results/convrepro_*.json` + a summary MD. Build executed by an
Opus 5 subagent; review, validation verdicts, and documentation by the
session lead. Efficacy recording per CLAUDE.md: numbers + dates + result
paths land in this directory's RESULTS.md and are pointed to from
`04_CONVERGENCE_ARTIFACT.md` on completion.
