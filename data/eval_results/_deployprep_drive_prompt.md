# DRIVE PROMPT — deployprep: demo-dependability + portable-handout groundwork

You are the in-container execution half of the `deployprep` campaign
(2026-07-16). The project's two end goals are (a) a **fully dependable public
tech demo** of the 150M thin-client search stack and (b) a **portable handout
version** an end user can install on their own machine. Your job today is the
in-container groundwork for both, working the ordered items in §Work-queue.
You author ALL scripts, run the measurements, and write the docs yourself.
You CANNOT run docker, privileged probes, or memory-capped cells (no docker
daemon in here; read-only cgroups) — if an item genuinely needs one, request
it via the host-queue protocol below; never try to run it yourself.

Orient first: `docs/README.md` (index), `docs/THIN_CLIENT_SWAP.md`
(architecture), and per-item pointers below. Read before you write.

## Binding rules (CLAUDE.md — non-negotiable)

- `git pull` before your first action and before each commit; stage files
  EXPLICITLY (`git add <file> <file>`) — NEVER `git add .`, `git add -A`, or
  `git commit -a`. The tree carries multi-GB runtime state. Push after commit.
- Shards under `data/seismic_150m/` are irreplaceable — READ-ONLY. Anything
  about them looks broken: STOP, write a note, commit, exit. Never touch /tmp.
- Do not restart containers, do not run docker, do not kill processes you did
  not start. Absolute dates only (e.g. 2026-07-16).
- F6 discipline: recompute every headline number from its raw result file
  before it enters a doc. A number that fails verification is recorded as
  INVALID, never quoted. Refuted expectations are valid results — record them.
- Same-commit doc rule: results land in the owning doc in the same commit;
  unmeasured claims are marked `*est.*` or "IMPLEMENTED, EFFICACY UNMEASURED".
- New measured experiments on the SEISMIC serving path get pre-registered in
  `docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` (hypothesis + bars)
  BEFORE the run, per that doc's discipline.

## OWNER CONSTRAINTS (2026-07-16 — absolute)

- Do NOT deploy or spin up any public demo. Do NOT provision or spend
  DigitalOcean credit. Do NOT touch the TrueNAS server. Demo-related work is
  STAGING/PREP ONLY: code, scripts, local measurements, docs.
- Do NOT flip any served default (env manifest, backend selection) — propose
  flips as a host-queue request instead.

## Host-queue protocol

Host actions go through `data/eval_results/_deployprep_host_queue.md`:
append a `## REQ-<n> <UTC timestamp>` block with `status: PENDING`,
`command:`, `why:`, `expected:`. Commit the queue file and every script it
references BEFORE marking PENDING. The host monitor reviews hourly and flips
status to RUNNING/DONE/REJECTED with evidence in
`data/eval_results/_deployprep_hostreq_<n>.log`. Poll every ~5 min
(`sleep 300`); while waiting, continue work that does not depend on the
result. Stall rule: 3 h untouched PENDING → write
`data/eval_results/_deployprep_stall_note.md`, commit, exit.

## STAY-ALIVE RULE

You run under plain `claude -p`: your process TERMINATES the moment you end
your turn — no background monitor or wakeup survives. While any host request
is PENDING or any long measurement is RUNNING, spin-wait inside your turn
with literal Bash `sleep 300` calls in a loop, re-reading the queue/status
files after each sleep. Only end your turn when the queue in §Work-queue is
complete, the time budget (below) is spent, or the stall rule fires. If you
find prior-session work already committed (scripts, timing rows, REQ
statuses), do NOT redo it — read `_deployprep_timing.md` + git log and
continue from the first incomplete step.

## Time budget + timing ledger (owner requirement)

Session hard stop: **2026-07-17 06:56Z** (T+10 h from launch; the owner's
11-hour limit minus a wind-down hour). At the hard stop: finish the current
step, run the session-end doc sync (re-read `docs/THIN_CLIENT_SWAP.md` +
`docs/README.md` against what you actually changed), commit, push, exit —
even mid-item.

Maintain `data/eval_results/_deployprep_timing.md`: one row per work item —
`| item | started (UTC) | finished (UTC) | wall time | status | blocked-on-host time |`.
Write the start row the moment you begin an item and the finish row the
moment its final commit lands (these feed the owner's ETA model — accuracy
matters more than looking fast). Commit the ledger with each update.

## Work-queue (strict order; each item: read context → design → build →
measure → document → commit+push → timing row → next)

### WI-1 (both) — clean sequential-vs-parallel federation benchmark
Context: `docs/seismic_sequential_serving/` (esp. `04_BENCHMARKING.md`),
`docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md`, doc 06 findings.
Guiding idea: `SequentialSeismicBackend` is implemented but its efficacy is
UNMEASURED — the only prior attempt (G8) was swap-contaminated. This
54 GB container can host a clean A/B: sequential vs parallel federation on
the served e5/dv shards, warm and cold (fresh-process mmaps are naturally
cold here — the E5 A/B method, doc 13 §5), reporting p50/p95 latency,
peak-RSS bound per mode, and result parity. Pre-register bars first.
Deliverable: measured verdict in the sequential-serving docs + backlog row,
result JSONs under `data/eval_results/`.

### WI-2 (both) — production query-log capture
Context: `docs/THIN_CLIENT_SWAP.md` (serving path + `/api/*`),
`docs/disk_streaming_research/` (LRU/pin is explicitly gated on a production
query log — this item unblocks it). Guiding idea: a small, always-on,
privacy-sane query-log module on the served path (timestamp, normalized
query text or stable hash, leg latencies, k, backend/mode, result-set
fingerprint), JSONL with size-capped rotation, env-gated ON by default in
staging, OFF-able by one env. Must add ≈zero latency (async/buffered write).
Deliverable: module + tests + wiring + a doc section (which doc: your call,
follow the doc hierarchy) + a tiny replay/summary script proving the format
feeds the Q12-style skew analysis.

### WI-3 (demo, STAGING ONLY) — dependability harness
Context: `docs/infrastructure/HYBRID_DEMO_DEPLOYMENT.md` §4–§6 (do NOT
action its provisioning steps — owner constraint). Guiding idea: the demo is
"dependable" when it survives strangers' traffic unattended. Build and
measure locally: (a) a health-check endpoint/probe covering all three legs +
federation mode; (b) a watchdog that detects a wedged/dead serving process
and restarts it (staging-scoped, must not fight the container supervisor);
(c) a concurrent load-test driver (concurrency 1/4/8/16, fixed query set)
run against the local staging serve — p50/p95/error-rate per concurrency,
plus behaviour under one induced failure (kill the serving process
mid-load; watchdog recovery time). Deliverable: scripts + measured numbers
in a new `docs/infrastructure/DEMO_DEPENDABILITY.md` + README index row.

### WI-4 (portable) — portable-CPU build + gate reclear
Context: `docs/seismic_150m_testbed/10_FORWARD_COMPRESSION_DESIGN.md`
(native rebuild history: SSE2 baseline FAILED warm gate 1.223×, native
passed 0.957), `docs/math_optimization/` (ISA-portability discipline +
worst-case-shard gating), the seismic fork location per doc 12's asset map.
Guiding idea: today's .so is `target-cpu=native` — it cannot ship to end
users. Build `x86-64-v3` (and `x86-64-v2` if v3 fails gates) variants,
then re-run the established gates vs the native build on the served shards:
parity (worst-case-shard rule, n≥100) and warm-latency ratio. Do NOT
overwrite or unlink the production .so — variants live beside it, loadable
by explicit path/env only. Deliverable: per-target gate table (PASS/FAIL
with numbers) in doc 10 or a new doc-16 (your call), the buildable recipe
committed, backlog row.

### WI-5 (portable, stretch) — subset-corpus pilot
Only start if ≥2 h remain before hard stop. Context:
`docs/LOCALIZED_DEPLOYMENT_PLAN.md` §2–§3 (the ~10–15M year×citation-floor
"Subset" tier). Guiding idea: the handout ships a subset index; nothing
exists yet. Build the selection machinery (year × citation floor from
available metadata; measure what the actual cut yields) and a ~1M-doc pilot
through the existing index-build path to validate the pipeline end-to-end
(build succeeds, sane size/doc, spot-check queries return). READ-ONLY on
all production indexes; pilot artifacts under a clearly-named new dir, NOT
inside `data/seismic_150m/`. Deliverable: selection script + measured cut
table + pilot build log + a design note recording pipeline viability.

## Session end

Session-end doc sync per CLAUDE.md, final timing-ledger update (mark
unstarted items NOT-STARTED), commit, push, exit. Leave the queue file
clean: no PENDING requests you no longer need.
