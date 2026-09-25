# 05 · Research Sources — annotated bibliography

**Status:** DEFERRED 2026-07-16 (measured WI-1 but never promoted; parallel federation is still the served path)

**Created 2026-06-30.** The external evidence backing every design choice in this
directory. Each entry: what it is, and **which decision here it supports**. All are
`[literature]` (other corpora/hardware) — they justify *which* technique to try,
not our numbers (efficacy rule).

## Out-of-core / sequential processing (the core pattern)

- **PartitionedVC / GraphChi-style external-memory processing** —
  [arXiv:1905.04264](https://arxiv.org/pdf/1905.04264).
  Out-of-core graph systems process data **one shard/interval at a time**, loading a
  single partition into memory and relying on **sequential disk access, minimising
  random access**. → Backs the central idea (`00`, `01` mechanism A): bound RAM by
  processing shards serially.

- **GraphChi (vertex-interval shards, bounded memory)** — referenced via the
  out-of-core BFS / external-memory literature above. → Backs "use memory while
  available, fall to external storage only under pressure" — our ~1-shard-resident
  model.

## Disk-based / low-memory vector search (the RAM↔latency trade)

- **DiskANN: billion-point ANN on a single node with 64 GB + SSD** —
  [NeurIPS'19 PDF](https://suhasjs.github.io/files/diskann_neurips19.pdf) /
  [Microsoft Research](https://www.microsoft.com/en-us/research/publication/diskann-fast-accurate-billion-point-nearest-neighbor-search-on-a-single-node/).
  Keeps **compressed codes in RAM, full vectors + graph on disk, read on demand**.
  → Backs mechanism (C) in `01`: pin the small inverted+summary side, stream the
  large forward index. Also the canonical "RAM-for-latency is a legitimate, shipped
  trade" precedent.

- **Scalable Disk-Based ANN with Page-Aligned Graph** —
  [arXiv:2509.25487](https://arxiv.org/html/2509.25487v2).
  Quantifies the trade: as the in-RAM fraction shrinks, latency climbs (≈3× from a
  50%→10% memory ratio); **I/O is 70–90% of query latency** in disk-bound search.
  → Backs `00`/`04`'s honest cost statement and the "expect slower than big-RAM
  parallel" framing.

- **SPANN / LM-DiskANN / FreshDiskANN** (low-memory + streaming variants, surveyed
  alongside DiskANN). → Backs that low-memory and incremental serving over an
  immutable base index are established designs, not novel risk.

## mmap / page-fault mechanics (the resident-control tools)

- **Optimizing Memory-mapped I/O for Fast Storage (FastMap), USENIX ATC'20** —
  [PDF](https://www.usenix.org/system/files/atc20-papagiannis.pdf).
  **Sequential ≈ 3× random** access; **page faults are the dominant overhead** for
  large mmap I/O; Linux mmap scales to ~8 cores. → Backs `01` mechanism (A) (serial
  one-region access is the friendly pattern) and the diagnosis that our 76 s is a
  fault-storm, not engine time.

- **madvise(2) — `MADV_DONTNEED` / `MADV_RANDOM` / `MADV_WILLNEED`** —
  [man7](https://man7.org/linux/man-pages/man2/madvise.2.html).
  `MADV_DONTNEED` **immediately reduces RSS** for a range (re-faults from the file
  later) — the out-of-core "release between phases" primitive; `MADV_RANDOM`
  suppresses wasteful read-ahead for pointer-chasing. → Backs `01` mechanisms (B)
  and (C).

## Bounding the host (clean measurement, no swap)

- **cgroup v2 memory controller — `memory.swap.max=0`, `memory.low`** —
  [cgroup2 docs](https://facebookmicrosites.github.io/cgroup2/docs/memory-controller.html),
  [Chris Down, "In defence of swap"](https://chrisdown.name/2018/01/02/in-defence-of-swap.html).
  → Backs `04` pre-conditions: convert swap-thrash into honest page-cache misses so
  the sequential latency we measure is real.

- **vmtouch** — [hoytech.com/vmtouch](https://hoytech.com/vmtouch/).
  Report/pre-load file residency. → Backs `04` warm-pass methodology + T2/T3 RAM
  measurement in `03`.

## Build-once / serve-many (the independence justification)

- **IVF two-phase indexing (build once, query many)** —
  [IVF clustering explainer](https://mbrenndoerfer.com/writing/ivf-index-clustering-vector-search-partitioning).
  Expensive organisation happens **once offline**; every query exploits the
  precomputed structure. → Backs `02`: the shards are an immutable build; serving
  mode is a runtime choice.

- **Milvus — multiple query-execution modes over one index** —
  [SIGMOD'21 PDF](https://www.cs.purdue.edu/homes/csjgwang/pubs/SIGMOD21_Milvus.pdf).
  A production system selects among **multiple execution paths** by workload over
  the same data. → Backs the "one system, two serving methods" thesis directly.

## SEISMIC / sparse-retrieval context (the engine under all this)

- **Seismic (SIGIR'24) + scalability to 138M (ECIR'25)** —
  [arXiv:2501.11628](https://arxiv.org/pdf/2501.11628).
  Block-summary pruning; the `query_cut`/`heap_factor` dials. → Backs `01`'s
  composable free latency levers and the shared-vocabulary inner-product property
  that makes merge-by-score (hence result-equivalence) valid.

- **Latency-technique companion** —
  [`../seismic_150m_testbed/08_LATENCY_RESEARCH.md`](../seismic_150m_testbed/08_LATENCY_RESEARCH.md)
  (forward-index compression, 4-bit summary quant, int8 encoder). → The
  working-set-shrinking levers that compose with sequential serving.
</content>
