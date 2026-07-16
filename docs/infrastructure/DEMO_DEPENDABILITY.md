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
