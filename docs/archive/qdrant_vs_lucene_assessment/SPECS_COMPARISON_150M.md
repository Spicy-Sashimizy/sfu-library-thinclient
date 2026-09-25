# Full 150M Specs Comparison — Thin-client vs OpenSearch

> **CLOSED SUPERSEDED 2026-07-06** — the "should we swap off Qdrant back to Lucene?" question was answered instead by promoting SEISMIC federated mmap (`docs/SEISMIC_ARCHIVE_SPLIT.md`). The RAM analysis and OOM findings remain the recorded evidence base for that move. Not current; do not resume.

**Status:** CLOSED SUPERSEDED 2026-07-06

**Date:** 2026-06-25 · All numbers MEASURED unless marked *est.* Sources cited per
row. See `FINDINGS.md` for interpretation and `QDRANT_VS_LUCENE_RAM.md` for the RAM
deep-dive.

## The two stacks

| | **Stack A — Thin-client (current default)** | **Stack B — OpenSearch (legacy baseline)** |
|---|---|---|
| BM25F leg | tantivy 0.26 (mmap) | Lucene BM25 `multi_match most_fields` |
| SPLADE leg | **Qdrant `on_disk` sparse** (f32, exact dot product) | Lucene `rank_features` (8-bit impacts, mmap) |
| Dense leg | usearch b1 Hamming + int8 rescore (mmap) | Lucene k-NN HNSW |
| Fusion | Python RRF k=60 | Python RRF k=60 (same code) |
| Runtime | 3 engines, **no JVM**; Qdrant = 1 binary | single Lucene index, **JVM heap `-Xmx2g`** |

> **⚠ Two caveats that govern this whole table.** (1) **Latency is NOT
> hardware-matched** — Stack A's 150M numbers are RAM-bound on the 24 GB dev host;
> Stack B ran on its own cluster. (2) Stack B's 150M index is **archived** (operator
> confirmed 2026-06-25), so its numbers are the **recorded baseline**, not a live
> query. Only the JVM heap + version were re-probed live. A fair latency head-to-head
> requires restoring the index on matched hardware — that's Phase 2 of
> `QDRANT_150M_BENCHMARK_PLAN.md`.

---

## 1. Quality — LLM-judged, 40 queries, RRF k=60 (the decisive axis)

| Metric | Thin-client (Qdrant) | Thin-client (BMP) | OpenSearch 150M | Winner |
|---|---|---|---|---|
| **RRF NDCG@10** (34-common subset) | **0.560** | 0.561 | 0.449 | **Thin-client +0.111** |
| RRF NDCG@10 (judged headline) | 0.5378 | 0.5368 | 0.4487 | Thin-client |
| Per-query wins (34-common) | **29 / 34** | 29 / 34 | 5 / 34 | **Thin-client 85%** |
| SPLADE leg NDCG@10 (isolated, judged-cov.) | 0.6039 (Qdrant f32) | 0.6039 (BMP quant) | — | tie (Qdrant=BMP exactly) |

Per-leg overlap@50 vs the OpenSearch baseline (agreement, not quality — engines
differ): bm25f **0.532**, splade **0.395**, rrf **0.475**.

*Source: `BENCHMARK_METHODOLOGY.md`, `bmp_decommission_plan/VALIDATION_REPORT.md`,
`PRESENTATION_METRICS.md`; files `thinclient_parity_qdrant_20260625_0001.json`,
`parity_record_os_20260618_0028.json`, `quant_fidelity_live_150m_20260624_2345.json`.*

**→ Thin-client wins quality decisively (+0.111 NDCG@10, 29/34). Qdrant and BMP are
RRF-indistinguishable (|Δ|<0.001).**

---

## 2. RAM @150M (the axis where OpenSearch wins)

| | Thin-client (Qdrant SPLADE) | OpenSearch (Lucene) |
|---|---|---|
| Non-reclaimable floor | **RssAnon 6.55 GB** (~43 B/point, scales with corpus) | **JVM heap, flat `-Xmx2g`** (live: 0.98/2.0 GB; corpus-independent) |
| Other legs resident | tantivy + meta + dense mmap ≈ **0 resident** | in-heap/off-heap, bounded |
| At-rest total RSS | ~8 GB (6.55 anon + 1.5 file) | ~2 GB heap + reclaimable page cache |
| Under query load | climbs to **~17 GB** (page-cache warming 205 GB) | heap ≤ 2 GB; page cache reclaimable |
| OOM behaviour | kernel OOM-kill if anon+cache+swap exhaust (mitigated: serve-only supervisor autorestart; optimizer-OOM fixed) | heap-bounded; sparse index size never forces OOM |
| Scaling law | **floor RISES with point count** | **floor FLAT** |

*Source: live `/proc/112/status` + `_nodes/stats` 2026-06-25;
`THIN_CLIENT_SWAP.md` 322–330/487–499; `DO_SIZING.md`.*

**→ OpenSearch wins RAM at scale: bounded heap + reclaimable page cache, no per-point
floor. This is the single axis the swap-off question hinges on.**

---

## 3. Latency @150M (NOT hardware-matched — read the caveat)

| | Thin-client Qdrant SPLADE (24 GB host, RAM-bound) | Thin-client @30M (fitting-tier) | OpenSearch 150M |
|---|---|---|---|
| p50 | **545–861 ms** | **66.5 ms** | not captured as comparable ms* |
| p95 | **3.4–4.5 s** | 86.0 ms | — |
| Resident under load | ~17 GB | 5.3 GB | bounded heap |

\* The recorded OS baseline stored ids/quality, not clean per-query latency; docs
mark OS-vs-tc latency "NOT comparable, different hardware." The only apples-to-apples
latency datapoint is the 100k POC: OS BM25 **19.7 ms** vs tantivy **4.4 ms/q** (HTTP
transport included) — lexical leg only, not 150M.

*Source: `measure_150m_postfix.log`, `measure_par30_warm.log`,
`THIN_CLIENT_STACK_RESEARCH.md` POC table.*

**→ Thin-client's 150M latency is a host-sizing artifact (205 GB index / 23 GB RAM),
not an engine verdict. At a fitting tier (30M, or 150M on 64–128 GB) it's ~66 ms.**

---

## 4. On-disk footprint @150M (Qdrant is the LARGEST sparse store)

| Component | Thin-client | OpenSearch |
|---|---|---|
| BM25F (tantivy / Lucene) | ~44.8 GB | — (in combined index) |
| **SPLADE sparse** | **Qdrant on_disk 205 GB** | — (in combined index) |
| Abstract sidecar | 52.9 GB (externalized, zstd-19 dicts) | (stored fields in index) |
| meta.sqlite | 24.9 GB (as-built) | (in index) |
| Dense | 0.36 GB (600k partial) / ~26 GB *est.* full | (in combined index) |
| **Total** | **≈ 328 GB** (sparse-dominated) | **141.3 GB lossless** (`combined2`) / 274 GB raw |

Reference points: with the **old BMP** sparse leg the thin-client was 300.9 GB
all-levers → 188.8 GB after levers (closer to OpenSearch). **Swapping BMP→Qdrant
traded disk for serveability**: Qdrant on_disk (205 GB) is ~3× BMP's 68.6 GB on disk,
but it pages from disk (vs BMP's 211 GB RAM load), which is the whole point.

*Source: `STORAGE_BUDGET_150M.md` §1, `PRESENTATION_METRICS.md` §3,
`deprecated/OPENSEARCH3_UPGRADE.md` (274 GB), `LEXICAL_STORAGE_RESEARCH.md` (141.3 GB).*

**→ OpenSearch wins disk (~2.3× smaller): Lucene FOR/PFOR postings are near-SOTA;
Qdrant on_disk sparse is the most disk-hungry representation in this comparison.**

### Why each component is (or isn't) compressed — and the unexploited Qdrant lever

zstd + custom-dictionary is a **stored-text** lever; it does **not** apply to
postings or sparse vectors (those use integer/impact compression families). So in
the ~328 GB total:

- **Abstract sidecar (52.9 GB):** already zstd-19 + per-(section×language) dicts
  (3.42×, measured) — the stride is *already applied*.
- **meta.sqlite (24.9 GB):** already dict-zstd titles/DOIs + numeric PK.
- **tantivy BM25F (44.8 GB):** already delta/bit-packed (FOR/PFOR-style). zstd-dict
  on postings was **measured as a +0.7% null result** and skipped — postings aren't
  prose, so a text dictionary buys ~nothing.
- **Qdrant sparse (205 GB): NOT compressed at all.** Live config (probed
  2026-06-25): sparse `datatype` unset → **raw float32**, `quantization_config:
  null`. This is the one big component with its compression lever **untouched**.

**The lever:** Qdrant supports a sparse-vector value `datatype` of `float16`
(≈2×) or `uint8` (≈4×). **Important nuance (Qdrant docs):** the `datatype` sets
the precision of the values *inside the searchable index*, but **the original
f32 values are still kept on disk regardless** — so the primary win is **RAM /
page-cache footprint and scoring speed, not total on-disk bytes**. That is
exactly the 150M pain point: the searchable index is what must page-cache, and at
uint8 it shrinks ~4× (Qdrant's own example: ~13 MB for ~530k docs ⇒ ~24 B/doc ⇒
~7 GB at 150M for the quantized index, vs the f32 index today), so a far larger
fraction fits in RAM → latency drops. The **B1 parity gate already proved 8-bit
is safe**: BMP ×70 8-bit quant vs Qdrant f32 scored **overlap@10 = 1.0,
Kendall-τ = 1.0, NDCG Δ = 0.0** on the live index. **Status: UNIMPLEMENTED /
UNMEASURED** — the current collection is f32 by the original "measured-parity
path" choice; re-creating with sparse `datatype: uint8` (+ optional server-side
IDF) and re-running B1 + the latency `measure` is the owed step. This is the
analogous "stride" for the sparse leg — vector quantization, not zstd-dict —
and it attacks RAM-bound latency directly. (Total disk stays ~205 GB; the win is
latency/RAM.)

---

## 5. Ingest & ops

| | Thin-client (Qdrant) | OpenSearch |
|---|---|---|
| Ingest throughput | 4,234 docs/s (8 workers, wait=True); ~9.8 h for 150M | original indexer removed from this container — N/A |
| Re-ingest needed for SPLADE | no (re-uses stored `sparse_field` vectors) | no (rank_features stored) |
| Optimizer/merge OOM | **fixed** (`max_optimization_threads=1`, `max_segment_size=5_000_000`, persisted, verified live) | n/a (segment merge bounded by heap) |
| Crash recovery | serve-only supervisor `autorestart=true` | cluster/node management |
| Upsert resilience | `_upsert_wait_retry` backoff (IMPLEMENTED, unmeasured at scale) | native |

*Source: `THIN_CLIENT_SWAP.md` off-BMP + OOM sections; live collection config 2026-06-25.*

---

## 6. Architecture / deployment properties

| Property | Thin-client | OpenSearch |
|---|---|---|
| JVM required | **No** | Yes (2 GB heap min) |
| Runs on a laptop | Yes (at ~15M tier) | No (JVM + cluster floor) |
| Engines | 3 (tantivy + Qdrant + usearch) + Python RRF | 1 (Lucene, all legs) |
| Cold start | seconds (mmap) | JVM warmup |
| BM25F fidelity | near-identical (tantivy) | reference |
| Sparse search | **exact** dot product | approximate (impact-quantized) |
| Filters | sidecar numpy masks + over-fetch | native |
| Min viable host @150M | 64–128 GB (Qdrant RAM-bound below) | server-class, but bounded heap tolerates less RAM |

*Source: `THIN_CLIENT_STACK_RESEARCH.md` survey + POC.*

---

## Bottom line @150M

| Axis | Winner | Margin |
|---|---|---|
| **Quality (NDCG@10)** | **Thin-client** | +0.111, wins 29/34 |
| **Sparse-leg RAM scaling** | **OpenSearch** | bounded heap vs 6.55 GB+ rising anon floor |
| **On-disk size** | **OpenSearch** | ~141 GB vs ~328 GB (~2.3×) |
| **Latency** | inconclusive (not hardware-matched) | tc ~66 ms at fitting tier; 150M RAM-bound on 24 GB |
| **No-JVM / laptop fit** | **Thin-client** | OpenSearch can't run the laptop tier |
| **Exact sparse search** | **Thin-client** | exact vs impact-quantized |

**Synthesis:** the thin-client (with Qdrant) **wins ranking quality and the no-JVM
property** but **pays in disk and carries a rising RAM floor** that makes 150M
host-sizing the binding constraint. OpenSearch **wins RAM-at-scale and disk** but
**loses ~0.11 NDCG@10** and can't serve the laptop tier. This is exactly the
two-tier conclusion the original engine survey reached: **thin-client/Qdrant for
laptop + demo (≤~30M), OpenSearch 3.x for a full-150M server** — and on a properly
sized 64–128 GB box, Qdrant serves 150M too (just not on the 24 GB dev host).
</content>
