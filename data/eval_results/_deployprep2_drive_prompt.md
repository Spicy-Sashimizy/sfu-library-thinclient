# DRIVE PROMPT — deployprep wave 2: warmup hook, warm capacity, portable-stack manifest

You are the in-container execution half of `deployprep` wave 2 (2026-07-17).
Wave 1 (WI-1..5) is COMPLETE and committed — read
`data/eval_results/_deployprep_timing.md` + git log for what exists; do NOT
redo any wave-1 work. This wave turns wave-1's findings into the next three
deliverables for the same two end goals (dependable tech demo; portable
handout). You author ALL scripts, run the measurements, write the docs.
You CANNOT run docker or privileged probes — host-queue anything that needs
them (`data/eval_results/_deployprep_host_queue.md`, same protocol as wave 1;
the monitor reviews on event, expect minutes-to-1h latency).

## Binding rules — identical to wave 1 (read `_deployprep_drive_prompt.md`
§Binding rules + §OWNER CONSTRAINTS + §STAY-ALIVE, they apply verbatim)

Highlights, non-negotiable: git pull before commits; explicit `git add
<files>` only; `data/seismic_150m/` READ-ONLY; no docker/container restarts;
absolute dates; F6 discipline (recompute headline numbers from raw before
they enter a doc); pre-register measured experiments in backlog doc 11 before
running; NO demo deployment / NO DigitalOcean spend / NO TrueNAS / NO
served-default flips (propose via host queue instead); STAGING ONLY.

## Time budget + timing ledger

Hard stop for new work: **2026-07-17 06:56Z**; then session-end doc sync
(re-read `docs/THIN_CLIENT_SWAP.md` + `docs/README.md` against what you
changed), final ledger update, commit, push, exit. Continue the SAME ledger
`data/eval_results/_deployprep_timing.md` with rows WI-6/WI-7/WI-8 (start row
at item start, finish row at final commit — owner ETA tracking).

## Work-queue (strict order)

### WI-6 (demo) — startup-warmup hook + recovery-to-first-good-query
Context: WI-3's measured gap (`docs/infrastructure/DEMO_DEPENDABILITY.md` —
watchdog health-recovery 2.4 s but a cold-restarted serve answers first
queries at the multi-second cold-fault floor; 829 dead-window errors in the
kill test). Prior art to REUSE, not reinvent: the F6 prefault machinery
(`prefault_ranges` pyo3 hook + hot-set sidecars, `docs/disk_streaming_research/`
— F6 measured cold p95 4.66→1.67 s) and/or a fixed warmup query set replayed
at startup. Guiding idea: the staging serve gains an env-gated warmup phase
at (re)start; /health distinguishes "up" from "warm"; the watchdog waits for
warm before declaring recovery. Deliverable: hook + a re-run of the WI-3
induced-failure cell measuring recovery-to-first-good-QUERY (not just first
healthy /health) before vs after the hook, appended to DEMO_DEPENDABILITY.md
with raw result paths.

### WI-7 (demo) — warm-state concurrent capacity
Context: WI-3's baseline sweep measured the COLD floor (~4–6 s p50 — honest
but not the demo's steady state). Guiding idea: pre-warm the serve (WI-6
hook or a warmup pass), verify warm state (majflt quiet), then re-run the
concurrency sweep 1/4/8/16 (+32 if stable) → warm p50/p95/error/qps. This is
the demo's real capacity figure and the input the DO-sizing doc needs (do
NOT provision anything — numbers only, recorded in DEMO_DEPENDABILITY.md
with a pointer row added to `docs/bmp_decommission_plan/DO_SIZING.md` if the
numbers change its assumptions).

### WI-8 (portable) — portable-stack dependency manifest
Context: the handout installer must bundle exactly what the serve path
needs; today that's implicit. `docs/seismic_150m_testbed/16_SUBSET_CORPUS_PILOT.md`
(subset blockers), WI-4's v3 .so (`spike/seismic_upstream/target/portable_so/v3/`),
and the earlier installer research. Guiding
idea: produce the authoritative manifest of a Qdrant-free, docker-free
portable bundle: (a) runtime imports audit of the staging serve path (what
python packages actually load, with versions); (b) artifact inventory —
which index/model/sidecar files each leg needs, with per-file sizes measured
(150M figures as-is + the subset-tier projection formula); (c) a staging
probe proving the serve runs with the seismic backend + v3 .so + no Qdrant
reachable (env-selected, no served-default flip); (d) the delta list of
what's still missing for a real installer (Windows/mmap questions, spool
re-export, licensing check) with owning docs. Deliverable: a new
`docs/infrastructure/PORTABLE_STACK_MANIFEST.md` + machine-readable
`data/eval_results/portable_stack_manifest.json` + README index row.

## Session end

Doc sync, ledger rows finalized (unstarted = NOT-STARTED), queue file clean,
commit, push, exit.
