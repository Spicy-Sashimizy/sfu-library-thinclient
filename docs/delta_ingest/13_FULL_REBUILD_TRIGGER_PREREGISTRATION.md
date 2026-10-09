# 13 — Pre-registration: when per-shard folds are not enough — the full-rebuild trigger (and the sections-tier fold it forces)

**Status:** ACTIVE

**PRE-REGISTERED 2026-10-08, NOTHING RUN; DESIGN ONLY.** Asked for by the
owner on 2026-10-08 ("where the tipping point is … where we need to trigger
the full ingest workflow"), to be written once F0 and the fold memory numbers
were in; both landed 2026-10-08. Frozen at the commit that adds this file.
Every bar below is numeric and written before any number for it exists; a
failed bar is recorded as FAIL and never re-cut; clarifications go in a dated
addendum written BEFORE the run they affect. Every calendar figure is *est.*
(derived, not measured) unless a record is named beside it.

## 0. The question

`10_FOLDIN_TRIGGER_PREREGISTRATION.md` decides when ONE base shard's SEISMIC
leg is rebuilt with its delta docs (a **fold**). A fold leaves three things
growing, and this document decides when they force a **full rebuild** — the
whole base re-made from a fresh full export of the source plus a replay of
the ledger: 10 tantivy sections, `meta.sqlite`, abstract sidecars, 8 SEISMIC
shards (optionally re-sharded), packer/hot-cold lists, and an emptied delta.

1. **The sections tier never folds.** tantivy, meta and abstract copies of
   every updated or new doc stay in the delta's consolidated generation
   (doc 10 §4: no rebuild input, because the base tantivy does not store
   `title`/`abstract` — `src/lib/thinclient/builder.py` schema `stored=False`,
   checked 2026-10-08 — and the base export spool is gone).
2. **Base dead copies are never reclaimed** in tantivy/meta/sidecars
   (`02_DESIGN.md` §4 item 8); a fold removes them only from SEISMIC.
3. **Shards grow** until a fold no longer fits the memory bar.

## 1. Measured inputs (all 2026-10-08 unless dated)

| Input | Number | Record |
|---|---|---|
| Sections-tier tax per delta doc (F0) | **c = 21.35 ms per million delta docs** (CI 12.62–27.63); Δ(g1M) − Δ(n1) +17.93 ms, CI 10.60–23.20 → F0 FAIL; BM25F delta-sections leg alone +15.0 ms. Upper bound (g1M kept its delta SEISMIC shard) | `data/eval_results/delta_ingest_foldin_f0_20261008.json` key `F0` |
| Post-fold residue (F3) | Δ(F, n0) +5.76 ms, CI upper 13.57 vs 8.0 → F3 FAIL; Δ(L, F) −1.5 ms (fold removes no measurable time while the sections tier stays) | `…/delta_ingest_foldin_f3f8_20261008.json` key `F3` |
| Fold memory vs shard size (F4) | tree peak **11.37 GiB at 18,819,434 docs** (fold 3, 2026-10-04) and **10.86 GiB at 17,691,720** (deletions fold) → slope *est.* **0.45 GiB per million docs** (two builds, different deltas; the peak moves between builds, doc 12 §6) | `…/delta_ingest_foldin_20261004.json` `F4_build_fold3`; `…_20261008.json` `F4_build_fold_del` |
| Fold wall | 23.7–23.9 min per shard on `desktop_gpu` (publish 15.1 s, F8) | same + F8 |
| Churn (one shard, one quarter, 10 % sample) | 27.4 % of docs updated, 15.1 % new, 6.0 % deleted per quarter; **701,538 touched docs/day across 8 shards as coded**, 363,152/day text-filtered (O14 + ledger rule, not built) | doc 10 §2; `09_…` §6 P1(b) |
| Original full build (text side) | export → 10 tantivy sections → pack → dense, **2026-06-11 19:47 → 06-16 03:00 (~103 h wall)**; per-section build 3.1–7.7 h (`build_secs`), 150,413,098 docs; exported from OpenSearch (gone) | `data/thinclient_index/build_status.json` |
| SEISMIC rebuild from twins | 8 × ~24 min ≈ 3.2 h serial (fold route, no re-encode) | F4 records |
| Full source stream | the OpenAlex 2026-09-23 snapshot streamed in 7.42 h (2,040 partitions, 476 M works) for the OA bitmap | `spike/delta_ingest/OA_BITMAP_FINDINGS.md` |

## 2. What the inputs mean in calendar time (*est.*, linear, from a fresh rebuild)

| Trigger level | as coded | text-filtered | Basis |
|---|---|---|---|
| Sections-tier tax reaches 8 ms (D ≈ 0.37 M docs) | **0.5 day** | 1.0 day | c × D, D = touched docs/day |
| … 16 ms | 1.1 days | 2.1 days | same |
| … 32 ms | 2.1 days | 4.1 days | same |
| Shard 0 fold peak reaches the 11.5 GB amended bar (+0.29 M docs) | ≈ 15 days | ≈ 15 days | 0.45 GiB/M × net growth +9.1 %/quarter (≈ 18.8 k docs/day/shard; new works drive it, so the text filter does not slow it) |
| … the 12 GB kill line (+1.38 M docs) | ≈ 74 days | ≈ 74 days | same |
| Base dead copies reach 20 % of a shard | 54.5 days | 140.9 days | doc 10 §2 (d) table |

Caveats that make all of it *est.*: one shard, one quarter (the first after
the 2026-06-16 build, so drift-inflated; steady-state churn UNMEASURED); c is
measured at two sizes (0.16 M and 1.0 M) and extrapolated linearly far past
1 M; the memory slope rests on two builds; g1M put half its docs in one base
section.

**Reading.** If c holds past 1 M, the sections tier — not SEISMIC memory — is
the binding constraint, by more than an order of magnitude in time (half a
day vs about two weeks). A full rebuild cannot be the answer to it: the last
one took ~103 h on the text side alone, so at a 25 % duty cycle it supports a
cadence of ~17 days at best, against a tier that spends its budget in about
a day. The sections tier therefore needs its own fold (doc 10 §8 flag,
confirmed by F0), and the full rebuild is the rarer reset for what a section
fold cannot do (re-sharding, encoder or schema change, accumulated drift).

## 3. Two rungs, one ladder

| Rung | What it rebuilds | Input | Fires on | Cost (*est.* unless measured) |
|---|---|---|---|---|
| **R-fold** (doc 10) | one base shard's SEISMIC leg | f16 twin + delta vectors | doc 10 (a)/(d)/(b)/(c) | 24 min, ≤ 11.5 GB (measured) |
| **S-fold** (new, design only) | one base tantivy section `<base>__<era>` + its meta rows + sidecar, with its delta docs and without its dead copies | the section's full text: titles from `meta.sqlite`; abstracts from a full source export (OpenAlex snapshot stream; other sources: their own full export) | §4 T1 / T3, per section | 3.1–7.7 h per section (2026-06 `build_secs`) + the export read; UNMEASURED as a fold |
| **Full rebuild** | everything, optionally into more shards | full source export + ledger replay | §4 T2 / T4 / T5, or T1 with no S-fold available | ~103 h text side + ~3.2 h SEISMIC (2026-06 record and F4), more if re-encoding |

## 4. Trigger parameters and candidate values (frozen)

All evaluated at every `publish()` alongside doc 10's trigger
(`spike/delta_ingest/trigger.py` writes the inputs for T1 and T3 already:
D per shard and (d)). Report only; nothing builds or publishes on its own;
publishing a rebuild is an operator step, as for folds (doc 10 §3 G3).

| # | Parameter (env / profile dial) | Definition | Candidates | Fires |
|---|---|---|---|---|
| **T1** | `SFU_REBUILD_SECTIONS_TAX_MS` | modelled sections-tier tax c × D_sections (D_sections = live docs held only by the delta's sections tier; c from F0, replaced by §6 M1's curve once measured) | 8, 16, 32 ms | S-fold of the section holding the largest share of D; a full rebuild only if no S-fold exists |
| **T2** | `SFU_REBUILD_FOLD_PEAK_GB` | projected fold peak of any shard = measured peak + slope × docs added since that measurement (slope from §6 M2, *est.* 0.45 GiB/M until then) | 11.5 (the amended F4 bar) | full rebuild into more shards (M10 path), unless the Rust-tool memory change (doc 12 §4 item 6) has landed and moved the projection |
| **T3** | `SFU_REBUILD_DEAD_FRAC` | dead base copies (deleted + superseded) in a tantivy section ÷ its docs | 0.10, 0.20 | S-fold of that section |
| **T4** | `SFU_REBUILD_MAX_FOLDS` | folds of one shard since its last full build | 4, 8 (or any F6 FAIL) | full rebuild of that shard's data (all legs) |
| **T5** | — | encoder model, SPLADE vocabulary, tantivy schema or section map changes | always | full rebuild |

Hysteresis: a full rebuild resets every counter; no T-trigger is evaluated
for 7 days after one publishes. Profile defaults are chosen by §7 after §6
has run; until then nothing ships ON.

## 5. Gates before any rebuild run

- **GR1 — inputs exist.** Inventory, per leg, of what a full rebuild and an
  S-fold read and whether it exists on this host today: the source export
  (OpenAlex snapshot: streamable, measured 7.42 h; an exporter from snapshot
  records to the builder's spool format does NOT exist —
  `scripts/build_thinclient_index.py` exports from OpenSearch, which is
  gone), titles (`meta.sqlite`, local), abstracts (local sidecar for one
  section only), SPLADE vectors (f16 twins for unchanged docs; delta ledger
  for changed ones), the ledger itself. Bar: every input present or a build
  path for it written and unit-tested. Until GR1 holds, the full rebuild is
  UNRUNNABLE here and §2's reading stands as a design constraint, not a plan.
- **GR2 — write protection.** As doc 10 G3: rebuild output goes to a side
  root on local disk; `data/seismic_150m/` and the served roots are never
  written; swap-in is a manifest repoint published by an operator.
- **GR3 — the text filter decision** (owner): whether metadata-only updates
  keep out of the sections tier (O14 + ledger rule). It halves T1's inflow
  (§2) and changes every T1 date.

## 6. Measurements and frozen bars (run order M1 → M2 → M3 → M4)

| # | Question | Metric | Bar (frozen) | Lock |
|---|---|---|---|---|
| **M1** | Is c linear in D, and what is the true sections-tier tax (no delta SEISMIC shard)? | F0's design, arms n0x, x1, g1M-noseis (g1M rebuilt `seismic=False`), g3M-noseis (3,000,000 docs, spread over all 10 base sections if GR1 gives their text, else stated) | c(3 M) within **±30 %** of c(1 M) on the noseis arms (the doc 10 §8 rule for (b)); outside → T1 uses the measured curve, recorded | exclusive |
| **M2** | Does the fold peak scale with shard docs as *est.*? | F4 recorder on a fold of shard 0 + 1,500,000 added docs (new-work vectors from the twin of another shard, re-routed for the fixture only) | measured peak within **±0.3 GiB** of the projection 11.37 + 0.45 × 1.5 = 12.05 GiB; the run aborts at the 12 GB `desktop_gpu` line as usual (an abort is a result: T2 fires at 1.5 M) | exclusive |
| **M3** | S-fold feasibility on the smallest section | rebuild `med_bio__archive` (149,551 docs) from meta titles + source-export abstracts + its delta docs, minus dead copies; compare with served section + delta | wall and peak recorded; BM25F leg top-10 overlap vs (served + delta) **≥ 0.99** on M3's 600-title protocol (doc 11 §2 sampling, this section only); 0 dead-copy leaks | shared |
| **M4** | Full-rebuild cost on this host | dry run of the GR1 pipeline on one shard's slice (export → spool → tantivy + meta + sidecar for its docs) | recorded only; feeds §7's duty cycle | exclusive |

## 7. Choosing defaults (fixed rule)

Per profile: T1 = the smallest candidate whose S-fold duty cycle (Σ S-fold
wall over all sections per T1 period, from M3 scaled by section docs) ≤
**25 %**; if none qualifies, the profile is FLAGGED (the delta layer cannot
keep the sections tier within budget at that churn; no default ships ON).
T2 = 11.5 GB. T3 = 0.20 unless T1 already fires first at every candidate.
T4 = 4 until F6 has passed, then 8.

## 8. Engine interaction

| Engine | S-fold | Full rebuild |
|---|---|---|
| tantivy BM25F | one section rebuilt with its delta docs, dead copies dropped; served by manifest repoint; IDF of that section changes (its doc set changes) | all 10 sections rebuilt; IDF everywhere moves to the new corpus |
| SEISMIC | untouched (R-fold covers it) | rebuilt from twins + delta vectors, or re-encoded (T5); optionally more shards |
| meta.sqlite | the section's rows rewritten into a new side DB; base `immutable=1` DB stays as rollback | rebuilt |
| Abstract sidecars | the section's store rebuilt | rebuilt |
| Delta layer / livedocs | folded docs leave the sections tier; their masks in that section clear; ledger rows marked folded per leg (G4 origins per leg, doc 10) | ledger replayed into the base, then reset; livedocs empty; trigger state reset |
| Dense leg (OFF) | none | none (re-run only if the leg is turned on) |
| RRF / rerank / `hydrate_scope` | ranks move where that section's IDF moved — needs a quality check (M3 overlap) | full quality parity run required (doc 10 F2 protocol on all shards) |
| Result cache | key rotates at publish | fully cold |
| Packer / hot-cold / personas / `manifest.json` | that section repacked; hot-cold lists for it recomputed | all rebuilt |
| `reload()` | F8 showed the first query after any backend drop is 2.17× warm (FAIL); a section repoint should reload the tantivy leg only — unverified | full cold start |

## 9. Generalisation and resource profiles

Source-agnostic: an S-fold or full rebuild reads "the full export of the
source" through the same adapters as ingest (OpenAlex snapshot, an arXiv
dump, a Zotero library export) plus the ledger; non-W ids route by the same
hash. Scale: on `laptop` corpora (≤ a few M docs) a full rebuild may be
cheap enough that S-fold is unnecessary — the same T-rule decides, with M3/M4
scaled to the corpus; on `server` S-folds of different sections run
concurrently up to the RSS cap.

## 10. Kill and flag criteria

- **Sections tier FLAGGED for this corpus** (no default ON): §7 finds no T1
  candidate within the 25 % duty cycle, or M3 fails its overlap bar after one
  harness-corrected re-run. The delta layer then serves only churn below the
  T1 budget (e.g. a subject subset or new works only) — an owner decision.
- **Full-rebuild path BLOCKED here**: GR1 cannot be met (no exporter
  possible from available sources). Recorded; T2/T4/T5 then have no action
  on this host and the deployment is bounded by T2's date.
- A failed bar is recorded and never re-cut; a harness defect is fixed and
  re-run once.

## 11. Owner decisions this document needs

1. GR3 — keep metadata-only updates out of the sections tier (halves T1's
   inflow; needs O14 + a ledger rule).
2. Whether to fund the S-fold build (§3) — the only rung that answers T1 at
   measured churn — or to restrict the delta to a churn subset.
3. The Rust-tool memory change (doc 12 §4 item 6) moves T2 by an amount
   unmeasured; it touches the fork `spike/seismic_upstream` (ask first).

Related: research already gathered on rebuild-vs-local-maintenance and
read-amplification mitigations in `12_NEXT_SESSION_2026-10-05.md` §5 and §8
(SPFresh, FreshDiskANN, OpenSearch SEISMIC thresholds, Lucene merging,
global statistics); none of it is a measurement of this system.
