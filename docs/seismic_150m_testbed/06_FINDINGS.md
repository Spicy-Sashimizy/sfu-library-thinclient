# 06 · Findings — running results ledger

"Measured, not flagged. Numbers, not adjectives." Each row: absolute date, gate,
value, verdict, eval script + result file. Unmeasured claims are marked `est.`

## Decision log

| Date | Gate | Value | Verdict | Note / evidence |
|---|---|---|---|---|
| 2026-06-26 | **GZ** (algorithm prunes at scale) | SEISMIC validated on **138M passages, MS MARCO v2** (ECIR 2025) | ✅ **PASS** | The pruning that BMP lacked is validated at ≈ our target scale. Source: [arXiv:2501.11628](https://arxiv.org/abs/2501.11628) "Investigating the Scalability of Approximate Sparse Retrieval Algorithms to Massive Datasets" (Bruch, Nardini, Rulli, Venturini, Venuta). Mechanism (cross-ref 2026-06-26): SEISMIC = "Spilled Clustering of Inverted Lists with Summaries" — geometrically-cohesive **blocks + per-block summary-vector ("sketch") skipping + static per-posting-list pruning** (top-entries, "concentration of importance") + forward index for in-block scoring, coordinate-at-a-time traversal. Source: [arXiv:2404.18812](https://arxiv.org/abs/2404.18812) (SIGIR 2024). **Caveat:** the RAM/latency tables at 138M did not decode in the PDF fetch — pull them before setting G8 expectations (`04_BUILD_AND_GATHER.md`). |
| 2026-06-26 | **GZ** (no-JVM / embeddable) | pure-Rust, **MIT**, `cargo add seismic` + `pyseismic-lsr` Python bindings | ✅ **PASS** | Clears the two gates OpenSearch+SEISMIC fails (no-JVM, embeddable). Source: [github.com/TusKANNy/seismic](https://github.com/TusKANNy/seismic) README (fetched 2026-06-26). |
| 2026-06-26 | **GZ** (RAM cure out-of-box) | **No mmap / on-disk / out-of-core mode** in the FOSS repo as of 2026-06-26; index is RAM-resident | ⚠️ **OPEN RISK (R-RAM)** | The reference impl loads forward+inverted into RAM — same class as BMP (retired at 211 GB) and the prior `STACK_COST_MATRIX` row ("Seismic standalone … RAM-resident … ~8 GB/9M → not viable @150M"). The paper's own future-work names "retrieval where indexes cannot fit in main memory" → confirms it's an open direction, not shipped. **This is why the testbed exists rather than just wiring up the crate.** Source: repo README + `docs/qdrant_vs_lucene_assessment/STACK_COST_MATRIX.md`. |
| 2026-06-26 | (context, Path C substrate) | **Lance is over-engineered for sparse-only Path C; thinner mmap wins** | — | Once the substrate's job = "immutable mmap container of fixed-width blobs SEISMIC reads zero-decode," most of Lance is unused and its encoding layer is a hazard. Ranked alternatives (cross-ref 2026-06-26): **raw `memmap2`+`bytemuck` flat files = top pick, already validated by this project's own FORMAT-WALL flip** (696→25.63 ms, `sparse_engine_project` G1 zero-decode / `R3v2_delta.patch`); **`redb`** pure-Rust zero-copy mmap KV ([redb.org](https://www.redb.org/post/2023/06/16/1-0-stable-release/)) if keyed access wanted; **Arrow IPC/Feather v2 uncompressed** zero-copy "except when compression enabled" ([Arrow IPC](https://arrow.apache.org/docs/cpp/ipc.html)); term dict = mmap'd [`fst` crate](https://crates.io/crates/fst). Lance only wins if dense unification becomes a goal (non-goal here). Substrate is a P5 decision downstream of G4/G3. See `01_ARCHITECTURE.md` Path C. |
| 2026-06-26 | (context, Path C substrate) | **Lance is purpose-built for random access** (adaptive structural encodings by data width), with a near-zero-copy path for fixed-width data | — | Refines the Path C format-wall risk: the substrate fits SEISMIC's random-pointer-chasing access *better* than the BMP-era framing assumed — but "fast random access ≠ zero-decode." The zero-copy path exists in Lance and is reachable by pinning SEISMIC's hot structures to the fixed-width/transparent encoding (not compressed columns). Make-or-break is a layout constraint, measured, not assumed. Source: [arXiv:2504.15247](https://arxiv.org/abs/2504.15247) "Lance: Efficient Random Access in Columnar Storage through Adaptive Structural Encodings." See `01_ARCHITECTURE.md` Path C. |
| 2026-06-26 | (context) | **Qdrant-150M OOMs on the 31.6 GB host** during optimization (projected force-optimize peak ~38 GB > 31.6 GB; resting RssAnon 17.4 GB, MemAvailable 8.8 GB; historical `os error 12` Jun 19–20) | — | The forcing function: the present engine cannot serve 150M-single-collection on the hardware we have. Per `sparse_engine_project/07_INTEGRATION_PLAN.md` §8 this triggers the SEISMIC pivot. Source: live probe + `docs/bmp_decommission_plan/DO_SIZING.md` (150M needs ≥64 GB). |

> Pre-registration note (retained for traceability): until G4 and G2 were
> measured, no claim that "SEISMIC works for us" was permitted — gate-zero only
> established SEISMIC as the *right thing to test*. The 138M paper result was on
> MS MARCO queries; our 64-term SFU queries were the open question. G4/G2/G3 now
> measured below.

---

## P1/P2 measured results (2026-06-26 — the session that ran the three deciding gates)

The three gates `02` says "decide everything," measured on the existing 31.6 GB
host with no 150M dependency. Per `03_BENCHMARK_METHODOLOGY.md`: measured values
+ eval-script + result-file paths.

| Gate | Value (MEASURED 2026-06-26) | Verdict | Eval script → result file |
|---|---|---|---|
| **G1 Build** | 2M med_bio SEISMIC index builds from stored `sparse_field` (no re-encode) in 187s; peak RSS 2.81 GB; on-disk 1.69 GB; 27,896 vocab (standard variant, <65K). | ✅ **PASS** | `scripts/seismic_testbed/build_persona_seismic.py` → `data/eval_results/seismic_build_persona_2m.json` (+ `seismic_build_persona_929k.json`) |
| **G4 Pruning** | `candidates_scored/corpus` (instrumented `search_with_stats` = `visited.len()`) **FALLS** as corpus grows: worst-query ratio **0.0198 → 0.0092** across a 2.15× corpus jump (0.93M → 2.0M med_bio, same 34 queries). Both ratios <2%; BMP's was ~0.95 stable. | ✅ **PASS (sub-linear)** | `scripts/seismic_testbed/measure_seismic_pruning.py` (instrumented fork, `spike/seismic_testbed_instrumented/README.md`) → `data/eval_results/seismic_pruning_persona.json` |
| **G3 RAM (Path A)** | RAM-resident: RssAnon delta after load ≈ 100% of index Total bytes (RssFile ≈ 0). 2.0M → **912 B/doc → 150M proj 137 GB**; 0.93M → 1323 B/doc → 199 GB (per-doc rate falls as corpus grows). Both ≫ Qdrant's 43 B/doc (6.55 GB @150M). | ❌ **FAIL** (Path A RAM-NO-GO, as gate-zero predicted) | `scripts/seismic_testbed/measure_seismic_ram.py` → `data/eval_results/seismic_ram_floor_persona_2m.json` (+ `_929k`) |
| **G2 Quality** | overlap@10 vs Qdrant (scoped to the SAME 2M med_bio oaids, 500k-deep over-fetch) = **0.479** (<0.95 bar). NDCG@10 common-judged = 1/34 (judge-cache-limited to the med_bio subset → under-powered, NOT a pass). R-PARAM separated: overlap stable 0.517 across `heap_factor ∈ {0.8, 0.5, 0.0}` → NOT query-time heap prune; static **index-time** pruning (n_postings/max_fraction) + summary approximation. | ❌ **FAIL** (overlap), NDCG inconclusive | `scripts/seismic_testbed/eval_seismic_parity.py` → `data/eval_results/seismic_parity_persona_2m.json` (+ `seismic_parity_heapfactor_sweep.json`) |

**Plain reading:** The decisive gate (G4) is GREEN — SEISMIC prunes where BMP
couldn't; the pivot is validated as the right thing. But Path A is confirmed
RAM-resident (G3, exactly as the gate-zero R-RAM risk predicted) and diverges
from exact Qdrant at default configs (G2 — likely recoverable via index-time
pruning shrink + rebuild, OPEN not proven-impossible). The no-JVM + RAM-cured
goal therefore hangs entirely on **Path C** (mmap substrate). The G3
forward-vs-inverted split (2M: forward 628 MB / inverted+summary 1.03 GB = 62%)
means Path C must **mmap the WHOLE index**, not forward-only — the cheap option
`01_ARCHITECTURE.md` flagged is ruled out; this feeds the G9 build-vs-buy cost.

## Open gates (next measurements, in priority order)

1. **G2 follow-up — index-time param sweep** (reclaim the 0.95 overlap):
   rebuild the persona index with `n_postings` ↑ and `max_fraction` ↑ (less
   static pruning) and re-run `eval_seismic_parity.py`. Green → G2 flips;
   red even at minimal pruning → SEISMIC's approximation is the ceiling.
   Cheapest next run: one rebuild + the existing harness.
2. **G5 latency at persona**: the G4 run already recorded per-query ms (sub-ms
   warm); formalize vs the Qdrant persona 66 ms ref.
3. **G6 RRF parity** (P3): behind G2 — a divergent leg won't fuse cleanly.

> G4 + G3 measured. G4 (the decisive gate) is GREEN; G3 is as pre-registered
> (R-RAM); G2 fails at default configs. No 150M host spent; no Path-C build
> started.

## Current one-line status

**P0 ✓ (gate-zero). P1 ✓ (G1 PASS). P2: G4 ✓ PASS (decisive), G3 ✗ FAIL as
predicted (R-RAM), G2 ✗ FAIL (static-pruning; likely tunable).** SEISMIC prunes
where BMP couldn't — the pivot is validated. Path A is RAM-resident, so the
no-JVM RAM-cured goal routes entirely to Path C (mmap the whole index, per the
G3 split). Cheapest next step: the G2 index-time param sweep to test whether
default-pruning is the ceiling or just too aggressive.
