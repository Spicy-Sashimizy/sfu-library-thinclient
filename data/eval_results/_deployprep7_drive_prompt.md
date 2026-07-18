# DRIVE PROMPT — deployprep wave 7: demo result cache + pre-seed (2026-07-18)

You are the in-container execution half of `deployprep` wave 7. Waves 1–6 are
COMPLETE — read `data/eval_results/_deployprep_timing.md` + git log; do NOT
redo their work. Owner decision (2026-07-18): for the upcoming live review,
wire the existing `ResponseCache` into the GUI search path as a read-through
result cache and pre-seed it with the demo's own queries. Keystroke
speculation is explicitly OUT of scope — do not build it.

Orient first: `docs/THIN_CLIENT_SWAP.md` (architecture + serving path),
`src/lib/cache.py` (the existing `ResponseCache` — reuse it, do not write a
new cache class), `src/sfu_library_mcp_http.py` (`api_search` ~line 162 is
the wire point; `_run_warmup` + `SFU_HTTP_WARMUP` is the warmup pattern to
imitate), `src/lib/serve_query_log.py` (wave-2 query log — extend, don't
fork).

## Binding rules — identical to wave 1 (`_deployprep_drive_prompt.md`
§Binding rules + §OWNER CONSTRAINTS + §STAY-ALIVE apply verbatim)

Highlights: git pull before commits; explicit adds — NEVER `git add .`;
`data/seismic_150m/` READ-ONLY; no docker; no /tmp for deliverables;
absolute dates; F6 discipline on every measured claim; NO deploy / NO DO
spend / NO TrueNAS. Exception to the no-served-default-flip rule, granted by
the owner for this wave ONLY: the result cache may default ON in the staging
serve, provided a single env (`SFU_RESULT_CACHE=0`) fully disables it.

## Contract terms (owner-audited 2026-07-18 against current caching best
practice — these are binding, not suggestions)

1. **Read-through / cache-aside** on `api_search` only: check cache → on
   miss run `search_academic_structured` → store → return. A cache failure
   must never fail a search (wrap cache ops so any exception falls through
   to the normal path).
2. **Normalized, versioned cache key**: normalize the query text (strip,
   casefold, collapse internal whitespace) and build the key from the
   normalized query + every request parameter that changes the result set
   (k/limit, filters, backend/mode — enumerate them from the actual
   `api_search` arg schema, don't guess) in a FIXED field order, plus an
   index/model version stamp (the served manifest identity) so an index or
   model swap can never serve stale results. Semantically identical requests
   MUST hit the same key; document the key recipe in the code.
3. **Never cache bad responses**: no caching of errors, exceptions, empty
   error-shaped payloads, 429/shed responses, or any response produced while
   the serving path is degraded (leg-breaker/degraded flag from WI-9,
   `seismic_loaded=False` BM25F fallback from WI-13, warmup not complete).
   A transient failure frozen for a TTL is worse than no cache. Add a unit
   test proving a degraded/error response is NOT stored.
4. **TTL/size**: the index is static between updates, so a long TTL (hours)
   is correct; size-bound via the existing `ResponseCache` limits (pick
   max_size ≥ 200, justify memory bound from a measured typical response
   size — measure one, don't guess).
5. **Observability**: hit/miss/store/bypass counters exposed in `/health`
   (or `/api/index_status` — your call, follow existing shape) AND a
   `cache_hit` boolean field added to the wave-2 serve query log schema.
6. **Throttled pre-seed**: the primer runs strictly AFTER the existing
   warmup battery completes, sequentially (concurrency 1) — never a
   parallel burst on the single-GPU cross-encoder. Idempotent (re-running
   primes misses only).

## Work-queue (strict order; each item: read → build → test → document →
commit+push → timing row `WI-17<letter>` → next). EVERY item must be
commit-complete and independently pause-safe: if the session dies after any
item's final commit, the tree is consistent and shippable.

- **WI-17a — cache wiring.** Wire `ResponseCache` into `api_search` per
  contract terms 1–5. Env gate `SFU_RESULT_CACHE` (default ON for staging
  serve, `=0` disables — one-env rollback documented in
  `scripts/serve_http.sh` comment + doc). Unit tests in `src/tests/` for:
  key normalization (same key for whitespace/case variants; different key
  for different k/filters), error/degraded non-caching, cache-failure
  fall-through. Bar: tests green (`.venv/bin/python3 -m pytest src/tests/`),
  serve boots with and without the env gate.
- **WI-17b — pre-seed primer.** Seed list = the 4 landing-page example
  queries (compiled artifact `web/search.js` ~line 4416 — find the SOURCE
  file via `scripts/build_web.mjs` and read the list from source, in case
  they drift) + a committed extensible list file (e.g.
  `data/eval_results/demo_seed_queries.txt` or a better home — your call,
  document it) for owner-added review queries. Two entry points: (a) a
  post-warmup background primer thread in the serve (same pattern/gating
  style as `_run_warmup`; env `SFU_CACHE_PRESEED`, default ON, `=0`
  disables), (b) a standalone `scripts/prime_result_cache.py` that primes a
  RUNNING serve over HTTP for re-priming without restart. Contract term 6
  applies. Bar: after serve start + warmup + primer, all seed queries are
  cache-resident (prove via the counters).
- **WI-17c — measured efficacy (F6).** On the local staging serve: n≥20
  repeat-query latency A/B — cold-miss vs cache-hit p50/p95 for the seed
  queries; parity check that a cached response is byte-identical to a fresh
  uncached run of the same normalized query (cache OFF vs ON, same query);
  confirm miss-path latency is not measurably regressed (cache-OFF vs
  cache-ON-first-hit within noise). Results JSON under
  `data/eval_results/result_cache_ab_2026-07-18.json`. Docs in the SAME
  commit: `docs/THIN_CLIENT_SWAP.md` (serving path + env gates),
  `docs/infrastructure/DEMO_DEPENDABILITY.md` (demo-latency section),
  backlog row in `docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md`
  (pre-register bars BEFORE running), README index if any new doc.
- **WI-17d (stretch, only if ≥25 min remain before hard stop)** — surface
  cache state in the GUI Index Manager panel (hit ratio + resident seed
  count via the counters endpoint); jsdom verify additions in the wave-5
  style if trivial. GUI changes minimal; no redesign.

## Time budget + timing ledger (owner requirement — HARD)

Owner total budget: 2 hours from launch (~06:50Z). Hard stop for NEW work:
**2026-07-18 08:15Z**. At the hard stop: finish the current step ONLY if
<10 min from its commit, else revert uncommitted work-in-progress cleanly
(`git status --short` must be clean of half-done source edits — stash
nothing; a clean revert of an unfinished item IS the pause-safe outcome).
Then: ledger rows final (unstarted items NOT-STARTED, partial items honest
status), session-end doc sync per CLAUDE.md, commit, push, exit by
**2026-07-18 08:45Z ABSOLUTE** — even if incomplete.

Maintain `data/eval_results/_deployprep_timing.md`: start row when you
begin an item, finish row when its final commit lands. Commit the ledger
with each update.

## Host-queue

Same file + protocol as wave 1: `data/eval_results/_deployprep_host_queue.md`,
blocks `## REQ-<n>` continuing existing numbering. The host monitor is
active this session (polling on a minutes cadence). Expected host needs:
none (no privileged ops in this wave) — anything privileged goes through
the queue, never run yourself. If the staging serve needs a restart to pick
up wiring, that is YOURS to do (it is the staging serve, launched via
`scripts/serve_http.sh` — check for an existing running serve first and
note in the ledger if you restart it).

## Session end

Ledger rows final, session-end doc sync per CLAUDE.md, commit, push, exit
by 08:45Z even if incomplete (honest partial status in ledger rows).
