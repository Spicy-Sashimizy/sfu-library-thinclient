# Stack cost matrix @150M — past, present, mix-and-match (RAM + storage)

> **CLOSED SUPERSEDED 2026-07-06** — the "should we swap off Qdrant back to Lucene?" question was answered instead by promoting SEISMIC federated mmap (`docs/archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md`). The RAM analysis and OOM findings remain the recorded evidence base for that move. Not current; do not resume.

**Status:** CLOSED SUPERSEDED 2026-07-06

**Date:** 2026-06-25 · Scope: full 150M corpus. MEASURED unless marked *est.*
RAM column = **non-reclaimable resident floor** (what the engine forces into RAM);
page cache is reclaimable and listed separately where it matters. Sources in
`SPECS_COMPARISON_150M.md` / `FINDINGS.md`.

---

## Table 1 — per-leg engine options (the building blocks)

| Leg | Engine | Storage @150M | Resident RAM floor | Active RAM (under load) | Quality / speed | Status |
|---|---|---|---|---|---|---|
| **BM25F** | tantivy 0.26 (mmap) | **44.8 GB** | **~0** (45 MB RSS) | + reclaimable page cache | leg overlap@50 0.532 vs OS; 4.4 ms/q (100k) | **present** |
| BM25F | Lucene (OpenSearch) | in combined index | share of 2 GB heap | + reclaimable cache | reference; 19.7 ms/q (100k, HTTP) | past |
| **Sparse** | **Qdrant on_disk f32** | **205 GB** | **6.55 GB anon** (~43 B/pt) | **→ ~17 GB** (page-caching 205 GB) | exact; p50 545–861 ms @150M / 66 ms @30M | **present default** |
| Sparse | Qdrant on_disk **uint8** | ~205 GB (f32 kept on disk) | 6.55 GB anon | **much lower** — searchable index ~4× smaller (~7 GB *est.*) → more cacheable | exact, 8-bit proven == f32 (B1); latency ↓ *est.* | **proposed (move 1)** |
| Sparse | BMP 0.2.6 (load-into-RAM) | 68.6 GB | **211 GB** (3.07×, no mmap) | 211 GB | approx WAND; fast in-RAM | **RETIRED** |
| Sparse | Lucene `rank_features` (mmap) | in combined index | bounded heap | + reclaimable cache | approx; mmap postings | past |
| Sparse | **SEISMIC (OpenSearch 3.3+)** | *est.* compact | bounded heap | + reclaimable cache | **SOTA: sub-12 ms @ billion-scale, ≥90% recall** *(vendor)* | **available (move 3)** |
| Sparse | Seismic standalone (`pyseismic-lsr`) | ~similar | **RAM-resident (~8 GB/9M → huge @150M)** | RAM-resident | SOTA µs; **source-only wheels** | not viable @150M |
| **Dense** | usearch b1 + int8 (mmap) | 0.36 GB (600k) / ~7–26 GB *est.* full | ~0 (mmap) | + reclaimable cache | R@10 0.996 @32× | present |
| Dense | Lucene k-NN HNSW | in combined index | heap + mmap | + reclaimable cache | reference | past |
| **Shared** | meta.sqlite (mmap) | **24.9 GB** | ~0 | — | id→title/doi/year | both |
| Shared | abstract sidecar (hot, zstd-dict) | **52.9 GB** all-hot | ~0 (disk/mmap) | — | rerank fuel; cold = remote | thin-client |

---

## Table 2 — full-stack totals @150M (all sections queryable)

Engine-dependent legs + shared infra. **Disk = sum of components; RAM floor =
non-reclaimable resident.** Quality = RRF NDCG@10 (34-common, LLM-judged).

| Stack | BM25F | Sparse | Dense | meta + abstracts | **Total disk** | **Resident RAM floor** | RRF NDCG@10 | JVM? |
|---|---|---|---|---|---|---|---|---|
| **Past — OpenSearch (Lucene)** | Lucene | rank_features | k-NN | (in index) | **141.3 GB** (1 combined index; 274 GB raw) | **~2 GB heap** + reclaimable cache | 0.449 | yes |
| **Present — thin-client (Qdrant f32)** | tantivy 44.8 | **Qdrant 205** | 0.36 | 77.8 | **≈ 328 GB** | **6.55 GB anon** (→17 GB load) | **0.560** | no |
| **Present + uint8 (move 1)** | tantivy 44.8 | Qdrant ~205 | 0.36 | 77.8 | ≈ 328 GB | 6.55 GB anon, **far less page-cache needed** | 0.560 *est.* | no |
| Reference — BMP-era (retired) | tantivy 44.8 | BMP 68.6 | 0.36 | 77.8 | ≈ 192 GB | **211 GB** (unservable) | 0.561 | no |
| **Hybrid — tantivy + OpenSearch-SEISMIC sparse + usearch** | tantivy 44.8 | SEISMIC (in OS index) *est.* | usearch 0.36 | tantivy-side meta/abstracts 77.8 + OS index | **≈ 150–230 GB** *est.* | tantivy/usearch ~0 **+ bounded OS heap** | ~0.56 *est.* | partial (sparse only) |

**Reading it:**
- Past OpenSearch is **smallest on disk (141 GB) and lowest RAM floor (2 GB heap)** — but lowest quality and needs a JVM.
- Present Qdrant **wins quality (+0.111)** and drops the JVM, but is **~2.3× the disk** and carries a **rising 6.55 GB anon floor** that goes RAM-bound at 150M on small hosts.
- **uint8 (move 1)** keeps everything the same except it shrinks the *cacheable* searchable index ~4× → the 150M latency wall eases on the same host. Total disk ~unchanged.
- **BMP-era** is the cautionary row: smallest sparse disk (68.6 GB) but **211 GB RAM** — why it was retired.

---

## Table 3 — mix-and-match feasibility (BM25F × Sparse)

Each leg is independent (RRF fuses score lists), so you *can* mix engines — within
limits. ✅ works · ⚠️ works with a catch · ❌ not possible.

| BM25F engine ↓ / Sparse engine → | Qdrant (f32/uint8) | Lucene `rank_features` | OpenSearch SEISMIC | BMP |
|---|---|---|---|---|
| **tantivy** | ✅ **present** | ⚠️ needs embedded Lucene/PyLucene (a JVM sidecar + packaging pain) | ⚠️ sparse leg = an OpenSearch call (JVM server, but reuses your 3.7) | ✅ retired |
| **Lucene (OpenSearch)** | ⚠️ two systems (OS for BM25 + Qdrant for sparse) — redundant | ✅ **past (one index)** | ✅ **all in one OS 3.7 index** | ❌ no |
| **Can tantivy do sparse itself?** | ❌ **No** — tantivy has no `FeatureField`/`rank_features`; SPLADE not implementable from Python (measured) | | | |

**Key mix-and-match facts:**
- **tantivy + Qdrant** (present) is the clean no-JVM mix.
- **tantivy BM25F + OpenSearch SEISMIC sparse** is the "both worlds" mix: tantivy keeps the lexical leg at ~0 RAM, OpenSearch (which you already run at 3.7) serves SPLADE with Lucene's bounded heap **and** SEISMIC's speed. Catch: the sparse call crosses into a JVM service — but it's the one you already operate, not a new stack.
- **All-in-OpenSearch-3.7 + SEISMIC** is the lowest-moving-parts server option (one index, BM25F + SEISMIC sparse + k-NN dense together).
- **tantivy can never own the sparse leg** — that's the hard constraint that forces either Qdrant/Seismic/BMP (no-JVM) or Lucene (JVM) for SPLADE.

---

## Total tech cost — the bottom line per realistic config

Per-persona **serving** footprint (hot/cold: one hot section live, 9 packed), the
number that actually runs:

| Config | Disk (serving) | RAM floor (resident) | Page cache wanted | Min host RAM | Quality |
|---|---|---|---|---|---|
| **Past — OpenSearch 3.x (restore index)** | ~141 GB | ~2 GB heap | reclaimable, as available | ~16–32 GB | 0.449 (0.45) |
| **Present — Qdrant f32, hot/cold** | Qdrant 205 + ~104 GB index ≈ **309 GB** | **6.55 GB anon** | a large fraction of 205 GB | **64–128 GB** for ~66 ms; works (slow) at 24 GB | **0.560** |
| **Present + uint8 (move 1)** | ~309 GB | 6.55 GB anon | ~7 GB searchable index (*est.*) | **far lower** — fits a smaller box near fitting-tier *est.* | 0.560 *est.* |
| **Hybrid — tantivy + OS-SEISMIC** | tantivy/meta/abstracts ~104 GB + OS sparse index *est.* | tantivy/usearch ~0 + **bounded OS heap** | reclaimable | ~32–64 GB *est.* | ~0.56 *est.* |
| **Demo — Qdrant @30M** | ~40 GB | 1.44 GB | ~40 GB | **16–32 GB** | n/a (tier) |

- **Cheapest on RAM+disk:** OpenSearch (141 GB, 2 GB heap) — but lowest quality + JVM.
- **Best quality:** present thin-client (0.560) — at a 64–128 GB / ~309 GB cost at 150M.
- **Best cost-for-quality, least overhead:** **move 1 (uint8)** on the present stack — same disk, far less RAM pressure, quality held; **then** consider the SEISMIC hybrid for the server tier.
- **Constant across all:** dense ~0.36 GB now (→ ~7–26 GB *est.* at full coverage), meta 24.9 GB, hot abstracts 52.9 GB — these don't change with the BM25/sparse engine choice.
</content>
