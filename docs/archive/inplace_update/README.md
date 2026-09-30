# inplace_update/ — in-place bit-update spike (custom v3 encoder/decoder + bit updater)

> **CLOSED MEASURED 2026-09-30** — the pre-registered GO rule of `06_INPLACE_SPIKE_PLAN.md` read NO-GO: bar S0-1 measured a long-list dead-slot coverage of **0.019** (95 % CI 0.018–0.020) against 0.80. In one quarter 27 % of shard 0's docs are updated and 15 % more are new while deletions free 6 %, and a list cannot grow, so dead-slot reuse cannot absorb the churn (`inplace_s0_20260930.json`). Nothing in-place replaces it: updates stay with delta generations (`docs/delta_ingest/`). The v3 encoder/decoder is exact (B1 460/460, +1.3 % per query) and the +tail variant was built, but they remove the wrong obstacle. Full record: `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` results table and §"NO-GO 2026-09-30". Not current; do not resume.

**Status:** CLOSED MEASURED 2026-09-30

Opened 2026-09-29 (brief `05_…`), pre-registered the same day (`06_…`),
measured 2026-09-29 → 2026-09-30, closed 2026-09-30 by its own GO rule.

| Doc | What |
|---|---|
| `05_INPLACE_BIT_UPDATE_BRIEF_2026-09-29.md` | the dispatch brief (design: dead-slot reuse, bounded lists with eviction, epoch bits + atomic publish; cloud addendum P1/P2) |
| `06_INPLACE_SPIKE_PLAN.md` | pre-registration, four addenda, **the results table with every measured row**, and §"NO-GO 2026-09-30" |
| `07_INPLACE_PAUSE_HANDOVER_2026-09-29.md` | operational handover: what ran when, the queues, scratch on disk, the staged-shard incident, owner items |

Code and its own docs (evidence at the closing commit; paths as they were
when the runs were made — to re-run, check out the parent of the closure
commit, because the scripts import `spike.inplace_update` and name
`scripts/experiments/` paths):

| Was | Now |
|---|---|
| `spike/inplace_update/` (Stage-0 harness modules, `FORMAT_V3.md` spec revs 1–6, `UPDATER_DESIGN.md`, both reviews, `STAGE1_ENCODER_FINDINGS.md`, `STAGE1_UPDATER_FINDINGS.md`, the Rust updater crate `updater/`) | `spike/archive/inplace_update/` |
| `scripts/experiments/eval_inplace_*.py` (S0-1/S0-2/S0-3, P1, B1 parity, W1, bench B2–B7, A2b read, tail read) | `scripts/archive/inplace_update/` |
| `spike/seismic_upstream_inplace_v3*.patch` (fork commits a3173d1..328bf51 and c7b4b54: v3 encoder/decoder, A2b unit read path, guards, +tail, A2b oracle fix; they touch `src/inplace_v3.rs` and the served read path `mmap_io.rs`, `mmap_index.rs`, `pylib/`) | `spike/archive/inplace_update/patches/`. In `spike/seismic_upstream`: fork `main` reset to 2c4d863 on 2026-09-30; the spike commits a3173d1..328bf51 live on fork branch `inplace-v3` (c7b4b54 on `b1-guard`); the installed `.so` (built 2026-08-10) never contained them; do not merge `inplace-v3` into `main` (owner decision 2026-09-30: the +1.3 % B1 per-query cost is not acceptable on the serving path). |

Results files (kept in place, `data/eval_results/`): `inplace_s0_20260930.json`,
`inplace_b_20260929.json`, `inplace_writeunit_20260929.json`,
`inplace_b_updater_20260929.json`, `inplace_b_updater_20260930.json`,
`inplace_b_updater_synthetic_2026092{9,30}.json`, `inplace_b_updater_synthetic_r7off_20260930.json`,
`inplace_b_updater_indicative_v31_20260930.json`, `inplace_a2b_read_20260930*.json`,
`inplace_tail_read_20260930.json`.

What survives as input to live tracks: the measured quarter churn (27 %
updated + 15 % new + 6 % deleted of a shard), the P1 finding that
re-encoding byte-identical text does not reproduce the stored vector (no
vector diff can filter churn), the dv-v2 spare-bit and mask-cost
measurements, and the A1(N=1) generation-build cost (16.4 s, 0.49 GB device
bytes for 32,155 docs). The churn and P1 facts are restated in
`docs/THIN_CLIENT_SWAP.md` and the `docs/README.md` `delta_ingest/` row; the
rest live only in the `06` results table here.

Bare names `02_DESIGN.md`, `03_SPIKE_PLAN.md`, `04_*.md` inside `05`–`07`
refer to `docs/delta_ingest/`. Bare `06_…`/`07_…` names inside the spike docs
refer to this folder.
