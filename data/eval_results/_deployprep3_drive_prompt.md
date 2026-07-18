# DRIVE PROMPT — deployprep wave 3: system-wide reliability jobs + graceful degradation

You are the in-container execution half of `deployprep` wave 3 (2026-07-17).
Waves 1–2 are COMPLETE and committed — read
`data/eval_results/_deployprep_timing.md` + git log; do NOT redo their work.
Owner's directive for this wave: **jobs that test reliability, and mechanisms
for graceful degradation, for the ENTIRE system** — not one leg, the whole
served search path (BM25F/tantivy + SPLADE/SEISMIC federation + dense +
encoder + RRF + hydration + the staging serve/watchdog from WI-3/6).

## Binding rules — identical to wave 1 (`_deployprep_drive_prompt.md`
§Binding rules + §OWNER CONSTRAINTS + §STAY-ALIVE apply verbatim)

Non-negotiable highlights: git pull before commits; explicit adds only;
`data/seismic_150m/` READ-ONLY — fault injection NEVER corrupts or renames
real index files (inject via mocks, env, wrappers, or copies of SMALL
fixtures only); no docker; no /tmp (use repo paths under
data/eval_results/); absolute dates; F6 discipline; pre-register measured
experiments in backlog doc 11; NO deploy / NO DO spend / NO TrueNAS / NO
served-default flips (new mechanisms ship env-gated, defaults proposed via
host queue, staging-default may be ON only for pure-observability).

## Time budget + ledger

Hard stop for new work **2026-07-17 06:56Z**, then session-end doc sync +
ledger + exit (same as prior waves). Continue
`data/eval_results/_deployprep_timing.md` with rows WI-9/WI-10/WI-11/WI-12.

## Work-queue (strict order)

### WI-9 (system) — leg-level graceful degradation + fault-injection proof
Guiding idea: today a dead/hung leg likely fails the whole query; a
dependable demo serves *degraded* results instead. Mechanisms (env-gated):
per-leg timeout budgets on the RRF path; a simple circuit breaker (N
consecutive leg failures → skip leg, retry-probe after cooldown); RRF
computes over surviving legs with a `degraded: [legs]` flag in the response;
`/health` gains a `degraded` state between `warm/ok` and `dead`; encoder
failure degrades to the lexical leg (BM25F still answers). Then the PROOF
job: a fault-injection test script that, against the staging serve, induces
each failure class one at a time — SPLADE leg hung (mock/env), dense leg
erroring, encoder down — and asserts: no 5xx storm, results still returned,
degraded flag correct, breaker recovers after the fault clears. Measured
table (per fault: availability %, p50/p95 during fault, recovery s) in
DEMO_DEPENDABILITY.md.

### WI-10 (system, OWNER ASK 2026-07-17) — shard-failure isolation: one shard down, seven serve
Guiding idea: the owner requires that if ANY one of the 8 SEISMIC shards
fails in any way, all other shards keep working independently. Mechanisms
(env-gated): per-shard load AND per-shard search fault boundaries in BOTH
federation classes (`ParallelSeismicBackend` + `SequentialSeismicBackend`) —
a shard that fails to load (missing/truncated/unreadable file), throws
during search, or exceeds a per-shard timeout is marked failed + skipped;
the federation merges the surviving shards' results, responds with
`degraded_shards: [...]`, `/health` reports it, and a retry-probe re-admits
the shard when it recovers. Hash sharding means a lost shard costs a
bounded ~1/8 of recall with no score-comparability issues (doc 09:
calibration unnecessary by construction) — quantify exactly that. PROOF
job: fault injection via shard-path/manifest override envs or tiny corrupt
FIXTURE files (`data/seismic_150m/` stays READ-ONLY — never rename, edit,
or relocate real shard files): per failure class (absent file, truncated
fixture, search exception, hang/timeout) assert the other 7 load+serve,
measure overlap@10 + recall retention vs full federation (expect ≈7/8) and
latency during the fault, and prove re-admission works. Table into
DEMO_DEPENDABILITY.md + backlog row; results under data/eval_results/.

### WI-11 (system) — overload protection: shed, don't collapse
Guiding idea: WI-3/7 measured capacity; past capacity the serve must degrade
gracefully — bounded in-flight concurrency + bounded accept queue, clean
429 + Retry-After on shed, never an unbounded pileup. Env-gated knobs with
staging defaults derived from the WI-7 warm numbers. PROOF job: drive load
well past capacity (e.g. 2–4× the WI-7 knee) and show: p95 of ACCEPTED
requests stays within a pre-registered bound, shed requests get clean 429s
(no timeouts/connection resets), and the serve returns to normal within a
bar after load drops. Numbers in DEMO_DEPENDABILITY.md.

### WI-12 (system) — repeatable reliability soak job (the pre-launch gate)
Guiding idea: one runnable job (`scripts/demo_dependability/reliability_soak.sh`)
the owner can run before any future demo launch: ~45–60 min soak at modest
QPS with a scheduled fault timeline injected mid-soak (leg fault from WI-9,
a shard fault from WI-10, overload burst from WI-11, watchdog SIGKILL/restart from WI-3/6), emitting a
single timeline report JSON + markdown summary: availability %, error
budget, per-phase p50/p95, every degradation/recovery event with timestamps,
PASS/FAIL against pre-registered bars. Run it ONCE tonight end-to-end (bars
pre-registered first); record the run + verdict in DEMO_DEPENDABILITY.md +
README row naming it the pre-launch reliability gate.

## Session end

Doc sync, ledger finalized, queue clean, commit, push, exit. If time runs
short, a fully-measured WI-9 beats three half-built items — depth over
breadth, in queue order.
