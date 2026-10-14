# OpenSearch neural sparse ANN (SEISMIC inside Lucene segments): update/merge design and reusability for standalone Rust SEISMIC

**Status:** ACTIVE (research input to the delta_ingest track; compiled 2026-10-02, moved from the repository root `research_notes/`/`reports/` 2026-10-10)

Researched 2026-10-02. Tags: [read] = I opened and read the source (for code: shallow clone of the repository's default branch on 2026-10-02); [snippet] = search-result snippet or tool summary only; [inferred] = my reasoning from read material.

Code snapshots read:
- opensearch-project/neural-search @ `67ab3ca73cbb` (2026-10-01, "Increment version to 3.10.0-SNAPSHOT"). Paths below are relative to `source/main/java/org/opensearch/neuralsearch/sparse/`.
- opensearch-project/neural-sparse-cpp @ HEAD dated 2026-09-24 (`nsparse/`).
- TusKANNy/seismic @ HEAD dated 2026-09-10.
- Docs read as raw Markdown from opensearch-project/documentation-website `main` (2026-10-02): `_vector-search/ai-search/neural-sparse-ann.md`, `_mappings/supported-field-types/sparse-vector.md`, `_vector-search/performance-tuning-sparse.md`.

## Updater separability (owner's priority question: can we lift ONLY their insert/update/delete/merge machinery into our Rust SEISMIC + tantivy system?)

### Takeaway
No. OpenSearch has no SEISMIC updater to lift. Lucene does all the update work: it buffers new docs into new segments, applies deletes as a per-segment live-docs bitset, and picks merges. The SEISMIC part only builds a fresh, immutable SEISMIC structure for each new segment: once at flush (if the segment is big enough) and once more at every merge, starting again from the merged documents. Nothing in it updates clusters or summaries incrementally. We already do the same thing ourselves: rebuild a shard from its forward vectors. The parts that are worth copying are design ideas, and all of them are small: a size threshold below which a segment stays a plain exact inverted index, live-docs filtering inside the block scan, and per-segment λ = max(0.0005·N, 160) with β = cluster_ratio·λ.

### Cited Findings

**(1) Update path versus query path: which classes do what** [read, neural-search @67ab3ca]
- Ingest / field parse: `mapper/SparseVectorFieldMapper.java`. It stores each document's raw sparse vector as BINARY doc values (`setDocValuesType(DocValuesType.BINARY)`, line 80). For the Lucene engine only, it also emits one Lucene `FeatureField` per token (lines 196-198, `if (!NATIVE...) new FeatureField(...)`). Those form the normal `rank_features` inverted index that small segments use. — https://github.com/opensearch-project/neural-search/blob/main/src/main/java/org/opensearch/neuralsearch/sparse/mapper/SparseVectorFieldMapper.java
- Codec wiring: `codec/SparseCodec.java`, `SparsePostingsFormat.java`, `SparseDocValuesFormat.java`, `SparseCompoundFormat.java`, `SparseCodecService.java`. These are custom Lucene `PostingsFormat`/`DocValuesFormat` wrappers that delegate non-sparse fields to the stock codec. [read: file list plus SparsePostingsConsumer delegation]
- Flush-time build (Lucene engine): `codec/SparsePostingsConsumer.write()` takes the sparse fields that pass `PredicateUtils.shouldRunSeisPredicate` (segment `maxDoc >= approximate_threshold`) out of the delegate postings writer. It writes them through `ClusteredPostingTermsWriter` into its own files, `.sit` (terms) and `.sip` (clustered postings), at format version 1. `ClusteredPostingTermsWriter.setFieldAndMaxDoc(..., isMerge=false)` creates a `SeismicPostingClusterer` sized for the segment's `maxDoc`. — `codec/SparsePostingsConsumer.java`, `codec/ClusteredPostingTermsWriter.java`
- Flush/merge forward index (Lucene engine): `codec/SparseDocValuesConsumer.addSparseVectorBinary()`. For SEISMIC-eligible segments it inserts every document's 8-bit-quantized vector into an in-heap `ForwardIndexCache` item keyed by (segment, field). On merge it reuses any vector already cached for the old segment (`cachedSparseVector()`), then drops the old segments' cache keys (`mergeHelper.clearCacheData`). — `codec/SparseDocValuesConsumer.java`
- Merge-time rebuild (Lucene engine): `codec/SparsePostingsConsumer.merge()` → `codec/SparsePostingsReader.merge()` → batches of 50 terms (`BATCH_SIZE = 50`, commented "magic number") → `algorithm/seismic/BatchClusteringTask` → `codec/MergeHelper.getMergedPostingForATerm()` (concatenates each source segment's posting for the term and remaps doc IDs through Lucene's `MergeState.docMaps`; docs that map to `-1`, that is, deleted, are dropped) → `SeismicPostingClusterer.cluster()` (top-λ prune via `PostingsProcessingUtils.getTopK`) → `RandomClusteringAlgorithm.cluster()` → `PostingsProcessingUtils.summarize()`. Clustering runs on `ClusterTrainingExecutor` (setting `plugins.neural_search.sparse.algo_param.index_thread_qty`, default 1). — files named above
- Merge-time and flush-time build (native engine, 3.9+): `codec/NativeDocValuesConsumer.java`. `addBinaryField` (flush) and `merge` (merge) both call `writeIndex(field, binaryDocValues)`. For a merge, the input is `SparseDocValuesReader` over the merged doc values, so the raw float vectors of all live docs in the source segments. `codec/nativeindex/CsrFileNativeIndexWriter` stages them as a CSR file, or `DefaultNativeIndexWriter` streams them off-heap. Either way they go through JNI to `nsparse`, which builds `seismic_sq` / `disk_seismic_sq` (segment ≥ threshold) or `inverted` (below threshold), as set in `codec/nativeindex/NativeIndexParameters.build()`. — `codec/NativeDocValuesConsumer.java`, `codec/nativeindex/NativeIndexParameters.java`
- Delete handling: OpenSearch writes no SEISMIC-specific delete code. Deletes are Lucene live-docs. The query scorers take `context.reader().getLiveDocs()` (`query/SparseQueryWeight.selectScorer`). `query/SeismicBaseScorer` skips non-live docs during the block scan (`if (acceptedDocs != null && !acceptedDocs.get(docId)) continue;`, lines ~110-112). Deleted docs are physically removed only when a merge rewrites the segment (docMap → -1 in `MergeHelper`). — `query/SeismicBaseScorer.java`, `query/SparseQueryWeight.java`, `codec/MergeHelper.java`
- Update = Lucene delete + re-add (standard Lucene semantics) [inferred: no update-specific code exists in the sparse package; grep found none].
- Caches (Lucene engine only): `cache/ClusteredPostingCache`, `ForwardIndexCache`, `LruTermCache`, `LruDocumentCache`, `CircuitBreakerManager`, `MemoryUsageManager`, `CacheGated*Reader`. They are bounded by `plugins.neural_search.circuit_breaker.limit` (default `"10%"`, `settings/NeuralSearchSettings.java` line 27/119) with LRU eviction. — [read code]; https://github.com/opensearch-project/documentation-website/blob/main/_vector-search/ai-search/neural-sparse-ann.md [read]
- Query path (not part of the updater): `query/SparseVectorQuery`, `SparseQueryWeight` (picks the fallback `rank_features` query below threshold, `ExactMatchScorer` when a filter has ≤ k docs, `OrderedPostingWithClustersScorer`/`SeismicBaseScorer` otherwise, `NativeIndexScorer` for native), `DiskSeismicKPrime`, `SparseAnnQueryBuilder`. [read]

**(2) Does the merge logic depend on Lucene codec/segment APIs?** [read]
- The Lucene-engine merge reads its inputs through Lucene types throughout. It walks `FieldsProducer`/`TermsEnum`/`PostingsEnum` per source segment, uses `MergeState.docMaps` for doc-ID remapping, reads `BinaryDocValues`/`SparseBinaryDocValuesPassThrough` for forward vectors, writes `BlockTermState` (`Lucene101PostingsFormat.IntBlockTermState`), and calls `IndexOutput`/`CodecUtil` (`codec/MergeHelper.java`, `codec/SparsePostingsReader.java`, `codec/ClusteredPostingTermsWriter.java`).
- The algorithmic core does not depend on Lucene. It is three small Java classes working on `List<DocWeight>` plus a `SparseVectorReader` lookup: `algorithm/seismic/SeismicPostingClusterer.java` (top-K prune; lists under 10 docs become a single unclustered block, `MINIMAL_DOC_SIZE_TO_CLUSTER = 10`), `algorithm/seismic/RandomClusteringAlgorithm.java`, and `algorithm/PostingsProcessingUtils.java`. In total they are about 200 lines.
- The native engine's builder, `nsparse` (C++, Apache-2.0), knows nothing about Lucene. Its `Index::add(n, indptr, indices, values)` takes CSR arrays, and `SeismicIndex::build()` calls `detail::build_clustered_lists(get_vectors(), dimension, cluster_parameter_, ...)` (`nsparse/seismic_index.cpp` lines 127-148). `add` only appends vectors; `build` clusters everything from scratch. — https://github.com/opensearch-project/neural-sparse-cpp/blob/main/nsparse/seismic_index.cpp [read]
- `nsparse` index headers (`index.h`, `seismic_index.h`, `disk_seismic_index.h`, `id_map_index.h`, `inverted_index.h`) declare `add`/`add_with_ids`/`build`/`search` only. There is no `remove`, `delete` or `merge` method (grep 2026-10-02). [read]

**(3) What reusing "just the updater" would take**
- Port to Rust: the only SEISMIC-specific merge logic is (a) gather each term's postings from the source segments, (b) drop deleted docs, (c) top-λ prune, (d) cluster with random centers in one assignment pass, (e) summarize with max-per-token then alpha-mass pruning. TusKANNy/seismic's builder already does (c) to (e), and in Rust. Porting would duplicate what we have [inferred from the read code above and our own builder].
- Java sidecar: they cannot run as a library outside a Lucene `IndexWriter` merge. Their inputs are `MergeState`/`FieldsProducer` objects, and their outputs are Lucene segment files (`.sit`/`.sip` plus a compound file), in a format private to the plugin (version 1). A sidecar would have to run a real Lucene index, meaning a full OpenSearch-like stack, just to get these files [inferred from (2)].
- Translation layer, direction 1 (ours → theirs): our forward index (per-doc component/value arrays, f32 or our quantization) → CSR (indptr/indices/values). That is the whole input `nsparse` needs. Direction 2 (theirs → ours): `nsparse`'s on-disk layout (`seismic_sq`/`disk_seismic_sq`: 8-bit scalar-quantized, `vmin=0`, `vmax=quantization_ceiling_ingest`, default 3.0, alignment-padded mmap layout, `idmap`) → our Rust SEISMIC posting/block/summary/forward-index layout. Their layout uses 8-bit quantization and different structures, so this direction is a full format rewrite. Its output would equal what `rebuild(forward_vectors)` in our own builder already produces [inferred; parameters from `codec/nativeindex/NativeIndexParameters.java`, read].
- Delete bookkeeping in their system is Lucene's live-docs bitset plus doc-ID compaction at merge. Our delta layer already needs both (a tombstone bitset per shard, and remapping on compaction). Neither has SEISMIC-specific logic in OpenSearch [read: SeismicBaseScorer/MergeHelper; inferred: equivalence to our layer].

**(4) Rebuild or incremental?** [read]
- Native engine (3.9): a full rebuild from the raw forward vectors of the merged live docs on every merge (`NativeDocValuesConsumer.merge` → `writeIndex(SparseDocValuesReader.getBinary)` → `nsparse` `add`+`build`). The docs say: "While the native engine is disabled, OpenSearch skips building the native index during segment flush and merge. Raw vectors are still written to disk, so re-enabling the engine and then force merging the affected indexes rebuilds the native index." — https://github.com/opensearch-project/documentation-website/blob/main/_vector-search/ai-search/neural-sparse-ann.md [read]
- Lucene engine: per term, it re-prunes, re-clusters and re-summarizes from scratch over the concatenated source postings. No existing cluster or summary is reused; only cached forward vectors are reused to avoid re-decoding (`SparseDocValuesConsumer` `cachedSparseVector()`). One subtlety: `SparsePostingsConsumer.write()` removes SEISMIC-eligible sparse fields from the delegate postings writer, so a SEISMIC segment keeps only its already-pruned top-λ lists. `SparsePostingsEnum.nextDoc()` iterates the clustered docs. So when SEISMIC segments merge, the new top-λ' (λ' = 0.0005·N_merged ≥ each source λ) is taken over the union of the pruned source lists, not over the full postings. Docs pruned out of a source segment's list for term t cannot come back in the merged segment, even though λ' is larger. [read: SparsePostingsConsumer.write masking, MergeHelper.getMergedPostingForATerm, SparsePostingsEnum; consequence is inferred]. The native engine does not have this issue because it rebuilds from doc values.
- Cost guidance from OpenSearch is about avoiding repeated rebuilds, not reducing their cost: "set `approximate_threshold` to a high value so that individual segments do not trigger clustering but the merged segment does. This approach helps avoid repeated cluster building during indexing." They also recommend `_forcemerge?max_num_segments=1` for lowest latency. — https://github.com/opensearch-project/documentation-website/blob/main/_vector-search/performance-tuning-sparse.md [read]

### Inferences
- Their "updater" is: (Lucene LSM: new small segments + live-docs + tiered merge policy) + (rebuild SEISMIC per segment once it reaches the threshold; below that, exact inverted index). Our delta layer already has this shape (base shards + delta + tombstones + compaction = rebuild). The one idea we may lack is a per-segment exact `rank_features`-style inverted index with a size threshold, that is, delta segments stay exact until they are large enough to cluster. Whether we have it depends on how our delta is currently served.
- Unlike the original SEISMIC's fixed λ, λ scales with segment size: max(0.0005·N, 160). With N = 18.8M that gives λ ≈ 9,400. Small delta segments therefore get short lists that cannot be "grown" later; any growth requires a rebuild.
- Neither OpenSearch codebase contains incremental SEISMIC maintenance (adding a doc to existing blocks and updating summaries in place, or merging clustered lists). Choosing between their code and ours makes no difference to the asymptotic update cost: both rebuild.

### Gaps
- I found no OpenSearch measurement of merge cost as a function of segment size, and no measurement of recall degradation from the pruned-union merge in the Lucene engine.
- I did not read the `nsparse` on-disk serialization (`io/index_io.cpp`, `io/seismic_invlists_writer.h`) byte by byte, so the effort for translation direction 2 is estimated, not measured.

## What OpenSearch shipped: versions, field settings, code locations

### Takeaway
SEISMIC shipped as the `sparse_vector` field type with `method.name: seismic`. It was introduced in OpenSearch 3.3 (Lucene/Java engine, default) and gained an optional native C++ engine (`engine: native`, the `neural-sparse-cpp` library over JNI, disabled by default) in 3.9 (blog dated 2026-09-29). All code is Apache-2.0.

### Cited Findings
- "**Introduced 3.3**" on both the sparse ANN page and the `sparse_vector` field page; "Engines … **Introduced 3.9**". — https://github.com/opensearch-project/documentation-website/blob/main/_vector-search/ai-search/neural-sparse-ann.md, https://github.com/opensearch-project/documentation-website/blob/main/_mappings/supported-field-types/sparse-vector.md [read]
- Method parameters and defaults (docs plus `common/SparseConstants.java`): `n_postings` default `-1` → `max(0.0005·doc_count, 160)` per segment; `cluster_ratio` 0.1; `summary_prune_ratio` 0.4; `approximate_threshold` 1,000,000; `clustering_batch_size` 1 (range 1–10000, native only); `forward_index` `shared`|`per_block` (native only); `quantization_ceiling_ingest` 3.0; `quantization_ceiling_search` 16.0; `engine` `lucene` (default) | `native`. Query parameters: `top_n` (query-token cut), `heap_factor`, `k`, filters. "The `method` object cannot be updated after the field is created." [read] Same sources, plus `common/SparseConstants.java`.
- Index setting `index.sparse`; cluster settings `plugins.neural_search.sparse.native_engine_feature_enabled` (static, default true), `plugins.neural_search.sparse.native_engine_enabled` (dynamic, default false), `plugins.neural_search.sparse.algo_param.index_thread_qty` (default 1), `plugins.neural_search.circuit_breaker.limit` (default 10%). — `SparseSettings.java`, `settings/NeuralSearchSettings.java` [read]; docs [read]
- Design history: k-NN RFC #2715 "[RFC] Sparse ANN Algorithm: Seismic" (author yuye-aws; PoC on MS MARCO v1 8,841,823 docs: P50 11.41 ms (17.46x), P99 13.96 ms, 86.11 ops/s (18.80x), recall 92.38%) — https://github.com/opensearch-project/k-NN/issues/2715 [snippet: WebFetch summary]. Native engine: RFC neural-search #1778 — https://github.com/opensearch-project/neural-search/issues/1778 [snippet]; Design #1802 (opened 2026-03-20, target 3.9.0, revised 2026-08-31) — https://github.com/opensearch-project/neural-search/issues/1802 [snippet: WebFetch summary]; docs PR #13018 — https://github.com/opensearch-project/documentation-website/pull/13018 [snippet]; PR #2005 "Bump neural-sparse-cpp submodule for DiskSeismic madvise fix" — https://github.com/opensearch-project/neural-search/pull/2005 [snippet].
- Code lives in `opensearch-project/neural-search` under `source/main/java/org/opensearch/neuralsearch/sparse/` (about 100 main classes), with git submodule `jni/external/neural-sparse-cpp` → https://github.com/opensearch-project/neural-sparse-cpp (C++, "inverted index, SEISMIC, and SEISMIC with scalar quantization … SIMD … ID mapping and ID selector filtering … Python bindings via SWIG"). Both are Apache-2.0. [read: LICENSE files, .gitmodules, README]

### Inferences
- `nsparse` (C++, Apache-2.0, CSR in, mmap out, Python bindings) is a SEISMIC builder and searcher that could stand alone. It is an alternative engine, not an updater, and has no update API.

### Gaps
- I did not read the exact 3.3 GA release-notes entry, or whether SEISMIC was experimental in 3.2. The docs say "Introduced 3.3".

## Per-segment storage, build timing, and the size threshold

### Takeaway
SEISMIC is built only for segments with maxDoc ≥ `approximate_threshold` (default 1M). It is built at flush if the flushed segment is already that big, and otherwise at the merge that first crosses the threshold, and again at every merge after that. Below the threshold, Lucene engine segments are ordinary `rank_features` postings scored exactly by the standard neural sparse query; native engine segments get an exact unquantized `nsparse` inverted index.

### Cited Findings
- Threshold predicate: `segmentInfo.maxDoc() >= approximate_threshold` (uses maxDoc, so deleted docs still count). — `common/PredicateUtils.java` [read]
- Below threshold: "Segments with fewer documents than `approximate_threshold`: Indexed without clustering, so queries against them score every matching document. The Lucene engine indexes these segments as plain neural sparse (`rank_features`) segments … The native engine indexes them as an equivalent inverted index built in its native format." — neural-sparse-ann.md [read]; `NativeIndexParameters.build` puts `index=inverted` below threshold, "unquantized, which is what lets it reproduce the Lucene rank_features ranking exactly" [read]
- Lucene engine files: `.sit` terms plus `.sip` clustered postings (`SparsePostingsConsumer`, codec name `SparsePostingsProducer`, version 1), forward vectors in BINARY doc values, compound extension `c` (`SparseConstants.COMPOUND_EXTENSION`). [read]
- Native engine: "The native engine writes the SEISMIC index to a file that OpenSearch memory maps at query time and reads in place. The on-disk layout is the runtime layout, so nothing is reconstructed when the index is loaded." 8-bit codes "cut the engine file from 13.9 to 8.0 GiB on base_full" (code comment in `NativeIndexParameters.java`). Parameters passed to nsparse: `lambda = nPostings`, `beta = cluster_ratio * nPostings`, `alpha = summary_prune_ratio`, `quantizer=8bit`, `vmin=0`, `vmax=quantization_ceiling_ingest`, `idmap=true`; when `clustering_batch_size > 1` it does a batched build that spills `nsparse-clustered-lists-*.tmp` into the segment directory. [read] Docs and `codec/nativeindex/NativeIndexParameters.java`.

### Gaps
- Not checked: whether a flush of more than 1M docs ever happens in practice (it depends on the refresh/RAM buffer). In practice the first SEISMIC build is almost always a merge [inferred].

## Merge cost, memory, force-merge guidance

### Takeaway
Merges are full rebuilds and can be expensive. Published numbers: native force-merge 1,159 s versus Lucene 3,863 s on 8.8M docs. At 1.29B docs, force-merging to segments of about 8.5M docs took 2 h 58 min on 15 r7g.12xlarge nodes.

### Cited Findings
- Design #1802 benchmark (MS MARCO v1, 8.8M docs): force-merge time Lucene engine 3,863 s → native 1,159 s; JVM heap 31 GB → 4 GB; resident memory 32.77 GiB → 16.35 GiB; QPS 259.8 → 361.3; average latency 3.28 → 2.18 ms; recall@10 0.86 → 0.84. — https://github.com/opensearch-project/neural-search/issues/1802 [snippet: WebFetch summary, numbers not checked against the raw issue text]
- 3.9 release blog: "39 percent higher throughput", "3.3x faster index builds", "8x smaller JVM heap", 8.8M-doc corpus; "The Lucene engine remains the default." — https://opensearch.org/blog/get-to-know-opensearch-3-9/ [snippet: WebFetch summary]
- Billion-scale blog (2025-10-28, OpenSearch 3.3): C4 corpus of 1,285,526,507 docs; 3 m7g.4xlarge managers plus 15 r7g.12xlarge data nodes; "10 SEISMIC segments per node, ~8.5 million documents each"; force merge "2 hours, 58 minutes, and 30 seconds"; memory "approximately 53 GB per data node"; guidance "Plan for approximately 1 GB of memory per 1M documents", set approximate threshold to "5M documents", keep "segments to between 5M and 10M documents". — https://opensearch.org/blog/scaling-neural-sparse-search-to-billions-of-vectors-with-approximate-search/ [snippet: WebFetch summary]
- `clustering_batch_size` "reduces memory usage during index building at the cost of longer build times"; `index_thread_qty` "can reduce force merge time". — performance-tuning-sparse.md [read]

### Inferences
- Rough comparison: our full rebuild of an 18.8M-doc shard takes 26 min on 8 threads. Their native force-merge of 8.8M docs took 19.3 min (thread count not reported). The scale is similar, and a merge in their system costs about as much as our rebuild.

### Gaps
- No per-merge (as opposed to force-merge) timing, and no peak build memory figures for the native engine.

## Deletes and updates at query time

### Takeaway
Deleted docs are skipped at query time through Lucene live-docs. They still occupy cluster slots, are still reflected in block summaries (built before the deletes), and still count toward the threshold and λ, until a merge rewrites the segment.

### Cited Findings
- `SeismicBaseScorer`: `if (acceptedDocs != null && !acceptedDocs.get(docId)) continue;` inside the block-doc loop; `acceptedDocs = context.reader().getLiveDocs()`. Filters with cardinality ≤ k go to `ExactMatchScorer`; for the native engine, filters are intersected with live-docs (`NativeIndexScorer.FilteredBitSetIterator`). [read] `query/SeismicBaseScorer.java`, `query/SparseQueryWeight.java`, `query/NativeIndexScorer.java`

### Inferences
- Summaries go stale in the safe direction: max-pooled summaries computed with deleted docs overestimate block scores. More blocks pass the `heap_factor` check, which wastes work but does not lose recall. If a block's best docs were deleted, live docs further down the posting list may not have survived the λ pruning, so recall can drop under heavy deletes until a merge.

### Gaps
- I found no published recall or latency measurement under many deletes.

## Memory model

### Takeaway
The Lucene engine (default) keeps clustered postings and the forward index in on-heap LRU caches bounded by a circuit breaker (default 10% of heap), with Warm Up and Clear Cache APIs. The native engine mmaps its file, uses the page cache with no bound or eviction, and keeps about 6 MB of anonymous metadata per segment-field at a 30K vocabulary.

### Cited Findings
- Engine comparison table: Lucene "JVM heap, in a plugin-managed cache", bounded by `plugins.neural_search.circuit_breaker.limit` "with least recently used cache eviction"; native "A memory-mapped file on disk … The operating system page cache, with no configurable limit and no eviction by OpenSearch"; "The first query against a segment pays a one-time cost to establish the memory mapping … grows with segment size." — neural-sparse-ann.md [read]
- "mapping handle plus per-term index metadata (~6 MB per segment-field at a 30 K vocabulary)"; "There is no self-managed native cache and no native-memory circuit breaker". — Design #1802 [snippet]

### Inferences
- The native engine's memory model (mmap, on-disk layout equals runtime layout) is the same as our Rust shards. Per-segment fixed overhead (about 6 MB, plus mmap setup) adds up as the number of segments grows.

### Gaps
- None material.

## Published benchmarks

### Takeaway
The largest published run is 1.29B docs: 11.77 ms average single-thread latency at 90% recall@10, about 4x faster than BM25 and over 10x faster than plain neural sparse. I found no head-to-head comparison with the original Rust SEISMIC.

### Cited Findings
- 1.29B C4 (90% recall@10): SEISMIC average 11.77 ms (P50 11, P99 27) and 158.7 ops/s, versus two-phase 45.62 ms / 82.05 ops/s, BM25 41.52 ms / 85.86 ops/s, plain neural sparse 125.12 ms / 26.35 ops/s. — billion-scale blog [snippet]
- 3.3 marketing: "up to 100x faster … over 90% recall … under 15ms for a 50-million document collection." — https://opensearch.org/blog/explore-opensearch-3-3/ [snippet: search summary only]

### Gaps
- No comparison against TusKANNy/seismic, and no index size on disk for the 1.29B run.

## Licence, separability of the design, per-segment overhead

### Takeaway
Everything is Apache-2.0, so the design can be copied freely. The design itself (per-segment SEISMIC, rebuild on merge, exact fallback below a size threshold, live-docs filtering) is simple and already close to our delta architecture. Its cost is a top-k search per segment, with results merged across segments.

### Cited Findings
- Licences: neural-search and neural-sparse-cpp are both Apache License 2.0. [read: LICENSE files]
- Each segment is scored independently (`SparseQueryWeight.scorerSupplier` per `LeafReaderContext`, with a per-segment `SEISMIC_HEAP_SIZE` heap in `SeismicBaseScorer`). The guidance keeps segments at 5–10M docs and uses force merge for latency. [read code]; blog [snippet]

### Inferences
- With S segments, query cost is roughly the sum over segments of a SEISMIC search, each touching top_n lists. That fits their 10 segments per node. Many small delta segments are only cheap because they are exact inverted indexes below the threshold.

## SEISMIC upstream (TusKANNy) and fidelity of OpenSearch's implementation

### Takeaway
As of 2026-10-02, upstream SEISMIC has no insert, delete or merge support, and no paper on dynamic updates. OpenSearch follows the SIGIR 2024 algorithm (static pruning, clustering into blocks with alpha-mass summaries, forward index, heap_factor block skipping). It differs in its per-segment λ formula, 8-bit quantization of both postings and summaries, and the absence of the CIKM 2024 kNN-graph refinement.

### Cited Findings
- TusKANNy/seismic commits 2025-01 to 2026-09 cover build speed-ups ("Speed up index construction: pruning, clustering, and summaries", 2026-07-28), vectorium compatibility, grid searches, and FxHashSet. There is no insert/delete/merge. The only public `add_document` (`src/inverted_index_wrapper.rs:680`) appends to the dataset and token map [read]; my inference is that it runs before the build. Issues #1–#19 (latest #19, 2026-04-15, "Skip-singleton summaries: 52% summary compression") contain no update feature request. — https://github.com/TusKANNy/seismic [read via clone + gh api]
- TusKANNy papers 2024–2026: SIGIR 2024 SEISMIC; CIKM 2024 kNN graph ("nearly 2.2x speedup"); ECIR 2025 scalability on 138M MS MARCO v2; ECIR 2026 "Forward Index Compression for Learned Sparse Retrieval" (DotVByte); SISAP 2026 "Two Indexes, One Foundation: kANNolo and Seismic". None covers dynamic updates. — https://tuskanny.com/en/publications/ [snippet: WebFetch summary]
- OpenSearch clustering: random centers (`numCluster = ceil(size·cluster_ratio)`), with each doc assigned once to the center that gives the maximum dot product, and no iterations; summary = per-token max, then the highest-weight tokens kept up to `summary_prune_ratio` of total mass. — `RandomClusteringAlgorithm.java`, `PostingsProcessingUtils.java` [read]

### Inferences
- This matches the SEISMIC paper's shallow single-pass clustering and alpha-mass summaries. It is a straightforward reimplementation, not a variant with update support.

### Gaps
- I did not check whether "Seismic-Wave" exists as a named paper. It did not appear in the TusKANNy publication list.
