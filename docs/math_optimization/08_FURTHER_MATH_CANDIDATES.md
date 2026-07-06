# 08 — Further math candidates (M6–M10): pre-registered, UNMEASURED

**Created 2026-07-05. Status: DESIGN ONLY / PRE-REGISTERED — every row
UNMEASURED unless it cites a result file.** This doc extends the M1–M5
interaction map (`03_INTERACTION_MAP.md`) with five additional restructurings
of the mmap-serving dot kernel
(`spike/vectorium_fork/src/encoders/dotvbyte_fixedu8.rs:603-642`), grounded in
external literature/ISA research done 2026-07-05 (sources at bottom). House
rules apply: every value estimate is `*est.*` until a result file exists;
Stage-0 Python pre-gate before any Rust edit (`05_TESTING_PROTOCOL.md`);
quality gates at **n=100 minimum** (the M2 n=40 lesson,
`07_M2_IMPLEMENTATION_RESULTS.md`); ISA rules of `04_ISA_PORTABILITY_RULES.md`
bind every candidate.

## Leverage map — where a kernel win actually lands (read first)

G8b (2026-07-04, `data/eval_results/g8b_fullcorpus_*.json`) measured
full-corpus parallel-federated warm p50 ≈ 65 ms while the single-shard warm
kernel traverse is ~2–3 ms (E7 Arm E1; E7b warm 3.3 ms). So at deploy scale
the kernel is **~a few percent of federated latency** — encode, fan-out, and
merge dominate. Kernel wins multiply only in three regimes:

1. **Sequential federation** (`SFU_SEISMIC_FEDERATION=sequential`): latency =
   Σ per-shard traverses, so a kernel speedup applies ~8×.
2. **Warm single-shard serving** (the E7b RAM-capped deploy shape, 3.3 ms
   p50): the kernel ≈ the whole cost.
3. **Throughput/energy per query** at any scale (batch eval, reindex-time
   scoring).

None of M6–M10 touches gate c (cold major faults) — the 00-doc correction
stands: page faults are a layout property (E5/M5 territory), not a math
property. Every candidate below is a **gate-b** (warm arithmetic) play except
where noted.

## The dotvbyte index DB — what each candidate assumes of it

All five candidates score against the **existing converted dotvbyte shard
DB** — the asset these changes must not casually invalidate:

- **Inventory (E7c, 2026-07-04):** all 8 shards file-level-converted
  f16→dotvbyte + the 8-shard dv manifest
  (`data/eval_results/e7c_convert_shards_20260704.log`); shard0 forward
  6.74→3.97 GB (1.70×). Measured serving footprint: **3.10 GiB warm working
  set per shard** (E7b), **25.23 GB VmRSS full corpus** (G8b). Promoted for
  RAM-constrained deploys (doc 10 §7.5). `seismic.MmapSeismicIndex`
  auto-dispatches to the dv reader — serving code never names the format.
- **On-disk record shape** (what the kernel decodes): per-doc self-contained
  blob = SVB-encoded u16 component-id **gap deltas** + FixedU8`<U6>` values
  (scale 1/64), **term-sorted within the blob**
  (`dotvbyte_fixedu8.rs:483-555`, sort at `:490-496`), addressed by a plain
  offsets array (`packed_dataset.rs:117-130`). Immutable, mmap'd, Rule Zero
  applies: kernels are read-only over it.
- **The isolation fact (03) extended:** M2b, M6, M7, M8 are
  query-evaluator-only — they change how the query side is represented
  (int-quantized query, membership bitmap, batch loop) and **serve the
  existing dv shards byte-for-byte as-is**; the doc side of the dot is
  untouched. Zero re-conversion, zero rebuild.
- **The dv format is itself an input to the candidates:** M7's intersection
  leg exists *because* the dv blob keeps component ids sorted — the sorted
  doc-side list comes free from the DB format. Conversely the SVB decode
  third exists *only* on the dv path — f16 shards skip it — so every kernel
  win here is a dv-DB win specifically; measure against dv twins, with the
  f16 shards as the control arm (the E7 discipline).
- **What would touch the DB:** only **M9's** 4-bit doc-value variant — that
  is a new dv format version requiring a full 8-shard re-conversion (an
  E7c-scale job) plus a fresh E6-style fidelity gate, which is a second
  independent reason it's ranked last. (It would also shrink the DB further —
  value bytes halve — `*est.*`, unquantified.) **M10** touches the f16 DB
  path only, not dv.

## Options at a glance (extends the 03 table; same columns)

| Change | Files touched | Shard rebuild? | ISA risk | Gate | Pre-gate needed |
|---|---|---|---|---|---|
| **M6. VNNI/UDOT hardware integer dot** (7-bit query, i32 accumulate) | `dotvbyte_fixedu8.rs:349-407, 603-642` (M2 plumbing reused) | No | **Medium — first candidate needing hand intrinsics on BOTH ISAs; twins exist** (`vpdpbusd` ↔ `UDOT`) | b | cpuid inventory + 7-bit quality at n=100 |
| **M7. Query-membership bitmap + intersection dot** (never gather a zero) | `dotvbyte_fixedu8.rs:379-390` (query build) + `:603-642` (kernel) | No | Low (`std::simd` masks / scalar bit tests) | b | E5-style Python lane-accounting sim |
| **M8. Batched multi-candidate scoring** (register blocking across a block's survivors) | `posting_list.rs:202-225` + evaluator API | No | Low (portable) | b (warm); cold *wall-clock* maybe, majflt count NO | none for quality (f32 semantics preserved) |
| **M9. Shuffle-LUT scoring** (Quicker ADC / FastScan lineage) | kernel + possibly doc-value width | Only if doc width changes | High (AVX512-VBMI x86 / NEON `TBL` — different shapes) | b | 4-bit doc fidelity (E6-style) — likely fails; SPECULATIVE |
| **M10. Native f16 arithmetic on the served f16 path** | the f16 evaluator (NOT dotvbyte) | No | Medium (AVX512-FP16 rare; NEON FP16 common) | b | profile: is convert even visible? UNVERIFIED premise |

Relationship to the existing map: **M6 is M2b's hardware end-state** (same
revival path 07 names, executed with the ISA's native instruction instead of
`std::simd` widening). **M7 is M1 taken to its logical conclusion** (move the
zero test *before* the gather instead of after it). **M8 is a mid-point
toward M5** that needs no format change. M9/M10 are ranked last and included
so they aren't re-derived from scratch later.

---

## M6 — VNNI/UDOT hardware integer dot (the M2b end-state)

**Mechanism.** M2 died on quality because 6-bit is the widest query that
single-stage `vpmaddubsw` i16 pair-sums tolerate (03 §M2 saturation math),
and 6-bit costs −0.007 overlap@10 (07). The saturation constraint is an
artifact of the *instruction*, not the math: both `vpdpbusd` (x86
AVX-VNNI / AVX512-VNNI) and `UDOT` (aarch64 ARMv8.2 `dotprod`) fuse 4
u8-pair products **directly into an i32/u32 accumulator with no saturating
i16 intermediate**. That buys:

- **7-bit query on x86** — `vpdpbusd` is unsigned×**signed** (doc u8 stays
  the unsigned operand; query as i8 caps at 127 = 7-bit). 7-bit scored
  **overlap@10 = 0.995 in the Stage-0 pre-gate** (n=40, un-saturated model,
  `06_PREGATE_RESULTS.md`) — above the 0.99 bar with margin, where 6-bit was
  exactly at the bar and failed at n=100.
- **8-bit query on ARM** — `UDOT` is unsigned×unsigned (both operands
  non-negative here: doc values ≥0 measured, query weights ≥0 for SPLADE),
  pre-gate 0.9975.
- One instruction replaces the whole convert+FMA third for 4 pairs/lane.

**Why this is a new ISA-risk class.** `std::simd` will not lower a widening
mul-accumulate to VNNI/UDOT (same class of gap as the `vpgatherdd`=0 defect,
`01_KERNEL_AND_MATH_MAP.md`). M6 therefore needs **hand intrinsics on both
targets** — but unlike M3 (NEON has no gather), *twins exist on both ISAs*,
so rule 2 of 04 (cfg-gated twin pattern) is satisfiable:
`core::arch::x86_64::_mm256_dpbusd_epi32` (avx512vnni+avx512vl; some VNNI
intrinsics stabilized in Rust 1.89, the rest nightly — we're on nightly
anyway) or `_mm256_dpbusd_avx_epi32` (AVXVNNI, no AVX-512 requirement) ↔
`vdotq_u32` (NEON dotprod). Scalar fallback mandatory as the third arm.

**Pre-gates (in order, cheapest first):**
1. **cpuid inventory** — does the dev container / host / DO droplet CPU
   report `avx_vnni` or `avx512_vnni` (`lscpu | grep vnni`), and does the ARM
   target report `asimddp`? *If no serving CPU has it, M6 is parked, zero
   code written.* UNMEASURED.
2. **7-bit quality at n=100** — rerun `m2_pregate_query_integer_dot.py` at
   7-bit with the n=100 query set (the model already exists; the n=40 0.995
   must survive the same enlargement that killed 6-bit's 0.99).
3. **M2b first** — the `std::simd` two-stage i32-widen (07's revival path,
   backlog row M2b) is the portable version of the same math. If M2b clears
   quality but its speed win is eaten by the widening shuffle overhead, M6
   is the targeted fix; they share the `SFU_SEISMIC_M2_INT6` plumbing and
   the kernel-match test harness.

**Footguns (add to the 03 checklist):**
- `vpdpbusd` operand order is load-bearing: **doc bytes = unsigned operand,
  query bytes = signed operand.** Swapped, doc values >127 (measured max 208
  in u8 scale) are reinterpreted negative and silently corrupt scores.
- Runtime dispatch (`is_x86_feature_detected!("avxvnni")`) — the .so must
  not SIGILL on the 2019-era dev container; compile-time-only gating via
  `target-cpu=native` stays env-only (04 rule 4).

**Value `*est.*`:** medium — the arithmetic third shrinks ~4×, but the
gather third (still scalar) remains; Amdahl caps the kernel win well below
4×. Elastic's simdvec int8 work (same instruction family) reports large
kernel-level speedups but on gather-free layouts.

---

## M7 — Query-membership bitmap + intersection dot (never gather a zero)

**Mechanism.** The measured waste is precise: **76.7% of gather lanes fetch
0.0** (06 — doc term not in query). M1 elides the FMA *after* paying the
gather; M7 moves the test **before** the gather:

1. Build once per query: a **membership bitmap** over the component space —
   dim 28,702 bits ≈ **3.6 KB, L1-resident** (vs the 115 KB dense f32 query
   table, which can only be L2). Optionally alongside: the query as a sorted
   `(u16 id, weight)` list, nnz ≤ 64 (02's measured cap; ~10 under
   query_cut=10).
2. In the kernel, after the SVB prefix-sum yields a pack of 8 absolute
   component ids (`:607`): test the 8 ids against the bitmap (portable:
   shift/mask per lane, or `std::simd` gather of 8 *bytes* from the 3.6 KB
   map — a gather that hits L1 instead of L2). All-miss packs (the common
   case if hits cluster) skip gather+convert+FMA entirely.
3. Hit lanes only: fetch the weight — from the dense table as today, or by
   SIMD intersection of the sorted id lists (doc blob ids are already
   term-sorted within a blob, `dotvbyte_fixedu8.rs:490-496`). Literature:
   for similar-size sorted lists (doc nnz ~88 vs query ≤64) Inoue's V1
   block intersection wins; galloping only wins at strongly skewed sizes
   (query_cut=10 regime) — both SIMD-friendly and portable.

**Why it can beat M1:** M1's own doc (03) ranks it lowest because the gather
is "already-cheap scalar" and only the FMA is saved. M7 saves the gather
itself *and* shrinks the query working set 32× (115 KB → 3.6 KB), which is a
cache-residency change, not just an instruction-count change.

**Pre-gate (Stage 0, container-side, zero Rust):** an E5-style Python
lane-accounting sim on real candidate sets — for each scored doc, the
distribution of **query-hits per 8-lane pack**. The decision rule mirrors
M1's caveat: 76.7% zero *lanes* is only an upper bound; if ≥1 hit lands in
nearly every pack, the skip rate collapses and M7 dies on paper. Bars
(pre-registered): all-miss-pack rate ≥ 0.5 → GO for a Rust spike; < 0.3 →
KILL (record and stop). Between: build only the bitmap-gather variant (which
wins on cache residency even with no packs skipped) and measure.

**Quality risk: none by construction** — f32 semantics unchanged; skipped
lanes contributed exactly 0.0. (Same class as M1: no gate-a exposure.)

**ISA risk: low** — `std::simd` masks + integer ops throughout; no hand
intrinsics needed. No shard rebuild; evaluator-only.

**Value `*est.*`:** medium-high for the warm kernel: removes up to ~77% of
thirds (b)+(c) work and moves the hot query structure into L1. The honest
unknown is the pack-level distribution — measured by the sim before any
Rust.

---

## M8 — Batched multi-candidate scoring (register blocking)

**Mechanism.** `evaluate_posting_block` scores a surviving block's
candidates strictly one at a time (`posting_list.rs:202` → `:225`
`evaluator.compute_distance(vector)` per doc). Standard GEMM register
blocking applied here: decode and score **4 candidates interleaved**, each
with its own `Simd<f32, 8>` accumulator, sharing one pass over the query
structures. Wins `*est.*`:

- The scalar gather's latency (the `vpgatherdd`=0 defect) is **hidden by
  memory-level parallelism** across 4 independent candidate streams instead
  of serializing per candidate.
- Query-table (or M7-bitmap) accesses amortize 4×.
- FMA ports fill: today's loop is dependency-chained on one accumulator.

**Quality: bit-identical by construction** — each candidate keeps its own
accumulator and per-candidate summation order; only the interleaving
changes. Stage-1 new≡old equality tests apply directly (unlike M2, no
kernel-match model needed).

**Gate c caveat (pre-registered so it isn't over-claimed):** interleaving
candidate blob fetches lets *cold* page faults overlap, which can improve
cold **wall-clock** — but gate c is a majflt **count** ratio and the count
is unchanged. Any cold improvement must be reported as wall-clock, never as
a gate-c reclear.

**Files:** `posting_list.rs` block loop + a `compute_distance_batch(&[range])`
on the evaluator; forward blobs still fetched individually
(`packed_dataset.rs:344-347`) — **no format change, no rebuild**. This is
the largest structural step available **without** M5's single-home-cluster
blocker.

**Pre-gate:** none required for quality; a 20-line criterion check first —
instrument the survivors-per-block distribution (if the typical surviving
block contributes 1–2 candidates, there is nothing to batch and M8 dies on
paper; blocks are 64-doc clusters, so `*est.*` batch of 4–16 is usually
available, UNMEASURED).

**ISA risk: low** (pure `std::simd` restructuring). **Value `*est.*`:**
medium; precedents (SimSIMD batch APIs, Elastic simdvec bulk scoring) put
2–4× kernel-level for gather-latency-bound loops, Amdahl-capped here as
always by the decode third.

---

## M9 — Shuffle-LUT scoring (Quicker ADC / FastScan lineage) — SPECULATIVE, ranked last

**Mechanism (what the literature actually does):** PQ fast-scan (Quick ADC →
Quicker ADC → Faiss `PQFastScan`) replaces gather+arithmetic with in-register
`pshufb` lookups: 4-bit codes index a 16-entry table of **precomputed
per-subspace distances**, 16–32 lookups per instruction.

**Why the fit is poor here (recorded so it isn't re-derived):** the LUT wins
in PQ because the table encodes an *arbitrary function* (subspace distance).
Our per-term contribution is separable — `q[c] · d` — and the multiply is
already a single FMA lane; a per-term product LUT would have to be selected
per component id, which **reintroduces exactly the gather M7 kills**. The
only shape with any value: replace `simd_fixedu8_to_f32` (`:697-702`, cast +
`× 1/64`) with a 64-entry dequant LUT via AVX512-VBMI `vpermb` / NEON
`vqtbl4q` — saving one convert per pack. Marginal `*est.*`, and it would
need doc values requantized to ≤6-bit lookup granularity we already have.

**If ever pursued:** the pre-gate is an E6-style fidelity run at 4-bit doc
values (16-entry tables) — `*est.*` FAIL given U6 (64-level) was already the
chosen fidelity point at 0.995. **ISA note:** contrary to the usual pattern,
ARM is the *stronger* target here (`TBL` does 64-byte in-register lookups
natively; x86 needs AVX512-VBMI, absent on most consumer parts). Parked
unless M6+M7 both land and the kernel is still hot.

---

## M10 — Native f16 arithmetic on the served f16 path — premise UNVERIFIED

The f16 forward (the format actually served today) skips the decode third
but `*est.*` upconverts f16→f32 before the FMA. AVX512-FP16
(Sapphire-Rapids+) and NEON FEAT_FP16 can FMA in half precision at 2× lane
width, or at minimum `vcvtph2ps` batching can shrink convert cost.

- **Premise to verify first** (grounding task, not a build task): objdump
  the shipped .so for `vcvtph2ps` counts and read the f16 evaluator the way
  01 reads the dotvbyte one. This doc deliberately does NOT cite line
  numbers for the f16 path — they haven't been mapped; mapping them is the
  first step.
- **Precision footgun:** accumulate must stay f32 (f16 accumulation loses
  ~3 decimal digits over nnz≈88 sums) — so only the convert+width win is
  real, not a full-half-precision pipeline.
- **Leverage:** the f16 path is the one whose kernel is already
  gate-b-GREEN by 0.957 — this is a throughput/energy candidate only.
  Ranked last with M9.

---

## Recommended order (the decision, not just the menu)

> **AMENDED 2026-07-05, same day (post-G8d, doc 10 §7.6):** G8d measured the
> dv parity budget as nearly spent — corpus mean 0.9906 vs f16, shards 1–2 at
> 0.985, accepted as marginal. That demotes the lossy candidates (M2b, M6 add
> query-quantization loss on top of an already-marginal parity) and promotes
> the quality-free ones. **The executing order is now M7 sim → M8 instrument
> → M2b → M6**, with M2b/M6 quality gates on shards 1–2 at n=100 (05's
> worst-case-shard rule), and the quality-*recovery* lever E8 (dv-v2 per-doc
> scale, `seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md`) ahead of all of
> them. Recipes: `seismic_150m_testbed/12_EXECUTION_ROADMAP.md`. The original
> order below stands as the pre-G8d record.

1. **M2b** (backlog row, `std::simd` i32-widen, 7-bit) — cheapest, reuses
   everything M2 built, and its quality answer gates M6 too.
2. **M7 Stage-0 sim** (container-side, zero Rust) — the only candidate that
   attacks the measured 76.7% waste at its source; sim decides GO/KILL.
3. **M8 survivors-per-block instrument, then build if ≥4** — quality-free
   risk profile makes it the safest actual Rust change.
4. **M6** — only after M2b's quality verdict and a positive cpuid inventory.
5. **M9 / M10** — parked; premises recorded above so they aren't re-derived.

Every result lands here + `11_EXPERIMENT_BACKLOG.md` (Tier 3 rows added
2026-07-05) with result-file paths and absolute dates, per the recording
rules. A row without numbers stays UNMEASURED.

## Sources (external research, accessed 2026-07-05)

- VNNI `vpdpbusd` semantics (u8×i8 → i32, non-saturating; replaces the
  `vpmaddubsw`+`vpmaddwd`+`vpaddd` sequence):
  [Intel DL Boost guide](https://www.intel.com/content/www/us/en/developer/articles/guide/deep-learning-with-avx512-and-dl-boost.html),
  [Grokipedia AVX overview](https://grokipedia.com/page/Advanced_Vector_Extensions)
- Rust intrinsic status (`_mm256_dpbusd_epi32` avx512vnni+avx512vl,
  partial stabilization in 1.89; `_mm256_dpbusd_avx_epi32` for AVXVNNI):
  [doc.rust-lang.org](https://doc.rust-lang.org/core/arch/x86_64/fn._mm256_dpbusd_epi32.html),
  [AVX512 tracking issue #111137](https://github.com/rust-lang/rust/issues/111137)
- ARM `UDOT`/`SDOT` (ARMv8.2 `dotprod`, u8×u8 4-pair → 32-bit accumulate;
  i8mm `SMMLA`/`UMMLA` at 8.6):
  [Arm dot-product blog](https://developer.arm.com/community/arm-community-blogs/b/tools-software-ides-blog/posts/exploring-the-arm-dot-product-instructions),
  [NEON intrinsics reference](https://arm-software.github.io/acle/neon_intrinsics/advsimd.html)
- Int8 SIMD scoring precedent in a search engine:
  [Elasticsearch simdvec (6× kernel speedup)](https://www.elastic.co/search-labs/blog/vector-search-simd-optimization-simdvec),
  [SimSIMD](https://github.com/ashvardanian/SimSIMD)
- Shuffle-LUT scoring lineage:
  [Quicker ADC paper (arXiv:1812.09162)](https://arxiv.org/abs/1812.09162),
  [faiss-quickeradc](https://github.com/technicolor-research/faiss-quickeradc)
- SIMD sorted-set intersection (V1 for similar sizes, galloping for skewed):
  [Inoue et al., VLDB'15](http://www.vldb.org/pvldb/vol8/p293-inoue.pdf),
  [Lemire, SIMD compression & intersection](https://arxiv.org/pdf/1401.6399),
  [Lemire blog](https://lemire.me/blog/2015/03/25/accelerating-intersections-with-simd-instructions/)
