# Fold-in F-bars (doc 10 §6): first fold of shard 0

**Status:** ACTIVE

Spec: `docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md` (frozen; Q-a
Reading A by its 2026-10-03 addendum). Harness:
`scripts/experiments/eval_delta_ingest_foldin.py` (its header fixes the
implementation readings of the F2 row, written before the run). Results:
`data/eval_results/delta_ingest_foldin_20261003.json` (keys `F4_build`,
`F2`). Gates: `FOLDIN_GATES_FINDINGS.md`. Measured 2026-10-03.

**F2 = FAIL as computed (Q-b, QD, shard level) on 2026-10-03 and again on
the fold-2 rebuild of 2026-10-04; by the owner's 2026-10-04 decision the
federated level binds for Q-b, on which F2 = PASS on both folds (sections
"2026-10-04" below). F4 build record over its frozen 10 GB memory bar on
all three folds; the owner amended that bar to 11.5 GB on 2026-10-05, on
which fold 3 (11.37 GiB) is within (last section). F1, F3, F5, F6, F8 NOT
RUN. Nothing was published.**

**2026-10-08: a NEW fold on a deletions fixture (1.13 M tombstones, 28,577
superseded copies): F2 = PASS at the owner's levels with Q-d 0 leaks, F4
within every amended bar (tree peak 10.86 GiB) — section "2026-10-08 — deletions fixture fold
(Q-d)".**

## Fixture and fold

`/home/vscode/work/delta_ingest/foldin/fixture_n8` = copy of the M4 corpus (b)
root `root_n8` (8 generations, 160,347 new docs, 0 tombstones, 0 superseded),
routes backfilled and published on the copy. Fold 1 of shard 0
(`foldin/shard0/fold1`), input and pinned token map = the local f16 twin:
18,799,322 base rows kept, 0 dropped, **20,112** delta docs added → 18,819,434
docs; 0 tokens appended to the map; baseline of the protected trees unchanged
(817 files).

## F4 — build record (exclusive lock 20:51–21:15Z, quiet host; publish stage NOT included)

| Measure | Result | Bar | Reads |
|---|---|---|---|
| Wall | 1,416 s = 23.6 min (dump 147 s, build 1,122 s, c1a 41 s, dotvbyte 97 s) | ≤ 90 min | within |
| Peak RSS + VmSwap | process tree **12.11 GB** (swap 0.05 GB); largest single process **10.27 GB** | ≤ 10 GB | **over** on both |
| Peak scratch (fold dir) | 59.50 GB | ≤ 60 GB | within by 0.5 GB |
| Output (f16 + dv-v2) | 13.83 GB | ≤ 15.23 GB (1.10 × 13.83 GB × 18,819,434 / 18,799,322) | within |

Doc 10 §8 kills the track at peak RSS > 12 GB per shard. The process-tree
peak (12.11 GB, sampled every 2 s, summed over the parent and its children)
is above that; the largest single process (10.27 GB) is below. Doc 10 does
not say which one "peak RSS" is. Not decided here.

## F2 — quality parity, F (s′ + masks, preview root) vs L (base 0 + 8 delta generations)

Run 21:22–21:42Z under the shared lock (no exclusive holder), code 189e4107,
complete (120 + 100 + 240 leg queries, 240 pipeline queries), healthy (no
failure signature, no swap, self-check equal to `search_encoded` 10/10).
The first attempt at 21:15Z stopped before measuring (import path); a
3-query smoke then found two harness defects (a blanked
`SFU_SEISMIC_HEAP_FACTOR` broke the SPLADE leg; the Reading A `m_set` source
file held a later prefix run). All three were fixed (189e4107) before this,
the only measured run.

| Bar | QT (120) | QD (100) | Verdict |
|---|---|---|---|
| **Q-a** federated overlap@10(F, L) ≥ bar A (0.985 / 0.980; m_set 0.9908 / 0.985 recomputed) | **0.9992** (119/120 identical) | **0.9980** (98/100 identical) | PASS (also ≥ 0.99, Reading B) |
| shard-own overlap@10(F, L), recorded beside Q-a | 0.9892 (109/120 identical, min 0.8) | 0.9780 (81/100 identical, min 0.8) | QT clears A, QD does not; neither clears 0.99 |
| **Q-b** overlap@10(F, L) ≥ overlap@10(R, A0) − 0.005 = 0.9808 / 0.9820 (R vs A0 recomputed: 0.9858 / 0.9870, shard level) | shard-own 0.9892, federated 0.9992 | shard-own **0.9780**, federated 0.9980 | **FAIL on QD at shard level** (PASS on QT; PASS on both at federated level) |
| **Q-c** NDCG@10 final, F − L, 120 topics | F 0.72160, L 0.72162, Δ −0.00003, CI95 [−0.00008, 0.00000]; 236/240 final top-10 identical | | PASS (CI contains 0, at its edge) |
| **Q-d** mask leaks, 460 leg queries + 240 fused/final lists | 0 (L control 0) | | PASS — weak: 0 tombstones and 0 superseded docs, only double-serving is exercised |

**Verdict as computed: FAIL (Q-b).** The failure depends on one of the
harness's implementation readings, fixed before the run: Q-b is required at
the shard level (like for like with R vs A0, which is a one-shard
comparison) as well as federated. Read on the federated leg only, every bar
passes. At shard level 19/100 QD and 11/120 QT queries change their top-10
set, by 1 doc (25 queries) or 2 docs (5 queries). The pinned-map rebuild
WITHOUT delta reproduced the served shard at 1.000 (`TWIN_DRIFT_BASELINE_
FINDINGS.md`), so this difference comes with the 20,112 added docs
(inference: they change the clustering/summaries of the rebuilt shard; not
isolated).

## Open for the owner

1. Q-b level: shard level binding (FAIL as run) or federated only (PASS).
   Doc 10 §8: an F2 Q-a/Q-b failure kills the track only "after one fold
   rebuild"; no rebuild has been run.
2. F4 memory: which number is "peak RSS" (tree 12.11 GB is over the 12 GB
   kill line, single process 10.27 GB is over the 10 GB bar only). After the
   2026-10-04 changes (below) the choice no longer decides the kill line:
   every reading is under 12 GB and over the 10 GB bar.
3. Q-d needs a fixture with deletions and superseded docs (doc 10 §5 (ii),
   Stage-0 subsample) before it means much.

## 2026-10-04 — F4 memory, second attempt (dump stage)

The 2026-10-03 record stands as measured. Diagnosis of where the memory went,
dump stage alone (`scripts/experiments/probe_delta_ingest_fold_dump_mem.py`,
8 workers, local f16 twin of shard 0, no delta rows, idle host, sampled every
1 s, GiB):

| Dump code | Tree VmRSS + swap | of which RssAnon | of which RssFile | Tree Pss | Largest process | Wall |
|---|---|---|---|---|---|---|
| 2026-10-03 (workers map the twin's forward files) | 10.37 | 4.35 | 6.63 | 10.05 | 1.40 | 120.5 s |
| 2026-10-04 (workers `read()` their ranges, `foldin._dump_read`) | **4.37** | 4.30 | 0.07 | 4.20 | 0.73 | 118.6 s |

The two dumps are byte-identical (`cmp` of the 38,895,361,743-byte jsonl).
The mapped input pages were page cache counted as RSS in each worker; the
change removes them from the count, not from the page cache.

### Rebuild through the F4 recorder: fold 2 of shard 0 (2026-10-04 21:24–21:47Z)

Same fixture, input, pinned map and arguments as fold 1; exclusive lock, quiet
host, code f44b4346 (the dump change only);
`data/eval_results/delta_ingest_foldin_20261004.json` key `F4_build_fold2`;
the recorder now writes a per-process timeline
(`/home/vscode/work/delta_ingest/foldin/fold_build_s0_20261004.log.mem.jsonl`,
2 s samples) and RssAnon / RssFile / Pss peaks beside the 2026-10-03 fields,
whose definitions are unchanged. Publish stage NOT included.

| Measure | Fold 1 (2026-10-03) | Fold 2 (2026-10-04) | Bar | Reads |
|---|---|---|---|---|
| Wall | 1,416 s | 1,359 s = 22.7 min (dump 128 s, build 1,090 s, c1a 38 s, dotvbyte 90 s) | ≤ 90 min | within |
| Peak tree VmRSS + VmSwap | 12.11 GiB | **13.13 GiB** | ≤ 10 GB | **over** |
| Largest single process | 10.27 GiB | **11.24 GiB** | ≤ 10 GB | **over** |
| Peak tree RssAnon + VmSwap (new field) | not recorded | 11.02 GiB | — | recorded |
| Peak scratch | 59.50 GB | 59.50 GB | ≤ 60 GB | within |
| Output | 13.83 GB | 13.83 GB | ≤ 15.23 GB | within |

**F4 memory as defined by the recorder did not improve (12.11 → 13.13 GiB);
the dump change fixed a stage that was not the peak.** Per stage, from the
timeline (GiB, VmRSS; anon / file split in brackets):

| Stage | Tree | Largest process | What it is |
|---|---|---|---|
| dump (8 workers) | 5.12 | 0.75 | was 10.37 before the change (probe above) |
| build (`SeismicIndex.build` + save, in the cli process) | 9.65 | 9.65 (anon 9.63) | the builder's own working set |
| c1a (`c1a_mmap_index` child) | 10.99 | 9.16 (anon 9.16) | child 9.16 + **1.89 left in the cli process after `del idx`** |
| dotvbyte (`convert_f16_to_dotvbyte` child) | **13.13** | **11.24** (anon 4.96, file 6.29) | child 11.24, of which 6.29 is the mapped f16 source (page cache), + the same 1.89 |

So both recorded peaks are the dotvbyte converter at its last sample, and
6.29 GiB of its 11.24 is the source shard mapped read-only. The fold-1
numbers (12.11 / 10.27) are read as the same stage caught at an earlier
sample (inference: the converter's RSS rises until it exits and the sampler
runs every 2 s; fold 1 has no timeline to confirm it).

Fold 2 vs fold 1, file by file (`cmp`): the forward files, document mapping
and config are identical (12 files); `posting_lists.bin`,
`token_to_id_map.bin` and `manifest.json` differ in both the f16 and the
dv-v2 dir. A full-shard build with a pinned token map is therefore NOT
byte-reproducible in its posting lists.

Second change, 2026-10-04 (`generation._release_freed_heap`: `gc.collect()` +
glibc `malloc_trim(0)` after the build's `del idx`), aimed at the 1.89 GiB
left in the cli process. Measured on a third build, fold 3 of shard 0
(22:09–22:33Z, same inputs and arguments, exclusive lock, quiet host, code
9f677a21; key `F4_build_fold3`, timeline
`…/foldin/fold_build_s0_20261004_fold3.log.mem.jsonl`):

| Measure | Fold 2 (dump change only) | Fold 3 (+ heap release) | Bar | Reads |
|---|---|---|---|---|
| Wall | 1,359 s | 1,431 s = 23.9 min (dump 161 s, build 1,116 s, c1a 48 s, dotvbyte 93 s) | ≤ 90 min | within |
| Peak tree VmRSS + VmSwap | 13.13 GiB | **11.37 GiB** | ≤ 10 GB | **over** (under the 12 GB kill line of §8) |
| Largest single process | 11.24 GiB | **11.24 GiB** (converter: 4.95 anon + 6.29 mapped source) | ≤ 10 GB | **over** |
| Peak tree RssAnon + VmSwap | 11.02 GiB | 10.32 GiB | — | recorded; also above 10 |
| cli process during the converter stages | 1.89 GiB | **0.13 GiB** | — | the release works |
| Peak scratch / output | 59.50 / 13.83 GB | 59.50 / 13.83 GB | ≤ 60 / ≤ 15.23 GB | within |

Per stage on fold 3 (tree / largest, GiB): dump 4.68 / 0.62; build 9.65 /
9.65; c1a 10.34 / 10.20 (all anonymous; fold 2's 9.16 for the same child was
an earlier sample); dotvbyte 11.37 / 11.24.

**F4 memory after both changes: FAIL on the 10 GB bar by every reading
(tree 11.37, largest process 11.24, anonymous-only 10.32 GiB); below the
12 GB kill line by every reading (fold 1 read 12.11 on the tree).** What is
left is inside the Rust tools, not changed here: `c1a_mmap_index` loads the
stock index into 10.2 GiB of anonymous memory, and
`mmap_io::convert_f16_dir_to_dotvbyte` maps the three f16 forward files whole
(6.29 GiB of page cache counted as RSS) beside 4.95 GiB of its own.

### F2 on fold 2 — the "one fold rebuild" of doc 10 §8 (2026-10-04 21:50–22:09Z)

`data/eval_results/delta_ingest_foldin_20261004.json` key `F2_fold2`; same
harness, queries, fixture, Reading A and conventions as the 2026-10-03 run;
preview root `/home/vscode/work/delta_ingest/foldin/f2_fold2/preview_root`
(origin `fold:0:2`); shared lock, code f44b4346, complete (120 + 100 + 240 leg
queries, 240 pipeline queries), healthy; a 3-query smoke with `--lock none`
ran first (not read).

**Every number equals the fold-1 run: F2 = FAIL as computed, on Q-b, QD,
shard level (0.9780 vs 0.9820).** Q-a PASS (federated 0.9992 / 0.9980), Q-b
QT PASS (shard-own 0.9892 vs 0.9808), Q-c PASS (Δ −0.00003, CI [−0.00008,
0.00000], 236/240 final top-10 identical), Q-d PASS (0 leaks, still on a
fixture without deletions). Query by query, fold 2's shard-own top-10 is the
same ordered list as fold 1's on 120/120 QT and 100/100 QD: the two builds
differ in bytes (posting lists) and not in any measured result, so a rebuild
of the same input is not a second draw.

Read from the saved rows of both runs (no new measurement):

| Set | Queries whose shard-own top-10 set differs F vs L | Docs only in L | Docs only in F | of those, delta (folded) docs | Missed by F / by L vs the pooled top-10 |
|---|---|---|---|---|---|
| QT (120) | 11 | 13 | 13 | 0 | 6 / 9 |
| QD (100) | 19 | 22 | 22 | 0 | 15 / 8 |

No folded doc is involved in any difference (no folded doc is in any L
shard-own top-10 of these sets); every swapped doc is a base doc, and scores
of docs present in both arms are equal on 2,165/2,165. Against the top-10 of
the two arms pooled by score, F misses 21 docs and L misses 17 over the 220
queries. Reading (inference): the fold re-clusters the base docs, and the
approximate search then misses a different handful of base docs — the same
kind of difference as build vs build (m_set 0.9908 / 0.985), not a loss tied
to the folded docs.

**Doc 10 §8, as written:** "F2 fails Q-a or Q-b after one fold rebuild with a
corrected harness" is a track-kill condition. With Q-b required at shard
level (the harness reading fixed before the first run) that condition is now
met; with Q-b read on the federated leg it is not (every bar passes on both
folds). Which level binds was owner question 1 ("Open for the owner", above);
no closure was executed and nothing is published.

**Owner decision 2026-10-04 (after both runs were read; doc 10 addendum of
that date): the federated level is binding for Q-b, the shard level is
not.** Re-read from the saved rows with `--q-b-level federated`
(`delta_ingest_foldin_20261003.json` key `F2_qb_federated`,
`delta_ingest_foldin_20261004.json` key `F2_fold2_qb_federated`): **F2 =
PASS on fold 1 and on fold 2**; the §8 kill condition is not met. The
shard-own numbers above stand as measured. Owner question 1 is closed;
questions 2 (which number is F4's "peak RSS") and 3 (a deletions fixture for
Q-d) stay open.

## 2026-10-05 — owner amendment of the F4 memory bar

Doc 10 addendum 2026-10-05 (taken after folds 1–3 were measured): peak RSS ≤
**11.5 GB**, read on the process-tree VmRSS + VmSwap as the recorder samples
it. This closes owner question 2 (which number is "peak RSS"). No new
measurement; recomputed from the stored records
(`delta_ingest_foldin_20261004.json` key `F4_amended_bar_20261005`):

| Build | Peak tree VmRSS + swap | Frozen bar 10 GB | Amended bar 11.5 GB |
|---|---|---|---|
| Fold 1 (2026-10-03, before the memory changes) | 12.11 GiB | FAIL | FAIL |
| Fold 2 (dump change only) | 13.13 GiB | FAIL | FAIL |
| Fold 3 (current code) | 11.37 GiB | FAIL | **PASS** (margin 0.13 GiB) |

The 12 GB kill line of doc 10 §8 is unchanged. With wall, scratch and output
already within, fold 3's build record is within every F4 bar as amended; the
publish stage and the duty cycle are still unmeasured, so F4 as a whole is
not read. Owner question 3 (a deletions fixture for Q-d) stays open as work,
not as a decision (`docs/delta_ingest/12_NEXT_SESSION_2026-10-05.md` §4).


## 2026-10-08 — trigger code + F1

**Built** (commit 879a5aa3): `spike/delta_ingest/trigger.py`, called by
`generation.publish()` after `generations.json` is written. Per base shard it
records (a) live delta docs routed to s ÷ base docs of s, (d) masked base docs
routed to s ÷ base docs of s (distinct ordinals of the livedocs bitset; ledger
reading when no ordinal arrays are given), (c) age of the oldest live delta
doc routed to s, the dials `SFU_DELTA_FOLDIN_FRAC` / `_DEAD_FRAC` / `_MAX_AGE`
(days; unset = OFF, so nothing fires by default) and the 24 h hysteresis after
a fold publish. Output: `<delta_root>/trigger.json` (latest, atomic) +
`trigger_log.jsonl` (one line per publish). It only reports; it never builds or
publishes a fold, serving never reads it, and nothing under `src/` changed.
**(b) tax is NOT implemented** (needs F0): `tax_ms` is null and
`SFU_DELTA_FOLDIN_TAX_MS` is ignored. Readings of (a)/(c)/(d) — including the
post-fold reading (folded docs leave (a); only copies dead in s′ count for
(d)) — are in doc 10's addendum 2026-10-08, written before the F1 run. Unit
tests: `scripts/tests/test_foldin_trigger.py` (7, tmp trees: counts without
ordinals, (d) vs a direct bitset decode, thresholds and unset = OFF,
hysteresis at 1 h / 25 h, post-fold readings, old ledger without route
columns skipped, a trigger error recorded and not raised).

**F1 RUN 2026-10-08 00:52–00:53Z: PASS — identical on 20 / 20 checkpoints on
each root** (bar: 100 % of 20). Harness `scripts/experiments/eval_delta_ingest_trigger.py`
(no lock, no index loaded); results `data/eval_results/delta_ingest_foldin_f1_20261008.json`
key `F1`; log `/home/vscode/work/delta_ingest/foldin/f1/f1_20261008_run2.log`.

- Roots: copies under `/home/vscode/work/delta_ingest/foldin/f1/` of
  `fixture_n8` (the F-fixture) and `inplace_update/m4/root_n8` (route columns
  backfilled on the copy). Each copy = the ledger (SQLite backup from a
  read-only connection) + each generation's `generation.json`; the originals'
  ledger and WAL size + mtime are unchanged after the run on both.
- Each checkpoint = 400 new ids, 600 base-id updates, 300 + ~60 base deletions
  (some of earlier-updated ids), 120 deletions of live delta ids, 40 re-adds
  of deleted ids, then `publish()` with the full local ordinal arrays
  (`/var/tmp/sfu_delta_C_20260929/ords`, 150,413,098 rows) so a bitset is
  written. Seed 20261008.
- Brute force (independent code path): every `docs` row routed with
  `shard_spool.shard_id`; the `.liv` decoded (crc and popcount checked), set
  ordinals mapped to W-ids via `wids.npy` and routed; base docs from the
  manifest file. Compared per shard: base docs, live numerator, masked
  numerator, `oldest_staged_at`; plus `trigger.json` on disk = the returned
  record and no shard fires with the dials unset.
- At checkpoint 20 (fixture_n8 / root_n8): 177,566 / 177,564 live delta docs,
  17,998 bits set; shard 0: (a) 22,251 / 22,288 of 18,799,322 = 0.118 % /
  0.119 %, (d) 2,219 / 2,290 = 0.0118 % / 0.0122 %, (c) 8.66 days (the
  fixture's oldest doc, staged 2026-09-29). Publish with trigger ≤ 1.46 s per
  checkpoint on these roots.
- A negative control (trigger patched to drop tombstones from (d); 1
  checkpoint, not recorded in the results file) reads FAIL, so the comparison
  can see a miscount.
- **Harness defect, fixed and re-run once:** run 1 (00:50–00:51Z, key
  `F1_run1`, also 20 / 20 identical on both roots) wrote `source_unchanged:
  false` because its source check included the `-shm` file, which SQLite
  readers write read marks into even with `mode=ro`. Run 1's own signature
  shows the ledger and WAL unchanged. The check now covers the ledger and WAL
  only. Both runs record `git_head` 879a5aa3; the harness was committed after
  them (e1825fc1), and the only change between runs is that check.

**Not covered by F1:** the post-fold (d)/(a) branch (no fold is published on
the copies; unit tests only), the (b) tax, and real churn levels (the
checkpoints reach about 0.1 % of a shard, far below any candidate threshold —
F1 tests exactness, not the threshold level). Doc 10 §8's parameter kill for
(d) ("if F1 cannot compute per-shard dead counts exactly") is not met.

## 2026-10-08 — F3/F8 harness built and queued (NOT RUN when written)

- **Operator prefault** (doc 10 §4): `foldin.publish_fold` now reads the fold's
  served dir into the page cache before the manifest repoint (`prefault_dir`,
  recorded under `plan.prefault`; `cli.py publish-fold --no-prefault` skips it).
  Commit c5998e72, tests in `scripts/tests/test_foldin_guard.py`.
  IMPLEMENTED, EFFICACY UNMEASURED — F8 is its measurement.
- **Harness** `scripts/experiments/eval_delta_ingest_foldin_f3f8.py` (commit
  ed061e64, tests `scripts/tests/test_foldin_f3f8_harness.py`); arm
  construction and rep design fixed in doc 10 addendum "2026-10-08 — F3/F8
  implementation reading" before any run: F3 arms n0 / n0x / L (`root_n8c` +
  L3–L5) / F (fixture copy compacted `--no-seismic` + `publish-fold` fold 1);
  F8 on a fixture copy with fold 2, rep 1 = the real `publish-fold`, reps 2–5
  restore pre/post state files.
- **Queued**: `/home/vscode/work/delta_ingest/foldin/f3f8/run_f3f8.sh`
  (`nohup setsid`), waits for the deletions-fixture F2 result (or a `GO` file
  in that dir), then holds the latency lock exclusively for setup → smokes →
  F8 → F3 → summarize; `F3F8_DONE` holds its exit status. Results will land in
  `data/eval_results/delta_ingest_foldin_f3f8_<YYYYMMDD>.json` (keys `setup`,
  `F8`, `F3`). Expected wall *est.* 2.5–3 h after the lock.

## 2026-10-08 — F8 and F3 RESULTS: both FAIL on one bar each

Run 2026-10-08 01:59–03:28Z under the exclusive lock (quiet gate passed,
no swap growth, healthy, log scan clean), code snapshot 46b85c0c, launcher
`/home/vscode/work/delta_ingest/foldin/f3f8/run_f3f8.sh`, results
`data/eval_results/delta_ingest_foldin_f3f8_20261008.json` keys `setup`, `F8`,
`F3` (raw per-query timings inside). Two launches before it stopped at setup
on harness defects, nothing measured: `No module named lib` (sys.path,
85918e64) and a false G3 alarm (JSON lists vs tuples, 817/817 "changed";
tuple compare 0 changed; 46b85c0c). The G3 baseline at the end of the run
reads unchanged.

**F8 (reload after a fold publish): FAIL** — reload bar PASS, first-query bar FAIL.
- `reload()` wall 1.223 / 0.559 / 0.552 / 0.582 / 0.546 s (max 1.22 vs ≤ 15 s):
  **PASS**. Backend reopen adds 1.35–3.31 s.
- First query after the reload, ms: **22,333** (rep 1, the real
  `publish-fold`; 1,861 major faults on that query), 5,718, 4,684, 3,684,
  3,838 → p50 **4,683.6 ms vs warm p50 2,158.0 ms = 2.17×** (bar ≤ 2×):
  **FAIL**. Same-topic paired ratio median 1.83 (recorded, not the bar).
- `publish-fold` CLI 15.1 s including the operator prefault of the 5.55 GB
  fold dir (9.8 s cold, 0.45–1.6 s warm). The prefault did not prevent rep
  1's cold first query: the major faults came from pages outside the
  prefaulted fold dir (not attributed further).
- Controls (reload with no change, backend kept): first query 2,769 / 2,692
  ms. Rollback reloads (back to pre-fold) behave like the fold reloads
  (first query 3,466–5,289 ms) — the cost follows the backend drop and
  reopen, not the fold's bytes. For comparison M5 (2026-09-30) passed at
  ≤ 1.82× on generation publishes.

**F3 (latency returns to n0): FAIL** — ratio bar PASS, CI bar FAIL.
- Arms (doc 10 addendum 2026-10-08): n0, n0x (n0 + L4), L (`root_n8c` + L3–L5),
  F (fold 1 at position 0 + the delta compacted `--no-seismic` into one
  sections-only generation, + L3–L5); 2 measured passes × 120 topics.
- p50 ratio F / n0 = **1.014** (≤ 1.05): PASS. Paired Δ(F, n0) median
  **+5.76 ms, CI 0.37–13.57** — upper bound 13.57 > **8.0 ms**: **FAIL**.
- Recorded: Δ(L, F) −1.5 ms (CI −8.76 to +6.41, no measurable difference
  between the live delta and the fold); Δ(F, n0x) +4.8 ms (CI −2.55 to
  +12.33); Δ(L, n0) +6.6 ms (CI −1.36 to +14.67); Δ(n0x, n0) −0.3 ms (CI
  −9.43 to +5.04, the noise scale of this host).
- Reading (mine, not a bar): what is left after the fold is the sections
  tier — the one consolidated generation with 10 tantivy sections and 10
  abstract stores, which doc 10 §4 says never folds. F0 (queued next)
  measures how that cost grows with its size.

Doc 10 consequences: neither failure is a §8 kill criterion. §9 promotion of
fold-in needs F3 and F8 PASS, so fold-in is **not promotable** as measured.
No bar re-cut, no re-run (both are model results, both runs healthy).

## 2026-10-08 — F5 crash-safety harness built and queued (NOT RUN when written)

**Status: IMPLEMENTED, EFFICACY UNMEASURED** — no F5 trial of record has run.
Readings: doc 10 addendum "2026-10-08 — F5 implementation readings".

- **Three crash-safety defects found by review and fixed before any trial**
  (commit 60ba0fc1): (1) `publish()` rewrote `<delta_root>/shard_manifest.json`
  in place ahead of `generations.json`; a kill between them paired the new
  manifest with the old masks (on `fixture_n8` every fold member double-served:
  the negative control in `scripts/tests/test_foldin_f5_crash.py` reads 6/6
  docs kept twice). Now one stamped manifest file per publish, with
  `generations.json` as the single commit point. (2) `publish-fold` could not
  be re-run after a kill between compose and the ledger commit; an identical
  composed manifest is now reused. (3) `fold-build` could not be re-run after a
  kill between `make_fold_dir` and its ledger row; fold numbers now skip orphan
  dirs. 158 delta/fold-in tests pass after the change.
- **Harness** `scripts/experiments/eval_delta_ingest_foldin_f5.py`: a 1M-doc
  reduced fixture builder, calibration (fold wall W, m_set, clean Q-a), 50
  process-group SIGKILLs over the fold wall and 10 inside `publish-fold` (full
  shard-0 fold 1, copy of `fixture_n8`), a served-state checker (digest +
  per-doc origin inspection + 200 own-id lookups), G3 baseline, re-run + Q-a.
  Resumable rows file.
- **Smoke** (30,000-doc base, 10 queries per set, 3 fold kills + 2 publish
  kills, `/home/vscode/work/delta_ingest/foldin/f5_smoke/`): plumbing only, 5/5.
  Fold kills landed in `build`, all read PRE; publish kills landed before the
  ledger commit (read PRE) and after `generations.json` (read POST). Own-vector
  lookups at k = 200 missed 51/200 (the docs rank 384–778 on their own vector);
  at k = 1000 they miss 2 (pre) and 0 (post), the same docs in every trial.
- **Queued:** `/home/vscode/work/delta_ingest/foldin/f5/run_f5.sh` waits for
  `f3f8/F3F8_DONE` AND `f0/F0_DONE`, then runs under the SHARED latency lock
  (wall *est.* ~6.5 h) and writes `f5/F5_DONE`; results
  `data/eval_results/delta_ingest_foldin_f5_<YYYYMMDD>.json` key `F5`.

## 2026-10-08 — deletions fixture fold (Q-d)

Doc 12 §4 item 1; pre-run reading in doc 10 addendum 2026-10-08 ("the
deletions fixture for Q-d", commit c4cdd723, written before the build).
Results `data/eval_results/delta_ingest_foldin_20261008.json` keys
`F4_build_fold_del`, `F2_fold_del`, and `fold_del_derived_20261008`
(the numbers below that are not in the harness keys, derived from the
raw outputs). Logs and rows: `/home/vscode/work/delta_ingest/foldin_del/`.

**Fixture** `/home/vscode/work/delta_ingest/foldin/fixture_n8_del`
(`scripts/experiments/delta_ingest_foldin_del_fixture.py`, 9.2 min, record
`build_fixture.json`): a copy of `fixture_n8` + the Stage-0 encoded subsample,
through `IngestLedger.delete`/`stage` → `freeze_buffer` → `publish` with the
base ordinal arrays (livedocs bitset, popcount 1,139,757). **1,131,292
tombstones** (every one routed to shard 0 and in base), **8,465 superseded
base docs**, **20,112 superseded delta docs** (every corpus (b) doc routed to
shard 0 is also a Stage-0 upsert, so its g0001–g0008 copy is now stale) and
3,578 new docs, all in the new generation g0009; 32,155 live delta docs routed
to shard 0. NEW fold (different delta), fold root
`/home/vscode/work/delta_ingest/foldin_del`, fold 1: 17,659,565 base rows kept,
1,139,757 dropped, 32,155 added → **17,691,720 docs** (as predicted before the
build); 0 tokens appended to the pinned map; protected-tree baseline unchanged
(817 files). The fold code already dropped tombstoned ids (`fold_plan`;
covered by `scripts/tests/test_foldin_e2e.py`), so no code change was needed.

### F4 — build record (exclusive lock 00:57–01:21Z, quiet host; publish stage NOT included)

| Measure | Result | Bar (amended 2026-10-05) | Reads |
|---|---|---|---|
| Wall | 1,420 s = 23.7 min (dump 145 s, build 1,123 s, c1a 39 s, dotvbyte 101 s) | ≤ 90 min | within |
| Peak tree VmRSS + VmSwap | **10.86 GiB** (swap 0); largest process 10.59 (converter, 4.69 anonymous) | ≤ 11.5 (frozen 10) | within the amended bar (margin 0.64); over the frozen 10 GB bar |
| Peak scratch | 55.99 GB | ≤ 60 GB | within (margin 4.0) |
| Output (f16 + dv-v2) | 13.08 GB | ≤ 14.31 GB (1.10 × 13.83 × 17,691,720 / 18,799,322) | within |

Per-stage tree peaks from the timeline (GiB, this fold vs fold 3): dump 6.13
vs 4.68 (each of the 8 workers holds the 1.16 M-id drop set), build 9.39 vs
9.65, c1a 9.62 vs 10.34, dotvbyte 10.86 vs 11.37. The 6 % smaller shard lowers
the peak; the peak is still the converter's last samples.

### F2 — F (s′ + masks) vs L (base 0 + 9 delta generations + livedocs), 01:23–01:45Z, shared lock

3-query smoke first (`--limit 3 --lock none`, healthy). Full run complete
(120 + 100 + 240 leg queries, 240 pipeline queries), healthy (no failure
signature, no swap, self-check equal to `search_encoded`), code 312b42b7.

| Bar | QT (120) | QD (100) | Verdict |
|---|---|---|---|
| **Q-a** federated overlap@10(F, L) ≥ 0.985 / 0.980 | **0.9983** (118/120 identical) | **1.0000** (100/100) | PASS (also Reading B) |
| shard-own overlap@10(F, L), recorded | 0.9708 (90/120 identical, min 0.7) | 0.9580 (66/100 identical, min 0.7) | neither clears A |
| **Q-b** (federated, owner level) ≥ 0.9808 / 0.9820 | federated 0.9983; shard-own 0.9708 | federated 1.0000; shard-own 0.9580 | PASS at federated level; shard-own does not clear (not binding) |
| **Q-c** NDCG@10 final, F − L | F 0.72225, L 0.72265, Δ −0.0004, CI95 [−0.0012, +0.0001]; 235/240 final top-10 identical | | PASS (CI contains 0) |
| **Q-d** mask leaks, 460 leg queries + 240 fused/final lists | **0** (L control 0); masks removed 96,283 of 1,564,000 raw candidates on L and 184,251 on F | | **PASS — first run with real tombstones and superseded copies** |

**Verdict: F2 = PASS (Q-a Reading A, Q-b federated).** Shard-own overlap is
lower than on fold 1 (0.9708 / 0.9580 vs 0.9892 / 0.9780): the 148 docs that
enter shard 0's own top-10 only under F are all base docs, none a fold member,
the same pattern as fold 1, here larger because the rebuilt shard lost 6 % of
its docs. At the shard level, which no longer binds, Q-b would read FAIL on
both sets.

## 2026-10-08 — F0 RESULT: FAIL (sections tier flagged, doc 10 §8)

Run 2026-10-08: g1M build 03:28–04:10Z (shared lock, 2,493 s, tree peak
19.75 GiB under the fixture-only 40 GB cap; 1,000,000 docs staged, 0
refused), measurement 04:14–05:05Z (exclusive lock, quiet gate passed, no
swap growth, healthy), code snapshot 54318c08, harness
`scripts/experiments/eval_delta_ingest_foldin_f0.py`, readings = doc 10
addendum "2026-10-08 — F0 implementation readings" (written before the
build), results `data/eval_results/delta_ingest_foldin_f0_20261008.json` key
`F0` (raw per-query rows inside).

- Arms (2 measured passes × 120 topics): n0x p50 2,132.3 ms, x1 (`root_n1`,
  160,347 docs + L3–L5) 2,144.0 ms, xg1M (`root_g1M`, 1,000,000 docs in one
  generation + L3–L5) 2,150.3 ms.
- **Bar Δ(g1M) − Δ(n1): median +17.93 ms, CI 10.60–23.20 vs ≤ 8.0 (CI
  upper) → FAIL.** Δ(x1, n0x) +6.6 ms (CI −1.12 to +16.96); Δ(xg1M, n0x)
  +24.1 ms (CI 16.94–33.41).
- **Coefficient c** (for (b)'s model T = a + b·G + c·D): **21.35 ms per
  million delta docs** (CI 12.62–27.63), over 0.8397 M added docs. Upper
  bound for the post-fold sections tier: g1M keeps its delta SEISMIC shard.
- Leg medians, xg1M − x1 (ms; attribution, not additive): BM25F delta
  sections +15.0, delta SEISMIC shard sum +19.9 (wall share via traverse
  +10.0), delta masks +3.45, BM25F parse/merge/masks +3.68, delta abstract
  hydration +0.18.
- Reading (mine, not a bar): the BM25F delta-sections leg alone grows by
  +15 ms, so dropping the delta SEISMIC shard (the consolidated tier of doc
  10 §4) would not obviously bring the bar under 8 ms. Corpus caveats from
  the addendum: half the docs sit in one base section; all route to shard 0.

Doc 10 consequences: §8 "Sections tier FLAGGED, not killed — the
consolidated generation needs its own split/fold design (a new
pre-registration)". F7's tax check now has c; with the sections tier never
folding, its D only grows, which is the premise of
`docs/delta_ingest/13_FULL_REBUILD_TRIGGER_PREREGISTRATION.md`.

## 2026-10-08/09 — F5 RESULT: PASS 60 / 60

Harness `scripts/experiments/eval_delta_ingest_foldin_f5.py` (readings = doc 10
addendum "F5 implementation readings", written before any trial), results
`data/eval_results/delta_ingest_foldin_f5_20261008.json` key `F5` (final,
2026-10-09 19:44Z, code 2fd0db84; per-trial rows in
`/home/vscode/work/delta_ingest/foldin/f5/rows.json`), shared lock, seed
20261008.

- **50 / 50 fold-build kills PASS** on the 1,000,000-doc reduced fixture
  (fold wall W = 199.8 s; clean-fold Q-a 1.000 / 1.000, so (iii) readable).
  Stages hit: before mkdir, plan/token map, dump, build, dotvbyte.
- **10 / 10 `publish-fold` kills PASS** on a copy of `fixture_n8` with fold 1
  of the full shard 0 (reference publish 12.07 s). Stages hit: before the
  ledger commit (prefault / compose / baseline), after the ledger commit +
  new manifest, after `generations.json` + trigger — the middle one is the
  window where the pre-60ba0fc1 in-place manifest rewrite tore state.
- Every trial: (i) served state exactly pre- or post-fold (0 NEITHER), (ii)
  G3 baseline unchanged, (iii) the re-run completes and passes Q-a.
  Redraws (kill time after the run had already finished): fold-02, fold-20,
  pub-00 ×3, pub-02, pub-03, pub-06 ×2, pub-08.
- **Run split over three invocations by host pauses** (inferred, not
  verified: the wall clock jumped 2026-10-08 07:41Z → 10-09 04:59Z during
  fold-29 and 10-09 06:50Z → 19:38Z during pub-00, while the tools' stage
  timers advanced minutes). Each time the harness stopped cleanly on its
  wall-clock deadline. Resume fixes (2fd0db84) before continuing: an old
  deadline stop no longer skips the publish phase, and skipped tags consume
  their recorded draws, so the kill times are exactly the single-run seeded
  sequence (checked: recorded kills == draws[:32] at the first resume). The
  first invocation's summary is kept as key `F5_interrupted_20261008`.

Doc 10: F5 PASS. Fold-in promotion (§9) is still blocked by F3 and F8 FAIL.

## 2026-10-09 — F7: trigger values per profile — desktop_gpu and server FLAGGED

Computation, no index, no lock. Script
`scripts/experiments/eval_delta_ingest_foldin_f7.py` (reads its inputs from
the recorded F4, F8, F0 and `09` R1 results), readings = doc 10 addendum
"2026-10-09 — F7 implementation reading" (committed 1eb47eb9 before the
computation), results `data/eval_results/delta_ingest_foldin_f7_20261009.json`
key `F7`.

- Inputs: fold wall 1,431.2 s + publish 15.1 s per shard → Σ 8 shards
  3.21 h; Δ(x1, n0x) 6.60 ms, c 21.354 ms per M delta docs (CI 12.62–27.63),
  b 1.308 ms/gen; churn as coded 87,692 upserts/day/shard.
- Duty cycle (as coded): (a) = 0.02 → period 4.29 days, duty **3.1 %**
  (0.05: 1.3 %, 0.10: 0.6 %, 0.20: 0.3 %) — every candidate is far under
  25 %, so the rule picks **(a) = 0.02**. (d) reached at that fire 1.57 % →
  **(d) = 0.05**; (c)-driven duty 0.45 % → **(c) = 30 days**; **(b) = 8 ms**.
- Tax at (a) = 0.02's first fold moment (D = 3.008 M docs incl. the
  sections tier, G = G_max = 8): **T = 76.6 ms > 8 × 8 = 64 ms → FLAGGED,
  no default ships ON** for `desktop_gpu` and `server` (server uses the
  desktop wall, *est.*). `laptop`: NOT APPLICABLE (fold disabled for 18.8 M-
  doc shards, doc 10 §7).
- Recorded, no verdict: at c's CI bounds T = 51.7 / 94.4 ms (the low bound
  would pass); at G_max 1 T = 67.4 vs 8 ms, at G_max 4 T = 71.3 vs 32 ms;
  the k-th fold round T = 76.6 / 140.8 / 269.3 ms for k = 1 / 2 / 4 (the
  sections tier keeps every folded doc). The text-filtered stream gives the
  same (a), (d), (c) and the same T (D at a fold moment depends on (a), not on
  the rate).
- Reading (mine): folding is cheap enough (duty ≤ 3 %); what flags the
  profile is the sections tier's tax, the same cause as F0 and F3 — doc 13.

## 2026-10-09 — F6 RESULT: PASS (repeated folds do not compound drift)

Readings = doc 10 addendum "2026-10-09 — F6 implementation reading"
(3995848b, before any build). Script `scripts/experiments/eval_delta_ingest_foldin_f6.py`
(setup + post), fold/preview/F2 through `scripts/experiments/eval_delta_ingest_foldin.py`,
chain `/home/vscode/work/delta_ingest/foldin_f6/chain_f6.sh`, results
`data/eval_results/delta_ingest_foldin_f6_20261009.json` keys
`F4_build_fold2_of_s_prime`, `F2_fold2_of_s_prime`, `F6_overlaps`.

- **Live state:** `fixture_n8` copy with fold 1 published (s′ at position 0,
  20,112 members marked `fold:0:1`), then the Stage-0 Q1 batch (1,131,292
  tombstones; 32,155 upserts re-updating all 20,112 fold-1 members,
  superseding 8,465 base docs, adding 3,578) → 17 served shards.
- **Fold 2 of s′** (ledger fold 4) built from fold 1's own `fold.mmap`:
  wall 24.7 min, tree peak 10.85 GiB, scratch 55.99 GB, output 13.08 GB
  (shared lock; recorded, not an F4 read); 17,691,720 docs.
- **F2 at the owner's readings (shared lock, complete, healthy):** Q-a
  federated overlap@10 **0.9975 / 0.9980** (QT / QD; bars 0.985 / 0.980)
  PASS; Q-b federated **PASS** (thresholds 0.9808 / 0.982; shard-own
  0.9733 / 0.9540 recorded, not binding). **F6 PASS.** Recorded beside it:
  Q-c ΔNDCG@10 −0.0004 (CI −0.0012 to +0.0001) PASS, 236/240 identical
  final top-10; Q-d 0 leaks over 460 queries.
- **Compounding drift, recorded:** fold 2 of s′ vs the deletions fold built
  from the twin (same doc set): **identical federated top-10 on 220 / 220
  queries, shard-own overlap 1.000 / 1.000**. Base-only overlap@10 vs A0:
  0.9704 / 0.9573 for both folds — the same numbers to four places.
- **One harness defect fixed once** (a259914f): the L-arm health check
  required the base shard at position s; F6's L serves s′ there by design.
  The smoke stopped on it before any measurement.

Doc 10: F6 PASS. Scoreboard F1, F2, F4 (amended), F5, F6 PASS; F0, F3, F8
FAIL; F7 FLAGGED — fold-in not promotable under §9.

