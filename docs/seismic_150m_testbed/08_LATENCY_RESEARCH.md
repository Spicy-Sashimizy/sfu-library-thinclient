# 08 · Latency Research — RAM-efficient ways to speed up the SEISMIC serve leg

**Status:** ACTIVE

**Created 2026-06-30.** Status: RESEARCH / DESIGN-ONLY. Every number below that is
not tagged `[OURS]` is an **external literature figure** (paper/benchmark on a
different corpus + host) — per the CLAUDE.md efficacy rule it is **not a measured
result for our index** and must not be quoted as one. Treat them as *candidate*
techniques ranked for our G5/G8 latency work, with source links to read before
implementing.

## Why this doc exists (the forcing observation)

> **UPDATE 2026-06-30 (RESOLVED):** the swap confound below is solved (SEISMIC-only,
> Qdrant stopped), and the follow-on RAM-starvation question is now answered too.
> Two same-box runs: at a **32 GB** WSL cap latency was page-cache-starved (warm
> p50 **18.1 s**); raising the cap to **56 GB** to cache the working set dropped
> warm p50 to **0.55 s — a 33× collapse with no other change**, proving the 15–18 s
> was RAM starvation, *not* the engine. **SEISMIC at 150 M is ~0.5 s warm when
> provisioned to cache the working set (~40 GB here); RAM floor stays 1.13 GB versus
> Qdrant ~17 GB.** Details in **§A1 measured** (#1 and #2).

The G8 latency bench (2026-06-29/30) is **swap-contaminated and not a verdict**:

- 66 GB mmap'd 8-shard working set on a **31.6 GB** host already **~15/16 GiB into
  swap**. Each query touches different postings → faults new pages from swap.
- Observed `[OURS]`: ~86 s/paired query; Qdrant portion ~6–7 s (itself inflated —
  `splade_150m` is `status=grey`, not optimized); inferred SEISMIC ~80 s/query is
  **almost entirely swap page-fault time, not engine traversal**.
- The RAM half is already clean and decisive `[OURS]`: anon floor **0.142 GB**
  (SEISMIC mmap) versus **6.71 GB** (Qdrant). The *latency* half is the open question.

So this doc splits into two jobs: **(A) make the measurement clean** (you cannot
research latency on a thrashing host), and **(B/C/D) the techniques that lower
latency while keeping the RAM win** — the whole point of the SEISMIC pivot is the
mmap RAM floor, so any latency fix that re-inflates anon RAM is self-defeating.

Cross-refs: G5/G8 rows in [`02_GO_NO_GO_GATES.md`](02_GO_NO_GO_GATES.md); the serve
footprint finding in [`06_FINDINGS.md`](06_FINDINGS.md) (2026-06-28 row); the mmap
reader C2/C2.5 in [`07_G3_RAM_FIX_PLAN.md`](07_G3_RAM_FIX_PLAN.md).

---

## A. Make the measurement clean FIRST (no new index work needed)

These do not change the index — they change *how we measure*, so the next run
attributes latency instead of measuring swap. **Do these before any B/C/D work.**

### A1. Bound the working set so a faulted page never goes to swap
On a host where RAM < working set, the kernel swaps *anonymous* pages to dodge
OOM, which thrashes everything. Two complementary controls:
- **cgroup v2 `memory.swap.max = 0`** on the serving slice → the workload never
  swaps; file-backed mmap pages are simply reclaimed/re-read from the index file
  (cheap, sequential-ish) instead of fighting the anon swap. This converts
  "swap thrash" into "honest page-cache miss," which is the latency we actually
  want to measure. Pair with `memory.low` so the kernel reclaims from *other*
  procs first. ([cgroup2 memory controller](https://facebookmicrosites.github.io/cgroup2/docs/memory-controller.html),
  [Chris Down — in defence of swap](https://chrisdown.name/2018/01/02/in-defence-of-swap.html))
- **The real fix is a host whose RAM ≥ resident set** (expect ~7.5 GB anon +
  page cache for the 8 mmap shards, per the G8 projection). On such a box the
  mmap pages stay in page cache and the swap term vanishes — that is the *only*
  configuration that yields a trustworthy SEISMIC-vs-Qdrant p50.
  > **CORRECTION — MEASURED 2026-06-30 (see "A1 measured" below):** the ~7.5 GB
  > VmRSS figure is the *instantaneous* resident window, **not** the cache a warm
  > p50 needs. 40 diverse queries touch postings spanning the **full ~62 GB
  > index**, so a host with only ~7.5 GB free still re-faults continuously. The
  > true requirement is **RAM ≥ ~62 GB (whole index cacheable)**; "RAM ≥ resident
  > set" is necessary but **insufficient**.

> **Turnkey wrapper (2026-06-30):** `scripts/seismic_testbed/run_g8_latency_noswap.sh`
> stages the whole §A1 + §C1 + §A4 recipe as one command. It (1) tries to bound
> swap — cgroup v2 `memory.swap.max=0` first, `swapoff -a` second, and if
> *neither* is permitted (the common read-only-cgroup / WSL2 case) prints a loud
> CAVEAT instead of silently proceeding; (2) pre-stages the §C1 lever
> (`SFU_SEISMIC_QUERY_CUT=10` default → 4× traverse @ overlap@10 0.995) and
> `--passes 2` (real warm p50); (3) runs `serve_footprint_bench.py` with the
> §A4 encode/traverse split; (4) captures the **actual resident set** (RssAnon
> / VmSwap / VmRSS-peak + encode p50 / traverse p50) so the ~7.5 GB projection
> above finally gets a measured number, and reads `vmswap_gb` from the result to
> say definitively whether the run was clean (≈0 swap → verdict) or still
> swap-confounded (>0 swap → record, do not conclude — same status as the
> 2026-06-29 run). The bench now honors `SFU_SEISMIC_QUERY_CUT`/`HEAP_FACTOR`/
> `K_PRIME` (matching the served retriever's environment) and accepts plain-list
> manifests via `_load_manifest`. **Env-gated reality on this container
> (measured 2026-06-30):** `/sys/fs/cgroup` is mounted **read-only** and
> `swapoff` reports "Not superuser" even under sudo → the cgroup/swapoff paths
> are walled off here; getting a real no-swap run needs either a host with
> writable cgroup v2, or the operator setting `memory.swap.max=0` on this
> container's slice. Run:
> ```bash
> sudo environment "PATH=$PATH" scripts/seismic_testbed/run_g8_latency_noswap.sh \
>     --shard-manifest data/eval_results/seismic_c25_shards_150m_mmap.json \
>     --queries 40 --passes 2
> # disable C1 to measure the all-terms baseline: SFU_SEISMIC_QUERY_CUT= ./...
> # Path-A control on a testbed index: SFU_SEISMIC_LOAD_MODE=stock ./...
> ```

#### A1 measured — first clean SEISMIC-only G8 run `[OURS]` (2026-06-30)

Run on the `claudebox-sfu-library-thinclient-app` container (Docker-in-WSL2,
**64 GB physical / 32 GB WSL2 cap**). The 2026-06-29 run was confounded by
**anon swap thrash** caused by co-loading Qdrant's ~17 GB heap; this run removed
that by **stopping the Qdrant process** (`supervisorctl stop qdrant-spike`),
which drained swap **12 GiB → 0.17 GiB** before launch. SEISMIC-only, 8-shard
150 M mmap (`federation=parallel`), `SFU_SEISMIC_QUERY_CUT=10`, 40 queries × 2
passes.

- **Eval:** `scripts/seismic_testbed/run_g8_latency_noswap.sh` → `serve_footprint_bench.py`
- **Result:** `data/eval_results/seismic_g8_150m_serve_noswap_20260630_065143.json`
  (corpus `total_docs=150,413,098`)

| Metric `[OURS]` | Value | Note |
|---|---|---|
| mmap load (8 shards) | **0.41 s** | lazy mmap; post-load RssAnon 0.14 GB |
| RssAnon floor | **1.12 GB** | the decisive RAM win (versus Qdrant ~17 GB) |
| **VmRSS peak** | **7.71 GB** | ← the §A1 "~7.5 GB projection" **CONFIRMED measured** |
| VmSwap | 0.69 GB | minor anon; the 17 GB swap thrash is **gone** |
| encode p50 (SPLADE) | cold 65 / warm 74 ms | trivial — **not** the bottleneck |
| traverse p50 (8-shard fan-out) | cold **15.1 s** / warm **18.0 s** | ~99.6 % of latency |
| end-to-end p50 | cold **15.2 s** / warm **18.1 s** | warm ≥ cold (see below) |

**Verdict: latency is DISK-FAULT-BOUND, not a compute verdict.** Two confounds
were conflated in 2026-06-29; this run separates them:

1. **Anon swap (SOLVED).** Stopping Qdrant removed the 17 GB heap → swap drained,
   SEISMIC VmSwap fell to 0.69 GB. The swap-thrash story is closed.
2. **Index > cacheable RAM (the real 150 M wall).** `RssFile` could hold only
   ~7.5 GB of the **62 GB** index at once; 40 diverse queries faulted different
   postings across all 8 shards, so the page cache (~29 GB, maxed) churned and
   re-read from the vhdx disk continuously (**majflt ≈ 661 k**). Decisive tell:
   **warm p50 (18.1 s) ≥ cold p50 (15.2 s)** — there is *no* warm-cache benefit
   because the working set never fits, so pass 2 re-faults as much as pass 1.

**Why the full-corpus warm p50 was unmeasurable at the 32 GB cap** *(largely
RESOLVED — see "A1 measured #2" below)*: a warm p50 needs the touched working
set in page cache. At 32 GB the cache (~29 GB) was smaller than the ~40 GB the
40-query set touches, so it churned. **Raising the WSL2 cap to 56 GB (2026-06-30)
fit the working set and dropped warm p50 from 18.1 s → 0.55 s — a 33× collapse,
proving the 15–18 s was RAM starvation, not the engine.** The *fully*-clean
(zero-swap) verdict still wants a ≥72 GB host (62 GB index + process + OS), but
the engine-speed question is now answered. Other paths to a perfectly-clean or
smaller-RAM result: (a) a ≥72 GB-RAM host; (b) shrink the index under cacheable
RAM (compression / fewer-larger shards / stronger `query_cut` pruning); (c) the
`sequential` backend's mechanism-B `MADV_DONTNEED` bounded-resident streaming.

**The compute floor IS measurable per-shard (fits cache):** the 1-shard smoke
(`data/eval_results/_g8_host_smoke.json`) gave warm **266 ms** (encode 41 +
traverse 223 ms), agreeing with the manifest's build-time `mmap_p50_ms ≈ 0.17 ms`
per shard. That is the engine-traversal latency; the 15–18 s above is *purely*
the can't-cache-62 GB penalty, not the engine.

**Wrapper/bench verdict gate — FIXED 2026-06-30:** previously the clean/verdict
gate keyed only on anon `VmSwap` (so it printed "needs RAM ≥ ~7.5 GB resident")
and the bench hardcoded a "swap-thrashing host" caveat — both **misleading** when
the dominant cost is **`RssFile` mmap re-faulting**. Both now use a **data-driven
gate**: a run is a verdict only if `VmSwap≈0` **AND** warm p50 < cold p50 (page
cache actually helped). Either symptom present — anon swap *or* warm ≥ cold
(index exceeds page cache) — is reported (composed, both if both), with the
unified root cause (**host RAM < working set**) and fix (**RAM ≥ index-on-disk
size + headroom**). On this run it correctly emits: *"NOT A VERDICT: VmSwap=0.69 GB
anon paged to swap; warm 18061 ms ≥ cold 15217 ms (index exceeds page cache →
re-fault from disk)."*

#### A1 measured #2 — same box, WSL2 cap 32 GB → 56 GB `[OURS]` (2026-06-30)

The #1 run was page-cache-starved (32 GB VM < ~40 GB touched working set). Raised
`%UserProfile%\.wslconfig` `memory=32GB → 56GB` (+ `swap=8GB`,
`autoMemoryReclaim=gradual`, `pageReporting=true`; `memory=` is a ceiling-on-demand
so idle RAM returns to Windows), `wsl --shutdown`, re-ran the **identical**
SEISMIC-only bench (8-shard 150 M mmap, `query_cut=10`, 40 q × 2 passes).

- **Result:** `data/eval_results/seismic_g8_150m_serve_noswap_56gb_20260630_074056.json`

| Metric `[OURS]` | 32 GB cap (#1) | **56 GB cap (#2)** | change |
|---|---|---|---|
| **warm p50** | 18,061 ms | **549 ms** | **33× faster** |
| warm p95 | 26,181 ms | 2,178 ms | 12× |
| cold p50 | 15,217 ms | 3,985 ms | 3.8× |
| warm traverse / encode p50 | 17,987 / 74 ms | **509 / 37 ms** | — |
| VmRSS peak | 7.7 GB | **40.4 GB** | working set now cached |
| VmSwap | 0.69 GB | 0.38 GB | residual (cold-pass peak) |
| RssAnon floor | 1.12 GB | 1.13 GB | RAM win unchanged |

**Finding — the engine is fast at 150 M; the 18 s was RAM starvation.** With the
working set cached, warm p50 is **~0.55 s** (traverse 509 ms + SPLADE encode
37 ms). Cold p50 also fell to ~4 s (first-touch faults still hit disk, but the
cache no longer thrashes). The 33× warm collapse with *no other change* isolates
the cause beyond doubt: prior 15–18 s = page-cache miss, not traversal cost.

**Caveats (why this is "near-clean", not a perfect verdict):**
- Residual `VmSwap=0.38 GB` — minor anon paged at the cold-pass peak (VmRSS hit
  40 GB + ~8 GB bench anon ≈ the 54 GB usable cap). The verdict gate still flags
  it `NOT A VERDICT (swap)` — correctly conservative — but warm (549) ≪ cold
  (3985) shows the *cache hit was real*; the swap is a cold-pass artifact, not a
  warm-steady-state confound.
- warm **p95 2.18 s** and max 2.3 s: the working set (~40 GB) mostly but not
  wholly fits, so a tail of warm queries still faults uncached postings. The true
  fully-cached compute floor is nearer the warm **min 93 ms** / the 1-shard smoke
  266 ms.

> **A1 measured #2b — max host RAM, FULLY-CLEAN verdict `[OURS]` (2026-06-30):**
> bumped the WSL cap to the practical host max **58 GB** (leave ~6 GB for Windows;
> `.wslconfig`), re-ran the identical 40-query bench. **VmSwap = 0.0 GB** (the
> 0.38 GB residual is gone) → the fixed verdict gate emits *"VmSwap≈0 and warm <
> cold → CLEAN. This p50 IS a verdict."* warm p50 **668 ms** (traverse 625 +
> encode 39), p95 2.18 s, min **126 ms**, VmRSS peak 41.2 GB, RssAnon 1.09 GB.
> Result `data/eval_results/seismic_g8_150m_serve_noswap_58gb_20260630_093602.json`.
> The 549↔668 ms warm-p50 wobble versus #2 is run-to-run noise (different cache start
> state); the decisive result is **zero swap → SEISMIC 150 M warm ≈ 0.5–0.7 s is a
> definitive clean verdict, not swap/cache-confounded.** 58 GB sufficed to zero-out
> swap for this ~41 GB working set; a working set touching the whole 62 GB index
> would still want ≥72 GB or `vmtouch` pre-fault (§A2).

**Net:** RAM axis decisive (1.13 GB versus Qdrant ~17 GB) **and** latency now
answered directionally — **~0.5 s warm at 150 M when provisioned to cache the
working set.** Deployment implication: provision serving RAM ≥ touched working
set (here ~40 GB), or shrink the index (§B) to make a smaller box sufficient.

**Still open (not measured here):** the §C1 `query_cut=10` overlap@10 ≥ 0.99
check at 150 M, and the paired all-terms baseline — both need the same
cache-resident host, so they are deferred behind the hardware blocker above.

#### A1 measured #3 — RAM-vs-latency sweep, the knee `[OURS]` (2026-06-30)

Stepped the **container** memory cap down (`docker update --memory`, no WSL restart;
cgroup `memory.max` forces page-cache reclaim → re-fault) and re-ran the bench
(12 q × 2 passes, SEISMIC-only) at each level. Working set for this 12-query set
≈ **25 GB** (smaller than the 40-query run's ~40 GB — the working set scales with
query diversity).

| container cap | warm p50 | VmRSS peak | state |
|---|---|---|---|
| 48 GB | 65 ms | 24.9 GB | fits |
| 42 GB | 81 ms | 25.0 GB | fits |
| 36 GB | 67 ms | 24.7 GB | fits |
| 30 GB | 70 ms | 24.5 GB | fits |
| **24 GB** | **42,355 ms** | 6.7 GB | **cliff** |
| 18 GB | — | — | stopped early (knee already clear) |

**The curve is flat-then-cliff, not a slope.** Warm p50 holds ~65–80 ms from 48
down to 30 GB (working set cached), then at **24 GB it falls off a cliff — ~650×
to 42 s** as cache (collapsed to 6.7 GB resident) drops below the ~25 GB working
set. **Deployment implication:** there is *no graceful-degradation zone* — provision
serving RAM ≥ touched working set **plus margin**; cross the knee and latency goes
from tens-of-ms to tens-of-seconds. The knee location scales with query
diversity/volume (more distinct queries → larger working set → knee at higher RAM).
Sweep data `data/eval_results/seismic_ram_sweep_20260630.tsv`; driver
`scripts/seismic_testbed/ram_sweep.sh`.

#### A1 measured #4 — corpus-size scaling: serve N of 8 shards `[OURS]` (2026-06-30)

Served N of the existing 8 shards (sub-manifests; **no rebuild, no restart** — the
cheapest scaling knob) at the 56 GB cap, 40 q × 2 passes. N shards ≈ N×18.8 M docs.

| shards | docs | warm p50 | warm traverse | warm encode | VmRSS peak | swap |
|---|---|---|---|---|---|---|
| 1 | 18.8 M | 50 ms | 14 ms | 34 ms | 5.6 GB | 0 |
| 2 | 37.6 M | 32 ms | 11 ms | 20 ms | 10.2 GB | 0 |
| 4 | 75.2 M | 48 ms | 26 ms | 21 ms | 20.3 GB | 0 |
| 8 | 150.4 M | **82 ms** | 52 ms | 29 ms | 41.9 GB | 0 |

**Latency scales flat; RAM scales linear.** Over an **8× corpus increase
(18.8 M→150 M)** warm p50 rose only **50→82 ms (~1.6×)** — the parallel federation
makes latency ≈ **slowest shard + merge**, not the sum. The SPLADE **encode
(~20–34 ms) is corpus-independent** (per-query, not per-shard); **traverse grows
sub-linearly 14→52 ms**. Working set (VmRSS) scales ~linearly, ≈ **5 GB/shard**.
**Caveat (cache-warm best case):** these warm passes ran with a hot cache (sequential
N=1,2,4,8 + the prior 58 GB bench reused the same 40 queries), so **82 ms is the
asymptotic fully-cached 150 M warm latency** — better than the 58 GB cold-start
bench's 668 ms (#2b), which warmed from a fresh post-restart cache. Takeaway:
**the engine traversal is fast (tens of ms); absolute warm latency is governed by
cache residency, not corpus size.** Data `data/eval_results/seismic_shard_scale_20260630.tsv`;
driver `scripts/seismic_testbed/shard_scale.sh`.

### A2. Pin / pre-fault the hot pages (measure warm, not fault-storm)
- **`vmtouch`** to (a) report what % of each shard is resident before a run and
  (b) `vmtouch -t` to pre-load shards into page cache so the first queries aren't
  a cold-fault storm. ([vmtouch](https://hoytech.com/vmtouch/))
- **`mlock`/`MAP_POPULATE`** in the C2 reader to keep the inverted+summary side
  (the hot, repeatedly-traversed structure) resident, letting only the larger
  forward index page in on demand. Note the G3 split `[OURS]`: at 150M scale the
  **forward index dominates (~85%)**, so mlocking *everything* won't fit — mlock
  the inverted/summary side only. ([mlock + page cache](https://biriukov.dev/docs/page-cache/4-page-cache-eviction-and-page-reclaim/))

### A3. madvise the mmap correctly for SEISMIC's access pattern
SEISMIC chases random posting/forward pointers, not a sequential scan:
- **`MADV_RANDOM`** on the forward-index mmap → tells the kernel to *stop*
  read-ahead (default read-ahead wastes IO + cache on neighbours we won't read).
- **`MADV_WILLNEED`** (advisory) or `MAP_POPULATE` to warm the inverted/summary
  region at construct time. Caveat: `WILLNEED` is advisory — kernel may ignore it
  and gives no completion signal; `MAP_POPULATE` is the harder guarantee.
  ([madvise(2)](https://man7.org/linux/man-pages/man2/madvise.2.html),
  [Rigtorp — virtual memory latency](https://rigtorp.se/virtual-memory/))
- Action: add the madvise calls in `spike/seismic_upstream/src/pylib/mmap_index.rs`
  (the C2.5 reader) and re-measure resident-% with vmtouch.

### A4. Instrument the encode-vs-traverse split (the suspect)
The ~80 s/query is currently un-attributed. The in-process SPLADE ONNX encoder
runs in the same process as SEISMIC search, so part of that wall could be the
**encoder**, not traversal. Add two timers in
`scripts/seismic_testbed/serve_footprint_bench.py` / `seismic_backend.py`:
`t_encode` (around `encode_query`) and `t_search` (around `index.search`), write
both to the result JSON per query. **Small, non-disruptive change — does not
affect a running process.** Without this split, no latency number is actionable.

> **MEASURED on the promoted served path (G8e, 2026-07-08, container).**
> `ParallelSeismicBackend(load_mode=mmap)` over the 8 dv shards via its
> `search_with_timing` hook, 40 diverse queries, top_k=50, 3 warm passes
> (`scripts/seismic_testbed/g8e_encode_traverse_split.py`,
> `data/eval_results/g8e_encode_traverse_split_20260708.json`):
> **warm p50 total 64.2 ms = encode 20.0 ms (31%) + traverse/fan-out/merge
> 43.7 ms (69%)** — the total reproduces G8b's 64.5 ms warm p50, confirming
> G8b's figure INCLUDED encode. Attribution consequence: the single-shard
> warm kernel traverse is ~3–6 ms (E1/E7b), so **most of the 43.7 ms is
> federation machinery** (thread fan-out, per-shard k'=200 result
> materialization, Python merge, GIL) — the largest addressable latency
> component, ahead of encode (~20 ms) and far ahead of the dot kernel
> (~3 ms). Cold pass (as-found cache, not drop_caches): p50 5.3 s /
> p95 23.1 s, encode share 0.7% — cold remains a fault problem, not an
> encode problem. Next split (unmeasured): per-shard traverse walls versus
> merge inside the 43.7 ms.

> **G8f attribution (2026-07-08, same day):** instrumented replica of
> `search_encoded` (per-shard walls timed inside the fan-out threads),
> n=100, top_k=50, 3 warm passes
> (`scripts/seismic_testbed/g8f_shardmerge_profile_kprime.py`,
> `data/eval_results/g8f_shardmerge_profile_kprime_20260708.json`). At the
> pre-flip k'=200: **traverse p50 38.3 ms = max-shard 10.1 ms +
> scheduling overhead 27.7 ms + merge 0.26 ms** (per-shard p50 walls
> 4.5–8.8 ms). The dominant cost is neither shard search nor merge — it is
> **`ParallelSeismicBackend._fan_out` constructing a fresh
> `ThreadPoolExecutor` per query** (8 thread spawns/teardowns each search).
> A persistent per-backend executor is the obvious next lever
> (`*est.*` −20+ ms of the ~64 ms served warm p50 — UNMEASURED, needs its
> own gate + T1 re-run). *(2026-07-08 later that day: estimate REFUTED —
> measured −2.3 ms; see the G8g note below.)* Second finding: **k' 200→100 federated gate
> PASSED at n=100** (merged overlap@10 0.999 / @50 0.994, traverse 1.47×:
> 38.3 → 26.0 ms) → **served default FLIPPED to `max(2×top_k, 100)`**
> (2026-07-08, `sharded_seismic_backend._prepare_query`), closing doc 09
> §4's open recommendation.

> **G8g — persistent executor SHIPPED; the −20 ms estimate REFUTED
> (2026-07-08, container).** `ParallelSeismicBackend` now builds its
> `ThreadPoolExecutor` once in `__init__` and reuses it every query
> (`scripts/seismic_testbed/g8g_persistent_executor_gate.py` +
> `g8g_ab_perquery_vs_persistent.py`;
> `data/eval_results/g8g_persistent_executor_gate_20260708.json`,
> `g8g_ab_perquery_vs_persistent_20260708.json`). Results, n=100, top_k=50,
> served k'=100, 3 warm passes:
> - **Identity:** served fan-out ≡ serial per-shard reference, 100/100
>   bit-identical merged top-50 (real-corpus complement to T1; the 17-test
>   sequential + served-path suites pass).
> - **Efficacy (same-process interleaved A/B — unconfounded):** per-query
>   executor traverse p50 26.4 ms → persistent 22.8 ms; **paired per-query
>   delta −2.3 ms p50**, arms bit-identical (100/100). The pre-registered
>   gate bar (sched_overhead_ms_p50 < 5) **FAILED** (10.3 ms) — the change
>   is kept anyway: strictly faster, bit-identical results, zero quality
>   risk.
> - **Attribution correction (why the −20 ms estimate was wrong):** G8f's
>   "27.7 ms scheduling overhead" was mostly NOT pool construction — it is
>   k'-dependent (19.6 ms already at k'=100 in G8f's own k100 arm) and
>   partly a measurement artifact: per-query thread spawns STAGGER the 8
>   shard searches, so each ran less contended (max-shard 6.4 ms) with the
>   stagger booked as "overhead"; the persistent pool overlaps them
>   genuinely — max-shard rises to 12.9 ms (memory-bandwidth contention)
>   while the total wall still drops. The remaining ~10 ms of
>   fanout-wall−max-shard is GIL-serialized per-shard result
>   materialization + contention, not an executor cost → **no large
>   federation-machinery lever remains**; encode (~20 ms) is now the
>   largest single addressable component of the served warm path.
> - **New served warm headline (k'-flip + persistent executor stacked):**
>   `search_with_timing` end-to-end **warm p50 53.8 ms = encode 19.5 ms
>   (36%) + traverse 33.7 ms** (p95 79.3 ms), versus G8e's 64.2 ms measured at
>   the pre-flip k'=200 default.

---

## B. Shrink the working set (latency win *via* RAM — the aligned lever)

Smaller index ⇒ more of it fits in page cache ⇒ fewer faults ⇒ lower latency,
*and* the RAM floor stays low. This is the lever that doesn't trade the pivot away.

### B1. Forward-index compression — DotVByte `[literature]`
The forward index is ~85% of our 150M on-disk size `[OURS]`, so compressing it
shrinks the dominant working set directly. The 2026 forward-index-compression
study evaluated VByte/Elias/Zeta/StreamVByte and a new **DotVByte**:
- DotVByte: **~32% size reduction at ~1.2× decode cost** (near-zero-decode,
  SIMD inner product in-register, 8 values/register). The classic codecs
  (VByte/Zeta) cut more size (~40–53%) but cost **24–32× decode** → unusable for
  our random-access mmap pattern. StreamVByte ~30% size / ~4× decode is the
  fallback. End-to-end (MS MARCO, SPLADE): uncompressed 289 µs / 5.8 GB →
  DotVByte 309 µs / 5.1 GB. ([Forward Index Compression for LSR, arXiv 2602.05445](https://arxiv.org/html/2602.05445))
- **Fit for us:** a zero-/cheap-decode codec is exactly the FORMAT-WALL constraint
  this project already proved matters (696→25.63 ms zero-decode flip,
  `sparse_engine_project` G1). DotVByte/StreamVByte preserve the mmap zero-copy
  property; Zeta/Elias break it. **Design-only — not yet in our Rust reader.**

### B2. 4-bit quantization of block/superblock max-weights `[literature]`
The superblock-efficiency paper reports **~30–35% extra memory savings** from
quantizing the per-block max term weights 8-bit→4-bit, at **negligible latency
cost and 99.8% of safe retrieval quality**. These are the summary/skip structures
(the part we'd want mlock'd in A2) — shrinking them makes A2 affordable.
([Efficiency Optimizations for Superblock-based Sparse Retrieval, arXiv 2602.02883](https://arxiv.org/html/2602.02883v1))

### B3. Lightweight flat inverted index `[literature]`
Same paper: a flat inverted index (no per-vector Rust `Vec` 24-byte overhead)
gives **6.2× memory reduction versus BMP-Inv (3.6 GB versus 19 GB)** for the inverted
side, optimal for blocks ≥96 docs. Relevant because our C2 mmap layout is already
a flat-file design — this validates the direction and gives a target.

---

## C. Algorithmic latency (faster traversal) — watch the RAM trade-off

These cut traversal work but several **add** RAM, so they're only worth it once
A (clean measurement) shows traversal — not swap/encode — is the bottleneck.

### C1. Tune `query_cut` / `heap_factor` (FREE — no rebuild) — do this first
Our backend currently uses **all 64 query terms** (`query_cut=len(tokens)`) and
`heap_factor=0.8` (`seismic_backend.py:72-89`) — deliberately recall-first while
G2 was open. SEISMIC's own MS MARCO best-configs use a **small `query_cut`** and
lower `heap_factor` for big latency wins at modest recall cost. Sweep
`query_cut ∈ {10,15,20}` × `heap_factor ∈ {0.6,0.7,0.8}` and plot latency versus
overlap@10 — pure query-time knobs, zero rebuild, zero extra RAM.
([Seismic SIGIR'24 / scalability ECIR'25, arXiv 2501.11628](https://arxiv.org/pdf/2501.11628))

> **MEASURED 2026-06-30** (commit on this date) — the §C1 sweep is done.
> Script: `scripts/seismic_testbed/g_sweep_querycut_heapfactor.py`. Results:
> `data/eval_results/seismic_sweep_c1_querycut_heapfactor_20260630.json`.
> **Index:** 100K-doc stock testbed index (`data/thin_client_poc/seismic_idx`,
> len=100000, dim=26603, nnz=11.8M), `models/splade_onnx_fp16` query encoder,
> n=60 queries from `data/eval_results/diverse_queries.json`. **overlap@10 is
> self-relative** — agreement with the recall-max baseline (all-terms, hf=0.8),
> NOT versus a live Qdrant (not running on this box, not needed for the lever
> study). Per-cell traverse is the p50 of 5 warm repeats; warm-encode is timed
> separately (the §A4/§D split). Absolute latency is swap-confounded off a
> clean host — the relative recall + the encode/traverse split are the clean
> signals.
>
> **Baseline (all-64-terms, hf=0.8):** traverse p50 **9.98 ms**, warm-encode
> **~38.6 ms**.
>
> | query_cut | heap_factor | overlap@10 (versus base) | traverse p50 (ms) | speedup |
> |-----------|------------|----------------------|-------------------|---------|
> | 10 | 0.8 | 0.9950 | 2.482 | **4.02×** |
> | 10 | 0.7 | 0.9950 | 3.149 | 3.17× |
> | 10 | 0.6 | 0.9967 | 3.924 | 2.54× |
> | 15 | 0.8 | 0.9983 | 3.577 | 2.79× |
> | 15 | 0.7 | 0.9983 | 4.443 | 2.25× |
> | 15 | 0.6 | 0.9983 | 5.307 | 1.88× |
> | 20 | 0.8 | **1.0000** | 4.577 | 2.18× |
> | 20 | 0.7 | 0.9983 | 5.587 | 1.79× |
> | 20 | 0.6 | 0.9983 | 6.719 | 1.49× |
>
> **Verdict — biggest free latency win on the SEISMIC leg, ~zero recall cost:**
> `query_cut=10, heap_factor=0.8` → **4.02× faster traversal at overlap@10
> 0.995** (0.995–0.9967 across the qc=10 row). `query_cut` is the dominant
> lever (traversal falls monotonically 20→15→10 at every heap_factor); the
0.6–0.8 `heap_factor` band is inert-to-mild within a query_cut (so ship
> 0.8 = the recall-safe end). The served path currently pays **4× the
> traversal it needs** at the all-terms default. **Caveat (scoped):** measured
> on the 100K testbed index, not 150M; the 0.995 floor is *self-relative*
> recall versus the un-pruned run (a recall-vs-baseline proxy, not a NDCG-vs-Qdrant
> verdict). Re-verify overlap@10 ≥0.99 holds at 150M before flipping the served
> default — but no rebuild is needed to do so (pure query-time knob).
>
> **Encode dominates warm wall (reinforces §D):** warm-encode is **~26–35 ms**
> versus traverse **1.7–6.7 ms** — the SPLADE ONNX fp16 encoder is the post-cache
> latency mass, not the SEISMIC fan-out. The cold model load (~78 s on this
> box) is amortized by a one-query warmup. So §D (int8 SPLADE encoder) is the
> next latency lever *after* C1 lands; C1 is the no-build change to ship first.

### C2. Dynamic superblock pruning `[literature]` — latency↑ but RAM↑
Group blocks into superblocks; reject whole superblocks by a max/avg score bound
before touching child blocks. Reported **up to 2.9× faster than BMP at 99%
recall**. **Cost: +1–2 GB index** (stores per-superblock max/avg weights) — so
only adopt if B2's 4-bit quant offsets it, else it erodes the RAM win.
([Dynamic Superblock Pruning, arXiv 2504.17045](https://arxiv.org/html/2504.17045v1))

### C3. Top-γ superblock inclusion (LSP/0) `[literature]` — latency↑ AND RAM↓
The 2026 superblock paper's headline: guarantee visiting the top-γ superblocks +
µ-prune the rest. Reports **1.8–17× faster than SP, 1.8–12× faster than BMP, 2×
faster than SeismicWave**, *and* a smaller index (fewer safeness guards), with
robust fixed parameters (γ=250–1000, β=0.33) — no per-dataset grid search. Most
attractive of the algorithmic options because it claims latency↑ *with* RAM↓, but
it's a different index structure (build-side work, not a configuration flip).
([arXiv 2602.02883](https://arxiv.org/html/2602.02883v1))

### C4. κ-NN graph augmentation `[literature]`
Adding a κ-NN (κ=10–20) graph over doc vectors keeps SEISMIC Pareto-efficient versus
HNSW at higher accuracy. Adds graph RAM — characterize before considering; lower
priority than B/C1 for our RAM-constrained case. ([arXiv 2501.11628](https://arxiv.org/pdf/2501.11628))

---

## D. Encoder-side latency (the other half of A4's split)

If A4 shows the SPLADE encoder is a big slice of per-query wall:
- **Dynamic INT8 quantization of the SPLADE ONNX encoder** — literature reports
  **1.5–3× CPU speedup** (one example 24.8 ms→6.1 ms) with negligible Recall@10
  loss; best on x86-64 with VNNI. We run `models/splade_onnx_fp16` on CPU
  in-process (served default `models/splade_onnx_fused` since 2026-07-09 D2),
  so this is a direct candidate.
  ([ONNX Runtime quantization](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html),
  [Sentence-Transformers efficiency](https://sbert.net/docs/sparse_encoder/usage/efficiency.html))
- **Caveat:** the doc vectors were built from the **fp16** encoder; re-quantizing
  the *query* encoder to int8 risks an encoder-asymmetry quality hit. Validate
  overlap@10 parity before/after — the symmetry guarantee in `seismic_backend.py`
  (raw-float query versus raw-float doc) is load-bearing for G2 attribution.

> **D1 MEASURED — dynamic int8 KILLED (2026-07-09, container).** The
> asymmetry caveat above was decisive.
> (`scripts/seismic_testbed/d1_int8_query_encoder.py`;
> `data/eval_results/d1_int8_query_encoder_20260709.json` run 1 /
> `…_20260709_0034.json` run 2.) Discovery en route: `models/splade_onnx`
> and `models/splade_onnx_fp16` are **byte-identical fp32 models** (md5
> `2c54704e…`) — the "_fp16" name is a misnomer; serving encode is fp32
> everywhere today. Two arms, dynamic int8 per-channel
> (`AutoQuantizationConfig.avx2`, host has no VNNI), gated on the SERVED
> federated merged top-k versus fp32 qvecs, n=100, dv shards, served defaults:
> - **`int8_all`** (every MatMul): encode p50 1.45–1.59× faster, but
>   **merged overlap@10 0.791** (min 0.30), top-64 qvec Jaccard 0.69 —
>   catastrophic versus the ≥0.99 bar.
> - **`int8_nohead`** (MLM vocab-projection head `/cls/predictions/*`
>   kept fp32): **overlap@10 0.798** — no rescue; the damage is in the
>   quantized transformer body, not the head.
> - **Sequential serving method covered:** `SequentialSeismicBackend`
>   (mechanisms A+B, real `release_pages`) returned merged top-50
>   **bit-identical to parallel on 100/100 queries** for BOTH fp32 and
>   int8 qvecs — the gate verdict transfers to both serving classes.
> - **Verdict: KEEP_FP32**; the quantized model directories were deleted (the
>   script regenerates them). Encoder-side revival levers, all
>   unmeasured / design only: **static (calibrated) int8** on real query
>   activations; **ORT graph-optimization fusion** (lossless, no
>   asymmetry risk — the only arm that can't hurt quality); a
>   **distilled/smaller query encoder** re-gated the same way.
>   *(Fusion measured same day — D2 below: PROMOTED.)*

> **D2 — ORT graph-fusion + session-option matrix; exact-GELU fusion
> PROMOTED (2026-07-09, container).** Full runtime-option matrix versus the
> production baseline (ORT_ENABLE_ALL, default threads, spinning on), one
> arm session co-resident at a time, interleaved per query, n=100
> (`scripts/seismic_testbed/d2_ort_fusion_matrix.py` + `d2b_fused_exact_gate.py`;
> `data/eval_results/d2_ort_fusion_matrix_20260709_0103.json`,
> `d2b_fused_exact_gate_20260709_0117.json`, `d2_served_e2e_ab_20260709_0203.json`):
> - **`fused` (offline bert fusion, exact GELU) — PROMOTED to served
>   default** `models/splade_onnx_fused` (same fp32 weights): encode
>   **1.11× p50**, merged **overlap@10 0.999 / @50 1.0**, sequential ≡
>   parallel bit-identical 100/100. Paired served e2e (same-process A/B,
>   encode + traverse): **total −5.6 ms p50** (encode leg −3.6 ms is the
>   defensible part; the traverse share of the delta may include
>   fixed-order warm bias). Regenerate the directory with the D2 script;
>   `SFU_SPLADE_MODEL_PATH` overrides (`models/splade_onnx` = unfused
>   fallback).
> - **`fused_gelu` (FastGelu approximation): passed the bar with ZERO margin —
>   NOT promoted.** 1.14× but overlap@10 mean exactly 0.990 (min 0.90),
>   0/100 qvecs exact; ~0.5 ms extra win doesn't justify grazing the
>   quality floor. Directory deleted.
> - **Thread pinning REFUTED:** intra_op 8/4/2/1 → 0.86×/0.80×/0.64×/0.40×
>   (the default 16-core configuration wins at batch-1); **spinning-off REFUTED:**
>   0.65× single-stream. All qvec-exact 100/100 (thread count doesn't
>   change numerics here) but strictly slower.
> - Not tested, by design: graph_opt_level < ALL (baseline already ALL),
>   `optimized_model_filepath` (init-time, not per-query), fp16/bf16 CPU
>   (no native fp16 on avx2), batching/IOBinding (serving is batch-1).
> - Methodology note (binding for future encoder work): absolute
>   latencies on this container drift run-to-run (a single-arm e2e re-run
>   moved the traverse leg +7 ms with no encoder involvement —
>   `d2_served_e2e_20260709_0140.json`, superseded); **only same-process
>   interleaved A/Bs are promotable evidence.**

---

## Prioritized next steps (for our G5/G8 work)

> **Reconciled 2026-09-25** — 6 items: 5 DONE, 0 CLOSED, 1 SUPERSEDED, 0 STILL OPEN.
> No item in this list is pending work. Per-item evidence tags are appended below;
> the list text itself is unchanged.

1. **A4 — encode-vs-traverse split instrumentation.** Tiny, non-disruptive, makes
   every later number actionable. Do now (does not touch the running bench).
   — **DONE 2026-07-08 (§A4 "MEASURED on the promoted served path (G8e)" above;
   `scripts/seismic_testbed/g8e_encode_traverse_split.py`,
   `data/eval_results/g8e_encode_traverse_split_20260708.json`; commit `75aa2b1f`)** —
   warm p50 64.2 ms = encode 20.0 ms (31%) + traverse/fan-out/merge 43.7 ms (69%),
   of which the single-shard kernel is only ~3–6 ms.
2. **A1 — DONE 2026-06-30 (see "A1 measured" #1 + #2).** Swap confound solved
   (Qdrant stopped); RAM-starvation question answered by raising the WSL cap
   32→56 GB → **warm p50 18.1 s → 0.55 s (33×)**, proving the engine is fast at
   150 M and the prior latency was page-cache starvation. Remaining polish (not
   blocking): a *perfectly* zero-swap verdict wants a ≥72 GB host or `vmtouch`
   pre-fault (§A2); **the strategic win is §B index shrink** so a smaller box
   caches the whole working set.
   — **DONE 2026-06-30 (§A1 measured #1 + #2)**; the residual "≥72 GB host or
   `vmtouch` pre-fault" polish is **CLOSED-UNRUNNABLE 2026-09-25** — no cloud hosts
   remain (OCI E5 and every DigitalOcean droplet are gone) and the only surviving
   machine is the 31 GB local WSL2 host (`docs/infrastructure/README.md` banner).
3. **C1 — `query_cut`/`heap_factor` sweep.** Free, no rebuild, likely the biggest
   single latency lever; record latency-vs-overlap@10 Pareto. **✅ DONE 2026-06-30**
   — measured above (4.02× faster traversal at overlap@10 0.995; `query_cut=10`
   is the dominant lever). Ship C1 before B/D.
   — **DONE 2026-06-30 (commit `d27bb3ed`,
   `data/eval_results/seismic_sweep_c1_querycut_heapfactor_20260630.json`)**, and
   re-measured at full corpus in the G8c warm matrix 2026-07-05
   (`data/eval_results/g8c_{dv,f16}_warm_kp200_qc10_hf08_20260705.json`).
4. **B1 + B2 — DotVByte forward-index + 4-bit summary quant** in the C2 reader.
   Shrinks the dominant working set → fewer faults → lower latency *and* keeps the
   RAM floor (the pivot's whole point). Build-side work.
   — **DONE 2026-07-04 for B1 (dotvbyte forward index shipped E7 2026-07-03,
   PROMOTED E7b, all 8 shards converted E7c 2026-07-04, E8 dv-v2 served default
   since 2026-07-14 — `10_FORWARD_COMPRESSION_DESIGN.md` §7.5/§7.6,
   `THIN_CLIENT_SWAP.md` §SPLADE leg); B2 (4-bit summary quant) SUPERSEDED
   2026-08-10 — never built, and the math-candidate book M1–M10 is now fully
   decided (`math_optimization/08_FURTHER_MATH_CANDIDATES.md` §M8: "every
   candidate measured, killed, or dead-parked"); the byte mass is the forward
   index (85%, doc 09), not the summaries.**
5. **C3 (LSP/0) / C2 (dynamic superblock)** — only if A shows traversal is the
   real bottleneck; prefer C3 (claims latency↑ + RAM↓) over C2 (RAM↑).
   — **SUPERSEDED 2026-07-08 (G8e, `g8e_encode_traverse_split_20260708.json`)** —
   the stated precondition failed: traversal is not the bottleneck (single-shard
   kernel ~3–6 ms of a 64.2 ms warm p50; ~35 ms is federation machinery), so the
   conditional never fired. Neither C2 nor C3 was ever implemented, and the
   math-candidate book closed 2026-08-10 (`math_optimization/08` §M8).
6. **D — int8 SPLADE encoder** only if A4 shows the encoder dominates; gate on
   overlap@10 parity.
   — **DONE 2026-07-10 (measured KILL; `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` Q11,
   `data/eval_results/q11_c5_static_int8_20260710_*.json`)** — C5 static-int8
   merged overlap@10 **0.006** and 5.5× SLOWER; with D1's 0.79 the int8 encoder
   family is dead end-to-end. The whole encoder book was CLOSED 2026-07-28 after
   the C4 distillation KILL (`14_ENCODER_UPGRADE_PATH.md` §6); the served fused
   fp32 encoder stays.

> Reminder (CLAUDE.md efficacy rule): none of B/C/D is "done" until *we* measure it
> on *our* index and record before→after numbers + eval script + result file here.
> The figures above are external and only justify which technique to try first.

---

## E. RAM-compression lever (owned-anon load + memory compression) — WIRED, UNMEASURED

**Added 2026-07-01 (commit `219c7e1`).** Status: **EFFICACY UNMEASURED** — the
harness is wired and regression-tested; the measurement is the operator's
Windows-host G8 run (where memory compression is default-on). This is a G8
**RAM-residency** lever, NOT a storage lever: the constraint is how much of the
~62 GB mmap working set stays resident on a host whose RAM < index size, not
the on-disk footprint.

### Why file compression was ruled out (set aside, not tracked here)
- **Whole-file zstd** breaks mmap (forces full-shard owned-anon load →
  re-introduces the Path-A floor G3 killed). [design]
- **Transparent FS compression** (`chattr +c` / NTFS) leaves the *decompressed
  resident set* unchanged on fault + adds per-fault CPU → doesn't touch the
  actual constraint. [design]

### The candidate: owned-anon load + a compressed-RAM regime
Load the index **owned-anonymous** (Path A, `SFU_SEISMIC_LOAD_MODE=stock`)
instead of file-backed mmap, with **memory compression enabled** (zram/zswap on
Linux; Windows memory compression, default-on). Anonymous pages under a
compressed-RAM regime get compressed **in RAM** (~2–3×, decompress at multiple
GB/s) instead of paged out — potentially converting the ~15 s **disk re-fault**
(file-backed pages dropped from page cache, re-read from the vhdx) into a
~µs **CPU decompress**. Crucial asymmetry: an owned-anon page compressed to
zram/zswap *stays in RAM* (just smaller); a file-backed page, once evicted,
*must re-fault from disk*. So compression only helps the **owned-anon** cell,
not the file-backed mmap cell. [design — the asymmetry is the mechanism; the
~2–3× ratio + GB/s decompress are external figures, not measured on our index]

### The 2×2 matrix (one bench invocation per cell)

|              | mem-compression OFF | mem-compression ON |
|--------------|---------------------|--------------------|
| `load_mode=mmap` (Path C) | the 15.8 s disk-re-fault baseline (measured, §A1 #1) | moot — file pages don't compress; expected ≈ baseline |
| `load_mode=stock` (Path A) | OOMs / swaps to disk swap at 150 M (the floor G3 killed) | **the candidate win** — anon compressed in RAM |

### ✅ Harness wiring (shipped, efficacy unmeasured)
- **`detect_memcompression()`** (`scripts/seismic_testbed/serve_footprint_bench.py`)
  resolves the host's anon regime (`zram`/`zswap`/`windows_compression`/
  `disk_swap`/`off`/`unknown`) from `/proc`, honoring an operator
  **`SFU_MEMCOMPRESSION_REGIME`** override for the Windows case `/proc` can't
  see; recorded in result `meta.g8_matrix_cell`.
- **`_latency_caveat()` verdict gate is regime-aware — the load-bearing fix.**
  Under zram/zswap/windows_compression, `VmSwap>0` is compressed-in-RAM (a
  VERDICT, decompress at GB/s), NOT the disk-re-fault the old gate flagged.
  Without this fix the stock+zram cell would be mislabeled "not a verdict".
  The 'mmap exceeds page cache' (warm>=cold) symptom is gated on
  `load_mode=='mmap'` (owned-anon has no file-backed page cache to exceed).
- **Tests:** `scripts/tests/test_serve_footprint_g8_matrix.py` (14 unit tests
  pinning the gate across all cells).

### Invocation (the cells to run on the Windows host)
```bash
# (mmap, off) — disk-re-fault baseline:
SFU_SEISMIC_LOAD_MODE=mmap .venv/bin/python3 scripts/seismic_testbed/serve_footprint_bench.py \
    --shard-manifest data/eval_results/seismic_c25_shards_150m_mmap.json --queries 40 --passes 2 \
    --result-file data/eval_results/seismic_g8_cell_mmap_off_<date>.json
# (stock, windows_compression) — THE candidate win:
SFU_SEISMIC_LOAD_MODE=stock SFU_MEMCOMPRESSION_REGIME=windows_compression \
    .venv/bin/python3 scripts/seismic_testbed/serve_footprint_bench.py \
    --shard-manifest data/eval_results/seismic_c25_shards_150m_mmap.json --queries 40 --passes 2 \
    --result-file data/eval_results/seismic_g8_cell_stock_wincomp_<date>.json
```

### Decision rule
- **stock+compression cell** → warm p50 in a usable band AND `VmSwap>0` flagged
  **compressed-in-RAM verdict** ⇒ G8-latency clears **without a bigger box**;
  G9 weighs Path-C build cost versus this (cheaper) Path-A-with-compression win.
- stock cell still re-faults (warm≈cold) AND `VmSwap` reads as disk (regime
  not compressed) ⇒ memory compression isn't enough; Tier 2 #5 (no-swap host /
  pre-fault+mlock) or a bigger box remains the only resolution.

### Bigger-lift note (→ G9 / Path C, not this spike)
A succinct / Elias-Fano compressed index format (§B1 DotVByte / §B2 4-bit
summary quant) genuinely shrinks the resident set and is queryable-while-
compressed, but needs a SEISMIC build+traversal fork — not a configuration knob.
Design-only; not in our Rust reader.

