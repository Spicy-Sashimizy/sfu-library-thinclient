# 03 — Interaction map: what a math change touches

**Status:** DEFERRED 2026-09-25 (M2 measured but NOT promoted - it failed its pre-registered bar; M6-M10 pre-registered and unfrozen)

The options, from drop-in to architectural. Each row is grounded in the file
map of `01_KERNEL_AND_MATH_MAP.md`. **The load-bearing isolation fact** (see
`00_CONTEXT_AND_CORRECTIONS.md`): to change the per-candidate dot math you need
only a Rust query-evaluator change in the encoder crate
(`spike/vectorium_fork/src/encoders/dotvbyte_fixedu8.rs`); the converted mmap
shards serve as-is, with the sole exception of M5.

## Options at a glance

| Change | Files touched | Shard rebuild? | ISA risk | Gate affected | Pre-gate |
|---|---|---|---|---|---|
| **M1. Zero-product skip** | `dotvbyte_fixedu8.rs:606-622` (kernel) | No | Medium (if hand-intrinsic) / Low (if `std::simd`) | b (minor) | zero-gather inventory = 76.7% ✓ |
| **M2. Integer dot, query quantized to 6-bit** | `dotvbyte_fixedu8.rs:349-407` (evaluator + dense_query) + `:603-642` (kernel) | No | Low (`std::simd` int) / High (hand `vpmaddubsw`) | b (the headline) | **query_int6 overlap@10 = 0.99 ✓ (2026-07-03)** |
| **M3. Real gather** (hand `vpgatherdd`) | `dotvbyte_fixedu8.rs:609-616` | No | High (no NEON gather twin) | b (attacks `vpgatherdd`=0 defect) | none needed (defect is objdump-proven) |
| **M4. Query table u8 shrink** (f32→u8 dense query) | `dotvbyte_fixedu8.rs:379-390` (+ kernel gather) | No | Low (portable types) | b (L2 fit) | collapses into M2 |
| **M5. Block-burst columnar scoring** | **Index format** (`packed_dataset.rs` forward layout) + `posting_list.rs` + kernel | **YES — full rebuild + new shard conversion** | n/a (later) | **b AND c** | gated on semantic-docid/E5 spike |

## M1 — Zero-product skip (drop-in, low value)

A candidate doc has ~88 stored terms; the query has ≤64. Every doc-term *not
also in the query* gathers 0, and the FMA after it multiplies nothing. An
8-lane all-zero test before the FMA skips the arithmetic for most groups.

- **Kernel site:** `dotvbyte_fixedu8.rs:606-622` — after the gather (`:609-616`),
  test whether `query_values` is all-zero (`Mask::all_false` in `std::simd`,
  lowering to `vptest`/`vtestz` on x86, `cmtst`/`umin` on aarch64); if so, skip
  the `mul_add` at `:618`.
- **Pre-gate:** the zero-gather inventory (76.7% of lanes fetch zero) is
  measured (`06_PREGATE_RESULTS.md`). **But** M1's win is the *all-zero-pack*
  rate, not the per-lane rate — a pack with one non-zero lane still pays the
  FMA. The 76.7% is an upper bound on M1's skip rate, not its win. Instrument
  the all-zero-pack rate before committing.
- **Value `*est.*` low:** the gather is already scalar (`vpgatherdd`=0), so
  saving the FMA saves only the arithmetic third, not the (already-cheap)
  gather. Probably the lowest-value option.
- **ISA risk:** **medium if hand-written** (`_mm256_testz_si256` is x86-only);
  **low if `std::simd`** `Mask` ops are used (they lower per-target). Use
  `std::simd`.

## M2 — Integer dot, query also quantized to 6-bit (the headline)

Score in the integer domain, the way quantized NN inference does:

```
score ≈ s_q · s_d · Σ ( q_u8[c] · d_u8[c] )
```

Quantize the query to 6-bit int too, and the mul-accumulate becomes
`vpmaddubsw` (32 u8×i8 products per instruction) on AVX2 / `UDOT` on
aarch64 ARMv8.4+, versus 8 f32 FMA lanes today. Plus the u8→f32 conversion
disappears, plus the dense query table shrinks 115 KB → 29 KB.

- **Kernel + evaluator site:** `dotvbyte_fixedu8.rs:349-407` (the query
  evaluator + `dense_query` build at `:379-390`) and `:603-642` (the kernel).
- **Pre-gate: PASSED.** `query_int6` overlap@10 = 0.99 (bar 0.99), saturation-safe
  by construction. See `06_PREGATE_RESULTS.md`. The 5-bit floor probe (0.9875)
  and the 7/8-bit intentional-saturation demo (0.995/0.9975) bracket the
  quality-vs-saturation trade.
- **ISA risk:** **low if `std::simd` int ops** (widening + mul-add lowers to
  `vpmaddubsw` on x86, `UDOT` on Apple aarch64, scalar on baseline — one
  source, three targets). **High if hand-`vpmaddubsw`** with no aarch64 twin.
  Prefer `std::simd`. See `04_ISA_PORTABILITY_RULES.md`.

### M2 saturation math (the load-bearing fine print)

`vpmaddubsw` produces **saturated i16 pair sums**: `out[i] = q[2i]·d[2i] + q[2i+1]·d[2i+1]`.
With doc values `d ∈ [0, 255]` (FixedU8`<U6>`), for **no saturation**:

```
2 · d_max · q_max ≤ 32767   ⇒   q_max ≤ 32767 / (2·255) = 64.2   ⇒   q ≤ 63  (6-bit)
```

Measured doc values (E6 phase A): min 0.01, **max 3.25 → 208 in u8 scale**, all
non-negative. 208 < 255, so there's even some headroom, but the *format cap* is
255, so the safe bound is set by the format, not the empirical max: **query must
quantize to 6-bit (≤63)** to be saturation-safe by construction. This is exactly
the kind of thing the Python pre-gate answers before any Rust — and it passed.

The 7-bit/8-bit modes in the pre-gate are `*est.*` demonstrations that the bound
bites: at 7-bit the pair sum can reach `255·127·2 = 64,770 > 32,767` →
saturation → in real hardware that would corrupt scores. (The pre-gate does
*not* simulate saturation — it gates bits>6 out by construction and shows
their *un-saturated* overlap only to confirm query resolution isn't the binding
constraint.) **Never ship a >6-bit query with a `vpmaddubsw` kernel**; if a
wider query is ever wanted, accumulate in i32 (two `vpmaddwd` style stages),
not single-stage `vpmaddubsw`.

## M3 — Real gather (attacks the `vpgatherdd`=0 defect)

The native rebuild closed FMA but left the gather scalar (objdump:
`vpgatherdd`=0 even at `target-cpu=native`). `std::simd` does not lower
`gather_select_unchecked` to a true AVX2 gather — a known LLVM portable-SIMD
gap ("fix #4 last resort," not taken).

- **Kernel site:** `dotvbyte_fixedu8.rs:609-616`.
- **Pre-gate:** none needed — the defect is objdump-proven (`01_KERNEL_AND_MATH_MAP.md`).
- **ISA risk: HIGH.** A hand `vpgatherdd` gives an x86-only gain with **no
  portable twin** — **NEON has no gather instruction.** On aarch64 the gather
  is scalar `ldar`-sequence regardless. So a hand-AVX2 gather is the one
  option that *structurally cannot* be made cross-ISA parity. The honest
  framing: M3 is "faster on x86, scalar parity on ARM" — acceptable only if
  written `std::simd` (accepting scalar gather on ARM as the platform's
  intrinsic limit), never as a hand-`vpgatherdd` fast path without a cfg-twin.
- **Value:** only worth it if Stage 3 (150M serve) shows the kernel is still the
  bottleneck under real load. At 929k-warm it isn't (gate b 0.957 already
  passes); at 150M/IO-bound the relative cost may re-emerge — measure first.

## M4 — Query table u8 shrink (collapses into M2)

Quantize the dense query from `Vec<f32>` (115 KB at dim 28,702) to `Vec<u8>`
(29 KB). Fits L2 comfortably, making the gathers cheaper.

- **Site:** `dotvbyte_fixedu8.rs:379-390` (dense_query build) + the kernel
  gather (`:610`).
- **Value `*est.*`:** L2-fit win; measure at Stage 3.
- **ISA risk:** Low (portable types).
- **Note:** M4 is essentially the query-side half of M2 — doing M2 (integer
  dot) *implies* an int dense query, so M4 is not a separate change if M2
  proceeds. Listed only because it has an independent value if M2 is rejected.

## M5 — Block-burst columnar scoring (architectural; the only option that touches gate c)

Today the kernel is row-major: 64 separate record decodes, 64 scattered page
touches, 64 independent dots per surviving block. A block is a cluster of
similar docs sharing many terms (that's what the k-means blocking means). The
column-major alternative: store each cluster's forward data transposed
(term → list of (local-doc, value)); scoring a surviving block becomes a
sum over query terms accumulating into 64 local accumulators.

```
row-major:    cost ∝ Σ_docs nnz_doc            ≈ 64 × 88 ≈ 5,600 decode+gather+fma
column-major: cost ∝ Σ_{t ∈ query} nnz_t(block) ≈ tens–hundreds of pure adds
```

— an order of magnitude less arithmetic AND the page pattern flips from ~64
scattered faults to 3-4 sequential pages (~13 KB contiguous per block).
**Attacks gates b AND c simultaneously.** This is the only option that touches
gate c (the actually-failing gate).

**The catch, substantial:**
- **Files touched:** index format — `packed_dataset.rs:117-130, 344-347`
  (forward layout), `posting_list.rs:83-86, 26-28` (block structure), and the
  kernel. **Forces a full rebuild + new shard conversion** (the only option
  that does).
- **The 88× duplication blocker:** a doc belongs to ~88 different lists'
  blocks, so per-block transposition would duplicate the forward ~88× →
  impossible. M5 only works with a **single global clustering** where each doc
  has one "home" cluster used by all lists — which is precisely the
  semantic-docid / E5 territory (`docs/semantic_docid_ingest/`).
- **Gating:** M5 is **research-grade, gated behind a separate spike**
  (semantic-docid / E5 doc reordering). E5's doc reordering is the cheap
  statistical approximation of it (co-clustered docs share pages without
  changing the math), which is why E5 is ranked ahead of M5.

## Catastrophic-to-get-wrong footguns (checklist before any kernel edit)

1. **M2 saturation** (`vpmaddubsw` i16 pairs): with doc u8 cap 255, query
   **MUST be ≤6-bit** or silent saturation corrupts scores. Pre-gated ✓
   (`06_PREGATE_RESULTS.md`). Never ship >6-bit query with single-stage
   `vpmaddubsw`; widen to i32 (`vpmaddwd`) if more query resolution is needed.
2. **M5 duplication blocker:** per-block transposition duplicates the forward
   ~88× → impossible without single-home-cluster. Gated on semantic-docid.
3. **Any hand-intrinsic kernel that lacks an aarch64 twin LOCKS the codebase
   to x86** and silently kills the iPhone/ARM target. M3's `vpgatherdd` is the
   worst offender (no NEON gather exists). Mandate the cfg-gated twin pattern
   (`04_ISA_PORTABILITY_RULES.md` rule 2) for any hand-intrinsic path.
4. **`target-cpu=native` MUST stay env-only**, never baked into
   `.cargo/config.toml` or `build.rs`. Baking it breaks cross-compile to
   aarch64/iPhone and silently emits wrong code. It is currently env-only
   (`scripts/run_experiments.py:62`); keep it that way.
5. **The mmap shard layout is NOT to be touched** by M1–M4 — the converted
   shards serve as-is (the math is in the evaluator, the shard is just the
   data). Only M5 changes the layout. Ignoring this re-triggers a multi-hour
   shard rebuild for no reason.
