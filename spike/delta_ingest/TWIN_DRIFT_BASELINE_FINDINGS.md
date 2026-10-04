# M9 follow-up — twin-rebuild build-vs-build drift baseline

**Status:** ACTIVE

Item B of the 2026-10-01 delta-ingest second-wave dispatch; full-shard run
by agent DRIFT of the third wave (2026-10-01 15:27–16:45Z). Harness:
`scripts/experiments/eval_delta_ingest_twin_drift_baseline.py`. Results:
`data/eval_results/delta_ingest_twin_drift_baseline_20261001.json` (3M-doc
prefix, PARTIAL) and
`data/eval_results/delta_ingest_twin_drift_baseline_full_20261001.json`
(FULL shard, 18.8M docs — **the result of record**, see §"Full-shard run").
Work dir (local disk): `/home/vscode/work/delta_ingest/twin_drift/`.

**Bottom line (2026-10-01, full shard):** verdict **NOISE** by the
pre-registered rule (m = 0.985 ≤ 0.9915). A rebuild with the twin/served
`input_token_to_id_map` pinned matches the SERVED shard 0 at overlap@10
**1.000 / 1.000** (220/220 identical top-10). M9's FAIL is explained by
random component ids. It is not a fidelity loss of the twin route.

## Question

M9 (`eval_delta_ingest_twin_rebuild.py`, 2026-09-29) rebuilt served shard 0
from its f16 twin and FAILED its pre-registered parity bar: overlap@10
rebuilt-vs-served **0.9858** (120 topics) / **0.9870** (100 diverse) against
0.99 on each set. Is that gap just SEISMIC build non-determinism?

## Pre-run note (written 2026-10-01 04:20Z, before any full-scale build or comparison)

### How M9 ran (from its script, logs and results JSON)

- Input: `/var/tmp/sfu_delta_D_20260929/twin_shard0.jsonl` (38.9 GB,
  18,799,322 lines, twin row order, values = exact decimal of the stored f16).
- Build: `seismic.SeismicIndex.build(jsonl, num_threads=8, n_postings=3500,
  centroid_fraction=0.1, min_cluster_size=2, summary_energy=0.4,
  max_fraction=1.5, doc_cut=15)` in a child process; 1,764.4 s build + 98.9 s
  save, peak RSS 8.2 GB. No seed argument exists in the API.
- Then `c1a_mmap_index` (f16 mmap dir) and `convert_f16_to_dotvbyte
  --value-scale perdoc` (dv-v2 dir).
- Parity: `MmapSeismicIndex` on the rebuilt dv-v2 dir vs the served
  `global_shard0of8.dotvbyte.e5.v2.mmap`; queries = 120 topics
  (`data/sfu_eval_queries.json`) + first 100 distinct diverse paraphrases;
  `encode_splade(q, "models/splade_onnx_fp16")`, top-64 terms; k=200,
  query_cut=len(terms), heap_factor=0.8, `SFU_SEISMIC_PREFLOOR=2`; overlap@10
  on doc-id strings. 0.9858 is the 120-topic set (min 0.8, 106/120 identical),
  0.9870 the 100-diverse set (min 0.9, 87/100 identical).
- Build 1 still exists on disk: stock `rebuilt_shard0.index.seismic`
  (8.28 GB), `rebuilt_shard0.mmap/`, `rebuilt_shard0.dotvbyte.v2.mmap/`. So
  ONE further build suffices; two are not needed.
- The installed `seismic` .so (sha256 6263…d6c6, mtime 2026-08-10) and the
  `c1a_mmap_index` / `convert_f16_to_dotvbyte` binaries (mtime 2026-07-10)
  are unchanged since M9 ran; the local venv mirror carries the same .so.

### Is the build seeded / deterministic? (code reading, fork `main` 2c4d863)

- k-means centroid choice is seeded: `StdRng::seed_from_u64(1142)` in
  `do_random_kmeans_on_docids_ii_approx_dot_product` (`src/utils.rs`).
- Parallel steps (`par_iter().map().collect()` for posting-list build and
  summaries) collect in order; global-threshold pruning (`k_largest_by`) is
  sequential. Thread scheduling is not a source of output variation as far as
  the code shows.
- **But the component ids are random per build.** `JsonSparseVector.vector`
  is a `std::collections::HashMap<String, f32>` (`src/json_utils.rs`) with the
  default per-process `RandomState`; `extract_jsonl` iterates it, and
  `build_token_map` assigns component ids in first-seen order of that
  iteration (`src/inverted_index_wrapper.rs`). So every build from jsonl
  relabels the vocabulary at random. Relabeling changes the order in which
  equal-valued entries reach `k_largest_by` and the per-term cap (values are
  f16 with only ~5.9k distinct bit patterns, so ties at the pruning threshold
  are common), which changes posting-list membership, k-means inputs, and the
  f32 summation order of scores. M9 already saw `token_to_id_map.bin` differ in
  id order and `posting_lists.bin` differ by +35,112 bytes.
- Toy confirmation (2026-10-01 04:14–04:19Z, a 2,000-doc prefix of the same
  jsonl, 1 thread, 2.1 s per build, light work under the lock, scratch only):
  two same-parameter builds gave different stock files (12,182,289 vs
  12,183,158 bytes), top-10 identical but top-200 identical on only 109/120 and
  89/100 queries, score differences up to 1.9e-6; the SAME file loaded in two
  processes gave identical results 120/120 + 100/100 at top-200 (search is
  deterministic). Two builds given the same `input_token_to_id_map` gave
  identical top-200 lists and scores on all 220 queries, and a build given
  build 1's map reproduced build 1's results exactly. On 2,000 docs the noise
  does not reach top-10; at 18.8M docs, unknown — that is what this run
  measures.

### Method (Phase 2)

- Arm A (primary, the brief): build 2 = same jsonl, same params, 8 threads,
  saved to `/home/vscode/work/delta_ingest/twin_drift/rebuilt2_shard0`. Queries
  encoded ONCE (`encode` subcommand, 2026-10-01 04:13Z, sha256 db648ae5…,
  34–64 terms per query) and reused by every arm.
- Primary metric: overlap@10 build 2 vs build 1 on the **stock** f16
  `SeismicIndex` (in memory), per query; mean, min, distribution
  (histogram), identical top-10 (ordered / set), identical top-200, overlap@200,
  per set. **Deviation from M9, stated before the run:** M9 compared dv-v2
  `MmapSeismicIndex` outputs; the stock level isolates the build itself and
  skips c1a + dotvbyte (~10 min). Links back to M9's level: both builds are
  also compared with the ORIGINAL build's f16 c1a dir (the twin,
  `global_shard0of8.mmap`, read-only, `MmapSeismicIndex`); and the M9-exact
  dv-v2 vs dv-v2 comparison (c1a + dotvbyte on build 2) runs last if ≥ 15 min
  remain.
- Control: build 1 queried twice in one process (search noise floor); the toy
  showed cross-process search identity.
- Arm B (supplementary, runs only if ≥ 38 min remain after arm A): rebuild
  with `input_token_to_id_map` = the twin's `token_to_id_map.bin` (the original
  served build's component ids), compared with the twin f16 dir. Tests whether
  pinning the vocabulary makes the twin route exact.
- Decision rule (m = min over the two sets of mean overlap@10, build 2 vs
  build 1, arm A):
  - m ≥ 0.998 and identical top-10 on ≥ 99% of queries → builds reproducible;
    M9's gap is NOT build noise → real fidelity loss of the twin route.
  - m ≤ 0.9915 (within ~0.005 of M9's 0.9858 / 0.9870, or lower) → NOISE: M9's
    gap is build-vs-build drift; the 0.99 bar needs a noise-aware restatement
    (recommended, not changed).
  - otherwise MIXED (part noise, part real loss; both numbers reported).
  - Prediction from the code reading and the toy (stated so it can be wrong):
    NOISE, m near M9's ~0.986.
- Arm choice and fallback (pre-committed): FULL iff the shared latency lock is
  acquired (or abandoned at 06:15Z because the exclusive holder overran) by
  05:50Z. Otherwise PREFIX: the first 3,000,000 jsonl lines built TWICE with
  the same params and compared to each other, verdict marked PARTIAL (N =
  3,000,000 docs), then (time permitting) the same prefix built twice with the
  twin token map. Hard stop 06:40Z (children killed at the deadline).
- Resources: `nice -n 10 taskset -c 8-15`, `num_threads=8`,
  `RAYON_NUM_THREADS=8`, local venv mirror (`/home/vscode/work/venv_local`,
  same .so), jsonl and build 1 read from local disk (`/var/tmp`), peak memory
  ~8.2 GB (one index in memory at a time), `SFU_SEISMIC_STAGE_DIR` empty.
  Nothing written under `data/seismic_150m/`.
- Expected runtime: arm A ≈ 35–45 min (build ~30 min + save ~2 + build-1 load
  and queries ~3 + twin query ~2); arm B ≈ 35 min; dv-v2 step ≈ 12 min.
  Timings are INVALID by construction (Agent C's index-loading parity eval runs
  on cores 0-7 at the same time).

### Deviation 2026-10-01 06:00Z (before any comparison result existed)

- The shared lock was acquired at 05:42:08Z (waited 4,020 s), before the
  05:50Z cutoff, so the runner chose arm FULL and started build 2 at 05:42Z.
- At 06:00Z, 18 min in, the build child was still in the jsonl read phase with
  **VmSwap 5.8 GB and VmRSS 1.7 GB**: two concurrent M1 children of another
  agent held ~6.3 GB each, host swap was at 8/16 GB, and the build's growing
  dataset was being pushed to the slow swap disk. M9's whole build took
  1,764 s on a less loaded host; this one could not have finished build + save
  + queries by the 06:40Z hard stop.
- So the FULL attempt was KILLED at 06:00:30Z (its log and state kept as
  `run_full_attempt_killed.log` / `run_state_full_attempt_killed.json` in the
  work dir; no build-2 index was produced) and the pre-committed PREFIX
  fallback was started at 06:00:40Z by setting `SFU_DRIFT_FULL_CUTOFF` to a
  past time: first 3,000,000 jsonl lines built twice, same params, verdict
  PARTIAL (N = 3,000,000 docs). The decision rule is unchanged. A prefix index
  is structurally different from the full shard (global pruning keeps up to
  5,250 postings per term over 3M instead of 18.8M docs), so the prefix result
  measures the build's non-determinism mechanism, not the full-shard magnitude.

## Results (measured 2026-10-01 06:00–06:20Z, git HEAD at run f24151ff)

Verdict: **MIXED — PARTIAL (3,000,000-doc prefix)** by the pre-registered rule
(m = 0.996, between 0.9915 and 0.998). Full-shard (18.8M) build-vs-build drift:
**NOT RUN** (attempt killed, see deviation above).

| Comparison (3M-doc prefix, stock f16 `SeismicIndex`, 220 queries) | topics120 overlap@10 mean / min | diverse100 overlap@10 mean / min | identical top-10 (set) | identical top-200 (ordered) | overlap@200 mean |
|---|---|---|---|---|---|
| Same params, build 2 vs build 1 (primary) | **1.000** / 1.0 | **0.996** / 0.9 | 120/120, 96/100 | 34/120, 20/100 | 0.9814 / 0.9761 |
| Same params + twin `token_to_id_map`, build 2 vs build 1 (supplementary) | 1.000 / 1.0 | 1.000 / 1.0 | 120/120, 100/100 | **120/120, 100/100** (scores bit-equal) | 1.0 / 1.0 |

- Per-query distribution, primary: topics120 all 120 at 1.0; diverse100 96 at
  1.0, 4 at 0.9 (query indices 38, 77, 88, 92). Score differences on lists
  that are identical up to 200: max 3.8e-6 (f32 summation order).
- Stock files differ (2,088,947,184 vs 2,088,992,339 bytes). Both builds:
  3,000,000 docs, dim 28,139, nnz 258,874,916.
- Build seconds 335.9 / 290.8 (primary), 267.7 / 266.2 (token-map); peak RSS
  ~2.8–3.3 GB; peak VmSwap 1.35 GB in the first build only. Timings INVALID
  (shared host: Agent C on cores 0-7, another agent's two M1 children).
- Script `scripts/experiments/eval_delta_ingest_twin_drift_baseline.py`;
  results `data/eval_results/delta_ingest_twin_drift_baseline_20261001.json`;
  work dir `/home/vscode/work/delta_ingest/twin_drift/` (9.7 GB: prefix jsonl
  + two prefix indexes; deletable).

### Reading

1. **SEISMIC builds from jsonl are not reproducible, and the cause is known.**
   The vocabulary gets random component ids in every build (std `HashMap`
   with a per-process `RandomState` in `JsonSparseVector`). This is not
   thread scheduling, not k-means seeding (seeded 1142). Pin the ids and two
   builds give bit-equal search results (supplementary row, 220/220 top-200
   lists and scores equal). The 2,000-doc toy showed the same.
2. **This noise reaches top-10.** On a 3M prefix, 4 of 220 queries (all
   diverse) lose one top-10 doc between two same-parameter builds, and only
   54/220 top-200 lists match. M9's rebuilt-vs-served gap (0.9858 / 0.9870,
   overlap@200 0.9636 / 0.9518) is the same kind of difference. Both sides of
   M9 were jsonl builds with independent random id assignments; the served
   build's ids came from the shard_spool jsonl.
3. **Not shown:** whether the full-shard build-vs-build noise is as large as
   M9's gap. Noise should grow with shard size: more docs mean more ties at
   the global-threshold cut, and 18.8M vs 3M docs is 6.3× (*est.*,
   unmeasured). Both the prefix overlap@200 (0.98) and overlap@10 (0.996) sit
   between "exact" and M9's numbers. The rule says MIXED, and the full-shard
   number is needed to split M9's gap into noise and real loss.

### Recommendations

- **M9:** its FAIL stands as recorded. Do NOT restate the bar from this PARTIAL
  result. The decisive and cheaper next step: rebuild shard 0 from the same
  jsonl **with `input_token_to_id_map` = the twin's `token_to_id_map.bin`**
  (the original build's ids), then compare with the twin f16 dir and with the
  served dv-v2 shard using M9's method. The harness has this already as arm B
  (`run` FULL path, ~35 min build plus ~10 min conversion on a quiet host,
  peak ~8.2 GB). On the prefix this pin makes builds bit-equal, so if the
  original build is reproduced, M9 should come out at ≈ 1.0 / the E8 per-shard
  level (0.993–0.997) against served (*est.*). The twin route is then exact,
  and no noise-aware bar is needed.
- If a noise-aware bar is still wanted (e.g. unpinned rebuilds), it needs the
  full-shard same-params rebuild-vs-rebuild number. Command below.
- **Fold-in trigger design (`02_DESIGN.md` §4 item 11):** every fold-in or
  compaction that rebuilds a SEISMIC shard from jsonl must pass a fixed
  `input_token_to_id_map` (the base's map plus new tokens appended). Otherwise
  each rebuild randomly perturbs the ranking of untouched docs: on 3M docs,
  1.8% of queries changed top-10 and 75% changed top-200 with zero content
  change. Without the pin, parity checks after a fold-in cannot tell a bug
  from relabel noise. This also applies to
  `spike/delta_ingest/generation.build_seismic_shard` (delta generations),
  which builds from jsonl the same way (recommendation; not checked or changed
  here).

### Resume commands

**DONE 2026-10-01 15:27–16:45Z. See §"Full-shard run" below. The command
is kept for the record. Its run needed the exclusive-lock/abort edits of
commit 1f32ed8a and the branch fix of the commit that added this note.**

Full same-params drift baseline (arm A, then arm B if ≥ 38 min remain, then
the dv-v2 step), on a quiet host, under the shared latency lock:

```
cd /workspaces/sfu-library-thinclient
SFU_DRIFT_NOT_BEFORE=2000-01-01T00:00:00Z SFU_DRIFT_FULL_CUTOFF=<now+5min> SFU_DRIFT_DEADLINE=<now+2h> \
SFU_DRIFT_RESULT=data/eval_results/delta_ingest_twin_drift_baseline_<date>.json \
  nice -n 10 taskset -c 8-15 /home/vscode/work/venv_local/bin/python3 \
  scripts/experiments/eval_delta_ingest_twin_drift_baseline.py run
```

(Script constants `LOCK_GIVEUP` is pinned to 2026-10-01; edit for a later
date. Arm B alone needs a small driver around `arm_b()`.)

## Full-shard run (measured 2026-10-01 15:27–16:45Z, git HEAD at run 1f32ed8a)

Run by agent DRIFT (third wave) ALONE on the host, under the EXCLUSIVE
latency lock `/tmp/sfu_latency_measure.lock` (acquired 15:27:54Z with no
wait, released 16:45:07Z). Host MemAvailable at start was 28.4 GB. Abort
rule: child VmSwap > 2 GB or host MemAvailable < 6 GB. It never fired:
peak child VmSwap was 0.0 GB in every step and the lowest MemAvailable
seen was 16.5 GB. Arm FULL used the whole jsonl (18,799,322 docs) with the
same params, the same 220 encoded queries (sha256 db648ae5…, encoded
2026-10-01 04:13Z) and the same search (k=200, query_cut=len(terms),
heap_factor=0.8, PREFLOOR=2). The pre-registration above is unchanged.
Results:
`data/eval_results/delta_ingest_twin_drift_baseline_full_20261001.json`.
Log: `/home/vscode/work/delta_ingest/twin_drift/run_full.log`.

### Verdict (pre-registered rule, applied mechanically)

m = min(0.9908, 0.985) = **0.985 ≤ 0.9915 → NOISE**. Build-vs-build drift
explains M9's gap. The arm is FULL, so the verdict is not PARTIAL. The 3M
prefix's MIXED / PARTIAL verdict is superseded.

### Numbers (220 queries; overlap@10 mean / min per set; identical top-10 = set equality)

| Comparison | topics120 | diverse100 | identical top-10 | identical top-200 | overlap@200 |
|---|---|---|---|---|---|
| **Primary:** unpinned build 2 vs M9 build 1, stock f16 `SeismicIndex` | **0.9908** / 0.8 | **0.985** / 0.8 | 111/120, 86/100 | 2/120, 1/100 | 0.9632 / 0.9536 |
| Control: build 1 queried twice, one process | 1.0 / 1.0 | 1.0 / 1.0 | 120/120, 100/100 | 120/120, 100/100 | 1.0 / 1.0 |
| dv-v2 (M9's level): build 2 vs build 1, `MmapSeismicIndex` | 0.9908 / 0.8 | 0.986 / 0.8 | 111/120, 87/100 | 2/120, 1/100 | 0.9632 / 0.9533 |
| Link: build 1 stock vs twin f16 (original build) | 0.9858 / 0.8 | 0.987 / 0.9 | 106/120, 87/100 | 1/120, 1/100 | 0.9637 / 0.952 |
| Link: build 2 stock vs twin f16 | 0.9925 / 0.8 | 0.984 / 0.8 | 112/120, 86/100 | 2/120, 0/100 | 0.9624 / 0.9516 |
| **M9 rerun:** build 1 dv-v2 vs SERVED dv-v2 (unpinned) | 0.9858 / 0.8 | 0.987 / 0.9 | 106/120, 87/100 | 1/120, 1/100 | 0.9636 / 0.9518 |
| Build 2 dv-v2 vs SERVED (a second unpinned sample) | 0.9925 / 0.8 | 0.985 / 0.8 | 112/120, 87/100 | 2/120, 0/100 | 0.962 / 0.9516 |
| **Pinned map** (arm B) stock vs twin f16 | **1.0** / 1.0 | **1.0** / 1.0 | 120/120, 100/100 | 118/120, 97/100 | 0.9999 / 0.9999 |
| **Pinned map** dv-v2 vs **SERVED** dv-v2 | **1.0** / 1.0 | **1.0** / 1.0 | 120/120, 100/100 | 118/120, 96/100 | 0.9999 / 0.9999 |
| Pinned map stock vs build 1 / build 2 stock | 0.9858 / 0.9925 | 0.987 / 0.984 | 106+87 / 112+86 | 1+1 / 2+0 | — |
| Twin f16 vs SERVED dv-v2 (E8 level, for scale) | 0.9925 / 0.9 | 0.995 / 0.9 | 111/120, 95/100 | 0/120, 0/100 | 0.9972 / 0.9969 |

- The M9 rerun reproduces M9's recorded 0.9858 / 0.9870 exactly, so the
  queries and paths match M9's. Two unpinned rebuilds disagree with each
  other (0.9908 / 0.985) about as much as each disagrees with the served
  shard (0.9858 / 0.987 and 0.9925 / 0.985).
- Pinned-map rebuild (arm B: `input_token_to_id_map` = the twin's
  `token_to_id_map.bin`, which is byte-identical to the served dv-v2
  shard's): every top-10 equals the original build's and the served
  shard's. 214–215 of 220 top-200 lists are identical too. The c1a output
  has `forward_offsets`, `forward_components`, `forward_values` and
  `document_mapping_strings` **byte-identical** to the twin. The token map
  is content-identical (28,702 entries, equal dict; the file's byte order
  differs). `posting_lists.bin` differs by +1,304 bytes (1,159,213,032 vs
  1,159,211,728). Cause of that residual: not investigated.
- Unpinned build 2 vs build 1 files: stock 8,280,290,695 vs 8,280,343,062
  bytes; f16 forward components/values differ (relabelled ids); posting
  lists −52,408 bytes.
- Resources (exclusive lock, idle host; timings informative, not the
  deliverable). Build 2: 1,585.5 s build + 17.0 s save, peak RSS 9.68 GB.
  Arm B: 1,403.4 s + 18.8 s, 9.58 GB. c1a: 60 s, 9.9 GB. dotvbyte perdoc:
  128–129 s, 10.1 GB. Build-1 stock load: 40.5 s, 8.8 GB.

### What it means for M9

- **M9's FAIL stands as recorded and is now explained.** The unpinned twin
  route as M9 ran it misses the 0.99 bar (0.9858 / 0.9870, reproduced
  today). A second unpinned rebuild misses it as well (0.9925 / 0.985
  against served). The pre-registered rule reads the gap as build noise
  (NOISE), so it is not a real fidelity loss.
- **The pinned-map rebuild meets M9's bar:** dv-v2 vs served overlap@10
  1.000 / 1.000 ≥ 0.99 on each set. It is a different procedure from M9 as
  run (one more build argument), so M9's own row is not rewritten. This is
  the remedy that `10_FOLDIN_TRIGGER_PREREGISTRATION.md` G1 names as
  (R-a), and its R-a bar (≥ 0.99 vs served on each set) is met. Because
  the outcome is NOISE, G1 does not need a remedy; the number is recorded
  against that bar for completeness.
- The pre-registered NOISE branch says "the 0.99 bar needs a noise-aware
  restatement (recommended, not changed)". For unpinned rebuilds that
  holds. With the pinned map there is nothing left to restate: the
  rebuild reproduces the served ranking.

### What it means for G1 (`docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md` §3; doc 10 not edited)

- Item N's outcome is **NOISE** (m = 0.985 ≤ 0.9915). In doc 10 the row
  "**NOISE** (m ≤ 0.9915)" is selected, so **G1 holds**. Doc 10's table
  and item N's own verdict agree (both NOISE), so the "stricter consequence
  governs" clause does not apply.
- The noise-aware F2 bar this row fixes, `bar_set = min(0.99, m_set) −
  0.005`, comes out as: QT (topics120) min(0.99, 0.9908) − 0.005 =
  **0.985**; QD (diverse100) min(0.99, 0.985) − 0.005 = **0.980**. Both m_set
  values are rounded to 4 dp in the results JSON.
- Observation for the coordinator (not a rule change): doc 10 F2 already
  has an "under a G1 remedy: 0.99" branch, and the pinned-map route
  reproduces served at 1.000. Choosing between the two belongs to the frozen
  pre-registration's owner, not to this run.
- Fold-in design consequence (unchanged from the prefix recommendation, now
  measured at full scale): every SEISMIC rebuild from jsonl should pass a
  pinned `input_token_to_id_map`. Without it, a rebuild with zero content
  change moves 23/220 top-10 lists (overlap@10 0.9908 / 0.985) and leaves
  only 3/220 top-200 lists unchanged.

### Incident (scratch only; nothing under `data/` written)

An edit in commit 1f32ed8a put the new `if ABORT:` block between the FULL
branch and its `else:`. After the FULL arm finished (all its query outputs
were on disk by 16:34:15Z), the harness therefore also started the PREFIX
arm at 16:34Z. It re-created `prefix_3000000.jsonl` (same `head -n`
content) and overwrote the scratch `prefix_p1.index.seismic` /
`q_prefix_p1.json` of the 06:00Z prefix run. Those two files are now
renamed `*_STRAY_20261001T1640Z*`. The committed prefix results JSON is
untouched. The stray run was killed at 16:45Z, before its final save, so
the FULL results JSON never received prefix keys. Because of the kill, the
FULL run never saved its own `served_level` block. It was computed offline
at 16:45Z from the saved query outputs (new `finalize` subcommand, marked
`computed_by` in the JSON); none of the inputs to that computation was
re-run or changed. The branch is fixed in the commit that adds this
section. The served shard and the twin were only read (mmap search,
`cmp`).
