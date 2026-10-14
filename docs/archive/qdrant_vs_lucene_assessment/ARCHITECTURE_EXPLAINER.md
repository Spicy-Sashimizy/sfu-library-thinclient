# Architecture explainer: bounded heap, mmap, and the mutable-vs-immutable root cause

> **CLOSED SUPERSEDED 2026-07-06** — the "should we swap off Qdrant back to Lucene?" question was answered instead by promoting SEISMIC federated mmap (`docs/archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md`). The RAM analysis and OOM findings remain the recorded evidence base for that move. Not current; do not resume.

**Status:** CLOSED SUPERSEDED 2026-07-06

**Date:** 2026-06-25 · Explains *why* Qdrant carries a resident RAM floor that
Lucene/tantivy don't, why a "bounded heap" is a red herring, and whether a Rust
engine exists that would unify the lexical + sparse legs with ~0 resident RAM and
no JVM. **Verdict up front: that engine does NOT exist in production today** (§6).

---

## 1. How the JVM bounded heap works with Lucene/OpenSearch

A Lucene/OpenSearch process splits memory into two **separate** regions:

| Region | Holds | Bounded? | Reclaimable? |
|---|---|---|---|
| **JVM heap** (`-Xmx2g`) | transient query state: query objects, top-K priority queue, scoring buffers, field/query caches | **Yes** — JVM throws `OutOfMemoryError` past `-Xmx` | no (anonymous), but capped |
| **OS page cache** (via `MMapDirectory`) | the actual index: postings, term dict, doc-values, stored fields, **`rank_features` SPLADE postings**, HNSW | no (uses spare RAM) | **Yes** — kernel drops clean file pages on demand |

**Why a 2 GB heap serves a 274 GB index:** the index lives in files on disk, memory-mapped. A query pages in only the bytes it touches; those land in **page cache** (file-backed), not the heap. The heap holds only the few KB of per-query scoring state. The 274 GB never has to be resident.

The "bound" is a JVM safety property: the process's GC-managed anonymous memory is *guaranteed* ≤ `-Xmx`, so you can size a host as `heap + headroom + whatever page cache you choose to give it`.

## 2. The real principle: reclaimable (file-backed) vs non-reclaimable (anonymous)

This is the load-bearing idea behind the whole comparison:

- **File-backed pages** (page cache from mmap'd index files) = a clean copy of on-disk data, so the kernel can **evict them anytime** and re-read later. Effectively free.
- **Anonymous pages** (heap, `malloc`) = no on-disk backing, so they **cannot be reclaimed** without swap.

Lucene keeps almost everything **file-backed** (immutable mmap'd segments) and only a small, bounded slice anonymous (the heap). That — not the heap itself — is the source of its good memory behaviour.

## 3. Why tantivy needs no bounded heap — and gets the same result anyway

tantivy is **Rust: no JVM, no GC, no `-Xmx`.** It physically *can't* have a bounded heap. But it doesn't need one, because it already does the good thing:

> "Tantivy uses `MmapDirectory` where files on disk are accessed via mmap, and **does not require loading any data structures in anonymous memory**, so resident memory footprint is extremely low." (measured here: **45 MB RSS** for the BM25F leg.)

So tantivy reaches the *same* end-state as Lucene — tiny resident + reclaimable page cache — **without** a heap. **The bounded heap is not Lucene's superpower; mmap + immutable on-disk segments is, and tantivy has that too.** The heap is, if anything, a JVM *liability* (GC pauses, tuning) that tantivy avoids.

## 4. THE ROOT CAUSE you've been fighting: mutable vs immutable storage

This is the answer to "is the going issue that Qdrant's storage model is what I've been working around?" — **yes.** And it has nothing to do with heaps.

- **Lucene/tantivy segments are IMMUTABLE.** Write-once; updates make new segments, deletes are tombstones merged away later. Because a segment never changes in place, the per-document mapping (id → offset, liveness) is **baked into the on-disk file** — file-backed, reclaimable, nothing forced resident. SPLADE-as-`rank_features` is just more immutable postings in those same files.

- **Qdrant is a MUTABLE, MVCC point store**, built for live upserts/deletes. To support in-place mutation it must keep **per-point bookkeeping in anonymous RAM**: the id tracker, version tracker (MVCC), soft-delete bitsets, and sparse-index offsets. Measured: **~43 B/point → 6.55 GB resident at 150M**, scaling linearly, non-reclaimable. `on_disk=true` pushes the posting *lists* to mmap, but that resident per-point state is **structural to a mutable store** — config cannot remove it.

**So the chain you've been hitting is:**

```
Qdrant mutable/MVCC design
  → per-point trackers must stay RESIDENT (anonymous, non-reclaimable)
  → 6.55 GB floor at 150M that rises with corpus size
  → on a 205 GB index / 23 GB host, ~7% page-cacheable
  → RAM-bound: p50 545–861 ms, optimizer/server OOMs
  → all the supervisor/retry/host-sizing work you've been doing
```

Lucene's immutable segments never enter this chain: per-doc state is on disk, the heap is bounded, the rest is reclaimable cache. **Mutable-vs-immutable is the real fault line — not JVM-vs-no-JVM.** (Two *separate* Qdrant issues, don't conflate: the **anon RAM floor** = mutability; the **205 GB disk** = storing raw f32 uncompressed, fixable with `datatype: uint8`, see `STACK_COST_MATRIX.md`.)

## 5. Why the legs can't be "unified into one area" today

- **Lucene unifies them natively:** `rank_features` is a Lucene field type living in the *same* immutable segment files as the BM25 text fields — one index, one mmap'd region, one bounded heap. That unification is Lucene's structural edge and exactly what a multi-engine thin-client gives up.
- **tantivy + Qdrant can't unify:** two engines, two file formats, two processes — inherently two areas.
- **The specific missing piece:** to put SPLADE into a tantivy/Lucene-style inverted index you need an **impact-postings field that bypasses tf-idf scoring**. Lucene has it (`FeatureField`/`rank_features`). The naïve alternative — the "fake words" / term-repetition trick (store a term *N* times where *N* = its impact) — **distorts BM25's idf math** and is the wrong scoring (confirmed in `THIN_CLIENT_STACK_RESEARCH.md`). **tantivy has no `FeatureField` equivalent and no custom similarity from Python**, so SPLADE is not expressible on it today. That is the entire gap.

## 6. Does the "dream" Rust engine exist? — researched 2026-06-25

**The dream:** one no-JVM Rust engine storing BM25 lexical **+** SPLADE sparse in the *same immutable mmap'd segments*, ~0 resident floor, no per-point anon tax.

**Verdict: it does NOT exist as a production-ready engine today.** The pieces exist separately; nothing combines them. Closest candidates:

| Candidate | Lexical (BM25) | Sparse (SPLADE) | Storage model | Resident RAM | Status / gap |
|---|---|---|---|---|---|
| **tantivy** | ✅ excellent, mmap | ❌ **no `FeatureField`** | immutable mmap segments | **~0 (45 MB)** | perfect memory profile; **missing the sparse field type** — the whole gap |
| **LanceDB / Lance** (Rust) | ✅ FTS (tantivy-based) + dense | ⚠️ **can STORE sparse vectors as column data, but no sparse INDEX/search** (IVF-PQ + HNSW are dense-only) + storage not optimized for sparse ([Lance #4261](https://github.com/lance-format/lance/issues/4261)); SPLADE retrieval = open feature ([#1930](https://github.com/lancedb/lancedb/issues/1930)) | **immutable, versioned, mmap'd columnar** | low (mmap) | **most likely future home of the dream** — immutable + mmap by design, already has lexical + dense; the missing piece is the **sparse index + optimized sparse storage**, not the data type |
| **`sporse`** (Rust crate) | ❌ sparse-only | ✅ inverted index + Block-Max WAND, exact top-k | likely **RAM-resident** (Block-Max family, *unverified*) | likely high (like BMP) | young/unproven; not unified with lexical; probably re-creates the resident-RAM problem |
| **Seismic** (Rust, SOTA) | ❌ sparse-only | ✅ SOTA µs retrieval | **RAM-resident (~8 GB/9M)** | high at 150M | fast but same anon-RAM class as BMP; source-only wheels |
| **Qdrant** (Rust) | ⚠️ BM25-as-sparse only | ✅ native | **mutable MVCC** | **6.55 GB floor @150M** | the current pain — mutable store, §4 |
| **OpenSearch + SEISMIC** (JVM) | ✅ | ✅ SEISMIC ANN | immutable Lucene segments | bounded heap | solves it — **but it's the JVM**, not Rust |

**Reading the table:**
- The two halves of the dream each exist in Rust — **tantivy** nails the immutable/mmap/~0-RAM lexical half; **Seismic/`sporse`** do SOTA sparse — but **no one has fused them into a single immutable mmap'd index.** The sparse Rust engines are all **RAM-resident** (Block-Max/Seismic load into memory), so they'd reintroduce a resident floor anyway.
- The closest thing on a trajectory toward the dream is **LanceDB**: its Lance format is immutable + mmap'd columnar, it already serves lexical (tantivy) + dense, and it can already **store** sparse vectors as column data — but it has **no sparse index or sparse search** (its IVF-PQ/HNSW indexes are dense-only), and the columnar storage isn't yet optimized for sparse ([Lance #4261](https://github.com/lance-format/lance/issues/4261)). So the precise gap is the **sparse index + optimized sparse storage**, not the ability to hold the vectors. If/when the sparse *index* ships ([#1930](https://github.com/lancedb/lancedb/issues/1930)), LanceDB would be the first engine to actually offer "lexical + sparse, immutable, mmap, ~0 resident, no JVM." **Today it can store SPLADE vectors but not efficiently retrieve them.**
- The only thing that fully unifies lexical + sparse with bounded RAM **right now** is **Lucene/OpenSearch** — i.e. it requires the JVM. There is no no-JVM equivalent yet.

**Bottom line:** your instinct is correct and the gap is real and specific — it's a missing `FeatureField`-equivalent in a Rust immutable-segment engine. It's an **implementation gap, not a law of physics**, and LanceDB is the most credible engine likely to close it. Until then the honest choices stay: (a) Lucene/OpenSearch+SEISMIC (unified, bounded RAM, **JVM**), or (b) tantivy + a separate sparse engine (no JVM, but the sparse engine pays a resident-RAM tax — Qdrant's mutable floor, or Seismic/BMP's load-into-RAM).

### Could a LanceDB + BMP connector be the no-JVM cure? (researched 2026-06-25)

Tempting: LanceDB has the immutable/mmap/lexical/dense half and *lacks a sparse
index*; BMP *is* a Block-Max sparse index. But it splits on **BMP's memory model**
— and BMP's `Searcher` still **loads the whole index into anonymous RAM** (no mmap
mode, confirmed 2026; a recent update only shrank the *block-bound* storage
[5.5 GB vs 30 GB on MS MARCO], not the in-RAM posting data). So:

- **Naive connector** (Lance stores docs/dense + hydrates; BMP does sparse top-k
  in its own RAM): trivially wireable — both expose Rust/Python APIs, BMP returns
  ids, Lance hydrates — **but pointless.** BMP still `load_into_memory` at 3.07×,
  so it re-imports the **exact resident-floor disease**: ~37 GB RAM at a 26M
  persona, ~211 GB at 150M — **worse than per-persona Qdrant (~1 GB)**. This is
  essentially the *retired* BMP thin-client with Lance swapped in for
  meta.sqlite/tantivy. No win.
- **The version that actually helps is NOT a connector — it's a build:** port
  BMP's Block-Max WAND traversal to read **mmap'd immutable postings** (BMP's own
  `.bmp` files mmap'd, or the postings stored as Lance columns). Both BMP and Lance
  are **Rust**, so forking BMP's search to operate over Arrow/Lance mmap buffers is
  feasible-in-principle. **This cures the floor** (immutable mmap = reclaimable, no
  mutable per-point trackers) and, via Lance, unifies with lexical+dense → the
  dream no-JVM engine. The catch: it's the **same effort class as the
  "BMP-with-mmap fork" durable-fix already on the list** (`THIN_CLIENT_SWAP.md`),
  plus the Lance integration — a real R&D/ownership project, not wiring two
  libraries. And note the RAM cure is specifically *"make Block-Max search from
  mmap"*; **Lance isn't strictly required for that** (you could just mmap the
  `.bmp` files). Lance's value-add is the *unification* (one immutable store for
  lexical+sparse+dense) + versioning + the embeddable no-JVM substrate — i.e. it
  turns "mmap-BMP" into the unified engine and would contribute exactly the sparse
  index LanceDB #1930 wants.

**Verdict:** a LanceDB+BMP *connector* that helps = a **build project**
(mmap-Block-Max over immutable storage), worth it only as a strategic bet to *own*
the unifying no-JVM engine. The naive wire-up is a **no-op on the actual problem**
because BMP-in-RAM is the disease, not the cure. For pragmatic delivery the
existing paths (per-persona Qdrant local; immutable engine server) are far lower
effort.

### Does BMP's block-filtering tolerate a paged mmap access pattern? — source-checked (2026-06-25)

Checked the BMP Rust source (`pisa-engine/BMP`, `src/index/posting_list.rs`):

```rust
pub struct PostingList { range_maxes: BlockData, kth_score: Vec<u8> }
enum BlockData { Compressed(Vec<CompressedBlock>), Raw(Vec<u8>) }
pub struct CompressedBlock { max_scores: Vec<(usize, u8)> } // (block id, quantized max)
```

**Block-max is stored TERM-MAJOR:** each term (`PostingList`) owns a *contiguous*
list of `(block_id, max_score)` pairs (the sparse format). So block-filtering
iterates the query's *q* terms and reads each term's `range_maxes` as **one
contiguous run**, accumulating into a small per-block score array (#blocks at
150M, b256 ≈ 587k ⇒ a ~0.6–2 MB accumulator that stays resident).

**Verdict: the layout is mmap-TOLERANT.** Per-term access is
**sequential/prefetch-friendly**; across *q* terms it's *q* contiguous seeks, not
scattered-everywhere random access. This is the **same access shape as classic
WAND over mmap'd inverted postings — which Lucene/tantivy serve from mmap fine.**
The current `Vec` storage is an **engineering choice** (deserialize into heap for
peak speed), **not an algorithmic need** for non-mmappable random access. The only
mmap penalty is the **cold-cache tail** — ~*q* page faults on first touch of a
query's term lists, then sequential — i.e. the *same* page-warmup tail Qdrant
already has, which warms to a small **reclaimable** working set (no rising anon
floor). Block-evaluation then reads a few pruned candidate blocks' postings (few
seeks). **Caveat:** this is a static-analysis verdict, not a benchmark — the real
cold p95 of an mmap-BMP needs a prototype (mmap the `.bmp` file, measure warm vs
cold). But there is **no structural blocker**: the data is laid out the way
mmap-friendly search engines lay it out.

### Hypothesis — what mmap-BMP (immutable, Lance-unified) would buy us (est., unmeasured)

| Axis | vs **current** (tantivy + Qdrant f32) | vs **past OpenSearch** |
|---|---|---|
| **Resident RAM floor** | **cures it** — Qdrant's 6.55 GB rising anon floor → ~0 (immutable mmap, reclaimable page cache, like tantivy) | **better** — no JVM heap at all (~0 vs OpenSearch's 2 GB `-Xmx`) |
| **On-disk (sparse)** | **~3× smaller** — BMP b256 ≈ 68.6 GB vs Qdrant f32 205 GB | comparable (both compact; Lucene postings vs BMP 8-bit impacts) |
| **Warm latency** | likely **faster** — BMP approximate block-max pruning vs Qdrant's exact posting scan (their measure: BMP ~10.7 ms/q @100k) | comparable to OpenSearch+SEISMIC; faster than old two-phase rank_features |
| **Quality (NDCG@10)** | **neutral** — BMP ties Qdrant (overlap 1.0, RRF |Δ|<0.001 measured) | **keeps the +0.111 lead** the current stack already holds over OpenSearch |
| **Engines / unification** | **fewer** — Lance unifies lexical+sparse+dense in one immutable store vs 3 separate engines | similar (one store) but **no JVM** |
| **No-JVM** | preserved | **gained** (OpenSearch is JVM) |
| **Cost / risk** | **you build & own a custom engine**; cold-p95 unproven | same — vs OpenSearch's maturity, native filters/aggs/multi-tenancy |

**Net hypothesis:** mmap-BMP-over-Lance would, *if the engineering holds*, be
**strictly better than the current Qdrant path at 150M** (cures the floor, ~3×
less disk, faster warm, same quality, fewer engines, still no-JVM) and **beat past
OpenSearch on quality (+0.111) and no-JVM** while matching its RAM/immutability —
trading away OpenSearch's maturity/features and the cost of owning a custom
engine. **All `est.`/unmeasured** — contingent on a prototype proving the cold-p95
tail and preserving the measured parity. This is the concrete shape of "the dream
engine," and the source check says the algorithm doesn't structurally forbid it.

Sources: [tantivy MmapDirectory / Qdrant Gridstore](https://qdrant.tech/lp/lucene/),
[LanceDB sparse-vector roadmap issue #1930](https://github.com/lancedb/lancedb/issues/1930),
[sporse crate](https://docs.rs/sporse/latest/sporse/),
[Seismic](https://github.com/TusKANNy/seismic),
[OpenSearch SEISMIC neural sparse](https://opensearch.org/blog/scaling-neural-sparse-search-to-billions-of-vectors-with-approximate-search/),
["fake words" trick — Lucene LSR](https://arxiv.org/pdf/2311.18503).
</content>
