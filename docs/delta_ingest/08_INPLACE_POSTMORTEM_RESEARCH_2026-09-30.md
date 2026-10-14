# 08 — Post-mortem research 2026-09-30: is there any in-place route left after the NO-GO?

**Status:** ACTIVE (research record; feeds the delta_ingest track's next pre-registration — nothing here is dispatched)

**Premise (measured, `06_…` §"NO-GO 2026-09-30", closed track `../archive/inplace_update/`):** the in-place bit-update spike failed on posting-slot supply (dead slots cover 1.9 % of new-posting demand; 27 % of a shard's docs updated + 15 % new versus 6 % deleted per quarter), while its v3 encoder/decoder (exact, +1.3 %/query) and crash-safe updater (300/300) work. Question put to the literature 2022–2026: with list GROWTH (not slot reuse) as the obstacle, is there anything untried?

---

# Can anything make in-place or near-in-place updating of the SEISMIC shards work at 27% updated + 15% new docs per quarter?

Research pass, 2026-09-30, by an Opus agent dispatched from the closure session; recorded as a repository doc in the closure commit. Every candidate is DESIGN ONLY, EFFICACY UNMEASURED. Tags: **[read]** = I fetched and read the full text or page; **[snippet]** = search-result text only; **inferred** = my reasoning, not in any source. Before searching I checked `docs/delta_ingest/04_IMMUTABILITY_RESEARCH.md` (sources 1–19 plus §E) so I would not repeat its sources. Items it already covers are marked "(04 covered)".

## 0. Three facts from your own results file that change the question

Source: `data/eval_results/inplace_s0_20260930.json`, read 2026-09-30.

1. **The problem is membership turnover, not only list growth.** In S0-2 Q1, the 3,718 query-term lists hold 10.18 M base postings. The quarter placed 7.89 M postings into them: 3.48 M into dead slots and 4.41 M by eviction. It dropped 466 M. In R_sim's top-10, the share of inserted docs is 0.73, 0.65 and 0.57 (QA, QT, QD). The rebuild reference itself replaces most of what the queries see within one quarter. Any in-place scheme has to write roughly the posting volume of the lists it touches, spread over almost every block. That is why your copy-on-write (CoW) arms cost 4.5–5.6× the device bytes.
2. **Placement, not only supply, broke S0-3.** 98.6% of the placed postings landed in a block other than the one with the best summary dot product (`supp_placement`). That is what drove block visits to ×3.9. The same failure appears in the literature (§2, SPFresh's Vearch experiment).
3. **Encoder calibration looks mismatched (inferred, verify).** The base shard averages 1,647,141,424 / 18,799,322 = **87.6 nnz/doc**. The S0-1 re-encodes average **122.5 nnz/doc** (mean over 110 sampled files, range 88–144). If new vectors are systematically denser or heavier, the "inserted share 0.73" and part of the demand are inflated. The same bias would hit the delta layer's ranking: new docs would be favoured over base docs. Check this before any further spike, including the ones below. It costs one hour: compare the norm and nnz of re-encoded versus stored vectors for text-unchanged docs.

## 1. Growable, segmented or non-contiguous list layouts

| Candidate | Source | What it is | Cost to us | Gain versus our numbers | Verdict |
|---|---|---|---|---|---|
| **LinkedBlock for LSR** (Rule & Mackenzie, ECIR 2026) | https://JMMackenzie.io/pdf/rm26-ecir.pdf, pub. 2026-03 [read] | Each list is a chain of fixed B-byte blocks (B ≤ 256) in one slab; only appends; **no deletion**; a 1-byte list upper bound in the head block; MaxScore. At 8.8 M docs, SPLADEv3 MaxScore takes 83.3 ms versus PISA 35.9 ms (2–6× slower). The authors place it explicitly as the **fresh tier that is offloaded into the static index**, that is, a delta layer. | New index type | None beyond the delta layer: its own paper uses it as one | **Already covered by our delta layer** (04 covered the paper, not this framing) |
| Extensible arrays / immediate access (Moffat & Mackenzie IPM 2023; ACDS 2023) | https://arxiv.org/abs/2211.06030, v2 2023-01-11 [read: abstract] | About 2 B/posting, 2 GB/min ingest, insert-only | Same as above | Same | Already covered by delta layer (04 covered) |
| Apoptosic index (Eades, Wirth, Zobel, ECIR 2022) | described in rm26 §2 [read] | Circular slab; age-based overwrite | n/a | Age eviction is the wrong policy for a top-λ index | Not worth it (04 covered) |
| **SPFresh block controller: posting → block-list indirection, APPEND = rewrite the last block + CAS the mapping** | https://arxiv.org/pdf/2410.14452 (SOSP 2023, arXiv 2024-10) [read] | "APPEND only involves read-modify-write of the last block of a posting"; an in-memory block mapping of 40 B per posting; the free-block pool is garbage-collected on split | A v4 format: per-list block table, blocks can live anywhere. Your v3 epoch and free-slot bits and the crash-safe updater carry over (inferred) | Removes the fixed-slot supply limit. **Read locality (inferred):** SEISMIC already scans a list's summaries and then jumps to selected blocks, so blocks that are not contiguous add about one TLB/page miss per visited block, not a scan penalty. Summaries must stay contiguous per list and be rewritten per touched list. | Part of shortlist #3 |
| MFIS (flash, non-contiguous lists) | (04 covered) | | | | covered |

## 2. ID-level indirection so updated docs need no new postings

| Candidate | Source | What it is | Cost to us | Gain versus our numbers | Verdict |
|---|---|---|---|---|---|
| **SPFresh version map** | arXiv 2410.14452 §4.1–4.2 [read] | 1 byte per vector; an update bumps the version and appends a new replica; "old replicas with a stale version number are dropped during the search", with batched GC | Our v3 epoch tag + deletion bitset already do this | None new | Already covered (v3 epoch + delta masks) |
| Lucene updatable doc values: a "gen'd" per-segment file layered over the immutable core | http://shaierera.blogspot.com/2014/04/updatable-docvalues-under-hood.html [snippet]; Lucene 10.3 index package docs [snippet] | Per-field sidecar generations. **Postings never change**: updates go through delete + reinsert | n/a | n/a | Pattern only, and it is the same as the delta layer |
| Vespa attributes versus index fields | https://docs.vespa.ai/en/partial-updates.html [read] | True in-place updates for attributes (including weighted sets and tensors). Index fields: a CoW B-tree memory index is flushed to disk indexes, which are then merged | n/a | n/a | Already covered (LSM = delta layer) |
| Manticore RT kill-list + in-place attribute UPDATE | https://docs.manticoresearch.com/2.7.0/html/real-time_indexes.html [snippet] | "full-text field changes suppress a previous row version … using a kill-list" | n/a | n/a | Already covered |
| **Overlay-scored updates: keep the base doc's old postings as its candidate route, and score it with a replacement forward vector held in an override table (docid → new vector) inside the delta root** | **inferred** from two facts. (a) SEISMIC scores every candidate exactly with the forward index, so lists only produce candidates: Bruch et al. SIGIR 2024 [snippet: "aggressive static inverted index pruning while fully scoring documents with an unpruned forward index"]. (b) Meilisearch ≥1.6 diffs the old and new document versions and applies only the changed postings: https://www.meilisearch.com/docs/changelog/changelog [snippet] | Updated docs never enter delta SEISMIC shards and are not masked. The base stays byte-immutable (no 9p writes). One bitset test per scored candidate, plus a rare lookup. | A hook in the Rust scoring loop: if the doc's bit is set, score with the overlay row. Simulate first in the existing S0-2 harness: updated docs keep their base list membership and are scored with the new vector; compare against R_sim. About 1–2 days, mostly harness wiring (inferred). | Per quarter per shard it removes **5.15 M of the 7.98 M** docs that would otherwise enter delta SEISMIC generations (−65%). After the base-hash text filter (3.96:1 touched:text-changed, M7-seed) it is 1.30 M of 4.13 M (−31%). Fold-in trigger (a) fires about 1.5–2.8× less often. Risk: missed recall on **new** strong terms of text-changed docs (the old block summaries also do not know the new vector). M7 splits text changes 1,344 cosmetic / 302 minor / 871 substantive of 2,517, so about 65% are small; route "substantive" to the delta layer. It does **not** remove the BM25F/abstract share of the generation tax for text-changed docs. | **Worth a pre-registered spike (shortlist #1)** |

## 3. Changing the block-summary or pruning layer instead of the postings

| Candidate | Source | What it is | Cost to us | Gain | Verdict |
|---|---|---|---|---|---|
| Monotone loosening of bounds | Macdonald & Tonellotto ICTIR 2017 (04 covered) + your S0-3 | Inflating bounds | measured | ×3.9 block visits, FAIL | Dead (measured) |
| **Exact local re-summarisation + append-to-best-block + split (LIRE applied to SEISMIC blocks)** | SPFresh LIRE [read]: split at a length limit, reassign only boundary vectors. Ada-IVF, arXiv 2411.00970, 2024-11-01 [read, partial]: local re-clustering triggered by size, drift or **access "temperature"**; update time 62% of LIRE on an internal workload, −50% on BIGANN-SS at equal QPS. Quake, OSDI 2025, https://www.usenix.org/conference/osdi25/presentation/mohoney [snippet]: cost-model-driven partition maintenance, 4.5–126× lower update latency | New posting → argmax over the list's blocks of dot(summary_b, doc). Append there. Recompute that block's summary **exactly** from its members. Your blocks average about 12 docs (843,233 blocks / 10.18 M postings in lists_T), so a recompute reads about 12 forward rows (inferred). Split oversize blocks and GC tombstones at split time. | The v4 block-table format (§1) + a new S0-2/S0-3 simulation arm. Weeks, not days. | Targets exactly the two measured failures: supply (FAIL 1.9%) and misplacement (98.6% wrong block → ×3.9 visits). SPFresh's own motivation (Fig. 2): Vearch-style "append to nearest partition, no rebalancing" with 1/3 of vectors updated lost more than 1 recall point and had 4× tail latency. That is our S0-3 result in dense form, and LIRE is the published fix. Ceiling: it can remove only the SEISMIC share of the generation tax (about 11 of 27.7 ms/gen, M4), while BM25F sections still need the delta layer. It does **not** fix top-λ truncation drift (S0-2 membership 0.878/0.915/0.903 versus R_sim): lists must either grow past the cap or evict. | **Shortlist #3, conditional** |
| Hot-list-first maintenance (Ada-IVF "temperature") | arXiv 2411.00970 [read]: "only 15% of partitions were accessed during search … 80% of the updates affected partitions that were not accessed" | Maintain or re-derive only the lists that queries touch; leave cold lists stale | Small add-on to #2 or #3 | Unmeasured for us. Your hotset files (`hotset_hot50_1.6gb.json`) suggest the skew exists (inferred). | Fold into #2 as an option |

## 4. Learned-sparse-specific dynamic indexing, 2023–2026

- **Rule & Mackenzie ECIR 2026** [read]: the only LSR dynamic-index paper found. Append-only, no deletion, and framed as a fresh tier. Its future-work list names block-max (BMW) for LinkedBlock, which shows that nobody has done block-level summaries under updates for LSR.
- **Sinnamon** (Bruch, Nardini, Ingber, Liberty; arXiv 2301.10622, 2023-01-25; TOIS 2024) [read]: an insert/delete sparse MIPS index built on sketches. Deletion removes the id from the lists; tombstone-recycle is rejected. It is a different index, so adopting it means a rebuild (04 covered).
- **No SEISMIC follow-up adds updates.** Checked: SIGIR 2024, ECIR 2025 ×2, the pyseismic-lsr 0.5.2 PyPI page, SINDI 2509.08395, GPUSparse 2606.26441, Superblock Pruning SIGIR 2025, Song et al. 2608.16309. All are static [snippet].
- Ada-IVF, Quake and SPFresh/LIRE are the closest *clustered-index* maintenance literature, and SEISMIC blocks are per-list k-means clusters. 04 had SPFresh only as "the clustered-index analogue". The block-level transfer in §3 is not in 04.

## 5. Production partial-update mechanisms, 2023–2026: does anyone patch immutable postings in place?

**No.** Every system found either (a) updates only non-posting columns in place, or (b) is an LSM or delta design with masks:

- Vespa: attributes in place, indexes as memory index + disk merge [read].
- Lucene 10 / Elasticsearch: gen'd doc-values files; postings rewritten by delete + reinsert [snippet].
- Manticore: kill-lists, in-place attributes only [snippet].
- Milvus 2.5: WAL → growing → sealed immutable segments, L0 delete segments, compaction [snippet].
- Qdrant: a mutable sparse index for appendable segments; the optimizer builds immutable ones; sparse vectors are "point-level immutable" [snippet].
- LanceDB: unindexed fragments are flat-scanned; `optimize()` adds rows to the index incrementally [snippet].
- turbopuffer: WAL, with "unindexed data … searched exhaustively"; async indexing by separate nodes; SPFresh centroid index "incrementally updates clusters" (docs/concepts, and the ANN v3 post of 2026-05-05) [read].
- Meilisearch: LMDB CoW B-tree pages, with old/new document diffing so only changed postings are written [snippet].
- Havenask / Sia: scalar fields only (04 covered).

Not searched individually: Quickwit/tantivy, Sonic, Weaviate. I expect nothing new there, but that is inferred, not checked.

The only production system that grows postings in place (turbopuffer via SPFresh) does it for **dense single-assignment clusters**. It still fronts them with a WAL that is scanned exhaustively, which is a delta tier.

## 6. Hybrid cadence: which side of the in-place vs merge line are we on?

Our rates:
- 27% + 15% per quarter ≈ **0.46%/day** of docs touched.
- New docs alone: 0.16%/day.
- Text-changed updates after the base-hash filter: about 6.9%/quarter ≈ 0.08%/day.

Each published model puts us on a different side:
- **Lester/Zobel/Williams 2004/2006 and Büttcher & Clarke 2006/2008** (04 covered): the models are seek-cost and batch-buffer based. In-place wins only for small buffers or low rates. With **quarterly** batches touching 42% of docs, every one of them says merge or rebuild.
- **SPFresh**: evaluated at **1%/day** in place on a billion-scale disk index [read]. That is above our 0.46%/day, so by rate alone we are on the in-place side. It works only because (a) partitions grow by append plus local split, and (b) each vector sits in about one posting. Our index is heavily pruned: 40.4 M postings / 18.8 M docs ≈ **2.1 postings per doc**, so the per-doc posting fan-out is actually comparable (inferred). What SPFresh does not face is the **global top-λ truncation**, which turns inserts into evictions and refills (S0-2).
- **Conclusion (inferred):** the update rate itself is not what puts us on the merge side. Two things do: (i) the fixed-slot layout, which is already falsified, and (ii) quarterly batching combined with top-λ turnover. Your measured quarter replaced most of the query lists' effective content. At a daily cadence with growable blocks, the published evidence (SPFresh, Ada-IVF) says local maintenance is viable. At a quarterly cadence, nothing published says in-place beats a rebuild of the posting layer.

## Ranked shortlist (at most three)

1. **Overlay-scored updates.** Updated docs keep their base postings as the candidate route and are scored with an override forward vector; no new postings and no base writes.
   - Cheapest: a simulation in the existing S0-2 harness, then a Rust scoring hook.
   - Largest expected gain: −65% of the docs that enter delta SEISMIC generations per quarter (−31% after the text filter), with the base staying byte-immutable.
   - Pre-register overlap@10 versus R_sim with this arm next to the delta-layer arm, split by M7 change class.
   - It is an **extension of the delta layer**, not a replacement.
2. **Posting-layer-only fold-in.** Re-derive `posting_lists.bin` (1.16 GB/shard: lists, blocks, summaries) from the immutable `forward_data.bin` (3.85 GB) plus a forward tail of delta docs. Publish it through the manifest instead of running today's full twin route (38.9 GB jsonl dump, full SEISMIC build 1,919 s, c1a and dotvbyte conversion). *Inferred* from §0.1: at quarterly churn every in-place scheme ends up rewriting about the whole posting layer anyway, so write it once, cleanly, and leave the 77% of shard bytes that are forward data untouched. Hot-list-first (Ada-IVF) is an option within it. Cost: the SEISMIC fork must build its inverted index from an existing forward file (unverified that upstream allows this). This is an optimisation of design item 11, and it inherits M9's open build-vs-build drift question (0.9858 / 0.9870). **Worth a spike after the M9 drift baseline.**
3. **LIRE-style block maintenance** (append to the best block, exact local re-summary, split + GC, v4 block table). This is the only genuinely in-place candidate that addresses both measured failure modes (supply, and misplacement ×3.9). Its payoff is capped at the SEISMIC share of the generation tax (about 11 of 27.7 ms/gen), it does not solve top-λ truncation drift, and it costs a new format. **Not worth it unless #1 and #2 fail, and only at a daily cadence.** Design-only for now.

**Honest bottom line.** At 27% + 15% per quarter applied in quarterly batches, nothing in the 2022–2026 literature or in any production system beats an LSM/delta layer for the posting side. Every system found that sustains this kind of churn is either a delta layer (Vespa, Lucene, Milvus, Manticore, LanceDB, turbopuffer's WAL tier, LinkedBlock-as-fresh-tier) or SPFresh-style growable clustered partitions maintained at daily cadence. What remains is to make the delta layer cheaper: #1 shrinks what enters it, and #2 shrinks what folding it costs. First, verify the 87.6 versus 122.5 nnz/doc encoder mismatch (§0.3), since it inflates every demand and turnover number above.
