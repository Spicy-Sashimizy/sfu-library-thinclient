# 05 · Risk Register

**Status:** ACTIVE

Each risk lists the **cheapest experiment that retires it** and the **gate** that
catches it. Ordered by kill-probability × cost.

| # | Risk | Likelihood | Impact | Cheapest retiring experiment | Gate |
|---|---|---|---|---|---|
| **R-RAM** | **SEISMIC standalone is RAM-resident** — no mmap, so ~133 GB @150M, repeating BMP's row-4 disease | **High (confirmed for FOSS impl, gate-zero)** | **Kill Path A** | P2: measure RssAnon/doc on the persona index; extrapolate. Already *known* RAM-resident — this quantifies how bad | G3 |
| **R-PRUNE** | **Pruning doesn't transfer to our queries** — paper used MS MARCO; our 64-term SFU SPLADE queries may defeat the summary-vector skip (BMP's WAND did) | **Med** | **Kill (SEISMIC offers nothing BMP didn't)** | P2: candidates_scored/corpus on 0.93M vs 2.0M shards — the *exact* probe BMP failed | **G4 (the decisive gate)** |
| **R-QUAL** | SEISMIC's approximation drops the papers we validated → quality regression | Low–Med | Kill | P1/P3: overlap@10 vs Qdrant + RRF NDCG@10 ±0.005 on the same vectors | G2/G6 |
| **R-OWN** | **Path C is a maintenance trap** — a SEISMIC fork + Lance writer + per-arch wheels to own forever, for a research codebase | **High** | **Strategic** | P5: cost Path C vs the value of no-JVM over OpenSearch+SEISMIC (Path B, zero new code); decide explicitly | G9 |
| **R-BUILD150M** | 150M SEISMIC build OOMs on any host we can justify (build peak unknown; Qdrant-150M already OOMs the 31.6 GB box) | Med | Major | P4: measure persona build-peak RAM, project to 150M *before* committing a host | G7 |
| **R-PARAM** | Param tuning (λ/block/query-cut) trades recall for the latency/RAM numbers — easy to report a flattering point | Med | Correctness of the result | P1: lock params to **match Qdrant recall@k first**, then read latency/RAM — never tune for the number you want | G2 |
| **R-WHEELS** | Source-only `pyseismic-lsr` wheels → per-arch build (linux x86_64/aarch64, mac arm64), the original BMP packaging gap | Med | Cost | P5: maturin CI for the 3 arches (only if Path A/C wins) | G9 |
| **R-OBSOLETE** | The FOSS gap closes upstream mid-build — SEISMIC ships its own on-disk mode (ECIR-2025 line) and Path C becomes wasted work | Med | Strategic | pre-P5: re-check the repo for mmap/on-disk before building Path C; prefer contributing upstream over forking | (pre-P5) |

## The risks that actually decide it

- **R-PRUNE (G4)** is the whole bet. If SEISMIC's pruning is sub-linear on *our*
  queries, SEISMIC is fundamentally better than BMP and worth the work. If it's
  linear (like BMP), **stop** — there's no engine here. Retired on persona shards,
  here, for the cost of one instrumented run.
- **R-RAM (G3) + R-OWN (G9)** together decide *which* path: if standalone RAM is
  curable cheaply or Path C is worth owning → no-JVM win; else → **OpenSearch+SEISMIC**
  (accept the JVM) is the honest landing.

## Cheapest path to a confident kill-or-go

P0 (done) → instrument-and-measure **G4 (pruning)** and **G2 (quality)** on the
existing persona shards. Two runs. If G4 is linear → killed in a day, no 150M host,
no fork. If G4 is sub-linear and G2 holds → you've earned the right to spend a 150M
host and the build-vs-buy analysis.
