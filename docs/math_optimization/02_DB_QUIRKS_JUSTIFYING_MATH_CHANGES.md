# 02 — Measured DB quirks that justify a math change

The generic SEISMIC engine's dot math knows nothing about our corpus. Our
corpus has measured properties the engine ignores. The math-change options
(M1–M5, see `03_INTERACTION_MAP.md`) are justified by — and gated on — these
statistics.

## A. Doc values: non-negative, bounded ≤3.25

**Measured** in `data/eval_results/seismic_e6_forward_codec_proto_20260702_2346.json`
→ `phase_a_stats`, E6 phase A on shard0 of the 150M index (n_docs=18,799,322):

- min = 0.01
- **max = 3.25**
- **all non-negative** (`all_nonneg=true`)

**Why this enables a math change (M2 integer dot):** integer dot products are
safe — no sign handling needed. 3.25 → 208 in the FixedU8`<U6>` u8 scale (×64),
well under the 255 cap. The dot is a sum of products of two non-negative
bounded quantities, exactly the `vpmaddubsw` regime. This is the corpus fact
that makes M2 possible at all.

## B. Doc nnz: mean 87.6 (the "~88 terms")

Same phase A result: nnz **mean = 87.6** (min 7, max 256, p50 82, p99 255).
`cap_note`: "7 ≤ nnz ≤ 256 over ALL 18.8M docs (top-256 build cap)."

This is the "~88 terms per doc" figure. It means each scored candidate doc
runs ~11 SIMD packs (`88 / 8`) through the kernel — the decode/gather/arith
loop body executes ~11× per candidate.

## C. FixedU8`<U6>` fidelity: overlap@10 = 0.995 (gate ≥0.99 PASS)

**Measured** in `data/eval_results/seismic_e6b_fixedu8_quality_20260702.json`:
FixedU8`<U6>` (the served doc-side quantization) `overlap@10_mean = 0.995`,
`overlap@50_mean = 0.9945`, `gate_pass_0.99 = true`. Script:
`scripts/seismic_testbed/e6b_fixedu8_quality.py`.

The decision recorded there: "REUSE DotVByteFixedU8 — FixedU8Q passes the 0.99
gate at the same overlap@10 as SFR1." So doc-side u8 quant is already proven
lossless-enough. This gives **headroom to also quantize the query** (the M2
move): doc values can absorb the doc-half of an integer dot without losing
the top-10 ranking, so the question reduces to whether the *query* can be
quantized to int without crossing the bar — which is the M2 pre-gate
(`06_PREGATE_RESULTS.md`).

## D. Per-doc-linear u8 rel-L2: 0.329% (vs global codebook 1.276%)

Same phase A result: u8 per-doc linear quantization relL2 error **mean 0.329%**
(p95 0.431%); global-quantile-codebook relL2 **1.276%**. Verdict: "per-doc
linear WINS on this corpus."

Doc values are smooth enough for u8 fixed-point *everywhere*. The
"obvious" corpus codebook (global quantile) **loses** — an anti-fact against
a codebook-based quantizer and for the simple per-doc linear scheme already
in use.

## E. BMP ×70 u8×u8 integer dot: the production precedent

The production SPLADE path **already does u8×u8 integer scoring** — this is
the precedent for doing the same in SEISMIC:

- Doc values quantized at build: `src/lib/thinclient/builder.py:213`
  `vec = {t: min(BMP_IMPACT_MAX, max(1, int(round(w * QUANT_SCALE))))}`
  with `QUANT_SCALE = 70`, `BMP_IMPACT_MAX = 255` (`builder.py:34-35`).
- Query weights quantized at search: `src/lib/thinclient/retriever.py:669`
  `qvec = {t: max(1, int(round(w * QUANT_SCALE))) for t, w in top_terms.items()}`
  with `QUANT_SCALE = 70` (`retriever.py:100` — "saturation-free" comment,
  must match builder).
- `SPLADE_QUERY_TERMS = 64` (`retriever.py:101`) — the query cap.

**Quant fidelity (BMP ×70 vs Qdrant f32):** `data/eval_results/quant_fidelity_30mscan.json`
(n=1,000,000 docs, 40 queries, 30M-scan harvest): `mean_overlap@10 = 0.9875`,
`mean_ndcg@10_f32 = 0.8681`, `mean_ndcg@10_quant = 0.8681`,
**`ndcg_delta = 0.0`** (bit-identical judged quality). Live 150M re-measurement
(`quant_fidelity_live_150m_20260624_2345.json`): overlap@10/50 = 1.0,
ndcg_delta = 0.0, pass=true.

So u8×u8 integer dot is **not** a theoretical move — it's the proven
production mechanism on the BMP leg. M2 ports the same idea into the SEISMIC
kernel.

## F. Zero-gather fraction: 76.7% (measured 2026-07-03)

**Measured** in `data/eval_results/seismic_m2_pregate_queryint_20260703.json` →
`zero_gather_inventory`: across 4,728 real engine top-200 candidate docs,
822,843 doc-term slots were iterated by the kernel; of those, only 191,732
(23.3%) were present in the query (non-zero gather); **631,111 (76.7%) were
absent** (zero gather → wasted FMA lane).

**Why this matters (M1 zero-product skip):** ~3 of every 4 kernel gather
lanes fetch 0 from the dense query array, then the FMA multiplies nothing.
An all-zero-lane test (`vptest` on x86, `cmtst`/`umin` on aarch64 — both via
`std::simd` `Mask::all_false`) before the FMA would elide the arithmetic for
those groups. This grounds — and corrects — the earlier unmeasured "~90%
zero FMA lanes" estimate; the real number is **76.7%**. The actual FMA-lane
idle rate is *lower* than 76.7% (a lane is zero-gathered but the surrounding
pack may not be all-zero), so M1's win is bounded by the all-zero-pack rate,
not the per-lane rate — instrument that too if implementing M1. `*est.*`

## G. Query is the short vector (cap 64); doc is the long one (mean 88)

The asymmetry that makes query-side changes cheap and doc-side changes
expensive:

- Query: ≤64 non-zero terms (`SPLADE_QUERY_TERMS = 64`). Densified to `Vec<f32>`
  length `dim` (28,702 on shard0 per the manifest). The dense table is ~115 KB
  (28,702 × 4 B). Quantizing the query to u8 shrinks it to ~29 KB
  (28,702 × 1 B) — fits L2 comfortably (`~14 KB` for the u8 form on a 28,702
  dim, well under typical 256 KB–1 MB L2), making the gathers cheaper too.
- Doc: ~88 stored terms, fetched per candidate.

So the dense-query table is the thing the gather iterates over, and it's the
thing M4 (query u8 shrink) attacks. `*est.*` on the exact L2-fit win — measure
at Stage 3 (150M serve) where cache behaviour under real load shows up.

## Summary table — what each quirk enables

| Quirk | Measured value | Source | Enables |
|---|---|---|---|
| Doc values non-negative, ≤3.25 | min 0.01, max 3.25, all ≥0 | E6 phase A | M2 integer dot (no sign handling) |
| Doc nnz | mean 87.6 | E6 phase A | Sets the ~11 packs/candidate loop count |
| FixedU8Q doc fidelity | overlap@10 0.995 | e6b gate | Headroom to also quantize the query (M2) |
| Per-doc-linear u8 rel-L2 | 0.329% | E6 phase A | Doc u8 quant is the right scheme (not codebook) |
| BMP ×70 u8×u8 integer dot | overlap 0.9875, ndcg_delta 0.0 | quant_fidelity | M2 is the proven production precedent |
| Zero-gather fraction | 76.7% | m2_pregate | M1 zero-product skip target |
| Query cap 64, dim 28,702 | 64 terms, ~115 KB dense table | retriever.py:101 + manifest | M4 query u8 shrink (115 KB→29 KB) |
