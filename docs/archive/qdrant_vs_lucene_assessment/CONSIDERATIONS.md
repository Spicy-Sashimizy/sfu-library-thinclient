# Considerations — current vs past stack, least-overhead "best of both worlds"

> **CLOSED SUPERSEDED 2026-07-06** — the "should we swap off Qdrant back to Lucene?" question was answered instead by promoting SEISMIC federated mmap (`docs/archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md`). The RAM analysis and OOM findings remain the recorded evidence base for that move. Not current; do not resume.

**Status:** CLOSED SUPERSEDED 2026-07-06

**Date:** 2026-06-25 · Condensed decision guide. Numbers/cited claims live in
`SPECS_COMPARISON_150M.md` + `FINDINGS.md`. Online survey at the bottom.

## Goal-driven framing (no-JVM is a weighted goal) — read this first (added 2026-06-25)

**Decision frame:** rank by goals, not by language — but **no-JVM is itself a real
goal**, because the JVM is *ongoing* overhead (heap tuning, GC pauses, a 2 GB
floor, cluster machinery), not a one-time cost. So no-JVM is weighted in, just not
treated as absolute.

**The overarching goals:**
1. **Serve 150M without RAM-bound latency / OOMs** — durably fix the pain.
2. **Preserve ranking quality** (the +0.111 NDCG@10 lead).
3. **Low resident RAM on affordable hardware** (immutable mmap / bounded; no per-point anon tax).
4. **Unify lexical + sparse** (fewer engines, less ops overhead).
5. **No-JVM** — avoid the *recurring* JVM overhead. **Weighted, not absolute.**
6. **Least migration overhead** (one-time).
7. Two tiers: full-150M **server** + laptop/demo **thin-client**; no re-encoding.

**The tension this creates.** The property you want — *immutable segments +
bounded RAM + unified lexical/sparse* — is exactly what cures the Qdrant
mutable-per-point-floor pain (`ARCHITECTURE_EXPLAINER.md` §4). The catch: the only
**production** engine that delivers it *and* SOTA sparse speed today is
**Lucene-based (a JVM)** — OpenSearch+SEISMIC. The **no-JVM** engines either don't
solve the floor (Qdrant = mutable; Seismic/`sporse`/BMP = RAM-resident) or don't
ship a sparse *index* yet (LanceDB can store sparse vectors but can't search them
— IVF-PQ/HNSW are dense-only). So goals 5 (no-JVM) and 1+3+4 (cure the floor,
unified) **pull against each other at the 150M server tier** — that trade is the
whole decision.

**Goal-optimal by tier (no-JVM weighted):**

| Tier | Recommended | JVM? | Trade |
|---|---|---|---|
| **Laptop / demo (≤~30M)** | **thin-client (tantivy + Qdrant uint8)** | **no** ✅ | no-JVM wins outright; RAM is a non-issue at this scale |
| **Full-150M server — keep no-JVM** | **thin-client + Qdrant uint8 + 64–128 GB host** | **no** ✅ | honors no-JVM; **mitigates** the mutable floor (smaller cacheable index + more RAM) but doesn't *cure* it — the anon floor still rises with corpus |
| **Full-150M server — willing to migrate, stay no-JVM** | **Infinity (C++)** | **no** ✅ | **cures** the floor (immutable, unified, low-mem PGM index, faster sparse than Qdrant) — at a **one-time full-DB migration** (goal 6) + a quality eval owed |
| **Full-150M server — if no-JVM relaxed** | **OpenSearch 3.7 + SEISMIC** | **yes** ❌ | lowest *deploy* overhead (you already run it) + cures floor + SOTA sparse — but pays the **recurring JVM overhead** you're trying to avoid |
| **Future watch** | **LanceDB** | **no** ✅ | immutable + no-JVM + already stores sparse vectors, but **lacks the sparse index/search** (IVF-PQ/HNSW are dense-only) — needs the sparse *index* before it's usable for SPLADE |

**Reading the trade for the 150M server (the only place it's hard):**
- **Most weight on no-JVM + least migration →** thin-client + uint8 + bigger host.
  Keeps everything, no migration, no JVM; accepts the mutable floor as a *managed*
  ceiling rather than a cure.
- **Most weight on no-JVM + willing to migrate once →** **Infinity.** It's the
  strongest no-JVM engine that actually *cures* the floor and unifies the legs;
  the price is a one-time migration and a quality validation.
- **No-JVM negotiable →** OpenSearch+SEISMIC is objectively the lowest-overhead-
  to-stand-up (already running, corpus came from it) and ticks every box except
  no-JVM. Keep it on the table as the pragmatic fallback.

**Quality note (applies to OpenSearch *and* Infinity):** the −0.111 NDCG@10 gap
was measured on OpenSearch's **old config**, not the thin-client's. Low per-leg
overlap (bm25f 0.532, splade 0.399) ⇒ the gap is **mostly config/analyzers, not
engine**. BM25F + SPLADE vectors are portable, so it's **plausibly recoverable**
by porting the thin-client config — a testable ablation either engine should pass.

**Bottom line:** with no-JVM weighted back in, there is **no zero-cost win** at
150M — you choose which overhead to pay: **mutable-floor management** (stay
no-JVM, thin-client + uint8 + RAM), **one-time migration** (no-JVM cure via
Infinity), or **recurring JVM** (OpenSearch+SEISMIC, zero migration). For the
**laptop/demo tier the choice is clear — stay no-JVM thin-client.** The cheap
moves below (uint8, host-sizing) are worth doing **now regardless**, since they
help every no-JVM path.

---

## The trade in one line

- **Past (OpenSearch/Lucene):** lower RAM-at-scale + lower disk, but a JVM, no
  laptop tier, and **−0.111 NDCG@10** vs the current stack.
- **Current (tantivy + Qdrant + usearch):** **+0.111 NDCG@10**, no-JVM, exact
  sparse — but Qdrant's f32 sparse leg is RAM-bound at 150M on small hosts and
  ~2.3× the disk.

The "best of both worlds" is **not a third engine** — it's two cheap moves on the
stacks you already run, chosen by tier.

## Ranked by tech overhead (do the cheap ones first)

### 1. Qdrant sparse `datatype: uint8` — LEAST overhead, attacks the real pain
- **What:** re-create `splade_150m` with sparse `datatype: uint8` (and optional
  server-side IDF). Same engine, same serving code, no new dependency.
- **Why it's the best first move:** the 150M problem is **RAM-bound latency**, and
  uint8 shrinks the *searchable* index ~4× (~7 GB est. vs the f32 index), so far
  more page-caches → latency drops, on the host you already have. Total disk stays
  ~205 GB (Qdrant keeps original f32 on disk), but disk was never the binding pain.
- **Risk: ~zero on quality.** The B1 gate already measured BMP 8-bit == Qdrant f32
  (overlap@10 1.0, τ 1.0, NDCG Δ 0.0). Re-run B1 + `measure` against the uint8
  collection to confirm.
- **Overhead:** one re-ingest (~9.8 h, scripted) + one validation pass. **No
  migration.**

### 2. Right-size the host (if staying on Qdrant for 150M) — zero code
- 64–128 GB box page-caches enough of 205 GB to leave the RAM-bound regime
  (`DO_SIZING.md`). Combined with (1), the cacheable fraction jumps and the
  fitting-tier ~66 ms becomes reachable at 150M. **No code, no migration.**

### 3. OpenSearch 3.7 + SEISMIC sparse ANN — best server-tier "both worlds",
###    LOW overhead because you ALREADY run 3.7.0
- **What:** their `sfu-library-mcp-training` OpenSearch is **already 3.7.0 /
  Lucene 10.4.0** (probed live 2026-06-25). OpenSearch **3.3+ ships SEISMIC** as a
  native neural-sparse ANN method — the SIGIR'24 SOTA sparse algorithm — reported
  **sub-12 ms at billion scale, ≥90% recall, 50M vectors/node** (OpenSearch blog).
- **Why it's "both worlds" for the server tier:** you get **Lucene's RAM/disk
  efficiency + bounded heap** (the axis Qdrant loses) **AND** modern SPLADE ANN
  speed (the axis BMP/Qdrant struggled with) — in the **same engine you already
  operate**, no new database. It also keeps BM25F native in the same index.
- **Catch:** it's the **server/JVM tier**, not the laptop tier; and the 150M
  `openalex_works` index is **archived** — you'd restore it, then flip the
  neural-sparse field to the SEISMIC ANN method and re-run the parity harness.
- **Overhead:** restore index + enable SEISMIC + re-validate. **No new stack.**
  This is the lowest-overhead way to get SOTA sparse *and* Lucene RAM behaviour.

## Recommended split (least total overhead)

| Tier | Stack | Sparse leg | Rationale |
|---|---|---|---|
| **Laptop / demo (≤~30M)** | keep thin-client | **Qdrant uint8** | no-JVM, +0.11 quality, fits RAM; move (1) makes it snappier |
| **Full-150M server** | OpenSearch 3.7 (already run) | **SEISMIC ANN** | Lucene RAM/disk + SPLADE ANN speed, same engine; restore the archived index |
| **Bridge (stay all-Qdrant at 150M)** | thin-client on 64–128 GB | Qdrant uint8 | if you don't want to reopen OpenSearch; moves (1)+(2) |

Both legs stay quality-equivalent — engine choice doesn't change BM25/SPLADE math
(measured, `THIN_CLIENT_STACK_RESEARCH.md`); it changes RAM/latency/packaging.

---

## Online survey — methods NOT already in the docs (only the significant ones)

Filter applied: *only flag if it's a meaningful metric win AND plausibly worth a
painful move.* Most options below are **noted, not recommended**, because they
don't beat moves (1)–(3) enough to justify a migration.

| Method | What it is | Verdict for this stack |
|---|---|---|
| **SEISMIC in OpenSearch 3.3+** | SIGIR'24 SOTA sparse ANN, now a native OpenSearch neural-sparse method; sub-12 ms @ billion-scale, ≥90% recall, 50M/node | **RECOMMENDED (move 3).** Significant *and* low-overhead — you already run 3.7.0. The single best new datapoint. |
| **Qdrant uint8 sparse datatype + server-side IDF** | per-value quantization inside the sparse index; Qdrant computes IDF server-side | **RECOMMENDED (move 1).** Significant for RAM/latency, ~zero migration. |
| **Standalone Seismic (`pyseismic-lsr`, Rust)** | the same SOTA algorithm as a no-JVM library; µs retrieval; "21× faster than BigANN winners" | **Noted.** Already evaluated (picked BMP over it) — still **source-only wheels** (`pip install --no-binary`) and **RAM-resident** (~8 GB/9M → huge at 150M). Get SEISMIC via OpenSearch instead; keep this only for a fixed-size subset/laptop index. |
| **InfiniFlow Infinity** | RAG-native DB; block inverted+forward sparse index; benchmarks **faster than Qdrant on sparse** | **Noted, not recommended.** Faster sparse, but a **full new database migration** — not worth it when OpenSearch SEISMIC gives the speed in an engine you already run. |
| **ParadeDB `pg_search` (tantivy-in-Postgres) + VectorChord-BM25** | BM25 + sparse/dense inside Postgres; VectorChord-BM25 claims **3× faster than Elasticsearch BM25** | **Noted, conditional.** Only compelling if you want to **consolidate on Postgres** as the system of record. Otherwise it's a new stack for no quality gain (BM25 math is portable). |
| **Qdrant BM42** | Qdrant's attention-weighted hybrid baseline (alternative to BM25/SPLADE for short docs) | **Skip.** Aimed at short-doc RAG; your SPLADE+BM25F already wins on the academic corpus. Not a metric win here. |

**Bottom line:** the genuinely new, significant, *low-overhead* option you hadn't
logged is **SEISMIC — and you can have it without leaving the Lucene family you
already run (OpenSearch 3.7)**. Everything else either needs a painful migration
for no quality gain, or is already in your docs. Pair SEISMIC (server tier) with
Qdrant-uint8 (laptop/demo tier) and you have the best-of-both with the least
total moving.

Sources: see the chat message that generated this doc (OpenSearch SEISMIC blog +
docs, Infinity benchmarks, Seismic repo/docs, ParadeDB/VectorChord, Qdrant sparse
datatype docs).
</content>
