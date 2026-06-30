# 04 — What to borrow from Lucene (and what not to)

**Status: DESIGN REFERENCE (2026-06-30).**

The LSM machinery this idea rides on is Lucene, feature-for-feature. We are *not*
using Lucene (no-JVM thin client), so we re-implement the **design** over the
immutable SEISMIC/BMP leg. This doc extracts the specific Lucene components
worth cribbing, with class pointers, the algorithm, the tunables that matter,
and the SEISMIC adaptation. Lucene is Apache-2.0 — the *designs* are free to
reuse; do not paste Java verbatim, port the algorithm.

> Rule of thumb: borrow everything in §1–§5. Do **not** borrow Lucene's docid
> scheme (§6) — it is the exact opposite of what this idea needs.

---

## §1 Segment lifecycle + the commit point — BORROW

**Lucene:** `IndexWriter`, `SegmentInfos`, `IndexFileNames`.
- A segment is write-once. The set of live segments is named by a single
  atomically-swapped commit file (`segments_N` via `SegmentInfos`). Readers open
  *a* commit point; a new commit never mutates an open one.

**Why it helps:** gives the immutable SEISMIC leg a transactional "current set of
segments" without locks — readers keep serving the old generation while a flush
or merge writes a new one.

**SEISMIC adaptation:** a `manifest.json`-style commit file listing
`{segment_dir, id_prefix_range, tree_vN, doc_count, checksum}`; swap it
atomically (write-tmp + `rename`) after a flush/merge completes. You already have
`manifest.json` with section states + checksums — extend it to a generationed
segment list.

---

## §2 RAM buffer + flush trigger — BORROW

**Lucene:** `IndexWriterConfig.setRAMBufferSizeMB` /
`setMaxBufferedDocs`; `DocumentsWriter` flushes the in-memory buffer to a new
segment when the threshold trips.

**Key tunables to copy:**
- flush by **RAM size** (default 16 MB in Lucene) *or* doc count — size is the
  robust trigger across hardware (directly serves the any-hardware constraint).
- flush is **concurrent** with indexing (don't stall ingest).

**SEISMIC adaptation:** the "warm buffer fills → build one small SEISMIC
segment" step. Trigger on buffer RAM, not wall-clock, so a laptop and a server
self-tune segment size to their memory. This is also your NRT visibility knob:
smaller buffer = fresher immutable results, more segments (worse mmap).

---

## §3 TieredMergePolicy — BORROW (this is the most valuable piece)

**Lucene:** `org.apache.lucene.index.TieredMergePolicy` (the default since 3.x),
plus `ConcurrentMergeScheduler`.

**The algorithm (port this):**
- Group segments into **tiers** by size (roughly log-scaled buckets).
- Eligible merge = pick a budget-bounded set within a tier whose merged size
  stays under a cap; prefer merges that reclaim the most deletes / shrink the
  most segments per byte written.
- Run merges in the **background**, concurrently, throttled so they never
  starve queries.

**The tunables that actually matter (copy these names/intents):**
| Lucene knob | Default | What it controls | Why it matters here |
|---|---|---|---|
| `segmentsPerTier` | 10 | how many segments before a merge fires | the direct **resident-set vs. write-amp** dial |
| `maxMergedSegmentMB` | 5120 | cap on a merged segment | bounds the localised-rebuild cost per compaction |
| `floorSegmentMB` | 2 | tiny segments rounded up | stops a long tail of micro-segments killing mmap |
| `maxMergeAtOnce` | 10 | fan-in per merge | bounds rebuild working-set |
| `deletesPctAllowed` | ~20–33% | force-merge when tombstones pile up | see §4 |

**Why it helps:** this policy *is* the answer to the §01 mmap tension —
"too many small files" is precisely what TieredMergePolicy was built to bound.
Lucene spent ~20 years tuning it; start from its constants, then sweep.

**SEISMIC adaptation:** a "merge" is a **localised SEISMIC rebuild** of one
id-prefix's union, not a byte concat. So `maxMergedSegmentMB` /
`maxMergeAtOnce` are even more important — they cap how expensive each rebuild
is. Constrain merges to **within a single id-prefix** so merged segments stay
semantically local (preserves the mmap-locality win from §01).

---

## §4 Tombstone deletes (liveDocs) — BORROW

**Lucene:** `Bits liveDocs`, `BufferedUpdates`, `ReaderPool`.
- You never delete from an immutable segment. You keep a per-segment **liveDocs
  bitset** marking deleted/updated docs; queries skip them; space is reclaimed
  at the next merge. An "update" = delete-then-add (new doc in the buffer).

**Why it helps:** the immutable SEISMIC leg has no in-place delete either. A
sidecar bitset per segment + "force-merge when deletes exceed N%" gives you
retractions/corrections (OpenAlex docs do get withdrawn/merged) without mutating
a segment. `deletesPctAllowed` ties this back into §3.

**SEISMIC adaptation:** a roaring/bit-packed `livedocs.bin` next to each
`splade_NNN.seismic`; the retriever masks hits post-scan (you already do sidecar
post-filtering for BMP). Reclaim at the localised rebuild.

---

## §5 NRT reader management + mmap — BORROW

**Lucene:** `SearcherManager` / `DirectoryReader.openIfChanged`;
`MMapDirectory` + `MemorySegmentIndexInput`.
- **NRT:** `SearcherManager.maybeRefresh()` atomically swaps the active reader to
  the newest commit and ref-counts the old one until in-flight queries drain.
- **mmap:** `MMapDirectory` maps segment files and leans on the OS page cache;
  modern Lucene chunks the mapping and issues `madvise` hints
  (`IOContext`/`ReadAdvice`: `RANDOM` for postings, `SEQUENTIAL`/`WILLNEED` for
  merges).

**Why it helps:**
- The reader-swap + ref-count pattern is exactly how you flip to a new segment
  generation without tearing down in-flight queries (your `reload_index` MCP
  tool is the seam).
- The `madvise` hints are a free win for the mmap-bmp spike:
  `MADV_RANDOM` on posting-list regions stops the kernel read-ahead from paging
  in cold neighbours (a direct lever on resident-set), `MADV_WILLNEED` warms a
  segment being merged.

**SEISMIC adaptation:** wrap segment open/close in a ref-counted manager;
`mmap` + `posix_madvise(MADV_RANDOM)` on the `.seismic` posting regions; swap the
manifest generation under a refresh call.

---

## §6 Lucene's docid scheme — DO **NOT** borrow

**Lucene:** the internal docid is a **per-segment ordinal** (`0..maxDoc`),
**reassigned on every merge**, carrying zero semantic meaning. External identity
is a user `id` field you look up.

**Why we reject it:** it is the *opposite* of this idea's core. We need an ID
that is **stable across merges**, **hierarchical**, and **semantic** so it can be
the routing address (§01). Borrowing Lucene's ordinal would throw away the only
novel part.

Also do **not** borrow Lucene/ES **routing** (`hash(_routing) % numShards`): it
is flat and the shard count is fixed at index creation. Elastic prefix-depth
sharding (§01) is the explicit replacement.

---

## Summary table

| Lucene component | Class pointer | Verdict | SEISMIC adaptation |
|---|---|---|---|
| Segment commit point | `SegmentInfos` / `segments_N` | **Borrow** | generationed `manifest.json`, atomic rename |
| RAM buffer + flush | `IndexWriterConfig.setRAMBufferSizeMB` | **Borrow** | flush warm buffer → 1 SEISMIC segment, RAM-triggered |
| Merge policy | `TieredMergePolicy` + `ConcurrentMergeScheduler` | **Borrow (key)** | localised per-prefix SEISMIC rebuild; same tunables |
| Tombstone deletes | `liveDocs` / `BufferedUpdates` | **Borrow** | `livedocs.bin` sidecar, mask post-scan |
| NRT reader swap | `SearcherManager.openIfChanged` | **Borrow** | ref-counted segment manager via `reload_index` |
| mmap + madvise | `MMapDirectory` / `ReadAdvice` | **Borrow** | `posix_madvise(MADV_RANDOM)` on posting regions |
| Internal docid | per-segment ordinal | **Reject** | stable hierarchical semantic ID instead |
| Shard routing | `hash(_routing) % numShards` | **Reject** | elastic prefix-depth sharding instead |
