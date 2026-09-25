# 01 — Architecture

**Status:** DEFERRED 2026-09-25 (DESIGN ONLY / UNMEASURED since 2026-06-30; no code was ever written) — **DESIGN ONLY / UNMEASURED (2026-06-30).** Every number below is *est.*
or "unmeasured / design only" until the spike in `02_SPIKE_PLAN.md` runs.

## The shape that survives the constraints

```
ingest doc ──▶ assign semantic ID        (host CPU, frozen tiny model, deterministic)
            ──▶ doc lands in mutable warm buffer   (searchable NOW, RAM)
buffer fills ─▶ build ONE small immutable sparse segment, keyed by ID prefix
            ──▶ flush; warm-buffer entries graduate to the immutable segment
periodic ────▶ compact: merge small immutable segments into bigger ones
```

The **only mutable, online component is the ID assignment + a small RAM
buffer.** Everything downstream of the ID stays immutable — which is exactly the
constraint. The autoregressive ID is what makes incremental segment-building
*coherent* instead of a full rebuild.

Pieces that already exist and map directly:
- 2M-doc shards → the *segments*.
- The dense warm cache (`lib/thinclient/dense_cache.py`, RAM + SQLite durability)
  → the pattern for the *mutable warm buffer* that plugs the ingest→flush gap.
- `sections/<subject>__<era>/` directory layout → depth-2 *prefix routing*,
  already in place.

## The ID is a routing address, not a name

A self-routing hierarchical ID means the **prefix IS the path**:

```
sections/<subject>__<era>__<cluster>/splade_NNN.seismic
```

A query's candidate segments = the directories in its ID-prefix neighbourhood.
Consequences:
- The routing hot path can **skip the `meta.sqlite` id→section lookup** (the ID
  already encodes location).
- **W-id stays canonical** for provenance (the OpenAlex join, Analytics
  disclosures); semantic-id is a *secondary routing key in a sidecar*, never a
  replacement for the int-PK.

## Elastic prefix-depth sharding (the scale up/down knob)

Because the ID is hierarchical, shards are cut at **any prefix depth**:

| Deployment | Cut depth | Result |
|---|---|---|
| Laptop / small | depth 2 | a handful of big segments |
| 150M / big host | depth 5 | thousands of small segments |

Resharding up or down = "re-bucket by a different prefix length," **not**
"recompute IDs." This is the property Lucene/Elasticsearch structurally lacks
(ES primary shard count is fixed at index creation; changing it means reindex).

## Interaction with the mmap infra — the load-bearing tension

The mmap-bmp thesis works because there are **a few big immutable files**: the OS
page-cache keeps hot pages resident, posting lists are contiguous, faults are
few.

**LSM pulls the opposite way — it produces many small segment files.** A term's
posting list then scatters across N segments → more mmap regions, more
page-table / anon-bookkeeping overhead (already noted as scaling with point
count), fragmented faults, read amplification. This is the classic Lucene "too
many segments" problem, and on a page-cache-resident design it **directly
inflates resident-set size and tail latency.** The **compaction policy is the
load-bearing wall**, not a nicety. (This is why `04_LUCENE_BORROW.md` exists.)

**The semantic ID is what rescues mmap from LSM** — and this is the real
justification for the *learned* part, beyond routing. If similar docs cluster
into prefix-adjacent segments, a query touches **few** segments, hot pages are
**semantically coherent**, and fan-out + resident set stay bounded. Locality is
not a bonus; it is what keeps LSM-on-mmap tractable.

## SEISMIC-specific realities

- **No cheap byte-level merge.** Lucene merges by concatenating posting bytes;
  SEISMIC clusters by centroids and is build-once. So "compaction" = a
  **localised rebuild of one prefix's segment** over the union of its small
  segments' docs. Scoped to one prefix it is manageable, but it is a rebuild,
  not a stream-copy — budget for it.
- **Layering is coherent with existing patterns:** mmap'd immutable
  semantic-segments = the cold, page-cache-managed tier; the RAM warm buffer
  (mutable, *not* mmap'd, small) = the hot recent delta; flush moves
  buffer→new mmap'd segment. Same RAM-hot + durable-cold split the dense warm
  cache already uses.

## The three honest caveats (carried from the discussion)

1. **"Searchable" has a flush latency.** New docs are instantly searchable only
   via the warm buffer; they enter the immutable leg at flush. Standard NRT, but
   be precise: not "fully indexed at ingest instant."
2. **"Any hardware" forces bit-reproducible assignment.** argmin-over-distances
   can route the same doc to different leaves across CPUs/BLAS on float ties.
   The ID must be bit-reproducible — fixed-point/integer centroid distances or a
   deterministic tie-break — or it is not a stable cross-host routing key.
3. **Drift pinned to rebuild boundaries.** Re-fitting the tree changes the ID
   space; immutable segments minted under `tree_v1` cannot be re-keyed without a
   rebuild. Re-fit only at the monthly-rebuild boundary, version every segment
   with the `tree_vN` that minted its IDs, let the router span at most two
   generations.

## What is novel vs. what is Lucene

After the Lucene reality-check (`DECISION_TRAIL.md`), the defensible novelty is
**only two things**:
1. a **stable hierarchical semantic ID** (Lucene docids are ephemeral
   per-segment ordinals, reshuffled every merge, zero semantics); and
2. **elastic prefix-depth resharding** (Lucene/ES cannot reshard without
   reindex).

Everything else — segments, flush, merge, NRT, tombstone deletes, mmap — is
Lucene prior art to **borrow, not reinvent**. See `04_LUCENE_BORROW.md`.
