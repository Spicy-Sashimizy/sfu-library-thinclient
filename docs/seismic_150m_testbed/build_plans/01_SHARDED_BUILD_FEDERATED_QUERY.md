# Build Plan 01 — Sharded build + federated query (OpenSearch segment-model → pure Rust)

**Status:** ACTIVE — BUILD COMPLETE (2026-06-28); serve half — C2.5 mmap binding GREEN + persona-validated (2026-06-28); the 150M shard-to-mmap conversion is the turnkey next step (driver shipped, run not started). **Solves:** the 150M build-RAM wall, *losslessly*, on a 32 GB host, with **no JVM**.

- **Federation gate PASSED 2026-06-28** (the one quality variable this plan
  introduces). 2-shard federated versus 1-shard single over the same 929k med_bio docs:
  overlap@10 **0.9967** over 60 queries (58/60 bit-identical, 2/60 at 0.9) →
  `FEDERATION_RESULT_SAFE` (bar ≥0.98, STOP <0.95). Per-shard pruning/k-means
  perturbation is ~0.3% of top-10. **A sharded 150M build is result-safe to trust a
  G6 number on.** Re-confirmed under the C2.5 mmap loader (`--load-mode mmap`):
  overlap@10 **0.9967** bit-identical to stock — federation is result-safe under
  Path C too. Eval `scripts/seismic_testbed/g_federation_overlap.py` →
  `data/eval_results/seismic_federation_overlap_929k.json` (+ `_mmap.json`).
  Scripts: splitter `shard_spool.py` + federated serve `seismic_federated.py` shipped.
- **Build half COMPLETE 2026-06-28 (G7 PASS).** The full 150,413,098 docs built as
  K=8 shards, **serially on the 32 GB host**: peak RSS **9.925–9.932 GB/shard** (max
  9.932 GB, << the 20 GB G7 budget), **66.26 GB total on-disk**, balance max/min
  1.001–1.0017 across all 40 section-shards. The 20M-point projection (9.54 GB)
  extrapolated near-perfectly. Driver `build_plan01_150m_shards.py` → per-shard
  result files + `data/eval_results/seismic_plan01_shards_150m.json` (manifest).
  Gate flipped to PASS in `02_GO_NO_GO_GATES.md` G7; result recorded in `06_FINDINGS.md`.
  The sharded reality ran at per-shard ~10 GB peak (serial), NOT the prior 25–60 GB
  band (that was a *single-index* 150M projection; splitting the corpus split the peak).
- **Serve half — C2.5 pyo3 mmap binding GREEN 2026-06-28.** The stock-`.load()`
  hole (RssAnon 1.706 GB on the 2M index = Path A →137 GB @150M) is **closed**:
  `seismic.MmapSeismicIndex` (new pyclass wrapping the C2 reader) validated at the
  Python serve boundary — parity bit-identical, anon Δ **0.000 GB**, 96% file-resident,
  mmap p50 0.441 ms (`data/eval_results/seismic_c25_mmap_serve_validate.json`).
  `seismic_federated.py` gains `--load-mode mmap` (default stock, back-compat).
  **150M serve shards CONVERTED 2026-06-28.** All 8 stock shards converted to the
  flat mmap layout by `convert_shard_to_mmap.py` (per-shard `load → write_mmap_index
  → from_mmap`, serial). **Measured:** 8/8 OK, bit-identical parity every shard,
  peak RSS **9.878 GB** (≈half the 20 GB/shard budget; ~14× under Path A's ~137 GB
  floor), floor anon Δ **0.044 GB** (zero re-materialization), ~97% file-resident,
  66.2 GB on-disk total (== the 66 GB source, no bloat), **~7 min wall-clock** for the
  whole 8-shard run (NOT multi-hour — the docstring estimate was conservative; rss/doc
  is sub-linear). Manifest → `data/eval_results/seismic_c25_shards_150m_mmap.json`,
  verdict `C2.5 150M_MMAP_READY`. **Load-bearing:** converted shards MUST use the C2
  flat doc-mapping layout
  (`document_mapping_strings.bin` + `document_mapping_offsets.bin`), not the stale
  C1a writer — else the reader loads `doc_mapping=None` and search falls back to
  numeric ids (overlap → 0).

## The idea in one line

OpenSearch serves SEISMIC at billion-scale by building **small immutable segments**
(forward index on disk, pruned inverted index in RAM) and querying them in parallel.
The only piece the embedded Seismic **Rust** core lacks is that segment model. Port
*just that one idea*: build the corpus as **K independent SEISMIC shards**, each small
enough to build in RAM, then **federate at query time** (query all shards, merge
top-k). No Lucene, no JVM, no on-disk merge.

## Why this is the right lever (vs compression)

- **Lossless per shard.** Each 30M-doc shard is a full-fidelity SEISMIC index — no
  quantization, no nnz pruning. It does **not** touch the 0.479 quality axis the way
  compression (Plan 03) does. The only quality nuance is per-shard-vs-global pruning
  (see Risks), which is small and *measurable*.
- **Dissolves the build wall.** Build-RAM is linear in nnz, so splitting the corpus
  splits the peak: 5 × 30M shards build at ~15–18 GB each → **fits 32 GB, one shard
  at a time** (build serially or with a 1-at-a-time queue).
- **Serving already proven.** mmap each shard (Path C: +0.041 GB anon, 96 % file).
  Resident RAM ≈ Σ(small inverted indexes) ≈ 5 × ~1.5 GB ≈ **7.5 GB + page cache**.

## Shard sizing for a 32 GB build budget

From measured build peak RSS (8M→5.11 GB, 20M→9.54 GB; ≈0.45–0.5 GB per M-doc plus
fixed overhead):

| shards | docs/shard | est. build peak RSS/shard | fits 32 GB build? |
|--------|-----------|---------------------------|-------------------|
| 5      | 30.1M     | ~15–18 GB                 | ✅ comfortable     |
| 8      | 18.8M     | ~9–11 GB                  | ✅ lots of headroom |
| 10     | 15.0M     | ~7–8 GB                   | ✅ (more fan-out)   |

**Default: 8 shards × ~18.8M docs.** Headroom for OS + the JSONL read buffer, and
fan-out of 8 is cheap to parallelize. (5 shards also fine; 8 trades a little query
CPU for a lot of build-RAM safety.)

## Build steps

1. **Shard the spool deterministically.** Hash `oaid → shard_id` (for example,
   `xxhash(oaid) % K`) so a doc always lands in the same shard and re-runs are
   reproducible. Reuse `spool_to_seismic_jsonl.py` with a `--shard k/K` filter to
   emit `med_bio_shard{0..K-1}.jsonl`. (Hash-partition, NOT range — keeps shards
   balanced in nnz so build-RAM is even.)
2. **Build each shard with DEFAULTS** (parity-matched to the G2 configuration: n_postings
   3500, centroid_fraction 0.1, summary_energy 0.4, max_fraction 1.5, doc_cut 15) via
   `build_persona_seismic.py`, one shard at a time (a serial queue; never two
   concurrent builds — that would stack the RSS). Record peak_rss / on_disk per shard.
3. **Persist a shard manifest** (`shards.json`): K, doc counts, paths, the hash seed,
   build parameters, per-shard nnz. This is the source of truth for the serving layer.

## Serving layer (the federation)

A thin Rust (or Python-over-pyseismic) wrapper:

1. **Load K shards mmap'd** (Path C mode) at startup. Resident anon RAM stays tiny;
   page cache holds hot forward pages.
2. **Query fan-out:** run the query against all K shards **in parallel** (rayon /
   thread pool). Each returns its local top-`k'` (over-fetch: `k' = k + buffer`,
   for example, top-200 per shard for a global top-50).
3. **Merge:** SEISMIC scores are inner products on a shared vocabulary, so per-shard
   scores are **directly comparable** — merge by raw score, take global top-k. (No
   score normalization needed: same query vector, same dot-product space.)
4. **Hydrate** metadata by doc-id from the doc store (see Plan 04), not from the
   index.

## RAM / latency budget (projected)

- **Build:** ≤18 GB peak per shard → fits 32 GB. ✅
- **Serve resident:** ~7.5 GB anon (Σ inverted indexes) + page cache for the ~47 GB
  of on-disk forward across shards. On 32 GB, ~24 GB of page cache covers ~50 % of
  the forward hot set → cache-miss reads on the rest. *est.*
- **Latency:** OpenSearch's single-index SEISMIC hit 11.77 ms @ 90 % recall with the
  forward on disk; fan-out over 8 shards in parallel adds merge + the slowest-shard
  tail, not 8×. Expect low-tens-of-ms warm. **UNMEASURED — must benchmark.**

## Risks / honest caveats

- **Per-shard versus global pruning (the one real quality variable).** SEISMIC computes
  its posting-pruning and k-means *within* each shard, so K-shard top-k is **not
  bit-identical** to a single 150M index. Each shard is still ~18–30M docs (well above
  the persona degeneracy threshold), so the perturbation is expected to be small —
  but it MUST be measured before trusting a G6 result on the sharded index:
  build a 2-shard versus 1-shard index over the *same* 4M docs, compare overlap@10.
  Pre-registered: if 2-shard versus 1-shard overlap ≥ 0.98, federation is result-safe;
  if < 0.95, fan-out is itself perturbing results and the shard count must drop.
- **Engineering cost is real.** Shard manager + parallel fan-out + merge + manifest
  is new code (not a flag). Estimate: a focused build, not a one-liner.
- **Over-fetch tuning.** Too small `k'` per shard truncates the global top-k; start
  at `k' = 4×k` and verify the global top-k is stable as `k'` grows.
- **Does NOT fix quality.** If single-index G2 is 0.479, sharding keeps it ~there
  (modulo the pruning nuance). This unblocks G6; it does not win the quality gate.

## Success criteria

1. 150M built as K shards, each build ≤ 20 GB peak RSS on the 32 GB host (G1/G7).
2. Federated serve: resident anon ≤ 10 GB, warm p50 latency measured & recorded.
3. 2-shard-vs-1-shard overlap@10 ≥ 0.98 on a shared 4M slice (federation is
   result-safe).
4. **G6 RRF parity run completes on the sharded 150M leg** — the actual goal.

## Provenance

Ports the segment architecture documented in OpenSearch's
"Scaling neural sparse search to billions of vectors" blog into the embedded Rust
Seismic core (`SeismicIndex` + mmap/Path C), avoiding the JVM the thin-client
deliberately left. Measured groundwork: `06_FINDINGS.md` (forward-floor, build-RSS
curve, Path C), `02_GO_NO_GO_GATES.md` (G2/G7).
