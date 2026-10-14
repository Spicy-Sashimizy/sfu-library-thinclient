# 00 · Vision & Goals — sequential SEISMIC serving

**Status:** DEFERRED 2026-07-16 (measured WI-1 but never promoted; parallel federation is still the served path)

**Created 2026-06-30, updated 2026-06-30.** Mechanisms (A) (serial branch +
`SFU_SEISMIC_FEDERATION` flag) and (B) (`MADV_DONTNEED` `release_pages`, hard
~1-shard resident guarantee) are **IMPLEMENTED** for the sequential class only
(parallel path untouched, never calls (B); the `.so` rebuild is additive; default
keeps parallel); T1 result-equivalence + the mechanism-(B) re-fault test verified
bit-identical on a synthetic shard. Mechanism (C) `mlock`/`MADV_RANDOM` and 150M
latency are still **design-only (unmeasured)**.

## The problem this solves

The parallel federation serve loads all 8 shards and searches them concurrently,
which means the **whole ~66 GB working set is touched at once**. On the 31.6 GB
host that forces the kernel to swap, and queries spend their time page-faulting
from swap, not searching (G8: ~76 s/query, swap-confounded — `[OURS]`). The RAM
**floor** is already a decisive SEISMIC win (anon ~0.14 GB index versus Qdrant ~17 GB
`[OURS]`); the problem is purely the *transient* working set under parallelism on
a small box.

## The idea

Serve the same immutable shards **sequentially**: search shard 0, then shard 1, …,
keeping only **~one shard's pages resident at any moment** and merging results by
raw score at the end. Peak resident working set drops ~8× → fits the host **with
no swap**. This is the out-of-core / external-memory pattern (process data in
bounded phases, sequential disk access, minimise random faults) — see
[`05_RESEARCH_SOURCES.md`](05_RESEARCH_SOURCES.md).

## What it buys us (and the cost)

**Buys:**
- **A demo on the hardware we already have.** No new host, no provisioning. The
  single biggest blocker to a tech demo (76 s swap-storm) is addressed by bounding
  RAM, not by buying RAM.
- **A graceful degradation story for any RAM-constrained deployment**, not just the
  demo box — the same lever scales down to smaller machines.
- **Symmetry with the proven build path.** The 150M build already runs shards
  *serially* to fit 32 GB; serving them serially is the mirror image of a strategy
  we know fits.

**Costs (honest):**
- **Latency = sum-of-shards, not max-of-shards.** Naively ~8× the per-shard search
  time. The bet is that 8 × (swap-free per-shard time) ≪ the current 76 s swap-storm
  — *plausible but unmeasured* (design-only until `04_BENCHMARKING.md` runs).
- **Not the fast path on big hardware.** On a host with RAM ≥ resident set,
  parallel federation is strictly faster. Sequential is a *small-RAM* method, not a
  *speed* method — both should exist; pick per host.

## Goals (in priority order)

1. **G-SEQ-1 — Bounded resident RAM.** Peak resident working set during a query
   stream ≤ ~1 shard + encoder (target: well under the host RAM, **VmSwap stays 0**).
2. **G-SEQ-2 — Result-equivalence.** Sequential top-k is **identical** to parallel
   top-k for the same query (merge-by-raw-score is order-independent — see
   `01_ARCHITECTURE.md`). A demo must not change answers versus the validated pipeline.
3. **G-SEQ-3 — Demo-usable latency on the current box.** p50 in a band a human demo
   tolerates (target: single-digit seconds, ideally low), **measured swap-free**.
4. **G-SEQ-4 — Clean coexistence.** Selectable by one environment flag; never co-active with
   parallel; mmap-only with no silent Path-A fallback. **Implemented as two distinct
   classes** (`ParallelSeismicBackend` for server-side, `SequentialSeismicBackend` for
   localized/RAM-efficient) sharing pure helpers, no shared mutable instance state →
   a fault in one method cannot cascade to the other's instance.

## Non-goals

- Beating parallel federation on a big-RAM host (it won't; not the point).
- Changing the index format, the build, or the query encoder.
- Resolving G6 quality (orthogonal — same shards, same results).

## Success / kill criteria

- **SUCCESS (demo-ready):** G-SEQ-1 ✓ (swap-free, bounded) AND G-SEQ-2 ✓ (== parallel
  results) AND G-SEQ-3 ✓ (demo-usable p50 measured on the 31.6 GB box).
- **KILL (sequential not worth it):** even swap-free, 8 × per-shard time is still
  not demo-usable AND the `query_cut`/`heap_factor` + mlock-small-side levers
  (`01_ARCHITECTURE.md`) can't bring it into band → conclude the demo needs the
  provisioned-RAM parallel path after all, and document that cleanly.

The kill criterion is an acceptable, documented landing — the whole reason to
measure sequential cheaply is to find out *before* spending on hardware.
</content>
