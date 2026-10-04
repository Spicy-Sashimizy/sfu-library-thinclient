# Impact-quantized inverted index as a SPLADE "translation layer" (tantivy / Lucene / PISA)

Research notes compiled 2026-10-02. Markers: **[read]** = I opened and read the source (paper PDF text, source file, doc page); **[snippet]** = search-result snippet only; **[inferred]** = my derivation from cited facts, not stated by any source.
Code read at: tantivy `master` commit `1f9e49da` (2026-09-30, Cargo version `0.27.0`, unreleased); tantivy crate tarball `0.26.2` from crates.io (published 2026-09-08); tantivy-py `master` commit `46b25280` (2026-10-01, package version `0.26.2`, depends on `tantivy = "0.26.2"`, pyo3 0.29). This repo pins `tantivy>=0.26.0` (`requirements.txt:25`) and the venv has tantivy-py `0.26.0` installed.

**Scope note from the owner (added mid-task).** The idea under test is to take *only the updater* (insert/update/delete/merge machinery) of an existing engine and plug it into our system, perhaps through a translation layer. It is *not* to adopt a whole engine. These notes therefore keep two options apart:
- **(a) Full replacement for the sparse leg.** tantivy's writer, deletes and merges maintain a SPLADE impact index, *and* tantivy's query path answers the sparse queries. This replaces SEISMIC for that data. The latency consequence is in Q1/Q2/Q4.
- **(b) Updater-only.** tantivy's (or Lucene's) segment, merge and delete bookkeeping tracks which docs are live, which segment holds the newest copy and when to merge, while SEISMIC still answers queries. Q5 covers whether this can be separated and who has done it.

---

## Q1. Published effectiveness and latency of SPLADE on impact-quantized inverted indexes (Lucene/Anserini, PISA), and the "wacky weights" problem

### Takeaway
On MS MARCO passage (8.8M docs), exact DaaT on SPLADE takes about 100–220 ms/query single-thread in PISA with MaxScore, and roughly 600–690 ms with WAND/BMW. In old Lucene 8.3 (BMW) it took 2,140 ms for SPLADEv2. Recent Lucene (vectorized block-max MaxScore) reaches about 36 ms for SPLADEv3, level with PISA MaxScore. SPLADE's long expanded queries (about 25 unique terms; we use up to 64) and flat, high weights on common subword and stopword tokens leave few documents that BMW can skip. BMW is therefore slower than an exhaustive OR on SPLADE. No numbers are published for exact Lucene/PISA SPLADE on MS MARCO v2 (138M).

### Cited Findings
- **Wacky Weights (Mackenzie, Trotman, Lin; arXiv 2110.11540, 2021).** Setup: MS MARCO passage dev, top k=1000, single thread, in memory, 2× Xeon Gold 6144, Anserini on Lucene 8.3.0 using BMW, PISA using MaxScore over SIMD-BP128 with BP doc reordering, JASS as SaaT. RR@10 / mean latency ms / index MB [read] — [arXiv PDF](https://arxiv.org/pdf/2110.11540):
  - Lucene: BM25 0.187 / 40.1 / 661; uniCOIL-T5 0.352 / 222.3 / 1,313; **SPLADEv2 0.369 / 2,140.0 / 4,987**.
  - PISA MaxScore: BM25 0.187 / 8.3 / 739; uniCOIL-T5 0.352 / 36.9 / 1,358; **SPLADEv2 0.369 / 220.3 / 4,326**.
  - JASS exact: SPLADEv2 0.369 / 314.0 / 3,813. JASS approximate (ρ = 1M postings): SPLADEv2 **0.324** / 15.3, which is a loss of more than 12% RR@10.
  - SPLADEv2 vs BM25 slowdown: about 50× in Lucene and about 25× in PISA [read].
  - In PISA, WAND, BMW and VBMW on SPLADEv2 averaged **619 / 681 / 553 ms**, all slower than MaxScore at 220 ms. The paper says these algorithms are "working hard" to find skippable documents when "few documents can actually be skipped" in exact evaluation [read].
  - Term statistics (Table 2): SPLADEv2 documents have 229.4 unique terms and a sum of weights of 10,794.8. Queries have 25.0 unique terms and a weight sum of 2,037.8. The vocabulary has 28,131 terms, against 2.66M for BM25. SPLADEv2 queries carry about 4× more unique terms than uniCOIL [read].
  - Example "wacky" query weights: "and" 225 (a subword of "androgen"), "is" 70, "the" 56, and the comma "," 68 [read].
  - Impacts were fed in through the **"pseudo-document" trick**: an integer weight w is written as the term repeated w times, and the scorer is "sum of term frequency". JASS had to move to 32-bit accumulators because learned scores exceed 2^16, which added almost 50% overhead [read].
- **Guided Traversal (Mallia et al., SIGIR 2022, arXiv 2204.11314)**, Table 2, MS MARCO dev, single thread, PISA, mean / median / P99 ms / RR@10 [read] — [arXiv PDF](https://arxiv.org/pdf/2204.11314):
  - BM25: 5.7 / 4.3 / 24.0 / 0.187
  - uniCOIL: 37.9 / 21.4 / 194.5 / 0.352
  - **SPLADEv2: 219.9 / 201.3 / 581.6 / 0.369**
  - DeepImpact: 19.5; DeepImpact-GT: 4.8 at equal RR@10 0.326
  - GT was only applied to DeepImpact because WordPiece models (uniCOIL, SPLADE) use vocabularies that do not match BM25's [read].
- **BMP paper (Mallia, Suel, Tonellotto, SIGIR 2024, arXiv 2405.01117)**, Table 2, exact retrieval, PISA baselines, single thread, 2.8 GHz Xeon. SPLADE here is CoCondenser-EnsembleDistil (SPLADE++ ED), ms/query at k = 10 / 100 / 1000 [read] — [arXiv PDF](https://arxiv.org/pdf/2405.01117):
  - **MaxScore 120.6 / 152.8 / 193.8**
  - **BMW (block size 40) 614.2 / 658.7 / 686.7**
  - IOQP (SaaT) 79.1 / 80.2 / 80.8
  - Anytime 80.6 / 114.0 / 163.1
  - Clipping 245.9 / 358.8 / 504.1
  - E-SPLADE (efficient model), same order: MaxScore 13.6 / 19.2 / 28.2; BMW 10.8 / 16.0 / 27.0.
  - The paper attributes SPLADE's slowness to "queries with a large number of terms, which these algorithms are particularly sensitive to" [read].
  - The uncompressed inverted index for SPLADE is about **7.9 GB** [read].
- **Efficiency Study for SPLADE (Lassance & Clinchant, SIGIR 2022, arXiv 2207.03834)**, Table 1, PISA, mono-CPU. Latency includes query encoding [read] — [arXiv PDF](https://arxiv.org/pdf/2207.03834):
  - SPLADEv2-distil: 691 ms total, MRR@10 36.8, BEIR 47.0.
  - **BT-SPLADE-S: 7 ms, 35.8, BEIR 39.2**
  - BT-SPLADE-M: 13 ms, 37.6, BEIR 42.1
  - **BT-SPLADE-L: 32 ms, 38.0, BEIR 44.5**
  - BM25: 4 ms, 19.7.
  - Levers: separate query/doc encoders, L1 query regularization, FLOPS-regularized PLM middle training, BERT-tiny query encoder. BERT-tiny reduced latency about 10× in PISA and about 2× in Anserini for about −1.0 MRR@10. Out-of-domain cost: Quora nDCG@10 fell from 0.84 to 0.46 [read].
- **Rule & Mackenzie, "Fast, Compact, Immediate-Access Indexing for LSR Systems" (ECIR 2026)**, Table 3, top-10, single core of a Threadripper PRO 5975WX, MS MARCO v1 8.8M, SPLADEv3 (1,483,571,102 postings, 167.8 terms/doc, 24.1 unique query terms) [read; local PDF text of the paper] — [Springer](https://link.springer.com/chapter/10.1007/978-3-032-21324-2_1):
  - **PISA MaxScore 35.9 ms; Lucene (via Anserini, "vectorized Block-Max MaxScore") 36.1 ms**
  - LinkedBlock (dynamic, immediate-access) with MaxScore 83.3 ms; naive 215.0 ms
  - At 1M docs: PISA 5.93, Lucene 6.91, LB-MS 12.1
  - The paper states Lucene "has been heavily optimized for learned sparse retrieval, employing vectorization, compression codecs tailored to impact-based indexes, and document re-ordering by default" [read]. The Lucene version number is not stated in the text I read.
- **Anserini regressions for SPLADE++ ED** (`-impact -pretokenized`) [read] — [v1 page](https://github.com/castorini/anserini/blob/master/docs/reproduce/from-document-collection/msmarco-v1-passage.splade-pp-ed.onnx.md), [v2 page](https://github.com/castorini/anserini/blob/master/docs/reproduce/from-document-collection/msmarco-v2-passage.splade-pp-ed.onnx.md):
  - `-impact` means "not to encode BM25 doc lengths into Lucene's norms"; `-pretokenized` means no further tokenization. Collection type: `JsonVectorCollection`. Its loader repeats each token `cnt` times, i.e. the pseudo-doc trick (`JsonVectorCollection.java` lines 84–85).
  - MS MARCO v1 dev: RR@10 **0.3828**, R@1000 **0.9831** (8,841,823 docs).
  - MS MARCO **v2** dev: MRR@100 **0.1558**, R@100 0.6020, R@1000 **0.8223**. The pre-encoded v2 corpus tar is 66 GB.
  - **No latency or index-size numbers** are given on these pages [read].

### Inferences
- Up to 2021, BMW-family DaaT (Lucene 8 and tantivy's only pruning algorithm, see Q4) was the worst choice for SPLADE: 3–5× slower than MaxScore in PISA, and Lucene 8.3 was about 10× slower than PISA. Lucene caught up with PISA once it moved to block-max MaxScore [inferred from Wacky Weights + BMP + Rule & Mackenzie].
- Our query regime (up to 64 terms) is longer than SPLADEv2/v3 MS MARCO queries (25 / 24.1 unique terms). Every source above says DaaT cost grows with query length, so published numbers likely understate our cost [inferred].

### Gaps
- I found no published exact (rank-safe) Lucene or PISA SPLADE latency on MS MARCO v2 (138M). The Anserini v2 regression gives effectiveness only. The SEISMIC v2 paper compares only against HNSW.
- No multi-thread numbers for intra-query parallel exact Lucene/PISA SPLADE were found. All papers above are single-thread.

---

## Q2. Comparison with SEISMIC at equal recall; claimed speed-ups

### Takeaway
On MS MARCO v1 SPLADE, SEISMIC reports 0.19–0.53 ms single-thread at 90–97% accuracy@10, against about 100 ms for exact PISA. Its speed-up over IOQP is 85–105×. On MS MARCO v2 (138M) SEISMIC reaches about 3 ms at 98% accuracy@10 in RAM, and no inverted-index baseline exists at that scale. Later, rank-safe block-filtering methods (BMP, Superblock Pruning) come within 1.3–3.8× of SEISMIC or beat it, but they use custom forward/block indexes, not a standard engine's postings.

### Cited Findings
- **SEISMIC (Bruch, Nardini, Rulli, Venturini, SIGIR 2024, arXiv 2404.18812)**, Table 1, mean µs/query at accuracy@10 of 90 → 97%, single thread on an i9-9900K, SPLADE (cocondenser) on MS MARCO [read] — [arXiv PDF](https://arxiv.org/pdf/2404.18812):
  - **SEISMIC 187 → 531 µs**
  - **IOQP 17,423 → 51,522 µs (84.6–105.1×)**
  - SparseIvf 4,169 → 15,840
  - GrassRMA 807 → 1,984
  - PyAnn 489 → 1,878
  - **PISA (exact) about 100,325 µs on SPLADE**; 7,947 µs on E-SPLADE; 9,214 µs on uniCOIL-T5.
  - Index size (Table 2): SEISMIC **6,416 MiB**, built in 5 min on 64 threads; IOQP 2,195 MiB.
  - The authors dropped static pruning (Lassance et al.) from the comparison because it gave only a "2–4× over Pisa on E-Splade" and was "ineffective on Splade" [read].
- **SEISMIC at scale (Bruch et al., ECIR 2025, arXiv 2501.11628)** [read] — [arXiv PDF](https://arxiv.org/pdf/2501.11628):
  - MS MARCO v2: 138M passages, 127 nonzeros per passage, 44 per query. Exact retrieval gives MRR@10 10.88%, R@1000 61.87%. The dataset is about 66 GB with 16-bit values and 16-bit components.
  - **At 98% accuracy@10 (2× memory budget), SEISMIC takes 3 ms/query**, single thread, NUMA-pinned, in RAM, and HNSW is 6.9× slower.
  - Index sizes: SEISMIC without the κ-NN graph is **98.5 GB, built in 0.5 h**; with κ = 20 it is 98.4 GB, built in 16.6 h; HNSW is 104.4 GB, built in 10.1 h.
  - Going from v1 to v2 (about 15× more docs) slowed SEISMIC down by less than 8× at 90–96% accuracy.
  - The authors explicitly leave "indexes [that] cannot fit completely in main memory" to future work. **No PISA/Lucene baseline is included** [read].
- **Superblock Pruning (Carlson et al., arXiv 2504.17045, SIGIR 2025)**, Table 1, SPLADE, MS MARCO, single thread on an i7-1260P, uncompressed in-memory indexes. Mean ms at k=10 for recall 99% / 99.5% / 99.9% / rank-safe [read] — [arXiv PDF](https://arxiv.org/pdf/2504.17045):
  - **MaxScore: rank-safe 75.7 only**
  - SEISMIC 2.06 / 2.57 / 3.01 / –
  - **BMP 1.44 / 1.49 / 1.88 / 2.70**
  - **SP 0.629 / 0.715 / 0.785 / 2.15**
  - ASC 4.70 / … / 7.19
  - At k=1000: MaxScore 124; SEISMIC 5.72–10.5; BMP 4.99–13.9.
  - Index memory: BMP up to 37 GB raw, SP 39 GB, **SEISMIC 13 GB** (it uses static pruning). "Seismic cannot be rank-safe because it uses static index pruning" [read].
- **BMP**, Table 3, approximate, k=10, SPLADE. With the raw BM index: b=64, α=0.75 gives **2.7 ms at RR@10 37.45**; b=32, α=0.85 gives 3.2 ms at 37.97, against exhaustive 38.11. Safe BMP (b=16, k=10) takes 11.0 ms, against MaxScore 120.6 [read] — [arXiv PDF](https://arxiv.org/pdf/2405.01117).

### Inferences
- At equal high recall on 8.8M docs, SEISMIC is about **200–500× faster than exact PISA/Lucene MaxScore** (0.2–0.5 ms vs about 100 ms for SPLADE cocondenser). Against modern Lucene's 36 ms on SPLADEv3 (a different model and machine), the gap is about 70–190× [inferred: cross-paper ratio, different hardware].
- Our deployment: SEISMIC at about 65 ms warm p50 across 8 mmap shards on one host. That is far above the 3 ms in-RAM v2 number, which points to mmap/page-cache effects rather than algorithm cost. So the relative penalty of moving to an impact index under the *same* mmap regime may be smaller than the in-RAM paper ratios suggest. Both engines would then be bound by page faults, and an inverted index reads whole posting lists, so it touches more bytes per query than SEISMIC's pruned blocks [inferred, unmeasured].

### Gaps
- There is no head-to-head SEISMIC vs Lucene/PISA/tantivy on mmap or out-of-RAM indexes; SEISMIC's own authors list it as future work.
- There is no SEISMIC vs exact inverted index comparison on 138M+ docs.

---

## Q3. Mitigations that make inverted-index LSR fast — numbers

### Takeaway
Query-side levers (query-term pruning, two-phase, token pruning) give 2–10× on standard engines and are the only ones a stock Lucene or tantivy query path can use without engine changes. The large gains (10–100×) come from new traversal structures: BMP, superblocks, SEISMIC blocks, and clustered "Anytime" layouts. None of these exist in stock Lucene or tantivy.

### Cited Findings
- **Query-term pruning (BMP Table 4, SPLADE, BMP engine).** Keeping fraction β of query terms: β = 0.3 gives 1.2 ms at RR@10 37.31; β = 0.5 gives 1.8 ms at 38.13; β = 1.0 gives 3.2 ms at 37.97; β = 0.1 gives 0.5 ms at 30.38 [read] — [arXiv PDF](https://arxiv.org/pdf/2405.01117).
- **OpenSearch two-phase processor (OpenSearch 2.15; blog dated 2025-06-18).** High-weight query tokens retrieve candidates, then low-weight tokens rescore them. Setup: 3× m5.4xlarge, 20 clients, BEIR NQ/HotpotQA/DBPedia/FEVER/Climate-FEVER (2.7–5.4M docs).
  - P99 doc-only: 198 → 124 ms (1.22–1.78×).
  - **P99 bi-encoder: 617 → 122 ms (4.15–6.87×)**.
  - The blog page does not state default parameter values [read — WebFetch summary of the page] — [OpenSearch blog](https://opensearch.org/blog/introducing-a-neural-sparse-two-phase-algorithm/).
  - A search snippet claims "at most 9.8 times" speed-up "with negligible impacts on search relevance" [snippet] — [OpenSearch docs](https://docs.opensearch.org/latest/search-plugins/search-pipelines/neural-sparse-query-two-phase-processor/).
- **Elasticsearch token pruning** (ES 8.13 for `text_expansion`; index-level `pruning_config` default-on from ES 9.1 with `tokens_freq_ratio_threshold` = 5 and `tokens_weight_threshold` = 0.4) [read] — [ES sparse_vector docs](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/sparse-vector). It gave "3-4x improvement in 99th percentile latency" and "2 and 5 times" on ELSER benchmarks [snippet] — [Elastic Search Labs](https://www.elastic.co/search-labs/blog/text-expansion-pruning).
- **Model-side efficiency (SPLADE-doc / BT-SPLADE):** 691 → 7–32 ms in PISA (see Q1) [read] — [arXiv 2207.03834](https://arxiv.org/pdf/2207.03834).
- **Static pruning (Lassance et al.):** "only able to speed up query processing by 2–4× over Pisa on E-Splade ... ineffective on Splade", as reported by the SEISMIC authors [read] — [arXiv 2404.18812](https://arxiv.org/pdf/2404.18812).
- **Guided Traversal (GT):** DeepImpact went from 19.5 to 4.8 ms mean at equal RR@10 (4×). It could not be applied to SPLADE because the vocabularies do not match [read] — [arXiv 2204.11314](https://arxiv.org/pdf/2204.11314). The 2GTI-Fast variant was slower than 45 ms on SPLADE, per the BMP authors [read] — [arXiv 2405.01117](https://arxiv.org/pdf/2405.01117).
- **SaaT/JASS approximate:** 15.3 ms on SPLADEv2, but with an RR@10 loss above 12%. At about 52 ms, the loss is about 3% [read] — [arXiv 2110.11540](https://arxiv.org/pdf/2110.11540).
- **Approximate scale-out inside OpenSearch** (Q5(b)): SEISMIC per Lucene segment on 1.29B docs at 90% recall takes **11.77 ms avg (P99 27 ms)**, against "neural sparse" on the inverted index at 125.12 ms avg (P99 397.21 ms) and BM25 at 41.52 ms. It needs about 53 GB of memory per data node (OpenSearch 3.3, blog dated 2025-10-28) [read — WebFetch summary] — [OpenSearch blog](https://opensearch.org/blog/scaling-neural-sparse-search-to-billions-of-vectors-with-approximate-search/).

### Inferences
- With a stock tantivy query path, only query-side levers are available: dropping low-weight query terms, and a two-phase "top-N terms retrieve, full-vector rescore". The rescore could use our existing forward vectors. From the numbers above, expect about 2–7× over unpruned, not the 100× gap to SEISMIC [inferred].

### Gaps
- No two-phase or term-pruning numbers exist on 100M+ docs for a plain inverted index.

---

## Q4. tantivy specifics: Block-Max WAND, custom impact scoring, limits, prior art

### Takeaway
tantivy has exactly one dynamic-pruning algorithm, Block-Max WAND. It applies only to a top-k collector over a union (or intersection) of plain `TermQuery` scorers, and those scorers are hard-wired to BM25 with constants k1 = 1.2 and b = 0.75. A SPLADE dot product (Σ q_t · w_{d,t}) cannot be expressed through stock tantivy or tantivy-py queries. BM25 saturates in tf, and `BoostQuery` only scales whole term scores.

Exact impact scoring needs a Rust custom `Query`/`Weight`/`Scorer`. That scorer cannot reuse tantivy's internal `block_wand` (crate-private), and the block-max metadata only stores the BM25-maximizing (fieldnorm_id, tf) pair per 128-doc block. No SPLADE-on-tantivy implementation or benchmark exists that I could find. The tantivy issue asking for learned-sparse support has been open since 2024-05-09 with "no plans at the moment".

### Cited Findings
- **BMW dispatch.** `BooleanWeight::for_each_pruning` calls `block_wand(term_scorers, …)` only when the specialized scorer is `TermUnion` and the score combiner `SUPPORTS_BLOCK_WAND` (sum). A `TermIntersection` goes to `block_wand_intersection`, and everything else to a generic threshold loop [read: `src/query/boolean_query/boolean_weight.rs` ll. 677–711].
  - A single `TermQuery` uses `block_wand_single_scorer` [read: `src/query/term_query/term_weight.rs` l. 118–127].
  - `block_wand` / `block_wand_single_scorer` are re-exported only `pub(crate)` [read: `src/query/boolean_query/mod.rs` l. 8], so they are not available to custom queries.
- **BM25 is hard-wired in the term path.** `TermScorer` holds `similarity_weight: Bm25Weight` [read: `src/query/term_query/term_scorer.rs` ll. 9–24]. `const K1 = 1.2; const B = 0.75` are module constants with no setter. Scoring is `weight * tf/(tf + K1*(1-B+B*fieldnorm/avg))` via a 256-entry fieldnorm cache [read: `src/query/bm25.rs` ll. 8–9, 58–68, 179–191]. `Bm25Weight::new` is `pub(crate)`, while `for_one_term`/`for_terms`/`boost_by` are public [read].
- **Block-max metadata format.** Per full 128-doc block, the postings serializer computes the `(fieldnorm_id, term_freq)` pair maximizing BM25 `tf_factor` and writes 2 bytes, `[fieldnorm_id, encode(tf)]`. The tf is clamped `min(tf, 255)` and decoded with 255 → `u32::MAX` [read: `src/postings/serializer.rs` ll. 403–427; `src/postings/skip.rs` ll. 32–43, 77–81]. `SkipReader::block_max_score(&Bm25Weight)` turns that pair into a BM25 score [read: `src/postings/skip.rs` l. 175–181]. The block size is `COMPRESSION_BLOCK_SIZE = BitPacker4x::BLOCK_LEN` (128) [read: `src/postings/compression/mod.rs` l. 3].
- **Public low-level access.** `BlockSegmentPostings` (pub) exposes `docs()`, `freqs()`, `seek()`, `advance()`, and `block_max_score(&FieldNormReader, &Bm25Weight)`. `skip_reader()` and `load_block()` are `pub(crate)` [read: `src/postings/block_segment_postings.rs`]. `Weight::for_each_pruning` is a trait method a custom `Weight` may override [read: `src/query/weight.rs` l. 155].
- **Record options.** Text fields take `IndexRecordOption` Basic/WithFreqs/WithFreqsAndPositions. tantivy-py exposes this as `index_option` = `'basic' | 'freq' | 'position'` (default `'position'`) [read: tantivy-py `src/schemabuilder.rs` ll. 34, 67–72]. tantivy core has a `fieldnorms: bool` text option (default true) [read: `src/schema/text_options.rs` ll. 188–213]. tantivy-py's schema builder has no fieldnorms parameter (grep found none) [read].
- **tantivy-py query surface:** `term_query`, `term_set_query`, `boolean_query`, `boost_query(query, boost: f32)`, `const_score_query`, `disjunction_max_query`, and others. There is no custom-scorer hook [read: tantivy-py `src/query.rs`]. `add_document` takes text, so impacts would have to be fed in as repeated tokens (pseudo-doc trick) [read: `src/index.rs` l. 78; inferred for the pseudo-doc consequence].
- **Prior art / maintainer stance:**
  - tantivy issue **#2388** "Any plan to support learned sparse vector search?" (opened 2024-05-09). The issue text says BMW on SPLADE-like vectors "is even worse than exhaustive-or search". fulmicoton replied "no plans at the moment … Several companies in that space are using tantivy" (2024-05-09) and "none at the moment" (2025-01-07). Commenters pointed at 2GTI, BMP and SEISMIC [read via `gh issue view`] — [issue #2388](https://github.com/quickwit-oss/tantivy/issues/2388).
  - Issue **#936** "Right way to use only TF score for ranking" (2020) is a DeepCT/SPARTA user wanting model-set term scores. The maintainer called custom similarity something "requested a couple of times". The user kept a fork (`snakeztc/tantivy-ztc`, tantivy 0.13.2 `scored_text.rs`). It is still open [read] — [issue #936](https://github.com/quickwit-oss/tantivy/issues/936).
  - GitHub repo/code search for "tantivy splade" and "tantivy sparse vector" returned **no results** on 2026-10-02 [read].
- **SegmentPlugin (see Q5)** is the only new extension point. ParadeDB says it plans to use it for a "custom vector index" [read] — [PR #2993](https://github.com/quickwit-oss/tantivy/pull/2993).

### Inferences
- **Option (a) on stock tantivy-py is not exact SPLADE.** A `BooleanQuery` of `BoostQuery(TermQuery(t), q_t)` over a pseudo-doc field scores Σ q_t·idf_t·2.2·tf/(tf + 1.2·norm). That is a saturating and idf-reweighted function of the impact, so tf = 10 and tf = 100 differ by about 10%, not 10×. Disabling fieldnorms (Rust-only) makes the norm constant but leaves the saturation and idf in place. Ranking quality would have to be re-measured; it is not a faithful translation [inferred from `bm25.rs`].
- **Exact option (a) needs a Rust extension.** A custom `Weight`/`Scorer` would read `freqs()` as impacts and implement its own MaxScore/BMW in `for_each_pruning`. Block bounds could be recovered from the stored (fieldnorm_id, tf) pair: with fieldnorms disabled, the BM25-argmax pair is the max tf in the block, since tf_factor is monotone in tf at fixed norm. But the bound is only reachable through a `Bm25Weight` score, so one would invert BM25 or recompute. Impacts ≥ 255 lose their block bound, because the code maps 255 to u32::MAX, i.e. an unbounded block. A 0–254 quantization fits [inferred].
- **Pseudo-doc ingest cost.** Our 85 terms with 8-bit impacts mean thousands of token occurrences per doc through the tokenizer. Rule & Mackenzie measured Lucene at 100–500 µs/doc for SPLADEv3 pseudo-docs (up to 40 min for 8.8M docs) [read — Springer link above]. tantivy is unmeasured [inferred].
- **Latency consequence of option (a), order-of-magnitude only.**
  - Per shard: 150M/8 = 18.75M docs × 85 ≈ 1.59B postings, about 1.07× the SPLADEv3 MS MARCO volume (1.48B).
  - PISA/Lucene MaxScore takes about 36 ms there at k=10 in RAM. tantivy has no MaxScore, only BMW, which PISA measured at about 5× slower than MaxScore on SPLADE (614 vs 121 ms).
  - So a stock-tantivy BMW query is plausibly on the order of **hundreds of ms per shard single-thread, in RAM, with ≤ 25 query terms**. Our 64-term queries and mmap would add to that.
  - Compare the current SEISMIC p50 of about 65 ms. With aggressive query-term pruning (β ≈ 0.3–0.5) plus a two-phase rescore, a 2–7× reduction is the published range.
  - None of this is measured on tantivy [inferred; unmeasured].

### Gaps
- No published SPLADE/LSR benchmark on tantivy exists (latency, size or effectiveness). No tantivy MaxScore implementation was found in master.
- I did not find whether Quickwit or ParadeDB have shipped a sparse-vector feature built on the plugin. The PR states intent only.

---

## Q5. tantivy updater/merge API, tantivy-py exposure, and whether "updater-only" (option b) can be separated; updater components of tantivy and Lucene

### Takeaway
**tantivy 0.26.x (released):** the updater is fused to tantivy's own segment components (postings, fieldnorms, fast fields, doc store). There is no codec hook, so a foreign payload can only ride along as a stored-bytes or fast field that merges copy. A SEISMIC index per segment would have to be rebuilt externally by watching `meta.json`.

**tantivy master (0.27.0-dev, unreleased):** since PR #2993 (merged 2026-08-10) a `SegmentPlugin` trait lets custom per-segment files take part in write, merge (with the doc-id mapping that drops deleted docs) and GC. That is the hook a "SEISMIC-per-segment" design would need.

Lucene already has this separation through `Codec`/`FilterCodec`. **OpenSearch 3.3 ships exactly option (b):** SEISMIC built per Lucene segment through a custom codec, with Lucene's IndexWriter, deletes and merges as the updater.

tantivy-py exposes no `merge()`, no merge-policy setter and no plugin registration. It only has `commit`, `delete_*`, `garbage_collect_files` and `wait_merging_threads`; the last one consumes the writer.

### Cited Findings
**tantivy updater components (master `1f9e49da`, same layout in 0.26.2 except the plugin layer)** [read: `src/indexer/mod.rs`]:
- `IndexWriter` (public; `index_writer.rs`) holds the indexing worker threads, `delete_queue`, `segment_updater` and stamper.
  - Public API: `add_document`, `delete_term(Term) -> Opstamp`, `delete_query` (`#[doc(hidden)]`), `commit`/`prepare_commit`, `rollback`, `merge(&[SegmentId]) -> FutureResult<Option<SegmentMeta>>` ("If all segments are empty no new segment will be created"), `set_merge_policy(Box<dyn MergePolicy>)`/`get_merge_policy`, `wait_merging_threads(self)`, `garbage_collect_files`, and `add_segment(SegmentMeta)` (`#[doc(hidden)]`) [read: ll. 355, 381, 466–471, 483, 536, 694, 712].
  - Deletes "only affect documents that were added in previous commits … visible only after calling `commit()`" [read].
- `SegmentUpdater`, `SegmentManager`, `SegmentRegister`, `SegmentEntry`, `DeleteQueue` and `merger` are `pub(crate)` or private modules [read: `src/indexer/mod.rs` ll. 8–30]. Only `IndexWriter`, `LogMergePolicy`, `MergePolicy`/`MergeCandidate`/`NoMergePolicy`, `MergeOperation`, `SegmentEntry`, `SegmentWriter`, `SingleSegmentIndexWriter`, `merge_indices`, `merge_filtered_segments` and `advance_deletes` are re-exported [read: ll. 35–45].
- `MergePolicy` trait: `fn compute_merge_candidates(&self, segments: &[SegmentMeta]) -> Vec<MergeCandidate>`. It is called "every time the list of segments changes", on the segment-updater thread [read: `src/indexer/merge_policy.rs`].
- `LogMergePolicy` defaults: `level_log_size` 0.75, `min_layer_size` 10,000, `min_num_segments` 8, `max_docs_before_merge` 10,000,000, `del_docs_ratio_before_merge` 1.0. The value 1.0 means deletes alone never trigger a merge; it is settable in (0, 1] [read: `src/indexer/log_merge_policy.rs` ll. 8–15, 72–76].
- Standalone merge without a writer:
  - `merge_indices(&[Index], output_dir)` merges whole indices.
  - `merge_filtered_segments(&[Segment], IndexSettings, Vec<Option<AliveBitSet>>, output_dir)` accepts *caller-supplied* alive bitsets to drop doc_ids.
  - Both carry the warning "does NOT check or take the `IndexWriter` is running. It is not meant to work if you have an `IndexWriter` running" [read: `src/indexer/segment_updater.rs` ll. 131–200].
- Merger: `IndexMerger` opens source segments with their alive bitsets and builds a `doc_id_mapping` (or a sort-by-field mapping). In master it calls `plugin.merge(PluginMergeContext{readers, doc_id_mapping, target_segment, schema, settings})` for built-ins (inverted index, fast fields, store) and then custom plugins [read: `src/indexer/merger.rs` ll. 70–130, 511–537].
  - Deleted docs are therefore physically dropped only when a merge rewrites the segment [inferred from merger + the delete-file component].
- Segment files per component: `Postings, Positions, FastFields, FieldNorms, Terms, Store, TempStore, Delete` [read: `src/index/segment_component.rs`].
- Locks:
  - `.tantivy-writer.lock` is non-blocking. A failure "usually means … creating more than one instance of the `IndexWriter` … or a spurious lock file remaining after a crash".
  - `.tantivy-meta.lock` is blocking. It protects files being opened by `IndexReader::reload()` from GC so "another process [can] safely consume our index in-writing" [read: `src/directory/directory_lock.rs` ll. 40–60].
  - Reader reload policies are `Manual` and `OnCommitWithDelay` (default) [read: `src/reader/mod.rs`].
- **SegmentPlugin (master only).**
  - `trait SegmentPlugin { extensions(); create_writer(&PluginWriterContext) -> Box<dyn PluginWriter>; merge(PluginMergeContext); space_usage() }`.
  - `trait PluginWriter { add_document(doc_id, &dyn ErasedDocument, …); serialize(…); mem_usage(); as_any… }`.
  - Built-ins are re-implemented as plugins, and custom plugins run after all built-ins so they "can read built-in output" [read: `src/plugin.rs` ll. 22–145].
  - The index meta records `persisted_custom_extensions`. Reopening *without* registering the plugin still opens the index, but **creating a writer fails with `MissingPlugin`** ("fail closed") [read: `src/plugin.rs` test `test_reopen_without_plugin_fails_closed`, ll. 407–455; `src/index/index_meta.rs` ll. 316–322].
  - `merge_indices` requires an identical plugin set on all sources [read: `segment_updater.rs` ll. 139–141].
  - PR #2993 "Extensible segment components via plugin trait" by rebasedming (ParadeDB) was merged **2026-08-10**. Stated motivation: "Adding a new per-segment data structure means forking Tantivy … We (ParadeDB) plan on using this trait for 1) additional segment metadata for partitioning 2) custom vector index" [read] — [PR #2993](https://github.com/quickwit-oss/tantivy/pull/2993).
  - **Not in any release.** The crates.io `0.26.2` tarball (2026-09-08) has no `src/plugin.rs`, and master's CHANGELOG lists 0.27.0 as the next version [read]. GitHub's "Latest" release is v0.26.1 (2026-05-10), and PyPI tantivy-py latest is 0.26.2 (2026-09-17) [read].

**tantivy-py (master `46b25280`, v0.26.2)** [read: `src/index.rs`]:
- `IndexWriter` methods: `add_document`, `add_json`, `commit`, `rollback`, `garbage_collect_files`, `delete_all_documents`, `commit_opstamp`, `delete_documents` / `delete_documents_by_term` / `delete_documents_by_query`, `wait_merging_threads`, `__enter__`/`__exit__`.
  - `wait_merging_threads` calls `take_inner()`, so the Python writer is unusable afterwards [read: ll. 59, 291–293].
  - There is **no `merge`, no `set_merge_policy`, no plugin registration**.
- `Index.writer(heap_size=128_000_000, num_threads=0)` creates a tantivy writer with tantivy's default merge policy [read: ll. 398–417]. Maintainer cjrh in tantivy-py issue #59 (closed 2024-03-22): "the default merge policy in tantivy-py is the LogMergePolicy which will automatically merge documents. Just remember to call `writer.wait_merging_threads`" [read] — [tantivy-py #59](https://github.com/quickwit-oss/tantivy-py/issues/59).

**Lucene updater components and coupling:**
- A Lucene `Codec` is composed of `PostingsFormat`, `DocValuesFormat`, `StoredFieldsFormat`, `TermVectorsFormat`, `PointsFormat`, `FieldInfosFormat`, `SegmentInfoFormat`, `NormsFormat`, **`LiveDocsFormat`** (deletes), `KnnVectorsFormat` and `CompoundFormat`. A custom codec is registered via `META-INF/services/org.apache.lucene.codecs.Codec`; per-field postings/doc-values formats can be overridden. `CompetitiveImpactAccumulator` "accumulates the (freq, norm) pairs that may produce competitive scores" [read — WebFetch summary] — [Lucene 10.2 codecs package](https://lucene.apache.org/core/10_2_0/core/org/apache/lucene/codecs/package-summary.html).
- IndexWriter, MergePolicy and MergeScheduler call into codec formats through `SegmentWriteState`/`MergeState`, so the update machinery is format-agnostic by design [inferred from the codec package structure; class-level javadocs for IndexWriter/MergePolicy were not opened this session].
- **OpenSearch neural-search (option (b) in production).** `SparseCodec extends FilterCodec` (name `Sparse10010Codec`, delegate `Lucene101Codec`) overrides `docValuesFormat()`, `postingsFormat()` and `compoundFormat()`.
  - `SparseDocValuesFormat` wraps the delegate consumer with `SparseDocValuesConsumer` and `NativeDocValuesConsumer`.
  - On flush (`addBinaryField`) and on `merge(...)`, it reads each doc's sparse vector from BINARY doc values, but only if `shouldRunSeisPredicate(segmentInfo, field)` passes. It inserts the vector, byte-quantized, into a per-segment forward index keyed by `(segmentInfo, field)`, and the clustered SEISMIC postings are written through `SparsePostingsConsumer`/`ClusteredPostingTermsWriter`.
  - On merge it clears the cache entries of the merged-away segments [read: `src/main/java/org/opensearch/neuralsearch/sparse/codec/SparseCodec.java`, `SparseDocValuesFormat.java`, `SparseDocValuesConsumer.java` ll. 44–103, via `gh api`] — [neural-search repo](https://github.com/opensearch-project/neural-search/tree/main/src/main/java/org/opensearch/neuralsearch/sparse/codec).
  - The earliest commit touching `SparseCodec.java` is dated 2025-09-03 [read].
  - Operational guidance: "Set the approximate threshold to 5M documents and force merge segments to between 5M and 10M documents". The benchmark ran 10 force-merged SEISMIC segments per node, about 8.5M docs each, at about 1 GB RAM per 1M docs [read — WebFetch summary] — [OpenSearch blog 2025-10-28](https://opensearch.org/blog/scaling-neural-sparse-search-to-billions-of-vectors-with-approximate-search/).

### Inferences
- **(b) on tantivy ≤ 0.26:**
  - The workable shape is to store the quantized SPLADE vector as a `bytes` fast field or stored field, keyed by a doc-ID term. tantivy's writer, deletes and merges then maintain liveness and newest-copy, and merges carry the bytes along (and drop deleted ones).
  - SEISMIC would be rebuilt per tantivy segment from those bytes after each merge, detected by polling `meta.json` / segment IDs. Queries fan out over per-segment SEISMIC indexes, filtered by each segment's alive bitset.
  - tantivy gives no notification hook for merges in 0.26. A writer in another process holds `.tantivy-writer.lock`, and tantivy-py cannot call merge or set a policy, so a separate Rust helper would have to *be* the only writer (or the Python side must close its writer first) [inferred from the lock and API facts above].
- **(b) on tantivy master:** a `SegmentPlugin` could build the SEISMIC structure inside tantivy's flush and merge, as OpenSearch does in Lucene. But:
  - it is unreleased;
  - every writer process must register the plugin, otherwise it gets `MissingPlugin`;
  - tantivy-py would need a custom build with the plugin compiled in;
  - plugin merge receives `doc_id_mapping`, so deletes are honoured automatically [inferred].
- **Coupling:** in 0.26 the merger and segment writer are hard-wired to the four built-in components (the PR text says they were "hardcoded into several places"). Before the plugin PR, any foreign payload had to be one of tantivy's own field types [read PR text + inferred].
- **Rust-helper `merge` against a tantivy-py index directory** is technically possible: same on-disk format, `IndexWriter::merge(&[SegmentId])`. But only while no other `IndexWriter` (including tantivy-py's) is open, because of the non-blocking writer lock. tantivy-py readers with `OnCommitWithDelay` would pick up the new `meta.json` after the merge commits [inferred from `directory_lock.rs` + reader reload policy].

### Gaps
- No tantivy-based project implementing per-segment ANN or sparse structures via `SegmentPlugin` is public yet (as of 2026-10-02 I found only the PR's intent).
- I did not open Lucene's `IndexWriter`/`TieredMergePolicy` javadocs this session, so Lucene merge defaults are not cited here.
- OpenSearch's handling of segments below the 5M threshold (fallback to the plain inverted-index `neural_sparse` path) is implied by the blog, but I did not verify it in code.

---

## Q6. Lucene specifics for comparison (FeatureField, impacts, ES sparse_vector)

### Takeaway
Lucene supports learned-sparse impacts natively. `FeatureField` stores a positive float as a term frequency (9 significant bits in 16 bits) with a linear, log, saturation or sigmoid scorer. Because the value is a freq, Lucene's block-max impacts let it skip non-competitive docs. Elasticsearch `sparse_vector` and ELSER sit on this, adding index-level token pruning (default-on since ES 9.1).

### Cited Findings
- `FeatureField`: values are "internally encoded as term frequencies"; "only considers the top 9 significant bits … store them on 16 bits", giving a relative precision of about 2^-8. The linear query scores `w * S` with weight in (0, 64]. Values stored as freqs let search "efficiently skip documents that can't be competitive when total hit counts are not requested" [read — WebFetch summary] — [Lucene 10.2 FeatureField](https://lucene.apache.org/core/10_2_0/core/org/apache/lucene/document/FeatureField.html).
- ES `sparse_vector`: "9 significant bits for the precision … relative error of about 0.4%"; only strictly positive values; vectors are excluded from `_source` by default (GA 9.2); `pruning_config` defaults to `tokens_freq_ratio_threshold` 5 and `tokens_weight_threshold` 0.4 (ES 9.1) [read] — [ES docs](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/sparse-vector).
- Anserini's `-impact` mode is the integer pseudo-doc variant: no BM25 norms, tf = quantized weight [read — Anserini page in Q1].
- Lucene 8.3 BMW on SPLADEv2 took 2,140 ms (2021). A recent Lucene with vectorized block-max MaxScore took 36.1 ms on SPLADEv3, about equal to PISA [read — Q1 sources].

### Inferences
- Lucene's per-block impacts are (freq, norm) pairs used by any monotone Similarity. tantivy stores one BM25-argmax (fieldnorm_id, tf) pair per block with a BM25-only consumer. Lucene's design allows linear impact scoring with valid block bounds; tantivy's does not out of the box [inferred from FeatureField doc + tantivy source].

### Gaps
- Lucene's exact current sparse algorithm and the version that introduced vectorized MaxScore were not pinned to a release note this session.

---

## Q7. Index size per posting (impact-quantized) vs SEISMIC, scaled to 150M × 85 ≈ 12.75B postings

### Takeaway
Measured impact-index sizes for SPLADE on MS MARCO v1 work out to about 17–20 bits per posting (Lucene and PISA, 8-bit-range impacts, BP reordering for PISA). That gives roughly **27–31 GB for 12.75B postings**. SEISMIC's published indexes (forward index plus pruned clustered inverted lists) are about 45–51 bits per stored nonzero, i.e. about 2–3× larger per nonzero. A tantivy figure has not been measured.

### Cited Findings
- Rule & Mackenzie (ECIR 2026), SPLADEv3, 1,483,571,102 postings: **PISA 3,379 MiB, Lucene 3,032 MiB**, LinkedBlock (dynamic) 3,265–3,441 MiB [read — Springer link above].
- Wacky Weights, SPLADEv2, about 8.8M × 229.4 ≈ 2.03B postings: Lucene 4,987 MB, PISA 4,326 MB, JASS 3,813 MB [read — arXiv 2110.11540].
- BMP: SPLADE (cocondenser) uncompressed inverted index ≈ 7.9 GB. The BMP forward + block-max index is 4.3 + 2.3 GB at b = 64 compressed. BMW "necessitates storing an upper bound score for each posting block, leading to higher space consumption" [read — arXiv 2405.01117].
- SEISMIC: MS MARCO v1 SPLADE **6,416 MiB** (about 8.8M × 119 nnz/doc ≈ 1.05B nnz, using the nnz figure from arXiv 2501.11628). MS MARCO v2 **98.5 GB** for 138M × 127 ≈ 17.5B nnz; the raw dataset is 66 GB at 16-bit values and 16-bit components [read — arXiv 2404.18812, 2501.11628]. Superblock-pruning authors: SEISMIC uncompressed is 13 GB on MS MARCO [read — arXiv 2504.17045].
- tantivy postings encoding: 128-doc bitpacked blocks of doc deltas and tf, plus 8–12 byte skip entries per block (offsets, bit widths, block-max (fieldnorm_id, tf)) [read: `src/postings/skip.rs` ll. 205–250; `serializer.rs`]. There is no doc reordering (BP) in tantivy [inferred: none found in source; not verified exhaustively].

### Inferences
- Bits per posting:
  - Lucene 3,032 MiB × 8 / 1.4836B ≈ **17.1 bpp**; PISA ≈ **19.1 bpp**.
  - Wacky Weights SPLADEv2: Lucene ≈ 19.7 bpp, PISA ≈ 17.1 bpp (taking MB as 10^6 bytes).
  - SEISMIC: v2 ≈ 98.5e9 × 8 / 17.5e9 ≈ **45 bits/nnz**; v1 ≈ 6,416 MiB × 8 / 1.05B ≈ **51 bits/nnz** [inferred arithmetic].
- Scaled to 150M × 85 = 12.75B postings:
  - Lucene-like impact index ≈ 12.75e9 × 17.1 / 8 ≈ **27 GB**; PISA-like ≈ **30 GB** [inferred].
  - tantivy without BP reordering and with a per-128 skip overhead would plausibly be somewhat larger, but this is unmeasured. The pseudo-doc trick does not change the posting count (tf stores the impact), but freq bit widths of up to 8 bits per posting add to doc-delta bits [inferred].
  - SEISMIC-style at about 45 bits/nnz on all 12.75B nnz ≈ **72 GB** (upper bound; actual depends on static pruning λ and the forward-index precision).
- The serving footprint matters more than disk for our mmap regime. Exact DaaT touches every posting of each query term, while SEISMIC touches summaries plus selected blocks and forward-index rows. Bytes *touched* per query, not index size, would decide mmap latency, and that is unmeasured for both [inferred].

### Gaps
- No published tantivy index size for any learned-sparse collection.
- No published bits-per-posting for Lucene/PISA SPLADE at 100M+ docs. The figures above are linear extrapolations from 8.8M-doc collections.
