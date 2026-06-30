# Build Plan 04 — Cross-engine metadata externalization (store-once, hydrate-by-id)

**Status:** DESIGN (created 2026-06-28, unbuilt). **Solves:** serving RAM / storage
duplication across the lexical (BM25F) and sparse engines. **Orthogonal** to the
SEISMIC build wall — but a real win that applies even to the *current live Qdrant
deployment*, so it's worth doing regardless of the SEISMIC verdict.

## The idea in one line

The only thing genuinely duplicated across the lexical and sparse engines is
**document metadata/payload** (text, title, abstract, oaid, authors). Keep **one
canonical doc store**, strip the duplicate copies from the engines, and **hydrate
search results by doc-id join** at query time.

## Critical scope boundary (why this does NOT touch the RAM wall)

The 47 GB build floor is the SEISMIC **forward index = SPLADE vectors**, NOT
metadata. SEISMIC stores `doc_id → sparse vector`; it holds **no** text/abstract to
strip. The duplicated metadata lives in the *lexical engine* and/or *Qdrant payload*
— so externalizing it is a serving/storage win, **not** a build-RAM win, and **not**
a way to "rehydrate the vectors from the other engine" (BM25 has neither the SPLADE
weights nor the expansion terms — it cannot supply forward-index data).

## What overlaps, and the fix

| Data | Where it's duplicated today | After |
|------|-----------------------------|-------|
| doc text / title / abstract / authors | lexical stored-fields **and** Qdrant payload | single doc store (KV / on-disk), keyed by doc-id |
| doc-id ↔ internal-id map | each engine | each engine keeps only ids + index structures |
| BM25 postings | lexical only (not duplicated) | unchanged |
| SPLADE vectors | sparse only (not duplicated) | unchanged |

## Build steps

1. **Pick the canonical store.** Cheapest: a single on-disk KV (e.g. an
   `oaid → {title, abstract, …}` mmap'd store or SQLite) that both serving paths read
   by id. (Qdrant can also *be* this store via id-only points + `on_disk_payload`.)
2. **Strip duplicates from the engines:**
   - Qdrant: set **`on_disk_payload=true`** (payload off the RAM working set), or
     drop payload entirely if the external KV is canonical.
   - Lexical engine: stop storing the heavy fields as retrievable stored-fields;
     keep only what's needed for scoring (indexed terms) + the doc-id.
3. **Hydrate at result time:** after RRF produces the final top-k doc-ids, batch-fetch
   metadata from the canonical store for *only those k results* (not during scoring).

## RAM / storage budget

- **Qdrant serving RAM:** `on_disk_payload` removes the payload from the anon working
  set (current ~6.55 GB anon floor includes payload structures) — measure the actual
  drop. *est.* meaningful but UNMEASURED here.
- **Disk:** one copy of metadata instead of two → roughly halves metadata storage.
- **Build RAM (SEISMIC):** **unchanged.** This plan does not pretend to help it.

## Risks / honest caveats

- **Hydration latency:** an extra id→metadata fetch per result. Negligible if batched
  over the final top-k (k≈50) against an mmap'd/SSD KV; do **not** hydrate during
  candidate scoring.
- **Consistency:** the canonical store must stay in sync with the index doc-ids
  (handle deletes/updates). Use the same id space across engines + store.
- **Not a vector dedup.** Re-state for reviewers: this strips *metadata*, never the
  SPLADE vectors. The vectors are not reconstructable from the lexical engine.

## Success criteria

1. Single canonical metadata store; engines hold ids + index structures only.
2. Measured Qdrant serving-RAM reduction after `on_disk_payload` / payload strip.
3. End-to-end result hydration with no measurable latency regression at k≈50.

## Provenance

Qdrant `on_disk_payload` + id-only points + id-mapper (Qdrant Storage/Payload docs);
the cross-engine overlap analysis (2026-06-28 session). Applies to the **live**
Qdrant leg independent of the SEISMIC decision.
