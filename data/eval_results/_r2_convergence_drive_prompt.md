# DRIVE PROMPT — R2 fine convergence ladder: verification + documentation loop

You are the in-container analysis half of the R2 experiment (backlog §R2 in
`docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md`; theory background in
`docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`).
A host-side orchestrator OUTSIDE this container
(`scripts/seismic_testbed/r2_host_orchestrator.sh`) is running memory-capped
sibling-container cells one at a time. You cannot run cells yourself (no
docker daemon in here) and must never try. Your job: as each cell lands,
VERIFY it, record it, commit it; when all rungs are done, write the analysis.

## Binding rules (CLAUDE.md — non-negotiable)

- `git pull` before your first action and before each commit.
- Stage files EXPLICITLY (`git add <file> <file>`) — NEVER `git add .`,
  `git add -A`, or `git commit -a`. The tree carries multi-GB runtime state.
- The shards under `data/seismic_150m/` are irreplaceable — READ-ONLY. If
  anything about them looks broken: STOP, write a note, commit it, exit.
  Never "fix", move, or re-convert a shard. Never touch /tmp.
- Do not restart containers, do not run docker, do not kill processes you
  did not start.
- Absolute dates only (e.g. 2026-07-14), never "today".

## Files and signals (all under `data/eval_results/`)

- Cell results:  `r2_cap<N>g[_rep2]_<YYYYMMDD>.json`
- Cell logs:     `_r2_cap<N>g[_rep2]_drive.log`
- Status files:  `_r2_cap<N>g[_rep2].status` — RUNNING / DONE / FAIL rc=N
- All-done flag: `_r2_ladder.ALLDONE`
- Rung plan (in run order): 17 16 15 14 13 12 11 10 9 24 6, then replicates
  `_rep2` at 16, 13, 11. A mid-band rung takes roughly 15–45 minutes.

## The loop

1. `git pull` once at start.
2. Poll every ~5 minutes (`sleep 300`) for status files newly DONE or FAIL.
3. For each newly DONE cell: run the verification checklist below, append a
   row to `data/eval_results/_r2_ladder_summary.md` (create it on the first
   cell: a markdown table `cap | rep | passes_to_converge | kind |
   converged p50/p95 ms | final majflt | ms/fault | pass1 majflt | verdict`),
   then commit and push exactly these files:
   `git add data/eval_results/r2_cap<...>.json data/eval_results/_r2_cap<...>.status data/eval_results/_r2_cap<...>_drive.log data/eval_results/_r2_ladder_summary.md`
   with message `data(r2): cap <N>g cell — <p50> ms, <k> passes, <verdict>`.
4. For a FAIL cell: append a FAIL row with the last ~10 log lines quoted in
   the summary file, commit the status+log+summary the same way, continue.
   Do NOT retry the cell yourself.
5. When `_r2_ladder.ALLDONE` exists and every listed rung is processed:
   do the final write-up (below), then exit.
6. Stall rule: if 2 hours pass with no status change and no ALLDONE, write
   `data/eval_results/_r2_stall_note.md` describing exactly what you see
   (statuses, newest file mtimes), commit it, and exit.

## Verification checklist — EVERY cell, before its row is written

F6 discipline (2026-07-14 incident: a drive session once recorded a "150×"
win where all 300 queries had silently failed). A number that fails a check
is recorded as INVALID, never quoted as a result.

- `swap_confounded` must be false.
- `convergence.kind` is one of near_zero / plateau / maxpass; `maxpass`
  means UNCONVERGED — mark the row `unconverged`, its p50 is NOT steady state.
- Cache-contamination guard: pass-1 `majflt` must be ≥ 50,000 for caps
  ≤ 17g (the cold fill is real). If it is tiny, the pre-cell drop_caches
  failed — verdict INVALID.
- `ms_per_fault` in passes with majflt > 0 should sit roughly 0.1–2.0 ms;
  wildly outside → flag it.
- Converged p50 must be ≥ ~15 ms (traversal-only; the uncapped floor is
  ~18 ms). A p50 below 10 ms, or majflt ≈ 0 at cap ≤ 12g, is a broken cell,
  not a win — verdict INVALID.
- `per_pass[].cg_delta` should show pgscan/pgsteal activity in passes where
  majflt is large; all-zero cg_delta under heavy faulting means the cgroup
  instrumentation failed — note it (cell still usable for latency/majflt).

## Final write-up (only after ALLDONE)

1. Finish `_r2_ladder_summary.md` with three derived tables: converged p50
   vs cap (ascending cap); passes-to-converge vs cap; per-pass pgscan and
   workingset_refault_file trajectories for caps 9–17.
2. Update `docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` §R2 from
   PRE-REGISTERED to MEASURED: the summary table, the measured cliff
   location (the cap where converged p50 jumps from ~20 ms to seconds — this
   is the empirical repeat-set size), result-file paths, absolute date, and
   an explicit verdict on each of the four pre-registered expectations
   (confirmed / refuted / unclear — refuted is a valid result, do not
   massage it).
3. Append a `## §7 The fine ladder (R2)` section to
   `docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`:
   cliff location; whether passes-to-converge rises with cap in the marginal
   band (the Che/Fagin prediction, §4); whether pgscan-rate scaling with
   pressure was directly observed in cg_delta (§2.2 upgraded from inference
   to observation, or not). Mark anything unmeasured `*est.*`.
4. Do not create new doc files; do not edit `docs/README.md`.
5. Commit the docs + summary together, push, exit.
