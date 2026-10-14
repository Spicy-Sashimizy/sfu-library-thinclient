# 00 — Context and corrections to earlier framing

**Status:** DEFERRED 2026-09-25 (M2 measured but NOT promoted - it failed its pre-registered bar; M6-M10 pre-registered and unfrozen)

## What this arc is

The **SEISMIC dot-kernel math optimization arc**: a research track asking
whether we can change *how the per-candidate dot-product math is processed* —
and optimize it for our specific corpus's measured properties — rather than
accepting the generic engine's arithmetic.

This is downstream of the mmap-serving work
(`docs/seismic_150m_testbed/`, gates E6/E7/C2.5). The mmap reader is shipped
and serving. The question here is purely about the **scoring kernel** that runs
on the candidates the mmap path surfaces.

## Three corrections to the earlier-session framing

Recorded so the framing doesn't drift back.

### Correction 1 — the math gate is already GREEN

Earlier framing: "the failed 22% is pure matrix-math cost."

**Corrected:** the math gate (gate b) **PASSED on 2026-07-03** via the free
native rebuild — `warm_p50_ratio = 0.957` (bar ≤1.07), dotvbyte warm p50
1.995 ms versus f16 baseline 2.084 ms (dotvbyte is now *faster* than f16).
See `data/eval_results/seismic_e7_RECLEAR_VERDICT.json`
(`final_same_footing_verdict_2026-07-03`, pinned to deliverable Arm E1).

The gate that is actually **red** is **gate c**: `majflt_cold_ratio = 0.591`
pre-registered / **0.560 fully calibrated** (bar ≤0.55; the Fix #4+#5B floor
prefault strips the posting-list + doc-mapping + forward-offsets constants
that fault identically for both codecs — see
`docs/seismic_150m_testbed/10_FORWARD_COMPRESSION_DESIGN.md` §7.3–§7.4,
2026-07-03). Gate c is a **cold major-page-fault / RAM-structural** property,
*not* a per-candidate math property. **No dot-kernel change touches gate c**
(confirmed empirically: both kernel-advice levers — `MADV_RANDOM` (Fix #2)
and `MADV_WILLNEED` (Fix #3) — were refuted 2026-07-03, and so was
**page-aligned record placement** (Fix #5A, +2% faults: kernel readahead
already absorbs straddle continuations); the verdict states gate c "appears
to be a STRUCTURAL floor of the forward reading pattern, not a tunable
advice axis"). The decisive open experiment is **E7b**, packaged for the
host: `scripts/seismic_testbed/HOST_PROMPT_E7B_RAMCAP.md`.

So: the math arc **cannot** fix the currently-failing gate. Its value is
upside on gate b at real 150M load (where the 929k-warm 0.957 number may not
hold under I/O-bound regimes) and on the two measured defects the native
rebuild did *not* close (see `01_KERNEL_AND_MATH_MAP.md`: the gather stays
scalar; f32 width persists).

### Correction 2 — the kernel is portable-SIMD, not hand-written AVX

Earlier framing implied the kernel used hand-written x86 intrinsics.

**Corrected:** `DotVbyteFixedu8::dot_product`
(`spike/vectorium_fork/src/encoders/dotvbyte_fixedu8.rs:603-642`) uses
`std::simd` calls (`Simd::gather_select_unchecked`, `mul_add`, `reduce_sum`)
that LLVM lowers per-target. The *only* explicit x86 intrinsic in the whole
crate is `avx2_pshufb` in `swizzle.rs:130-134`, dual-guarded
`#[cfg(target_arch="x86"/"x86_64")]` + `#[target_feature(enable="avx2")]` — it
**compiles out on aarch64** and falls through to a scalar `match N` arm.

Implication for any math change: **prefer `std::simd` over `core::arch`** so
the codebase stays cross-ISA by construction. This is the central portability
discipline (`04_…md`). Writing a hand-`vpmaddubsw` kernel without an aarch64
twin would **lock the codebase to x86** and silently kill the iPhone/ARM
target — the exact failure mode the user flagged as a concern.

### Correction 3 — two cited stats were overreaches

Earlier framing asserted "~7% query/doc overlap" and "~90% zero FMA lanes."

**Corrected:**
- "~88 terms/doc" is **real** — E6 phase A on shard0 (18.8M docs): nnz mean =
  87.6 (p50 82, p99 255). Source:
  `data/eval_results/seismic_e6_forward_codec_proto_20260702_2346.json`
  → `phase_a_stats`.
- "~7% overlap" is **not a code/repo-cited figure.** The "~7%" string in the
  repository refers to Qdrant index *page-cacheability*
  (`docs/archive/bmp_decommission_plan/DO_SIZING.md:17`, `docs/THIN_CLIENT_SWAP.md:506`),
  not query/doc term overlap. Marked `*est.*`.
- "~90% zero FMA lanes" was **not measured anywhere** — a conceptual
  derivation from "doc has ~88 terms, query has ≤64, so most gather lanes are
  zero." **Now measured** (2026-07-03): the zero-gather fraction is **76.7%**
  (767 of every 1000 kernel gather lanes fetch zero from the dense query).
  See `06_PREGATE_RESULTS.md`. This is the real number for the M1 wasted-FMA
  tail, not 90%.

Per the doc-freshness rule, unmeasured claims in this section are marked
`*est.*` or "design only"; measured claims carry their result-file path and
absolute date.

## Source-of-truth hierarchy (this section)

1. **The code is always right.** If a doc here contradicts the kernel at
   `spike/vectorium_fork/src/encoders/dotvbyte_fixedu8.rs`, the code wins —
   fix the doc in the same session.
2. This section (`docs/math_optimization/`) is the canonical record for the
   math arc. `docs/seismic_150m_testbed/` is the parent E6/E7/mmap track.
3. Newer measured numbers supersede older ones. `06_PREGATE_RESULTS.md` holds
   the latest pre-gate measurements; earlier conversation estimates
   (the "90%", the "~7% overlap") are **superseded** by the measured values
   there.
4. The math arc is **not on the served path.** Served-path architecture lives
   in `docs/THIN_CLIENT_SWAP.md`; mmap-serving in
   `docs/seismic_150m_testbed/`.

## The load-bearing isolation fact

**To change the per-candidate dot math, you need only a Rust query-evaluator
change** in the encoder crate
(`spike/vectorium_fork/src/encoders/dotvbyte_fixedu8.rs`). The converted mmap
shards serve **as-is** — no `convert_shard_to_mmap.py` change, no `mmap_io.rs`
change, no C1a-writer change, **no shard rebuild.**

Why: the math lives in the `DotVByteFixedU8QueryEvaluator` (`dotvbyte_fixedu8.rs:349`),
built at runtime from `self.forward.encoder().query_evaluator(query)`
(`spike/seismic_upstream/src/mmap_io.rs:1165`). The shard on disk is just the
packed `u64` data the evaluator *reads*. As long as you keep reading the same
u64 layout, the eval mathematics over it is swappable. (This is exactly how
the E7 native rebuild worked — same shards, new `.so`.) The sole exception is
**M5** (block-burst columnar scoring), which changes the *forward layout* and
therefore does force a rebuild — see `03_INTERACTION_MAP.md`.
