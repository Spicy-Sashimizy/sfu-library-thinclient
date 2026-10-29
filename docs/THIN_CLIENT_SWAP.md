# Thin-Client Swap — this container's architecture (2026-06-11)

**Status:** ACTIVE

This development container is the **thin-client testbed**: OpenSearch is removed from
it entirely and the serving path runs the validated no-JVM stack. The original
`sfu-library-mcp` container (150M-doc OpenSearch 3.7 cluster at host port 9200)
is untouched and is used only as a **read-only export source and eval baseline**.

> **2026-10-13 — directory rename:** the serving code moved from `src/` to
> `source/` and the GUI sources from `web/src/` to `web/source/` (owner
> decision: no abbreviated names in the tree). Module names, imports and the
> `lib.*` package are unchanged; `pytest.ini` puts `source` on the path.
> Restore tag `pre-src-to-source-2026-10-13`; record in
> `infrastructure/REPO_REORG_2026-10-10.md` §Addendum 2026-10-13. Ledgers and
> records dated before 2026-10-13 use the old names.

Code-level constraints and env-gate semantics referenced throughout live in
`docs/CODE_INVARIANTS.md` and `docs/ENV_GATES.md` (2026-09-01).

## What runs here now

> **2026-10-06:** everything below describes the local WSL2 serving path. The owner reopened the public
> OCI demo the same day: the tenancy is Pay As You Go and the E5.Flex 8 OCPU/64 GB serve instance was
> rebuilt from its preserved disks (serving since 19:47 UTC; scale-to-zero, wakes only on an invite
> click, 60 min idle stop, 55 h/month cap). Statements further down that the OCI host is "gone for
> good" predate this; state and measured numbers in `scripts/demo_broker/README.md`
> §"2026-10-06 revival" (the demo docs are still under `docs/deprecated/oci_demo/` pending the first
> measured click-wake).

| Leg | Engine | Summary (detail in the subsections below) |
|---|---|---|
| Lexical BM25F | tantivy 0.26 | title^3 + abstract, `index_option='freq'` (positions-off lossless lever), fast-field year/type/is_oa filters, no stored text |
| Sparse SPLADE | **SEISMIC federated mmap** (default since 2026-07-06) | E8 dv-v2 shards served since 2026-07-14; the only SPLADE backend. BMP code path removed 2026-10-11, Qdrant on_disk rollback leg removed 2026-10-12 (owner decision); forensic home of both: branch `archive/bmp-qdrant` |
| Dense | usearch 2.x | b1 Hamming + int8 rescore; **OPTIONAL payload component, DEFAULT OFF since 2026-08-18** (ablation: DROP) |
| Dense warm cache | `lib/thinclient/dense_cache.py` | query-driven delta over the static seed; inert while the dense leg is off |
| Filter stage | `meta.sqlite` (default) · `lib/thinclient/ordinals.py` (opt-in) | the dominant variable is WHERE `meta.sqlite` lives, not the addressing scheme |
| Fusion | Python RRF k=60 | unchanged (`federated_search.py`); routing live-versus-local is either/or — coverage-aware date rules + live-failure fallback since 2026-10-29 (bullet below; `docs/CODE_INVARIANTS.md` §federated_search) |
| Delta layer | `lib/thinclient/delta_layer.py` | **OPTIONAL, `SFU_DELTA_ROOT` default OFF (2026-09-29)** — trickle updates over the immutable base: mutable buffer + immutable delta generations (tantivy sections, meta, sidecar, one SEISMIC shard each) + newest-wins masks + livedocs bitset over base ordinals; IMPLEMENTED; serving quality bars **M2 PASS / M3 PASS 2026-09-30** (partial N; delta-shard recall ratio 1.159, 1/1,200 top-10 slots displaced, 0 mask leaks); gate stays OFF on M4 alone; M1 gate-off parity PASS on the clean run 120/120 (1 pass, code aa0fc405). Measured 2026-09-29/30: **M4 read amplification FAIL** (27.7 ms p50 per live generation versus +8; compaction half PASS 2026-10-01, 1.0135× the one-generation arm versus ≤ 1.05), **M5 reload PASS** (≤ 1.8 s; first query ≤ 1.82× warm); livedocs filter G1/G2 PASS partial 101/120; result-cache delta stamp DONE; M7 churn filter FAIL; M6 throughput recorded; M8 sidecar ratio RECORDED (lever not triggered); O1/O3/O9 fixed 2026-09-30 — `docs/delta_ingest/03_SPIKE_PLAN.md` addenda 2026-09-29/30 |
| Rerank | abstracts via hot sidecar / OpenAlex fetch + cross-encoder | torch v1 CE serving default; int8 ONNX opt-in; **base-flip DECISION PENDING** |

**Rebuilding from public data (2026-10-10):** the whole served artifact set
can be regenerated for a corpus of any size from the OpenAlex snapshot with
`scripts/reproduce/rebuild_from_openalex.py` (delta-ingest chain against an
empty base, generation directory served as the index root; MEASURED 50 k works →
21,122 kept → served in 182 s, serve check PASS) — `docs/REPRODUCIBILITY.md`.

### SPLADE leg (SEISMIC — the promoted engine)

- **Served today:** 8 dotvbyte mmap shards, **E8 dv-v2 per-doc-value-scale,
  served since 2026-07-14 (operator-signed flip)** over the E5
  `block_walk_canonical` layout
  (`data/seismic_150m/index/plan01/global_shard{0..7}of8.dotvbyte.e5.v2.mmap`,
  Path C — anon floor ~0, page-cache resident). Full-corpus RSS: dv
  **25.23 GB** versus f16's 41.86 GB; warm federated p50 ~65 ms (G8b 2026-07-04).
- **Manifest:** `data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json` is
  the code default when `SFU_SEISMIC_SHARD_MANIFEST` is unset (since the
  2026-07-14 flip); falls back down the ladder to
  `seismic_c25_shards_150m_mmap_e5.json` then
  `seismic_c25_shards_150m_mmap_dotvbyte.json` if absent. A set environment var always
  wins — the one-env rollback to any prior served shard set.
- **E8 dv-v2** (per-doc f16 vmax record head, `forward_format_version: 2`,
  doc `seismic_150m_testbed/14`): quality-IMPROVED versus the E5 dv-v1 promotion —
  per-shard overlap@10 versus f16 **0.993–0.997**, corpus mean ~0.9955 (versus e5/dv1
  ~0.9906); +0.67% size; warm p50 ≤1.05×; T1 0/0 all 8 shards. Stage-2
  per-shard chain + Q7 federated 2-rep PASS 2026-07-13
  (`_e8s2_q7_federated_v2_20260713.json`: hybrid cold 0.942× seq / warm
  1.044× par / T1 20/20).
- **E5** (`block_walk_canonical` forward-locality reorder, doc
  `seismic_150m_testbed/13`): quality-IDENTICAL to plain dv (a pure
  permutation of forward records — all 8 shards bit-identical parity; served
  federated top-10 exact-order on the A/B, 2026-07-09). Bought a cold-latency
  win: cold major-faults ~0.53–0.54×, cold traverse p50 ~1.46–1.51× faster
  (shards 1–2 full gates 2026-07-09, `e5_shard_gates_20260709_*.json`), warm
  neutral-to-1.1×-faster. Plain-dv + E5 dv-v1 shards stay on disk as the
  rollback ladder.
- **Quality:** **served E8 dv-v2 leg absolute NDCG@10 (2026-09-27, n=120
  parity queries, within-own-top-10): Haiku 0.9426 / Kimi 0.9249**; paired Δ
  versus the 2026-06-29 build −0.0012 (Haiku) / −0.0013 (Kimi), overlap@10 0.9858
  (`seismic_quality_haiku_e8dvv2_2026-09-27.json`, `BENCHMARK_METHODOLOGY.md`
  last section). G6 system parity **PASS** (paired-delta 2026-06-30, Kimi,
  scored the 2026-06-29 f16 build's IDs: SEISMIC leg
  NDCG@10 0.9262 versus Qdrant 0.9065, Δ=+0.0197, 95% CI clears zero, n=120);
  dv-vs-f16 corpus parity 0.9906 overlap@10 (G8d, accepted 2026-07-05; shards
  1–2 = 0.985; E8 dv-v2 is the recovery lever, Stage-2 LANDED 2026-07-14).
- **Backend selection:** `SFU_SPLADE_BACKEND` (default `seismic` since
  2026-07-06; `seismic` is the only supported value since 2026-10-12).
  **Qdrant** (was `on_disk=true` sparse `splade_150m`, 202 GB storage, exact
  posting-list dot product, the one-env rollback): *2026-10-12:* the leg was
  removed from `retriever.py` by owner decision (no Qdrant binary, service or
  collection exists in this container; the archive split that would have
  carried it is CLOSED KILLED, `archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md`);
  `SFU_SPLADE_QDRANT_URL` / `SFU_SPLADE_QDRANT_COLLECTION` are retired gates.
  The removed code is kept by the owner (branch `archive/bmp-qdrant`, restore
  tag `pre-owner-decisions-2026-10-12`). **BMP**: 150M artifacts deleted 2026-06-25
  (`docs/archive/bmp_decommission_plan/`). *2026-10-11:* the BMP code path was
  removed from `retriever.py`/`builder.py`/`build_thinclient_index.py` (the 1M
  testbed and POC artifacts it served are gone from this container); the owner
  keeps that code on the same archive branch. Any `SFU_SPLADE_BACKEND`
  other than `seismic` (since 2026-10-12 including `qdrant`) raises
  `ValueError` on the first SPLADE query (pinned by
  `source/tests/test_thinclient.py::test_unknown_splade_backend_raises` and
  `::test_qdrant_splade_backend_removed`);
  `SFU_SKIP_BMP` and `SFU_LOAD_MEM_FLOOR_GB` are gone and `/health` metrics no
  longer carry `bmp_shards`.

### Dense leg (OPTIONAL, default OFF)

b1 Hamming mmap + int8 rescore memmap (binary+rescore 32×, R@10 0.996 —
⚠ that is **binary-vs-float rescore fidelity WITHIN the covered subset**, not
corpus-level retrieval benefit). Coverage = the dense-POC 600k seed =
**0.399% of 150M** until the full corpus is encoded, plus the warm cache.
**DEFAULT OFF since 2026-08-18** (`SFU_DENSE_LEG` unset ⇒ off; only the
literal `1` enables the whole leg, seed + warm cache) after the ablation
measured the 0.4%-coverage leg significantly harmful. Serving is verified to
degrade cleanly with no `dense/` at all. ⚠ The recorded dense wins (+0.292
retrieval / +0.119 post-rerank nDCG@10) are an **UPPER bound**: the 600k pool
was built judged-docs-first and holds **90.3%** of the standard eval's ground
truth versus 0.399% for a random same-size subset (**226×** enrichment, measured
2026-08-17). Partition, sizes, evidence + the ablation:
**`DENSE_PARTITION_AND_ABLATION.md`**.

**Warm cache** (`dense_cache.py`): query-driven delta over the static seed —
RAM Hamming + int8 rescore, SQLite durability, 500k-doc cap.
`SFU_DENSE_WARMCACHE=0` disables the cache only; the leg gate above governs
everything. Holds 20,520 docs as of 2026-08-17 in `dense/delta.sqlite`.
**All four pre-registered success metrics were MEASURED 2026-09-25**
(240-query replay against a scratch delta grown 0 → 17,316 docs;
`scripts/experiments/eval_warmcache_replay.py`,
`data/eval_results/warmcache_metrics_20260925.json`): the dense leg's
recall@50 against judged qrels grows **0.107 → 0.348** while a seed-only
control stays flat at ~0.14 (+0.1207 mean, payoff visible after 25–50
queries); its cache-hit fraction grows **0.000 → 0.592**; delta-vs-exact
recall is **mean 0.9978 / min 0.94** — so the pre-registration's "trivially
exact in v1" is **wrong**, the binary Hamming prefilter is lossy; and p95
`search_rrf` is **unchanged** with the cache on (p50 +31.5 ms / +0.9%; the p95
delta is −6.8%, that is, the wrong sign, which is this host's noise floor —
`warmcache_metric3_isolated_20260925.json`, quiet-host gated).
⚠ **The fourth metric's pre-registered input does not exist**: the served
query log is PII-safe (`query_norm` empty in all 2,254 entries, only a
non-invertible sha1 prefix), so metric 1 is **UNMEASURABLE on the served log**
and the numbers above come from a labelled surrogate judged stream. None of
this reverses the 2026-08-18 DROP verdict — it measures the cache's coverage
growth, not fused nDCG. Design + numbers in `DENSE_WARMCACHE_RESEARCH.md`,
status in `DENSE_PARTITION_AND_ABLATION.md`.

### Filter stage (`_post_filter`)

Masks the over-fetched candidates for the SPLADE/dense legs. Default = the
`meta.sqlite` sidecar mask; `SFU_THINCLIENT_ORDINALS=<dir>` (default UNSET)
serves the stage from mmap'd ordinal-indexed columns instead.

- **WHERE `meta.sqlite` lives dominates** (doc `seismic_150m_testbed/18` §14,
  measured 2026-08-03): the stage costs **222.2 ms** served off 9p versus
  **4.0 ms** with the same file on local disk — 55×, no code change. Ordinals
  reach 1.5 ms; against a *staged* SQLite baseline that is 2.7× on the stage
  but only **2.5 ms (2.0%) of the whole query — inside the ±4% noise floor,
  not claimable**. Whole-query 2×2 at `top_k=50`: 9p 332.3 ms →
  staged-SQLite 117.3 ms (**2.83×**) → ordinals 122.3 ms (2.72×) → both
  125.6 ms (2.65×) — **the two levers are redundant, not additive**; parity
  PASS 4/4, all four arms byte-identical.
- ⚠ Earlier rows quoting **120–211×** (§11) and **whole-query 3.20×** (§13)
  measured ordinals against SQLite-on-9p and misattributed a filesystem win
  to the addressing change — see the dated banners on those sections.
  **Updated 2026-09-25 — there is no droplet.** Cloud access ended
  (no OCI host, no DigitalOcean droplet); the only serving host is this WSL2
  machine, where `data/thinclient_index/` genuinely **is** 9p (`v9fs`,
  re-verified 2026-09-25) and `/var/tmp` is local overlay. So the earlier
  "the 9p baseline does not exist in production" reasoning no longer applies
  by way of a droplet: the realisable baseline is whatever this host serves
  off **local disk**, reached here by staging, and against that staged local
  baseline everything ordinals can still win is 4.0 → 1.5 ms = 2.0% of the
  query. `meta.sqlite` staging is a real (not no-op) lever here, because the
  source path is 9p.
- **The residency case is REFUTED — MEASURED 2026-09-25**
  (`ORDINALS_RESIDENCY_CLIFF.md`;
  `scripts/experiments/eval_ordinals_cliff.py`;
  `data/eval_results/ordinals_cliff_20260925.json`). §14 "not settled" #5 was
  the only open question that could still justify the module, and a 6-rung
  page-cache ladder (23.97 → **1.86 GiB** available, that is, below the arrays'
  own 1.955 GB) answers it: the staged-SQLite stage stays at **2.8–3.2 ms p50
  / 2.9–4.5 ms p95 at every rung** — pre-registered bar B1 (≥3× degradation)
  fails at **1.240** — while ordinals hold 0.93–1.08 ms p50. The advantage is
  flat at ~3×, not growing (B3 fails). Parity 0 mismatches / 240 comparisons.
  ⚠ **The mechanism claimed here was backwards.** This bullet used to say the
  stage's page-cache working set "shrinks from a randomly-descended 24.9 GB
  B-tree to 1.96 GB". `mincore(2)` measures the SQLite stage's *hot* set at
  **122.7 MB of the 24.9 GB file (0.49%)** versus **1,643.9 MB** for the
  ordinal arrays: adopting ordinals makes the filter stage's resident set
  **13.4× LARGER**. That is why no cap in the ladder hurt SQLite — 122.7 MB
  fits in every rung. Ordinals still do NOT replace `meta.sqlite` (`_hydrate`
  reads title/DOI from it), so their 1.96 GB remains additive to its 24.9 GB
  on disk **and** on top of the hot set in RAM.
- **What ordinals DO win, newly measured 2026-09-25**: the **cold transient**.
  On the first pass after a verified eviction they are **55–90× faster**
  (SQLite 117–136 ms p50 → ordinals 1.5–2.2 ms p50), which prices process
  restarts and post-eviction recovery, not steady-state serving — by pass 2
  SQLite is back to ~2.9 ms. Buying that with 13.4× more resident memory is
  the opposite of the trade the module was proposed for; no default changed. Loads only if the
  directory's `ordinal_space_id` matches the index `manifest.json` (**fails
  closed** otherwise); ids with no ordinal fall back to SQLite rather than
  being dropped; requires the arrays on local disk (off 9p measured 8×
  *slower* than SQLite). Neither lever is enabled by default.
- **`meta.sqlite` staging is BUILT (2026-08-17, default OFF) and its
  automated path is MEASURED at full size** — `retriever._stage_meta_local` +
  `_connect_meta`: `SFU_META_STAGE_DIR=<dir>` (or `SFU_STAGE_META=1` to reuse
  `SFU_SEISMIC_STAGE_DIR`), `SFU_META_STAGE_FORCE=1` to stage off a local FS
  anyway, `SFU_META_STAGE_VERIFY=size|fingerprint|sha256` (default
  `fingerprint` = size + head/tail 64 KiB sha256). Dev-container lever,
  production no-op: without FORCE it refuses to copy unless the source FS is
  9p/virtiofs/NFS/CIFS/sshfs (`data/thinclient_index` measured 2026-08-17:
  fstype `9p`). Copy is atomic (`<name>.tmp-<pid>` → verify → `os.replace`),
  idempotent via a `.staged_ok` marker (source size + mtime_ns +
  fingerprint), refuses a source with a live `-wal`/`-journal`, never leaves
  a prior stage's sidecars beside the new copy; the staged copy opens
  `mode=ro&immutable=1`; `metrics()` reports `meta_path`/`meta_staged`.
  Measured results: see "the same lever for `meta.sqlite`" under Web GUI
  below (2026-08-17: `_post_filter` p50 186.7 → 2.97 ms, 62.8×, parity
  36/36). Tests: `scripts/tests/test_meta_staging.py` (23 cases).

  > Correction 2026-09-01: an earlier revision of this table still called the
  > automated staging path "UNMEASURED at full size"; the 2026-08-17 n8 run
  > (below) had already measured it. The MEASURED statement stands.

### Delta layer (`SFU_DELTA_ROOT`, default OFF — opened 2026-09-29)

The base above is immutable and its rebuild inputs are gone (§Migration). The
delta layer (`docs/delta_ingest/`, code `spike/delta_ingest/` +
`lib/thinclient/delta_layer.py`) adds documents from ANY source without
touching it: a canonical `DocRecord` from an adapter (OpenAlex snapshot
partitions / API, JSONL/CSV, arXiv/Zotero next) → content-hash diff (skips
OpenAlex's citation-count churn) → GPU/CPU SPLADE encode → an L0 mutable
buffer (tantivy delete+add+commit, exact sparse in RAM, searchable at once) →
frozen into immutable generations `delta/gNNNN/` (tantivy `<base>__<era>`
sections + `meta.sqlite` + hot `abstracts.sqlite` + a SEISMIC shard through
the same build → c1a → dotvbyte-v2 chain) → served alongside the base with
newest-wins masks (base copy of an updated doc dropped before RRF, deletes
hidden everywhere) → compacted N→1 from the ledger's stored records.
Resource profiles (`laptop` CPU trickle / `desktop_gpu` / `server`) set
encoder, batch, throttle, freeze thresholds, RSS abort, niceness. Operator
flow: `python -m spike.delta_ingest.cli ingest|flush|compact`, then the
`reload_index` MCP tool (drops the SEISMIC backend when the delta stamp
changed). **State 2026-09-29: IMPLEMENTED; serving efficacy UNMEASURED;
OPTIONAL, default OFF.** Synthetic e2e (`scripts/tests/test_delta_ingest.py`)
passes incl. the real SEISMIC chain on 200 docs. Measured 2026-09-29
(`docs/delta_ingest/03_SPIKE_PLAN.md` addendum has numbers, files, commits):
- **Livedocs bitset** (deletes + superseded base copies over base ordinals,
  `<delta_root>/livedocs/base-<stamp>.liv`, written by `publish()` when base
  ordinals are available; Python per-shard filter before `_merge_topk`, fixes
  S5): G1 empty-bitset bit-identity and G2 synthetic-delete no-leak **PASS,
  PARTIAL 101/120 topics**; filter cost p50 6.5–10.6 ms/query. Rust
  gather-time skip DESIGN ONLY. Roots without a livedocs key use the JSON
  mask lists as before.
- **Result-cache stamp (R1) DONE** (f5da0d24): cache key gains
  `@delta=<stamp>` only while a delta layer is loaded; gate off → keys
  byte-identical.
- **M7 churn filter FAIL** (touched:must-encode ≈1.15:1 and ≈2.61:1 *est.*,
  bar < 3:1 falsifies); the ledger cannot filter base docs (no base hashes).
- **M6 throughput RECORDED** (adapter→buffer 403 / 2,561 docs/s laptop /
  desktop_gpu; ingest peak RSS 6.74 GB on both profiles).
- **Twin-shard rebuild (M9) FAIL** versus its 0.99 bar (overlap@10 0.9858 /
  0.9870); the SEISMIC-leg base fold-in stays UNVERIFIED.
- **M1 gate-off parity PASS on the clean run** (a12f8d26): fused + final
  top-10 byte-identical 120/120, unset versus EMPTY root. Limits: 1 pass per arm
  (plan: 2); measured code aa0fc405, which predates C's livedocs serving
  commit 6f5dd471; latency fields invalid. A first empty-root run FAILED as
  recorded (final 0/120) after ENOMEM while importing onnxruntime / the
  embedding model / the cross-encoder from the `.venv` on the 9p mount — the
  process silently served BM25F-only SPLADE fallback and no rerank; root
  cause unverified (`docs/delta_ingest/02_DESIGN.md` §3.1 O12).
- **M4 read amplification FAIL** (2026-09-29, 4014ef07): 27.7 ms p50 per
  live generation (paired median 14.8) against +8 ms; about half of it is
  BM25F per-section work and delta abstract probes, not SEISMIC. Compaction
  half PASS 2026-10-01 (below). **M5 reload PASS** (2026-09-30): reload ≤ 1.8 s, first
  query 1.60–1.82× warm. `spike/delta_ingest/M4_M5_FINDINGS.md`.
- **M8 sidecar ratio RECORDED** (2026-09-30): 0.31–0.36× the base's 351.8 B/abstract
  on corpus (b) (90% duplicate dataset abstracts), 1.47–1.51× on article-like
  subsets; base-dict reuse does not help. O1 (stale buffer view on the SPLADE
  leg), O3, O9 fixed 2026-09-30. Base-hash ledger seed built and measured
  2026-09-30 (PASS: reproduces M7's exact proxy; M7's FAIL stands because
  most touched records are new works); O5 DOI normalisation and O6 min-year
  fixed.
- **M2 PASS / M3 PASS** (2026-09-30, `spike/delta_ingest/M2_FINDINGS.md`,
  `M3_FINDINGS.md`): an updated doc served from a 50k-doc delta generation is
  found at least as often as its base copy (recall ratio 1.159 at k=10 on
  1,352 queries), the delta shard's top-10 matches an exact dot product
  (0.9968–1.0), the livedocs mask leaked 0 of 1,043 surfaced base copies,
  1 of 1,200 fused top-10 slots changed across the 120 topics, median BM25F
  rank change 0 (350/600 titles). Promotion rule: M1–M3 PASS, M4 FAIL → gate
  stays OFF until the M4 follow-up passes.
- **2026-10-01** (`docs/delta_ingest/03_SPIKE_PLAN.md` addendum 2026-10-01):
  **M4 compaction bar PASS** — compacting 8 generations to 1 returns p50 to
  1.0135× the one-generation arm (bar ≤ 1.05; 120 topics × 2 passes,
  `data/eval_results/delta_ingest_M4_compaction_20261001.json`); the growth
  bar still FAILS, so the gate stays OFF on it alone. **M1 gate-off parity
  PASS on 2 passes on current code** (120/120 both passes, d985b70d,
  `delta_ingest_M1_2pass_20261001.json`). Twin-rebuild drift baseline
  PARTIAL (3M-doc prefix): rebuilds differ run to run (overlap@10
  0.996–1.000) unless the token-id map is pinned, then bit-equal; M9's FAIL
  stands. Serving fixes (unit-tested only): the buffer tantivy section now
  attaches lazily after load, the SPLADE buffer view counts
  published-not-loaded generations (O2), `resolve_delta_root` refuses write
  roots under `data/seismic_150m` (O16, `docs/ENV_GATES.md`), the abstract
  store opens read-only (O15). The O19 lower-casing changes the result for 1
  of 120 topics on the served index (cause not investigated). M4 follow-up
  and fold-in trigger are pre-registered (`docs/delta_ingest/09_…`, `10_…`),
  nothing run.
- **2026-10-01, third wave (ENDED 2026-10-02 01:50Z; end-of-wave summary in the next bullet;
  dispatch record `docs/delta_ingest/04_HANDOFF_2026-09-29.md` §"third
  wave"):** new serving gates, **all default OFF and no-ops when unset**
  (`docs/ENV_GATES.md`, invariants in `docs/CODE_INVARIANTS.md`):
  `SFU_DELTA_ABS_ROUTE` (09 lever L3, routed delta abstract probes),
  `SFU_BM25F_PARSE_ONCE` (L4, parse once per tantivy schema),
  `SFU_SEISMIC_DELTA_GROUP` (L5, all delta shards in one pool task) —
  **IMPLEMENTED, EFFICACY UNMEASURED** (parity run P of `docs/delta_ingest/09_…`
  PASS 2026-10-01: each lever and the all-gates-unset check identical on
  120/120 topics on `root_n8` and `root_n1`,
  `data/eval_results/delta_ingest_M4F_20261001.json`; latency run R1 NOT RUN
  yet); `SFU_OA_BITMAP` (O17 option (a) by
  owner decision 2026-10-01: base `is_oa` override from
  `lib/thinclient/oa_overlay.py`, three-state, fails closed) — premise
  MEASURED 2026-10-01: 0 of 150,413,098 base docs carry `is_oa` in tantivy
  or the ordinals, so `open_access_only` matches no base doc with the gate
  off; ingest effect on the M7 primary seeded subset with a same-partition
  bitmap: updates 8,047 → 3,582, `is_oa`-only content updates 4,465 → 0
  (`spike/delta_ingest/OA_BITMAP_FINDINGS.md`); **Full bitmap BUILT 2026-10-01 23:07Z** from the OpenAlex 2026-09-23 snapshot (2,040/2,040 partitions, 476,196,327 works streamed in 7.42 h, nothing stored): **141,288,198 of 150,413,098 base docs known (93.93 %) — 110,525,184 open access, 30,763,014 not; 9,124,900 unknown (6.07 %, absent from the snapshot; served as `is_oa: null`, excluded by `open_access_only`)**; 37.6 MB; spot check 100,000/100,000 lookups equal the raw scan (`data/eval_results/delta_ingest_O17_bitmap_build_check_20261001.json`). **Gate-ON serving efficacy NOT RUN** (queued); with the gate on the reranker's full-text feature reads `is_oa`, so final order can change on unfiltered queries too (UNMEASURED). Measured 2026-10-01 18:30Z
  (`scripts/experiments/eval_delta_ingest_o17_oa_bitmap.py`, ac0a4c71; 120
  topics): gate-off identity **PASS 120/120** (fused + final, unfiltered and
  OA-filtered, pre-O17 code versus gate off); before-number: `open_access_only`
  returns 0 results on 120/120 topics. Gate-ON arm NOT RUN yet. Ingest-side
  levers L1 (compaction cadence `compact_all`, `G_max`) and L2 (generation
  layout `per_base_section` default / `per_era` / `single`) are profile
  dials in `spike/delta_ingest/`, defaults unchanged, EFFICACY UNMEASURED.
  Behaviour changes on the serving path (unit-tested only): an unparseable
  BM25F query now degrades to no BM25F hits instead of raising, and the
  query sanitiser handles Unicode whitespace and dotted İ (O19 follow-up —
  cause of the 1/120 change: tantivy collapses repeated query words by
  surface form only, `spike/delta_ingest/FIXES_20261001_WAVE3.md`); frozen
  docs stay BM25F-visible until `reload()` (O2 residual); the doc encoder
  reports a per-instance `runtime_backend` label (O8). O14: reused base
  vectors give the same served dotvbyte codes as the base copy,
  20,000/20,000 shard-0 rows (encode saving still UNMEASURED).
  **Full-shard drift baseline 2026-10-01 (third wave): NOISE** — build-vs-build overlap@10 0.9908 / 0.985 on the 18.8M-doc shard, so M9's 0.9858 / 0.9870 FAIL stands as recorded but is build noise; a rebuild with the token-id map pinned matches the served shard 1.000 / 1.000 (220/220 top-10); fold-in gate G1 of `docs/delta_ingest/10_…` holds (`docs/delta_ingest/03_SPIKE_PLAN.md` addendum third wave).
- **Third wave 2026-10-01/02 (results in `docs/delta_ingest/03_SPIKE_PLAN.md` addendum "third wave", dispatch record in `docs/delta_ingest/04_HANDOFF_2026-09-29.md`):** M2 PASS at full N (ratio 1.159 over 2,000 queries, 0 leaks), M3 PASS at full N (stitched, 585/600 compared, median rank change 0), livedocs G1/G2 PASS on 120/120, **M4 sequential FAIL on growth** (20.1 ms/gen versus +8; parallel 27.7), drift baseline NOISE with a pinned-token-map rebuild matching served 1.000 / 1.000. `docs/delta_ingest/09_…`: levers L1–L5 IMPLEMENTED (serving gates `SFU_DELTA_ABS_ROUTE`, `SFU_BM25F_PARSE_ONCE`, `SFU_SEISMIC_DELTA_GROUP`, default OFF), Run P PASS 120/120, P2 PASS on layout `single` (caveat: the one-section fixture does not exercise the cross-subject IDF risk), **R1 NOT RUN — aborted on the pre-registered memory rule with 8 retrievers in 32 GB; needs more host RAM** — so every lever's latency effect is UNMEASURED and **`SFU_DELTA_ROOT` stays OFF, not eligible**. O17 option (a) by owner decision: base `is_oa` bitmap BUILT (93.93 % of 150,413,098 base docs known, 110,525,184 OA) behind `SFU_OA_BITMAP` (default OFF); gate ON makes `open_access_only` return results (0 → 6,000 fused over 120 topics, all known-OA) but lowers unfiltered nDCG@10 0.7053 → 0.6835 through the reranker's full-text feature — gate stays OFF, owner decision. O18, O8 FIXED; O2 BM25F residual FIXED for one freeze per reload; O19 cause found + fixed; O14 reuse gives identical served codes (20,000/20,000) but no GPU encode saving (−4.1 % end to end); O10 Rust skip IMPLEMENTED on a fork branch (parity 220/220), EFFICACY UNMEASURED. `docs/delta_ingest/10_…`: G1, G2 HOLD, G6 recorded, G3/G4 code + unit bars; no fold built, no F-bar run.
- **Open after the third wave:** R1 (then R2/R3/P3) once the host has more RAM; a multi-section fixture for the `single`-layout IDF risk (not pre-registered); the `SFU_OA_BITMAP` rerank-quality decision; the `docs/delta_ingest/10_…` F-bars (F2 harness not written; owner choice of the F2 bar reading; G4's M1 run; G3's real-fold baseline bar); O10 exclusive-lock timing + operator `.so` swap; O2 two-freeze residual; O14 CPU-profile saving and locators for shards 1–7; M2 on a second section; hot-section base-hash seed (owner decision; the TrueNAS snapshot chunks may hold the base text — unverified lead 2026-10-01); 9-shard pilot M10 NOT RUN.
- **2026-10-03 — supersedes the R1 and fold-in items of the two bullets above:** `docs/delta_ingest/09_…` R1 was run twice on 2026-10-03 after the host went from 32 GB to 54 GB RAM (`data/eval_results/delta_ingest_M4F_20261001.json` keys `R1`, `R1_repeat`; `scripts/experiments/eval_delta_ingest_m4f.py`; exclusive lock, 2 measured passes × 120 topics per arm, no swap, healthy). The REPL integrity check was OUTSIDE its 60–250 ms window on the first run (n8 − n0 +21.1 ms), so by the frozen rule R1 was repeated once and the verdicts are read on the repeat (code 189e4107), where REPL is again outside (+28.5 ms, CI 24.2–32.4, versus M4's +123 ms): **F-SLOPE PASS** — paired slope 1.28 ms/gen (CI 0.73–2.09), pooled 3.28, versus 8.0 (first run 1.48, CI 0.60–2.51, pooled 0.95); **F-CAD PASS at G_max=4** (paired +12.6 ms, CI 6.4–18.2, versus 32; G_max=1 FAIL on its paired CI upper bound 11.2 versus 8.0); **F-COMP FAIL** (ratio 1.0079, paired CI −4.2 to +8.7 ms versus ±8; the first run read PASS at −7.0 to +6.5). Pooled p50 on the repeat: n0 2,133.0, n8 2,147.6, n0x 2,118.8, x1 2,106.2, x4 2,141.4, x8 2,136.0, x8c 2,122.7 ms. The no-lever tax n8 − n0 is ~21–29 ms on this host against +123 ms in M4 (likely the larger RAM; not isolated), so M4's 27.7 / 20.1 ms/gen rows describe the 32 GB host. **Promotion rule P1 holds by route (a)**; with P3 (below) every condition P1–P4 of `docs/delta_ingest/09_…` §6 now holds by the letter of the frozen rule — P2's PASS being the one-section run with its recorded caveat. The eligibility statement is NOT made here: whether it waits for the multi-section check pre-registered in `docs/delta_ingest/11_P2_MULTISECTION_PREREGISTRATION.md` (written 2026-10-03, NOTHING RUN) was an owner decision, taken 2026-10-04: **eligibility waits for that check** (doc 11 addendum); the code default stays OFF either way. **P3 PASS 2026-10-03 23:30–23:48Z** (M1 gate-off versus empty-root parity on the lever code 8dcde712, every new gate unset: full fused list and final top-10 byte-identical 120/120 on each of 2 passes, 0 degraded rows, shared lock; `data/eval_results/delta_ingest_M1_2pass_20261003.json`, `scripts/experiments/eval_delta_ingest_m1_2pass.py`; this is also the M1 run doc 10's G4 needed, 8dcde712 being a descendant of 11527c59; informational only: 119/120 identical to the 2026-09-29 gate-off rows of code aa0fc405, one topic differs, not investigated); **`docs/delta_ingest/09_…` R2 (lever attribution at N = 8) RUN 2026-10-03 23:49Z–2026-10-04 01:33Z** (exclusive lock, code 865b7c74, 2 measured passes × 120 topics per arm, no swap, healthy; `data/eval_results/delta_ingest_M4F_20261001.json` key `R2`; recorded, no bar): paired gain versus n8 — L3 routed abstract probes −9.6 ms (CI −14.9 to −0.8), L4 parse-once −8.0 ms (CI −12.0 to −2.0), L5 grouped delta shards −4.7 ms (CI −11.8 to +1.0, **CI includes 0**), layout `per_era` −14.8 ms (CI −23.5 to −10.5), layout `single` −17.9 ms (CI −22.8 to −12.3); n8 − n0 +34.1 ms (CI 29.0–41.7). By the `docs/delta_ingest/09_…` §7 rule (kill when the paired gain is > −1.0 ms) **every lever is KEPT**; L5's interval reaches 0. Pooled p50: n0 2,129.6, n8 2,162.5, n8+L3 2,122.8, n8+L4 2,133.0, n8+L5 2,150.7, e8 2,108.7, s8 2,142.2 ms. **Fold-in, first fold 2026-10-03** (`spike/delta_ingest/FOLDIN_FINDINGS.md`, `data/eval_results/delta_ingest_foldin_20261003.json`, harness `scripts/experiments/eval_delta_ingest_foldin.py`): shard-0 fold of 20,112 docs built in 23.6 min, peak memory 12.11 GB process tree / 10.27 GB largest process (bar 10 GB), scratch 59.5 GB (bar 60); F2 with Q-a Reading A (owner, 2026-10-03): Q-a PASS (federated overlap@10 0.9992 / 0.9980), Q-c PASS, Q-d PASS on a fixture without deletions, **Q-b FAIL on the diverse set at shard level (0.9780 versus 0.9820) — F2 FAIL as computed**; F1/F3/F5/F6/F8 NOT RUN; nothing published; owner questions open (Q-b level, the peak-RSS definition, a deletions fixture).
- **2026-10-04 — supersedes the eligibility wording of the bullet above:** **`docs/delta_ingest/11_P2_MULTISECTION_PREREGISTRATION.md` multi-section P2 RUN 2026-10-04 01:39–05:25Z: FAIL by the frozen rule, on bar A only** (`data/eval_results/delta_ingest_P2_multisection_20261004.json`, `scripts/experiments/eval_delta_ingest_p2_multisection.py`; shared lock, timings invalid by declaration; both contrasts complete and healthy, 600 titles + 120 topics + 600 titles each; search code snapshot e3fb5ad0 for both). Layout `single` versus `per_base_section`, 1 generation / 8 generations: **A** median own-rank change in the BM25F leg overall 0 / 0, per subject 0 in four strata and **−13.5 / −1.0 in `other__recent`** (negative = the doc ranks BETTER under `single`), so the two-sided bar "median = 0 in each stratum" FAILS; the medians rest on the docs present in both arms' top-100: 217 / 210 of 600 overall and 20 / 14 in `other__recent`, 5 / 5 in `phys_eng__recent` (48 / 47 more docs enter the top-100 only under `single`, none only under `per_base_section`; 335 / 343 are in neither); own-doc raw score ratio single/per_base_section median 1.11 / 1.19. **A2 PASS** (own-recall@100 0.362 → 0.442 and 0.350 → 0.428). **B PASS** (1 / 0 of 1,200 fused top-10 slots displaced on the 120 topics). **C PASS** (122 / 128 of 6,000 slots displaced = 2.0 % / 2.1 %; own fused-rank median change 0). **D PASS** (0 duplicates, 0 wrong-origin hits). `per_era` by the same rule: does not hold either (A: −13.5 / −1.0 in the same stratum). Reading: pooling subjects raises delta docs' BM25F scores, which moves them up, not down; the bar as written does not distinguish the direction. By its §3 the adopted layout falls back to `per_base_section`, lever L2 is killed, and P1 has to be shown by R1 on the `n…` roots with L3–L5; **`SFU_DELTA_ROOT` is NOT eligible**.
- **`docs/delta_ingest/09_…` R1 repeat on the fallback stack (layout `per_base_section` + L3, L4, L5) 2026-10-04 07:11–08:53Z — verdicts read on this run** (exclusive lock, code 425346ad, 2 measured passes × 120 topics per arm, no swap, healthy; `data/eval_results/delta_ingest_M4F_20261001.json` key `R1_per_base_section_repeat`): **F-SLOPE PASS** — paired slope 1.31 ms/gen (CI 0.43–2.39), pooled 7.05, versus 8.0 (first run 2.49, CI 1.75–3.70, pooled 3.42); **F-CAD PASS at G_max=1** (paired −5.3 ms, CI −12.0 to +4.6, pooled −2.1, versus 8.0; the first run read PASS only at G_max=4); **F-COMP FAIL** (ratio 0.9998, paired CI −1.1 to +10.7 ms versus ±8); REPL outside its window again (n8 − n0 +28.7 ms, CI 23.1–33.1). Pooled p50: n0 2,137.8, n8 2,186.0, n0x 2,138.9, x1 2,136.8, x4 2,167.2, x8 2,191.0, x8c 2,136.5 ms. **P1 holds by route (a) for the fallback stack**; P2 does not apply to `per_base_section`, P3 and P4 PASS. **No eligibility statement is made:** the owner decision recorded in doc 11 (not eligible until doc 11 reads PASS; it read FAIL for `single`) stands until the owner rules on the fallback stack. Session closed 2026-10-04 08:55Z with nothing running and the latency lock free.
- **2026-10-04, late session — fold-in second attempt and `09` R3:** **Fold-in, second attempt 2026-10-04 (`spike/delta_ingest/FOLDIN_FINDINGS.md` §"2026-10-04"; `data/eval_results/delta_ingest_foldin_20261004.json`, `scripts/experiments/eval_delta_ingest_foldin.py`):** F4 memory — the dump workers now `read()` their ranges instead of mapping the f16 twin (dump stage alone, tree VmRSS 10.37 → 4.37 GiB, jsonl byte-identical; `scripts/experiments/probe_delta_ingest_fold_dump_mem.py`) and the cli process releases the freed build heap before the converter stages (`generation._release_freed_heap`; residual 1.89 → 0.13 GiB). Shard-0 fold rebuilt twice through the recorder under the exclusive lock (fold 2 with the dump change, key `F4_build_fold2`; fold 3 with both, key `F4_build_fold3`): peak tree VmRSS + swap fold 1 12.11 → fold 2 13.13 → **fold 3 11.37 GiB**, largest process 10.27 → 11.24 → 11.24 GiB, anonymous-only tree 10.32 GiB on fold 3; wall 23.9 min, scratch 59.50 GB, output 13.83 GB. **F4 memory still FAILS the 10 GB bar by every reading and is now under the 12 GB kill line by every reading.** The per-process timeline (new in the recorder) puts the remainder in two Rust tools, not changed: `c1a_mmap_index` holds 10.2 GiB anonymous, `convert_f16_to_dotvbyte` 11.24 GiB of which 6.29 is the mapped f16 source. F2 — fold 2 (the one rebuild of doc 10 §8; key `F2_fold2`, 21:50–22:09Z, shared lock) returns the same ordered shard-own top-10 as fold 1 on 220/220 queries although its posting-list bytes differ, so every F2 number repeats: Q-a, Q-c, Q-d PASS, Q-b QD shard-own 0.9780 versus 0.9820, federated 0.9980. All 35 swapped docs per arm are base docs, none a folded doc. **Owner decision 2026-10-04, taken after both runs were read (doc 10 addendum of that date): the federated level is binding for Q-b, not the shard level — on it F2 = PASS on fold 1 and fold 2** (keys `F2_qb_federated` in `delta_ingest_foldin_20261003.json`, `F2_fold2_qb_federated`); the shard-level numbers stand as measured and the §8 kill condition is not met. Still open in doc 10: the F4 memory bar, a deletions fixture for Q-d, F1 (no trigger code exists yet), F3, F5, F6, F8; nothing published. **`09` Run R3 (pre-registered follow-up to an F-COMP FAIL; recorded, no bar, cannot overturn F-COMP) RUN 2026-10-04 22:33–23:36Z** on the fallback stack (layout `per_base_section` + L3, L4, L5; exclusive lock, code 9f677a21, 2 measured passes × 120 topics per arm, healthy, host swap grew 1.17 GB during the run; `data/eval_results/delta_ingest_M4F_20261001.json` key `R3_per_base_section`, `scripts/experiments/eval_delta_ingest_m4f.py`): paired median x8c − x1 **−5.5 ms** (CI −15.7 to +4.8), n8c − n1 +0.6 ms (CI −4.7 to +6.9), x1 − n1 −1.3 ms (CI −6.4 to +5.7), x8c − n8c −4.1 ms (CI −10.6 to +5.4); pooled p50 x1 2,104.8, x8c 2,109.9, n1 2,096.0, n8c 2,085.8 ms (x8c / x1 = 1.0024). Per-leg medians of the delta work are the same for a compacted and a fresh 160,347-doc generation (delta BM25F sections 3.0 versus 3.1 ms, delta SEISMIC shard 2.1 versus 2.2 ms, delta abstracts 0.1 versus 0.1 ms on the x arms); the base BM25F leg is ~1,960 ms of each ~2,100 ms query. Reading: no compaction residue is visible; every interval contains 0 and is wider than ±8 ms on one side, so F-COMP's FAIL is the interval width of this design, not a measured cost. **F-COMP stays FAIL as recorded; P1 still holds by route (a).** Unchanged and still the owner's: eligibility of the fallback stack for `SFU_DELTA_ROOT` (doc 11 decision), whether a rank improvement fails doc 11's bar A, `SFU_OA_BITMAP`, the hot-section base-hash seed. No serving default changed; session closed 2026-10-04 23:45Z with nothing running and the latency lock free.
- **2026-10-05 — owner amendment of the doc 10 F4 memory bar (taken after the runs; doc 10 addendum of that date):** peak RSS ≤ **11.5 GB**, read on the process-tree VmRSS + VmSwap of the fold build; the 12 GB kill line and the `desktop_gpu` abort are unchanged, and the original 10 GB bar's FAIL stays on record. Read on the amended bar the fold-3 build record (current code) is within every F4 bar (wall 23.9 min, peak 11.37 GiB — margin 0.13 GiB, scratch 59.50 GB, output 13.83 GB; `data/eval_results/delta_ingest_foldin_20261004.json` key `F4_amended_bar_20261005`, no new measurement); the publish stage and the duty cycle are not measured. Online research of 2026-10-05 on whether the fold-in costs are known elsewhere, the owner decisions taken and open, and the work order are in `docs/delta_ingest/12_NEXT_SESSION_2026-10-05.md` — **start there**. `SFU_DELTA_ROOT` still NOT eligible pending the owner's ruling on the fallback stack; no serving default changed.
- **2026-10-08 — fold-in trigger, deletions fold, crash-safety fixes** (`spike/delta_ingest/FOLDIN_FINDINGS.md` §§2026-10-08; `docs/delta_ingest/03_SPIKE_PLAN.md` addendum 2026-10-08; doc 10 addenda 2026-10-08): **trigger bookkeeping** `spike/delta_ingest/trigger.py` runs at every `generation.publish()` and writes `<delta_root>/trigger.json` + `trigger_log.jsonl` with per-shard (a) live-delta fraction, (d) dead-copy fraction, (c) oldest live delta age; report only (never builds or publishes), dials `SFU_DELTA_FOLDIN_FRAC` / `_DEAD_FRAC` / `_MAX_AGE` unset = nothing fires, 24 h hysteresis, (b) tax NOT implemented (needs F0). **F1 PASS** 20/20 checkpoints on copies of `fixture_n8` and `root_n8` versus an independent recount (`scripts/experiments/eval_delta_ingest_trigger.py`, `data/eval_results/delta_ingest_foldin_f1_20261008.json`). **Deletions fold** (new fold, Stage-0 shard-0 data: 1,131,292 tombstones, 8,465 superseded base docs, 20,112 superseded delta copies; s′ = 17,691,720 docs; `data/eval_results/delta_ingest_foldin_20261008.json`): **F4 within every amended bar** — wall 23.7 min, peak tree 10.86 GiB (≤ 11.5; original 10 GB bar still FAIL), scratch 55.99 GB, output 13.08 GB; **F2 PASS** at the owner's readings — federated overlap@10 0.9983 / 1.0000, ΔNDCG@10 −0.0004 (CI −0.0012 to +0.0001), **Q-d 0 mask leaks over 460 queries with real tombstones** (shard-level Q-b 0.9708 / 0.9580 recorded, not binding). **Serving-path change:** `publish()` now writes the composed shard manifest to a NEW `<delta_root>/shard_manifests/shard_manifest-<stamp>.json` and `generations.json` (written last) is the single commit point; `delta_layer.py` already reads the manifest path from `generations.json` (`shard_manifest` key), so serving is unchanged — the old in-place `shard_manifest.json` rewrite could pair a new manifest with old masks after a kill (found by review before any F5 trial, 60ba0fc1). `publish-fold` is re-runnable after a kill and prefaults the fold's served directory before the repoint (`--no-prefault` to skip; IMPLEMENTED, EFFICACY UNMEASURED until F8). The G3 baseline compare now survives a JSON round trip (46b85c0c; a false 817/817 "changed" alarm stopped F3/F8 setup once, real compare 0 changed). **F8 FAIL** (reload ≤ 1.22 s PASS versus 15 s; first-query p50 2.17× warm versus ≤ 2× FAIL — rep 1 after the real `publish-fold` 22.3 s despite the prefault; rollback reloads cost the same, so it follows the backend drop/reopen) and **F3 FAIL** (p50 F/n0 1.014 PASS; Δ(F, n0) +5.76 ms, CI upper 13.57 versus 8.0 FAIL; Δ(L, F) −1.5 ms) — `data/eval_results/delta_ingest_foldin_f3f8_20261008.json`; neither is a doc 10 §8 kill, fold-in is not promotable under §9 as measured. **F0 FAIL** (one 1,000,000-doc generation versus the 160,347-doc one: +17.93 ms, CI 10.60–23.20 versus ≤ 8.0; **c = 21.35 ms per million delta docs**, upper bound; `data/eval_results/delta_ingest_foldin_f0_20261008.json`) → doc 10 §8 sections tier FLAGGED; follow-on pre-registration `docs/delta_ingest/13_FULL_REBUILD_TRIGGER_PREREGISTRATION.md` (design only: S-fold of one tantivy section + full-rebuild triggers T1–T5; *est.* the sections tier spends an 8 ms budget in ≈ 0.5 day of churn as coded; no snapshot→spool exporter exists today). **F5 PASS 60/60** (2026-10-09: 50 fold-build + 10 `publish-fold` SIGKILLs, served state always exactly pre- or post-fold; `data/eval_results/delta_ingest_foldin_f5_20261008.json`). Doc 10 scoreboard: F1, F2, F4 (amended), F5 PASS; F0, F3, F8 FAIL; **F7 (2026-10-09): `desktop_gpu`/`server` FLAGGED** — the rule picks (a) 0.02 (duty 3.1 %) but the modelled tax at its first fold moment is 76.6 ms > 8 × G_max = 64 ms (sections tier), `laptop` not applicable (`data/eval_results/delta_ingest_foldin_f7_20261009.json`); **F6 PASS** (2026-10-09: a second fold of s′ from fold 1's own output after a 1.13 M-tombstone batch — Q-a federated 0.9975 / 0.9980, Q-b PASS, Q-d 0 leaks; identical top-10s to the one-step fold of the same docs on 220/220 queries; `data/eval_results/delta_ingest_foldin_f6_20261009.json`) — fold-in not promotable (F0, F3, F8 FAIL; F7 FLAGGED). Gate still NOT eligible (owner chose to decide later, 2026-10-08).
- **2026-10-29 — federated router: coverage-aware date routing, live-failure fallback, calendar year cues** (`source/lib/federated_search.py`, `ThinClientRetriever.coverage_end()`, `source/lib/tools.py`; tests `source/tests/test_federated_search.py` 59 pass, `scripts/tests/test_thinclient_stack.py::test_coverage_end_*`). Defect found 2026-10-29 on the staged Duck Library server: the router read only `from_publication_date` against a start-date window, so `year_from=2026` (1 January, older than any window ≤ 300 days) and every `year_from`+`year_to` range (written as `publication_year`, never read) stayed on the local index, whose build is 2026-06-16 — four months of 2026 silently missing, while only cue words (`recent`, `latest`, …) reached live OpenAlex. Now: (1) `requested_range()` reads all three date filters; (2) a range starting after the local `coverage_end()` (manifest `built` day, or the delta publish day when later; also reported in `/health` metrics) routes live at any window, a range the local index fully covers never routes live by date, and only between those does `SFU_FEDERATED_RECENCY_DAYS` apply — the rule retires itself as coverage freshens; (3) the year cues are the current and previous calendar year, computed; (4) a live-leg failure falls back to the local route with a user-visible note (`last_live_fallback`) instead of an empty result — the client never raises, so `search_works` now answers `degraded: True` when `_get` returned None (budget, breaker, 429, 4xx incl. a 401 bad key) and the router falls back on that flag or an exception; a genuine zero-hit live answer does not fall back. Live terms verified the same day (`docs/EXTERNAL_API_CONTRACT.md` note 2026-10-29): publication-date filters work on the free key at `cost_usd` 0.001 per call; only the sync filters (`from_updated_date`) are paid-plan. Not changed: routing stays either/or (no live+local fusion; delta ingest remains the designed answer to the coverage gap), and the partially-covered open-ended case (`year_from=<this year>`) is still decided by the window — the owner's deployment override (365 days on the staged server) is the knob. **IMPLEMENTED, EFFICACY UNMEASURED** for ranking quality: no date-filtered judged query set exists; the 120-query benchmark has no date filters.
- **In-place update spike: CLOSED MEASURED 2026-09-30** (opened 2026-09-29;
  never a serving path). Its GO rule read NO-GO: dead-slot supply covers
  1.9 % of a quarter's new-posting demand in long lists (bar 80 %; 27 % of a
  shard's docs updated + 15 % new per quarter versus 6 % deleted). The v3
  encoder/decoder proved exact (B1 460/460, +1.3 % per query) and the +tail
  variant was built, but the mechanism fails on posting-slot supply. Record:
  `docs/archive/inplace_update/` (plan + results table), code
  `spike/archive/inplace_update/`, `scripts/archive/inplace_update/`,
  patches `spike/archive/inplace_update/patches/`. The served `.so`, the
  served shards and every serving default were never touched. Fork
  `spike/seismic_upstream`: `main` reset to 2c4d863 on 2026-09-30; the spike
  commits a3173d1..328bf51 live on fork branch `inplace-v3` (c7b4b54 on
  `b1-guard`); the installed `.so` (built 2026-08-10) never contained them; do
  not merge `inplace-v3` into `main` (owner decision 2026-09-30: the +1.3 % B1
  per-query cost is not acceptable on the serving path). M4/M5 stand
  on their own bars (`docs/delta_ingest/03_SPIKE_PLAN.md`): M4 growth bar
  FAIL (27.7 ms/gen), M5 PASS.
Gate unset ⇒ no code path differs (a code-reading claim, not measured
against pre-delta code; M1 measured that an EMPTY root serves exactly like
the gate unset, on aa0fc405). Known costs and the per-engine interaction matrix (score drift of
tiny BM25 segments, +1 shard/section/probe per generation, second query
encode while the buffer is non-empty, 6 h result-cache staleness, delta
files not covered by the staging levers → keep the delta root on local disk;
ordinal arrays for livedocs on local disk too) and the open issues found
2026-09-29 are in `02_DESIGN.md` §3–§4.

**Fork provenance (recorded 2026-09-29, corrected 2026-09-30):** this doc
does not state which commit of the SEISMIC Rust fork the served `.so` is
built from. `spike/CLAUDE.md` names `spike/seismic_upstream/` (gitignored
nested repository, tracked as `seismic_upstream_fork.patch`) as the LIVE fork. Its
`main` is `2c4d863` (`git -C spike/seismic_upstream rev-parse --short main`):
it moved to `328bf51` during the in-place spike (2026-09-29/30) and was reset
to `2c4d863` on 2026-09-30. The spike's commits a3173d1..328bf51 live on fork
branch `inplace-v3` (c7b4b54 on `b1-guard`); the installed `.so` (built
2026-08-10) never contained them (`hasattr(seismic, "inplace_v3_convert")`
is False). Do not merge `inplace-v3` into `main` (owner decision 2026-09-30:
the +1.3 % B1 per-query cost is not acceptable on the serving path). Whether
the installed `.so` was built from exactly `2c4d863` is not recorded
anywhere — UNVERIFIED.

### Rerank

Abstracts via hot sidecar / OpenAlex fetch (policy below). Second-pass
cross-encoder (`lib/reranker.py`): torch `models/sfu-cross-encoder-v1` is the
serving default; the int8 ONNX export is **OPT-IN via `SFU_CE_ONNX=1`
(default OFF, 2026-08-19)** — at the serve shape (batch of
`_CE_CANDIDATE_POOL`=20) torch measured **25.5 ms** versus int8 ONNX **288 ms**
on 16 cores, so the export's per-pair 19× does NOT transfer; ONNX is a
single-stream/low-core fallback only (2026-09-27: with CUDA absent the
order reverses, int8 ONNX 219 versus torch 337 ms CE-stage p50, but rankings
differ — see "CPU-only serving" below)
(`data/eval_results/ce_v1_inversion_check_20260819_1920.json`,
`scripts/archive/demo_dependability/check_ce_direction.py`). ⚠ Same audit, OPEN
model-quality question: v1 promotes injected off-topic real docs into the
top-5 at 24.4% versus base ms-marco's 3.8% (v1 still won the original judged
eval +0.064 nDCG@10 in-pool). **Judged serve-path eval 2026-08-19 on the
fresh 120-topic set** (`eval_ce_v1_vs_base.py`,
`ce_v1_vs_base_judged_20260819_2124.json`, 4,800 candidates, 0 unjudged):
RRF-top-20 → CE → nDCG@10 = none 0.7139 / v1 0.7904 / **base 0.8069**;
paired v1−base **−0.0165**, CI [−0.0281, −0.0051] — base significantly
better; v1's old win was on the contaminated original query set. One-env
flip: `SFU_CE_MODEL_PATH` (default unchanged = v1). **DECISION PENDING
(operator).**

**Fixed-shape scoring (2026-09-25).** The CE and the stage-1 embedder no
longer pad each call to its longest input: the CE scores in (10 pairs × 256
tokens) batches through `reranker._ce_score_pairs` (on CPU the
pooler/classifier head runs per row), the embedder in (11 texts × 256)
batches through `embedding.encode_texts`; short batches are filled with dummy
rows. A (query, doc) score is therefore bit-identical whatever else shares
its call (MEASURED on CPU threads 1/8/16 and CUDA), which lets lever #1 reuse
drafted per-candidate scores. 256 is both models' configured max length, so
truncation is unchanged (real serve pairs: 44% of CE pairs exceed 256 tokens
and were already truncated; tokenization identical on 800/800). **Ranking
effect MEASURED 2026-09-25 on the 120 natural topics** (serving flags, CUDA):
0/120 topics change top-10 order or set, 0/120 change the stage-1 top-20
order; max |Δ| CE 9.2e-6, stage-1 3.9e-7
(`scripts/experiments/eval_fixed_shape_parity.py`, `data/eval_results/fixed_shape_parity_2026-09-25.json`).

Latency p50 (ms), 2026-09-25, host otherwise idle:

| Where | old longest-padding | fixed shape | ratio |
|---|---|---|---|
| CE stage, 120-topic replay on identical inputs (CUDA) | 19.4 | 25.1 | 1.29× |
| stage-1 stage, same replay (CUDA) | 29.1 | 42.1 | 1.45× |
| CE, 20 real serve pairs, micro-bench (CUDA) | 19.1 | 24.2 | 1.27× |
| embedder, query + 20 real docs, micro-bench (CUDA) | 27.2 | 25.0 | 0.92× |
| CE, 20 synthetic pairs (CPU, 8 threads) | 344 | 312 | 0.91× |
| embedder, query + 20 synthetic docs (CPU, 8 threads) | 724 | 354 | 0.49× |

Sources: `data/eval_results/fixed_shape_real_pairs_cuda_2026-09-25.json`,
`fixed_shape_latency_sweep_{cuda,cpu_t8}_2026-09-25.json` (the CPU sweep
predates the per-row head; the CPU invariance runs include it). The serving
host for this container runs both models on CUDA; the 16-core CPU rows are
for a CPU-only deploy. Batch sizes came from the same sweep: CE B=20 would
make a 9–10-pair remainder cost a full 20-row batch, so reuse would save
nothing; B=10 keeps the full pool within 1.5× of the old path. Contract:
`CODE_INVARIANTS.md` §reranker "Fixed-shape scoring".

**CPU-only serving (CUDA absent) — MEASURED 2026-09-27.** Both rerank models
pick their device automatically (no hard-coded `.cuda()`), so the serve path
runs unchanged with CUDA hidden (`CUDA_VISIBLE_DEVICES=""`) and with a
CPU-wheel venv (`torch 2.6.0+cpu`, `onnxruntime 1.26.0`, no CUDA packages).
120 natural topics, 2 passes per arm, serving flags: final top-10
byte-identical to the CUDA arm on 120/120 (fused list 120/120, stage-1 top-20
order 120/120; max |Δ| CE 1.7e-5, stage-1 5.3e-7). Pooled p50 / p95 (ms),
CUDA → CPU (8 torch threads): total cache-miss 4,966 / 7,170 → 5,789 / 7,923
(+823 ms p50, +17%); stage-1 embed 233 → 721; CE 56 → 337; retrieval legs
unchanged (CPU in both arms). On the real serve inputs the CPU stage-1 costs
about 2× the synthetic 354 ms row above. The int8 ONNX CE (`SFU_CE_ONNX=1`)
is faster than the torch CE on CPU (CE p50 219 versus 337 ms), unlike on CUDA,
but it changes top-10 order on 108/120 topics versus torch v1 (max |Δ| score
1.63), so it is not a like-for-like CPU substitute
(`scripts/experiments/eval_cpu_only_serve_path.py`,
`data/eval_results/cpu_only_serve_path_2026-09-27.json`;
`infrastructure/PORTABLE_STACK_MANIFEST.md` §(d) row 6).

**Speculative rerank on the BM25F draft — lever #1 (`SFU_SEARCH_SPECULATIVE_RERANK`,
default OFF). IMPLEMENTED 2026-09-25 (per-candidate reuse over fixed-shape
scoring); PARITY MEASURED 120/120 byte-identical gate-on versus gate-off;
one-pass latency below (bars in `SPECULATIVE_RETRIEVAL_UPGRADES.md` §6 step 4).** With literal `1`,
`FederatedSearchRouter.search` (LOCAL_RRF) hands the BM25F leg's hydrated
top-k to one background thread (`lib/speculative_rerank.py`) as soon as that
leg returns; the thread runs the real `tools._maybe_rerank_impl` over the pool
the router would return if SPLADE added nothing, recording each stage-1 and
CE call with the items it scored. After fusion the draft is bound to the
fused list; the real `_maybe_rerank` reuses the drafted score of every
candidate that is also in the fused pool and scores only the remainder, which
is byte-identical to gate-off because both paths use fixed-shape scoring
(above). Single draft slot (drop when busy); a draft CE batch never overlaps
a real CE pass. **One warm pass, 120 topics, 2026-09-25** (`data/eval_results/fixed_shape_parity_2026-09-25.json`):
stage-1 reuse 1,323 / 2,400 candidates (55%, ≈ acceptance), CE reuse only
194 / 2,400 (8%) because 102/120 drafts were abandoned before their CE batch
(the real pass consumed first); stage-1 stage p50 250 → 165 ms, CE stage p50
39 → 32 ms (≈ 92 ms p50 attributable); cache-miss total p50 5,454 → 5,045 ms,
p95 7,677 → 6,988 ms, but single-pass totals are dominated by leg variance, so
only the ~92 ms stage saving is attributable. **Multi-pass A/B 2026-09-25
(commit 6d83760a, draft CE batch started alongside the stage-1 draft;
`scripts/experiments/eval_speculative_multipass_ab.py`,
`data/eval_results/speculative_multipass_ab_2026-09-25.json`, OFF/ON × 3,
360 requests per arm):** parity 360/360; CE reuse 1,323 / 2,399 (55.1%, the
acceptance ceiling), stage-1 reuse 55.1%, 0/120 drafts abandoned before CE;
`_maybe_rerank` p50 282.7 → 202.9 ms (−79.8 ms attributable); total
cache-miss p50 5,031 → 5,155 ms (not reduced, inside leg variance), p95
ratio 1.0002. **Verdict: p50 bar (≥ 128 ms) FAILED, gate stays OFF**; the
ceiling at 55% acceptance is below the bar. Invariants: `CODE_INVARIANTS.md`
§"source/lib/speculative_rerank.py". Both LOCAL_RRF legs run in the
retriever's `hydrate_scope()` (lever #0), so the router path hydrates each
candidate once per request. Lever #0 MEASURED 2026-09-27 (3 × 3-pass
A/B, `scripts/experiments/eval_hydrate_once_ab.py`,
`data/eval_results/hydrate_once_ab_2026-09-27.json`): fused + final lists
byte-identical 120/120 in all passes, duplicate-hydrate ids 3.98% → 0, hydrate
stage p50 130.2 → 128.8 ms (−1.4 ms, below the ~7 ms *est.*); total cache-miss
delta inside leg variance.

**Term-prefix block prefetch — lever #4 (`SFU_BLOCK_PREFETCH`, REMOVED): CLOSED
MEASURED 2026-09-25**, never wired to serving. WILLNEED over the typed prefix's
posting lists cut cold SEISMIC traverse p50 only 1658.9 → 1590.3 ms (−4.4% paired,
bar ≥ 20%) and slowed the RAM-resident arm 27.9 → 35.6 ms
(`data/eval_results/block_prefetch_ab_2026-09-25.json`; code in
`spike/archive/block_prefetch/`; `SPECULATIVE_RETRIEVAL_UPGRADES.md` §4 row 4).

## Serving swap & hardening

`SFU_SEARCH_BACKEND=thinclient` (default) makes `tools.py` construct
`lib.thinclient.retriever.ThinClientRetriever` — a drop-in for
`OpenSearchRetriever` (same `search/dense_search/is_available` surface and
result shape). *(2026-10-11 note: the `opensearch` value no longer restores a
backend. Any `SFU_SEARCH_BACKEND` other than `thinclient` raises `RuntimeError`
("only 'thinclient' is served; the OpenSearch backend was decommissioned
2026-06-11"); the `OpenSearchRetriever` class is archived at
`scripts/archive/opensearch_era/opensearch_retriever.py`.)*

Hardening (2026-06-11 evening): SPLADE query-encoder fallback (lexical +
dense still serve if the encoder dies), per-leg latency metrics + JSONL query
log (`SFU_METRICS_LOG_PATH` / `SFU_QUERY_LOG_PATH`), and four
index-management MCP tools: `get_index_status`, `list_personas`,
`request_section_unpack`, `reload_index`.

**Full MCP tool surface (trimmed 2026-10-12, owner decision):** both servers
advertise 18 tools over stdio and `/mcp`: the search tools (`search_academic`,
`search_by_author`, `search_by_doi`, `search_by_topic`, `search_biomedical`),
the doc-level tools (`get_citations`, `get_references`, `get_paper_summary`,
`find_open_access`, `get_full_text_link`), the library tools
(`browse_library_databases`, `check_library_access`), the Zotero write tools
`save_to_zotero` / `batch_save_to_zotero` (which the demo broker blocks for
visitors) and the four index-management tools above. None is called by the web
GUI except through `/api/*`. The nine tools no doc named (`generate_citation`,
`batch_generate_citations`, `export_search_results`, `list_zotero_collections`,
`search_zotero`, `get_zotero_collection_items`, `get_zotero_status`,
`get_openalex_budget`, `record_engagement`) were removed 2026-10-12 by owner
decision (`infrastructure/CODEBASE_TRIAGE_2026-10-11.md` decision 6), together
with the APA/MLA/Chicago/BibTeX/RIS formatters in `citations.py` and the
Zotero read helpers only they used; calling one now returns "Unknown tool".
The GUI records engagement through `POST /engagement` (`lib/engagement.py`
stays). The removed code is kept by the owner (restore tag
`pre-owner-decisions-2026-10-12`).

**Duck Library rebrand of the MCP surface (2026-10-10):** the two
database-registry tools are advertised as `browse_library_databases` and
`check_library_access`; the old names `browse_sfu_databases` /
`check_sfu_access` are no longer listed by `tools/list` but still dispatch
(string aliases in `tools._dispatch_tool`), so any client that hard-codes
them keeps working. Tool descriptions and text outputs say "Duck Library";
the registry/EZProxy endpoints they call are unchanged. The MCP server
name stays `"sfu-library"` (owner decision pending). Full alias list and
rollback: `docs/infrastructure/REBRAND_DUCK_LIBRARY_2026-10-10.md`.

**Metrics log `ids` + `session` (2026-09-25, specification
`SPECULATIVE_RETRIEVAL_UPGRADES.md` §4b):** every `SFU_METRICS_LOG_PATH`
line (written by `tools._persist_metric` for each `handle_tool_call`, stdio
and HTTP alike) now also carries `session` and `ids`. `session` is a
per-process 8-hex id (`secrets.token_hex(4)`, the `serve_query_log._rand_id`
style); the HTTP `call_tool` binds the request's `mcp-session-id` header
instead when the client sent one — the session manager runs `stateless=True`,
so usually it did not and HTTP lines share the process id. `ids` is the ranked
top-10 of search tools (`search_academic` both branches, `search_by_author`,
`search_by_topic`, the S2 fallback, Europe-PMC `search_biomedical`), each
the `normalize_doi()` DOI when present else the OpenAlex id (Europe PMC:
DOI else `pmid:<n>`), and `[normalize_doi(doi_arg)]` for doc-level tools
(`search_by_doi`, `get_paper_summary`, `get_references`, `get_citations`,
`find_open_access`, `get_full_text_link`); `null` everywhere else and on
early validation returns. Log-only: tool text output is byte-identical
(pinned in `source/tests/test_metrics_log.py`). Purpose: makes the lever #5/#6
follow-up rate (Q1 of §4b) measurable; no prefetch code exists.

```json
{"ts": "2026-09-25T22:31:02.114Z", "tool": "get_paper_summary", "latency_ms": 412.7, "success": true, "server_version": "<SERVER_VERSION>", "session": "9f3c01ab", "ids": ["10.1038/nature14539"]}
```

**Production query-log capture (deployprep WI-2, 2026-07-16):**
`lib/serve_query_log.py` — staging-default ON (`SFU_SERVE_QUERY_LOG=1`/`=0`;
an explicit production profile defaults OFF), privacy-sane (normalized query
+ sha1 hash; raw only with `SFU_SERVE_QUERY_LOG_RAW=1`), ~0 hot-path cost
(async daemon thread + bounded non-blocking queue that drops+counts on
backpressure), size-capped rotation (live + `.1`,
`SFU_SERVE_QUERY_LOG_MAX_BYTES`). Captures per served query: query hash, k,
mode, SPLADE backend + federation mode, per-leg latencies (diffed from the
retriever's `_leg_metrics`), result count, result-set fingerprint (sha1 of
top-k oaids — the hot-set key), filters shape, session. Wired into
`tools.search_academic_structured` (the `/api/search` path). Unblocks the
`disk_streaming_research/` LRU/pin gate (which had to synthesize a log for
Q12/Q12b). Replay/summary:
`scripts/seismic_testbed/wi2_query_log_replay.py`. Tests:
`scripts/tests/test_serve_query_log.py` (13/13).

**Read-through result cache on `/api/search` (WI-17, 2026-07-18):** wraps
`api_search` in the existing thread-safe `lib/cache.ResponseCache` (TTL + LRU
+ memory-bounded; no new cache class). Contract terms (owner-audited
2026-07-18, binding):

- **cache-aside, never fail a search** — every cache op wrapped; any
  exception falls through to the uncached path;
- **normalized, versioned key** —
  `v1|<norm_query>|limit=…|page=…|year_from=…|year_to=…|oa=…|type=…|prefer_local=…|stamp=<manifest_built>@<engines>`
  in FIXED field order (casefold/whitespace/outer-punct normalization
  mirroring the serve-log normalizer); an index/model swap rotates the stamp
  → new key → never serves stale;
- **never cache a bad response** — no errors, no empty error-shaped
  payloads, no degraded/leg-breaker (WI-9 `router.last_degraded`) or BM25F
  silent-fallback (WI-13) responses, nothing while warmup is pending;
- **TTL/size** — 6 h TTL (static index between updates), `max_size=256`,
  `max_memory_mb=64` backstop (sizing measured in WI-17c);
- **observability** — hit/miss/store/bypass + resident + hit_ratio on
  `/health` under `result_cache`; `cache_hit` tri-state in the serve log.

Environment: **`SFU_RESULT_CACHE`** — staging-default ON, `=0` is the one-env
rollback (owner-granted exception to the no-served-default-flip rule for
this wave ONLY). Tunables: `SFU_RESULT_CACHE_TTL`, `_MAX_SIZE`, `_MAX_MEM_MB`.
Post-warmup pre-seed: **WI-17b** (`SFU_CACHE_PRESEED`, default ON;
standalone re-primer `scripts/prime_result_cache.py`). Tests:
`source/tests/test_result_cache.py` (26/26). **Efficacy measured 2026-07-18
(WI-17c, F6)** → `data/eval_results/result_cache_ab_2026-07-18.json`
(`scripts/experiments/eval_result_cache_ab.py`), all 4 bars PASS on the warm+primed
staging serve: (A) cache-hit p50 **3.7–4.1 ms** versus genuine cold-miss p50
0.2–3.0 s = **50×–776×** for the 6 seed queries, n=20/leg (speedup
recomputable from the stored p50 fields; raw arrays in the JSON); (B)
round-trip parity; (B2) cached response byte-identical to a FRESH CACHE-OFF
run (parsed-JSON equality, all 6 queries —
`scripts/experiments/eval_result_cache_parity.py`); (C) miss-path latency unchanged
(get→None→search→put overhead sub-ms). The resident count hit the 256 cap
mid-run and LRU-evicted correctly.

**Searchbar keystroke speculation (WI-18, 2026-07-18):** OPT-IN predictive
prefetch layered on WI-17. Debounced client helper
(`web/lib/api.js::createSpeculationController`, ≥400 ms idle AND ≥8 chars)
asks the server to speculate the finished query through the SAME
read-through cache + key recipe a real submit produces — **not a second
cache**. **Default OFF** (`SFU_SEARCH_SPECULATE` — the owner reviews measured
hit-rate/waste/interference and flips the default, not the build). Contract
terms (owner-audited 2026-07-18):

- **same cache, same key** — speculation primes through `read_through`;
- **predictor before literal** — candidate pool = the live landing examples
  (read from `web/source/search.jsx` SOURCE) + `demo_seed_queries.txt` +
  `speculation_bench_queries.txt` + distinct serve-log queries; normalize,
  prefix/containment-match; speculate the full predicted query only when
  exactly one candidate matches and adds real information
  (`SFU_SPECULATE_MIN_RATIO`, default 0.35 = predicted ≥1.35× typed length);
  else the literal typed text (`SFU_SPECULATE_LITERAL`, default OFF →
  no-match suppresses). Deterministic string matching, NO ML. A
  request-level `force_literal` override (2026-07-28, WI-19b) lets the bench
  measure predictor-vs-literal in ONE serve lifetime;
- **guards** — never speculate when warming, degraded (WI-9/WI-13), cache
  disabled, shedding (WI-11), or typed < `SFU_SPECULATE_MIN_LEN` (default 8);
- **single-slot** — at most ONE speculative query in flight (single-GPU CE);
  a newer speculation while busy is DROPPED, never queued; speculation-path
  exceptions fall through silently;
- **log honesty** — `speculative:true` marked via a contextvar; `cache_hit`
  stays uncontaminated (a speculation that hits is `cache_hit=true` AND
  `speculative=true`).

Endpoint `POST /api/speculate` (harmless no-op when OFF). `/health` gains a
`speculation` counter block (fired/dropped_busy/suppressed_by_guard/
predicted/literal/stores + per-reason suppression). Tests:
`source/tests/test_speculation.py` (24/24, incl. route-level api_search returns
— HOST-NOTE-W8-2 #2 — and the WI-19b override); jsdom +6 controller cases.
**Efficacy measured 2026-07-18 (WI-18b)** →
`data/eval_results/speculation_ab_2026-07-18.json` (arm A only — HISTORICAL,
superseded by the 2026-07-28 same-session run). **WI-19a protocol fix
(2026-07-28):** the arm-C harness plays the typing timeline in REAL
WALL-CLOCK TIME; Enter fires at `enter_t` REGARDLESS of speculative-store
state; `resident_by_enter` is observed at the real Enter instant (hit
counter advanced AND Enter returned 200); the pre-Enter wait-for-store probe
that inflated hit-rate-by-construction is DELETED; arm G is genuine
OFF-vs-ON byte-parity. **Measured 2026-07-28 (WI-19b, F6)** →
`data/eval_results/speculation_ab_2026-07-28.json`; numbers + owner
recommendation in `docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md` §Wave 8–9.

## Web GUI — Library Suite (2026-06-19)

Lives in `web/`, served by the HTTP entry point (`source/sfu_library_mcp_http.py`)
as **static files at `/app`** — no Node/npm build step at serve time.
Implements the `claude.ai/design` handoff bundle. Visible branding is Duck
Library (suite GUI 2026-08-21; remaining visible strings — mock access
labels, the admin e-mail placeholder, the Index Manager env-gate labels —
2026-10-10, assets rotated `?v=duck6`→`?v=duck7`; `?v=duck8` on 2026-10-11 when the dead GUI code and the tweak panel were removed; `?v=duck9` on 2026-10-12 for the engagement client + analytics panels). Code identifiers
(`window.SFUApi`/`SFUUI`/`SFUHistory`/`SFUMock`, `sfu-*` DOM ids, localStorage
keys, `sfu_proxy` access types) stay `sfu` — renaming them would reset saved
preferences/history and break the verify harnesses for no visible gain; see
`docs/infrastructure/REBRAND_DUCK_LIBRARY_2026-10-10.md`.
**2026-09-25:** the cloud host is gone — the operator has no cloud instances,
the OCI demo box and every DigitalOcean droplet are gone for good, so the Duck
Library broker (`scripts/demo_broker/`, incl. its watchdog timer/ntfy alerting
and the `DEMO_PIN_RUNNING` gate) is dormant and the suite is served locally
only; see `docs/infrastructure/OCI_DEMO_DEPLOYMENT.md`.

**Stack:** vendored React 18.3.1 + ReactDOM + Babel-standalone (`web/vendor/`,
no CDN). Since 2026-07-18 `scripts/build_web.mjs` pre-compiles JSX
(`web/source/*.jsx` → `web/*.js`) so the browser never runs the 3 MB in-browser
transformer.

**Apps:** `web/suite.html` = shell at `/app` (iframes one app at a time,
`postMessage` coordination: `suiteReady`/`suiteNav`/`suiteScreen`);
`web/search.html` = primary search app (6 screens); `web/analytics.html` =
"About this index" (since 2026-10-12 every figure on it comes from the `/analytics`
bundle; operator + engagement panels behind two collapsibles);
`web/index_manager.html` = personas/sections, warm cache, storage budget.

**Shared client (`web/lib/`):** `api.js` (`window.SFUApi`) calls the live
backend and falls back to `mock.js` on any error/timeout; `ui.js` renders a
demo-data indicator whenever mock/fallback data is shown. The AI-status pill
reflects real backend reachability via `/health`.

**GUI-facing REST endpoints** (`sfu_library_mcp_http.py`): `POST /api/search`
(→ `tools.search_academic_structured()`, structured `{results, meta, notes}`;
the MCP `search_academic` text tool unchanged); `GET /api/index_status`;
`GET /api/personas`; `POST /api/unpack` (background unpack);
`GET /analytics` + `POST /engagement` (pre-existing, reused). *(2026-10-12: the GUI
calls `/health`, `/api/search`, `/api/search_stream`, `/api/speculate`,
`/analytics`, `/api/unpack` and `POST /engagement`; `GET /api/index_status` and
`GET /api/personas` are still served with no GUI caller. The 2026-10-11 state "no
GUI action records an engagement event" ended with owner decision 7 of
`CODEBASE_TRIAGE_2026-10-11.md`, resolved 2026-10-12: GUI wired, see "Engagement +
analytics GUI" below.)* Static mount is
conditional on `web/` existing (headless deploys: `/app` 404s).

**Engagement + analytics GUI (2026-10-12, owner decision "write the GUI for analytics
and engagement"):**
- **What the search app posts** (`web/lib/api.js` `SFUApi.engagement`, wired in
  `web/source/search.jsx`): one `query` event per completed live search (`refined_from` =
  the previous query of the tab when it differs); one `impression` per displayed,
  non-preliminary, non-sample result (rank = 1-based position across the merged pages,
  `doc_id` = DOI without the `https://doi.org/` prefix, else the OpenAlex id, the same
  preference as `lib/engagement.log_impressions`; deduplicated per query+doc until the
  next query); `result_click` when a result card is opened (rank, doc_id, query of the
  displayed list); `action` events: detail open → `abstract`, DOI / full-text / Access
  link → `pdf`, citation copy (card and detail) → `citation`, bookmark (only when it
  saves, not when it unsaves) → `save` (new action type, added to `ACTION_TYPES` in
  `lib/engagement.py`).
- **Write path:** `POST /engagement` on the HTTP server (`lib.engagement.record_engagement`)
  is the only entry point since 2026-10-12; the `record_engagement` MCP tool was removed
  the same day (owner decision, MCP-surface trim), and the `record_engagement` docstring
  in `lib/engagement.py` no longer names it.
- **Session id:** one per browser tab, `sessionStorage["sfu_engagement_session_v1"]`
  (`g-` + 24 hex chars from `crypto.getRandomValues`, random fallback when storage or
  crypto throws). The suite iframes share it.
- **Batching:** events queue client-side and flush as `{"events": [...]}` (≤ 50 per
  batch, queue capped at 500, oldest dropped) with `fetch(BASE + "/engagement",
  {method: "POST", keepalive: true})` 2 s after the first queued event or at 50 events;
  `navigator.sendBeacon` on `pagehide` when available. Fire-and-forget: never throws,
  never awaited by the UI. Nothing is queued or posted while the backend is in mock mode
  (the last `/health` or search answer was the mock fallback); the integrity floor (demo
  banner, degraded notices, backend pill) is untouched.
- **Server-session exclusion:** `tools._log_query` still writes impressions under
  session `"server"` when `SFU_FEATURE_ENGAGEMENT_LOG_ENABLED` is on (default OFF; the
  GUI's `/api/search` also reaches `_log_query`). `lib/analytics.py`
  `engagement_source()` makes `position_bias` and `session_replay` drop every
  `"server"` row whenever any non-server impression exists, and each panel reports what
  it counted in `"source"`: `"gui"`, `"server"` (only server rows exist) or `"none"`
  (empty log). Impression rows no longer open a session node in `session_replay`, so
  the impressions-only server session never shows as an empty session.
- **Analytics app** (`web/source/analytics.jsx`, "About this index"): renders all nine
  bundle panels: `kpis` (per-method NDCG@k / MRR / P@k table from
  `data/eval_results/benchmark_llm_judge_final.json`, 120 queries, Haiku judge,
  2026-05-16), `ndcg_by_subject`, `reranker_signal`, `model_versions` (table),
  `position_bias` (per-rank impressions/clicks/P(click)/propensity; the
  `awaiting_click_data` state shows "N of the 20 clicks needed", 20 =
  `_MIN_CLICKS_FOR_PROPENSITY`), `session_replay` (query → clicked result → actions,
  newest first, 20 sessions shown), and the three stubs (`embedding_drift`,
  `access_funnel`, `oa_equity`) as "Not wired: <reason>". A tenth panel, `index_shape`
  (new 2026-10-12), reads `<SFU_THINCLIENT_INDEX_ROOT or data/thinclient_index>/manifest.json`
  read-only (per-section doc counts), `lib.thinclient.sections.ERA_BOUNDARY_YEAR` and
  `lib.federated_search._RRF_K`; it feeds the facts row, the subject/era charts and the
  disclosure figures. Every prototype placeholder figure was removed (NDCG@10 0.561,
  Recall@50 0.967, dense seed 600k, the per-leg latency bars, the language split, the
  63/37 era split, the discipline bars, "roughly 7 million" in "other", "June 2026",
  top-64 / 8-bit). The real manifest says the unrouted `other` bucket holds 57,820,012
  documents (38.4%), not ~7M, and the era split is 145,930,797 recent / 4,482,301
  archive. In mock mode every panel is a "Not wired: live backend unavailable" stub
  (`web/lib/mock.js`), so the demo shows no figures.
- **Verified 2026-10-12:** `node scripts/verify_web_jsdom.mjs` 105/105 (was 74; +31:
  query + impression posts, card click → result_click rank, abstract/pdf/save actions,
  refined_from, batch shape against the `validate_event` rules, client/server vocabulary
  parity, the pure queue (timer, full-batch, invalid-event, throwing-transport cases),
  mock mode posts nothing and keeps the banner, the analytics app's nine panel states
  from a fixture bundle including the stub notices and the awaiting-click state, no
  prototype figure, offline → all stubs + banner); `node scripts/verify_web_progress.mjs`
  18/18; `source/tests/test_engagement_gui.py` 14 passed (route accepts the GUI batch
  end-to-end through Starlette `TestClient` into a tmp `SFU_ENGAGEMENT_LOG_PATH`, beacon
  body without a JSON content type, invalid events skipped, `save` valid,
  ACTION_TYPES/KINDS parity, server-session exclusion in both panels, `index_shape`,
  `kpis`). Playwright `e2e_sweep.mjs` NOT RUN (Playwright not installed), so real-browser
  overflow and layout shift on the new panels are unverified. Assets rotated
  `?v=duck8` → `?v=duck9`.
- **Efficacy:** IMPLEMENTED 2026-10-12; click-fed panels populate from first use, no
  click data existed before.

**Result paging / infinite scroll (2026-09-01):** the search app pages
results client-side (PAGE_SIZE 10, cumulative fetch, server clamps
`limit` ≤ 50; IntersectionObserver + button fallback) because the federated
path ignores `page` — contract + rationale recorded in
`docs/infrastructure/OCI_DEMO_DEPLOYMENT.md` §"GUI result paging". jsdom
suite now 42 checks.
**2026-09-25:** the contract still governs the local GUI, but the OCI demo it
was written for is gone — cloud access ended, that doc is history-only.

**Startup warmup + `warm` on `/health` (2026-07-18):** one background
structured search at startup (`SFU_HTTP_WARMUP=0` disables) because the stack
lazy-loads on first `/api/search` — measured **2m24s cold** versus 6–20 s warm
(in-container 9p). `/health` gained `warm: bool` + `warmup:
disabled|warming|warm|failed` (`warming` → `warm:false`; every other state →
`warm:true`); `api.js` already treated absent-⇒-warm. The warmup also
serializes first model loads: concurrent HF construction across threads
corrupted models via accelerate's global meta-device init ("Cannot copy out
of meta tensor", transient SPLADE ImportError, warm-cache self-disable — all
observed 2026-07-18); all four model loaders now hold
`lib/hf_load_lock.HF_LOAD_LOCK` during construction. `api.js` request timeout
raised 12 s → 30 s the same day (measured warm `/api/search` p50 ~10 s /
worst 20.6 s — 12 s silently dropped live searches to demo data).

**Warm-latency root cause + fix (profiled 2026-07-18):** the ~10 s was the
SEISMIC leg on the repository's **9p bind mount**: 9p random mmap page faults run
~**1,830 faults/s (~0.5 ms each)**; a query faults ~15k pages ⇒ ~8 s, and 9p
page cache does not stay resident, so every distinct query re-faults cold.
The documented warm p50 ~47–65 ms (WI-1/G8g) is the pages-resident number,
reachable only on a native FS.

- **Not the lever:** federation mode — clean cold A/B measured parallel p50
  9134 ms versus sequential 8747 ms (within noise; an earlier "sequential
  227 ms" was a 9p host-cache artifact). The `SFU_SEISMIC_FEDERATION` default
  is FS-aware anyway (sequential on passthrough FS, parallel on native disk)
  but that is a RAM/warm-hold choice, not the latency fix.
- **The fix:** serve shards from a native filesystem — measured **~300k
  faults/s (~160–240× 9p)** and residency holds. `SFU_SEISMIC_STAGE_DIR=<native
  path>` stages the shard set once (idempotent `.staged_ok` marker; adopts a
  copy made by `scripts/stage_seismic_local.sh`). **On a DO droplet this is a
  no-op by construction** — the 9p wall is a WSL2-dev-container artifact.
  Portability rule: never serve the SEISMIC index off a 9p/virtiofs/NFS
  mount.
- **Verified end-to-end (staged native overlay, 2026-07-18):** SEISMIC leg
  warm p50 ~82 ms and it holds across passes; real `/api/search` first-touch
  2.5–3.9 s, warm repeat **0.86–1.36 s** (was 8–17 s) — the remaining ~1 s is
  CE rerank + meta hydration. The development container sets
  `SFU_SEISMIC_STAGE_DIR=/var/tmp/seismic_stage` in gitignored `.env`; the
  warmup faults a 6-query subject-diverse battery.
- **Staging never deletes what it cannot replace (fixed 2026-09-29,
  `585f3cab`):** a process given `staged_manifest.json` while
  `SFU_SEISMIC_STAGE_DIR` pointed at the same directory removed staged
  shard 0 (re-staged the same day; `data/seismic_150m/` untouched).
  `_stage_shards_local` now skips a shard whose source is its own staged
  path and re-copies via `<name>.tmp-<pid>` + replace. Test
  `scripts/tests/test_seismic_shard_staging.py` (5 cases, 2 fail on the old
  code); invariant in `CODE_INVARIANTS.md`. No latency effect expected or
  measured (the change is on the staging path, not the query path).
- **The same lever for `meta.sqlite` (IMPLEMENTED + MEASURED 2026-08-17,
  default OFF):** filter stage 222.2 ms on 9p versus 4.0 ms local (doc 18 §14).
  The shipped `retriever._stage_meta_local` path reproduces the hand-copy
  result: `_post_filter` p50 **186.7 ms unstaged (9p) → 2.97 ms staged
  (overlay) = 62.8×** at 500 candidates/query, 12 queries × 3 reps, n=36/arm,
  interleaved + order-randomized, **parity 36/36**
  (`spike/meta_consolidation/20_n8_meta_stage_shipped.py`,
  `data/eval_results/n8_meta_stage_shipped_20260817.json`). The 24.9 GB copy
  took **194 s** (fingerprint-verified); a second call skipped in **0.01 s**;
  `PRAGMA quick_check` ok, 150,413,098 rows. A copy killed at 16.9/24.9 GB
  left only the `.tmp-<pid>` file — nothing openable, the property the
  atomicity buys. Exercise on the real file (development container, ~25 GB local
  disk, minutes of 9p read — not while a big eval owns the machine):

  ```bash
  cd /workspaces/sfu-library-thinclient
  SFU_META_STAGE_DIR=/var/tmp/meta_stage SFU_META_STAGE_VERIFY=fingerprint \
  .venv/bin/python3 - <<'PY'
  import sys, time; sys.path.insert(0, "source")
  from pathlib import Path
  from lib.thinclient import retriever as R
  src = Path("data/thinclient_index/meta.sqlite")
  t0 = time.perf_counter()
  dst = R._stage_meta_local(src)
  print(f"staged -> {dst} in {time.perf_counter()-t0:.0f}s")
  c = R._connect_meta(dst, staged=True)
  print("rows:", c.execute("SELECT count(*) FROM docs").fetchone())
  print("integrity:", c.execute("PRAGMA quick_check").fetchone())
  PY
  export SFU_META_STAGE_DIR=/var/tmp/meta_stage   # then serve with it set
  ```

  `SFU_STAGE_META=1` reuses `SFU_SEISMIC_STAGE_DIR` (one directory for both
  artifacts); `metrics()["meta_staged"]`/`["meta_path"]` report which copy
  serves.

**Portability / droplet survivability (2026-07-18):** canonical launcher =
`scripts/serve_http.sh` (repo-relative, venv-with-PATH-fallback).
`SFU_EMBEDDING_MODEL_PATH` defaults repo-relative to
`models/sfu-academic-embed-v5` when unset, and a configured absolute path
that doesn't exist falls back to the repo-local same-named model with a
warning — the development container BAKES `.env` into container environment at creation, so
a stale absolute path survives `.env` edits until recreate; a droplet
without `.env` previously served the off-the-shelf HF fallback silently.

**Search history (2026-07-18):** the PubMed/EBSCO/library-discovery pattern — a capped
(100) reverse-chronological localStorage list (`window.SFUHistory` in
`web/source/_sidebar.jsx`) recorded by every executed search; sidebar "Recent
Searches" panel (all apps, click = rerun, cross-app pending-query handoff) +
a History screen (rerun / per-row delete / clear all). `savedHistoryNav`
defaults ON. Verified same day: jsdom 14/14, progress 18/18, Playwright e2e
13/13.

**Efficacy — verified 2026-06-19** (UI; verification automated): all 3 apps +
`tweaks-panel.jsx` compile under vendored Babel *(2026-10-11: `web/tweaks-panel.jsx` deleted — the build never read it and the inlined design-time panel was removed from `search.jsx`, see `CODEBASE_TRIAGE_2026-10-11.md`)*; lib logic unit-tested
(11/11: live→mock fallback, result normalization, banner source); full jsdom
mounts offline AND online with zero runtime errors (banner offline, absent
online); simulated query renders live results, live-but-empty falls back
with banner; live-server checks all 200 (static `/app/*`, `/analytics`,
index/personas, structured `/api/search`, validation 400s, `/engagement`).
Known trait: index-touching endpoints lazily load the 24 GB
`meta.sqlite`+sections and can block the event loop on first call — the
client timeout → mock fallback is the intended mitigation.

**Post-launch hardening (2026-06-19):** fixed a Settings crash
(Rules-of-Hooks violation — `useState` inside `.map()` → extracted
`PrivacyToggle`); accessibility baseline `web/lib/base.css`
(prefers-reduced-motion, focus-visible rings, text-zoom safety, long-token
wrap, small-window sidebar shrink, favicon); sidebar 220→256px, ~44px nav
rows; Index Manager responsive (persona grid stacks ≤1400px) — 0px
horizontal overflow at 1280/1366/1536/1920; e2e harness
`scripts/e2e_sweep.mjs` (every screen/tab at 4 viewports + deep pass + shell
swaps, console errors/crashes/overflow, cross-app design-token consistency,
banner no-layout-shift, load timing).

**UX round 2 (2026-06-19):** suite shell keeps one iframe per app alive
(toggled by display — kills the white-flash recompile; branded loader on
first load); design tokens unified across apps (accent `oklch(52% 0.18 25)`,
radius 8/5/12, shared shadows; Search default accent teal→red); demo
indicator became a fixed corner pill (zero layout shift); FIPPA note removed
from Privacy per request; public live access via the dedicated Cloudflare
tunnel (`<suite-host>`, creds in gitignored `.env`).

### Search progress + bare-bones default — WI-15 (2026-07-17)

Implements `docs/infrastructure/GUI_BAREBONES_PROGRESS_SPEC.md` (the
contract: threshold table, tier/toggle table, integrity floor). Source:
`web/source/search.jsx`, `web/lib/api.js`, `web/lib/interface_prefs.js`,
`web/source/_sidebar.jsx`, `web/suite.html`. No API changes — the GUI reads
`warm` on `/health` (forward-only) and forwards WI-11 `Retry-After` +
WI-9/10 `degraded`/`degraded_shards`.

- **§1 progress (real signals only, no fake percent):** <300 ms → nothing;
  300 ms–10 s → skeleton cards matching live `ResultCard` geometry (zero
  layout shift) + elapsed counter; >10 s AND `warm=false` → honest "index
  warming"; HTTP 429 → determinate countdown from `Retry-After` + one
  auto-retry; degraded flags → results + one-line notice. Shimmer is
  opacity-only, ~0 ms under prefers-reduced-motion.
- **§2 bare-bones + toggles:** Tier-0 = search box + results + one status
  line; filters are a collapsed Tier-1 expander; the rest are Settings →
  Interface Tier-2 toggles (localStorage), all default OFF except
  density=comfortable. **Integrity floor:** demo banner, degraded notices,
  backend pill have NO toggle (unhideable). The shell refuses to mount
  iframes for toggled-off apps and tears them down when toggled off
  mid-session.
- **Verified 2026-07-17:** Babel compile OK; jsdom 14/14 (offline/online
  mount, search renders, 429 retry shape, degraded pass-through, warm
  semantics, prefs persist, integrity floor); progress 18/18 (default-bare,
  skeleton timing, no layout shift, countdown, toggle persistence); e2e
  PASS 6 run live 13/13 (Chromium in-container: Playwright 1.61.1 +
  chromium-headless-shell 149.0.7827.55, npx-cache-resolved). One real bug
  found+fixed: the landing screen early-returned before the progress render,
  so the first cold-start search showed no progress signal.

**Full-interaction testbed (2026-07-17):** `scripts/gui_testbed/` layers
action generation over one invariant oracle — L-A element enumeration, L-B
model walk of the §2 toggles, L-C seeded-gremlins chaos (backend-dead, hang,
429-storm, storage-corrupt; vendored gremlins.js 2.2.0), L-D continuous
resize/zoom/DPR. L-D caught a narrow-viewport `main` overflow the ≥1280px
sweep missed (242px@320 → fixed in `3836f64` via `minWidth:0` + a
`--landing-pad` token; residual 14px@320 recorded). Plan
`docs/infrastructure/GUI_INTERACTION_TESTBED_PLAN.md`; verdict
`data/eval_results/gui_testbed_2026-07-17.json`.

Out of scope: live `Retry-After` presence depends on the WI-11 overload path
(env-gated OFF); the GUI codes against the header and is correct regardless.

### Search queue — sequential mode (2026-08-05, portable_socsci)

For the portable USB bundle (cold searches page the mmap off USB, measured
~112 s cold), the Search screen gains an optional one-at-a-time search queue
(download-manager pattern; UX research:
`docs/infrastructure/PORTABLE_SOCSCI_WINDOWS_BUNDLE.md` §8). Submits enqueue;
one client-side worker runs the head item — serial by design (parallel
random reads thrash the mmap). Items show Queued·N-ahead / Searching /
N-results / Failed; done items clickable; best-effort desktop Notification
on completion; 429s back off and requeue; remove + clear-completed. Non-queue
behavior unchanged when off. Gate: **`SFU_SEQUENTIAL_MODE`** (set by the
bundle's START.bat from `sfu_runtime.cfg`); the server advertises
`sequential` on `/health`; user override in Settings → Interface
(`searchQueueAuto` + `searchQueue`; NOT integrity-floor). **IMPLEMENTED
2026-08-05, jsdom-verified 24/24**; real-USB latency benefit UNMEASURED on
Windows.

### Draft → final search stream — lever #2 (2026-09-25)

`POST /api/search_stream` (gate **`SFU_SEARCH_DRAFT_STREAM`**, default OFF,
forced off under `SFU_SEQUENTIAL_MODE`; advertised as `search_draft_stream`
on `/health`) streams an SSE `draft` event with the thin-client BM25F leg's
hydrated top-k (`preliminary: true`) and then a `final` event byte-identical
to `POST /api/search` for the same arguments (same cache read-through; a cache hit
emits `final` only). The GUI renders the draft with a "Preliminary" label and
swaps to the final list only when the user is idle, pinning a hovered card;
`/api/search` stays the default path. **IMPLEMENTED 2026-09-25, EFFICACY
UNMEASURED** — gated on measurement (a) of
`docs/SPECULATIVE_RETRIEVAL_UPGRADES.md` (overlap@10 of BM25F versus the post-CE
top-10 ≥ ~0.7); bars: time-to-first-card, time-to-final ±5% versus gate-off,
final byte-parity versus cache-off, reshuffle rate. **Measurement (a) landed
2026-09-25: overlap@10 = 0.433 mean (9.2% of topics ≥ 0.7), below the bar, so
the gate stays OFF and lever #2 is DEFERRED until a better draft leg exists
(`SPECULATIVE_RETRIEVAL_UPGRADES.md` §3b, §4 row 2).** Invariants:
`docs/CODE_INVARIANTS.md` §"Draft → final search stream". Verification 2026-09-25: `source/tests/test_search_draft_stream.py`
13/13; `node scripts/verify_web_jsdom.mjs` 74/74 (was 42; 32 draft-stream
checks added).

## Hot/cold profile structure (fully implemented)

- Subject sections: `social_sciences`, `med_bio`, `phys_eng`, `cs_math`,
  `other` — priority-ordered disjoint title+abstract vocabulary classifier
  (`lib/thinclient/sections.py`, ported from the measured eval).
- **Era sub-sections (primary fast axis):** each subject is built as
  `<base>__recent` / `<base>__archive` (boundary publication_year 2010,
  routed at build time; the export spool stays base-keyed). Year-filtered
  queries prune the contradicting era (`retriever._era_skip`).
- Personas are era-qualified: subject personas default to the recent era
  (`political_science` → `social_sciences__recent`) with `*_historical`
  variants, plus era-wide `contemporary`/`historical` and the testbed
  `all_hot`. Hot sections stay live with a zstd-dictionary abstract sidecar;
  cold sections are packed.
- **Packing operates on built artifacts** (`packer.py`, tar+zstd-19 LDM):
  unpack = pure decompression at disk speed with SHA-256 parity — replacing
  the old rebuild-from-JSONL flow (2,016 docs/s, ~2.4 h/section at 150M).
  Archives are kept after unpack, so re-packing an unwritten section is just
  deleting the live dir.
- Abstract policy (measured: extern_display is ranking-lossless): hot =
  local sidecar; cold = OpenAlex API mget before rerank; never title-only
  rerank. **2026-09-25:** on the serving path the cold mget goes through the
  shared `OpenAlexClient` (`fetch_abstracts_by_ids`, injected by `lib.tools`)
  with the configured API key, daily budget tracker (≤ 2 calls per served
  cache miss), circuit breaker and no retry sleep; a blocked/429 fetch means
  "no abstract", never an error. Previously it was a direct keyless
  `requests.get` that 429'd on every query on this network. Contract:
  `docs/EXTERNAL_API_CONTRACT.md`. Sidecar format v3: script-bucketed clustered 32 KB blocks, zstd-19
  with per-script trained dicts (projected 64.7→52.9 GB at 150M from the
  2026-06-11 20k sample, *est.*; **measured 2026-10-19 on every block of the
  served store: 475.7 B/doc, dictionaries −17.6 % vs none, 71.6 vs 86.8 GB at
  150M *est.*, parity 1,062,917/1,062,917 —
  `docs/STORAGE_BUDGET_150M.md` §6**); v1/v2 stores are refused since
  2026-10-11 (only v3 and v3-flat are served).
- `meta.sqlite` is v2: W-ids as INTEGER PRIMARY KEY with a TEXT overflow
  table (measured ~10 GB at 150M versus 24 GB v1 — but see the as-built 24.9 GB
  note below); the retriever auto-detects v1/v2.
- CLI: `python -m lib.thinclient.packer {pack|unpack|repack|status} <root> [section]`.

## Index layout

```
data/thinclient_index/
  manifest.json        provenance, persona, section states, checksums
  build_status.json    resumable build checkpoint (phase/section granularity)
  build_progress_<base>.json   per-spool-slice BUILD checkpoint (transient)
  meta.sqlite          v2: int-PK id -> title/doi/year/type/is_oa/section
  sections/<base>__<era>/   tantivy/  (splade_NNN.bmp + vocab.zst no longer emitted, 2026-10-11)
                            + abstracts.sqlite (hot)
                            + abstracts.sqlite.flat/ (hot, OPTIONAL — N5)
  packed/<base>__<era>.tar.zst
  dense/               b1.usearch + rescore_int8.npy + ids.json  (OPTIONAL —
                       SFU_DENSE_LEG gates the leg; DENSE_PARTITION_AND_ABLATION.md)
    delta.sqlite       warm-cache delta — lives INSIDE dense/ (corrected
                       2026-08-17); runtime state, never shipped.
```

### Abstract flat block store (N5) — timeline and current state

The flat sidecar (`abstracts.sqlite.flat/`) holds the same compressed block
payloads as a v3 `abstracts.sqlite` in a flat `blocks.bin` + three arrays,
read by `pread` instead of `SELECT z FROM blocks`. Dicts, block layout, and
(originally) the `docs` locator are unchanged — doc 17 §11 measured payload
as 83% of the store and moving the locator to tantivy as a 27–54×
regression. `AbstractStore` picks the sidecar up automatically on directory
existence (no environment gate); deleting the directory reverts the section; a
half-built sidecar falls back to the v3 blocks table losslessly.

Dated findings (full detail: doc `seismic_150m_testbed/18` §§9–23):

- **2026-08-02 (§9, `n5_flat_blocks_20260802_0741.json`):** fetch() k=10/50/
  100 = 18.71→6.64 / 80.06→27.91 / 159.36→55.22 ms (**2.82–2.89×**);
  byte-parity PASS on 20,000 ids; build 1,062,917 blocks → 11.13 GB +
  19.7 MB index in 878 s. ⚠ Later shown to be a **9p number** — on local
  disk the identical payload move is 1.21×.
- **2026-08-03 (§16):** the locator, not the payload, held the remaining
  time — four flat ordinal arrays (421 MB, 18.00 B/doc) gave a further
  4.55×: p50 5.09→0.92 ms (5.53×), mean 2.09×, p90 1.19× (tail =
  decompress misses). Space story: blocks 11.15 GB + locator 0.42 GB =
  **11.57 GB replaces the 13.47 GB file (−1.90 GB), and `abstracts.sqlite`
  becomes deletable**.
- **2026-08-03 (§17): the locator reader SHIPS** — `AbstractLocator` +
  fail-closed identity gate (`flat_store_id`; a locator over the wrong
  `blocks.bin` raises rather than serving a plausible wrong abstract);
  `fetch()` routes automatically. Measured: parity PASS 20,000 ids, 1.18×
  p50 / 1.16× p90 (`c9_locator_reader_20260803_2308`). The §16 5.53× was a
  cold-cache artifact — warm, the locator saves ~0.24 ms/fetch; the durable
  win is **−1.90 GB and a database removed, not speed**.
- **2026-08-03 (§18): `abstracts.sqlite` is DELETABLE** — dicts rehomed into
  the sidecar (`dump_dict_sidecar`, identity-bound); `AbstractStore` gained
  a SQLite-free mode (`_db is None`). Measured
  (`c10_sqlite_free_20260803_2329`): parity PASS with the file gone, 1.19×
  p50; replacement 11.55 GB ⇒ deletion saves −1.92 GB (abstract DB 4 → 3).
- **2026-08-17: the build path SHIPS** — `scripts/build_flat_blocks.py`
  (`plan`/`build`/`verify`), resumable per stage, staged-directory publish
  only after a four-arm byte-parity gate (v3 oracle versus flat+`docs` versus
  flat+locator versus SQLite-free) + a `pread`-vs-`z`-BLOB block check.
  **Production build RUN 2026-08-17 — gate PASS, `social_sciences__recent`
  published and serving flat** (still the only section holding an
  `abstracts.sqlite`). Build measured: flat stage 823.9 s (1,062,917
  blocks), dicts rehomed (7), locator 132.0 s (23,398,073 rows, 0 non-W
  ids), gate ~3.6 min → **19 min 33 s wall**; independent `verify` 2 min
  49 s, PASS. Disk: **+11.57 GB** additive until the operator deletes the
  sqlite (**−1.90 GB net** if they do; exact bytes 11,573,203,382 total /
  1,897,229,898 saved). `sqlite_deletable: true` — deletion legal, NOT
  done. Coverage caveat: `ids_checked` 14,000 of nominal 20,000 (rowid-gap
  dedupe, §22). Results
  `data/eval_results/flat_build_social_sciences__recent_20260817_0118.json`
  + `flat_verify_…_0121.json`. Synthetic-scale tests:
  `scripts/tests/test_flat_block_builder.py` (45 pass; includes the
  torn-`.npy` reader hardening — `np.load` raises
  ValueError/EOFError, not just OSError, on torn files; `_open_flat` now
  catches all three, measured 2026-08-17).
- **2026-08-17: inline emission** — `build_thinclient_index.py
  --flat-sidecar` runs the same `build_section` between BUILD and PACK,
  fail-closed, checkpointed (`flat_sections`/`flat_info`), skipped on
  resume; **off by default**. IMPLEMENTED, synthetic-only (the production
  sidecar came from the standalone script).
- **2026-08-17 (§23): serving efficacy MEASURED** against the published
  directory, real ranked result sets, 300 interleaved trials/arm,
  `sqlite_ctrl` noise floor
  (`scripts/seismic_testbed/j1_flat_sidecar_serving_ab.py`,
  `data/eval_results/j1_flat_serving_*_20260817.json`):

  | where | state | sqlite p50 | flat p50 | multiple |
  |---|---|---|---|---|
  | local disk (droplet target) | warm | 1.726 ms | 1.581 ms | **1.091×** |
  | local disk | cold | 27.6–31.7 ms | 11.0–12.3 ms | **2.546×** |
  | local disk | first touch after eviction | 1.907 ms | 2.075 ms | **0.919× — slower** |
  | this container (9p) | warm | 45.679 ms | 15.886 ms | 2.876× *(9p artifact)* |

  Byte-parity PASS everywhere. §16/§17's multiples do not reproduce on the
  serving path's own inputs; the durable win remains −1.90 GB + a database
  removed.
- **2026-08-18: first-touch mitigation** — `SFU_ABSTRACTS_PREFAULT=1`
  (`AbstractLocator.prefault()`: MADV_WILLNEED + strided read of all four
  `loc_*.npy` columns at store open; 421.2 MB in 203 ms from evicted,
  parity PASS; residency-only, fail-open, stats on
  `AbstractStore.prefault_stats`). **But the 0.919× regression did NOT
  reproduce under symmetric eviction** — gate-OFF already reads 1.00–1.10×
  with both arms evicted; the 2026-08-17 0.919× row was a run-ordering cache
  artifact. **Verdict: default stays OFF** — correct, cheap
  belt-and-suspenders for long-lived processes, no measured query-time
  benefit. Results
  `j1_flat_serving_firsttouch_{off,prefault}_20260818.json`; tests
  `scripts/tests/test_abstract_locator.py` (39 pass).

Build/verify commands:

```bash
.venv/bin/python3 scripts/build_flat_blocks.py plan
.venv/bin/python3 scripts/build_flat_blocks.py build  --section social_sciences__recent
.venv/bin/python3 scripts/build_flat_blocks.py verify --section social_sciences__recent
# inline in a fresh build:
.venv/bin/python3 scripts/build_thinclient_index.py --persona political_science \
    --flat-sidecar [--flat-verify-ids 20000] [--flat-verify-blocks 500]
```

Script guarantees: staged publish (`.flat.building/` renamed only after the
gate — the reader attaches on directory existence, so this removes the
crash window); four-arm parity gate through the shipped `AbstractStore` via
symlink views; resumable per stage (stamp written last + length check);
additive only (source read-only, refuses to overwrite a published sidecar or
touch foreign files; revert = `rm -rf`); report carries `sqlite_deletable`
(true only when `skipped_non_wid == 0` AND dicts rehomed — deleting the
sqlite stays a separate explicit operator step).

## Migration (150M docs, kept)

`scripts/build_thinclient_index.py` streams the corpus out of the original
cluster's `openalex_works` (sliced scroll; `_source` carries the production
`sparse_field` weights — **no re-encoding**; since 2026-10-11 the export no
longer requests `sparse_field`, which only fed the removed BMP shards),
classifies sections, and builds
all artifacts checkpointed (export/build/pack/dense). Monthly rebuilds:
snapshot JSONL → `lib/thinclient/doc_encoder.py` (GPU TRT batch SPLADE
encoder) → same builder. Operational helpers (archived):
`scripts/archive/wait_and_resume_migration.sh`,
`scripts/archive/restart_at_build_phase.sh`.

**Build RAM (measured 2026-06-12):** the era split runs TWO builders per
section worker; `--build-workers 3` at the then-default
`--bmp-shard-docs 2_000_000` OOM-killed the 150M BUILD on the 31 GB host
(BrokenProcessPool ~1 min in; worker RSS ~10.5–11.3 GB each at 2 workers).
Code defaults stay `--build-workers 2` / 2M shard docs
(`BMP_CLUSTER_CHUNK_DOCS` 250k, `TANTIVY_WRITER_HEAP` 512 MB); the 150M run's
supervisor conf overrode to `--build-workers 3 --bmp-shard-docs 1_000_000` —
halving the shard buffer fit the third worker. Trade: ~2× BMP shard count →
more fan-out, mitigated by vocab-sidecar skip + era pruning
(retrieval-latency impact unmeasured at 150M). Under full 3-way load
(2026-06-13): ~6.2 GB/worker early, drifting +~0.35 GB/h (tantivy segment
churn) — pool uses `max_tasks_per_child=1`; per-worker throughput ~1,050
docs/s non-hot / ~375 docs/s hot (abstracts zstd-19 is the hot bottleneck)
versus ~1,400/s solo — the third worker nets ~+12%, not +50%.
*2026-10-11:* `--bmp-shard-docs` and the BMP chunk/shard constants were removed
with the BMP code path; the numbers above are the BMP-era record.

**WAL swap-thrash + fixes (2026-06-13):** a plain WAL commit only does a
PASSIVE checkpoint, so per-section `meta_*.sqlite-wal` files grew to ~11 GB
combined and drove the 31 GB host into swap (free 1.5 GB, one worker at
~54 KB/s in D state). Fix 1: `slice_checkpoint()` +
`AbstractStoreWriter.checkpoint()` issue `PRAGMA wal_checkpoint(TRUNCATE)`
per slice. Fix 2 (per-slice was insufficient — dominant sections have
~2–2.5 h slices; `other`/`social_sciences` reballooned to 5.8/5.3 GB
mid-slice): `SectionBuilder.add()` commits + TRUNCATEs every
`META_WAL_TRUNCATE_DOCS` docs (default 250k ≈ ~200 MB cap;
`SFU_META_WAL_TRUNCATE_DOCS` override). Safe because meta rows are
idempotent `INSERT OR REPLACE` and only the meta db is touched — the
atomic-slice resume model is unchanged. Both validated with
`scripts/archive/bmp_era/test_build_resume.py` (archived 2026-10-11; clean==chaos under repeated SIGKILL; mid-slice
truncates firing under chaos).

**Per-slice BUILD checkpointing (2026-06-12):** a silent whole-session kill
cost ~8 h when resume granularity was the whole section (10–15 h each). The
worker now checkpoints after every spool slice
(`build_progress_<base>.json`): meta + abstracts commit (both sidecars moved
journal_mode OFF → WAL so SIGKILL can't corrupt them), tantivy commit, BMP
shard rotation at the slice boundary (shards never span slices; resume
deletes shards ≥ `next_shard`). A crash costs at most one slice
(~10–25 min). Edge cases: tantivy double-commit window (first re-fed slice
probes its first doc id), dict-training buffers persisted as `pending_*`
rows, orphaned re-fed abstract blocks dropped at finish. Slice-boundary BMP
rotation is safe: minimum per-slice era is 18.6k docs, above the 5k tail
bar. Kill/resume parity: `scripts/archive/bmp_era/test_build_resume.py`
(archived 2026-10-11: 0 pytest tests, needs the missing `spool_backup/`).
*2026-10-11:* BMP shard rotation is gone; `slice_checkpoint()` returns only
`{"count": ...}` and a `next_shard` key in an older progress file is ignored.

**Process supervision (2026-06-12):** a second BUILD died silently ~17 min in
(no traceback, no OOM event; nohup/setsid detachment is fragile here) → the
migration ran under supervisord (`autorestart=unexpected` + checkpointed
phases). 2026-06-24: build long complete; conf archived to
`scripts/archive/migration-150m.supervisor.conf`; the steady-state Qdrant
serving unit was `scripts/archive/qdrant-serve.supervisor.conf`.

### BUILD COMPLETE — measured results (2026-06-16)

`phase: done` at **2026-06-16T03:00:21**; **150,413,098 docs**, 5 personas ×
2 eras = 10 sub-sections. Engines as built: tantivy 0.26 BM25F
(title^3/abstract, freq-only), bmp 0.2.6 (b256 clustered,
`splade_quant_scale` 70), usearch b1 + int8 rescore (32×).

As-built footprint — persona `political_science`, hot
`social_sciences__recent` live + 9 cold packed:

| Component | Size | Notes |
|---|---|---|
| packed cold (9 × tar.zst) | 45.0 GB | live 84.3 GB → 45.0 GB, aggregate **1.875×** |
| hot section live | 34.0 GB | incl. 26,322,924 abstracts (zstd-19 script dicts) |
| `meta.sqlite` | **24.9 GB** | exceeds the ~10 GB v2 estimate in `STORAGE_BUDGET_150M.md` §1 — corrected there, cause not diagnosed |
| dense leg | 0.36 GB | 600k vectors dim 384 (b1 118 MB + int8 230 MB + ids 9 MB = 0.357 GB measured 2026-08-17). OPTIONAL; **ABLATION VERDICT 2026-08-18: DROP from the demo payload** — Δ final nDCG@10 **−0.0077**, 95% CI [−0.0153, −0.0001] (significantly negative), Δ recall@50 −0.028, no coverage band positive; leg stays in code, ships in no payload (`DENSE_PARTITION_AND_ABLATION.md` §7) |
| **Serving total (disk)** | **≈104 GB** (97 GiB) | versus ≈95 GB estimate; the +9 GB is entirely `meta.sqlite` |

Per-section pack ratio ranged 1.86–2.01×, aggregate 1.875× — below the 2.10×
bsize-32 assumption, confirming the `STORAGE_BUDGET_150M.md` §1 note. Pack
phase ~86 min; dense leg 36 s. The 3-worker / 1M-shard-docs build reached
DONE without the OOM/swap-thrash recurring, so the bounded-WAL fix held at
150M. NOTE: the post-build meta-merge of `other` (54.9M docs) is a single
bulk `INSERT OR REPLACE` and produced a transient ~24 GB `meta.sqlite-wal`
that checkpoint-drained cleanly. `spool_backup/` (131 GB build intermediate)
was RECLAIMED — verified gone 2026-07-17; a subset re-export needs the
host-tier spool job (doc 16).

> **⚠ On-disk ≠ resident RAM (measured 2026-06-17, BMP era).** The 68.6 GB of
> BMP SPLADE shards were NOT mmap'd — `bmp.Searcher` (0.2.6, no mmap mode)
> deserializes each `*.bmp` into anonymous RAM at a measured **3.07×**
> on-disk size (probe: 569 MB shard → 1747 MB RSS; ratio holds 12 MB–569 MB).
> `_load()` builds all 192 shards eagerly ⇒ the full 150M SPLADE leg needed
> **~211 GB resident**. tantivy (29 GB), `meta.sqlite` (24 GB) and dense are
> genuinely mmap/paged (~0 resident) — the RAM wall was BMP alone.
> `retriever._load()` samples `MemAvailable` before each shard and aborts
> with a clear RuntimeError (`SFU_LOAD_MEM_FLOOR_GB`, default 1.5) instead of
> being SIGKILLed mid-construction. *(2026-10-11: guard removed with the BMP
> code path.)*

#### Why SPLADE served fine at 1M/15M but OOM'd at 150M (BMP era, resolved)

Scale meeting a known design property, not a regression: BMP always loaded
shards fully into RAM (~1 GB → ~3 GB at 1M — trivial; 150M was the first
full-corpus load). The thin client was designed as the **laptop-tier (~15M)**
OpenSearch replacement (tantivy BM25F 45 MB RSS versus a 2 GB JVM heap; sparse
always expected RAM-resident at ~9–13 GB laptop scale); 150M was always the
server tier. OpenSearch never hit this because Lucene serves SPLADE
`rank_features` from mmap'd postings with a bounded heap — BMP traded that
away, so at 150M the BMP sparse leg was a RAM regression versus the leg it
replaced, while tantivy/usearch kept the mmap property. The ~211 GB figure
itself was an eval artifact (full-corpus parity forces all 10 sections live;
designed serving keeps one persona hot) — but the ceiling was real: one hot
`__recent` section at 150M ≈ 13 GB disk → ~40 GB resident, over a 24 GB
host, and a query routed to a cold section triggers an on-demand
unpack→load spike. Hot/cold was a partial mitigation; the durable fix was a
mmap-backed sparse engine — first Qdrant on_disk, then SEISMIC (below).

#### Off-BMP migration → Qdrant on_disk sparse (gate PASSED 2026-06-19; historical — Qdrant became the rollback, leg removed 2026-10-12)

GPU-free migration: `spool_backup/` held the precomputed `sparse_field`, so
vectors were re-ingested, not re-encoded
(`scripts/archive/spike_qdrant_sparse.py build-spool-par`, 8 workers, gRPC,
`wait=True`; token space = bert-base-uncased vocab ids shared doc/query).
Per-worker fsync'd checkpoints + deterministic point IDs made replay
idempotent (commit 19bb44e). Spike signal: on_disk sparse RAM flat/sub-linear
(544 MB at rest @5M versus BMP ~7 GB).

- **30M gate — MEASURED 2026-06-19** (`splade_par30`, 30M docs, green):
  **1,441 MB resident at rest** (the thesis); warm search p50 ~66 ms / p95
  ~85 ms (cold first-touch p50 208 / p95 1333 ms = page-cache warm-up);
  ingest 4,234 docs/s end-to-end, 30M in 7,086 s, peak RSS 11.4 GB.
- **Quality parity — MEASURED 2026-06-19**
  (`eval_quant_fidelity.py`, `quant_fidelity_30mscan.json`): BMP's ×70 u8
  quantization versus Qdrant raw f32 on a 1,000,032-doc real pool — overlap@10
  0.987 / @50 0.988, Kendall-τ 0.972; head-to-head NDCG@10 on the 9
  judged-coverage queries **0.8681 versus 0.8681, Δ 0.0000** (engines tie
  exactly; not the 150M RRF system number). Structural backstop: Qdrant
  sparse is an exact dot product, BMP approximate ⇒ the swap is
  quality-neutral by construction and corpus-size-independent.
- **Serving wired 2026-06-19** (`SFU_SPLADE_BACKEND`; default `qdrant`
  2026-06-24 → `seismic` 2026-07-06): collection
  `SFU_SPLADE_QDRANT_COLLECTION` (default `splade_150m`) at
  `SFU_SPLADE_QDRANT_URL` (default `http://localhost:6333`); forces
  `skip_bmp` in `_load()` (reclaims the RAM; `skip_bmp` removed with the BMP
  leg 2026-10-11); degrades to the BM25F leg on
  any encode/Qdrant error. Validated on 30M: warm leg ~1–2 s
  encode-dominated (Qdrant search itself ~66 ms).
- **Query-encoder environment** (`SFU_SPLADE_MODEL_PATH`, 2026-06-19): a measured
  fp32-cold-load 104.6 s versus 6.1 s gap between `models/splade_onnx` and
  `models/splade_onnx_fp16` motivated pointing serving at the latter — but
  the 2026-07-09 correction found both directories byte-identical fp32 (md5
  `2c54704e…`), so the 17× was page-cache state or a since-overwritten
  export, not precision. Dynamic-int8 query-encoder quantization was gated
  and **KILLED 2026-07-09** (merged overlap@10 ≈0.79, doc
  `seismic_150m_testbed/08` §D,
  `d1_int8_query_encoder_20260709_0034.json`). **D2 (2026-07-09): the served
  encoder default is `models/splade_onnx_fused`** — offline ORT bert-fused
  export of the same fp32 weights (exact GELU): encode 1.11× p50, merged
  overlap@10 0.999 / @50 1.0, paired served e2e −5.6 ms p50; flipped in
  `lib/config.py` + retriever + seismic backend defaults;
  `SFU_SPLADE_MODEL_PATH` still overrides (`models/splade_onnx` = unfused
  fallback); the fused directory is untracked — regenerate with
  `scripts/seismic_testbed/d2_ort_fusion_matrix.py`. Thread pinning and
  spin-off refuted; FastGelu-approx passed with zero margin, NOT promoted.
- **150M ingest COMPLETE 2026-06-20 22:46** (`splade_150m`): 150,413,098
  points, indexed 150,412,961; resumed across two manual pauses + watchdog
  restarts with no re-ingest. Incidents, all diagnosed:
  - **Optimizer OOM (fixed 2026-06-21):** 205 GB / 36×~5.4 GB segments on a
    23 GB-RAM box — big merges OOM'd (`os error 12`), driving the server
    red and stalling `wait=True` upserts. Fix (no infra change):
    `max_optimization_threads=1` + `max_segment_size=5_000_000` KB → zero
    OOM since, stable 36 segments.
  - **⚠ 150M search latency is RAM-bound (measured 2026-06-21):** red-state
    p50 1004.8 / p95 5535.9 ms; post-fix warm p50 **545.8–861.5** / p95
    3386–4510 ms, RSS ~17 GB. **8–15× the 30M gate's 66 ms and it does not
    extrapolate down** — 205 GB on_disk versus 23 GB RAM = ~7% page-cacheable;
    hitting ~66 ms at 150M needs materially more RAM or a smaller index.
  - **Server OOM crash (2026-06-21):** kernel OOM-killed Qdrant (external
    SIGKILL, no panic line; 16 GB swap 100% full). Root cause measured on
    the live pid: `on_disk: true` offloads only posting lists — per-point
    bookkeeping stays anonymous RAM, **RssAnon 6.55 GB ≈ 43 B/point at
    150.4M**, climbing ~17 GB under load; structural, configuration cannot remove
    it. Durable fix: serve-only supervisord conf with `autorestart=true`
    (the optimizer fix persisted in collection configuration and survived).
  - **Worker stalls:** `wait=True` upserts with no retry died past the
    600 s gRPC timeout when the server went red (~every 2 h under
    contention). Backstop: `scripts/archive/bmp_ingest_watchdog.sh`
    (IMPLEMENTED 2026-06-20, one heal observed; guarded the run to
    completion — stalls clustered early; the static `slices[w::W]` split
    left the last ~30% on 3–4 workers, net rate below the gate's 4,234
    docs/s; next-run fix: work-stealing). Root-cause fix
    `_upsert_wait_retry` (2026-06-24, Workstream A2): retries the same
    batch with exponential backoff (10→120 s cap, 20 attempts) —
    IMPLEMENTED, UNMEASURED at ingest scale (the 150M ingest predates it).
- **BMP decommission — COMPLETE 2026-06-25 (Workstream D):** the 68.66 GB of
  150M `.bmp` artifacts deleted (`data/thinclient_index` 298→230 GB); BMP
  code + builder stayed behind `SFU_SPLADE_BACKEND=bmp` for small-tier
  rebuilds until 2026-10-11 (removed; code kept by the owner); `import bmp` deferred to the BMP branch (commit 0b7ca48) so a
  qdrant-only deploy needs no pisa. Authorizing gate: B2 RRF quality
  (qdrant 0.5378/0.560 versus BMP 0.5368/0.561, |Δ|<0.001; still beats
  OpenSearch +0.111) + B1 parity —
  `docs/archive/bmp_decommission_plan/VALIDATION_REPORT.md`. Post-deletion smoke:
  qdrant default serves end-to-end; Qdrant-stopped degrades SPLADE → BM25F.

#### SEISMIC served leg — PROMOTED 2026-06-29

The federated backend moved from the testbed into the served package
(`source/lib/thinclient/sharded_seismic_backend.py`); `_seismic_backend()`
resolution order:

1. **`SFU_SEISMIC_SHARD_MANIFEST`** set → federated backend over all K
   shards, `load_mode=SFU_SEISMIC_LOAD_MODE` (default **`mmap`** — Path C,
   anon floor ~0; what makes 150M servable on a 32 GB host). **The mmap gate
   is hard:** a missing converted `.mmap/` directory raises a clean RuntimeError,
   NEVER a silent fallback to stock `SeismicIndex.load()` (Path-A owned
   anon, ~137 GB @150M — the floor G3 killed). `SFU_SEISMIC_LOAD_MODE=stock`
   only for persona-scale bit-for-bit reproducibility.
2. ~~else `SFU_SEISMIC_INDEX` → single `SeismicBackend` (Path-A testbed)~~ — branch
   removed 2026-10-11 (the persona harness `scripts/seismic_testbed/g6_rrf_parity.py`
   builds `SeismicBackend` itself).
3. else a clean RuntimeError naming `SFU_SEISMIC_SHARD_MANIFEST`.

**Two serving classes** (split 2026-06-30), picked by
`SFU_SEISMIC_FEDERATION` (environment always overrides; FS-aware default since
2026-07-18):

- **`ParallelSeismicBackend`** — ThreadPoolExecutor fan-out, never releases
  pages. G8g 2026-07-08: persistent executor (built once) measured −2.3 ms
  traverse p50, bit-identical; served warm e2e p50 53.8 ms = encode 19.5 +
  traverse 33.7 (`g8g_ab_perquery_vs_persistent_20260708.json`).
- **`SequentialSeismicBackend`** — shards searched one at a time; after each,
  `MmapSeismicIndex.release_pages()` (`MADV_DONTNEED`) hard-releases its
  slabs so peak resident ≈ one shard. Post-release re-fault bit-identical
  (`test_seismic_sequential.py`). **Efficacy MEASURED 2026-07-16 (WI-1)**:
  warm p50 5.29× parallel (248 versus 47 ms, Σ-of-shards), peak RssFile 0.023×
  (0.27 versus 11.74 GB), T1 0/2000 — its value is the RAM floor, not warm
  speed (`docs/seismic_sequential_serving/04_BENCHMARKING.md`).

`ShardedSeismicBackend` remains a thin `__new__` selector for the testbed
CLI; the retriever instantiates the concrete class. Federated over-fetch
knobs: `SFU_SEISMIC_K_PRIME` (default max(2×k, 100) — flipped from 4×k
2026-07-08 after G8f: merged overlap@10 0.999 / @50 0.994 at n=100, traverse
1.47× faster, `g8f_shardmerge_profile_kprime_20260708.json`),
`SFU_SEISMIC_QUERY_CUT`, `SFU_SEISMIC_HEAP_FACTOR` (default 0.8).

**Disk-streaming pin tier (2026-07-14; residency-only, all default OFF =
byte-identical kill-switch; doc `disk_streaming_research/03` §5):**

- `SFU_SEISMIC_PIN_BUDGET_GB` — mlock the F2 hot-set sidecar up to
  min(dial, MemAvailable − 1.5 GB floor − 1.0 GB headroom). T1 20/20
  bit-identical. **REFUTED as a thrash rescue 2026-07-14 — keep 0**: R1
  pin-ON neutral at 8 GB, ~35% WORSE at 6 GB (steady p50 4.9→6.6 s,
  per-fault +26%; `r1_cap{8,6}g_pin16_20260714.json`) — touch coverage ≠
  fault mass and locked bytes starve the streaming remainder. Untested
  remaining use-case: external cache competitors.
- `SFU_SEISMIC_MLOCK_FLOOR=1` — **RESCOPED 2026-08-17**: locks only the
  posting-list *navigation* floor (block_offsets + Elias-Fano offsets +
  DArray inventories), budget `SFU_SEISMIC_MLOCK_FLOOR_MB` (TOTAL MB, default
  160 = 20 MB/shard × 8), capped by MemAvailable − 1.0 GB and ≤2048 locked
  ranges/shard (VMA-split cap). Measured 2026-08-17: shard0 19,980,288 B in
  929 ranges, 1.6 s (`f4_floor_mlock_rescope_20260817.json`); that shard's
  full navigation floor is 153.1 MB of the 1,159.2 MB slab (13.2%); 671×
  less RAM than the 2026-07-14 whole-slab pin (13.4 GB), which now requires
  `=full` (measurement reproduction only). Parity 5/5; **latency A/B
  2026-08-17** (8 shards, hybrid, 100 q × 3 passes): warm p50 62.17→63.35 ms
  = 1.019× (clears the ≤1.05× bar), p95/mean nominally better ON, parity
  10/10 (`f4_floor_ab_verdict_20260817.json`). 8-shard residency smoke:
  159,907,840 B locked in 7.65 s warm — but **cold-cache load 2.8 s →
  91.4 s** (the mlock walk faults 160 MB off 9p). **Default stays 0** — the
  third pre-registered bar (zero navigation re-faults under pressure) is NOT
  MEASURED (no pressure pass in `serve_footprint_bench`, no RAM cap here):
  proven free and bit-identical, not useful. Caveat: the old "~20 MB true
  floor (Q9's ~5,000 pages)" was a unit error — 5,093 was a major-fault
  count carrying ~1.27 GB of readahead (doc 10 §7.3).
- `SFU_SEISMIC_PREFLOOR_HOTSET=1` — prefault (NOT mlock) the hot extents at
  load; the cold-start lever: **cold p95 4.66 s → 1.67 s (~2.8×)**, cold p50
  ~1.5×, warm unchanged (paired same-binary A/B 2026-07-14,
  `f6_prefault_hotset_20260714.json` versus `f6_gateoff_baseline_20260714.json`).
  The earlier "cold p95 → 30 ms" claim was **INVALID** — every bench query
  had failed and scored 0 ms; five defects fixed in commit 2203d9b.

**RECOMMENDED SERVING CONFIGURATION (2026-07-14, all values measured):** E8
dv-v2 manifest + `mmap` + hybrid federation +
**`SFU_SEISMIC_PREFLOOR_HOTSET=1`** (the one residency lever ON) +
`SFU_SEISMIC_PIN_BUDGET_GB=0` + `SFU_SEISMIC_MLOCK_FLOOR=0` +
k′/query_cut/heap_factor defaults + post-deploy warmup replay (~10 common
queries). RAM sizing (R1 ladder, `r1_cap*_20260714.json`; working set
≈15.5 GB, workload-defined): **24 GB comfortable** (steady 18–19 ms
traversal, 0 faults) · 16 GB acceptable minimum · ≤8 GB DO NOT SHIP (2–5
s/query permanent thrash; pinning made it worse).

**Kernel LRU sensitivity at near-critical RAM (Tier-1d verdict 2026-09-05):**
the convergence artifact's arm asymmetry is a **general kernel behavior, not
a property of this index** — reproduced index-independently in a synthetic
hot-set-skew cell (frozen pre-registered bars, both fresh-seed replicates):
under a cap in the band `hot-set < cap < working set`, classic LRU converges
(refault-activation stabilises the hot set, hot residency ~73%→90%) while
MGLRU pins at a **1.443×** higher steady major-fault floor (hot residency
flat at 75%), with the effect specific to that band (ratio 1.000 uncapped
control, 1.038 at a loose cap). On the real stack the same mechanism is far
larger (MGLRU sustained thrash versus ~21 ms classic at equal 28 GB caps,
Tier-2/3 2026-09-01). Characterization (recorded-only, 2026-09-06): the
asymmetry is a **peaked curve** in hot-set size — it needs a hot set big
enough to be contested, small enough to fit (ratio collapses into noise when
the hot set exceeds the cap); MGLRU's own anti-thrash knob `min_ttl_ms`
(1000/4000 ms) does **not** rescue it at the divergence rung (floors
483,014/483,022 versus 482,884 baseline, residency pin untouched) — the
divergence is not config-rescuable; and with readahead on under a binding
cap, per-pass wall is amplified **>30×** before any arm asymmetry enters
(the first measured factor of the 1.44×→~220× real-stack gap). The line
closed SETTLED 2026-09-06: hot-set **layout is a non-factor** (clustered
floors replicate scattered to 0.03%, ratio 1.443 both), the synthetic
fixed-window inversion is **closed negative in every expressible form**
(even with the residue sort in-window and pressure-proportional, reclaim in
both arms victimizes the untouched residue exclusively — bit-identical
majflt trajectories across caps and arms), and fault-around under a binding
cap shed 8-for-8 across layouts/fracs/caps (thrash before measurement).
Operationally: near the 16 GB acceptable-minimum edge,
kernel LRU choice matters — prefer classic (`lru_gen` off) or size so the
hot set fits with headroom. Evidence:
`spike/convergence_repro/RESULTS.md` §23–25 (verdicts) + §26–31
(characterization) + §32 (2026-09-12 access-histogram probe: the real
index's skew is ≈`hotset:0.10:0.80` on forward pages, hot-80 3.21 GB,
hot set only 1.57× tighter than random placement — two replays
byte-identical) + `PREREGISTRATION_TIER1D.md`;
cells `data/eval_results/t1d_*_seed{2027,8128}_2026090{5,6}.json` +
`data/eval_results/_t1d_CHAR_report_2026090{5,6}.md`. Yields e2e ~54 ms warm
(quiet host; ~120 ms co-loaded) / ~430 ms cold p50 / ~1.7 s cold p95 at full
150M quality; quality invariant across every residency setting (parity 10/10
+ 40/40×3 stressed). Hot-set sidecars: `<shard>.mmap/hotset_*.json` from
`scripts/seismic_testbed/f1_hotset_generator.py`. Same `[(oaid, score)]`
return shape as the Qdrant/BMP legs. *(Manifest/default history: /tmp-era
manifest → persistent `data/seismic_150m/index/plan01/` 2026-07-01 →
dotvbyte default 2026-07-06 → E5 2026-07-09 → E8 dv-v2 2026-07-14; see the
SPLADE leg section above.)*

**G8 served-150M results (2026-06-30):**

- **RAM (decisive):** TRUE anon floor (RssAnon + VmSwap) **1.1 GB versus Qdrant
  16.99 GB** (~15×; index anon ≈0.14 GB, zero swap).
- **Latency (clean verdict; the 2026-06-29 "76.7 s" was a swap artifact from
  co-loading Qdrant):** SEISMIC-only on a RAM-provisioned host (58 GB cap,
  VmSwap 0): warm p50 ~0.5–0.7 s at 150M (encode ~35 ms + traverse;
  fully-cached best ~82 ms). Flat-then-cliff under pressure (~650× cliff
  when page cache drops below the working set). Corpus scaling near-flat:
  18M→150M (8×) raises warm p50 only ~1.6×; RAM ~5 GB/shard.
- **Quality (Kimi-judged, mmap path; 2026-06-29 f16 build — status note
  2026-09-27: the served E8 dv-v2 leg is Kimi 0.9249 / Haiku 0.9426 on the
  parity-120, see §SPLADE leg "Quality"):** NDCG@10 0.944 / MRR@10 0.996 /
  P@10(≥2) 0.773 (120 SFU queries; Kimi ~0.27 stricter than Haiku — not
  comparable to Haiku baselines). **Cross-engine, one judge (2026-06-30):**
  headline SEISMIC 0.944 / Qdrant 0.9065 / OpenSearch 0.8772 are DIFFERENT
  query sets (query-set artifact, not an edge); the matched-paired test says
  TIE — SEISMIC−Qdrant on the 40 shared queries Δ=−0.002 ± 0.0035 (ns); on
  the 14 common to all three 0.9613 ≈ 0.9607 > 0.9489 (all ns). **Matched
  n=120 re-judge (same day, closes the small-n caveat):** SEISMIC leg
  0.9262 versus Qdrant 0.9065, paired Δ=+0.0197 (SEM 0.0051, 95% CI
  +0.0098..+0.0297 — first n=120 CI clearing zero, SEISMIC-favored) →
  **G6 re-scoped to paired-delta → PASS.** Results
  `rejudge_kimi_{qdrant_n120,opensearch_n40}_20260630_2041.json`,
  `rejudge_kimi_seismic_n120_20260630_2137.json`,
  `rejudge_kimi_crossengine_summary_20260630.json`.

Guard tests (2026-06-30, commit 3085122):
`scripts/tests/test_served_seismic_path.py` — happy-path federated mmap load
→ `[(oaid, score)]`; missing-`.mmap/` → RuntimeError, never silent Path-A;
leg failure → BM25F degrade.

### 150M parity history

> **STATUS 2026-08-17 — the RAM history above is BMP-era.** On SEISMIC the
> SPLADE leg is mmap-backed, so plain `record-tc` at 150M runs in one
> process (`MemAvailable` never below 51.5 GB on a 56 GB host); the
> section-shard-wave workaround is no longer needed. Still blocked: phase B
> (`record-os`) — the OpenSearch 150M baseline is decommissioned, so
> `run_parity_safe.sh` cannot complete end-to-end; run phases A + C
> directly.

**BMP-era OOM-safe method:** `scripts/run_parity_safe.sh` split the eval
into one-engine-per-process subcommands (`record-tc` → `record-os` →
`compare`) with page-cache drops, `MemAvailable` preflight, an in-loop
mem-floor guard (flush + clean exit before the OOM killer), and optional
`PAUSE_OS=1`. Still not enough at 150M on BMP (one engine ~211 GB; verified
2026-06-17: `record-tc` SIGKILLed mid-`_load()` at ~32 GB committed). The
wave eval `scripts/archive/bmp_era/eval_parity_section_waves.py` sidestepped it: BM25F via
`SFU_SKIP_BMP=1` (gate removed 2026-10-11; mmap, ~0 resident), SPLADE recorded shard-by-shard in
fresh processes, merged offline — exact by construction (validated
byte-for-byte versus direct `record-tc` on `thinclient_1m`).

- **2026-06-18 (BMP, first full-corpus parity):** 40 diverse queries,
  LLM-judged; tc via 27 waves (8 GB budget, ~43 min, min RAM 15.4 GB, no
  OOM). **Common judged set (34 q): thin-client RRF NDCG@10 0.561 versus
  OpenSearch 0.449 (Δ +0.112; tc wins 29/34).** Overlap@50 versus OS: bm25f
  0.532, splade 0.399, rrf 0.476 (different analyzers; final RRF higher).
  Latency not comparable across runs. Records
  `thinclient_parity_waves_150m.json`, `parity_record_tc_waves_150m.json`,
  `parity_record_os_20260618_0028.json`. Caveat: judge-cache-limited (34/40
  scored).
- **B2 2026-06-25 (qdrant backend):** same queries/corpus/judge cache/RRF
  k=60 — tc-qdrant RRF NDCG@10 **0.5378** (39 judged) / **0.560**
  (34-common) versus BMP 0.5368 / 0.561 → |Δ|<0.001 on both:
  RRF-indistinguishable; OS win preserved (+0.111, 29/34). Records
  `thinclient_parity_qdrant_20260625_0001.json` + tc record. Unblocked the
  BMP decommission.
- **A1 2026-08-17 (SEISMIC E8 dv-v2 — the CURRENTLY SERVED configuration):** first
  end-to-end run against the actually-serving configuration (backend default
  seismic, e5_v2 manifest, mmap, parallel auto-selected,
  `SFU_DENSE_WARMCACHE=0`; corpus 150,413,098):

  | Backend | NDCG@10 | judged q | paired Δ versus seismic (n=38, 10k bootstrap) |
  |---|---|---|---|
  | **SEISMIC E8 dv-v2 (served)** | **0.5369** | 38 | — |
  | qdrant (2026-06-25) | 0.5378 | 39 | −0.0076, CI [−0.0189, +0.0041] |
  | BMP (2026-06-18) | 0.5368 | 39 | −0.0064, CI [−0.0198, +0.0067] |

  **Verdict: quality-INDISTINGUISHABLE from both validated backends**
  (neither CI clears zero) — the SEISMIC promotion + E5/E8 work cost no
  measurable end-to-end RRF quality. Per-leg parity@50: bm25f **1.0000 versus
  both** (tantivy bit-stable — harness+index identity check); splade 0.8855
  versus qdrant / 0.8775 versus BMP (SEISMIC is approximate where qdrant/BMP are
  exact; qdrant-vs-BMP = 0.974); rrf 0.951 / 0.9485. Latency (warm, q2–40):
  splade p50 247.9 ms / p95 543.4 ms with shards staged to local overlay;
  **bm25f p50 3037.6 ms — tantivy still on 9p is now the dominant cost** (the
  remaining lever is storage locality on the lexical leg). Cold first query
  76.9 s (splade) / 5.4 s (bm25f) = the dev-container mmap artifact,
  excluded. Shard staging: 41.4 GB in 508.5 s. Still UNMEASURED: overlap versus
  the OpenSearch baseline (cluster decommissioned — phase B skipped;
  `overlap_vs_baseline@50` null; the 2026-06-18 "+0.112 versus OS" is not
  re-confirmed by this run). NDCG is judge-cache-limited (no live judge;
  mean 5.33/10 top-10 docs graded — absolute 0.5369 is a floor; coverage
  balanced across backends, so the paired comparison is unconfounded).
  Results `thinclient_parity_seismic_e8dv2_20260817.json` +
  `parity_record_tc_seismic_e8dv2_20260817.json`.

Base harness: IMPLEMENTED 2026-06-17, smoke-tested on `thinclient_1m`.
Permanent suite: `scripts/tests/test_thinclient_stack.py` (meta v1/v2, era
routing/pruning, abstracts v1/v2/v3, dense cache, metrics/reload, MCP index
tools). Storage research: `LEXICAL_STORAGE_RESEARCH.md`,
`STORAGE_BUDGET_150M.md`.

## Removed from this container

Training (SPLADE finetune, embedding/CE/LambdaMART trainers, miners,
generators), the OpenSearch indexing pipeline (splade_indexer,
opensearch_sync, reindex shells, watchdogs), cloud GPU offload,
docker/opensearch templates, the devcontainer OpenSearch service+volume,
training data and superseded checkpoints (embed v2/v3, sfu-splade-v1).
Kept: all eval/benchmark harnesses, dense ANN code + artifacts, snapshot
downloader + 304-part snapshot, serving path, query-side encoders.

Host-side cleanup after container recreate:
`docker rm -f claudebox-sfu-library-thinclient-opensearch &&
docker volume rm claudebox-sfu-library-thinclient-opensearch`
