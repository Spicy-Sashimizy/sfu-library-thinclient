# 11 — Pre-registration: P2 on a multi-section fixture (BM25F drift of the `single` layout across subjects)

**Status:** ACTIVE

**Written 2026-10-03, BEFORE any number below exists. NOTHING RUN; the
harness is not written. DESIGN ONLY, EFFICACY UNMEASURED.** Bars are frozen
at the commit that adds this file; a later change is a dated addendum, never
an edit.

## 0. Why this exists

`09_M4_FOLLOWUP_PREREGISTRATION.md` §2 attaches one quality risk to lever L2
(layout `single` = one tantivy section per generation): that section's IDF
spans every subject of the generation, so BM25F scores of delta docs change
(T1, `02_DESIGN.md` §3). §6 P2 guards it with an M3 re-run "on a corpus (a)
fixture built with that layout". That run PASSED on 2026-10-01
(`spike/delta_ingest/M4F_FINDINGS.md` §P2), but corpus (a) is 50,000 docs of
ONE base section (`social_sciences__recent`, the only section with a local
abstract sidecar), so it is one tantivy section under every layout: ranks
were identical to the `per_base_section` run on 340/340 common titles. The
PASS confirms the plumbing and does not exercise T1.

Where the promotion rule stands on 2026-10-03, by the letter of `09` §6:
P1 holds by route (a) (R1 repeat: F-SLOPE PASS, with the REPL check outside
its window on both runs), P2 PASS with the caveat above, P3 PASS, P4 PASS.
**Whether the eligibility statement waits for this document's bars is an
owner decision, not taken here.** Stack X (the stack R1 measured) uses
`single`, i.e. the layout the untested risk belongs to.

## 1. Fixture — existing roots, nothing to build

Corpus (b) (`03_SPIKE_PLAN.md` fixed inputs): 160,347 NEW works, 10
`<base>__<era>` sections, already built in three layouts by `09` §3 with the
SEISMIC generation dirs copied byte-identical between layouts
(`--reuse-seismic-from`, doc-id sets asserted). Under
`/home/vscode/work/inplace_update/m4/`:

| Arm | Root | Layout | Generations | Tantivy sections per generation |
|---|---|---|---|---|
| **N1** (reference) | `root_n1` | `per_base_section` | 1 × 160,347 | 10 |
| **S1** | `root_s1` | `single` | 1 × 160,347 | 1 (`delta`) |
| **N8** (reference) | `root_n8` | `per_base_section` | 8 × ~20,044 | 9–10 |
| **S8** | `root_s8` | `single` | 8 × ~20,044 | 1 |
| E1, E8 (recorded only) | `root_e1`, `root_e8` | `per_era` | 1, 8 | 2 |
| G0 (control) | gate off | — | 0 | — |

Section sizes (ledger of `root_s1`, read 2026-10-03): `other__recent` 91,590,
`phys_eng__recent` 45,373, `cs_math__recent` 11,754, `med_bio__recent` 5,681,
`social_sciences__recent` 4,387, `other__archive` 1,501, four more archive
sections with 4–30 docs. Limits of this fixture, stated now:

- The docs are NEW works, so there is no base copy to compare against (M3's
  delta-vs-base contrast). The contrast here is **layout vs layout on the
  same docs** (S vs N), which isolates exactly what L2 changes.
  `per_base_section` is the layout M3 passed on at full N (2026-10-02).
- The subject mix is skewed (57 % `other`, 28 % `phys_eng`); the sample in
  §2 is stratified so the small subjects, where a pooled IDF moves most,
  carry equal weight.
- Corpus (b) is ~90 % dataset-like abstracts (M8 note), and its docs reach
  no fused top-10 on the 120 topics (`delta_docs_in_top10_mean` = 0.0 on
  every arm of R1, 2026-10-03). The 120-topic part (B) is therefore a
  control; the sensitive parts are A and C, which query for the delta docs.

The harness asserts before measuring: identical live doc-id sets in N1/S1
and in N8/S8, identical SEISMIC generation files (`cmp`), the section counts
of the table, masks empty, buffer empty. Nothing is written under any root.

## 2. Measurements and frozen bars

Code under test: `git archive <HEAD at drive time> src`. Serving levers
L3–L5 unset in every arm (L2 is the only variable). One process per
contrast, arms opened in-process as in `eval_delta_ingest_m4f.py`
(`open_arm`), same health assertions; shared latency lock, **timings
invalid by declaration**. Queries run on both arms of a contrast in the
same order.

**Sample (Parts A and C):** 600 corpus (b) docs with a non-empty title:
120 from each of the five `__recent` sections, drawn with
`numpy.default_rng(20261003)` (one `permutation` per section, sections in
alphabetical order, first 120 with `title.strip() != ""` and at least 4
whitespace-separated tokens). The same 600 for every arm.

| # | Question | Metric | Bar (frozen) |
|---|---|---|---|
| **A** | Does pooling subjects into one section move a delta doc's BM25F rank? | `_bm25f_leg(title, 100, None)` (M3 Part A's entry point), rank of the doc's own id, per doc: `rank_S − rank_N` over docs present in both arms | **median = 0 overall AND in each of the 5 strata**, on BOTH contrasts (S1 vs N1, S8 vs N8) |
| **A2** | Does it lose docs from the leg? | own-recall@100 (share of the 600 whose id is in the leg's top-100) | `recall(S) ≥ recall(N) − 0.01` on both contrasts |
| **B** | Control on the 120 topics (M3 Part B's definition, layout vs layout) | `search_rrf_detailed(q, top_k=50)`; displaced = a doc in the N-arm fused top-10 absent from the S-arm fused top-10, summed over 120 topics | **≤ 60** of 1,200 slots (5 %, the M3 bar) on both contrasts |
| **C** | Does the fused result change when the query targets a delta doc? | `search_rrf_detailed(title, top_k=50)` for the 600 titles; displaced as in B; and the rank of the doc's own id in the fused list | displaced **≤ 5 %** of 6,000 slots (≤ 300) on both contrasts; own-id fused-rank median change **0** |
| **D** | Mask and plumbing integrity | any id returned twice in one leg list; any id of corpus (b) served from a section not of its generation | **0** |

PASS = A, A2, B, C, D all hold on both contrasts. Recorded without a bar:
the rank-change quantiles and better/same/worse shares per stratum; the
S/N raw-score ratio of the own doc; the same numbers for E1 vs N1 and E8 vs
N8; B and C computed on the BM25F leg's own top-10 and on the final
(reranked) top-10; B against G0 (base docs leaving the fused top-10 when
the layer is on, per layout).

N: 600 titles and 120 topics, 1 pass per arm; no partial pass (a run that
stops early is NOT READ).

## 3. What each outcome means

- **PASS:** T1 is measured for `single` on a 10-section corpus; the caveat on
  `09` P2 is discharged and the docs may cite P2 without it.
- **FAIL on S, and the same bars hold for E** (`per_era`, computed from the
  recorded E arms by the same rule): by `09` §2 the adopted layout falls back
  to `per_era`. Stack X changes, so R1's F-bars, measured on `single` roots,
  do not transfer: R1 must be re-run on the `e…` roots before P1 is cited
  for that stack.
- **FAIL on S and on E:** layout falls back to `per_base_section`; lever L2
  is KILLED (`09` §7); P1 must then be shown by R1 on the `n…` roots with
  L3–L5 (not measured: R1's x arms used `single`).
- A harness defect is fixed and the run repeated once; a model result is not
  re-run.

## 4. Harness, results, runtime

- Harness: `scripts/experiments/eval_delta_ingest_p2_multisection.py` (to be
  written; copies §2 verbatim into its header before its first run).
- Results: `data/eval_results/delta_ingest_P2_multisection_<YYYYMMDD>.json`;
  findings appended to `spike/delta_ingest/M4F_FINDINGS.md`.
- Runtime *est.* (BM25F leg ~2 s and `search_rrf` ~2.2 s per call on this
  host, 2026-10-03): A 600 × 6 arms ≈ 2 h; B 120 × 7 arms ≈ 30 min; C 600 × 6
  arms ≈ 2.2 h; total ≈ 5 h under the shared lock, or ≈ 2.5 h if the
  recorded E arms are dropped (which removes the §3 fallback reading).

## 5. Engine interaction (what the layout touches)

| Engine | `single` vs `per_base_section` | Covered by |
|---|---|---|
| tantivy BM25F | IDF and average field length computed over all subjects of a generation; era skip never applies to `delta` | A, A2, B, C |
| SEISMIC | byte-identical generation shards | asserted (`cmp`), not re-measured |
| Abstract sidecar | one store per generation, dictionaries trained per store | D (served abstracts are not compared; M8 covers size) |
| meta.sqlite, masks, RRF, rerank | unchanged | B, C on fused and final lists |

## Addendum 2026-10-04 — owner decision; harness written (NOTHING RUN)

- **Owner decision 2026-10-04:** the `SFU_DELTA_ROOT` eligibility statement
  WAITS for this document's verdict. Until it reads PASS the gate is not
  eligible, whatever `09` §6 reads by its letter.
- Harness written 2026-10-04:
  `scripts/experiments/eval_delta_ingest_p2_multisection.py` (§2 copied
  verbatim into its header; tests `scripts/tests/test_p2_multisection_harness.py`,
  7 on synthetic rows). Its header fixes the operational definitions (rank,
  absent, the pre-mask origin capture for D, where displacement is counted)
  before the first run. **IMPLEMENTED, NOT RUN.**
- **Correction 2026-10-04 01:40Z, before any measured number** (the 3-query
  smoke stopped on the harness's fixture assertion, nothing was measured on
  the 8-generation contrast): the §1 table says `root_n8` has 9–10 tantivy
  sections per generation; the real counts are 9, 10, 9, 9, 9, 9, **8**, 9
  (the archive sections with 4–30 docs are absent from some 20k slices). The
  assertion is 8–10. No bar, sample or statistic changes.
- **Harness stop/resume added 2026-10-04 03:23Z, while the 1-generation
  contrast was finishing and before the 8-generation contrast started** (no
  bar, sample or statistic involved): a measure process stops cleanly before
  its next query on SIGTERM / SIGINT or when `<rows file>.STOP` exists and
  exits 4 (verdict NOT READ); `--resume` continues from the rows already
  written for the same contrast, sample and code snapshot. Checked on a
  6-query scratch run of the 8-generation contrast: stopped by SIGTERM after
  3 Part A queries, resumed to 6 / 6 / 6 with every index once. The
  1-generation contrast ran on the harness without it (e3fb5ad0).

## Result 2026-10-04

**Doc 11 multi-section P2 RUN 2026-10-04 01:39–05:25Z: FAIL by the frozen rule, on bar A only** (`data/eval_results/delta_ingest_P2_multisection_20261004.json`, `scripts/experiments/eval_delta_ingest_p2_multisection.py`; shared lock, timings invalid by declaration; both contrasts complete and healthy, 600 titles + 120 topics + 600 titles each; search code snapshot e3fb5ad0 for both). Layout `single` vs `per_base_section`, 1 generation / 8 generations: **A** median own-rank change in the BM25F leg overall 0 / 0, per subject 0 in four strata and **−13.5 / −1.0 in `other__recent`** (negative = the doc ranks BETTER under `single`), so the two-sided bar "median = 0 in each stratum" FAILS; the medians rest on the docs present in both arms' top-100: 217 / 210 of 600 overall and 20 / 14 in `other__recent`, 5 / 5 in `phys_eng__recent` (48 / 47 more docs enter the top-100 only under `single`, none only under `per_base_section`; 335 / 343 are in neither); own-doc raw score ratio single/per_base_section median 1.11 / 1.19. **A2 PASS** (own-recall@100 0.362 → 0.442 and 0.350 → 0.428). **B PASS** (1 / 0 of 1,200 fused top-10 slots displaced on the 120 topics). **C PASS** (122 / 128 of 6,000 slots displaced = 2.0 % / 2.1 %; own fused-rank median change 0). **D PASS** (0 duplicates, 0 wrong-origin hits). `per_era` by the same rule: does not hold either (A: −13.5 / −1.0 in the same stratum). Reading: pooling subjects raises delta docs' BM25F scores, which moves them up, not down; the bar as written does not distinguish the direction. By doc 11 §3 the adopted layout falls back to `per_base_section`, lever L2 is killed, and P1 has to be shown by R1 on the `n…` roots with L3–L5; **`SFU_DELTA_ROOT` is NOT eligible**.
