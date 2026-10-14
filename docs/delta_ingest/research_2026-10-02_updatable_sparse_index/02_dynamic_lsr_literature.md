# Dynamic / updatable indexes for learned sparse retrieval (LSR): 2024–2026 literature and code survey

**Status:** ACTIVE (research input to the delta_ingest track; compiled 2026-10-02, moved from the repository root `research_notes/`/`reports/` 2026-10-10)

Compiled 2026-10-02. Evidence tags: **[read]** = I opened the full paper PDF, source code or page and read the passage; **[snippet]** = search-result snippet or abstract only; **[inferred]** = my own derivation from cited facts (not a claim made by any source). PDFs were fetched from arXiv or author pages and text-extracted locally; GitHub facts come from `gh api` and shallow clones on 2026-10-02.

Context used for the inferences: 150M SPLADE vectors served from immutable SEISMIC shards (per-term statically pruned posting lists, clustered into blocks with summary vectors, plus a forward index). Per quarter, about 27% of a shard's docs are updated, 15% are new and 6% are deleted. An in-place posting-slot updater failed because list growth outran the slots that deletions freed.

**Scope note (owner clarification, received mid-task).** The idea being tested is to take ONLY the updater part of an existing system (its insert/update/delete/merge machinery) and plug it into our system, so that SEISMIC shards and tantivy stay the serving engines, possibly through a translation layer that converts between our format and theirs. Their engine would not replace ours. Each section below therefore carries an "Updater separability" block. Section 8 gives the cross-method summary.

---

## 1. Rule & Mackenzie (ECIR 2026) and related Moffat/Mackenzie immediate-access indexing

### Takeaway
Rule & Mackenzie take the Moffat–Mackenzie "LinkedBlock" immediate-access index (a fixed-size in-memory slab of chained fixed-size blocks, one chain per term) and adapt it to LSR. On MS MARCO v1 (8.8M passages) with SPLADEv3 it indexes at ≤~6 µs/doc and uses roughly as much space as PISA/Lucene. Its exact MaxScore queries are 2–6× slower than PISA (83.3 ms versus 35.9 ms). It is append-only, with no delete or update. It is meant as a small "fresh tier" that is later folded into the static index. It is not a mechanism for growing pruned or clustered lists.

### Cited findings
**Rule & Mackenzie, "Fast, Compact, Immediate-Access Indexing for Learned Sparse Retrieval Systems", ECIR 2026 (LNCS 16485), pp. 1-ff.** PDF: https://JMMackenzie.io/pdf/rm26-ecir.pdf ; Springer: https://link.springer.com/chapter/10.1007/978-3-032-21324-2_1
- What it is: a clean-room re-implementation of the "linked block" index of Moffat & Mackenzie (IPM 2023), with modifications for LSR — [read] https://JMMackenzie.io/pdf/rm26-ecir.pdf
- Data structure: "stored in a single contiguous slab of memory, the entirety of which is allocated at the beginning of indexing". Each postings list is a linked list of fixed-size blocks of B bytes. A hash table (perfect hashing on integer term IDs) points to the head block. "As blocks become full, new blocks are appended to the next free space of the memory slab and are linked by an implicit pointer, resulting in many interleaved lists of blocks." — [read] same URL
- Block types: the head block holds next_block, tail_block, doc_freq, last_docid, w_offset and a 1-byte term upper bound. Torso blocks are full of postings. The tail block holds first_doc and is the write point. Because the write offset is one byte, B ≤ 256 — [read]
- LSR modifications: (1) standard VByte on docID gaps plus the impact stored as one uncompressed byte, replacing Double-VByte; (2) a 1-byte per-list upper-bound impact in the head block, updated on insert, which enables MaxScore/WAND; (3) a shared integer vocabulary with the static index, so the dynamic index never stores strings — [read]
- Residency: in-memory. When written to disk, the vocabulary table takes up to 15% of total index space in the worst case — [read]
- Deletes and updates: the linked block index "supports rapid insertion, but no deletion" — [read]. The apoptosic index (Eades et al., ECIR 2022) handles expiry only through circular-buffer overwrite — [read]
- Operational model: the dynamic index serves "the fresh tier". "Once the dynamic index becomes sufficiently large, it will be offloaded into the static index, and a new, empty dynamic index will resume". The authors expect it "should not be expected to handle huge quantities of documents" — [read]
- Hardware: single core of an AMD Threadripper PRO 5975WX with 512 GiB RAM. Baselines: PISA (SIMD-BP128, MaxScore) and Lucene/Anserini — [read]
- Corpus: MS MARCO v1 passages (8.8M docs), subsets from 10k to 5M plus the full set. SPLADEv3 has 1,483,571,102 postings (167.8 per doc), a 27,952-term vocabulary, 24.1 unique query terms and a 16.61 GiB JSON. **Largest corpus tested: 8.8M docs** — [read]
- Index size, SPLADEv3, MiB (Table 2):

  | Docs | PISA | Lucene | LinkedBlock B=64 | LinkedBlock B=128 |
  |---|---|---|---|---|
  | 1M | 373 | 337 | 393 | 374 |
  | 8.8M | 3379 | 3032 | 3441 | 3265 |

  Source: [read]
- Insertion: "At a maximum of around 6 microseconds per document … can index over 100,000 documents per second". The full SPLADEv3 MS MARCO builds in under 1 minute, and throughput stays constant as the index grows. Lucene takes 100–500 µs/doc (up to 40 min). The original LinkedBlock was ~10 µs/doc; apoptosic is ~2 µs/posting — [read]
- Query latency, top-10, ms (Table 3), SPLADEv3:

  | Docs | PISA | Lucene | LB-Naive | LB-MaxScore |
  |---|---|---|---|---|
  | 1M | 5.93 | 6.91 | 24.2 | 12.1 |
  | 8.8M | 35.9 | 36.1 | 215.0 | 83.3 |

  DeeperImpact at 8.8M: PISA 28.6, LB-MS 90.7. LinkedBlock is "2 to 6× longer" than PISA/Lucene. MaxScore gives a 2–2.6× speedup over naive for LSR. The reference implementation with the same enhancements runs ~75 ms for the LSR indexes — [read]
- All of these are exact (rank-safe) DAAT queries over unpruned lists. No comparison with SEISMIC or any approximate engine is reported. SEISMIC appears only as citation [6] — [read]
- Future work suggested by the authors: block-based dynamic pruning (BMW-like) on LinkedBlock, LSR-tailored compression, and "revisiting other efficient static LSR systems in the context of dynamic document streams" — [read]
- Code: https://github.com/JMMackenzie/lslb — Apache-2.0, C/C++, 15 commits, last push 2025-10-22. Binaries for stream indexing and conjunctive/disjunctive querying (plain and quantized). Configured for WSJ1/Robust/Wiki — [read] (gh api + repository page)

**Moffat & Mackenzie, "Efficient Immediate-Access Dynamic Indexing", IPM 60(3) 103248 (2023; arXiv 2211.06030).** PDF: https://JMMackenzie.io/pdf/mm23-ipm.pdf
- "incremental document-level indexing using as little as two bytes per posting". Indexing rate is "two gigabytes/minute". Conjunctive Boolean queries take "just a few milliseconds" while ingesting concurrently. Net memory is "less than half the space required by the best previous mechanism" — [read]
- Largest collection: English Wikipedia (Apr 2022), 2,444,347,604 postings at document level / 996,277,511, 6,477,362 docs. Robust04 and WSJ1 are smaller. Hardware: single core, 2× Xeon Gold 6144, 512 GiB — [read]
- Wikipedia: Count-only 420.7 s versus Count+Index 574.5 s ("over a gigabyte per minute") — [read]
- Capacity: with B=64 and h=4-byte links, the slab tops out at 256 GiB, which supports ">100 billion postings" — [read]
- Total cost in bytes/posting for Wikipedia, document-level (Table 13):

  | Growth scheme | B=48 | B=64 |
  |---|---|---|
  | Const | 2.091 | 2.110 |
  | Expon(1.1) | 1.996 | 2.056 |
  | Triangle (new; overhead is a sub-constant fraction on long lists) | 1.952 | 2.013 |

  Source: [read]
- Query time, Wikipedia (Table 14): Const collated has a mean of 4.08 ms. Triangle interleaved is about 31 ms mean. A "collation" pass rewrites interleaved blocks into per-list order; it needs "a brief pause in query processing" — [read]
- The structure "facilitates fast conversion of the dynamic index to a 'normal' static compressed inverted index" — [read]
- Limitations stated: "We have not considered document deletions nor updates … Deletions are a complex challenge in all inverted file-based retrieval systems, because of the need to withdraw postings from the middle of lists, and then adjust neighboring d-gaps". Concurrency control and integration with static shards are also out of scope — [read]
- Code: https://github.com/JMMackenzie/immediate-access — Apache-2.0, C++, last push 2024-03-19 — [read] (gh api)
- Companion paper: Moffat & Mackenzie, "Immediate-Access Indexing Using Space-Efficient Extensible Arrays", ADCS 2022 (https://JMMackenzie.io/pdf/mm22-adcs.pdf) covers on-demand slab growth — [read] (title/abstract only)

**Eades, Wirth, Zobel, "Immediate text search on streams using apoptosic indexes", ECIR 2022.** Described by Moffat & Mackenzie: a circular array of n postings ⟨d,t,f,p⟩ with back-pointers. Expiry happens by overwriting; it is a sliding window, not arbitrary delete. It costs 16n bytes uncompressed, and the "maximum ratio of postings to documents must be known in advance". "Nor can the apoptosic method be used as a stepping stone in the construction of a conventional on-disk inverted index" — [read] via https://JMMackenzie.io/pdf/mm23-ipm.pdf (secondary description; I did not read the primary paper)

**Mackenzie, MacAvaney, Mallia, Siedlaczek, "Practical, Efficient, In-Memory Inverted Indexes", ECIR 2026 tutorial.** The proposal covers in-memory indexing, compression and dynamic pruning. It has no dynamic-update content in the text I grepped — [read] https://JMMackenzie.io/pdf/mmms26-ecir.pdf

### Updater separability
- (1) The updater is the posting-append path: hash to head, jump to the tail, VByte-append, update the block max. It is algorithmically trivial and separable as an idea. As code it is tied to its own slab/linked-block layout, and query processing walks that layout — [inferred from read structure]
- (2) Code is C/C++ under Apache-2.0 (lslb, immediate-access). Both are research binaries (stream indexer + query tools), not packaged libraries — [read] repository pages
- (3) Translation to SEISMIC: LinkedBlock holds docID-ordered, unpruned, unclustered full posting lists. Its natural output is "a normal static compressed inverted index" — [read]. Building SEISMIC blocks from it still needs SEISMIC's per-list static pruning (global top-λ), clustering and summary computation. Converting back into SEISMIC therefore amounts to a SEISMIC build over the merged lists, or at least over every touched list — [inferred]
- It has no delete or update path, so the 27% updates and 6% deletes would need a separate tombstone/version layer — [inferred from "no deletion" [read]]

### Inferences
- Bytes per posting for SPLADEv3 at 8.8M docs: 3265 MiB × 1,048,576 / 1,483,571,102 ≈ 2.3 B/posting (B=128) — [inferred]
- Quarterly fresh volume if the per-shard proportions hold corpus-wide: (15% new + 27% updated) × 150M ≈ 63M documents re-ingested per quarter. That is ~7× the largest corpus Rule & Mackenzie tested — [inferred]
- At ~168 postings/doc (SPLADEv3 MS MARCO; our model's density may differ), 63M docs ≈ 10.6B postings ≈ 24 GiB at 2.3 B/posting. Ingestion would take ~6 min at 6 µs/doc. Exact MaxScore query latency at that size is unmeasured in any paper; the trend line implies it would exceed the 83 ms seen at 8.8M — [inferred]
- The Rule & Mackenzie latencies are for exact (safe) top-k. They are not comparable to SEISMIC's approximate sub-ms numbers — [inferred]

### Gaps
- No paper tests LinkedBlock beyond 8.8M LSR docs, or with deletes/updates, or against SEISMIC/BMP.
- The Springer page (paywalled) was not read. The author PDF was read instead.
- No measured numbers exist for merging a LinkedBlock fresh tier into a static LSR index (PISA or SEISMIC).

---

## 2. SEISMIC line (Bruch, Nardini, Rulli, Venturini et al.)

### Takeaway
Through 2026-09 there is no published SEISMIC variant that supports insert, update or delete. All SEISMIC papers and the TusKANNy/seismic code are build-once. The 2026 work is about faster builds (build output unchanged), DotVByte forward-index compression and kNN-graph pairing. The only production "update" story is OpenSearch's per-Lucene-segment SEISMIC build, which rebuilds clusters at segment flush/merge time.

### Cited findings
- SEISMIC (SIGIR 2024, arXiv 2404.18812): posting lists are organised "into geometrically-cohesive blocks, each equipped with a summary vector". Construction uses static pruning. Stated future work is only "compression techniques for inverted lists … to further reduce the size of inverted and forward indexes". A grep of the full text for update/insert/delete/streaming/incremental finds nothing — [read] https://arxiv.org/pdf/2404.18812
- Seismic + κ-NN graph ("SeismicWave"; CIKM 2024, arXiv 2408.04443): the conclusions/future-work section leaves quantization and graph compression to future work and says nothing about updates — [read] https://arxiv.org/pdf/2408.04443. A 2.2× speedup over Seismic on MS MARCO SPLADE is reported — [snippet] https://lacuna.tiptreesystems.com/work/pairing-clustered-inverted-indexes-with-knn-graphs-for-fast-approximate/wrk_a0ccc490ec4cfd62efeae9a5c343d6da
- Scalability (ECIR 2025, arXiv 2501.11628), MS MARCO v2 SPLADE, 138M passages, ~127 nnz/doc, dataset ≈ 66 GB with fp16 values and u16 components. Table 1 (index size / build time, all threads):

  | Configuration | Index size | Build time |
  |---|---|---|
  | HNSW M=32 | 104.4 GB | 10.1 h |
  | Seismic λ=4e4, κ=20 (with κ-NN graph) | 98.4 GB | 16.6 h |
  | Seismic no κ-NN, λ=6e4 | 98.5 GB | 0.5 h |

  The κ-NN graph costs (⌊log2(n−1)⌋+1)·n·κ bits, that is, 27 bits/doc. Seismic answers in 3 ms at 98% accuracy@10 (2× budget), and HNSW is 6.9× slower. Each NUMA node had 256 GiB — [read] https://arxiv.org/pdf/2501.11628. Internal inconsistency: the text says sparse HNSW "takes about 12.5 hours" while Table 1 says 10.1 h — [read]
- Forward Index Compression for LSR (ECIR 2026, arXiv 2602.05445; Bruch, Fontana, Nardini, Rulli, Venturini): evaluates integer codecs on SEISMIC's forward index. DotVByte (a StreamVByte variant) gets "a space reduction of up to 22% over Uncompressed with similar query latency" for Splade and LiLsr. Recursive Graph Bisection docID reordering is evaluated as a further lever. Nothing on updates — [read] https://arxiv.org/pdf/2602.05445
- "Efficient Sketching and Nearest Neighbor Search Algorithms for Sparse Vector Sets" (arXiv 2509.24815, JACM under review, same authors) has no update/insert procedure for the index in the text I grepped — [read] https://arxiv.org/pdf/2509.24815
- TusKANNy/seismic repository (https://github.com/TusKANNy/seismic) — [read] gh api + clone, 2026-10-02:
  - MIT licence (plus a README "citation license"), 140 stars, last push 2026-09-10.
  - 2026 commits: "faster build" (Feb); DotVByte Python interface (2026-02-21); "Speed up index construction: pruning, clustering, and summaries" (2026-07-28); comparison with Dynamic Superblock Pruning (2026-04-08); version 0.5.1 (2026-08-06).
  - CHANGES.md says the build speed-ups (parallel global-threshold pruning, LPT dispatch, dense summary scratch, CSR clustering index, survivors-only reassignment) do not change the built index.
  - The only `add_document` APIs are on the dataset wrapper before build (`src/inverted_index_wrapper.rs:680`, `src/pylib/dataset.rs`). The index has no insert/delete/update API; `add_knn` attaches a κ-NN graph.
  - None of the 19 issues mentions updates, inserts or deletes.
- README comparison (splade-v3, MS MARCO, single thread, Core Ultra 7 265K):

  | Engine | MRR@10 | Average query time | Memory |
  |---|---|---|---|
  | DSP | 40.28 | 745 µs | 24.0 GB |
  | Seismic | 40.27 | 185 µs | 7.9 GB |

  Source: [read] repository README
- No "Seismic-Wave" incremental variant exists. "SeismicWave" is the kNN-graph-paired variant above — [read]/[snippet]
- Third-party remark (Carlson, Xie, Shah, Yang, "Efficiency Optimizations for Superblock-based Sparse Retrieval", arXiv 2602.02883): LSP/0's advantage includes "avoiding the need of a KNN graph which is complex to maintain with all-pair document-level comparison during search data update" — [read] https://arxiv.org/pdf/2602.02883
- OpenSearch neural sparse ANN (SEISMIC on `sparse_vector`, "Introduced 3.3"; native C++ engine "Introduced 3.9") — [read] https://docs.opensearch.org/latest/vector-search/ai-search/neural-sparse-ann/ and https://docs.opensearch.org/latest/vector-search/performance-tuning-sparse/
  - "Neural sparse ANN search automatically builds clustered posting lists once a segment's document count exceeds approximate_threshold".
  - Raising approximate_threshold avoids "rebuilding clusters repeatedly when segments with fewer documents are merged". Segments below the threshold "fall back to the rank_features … mode".
  - Mapping parameters are fixed: "create a new index with the intended mapping and reindex".
  - Updates and deletes therefore go through Lucene's segment/merge machinery, and SEISMIC clusters are rebuilt per merged segment — [read]
- OpenSearch blog (2025-10-28): 1.29B C4 docs on 15 r7g.12xlarge data nodes, ~53 GB memory per data node. Ingested in 10 partitions with a force merge after each. Force merge took 2 h 58 min 30 s. Single-thread mean latency was 11.77 ms (P99 27 ms) at 90% recall@10. Guidance: "approximate threshold to 5M documents and force merge segments to between 5M and 10M documents", and "approximately 1 GB of memory per 1M documents" — [read via WebFetch summary] https://opensearch.org/blog/scaling-neural-sparse-search-to-billions-of-vectors-with-approximate-search/

### Updater separability
- (1) SEISMIC has no updater to separate. Its build pipeline (global-threshold pruning, then per-list clustering, then summaries, then the forward index) is the only mutation path — [read code]
- (2) It is a Rust library, MIT-licensed. The build is a library call (`InvertedIndexBase::build`). Since 2026-07-28 the build is faster but produces identical output — [read]
- (3) The OpenSearch pattern is the nearest published "updater": LSM segments, each with its own SEISMIC build, plus Lucene deletes/merges. It is separable only as an architecture (segment-level rebuild + tombstones). It still runs a full SEISMIC build of every merged segment, so "converting back" is by construction a SEISMIC build at segment granularity — [read docs + inferred]

### Inferences
- Static pruning keeps a per-list top-λ by weight (global-threshold pruning in the 2026 code). When a new or updated document must enter a list, it competes with the current tail. Admission changes both list membership and the cluster summaries, which is consistent with the list-growth problem our in-place attempt hit — [inferred from read code/changelog]
- Because the 2026 build speed-ups leave output identical, rebuilding is cheaper than before, but a rebuild is still required. At 138M docs, a no-κ-NN build took ~0.5 h with all threads (2025 code) — [inferred from read]

### Gaps
- No author statement says explicitly that SEISMIC will not support updates. Absence of updates is inferred from papers, code and issues.
- No published build-time numbers exist for the 2026-07 faster build at 100M+ scale.
- The OpenSearch issue #1802 (native engine design) was not read in full.

---

## 3. Block-Max Pruning (BMP), Superblock Pruning (SP/DSP), LSP and other block/forward-index LSR indexes

### Takeaway
BMP, SP and LSP are build-once indexes over a BP-reordered docID space. Blocks are runs of consecutive docIDs, with per-term block-max arrays sized ⌈n/b⌉. Nothing has been published on dynamic BMP/SP. Appending blocks of new docIDs at the end is structurally possible; that is my inference, and no paper measures it. Rewriting blocks for updates breaks the BP ordering that gives these methods their speed. The code exposes only build-time builders.

### Cited findings
- BMP (Mallia, Suel, Tonellotto, SIGIR 2024, arXiv 2405.01117):
  - Divides docIDs into blocks of b consecutive IDs. Per term it stores an array of ⌈n/b⌉ block-max impacts (sparse when zero).
  - The per-block hybrid index holds (log2(b)-bit local docID, score) postings plus a sorted term list.
  - "We assign docIDs according to BP ordering", which yields "sparser and thus more compressible block-max impact scores, and … tighter upper bounds".
  - SPLADE MS MARCO space (Table 1, GB, b = 8/16/32/64/128/256): forward index 7.1/6.0/5.1/4.3/3.7/3.3; BM index raw 30.0/15.0/7.4/3.7/1.9/0.9; compressed 5.5/4.1/3.0/2.3/1.7/1.2. The uncompressed SPLADE inverted index is ~7.9 GB.
  - Speedups of ~2× to ~60× over earlier safe methods. Rust.
  - No discussion of updates.

  Source: [read] https://arxiv.org/pdf/2405.01117
- BMP code: https://github.com/pisa-engine/BMP — Apache-2.0, Rust, last push 2026-01-14. `ForwardIndexBuilder::insert_document` and the Python `Indexer.add_document` push into builders. `finish()` then builds the inverted + block-forward index and bincode-serializes it. There is no post-build mutation API — [read code]
- Dynamic Superblock Pruning (Carlson, Xie, He, Yang, SIGIR 2025, arXiv 2504.17045):
  - Aggregates c consecutive blocks into superblocks and "assume[s] the documents are reordered based on a similarity-based clustering strategy like Bipartite Partitioning". Max/avg term weights are precomputed "during offline indexing".
  - Extra space ≈ 2 GB (b=8) or 1 GB (b=16) on MS MARCO (c=64).
  - Uncompressed index sizes: BMP up to 37 GB, SP up to 39 GB, Seismic 13 GB ("because it uses static index pruning").
  - Code: https://github.com/thefxperson/hierarchical_pruning (Apache-2.0, Rust, last push 2026-07-21).

  Source: [read] https://arxiv.org/pdf/2504.17045
- In that code, `insert_term_streaming` computes block maxes per term during build (memory-efficient building). It is not a dynamic insert — [read code]
- LSP (Carlson, Xie, Shah, Yang, arXiv 2602.02883, "Efficiency Optimizations for Superblock-based Sparse Retrieval"):
  - Tests "zero-shot parameter robustness" because "a news index updated hourly can have large variations … it is not viable to run a full parameter grid search for each incremental change". This concerns the stability of parameters across rebuilt indexes, not an update algorithm.
  - Claims LSP/0 needs 5×, 8× and 4× less memory than SeismicWave, SP and BMP respectively out-of-domain on BEIR.

  Source: [read] https://arxiv.org/pdf/2602.02883
- SINDI (arXiv 2509.08395, Ant Group, integrated in VSAG): claims 4.2–26.4× single-thread QPS over SEISMIC/PyANNs at Recall@50 > 99% on MS MARCO — [snippet] https://arxiv.org/abs/2509.08395. Its full text mentions no insert/delete procedure (the grep hits are heap inserts only) — [read]

### Updater separability
- (1) No BMP/SP/LSP updater exists. A hypothetical "append new docIDs as new blocks" scheme would leave the existing per-block structures untouched and extend the per-term block-max arrays. New docs would not be BP-reordered relative to old ones, and updated/deleted docs would need tombstones — [inferred]
- (2) Code is Rust under Apache-2.0. The builders are library-usable for whole-index construction only — [read]
- (3) The BMP block is a docID range, while a SEISMIC block is a per-term cluster of docs inside one pruned list. These are different block semantics, so a translation would have to recompute SEISMIC's per-list pruning, clustering and summaries. Going the other way, a BMP index can be built from a forward index alone (BMP needs no clustering beyond the BP docID order), which is a full BMP build — [inferred]

### Gaps
- No published dynamic BMP/SP/LSP, no measured cost of appending unreordered blocks, and no measurement of BP-order decay under churn.

---

## 4. Graph-based sparse retrieval (HNSW over sparse vectors, PyANNs, GrassRMA, kANNolo)

### Takeaway
The BigANN 2023 sparse-track winners (PyANNs, GrassRMA) are HNSW-based. That track measured static build + query only, on 8.8M docs. HNSW's construction is incremental by design, but at 138M SPLADE docs sparse HNSW (M=32) needs 104.4 GB and 10–12.5 h to build. kANNolo's HNSW exposes only a batch `build_index`. No published sparse-graph system measures deletes or updates.

### Cited findings
- BigANN NeurIPS'23 sparse track: MS MARCO 8,841,823 passages, SPLADE, ~120 nnz/doc and ~49 nnz/query. Best QPS at recall@10 ≥ 0.9 (private / public query sets):

  | Entry | Private | Public |
  |---|---|---|
  | pyanns | 6500 | 8732 |
  | shnsw/GrassRMA | 5078 | 7137 |
  | nle (PISA-based) | 1313 | 2359 |
  | sustech-whu | 788 | 1015 |
  | cufe | 98 | 105 |
  | linscan | 95 | 93 |

  - PyANNs: HNSW with coordinates as 16-bit ints and values as fp16, 8-bit during graph search, plus refinement.
  - GrassRMA: HNSW with co-located coordinates and values, plus upper/lower value bounds for early termination.
  - Build limit 12 h. sustech-whu needed 14 h.
  - The evaluation is build-then-query only; no updates.

  Source: [read] https://arxiv.org/pdf/2409.17424
- Sparse HNSW at 138M (ECIR 2025): M=32, 104.4 GB, 10.1 h build (text says ~12.5 h). It is 25× slower to build than Seismic without the κ-NN graph — [read] https://arxiv.org/pdf/2501.11628
- kANNolo (ECIR 2025 demo, arXiv 2501.06121; https://github.com/TusKANNy/kannolo — MIT, Rust, last push 2026-09-13): HNSW over dense and sparse data with PQ. The public API has `build_index(dataset, config)`, search and conversion functions. There is no public insert/delete API, and the grep for delete/tombstone/incremental finds nothing — [read code]
- Seismic's κ-NN graph adds 27 bits/doc at 138M (κ=20) and turns the build from 0.5 h into 16.6 h — [read] https://arxiv.org/pdf/2501.11628. A third party describes it as "complex to maintain … during search data update" — [read] https://arxiv.org/pdf/2602.02883

### Updater separability
- (1) An HNSW insert routine is algorithmically separable (greedy search + neighbour selection + reverse-link pruning). However, it maintains a graph, which is not the posting-list/forward-index structure SEISMIC serves from. Of SEISMIC's parts, it could only maintain the optional κ-NN graph — [inferred]
- (2) kANNolo is Rust/MIT with no exposed incremental insert. The PyANNs/GrassRMA code licences were not checked — [read kANNolo]; [gap others]
- (3) A translation from graph to SEISMIC does not exist; graph neighbours carry no per-term posting information — [inferred]

### Gaps
- PyANNs/GrassRMA repositories were not inspected for insert/delete APIs or licences.
- No published delete/update measurement exists for any sparse-graph index at 100M scale.

---

## 5. Dense-ANN dynamic techniques that might transfer (SPFresh/LIRE, FreshDiskANN, Quake, IVF overflow); LIRE on sparse?

### Takeaway
SPFresh's LIRE is the closest published analogue to our problem. It is a clustered (IVF-like, SPANN) on-disk index with an append-to-nearest-posting foreground updater, version-map tombstones, and a background split/merge/reassign rebalancer. It was measured only for dense vectors at 1% daily churn. FreshDiskANN uses an in-memory delta + StreamingMerge and merges a 10% change in ~10% of rebuild time. I found no publication applying LIRE-style rebalancing to sparse or inverted indexes.

### Cited findings
**SPFresh: Xu et al., "SPFresh: Incremental In-Place Update for Billion-Scale Vector Search", SOSP 2023 (arXiv 2410.14452).** Source for all bullets: [read] https://arxiv.org/pdf/2410.14452
- LIRE is "a lightweight incremental rebalancing protocol to split vector partitions and reassign vectors in the nearby partitions". Rebalancing is cheap "by only reassigning vectors at the boundary between partitions".
- Updater: "appends a new vector at the tail of its nearest posting and maintains a version map to keep track of vector deletion by setting a corresponding tombstone version". The version map is 7-bit version + 1-bit valid per vector, kept in memory.
- Split: "When a posting exceeds a length limit, LIRE evenly splits the oversized posting into two smaller ones". A reassign check follows for vectors in the split and nearby postings, using two necessary conditions derived from the nearest-partition-assignment (NPA) property. Merges are triggered by small postings. Convergence is proved because |C| grows by 1 per split and |C| ≤ |V|.
- Measured: "only 0.4% insertion will cause rebalancing"; average split count 2, maximum 160, cascade length 3. "The merge frequency is only 0.1% of the update". "On average, each time 5094 vectors are evaluated, and only 79 are actually reassigned".
- Workloads: SPACEV/SIFT 100M with 1% delete + 1% insert daily for 100 days, plus billion-scale stress tests.
- Resources: DiskANN global rebuild needs 1100 GB DRAM for 2 days (or 5 days at 64 GB). SPFresh used 10 GB memory and 2 cores and had 2.41× lower P99.9 latency than DiskANN. Peak was 4K QPS search + 2K QPS update on one NVMe with 15 cores.
- The SPANN+ append-only baseline (no split/reassign) saw P99.9 rise "from 4ms to more than 10ms because its posting keeps growing, inducing data skews".
- Code: https://github.com/SPFresh/SPFresh — MIT, C++, last push 2025-05-31. It requires SPDK (user-space NVMe, Secure Boot disabled) and a modified RocksDB, and is built on SPTAG — [read README via gh]

**FreshDiskANN: Singh et al., arXiv 2105.09613 (2021).** Source for all bullets: [read] https://arxiv.org/pdf/2105.09613
- Architecture: a long-term SSD index plus a short-term in-memory index, consolidated by a two-pass StreamingMerge whose "time and space complexity … is proportional to the change set".
- Measured on ~1B SIFT points, 48 cores, 3.2 TB SSD:
  - under 128 GB DRAM at all times;
  - merges "a 10% change … (5% inserts + 5% deletes) … in ∼10% of the time than it takes to rebuild";
  - steady state of 1800 inserts/s + 1800 deletes/s, with bursts to 40,000 inserts/s;
  - insert/delete user latency under 1 ms;
  - about 1000 searches/s at 95+% 5-recall@5.
- Deletes are lazy, followed by consolidation.

**Other dense work**
- BigANN'23 streaming track (dense MSTuring 10M slice, 8 GB memory cap, 1 h runbook, insert:delete:search ≈ 4:4:1): the baseline is DiskANN streaming (FreshDiskANN ideas). Puck (Baidu, hierarchical clusters + PQ) did inserts "using a natural extension of the build algorithm" and deletions "via an array of flags". After the recall-computation bug was fixed, PyANNs won using "DiskANN … out-of-the-box with an 8-bit scalar quantization". The track had no sparse streaming entry — [read] https://arxiv.org/pdf/2409.17424
- Quake (Mohoney et al., arXiv 2506.03437): an adaptive multi-level partitioned (IVF) index that "adjusts to updates and changing access patterns, guided by a cost model". Dense only — [read abstract] https://arxiv.org/pdf/2506.03437

**LIRE applied to sparse or inverted indexes**
- A web search for LIRE/split-reassign on sparse vectors, inverted indexes or clustered posting lists found nothing relevant — [snippet search, negative result]

### Updater separability
- SPFresh/LIRE:
  - (1) The protocol (append to nearest partition, tombstone via version map, split when over length, local NPA-checked reassignment, merge when small) is described as an algorithm and is conceptually separable. The code is tightly coupled to SPTAG/SPANN centroid navigation, the SPDK block controller and RocksDB — [read]
  - (2) C++/MIT, research artefact needing SPDK. It is not a library — [read]
  - (3) Mapping onto SEISMIC: a SEISMIC "partition" is a block inside one term's pruned posting list, and a document appears in up to ~nnz lists. One LIRE insert would become ~nnz per-list nearest-block appends plus summary updates, and a split would re-cluster one list's block. The NPA reassign condition depends on L2 centroid geometry; SEISMIC clusters by inner-product similarity within a list. Static pruning (top-λ per list) has no counterpart in SPFresh. Whether the reassign conditions hold for IP-summary blocks is unanalysed — [inferred]
- FreshDiskANN:
  - (1) The StreamingMerge idea (delta index + merge cost proportional to the change set) is architecture-level and separable. The merge code is specific to the Vamana graph — [read]/[inferred]
  - (2) microsoft/DiskANN is MIT, now mainly Rust (last push 2026-10-02) — [read gh api]
  - (3) For SEISMIC, the analogue would be a delta SEISMIC (or exact) index plus a per-list merge. A merge proportional to the change set would require per-list re-pruning and re-clustering of only the touched lists. That is unpublished for SEISMIC — [inferred]

### Inferences
- SPFresh was validated at 1%/day (~90%/quarter of inserts+deletes, but spread daily). Our ~48% of docs churned per quarter is in the same aggregate range. The difference is that each sparse doc touches ~100+ posting lists, while a dense vector touches 1 partition (or a few with SPANN replicas) — [inferred]
- The SPANN+ result (append-only, no split, latency 4 → >10 ms as postings grow) is the dense analogue of our "list growth" failure. LIRE's answer is to split oversized partitions rather than reuse slots — [inferred from read]

### Gaps
- No sparse/LSR implementation or evaluation of LIRE exists. The behaviour of the NPA reassign conditions under inner-product summaries is unanalysed.

---

## 6. Classic dynamic inverted-index maintenance (geometric partitioning, logarithmic merge, hybrid in-place + merge)

### Takeaway
The classic literature frames the choice as in-place extension versus re-merge versus re-build. It concludes that geometric/logarithmic partitioning (a bounded number of sub-indexes merged when sizes are similar) and Büttcher–Clarke hybrids (long lists in place, short lists merged) beat pure strategies for append-heavy text streams. None of it covers deletions at ~40% quarterly churn, or pruned/clustered LSR lists.

### Cited findings
- Lester, Moffat, Zobel, "Fast on-line index construction by geometric partitioning", CIKM 2005 (doi 10.1145/1099554.1099739): "When straightforward approaches are used, document insertions become increasingly expensive as the size of the database grows". Controlled partitioning "can be adapted to suit different balances of insertion and querying operations". Experiments on 100 GB of web data — [snippet: OpenAlex abstract] https://doi.org/10.1145/1099554.1099739
- Lester, Moffat, Zobel, "Efficient online index construction for text databases", ACM TODS 2008 (doi 10.1145/1386118.1386125): geometric partitioning "provides a range of tradeoffs between costs … can yield substantial savings" — [snippet: OpenAlex abstract] https://doi.org/10.1145/1386118.1386125
- Moffat & Mackenzie summarise these strategies — [read] https://JMMackenzie.io/pdf/mm23-ipm.pdf
  - Lester et al. "immediately merged with a single on-disk index … growing merging costs … not asymptotically efficient" (only 2 indexes to query).
  - Hierarchical/logarithmic merging is "asymptotically efficient, but requires that queries be processed against … a logarithmic-bounded number of on-disk indexes".
  - Büttcher & Clarke "consider a range of hybrid strategies that blend these two approaches".
  - Extensible-list schemes (Const/Expon/Triangle; Shoens/Tomasic short versus long blocks; Brown et al. 16–8192-byte size palette) handle in-memory list growth.
- Büttcher & Clarke, "A Hybrid Approach to Index Maintenance in Dynamic Text Retrieval Systems", ECIR 2006, and "Hybrid index maintenance for contiguous inverted lists", Inf. Retr. 2008 (doi 10.1007/s10791-007-9042-8): long posting lists are updated in place and short lists by merge, which is faster than either pure strategy. Contiguous lists favour queries, discontiguous lists favour updates — [snippet] https://link.springer.com/chapter/10.1007/11735106_21 ; https://www.researchgate.net/publication/220479957_Hybrid_Index_Maintenance_for_Contiguous_Inverted_Lists
- Lester, Zobel, Williams, "Efficient online index maintenance for contiguous inverted lists" (IPM 2006) / "In-place versus re-build versus re-merge" (2004) — [snippet: titles only] https://www.researchgate.net/publication/222688290_Efficient_online_index_maintenance_for_contiguous_inverted_lists
- Deletes in classic inverted indexes: "Deletions are a complex challenge in all inverted file-based retrieval systems, because of the need to withdraw postings from the middle of lists, and then adjust neighboring d-gaps" — [read] Moffat & Mackenzie 2023
- Sinnamon/LinScan's "full deletion" from parallel id/value arrays "often leads to a reorganization of the underlying array of data in memory". Sinnamon instead removes the id from compressed (Roaring) lists and leaves the sketch column for reuse — [read] https://arxiv.org/pdf/2301.10622
- Packed-memory arrays: I found no IR/LSR paper applying PMAs to posting lists in 2024–2026 — [negative search result; not specifically searched beyond the queries above]

### Updater separability
- (1) Geometric partitioning and logarithmic merge are generic segment-merge policies. They are separable from any index format, provided each segment can be built and queried independently and results federated — [inferred]
- The Büttcher–Clarke hybrid needs per-list mutability (in-place long lists), which is exactly what failed for pruned/clustered SEISMIC lists — [inferred]
- (2) Classic papers have no maintained code — [inferred; not checked]
- (3) With SEISMIC as the segment format, each merge is a SEISMIC build of the merged segment. This is the OpenSearch pattern (§2) — [inferred]

### Inferences
- With ~48% quarterly churn (15% new + 27% updated + 6% deleted), a logarithmic-merge policy would rewrite a large share of base data each quarter. Its main benefit over full rebuild is spreading and bounding merge cost. Query cost grows with the number of live segments (log-bounded) — [inferred]

### Gaps
- Primary PDFs for Lester et al. (2005/2008) and Büttcher & Clarke (2006/2008) were not accessible (Springer/ACM/Semantic Scholar blocked or rate-limited). Their quantitative numbers are therefore not recorded here.
- No classic-literature numbers at ~40% churn with deletions were found.

---

## 7. BigANN 2023 sparse track and 2024–2026 successors: streaming/updates for sparse vectors?

### Takeaway
No. The 2023 sparse track was static (build + batch query on 8.8M MS MARCO SPLADE). The streaming track was dense only (MSTuring 10M). The only published streaming-sparse algorithm is Sinnamon/LinScan (Bruch, Nardini, Ingber, Liberty; TOIS 2024). LinScan was the sparse-track baseline.

### Cited findings
- Track definitions and results: see §4/§5 — [read] https://arxiv.org/pdf/2409.17424. The streaming track used "a 10 million vector slice of the MS Turing data set", which is dense — [read]
- Sinnamon / LinScan (Bruch, Nardini, Ingber, Liberty, "An Approximate Algorithm for Maximum Inner Product Search over Streaming Sparse Vectors", arXiv 2301.10622; ACM TOIS, doi 10.1145/3609797). Source: [read] https://arxiv.org/pdf/2301.10622 unless marked.
  - Scope: "collections are streaming—necessitating dynamic indexing".
  - LinScan: an uncompressed inverted index with parallel id/value arrays, or Roaring-compressed ids ("LinScan-Roaring"). Its "full deletion" wipes postings.
  - Sinnamon: an inverted index (Roaring) of non-zero coordinates plus a 2m-dimensional upper/lower-bound sketch matrix per doc. On insert, the doc's ids go into the inverted lists and its sketch into a matrix column. On delete, the id is removed from the lists and the column is recycled for the next insert.
  - The authors say this "may prove suboptimal" for delete-heavy workloads because the sketch matrix grows to the max simultaneous size. They also say "deletions are dwarfed by insertion and update requests".
  - Measured on MS MARCO v1 encodings (SPLADE ~119 nnz/doc, E-SPLADE, uniCOIL, BM25), single-threaded random-order insertion. "As the index grows the insertion throughput decreases". Sinnamon inserts are "often slower than … LinScan-Roaring" but adequate.
  - Deleting 1M random vectors: Sinnamon "about an order of magnitude faster" per deletion than LinScan-Roaring.
  - Exact docs/s and ms/deletion values appear only in Figure 12 (plots). They are not extractable as text, so no numbers are recorded here.
  - Written in Rust.
  - The paper has no clustering or static pruning. Retrieval is coordinate-at-a-time over full lists plus sketch scoring, followed by exact re-ranking of k′ candidates (for example, k′ = 5,000–20,000).
- LinScan code: https://github.com/pinecone-io/research-bigann-linscan — MIT, Rust, last push 2023-06-19 — [read gh api]
- No 2024–2026 BigANN successor with a sparse streaming track was found. The big-ann-benchmarks repository is still active (MIT, last push 2026-07-13), but I did not find a new sparse-streaming track in it — [read gh api]; [gap: repository contents not inspected]
- Production LSM-style sparse systems: Milvus keeps inserts in in-memory "growing segments" until flush/compaction before building SPARSE_INVERTED_INDEX — [snippet] https://milvus.io/docs/sparse-inverted-index.md. OpenSearch uses the per-segment SEISMIC build (§2).

### Updater separability
- Sinnamon:
  - (1) The insert/delete logic (append id to per-coordinate Roaring lists; write or recycle a sketch column; remove id on delete) is simple and separable as an algorithm. It maintains unpruned docID lists plus a sketch matrix, not SEISMIC's pruned clustered blocks — [inferred from read]
  - (2) The LinScan baseline is Rust/MIT. I did not locate a public Sinnamon repository — [read]/[gap]
  - (3) Sinnamon lists could act as an exact or approximate fresh tier. Folding them into SEISMIC would require SEISMIC's pruning, clustering and summarisation over the affected lists, that is, a (partial or full) build — [inferred]

### Gaps
- Sinnamon's numeric insert/delete throughput is not recorded (figure-only).
- I found no 2024–2026 benchmark with a sparse streaming workload.

---

## 8. Updater separability — cross-method summary (owner clarification)

### Takeaway
No published method contains an updater that maintains SEISMIC's structure: per-term statically pruned lists, clustered into summary-bearing blocks, plus a forward index. Every candidate falls into one of three groups.
- (a) Fresh-tier structures with their own layout: LinkedBlock, Sinnamon/LinScan, FreshDiskANN's in-memory index. Folding them into SEISMIC requires a SEISMIC build over the merged or affected data.
- (b) Merge policies that are format-agnostic: geometric/logarithmic partitioning, StreamingMerge, Lucene segment merges as used by OpenSearch-SEISMIC. These are separable, but each merge output is a SEISMIC build.
- (c) In-place clustered-partition maintenance: SPFresh/LIRE. Algorithmically the closest match to clustered-list growth (split oversized partitions plus local reassign), but published and coded only for dense L2/IP vectors inside SPTAG+SPDK.

### Cited findings
The table below combines evidence from §§1–7. Tags: [read] = paper/code read; [snip] = snippet only; [inf] = my inference.

| Method | Updater separable as algorithm? | Code and licence | Update part usable as library? | Translation to/from SEISMIC | Back-conversion needs SEISMIC build? |
|---|---|---|---|---|---|
| LinkedBlock (Rule & Mackenzie 2026; Moffat & Mackenzie 2023) | Yes, trivial append path; insert-only [read] | C/C++, Apache-2.0 (lslb, immediate-access) [read] | No; research binaries [read] | Full docID-ordered unpruned lists, converts to a "normal static" index [read]. SEISMIC needs pruning + clustering + summaries [inf] | Yes, for every touched list or a full build [inf] |
| Apoptosic (Eades et al. 2022) | Sliding-window expiry only [read, secondary] | Not checked | — | Cannot feed a conventional index build [read, secondary] | — |
| BMP / SP / LSP | No updater exists [read code] | Rust, Apache-2.0 [read] | Builders only [read] | DocID-range blocks versus per-term clusters; incompatible block semantics [inf] | Yes [inf] |
| SEISMIC itself | No updater exists [read code] | Rust, MIT (+ citation licence) [read] | Build only [read] | — | — |
| OpenSearch SEISMIC-per-segment | Yes, as architecture (Lucene segments, tombstones, merges) [read] | Apache-2.0 OpenSearch (licence not re-checked) [inf] | Not separable from Lucene/OpenSearch as code [inf] | Each segment is its own SEISMIC index [read] | Yes, per merged segment [read] |
| Sparse HNSW / kANNolo / PyANNs | Graph insert is separable but maintains a graph [inf]. kANNolo: batch build only [read] | kANNolo Rust, MIT [read] | No [read] | Graph ≠ postings. Could maintain only SEISMIC's optional κ-NN graph [inf] | N/A [inf] |
| Sinnamon / LinScan | Yes: per-coordinate Roaring append/remove + sketch column [read] | LinScan Rust, MIT; Sinnamon repository not found [read] | LinScan is a small Rust crate-like repository; library use not verified [inf] | Unpruned lists + sketch; SEISMIC pruning/clustering needed [inf] | Yes [inf] |
| SPFresh / LIRE | Protocol separable on paper [read]. Code coupled to SPTAG + SPDK + RocksDB [read] | C++, MIT [read] | No [read] | Per-doc insert becomes ~nnz per-list block appends. Split = recluster one list's oversized block. NPA reassign derived for L2 geometry, unverified for IP summaries; static top-λ pruning has no analogue [inf] | Not necessarily, if adapted. Unpublished [inf] |
| FreshDiskANN StreamingMerge | Merge idea separable; code Vamana-specific [read]/[inf] | Rust/C++, MIT (microsoft/DiskANN) [read] | No [inf] | Delta index + change-proportional merge would need per-list re-prune/re-cluster for touched lists [inf] | Partial (touched lists) if built; unpublished [inf] |
| Geometric / logarithmic merge; Büttcher–Clarke hybrid | Merge policy fully format-agnostic. Hybrid in-place needs mutable long lists [read secondary]/[inf] | None found [inf] | — | Each merge = SEISMIC build of merged segment [inf] | Yes [inf] |

### Inferences
- Of the published updaters, only SPFresh/LIRE addresses the specific obstacle we hit: partition growth beyond allotted capacity, handled by splitting and locally reassigning rather than reusing freed slots. Its SPANN+ ablation (append-only, no split) shows the same failure mode as ours: latency 4 → >10 ms as postings grow — [inferred from read]
- Every other option either avoids mutating the clustered/pruned structure (fresh tier + rebuild/merge) or does not have one — [inferred]

### Gaps
- No paper evaluates any of these updaters on SEISMIC-format data, on pruned or clustered sparse lists, or at our churn mix (15% new / 27% updated / 6% deleted per quarter).
- The licences of PyANNs, GrassRMA, Sinnamon and OpenSearch neural-search were not verified.
