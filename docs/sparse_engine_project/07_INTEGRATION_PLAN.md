# 07 · Custom Engine Integration Plan (v2 — post zero-decode)

**Status:** RESOLVED → STOP (2026-06-26, post-measurement). Supersedes
`02_IMPLEMENTATION_PLAN.md` as the forward path. `02` is retained as the historical
P0→P2 record. **Posture: measured and killed.** The zero-decode tiebreaker flipped
P2's G3a kill to **FORMAT-WALL** on a 4-shard subset, provisionally re-opening the
standalone `immsparse` engine — but the three open ledger rows (§2: 4, 5, 6) that
gating required have now been **measured** (not flagged), and **rows 4 and 6 fail
the 150M target the build exists for.** The custom engine does not beat FOSS at
scale; the thin client ships on Qdrant. §8 has the verdict; this doc is retained as
the decision record so the question is not re-litigated on another curiosity budget.

> **Read first:** `03_GO_NO_GO_GATES.md` (the numbers), `06_NEXT_STEPS_ZERO_DECODE.md`
> (the tiebreaker that produced this re-open), `WHY_NO_FOSS.md` (the build-vs-buy
> framing). This doc assumes those.

---

## 1. What changed (the one number that re-opened this)

The P2 kill (2026-06-26, `02`/`03`) said warm p50 696 ms ≫ qdrant 66 ms → the mmap
sparse path is too slow to serve. The zero-decode re-test proved that wall was the
**R3-v1 compact on-disk format** (which decodes every block per query), not BMP's
Block-Max algorithm:

| Build | Forward index on access | warm p50 (4-shard med_bio) | anon | Verdict |
|---|---|---|---|---|
| Stock BMP (load-into-RAM) | decoded, **resident** | 4.67 ms (1M) | 1.98 GB | fast, but RAM floor ❌ |
| **R3-v1** flat (mmap + decode-per-query) | compact, **re-decoded** | **696 ms** | 1.98 GB/4sh | the false kill |
| **R3-v2** zero-decode (`bytemuck::cast_slice`) | POD, **read in place** | **25.63 ms** ✅ | 1.976 GB/4sh | **FORMAT-WALL** |

R3-v2 re-laid the forward region as `#[repr(C)]` POD (`FlatPair{doc_off:u8,score:u8}`
+ `TermEntry`), read via `bytemuck::cast_slice` over the mmap (zero decode, zero
alloc), scored with `flat_block_score` (a faithful twin of `block_score`, so the
stock path stays byte-identical). **G1 held 50/50 @1M + 40/40 @persona.**
Result: `data/eval_results/p2_zerodecode_med_bio_4shard.json`. Patch:
`spike/archive/mmap_bmp/R3v2_delta.patch`.

**Net (revised post-measurement 2026-06-26):** the format-wall was real and the
forward-side cure works — *mmap cures the forward RAM floor* and *mmap-BMP can serve
at ~stock speed on a 4-shard subset.* But "won in principle" overstated it: the two
remaining bets (pruning sub-linearity at scale, and a *complete* RAM cure) are now
**measured and lost (§2 rows 4 & 6)**. The 4-shard subset hid both: a small corpus
makes scoring-most-blocks cheap enough, and the inverted-side floor only becomes
~50 GB at 150M.

---

## 2. The honest ledger — what is proven vs. what is NOT

A latency PASS on a 4-shard subset is **necessary, not sufficient.** The three
OPEN rows (4, 5, 6) are now **MEASURED (2026-06-26)**, not flagged — see the
`data/eval_results/p3a_*` / `p3b_*` results and the eval scripts under
`spike/archive/mmap_bmp/measure_p3{a,b}_*.py`. **Result: rows 4 and 6 FAIL the 150M
target the build exists for. The table does not go all-green; the build does
not beat FOSS at scale.**

| # | Claim | Status | Evidence / gap |
|---|---|---|---|
| 1 | Forward index can be served zero-decode at ~stock speed | ✅ proven | 25.63 ms warm p50, 4-shard med_bio |
| 2 | Top-k stays byte-identical (quality preserved) | ✅ proven | G1 50/50 @1M + 40/40 @persona |
| 3 | Cold ≈ warm (mmap locality holds) | ✅ proven | G3b cold/warm 1.49 (≤3×) |
| 4 | **Anon floor is actually cured at scale** | ❌ **FAIL at scale (measured)** | R3 cured only the *forward* side; the *inverted* side (`documents`, `range_maxes`, `kth_scores`) is `.to_vec()`'d. **Measured 2026-06-26**: ~334 B/doc, gc-persistent (resident anon, not page cache). Projects to ~7.8 GB at 16-shard persona (matches the recorded 8.26 GB ref) and **~50 GB at 150M — ~7.6× WORSE than Qdrant's 6.55 GB floor this engine was built to cure.** The forward-only cure is half-built; P3a (offset-index `documents` + mmap `range_maxes`/`kth_scores`) is mandatory. Eval: `data/eval_results/p3a_inverted_floor.json`, script `spike/archive/mmap_bmp/measure_p3a_inverted_floor.py`. |
| 5 | **Engine-level latency at full scale** | ⚠️ persona-scale PASS, 150M moot (measured) | Per-shard warm p50 ceiling **40 ms ≤ qdrant 66 ms** — the *format* is fast enough at persona. But 25.63 ms was a *serial PyO3 loop* over **4 v2 shards only** (12 of 16 persona shards are v1 and were never transcoded). At 150M the outcome is dominated by row 6 regardless of thread count: a linear block-count means even `max(shard)` parallelism scores ~const-fraction of a much larger shard. Eval: `data/eval_results/p3b_pruning_persona.json`. |
| 6 | **Pruning stays sub-linear at 150M** | ❌ **FAIL — linear in corpus (measured)** | **Measured 2026-06-26**: `blocks_scored/num_blocks` worst-query ratio is **stable ~0.95–0.96 across a 2.15× corpus jump** (928K→2.0M docs). `num_blocks = docs/256` is linear in corpus, so a constant ratio ⇒ `blocks_scored` is linear in corpus too. BMP's WAND pruning prunes almost nothing on 64-term SPLADE queries (5/10 queries score ≥80% of all blocks; worst **95%**). The 25.63 ms win exists *because* zero-decode made scoring-everything cheap, **not** because the algorithm is selective. At 150M (~75×) that's ~557K block-scores/query vs 7.4K — the wall re-establishes. Eval: `data/eval_results/p3b_pruning_persona.json`, script `spike/archive/mmap_bmp/measure_p3b_pruning.py`. |

**Plain reading (updated):** the format-wall was real (row 1 ✅) and the cure
works on the forward side — but the two questions the plan said must be answered
before spending effort are **both now answered, both NO**: the algorithm's
pruning is **not** sub-linear (row 6), and the RAM cure is **not** complete at
scale (row 4 projects to ~50 GB at 150M, worse than the Qdrant floor it replaces).
The custom engine does **not** beat FOSS at the 150M scale that is the entire
reason to own it. Do **not** report this as "the engine works."

---

## 3. Gate-zero (was: re-affirm BEFORE spending P3 effort) — DECIDED STOP

`WHY_NO_FOSS.md` (Risk R7) says a custom engine is only worth owning if **no-JVM +
embeddable-as-a-library + our exact measured quality recipe** beats *not maintaining
code.* The tiebreaker session answered gate-zero **YES** on a curiosity budget — but
that was always conditional on the P3a/P3b gates (§2 rows 4 & 6) going green. They did
not (both measured FAIL at the 150M target, §2), so gate-zero is re-decided **STOP**
below. The build-vs-FOSS framing is retained as the decision record:

**Arguments the build is still right**
- The floor disease is real and structural: Qdrant's mutable/MVCC per-point anon
  (~43 B/pt → 6.55 GB at 150M, *rising*) is the documented 150M root cause
  (`qdrant_vs_lucene_assessment/`). Immutable mmap segments cure it by construction.
- Our intersection (no-JVM + immutable-distributable + indexed-learned-sparse +
  unified + 150M-static) is still genuinely empty in FOSS (`WHY_NO_FOSS.md`).
- The thin-client/laptop tier *needs* no-JVM; OpenSearch+SEISMIC (the closest mature
  cure) is JVM, and Infinity is a whole new C++ DB to migrate to, not embeddable.

**Arguments to NOT build (weigh these honestly — they got stronger since the kill)**
- **The thin client does not need this engine at all.** At persona scale Qdrant is
  already GREEN (66 ms, 30M-fits tier). The ownership case is *strictly* the
  full-150M-single-collection floor (`DECISION_TRAIL.md` step 10) — a server problem,
  not the product we ship.
- **Maintenance is the real cost, not the build.** Industry norm is ~15–20% of build
  cost per year in perpetuity ([build-vs-buy 2025](https://hatchworks.com/blog/software-development/build-vs-buy/),
  [Appinventiv](https://appinventiv.com/blog/build-vs-buy-software/)). For us that's
  per-arch maturin wheels, a PyO3 boundary, and tracking BMP upstream forever — for a
  research codebase that was never meant to be productionized.
- **The empty intersection is filling.** Since the assessment: Chroma shipped
  first-class [sparse/SPLADE vectors](https://www.trychroma.com/project/sparse-vector-search);
  Qdrant added `on_disk` mmap sparse + [immutable-segment RAM cuts](https://github.com/qdrant/qdrant/releases)
  (e.g. 7× immutable geo index in 2025; [400M vectors on 64 GB](https://qdrant.tech/documentation/tutorials-operations/large-scale-search/));
  tantivy continues sparse-index work; LanceDB #1930 (sparse index) is in progress.
  **Building a bespoke engine that a maturing FOSS project ships in 12 months is the
  classic build-vs-buy trap.**

**Decision recorded 2026-06-26 (post-measurement): STOP — do not build.**
Rows 4 and 6 are now measured (§2), not flagged, and **both fail the 150M target
the build exists for**: the RAM "cure" projects to ~50 GB at 150M (~7.6× the
Qdrant 6.55 GB floor it replaces), and BMP's pruning is linear in corpus
(scores ~95% of all blocks in the worst query, *not* selective). The forward-side
FORMAT-WALL win is real but insufficient — it lowered per-block cost without
removing the O(corpus) block count or the inverted-side floor. Keeping `immsparse`
as a proven research result (FORMAT-WALL documented); shipping the thin client on
Qdrant, which is already GREEN at persona (66 ms) and whose only structural
disease is a *mutable/MVCC* floor that this immutable approach was meant to beat
but, measured, does not. If 150M-single-collection ever becomes a hard
requirement, the measured row-6 result says **pivot to SEISMIC (§4.3)** — whose
geometrically-cohesive blocks + summary vectors are *designed* to prune and were
validated at 138M (our scale) — not more BMP work.

- *"Fallbacks are fine / ecosystem will cover it"* → **DECIDED (this branch).** Keep
  `immsparse` as a proven research result (FORMAT-WALL documented) and ship the thin
  client on Qdrant; revisit only if 150M-single-collection becomes a hard requirement.
- *"No-JVM + embeddable + exact recipe is worth owning code"* → **rejected by
  measurement.** P3a/P3b (the §4 gating prerequisites) both FAIL at the 150M target,
  so the premise ("beats not maintaining code") does not hold even before the
  maintenance/packaging cost (§4.5). Do NOT proceed to §5.

---

## 4. What to consider before going forward (research-grounded)

These are the things that, if ignored, sink the project after real effort is spent.

### 4.1 The pruning confound is the #1 technical risk (not RAM, not decode)
blocks-scored max 7424 ≈ full block count means BMP's WAND-style pruning is **not
pruning** on this corpus/query mix — it scores nearly every block. The 25.63 ms win
exists *because* zero-decode made scoring-everything cheap, **not because the
algorithm is selective.** At 150M (≈6× the persona shard count, larger shards) this
is the term most likely to re-establish a latency wall. **Before any MVP, run the
blocks-scored-vs-corpus-size curve** (P3b) — if it's linear in corpus, the standalone
build is in trouble regardless of decode.

### 4.2 There is published work on exactly our forward-index tradeoff — read it first
Our whole tiebreaker was "compact-but-decode" vs "POD-but-larger" for the forward
index. That is a studied problem:
[**Forward Index Compression for Learned Sparse Retrieval** (arXiv 2602.05445)](https://arxiv.org/html/2602.05445).
Before we commit to our hand-rolled `#[repr(C)]` layout as the on-disk format, check
whether a published scheme gives most of the speed at a fraction of the disk cost
(G3c is currently a *win* at 0.75–0.79× bincode, but the POD layout spends that
headroom — know what state-of-the-art does before freezing the format).

### 4.3 If we're going bespoke, is BMP even the right base? — SEISMIC
[**SEISMIC** (arXiv 2404.18812, SIGIR'24)](https://arxiv.org/abs/2404.18812) reports
**sub-millisecond single-thread** on MS-MARCO SPLADE — 1–2 orders faster than
inverted-index methods — and was **evaluated on 138M MS-MARCO-v2 passages**, i.e. our
exact scale. Its geometrically-cohesive blocks + summary vectors are *designed* to
prune (directly addressing §4.1's confound), and the summaries are more mmap-amenable.
Caveat: still load-into-RAM by research design, so the *same* decode-vs-resident /
inverted-side-mmap questions apply. **But if the BMP pruning confound (§4.1) proves
fatal, SEISMIC — not more BMP work — is the pivot.** A 2025
[scalability paper](https://arxiv.org/html/2501.11628v1) and
[dynamic superblock pruning](https://arxiv.org/pdf/2504.17045) extend it for massive
corpora.

### 4.4 The inverted-side mmap is unglamorous but mandatory
Row 4 of the ledger. The "cure" only cured the forward index. A true zero-anon engine
must offset-index `documents` (one String per doc — 23.4M of them at persona scale)
and mmap `range_maxes`/`kth_scores`. This is more invasive than the spike's budget and
is **the literal point of the project** (kill the floor). It is P3a, and it is HARD.

### 4.5 Maintenance/packaging reality
Per-arch maturin wheels (the engine is a PyO3 extension), a CI matrix, and keeping the
fork rebased on upstream BMP. None is hard individually; together they're the ~15–20%/yr
that the build-vs-buy literature says people underestimate. Budget it explicitly or
don't start.

---

## 5. The rewritten phased plan (re-enter the gate ladder)

`02`'s P0–P2 stand as done. The path forward inserts **P3a/P3b/P3c as gating
prerequisites** (retire the three open ledger rows) *before* the spin-off, then the
original P3–P5.

| Phase | Deliverable | Exit gate | Where | ~Effort |
|---|---|---|---|---|
| **P2.5 · Tiebreaker** | zero-decode R3-v2 forward layout | **FORMAT-WALL** (warm p50 ≤ 66 ms, G1 identical) | here | ✅ DONE 2026-06-26 |
| **P3a-evidence · Inverted-side floor** | measure the inverted-side anon floor (no impl) — is the forward-only cure sufficient? | **G2b** RssAnon flat-in-corpus on 16 persona shards (≪ 8.26 GB) | here | ✅ **MEASURED 2026-06-26 → FAIL**: ~334 B/doc, ~7.8 GB@persona / ~50 GB@150M (≫ Qdrant 6.55). Full P3a impl **not built** — its evidence pre-empted it. |
| **P3b · Pruning + parallel reality** | blocks-scored-vs-corpus curve; native multi-thread shard merge | **G3d** blocks-scored grows **sub-linearly** in corpus AND engine-level warm p50 ≤ 66 ms (full persona) | here | ✅ **MEASURED 2026-06-26 → FAIL**: pruning is *linear* in corpus (worst-query ratio ~0.95 stable across 2.15× scale). Native threads never added — moot given the linear block count. |
| **P3c · 150M projection** | extrapolate G2b + G3d to 150M | projected 150M RAM flat + latency ≤ budget; **no linear blow-up** | here | ❌ **FAIL (projected from P3a/P3b evidence)**: ~50 GB RAM + ~557K block-scores/query at 150M. |
| **— RE-AFFIRM SPIN-OFF —** | gate-zero (§3) decided **with P3a/b/c numbers in hand** | all of P3a/b/c green AND gate-zero = BUILD → new repo; else **stop, keep findings** | — | ✅ **DECIDED 2026-06-26 → STOP.** P3a/P3b measured-fail ⇒ gate-zero = keep findings, ship on Qdrant. |
| ~~P3 · Engine MVP~~ | ~`immsparse` lib: mmap loader + per-section build + serving + degrade-to-BM25F~ | ~~G4 section RRF NDCG@10 within ±0.005~~ | ~~spun-off repo~~ | ⛔ not reached |
| ~~P4 · 150M validation~~ | ~full-150M `.bmflat` served via mmap, OOM-safe~ | ~~G5a anon flat/~0 at 150M; G5b B1/B2 parity; G5c latency-vs-RAM ≥ Qdrant~ | ~~spun-off repo~~ | ⛔ not reached |
| ~~P5 · Productionize / (opt) unify~~ | ~per-arch maturin wheels; hot/cold packaging; (opt) Lance substrate~ | ~~G6 reproducible build; G7 (opt) one Lance store~ | ~~spun-off repo~~ | ⛔ not reached |

**Kill criteria for the new phases — BOTH TRIPPED (2026-06-26)**
- **P3a fails** (inverted-side still scales with corpus) → the floor isn't really
  cured; mmap-BMP is a partial win only → fall back (the thin client never needed it).
  **✓ TRIPPED (measured): ~334 B/doc → ~50 GB at 150M, ~7.6× the Qdrant floor.**
- **P3b fails** (blocks-scored linear in corpus, or parallel warm p50 > 66 ms at full
  persona) → BMP's pruning is the wall after all → **pivot to SEISMIC (§4.3) or kill.**
  This is the most likely failure and the cheapest to find out — do it first after P3a.
  **✓ TRIPPED (measured): worst-query ratio ~0.95 stable across a 2.15× corpus jump ⇒
  linear in corpus. Per-shard latency stayed ≤ 66 ms (persona), but that is moot at 150M
  where the linear block count dominates. → Per §8: kill the BMP line now; SEISMIC is
  the pivot IF 150M-single-collection ever becomes a hard requirement.**
- **P3c fails** (150M projection blows the RAM or latency budget) → standalone doesn't
  reach the target scale → kill; OpenSearch+SEISMIC (JVM) is the server answer.
  **✓ TRIPPED (projection): ~50 GB RAM + ~557K block-scores/query at 150M.**

---

## 6. Integration specifics (how `immsparse` wires into the current stack)

Unchanged from `01_ARCHITECTURE.md`; restated as the concrete integration contract so
the MVP (P3) is a drop-in, not a rewrite.

- **Backend gate:** add `immsparse` next to `qdrant`/`bmp` behind `SFU_SPLADE_BACKEND`.
  `_load()` mmaps the `.bmflat` (R3-v2 layout) shards per section. No retriever-interface
  change; the fusion/rerank path (RRF k=60 + cross-encoder) is untouched.
- **Build path:** corpus → stored SPLADE `sparse_field` (no re-encode) → BMP b256
  clustered builder (`builder.py`, already have it) → R3-v2 `.bmflat` transcode
  (`spike/archive/mmap_bmp/` flat writer). Per-section, so it slots into the existing hot/cold
  persona packaging with no new build stage.
- **Quality invariant:** quantization (×70 8-bit), alpha/beta (0.8/1.0), top-64 query
  terms, RRF k=60 all stay identical — which is why G4 is an end-to-end RRF check and
  G1 is byte-identical, not a re-eval. The engine changes *where bytes live*, not *what
  is computed*.
- **Degrade-to-BM25F:** the serving contract must keep the existing fallback when the
  sparse leg is unavailable; verified in P3 (G4 line).
- **Tiers:** server = full 150M (all sections mmap'd, ~0 floor); local = per-persona hot
  section (`.bmflat`) — **same engine, same artifact format.**

---

## 7. Updated gate table (additions to `03_GO_NO_GO_GATES.md`)

New/changed gates introduced by this plan. Fold these into `03` when P3a starts.

| Gate | Phase | Type | PASS condition | Status |
|---|---|---|---|---|
| **G3a Warm latency** | P2.5 | HARD | warm p50 ≤ qdrant 66 ms, zero-decode | ✅ PASS (provisional, 4-shard) 2026-06-26 |
| **G2b Inverted-side RAM** | P3a | HARD | RssAnon flat-in-corpus on all 16 persona shards (≪ 8.26 GB) | ❌ **FAIL (evidence measured 2026-06-26)** — forward-only cure is half-built; ~334 B/doc gc-persistent proxies to ~50 GB at 150M (≫ 8.26, ≫ Qdrant 6.55). P3a implementation never built; its evidence pre-empted it. |
| **G3d Pruning + parallel** | P3b | HARD | blocks-scored sub-linear in corpus AND native parallel warm p50 ≤ 66 ms (full persona) | ❌ **FAIL — pruning is linear (measured 2026-06-26)** — worst-query `blocks_scored/num_blocks` stable ~0.95 across a 2.15× corpus jump ⇒ linear in corpus. Per-shard warm p50 ceiling 40 ms ≤ 66 at persona is PASS but moot (150M dominated by the linear block count). |
| **G3e 150M projection** | P3c | SIGNAL→HARD | extrapolated 150M RAM flat + latency ≤ budget; no linear blow-up | ❌ **FAIL (projection from P3a/P3b evidence)** — ~50 GB RAM (row 4) + ~557K block-scores/query (row 6) at 150M. |
| G4 / G5a / G5b / G5c / G6 / G7 | P3–P5 | per `03` | unchanged | ⛔ **not reached** — gate-zero re-decided STOP at P3a/P3b |

---

## 8. Recommendation

**Measured verdict: STOP the BMP build. It does not beat FOSS at the scale that
justifies owning it.** P3b (pruning) and P3a-evidence (inverted-side floor) were
run in the cheapest-kill order this doc prescribed, and both killed it:

- **Row 6 (P3b) = FAIL.** `blocks_scored/num_blocks` is a *constant* ~0.95 worst-query
  ratio across a 2.15× corpus jump ⇒ blocks-scored is **linear in corpus**, not
  sub-linear. BMP's WAND pruning prunes almost nothing on real 64-term SPLADE
  queries; the 25.63 ms win was zero-decode making scoring-everything cheap, not
  selectivity. At 150M that is ~557K block-scores/query — the wall re-establishes at
  exactly the scale the build targets.
- **Row 4 (P3a-evidence) = FAIL at scale.** The forward-only cure leaves the
  inverted side `documents`/`range_maxes`/`kth_scores` materialized: ~334 B/doc,
  gc-persistent, projecting to **~50 GB at 150M — ~7.6× the Qdrant 6.55 GB floor**
  the engine was built to replace. The cure is half-built; even completing P3a would
  not rescue row 6's linear block-scoring.

Both failures are at the 150M-target scale (persona/persona-subset numbers stay
green, which is exactly why the 4-shard subset mislead). The thin client ships on
**Qdrant** — already GREEN at persona (66 ms), and the BMP line offers nothing
Qdrant doesn't at the scale that matters.

**If 150M-single-collection becomes a hard requirement later, do NOT resume BMP.**
Row 6 says the algorithm is the wall after all → pivot straight to **SEISMIC (§4.3)**,
whose geometrically-cohesive blocks + summary vectors are *designed* to prune and
were validated on 138M MS-MARCO-v2 (our scale); bring the same zero-decode/inverted-
side-mmap questions to it then. Until then: keep `immsparse` + FORMAT-WALL as a
recorded research result, ship on Qdrant, and let the maturing FOSS ecosystem
(Chroma sparse, Qdrant `on_disk` mmap + immutable segments, LanceDB #1930) keep
filling the gap §3 flags rather than racing it with bespoke code.

---

*Provenance: this plan supersedes the forward-looking parts of `02`. Findings on
branch `spike/mmap-bmp` (fast-forwarded from the zero-decode tiebreaker, commit
0734404). Results: `data/eval_results/p2_zerodecode_med_bio_4shard.json`,
`p2_zerodecode_G1_1m.json`. Repro: `spike/archive/mmap_bmp/R3v2_delta.patch` +
`spike/archive/mmap_bmp/compare_zerodecode_persona.py`.*
