# 03 · Go / No-Go Gates

> **CLOSED MEASURED 2026-06-26** — the bespoke sparse engine was MEASURED & STOPPED 2026-06-26 (verdict STOP in `07_INTEGRATION_PLAN.md` §8: pruning linear in corpus, ~50 GB inverted side at 150M). SEISMIC federated mmap took the slot (promoted 2026-07-06, `docs/archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md`); the FORMAT-WALL result is kept. Not current; do not resume.

**Status:** CLOSED MEASURED 2026-06-26

HARD = a fail kills (or blocks) the project. SIGNAL = informs, doesn't auto-kill.
Numbers are the decision thresholds; record the actual value next to each when run.

| Gate | Phase | Type | PASS condition | Why this number | Measured |
|---|---|---|---|---|---|
| **G1 Correctness** | P1 | HARD | mmap top-k `(ids, scores)` **byte-identical** to stock BMP for every (shard, query) | the fork must change storage, not results; any diff = wrong fork | ✅ PASS 2026-06-25 |
| **G2 RAM (the cure)** | P1 | HARD | `RssAnon` after loading shards **< 1 GB** (target ~0); resident scales with *hot working set*, not point count | the entire point — kills the 6.55 GB rising anon floor | ✅ PASS 2026-06-25 (R3 flat rewrite) |
| **G3a Warm latency** | P2 | HARD | warm p50 **≤ live Qdrant p50** on the same section (30M gate ≈ 66 ms; section-scaled) | must not regress serving speed vs what we have | ❌ FAIL 2026-06-26 (R3-v1 decode-per-query) · **🔄 re-test PASS 2026-06-26 (R3-v2 zero-decode: 25.63 ms)** — see decision log |
| **G3b Cold p95** | P2 | HARD | cold p95 **≤ ~2–3× warm p95** at a section size that does NOT fit page cache | the open architectural risk: do term-major faults stay bounded? | ✅ PASS 2026-06-26 |
| **G3c Disk** | P2 | SIGNAL | sparse on-disk ≈ BMP b256 (≈ 3× smaller than Qdrant f32) | confirms the disk win | ✅ PASS 2026-06-26 |
| **G2b Inverted-side RAM** | P3a | HARD | RssAnon flat-in-corpus on all 16 persona shards (≪ 8.26 GB) | the forward-only cure left the inverted side owned; this proves the floor is *fully* cured | ❌ **FAIL (measured 2026-06-26)** — ~334 B/doc gc-persistent → ~7.8 GB@persona (ref 8.26), **~50 GB@150M ≈ 7.6× the Qdrant 6.55 GB floor it replaces.** Eval: `data/eval_results/p3a_inverted_floor.json`. |
| **G3d Pruning + parallel** | P3b | HARD | blocks-scored sub-linear in corpus AND native parallel warm p50 ≤ 66 ms (full persona) | zero-decode made scoring-all-blocks cheap; this checks the *algorithm* actually prunes at scale | ❌ **FAIL — pruning linear (measured 2026-06-26)** — worst-query `blocks_scored/num_blocks` ≈ 0.95 **stable across a 2.15× corpus jump** ⇒ linear in corpus (not sub-linear). Per-shard warm p50 ceiling 40 ms ≤ 66 at persona is PASS but moot at 150M (linear block count dominates). Eval: `data/eval_results/p3b_pruning_persona.json`. |
| **G3e 150M projection** | P3c | SIGNAL→HARD | extrapolated 150M RAM flat + latency ≤ budget; no linear blow-up | the target scale is the whole point — persona greens don't authorize 150M | ❌ **FAIL (projection from G2b+G3d evidence 2026-06-26)** — ~50 GB RAM + ~557K block-scores/query at 150M. |
| **G4 End-to-end quality** | P3 | HARD | section RRF NDCG@10 within ±0.005 of current stack; degrade-to-BM25F works | no quality regression at the system level | ⛔ not reached — gate-zero STOP at P3a/P3b |
| **G5a 150M RAM** | P4 | HARD | full-150M served with `RssAnon` flat/~0 (no rising floor); no OOM | proves the cure at the target scale | ⬜ |
| **G5b 150M parity** | P4 | HARD | B1 overlap@10=1.0 / τ=1.0 + B2 RRF |Δ|<0.005 vs current (still > OpenSearch +~0.11) | the decommission-plan bar, re-passed on the new engine | ⬜ |
| **G5c 150M latency curve** | P4 | SIGNAL | p50 vs host-RAM curve matches/beats Qdrant; reaches fitting-tier on a smaller box | the practical serving win | ⬜ |
| **G6 Productionization** | P5 | HARD | reproducible per-arch build (maturin wheels); hot/cold packaging integrated; runs on a laptop (local) and a server (150M) | it's an engine, not a demo | ⬜ |
| **G7 Unification (opt)** | P5 | SIGNAL | lexical+sparse+dense in one Lance store; build/serve from it | only if Option B pursued | ⬜ |

## Kill criteria (explicit)
- **G1 fails** → fork is incorrect OR BMP semantics can't survive zero-copy → fix or kill.
- **G2 fails** (RssAnon still high) → mmap didn't actually offload (still copying into
  RAM) → the cure isn't real → **KILL**, fall back to immutable-JVM (OpenSearch+SEISMIC)
  or accept Qdrant+host-sizing.
- **G3a fails** (warm p50 > qdrant) → the mmap path is RAM-cheap but not *fast* — per-block
  decode cost dominates, not faults → **KILL the standalone idea** (this is what happened
  2026-06-26: warm 696 ms vs qdrant 66 ms). Cheap mitigations (`madvise`/prefetch) do NOT
  help — the faults were never the cost (G3b proved cold≈warm, ratio 1.04). **Caveat on the
  fix (added 2026-06-26):** the decode cost is a property of R3's *compact* on-disk format
  (`get_block` decodes per query), **not proven intrinsic to mmap-BMP** — stock load-into-RAM
  BMP is 4.7 ms because its forward index is decoded-and-resident. The kill was NOT tested
  against a **zero-decode, directly-addressable** forward layout (read a block by pointer-cast
  over the mmap slice, no decode). That single ~1–2 day test distinguishes *format-wall* from
  *real-wall* and is the only thing that could flip this verdict — scoped in
  `06_NEXT_STEPS_ZERO_DECODE.md`. Absent that test, the kill stands but should not be read as
  "mmap sparse is fundamentally too slow."
  **UPDATE 2026-06-26 — the test RAN and it FLIPPED (FORMAT-WALL):** the zero-decode
  layout (R3-v2, `bytemuck::cast_slice` over the mmap + `flat_block_score`) drops warm
  p50 from **696 ms → 25.63 ms** on the same 4-shard subset — below qdrant 66 ms, G1
  byte-identical (50/50 + 40/40), anon 1.976 GB, cold/warm 1.49. **The wall was the
  compact format, not the Block-Max algorithm; the P2 kill was premature.** Caveat: the
  #blocks-scored confound (max 7424 ≈ full block count) shows pruning touches O(corpus)
  blocks/query — the win is real but fragile at larger scale; §4 follow-ons (inverted-side
  mmap, native parallel shard search, P3/G4) still gate any re-open. Full record: decision
  log + `data/eval_results/p2_zerodecode_med_bio_4shard.json`.
- **G3b fails** (cold p95 blows up, e.g. >5–10× warm) → scattered faults dominate; the
  term-major layout wasn't enough → **KILL** the standalone idea; reconsider only if a
  block-prefetch/`madvise` redesign is cheap. *(G3b PASSED 2026-06-26 — the cold-fault
  bet was won; G3a, not G3b, is the P2 killer.)*
- **G5b fails** (quality drifts at 150M) → the engine isn't faithful → **KILL**.

## P2 verdict (2026-06-26): RED — KILL the standalone build, keep the findings
> **🔄 SUPERSEDED 2026-06-26 by the zero-decode re-test (FORMAT-WALL).** The RED
> below applies to the **R3-v1 decode-per-query** format. The R3-v2 zero-decode
> test (`06_NEXT_STEPS_ZERO_DECODE.md`) ran the same 4-shard subset and flipped
> G3a: warm p50 **696 ms → 25.63 ms** (≤ qdrant 66 ms), G1 byte-identical, anon
> 1.976 GB. **The wall was the compact format, not the algorithm — the kill was
> premature.** The standalone idea is NOT dead, but is not yet shippable (§4
> follow-ons still gate re-open). See the G3a/G1 zero-decode decision-log rows +
> `data/eval_results/p2_zerodecode_med_bio_4shard.json`. The original v1 RED
> record is preserved below for provenance.

**G3b (cold p95) WON** — the mmap locality bet was right, cold≈warm (1.04×). But
**G3a (warm latency) FAILS hard** (696 ms vs qdrant 66 ms, ~10×) — the per-block decode
cost makes the mmap path too slow to serve regardless of cache state, and it scales worse
than linear. Per the kill criteria, a HARD-gate fail → **stop the standalone `immsparse`
build.** Do NOT spin off the repo; do NOT proceed to P3.

Bonus scale finding (not a P2 gate but decisive): **G2 does not hold at persona scale** —
R3 cured only the *forward* index; the *inverted* side it left owned (`documents` Strings
+ `range_maxes` PostingLists) scales with corpus → 8.26 GB anon on 16 persona shards
(0.5 GB/shard, vs 0.535 GB for all 5 at 1M). A true zero-anon cure would also need the
inverted side mmap'd — more invasive than the spike's budget, and moot given G3a kills it.

**Net:** the spike did exactly what fail-fast spikes are for — killed the dream engine
with measured numbers in ~3 days, created no repo. The two papers'-thesis bets split:
*mmap cures the RAM floor* — **partially** (forward yes, inverted no, at scale); *mmap
keeps cold latency bounded* — **yes** (G3b). But *mmap makes BMP fast enough to serve* —
**no** (G3a, decode-bound). Fallback paths stand unchanged: per-persona Qdrant locally;
Infinity or OpenSearch+SEISMIC server (see `docs/archive/qdrant_vs_lucene_assessment/`).

## Decision log (fill in as gates run)
| Date | Gate | Value | Verdict | Note |
|---|---|---|---|---|
| 2026-06-25 | G1 | 50/50 byte-identical (5 shards × 10 q, k=50) | PASS | mmap+deserialize read path is faithful; build (nightly + pyo3 0.21, cp311) works. R4 retired. Eval: `spike/archive/mmap_bmp/compare_fork.py` w/ `BMP_LOAD=mmap`, `MMAP_BMP_SITE=<throwaway venv>`. Result: `spike/archive/mmap_bmp/out/baseline.json` (re-baselined, all 5 shards) |
| 2026-06-25 | G2 | RssAnon = 1.86 GB while 1 Searcher live on 606 MB shard | FAIL | **R2 confirmed (as predicted).** `bincode::deserialize_from` materializes the nested `BlockForwardIndex.data` `Vec`s as anonymous RAM even when read from an mmap'd slice — mmap'ing the file doesn't avoid the deserialize allocation. The cheap "buffer-source swap" probe does NOT cure the floor. True G2 cure needs **lazy per-block decode over a flat layout** (bincode → mmap-friendly format + matching builder) = risk R3 (invasive, timeboxed). Decision pending on whether to invest in the R3 rewrite vs invoke the kill/fallback |
| 2026-06-25 | G2 | RssAnon peak 0.535 GB across all 5 shards (flat in corpus size) | **PASS** | **R3 flat rewrite CURES the floor.** New `src/index/flat.rs` + `src/flat_search.rs`: forward index stored flat behind an offset table, mmap'd, one block decoded transiently per `block_score`; inverted side (termmap/range_maxes/documents) stays owned-but-small. Down from 1.86 GB (stock mmap) / 1.98 GB (load-into-RAM) → 0.535 GB for all 5 shards, flat in corpus. Fork patch: `spike/archive/mmap_bmp/R3_fork.patch` (applies clean to upstream). Eval: `spike/archive/mmap_bmp/compare_flat.py` (`BMP_LOAD=flat`). The make-or-break R2 bet is WON. |
| 2026-06-25 | G3 | cold/warm p50 ≈ 67 ms vs stock 4.67 ms; p95 ≈ 330 ms | SIGNAL (degraded, not HARD) | **Latency regressed ~14× (R1 surfacing).** Per-block decode + page-fault cost dominates; 1M shards fit page cache so this is decode/access overhead, not true cold-fault. Expected open risk; P2 measures it at section scale and `madvise`/prefetch mitigations target it. G3 is a signal gate at P1 (HARD only at P2, G3a/G3b) — does NOT block the G1+G2 GREEN verdict. |
| 2026-06-26 | G2 (at scale) | RssAnon **8.26 GB** loading all 16 persona shards (med_bio, 23.4M docs, 9.0 GB flat) | ⚠️ **REGRESSION at scale** | **The G2 cure does NOT hold flat-in-corpus at persona scale.** R3 cured the *forward* index (the ~100% of anon at 1M), but left the *inverted* side owned — `FlatIndex::from_mmap` does `.to_vec()` on `documents: Vec<String>` (one per doc, 23.4M strings), `range_maxes: Vec<PostingList>`, `kth_scores`. At 1M×5 it read 0.535 GB (small); at persona (16 shards × ~1.5M) it's **0.5 GB/shard → 8.3 GB** — the floor is back, just moved from forward to inverted side. Targeting the forward index alone was insufficient; a true zero-anon cure must ALSO mmap the inverted side (offset-index `documents` + `range_maxes`). NOT a P2 gate (G2 is P1), recorded here as the decisive scale finding. Eval: `spike/archive/mmap_bmp/measure_p2_cold.py` load (`/proc/self/smaps_rollup`: Pss_Anon 8.26 GB, Pss_File 3.87 GB). |
| 2026-06-26 | G3b | cold p95 1515 ms / warm p95 1458 ms → **cold/warm = 1.04** (4-shard subset, no swap) | ✅ **PASS** | **The R1 cold-fault bet WON.** Almost no cold-vs-warm separation (ratio 1.04) ⇒ cost is **per-block decode, not page faults**. The term-major+contiguous locality hypothesis holds: cold faults stay bounded. P2's *named* risk is retired. BUT cold p95 1515 ms is itself huge — because the decode cost (G3a) dwarfs any fault cost. Eval: `spike/archive/mmap_bmp/measure_p2_cold.py` (`--no-drop posix_fadvise`, clean 4-shard run). Result: `data/eval_results/p2_coldp95_med_bio_4shard.json`. Measured on 4 of 16 shards (2.4 GB flat, 1.98 GB anon) to avoid swap contamination from the full 8.3 GB anon loading concurrently with live qdrant on the 31 GB host. |
| 2026-06-26 | G3a | warm p50 **696 ms** / p95 1458 ms vs qdrant 66 ms (4 shards) | ❌ **FAIL** | **Warm decode is ~10× too slow — the real P2 killer.** The mmap path is RAM-cheap(ish) but not *fast*: per-`search()` warm p50 696 ms vs qdrant section-scale 66 ms. Scales worse than linear (1M shard 67 ms → ~625k-doc persona shard ~174 ms ≈ 2.6× for ~0.6× docs) — the per-block decode in `flat_search` + the heap-driven descending-upper-bound block iteration dominate, exactly the R1 tail risk the register flagged as costing schedule. Per the kill criteria G3a is HARD and fails → **RED.** Mitigation would need SIMD/batch block decode or a re-layout for sequential block-eval reads — not a cheap `madvise` tweak (the faults were never the cost). Eval: `spike/archive/mmap_bmp/measure_p2_cold.py`. Result: `data/eval_results/p2_coldp95_med_bio_4shard.json`. qdrant 66 ms bar: `docs/archive/qdrant_vs_lucene_assessment/QDRANT_VS_LUCENE_RAM.md` (30M-fits tier). |
| 2026-06-26 | G3c | flat 0.79× bincode: 17.8 GB `.bmp` → 9.0 GB `.bmflat` (16 shards) | ✅ PASS (SIGNAL) | The disk win holds at scale (≈3× under Qdrant f32 at 150M). Persona build: `spike/archive/mmap_bmp/build_persona_bmp.py` (med_bio from `spool_backup`, 23.4M docs → 16 shards). |
| 2026-06-26 | G1 (zero-decode) | **50/50 byte-identical** (1M, 5 shards × 10 q, k=50) + **40/40 byte-identical** (persona 4 shards, zero-decode v2 vs stock load-into-RAM, same `.bmp`) | ✅ **PASS** | **The zero-decode layout (R3-v2) is faithful at both scales.** Forward region re-laid-out as `#[repr(C)]` POD (`FlatPair{doc_off:u8,score:u8}` + `TermEntry{term_id:u16,pair_len:u16}`); reader = `bytemuck::cast_slice` over the mmap sub-slice (zero decode, zero alloc); scorer = `flat_block_score`, a faithful twin of upstream `block_score`'s two-pointer walk over the views (block_score itself untouched — stock path byte-identical). Disk headroom held: 2.9 GB `.bmp` → 2.4 GB `.bmflat` (0.79×, G3c intact). Eval: `spike/archive/mmap_bmp/compare_flat.py` (1M) + `spike/archive/mmap_bmp/compare_zerodecode_persona.py` (persona). Result: `data/eval_results/p2_zerodecode_G1_1m.json`. Throwaway venv: `/tmp/bmp-fork-work/zerodecode-venv` (cp311, pyo3 0.21, bytemuck). |
| 2026-06-26 | G3a (zero-decode re-test) | warm p50 **25.63 ms** / warm p95 57.01 ms vs qdrant 66 ms (4-shard med_bio); RssAnon 1.976 GB; cold/warm 1.49; **#blocks-scored/query p50 3481 / max 7424** | 🟢 **FORMAT-WALL — the kill was premature** | **Removing the per-query decode flips G3a from 696 ms (R3-v1) → 25.63 ms (R3-v2): a ~27× drop, now BELOW the qdrant 66 ms bar.** G1 byte-identical, anon 1.976 GB/4 shards (≤ ~2 GB holds; the inverted-side floor is the same P2-measured one, not a regression), G3b cold/warm 1.49 (still won). **Per `06_NEXT_STEPS_ZERO_DECODE.md` §3 this is the FORMAT-WALL outcome: the wall was R3-v1's compact format (decode per query), NOT the Block-Max algorithm.** Same 4-shard subset + same `posix_fadvise` weak-cold mode as the P2 RED baseline (`--no-drop`; `sudo drop_caches` unavailable in this container, fell back — apples-to-apples vs the 696 ms run which used the same mode). Eval: `spike/archive/mmap_bmp/measure_p2_cold.py` (harness edited to record #blocks-scored). Result: `data/eval_results/p2_zerodecode_med_bio_4shard.json`. **⚠️ Confound caveat (does NOT flip the verdict but bounds it):** the #blocks-scored confound fires hard — max 7424 ≈ the entire block count of the largest shard (~1.9M docs / 256 bsize), i.e. the descending-upper-bound iteration prunes almost nothing and scores O(corpus) blocks per query. The win is real *because* zero-decode made scoring-all-blocks cheap; but at larger scale, scoring O(corpus) blocks/query with no pruning could re-establish a wall. `06_NEXT_STEPS_ZERO_DECODE.md` §4 follow-ons a re-open still needs: (1) mmap the inverted side too (`documents` + `range_maxes`, the 8.26 GB/16-shard floor), (2) native parallel shard search (~max(shard) not sum — the 25.63 ms is a serial Python/PyO3 loop, harness not engine number), (3) re-enter the gate ladder at P3/G4 (end-to-end RRF NDCG@10 ±0.005) before any spin-off. **The honest read: the standalone idea is NOT dead — the format was the wall, not the algorithm — but it is not yet proven shippable.** |
| 2026-06-26 | **G3d (pruning sub-linearity) + G2b (inverted-side floor)** — the §4 follow-ons that gated the FORMAT-WALL re-open, now measured | G3d: `blocks_scored/num_blocks` worst-query ratio **0.950 @2.0M docs** vs **0.963 @0.93M docs** (stable across a 2.15× corpus jump); G2b: RssAnon **~334 B/doc** gc-persistent, ~0.67 GB/first 2M-doc shard, ~7.8 GB@persona / **~50 GB@150M** projection | ❌ **BOTH FAIL at the 150M target** | **The custom engine does NOT beat FOSS at the scale that justifies owning it — measured, not flagged.** G3d: since `num_blocks = docs/256` is linear in corpus, a *constant* worst-query ratio (~0.95) means `blocks_scored` is **linear in corpus too** — BMP's WAND-style pruning prunes almost nothing on real 64-term SPLADE queries (5/10 queries score ≥80% of all blocks; worst 95%). The 25.63 ms FORM-WALL win was zero-decode making scoring-everything cheap, **not algorithmic selectivity**; at 150M (~75×) that is ~557K block-scores/query vs 7.4K → the wall re-establishes at exactly the target scale. G2b: the forward-only cure is half-built — the inverted side (`documents: Vec<String>`, `range_maxes: Vec<PostingList>`, `kth_scores`) is `.to_vec()`'d and gc-persistent, ~50 GB at 150M, **~7.6× the Qdrant 6.55 GB floor the engine was built to replace.** Per-shard warm p50 ceiling **40 ms ≤ qdrant 66 ms** at persona (the format is fast enough at persona) but moot at 150M. **Verdict (gate-zero, `07_INTEGRATION_PLAN.md` §8): STOP the BMP line.** `immsparse` + FORMAT-WALL kept as a recorded research result; the thin client ships on Qdrant (already GREEN at persona). If 150M-single-collection ever becomes a hard requirement, the row-6 result says pivot to **SEISMIC** (its geometrically-cohesive blocks + summary vectors are *designed* to prune, validated at 138M) — not more BMP work. Eval: `spike/archive/mmap_bmp/measure_p3b_pruning.py` + `measure_p3a_inverted_floor.py` (zero-decode venv `/tmp/bmp-fork-work/zerodecode-venv`, existing persona shards, no rebuild). Results: `data/eval_results/p3b_pruning_persona.json`, `p3a_inverted_floor.json`. |
</content>
