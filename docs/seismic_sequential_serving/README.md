# SEISMIC Sequential Serving — one index, a second serving method

**Created 2026-06-30.** Status: **IMPLEMENTED (mechanisms A + B) — two distinct
classes, EFFICACY UNMEASURED**. The two methods are separate classes —
`ParallelSeismicBackend` (server-side) and `SequentialSeismicBackend` (localized,
RAM-efficient) — sharing pure module-level helpers, with no inheritance coupling
of per-query behavior and no shared mutable instance state (lowest cascade risk;
a parallel thread bug can't reach a sequential instance). `SFU_SEISMIC_FEDERATION`
picks the class (default `parallel`). T1 result-equivalence verified bit-identical
on a synthetic shard. Mechanism (A) serial loop + mechanism (B) `MADV_DONTNEED`
`release_pages` (after each shard's search → hard ~1-shard resident guarantee) are
**both shipped** for the sequential class only (parallel never calls (B); the `.so`
rebuild is additive). Mechanism (C) `mlock`/`MADV_RANDOM` remains a **design-only
future hook**. Latency on the real 150M box is **unmeasured** — run
`04_BENCHMARKING.md`. Owner: TBD.

## The one-sentence idea

The 150M SEISMIC index is already built as **8 immutable mmap shards** (G7 +
C2.5). Today they are served **in parallel** (all shards live at once, one thread
each — `sharded_seismic_backend.py:190`). This directory documents a **second,
independent serving method** for the *same* shards: **sequential federation** —
search the shards **one at a time**, keeping only ~one shard's pages resident.

> **Build once, serve two ways.** Nothing about the index changes. The shards are
> immutable artifacts; "parallel" and "sequential" are two runtime strategies that
> read them. This directory is deliberately self-contained so the sequential track
> can be built, tested, and benchmarked **without entangling** the parallel
> federation work in `seismic_150m_testbed/`.

## Why a second method exists (the motivation)

The parallel method needs the **whole working set resident at once** (~66 GB), so
on the 31.6 GB host it swap-thrashes → ~76 s/query (the G8 swap-confounded
result). Sequential federation trades peak parallelism for a **bounded resident
working set (~1 shard)**, which fits the host **without swap** — the most
promising way to get a usable tech demo on the hardware we already have, no new
box required. The cost is latency-as-a-sum-of-shards instead of max-of-shards;
whether that still beats the 76 s swap-storm is the open measurement.

This is a textbook out-of-core pattern (GraphChi-style one-shard-at-a-time;
DiskANN/SPANN RAM-for-I/O trade) — see [`05_RESEARCH_SOURCES.md`](05_RESEARCH_SOURCES.md).

## Relationship to the parallel path (kept separate on purpose)

| | Parallel federation (existing) | Sequential federation (this dir) |
|---|---|---|
| Lives in | `docs/seismic_150m_testbed/`, `sharded_seismic_backend.py` (ThreadPoolExecutor) | this dir; a new serve-mode branch, env-gated, no change to parallel code |
| Resident RAM | all shards (~66 GB working set) | ~1 shard at a time |
| Latency | ≈ slowest single shard (max) | ≈ sum of shards |
| Best on | a host with RAM ≥ resident set | a small/RAM-constrained host (the demo case) |
| Index artifacts | the 8 C2 mmap shards | **the same 8 C2 mmap shards** |

The two methods are mutually exclusive at runtime (one env flag), never co-active,
and **share zero build state** beyond the immutable shards — so neither can
destabilise the other.

## Documents

| Doc | What |
|---|---|
| [`00_VISION_AND_GOALS.md`](00_VISION_AND_GOALS.md) | Why sequential, what it buys, goals/non-goals, success + kill criteria |
| [`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) | How sequential federation works; the resident-bounding mechanisms; result-equivalence with parallel; code touch-points |
| [`02_BUILD.md`](02_BUILD.md) | **Independent** build/artifact documentation — what sequential needs (same immutable shards), self-contained, no parallel-path dependency |
| [`03_TESTING.md`](03_TESTING.md) | **Independent** test plan — correctness (== parallel), RAM-bound + swap-free assertions, no-silent-fallback, degrade contract |
| [`04_BENCHMARKING.md`](04_BENCHMARKING.md) | Methodology to measure sequential vs parallel head-to-head on the current box |
| [`05_RESEARCH_SOURCES.md`](05_RESEARCH_SOURCES.md) | Annotated bibliography of the online sources backing every design choice here |

## Efficacy-rule note (binding, per root CLAUDE.md)

Everything in this directory is **design + external-literature** until *we* measure
it on *our* shards. External numbers are tagged `[literature]`; our own numbers are
tagged `[OURS]`. No "should be faster" without numbers — unmeasured claims are
marked "design-only / unmeasured." Cross-engine latency context lives in
[`../seismic_150m_testbed/08_LATENCY_RESEARCH.md`](../seismic_150m_testbed/08_LATENCY_RESEARCH.md).
</content>
