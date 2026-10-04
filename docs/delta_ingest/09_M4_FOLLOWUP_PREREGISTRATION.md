# 09 — Pre-registration: M4 follow-up (read amplification levers) and the promotion rule for `SFU_DELTA_ROOT`

**Status:** ACTIVE

**PRE-REGISTERED 2026-10-01, NOTHING RUN.** FROZEN 2026-10-01 at the commit
that adds this file (parent `c6a9d4de`; `git log --diff-filter=A --format=%H --
docs/delta_ingest/09_M4_FOLLOWUP_PREREGISTRATION.md` prints it). Every bar
below is numeric and was written before any number for it exists. A failed
bar is recorded as FAIL and never re-cut; a bar may only be clarified in a
dated addendum at the end, written BEFORE the run it affects, and never
loosened. Written by item P of the 2026-10-01 dispatch
(`04_HANDOFF_2026-09-29.md` §"Dispatched work items (2026-10-01)"); documents
only — no index was loaded and nothing was measured to write it.

## 0. Why this exists (measured inputs, cited)

- **M4 FAIL** (`03_SPIKE_PLAN.md` M4 row; `data/eval_results/delta_ingest_M4_20260929.json`;
  `spike/delta_ingest/M4_M5_FINDINGS.md`; measured 2026-09-29 21:51–23:19Z,
  harness `scripts/experiments/eval_delta_ingest_m4_read_amp.py`, code
  `ef48050d`): `search_rrf(q, top_k=50)` p50 n0 2306.8 / n1 2340.5 / n4
  2387.1 / n8 2535.9 ms; primary OLS slope of pooled arm p50 over N =
  **27.7 ms/gen** (bootstrap CI 14.8–34.1); paired per-query median slope
  **14.8 ms/gen** (CI 13.0–16.9). Bar ≤ +8 ms/gen.
- **Where it goes** (OLS of per-arm means, ms/gen, total 23.5; per-query
  median slope in brackets): SEISMIC fan-out incl. delta shards 11.0 [7.1];
  BM25F parse/merge/masks outside the section searches 5.2 [1.1]; delta
  abstract-store probes 4.8 [4.5]; delta tantivy sections 1.5 [1.3]; base
  sections 1.3 [0.2] (noise); delta meta probes 0.04. The slowest base shard
  barely moves (p50 87 → 96 ms); "traverse minus slowest shard" grows 71 →
  134 ms mean from n0 to n8.
- **Why per generation is expensive** (verified in code and on disk
  2026-10-01, not measured): `build_generation` (`spike/delta_ingest/generation.py`
  ~131–141) writes one tantivy section + one `abstracts.sqlite` per
  `<base>__<era>` the generation's docs fall into (`DocRecord.section()`,
  `records.py:73`). On the M4 roots that is **10 sections / 10 abstract
  stores for `root_n1`, 38 for `root_n4`, 72 for `root_n8`** (counted
  2026-10-01). `_bm25f_leg` (`src/lib/thinclient/retriever.py` ~985–1027)
  calls `parse_query` twice per section per query; `fetch_abstracts`
  (~1427–1440) probes every store in turn for every still-missing id, so a
  base id with no local base abstract (remote fetch stubbed in M4) probes
  every delta store; the parallel SEISMIC backend submits one pool task per
  shard (`sharded_seismic_backend.py` `search_encoded`).
- **M4 compaction half** (bar: compacted p50 within 5% of n1) is being
  measured by item M of the same dispatch right now; its result is unknown
  to this document. §5 states what applies for each outcome.

## 1. Fixed inputs (every run below unless a run says otherwise)

- **Corpus (b)** = the 160,347 OpenAlex works of
  `updated_date=2026-09-15/part_0001` absent from the base (`WORK/corpus_b.json`,
  WORK = `/home/vscode/work/inplace_update/m4/`), split evenly in ledger
  rowid order exactly as M4 (`split_even`). Existing roots, reused
  read-only: `root_n1`, `root_n4`, `root_n8`, `root_n4c`, `root_n8c`
  (per-base-section layout). New roots go beside them (§3).
- **Queries:** the 120 natural topics of
  `data/eval_results/dense_ablation_qrels_20260817.json`, as M4 (pairing with
  M4 needs the same set); `retriever.search_rrf(q, top_k=50)`, remote
  abstracts stubbed to `{}`, serving flags as in M4.
- **Federation:** parallel only (the served mode). Sequential: NOT in scope
  (recorded as not measured, as in M4).
- **Process design = M4 REVISION 2, unchanged:** one process per run holds one
  `ThinClientRetriever` per arm, each loaded with its own env; a separate
  priming retriever configured like n0 takes the discarded prime call; 1
  warm-up pass + 2 measured passes; per-query shuffled arm order (seed
  recorded); quiet check before every 10th query; health asserted before the
  first timed query (SPLADE encoder non-empty, backend class and shard count
  = 8 + live generations with none missing, delta generations as expected,
  cross-encoder and embedding model loaded) and log-scanned after (no
  ENOMEM/fallback signature). A degraded arm's numbers are not used.
- **Lock:** every latency run holds `/tmp/sfu_latency_measure.lock`
  EXCLUSIVELY for its whole duration on an otherwise idle host (no other
  agent's index load, build or GPU job). `SFU_SEISMIC_STAGE_DIR=""` and
  `SFU_META_STAGE_DIR=""` in every process (base manifest = the frozen copy
  `WORK/base_manifest.json`, as M4). Imports from the local venv mirror
  `/home/vscode/work/venv_local` and models from `/home/vscode/work/models_local/`
  (O12 workaround), with the health assertion above.
- **Memory bound:** ≤ 8 retrievers per process (M4 ran 5 + prime); the run
  aborts (not a result) if MemAvailable < 6 GB or the process `VmSwap` grows
  by > 2 GB.
- **Record per run:** `git rev-parse HEAD`, the measured `src/` snapshot
  (`git archive <commit> src`, as M4), host samples, arm order seeds.
- **Results:** `data/eval_results/delta_ingest_M4F_<YYYYMMDD>.json` (one key
  per run: `parity`, `R1`, `R2`, `R3`); findings
  `spike/delta_ingest/M4F_FINDINGS.md`.

### 1.1 Statistics (fixed now; paired analysis is mandatory)

End-to-end `search_rrf` on this host takes ~2.3–2.5 s per query and its
pooled p50 moved with a bootstrap CI 19 ms wide in M4, so a bar at the
8 ms scale is read on PAIRED per-query statistics; the pooled statistic of
the original M4 bar is kept beside it for continuity.

- `t(a, q, p)` = wall ms of arm a on topic q in measured pass p.
- **Paired slope** of an arm family {N ∈ set}: for each (p, q), the OLS
  slope of t over N; report the median over (p, q) and a bootstrap 95% CI
  (resample topics, 2,000 resamples, seed 20261001).
- **Paired difference** Δ(a, b) = median over (p, q) of t(a) − t(b), same
  bootstrap.
- **Pooled slope** = OLS of the arms' pooled p50 over N (the M4 primary).
- p95 per arm recorded, not gated.
- **Leg attribution** as M4 (`_leg_parts`, `_Timed` proxies): recorded per
  arm, not gated.

## 2. Levers (hypothesis, code, parity)

Every lever is either a different on-disk layout of the delta generations
(built by the spike, no serving change) or a serving change behind a NEW env
gate that is **default OFF** and must be a no-op when unset. A serving lever
enters the latency runs only after its parity check (§4 run P) passes.

| # | Lever | Hypothesis (*est.* until R1/R2 run) | What it touches per engine | Code that must be written first (scoped) |
|---|---|---|---|---|
| **L1** | **Compaction cadence:** never serve more than `G_max` live generations; when a freeze would make it `G_max + 1`, compact ALL live generations into one (policy `compact_all`), candidates `G_max ∈ {1, 4, 8}`. Today `auto_compact_plan` (`generation.py:302`) merges only above 8, tiered | Tax is bounded by the worst served state, `G_max` generations; at `G_max = 1` the steady-state tax is the one-generation fixed cost (M4: n1 − n0 pooled p50 +33.7 ms, paired unmeasured) | All legs: fewer sections, stores, meta DBs, SEISMIC shards. Ingest: compaction CPU (M4 roots: 126.4 s for 8 → 1 and 145.9 s for 4 → 1 at 160,347 docs, `WORK/compact_n{8,4}.json`, 2026-09-29, host not quiet); result-cache key rotates on every compaction publish (R1); M5 reload per publish | `auto_compact_plan(policy="compact_all", max_gens=G_max)` in `generation.py`; a `--max-live-gens` dial in `profiles.py`. No serving change |
| **L2** | **Fewer stores per generation:** layout `per_era` = 2 sections per generation (`delta__recent`, `delta__archive`) or `single` = 1 (`delta`), instead of one per `<base>__<era>` (10 on corpus (b)) | Cuts the per-generation BM25F parse+search+merge work (5.2 + 1.5 ms/gen by means) and abstract stores (4.8) by up to 5× (`per_era`) or 10× (`single`) | **tantivy:** one section's IDF now spans all subjects of the generation → BM25F scores of delta docs change (T1, `02_DESIGN.md` §3) → M3 must be re-run on this layout (§6 P2). `per_era` keeps `_era_skip` (suffix rule, `retriever.py` ~1508); `single` is never era-skipped (year filter inside tantivy still applies; cost only). **Sidecar:** fewer, larger stores — M8's "likelier lever" (`03_SPIKE_PLAN.md` M8 row); dictionaries trained per store. **meta.sqlite:** unchanged (one per generation already). **SEISMIC:** unchanged (one shard per generation). **Packer/manifest.json:** delta sections are never packed; unchanged. **Personas:** the BM25F leg searches all sections; no persona scoping by section exists in `_bm25f_leg` (verified 2026-10-01) | `layout` parameter of `build_generation` (`DocRecord.section()` override: `per_base_section` default, `per_era`, `single`), a profile dial, and `--layout` on the M4 harness `build`/`compact` subcommands; `--reuse-seismic-from root_nN` so the new roots copy the identical SEISMIC generation dirs (same docs per generation; the harness asserts identical doc-id sets) instead of rebuilding them |
| **L3** | **Routed abstract probes:** `fetch_abstracts` probes delta stores only for ids the delta layer owns, and only the owning `(generation, section)` store | Removes most of the 4.8 ms/gen abstract-probe term (every unowned id probes 0 delta stores instead of all) | **Abstract sidecar** read path only; base stores untouched. Ownership from the delta meta rows (`meta_rows` already fetches them; the `section` column exists) plus `superseded`. **Hydration / CE rerank / `hydrate_scope`:** same texts by construction (parity check) | `DeltaLayer.abstract_owner(ids) -> {id: (gen, section)}` in `delta_layer.py`; routed loop in `retriever.fetch_abstracts`; gate `SFU_DELTA_ABS_ROUTE` (default OFF) recorded in `docs/ENV_GATES.md` + invariant in `docs/CODE_INVARIANTS.md` in the same commit; the gate must be read per retriever instance at `_load` (in-process arms) |
| **L4** | **Parse once per query:** `bm25f_query_text` is parsed once per distinct schema and the two `Query` objects reused across sections, instead of two `parse_query` calls per section | Cuts the parse share of the 5.2 ms/gen "parse/merge/masks" term; also lowers n0 (10 base sections) | **tantivy** only. Premise UNVERIFIED: that a `Query` parsed by one `Index` is valid on another with an identical schema in tantivy-py. A unit test proves or kills it before anything else | Unit test `scripts/tests/test_bm25f_parse_once.py` (identical hits on two indexes sharing a schema); `_bm25f_leg` change; gate `SFU_BM25F_PARSE_ONCE` (default OFF), ENV_GATES + CODE_INVARIANTS in the same commit |
| **L5** | **Grouped delta shards in the SEISMIC federation:** all delta-generation shards are searched serially inside ONE pool task; base shards keep one task each | The fan-out overhead (traverse minus slowest shard, 71 → 134 ms n0 → n8) comes from more tasks and threads; one task for all small delta shards removes most of the 11.0 ms/gen. Risk: the delta group becomes the slowest task if Σ delta traverse > slowest base shard (p50 87–96 ms, M4) | **SEISMIC** federation only; `_merge_topk` and per-shard results unchanged (order-independent merge), so the SPLADE leg must be byte-identical (parity). **Livedocs** `_shard_result_filter` sees the same per-shard list. **S7 fault boundary:** one broken delta shard now fails its group task; with `SFU_SEISMIC_SHARD_FAULT_BOUNDARY=1` the group must degrade per shard (test) | Grouping in `sharded_seismic_backend.py` keyed on the manifest records' `delta_generation`; gate `SFU_SEISMIC_DELTA_GROUP` (default OFF), ENV_GATES + CODE_INVARIANTS; a unit test that a raising delta shard inside the group is isolated under the fault boundary |

Not a lever here: SEISMIC per-shard `k′` for small shards (a recall
question, not a latency-parity one; would need M2's recall bar again),
the Rust livedocs skip (O10; livedocs is off in all M4 roots), overlay-scored
updates (`08_…` shortlist #1; changes what enters a generation, not the
per-generation cost — its own pre-registration).

**The adopted stack X** (fixed now, applied mechanically): layout `single` if
its M3 re-check passes (§6 P2), else `per_era` if its re-check passes, else
`per_base_section`; plus every serving lever L3–L5 whose parity check passed.
Arms named `x…` below use stack X. Arm `n0x` = gate off with every lever of
X that also acts on the base (L4 only) — the reference for X's slope, so a
lever that speeds the base too is not credited to the delta layer.

## 3. Roots to build (no lock needed; light; `nice -n 19`, ≤ 4 cores)

From corpus (b) with the same split as M4, SEISMIC dirs copied from the
matching `root_nN` generation (doc-id sets asserted identical), no GPU:
`root_e1`, `root_e4`, `root_e8` (`per_era`), `root_s1`, `root_s4`, `root_s8`
(`single`); compacted copies `root_e8c`, `root_s8c` via the harness
`compact` path (all 8 → 1, so the compacted generation is a fresh build of
the same 160,347 records, SEISMIC included). *est.* section build at ~375
docs/s/worker (`02_DESIGN.md` §2): ~7 min per root on one worker, ~45 min
for all eight; compactions ~2.5 min each (M4 roots, above) — total *est.*
≤ 1.5 h, disk *est.* ≤ 12 GB (M4 roots: 1.1–2.1 GB each).

## 4. Runs, arms, bars

### Run P — lever parity (no latency; may run under a SHARED lock after the exclusive holder finishes; timings invalid by declaration)

One process, 120 topics, 1 pass, `root_n8` (72 sections, the hardest case)
and `root_n1`. For each serving lever, its gate OFF vs ON on the same
retriever class:

| Lever | Compared | PASS iff |
|---|---|---|
| L3 | `fetch_abstracts(ids)` dict for every id hydrated by `search_rrf` on the 120 topics | identical keys and byte-identical texts, 120/120 topics |
| L4 | `_bm25f_leg(q, 100, f)` list, with `f` = None and with a year-range filter (2015–2026) | identical ids, order and float scores, 120/120 on both |
| L5 | `_splade_leg_seismic` result list | identical ids, order and float scores, 120/120 |
| all | `search_rrf` fused list and final top-10 with every new gate UNSET vs the code before the levers (`git archive` of the parent commit) | byte-identical 120/120 (the M1 property for the new gates) |

A lever whose parity FAILS is DROPPED from stack X (recorded with the
first differing topic). Runtime *est.* ≤ 40 min.

### Run R1 — PRIMARY (exclusive lock, quiet host)

Arms (8 retrievers incl. prime): `n0`, `n8` (M4 replication anchor),
`n0x`, `x1`, `x4`, `x8`, `x8c` (stack X roots; `x8c` = compacted layout
root). Runtime *est.* (7 × 360 + 240 calls) × ~3.1 s/call (M4: 1,680 calls in
88 min) ≈ **2.4 h**.

| Bar | Metric | Threshold (frozen) | Verdict |
|---|---|---|---|
| **F-SLOPE** (tied to the M4 bar: +8 ms p50 per live generation) | paired slope over arms {n0x, x1, x4, x8} (N = 0, 1, 4, 8) | PASS iff the bootstrap CI upper bound of the paired median slope ≤ **8.0 ms/gen** AND the pooled slope point estimate ≤ **8.0 ms/gen**. PARTIAL iff the paired CI upper bound ≤ 8.0 but the pooled point > 8.0 (one confirmatory re-run of R1 with 4 measured passes is then pre-authorised; its verdict replaces PARTIAL by PASS/FAIL with the same rule). FAIL iff the paired median point > 8.0, or neither of the above | PASS / PARTIAL / FAIL |
| **F-CAD** (L1; tied to the same bar: at most 8 ms per generation served) | for each `G_max ∈ {1, 4, 8}`: Δ(x_{G_max}, n0x) | `G_max` PASSES iff the bootstrap CI upper bound of Δ ≤ **8.0 × G_max ms** AND pooled p50(x_{G_max}) − p50(n0x) ≤ 8.0 × G_max ms. The cadence lever PASSES at the smallest passing `G_max` | per `G_max` |
| **F-COMP** (tied to the M4 compaction bar: within 5% of n1) | x8c vs x1 | PASS iff \|p50(x8c)/p50(x1) − 1\| ≤ **0.05** (the M4 rule) AND the bootstrap CI of Δ(x8c, x1) lies within **[−8.0, +8.0] ms** | PASS / FAIL |
| **REPL** (not a bar; integrity check) | Δ(n8, n0) vs M4's paired n8 − n0 median +123 ms (CI 112–137) | recorded; a value outside 60–250 ms flags the run's host conditions for the coordinator, and R1 is repeated once before any verdict is read | flag |

### Run R2 — attribution at N = 8 (exclusive lock; recorded, no bar)

Arms: `n0`, `n8`, `n8+L3`, `n8+L4` (with `n0+L4` as its own reference),
`n8+L5`, `e8`, `s8` (8 retrievers incl. prime, ≈ 2.4 h *est.*). Reported:
Δ(arm, n8) per lever with CI and the leg attribution. Use: explains R1;
drops from the default any lever whose paired gain at N = 8 is > −1.0 ms
(CI includes 0), so no unmeasured lever ships ON. Runs only after R1, or
instead of R1 if R1 cannot start (then no F-bar is read).

### Run R3 — only if F-COMP FAILS on stack X (exclusive lock)

Size-matched diagnosis of compaction residue: arms `x1` (fresh 160,347-doc
generation) and `x8c` (compacted 160,347-doc generation) plus `n1`, `n8c`;
leg attribution per arm. Recorded, no bar; it cannot overturn F-COMP or
item M's verdict.

## 5. What applies for each outcome of item M (M4 compaction half, running 2026-10-01)

Item M measures `n1, n8, n4c, n8c` on the per-base-section layout with the
M4 rule \|p50(n8c)/p50(n1) − 1\| ≤ 0.05.

- **M = PASS:** compaction restores the one-generation latency on the
  current layout. L1 stays in R1 as registered. F-COMP on stack X is still
  run (a layout change could change it) but the cadence branch of the
  promotion rule (§6) may also cite item M's PASS when stack X's layout is
  `per_base_section`.
- **M = FAIL:** compaction leaves residue on the current layout. The cadence
  branch of §6 then needs F-COMP PASS on a stack-X layout DIFFERENT from
  `per_base_section` (a re-run of the same arms on the same layout is not
  allowed — no re-rolling a failed bar); if stack X's layout is
  `per_base_section`, the cadence branch is closed and only F-SLOPE can
  promote. R3 runs.
- **M = NOT RUN / INVALID** (lock lost, degraded arm, host not quiet): treated
  as FAIL for planning; F-COMP on stack X decides by itself.

## 6. Promotion rule — when `SFU_DELTA_ROOT` becomes ELIGIBLE

"Eligible" means an operator may turn the gate on for a deployment and the
docs may say so; the code default stays OFF (an owner decision, and see
`10_FOLDIN_TRIGGER_PREREGISTRATION.md` for unbounded growth without
fold-in). Eligible iff ALL of:

- **P1 — latency (one of):**
  (a) F-SLOPE PASS on stack X; or
  (b) F-CAD PASS at some `G_max ∈ {1, 4}` AND F-COMP PASS on stack X
  (or item M PASS with stack X layout = `per_base_section`) AND the
  compaction keeps up: measured compaction wall per merge (R1 build logs,
  recorded under a quiet host or flagged) ≤ **25%** of the freeze interval
  at the deployment profile's freeze size and the measured churn
  (`desktop_gpu`: freeze 500k docs, *est.* 701,538 touched docs/day across
  8 shards as coded → a freeze every *est.* ~17 h, so compaction ≤ ~4.3 h;
  derivation in `10_…` §2). `G_max = 8` passing alone does not satisfy P1
  (it is the status quo cap of `auto_compact_plan`).
- **P2 — quality on stack X's layout** (only if the layout differs from
  `per_base_section`): M3 re-run on a corpus (a) fixture built with that
  layout (`eval_delta_ingest_m3_bm25f_drift.py`, fixture build with
  `--layout`): median rank change **0** AND displaced base docs **≤ 5%** of
  fused top-10 slots (the M3 bars, unchanged), N_A ≥ 600 titles (no partial
  pass); M2's overlap@10 vs exact ≥ **0.99** and mask leak **0** (the SEISMIC
  shard is unchanged by L2, so the recall ratio is not re-run).
- **P3 — gate-off parity on the lever code:** M1 on 2 passes, current code
  with every new gate unset: fused + final top-10 byte-identical **120/120**
  on each pass (item O of 2026-10-01 measures this for the pre-lever code;
  the lever commits need their own run).
- **P4 — the standing bars:** M1, M2, M3 PASS as recorded in `03_SPIKE_PLAN.md`
  (M2/M3 at partial N stand as recorded; this rule does not upgrade them).

If P1 fails both ways, the gate stays OFF and the track's next options are
recorded, not run: overlay-scored updates (`08_…` #1, fewer docs into
generations), fold-in at a high cadence (`10_…`, fewer live generations
because folded docs leave the delta), or accepting a measured tax by owner
decision.

## 7. Kill criteria

- A serving lever is KILLED (code stays behind its OFF gate, removed in the
  next cleanup) if its parity check fails, or if R2 shows its paired gain at
  N = 8 is > −1.0 ms.
- L2 `single`/`per_era` is KILLED if its M3 re-check fails (P2); the
  layout falls back as defined in §2.
- L1 is KILLED as a promotion path if F-CAD fails at `G_max ∈ {1, 4}` or
  F-COMP fails on every layout that ran.
- The whole follow-up is recorded CLOSED MEASURED (and the gate stays OFF
  pending a new design) if F-SLOPE FAILS AND the cadence branch is closed,
  after R1 (and its pre-authorised confirmatory re-run when PARTIAL).

## 8. Runtime and order (*est.*)

1. Code for L1–L5 + unit tests + ENV_GATES/CODE_INVARIANTS rows (no lock):
   *est.* 1 working day. 2. Roots (§3): ≤ 1.5 h, light. 3. Run P: ≤ 40 min
   (shared lock allowed). 4. P2 M3 re-check on the new layout: fixture build
   *est.* ~30 min + M3 Part A/B *est.* 3–4 h (M3 ran > 1 h for 350 titles on
   a loaded host). 5. R1: ≈ 2.4 h exclusive. 6. R2: ≈ 2.4 h exclusive.
   7. R3 if needed: ≈ 1.3 h. 8. P3: ≈ 1 h. Latency runs never overlap each
   other or any other agent's heavy job.

## 9. Engine-interaction summary (every served engine)

| Engine | L1 cadence | L2 layout | L3 abs route | L4 parse once | L5 delta group |
|---|---|---|---|---|---|
| tantivy BM25F | fewer delta sections | 1–2 sections/gen; IDF per gen spans subjects (T1 → P2) | — | parse 2× per query instead of 2× per section | — |
| SEISMIC | fewer delta shards | unchanged | — | — | one task for all delta shards; merge unchanged |
| meta.sqlite (base + per-gen) | fewer per-gen DBs | unchanged | ownership read from delta meta rows already fetched | — | — |
| Abstract sidecars | fewer stores | 1–2 stores/gen (M8 lever) | probes only owned store | — | — |
| Livedocs / masks | masks rewritten on each compaction publish | unchanged | `superseded` used for ownership | unchanged filter | per-shard filter sees the same lists |
| Dense leg (OFF) | — | — | — | — | — |
| RRF fusion | — | ranks of delta docs may move (P2) | — | — | — |
| CE rerank / `hydrate_scope` | — | — | same texts (parity) | — | — |
| Result cache | key rotates per compaction publish (R1 trade-off) | — | — | — | — |
| Packer / `manifest.json` / personas | — | delta sections never packed | — | — | — |
| `reload()` / M5 | one reload per compaction publish | — | — | — | — |

Source-agnostic: nothing here depends on the source; levers act on
generations, whatever adapter filled them. Laptop → server: L1's `G_max`
and the layout are profile dials; the levers cost no GPU.
