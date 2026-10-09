# 02 — Design: three tiers over an immutable base, any source, any rate

**Status:** ACTIVE

**2026-09-29 — IMPLEMENTED; serving efficacy UNMEASURED.** First measured
results 2026-09-29 are folded in below (M7 FAIL §4.1, livedocs §4.3, twin
rebuild §1.7, R1 in §3, open issues §3.1; M1 gate-off parity PASS on the clean
run, 1 pass, measured on aa0fc405 — `03_SPIKE_PLAN.md` addendum; **M4 read
amplification FAIL and M5 reload PASS folded in 2026-09-30**, §3 S1/S4 and §4
items 2 and 6). Every other
number here is *est.*
or a synthetic-test fact unless it cites a results file. The measured base
facts it leans on are cited to their docs.

## 1. The shape

```
   any source ──adapter──▶ DocRecord ──classify (content-hash diff)──▶ encode (GPU/CPU)
                                                                          │
   L0  MUTABLE buffer    tantivy delta_buffer (delete+add+commit)  +  exact sparse (RAM) ◀── ledger records (gen 0)
        searchable now   ───────────── freeze (flush_docs / flush_bytes / cap) ─────────────▶
   L1  IMMUTABLE gens    gNNNN/{sections/<base>__<era>/tantivy+abstracts.sqlite, meta.sqlite, seismic/*.dotvbyte.v2.mmap}
        + newest-wins    generations.json (stamp, masks, commit point) + shard_manifests/shard_manifest-<stamp>.json (base 8 + one per gen)
        masks            ───────────── compact (rebuild N gens → 1 from ledger records) ─────▶
   L2  IMMUTABLE base    the 2026-06-16 150M build: 10 tantivy sections, meta.sqlite, sidecars, 8 SEISMIC shards
                         (never touched; folded only by a full rebuild that REPLAYS the ledger)
```

Only L0 is ever written in place. L1 directories are staged as
`gNNNN.building/` and renamed once complete; `generations.json` is written
last and atomically, and the serving reader keys everything off it.

### 1.1 Canonical record (`spike/delta_ingest/records.py`)

`DocRecord(id, title, abstract, year, type, is_oa, doi, source, updated_at,
sparse_field?, extra)`. Ids: a bare `W…` (or openalex.org URL) is canonical
from ANY source and supersedes that work; everything else is
`<namespace>:<local id>` (`arxiv:2401.01234`, `zotero:ABCD`, `doi:10.…`) and
lands in `docs_other` (TEXT PK) exactly like the base's non-W ids. Non-W ids
have no OpenAlex abstract fallback, so every delta generation writes hot
sections (sidecar mandatory).

Two hashes drive the change detector: `content_hash` over
(title, abstract, year, type, is_oa, doi) decides "re-index or skip";
`encode_hash` over the encoder text (`f"{title} {abstract}".strip()`,
byte-identical to the retired splade_indexer that produced the base vectors)
decides "re-encode or reuse the stored vector". Citation-count churn (§1.1 of
`01_RESEARCH.md`) hits neither.

### 1.2 Adapters (`adapters.py`)

Duck-typed: `name`, `iter_records(state)`, `iter_deletions(state)`, cursor in
`state` (the ledger persists it after every batch — a kill costs one batch).
Shipped: `JsonlAdapter` (JSONL/CSV/TSV with a column mapping; `{"_delete": id}`
lines are deletions — the "any datapoint" path), `OpenAlexSnapshotAdapter`
(partition-date watermark + `deleted_ids.csv.gz`, network injected),
`OpenAlexApiAdapter` (cursor paging, key mandatory, `meta.cost_usd` summed).
arXiv/Zotero/S2 adapters are ~30 lines each over their existing clients
(`scripts/arxiv_fetcher.py`, `src/lib/zotero.py`, `src/lib/semantic_scholar.py`
already produce the fields) — not written yet.

### 1.3 Ledger (`ledger.py`) — the only continuously written store

`<delta_root>/ledger.sqlite` (WAL): `sources` (cursors), `docs` (id →
hashes, status, generation, in_base), `records` (full record JSON incl.
`sparse_field` — the spool that makes compaction and the eventual base
rebuild replays, not re-downloads/re-encodes), `generations`, `tombstones`,
`history` (id, gen) for docs re-updated after publication. `mask()` derives
`{"deleted": [...], "superseded": {id: newest_gen}}`.

### 1.4 L0 buffer (`buffer.py`, reader in `delta_layer.py`)

tantivy is mutable off-the-shelf; the buffer index reuses `SectionBuilder`'s
schema, so the retriever treats it as one more section (`delta_buffer`, no
era suffix → never era-pruned; year filter still applies inside tantivy). The
serving process reloads it per query (`idx.reload()` = a meta.json stat).
SPLADE side: an exact inverted-dict dot product over the buffered vectors,
rebuilt from the ledger when its `(count, max rowid)` signature changes
(append when rows only grew, full rebuild otherwise). Records of a generation
that is still `building` stay visible in the buffer, so a long SEISMIC build
opens no visibility gap.

### 1.5 L1 generations (`generation.py`)

`build_generation` = `SectionBuilder` per `<base>__<era>` (hot, no
`sparse_field` given so no BMP is emitted) + one `meta.sqlite` + the SEISMIC
chain: `SeismicIndex.build` (G2-locked params) → `c1a_mmap_index` (f16 mmap
layout) → `convert_f16_to_dotvbyte --value-scale perdoc` (the served
`dotvbyte_fixedu8_v2` format; the E5 block-walk reorder is skipped — it bought
cold-latency on 18.8M-doc shards, irrelevant at delta size). Each stage
records success or why it was skipped; `mmap_dir` is the most advanced layout
that exists, so a host without the Rust bins still publishes tantivy + meta
(SPLADE leg then lacks those docs until the buffer freezes elsewhere).
`publish` composes the shard manifest = base shard records (from the
served manifest ladder or `--base-shard-manifest`) + one record per
generation, `n_shards` = total (satisfies the loader's partial-corpus gate).
Since 2026-10-08 it goes to a NEW file per publish
(`shard_manifests/shard_manifest-<stamp>.json`, never an existing path) and
`generations.json`, written last, names it — so `generations.json` is the
single commit point (before, `shard_manifest.json` was rewritten in place
first; doc 10 addendum 2026-10-08 "F5 implementation readings").

### 1.6 Newest-wins masks

`keep_hit(id, origin)`: deleted → drop everywhere; `superseded[id] = g` →
keep only the copy whose origin is `g` (base = `None`, buffer = `0`, gen =
`g`). BM25F hits are tagged with their section's origin before the leg
merge, so the base copy of an updated doc never gets an RRF vote. SEISMIC
results arrive already score-deduped across shards (`_merge_topk`), so the
SPLADE leg can only apply `deleted` and "buffer is newest" exactly; for an
updated doc whose newest copy is a delta SHARD, base-vs-delta wins by score,
not recency (§4 issue S5 — the fix is shard provenance in `_merge_topk`).
Meta/abstracts resolve superseded ids delta-first, so hydration shows the new
title.

### 1.7 Compaction (`compact`, `auto_compact_plan`)

No merge primitive exists (SEISMIC: none; tantivy-py: not exposed), so
compaction = build a NEW generation from the ledger's records of N old
generations (vectors reused, no GPU), publish, rename the old dirs
`*.compacted` for the operator to delete. `auto_compact_plan` is
TieredMergePolicy-lite: above 8 live generations, merge the smallest run
whose sizes are within 10× of each other. The top of the tier — folding into
the base — was written here as "a full 150M rebuild fed by `spool +
ledger.records`, design-only (the spool itself is gone)".

**Corrected 2026-09-29:** for the SPLADE/SEISMIC leg the fold-in is a
**per-shard rebuild from the f16 twins**
(`data/seismic_150m/index/plan01/global_shard{0..7}of8.mmap`, READ-ONLY,
which hold every doc's full stored sparse vector + doc mapping): twin →
jsonl (minus deleted ids, plus delta docs) → `SeismicIndex.build` with the
G2-locked params → `c1a_mmap_index` → `convert_f16_to_dotvbyte --value-scale
perdoc`. State: **build chain MEASURED; parity FAILED its bar → premise
UNVERIFIED** (item D, shard 0, 2026-09-29,
`data/eval_results/delta_ingest_twin_rebuild_20260929.json`, commits
aa0fc405 harness + bar, aa5f8dd4 interim, 3de2838d final): 18,799,322 docs / nnz 1,647,141,424
reproduced exactly; 5,000/5,000 sampled forward rows identical after token
remap; dump 220 s (38.9 GB jsonl), build 1,919 s wall under host load
(original 1,150 s), peak RSS 8.2 GB resident, c1a 365 s, dotvbyte 195 s,
dv-v2 5,541,633,957 B vs served 5,543,274,243 B. Parity vs the served
shard (bar: mean overlap@10 ≥ 0.99 on each set, `03_SPIKE_PLAN.md` M9):
120 topics **0.9858** (min 0.8, 106/120 identical top-10, overlap@200
0.9636); 100 diverse **0.9870** (min 0.9, 87/100 identical, overlap@200
0.9518) — **FAIL**. The forward index round-trips exactly, so the gap is
*inferred* (not measured) to come from the posting side (k-means blocks,
summaries; token-id order differs because `generation.py` passes no
`input_token_to_id_map`, plus seed/thread scheduling). Whether two stock
builds of the SAME input agree with each other is UNMEASURED, so the 1.3-point
gap cannot yet be attributed to the twin being an insufficient input versus
ordinary rebuild drift. The twin route is neither refuted nor shown to work.
Open next step (unmeasured, ~30 min): a second build of the same jsonl
(optionally with the original token map) compared against the first. The tantivy/meta/sidecar legs of a base
fold-in still have no rebuild input (P1); only the SEISMIC leg is covered.

### 1.8 Serving hooks (`retriever.py`, gate `SFU_DELTA_ROOT`)

`_load` registers delta sections/abstract stores; `_bm25f_leg` tags origins
and masks; `_splade_leg_seismic` masks and merges the exact buffer results by
score; `_meta_rows` resolves superseded ids delta-first and falls back to
delta meta for misses; `fetch_abstracts` adds buffer abstracts;
`_seismic_backend` prefers the composed manifest when the env is unset (a set
`SFU_SEISMIC_SHARD_MANIFEST` still wins, with a warning that delta shards are
not served); `reload()` drops the SEISMIC backend when the delta stamp
changed; `metrics()["delta"]` reports the layer. Gate unset ⇒ no code path
differs (26/26 stack tests unchanged, 94/94 neighbouring suites).

## 2. Resource profiles — one pipeline from laptop trickle to server bulk

| dial (`profiles.py`) | `laptop` | `desktop_gpu` (this box) | `server` |
|---|---|---|---|
| encoder | PyTorch fp32 CPU, batch 8 | TRT→PyTorch auto, batch 64 | TRT CUDA, batch 128 |
| ingest batch / rate | 200 docs, 20 docs/s throttle | 2,000, unthrottled | 10,000, unthrottled |
| freeze at | 20k docs / 256 MB | 500k / 2 GB | 5M / 16 GB |
| buffer cap | 20k | 100k | 500k |
| RSS abort | 3 GB | 12 GB | 48 GB |
| SEISMIC threads / snapshot parts per run | 2 / 1 | 8 / 4 | 16 / all |
| `os.nice` | +10 | +5 | 0 |

Throughput anchors: doc encoder TRT **3.1k docs/s** on the RTX 4070 (docstring,
measured in the retired indexer); CPU fp32 *est.* 5–20 docs/s per core;
`SectionBuilder` hot sections **~375 docs/s per worker** (abstracts zstd-19 is
the bottleneck — `THIN_CLIENT_SWAP.md` §Build RAM); SEISMIC build near-linear
(§3 of `01_RESEARCH.md`). So a 1M-doc generation on this box is *est.*
~6 min encode + ~45 min section build + minutes of SEISMIC; the laptop
profile freezes 20k-doc generations in *est.* ~10 min each after ~1 h of
CPU encoding. Every stage is resumable from the ledger.

## 3. Engine-interaction matrix (what each served component does with a delta)

| Component (served today) | Delta layer touches | Interaction | Issues / costs |
|---|---|---|---|
| **tantivy BM25F**, 10 base sections, era-pruned, raw-score merge across sections | nothing in base; adds `delta_gNNNN:<base>__<era>` sections + `delta_buffer` | searched like any section; era suffix keeps `_era_skip` working; buffer reloads per query | **T1** BM25 IDF is per-section and the leg merges RAW scores: a tiny segment's rare-term IDF is extreme, so delta docs can outrank base docs for terms rare in the small segment (pre-existing across 10 sections; worse at delta size — measure M3). **MEASURED 2026-09-30 (M3): the opposite on corpus (a)** — an updated doc's delta copy scores 0.982× its base copy (median; p5 0.846, p95 1.005, only 11.3% higher), median rank change 0 over 331 docs, 1 of 1,200 fused top-10 slots displaced across the 120 topics — PASS; the rare-term case for NEW docs (corpus (b)) is unmeasured (`03_SPIKE_PLAN.md` M3 row). **T2** +1 parse/search per section per query (*est.* 1–3 ms each). **T3** one writer per index (flock) — the ingest process owns the buffer writer; a stale lockfile after a crash must be removed. **T4** LogMergePolicy never re-merges the base segments; buffer segments merge at ≥8 similar ones; after each freeze the buffer keeps tantivy tombstones until a merge — reset the buffer dir when empty (not automated). |
| **SEISMIC**, 8 immutable dv-v2 shards, parallel federation, `_merge_topk` score-dedupe, k′=max(2k,100) | nothing in base; composed manifest = 8 + one shard per generation | loader accepts any shard count when `n_shards` matches; delta shards go through the same c1a + dotvbyte chain (E5 reorder skipped) | **S1** +1 thread and +k′ candidates per shard per query; sequential federation adds Σ latency. **MEASURED 2026-09-29 (M4, parallel): 27.7 ms p50 per live generation** (primary OLS; paired per-query median 14.8), of which the SEISMIC fan-out is ~11 ms/gen by means (7 per-query median), BM25F per-section work 5.2, delta abstract probes 4.8 — bar +8 ms/gen **FAIL**; compaction half and sequential federation NOT MEASURED (`03_SPIKE_PLAN.md` addendum 2026-09-30, `spike/delta_ingest/M4_M5_FINDINGS.md`). **S2** mlock/hot-set budgets are divided by `len(shards)` — deltas dilute the base's F4/hot-set budgets slightly. **S3** pruning (`n_postings`, summaries) is corpus-relative: a delta shard is differently pruned; per-doc value scale keeps forward values comparable, recall on small shards **MEASURED 2026-09-30 (M2, 50k-doc generation): own-title recall@10 of updated docs 0.8195 from the delta shard vs 0.7071 for their base copies (ratio 1.159, PASS on 1,352 queries), delta-shard overlap@10 vs exact 0.9968–1.0; the advantage is the small shard's near-exact search, not rank parity (`03_SPIKE_PLAN.md` M2 row). **S4** `_seismic` loads once per process → `reload()` now drops it when the delta stamp changes; reopen = re-mmap 8 shards (page cache stays warm; anon floor ~0) — **MEASURED 2026-09-30 (M5): reload() ≤ 1.8 s, re-open ≤ 3.7 s, first query 1.60–1.82× warm — PASS both bars** on 9- and 16-shard manifests; prefault/mlock state (F4/F6 levers) is lost until re-applied. **S5** superseded base-vs-delta copies of an UPDATED doc are chosen by score, not recency (§1.6). **S6** a set `SFU_SEISMIC_SHARD_MANIFEST` (the documented one-env rollback) silently excludes delta shards — a warning is logged. **S7** without `SFU_SEISMIC_SHARD_FAULT_BOUNDARY=1`, a broken delta shard fails the whole leg (BM25F fallback). |
| **Query encoder** (CPU ONNX, fused) | second encode of the query when the buffer is non-empty | `_delta_merge_sparse` calls `encode_splade` again | **Q1** *est.* +10–40 ms per query only while docs sit in the buffer; fix = a `search_vec` entry on the sharded backend (not done). |
| **meta.sqlite** (24.9 GB, staged, opened `immutable=1`) | never mutated; per-generation `meta.sqlite` + buffer rows from the ledger | superseded ids resolved delta-first; misses fall through to delta meta; `_post_filter_sqlite` therefore filters delta docs correctly | **M1** +1 SQLite probe per generation for superseded ids and misses (bounded by compaction). **M2** the staged-copy lever (`SFU_META_STAGE_DIR`) does NOT stage delta meta DBs — on this host `data/thinclient_index` is 9p, so a delta root under it serves meta off 9p (the measured 55× stage penalty, `THIN_CLIENT_SWAP.md` §Filter) → put the delta root on local disk (`SFU_DELTA_ROOT=/var/tmp/...`) until staging covers it. |
| **Ordinals** (opt-in) | nothing | delta ids have no ordinal → SQLite fallback path (already fail-open by design) | none beyond M1. |
| **Abstract sidecar / flat store** (v3 zstd-19 script dicts; flat + locator on one section) | per-generation `abstracts.sqlite` per section (hot); no flat sidecar | `fetch_abstracts` iterates ALL stores for misses | **A1** dictionary economics at delta size: <300 docs/bucket → plain zstd (ratio loss *est.* 20–40%), ≥20k → retrains dicts per generation (CPU); reuse of the base dicts (pre-seeding `meta.zdict_*`) was the lever — **MEASURED 2026-09-30 (M8): it does not help at delta size** (payload +7–8%, store ~1.9× if dicts are copied); on-disk bytes/abstract are 0.31–0.36× the base on corpus (b) (90% duplicate dataset abstracts, uninformative) and 1.47–1.51× on article-like subsets, mostly SQLite locator/page overhead (~95 B) and per-section dicts (~35 B); the likelier lever is fewer, larger stores per generation (`03_SPIKE_PLAN.md` M8 row, `spike/delta_ingest/M8_FINDINGS.md`). **A2** +1 SQLite probe per store per missing-id batch (bounded by compaction). **A3** flat/locator skipped (its durable win was −1.9 GB at 26M docs). |
| **Dense leg** (OPTIONAL, default OFF, DROP verdict) | nothing | delta docs absent from the dense leg | if ever re-enabled, `dense_cache.enqueue` is the hook (not wired). |
| **RRF fusion** (k=60, Python) | masks applied per leg BEFORE fusion | no double vote for an updated doc's base copy | none new; buffer/SEISMIC merge is by score inside the SPLADE leg. |
| **CE rerank, `hydrate_scope`, speculative levers** | nothing | abstracts for delta docs come from delta stores/buffer; the BM25F draft inherits the masks | none. |
| **Result cache** (TTL 6 h) | key suffix `@delta=<stamp>` only when a delta layer is loaded | **R1 FIXED 2026-09-29** (f5da0d24): stamp term = `generations.json` stamp + per-`DeltaLayer`-object epoch + stat signatures of `ledger.sqlite`, `ledger.sqlite-wal` and the buffer's tantivy `meta.json`; gate off → keys byte-identical (24/24 vs the 46ec1182 module); 18 µs per key. Trade-off: any ledger write rotates the key, so the hit rate is low during active ingest. The delta stamp itself changes only on `publish()`, and serving sees it only after `retriever.reload()`. |
| **Packer / hot-cold / personas / `manifest.json`** | nothing | delta sections are never packed, invisible to `request_section_unpack` and cold lists, absent from `manifest.json` | **P1** a full rebuild's `write_manifest`/`merge_section_meta` ignore delta sections → the rebuild MUST replay `ledger.records` (design-only, the base spool is gone). |
| **Staging levers** (`SFU_SEISMIC_STAGE_DIR`) | nothing | delta shards are not staged | same as M2 for shards on 9p. |
| **MCP `reload_index` / `get_index_status` / web GUI** | `reload()` swaps the layer; `metrics()["delta"]` | operator flow = ingest → flush → `reload_index` | none. |

### 3.1 Open issues found by the 2026-09-29 agents (OPEN, not fixed)

| # | Issue | Found by | Verified in code 2026-09-29 |
|---|---|---|---|
| O1 | `_delta_merge_sparse` (`retriever.py`) returns early on `self._delta.buffer_size() == 0`, and `buffer_size()` does not call `refresh_buffer()`: if the buffer was empty when the layer loaded, the SPLADE buffer leg never sees later buffered docs (BM25F unaffected) | G | yes — `delta_layer.py` `buffer_size()` returns `len(self._buffer_rows)` without refresh → **FIXED 2026-09-30** (8a51e48f): `buffer_size()` refreshes the buffer through a stat-gated poll on `ledger.sqlite` + `-wal` (no SQL while unchanged), ledger opened lazily; repro test `scripts/tests/test_delta_buffer_refresh.py` (failed `0 == 4` before the fix), SPLADE/BM25F legs, abstracts and meta all see later-buffered docs; gate-off path untouched (the layer exists only with `SFU_DELTA_ROOT`). Invariant recorded in `docs/CODE_INVARIANTS.md`. **Related gap** (if the buffer's tantivy dir did not exist when the layer loaded, BM25F never saw it until `reload()`) → **FIXED 2026-10-01** (e59ad355): `_bm25f_leg` attaches `delta_buffer` lazily once `tantivy/meta.json` appears (copy-on-write `_sections` rebind under the load lock); test `scripts/tests/test_delta_serving_fixes.py::test_buffer_section_created_after_load_is_searched` |
| O2 | On `publish()` records leave the buffer at once, but serving sees the new generation only after `reload()`; in between those docs can be missing from the SPLADE buffer leg | G | design reading, not reproduced → still OPEN 2026-09-30: cause is `ledger.finish_generation` (`ledger.py:256`) removing records from the buffer before `reload()`; the one-line fix (count unloaded generations as buffer) would parse up to a whole generation with vectors into RAM on every freeze/compaction, so it was not applied. BM25F still sees the docs until the buffer delete that follows the freeze → **FIXED 2026-10-01** (c6a9d4de) for the SPLADE buffer leg, meta and abstracts: the buffer view adds published-not-loaded buffer-derived generations (`_buffer_generations`, ledger `info.from_gens`, kept by `finish_generation` since b6480b58). No re-parse on freeze; compactions of already-loaded generations are no longer parsed into the buffer. Residual OPEN: BM25F misses frozen docs from the buffer delete until `reload()` (design only). Unit-tested on synthetic roots only → **BM25F residual FIXED 2026-10-01 (2fc2cb5c) for one freeze per `reload()`**: frozen docs stay BM25F-visible until `reload()` (`keep_hit` drops buffer-section hits not in the buffer view; `BufferWriter.retain_only` bounds the buffer tantivy to buffer + last frozen generation); second defect fixed in the same commit — ingest auto-freezes never deleted from the buffer tantivy, so BM25F returned frozen docs twice after `reload()`. Residual OPEN (design only): two freezes without a `reload()` between them hide the older freeze from BM25F. Unit-tested on synthetic roots only (`spike/delta_ingest/FIXES_20261001_WAVE3.md`) |
| O3 | `_stamp_cache` in `src/lib/result_cache.py` is declared (and named `global`) but never read or written | G | yes → **FIXED 2026-09-30** (37937f6b): dead global removed; 120 result-cache/draft/speculation tests pass |
| O4 | Ledger holds no content hashes for base docs → the churn filter cannot apply to base documents (M7) | B | per M7 results file → **BUILT + MEASURED 2026-09-30** (6ba3c4de; `seed.py`, `base_hashes` table, `seed-base` CLI): seeded, the ledger reproduces M7's exact proxy on both partitions (`03_SPIKE_PLAN.md` M7-seed row); full seed *est.* 24.6 h and needs the packed abstract sections unpacked locally. **Correction 2026-10-01** (03f1ec42, `spike/delta_ingest/INGEST_FIXES_20261001.md`): only the hot section has abstracts on this host (the non-hot packs hold none), so the full seed cannot be run locally; the hot-section seed is ≈ 4.2 h *est.*, resumable, NOT started; the other ~127M docs need base-era text that is not on this host |
| O5 | DOI prefix trap: base stores the `https://doi.org/` prefix (33,600 raw DOI diffs, 379 after normalising) | B | per M7 results file → **FIXED 2026-09-30** (6ba3c4de): one `normalize_doi` in `records.py` for adapters and seed; in-base DOI diffs 33,600 → 379 |
| O6 | Adapter `min_year=2015` vs base boundary 2010 (199 base docs dropped in the primary M7 file) | B | per M7 results file → **FIXED 2026-09-30** (6ba3c4de): default `min_year` 2010 (overridable); dropped in-base works 199 → 101 (pre-2010 years the base holds anyway; archive sections store year 0, treated as no year). Other year filters NOT aligned: `scripts/snapshot_downloader.py:94` (2015), `spike/archive/inplace_update/prep.py:196` |
| O7 | Snapshot adapter decompresses a whole partition into memory: ingest peak RSS 6.74 GB on both profiles, above the laptop profile's 3.0 GB cap (enforced only in builds) | F | per M6 results file → **FIXED + MEASURED 2026-10-01** (2df356ab): the adapter streams — a local partition is read in place, a remote one is spooled compressed to `--spool-dir` and read line by line. Adapter-only peak RSS 1.527 → 0.024 GB on a 60k-line real subset (41,735 records, identical counts); 0.025–0.026 GB on the full partition (205,358 records; pre-fix ~6.8 GB *est.*). `scripts/experiments/eval_delta_ingest_o7_streaming.py`, `data/eval_results/delta_ingest_O7_streaming_20261001.json`. Whole laptop-pipeline peak RSS after the fix UNMEASURED |
| O8 | Encoder labels do not match the runtime: desktop_gpu falls back TensorRT → CUDA (onnxruntime 1.26, TensorRT libs not found) while labelled `onnxruntime_trt_iob_fp16`; CPU runs fp32 while labelled `pytorch_fp16` | F | per M6 results file → still OPEN 2026-10-01 (lives in `doc_encoder.py`, not the serving path; proposed: add a per-instance runtime label beside the class label, do not rename it — results files key on it) → **FIXED 2026-10-01 (c7cd095f)**: per-instance `runtime_backend` beside the unchanged class label (e.g. `onnxruntime_cuda_iob_fp16` on this host, libnvinfer missing); earlier numbers stand, their label means "requested backend" (`spike/delta_ingest/FIXES_20261001_WAVE3.md`) |
| O9 | No CLI flag for the ordinal dir (publish reads the `ordinal_dir` argument or `SFU_THINCLIENT_ORDINALS` only) | C | yes — `generation.publish` → **FIXED 2026-09-30** (11fc76a4): `--ordinal-dir` on ingest/flush/compact/publish, threaded through `freeze_buffer`/`compact` to `generation.publish`; env stays the fallback; tests cover every subcommand, relative path, fallback and precedence |
| O10 | Livedocs Python filter costs 6.5–10.6 ms p50 per query, not small next to the ~65 ms warm traverse; the Rust gather-time skip (§4 item 3) is the design-only fix | C | per livedocs results file → **2026-10-01 wave 3: IMPLEMENTED on fork branch `livedocs-skip` (620f1d2), EFFICACY UNMEASURED** — patch `spike/delta_ingest/patches/seismic_livedocs_skip.patch`, side-path build only, installed `.so` untouched; design changed from the §4 item 3 sketch: dead docs are pre-loaded into the traversal's `visited` set (no new instruction in the candidate loop; O(D) inserts per query per shard, D ≈ 19k in shard 0). MEASURED on served shard 0, 120 topics + 100 diverse (`data/eval_results/delta_ingest_O10_rust_livedocs_20261001.json`, `scripts/experiments/eval_delta_ingest_o10_rust_livedocs.py`): no-bitset parity branch `.so` vs installed 220/220 byte-identical, `search_skip` with an empty dead set 220/220; skip correctness 0 dead ids returned on both fixtures, top-10 identical to the Python filter 220/220 (0.1 % deletes) and 218/220 (plus each query's top-3 deleted; overlap@10 0.99909). Semantics differ from the Python filter (each shard returns k′ live docs). **Cost: no valid timing** (first run INVALID — shared lock, fixed arm order; order-alternating rerun queued, also shared-lock/indicative). Serving hook design only (proposed gate `SFU_DELTA_RUST_SKIP`); shipping needs an exclusive-lock timing against the 2026-09-30 owner bar and an operator `.so` swap (`spike/delta_ingest/O10_RUST_LIVEDOCS_FINDINGS.md`, e96630a1) |
| O11 | Fixed by B, recorded: `s3://` manifest URLs are now mapped to HTTPS in the adapter; the snapshot manifest key is `data/jsonl/works/manifest.json` in the OpenAlex bucket (`adapters.py` `OPENALEX_WORKS_MANIFEST`; a `data/works/manifest.json` path given in the dispatch was wrong) | B | — |
| O13 | `AbstractStoreWriter._train` (`src/lib/thinclient/abstracts.py` ~185–187) can compress a bucket with plain zstd while the reader (~720–725) would decode it with the latin dictionary — only if a non-latin bucket reaches 20,000 docs before latin is trained and its own training fails; not observed in any measured store | M8 agent 2026-09-30 | yes (code reading), not reproduced → **NOT A DEFECT 2026-10-01** (6fc81e66): plain dictID-0 frames decode identically under the latin dictionary; a writer-level test round-trips 800 docs; invariant recorded |
| O14 | `reusable_sparse` (`spike/delta_ingest/ledger.py:152`) reuses only ledger-stored vectors, so a seeded base doc whose encoder text is unchanged (5,530 of 9,965 on the M7 primary hot section) is still re-encoded; the saving the seed enables needs a base-SEISMIC-vector reuse path | seed agent 2026-09-30 | yes → **IMPLEMENTED 2026-10-01, flag off by default** (504ff2ca, d985b70d, 56d38a39): `spike/delta_ingest/base_vectors.py`, `ingest --base-forward-dir/--base-locator-dir`, exact-or-refuse. Reader exactness MEASURED on the real shard-0 twin: 20,000/20,000 random rows reused and bit-equal to an independent read (locator 18,799,322 ids, 0 duplicates). GPU check on 1,882 text-unchanged docs: re-encoded nnz 83.18 vs base 83.00, cosine 0.99998, term Jaccard 0.9935, 0 bit-identical — reuse is the only way to keep a content-only copy identical to its base copy. `data/eval_results/delta_ingest_O14_base_reuse_20261001.json`. **Encode time saved UNMEASURED** (bound 55.5 % of seeded in-base updates *est.*); equality of the served dotvbyte codes UNMEASURED; locators for shards 1–7 not built → **2026-10-01 wave 3 (c0a02924): equality of the served dotvbyte codes MEASURED** — reused base vectors give the same served codes as the base copy on 20,000/20,000 shard-0 rows; encode time saved still UNMEASURED (harness `f839a5e4`/`127da3c1` written, run NOT RUN); locators for shards 1–7 not built → **2026-10-02: encode saving MEASURED — none on this GPU** (reuse ON 13.66 s vs OFF 13.13 s end to end on 8,047 updates, −4.1 %; 704 reused via the shard-0 locator; `data/eval_results/delta_ingest_O14_reuse_saving_20261001.json`); reuse's value is bit-identical copies, not GPU time; CPU profile NOT RUN |
| O15 | `AbstractStore` (`src/lib/thinclient/abstracts.py:682`) opens the abstract SQLite read-write, not `immutable=1`/read-only by construction | seed agent 2026-09-30 | yes → **FIXED 2026-10-01** (5ede9310): opened through a `file:` URI with `mode=ro`; invariant in `docs/CODE_INVARIANTS.md` |
| O16 | `cli.py:191` default `--delta-root` is under `data/thinclient_index/`, so `seed-base` (or any subcommand) without `--delta-root` writes a ledger there — the documented default (`SFU_DELTA_ROOT=1` == `<index_root>/delta`) is a footgun on this host where that tree is 9p and `data/` is not to be written casually | seed agent 2026-09-30 | yes → **FIXED 2026-10-01** (8520e6e2 resolver, 86b75786 CLI wiring): `delta_layer.resolve_delta_root(..., for_write=True)` (explicit > `SFU_DELTA_ROOT` > `<index_root>/delta`) refuses `data/seismic_150m` and an implicit root under `data/`; serving resolution unchanged; `docs/ENV_GATES.md` |
| O17 | Base `is_oa` looks stale or biased to 0: every `is_oa` flip among the 5,225 metadata-only in-base updates on the M7 primary file went 0 → 1 | seed agent 2026-09-30 | INFERRED, unverified → **2026-10-01: base `is_oa` was never populated** (0 of 300,000 sampled meta rows; the retired indexer and sync scripts never wrote it; a random-probe sample timed out on 9p). Inferred, not measured: `open_access_only` matches no base doc. OPEN — owner decision (options in `spike/delta_ingest/INGEST_FIXES_20261001.md` §O17) → **owner decision 2026-10-01: option (a)**, a base `is_oa` bitmap from one snapshot pass served as an override (no reindex); IMPLEMENTED 2026-10-01 behind `SFU_OA_BITMAP` (default OFF, fails closed; `src/lib/thinclient/oa_overlay.py`, builder `spike/delta_ingest/oa_bitmap.py`): premise MEASURED (0 of 150,413,098 base docs carry `is_oa`; `open_access_only` returns 0 results on 120/120 topics); gate-off identity PASS 120/120; **full bitmap BUILT 2026-10-01 23:07Z** from the OpenAlex 2026-09-23 snapshot (2,040/2,040 partitions, 476,196,327 works streamed in 7.42 h, nothing stored): **141,288,198 of 150,413,098 base docs known (93.93 %) — 110,525,184 open access, 30,763,014 not; 9,124,900 unknown (6.07 %, absent from the snapshot; served as `is_oa: null`, excluded by `open_access_only`)**; 37.6 MB; spot check 100,000/100,000 lookups equal the raw scan (`data/eval_results/delta_ingest_O17_bitmap_build_check_20261001.json`). **Gate-ON serving efficacy NOT RUN** (queued); with the gate on the reranker's full-text feature reads `is_oa`, so final order can change on unfiltered queries too (UNMEASURED). Ingest effect MEASURED with the full bitmap on the M7 primary seeded subset: updates 8,047 → 3,582, `is_oa`-only updates 4,465 → 0, must-encode unchanged at 2,517 (`spike/delta_ingest/OA_BITMAP_FINDINGS.md`, ff4adde6) → **2026-10-02: gate-ON efficacy MEASURED** — `open_access_only` 0 → 6,000 fused results over 120 topics (6,000/6,000 known-OA in the scan); unfiltered fused lists identical 120/120 but final top-10 changes on 114/120 and nDCG@10 falls 0.7053 → 0.6835 (reranker full-text feature reads `is_oa`); latency UNMEASURED; gate stays OFF pending an owner decision (`data/eval_results/delta_ingest_O17_oa_bitmap_20261001.json`) |
| O18 | `generation.py` (`build_seismic_shard`/`build_generation`, ~60–150): `generation.json` records the absolute `seismic.jsonl` / `seismic.stock` paths under `gNNNN.building/`, which no longer exist after the rename to `gNNNN/`; serving unaffected | M2 agent 2026-09-30 | yes → **FIXED 2026-10-01 (d4fedcef)**: `jsonl`, `stock`, `mmap_dir` recorded relative to the generation dir; no reader used the absolute fields; generations built before the fix keep their strings (`spike/delta_ingest/FIXES_20261001_WAVE3.md`) |
| O19 | `_bm25f_leg` (`src/lib/thinclient/retriever.py` ~988–1002) sanitises only non-alphanumerics, so tantivy's `parse_query` raises `ValueError: Syntax Error` on a query containing the upper-case operator word `IN` (verified 2026-09-30 on a 1-doc index: "advances IN machine learning" fails, lower-case parses; `AND`/`OR`/`NOT`/`TO` parse). Hit 10 of 350 real titles (2.9%) in M3. `search_rrf`'s leg runner (`_run_legs`, ~lines 770–790) and `search()` (~818) do not catch it, so a user query such as "advances IN deep learning" raises out of `search_rrf` instead of degrading — user-visible. Fix: lower-case the sanitised text before `parse_query` (tantivy's default tokenizer lower-cases anyway, so results are unchanged) — **FIXED 2026-09-30** (`bm25f_query_text`, test `scripts/tests/test_bm25f_query_text.py`: the failing string parses, the sanitiser is unchanged apart from case, hits identical on a default-tokenizer index; invariant in `docs/CODE_INVARIANTS.md`). **CORRECTION 2026-10-01, OPEN:** on the served index the lower-casing DOES change BM25F hits for at least 1 of 120 natural topics (index 117, "How does psychological safety affect whether people speak up and how teams perform?"): fused/final results differ from aa0fc405 and reverting only `bm25f_query_text` reproduces the old row byte-for-byte (`scripts/experiments/eval_delta_ingest_m1_o19_diag.py`, `spike/delta_ingest/M1_FINDINGS.md`). The "results are unchanged" claim above and in 99e2b663 holds only for the unit-test index; the parser-side cause is NOT investigated, and which of the two rankings is better is UNMEASURED | M3 agent 2026-09-30; runner verified and fixed by the coordinator; correction by the M1 agent 2026-10-01 | yes → **CAUSE FOUND + FIXED 2026-10-01 (d4e6a29f)**: tantivy's QueryParser collapses a repeated query word by surface form only, before the tokenizer lower-cases, so a case-variant repeat ("How … how", topic 117) counted the term twice before 99e2b663; lower-casing is kept as the consistent behaviour (ranking quality UNMEASURED). Parse differs pre vs post on 1/120 topics, 27/350 M3 titles, 4,581/50,000 titles (`data/eval_results/delta_ingest_O19_case_parse_20261001.json`, `scripts/experiments/eval_delta_ingest_o19_case_parse.py`). Two parse failures 99e2b663 still had (Unicode whitespace 384, dotted İ 55 of 50,000 titles) FIXED; an unparseable query (5 of 50,000, over-long CJK runs) now returns no BM25F hits instead of raising. Served-index hit counts NOT RUN (agent stopped before its shared-lock run) (`spike/delta_ingest/FIXES_20261001_WAVE3.md`) → **2026-10-02: served-index hits MEASURED** — of 194 titles whose parse differs, top-1 same on 189, known-item rank better 5 / worse 2 / equal 187 (`…O19_case_parse_20261001.json` key `hits`) |
| O12 | Library imports from the `.venv` on the `/workspaces` (9p) mount intermittently fail with `[Errno 12] Cannot allocate memory` under load, which silently degrades a serving process: the SPLADE leg falls back to BM25F-only and the cross-encoder is unavailable (M1 run3: 3 errors before topic 1, final top-10 0/120 identical). Item D hit the same ENOMEM importing transformers; item C measured slow 9p ordinal lookups. **Root cause UNVERIFIED** (item A infers 9p directory reads, not process memory — ~25–28 GB was available) | A (also D, C) | log evidence in `data/eval_results/delta_ingest_M1_20260929.json` `log_scan`; not reproduced → **ROOT CAUSE VERIFIED 2026-09-30 20:25Z** (coordinator, strace on a failing import): the kernel 9p client returns ENOMEM from `read(fd, buf, 48565)` and `getdents64(fd, buf, 32768)` on `/workspaces` (drvfs 9p) — its request buffers need contiguous kernel pages, and `/proc/buddyinfo` showed the Normal zone with one free order-4 block and none above while MemFree sat at 160–900 MB under ~25 GB of page cache (fragmentation left by a 21 GB anonymous peak of a concurrent run). It is not process memory (MemAvailable 25–27 GB) and it is intermittent (an import probe passed 2/10, then 0/8, then 1/12). Already-loaded processes and page-cache-resident files are unaffected. `/proc/sys` is read-only in this container, so `vm.compact_memory` / `vm.min_free_kbytes` cannot be set from inside; a transient 4 GB THP mapping forced partial compaction without curing it. Workaround: a local-disk mirror of the venv (`/home/vscode/work/venv_local`, rsync with retries) so imports bypass 9p, plus pre-warming the page cache for `models/` and `src/` before a run; harnesses keep the health assertions. Durable fix is host-side (container privileges for sysctl, or the venv/models on local disk by construction) |

## 4. Immutability — the efficiency issues, honestly

1. **Write amplification.** An update rewrites the whole document into a new
   segment; the stale copy stays until compaction, at ~1.0–1.3 KB/doc
   (tantivy ~0.3 + SEISMIC dv ~0.3 + meta ~0.15 + sidecar ~0.35–0.5, per
   `STORAGE_BUDGET_150M.md`, small-segment overheads on top). With OpenAlex's
   ~15%/month churn this is only survivable because of the content-hash diff
   (§1.1): real title/abstract changes are *est.* 1/15–1/30 of touched records.
   **MEASURED 2026-09-29 (M7): this premise FAILED its bar.** On two real
   snapshot partitions touched:must-encode was ≈1.15:1 and ≈2.61:1 in slice
   (*est.* ratios; bar: < 3:1 means the write-amplification argument is
   wrong; `data/eval_results/delta_ingest_M7_20260929*.json`). Most touched
   in-slice records are NEW works (160,347 of 194,931 in the primary file),
   which must be encoded regardless, and among in-base docs the encoder text
   changed for 25.3% of an exactly-compared 9,965-doc section. Design
   consequences: (a) **the ledger cannot apply the filter to base documents**
   — it holds no content hashes for base docs, so every in-base id is
   classified "updated" (ledger as coded = 1.00:1); a base-hash seed (from
   meta + sidecar text) would be needed — **BUILT + MEASURED 2026-09-30**
   (`03_SPIKE_PLAN.md` M7-seed row): seeded, the ledger reproduces the exact
   proxy (3.959:1 among in-base docs), and the whole-partition ratio stays
   ≈ 1.01–1.16:1 because most touched in-slice records are new works; (b) the churn filter does
   not bound write amplification at the rates measured; per-partition ingest
   cost is ~ the partition's in-slice size. UNMEASURED: steady-state
   partition-to-partition churn (the proxy compares against base text from
   the 2026-06-11..16 build, i.e. ~3 months of accumulated drift, over two
   files only).
2. **Read amplification.** Every generation adds one tantivy search, one
   SEISMIC shard, one meta probe and one abstract probe per query — latency
   grows roughly linearly with live generations. Compaction is therefore
   load-bearing, not optional (`auto_compact_plan` at >8 gens); bar M4.
   **MEASURED 2026-09-29 (M4): FAIL** — 27.7 ms p50 per live generation
   (primary; paired median 14.8) against +8; p50 2,307 → 2,536 ms from 0 to
   8 generations. Roughly half the tax is outside SEISMIC (BM25F per-section
   parse/merge/mask 5.2 ms/gen, delta abstract-store probes 4.8 ms/gen), so
   compaction cadence and per-generation store count are the first levers;
   whether compaction returns to within 5% of one generation is NOT
   MEASURED (the compaction arm never ran). `03_SPIKE_PLAN.md` addendum
   2026-09-30; `spike/delta_ingest/M4_M5_FINDINGS.md`.
3. **Mask growth.** `deleted`/`superseded` are JSON lists in
   `generations.json` loaded into Python sets: *est.* ~100 B/id → a quarterly
   OpenAlex delta with tens of millions of `deleted_ids` rows is **not**
   servable this way. Planned fix: a livedocs bitset over the base's ordinal
   space (`ordinals.py` already maps id→ordinal; 150M bits = 19 MB) plus
   per-generation bitsets — the Lucene `.liv` model.
   **2026-09-29: the livedocs bitset is now the core delete mechanism;
   the JSON list is the fallback.** Python per-shard filter **IMPLEMENTED,
   gates PASS PARTIAL (101/120 topics)** (item C, commits 6f5dd471, 35b11c75,
   af15c2e1, 333a3f9b, 3cc64680; `data/eval_results/delta_ingest_livedocs_20260929.json`):
   - Format: `.liv` file = 80-byte header (magic `SFULIV01`, version 1,
     nbits, popcount, crc32, 40-byte `ordinal_space_id`) + bit payload;
     18,801,718 bytes for 150,413,098 bits; mmapped; fails closed.
   - `publish()` writes `<delta_root>/livedocs/base-<stamp>.liv` BEFORE
     `generations.json` when base ordinal arrays are available (`ordinal_dir`
     argument, else `SFU_THINCLIENT_ORDINALS` resolved against the base
     index root); deletes and base copies superseded by a delta/buffer copy
     go into the bitset, and `mask.deleted` keeps only ids with no base
     ordinal. Old roots without a `livedocs` key serve from the JSON lists
     unchanged.
   - Applied via the `_shard_result_filter` hook in
     `sharded_seismic_backend.py` BEFORE `_merge_topk` (fixes **S5**,
     including generation-vs-generation), `filter_hits` for BM25F, and a
     post-merge `filter_ids` fallback for backends without the hook (S5
     remains open on that fallback only).
   - Measured: G1 empty-bitset bit-identity fused 101/101, final top-10
     101/101; G2 synthetic delete (150,413 random ordinals + per-topic
     top-1s) 0 leaks, relative order kept 101/101; 284 candidates dropped
     over 101 queries (max 3 per shard) at 0.1% density — heavier densities
     UNMEASURED; filter cost p50 6.5 ms (empty) / 10.6 ms (synthetic) per
     query, not small next to the ~65 ms warm traverse. Ordinal arrays must
     sit on local disk (9p: ~0.7 s per 100 ids vs 2–50 ms per 800 ids local).
   - **Rust gather-time skip: DESIGN ONLY (not built).** pyo3
     `set_tombstones` on `SeismicIndexDotVByte` (`src/pylib/dotvbyte.rs` in
     the fork) resolving ids to forward range starts, threaded through
     `search_raw_visited` (`src/mmap_io.rs`) and posting-list search /
     `evaluate_posting_block` (`src/mmap_index.rs`), and the same for the
     f16 twin in `posting_list.rs`. Benefit: dead docs never take heap
     slots (no over-fetch, no Python filter cost). Unmeasured.
4. **Compaction cost.** Rebuild, not merge: linear in the merged size, CPU-
   bound in `SectionBuilder` (~375 docs/s/worker hot) and SEISMIC's build;
   no GPU. Folding into the base was written as a full 150M rebuild
   (multi-day); corrected 2026-09-29 — the SEISMIC leg folds in per shard
   from the f16 twins (§1.7: build chain MEASURED ~32 min build + ~9 min
   conversion per shard under load, serial; parity FAILED the 0.99 bar at
   0.9858/0.9870, so the route is UNVERIFIED). Other legs
   unchanged (P1).
5. **Score-space drift across segments** (T1, S3): rank fusion downstream
   hides some of it; the BM25F leg's raw-score merge does not. Candidate
   fixes if M3 fails: per-section score normalisation, or feeding the
   base section's term statistics to delta queries (bespoke).
6. **Reload cost** (S4): re-mmapping 8 base shards on every delta publish is
   the price of "one manifest per stamp". **MEASURED 2026-09-30 (M5): it does
   not matter at this scale — reload() ≤ 1.8 s, first query 1.60–1.82× warm,
   PASS both bars** (the 16-shard root at 1.82 is close to the 2× bar). The
   fix if it ever does is loading delta shards into the live backend without
   dropping the base ones.
7. **Windows of double visibility.** Between `stage()` and the next
   `publish()` a doc re-updated after its generation was published exists in
   both (mask says newest = gen until republished). Bounded by one ingest
   batch; `run_ingest` publishes at its end. Freeze has no gap (building gens
   stay in the buffer view); the buffer copy is dropped by the mask the moment
   `open_generation` moves the doc, before the tantivy delete lands.
8. **Deletes never reclaim base space.** Tombstones only; physical removal
   is the full rebuild.
10. **Changing the on-disk format to absorb updates in place** (decided
   2026-09-29, `04_IMMUTABILITY_RESEARCH.md` conclusion 5):
   - *Slack-space format reorganisation* (PMA / Büttcher–Clarke gaps in
     posting lists): **CLOSED DEAD 2026-09-29 — not worth it; never
     dispatched.** Weeks of Rust, ~1.5–2× space (*est.*), E5 Fix #5A
     measured that padding dilutes page sharing, and new docs still need a
     side buffer first. Listed in `docs/README.md` "Closed tracks".
   - *Forward append-and-repoint* (append a new forward record at the tail,
     repoint the doc's `(forward_offset:48, len:16)` packs, refresh affected
     block summaries — SPFresh-style version map): **DESIGN ONLY**, worth
     building only if M4 shows the double copies cost latency. Unmeasured.
   - *Time/era partitioning of SEISMIC shards* (only recent-year shards
     churn): **DEFERRED 2026-09-29, pending a passing M9 (item D failed
     its parity bar 2026-09-29; rebuild-drift baseline unmeasured) and M4.**
     The M7 result (most in-slice churn is new works) is consistent with
     it but does not measure it.
11. **Fold-in trigger (the "cutback" parameter) — DESIGN ONLY, added
   2026-09-30 at the owner's request; pre-registered 2026-10-01 in
   `10_FOLDIN_TRIGGER_PREREGISTRATION.md` (frozen, nothing run).** Compaction (item 2, `auto_compact_plan`)
   only merges delta generations into larger delta generations; nothing in
   the design ever decides that enough has been bypassed and the new
   information must be committed into a rebuilt base shard. That decision
   needs an explicit, measurable threshold, per SEISMIC shard (a shard is the
   rebuild unit, §1.7): fold shard *s* in when ANY of (a) the live delta docs
   routed to *s* exceed a fraction `SFU_DELTA_FOLDIN_FRAC` of its base docs
   (*est.* 5–10%: at the measured quarter churn of 27% updated + 15% new per
   shard, that is a fold-in every few weeks); (b) the per-query generation tax
   attributed to *s*'s deltas exceeds a latency budget (M4 measured ~28 ms
   per live generation, of which ~11 ms is SEISMIC fan-out); (c) a wall-clock
   cap (`SFU_DELTA_FOLDIN_MAX_AGE`) so a quiet shard still folds eventually.
   The fold is the §1.7 twin route: dump the shard's f16 twin + its live delta
   docs + masks → one jsonl → `SeismicIndex.build` → c1a → dotvbyte → swap the
   shard file under the manifest, then drop the folded generations and rewrite
   the masks; BM25F sections, meta and sidecars fold by the same replay
   (P1). Prerequisites before it can be built: M9's parity bar must pass or
   its build-vs-build drift baseline must show the 0.9858/0.9870 miss is
   build noise (second build of the same jsonl; PARTIAL 2026-10-01 on a
   3M-doc prefix, verdict MIXED: overlap@10 1.000 / 0.996 rebuilt-vs-rebuilt,
   bit-equal 220/220 once the token-id map is pinned — every fold-in or
   compaction rebuild must pass the base's `input_token_to_id_map` with new
   tokens appended; full shard NOT RUN, `03_SPIKE_PLAN.md` addendum
   2026-10-01); a
   per-shard routing of delta docs (today a generation is one shard for all
   sections, so "delta docs routed to *s*" is the blake2b-%-N assignment the
   base uses, not yet computed at ingest); and the write-protection of
   `data/seismic_150m` (`docs/infrastructure/INDEX_WRITE_PROTECTION.md`), since
   the swap is the one moment the base tree is written. Pre-registration to
   write before any run: the trigger values, the parity bar for the folded
   shard vs (base + its deltas) served together (overlap@10 ≥ 0.99 on the 120
   topics + 100 diverse), the fold wall time and peak RSS per shard (~32 min
   build + ~9 min conversion measured under load, M9), and the latency after
   the fold returning to the n0 arm of M4 within 5%.
9. **Crash safety:** ledger writes are transactions; generation dirs stage as
   `.building` and rename; `abort_generation` returns docs to the buffer;
   `generations.json` and the composed manifest are atomic renames, and
   since 2026-10-08 the manifest is a new file per publish, so
   `generations.json` is the one commit point (the earlier in-place rewrite
   of `shard_manifest.json` ahead of it could pair a new manifest with old
   masks after a kill — found by review before F5, doc 10 addendum
   2026-10-08). Not covered: a crash between `finish_generation` and
   `publish` leaves a published generation without a manifest until the
   next `publish` (idempotent). Fold-in crash safety is doc 10 F5.

## 5. What "off the shelf" bought and what stayed bespoke

Off the shelf: tantivy's writer/reader for the mutable tier; SQLite for the
ledger and per-generation meta; `SectionBuilder`, `AbstractStoreWriter`, the
SEISMIC build and conversion chain, the sharded backend's manifest loader —
all reused unchanged. Bespoke and small: the record contract + adapters
(~400 lines), the ledger (~200), the generation/publish/compact driver
(~300), the serving reader + retriever hooks (~350). Nothing new was written
in Rust. `01_RESEARCH.md` §7 has the per-leg verdict.
