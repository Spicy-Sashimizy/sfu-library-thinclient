# Bottom line: one stack or two? (local vs server deployment)

**Date:** 2026-06-25 · The capstone decision, given everything in this directory.

> **⚠ CORRECTION 2026-06-26:** the "Qdrant uint8" tier recommendations below treat
> `datatype: uint8` as a meaningful fix for the 150M RAM bound. Per
> **`docs/qdrant_config_tuning/CONFIG_LEVERS.md` §1** that is over-optimistic: the
> on_disk sparse index is **already f16-bitpacked** and raw values stay on disk
> regardless of datatype, so uint8 is a tier-2 incremental lever, not a cure — the
> strategy's own "uint8 is a mitigation, not a cure" hedging is the correct read;
> treat the implied ~4× index shrink as retracted. Ship-on-Qdrant is confirmed;
> the no-JVM cure the assessment then pursued (the engine spike) is **MEASURED &
> STOPPED** (`docs/sparse_engine_project/`) — we ship on Qdrant and *tune* it
> (`docs/qdrant_config_tuning/`).

## The answer

**No — do not build two fully separate deployments. Build ONE stack with a
swappable storage backend (which you already have), and differ ONLY the
BM25F + sparse storage engine per tier.** That's "same deployment method,
different engine where the constraint differs" — not a fork.

## Why not two full forks

~80% of the stack is **tier-independent and already shared**, so forking it
doubles maintenance for no gain:

| Shared layer (same on laptop and server) | Where |
|---|---|
| SPLADE + dense **query encoders** (ONNX) | `lib/thinclient/` / encoders |
| **RRF k=60 fusion** | `federated_search.py` |
| **Cross-encoder rerank** + abstracts hot/cold | `lib/reranker.py`, sidecar |
| **meta.sqlite**, query log, metrics | shared |
| **Web GUI + MCP tools** | `web/`, `tools.py` |
| The SPLADE **`sparse_field` vectors** (no re-encoding either tier) | spool |

You also **already built the swap point**: `SFU_SEARCH_BACKEND`
(`thinclient`|`opensearch`) and `SFU_SPLADE_BACKEND` (`qdrant`|`bmp`) are a
drop-in retriever interface (same `search`/`dense_search`/result shape). So the
"two backends" already coexist behind one orchestration — keep it that way.

## What SHOULD differ per tier (and why)

The binding constraint is genuinely different at each tier, so the **storage
engine for the lexical+sparse legs** should differ — behind the shared interface:

| Tier | Scale (how users actually run it) | Binding constraint | Engine | JVM? |
|---|---|---|---|---|
| **Local / persona** | **one persona's HOT section live + cold packed** (~5–26M docs live; e.g. `social_sciences__recent` = 26.3M) | no-JVM, consumer hardware; **this is the 30M-gate-proven zone** | **thin-client: tantivy + per-persona Qdrant `uint8` + usearch** | no |
| **Server / full 150M** | all sections resident/queryable | serve without the Qdrant mutable-floor RAM wall | **immutable engine** (Infinity / OpenSearch+SEISMIC) | depends |

Everything *above* the storage leg stays identical. Even the index **build** can
share its front-end (corpus → SPLADE vectors) and differ only in the final ingest
target — so "two engines" is not "two pipelines."

## Decision rule for the server engine (the only open choice)

```
Is full-150M-on-a-server a near-term PRODUCTION goal?
├─ No — it's the eval baseline / future
│     → Do nothing new. Keep Qdrant behind the interface, apply uint8,
│       revisit when it's real. (Zero work.)
│
└─ Yes
    ├─ no-JVM NON-negotiable on the server
    │     → NOW: Qdrant uint8 on a 64–128 GB host (mitigates the floor).
    │       CURE: pilot Infinity (C++, no-JVM, immutable, unified) on 30M;
    │       migrate if its quality holds.
    │
    └─ no-JVM negotiable on the server
          → OpenSearch 3.7 + SEISMIC. Zero migration (you already run it,
            the corpus came from it), cures the floor, SOTA sparse.
            Restore openalex_works, port the thin-client BM25F/SPLADE config,
            re-run the parity harness.
```

## The one case that DOES justify a fuller split

If the **server** needs capabilities the shared orchestration can't express —
heavy aggregations/faceting, multi-tenant isolation, or live high-rate updates at
150M — **and** no-JVM is negotiable there, then a dedicated OpenSearch deployment
for the server is justified. **Even then**, keep RRF + rerank + encoders + GUI +
MCP shared; only the retrieval engine forks. You never need two *application*
stacks — at most two storage engines behind one app.

## Local = persona hot/cold — this is the right way to scale the local tier

Users run **one persona** locally: its **hot section live**, the rest **packed**
(`packer.py`, era sub-sections). That hot working set is **~5–26M docs**, not
150M — `social_sciences__recent` (the biggest) is 26.3M docs / 34 GB on disk;
most personas are smaller. **At that scale Qdrant's mutable floor is ~0.2–1.1 GB
(43 B/point) — the same regime as the measured 30M GREEN gate (1.44 GB resident,
p50 66 ms).** So the local/persona tier is exactly where Qdrant *belongs*: the
disease never appears, and you keep no-JVM on consumer hardware.

**BUT — one build change is required to realize it.** The hot/cold packer today
packs the **tantivy / abstracts** section dirs; it does **not** carve up the
Qdrant sparse leg. The live Qdrant collection `splade_150m` is **monolithic — all
150M points in one collection — and the anon floor scales with points IN the
collection, not with what you query.** A payload filter on the full collection
does **not** shrink the floor. So to ship a *light* local persona you must build
**per-persona (or per-section) Qdrant collections** — only that persona's hot
points — distributed as a Qdrant snapshot alongside the packed tantivy/abstracts.

> **Owed implementation:** extend hot/cold packing to emit a **per-section Qdrant
> snapshot** (the hot section's points as their own small collection), so the
> local install loads ~5–26M points (~1 GB floor), not the 150M collection
> (6.55 GB). This is the missing piece that makes "local = persona" actually
> light on the sparse leg. Until it exists, a local install pointed at the full
> `splade_150m` would inherit the 150M floor — i.e. the disease — defeating the
> point.

This also resolves the prior worry cleanly: **per-persona Qdrant collections at
~5–26M points do NOT perpetuate the 150M problem** — they are the proven-fine
tier. The disease is strictly a *full-150M-in-one-collection* phenomenon, which
is the server's job.

## "But doesn't keeping Qdrant perpetuate the root cause?" — yes, at 150M

Correct, and this sharpens the recommendation. The root cause is Qdrant's
**mutable per-point anon floor** (`ARCHITECTURE_EXPLAINER.md` §4). Whether keeping
Qdrant "keeps the disease" depends entirely on **scale**, because the floor is
~43 B/point:

| Scale | Qdrant anon floor | Index | Verdict |
|---|---|---|---|
| **15M (laptop)** | ~0.65 GB | ~20 GB | **non-issue** — fits trivially; the disease never manifests |
| **30M (demo)** | ~1.3 GB (measured 1.44 GB rest, p50 66 ms) | ~40 GB | **non-issue** — measured GREEN |
| **150M (server)** | **6.55 GB and rising** | 205 GB | **the disease** — RAM-bound, OOMs |

So:
- **At the local/demo tier, keeping Qdrant does NOT perpetuate the problem** — at
  ≤~30–60M the floor is ~1 GB, far below any host. (And a laptop can't hold 150M
  on *any* engine, so the local tier is inherently a subset tier.)
- **At 150M, you are 100% right: keeping Qdrant = managing the root cause forever,
  not curing it.** `uint8` + a bigger host are **mitigations** (smaller cacheable
  index, more RAM) — they shrink the symptom but the mutable anon floor is still
  there and still grows. **The only actual CURE at 150M is an immutable engine:**
  OpenSearch+SEISMIC (JVM) or Infinity (no-JVM, C++). LanceDB (which already
  stores sparse vectors but lacks a sparse index) would be the
  no-JVM cure once its sparse leg ships.

**Corrected stance:** the "keep Qdrant uint8 on a big host" server branch is
**explicitly symptom-management, not a fix.** If the goal is to *fix* 150M (it
has been this whole time), the server tier should **move off Qdrant to an
immutable engine**. Keep Qdrant only where it doesn't bite — the local/demo tier.
Use `uint8` at 150M only as a **bridge** while the cure (Infinity pilot or
OpenSearch+SEISMIC) is stood up — not as the destination.

**The clean long-term resolution** is one **immutable** engine that is *also*
no-JVM and embeddable, serving both tiers — which today means **watching
LanceDB** (immutable, embeddable like the thin-client; already stores sparse
vectors but still needs a sparse *index/search* — IVF-PQ/HNSW are dense-only), or
**Infinity** if you want a cure that exists now and are willing to migrate.

## One-line bottom line

**One application + orchestration, two storage engines behind the interface you
already have: thin-client (tantivy + Qdrant uint8) for local — where Qdrant's
floor is ~1 GB and harmless — and, for the 150M server, an IMMUTABLE engine that
actually cures the floor (Infinity if no-JVM matters, OpenSearch+SEISMIC if not).
Keeping Qdrant at 150M only manages the root cause; curing it means an immutable
engine. Not two deployments; one deployment with a per-tier engine.**
</content>
