# Updatable, disk-resident learned-sparse / impact indexes: engine survey (as of 2026-10-02)

**Status:** ACTIVE (research input to the delta_ingest track; compiled 2026-10-02, moved from the repo root `research_notes/`/`reports/` 2026-10-10)

Context: 150M SPLADE docs, ~85 nnz/doc, 8 mmap SEISMIC shards, one host with 32–48 GB RAM. Scope clarification from the owner (received mid-task): the idea being checked is to take **only the updater** (insert/update/delete/merge machinery) from an existing product and attach it to our system, with SEISMIC shards and tantivy still serving, possibly through a translation layer. The whole engine is not being adopted. Each engine section below has an "Updater separability" block. Whole-engine RAM/latency facts are kept as secondary context.

Tags: [read] = I opened the page or source and read it; [snippet] = search-result snippet only; [inferred] = my inference or background knowledge, not verified this session. Rough arithmetic for our corpus: 150M × 85 ≈ 12.75B postings.

---

## Qdrant: sparse vectors (on_disk / memory tiers, segments, optimizer)

### Takeaway
The 2026-09-29 claim is partly outdated. In Qdrant the *mutable* sparse index (appendable segments) lives in RAM (`InvertedIndexRam`). The optimizer then rebuilds immutable segments into a compressed inverted index, which can be mmap'd: `on_disk: true`, which since v1.19 (2026-08-05) is `memory: cold` or the new `memory: cached`. So the bulk of a large collection *can* be disk-resident. Only the not-yet-optimized tail has to fit in RAM. No official ≥100M sparse benchmark exists. The updater lives in Apache-2.0 Rust crates (`sparse`, `segment`, `shard`, `wal`), and `qdrant-edge` on crates.io is an embeddable bundle of them. It is tied to Qdrant's own segment and index formats.

### Cited Findings
- The sparse index has been available since v1.7.0. It is exact (no approximation). "All sparse vectors added to the collection are immediately indexed in the mutable version of a sparse index." The docs also mention "a more compact and efficient immutable sparse index, which is constructed during the same optimization process as the dense vector index." [read] — [Qdrant indexing docs](https://qdrant.tech/documentation/concepts/indexing/#sparse-vector-index)
- Memory tiers for the sparse index: `pinned` (default, "loaded into memory"), `cached` ("pre-loaded into the disk cache on startup, though it may be evicted under memory pressure") and `cold` ("stored on disk, which saves memory at the cost of search performance"). Config: `"sparse_vectors": {"text": {"index": {"memory": "cold"}}}`. [read] — [Qdrant indexing docs](https://qdrant.tech/documentation/concepts/indexing/#sparse-vector-index)
- "For sparse vectors, only the sparse vector index has a `memory` parameter." "Qdrant doesn't offer a RAM cache for sparse vectors, since their values aren't read during the index search step itself, only when a point is fetched." Legacy mapping: `pinned` = `on_disk: false`, `cold` = `on_disk: true`. Memory tiers were introduced in v1.19. [read] — [Qdrant Memory Tiers](https://qdrant.tech/documentation/ops-configuration/memory-tiers/)
- The Qdrant 1.19 release blog is dated 2026-08-05. It says "sparse indexes have gained a new `cached` tier". It gives no sparse performance numbers. [read] — [Qdrant 1.19 blog](https://qdrant.tech/blog/qdrant-1.19.x/). The latest server release is v1.19.1 (2026-09-04) [read, GitHub API] — [releases](https://github.com/qdrant/qdrant/releases)
- In source, the segment-level enum has these index variants: `SparseRam(InvertedIndexRam)`, `SparseCompressedImmutableRam{F32,F16,U8}` and `SparseCompressedMmap{F32,F16,U8}` (`InvertedIndexCompressedMmap<W, MmapFile>`). Only the mmap variants implement `populate()` / `clear_cache()`. [read] — [lib/segment/src/index/vector_index_base.rs](https://github.com/qdrant/qdrant/blob/master/lib/segment/src/index/vector_index_base.rs)
- `lib/sparse/src/index/inverted_index/` contains `inverted_index_ram.rs`, `inverted_index_ram_builder.rs`, `inverted_index_compressed_immutable_ram.rs` and `inverted_index_compressed_mmap.rs`. The mmap format consists of an index data file plus `inverted_index_config.json`, with a `StorageVersion`, an `InvertedIndexFileHeader` and a per-list `PostingListFileHeader<W>`. [read] — [qdrant/lib/sparse](https://github.com/qdrant/qdrant/tree/master/lib/sparse/src/index/inverted_index)
- PR #10682 was merged on 2026-09-17. It fixed `PostingList::upsert` rewriting whole posting lists, which made `InvertedIndexRam` (the mutable index of appendable segments) quadratic. On 1M SPLADE points, index building went from 250/s to 114,422/s. End-to-end upload went from 72.2 s to 23.7 s with defaults, and from 839.8 s to 29.5 s with `indexing_threshold: 0`. [read] — [PR #10682](https://github.com/qdrant/qdrant/pull/10682). Inference: before this fix, sparse ingest into appendable segments was pathologically slow, which may explain part of the earlier "slow at 150M" experience.
- A third-party tutorial says: set `on_disk=True` "only if you have >100M points", the on-disk path is "around 30% slower", and this lets 100M points fit on a 64 GB machine. [snippet, non-official, unverified] — [theneuralbase.com](https://theneuralbase.com/qdrant/learn/advanced/on-disk-vs-in-memory-vectors/)
- Appendable segments: "You can freely add, delete and query data in the appendable segment, and at least one appendable segment must be present." [snippet] — [Qdrant storage docs](https://qdrant.tech/documentation/manage-data/storage/)

### Updater separability
1. **What the updater is** [read, source tree]: a WAL (`lib/wal`, crate `wal` v0.1.4, Apache-2.0, `publish = false`, originally Dan Burkert's WAL); the shard and segment holder with appendable/non-appendable segments, deletes as per-segment ID-tracker flags, and optimizers (`lib/shard`, `lib/segment`, `lib/collection`); and the sparse index structures (`lib/sparse`, Apache-2.0, depends on `common`, `blobstore`, `memmap2`, `half`, `bitpacking`, `zerocopy` and others). — [lib/](https://github.com/qdrant/qdrant/tree/master/lib)
2. **Usable as a library?** Yes, as the whole local engine. `qdrant-edge` is an in-process Rust crate on crates.io (v0.8.0 published 2026-08-05; first version 2026-03; Apache-2.0) with a Python package `qdrant-edge-py`. It is generated by `amalgamate.py`, which bundles the internal crates (bm25, common, edge, blobstore, posting_list, quantization, segment, shard, sparse, wal). Its examples include `bm25-search.rs`, and `lib/edge/src` handles sparse vectors. [read: crates.io API + lib/edge/README] — [crates.io qdrant-edge](https://crates.io/crates/qdrant-edge), [lib/edge](https://github.com/qdrant/qdrant/tree/master/lib/edge); bundle list [snippet] — [DeepWiki](https://deepwiki.com/qdrant/qdrant/11.4-qdrant-edge-library). The individual crates (`sparse`, `wal`, `segment`) are workspace-internal (`publish = false` seen for `wal`) and have no stable public API. [read/inferred]
3. **Translation layer** [inferred]: the updater produces Qdrant segments, whose immutable sparse index is a Qdrant-specific compressed posting format. That format is versioned (`StorageVersion`) but not documented as a public format. Translating would mean reading Qdrant's posting lists (dim → [(point id, weight)], with block max-next-weight metadata) and point-ID mappings, then re-clustering them into SEISMIC blocks and summaries. SEISMIC needs global per-term clustering, so a "merge" in Qdrant does not yield a SEISMIC-ready unit without a SEISMIC rebuild of that unit.
4. **Precedent** [snippet/read]: qdrant-edge itself is Qdrant embedding its own updater in-process. I found no third party that took only Qdrant's segment/optimizer machinery to feed a different index.

### Inferences
- With `memory: cold`/`cached`, 150M × 85 nnz in compressed mmap segments would be page-cache-resident rather than anonymous RAM. Appendable segments (below `indexing_threshold`) and the ID tracker / payload structures still use heap. [inferred]
- Qdrant's immutable sparse search is exact and term-at-a-time / DAAT over full posting lists, not SEISMIC-style approximate. At 150M, latency would track posting-list length. [inferred]

### Gaps
- No official Qdrant sparse benchmark at ≥ 100M with RAM/latency/build-time numbers was found.
- Official numbers for cold vs cached vs pinned sparse latency were not found.
- Whether the optimizer's merge of sparse segments needs the full source posting lists in RAM was not verified in source.

---

## Vespa: wand / dotProduct / weakAnd over attributes, paged attributes, index fields

### Takeaway
The earlier claim mostly holds: fast `wand`/`dotProduct` need a weightedset **attribute with fast-search**, and its dictionary and posting lists are **never paged out**. `paged` pages only the attribute data vector. Disk-backed **index** fields are allowed for wand/dotProduct, but the docs say performance is "much weaker". Updates go through the transaction log into in-memory attributes. Vespa is a monolithic server (Apache-2.0, C++/Java), and its updater is not separable.

### Cited Findings
- WAND and dotProduct field types: "Weighted set attribute with fast-search. Note: Also supported for regular attribute or index fields, but then with much weaker performance." weakAnd: "Multiple fields of all types (both attribute and index)". [read] — [YQL reference](https://docs.vespa.ai/en/reference/query-language-reference.html)
- wand works over "a single weightedset field", string or int/long; "the weight is always int". Example: `weightedset<int> { indexing: summary | attribute, attribute:fast-search }`. On 8.8M MS MARCO passages, wand with totalTargetHits = 1000 evaluated 196,900 docs instead of 7,926,256 and returned the same top results. [read] — [Vespa WAND guide](https://docs.vespa.ai/en/using-wand-with-vespa.html)
- "For attribute fields using fast-search, the memory needed for dictionary and index structures are never paged out to disk." Multivalue/weightedset sizing is D × V × ((FW or EIW) + WW) × ROF, with EIW = 4 B, WW = 4 B and ROF = 6/5. Updates write the full value into a memory buffer, with the transaction log for durability. [read] — [Vespa attributes](https://docs.vespa.ai/en/attributes.html)
- `paged` is not supported for "tensor with fast-rank" or "predicate". Documented downsides include "Unpredictable query latency as attribute access might touch disk" and "Using a paged attribute in first-phase ranking can result in extremely high query latency if a large amount of the corpus is retrieved." [read] — [Vespa attributes](https://docs.vespa.ai/en/attributes.html)
- "Weightedset attributes use memory-only operations when updating: read full set, update, write back." [snippet] — [Vespa feed sizing](https://docs.vespa.ai/en/performance/sizing-feeding.html)

### Updater separability
1. The updater is the Vespa content node: proton document DB, transaction log, attribute flush, disk-index fusion. It is C++ inside the `vespa-engine/vespa` monorepo. [inferred]
2. I found no evidence that it can be used as a standalone library. It is coupled to Vespa's document model and config system. [inferred]
3. A translation layer would have to read Vespa attribute snapshot files or disk-index posting files. These are internal formats with no documented stability. [inferred]
4. No precedent found.

### Inferences
- For our corpus, attribute data alone is 150M × 85 × (4 + 4) × 1.2 ≈ 122 GB. That part is pageable with `paged`, but the fast-search posting structures (~12.75B postings) must stay in RAM. This is far beyond 32–48 GB. [inferred from the documented formula]

### Gaps
- No published Vespa learned-sparse benchmark at ≥ 100M with RAM numbers was found.
- No measured numbers for wand over disk *index* fields ("much weaker" is unquantified).

---

## Elasticsearch `sparse_vector` and Lucene FeatureField

### Takeaway
ES `sparse_vector` is Lucene `FeatureField`: the weight is encoded in the term frequency with 9 significant bits. Postings are on disk and read through mmap and the page cache, not the JVM heap, so the "needs JVM heap" claim is imprecise. The heap holds caches and inference models, not the postings. Updates use Lucene's standard machinery: an in-memory buffer, immutable segments, a liveDocs tombstone bitset and merges. That machinery is Lucene's IndexWriter (Apache-2.0, Java), which is a library.

### Cited Findings
- `SparseVectorFieldMapper` imports `org.apache.lucene.document.FeatureField`. Its Javadoc reads: "A FieldMapper that exposes Lucene's FeatureField as a sparse…". Indexing calls `new FeatureField(fullPath(), feature, value, …)`, queries use `FeatureField.newLinearQuery`, and values decode from `freq()` via `XFeatureField.decodeFeatureValue`. [read, source] — [SparseVectorFieldMapper.java](https://github.com/elastic/elasticsearch/blob/main/server/src/main/java/org/elasticsearch/index/mapper/vectors/SparseVectorFieldMapper.java)
- Values are stored "as floats with 9 significant bits for the precision", with a relative error of about 0.4%. Query-side token pruning (`prune`, `tokens_freq_ratio_threshold` default 5, `tokens_weight_threshold` default 0.4) has been GA since 9.1. Excluding vectors from `_source` has been GA since 9.2. Only strictly positive values are accepted. [read] — [ES sparse_vector docs](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/sparse-vector)
- `sparse_vector` was reintroduced in ES 8.11 for ELSER v2. [snippet] — [Elastic docs/blogs via search](https://www.elastic.co/docs/explore-analyze/machine-learning/nlp/ml-nlp-elser)
- "The filesystem cache is largely used by Lucene to MMAP the index data." [snippet] — [oneuptime blog](https://oneuptime.com/blog/post/2026-01-25-elasticsearch-memory-settings/view)

### Updater separability
1. Lucene `IndexWriter` is the updater. It covers RAM buffering, flushes to immutable segments, deletes and updates via `updateDocument` (delete-by-term plus add, with liveDocs bitsets), `MergePolicy`/`MergeScheduler`, and an optional NRT reader. It is a public, stable Java API (Apache-2.0). Elasticsearch adds a translog on top. [inferred, background knowledge]
2. Lucene is a library by design, but it brings Lucene's codec/segment format and the JVM. [inferred]
3. A translation layer could read FeatureField postings per term (docID, freq → weight) through public `LeafReader` APIs and rebuild SEISMIC blocks per merged segment. The Lucene codec is versioned and readable through stable APIs, but the docIDs are segment-local and change on merge. [inferred]
4. Precedent: Anserini/Pyserini build Lucene "impact" indexes for SPLADE (quantized weights as term frequencies), including prebuilt SPLADE-v3 indexes for MS MARCO v2.1 segmented docs. The search result gives 124,131,414 segments for the v2 segmented collection. This is Lucene used as a library for learned-sparse indexes, as static batch builds. [snippet] — [Pyserini prebuilt indexes](https://github.com/castorini/pyserini/blob/master/docs/prebuilt-indexes.md), [HF castorini MS MARCO v2.1 seg](https://huggingface.co/datasets/castorini/prebuilt-indexes-msmarco-v2.1-doc-segmented)

### Gaps
- No Elastic-published benchmark of `sparse_vector` at ≥ 100M docs with RAM, latency or build numbers was found.
- Licence: ES is SSPL / Elastic License / AGPLv3 (tri-licence since 2024) [inferred, not re-verified this session]. Lucene is Apache-2.0.

---

## OpenSearch neural sparse (rank_features two-phase and 3.3+ SEISMIC "neural sparse ANN"); summary only

### Takeaway
Classic neural sparse uses Lucene `rank_features` (FeatureField), so its postings are on disk and page-cache-backed, like ES. The 3.3+ SEISMIC ANN mode builds SEISMIC per Lucene segment above `approximate_threshold` and **caches the sparse data in JVM memory**, at about 1 GB per 1M docs. Updates still flow through Lucene segments and merges, with SEISMIC built at merge or flush time for large segments.

### Cited Findings
- Neural sparse ANN was introduced in 3.3 and uses SEISMIC on `sparse_vector` fields. Segments below `approximate_threshold` are indexed and queried as plain rank_features. Larger ones become SEISMIC segments. "OpenSearch caches sparse data in JVM memory." Sizing guidance: "approximately 1 GB of memory per 1M documents". Recommended: set the threshold to 5M and force-merge to 5–10M docs per segment. [snippet] — [OpenSearch neural sparse ANN docs](https://docs.opensearch.org/latest/vector-search/ai-search/neural-sparse-ann/), [performance tuning](https://docs.opensearch.org/latest/vector-search/performance-tuning-sparse/)
- Blog dated 2025-10-28 (OpenSearch 3.3). Corpus: 1,285,526,507 docs (C4/Dolma chunks), 15 × r7g.12xlarge data nodes, 10 SEISMIC segments per node of about 8.5M docs each. Results: about 53 GB memory per data node; at 90.2% R@10, average 11.77 ms, P50 11 / P90 16 / P99 27 / P99.9 50.02 ms (single-threaded), 158.7 ops/s with 4 threads. Force merge took 2 h 58 m 30 s. Comparison latencies: BM25 41.52 ms, standard neural sparse 125.12 ms. [read] — [OpenSearch blog](https://opensearch.org/blog/scaling-neural-sparse-search-to-billions-of-vectors-with-approximate-search/)
- Source classes include `sparse/cache/ClusteredPostingCache`, `ClusteredPostingReader` and `ClusteredPostingWriter` in neural-search. [read, filenames via code search] — [opensearch-project/neural-search](https://github.com/opensearch-project/neural-search)

### Updater separability
- The updater is Lucene IndexWriter plus the OpenSearch translog. SEISMIC structures are written by a custom codec on flush and merge (ClusteredPostingWriter). The codec lives inside the neural-search plugin (Apache-2.0), not as a standalone library. Another researcher covers its internals. [inferred]

### Gaps
- Single-host, small-RAM numbers at ≥ 100M are not published. The only scale point is 1.29B across 15 nodes (~795 GB total memory used).

---

## Milvus / Knowhere: sparse (SPARSE_INVERTED_INDEX, SINDI, mmap, 2.5 → 3.0)

### Takeaway
The earlier claim needs correcting. Sealed-segment sparse indexes are mmap-able: an mmap fix and enable shipped in 2.4.20, and Knowhere `DeserializeFromFile` mmaps the index file. Growing segments use `GrowableInvertedIndex`, which is explicitly all in memory. Milvus 3.0 (2026-07-27) made SINDI the default sparse IP algorithm and added block-compressed postings and quantization. The sparse index code is in Knowhere (Apache-2.0, C++), a standalone library. But Knowhere contains only the index. WAL, deletes and compaction are in Milvus itself.

### Cited Findings
- `inverted_index_algo` options: DAAT_MAXSCORE (default for BM25), DAAT_WAND, TAAT_NAIVE, BLOCK_MAX_MAXSCORE, BLOCK_MAX_WAND, and SINDI ("based on fixed document-id windows, with SIMD acceleration… default for IP"). Search parameter: `drop_ratio_search`. [read] — [Milvus SPARSE_INVERTED_INDEX](https://milvus.io/docs/sparse-inverted-index.md)
- SPARSE_WAND is deprecated from 2.5.4 in favour of `inverted_index_algo: DAAT_WAND`. 2.4.20 "fix[ed] mmap for sparse index" / "enabled mmap for sparse index (#38849)". [snippet] — [Milvus 2.4.x release notes](https://milvus.io/docs/v2.4.x/release_notes.md)
- Milvus 3.0 blog dated 2026-07-27: "block-compressed postings (VByte-related algorithms plus SIMD decoding) and quantization (fp16 for inner products, u16 for BM25)", a BM25 index about 3× smaller than 2.6, and "SINDI reaches up to about 10x the QPS of MaxScore on learned-sparse vectors, with a worst-case of around 5x" on 4 SPLADE datasets. SINDI is the default for sparse IP. The post states no dataset sizes or RAM numbers. [read] — [Milvus 3.0 blog](https://milvus.io/blog/announcing-milvus-3-lake-native-vector-search-and-a-more-powerful-retrieval-engine.md)
- Knowhere: `GrowableInvertedIndex` is a "Dynamic in-memory inverted index for sparse vectors that supports incremental updates… All data is stored in memory." In `sparse_index_node.cc`, `CreateIndexImpl(cfg, is_growable)` picks Growable(Sindi)InvertedIndex for growing segments ("For concurrent add/search, always use growable index"), and `DeserializeFromFile` mmaps the serialized file (`mmap(... PROT_READ ...)`, with an optional populate). Directory files include `block_inverted_index.h`, `sindi_inverted_index.h`, `inverted_index_format.h` and `codec/`. Licence Apache-2.0. Latest releases: v3.0.4 and v2.6.16 (2026-06-17). [read, source via GitHub API] — [knowhere/src/index/sparse](https://github.com/zilliztech/knowhere/tree/main/src/index/sparse)
- The general mmap docs mention `queryNode.mmap.vectorIndex` / `vectorField` and say "Memory mapping is not supported for DiskANN or GPU-class indexes". They say nothing specific about sparse. [read] — [Milvus mmap docs](https://milvus.io/docs/mmap.md)
- Milvus 2.6 (2025-06-12 announcement) added tiered storage with hot/cold on-demand loading. [snippet] — [GlobeNewswire](https://www.globenewswire.com/news-release/2025/06/12/3098386/0/en/Milvus-2-6-Built-for-Scale-Designed-to-Reduce-Costs.html), [tiered storage blog](https://milvus.io/blog/milvus-tiered-storage-80-less-vector-search-cost-with-on-demand-hot%E2%80%93cold-data-loading.md)
- Issue #33776: under concurrent DML/DDL with sparse vectors, querynode memory grew about 26 GB over 3 h (benchmark bug report, 2024). [snippet] — [issue #33776](https://github.com/milvus-io/milvus/issues/33776)

### Updater separability
1. The updater is Milvus itself (Go plus C++ segcore): WAL / streaming node (Woodpecker or Pulsar/Kafka in 2.6+), growing → sealed segment flush, delete logs / bloom filters, and compaction (mix/L0/clustering), with index builds on sealed segments. Knowhere only provides `Add` (growable) and build/serialize/deserialize (sealed). [inferred from source plus architecture background]
2. Knowhere is usable as a C++ library (Apache-2.0) for building and searching sparse indexes, including the growable one. But it has no delete/tombstone or merge logic. Tombstones are bitsets that Milvus passes in at search time. [inferred]
3. Translation: Knowhere's serialized sparse format (`inverted_index_format.h`, codecs) is internal and has changed across 2.6 → 3.0 ("persisted format" overhaul [snippet]). Converting to SEISMIC would mean decoding postings and re-clustering. [inferred]
4. Precedent: Knowhere is embedded by Milvus and Zilliz Cloud. I found no third-party use of Milvus's compaction or updater alone.

### Gaps
- No published Milvus sparse benchmark at ≥ 100M with RAM numbers was found. The 3.0 post gives only relative QPS and size.
- I did not verify whether the 3.0 SINDI sealed index is mmap-able under tiered storage at query time, with page-in rather than full load.

---

## Infinity (infiniflow): BMP sparse index

### Takeaway
Infinity has a real-time sparse index based on Block-Max Pruning (BMP). The index file worker supports mmap reads. Infinity is Apache-2.0 C++ (latest v0.7.3, 2026-08-06) with segments and a transactional storage layer. I found no scale benchmarks, and the updater is not packaged separately.

### Cited Findings
- "Infinity supports real-time sparse vector search, which is based on a sparse vector index implemented using Block-Max Pruning (BMP)." [snippet] — [Infinity search guide](https://infiniflow.org/docs/search_guide)
- Source: `bmp_index_file_worker_impl.cpp` implements `ReadFromMmapImpl` / `FreeFromMmapImpl`, building a `BMPHandler` over mmap'd data. Transactional index code is in `src/storage/new_txn/new_txn_index_impl.cpp`. Licence Apache-2.0. Latest release v0.7.3, 2026-08-06. [read, source via GitHub API] — [infiniflow/infinity](https://github.com/infiniflow/infinity)
- A commit titled "Dump mem index for sealed segments generated by Append" suggests a mem-index → dump path for appended data. [snippet] — [infinity actions run](https://github.com/infiniflow/infinity/actions/runs/15486598955)
- The roadmap lists mmap-backed secondary indices for v0.7.0 (search summary). [snippet, low confidence] — [Roadmap issue #338](https://github.com/infiniflow/infinity/issues/338)

### Updater separability
- The updater (new_txn, segments, compaction, buffer manager) is in-tree C++20 modules (`.cppm`) coupled to Infinity's buffer manager and file workers. I found no standalone library. The BMP index format is internal. [inferred]

### Gaps
- No ≥ 100M numbers, no RAM numbers, and no documented delete/merge semantics for BMP were found.

---

## Weaviate

### Takeaway
I could not confirm the 2026-09-29 claim either way. I found no evidence of user-provided (SPLADE) sparse vector support. Weaviate's hybrid search uses BM25 for its sparse side.

### Cited Findings
- Weaviate's knowledge cards describe sparse embeddings (BM25, SPLADE) conceptually. Hybrid search, added in 1.17, uses BM25 as the sparse component. [snippet] — [Weaviate sparse vectors card](https://weaviate.io/learn/knowledgecards/sparse-vectors), [Hybrid search explained](https://weaviate.io/blog/hybrid-search-explained)

### Gaps
- I did not find release notes confirming or ruling out a native SPLADE/sparse-vector type in Weaviate 1.3x (2025–2026). Treat this as unverified.

---

## pgvector `sparsevec`

### Takeaway
`sparsevec` is indexable only with HNSW, up to 1,000 nnz. Our 85 nnz fits. HNSW pages live in Postgres shared buffers / page cache and are updated through MVCC and vacuum. It is not an inverted index. I found no ≥ 100M sparse numbers.

### Cited Findings
- HNSW on sparsevec supports up to 1,000 non-zero elements. Storage is 8 × nnz + 16 bytes. The docs inconsistently say 16,000 for the type and 1,000 for HNSW. [snippet] — [pgvector #818](https://github.com/pgvector/pgvector/issues/818), [#747](https://github.com/pgvector/pgvector/issues/747), [pgvector README](https://github.com/pgvector/pgvector)

### Updater separability
- The updater is PostgreSQL itself (WAL, MVCC, vacuum). It is not separable. [inferred]

### Gaps
- No ≥ 100M sparsevec benchmark was found. The licence (PostgreSQL licence) was not re-verified this session.

---

## ParadeDB pg_search, tantivy and Quickwit

### Takeaway
Neither tantivy nor pg_search has a learned-sparse / impact field type. However, tantivy's updater (IndexWriter, segments, delete bitsets, merge policy) is an MIT Rust library that our stack already uses for serving. ParadeDB is the clearest real-world precedent of taking tantivy's segment/merge machinery and re-hosting it on a different storage layer (Postgres block storage) in a fork.

### Cited Findings
- ParadeDB maintains "a Postgres-optimized fork of Tantivy". pg_search was migrated to Postgres block storage, "the first-ever extension to port an external file format to Postgres block storage". [snippet] — [paradedb/tantivy](https://github.com/paradedb/tantivy), [ParadeDB block storage blog](https://www.paradedb.com/blog/block-storage-part-one)
- In 2026, the paradedb/tantivy fork added vector fields with "block-major segment storage" (`.vec` format v4, IVF clusters). [snippet] — [paradedb/tantivy PR #269](https://github.com/paradedb/tantivy/pull/269), [paradedb PR #6542](https://github.com/paradedb/paradedb/pull/6542)
- Tantivy lets users write custom Weight/Scorer implementations and reuse its posting infrastructure (old issue #401 on custom scoring). [snippet] — [tantivy issue #401](https://github.com/quickwit-oss/tantivy/issues/401)

### Updater separability
1. The tantivy updater is `IndexWriter` (indexing threads, in-RAM segment writer, commit/flush to immutable segments, `delete_term` → per-segment delete bitsets, `MergePolicy` with LogMergePolicy by default, `SegmentUpdater`). The crate is `tantivy`, MIT. [inferred, background knowledge]
2. It is a library by design. ParadeDB shows that the `Directory` abstraction can be swapped (Postgres blocks). [snippet + inferred]
3. Translation: impacts would have to be stored as quantized term frequencies (u32 tf) per SPLADE token, the Anserini-style "impact" trick. Merged segments would then be read through public postings APIs and turned into SEISMIC blocks. Tantivy's format is documented in-code but changes between major versions. [inferred]
4. Precedent: ParadeDB (tantivy fork re-hosted on another storage layer) and Quickwit (tantivy segments on object storage). Neither does learned-sparse. [snippet/inferred]

### Gaps
- I found no published use of tantivy for SPLADE impact indexes at ≥ 100M.

---

## Turbopuffer and Chroma Cloud (object-storage, proprietary)

### Takeaway
Both now offer learned-sparse retrieval as a hosted service. Turbopuffer has `SparseKNN` with `{}f16` sparse attributes. Chroma Cloud has BM25 and SPLADE via its Search API. Both are proprietary and closed-source, so their updaters cannot be separated. Neither publishes ≥ 100M sparse numbers.

### Cited Findings
- Turbopuffer: "You can use `SparseKNN` to rank by the distance between a sparse vector attribute and a sparse vector query". It is "compatible with FTS operators: `Sum`, `Max`, `Saturate`". [read] — [turbopuffer query docs](https://turbopuffer.com/docs/query). The sparse vector type has string keys and f16 weights (`{}f16`). [snippet] — [turbopuffer write docs](https://turbopuffer.com/docs/write). The announcement post says "sparse vectors a first-class retrieval primitive… no client-side fusion needed for SPLADE / learned-sparse retrievers". It is undated in my results; the status ID suggests roughly mid-2026. [snippet] — [X post](https://x.com/turbopuffer/status/2052759200078733590)
- Chroma: "first class support for BM25 and SPLADE embeddings" in Chroma Cloud via the Search() API. No index details, date or numbers are given. [read] — [Chroma sparse vector page](https://www.trychroma.com/project/sparse-vector-search)

### Gaps
- Index algorithm (exact vs approximate), limits, latency and dates are undocumented for both.

---

## LanceDB, Manticore, PISA

### Takeaway
LanceDB has no sparse-vector support (issue open since 2024-12-10). For Manticore I found no sparse/SPLADE support. PISA is a static-index research engine with no update path [inferred].

### Cited Findings
- LanceDB issue #1930 ("Support for sparse vectors for example SPLADE") is open, opened 2024-12-10, with no linked PRs. [read] — [lancedb #1930](https://github.com/lancedb/lancedb/issues/1930)
- Manticore has dense vector search since 6.3.0 (HNSW). My search found no sparse vector feature. [snippet] — [Manticore vector search manual](https://manual.manticoresearch.com/vector-search)
- PISA builds static compressed indexes (e.g. block-max) offline from a forward index. It has no incremental update or delete. [inferred, background knowledge; not re-verified]

### Gaps
- None of these three has any ≥ 100M learned-sparse RAM numbers.

---

## Is there any published learned-sparse benchmark at ≥ 100M docs with RAM numbers?

### Takeaway
Only one was found: OpenSearch 3.3 SEISMIC at 1.29B docs on 15 nodes, with about 53 GB per node and about 1 GB per 1M docs. That works out to roughly 150 GB for our 150M, held in JVM memory. I found **no** published ≥ 100M learned-sparse benchmark with RAM numbers for Qdrant, Vespa, Elasticsearch, Milvus, Infinity, pgvector, Turbopuffer, Chroma or tantivy.

### Cited Findings
- OpenSearch 3.3: 1,285,526,507 docs, about 53 GB per data node across 15 nodes, P99 27 ms at R@10 90.2%, force merge 2 h 58 m. [read] — [OpenSearch blog](https://opensearch.org/blog/scaling-neural-sparse-search-to-billions-of-vectors-with-approximate-search/)
- Anserini/Pyserini publish SPLADE-v3 Lucene impact indexes for MS MARCO v2.1 segmented docs (about 113–124M passages) with effectiveness numbers. I found no RAM or latency numbers. [snippet] — [Pyserini prebuilt indexes](https://github.com/castorini/pyserini/blob/master/docs/prebuilt-indexes.md)

### Inferences
- In every engine examined that has an updater, the update path is the same: mutable in-RAM tier, then flush to immutable segments, then tombstones, then background merge. Only the immutable tier is ever mmap/page-cache-resident (Qdrant cold/cached, Lucene/ES/OpenSearch rank_features, Milvus sealed mmap, Infinity BMP mmap). The mutable tier is always anonymous RAM, but it is bounded by flush thresholds. [inferred]
- Of the updaters, only Lucene IndexWriter and tantivy IndexWriter are designed and documented as stand-alone libraries with public APIs. Qdrant's is embeddable only as the whole `qdrant-edge` engine. Knowhere is a library, but it has the index only, with no WAL/tombstone/merge logic. [inferred]

### Gaps
- No vendor publishes merge or compaction times for sparse segments at ≥ 100M, except OpenSearch's single force-merge figure.
