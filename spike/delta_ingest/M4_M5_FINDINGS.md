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
