# 07 — M2 implementation results (MEASURED 2026-07-03)

**Verdict: M2 IMPLEMENTED, CORRECT, FASTER — but FAILS the pre-registered
quality bar at n=100. Stays env-gated OFF (`SFU_SEISMIC_M2_INT6`), NOT
promoted.** The n=40 pre-gate 0.99 was a small-n artifact, exactly as the
borderline-pass caveat in `06_PREGATE_RESULTS.md` warned.

## What was built

`spike/vectorium_fork/src/encoders/dotvbyte_fixedu8.rs` (committed with this doc):

- `DotVbyteFixedu8::dot_product_int6(&self, query: &[u8]) -> u32` — the M2
  integer-domain dot. Portable `std::simd` only (no hand intrinsics, per
  `04_ISA_PORTABILITY_RULES.md`): u8×u8 widened to u16 (max product
  255·63 = 16,065), accumulated in `Simd<u32, N>` (worst case ≈1.05e9 <
  u32::MAX — overflow-free for every encodable vector). Exact integer
  arithmetic, bit-identical to the Stage-0 Python pre-gate model.
- `DotVByteFixedU8QueryEvaluator::with_int6_query(query, encoder, bool)` —
  quantizes the dense query to 6-bit exactly as the Python pre-gate
  (`m2_pregate_query_integer_dot.py::dot_integer`): f64 intermediates,
  ties-to-even, `q_u6 = clip(round(w / q_max · 63), 0, 63)`; rescale
  `s_q·s_d = (q_max/63)·(1/64)` applied once per candidate.
- **Switch:** `SFU_SEISMIC_M2_INT6=1` (read once per evaluator construction,
  i.e. per query). **Default OFF = byte-identical pre-M2 f32 path** (asserted
  by test). Only the dotvbyte forward is affected — the f16 forward uses a
  different encoder/evaluator, so the served path (f16 mmap shards) never
  executes this code regardless of the env.

## Stage 1 — Rust edit + T1 (PASS)

Result file: `data/eval_results/seismic_m2_t1_20260703.json`.

- `cargo test` (vectorium_fork): **122 unit + 27 doctests, 0 failures**,
  including 5 new tests: the **kernel-match safety net**
  (`dotvbyte_int6_matches_python_reference_model` — Rust integer dot ==
  Python pre-gate model exactly, packed loop + scalar remainder both
  exercised), the **saturation edge** (16 terms at 255·63: total 257,040
  overflows i16; u32 accumulator exact), the f32-envelope bound (<2% rel),
  component-remap invariance, and flag-off == pre-M2 behavior.
- Native `.so` rebuilt (`maturin build --release -i .venv python3.11` +
  sudo venv install; `vfmadd` count 81 confirms native).
- T1 keystone (`scripts/tests/test_seismic_sequential.py`): **10/10 with the
  flag off AND 10/10 with `SFU_SEISMIC_M2_INT6=1`** (sequential ≡ parallel
  under both kernels; new≡old f32 equality is not claimed for int6 — integer
  dot changes scores by design; the kernel-match cargo test is the M2 safety
  net per `05_TESTING_PROTOCOL.md` Stage 1).

## Stage 2 — E7 gates (gate a FAILS at n=100; the decisive result)

Same footing as the Arm-E1 anchor (`global_shard0of8` f16 vs dotvbyte twins,
k′=200, heap_factor 0.8, warm_repeats 5, no prefloor). Three runs:

| Run | Result file | gate a overlap@10 (bar ≥0.99) | gate b warm ratio (bar ≤1.07) | gate c majflt ratio (bar ≤0.55) |
|---|---|---|---|---|
| int6, n=40 | `seismic_m2_e7_20260703.json` | 0.990 PASS (at bar) | 0.948 PASS | 0.591 FAIL (= anchor) |
| **int6, n=100** | `seismic_m2_e7_n100_20260703.json` | **0.984 FAIL** | **0.930 PASS** | 0.610 FAIL |
| f32 control, n=100 (same queries, same session) | `seismic_m2_e7_n100_f32control_20260703.json` | **0.991 PASS** | 0.993 PASS | 0.610 FAIL |

**Attribution (the n=100 pair is same-queries, same-session):**

- **Quality:** int6 costs **Δ = −0.007 overlap@10** (0.991 → 0.984) on top of
  the dv-baseline — and that pushes gate a below the 0.99 bar at the
  well-powered n. The n=40 pass at exactly 0.99 was the small-n artifact the
  pre-gate caveat pre-registered ("re-run at larger n before promoting").
- **Speed:** the win is real — warm p50 ratio **0.930 vs 0.993 control**
  (~6% faster warm traverse than the f32 dv kernel on the same queries;
  dv 2.11 ms vs f16 2.27 ms p50).
- **Pages:** gate c is bit-identical under int6 (majflt 83,219 vs control
  83,209 — noise). Confirms (again) gate c is structural, not a math
  property; no dot-kernel change touches it.

## Stage 4 — aarch64 cross-compile after the edit (PASS)

`cargo +nightly check` clean (0 errors, same 2 pre-existing lint warnings) for
BOTH `aarch64-unknown-linux-gnu` (23.6 s) and `aarch64-apple-darwin` (19.5 s)
— the M2 edit did not regress the cross-ISA baseline (it is pure `std::simd`).
Transcript: `data/eval_results/seismic_m2_aarch64_check_20260703.log`.

## Stage 3 (150M serve) + G6 side-channel — NOT RUN, by scoping, not omission

Both exercise the **served** path, which is the **f16** forward (8 f16 mmap
shards). The int6 kernel executes only on the dotvbyte forward (shard0 twin,
itself not promoted — gate c). A G6/Stage-3 run under `SFU_SEISMIC_M2_INT6=1`
would execute zero int6 code, and the prior G6 n=120 run was already
INCONCLUSIVE at this bar (SEM(Δ)=0.0049 ≈ the ±0.005 bar,
`seismic_g6_rrf_fullcorpus_n120_20260629.json`). These stages become
meaningful only if the dotvbyte forward is ever promoted — at which point
gate a already blocks M2 anyway.

## Disposition & what could revive M2

- **Kernel stays in-tree, default OFF** — it is correct (kernel-match test),
  portable (aarch64 clean), measurably faster (0.93 vs 0.99 warm ratio), and
  the honest record of a bar-driven no-promote. Do NOT enable
  `SFU_SEISMIC_M2_INT6` on any quality-bearing path.
- **The resolution/saturation trade is now measured end-to-end:** 6-bit query
  (the widest single-stage-safe width) costs 0.007 overlap@10 — too much.
  The pre-gate already showed 7-bit would clear quality (0.995 in Python,
  n=40) but saturates single-stage i16 pair-sums. The only revival path is a
  **two-stage widen** (u8×u8→u16 products, i32 accumulate via
  `vpmaddwd`/`SMLAL`-class lowering — in `std::simd`: cast to u32 before the
  horizontal add per pack), which buys 7/8-bit query resolution at some of
  the arithmetic win. That is a NEW pre-gate + implementation arc (call it
  M2b), not a tweak to this one.
- The M1 (zero-pack skip) target is untouched by this outcome — 76.7%
  zero-gather stands, and M1 preserves f32 semantics (no quality bar risk),
  but its all-zero-*pack* rate is still unmeasured (instrument first, per 06).
