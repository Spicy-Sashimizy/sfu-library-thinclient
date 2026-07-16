# DRIVE PROMPT — R3 kernel-ledger spike: build, verify, join, document

You are the in-container execution half of R3 (design:
`docs/seismic_150m_testbed/15_R3_KERNEL_LEDGER_SPIKE.md`; pre-registered bars:
`docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` §R3; theory background:
`docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`).
Read all three BEFORE writing anything. You author ALL scripts, run the
analysis, and write the docs. You CANNOT run docker, privileged probes, or
memory-capped cells yourself (no docker daemon in here; read-only cgroups) —
those are executed on the host via the host-queue protocol below. Never try
to run them yourself.

## Binding rules (CLAUDE.md — non-negotiable)

- `git pull` before your first action and before each commit; stage files
  EXPLICITLY (`git add <file> <file>`) — NEVER `git add .`, `git add -A`, or
  `git commit -a`. The tree carries multi-GB runtime state.
- Shards under `data/seismic_150m/` are irreplaceable — READ-ONLY. Anything
  about them looks broken: STOP, write a note, commit, exit. Never touch /tmp.
- Do not restart containers, do not run docker, do not kill processes you did
  not start. Absolute dates only (e.g. 2026-07-15).
- F6 discipline: a number that fails a verification check is recorded as
  INVALID, never quoted as a result. Refuted expectations are valid results —
  do not massage them.

## Host-queue protocol

Host actions are requested by appending a block to
`data/eval_results/_r3_host_queue.md`:

    ## REQ-<n> <UTC timestamp>
    status: PENDING
    command: <exact host command, usually bash scripts/seismic_testbed/r3_...>
    why: <one line>

Commit the queue file and every script it references BEFORE marking PENDING.
An hourly host monitor reviews the script, runs it, writes output to
`data/eval_results/_r3_hostreq_<n>.log`, and flips the block's status to
DONE or REJECTED (with a reason). Poll every ~5 min (`sleep 300`); while
waiting, continue any work that does not depend on the result. The monitor is
hourly — expect up to ~1 h latency per request, so BATCH requests where
possible. Stall rule: if 3 hours pass with a PENDING request untouched, write
`data/eval_results/_r3_stall_note.md` with what you see, commit, exit.

**STAY-ALIVE RULE (learned 2026-07-16: the first R3 session lost itself
here).** You run under plain `claude -p`: your process TERMINATES the moment
you end your turn. There is no "pause point", no background Monitor, no
scheduled wakeup that survives — a previous session armed those and died
waiting on a flip it never saw. While ANY host request is PENDING or any cell
is RUNNING, you MUST spin-wait inside your turn with literal Bash
`sleep 300` calls in a loop, re-reading `_r3_host_queue.md` and the status
files after each sleep. Only end your turn when the drive prompt is fully
complete (Phase D committed), the spike is parked, or the 3 h stall rule
fires. If you find prior-session work already committed (scripts, REQ
statuses), do NOT redo it — read the queue + logs and continue from the
first incomplete step.

## Phase A — capability gate G-R3-0

Write `scripts/seismic_testbed/r3_capability_probe.sh`, designed to run ON THE
HOST via a privileged `--pid=host` container (model the docker invocation
style on `scripts/seismic_testbed/r2_host_orchestrator.sh`, including
`MSYS_NO_PATHCONV=1`). It must check and print, unambiguously PASS/FAIL each:
kernel version (cachestat needs ≥ 6.5); `/sys/kernel/btf/vmlinux`; the four
tracepoints (`filemap:mm_filemap_delete_from_page_cache`,
`filemap:mm_filemap_add_to_page_cache`, `vmscan:mm_vmscan_lru_shrink_inactive`,
`vmscan:mm_vmscan_memcg_reclaim_begin`); a trivial bpftrace one-liner actually
firing; `cachestat` (x86_64 syscall 451) returning sane counts on a
known-resident file. Handle bpftrace not being installed in the probe
container (apt-get it or use a bpftrace image — your choice, document it).
Submit as REQ-1. On hard FAIL of BTF/tracepoints/bpftrace: park per §R3 —
commit the probe log, record the park in backlog §R3 with the failing check,
and skip to Session-end. cachestat-FAIL alone → mincore fallback, recorded.

## Phase B — instruments (write while REQ-1 is pending)

All new files under `scripts/seismic_testbed/`, committed as built:

1. `r3_ledger.bt` — bpftrace: the two filemap tracepoints (+ vmscan
   begin/end for batch context) → `(ns, event, ino, pgoff)` lines. Filter to
   the shard inode set IN-PROBE (read it from a generated header/map — do not
   post-filter, the event rate would swamp the buffer). Count and print
   drops. Output must be machine-parseable.
2. `r3_inode_map.py` — inventory `(path, dev, ino, size)` for every file of
   both mmap shards used by the driver → `data/eval_results/_r3_inode_map.json`
   + whatever include/map `r3_ledger.bt` consumes.
3. `r3_refault_probe.bt` — kprobe/kfunc on `workingset_refault` →
   `(ns, ino, pgoff, refault_distance, activated)`. If distance cannot be
   extracted under this kernel's BTF, downgrade to `(ns, ino, pgoff,
   activated)` and RECORD the downgrade in the summary — never silently.
4. `r3_cachestat_map.py` — per-extent residency snapshot (cache / evicted /
   recently_evicted) across all shard slabs via syscall 451 (ctypes);
   mincore fallback if REQ-1 said so. Fixed extent size (e.g. 2 MiB) —
   document the choice.
5. `r3_query_extent_map.py` — per-query touched-extent map for the same 40
   pre-encoded queries, via the `search_visited` pyo3 surface
   (`mmap_index.rs:251`, the F1 generator's surface — NO Rust changes) →
   `data/eval_results/_r3_query_extent_map.json`.
6. `r3_kernel_ledger_driver.py` — extend `r2_convergence_ladder.py` (same
   convergence rules, min 3 / max 12, near_zero ≤ 2,500 / plateau; same
   result-JSON schema plus): pass-boundary CLOCK_MONOTONIC ns timestamps in
   the JSON (to slice the ledger by pass), and an optional
   `--cachestat-between-passes` flag invoking instrument 4.
7. `r3_host_orchestrator.sh` — extend `r2_host_orchestrator.sh`: per
   instrumented cell, start a privileged `--pid=host` tracer container
   running instruments 1+3 (logs to `data/eval_results/_r3_<label>_ledger.log`
   / `_refault.log`), drop caches, run the capped cell, stop the tracer.
   Cell order: 16g-ctrl, 12g-ctrl (no tracer), then 16g-instr, 12g-instr.
   Status files `_r3_<label>.status` RUNNING/DONE/FAIL and
   `_r3_cells.ALLDONE`, exactly in the R2 style.

## Phase C — cells + per-cell verification

Submit the orchestrator as REQ-2 (after REQ-1 PASSES and Phase B is
committed). As each cell lands, verify before recording — the FULL R2
checklist from `data/eval_results/_r2_convergence_drive_prompt.md`
(swap_confounded false; convergence.kind; pass-1 majflt ≥ 50k; ms/fault
0.1–2.0; converged p50 ≥ ~15 ms; cg_delta activity), PLUS the R3 checks:
ledger drop rate ≤ 1% (else that ledger INVALID); instrumented converged p50
≤ 1.10× its control (else instrument overhead fails the bar — record, then
request ONE downsampled rerun via the queue); ledger pgoffs ⊆ inode map;
ledger refault count within ~2× of the cell's shard-attributable majflt
(gross mismatch = broken filter — INVALID). Latency numbers are ONLY ever
quoted from control cells. Append each verified cell as a row to
`data/eval_results/_r3_ledger_summary.md`; commit result + status + log +
summary per cell, R2-style messages `data(r3): <label> — <verdict>`.

## Phase D — the join + write-up (only after ALLDONE)

1. `r3_join_analysis.py`: join ledger × refault events × between-pass maps ×
   query-extent map on (ino, pgoff→extent) and pass windows. Emit per
   instrumented cell: (a) residue map per pass boundary; (b) pass-3
   residual-fault attribution per query; (c) refault-distance distribution vs
   concurrent active_file per pass. Verdict each of the four §R3
   pre-registered expectations CONFIRMED / REFUTED / UNCLEAR, in
   `_r3_ledger_summary.md`.
2. Update backlog §R3 PRE-REGISTERED → MEASURED (numbers, file paths,
   verdicts, absolute date). Fill doc 15 §7 with results (`*est.*` on
   anything unmeasured). Append `## §8 Per-page attribution (R3)` to
   `04_CONVERGENCE_ARTIFACT.md` — what the ledger adds to §2/§4/§7,
   explicitly including any refuted expectation.
3. Do not create new doc files; do not edit `docs/README.md`. Commit docs +
   summary together, push, exit.
