# Query-Driven Dense Warm Cache — research + design (2026-06-11)

**Status:** ACTIVE — v1 shipped; all four success metrics MEASURED 2026-09-25.

The "index that builds itself from what users request" line of research, re-traced
and turned into the v1 implementation in `src/lib/thinclient/dense_cache.py`.

## Where the idea comes from

**In-repo:** `docs/LOCALIZED_DEPLOYMENT_PLAN.md` §5 "Dynamic warm-cache" (design,
previously unimplemented): a read-through, usage-driven local index that caches
exactly what the user actually searches; §7 cites Frieder et al., *Caching
Historical Embeddings in Conversational Search* (arXiv 2211.14155, ACM TWEB 2023
— up to 75% hit rate from temporal locality). §8 decision #6 deferred wiring
dense into the warm-cache write path.

**Literature:** the classic lineage is **database cracking / adaptive indexing**
(Idreos et al., CIDR 2007; EDBT 2012; VLDB 2012) — indexes built incrementally as
a byproduct of query processing. Ported to vector search:

- **CrackIVF** (PVLDB 18, 2025, arXiv 2503.01823): answer with near-brute-force
  immediately, build IVF partitions progressively from the query distribution;
  10–1000× faster index initialization.
- **Quake** (arXiv 2506.03437): workload-adaptive partition maintenance.
- Maintenance-side: **FreshDiskANN** (two-tier fresh/static + background merge),
  **SPFresh** (SOSP 2023, in-place LIRE rebalancing), LSM-VEC.
- Risk literature: HNSW recall depends on insertion order — up to ~12.8 pp swing,
  query-correlated insert order is the bad case (arXiv 2405.17813).

## Verified facts (this container, usearch 2.25.3)

- usearch b1 incremental `add()` works on a mutable index; concurrent add+search
  from multiple threads: zero errors. `view=True` (how the serving seed is
  loaded) is **immutable**; duplicate keys **raise** — dedup is mandatory.
- CPU dense encode with `models/sfu-academic-embed-v5`: ~87 docs/s (batch 32).
- Bulk GPU encode of 150M ≈ 13.5 h on the RTX 4070 + ~84 GB artifacts; the warm
  cache costs ~0.6–1.7 s background CPU per query and ~0.5 GB per 1M cached docs,
  and converges to the *user's active domain* rather than the full corpus —
  it is the automatic answer to "which subset to ship".

## v1 design (implemented)

Two-tier delta, FreshDiskANN-style, with CrackIVF's answer-first philosophy:

- **Seed** = the existing static `dense/` artifacts (immutable mmap view +
  int8 memmap), untouched.
- **Delta** = `dense/delta.sqlite` (sole durability point: id, key, int8 vector,
  doc metadata) + in-RAM packed binary codes searched by **brute-force Hamming**
  (popcount LUT) + exact int8 rescore. Brute force sidesteps HNSW insert-order
  degradation entirely at delta scale (*"sub-ms below ~200k docs" was an
  estimate and is WRONG — measured 2026-09-25: 1.4 ms at 10k, 12.4 ms at 100k,
  69.9 ms at 500k rows; "Deferred to v2" item 2*); scores are
  corpus-independent dot products, so seed and delta merge exactly by score.
- **Ingest**: every hydrated local result (BM25F/SPLADE/dense legs) is enqueued
  fire-and-forget; a single background worker dedups (seed ids + delta ids),
  CPU-encodes title+abstract in batches of 32, commits to SQLite, then appends
  to the RAM arrays. Bounded queue (drop-newest on overflow), hard doc cap.
- **Hydration**: delta rows carry their own title/doi/year/type/is_oa, so warm
  docs hydrate and post-filter even when absent from `meta.sqlite`.
- Gated by `SFU_DENSE_WARMCACHE` (default on; `0` disables the cache only).
  **Since 2026-08-18 the whole dense leg is DEFAULT OFF** (`SFU_DENSE_LEG`,
  literal `1` enables — ablation DROP verdict, `DENSE_PARTITION_AND_ABLATION.md`),
  so the warm cache is inert unless the leg is explicitly enabled.

### Deferred to v2 — three of four shipped 2026-09-25

All three are **gated and inert by default**; the dense leg itself is still OFF
(`SFU_DENSE_LEG`, ablation DROP verdict), so none of this is on the served
path. Gate semantics: `ENV_GATES.md`. Code constraints: `CODE_INVARIANTS.md`.
Regression suite for all three: `scripts/tests/test_dense_cache_v2.py`
(9 tests, synthetic roots only — nothing here reads `data/thinclient_index`).

#### 1. `merge_dense_delta(index_root)` — IMPLEMENTED; CORRECTNESS MEASURED, SERVING EFFICACY UNMEASURED

`src/lib/thinclient/dense_delta_merge.py` (CLI: `PYTHONPATH=src
.venv/bin/python3 -m lib.thinclient.dense_delta_merge <index_root>`, verified
2026-09-25). Bulk-rebuilds the three seed
artifacts from seed ∪ delta and truncates `delta.sqlite`:

- **Bulk rebuild, not incremental `add()`** — that is the point: it erases the
  HNSW insert-order debt that query-correlated insertion creates (arXiv
  2405.17813, up to ~12.8 pp recall swing).
- **Fails closed before writing anything** on any disagreement between
  `ids.json` ↔ `rescore_int8.npy` ↔ `b1.usearch` ↔ `manifest.json`'s `dense`
  block (`DenseDeltaMergeError`).
- **Atomic per artifact**: `<name>.tmp-<pid>` → fsync → `os.replace`, in the
  order rescore → b1 → ids, with the dir fsynced after; the delta is truncated
  only once all three renames land, so a crash costs a re-merge, never a
  document. An `O_EXCL` `dense/.merge.lock` keeps two merges from interleaving.
- Seed bits are read back out of the seed index (`Index.get`), never
  re-derived from `rescore > 0` — int8 rounding drops the sign of |x| < 1/254.

**Measured 2026-09-25** — correctness on synthetic index roots built by
`builder.build_dense_leg` (30–400 seed rows, 5–60 delta rows), 6 merge tests in
`scripts/tests/test_dense_cache_v2.py`: the seed prefix of `ids.json` and
`rescore_int8.npy` survives byte-for-byte; merged rows are searchable in the
rebuilt b1 index and rank first under exact rescore; a second merge is a no-op;
delta rows already in the seed are counted as `duplicate_of_seed` and dropped;
truncated ids, a lying `manifest.json`, a missing artifact and a held lock each
raise with the delta and the seed untouched and no `*.tmp-*` left behind.

**UNMEASURED:** the serving effect of merging (latency, recall, load time at
600k+ seed scale) — that needs a rebuild against the real `dense/` seed, which
this session did not run. No claim is made that merging improves anything.

#### 2. usearch mutable delta index above the brute-force threshold — IMPLEMENTED + MEASURED

`SFU_DENSE_DELTA_USEARCH_MIN` (default unset/`0` = v1 brute force, unchanged).
Above the configured row count `DenseWarmCache` also maintains a mutable
usearch b1 (Hamming) index over the delta and takes candidates from it with
`ANN_OVERFETCH = 4`× over-fetch; the returned scores are still the exact int8
rescore, so they remain comparable with the seed leg's. Any usearch error
disables the lever for the process and brute force continues.

**What was measured** (2026-09-25, `scripts/experiments/bench_dense_delta_index.py`,
results `data/eval_results/dense_delta_index_bench_20260925_0018.json`):
50 queries × synthetic 384-d unit vectors with planted 20-doc neighbourhoods,
`fetch=200`, top-10, through the real `DenseWarmCache.search`; 16-core host.

| delta rows | brute p50 / p95 (ms) | usearch p50 / p95 (ms) | p50 speedup | recall@10 vs exact — brute / usearch | bulk build | incremental add |
|---:|---:|---:|---:|---:|---:|---:|
| 10,000 | 1.38 / 1.72 | 0.72 / 0.83 | **1.9×** | 1.000 / 0.914 | 0.30 s | 149 µs/row |
| 100,000 | 12.38 / 14.37 | 1.49 / 1.90 | **8.3×** | 1.000 / 0.990 | 1.86 s | 227 µs/row |
| 500,000 | 69.88 / 75.61 | 5.64 / 8.86 | **12.4×** | 1.000 / 0.972 | 14.69 s | 582 µs/row |

(500k = `DEFAULT_MAX_DOCS`, the hard doc cap.) Top-10 agreement between the two
engines equals the usearch recall column — brute force is exact at these sizes,
so every disagreement is a usearch miss.

**Reading**: the lever buys latency and costs 1–9 pp of recall@10. Brute force
stays the default because the delta is small in practice (20,520 docs on the
2026-08-17 payload) and it is exact there; the crossover worth flipping the
gate at is ~100k rows, where brute force costs 12 ms per query on the serving
thread. **Correction to the v1 text above:** brute force is *not* "sub-ms below
~200k docs" — measured 2026-09-25 it is 1.4 ms at 10k, 12.4 ms at 100k and
69.9 ms at 500k on this 16-core host.

#### 3. ONNX-int8 export of the v5 encoder — IMPLEMENTED + MEASURED

`scripts/experiments/export_dense_encoder_onnx_int8.py` (mirrors
`export_ce_onnx_int8.py`) exports `models/sfu-academic-embed-v5` →
`models/sfu-academic-embed-v5-onnx-int8` (fp32 ONNX + AVX2 dynamic int8,
per-channel) and benchmarks it. Serving gate: `SFU_DENSE_ENCODER_ONNX=1`
(literal `1`, default OFF) with `_PATH` / `_THREADS`; the warm cache's
background encoder uses it, and an unusable export logs an ERROR and falls back
to torch (fail-open — the embeddings are equivalent, only slower).

**What was measured** (2026-09-25, results
`data/eval_results/dense_encoder_onnx_int8_bench_20260925_0021.json`;
64 title+abstract texts, max_len 256, 16 intra-op threads pinned on both
engines, CPU only):

| | torch fp32 | ONNX int8 |
|---|---:|---:|
| on-disk weights | 133.5 MB | **34.0 MB** (3.9× smaller; fp32 ONNX 133.0 MB) |
| batch=1 p50 / mean | 18.73 / 47.50 ms | **5.25 / 6.66 ms** (3.6× p50, 7.1× mean) |
| batch=1 throughput | 21.1 docs/s | **150.2 docs/s** |
| batch=32 p50 / mean | 192.0 / 223.9 ms | **116.3 / 124.6 ms** (1.65× p50, 1.8× mean) |
| batch=32 throughput | 142.9 docs/s | **256.7 docs/s** |

Embedding parity (load-independent): cosine(torch, int8) **mean 0.99493, min
0.99062**; cosine(sentence-transformers, torch) = 1.000000, i.e. the script's
hand-written CLS-pool + L2-norm reproduces the served transform exactly, so the
0.995 is quantization alone. Top-3 neighbour agreement over the 8 distinct
benchmark topics: **0.958** (the all-64-texts top-5 number, 0.766, is
tie-dominated — the 64 texts are 8 topics × 8 near-duplicates —
`..._20260925_0054.json`).

**CAVEAT — contended host.** Five other agents were working this container;
loadavg was **13.75** (16 cores) during the run quoted above. Three runs, same
export, different load:

| run | loadavg(1m) | batch=1 p50 speedup | batch=32 p50 speedup |
|---|---:|---:|---:|
| `..._20260925_0021.json` (quoted) | 13.75 | 3.56× | 1.65× |
| `..._20260925_0129.json` | 16.61 | 3.38× | 1.88× |
| `..._20260925_0054.json` | 29.62 | 19.54× | 9.43× |

Absolute latencies are therefore upper bounds and the ratio moves with load:
the defensible measured claim is **~3.4–3.6× at batch=1 p50 and ~1.7–1.9× at
batch=32 p50**, with the loadavg-29.6 run discarded as noise (it inflated torch
to 155 ms p50 at batch=1). A single-tenant re-run is the outstanding work. Retrieval-quality parity (nDCG)
is **NOT** measured — and cannot pay off while the leg is off.

#### 4. OpenAlex live-API ingest hook — NOT IMPLEMENTED

(`openalex.py:_push_to_opensearch` repurpose.) v1 still captures the dominant
path (local legs) only.

### Success metrics — pre-registration (2026-09-01)

1. Cross-query recall growth on a replayed query log (expect in-domain payoff
   after ~10–50 queries, per LOCALIZED §5 model).
2. Delta-vs-exact recall ≥ 0.97 (~~trivially exact in v1: brute force~~ — this
   parenthesis was **wrong and is measured wrong below**; the v1 "brute force"
   is exhaustive over the **binary** Hamming codes and then keeps only
   `top_k × OVERFETCH` candidates to rescore, so the stage is a lossy
   prefilter, not an exact scan).
3. p95 `search_rrf` unchanged with cache on.
4. Cache-hit fraction of the dense leg vs query count.

### Success metrics — MEASURED 2026-09-25

| # | Metric | Before → After | Verdict |
|---|---|---|---|
| 1 | dense-leg recall@50 vs judged qrels, first 10 queries → last 80 | **0.107 → 0.348** (seed-only baseline flat: 0.109 → 0.141) | **growth confirmed** |
| 2 | delta search vs exact int8 top-50 over the same delta | mean **0.9978**, min **0.94**, 3/240 queries below 0.97 | **mean PASSES the 0.97 bar, worst case FAILS**; not exact |
| 3 | p95 `search_rrf` cache on vs off | p50 **3560.5 → 3592.0 ms (+31.5, +0.9%)**; p95 **8890.2 → 8287.8 ms (−602, cache-on *faster*)** | **unchanged — PASSES**, and the wrong-signed p95 bounds the noise floor |
| 4 | cache-hit fraction of the dense leg, first 10 → last 80 queries | **0.000 → 0.592** | **rises as designed** |

- **Script**: `scripts/experiments/eval_warmcache_replay.py`
- **Results**: `data/eval_results/warmcache_metrics_20260925.json` (metrics 1,
  1b, 4 and the contaminated metric 3),
  `data/eval_results/warmcache_delta_recall_20260925.json` (metric 2's full
  per-query distribution),
  `data/eval_results/warmcache_metric3_isolated_20260925.json` (metric 3,
  quiet-host re-run)
- **N**: 240 queries replayed, delta grown **0 → 17,316 docs** (17,316 enqueued,
  17,316 encoded, 0 dropped, 0 errors), replay wall 2,606 s
- **Date**: 2026-09-25

#### The pre-registered input for metric 1 DOES NOT EXIST — recorded, not worked around

Metric 1 says "on a replayed query log". The served log
`data/eval_results/serve_query_log.jsonl` **cannot be replayed**: `store_raw`
(`SFU_SERVE_QUERY_LOG_RAW`) was never set, so `src/lib/serve_query_log.py`
writes `query_norm: ""` for every entry and keeps only
`query_hash = sha1(query_norm)[:16]`. Audited by the harness at run time:
**2,254 entries, 2,254 with an empty `query_norm`, 733 distinct hashes, zero
recoverable query strings.** A sha1 prefix is not invertible.

**So metric 1 as pre-registered (on the served log) is UNMEASURABLE, and stays
that way until a consenting operator sets `SFU_SERVE_QUERY_LOG_RAW=1` and a new
log accumulates.** What was measured instead is the same quantity on a
**SURROGATE stream**: the 2026-08-18 judged query set (120 topics × 2 forms =
240 queries, `dense_ablation_queries.json`), replayed in a shuffle seeded
**20260925** so a topic's keyword and natural forms land far apart and any gain
is genuinely *cross*-query. This is a different stream, not a reinterpreted
bar — and it is a *better* one in one respect: it has graded qrels, so recall is
measured against real judgments rather than against the cache's own output.

#### 1. Cross-query recall growth — MEASURED

Dense-leg recall@50 against the judged qrels (grade ≥ 2), evaluated at the
delta state *in force before each query ran*, bucketed by how many queries had
already been replayed:

| queries already seen | n | recall@50, cache ON | recall@50, seed only |
|---|---:|---:|---:|
| 0–9 | 10 | 0.107 | 0.109 |
| 10–24 | 15 | 0.143 | 0.143 |
| 25–49 | 25 | **0.189** | 0.155 |
| 50–99 | 50 | **0.220** | 0.136 |
| 100–159 | 60 | **0.262** | 0.139 |
| 160–239 | 80 | **0.348** | 0.141 |

Mean over all 240: **0.2603 cache-on vs 0.1395 seed-only, +0.1207 absolute
(+86.6% relative)**. The seed-only arm is flat by construction (a static index
cannot learn), which is the negative control. **The payoff appears between 25
and 50 queries**, matching the LOCALIZED §5 expectation of ~10–50.

Secondary, self-referential saturation curve (how much of the *final* delta's
answer the prefix already held): 0.052 → 0.088 → 0.128 → 0.300 → 0.396 →
**0.628** over the same buckets.

**What this is NOT.** It is recall of the **dense leg alone**, not of fused
`search_rrf` output, and not nDCG. It does not reverse the 2026-08-18 ablation
verdict (`DENSE_PARTITION_AND_ABLATION.md` §7: the whole leg measured
significantly *harmful* at 0.4% coverage, Δ nDCG@10 −0.0077). It says the warm
cache does the job it was designed to do — grow the dense leg's coverage from
the query stream — and says nothing about whether the leg should be on.

#### 2. Delta-vs-exact recall — MEASURED, and the pre-registration's parenthesis was wrong

Over the final 17,316-doc delta, `DenseWarmCache.search` (exhaustive Hamming
over the packed binary codes → keep the best `fetch = top_k × OVERFETCH = 200`
→ exact int8 rescore) versus an exact int8 scan of the *same* delta:

| | recall@50 | recall@10 |
|---|---:|---:|
| mean | **0.99775** | 0.99792 |
| min | **0.94** | 0.90 |
| queries below the 0.97 bar | **3 / 240 (1.25%)** | 5 / 240 |
| queries exactly 1.0 | 90.4% | — |

**Mean clears the ≥ 0.97 bar; the worst case does not.** The loss is the binary
prefilter, not the rescore: 200 candidates are chosen by Hamming distance
before any int8 score is computed, so a doc whose sign pattern is unlucky never
reaches the rescore. The pre-registration's "trivially exact in v1: brute
force" is therefore **false** and has been struck above. Raising `OVERFETCH`
would close the gap at linear cost; nothing has been changed on that basis
here.

#### 3. p95 `search_rrf` with the cache on — MEASURED (isolated re-run is the authoritative one)

80 queries from the same replay stream, `include_dense=True`, arms
**interleaved per query** with the order flipped every rep (first-arm-on
fraction exactly 0.500), 2 reps ⇒ **n = 160 per arm**, against the already-warm
17,316-doc delta. `remote_abstracts=False`: the first attempt logged OpenAlex
**429**s from `_hydrate`, which puts the internet inside a timed section — the
same reason `spike/meta_consolidation/12_n7_fs_control.py` disables it.
Delta size before = after = 17,316, so the cache-on arm did no encoding during
the measurement; what it pays is the delta Hamming scan plus the dedup check.

| | p50 ms | p95 ms | p99 ms | mean ms |
|---|---:|---:|---:|---:|
| cache **ON** | 3592.01 | 8287.83 | 10655.0 | 3876.85 |
| cache **OFF** | 3560.47 | 8890.19 | 10130.26 | 3831.31 |
| Δ (on − off) | **+31.54 (+0.9%)** | **−602.36 (−6.8%)** | +524.7 | +45.5 |

**Verdict: p95 is unchanged — the bar passes.** Read it carefully, though: the
p95 difference has the **wrong sign** (attaching a cache cannot make the query
faster), so that −6.8% is not a win, it is a **direct measurement of this
instrument's noise floor: ≥ ~7% of p95**. The p50 delta, **+31.5 ms on a
3.56 s query (+0.9%)**, is the better-conditioned estimate of what the cache
actually costs.

⚠ **This is a weak test and the reason is structural.** On this host the
SPLADE leg serves 8 SEISMIC shards staged to local disk totalling **42 GB
against 31 GB of RAM**, so every query's p95 is set by page-cache misses in a
leg the warm cache does not touch. The measurement can exclude a *large*
regression; it cannot resolve a small one. `_record_leg("dense", ...)` per-leg
timings in `warmcache_metrics_20260925.json` are the place to look for the
dense leg's own cost.

**Provenance of the two runs.** The first metric-3 pass ran inside the replay
process while another agent's Qdrant eval and an ONNX microbench were running:
`load1 = 11.5` on 16 cores, and it produced p95 on 8564.8 vs off 9650.4 — the
same impossible sign, larger. It is kept in
`warmcache_metrics_20260925.json` **labelled contaminated**. The authoritative
numbers above come from `warmcache_metric3_isolated_20260925.json`, taken after
a quiet-host gate (`--require-quiet 3.0`) passed at `load1 = 2.35` with no
other Python benchmark running; `load1` peaked at **4.92** during the run
(this process is ~1–2 of that) and every sample is in the JSON.

#### 4. Cache-hit fraction of the dense leg — MEASURED

Fraction of the dense leg's returned top-50 that came from the warm delta
rather than the static 600k seed, at the delta state in force when the query
ran:

| queries already seen | n | delta docs | hit fraction |
|---|---:|---:|---:|
| 0–9 | 10 | 0 → 912 | 0.000 |
| 10–24 | 15 | ~1.8k | 0.001 |
| 25–49 | 25 | ~3.6k | 0.094 |
| 50–99 | 50 | ~8.4k | 0.228 |
| 100–159 | 60 | ~12.7k | 0.334 |
| 160–239 | 80 | ~17.3k | **0.592** |

Mean over the replay **0.338**. The per-query series is strongly bimodal — 0/50
on a topic the cache has never seen, up to **49/50** on a topic an earlier query
already populated. That bimodality *is* the temporal-locality effect Frieder et
al. (arXiv 2211.14155) predict, and it is why the mean understates the win on a
repeat-heavy real workload.
