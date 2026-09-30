# 04 — Research: updating immutable indexes (conclusions + sources)

**Status:** ACTIVE

**Recorded 2026-09-29** by the docs item (H) from `04_HANDOFF_2026-09-29.md`,
which held (until its conversion to a dispatch record the same day) the conclusions of three online research passes run by the cloud
review session on 2026-09-29. This doc adds nothing the handoff did not
record, except the measured contradictions from this host's 2026-09-29 runs
(`03_SPIKE_PLAN.md` addendum), which are marked as such.

## Provenance rule (read first)

Egress blocked most academic and vendor hosts during the research, so most
findings come from search-result summaries; GitHub pages were read in full
(handoff, last paragraph). The handoff does not say per source what was read,
so marks are applied by rule, not upgraded by guesswork:

- **[read]** — a GitHub-hosted source the handoff says was checked. Only
  `TusKANNy/seismic` qualifies.
- **[snippet]** — every other source (from search summaries).
- **inferred** — a conclusion drawn by the research session, not stated by a
  source.

Any number below not measured on this host is *est.* or "unmeasured / design
only". No web fetch was made to write the sections above the addendum; the
**Addendum 2026-09-29** at the end was written from primary sources opened on
that date and supersedes a mark above wherever the two differ.

## Conclusions (from the handoff, with 2026-09-29 measurements alongside)

1. **The design shape is correct** — inferred (from the sources in groups
   "Theory" and "Production" below). `02_DESIGN.md` (L0 mutable buffer, L1
   immutable generations, L2 immutable base, newest-wins masks, compaction)
   is the Bentley–Saxe static-to-dynamic route; read/update/space cannot all
   be minimised (RUM conjecture [snippet]); the production systems listed
   below use masks for deletes + a side buffer for inserts + background
   rebuild [snippet]. Bars M1–M8 stay uncut.

2. **"Almost no OpenAlex churn reaches the SEISMIC shards"** — inferred from
   `01_RESEARCH.md` §1.1 (~15%/month touched, dominated by citation-count
   bumps; real title/abstract changes *est.* ~1M/month in slice).
   **Contradicted by measurement 2026-09-29 (M7 FAIL):** on two real snapshot
   partitions touched:must-encode was ≈1.15:1 and ≈2.61:1 in slice (*est.*
   ratios), below the < 3:1 falsification bar. Most touched in-slice records
   were NEW works (160,347 of 194,931 in the primary file), and 25.3% of an
   exactly-compared 9,965-doc base section had changed encoder text (against
   base text ~3 months old; steady-state churn unmeasured). The ledger also
   cannot filter base docs (no base hashes). See
   `data/eval_results/delta_ingest_M7_20260929*.json`.

3. **Deletes move from follow-up to core** — inferred. The JSON mask list
   cannot hold tens of millions of `deleted_ids`; a livedocs bitset over base
   ordinals (150M bits ≈ 19 MB) also fixes S5. Lucene live-docs and tantivy
   `.del` files are the model [snippet]. **Measured 2026-09-29:** implemented
   as a Python per-shard filter; `.liv` 18,801,718 bytes for 150,413,098
   bits; gates G1/G2 PASS, PARTIAL 101/120 topics; filter cost p50
   6.5–10.6 ms/query (`02_DESIGN.md` §4 item 3).

4. **The fold-in premise "needs a full 150M rebuild whose input is gone" is
   probably wrong for the SPLADE leg** — inferred. The f16 twin shards hold
   every doc's stored sparse vector; a per-shard rebuild (twin → jsonl →
   `SeismicIndex.build` → c1a → dotvbyte perdoc) was estimated at *est.*
   ~17–19 min build + minutes of conversion, peak ~10 GB, serial.
   **Measured 2026-09-29 (M9, shard 0):** build 1,919 s (~32 min) wall under
   host load (original build 1,134 s + 16 s save), c1a 365 s + dotvbyte
   195 s, peak RSS 8.2 GB resident (swapped; original 9.92 GB) — the 17–19
   min estimate did not hold on a loaded host. Forward index round-trips
   exactly (5,000/5,000 rows), but parity vs the served shard **FAILED** the
   pre-registered 0.99 bar: overlap@10 0.9858 (120 topics) / 0.9870 (100
   diverse). Build-vs-build drift of two stock builds of the same input is
   UNMEASURED, so the route is neither refuted nor verified.

5. **In-place editing verdicts** — inferred, from the slack-structure and
   version-map sources below plus this repo's E5 record.
   (a) Forward-record append-and-repoint (SPFresh-style version map
   [snippet]): DESIGN ONLY, worth building only if M4 shows double copies
   cost latency. (b) Slack-space format change (PMA / Büttcher–Clarke gaps
   [snippet]): **CLOSED DEAD 2026-09-29** — weeks of Rust, ~1.5–2× space
   (*est.*), E5 Fix #5A measured that padding dilutes page sharing, new docs
   still need a side buffer. (c) Patching NEW docs into packed lists is
   impossible without (b).

6. **Shard count** — inferred from this repo's G8g measurements (12.9 vs
   6.4 ms max-shard time at 8 concurrent shards) and the `blake2b % 16`
   refinement property. 16 shards is the defensible ceiling, UNMEASURED;
   sequential Σ *est.* ~420 ms at 16, ~720 ms at 32. A 9-shard pilot (M10)
   was pre-registered 2026-09-29 and did NOT RUN. Era/time partitioning is
   DEFERRED pending a passing M9 and M4.

SEISMIC-specific facts: `TusKANNy/seismic` has no insert/delete/merge API and
no issues asking for one (checked 2026-09-29) [read]; OpenSearch neural-sparse
builds SEISMIC per Lucene segment and rebuilds on merge [snippet].

## Sources (grouped as in the handoff)

**Inverted-index maintenance**
- Lester, Zobel, Williams 2004 — in-place vs re-merge vs rebuild [snippet]
- Lester, Moffat, Zobel 2005/2008 — geometric partitioning [snippet]
- Büttcher, Clarke 2006/2008 — hybrid maintenance, over-allocation [snippet]
- Moffat, Mackenzie 2023 — immediate-access dynamic indexing [snippet]
- Rule, Mackenzie, ECIR 2026 — immediate-access dynamic indexing for LSR [snippet]

**Vector / ANN**
- FreshDiskANN 2021 [snippet]
- SPFresh, SOSP 2023 [snippet]
- IP-DiskANN 2025 [snippet]
- UBIS 2026 [snippet]
- LSM-VEC 2025 [snippet]
- Ada-IVF 2024 [snippet]
- CleANN 2025 [snippet]

**Production systems**
- Lucene doc-values generations and live-docs [snippet]
- tantivy `.del` files [snippet]
- Vespa memory index + fusion [snippet]
- Milvus L0 / sealed segments [snippet]
- Qdrant appendable vs immutable segments [snippet]
- Pinecone slabs [snippet]
- turbopuffer WAL [snippet]
- Iceberg / Delta Lake deletion vectors [snippet]
- Lance fragments + manifests [snippet]
- RocksDB / ClickHouse / Elasticsearch hard-link snapshots [snippet]
- reflink / `FICLONERANGE` copy-on-write [snippet]

**Theory**
- Bentley, Saxe 1980 — static-to-dynamic transformation [snippet]
- Overmars 1983 [snippet]
- O'Neil et al. 1996 — LSM-tree [snippet]
- Brodal, Fagerberg 2003 [snippet]
- Yi 2012 [snippet]
- RUM conjecture 2016 [snippet]

**Slack structures**
- PMA — Bender, Demaine, Farach-Colton 2000 [snippet]
- PCSR 2018 [snippet]
- CPMA 2024 [snippet]
- ALEX 2020 [snippet]
- "Are Updatable Learned Indexes Ready?", VLDB 2022 [snippet]

**Persistent structures**
- Driscoll, Sarnak, Sleator, Tarjan 1989 [snippet]
- Okasaki 1998 [snippet]
- HAMT [snippet]
- Prolly trees [snippet]

**Immutable pages + deltas**
- Bw-tree 2013 [snippet]
- Wang, Pavlo et al. 2018 critique of the Bw-tree [snippet]

**SEISMIC-specific**
- `TusKANNy/seismic` (GitHub) — no insert/delete/merge API, no issues asking
  for one, checked 2026-09-29 [read]
- OpenSearch neural-sparse — SEISMIC built per Lucene segment, rebuilt on
  merge [snippet]

---

## Addendum 2026-09-29 — sources of brief 05 re-read, novelty check

Written 2026-09-29 by the internet-research agent of session
`session_01W21GKQhsdhoE9jbxQScFr5` for
`../archive/inplace_update/05_INPLACE_BIT_UPDATE_BRIEF_2026-09-29.md` (brief 05; the spike
it briefed closed MEASURED 2026-09-30). All sources were
opened on **2026-09-29**. Nothing here is a measurement of this system except
the OpenAlex header probe in §F.

Marks used in this addendum:
- **[read]** — the primary document (full text, official doc page, source
  file or repository) was opened and the quoted passage was found in it.
- **[read: abstract]** — only the publisher/arXiv abstract page (or
  bibliographic record) was opened; body claims stay unverified.
- **[snippet]** — the primary could not be opened (paywall, bot block, JS
  page); only a search summary was seen.
- **NOT FOUND** — no primary source carrying the claim could be located.
- **inferred** — this agent's reasoning, not a statement of any source.

Results on 2004–2007 hard disks (Lester et al., Büttcher & Clarke) measured
seek-bound disk I/O; their verdicts do not transfer to an mmap'd shard on
NVMe except as design patterns. Results on MS MARCO v1 (8.8M passages) do not
transfer to 150M documents without measurement.

### A. Verification of brief 05 §3 sources

| # | Source (as cited in brief) | Correct identifier | Mark | Claim in brief | What the source says | Verdict |
|---|---|---|---|---|---|---|
| 1 | Lester, Zobel, Williams 2004 (researchgate 221574123) | ACSC 2004, pp. 15–22; PDF people.eng.unimelb.edu.au/jzobel/fulltext/acsc04.pdf | [read] | in-place wins only at LOW update rate | Abstract: "re-merge is for large numbers of updates the fastest approach, but in-place update is suitable when the rate of update is low or buffer size is limited." | Supported. |
| 2 | people.eng.unimelb.edu.au/jzobel/fulltext/ipm06.pdf | Lester, Zobel, Williams, IPM 42(4):916–933 (2006), doi 10.1016/j.ipm.2005.09.005 | [read] | same | Same verdict; plus "with careful design of … free-space management, in-place update can be improved by around an order of magnitude over a naïve implementation"; gain "almost entirely due to" keeping short lists in the vocabulary; over-allocation gave little. Hardware: Pentium IV 2.8 GHz, 2 GB RAM; WT10g (1.7M docs) and GOV2 (25M docs, 426 GB). | Supported, but disk-seek era; the *hybrid* in this paper is short-lists-in-vocabulary, not "in-place long / merge short". |
| 3 | Büttcher & Clarke (Springer 10.1007/s10791-007-9042-8) | Büttcher, Clarke, "Hybrid index maintenance for contiguous inverted lists", Information Retrieval 11(3):175–207, 2008 | [read: abstract] (Crossref metadata); body via Büttcher PhD thesis 2007 ch. 6 [read] (uwaterloo DSpace PDF); SIGIR 2006 (with Lushman) and ECIR 2006 papers [snippet] | hybrid (in-place long lists, merge short) beats both | Thesis §6.4.6: hybrid "is not always clear" to be better for non-contiguous lists; HIMC "should always be preferred over Immediate Merge" (same query speed, better update speed); HLMNC up to 9% faster updates than Logarithmic Merge with query time within 3%. Thesis §2.5: in 2007 "nobody has actually been able to come up with an implementation of in-place update that performs better than merge update"; relative performance "entirely depends on the operating characteristics of the hard drive(s)". | **Overstated.** Hybrid dominates Immediate Merge; against Logarithmic Merge it is a trade-off, not a win on both axes. All HDD-era. |
| 4 | ScienceDirect S030643791400180X (MFIS 2014) | Jung, Roh, Shin, Park, "Inverted index maintenance strategy for flashSSDs: Revitalization of in-place index update strategy", Information Systems 49:25–39 (2015), doi 10.1016/j.is.2014.11.004 | [read: abstract] (Crossref metadata; PII matches); body [snippet] (ScienceDirect 403) | in-place revived on SSDs; non-contiguous lists, flash parallelism | Snippet: MFIS "stores the posting list of each term non-contiguously and exploits the internal parallelism of flashSSDs"; up to 14.93× vs Immediate Merge, 2.33× vs SSD-aware Hybrid. | Identifier correct (print year 2015). Claim plausible, body unread. |
| 5 | arXiv 2211.06030 (Moffat & Mackenzie IPM 2023) | Moffat, Mackenzie, "Efficient immediate-access dynamic indexing", IPM 60(3):103248 (2023), doi 10.1016/j.ipm.2022.103248 | [read] | extensible arrays, ~2 B/posting; growable format | "incremental document-level indexing using as little as two bytes per posting"; measured on WSJ and Wikipedia with ⟨d, f_t,d⟩ postings (BM25-era, not learned impacts). Structure is linked fixed-size blocks ("extensible lists"), not extensible arrays; the extensible-array variant is a separate paper (ADCS 2022, doi 10.1145/3572960.3572984). §6.1: "We have not considered document deletions nor updates". Dynamic pruning "would require allocation of an additional 4-byte field" per head block. | **Partly wrong:** ~2 B/posting holds for document-level frequency postings only; the structure is append-only with no deletes. |
| 6 | Springer 10.1007/978-3-032-21324-2_1 (Rule & Mackenzie ECIR 2026) | Rule, Mackenzie, "Fast, Compact, Immediate-Access Indexing for Learned Sparse Retrieval Systems", ECIR 2026, LNCS pp. 3–16 | [read] (author PDF jmmackenzie.io/pdf/rm26-ecir.pdf; Crossref metadata; Springer page itself bot-blocked) | closest work; growable format | Clean-room linked-block index for LSR; impacts as 1 uncompressed byte, VByte doc ids; **per-list upper bound (1 byte) "checked and updated as new postings are inserted"**; MaxScore only, BMW left to future work; linked-block "supports rapid insertion, but no deletion". MS MARCO v1 8.8M, single core; SPLADEv3 full collection: 3,441 MiB at B=64 for 1.48B postings (≈2.4 B/posting, computed here), MaxScore 83.3 ms vs PISA 35.9 ms. Repo github.com/JMMackenzie/lslb. | Exists, correctly cited. Append-only, no deletes; partially anticipates Mechanism C at list granularity (see §B.2). |
| 7 | arXiv 2605.01260 (Write-Read Decoupling survey) | Liang, Yang, Qiu, Mao, Ma, Zhu, Wang, submitted 2026-05-02 | [read] | Uber Sia, Alibaba Havenask route scalar fields to O(1) in-place | §4.1: Sia — "Stateless Searcher nodes pull pre-built segments. Zero live indexing occurs on serving nodes." §4.4: Havenask — full / incremental (30–60 min) / real-time build modes; no in-place attribute path described. §4.5 "In-Place Partial Updates" attributes O(1) in-place attribute updates to **Vespa's Proton** ("updated in-place in O(1) time … immediate query visibility", durability via a Transaction Log Service) and to the authors' in-house **ScaleSearch**. | **Wrong attribution.** Replace Sia/Havenask with Vespa Proton attributes (+ ScaleSearch). Scalar-field only; no posting-list in-place. |
| 8 | github.com/alibaba/havenask wiki | — | [read] (wiki index only; Chinese "实时功能使用文档" page not opened) | as #7 | Wiki advertises second-level updates; no in-place claim seen. | Not evidence for the brief's claim. |
| 9 | US 10474650 | US 10,474,650 B1, Google LLC, "In-place updates for inverted indices" (Sivathanu, Goyal, Mathews); priority 2013-05-24, granted 2019-11-12 | [read] (Google Patents) | provisioning empty posting positions = the CLOSED slack track | Abstract: "provision empty positions in posting lists to enable in-place updating"; count per list "based on the rate of updates for a particular term" (e.g. every 5th vs every 100th position); "Removing a document from the posting list may generate a new open position"; skip table updated when moved ids cross its boundaries. No block maxima / score bounds; no eviction. | Supported; also prior art for **dead-slot reuse** (brief §2.3 step 1). |
| 10 | arXiv 2607.29173 (MERIT) | Wu, Jin, Cheng, Ni, Li, Chen, Yao, Song, Shen, "MERIT: Efficient In-Place Deletion for Dynamic Graph-Based Approximate Nearest Neighbor Indexes", submitted 2026-07-31, rev. 2026-08-19 | [read: abstract] | versioned-edge invalidation; 3–19× faster deletes, recall stable; cited for "epoch tags, atomic publish by one write" | Abstract: "versioned-edge invalidation that immediately filters all stale incoming edges"; "up to 3.02×–18.87× faster deletion than SOTA". | Exists; numbers match. **Does not support atomic publish / crash safety** — it is in-memory graph deletion. Relevant only as "version tags filter stale references". |
| 11 | alphaxiv 2502.13826 (IP-DiskANN) | arXiv 2502.13826, Xu, Manohar, Bernstein, Chandramouli, Wen, Simhadri, "In-Place Updates of a Graph Index for Streaming Approximate Nearest Neighbor Search", 2025-02-19 | [read: abstract] | in-place vector-index updates | Processes inserts and deletes directly "without accumulating updates in batches"; "stable recall over various lengthy update patterns". | Supported (alphaxiv is a mirror; use the arXiv id). |
| 12 | arXiv 2105.09613 (FreshDiskANN) | Singh, Subramanya, Krishnaswamy, Simhadri, 2021-05-20 | [read: abstract] | in-place vector updates | "Thousands of concurrent real-time inserts, deletes and searches per second", >95% recall@5, 5–10× lower freshness cost. Design is RW/RO temp indexes + StreamingMerge (see `01_RESEARCH.md` §2), i.e. a delta layer, not in-place. | Exists; it is prior art for the **delta** arm, not for in-place. |
| 13 | dl.acm.org/doi/10.1145/3600006.3613166 (SPFresh) | Xu et al., SOSP 2023, pp. 545–561; arXiv 2410.14452 | [read] (arXiv full text; Crossref metadata) | "SPFresh is the clustered-index analogue of Mechanism B" | LIRE appends a new vector "at the tail of its nearest posting" and splits/merges/reassigns boundary vectors; a 1-byte per-vector version ("seven bits for re-assign version and one bit for deletion label") drops stale replicas at search time; crash recovery = periodic snapshot + WAL, with **block-level copy-on-write** and freed blocks held until the next snapshot "so all the data blocks modified in the interim can be rolled back". | Exists. Analogy **overstated**: SPFresh places a vector in its *nearest* partition and re-balances; Mechanism B places a posting in whichever block owns a dead or minimum slot. SPFresh is, however, direct prior art for Mechanism D's version tags *and* shows the CoW that D lacks (see §D). |
| 14 | lmdb.tech/doc | LMDB `mdb.c` / `lmdb.h` (github.com/LMDB/lmdb, branch mdb.master) | [read] (source; lmdb.tech TLS failed) | dual meta pages, txn id written last | `mdb_env_write_meta`: meta slot `toggle = txnid & 1`; with `MDB_WRITEMAP` the fields are stored, then (non-x86 only) `__sync_synchronize()` "ITS#7969", then `mm_txnid` last, then `msync(MS_SYNC)` of the meta page; data pages are flushed and synced **before** the meta write (`mdb_page_flush` → `mdb_env_sync0` → `mdb_env_write_meta`). `mdb_env_pick_meta` takes the larger txnid. Pages reachable by a live reader are never overwritten (copy-on-write B+tree; "Read transactions prevent reuse of pages freed by newer write transactions"). `lmdb.h`: "Do not use LMDB databases on remote filesystems … possibly memory map sync". | Supported as a pattern; the brief omits the part that makes it safe (CoW, never overwrite reachable data; sync data before meta). |
| 15 | researchgate 221301210 (Carmel et al.) | Carmel, Cohen, Fagin, Farchi, Herscovici, Maarek, Soffer, "Static index pruning for information retrieval systems", SIGIR 2001, pp. 43–50, doi 10.1145/383952.383958 | [snippet] (ResearchGate/ACM 403; Semantic Scholar record confirms authors; abstract elided); described in #16 [read] | ε-guarantee on top-k | Jiang et al. (#16): Carmel et al. "proposed two methods, UP, which uses a global cut-off on the impact scores of postings, and TCP, which selects the highest impact postings from each inverted list". | Citation correct; ε-guarantee not verified from the primary. |
| 16 | research.engineering.nyu.edu/~suel/papers/prune.pdf ("Suel") | Jiang, Rodriguez, Suel, "Improved Methods for Static Index Pruning" (venue not printed in the PDF) | [read] | static pruning prior art | Static pruning removes "postings that are unlikely to lead to top results"; related-work taxonomy above. | Supported; the brief should name all three authors. |
| 17 | "truncation to bounded top set → ~65% query time, no precision loss" | — | NOT FOUND | as stated | Only search-engine summaries carry the sentence; no primary located (Carmel, Jiang et al., Nguyen 2009 ceur-ws Vol-480 paper9 all opened — none contains it). The "truncating to a bounded number of top-ranked elements + term combinations" wording matches P2P query-driven-indexing work, not static pruning. | **Drop the number.** |
| 18 | arXiv 2405.01117 (Block-Max Pruning for LSR) | Mallia, Suel, Tonellotto, SIGIR 2024 (per Rule & Mackenzie ref. [25]) | [read: abstract] | cited under "monotone loosening" row | Query-time block filtering over static indexes; no index updates. | Exists; not about updates. |
| 19 | github.com/nowledge-co/hawdb/issues/292 | "search: block-max pruning for long doclists", @hawkingrei, 2026-09-04, open, no comments | [read] | "hints at overlay adjustments" | "The mini-delta overlay documents are few (8 MiB budget) and always scored exhaustively"; "pruning applies to immutable segment postings only"; bounds must stay "sound under filtering (a filter only removes candidates)". | **Misread.** It keeps bounds on immutable segments and scores the overlay exhaustively — evidence *for* the delta-buffer design, not for in-place bound loosening. |

Brief §1.1 side claims:
- **LLM citation fabrication.** "45% of the real ones carry field errors, DOI
  worst" = Linardon et al., *JMIR Mental Health* 2025;12:e80371, doi
  10.2196/80371 — GPT-4o, six simulated mental-health reviews: 19.9%
  fabricated overall (6% / 28% / 29% by topic familiarity); of real
  citations "45.4% contained bibliographic errors, most commonly incorrect or
  invalid Digital Object Identifiers" [read: press release,
  eurekalert.org/news-releases/1106130]. The **"11–57%" range: NOT FOUND** in
  any primary opened; GhostCite (arXiv 2602.06718) reports 14.23–94.93%
  across 13 LLMs and 40 domains [snippet]; the Lancet audit (Topaz et al.
  2026) reports ~57 fabricated-citation papers per 10,000 — a different
  quantity [snippet]. Replace the range with the single-study figures above.
- **OpenAlex pricing/limits** — see §F; mostly correct, "keys mandatory" is
  no longer accurate.

### B. Novelty claims

**B.1 Insert-by-eviction into a bounded (top-λ) posting list under churn —
PARTIALLY ANTICIPATED.**
- Yi, Yu, Yang, Xia, Chen, "Efficient maintenance of materialized top-k
  views", ICDE 2003 [read] (cse.ust.hk/~yike/topk/icde03.pdf): a top-k view
  "is not self-maintainable"; "Deletions and updates on the base table may
  cause tuples to leave the top-k view, resulting in expensive queries over
  the base table to 'refill' the view"; they keep a top-k′ view with
  k ≤ k′ ≤ k_max. A SEISMIC list truncated to λ is exactly a materialised
  top-λ view of one column; inserts that beat the minimum displace it
  (trivial), and the known hard case is **deletion → refill**, which brief 05
  §2.3 does not address (it reuses the dead slot for whatever arrives next).
- Eades, Wirth, Zobel, "Immediate text search on streams using apoptosic
  indexes", ECIR 2022, doi 10.1007/978-3-030-99736-6_11 [read: abstract; body
  described in Moffat & Mackenzie 2023 §2 [read]]: fixed slab, circular
  buffer, "expired postings are simply overwritten, without a specific
  deletion operator … replaced on a one-for-one basis" — bounded capacity
  with **age**-based eviction.
- US 10,474,650 (#9): deletion creates an open position that later inserts
  reuse — dead-slot reuse.
- Bruch, Nardini, Ingber, Liberty, "An Approximate Algorithm for Maximum
  Inner Product Search over Streaming Sparse Vectors" (Sinnamon), TOIS 2024,
  arXiv 2301.10622 [read]: streaming sparse MIPS with insert and delete. It
  discusses marking postings "deleted" and having them "recycled when a new
  posting is inserted into the inverted list", and **rejects** it because
  retrieval must then branch on every posting; it uses full deletion.
- Earlybird (ICDE 2012) [read], Rule & Mackenzie 2026 [read]: append-only,
  no eviction. JASS / impact-ordered indexes: no update mechanism found
  [snippet-level search only].
- Verdict: each ingredient is known (bounded top-k view maintenance, slot
  reuse, overwrite-on-capacity). Not found: **weight-based eviction inside
  the truncated lists of a clustered learned-sparse index (SEISMIC) as its
  update mechanism**, or any measurement of its quality. Bar S0-2 remains
  the right test; the refill problem is the prior-art prediction of where it
  fails.

**B.2 Keeping block/list upper bounds valid under inserts by loosening
instead of recomputing — PARTIALLY ANTICIPATED (for exact DAAT); SEISMIC
case open.**
- Macdonald & Tonellotto, "Upper Bound Approximations for BlockMaxWand",
  ICTIR 2017, pp. 273–276 [read] (eprints.gla.ac.uk/145572): motivated
  explicitly because recorded block bounds are "disadvantageous in
  situations such as when an index must be updated"; approximate bounds from
  tf_max "can be easily updated when new documents are added to a term's
  posting list"; being "greater than exact upper bounds, [they] limit the
  skipping abilities of BMW, forcing more blocks to [be] processed" (e.g.
  BM25, K=20: BMW −34% vs WAND with exact bounds, −17% with approximate).
  ClueWeb12-B13. This is the cost side of Mechanism C, measured.
- Macdonald, Ounis, Tonellotto, "Upper-bound approximations for dynamic
  pruning", TOIS 29(4):17 (2011) [read]: query-time approximate (looser)
  term bounds; safe for effectiveness, costlier in postings scored.
- Rule & Mackenzie ECIR 2026 [read]: list-level bound raised on insert —
  monotone loosening at list granularity, append-only.
- Asadi & Lin, "Fast, Incremental Inverted Indexing in Main Memory for
  Web-Scale Collections", arXiv 1305.0699 [read]: BMW "is not directly
  applicable for incremental indexing" — block bounds would need global BM25
  statistics; "either use statistics at the time the block is written, which
  might compromise correctness, or continually update the upper bounds …
  which is slow". *Inferred:* learned-sparse impacts are precomputed, so
  this particular obstacle does not apply to SEISMIC.
- Lucene `Impacts.getImpacts` [read] (lucene.apache.org 9.12 javadoc):
  "There is no guarantee that these impacts actually appear in postings,
  only that they trigger scores that are greater than or equal to the
  impacts that actually appear" — bounds are conservative by contract.
  *Inferred:* segments are immutable and deleted docs stay in postings until
  merge, so Lucene bounds are stale-high under deletes by construction.
- hawdb #292 (#19): bounds on immutable segments only; overlay scored
  exhaustively.
- **SEISMIC-specific caveat (changes the design premise):** SEISMIC summaries
  are not upper bounds. Bruch et al. SIGIR 2024 §5.3 [read]: after α-mass
  pruning and 8-bit quantisation "any such method may take away the
  conservatism of the summary". Upstream issue TusKANNy/seismic#19 [read]
  (2026-04-15) removes singleton components as well. *Inferred:* (a)
  inflating a summary can only increase that block's estimate, but SEISMIC's
  skip test is against a moving heap threshold, so a looser bound that
  finds good documents earlier can raise the threshold and cause *other*
  blocks to be skipped — recall is **not** guaranteed monotone per query;
  (b) summaries are sparse (bitfield/ids + u8 values + EF offsets), so a new
  document's components absent from the summary cannot be added in place,
  and a per-block scalar inflation cannot represent them.
- Verdict: loosening bounds so they stay valid under inserts is known for
  exact document-at-a-time pruning (list-level in Rule & Mackenzie; block-level
  approximate bounds costed in Macdonald & Tonellotto 2017). Not found: a
  per-block inflation multiplier over SEISMIC's (already non-conservative)
  summary vectors, or its recall/latency trade-off.

### C. SEISMIC specifics

- Papers [read, arXiv full text]: Bruch, Nardini, Rulli, Venturini, SIGIR
  2024, arXiv 2404.18812 (λ-truncation, β clustered blocks, α-mass + u8
  summaries); CIKM 2024 κ-NN graph variant, arXiv 2408.04443; ECIR 2025
  scalability study, arXiv 2501.11628. None mentions insertion, deletion,
  incremental build or a mutable variant (text search of all three for
  update/insert/delete/increment/stream found only heap operations and the
  Sinnamon citation).
- Repository `TusKANNy/seismic` [read via GitHub API]: licence **MIT**; last
  push 2026-09-10; 19 issues/PRs, none about insert/update/delete/merge
  (matches the earlier [read] line above). Issue #19 (skip-singleton
  summaries, 52% summary bytes saved, MS MARCO v1) is the only format-level
  discussion; it confirms the summary sub-components (bitfield ids, u8
  values, EF offsets, per-block f32 minimums/quants).
- Sibling repos in the org (kannolo, vectorium, tachiom — all MIT): no update
  work seen at README level. The group's own curated list
  (TusKANNy/awesome-learned-sparse-retrieval, pushed 2026-08-04) lists
  Sinnamon as its only streaming/dynamic entry.
- Spare bits: no upstream documentation of spare bits was found. This
  repo's audit records each packed posting as `(forward_offset:48, len:16)`
  u64 (`docs/seismic_150m_testbed/09_CROSS_SHARD_MMAP_AUDIT.md` §file table),
  i.e. **postings carry no weight** — eviction by minimum weight needs the
  side array brief 05 §2.3 proposes (or a forward-index read per candidate).
  The reader casts postings with `bytemuck::cast_slice` to `u64`
  (`.claude/plans/done/seismic-c1-mmap-spike.md`), which requires 8-byte
  alignment — so postings are aligned in the served files (inferred).
- OpenSearch neural sparse ANN [read] (docs.opensearch.org, latest):
  segments with fewer documents than `approximate_threshold` are indexed as
  plain `rank_features` and queried exactly; larger segments get SEISMIC
  (`n_postings`, `cluster_ratio`, `summary_prune_ratio`). The production
  SEISMIC deployment is therefore "small mutable tier exact, large tier
  rebuilt per segment" — the delta-layer pattern. Rebuild on merge and the
  3.9 memory-mapped native engine are [snippet] (OpenSearch blog / search
  summary).

### D. Crash safety and atomic publish on mmap'd files

| Question | Finding | Source |
|---|---|---|
| Is an aligned 8-byte store atomic to concurrent readers on x86-64? | Yes: Pentium and later guarantee "reading or writing a quadword aligned on a 64-bit boundary" is atomic; P6+ also unaligned within one cache line. | Intel SDM Vol. 3A §9.1.1 "Guaranteed Atomic Operations" [read, via xem.github.io mirror of the SDM page; Intel PDF not opened] |
| … on AArch64? | Aligned single-register 64-bit loads/stores are single-copy atomic. | Arm ARM DDI 0487 §B2.2.1 [snippet] (JS page not renderable); Rust `std::sync::atomic` lists `aarch64` among targets with 8-byte atomic loads [read] |
| Is it legal to read it with plain loads while another process writes? | Not in the Rust/C++ model: "data races are undefined behavior … conflicting non-synchronized accesses where at least one of the accesses is non-atomic". Relaxed atomic loads of ≤ 8 bytes are allowed even on read-only mappings on x86_64/aarch64. | doc.rust-lang.org/std/sync/atomic [read] |
| Ordering of a "publish" flip | x86-64 (TSO) keeps store order; ARM does not — LMDB inserts `__sync_synchronize()` before writing `mm_txnid` "if not x86" (ITS#7969). The flip must be a release store and the reader's header read an acquire load. Earlybird uses the same single-writer pattern with a volatile `maxDoc` memory barrier — but only over **appended** data. | LMDB `mdb.c` [read]; Earlybird ICDE 2012 §V [read] |
| Coherence between processes | Linux `MAP_SHARED`: "Updates to the mapping are visible to other processes mapping the same region". Windows: views of the same file are coherent within and across processes, **except** remote files ("each computer only sees its own writes") and **not** coherent with `ReadFile`/`WriteFile`. | man7 mmap(2) [read]; MS Learn MapViewOfFile remarks [read] |
| Durability / ordering to disk | msync gives no ordering among dirty pages; the kernel may write back any page (including the header page) at any time. `MS_SYNC` waits; on Linux `MS_ASYNC` is a no-op since 2.6.19. Windows `FlushViewOfFile` "does not wait … until the changes are flushed from the underlying hardware disk cache"; must be followed by `FlushFileBuffers`; over a network it only guarantees the data left the local machine. LMDB syncs data pages **before** writing the meta, then syncs the meta. | man7 msync(2) [read]; MS Learn FlushViewOfFile [read]; LMDB `mdb.c` [read] |
| Torn writes after power loss | An interrupted sector write can read back as garbage/zeros for the whole sector ("powersafe overwrite" is an assumption; SQLite assumed it false until 3.7.10). NVMe AWUPF bounds the all-or-nothing write size [snippet]. An aligned 8-byte header never spans a sector, but the page holding it may be written back with other in-progress edits. File-system persistence properties differ widely; 60 crash vulnerabilities found in 11 production systems. | sqlite.org/psow.html [read]; Pillai et al. OSDI 2014 [read: abstract]; NVMe AWUPF [snippet] |
| How SQLite WAL does it | Never overwrites the database while readers may need the old page: commits append to the WAL; each reader fixes an "end mark"; checkpoints "must stop when [they reach] a page … past the end mark of any current reader". "WAL does not work over a network filesystem." | sqlite.org/wal.html [read] |
| 9p (this host's shared mounts) | v9fs cache modes: `none`, `readahead`, `mmap` ("read-ahead + writeback file cache"), `loose`, `fscache`; loose caches "do not necessarily validate cached values on the server". Reports of data corruption with `cache=mmap` under concurrent writes exist [snippet]. | docs.kernel.org/filesystems/9p.html [read]; LKML/issue reports [snippet] |

**Verdict.** "Aligned 8-byte writes are atomic on x86-64": **confirmed**, and
also on AArch64 — for *visibility to concurrent readers*, provided the
fields are accessed as atomics (the current reader uses plain `&[u64]`
slices) and the flip is release/acquire. "mmap coherence holds on both
platforms": **confirmed for local files between mapped views only**; not for
remote/9p/SMB files and not against `ReadFile`/`WriteFile`. "A crash
mid-batch leaves epoch e serving": **refuted as written** (inferred from the
LMDB, SQLite and SPFresh designs above). Epoch tags hide *new* content from
epoch-e readers, but every slot overwritten in place loses its *old*
content: an evicted live posting, a slot reused in the same batch it was
freed, a raised summary byte or an inflation byte cannot be restored by
reading epoch e. LMDB, SQLite WAL and SPFresh all avoid this by never
overwriting data a published version can reach (CoW pages, WAL, CoW blocks
held until the next snapshot). And atomicity is not durability: without
"sync data, then write+sync header", the header page can reach disk before
the slot pages it publishes.

### E. Newer work (2024–2026) the brief missed

- **Sinnamon** (TOIS 2024, arXiv 2301.10622) [read] — the only dynamic
  (insert+delete) sparse-MIPS index from the SEISMIC authors; per-document
  sketches, full deletion; argues against tombstone-and-recycle on retrieval
  cost grounds. Relevant to B1/B3: the "three masks" decoder change must be
  measured, not assumed free.
- **Macdonald & Tonellotto ICTIR 2017** [read] — measured cost of loosened
  block bounds (above); gives S0-3 a prior.
- **Yi et al. ICDE 2003** [read] — top-k view refill theory; gives S0-2 a
  predicted failure mode.
- **Rule & Mackenzie ECIR 2026** [read] — already cited, but its limits
  (append-only, no deletion, MaxScore only, MS MARCO v1) were not.
- **OpenSearch neural sparse ANN** [read] — production precedent for the
  hybrid rule at *segment* granularity (exact small tier, SEISMIC large
  tier): supports arm A1 as the industry baseline.
- **IP-DiskANN 2025, MERIT 2026** [read: abstract] — in-place deletion is an
  active topic for graph ANN, not for clustered sparse indexes.
- **Gallagher, Mackenzie, Moffat, SIGIR-AP 2025** [read: first page] —
  query time of dynamic pruning grows linearly with collection size combined
  with depth; background for scaling any MS MARCO-size result to 150M.
- **Song, Zhu, Yang arXiv 2608.16309 (2026-08-17)** [read: abstract] —
  static index pruning across engines incl. SEISMIC (1.2–6.6× latency);
  static only, no update path.
- **SINDI arXiv 2509.08395**, **GPUSparse arXiv 2606.26441**,
  **Dynamic Superblock Pruning SIGIR 2025** — static indexes; no update path
  ([read: abstract] for SINDI, others [snippet]).

### F. OpenAlex API facts (read 2026-09-29)

| Fact | Value | Source |
|---|---|---|
| API key | Optional for "basic queries"; "to use the API at any real scale … a free API key". Passed as `api_key=` or `Authorization: Bearer`. | help.openalex.org/api-reference/authentication, "Last updated August 19, 2026" [read] |
| Daily budget | Keyless **$0.10/day**; free key **$1/day** ("10× that") | help.openalex.org/access/example-costs, updated 2026-08-09 [read]; pricing page updated 2026-08-11 [read] |
| Prices | single entity $0; list/filter $0.0001/call; search $0.001/call; content (PDF/XML) $0.01/call. $1 covers unlimited singletons, 10,000 list calls, 1,000 searches or 100 PDFs. | blog.openalex.org (2026-02-24) [read]; example-costs page [read] |
| Rate limit | **100 requests/second**; exceeding the budget or the rate returns HTTP 429 | authentication page [read] |
| Polite pool / mailto | Not mentioned anywhere in the current docs | authentication page [read] |
| Paid plans | Member $5,000/yr ($20/day); Member+ $10,000/yr ($100/day); Partner $20,000+/yr; prepaid top-ups in $1 units, expire after 3 months | pricing page [read] |
| Live check (measured) | Three keyless GETs from this host on 2026-09-29: `x-ratelimit-limit-usd: 0.1`, `x-ratelimit-limit: 1000` (credits); `x-ratelimit-cost-usd` 0 (singleton), 0.0001 (filter), 0.001 (search); `GET /rate-limit` without a key returns "Authentication required". | `curl -D -` against api.openalex.org, 2026-09-29 |

Differences from what was believed: the February 2026 blog gave the keyless
budget as $0.01/day; the August 2026 docs give $0.10/day. "Keys mandatory"
(brief 05 §1.1, `01_RESEARCH.md` §1.2) is no longer accurate for low
volumes. `src/lib/openalex.py` (not edited here) documents "mailto polite
pool (10 req/s)" and caps **calls** at 900/day; the budget is in **dollars**,
so free singleton lookups should not count against it, while 900 search
calls would cost $0.90 against a $1 key budget (or exceed the $0.10 keyless
budget after 100). The coordinator owns that fix.

### Consequences for brief 05 (most important first)

1. **§2.5 Mechanism D and bar B7 — the crash claim does not hold as
   designed.** Only writes into slots that were already dead *as of the
   published epoch* are safe to roll back by epoch. Eviction of a live
   posting, same-batch reuse, and summary/inflation raises need copy-on-write
   or an undo record of the old 8 bytes (SPFresh CoW blocks + snapshot/WAL;
   LMDB never overwrites reachable pages). Required order: write slots →
   sync data → release-store + sync header (Windows: `FlushViewOfFile` then
   `FlushFileBuffers`). B7's "kill -9 mid-batch" tests only process death —
   `MAP_SHARED` dirty pages survive it — so it cannot detect ordering or torn
   writes; B7 needs power-loss simulation (VM hard reset, or crash-state
   enumeration in the style of Pillai et al. OSDI 2014).
2. **§2.4 Mechanism C and bar S0-3 — the premise "bounds, so recall cannot
   drop" does not hold for SEISMIC.** Summaries are α-mass-pruned and
   quantised, not upper bounds (SIGIR 2024 §5.3), and the skip test uses a
   moving heap threshold, so recall is not monotone under loosening
   (inferred). Components missing from a sparse summary cannot be added in
   place. S0-3 must record recall/overlap as well as block visits, and
   should take Macdonald & Tonellotto 2017's loosened-bound cost as its
   prior.
3. **§2.3 Mechanism B and bar S0-2 — two failure modes named by prior art.**
   (a) Deletions leave truncated lists short with no refill (Yi et al. 2003):
   S0-2 should separate loss caused by deletions from loss caused by
   inserts. (b) A new posting lands in the block that owns the free/min slot,
   not in its nearest cluster — unlike SPFresh, which appends to the nearest
   partition and re-balances. The §3 row "SPFresh is the clustered-index
   analogue of Mechanism B" should say this. Postings carry no weight
   (`offset:48,len:16`), so the minimum-weight side array is mandatory.
4. **§3 table and source list — corrections.** Sia/Havenask → Vespa Proton
   attributes (+ ScaleSearch), scalar fields only; delete the "~65% query
   time" number (NOT FOUND); "hybrid beats both" → "hybrid dominates
   Immediate Merge; vs Logarithmic Merge it is a trade-off (HDD-era)";
   Moffat & Mackenzie "extensible arrays, ~2 B/posting" → "linked-block
   extensible lists, ~2 B/posting for document-level frequency postings, no
   deletes" (extensible arrays = ADCS 2022); Rule & Mackenzie: append-only,
   no deletes, list-level bound raised on insert; MERIT: in-memory graph
   deletion, not crash-safe publish; hawdb #292: supports the overlay
   design, not in-place loosening; "Suel" → Jiang, Rodriguez, Suel; MFIS is
   Information Systems 49 (2015); IP-DiskANN → arXiv 2502.13826.
5. **§3 novelty rows** — both become **partially anticipated**: B.1 by Yi et
   al. 2003 (top-k views), the apoptosic index, US 10,474,650 and Sinnamon;
   B.2 by Macdonald & Tonellotto 2017, Macdonald et al. 2011 and Rule &
   Mackenzie 2026. What remains unpublished is their application to
   SEISMIC's truncated, clustered lists and non-conservative summaries — the
   bars stay the test.
6. **§7 "atomic 8-B writes + mmap coherence hold on both platforms"** —
   qualify: true for aligned fields on local files between mapped views;
   the reader must use atomic (Relaxed) loads for mutable fields and an
   acquire load for the header; not true on remote/SMB/9p files, and
   Windows views are not coherent with `ReadFile`/`WriteFile`. In-place
   writes stay on local-disk copies (the brief already says so for 9p).
7. **§1.1 facts** — OpenAlex: keyless access exists ($0.10/day); key
   $1/day; prices and 100 req/s confirmed; no polite pool. LLM citations:
   replace "11–57%" with Linardon et al. 2025 (GPT-4o, one domain: 19.9%
   fabricated, 6–29% by topic; 45.4% of real citations with errors, DOI most
   common).
8. **§2.7 hybrid rule and §4 write-pattern rows** — the in-place-vs-merge
   evidence is seek-bound HDD work from 2004–2007; it motivates the hybrid
   rule but gives no number for mmap on NVMe. The production precedent that
   *does* transfer is OpenSearch's per-segment rule (exact small tier,
   SEISMIC large tier), which is arm A1's shape.
9. **§2.6 decoder** — Sinnamon's authors rejected tombstone-and-recycle for
   branch cost at retrieval; B1/B3 should report the mask-check overhead
   with zero patches applied, not only bit-identical output.

### Sources that could not be opened (2026-09-29)

Springer chapter pages (bot redirect; Rule & Mackenzie read via the author
PDF instead); ScienceDirect (MFIS body, Lester IPM abstract page — PDF read
from unimelb instead); ResearchGate (all IDs; content read from other copies
where possible); ACM DL body of Carmel et al. 2001; MDPI *Data* 11(5):122;
lmdb.tech (TLS error; source read instead); Arm developer documentation
pages (JS-rendered); the Havenask Chinese real-time wiki page; the Büttcher &
Clarke IR 2008 article body (thesis read instead).
