# Qdrant config levers — what each one actually does (research-confirmed)

**Date:** 2026-06-26. Research against Qdrant 1.18 docs, source (DeepWiki),
release notes, PRs, and maintainers' large-scale guidance.

## The headline: the config is already near-optimal

The active config is `on_disk=true` sparse + `on_disk_payload=true`. Research
confirms this is **already the maintainers' recommended large-scale path**:

| Lever | Status | What it does |
|---|---|---|
| `sparse index.on_disk=true` | ✅ already set → `InvertedIndexCompressedMmap` = mmap'd postings + **bitpacking + f16 compression** | Moves posting lists out of RAM into a page-cache-backed mmap file. This is the compressed-mmap path. |
| `on_disk_payload=true` | ✅ already set | Payload (oaid/year/type) stays on disk, not resident. |
| `datatype` on sparse index | ⚠️ **not set** (`{"on_disk": true}` only in live config) → currently the default path | Locking `float16` explicitly guarantees the compressed-mmap path rather than depending on `on_disk` defaulting to it. See §1. |
| `default_segment_number` | = 24 on the 150M live collection | Lower = fewer, larger segments = less per-segment metadata. Maintainer large-scale recommendation for multitenancy. Not a RAM emergency; left alone unless A1 says otherwise. |
| `async_scorer` env | ⚠️ **not set** in the demo compose | Latency recommendation for page-cache-bound serving (the 150M case). See §3. |

So the forcing function isn't "fix a misconfig" — it's "lock the good path
explicitly so it can't silently regress, add the one latency env the large-scale
guide recommends, and confirm the floor." That's a narrow lever set, by design.

## The anon floor (6.55 GB at 150M) — what config can and can't do

| Claim | Verified | Source |
|---|---|---|
| The per-point id tracker is **required-resident RAM**, not reclaimable | ✅ Qdrant's own 400M LAION example budgets "~12 GB ID tracking (required resident, ~30 B/pt)" — our 43 B/pt at 150M is in the same band | large-scale-search tutorial |
| `on_disk=true` sparse index is **already compressed** (mmap + bitpack + f16) | ✅ `InvertedIndexCompressedMmap` | DeepWiki sparse-vector-support |
| Immutable segments get a **~2× smaller compressed id tracker** (PR #6023), but **only on optimized/immutable segments** | ✅ PR #6023 shipped ~v1.13.5, live in our 1.18.2 — appendable segments still hold the uncompressed map | PR #6023, memory-consumption article |
| Single-collection multitenancy + fewer/larger segments is the maintainer-endorsed scaling path | ✅ "the only long-term/scalable solution"; lower `default_segment_number` to cut per-segment metadata | discussion #4826 |

**Net:** the floor is structural at steady green. The only thing that might
*part* of it is appendable-segment overhead — see `MEASURE_FIRST.md` (A1). The
only levers that *scale the floor down linearly* are outside Qdrant config:
**fewer points** (product call) and **sharding**. Config cannot remove it.

## §1 — `datatype`: float16 lock (not uint8)

### Corrected stance on uint8 (the research error)

An earlier research turn recommended `sparse index.datatype=uint8` as **move #1**
and claimed it would "~quarter the on-disk index" / "shrink the searchable
index ~4× (~7 GB est. vs the f32 index)". **That claim was over-optimistic and is
superseded here:**

- The `on_disk=true` sparse index is **already f16-bitpacked** regardless of
  `datatype`. Forcing `uint8` quantizes the *search* index values further — a
  small incremental win, not a 4× shrink.
- **Raw values are retained on disk regardless of `datatype`** — `datatype`
  changes the index's search precision, **not the raw store**. So it does not
  shrink the 205 GB on-disk footprint the way the old claim implied.

The **real index-shrink lever is fewer/shorter postings via SPLADE doc-term
pruning** (encode-time, ours to control), not a smaller per-value type. See §4.

> **SUPERSEDED 2026-06-26:** the uint8-as-4×-shrink claim in
> `docs/qdrant_vs_lucene_assessment/CONSIDERATIONS.md` and
> `ARCHITECTURE_EXPLAINER.md` is corrected here. uint8 is a *tier-2 incremental*
> lever, demoted from move #1; revisit only after a measurement re-run confirms
> the quality cost is free.

### What we actually do with datatype

Lock `float16` explicitly on the sparse index so the compressed-mmap path is
guaranteed, not merely defaulted-via-`on_disk`. This is a one-line-per-call-site
patch to `scripts/spike_qdrant_sparse.py`:

```python
index=models.SparseIndexParams(
    on_disk=True,
    datatype=models.Datatype.FLOAT16,  # lock the compressed-mmap path explicitly
)
```

`uint8` only if a future fidelity re-run (`scripts/eval_quant_fidelity.py`)
says the quality cost is free — and even then it's a latency/RAM trimming, not
a storage lever.

## §2 — segment number

`default_segment_number=24` on the live 150M collection. The large-scale guide
suggests lowering it to consolidate into fewer, larger immutable segments (less
per-segment id-tracker overhead). This interacts with A1: if force-optimizing
to green does the compaction, the segment count may already be settling. Leave
it alone unless A1's measurement shows residual overhead, then consider
lowering as a follow-up nudge.

## §3 — `async_scorer` env (latency, for the page-cache-bound case)

For the 150M case where we are **page-cache-bound** (the 205 GB index is only
~7% cacheable on a 23 GB host), the maintainers' large-scale recommendation is
`QDRANT__STORAGE__PERFORMANCE__ASYNC_SCORER=true`, which scores asynchronously
and overlaps disk reads. This is a **latency** lever (helps p95 when disk-bound),
**not a RAM lever** — it does not touch the anon floor. Patched into the demo
compose under the `qdrant` service. Pair with the existing `mem_limit: 8g` cap
(which bounds anon) on the 30M demo tier.

## §4 — the real index-shrink lever: SPLADE doc-term pruning (B2)

Independent of Qdrant internals, **ours to control at encode time**: prune each
document's SPLADE term list to its top-k nonzero terms. Fewer nonzeros per doc →
fewer/shorter posting lists → smaller on-disk index → smaller page-cache budget
→ smaller host for the same latency. This is the lever that actually shrinks the
205 GB, and the right way to re-run the existing NDCG eval (`BENCHMARK_METHODOLOGY.md`)
to find the recall/size knee. **Not in scope for this directory's first pass**
(recorded here so it isn't lost); the config-tuning line ships the float16 lock
+ async_scorer + A1 measurement first, and pruning is the next-tier lever.

## Bottom line

Qdrant isn't misconfigured. The lever set on the config side is narrow:
1. **Confirm** the floor (A1 — possibly reclaims appendable overhead).
2. **Lock** `datatype=float16` explicitly (one-line, no behavior change, just
   no silent regression).
3. **Add** `async_scorer=true` (latency, page-cache-bound case).
4. Record the corrected uint8 stance so the docs stop carrying the 4× claim.

Everything else that materially moves the RAM number (point count, sharding,
SPLADE pruning) is a **product/encode** decision, not a Qdrant config knob.
