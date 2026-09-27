# SEISMIC 150M Testbed — go/no-go for a no-JVM, RAM-cured sparse leg at full scale

> **Executing (not researching)? Start at `docs/README.md` §"Still open —
> Active backlog"** — the only index of open work (closed-tracks policy,
> 2026-09-25). The 2026-07-05 queue that used to live here is CLOSED: `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md`
> is a historical decision ledger, not an entry point.

**Status:** ACTIVE — as of 2026-09-01, the track's major results are in — dv forward
compression promoted for RAM-capped deploys (doc 10), E5 reorder served by
default since 2026-07-09 (doc 13), G8d parity accepted (0.9906), doc 17
NOT-ADOPTED, doc 18 re-attributed to consolidation. Open queue: `docs/README.md` §"Still open — Active backlog".
Historical queue + binding gate rules: `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` (CLOSED SUPERSEDED 2026-09-25). Created 2026-06-26. · **Lineage:** this is the
successor the prior project named — `archive/sparse_engine_project/07_INTEGRATION_PLAN.md` §8
said *"if 150M-single-collection ever becomes a hard requirement, pivot to SEISMIC,
not more BMP."* That condition has now materialized (below).

## Why this exists now (the forcing function)

The thin client ships on Qdrant, which is **GREEN at persona scale** (30M-fits tier,
p50 ~66 ms). That decision is unchanged for the product. What changed is the
**full-150M-single-collection** path:

- Qdrant at 150M needs **≥64 GB RAM** to leave the disk-bound regime
  (`docs/archive/bmp_decommission_plan/DO_SIZING.md` — 205 GB on disk, 6.55 GB rising anon
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
| RAM cure out-of-the-box | ❌ **NO — RAM-resident, no mmap/on-disk/out-of-core mode** in the public repo as of 2026-06-26. Inherits BMP's row-4 disease: ~8 GB/9M docs → **~133 GB @150M resident** (est., to be measured). | repo README + `archive/qdrant_vs_lucene_assessment/STACK_COST_MATRIX.md` ("Seismic standalone … RAM-resident … not viable @150M") |

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
| `06_FINDINGS.md` | Running results ledger — gate-zero ✓; P1/P2 G1✅ G4✅ G3❌(cured on Path C) G2❌; **G2 sweeps #1+#2+#3 (2026-06-27): ALL THREE lever axes measured — `max_fraction`+`n_postings` inert (bit-identical 0.479), `centroid_fraction` (#3) the only non-inert axis but TUNABLE-NOT-REACHED (+0.003→0.4824, 97% below 0.95) → no index knob clears G2; 0.479 is the query-time approximation floor. G6 (2026-06-27) → INCONCLUSIVE: persona-scale ±0.005 is unmeasurable (any 2M slice holds ≤4% of judged docs; matched-baseline degenerate; n=11, SEM 0.0058 > bar); **G6 re-scoped → PASS 2026-06-30** (matched n=120 SPLADE-leg Δ=+0.0197, CI clears zero — see `02_GO_NO_GO_GATES.md` + `06_FINDINGS.md` 2026-06-30 row). **G5 persona latency → SIGNAL-PASS 2026-07-01** (leg p50 58.20 ms ≤ 66 ms Qdrant ref, n=34, swap-tainted — the real signal is SEISMIC's anon floor surviving the swap storm that wrecked Qdrant's 66→13,930 ms; tail exceeds 66 ms; not "sub-ms" — that was the bare mmap-traversal micro-bench, see `02_GO_NO_GO_GATES.md` G5 row). Persona-unmeasurable note preserved (any 2M slice holds ≤4% of judged docs; matched-baseline degenerate; n=11, SEM 0.0058 > bar). G7 build-RAM CONFIRMED: 150M build needs **25-60 GB band** (NOT 160 GB — the 2-pt linear 128GB claim refuted by the 4-pt curve; sub-linear rss/doc 2.06→0.48 MB/M) → the eventual full-corpus run (G7/G8) is build-feasible on a ~75 GB host; SEISMIC→retriever wiring + indexes built for it.** |
| `07_G3_RAM_FIX_PLAN.md` | **Worklist to cure G3 (RAM-resident)** — byte-split analysis, cheapest→hardest fix menu, Path C scope, cross-referenced upstream/2026 sources. **Step A + C0 + C0.5 + C1a + C2 DONE** — floor CURED on Path C (C2 KEEPS_GATE §4.4: anon +0.041 GB, file-resident 96%, parity✓, latency 0.97×). **G2 quality is now the live open risk** (07 §5 update): neither `max_fraction`/α/`doc_cut` nor `n_postings` recovers 0.479 (both sweep axes inert). |
| `08_LATENCY_RESEARCH.md` | **RAM-efficient ways to speed up the SEISMIC serve leg (G5/G8)** — created 2026-06-30. (A) make the latency measurement clean first (the current G8 run is swap-contaminated, NOT a verdict): cgroup `memory.swap.max=0`, vmtouch pre-fault, madvise(`MADV_RANDOM`/`WILLNEED`), and encode-vs-traverse split instrumentation. (B) shrink the working set (DotVByte forward-index compression, 4-bit summary quant) — latency win *via* RAM, the aligned lever. (C) algorithmic (query_cut/heap_factor sweep — free; LSP/0 top-γ; dynamic superblock pruning — flag RAM trade-off). (D) int8 SPLADE encoder. (E) **RAM-compression lever (owned-anon load + zram/zswap/windows-compression)** — added 2026-07-01: the G8 2×2 matrix (load_mode mmap/stock × mem-compression off/on), wired into `serve_footprint_bench.py` (`detect_memcompression()` + regime-aware verdict gate) with 14 unit tests; **EFFICACY UNMEASURED** — measurement is the operator's Windows-host G8 run. All external numbers labeled literature, not our measurements. |
| `09_CROSS_SHARD_MMAP_AUDIT.md` | (2026-07-02) Cross-shard signal inventory + mmap page economics (forward index = 85% of bytes, ~2 random pages/candidate; MATH-vs-LAYOUT lever table) — the parent of the E6/E7 compression track |
| `10_FORWARD_COMPRESSION_DESIGN.md` | **The dv (dotvbyte) compressed-forward track** — E6 codec design → E6b reuse decision → E7 shipped converter/reader + gates → §7.5 E7b/G8b promotion (−40% RSS, latency-neutral, fits where f16 thrashes) → §7.6 G8d full-corpus parity (corpus 0.9906, shards 1–2 = 0.985 marginal, **accepted 2026-07-05**) + the E8 quality-recovery pre-registration |
| `11_EXPERIMENT_BACKLOG.md` | Pre-registered hypothesis registry (Tier 1/2 host cells — G8c executed 2026-07-04; Tier 3 container queue: E5, E8, M2b, M6, M7, M8) — rows stay until measured |
| `15_R3_KERNEL_LEDGER_SPIKE.md` | **R3 spike — MEASURED 2026-07-16** — per-page eviction/refault attribution of the R2 convergence inversion (bpftrace filemap ledger + `workingset_refault` probe + between-pass `cachestat()` maps × per-query extent maps). Verdicts (§7): attribution REFUTED (repeat-set extents are shared — 19.6% touched by all 40 queries — so residual faults spread ~uniformly; the inversion is trajectory position, not per-query placement); decision-site UNCLEAR (distance not BTF-extractable; probe validated ±2% vs cgroup counter); the-sort-pictured CONFIRMED (12g evicts 3.17 GB by pass 0 vs 16g 0.0; drains to the 10.1 GB repeat set); observer-effect bars met on the final probes. GLM-drive-session-executed (§6); artifact §8 has the write-up |
| `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` | **CLOSED SUPERSEDED 2026-09-25 — archived, historical** (was "START HERE TO EXECUTE", 2026-07-05) — state snapshot, binding gate rules (worst-case-shard, n≥100, quality-free-first), the ordered queue with recipes + pre-registered bars (Q1 E8 dv-v2 → Q2 M7 sim → Q3 M8 instrument → Q4 M2b → Q5 M6 → Q6 E5), host-tier batch list, decision ledger, asset map |
| `build_plans/` | **RAM-escape build plans (2026-06-28)** — how to build+serve a 150M SEISMIC leg on the 32 GB WSL2 box, no JVM, so G6 can be measured: **01** sharded build + federated query (OpenSearch segment-model ported to pure Rust; lossless, fits 32 GB), **02** build-once on a ≥56 GB host + serve mmap, **03** compression/nnz-reduction (adjunct), **04** cross-engine metadata dedup. Index + per-plan dirs in `build_plans/README.md`. Note: this session's forward-floor analysis refines the G7 build-RAM estimate to **~55–63 GB** (the 25 GB lower end of the old 25–60 band is not credible — it ignored the linear 4.10 bytes/nnz forward floor). |
| `REBUILD_TO_PERSISTENT_PATH.md` | **Shard-rematerialization runbook (2026-06-30)** — after the `/tmp` wipe (host reboot) lost all 8 served mmap shards + G7 sources + section spool. The upstream 150M corpus survives at `data/thinclient_index/spool_backup` (123 GB) → rebuild feasible. Final mmap shards land persistent at `data/seismic_150m/index/plan01/` (NOT `/tmp`); G7 sources + scratch stay on `/tmp`. Chain smoke-verified end-to-end before the full run. Unblocks `SequentialSeismicBackend` efficacy measurement (Tier 1 #3). |

## Standing constraint (do not re-litigate)

This testbed is **scoped to the 150M-single-collection server problem only.** At
persona scale Qdrant is GREEN and nothing here is needed — the prior STOP
(`archive/sparse_engine_project/`) stands for the product we ship. Do not let this re-open
the bespoke-engine question for the laptop tier.

## 17 — BM25-through-SEISMIC spike (MEASURED & NOT ADOPTED, 2026-08-01)

`17_BM25_THROUGH_SEISMIC_SPIKE.md`. Can SEISMIC also serve the BM25 lexical leg,
retiring tantivy? Quality says yes (overlap@10 0.9992 vs exact BM25F; LLM-judged
−0.66% NDCG@10 vs tantivy), cost says no (22.4× tantivy on disk, and exact only
because the pruning budget is 95× oversized on BM25's 710k-term vocabulary —
force pruning to bind and overlap falls to 0.3942 at still 7.1× the size). The
mirror question is a harder no: tantivy cannot serve SPLADE (overlap@10 0.485).
Code `spike/bm25_seismic/`, results `data/eval_results/bm25_seismic_spike_*`.

## 18 — Ordinal addressing design (MEASURED, NOT IMPLEMENTED; RE-ATTRIBUTED 2026-08-03)

> **READ §14–§16 BEFORE QUOTING ANY MULTIPLE BELOW (2026-08-03).** The
> headline numbers in this entry — 3.20×, 120–211×, 2.89× — were all measured
> against a `meta.sqlite`/`abstracts.sqlite` on **9p**, a WSL2-dev-container
> artifact that **does not exist on the deployment target** (a DO droplet
> serves the index from local block storage; `THIN_CLIENT_SWAP.md:251-254`).
>
> - **§14:** N6's 3.20× is a **filesystem** result, not an addressing one.
>   Staging `meta.sqlite` to local disk — no code change — gets 2.83×; adding
>   ordinals on top gets nothing further. The two levers are **redundant, not
>   additive**. Against a production-realistic baseline the whole ordinal win
>   is **4.0 → 1.5 ms = 2.0% of the query**, inside the ±4% noise floor.
>   Ordinals are a **residency** lever (and *additive* 1.96 GB on disk, since
>   `_hydrate` still needs `meta.sqlite`), not a latency or space lever.
> - **§15 (C7):** with the goal changed from latency to **consolidation**,
>   §13's rejected title/DOI store was reopened and measured: a per-record zstd
>   store replaces `meta.sqlite` for **14.69 GB vs 24.91 GB (−10.22 GB)** while
>   `_hydrate` gets *faster* (0.70× mainline). Latency is a 1M-doc
>   extrapolation; size is trustworthy. **Unbuilt.**
> - **§16 (C8):** `abstracts.sqlite` is deletable — **13.47 → 11.57 GB
>   (−1.90 GB)**, parity PASS on 20,000 ids. And **§9 optimised the wrong
>   half**: the payload move is worth 1.21× on a level filesystem, while
>   replacing the **locator** (23.4M rows keyed by TEXT W-ids) adds 4.55× on
>   top. p50 5.53×, mean 2.09×, **p90 essentially unimproved (1.19×)**.
>   Reader **unwritten**.
>
> Consolidation scorecard: doc 17 §13's "4 → 0 storage databases" is not
> reachable; **4 → 2** is (`meta.sqlite` + `abstracts.sqlite` removable, both
> dense artifacts stay). Nothing is enabled or built.

`18_ORDINAL_ADDRESSING_DESIGN.md`. The follow-on from 17 §10–§13. Finding: the
thin client's storage cost is an **addressing** problem, not a storage-engine
problem. A W-id (OpenAlex Work ID) is a *sparse* key — 150M docs over a 7.14e9
range — so resolving one is inherently a search; doing it ~1000×/query is the
~400 ms post-filter mask. C1/C3/C5 all swapped the *searcher* (tantivy fst,
Lance BTREE) while keeping the *address*, and all lost. Assigning dense build-time
**ordinals** makes the mask an array index (0.16–1.0 ms vs 38–400 ms at 150M) and
lets ~1.95 GB stay resident where 24.9 GB cannot. Closes 17 §13's load-bearing
gap: tantivy fast-field reads are 2.1–11× cheaper than the stored-id read
production already pays. Cross-referenced to Lucene's docid↔UID split (mainstream
practice; we collapsed identity and address) and to MPHF/Elias-Fano, proposed as
better primitives than the sorted array (**MPHF refuted 2026-09-27, §7 N2
CLOSED MEASURED FAIL:** PtrHash is 56.2 MB alone but 1.26 GB with the
verification read an exact answer needs — larger than the 1.20 GB sorted
array, which stays; `data/eval_results/n2_mphf_viability_2026-09-27.json`). Ends with staged next
steps N1–N5. **N5, N3 and N4 EXECUTED 2026-08-02** (§9, §11): the flat block
store was built and passed a byte-parity gate on 20,000 abstracts at 2.89×
end-to-end (correcting §11's 3.4× projection); ordinal artifacts built at 97,063
docs/s; and the `_post_filter` swap passed a 360-trial parity gate (ids, scores
AND rank order) at **120–211×**, 214.1 → 1.013 ms at 1000 candidates, with **no
rebuild of any engine**. §10 restages the design: a tantivy rebuild buys ~2% and
would cost ~127M re-fetched OpenAlex abstracts, so it is deferred indefinitely.
**N6 EXECUTED 2026-08-02 (§13) — the whole-query number: 3.20× at production's
default `top_k=50` (344.6 → 107.6 ms) and 2.70× at `top_k=100`, parity PASS on
216/216 pairs with 0 coverage misses in 57,600 ids.** `_post_filter` is **61.5%**
of the query, which is why the stage win survived end-to-end. The `bm25f`
negative control (it never post-filters) bounds noise at ~9%, so the k=10 row's
1.13× is inside the band and is not claimed. **`_hydrate` extension REJECTED on
measurement** — `hydrate_meta` is 17.5 ms / 4.1%, not worth a 150.4M-doc blob
(the MPHF ~2% / C3-locator 1.3% trap again). **Residency is a precondition:**
run from a 9p mount the ordinal arm measured 8× *slower* than SQLite. §12 built
the full 150M space (98,867 docs/s, 1.96 GB vs meta.sqlite's 24.91 GB), the
stale-ordinal guard, and the retriever gate `SFU_THINCLIENT_ORDINALS`
(default off; nothing is enabled). **§14–§16 (2026-08-03) re-attribute every
multiple in this paragraph and pivot the work to consolidation — see the banner
at the top of this entry. The `_hydrate` rejection in particular was REOPENED
(§15): it was made against a latency objective, and the goal is deleting a
database.** Code `spike/meta_consolidation/`, results
`data/eval_results/c6_*`, `n3_*`, `n4_*`, `n5_*`, `n6_*`, `n7_fs_control_*`,
`c7_meta_flat_*`, `c8_abs_locator_*`.
**§22 (2026-08-17): the flat abstract sidecar was BUILT AND PUBLISHED** for
`social_sciences__recent` (gate PASS, 11.57 GB, 19 min 33 s) — the section
serves flat today. **§23 (2026-08-17): its SERVING efficacy is now measured**
against that directory rather than carried forward from the spikes — byte-parity
PASS, **local disk 1.091× warm / 2.546× cold**, 9p 2.876× (a filesystem
artifact), −1,897,229,898 B; §17's 1.18× does not reproduce on real ranked
result sets, and a freshly started process is **0.919×** (slower) until its
421 MB locator is resident. Harness
`scripts/seismic_testbed/j1_flat_sidecar_serving_ab.py`, results
`data/eval_results/j1_flat_*_20260817.json`.
