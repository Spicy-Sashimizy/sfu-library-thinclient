# DRIVE PROMPT — deployprep wave 8: searchbar speculation vs pre-seed vs cold — three-arm latency benchmark (2026-07-18)

You are the in-container execution half of `deployprep` wave 8. Waves 1–7 are
COMPLETE — read `data/eval_results/_deployprep_timing.md` + git log; do NOT
redo their work. Wave 7 shipped the read-through result cache + pre-seed
primer (hit p50 ~4 ms vs 0.2–3.0 s warm retrieval floor). Wave 7 explicitly
deferred keystroke speculation; the owner has NOW authorized it (2026-07-18)
for exactly this wave: **build a minimal searchbar-prediction prefetch, then
run a thorough three-arm benchmark: (A) regular/cold latency, (B) wave-7
pre-seed hit, (C) speculation-primed hit.** The benchmark is the product;
the feature exists to be measured.

Orient first (read before writing anything):
`docs/THIN_CLIENT_SWAP.md` (architecture, serving path, env gates);
`src/sfu_library_mcp_http.py` (`api_search` read-through wiring, `_run_warmup`,
`_run_cache_preseed` — the patterns to imitate); `src/lib/cache.py`
(`ResponseCache` + the wave-7 key recipe — reuse, never fork);
`src/lib/serve_query_log.py` (log schema — extend, don't fork);
`web/src/search.jsx` (`SearchBar` ~line 641 — the JSX SOURCE; `web/search.js`
is the compiled artifact via `scripts/build_web.mjs`);
`scripts/eval_result_cache_ab.py` + `scripts/eval_result_cache_parity.py`
(wave-7 eval patterns); `scripts/prime_result_cache.py`;
`scripts/gui_testbed/lib.mjs` (Playwright harness; Chromium IS in-container);
`data/eval_results/demo_seed_queries.txt`;
`data/eval_results/serve_query_log.jsonl` (real query pool source).

## Binding rules — identical to wave 1 (`_deployprep_drive_prompt.md`
§Binding rules + §OWNER CONSTRAINTS + §STAY-ALIVE apply verbatim)

Highlights: git pull before commits; explicit adds — NEVER `git add .`;
`data/seismic_150m/` READ-ONLY; no docker; no /tmp for deliverables;
absolute dates; F6 discipline on every measured claim (recompute headline
numbers from the raw file before they enter a doc); NO deploy / NO DO spend /
NO TrueNAS. Wave-8 specifics:

- **Staging-serve exception:** the staging serve on :8080 (launched by the
  host via `scripts/serve_http.sh`) is yours to stop/start/restart for
  benchmark arms. At wind-down it MUST be left RUNNING, warm AND primed
  (`/health` → `warm:true`, `cache_preseed:"primed"`) — wave 7's one
  operational defect was leaving it down; do not repeat it.
- **No served-default flip:** wave 7's default-ON exception does NOT extend
  to speculation. `SFU_SEARCH_SPECULATE` defaults **OFF**; the benchmark
  enables it explicitly per arm. Ship a measured ON/OFF recommendation for
  the live review; the owner flips the default, not you.
- Only interleaved A/Bs are promotable evidence — never run all of arm A,
  then all of arm B; interleave trials across arms within each cell.

## Contract terms (owner-audited 2026-07-18 — binding, not suggestions)

1. **Speculation primes through the SAME read-through path and key recipe as
   wave 7.** A speculated result must land under the exact key a real
   submit of that query produces (byte-identical retrieval on hit). No
   second cache, no separate namespace.
2. **Predictor before literal.** Server keeps a candidate pool = landing
   example queries (from JSX source) + `demo_seed_queries.txt` + distinct
   historical queries from the serve query log. On a speculation request
   with partial text: normalize (wave-7 recipe), prefix/containment-match
   against the pool; if a sufficiently unambiguous match exists, speculate
   the FULL predicted query; otherwise fall back to speculating the literal
   typed text (this fallback is param-gated so the bench can measure
   predictor-vs-literal separately). Predictor is deterministic string
   matching + recency/frequency tiebreak — no ML, no training.
3. **Guards — never speculate when:** warming (`warm=false`), degraded
   (WI-9/WI-13 flags), result cache disabled, overload/shed active (WI-11),
   or typed text below min length (default ≥ 8 chars after normalize).
4. **Single-slot speculation:** at most ONE speculative backend query in
   flight, ever (single-GPU cross-encoder). A newer speculation while the
   slot is busy is DROPPED (not queued). A real search never waits on
   speculation bookkeeping; any speculation-path exception falls through
   silently (wave-7 term 1 discipline).
5. **Log honesty:** speculative executions are marked `speculative:true` in
   the serve query log (schema extension, wave-2 module) so analytics and
   the wave-7 `cache_hit` field stay uncontaminated. `/health` gains
   speculation counters (fired / dropped-busy / suppressed-by-guard /
   predicted-vs-literal / stores) following the existing `result_cache`
   counter shape.
6. **Client debounce:** SearchBar fires speculation only after ≥ 400 ms
   typing idle AND min length; a submitted real search cancels pending
   client speculation timers. Client behavior must be testable headlessly
   (jsdom, wave-5 style) — keep the logic in a small exported helper, not
   inline in the component closure.
7. **Trial hygiene (arm C):** a speculation trial is valid only if its query
   was NOT cache-resident before the typing simulation began — probe the
   counters (or a key-probe) before each trial; a contaminated trial is
   discarded and logged as such. Each arm-C trial uses a distinct query
   within a serve lifetime.
8. **F6 on everything:** every headline number recomputed from the raw
   results JSON (store per-trial raw samples + per-trial event timelines,
   not just aggregates). Pre-register hypotheses + bars in
   `docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` BEFORE the first
   measured run. Refuted expectations are valid results — record them.

## Work-queue (strict order; each item: read → build → test → document →
commit+push → timing row `WI-18<letter>` → next). EVERY item must be
commit-complete and independently pause-safe.

- **WI-18a — speculation prefetch (build).** Server: `/api/speculate`
  endpoint (or `api_search` speculative flag — your call, document it)
  implementing contract terms 1–5, env gate `SFU_SEARCH_SPECULATE`
  (default OFF; `=1` enables; documented in `scripts/serve_http.sh` comment
  + doc). Client: debounced speculation wiring in `SearchBar`
  (`web/src/search.jsx`, term 6), rebuilt via `scripts/build_web.mjs`.
  Unit tests in `src/tests/`: predictor matching (unambiguous / ambiguous /
  no-match / short-input), guard suppression (warming, degraded, cache-off,
  shed), single-slot drop behavior, log marking; jsdom test for the client
  debounce helper. Bar: tests green (`.venv/bin/python3 -m pytest
  src/tests/` + the jsdom verify), serve boots with the gate ON and OFF,
  and a manual curl sequence shows: partial text → speculate → counters
  move → full-query `api_search` returns `cache_hit:true`.
- **WI-18b — three-arm benchmark (the core deliverable — be thorough).**
  Build `scripts/eval_speculation_ab.py`: a deterministic typing simulator
  replaying each query as timed keystrokes at three profiles (slow ~35 WPM,
  medium ~55 WPM, fast ~90 WPM; fixed seed, inter-key jitter recorded) that
  drives the SAME speculation rules as the client (same debounce, same min
  length), then submits at "Enter" and measures Enter→response.
  Query pools: seed queries (arm B); ≥ 80 distinct realistic non-seeded
  academic queries in a committed pool file
  (`data/eval_results/speculation_bench_queries.txt` — draw from distinct
  serve-log queries + write the remainder yourself); an adversarial set
  (mid-typing edits/backspace, abandoned-then-changed query, sub-min-length
  shorts).
  Cells (all on the WARM serve — process-cold/9p re-warm is WI-6/WI-12
  territory, OUT of scope; record serve state with every cell):
  - **A — cold floor:** `SFU_RESULT_CACHE=0` serve, n≥20 queries,
    Enter→response p50/p95. This is "regular latency".
  - **B — pre-seed hit:** cache ON + primer done, the 6 seed queries,
    n≥20 trials (repeat-visits), p50/p95. Expect ~wave-7 numbers.
  - **C — speculation:** cache ON, speculation ON, non-seeded distinct
    queries, n≥20 per typing profile (3 profiles), predictor mode AND
    literal mode measured separately. Per trial record: full event
    timeline (keystrokes, speculation fired/dropped, store-complete time,
    Enter time), whether resident-by-Enter, Enter→response latency.
    Headline: **speculation hit-rate at Enter and Enter→response p50/p95,
    per profile** + the lead-time distribution (Enter − store-complete).
  - **D — cache-ON control miss:** cache ON, speculation OFF, non-seeded
    queries, n≥20 — must match arm A within noise (isolates cache/spec
    overhead on the miss path).
  - **E — interference:** while a continuous simulated typist speculates,
    fire n≥10 real cold searches; compare p50 vs arm A (does speculative
    GPU load regress a real search?).
  - **F — waste:** speculative backend executions fired per completed
    search, per profile + adversarial set (the GPU-cost of the feature).
  - **G — parity:** ≥ 6 speculation-primed responses byte-identical to
    fresh cache-OFF runs of the same normalized query (extend/reuse
    `eval_result_cache_parity.py`).
  Pre-registered bars (register in backlog BEFORE running; misses are
  recorded honestly, not renegotiated): (a) arm B hit p50 ≤ 10 ms;
  (b) arm C medium-profile predictor-mode hit-rate ≥ 80% with hit
  latency ≤ 2× arm-B p50; (c) parity 6/6; (d) arm D within 10% of arm A
  AND arm E within 15% of arm A; (e) waste ≤ 3 speculative executions per
  completed search at medium profile.
  Results: `data/eval_results/speculation_ab_<absolute-date>.json` (raw
  per-trial samples included). GUI-level validation: a SMALL Playwright run
  (n≥5, medium profile, real SearchBar typing → Enter→results-rendered)
  confirming the client wiring fires in a real browser and roughly matches
  the HTTP-level arm-C numbers — the HTTP harness is the measured evidence,
  the Playwright pass is the wiring proof.
- **WI-18c — F6 docs + verdict (same-commit rule).**
  `docs/THIN_CLIENT_SWAP.md` (serving path + env gates);
  `docs/infrastructure/DEMO_DEPENDABILITY.md` (demo-latency section: the
  three-tier table cold vs pre-seed vs speculation, with the measured
  numbers and the typing-time-budget explanation); backlog rows flipped to
  MEASURED; README index if any new doc. Include an explicit **owner
  recommendation**: speculation ON or OFF for the live review, justified
  ONLY from the measured hit-rate, waste, and interference numbers.
- **WI-18d (stretch, only if ≥ 25 min remain before hard stop)** — Interface
  toggle for speculation (wave-15 Tier-2 localStorage pattern, default
  follows server gate) + speculation counters in the Index Manager cache
  card (wave-7 WI-17d pattern); jsdom verify additions if trivial.

## Time budget + timing ledger (owner requirement — HARD)

Owner total budget: 3 h 15 min from launch (~2026-07-18 21:15Z). Hard stop
for NEW work: **2026-07-19 00:00Z**. At the hard stop: finish the current
step ONLY if <10 min from its commit, else revert uncommitted
work-in-progress cleanly (`git status --short` clean of half-done source
edits). Then: ledger rows final (unstarted items NOT-STARTED, partial items
honest status), session-end doc sync per CLAUDE.md, **restore the staging
serve** (default env: cache ON, preseed ON, speculation OFF unless the
owner has already said otherwise in the host queue; verify `/health`
warm+primed), commit, push, exit by **2026-07-19 00:30Z ABSOLUTE** — even
if incomplete. If your actual launch time differs from 21:15Z by more than
10 min, shift all three times by the same delta and write the actuals into
your first timing-ledger row.

Maintain `data/eval_results/_deployprep_timing.md`: start row when you begin
an item, finish row when its final commit lands. Commit the ledger with each
update.

## Host-queue

Same file + protocol as wave 1: `data/eval_results/_deployprep_host_queue.md`,
blocks `## REQ-<n>` / `## RESOLVED-GLM` continuing existing numbering; host
notes arrive as `## HOST-NOTE-W8-<n>`. The host monitor is active this
session (polling on a minutes cadence). Expected host needs: F6 review of
WI-18b numbers before WI-18c docs land (submit the raw JSON path in a queue
note when arm results are complete); anything privileged; anything
surprising about the serve. When in doubt, write a queue block and continue
with the next non-blocked step — never idle-wait on the host.
