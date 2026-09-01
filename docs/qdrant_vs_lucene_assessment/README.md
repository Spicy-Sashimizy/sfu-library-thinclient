# Qdrant vs Lucene/OpenSearch — Sparse-Leg Assessment (2026-06-25)

> **Status note 2026-09-01:** this assessment predates the SEISMIC promotion —
> since 2026-07-06 the served SPLADE backend is SEISMIC federated mmap
> (`docs/SEISMIC_ARCHIVE_SPLIT.md`), with Qdrant as the env-gated rollback
> slated for the archival container. The RAM analysis and OOM findings below
> remain the recorded evidence base for that move.

Commissioned question (paraphrased): *given the sparse-vector storage/calling
issues we keep hitting with Qdrant at 150M, would swapping off Qdrant — e.g. back
to OpenSearch/Lucene — provide any benefit? Direct Qdrant-vs-Lucene RAM
comparison (active + passive), a plan to actually benchmark Qdrant at 150M, and:
were the past Qdrant OOMs ever fixed?*

This directory collects the findings. Every number is **measured** unless marked
`est.`, and every claim cites the source file it came from. It is a synthesis of
the live container state (probed 2026-06-25), git history, and the canonical docs
(`docs/THIN_CLIENT_SWAP.md`, `docs/STORAGE_BUDGET_150M.md`,
`docs/THIN_CLIENT_STACK_RESEARCH.md`, `docs/bmp_decommission_plan/`).

## Files

| File | What it answers |
|---|---|
| `FINDINGS.md` | The full answer to all six questions, with the measured numbers + citations and a recommendation per deployment tier. |
| `QDRANT_VS_LUCENE_RAM.md` | The direct active/passive RAM comparison table (the structural anon-vs-page-cache difference that is the whole story). |
| `QDRANT_150M_BENCHMARK_PLAN.md` | Concrete, runnable plan to benchmark Qdrant at 150M **on a correctly-sized host** (the gap that remains) + a matched head-to-head vs OpenSearch. |

## 30-second answer

- **The OOMs are fixed at the operational layer, structural at the host layer.**
  The optimizer-OOM (`os error 12` on segment merge) was fixed by a persisted
  collection PATCH (`max_optimization_threads=1`, `max_segment_size=5_000_000`) —
  **zero OOM since, verified live 2026-06-25** (`optimizer_status: ok`, 36 stable
  segments, `VmSwap: 0`). The server-OOM crash was made auto-recovering with a
  serve-only supervisor. What is **not** "fixed" is the underlying ceiling: at
  150M the index is **205 GB on disk vs 23 GB host RAM**, so it is RAM-bound by
  physics, not by a bug. That is closed only by **right-sizing the host**, not a
  config flag.
- **Swapping back to OpenSearch/Lucene would help on exactly ONE axis — sparse
  RAM at scale — and lose on the axes the whole project swapped away from it
  for.** Lucene serves SPLADE as mmap'd `rank_features` postings under a bounded
  2 GB heap with **no per-point resident overhead**; Qdrant `on_disk` carries a
  **structural ~43 B/point anonymous RAM** floor (6.55 GB at 150M) that page
  cache can't reclaim. But OpenSearch measured **−0.111 NDCG@10 worse** than this
  stack (it loses 29/34 queries) and reintroduces the JVM/cluster floor that
  disqualified it for the laptop/thin-client tier.
- **Net recommendation: keep Qdrant, but size the host to the tier.** Qdrant is
  the right call for the no-JVM thin-client/demo tier (30M: p50 ~66 ms, 1.44 GB
  resident). For a *full-150M server*, the honest options are (a) a 64–128 GB
  Qdrant box, or (b) the path the original research already flagged as
  recommendation #1 — stay on OpenSearch 3.x for the server tier. The current
  24 GB dev host is simply undersized for 150M on *either* engine.

See `FINDINGS.md` for the reasoning and the per-tier breakdown.
</content>
</invoke>
