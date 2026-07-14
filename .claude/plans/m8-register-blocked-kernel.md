# Plan — M8: register-blocked batch scoring kernel (Q3 finale, container, Rust)

**Created 2026-07-10**, after the Q3 pre-gate GO: survivors-per-block median
**18** (bar 4), 97.6% of surviving blocks ≥4 candidates, instrument parity
100/100 (`q3_m8_survivors_per_block_20260710.json`, math 08 §M8, doc 12 §3
Q3). The kernel is **bit-identical by construction** — the only gates are
identity + latency. Environment: dev container. Paste-ready session prompt:
`scripts/seismic_testbed/SESSION_PROMPT_M8_KERNEL.md`.

## Pre-registered bars (written BEFORE the build — never retrofitted)

| # | Gate | Bar |
|---|---|---|
| a | bit-identity vs the pre-M8 `.so`: full result lists, n=100, shards 1–2, dv + f16, k'=100 | hard=0 AND tie-swaps=0, 100/100 both shards both codecs |
| b | test suites | seismic lib green + vectorium release green + 12/12 sequential parity suite re-pass |
| c | warm traverse p50, same-process interleaved paired A/B (batch ON vs OFF), shards 1–2 dv, n=100 × 3 reps | **PROMOTE** ≤0.95× on both shards; **KEEP-unpromoted** <1.00× consistently (G8g precedent — strictly faster + zero risk); **REVERT** ≥1.00× |
| d | federated warm p50 (info) | recorded; expectation *est.* −3–8 ms of the 33.7 ms traverse share, Amdahl-capped by the decode third (math 08 §M8 value note) |

**Cold caveat (pre-registered, math 08 §M8):** interleaved fetches may
overlap cold faults → any cold improvement is reported as **wall-clock
only, never a majflt/gate-c claim** (the count is unchanged).

## The change

Target: `spike/seismic_upstream/src/posting_list.rs:239–249` — the block
loop scores survivors strictly one at a time
(`evaluator.compute_distance(vector)` per doc, one dependency-chained
accumulator). Restructure per math 08 §M8:

1. **Two-phase block loop:** first pass = the existing `visited.insert`
   filter, collecting the surviving `Range`s in today's order; second pass =
   score them in batches of **4** interleaved candidates, pushing to the
   heap in the SAME candidate order as today.
2. **`compute_distance_batch(&[Range; B]) -> [f32; B]`** on the evaluator /
   forward-index seam, with a **default implementation = the scalar loop
   over `compute_distance`** (bit-identical fallback for every codec), and a
   specialized interleaved impl for the dv (dotvbyte) evaluator first: 4
   independent `Simd<f32, 8>` accumulators sharing one pass over the query
   structures (`spike/vectorium_fork/.../dotvbyte_fixedu8.rs` kernels; the
   E8 v2 per-doc `vmax/255` factor stays per-candidate, factored out of each
   candidate's own accumulator exactly as in the scalar kernel).
3. **Bit-identity invariants (the whole point):** each candidate keeps its
   OWN accumulator and its OWN per-candidate summation order; only the
   interleaving across candidates changes; remainder (<4 survivors) takes
   the scalar tail. No kernel-match model needed (unlike M2).
4. **Rollback env:** `SFU_SEISMIC_M8_BATCH=0` forces the scalar path
   (one-env rollback pattern); default ON only if bar c promotes, else
   default OFF.
5. Forward blobs still fetched individually (`packed_dataset.rs:344–347`) —
   **no format change, no shard rebuild, Rule Zero trivially satisfied.**

Optional measurement arm (only if batch-4 promotes): batch-8 behind the
same env, reported as an extra cell — not a separate promotion decision.

## Build + eval order

1. Cargo unit test first: synthetic dataset, batch vs scalar exact-equality
   (both codecs, remainder widths 1–3, plus the E8 v2 codec path).
2. `cargo build --release` + maturin develop into the venv — coordinate the
   `.so` swap with any concurrently running measurement (nothing else may be
   mid-run; same rule as the Q7/E8 builds).
3. Gate a/b, then gate c (`serve_footprint_bench.py` traverse timings or the
   `e7_dotvbyte_gates.py` warm-cell convention — interleaved ON/OFF in ONE
   process, the D2 methodology rule).
4. Result JSON `data/eval_results/m8_batch_kernel_2026MMDD.json`.

## Same-commit docs

math 08 §M8 (kernel RESULT under the pre-gate RESULT), doc 12 §3 Q3 verdict
line + §4 ledger row, doc 06 row on promotion;
`docs/math_optimization/01_KERNEL_AND_MATH_MAP.md` if the kernel map's
line-anchors move. If promoted to default-ON: `docs/THIN_CLIENT_SWAP.md`
env-gate table, same commit.

## Interaction notes

- **Composes with E8 dv-v2** (per-doc scale is per-candidate, factors out
  per accumulator) — implement batch kernels for BOTH v1 and v2 value
  scales so E8 Stage 2 doesn't orphan this work.
- **M7 is dead** (all-miss-pack 0.194) — no bitmap pre-filter in the batch
  loop; the visited-filter phase is the plain existing one.
- **Where it pays** (math 08 leverage map): warm single-shard, sequential
  federation, throughput/energy — NOT primarily the federated p50 (~2–3 ms
  of ~54 ms is kernel time under parallel federation).
