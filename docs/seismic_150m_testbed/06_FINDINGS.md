# 06 · Findings — running results ledger

"Measured, not flagged. Numbers, not adjectives." Each row: absolute date, gate,
value, verdict, eval script + result file. Unmeasured claims are marked `est.`

## Decision log

| Date | Gate | Value | Verdict | Note / evidence |
|---|---|---|---|---|
| 2026-06-27 | **G2 follow-up** (param sweep) | overlap@10 frozen at **0.479** across P0/P1/P3: `max_fraction` 1.5→5.0→10.0, `doc_cut` 15→1, `summary_energy` 0.4→0.9 (index 1.69→5.28 GB, peak RSS 2.83→7.92 GB). Per-query overlap **bit-identical** across configs. | ❌ **FAIL (not tunable on named levers)** | The 06 hypothesis ("likely recoverable via index-time pruning shrink") is **falsified**. The lever `max_fraction` is proven inert: 2× more retained docs/list changes zero top-10 results (the pruning tail ranks below top-10). Two escapes remain: untested `n_postings`/`centroid_fraction`, and the looser G6 RRF system-level gate. Eval `scripts/seismic_testbed/g2_param_sweep.py` → `data/eval_results/seismic_g2_param_sweep.json`. See §"G2 param-sweep" below. |
| 2026-06-27 | **G2 follow-up #2** (`n_postings` sweep) | overlap@10 frozen at **0.479** across P0/N1/N3: `n_postings` 3500→7000→14000 (index 1.69→2.91 GB, peak RSS 2.83→7.35 GB, avg list 5485→...→2808 post-prune). Per-query overlap **bit-identical** (every one of 34 queries unchanged; programmatic check N1==P0 AND N3==P0). | ❌ **FAIL (server-side pruning is NOT the gap)** | N3 saturates the **global** selection (budget 390.5M > 153M total postings `idx.nnz` → every posting selected); only the per-list cap (21,000) still clips the hottest lists, and the `max_fraction` sweep already proved that cap is irrelevant to top-10. So 0.479 is the **query-time approximation floor** (summary-skip + in-block coordinate traversal), not a posting-retention gap — **no index knob reclaims it**. The "untested `n_postings`" escape (G2 follow-up #1) is **closed**. Only `centroid_fraction` and the **G6 RRF** system-level gate remain. Eval `scripts/seismic_testbed/g2_param_sweep.py --lever n_postings` → `data/eval_results/seismic_g2_npostings_sweep.json`. See §"G2 n_postings sweep" below. |
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
| **G2 Quality** | overlap@10 vs Qdrant (scoped to the SAME 2M med_bio oaids, 500k-deep over-fetch) = **0.479** (<0.95 bar). NDCG@10 common-judged = 1/34 (judge-cache-limited to the med_bio subset → under-powered, NOT a pass). R-PARAM separated: overlap stable 0.517 across `heap_factor ∈ {0.8, 0.5, 0.0}` → NOT query-time heap prune; static **index-time** pruning (n_postings/max_fraction) + summary approximation. — **Both pruning levers proven inert 2026-06-27** (sweeps #1 `max_fraction`/`doc_cut`/`summary_energy` + #2 `n_postings` to the selection-saturated ceiling): overlap frozen at 0.479, per-query **bit-identical** → the gap is the query-time approximation floor, not posting retention. | ❌ **FAIL** (overlap), NDCG inconclusive | `scripts/seismic_testbed/eval_seismic_parity.py` → `data/eval_results/seismic_parity_persona_2m.json` (+ `seismic_parity_heapfactor_sweep.json`); sweeps → `seismic_g2_param_sweep.json` + `seismic_g2_npostings_sweep.json` (`g2_param_sweep.py --lever {max_fraction,n_postings}`) |

**Plain reading:** The decisive gate (G4) is GREEN — SEISMIC prunes where BMP
couldn't; the pivot is validated as the right thing. But Path A is confirmed
RAM-resident (G3, exactly as the gate-zero R-RAM risk predicted) and diverges
from exact Qdrant at default configs (G2 — ~*likely recoverable via index-time
pruning shrink + rebuild, OPEN not proven-impossible*~, per the 2026-06-26
reading; **SUPERSEDED 2026-06-27** — the param sweeps below tested exactly this
across BOTH lever axes and both are INERT (overlap frozen at 0.479,
per-query bit-identical, including the `n_postings` selection-saturated
ceiling); the 0.479 gap is the query-time approximation floor, not a posting-
retention gap — only `centroid_fraction` (clustering density) + the looser G6
remain). The no-JVM + RAM-cured
goal therefore hangs entirely on **Path C** (mmap substrate). The G3
forward-vs-inverted split (2M: forward 628 MB / inverted+summary 1.03 GB = 62%)
means Path C must **mmap the WHOLE index**, not forward-only — the cheap option
`01_ARCHITECTURE.md` flagged is ruled out; this feeds the G9 build-vs-buy cost.

## G2 param-sweep (2026-06-27 — quality ceiling test, MEASURED)

The G2 FAIL follow-up the open-gates list named: rebuild the 2M persona index
with swept index-time params and re-run parity. The 06 diagnosis was **static
index-time pruning** (`max_fraction`), NOT query-time heap; the C2 floor cure
(07 §4.4) unblocked the §5 tension (bigger-index-for-quality no longer
threatens RAM), so the sweep ran ungated.

Ran: `scripts/seismic_testbed/g2_param_sweep.py` (Qdrant-memoized — the Qdrant
top-10 per paraphrase is reused from the baseline `seismic_parity_persona_2m.json`
across configs, since Qdrant is constant across builds; turns each point from
~8.5 min live-fetch into ~4 min build + 34 SEISMIC-only searches).
→ `data/eval_results/seismic_g2_param_sweep.json`

Lever semantics (inverted_index.rs:401-434 `global_threshold_pruning`): the
`n_postings*dim` largest postings are selected GLOBALLY, then each inverted
list is capped at `n_postings * max_fraction` docs. Default cap = 3500×1.5 =
5,250 docs/list. `doc_cut` = per-block document-approximation threshold;
`summary_energy` (α) = summary energy retention.

**Grid (3 configs, the minimal decisive sweep):**

| config | max_fraction | doc_cut | summary_energy | on-disk | peak RSS | overlap@10 |
|---|---|---|---|---|---|---|
| **P0 baseline** (anchor) | 1.5 | 15 | 0.4 | 1.69 GB | 2.83 GB | **0.479** |
| P1 mf5.0 (single lever) | 5.0 | 15 | 0.4 | 2.34 GB | 5.47 GB | **0.479** |
| P3 ceiling (all levers) | 10.0 | 1 | 0.9 | 5.28 GB | 7.92 GB | **0.479** |

**VERDICT: `G2 CEILING` — 0.479 overlap@10 is invariant across a 3× index-size
range (1.69→5.28 GB) and the full pruning/approx knob family tested.**

The named lever (`max_fraction`) is **proven inert**: P1 retains 2× more docs
per posting list (avg list length 1231→2080) yet changes **zero** top-10
results — the extra retained postings all rank below the top-10 cutoff, so the
pruning tail never surfaces in results. P3 (max_fraction 10.0 + doc_cut→1
exact in-block + summary_energy→0.9 bigger summaries, 7.9 GB peak) moves the
number by exactly 0.000. Per-query overlap is **bit-identical** P0==P1==P3
(not just the mean — every one of the 34 queries, e.g. 0.4/0.7/0.6/0.5/0.5/0.4
unchanged across configs). The harness is faithful: P0 reproduces the
baseline 0.4794 exactly (anchor check, the Qdrant cache keyed by paraphrase).

**What this does NOT settle (after the `n_postings` sweep closed escape #1):**
1. ~~**Untested levers — `n_postings`**~~ — **CLOSED 2026-06-27** (sweep #2,
   see §"G2 n_postings sweep" below): raising the global budget to the
   selection-saturated ceiling left every per-query top-10 BIT-IDENTICAL to P0 →
   server-side posting retention is **not** the gap. The mechanism hypothesis
   this confirmed: since 2× more per-list docs *and* saturating the global
   budget both changed zero top-10, the 0.479 divergence is in the *score
   approximation* (summary-skip + in-block coordinate traversal), not posting-list
   retention — an index-knob-blind floor. The only untested lever left of the
   named set is `centroid_fraction` (clustering density), which is not a
   posting-retention lever and is unlikely to move top-10 either.
2. **G6 RRF system-level parity** — G2 (B1 leg-level, ≥0.95) is stricter than
   G6 (full-pipeline RRF NDCG@10 within ±0.005 of 0.560). A leg at 0.479
   overlap can *still* RRF-fuse acceptably; that's an untested, looser gate.

**Honest read of the gate status:** per `02_GO_NO_GO_GATES.md`, "G2/G6 fail →
KILL SEISMIC." G2 now fails *and* is proven non-tunable on the named levers —
so the quality goal arcs toward KILL **unless** one of the two escapes above
holds. The no-JVM + RAM-cured goal (the G3/Path-C axis) is unaffected and
structurally solved; this is a *quality-only* risk on an otherwise-validated
pivot. Path B (OpenSearch+SEISMIC) inherits the *same* SEISMIC approximation,
so it does not dodge G2 — the escape there is Lucene-exact sparse, a different
approximation floor entirely.

## G2 n_postings sweep (2026-06-27 — the global-budget lever, MEASURED, FOLLOW-UP #2)

The direct follow-up to the max_fraction sweep above: `max_fraction` proved
inert because it only raises the *per-list cap* while leaving the *global
budget* `dim*n_postings` unchanged (→ the SAME postings selected → bit-identical
0.4794). `n_postings` is the ONLY index knob that raises the global budget
itself — it changes *which postings exist at all* — so it's the only lever that
could change which docs get scored into the top-10. Mechanism grounded in
`inverted_index.rs:401-437` `global_threshold_pruning`: the top `n_postings*dim`
postings selected globally, then each list capped at `n_postings*max_fraction`.

Ran: `scripts/seismic_testbed/g2_param_sweep.py --lever n_postings`
(Qdrant-memoized — same reuse as sweep #1; each config ≈ build + 34 SEISMIC-only
searches).
→ `data/eval_results/seismic_g2_npostings_sweep.json`

**Grid (3 configs, all other params at DEFAULTS — isolates the single lever):**

| config | n_postings | global budget (`dim*n_postings`) | on-disk | peak RSS | overlap@10 |
|---|---|---|---|---|---|
| **P0_np3500** (anchor) | 3500 | 97.6M | 1.69 GB | 2.83 GB | **0.4794** |
| N1_np7000 (2× budget) | 7000 | 195.3M | 2.35 GB | 6.28 GB | **0.4794** |
| N3_np14000 (ceiling) | 14000 | 390.5M | 2.91 GB | 7.35 GB | **0.4794** |

**Ceiling math (measured, not estimated):** total corpus postings = `idx.nnz`
(the unpruned forward index) = **152,996,652** (2.0M docs × 76.5 nnz/doc). N3's
global budget (390.5M) > 153M total → the **global selection saturates** (every
posting is selected); the only remaining loss is the per-list cap
(14,000×1.5=21,000) clipping the hottest lists — and the `max_fraction` sweep
already proved that cap is irrelevant to top-10 (same postings ⇒ bit-identical).
So N3 is "as unpruned as any index knob can make the SEISMIC retriever."

**VERDICT: `G2 CEILING` (server-side pruning is NOT the gap)** — overlap@10
invariant at 0.4794 across a 3× index-size range *including* the
selection-saturated ceiling. Per-query overlap is **bit-identical** P0==N1==N3
(verified programmatically: both N1 and N3 per-query top-10 are byte-identical
to P0 across all 34 queries). The harness is faithful: P0_np3500 reproduces the
baseline 0.4794 exactly (same Qdrant cache, same anchor).

**What this settles:** the "untested `n_postings`" escape (06 follow-up #1,
the cheapest remaining informative run) is **closed** — raising the global
posting budget to saturation moves zero top-10 results. Combined with sweep #1
(max_fraction inert), **no index-time pruning knob reclaims the 0.479 gap**.
The divergence is the query-time approximation floor (summary-skip + in-block
coordinate traversal), which is structural to SEISMIC's block-summaries design
and is not addressed by any `n_postings`/`max_fraction`/`doc_cut` combination.
Path B (OpenSearch+SEISMIC) inherits this same floor.

**Remaining escapes from "G2 KILL":** (1) `centroid_fraction` (clustering
density — not a posting-retention lever; per the above mechanism, unlikely to
move top-10, and untested), and (2) the **G6 RRF system-level gate** (looser
than the B1 leg-level bar — a divergent leg at 0.479 can still RRF-fuse within
±0.005 of 0.560; this is now the load-bearing escape hatch for the quality goal).

## G6 RRF parity (2026-06-27 — persona-scale attempt, MEASURED → INCONCLUSIVE, persona-unmeasurable)

The load-bearing quality escape after G2 proved non-tunable on every index-time
lever: does RRF (rank-fusion, forgiving of candidate divergence) absorb the 0.479
leg divergence at the system level, landing within ±0.005 of 0.560?

**Built (enables the eventual full-corpus run):**
- `src/lib/thinclient/seismic_backend.py` — SEISMIC relocated under `src/lib/thinclient/`
  (canonical), `scripts/seismic_testbed/seismic_backend.py` now a back-compat shim.
- `ThinClientRetriever` `SFU_SPLADE_BACKEND=seismic` branch wired: lazy `_seismic_backend`
  loader + `_splade_leg_seismic` returning the same `[(oaid, score)]` leg shape as the
  Qdrant leg (RRF/record-tc byte-compatible), clean `RuntimeError` if `SFU_SEISMIC_INDEX`
  unset, degrades to BM25F on failure. Testbed-only, env-gated, never served.
- Built a `social_sciences` 2M SEISMIC index (1.97 GB, dim 28311, nnz 169M, peak RSS
  2.99 GB, 191s build — G1 PASS; the med_bio twin is 1.69 GB/27,896 dims). Picked
  social_sciences over med_bio for judge coverage.

**Why social_sciences:** the persona must cover the judged relevance. med_bio holds
only 31/3958 (0.8%) judged docs → 0/40 queries register scoped NDCG. social_sciences
holds 163/3958 (4.1%) → 20/40 SEISMIC-treatment queries register, 11 paired with the
scoped baseline. Better, but still structurally under-powered.

**The measurement (3 lanes, cached judge, 34-common):**
| lane | n judged | mean NDCG@10 |
|---|---|---|
| Full-corpus baseline (the 0.560 regime) | 39 | 0.5378 |
| Scoped Qdrant-as-sparse-leg (matched) | 11 | 0.2098 |
| SEISMIC treatment (RRF BM25F+seismic) | 20 | 0.1475 |
| Paired Δ (treatment − scoped baseline, n=11) | 11 | +0.0020 |

**VERDICT: G6 INCONCLUSIVE (degenerate + under-powered) — NOT a pass.**
- The matched-baseline is degenerate: the stored Qdrant top-50 is full-corpus, so
  client-side-filtering it to the 2M slice leaves 1–6 docs/query (100% of paired
  queries <10 scoped-Qdrant docs). SEISMIC's 50 dominate RRF → `ov@10` collapses to
  **1.0 on every paired query** → the comparison measures SEISMIC-vs-(mostly)-SEISMIC,
  not SEISMIC-vs-Qdrant.
- Even setting degeneracy aside: SEM(Δ)=0.0058 > the ±0.005 bar (95% CI ±0.0113) → the
  +0.002 delta is **inside the noise floor**, not signal.
- Root cause is judge coverage, not harness: the judged docs are spread across the full
  30M/150M corpus; no 2M topical slice captures enough (med_bio 0.8%, social_sciences 4.1%).
  A ±0.005 bar is narrower than the per-query NDCG spread at n=11.

**Honesty note (the CLAUDE.md efficacy rule):** the raw Δ=0.002 *is* within ±0.005, so a
naïve scorer emits "G6 PASS." It is not — degenerate baseline + below-noise n. The scorer
(`g6_rrf_parity.py`) explicitly detects both and refuses to emit PASS; the result JSON
records `degenerate_baseline: true`, `overlap_unity: true`, `below_noise` diagnostics.

**What a real G6 verdict needs:** either (a) a **full-corpus** SEISMIC run (G7 build +
150M host, the P4 path) where the judge has the 39/40 coverage the baseline enjoys, or
(b) Qdrant **searching the slice collections directly** (not a client-side id-filter) to
make the matched baseline non-degenerate at persona scale. Both are downstream of the
current testbed budget; the wiring + index + scorer are staged so the eventual run is a
config flip, not a rebuild.

Eval: `scripts/seismic_testbed/g6_rrf_parity.py` →
`data/eval_results/seismic_g6_rrf_persona_2m.json` (social_sciences 2M slice).

## Open gates (next measurements, in priority order)

1. **G2 follow-up — DONE 2026-06-27** (see §"G2 param-sweep" and §"G2 n_postings sweep" below): BOTH index-time lever
   axes are now measured and inert. The per-list-cap axis (`max_fraction`, `doc_cut`, `summary_energy`) and the
   global-budget axis (`n_postings`, swept to the selection-saturated ceiling) both leave overlap@10 frozen at 0.479
   with bit-identical per-query top-10. **No index-time pruning knob reclaims the 0.479 gap.** Two escapes from
   "G2 KILL" remain: (a) **`centroid_fraction`** (clustering density — not a posting-retention lever; untested and,
   per the measured mechanism, unlikely to move top-10), and (b) the **G6 RRF system-level gate** (looser than the B1
   leg-level bar; a divergent leg can still fuse — open, not closed by G2).
2. **G5 latency at persona**: the G4 run already recorded per-query ms (sub-ms
   warm); formalize vs the Qdrant persona 66 ms ref.
3. **G6 RRF parity** (P3) — **MEASURED 2026-06-27 → INCONCLUSIVE (persona-unmeasurable)**,
   see §"G6 RRF parity" below. The leg diverges at 0.479, but G2 ≠ G6 — a divergent
   leg *may* still RRF-fuse within ±0.005 of 0.560. The persona-2M run found this is
   **not measurable at persona scale**: any 2M slice holds ≤4% of judged docs (med_bio
   0.8%, social_sciences 4.1%), the matched-baseline client-filter is degenerate
   (ov@10→1.0), and where it pairs (n=11) SEM(Δ)=0.0058 > the ±0.005 bar. A real G6
   verdict needs the full-corpus run (G7/G8) or Qdrant searching slice collections
   directly. SEISMIC→retriever wiring + social_sciences index + treatment leg are
   recorded for that eventual run.

> G4 + G3 + G2-sweeps (#1 max_fraction + #2 n_postings) measured. G4 (the decisive gate) is GREEN; G3 is as
> pre-registered (R-RAM) and now *cured* on Path C (C2, 07 §4.4); G2 fails at default configs AND is not recoverable
> via any index-time pruning lever (both the per-list-cap axis and the global-budget axis proven inert, bit-identical
> to the selection-saturated ceiling). No 150M host spent.

## Current one-line status

**P0 ✓ (gate-zero). P1 ✓ (G1 PASS). P2: G4 ✓ PASS (decisive), G3 ✗ FAIL as
predicted (R-RAM) → **cured on Path C** (C2 KEEPS_GATE, 07 §4.4), G2 ✗ FAIL
(defaults) AND ✗ not-tunable on any index-time pruning lever (both lever axes
proven inert 2026-06-27: per-list-cap `max_fraction`/α/`doc_cut` AND global-budget
`n_postings` to the selection-saturated ceiling → bit-identical 0.479).** SEISMIC
prunes where BMP couldn't — the pivot is validated on the RAM/scale axis. The
no-JVM + RAM-cured goal is structurally solved (Path C). The **remaining open
risk is quality** (G2): 0.479 overlap@10 is the query-time approximation floor
(summary-skip + in-block coordinate traversal), structural to SEISMIC's
block-summaries design and **not retrievable by any index knob**. **G6 (the looser
system-level escape) was measured 2026-06-27 → INCONCLUSIVE: a persona-scale
±0.005 verdict is unmeasurable (any 2M slice holds ≤4% of judged docs; the
client-filtered matched-baseline is degenerate; n=11 paired, SEM 0.0058 > bar).**
The quality goal now hangs on (a) untested `centroid_fraction` (clustering density
— not a posting-retention lever, unlikely to move top-10), or (b) a full-corpus
G6 run (G7/G8) where the judge has real coverage — the persona path cannot
resolve it either way.
