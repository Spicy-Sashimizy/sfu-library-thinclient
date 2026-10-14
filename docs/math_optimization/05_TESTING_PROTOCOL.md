# 05 — Testing protocol (staged, pre-registered bars)

**Status:** DEFERRED 2026-09-25 (M2 measured but NOT promoted - it failed its pre-registered bar; M6-M10 pre-registered and unfrozen)

Every math change (M1–M5) follows this protocol. Each stage is a go/no-go gate
with a pre-registered bar; no stage's bar is retrofitted to the result.

> **AMENDED 2026-07-05 (post-G8d — binding for every future quality gate):**
> 1. **Worst-case-shard rule.** G8d (`seismic_150m_testbed/10_…` §7.6) measured
>    shard0 as the *best-case* parity shard (0.995 versus corpus mean 0.9906;
>    shards 1–2 = 0.985). All Stage-0 and Stage-2 quality gates now run on
>    **shard 1 or shard 2** (both when cheap), never shard0-only. A
>    shard0-only quality PASS is not promotable.
> 2. **n≥100 minimum** for any promotable overlap gate (the M2 n=40→100
>    reversal, `07_M2_IMPLEMENTATION_RESULTS.md`).
> 3. Execution queue + per-candidate recipes:
>    `../archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md`.

Result files write to `data/eval_results/{topic}_{descriptor}_{YYYYMMDD}[_{HHMM}].{json,log}`
(the established convention; see `06_PREGATE_RESULTS.md` for examples).

## Stage 0 — Python pre-gates (zero Rust risk)

**Template:** `scripts/seismic_testbed/e6b_fixedu8_quality.py` +
`e6_forward_codec_proto.py` `phase_c_quality()` — take the engine's real
top-K candidates on a `seismic.MmapSeismicIndex`, re-score those *same*
candidates in pure Python under alternate arithmetic, measure overlap@10.

**M2 pre-gate (DONE 2026-07-03):** `scripts/seismic_testbed/m2_pregate_query_integer_dot.py`
— adds a `query_int` mode (the e6b harness only tested *doc* quantization;
this adds *query* quantization to int). Doc → FixedU8`<U6>` (the served
format), query → 5/6/7/8-bit int, integer dot `Σ d_u8·q_u8`. Also instruments
the zero-gather fraction. Result: `data/eval_results/seismic_m2_pregate_queryint_20260703.json`.

| Mode | overlap@10 | saturation | Verdict |
|---|---|---|---|
| `query_int5` (≤31) | 0.9875 | safe | FAIL (below bar — 5-bit query too coarse) |
| `query_int6` (≤63) | **0.99** | **safe** | **PASS — M2 GO** |
| `query_int7` (≤127) | 0.995 | unsafe (demo only) | (proves bound bites, not a shippable mode) |
| `query_int8` (≤255) | 0.9975 | unsafe (demo only) | (proves bound bites, not a shippable mode) |

- **Bar:** overlap@10 ≥ 0.99 AND saturation-safe by construction (query ≤6-bit).
  The `query_int6` PASS at exactly 0.99 is a borderline pass — for the Rust
  implementation, also record overlap@50 (0.993) and per-query min (0.9) so the
  margin is visible, and consider re-running at n=120 (the G6 footing) before
  promoting.
- **Zero-gather inventory:** 76.7% (631,111 / 822,843 doc-term slots) — grounds
  the M1 target.
- **Stage 0 go/no-go for M2:** GO (6-bit safe). For M1: the all-zero-*pack*
  rate is still unmeasured (76.7% is the per-lane upper bound) — instrument
  before committing M1.

## Stage 1 — Rust edit + T1 bit-identical (the keystone)

Edit only `spike/vectorium_fork/src/encoders/dotvbyte_fixedu8.rs` (M1/M2/M4) or
the kernel. Build the `.so` (`RUSTFLAGS='-C target-cpu=native' maturin develop`
into the venv — see the build section below).

**Run:** `scripts/tests/test_seismic_sequential.py` — the keystone is
`test_sequential_identical_to_parallel` (`:149`): same oaid order AND scores
within `1e-6` on a real `MmapSeismicIndex`. (This is the "T1 bit-identical"
property; the 14-test framing in memory is this keystone + the G8-matrix tests
in `test_serve_footprint_g8_matrix.py`.)

**Critical for M2:** the scores will NOT be bit-identical to the f32 baseline
(it's integer dot). So T1 here means *sequential≡parallel* (both modes use the
new kernel), NOT *new≡old f32*. Add a new test:

- `test_new_kernel_matches_python_integer`: asserts the Rust integer dot
  matches the Stage-0 Python integer dot **exactly** (same rounding, same
  6-bit query quant). This is the true safety net for M2 — it pins the Rust
  arithmetic to the pre-gated Python model so the saturation bound can't drift
  in implementation.

  For M1/M3/M4 (which preserve f32 semantics), the standard T1
  *new≡old bit-identical* does apply (those are pure execution changes).

- **Bar:** tests green.
- **No gate-b claim yet** (this stage is correctness, not performance).
- Result: `data/eval_results/seismic_m2_t1_{date}.json` (pytest junit +
  the kernel-match assertion).

## Stage 2 — E7 gates, same footing

`scripts/seismic_testbed/e7_dotvbyte_gates.py` — run against the **same Arm-E1
native anchor** (`seismic_e7_armE1_native_reconfirm_k200_run1.json`, the 0.957
result) so the comparison is apples-to-apples.

| Gate | Bar | Definition site | Expected outcome for M2 |
|---|---|---|---|
| gate a parity | `overlap@10 >= 0.99` | `e7_dotvbyte_gates.py:184` | must stay PASS (M2 changes scores, so re-verify) |
| gate b warm latency | `warm_p50_ratio <= 1.07` | `:185` | should improve or hold (integer dot is the headline win) |
| gate c cold majflt | `majflt_cold_ratio <= 0.55` | `:187` | **will NOT move** (not a math property — confirmed by Fix #2/#3 both refuted) |

`K_PRIME=200, HEAP_FACTOR=0.8, WARM_REPEATS=5` (`:47-51`).
- **Bar:** gate a stays PASS, gate b improves or holds. (Gate c stays FAIL —
  that's not a regression, it's a non-target.)
- Result: `data/eval_results/seismic_m2_e7_{date}.json`, verdict-aligned with
  `seismic_e7_RECLEAR_VERDICT.json`.

## Stage 3 — End-to-end at 150M (where the math could re-emerge)

`scripts/seismic_testbed/serve_footprint_bench.py --queries 40 --passes 2
--federation parallel --result-file …` — the regime-aware G8 harness.

**Why this stage matters:** gate b's 0.957 is a 929k-warm number. At 150M on
the 32 GB host the serve bench showed ~15.8 s p50 **IO-bound** (re-fault each
pass) — so a faster kernel may NOT move wall-clock there. The prior
sequential-serving measurement already refuted "faster math ⇒ faster serve"
when IO-bound. So Stage 3 is the honesty check: does the kernel win survive a
regime where the bottleneck is memory, not arithmetic?

- **Bar:** G8 honesty verdict (warm < cold AND VmSwap ≈ 0 under a
  non-compressed regime; see `serve_footprint_bench.py:_latency_caveat`).
- Record: encode/traverse split (the traverse split is where a kernel win
  should show), cold/warm p50/p95.
- Result: `data/eval_results/seismic_m2_g8_{date}.json`.

## Stage 4 — ISA cross-compile + aarch64 parity (the portability guarantee)

```bash
cargo +nightly check --target aarch64-unknown-linux-gnu   # type-check only, no linker
cargo +nightly check --target aarch64-apple-darwin
# then, when an aarch64 box / QEMU is available:
#   build the .so for aarch64, run scripts/tests/test_seismic_sequential.py on it
```

- **Bar:** compiles clean on both aarch64 targets (no unresolved
  `core::arch::x86_64` symbols, no hand-intrinsic without a twin) AND T1
  bit-identical on aarch64 once the `.so` is built.
- **This is the gate that catches an x86-locked regression before it reaches
  iPhone.** See `04_ISA_PORTABILITY_RULES.md` Rule 5.
- Result: `data/eval_results/seismic_m2_aarch64_check_{date}.log` (cargo check
  transcript) + the on-box T1 result if available.

## Side-channel gates (run only if Stage 1 changes scores system-wide)

| Script | Bar | When to re-run |
|---|---|---|
| `seismic_testbed/g_federation_overlap.py` | `overlap@10 >= 0.98` (`FED_BAR`), stop 0.95 | M5 only (layout change) |
| `seismic_testbed/g6_rrf_parity_fullcorpus.py` | `abs(paired_delta) < 0.005` (`G6_BAR`) | M2 (ranking arithmetic change — re-verify quality at the system level) |
| `seismic_testbed/rejudge_seismic_leg_n120.py` | shard-independent; clears zero | M2 (if G6 borderline) |
| `T1` (`test_seismic_sequential.py`) | bit-identical `1e-6` | every kernel change (Stage 1) |

M1/M3/M4 preserve f32 semantics → no side-channel re-run needed.
M2 changes ranking arithmetic → re-run G6.
M5 changes layout → re-run federation overlap + G6.

## The build command (recorded so each stage is reproducible)

The `.so` served to the venv is built with maturin + native, env-only:
```bash
cd spike/seismic_upstream
RUSTFLAGS='-C target-cpu=native' maturin develop --release  \
  # installs into .venv/lib/python3.11/site-packages/seismic/
```
- Verify the build: `objdump -d .venv/.../seismic.cpython-311-x86_64-linux-gnu.so | grep -c vfmadd`
  (should be ~88 for a native build; 0 for a baseline SSE2 build with no environment).
- Verify importability: `/workspaces/sfu-library-thinclient/.venv/bin/python3 -c "import seismic; print('OK')"`.
- For aarch64 (Stage 4 runtime): set the target triple in the maturin build
  (`--target aarch64-...`) — requires the cross-linker; the type-check gate
  (Stage 4 `cargo check`) does not.
