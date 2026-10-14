# LSM / segment-based update machinery, per-segment query overhead, and a mutable exact delta tier

**Status:** ACTIVE (research input to the delta_ingest track; compiled 2026-10-02, moved from the repository root `research_notes/`/`reports/` 2026-10-10)

Compiled 2026-10-02. Context: 150M-doc hybrid system (SPLADE via 8 immutable mmap SEISMIC shards + tantivy BM25F + RRF + CE rerank; 16 cores, 32-48 GB RAM, 1x16 GB GPU). Measured: each live delta generation adds ~20-28 ms p50 (target +8 ms/gen). The cost splits into ~11 ms/gen sparse fan-out, ~5 ms/gen lexical per-section parse/merge, and ~5 ms/gen abstract-store probes.

Markers: **[read]** means the source was opened and read (the full page or the extracted PDF text). **[snippet]** means a search-result snippet only. **[inferred]** means my own derivation, with the arithmetic shown. **[local-bench]** means a synthetic micro-benchmark run on this host on 2026-10-02. The script is `/tmp/claude-1000/-workspaces-sfu-library-thinclient/4e24eda4-ae7d-47ca-b274-66a1a52510d4/scratchpad/exact_taat_bench.py`, which is outside the repository and not reproducible from git. The host is an AMD Ryzen 7 5700X3D (8C/16T), and the benchmark ran single-threaded with scipy 1.17.1 and numpy 2.4.3.

Owner scope (added 2026-10-02 mid-task): the goal is to adopt only the **updater** portion of another product (insert/update/delete/merge machinery), possibly through a translation layer, while SEISMIC + tantivy stay the serving engines. The "Updater separability" question below covers this.

---

## Q1. Merge policies and segment-count control in practice (Lucene, ES/OpenSearch, Quickwit, Vespa, Tantivy, Manticore, LSM compaction theory); published latency-vs-segment-count numbers

### Takeaway
Every production engine bounds the live segment count through a size-tiered or log-level merge policy. Typical defaults allow about 10 segments per tier or level and about 8-12 segments per merge. Production deployments also merge tiny segments eagerly because "the small fixed cost of even tiny segments can add up" (Amazon product search). Published per-segment latency numbers are scarce. The best data points are Amazon's ~25% reduction in segments searched per query after merge-on-refresh, and FreshDiskANN's 6 x 5M temp indexes at 0.77 ms each versus 0.89 ms for one 30M index.

### Cited Findings
**Lucene TieredMergePolicy (Lucene 9.12 javadoc)** [read]. Defaults:
- segmentsPerTier = 10.0
- maxMergeAtOnce = 10
- maxMergedSegmentMB = 5 GB
- floorSegmentMB = 2 MB
- deletesPctAllowed = 20
- forceMergeDeletesPctAllowed = 10%

TMP differs from LogByteSizeMergePolicy in three ways. It can "merge non-adjacent segment[s]", it "separates how many segments are merged at once from how many segments are allowed per tier", and it "does not over-merge (that is, cascade merges)". Source: [Lucene TMP javadoc 9.12](https://lucene.apache.org/core/9_12_0/core/org/apache/lucene/index/TieredMergePolicy.html).

**Lucene merge-on-refresh/commit (Lucene 8.7.0, `IndexWriterConfig.setMaxFullFlushMergeWaitMillis`)** [read]:
- Purpose: merge tiny segments during commit/refresh so that the published point-in-time never references them.
- Per-segment fixed query cost: "initializing a Scorer for that query and segment, looking up terms in the segment's term dictionary", plus object allocation and IO cloning.
- At Amazon product search (100% of customer-facing queries on Lucene), "the small fixed cost of even tiny segments can add up".
- Result: a "~25% reduction in average segment counts searched per-query, along with a big reduction in segment count variance".
- No per-segment ms figure is published.

Source: [McCandless, 2021-03-19](https://blog.mikemccandless.com/2021/03/open-source-collaboration-or-how-we.html).

**Elasticsearch** [snippet]:
- "The more segments you have to search through, the slower the search".
- The default 1 s refresh creates one new segment per second per active shard.
- Force-merging to one segment can enable "simpler and more efficient data structures".
- No official latency-vs-segment-count curve was found.
- Sources: [ES force-merge docs](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-indices-forcemerge); [ILM forcemerge](https://www.elastic.co/docs/reference/elasticsearch/index-lifecycle-actions/ilm-forcemerge).
- A third-party blog claims p99 dropped from 120 to 45 ms with refresh_interval 30 s + a larger buffer + merge max_thread_count 1. Its quality is unverified and it is not a primary source: [markaicode](https://markaicode.com/benchmarks/elasticsearch-production-benchmark-latency/) [snippet].

**Quickwit StableLogMergePolicy** [read]:
- Defaults: merge_factor 10, max_merge_factor 12, min_level_num_docs 100,000, maturation_period 48h, split_num_docs_target 10,000,000. Source: [Quickwit index configuration](https://quickwit.io/docs/configuration/index-config).
- Source code: splits are sorted by recency and assigned to levels where `l_0 = 3 x min_level_num_docs` and `l_N = min(num_docs(split)*3, split_num_docs_target)`, so each level is at least 3x the previous one, giving a log scale. A split stops merging once it is mature (reaches the target size, or is older than maturation_period). Source: [stable_log_merge_policy.rs](https://github.com/quickwit-oss/quickwit/blob/main/quickwit/quickwit-indexing/src/merge_policy/stable_log_merge_policy.rs).
- The docs only say that shorter commit timeouts produce smaller splits and more merge overhead. No published search-latency-vs-split-count number was found [read].

**Tantivy LogMergePolicy (tantivy main, source read 2026-10-02)** [read]. Defaults:
- DEFAULT_MIN_NUM_SEGMENTS_IN_MERGE = 8
- DEFAULT_MAX_DOCS_BEFORE_MERGE = 10,000,000
- DEFAULT_MIN_LAYER_SIZE = 10,000
- DEFAULT_LEVEL_LOG_SIZE = 0.75
- DEFAULT_DEL_DOCS_RATIO_BEFORE_MERGE = 1.0

The source comment on the last default says: "The default value of 1 means that deletes are not taken in account ... not a very sensible default". Levels are computed from log2 of num_docs. Source: [log_merge_policy.rs](https://github.com/quickwit-oss/tantivy/blob/main/src/indexer/log_merge_policy.rs).

**Vespa proton** [read]:
- One in-memory index per field is updated on every write. A flush writes it to a new disk index and triggers "disk index fusion" into the primary disk index.
- "A high feed rate can cause multiple smaller flushed indices", which is a symptom of the memory index being too small. The fix is to raise `flushstrategy > native > component > maxmemorygain` [snippet].
- Fusion temporarily needs 2x disk for that index.
- LID-space compaction triggers at more than 1% bloat.
- Sources: [Vespa proton](https://docs.vespa.ai/en/proton.html); [services-content](https://docs.vespa.ai/en/reference/applications/services/content.html) [snippet].
- No published latency-vs-number-of-disk-indexes figure was found.

**Manticore RT tables** [read/snippet]:
- One RAM chunk takes all changes. Its size is governed by `rt_mem_limit`, which defaults to 128M; the RAM chunk is about 50% of rt_mem_limit [read].
- When the limit is hit, the RAM chunk is flushed to a disk chunk. When there are too many disk chunks, auto-OPTIMIZE merges them down to `optimize_cutoff`.
- Automatic compaction never merges below 2 disk chunks unless optimize_cutoff is set to 1 [snippet].
- The manual says to keep the chunk count under control and to make rt_mem_limit large to "minimize ... index fragmentation (number of disk chunks)" [snippet].
- No latency numbers are published.
- Sources: [optimize_cutoff](https://manual.manticoresearch.com/optimize_cutoff); [compacting](https://manual.manticoresearch.com/Securing_and_compacting_a_table/Compacting_a_table).

**OpenSearch concurrent segment search (GA in 2.12; blog updated 2025-10-03)** [read]:
- Theoretical gain is about 50% lower shard latency per doubling of concurrency.
- 1 shard, 1 client, Lucene default slices: big5 range-auto-date-histo p90 dropped from 21,757 to 4,178 ms, and nyc_taxis distance_amount_agg from 12,403 to 2,921 ms.
- CPU overhead with 1 client: +3% (2 slices), +6% (4 slices), +33% (Lucene default slices). With 8 clients, Lucene default slices reach 100% CPU, and going from 4 slices to default slices gives "0%" improvement.
- Listed per-slice overheads: thread-pool queueing, CPU multiplexing, duplicate per-slice work, and a "sequential reduce phase".
- Source: [OpenSearch CSS follow-up](https://opensearch.org/blog/concurrent-search-follow-up/).

**FreshDiskANN (2021)** [read]:
- "A typical set up for a billion-point index would hold up to 30M points in the TempIndex between merges".
- "Limiting each in-memory index to 5M points results in at most 6 instances TempIndex which can each be searched in 0.77ms, compared to 0.89ms needed to search a single 30M size index".
- The authors note that searching small temp indexes "is not the rate limiting step" (the large LTI is), but "creating too many could lead to inefficient search".
- Rebuilding the RW-TempIndex from the log on 48 cores takes about 2.5 min at 5M points versus 16 min at 30M.
- Source: [arXiv 2105.09613](https://arxiv.org/pdf/2105.09613).

**LSM theory (Dostoevsky, SIGMOD 2018; Monkey)** [snippet]:
- Lazy leveling uses tiering at the smaller levels and leveling at the largest level. It keeps the leveling point-lookup and space-amplification bounds while cutting write cost from O(T*L/B) to O(T/B + L/B).
- With Monkey-tuned Bloom filters, point lookup cost is dominated by the largest level.
- Read amplification is the number of sorted runs probed. Tiering at level i allows up to T-1 runs per level.
- Sources: [Dostoevsky PDF](https://nivdayan.github.io/dostoevsky.pdf); [LSM survey](https://arxiv.org/pdf/1812.07527).

### Inferences
- [inferred] Default fan-in bounds the live count. Lucene TMP allows about 10 segments per tier. If the delta tier is one log-tier above a fixed base (deltas of 20k-500k docs against the 2 MB floor), Lucene-like defaults would allow up to about 10 small segments before a merge. That matches the regime where this system's +20-28 ms/gen becomes +200-280 ms.
- [inferred] Amazon, FreshDiskANN and Manticore all bound small segments and merge them early instead of making per-segment search cheaper. None of them publishes a per-segment cost as high as ~20 ms. FreshDiskANN's small-index search costs are about 0.8 ms each, which is 25x below this system's measured per-generation cost.
- [inferred] Dostoevsky's point-lookup analysis assumes Bloom filters, which avoid probing runs that lack the key. A top-k scored query over posting lists has no Bloom-filter shortcut: every run that holds postings for the query terms must be scanned. Ranked retrieval therefore pays the full tiering read amplification, so the "lazy leveling keeps reads cheap" result does not carry over to scored search.

### Gaps
- I found no official Elastic or Lucene published curve of query latency versus segment count. McCandless gives a qualitative description and the 25% segment-count reduction only.
- Quickwit's statements on "too many splits" for search latency are not quantified in the docs I read.
- I did not read the Vespa flushstrategy default values (maxmemorygain, maxage); I have snippet only.

---

## Q2. How engines search small segments cheaply

### Takeaway
Lucene amortizes per-segment cost in several ways:
- It builds one `Weight` per query per searcher. Term statistics are aggregated across segments, and only the Scorer is per-segment.
- It groups small segments into slices of at most 5 segments or 250k docs, which run serially in one task.
- It shares a minimum competitive score across slices (`MaxScoreAccumulator`), so later or smaller segments are pruned against the global top-k threshold.
- It merges tiny segments at refresh.

### Cited Findings
- **Lucene `IndexSearcher` slicing (main branch source, read 2026-10-02)** [read]:
  - `MAX_DOCS_PER_SLICE = 250_000` and `MAX_SEGMENTS_PER_SLICE = 5`.
  - "Each LeafSlice is executed in a single thread. By default, segments with more than MAX_DOCS_PER_SLICE will get their own thread." Small segments are therefore packed up to 5 per slice and searched sequentially in one task.
  - Intra-segment partitioning exists but is off by default because of "a performance penalty for queries that require segment-level computation ahead of time".
  - `TOTAL_HITS_THRESHOLD = 1000`: hits are counted exactly only up to 1000, so time is not spent on counting.
  - Source: [IndexSearcher.java](https://github.com/apache/lucene/blob/main/lucene/core/src/java/org/apache/lucene/search/IndexSearcher.java).
- **Shared min-competitive score across segments in concurrent search (LUCENE-8992)** [snippet]:
  - `createSharedManager` creates a CollectorManager with a shared hit counter and "a shared MaxScoreAccumulator to propagate the minimum score across segments".
  - It applies only when the primary sort is `_score` descending.
  - Elasticsearch ESQL extended sharing of collector managers across operators (PR 142406) so that "scoring can have updated min competitive information".
  - Sources: [lucene-solr PR 904](https://github.com/apache/lucene-solr/pull/904); [ES PR 142406](https://github.com/elastic/elasticsearch/pull/142406).
- **Per-segment fixed cost** [read]: Scorer initialization, a terms-dictionary lookup per query term per segment, object allocation and IO cloning. For tiny segments "the cost can be significant" relative to postings iteration. Source: [McCandless 2021](https://blog.mikemccandless.com/2021/03/open-source-collaboration-or-how-we.html).
- **Global stats.** The Lucene IndexSearcher javadoc says it "Creates a Weight for the given query", once per query [read, partial]. IDF from a single searcher spans all its segments.
  - [inferred, not re-verified this session] This is the mechanism by which per-segment BM25 avoids per-segment IDF skew. Elasticsearch's `dfs_query_then_fetch` extends the same idea across shards.
- **OpenSearch** [read]: the reduce phase across slices is sequential, and more slices mean more "duplicate work". Source: [OpenSearch CSS](https://opensearch.org/blog/concurrent-search-follow-up/).
- **FreshDiskANN** [read]: the search fans out to the long-term index (LTI), the RW-TempIndex and every RO-TempIndex "with parameters K and L", aggregates the results, and filters the DeleteList. Each small temp index gets the full K/L, with no shared threshold. Source: [FreshDiskANN](https://arxiv.org/pdf/2105.09613).

### Inferences
- [inferred] Lucene equivalents of the three measured cost buckets:
  - Lexical per-section parse/merge (~5 ms/gen): Lucene parses and builds the Weight once and only re-runs term lookups per segment. A tantivy `Searcher` over all segments of one index does the same. Running a separate query parse/search per section corresponds to the anti-pattern.
  - Sparse fan-out (~11 ms/gen): Lucene would put all segments under 250k docs into at most one slice per 5 segments. Unlike FreshDiskANN, it would prune them with the shared threshold.
  - Abstract-store probes (~5 ms/gen): no direct analogue. Lucene fetches stored fields only for the final top-k, once per hit, from the owning segment.
- [inferred] A shared min-competitive score helps only if the delta is scored after the base (or concurrently with a shared accumulator) and the delta's scorer can skip by block max. With an exact brute-force delta, skipping is not needed when the delta is small (see Q4).

### Gaps
- I found no published Lucene number for the per-segment fixed cost in microseconds.
- I did not verify tantivy's equivalents (one `Weight` per Searcher across segments; whether tantivy shares a top-k threshold across segments in multi-segment collection) from source this session.

---

## Q3. The "one mutable in-memory tier with exact search" pattern: allowed size and latency impact

### Takeaway
Most engines keep exactly one mutable tier searched without an approximate index, and seal or index it at a fixed size threshold:
- Qdrant: 10,000 KB of vectors (about 10k vectors at 256-d float32).
- Milvus: about 123 MB per growing segment, with an interim IVF index since v2.3.4.
- Turbopuffer: the unindexed WAL tail.
- LanceDB: guidance to optimize after about 100k changed rows.
- Manticore and Vespa: one RAM chunk or memory index.
- FreshDiskANN: one RW-TempIndex of up to about 5M points.

For sparse vectors specifically, Qdrant's mutable sparse index is an exact inverted index. Published latency impact numbers are sparse. The concrete ones are Turbopuffer's "~10 ms for consistent read" of unindexed WAL, and FreshDiskANN's 0.77 ms per 5M temp index.

### Cited Findings
- **Qdrant (config/config.yaml on master, read 2026-10-02)** [read]:
  - `indexing_threshold_kb: 10000` ("1Kb = 1 vector of size 256").
  - `full_scan_threshold_kb: 10000`, below which "full-scan search instead of HNSW".
  - `deleted_threshold: 0.2`, `vacuum_min_vector_number: 1000`, `flush_interval_sec: 5`.
  - `default_segment_number: 0`, meaning auto by CPU count, "so that each segment would be handled evenly by one of the threads".
  - Source: [qdrant config.yaml](https://github.com/qdrant/qdrant/blob/master/config/config.yaml).
  - Below the indexing threshold Qdrant "searches the segment without HNSW" [snippet]: [Qdrant optimizer docs](https://qdrant.tech/documentation/concepts/optimizer/). Two direct fetches of this page failed.
  - Sparse vectors: "A sparse vector index in Qdrant is exact"; "All sparse vectors added to the collection are immediately indexed in the mutable version of a sparse index" [snippet]: [Qdrant indexing](https://qdrant.tech/documentation/concepts/indexing/).
- **Milvus** [snippet]:
  - Growing segments are in memory and searched by brute force.
  - Since v2.3.4, an interim (temp) IVF index on growing segments kicks in once the row count exceeds a threshold (`queryNode.segcore.interimIndex.enableIndex`, default true).
  - Seal threshold = `dataCoord.segment.maxSize` (1024 MB) x `sealProportion` (0.12), which is about 123 MB.
  - Sparse fields support only SPARSE_INVERTED_INDEX / SPARSE_WAND.
  - The interim index "occupies CPU resources, which can affect search latency".
  - Sources: [datacoord configuration](https://milvus.io/docs/configure_datacoord.md); [discussion 41890](https://github.com/milvus-io/milvus/discussions/41890); [discussion 35554](https://github.com/milvus-io/milvus/discussions/35554); [sparse index](https://milvus.io/docs/sparse-inverted-index.md).
  - No latency numbers for brute-force growing-segment search were found.
- **Turbopuffer (architecture doc)** [read]:
  - Every write adds a WAL file. There is 1 WAL entry per second per namespace, and concurrent writes are batched. Write latency is "p50=165ms for 500kB".
  - Unindexed data "is still available to search, with a slower exhaustive search of recent data in the log", at "~10ms for consistent read".
  - Queries: cold p50 874 ms and warm p50 14 ms at 1M docs.
  - The doc publishes no explicit cap on unindexed size.
  - Source: [turbopuffer architecture](https://turbopuffer.com/docs/architecture).
- **LanceDB** [snippet]:
  - Queries combine index results with "exhaustive/flat search on the new data", which "does come at a performance cost".
  - `fast_search=True` skips unindexed rows. `index_stats()` reports the unindexed count.
  - Rule of thumb: call `optimize()` after about 100,000 row changes or 20 modification operations.
  - Sources: [LanceDB reindexing](https://docs.lancedb.com/indexing/reindexing); [vector search](https://docs.lancedb.com/search/vector-search).
  - No latency-vs-unindexed-rows curve is published.
- **FreshDiskANN** [read]:
  - One mutable RW-TempIndex, periodically frozen to an RO-TempIndex and snapshotted.
  - StreamingMerge runs when the total RO-TempIndex memory exceeds a threshold. A typical configuration holds up to 30M points (on a ~1B index) in temp indexes, in instances of 5M or fewer.
  - Mean search latency is about 5 ms with no merge running and about 15 ms during StreamingMerge (800M-point ramp-up).
  - Throughput: 1000 searches/s at 95%+ 5-recall@5 with mean latency "well under 20ms"; 1,800 inserts/s plus 1,800 deletes/s steady state; insert/delete latency under 1 ms.
  - StreamingMerge applies a 10% change in about 10% of rebuild time.
  - Source: [FreshDiskANN](https://arxiv.org/pdf/2105.09613).
- **Vespa** [read]: the memory index is updated per write and flushed to disk indexes that are fused. Its size is governed by flushstrategy. Source: [Vespa proton](https://docs.vespa.ai/en/proton.html).
- **Manticore** [read]: the RAM chunk is about 50% of `rt_mem_limit`, which defaults to 128M. Source: [Manticore](https://manual.manticoresearch.com/optimize_cutoff).
- **Linscan / Sinnamon (Bruch et al., TOIS 2023)** [read]:
  - Designed explicitly for streaming sparse vectors with online inserts and deletes.
  - LinScan is an uncompressed inverted index (u32 doc id + f32 value) with coordinate-at-a-time accumulation.
  - "Both algorithms are fast on modern CPUs due to predictable and regular memory access patterns", and they parallelize over one monolithic structure with no sharding.
  - LinScan-Roaring (compressed) has "latency [that] tends to increase substantially".
  - Deletion: LinScan removes the id from the inverted index. Sinnamon deletes "about an order of magnitude faster" than LinScan-Roaring.
  - Hardware: 8-core Xeon Ice Lake 2.6 GHz and Apple M1 Pro.
  - LinScan exact latencies are given in log-scale figures only (SPLADE axis 10-1000 ms at k=1000 on 8.8M). No table of exact LinScan latency was found in the text.
  - Source: [arXiv 2301.10622](https://arxiv.org/abs/2301.10622).

### Inferences
- [inferred] Size caps, converted:
  - Qdrant 10,000 KB / (256 x 4 B) is about 10k dense vectors.
  - Milvus 123 MB / (768 x 4 B) is about 40k 768-d vectors.
  - FreshDiskANN allows 5M per instance and 30M in total, but those are graph-indexed temp indexes, not brute force.
  - The only brute-force tiers with numbers (Qdrant, Milvus pre-interim) are capped at tens of thousands of rows. The documented caps on purely brute-force tiers are 1-2 orders of magnitude below this system's 20k-500k-doc generations.
  - Sparse is the exception: Qdrant's mutable sparse tier is exact and uncapped, because an exact inverted index is the index.
- [inferred] Turbopuffer, LanceDB, Milvus and Qdrant all make one unindexed tier per collection or partition, not N of them. N grows only in the sealed-and-indexed tier, where merge policies bound it.

### Gaps
- No vendor publishes latency as a function of brute-force-tier size (Turbopuffer, LanceDB, Milvus, Qdrant).
- I found no explicit Turbopuffer cap on unindexed WAL bytes.
- Elasticsearch indexing-buffer defaults (`indices.memory.index_buffer_size`) were not verified this session.

---

## Q4. Cost of brute-force exact sparse dot-product over a small delta (CPU and GPU)

### Takeaway
Exact sparse top-k over SPLADE is linear in the postings touched. On published single-thread CPU numbers, it scales to about 11-34 ms per query at 1M docs. A local single-thread synthetic run measured about 10-23 ms at 1M docs and about 2 ms at 100k. On GPU at batch 1, it is about 0.3 ms at 100k and 9.6 ms at 8.8M (H100, preprint). An uncompressed exact index over 1M x 85-nnz docs is about 85M postings, which is about 680 MB at u32 id + f32 value.

### Cited Findings
- **PISA, exact (block-max WAND, rank-safe)**, SPLADE on MS MARCO (8.8M passages), single thread, i9-9900K 3.6 GHz: "about 100,325 microseconds". On E-SPLADE it is 7,947 µs and on uniCOIL-T5 9,214 µs. IOQP (impact-ordered) is the slowest approximate baseline: about 17-51 ms SPLADE across 90-97% accuracy. Seismic is 84.6x faster than IOQP at matched accuracy. [read] Source: [Seismic, SIGIR 2024, arXiv 2404.18812](https://arxiv.org/abs/2404.18812).
- **Pyserini exact SPLADE**: 298 ms per query single-threaded at 8.8M (3.4 QPS). [read] Source: [GPUSparse, arXiv 2606.26441 (June 2026 preprint, not peer-reviewed)](https://arxiv.org/html/2606.26441).
- **GPUSparse (H100 80 GB, exact SPLADE, MS MARCO)** [read]:
  - Per-query latency amortized at batch 500: 15 µs at 100K, 786 µs at 1M, 1.27 ms at 8.8M.
  - Batch = 1: 331 µs at 100K, 9.6 ms at 8.8M.
  - Index memory 8.5 GB at 8.8M. Peak at batch 500 is 44 GB because of score buffers.
  - The cuSPARSE SpMV baseline took 46.2 ms for 500 queries at 100K.
  - Quality matches Pyserini (MRR@10 0.383, R@1000 0.983).
  - Source: [GPUSparse](https://arxiv.org/html/2606.26441).
- **BigANN NeurIPS'23 sparse track** [read]:
  - Dataset: MS MARCO SPLADE, 8,841,823 docs, about 120 nnz/doc, about 49 nnz/query.
  - Hardware: Azure D8lds_v5, 8 vCPU, 16 GB RAM.
  - The linscan baseline used "an efficient linear scan of an inverted index" with query-term pruning (approximate) and reached 95 QPS private / 93 QPS public at recall@10 ≥ 0.9.
  - Winners at the same bar: pyanns 6,500 / 8,732 QPS; shnsw 5,078 / 7,137 QPS.
  - Source: [BigANN'23 results, arXiv 2409.17424](https://arxiv.org/pdf/2409.17424).
- **LinScan design** [read]: uncompressed u32 id + f32 value postings, coordinate-at-a-time, parallel over one monolithic index. Measured SPLADE: ψd = 119 nnz/doc and ψq = 43 nnz/query on MS MARCO. Source: [Bruch et al.](https://arxiv.org/abs/2301.10622).
- **Local synthetic benchmark** [local-bench]:
  - Setup: single thread, scipy CSC column-slice plus `X[:,q] @ w` plus `argpartition` top-1000. Vocabulary 30,522; 85 sampled terms per doc with Zipf-like term frequencies; 64-term queries drawn from the same distribution; 30 queries per size.

  | Docs | Zipf s | Postings stored | Postings touched (p50) | TAAT p50 / p90 | Full CSR SpMV over all postings, p50 | CSC memory |
  |---|---|---|---|---|---|---|
  | 100k | 0.8 | 8.0M | 0.44M | 1.79 / 2.9 ms | 5.4 ms | 61 MB |
  | 1M | 0.8 | 80.4M | 4.18M (5.2%) | 9.57 / 10.9 ms | 56.9 ms | 614 MB |
  | 3M | 0.8 | 241M | 13.2M | 37.8 / 76.3 ms | 172 ms | 1.84 GB |
  | 100k | 1.1 | 5.8M | 1.05M | 1.98 / 4.95 ms | 4.0 ms | 44 MB |
  | 1M | 1.1 | 57.8M | 10.1M (17%) | 22.6 / 27.4 ms | 41.6 ms | 441 MB |

  At s = 1.1, duplicate draws reduce the average to about 58 nnz/doc. The full-SpMV column is a worst-case bound in which every posting is touched, which works out to about 1.4 G postings/s per core.

### Inferences
- [inferred] Linear scaling of the published exact CPU numbers to delta sizes (N/8.8M):

  | Docs | PISA (100.3 ms at 8.8M) | Pyserini (298 ms at 8.8M) |
  |---|---|---|
  | 100k | 1.14 ms | about 3.4 ms |
  | 500k | 5.7 ms | about 17 ms |
  | 1M | 11.4 ms | about 34 ms |
  | 5M | 57 ms | about 169 ms |

  PISA's block-max WAND is not strictly linear, so these are order-of-magnitude figures.
- [inferred] Memory for an uncompressed exact index:

  | Docs | Postings | u32 id + f32 value | u32 + u16 value |
  |---|---|---|---|
  | 1M | 85M | 680 MB | 510 MB |
  | 5M | 425M | 3.4 GB | 2.55 GB |

  Add a dense score accumulator of 4 B x N per in-flight query: 4 MB at 1M, 20 MB at 5M.
- [inferred] Threading: on 16 cores, coordinate-at-a-time over one monolithic index parallelizes by splitting query terms or doc ranges. LinScan claims this without sharding, but the Sinnamon table shows sub-linear speedup: 4.35-4.68x at 8 threads. At about 4x, the 1M single-thread figure of about 10-23 ms (local) or about 11 ms (PISA-scaled) becomes about 3-6 ms.
- [inferred] Comparison to the measured ~11 ms/gen fan-out:
  - One exact tier of about 500k docs costs about 5-12 ms single-thread (local-bench interpolation; PISA-scaled 5.7 ms). That is about the cost of one SEISMIC delta generation today, but it is paid once rather than per generation.
  - At 1M docs, about 10-23 ms single-thread.
  - Beyond about 3M, single-thread exact cost (about 38-170 ms) dominates unless the tier is threaded or moved to GPU.
- [inferred] GPU batch-1 at 1M: interpolated between 331 µs (100k) and 9.6 ms (8.8M), roughly 1-2 ms on H100. Memory scales at about 8.5 GB per 8.8M docs, so about 1 GB per 1M docs. A 16 GB consumer GPU has lower bandwidth than an H100's 3.35 TB/s, so expect slower. No 16 GB-GPU number is published.

### Gaps
- No published table gives LinScan's exact (unpruned) SPLADE latency. It appears in log-scale figures only.
- The term-skew and postings-touched fraction for this system's own SPLADE model on 64-term queries was not measured here. The local benchmark is synthetic (Zipf 0.8 and 1.1), so real cost could sit outside the 5-17% touched range.
- GPUSparse is a June 2026 preprint and its numbers are unreplicated.

---

## Q5. LSM key-value stores as posting-list stores

### Takeaway
KV-backed inverted indexes exist in production, but ranked top-k over them is shown only for BM25 and only with a block layout and block-max pruning:
- Turbopuffer FTS v2: about 256-posting blocks in an LSM on object storage, with vectorized MAXSCORE.
- Rockset: Elias-Fano posting lists in RocksDB, used for predicates.
- CockroachDB GIN on Pebble: boolean only, with ranking done afterwards.

I found no published learned-sparse (SPLADE) top-k latency on an LSM KV store, and no system near 12.8B scored postings on one.

### Cited Findings
- **Turbopuffer FTS v2 (blog, January 2026 numbers)** [read]:
  - Postings are stored as KV pairs in their LSM tree on object storage, in fixed blocks of about 256 postings. A block splits above 512 and merges with a neighbor below 128.
  - Postings are bitpacked in 128-posting frames using Quickwit's bitpacking, decoding at about 741M postings/s per core (about 4.5 GB/s) versus Zstd at about 1 GB/s.
  - v1 aligned postings to vector clusters and got a median of about 1.5 postings per partition (p90 about 11).
  - Size on 40M MS MARCO docs: 51.6 GiB (v1) versus 5.22 GiB (v2).
  - Latency on 5M Wikipedia docs, k=100, with vectorized MAXSCORE block skipping:

    | Query | v1 | v2 |
    |---|---|---|
    | "san francisco" | 8 ms | 3 ms |
    | "the who" | 57 ms | 7 ms |
    | "lord of the rings" | 75 ms | 6 ms |
    | 5-term query | 174 ms | 20 ms |

  - Source: [turbopuffer FTS v2 postings](https://turbopuffer.com/blog/fts-v2-postings).
- **Rockset Converged Index** [snippet]:
  - Row, column and search indexes are all built on a KV abstraction (RocksDB, "but any key-value store will do").
  - The inverted index is stored as KV posting lists with prefix compression and Elias-Fano. It serves "sub-millisecond point lookups" and predicate retrieval.
  - Rockset aims for ms-latency at thousands of QPS per leaf while applying updates.
  - No ranked (score-sum) retrieval numbers are given.
  - Sources: [Rockset converged index](https://medium.com/rocksetcloud/how-rocksets-converged-index-powers-real-time-analytics-c6c2e6066d9e); [How we use RocksDB at Rockset](https://rockset.com/blog/how-we-use-rocksdb-at-rockset/).
- **CockroachDB** [snippet]: GIN / inverted indexes on Pebble (a RocksDB derivative) accelerate match predicates. Ranking via `ts_rank` is applied to the results, and the index "won't be used to accelerate" some ranking queries. Source: [CockroachDB FTS v26.2](https://www.cockroachlabs.com/docs/v26.2/full-text-search).
- **RocksDB Merge Operator wiki** [read]:
  - `MergeOperator` has FullMerge plus optional PartialMerge; `AssociativeMergeOperator` is the simple form.
  - Merges are applied lazily, "the next time the user calls Get(), or ... Compaction".
  - This lets posting appends avoid read-modify-write.
  - The wiki page gives no numbers on read cost with many stacked operands.
  - Source: [RocksDB Merge Operator](https://github.com/facebook/rocksdb/wiki/Merge-Operator).
- **Sinnamon / LinScan** treat insert as an append to each term's posting list [read]. This is the operation a merge operator would serve. Source: [Bruch et al.](https://arxiv.org/abs/2301.10622).

### Inferences
- [inferred] Scale arithmetic for 12.8B postings:
  - At 8 B per posting (u32 id + f32) that is about 102 GB raw. At Turbopuffer v2's ratio (5.22 GiB for 40M docs) it is roughly 1.2 B per posting for BM25 tf data, but SPLADE carries real-valued weights.
  - A block layout of about 256 postings per KV gives about 50M KV entries ([inferred] 12.8e9 / 256).
  - Exact score-sum over 64 SPLADE query terms must read every block of every query term unless block-max pruning applies. SEISMIC exists because exact or rank-safe traversal of SPLADE at 8.8M already costs about 100 ms (PISA).
  - An LSM adds per-level read amplification on top: every run holding blocks for a term must be read.
- [inferred] Every KV-backed inverted index found uses the KV for storage or boolean retrieval, plus a block-max (MAXSCORE) scorer layered above it. None publishes learned-sparse ranked latency. The LSM is a storage and update layer, not a scorer.

### Gaps
- I found no paper or system with SPLADE / learned-sparse ranked top-k over an LSM KV store.
- I did not obtain Sonic, MyRocks or AsterixDB LSM-inverted-index ranked-latency numbers. AsterixDB's LSM inverted index targets similarity predicates. I did not read it this session.

---

## Q6. Delete and visibility handling costs

### Takeaway
Deletes are universally soft: a bitset or bitmap per segment (Lucene liveDocs, Qdrant deleted bitmaps, FreshDiskANN DeleteList, Vespa removed sub-DB). Reclaim triggers when about 20% of a segment is deleted (Lucene TMP 20%, Qdrant 0.2). For graph ANN indexes, repeated delete and reinsert causes unreachable nodes and a 3% recall drop that ef cannot recover. For exact inverted indexes, deletes cost only skipped work.

### Cited Findings
- **Lucene TMP**: `deletesPctAllowed` default 20 and `forceMergeDeletesPctAllowed` 10% [read]. Source: [TMP javadoc 9.12](https://lucene.apache.org/core/9_12_0/core/org/apache/lucene/index/TieredMergePolicy.html).
- **Tantivy LogMergePolicy**: `del_docs_ratio_before_merge` defaults to 1.0, so deletes never trigger merges by default. The source calls this "not a very sensible default" [read]. Source: [log_merge_policy.rs](https://github.com/quickwit-oss/tantivy/blob/main/src/indexer/log_merge_policy.rs).
- **Qdrant**: vacuum when `deleted_threshold: 0.2` and segment ≥ `vacuum_min_vector_number: 1000` [read]. Source: [qdrant config.yaml](https://github.com/qdrant/qdrant/blob/master/config/config.yaml).
- **FreshDiskANN** [read]:
  - Deletes are added to a DeleteList and filtered from results.
  - StreamingMerge applies them to the graph in place.
  - Recall is stable over StreamingMerge cycles: 80M index with 10% deletes plus inserts per cycle; 800M index with 30M inserts and deletes.
  - Source: [FreshDiskANN](https://arxiv.org/pdf/2105.09613).
- **HNSW markDelete + replaced_update (Xiao et al., 2024)** [snippet]:
  - On SIFT 1M, deleting and reinserting 5% for 3,000 rounds grows unreachable points to 3-4%, with recall@1 down about 3%. Raising ef does not recover it.
  - replaced_update inserts are 5-10x slower on GIST and ImageNet.
  - Their fix keeps unreachable points under 0.2% and recall within 0.5-1% of a fresh build.
  - Source: [arXiv 2407.07871](https://arxiv.org/html/2407.07871v2).
- **SPFresh (SOSP 2023)** [read]:
  - Abstract-level claims: in-place partition updates (LIRE rebalancing) give "2.41x lower tail latency on average" than DiskANN with global rebuild, using 10 GB memory and 2 cores versus DiskANN's additional 1000 GB and 32 cores.
  - Peak 4K QPS search plus 2K QPS update on one NVMe SSD with 15 cores.
  - Workload A: 1% daily updates over 100 days on SPACEV 100M.
  - Source: [SPFresh arXiv 2410.14452](https://arxiv.org/pdf/2410.14452).
- **Vespa**: the removed-documents sub-DB is pruned by a cheap job. LID-space compaction triggers at more than 1% bloat [read]. Source: [Vespa proton](https://docs.vespa.ai/en/proton.html).
- **LinScan**: delete removes the id from the inverted lists. Sinnamon is about 10x faster at deleting than LinScan-Roaring [read]. Source: [Bruch et al.](https://arxiv.org/abs/2301.10622).

### Inferences
- [inferred] For SEISMIC-style approximate shards (fixed blocks, summaries, and a forward index), a deleted doc still occupies its block and summary mass. A deleted doc with high summary score can keep a block "promising" and waste evaluations. This is analogous to HNSW holes, but recall loss comes from top-k slots being consumed only if filtering happens after truncation. No published measurement exists for SEISMIC with X% deleted.
- [inferred] Industry reclaim thresholds (20%) imply that up to about 20% dead postings is tolerated per segment before rewrite.

### Gaps
- I found no published SEISMIC, or learned-sparse approximate-index, recall/latency curve versus deleted fraction.
- I did not find a published number for live-docs bitset check cost per hit in Lucene. It is generally treated as negligible, which is not cited here.

---

## Q7. Updater separability: can another product's insert/update/delete/merge machinery manage our segments as opaque payloads?

### Takeaway
Only the merge-selection policies are separable as small pure functions over segment metadata:
- Tantivy `MergePolicy` (MIT).
- Quickwit `MergePolicy` / StableLogMergePolicy (Apache-2.0).
- SlateDB `CompactionScheduler` (Apache-2.0), in principle.

They take a list of (id, num_docs, deletes, time/size) and return groups to merge. Executors, writers, WAL and visibility machinery in every surveyed product are bound to that product's own segment format. No surveyed system offers a format-agnostic "merge these N opaque segments via callback" LSM framework off the shelf.

### Cited Findings
**Tantivy `MergePolicy` (MIT, Rust)** [read]:
- `pub trait MergePolicy: Send + Sync + Debug { fn compute_merge_candidates(&self, segments: &[SegmentMeta]) -> Vec<MergeCandidate>; }`, where `MergeCandidate(pub Vec<SegmentId>)`.
- The trait is called "every time the list of segments changes" on the segment-updater thread and "should happen rapidly".
- LogMergePolicy reads only `num_docs()`, `num_deleted_docs()` and `max_doc()`.
- The executor (SegmentUpdater/IndexMerger) is tantivy-format-specific.
- `SegmentMeta` is a tantivy type created via the index inventory, so reusing it requires constructing tantivy metas or porting about 150 lines.
- Sources: [merge_policy.rs](https://github.com/quickwit-oss/tantivy/blob/main/src/indexer/merge_policy.rs); [log_merge_policy.rs](https://github.com/quickwit-oss/tantivy/blob/main/src/indexer/log_merge_policy.rs). The licence is reported as MIT by the GitHub API.

**Quickwit merge planner (Apache-2.0 per file header "Copyright 2021-Present Datadog, Inc.", Rust)** [read]:
- `trait MergePolicy { fn operations(&self, splits: &mut Vec<SplitMetadata>) -> Vec<MergeOperation>; fn finalize_operations(..); fn split_maturity(&self, split_num_docs: usize, split_num_merge_ops: usize) -> SplitMaturity; }`.
- Input is `quickwit_metastore::SplitMetadata` (num_docs, time range, maturity, ...).
- The merge executor downloads and merges tantivy splits, so it is format-bound.
- Source: [quickwit merge_policy/mod.rs](https://github.com/quickwit-oss/quickwit/blob/main/quickwit/quickwit-indexing/src/merge_policy/mod.rs).
- GitHub reports the repository licence as Apache-2.0 [read].

**Lucene** [inferred, from prior knowledge, not re-read this session]:
- `MergePolicy.findMerges(MergeTrigger, SegmentInfos, MergeContext)` operates on Lucene `SegmentCommitInfo`. `IndexWriter` owns flush, merge execution, liveDocs and commit points.
- Java, Apache-2.0.
- Not usable standalone over non-Lucene segments without fabricating SegmentInfos.
- The TMP defaults themselves are [read] (Q1).

**SlateDB (Apache-2.0 per GitHub API, Rust)** [read]:
- `trait CompactionScheduler { fn start(&self, executor: Box<dyn CompactionExecutor>, chan: Receiver<CompactorUpdate>); }`. It receives DB-state updates (new L0 files, compaction finished) and decides which sorted runs to compact.
- The executor "handles sort-merging key-values" with newest-wins and drops tombstones at the last level. It is KV/SST-format bound.
- Source: [SlateDB RFC 0002](https://github.com/slatedb/slatedb/blob/main/rfcs/0002-compaction.md).

**fjall / lsm-tree (Rust)** [snippet]: a KV LSM with compaction strategies and (since 3.1) compaction filters for custom logic during compaction. Its data model is KV, so it cannot hold opaque index segments. Source: [fjall lsm-tree](https://github.com/fjall-rs/lsm-tree). GitHub reports Apache-2.0 [read].

**RocksDB (C++)** [read/inferred]:
- Compaction styles plus user `MergeOperator` / compaction filters, operating on ordered KV SSTs [read: merge operator wiki].
- Licence: GitHub API reports GPL-2.0 for the primary licence file. The repository is dual-licensed GPLv2 / Apache-2.0 [inferred from repository layout, not re-read].
- Usable as an opaque-blob store but not as a manager of externally built index segments.

**Formats bound to their own engines** [inferred from the architecture docs read above; none is shipped as a standalone library]:
- Vespa proton flush/fusion is C++ internal (Apache-2.0).
- Qdrant optimizer and appendable segments are Rust internal (Apache-2.0).
- Milvus growing/sealed segments plus datacoord compaction are Go (Apache-2.0).
- Lance/LanceDB compaction/optimize is Rust, Lance format (Apache-2.0).
- FreshDiskANN StreamingMerge is Vamana-graph-specific [read].

### Inferences
- [inferred] Interface a format-agnostic generation manager would need from our side, distilled from the traits above:
  1. A metadata view per generation: id, num_docs, num_deleted, bytes, creation time / level, merge-op count.
  2. A `merge(gen_ids) -> new_gen` callback that our code implements by rebuilding one SEISMIC shard plus one tantivy section plus SQLite rows and the abstract store.
  3. A delete-bitmap or newest-wins resolution hook.
  4. An atomic manifest swap.

  Policy pieces 1 and 2 are directly expressible with Tantivy's or Quickwit's policy traits (both take metadata and return groups). Pieces 3 and 4 are not provided by any separable component found.
- [inferred] A translation layer that encodes our SPLADE docs into another engine's segment format (for example Qdrant sparse segments or Milvus sparse) would hand serving to that engine for the delta. It would not plug into SEISMIC/tantivy, because the executors write only their own formats.

### Gaps
- I did not check whether Quickwit's `quickwit-indexing` crate builds as a library without the full Quickwit dependency graph.
- I did not check whether any Rust crate offers a generic "LSM of opaque segments" (manifest plus merge-policy plus callback) outside KV stores. None turned up in these searches.
- I did not read the Lucene MergePolicy signature this session.
