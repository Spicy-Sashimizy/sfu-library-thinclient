# 06 — Pre-gate results (MEASURED 2026-07-03)

> **UPDATE 2026-07-03 (same day, post-implementation):** the borderline-pass
> caveat below was vindicated. The M2 Rust kernel was implemented and the
> larger-n re-run **refuted the 0.99**: at n=100 (same footing, same-session
> f32 control) int6 overlap@10 = **0.984 FAIL** vs control 0.991 — the n=40
> 0.99 was a small-n artifact. **M2 is NOT promoted** (env-gated OFF). The
> Stage-0 GO verdict below stands as the correct cheap go-signal for the
> *Rust edit*; the promotion verdict is `07_M2_IMPLEMENTATION_RESULTS.md`.

The cheap, zero-Rust-risk pre-gates called for in
`05_TESTING_PROTOCOL.md` Stage 0/4. These are the numbers that decide whether
the math changes are worth a Rust edit.

## M2 query-int pre-gate — PASS (M2 GO)

**Script:** `scripts/seismic_testbed/m2_pregate_query_integer_dot.py`
**Result:** `data/eval_results/seismic_m2_pregate_queryint_20260703.json`
**Method:** the E6b pattern — real engine (seismic.MmapSeismicIndex) top-200
candidates per query (40 queries, K_PRIME=200, HEAP_FACTOR=0.8 — served
defaults) on `global_shard0of8.mmap` (the f16-forward shard, 18.8M docs),
re-scored in pure Python under integer-dot arithmetic (doc → FixedU8`<U6>`,
query → N-bit int). overlap@10 of re-ranked list vs f32 baseline.

| Mode | query bits | query int range | overlap@10 mean | overlap@10 min | overlap@50 mean | saturation | bar ≥0.99 |
|---|---|---|---|---|---|---|---|
| `query_int5` | 5 | [0, 31] | 0.9875 | 0.9 | 0.983 | **safe** | ❌ FAIL |
| `query_int6` | 6 | [0, 63] | **0.99** | 0.9 | 0.993 | **safe** | ✅ **PASS** |
| `query_int7` | 7 | [0, 127] | 0.995 | 0.9 | 0.9935 | unsafe (demo) | (not shippable) |
| `query_int8` | 8 | [0, 255] | 0.9975 | 0.9 | 0.993 | unsafe (demo) | (not shippable) |

**Verdict:** **M2 GO.** 6-bit query quant preserves top-10 ranking under integer
dot → `vpmaddubsw` kernel is quality-safe to implement (saturation-free by
construction: `255·63·2 = 32,130 < 32,767`).

### Why the 5/6/7/8-bit sweep matters

The sweep brackets the quality-vs-saturation trade and proves the saturation
bound is the *binding* constraint, not query resolution:

- **5-bit** (0.9875, FAIL) is the headroom floor — too coarse, loses top-10.
  Establishes "5 bits is not enough resolution."
- **6-bit** (0.99, PASS, safe) is the saturation boundary and the chosen
  target. This is the widest query quant that is *also* saturation-safe for
  single-stage `vpmaddubsw`.
- **7/8-bit** (0.995/0.9975, *un-saturated* in Python; FAIL to ship because
  unsafe) demonstrate that *if* you could ignore saturation, more bits would
  help — but you can't: at 7-bit a pair sum can reach `255·127·2 = 64,770 >
  32,767` → silent saturation → wrong scores in real hardware. The pre-gate
  does NOT simulate saturation; these modes are gated-out by construction and
  shown only to prove "wider query would help quality, but the saturation
  math forbids it at single-stage width." If a wider query is ever genuinely
  needed, widen to i32 (`vpmaddwd` stage on x86, `smlal` on aarch64) — never
  single-stage `vpmaddubsw` with >6-bit query.

### Borderline-pass caveat

`query_int6` passes at exactly 0.99 — the bar. For the Rust implementation,
record overlap@50 (0.993) and the per-query min (0.9) so the margin is
visible, and **re-run at n=120** (the G6 footing, `g6_rrf_parity_fullcorpus.py
--queries 120`) before promoting to served — a 4× larger query set tightens
the SEM and confirms the 0.99 isn't a small-n artifact. The 40-query pre-gate
is a cheap go-signal for the *Rust edit*, not a promotion verdict.

## Zero-gather inventory — 76.7% (M1 target grounded, est. corrected)

**Result (same file):** `zero_gather_inventory` block.

| Metric | Value |
|---|---|
| doc-term slots iterated by kernel (across 4,728 candidate docs) | 822,843 |
| present in query (non-zero gather) | 191,732 (23.3%) |
| **absent from query (zero gather → wasted FMA lane)** | **631,111 (76.7%)** |

**Meaning:** ~3 of every 4 kernel gather lanes fetch 0 from the dense query
array (the doc term isn't in the query), then the FMA multiplies nothing. This
is the M1 (zero-product skip / `vptest`) target.

**This corrects the earlier unmeasured estimate.** The prior framing asserted
"~90% zero FMA lanes" as a conceptual derivation; the measured zero-gather
fraction is **76.7%**, not 90%. The actual M1 *FMA-lane idle rate* is lower
than 76.7% (a gather lane is zero-gathered but the surrounding 8-lane pack may
not be *all*-zero, so the pack still pays the FMA). So 76.7% is the **upper
bound** on M1's skip rate (the all-zero-pack rate, which M1 actually needs, is
unmeasured — instrument it before committing M1). `*est.*` on M1's realized
win.

## aarch64 cross-compile status — see below (updated as the check completes)

The Stage-4 portability gate (`cargo +nightly check --target
aarch64-unknown-linux-gnu` and `aarch64-apple-darwin`) was the first thing
that exercises the `04_ISA_PORTABILITY_RULES.md` discipline. It hit a
chain of dev-container permission issues (root-owned
`/usr/local/cargo/{registry,git}` and a nightly `rust-std` install that
silently rolled back), each documented in `04_…md`'s environment-notes
section so the gate is runnable next time. The final, correct invocation:

```bash
# one-time setup (sudo + explicit RUSTUP_HOME because rustup installs to root-owned dirs):
sudo RUSTUP_HOME=/usr/local/rustup CARGO_HOME=/usr/local/cargo \
     "$(which rustup)" +nightly target add aarch64-unknown-linux-gnu aarch64-apple-darwin
sudo chown -R vscode:vscode /usr/local/cargo/registry /usr/local/cargo/git  # dev-container fix

# the gate itself (type-check, no linker needed):
cd spike/vectorium_fork
cargo +nightly check --target aarch64-unknown-linux-gnu
cargo +nightly check --target aarch64-apple-darwin
```

**Outcome: PASS — both aarch64 targets compile clean (2026-07-03).**

```
cargo +nightly check --target aarch64-unknown-linux-gnu   → Finished in 35.61s  (2 warnings, 0 errors)
cargo +nightly check --target aarch64-apple-darwin        → Finished in 1m 00s  (2 warnings, 0 errors)
```

The 2 warnings are unrelated unused-nightly-feature lints (`associated_type_defaults`,
`stable_features` in `lib.rs:7`) present on the host target too — not portability issues.

**What this confirms:** the kernel compiles for aarch64 with **no missing
`core::arch::x86_64` symbols, no hand-intrinsic without a twin, no cfg-gate that
drops the aarch64 path.** The `01_KERNEL_AND_MATH_MAP.md` analysis predicted this
(the kernel is `std::simd`; the only x86 intrinsics are cfg-guarded in
`swizzle.rs` and fall through to the scalar `match N` arm on aarch64); the gate
**verifies** it rather than asserting it. This is the cross-ISA baseline before
any M2 edit — any future kernel change that regresses this gate is caught before
it ships. Transcript (re-runnable): the commands above plus the one-time setup
in `04_ISA_PORTABILITY_RULES.md`.

**What this gate proves either way:** whether the kernel (as it stands today,
before M2) is cross-ISA at source level. The `01_KERNEL_AND_MATH_MAP.md`
analysis says it should be (the kernel is `std::simd`; the only x86 intrinsics
are cfg-guarded in `swizzle.rs`), but the gate *verifies* it rather than
asserting it — exactly the discipline any future kernel edit must follow.

## Summary

| Pre-gate | Question | Result | Decision |
|---|---|---|---|
| M2 query-int | does 6-bit query quant hold overlap@10 ≥0.99? | **0.99 PASS** (safe) | **M2 GO** — quality-safe to implement in Rust |
| M2 saturation sweep | is the saturation bound the real constraint? | 7/8-bit would help quality but are unsafe | confirms 6-bit is the right target; wider needs i32 widen |
| Zero-gather inventory | what fraction of gather lanes fetch zero? | **76.7%** | grounds M1's target (corrects the "90%" estimate) |
| aarch64 cross-check | is the codebase cross-ISA today? | **PASS — both targets compile clean** | establishes the cross-ISA baseline before any M2 edit |

## What the pre-gates did NOT do (honesty)

- The M2 pre-gate is a **scoring-side proxy**: it re-scores the engine's
  existing top-200 candidates. It does NOT capture the second-order effect of
  integer-dot scores on the heap-min block-skip test during traversal (the
  block-pruning decision uses the *scored* threshold). Bounded by the ~same
  error the FixedU8Q doc-side already incurs (0.995 fidelity), but the final
  Rust implementation must clear Stage 2 (full E7 gates) to confirm it.
- `query_int6` passes at exactly 0.99 — borderline. Re-run at n=120 (G6
  footing) before promoting to served.
- The zero-gather 76.7% is the per-lane rate; M1's actual skip rate (all-zero
  *pack*) is unmeasured.
- The 5/7/8-bit modes do not simulate saturation — they're construction-gated
  and shown only to bracket the trade.
