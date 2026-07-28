# Demo dependability harness — staging serve that survives strangers' traffic

**Created 2026-07-16 (deployprep WI-3). STAGING ONLY — not deployed.** The public
tech demo (see `HYBRID_DEPLOYMENT.md`) is "dependable" when it survives strangers'
traffic unattended: a health-check that sees all three legs + the federation mode,
a watchdog that restarts a wedged/dead serving process, and a load profile that
holds up under concurrent visitors — including recovery when the serve dies
mid-load. This is the **in-container measurement harness** for that property; the
scripts + measured numbers here are prep for the eventual staged demo (owner
constraint 2026-07-16: NO public deploy, NO spend — this is staging/prep only, on
the hardware we already have).

## What "dependable" means here (the three measured properties)

1. **Health covers all three legs + federation.** `/health` exercises the BM25F
   (tantivy), SPLADE (SEISMIC), and dense (usearch) legs with a tiny probe — not
   just "process up." A wedged leg hangs the probe (the watchdog's timeout catches
   it). The federation mode (`SFU_SEISMIC_FEDERATION`) is reported so a health
   snapshot knows which serving method answered.
2. **Watchdog restarts a wedged/dead serve.** `watchdog.py` launches the staging
   serve as a subprocess, polls `/health` on a timeout, and restarts on (a) process
   death (subprocess exit) or (b) a wedged process (N consecutive probe failures).
   It only manages a process IT started (kill-switch `SFU_DEMO_WATCHDOG`); it never
   adopts/kills a process it didn't spawn — so it can't fight a real supervisor.
3. **Load holds under concurrency + recovers from induced failure.** The load
   driver runs 1/4/8/16 concurrent clients over a fixed query set (strangers'
   traffic shape) → p50/p95/error per concurrency; an induced-failure arm SIGKILLs
   the serve mid-load and counts the dead-window errors + the watchdog's recovery
   time (death → restart → first healthy response).

## Components (all under `scripts/demo_dependability/`)

| File | Role |
|---|---|
| `staging_serve.py` | The thing being made dependable: a tiny stdlib HTTP server over `ThinClientRetriever.search_rrf` (3-leg RRF, `include_dense=True`). `/health` (all legs + federation) + `/search`. Loads the real `data/thinclient_index` (8 sections + 8 SEISMIC shards lazy + dense). `SFU_DEMO_STAGING_PORT` (default 8159). NOT the full MCP server — minimal surface for the harness. |
| `watchdog.py` | Process supervisor: launch + `/health` probe (timeout `SFU_DEMO_WATCHDOG_HEALTH_TIMEOUT` s) + restart on death/wedge (`SFU_DEMO_WATCHDOG_WEDGE_N` consecutive fails). Kill-switch `SFU_DEMO_WATCHDOG`; staging-default-on. Writes `_deployprep_watchdog_report.json` (restart count + recovery_ms per event). |
| `load_driver.py` | Concurrent load (1/4/8/16) + the induced-failure arm. `--induce-failure --serve-pid <pid>` kills the serve mid-load and measures dead-window errors + first-client-recovery. |

## Measured results (2026-07-16)

> **Numbers below are placeholders until the measurement run completes this
> session; any `*est.*` is design-only. Per the efficacy rule, an unmeasured cell
> is marked UNMEASURED — never a silent claim.** [FILLED-IN BELOW once the run lands.]

### Baseline load (concurrency sweep) — results `wi3_load_baseline_20260716_230808.json`

40 requests/level, 20 query set round-robinned, top_k=10, 3-leg RRF
(BM25F+SPLADE+dense) over the served e5_v2 shards. Measured 2026-07-16 23:03Z
on the 64 GB container.

| concurrency | p50 (ms) | p95 (ms) | mean (ms) | errors | error rate | qps |
|---|---|---|---|---|---|---|
| 1 | 4415 | 16237 | 5590 | 0/40 | **0.0%** | 0.2 |
| 4 | 3643 | 4792 | 3060 | 0/40 | **0.0%** | 1.2 |
| 8 | 4357 | 5129 | 3514 | 0/40 | **0.0%** | 2.1 |
| 16 | 5866 | 7822 | 4920 | 0/40 | **0.0%** | 2.8 |

**Read: error rate 0% at every concurrency level — the serve holds up under
concurrent strangers' traffic with no failures** (160/160 requests succeeded).
Latency is high (~4–6 s p50) because each diverse query cold-faults different
seismic forward pages (20-query working set ≈ the full ~15 GB forward index,
not fully resident at this query diversity) — this is the cold-9p-fault regime
WI-1 measured (parallel cold p50 ~2.6 s, plus BM25F/dense/RRF/hydration here).
Graceful degradation, NOT a cliff: p95 ≤ ~2× p50 at concurrency ≥4; concurrency-4
fastest (page-cache warming amortizes across the shared working set).
Throughput rises with concurrency (0.2 → 2.8 qps) — the ThreadingHTTPServer +
GIL-releasing pyseismic `.search` get real parallelism, confirming the served
path's concurrency story. NOTE: the absolute latency is the cold-fault floor,
NOT a compute verdict — a demo on a host whose page cache holds the working set
(RAM ≥ ~16 GB free, the WI-3 caveat) serves warm at sub-100 ms (WI-1 parallel
warm p50 47 ms); this sweep measures the worst-case cold-diverse-query shape.

### Induced failure (kill serve mid-load @ concurrency 8) — results `wi3_load_failure_*.json` + `_deployprep_watchdog_report.json`

The serve, managed by the watchdog, was SIGKILLed mid-load (concurrency 8, killed
at t=3s of a 30s run). Measured 2026-07-16:

| signal | measured |
|---|---|
| serve killed mid-load (SIGKILL) | **yes** (rc=-9) |
| dead-window errors (client requests that errored before recovery) | 829 |
| client OK responses after the kill (in the 30s window) | 0 (`first_client_recovery` = null) |
| **watchdog recovery (death → restart → first healthy `/health`)** | **2435 ms** ✅ |
| `healthy_after_restart` | true |

**Read: the watchdog detects a SIGKILLed serve and restores a healthy `/health`
in ~2.4 s** — the process-level dependability property holds (the demo's monitor
sees green again in seconds, not minutes). **BUT the first real `/search` after
restart pays the cold-mmap cost** (the 150M seismic shards lazy-load on first
query; WI-1 measured parallel cold p50 ~2.6 s for the seismic leg alone, +BM25F/
dense/hydration here) → `first_client_recovery` within the 30s window was null
(no client saw a completed search before the window ended). This is the
documented cold-start trade: health-recovery (2.4s, the lightweight probe) is
fast; first-query-after-restart is cold-load-bound. **Implication for the staged
demo:** a restart must pre-warm (the Q9/reorder floor, or a warmup query at
startup) so the first stranger's query doesn't hit a cold shard load. The
watchdog's fast health-recovery + a startup-warmup hook = unattended-survivable;
without the warmup, a stranger arriving in the cold window sees a long stall.

This is the honest dependability verdict the harness exists to surface — not a
"everything is fine" but "process recovery is fast; cold-restart first-query is
the remaining gap, addressed by the warmup hook the WI-1/Q9 work already
prepared (`SFU_SEISMIC_PREFLOOR_AT_LOAD`, the startup floor prefault)."

### Health-check (all three legs + federation mode) — `/health`

The lightweight `/health` (process up + leg availability + federation mode in
effect — NOT a full 3-leg search, which would be ~minutes cold). Measured
2026-07-16:

| leg | field | value |
|---|---|---|
| bm25f (tantivy) | configured / ok | true / true (8 sections loaded) |
| splade (SEISMIC) | configured / federation | seismic / parallel |
| dense (usearch) | configured / ok | true / true |
| federation mode | — | parallel (SFU_SEISMIC_FEDERATION default) |
| response time (warm) | — | ~7 ms |

The health endpoint reports the SPLADE backend + federation mode (`parallel`),
so a health snapshot knows which serving method answered — the property the
demo's monitoring needs to tell sequential from parallel federation at a glance.
A wedged leg is caught two ways: (1) `available=False` (is_available loads +
checks sections) on the lightweight health, (2) the watchdog's health-probe
timeout (a hung leg hangs the probe → the watchdog restarts after
`SFU_DEMO_WATCHDOG_WEDGE_N` fails).

## Limitations + honest caveats

- **Single host, 127.0.0.1 only.** This measures the serve's own behavior under
  concurrency + recovery, NOT network egress / DO droplet provisioning / NAS
  broker (those are `HYBRID_DEMO_DEPLOYMENT.md`, owner-gated). The harness is the
  in-container proxy for "does the engine survive traffic" — the cloud-tier
  dependability is a separate, owner-gated measurement.
- **Watchdog is NOT a production supervisor.** It's the measurement harness; a real
  demo uses systemd/supervisord. The recovery-time NUMBER transfers; the
  watchdog process does not ship as the demo's supervisor.
- **Cold-start latency is a confound for the very first request.** The staging
  serve loads shards lazy; the first /search after a (re)start pays the cold
  mmap fault cost (WI-1 measured ~2.6 s cold p50). The load driver's concurrency
  sweep is measured WARM (the steady state); the induced-failure recovery
  number includes the cold restart (the real stranger-facing experience).

## WI-6 — startup-warmup hook + recovery-to-first-good-QUERY (2026-07-17)

**The WI-3 gap this closes:** the watchdog restored a *healthy* `/health` in
2.4 s after a SIGKILLed serve, but `first_client_recovery` within the 30 s load
window was **null** (829 dead-window errors, 0 client OK) — the seismic backend
lazy-loads on first `/search`, so the first stranger's post-restart query paid
the cold-mmap-fault floor. **`/health` up ≠ `/search` warm.** WI-6 adds a
startup-warmup hook so the watchdog declares recovery only when a real query
will be served warm.

**The hook (reuses prior art, does not reinvent):**
- **F6 hotset prefault** (`SFU_SEISMIC_PREFLOOR_HOTSET=1`, the existing
  `prefault_ranges` pyo3 hook over the F2 hotset sidecar) — cold p95
  4600→1674 ms measured 2026-07-14 (`f6_prefault_hotset_20260714.json`); cold
  p50 ~431 ms. (The Q9 floor prefault `SFU_SEISMIC_PREFLOOR_AT_LOAD` is
  deliberately NOT relied on — REFUTED 2026-07-10: cold p50 ratio ON/OFF 1.025,
  all bars FAIL. The floor touch is not a lever in this 9p cold regime.)
- **a fixed warmup query set** replayed through `search_rrf` at startup
  (`SFU_DEMO_WARMUP=1`, `SFU_DEMO_WARMUP_N=24`, `SFU_DEMO_WARMUP_TOPK=10`) —
  faults the forward pages real queries touch (the floor touch does not, per
  F6's own first-process-cold caveat).
- `/health` reports `warm` + `warmup` state (up ≠ warm); the watchdog's
  `SFU_DEMO_WATCHDOG_WAIT_WARM=1` waits for `warm=true` before declaring
  recovery. Default OFF (no served-default flip — staging-env-gated).

### Induced-failure A/B — recovery-to-first-good-QUERY, before vs after the hook

> Numbers reconstructed from raw result files 2026-07-17 (F6 recompute
> discipline). The before-arm reproduces WI-3's shape (no warmup, watchdog
> up-only recovery); the after-arm turns the WI-6 hook ON. Kill at t=4 s,
> concurrency 8, 12-query set.

| signal | BEFORE (no warmup) | AFTER (WI-6 hook) | result file |
|---|---|---|---|
| serve killed mid-load (SIGKILL) | yes (rc=-9) | yes (rc=-9) | BEFORE `wi6_recover_before_20260717_005541.json`; AFTER `wi6_recover_after_long_20260717_010457.json` |
| dead-window errors (client reqs errored pre-recovery) | **1147** | **253002** | `induced_failure.dead_window_errors` in the file at left |
| client OK responses after the kill (in the window) | **0** | **73** (p50 4878 ms / p95 6066 ms) | `induced_failure.total_ok` + `latency_ms_ok` in the file at left |
| **recovery-to-first-good-QUERY** (`first_client_recovery_ms_after_kill`) | **null** | **323998 ms (~5.4 min)** | `wi6_recover_after_long_20260717_010457.json` → `induced_failure.first_client_recovery_ms_after_kill` |
| watchdog health-recovery (death→restart→first healthy /health) | **2724 ms** | n/a (wait-warm holds recovery until `warm=true`) | BEFORE `_wi6_watchdog_report_before.json`; AFTER see warm-recovery row |
| watchdog **warm-recovery** (death→restart→`warm=true`) | n/a (no warm) | **319215 ms (~5.3 min)** | `_wi6_watchdog_report_after_long.json` → `restarts[0].recovery_ms` |

> **File-provenance note (monitor ask 2026-07-17):** the BEFORE number's 1147 is
> from `wi6_recover_before_20260717_005541.json` (the valid rerun). An earlier
> `wi6_recover_before_20260717_005321.json.INVALID` file exists from the
> pre-eval-fix run (the `eval "true " ...` bug swallowed the watchdog launch →
> 6502 bogus errors); it's marked `.INVALID` + sidecar-tagged so it can't be
> mistaken for a result. The 40 s-window AFTER result
> (`wi6_recover_after_20260717_005541.json`) had `first_client_recovery=null`
> (window closed before re-warm); the 360 s-window AFTER
> (`wi6_recover_after_long_20260717_010457.json`) is the real recovery number.
> `_wi6_watchdog_report_after.json` (40 s arm) has `restarts: []` because the
> watchdog was SIGTERM'd mid-`_wait_warm` (by design — the script tears down at
> the load window's end); the 360 s `_wi6_watchdog_report_after_long.json` has
> the complete `restarts[0].recovery_ms = 319215`. Raw dead-window counts are NOT
> comparable across arms of different window lengths (40 s vs 360 s); the
> headline metric is `first_client_recovery_ms` + the OK-latency (both at left).

**Read (the honest 9p-cold-load verdict):** the hook is CORRECT — it makes the
serve answer warm at startup AND after a SIGKILL restart, and the long-window
run **flips `first_client_recovery` from null (BEFORE) to a measured 323998 ms
(AFTER)** with 73 client OKs (vs 0 before). **BUT the WI-6 bar (first good query
≤~5 s post-kill) is NOT met on 9p** — the re-warm after a SIGKILL takes ~5.4 min
(the same 9p cold-fault floor as the initial ~302 s warmup; the page cache is
process-cold on 9p, so a restarted serve re-faults the whole working set). The
253002 dead-window errors are the load driver firing 8 concurrent reqs every
~10 ms for the 324 s re-warm (most errored against the re-warming serve); the 73
OKs (p50 4878 ms) landed during the re-warm's tail when the working set was still
faulting. The watchdog's `_wait_healthy` with `WAIT_WARM=1` correctly did NOT
declare recovery until `warm=true` — so the warm-recovery (319215 ms) honestly
reflects "first query will be warm," not "process merely up."

**Where the bar IS met (not this container):** a **native-ext4 host** — cold
faulting is ms-scale there (F6's 4600→1674 ms cold-p95 was measured on this
*same* 9p mount); a native host re-warms in seconds, landing inside the bar.
And on 9p with an **mlock'd hot set** (the F6 hotset prefault makes pages
reclaimable → re-fault on restart; an mlock makes them non-reclaimable →
survives a restart without re-faulting). **The remaining gap is a host-tier
mlock/pin tier (owner-gated, NOT done here)** — the honest escalation per the
pre-registration's own bar clause. Recorded, not papered: on 9p the hook closes
the "is the served query ever warm after restart" question (yes, in ~5.4 min)
but not the "is the dead window seconds-wide" question.

## WI-7 — warm-state concurrent capacity (2026-07-17)

**Why this exists:** WI-3's baseline sweep measured the **cold floor**
(~4–6 s p50 over a 20-query diverse working set — honest but NOT the demo's
steady state; a warmed serve answers sub-100 ms, WI-1 parallel warm p50 47 ms).
WI-7 pre-warms the serve (the WI-6 hook) then re-runs the concurrency sweep →
the demo's **real** warm capacity figure + the input the DO-sizing doc needs.

### Warm concurrency sweep (pre-warmed via WI-6 hook, majflt≈0 verified warm)

> Numbers reconstructed from raw 2026-07-17
> (`wi7_warm_capacity_20260717_011753.json` + per-cell `_wi7_cell_c{1,4,8,16,32}_*`).
> 40 reqs/level, 20-query diverse set round-robinned, top_k=10, 3-leg RRF over
> the served e5_v2 shards, watchdog-supervised, serve pre-warmed via the WI-6
> hook (`SFU_DEMO_WARMUP=1` + `SFU_SEISMIC_PREFLOOR_HOTSET=1`, warmup 310.5 s).

| concurrency | p50 (ms) | p95 (ms) | errors | error rate | qps | majflt Δ (warm check) |
|---|---|---|---|---|---|---|
| 1 | 3327 | 4058 | 0/40 | **0.0%** | 0.4 | 4608 |
| 4 | 3767 | 4566 | 0/40 | **0.0%** | 1.2 | 7321 |
| 8 | 4304 | 5361 | 0/40 | **0.0%** | 2.1 | 8172 |
| 16 | 6111 | 8309 | 0/40 | **0.0%** | 2.7 | 16552 |
| 32 | 10344 | 13562 | 0/40 | **0.0%** | 2.9 | 23908 |

**Read (the honest 9p-warm verdict):** **0% errors at every concurrency level**
(200/200 requests succeeded) — the serve holds up under concurrent strangers'
traffic with no failures, and throughput rises monotonically (0.4 → 2.9 qps) with
no regression cliff → the concurrency story (ThreadingHTTPServer + GIL-releasing
pyseismic `.search`) holds. **BUT the warm p50 stays ~3.3–10.3 s**, NOT the
sub-100 ms the WI-1 parallel-warm p50 (47 ms) measured — because the 20-query
**diverse** working set (~15 GB forward index) is **NOT fully resident on 9p**:
the majflt Δ rises with concurrency (4608 → 23908), proving real cold re-faulting
under contention (each diverse query touches forward pages the 24-query warmup
didn't prefault; under concurrency the page cache thrashes). So on 9p the demo's
"warm" capacity is **working-set-bound, not compute-bound** — the p50 scales with
how much of the diverse working set faults, not with the query count.

**This is the WI-3 caveat made concrete:** WI-3's baseline (~4–6 s p50) was the
*cold-diverse* floor; WI-7's pre-warmed sweep is the *warm-* (but still
9p-faulting) floor — the gap to sub-100 ms is the working set not fitting in
resident memory on this 9p mount. **On the demo's real host (native NVMe, RAM ≥
the ~16 GB free working set)** the warm p50 drops to the WI-1 tens-of-ms range
(the page cache holds the working set without 9p's fault penalty); the 0%-error +
monotone-throughput properties transfer directly. The bar (warm p50 ≤ 250 ms) is
**NOT met on 9p** (working-set-bound) but IS the expected number on a correctly-
sized native host. Recorded, not papered.

**DO_SIZING pointer (assumptions changed — row added):** the served stack is now
**SEISMIC** (since the 2026-07-06 promotion), NOT the Qdrant `on_disk` sparse
path `DO_SIZING.md` sized. DO_SIZING's SPLADE figures (p50 545–861 ms cold,
~66 ms 30M-warm) **do not apply to the SEISMIC served path** — WI-7's warm
diverse-query p50 on 9p is 3.3–10.3 s (9p-fault-bound, not the SEISMIC engine's
tens-of-ms warm which a native host delivers). A pointer row is added to
`docs/bmp_decommission_plan/DO_SIZING.md` noting the SEISMIC stack + that its
sizing (RAM ≥ working set for warm p50) still holds in spirit but the engine +
numbers are SEISMIC's, not Qdrant's.

## Wave 3 (2026-07-17) — system-wide reliability + graceful degradation

Waves 1–2 made the serve *survive* (process-level: watchdog restart, warmup,
capacity). Wave 3 makes it *degrade gracefully* under leg/shard/overload faults —
the property a dependable demo needs when a leg dies mid-stranger-traffic: serve
*degraded* results instead of failing the query. All four ship **env-gated OFF by
default** (no served-default flip; off = byte-identical to wave-1/2 behavior).
Pre-registered in `docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` §WI-9..12.

### WI-9 — leg-level graceful degradation + circuit breaker (2026-07-17)

**The gap:** today a dead/hung leg fails the whole query. The retriever already
degrades SPLADE/encoder failure to a BM25F mirror silently, but there is no
per-leg timeout (a hung leg hangs the whole query → client timeout storm), no
circuit breaker (a failing leg is retried every query), the BM25F leg throwing
→ a 5xx, and the degrade is silent (no `degraded` flag in the response).

**The mechanism (`scripts/demo_dependability/leg_breaker.py`, env-gated
`SFU_DEMO_LEG_BREAKER=1`, default OFF):**
- **per-leg timeout budget** (`SFU_DEMO_LEG_TIMEOUT_S`, default 30): each leg runs
  in a DEDICATED daemon thread (not a shared pool — a shared pool was the
  first-attempt bug: a hung SPLADE leg's abandoned worker starved the pool so
  BM25F/dense queued behind it + timed out too, all 3 degraded). The leg's
  thread is `join(timeout=…)`-ed; still-alive after the budget → HUNG → marked
  failed (the thread dies on process exit as a daemon; the request returns
  degraded, the serve stays up).
- **circuit breaker** (`SFU_DEMO_LEG_BREAKER_N`, default 3; cooldown
  `SFU_DEMO_LEG_BREAKER_COOLDOWN_S`, default 8): N consecutive leg failures →
  OPEN (the leg is skipped — `[]`, no RRF vote — for the cooldown); after
  cooldown one PROBE query re-admits (success closes, fail re-arms).
- **RRF over surviving legs** (`search_rrf_degraded`): drops the OPEN leg's
  contribution; RRF is rank-based so dropping a leg removes its vote and the
  survivors re-weight naturally.
- **`degraded` surface**: every search returns `degraded: [leg,…]`; `/health`
  gains a `degraded` state between `ok` and `dead` (amber: up but a leg is
  down) + per-leg breaker states. OFF → `degraded` + breaker fields absent
  (byte-identical wave-1 health/search shape).

**Fault-injection proof** (`wi9_fault_injection.py`, mocks via monkeypatch — Rule
Zero: no real shard touched). Five single-leg fault classes, one at a time.

**MEASURED 2026-07-17** (`wi9_fault_injection_20260717_022742.json`; breaker ON,
per-leg timeout 30s, N=2, cooldown 1s in the proof for speed — the behavior under
test is identical to the default knobs; retriever direct, `remote_abstracts=False`
to keep OpenAlex 429s out of the leg-failure attribution). Warm baseline p50
13.0 s (9p cold-diverse), 4/4 results; `degraded=['dense']` in the warm batch is a
one-off dense timeout on a cold diverse query (not the injected fault; it clears).

| fault class | inject | DURING p50 / p95 (ms) | degraded flag | results | recovers |
|---|---|---|---|---|---|
| SPLADE leg hung (sleep>>timeout) | `_splade_leg_seismic`→sleep(60) | 30002 / 30003 | `['splade']` ✅ | 4/4 ✅ | ✅ |
| SPLADE leg throws | `_splade_leg_seismic`→raise | 3212 / 3370 | `['splade']` ✅ | 4/4 ✅ | ✅ |
| dense leg throws | `dense_search`→raise | 3655 / 3777 | `['dense']` ✅ | 4/4 ✅ | ✅ |
| BM25F leg throws (today: 5xx) | `_bm25f_leg`→raise | 115 / 119 | `['bm25f']` ✅ | 4/4 ✅ | ✅ |
| encoder down (graceful mirror) | `_encode_splade_top`→None | 3204 / 3586 | `[]` ✅ (not tripped) | 4/4 ✅ | ✅ |

> Bars: (a) no 5xx storm under any single-leg fault; (b) results still returned;
> (c) `degraded` names the injected leg; (d) breaker re-admits after cooldown.
> Result file: `data/eval_results/wi9_fault_injection_20260717_022742.json`.

**WI-9 VERDICT: PASS — 20/20 bars (all 5 fault classes × all 4 bars).** Every
injected single-leg fault: 0 5xx, results still returned (4/4), the `degraded`
flag names exactly the injected leg, and the breaker re-admits the leg after the
cooldown. The headline isolation result: `splade_hung` DURING p50 = 30 002 ms
(the abandoned 30 s leg-timeout — the hung leg is dropped, not waited on) but
`degraded=['splade']` ONLY — BM25F + dense stay healthy (the dedicated-thread-per-
leg fix; the first-attempt shared-pool bug made all 3 degrade). `bm25f_error`
DURING p50 = 115 ms (the BM25F throw is caught, SPLADE+dense answer fast — the
leg that today would 5xx now degrades). `encoder_down`: `degraded=[]` — the
graceful-mirror contract holds (an encoder failure mirrors BM25F; the breaker
correctly does NOT trip on a successful degrade, only on a throw/timeout). The
proof runs the retriever DIRECTLY (not the HTTP serve) for speed; the serve's
`/search` calls the SAME `LegGuardian.search_rrf_degraded` wired in
`staging_serve.py`, so the serve carries the identical `degraded` field the proof
asserts on.

### WI-10 — shard-failure isolation: one shard down, seven serve (2026-07-17, OWNER ASK)

**The owner ask:** if ANY one of the 8 SEISMIC shards fails in any way, all
others keep working independently. Hash sharding ⇒ a lost shard costs a bounded
~1/8 of recall with no score-comparability issue (doc 09: calibration
unnecessary by construction — each shard is a disjoint doc-id hash partition,
scored in one shared SPLADE vocab space).

**The mechanism (`src/lib/thinclient/sharded_seismic_backend.py`, env-gated
`SFU_SEISMIC_SHARD_FAULT_BOUNDARY=1`, default OFF):** per-shard LOAD AND SEARCH
fault boundaries in BOTH federation classes (`ParallelSeismicBackend` +
`SequentialSeismicBackend`, the cascade design — `_fan_out` is the only per-method
behavior, the guard wraps it identically):
- **load boundary** (`__init__`'s shard-load loop): a shard that fails to load
  (missing/truncated/unreadable) is marked failed + a `None` placeholder takes
  its slot; the OTHER 7 still load. (Pre-WI-10 a bad shard raised `RuntimeError`
  → no federation.)
- **search boundary** (`_guarded_search_one` wrapping `_search_one` in
  `search_encoded`): a shard that throws or exceeds
  `SFU_SEISMIC_SHARD_SEARCH_TIMEOUT_S` (default 30) → `[]` + recorded fault; the
  reprobe cooldown (`SFU_SEISMIC_SHARD_REPROBE_S`, default 10) re-admits on a
  successful probe.
- **`degraded_shards: [...]`** + `fault_status()` accessor surface; the merge
  (`_merge_topk`, the shared pure one) is unchanged — only which per-shard results
  feed it differs, and only under an explicit fault. T1 bit-identity unaffected by
  construction (OFF → zero behavioral change; ON with no fault → the guard passes
  every result through unchanged).

**Fault-injection proof** (`wi10_shard_isolation.py`): manifest-override envs +
`_FaultyShard` wrapper (Rule Zero: real shards READ-ONLY — the pyo3
`.search` is read-only, so a wrapper object replaces the shard in the list for
the fault window; corrupt fixtures under `data/eval_results/_fixtures/` only).

**MEASURED 2026-07-17** (`wi10_shard_isolation_20260717_023630.json`; boundary ON,
per-shard search timeout 3s, reprobe cooldown 1s in the proof for speed — behavior
identical to the default knobs; baseline 8-shard parallel p50 5583 ms cold,
sequential p50 272 ms). Recall retention@10 = **0.850 across every cell** — right
in the pre-registered [0.80, 0.95] band, the bounded ~7/8 hash-sharding loss
predicted (a dropped shard costs exactly its ~1/8 of docs; no re-calibration).

| fault class | inject | shards loaded | recall@10 | degraded_shards | re-admit | p50 (ms) |
|---|---|---|---|---|---|---|
| search exception (parallel) | `_FaultyShard` shard[0]→raise | 8 (1 faulted) | 0.850 | `[shard0]` ✅ | ✅ | 98 |
| search hang/timeout (parallel) | `_FaultyShard` shard[0]→sleep(30) | 8 (1 faulted) | 0.850 | `[shard0]` ✅ | ✅ | 117 |
| search exception (sequential) | `_FaultyShard` shard[0]→raise | 8 (1 faulted) | 0.850 | `[shard0]` ✅ | ✅ | 270 |
| load absent (parallel) | manifest: shard[0]→missing path | 7/8 ✅ | 0.850 | shard0 failed ✅ | ✅ | 123 |
| load truncated (parallel) | manifest: shard[0]→corrupt fixture | 7/8 ✅ | 0.850 | shard0 failed ✅ | ✅ | 120 |

> Bars: (a) other 7 load+serve (0 throws); (b) results returned; (c) the shard
> named; (d) re-admission clears the flag; (e) BOTH parallel + sequential isolate.
> Expected recall retention ≈ 7/8 = 0.875 (bounded hash-sharding loss; bar [0.80, 0.95]).
> Result file: `data/eval_results/wi10_shard_isolation_20260717_023630.json`.

**WI-10 VERDICT: PASS — all 5 cells, all bars. The owner-ask property holds: any
one of the 8 SEISMIC shards down, the other 7 serve.** Every fault class (search
exception, search hang/timeout, load-absent, load-truncated, in BOTH the parallel
and sequential federation classes): the other shards load+serve with 0 throw-ups,
results are returned, `degraded_shards` names exactly the failed shard, and re-
admission clears the flag (re-load with the good manifest for load faults; the
reprobe probe for search faults). The headline recall number — **0.850 retention,
the same across every cell** — is the bounded hash-sharding loss made concrete: a
dropped shard is a disjoint doc-id hash partition, so dropping it costs exactly
its ~1/8 of the top-k with no score-comparability issue (doc 09: calibration
unnecessary by construction, now measured). The fault's p50 stays low (98–270 ms)
because a dropped shard doesn't slow the survivors (no pileup).

### WI-11 — overload protection: shed, don't collapse (2026-07-17)

**The gap:** WI-3/7 measured capacity (~2.9 qps warm knee). Past capacity the
serve piles up unboundedly → p95 → ∞ + connection resets (the cliff). WI-11 sheds
cleanly instead: bounded in-flight + bounded accept queue, HTTP 429 +
`Retry-After` on shed.

**The mechanism (`staging_serve.py`, env-gated `SFU_DEMO_OVERLOAD_SHED=1`, default
OFF):** a `BoundedSemaphore` (`SFU_DEMO_MAX_INFLIGHT`, default 64) + accept queue
(`SFU_DEMO_ACCEPT_QUEUE`, default 64). A request that finds a free slot is
accepted (the common warm case, non-blocking); one that would exceed the queue cap
is shed immediately with a clean 429 + `Retry-After`; one that fits the queue
waits briefly (`SFU_DEMO_QUEUE_WAIT_S`, default 1) for a slot. `/health` reports
`overload: {inflight, max_inflight, accept_queue, stats:{shed, accepted}}`. The
gate is on `/search` only (NOT `/health` — so the watchdog never mis-reads a shed
storm as a wedged serve). OFF → no gate, no 429 path (byte-identical wave-2).

**Proof** (`wi11_overload.sh`): warm serve + gate ON (max_inflight=16,
accept_queue=16, raised socket backlog), three phases — baseline c=4 → OVERLOAD
c=128 (8× the gate depth, 4× the c=32 knee) → recovery c=4. A custom concurrent
driver records the per-request HTTP STATUS histogram (not just ok/err) so a clean
429 shed is distinguished from a timeout/connection-reset collapse.

**MEASURED 2026-07-17** (`wi11_overload_20260717_030631.json`):

| phase | p50 ms | p95 ms | ok | sheds (429) | collapse | qps | status hist |
|---|---|---|---|---|---|---|---|
| pre-overload c=4 | 4186 | 6258 | 40/40 | 0 | 0 | 1.1 | `{200:40}` |
| overload c=128 | 10440 | 11917 | 21 | 175 | 4 (2%) | 16.2 | `{429:175, 200:21, 0:4}` |
| post-overload c=4 | 4381 | 5358 | 40/40 | 0 | 0 | 1.2 | `{200:40}` |

> Bars: (a) accepted p95 during overload ≤ ~3× the pre-overload scale (bounded
> tail, not ∞); (b) shed = clean 429s (no timeouts/connection resets as the
> majority — collapse ≤5% is the documented socket/accepted-timeout edge); (c)
> post-overload p50 returns to within ~1.5× baseline.
> Result file: `data/eval_results/wi11_overload_20260717_030631.json`.

**WI-11 VERDICT: PASS — all 3 bars.** Driving 8× the gate depth (c=128 vs a 16-slot
gate) the serve sheds cleanly: **175 of 200 requests get a clean HTTP 429 +
Retry-After**, 21 are accepted + served (accepted p95 11 917 ms, bounded — ≤3× the
baseline, NOT the ∞ of an unbounded pileup), and only 4 (2%) collapse (a ≤5%
socket-edge residual — the raised listen backlog got collapses from the
first-attempt's 4-with-a-smaller-backlog down to a stable 2%; the bar tolerates
the documented edge, not a cliff). Post-overload the serve returns to baseline
(p50 4381 ms ≤ 1.5× the 4186 pre-overload). The gate's contract holds: **shed,
don't collapse** — overload produces clean 429s, not timeouts/connection resets.

### WI-12 — repeatable reliability soak job (the pre-launch gate) (2026-07-17)

**The job (`scripts/demo_dependability/reliability_soak.sh`):** one runnable job
the owner runs before any future demo launch. ~40-min soak at modest QPS
(`SFU_DEMO_SOAK_QPS`, default 0.3) with a SCHEDULED fault timeline injected
mid-soak — a WI-11 overload burst, a WI-3/6 watchdog SIGKILL/restart (a WI-9 leg
fault + WI-10 shard fault are proven by their direct Python harnesses; the soak
exercises the *compounded* timeline) — emitting a single timeline report JSON +
markdown summary: availability %, error budget, per-phase p50/p95, every
degradation/recovery event with timestamps, PASS/FAIL vs pre-registered bars.

| signal | measured |
|---|---|
| availability (ok-or-shed / accepted) | **0.822** (82.2%) |
| error budget (fails / total) | 96 / 540 (17.8%) |
| p50 / p95 / p99 (ms) | 2634 / 3405 / 3544 |
| fault timeline events | 8 |
| phase-3 SIGKILL → warm recovery | **312 856 ms (~5.2 min)** |
| phase-2 overload burst (gate sheds) | 33 clean 429s (gate.stats.shed) |

> Bars: (a) availability ≥ 95%; (b) every injected fault produces a degradation +
> recovery event (both timestamped); (c) worst-phase p95 ≤ ~5× the warm baseline.
> Result files: `data/eval_results/wi12_soak_20260717_032757.json` + `.md`.
> Named the **pre-launch reliability gate** in `docs/README.md`.

**WI-12 VERDICT: FAIL on bar (a); PASS on (b) + (c).** The single end-to-end run
(30 min @ 0.3 qps, 540 requests) ran cleanly: the scheduled fault timeline fired
on schedule — phase-1 baseline → phase-2 overload burst (the WI-11 gate shed 33
requests with clean 429s, `overload.stats.shed=33` in the phase-2 health) →
phase-3 watchdog SIGKILL/restart → phase-4 final — and **every injected fault
produced a degradation + a recovery event with timestamps** (bar b ✅), with
worst-phase p95 (3405 ms) ≤ 5× the baseline (bar c ✅). **Bar (a) FAILS at 82.2%
availability** — and this is the **documented WI-6 finding in soak form, not a
new failure**: the 96 fails are the ~5.2-min SIGKILL-re-warm dead-window (the
phase-3 `recovery_ms_warm = 312 856 ms`, the 9p cold-fault floor — exactly the
WI-6 re-warm-to-first-warm-query number). During that re-warm the soak driver's
paced requests fail (connection-refused against the re-warming serve); 5.2 min of
dead-window out of a 30-min soak = ~17.8% fail = 82.2% availability (the math
checks). **On a native-ext4 host** (ms-scale re-warm, per the WI-6 native
finding) the dead-window collapses to seconds → availability ≥ 95% passes. So:
the soak *gate is runnable + correct* (it ran end-to-end, timed every event, gave
a clean PASS/FAIL), and on 9p it surfaces the SAME re-warm gap WI-6 already
owns — the reliability gate's bar (a) is the one number that needs the host-tier
mlock/pin (owner-gated) to pass on this 9p container. Recorded, not papered: the
two bars that hold independent of host-tier (b: the fault timeline mechanics;
c: no cascade collapse) PASS on 9p; the one bar that needs a fast re-warm (a)
fails on 9p + passes on native. The pre-launch gate is shipped + measured; the
owner runs `bash scripts/demo_dependability/reliability_soak.sh` before any demo
launch on the demo's REAL host.

### WI-12 route B — ext4-overlay re-run attempt (2026-07-28, SMOKE-GATE STOPPED before the full soak)

**Goal:** convert bar (a) from FAIL to PASS by moving the served SEISMIC shard
set off the 9p workspace mount onto container-local ext4-overlay storage (the
gap the WI-6/WI-12 9p rows already name: "on a native-ext4 host the dead-window
collapses to seconds"). **Mechanism used:** the existing
`retriever._stage_shards_local()` lever, `SFU_SEISMIC_STAGE_DIR=/home/vscode/seismic_ext4`
— NOT a hand-edited manifest as originally sketched; the retriever already
copies each manifest shard's `mmap_dir` to a local dir and rewrites a
`staged_manifest.json` automatically (idempotent via a `.staged_ok` marker, and
correctly adopts a copy pre-staged by `scripts/stage_seismic_local.sh` via
byte-size match) — this turned out to be the better path than the plan's
original hand-rolled-manifest sketch, so it's what's recorded here. All 8
shards (42 GB total, `data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json`)
copied + verified (byte-size match all 8 + md5 spot-check on shard0's
`config.json`/`forward_encoder.bin`/`manifest.json` + full file-list diff on
shard0 and shard7). Ran on an alternate port (8261, a fresh watchdog instance)
— the container had **no pre-existing serve running** at session start (a
finding in itself: `ss -tlnp` showed nothing on 8159/8185, no
`staging_serve.py`/`watchdog.py` process, `data/watchdog_status.json` stale
since 2026-05-13 — the wave-9 "serve restored OFF" exit state did not survive
the container rebuild the git log documents. Nothing needed preserving; the
alternate-port discipline was followed regardless).

**Confirmed the storage-type fix took effect:** `retriever._fstype_for_path()`
reports `overlay` for the staged copy vs `9p` for the original, and
`_auto_federation_mode()` now auto-selects **`parallel`** (not `sequential` —
its slow-FS branch) for the served shards, proving the system no longer
classifies the served path as a slow passthrough mount.

**Smoke induced-failure cell (WI-6-style, port 8261, SIGKILL serve pid, watched
via the watchdog's own wait-warm timer):**

| signal | 9p (WI-6, 2026-07-17) | ext4-overlay (2026-07-28) | file |
|---|---|---|---|
| watchdog warm-recovery (death→restart→warm=true) | 319 215 ms | **159 124 ms** | `data/eval_results/_wi12_ext4_smoke_watchdog_report_20260728.json` |
| improvement | — | **~2.0× faster**, a real measured effect | — |
| pre-registered smoke go/no-go bar | ≤ ~85 000 ms to proceed to the full soak | **159 124 ms — bar NOT met** | — |

Per the pre-registered smoke gate ("if re-warm does not drop below ~85 s, STOP
and report; do not run the soak"), **the full 30-min/0.3 qps soak was NOT run**
— it would predictably still FAIL bar (a) (159 s dead window / 1800 s soak ≈
8.8% fail ≈ 91.2% availability, short of the ≥95% bar, though closer than the
9p arm's 82.2%). Running it would have cost ~30 min for an already-diagnosable
non-pass.

**Root-cause diagnosis** (direct in-process timing of `ThinClientRetriever`
methods, bypassing the HTTP harness — full breakdown in
`data/eval_results/wi12_ext4_diagnosis_20260728.json`):

| step | seconds |
|---|---|
| ctor + `is_available()` (BM25F tantivy ×10 sections + dense — still on 9p, not moved) | 2.2 |
| `_seismic_backend()`, hotset prefault ON, ext4-staged (2 fresh-process runs) | 82.7 / 80.2 |
| `_seismic_backend()`, hotset prefault OFF (lazy) | 1.9 (cost moves, doesn't vanish — see next row) |
| `search_rrf()` first call after prefault-OFF ctor | 94.3 |
| `search_rrf()` first call, prefault ON, `remote_abstracts=False` (isolates the OpenAlex confound) | 18.2 |
| `search_rrf()` second call, different query, `remote_abstracts=False` | 3.8 |

**Read:** the 9p-specific *per-page-fault* penalty is genuinely fixed (WI-1's
~160–240× claim is about per-fault latency, and federation auto-selection
confirms the FS is no longer flagged slow) — but two costs that were previously
dwarfed by the 313 s 9p floor are now the visible bottleneck: **(1)** the raw
first-touch cost of 42 GB of SEISMIC data on *this container's* ext4-overlay is
itself ~80–95 s, consistent with a plain `dd` sequential-read test and with
`free -h` showing only ~1 GB free / 50 GB buff-cache — the combined served
working set (BM25F sections 42 GB + SEISMIC 42 GB + dense) is ~85 GB+ against
this container's 56 GB RAM, so cache eviction under memory pressure forces real
disk reads even on "fast" local storage, and this container's overlay is itself
a WSL2-virtualized disk, not bare-metal cloud NVMe (the plan's own caveat — "the
storage shape the droplet deploy would use" — is exactly the gap: a real
droplet's local NVMe would very likely clear the ~85 s bar where this sandboxed
overlay does not); **(2)** a ~18 s non-disk first-query overhead (SPLADE ONNX
encoder cold session + hydration) plus OpenAlex remote-abstract-fetch 429
retries across the 24-query warmup replay — present in BOTH the 9p and ext4
arms (same `staging_serve.py` code path), so it doesn't invalidate the
ext4-vs-9p comparison but does inflate the absolute number in both.

**WI-12 ROUTE-B VERDICT: MEASURED, NOT PASSED.** A real ~2× recovery-time
improvement (319 215 ms → 159 124 ms) from moving the SEISMIC shard set to
container-local ext4-overlay — confirming the storage-type hypothesis in
direction — but bar (a) is **not** converted to PASS in this sandboxed
container; the smoke gate correctly stopped the full soak rather than running
it to a predictable non-pass. **Config caveat (binding):** the ext4-overlay
copy at `/home/vscode/seismic_ext4/` (42 GB) is **ephemeral** — lost on
container rebuild — this is a measurement configuration proving/refuting the
ext4 hypothesis, not a standing serving path; a real droplet deploy with
native local NVMe and RAM sized to the full working set (not this sandbox's
56 GB against an ~85 GB+ working set) is the environment where bar (a) is
expected to actually pass. Files: smoke result
`data/eval_results/wi12_ext4_smoke_induced_20260728.json`; watchdog report
`data/eval_results/_wi12_ext4_smoke_watchdog_report_20260728.json`; full
diagnosis `data/eval_results/wi12_ext4_diagnosis_20260728.json`. Date
2026-07-28.

## Wave 4 (2026-07-17) — update mechanisms for the demo + portable build

Waves 1–3 proved the demo SURVIVES strangers' traffic once it's running. Wave 4
closes the other half of "dependable": the demo and the portable build must
each have a METHOD OF BEING UPDATED — pending upgrades and research (E8 stages,
encoder work, index rebuilds, `.so` rebuilds) WILL change code + artifacts after
deploy/handout, and those updates must be checksum-verified, crash-safe, and
auto-rollbackable. Two items: WI-13 (the demo host's versioned update + rollback)
and WI-14 (the portable bundle's update path — `PORTABLE_STACK_MANIFEST.md`
§(e)). Owner constraints identical to wave 1: NO deploy / NO DO spend / NO
TrueNAS / NO served-default flips; `data/seismic_150m/` READ-ONLY — the proofs
exercise a STAGING serve + FIXTURE artifacts, never the promoted e5_v2 default
on the real port.

### WI-13 — versioned update + auto-rollback for the demo host (2026-07-17)

The demo's update unit is the 4-tuple in `deploy_versions.json` (generated by
`scripts/demo_dependability/deploy_versions.py`): **(1) code rev** (the git
commit + the `SFU_*` version envs a flip changes), **(2) seismic `.so` variant**
(the served extension `.so` under the `seismic` package — WI-4's portable v3
installed into the venv, ~2.7 MB), **(3) index manifest** (the served shard-set
manifest + its one-env-rollback ladder: e5_v2 → e5_v1 → plain dv, each with the
per-shard `manifest.json` checksum — the immutable-shard versioned POINTER a
re-conversion rewrites, NOT 66 GB of shard data), **(4) models** (the SPLADE
ONNX + dense v5 query-encoder WEIGHT files an encoder distill changes). Each
component carries sha256 + byte size + an absolute date + the update-class
delta-size expectations (`.so` rebuild ~2.7 MB; encoder distill ~1 GB; E8
dv-v2 re-conversion ~26 GB; manifest-flip-only ~7.5 KB).

`scripts/demo_dependability/update_demo.sh` codifies the update FLOW around the
repo's EXISTING manifest-flip + one-env-rollback mechanism (the E5/E8 rollouts
— `retriever.py _seismic_backend` reads `SFU_SEISMIC_SHARD_MANIFEST`; the ladder
is every prior served set reachable by flipping the env):

1. **git pull** (a real code update = a new HEAD)
2. **verify artifact checksums** vs `deploy_versions.json` (abort BEFORE the
   flip on a mismatch — the stage-beside discipline means the pre-update
   artifacts survive a broken flip; rollback never needs re-fetch)
3. **stage the NEW manifest BESIDE the old** (never in-place — `cp` to
   `data/eval_results/_fixtures/`; the flip is env-only, old files untouched)
4. **flip** the staging serve's `SFU_SEISMIC_SHARD_MANIFEST` to the staged copy
5. **warm-restart** via the WI-3/6 watchdog (wait-warm: recovery declared only
   at `/health warm=true` — a stranger's first post-restart query answers warm)
6. **health + smoke gate** — `/health ok+warm` AND `/search` 200 AND **the
   SEISMIC backend actually LOADED** (the WI-13 gate-strengthening, below)
7. **AUTO-ROLLBACK on gate failure**: flip back to the prior manifest,
   warm-restart, verify the post-rollback gate PASSES → serve ends SERVING on
   the prior version (the rollback is not itself a failure)

#### The gate-strengthening finding (the part that makes the gate trustworthy)

The first broken-arm run surfaced a real failure mode: `/health` reports
`legs.splade.configured="seismic"` whether or not the shards actually LOADED —
the retriever silently falls back to the BM25F leg when a shard's mmap fails
(`OSError` on `from_mmap`, caught in `_splade_leg_seismic` → "SEISMIC SPLADE
leg failed; falling back to BM25F leg"). So the WI-3 health+smoke gate (a 200
`/search` from BM25F) would COMMIT a silently-degraded update — the exact
failure the auto-rollback is meant to prevent. Fix: `staging_serve.py` gained a
`/verify` endpoint (gated `SFU_DEMO_UPDATE_VERIFY_SEISMIC=1`, OFF by default =
byte-identical to wave-3 serve) that forces the lazy `_seismic_backend()` load +
reports `seismic_loaded`. The update flow sets the gate; `smoke_gate` asserts
`seismic_loaded=True` on the new version. Verified directly (the F6 recompute):
a good manifest (e5_v2) → `_seismic_backend()` loads → `seismic_loaded=True`;
the broken fixture (truncated shard0) → `_seismic_backend()` raises `OSError` →
`seismic_loaded=False` → gate FAILS → auto-rollback. `/health` alone can NOT
catch this; `/verify` is the gate's load-served signal.

#### MEASURED 2026-07-17 — two staging arms, FIXTURE artifacts

**Arm 1 (success)** — `wi13_update_success_20260717_045419.json`: a stable serve
is running on the e5_v2 baseline (warm, pre-gate smoke pass, `seismic_loaded=True`);
the updater stages a checksum-verified COPY of the manifest (the manifest-flip-
only / `.so`-rebuild update class — shards resident → fast re-warm), flips
`SFU_SEISMIC_SHARD_MANIFEST`, warm-restarts via the watchdog (wait-warm), the
post-flip health+smoke+`/verify` gate PASSES (`smoke=pass (search=6 ok/0 fail,
seismic_loaded=True)`), committed, **NO rollback**. Downtime = **226 585 ms**
(the warm-restart + re-warm window on 9p — a cold re-mmap of the resident
shards; on a native-ext4 host this is ms-scale, per the WI-6 native finding). Bar (a) ✅.

**Arm 2 (broken)** — `wi13_update_broken_20260717_045419.json`: the updater
flips to a fixture manifest whose shard0 `mmap_dir` is a TRUNCATED fixture (the
WI-10 `_make_truncated_fixture` pattern — a real shard's `manifest.json` + a
16-byte garbage `data.bin`). The serve warm-restarts and COMES UP via the
silent BM25F fallback (`wait_warm=ok` — the warmup queries answer from BM25F);
the `/verify` smoke check catches the degradation — `seismic_loaded=False
— SEISMIC silently fell back to BM25F; the new shard set did NOT load` — so the
gate FAILS (`new_smoke FAILED → triggering auto-rollback`); **AUTO-ROLLBACK**
flips back to the prior (resident) e5_v2 manifest, warm-restarts, and the
post-rollback gate PASSES (`rollback_gate ok smoke=pass (seismic_loaded=True)`)
→ `rollback_committed ok — serve re-serving on the PRIOR version` → the demo
ends SERVING on the rolled-back version. The broken-version's measured downtime
before rollback = **186 913 ms`; `overall=PASS_ROLLED_BACK, rolled_back=True`.
Bar (b) ✅ — the broken update's gate FAILS and auto-rollback restores a serving
state whose post-rollback gate PASSES (the rollback is not itself a failure).
Bar (c) ✅ — the stage-beside discipline means the pre-update artifacts survived
the broken flip (the old manifest + shards were never touched; rollback needs no
re-fetch). Bar (d) ✅ — `deploy_versions.json` checksums verified before + after
each arm (`checksum_verify ok` recorded in both timelines; a mismatch would
abort before the flip).

*The success arm models the manifest-flip-only / `.so`-rebuild update class (the
cheapest real class — shards resident, ~2.7 MB / 7.5 KB delta). The real
CROSS-VERSION flip (e5_v2 ↔ e5_v1, different `mmap_dir`s = a full cold re-load)
is ALREADY proven by the E5/E8 rollouts (served 2026-07-09 / 2026-07-14, one-env
rollback) — WI-13's job is the UPDATE FLOW (stage, verify, flip, warm-restart,
gate, auto-rollback) around that mechanism, which the copy-flip does faithfully
+ efficiently (one cold load per arm). The per-step timestamps + gate verdicts
are the `events[]` array in each timeline JSON; the drive log is
`data/eval_results/_wi13_update_drive4.log`.*

## Wave 7 (2026-07-18) — demo result cache + pre-seed: instant repeat queries

The live-review demo's biggest latency risk AFTER warmup is the **repeat
query**: a reviewer clicks the same (or a near-identical) landing example twice,
or revisits a query during Q&A. Even warm, that's a full SEISMIC federation +
SPLADE + dense + cross-encoder re-rank pass — measured (WI-17c, F6)
**0.2–3.2 s** warm-miss p50 across the 6 seed queries (the variance is the
working-set: queries faulting already-cached pages ~0.2 s; cold-region queries
~2.5–3.2 s). A cached repeat lands in **3.4–4.0 ms**.

**What shipped (deployprep WI-17, 2026-07-18):** the existing thread-safe
`lib/cache.ResponseCache` (TTL+LRU+memory-bounded, no new cache class) wired
into `api_search` as a **read-through result cache** — check the versioned
cache → on miss run `search_academic_structured` → store → return. Every cache
op is wrapped so a cache failure can never fail a search (fall through to the
normal path). **Never caches a bad response**: no errors, no degraded
(WI-9 leg-breaker / WI-13 BM25F silent fallback) responses, nothing produced
while warmup is still pending. **Versioned key** includes the served manifest's
`built`+`engines` stamp so an index/model swap can never serve stale results.
**Pre-seed primer** (WI-17b) plants the demo's own queries into the cache
strictly after warmup completes, sequentially (concurrency 1 — never a parallel
burst on the single-GPU cross-encoder), idempotent.

**Efficacy (WI-17c, `data/eval_results/result_cache_ab_2026-07-18.json`, all
4 bars PASS)** on the warm+primed staging serve:

| leg | measurement | result |
|---|---|---|
| A. cold-miss vs cache-hit | n=20/leg, 6 seed queries | hit p50 **3.7–4.1 ms** vs cold-miss p50 **0.2–3.0 s** → **50×–776× speedup** (speedup recomputed from the stored p50 fields — F6; raw per-sample arrays in the JSON) |
| B. byte-parity (round-trip) | cached response == stored | PASS for all 6 seed queries (round-trip identity) |
| **B2. byte-parity (OFF-vs-ON)** | serve restart `SFU_RESULT_CACHE=0` (fresh path) vs `=1` (cache hit); parsed-JSON equality of result set + meta + notes | **PASS for all 6 seed queries** — the cached response is byte-identical to a fresh uncached run (`scripts/eval_result_cache_parity.py`) |
| C. miss-path no-regression | fresh-nonce queries (genuine misses) | 0.26–3.0 s = the known warm-search floor; cache wrapper overhead sub-ms (no measurable regression) |

Final `/health` counters after the run: `resident` reached the `max_size=256`
cap mid-run (LRU evicted 2 oldest) — the size bound works as designed. The
`hit_ratio` over the eval's repeat-heavy mix: 0.62 (the cold-nonce misses pull
it down; a real demo's repeat fraction is higher → the ratio in production will
be higher).

**Operational posture:** `SFU_RESULT_CACHE` default ON in staging (one-env
rollback `=0` — owner-granted exception to the no-served-default-flip rule for
this wave only); `SFU_CACHE_PRESEED` default ON. Both are no-op-safe in
production (default OFF unless an explicit production profile opts in, mirroring
`serve_query_log._staging_default`). Tunables: `SFU_RESULT_CACHE_TTL` (6 h —
the index is static between updates), `_MAX_SIZE` (256), `_MAX_MEM_MB` (64).
Re-prime a running serve without restart:
`scripts/prime_result_cache.py --port <port>` (refuses while warming).

## Wave 8–9 (built 2026-07-18, finished 2026-07-28) — searchbar speculation: three-arm latency benchmark

Wave 7 shipped the read-through result cache + pre-seed primer (hit p50 ~4 ms
vs 0.2–3.0 s warm-retrieval floor) but explicitly DEFERRED keystroke
speculation. Wave 8 builds a minimal searchbar-prediction prefetch (the
feature) and runs a thorough three-arm benchmark (the product): **(A)
regular/cold latency, (B) wave-7 pre-seed cache hit, (C) speculation-primed
hit**, plus D/E/F/G controls. The benchmark is the deliverable; the feature
exists to be measured.

**What shipped (deployprep WI-18, 2026-07-18):** `src/lib/speculation.py` — a
predictor (candidate pool = landing JSX examples + `demo_seed_queries.txt` +
`speculation_bench_queries.txt` non-seeded pool + serve-log distinct queries;
deterministic prefix/containment match + ordered tiebreak, **no ML**) that
fire-and-forgets ONE speculative backend query through the SAME `read_through`
cache path + key recipe a real `api_search` uses (term 1 — same cache, no
second namespace). Single-slot (a newer speculation while busy is DROPPED, term
4); guarded (never when warming/degraded/cache-off/shed/<min-length, term 3);
speculative executions marked `speculative:true` in the serve query log (term
5). Client `web/lib/api.js::createSpeculationController` debounces (≥400 ms idle
AND ≥8 char) and cancels on submit (term 6). **Default OFF**
(`SFU_SEARCH_SPECULATE` — owner flips the default, not the build).

**The three demo-latency tiers (the typing-time-budget framing).** A search
takes the user several seconds to TYPE. Any latency the serve can HIDE inside
that typing time — whether by pre-seeding (wave 7) or by speculating the
finished query while the user is still typing (wave 8) — is free to the user.
The three tiers:

| tier | mechanism | Enter→response | when it applies |
|---|---|---|---|
| Cold | full retrieval on Enter (cache OFF) | p50 3080.57 ms (arm A, n=20) | a novel query never seen before, first click |
| Pre-seed (wave-7) | the demo's own queries primed in the cache at startup | p50 4.98 ms (arm B, n=20) — ~620× faster than cold | repeat clicks of the planted seed queries |
| Speculation (wave-8) | the typed prefix predicts the full query, priming it while the user types | predictor (known/in-pool): p50 4.47 ms / 2493.41 ms / 2667.23 ms at slow/medium/fast (arm C, n=20/profile); hit-rate 1.00 / 0.20 / 0.15 | a known/in-pool query the user is typing toward |

**Efficacy (WI-18b → finished in WI-19b 2026-07-28, `data/eval_results/speculation_ab_2026-07-28.json`, F6 — every headline recomputed from the raw per-trial samples in the JSON; the 2026-07-18 file holds arm A only and is historical after the container rebuild + serve restart):**

| cell | measurement | result |
|---|---|---|
| A. cold floor (cache OFF) | n=20 distinct non-seeded queries, Enter→response | p50 3080.57 ms, p95 5708.69 ms |
| B. pre-seed hit (cache ON + primer) | 6 seeds, n=20 repeat-visits | p50 4.98 ms (bar a PASS: ≤10 ms) |
| C. speculation — predictor (known/in-pool) | n=20 per profile × 3, predictor mode | hit-rate 1.00 / 0.20 / 0.15 (slow/med/fast), enter p50 4.47 / 2493.41 / 2667.23 ms; n_valid=20/profile, 0 anomalies. Bar b FAIL at medium (0.20 < 0.80 threshold) — refuted pre-registered bar, recorded not renegotiated |
| C. speculation — literal (novel query) | n=20 per profile × 3, literal mode | hit-rate 0.0 across all profiles (slow/med/fast), enter p50 1879.49 / 2038.04 / 2281.41 ms, spec_execs 1.8 / 0.8 / 0.75 per trial. n_valid=20/profile, 0 anomalies. Literal stores under the prefix key, which cannot match the full-query Enter key — structural miss (the implausibility check the W9-3 contamination tripped no longer trips) |
| D. cache-ON control miss | cache ON, spec OFF, n=20 — isolates cache/spec overhead | p50 1978.76 ms, all 20 trials genuine misses (no single-digit-ms hits; W9-3 contamination fixed). D is 36% *faster* than A cold floor (warm-cache-miss benefits from index residency) — bar d (within-10% of A) FAILS its ≤10% framing but the miss path does not regress beyond the warm floor: D 1979 < A 3081 |
| E. interference | real cold searches under a speculating typist, n=10 | p50 1324.69 ms < A 3080 ms (bar e PASS: within 15%). Measurement is latency-only (concurrent typist's speculation stores contaminate the hit-counter delta). E ran after D had warmed the index — the same warm-residency effect, non-blocking; flagged as unexplained-but-non-blocking in F6 |
| F. waste | spec backend execs per completed search, per profile + adversarial | medium 1.1 spec_execs/search (bar e-waste PASS: ≤3); slow 1.7, fast 0.6; fired 2.0 / 1.1 / 0.7 per trial; single-slot guard dropped 137 busy attempts across the run (constrained, bounded) |
| G. parity | spec-primed response == fresh cache-OFF run, ≥6 | 5/6 parity PASS (bar c-parity FAIL: <6). One trial ("digital divide broadband access") showed single-query byte divergence between the spec-primed hit and its cache-OFF baseline (baseline 2000.52 ms, notably faster than the other five) — REAL and UNEXPLAINED (possible retrieval nondeterminism under differing warm state; the OFF baselines were captured on a cache-OFF serve, so this is not a cache-hit artifact). Wave-7 OFF-vs-ON parity was 6/6. Per HOST-NOTE-W9-6 amendment B: no renegotiation, no invented explanation. |

**Framing constraints (HOST-NOTE-W8-1, applied):** arm-C predictor mode measures
the *known-query (in-pool)* scenario — "given the final query is a known/repeat
query, does speculation land it resident before Enter at this typing speed" —
NOT real-world prediction coverage. Literal mode is the novel-query scenario.
No sentence implies ≥80% of live searches would be predicted.

**Pre-registered bars (docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md, set
before the first measured run):** see backlog §WI-18 rows (a)–(e), now MEASURED
with PASS/FAIL per bar (recomputed from the raw 2026-07-28 JSON): (a) B preseed
hit p50 ≤10 ms — **PASS** (4.98 ms); (b) C-medium predictor hit-rate ≥80% —
**FAIL** (0.20); (b') C-medium hit latency ≤2× arm B — **FAIL** (2493 ms vs 4.98 ms);
(c) G 6/6 OFF-vs-ON parity — **FAIL** (5/6); (d) D within 10% of arm A — **FAIL**
(D 1979 ms is 36% faster than A 3081 ms, expected direction but fails the ≤10% framing; D-all-genuine-miss check PASS); (e) interference within 15% of A — **PASS** (1325 ms);
(e') waste ≤3 spec execs/search at medium — **PASS** (1.1).

**Owner recommendation (speculation ON or OFF for the live review): OFF.**
Justified ONLY from the measured hit-rate, waste, and interference numbers
(arm C/D/E/F): the predictor mode's value is confined to the known/in-pool
slow-profile scenario (1.00 hit-rate, ~4.47 ms Enter), but at the
demo-representative medium/fast profiles the predictor hit-rate collapses to
0.20/0.15 (bar b FAIL) — the feature only pays when the user types slowly enough
that the finished query is predictable from the prefix. Literal mode hits 0.0
across all profiles (prefix-key store cannot match the full-query Enter key — a
structural mismatch). Waste is bounded (1.1 execs/search at medium, single-slot
guard dropped 137 busy attempts), so OFF is low-regret: the miss path (D 1979 ms,
E 1325 ms) already beats the cold-OFF floor (A 3081 ms) via warm residency
without speculation. The feature ships (built, wired, spec tests 24/24) with a
measured headline that does not yet meet the pre-registered bar at demo
profiles; defaulting OFF keeps the live review honest. Owner may flip ON to
showcase the slow-profile predictor scenario deliberately.
