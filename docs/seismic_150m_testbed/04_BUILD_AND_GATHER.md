# 04 · What to Build and Gather

## Already have (in this container)

| Asset | Where | Use |
|---|---|---|
| Rust toolchain | `cargo 1.96`, `rustc` | build `seismic` crate / Path C |
| Stored SPLADE vectors | `data/thinclient_index/spool_backup` (123 GB, sparse_field) | feed SEISMIC with NO re-encode |
| Persona shards (med_bio) | built in the prior spike (`data/thinclient_*`) | P1–P3 persona scale |
| Live Qdrant baseline | `splade_150m`, `splade_par30` collections | G2/G3/G8 head-to-head |
| Parity + measure harness | `scripts/eval_thinclient_parity.py`, `benchmark_llm_judge.py`, `spike/archive/mmap_bmp/measure_p2_cold.py`, `measure_p3b_pruning.py` | G2/G4/G5/G6 (reuse/adapt) |
| Query encoder | `lib.opensearch_retriever.encode_splade` + `models/splade_onnx_fp16` | qvecs |
| Serving constants | `QUANT_SCALE=70`, α=0.8, β=1.0 | identical-compute guarantee |
| RAM probes | RssAnon/`smaps_rollup` pattern + Qdrant `/metrics` jemalloc (added in `measure_qdrant_floor.py`) | G3/G8 |

## Need to create

| Item | Phase | Notes |
|---|---|---|
| Throwaway venv + `pyseismic-lsr` | P1 | `pip install pyseismic-lsr` — **NOT** the serving `.venv` (source-only wheels; needs Rust toolchain to build) |
| Persona SEISMIC index builder | P1 | read `spool_backup` sparse_field → SEISMIC `index()`; param-match Qdrant recall@k |
| `SFU_SPLADE_BACKEND=seismic` shim | P1 | drop-in next to `qdrant`/`bmp` in the retriever — Path A |
| RAM-floor probe for SEISMIC | P2 | RssAnon + jemalloc-ctl before/after load; per-doc normalization |
| Pruning probe | P2 | instrument SEISMIC traversal for candidates_scored/query on the 0.93M vs 2.0M shards |
| (if P1/P2 green) 150M build harness | P4 | build full index; watch `MemAvailable` for OOM; record on-disk size |
| (only if Path C) mmap forward/inverted store | P5 | SEISMIC blocks+summaries on an immutable mmap substrate read zero-decode — **default raw `memmap2`+`bytemuck` / `redb`** (the proven path; not tantivy; Lance only if dense unification becomes a goal). Term dict = mmap'd `fst`. The build; gate behind G9. See `01_ARCHITECTURE.md` Path C substrate table |
| (Path B control) OpenSearch+SEISMIC re-index | P2/P4 | the JVM fallback baseline to beat on the ownership math |

## Need to gather / decide (external)

| Item | Phase | Notes |
|---|---|---|
| SEISMIC param map (λ, n-postings, block size, query-cut) → Qdrant-recall parity | P1 | match recall *first*, read latency *after* |
| 150M host (≥64 GB for Qdrant baseline; SEISMIC build peak TBD) | P4 | the 31.6 GB host **cannot** hold Qdrant-150M (OOMs) — Path A/C build-peak must be measured before committing a host |
| ECIR-2025 results tables (RAM/latency @138M) | P0/P4 | `arXiv:2501.11628` PDF didn't decode in fetch — pull the tables to set the G8 expectation |
| SEISMIC on-disk/mmap status re-check before P5 | pre-P5 | the FOSS gap may close upstream; re-verify the repo before building Path C |

## "Definition of ready" per phase

- **P0:** gate-zero recorded (done). 
- **P1:** throwaway venv + `pyseismic-lsr` built; persona sparse_field accessible.
- **P2:** P1 green (G1/G2); pruning + RAM probes wired.
- **P3:** P2 green (G3/G4); LLM-judge harness pointed at the SEISMIC backend.
- **P4:** P3 green (G6); a ≥64 GB host secured; SEISMIC build-peak RAM measured at
  persona to project the 150M peak before committing the host.
- **P5:** P4 green; the build-vs-buy numbers (Path C cost vs Path B value) in hand.
