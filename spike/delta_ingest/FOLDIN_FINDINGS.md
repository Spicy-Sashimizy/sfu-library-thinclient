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
"2026-10-04" below). F4 build record over its 10 GB memory bar on both
folds. F1, F3, F5, F6, F8 NOT RUN. Nothing was published.**

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
