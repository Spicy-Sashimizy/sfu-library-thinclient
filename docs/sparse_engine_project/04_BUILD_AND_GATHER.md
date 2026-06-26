# 04 · What to Build and Gather

> **CLOSED — line MEASURED & STOPPED 2026-06-26.** Written while the mmap-BMP /
> `immsparse` engine was a live option. At the 150M target scale the bespoke engine
> loses to FOSS (pruning linear in corpus; inverted-side RAM ~7.6× the Qdrant floor).
> Historical design context only — current verdict in `README.md` + `07_INTEGRATION_PLAN.md` §8.

## Already have (in this container — verified 2026-06-25)
| Asset | Where | Use |
|---|---|---|
| Rust toolchain | `cargo 1.96`, `rustc` | build the BMP fork |
| Stock BMP + builder | `.venv` `bmp`, `src/lib/thinclient/builder.py` | baseline + build test `.bmp` |
| Test `.bmp` shards | `data/thinclient_1m/sections/*/splade_000.bmp` (≤114 MB) | P1 correctness |
| Bigger build input | `data/thinclient_index/spool_backup` (123 GB, 5 sections) | P2 persona-sized `.bmp` |
| Live Qdrant baseline | `splade_150m`, `splade_par30` | P2/P4 head-to-head |
| Measure + parity harness | `scripts/spike_qdrant_sparse.py`, `eval_thinclient_parity.py`, `eval_quant_fidelity.py` | G3/G4/G5 |
| Query encoder | `lib.opensearch_retriever.encode_splade` + `models/splade_onnx_fp16` | qvecs |
| Serving constants | QUANT_SCALE=70, α=0.8, β=1.0, k-overfetch | identical-compute guarantee |
| Spike scaffold | `spike/mmap_bmp/` | P0–P2 |

## Need to create
| Item | Phase | Notes |
|---|---|---|
| `maturin` in a throwaway venv | P1 | `pip install maturin`; NOT the serving `.venv` |
| **BMP fork** (`memmap2`, zero-copy views) | P1 | the core change — `FORK_BMP.md` |
| Persona-sized `.bmp` (e.g. med_bio ~17M or social_sciences__recent ~26M) | P2 | from `spool_backup` via `builder.py`; must exceed page-cache to test cold |
| Cold-cache harness | P2 | `drop_caches` (sudo) + the existing measure cadence |
| `immsparse` library wrapper | P3 | mmap loader + `Searcher` API surface compatible with retriever |
| `SFU_SPLADE_BACKEND=immsparse` branch in `retriever.py` | P3 | drop-in next to `qdrant`/`bmp` |
| Per-arch wheel CI (maturin) | P5 | linux x86_64 + arm64 + mac arm64 (the old BMP wheel gap) |
| (opt) Lance sparse-column writer/reader | P5 | Option B unification |

## Need to gather / decide (external)
| Item | Phase | Notes |
|---|---|---|
| BMP licence posture (Apache-2.0) for a maintained fork | pre-P3 | confirm fork/redistribution terms |
| Memmap on target deploy FS (NVMe assumed) | P2/P4 | cold p95 is NVMe-dependent; SATA tails worse |
| Decision: standalone (A) vs Lance-unified (B) | P3 | A proves the cure; B adds unification at cost |
| Host for P4 150M (≥64–128 GB to page-cache enough of the index) | P4 | per `DO_SIZING.md` |
| Spin-off repo + container | post-P2 | only after the cure is proven |

## "Definition of ready" to start each phase
- **P1:** throwaway venv + maturin + BMP cloned; P0 baseline.json present.
- **P2:** P1 green; a `.bmp` larger than page cache built; sudo for `drop_caches`.
- **P3:** P1+P2 green; spin-off repo created.
- **P4:** P3 green; 64–128 GB host; full SPLADE `sparse_field` (in `spool_backup`).
- **P5:** P4 green; CI runners per arch.
</content>
