# M4 / M5 findings: read amplification and reload cost of delta generations

**Status:** ACTIVE

Measured 2026-09-29 to 2026-09-30 (UTC) on this host (Ryzen 7 5700X3D, 31 GB,
WSL2; base tantivy sections and meta.sqlite on the `/workspaces` 9p mount,
SEISMIC base shards staged on local disk). Bars are those of
`docs/delta_ingest/03_SPIKE_PLAN.md` M4/M5, unchanged. Numbers below are copied
from the results files; the files are authoritative.

- M4: `data/eval_results/delta_ingest_M4_20260929.json`
  (harness `scripts/experiments/eval_delta_ingest_m4_read_amp.py`, harness
  commit 60f24f4c, code snapshot `git archive ef48050d src`)
- M5: `data/eval_results/delta_ingest_M5_20260930.json`
  (harness `scripts/experiments/eval_delta_ingest_m5_reload.py`, same snapshot)

## Setup

Corpus (b) = 160,347 OpenAlex works from snapshot partition
`updated_date=2026-09-15/part_0001` absent from the base `meta.sqlite`
(194,931 in-slice records minus 34,584 in base; vectors reused from item F's
GPU encode). Delta roots under `/home/vscode/work/inplace_update/m4/`:
`root_n1` (1 generation), `root_n4` (4), `root_n8` (8, about 20k docs each),
`root_n4c` / `root_n8c` (the same compacted into one). All built with the
supported spike calls (stage, buffer upsert, `freeze_buffer`, buffer delete;
`compact`). Livedocs off (no ordinals env), no deletes or supersedes, empty
buffer.

Design (script header, REVISION 1 and 2): one process per federation holds one
`ThinClientRetriever` per arm; each of the 120 natural topics is first sent to
a separate priming retriever (discarded), then to every arm in a per-query
shuffled order; 1 warm-up pass + 2 measured passes; quiet-host checks every 10
queries; the latency lock is held for the whole process. Health (SPLADE
encoder, SEISMIC backend class and shard count, delta generations,
cross-encoder, embedding model) is asserted before any timed query; no process
was degraded and no log contains ENOMEM or fallback signatures.

## M4 (parallel SEISMIC backend, the served mode)

| arm | live gens | p50 ms | p95 ms |
|---|---|---|---|
| n0 | 0 | 2306.8 | 3478.6 |
| n1 | 1 | 2340.5 | 3568.7 |
| n4 | 4 | 2387.1 | 3599.9 |
| n8 | 8 | 2535.9 | 3772.6 |

- **Pre-registered primary (the statistic the bar uses):** OLS slope of arm
  p50 over N in {0,1,4,8} = **27.7 ms per generation**; post-hoc bootstrap
  95% CI 14.8 to 34.1 (width 19.3 ms); per pass 23.1 and 33.8.
- **Supplementary paired statistic:** median over (pass, topic) of each
  query's own OLS slope = **14.8 ms per generation**, bootstrap 95% CI 13.0
  to 16.9 (width 3.9 ms). Paired n8 - n0 median +123 ms (CI 112 to 137).
- **Bar (p50 growth <= +8 ms per generation): FAIL.** Both statistics and
  both CIs are above 8 ms.
- **GO line of the in-place spike (>= 3 ms p50 per generation): MET.** The
  measurement resolves 3 ms: the lower CI bounds are 14.8 (primary) and 13.0
  (paired).
- The primary and paired values differ because the per-query distribution is
  heavy-tailed at n8 (n8 - n0: mean 189 ms, median 123 ms), so the pooled p50
  moves more than the typical query does; the mean-based slope is 23.5.

Where the tax goes (post-hoc, `post_hoc.leg_attribution_parallel`; OLS of
per-arm means, ms per generation, additive; total 23.5):

| leg | ms/gen (means) | per-query median slope |
|---|---|---|
| SEISMIC traverse (fan-out incl. delta shards) | 11.0 | 7.1 |
| BM25F parse/merge/masks outside section search | 5.2 | 1.1 |
| delta abstract-store probes (hydration) | 4.8 | 4.5 |
| BM25F delta tantivy sections | 1.5 | 1.3 |
| BM25F base sections (should be 0; noise) | 1.3 | 0.2 |
| delta meta probes | 0.04 | 0.0 |
| query encode, base hydration, fusion | about 0 | about 0 |

The BM25F leg p50 moving 2034 to 2065 ms is mostly noise in the unchanged base
sections (paired median change -0.1 ms) plus the delta sections and the
per-section parse and mask work; the per-section tantivy search itself adds
about 1.3 to 1.5 ms per generation. For SEISMIC, the slowest base shard hardly
moves (p50 87 to 96 ms) and a delta shard is never the slowest shard; the
added time is fan-out overhead around the shards (traverse minus slowest shard
71 to 134 ms mean from n0 to n8: more threads, more candidates to merge).
**Only the SEISMIC share (about 11 ms/gen by means, 7 ms/gen per-query median,
roughly half of the tax) is what an in-place shard update would remove.** The
BM25F and abstract-probe shares need their own fix (fewer sections or
compaction), and they alone (about 6 to 12 ms/gen) exceed the 3 ms line.

**Compaction bar (the compacted p50 within 5% of the 1-generation p50): NOT
MEASURED at this commit.** The re-run held only n0, n1, n4 and n8. A separate
parallel run with the same design (arms n1, n8, n4c, n8c; run dir
`m4/inproc_compaction`) was running when this was written; its result goes
into `compaction_run` of the M4 file and into this section. The discarded
first run did contain n4c and n8c (ratios 0.991 and 0.986 against n1). Those
arms were not the primed instance, but that run is discarded, so those
numbers do not decide the bar.

Sequential backend: see "Not measured" below.

## Discarded first run (`inproc_main`), and why the harness was revised

The first M4 process (parallel, all six arms, started 19:19Z on 2026-09-29)
primed each query on the **n0 retriever itself**. After its first measured
pass I saw that this left the n0 instance warm in state that the other arms
do not share (its own SQLite connection caches for meta and abstracts on 9p,
its own shard mappings): n0's median SEISMIC traverse was 48 ms vs 193 ms for
n1, hydration 5 vs 77 ms, and 5 vs 723 major faults per call, putting n0's p50
about 370 ms below every delta arm. The low N=0 point then inflated the slope
(that run's primary: 44.3 ms/gen, biased; paired median 39.6, biased). I
revised the harness (REVISION 2, commit 60f24f4c, written into the script
header before any further measured run) so that the priming call runs on a
separate seventh retriever configured like n0, and re-ran parallel with arms
n0, n1, n4, n8. The bar, the metric and the slope definitions were not
changed; only which instance takes the discarded priming call. The revision
was made after measured queries of that run had been seen, and the run is
reported, not hidden: its numbers are in
`post_hoc.discarded_run_inproc_main` of the M4 file. Statistics that do not
involve n0 were unaffected by the flaw and agree with the re-run: OLS over
{1,4,8} 16.2 ms/gen (re-run 28.4), n8 - n1 paired median +117 ms (re-run
+106 ms).

## M5 (reload after a delta publish, parallel backend, 5 reps per root)

| root | shards | reload() s (5 reps) | max | backend re-open s | first query p50 ms | warm p50 ms | ratio |
|---|---|---|---|---|---|---|---|
| n1 | 9 | 1.53, 0.63, 0.60, 1.19, 1.32 | 1.53 | 1.1 to 2.9 | 8179 | 5100 | 1.60 |
| n8 | 16 | 1.48, 0.90, 1.15, 0.77, 1.81 | 1.81 | 1.7 to 3.7 | 10042 | 5515 | 1.82 |

- **reload <= 15 s: PASS** on both roots (max 1.8 s; with the lazy SEISMIC
  backend re-open inside the first query, reload + re-open max 5.3 s).
- **first-query p50 <= 2x warm p50: PASS** on both (1.60 and 1.82; the same
  topic's own warm latency gives paired median ratios 1.42 and 1.67). n8 is
  close to the bar.
- The backend was dropped on every publish (S4 path confirmed). Major faults
  of the first query after reload were 4k to 20k. Controls (reload without a
  publish, backend kept): first query 4.1 to 8.1 s.
- The warm p50 here (about 5 s) is a one-retriever process touching each
  topic once per pass; it is not comparable to M4's per-arm p50 (about 2.3 s),
  where every topic had just been primed.
- O1 and O2 cannot bias these runs: the buffer was empty and every publish
  was followed by `reload()` before any query.

## Host conditions

- M4 re-run: 21:51Z to 23:19Z on 2026-09-29, load 1.3 to 3.5 at all 24 inline
  checks, no other busy process, GPU 0 to 2%, MemAvailable 28 GB.
- M5: 23:25Z to 00:41Z, quiet at start and end of each root.
- The first attempt at 19:05Z was stopped before any measured query because
  the Stage-0 agent ran without the lock (5 workers at 100% CPU); the
  coordinator had it stop.
- `maxrss_gb: 72.57` in the M4 file counts every resident page mapped into the
  measuring process. Five retrievers each map the same 8 staged base shards,
  so shared page-cache pages are counted once per mapping. It is not physical
  memory: MemAvailable stayed about 28 GB, and SwapFree fell from 14.0 to
  11.8 GB during the run.

## Not measured

- **Sequential SEISMIC federation: NOT MEASURED.** After the parallel re-run,
  the time left before the 8 h limit fit either the sequential run (about
  2.5 h) or the compaction arms (about 1.6 h). The compaction arms carry half
  the bar, so they ran instead. The sequential run can still be done with
  `inproc-drive --federations sequential --arms n0,n1,n4,n8 --tag fixprime`
  under the lock.

## M4 compaction half, run 2026-10-01 (parallel federation)

**Pre-run record (written 2026-10-01 ~04:12Z, after launch and during the
discarded warm-up pass, before any measured query).**

- Bar (frozen, `03_SPIKE_PLAN.md` M4 row 35 and the script header): compaction
  returns to within 5% of the 1-generation arm, operationalised as PASS iff
  `|p50(n8c)/p50(n1) - 1| <= 0.05`, parallel federation; n4c reported with the
  same rule (not decisive).
- Command (launched 2026-10-01 04:09:09Z, repo HEAD 105261c8, measured code
  snapshot `git archive 105261c8 src` at
  `/home/vscode/work/inplace_update/m4/code_105261c8`):
  `inproc-drive --federations parallel --arms n1,n8,n4c,n8c --tag compaction_20261001
  --retries 0 --out data/eval_results/delta_ingest_M4_compaction_20261001.json`,
  defaults otherwise (1 warm-up + 2 measured passes, 120 topics, separate
  priming retriever, seed 20260929), wrapped in `timeout` to 06:08Z. The child
  takes `/tmp/sfu_latency_measure.lock` exclusively (it held it from 04:09Z).
- Roots unchanged since 2026-09-29 (`root_n1`, `root_n8`, `root_n4c`,
  `root_n8c`; `compact_n8.json` 8 gens into g0009, `compact_n4.json` 4 into
  g0005).
- Deviations, stated before measuring:
  1. Interpreter is the local-disk venv mirror
     `/home/vscode/work/venv_local/bin/python3` (same installed `seismic` .so,
     md5 04ca2e42…, as `.venv`), and `SFU_SPLADE_MODEL_PATH` /
     `SFU_CE_MODEL_PATH` point at the local mirrors under
     `/home/vscode/work/models_local/` (same model files), to avoid the 9p
     ENOMEM failure mode (O12). The 2026-09-29 primary run used `.venv` and the
     repo model paths, so absolute p50s across the two runs are not directly
     comparable; the bar compares arms within this one process.
  2. Measured code is snapshot 105261c8 (includes the O19 BM25F lower-case fix
     and the livedocs work), not ef48050d as in the growth run. Same reason:
     cross-run absolute comparisons are indicative only.
  3. Sequential federation not run (does not fit the time box).
  Projected runtime ~1.5 h (2026-09-29 run with 4 arms + prime: 5,255 s),
  i.e. finish ~05:40Z, inside the 06:10Z lock release; no trimming planned.

### Result (measured 2026-10-01 04:09Z – 05:42Z)

Results file `data/eval_results/delta_ingest_M4_compaction_20261001.json`
(rows `/home/vscode/work/inplace_update/m4/inproc_compaction_20261001/parallel.json`),
script `scripts/experiments/eval_delta_ingest_m4_read_amp.py` (`inproc` child at
HEAD 105261c8; summary re-run with `inproc-summarize --tag compaction_20261001
--commit 105261c8…` at e0f9eebf, because the driver's in-memory summarize hit the
per-pass bug fixed in e0f9eebf; no statistic of the run depends on that fix).
Health OK for all four arms + the priming retriever (SPLADE 43 terms,
CrossEncoder, SentenceTransformer, ParallelSeismicBackend; n1/n4c/n8c 9 shards
and 11 delta sections, n8 16 shards and 73), every measured call reached the
SEISMIC traverse, 0 warnings during passes, no ENOMEM in the log, no retry.
N = 240 calls per arm (120 topics × 2 measured passes).

| arm | live gens | p50 ms | p95 ms | mean ms | per-pass p50 (2, 3) |
|---|---|---|---|---|---|
| n1 | 1 | 2491.5 | 3650.4 | 2483.5 | 2511.4 / 2440.8 |
| n8 | 8 | 2614.7 | 3815.8 | 2631.9 | 2680.1 / 2599.6 |
| n4c | 4 → 1 (g0005) | 2520.0 | 3598.0 | 2483.0 | 2536.5 / 2442.6 |
| n8c | 8 → 1 (g0009) | 2525.1 | 3656.4 | 2487.6 | 2566.2 / 2483.3 |

- **Compaction bar (`|p50(n8c)/p50(n1) - 1| <= 0.05`, parallel): PASS.**
  Ratio **1.0135** (per pass 1.022 / 1.017). n4c (reported, same rule): 1.0114,
  PASS.
- Paired per-query differences (median over 240 (pass, topic) pairs, bootstrap
  95% CI): n8c − n1 **−0.2 ms** (−14.7 to +12.1); n4c − n1 −3.3 ms (−15.6 to
  +15.9); n8 − n1 +94.5 ms (+82.9 to +110.4); n8c − n8 **−93.1 ms** (−109.9 to
  −80.4).
- **What compaction buys back vs n8:** by the paired statistic essentially all
  of the 7-extra-generation tax (93.1 of 94.5 ms, ~98%); by pooled p50 89.6 of
  123.1 ms (~73%; the rest is p50 noise, the n8c − n1 CI straddles 0). After
  compaction the delta layer costs the same as one generation: per-arm mean
  delta-side serial work 14.7 ms (n8c) vs 15.1 (n1) vs 93.7 (n8); SEISMIC
  traverse p50 170.5 / 173.0 / 225.2 ms; major faults per call 951 / 842 / 1653.
  The biggest single n8 component is the per-generation delta mask work
  (`delta_masks` mean 40.2 ms at n8 vs 0.3 at n1/n8c), then delta abstract-store
  probes (37.9 vs 6.0 / 5.6) and delta BM25F sections (15.1 vs 8.7 / 8.5).
- Growth statistics are NOT recomputed here (no n0/n4 arm; the summary's
  `slope_primary_per_pass` entries are 2-point {1,8} slopes, 24.1 / 22.7 ms/gen,
  and are not the pre-registered primary). They agree with the 2026-09-29 growth
  run's n8 − n1 paired median (+106 ms, CI 94–116) within CIs.
- Delta docs in fused top-10: 0.0 mean in every arm (corpus (b) is ~90%
  datasets), so this run times the delta layer's cost, not its ranking effect.
- Host: load1 1.6–4.5 at all 24 inline quiet checks, all quiet (max wait 1.1 s),
  MemAvailable 29.0 → 28.3 GB, SwapFree 15.0 → 12.5 GB; the measuring process
  held ~1.3 GB VmSwap from the warm-up pass on (WSL swap-out under a full page
  cache; anon RSS ~1 GB), steady through both measured passes and identical for
  all arms, which are interleaved per query. Pass walls 1792 / 1872 / 1847 s,
  total 5551 s. The latency lock was held exclusively from 04:09Z to 05:42Z.

**What it means for M4 and the follow-up.** M4's two halves now stand at:
growth bar FAIL (27.7 ms/gen, 2026-09-29), compaction bar PASS (1.35% vs ≤ 5%,
2026-10-01). Since `compact` returns the read path to the 1-generation cost,
the per-generation tax is bounded by how many live generations are allowed to
accumulate. The follow-up is a compaction-cadence rule: with ~15–28 ms per
extra live generation (paired / pooled), a cap of K live generations bounds the
added p50 to about (K − 1) × 28 ms over the one-generation state; e.g. K = 2
holds it within one generation's tax, *est.* from these two runs, not measured
as a cadence. The cadence rule and its bar must be pre-registered in
`03_SPIKE_PLAN.md` before any run; this run measured only the end states (8 → 1
and 4 → 1), not compaction's cost while serving (compact walls 126 s / 146 s
offline, `compact_n8.json` / `compact_n4.json`, 2026-09-29) nor reload after a
compaction publish.

Still not measured: sequential federation (both halves), compaction under
concurrent serving, a cadence policy.
