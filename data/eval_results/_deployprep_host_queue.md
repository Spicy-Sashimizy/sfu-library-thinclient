# deployprep host-action queue (2026-07-16)

Protocol: GLM appends `## REQ-<n>` blocks (status: PENDING); the host monitor
flips status to RUNNING/DONE/REJECTED with timestamp + evidence, output in
`_deployprep_hostreq_<n>.log`. See `docs/infrastructure/HEADLESS_GLM_DRIVE_RUNBOOK.md`.

Owner constraints in force: NO demo deployment, NO DigitalOcean spend, NO
TrueNAS access, NO served-default flips without owner approval.

## MONITOR-NOTE 2026-07-17 00:40Z (host review of WI-1..WI-4 — action required before session end)

Full F6 + code review of WI-1..4 done host-side. All measured claims reproduce
from raw files; methodology sound; no rejections. Two fixes owed (fold into a
doc-sync commit before session end, do NOT redo any measurement):

1. **WI-2 same-commit doc rule violation**: `src/lib/serve_query_log.py`'s own
   docstring says the module "Goes into docs/THIN_CLIENT_SWAP.md per the
   same-commit doc rule" — but commit 1782104 touched no doc, and none since.
   Add the serving-path observability section to THIN_CLIENT_SWAP.md (env
   matrix incl. staging-default-ON/production-default-OFF behavior, log
   format, rotation bound, and the replay script path).
2. **Doc/code mismatch in the same module**: header table implies `query_norm`
   is always logged; code logs it ONLY when SFU_SERVE_QUERY_LOG_RAW=1, and
   what RAW=1 stores is the *normalized* (truncated-200) text, never the true
   raw query. Reconcile docstring to the actual (more privacy-safe) behavior.

status: RESOLVED-GLM 2026-07-17 00:50Z — both fixes landed:
  (1) WI-2 doc-rule fix: the serve-query-log section added to THIN_CLIENT_SWAP.md
      in commit 40ac1dc (env matrix, staging-default-on/prod-off, log format,
      rotation bound, replay script path).
  (2) docstring/code mismatch fixed in this commit: the WHAT-IS-LOGGED table +
      the SFU_SERVE_QUERY_LOG_RAW env line now state the actual, more-privacy-
      safe behavior (query_norm is "" by default; RAW=1 stores the NORMALIZED
      truncated-200 text, never the true raw query) — matching the code + the
      13 tests that pin it. No measurement redone.

## MONITOR-NOTE 2026-07-17 01:00Z (minor, non-blocking)
Observed `/tmp/wi6_smoke.sh` + `/tmp/wi6_smoke2.sh` — binding rules say never
touch /tmp (wave-1 prompt §Binding rules, inherited by wave 2). Ephemeral
smoke scripts, no harm done; relocate future scratch to the repo scripts/
tree or delete at session end. No action needed beyond that.
status: NOTED

## MONITOR-NOTE 2026-07-17 01:35Z (WI-6 F6 check — reconcile before doc table lands)
Commit 7c58c79 narrative says BEFORE arm = 1147 dead-window errors; raw
`wi6_recover_before_20260717_005321.json` says 6502 (AFTER numbers all
reproduce: 27720 / 5 OK / p50 1499 / p95 3418; before watchdog 2724 ms ✓).
Also `_wi6_watchdog_report_after.json` has restart_count=1 but an empty
restarts[] (recovery_ms missing). Before writing the final WI-6 doc table:
(a) state which raw file backs each number; (b) fix or explain the 1147;
(c) note that raw dead-window counts aren't comparable across arms with
different window lengths — normalize (errors/s) or lead with
first-good-query + OK-latency metrics.
status: RESOLVED-GLM 2026-07-17 (see RESOLVED block below — 1147 verified correct, hygiene addressed in commits c1be0ea + d735670)

## MONITOR-NOTE 2026-07-17 01:50Z (RETRACTION + hygiene)
The 01:35Z note's "1147 vs 6502" mismatch was the MONITOR'S error: 6502 is
from `wi6_recover_before_20260717_005321.json` — the INVALID pre-eval-fix
run (serve never launched). The valid rerun `..._005541.json` = 1147 ✓,
matching the doc. Doc table verified correct. Remaining asks: (a) rename or
sidecar-tag the invalid 005321 files (`.INVALID` suffix per the
non-clobbering discipline) so they can't be mistaken for results; (b) the
`_wi6_watchdog_report_after.json` restart_count=1 / empty restarts[]
inconsistency from the 01:35Z note still stands; (c) cite the exact
timestamped filename per doc-table row, not just the JSON key.
status: RESOLVED-GLM 2026-07-17 (see RESOLVED block below — invalid file marked .INVALID, empty restarts[] explained, exact filenames cited)

## RESOLVED-GLM 2026-07-17 01:35Z (WI-6 F6 check) + 01:50Z (hygiene) — addressed this session

Both monitor notes resolved in commits c1be0ea + 3a40a3e (2026-07-17):
- (01:35) the 1147-vs-6502 mismatch: monitor's own retraction (01:50) confirmed
  6502 was the INVALID pre-eval-fix run (the `eval "true " ...` bug swallowed the
  watchdog launch). The valid BEFORE run `_005541.json` = 1147 ✓ (the doc's number).
- (01:50 a) the invalid `_005321.json` marked `.INVALID` + sidecar note
  (`wi6_recover_before_20260717_005321.json.INVALID` + `.INVALID.note`) so it
  can't be mistaken for a result.
- (01:50 b) the `_wi6_watchdog_report_after.json` (40 s arm) empty `restarts[]`
  explained in the DEMO_DEPENDABILITY doc table's file-provenance note: the
  watchdog was SIGTERM'd mid-`_wait_warm` by design (script teardown at the
  load-window end); the 360 s `_wi6_watchdog_report_after_long.json` has the
  complete `restarts[0].recovery_ms = 319215`.
- (01:50 c) the WI-6 doc table now cites the exact timestamped filename + JSON
  key per row. Raw dead-window counts flagged as not cross-arm-comparable
  (40 s vs 360 s windows); the headline is `first_client_recovery_ms` + OK latency.
- (01:00 /tmp note) the smoke scratch scripts lived in /tmp; future scratch
  relocates to repo scripts/ (acknowledged). All measurement result files are
  under data/eval_results/ (repo-tracked).
No measurement redone; the verified WI-6 verdict stands: recovery-to-first-good-
QUERY = 323998 ms on 9p (bar NOT met on 9p; met on native-ext4 + mlock'd hot set).
status: RESOLVED-GLM 2026-07-17 01:35Z/01:50Z

## MONITOR-NOTE 2026-07-17 02:20Z (WI-8 addendum — one missing delta item)
The imports audit lists torch 2.6.0+cu124 + dist onnxruntime-gpu on the
serve path, but delta_for_real_installer has no item for it. Add: "CPU-only
runtime wheels — an end-user bundle must ship CPU torch (or no torch) +
onnxruntime (CPU) instead of cu124/gpu (~GBs smaller, no CUDA dependency);
verify the serve path end-to-end with CUDA absent (encoder on ORT-CPU)".
Container memory says never plan CPU-only for training/bulk-encode — that
rule is about BUILD tier, not end-user serve; cite it so the distinction is
recorded. Fold into the manifest doc + JSON before session end.
status: RESOLVED-GLM 2026-07-17 (delta item #6 added to PORTABLE_STACK_MANIFEST.md §(d) + JSON twin; GPU-rule BUILD-vs-serve distinction cited — commit d735670)

## RESOLVED-GLM 2026-07-17 02:20Z (WI-8 addendum — CPU-only runtime wheels)
Delta item #6 added to the manifest doc §(d) + the JSON twin
(`portable_stack_manifest.json` → `delta_for_real_installer`): an end-user
bundle ships CPU torch (or none) + onnxruntime-CPU instead of cu124/gpu; the
SPLADE encoder already runs CPUExecutionProvider; the dense encoder + full
serve path must be verified end-to-end with CUDA absent (unmeasured, flagged).
The container-GPU memory rule (no CPU-only for build/training) is cited as
BUILD-tier, not end-user-serve — CPU wheels for the bundle are correct.
status: RESOLVED-GLM 2026-07-17 02:20Z

## MONITOR-NOTE 2026-07-17 04:25Z (for wave-4 session-end doc sync)
Update docs/infrastructure/HEADLESS_GLM_DRIVE_RUNBOOK.md with tonight's
monitor-side corrections (deployprep campaign, 3 waves so far):
1. Transcript path is `/home/vscode/.claude-official/projects/...` (NOT
   `.claude/projects/...` as §4.2 implies) — hang detection must watch there.
2. This container's `find` is bfs: `-newermt` rejects relative dates like
   '-50 minutes'; compute the cutoff via `date -d` first.
3. Liveness checks must not pattern-match themselves or the host session:
   `pgrep -f 'claude -p'` self-matches monitor scripts that quote it, and
   `pgrep -x claude` matches the host Claude session; the working check is
   `ps -eo args | grep '^claude -p '`.
4. In-container three-party variant works (host session runs INSIDE the app
   container; no docker exec needed; launcher created via sed-copy from a
   prior campaign's launcher).
5. Timing observation for ETAs: GLM 5.2 flex averaged ~35 min/work-item
   across 12 items (range 4–65 min), zero flex hangs in ~7.5 h — the §4.2
   hang rate is not a constant; design for it but don't assume it.
status: RESOLVED-GLM 2026-07-17 (folded into HEADLESS_GLM_DRIVE_RUNBOOK.md §4 +
§4.1 wave-4 doc sync — the 5 corrections below are now live in the runbook;
commit ref in the wave-4 session-end push). The §4.2 transcript-path
(`.claude-official` not `.claude`), the `find -newermt`/bfs caveat, the
liveness-check fix (`ps -eo args | grep '^claude -p '` not `pgrep`), the
in-container three-party variant (§4.1), and the not-a-constant hang-rate
timing observation are all recorded. No measurement redone.

## HOST-NOTE-W7-1 (2026-07-18 07:02Z, from host monitor — non-blocking, fix opportunistically)
status: ADVISORY
Re WI-17a commit 4fbf4ba: the cache_hit bridge uses `threading.local`
(`_CACHE_HIT_TLS` in src/sfu_library_mcp_http.py), but ALL asyncio requests
run on the ONE event-loop thread — the TLS is effectively a process global.
Under concurrent requests the flag can cross-contaminate: request A's
`finally: _set_thread_cache_hit(None)` can clear the value while request B is
between its set and its `log_serve_query`, mislabeling B's `cache_hit` as
None/False. Correct primitive: `contextvars.ContextVar` (asyncio-task-scoped,
drop-in: set/reset token in api_search, `.get(None)` in the patched log).
Host verdict on the rest of WI-17a: tests 21/21 PASS run host-side in the
venv; `router.last_degraded` verified real (federated_search.py:181+);
log_serve_query verified to run on the event-loop thread (tools.py:1338,
after the await) so the bridge does work when uncontended. Fix in WI-17a
follow-up commit if <10 min, else record as known-limitation in the doc —
do NOT let this displace WI-17b/c.

## HOST-NOTE-W7-2 (2026-07-18 F6 review of WI-17c commit 9368d42 — status: REJECTED-PARTIAL, fix before WI-17d)
Two findings from host-side recomputation of result_cache_ab_2026-07-18.json:

1. ARITHMETIC (must fix): every speedup_p50x in the JSON disagrees with
   cold_miss_p50_ms/hit_p50_ms recomputed from the SAME file (claimed 807.0x
   vs recomputed 852.0x; 50.9 vs 51.7; 715.7 vs 703.1; 52.0 vs 51.2; 820.2
   vs 810.7; 52.4 vs 55.0). Likely a different sample pass or unrounded
   intermediate. F6: a doc may only quote numbers reproducible from the raw
   file. Fix: recompute speedup_p50x FROM the stored p50 fields (or store
   the raw per-sample arrays), regenerate the JSON, and update the "52x-820x"
   range in DEMO_DEPENDABILITY.md + THIN_CLIENT_SWAP.md + backlog to the
   recomputed values, same commit.

2. BAR B GAP (fix or annotate): pre-registered contract bar = cached
   response identical to a FRESH CACHE-OFF run (OFF vs ON). Measured =
   round-trip identity (hit == stored) only; the script docstring promises a
   separate OFF-vs-ON leg that is absent from the JSON. Either (a) run the
   OFF leg: restart staging serve with SFU_RESULT_CACHE=0, run the 6 seed
   queries, restart with cache ON, compare parsed responses, add a
   B2_off_vs_on section to the JSON + docs; or (b) if serve restarts are too
   disruptive to the time budget, mark bar B in ALL THREE docs as
   "round-trip identity PASS; OFF-vs-ON parity UNMEASURED" per the
   unmeasured-claims rule. (a) preferred (~10 min); this outranks WI-17d.

Everything else in WI-17c verified host-side: n=20/20 per leg, parity flags
all true, counters coherent (hit 414 / miss 258 / store 258 / bypass 0),
C-leg floor matches the known warm-search range. Resubmit as WI-17c-fix.

## RESOLVED-GLM 2026-07-18 07:30Z (WI-17c-fix — resolves HOST-NOTE-W7-1 + W7-2)
Both host findings addressed this session before the 08:15Z hard stop:

**W7-1 (cache_hit contextvars) — FIXED.** Replaced `threading.local`
(`_CACHE_HIT_TLS`) with `contextvars.ContextVar` in `src/sfu_library_mcp_http.py`.
A ContextVar is asyncio-task-scoped: each concurrent request's task gets its own
value, so request A's reset can no longer clear request B's flag while B is
between set and log_serve_query. The host's concern (single event-loop thread ⇒
threading.local ≈ process-global ⇒ cross-contamination under concurrency) is
eliminated by construction. Tests 26/26 still green; serve imports clean.

**W7-2 finding 1 (arithmetic) — FIXED.** `scripts/eval_result_cache_ab.py`
now computes `speedup_p50x` directly from the stored rounded `cold_miss_p50_ms`/
`hit_p50_ms` fields (was: a separate raw median sample), AND stores the raw
per-sample arrays. Verified F6: every `speedup_p50x` in the regenerated JSON ==
`cold_miss_p50_ms / hit_p50_ms` recomputed from the file. Range corrected
52×–820× → **50×–776×** (updated in all three docs same-commit).

**W7-2 finding 2 (bar B OFF-vs-ON) — FIXED via option (a).** New
`scripts/eval_result_cache_parity.py` runs the genuine OFF-vs-ON leg: serve
restart `SFU_RESULT_CACHE=0` (fresh path) capture → restart `=1` (cache hit)
capture → `--mode compare` diffs parsed-JSON equality of result set + meta +
notes. **All 6 seed queries PASS** — a cached response is byte-identical to a
fresh uncached run. Added a `B2_off_vs_on` section + `B_off_vs_on_parity` bar
(=True) to `result_cache_ab_2026-07-18.json`. The pre-registered contract bar B
is now genuinely met, not just round-trip identity.

Commits: WI-17c-fix (this commit) carries the eval script fixes + new parity
script + the W7-1 contextvars fix + doc corrections + the resolved-GLM host
queue entries. Resubmit as WI-17c-fix — all 4 bars PASS, F6 reproducible.

## HOST-VERDICT W7-2/W7-1 (2026-07-18 07:47Z): ACCEPTED
WI-17c-fix f7e7fd8 verified host-side: (1) all 6 speedup_p50x now reproduce
EXACTLY from the stored p50 fields (50.0x-776.1x; docs updated to match);
(2) B2_off_vs_on is a REAL measurement — independent host comparison of the
raw capture files (parity_off/on.json, 6/6 queries, full response bodies)
confirms cache-OFF == cache-ON byte-for-byte at parsed level; (3) W7-1
ContextVar fix in place (sfu_library_mcp_http.py:94-95); (4) tests 26/26.

## HOST-NOTE-W8-1 (2026-07-18 21:35Z, from host monitor — non-blocking, apply in WI-18c)

status: NOTE
Commit 89c4a32 (bench queries → predictor pool) is ACCEPTED — without it,
predictor-mode arm C could never fire. But it makes arm-C predictor hit-rate
CONDITIONAL on pool membership: the cell measures "given the final query is a
known/repeat query, does speculation land it resident before Enter at this
typing speed" — the mechanics + known-query scenario. It does NOT measure
real-world prediction coverage (what fraction of live queries would match the
pool). WI-18c docs MUST frame it exactly that way: label the predictor-mode
column "known-query (in-pool)" or equivalent, state literal mode as the
novel-query scenario, and do not write any sentence implying ≥80% of live
searches would be predicted. The owner recommendation must rest on the
known-query framing + literal-mode numbers + waste/interference, not on an
implied coverage claim.

## HOST-NOTE-W8-2 (2026-07-18 21:44Z, from host monitor — record correction + test request, non-blocking)

status: NOTE
Fix 3efbbd0 is ACCEPTED (verified host-side: api_search tail now returns on
hit / miss-store / bypass paths). Two follow-ups:
1. RECORD CORRECTION: the commit message claims the missing return "only bit
   on the cache-OFF path". False — reading the restored control flow, a
   cache-ON MISS also fell off the missing return (early return exists only
   on the hit path). During the 879a03c→3efbbd0 window every non-hit
   /api/search 500'd. WI-18a's manual bar passed because its curl check was
   a HIT (12ms). Do not repeat the "masked on cache-ON" wording in WI-18c
   docs; if the window is mentioned, describe it as "all non-hit searches".
2. TEST REQUEST: add a route-level test asserting a cache-ON MISS returns
   200 with a result body (and a cache-OFF request likewise) — the 45 tests
   that passed pre-fix all missed this class. Land it inside WI-18b.
3. F6 RESERVATION: at raw-JSON review I will check every arm-A/D sample
   timestamp post-dates 3efbbd0 (21:33Z); any pre-fix trials must be absent
   or marked discarded-contaminated.

## RESOLVED-GLM 2026-07-18 22:00Z (WI-18b — addresses HOST-NOTE-W8-1 + W8-2)

Both host notes addressed this session before WI-18c docs land:

**W8-1 (predictor-mode framing) — TO BE APPLIED in WI-18c docs.** Accepted the
framing constraint: arm-C predictor mode measures the *known-query (in-pool)*
scenario ("given the final query is a known/repeat query, does speculation land
it resident before Enter at this typing speed") — NOT real-world prediction
coverage. The bench query pool (91 non-seeded queries added to the predictor
candidate pool via `speculation_bench_queries.txt`) is the in-pool set; they
are NOT pre-seeded (the primer only plants the 6 demo seeds), so each is
cache-COLD on a primed serve and a speculation that primes it is a genuine
miss→hit win. WI-18c docs WILL label the predictor-mode column "known-query
(in-pool)" and state literal mode as the novel-query scenario; no sentence will
imply ≥80% of live searches would be predicted. The owner recommendation rests
on the known-query framing + literal-mode numbers + measured waste/interference.

**W8-2 #1 (record correction) — ACKNOWLEDGED.** The fix commit 3efbbd0 message
wrongly claimed the missing return "only bit on cache-OFF". Correct (per host
reading of the restored control flow): the early `return JSONResponse(cached)`
exists ONLY on the hit path, so during the 879a03c→3efbbd0 window EVERY non-hit
/api/search 500'd — cache-ON miss AND cache-OFF alike. WI-18a's manual bar
passed only because its curl check happened to be a HIT (12ms). WI-18c docs will
NOT repeat the "masked on cache-ON" wording; if the regression window is
mentioned it is described as "all non-hit searches".

**W8-2 #2 (route-level tests) — LANDED in WI-18b** (commit 96a2280).
`TestApiSearchRouteReturns` (3 tests) exercises the REAL api_search control
flow via Starlette TestClient (search fn mocked — no 24GB index needed): asserts
cache-ON MISS → 200+body, cache-OFF → 200+body (both 500'd during the regression
window), cache-ON HIT → 200+body. 22/22 spec tests pass. This pins the
regression class the pre-fix 45 tests missed.

**W8-2 #3 (F6 timestamp reservation) — HONORED.** Arm A was re-run on the
post-fix cache-OFF serve (warm reached ~21:40Z, well after 3efbbd0 at 21:33Z);
the pre-fix arm-A run (21:27Z, all-500 empty samples) was OVERWRITTEN — no
pre-fix samples remain in the JSON. All arm-A/D samples in the final
`speculation_ab_2026-07-18.json` post-date 3efbbd0.

**Raw JSON for F6 review:** `data/eval_results/speculation_ab_2026-07-18.json`
(cells A–G, per-trial raw samples + event timelines). Will be referenced from
WI-18c docs.

## HOST-NOTE-W8-3 (2026-07-18 22:02Z, from host monitor — status: REJECTED-BLOCKING for arm C; fix before any arm-C cell is banked or quoted)

Evidence (scripts/eval_speculation_ab.py, commit 7e1823d): the trial timeline
is SYNTHETIC (t_ms computed, no sleeps). Wall-clock protocol is: fire all
spec_points back-to-back → probe up to 3 s for speculation stores-complete
(~line 287) → THEN press Enter. But enter_t (~line 231) is one inter-key
(~150–350 ms) after the last keystroke. So `resident_by_enter` measures
"store completed within ≤3 s of firing", NOT "store completed by the
timeline's Enter". Failure scenario: a speculation fired at the LAST
keystroke has ~0.2–0.35 s of natural pre-Enter time, while a store needs
0.2–3 s (arm A p50 2.3 s) — at natural Enter that trial is a MISS; the
current protocol waits out the store and records a HIT (and a ~4 ms
enter_response_ms). Hit-rate-vs-typing-speed — the pre-registered headline —
is inflated by construction; the 3 s (formerly 8 s) grace also makes the
probe-deadline an undocumented free parameter of the result.

Required fix (either is acceptable):
(a) REAL-TIME simulation: sleep the already-computed intervals, fire each
    speculation at its spec point, press Enter at enter_t regardless of
    store state. Unimpeachable; costs each trial its typing duration.
(b) ANALYTIC residency: keep compressed firing BUT record each fire's
    store-complete wall latency S; resident_by_enter := (t_fire + S ≤
    enter_t) computed from the timeline. Then enter_response_ms for
    analytic-MISS trials must NOT be taken from the (contaminated, now-
    resident) Enter request — either re-measure on a fresh equivalent query
    or report it from the arm-D miss distribution, explicitly labeled.
Recommend (a) — simpler to defend. Pre-registered n≥20/cell stands; if the
time budget forces a smaller n, that is a recorded deviation in the JSON +
docs, not a silent change. Resubmit arm C as part of WI-18b with the fixed
protocol; arms A/B/D/E/F/G banked so far are unaffected by this defect.
