# 01 · Architecture — sequential federation

**Created 2026-06-30, implemented 2026-06-30 (mechanisms A + B).** External claims
tagged `[literature]`. Mechanism (C) `mlock`/`MADV_RANDOM` remains design-only.

## The model in one picture

```
Parallel (existing):   load S0..S7 → [search S0 | S1 | ... | S7 concurrently] → merge → top-k
                       resident: ~all 8 shards         latency: ≈ max(shard_i)

Sequential (this dir): for i in 0..7:  fault-in Si → search Si → release Si → keep its top-k'
                       then merge all per-shard top-k' → top-k
                       resident: ~1 shard at a time     latency: ≈ Σ shard_i
```

The query is encoded **once** (SPLADE) and the *same* encoded sparse vector is
issued to each shard — so encoding is not repeated per shard.

## Why results are identical to parallel (the load-bearing property)

SEISMIC scores are inner products on a **shared SPLADE vocabulary**: every shard
was built from the same token space, and the identical encoded query is sent to
each. So per-shard scores live in the **same dot-product space** → directly
comparable. A global top-k is just "take each shard's local top-k′, merge by raw
score, keep the best k." **Merging by score is order-independent** — visiting
shards sequentially vs concurrently cannot change the merged set. Therefore:

> **Sequential top-k ≡ parallel top-k, bit-for-bit** (same `k′` over-fetch). This
> is what makes sequential a *serving* change with **zero quality impact** — the
> demo returns the validated answers. (Asserted as a test in `03_TESTING.md`.)

This mirrors the federation result-safety already proven for the parallel path
(overlap@10 0.9967, `[OURS]`); sequential inherits it because it is the same
merge over the same per-shard results.

## The three resident-bounding mechanisms

Layered from simplest to most aggressive. G-SEQ-1 (bounded RAM) needs at least
(A); (B) and (C) tighten it.

### (A) Process one shard at a time (the core change)
Replace the `ThreadPoolExecutor` fan-out (`sharded_seismic_backend.py:190`) with a
serial loop. Even with all shards mmap'd, only the **actively-searched** shard's
pages are faulted in at any instant; under memory pressure the kernel reclaims the
idle shards' file-backed pages. This alone collapses the *transient* working set
from ~8 shards to ~1, which is the whole point. Sequential, one-region-at-a-time
access is also the pattern SSDs + mmap serve best — **sequential ≈ 3× random**,
and page-fault storms are the dominant cost otherwise `[literature]`
([USENIX ATC'20 FastMap](https://www.usenix.org/system/files/atc20-papagiannis.pdf)).

### (B) Explicitly release each shard after searching it — `madvise(MADV_DONTNEED)` — SHIPPED 2026-06-30
**Implemented** as `MmapSeismicIndex.release_pages()` (pyo3, on the C2.5 reader) +
called by `SequentialSeismicBackend._fan_out` after each shard's search (guarded
`hasattr`, so stock shards / an older `.so` degrade to a no-op). Purely additive to
the shared `.so` — `ParallelSeismicBackend` never calls it, so the parallel path is
unchanged. Verified: T1 bit-identical equivalence still holds WITH `release_pages`
active, and a dedicated re-fault test confirms a subsequent search returns identical
data after `MADV_DONTNEED` (the `madvise(2)` contract).

After a shard's search returns, advise the kernel the range is done:
`MADV_DONTNEED` **immediately drops the resident set** for that mapping (re-faults
from the backing file on next use) — the canonical out-of-core "bound the working
set across phases" tool `[literature]`
([madvise(2)](https://man7.org/linux/man-pages/man2/madvise.2.html)). This makes
the ~1-shard bound a hard guarantee rather than relying on kernel reclaim timing.
Exposed from the C2 reader (`spike/seismic_upstream/src/pylib/mmap_index.rs`).

### (C) Hybrid: pin the small side, stream the big side — `mlock` + `MADV_RANDOM`
G3 split `[OURS]`: at 150M the **forward index dominates (~85%)**; the
inverted+summary side is small. DiskANN's design — *keep the small/compressed
structures resident, stream the large ones from disk on demand* `[literature]`
([DiskANN NeurIPS'19](https://suhasjs.github.io/files/diskann_neurips19.pdf)) —
maps directly: **`mlock` the inverted+summary side** (small, hit repeatedly across
all shards) so it never pages out, and `MADV_RANDOM` the forward index so the
kernel doesn't waste read-ahead on the random pointer-chases. This keeps the hot
skip structures warm while the bulky forward data pages in sequentially.

## Latency levers that compose with sequential (free, no rebuild)

Sequential makes per-shard time the unit of cost, so the engine dials that cut
per-shard work multiply across all 8:
- **`query_cut`** (currently all 64 terms) and **`heap_factor`** (currently 0.8) —
  the free quality↔speed dials (see
  [`../seismic_150m_testbed/08_LATENCY_RESEARCH.md`](../seismic_150m_testbed/08_LATENCY_RESEARCH.md) §C1).
- **`k′` over-fetch** per shard (default `max(2×k, 100)` since 2026-07-08, G8f;
  previously 4×k) — smaller k′ = less per-shard heap work; the federation-overlap
  gate bounds how low it can go safely (measured: k′=100 @ top_k=50 is merged-
  overlap-safe at 0.999, `g8f_shardmerge_profile_kprime_20260708.json`).

## Shard-failure isolation (WI-10, 2026-07-17 — env-gated OFF by default)

A property of the federation, not a happy-path accident: any ONE of the 8
shards down (missing/truncated/unreadable file, search exception, hang/timeout)
→ the OTHER 7 keep serving. Per-shard LOAD AND SEARCH fault boundaries in BOTH
`ParallelSeismicBackend` + `SequentialSeismicBackend` (the cascade design —
`_fan_out` is the only per-method behavior, the guard wraps it identically).

- Gate: `SFU_SEISMIC_SHARD_FAULT_BOUNDARY=1` (default **OFF** = byte-identical
  federation, T1 unaffected: a non-faulted shard set has zero behavioral change;
  ON with no fault → the guard passes every result through unchanged).
- A failed-to-load shard → `None` placeholder + marked down; a thrown/timed-out
  search (`SFU_SEISMIC_SHARD_SEARCH_TIMEOUT_S`, default 30) → `[]` for that shard
  + recorded fault; the reprobe cooldown (`SFU_SEISMIC_SHARD_REPROBE_S`, default
  10) re-admits on a successful probe. The federation merges surviving shards'
  results with `degraded_shards:[…]`; `fault_status()` surfaces it to `/health`.
- Hash sharding ⇒ a lost shard costs a BOUNDED ~1/8 of recall with no score-
  comparability issue (each shard is a disjoint doc-id hash partition, scored in
  one shared SPLADE vocab space — doc 09: calibration unnecessary by
  construction). **MEASURED 2026-07-17**: recall retention@10 = **0.850** across
  every fault class (in the pre-registered [0.80, 0.95] band) →
  `docs/infrastructure/DEMO_DEPENDABILITY.md` §WI-10.

## Code touch-points (IMPLEMENTED — two distinct classes, 2026-06-30)

**Shape (Option 3 — lowest cascade risk):** two DISTINCT serving classes —
`ParallelSeismicBackend` (server-side, persistent `ThreadPoolExecutor` fan-out
since 2026-07-08 G8g) and
`SequentialSeismicBackend` (localized, RAM-efficient, serial one-shard-at-a-time
loop) — sharing **pure module-level helpers** (`_merge_topk`, `_load_one_shard`,
`_prepare_query`, `_load_manifest`, `_EncoderShim`), with NO inheritance coupling
of per-query behavior and NO shared mutable instance state. A parallel thread bug
physically cannot reach a `SequentialSeismicBackend` instance. The shared merge is
ONE pure function, so the two methods cannot silently drift (the cascade vector
that matters most for a system whose correctness story is "bit-identical top-k").

- `src/lib/thinclient/sharded_seismic_backend.py`
  - `ParallelSeismicBackend` / `SequentialSeismicBackend` — each owns its `_fan_out`
    (the ONLY per-query behavior that differs); inherits a private construction +
    thin-wrapper shell. `SequentialSeismicBackend._fan_out` is the serial loop
    (mechanism A — kernel reclaims idle shards' file-backed pages);
    `ParallelSeismicBackend._fan_out` is the `ThreadPoolExecutor` fan-out
    (persistent per-backend pool since 2026-07-08 G8g — built once in
    `__init__`; per-instance, so no cross-class shared state).
  - `_merge_topk` (module fn) — the ONE shared score-merge, order-independent →
    bit-identical top-k across both classes (the load-bearing property).
  - `ShardedSeismicBackend` — back-compat `__new__` selector returning the matching
    concrete class (default `parallel`); kept so the load-bearing parity harnesses
    constructing it with NO `federation` kwarg keep working unchanged.
- `src/lib/thinclient/retriever.py` `_seismic_backend()` → reads
  `SFU_SEISMIC_FEDERATION` (`parallel` default | `sequential`) and picks the
  concrete class directly.
- `scripts/seismic_testbed/serve_footprint_bench.py` +
  `seismic_federated.py` → `--federation {parallel,sequential}` flag (default
  parallel; `SFU_SEISMIC_FEDERATION` fallback); now pick the concrete class + the
  bench records it (class name + federation) in the result JSON.
- `scripts/tests/test_seismic_sequential.py` → guard tests; T1 verifies the
  bit-identical equivalence (single- + multi-shard) on a real `MmapSeismicIndex`;
  a cascade guard pins the no-shared-mutable-state property; a back-compat test
  pins the selector dispatch; a mechanism (B) re-fault test confirms `release_pages`
  doesn't corrupt the view.
- C2 reader (`mmap_index.rs`) → mechanism (B) `MADV_DONTNEED` is **SHIPPED**
  (`MmapSeismicIndex::release_pages`, rebuilt `.so`); mechanism (C) `mlock` /
  `MADV_RANDOM` remains a **design-only future hook** (needs the C3 split-layout
  knowledge to mlock the right slabs). (A) needed no Rust change (shipped); (B)
  shipped for the sequential class only (parallel never calls it).

**Independence guarantee (held):** the sequential class adds *no* dependency the
parallel class needs, and the parallel class is untouched — the two are never
co-active in a process. Verified: `test_served_seismic_path.py` (4/4) +
`test_seismic_sequential.py` (8/8, T1 bit-identical + cascade guard + selector)
together 12/12.
</content>
