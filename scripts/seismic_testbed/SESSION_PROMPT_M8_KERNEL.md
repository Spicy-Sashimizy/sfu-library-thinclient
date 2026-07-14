# SESSION PROMPT — M8: register-blocked batch scoring kernel (paste-ready)

Paste everything below the `---` into a Claude Code session in the dev
container (`/workspaces/sfu-library-thinclient`). Plan:
`.claude/plans/m8-register-blocked-kernel.md`; candidate spec:
`docs/math_optimization/08_FURTHER_MATH_CANDIDATES.md` §M8. Doc 12 §3 Q3 is
the source of truth — if this file and doc 12 disagree, doc 12 wins.

**Pre-gate already GO (2026-07-10):** survivors-per-block median 18 (bar 4),
97.6% of blocks ≥4 candidates, instrument parity 100/100
(`q3_m8_survivors_per_block_20260710.json`). The kernel is bit-identical by
construction — this session is build + identity gate + latency gate only.

---

You are building the M8 register-blocked kernel per
`.claude/plans/m8-register-blocked-kernel.md`. One item, take-one-finish-one:
implement → gate → record → commit. Do not start if you cannot finish the
latency measurement in-session; leave a dated "IN PROGRESS" note in doc 12
§3 Q3 if interrupted.

## Standing rules (binding)

1. **Rule Zero:** served shard dirs are READ-ONLY (no format change here, so
   this session should touch NO shard files — verify with
   `find data/seismic_150m/index/plan01 -newermt <session start>` at end).
2. **Git:** `git pull` first; explicit `git add <files>` (NEVER `git add .`);
   commit+push per logical unit. Branch `spike/mmap-bmp`.
3. **Venv:** `.venv/bin/python3` everywhere; maturin develop into the venv.
4. **`.so` swap coordination:** nothing else may be mid-measurement when you
   rebuild/reinstall the wheel (the Q7/E8 rule).
5. **Only same-process interleaved A/Bs are promotable** (D2 methodology
   rule) — the ON/OFF arms run in ONE process, alternating.
6. **Bars are pre-registered below — never moved after results.**

## The change (spec: math 08 §M8 + the plan)

- `spike/seismic_upstream/src/posting_list.rs:239–249`: two-phase block
  loop — visited-filter collect surviving ranges (today's order), then score
  in batches of 4 via `compute_distance_batch`, heap-push in the SAME order.
- `compute_distance_batch(&[Range]) -> [f32]` at the evaluator/forward-index
  seam: **default impl = scalar loop over `compute_distance`** (bit-identical
  fallback, every codec), specialized interleaved impl for the dotvbyte
  evaluator (4 independent `Simd<f32,8>` accumulators, one shared pass over
  the query structures; `spike/vectorium_fork/.../dotvbyte_fixedu8.rs`).
  Cover BOTH value scales (v1 fixed 1/64 AND E8 v2 per-doc vmax/255 — the
  per-doc factor stays per-candidate, factored out per accumulator).
- Invariants: per-candidate accumulator, per-candidate summation order,
  scalar tail for remainders <4. Only cross-candidate interleaving changes.
- Rollback env `SFU_SEISMIC_M8_BATCH` (=0 forces scalar). Default ON only if
  the promotion bar passes; else ships default-OFF.

## Gates (pre-registered)

| # | Gate | Bar |
|---|---|---|
| a | bit-identity vs pre-M8 `.so`: full result lists, n=100, shards 1–2, dv + f16, k'=100 | hard=0 ∧ tie-swaps=0, 100/100 everywhere |
| b | suites | cargo tests green (incl. new batch-vs-scalar exact-equality: both codecs, both value scales, remainder widths 1–3) + 12/12 sequential parity re-pass |
| c | warm traverse p50, interleaved paired ON/OFF, shards 1–2 dv, n=100 × 3 reps | **PROMOTE** ≤0.95× both shards; **KEEP-unpromoted** <1.00× consistently; **REVERT** ≥1.00× |
| d | federated warm p50 | info only (*est.* −3–8 ms of the 33.7 ms traverse share, Amdahl-capped) |

**Cold caveat (pre-registered):** any cold-cell improvement is wall-clock
only — NEVER a majflt/gate-c claim (the fault count is unchanged; math 08
§M8 caveat). Batch-8 arm: optional extra cell only if batch-4 promotes.

## Build + eval order

1. Cargo unit tests on a synthetic dataset FIRST (exact equality).
2. `cargo build --release` + maturin develop; verify the served v1 e5
   manifest still loads + the 12/12 parity suite passes.
3. Gate a (reuse the `e8_dvv2_gates.py` / T1 comparison conventions).
4. Gate c: one process, ON/OFF alternating (env toggle or a per-call flag),
   3 reps. Result → `data/eval_results/m8_batch_kernel_$(date +%Y%m%d).json`.

## Recording (same commit as the measurement)

math 08 §M8 kernel RESULT, doc 12 §3 Q3 verdict line + §4 ledger row,
doc 06 row if promoted, `docs/math_optimization/01_KERNEL_AND_MATH_MAP.md`
if line-anchors moved, `docs/THIN_CLIENT_SWAP.md` env-gate table if
default-ON ships. Numbers + result path + absolute date, or `*est.*` — no
unmarked optimism.
