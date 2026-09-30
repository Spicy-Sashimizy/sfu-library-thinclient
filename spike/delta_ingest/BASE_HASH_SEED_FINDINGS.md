# Base-hash seed for the ingest ledger (O4) + DOI (O5) + min_year (O6): findings

**Status:** ACTIVE

Measured 2026-09-30 18:08Z–18:17Z (UTC) on this host (16 cores, 31 GB, WSL2;
base `meta.sqlite` and the hot-section abstract sidecar read over the
`/workspaces` 9p mount; partition files on local disk). All numbers below are
copied from the results file, which is authoritative.

- Results: `data/eval_results/delta_ingest_M7seed_20260930.json`
- Harness: `scripts/experiments/eval_delta_ingest_m7_seed.py` (pre-registered
  header commit 23cfafc1, revision 945dc47a, timestamps fc8586c3; run at
  fc8586c3)
- Code: `spike/delta_ingest/seed.py` (new), `ledger.py` (`base_hashes`
  table, `seed_base`, `base_known`, seeded `classify`), `records.py`
  (`normalize_doi`, `BASE_MIN_YEAR`), `adapters.py` / `cli.py` (min_year
  default, `seed-base` subcommand). Commits 6ba3c4de, 945dc47a.
- Tests: `scripts/tests/test_delta_seed.py` (6 tests; delta suites 17 passed).
- Seeded ledger copies: `/home/vscode/work/delta_ingest/seed/ledger_{primary,supplementary,T2,T2w}.sqlite`.

## What was built

- `BaseSeeder` rebuilds for each base doc the `DocRecord` the snapshot
  adapter would build (meta title/doi/year/type/is_oa, sidecar abstract, DOI
  via `normalize_doi`, meta year 0 read as no year) and stores 64-bit
  prefixes of its `content_hash` / `encode_hash` in a new ledger table
  `base_hashes(id INTEGER PK, ch, eh)`. The table sits outside `docs`, so seeded
  ids never enter masks, the buffer or `docs_live`. A staged `docs` row always
  takes precedence. `classify` compares an in-base id that has no `docs` row
  against its seed: equal content hash gives `unchanged`, otherwise
  `updated`. An unseeded in-base id stays `updated`, as before.
- Modes: `seed_ids` (explicit ids) and `seed_range` (meta id range, resumable
  through a `sources` cursor committed in the same transaction as the hashes).
  Docs whose section has no local sidecar are skipped and counted per section.
  `SFU_META_STAGE_DIR` is honoured when non-blank. Nothing is written under
  `data/` (the harness checked: no new entries).
- O5: `records.normalize_doi` (trim, lowercase, strip `https://doi.org/`,
  `http://doi.org/`, `dx.doi.org/`, `doi.org/`, `doi:`) is the only DOI
  normaliser. `normalize_openalex_work`, `normalize_generic` and the seed all
  call it.
- O6: `BASE_MIN_YEAR = 2010` is the default for `OpenAlexSnapshotAdapter` and
  CLI `--min-year`, and can still be overridden (`None` disables the gate).
  The base holds year ≥ 2010 plus year-less works: the `__archive` sections
  carry year 0, as sampled in meta.

## Pre-registered expectation and result

The expectation, taken verbatim from the dispatch: "the seeded-ledger ratio for
in-base docs agrees with M7's exact proxy". PASS iff |R_enc / M7 − 1| ≤ 0.02,
where R_enc = seeded touched / encode-hash changed, in the min_year=2015 arm
(the set M7 used).

| file | seeded subset touched | unchanged | updated (content hash) | encode hash changed | R_enc | M7 ref | verdict |
|---|---|---|---|---|---|---|---|
| primary 2026-09-15/part_0001 | 9,965 | 1,918 | 8,047 | 2,517 | **3.9591:1** | 3.959 | **PASS** |
| supplementary 2026-09-22/part_0054 | 10,843 | 2,034 | 8,809 | 3,182 | **3.4076:1** | 3.408 | **PASS** |

Consistency check: the encode-changed counts and the content-changed counts
equal M7's (2,517 / 8,047; 3,182 / 8,809) exactly. The seed and M7's proxy build
the same record. The min_year=2010 arm adds 6 (primary) and 1
(supplementary) seeded docs, giving R_enc 3.9567 and 3.4079.

## The gap: content hash vs encode hash

As coded, `classify` calls 8,047 of the 9,965 seeded docs "updated", a ratio of
1.238:1 (supplementary 1.231:1). Only 2,517 of them need an encode. The other
5,530 "content-only" updates break down by field as follows (primary; a doc can
count under more than one field):

- is_oa differs: 5,225. is_oa alone: 4,465. is_oa+type: 727.
- type differs: 1,034. type alone: 302.
- year differs: 28.
- DOI differs after normalisation: 13.

Supplementary: 5,627 content-only (is_oa 4,888, type 1,493). The is_oa drift
is one-directional. M7 recorded 25,792 base-0 to new-1 flips and none the other
way, which suggests the base's is_oa values are stale or biased to 0. This is
inferred, not verified.

As coded, these content-only updates are still re-encoded:
`IngestLedger.reusable_sparse` only reuses a sparse vector stored in
`records`, and a base doc has none (see Issues). Whole-partition numbers with
only the hot section seeded (primary, 2015 arm) are new 160,347 / updated
32,666 / unchanged 1,918. That gives touched:must-encode of 1.010:1 as coded and
1.040:1 if content-only base updates skipped the encoder. The supplementary
file gives 1.038:1 and 1.161:1. These are partial-seed numbers. The M7 FAIL
stands on both files, because new works dominate the primary file and
in-base ratios are about 3.4–4:1.

## O5 / O6 on the same files

- O5, primary, in-base in slice: 34,584 compared. 33,600 DOIs differ with the
  base DOI raw. 379 still differ after `normalize_doi` on both sides, which
  matches M7's 379. Supplementary: 45,129 raw, 78 after normalisation.
- O6, primary: the 2015 gate drops 199 in-base works and the 2010 gate drops
  101. All 101 are years 1857–2009 that the base holds anyway, per the
  year-by-year table in the results file. In-slice, the 2010 gate gives 205,358
  (in base 34,620) against 194,931 at 2015. Supplementary: 29 in-base works
  dropped at 2015, 14 at 2010, in-slice 70,378 against 55,237.

## Throughput and extrapolation (timings_valid = false)

The host was shared: B7 was running on cores 0–7 and S0-2 (about 19 GB) on
cores 8–15. This run used `nice 10` on cores 8–15.

| run | docs seeded | meta rows | wall s | seeded docs/s | meta rows/s | rchar MB | maxrss MB |
|---|---|---|---|---|---|---|---|
| T1 primary `seed_ids` (random ids) | 9,971 | 9,971 | 11.6 | 856.3 | — | 171.7 | 500 |
| T1 supplementary | 10,844 | 10,844 | 9.1 | 1,197.0 | — | 181.4 | 576 |
| T2 `seed_range` from W2000000000, 300k meta rows, 9p | 60,386 | 300,000 | 39.5 | 1,528.3 | 7,592.8 | 697.3 | 576 |
| T2w same range repeated | 60,386 | 300,000 | 28.4 | 2,122.9 | 10,546.7 | 697.3 | 576 |

In T2, 239,614 of the 300k rows were skipped because their section has no
local sidecar. T2 timers: meta 4.4 s, abstract fetch 33.2 s, hash 1.3 s, ledger
write 0.16 s. The abstract fetch dominates. In id order each seeded doc reads
about one sidecar block (11.5 KB rchar per doc). The ledger costs 28.3 B per
seeded row for the `base_hashes` table.

A local-copy arm was NOT RUN. No local copy of meta.sqlite or the hot sidecar
exists, and `SFU_META_STAGE_DIR` is unset in `.env`.

Extrapolation to 150,413,098 docs is *est.*. It assumes every section's
sidecar is local with the hot section's per-doc cost in id order, that per-row
and per-doc costs from the T2 timers scale linearly, and a single process on
this shared host.

- Wall: 0.588 ms per doc, about **24.6 h**. The naive wall/seeded figure is 27.3 h.
- Reads: about **1,737 GB** in id order.
- Ledger: about **4.3 GB** of `base_hashes`.

## What a full seed would cost and where it would run

On this host only `social_sciences__recent` (23,398,073 docs) keeps a sidecar.
The other nine sections are `packed/*.tar.zst` archives. A full seed therefore
needs each packed section unpacked to local disk first (686 GB free on `/`),
then passed with `--sidecar-root`. Unpack cost is UNMEASURED.

Id order re-reads a block per doc. Iterating each sidecar in block order
(sequential `blocks.bin`) with meta looked up by id would read each block
once. For the hot section that is 11,131,511,857 B / 23,398,073 docs ≈ 476 B
per doc, about 72 GB for 150M docs at the same density (*est.*, design only,
not built or measured). That is roughly 24× fewer bytes than id order.

Place: a local-disk copy on this host (cores 8–15, off 9p), or the rebuild
host. The seed is CPU-light (hash 1.3 s per 60k docs) and IO-bound.

## Deviations

- The partition was streamed line by line with the adapter's slice rule
  reproduced exactly, not through `OpenAlexSnapshotAdapter`. The adapter
  decompresses whole partitions (O7) and was not needed to reproduce M7's set.
  The counts reproduce M7 exactly (194,931 in slice; 34,584 in base).
- Seed set = the min_year=2010 superset (9,971 / 10,844). The primary verdict
  uses the 2015 arm, which is exactly M7's 9,965 / 10,843.
- The extrapolation model was revised before the measured run (header
  REVISION, 945dc47a).

## Not measured

- Throughput from a local copy.
- Unpacking the packed sections.
- A block-order seeder.
- Seeding of any section other than the hot one.
- Steady-state partition-to-partition churn. Base text is from the
  2026-06-11..16 build, as for M7.
- Whether the base's is_oa bias is real.
- The encode cost saved end-to-end. That needs base-vector reuse (below).

## Issues found, not fixed

1. `spike/delta_ingest/ledger.py:152` `reusable_sparse` reuses only vectors
   stored in `records`. A seeded base doc with an unchanged encode hash
   (5,530 of 9,965 in the primary subset) is still re-encoded. Reusing it would
   need a copy of the base SEISMIC forward vector.
2. `src/lib/thinclient/abstracts.py:682` `AbstractStore` opens the sidecar
   SQLite read-write (no `mode=ro`). It is harmless on this rollback-journal
   file, which gained no new files, but it is not read-only by construction.
3. `scripts/snapshot_downloader.py:94` `DEFAULT_MIN_YEAR = 2015` and
   `spike/archive/inplace_update/prep.py:196` (moved at the 2026-09-30 closure) (`parse_part(min_year)`) still carry
   their own year gate. They are not aligned to `BASE_MIN_YEAR`.
4. `spike/delta_ingest/cli.py:191`: the default `--delta-root` is
   `<index_root>/delta`, i.e. under `data/thinclient_index/`. Running
   `seed-base` without `--delta-root` writes a ledger there.
5. `spike/delta_ingest/adapters.py:173`: the whole partition is decompressed
   in memory (O7, unchanged).
6. The base meta is_oa appears 0-biased (inference above). If so, every
   in-base doc whose OA status has since become true is a content-only update
   on first contact.
