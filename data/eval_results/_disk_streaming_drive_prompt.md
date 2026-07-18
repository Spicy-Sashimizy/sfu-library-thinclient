# DRIVE PROMPT — Disk-Streaming Research Program (colibrì-derived, F1–F6)

You are executing the full research program pre-registered in
`docs/disk_streaming_research/` (01 cross-project study → 02 verification →
03 min-RAM design map). Work top-to-bottom; do not reorder phases; every
phase ends with a committed result file under `data/eval_results/` and a
doc update in the same commit.

## Binding rules (from doc 12 §2 + CLAUDE.md — non-negotiable)

- Gates are judged on the **worst-case shard**, never the mean. n≥100 queries
  per latency cell; report p50 AND p95; 2+ reps; paired ratios only.
- **Quality-free levers first**: nothing that can move ranking ships before
  residency-only levers are exhausted. Every lever here is residency-only —
  assert T1 bit-identity anyway after each phase.
- Kill-switch discipline: all new behavior behind
  `SFU_SEISMIC_PIN_BUDGET_GB` (=0 → today's behavior, byte-identical path).
- Pre-register bars in `docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md`
  BEFORE running any measurement; absolute dates; `*est.*` markers on
  anything unmeasured. Same-commit doc rule applies (03 + THIN_CLIENT_SWAP.md).
- Stage files explicitly (`git add <file>` — never `git add .`); commit and
  push after each phase.

## Phase 0 — Clear the build gates (G-a, G-b from doc 03)

0a. **G-b (E8 Stage-2 lands).** All 8 shards are rebuilt and gated
    (commits a1bcb51…7cb8ca6). Finish the flip: commit the federated gate
    results (`_e8s2_q7_federated_v2_20260713.json` + cell files), flip the
    serving manifest to the e8 v2 shard set, re-run the Q7 hybrid smoke
    (bars: cold ≤1.05× seq-cold, warm ≤1.05× par-warm, T1 20/20). The
    operator issuing this prompt has signed off on the flip.
0b. **G-a (Q12 rerun, production-shaped).** Re-run
    `scripts/q12_access_skew_probe.py` against the **E8 v2 shards** with a
    production-shaped query log (not the 120-diverse synthetic set).
    Pre-registered bars unchanged: repeat-rate ≥25%, hot-set-80 ≤4 GB.
    Prior result was GRAY (repeat 85% PASS, hot-set-80 4.20 GB — 5% over).
    Record GO / NO-GO / GRAY in `11_EXPERIMENT_BACKLOG.md` and doc 03.
    - GO or GRAY-live-leaning → proceed.
    - Hard NO-GO (hot-set-80 ≫ 4 GB, e.g. >8 GB) → stop after Phase 1+2
      (they are useful regardless) and write up why F3 is parked.

## Phase 1 — F2 sidecar format + F1 offline hot-set generator (script-only, zero serving risk)

- Sidecar: `<shard>.mmap/hotset.json` = sorted `(page_start, page_len)`
  extents + `forward_format_version` + `forward_reordered` + generation
  date. Loader must refuse-and-log on key mismatch (E8-style reconversion
  must fail loud, not pin garbage).
- Generator: offline script over `search_visited` output (the pyo3 surface
  already returns visited sets — `mmap_index.rs:251`; NO Rust changes).
  Greedy ranking by touch count = the Q12 counter. Emit per-shard sidecars
  from the Phase-0b run.
- Deliverable: script + sidecars for all 8 v2 shards + doc 03 §5 status
  update.

## Phase 2 — F4 floor prefault → floor pin

- Extend `prefault_floor` (Q9, `SFU_SEISMIC_PREFLOOR_AT_LOAD`) with an
  optional mlock flag over the same slabs (~1.5 GB structural floor).
- Bar (pre-register): floor pages show zero re-faults across a
  memory-pressure pass on the capped host; warm p50 ratio ≤1.05× vs
  pin-off; T1 identical.

## Phase 3 — F3 `mlock_ranges` pin tier + budget check

- pyo3 hook on `MmapSeismicIndex`: `mlock_ranges(extents)`; pin
  ≤ min(`SFU_SEISMIC_PIN_BUDGET_GB`, `MemAvailable` − floor − headroom),
  largest-coverage extents first.
- A/B on the 32 GB host regime (the 15.8 s warm≈cold cell), dials 0 / 1.6
  (hot-50) / 4.2 GB (hot-80). Pre-register bars before running; doc 02 §6
  revised estimate to beat is ~1.5–3× p50 — treat as *est.*, not target.
- No-OOM guarantee is the budget check: assert VmSwap≈0 and no OOM-killer
  events in every cell.

## Phase 4 — F5 `release_pages_except(pinned_extents)`

- Range-split `MADV_DONTNEED` around pinned extents (plain DONTNEED EINVALs
  on mlocked ranges — doc 02 §4). Needed for the sequential/hybrid cold arm
  only; parallel path never releases.
- Bar: sequential per-shard transient residency ≈1 shard preserved with
  pinning ON.

## Phase 5 — Correctness re-gate with pinning ON

- Re-run T1 bit-identity (100 q) + the G6 overlap harness with F3+F4+F5
  active at both dial settings. Expected trivially identical — assert it.
  Any mismatch = stop, revert to dial 0, investigate before proceeding.

## Phase 6 — Cold-start prefault-hotset-at-load (the cold-p95 lever)

- At load: prefault (NOT mlock) the F2 sidecar extents, Q9-style.
- Re-run the Q7 federated cold/warm benchmark (100 q, 2 reps, all three
  federation modes). Baselines to beat (measured 2026-07-13, E8 v2):
  hybrid cold p50 783–899 ms / **p95 4.6–4.9 s**; warm p50 115–120 ms /
  p95 177–182 ms. Doc 02 §6 *est.* for the hot fraction: 1.3–2× cold.
  Report the cold p95 delta explicitly — it is the number this phase exists
  to move.

## Explicitly OUT of scope (measured-out — do not build)

- **F7 software LRU proper** (ESlot/eclock): rung 3 — only if Phase-3 A/B
  measurably plateaus, with the plateau numbers written down first.
- **F8 PILOT prefetch**: parked; cold path is channel-contended (seq cold
  2.2 s < par cold 2.7 s; three adjacent negative results).
- **F9 pread + buffer pool**: deferred; unreclaimable anon RAM is strictly
  worse for the min-RAM goal absent evidence F3 hit the kernel ceiling.

## Session-end

Doc sync per CLAUDE.md: update `docs/disk_streaming_research/03` status
lines from DESIGN ONLY → per-phase MEASURED with numbers + result-file
paths, update `docs/THIN_CLIENT_SWAP.md` if the serving path changed
(Phase 0a flip does), update `docs/README.md` index if docs were added.
