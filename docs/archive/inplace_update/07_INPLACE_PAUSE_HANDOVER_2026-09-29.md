# 07 — Pause handover: in-place bit-updater spike, state at 2026-09-29 09:25Z

> **CLOSED MEASURED 2026-09-30** — the pre-registered GO rule of `06_INPLACE_SPIKE_PLAN.md` read NO-GO: bar S0-1 measured a long-list dead-slot coverage of **0.019** (95 % CI 0.018–0.020) against 0.80. In one quarter 27 % of shard 0's docs are updated and 15 % more are new while deletions free 6 %, and a list cannot grow, so dead-slot reuse cannot absorb the churn (`inplace_s0_20260930.json`). Nothing in-place replaces it: updates stay with delta generations (`docs/delta_ingest/`). The v3 encoder/decoder is exact (B1 460/460, +1.3 % per query) and the +tail variant was built, but they remove the wrong obstacle. Full record: `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` results table and §"NO-GO 2026-09-30". Not current; do not resume.

**Status:** CLOSED MEASURED 2026-09-30

**State 2026-09-30 03:30Z: RESUMED again (§0 below). Measured since the
pause: B1 PASS, W1, B4 (real shard), M4, M5, P1 control; the rest is queued
or in build.** Earlier state line, kept: PAUSED by the owner 2026-09-29,
RESUMED by the owner 2026-09-29 (agents redeployed after the staging fix),
NOTHING MEASURED at the pause. Every row of
the results table in `06_INPLACE_SPIKE_PLAN.md` is still NOT RUN. No code
exists for the bit updater or for the format-v3 encoder/decoder; both are
held behind the GO rule of `06_INPLACE_SPIKE_PLAN.md`. Pilots and smoke runs
mentioned below are not results.

Read order for whoever resumes: this file, then `06_INPLACE_SPIKE_PLAN.md`
(bars + addendum), then `04_IMMUTABILITY_RESEARCH.md` §"Addendum 2026-09-29",
then the brief `05_INPLACE_BIT_UPDATE_BRIEF_2026-09-29.md` with its two notes.

---

## 0. Resume 2026-09-30 03:30Z — what happened after this handover, what runs now

Written by the coordinator of the 2026-09-30 session. The results table of
`06_INPLACE_SPIKE_PLAN.md` carries every number; this section is the
operational state.

### 0.1 Measured 2026-09-29 21:50Z → 2026-09-30 00:44Z (all pushed)

| Item | Result | Where |
|---|---|---|
| B1 zero-patch parity | PASS 460/460; mask cost v3/v2 mean 1.0128 | `spike/archive/inplace_update/STAGE1_ENCODER_FINDINGS.md`, `inplace_b_20260929.json` |
| W1 write unit | LIST | same, `inplace_writeunit_20260929.json` |
| A2b unit-encoder identity, full shard 0 | 28,702 / 28,702 lists byte-identical (console result, `stage2/identity_full.json`; the findings note still says "queued") | `spike/archive/inplace_update/STAGE1_UPDATER_FINDINGS.md` |
| B4 real shard 0 | A2 and A2b place 0 docs on batch 1; A2b heap exhausted at 1.06 batches; A2-2p places 29,651 | `STAGE1_UPDATER_FINDINGS.md`, `inplace_b_updater_20260929.json` |
| M4 / M5 | M4 bar FAIL (27.7 ms/gen), GO line MET; M5 PASS | `spike/delta_ingest/M4_M5_FINDINGS.md` |
| P1 control | UNRELIABLE AS DEFINED (100 % of byte-identical docs re-encode differently) | `stage0/p1_control.json` |
| Stage-0 inputs | 110 part files (f = 0.1005) downloaded, routed, encoded (`stage0/partsout_f10`, `encode.log` rc=0 23:24Z) — §7 item 2 is resolved: S0-1 can now PASS | scratch |

### 0.2 What died at 2026-09-30 00:44Z (session end, nothing running afterwards)

- `stage2/real_run2.sh` mid-B2: A2's 3 reps had run (wall 19.0 / 14.0 /
  13.6 s) but nothing was saved; the A2b work copy was half-copied.
- `stage0/chain5.sh` at its `p1m7` step (P1 control had just finished).
- `stage1/job_a2b.sh` (A2b read-path build after the reserved-`gen` fix,
  then `eval_inplace_a2b_read.py`) never got the lock.

### 0.3 Relaunched 2026-09-30 03:30Z (host quiet, lock free, 16 cores, 31 GB)

- `stage2/resume_run.sh` (latency lock, cores 0-7), in order: B2 (A2, A2b,
  A2-2p × 2, then A1 N=1; 3 reps) → B5 (A2, A2b; 5 reps) → `job_a2b.sh`
  (build + A2b read test) → marker `stage0/STAGE0_GO` → B7 A2 → B7
  A2-2p/old-at-free → B7 A2-2p/old-at-fill → B7 A2b. Log
  `stage2/resume_run.log`, per-step logs `stage2/real_logs/`. *est.* wall:
  B2 + B5 + a2b ≈ 1 h; B7 A2 ≈ 2.5 h; each A2-2p ≈ 3 h; A2b ≈ 12 h (its
  readers loop 1.5 × T_apply = 345 s per SIGKILL trial).
- `stage0/chain6.sh` (NO lock, cores 8-15) waits for `STAGE0_GO`, then:
  P1 m7 → S0-1 → S0-2 smoke (scale 0.02) → S0-2 (+ S0-3) → traversal → P1
  record, into `data/eval_results/inplace_s0_20260930.json`. Log
  `stage0/chain6.log`. Timings from this chain are not deliverables, which
  is why it runs beside the B7 arms (B7 is a correctness bar).
- Two build agents (cores 8-15, no lock, scratch `stage3/`): encoder/
  decoder `+tail` (FORMAT_V3 §3.R4, v3.1 copy of shard 0 at
  `stage3/encoder/v3_1/`) and updater `+tail` + A2b heap reuse
  (`posting_free.bin`). Their findings go to `STAGE1_ENCODER_FINDINGS.md`
  and `STAGE1_UPDATER_FINDINGS.md`; the +tail bars are queued by the
  coordinator after both land.

### 0.4 Still the owner's

1. **B3 / B6 hold.** Neither §4 A (ro bind mount) nor §4 B (host ACL) of
   `docs/infrastructure/INDEX_WRITE_PROTECTION.md` is in place at 03:30Z
   (`findmnt` shows one rw 9p mount for the repo). The uncommitted
   `.devcontainer/*` edits in the tree are unrelated (zombie reaping, MCP
   registration, Pommel mirror). B3/B6 also need the v3 decoder behind
   `search_rrf` and (B6) the A3 rebuild — not started.
2. §7 item 4 (`src/lib/openalex.py` dollar budget): not started.

### 0.4a State 2026-09-30 05:40Z — NO-GO read; closure pending in-flight rows

Reconciled 2026-09-30 18:10Z: B7 A2 (rerun from zero, started 17:11Z under
the lock) and `chain8.sh` (S0-2 smoke relaunched 17:25Z after the ranges fix
45c5168d) are the two in-flight rows; the closure commit follows once both
stop. Nothing else of this track is pending.

Landed 2026-09-30: B7 A2 PASS 21:20Z; the S0-2 chain finished 23:43Z
(S0-2 FAIL, S0-3 FAIL, traversal and P1 record written). This closure
commit archives the track.

- S0-1 ran 04:17Z: **FAIL** (long-list coverage 0.019 vs 0.80). The frozen
  GO rule therefore reads **NO-GO** and the track is to be recorded CLOSED
  MEASURED (`06_…` §"NO-GO 2026-09-30"). B2, B5, the A2b read test and the
  P1 m7 leg are recorded in the `06` results table.
- Both build agents finished and pushed (encoder `c4caac6c`, `e8f85d1c`,
  `36910b43`, `68f7bdd1`, `ac47fa98`; updater `d456f4a3`, `1d069329`,
  `70fe49f4`, `cad6fa45`). The +tail variant exists on both sides and its
  read side is exact; it does not change the verdict.
- Landed for the record (no new dispatch; rerun 2026-09-30 from 17:11Z after the §0.4b overnight stop): B7 A2 **PASS** (SIGKILL 100/100, power-loss drop 100/100, pages 100/100; `inplace_b_updater_20260930.json` key `B7`, 2026-09-30T21:20:53Z); the S0-2 chain (`chain8.sh` smoke at floor 0.3 after the ranges fix `45c5168d`; `chain9.sh` full run at floor 0.14, swap-bound, killed 22:38Z at 80/460; `chain11.sh` 22:52Z–23:43Z on the memory-bounded harness `f6da4a1d` and the local twin copy `fcce74ca`: run → traversal → P1 record): S0-2 **FAIL**, S0-3 **FAIL** (T* = 0; traversal recorded), P1 `record` written (`supplementary.P1.control`, `.m7_vector`); and the non-vacuous A2b read rerun **PASS** 460/460, 4 queries changed, readers free (`inplace_a2b_read_20260930b.json`, 2026-09-30T05:21:00Z). None of these can change the NO-GO.
- Closure commit (banners, `docs/archive/inplace_update/`, `spike/archive/`
  and `scripts/archive/` moves, README rows, repointed references): DONE
  2026-09-30 after the three landed (this commit).

### 0.4b Stopped for the night by the owner, 2026-09-30 05:40Z

Both in-flight runs were stopped cleanly (a frozen process would have
corrupted B7's wall-clock trial timing, and both harnesses write results
only at the end of a run). Nothing on disk is at risk; every finished bar is
committed. Host idle, latency lock free, no eval process running.

- **B7 A2**: 77 / 100 SIGKILL trials had passed with 0 failures when
  stopped (per-trial lines kept in
  `stage2/real_logs/b7_A2_partial_stopped_0930T0537Z.log`; INCOMPLETE, not
  a bar result). Rerun from zero (*est.* 5 h):
  `flock /tmp/sfu_latency_measure.lock taskset -c 0-7 .venv/bin/python3 scripts/archive/inplace_update/eval_inplace_bench.py b7 --trials 100 --arms A2`
  (with `SFU_SEISMIC_STAGE_DIR`, `SFU_DELTA_ROOT`, `SFU_META_STAGE_DIR` set
  empty, from the repo root; `stage2/resume_run.sh` shows the wrapper).
- **S0-2 / S0-3**: the floor-0.3 smoke had completed its six quarters and
  was scoring when stopped; the full run had not started. Rerun:
  `bash /home/vscode/work/inplace_update/stage0/chain8.sh` (smoke → run →
  traversal → P1 record; cores 8-15; no lock; *est.* 2–3 h).
- Then the closure commit (`/tmp/...scratchpad/close_inplace_track.py` of
  the 2026-09-30 session, or by hand per `.claude/CLAUDE.md` §"Closed
  tracks"): banners, `docs/archive/inplace_update/`,
  `spike/archive/inplace_update/`, `scripts/archive/inplace_update/`,
  README rows, repointed references. Do not move the harness files while
  either run is executing them.

**Outcome 2026-09-30 (the reruns as they actually went).** B7 A2 ran
17:11Z–21:20Z under the lock: SIGKILL 100/100, power-loss drop 100/100,
pages 100/100 (`inplace_b_updater_20260930.json`; the 5 h estimate was for
all three phases). The S0-2 chain needed four launches: the 17:25Z smoke
crashed at its first scoring step (a `(start, length)` argument passed to
`sim.ranges(start, end)`, never executed by any earlier smoke; fixed
`45c5168d`); the 18:12Z full run asserted the candidate-pool floor guard at
quarter 6 (deletion-only tau 0.211 < floor 0.413 at `--floor-frac 0.3`;
rerun at 0.14, a wider pool, no bar changed); the 18:15Z run peaked at
21 GB, had 15.3 GB swapped out into the full 16 GB swap partition and
scored 80/460 queries in 84 min (killed 22:38Z; `f6da4a1d` bounds the
R_sim sort peak and mlockall's the run); the 22:29Z relaunch died on
ENOMEM reading the twin manifest over the 9p mount (`fcce74ca`: the run
reads a cmp-verified local-disk copy of the twin via `INPLACE_TWIN_DIR`).
The final run took 22:52Z–23:43Z end to end (`chain11.sh`). Results in
`inplace_s0_20260930.json` keys `s0_2`, `s0_3`, `supplementary`.

### 0.5 If this session dies too

(OBSOLETE 2026-09-30 23:43Z — nothing of this track runs; it is closed.)

Check `ps -eo pid,etime,cmd | grep -E 'resume_run|chain6|eval_inplace'`.
Nothing running → re-run `bash stage2/resume_run.sh` (it re-does finished
bars; delete the finished `run` lines from a copy to skip them) and
`bash stage0/chain6.sh` (touch `stage0/STAGE0_GO` first if B2/B5 are done).
Every harness restores work copies from `stage2/pristine` + the op log, so a
killed run leaves no state to clean beyond `stage2/work_*`.

---

## 1. What is done (all pushed)

| Item | Commit | Where |
|---|---|---|
| Brief merged from the cloud session, reconciliation note | `2a5d0da5` | `05_INPLACE_BIT_UPDATE_BRIEF_2026-09-29.md` |
| Pre-registration of arms and bars | `8c239e99` | `06_INPLACE_SPIKE_PLAN.md` |
| Sources of the brief re-read, novelty check, crash safety, OpenAlex terms | `3f99a748` | `04_IMMUTABILITY_RESEARCH.md` addendum |
| Plan addendum (B7 power-loss arm, mask cost, supplementary metrics) + brief correction note | `dc20bf2a` | `06_`, `05_` |
| Stage-0 harness: shard decoder, traversal, S0-1, S0-2/S0-3, prep | `b7456435`, `91d63ca2`, `a2a6dd06`, `b6fcb4d0`, `38276a9b` | `spike/archive/inplace_update/`, `scripts/archive/inplace_update/eval_inplace_s0_*.py` |
| M4 and M5 harnesses | `0f6f6c30`, `275c31a4` | `scripts/experiments/eval_delta_ingest_m4_read_amp.py`, `eval_delta_ingest_m5_reload.py` |

## 2. What is NOT RUN

| Bar | State | Note |
|---|---|---|
| S0-1 | NOT RUN, inputs cached | Cannot reach PASS from the cached sample: 6 part files of 1,098 is below the plan's 10 % minimum, so the outcome is FAIL or PARTIAL, and PARTIAL does not count for GO |
| S0-2 | NOT RUN | Insert/evict logic matches a naive reference on a synthetic shard; never run end to end on real data — run the scale-0.02 smoke first |
| S0-3 | NOT RUN | Computed inside the S0-2 run |
| M4 | NOT RUN, delta roots built | Only 3/5/10-topic pilots ran |
| M5 | NOT RUN | Harness compiles, never executed |
| B1–B7 | NOT RUN | Stage 1 not started |

## 3. Resume commands

Host must be quiet. Run M4/M5 ALONE (no Stage-0 job beside it): during the
pilots the Stage-0 prep used about 14.5 cores and made the latency pilots
noisy. Wrap every command in `timeout`. From the repo root.

Stage 0 (prefix each with
`PYTHONPATH=/home/vscode/work/inplace_update/pylocal`, a local copy of
`transformers` that works around open issue O12):

1. `.venv/bin/python3 scripts/archive/inplace_update/eval_inplace_s0_1.py run --out data/eval_results/inplace_s0_<UTCDATE>.json`
2. `.venv/bin/python3 scripts/archive/inplace_update/eval_inplace_s0_2.py run --scale 0.02 --out /home/vscode/work/inplace_update/stage0/smoke.json` (smoke, not a result)
3. `.venv/bin/python3 scripts/archive/inplace_update/eval_inplace_s0_2.py run --out data/eval_results/inplace_s0_<UTCDATE>.json` (S0-2 and S0-3)
4. `.venv/bin/python3 scripts/archive/inplace_update/eval_inplace_s0_2.py supp-traversal --out data/eval_results/inplace_s0_<UTCDATE>.json`
5. Write `spike/archive/inplace_update/STAGE0_FINDINGS.md` citing the results file.

M4 / M5 (each takes `/tmp/sfu_latency_measure.lock` itself):

1. `timeout 14400 .venv/bin/python3 scripts/experiments/eval_delta_ingest_m4_read_amp.py inproc-drive --federations parallel,sequential`
2. `timeout 7200 .venv/bin/python3 scripts/experiments/eval_delta_ingest_m5_reload.py drive`

## 4. Scratch left on disk (local disk, outside the repo)

| Path | Content | Size |
|---|---|---|
| `/home/vscode/work/inplace_update/stage0/` | 6 sampled OpenAlex part files + the M7 file, routed demand vectors, posting table of shard 0 (40,361,159 postings), shard doc ids, deletions in window, forward scan, encoded queries QA/QT/QD | ≈2.9 GB |
| `/home/vscode/work/inplace_update/pylocal/` | local `transformers` copy | 119 MB |
| `/home/vscode/work/inplace_update/m4/` | corpus (b) = 160,347 docs; `root_n1`, `root_n4`, `root_n8`, `root_n4c`, `root_n8c`; frozen `base_manifest.json`; pilots under `pilot/` | ≈8 GB |

## 5. Input facts found while preparing (inputs, not bar results)

- Shard 0 holds 18,799,322 docs; 1,131,292 of them appear in OpenAlex
  `deleted_ids.csv.gz` within the window. That file reaches back only to
  2026-08-14, so deletions of 2026-06-17 → 2026-08-13 are missing from it.
- The quarter window 2026-06-17 → 2026-09-15 is 1,098 part files,
  297,498,722 records.
- Update volume, from ONE sampled file scaled to the window: ≈11 M updated
  docs in shard 0 per quarter, ≈60 % of the shard (*est.*, high variance
  between files). If the full run confirms anything near it, in-place slot
  reuse is being asked to absorb a majority-of-shard rewrite per quarter.
- List cap in shard 0 is 5,250; 28,702 lists, so the per-list minimum side
  array is ≈112 KiB.
- S0-2 deviations from the plan, recorded in the script docstring before any
  run: quarters 2–6 apply Q1's deletion/update RATE (the count would exhaust
  the base); Q1's updated docs are uniformly sampled base docs standing in
  for the real ones. The encoded pool (~30 k vectors) is reused hundreds of
  times each, so a content-key overlap is recorded beside the gated doc-id
  overlap (not pre-registered).

## 6. Incident 2026-09-29 and the open product bug

- An M4 pilot deleted the STAGED copy of shard 0 in `/var/tmp/seismic_stage`
  (≈5.5 GB). It was re-staged at 08:54Z from the read-only source. Verified
  09:22Z by the coordinator: 8 shards + `staged_manifest.json` present
  (42 GB), `data/seismic_150m/` untouched (mtime 2026-06-30), latency lock
  free, no eval process running.
- Cause, **FIXED 2026-09-29** (same-path skip + copy-then-replace, pinned by
  `scripts/tests/test_seismic_shard_staging.py`, invariant in
  `docs/CODE_INVARIANTS.md`). As it was: `_stage_shards_local`
  (`src/lib/thinclient/retriever.py`) deletes the shards when the manifest it
  is given already points into the stage dir (source and destination are the
  same path, and the size check counts the `.staged_ok` marker). A serving
  process pointed at `staged_manifest.json` with `SFU_SEISMIC_STAGE_DIR` set
  destroys the stage. The repo `.env` re-inserts `SFU_SEISMIC_STAGE_DIR`
  into a process environment that had it removed. The M4 harness now sets
  the stage variables empty and aborts if a stage dir is visible.

## 7. Open points for the owner

1. **The M4 bar versus the host.** End-to-end `search_rrf` here takes
   seconds per query (pilots 2–3.7 s after priming; warmcache 2026-09-25 p50
   3.56 s), dominated by BM25F over the 9p mount. The +8 ms/generation bar
   and the 3 ms GO line are far inside that noise; the harness adds a paired
   per-query slope with a confidence interval (bar unchanged). Pilot
   indication only: delta-only serial work 3–26 ms per query across 1–8
   generations.
2. **S0-1 cannot PASS from the cached sample.** Reaching the plan's 10 %
   minimum means downloading ≈110 part files. Decide: download, or accept
   that the Stage-0 half of GO cannot be met and the GO rule reads NO-GO or
   is revisited by the owner before any number exists.
3. **Start the encoder/decoder ahead of GO?** Offered 2026-09-29, not decided.
4. **`src/lib/openalex.py`**: counts calls (900/day) while OpenAlex bills in
   dollars and single-record lookups are free (docs read 2026-09-29, see
   `04_IMMUTABILITY_RESEARCH.md`). Proposed: dollar budget from
   `meta.cost_usd`, default $1/day. Not started.
5. **Fix `_stage_shards_local`** (§6): DONE 2026-09-29.
