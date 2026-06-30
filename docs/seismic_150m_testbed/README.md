# SEISMIC 150M Testbed — go/no-go for a no-JVM, RAM-cured sparse leg at full scale

**Status:** OPEN (created 2026-06-26). Gate-zero (literature + repo fact-find)
**MEASURED**; all serving gates OPEN. · **Owner:** TBD · **Lineage:** this is the
successor the prior project named — `sparse_engine_project/07_INTEGRATION_PLAN.md` §8
said *"if 150M-single-collection ever becomes a hard requirement, pivot to SEISMIC,
not more BMP."* That condition has now materialized (below).

## Why this exists now (the forcing function)

The thin client ships on Qdrant, which is **GREEN at persona scale** (30M-fits tier,
p50 ~66 ms). That decision is unchanged for the product. What changed is the
**full-150M-single-collection** path:

- Qdrant at 150M needs **≥64 GB RAM** to leave the disk-bound regime
  (`docs/bmp_decommission_plan/DO_SIZING.md` — 205 GB on disk, 6.55 GB rising anon
  floor, p50 545–861 ms / p95 3.4–4.5 s when RAM-bound).
- The host we have is **31.6 GB**. Measured live (this session): 150m resting
  RssAnon ~17.4 GB, MemAvailable ~8.8 GB, projected force-optimize peak ~38 GB >
  31.6 GB host → **150M has OOM'd here during optimization** (`os error 12`,
  Jun 19–20). A1-on-150M is **blocked by host RAM**, not merely deferred.

So the 150M-single-collection question is no longer hypothetical: **the present
engine cannot serve it on the hardware we have.** Per §8, the named pivot is SEISMIC.
This testbed decides — with measured gates, not adjective — whether SEISMIC actually
delivers a **no-JVM, embeddable, RAM-cured** sparse leg at 150M, or whether it
repeats BMP's RAM disease and the honest answer is "accept the JVM (OpenSearch+SEISMIC)
or buy a bigger box."

## The one-sentence question

> SEISMIC's pruning is **validated at 138M** (ECIR 2025) — the thing BMP's WAND
> pruning was **not** (it scored ~95% of blocks, linear in corpus). But the FOSS
> reference impl is **RAM-resident, no mmap** (repo README, 2026-06-26). **Can
> SEISMIC's validated-at-scale pruning be served at 150M with the RAM floor cured,
> without a JVM** — and is that worth owning over just running OpenSearch+SEISMIC?

## Gate-zero finding (MEASURED 2026-06-26 — the cheapest kill, already run)

| Property | Finding | Source |
|---|---|---|
| Algorithm validated at scale | ✅ **YES — 138M MS MARCO v2** (≈ our 150M target). SEISMIC *prunes* (geometric blocks + summary vectors) — the exact gap that killed BMP (row-6 linear pruning). | ECIR 2025, [arXiv:2501.11628](https://arxiv.org/abs/2501.11628) |
| No-JVM / embeddable | ✅ **YES** — pure Rust, MIT, `cargo add seismic` + `pyseismic-lsr` Python bindings. Clears the two gates OpenSearch+SEISMIC fails. | [github.com/TusKANNy/seismic](https://github.com/TusKANNy/seismic) |
| RAM cure out-of-the-box | ❌ **NO — RAM-resident, no mmap/on-disk/out-of-core mode** in the public repo as of 2026-06-26. Inherits BMP's row-4 disease: ~8 GB/9M docs → **~133 GB @150M resident** (est., to be measured). | repo README + `qdrant_vs_lucene_assessment/STACK_COST_MATRIX.md` ("Seismic standalone … RAM-resident … not viable @150M") |

**Plain reading:** SEISMIC fixes BMP's *fatal* axis (pruning) and keeps no-JVM —
but ships with BMP's *other* axis (RAM-resident) unfixed. So this is **not** a "wire
up an existing crate and done" outcome; the RAM cure is the open work, and the
question is whether it's a small surgical add (mmap the forward/inverted store) or a
maintenance trap. That is what the gates below decide.

## Documents

| Doc | What |
|---|---|
| `00_VISION_AND_GOALS.md` | What we're deciding, success/kill definitions, goals in priority order |
| `01_ARCHITECTURE.md` | The three candidate paths (A standalone / B OpenSearch+SEISMIC / C mmap-substrate) + the **two co-resident mmap engines** design (tantivy lexical + SEISMIC sparse, fused at RRF — *not* SEISMIC-into-tantivy-postings, and why) |
| `02_GO_NO_GO_GATES.md` | The HARD/SIGNAL gates with thresholds; gate-zero filled in |
| `03_BENCHMARK_METHODOLOGY.md` | **Full benchmarking documentation** — corpus, queries, metrics, harness, parity bars, reproduction steps |
| `04_BUILD_AND_GATHER.md` | Assets in-container vs what to create per phase |
| `05_RISK_REGISTER.md` | Risks + cheapest retiring experiment per risk |
| `06_FINDINGS.md` | Running results ledger — gate-zero ✓; P1/P2 G1✅ G4✅ G3❌(cured on Path C) G2❌; **G2 sweeps #1+#2+#3 (2026-06-27): ALL THREE lever axes measured — `max_fraction`+`n_postings` inert (bit-identical 0.479), `centroid_fraction` (#3) the only non-inert axis but TUNABLE-NOT-REACHED (+0.003→0.4824, 97% below 0.95) → no index knob clears G2; 0.479 is the query-time approximation floor. G6 (2026-06-27) → INCONCLUSIVE: persona-scale ±0.005 is unmeasurable (any 2M slice holds ≤4% of judged docs; matched-baseline degenerate; n=11, SEM 0.0058 > bar); **G6 re-scoped → PASS 2026-06-30** (matched n=120 SPLADE-leg Δ=+0.0197, CI clears zero — see `02_GO_NO_GO_GATES.md` + `06_FINDINGS.md` 2026-06-30 row). Persona-unmeasurable note preserved (any 2M slice holds ≤4% of judged docs; matched-baseline degenerate; n=11, SEM 0.0058 > bar). G7 build-RAM CONFIRMED: 150M build needs **25-60 GB band** (NOT 160 GB — the 2-pt linear 128GB claim refuted by the 4-pt curve; sub-linear rss/doc 2.06→0.48 MB/M) → the eventual full-corpus run (G7/G8) is build-feasible on a ~75 GB host; SEISMIC→retriever wiring + indexes built for it.** |
| `07_G3_RAM_FIX_PLAN.md` | **Worklist to cure G3 (RAM-resident)** — byte-split analysis, cheapest→hardest fix menu, Path C scope, cross-referenced upstream/2026 sources. **Step A + C0 + C0.5 + C1a + C2 DONE** — floor CURED on Path C (C2 KEEPS_GATE §4.4: anon +0.041 GB, file-resident 96%, parity✓, latency 0.97×). **G2 quality is now the live open risk** (07 §5 update): neither `max_fraction`/α/`doc_cut` nor `n_postings` recovers 0.479 (both sweep axes inert). |
| `08_LATENCY_RESEARCH.md` | **RAM-efficient ways to speed up the SEISMIC serve leg (G5/G8)** — created 2026-06-30. (A) make the latency measurement clean first (the current G8 run is swap-contaminated, NOT a verdict): cgroup `memory.swap.max=0`, vmtouch pre-fault, madvise(`MADV_RANDOM`/`WILLNEED`), and encode-vs-traverse split instrumentation. (B) shrink the working set (DotVByte forward-index compression, 4-bit summary quant) — latency win *via* RAM, the aligned lever. (C) algorithmic (query_cut/heap_factor sweep — free; LSP/0 top-γ; dynamic superblock pruning — flag RAM trade-off). (D) int8 SPLADE encoder. All external numbers labeled literature, not our measurements. |
| `build_plans/` | **RAM-escape build plans (2026-06-28)** — how to build+serve a 150M SEISMIC leg on the 32 GB WSL2 box, no JVM, so G6 can be measured: **01** sharded build + federated query (OpenSearch segment-model ported to pure Rust; lossless, fits 32 GB), **02** build-once on a ≥56 GB host + serve mmap, **03** compression/nnz-reduction (adjunct), **04** cross-engine metadata dedup. Index + per-plan dirs in `build_plans/README.md`. Note: this session's forward-floor analysis refines the G7 build-RAM estimate to **~55–63 GB** (the 25 GB lower end of the old 25–60 band is not credible — it ignored the linear 4.10 bytes/nnz forward floor). |
| `REBUILD_TO_PERSISTENT_PATH.md` | **Shard-rematerialization runbook (2026-06-30)** — after the `/tmp` wipe (host reboot) lost all 8 served mmap shards + G7 sources + section spool. The upstream 150M corpus survives at `data/thinclient_index/spool_backup` (123 GB) → rebuild feasible. Final mmap shards land persistent at `data/seismic_150m/index/plan01/` (NOT `/tmp`); G7 sources + scratch stay on `/tmp`. Chain smoke-verified end-to-end before the full run. Unblocks `SequentialSeismicBackend` efficacy measurement (Tier 1 #3). |

## Standing constraint (do not re-litigate)

This testbed is **scoped to the 150M-single-collection server problem only.** At
persona scale Qdrant is GREEN and nothing here is needed — the prior STOP
(`sparse_engine_project/`) stands for the product we ship. Do not let this re-open
the bespoke-engine question for the laptop tier.
