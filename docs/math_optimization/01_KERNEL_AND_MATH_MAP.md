# 01 — Grounded kernel and math map

**Status:** DEFERRED 2026-09-25 (M2 measured but NOT promoted - it failed its pre-registered bar; M6-M10 pre-registered and unfrozen)

All line numbers against `/workspaces/sfu-library-thinclient/spike/vectorium_fork`
and `/workspaces/sfu-library-thinclient/spike/seismic_upstream` as of 2026-07-03.

## The hot loop

**Kernel:** `DotVbyteFixedu8::dot_product` —
`spike/vectorium_fork/src/encoders/dotvbyte_fixedu8.rs:603-642`.

**Call path** (the SEISMIC block-scoring dispatch):
```
posting_list.rs:202  evaluate_posting_block
posting_list.rs:225  evaluator.compute_distance(vector)
dotvbyte_fixedu8.rs:402-407  DotVByteFixedU8QueryEvaluator::compute_distance
dotvbyte_fixedu8.rs (dotvbyte_view).dot_product(&self.dense_query)
```

**The kernel:**
```rust
603  pub(crate) fn dot_product(&self, mut query: &[f32]) -> f32 {
604      let mut result = Simd::<f32, 8>::splat(0.0);
605      // This ugly clone is optimized away
606      for (components, values) in self.clone().iter_raw() {
607          let components = simd_prefix_sum(components);
608          let values = simd_fixedu8_to_f32(values);
609          let query_values = unsafe {
610              Simd::gather_select_unchecked(
611                  query,
612                  Mask::splat(true),
613                  components.cast(),
614                  Simd::splat(0.0),
615              )
616          };
617
618          result = values.mul_add(query_values, result);
619          let last_component = *components.to_array().last().unwrap();
620          // New starting point for the gather
621          query = unsafe { query.split_at_unchecked(last_component as usize).1 };
622      }
623      let simd_result = result.reduce_sum();
...      // scalar remainder for trailing elements not filling a full SIMD pack
641      simd_result.algebraic_add(remaining_result)
642  }
```

Lane width is `const N: usize = u8::BITS as usize;` = `8` (`dotvbyte_fixedu8.rs:409`),
so the accumulator is `Simd<f32, 8>` and packed doc values are `Simd<u8, 8>`.

## The three "thirds" — literally separate lines

| Third | Lines | Operation | Types |
|---|---|---|---|
| **(a) Decode** | `:606-607` | `iter_raw()` SVB-decodes gap bytes (`:557-575`); `simd_prefix_sum(components)` (`:681-695`) shift-and-add prefix-sums the gap deltas into absolute component ids | `Simd<u16, 8>` |
| **(b) Gather** | `:609-616` | `Simd::gather_select_unchecked(query, Mask::splat(true), components.cast(), …)` fetches query weights from the dense `Vec<f32>` of length `dim` (built at `:379-390`) | `f32` → `Simd<f32, 8>` |
| **(c) Arith** | `:608, :618` | `simd_fixedu8_to_f32(values)` (`:697-702`: cast + `* 1/64`); `result = values.mul_add(query_values, result)` (FMA) | `Simd<f32, 8>` → `f32` via `reduce_sum()` (`:623`) |

The f16 forward path (the *other* served format) skips third (a) entirely
(values are already decoded f16), which is where the pre-native 1.22× came
from: decode cost paid by dotvbyte but not f16.

## Data types

| Side | Type | Source |
|---|---|---|
| Doc values | `FixedU8Q = FixedU8<U6>` — u8, 6 fractional bits, scale `1/64`, saturates at `255/64 = 3.984` | `lib.rs:18-22` |
| Query values | `f32`, densified to `Vec<f32>` length `quantizer.dim` | `dotvbyte_fixedu8.rs:350, 379-390` |
| Component ids | `u16` (`InputComponentType = u16`), SVB-encoded gap deltas, post-decode `Simd<u16, N>` cast to `i32`/`usize` for the gather | `:106, :613` |
| Accumulator | `Simd<f32, 8>` → `f32` via `reduce_sum()` | `:604, :623` |
| Packed blob | `u64` (`PackedDataType = u64`), recast to `&[u8]` at decode (`:430`, `:146`) | `packed_dataset.rs:117-130` |

Also defined but unused in the dotvbyte path: `FixedU16Q = FixedU16<U13>`
(`lib.rs:23`, 13 fractional bits).

## Layout asymmetry (load-bearing for the M5 option)

The architecture is: **columnar inverted index whose leaves deref into a
row-major forward doc store.** The dotvbyte kernel operates on the
**row-major** side, one doc at a time.

- **Inverted side — columnar** (term → block list → doc offsets):
  `PostingList { packed_postings: Box<[PackedPostingBlock]>,
  block_offsets: Box<[usize]> }` (`posting_list.rs:83-86`), sliced per block
  at `:150, :189`. Each `PackedPostingBlock` stores doc-offsets+lengths, not
  doc_ids (`posting_list.rs:26-28`: "Instead of storing doc_ids we store their
  offsets in the forward_index and the lengths of the vectors").
- **Forward side — row-major**: `PackedSparseDatasetGeneric { offsets: [usize],
  data: [u64], encoder, nnz }` (`packed_dataset.rs:117-130`). Each document is
  a contiguous self-contained packed blob retrieved by `get_with_range`
  (`packed_dataset.rs:344-347`): `let slice = &self.data.as_ref()[range];
  PackedVectorView::new(slice)`. Per-doc encoding (`push_vector`,
  `dotvbyte_fixedu8.rs:483-555`) appends one self-contained blob.

Within a single doc the blob is internally *term-ordered* (sorted by component
id then gap-delta'd, `:490-496`), so a doc is term-semi-sorted — but across
documents there is **no transposition**. The iteration unit at search time is
"fetch one doc's full packed blob, score it against the query"
(`posting_list.rs:224` `forward_index.get_with_range(range.clone())` →
`evaluator.compute_distance(vector)`).

This asymmetry is why M5 (block-burst columnar scoring) is the only option
that can attack gate c, and why it's the only one that forces a rebuild — see
`03_INTERACTION_MAP.md`.

## x86-intrinsic inventory (full, for the portability audit)

**Critical: the kernel itself uses only `std::simd` portable-SIMD intrinsics,
not raw `core::arch` intrinsics.** Every SIMD operation in the kernel
(`dotvbyte_fixedu8.rs:604-623`) is a portable-SIMD call the compiler lowers.

The only **explicit `core::arch` x86 intrinsics** live in the swizzle helper
`spike/vectorium_fork/src/encoders/dotvbyte_fixedu8/swizzle.rs` (the SVB
gap/branch decode preceding the kernel):

| Intrinsic | Site | cfg guard | aarch64 fate |
|---|---|---|---|
| `_mm_shuffle_epi8` (SSSE3 `pshufb`) | `swizzle.rs:47` | `#[cfg(target_feature="ssse3")]` | compiles out → scalar `match N` (`:90-98`) |
| `_mm256_permute2x128_si256`, `_mm256_shuffle_epi8` (AVX2) | `swizzle.rs:141-142` | (under the AVX2 path) | compiles out |
| `_mm256_cmp_epu8_mask`, `_mm256_maskz_permutexvar_epi8` (AVX-512 VL/VBMI) | `swizzle.rs:69, 73` | `#[cfg(target_feature="avx512*")]` | never activates |
| `_mm512_cmp_epu8_mask`, `_mm512_maskz_permutexvar_epi8` (AVX-512 VBMI) | `swizzle.rs:82, 86` | `#[cfg(target_feature="avx512*")]` | never activates |

**The one `#[target_feature(enable=...)]` attribute** — the AVX2 swizzle
(`swizzle.rs:129-134`):
```rust
#[cfg(any(target_arch = "x86", target_arch = "x86_64"))]
#[target_feature(enable = "avx2")]
...
unsafe fn avx2_pshufb(bytes: Simd<u8, 32>, idxs: Simd<u8, 32>) -> Simd<u8, 32> {
```
The `32 => transize(avx2_pshufb, ...)` arm is gated
`#[cfg(all(target_feature="avx2", not(target_feature="avx512vbmi")))]`
(`swizzle.rs:63`). On baseline SSE2 this compiles out; only the SSSE3 16-lane
`_mm_shuffle_epi8` (or scalar fallback) is active. With `N=8` the swizzle
operates on `Simd<u8, 8>`, so on x86-64 the active arms are the SSSE3 16-lane
(used via `transize`) or scalar — the AVX2 32-lane arm is only reached when
`N≥32`.

**Important asymmetry: the AVX2 `avx2_pshufb` is additionally
`#[cfg(target_arch="...")]`-guarded so it physically compiles out on non-x86.
The kernel's `std::simd` operations are *not* cfg-guarded — they rely on the compiler
backend.** This is the load-bearing portability property: the kernel has no
hand-written fallback because `std::simd` *is* the portable fallback.

## Build config

- **`rust-toolchain.toml`: nightly** (required for `portable_simd`,
  `core_intrinsics`, `gen_blocks`, `yield_expr`, `float_algebraic` —
  `lib.rs:1-7`).
- **No `.cargo/config.toml`, no `build.rs`, no `RUSTFLAGS` baked into the
  crate** in either fork. `Cargo.toml` `[profile.release]` sets `lto = true`
  (vectorium). No `target-feature=` / `target-cpu` anywhere in the manifests.
- The shipped `.so` is built by **maturin** (`seismic_upstream/pyproject.toml`:
  `requires=["maturin>=1.2.3"]`, `[tool.maturin] features=["default","python"]`),
  which invokes `cargo build --release` with crate-type `["cdylib","lib"]`.
- **Native rebuild = environment var only:** `RUSTFLAGS='-C target-cpu=native' cargo
  build --release` (`spike/seismic_upstream/scripts/run_experiments.py:62`).
  Commit `223aca5` (E7 "Arm B native anchor", 2026-07-03) records that the
  rebuild was done via that environment, with **no code change**, and the `.so` was
  reinstalled to the venv. Its measured effect (from the commit): "+54 packed
  `vfmadd..ps`, +14k `ymm` regs, +185 `vpshufb` (baseline SSE2 had 0/294/26)."

## Scalar fallback / feature gating

- The swizzle `swizzle.rs:90-98` has an explicit scalar fallback (`match N { _ =>
  array loop }`) for architectures without the gated features — so swizzle never
  silently fails.
- The dot-product kernel itself (`dotvbyte_fixedu8.rs:603-642`) uses portable-SIMD
  unconditionally. There is **no `#[cfg(target_feature="avx2")]` on the kernel**
  and **no hand-written scalar fallback** for the gather/FMA/convert third. If
  the build target lacks the SIMD lowering, `std::simd` either lowers to scalar
  or fails to compile; there is no hand-written scalar `dot_product` branch.

## The shipped .so (2026-07-03)

Path: `.venv/lib/python3.11/site-packages/seismic/seismic.cpython-311-x86_64-linux-gnu.so`
(2,645,176 bytes, mtime Jul 3 03:22). Native build.

**objdump evidence** (the two defects the native rebuild did *not* close):

| Instruction | Count (native) | Baseline SSE2 | Note |
|---|---|---|---|
| `vfmadd` (FMA) | **88** | 0 | native enabled FMA — gate b's win |
| `%ymm` (AVX2) | **14,314** | 294 | native enabled AVX2 widths |
| `vpshufb` | **211** | 26 | swizzle widened |
| **`vpgatherdd`** | **0** | 0 | **DEFECT: `std::simd` does not lower `gather_select_unchecked` to a true AVX2 gather even at `target-cpu=native`.** The gather at `:610` lowers to scalar/fallback movs. Known LLVM portable-SIMD gap; the "fix #4 last resort" not taken. |
| `madvise` | 8 | — | mmap advice call sites (Fix #2/#3) |

**This is the kernel's "how the math is run" defect:** the gather — the
second third of the loop — never uses the hardware gather instruction.
Documented so an M3 (real gather) change has a concrete baseline to beat, and
so the `vpgatherdd`=0 observation isn't re-discovered from scratch.

## E7 / native rebuild status (the gates this math gate lives under)

E7 = the dotvbyte compressed-forward gate (replacing the f16 forward with
FixedU8Q-packed dotvbyte). Pre-registered bars
(`scripts/seismic_testbed/e7_dotvbyte_gates.py:184-188`):

| Gate | Bar | Status (2026-07-03) |
|---|---|---|
| gate a parity | `overlap@10 >= 0.99` | **PASS** — 0.995 robust across arms |
| gate b warm latency | `warm_p50_ratio <= 1.07` | **PASS (RECLEARED by Fix #1 native rebuild)** — Arm E1 3/3 PASS, median **0.957** |
| gate c cold majflt | `majflt_cold_ratio <= 0.55` | **FAIL (NOT RECLEARED)** — **0.591** pre-registered / **0.560 fully calibrated** (Fix #4+#5B floors), deterministic; advice levers AND page-aligned placement refuted (doc 10 §7.4, 2026-07-03) |

Baseline constants (`e7_dotvbyte_gates.py:47-51`): `K_PRIME=200`,
`HEAP_FACTOR=0.8`, `WARM_REPEATS=5`.

Result JSONs: verdict `data/eval_results/seismic_e7_RECLEAR_VERDICT.json`;
deliverable `seismic_e7_armE1_native_reconfirm_k200_run1.json` (+run2/run3);
control `seismic_e7_armA_CONTROL_anchor.json` (SSE2, 0/2 FAIL at median 1.388);
arms `seismic_e7_arm{A,B,C,D,E1,E2,F1}_*_{run1,run2,run3}.json`.

Plan: `.claude/plans/seismic-e7-reclear-fixes.md`.

**GOTCHA recorded for the future:** E7 Fix #3 (`MADV_WILLNEED`, commit
`ae6d64c`) added an `madvise_willneed` FFI helper in `prefetch_with_range`,
objdump-verified 25 madvise call sites — but it was **refuted** (gate c
majflt unchanged at 0.591; warm p50 regressed 3-4× from the per-candidate
madvise syscall overhead) and reverted to CPU-prefetch-only. The helper is
kept `#[allow(dead_code)]`. Do not re-try `MADV_WILLNEED` per-candidate
without reading this result first.
