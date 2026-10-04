# O17 option (a): base-side `is_oa` bitmap (Agent OA, third-wave dispatch)

**Status:** ACTIVE

Owner decision 2026-10-01 on issue O17 (`docs/delta_ingest/02_DESIGN.md` §3.1):
option (a), a base-side `is_oa` bitmap built from one pass over an OpenAlex
snapshot and served as an override of the never-populated base `is_oa`, no
reindex. This file is the work log; results are filled in as they are measured.

## 0. Bulk-source estimate (written before the bulk pass started, 2026-10-01 15:40Z)

- **Source.** Public OpenAlex snapshot, `https://openalex.s3.amazonaws.com/data/jsonl/works/manifest.json`
  (fetched 2026-10-01 15:31Z, saved as `/home/vscode/work/delta_ingest/oa/manifest_20261001.json`):
  snapshot date 2026-09-23, **2,040 partitions, 476,196,327 works, 659.0 GB gzip**.
  Nothing else on this host holds the full set: the only local partitions are the two M7
  files under `/var/tmp/sfu_delta_B_20260929/` (0.80 GB).
- **Nothing is stored.** Each partition is streamed through the gzip decoder and a regex
  scanner; only the base hits (`uint32` ordinal + 1 bit) are written, one `.npz` per
  partition under `/home/vscode/work/delta_ingest/oa/work/units/` (*est.* ≤ 1 GB total).
- **Rates measured 2026-10-01 15:30Z.** Download: one stream 25.2 MB/s, two streams
  28.3 MB/s together, four streams 23.6 MB/s together (curl, 15–20 s each) — the link,
  not S3, is the ceiling. Scan: 359 MB gzip partition (276,848 works, 3.24 GB decoded)
  in 10.2 s on one core = ~35 MB/s gzip per worker.
- ***est.*** **Full pass 6.5–7.3 h** at 25–28 MB/s with 2 workers (link-bound), 2 cores
  (`nice -n 19 taskset -c 12-15`), RSS per worker < 0.3 GB. Started with a deadline of
  2026-10-02 04:30Z; parts not done by then are reported PARTIAL with the resume command.

## 1. Premise (measured 2026-10-01 15:47Z, lock-free, read-only)

| Check | Corpus | Result |
|---|---|---|
| tantivy `is_oa` term query, count per base section (10 sections) | 150,413,098 base docs | **0 match** (every section 0) |
| ordinal `is_oa.npy` (built 2026-08-02 from the served `meta.sqlite`, same size+mtime) | 150,413,098 rows | **0 nonzero** |

So the premise holds for every row, not only the 300,000-row sample of
INGEST_FIXES §O17: the BM25F filter (tantivy clause) and the SPLADE/dense
post-filter (meta row `is_oa`) can match no base doc, and every hydrated base
`is_oa` is `False`. The search-level before-numbers (`open_access_only` on 120
topics) are the "off" arm of §4. Raw: `/home/vscode/work/delta_ingest/oa/premise_tantivy.json`.

## 2. Design

House style of `docs/delta_ingest/02_DESIGN.md`. Code: builder
`spike/delta_ingest/oa_bitmap.py`, reader `src/lib/thinclient/oa_overlay.py`,
gate `SFU_OA_BITMAP` (default OFF; `docs/ENV_GATES.md`; invariants
`docs/CODE_INVARIANTS.md` §oa_overlay). Tests `scripts/tests/test_oa_bitmap.py` (15, tmp trees).

### 2.1 Source-agnostic, one streaming pass, resumable

- The builder takes any iterable of `(doc_id, is_oa)`: the fast OpenAlex line
  scanner (`iter_openalex_lines`, regex on the compact snapshot layout with a
  json fallback), or `pairs_from_adapter(adapter)` for any delta-ingest adapter
  (`JsonlAdapter` for a custom CSV/JSONL, `OpenAlexApiAdapter` for a trickle).
- Unit = one partition (or file). Base hits are mapped to base ordinals with
  `searchsorted` on the mmapped `wids.npy` and written as one `.npz` per unit by
  `os.replace` (presence = done). A killed pass resumes at the next unit; a
  unit killed mid-way is redone. Laptop = `--workers 1` over a few partitions
  a night; server = more workers. Memory: one partition's base hits plus the
  page cache of `wids.npy` (1.2 GB, shared by workers).
- `finalize` replays units in name order: snapshot units are named
  `updated_date=YYYY-MM-DD/part_NNNN.gz`, so a work present in two partitions
  takes the later one (`coverage.repeat_hits` counts such overwrites).
- Regex scanner vs full `json.loads` on both local partitions (464,260 works):
  **identical pairs**, 0 json fallbacks (2026-10-01 15:44Z).

### 2.2 Artifact and three states

`<dir>/oa_bitmap.json` + `known.npy` + `oa.npy` (two `packbits(bitorder="little")`
arrays over the 150,413,098 base ordinals, 18.8 MB each). States: known-OA,
known-not-OA, unknown (base doc not seen by the pass: merged/deleted works or
a partial pass). Unknown is `None` in the hydrated `is_oa`, never `False`;
`open_access_only` keeps known-OA only. Identity: the stamp names the ordinal
dir; load fails closed unless the ordinal space id matches, the index manifest
(if it carries one) matches, and the served `meta.sqlite` size+mtime equal the
values recorded at build. `bitmap_id` = sha256 over space id + both arrays.

### 2.3 Engine interaction

| Engine / layer | Gate OFF | Gate ON |
|---|---|---|
| tantivy (BM25F leg) | unchanged (`is_oa` term clause, matches 0 base docs) | base sections: clause dropped, section searched at `top_k × OVERFETCH_FILTERED` (10×), hits kept iff known-OA; delta sections keep the clause (their field is real) |
| SEISMIC (SPLADE leg) | unchanged | untouched; its existing post-filter (`_post_filter` → `_meta_rows`) now sees the override; fetch already `top_k × 10` when filtered |
| meta.sqlite | unchanged | read as before; `_meta_rows` overrides column 5 of base rows only |
| ordinals (`SFU_THINCLIENT_ORDINALS`) | unchanged | bypassed for `is_oa` queries (its `is_oa.npy` is the never-populated column); other filters keep the fast path. Bitmap reuses the ordinal `wids.npy` for addressing |
| sidecars (abstracts) | unchanged | unchanged |
| RRF | unchanged | unfiltered: inputs unchanged → ranking identical (measured §4); filtered: fuses the new OA hits |
| rerank | unchanged | `reranker._score_fulltext` reads hydrated `is_oa` → known-OA base docs gain the fulltext feature; final top-10 can move on UNFILTERED queries (measured §4) |
| result cache | key unchanged | stamp gains `@oa=<bitmap_id>`; a new bitmap rotates the key |
| packer | n/a | bitmap lives outside the base; not packed |
| delta layer | unchanged | delta copies win: superseded ids take delta meta rows before the override; BM25F `filter_hits` drops superseded base hits after `keep_oa` |
| dense leg / warm cache | unchanged | dense post-filter through `_meta_rows` (overridden); warm-cache rows store `int(bool(None))=0` for unknown, but base ids always resolve through meta first |

### 2.4 Ingest

`BaseSeeder` (`spike/delta_ingest/seed.py`) uses the bitmap state where known
when seeding base hashes (`oa_overlay=` argument, else `SFU_OA_BITMAP`;
`False` disables). With a bitmap from the same snapshot, an in-base work whose
only difference from meta was the never-populated `is_oa` classifies as
`unchanged` (no delta copy); a later real flip still classifies as `updated`.
Unit test `test_seed_with_bitmap_makes_is_oa_only_flip_unchanged`. Ingest-side
efficacy on M7's 4,465 is_oa-only updates: UNMEASURED (needs a seeded ledger
over the M7 hot subset with the full bitmap; command in §6).

## 3. Ingest efficacy (measured 2026-10-01 15:50–15:57Z, lock-free, nice 19 on cores 12–15)

Script `scripts/experiments/eval_delta_ingest_o17_ingest_seed.py` (reuses the
M7-seed harness: same file, slice rule, seed set, classify). Results
`data/eval_results/delta_ingest_O17_ingest_seed_partbitmap_20261001.json`.
Bitmap: built from the M7 primary partition alone (`updated_date=2026-09-15
part_0001`, 39,276 base works known) — i.e. the same-partition case; the
full-snapshot rerun is §5. Seed set 9,971 in-base `social_sciences__recent`
works, all 9,971 known in that bitmap (7,224 OA, 2,747 not).

| Seeded subset, min_year=2015 arm | bitmap OFF (= M7-seed) | bitmap ON |
|---|---|---|
| classified `updated` (→ delta copy) | 8,047 | **3,582** |
| `unchanged` | 1,918 | 6,383 |
| content-only updates (encode hash unchanged) | 5,530 | 1,065 |
| content-only updates whose only diff is is_oa | 4,465 | **0** |
| updates where is_oa differs at all | 5,225 | 0 |
| encode-hash changed (must re-encode) | 2,517 | 2,517 |

The OFF arm reproduces M7-seed exactly (8,047 / 2,517 / 5,530 / 4,465). ON
removes every is_oa-driven update: 4,465 is_oa-only delta copies avoided,
and the 760 is_oa+other updates stay updates for their other field. The
min_year=2010 arm is the same within 6 docs (8,053 → 3,588). Wall 399 s
(9p meta + sidecar reads; not a throughput number).

## 4. Serving: gate-off identity and before-numbers (measured 2026-10-01 16:58–18:26Z)

Script `scripts/experiments/eval_delta_ingest_o17_oa_bitmap.py drive --arms pre,offon`
(no bitmap). Two child processes under `flock -s`, venv mirror + local models,
`SequentialSeismicBackend`, health checks clean (CE loaded, no failure
signature, 0 degraded rows). `pre` = HEAD a18d8295 `src` with the O17 serving
commit ef206dde reverse-applied; `off` = HEAD `src`, `SFU_OA_BITMAP` unset.
120 topics (natural form) of `dense_ablation_qrels_20260817.json`, top_k 50,
rerank to 10. Results `data/eval_results/delta_ingest_O17_gate_off_identity_20261001.json`.

| Metric (120 topics) | Result |
|---|---|
| pre vs off, byte-identical: fused / final / OA-filtered fused / OA-filtered final | **120 / 120 / 120 / 120 — PASS** (bar: 120/120, the M1 property for the new gate) |
| `open_access_only` results, pre and off (before-numbers) | **0 results on 120/120 topics**; BM25F leg 0, SPLADE leg 0 |

So today `open_access_only=true` returns nothing at all from the thin-client
path (no delta layer is served), confirming the inferred O17 consequence at
search level. Latency per query under the shared lock: INVALID by declaration
(RRF 15–30 s per call with three other shared jobs and the bulk scan running).

## 5. Full bitmap (built 2026-10-01 23:00:57Z) — coverage, size, cost

Scan: `python -m spike.delta_ingest.oa_bitmap scan --manifest
/home/vscode/work/delta_ingest/oa/manifest_20261001.json --work
/home/vscode/work/delta_ingest/oa/work --ordinals /home/vscode/work/delta_ingest/oa/ords
--workers 2` (nice 19, cores 12–15), OpenAlex snapshot **2026-09-23**.
Results `data/eval_results/delta_ingest_O17_bitmap_build_check_20261001.json`.

| Item | Value |
|---|---|
| partitions done / failed / retried | 2,040 / 0 / 0 |
| works scanned | 476,196,327 (= manifest `record_count`); json fallbacks 0 |
| scan wall | 15:35:20Z → 23:00:14Z = **7.42 h**, 659.0 GB gzip, mean **24.7 MB/s** (link-bound; *est.* was 6.5–7.3 h) |
| unit files | 680 MB (2,040 `.npz`), `/home/vscode/work/delta_ingest/oa/work/units` |
| finalize | 7.1 s (two uint8 arrays of 150.4M in RAM) |
| **base coverage** (150,413,098) | **known 141,288,198 (93.93 %)**: known-OA **110,525,184**, known-not-OA **30,763,014**; **unknown 9,124,900 (6.07 %)** |
| works present in two partitions | 0 (`repeat_hits`) |
| artifact size | `known.npy` + `oa.npy` 18.8 MB each (37.6 MB) + 673 B stamp; needs the ordinal `wids.npy` (1.2 GB) for addressing |
| bitmap_id | `7745356383de5c50` |
| check: 100,000 random base ordinals, serving read path (`OAOverlay.states(W-id)`) vs raw unit files | **100,000 / 100,000 agree** (73,613 OA, 20,301 not, 6,086 unknown) |

Unknown = base ids absent from the 2026-09-23 snapshot (merged/deleted since
the base build); they hydrate as `is_oa: null` and are excluded by
`open_access_only`.

Ingest rerun with the full bitmap (`data/eval_results/delta_ingest_O17_ingest_seed_20261001.json`,
2026-10-01 23:02–23:07Z): identical to §3 — seeded subset updated 8,047 → **3,582**,
is_oa-only content updates 4,465 → **0**; min_year=2010 arm 8,053 → 3,588.

## 6. Gate-ON serving efficacy — QUEUED (not run at commit time)

M4 sequential held the exclusive lock (marker `EXCL_WAITING_EVAL`) until
~00:20Z, so the gate-ON arm is queued, detached, per the owner's no-waiting
rule: `/home/vscode/work/delta_ingest/oa/queue_gate_on.sh` (setsid; log
`/home/vscode/work/delta_ingest/oa/queue_gate_on.log`; marker
`SHARED_RUNNING_OA`; waits for no `EXCL_WAITING_*`, < 2 `SHARED_RUNNING_*`,
MemAvailable ≥ 14 GB; `flock -s`; gives up as NOT RUN at 05:50Z and writes
`gate_on_NOT_RUN.json`). It runs `eval_delta_ingest_o17_oa_bitmap.py drive
--arms off,on --bitmap /home/vscode/work/delta_ingest/oa/bitmap` (on = a
separate process loading through `_load` with `SFU_OA_BITMAP` set), then
`summarize` (identity vs the run-1 `pre` rows, OA-only counts off/on, ranking
neutrality, final top-10 changes, nDCG@10) and
`eval_delta_ingest_o17_bitmap_check.py --rows on.rows.jsonl` (every returned
OA id checked against the raw scan units — no OpenAlex API), and writes
`data/eval_results/delta_ingest_O17_oa_bitmap_20261001.json` itself. Until
that file exists every gate-ON serving number is **NOT RUN**. Latency from it
is INVALID (shared lock). Smoke (2 topics, partition-only bitmap, 18:30Z):
the on path loads, returns OA hits with `is_oa: true`, unknowns hydrate `null`.

To turn the gate on in serving: keep the bitmap dir AND its ordinal dir on
local disk outside `data/` (e.g. `/home/vscode/work/delta_ingest/oa/bitmap` +
`/home/vscode/work/delta_ingest/oa/ords`; the stamp records the ordinal dir by
absolute path, so move both together and rebuild with `finalize --ordinals
<new>` if relocated), set `SFU_OA_BITMAP=/home/vscode/work/delta_ingest/oa/bitmap`
in the serve env, restart or `reload()`. It fails closed if `meta.sqlite`
changes (size/mtime) — rebuild the ordinal space + `finalize` after any base
rebuild (the unit files are reusable only with the same ordinal space).
Refresh with a new snapshot: rerun `scan` into a fresh `--work` dir, then
`finalize`; the result-cache key rotates on the new `bitmap_id`.
