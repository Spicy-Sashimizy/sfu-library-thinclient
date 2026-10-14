# Why is there no off-the-shelf FOSS for this exact use case?

> **CLOSED MEASURED 2026-06-26** — the bespoke sparse engine was MEASURED & STOPPED 2026-06-26 (verdict STOP in `07_INTEGRATION_PLAN.md` §8: pruning linear in corpus, ~50 GB inverted side at 150M). SEISMIC federated mmap took the slot (promoted 2026-07-06, `docs/archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md`); the FORMAT-WALL result is kept. Not current; do not resume.

**Status:** CLOSED MEASURED 2026-06-26

> **CLOSED — line MEASURED & STOPPED 2026-06-26.** The build-vs-buy case here argued the
> gap justified owning an engine; the later P3a/P3b measurements showed the bespoke build
> loses to FOSS at 150M (pruning linear in corpus; inverted-side RAM ~7.6× the Qdrant
> floor) → ship on Qdrant; pivot to SEISMIC if 150M-single-collection ever goes hard.
> Historical context only — current verdict in `README.md` + `07_INTEGRATION_PLAN.md` §8.

Short answer: **there is FOSS for every piece, and for the whole thing with a JVM
(OpenSearch) or as a young C++ DB (Infinity). What's missing is your specific
intersection** — and that intersection is empty for structural, not accidental,
reasons. This matters because it's the build-vs-buy question (Risk R7).

## What DOES exist in FOSS (so it's not "nothing")
| Need | FOSS that covers it |
|---|---|
| Lexical BM25F, no-JVM, immutable mmap | **tantivy** (Apache-2.0) |
| Learned-sparse (SPLADE) index | **Seismic**, **BMP** (research, but FOSS) |
| Dense ANN, mmap | **usearch**, **faiss**, **Lance** |
| All three legs unified | **OpenSearch/Elasticsearch** (JVM), **Vespa** (JVM/C++), **Infinity** (C++, no-JVM) |
| Immutable columnar substrate, no-JVM | **LanceDB/Lance** — but no sparse *index* yet |

So the right statement isn't "no FOSS exists" — it's **"no FOSS sits at
no-JVM + immutable-as-a-serving-property + indexed-learned-sparse + all-three-legs-
unified + 150M-static-distributable, at once."**

## Why that intersection is empty (structural reasons)
1. **You're in a rare quadrant.** No-JVM matters for *embedded/edge/laptop*; 150M
   corpora are almost always *server* deployments where the JVM is fine. So
   "no-JVM" people usually have small data, and "150M" people usually accept the
   JVM. **Huge corpus AND no-JVM AND immutable-distributable** is a thin slice —
   it's the *ship-a-server-scale-static-index-to-thin-clients* model almost nobody
   runs.
2. **Efficient learned-sparse tooling is research-grade.** Seismic/BMP are
   **academic artifacts** (SIGIR 2024) optimized for the metric in the paper —
   benchmark QPS/recall **in RAM**. Production properties (mmap, immutability,
   packaging, per-arch wheels) were never the goal, so they're **load-into-RAM by
   design**. That's exactly why BMP needs fixing rather than adopting.
3. **The "fake words" trick let SPLADE ride Lucene — which drained the demand.**
   Because learned-sparse fits Lucene's `rank_features`, everyone who wanted
   production sparse just used Elasticsearch/OpenSearch. So FOSS energy flowed into
   **Lucene plugins (SEISMIC-in-OpenSearch)**, not a standalone no-JVM sparse
   engine. The server crowd was already served; no one itched to build yours.
4. **No commercial sponsor points at your shape.** Well-funded search FOSS tracks a
   business model: Elastic (server SaaS), Qdrant/Weaviate/Pinecone (managed
   *mutable* vector DB), LanceDB (data lakehouse), ParadeDB (Postgres). **None
   monetizes "embeddable immutable no-JVM unified hybrid engine for a distributed
   static index."** Features land where revenue is; yours has no obvious sponsor.
5. **Mutability is where the market went.** Most RAG/app demand is *live upserts*,
   so vector-DB effort optimizes mutability — which is the very thing (MVCC,
   per-point resident trackers) that creates your 150M anon floor. Your need is the
   opposite (immutable, monthly rebuild), which the mutable-first ecosystem
   actively de-prioritizes.
6. **Unifying all three legs well is genuinely hard and recent.** Doing BM25F +
   learned-sparse + dense in one immutable store is the frontier — LanceDB is
   literally mid-building it (#1930), Infinity just shipped it in C++. It's a big
   lift with unclear monetization, so OSS does it slowly.
7. **Your requirement set is partly self-created.** It's the intersection of a
   specific corpus (OpenAlex 150M), a specific measured quality recipe (BM25F^3 +
   SPLADE + rerank + RRF + hot/cold personas), and a specific deployment goal
   (thin-client distributing a server-scale static index). **Bespoke intersections
   rarely have off-the-shelf FOSS** — FOSS forms around *common* needs, and you
   optimized your way into an uncommon one.

## The honest implication
The empty intersection is **not a red flag that you're doing something wrong — it's
a sign you're slightly ahead of the tooling.** The components are converging
(LanceDB adding sparse, OpenSearch adding SEISMIC, Seismic/BMP maturing); the
*integration* you need just hasn't been assembled by anyone with an incentive yet.

That's exactly why the rational move is the **small, surgical build** (mmap-fix
BMP) rather than a from-scratch engine: you're not filling a void the world doesn't
care about — you're assembling existing FOSS pieces (tantivy + BMP-algorithm +
Lance) across the one seam (`mmap` immutable sparse) that nobody had reason to weld
yet. And because it *is* the LanceDB-#1930 gap, the build has a plausible path to
**contribute back** — turning your bespoke need into shared FOSS, which is how
empty intersections eventually fill.

**Counterweight (R7):** if you don't want to own a custom engine, the two existing
FOSS that get *closest* are **Infinity** (no-JVM, unified, but a full new DB to
migrate to and not embeddable as a library) and **OpenSearch+SEISMIC** (unified,
mature, but JVM). "Build mmap-BMP" wins only if no-JVM + embeddable + your exact
quality recipe is worth more than not maintaining code. Decide that explicitly.
</content>
