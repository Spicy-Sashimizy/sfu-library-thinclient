# Findings: Qdrant vs Lucene/OpenSearch for the SPLADE sparse leg

> **CLOSED SUPERSEDED 2026-07-06** — the "should we swap off Qdrant back to Lucene?" question was answered instead by promoting SEISMIC federated mmap (`docs/SEISMIC_ARCHIVE_SPLIT.md`). The RAM analysis and OOM findings remain the recorded evidence base for that move. Not current; do not resume.

**Status:** CLOSED SUPERSEDED 2026-07-06

**Date:** 2026-06-25 · **Method:** live container probe + git history + canonical
docs. All numbers MEASURED unless marked `est.`

---

## 0. Access status — OpenSearch IS online, but EMPTY (no 150M corpus)

The request asked for **direct information from the `sfu-library-mcp-training`
container**. Reaching it took some work — the Docker socket is absent here
(`/var/run/docker.sock` → "no such file or directory") and the
`claudebox-sfu-library-mcp-training-opensearch` DNS name does **not** resolve from
this container. OpenSearch is actually reachable on the shared docker network at
**`http://172.20.0.1:9200`** (the gateway, where the host publishes 9200).

**Live probe 2026-06-25 — OpenSearch is ONLINE and GREEN:**

| Signal | Value |
|---|---|
| Distribution / version | **OpenSearch 3.7.0**, **Lucene 10.4.0** |
| Cluster status | **green**, 1 node, 3/3 active shards, 100% allocated |
| Node uptime | ~30 min (freshly started) |
| JVM heap (live) | **0.98 GB used / 2.00 GB max** (`-Xmx2g`) |
| OS mem | 18.2 GB used / 31.3 GB total; heap 50%, ram 58% |

**BUT — the 150M corpus is not loaded, BY DESIGN.** The only indices present are
system / plugin ones (`.opensearch-sap-log-types-config`, `top_queries-*`,
`.plugins-ml-config`); **`openalex_works` does not exist** on this endpoint
(404, confirmed with hidden + alias expansion). **This is intentional — the
operator archived the 150M index** (confirmed 2026-06-25), so the cluster is a
running-but-empty OpenSearch 3.7, not a broken one. The 3.x upgrade itself is
clearly done (Lucene 10.4.0), matching `docs/deprecated/OPENSEARCH3_UPGRADE.md`.
Re-running any *live* 150M OpenSearch comparison would first require
**restoring the index from that archive**.

**Consequence for this assessment:** the 150M OpenSearch numbers below come from
the **recorded eval baseline** captured when the corpus *was* loaded, not a fresh
query (because the index is absent live):

- `data/eval_results/parity_record_os_20260618_0028.json` — the 150M OpenSearch
  RRF record used for every tc-vs-OS comparison.
- JVM heap is **confirmed live** at `-Xmx2g` (matches the doc's `-Xms2g -Xmx2g`);
  index footprint **274 GB raw → 141.3 GB** lossless `combined2` is from the docs.

The Qdrant numbers, by contrast, are a **live probe of the running 150M
collection** taken 2026-06-25 (see §1). To get fresh 150M OpenSearch numbers, the
`openalex_works` index must first be restored/re-ingested into this cluster.

---

## 1. Live Qdrant state, probed 2026-06-25

Process `qdrant` (pid 112), serving `data/qdrant_spike/storage`, on the 31 GB /
16 GB-swap dev host:

| Signal | Value | Meaning |
|---|---|---|
| Collections | `splade_150m`, `splade_par30` | 150M prod + 30M demo/validation tiers both live |
| `splade_150m` points | **150,413,098** (`indexed_vectors 150,412,961`) | full corpus, fully indexed |
| `optimizer_status` | **`ok`** | the optimizer-OOM fix is holding |
| `segments_count` | **36** (stable) | was thrashing 38→36 before the fix |
| `max_optimization_threads` | **1** | the persisted OOM-fix PATCH |
| `max_segment_size` | **5,000,000** (KB) | the persisted OOM-fix PATCH |
| **RssAnon** | **6.55 GB** | structural per-point bookkeeping (≈43 B/point) — non-reclaimable |
| RssFile | 1.5 GB | mmap'd posting-list page cache — reclaimable, grows under load |
| **VmSwap** | **0 kB** | not thrashing right now (at rest, idle) |

The two PATCH values (`max_optimization_threads=1`, `max_segment_size=5_000_000`)
are exactly the persisted optimizer-OOM fix from 2026-06-21, confirming it
**survived the crash + restart** and is the live config.

---

## 2. Q: Were the past Qdrant OOMs ever fixed?

**Yes at the operational layer; structural at the host layer.** There were two
distinct OOMs — don't conflate them:

### 2a. Optimizer OOM — FIXED (config, persisted, verified live)
- **Symptom:** `optimizer_status.error = "Failed to flush mmap … gridstore: Out
  of memory (os error 12)"`, recurring 2026-06-19→21. Also the **root cause of
  the ingest stalls** (an optimizer OOM drives the server `red`, which blocks the
  `wait=True` upserts → workers die).
- **Cause:** 205 GB collection in 36 segments × ~5.4 GB; merging two 5.4 GB
  segments needs >10 GB to flush, but the box had 23 GB RAM + 16 GB swap already
  full, and `swapon` of a new swapfile is blocked in-container.
- **Fix (no infra change):** `PATCH /collections/splade_150m` →
  `max_optimization_threads=1` + `max_segment_size=5_000_000` (KB, just under the
  5.4 GB segments so they count as "full" and the optimizer stops attempting the
  OOM-prone giant merges). **Result: zero OOM since the PATCH; verified live
  2026-06-25** (`optimizer_status: ok`, 36 stable segments). Data was durable and
  vectors fully indexed throughout — search never broke.
  *(Source: `THIN_CLIENT_SWAP.md` lines 457–471.)*

### 2b. Server OOM crash (kernel OOM-killer SIGKILL) — MITIGATED, not "fixed"
- **Symptom (2026-06-21):** Qdrant killed by the kernel with no panic line
  (external SIGKILL) on a chronically memory-starved box.
- **Cause is STRUCTURAL:** `on_disk: true` offloads only the posting *lists* to
  mmap; the per-point bookkeeping (id/version trackers, soft-delete bitsets,
  sparse-index offsets) stays in **anonymous RAM and scales ~linearly with point
  count** — measured **6.55 GB RssAnon at rest** (≈43 B/point × 150.4M), climbing
  to ~17 GB under query load. Config **cannot** remove it; only fewer points /
  more RAM / sharding can. *(Source: `THIN_CLIENT_SWAP.md` lines 487–499.)*
- **Mitigation:** `scripts/archive/qdrant-serve.supervisor.conf` (serve-only,
  `autorestart=true`) so a crash auto-recovers; `SFU_LOAD_MEM_FLOOR_GB` preflight
  guard; the upsert retry-with-backoff (`_upsert_wait_retry`, commit ceb363f) so
  a `red` stall self-heals instead of killing a worker.
- **What is NOT fixed:** the 205 GB-index-vs-23 GB-RAM ceiling. On the dev host
  that means **p50 545–861 ms / p95 3.4–4.5 s** at 150M (RAM-bound), vs **p50
  ~66 ms** at 30M (fits). That gap is closed only by **right-sizing the host**
  (`docs/archive/bmp_decommission_plan/DO_SIZING.md`: 64–128 GB for full-150M), not a
  flag. **This is the single most important fact in this whole assessment.**

**Bottom line:** the OOMs you kept hitting were a *symptom of running a 205 GB
index on a 23 GB box*. The bug-class ones (optimizer merge, ingest stalls) are
fixed and verified stable; the remaining "OOM" is just an undersized host and is
not a Qdrant defect to fix in code.

---

## 3. Q: The Qdrant-vs-Lucene RAM comparison (active + passive)

Full table in `QDRANT_VS_LUCENE_RAM.md`. The one-paragraph version:

- **Lucene/OpenSearch** serves SPLADE as impact-quantized `rank_features`
  postings, **mmap'd via `MMapDirectory` (page-cache resident, reclaimable)**,
  under a **bounded 2 GB JVM heap**. It *never* makes the whole sparse index
  resident — cold postings stay on disk and the OS reclaims them under pressure.
  Passive floor: ~2 GB heap + reclaimable page cache. *(THIN_CLIENT_SWAP.md
  322–330.)*
- **Qdrant `on_disk` sparse** *also* mmaps the posting lists (RssFile,
  reclaimable) — **but** adds a **structural anonymous-RAM floor that scales with
  point count** (~43 B/point → **6.55 GB at 150M**, non-reclaimable). That anon
  floor is the axis on which Qdrant is strictly worse than Lucene at scale.
- **The crux:** Lucene's resident RAM is *bounded and reclaimable*; Qdrant's anon
  RAM is *unbounded in point-count and non-reclaimable*. At the 150M tier on a
  small host this is exactly why Qdrant is RAM-bound and Lucene was not. The doc
  states this plainly: *"at 150M the BMP sparse leg is a RAM regression vs the
  OpenSearch leg it replaced — on the one axis OpenSearch handled well"*
  (THIN_CLIENT_SWAP.md 326–330). The same logic applies to Qdrant's anon floor.

---

## 4. Q: Would swapping OFF Qdrant (to OpenSearch/Lucene) provide benefits?

**It depends entirely on the deployment tier. There is no single yes/no.**

### The quality picture (engine choice does NOT improve ranking — measured)
On the same 40 LLM-judged queries at 150M, RRF NDCG@10:

| Stack | NDCG@10 (34-common) | vs OpenSearch |
|---|---|---|
| thin-client, BMP SPLADE | 0.561 (wins 29/34) | **+0.112** |
| thin-client, **Qdrant** SPLADE | 0.560 (wins 29/34) | **+0.111** |
| OpenSearch 150M | 0.449 | — |

*(Source: `BENCHMARK_METHODOLOGY.md`, `bmp_decommission_plan/VALIDATION_REPORT.md`
B2.)* So **swapping to OpenSearch would measurably LOSE ~0.11 NDCG@10** at the
system level. (The gap is from analyzer/config differences, not engine math — the
research is explicit that BM25/SPLADE quality is engine-portable, `THIN_CLIENT_
STACK_RESEARCH.md` 211–214 — but as configured, this stack wins.) Qdrant and BMP
are RRF-indistinguishable (|Δ| < 0.001), so the BMP→Qdrant swap was quality-neutral
and the swap to Qdrant cost nothing on quality.

### Benefit Qdrant gives that you'd LOSE by leaving it
- **No JVM, no cluster machinery.** This is the entire reason the project left
  OpenSearch for the laptop/thin-client tier. tantivy BM25F idles at **45 MB RSS
  vs a 2 GB JVM heap** (THIN_CLIENT_STACK_RESEARCH.md 30). Qdrant runs as one
  local binary. OpenSearch reintroduces the multi-GB JVM floor + node machinery —
  disqualifying on consumer hardware.
- **Higher measured quality** (above).
- **Exact sparse search** (posting-list dot product) ≥ BMP's approximate WAND.

### Benefit you'd GAIN by going to OpenSearch/Lucene
- **The sparse-RAM-at-scale property** (the thing that's been biting you): bounded
  heap + mmap postings + **no per-point anon floor**. A 150M sparse index serves
  on commodity RAM the way BM25F already does, because cold postings never have to
  be resident. This is genuinely better than Qdrant's anon floor at 150M.
- It is also why the original engine survey's **recommendation #1 was "Server
  tier: stay on OpenSearch, upgrade to 3.x"** — for the *full-150M server*, never
  the laptop tier (`THIN_CLIENT_STACK_RESEARCH.md` 226–231).

### Verdict by tier
| Tier | Best sparse engine | Why |
|---|---|---|
| **Laptop / thin-client (~15M)** | **Qdrant (keep)** | no-JVM, fits RAM, higher quality; OpenSearch's JVM floor is disqualifying |
| **Demo (30M)** | **Qdrant (keep)** | measured p50 ~66 ms, 1.44 GB resident on a 32 GB droplet — already fine |
| **Full-150M server** | **Either — but size the host.** Qdrant on 64–128 GB, OR OpenSearch 3.x | Qdrant's anon floor + RAM-bound latency is a *host-sizing* problem, not an engine defect. OpenSearch is the lower-RAM option at this tier but costs −0.11 NDCG@10 and the JVM. |

**So: swapping off Qdrant buys you nothing the 30M/laptop tiers need, and at the
150M tier it trades quality + the no-JVM property for better sparse-RAM scaling —
a trade only worth making if you commit to the OpenSearch *server* path AND can't
get a 64–128 GB Qdrant box.** The cheaper move is to size the host to Qdrant.

---

## 5. Q: Is "streamline OpenSearch to reach tantivy performance (even with the JVM
heap)" a better development path?

Two corrections first, then the answer:

1. **tantivy is the BM25F leg, not the sparse leg.** The RAM/latency pain you've
   been hitting at 150M is the **SPLADE/sparse** leg (Qdrant anon RAM). tantivy
   BM25F already mmaps at ~0 resident and was *never* the problem. So "reach
   tantivy performance" conflates two legs.
2. **The "tantivy 2× faster than Lucene" headline is heavily caveated** —
   single-field, ~5M docs, page-cache-resident (jpountz's analysis,
   `THIN_CLIENT_STACK_RESEARCH.md` 218–220). OpenSearch BM25 can be tuned *close*
   on latency (measured 19.7 ms vs tantivy 4.4 ms on 100k, HTTP transport
   included) but **never matches tantivy's RAM floor** — the JVM is a structural
   tax (209 MB index + 2 GB heap vs tantivy's 65 MB + 45 MB RSS,
   `THIN_CLIENT_STACK_RESEARCH.md` 26–35).

**Answer:** Yes, "streamline/upgrade OpenSearch" is a *legitimate path — but only
for the full-150M SERVER tier, and the lever is the SPARSE leg, not BM25.** The
research already identifies the concrete moves and they're cheap:

- **OpenSearch neural-sparse two-phase** (2.15+): ~up to 9.8× SPLADE speedup,
  <0.04% relevance loss, usable on the *existing* `rank_features` field with **zero
  migration** (`THIN_CLIENT_STACK_RESEARCH.md` 222–224, 238–240). This is
  explicitly called the "cheapest high-information experiment."
- **OpenSearch 3.x upgrade** (`deprecated/OPENSEARCH3_UPGRADE.md`): derived source
  for vectors, disk-based binary quantization (matches the validated 32× recipe),
  Lucene 10, the Seismic k-NN path (PoC: P50 17.5×, recall 99.7→92.4%).

What "streamlining OpenSearch" does **not** do: make it viable on a laptop. The
JVM floor is unfixable there — that's the whole reason for the thin-client. So
this path is **complementary to Qdrant, not a replacement for it**: OpenSearch 3.x
for the server, Qdrant/thin-client for the laptop/demo. That is exactly the
two-tier conclusion the original survey reached (recs #1 and #2).

**Note:** working around the JVM heap to "get the needed performance metrics" is
viable for the *server* tier (a 2 GB heap is fine when off-heap page cache does the
work) but is precisely what you *cannot* do on consumer hardware — there the JVM
floor + cluster machinery is the metric you're trying to escape.

---

## 6. Q: Plan to benchmark Qdrant at 150M (it "hasn't been fully benchmarked")

**Status correction:** Qdrant *has* been benchmarked at 150M — B1 parity, B2 RRF
quality, B3 ops envelope are all GREEN as of 2026-06-25
(`bmp_decommission_plan/VALIDATION_REPORT.md`). What is **missing** is a
benchmark on a **correctly-sized host** — every existing 150M Qdrant number is
**RAM-bound on the 24 GB dev box** (p50 545–861 ms), which tells you about the
host, not the engine. The genuinely-owed benchmark is the **non-RAM-bound 150M run
on 64–128 GB**, plus a **matched-hardware head-to-head vs OpenSearch**.

The full runnable plan is in **`QDRANT_150M_BENCHMARK_PLAN.md`**. Headline:

1. **Provision a 64 GB and a 128 GB box** (DO_SIZING.md tiers); snapshot-restore
   `splade_150m` (no re-ingest).
2. **Latency vs RAM curve:** `scripts/archive/spike_qdrant_sparse.py measure` (40 queries,
   Qdrant-search-only) at 24 / 64 / 128 GB → show where p50 crosses back under
   ~100 ms as page-cache fraction of the 205 GB index rises.
3. **Matched head-to-head vs OpenSearch** on the same box class:
   `eval_thinclient_parity.py record-tc` (Qdrant backend) + `record-os` +
   `compare` — the first apples-to-apples *latency* comparison (all prior ones
   warned "latency NOT comparable, different hardware").
4. **Ingest-resilience replay** under seeded `status=red` to measure the
   `_upsert_wait_retry` backoff (currently IMPLEMENTED, UNMEASURED).
5. **Stress/soak:** concurrent query load (the existing `measure` is
   single-threaded) to find the real OOM ceiling per host size.

---

## 7. Source index

- Live probe: `curl localhost:6333/collections/splade_150m`, `/proc/112/status`,
  2026-06-25.
- `docs/THIN_CLIENT_SWAP.md` — architecture, OOM incidents, off-BMP migration.
- `docs/STORAGE_BUDGET_150M.md` — serving-RAM box, on-disk footprints.
- `docs/THIN_CLIENT_STACK_RESEARCH.md` — per-engine survey + OpenSearch verdicts.
- `docs/archive/bmp_decommission_plan/{VALIDATION_REPORT,DO_SIZING,METRICS_CATALOG}.md` —
  gates, host sizing, metric ledger.
- `docs/BENCHMARK_METHODOLOGY.md` — LLM-judge method + 150M parity numbers.
- `data/eval_results/`: `quant_fidelity_live_150m_20260624_2345.json`,
  `thinclient_parity_qdrant_20260625_0001.json`, `parity_record_os_20260618_0028.json`,
  `measure_150m_postfix.log`, `measure_par30_warm.log`.
</content>
