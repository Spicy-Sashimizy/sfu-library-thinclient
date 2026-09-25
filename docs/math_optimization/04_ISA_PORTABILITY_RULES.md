# 04 — ISA-portability rules (x86 → aarch64 / Apple Silicon / iPhone)

**Status:** DEFERRED 2026-09-25 (M2 measured but NOT promoted - it failed its pre-registered bar; M6-M10 pre-registered and unfrozen)

This is the discipline that keeps the codebase cross-ISA through any math
change. It exists because the user specifically flagged the risk of an x86-only
optimization locking the codebase out of an ARM/iPhone transition.

## Current state: the codebase IS cross-ISA at source level today

**Good news first:** the dot kernel is `std::simd` → it already compiles for
aarch64 and lowers to NEON. On Apple M-series / A-series (iPhone),
`target-cpu=native` would additionally enable `UDOT`/`SDOT` (ARMv8.4+ integer
dot) and FP16-FMA (ARMv8.2). **The existing math is not x86-locked at source.**

The only explicit x86 surface is in `swizzle.rs` (the SVB gap-decode helper),
and every intrinsic there is dual-cfg-guarded to compile out on aarch64 — see
the full inventory in `01_KERNEL_AND_MATH_MAP.md` and the aarch64-fate column.

**The only way we break portability is hand-intrinsics.** The rules below exist
to prevent that.

## Rule 1 — Prefer `std::simd` over `core::arch` for any new math

`std::simd` (portable SIMD) is the default. It lowers per-target:
- x86-64 + `target-cpu=native` → AVX2/AVX-512 + FMA
- aarch64 + `target-cpu=native` → NEON, and `UDOT`/`SDOT` on ARMv8.4+,
  FP16-FMA on ARMv8.2
- baseline → scalar

The integer dot (M2) **is** expressible as int widening × mul-add in
`std::simd`; that keeps one source lowering to `vpmaddubsw` (x86) / `UDOT`
(Apple aarch64) / scalar (baseline). Only drop to intrinsics if a measured gap
forces it (the only known one is the `vpgatherdd`=0 LLVM lowering gap — M3).

**Concretely for M2:** model the integer dot as `Simd<u8,8>` → widen to
`Simd<i16,8>` (`Simd::cast`) → mul-add → widen to `Simd<i32,4>` → horizontal
sum. Do NOT write `_mm256_maddubs_epi16` by hand unless a benchmark proves
`std::simd` mis-lowers it — and if so, follow Rule 2.

## Rule 2 — If a hand-intrinsic kernel is unavoidable, mandate the cfg-gated twin

The `swizzle.rs:129-134` pattern is the template:
```rust
#[cfg(any(target_arch = "x86", target_arch = "x86_64"))]
#[target_feature(enable = "avx2")]
unsafe fn avx2_pshufb(bytes: Simd<u8, 32>, idxs: Simd<u8, 32>) -> Simd<u8, 32> { ... }
```
- x86-64 path: `#[cfg(target_arch="x86_64")]` + `#[target_feature(enable="avx2")]`
- aarch64 path: `#[cfg(target_arch="aarch64")]` + the NEON intrinsic
- scalar fallback: the `match N { _ => array loop }` arm (so non-x86-non-aarch64
  still works)

**No single-ISA kernel without its twin.** A PR adding a hand-`vpmaddubsw`
path without an aarch64 `UDOT`/`vmull_u8` twin must be rejected at review. The
cross-compile CI gate (Rule 5 / Stage 4) enforces this.

**The M3 exception, and why it's still constrained:** `vpgatherdd` has **no
NEON equivalent** (NEON gather is a scalar `ldar` sequence). So M3 (real gather)
is "faster on x86, scalar parity on ARM" — acceptable ONLY if written as
`std::simd` (accepting scalar gather on ARM as the platform's intrinsic limit),
NEVER as a hand-`vpgatherdd` fast path without a cfg-twin (because there is no
twin — so the hand path would be x86-only and ARM would get *nothing*, breaking
parity). The honest framing for M3: portability parity means "the gather is
scalar on both x86 (until LLVM fixes the lowering) and ARM (forever)."

## Rule 3 — Never bake `target-cpu=native` into build config

`target-cpu=native` **stays env-var only**:
`RUSTFLAGS='-C target-cpu=native' cargo build --release`
(`spike/seismic_upstream/scripts/run_experiments.py:62`).

- **No `.cargo/config.toml`** with `target-cpu=native` — it is currently absent;
  keep it absent.
- **No `build.rs`** setting it — there is no `build.rs` in either fork; keep it
  that way.
- **No `RUSTFLAGS` baked into the manifest.**

Why: baking it breaks cross-compile to aarch64/iPhone (cargo would emit x86
code for an aarch64 target, or fail) and silently emits wrong code. It must be
set explicitly per-build-invocation, documented in the build command.

## Rule 4 — The x86→aarch64 instruction mapping (audit aid)

For reviewing a hand-intrinsic kernel, here's what each x86 op maps to:

| x86 (if hand-written) | aarch64 / Apple equivalent | Note |
|---|---|---|
| `vpmaddubsw` (u8×i8→i16, paired) | `UDOT`/`SDOT` (u8×u8→u32, 4-wide) — ARMv8.4+; else `vmull_u8` + `vmlal` | M2's integer dot. **Prefer `std::simd` int widening+mul-add** so LLVM picks `vpmaddubsw`/`UDOT` automatically |
| `vpgatherdd` | **none** (NEON gather is scalar `ldar` sequence) | M3: gather is scalar on both ISAs — a hand-AVX2 gather gives x86-only gain with no portable twin (Rule 2 / M3 exception) |
| `vfmadd132ps` (FMA) | `fmla` (f32, always available); `vfmlaq_f16` (FP16, ARMv8.2) | already portable via `std::simd` `mul_add` |
| `vptest` / `vtestz` | `cmtst` / `umin` | M1: use `std::simd` `Mask` ops (`Mask::all_false`), not intrinsics |
| `vpshufb` / `_mm_shuffle_epi8` (SSSE3) | `vqtbl1q_u8` (NEON tbl) | already used in `swizzle.rs`, already cfg-guarded |
| `vpmaddwd` (i16→i32 widening) | `smlal`/`smlal2` | M2's i32 widen stage if >6-bit query is ever needed |

## Rule 5 — Cross-compile CI gate (Stage 4 of the testing protocol)

Every kernel-touching commit must pass:
```bash
cargo +nightly check --target aarch64-unknown-linux-gnu   # Linux ARM (e.g. Graviton)
cargo +nightly check --target aarch64-apple-darwin        # Apple Silicon (iPhone-adjacent)
```
(Plus, when available, `aarch64-apple-ios` for the iPhone target directly.)
This catches an x86-only regression — an unresolved `core::arch::x86_64`
symbol, a hand-intrinsic without a twin, a cfg-gate that drops the aarch64
path — **before** it ships.

**Bar:** compiles clean on both aarch64 targets AND the T1 parity harness
(`scripts/tests/test_seismic_sequential.py`) runs bit-identical once the `.so`
is built for aarch64 (the T1 harness is Python, so it runs unchanged once the
Rust `.so` exists for the target arch). See
`05_TESTING_PROTOCOL.md` Stage 4.

**Note on the cross-linker:** `cargo check` type-checks without linking, so
this gate runs without a cross-linker installed. A *full* aarch64 build (for
runtime parity under QEMU / on an ARM box) needs `aarch64-linux-gnu-gcc`
(linker) — a separate, heavier step not required for the source-portability
gate.

## Environment notes (recorded so the gate is runnable)

Cross-checking this crate needs the aarch64 `rust-std` installed on the
**nightly** toolchain (the kernel uses `portable_simd`, a nightly feature):
```bash
sudo "$(which rustup)" +nightly target add aarch64-unknown-linux-gnu aarch64-apple-darwin
```
(`rustup` itself is root-owned at `/usr/local/cargo/bin/rustup`; sudo needs the
absolute path because sudo's PATH doesn't include it. The aarch64 `rust-std`
installs to root-owned `/usr/local/rustup/toolchains/nightly-.../lib/rustlib/`,
so sudo is required.)

The cargo registry/git caches (`/usr/local/cargo/registry`,
`/usr/local/cargo/git`) must be user-writable; on this dev container they were
made writable via `sudo chown -R vscode:vscode /usr/local/cargo/registry
/usr/local/cargo/git` (2026-07-03) — the same dev-container pattern as the
root-owned venv (`CLAUDE.md`). If a future clone hits permission errors on
crates.io index/git fetch, re-apply.
