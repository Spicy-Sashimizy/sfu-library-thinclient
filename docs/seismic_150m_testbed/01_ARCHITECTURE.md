# 01 · Architecture

## The three candidate paths

All three serve the **same** SPLADE `sparse_field` already stored in `spool_backup`
(no re-encode). They differ in *where SEISMIC's index lives* and *what RAM it costs.*

| Path | What it is | No-JVM? | RAM cure | New code to own | Verdict source |
|---|---|---|---|---|---|
| **A — standalone `pyseismic-lsr`** | The MIT Rust crate as-is, called from the retriever like the Qdrant backend | ✅ | ❌ **RAM-resident** (gate-zero) — ~133 GB @150M est. | ~none (a backend shim) | the cheapest to measure; likely RAM NO-GO at 150M but proves quality+pruning |
| **B — OpenSearch + SEISMIC** | SEISMIC as a Lucene/OpenSearch sparse index (OS 3.3+); we already run OS 3.7 | ❌ **JVM** | ✅ bounded heap | ~none (re-index) | the **fallback baseline** — works, loses G-NOJVM |
| **C — SEISMIC geometry on an mmap substrate** | SEISMIC's blocks + summary vectors written to an immutable mmap'd store read zero-decode — **default: raw `memmap2`+`bytemuck` / `redb`** (Lance only if dense unification becomes a goal; substrate sub-table below) | ✅ | ✅ (by construction) | **the build** — a SEISMIC fork/extension + reader | the open contribution; weigh against R-OWN |

**The testbed runs A and B as the bracketing measurements** (A = no-JVM-but-RAM-bound,
B = JVM-but-cured), and only opens C if A's quality/pruning hold *and* the RAM gap is
real *and* C beats B on the ownership math.

## The integration shape (whichever path wins): two co-resident mmap engines

This is the architectural correction carried over from the design discussion. The
sparse leg is **not** fused into the lexical engine at the postings level. Instead:

```
                 query (text)
                     │
      ┌──────────────┼───────────────┐
      ▼              ▼                ▼
  tantivy        SEISMIC          usearch
  (BM25F)        (SPLADE)         (dense)
  mmap postings  own index        mmap HNSW
  ~0 anon        (path A/B/C)      ~0 anon
      │              │                │
      └──────────────┴────────────────┘
                     ▼
                  RRF fuse (result lists)
                     ▼
                cross-encoder rerank → top-k
```

- Each leg is an **independent engine** returning a ranked list. RRF fuses the
  *lists*, not the postings — exactly what the current stack already does.
- tantivy stays the lexical leg at ~0 anon (44.8 GB on disk, ~45 MB RSS, mmap).
- SEISMIC owns the sparse leg with its **own** index format and pruning traversal.

### Why NOT "integrate SEISMIC's scorer as a patch into tantivy"

A category error worth stating once so it isn't re-attempted:

- **SEISMIC's pruning is an index *format*, not a scorer.** Its selectivity lives in
  (1) per-term posting truncation, (2) similarity-clustered blocks, and (3) per-block
  **summary vectors** the traversal scores first to skip whole blocks. None of that is
  expressible over tantivy's `term → docid-sorted + tf` postings, and tantivy's search
  path has no "score the summary, maybe skip the block" notion.
- To get SEISMIC's geometry you would store SEISMIC's structures as *side files* in a
  tantivy segment and read **those**, bypassing tantivy's postings entirely. At that
  point tantivy is only an mmap `Directory` + segment lifecycle — you've **forked
  SEISMIC onto tantivy's container**, i.e. you maintain a SEISMIC fork *and* a tantivy
  integration. Double maintenance, for a substrate Lance gives you more cleanly.
- **So Path C, if pursued, targets Lance (or a thin mmap file) as the container — not
  tantivy.** tantivy's job is the lexical leg, full stop.

## Path C in detail — SEISMIC on an mmap substrate (this *is* the old BMP "Option B")

Path C is the same **immutable-mmap-substrate** idea the prior project
carried as Option B (`sparse_engine_project/00_VISION_AND_GOALS.md`,
`04_BUILD_AND_GATHER.md` "Lance sparse-column writer/reader", risk R9). It is worth
stating plainly that **the Lance idea fits SEISMIC better than it ever fit BMP** — and
exactly *where* it bites.

**Why it closes the loop here when it couldn't for BMP.** Lance contributes **one
axis only: the RAM cure** (immutable, mmap'd, page-cache-resident, ~0 anon). It
contributes *nothing* to pruning — Lance has no sparse index (the LanceDB #1930 gap,
`WHY_NO_FOSS.md`).
- For **BMP** that was fatal: BMP's broken axis was *pruning* (linear in corpus,
  `sparse_engine_project` row-6). Lance would have cured RAM and left a linear-scan
  engine — useless at 150M.
- For **SEISMIC** the broken axis is *RAM* (gate-zero) and pruning is **already
  validated at 138M**. So Lance cures the **only** remaining gap → validated pruning +
  cured RAM + no-JVM = the whole goal. Lance-on-SEISMIC completes; Lance-on-BMP never
  could.

**The catch that decides it — the FORMAT-WALL recurs.** Holding the data in Lance and
getting SEISMIC's *speed* are different things, and your own mmap-BMP spike already
paid for this lesson (`sparse_engine_project/03_GO_NO_GO_GATES.md` G3a): the R3-v1
compact format that **decoded per query** was 696 ms; the zero-decode
`bytemuck::cast_slice` POD layout was 25.63 ms — a ~27× swing on layout alone.
- SEISMIC's hot path is **random pointer-chasing** (coordinate-at-a-time traversal)
  into per-term block summaries and forward vectors — *not* a columnar scan. Lance is
  actually **purpose-built for random access** (adaptive structural encodings chosen by
  data width, [arXiv:2504.15247](https://arxiv.org/abs/2504.15247)), so the substrate is
  a *good* fit — better than the BMP-era framing assumed. **But "fast random access" ≠
  "zero-decode":** Lance's *compressed* encodings (bit-packing, dictionary) still
  transform bytes on read, and a summary-vector fetch issued as a Lance `take(row_id)`
  that materializes an Arrow array re-creates the per-query decode the spike measured at
  696 ms.
- **So the design constraint is to pin SEISMIC's hot structures to Lance's
  fixed-width / transparent (near-zero-copy) encoding** — store them as
  flat fixed-size-list-of-u8 / large-binary blobs that SEISMIC reads **zero-decode**
  with its own `bytemuck`-style reader over the mmap'd buffer, *not* as compressed
  typed columns. Hit that path and Lance is the immutable mmap container + lifecycle
  (+ dense-leg co-location) and SEISMIC's traversal does the work; miss it (let Lance
  compress the hot columns) and you rebuild the format-wall. This is a **solvable
  layout constraint, not a likely wall** — but it is the make-or-break and must be a
  measured gate, not an assumption.
- SEISMIC has **more surface for the wall than BMP did** (block summary *vectors*,
  clustered blocks, truncated postings, forward vectors — vs BMP's simple POD pairs),
  so more structures must be laid out zero-decode, and the spike is the proof that
  getting it wrong costs ~27×.

### Substrate choice — Lance is over-engineered for this; thinner wins

Once Path C's job is reduced to "an immutable mmap container holding fixed-width blobs
SEISMIC reads zero-decode with its own reader," **most of Lance is unused (columnar
scan, compression, schema evolution, ANN index, SQL layer) and one part (the encoding
layer) is an active hazard.** Lance is not load-bearing here — it was a convenience.
Candidates, ranked for *this* scope (immutable, no-JVM, SEISMIC-owns-scoring,
fixed-width POD, RAM cure via mmap):

| Substrate | Zero-copy mmap | No-JVM / embeddable | Fit | Verdict |
|---|---|---|---|---|
| **Raw `memmap2` + `bytemuck`/`zerocopy` flat files** | ✅ by construction (`cast_slice` over the mmap) | ✅ pure Rust, ~zero deps | thinnest possible; no encoding layer to fight | **TOP PICK — already proven (below)** |
| **redb** (pure-Rust KV) | ✅ zero-copy reads, mmap'd COW B-trees ([redb.org](https://www.redb.org/post/2023/06/16/1-0-stable-release/)) | ✅ **pure Rust** → trivial per-arch wheels | keyed access + crash-safety, still zero-copy | **best if you want ergonomics over hand-rolled offsets** |
| **LMDB** (via `heed`) | ✅ values are pointers into the mmap | ✅ (C dep) | mature, read-optimized | solid; redb is the pure-Rust equivalent |
| **Arrow IPC / Feather v2 (uncompressed)** | ✅ *for uncompressed fixed-width* — 8-byte aligned, footer-indexed random access, zero-copy "except when buffer compression is enabled" ([Arrow IPC](https://arrow.apache.org/docs/cpp/ipc.html)) | ✅ | cleanest *standard* format; no adaptive encoding to fight | good if you want a documented format, not bespoke |
| **Lance** | ⚠️ conditional (must pin to fixed-width encoding, [arXiv:2504.15247](https://arxiv.org/abs/2504.15247)) | ✅ | over-engineered for sparse-only; encoding hazard | **only wins if dense-leg unification becomes a goal** |
| RocksDB / sled | ❌ LSM + compaction = mutable churn (wrong model) | ✅ | — | skip |
| Parquet | ❌ scan-oriented, decode-heavy | ✅ | — | skip (the weakness Lance's own paper exists to fix) |

**The top pick is already validated by *this project*.** The only green latency number
in the prior engine spike — the FORMAT-WALL flip **696 ms → 25.63 ms** — was achieved
with **raw `memmap2` + `bytemuck::cast_slice` over `#[repr(C)]` POD**, *not* Lance
(`sparse_engine_project/03_GO_NO_GO_GATES.md` G1 zero-decode row, `R3v2_delta.patch`).
So "raw mmap + bytemuck" is not speculative — it is the substrate the team already
measured at the latency target.

**Recommended composition (assemble thin pieces, per `WHY_NO_FOSS.md`'s "one seam"):**
- **Term dictionary** (term → postings offset): an **mmap'd FST** — the [`fst` crate](https://crates.io/crates/fst),
  exactly what tantivy uses; zero-copy, tiny resident RAM.
- **Forward index + block postings + summary vectors**: **raw `memmap2` + `bytemuck`**
  flat regions behind an offset table (the proven path), **or `redb`** if you want keyed
  access + crash-safety without hand-rolling offsets.

This gives the RAM cure (page-cache-resident, ~0 anon), the zero-decode path, pure-Rust
+ trivial per-arch wheels, and **no dependency on a columnar engine you'd mostly bypass.**
**Substrate is a P5 decision, downstream of G4 (pruning) and G3 (RAM split)** — it is the
*easy* part (almost any thin mmap layer clears it); do not pull it forward over the gates
that actually decide the project.

**What Lance does *not* buy here.** The unification half of old Option B (one store,
fewer engines) is a **non-goal** in this testbed (`00_VISION` — RRF fuses result
lists, legs stay separate). Only the RAM-cure half counts. You use Lance for its mmap
`Directory` property, not its query engine.

**The cheapest version — mmap the forward index only.** SEISMIC separates
inverted + forward index; the forward index (docID→sparse vector) is typically the RAM
bulk, while the pruning structures (inverted + blocks + summaries) are smaller. Pushing
**just the forward index** to the mmap substrate — leaving the pruning side resident —
may cure most of the floor for a fraction of the fork cost (mirrors the mmap-BMP R3
result: forward index was ~100% of anon at 1M). **Which side dominates is a
measurement, not a guess → see G3, which now breaks RssAnon into forward-vs-inverted.**

**Still gated by R-OWN + R-OBSOLETE.** Substrate-on-SEISMIC means forking SEISMIC's
storage layer (a fork + the mmap layout + per-arch wheels, tracking upstream forever, G9),
and the ECIR-2025 authors' own future work names "indexes that cannot fit in main
memory" — they may ship on-disk SEISMIC first. **Re-check the repo for a native
on-disk mode before building Path C** (`04`/`05`).

## RAM model (why this can work where Qdrant can't)

| Engine | What forces RAM | @150M floor |
|---|---|---|
| Qdrant (present) | **mutable/MVCC** per-point bookkeeping (~43 B/pt) — non-reclaimable anon | **6.55 GB rising** + wants ~half of 205 GB page-cache |
| BMP (retired) | load-into-RAM forward+inverted | **211 GB** (unservable) |
| SEISMIC path A | load-into-RAM (forward + inverted) | **~133 GB est.** — same disease |
| SEISMIC path C | **mmap'd** blocks + summaries, page-cache resident | **~0 anon** (target), reclaimable cache only |

The win, if C is built, is identical in kind to tantivy's lexical win: immutable
mmap segments push the floor onto disk/page-cache, which is reclaimable — so a
150M index serves on commodity RAM instead of needing ≥64 GB just to stop thrashing.
