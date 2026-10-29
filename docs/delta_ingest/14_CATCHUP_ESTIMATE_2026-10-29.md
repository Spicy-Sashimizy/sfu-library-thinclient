# 14 — ESTIMATE: bringing the 2026-06-16 base index fully up to date (written 2026-10-29)

**Status:** ACTIVE

> **THIS DOCUMENT IS AN ESTIMATE, NOT A MEASUREMENT.** Nothing in it was run.
> It arithmetically combines figures that WERE measured elsewhere (each row
> names its evidence) with linear scaling far beyond the sizes those figures
> were measured at. Every total below carries *est.*; treat each one as
> an order-of-magnitude planning number with an error band of at least ±50 %.
> It is not a pre-registration, it sets no bar, and it changes no verdict in
> docs 09–13. Written at the owner's request on 2026-10-29, after the OpenAlex
> support answer of that day (`01_RESEARCH.md` §1.2a, `EXTERNAL_API_CONTRACT.md`).

## 0. The question and what "fully up to date" means

The owner asked: approximately how long, and how much, to take the served
search index from its snapshot state to today's date, fully current.

"Fully current" has two parts, and no single free route delivers both:

| Part | What it is | Free source |
|---|---|---|
| **New publications** | works OpenAlex added since the base build | the API feed `from_publication_date` + `sort=publication_date` (free, 1 credit per 200-work page — support 2026-10-29) |
| **Everything else** | updates to held records (citation counts, retractions, corrected metadata, merges), deletions, and *backfilled* older works that entered OpenAlex late | ONLY the quarterly public snapshot; the daily/changefile/`from_updated_date` options are Member+ and Partner (confirmed 2026-10-29: 429 `Plan upgrade required`) |

## 1. Inputs (measured, with their evidence)

| Input | Value | Evidence |
|---|---:|---|
| Base build | 2026-06-16, 150,413,098 works, 2010 onward | `data/thinclient_index/manifest.json`, `build_status.json` |
| Works with publication_date 2026-06-16..2026-10-29 held by OpenAlex | **11,142,846** | live probe 2026-10-29, `01_RESEARCH.md` §1.2a |
| … of which the 7-day window 10-22..10-29 | 305,297 (≈ 44 K/day) | same |
| Touched base records per day (one shard, one quarter, as coded) | ~701,538/day (363,152 text-filtered) | doc 10 §2, doc 13 §1 |
| Free credit budget | 10,000/day; search 10, filter page 1 (≤ 200 works), single-id GET 0 | OpenAlex support 2026-10-29 |
| SPLADE doc encode, RTX 4070 | 3,100 docs/s TRT clean; 629.7 docs/s ORT-CUDA contended | `02_DESIGN.md` §2; M6 `03_SPIKE_PLAN.md` |
| Generation build end-to-end (desktop_gpu) | 446.9 s / 194,931 docs ≈ 436 docs/s, peak 3.0 GB | M6 |
| Sections-tier serving tax per live delta doc | c = 21.35 ms per million (CI 12.62–27.63), upper bound | F0, doc 13 §1 |
| SEISMIC per-shard fold | 23.7–23.9 min, peak ≤ 11.37 GiB | `spike/delta_ingest/FOLDIN_FINDINGS.md` |
| Full snapshot stream | 2026-09-23 snapshot, 476 M works, 659 GB gzip, **7.42 h** | `spike/delta_ingest/OA_BITMAP_FINDINGS.md` |
| Full text-side build (export → 10 sections → pack → dense) | **~103 h wall** (2026-06-11 19:47 → 06-16 03:00); 3.1–7.7 h per section | doc 13 §1, `build_status.json` |
| Full SPLADE encode, 150 M | ~13.5 h | `REPRODUCIBILITY.md` (3,100 docs/s × 150 M) |
| SEISMIC shard builds | 17–24 min per shard, ~10 GB peak | `REPRODUCIBILITY.md`, F4 |
| Next free snapshots | quarterly, second Wednesday of Jan/Apr/Jul/Oct → latest **2026-10-14**, next **2027-01-13** | `01_RESEARCH.md` §1.1 |

## 2. Route A — free API feed, new publications only (*est.*)

| Step | Estimate | Arithmetic |
|---|---:|---|
| Pull 11.14 M works | **55,715 credits ≈ 5.6 days** of the free budget, $0 | 11,142,846 / 200 per page; 10,000 credits/day. Wall at the 100 req/s cap would be ~9 min — the budget, not the rate, is binding |
| SPLADE encode | **~1.0 h** clean, **~4.9 h** contended | 11.14 M / 3,100; / 629.7 |
| Generation build incl. delta SEISMIC shards | **~7.1 h** | 11.14 M / 436 docs/s |
| Serving tax while it lives in the delta layer | **≈ +240 ms per query** | 21.35 ms/M × 11.14 M (upper bound, linear far past the 1 M it was measured at) |
| SEISMIC fold into the 8 base shards | **~3.2 h** serial, ≤ 11.5 GB | 8 × ~24 min |

*est.* total: **about one week of calendar time, almost all of it waiting on
the credit budget; under one day of compute.**

What it does NOT deliver, so it cannot be "fully up to date":
- none of the ~95 M touched base records (701 K/day × 135 days, as coded),
  no deletions, no merges, no backfilled older works;
- the generation builder holds its records in memory (M6 peak 3.0 GB at
  195 K docs; `REPRODUCIBILITY.md`), so the pull must land as many
  generations, not one — the per-generation read tax is exactly what F0/M4
  measured against;
- the text (sections) tier has no fold yet (doc 13 S-fold = design only), so
  the +240 ms stays until one exists; `SFU_DELTA_ROOT` is default OFF and
  fold-in is not promotable as measured (F0, F3, F8 FAIL; F7 FLAGGED).

A scoped variant — Social Sciences domain only, 1,466,960 works since the
build (7,335 credits, 73 % of one day; serving tax *est.* +31 ms) — is the
realistic first use of this route (`01_RESEARCH.md` §1.2a).

## 3. Route B — full rebuild from the 2026-10-14 snapshot, feed for the tail (*est.*)

| Step | Estimate | Arithmetic / basis |
|---|---:|---|
| Stream the 2026-10-14 snapshot | **~7.4 h**, $0 | measured 7.42 h for the 2026-09-23 snapshot; same network assumed |
| SPLADE encode 150 M | **~13.5 h** | 3,100 docs/s |
| Text side: export, 10 tantivy sections, pack, sidecars | **~103 h** as last run; partly overlappable with the encode | June build; the June source (OpenSearch) is gone, so the new path is `scripts/reproduce/rebuild_from_openalex.py`, measured only at 21 K works (182 s) — its 150 M wall is UNMEASURED and the 103 h is the only anchor |
| SEISMIC shard builds | **~2.5–3.2 h** serial | 8 × 17–24 min |
| Deletions | included | `deleted_ids.csv.gz` in the snapshot (`01_RESEARCH.md` §1.1) |
| Feed for 2026-10-14..today, new publications | **~650 K works, ~3,300 credits**, a third of one day | 305 K / 7 days × 15 days |

*est.* total: **about 5 days of wall on the desktop box (6 with no overlap),
$0 of API spend.** At completion the index reflects OpenAlex as of
2026-10-14 for everything, plus new publications to the day of completion.
Disk: the stream is processed on the fly (not stored); scratch ~60 GB per
shard fold/build; peak RAM 10–11.4 GB per stage, within the 54 GB host.

What stays stale after Route B: updates to held records between 2026-10-14
and the next free snapshot (2027-01-13), i.e. up to three months of
citation-count drift, retractions and corrections.

## 4. The only free way to refresh held records sooner (*est.*, NOT recommended without asking support)

Support states a single-work GET by id costs nothing. Re-fetching held
records by id at the 100 req/s cap:

| Scope | Requests | Wall at 100 req/s |
|---|---:|---:|
| 2026 works only (≈ 11.14 M) | 11.14 M | ≈ 1.3 days |
| whole base (150.4 M) | 150.4 M | ≈ 17.4 days |

This is within the letter of what support wrote and far from its spirit
(sustained saturation of the cap for days). Record only; ask support before
relying on it.

## 5. Reading (*est.*)

- **Route A alone cannot make the index fully current**; it covers new
  publications only and lands them in a tier that is not promotable today.
- **Route B does**, to within two weeks at the moment it finishes, for about
  five days of machine time and no money — then drifts for up to three
  months until the next quarterly snapshot.
- Doc 13 §2 reaches the same place from the other direction: at a 25 % duty
  cycle the ~103 h rebuild supports a cadence of ~17 days at best, against a
  sections tier that spends its 8 ms budget in about a day of churn. The
  sections-tier fold (doc 13 S-fold, design only) remains the open item that
  would let Route A's feed be served continuously; nothing here changes
  that ordering.
- The paid Member+ plan (daily snapshot, changefiles, `from_updated_date`;
  `01_RESEARCH.md` §1.2 records ~$10k/yr, unverified) is the designed answer
  to the three-month drift.

## 6. What would turn this estimate into a measurement

Pre-register and run, in this order, each with its own results file under
`data/eval_results/`: (1) `rebuild_from_openalex.py` on one full tantivy
section from the 2026-10-14 snapshot (gives the real text-side rate and
replaces the 103 h anchor); (2) one day of the publication-date feed into
the spike ingest with `--source openalex-api` (gives the real credit
consumption and late-arrival share); (3) the Social Sciences scoped delta end
to end (gives the real serving tax at ~1.5 M delta docs instead of the linear
extrapolation from 1 M). Until then every number above stays *est.*
