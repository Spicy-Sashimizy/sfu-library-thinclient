# Plan — Q1: E8 dv-v2 per-doc value scale (Stage 1, container, Rust)

**Pre-registered bars (doc 12 §3 Q1, written before Stage 1):**
- both shards 1–2 overlap@10 ≥ 0.99 (v2 dv vs f16 twins, n=100)
- on-disk size within ±2% of dv v1 (*est.* ~−6% per SFR1)
- warm p50 ratio ≤ 1.05× vs dv v1
- T1 sequential ≡ parallel green (v2 dir loads via the hybrid/parallel path)

**Stage 0 already GO** (0.997/0.993 vs FixedU8Q 0.985/0.984, shards 1–2, n=100;
`e8_stage0_perdoc_scale_20260708.json`). Stage 1 = codec + converter + reader
v2, shards 1–2 ONLY into NEW dirs.

## The change (one sentence)
Replace the global FixedU8Q (1/64) doc-value scale with a per-doc linear u8
scale: store `u8 = round(v / vmax_doc * 255)` + a per-doc `f16 vmax_doc`;
dequant `v' = u8/255 * vmax_doc`. Query side unchanged (proxy proved it).

## Why a format-version bump (not an in-place codec change)
The record envelope changes (a new per-doc f16 field), so a v1 reader must
refuse a v2 dir loudly (never silently mis-decode). There is NO magic/version
field anywhere today — only `manifest.json`'s `forward_format: Option<String>`
string. **Decision: add `forward_format_version: u32` (serde default 1) to
`MmapManifest`** — decouples format-name from version, cleanest for a
same-filename `forward_data.bin` record-envelope bump (the agent's recommended
option). v1 stays version-absent (=1); v2 sets it to 2.

## Files + concrete edits

### A. The codec (spike/vectorium_fork — 5 edits in 1 file)
File: `spike/vectorium_fork/src/encoders/dotvbyte_fixedu8.rs`

1. **Record writer** `push_vector` (lines 772–843): prepend a per-doc `f16
   vmax_doc` to the record. Compute `vmax = f16(max values)` from the incoming
   u8 values' dequantized originals BEFORE packing; re-quantize the values to
   `round(orig / vmax * 255)`. The incoming values are already FixedU8Q u8 —
   Stage 1 keeps the u8 *width* but changes the *scale*. (Detail to resolve in
   impl: the encoder receives already-quantized u8; the per-doc scale needs the
   ORIGINAL f32/f16 values. So the From conversion in (B) must pass originals.)

2. **Record reader** `from_unchecked_slice` (lines 717–770): parse the per-doc
   f16 vmax from the front of the record (shift all offsets by
   `size_of::<f16>()`). Bump the record struct with a `vmax: f16` field.

3. **f32 dot kernel** `dot_product` (892–931): dequant via `u8/255 * vmax`
   instead of `simd_fixedu8_to_f32` (bits/64). The per-doc `vmax` is now on the
   view → multiply the accumulated result by `vmax/255` (factor it out of the
   loop: `sum(u8 * q) * vmax / 255`). The `values_remaining` scalar path (920)
   uses `vmax/255 * u8` too.

4. **int6 kernel** `dot_product_int6` (949–983) + `int6_scale` (663–664): the
   int6_scale hardcodes `doc_scale = 1/64`; replace with the per-doc `vmax/255`
   → `int6_scale = q_max/63 * vmax_doc/255`. **Caveat:** the int6 path is M2
   (NOT promoted, env-gated off); for Stage 1 the int6 path may be left to
   return a WRONG score when M2 is off (it's never called on the served path) —
   gate it behind a `#[cfg]`/runtime check that the v2 codec refuses int6, OR
   implement it correctly. **Decision: implement correctly** (it's the same
   factor-out) so M2 stays composable later; ~3 lines.

5. **Tests** (the existing `#[cfg(test)]` block at the end of the file): add a
   round-trip test asserting v2 dequant error ≤ `vmax/255` (the per-doc step)
   and a cross-version-rejection unit test at the reader level.

### B. The From conversion that quantizes (spike/vectorium_fork)
File: `spike/vectorium_fork/src/datasets/packed_dataset.rs` lines 425–477
(`impl From<SparseDatasetGeneric<...>> for PackedSparseDataset<DotVByteFixedU8Encoder>`)

- The current `ScalarSparseQuantizer` quantizes f32→FixedU8Q (1/64). For v2,
  pass the ORIGINAL f16 values through to the encoder so `push_vector` can
  compute per-doc vmax + re-quantize to u8-linear. **Approach:** add a v2
  constructor path (`PackedSparseDataset::from_with_value_scale`) that bypasses
  the ScalarSparseQuantizer's 1/64 and feeds originals + a `PerDocLinear` scale
  mode. Keep the v1 path untouched (the served dv v1 shards depend on it).

### C. The converter + layout version (spike/seismic_upstream — mmap_io.rs)
File: `spike/seismic_upstream/src/mmap_io.rs`

1. `MmapManifest` (lines 96–135): add `forward_format_version: u32`
   (`#[serde(default = "one")]` → default 1). Add `is_dotvbyte_v2()` =
   `is_dotvbyte() && forward_format_version == 2`.

2. `convert_f16_dir_to_dotvbyte` (1452–1677): add a `value_scale: ValueScale`
   enum arg (`Fixed` = v1 1/64, `PerDocLinear` = v2). When PerDocLinear, use the
   v2 From conversion (B), set `forward_format_version = 2` in the written
   manifest, and **relax the sanity gate** (line 1513, `1.0/64.0` → the per-doc
   step `vmax/255`) so v2's larger dequant error doesn't false-fail.

3. **Cross-version rejection**: `MmapSeismicIndexDotVByte::from_mmap` (1127): a
   v1 reader must refuse a v2 dir (`forward_format_version == 2` on a v1-only
   build → `Err("dotvbyte v2 dir — needs a v2-aware reader")`). And a v2 reader
   must refuse v1 (`forward_format_version != 2` when v2 requested → `Err`).
   The existing strict-equality `is_dotvbyte()` already rejects a v2 string if
   we used the string route; with the numeric version route we add an explicit
   check.

### D. The pyo3 dispatch (spike/seismic_upstream — pylib/mmap_index.rs)
File: `spike/seismic_upstream/src/pylib/mmap_index.rs`

1. `PyMmapIndex::new` (53–101): the JSON sniff (79–83) reads
   `forward_format`. Extend to read `forward_format_version`; route v2 → a new
   `AnyMmapIndex::DotVByteV2(MmapSeismicIndexDotVByteV2)` arm, OR (simpler) make
   `MmapSeismicIndexDotVByte` version-aware internally (one struct, version
   field, branches in the kernels). **Decision: one version-aware struct**
   (avoids duplicating the whole reader; the kernel branches on
   `value_scale`). Add `AnyMmapIndex` arm only if a separate struct is cleaner
   — weigh in impl; the agent map favors one struct + a version field.

2. `get_forward_format` (333–339): return `"dotvbyte_fixedu8_v2"` for v2 dirs.

### E. The converter bin + Python driver
- `spike/seismic_upstream/src/bin/convert_f16_to_dotvbyte.rs`: add
  `--value-scale {fixed,perdoc}` (default fixed = v1).
- `scripts/seismic_testbed/convert_shard_to_mmap.py`: add `--value-scale` pass-
  through. Convert shards 1–2 f16 → v2 into NEW dirs
  (`global_shard{1,2}of8.dotvbyte.e5.v2.mmap/`) — never overwrite the served v1
  e5 dirs (Rule Zero).

### F. The gate harness (Python)
New: `scripts/seismic_testbed/e8_dvv2_gates.py` — mirroring `e7_dotvbyte_gates.py`:
load the v2 shard via `MmapSeismicIndex`, run overlap@10 vs the f16 twin
(n=100, shards 1–2), the size delta, warm-p50 ratio, and T1 (v2-dir served via
the hybrid/parallel path, bit-identical seq≡par). Reuse the f16 twin at
`global_shard{1,2}of8.mmap`.

## Build + run order (container)
1. `cargo build --release` vectorium fork + seismic fork (maturin develop into
   the venv) — the `.so` rebuild. **NOTE:** Q7 uses the current `.so`; do NOT
   rebuild while Q7 is running. Stage 1 builds after Q7 frees the .so, OR in a
   separate venv build. Stage 1's v2 changes must not break v1 (served dv
   shards keep loading — `forward_format_version` defaults to 1).
2. Convert shards 1–2 f16 → v2 (new dirs). ~minutes each.
3. Run `e8_dvv2_gates.py`. Record bars.

## Risk + non-goals
- **Risk: v2 record envelope breaks v1.** Mitigated by the numeric version +
  cross-version rejection + default-1 serde. v1 served shards MUST still load
  unchanged (verified by re-running the existing T1 suite after the build).
- **Risk: per-doc vmax costs a per-doc f16 (~18.8M × 2B = 38 MB/shard) + the
  re-quant changes the u8 distribution** (size within ±2% bar — *est.* −6%, but
  the per-doc f16 adds back ~+0.7%; net *est.* still < ±2%).
- **Non-goal (Stage 2):** full 8-shard re-conversion. The plan folds the E5
  perm into Stage 2's single rewrite (doc 13 §3) — NOT done here.
- **Int6/M2 path:** kept composable but the M2 gate stays env-gated OFF
  (math_optimization/07); v2 doesn't promote M2.

## Rollback
v2 dirs are NEW; the served v1 e5 manifest is untouched. A v2 failure = delete
the 2 new dirs; served path unaffected. No `THIN_CLIENT_SWAP.md` flip in
Stage 1 (that's Stage 2, host-tier, after full-corpus gating).
