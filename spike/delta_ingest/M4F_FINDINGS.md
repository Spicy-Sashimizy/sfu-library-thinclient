# M4F findings: 09 M4 follow-up (serving levers L3–L5, runs P / R1 / R2 / R3)

**Status:** ACTIVE

Agent SERVE, third-wave dispatch 2026-10-01. Spec: the FROZEN
pre-registration `docs/delta_ingest/09_M4_FOLLOWUP_PREREGISTRATION.md`
(bars never re-cut here). Harness `scripts/experiments/eval_delta_ingest_m4f.py`
(sibling of the M4 harness, which it imports unchanged). Results:
`data/eval_results/delta_ingest_M4F_20261001.json` (one key per run:
`parity`, `R1`, `R2`, `R3`). Run dirs: `/home/vscode/work/delta_ingest/serve/`.

## Lever code (2026-10-01, IMPLEMENTED; latency EFFICACY UNMEASURED until R1/R2)

| Lever | Gate (default OFF, literal `1` only) | Commit | Unit test |
|---|---|---|---|
| L4 parse once per schema | `SFU_BM25F_PARSE_ONCE` (read at `_load`) | 10bc02a5 | `scripts/tests/test_bm25f_parse_once.py` |
| L3 routed abstract probes | `SFU_DELTA_ABS_ROUTE` (read at `_load`) | fbde17bb | `scripts/tests/test_delta_abs_route.py` |
| L5 grouped delta shards | `SFU_SEISMIC_DELTA_GROUP` (read at `ParallelSeismicBackend.from_manifest`) | 930b5a71 | `scripts/tests/test_seismic_delta_group.py` |

- **L4 premise: CONFIRMED (unit test, 2026-10-01).** A tantivy-py 0.26 `Query`
  parsed by one `SectionBuilder` index returns identical hits (ids, order,
  float scores) on a second index with an equal schema and different
  documents: 9 queries × {no filter, year 2015–2026}, 18/18. `tantivy.Schema`
  supports `==` but is unhashable (TypeError), so reuse is keyed by schema
  equality, not a dict.
- **L3 behaviour difference by design:** for an id held by two generations,
  routed returns the newest copy's abstract, unrouted the oldest generation's
  (store-order first hit) — shown by the unit test. On the M4 roots every
  corpus (b) id is in exactly one generation, so Run P can be identical.
  Pre-existing and unchanged both ways: a superseded BASE id hydrates the
  stale base abstract (base stores are probed first) while `_meta_rows`
  serves the delta title (observation, not fixed here).
- **L5:** fault boundary isolates a raising delta shard inside the group (unit
  test with fake shards); worst-case group time under the boundary is
  #delta shards × per-shard timeout (recorded in `docs/CODE_INVARIANTS.md`).
- Rows: `docs/ENV_GATES.md` (3 gates), `docs/CODE_INVARIANTS.md` §"M4 follow-up
  serving levers".

## Pre-run note (written 2026-10-01 ~15:45Z, before any 09 measurement)

**Run P (09 §4), shared lock, parallel federation, 1 pass, 120 topics, roots
`root_n8` (72 delta sections) and `root_n1`.** Per root one OFF retriever (no
lever gate) and one ON retriever (L3+L4+L5 all set). Each lever is compared on
the only path its gate touches (verified in code: L3 only changes
`fetch_abstracts`, L4 only `_bm25f_leg`'s parsing, L5 only the parallel
fan-out), so one ON retriever stands for the three per-lever ON retrievers:
L3 `fetch_abstracts(ids)` dict for the ids the OFF retriever's `search_rrf`
hydrated (identical keys + texts); L4 `_bm25f_leg(q, 100, f)` for f = None and
year 2015–2026 (ids, order, float scores); L5 `_splade_leg_seismic(q, 50, None)`
(50 = the `top_k` `search_rrf` passes to the leg). Gate attributes asserted at
load (`_delta_abs_route`, `_bm25f_parse_once`, backend `_delta_group` = the
delta shard positions). Also recorded (not a 09 row): OFF vs ON `search_rrf`.
**"all" row:** two `rrf-dump` processes, fused top-50 + final top-10
(`tools._maybe_rerank`, as M1), every lever gate unset, roots n8 and n1: (a)
the measured HEAD snapshot, (b) the same snapshot with exactly the three lever
commits' `src/` diffs reverse-applied (`prelever-snapshot`; checked: retriever
and backend equal the pre-lever parent, delta_layer differs only by FIX's
O2 commit 2fc2cb5c, present in both arms). "Code before the levers" is
operationalised that way so another agent's concurrent `src/` commit cannot
show up as a lever effect. Verdict per lever: PASS iff 120/120 on both roots;
a FAIL drops the lever from stack X with the first differing topic.

**R1 (PRIMARY), exclusive lock.** Arms exactly 09's: n0, n8, n0x, x1, x4, x8,
x8c + a separate priming retriever = 8 retrievers. Stack X applied
mechanically from `/tmp/sfu_wave3/BUILD_P2_DONE` (layout) and Run P (levers).
1 warm-up + 2 measured passes, seed 20261001 for arm order and bootstrap.
Bars read by `bars_r1` exactly as frozen. If BUILD's P2 is not done by
2026-10-01 23:30Z: R2 instead (no F-bar read), R1 NOT RUN.

**R2 arm-count note (stated before any R2 run):** 09 lists n0, n8, n8+L3,
n8+L4, n0+L4, n8+L5, e8, s8 and "8 retrievers incl. prime", which is 9 with
n0+L4; §1 bounds a process at ≤ 8 retrievers. If R2 runs, n0+L4 is left out
(recorded NOT RUN) to keep the memory bound; Δ(n8+L4, n8) — the quantity the
R2 drop rule reads — does not need it.

## Run P — lever parity (measured 2026-10-01 16:47Z–20:27Z, shared lock, timings INVALID)

Results: `data/eval_results/delta_ingest_M4F_20261001.json` key `parity`;
rows `/home/vscode/work/delta_ingest/serve/run_p_a396eec9b143ccddf11ed80c560a0c1816f71ccc/`
(`parity.json`, `dump_lever.json`, `dump_prelever.json`, `compare_all.json`).
Script `scripts/experiments/eval_delta_ingest_m4f.py` (`parity`, `rrf-dump`,
`rrf-compare`, `summarize-parity`). Measured code: `git archive a396eec9 src`
(contains the three lever commits and FIX's O2 2fc2cb5c); pre-lever arm =
that snapshot with the `src/` diffs of 10bc02a5, fbde17bb, 930b5a71
reverse-applied (no lever gate name left in it). Interpreter
`/home/vscode/work/venv_local`, models from `/home/vscode/work/models_local`
(+ the M1 embed-v5 copy), `SFU_SEISMIC_STAGE_DIR=""`, `SFU_META_STAGE_DIR=""`,
parallel federation, 120 natural topics, 1 pass. Health OK in all three
processes (SPLADE 43 terms, CrossEncoder, embedding model, ParallelSeismicBackend
16 shards on `root_n8` / 9 on `root_n1`, gate attributes as specified per
retriever, no failure signature). Before the parity child, a 2-topic inproc
smoke test of the R harness (arms n0, n1+L3+L4+L5) passed health (not a result).

| Lever | Compared (09 §4) | root_n8 | root_n1 | Verdict |
|---|---|---|---|---|
| L3 | `fetch_abstracts(ids)` for the 11,425 ids hydrated by `search_rrf` (4 of them delta-owned) | 120/120 | 120/120 | **PASS** |
| L4 | `_bm25f_leg(q, 100, f)`, f = None | 120/120 | 120/120 | **PASS** |
| L4 | same, year 2015–2026 | 120/120 | 120/120 | **PASS** |
| L5 | `_splade_leg_seismic(q, 50, None)` | 120/120 | 120/120 | **PASS** |
| all | `search_rrf` fused top-50 + final top-10, every new gate unset, vs pre-lever code | 120/120 (fused, fused10, final10) | 120/120 | **PASS** |

Also recorded (not a 09 row): OFF vs ON (all three levers) `search_rrf`
fused list identical 120/120 on both roots.

**Stack X levers: L3 + L4 + L5** (none dropped). Caveat for L3: only 4 of
11,425 hydrated ids are delta-owned on these roots (corpus (b) is ~90%
datasets and rarely reaches the fused list), so its parity exercises the
routed path on few owned ids; the unowned-id short-cut (the latency lever)
is exercised on every call.

## L1/L2 + roots + P2 (agent BUILD, 2026-10-01)

### L1 compaction cadence and L2 layout (code, IMPLEMENTED; latency EFFICACY UNMEASURED until SERVE's R1/R2)

- **L1** (`spike/delta_ingest/generation.py` `auto_compact_plan(..., max_gens, policy)`):
  `policy="compact_all"` returns every live generation as soon as more than
  `max_gens` (= G_max) are live; the default `policy="tiered"` is the old plan,
  unchanged. Profile dials `compact_policy` (default `tiered`) and
  `max_live_gens` (default 8) in `profiles.py`; CLI `--compact-policy` /
  `--max-live-gens`; `flush` runs the compaction right after the freeze only
  under `compact_all` (`out["auto_compact"]`), `compact --auto` reads the
  profile dials. Commit 90076019.
- **L2** (`DocRecord.section(layout)` in `records.py`, `build_generation(...,
  layout=None)` → `profile.layout`): `per_base_section` (default; the original
  `<base>__<era>` names), `per_era` (`delta__recent` / `delta__archive`),
  `single` (`delta`). The meta.sqlite `section` column carries the same name
  as the store (SectionBuilder writes it), so L3's owner routing sees the
  layout's names; the ledger keeps the classification name. `generation.json`
  records `layout`. Profile dial `layout`, CLI `--layout`, `freeze_buffer` /
  `compact` pass it through. Commit 90076019.
- **SEISMIC reuse** (`build_generation(..., seismic_from=<gen dir>)`): copies
  the source generation's `seismic/` dir after asserting that the source jsonl
  id set equals the records' vector-doc id set (refuses otherwise, unit
  tested); `generation.json` `seismic.reused_from` / `reuse_ids_checked`. The
  `stages` timings in a reused generation are the SOURCE build's.
- **`_era_skip` check** (`retriever.py`, suffix rule; unit test): `delta__recent`
  / `delta__archive` are skipped exactly like base era sections for a
  year-bounded query; `delta` is never skipped (the tantivy year filter still
  applies inside it). No serving change was needed.
- **Unit tests:** `scripts/tests/test_delta_ingest_layout_cadence.py`, 12 pass
  on tmp roots (section names, build per layout incl. meta section column,
  profile default vs param, era skip, `compact_all` plan incl. G_max = 1,
  CLI end-to-end: `single` + `compact_all` + G_max 1 keeps one live generation
  over three flushes and BM25F/year filter/abstracts serve; default policy
  never compacts on flush; SEISMIC reuse copies / refuses). `test_delta_ingest.py`
  5 pass unchanged.
- **M4 harness** (`scripts/experiments/eval_delta_ingest_m4_read_amp.py`,
  commit 8e3fc6b8): `build`/`compact` take `--layout` (roots
  `root_{n,e,s}<N>[c]`), `build --reuse-seismic-from root_nN` (per generation:
  ledger doc-id set of the source generation == the chunk, then the jsonl
  check above), `--seismic-threads`.

### Roots (09 §3), built 2026-10-01 15:31–15:55Z

Under `/home/vscode/work/inplace_update/m4/` (existing `root_n*` only read).
`nice -n 19 taskset -c 8-11`, `OMP/RAYON_NUM_THREADS=4`, no lock, no GPU
(compactions rebuilt SEISMIC with 4 threads). **Host not quiet:** DRIFT's
exclusive full-shard build ran on cores 8-15 throughout (load1 4.5–9.9 at the
step starts). Logs `WORK/build_{s,e}{1,4,8}.json`, `WORK/compact_{s,e}8.json`;
code HEAD 90076019/8e3fc6b8 (generation.py identical in both for these calls).

| Root | Layout | Live gens | Sections = abstract stores | Shards in manifest | Disk | Wall |
|---|---|---|---|---|---|---|
| root_s1 | single | 1 | 1 | 9 | 1.12 GB | build 134.4 s |
| root_s4 | single | 4 | 4 | 12 | 1.34 GB | build 136.1 s (33.2/32.3/32.9/37.6) |
| root_s8 | single | 8 | 8 | 16 | 1.53 GB | build 188.9 s (21.9–24.8 per freeze) |
| root_s8c | single | 1 (g0009) | 1 | 9 | 2.23 GB* | copy 2.0 s + **compaction 161.1 s** (8 → 1) |
| root_e1 | per_era | 1 | 2 | 9 | 1.12 GB | build 186.2 s |
| root_e4 | per_era | 4 | 8 | 12 | 1.34 GB | build 191.4 s (44.6/46.6/47.9/52.3) |
| root_e8 | per_era | 8 | 16 | 16 | 1.53 GB | build 192.7 s (21.6–27.9 per freeze) |
| root_e8c | per_era | 1 (g0009) | 2 | 9 | 2.23 GB* | copy 2.1 s + **compaction 189.9 s** (8 → 1) |

\* includes the eight `*.compacted` source generations kept on disk as in
`root_n8c`; the served generation is 0.67 GB. For comparison (09 §0, M4
roots, per_base_section): 10 / 38 / 72 sections for n1 / n4 / n8; compaction
126.4 s (8 → 1, 8 SEISMIC threads, host not quiet, `WORK/compact_n8.json`).
Compaction SEISMIC stage in the new roots: build 30.5 s (s8c) / 38.5 s (e8c)
at 4 threads; the rest is the tantivy + sidecar rebuild of 160,347 records.
These are the 09 P1(b) "compaction wall per merge" inputs at 160,347 docs —
**host not quiet, 4 SEISMIC threads**.

**Load sanity check** (`/home/vscode/work/delta_ingest/BUILD/sanity_roots.py`
→ `sanity_roots.json`, 2026-10-01 15:55Z): all 8 PASS — `DeltaLayer(root)`
loads with the expected generations; every section's tantivy `num_docs` ==
its recorded docs and sums to the generation's docs (160,347 per root);
abstracts stored == docs; meta.sqlite rows == docs with section names == the
store names; every SEISMIC mmap dir opens with `len` == docs with vectors;
composed manifest 8 + N shards; for every copied generation all SEISMIC files
are byte-identical to the source `root_nN` generation (`filecmp`, 20 files each).
`/tmp/sfu_wave3/BUILD_ROOTS_DONE` touched 15:55Z.

### P2 — M3/M2 re-check on layout `single` (09 §6 P2): **PASS**; `per_era` NOT RUN

Run 2026-10-01 18:26–21:14Z by `/home/vscode/work/delta_ingest/BUILD/p2_run.sh single`
(shared lock, `nice 10`, cores 8-15, local venv mirror + local model copies;
every timing invalid by declaration). Results file (written by the
coordinator from these outputs): `data/eval_results/delta_ingest_M4F_P2_20261001.json`.
Raw outputs: `/home/vscode/work/delta_ingest/BUILD/p2_single/` (`m3_runs/`,
`m3_summary.json`, `m2/`). I re-read the raw outputs on 2026-10-01 22:20Z and
agree with the coordinator's reading on every bar.

- **Fixture:** `scripts/experiments/delta_ingest_m4f_p2_fixture.py --layout single`
  → `/home/vscode/work/delta_ingest/BUILD/corpus_a_single/` (corpus (a) read
  only): ledger backup, g0001 rebuilt from the same 50,000 stored records as
  one `delta` section, SEISMIC dir copied (50,000 ids asserted, 20/20 files
  `cmp`-identical), livedocs rebuilt with the fixture's ordinals (popcount
  50,000, superseded 50,000, deleted 0, same ordinal space id as the fixture).
  Build 43.8 s, publish 1.2 s (`build_fixture.json`).
- **M3 Part A** (BM25F leg, title-as-query, code a18d8295): **600/600 titles,
  not partial**, 0 query errors (the 2026-09-30 run had 10 tantivy syntax
  errors in 350; the O19 lower-casing landed in between), 587 present in both
  arms; **median rank change 0** (p5 0, p95 +1, min −8, max +15; same 89.8%,
  worse 9.4%, better 0.9%); delta/base-copy score ratio median 0.981; own-recall@100
  BASE 0.9783 / DELTA 0.9833; mask leak 0 (own doc and any updated id), both
  copies in one list 0, every served copy from generation 1 (600/600). **PASS.**
- **M3 Part B** (120 topics, fused `search_rrf`): **displaced 1 of 1,200 slots**
  (0.08%; the same topic and doc as on 2026-09-30, via the SPLADE leg); fused
  top-10 identical 118/120, BM25F-leg top-10 identical 119/120 (BM25F-leg
  displacement 0), final top-10 changed 2 topics with 0 displaced. **PASS.**
  Health OK in all 4 processes (delta: `delta_g0001:delta` loaded, 9 shards),
  log scan 0 signatures.
- **M2 overlap@10 vs exact** on the copied delta shard (e8 and served params):
  topics120 0.9975, diverse100 1.000, titles1000 0.9968 — **PASS**, numerically
  identical to M2 on 2026-09-30, as expected for a byte-identical shard.
- **Mask leak (SPLADE leg, M2 definition `summarise_arm`):** rows whose
  post-filter capture holds the doc in a base shard (index < 8 =
  `N_BASE_SHARDS`). The coordinator's "a shard index other than 8" is the
  same set here (9 shards, the delta shard is index 8; health asserted
  origins `[None×8, 1]`). Recount from `m2/rows_delta.jsonl`: **0 of 600**
  (600 unique ids, 600 captured, 0 empty results); the base copy was in a
  base shard's pre-filter top-k′ for 465 and the filter removed every one;
  delta copy hit@10 491/600. **PASS.** N = 600 is the M2 delta arm's
  first 600 sample ids (no N is fixed for this bar in 09 P2).
- **What P2 can and cannot show on corpus (a) — premise note.** Corpus (a)
  is 50,000 docs of ONE base section (`social_sciences__recent`). Its
  per_base_section generation already has a single section
  (`social_sciences__recent`), `per_era` also yields a single section
  (`delta__recent`, all docs ≥ 2010), and `single` yields `delta`: the same
  50,000 docs in one tantivy index in all three layouts. So the T1 concern
  09 §2 attaches to L2 ("one section's IDF now spans all subjects of the
  generation") is NOT exercised by this fixture; P2 here only confirms the
  layout plumbing (names, era skip off, masks, sidecar) changes nothing.
  Cross-check: the 340 titles common with the 2026-09-30 per_base_section
  delta arm have identical ranks 340/340 (scores differ in 99 rows; the
  code under test differs by the O19 query lower-casing, not attributed),
  and Part B delta-arm fused lists are identical 119/120. A cross-subject
  test needs corpus (b) or a multi-section corpus (a); not pre-registered,
  not run.
- **`per_era`: NOT RUN** (the 09 §2 rule adopts `single` when its re-check
  passes). Its fixture exists (`corpus_a_per_era/`, `build_fixture.json` ok)
  and would be identical in content for the reason above.
- **Adopted layout:** `single` (`/tmp/sfu_wave3/BUILD_P2_DONE`, written by the
  coordinator).

### Compaction keep-up for 09 §6 P1(b) (measured inputs + *est.*; R1 not run)

- **Measured** (`WORK/compact_s8.json`, 2026-10-01 15:39–15:41Z): `single`
  layout, 8 → 1 generations, 160,347 docs: **161.1 s wall per merge**
  (SEISMIC build stage 30.5 s at 4 threads, mmap 1.5 s, dotvbyte 5.1 s; the
  rest is reading the ledger records and the tantivy + sidecar + meta
  rebuild). `per_era` 189.9 s (`compact_e8.json`). **Host not quiet**
  (DRIFT's exclusive build on cores 8-15, load1 8.6 at start), `nice 19`,
  4 cores — an upper-side measurement for this size.
- **Reading against the 25% bar** (`desktop_gpu`: freeze 500k docs, a freeze
  every *est.* ~17 h → compaction must take ≤ *est.* ~4.3 h): at 160,347 docs
  in 161 s ≈ 1,000 docs/s, a G_max = 1 compaction (which rebuilds ALL live
  delta docs) of 500k docs is *est.* ~8.4 min, and the 4.3 h budget covers
  *est.* ~15M live delta docs by linear extrapolation, i.e. *est.* ~30 freezes
  (~3 weeks at the coded churn) before compaction alone hits 25% — unless
  fold-in (`10_…`) removes docs from the delta first. Linear scaling of the
  SEISMIC build and tantivy rebuild past 160k docs is UNMEASURED; no
  compaction larger than 160,347 docs was run. P1(b) also needs F-CAD and
  F-COMP from R1, which ABORTED (memory rule) — so P1(b) is NOT decided.

### Doc 11 — P2 on the multi-section corpus (b) roots (2026-10-04)

**Doc 11 multi-section P2 RUN 2026-10-04 01:39–05:25Z: FAIL by the frozen rule, on bar A only** (`data/eval_results/delta_ingest_P2_multisection_20261004.json`, `scripts/experiments/eval_delta_ingest_p2_multisection.py`; shared lock, timings invalid by declaration; both contrasts complete and healthy, 600 titles + 120 topics + 600 titles each; search code snapshot e3fb5ad0 for both). Layout `single` vs `per_base_section`, 1 generation / 8 generations: **A** median own-rank change in the BM25F leg overall 0 / 0, per subject 0 in four strata and **−13.5 / −1.0 in `other__recent`** (negative = the doc ranks BETTER under `single`), so the two-sided bar "median = 0 in each stratum" FAILS; the medians rest on the docs present in both arms' top-100: 217 / 210 of 600 overall and 20 / 14 in `other__recent`, 5 / 5 in `phys_eng__recent` (48 / 47 more docs enter the top-100 only under `single`, none only under `per_base_section`; 335 / 343 are in neither); own-doc raw score ratio single/per_base_section median 1.11 / 1.19. **A2 PASS** (own-recall@100 0.362 → 0.442 and 0.350 → 0.428). **B PASS** (1 / 0 of 1,200 fused top-10 slots displaced on the 120 topics). **C PASS** (122 / 128 of 6,000 slots displaced = 2.0 % / 2.1 %; own fused-rank median change 0). **D PASS** (0 duplicates, 0 wrong-origin hits). `per_era` by the same rule: does not hold either (A: −13.5 / −1.0 in the same stratum). Reading: pooling subjects raises delta docs' BM25F scores, which moves them up, not down; the bar as written does not distinguish the direction. By doc 11 §3 the adopted layout falls back to `per_base_section`, lever L2 is killed, and P1 has to be shown by R1 on the `n…` roots with L3–L5; **`SFU_DELTA_ROOT` is NOT eligible**.

### Run R3 on the fallback stack (2026-10-04 22:33–23:36Z)

**`09` Run R3 (pre-registered follow-up to an F-COMP FAIL; recorded, no bar, cannot overturn F-COMP) RUN 2026-10-04 22:33–23:36Z** on the fallback stack (layout `per_base_section` + L3, L4, L5; exclusive lock, code 9f677a21, 2 measured passes × 120 topics per arm, healthy, host swap grew 1.17 GB during the run; `data/eval_results/delta_ingest_M4F_20261001.json` key `R3_per_base_section`, `scripts/experiments/eval_delta_ingest_m4f.py`): paired median x8c − x1 **−5.5 ms** (CI −15.7 to +4.8), n8c − n1 +0.6 ms (CI −4.7 to +6.9), x1 − n1 −1.3 ms (CI −6.4 to +5.7), x8c − n8c −4.1 ms (CI −10.6 to +5.4); pooled p50 x1 2,104.8, x8c 2,109.9, n1 2,096.0, n8c 2,085.8 ms (x8c / x1 = 1.0024). Per-leg medians of the delta work are the same for a compacted and a fresh 160,347-doc generation (delta BM25F sections 3.0 vs 3.1 ms, delta SEISMIC shard 2.1 vs 2.2 ms, delta abstracts 0.1 vs 0.1 ms on the x arms); the base BM25F leg is ~1,960 ms of each ~2,100 ms query. Reading: no compaction residue is visible; every interval contains 0 and is wider than ±8 ms on one side, so F-COMP's FAIL is the interval width of this design, not a measured cost. **F-COMP stays FAIL as recorded; P1 still holds by route (a).**

| Arm | Pooled p50 (ms) | Per-pass p50 | delta BM25F sections | delta SEISMIC shards | delta abstracts | base BM25F sections |
|---|---|---|---|---|---|---|
| x1 (fresh, levers) | 2,104.8 | 2,098.3 / 2,129.7 | 3.1 | 2.2 | 0.1 | 1,963.7 |
| x8c (compacted, levers) | 2,109.9 | 2,109.9 / 2,109.7 | 3.0 | 2.1 | 0.1 | 1,962.2 |
| n1 (fresh, no levers) | 2,096.0 | 2,097.9 / 2,088.2 | 3.0 | 2.1 | 0.9 | 1,953.7 |
| n8c (compacted, no levers) | 2,085.8 | 2,112.7 / 2,080.0 | 3.0 | 1.9 | 0.9 | 1,946.1 |

Leg columns are per-query medians in ms (`legs_median_ms`). Run dir `/home/vscode/work/delta_ingest/serve/run_R3_20261004/`.
