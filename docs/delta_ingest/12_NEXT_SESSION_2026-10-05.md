# 12 — Next-session brief (written 2026-10-05)

**Status:** ACTIVE

Start here when resuming `delta_ingest/`. It states where the track stands
after the sessions of 2026-10-04 and 2026-10-05, what the owner has decided,
what is still the owner's to decide, and the work in order. Numbers are
copied from the records named beside them; if this page and a record
disagree, the record wins. Nothing was running and the latency lock
(`/tmp/sfu_latency_measure.lock`) was free when this was written.

## 1. Where the track stands

| Part | State | Record |
|---|---|---|
| Delta layer (ingest → buffer → generations → masks → compaction), gate `SFU_DELTA_ROOT` | Built, default OFF. M1, M2, M3, M5, M4-compaction PASS; `09` promotion conditions P1–P4 hold for the fallback stack (layout `per_base_section` + L3, L4, L5): F-SLOPE 1.31 ms/gen versus 8.0. **Not declared eligible** — waits for the owner (§3 item 1) | `spike/delta_ingest/M4F_FINDINGS.md`; `data/eval_results/delta_ingest_M4F_20261001.json` |
| Layout `single` | FAIL on doc 11 bar A (delta docs of one subject rank better); L2 killed, fallback in force | `11_P2_MULTISECTION_PREREGISTRATION.md` |
| F-COMP (compaction latency) | FAIL as recorded on the repeat (interval −1.1 to +10.7 ms versus ±8); R3 of 2026-10-04 shows no compaction residue (x8c − x1 −5.5 ms, CI −15.7 to +4.8). Not on promotion route (a) | key `R3_per_base_section` |
| Churn filter M7 | FAIL (most touched records are new works); a property of the data, a running cost | `spike/delta_ingest/BASE_HASH_SEED_FINDINGS.md` |
| Fold-in F2 (quality parity) | **PASS on fold 1 and fold 2** at the federated level (owner decision 2026-10-04); shard-own QD 0.9780 versus 0.9820 stays on record. Q-d still on a fixture without deletions | `spike/delta_ingest/FOLDIN_FINDINGS.md`; doc 10 addendum 2026-10-04 |
| Fold-in F4 (build cost) | Build record of fold 3 within every bar **as amended 2026-10-05** (wall 23.9 min; peak tree 11.37 GiB versus 11.5; scratch 59.50 GB versus 60; output 13.83 GB). Margins are thin on memory (0.13 GiB) and scratch (0.5 GB). Publish stage and duty cycle not measured | doc 10 addendum 2026-10-05; keys `F4_build_fold3`, `F4_amended_bar_20261005` |
| Fold-in F1, F3, F5, F6, F8, F0, F7 | NOT RUN. F1 needs trigger code that does not exist | doc 10 §6 |

Three folds of shard 0 (13 GB each, unpublished, same inputs) are at
`/home/vscode/work/delta_ingest/foldin/shard0/fold{1,2,3}`; fixture
`…/foldin/fixture_n8`; preview roots `…/foldin/f2/preview_root` (fold 1) and
`…/foldin/f2_fold2/preview_root` (fold 2). Fold 1 and fold 2 return the same
ordered top-10 on 220/220 queries although their posting-list bytes differ;
fold 3 was not put through F2.

## 2. Owner decisions taken (do not re-open without the owner)

| Date | Decision | Where recorded |
|---|---|---|
| 2026-10-03 | F2 Q-a bar = Reading A (0.985 QT / 0.980 QD) | doc 10 addendum 2026-10-03 |
| 2026-10-04 | Gate eligibility waits for the multi-section P2 check (it then read FAIL for `single`) | doc 11 |
| 2026-10-04 | F2 Q-b binds at the **federated** level, not the shard level (taken after the runs) | doc 10 addendum 2026-10-04 |
| 2026-10-05 | F4 memory bar amended to **≤ 11.5 GB on the process-tree peak** (taken after the runs); 12 GB kill line unchanged | doc 10 addendum 2026-10-05 |

## 3. Still the owner's to decide (ask first, in this order)

1. **Is the fallback stack eligible for `SFU_DELTA_ROOT`?** Doc 11's decision
   says "not eligible until doc 11 reads PASS"; it read FAIL for `single`
   only, and `per_base_section` does not need P2. This is the one thing
   between today and a usable opt-in module.
2. Should a rank **improvement** fail doc 11's two-sided bar A? (A dated
   amendment would revive layout `single`: −17.9 ms at N = 8 in R2.)
3. `SFU_OA_BITMAP`: ON makes `open_access_only` work (0 → 6,000 results) and
   lowers unfiltered nDCG@10 0.7053 → 0.6835. Stays OFF until ruled.
4. Hot-section base-hash seed (full seed *est.* 24.6 h).
5. Fold-in direction, only if rebuild cost becomes a problem at real churn:
   cluster-level update instead of a shard rebuild (§5 item 3) would need its
   own pre-registration.

## 4. Work in order (none needs an owner answer except where marked)

1. **Deletions fixture for Q-d** (doc 10 §5 (ii)): the Stage-0 subsample under
   `/home/vscode/work/inplace_update/stage0/` (32,155 upserts + 1,131,292
   deletions routed to shard 0; format unconfirmed). Build a fixture root
   with tombstones and superseded docs, fold it, run F2. This is a NEW fold
   (different delta): a Q-a/Q-b failure on it is a result, not a rebuild.
   Watch F4 on it — dropping 6 % of the shard changes the memory and scratch
   numbers, and both margins are thin.
2. **Trigger code + F1** (doc 10 §1, §6 F1): compute (a), (d), (c) per shard
   at `publish()`; F1 = identical to a brute-force recount on 20 checkpoints.
   No lock needed.
3. **F8** (reload after a fold publish; exclusive lock, ~30 min) and **F3**
   (latency returns to n0; exclusive, ~1.5 h). Both need `publish-fold` run on
   a COPY of the fixture, never on a served root.
4. **F5** crash safety (60 SIGKILL trials, ~6 h light + 30 min) — needs the
   1M-doc reduced fixture builder.
5. **F6** second fold of *s′* from its own output; **F0** / **F7** after F1.
6. Optional memory headroom (not required by the amended bar): make
   `convert_f16_to_dotvbyte` stop mapping its whole source (6.29 GiB of its
   11.24) and `c1a_mmap_index` stop loading the whole stock index (10.2 GiB
   anonymous). Both are in the Rust fork `spike/seismic_upstream`, which sits
   on branch `livedocs-skip` (HEAD 620f1d2, the O10 work) — **ask the owner
   before touching the fork**; build to a side path, never
   `-C target-cpu=native`.
7. Carried over, unchanged: O10 exclusive-lock timing + operator `.so` swap;
   O2 two-freeze residual; O14 locators for shards 1–7; M2 on a second
   section; 9-shard pilot M10.

Commands that worked on 2026-10-04 (run from the repository root with
`/home/vscode/work/venv_local/bin/python3`; smoke any measure with
`--limit 3 --lock none` first):

```bash
F=/home/vscode/work/delta_ingest/foldin
TW=/home/vscode/work/inplace_update/twin_local/global_shard0of8.mmap
# fold build through the F4 recorder (exclusive lock, ~24 min, writes <log>.mem.jsonl)
python3 scripts/experiments/eval_delta_ingest_foldin.py build --delta-root $F/fixture_n8 --shard 0 \
  --fold-input $TW --token-map-dir $TW --fold-root $F --fold-workers 8 --profile desktop_gpu \
  --seismic-threads 8 --lock exclusive --log $F/<name>.log --key <F4 key> --out data/eval_results/<file>.json
# F arm preview for a given fold, then F2 at the owner's readings (shared lock, ~20 min)
python3 scripts/experiments/eval_delta_ingest_foldin.py preview --delta-root $F/fixture_n8 --fold <k> --preview-root <dir>
python3 scripts/experiments/eval_delta_ingest_foldin.py run --delta-root $F/fixture_n8 --preview-root <dir> \
  --rows-out <dir>/rows.json --bar-reading A --q-b-level federated --lock shared --key <F2 key> --log <log> --out <file>.json
# 09 latency runs: launcher pattern in /home/vscode/work/delta_ingest/serve/run_r3_20261004.sh
```

## 5. Online research 2026-10-05 — has anyone met the fold-in problem before?

Question: is the cost and the result shift of "collect updates beside an
immutable approximate index, then merge by rebuilding" known? Provenance
marks: [read] = page fetched and read by a summarising model, [snippet] =
search-result summary only. Nothing here is a measurement of this system.

1. **The pattern and its cost are the stated norm.** SPFresh (SOSP 2023)
   describes a secondary index merged by periodic global rebuild as what
   existing systems do, and names the cost: a billion-vector DiskANN rebuild
   at 1,100 GB DRAM / 32 vCPUs for 2 days, and latency/accuracy fluctuation
   during rebuilds. [read] https://arxiv.org/html/2410.14452v1
2. **A merge whose memory follows the change set, not the index.**
   FreshDiskANN's StreamingMerge is described as having a memory footprint
   proportional to the inserted and deleted points; the abstract claims
   > 95 % 5-recall@5 under thousands of concurrent updates per second on a
   billion points. [snippet for the merge description; abstract read]
   https://arxiv.org/abs/2105.09613
3. **The known way around the rebuild is local maintenance.** SPFresh's LIRE
   splits or merges only the affected partitions and reassigns boundary
   vectors; reported at about 1 % of the DRAM and < 10 % of the cores at peak
   versus global rebuild. [read, same URL as 1.] For this track that is the
   block-maintenance candidate of `08_INPLACE_POSTMORTEM_RESEARCH_2026-09-30.md`
   (DESIGN ONLY, UNMEASURED); it is not the closed in-place spike, which
   failed on dead-slot supply inside the existing file.
4. **Results that shift after a rebuild are expected of approximate
   indexes.** A vendor blog (weak authority) lists the causes — rebuilt
   structure, near-ties, removed tombstones — and recommends comparing
   against exact search and not treating rank as stable. [read]
   https://shop.zimaspace.com/en-ca/blogs/tech-ai-hub/vector-database-neighbors-change-after-compaction
   Consistent with what F2 showed here (only base docs swap; equal scores).
5. **OpenSearch ships SEISMIC with the same shape.** Since 3.3, segments
   under `approximate_threshold` (default 1,000,000 docs) are searched
   without the clustered structure, which is built once a segment passes the
   threshold; `n_postings` defaults to 0.0005 × the segment's doc count;
   force merge is recommended for latency. [snippet; the docs pages did not
   render] https://www.instaclustr.com/blog/understanding-opensearch-vector-field-type-part-2-sparse_vector/
   and https://docs.opensearch.org/3.5/mappings/supported-field-types/sparse-vector/
6. **No insert-without-rebuild was found for SEISMIC itself** (searches of
   2026-10-05; the papers present fast construction as the answer).
   Agrees with `01_RESEARCH.md`. https://arxiv.org/html/2408.04443v1

Reading for this track: the two fold-in failures of 2026-10-03/04 (rebuild
memory, a small shift in approximate results) are costs of the chosen
design, not defects of this implementation. That is the ground of the
2026-10-05 bar amendment.

## 6. Traps met on 2026-10-04 (so they are not met again)

- The F4 recorder samples every 2 s and the converter's RSS rises until it
  exits: its peak moves between builds. Read the per-stage `.mem.jsonl`
  timeline, not the single peak.
- A full-shard build with a pinned token map is not byte-reproducible in its
  posting lists, yet two such builds returned identical top-10s. Do not use
  `cmp` as the equivalence test; compare query results.
- Long chains (build → latency run) go out with `nohup setsid` plus a
  separate waiter; killing the launcher shell kills an undetached chain.
- `eval_delta_ingest_foldin.py run` takes no `--fold`; make the preview root
  with `preview --fold k` first and pass `--preview-root`.
- The stop hook's doc-sync check fires at every pause until a file under
  `docs/` is committed: commit a dated interim note early.

## 7. Progress 2026-10-08 (supersedes §1 and §4 where they differ)

Owner, 2026-10-08: §3 item 1 (fallback-stack eligibility) — "decide later";
still open, nothing recorded as decided.

| §4 item | State 2026-10-08 | Record |
|---|---|---|
| 1 Deletions fixture for Q-d | **DONE.** Fixture `/home/vscode/work/delta_ingest/foldin/fixture_n8_del` (Stage-0 data was usable, no deviation): 1,131,292 tombstones, 8,465 superseded base docs, 20,112 superseded delta copies, 32,155 live shard-0 delta docs; s′ = 17,691,720 docs. **F4 within every amended bar** (wall 23.7 min, tree peak 10.86 GiB — margin 0.64, scratch 55.99 GB, output 13.08 GB; 10 GB bar still FAIL). **F2 PASS** (federated overlap@10 0.9983 / 1.0000; ΔNDCG@10 −0.0004, CI −0.0012 to +0.0001; **Q-d 0 leaks**, masks removed 96,283 / 184,251 raw candidates on L / F). Fold output `/home/vscode/work/delta_ingest/foldin_del/shard0/fold1` (unpublished) | `data/eval_results/delta_ingest_foldin_20261008.json` keys `F4_build_fold_del`, `F2_fold_del`; FOLDIN_FINDINGS §2026-10-08 |
| 2 Trigger code + F1 | **DONE, F1 PASS** 20/20 on both roots; (b) not implemented (needs F0) | `spike/delta_ingest/trigger.py`; `data/eval_results/delta_ingest_foldin_f1_20261008.json` |
| 3 F8 + F3 | Harness `scripts/experiments/eval_delta_ingest_foldin_f3f8.py`; **RUN 01:59–03:28Z: F8 FAIL** (reload ≤ 1.22 s PASS; first-query p50 2.17× warm versus ≤ 2× FAIL) and **F3 FAIL** (p50 ratio 1.014 PASS; Δ(F, n0) +5.76 ms, CI upper 13.57 versus 8.0 FAIL; Δ(L, F) −1.5 ms). Not §8 kills; fold-in not promotable under §9 as measured. Setup needed two harness fixes first (85918e64, 46b85c0c) | `data/eval_results/delta_ingest_foldin_f3f8_20261008.json`; FOLDIN_FINDINGS §"F8 and F3 RESULTS" |
| 4 F5 | Harness `scripts/experiments/eval_delta_ingest_foldin_f5.py`; three crash-safety defects fixed before any trial (60ba0fc1). **RUN, PASS 60/60** (2026-10-09 19:44Z; 50 fold-build + 10 publish kills; split by two host pauses, resumed with exact seeded kill times, 2fd0db84) | `data/eval_results/delta_ingest_foldin_f5_20261008.json` key `F5` |
| F0 (needed by F7 and doc 13) | **RUN 2026-10-08: FAIL** — Δ(g1M) − Δ(n1) +17.93 ms, CI 10.60–23.20 versus ≤ 8.0; **c = 21.35 ms per million delta docs** (CI 12.62–27.63; upper bound, g1M kept its SEISMIC shard); doc 10 §8: sections tier FLAGGED. **Doc 13 written** (`13_FULL_REBUILD_TRIGGER_PREREGISTRATION.md`) | `data/eval_results/delta_ingest_foldin_f0_20261008.json`; FOLDIN_FINDINGS §"F0 RESULT" |

Next: F7 (trigger values; F0 and the publish wall 15.1 s are now in) and
**doc 13 — full-rebuild trigger**, WRITTEN 2026-10-08 after F0 landed
(`13_FULL_REBUILD_TRIGGER_PREREGISTRATION.md`; its §2 supersedes the
projection below, which was written before F0). Its premise: a fold
rebuilds only the SEISMIC leg; the tantivy/meta/abstract legs never fold
(doc 10 §4), base dead copies are never reclaimed (`02_DESIGN.md` §4 item 8),
and the fold's memory follows the shard size — 11.37 GiB at 18.80 M docs,
10.86 GiB at 17.69 M. *est.* (linear in docs, unmeasured): net shard growth
≈ +9 %/quarter as coded (15.1 % new − 6.0 % deleted, doc 10 §2) would cross
the 11.5 GB bar after ≈ 1 % growth and the 12 GB kill line after ≈ 5 %,
unless the Rust tool memory (§4 item 6) is reduced or shards are split (M10).
Whether a full rebuild from an OpenAlex snapshot is runnable today is
UNVERIFIED (the OpenSearch export path is gone).

**Where 2026-10-09 leaves the track.** Doc 10 scoreboard: F1, F2, F4
(amended bar), F5 PASS; F0, F3, F8 FAIL (none a §8 kill); **F7 2026-10-09: `desktop_gpu`/`server` FLAGGED** ((a) 0.02 at duty 3.1 %, but tax 76.6 ms > 64 ms at the first fold; `data/eval_results/delta_ingest_foldin_f7_20261009.json`); **F6 PASS 2026-10-09** (second fold of s′ identical to the one-step fold of the same docs on 220/220 queries; `data/eval_results/delta_ingest_foldin_f6_20261009.json`) —
fold-in is not promotable under §9. What the failures point at:
- F3 residue and F0 both sit in the sections tier, which never folds → doc
  13 (S-fold + full-rebuild triggers; GR1 first: no snapshot→spool exporter
  exists).
- F8: the first query after ANY backend drop (fold or rollback) is ~2× warm;
  reloading the changed position without dropping the whole SEISMIC backend
  (the `02_DESIGN.md` §4 remark "loading delta shards into the live backend
  without dropping the base ones") is the candidate fix — needs its own
  pre-registration.
Next engineering without an owner answer: doc 13 GR1 inventory + M1 (F6
and F7 ran 2026-10-09: F6 PASS, F7 FLAGGED on the sections-tier tax).
Owner decisions open: §3 items 1–5 above, doc 13 §11 items 1–3.
On-disk leftovers that may be deleted: `foldin/f5_smoke` (3.6 GB),
`foldin/f0/smoke` (96 MB), `foldin/f1` copies (1.6 GB).

Correction recorded 2026-10-08: layout `per_era` WAS measured for quality by
doc 11 (arms E1/E8, key `per_era_vs_per_base_section_recorded` of
`data/eval_results/delta_ingest_P2_multisection_20261004.json`) — bar A
fails the same way as `single` (−13.5 / −1.0 in `other__recent`, docs rank
better); A2/B/C/D pass. A re-run is not allowed (model result). Reviving
`per_era` or `single` needs §3 item 2 (owner) or the global-statistics fix
below.

## 8. Online research 2026-10-08 — read-amplification mitigations not tried here

Read-only research; nothing measured on this system, every payoff *est.* /
unmeasured. [read] = page fetched and read; [snippet] = search summary only.
After L3–L5 the delta adds 1.31 ms/gen, so none is needed for a bar today.

1. **Score delta docs with base collection statistics** (global IDF, as
   Elasticsearch `dfs_query_then_fetch`; tantivy has
   `Bm25StatisticsProvider`). Removes the cause of doc 11's bar-A failure, so
   `single` (−17.9 ms at N = 8, R2) / `per_era` could return without an
   amendment. Blocker checked 2026-10-08: tantivy-py 0.26 exposes only
   `doc_freq`/`num_docs`, no scoring hook → a binding change; which of the 10
   base sections' statistics to use is a design question. [read]
   https://docs.rs/tantivy/latest/tantivy/query/trait.Bm25StatisticsProvider.html ;
   [snippet] https://www.elastic.co/guide/en/elasticsearch/guide/master/relevance-is-broken.html
2. **Exact scoring of the delta instead of a delta SEISMIC shard** (OpenSearch
   skips the SEISMIC structure below 1,000,000 docs per segment; Milvus
   brute-forces growing segments; turbopuffer scans unindexed data). The
   delta (160k, folding near 940k) is under that line, and the buffer already
   scores exactly (`02_DESIGN.md` §1.4). Scan cost at 160k–940k docs
   unmeasured. [snippet] https://docs.opensearch.org/3.5/vector-search/ai-search/neural-sparse-ann/ ;
   [snippet] https://lf-aidata.atlassian.net/wiki/spaces/MIL/pages/13304009/MEP+34+--+IDMAP+BinaryIDMAP+Enhancement ;
   [read] https://turbopuffer.com/docs/architecture
3. **Base-only result cache keyed by query alone**, delta legs recomputed
   and masks re-applied after it; avoids a cold cache at every publish (doc
   10 §4). A fold must rotate that shard's entries. Hit-rate gain unmeasured.
4. **Skip a generation whose best possible score cannot enter the top-k**
   (Lucene `MaxScoreAccumulator`, block-max MaxScore). Little left to save at
   1.31 ms/gen; serializes the legs. [snippet]
   https://code.yawk.at/org.apache.lucene/lucene-core/8.7.0/org/apache/lucene/search/TopScoreDocCollector.java ;
   [snippet] https://www.elastic.co/search-labs/blog/more-skipping-with-bm-maxscore
5. **Cap the L5 delta group** (Lucene slices: ≤ 250k docs or 5 segments per
   slice) so the group never becomes the slowest task. [read]
   https://docs.opensearch.org/2.16/search-plugins/concurrent-segment-search/

Already covered here (coverage check): tiered merging / live-generation cap
(`02_DESIGN.md` §1.7, L1), fewer stores (L2), grouped small segments (L5),
owner-routed probes (L3), parse once (L4), livedocs + Rust gather skip (O10),
stamped cache key (R1), prefault before serving (doc 10 §4), rebuild versus local
maintenance (§5 above), overlay-scored updates (`08_…` #1), real-time designs
of the same shape (`01_RESEARCH.md` §2). Earlybird reference:
[snippet] https://cs.uwaterloo.ca/~jimmylin/publications/Busch_etal_ICDE2012.pdf
