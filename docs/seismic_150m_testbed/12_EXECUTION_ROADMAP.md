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
| E8 dv-v2 quality recovery | **Stage 2 COMPLETE 2026-07-13, all 8 shards + federated gates PASS**; corpus-mean overlap@10 **0.9955** (recovers G8d's 0.9906, +0.0045) at +0.67% size, warm ≤1.05× all arms, T1 20/20; **served default since the 2026-07-14 operator-authorized flip** (`fcfcfb2`; v2.e5 manifest, one-env rollback to v1.e5) | §3 Q1, `THIN_CLIENT_SWAP.md`, `e8_stage2_*_20260713.json` |
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
- **Stage 1 RESULT (2026-07-10): GO — ALL 4 GATES PASS on both shards.**
  Measured by `scripts/seismic_testbed/e8_dvv2_gates.py` (n=100, k'=200,
  hf=0.8, PREFLOOR=2, 3 alternating-order reps, fadvise-evicted cold cells)
  → `data/eval_results/e8_dvv2_stage1_shard{1,2}_20260710.json`:
  | gate | bar | shard1 | shard2 |
  |---|---|---|---|
  | (a) overlap@10 v2 vs f16 | ≥ 0.99 | **0.997** (dv1: 0.985) | **0.993** (dv1: 0.984) |
  | (b) on-disk vs dv v1 | ±2% | **+0.673%** | **+0.672%** |
  | (c) warm p50 vs dv v1 | ≤ 1.05× | **0.985×** | **1.039×** |
  | (d) T1 seq≡warm bit-identity | hard=0 ∧ swaps=0 | **0/0** | **0/0** |
  The (a) numbers reproduce the Stage-0 proxy EXACTLY (0.997/0.993) — the
  codec is proxy-faithful. Cold p50 1.02×/0.92×, majflt 1.009×/1.008× (info;
  the +2 B/record head ≈ +0.9% pages). **Build (same date):** record envelope
  `[u16 len][f16 vmax][…v1]` (vectorium `dotvbyte_fixedu8.rs`, per-doc kernels
  factored `Σ(u8·q)·vmax/255`; `push_encoded_per_doc` from ORIGINAL f32,
  proxy-exact `vmax = f16(max)` first), `ValueScale::PerDocLinear` on
  `convert_f16_dir_to_dotvbyte` → `forward_format_version: 2`, version-aware
  `from_mmap` (unknown versions refused loudly; encoder flag serde(skip) —
  bincode fixed-int would break v1 `forward_encoder.bin`), pyo3
  `forward_format = "dotvbyte_fixedu8_v2"`, bin `--value-scale perdoc`.
  Served-v1 regression: shard1 f16/dv.e5 load+search unchanged (overlap@10
  0.980 @ n=20 vs recorded 0.985 @ n=100). v2 dirs
  `global_shard{1,2}of8.dotvbyte.v2.mmap` are BUILD-ORDER (E5 perm folds in
  at Stage 2) and are NOT served — the e5 v1 manifest is untouched.
- **Stage 2 (host):** full 8-shard re-conversion (E7c-scale, ~a day) + a
  G8d-convention re-run. **Bar:** corpus mean ≥0.995 (*est.*), no shard <0.99.
  **READY TO RUN (2026-07-10):** plan `.claude/plans/e8-stage2-host-dvv2-serve.md`
  (pre-registered bars a–f incl. federated warm ≤1.05×/cold ≤1.10× + T1 + serve
  flip); paste-ready host runbook
  `scripts/seismic_testbed/HOST_PROMPT_E8_STAGE2_DVV2.md`. Batch into the next
  58 GB host session.
- **Stage 2 shard-0 proving run (2026-07-10 container):** the full Stage-2
  chain (convert `--value-scale perdoc` → E5 reorder → gate a/b/e/f) was proven
  end-to-end on **shard 0** (the next unconverted shard, not a Stage-1 shard)
  in the 31 GB dev container — de-risking the host run. Result
  `data/eval_results/e8_stage2_shard0_20260710.json`
  (`e8_dvv2_gates.py` convention, `--v2-dir` = the **reordered** e5.v2 dir):
  | gate | bar | shard0 |
  |---|---|---|
  | (a) overlap@10 v2.e5 vs f16 | ≥ 0.99 | **0.995** (dv1: 0.991) |
  | (b) on-disk vs dv v1 | ±2% | **+0.678%** |
  | (c) warm p50 vs dv v1 | ≤ 1.05× | **0.974×** |
  | (e) T1 seq≡warm bit-identity | 0/0 | **0/0** |
  Cold p50 0.69×, majflt 0.54× (info; shard0 page-cache state — paired
  same-run ratios only are verdicts). Convert `sanity_max_value_absdiff`
  0.006 (u8-quant bound); reorder `doc_mapping_permuted` true,
  `verify_docs_checked` 2001 (gate f). Build-order `.v2.mmap` dir deleted
  after reorder+gate (reclaim 5.5 GB); e5.v2 dir (5.54 GB) retained. **Rule
  Zero clean:** all 24 input dirs + perms byte-identical pre/post. Shards
  1–2 reorder-only (Stage-1 v2 dirs exist); shards 3–7 + the federated c/d
  gates + serve flip remain for the host session. (The result JSON's
  `purpose` field reads "Stage-1 gates" — the harness is reused verbatim;
  this is a Stage-2 measurement on the reordered e5.v2 dir.)
- **Stage 2 COMPLETE — 8/8 shards, ALL GATES PASS (2026-07-13, in-container
  under a temp 58 GB `.wslconfig` cap; driven from host-ops).** Remaining shards
  3,4,5,6,7 converted (`--value-scale perdoc`) + E5-reordered + gated; 1,2
  reorder-only from the Stage-1 v2 dirs; shard 0 from the proving run above.
  Per-shard `data/eval_results/e8_stage2_shard{k}_20260713.json` (shard0 =
  `…_20260710.json`). Build parallelized (3-wide converts), **gates run serially
  isolated** (latency-sensitive). Per-shard overlap@10 v2.e5 vs f16 **0.993–0.997**
  (all ≥0.99), size **+0.67%**, warm **0.97–1.03×**, T1 **0/0** every shard.
  - **Federated gate a (quality) PASS:** corpus-mean overlap@10 **0.9955**
    (bar ≥0.995), min 0.993 (bar ≥0.99), vs dv1/e5 baseline 0.9910 → **+0.0045**.
    `e8_stage2_federated_quality_20260713.json`.
  - **v2 served manifest built:** `seismic_c25_shards_150m_mmap_e5_v2.json` (new
    file; served v1 `…_e5.json` untouched) — all 8 `forward_format
    dotvbyte_fixedu8_v2`, cardinality-verified.
  - **Federated footprint/latency A/B PASS (all 3 serving arms), v2.e5 vs served
    v1.e5**, 100 q · 2 reps · fadvise-DONTNEED cold protocol · VmSwap≈0 · paired
    ratios (`e8_stage2_ab_comparison_20260713.json`): parallel (served default)
    **cold 1.067× / warm 0.980×**; sequential **cold 0.872× / warm 0.976×**;
    hybrid **cold 0.992× / warm 0.956×** (bars cold ≤1.10× / warm ≤1.05×). The
    hybrid arm's 2-rep cold missed at 1.16× (cold-cache variance); a **6-rep
    re-bench resolved it to 0.992×** (`e8_stage2_hybrid_rebench_20260713.json`).
  - **T1 seq≡parallel≡hybrid: 20/20 bit-identical** on the v2 manifest.
  - **Rule Zero clean:** all read-only inputs byte-identical pre/post the session.
  - **SERVE FLIP LANDED (operator-authorized, 2026-07-14, commit `fcfcfb2`):**
    `retriever.py` default → v2.e5 manifest (`…_e5_v2.json` wins the ladder when
    `SFU_SEISMIC_SHARD_MANIFEST` unset); `THIN_CLIENT_SWAP.md` updated same
    commit. **Runtime note:** the flip is *armed in code* — at the time of
    writing no retrieval server is live in the testbed and production
    `sfu-library-mcp` is stopped, so v2 loads on the next service start (not
    live-serving this instant). Rollback stays one env
    (`SFU_SEISMIC_SHARD_MANIFEST` → `…_e5.json`); v1.e5 + plain-dv shards remain
    on disk as the rollback ladder (~44 GB co-resident — see
    `STORAGE_BUDGET_150M.md`). Justification (reconfirmed): quality +0.0045
    (0.9955 vs 0.9906), warm p50 faster all arms, cold within bars (parallel
    +6.7%, ≤1.10×), +0.67% size.
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
- **RESULT (2026-07-10): GO.** New pyo3 `MmapSeismicIndex.search_block_stats`
  hook (per-surviving-block candidate count; quality-free, results
  bit-identical to `search`, 100/100 parity). Shards 1–2, both dv (served)
  + f16 (twin), n=100, k'=100, query_cut=all
  (`q3_m8_survivors_per_block_20260710.json`): **median candidates/block =
  18** (both shards, both codecs — codec-independent as predicted, the
  posting-block structure is shared); mean 23.5, p25 11, p75 29; **97.6%
  of surviving blocks carry ≥4 candidates** (only 0.4% <2). worst_median
  18 ≫ 4 → **GO for the register-blocked kernel** (next build; bit-
  identical, latency-gated per math 08 §M8). The .so rebuilt (native); the
  12/12 sequential parity suite re-passes (instrument didn't break the
  served path). Q3 closed → M8 unblocked for the kernel build.
  **Kernel build READY TO RUN (2026-07-10):** plan
  `.claude/plans/m8-register-blocked-kernel.md` (bit-identical by
  construction; pre-registered bars — identity 100/100, PROMOTE at warm
  traverse ≤0.95×, KEEP <1.00×, REVERT ≥1.00×; cold reported wall-clock
  only, never gate-c); paste-ready session prompt
  `scripts/seismic_testbed/SESSION_PROMPT_M8_KERNEL.md` (container).
  **Kernel BUILT + MEASURED 2026-08-10 — gate c REVERT; ships in-tree
  DEFAULT-OFF behind `SFU_SEISMIC_M8_BATCH=1` (M2 precedent). M8 CLOSED.**
  Gate a bit-identity PASS 100/100 every cell (shards 1–2 × f16/dv ×
  ON/OFF vs the pre-M8 .so; `m8_batch_kernel_gatea_20260810.json`);
  gate b suites PASS (vectorium 136/136, fork 10/10, pytest 19/19);
  gate c warm p50 ON/OFF **1.0223× / 1.0435×** (REVERT ≥1.00 bar;
  `m8_batch_kernel_gatec_20260810.json`); gate d not run (moot).
  Driver `scripts/seismic_testbed/m8_batch_kernel_gates.py`. The first
  gate-a run caught the pre-existing scalar-sparse batch6 override being
  non-bit-exact (f16 3301/3328 hard) → M8 got its own
  `compute_distances_batch6_exact` seam. Full record: math 08 §M8. Both loop copies restructured (posting_list.rs
  AND the verbatim mmap_index.rs copy the served MmapSeismicIndex path
  actually uses — a recorded deviation from the plan's single line-anchor),
  behind `SFU_SEISMIC_M8_BATCH` (=0 forces the verbatim old loop; live-
  flippable in-process). Second recorded deviation: batch width 6 via the
  pre-existing `compute_distances_batch6` trait seam (dense-batch6 house
  precedent) instead of the plan's width-4 new API; bars unchanged. The
  interleaved dotvbyte kernel (six independent `Simd<f32,8>` accumulators,
  one shared query pass, per-candidate op order preserved exactly) covers
  BOTH value scales (v1 1/64, E8 v2 per-doc vmax/255); M2-int6 falls back
  to scalar. Fork-local commit 8b51b0b (+ completes the half-committed Q3
  signature halves that had left fork HEAD 85e30dd uncompilable); tracked
  as `spike/seismic_upstream_m8_batch.patch`; vectorium change tracked
  directly (main-repo 844c81b). Tests: vectorium 136/136 (7 new, all
  f32::to_bits equality, mutation-checked); fork m8 tests green (widths
  1/2/3/6/13/18 + ragged multi-term, mmap↔in-RAM cross-equality). Gate
  driver `scripts/seismic_testbed/m8_batch_kernel_gates.py`. Results row
  lands here when gates a–d complete.


### Q4 — M2b: i32-widen, 7-bit query (lossy — DEMOTED below the quality-free items post-G8d)

- **Pre-gate first (container, zero Rust):**
  `m2_pregate_query_integer_dot.py` at 7-bit/i32, **n=100, shards 1–2**.
  Honest prior: thin — M2's f32 control itself sat at 0.991 vs the 0.99 bar.
- **Bars:** overlap@10 ≥0.99 on BOTH shards at n=100 → build the kernel
  variant behind the existing `SFU_SEISMIC_M2_INT6` plumbing (protocol
  stages in `math_optimization/05`); else record and stop — and the FAIL
  also kills Q5's quality leg.
- **RESULT (2026-07-10): FAIL — KILL (kills Q5).** New driver
  `q4_m2b_integer_dot_pregate.py` (7-bit query + i32 horizontal
  accumulation, the widened M2 variant; n=100, k'=100 served default, shards
  1–2 f16 twins): shard1 `query_int7_i32` ov@10 **0.987** (min 0.9); shard2
  **0.983** (min 0.8) — both below the 0.99 bar. The i32 widening does NOT
  rescue the loss: 255×127=32385 ≪ 2^31 (i32 never saturates, faithfully
  modeled by Python arbitrary-precision `int(sum)`), so the gap is the 7-bit
  query quantization resolution, not the accumulation width. Same regime as
  M2's 0.984 fail (math 07) — arithmetic-width widening alone does not make
  integer-dot query quantization quality-safe. int6 boundary reproduced
  (0.983/0.979). **No cpuid inventory run; no kernel build. Q4 + Q5 closed
  together** (Q5/M6 same arithmetic width ⇒ Q4 answers its quality question).
  `data/eval_results/q4_m2b_pregate_20260710.json`.

### Q5 — M6: VNNI/UDOT hardware integer dot (gated on Q4's verdict + hardware inventory)

- **Pre-gates:** (a) cpuid inventory across dev/host/DO CPUs
  (`lscpu | grep -i vnni`; ARM `asimddp`); (b) Q4's 7-bit n=100 verdict
  (same arithmetic width, so Q4 answers M6's quality question).
- Full candidate spec + operand-order footguns: `math_optimization/08` §M6.
- **RESULT (2026-07-10): KILLED by Q4's FAIL.** Q4's 7-bit/i32 overlap@10
  0.987/0.983 < 0.99 ⇒ M6 (VNNI/UDOT, same arithmetic width) is quality-
  unsafe by the same bound. No cpuid inventory run (moot); no kernel build.
  Q5 closed (killed transitively by Q4). See Q4 RESULT above.

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
  1.12×** (`e5_shard_gates_20260709_0917.json`).
- **Q6 CLOSED (2026-07-09).** 8-shard rollout DONE + SERVED (commit 6170e1d:
  all shards converted, parity 0-hard on all 8, retriever default → e5
  manifest, one-env rollback); **full-federated 150M cold A/B CONFIRMED
  in-container (commit 8f05aeb): cold p50 0.569× (1.76×), all cells VmSwap 0,
  warm ≪ cold** — doc 13 §5 + doc 06 row. Ordering headroom is exhausted
  (oracle ceiling 0.358 vs shipped 0.393); successor levers are Q7–Q9 below.

### Q7 — Cold-start hybrid federation (sequential-cold → parallel-warm; measured basis, cheapest unclaimed serving win)

- **Basis (measured 2026-07-09, `e5_fullcorpus_cold_container_*.json`):**
  sequential federation cold p50 **2159 ms < parallel 2687 ms** (8-way cold
  fan-out contends on the 9p/disk channel) at VmRSS peak 1.34 GB vs 25.2 GB;
  warm inverts hard (parallel 80–101 ms ≪ sequential 367 ms). A backend that
  serves sequentially while cold and flips to parallel once warm captures
  both regimes.
- **Method (container):** `--federation hybrid` in the sharded backend —
  start sequential, flip to parallel on a *state* signal, not a timer
  (pre-register the signal: e.g. per-query traverse time crossing below a
  threshold, or cumulative majflt rate flattening; a fixed query-count
  fallback is the control arm). Both modes are already bit-identical, so
  the flip cannot change results — T1 stays the parity gate.
- **Bars (pre-registered):** hybrid cold p50 ≤ 1.05× sequential's cold;
  hybrid steady-state warm p50 ≤ 1.05× parallel's warm; T1
  sequential≡parallel≡hybrid 100/100. Eval = `serve_footprint_bench.py`
  A/B/C (parallel / sequential / hybrid), fadvise-DONTNEED eviction
  protocol per the 2026-07-09 container run.
- **RESULT (2026-07-10): bars PASS, NOT PROMOTED.** 3-arm × 2 reps
  (`q7_hybrid_federation_20260710.json`): rep1 seq/par/hyb cold
  3091/2093/2064 ms, rep2 2243/2114/2035; warm 329/56/58 + 289/66/56;
  VmSwap 0 + warm<cold on every cell (all valid); **T1 20/20 bit-identical**.
  Bars: hybrid cold 0.79× seq (≤1.05 PASS), hybrid warm 0.94× par (≤1.05
  PASS). Hybrid emitted as `HybridSeismicBackend` + `--federation hybrid`;
  count-backstop N=3 + adaptive threshold (cold-geomean × 0.25) both
  pre-registered.
  **Substantive finding (honest, the reason it is NOT promoted):** on THIS
  container sequential is the *slow* cold arm (rep1 3091 vs par 2093) — the
  opposite of the 2026-07-09 basis (seq 2159 < par 2687). Hybrid (~2.05 s)
  tracks **parallel** cold, not sequential, because the N=3 backstop flips
  to parallel before most of the cold pass runs — so hybrid captures the
  faster (parallel) cold regime here, NOT the sequential cold advantage the
  basis measured. Sequential keeps its RAM win (anon 1.05–1.10 GB vs par
  1.12–1.14 vs dv 25 GB). On a host where sequential *would* win cold (the
  basis host), the eager flip would switch away from the winner too soon →
  the flip policy needs refinement (stay sequential while it's winning the
  cold regime, e.g. a seq-vs-par probe) before any promotion. **Parallel
  stays the served default.** Q7-followup = the flip-policy refinement;
  the class + parity machinery are kept (correct + never worse than the
  better arm). Docs: doc 06 row + this verdict line; result +
  `q7_hybrid_federation_bench.py` shipped.
  **Fix (same commit):** `q7_hybrid_federation_bench.py` `Path.relative_to`
  crashed at write-time on a relative manifest path; resolve+try/except.


### Q8 — Posting-side cold-fault attribution → co-access sim (Q6 lineage; sim before ANY converter)

- **Question:** E5 reordered the *forward* files; posting_lists.bin +
  summaries + doc-mapping floors still fault cold (the E5 gates prefaulted
  them symmetrically via `PREFLOOR=2`, so their cost is measured-out, not
  eliminated).
- **Stage 0a (attribution, zero Rust):** one cold run per arm with floors
  NOT prefaulted; attribute majflt per file (mincore snapshots or per-file
  fadvise deltas). **Bar:** posting-side share ≥ ~25% of residual cold
  faults → Stage 0b; below → KILL on paper (record the share).
- **Stage 0b (page-touch sim, Q6 methodology):** simulate a co-access
  ordering of posting *blocks* on real per-query block-touch sets.
  **Bar:** worst-shard unique-page ratio ≤ 0.60, else KILL — the
  readahead-absorption lesson (doc 10 Fix #5A) says adjacency wins
  under-realize, so demand a decisive sim margin.
- **RESULT (2026-07-10): Stage 0a KILL — Stage 0b NOT run.** Per-file
  mincore attribution (shards 1–2 e5, 40 q × k'=100, no PREFLOOR,
  fadvise-DONTNEED+`release_pages` cold protocol; VmSwap 0 + warm<cold,
  both valid): **posting-side share of residual cold faults 0.071 (shard1)
  / 0.064 (shard2)** — far below the 0.25 bar on BOTH worst-case shards.
  The forward side is ~89% of residual faults (`forward_data.bin` 396k of
  470k pages faulted cold on shard1, the E5-reordered blob → already
  addressed); posting_lists.bin is 6.8%, doc-mapping 4.7%. An E5-for-
  postings reorder would chase <7% of an already-small residual — not
  worth a converter. **Stage 0b does not run** (the bar was conditional on
  0a GO). mincore delta totals (~470k pages) >> process majflt (24,964) —
  expected: 9p readahead pulls many pages per I/O fault; the ~18.8×
  amplification is uniform across files so the per-file SHARE (the
  attribution signal) is unaffected. The per-file method (a shared
  read-only mmap per file + mincore before/after a cold pass) is kept for
  future fault-attribution work. **Q8 closed.**
  `scripts/seismic_testbed/q8_posting_fault_attribution.py`;
  `data/eval_results/q8_posting_fault_attr_shard{1,2}_20260710.json`.


### Q9 — Startup floor prefault (load-time, composes with E5/Q7)

- **Idea:** at backend load, a background thread touches the small
  structural files (forward_offsets, doc-mapping offsets/strings,
  summaries) so the first real query pays only forward-data faults.
  Distinct from the REFUTED per-range query-time WILLNEED (doc 10 Fix #3 —
  that was per-query, this is once at load); pre-register it as such.
- **Bars (pre-registered):** first-query/cold-pass p50 ≥ 1.15× faster with
  prefault ON (else KILL); load-time increase ≤ ~5 s; warm p50 ratio
  ≤ 1.05 (no regression); zero anon growth (touch, don't copy).
- **Eval:** `serve_footprint_bench.py` cold cells, prefault ON/OFF
  alternating, fadvise-DONTNEED protocol.
- **RESULT (2026-07-10): KILL.** 2-arm OFF/ON × 2 reps
  (`q9_floor_prefault_20260710.json`): rep1 OFF load 3.0s/cold 1976/warm 60
  vs ON load 107.2s/cold 2026/warm 60; rep2 OFF 3.1s/2037/65 vs ON
  103.7s/1605/78 (VmSwap 0, warm<cold every cell). Bars: **cold speedup
  1.12× (≥1.15 FAIL, high variance — rep1 ON was SLOWER cold, rep2
  faster)**; **load delta +102s (≤5s FAIL)** — the ~1.5 GB floor × 8
  shards touch via `MADV_WILLNEED|SEQUENTIAL`+page-stride read is ~100s
  over 9p; **warm ratio 1.10× (≤1.05 FAIL)** — the floor touch pollutes
  the cache, displacing warm forward-data pages; **anon growth +0.062 GB
  (zero FAIL)**. Does NOT refute E7 Fix #4's `prefault_floor` mechanism
  (it works at the single-shard gate level, doc 10 §7.3) — refutes its use
  as a STARTUP-time lever over 9p at the federated-8-shard scale, where
  the floor touch is IO-bound and cache-hostile. The pre-registered 1.15×
  bar caught this marginal/negative case by design. **NOT promoted; Q9
  closed.** `SFU_SEISMIC_PREFLOOR_AT_LOAD` stays shipped (off by default,
  harmless) for a future host-tier retry where the floor touch is fast.


### Q10 — Delta side-shard ingest (design-ready; BUILD ONLY when ingest becomes real)

- Design already settled in doc 13 §3: new docs → small shard 9 (own build
  + dv convert; E5-reorder optional — a small shard is cache-resident so
  its ordering is irrelevant); federation manifest already merges K shards;
  fold into the main shards at the next full rebuild. No code needed until
  an actual ingest requirement lands — do not build speculatively.

### Q11 — Encoder upgrade path (query-side; the last untouched ~36% of warm p50)

- **Design + candidate registry: `14_ENCODER_UPGRADE_PATH.md`** (2026-07-10,
  SPIKE — nothing measured). Encode = 19.5 of 53.8 ms warm p50 (G8g);
  literature ceiling = sub-ms lookup encoders (Li-LSR / OpenSearch doc-only
  pattern), but ONLY same-space derivatives of the served model are
  benchmarkable (D1 evidence; off-the-shelf excluded without corpus
  re-encode — doc 14 §1/§5).
- **Order:** C1 expansion-table + C2 IDF-lookup first (shared harness,
  bracket the expansion question) → C3 learned scalar head only if C1
  grazes → C4 layer-truncated student only if lookups fail → C5 static-int8
  opportunistically.
- **Bars (pre-registered, doc 14 §4):** merged federated overlap@10 ≥0.99
  vs served fp32, n≥100, worst-case shards 1–2 + merged; interleaved
  same-process A/B only; T1; ship only via env-gated one-env-rollback (D2
  pattern). KILL of all five closes the encoder book.
- **STATUS 2026-07-10: CHEAP TIER MEASURED OUT (all offline; nothing
  shipped; served fused encoder STAYS).** C1 **0.533** / C2 **0.357**
  merged overlap@10 — static lookups KILLED (mechanism: contextual
  magnitude reweighting, which no static table can do); C3 SKIPPED (same
  static ceiling, per the pre-registered order); C4 untrained-truncation
  pre-gate **0.46–0.51** with L12 control 0.999 (C4 alive, decidable ONLY
  by a real distillation build); C5 static-int8 **0.006** and 5.5× slower
  (with D1's 0.79, the int8 encoder family is dead end-to-end). Remaining
  paths = doc 14 §5.1 training-tier prechecks (C4 distillation build;
  1M-slice shelf domain pilot; fine-tune probe — the pilot-vs-probe delta
  IS the measured value of "custom"). Results
  `data/eval_results/q11_{c1c2_stage0,c4_pregate,c5_static_int8}_20260710_*.json`;
  ledger doc 14 §6.
- **STATUS 2026-07-28: C4 DISTILLATION MEASURED — KILL; ENCODER BOOK
  CLOSED.** The §5.1 precheck-1 build ran in-container (4070 Ti SUPER):
  round-1 qvec-MSE distill gate 0.643–0.690, pre-registered escalation
  (margin-MSE on real shard doc vectors) **0.726–0.760** vs the 0.99 bar —
  KILL (doc 11 §Q11-C4; doc 14 §6 first entry). All same-space candidates
  are now measured dead; ~20 ms encode is the price of this doc space, and
  only the doc 14 §5 re-encode branch (prechecks 2–3: shelf domain pilot +
  fine-tune probe) remains. Served fused encoder STAYS; serving impact zero.

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
- **2026-07-09 E5 SHIPPED + SERVED + CONFIRMED AT SCALE:** converter +
  8-shard rollout + retriever default flip (6170e1d); full-federated 150M
  cold A/B in-container (8f05aeb): **cold p50 0.569× (1.76×)**, warm
  neutral, all cells VmSwap 0; secondary finding — **sequential federation
  beats parallel when cold** (2159 vs 2687 ms at 1.34 vs 25.2 GB resident).
  Doc 13 §5, doc 06 rows. Q6 lineage CLOSED.
- **2026-07-10 (this doc):** queue extended — **Q7 hybrid federation**
  (from the sequential-cold finding), **Q8 posting-side fault attribution
  + sim**, **Q9 startup floor prefault**, **Q10 delta-shard ingest
  (design-ready, parked)**. Session prompt for the open queue:
  `scripts/seismic_testbed/SESSION_PROMPT_OPEN_QUEUE.md`.
- **2026-07-10 Q7 (container):** **hybrid federation bars PASS, NOT
  PROMOTED.** `HybridSeismicBackend` (sequential-cold → parallel-warm on a
  state signal) shipped + measured 3-arm × 2 reps: hybrid cold 0.79× seq,
  warm 0.94× par, T1 20/20 bit-identical → all pre-registered bars clear.
  BUT on this container sequential is the *slow* cold arm (inverted from
  the 2026-07-09 basis), so hybrid ≈ parallel cold (the N=3 backstop flips
  before most of the cold pass). The premise (capture sequential's cold
  win) did NOT reproduce here; on a host where it would, the eager flip
  switches away from the winner too soon. **Parallel stays the served
  default.** Q7-followup = flip-policy refinement (stay sequential while
  winning). Result `q7_hybrid_federation_20260710.json`; §Q7 above + doc 06
  row.
- **2026-07-10 Q9 (container, EFFICACY UNMEASURED):** startup floor
  prefault shipped (`SFU_SEISMIC_PREFLOOR_AT_LOAD`, once-at-load, distinct
  from refuted per-query WILLNEED doc 10 Fix #3); bench
  `q9_floor_prefault_bench.py` wired. Bars pre-registered (cold ≥1.15× /
  load +≤5s / warm ≤1.05 / zero anon). Run pending after Q7 freed the shards.
  **UPDATE 2026-07-10: Q9 KILL.** Measured OFF/ON × 2 reps: cold speedup
  1.12× (FAIL ≥1.15), load +102s (FAIL ≤5s — the floor touch is ~100s over
  9p), warm 1.10× (FAIL ≤1.05, cache pollution), anon +0.062 GB (FAIL
  zero). The pre-registered bar caught the marginal/negative case by
  design. Does NOT refute Fix #4's `prefault_floor` (works at the
  single-shard gate level) — refutes its STARTUP-time use over 9p at
  federated-8-shard scale (IO-bound + cache-hostile). NOT promoted; Q9
  closed. Result `q9_floor_prefault_20260710.json`; §Q9 above + doc 06 row.
- **2026-07-10 Q8 (container):** **Stage 0a KILL — posting side 7.1%
  (shard1) / 6.4% (shard2) of residual cold faults** (bar 25%) on both
  worst-case shards. Per-file mincore attribution (a shared read-only mmap
  per shard file + mincore before/after a cold pass): forward side ~89% of
  residual (already addressed by E5), posting_lists.bin 6.8%, doc-mapping
  4.7%. Stage 0b (posting-block co-access sim) does NOT run (conditional on
  0a GO). An E5-for-postings reorder would chase <7% of a small residual —
  not worth a converter. §Q8 above; result
  `q8_posting_fault_attr_shard{1,2}_20260710.json`; the per-file mincore
  method is kept for future attribution. Q8 closed.
- **2026-07-10 Q3 (container):** **M8 GO — survivors-per-block median 18**
  (bar 4), 97.6% of surviving blocks ≥4 candidates, parity 100/100. New pyo3
  `search_block_stats` hook (quality-free, results bit-identical to `search`);
  shards 1–2 dv+f16, n=100. The `.so` rebuilt (native) with the Optional
  block_stats accumulator (default None = zero overhead); 12/12 parity suite
  re-passes. **M8 unblocked for the register-blocked kernel build** (next
  step; bit-identical, latency-gated). §Q3 above; result
  `q3_m8_survivors_per_block_20260710.json`; math 08 §M8 pre-gate RESULT.
- **2026-08-10 (container):** **M8 register-blocked kernel MEASURED —
  gate c REVERT; in-tree DEFAULT-OFF; M8 + the whole M-candidate book
  CLOSED.** Warm p50 ON/OFF 1.0223×/1.0435× (shards 1–2, one-process
  paired ×3 reps, k'=100; PROMOTE ≤0.95 / REVERT ≥1.00) — the warm regime
  hides no gather latency and the two-phase overhead outweighs the ILP.
  Bit-identity gate a 100/100 every cell both arms; suites green. Two
  latent bugs found + fixed en route: the non-bit-exact legacy
  scalar-sparse batch6 override (M8 re-seamed to
  `compute_distances_batch6_exact`) and the retriever manifest-form
  AttributeError (a335cb0). Results
  `m8_batch_kernel_gate{a,c}_20260810.json`; math 08 §M8 kernel RESULT;
  fork 8b51b0b/27900f3/ddca859 via `spike/seismic_upstream_m8_batch.patch`.
- **2026-08-10 (container, M8-session side-find):** **mmap reader
  summaries_ids length-label BUG fixed** (fork 2c3cf48, patch
  `spike/seismic_upstream_summaries_len_fix.patch`): `read_posting_lists`
  labeled the summaries_ids BitFieldSlice with `n_summaries` (block count)
  instead of `values_len` (summary-posting count) — born c987160
  (2026-07-03). Release serving was NEVER wrong (physical bit length was
  correct; reads in-bounds + value-correct, release parity 7/7), but the
  fork debug suite was red from birth (3/7 mmap parity tests) and any
  future checked `.get()`/`.len()` would have silently truncated. Debug
  suite 10/10 post-fix. No format change (manifests already carry
  `values_len`); no shard rewrite.
- **2026-07-10 Q4 (container):** **M2b 7-bit/i32 FAIL — KILL (kills Q5).**
  7-bit query + i32 horizontal accumulation (the widened M2 variant; n=100,
  k'=100 served default, shards 1–2): `query_int7_i32` overlap@10 **0.987/
  0.983** < 0.99 on both shards. The i32 widening does NOT rescue the loss
  (255×127=32385 ≪ 2^31, never saturates) — the gap is the 7-bit query
  quantization resolution. Same regime as M2's 0.984 fail (math 07). No
  kernel build. **Q5 (M6 VNNI/UDOT) killed transitively** (same arithmetic
  width ⇒ Q4 answers M6's quality question; no cpuid inventory run, moot).
  §Q4 + §Q5 above; result `q4_m2b_pregate_20260710.json`.
- **2026-07-10 plan trail:** E8 Stage-2 + M8 kernel execution plans written
  (`.claude/plans/e8-stage2-host-dvv2-serve.md`,
  `.claude/plans/m8-register-blocked-kernel.md`) with paste-ready prompts
  (`HOST_PROMPT_E8_STAGE2_DVV2.md`, `SESSION_PROMPT_M8_KERNEL.md`) — bars
  pre-registered in the plans, DESIGN ONLY, nothing new measured. All 17
  completed/superseded plans archived to `.claude/plans/done/` (ledger:
  `done/README.md`); active plans = the two above.
- **2026-07-11 Q1 Stage-2 shard 0 (container):** the E8 Stage-2 per-shard chain
  (convert `--value-scale perdoc` → E5 reorder → gates) proven end-to-end on a
  fresh shard in the 31 GB dev container — **1/8 done, IN PROGRESS.** All 4
  per-shard bars PASS on shard 0: overlap@10 0.995, size +0.678%, warm 0.974×,
  T1 0/0 — measured via `e8_dvv2_gates.py` with `--v2-dir` pointed at the
  reordered `e5.v2.mmap` dir (the Stage-2 serving target). Full table + Rule
  Zero + provenance: §3 Q1 "Stage 2 IN PROGRESS" above; result
  `e8_stage2_shard0_20260710.json`. De-risks the host run; remaining = shards
  3–7 (+ reorder-only 1–2) + federated c/d gates + serve flip (host-only).
- **2026-07-13 Q1 Stage-2 COMPLETE — 8/8 shards, ALL GATES PASS (in-container,
  temp 58 GB `.wslconfig` cap, driven from host-ops):** shards 3–7 converted +
  E5-reordered + gated, 1–2 reorder-only. Per-shard overlap@10 0.993–0.997
  (all ≥0.99), size +0.67%, warm 0.97–1.03×, T1 0/0. **Federated gate a
  (quality) PASS:** corpus-mean 0.9955 (bar ≥0.995, min 0.993) vs dv1/e5 0.9910,
  +0.0045. v2 manifest `seismic_c25_shards_150m_mmap_e5_v2.json` built (served
  v1 untouched). **Federated A/B (footprint/latency) PASS all 3 arms** (100 q,
  2 reps, fadvise-DONTNEED, VmSwap≈0, paired): parallel cold 1.067×/warm 0.980×,
  sequential 0.872×/0.976×, hybrid 0.992×/0.956× (hybrid 2-rep cold 1.16× was
  variance, resolved by a 6-rep re-bench). **T1 seq≡par≡hybrid 20/20.** Rule
  Zero clean. Results `e8_stage2_{shard*,federated_quality,ab_comparison,
  hybrid_rebench}_20260713.json`. **SERVE FLIP LANDED (operator-authorized,
  2026-07-14, commit `fcfcfb2`):** `retriever.py` default → v2.e5, `THIN_CLIENT_SWAP`
  updated; armed in code (no server live at flip time — loads next start).
  Rollback one env (`SFU_SEISMIC_SHARD_MANIFEST` → `…_e5.json`). Full detail:
  §3 Q1 "Stage 2 COMPLETE" above.



  `14_ENCODER_UPGRADE_PATH.md` (candidate registry C1–C5, all same-space
  derivatives of the served encoder; bars pre-registered; off-the-shelf
  encoders excluded without corpus re-encode; re-encode branch costed but
  unscheduled). Design only — NOTHING MEASURED.
- **2026-07-10 E1-owed (freshness check, container):** the 2026-07-08 G8f
  k' flip is **CONFIRMED LIVE** — `sharded_seismic_backend._prepare_query`
  line 246 still defaults `kp = max(top_k * 2, 100)` and `retriever.py` line
  669's docstring still states `max(2×top_k, 100)`. Every remaining `k'=200`
  mention in docs/scripts is either (a) explicitly under a FOLLOW-UP PAID +
  FLIPPED banner (doc 09 §2.2 lines 254-261) or (b) a held-constant
  experimental cell / a fixed basis for a bit-identical test
  (`seismic_sequential_serving/03` T1 passes k_prime=200 explicitly to compare
  modes at the SAME k' — correctness, not a default claim). No stale doc to
  fix; no code change. Refreshness gate cleared; latency items (Q7/Q9/Q8)
  unblocked.
- **2026-07-10 Q1 Stage-1 VALIDATION (container, post-GO deep audit):** the
  new dv-v2 module was independently re-validated the same day. Measured:
  (i) **cross-build regression** — current post-E8 `.so` re-ran the Jul-8
  pre-E8 Stage-0 candidate search (f16 dirs, n=100, k'=200, query weights
  verified bit-identical to the cached run): shard1 **100/100 top-200 lists
  bit-exact**, shard2 98/100 exact + 2 adjacent transpositions at ranks
  108/124 whose true f64 score gaps (2.0e-7, 6.7e-7) are **below f32 ulp**
  (~1e-6 at those magnitudes) — sub-resolution ties, identical doc sets, not
  a regression; (ii) **runtime back-compat** — all 8 served `.dotvbyte.e5.mmap`
  v1 dirs load under the post-E8 `.so` (real production `forward_encoder.bin`
  bincode decode over the serde(skip) field) and search; v2 dirs report
  `dotvbyte_fixedu8_v2`; a doctored `forward_format_version: 3` manifest is
  refused loudly (pyo3-level check); (iii) **test suites** — seismic lib 8/8
  (incl. both v1+v2 convert-parity), vectorium 123/125 release (2 fails =
  pre-existing debug_assert NaN tests that only fire in debug; pass under
  debug) + 27/27 doctests; (iv) **one latent defect found & fixed** — per-doc
  vmax > ~65520 overflowed `f16::from_f32` to +inf → decode 0·inf = **NaN
  scores**; unreachable via the f16-dir converter, guarded by f16::MAX
  saturation + new randomized/adversarial stress suite
  `spike/vectorium_fork/tests/e8_dvv2_stress.rs` (5/5). Wheel rebuilt +
  reinstalled from the fixed source (in-range encodes bit-identical: the
  saturation is a no-op ≤ f16::MAX). Post-rebuild re-verification: back-compat
  suite PASS again; cross-build re-run identical (same 100/100 + same 2
  sub-ulp swaps — build-stable); **gate (a) reproduced digit-for-digit on the
  rebuilt `.so`** (v2 0.9970/0.9930, dv1 0.9850/0.9840, n=100). Scripts
  (scratchpad, results inline here): cross-build + forensics vs
  `_stage0_cache/cands_*`.
- **2026-07-10 Q1 Stage 1 (container, Rust):** **E8 dv-v2 per-doc scale GO —
  all 4 pre-registered bars PASS on both shards** (overlap@10 0.997/0.993 vs
  f16 = the Stage-0 proxy EXACTLY; dv1 baseline 0.985/0.984; size +0.67%;
  warm p50 0.985×/1.039×; T1 bit-identity 0/0). Codec = record-head f16 vmax
  envelope, `forward_format_version: 2`, version-aware reader, v1 served path
  untouched (regression-checked). Full numbers + build inventory: §3 Q1
  Stage 1 RESULT above; `e8_dvv2_stage1_shard{1,2}_20260710.json`. **Stage 2
  (host-tier full 8-shard re-conversion + E5-perm fold + G8d re-run) is now
  the unlock for serving v2.**
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
