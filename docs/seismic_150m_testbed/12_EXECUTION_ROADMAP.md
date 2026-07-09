# 12 — Execution roadmap: the entry point for DOING the next thing (2026-07-05)

**Purpose.** The dv/mmap/kernel arc now spans two doc trees
(`seismic_150m_testbed/` and `math_optimization/`), a backlog (`11`), and a
string of dated decisions. This doc is the single place a future session starts
when it's time to **execute** rather than research: the state snapshot, the
binding rules, and the ordered queue with per-item recipes and pre-registered
bars. It quotes only headline numbers — the canonical figures live in the
pointed-to docs (source-of-truth hierarchy applies; if this doc and a parent
doc disagree, the parent + the code win, and this doc gets fixed).

**How to use:** read §2's rules, take the topmost unblocked item in §3 you have
the environment for, follow its recipe, write the result file + doc rows per
§2.5, and update this doc's queue row in the same commit.

---

## 1. State snapshot (2026-07-05 — one line each, with the canonical doc)

| What | State | Canonical |
|---|---|---|
| dv (dotvbyte) format | **PROMOTED**; serves all 8 shards; f16 stays default when RAM ample | doc 10 §7.5 |
| Full-corpus footprint (G8b) | dv 25.23 GB RSS vs f16 41.86 GB (−40%), warm p50 latency-neutral ~65 ms; at 28–32 GB caps f16 thrashes (~13 s) while dv serves 65 ms | `data/eval_results/g8b_fullcorpus_*`, doc 10 §7.5, backlog `11` |
| Full-corpus parity (G8d) | corpus mean **0.9906** overlap@10 vs f16; shards 1–2 = 0.985 sub-gate; **ACCEPTED as the parity figure (user decision 2026-07-05)** — marginal, and the budget constraint for every lossy candidate below | doc 10 §7.6 |
| Gate b (warm latency) | **PASS** 0.957 via native rebuild (env-only) | `math_optimization/00`, `06` |
| Gate c (cold majflt) | 0.560 vs 0.55 — **CLOSED as superseded by E7b** (dv promoted for RAM-capped deploys; no math change can move it) | doc 10 §7.4–7.5 |
| M2 (int6 kernel) | implemented, **NOT PROMOTED** (gate a 0.984 < 0.99 at n=100); env-gated OFF | `math_optimization/07` |
| Kernel leverage | ~2–3 ms of the ~65 ms federated query — kernel wins pay off in sequential federation, warm single-shard, and throughput/energy, NOT the federated p50 | `math_optimization/08` leverage map |

## 2. Standing rules (binding for every item below)

1. **Worst-case-shard rule (new, from G8d).** Shard0 measured as the
   *best-case* parity shard (0.995 vs corpus mean 0.9906). Every future
   quality gate runs on **shard 1 or shard 2** (both when cheap); a
   shard0-only quality PASS is not promotable. Recorded in
   `math_optimization/05_TESTING_PROTOCOL.md` (2026-07-05 amendment).
2. **n≥100 for any promotable overlap gate** (the M2 n=40→100 reversal,
   `math_optimization/07`).
3. **Quality-free before lossy.** G8d spent most of the parity budget
   (0.9906 accepted marginal). Candidates that cannot lose quality by
   construction (M7, M8, E8's Stage-0) run before candidates that quantize
   anything further (M2b, M6). Order amendment recorded in
   `math_optimization/08` §Recommended-order.
4. **Rule Zero** — no run modifies a served shard file; verify with
   `find <shard dirs> -newermt <run start>` after every host run.
5. **Recording** — result JSON under
   `data/eval_results/{topic}_{descriptor}_{YYYYMMDD}[_{HHMM}].json`;
   the measured row replaces its prediction cell in `11_EXPERIMENT_BACKLOG.md`
   AND lands in the parent doc, same commit (house doc rules). Bars are
   written BEFORE the run; a bar is never retrofitted.
6. **Environments.** *container* = the devcontainer venv
   (`/workspaces/sfu-library-thinclient/.venv/bin/python3`; Rust builds per
   `math_optimization/05` §build). *host* = the 58 GB WSL host session
   (HOSTPY; runbook lineage `scripts/seismic_testbed/HOST_PROMPT_G8B_FULLCORPUS.md`).

## 3. The execution queue (ordered; take the topmost unblocked item)

### Q1 — E8: dv-v2 per-doc value scale (quality RECOVERY, the only item that *raises* parity)

- **Goal:** recover the G8d loss at zero serve-time cost — lift shards 1–2
  ≥0.99 and corpus mean ≥0.995 (*est.*) by replacing FixedU8Q's global 1/64
  scale with SFR1's per-doc linear u8 scale (doc 10 §2.4: rel-L2 0.329%,
  ~4× better than global schemes) inside the dv container format.
- **Stage 0 (container, zero Rust, run FIRST):** e6b-lineage proxy
  (`scripts/seismic_testbed/e6b_fixedu8_quality.py` +
  `e6_forward_codec_proto.py` `phase_c_quality()`) re-scoring real shard-1
  and shard-2 candidates under per-doc-u8 semantics, **n=100**.
  **Bars (pre-registered):** per-doc overlap@10 ≥ FixedU8Q's on the same
  queries AND ≥0.99 on both shards → GO; below FixedU8Q → KILL (record; the
  §2.4 error advantage failed to survive ranking).
- **Stage 0 RESULT (2026-07-08): GO.** Per-doc overlap@10 **0.997 (shard1) /
  0.993 (shard2)** vs FixedU8Q **0.985 / 0.984** on the same candidates —
  both bars cleared with margin; the FixedU8Q arm reproduces G8d's measured
  0.985 on these shards, validating the proxy.
  `scripts/seismic_testbed/e8_stage0_perdoc_scale.py`,
  `data/eval_results/e8_stage0_perdoc_scale_20260708.json`.
  **Q1 is now unblocked at Stage 1** (v2 encoder/loader, shards 1–2 only).
- **Stage 1+ (container, Rust; only on GO):** encoder/loader v2 in
  `spike/vectorium_fork` (`DotVByteFixedU8Encoder` lineage, format-version
  bump, cross-version load rejection per the existing
  `dotvbyte_convert_parity` pattern). Convert shards 1–2 ONLY. Gate a vs
  their f16 twins at n=100 (`e7_dotvbyte_gates.py` convention).
  **Bars:** both shards ≥0.99; on-disk size within ±2% of dv v1 (*est.*
  ~−6% per SFR1); warm p50 ratio ≤1.05 vs dv v1; T1 sequential≡parallel green.
- **Stage 2 (host):** full 8-shard re-conversion (E7c-scale, ~a day) + a
  G8d-convention re-run. **Bar:** corpus mean ≥0.995 (*est.*), no shard <0.99.
- **Effort:** medium (converter+reader). **Risk:** quality-free until Stage 1
  ships; v1 shards keep serving throughout.
- Backlog row: `11_EXPERIMENT_BACKLOG.md` Tier 3 E8.

### Q2 — M7 Stage-0 sim (bitmap/intersection; quality-free; cheapest new information)

- **Goal:** decide GO/KILL on moving the query-membership test before the
  gather (the measured 76.7% zero-lane waste).
- **Method (container, zero Rust):** write
  `scripts/seismic_testbed/m7_pack_membership_sim.py` — lane-accounting sim
  on real candidate sets (shard 1 or 2 per rule §2.1): distribution of
  query-hits per 8-lane pack.
- **Bars (pre-registered in `math_optimization/08` §M7):** all-miss-pack
  rate ≥0.5 → GO for a Rust spike; <0.3 → KILL; between → bitmap-gather
  variant only.
- **RESULT (2026-07-08): KILL.** Combined all-miss-pack rate **0.194**
  (shard1 0.197, shard2 0.190; both shards, n=100) — below the 0.3 KILL bar.
  Hits anti-cluster exactly as 08 §M7's caveat warned: ~80% of packs carry
  ≥1 query hit, so the pack-skip never fires. Per-lane zero rate 0.7646
  reproduces 06's 76.7% inventory (sanity anchor).
  `data/eval_results/m7_pack_membership_sim_20260708.json`; verdict recorded
  in `math_optimization/08` §M7. **Q2 closed; queue advances to Q3 (M8).**

### Q3 — M8 survivors-per-block instrument (quality-free by construction)

- **Method (container):** ~20-line counter in the traverse path (or offline
  from posting-block stats): average candidates contributed per surviving
  posting block.
- **Bars (`math_optimization/08` §M8):** typical batch ≥4 → build the
  register-blocked kernel (bit-identical, latency gate only); <2 → M8 dies
  on paper.

### Q4 — M2b: i32-widen, 7-bit query (lossy — DEMOTED below the quality-free items post-G8d)

- **Pre-gate first (container, zero Rust):**
  `m2_pregate_query_integer_dot.py` at 7-bit/i32, **n=100, shards 1–2**.
  Honest prior: thin — M2's f32 control itself sat at 0.991 vs the 0.99 bar.
- **Bars:** overlap@10 ≥0.99 on BOTH shards at n=100 → build the kernel
  variant behind the existing `SFU_SEISMIC_M2_INT6` plumbing (protocol
  stages in `math_optimization/05`); else record and stop — and the FAIL
  also kills Q5's quality leg.

### Q5 — M6: VNNI/UDOT hardware integer dot (gated on Q4's verdict + hardware inventory)

- **Pre-gates:** (a) cpuid inventory across dev/host/DO CPUs
  (`lscpu | grep -i vnni`; ARM `asimddp`); (b) Q4's 7-bit n=100 verdict
  (same arithmetic width, so Q4 answers M6's quality question).
- Full candidate spec + operand-order footguns: `math_optimization/08` §M6.

### Q6 — E5 co-access reordering sim (the one remaining fault-COUNT lever)

- **Method (container):** doc 10 §7.4 pack-walk method
  (`e7_straddle_analysis.py` lineage) on real query candidate sets;
  simulate a co-access permute of the forward index at page-touch
  granularity. **Bar:** simulated majflt ratio clears ~0.45 before any
  converter/id-indirection is built.
- **RESULT (2026-07-09): GO.** Real candidate sets via the fork's new
  `search_visited` hook (fork 8af7088; bit-identical results; first 150M
  candidate-count measurement: mean ~17.8k/query/shard). Buildable
  posting-pack-walk first-touch order: **0.376/0.393 (shards 1/2, f16),
  0.382/0.400 (dv)** — worst shard 0.393 clears the 0.45 bar; held-out
  queries identical; log-driven ceiling 0.345–0.358 (the index-derived
  order captures most of it); random control 1.01.
  `scripts/seismic_testbed/q6_e5_coaccess_sim.py`,
  `data/eval_results/q6_e5_coaccess_sim_20260709.json`; docs 09 §3.2–3.4
  + 10 §7.4 item 2 updated.
- **Q6b/Q6c ordering research + converter + shard1 gates DONE (2026-07-09,
  doc 13).** Ordering: `block_walk_canonical` chosen (0.3927 worst-shard);
  hot/cold-first + per-doc single-term keys + bespoke meta-DB orders all
  refuted (meta_section_year 0.999 — the forward is already section-ordered).
  Converter `reorder_mmap_dir` (both layouts) shipped in the fork (a0c17d4)
  with a tie-aware parity contract. **shard1 real-shard gates: E5_ALL_GATES_PASS
  — parity bit-identical, cold majflt 0.53× (−47%), cold p50 1.46×, warm
  1.12×** (`e5_shard_gates_20260709_0917.json`). **Next: 8-shard rollout
  decision** — convert shards 0,2–7 + new manifest + `SFU_SEISMIC_SHARD_MANIFEST`
  flip (one-env rollback); OR fold into the queued E8 dv-v2 re-conversion so
  the corpus is rewritten once (doc 13 §3).

### Host-tier (needs the 58 GB host session; batch into the next one)

| Item | What | Bar / note |
|---|---|---|
| **H5** sequential dv @6G | the localized-deploy cell — full 150M inside a 6 GB cap | backlog `11` Tier 2 (pre-registered) |
| **Federated-merge overlap** | the G8d scope caveat: dv-vs-f16 on the *merged* 8-shard top-10 | co-resident needs >32 GB; a two-pass method (record each arm's federated top-10 in separate runs, compare offline) would avoid co-residence — *method idea, unvalidated* |
| **Absolute nDCG for the dv leg** | parity can't see real relevance; `rejudge_seismic_leg_n120.py` lineage | optional; run after Q1 settles the format |

### Parked (reasons recorded — do not re-derive)

M9 shuffle-LUT and M10 native-f16 (`math_optimization/08`), E3
n_postings-down (blocked on build budget, backlog `11`), E7-readahead-on-ext4
(Rule Zero, backlog `11`).

## 4. Decision ledger (dated one-liners; details in the named docs)

- **2026-07-02 E6/E6b:** SFR1 codec designed + measured; FixedU8Q reuse won
  on equal shard0 quality (doc 10 §5). Per-doc scale kept on record — now Q1.
- **2026-07-03 E7:** dv shipped + gates; gate b PASS via native rebuild;
  M2 implemented, NOT promoted (n=100 fail).
- **2026-07-03 E7b:** dv PROMOTED for RAM-constrained deploys; gate c closed
  as superseded (doc 10 §7.5).
- **2026-07-04 E7c + G8b/G8c:** all 8 shards converted; full-corpus −40% RSS,
  latency-neutral; capped cells measured (doc 10 §7.5, backlog `11`).
- **2026-07-05 G8d:** per-shard parity all 8 — 0.9906 corpus mean, shards 1–2
  0.985; **accepted** (doc 10 §7.6).
- **2026-07-05 (this doc):** worst-case-shard rule adopted; M-track order
  amended to M7 → M8 → M2b → M6; E8 (dv-v2 per-doc scale) pre-registered as
  the quality-recovery lever.
- **2026-07-08 G8f (container, served path):** traverse attribution — at
  k'=200, 38.3 ms = max-shard 10.1 + **scheduling 27.7** + merge 0.26:
  the per-query `ThreadPoolExecutor` construction dominates (persistent
  executor = the new top latency lever, *est.* −20+ ms, unmeasured).
  **k' federated gate PASSED at n=100** (merged overlap@10 0.999, 1.47×)
  → **served default k' flipped to `max(2×top_k, 100)`** (doc 09 §2.2
  follow-up paid; docs THIN_CLIENT_SWAP + sequential 01 updated).
- **2026-07-09 D2 (container, served path):** **ORT bert fusion (exact
  GELU) PROMOTED as served query-encoder default** `models/splade_onnx_fused`
  — encode 1.11×, merged overlap@10 **0.999**/@50 1.0, sequential ≡
  parallel 100/100; paired served e2e **−5.6 ms p50**. FastGelu arm faster
  (1.14×) but bar-grazing (overlap 0.990 exactly) → NOT promoted. Thread
  pinning (0.40–0.86×) and spinning-off (0.65×) REFUTED — ORT defaults win.
  Methodology rule recorded: only same-process interleaved A/Bs are
  promotable on this container. Doc 08 §D,
  `data/eval_results/d2_*_20260709_*.json`.
- **2026-07-09 D1 (container, served path):** **dynamic-int8 query encoder
  KILLED** — encode 1.3–1.6× faster but merged overlap@10 **0.791/0.798**
  (full-model / head-excluded arms) vs the ≥0.99 bar: encoder asymmetry
  against the fp32-encoded 150M doc vectors, damage in the transformer
  body. Sequential method covered: parallel ≡ sequential bit-identical
  100/100 on both fp32 and int8 qvecs. Misnomer found: `models/splade_onnx`
  ≡ `models/splade_onnx_fp16` (byte-identical fp32). Encoder levers left:
  static/calibrated int8, ORT graph fusion (lossless), distilled encoder —
  all unmeasured. Doc 08 §D, `data/eval_results/d1_int8_query_encoder_*.json`.
- **2026-07-09 Q6 (container):** **E5 co-access reordering sim GO** — real
  candidate sets (new fork hook `search_visited`, 8af7088; first 150M
  candidate count: ~17.8k/query/shard mean); buildable pack-walk order
  simulates **0.376–0.400× unique forward pages/query** on shards 1–2
  (bar ≤0.45), log-driven ceiling 0.345, random control 1.01 → **E5
  converter green-lit** (permutation key = posting-pack walk order).
  §Q6 above; docs 09 §3.2–3.4, 10 §7.4;
  `data/eval_results/q6_e5_coaccess_sim_20260709.json`.
- **2026-07-08 G8g (container, served path):** **persistent executor
  SHIPPED, the *est.* −20 ms REFUTED** — same-process A/B measured
  **−2.3 ms paired traverse p50** (26.4 → 22.8 ms at k'=100, n=100×3,
  100/100 bit-identical; pre-registered sched<5 ms bar FAILED at 10.3 —
  kept anyway, strictly faster + zero risk). G8f's "scheduling 27.7" was
  mostly k'-dependent GIL result-materialization + a stagger artifact of
  per-query spawns, not pool cost → **no large federation-machinery lever
  remains; encode (~20 ms) is now the top addressable component**. New
  served warm headline: **p50 53.8 ms = encode 19.5 + traverse 33.7**
  (was 64.2 at k'=200). Doc 08 §A4 (G8g note),
  `data/eval_results/g8g_*_20260708.json`.
- **2026-07-08 G8e encode/traverse split (container, served path):** warm
  p50 64.2 ms = **encode 20.0 ms (31%) + traverse/fan-out/merge 43.7 ms
  (69%)**; total reproduces G8b's 64.5 ms (G8b included encode). With the
  single-shard kernel at ~3–6 ms, **federation machinery is the largest
  addressable latency component**. Doc 08 §A4 (measured note),
  `data/eval_results/g8e_encode_traverse_split_20260708.json`.
- **2026-07-08 Q1/Q2 Stage-0 (container):** E8 per-doc scale **GO**
  (0.997/0.993 vs FixedU8Q 0.985/0.984, shards 1–2, n=100) → Stage 1 next;
  M7 pack-membership **KILL** (all-miss-pack rate 0.194 < 0.3) → queue
  advances to Q3 (M8 instrument). Result files + rows: backlog `11` Tier 3,
  `math_optimization/08`.
- **2026-07-06 SERVING PROMOTION:** `SFU_SPLADE_BACKEND` default flipped
  `qdrant` → `seismic` in the dev container (dv manifest as the code default;
  filtered-leg over-fetch + partial-manifest guards fixed pre-flip; 17/17
  serving tests). Qdrant/BMP slated for the archival-container split. Canonical:
  `docs/SEISMIC_ARCHIVE_SPLIT.md` + `docs/THIN_CLIENT_SWAP.md` leg table.

## 5. Asset map (what everything runs against)

- **dv shards (served):**
  `data/seismic_150m/index/plan01/global_shard{0..7}of8.dotvbyte.mmap`
  (~3.97 GB forward each; 8-shard dv manifest from E7c).
- **f16 twins (parity reference):**
  `data/seismic_150m/index/plan01/global_shard{0..7}of8.mmap` — required by
  every gate-a run; do not delete.
- **Gate harnesses:** `scripts/seismic_testbed/e7_dotvbyte_gates.py` (gate
  a/b/c per shard), `serve_footprint_bench.py` (G8 regime-aware, federated),
  `e6b_fixedu8_quality.py` + `e6_forward_codec_proto.py` (Stage-0 proxies),
  `m2_pregate_query_integer_dot.py` (integer-dot pre-gates).
- **Kernel/format code:** `spike/vectorium_fork` (encoder, converter,
  `dotvbyte_fixedu8.rs` kernel), build recipe in `math_optimization/05` §build.
- **Latest parity record:** `data/eval_results/e7_parity_shard{0..7}of8_20260705.json`
  + `g8d_8shard_parity_summary_20260705.json`.
