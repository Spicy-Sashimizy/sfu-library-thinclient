# 16 · Subset-corpus pilot — selection machinery + build-viability design note

**Status:** ACTIVE

**Created 2026-07-16 (deployprep WI-5, stretch).** The portable handout
(`docs/LOCALIZED_DEPLOYMENT_PLAN.md` §2 "Subset" tier) ships a **subset index**
(~10–15M docs on a laptop, year × citation floor cut from 150M). This doc records
the selection machinery + the measured cut yields + the pilot-build viability
verdict — closing the plan's §8 open question #2 ("is `cited_by_count` indexed?
gates the year×citation selector depth axis").

**Great-grandparent: `docs/LOCALIZED_DEPLOYMENT_PLAN.md` §2–§3.** The subset tier
is the handout's core: a re-bundle small enough for a 20–40 GB laptop, pre-encoded
(no GPU), with live-API fallback for out-of-range queries. Nothing existed here
before WI-5 — this is the first in-container work on the subset path.

## The honest finding (measured 2026-07-16): the citation axis is BLOCKED here

The served `meta.sqlite` `docs` table has columns
`[id, title, doi, year, type, is_oa, section]` — **`cited_by_count` is NOT
present** (verified via `PRAGMA table_info`). §8 #2 of the localized plan is
answered: **the citation floor is not indexed in the served metadata.** The
`data/openalex_cite_cache.json` (403 KB) is the **eval** citation cache
(sfu_eval_queries' results only), not a corpus-wide floor.

So the "year × citation" two-axis selector the plan calls for is **partially
blocked** on this container:
- **Year axis: measurable here** (`docs.year` is present; this WI measures it).
- **Citation axis: blocked** — needs either (a) a re-EXPORT from the source index
  with `cited_by_count` in `_source` (the source OpenSearch has it; the build
  spool didn't carry it — `EXPORT_FIELDS` in `build_thinclient_index.py` omits
  it), or (b) OpenAlex polite-pool enrichment (10 req/s, ~150M docs → days; not
  in-container — owner-gated, no external spend).

This is recorded, not papered over: the localized plan's §4 subset doc-count
model ("150M→15M = ~40 GB") assumed BOTH axes; the honest in-container number
on the year axis ALONE is what WI-5 measures. The two-axis cut stays a host-tier
unblock (the re-export), owner-gated.

## Year-axis cut yields (measured from meta.sqlite — prefix sample, 9p-blocked for full)

The docs table has NO index on `year` (`PRAGMA index_list: []`) and the db is a
25 GB file on the 9p/drvfs mount → every full-traversal query (`COUNT(*)`,
`GROUP BY year`, `WHERE year>=?`, `LIMIT N OFFSET M`, random-id pk probes) is
**D-blocked on `p9_client_rpc`** — infeasible in-container (~22 min for the full
scan; scattered pk probes even slower). So the **only in-container-measurable
truth** is a 2M-row sequential PREFIX sample (`SELECT year FROM docs LIMIT N`,
18.5 s — one contiguous 9p read). It is **BIASED toward early-ingested sections**
(the table is section-ordered, not year-sorted — the 1st 1M rows are ~80% one
section, an `_archive` era). Illustrative of the year shape, NOT a representative
corpus sample.

| year floor | prefix-sample count | prefix-sample share | full corpus |
|---|---|---|---|
| ≥ 2024 | 12,493 | 0.6% | BLOCKED (9p full-scan, ~22 min) |
| ≥ 2023 | 21,073 | 1.1% | BLOCKED |
| ≥ 2022 | 32,672 | 1.6% | BLOCKED |
| ≥ 2020 | 69,930 | 3.5% | BLOCKED |
| ≥ 2018 | 118,907 | 5.9% | BLOCKED |
| ≥ 2015 | 1,986,985 | 99.4% | BLOCKED |
| ≥ 2010 | 1,986,985 | 99.4% | BLOCKED |

Total corpus = **150,413,098 docs** (the G6/G7 build figure, `TOTAL_DOCS` in
`serve_footprint_bench.py`). 10 sections (from the filesystem `sections/` directory —
the SQL `GROUP BY section` is also 9p-slow, so the section inventory uses the
directory listing instead).

**The full-corpus year cut is the host-tier follow-on** (a native-ext4 host
counts in ~seconds; the 9p bottleneck is a container-mount artifact, not a data
property). The LOCALIZED_DEPLOYMENT_PLAN §3 figure "2022+ = 83M docs" came from
the LIVE source index (pre-thinclient); the in-container thinclient `docs` cut
is 9p-blocked from corroborating it here. Recorded — not silent.

## Pilot build: BLOCKED on the spool (recorded, with the unblock)

The pilot shard build (`scripts/seismic_testbed/build_persona_seismic.py --jsonl`)
needs the pre-encoded `sparse_field` **spool** (`data/thinclient_index/spool/
*.jsonl.zst`) — and the spool directory is **absent** (the root CLAUDE.md notes spool
re-derivation; the EXPORT step of `build_thinclient_index.py` produces it from
the source index, which isn't running here). So the ~1M-doc pilot build through
the existing index-build path is **not runnable in-container** — the selection
machinery (this doc + the measured cut yields + a 1M-doc id selection) is the
in-container-deliverable; the pilot BUILD is the host-tier follow-on (re-export
the spool with `cited_by_count` added to `EXPORT_FIELDS`, then subset + build).

**The unblock sequence (owner-gated, not done here):**
1. Re-export the spool from the source index, ADDING `cited_by_count` to
   `build_thinclient_index.EXPORT_FIELDS` (this single-line change unblocks BOTH
   the citation floor axis AND the pilot build).
2. Select the subset: year floor × citation floor (now both available) → the
   ~10–15M doc id set (this WI's `wi5_subset_selection.py` extends trivially to
   the two-axis cut once the citation column exists).
3. Build the pilot shard: `spool_to_seismic_jsonl.py` (filter to the subset ids)
   → `build_persona_seismic.py --jsonl <subset> --index-path <pilot>` →
   `convert_shard_to_mmap.py` (the C2.5 mmap conversion, same path the served
   e5_v2 shards went through).
4. Validate: build succeeds, sane size/doc (~5 GB/1M ≈ the served ratio), spot-
   check queries return real oaids (the F6 no-op guard).

## Selection machinery (committed, runnable)

`scripts/seismic_testbed/wi5_subset_selection.py`:
- `measure_year_cuts(meta, floors)`: ONE streaming pass over `SELECT year FROM
  docs` → year histogram (no index, so a single scan serves all floor cuts via
  in-memory derivation). Read-only URI (the 25 GB db is never written).
- `select_pilot_ids(meta, year_floor, target)`: streams `SELECT id, year FROM
  docs`, collects ids with `year >= floor` until the target (reuses the scan, no
  second pass) → writes `wi5_pilot_ids.txt` (the 1M-doc selection for the pilot
  build when the spool lands).
- Records the citation-axis + spool blockers honestly in the result JSON.

## Limitations + honest caveats

- **No citation floor in-container.** The "year × citation" two-axis cut the
  localized plan models is year-axis-only here; the citation axis is the recorded
  host-tier unblock, not a silent assumption.
- **No pilot build in-container.** The spool is absent; the build is the host-
  tier follow-on (the unblock sequence above). The selection + cut yields ARE the
  in-container deliverable.
- **Year-only subset is coarser than the plan's two-axis cut.** A year-only floor
  to ~10–15M (the plan's target) drops the long tail regardless of citation; the
  citation floor was the "quality selector" (keep cited work, drop the never-
  cited bulk). Without it, a year-floor subset over-represents recent uncited
  work — acceptable for a pipeline-viability pilot (does the build path work?),
  NOT for a quality-evaluated handout. Recorded.
