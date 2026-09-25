# 13 · E5 forward-reorder converter — design, ordering research, ingest impact

**Status:** ACTIVE

> Status 2026-07-09: **SHIPPED + SERVED.** Ordering research MEASURED
> (Q6/Q6b/Q6c); converter IMPLEMENTED (fork a0c17d4); all 8 shards converted
> + parity-verified; shards 1,2 full gates PASS (cold majflt 0.53–0.54×, cold
> p50 1.46–1.51×, warm neutral-to-faster); **served default flipped to the E5
> manifest** `data/eval_results/seismic_c25_shards_150m_mmap_e5.json`
> (`retriever.py`; one-env rollback to the plain-dv manifest). Served
> federated top-10 A/B exact-order vs dv (§5). Parent experiment:
> `09_CROSS_SHARD_MMAP_AUDIT.md` §3.4 (E5) gated by
> `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` Q6 (**GO 2026-07-09**, sim 0.376–0.400, bar ≤0.45).

## 0. Why (one paragraph)

Cold queries are a page-fault problem, not a compute problem (G8e: cold p50
5.3 s / p95 23.1 s, encode share 0.7%). Each query scores ~17.8k candidate
docs/shard (measured, Q6) and today those records are scattered ≈
uniformly across the forward files (~2.03 pages/candidate, ≈140 MB
faulted/shard/cold query on f16). SEISMIC scores candidates in posting-block
bursts of similar docs, so a permutation of the forward files that co-locates
co-block docs lets one 4 KiB page serve many candidates. Q6 simulated the
win at 0.376–0.400× unique pages/query on real candidate sets; scores are
position-independent, so the reorder is quality-free *by construction*
(bit-identical parity is the hard gate).

## 1. Ordering-method research (run BEFORE implementation — this section)

All cells: unique-4KiB-forward-pages/query vs the shipped layout, real
`search_visited` candidate sets, shards 1–2, n=100, k'=200/hf=0.8/qc=all
(Q6 methodology; identity = 1.000 exactly, random control ≈ 1.01).

| Order | Class | Derivable from | Append-friendly? | Worst-shard page ratio (f16) |
|---|---|---|---|---|
| `block_walk_canonical` | general (index) | posting-pack walk, token-id list order | ❌ global first-touch | **0.3927** (Q6/Q6b) |
| `block_walk_hotfirst` | general (index) | same walk, longest lists first | ❌ | 0.3945 (Q6b) |
| `block_walk_coldfirst` | general (index) | same walk, shortest lists first | ❌ | 0.6367 (Q6b) |
| `home_component` | general (index) | per-doc argmax-value SPLADE term | ✅ per-doc key | 0.7436 (Q6b) |
| `home_component_val` | general (index) | (home term, value desc) | ✅ per-doc key | 0.7123 (Q6b) |
| `meta_section_year` | **bespoke (meta DB)** | `meta.sqlite` `docs.section`‖`year` | ✅✅ known pre-index | 0.9988 (Q6c) |
| `meta_section_year_home` | **bespoke (meta DB)** | section‖year‖top-SPLADE-term (doc 09 §3.4's original proposal) | ✅✅ | 0.7675 (Q6c) |
| `coaccess_sig` | oracle ceiling | query logs (held-out eval) | ❌ not productionizable | 0.358 (Q6) |

Results: `q6b_order_sweep_20260709.json` (+ Q6's `q6_e5_coaccess_sim_20260709.json`).

**Selection rule (pre-registered in `q6b_order_sweep.py`):** best
append-friendly order if within +0.03 worst-shard page ratio of the best
global order; else best global order. Rationale: §3 — an ingest-time
computable key keeps incremental adds open, worth ≤0.03 pages.

**Q6b verdict (2026-07-09): `block_walk_canonical` CHOSEN.** The
append-friendly single-term keys are not competitive (0.71–0.74 — one
SPLADE term does not capture block co-access; a doc's ~87 lists matter
jointly), far outside the +0.03 margin. Hot-first ties canonical (Δ0.002 —
list visit order is a free parameter at the top); cold-first at 0.637 shows
short-lists-first actively hurts (long lists' blocks are the co-access
structure worth contiguity). Mechanism record: the win comes from
block-burst adjacency, not term identity — and the ~0.35 oracle ceiling
means canonical already captures ~90% of what ANY ordering can give.
**Q6c verdict (2026-07-09, user-requested bespoke cells): REFUTED —
`block_walk_canonical` stands.** `meta_section_year` = **0.9988** ≈
identity, with a clean mechanism explanation: the shipped forward order IS
already section-ordered (insertion order = section spools concatenated,
09 §3.4), so the bespoke DB key carries no information the baseline lacks
— its era/topic granularity (10 distinct sections over 18.8M docs) is
~2M-doc blocks vs the 4 KiB-page granularity the fault problem lives at.
`meta_section_year_home` = **0.7675** ≈ the home-term key alone (0.71–0.74)
— the meta fields add nothing on top of the SPLADE term. Both far outside
the ≤0.4227 displacement bar. Join method note: chunked-IN sqlite lookups
were killed at 50 min; ONE sequential 150M-row scan + searchsorted
membership does each shard in ~22 min (`q6c_meta_order_sim.py`).
`q6c_meta_order_sim_20260709.json`.

## 2. Converter spec (what gets built)

### 2.1 The mechanism already exists — E5 is a re-driven E7 converter

`convert_f16_dir_to_dotvbyte` (`spike/seismic_upstream/src/mmap_io.rs:1445`)
already performs the exact dangerous half of E5: the posting-lists byte-copy
walk that locates every pack u64, maps its `(offset:48|len:16)` to a doc via
`old_offsets.partition_point`, and rewrites it against `new_offsets` with
boundary/48-bit/16-bit asserts and a walk-desync guard (`mmap_io.rs:1577-1631`),
plus a sampled decode-verify. E5 = the same walk where `new_offsets` comes
from a **permutation** instead of a re-encode:

`reorder_mmap_dir(src, dst, perm)` (new, fork):
1. Read `perm.bin` (u64[n_docs], new-order → old-row; validated bijection).
2. Forward: write permuted `forward_offsets.bin` + forward payload —
   f16: `forward_components.bin`/`forward_values.bin`; dv:
   `forward_data.bin` (records moved verbatim, byte-exact; **no padding —
   Fix #5A proved padding dilutes page-sharing**).
3. Posting lists: the E7 walk, remapping every pack to the doc's new range.
4. **Doc-mapping: `document_mapping_strings.bin`/`_offsets.bin` PERMUTED**
   (the dv converter copies these verbatim — for E5 that would silently
   return wrong doc ids for every result; `id_from_range` resolves rows
   positionally. The T1-style parity gate catches this, but it is THE
   known trap.)
5. Verbatim copies: `config.json`, `token_to_id_map.bin`,
   `forward_encoder.bin` (dv). Manifest: unchanged geometry fields +
   `forward_reordered: "<order-name>"` provenance key (reader ignores
   unknown keys — verified by the existing manifest serde).
6. Untouched by construction: summaries (`QuantizedSummary` — block-level,
   no forward offsets), `block_offsets` (index into packs, not docs),
   EF/bitfield structures, knn (absent on all 150M shards; assert anyway).

### 2.2 What does NOT change

- **The reader/serving path: zero changes.** Packs carry absolute offsets;
  the reader never assumes doc order. A reordered shard is served by the
  same `.so` — rollback = point the manifest back at the un-reordered dir.
- Scores/ranking: bit-identical (same bytes, same arithmetic, same
  traversal order — only WHERE records sit changes).
- On-disk size: byte-identical totals (pure permutation).

### 2.3 Gates (pre-registered)

| Gate | Bar | Method |
|---|---|---|
| parity | **score sequence bit-equal per rank; doc-id SETS equal within every interior score-tie group** on n=100, both shards (tie groups may reorder internally, and a group straddling the k' boundary may swap members — `ScoredRange::cmp` tie-breaks on `range.start`, vectorium `dataset.rs:52-58`, which the permutation changes; quality-neutral by construction, found via the synthetic test 2026-07-09) | serial A/B, `eval_seismic_parity` convention + the `reorder_parity_both_layouts` contract; report tie-swap count |
| decode-verify | sampled records decode == source | converter-internal (E7 pattern) |
| cold efficacy | majflt ratio ≤ 0.60 (sim says 0.38–0.40; bar leaves room for floor noise); kill < 0.85 (doc 09 E5 kill: <15% reduction) | `e7_dotvbyte_gates.py` harness, `release_pages()` + `SFU_SEISMIC_PREFLOOR=2` footing, deterministic reps |
| warm no-regression | warm p50 ratio ≤ 1.05 | same harness warm passes |
| T1 | sequential ≡ parallel, 100/100 | existing suites |

## 3. New-information / ingest impact (the design constraint)

**Today's update model is periodic full rebuild** (`THIN_CLIENT_SWAP.md`:
"Monthly rebuilds later: snapshot JSONL → doc_encoder.py"; pipeline =
spool → K=8 shard build → mmap convert (`REBUILD_TO_PERSISTENT_PATH.md`
stages 1–3) → dv convert). There is **no incremental ingest path**, and the
binding constraint is SEISMIC itself: posting lists, block structure, and
summaries are static build-time artifacts — a new doc cannot be inserted
into an existing shard regardless of E5. E5 therefore cannot *worsen*
appendability; the question is how it composes with each update route:

| Update route | E5 impact |
|---|---|
| **Monthly full rebuild** (current) | Zero marginal design cost: the permutation is re-derived from the freshly built index at convert time (one more converter pass, ~minutes/shard). No persistent state, no drift possible. |
| **Delta side-shard** (natural incremental design: new docs → small shard 9, federation already merges K shards; fold in at next rebuild) | Composes cleanly: the delta shard is small enough to be fully cache-resident, so its ordering is irrelevant; main shards keep their locality untouched. **This is the recommended incremental route.** |
| **In-place append** (hypothetical, engine-blocked) | With a *global* order (pack-walk): new docs append at the tail, unclustered until next re-convert — locality degrades by the appended fraction, never below today's baseline. With a *per-doc key* order (home-component or meta section‖year): the key is computable at ingest from the doc alone, so a future append path could bisect into the right region — this option value is why the selection rule pays up to +0.03 for an append-friendly key. |
| **E8 dv-v2 re-conversion** (queued, Q1 Stage 1–2: all 8 shards re-encoded for per-doc scale) | **Ride the same pass**: permute + re-encode in one walk so the corpus is only rewritten once. The converter takes `perm` as an input file precisely so ordering derivation (Python) is decoupled from application (Rust) and can prepend any conversion. |

Module-by-module “what would a new doc need”:
- forward files: append record (any route) — E5 adds only *where* it should go.
- posting lists/summaries: full rebuild regardless (SEISMIC static structures).
- doc-mapping: append row aligned with forward — same as today.
- meta.sqlite: already global + shard-independent; unaffected by E5.
- perm derivation: recomputed per rebuild; `meta_section_year`/`home_component`
  keys additionally valid for single docs at ingest time.

## 4. Rollout (Rule Zero: never touch served artifacts)

1. Converter + cargo parity test on a synthetic index (fork).
2. Shard1 f16 + dv reordered into NEW dirs (`*.e5.mmap`), gates §2.3.
3. On pass: remaining shards (background, ~disk +1 shard transient; 550 GB
   free measured 2026-07-09), new manifest JSON alongside the C2.5/dv ones,
   flip via `SFU_SEISMIC_SHARD_MANIFEST` (one-env rollback, same as the
   qdrant→seismic promotion pattern).
4. Doc updates same-commit: this doc §1/§5 results, 06 ledger, 09 §3.3/§3.4,
   12 Q-queue + decision ledger; THIN_CLIENT_SWAP if the served manifest flips.

## 5. Results ledger (filled as measured — no numbers, not done)

- 2026-07-09 Q6: GO (see header).
- 2026-07-09 Q6b: `block_walk_canonical` chosen (0.3927 worst-shard; §1
  table + verdict; `q6b_order_sweep_20260709.json`).
- 2026-07-09 Q6c: bespoke meta-DB orders REFUTED (0.9988 / 0.7675 — the
  baseline is already section-ordered; §1 verdict);
  `q6c_meta_order_sim_20260709.json`.
- 2026-07-09 converter: IMPLEMENTED + synthetic parity green (600 docs,
  both layouts, tie-aware contract §2.3; fork a0c17d4).
- Perm derivation: `scripts/seismic_testbed/e5_derive_order.py`
  (block_walk_canonical only; cross-checks the derived perm reproduces the
  sim ratio before it may feed the converter). shard1 perm cross-checked
  0.3764 = its sim cell.
- **2026-07-09 shard1 REAL-SHARD GATES — E5_ALL_GATES_PASS.** Converted
  `global_shard1of8.dotvbyte.mmap` → `.dotvbyte.e5.mmap` (127 s: forward
  76 s + 40.4M packs rewritten 42 s; 2001 records byte-verified;
  doc-mapping permuted). Gates (`e5_shard_gates.py`, n=100, k'=200, hf=0.8,
  `SFU_SEISMIC_PREFLOOR=2`, `posix_fadvise(DONTNEED)` cold eviction, 3
  alternating reps — deterministic majflt every rep):

  | Gate | Bar | Measured | Verdict |
  |---|---|---|---|
  | parity | hard==0 | hard 0, tie-swaps 0 | ✅ bit-identical |
  | pages (cold majflt) | ≤0.60 | **0.5317** (37,760 vs 71,024) | ✅ −47% faults |
  | latency (warm p50) | ≤1.05 | **0.8945** | ✅ 1.12× faster |
  | (cold p50, informational) | — | **0.6842** (≈59 vs 87 ms) | 1.46× faster |

  Result `data/eval_results/e5_shard_gates_20260709_0917.json`. **Measured
  majflt 0.53 vs the sim's 0.376–0.400:** the sim modeled f16 (2 forward
  files, 2 pages/candidate); this is the single-file dv geometry under
  `PREFLOOR=2` (posting-list + doc-mapping + forward-offsets floors
  stripped symmetrically), so the residual is `forward_data.bin` faults
  only — still a decisive clear of the 0.60 bar, and the FIRST real cold
  win on a 150M-scale shard. First-run methodology note: `release_pages()`
  alone read majflt 0 (freshly-converted pages sat warm in the page cache);
  `posix_fadvise(DONTNEED)` after it is REQUIRED to force real disk faults
  (fix committed; the confound guard reports `E5_CACHE_CONFOUNDED` if an
  arm ever reads 0 again).
- **2026-07-09 shard2 gates — E5_ALL_GATES_PASS (2nd worst-case shard).**
  parity 0 hard / 0 tie-swaps; cold majflt **0.5401** (38,334 vs 70,977);
  cold p50 **0.6614** (~49 vs ~74 ms, 1.51× faster); warm p50 **0.9168**.
  Near-identical to shard1 → the win is shard-independent (structural block
  co-access, as Q6b predicted). `e5_shard_gates_20260709_2115.json`.
- **2026-07-09 8-shard ROLLOUT + SERVED.** All 8 dv shards converted
  (`e5_rollout.sh`; forward reorder + 40.3–40.4M packs each remapped);
  parity spot-check 25 queries/shard = 0 hard, 0 tie-swaps on all 8
  (`e5_validate_and_manifest.py`, `_e5_validate.log`). e5 served manifest
  written + `retriever.py` default flipped to it (one-env rollback to the
  dv manifest; a set `SFU_SEISMIC_SHARD_MANIFEST` still wins). **Served
  federated A/B (dv manifest vs e5 manifest, 5 queries top-10): exact-order
  identical, overlap@10 1.00** — the reorder is invisible to results, only
  cold latency moved. Full 8-shard e5 backend loads 150,413,098 docs in
  3.1 s, returns real OpenAlex ids. Converter surfaced one portability bug
  fixed mid-rollout: `posting_lists.bin` may end on a sub-8-byte tail
  (shard5), so the perm-walk views the 8-aligned prefix (commit in log).
- **2026-07-09 FULL-FEDERATED 150M COLD A/B — E5 CONFIRMED AT SCALE.** The
  gap this design doc left open (per-shard win vs federated end-to-end) is
  closed, measured in-container (the `HOST_PROMPT_E5_FULLCORPUS_COLD.md`
  protocol adapted: `drop_caches` denied → full-inventory
  `posix_fadvise(DONTNEED)`; verified fresh-process mmaps on 9p re-fault
  cold regardless of Linux page cache, so every bench invocation's pass 0
  is naturally Linux-cold). 8-shard parallel federation, 40 q × 3 passes,
  dv/e5 alternating × 2 reps, all cells VmSwap 0.0 + warm ≪ cold (gate
  clean): **federated cold p50 dv 4960/4838 ms vs e5 2687/2891 ms →
  median ratio 0.569 (1.76× faster)**, cold traverse ratio ~0.55 ≈ the
  per-shard majflt 0.53–0.54 — the layout win carries fully through
  federation; warm neutral (80–110 ms both arms). Pre-registered ≤0.80
  bar decisively cleared; the "federation fan-out masks the win" null is
  refuted. **Secondary finding:** the sequential-e5 cell's cold p50
  (**2159 ms**) beat parallel-e5 (2687 ms) — 8-way parallel cold faulting
  contends on the 9p channel — while bounding VmRSS peak at **1.34 GB**
  (vs 25.2 GB parallel); cold-sensitive RAM-constrained deploys should
  prefer sequential federation. Caveat: Linux-cold over 9p/drvfs (Windows
  file cache not evicted, symmetric across arms) — the paired ratio is
  the verdict; the host runbook stays available for a true-disk-cold
  absolute number. Results
  `data/eval_results/e5_fullcorpus_cold_container_{dv,e5}_rep{1,2}.json`
  + `…_e5_sequential.json`; findings row in doc 06.
