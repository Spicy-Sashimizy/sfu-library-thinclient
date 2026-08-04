# 17 — BM25-through-SEISMIC feasibility spike (MEASURED 2026-08-01)

**Status:** spike COMPLETE, measured. **Verdict: technically feasible and
quality-neutral, but it buys nothing — RECOMMEND NOT ADOPTING.**
**Corpus:** 207,973-doc subset of `social_sciences__recent` (NOT 150M).
**Code:** `spike/bm25_seismic/` · **Results:** `data/eval_results/bm25_seismic_spike_*.json`

---

## The question

SEISMIC is a generic sparse-vector index — nothing in it knows its input vectors
came from SPLADE. If it could also ingest **BM25-weighted** sparse vectors, the
lexical leg could move off tantivy onto an engine already adopted, already
mmap-proven, and the thin client would carry one sparse engine instead of two.
No published work does BM25-through-SEISMIC, so this was a research question,
not a known quantity.

The mirror question — **can tantivy read SPLADE vectors?** — is measured in §6.

## Isolation

Every `data/` read used `sqlite3` URI `mode=ro`. Nothing was written under
`data/thinclient_index/` or `data/seismic_150m/`; all artifacts live in
`spike/bm25_seismic/work/` (gitignored). No serving code, env gate, routing, or
MCP path was touched, and the LLM judge used a spike-local cache — the canonical
`llm_judge_cache.json` and `seismic_kimi_judge_cache.json` were never opened.

---

## 1. BM25F **is** exactly a sparse dot product (no approximation in the mapping)

The production lexical leg (`retriever._bm25f_leg`) is a tantivy boolean OR of a
title query boosted 3.0 and an abstract query, so

    score(q,d) = 3.0*BM25_title(q,d) + BM25_abstract(q,d)
    BM25_f(q,d) = SUM_t idf_f(t) * tf(t,d,f)*(k1+1)/(tf + k1*(1-b+b*dl/avgdl_f))

Every factor is query-only (`idf_f`) or doc-only (the saturation term), so BM25F
decomposes into an inner product **exactly**. Two decompositions were built
(`spike/bm25_seismic/bm25_lib.py`); they are algebraically identical but differ
under impact pruning:

| variant | doc component value | query component value |
|---|---|---|
| **A `idf_in_doc`** | `3*idf_t*sat_t + idf_a*sat_a` | `1.0` |
| **B `idf_in_query`** | `sat` per field-namespaced term | `boost*idf_f(t)` |

**Validated against tantivy** before any engine work: brute-force vectors
reproduce tantivy's own BM25F to ~0.02% (top hit 71.942 vs tantivy 71.953 —
the residual is tantivy's u8 fieldnorm quantisation), overlap@10 0.90–1.00.
So any downstream gap is the engine's, not the algebra's.

## 2. SEISMIC's standard index cannot hold a BM25 vocabulary

| | vocabulary |
|---|---|
| SPLADE (fixed BERT vocab) | 30,522 |
| BM25 over 207,973 docs | **710,047** (title 194,129 / abstract 650,920) |

The Rust builder **panics** — `inverted_index_wrapper.rs:499`, *"The number of
different tokens exceeds 2^16"* — before `idx.dim` is readable, so
`build_persona_seismic.py`'s build-then-check-`dim` fallback does not work for
BM25. `SeismicIndexLV` must be selected up front from a counted vocabulary
(`02_build_indexes.py`). Not a blocker, but a real porting cost.

## 3. Rank fidelity: SEISMIC reproduces exact BM25F essentially perfectly

`03_fidelity_gate.py`, variant A, 120 SFU eval queries, production serving
params (`query_cut=10`, `heap_factor=0.8`).
Result: `data/eval_results/bm25_seismic_spike_fidelity_idf_in_doc_20260801_2157.json`

| metric vs **exact** BM25F (brute force) | SEISMIC | tantivy |
|---|---|---|
| overlap@10 | **0.9992** | 0.9908 |
| NDCG@10 (gain = exact BM25F score) | **1.0000** | 0.9997 |
| top-1 match | **1.000** | 0.975 |
| recall of exact top-10 within top-100 | 1.000 | — |

For scale: **SPLADE through this same engine measures overlap@10 = 0.479**
(`06_FINDINGS.md` G2, 2026-06-27, proven to be the query-time approximation
floor and not reclaimable by any index knob). BM25 vectors land at 0.9992.
Both engines reproduce textbook BM25F almost exactly; tantivy's small residual
is its u8 fieldnorm quantisation plus this spike's 28-char token truncation.

> **Harness bug found and fixed mid-run (2026-08-01).** The first pass of this
> gate reported tantivy at overlap 0.900 / NDCG 0.908. That was wrong:
> `tantivy_search` omitted the non-alphanumeric scrub `retriever._bm25f_leg`
> applies before `parse_query`, so a hyphen made tantivy build a PHRASE query
> against `index_option="freq"` fields (no positions) → `ValueError` → the arm
> returned **nothing** on 11 of 120 queries (`post-acute`, `real-time`,
> `land-based`, `off-target`, `COVID-19`, `self-determination`, …). Production
> is NOT affected — `retriever.py:682` already scrubs. Retired runs:
> `data/eval_results/bm25_seismic_spike_*_20260801_2157.json.INVALID` and
> `*_2210.json.INVALID` (+ `.note` sidecars).

**Variant B** (`idf_in_query`, field-namespaced components) lands in the same
place — overlap@10 **0.9975**, top-1 0.9917, NDCG-vs-exact 0.9999 — while costing
60% more disk (§5). With the pruning inert (§4) the two decompositions cannot
differ much, which is what the design predicted.
Result: `data/eval_results/bm25_seismic_spike_fidelity_idf_in_query_20260801_2231.json`

Latency, variant A, 120 queries, idle host, single process, in-RAM index (ms):

| engine | p50 | p95 |
|---|---|---|
| brute-force exact | 0.79 | 1.69 |
| **SEISMIC** | **1.77** | **2.73** |
| tantivy | 2.43 | 15.40 |

This is the one axis SEISMIC wins: lower p50 and a far tighter tail. Read it with
two caveats — the spike's tantivy index is a **single** segment where production
fans out across 10 section indexes, and SEISMIC is measured on the stock
owned-RAM load, not the mmap path production would actually use.

## 4. Why the fidelity is perfect — and why that is bad news

**At production params SEISMIC's pruning never engages.**

    global budget = n_postings * dim = 3500 * 710,047 = 2.485 billion
    actual postings                                   =  26.1 million
    budget / actual                                   =  95.1x

(Careful with `idx.nnz`: it reports the **forward** index and does not move when
the inverted lists are pruned — the `n_postings=9` build below reports the same
26,127,568 while its build log shows avg posting list 2.69 against 36.8
unpruned. So `nnz` is not evidence either way; the budget arithmetic is.)

SEISMIC's pruning budget scales with the **vocabulary**, and BM25's vocabulary
is ~23× SPLADE's. The budget is so far above the corpus's posting count that the
`GlobalThreshold` selection is saturated — the same saturation the `n_postings`
sweep hit deliberately (`06_FINDINGS.md`, G2 follow-up #2, 2026-06-27).

So BM25-through-SEISMIC is exact **because the engine's distinctive machinery is
switched off**. What is left is a clustered exhaustive inverted index — which is
what tantivy already is, at a quarter the size.

This is structural, not a small-corpus artifact: the budget grows with vocabulary
faster than the corpus grows postings, so scaling up does not make the pruning
bind. Extrapolating the vocabulary by Heaps' law from the one measured point
(710k terms @ 208k docs, β≈0.5 → ~19M terms @ 150M docs) gives a budget of ~66
billion against ~18.8 billion actual postings — **still saturated (*est.*, one
data point, not measured)**.

## 5. Cost: measured on the identical corpus

| index | on disk | per doc | build | resident on load |
|---|---|---|---|---|
| tantivy (production schema) | **77.8 MB** | 374 B | **18.5 s** | ~0 (mmap) |
| SEISMIC variant A (`idf_in_doc`) | **1,742 MB** — 22.4× | 8,376 B | 760 s | **+2.024 GB** |
| SEISMIC variant B (`idf_in_query`) | **2,796 MB** — 35.9× | 13,442 B | 1,658 s | — |
| SEISMIC variant A, `n_postings=9` | 555 MB — 7.1× | 2,669 B | 1,111 s | — |

Variant B is *larger* because field-namespacing splits each term into
`title`/`abstract` components: dim 845,049 vs 710,047 and nnz 27.9M vs 26.1M.

> **Caveat — these are STOCK `.index.seismic` (bincode, f32) sizes, not the
> serving format.** Production converts to the f16 mmap layout and then to
> DotVByte + fixed-u8 (E7, shipped 2026-07-03, doc 10 §6: whole-dir 8.08 GB →
> 5.38 GB = **1.50×**, forward 1.70×). Applying that chain to variant A projects
> to roughly **0.9–1.2 GB (*est.*, ~11–15× tantivy)** rather than 22.4×. **Not
> measured for BM25 vectors** — the conversion needs the `c1a_mmap_index` /
> `convert_f16_to_dotvbyte` Rust bins, unbuilt on this host. The order-of-
> magnitude conclusion is unchanged; the exact multiple is not 22.4× in
> production form.

The per-posting view is the cleaner one, because it is codec-independent in
spirit: tantivy **2.98 B/posting** (delta-gap + bitpacked doc ids and tf) vs
stock SEISMIC **66.67 B/posting**. Tantivy's compression depends on postings
being sorted integer runs — which is exactly the structure SEISMIC gives up in
order to make block-skipping possible. That is why the gap is structural and why
codec work narrows it without closing it.

Production 150M actuals for context: tantivy lexical leg **29 GB** (193 B/doc),
SEISMIC SPLADE leg **187 GB** (1,247 B/doc). At the spike's measured 8,376 B/doc,
a 150M BM25-on-SEISMIC lexical leg projects to **~1.26 TB (*est.*, linear
per-doc)** replacing 29 GB — an order of magnitude past the entire current index.

### 5a. Can it be shrunk to tantivy's size? No — quality collapses first

`n_postings=9` is the setting at which the global budget finally drops below the
corpus's postings (6.4M vs 26.1M) and the pruning engages — build log: avg
posting list **2.69** vs 36.8 unpruned.
Result: `data/eval_results/bm25_seismic_spike_fidelity_idf_in_doc_np9_20260801_2230.json`

| variant A vs exact BM25F | `n_postings=3500` (1,742 MB) | `n_postings=9` (555 MB) |
|---|---|---|
| overlap@10 | **0.9992** | **0.3942** |
| top-1 match | 1.000 | 0.600 |
| NDCG@10 vs exact | 1.0000 | 0.8748 |
| recall of exact top-10 within top-**100** | 1.000 | **0.3942** |

The last row is the important one: over-fetching to depth 100 recovers **nothing**
(recall@100 == overlap@10). The pruned postings are physically absent from the
index, so no query-time knob — `heap_factor`, `query_cut`, deeper `k` — gets them
back. This is the same "index-time pruning, not query-time" conclusion G2 reached
for SPLADE (`06_FINDINGS.md`, 2026-06-27), arrived at from the opposite direction.

So the choice is: **exact BM25F at 22.4× tantivy's size, or 7.1× the size with
39% of the right results.** There is no configuration that is both small and
correct.

The +2.024 GB figure is the stock owned-RAM load; production serves SEISMIC
through the `MmapSeismicIndex` layout (Path C, anon Δ ≈ 0). That conversion is
format-level and vector-agnostic, so it would carry over — but it was **not
run here** (it needs the `c1a_mmap_index` Rust bin, unbuilt on this host), so
the mmap RAM profile for BM25 vectors is **unmeasured**. Disk is the binding
number either way.

## 6. The mirror question: can tantivy read SPLADE vectors? — **No**

`05_tantivy_reads_splade.py`, 20,000 docs encoded with the production SPLADE
encoder (91.0 terms/doc, 22,192 distinct terms), 120 queries.
Result: `data/eval_results/bm25_seismic_spike_tantivy_splade_20260801_2157.json`

Serving SPLADE means a sparse dot product, which needs a per-(term, doc) float
the scorer uses **linearly**. Lucene has one (`FeatureField`/`rank_features`) —
which is why SPLADE rode Lucene into Elasticsearch (`sparse_engine_project/
WHY_NO_FOSS.md` §3). tantivy has no equivalent: its float/integer fields are
per-**doc**. The only per-(term, doc) magnitude is **term frequency**, reachable
only via the "fake words" trick (emit token `t` `round(w*70)` times), and the
only scorer that reads it is BM25, whose `k1`/`b` are fixed in Rust and not
settable from the Python bindings.

| metric vs exact SPLADE dot product | raw query boost | idf-corrected boost |
|---|---|---|
| overlap@10 | **0.485** | 0.466 |
| top-1 match | **0.342** | 0.308 |

Three distortions, only one correctable: `idf(t)` multiplies every contribution
(correctable — divide it out of the query boost); tf **saturates** (`tf=1`
already scores 0.478 of the ceiling, `tf=10` → 0.893); and length normalisation
divides by doc length, which under this encoding **is** the vector's total mass,
so the highest-weight docs are punished hardest. The latter two are doc-side and
cannot be undone at query time — and dividing idf out measurably made things
*worse* (0.485 → 0.466), because idf was accidentally compensating for them.

Encoding cost is *not* the problem: the tf-repetition index was 4.5 MB for
20k docs (3,128.8 tokens/doc after repetition) and built in 2.6 s — tantivy
stores `(doc, tf)` pairs, so repeating a token costs nothing extra on disk.
The blocker is purely the scorer. Making tantivy serve SPLADE means implementing
a custom `Query`/`Weight`/`Scorer` in Rust — i.e. exactly the from-scratch
scorer work the effort/ROI verdict already priced.

## 7. LLM-judged search quality: **no degradation** (the "does it get worse?" gate)

`04_quality_ab.py`, 120 SFU eval queries, TREC-pooled (union of all three arms'
top-10; each (query, doc) pair graded once and shared, 1,211 pairs). Judge:
`claude-haiku-4-5-20251001` via `claude -p` — **$0**, the same judge regime the
repo's canonical numbers use — with a spike-local cache
(`work/spike_judge_cache.json`); `llm_judge_cache.json` and
`seismic_kimi_judge_cache.json` were never touched.
Result: `data/eval_results/bm25_seismic_spike_quality_idf_in_doc_20260801_2227.json`

| arm | NDCG@10 (pooled ideal) | NDCG@10 (self ideal) | MRR@10 | P@10(≥2) | mean grade |
|---|---|---|---|---|---|
| `tantivy` (production leg) | **0.8678** | 0.8685 | 0.9310 | 0.5058 | 1.5408 |
| `exact_vec` (exact BM25F) | 0.8629 | 0.8672 | 0.9268 | 0.5017 | 1.5325 |
| `seismic_idf_in_doc` | **0.8621** | 0.8672 | 0.9268 | 0.5008 | 1.5308 |

**Δ vs tantivy = −0.0057 NDCG@10 (−0.66%)** — noise at n=120. And the split is
attributable: `exact_vec` is itself −0.57% vs tantivy (that is the 28-char token
truncation + tantivy's fieldnorm quantisation), while **SEISMIC vs exact BM25F is
−0.0008 (−0.08%)**. The engine contributes essentially nothing to the difference.

So swapping the lexical leg to SEISMIC would not measurably change what users
see. The case against it is cost (§5), not quality.

---

## Verdict

**Feasible, quality-neutral, and not worth doing.** BM25 vectors go through
SEISMIC at overlap@10 0.9992 against exact BM25F with **no measurable search
quality change** (−0.66% NDCG@10 vs tantivy, of which the engine accounts for
−0.08%; §7). The swap is genuinely low-risk on quality.

It fails on cost, and it fails at both ends of the only lever:

- At production params it is **22.4× tantivy on disk** (1,742 MB vs 77.8 MB;
  *est.* ~1.26 TB vs 29 GB at 150M) — and it is exact only because the pruning
  budget is 95× oversized, i.e. SEISMIC is behaving as a plain clustered
  inverted index, which is what tantivy already is.
- Turn the pruning on hard enough to matter and quality collapses to **0.3942
  overlap / 0.600 top-1** while still costing **7.1×** tantivy — and depth-100
  over-fetch recovers none of it (§5a).

The root cause is structural, not a corpus-size artifact: SEISMIC's budget
scales with **vocabulary**, and BM25's open vocabulary is ~23× SPLADE's fixed
30,522 (710,047 terms at only 208k docs). BM25 also asks 3–8 literal query terms
where SPLADE asks 64 weighted ones, so there is little for block-max traversal
to prune. SEISMIC is built for dense-ish, high-cardinality *learned* query
vectors; BM25 is the opposite shape.

The one condition that would flip this: if the lexical leg ever moved to a
**learned/expanded** query vector, the pruning would start to bind and SEISMIC's
advantage would become real. At BM25's query shape it does not.

The mirror direction (§6) is a harder no: tantivy cannot serve SPLADE at all
without a custom Rust `Query`/`Weight`/`Scorer`, because the only per-(term,doc)
magnitude it exposes is term frequency and BM25's saturation + length norm are
uncorrectable at query time (overlap@10 0.485, top-1 0.342).

**Net: no existing implementation lets the lexical and learned-sparse legs share
one engine without either rewriting a scorer in Rust or paying an order of
magnitude in storage. The two-engine split stands.**

## 8. Could a "translation layer" fix this and let one engine serve both legs?

Asked 2026-08-02. Short answer: **not at the vector level — only at the engine
level, and the cheaper engine-level project is the tantivy one, not the SEISMIC
one.**

**Why no data-level transform works.** Every transform that would make BM25
vectors prunable destroys the property the lexical leg exists to provide:

| transform | what it does | why it fails |
|---|---|---|
| hash vocabulary into ~32k buckets | lists get long → prunable, budget arithmetic sane | collisions make unrelated words score as matches; the leg's job is *exact literal* matching of names/acronyms/rare terms |
| drop terms with df ≤ k | shrinks the index | deletes the long tail — again the leg's whole purpose |
| expand queries to ~64 weighted terms | gives pruning the redundancy it needs | that **is** SPLADE, which already runs as the other leg |
| re-weight impacts so pruning keeps "better" postings | — | the score is a **sum**; dropping *any* contributing posting corrupts it. `n_postings=9` already preferentially keeps high-idf postings (variant A bakes idf into the impact) and still fell to 0.3942 |

The generalisation: BM25 is valuable in the RRF fusion precisely *because* it is
literal, long-tailed, and unexpanded — and those are the same three properties
that make it un-prunable. A translation layer that fixes prunability has turned
BM25 into SPLADE.

**Engine-level option A — compress SEISMIC toward tantivy.** In flight already
(E7 DotVByte, §5 caveat): ~1.5–1.7×, taking BM25-on-SEISMIC to *est.* ~11–15×
tantivy. Closing the remaining gap needs delta-gap + bitpacked integer postings,
which is the structure SEISMIC discards to enable skipping. Plausible ceiling
~10×, not parity. **Does not reach the goal.**

**Engine-level option B — teach tantivy the dot product (the promising one).**
§6 measured that the *encoding* side already works: the fake-words tf-repetition
index was 4.5 MB for 20k docs, built in 2.6 s, and tantivy stores `(doc, tf)`
compressed at ~3 B/posting. The **only** broken piece is `Bm25Weight`'s idf ×
saturation × length-norm. tantivy's Rust API is trait-based (`Query` / `Weight` /
`Scorer`), so a custom scorer computing `SUM_t q_w(t) * dequant(tf(t,d))` — no
idf, no saturation, no norm — is an **exact sparse dot product over tantivy's
compressed postings**. That yields one engine, at ~3 B/posting, mmap'd, no JVM,
serving BM25F *and* SPLADE.

Scope and risks of B (unestimated — no spike run):
- A Rust crate + Python binding; the repo already vendors forks, so this is
  familiar ground.
- Impact quantisation is already a solved constant here (`QUANT_SCALE=70`).
- The real work is **pruning**: a naive custom scorer has no block-max skipping,
  so SPLADE's 64-term queries would traverse full lists. Restoring it means
  storing a per-block max impact and wiring it into tantivy's block-max WAND —
  i.e. building an impact-ordered index inside tantivy. That is the substantive
  piece, and it is exactly the "new scorer inside tantivy" the earlier
  effort/ROI verdict priced.

**Recommendation.** If the goal is eliminating the two-engine split, option B is
the only path that ends with a smaller index rather than a bigger one, and §6 is
the measurement that says why it is required. It is a bounded-but-real Rust
project, not a data-pipeline change. Against that, the status quo costs one extra
dependency and one build step — so B should only start if the two-engine
complexity is causing measured operational pain, not on principle.

## 9. Prior art (web survey 2026-08-02) — the approach is shipped practice; SEISMIC is the wrong host

**Correction to §Question.** This doc opened by calling BM25-through-a-sparse-engine
a research question with no published work. That is true of **SEISMIC
specifically**, but NOT of the approach: **Milvus ships it.** Milvus's full-text
search converts text to sparse vectors and serves BM25 through its sparse vector
index, using a dedicated `BM25` metric type. Qdrant does the same via FastEmbed's
BM25 sparse model (and `miniCOIL`, which is the BM25 formula scaled by the
semantic similarity of matched keywords). So the idea is validated in production
systems — the spike's negative result is about the host engine, not the idea.

**And Milvus's encoding explains our 22× storage result.** Milvus stores the
**raw TF** as the document vector and computes `IDF · f(TF)` *at query time* from
live `avgdl`/`df` statistics. We could not: SEISMIC's kernel is a pure dot
product, so the saturation and idf must be **baked into the stored impact**,
which forces float values (66.67 B/posting) where Milvus keeps a small
compressible integer. This is the same conclusion §8 reached from first
principles — **the fix belongs in the engine's scorer, not in a data
transformation** — reached independently by the one system that shipped it.

**All-three-legs survey, scored against this project's actual constraints**
(no-JVM · embeddable · immutable static index distributable to thin clients ·
mmap/low-RAM · 150M docs):

| engine | all 3 legs | no JVM | embeddable | static/mmap distributable | 150M |
|---|---|---|---|---|---|
| **Infinity** (infiniflow) | ✅ dense + sparse + full-text + tensor, one table | ✅ C++ | ✅ `infinity_embedded`, single binary, no server | ❓ unverified | ❓ unverified |
| **Milvus** | ✅ dense + BM25-as-sparse + external SPLADE, one collection | ✅ Go/C++ | ⚠️ Milvus Lite only — and **full-text search is NOT supported in Lite** (planned) | ❌ server + LSM storage | ✅ as a server |
| **LanceDB** | ❌ dense + BM25 (via **tantivy**); sparse still **open** — issue #1930, filed 2024-12-10, "SPLADE + HNSW" on the roadmap | ✅ Rust | ✅ | ✅ static columnar | ✅ |
| **Qdrant** | ✅ dense + sparse + BM25-via-FastEmbed | ✅ Rust | ⚠️ server | ❌ mutable-first | ❌ **measured here: OOMs at 150M, needs ≥64 GB** |
| Elasticsearch / OpenSearch | ✅ | ❌ JVM | ❌ | ❌ | ✅ |

**Verdict vs `sparse_engine_project/WHY_NO_FOSS.md` (2026-06-25).** That doc's
core claim — the no-JVM + immutable + all-three-legs + 150M intersection is
empty — **still holds**, with one update: **Infinity now has an in-process
embedded mode**, moving it from "a whole new DB to adopt" to "a library you could
spike." It is the only candidate hitting all-three + no-JVM + embedded
simultaneously. LanceDB is the near-miss and would become the best structural fit
for a static thin-client index if #1930 ever lands — note it already uses tantivy
for its FTS leg.

**Not adopted. No production code changed by this spike.**

---

## 10. C1 measured (2026-08-02): the fan-out is **correct but 3.6–6.7× slower** — C1 not adopted

A storage-consolidation review on 2026-08-02 (session analysis, never committed
to this doc as a table) enumerated four candidate moves for collapsing the
container's four storage technologies — tantivy Directory, SQLite ×3 roles,
usearch, SEISMIC — down to three:

| # | move | removes | status |
|---|---|---|---|
| **C1** | `meta.sqlite` → tantivy stored + fast fields | SQLite from the hot path; the Python post-filter mask on both approximate legs | **measured 2026-08-02 — NOT adopted (below)** |
| C2 | `dense/delta.sqlite` metadata role | the third metadata path | dropped — falls out of C1 |
| C3 | `abstracts.sqlite` → flat zstd block file + `(block, off, len)` as tantivy fast fields | the last SQLite | **measured 2026-08-02 — SPLIT: blocks yes, locator no (§11)** |
| C4 | `dense/ids.json` → tantivy fast field | one JSON fully loaded into RAM | projected, unmeasured |

C1 was the load-bearing one, and it carried one named risk: `id -> DocId`
becomes an fst lookup per id **per section (×10)** instead of one PK hit,
because a ranked list from an approximate leg is not section-partitioned.

(C3 carries a separate constraint worth preserving here: do **not** move abstract
text into tantivy's docstore. tantivy supports `None`/`Lz4`/`Zstd(level)` but has
no trained-dictionary support and uses 16 KB blocks, which would surrender the
measured per-script wins — ru −40% / fa −38% / ko −37% / zh −32%. C3 keeps the
existing codec and drops only the SQLite envelope around it.)

That risk is now measured, and it is real.

- Bench: `spike/meta_consolidation/01_c1_lookup_bench.py`
- Results: `data/eval_results/c1_meta_lookup_20260802_0340.json`
- Corpus: the 207,973-doc spike corpus, hash-partitioned across the **10 real
  production section names**, so the fan-out factor is the deployed one.

### Correctness: C1 works

At 100 / 500 / 1000 / 2000 ids, `Query.term_set_query(schema, "id", ids)` over
a raw-tokenized `id` field returned the **identical id set** and
**byte-identical field values** as `retriever._meta_rows`, on all six columns.
tantivy is a faithful replacement for the PK lookup. That was never the doubt.

### Latency: C1 loses at every size

p50 ms, filter-mask workload (`year`/`type`/`is_oa` — the hot one, run on every
approximate-leg query over the over-fetched candidate list):

| ids | `meta.sqlite` (64 MB cache) | tantivy ×10 fan-out | tantivy / sqlite |
|---|---|---|---|
| 100 | 1.56 | 5.63 | **3.6× worse** |
| 500 | 2.06 | 13.74 | **6.7× worse** |
| 1000 | 4.15 | 21.52 | **5.2× worse** |
| 2000 | 8.62 | 39.56 | **4.6× worse** |

Full hydration (all six columns) tracks within ~10% of these — the stored-field
read is not what costs; the ×10 fan-out is. The fan-out *scales* well
(sublinear: 5.6 → 39.6 ms for 20× the ids) but it starts from a ~5 ms floor that
one batched PK lookup never pays.

**C1 is therefore NOT adopted.** It is a correct transformation that trades a
faster store for a slower one. C2 falls out of C1 and is likewise dropped. C3
and C4 are untouched by this result — neither depends on the id fan-out — and
remain *projected*, unmeasured.

The 24 GB → est. 9–12 GB size projection in §8 is **not** validated or refuted
here; this spike measured latency only. The on-disk figures the bench prints
(161 MB tantivy vs 39 MB SQLite) are **not** a size comparison — the tantivy
indexes also carry indexed abstract text the SQLite file does not hold.

### Side finding, and the more valuable one: `PRAGMA cache_size`

The first run of this bench appeared to show C1 winning by 9.5× at 1000 ids.
That was an artifact of an under-configured baseline, and chasing it produced a
result worth more than C1 was:

`retriever._meta_rows` opens `meta.sqlite` with SQLite's default page cache
(2000 pages, ~2 MB). Above roughly **470 ids** the pages a candidate list
touches stop fitting, and every batch re-reads them through the container's
overlay filesystem, where a page read is a syscall rather than a memory hit.
The result is a latency **cliff**, not a curve — measured 2026-08-02 on the same
file, same ids, chunk size irrelevant (500/100/50 all identical):

| ids | default (~2 MB cache) | `cache_size=-65536` (64 MB) | speedup |
|---|---|---|---|
| 100 | 1.34 | 1.30 | — |
| 450 | 1.68 | — | *(below the cliff)* |
| 480 | 95.6 | — | *(cliff)* |
| 500 | 100.8 | 2.06 | **49×** |
| 1000 | 200.6 | 4.15 | **48×** |
| 2000 | 409.6 | 8.62 | **48×** |

Confirmed as an I/O effect, not an algorithmic one: the same database copied to
tmpfs is perfectly linear at the default cache (0.12 ms @ 100 → 2.20 ms @ 1000,
no cliff). `EXPLAIN QUERY PLAN` shows `SEARCH docs USING INTEGER PRIMARY KEY` on
both sides of the cliff, so it is not a plan flip. `mmap_size=256 MB` also fixes
it but is ~2× worse than the cache pragma alone.

> **CORRECTED 2026-08-02 (same day, by §10.3).** The ~48× above is a
> **spike-scale artifact and does not transfer to production.** It was measured
> on a 39 MB database that fits entirely in RAM. On the real 24.9 GB
> `data/thinclient_index/meta.sqlite` the pragma is worth **1.18× at 1000 ids
> and nothing at all at 100 ids** — see §10.3. The cliff is real, but it is a
> property of a *small* database whose working set straddles the cache
> boundary; at 24.9 GB no attainable cache holds the working set, so there is no
> boundary to straddle. The paragraph below stated the fix as if it were a
> production win. It is not. Retained, struck, as a record of the error.

~~This is a **one-line production fix** to `retriever._load`, worth ~48× on the
post-filter mask for any query whose over-fetched candidate list exceeds ~470
ids.~~ **IMPLEMENTED: no, and NOT recommended on this evidence** — see §10.3 for
what the pragma is actually worth in production.

**Not adopted. No production code changed by this spike.**

---

## 10.2 — C1's actual claim (filter pushdown) also fails, for a different reason

§10 timed C1 as a *metadata-lookup swap*: fetch the same rows from tantivy
instead of SQLite, then run the same Python mask. But C1 claimed to remove the
mask, by making the filter part of the query. That is a different algorithm and
§10's verdict did not cover it, so it was measured separately.

- Bench: `spike/meta_consolidation/02_c1_pushdown_bench.py`
- Results: `data/eval_results/c1_pushdown_warm_20260802_0510.json`

Four arms, same ids, same filter. p50 ms, warm, spike corpus:

| filter | ids | sqlite post-filter | tantivy lookup (stored) | tantivy lookup (fast fields) | **tantivy pushdown** |
|---|---|---|---|---|---|
| selective (5.6% pass) | 100 | 1.39 | 5.87 | 5.93 | **5.82** |
| selective | 1000 | 4.14 | 20.88 | 21.59 | **19.70** |
| loose (100% pass) | 100 | 1.43 | 5.72 | 5.99 | **5.60** |
| loose | 1000 | 4.28 | 23.64 | 30.53 | **22.04** |

All four arms returned identical survivor sets at both selectivities.

**Pushing the filter into the query saves essentially nothing** — 5.82 vs 5.87
ms at 100 ids, 19.70 vs 20.88 at 1000 — even at 5.6% selectivity, where it
avoids fetching 94% of the rows. That is the informative part: **the cost is the
`term_set_query` id fan-out itself, not the row fetching and not the Python
mask.** C1's promised saving was never where the time goes, so removing the mask
cannot pay for the fan-out. This closes the stronger reading of C1 too.

Two methodology gaps in §10 were fixed here and neither changed the verdict:
fast fields were *declared* but never *read* in §10 (it called `searcher.doc()`,
the row-oriented docstore, not `Searcher.fast_field_values`) — reading them
columnar is within noise, and slightly *worse* on the loose filter. And §10
reused one id list across all repetitions; `--fresh-ids` re-draws per rep. The
fresh-ids run is reported in
`data/eval_results/c1_pushdown_freshids_20260802_0511.json` but is **confounded
and should not be quoted**: the first filter block absorbs all the cold-cache
cost, so its SQLite column decreases with size (19.4 → 40.8 → 17.3 → 10.3 ms),
which is not a real curve. The warm comparison above is the trustworthy one.

---

## 10.3 — Production scale: C1 loses by MORE, and the pragma finding evaporates

Everything above ran on a 207,973-doc corpus with a **39 MB** metadata DB. That
fits in RAM, so both arms were served from page cache and the spike measured CPU
rather than the storage hierarchy. Production does not fit:

| | production | spike |
|---|---|---|
| `meta.sqlite` | **24.9 GB** | 39 MB |
| section tantivy index | **4.1 GB** × 10 | ~16 MB × 10 |

Production `meta.sqlite` measured 2026-08-02: **150,413,098 rows in `docs`**,
`page_size` 4096, `page_count` 6,081,055. **`docs_other` holds 0 rows** — every
production id is W-prefixed and integer-encodable, so `encode_meta_id` never
falls through to the TEXT overflow table. That validates an assumption in the
bench below, which queries only `docs`: on this index there is nothing else to
query. (It also means the v2 INTEGER-PK path is the only one that matters in
production, and the `docs_other` branch in `retriever._meta_rows` is dead code
against this index — untested by any real query.)

The same code path costs **4.15 ms at spike scale and 400 ms in production** for
1000 ids — a **96× gap**. Spike-scale numbers therefore do not extrapolate, in
either direction, and the C1 comparison had to be re-run against the real index.

- Bench: `spike/meta_consolidation/03_c1_production_scale.py`
- Results: `data/eval_results/c1_production_scale_20260802_0529.json`
- Read-only throughout. `meta.sqlite` opened `mode=ro`; sections opened with
  `tantivy.Index.open`, the identical call `retriever._load:378` already makes.
- Ids are **real** (random existing rowids, found by PK probing rather than
  scanning) and **disjoint across repetitions**, so no rep warms another.

p50 ms, 10-section fan-out vs production `meta.sqlite`:

| ids | sqlite (default cache) | sqlite (64 MB) | sqlite (1 GB) | tantivy ×10 fan-out | tantivy / best sqlite |
|---|---|---|---|---|---|
| 100 | 38.68 | 39.03 | 38.76 | 336.27 | **8.7× worse** |
| 500 | 203.43 | 188.38 | 188.59 | 743.88 | **3.9× worse** |
| 1000 | 400.83 | 338.98 | 339.32 | 897.67 | **2.6× worse** |

Coverage was exact at every size (both arms found 100/100, 500/500, 1000/1000).

**C1 is dead at production scale, by a wider margin than the spike showed.** The
×10 fan-out means ten 4.1 GB indexes each take cold page faults for every
candidate list, against one 24.9 GB B-tree that takes one PK probe per id.

### The pragma finding does not survive

§10 recorded `PRAGMA cache_size` as a ~48× one-line production win. **That was
wrong**, and this is the measurement that shows it. In production the pragma is
worth:

| ids | default → 64 MB | speedup |
|---|---|---|
| 100 | 38.68 → 39.03 ms | **none** (within noise) |
| 500 | 203.43 → 188.38 ms | 1.08× |
| 1000 | 400.83 → 338.98 ms | **1.18×** |

Raising it to 1 GB adds nothing over 64 MB. The spike's cliff was real but
**scale-specific**: a 39 MB DB has a working set that straddles the 2 MB cache
boundary, so enlarging the cache crosses it. At 24.9 GB no attainable cache
holds the working set, so there is no boundary to cross and the pragma only
trims the margin. §10 has been corrected in place.

### The finding that does survive, and it is not about C1

Production metadata lookup costs **~0.4 ms per id**: 38.7 ms for 100 ids, 400 ms
for 1000. Every approximate-leg query pays this on its over-fetched candidate
list, in Python, single-threaded, before ranking. At a 1000-candidate over-fetch
that is a **~400 ms floor on the post-filter mask alone** — plausibly the
dominant term in thin-client query latency, and it is a *scale* problem, not a
configuration one. No pragma fixes it. **UNRESOLVED — no fix measured.** What
C1 got right was the diagnosis (`meta.sqlite` is hot and it hurts); what it got
wrong was the remedy.

**Not adopted. No production code changed by this spike.**

### Addendum — where the fan-out cost actually is (and why a schema rebuild won't rescue C1)

One escape hatch remained. The production `id` field is `stored`, not `fast`, so
the fan-out arm pays a row-oriented `searcher.doc()` read per hit. If *that*
were the cost rather than the query, C1 could rebuild with `id` as a **u64 fast
field** — production W-ids are integers, so `Searcher.fast_field_values` would
apply and the stored read would vanish. Measured 2026-08-02 on the production
sections, two arms, same ids:

| ids | search only (no doc reads) | search + `doc()` read |
|---|---|---|
| 100 | 409.1 ms | **68.2 ms** |
| 500 | 300.0 ms | **200.1 ms** |

The arm doing strictly *more* work is **faster**, at both sizes. This run is
ordering-confounded — `search only` ran first and absorbed the cold page faults
on the term dictionary, which `search + doc()` then reused — so **the absolute
numbers here must not be quoted**. But the confound cannot manufacture the
direction: adding a stored read per hit did not add measurable time on top of
the query it followed. **The cost is the `term_set_query` term-dictionary
traversal across 10 multi-GB indexes, not the document fetch.**

So the u64-fast-field rebuild would remove a component that is not on the
critical path. It cannot rescue C1, and no schema change reachable from here
can: the fan-out is inherent to asking ten indexes for ids when only one of them
holds each id.

Note also the warm figure: 68 ms at 100 ids, against ~39 ms for production
SQLite on the same ids. Even fully warm, with the doc read included, the fan-out
loses — and cold it loses by 8.7× (§10.3).

---

## 11. C3 measured (2026-08-02): **split verdict** — move the blocks, keep the locator

C3 proposed moving `abstracts.sqlite` to a flat zstd block file with the locator
(`id -> block, offset, len`) in tantivy fast fields, keeping the trained
per-script dictionaries untouched. It was called "safe by construction" because
only the SQLite envelope changes, not the codec.

**C1's failure mode does not transfer, and that had to be checked first.** C1
died on a ×10 section fan-out. Abstracts are only carried by HOT sections, and
in this index exactly one is (`social_sciences__recent`, 13.47 GB) — every other
section's `abstracts.sqlite` is absent. So C3's locator lookup is ×1 and C3 had
to be judged on its own evidence.

- Bench: `spike/meta_consolidation/04_c3_abstracts_bench.py`
- Results: `data/eval_results/c3_abstracts_20260802_0559.json`
- Store: production `social_sciences__recent/abstracts.sqlite`, read-only.
  23,398,073 docs in 1,062,917 blocks, 476 B/abstract compressed, 22 docs/block.
- Ids are reservoir-sampled over the full 23.4M-row PK index, so they scatter
  across blocks the way a real rerank candidate list does. (A `LIMIT k` prefix
  would share blocks and flatter the block cache.)

### (a) Size — the ceiling is ~2.2 GB, not the whole file

| component | bytes | share |
|---|---|---|
| compressed abstract payload (`blocks.z`) | **11.132 GB** | 82.6% |
| everything else — locator table, btrees, page slack | **2.339 GB** | 17.4% |
| file | 13.470 GB | |

C3 can only ever recover from that 2.339 GB. Storing `(b, off, n)` as tantivy
fast fields costs ~6 B/doc bitpacked (b ≤ 1.06M → 20 bits, off < 32768 → 15,
n → ~13) ≈ **0.14 GB** for 23.4M docs, so the realistic ceiling is **~2.2 GB,
about 16%** of the store. Real but bounded — the payload is 83% of the file and
no envelope change touches it. *(Ceiling is computed, not measured: the
fast-field figure is arithmetic from the schema, and the 2.339 GB was not split
between locator table and page slack — a `dbstat` scan was started for that and
abandoned as not decision-relevant, since C3's flat file removes both.)*

### (b) Speed — the locator is not where the time goes

`AbstractStore.fetch()` decomposed on the production store, p50 ms:

| k | full fetch | locator | block reads | decompress | locator share |
|---|---|---|---|---|---|
| 10 | 14.53 | 1.33 | 12.84 | 0.80 | **9.2%** |
| 50 | 69.45 | 1.48 | 64.52 | 2.42 | **2.1%** |
| 100 | 136.86 | 1.75 | 129.41 | 5.07 | **1.3%** |

**Block reads are 93% of the cost at k=100.** The locator is 1.3–9.2%. And
random ids touch one distinct block each (22 docs/block, so no sharing), at a
rock-steady **1.29 ms/block** — min ≈ p50 ≈ max, i.e. pure cold random I/O.

### The locator half of C3 is a regression

Timed on the real production section index, the tantivy `id -> DocAddress`
term-dictionary lookup against the SQLite PK lookup for the same ids:

| k | sqlite locator | tantivy locator | |
|---|---|---|---|
| 10 | 1.33 | 71.36 | **53.7× worse** |
| 50 | 1.48 | 64.93 | **43.9× worse** |
| 100 | 1.75 | 46.72 | **26.7× worse** |

Replacing a stage worth 1.3% of the fetch with one 27–54× slower would take
k=100 hydration from 136.9 ms to ~182 ms, a **~33% regression**. This is the
same term-dictionary traversal cost that killed C1 (§10.3), showing up again at
×1 fan-out — it was never *only* about the ×10.

### The block half of C3 is a real win

C3's flat file replaces a SQLite blob read (btree descent + overflow page chain)
with one `pread` at a known offset. Measured as a floor, without building a
13.5 GB file — a `pread` of the average block size (10,472 B) at random offsets
in a file of exactly the production size:

| k | sqlite blob reads | flat-file `pread` | |
|---|---|---|---|
| 10 | 12.84 ms | 3.31 ms | **3.88× faster** |
| 50 | 64.52 ms | 16.76 ms | **3.85× faster** |
| 100 | 129.41 ms | 33.94 ms | **3.81× faster** |

0.34 ms/block vs 1.29. Applied to the dominant stage, projected k=100 hydration
becomes ~1.75 (locator, kept in SQLite) + 33.94 + 5.07 ≈ **40.8 ms, down from
136.9 — a ~3.4× speedup** on abstract hydration. *(Projection, not an
end-to-end measurement: no flat-file store was built. The probe measures the
I/O the design would do; a real store also needs a block→offset table, ~8.5 MB
at 1.06M blocks, RAM-resident and free per read.)*

### Verdict

**Adopt the block move; drop the locator move.** The resulting design keeps a
much smaller SQLite holding only the locator, and does NOT remove the last
SQLite from the container — so C3 as originally scoped ("removes the last
SQLite") is **not** achievable at acceptable latency. What it buys instead is
~2.2 GB and a projected ~3.4× on abstract hydration, which is worth more than
the technology-count reduction it was proposed for.

> **SUPERSEDED 2026-08-02 by N5 — the flat store was BUILT and the projection
> was optimistic.** See `18_ORDINAL_ADDRESSING_DESIGN.md` §9 and
> `data/eval_results/n5_flat_blocks_20260802_0741.json`. Measured end-to-end:
> **2.82–2.89×**, not the ~3.4× projected above (159.4 → 55.2 ms at k=100). The
> projection assumed the block stage's 3.8× carried through untouched; the
> locator and decompress stages dilute it. **Byte-parity gate PASSED** — 20,000
> abstracts byte-identical to `AbstractStore.fetch`. The verdict (adopt the
> block move) is unchanged; only the multiple was wrong.

**IMPLEMENTED: no. EFFICACY: (a) size ceiling computed, (b) speed measured on
the production store, (c) end-to-end flat store BUILT and gated 2026-08-02 —
see the banner above.**

### Side finding: abstract hydration is expensive

Independently of C3, **hydrating 100 abstracts costs 136.9 ms** on the
production store, 93% of it cold random block reads — paid on the rerank path
of every query that reranks a hot section. Together with §10.3's ~0.4 ms/id
metadata lookup, the two SQLite sidecars account for a large, previously
unquantified share of thin-client query latency. Both are I/O-shaped, and
neither is fixed by configuration.

**Not adopted. No production code changed by this spike.**

---

## 12. C5 (2026-08-02): revisiting LanceDB — **the first candidate that is not disqualified**

§9 surveyed LanceDB and parked it conditionally: *"the best structural fit for a
static thin-client index **if issue #1930 ever lands**"*. Two things have changed
since — one external, one internal.

**External, re-checked 2026-08-02:** [lancedb#1930](https://github.com/lancedb/lancedb/issues/1930)
(sparse vectors / SPLADE), filed 2024-12-10, is **still open**. So LanceDB
still cannot host the SPLADE leg, and **SEISMIC stays regardless of what else
is decided.**

**Internal, and more important:** §10–§11 changed what the question *is*. Those
sections established that this whole programme turns on one property —

| store | key → row lookup, 100 ids | |
|---|---|---|
| `meta.sqlite` PK (150M rows, production) | 38.7 ms | baseline |
| tantivy fst, ×10 fan-out (§10.3) | 336.3 ms | 8.7× worse |
| tantivy fst, ×1 fan-out (§11 locator) | 46.7–71.4 ms | 27–54× worse *per stage* |

Every failed consolidation failed the same way: **an fst term dictionary is not
a key→row index.** §9 scored engines on *which legs they serve*; the property
that actually decides adoption is *whether they can find a row by key*. Lance
has BTREE scalar indexes, so it is the first candidate that could pass a test
tantivy structurally cannot.

That also reframes §9's all-or-nothing verdict. Lance does **not** need #1930 to
be useful here, because it does not need to replace an engine — it could replace
the *storage roles*:

    today          tantivy · SQLite(×3) · usearch · SEISMIC   = 4 technologies
    Lance variant  tantivy · Lance      · SEISMIC             = 3

- Bench: `spike/meta_consolidation/05_lance_vs_sqlite_lookup.py`
- Results: `data/eval_results/c5_lance_vs_sqlite_20260802_0636.json`,
  `data/eval_results/c5_lance_real_titles_size_20260802.json`
- pylance 9.0.0 / pyarrow 25.0.0, installed in an **isolated spike venv**
  (`spike/meta_consolidation/.venv-lance/`) — the serving `.venv` the MCP server
  runs from was deliberately not touched.

### Lookup: Lance is in SQLite's league

Both stores built at an identical 20M rows (150M was not affordable here), same
machine, same ids, `id` int64 in both — production `docs_other` is empty (§10.3)
so the key really is an integer. Returned rows were **identical** at both sizes.

| ids | `meta.sqlite` | Lance + BTREE | |
|---|---|---|---|
| 100 | 39.25 ms | 67.67 ms | **1.72× worse** |
| 1000 | 222.74 ms | 255.13 ms | **1.15× worse** |

Lance loses modestly, and the gap **narrows** as the batch grows — the opposite
of tantivy, which lost by 8.7–54× and got worse at small batches. This is the
qualitative break: Lance is a viable key→row store.

*Scale note:* SQLite at 20M rows measures 39.25 ms/100 ids against 38.68 ms at
the real 150M (§10.3) — essentially identical, because the cost is one random
page read per id and B-tree depth barely moves. That the SQLite arm reproduces
its production number at 20M is decent evidence the Lance arm is not being
flattered by scale, but **Lance itself was never run at 150M** and its BTREE
may degrade differently. The ratio is the claim, not the absolute.

### Size: 1.73×, not the 3.23× the first run said

The first size run used synthetic titles and reported Lance 3.23× smaller. That
was **wrong** — formulaic titles dictionary-compress far better than real ones.
Re-run on the **first 2M real rows of production `meta.sqlite`** (avg title 88
chars):

| | Lance | SQLite | ratio |
|---|---|---|---|
| 2M real rows | **196.4 MB** | 339.3 MB | **1.73×** |
| build time | 4 s | 40 s | 10× faster |

Projected to 150M: **24.9 GB → ~14.4 GB, a ~10.5 GB saving** on metadata alone
(*linear extrapolation from 2M rows; NOT measured at 150M*). Columnar dictionary
encoding on `type`/`section`/`year` is where it comes from, and those columns do
not grow with corpus diversity — so the ratio should hold or improve, but that
is reasoning, not measurement.

### Verdict: worth a real spike — the only such conclusion in this doc

C1–C4 were all closed off by measurement. C5 is the first that **survives** its
first contact with a benchmark. A Lance-based store could plausibly absorb
`meta.sqlite`, `abstracts.sqlite`, C3's locator, and `dense/ids.json` in one
table, taking the container from 4 storage technologies to 3 and saving ~10.5 GB
on metadata, at a ~1.15–1.72× lookup cost that §11's numbers say is affordable
(the locator is 1.3% of abstract fetch; metadata filtering is I/O-bound either
way).

**NOT adopted, NOT implemented. What is measured is narrow:** key→row lookup
latency at 20M rows, and size at 2M rows. What is **NOT** measured, and would
have to be before any migration:

1. **The dense leg.** Moving off usearch to Lance's ANN is a recall/size
   question that has not been touched. If usearch must stay, the count is 4
   again and most of the appeal evaporates.
2. **150M behaviour** — build time, index size, lookup latency, and resident RAM
   for a static mmap-distributed dataset. §10.3's 96× spike-vs-production gap is
   the standing warning against assuming this scales.
3. **Abstracts in Lance** — whether the trained per-script zstd dictionaries
   (ru −40% / fa −38% / ko −37% / zh −32%) survive, or whether Lance's own
   compression gives that back. §11 showed the payload is 83% of that store, so
   losing the codec would cost more than the envelope saves.
4. Immutable/static distribution semantics and whether Lance's manifest layout
   suits a read-only thin-client index.

**Not adopted. No production code changed by this spike.**

---

## 13. C6 (2026-08-02): **change the address, not the searcher** — the consolidation that is faster

§10–§12 all lost, and all lost the same way. Each kept `W-id` as the address and
swapped the thing that *searches* for it:

| store | resolving 1000 ids | |
|---|---|---|
| `meta.sqlite` B-tree (production) | 400.8 ms | baseline |
| tantivy fst term dictionary | ×10: 897.7 ms · ×1 locator: 27–54× per stage | §10.3, §11 |
| Lance BTREE scalar index | 255.1 ms | §12, 1.15× |

A `W-id` is a sparse 64-bit integer bearing no relation to where its row sits,
so resolving one is **inherently a search**. Done ~1000× per query in Python,
that *is* the ~400 ms post-filter mask. No storage engine fixes it, because the
engine was never the problem — **the address was.**

C6 gives every doc a global ordinal `0..N` at build time. Then the filter mask
is a numpy fancy-index into mmap'd columnar arrays — an array *index*, not a
search — and `W-id -> ordinal` (still needed for direct lookups) becomes ONE
vectorised binary search instead of k independent page faults.

**Note the direction.** C1 failed going `id -> DocId`, which forces an fst walk.
C6 goes `DocId -> ordinal -> metadata`: columnar throughout, never touching a
term dictionary. §11's addendum already indicated tantivy's fast-field reads are
not the bottleneck — only the term dictionary is.

- Bench: `spike/meta_consolidation/06_ordinal_addressing.py`
- Results: `data/eval_results/c6_ordinal_20260802_0704.json`
- Measured at the **true 150M production scale** (not a subset), against the
  measured production SQLite baselines in `c1_production_scale_20260802_0529.json`.

| k | ordinal mask | `W-id`→ordinal | `meta.sqlite` | binary search exact |
|---|---|---|---|---|
| 100 | 1.012 ms | 1.767 ms | 38.68 ms | ✅ |
| 500 | 0.695 ms | 0.659 ms | 203.43 ms | ✅ |
| 1000 | 0.161 ms | 0.956 ms | 400.83 ms | ✅ |
| 5000 | 0.565 ms | 3.870 ms | — | ✅ |

The ratios span 22×–2491× and are **noisy** — absolute times are sub-millisecond,
so small variance moves the multiple a lot (an independent earlier run measured
the k=100 mask at 0.405 ms vs 1.012 ms here). **The durable claim is not a
specific multiple**: it is that the ordinal path stays sub-millisecond to
low-milliseconds at every k where SQLite costs 38–400 ms — one to three orders
of magnitude, reproduced across two independent runs.

### Why this is structural, not a caching fluke

| artifact | size |
|---|---|
| filter columns (`year` i16, `type` i8, `is_oa` u8, `section` i8) × 150M | **0.75 GB** |
| sorted `W-id` index (int64 × 150M) | **1.20 GB** |
| **total resident** | **~1.95 GB** |

~1.95 GB stays permanently in RAM. **24.9 GB never can.** The residency is the
mechanism — which is why this survives where a page-cache accident would not.

### What it consolidates

| today | becomes |
|---|---|
| `meta.sqlite` 24.9 GB | mmap'd columnar arrays + sorted W-id index + title/DOI blob |
| `abstracts.sqlite` locator | ordinal-indexed `(block, off, len)` arrays — **C3's locator problem solved without tantivy or SQLite** |
| `abstracts.sqlite` blocks | flat zstd block file — **C3's good half** (§11, 3.8×) |
| `dense/ids.json` (41 MB resident) | the ordinal *is* the usearch key — file disappears (**C4, free**) |
| `dense/delta.sqlite` | reserved high ordinal range |

**SQLite leaves the container entirely**, replaced not by another database but by
flat arrays and a blob file. The three engines remain — §5/§6 proved they cannot
merge. Final honest scorecard: **search engines 3 (permanent); separate storage
databases 4 → 0.**

C6 subsumes the surviving parts of every prior candidate, and delivers what C1
*wanted* (removing the post-filter mask) by the one route C1 never tried:
reversing the lookup direction.

### Durability — good for THIS architecture, bad for a different one

Durable here because the thin-client index is **write-once and shipped static**;
ordinals are assigned at build and never move. tantivy segment merges do not
break it — the ordinal rides as a *fast field*, which is data, not a position.

Risks, with mitigations:

1. **Query-driven growth.** `DenseWarmCache` adds docs at query time with no
   build-time ordinal → reserve a high ordinal range for deltas.
2. **Rebuilds renumber everything.** Any persisted ordinal (caches, query logs)
   then silently points at the WRONG document — no error, wrong answer. This is
   the nastiest failure mode. Mitigate with an ordinal-space version stamped in
   the manifest and a hard refusal to load mismatched artifacts.
3. Ordinals must be **globally unique across all 10 sections**, not section-local.
4. The `W-id -> ordinal` array must stay sorted; it is rebuilt, never mutated.

The trade is **flexibility for speed**. A mutable database cannot do this. A
static shipped artifact can, and this one is the latter.

### Status

**MEASURED: primitives only, at 150M. IMPLEMENTED: no.** What is NOT measured,
and is required before this becomes a plan:

1. **Reading the ordinal from tantivy per hit.** §11's addendum suggests
   fast-field reads are not the bottleneck, but that run was ordering-confounded
   and its absolute numbers were explicitly marked unquotable. Needs its own gate.
2. Whether **SEISMIC** can be made ordinal-native or needs its own translation.
3. **Build-time cost** of assigning global ordinals across 10 sections at 150M.
4. End-to-end `_post_filter` / `_hydrate` rewrite and a record-tc byte-parity
   gate against the current retriever.

**Not adopted. No production code changed by this spike.**

---

> ## ⚠️ WHAT ACTUALLY HAPPENED TO C6 — read this before quoting §13 (2026-08-03)
>
> C6 was pursued in **`18_ORDINAL_ADDRESSING_DESIGN.md`**. Only ONE slice of the
> §13 vision was ever built, and the payoff is far smaller than §13 implies.
>
> **The "4 → 0 / SQLite leaves the container entirely" scorecard above did not
> happen and is not on a path to happening.** Storage databases today: still 4,
> zero removed. Of the "What it consolidates" table:
>
> | §13 claimed | actual status 2026-08-03 |
> |---|---|
> | `meta.sqlite` → columns + title/DOI blob | **filter columns only** (doc 18 §11–12), built, **gated OFF**. The title/DOI blob was rejected on *latency* grounds (doc 18 §13) but **REOPENED and measured against the consolidation objective on 2026-08-03 (doc 18 §15): a per-record zstd store replaces `meta.sqlite` for −10.22 GB while being FASTER than mainline (0.70×)**. Route measured at 1M-doc scale, **still unbuilt**, and the latency half is an extrapolation. |
> | `abstracts.sqlite` locator → ordinal arrays | **not built** |
> | `abstracts.sqlite` blocks → flat file | built as N5 (doc 18 §9, 2.89×), **gated OFF — no `.flat/` sidecar exists for any served section** |
> | `dense/ids.json` disappears (C4) | **not built** |
> | `dense/delta.sqlite` → reserved range | **not built** |
>
> **`meta.sqlite` removal now has a measured route** (doc 18 §15, 2026-08-03),
> reversing the "can never be removed" reading of §13's latency-grounds
> rejection: a per-record zstd title/DOI store plus the already-built ordinal
> columns replaces it for **14.69 GB vs 24.91 GB** while `_hydrate` gets
> *faster* (0.70× mainline). **Nothing is built**, and the latency half is a
> 1M-doc extrapolation, not a 150M result. Until it is built, the ordinal
> arrays remain **additive** to the 24.9 GB rather than a replacement.
>
> **The reachable target is 4 → 2, not 4 → 0** — see doc 18 §15's scorecard.
> `dense/delta.sqlite` is likely unreachable on correctness grounds, not
> performance ones: the warm cache mints addresses at query time, and the
> ordinal design's safety argument (§6 risk 1) is that addresses never move.
>
> **And the speed case collapsed.** Doc 18 §13's headline 3.20× was
> re-attributed on 2026-08-03 (doc 18 §14): it was measured against a
> `meta.sqlite` on **9p**, a WSL2-dev-container artifact that does not exist on
> the deployment target. Against a production-realistic baseline the whole
> ordinal win is **4.0 → 1.5 ms = 2.0% of the query**. §13's "the consolidation
> that is faster" is only true versus a filesystem production does not have.
>
> C6 survives, if at all, as a **residency** lever on RAM-constrained hosts —
> unmeasured, doc 18 §14 "not settled" #5.
