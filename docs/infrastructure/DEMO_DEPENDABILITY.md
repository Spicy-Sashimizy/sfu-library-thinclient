# Demo dependability harness — staging serve that survives strangers' traffic

**Created 2026-07-16 (deployprep WI-3). STAGING ONLY — not deployed.** The
in-container measurement harness proving the demo survives unattended
strangers' traffic: 3-leg health checks, a watchdog, concurrent load with
induced failure, graceful degradation, overload shed, the pre-launch soak
gate, and update/rollback flows. Owner constraint (2026-07-16): NO public
deploy, NO spend, `data/seismic_150m/` READ-ONLY. Code-level constraints for
these harnesses: `docs/CODE_INVARIANTS_SCRIPTS.md`.

Dependable = (1) `/health` covers all three legs + federation mode; (2) the
watchdog restarts a wedged/dead serve (only a process IT started —
`SFU_DEMO_WATCHDOG` kill-switch; it never adopts/kills a foreign process);
(3) load holds under concurrency and recovers from a mid-load SIGKILL.

| File (`scripts/demo_dependability/`) | Role |
|---|---|
| `staging_serve.py` | stdlib HTTP server over `ThinClientRetriever.search_rrf` (3-leg RRF); `/health` + `/search`; real `data/thinclient_index`; port `SFU_DEMO_STAGING_PORT` (default 8159). Not the MCP server |
| `watchdog.py` | launch + `/health` probe + restart on death/wedge (`SFU_DEMO_WATCHDOG_HEALTH_TIMEOUT`, `_WEDGE_N`); writes `_deployprep_watchdog_report.json` |
| `load_driver.py` | concurrent load (1/4/8/16) + induced-failure arm (`--induce-failure --serve-pid`) |

## WI-3 — baseline + induced failure (MEASURED 2026-07-16)

Baseline sweep (`wi3_load_baseline_20260716_230808.json`; 40 req/level,
20-query set, top_k=10, 3-leg RRF over e5_v2, 64 GB container):

| concurrency | p50 (ms) | p95 (ms) | mean | errors | qps |
|---|---|---|---|---|---|
| 1 | 4415 | 16237 | 5590 | 0/40 | 0.2 |
| 4 | 3643 | 4792 | 3060 | 0/40 | 1.2 |
| 8 | 4357 | 5129 | 3514 | 0/40 | 2.1 |
| 16 | 5866 | 7822 | 4920 | 0/40 | 2.8 |

**0% errors at every level (160/160).** The 4–6 s p50 is the cold-9p-fault
floor (20 diverse queries ≈ the full ~15 GB forward working set), not a
compute verdict — WI-1 parallel warm p50 is 47 ms on resident cache.
Throughput rises 0.2 → 2.8 qps (real parallelism: ThreadingHTTPServer +
GIL-releasing pyseismic search).

Induced failure (SIGKILL at t=3 s of a 30 s run @ c=8,
`wi3_load_failure_*.json`): kill confirmed (rc=-9); 829 dead-window errors;
0 client OKs in-window (`first_client_recovery` null); **watchdog
health-recovery 2435 ms**; healthy after restart. Read: process recovery is
seconds-fast, but the first `/search` after restart pays the cold lazy-load
— the gap WI-6 closes with a warmup hook.

`/health` (warm ~7 ms): reports per-leg configured/ok + SPLADE backend +
federation mode; deliberately lightweight (a full cold 3-leg probe is
~minutes). Wedged legs are caught by `available=False` or the watchdog's
probe timeout.

Caveats: single host, 127.0.0.1 only (cloud-tier dependability is
`OCI_DEMO_DEPLOYMENT.md`); the watchdog is the measurement harness, not a
production supervisor (the NUMBER transfers, the process doesn't).

## WI-6 — startup warmup + recovery-to-first-good-QUERY (2026-07-17)

Closes the WI-3 gap (`/health` up ≠ `/search` warm). Hook = F6 hotset
prefault (`SFU_SEISMIC_PREFLOOR_HOTSET=1`; cold p95 4600→1674 ms,
2026-07-14) + a fixed warmup query set through `search_rrf`
(`SFU_DEMO_WARMUP=1`, `_N=24`, `_TOPK=10`); `/health` gains `warm` state;
`SFU_DEMO_WATCHDOG_WAIT_WARM=1` holds recovery until `warm=true`. Default
OFF. (The Q9 floor prefault was REFUTED as a lever here 2026-07-10: cold
p50 ratio 1.025.)

Induced-failure A/B (kill t=4 s, c=8, 12-query set):

| signal | BEFORE (no warmup) | AFTER (hook ON) |
|---|---|---|
| dead-window errors | 1147 | 253002 (360 s window — not comparable across window lengths) |
| client OKs after kill | 0 | 73 (p50 4878 / p95 6066 ms) |
| recovery-to-first-good-QUERY | null | **323998 ms (~5.4 min)** |
| watchdog recovery | 2724 ms (health-only) | **319215 ms warm-recovery** |

Files: `wi6_recover_before_20260717_005541.json` (the valid rerun — an
earlier `...005321.json.INVALID` came from the `eval "true "` launcher bug,
6502 bogus errors, marked INVALID), `wi6_recover_after_long_20260717_010457.json`
(the 360 s window with the real number; the 40 s
`wi6_recover_after_20260717_005541.json` closed before re-warm),
`_wi6_watchdog_report_after_long.json` (`restarts[0].recovery_ms=319215`).

**Verdict: the hook is CORRECT** (first_client_recovery flips null → measured;
serve answers warm after restart) **but the ≤~5 s bar is NOT met on 9p** —
a SIGKILL re-warm re-faults the whole working set (~5.4 min, same floor as
the initial ~302 s warmup). The bar is met on a native-ext4 host (ms-scale
faulting) or with an mlock'd hot set (prefaulted pages are reclaimable and
re-fault; mlocked ones survive restart) — the host-tier pin is owner-gated.
Recorded, not papered.

## WI-7 — warm-state concurrent capacity (2026-07-17)

Pre-warmed via the WI-6 hook (warmup 310.5 s), 40 req/level
(`wi7_warm_capacity_20260717_011753.json` + per-cell files):

| concurrency | p50 (ms) | p95 (ms) | errors | qps | majflt Δ |
|---|---|---|---|---|---|
| 1 | 3327 | 4058 | 0/40 | 0.4 | 4608 |
| 4 | 3767 | 4566 | 0/40 | 1.2 | 7321 |
| 8 | 4304 | 5361 | 0/40 | 2.1 | 8172 |
| 16 | 6111 | 8309 | 0/40 | 2.7 | 16552 |
| 32 | 10344 | 13562 | 0/40 | 2.9 | 23908 |

**0% errors (200/200), monotone throughput to the ~2.9 qps knee** — but
warm p50 stays 3.3–10.3 s on 9p because the diverse working set is not
resident (majflt Δ rising 4608→23908 proves re-faulting under contention):
working-set-bound, not compute-bound. The ≤250 ms warm bar is NOT met on
9p; on a native host with RAM ≥ the ~16 GB working set the WI-1
tens-of-ms range applies and the 0%-error + monotone-throughput properties
transfer. DO_SIZING pointer: the served stack is SEISMIC since 2026-07-06 —
`DO_SIZING.md`'s Qdrant SPLADE figures don't apply (a pointer row was added
there).

## Wave 3 (2026-07-17) — graceful degradation (all env-gated OFF by default)

Pre-registered in `docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md`
§WI-9..12. OFF = byte-identical to wave-1/2 behavior.

### WI-9 — leg breaker (`leg_breaker.py`, `SFU_DEMO_LEG_BREAKER=1`)

Per-leg timeout (`SFU_DEMO_LEG_TIMEOUT_S`, 30 — sized for a HUNG leg, not a
slow one) in a DEDICATED daemon thread per leg (a shared pool was the
first-attempt bug: one hung leg starved all three); circuit breaker
(`_BREAKER_N`=3, `_COOLDOWN_S`=8, half-open probe); RRF over surviving
legs; `degraded: [leg,…]` on every search + an amber `/health` state.

MEASURED (`wi9_fault_injection_20260717_022742.json`; mocks only, Rule
Zero; `remote_abstracts=False` to keep OpenAlex 429s out of attribution):

| fault | DURING p50/p95 (ms) | degraded | results | recovers |
|---|---|---|---|---|
| SPLADE hung (sleep 60) | 30002 / 30003 | `['splade']` | 4/4 | ✅ |
| SPLADE throws | 3212 / 3370 | `['splade']` | 4/4 | ✅ |
| dense throws | 3655 / 3777 | `['dense']` | 4/4 | ✅ |
| BM25F throws (was a 5xx) | 115 / 119 | `['bm25f']` | 4/4 | ✅ |
| encoder down | 3204 / 3586 | `[]` (graceful mirror, breaker correctly untripped) | 4/4 | ✅ |

**VERDICT: PASS — 20/20 bars** (no 5xx storm; results returned; `degraded`
names the leg; breaker re-admits). Headline: a hung SPLADE degrades ONLY
splade — BM25F + dense stay healthy. The proof runs the retriever
directly; the serve wires the same `LegGuardian.search_rrf_degraded`.

### WI-10 — shard isolation (`SFU_SEISMIC_SHARD_FAULT_BOUNDARY=1`, owner ask)

Per-shard LOAD and SEARCH fault boundaries in BOTH federation classes: a
failed load gets a None placeholder (other 7 load); a throwing/timed-out
search returns `[]` + recorded fault (`SFU_SEISMIC_SHARD_SEARCH_TIMEOUT_S`
30, reprobe `_REPROBE_S` 10); `degraded_shards` surface; the shared merge
unchanged. T1 bit-identity unaffected by construction.

MEASURED (`wi10_shard_isolation_20260717_023630.json`; `_FaultyShard`
wrappers + truncated fixtures under `data/eval_results/_fixtures/` only):

| fault | shards | recall@10 | degraded | re-admit | p50 (ms) |
|---|---|---|---|---|---|
| search exception (parallel) | 8 (1 faulted) | 0.850 | shard0 | ✅ | 98 |
| search hang (parallel) | 8 (1 faulted) | 0.850 | shard0 | ✅ | 117 |
| search exception (sequential) | 8 (1 faulted) | 0.850 | shard0 | ✅ | 270 |
| load absent | 7/8 | 0.850 | shard0 | ✅ | 123 |
| load truncated | 7/8 | 0.850 | shard0 | ✅ | 120 |

**VERDICT: PASS — all cells, all bars.** Recall retention 0.850 in every
cell = the bounded ~1/8 hash-sharding loss, inside the pre-registered
[0.80, 0.95] band (doc 09's calibration-unnecessary-by-construction, now
measured); survivors don't slow down.

### WI-11 — overload shed (`SFU_DEMO_OVERLOAD_SHED=1`)

BoundedSemaphore (`SFU_DEMO_MAX_INFLIGHT` 64) + accept queue
(`SFU_DEMO_ACCEPT_QUEUE` 64, `SFU_DEMO_QUEUE_WAIT_S` 1); shed = clean 429 +
Retry-After; gate on `/search` only (never `/health`, so the watchdog can't
mis-read a shed storm as a wedge).

MEASURED (`wi11_overload_20260717_030631.json`; gate 16/16, c=128 = 8× gate
depth):

| phase | p50 / p95 (ms) | ok | 429s | collapse | qps |
|---|---|---|---|---|---|
| pre c=4 | 4186 / 6258 | 40/40 | 0 | 0 | 1.1 |
| overload c=128 | 10440 / 11917 | 21 | 175 | 4 (2%) | 16.2 |
| post c=4 | 4381 / 5358 | 40/40 | 0 | 0 | 1.2 |

**VERDICT: PASS — all 3 bars** (bounded accepted tail ≤3× baseline; sheds
are clean 429s with collapse ≤5% socket edge; post-overload returns to
≤1.5× baseline). Shed, don't collapse.

### WI-12 — the pre-launch reliability soak gate

`reliability_soak.sh`: ~30-min soak @ `SFU_DEMO_SOAK_QPS` 0.3 with a
scheduled fault timeline (overload burst + watchdog SIGKILL), one
PASS/FAIL timeline report. Bars: (a) availability ≥95% (ok-or-shed /
accepted; a clean 429 counts ok); (b) every fault → timestamped
degradation + recovery events; (c) worst-phase p95 ≤ ~5× warm baseline.
Run `bash scripts/demo_dependability/reliability_soak.sh` before any
launch.

MEASURED 2026-07-17 (`wi12_soak_20260717_032757.json` + `.md`):
availability **0.822** (96/540 fails); p50/p95/p99 2634/3405/3544 ms; 8
timeline events; SIGKILL→warm 312856 ms; 33 clean 429s in the burst.
**VERDICT: FAIL bar (a), PASS (b)+(c)** — the 96 fails ARE the ~5.2-min
9p re-warm dead-window WI-6 already owns (math checks: 5.2/30 min ≈
17.8%). On a native host the dead window collapses to seconds → (a)
passes.

**Route B — ext4-overlay re-run attempt (2026-07-28, smoke-gate STOPPED):**
staged all 8 shards (42 GB, byte-verified) to container-local ext4 via the
existing `retriever._stage_shards_local()` lever
(`SFU_SEISMIC_STAGE_DIR=/home/vscode/seismic_ext4`); `_fstype_for_path()`
flipped 9p→overlay and `_auto_federation_mode()` auto-selected parallel —
the FS is no longer classified slow. Smoke SIGKILL cell: warm-recovery
**159124 ms vs 319215 ms on 9p (~2.0× faster, real)** — but the
pre-registered smoke bar (≤~85 s to proceed) was NOT met, so the full soak
was correctly not run (projected ~91.2% availability, still <95%).
Root cause (`wi12_ext4_diagnosis_20260728.json`): (1) first-touch of 42 GB
on this container's WSL2-virtualized overlay is itself ~80–95 s, and the
~85 GB+ combined working set exceeds the 56 GB RAM (cache eviction forces
real reads) — a real droplet's NVMe + right-sized RAM is where bar (a) is
expected to pass; (2) ~18 s non-disk first-query overhead (cold ONNX
session + hydration + OpenAlex 429 retries) present in both arms. Timing
detail: ctor+is_available 2.2 s; seismic backend prefault-ON 82.7/80.2 s;
prefault-OFF 1.9 s but first search 94.3 s; first search prefault-ON
`remote_abstracts=False` 18.2 s; second 3.8 s. **VERDICT: MEASURED, NOT
PASSED.** The ext4 copy is ephemeral (lost on rebuild) — a measurement
config, not a serving path. Files: `wi12_ext4_smoke_induced_20260728.json`,
`_wi12_ext4_smoke_watchdog_report_20260728.json`. Also found at session
start: no pre-existing serve survived the container rebuild
(`data/watchdog_status.json` stale since 2026-05-13); alternate-port
discipline (8261) followed regardless.

## Wave 4 (2026-07-17) — update mechanisms

### WI-13 — versioned update + auto-rollback (demo host)

Update unit = the 4-tuple in `deploy_versions.json`
(`deploy_versions.py`): code rev, seismic `.so` variant (~2.7 MB), index
manifest (the versioned POINTER + one-env rollback ladder e5_v2 → e5_v1 →
plain dv, per-shard checksums), models. Delta-class expectations: `.so`
~2.7 MB; encoder distill ~1 GB; E8 re-conversion ~26 GB; manifest-flip
~7.5 KB.

`update_demo.sh` flow: git pull → verify checksums vs
`deploy_versions.json` (abort BEFORE the flip on mismatch) → stage the new
manifest BESIDE the old → flip `SFU_SEISMIC_SHARD_MANIFEST` → warm-restart
via the watchdog (wait-warm) → health + smoke + `/verify` gate →
AUTO-ROLLBACK on failure (flip back, warm-restart, post-rollback gate must
PASS).

**Gate-strengthening finding:** `/health` reports
`splade.configured="seismic"` whether or not shards LOADED — the retriever
silently falls back to BM25F on a broken shard set, so a 200 `/search`
would commit a silently-degraded update. Fix: `/verify`
(`SFU_DEMO_UPDATE_VERIFY_SEISMIC=1`, OFF by default) forces the lazy
`_seismic_backend()` load and reports `seismic_loaded`; the gate asserts
it. `/health` alone cannot catch this.

MEASURED 2026-07-17, two fixture arms:
- **Success** (`wi13_update_success_20260717_045419.json`): staged
  copy-flip, gate PASS (`search=6 ok/0 fail, seismic_loaded=True`), no
  rollback; downtime 226585 ms (9p re-warm; ms-scale on native). Bar (a) ✅.
- **Broken** (`wi13_update_broken_20260717_045419.json`): truncated-shard0
  fixture manifest; serve comes up via silent BM25F fallback
  (`wait_warm=ok`!) but `/verify` catches `seismic_loaded=False` → gate
  FAILS → auto-rollback → post-rollback gate PASSES → serving on the prior
  version. Downtime before rollback 186913 ms;
  `overall=PASS_ROLLED_BACK`. Bars (b)(c)(d) ✅ (stage-beside preserved the
  old artifacts; checksums verified both arms).

The success arm models the cheapest update class; the real cross-version
flip is already proven by the served E5/E8 rollouts (2026-07-09 /
2026-07-14). Drive log: `data/eval_results/_wi13_update_drive4.log`.

## Wave 7 (2026-07-18) — WI-17 result cache + pre-seed

Read-through result cache on `api_search` reusing `lib/cache.ResponseCache`
(TTL+LRU+memory-bounded): check versioned cache → miss → search → store.
Cache-aside (a cache failure never fails a search); never caches errors,
degraded (WI-9/WI-13) responses, or pre-warmup results; the key embeds the
served manifest `built`+`engines` stamp (index/model swap ⇒ new key).
Pre-seed primer (WI-17b) plants the demo queries after warmup,
sequentially (single-GPU CE), idempotent; re-prime without restart:
`scripts/prime_result_cache.py --port <port>`.

Efficacy (WI-17c, `result_cache_ab_2026-07-18.json`, all 4 bars PASS):
hit p50 **3.7–4.1 ms** vs cold-miss 0.2–3.0 s → **50×–776×**; round-trip
parity 6/6; **OFF-vs-ON byte parity 6/6** (`eval_result_cache_parity.py`);
miss path unregressed (sub-ms wrapper overhead). `resident` hit the 256
cap mid-run (LRU worked); eval hit_ratio 0.62 (repeat-heavy production
will be higher). Posture: `SFU_RESULT_CACHE` staging-ON (owner-granted
exception; `=0` is the one-env rollback), TTL 6 h, max_size 256,
max_mem 64 MB.

## Waves 8–9 (2026-07-18 → 2026-07-28) — WI-18 searchbar speculation

`src/lib/speculation.py`: deterministic predictor (landing JSX examples +
seed/bench pools + serve-log distinct queries; no ML) fire-and-forgets ONE
speculative query through the SAME `read_through` path/key a real submit
uses; single-slot (busy ⇒ dropped); guarded (warming/degraded/cache-off/
shed/min-length); `speculative:true` in the serve log. Client debounce
≥400 ms idle + ≥8 chars (`web/lib/api.js::createSpeculationController`).
**Default OFF** (`SFU_SEARCH_SPECULATE` — owner flips defaults).

Three latency tiers (Enter→response): cold p50 3080.57 ms (arm A) ·
pre-seed hit p50 4.98 ms (arm B, ~620×) · speculation-primed p50 4.47 ms
at slow typing (arm C predictor, hit-rate 1.00), collapsing to 2493/2667 ms
at medium/fast (hit-rate 0.20/0.15).

Full 2026-07-28 benchmark (`speculation_ab_2026-07-28.json`; F6 recomputed
from raw; the 2026-07-18 file holds arm A only): D cache-ON control miss
p50 1978.76 ms, all 20 genuine misses (the W9-3 pool-contamination fix
held); E interference p50 1324.69 ms (latency-only by design); F waste 1.1
spec-execs/search at medium (slow 1.7, fast 0.6; 137 busy drops); G parity
5/6 — one trial ("digital divide broadband access") byte-diverged, REAL
and UNEXPLAINED, recorded per HOST-NOTE-W9-6 (no renegotiation). Literal
mode: hit-rate 0.0 everywhere (prefix-key store structurally cannot match
the full-query Enter key).

Pre-registered bars: (a) preseed ≤10 ms **PASS** (4.98); (b) C-medium
hit-rate ≥0.80 **FAIL** (0.20); (b') C-medium ≤2× arm B **FAIL**; (c) G
6/6 parity **FAIL** (5/6); (d) D within 10% of A **FAIL** (D is 36%
*faster* — expected direction, fails the framing; all-genuine-miss check
PASS); (e) interference within 15% **PASS**; (e') waste ≤3 **PASS** (1.1).

**Owner recommendation: OFF for the live review** — the predictor only
pays at slow typing on in-pool queries; medium/fast hit-rates collapse;
the miss path already beats the cold floor via warm residency. Ships
built + wired (spec tests 24/24); owner may flip ON to showcase the
slow-profile scenario deliberately.
