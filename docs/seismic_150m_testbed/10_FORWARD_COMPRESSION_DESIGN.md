# 10 · Compressed Forward Record for Mmap Serving (SFR1 design → DotVByte implementation)

**Created 2026-07-02. Status (2026-07-03, E7b host run): IMPLEMENTED (E7) —
converter + reader SHIPPED and gated on the real 18.8M shard0. Parity PASSED
on shard0 (0.995 — but this was the best-case shard; full-corpus is marginal,
see the §7.6 update below); gate (b) warm latency RECLEARED at 0.957× by the native rebuild
(§7.1); gate (c) landed at 0.560 vs the 0.55 bar with the micro-lever space
exhausted (§7.1–§7.4). The decisive E7b RAM-capped re-bench (§7.5, host,
2026-07-03) then CONFIRMED the pre-registered promotion hypothesis: at a 4 GB
cap f16 cliffs (warm p50 1.3–1.9 s, ~100–173k majflt/pass) while dotvbyte
stays fully warm (3.3 ms, 0 majflt). **PROMOTED for RAM-constrained deploys**
(per-shard cache budget below f16's measured 5.18 GiB working set); f16
remains the default when the corpus fits page cache. Gate c CLOSED as
superseded — E7b answered directly the deploy question the fault ratio
proxied. See §7.5.**

> **Full-corpus parity update (G8d · 2026-07-05 · §7.6).** The shard0 0.995
> parity was the *best-case* shard. Extending the identical gate-a convention
> to all 8 dv shards: overlap@10 averages **0.9906** (mean of shard means) but
> is **not uniform** — shards 1 and 2 land at **0.985**, below the per-shard
> 0.99 gate (2 of 8 FAIL; `all_8_shards_pass_0.99 = false`). Quality parity
> holds on the corpus average, **not per-shard**. Promotion stands (0.985–0.995
> rank agreement is still high), but the parity claim is downgraded from
> "0.995, comfortably passes" to "≈0.99 corpus mean, marginal." Accepted as
> the recorded parity figure (user decision 2026-07-05, §7.6). See §7.6.

> Parent: `09_CROSS_SHARD_MMAP_AUDIT.md` §3.3 lever "forward value/component
> width" (was literature-only: DotVByte / 4-bit summaries) and §3.2 page
> economics. This doc replaces the literature placeholder with a codec designed
> against THIS corpus's measured statistics and prototyped on 50,000 real
> shard0 documents. Experiment id: **E6**. Result file:
> `data/eval_results/seismic_e6_forward_codec_proto_20260702_2346.json`
> (script `scripts/seismic_testbed/e6_forward_codec_proto.py`).

## 0. Why the forward index, and why these two numbers rule everything

From the 09 audit (all measured): the forward index is **85% of shard bytes**
(shard0: 6.74 GB of 7.9 GB) and is read as **~350 B random probes split across
two files** (`forward_components.bin` u16 + `forward_values.bin` f16), i.e.
**≈ 2.09 expected 4 KB page faults per scored candidate** — and
candidates-scored is the page-touch elephant (60–90k/shard/query *est.*).
File-backed pages bypass zram/zswap (`08_LATENCY_RESEARCH.md` §E), so the only
levers that exist under mmap serving are (a) touch fewer pages and (b) make
the bytes smaller so the same page cache holds more of the corpus. SFR1 does
both at once; it is a **LAYOUT-class** change (converter rewrite + reader
fork), no SEISMIC re-clustering and no quality-relevant math changed except
the value quantization measured here.

## 1. The format

One interleaved file `forward_records.bin` replaces `forward_components.bin` +
`forward_values.bin`; `forward_offsets.bin` shrinks u64 → u32 (compressed file
< 4 GiB/shard, guard at convert time).

```
per-doc record (byte-aligned, random access via offsets[doc]):
  u16  first_component_id      — in the df-rank-remapped id space (§2.2)
  f16  vmax                    — per-doc value scale (exact: it IS an f16 value)
  var  LEB128[nnz-1] gaps      — gap-1 over strictly-ascending component ids
  u8   codes[nnz]              — value ≈ code/255 · vmax

nnz is DERIVED from the offsets table (measured over ALL 18,799,322 shard0
docs: 7 ≤ nnz ≤ 256 — a build-time top-256 cap) and never stored.
```

Decode = walk ≤255 varints (prefix-sum to ids) + one multiply-add per value.
Arithmetic precedent: C0.5 measured the much heavier EliasFano+BitField decode
at 1.07× — the Rust decode-cost gate for SFR1 is set at the same envelope.

## 2. Every choice is a measurement, not a default (E6 phase A, 2026-07-02)

Sample: 200,000 uniform-random shard0 docs (nnz/offsets), 50,000 fully decoded
(gaps/values/codec), seed 42. All sampled docs strictly ascending in
components (the gap premise); nnz mean 87.6, p50 82, p99 255.

### 2.1 Interleaving is the single biggest page win — and it's free

| Layout | E[4 KB pages / scored candidate] |
|---|---|
| current (two files, ~175 B in each) | **2.09** |
| SFR1 (one record, mean 194.8 B) | **1.05** |

Nothing about compression is needed for this half of the win: co-locating a
doc's components with its values halves candidate faults by construction.

### 2.2 df-rank id remap: the corpus's token-frequency skew is worth 8 bits/doc — free

Token ids reassigned by descending document frequency at convert time (the
posting-list array, summaries, and token map reorder consistently; queries are
token-STRING keyed, so scores cannot move — same argument as E5's permutation
parity). Measured on real gaps:

| id space | gap entropy (bits) | varint components B/doc |
|---|---|---|
| current ids | 8.23 | 113.6 |
| **df-rank ids** | **7.40** | **105.2** (entropy bound 82.1) |

### 2.3 Byte-varint gaps: the gap tail kills fixed-width

Gap distribution (gap−1): p50 = 39, p90 = 471, p99 ≈ 2,539, max ≈ 20k → per-doc
fixed width lands at 12–13 bits (135.0 B/doc), losing to byte-varint (113.6 B).
Nibble-varint saves a further ~15 B/doc (89.7 B at df-rank) and was declined
for v1: bit-fiddly decode for ~7% of record size. Recorded so v2 knows the
headroom.

### 2.4 Per-doc linear u8 values: the "obvious" corpus codebook LOSES here

Values are f16, all positive, global range [0.01, 3.25], per-doc vmax p50 ≈ 2.0.

| quantizer (8-bit) | rel-L2 error (mean) |
|---|---|
| **per-doc linear (code/255 · vmax)** | **0.329%** (p95 0.431%) |
| global 256-quantile codebook fit on this corpus | 1.276% |

The per-doc scale adapts to each doc's dynamic range and beats the
corpus-fitted codebook by ~4× — the reverse of the intuition that a customized
codebook must win. Components stay **lossless** (round-trip asserted per doc
in phase B).

## 3. Measured codec results (E6 phase B — 50,000 real docs encoded)

| Metric | Current | SFR1 | Δ |
|---|---|---|---|
| record bytes/doc (mean) | 350.5 (two files) | **194.8** (p50 183, p99 523) | **1.80×** |
| E[pages/candidate] | 2.09 | **1.05** | **2.0×** |
| shard0 forward bytes | 6.59 GB | **3.66 GB** (+offsets 150→75 MB) | −44% |
| 8-shard corpus forward | 52.7 GB | **~29.3 GB** *est. (uniform shards)* | −23 GB |
| component round-trip | — | LOSSLESS (asserted) | — |
| value rel-L2 | 0 | 0.33% | see §4 gate |

Whole-index projection: 62 GB converted → **~38.6 GB** *est.* — the warm
working set the 40-diverse-query workload touches (~40 GB, A1 #3) would
compress proportionally on its forward-dominated share, moving the
flat-then-cliff RAM knee (measured ~650× at the cliff) left by roughly the
same 40% on the forward component. *est.* until E6-impl measures it.

## 4. Serving-quality gate (E6 phase C — real queries, real engine candidates)

Method: 40 diverse queries (the E1 workload), baseline engine search on the
real mmap shard0 (all-terms, query_cut=all, hf=0.8, k′=200 — recall-max
params), then every returned candidate re-scored in Python two ways: exact
f32-from-f16 (sanity-anchored against the engine's own scores) and under SFR1
per-doc-u8 values. Overlap of the re-ranked lists:

| Metric | Value | Gate |
|---|---|---|
| overlap@10 (mean over 40 q) | **0.995** | ≥ 0.99 → **PASS** |
| overlap@10 (min) | 0.90 (worst query: one doc swapped at the top-10 boundary) | — |
| overlap@50 (mean) | 0.9975 | — |
| engine-vs-python exact-score max rel diff | **0.0** — the Python re-scoring reproduces the engine's forward scores bit-exactly, so the proxy measures ONLY the quantization effect | — |

**Honesty box:** this is a *scoring-side* proxy on the engine's own top-k′
candidates. It does not capture the second-order effect of quantized scores on
the heap-min block-skip test during traversal (bounded by the 0.33% score
error). The implementation must re-run the E-series parity convention
(overlap@10 vs the f16 shard on the same 40 queries, plus the T1
sequential-parallel identity) before any converted shard serves.

## 5. Implementation (E7 — SHIPPED 2026-07-03, built on DotVByte, not custom SFR1)

**The E6b decision (2026-07-02, `seismic_e6b_fixedu8_quality_20260702.json`):**
the vendored vectorium fork already carried a complete SIMD Stream-VByte packed
forward (`DotVByteFixedU8Encoder` + `PackedSparseDataset` + an owned search
path + `convert_dataset_into` range rewriting) with a **trained component
remap handled inside the encoder** — i.e. §2.2's remap idea with zero
consistency surface (posting lists/summaries stay in the original id space;
the query evaluator remaps on densify). Its value type `FixedU8Q` is a GLOBAL
1/64 fixed-point scale rather than SFR1's per-doc scale; re-running the E6
phase-C proxy with FixedU8Q semantics measured **overlap@10 0.995 — identical
to SFR1's** (overlap@50 0.9945 vs 0.9975). With quality equal, reuse won over
the custom codec. SFR1's per-doc scale + LEB128 spec (§1–§2) stays on record
as the fallback design (~6% smaller records) had the gate failed.

What shipped (all in the spike forks; main-repo record =
`spike/seismic_upstream_fork.patch` + tracked `spike/vectorium_fork`,
`spike/toolkit_fork`; fork-local commit c987160):

1. **Converter** — `convert_f16_dir_to_dotvbyte` (`mmap_io.rs`) + the
   `convert_f16_to_dotvbyte` bin: **file-level f16 `.mmap` dir → dotvbyte
   `.mmap` dir** (the K=8 `.index.seismic` sources are gone from /tmp; the
   persistent mmap dirs are the artifact of record, so the converter never
   needs an owned index load). Forward re-encoded via the existing trained
   `From` impl; **only each packed posting's u64 is rewritten**
   (elem-offset:48|nnz:16 → word-offset:48|word-len:16); block offsets,
   summaries, EliasFano bytes copied verbatim ⇒ the block-skip math is
   bit-identical to the f16 shard. Measured on shard0 (2026-07-03): 18.8M docs
   converted in **208 s** (~11 GB peak RSS), 40.36M packs rewritten, 2001 docs
   decode-verified (components lossless; max value err exactly 1/128).
2. **Reader** — `MmapSeismicIndexDotVByte` over a borrowed
   `MmapPackedSparseDataset` (new in the vectorium fork) + a
   `forward_format` manifest switch. The pyo3 class `seismic.MmapSeismicIndex`
   dispatches on the manifest, so `seismic_backend.py` /
   `sharded_seismic_backend.py` serve either layout with **zero Python
   changes** (`.forward_format` getter added). Posting-list reconstruction is
   shared code with the f16 reader (`read_posting_lists`). Wrong-loader use
   fails loud in both directions. `touch_slab`/`release_pages` (mechanism B)
   implemented over the dotvbyte slab set.
3. **Tests** — `dotvbyte_convert_parity` (tiny index → write → convert →
   cross-loader rejection → search parity within the FixedU8Q envelope) and
   the pre-existing `mmap_parity_twin` (f16, still green post-refactor).
4. **Interaction with E5 (semantic forward ordering)**: unchanged — orthogonal
   and composable; both rewrite the converter.

## 6. Shard0 artifacts (2026-07-03)

| Dir | Bytes (whole dir) | Forward bytes |
|---|---|---|
| `global_shard0of8.mmap` (f16) | 8.08 GB | 6.74 GB |
| `global_shard0of8.dotvbyte.mmap` | 5.38 GB (**1.50×**) | 3.97 GB (**1.70×**) |

(1.70× vs SFR1's prototyped 1.80×: Stream-VByte control bytes + u64 record
padding + bisection-remap-vs-dfrank differences. Conversion report:
`convert_f16_to_dotvbyte` stdout, logged in the E7 result JSON's meta.)

## 7. E7 gate results (2026-07-03) — the pre-registered §5 gates, honestly

Run: `scripts/seismic_testbed/e7_dotvbyte_gates.py`, 40 diverse queries,
recall-max params (all terms, qc=all, hf=0.8, k′=200), release_pages before
each cold pass (E1 method). Result
`data/eval_results/seismic_e7_dotvbyte_gates_20260703_0032.json`. **Verdict:
`E7_GATE_FAIL: b_latency,c_pages`.**

> **Update 2026-07-03 — reclear pass (§7.1–§7.2 below):** gate (b) warm latency was
> **robustly recleared** to 0.957× (3/3 PASS) by Fix #1, the
> `RUSTFLAGS=-C target-cpu=native` rebuild (the .so had been built SSE2-only,
> leaving the DotVByte SIMD/FMA decode unaccelerated; objdump-verified). Gate
> (c) cold majflt **NOT recleared** — Fix #2 `MADV_RANDOM` was refuted as an
> artifact (it quadruples absolute faults; see §7.1) and Fix #3
> `MADV_WILLNEED` per posting block was refuted too (zero effect on faults +
> a warm regression from syscall overhead; see §7.2). Gate c appears to be a
> structural floor, not a tunable advice axis. Parity 0.995 held throughout.
> The native rebuild is the shippable delta; E7 stays un-promoted pending
> gate (c) / E7b.

| Gate | Bar | Measured | Verdict |
|---|---|---|---|
| (a) parity overlap@10 | ≥ 0.99 | **0.995** (min 0.90) — exactly the E6/E6b proxy prediction | **PASS** |
| (b) warm traverse p50 | ≤ 1.07× f16 | **1.223×** (7.12 ms vs 5.82 ms) | **FAIL** |
| (c) cold majflt | ≤ 0.55× f16 | **0.591×** (69,148 vs 116,974) | **FAIL (narrow)** |
| — cold traverse p50 | (not a gate) | **0.70×** (470 ms vs 672 ms — 1.43× faster) | — |

Reading, without spin:

- **(b) is the real miss.** The 1.07× bar was borrowed from C0.5, which
  measured a *different* decode (EliasFano/BitField summaries). Stream-VByte
  gather-dot decode costs ~22% warm — squarely the literature's ~1.2×
  (`08` §B1), which the bar should have anticipated. Warm cost is per-shard
  CPU: at the federated level (+~1.3 ms on a parallel leg whose system p50 is
  ~58–80 ms) it is small but real, and it is paid on every warm query.
- **(c) missed its bar but confirmed its mechanism.** The 0.55 bar was derived
  from the forward-only page model (§3.2: ~2 → ~1 pages/candidate ⇒ ~0.5),
  ignoring that whole-process majflt includes the unchanged posting-list and
  doc-mapping faults. Faults fell 41% and cold latency 30% — the interleave +
  compression showed up exactly where predicted; the bar was miscalibrated,
  not the mechanism. The §5 kill criterion ("kill if it doesn't show up in
  faults") is NOT triggered.
- **The trade on the table:** −41% faults, −2.7 GB/shard on disk/cache
  (−21.6 GB corpus *est.* ×8), −30% cold latency — for +22% warm traversal.
  Under the flat-then-cliff RAM economics (A1 #3: ~650× cliff), the dotvbyte
  shard wins whenever the box is page-constrained (the whole reason this
  track exists) and loses ~1.3 ms/query when everything is already cached.

**Decision: NOT promoted to serving default (gates failed as registered).**
The converted shard0 dir is kept as the E7 artifact. Owed follow-ups, in
information-per-cost order:

- **E7b — the RAM-constrained re-bench (the decisive one):** repeat the
  f16-vs-dotvbyte comparison under the A1 #3 container-cap method at the
  operating point where the f16 corpus no longer fits page cache (e.g. 24 GB
  for 8 f16 shards). Hypothesis: dotvbyte's −41% faults dominates and its
  warm-CPU penalty is invisible next to re-fault stalls; if TRUE at a cap
  where f16 has cliffed and dotvbyte has not, promotion is justified for
  RAM-constrained deploys regardless of gate (b). **→ RUN 2026-07-03 (host):
  hypothesis CONFIRMED at the 4 GB cap — see §7.5.**
- **k′ interplay:** E1's recall-safe k′=100 halves candidates; measure whether
  it shrinks the dotvbyte warm gap (decode cost scales with candidates).
- **Warm decode tuning** (only if E7b says promote and (b) still hurts):
  per-block prefetch depth / gather width in `dotvbyte_fixedu8.rs`.

### 7.1 E7 reclear — targeted fixes under a hard, pre-registered protocol (2026-07-03)

A follow-up pass implemented the two researched fixes for the failed bars and
re-ran them under a *pre-registered* protocol: same 40 queries, same shard0
twins, k′=200, bars unchanged, **2–3 replicates per arm** with warm-p50
stability checked. (Arm A — control re-run — found the warm ratio spans
1.22–1.44 at `WARM_REPEATS=5` (~18% noise) because the ratio amplifies f16+dv
variance on a sub-ms warm microbench; the reclear arms use `--warm-repeats 15`
for a stable per-query median *without changing the bar*.) Verdict file
`data/eval_results/seismic_e7_RECLEAR_VERDICT.json`; per-arm jsons alongside.

**Fix #1 — `RUSTFLAGS="-C target-cpu=native"` rebuild (gate b).** No code
change. `RUSTFLAGS` was empty; the .so was compiled for baseline x86-64
(SSE2). The DotVByte decode hot loop
(`vectorium_fork/.../dotvbyte_fixedu8.rs`) is `std::simd` portable SIMD —
`Simd::<f32,8>` FMA accumulate + `Simd<u8,16>` shuffle-decode + a
`gather_select_unchecked` — that lowers to SSE2/scalar without the target.
**objdump-verified:** the native build added **+54 packed `vfmadd…ps`,
+14,020 `ymm` regs, +185 `vpshufb`** (baseline had 0 / 294 / 26). The packed
`vpgatherdd` stayed at 0 — `std::simd`'s gather does not lower to hardware
gather even with `target-cpu=native` (LLVM portable-SIMD gap; the researched
"last-resort gather tune" was *not* taken). cargo unit tests 5/5 PASS at
native (FMA float-rounding did not break parity). **Gate b: ROBUSTLY
RECLEARED** — deliverable arm E1 (native-only, k′=200): 0.957 / 0.946 / 0.976
(3/3 PASS, median 0.957 ≤ 1.07), vs control A's 1.338 / 1.436 (0/2). Native
also roughly halved f16's warm p50 (AVX2 benefits it too). **Parity held at
0.995 throughout. SHIP — zero-risk, highest-leverage.**

**Fix #2 — `MADV_RANDOM` on the forward files (gate c).** The audit's E2.
Hypothesis: suppress readahead overshoot on the ~200 B random candidate reads
→ fewer faults. **REFUTED by experiment.** `MADV_RANDOM` disables readahead
entirely → every 4 KB page faults individually. Absolute majflt
**quadrupled**: f16 116,974 → 437,219 (3.74×), dv 69,148 → 235,914 (3.41×);
cold latency worsened (f16 668 → ~1,595 ms). Gate c *appeared* to pass in arm C
(0.54) but only because MADV_RANDOM hurt f16 *worse* than dv, improving the
*ratio* — arm D (dv-only) isolates this: with only dv advised, the ratio jumps
to **2.017** (dv = 2× f16's faults). There is no genuine dv benefit; the
bar-as-written was gameable on an axis the bar's *intent* (fewer disk faults
per candidate) does not endorse. **DO NOT SHIP.** Disabled
(`leak_mmap_advise(.., false)` on all forward files); the helper is kept as
infrastructure.

**(k′=100, arm E2, *different footing*):** gate c 0.583 (still > 0.55), gate b
0.946/1.086/1.07 (straddles at the lower candidate count). Halving k′ does
NOT clear gate c either — it is not an escape hatch.

**Net same-footing verdict:** 1 of the 2 failed bars robustly recleared —
**gate b, via the free native rebuild** (the .so is already rebuilt in the
venv). **Gate c remains OPEN** (best honest config = 0.591); Fix #2 refuted,
the next lever is Fix #3 (batch `MADV_WILLNEED` per posting block), *not*
`MADV_RANDOM`. **E7 still NOT promoted** (gate c open), but the native build
is the shippable delta and closes the warm-latency gap decisively. E7b (the
RAM-capped re-bench above) remains the downstream promotion gate.

### 7.2 E7 reclear — Fix #3 `MADV_WILLNEED` per posting block (2026-07-03, REFUTED)

Fix #3 was the remaining honest gate-c lever (the audit's "batch `MADV_WILLNEED`
before scoring"). `evaluate_posting_block` already has a two-phase shape — phase
1 calls `prefetch_with_range` (previously a *CPU cache-line* prefetch,
`core::intrinsics::prefetch_read_data`, which does nothing for cold **page**
faults), phase 2 calls `get_with_range` (the read that takes the fault). Fix #3
added `madvise(MADV_WILLNEED)` over each candidate's exact byte range in phase
1, so phase 2's serial blocking faults should become overlapped async readahead.
Implemented in the vectorium fork (`madvise_willneed` helper, direct `extern "C"`
FFI, no `libc` dep) wired into **both** `prefetch_with_range` impls (packed
dotvbyte + sparse f16) — symmetric, advising *exact candidate ranges* (not whole
files), so no f16-vs-dv asymmetry to game the ratio (the trap that refuted
Fix #2). objdump verified 25 madvise call sites in the rebuilt .so.

**Result: REFUTED** (Arm F, 3 runs, k′=200, warm_repeats=15):

- **Gate c (the target): NO effect.** majflt ratio **0.591 unchanged** (f16
  116,954 / dv 69,124 vs base 116,982 / 69,149). Cold latency also unchanged
  (f16 646→686 ms, dv 428→435 ms, within noise). The async-readahead hypothesis
  is falsified on this kernel/WSL2 — the kernel did not honor `MADV_WILLNEED`
  on these ranges, or the default readahead already overlaps the faults enough
  that explicit `WILLNEED` adds nothing.
- **Gate b: artifact regression.** Warm p50 got **3–4× worse for both formats**
  (f16 2.07→8.13 ms, dv 2.00→5.66 ms) from per-candidate `madvise()` syscall
  overhead (~25 syscalls/block). The ratio *appeared* to improve to 0.696 only
  because f16 issues more madvise calls (2 slices: components+values) than dv
  (1 slice: data). A slower-both ratio improvement is **not** a latency win.
- **Parity held** (0.995 ×3 — `MADV_WILLNEED` is pure advice).

**DO NOT SHIP.** Reverted `prefetch_with_range` to CPU-prefetch-only (the native
rebuild's gate-b 0.957 PASS is the proven best); `madvise_willneed` kept as
infrastructure (`#[allow(dead_code)]`). Deliverable .so reconfirmed native-only
(Arm G): gate b 0.99/0.937 (PASS ×2, warm back to ~2.1 ms), gate c 0.591 open.

**Gate-c conclusion after the reclear pass:** *both* kernel-advice levers for
gate c are now refuted — Fix #2 `MADV_RANDOM` (quadruples faults; ratio was an
artifact) and Fix #3 `MADV_WILLNEED` (zero effect + warm regression). Gate c at
0.591 appears to be a **structural floor** of the forward reading pattern, not a
tunable advice axis. The remaining escapes are: **(i)** E7b — the RAM-capped
re-bench where dotvbyte's −41% faults should dominate once the f16 corpus
exceeds page cache (the regime this track exists for); or **(ii)** accept gate c
as a **miscalibrated bar** (the 0.55 modeled *forward-only* faults; whole-process
majflt includes the unchanged posting-list + doc-mapping fault floor, which no
forward codec can move). Gate b, the real miss, is closed by Fix #1.

### 7.3 E7 Fix #4 — prefault the floor so gate-c charges forward-only faults (2026-07-03, REFINED the bar; did NOT clear 0.55)

§7.2 escape **(ii)** — the "miscalibrated bar" hypothesis — is exactly testable
without shipping a different index: the gate-c 0.55 bar was *modeled* on
forward-codec faults only, but the measured `majflt_cold` (the
`/proc/self/stat` field-12 delta around the `release_pages → cold search`
pass) also charges the **constant** posting-list + doc-mapping floor that
faults identically for both codecs. That constant sits in *both* the numerator
and denominator, dragging the ratio toward 1.0 and hiding the forward-codec
delta the bar was meant to expose. Fix #4 removes it from both sides
symmetrically: a measurement-calibration fix, not a dv-preferring optimization.

**Implementation** (`spike/seismic_upstream/src/mmap_io.rs` +
`src/pylib/mmap_index.rs`):

- New `MmapSeismicIndex::prefault_floor()` (both f16 and DotVByte impls) does a
  dense sequential fault-in (`MADV_WILLNEED|SEQUENTIAL` + one page-stride read,
  the existing `touch_bytes`) over **only** the posting-list + doc-mapping
  slabs — leaving the forward-codec files to be faulted by the next `search`.
  This is the slab-granularity `readahead()`/`MADV_WILLNEED` use the man pages
  describe (it reduces major-fault *count*, fd-aware), *unlike* Fix #3's
  per-candidate 200 B advice (which the kernel ignores + adds syscall
  overhead). Exposed via pyo3 as `MmapSeismicIndex.prefault_floor()`.
- **Latent measurement-integrity bug fixed alongside:** the f16 path's
  `forward_components.bin` (3.3 GB) and `forward_values.bin` (3.3 GB) leaks
  were never retained as struct fields, so `release_pages()` could only
  `MADV_DONTNEED` the 150 MB offsets slab — the 6.5 GB forward elephant stayed
  resident across cold cycles, mis-attributed to the "floor". Both handles are
  now retained (`_forward_components_mmap` / `_forward_values_mmap`) and
  `release_pages` evicts them.
- Harness env-gate: `e7_dotvbyte_gates.py run_pass` calls `prefault_floor()`
  *after* `release_pages()` and *before* the `mj0` baseline only when
  `SFU_SEISMIC_PREFLOOR=1`. Default off → the pre-registered footing (0.591)
  is bit-identically reproducible. Recorded as `meta.prefloor_on` in the
  result JSON.

**Result** (Arm G native, 3 runs each, k′=200, warm_repeats=15, shard0 of 8):

| arm | gate-c ratio | f16 majflt | dv majflt | floor stripped (Δf16 ≈ Δdv) |
|---|---|---|---|---|
| control (prefloor off) | **0.591** ×3 (deterministic) | 116,975 | 69,147 | — |
| Fix #4 (prefloor on)  | **0.572** ×2 | 111,882 | 64,051 | ~5,093 ≈ ~5,096 ≈ **~1.27 GB / 4 KiB** |

- **The calibration is genuine.** The floor prefault stripped an *identical*
  ~5,000-page constant from both codecs (~5,093 f16 vs ~5,096 dv), exactly as
  expected for the posting-lists (1.16 GB) + doc-mapping (0.36 GB) ≈ 1.52 GB
  floor ÷ 4 KiB ≈ 5,000 faults. The ratio moved in the gate's intended
  direction (0.591 → 0.572) — proof the floor was the model/measurement
  mismatch the memory ledger flagged, now removed.
- **Gate c does NOT clear 0.55.** 0.572 > 0.55. Stripping the constant floor
  moves the ratio only ~0.019 toward the codec; the *remaining* gap is the
  actual forward-codec fault advantage of the denser DotVByte layout, and it
  is smaller than the 0.55 the bar was calibrated on. The 0.55 model
  over-estimated dv's forward-only fault reduction at this shard size.
- **Parity held** (overlap@10 = 0.995 in every arm — prefault is pure advice).
- **Gate b unaffected** by Fix #4 (prefloor runs in the cold pass only, before
  the warm repeats; warm ratio 0.98–1.13 across arms = the same run-to-run
  noise as §7.1, not a Fix #4 regression).

**Verdict: REFINED, not recleared.** Fix #4 makes gate-c *measure what it
claims to measure* (forward-codec faults only) — the honest calibrated ratio is
**0.572**, not 0.591. It does not cross the 0.55 bar, so gate c stays OPEN, but
its open-ness is no longer attributable to a floor/calibration artifact. The
actionable escapes collapse to two: **(i)** E7b — re-bench under a RAM cap
where the f16 forward exceeds page cache (the regime where the −41% density
delta *must* dominate, per §7.2); or **(ii)** re-calibrate the bar to the
now-measured forward-only floor (≈0.55 → ≈0.50 would clear, but that is
moving the goalposts, not a code fix). Fix #4 ships as the always-on-honest
calibration + a latent release-integrity fix; `SFU_SEISMIC_PREFLOOR=1` is off
by default to preserve the pre-registered footing for result-attribution. The
shipped .so is native-only (Arm G: 88 vfmadd / 14,306 ymm, parity 5/5).

Result files: `data/eval_results/seismic_e7_dotvbyte_gates_20260703_04{37,42,45,48,51}.json`

### 7.4 E7 Fix #5 — page-aligned placement REFUTED; offsets-floor calibration lands 0.560 (2026-07-03)

Fix #5 attacked the two components of the remaining 0.572-vs-0.55 gap that a
pre-measurement predicted (pack-weighted analysis over ALL 40.36M shard0
posting packs, `scripts/seismic_testbed/e7_straddle_analysis.py`, 2026-07-03):
records straddling 4 KiB boundaries (5.01% of candidate reads, records mean
26.7 words / max 74) and the `forward_offsets.bin` slab being charged to the
codec.

**Fix #5A — page-boundary-aware record placement (REFUTED).** The converter
gained `--page-align` (`convert_f16_dir_to_dotvbyte(page_align=true)`,
`page_align_packed_forward` in `mmap_io.rs`, fork commit ff15883): when the
next record would straddle a 4 KiB boundary, the gap is absorbed as zero words
INSIDE the previous record, inserted before its end-anchored SIMD values tail —
decode is bit-identical (the DotVByte layout reads the dgap stream from the
front for exactly `n_packs` entries and locates values from the slice end), so
no reader change and every `offsets`/`id_from_range` consumer stays exact.
Verified three ways: cargo test `dotvbyte_page_align_parity` (exact score
parity aligned-vs-unaligned + no-straddle walk), converter post-padding
decode-verify (2001 docs lossless), and gate-a parity 0.995 in every arm.
Shard0 converted in 203 s; pad = 13,020,733 words = +2.73% forward bytes
(on-disk ratio 1.503→1.476), matching the simulation exactly.

**Result: dv absolute faults went UP, not down** — 64,052 → 65,378 (+2.1%,
deterministic ×3). Gate c (prefloor=1) 0.572 → **0.584**. The straddle model
was refuted by the kernel itself: **default readahead/fault-around already
absorbs a straddling record's continuation page** (the second page is pulled in
the same I/O and never counts as a separate major fault), so alignment removed
~nothing — while the +2.7% pad diluted incidental page-sharing between
candidates, adding ~1.3k faults. Consistent on every footing (prefloor=0:
0.591→0.602; prefloor=2: 0.560→0.572). Cold latency unchanged (373 vs 381 ms).
**DO NOT SHIP `--page-align`** for gate c; the converter capability + test stay
in the fork (they are the mechanism proof for any future placement work, e.g.
E5 clustering). The `…dotvbyte_pa.mmap` shard0 artifact was deleted after
measurement (reproducible in 203 s; the 9 result JSONs are the record).

**Fix #5B — offsets-slab floor completion (SHIPPED, the honest calibration).**
`prefault_floor(include_forward_offsets)` (+ harness `SFU_SEISMIC_PREFLOOR=2`):
`forward_offsets.bin` (150,394,584 bytes in BOTH layouts) is touched only by
the per-winner `id_from_range` binary searches — never by candidate reads,
which go through posting-pack ranges — so it is a symmetric constant exactly
like the Fix #4 floor, not part of the codec the 0.55 bar models. Measured: it
strips **−3,197 (f16) vs −3,200 (dv)** faults — identical constants, the same
symmetry signature as Fix #4's ~5,093/~5,096.

**The arm table** (Arm-G native .so, k′=200, warm_repeats=15, 40 queries,
parity 0.995 and gate-b PASS 0.879–1.104 throughout; every ratio deterministic
across reps):

| arm | dv layout | prefloor | gate-c | f16 majflt | dv majflt |
|---|---|---|---|---|---|
| H0 | shipped | 0 (pre-registered) | 0.591 | 116,976 | 69,148 |
| H1 | shipped | 1 (Fix #4) | 0.572 | 111,883 | 64,052 |
| **H5** | **shipped** | **2 (Fix #4+#5B)** | **0.560** | **108,686** | **60,852** |
| H2 ×3 | page-aligned | 1 | 0.584 | 111,883 | 65,378 |
| H3 | page-aligned | 0 | 0.602 | 116,976 | 70,474 |
| H4 ×2 | page-aligned | 2 | 0.572 | 108,686 | 62,178 |

Result files: `data/eval_results/seismic_e7_fix5_H{0,1,2,3,4,5}_rep*_20260703.json`.

**Verdict: gate c remains OPEN at the fully-calibrated 0.560** (bar 0.55). The
measurement now charges the codec for nothing but its own candidate reads, and
the micro-lever space is exhausted BY EXPERIMENT: MADV_RANDOM (×3.7 faults),
MADV_WILLNEED (no-op), page alignment (+2%), plus THP/COLLAPSE/SEQUENTIAL ruled
out by kernel docs and readahead tuning blocked by the drvfs mount. 0.560 is
the codec's real fault advantage on this platform: **~1.05 effective
pages/candidate for dv vs ~1.9 for f16 — the bar's ~2→1 model was right about
the mechanism and ~0.01–0.02 optimistic about the endpoint.** The remaining
honest moves, in information-per-cost order:

1. **E7b — the RAM-capped re-bench (the decisive one, now packaged).**
   Un-runnable in this container (cgroup2 ro, no docker daemon, WSL2 swapoff
   denied — verified 2026-07-03): needs the host. Bench script
   `scripts/seismic_testbed/e7b_ramcap_bench.py` (one codec per capped
   process, pre-encoded queries so torch never enters the cap, per-pass
   p50/majflt/VmSwap; smoke-tested uncapped: dv pass0 952 ms/41,224 faults →
   pass1 2.86 ms/0 faults) + runbook
   `scripts/seismic_testbed/HOST_PROMPT_E7B_RAMCAP.md` (cap sweep 8G/6G/4G,
   promotion decision rule, swap-confound guard). **→ RUN on the host
   2026-07-03; verdict in §7.5 (promotion CONFIRMED at the 4 GB cap).**
2. **E5 co-access doc reordering** — the one remaining code lever with real
   headroom (multi-record page sharing; what alignment could not provide), and
   the same lever `docs/math_optimization/03_INTERACTION_MAP.md` gates M5
   behind. Fix #5A adds a datum to its forecast: readahead already absorbs
   *adjacent* continuation reads, so E5's win must be simulated at page-touch
   granularity (the §7.4 pack-walk method) before building the id-indirection
   it requires. **→ SIMULATED GO 2026-07-09 (roadmap Q6):** on real
   `search_visited` candidate sets (shards 1–2, n=100), the buildable
   posting-pack-walk first-touch order simulates to **0.376–0.400× unique
   forward pages/query** (bar ≤0.45; dv geometry 0.382–0.400; log-driven
   ceiling 0.345–0.358; random control 1.01; 64KiB-cluster proxy 0.35–0.37,
   so fault-around only helps further). Converter build green-lit.
   `data/eval_results/q6_e5_coaccess_sim_20260709.json`, doc 06 row
   2026-07-09.
3. Re-calibrate the bar 0.55 → 0.57 (fully-calibrated footing) — records the
   truth but moves the goalposts; only defensible bundled WITH an E7b verdict.
   **→ MOOT 2026-07-03: §7.5 closes gate c as superseded rather than
   re-calibrated — the E7b verdict answers the deploy question directly, so
   the proxy bar no longer decides anything.**

### 7.5 E7b — RAM-capped re-bench VERDICT: promotion CONFIRMED at the 4 GB cap (2026-07-03, host run)

Run on the Windows host's Ubuntu WSL2 distro (NOT this container — see §7.4
item 1 for why), per `scripts/seismic_testbed/HOST_PROMPT_E7B_RAMCAP.md`:
`e7b_ramcap_bench.py`, one codec per `systemd-run --scope` capped process
(`MemoryMax`, `MemorySwapMax=0`), pre-encoded queries (torch outside the cap),
40 queries, k′=200, hf=0.8, 4 passes (pass 0 cold after page release; warm =
passes 1–3). Rule Zero held: shard checksums byte-identical before/after
(f16 8,277,840,964 B; dv 5,505,935,084 B), shards read in place, never staged.
Every cell `swap_confounded: false` (VmSwap 0 throughout). Result files:
`data/eval_results/e7b_global_shard0of8_cap{8G,6G,4G}.json` (f16) and
`e7b_global_shard0of8.dotvbyte_cap{8G,6G,4G}.json`, commit 9351d8c.

| cap | codec | cold p50 / majflt (pass 0) | warm p50 ms (p1–p3) | warm majflt/pass | peak VmRSS | verdict |
|---|---|---|---|---|---|---|
| 8G | f16 | 669 ms / 116,979 | 3.14 / 3.03 / 2.86 | 0 | 5.18 GiB | fits (control) |
| 8G | dv | 414 ms / 69,156 | 2.78 / 2.82 / 2.85 | 0 | 3.10 GiB | fits (control) |
| 6G | f16 | 637 ms / 116,979 | 2.90 / 3.03 / 2.81 | 0 | 5.18 GiB | fits — projection was high |
| 6G | dv | 408 ms / 69,156 | 2.85 / 2.70 / 2.65 | 0 | 3.10 GiB | fits |
| 4G | f16 | 1,495 ms / 184,632 | **1,286 / 1,513 / 1,921** | **97,883–172,662** | 3.68 GiB (capped) | **CLIFFED** |
| 4G | dv | 453 ms / 69,156 | 3.86 / 3.31 / 3.33 | 0 | 3.10 GiB | fits — clean |

Reading:

- **The cliff is where the hypothesis said, relocated one cap down.** The §7
  hypothesis was pre-registered at "the cap where f16 no longer fits"; the
  prompt projected that at 6 GB from the 6.74 GB on-disk forward, but f16's
  *actual* single-shard serving working set measured 5.18 GiB peak VmRSS
  (5.07 GiB file-backed) — the traversal never touches ~1.5 GB of the forward
  slab — so f16 still fits at 6 GB. At 4 GB it cliffs exactly as the A1 #3
  flat-then-cliff economics predict: warm p50 ~1.3–1.9 **s** (≈450–650× its
  own uncapped 2.9 ms) with sustained ~100–173k majflt on *every* warm pass
  (steady-state thrash, not a one-time fill). DotVByte's 3.10 GiB set fits
  under the same 4 GB cap with zero warm faults and 3.3 ms warm p50.
- **Cold passes cross-check E7 exactly:** 69,156 / 116,979 = 0.591 — the same
  gate-c ratio as the container measurement (§7), independently reproduced on
  a different kernel/mount.
- **Pre-registered decision rule applied** (§7 E7b bullet: "if TRUE at a cap
  where f16 has cliffed and dotvbyte has not, promotion is justified for
  RAM-constrained deploys regardless of gate (b)"): TRUE at 4 GB →
  **dotvbyte is PROMOTED for RAM-constrained deploys.** The compressed
  forward buys ~2.1 GiB/shard of page-cache headroom (~17 GiB across 8
  shards *est.* — only shard0 is converted and measured), which at a tight
  cap is the difference between 3 ms warm and multi-second thrash.
- **What promotion means operationally:** `seismic.MmapSeismicIndex`
  auto-dispatches on the shard's forward format (E7, zero serving-code
  change), so promotion = choosing the dotvbyte-converted shard artifact for
  a deploy whose per-shard cache budget is below ~5.2 GiB (equivalently
  <~42 GiB total for 8 shards *est.*). f16 stays the default when RAM is
  ample: both codecs are warm-equivalent there (gate b 0.957× native), and
  f16 skips the conversion. Corpus-wide adoption needs the remaining 7 shards
  converted (measured 203 s/shard on shard0 → ~24 min total, −2.7 GB/shard
  on disk *est.*).
- **Gate c disposition: CLOSED (superseded by E7b).** The 0.55 fault-ratio
  bar was a proxy for "does the codec win when pages are scarce"; E7b
  measured that question directly and the answer is yes. The fully-calibrated
  0.560 stands as the codec's real fault advantage on this platform (§7.4);
  no bar re-calibration is performed or needed.

Open follow-ups inherited from §7 (unchanged by this verdict): k′=100
interplay on the warm gap; E5 co-access reordering (the remaining
fault-*count* lever, §7.4 item 2); warm decode tuning only if a promoted
deploy still feels gate (b).

### 7.6 G8d — full-corpus gate-a parity: shard0's 0.995 was best-case; 2 of 8 shards miss the gate (2026-07-05, host run)

The §4/§7 gate-a parity (overlap@10 dv-vs-f16) had only ever been measured on
shard0 (0.995); the other 7 shards were `*est.*` until E7c converted them
(2026-07-04) and G8b measured all 8 for *footprint*. G8d closes the quality
side: the **identical** gate-a convention (40 diverse queries, k′=200, hf=0.8,
all-terms; `e7_dotvbyte_gates.py`, gate-a only) re-run per-shard on all 8 dv
shards vs their f16 twins (both twins of one shard co-resident, ~14 GiB — fits
the 32 GB everyday cap, no RAM bump). Read-only (Rule Zero: no shard file
modified during the run; verified `find -newermt`). Host WSL, HOSTPY.

| shard | overlap@10 mean | ≥0.99 gate |
|---|---|---|
| 0 | 0.995 | PASS |
| 1 | **0.985** | **FAIL** |
| 2 | **0.985** | **FAIL** |
| 3 | 0.990 | PASS |
| 4 | 0.990 | PASS |
| 5 | 0.9975 | PASS |
| 6 | 0.9925 | PASS |
| 7 | 0.990 | PASS |
| **corpus** | **0.9906** (mean of shard means) | worst shard 0.985; global worst-query min 0.90 |

Result files: `data/eval_results/e7_parity_shard{0..7}of8_20260705.json`,
aggregate `g8d_8shard_parity_summary_20260705.json`.

**Reading:**
- **The corpus average (0.9906) clears 0.99, but the per-shard gate does not
  hold uniformly** — shards 1 and 2 sit at 0.985 (≈1.5% of top-10 slots differ
  from f16 vs the ≤1% the gate allows). `all_8_shards_pass_0.99 = false`.
- **Shard0 (0.995) was the favorable shard**, ~0.005 above the corpus average.
  The promotion's recorded quality evidence was therefore the best-case slice,
  not a representative one. This does **not** reverse the promotion — dotvbyte
  is a lossy re-quantization of f16 and 0.985–0.995 rank agreement is still
  high — but it downgrades the parity claim from "0.995, comfortably passes" to
  "≈0.99 corpus mean, marginal, 2/8 shards under the per-shard bar."
- **Scope caveat (unchanged):** this is PER-SHARD overlap-vs-f16 ("does each dv
  shard return the same top-10 as its f16 twin"). It is NOT (a) the
  federated-merge overlap across the 8-shard fan-out (needs f16's full ~41.9
  GiB + dv co-resident, >32 GB — unmeasured), nor (b) an absolute nDCG against
  relevance judgments. dv inherits f16's separately-measured quality only to
  within this rank agreement.

**Decision (user call, 2026-07-05): option (i) — ACCEPTED.** 0.9906 (mean of
shard means) is the recorded corpus parity figure for the dv promotion, with
shards 1–2 noted as marginally sub-gate (0.985). No converter investigation of
shards 1–2 is planned; reopen only if a downstream quality eval (federated
merge or nDCG) surfaces a shard-1/2-shaped regression.

A distinct quality-*recovery* lever (a format improvement, not the declined
diagnosis) is pre-registered as **E8**: graft SFR1's per-doc value scale
(§2.4) into the dv container as format v2 — predicted (*est.*) to lift
shards 1–2 above 0.99 at zero serve-time cost. Row:
`11_EXPERIMENT_BACKLOG.md` Tier 3; recipe: `12_EXECUTION_ROADMAP.md` Q1. G8d
also produced a binding protocol change: quality gates now run on shards 1–2
(the measured worst case), never shard0-only
(`math_optimization/05_TESTING_PROTOCOL.md`, 2026-07-05 amendment).

> **E8 Stage-0 MEASURED (2026-07-08): GO.** The per-doc-scale proxy re-score
> on real shard-1/2 candidates (n=100) ranked at overlap@10 **0.997 / 0.993**
> vs FixedU8Q's 0.985 / 0.984 on the same queries — the §2.4 error advantage
> survives ranking, and the FixedU8Q arm reproduces G8d's 0.985 (method
> validation). `scripts/seismic_testbed/e8_stage0_perdoc_scale.py`,
> `data/eval_results/e8_stage0_perdoc_scale_20260708.json`. Next: Stage 1
> (dv-v2 encoder/loader, shards 1–2 only) per `12_EXECUTION_ROADMAP.md` Q1.

### 7.7 WI-4 — portable-CPU build gate reclear (2026-07-16, deployprep) — v3 SHIPS, v2 too slow

**MEASURED 2026-07-16.** The served `.so` is `target-cpu=native` (this exact CPU;
SIGILL on a host lacking the instructions) → it cannot ship to end users. Built
portable `x86-64-v3` (AVX2+FMA+BMI1/2) and `x86-64-v2` (SSE4.2+SSSE3, the
broadest x86-64 baseline) variants via `RUSTFLAGS='-C target-cpu=x86-64-v{3,2}'
maturin build --release -i <venv-python>` (build, NOT `develop` — the latter
overwrites the production .so). Variants extracted to side-loadable packages at
`spike/seismic_upstream/target/portable_so/{v3,v2}/seismic/*.so`; the production
.so is NEVER touched — variants load by explicit `sys.path` prepend
(`scripts/seismic_testbed/wi4_portable_cpu_gates.py`).

**objdump (the SIMD profile per target):** native 76 `vfmadd` / 15392 `ymm`; v3
100 `vfmadd` / 13979 `ymm` (the SAME packed-SIMD FMA path as native — portable
v3 keeps the AVX2 win); v2 2 `vfmadd` / 288 `ymm` (SSE-only, the FMA → scalar/
SSE fallback — the cost).

**Gates (the established E7 bars, `math_optimization/05`: worst-case-shard +
n≥100; pre-registered in `11_EXPERIMENT_BACKLOG.md` §WI-4):**

| variant | shard | parity overlap@10 (mean / min, n=100) | warm ratio (variant/native) | gate a (≥0.99) | gate b (≤1.07×) |
|---|---|---|---|---|---|
| **v3** | 1 | **1.0 / 1.0** | 0.956 | ✅ PASS | ✅ PASS |
| **v3** | 2 | **1.0 / 1.0** | 0.968 | ✅ PASS | ✅ PASS |
| v2 | 1 | **1.0 / 1.0** | 2.198 | ✅ PASS | ❌ FAIL (2.20×) |
| v2 | 2 | **1.0 / 1.0** | 2.251 | ✅ PASS | ❌ FAIL (2.25×) |

Verdict JSONs `data/eval_results/wi4_verdict_{v3,v2}_global_shard{1,2}*.json`;
per-variant top-k `wi4_topk_{variant,native}_shard{1,2}.json`; driver
`scripts/seismic_testbed/wi4_portable_cpu_gates.py` (each variant runs in its own
subprocess + the join computes overlap@10 vs the native reference).

**Two findings:**

1. **Parity is BIT-IDENTICAL (overlap@10 = 1.0, min 1.0) for ALL variants on BOTH
   worst-case shards** — the CPU-target change does NOT alter float results, even
   for v2's no-FMA SSE path. The dot-product accumulation order is preserved across
   targets (the kernel's summation structure is target-invariant; only the SIMD
   width + FMA fusion change). *Stronger than the pre-registration's prediction*
   (v2 was predicted "marginal"; it is exact). The parity risk the gate exists to
   catch did not materialize — a portable target is parity-safe.
2. **v3 PASSES both gates and is the shippable portable target.** Warm p50
   1.69–1.70 ms vs native 1.75–1.77 ms — v3 is **slightly faster** (0.956–0.968×),
   within run-to-run noise of native (the v3 scheduling is not worse). v3 keeps
   the AVX2+FMA win the native rebuild earned (§7.1) while being portable to any
   x86-64-v3 CPU (2013+, Haswell-class — the overwhelming majority of end-user
   hardware). **v2 FAILS gate b** (2.20–2.25× slower — no FMA + no 256-bit SIMD
   → the DotVByte decode/gather is SSE2/scalar, the same floor the §7.1 baseline
   1.223× measured before the native rebuild). v2 is parity-safe but too slow to
   ship as the served target; it stands as the last-resort baseline for a
   pre-Haswell CPU that lacks v3 (a documented fallback, not the default).

**The buildable recipe (committed, reproducible):** `scripts/seismic_testbed/
wi4_run_all_gates.sh` builds both variants + runs the 6-cell gate matrix + the
join. The variant .so extraction (wheel → side-loadable package) is in the gate
script's setup. To ship v3 in a handout: build with
`RUSTFLAGS='-C target-cpu=x86-64-v3' maturin build --release -i <py>`, install the
wheel into the handout's venv (or ship the `.so` beside the package). **No
served-default flip** (owner-gated): the production .so stays `native` until an
operator swaps the v3 variant in via the explicit-path load.



- Posting lists, summaries, EliasFano/BitField, block-skip math — untouched
  (15% of bytes; already the sequential-friendly part of the traversal).
- The engine's gather/scoring mechanism (09 correction: query_cut is a gather
  cut; SFR1 only changes how a candidate's vector is materialized).
- The k′/query_cut serving defaults (E1's findings stand independently).

**Cross-references:** `09_CROSS_SHARD_MMAP_AUDIT.md` (page economics, lever
table — its "forward width" row now points here), `07_G3_RAM_FIX_PLAN.md`
(C0.5/C1a format-wall + mmap reader lineage), `08_LATENCY_RESEARCH.md` §B/§E
(DotVByte literature anchor; zram bypass), `06_FINDINGS.md` (results ledger).
