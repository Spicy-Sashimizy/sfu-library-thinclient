# 14 · Encoder upgrade path — query-encoder spike (D-track successor)

**Status:** ACTIVE

> **Status note 2026-08-10:** the 2026-07-10 banner below is the
> creation-time state and is superseded by §4/§6 — **C1–C5 are all
> measured/decided (C1/C2/C5 KILL 2026-07-10, C3 skipped, C4 distillation
> KILL 2026-07-28); the encoder book is CLOSED.** Only the §5 re-encode
> branch (prechecks 2–3: shelf domain pilot + fine-tune probe) remains open,
> unscheduled.

> **Status 2026-07-10: SPIKE — design + candidate registry only. NOTHING
> MEASURED.** Registered as **Q11** in `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` §3. Every
> quality/latency claim below is `*est.*` or literature-reported until a row
> lands in §6. Parent results: D-track in `08_LATENCY_RESEARCH.md` §D
> (D1 dynamic-int8 KILLED overlap 0.79; D2 ORT fusion PROMOTED 1.11×;
> pinning/spin REFUTED — the methodology + bars below inherit from those).

## 0. Why (one paragraph)

After G8g, encode is the largest addressable component of the served warm
path: **p50 53.8 ms = encode 19.5 + traverse 33.7** (2026-07-08, doc 08 §A4).
Every traversal-side lever is measured or queued; nothing else touches ~36%
of *every* query. The literature ceiling is dramatic: inference-free learned
sparse retrieval (Li-LSR, arXiv 2505.01452) replaces the query transformer
with a per-token score lookup (~0.8 ms vs ~24 ms encode) *without* losing
quality on MS MARCO/BEIR — but only when the query side is trained/derived
against the SAME doc space. That constraint is the whole design problem here.

## 1. The compatibility rule (hard constraint — read first)

The 150M doc vectors are fixed: encoded by the served SPLADE model
(`models/splade_onnx_fused`, tokenizer `sfu-academic-embed-v1`, sparse dim
~28.7k per shard manifest). A query encoder is only usable if it emits
vectors aligned to that space.

- **Off-the-shelf encoders are excluded** without a full corpus re-encode:
  `naver/efficient-splade-V-large-query`, the
  `opensearch-neural-sparse-encoding-doc-v2/v3` family, SPLADE-v3 variants —
  each lives in its own jointly-trained space (most on BERT's 30522 vocab,
  not even our vocabulary). Scoring them against our shards measures noise,
  not quality.
- **Evidence this constraint bites:** D1 — the *same* model dynamically
  int8-quantized dropped merged overlap@10 to **0.79** (bar 0.99). A
  different model entirely has no alignment at all.
- Therefore every benchmarkable candidate in §3 is a **derivative of the
  served encoder** (same tokenizer, same output space by construction).

## 2. Primer — how a SPLADE-style encoder is built (context for §3/§5)

A learned sparse encoder is a BERT-class transformer with its **MLM
(masked-language-model) head kept on**: text → contextual token embeddings →
MLM logits over the vocabulary at every position →
`log(1 + ReLU(logit))` → **max-pool across positions** → one sparse vector
over the vocab (weights = term importances, including *expansion* terms that
never appear in the text). Training = contrastive ranking loss on
query–doc pairs (hard negatives) + distillation from a cross-encoder
teacher + a **FLOPS/L1 sparsity regularizer** that directly controls how
many nonzeros docs/queries get — i.e. index size and traversal cost are
*training-time knobs*, not just serving knobs. Query and doc sides may be
the same model (symmetric — our setup) or two models trained jointly
(Efficient-SPLADE pairs a BERT-tiny query encoder with a large doc encoder;
OpenSearch doc-only pairs a doc transformer with a *lookup table* query
side, made viable by an IDF-aware penalty during training). The asymmetric
family is what makes cheap query encoders possible — and why a query-side
swap trained against someone else's doc encoder is meaningless.

## 3. Candidate registry (same-space derivatives — benchmarkable NOW)

| # | Candidate | Mechanism | Standing-up cost | Encode target | Quality hypothesis (*est.*) |
|---|---|---|---|---|---|
| C1 | **Expansion-table distill** | precompute served model's expansion vector per vocab token (~28.7k single-token passes, one-time ~minutes); query vec = sum of its tokens' rows | ~1 day, zero training | **sub-ms lookup** | the live question is whether context-dependent expansion matters on academic queries; 0.97–0.99 plausible |
| C2 | **Tokenizer + IDF weights** | query terms = raw tokens, weights from corpus IDF (OpenSearch doc-only pattern, minus their joint training) | hours | sub-ms | expected < C1 (no expansion); the control floor — if C1 ≈ C2, expansion wasn't earning its cost |
| C3 | **Learned scalar head (Li-LSR pattern)** | linear layer over the served model's frozen word embeddings, distilled to mimic full-encoder query vectors on a real query distribution | days, light training | sub-ms | literature beat SPLADE-v3-Doc; as a distill of OUR model it is the principled escalation if C1 grazes the bar |
| C4 | **Layer-truncated student (KALE / Efficient-SPLADE pattern)** | first 2–4 layers of the served model + MLM head, distilled on queries | days, training infra | ~4–8× faster (not sub-ms) | keeps context-dependence → highest expected quality of the fast options; KALE retained 92.5% — near our bar, not obviously over it |
| C5 | **Static-calibrated int8** | ORT static quantization of the served model, calibrated on real queries | hours | ~1.3–1.6× | same asymmetry class that killed D1 dynamic-int8; low prior; cheap to close the question |

**Benchmark order: C1+C2 first** (shared harness; they bracket the
expansion question), C3 only if C1 lands 0.97–0.99, C4 only if the lookup
family fails outright, C5 opportunistically alongside any run.

## 4. Gates (pre-registered — inherited from the D-track)

1. **Stage-0, fully offline, per candidate:** n≥100 real queries; merged
   federated overlap@10 vs the served fp32 encoder **≥ 0.99** (the bar that
   killed D1 and FastGelu), measured on worst-case shards 1–2 AND the merged
   8-shard top-10; overlap@50 recorded as the tail check; same-process
   interleaved A/B only (D2 methodology rule). Result JSON
   `data/eval_results/q11_encoder_<candidate>_<date>.json` + row in §6.
2. **T1:** sequential ≡ parallel bit-identical on the candidate's query
   vectors.
3. **Ship gate (only on Stage-0 PASS):** env-gated serving default
   (`SFU_SPLADE_QUERY_ENCODER=<candidate>`-style, one-env rollback — the D2
   promotion pattern), paired same-process latency A/B, doc rows
   (this doc §6 + doc 06 + `THIN_CLIENT_SWAP.md`) in the same commit.
4. **Optional pre-promotion belt-and-braces:** absolute relevance spot-check
   via the LLM-judge lineage (n=120), since overlap-vs-self cannot see
   "both arms equally wrong".

No candidate touches doc vectors, shards, or the index (Rule Zero
untouched); the worst possible outcome is a KILL verdict in a JSON. If even
C4 cannot hold 0.99, **the encoder book closes**: ~20 ms is the price of
this doc space until a corpus re-encode.

> **2026-07-28: THIS CAME TO PASS — C4 distillation KILLED (worst-arm 0.726
> after the escalation round; §6 first entry). The encoder book is CLOSED;
> only the §5 re-encode branch remains.**

## 5. The re-encode branch — off-the-shelf vs training our own (hypothetical; costed, unscheduled)

If a full corpus re-encode ever becomes acceptable (~150M docs of GPU
encode + full shard rebuild + E7 dv conversion + E5 reorder + every gate
re-run — the same pipeline as REBUILD_TO_PERSISTENT_PATH plus conversions),
the calculus changes from "derive" to "choose/train the pair jointly":

- **Off-the-shelf pair** (e.g. OpenSearch doc-v3 + its lookup query side,
  or Efficient-SPLADE large-doc + tiny-query): zero training cost,
  production-proven inference-free query path — but generic-domain
  (MS MARCO-trained), fixed vocab, and no control over sparsity/index
  geometry. Domain mismatch on an academic corpus is the open risk
  (*est.* — no academic-domain numbers in their cards).
- **Training our own** buys three things the shelf cannot (*all est.*):
  1. **Domain adaptation** — trained on academic text/queries with our
     cross-encoder (already in `models/`) as teacher;
  2. **Co-design with the serving stack** — query side trained as a lookup
     table from day one (OpenSearch's IDF-aware-penalty recipe), making
     C1's approximation exact by construction and deleting the encoder
     permanently;
  3. **Index-geometry control** — the FLOPS regularizer tunes nnz/doc
     against OUR posting-list/page-touch economics (docs 09/10/13), i.e.
     the index size and cold-path cost become training-time levers.
- **Cost either way** is dominated by the re-encode + rebuild, not the
  training — so *if* the branch is ever taken, custom (or
  custom-fine-tuned-from-shelf) strictly dominates plain off-the-shelf.
- This branch is NOT scheduled. It becomes worth costing properly only if
  (a) §3 ends in KILL and encode still matters, or (b) a corpus rebuild is
  forced anyway (then ride it, as E5 rides E8 Stage 2).

### 5.1 The training-tier prechecks that PRODUCE the custom-vs-shelf verdict

(Registered 2026-07-10, after the cheap tier measured out — §6. All three
are GPU/training-tier, multi-day; none can run in the dev container alone.)

> **CORRECTION 2026-07-28:** the "none can run in the dev container" clause is
> stale — the current container has working CUDA access to the host's RTX
> 4070 Ti SUPER (16 GB VRAM; verified `torch 2.6.0+cu124`
> `cuda.is_available()=True` in the project venv). The C4 distillation build
> (precheck 1) fits this GPU: 16 GB VRAM comfortably holds the 12-layer
> teacher + 4-layer student at training batch sizes, so the training-tier
> constraint no longer blocks it container-side. Prechecks 2–3 additionally
> need a ~1M-doc re-encode + slice index build — still multi-day, but also
> GPU-feasible here (*est.*, unmeasured). Wall-clock for one clean C4 pass on
> this GPU: teacher qvec generation for a 1–5M-query distill set ≈ minutes-to-
> tens-of-minutes batched; student training a few epochs ≈ hours; gate +
> ONNX/D2 export ≈ hours (*all est.* until a run lands in §6).

1. **C4 distillation build (decides the last same-space candidate):**
   truncate the served model to 4 layers, distill on real+pseudo queries
   (doc titles from meta.sqlite as pseudo-queries; teacher = the served
   12-layer model's qvecs; loss = ranking-aware, e.g. margin-MSE on sampled
   doc pairs). Gate = §4 unchanged (0.99 merged + shards 1–2). PASS moots
   the re-encode branch at ~4–8× encode; KILL closes same-space entirely.
2. **Domain pilot (shelf arm):** encode a ~1M-doc corpus slice with an
   off-the-shelf inference-free pair (OpenSearch doc-v3-distill + its
   lookup query side); build a small SEISMIC index on the slice; score the
   n=120 LLM-judge query set vs the same slice under the served model.
   Measures the actual domain-mismatch cost — the fact that decides if
   shelf is in the running at all.
3. **Fine-tune probe (custom arm):** same shelf doc model, briefly
   fine-tuned on academic text with the in-repo cross-encoder as teacher;
   re-run pilot 2. **The 2-vs-3 delta IS the measured value of "custom".**
   Decision rule: if 3 ≫ 2 → custom wins the re-encode branch; if 2 already
   matches the served model's judge scores → shelf suffices; if both trail
   badly → the branch dies and the served encoder stays.

## 6. Results ledger (no numbers, not done)

- **2026-07-28 C4 DISTILLATION BUILD — KILL; THE ENCODER BOOK CLOSES (§4).**
  The §5.1 precheck-1 training-tier build, run in-container on the 4070 Ti
  SUPER (per the §5.1 correction). Full pre-registration doc 11 §Q11-C4.
  Teacher = torch reconstruction of the served encoder from the ONNX
  initializers, parity max|Δ| 6.7e-5 / top-64 overlap 1.0 vs the ONNX
  session (`q11_c4_teacher_parity_20260728_1905.json`). Distill set 480k
  meta.sqlite titles + 97 real queries (gate/judge sets held out). Round 1
  (qvec-MSE in serving space, 3 epochs): gate **merged 0.690 / shards
  0.643–0.667** overlap@10 vs bar 0.99
  (`q11_c4_distill_gate_20260728_2007.json`). Escalation round (single,
  pre-registered; margin-MSE over 40k REAL shard-1/2 forward doc vectors +
  6 more epochs): gate **merged 0.760 / shard1 0.726 / shard2 0.752**,
  proxy and losses plateaued — an objective/capacity ceiling, not
  undertraining (`q11_c4_distill_gate_20260728_2127.json`). Encode p50
  17.65 vs fused 29.90 ms (1.69×, student unfused — moot at KILL). KALE's
  92.5% retention did NOT transfer to a 0.99-overlap regime: distillation
  recovered 0.46 → 0.76, nowhere near the bar. Scripts
  `scripts/seismic_testbed/q11_c4_{teacher_from_onnx,build_distill_set,train_student,train_student_v2,gate_student}.py`.
  **Method export:** the offline dev top-64 term-overlap proxy predicted
  the federated backend gate ~1:1 in both rounds — future encoder
  candidates can be triaged shard-free. Per §4: same-space candidates are
  now all measured dead; **~20 ms encode is the price of this doc space
  until a corpus re-encode (§5)**. Serving impact: zero (nothing shipped;
  Rule Zero clean).
- **2026-07-10 C1+C2 Stage-0 — KILL (zero-training lookups).** n=100,
  reference = served fused qvecs, SequentialSeismicBackend (T1
  bit-identical), merged + shards 1–2. Merged overlap@10: **C1-max 0.533**,
  C1-sum 0.331, C2-self-weight 0.357 (shards 1–2 within ±0.07 of merged) —
  all far below the 0.99 bar and the 0.97 escalation band.
  `scripts/seismic_testbed/q11_c1c2_stage0.py`,
  `data/eval_results/q11_c1c2_stage0_20260710_0228.json`.
  **Mechanism (diagnostic in the run):** the failure is NOT expansion
  quality — single-token rows are semantically sane ('indigenous' →
  native/aboriginal) — it is **contextual magnitude reweighting**: the full
  encoder decides which of the query's tokens matter *in this query*
  ('language' 2.54 > 'indigenous' 1.46 on the Indigenous-languages query)
  while any static table gives every token its fixed context-free loudness.
  Two corollaries recorded: (a) **C3 (learned static scalar head) is
  DEMOTED to near-dead** — it shares the static ceiling and cannot do
  contextual reweighting, and per the pre-registered order (C1 < 0.97) it
  is SKIPPED; (b) single-token expansion mass lives in the CLS/SEP
  positions (mid-position pooling yields almost no expansion) — no pooling
  variant rescues C1. C2 deviation note: implemented as model self-weight,
  not corpus IDF (no cheap df source; the bracket conclusion is unaffected
  — both static arms fail the same way).
- **2026-07-10 C4 PRE-GATE (untrained truncation) — LOW; no free shortcut.**
  Merged overlap@10: **L4 0.464, L8 0.506** (shards 1–2 within −0.06) —
  raw truncation collapses into the same ~0.5 band as the static lookups.
  **L12 control 0.999/1.0/1.0** — harness exact (reproduces D2's measured
  fp32-vs-fused gap). Per the pre-registered one-directional rule this does
  NOT kill C4 — KALE's 92.5%-retention says distillation recovers most of
  raw truncation's loss — but it means **C4 can only be decided by an
  actual distillation build (training-tier)**; there is no cheap encoder
  win left below that. Encode timings in this run are contended (Q7–Q9
  session benches co-resident) — overlap signal unaffected.
  `scripts/seismic_testbed/q11_c4_pregate.py`,
  `data/eval_results/q11_c4_pregate_20260710_0240.json`.
- **2026-07-10 C5 static-calibrated int8 — KILL (total collapse).** QDQ
  per-channel int8 (weights+activations), calibrated on the 120
  sfu_eval_queries (distinct from the eval set): merged overlap@10
  **0.006** (shards 1–2 0.005–0.007) — the quantized model is functionally
  destroyed, not merely degraded — AND encode p50 228 ms = **5.5× slower**
  on this CPU (QDQ without a VNNI path; timing contended but the direction
  is unambiguous). With D1's dynamic-int8 at 0.79, the int8-encoder family
  has now measured 0.006–0.79 across its spectrum vs the 0.99 bar —
  **the family is dead**; milder configs (op-exclusions, weights-only)
  remain unmeasured but are bounded by the same asymmetry evidence.
  `scripts/seismic_testbed/q11_c5_static_int8.py`,
  `data/eval_results/q11_c5_static_int8_20260710_0252.json`.
- **2026-07-10 CHEAP TIER CLOSED.** Every zero/low-cost candidate is
  measured: C1 0.533 / C2 0.357 (static lookups — contextual-reweighting
  mechanism), C3 skipped (shares the static ceiling), C4 untrained 0.46–0.51
  (alive, decidable only by a distillation build), C5 0.006 (int8 family
  dead). **The served fused encoder stays; the only remaining encoder paths
  are the training-tier prechecks of §5.1.** Serving impact of this spike:
  zero (nothing shipped, nothing touched — all gates offline).
