# 09 · Cross-Shard Signals & Mmap Page-Economics Audit

**Status:** ACTIVE

**Created 2026-07-02. Status: RESEARCH AUDIT + E1 MEASURED (2026-07-02).** The
audit itself was read-only; **experiment E1 (§4) has since been RUN** on one
150M mmap shard (single-shard micro-measurement, ≤100 queries, mmap load only —
within the standing RAM rules) and its result is recorded in §2.1 / §2.2 / §4.
E2–E5 remain proposals — not run. Every claim below either cites a measured
number (doc + result file + absolute date) or is tagged **UNMEASURED** / *est.*

> **CORRECTION FROM RUNNING E1 (2026-07-02):** `query_cut` is a candidate-
> **gather** cut, NOT a scoring cut — SEISMIC re-scores every gathered candidate
> against the FULL passed query vector (`mmap_io.rs:640-670`). The original §2.1
> framing ("keeps the top-N terms … df-aware re-rank before the cut") was wrong:
> shrinking the passed vector corrupts scoring (measured overlap@10 collapses to
> ~0.5), and the engine's internal weight-based list selection is not a
> query-time knob. §2.1 is rewritten below; the salvaged lever is **k'**, not
> df-aware term selection.

Two questions, answered from the existing evidence base + code:

1. **CROSS-SHARD SIGNALS** — which per-document signals are consistent across
   all 8 shards and could improve federated retrieval (pruning, score
   calibration, grouping related works)?
2. **MMAP EFFICIENCY** — which index-structure choices determine
   pages-touched-per-query under mmap serving, and which are changeable at
   query time vs only by rebuild?

---

## TL;DR

- **Shard pruning by metadata is structurally impossible under the current
  partitioning.** Routing is `blake2b(seed+oaid, 8B) % 8`
  (`scripts/seismic_testbed/shard_spool.py:50-55`) — content-agnostic, so every
  shard is a near-perfect uniform 1/8 random sample of the corpus (measured
  balance 1.001–1.0017, `seismic_plan01_shards_150m.json`, 2026-06-28/30). Any
  per-doc signal (year, section, type, is_oa) has an identical distribution in
  all 8 shards → no query can rule a shard out. Signal-keyed sharding is a
  rebuild-class change and is already designed (`docs/semantic_docid_ingest/`,
  GO'd for a Stage-1 spike, 2026-06-30) — build on that, do not re-derive it.
- **Cross-shard score calibration is a solved non-problem.** All shards share
  one SPLADE token space, receive the identical encoded qvec, and forward
  values are per-value deterministic f16 quantization — so per-shard scores are
  the same dot products and merge raw (`_merge_topk`,
  `src/lib/thinclient/sharded_seismic_backend.py:199`). Parallel ≡ sequential
  bit-identical (T1, `scripts/tests/test_seismic_sequential.py`); the only
  per-shard divergence is clustering/pruning approximation, measured at 0.33%
  of top-10 (federation overlap 0.9967, `seismic_federation_overlap_929k.json`,
  2026-06-28).
- **The useful cross-shard signals live OUTSIDE the shards**: `meta.sqlite` v2
  is one global DB (id → title/doi/year/type/is_oa/section for all 150M docs,
  shard-independent by construction). Filters and version-grouping are
  correctly done post-merge at the meta layer (already partly implemented:
  `retriever._post_filter`, `src/lib/thinclient/retriever.py:739`). DOI-based
  grouping of versions across shards is a cheap top-k post-pass — prevalence
  UNMEASURED.
- **The best query-time win is `k'`, MEASURED via E1 (2026-07-02).** Dropping
  the per-shard over-fetch `k'` from the served default 200 (4×k) to 100 is
  **recall-safe (overlap@10 0.995) and 1.41× faster warm traversal** (5.95 →
  4.22 ms) with fewer page faults, on the 18.8M shard0
  (`seismic_e1_kprime_df_sweep_20260702_2314.json`). **`query_cut` does NOT
  replicate the C1 100k win at 150M** — qc=10 falls to overlap@10 0.9275
  (avg/40 diverse queries), below the 0.99 bar, so the served default must stay
  ~all-terms on recall grounds. df-aware term *selection* is dead (mechanism:
  it corrupts full-query scoring — negative control overlap 0.48–0.62). Global
  per-term df is still free to read from one shard's manifest, but its only
  live use would be an in-engine gather-selection change (§2.2), not a
  query-time knob.
- **Page economics:** the forward index is **85% of shard bytes** (shard0:
  forward 6.74 GB vs inverted+summary 1.17 GB, `build_global_shard0.json`,
  2026-06-30) and is touched by **random ~350 B reads per candidate doc**
  (~87.6 nnz × 2 B components + 2 B values) → ≈ 2 random 4 KB pages per scored
  candidate across two separate files. Candidates-scored, not list length, is
  the page-touch elephant. Free query-time levers: `query_cut` (measured 4.02×
  traversal at overlap@10 0.995, 2026-06-30), `heap_factor`, `k'`
  (UNMEASURED). Layout levers (rebuild): `n_postings`↓, `centroid_fraction`,
  4-bit summaries / DotVByte forward (fork), and — the audit's main new
  observation — **forward-index doc ordering** (semantic ordering would convert
  scattered candidate faults into clustered ones; UNMEASURED, converter-level
  rewrite, ties directly into the semantic-docid design).
- **File-backed pages bypass zram/zswap** (only anonymous pages compress —
  `08_LATENCY_RESEARCH.md` §E, 2026-07-01). Under mmap serving the ONLY levers
  are (a) touch fewer pages and (b) make the on-disk bytes smaller so the same
  cache holds more of them. There is no compression rescue for the mmap cell.

---

## 1. Cross-shard signal inventory (Question 1)

### 1.1 The partitioning fact that governs everything

`shard_id = blake2b("sfu-seismic-plan01" + oaid, digest_size=8) % 8`, applied
per-section and unioned (global shard k = union of section shard-k across the 5
spool sections) — `scripts/seismic_testbed/shard_spool.py:50-55` and the
manifest `hash_fn` field. Measured consequences:

- Doc balance max/min 1.001–1.0017 across all 40 section-shards
  (`data/eval_results/seismic_plan01_shards_150m.json`, built 2026-06-30).
- Each shard ≈ 18.8 M docs, avg 87.6 nnz/doc, dim 28,700–28,725.

Because the hash ignores content, **every shard is an i.i.d. 1/8 sample**: the
year histogram, section mix, type mix, and is_oa rate of shard 3 are the same
as shard 5 (to sampling noise ~1/√18.8M). This has two faces:

- **Negative:** no signal can prune a shard at query time. A `year≥2020` query
  still has ~1/8 of its answer set in every shard.
- **Positive:** any global statistic can be estimated from one shard, and
  uniform per-shard `k'`/parameters are provably the right choice (no shard is
  special).

### 1.2 Per-document fields reachable at serve time

| Field | Where it lives | Present for all shards? | Query-time cost | (i) shard/era pruning | (ii) score calibration | (iii) grouping related works |
|---|---|---|---|---|---|---|
| `openalex_id` (W-id) | shard `document_mapping_strings.bin`/`_offsets.bin` (zero-copy mmap, `spike/seismic_upstream/src/mmap_io.rs:283-299`) + `meta.sqlite` PK | ✅ (every doc, every shard) | free — returned with results | no (content-agnostic) | n/a | join key for everything below |
| `title` | `meta.sqlite` v2 `docs.title` (global, one DB for all 150M) | ✅ shard-independent | one batched indexed lookup per top-k (`retriever._meta_rows`) | no | n/a | fuzzy match for version grouping (weak) |
| `doi` | `meta.sqlite` `docs.doi` | ✅ (nullable per doc — spool sample shows `doi: None` occurs) | same batch | no | n/a | **the strong grouping key** — same work's versions share DOI across shards; cheap top-k post-pass (rows already fetched by `_hydrate`). Prevalence in top-50 UNMEASURED |
| `year` (`publication_year`) | `meta.sqlite` `docs.year` | ✅ | same batch; already used by `_post_filter` (`retriever.py:748-751`) | **no on SEISMIC shards** (hash mix) — note the asymmetry: the tantivy leg DOES era-prune (`retriever._era_skip`, `retriever.py:837`) because its sections are era-keyed; the SEISMIC leg lost that axis when it sharded by hash | n/a | version disambiguation (earliest = preprint heuristic, UNMEASURED) |
| `type` | `meta.sqlite` `docs.type` | ✅ | same batch; `_post_filter` | no | n/a | filters `paratext`/`dataset` variants of a work |
| `is_oa` | `meta.sqlite` `docs.is_oa` | ✅ | same batch; `_post_filter` | no | n/a | no |
| `section` (subject+era) | `meta.sqlite` `docs.section` | ✅ | same batch | no on the current shards; **the rebuild lever** (see §1.4) | n/a | topical grouping |
| `abstract` | hot sidecar (hot section) / OpenAlex API (cold) | ⚠️ hot-section only locally | sidecar read or network mget | no | n/a | no (rerank input, not a key) |
| ISSN / venue / concepts / authorships | **NOT exported** — the spool record carries only `{abstract, doi, id, openalex_id, publication_year, sparse_field, title, type}` (verified on a live spool record, 2026-07-02) | ❌ needs OpenAlex API per doc or a new export | network per doc — too costly on the query path | no | n/a | would strengthen grouping (same venue/ISSN) but is a build-pipeline change, not a serve-time option |
| `sparse_field` (SPLADE vector) | the shard forward index itself (f16) | ✅ | already paid during search | see §2 (vocabulary leverage) | the reason calibration is unnecessary | n/a |

**Schema evidence:** `meta.sqlite` v2 = `docs(id INTEGER PRIMARY KEY, title,
doi, year, type, is_oa, section)` + `docs_other(id TEXT, …)` overflow —
inspected read-only 2026-07-02; matches `THIN_CLient_SWAP.md` "meta v2"
(measured ~24.9 GB at 150M, 2026-06-16).

### 1.3 The three uses, judged

**(i) Query-time shard/era pruning — NOT AVAILABLE without a re-shard.**
Year/type/is_oa filters currently run as post-filters on the merged federated
top-k (`retriever.py:748-756`) after all 8 shards were traversed; the
over-fetch multiplier for filtered queries (`OVERFETCH_FILTERED`) compensates
for filter loss. Under hash sharding this is correct and also the best
possible: there is nothing to prune. The only routes to pruning are
partitioning changes (§1.4). What IS available cheaply today: **pre-checking
degenerate filters** (e.g. `year_range` entirely outside the corpus range)
before paying the 8-shard fan-out — micro-win, UNMEASURED.

**(ii) Cross-shard score calibration — unnecessary by construction.**
Three stacked reasons, all in code:
1. One SPLADE token space: each shard's `token_to_id_map` maps the same token
   strings (per-shard ids differ — dims 28,700–28,725 — but
   `resolve_query_tokens` resolves per shard, `mmap_io.rs:619-623`, so id
   drift cannot leak into scores).
2. Identical qvec per shard: encoded once, fanned out
   (`sharded_seismic_backend.py:307-330`).
3. Forward values are `ScalarSparseQuantizer<u16,f32,f16>` — a per-value,
   corpus-independent f16 cast (`mmap_index.rs:55`), NOT per-shard statistical
   quantization. The per-block `minimums`/`quants` scalars ARE per-shard
   statistics, but they only steer the block-skip approximation; final scores
   come from the forward f16 values.
So raw scores merge exactly (`_merge_topk`), and the measured evidence agrees:
federation overlap@10 0.9967 vs a single index over the same docs (2-shard
gate, 2026-06-28, `seismic_federation_overlap_929k.json` + `_mmap` twin), and
the sequential/parallel bit-identical T1 test. **Do not add a calibration
layer; it can only distort an already-exact merge.** The residual 0.33%
divergence is per-shard k-means/pruning approximation, not score skew.

**(iii) Grouping versions/parts of the same work across shards — feasible
today, post-merge, at ~zero cost.** Different W-ids of the same work (preprint
vs published, parts of a book) hash to different shards, but grouping never
needed co-location: the merged top-k is ≤ tens of docs and `_hydrate` already
fetches their meta rows. A DOI-keyed collapse (keep best-scoring W-id per DOI,
attach the rest as `other_versions`) is an O(k) dict pass. Two honest
unknowns: (a) how often duplicate-DOI pairs actually co-occur
in a top-50, (b) whether OpenAlex merged-candidate W-ids (redirects) appear in
the corpus — those don't share a DOI row and would need the API. **(a) partly
MEASURED via the E1 piggyback (2026-07-02): 0/40 queries had ≥2 top-50 docs
sharing a DOI** on `global_shard0of8` — but this is a **single-shard** top-50,
and a work's versions hash to *different* shards (§1.1), so within-one-shard
co-occurrence is rare by construction; the federated-top-50 prevalence (the
number that decides whether grouping is worth building) needs the 8-shard merge
and is still UNMEASURED. Read the 0/40 as: within-shard duplicate DOIs are
effectively absent, consistent with hash sharding scattering versions.

### 1.4 The rebuild-class option: signal-keyed sharding (pointer, not a proposal)

`docs/semantic_docid_ingest/` (2026-06-30, DESIGN ONLY) already worked this
out: a hierarchical semantic ID (`subject · era · cluster …`) as the shard
routing key would make shard membership *mean* something → year/section-
filtered queries prune shards the way `_era_skip` prunes tantivy sections
today, and prefix-depth cuts give elastic re-sharding. Costs it already names:
LSM-vs-mmap tension (many small segments inflate resident set), no cheap
SEISMIC merge (compaction = localized rebuild), bit-reproducible assignment
required. Its Stage-1 spike gate (RSS-vs-segment-count, fan-out, p95) is the
right decision instrument. This audit adds one quantified argument in favor:
semantic sharding would also fix the **forward-locality** problem (§3.4),
which hash sharding makes worst-case by construction. Nothing here should be
built before that spike passes its mmap gate.

---

## 2. Shared-vocabulary leverage (Question 2, first half)

All shards were built from one SPLADE encoder's output and receive the same
top-64-term qvec (`SPLADE_QUERY_TERMS = 64`, `retriever.py:101`,
`seismic_backend.py:37`). Global term statistics therefore exist and are
identical in expectation across shards. What could be computed ONCE, offline,
with no rebuild:

| Global statistic | Where it already sits | Cost to extract | What it buys |
|---|---|---|---|
| per-term **pruned df** (posting-list length after n_postings pruning) | each shard's `.mmap/manifest.json` → per-list `packed_postings_words` (`mmap_io.rs:64-70`); ×8 ≈ global, or read all 8 manifests (~22 MB each) | minutes, pure file read | df-aware term selection (below) |
| per-term **summary mass** (`values_len` per list) | same manifest | same | predicts per-term page cost of step-1 traversal (§3.2) |
| per-term **max impact** (block `minimums+quants` ceilings) | posting_lists.bin (needs a small reader) or upstream at build | hours | upper-bounds a term's possible score contribution → safe skip criterion |
| true unpruned df | spool scan — **do not run** (full-section read, forbidden-class cost) | — | not needed; pruned df is what the traversal actually pays |

**2.1 `query_cut` is a gather cut, not a scoring cut — MEASURED (2026-07-02).**
`search_raw` builds the forward-scoring evaluator from the **full** passed
query vector, then visits only the top-`query_cut` posting lists (by weight,
`k_largest_by`, `mmap_io.rs:651`) to *gather* candidates; each gathered
candidate is re-scored against the full query. Two consequences, both measured
on shard0 (`seismic_e1_kprime_df_sweep_20260702_2314.json`, 40 diverse
queries):
- **Pass all terms + small `query_cut` (the correct lever):** fewer lists
  traversed, full-query scoring preserved. But recall is NOT free at 150M —
  overlap@10 vs the all-terms baseline is **0.865 @ qc=5, 0.9275 @ qc=10,
  0.9425 @ qc=15, 0.96 @ qc=20**, and only **qc=all reaches ≥0.99** (0.9875 at
  k'=50, 0.995 at k'=100). **This CONTRADICTS the C1 sweep's 0.995 @ qc=10**
  (`seismic_sweep_c1_querycut_heapfactor_20260630.json`) — that was on a 100k
  index; at 18.8M/shard the same qc=10 drops to 0.9275. **The C1 caveat ("re-
  verify overlap@10 ≥0.99 at 150M before flipping the served default") is now
  answered: NO — do not flip the served `query_cut` to 10 on recall grounds.**
- **Pass a pre-cut subset (the naive df idea — WRONG):** shrinking the passed
  vector truncates the scoring vector too. Negative control: a top-10-weight
  subset gives overlap@10 **0.50** (weight) / **0.4825** (idf) — df-reordering
  the subset is even worse than weight. **df-aware term selection from Python
  is killed.** A df-aware *gather* (choose which lists to visit by weight×idf,
  not weight) would help only inside the engine's `k_largest_by` — an engine
  change, not a query-time knob, and low priority since query_cut must stay
  ~all for recall anyway.

**2.2 `k'` is the salvaged query-time win — MEASURED (2026-07-02).** Default
`k' = 4×k` per shard (`_prepare_query`, `sharded_seismic_backend.py:195`) → 200
for a top-50. Under uniform 1/8 sampling the global top-50 spreads
~Binomial(50, 1/8)/shard (mean 6.25), so 200 is generously oversized (audit
§0). Measured: at fixed `query_cut`, dropping `k'` from 200→50 is
**overlap-neutral (Δ ≤ 0.005)** and cuts warm traversal ~1.4–1.7× with fewer
faults (e.g. qc=all: k'=200 baseline 5.95 ms → **k'=100 4.22 ms @ overlap
0.995 (recall-safe, 1.41×)** → k'=50 3.54 ms @ 0.9875 (1.68×); majflt on the
qc=5 cold pass 610→26→0 as k' drops 200→100→50). Mechanism confirmed: a
smaller `k'` heap fills sooner, its k-th score rises, and the `heap_factor`
block-skip test (`mmap_index.rs:313`) rejects more blocks. The knob is already
env-exposed (`SFU_SEISMIC_K_PRIME`, `retriever.py:634-641`). **Recommendation
(unmeasured at the federated/system level — leg-overlap only):** lowering the
served default from 200 to 100 is recall-safe on this shard; a federated G6-
style re-check before flipping the production default is the owed follow-up.

> **FOLLOW-UP PAID + FLIPPED (G8f, 2026-07-08).** The federated-level gate
> ran at n=100 on the served dv path: merged top-k overlap (k'=100 vs
> k'=200) **overlap@10 0.999 / overlap@50 0.994**, federated traverse
> **1.47× faster** (38.3 → 26.0 ms p50) — E1's per-shard 1.41× carries to
> the federation. **Served default flipped to `max(2×top_k, 100)`**
> (`sharded_seismic_backend._prepare_query`, same commit).
> `data/eval_results/g8f_shardmerge_profile_kprime_20260708.json`; the
> per-shard/merge attribution from the same run lives in doc 08 §A4.

**2.3 Early-exit / ordering of shards — two different verdicts.**
- *Shard ordering for pruning:* useless — shards are exchangeable (§1.1);
  there is no "most promising shard" to visit first.
- *Carrying the heap floor across shards (sequential mode only):* real. Each
  shard search starts an empty `KHeap::new(k)` (`mmap_io.rs:643`), so shards
  2..8 re-pay the warm-up period where the heap threshold is low and few
  blocks are skipped. `SequentialSeismicBackend._fan_out`
  (`sharded_seismic_backend.py:403-419`) could pass the running global k'-th
  score into the next shard as an initial threshold (needs a small pyo3 API
  addition: `search(..., initial_threshold=)` seeding the heap-min used in the
  skip test). Expected effect: strictly more block skips in later shards, same
  or better approximation than today's per-shard-independent skipping (the
  skip test is already approximate; a tighter *true* bound only skips blocks
  that could not enter the global top-k'). Parallel mode can't use it (shards
  race). **UNMEASURED** — experiment E4.

---

## 3. Mmap page-economics (Question 2, second half)

### 3.1 On-disk layout, measured (shard0 of 8, 18,799,322 docs)

From the persistent converted dir
`data/seismic_150m/index/plan01/global_shard0of8.mmap/` (listed 2026-07-02) and
the build split (`data/eval_results/build_global_shard0.json`, 2026-06-30):

| File | Bytes | Element type | Access pattern at query time |
|---|---|---|---|
| `forward_components.bin` | 3.294 GB | u16 per nnz | **random**, ~175 B per candidate doc |
| `forward_values.bin` | 3.294 GB | f16 per nnz | **random**, ~175 B per candidate doc |
| `forward_offsets.bin` | 150 MB | usize per doc (8 B) | random 8 B per candidate (dense enough to stay largely cached) |
| `posting_lists.bin` | 1.159 GB | per-list: packed postings (u64/posting) 323 MB + block_offsets 26 MB + summaries 820 MB (EF offsets, id bitfield, u8 values, f32 minimums/quants) | **sequential within a query term's list** |
| `document_mapping_strings.bin` + `_offsets.bin` | 207 + 150 MB | UTF-8 slab + usize offsets | k' random touches per shard (result hydration only) |
| `token_to_id_map.bin` | 0.65 MB | bincode → **owned anon** (`mmap_io.rs:556-565`) | resident, negligible |
| `manifest.json` | 21.9 MB | parsed once → owned | load-time only |

Whole-corpus totals: 8 shards, 62 GB converted (du 2026-07-01), forward =
**85%** of index bytes at 150M (vs 38% at 2M — the split flipped with scale;
`06_FINDINGS.md` G7 row, 2026-06-28).

### 3.2 Pages touched per query — the traversal model (from code)

Per shard, per query (`MmapSeismicIndex::search_raw`, `mmap_io.rs:599-690`):

1. **Per query term** (top `query_cut` by weight): one full summary pass of
   that term's posting list — `summaries.distances()`
   (`mmap_index.rs:143-232`) reads the list's u8 `values` run contiguously plus
   the `summaries_ids` bitfield and per-block `quants`/`minimums`. Contiguous
   inside `posting_lists.bin` → **sequential pages ≈ list-summary-bytes /
   4 KB**. Cheap and prefetch-friendly.
2. **Per surviving block** (summary dot ≥ `heap_factor` × heap-min,
   `mmap_index.rs:312-317`): the block's packed-posting slice (contiguous,
   8 B per posting — each posting is a `(forward_offset:48, len:16)` u64,
   `posting_list.rs:37-69`), then **per unvisited candidate doc one random
   forward read**: `get_with_range` pulls ~87.6 nnz × 2 B from
   `forward_components.bin` AND ~87.6 × 2 B from `forward_values.bin` — two
   separate files, so **≈ 2 random 4 KB pages per scored candidate** (≈ 350
   useful bytes per 8 KB faulted; occasionally 4 pages on straddles). A
   `prefetch_with_range` pass precedes scoring (`mmap_index.rs:332-338`) which
   hides latency but does not reduce pages.
3. **Result hydration**: k' doc-mapping reads — negligible.

**The forward side dominates pages-touched**: candidates-scored × ~2 pages.
G4 measured candidates/corpus at 0.92–1.98% (persona scale, falling with
corpus, `seismic_pruning_persona.json`, 2026-06-26); the exact 150M per-query
candidate count is **UNMEASURED** (the instrumented `search_with_stats` fork
was persona-only). Consistency check, *est.* only: ~0.3–0.5% of 18.8 M docs ≈
60–90k candidates/shard × 2 pages ≈ 0.5–0.7 GB faulted per shard per cold
diverse query — the right order of magnitude for the measured ~40 GB touched
working set of 40 diverse queries over 8 shards and the ~25 GB of 12 queries
(A1 #3, `seismic_ram_sweep_20260630.tsv`). Treat as a sanity envelope, not a
measurement.

> **MEASURED 2026-07-09 (Q6):** the fork's `search_visited` hook exported the
> real traversal `visited` set on shards 1–2, n=100, k'=200/hf=0.8/qc=all:
> **mean ~17.8k candidates/query/shard (p50 ~16.8k, range 5.2k–36.9k)** —
> ~0.09% of docs, so the envelope above was ~4× high, but the ~2
> pages/candidate model is exact (measured 2.03 on the shipped f16 layout).
> ≈ 140 MB faulted per shard per cold diverse query (f16, both files).
> `data/eval_results/q6_e5_coaccess_sim_20260709.json`.

**Why pages are THE serving currency here:** the RAM-latency curve is
flat-then-cliff — warm p50 65–80 ms while the touched set fits page cache,
**~650× cliff to 42 s** one step below it (A1 #3, measured 2026-06-30,
container-cap sweep 48→24 GB). Every page you stop touching moves the knee
left, i.e. shrinks the box the corpus serves from. And per `08_LATENCY_RESEARCH.md`
§E (2026-07-01): **file-backed mmap pages bypass zram/zswap** — an evicted page
is a disk re-fault, never a µs decompress. So under `load_mode=mmap` the only
levers that exist are *fewer pages touched* and *smaller on-disk blocks*.

### 3.3 The lever table — MATH (servable now) vs LAYOUT (rebuild)

| Lever | Changes | Mechanism on pages | Class | Evidence |
|---|---|---|---|---|
| `query_cut` (`SFU_SEISMIC_QUERY_CUT`) | which posting lists are **gathered** from (NOT which terms score — §2.1) | fewer lists → fewer blocks → fewer candidates | **MATH — env, no rebuild** | **MEASURED 2026-07-02 (E1)**: at 18.8M, qc=10 → overlap@10 **0.9275** (below 0.99), only qc=all clears 0.99 → **the 100k 0.995@qc=10 does NOT transfer; keep served default at all-terms** (C1 caveat answered NEGATIVE) |
| `heap_factor` (`SFU_SEISMIC_HEAP_FACTOR`) | block-skip aggressiveness | fewer blocks → fewer forward candidate pages | **MATH — env** | MEASURED inert-to-mild in 0.6–0.8 (same sweep) |
| `k'` (`SFU_SEISMIC_K_PRIME`) | per-shard heap size | heap-min rises sooner → more block skips | **MATH — env** | **MEASURED 2026-07-02 (E1)**: 200→100 recall-safe (overlap@10 0.995) at 1.41× warm; 200→50 at 0.9875/1.68× — the shippable lever |
| df-aware term selection | which terms enter `query_cut` | drops max-cost terms first | **MATH — Python-side + one offline df table** | UNMEASURED (E1) |
| carried heap floor (sequential) | initial skip threshold per shard | later shards skip warm-up blocks | MATH but needs a **small pyo3 API addition** (no index change) | UNMEASURED (E4) |
| `madvise(MADV_RANDOM)` on the two forward files | kernel readahead | stops speculative readahead around each ~350 B candidate read — default readahead can fault up to 32 extra pages per miss (*est.*, kernel-default 128 KB window; actual amplification UNMEASURED) | **`.so` rebuild only — index files untouched** | named design-only in `08` §A3; the reader today applies `WILLNEED|SEQUENTIAL` only inside the `touch_slab` fault-in helper (`mmap_io.rs:778-798`), nothing on the query path |
| `MADV_DONTNEED` after shard (mechanism B) | peak resident, not pages touched | bounds resident ≈ 1 shard; each query still re-faults | shipped (sequential only) | MEASURED 2026-07-01: anon floor 1.01 GB but warm ≈ cold 15.9 s on the 32 GB box (`seismic_serve_bench_sequential_20260701.json`) — release trades latency for floor, exactly as designed |
| `n_postings` ↓ (e.g. 3500→2000) | posting-list lengths → blocks → candidates AND summary bytes | fewer step-1 pages and fewer candidates | **LAYOUT — full shard rebuild** | G2 swept it **UP** to saturation and proved top-10 bit-identical (2026-06-27, `seismic_g2_npostings_sweep.json`); the DOWN direction (smaller index, same results?) was never tested — E3 |
| `centroid_fraction` | block count/size per list | finer blocks = sharper skips but more summary bytes; coarser = fewer summary pages but blunter skips | **LAYOUT — rebuild** | measured on quality (±0.003, 2026-06-27); page-cost axis UNMEASURED |
| `summary_energy` α | summary nnz per block | step-1 pages | **LAYOUT — rebuild** | quality-inert in the 0.4→0.9 sweep (2026-06-27); size axis: index grew 1.69→5.28 GB at α 0.9 — so α↓ *shrinks*, floor at default 0.4 |
| forward value/component width (DotVByte ~32% smaller fwd @1.2× decode; 4-bit summaries ~30-35%) | on-disk bytes per candidate/summary | same touches, smaller pages-per-candidate footprint → more of the index fits cache | **LAYOUT + reader fork** (writer AND `MmapSparseStorage` change) | **E6 design + E7 IMPLEMENTATION (2026-07-03)**: dotvbyte forward shipped (shard0 fwd 6.74→3.97 GB, majflt −41%, cold 1.43× faster, parity 0.995); warm recleared 0.957× by the native rebuild. **E7b RAM-capped verdict (2026-07-03, host): PROMOTED for RAM-constrained deploys** — at a 4 GB cap f16 cliffs (warm p50 1.3–1.9 s, ~100–173k majflt/pass) while dotvbyte stays warm (3.3 ms, 0 majflt); f16 stays default when RAM is ample. See `10_FORWARD_COMPRESSION_DESIGN.md` §7.5 |
| shard count K | per-shard file sizes, fan-out, merge width | total bytes unchanged; more shards = more (smaller) mmap regions + wider merge | **LAYOUT — re-shard + rebuild** (a K=16 split is mid-flight per the 2026-07-01 stage-1 commit `f23562b`) | corpus-scaling measured near-flat for parallel latency (A1 #4: 8× docs → 1.6× warm p50) |
| **forward-index doc ordering** (§3.4) | WHERE candidate docs sit in the forward files | co-locates docs that are scored together → candidate faults share pages | **LAYOUT — converter-level rewrite** (permute forward + remap the 48-bit offsets in every packed posting; no SEISMIC re-clustering needed) | **Q6 SIM GO 2026-07-09**: buildable posting-pack-walk order simulates to **0.376–0.400× pages/query** (bar ≤0.45, both shards, both codecs; log-driven ceiling 0.345); converter build green-lit — E5 (see §4 E5 note) |

### 3.4 The forward-locality observation (new in this audit)

Forward order today is spool/insertion order (sections concatenated, then
hash-filtered) — with respect to *what a query touches*, effectively random.
But step-2 touches arrive in **block bursts**: `evaluate_posting_block` scores
all unvisited members of one geometric block together
(`mmap_index.rs:322-349`). Block members are similar docs; a doc belongs to
~87 lists' blocks, so perfect co-location is impossible — but *any* similarity-
preserving order (the semantic-docid prefix, or even section+year) makes
co-block docs *statistically* adjacent in the forward files, so a burst of B
candidate reads lands on ≪ 2·B distinct pages instead of ≈ 2·B. This is the
classic docid-reordering result from the IR literature applied to SEISMIC's
forward index rather than postings compression. It requires **no change to
SEISMIC's clustering or scores** — a pure permutation of the forward arrays
plus rewriting each packed posting's 48-bit offset (`posting_list.rs:52`) and
the doc-mapping order at convert time; parity must stay bit-identical (scores
don't depend on doc position). Expected gain **SIMULATED 2026-07-09 (Q6): the
posting-pack-walk first-touch order — derivable from the index alone, no
semantic key — simulates to 0.376–0.400× unique pages/query** (see §4 E5
note); converter cost still unmeasured. It is also the page-economics
argument FOR the semantic-docid Stage-1 spike (§1.4) — though Q6 showed the
pack-walk key alone captures most of the log-driven ceiling, so routing, not
locality, is now that design's main argument.

---

## 4. Ranked experiment proposals (NOT RUN — proposals only)

Ranked by information-per-cost. Each lists metric, script to reuse, cost, and a
kill criterion. Per the standing rules: single-shard where possible, mmap load
mode only, ≤100 queries, cite RSS before/after.

**E1 — `k'` × `query_cut` sweep at 150M — ✅ DONE 2026-07-02.** Script
`scripts/seismic_testbed/e1_kprime_df_sweep.py` (df table read from the mmap
`manifest.json` + `token_to_id_map.bin`, no index build; `release_pages()`
mechanism-B eviction before each cell's cold pass so `majflt` is a real
pages-touched proxy). Ran on `global_shard0of8.mmap` (18,799,322 docs), 40
diverse queries, `models/splade_onnx_fp16`. Result
`data/eval_results/seismic_e1_kprime_df_sweep_20260702_2314.json`. **Verdict
`E1_NO_1.3x_WIN` on the strict bar, but a live recall-safe win on `k'`:** no
cell beat the (recall-failing) qc=10 ref by ≥1.3× at overlap ≥0.99, BUT the
sweep established (a) **`k'` 200→100 is recall-safe at 1.41× warm speedup**
(§2.2 — the shippable lever), and (b) **`query_cut` cannot drop below all-terms
at 150M without breaching overlap 0.99** (§2.1 — the C1 100k result does not
transfer; a NEGATIVE answer to the standing C1 caveat), and (c) the naive
df-subset negative control confirmed Python-side term selection is the wrong
mechanism. Anon floor held at RssAnon 0.075 GB (index) throughout; no swap.
The run overturned this audit's own §2.1 mechanism claim — logged as a
correction at the top. Owed follow-up: a federated/system-level check before
lowering the served `SFU_SEISMIC_K_PRIME` default.

**E2 — `MADV_RANDOM` on the forward mmaps (.so change, no index change).** Add
`madvise(MADV_RANDOM)` for `forward_components/values` at `from_mmap` time
(`mmap_io.rs:418-441`), keep `posting_lists.bin` default (its access is
sequential-per-list). Metrics: cold p50 + majflt + RssFile peak, 1 shard, ≤40
queries, before/after, page-cache dropped between runs. Cost: Rust rebuild +
~an hour. Kill: cold p50 improves <10% AND RssFile amplification (RssFile
touched ÷ theoretical bytes) unchanged — then readahead wasn't the amplifier
and the est. in §3.3 is falsified.

**E3 — `n_postings` DOWN-sweep on one shard (the untested direction of a
proven-inert lever).** Rebuild ONE 18.8M shard at n_postings ∈ {2000, 1000}
(build ~19 min + convert ~7 min/shard at ~10 GB peak RSS per the G7/C2.5
measurements — fits the 31.6 GB host serially), measure on-disk size,
posting_lists.bin size, traverse p50, overlap@10 vs the n=3500 shard on the
same queries. Rationale: G2 proved raising n_postings changes nothing
bit-identically; if lowering it also holds overlap ~1.0, the inverted side +
candidate counts shrink for free. Kill: overlap@10 < 0.98 vs the current shard
at n_postings=2000 (then the default is already at the quality edge and the
lever is dead downward too).

**E4 — carried heap floor for sequential federation (pyo3 API addition).**
Add `initial_threshold` to `MmapSeismicIndex.search` (seed the heap-min used
at `mmap_index.rs:313`), thread it through
`SequentialSeismicBackend._fan_out`. Metrics: per-shard blocks-evaluated (add
a counter) + traverse p50 on 2 shards, ≤40 queries; top-k equality vs today's
sequential run. Cost: small Rust+Python change + test run; no rebuild. Kill:
blocks-evaluated in shard 2 falls <20% (warm-up loss is negligible and the
change isn't worth the API surface).

**E5 — semantic-ordered forward layout (converter-level, the expensive one —
only after E1–E3 land).** Extend `convert_shard_to_mmap.py` with a permutation
pass: order docs by a cheap semantic key (section‖year‖top-SPLADE-term, no ML)
and remap all packed-posting offsets + doc-mapping. Metrics: majflt/query and
pages-touched (RssFile delta) vs the unpermuted shard, SAME queries, parity
bit-identical (hard gate — any score drift is a bug). Cost: converter work +
one shard re-convert (~10 GB RSS, minutes) + bench hours; the riskiest
engineering of the five. Kill: majflt/query reduction <15% — then forward
locality can't be bought by ordering and the semantic-docid design loses its
page-economics argument (its routing argument, §1.4, stands independently).

> **Q6 SIMULATION GO (2026-07-09, container).** The pre-build sim doc 12 §Q6
> gates this behind ran on shards 1–2, both geometries, n=100, real
> scored-candidate sets via the fork's new `search_visited` hook
> (`q6_e5_coaccess_sim.py`, `q6_e5_coaccess_sim_20260709.json`): the
> **buildable, query-independent `block_walk` order (first-touch over the
> canonical posting-pack walk — no semantic key needed) simulates to
> 0.376–0.400× unique forward pages/query** (worst shard 0.393, bar ≤0.45),
> ~identical on held-out queries; the query-log ceiling (`coaccess_sig`) is
> only modestly better at 0.345–0.358, so the index-derived order captures
> most of the win; random control 1.01; 64KiB-cluster ratios 0.35–0.37
> (fault-around makes the model conservative). **Candidates/query/shard
> measured for the first time at 150M: mean ~17.8k, p50 ~16.8k, range
> 5.2k–36.9k** — §3.2's 60–90k envelope was ~4× high, but its ~2
> pages/candidate model is exact (2.03 measured). → E5 converter is GO;
> the permutation key should be the posting-pack walk order, not the
> semantic key this entry originally guessed.

---

## 5. What this audit deliberately did NOT do

- No index build, conversion, or full-spool read (rules 3–4); the only data
  touched read-only were one spool line, `meta.sqlite` schema + 2 rows, and
  JSON manifests/result files.
- No re-measurement of anything already measured — all numbers above cite
  their original result files and dates.
- No implementation of any proposal (rule: report ends the run).

**Cross-references:** `02_GO_NO_GO_GATES.md` (gate states),
`06_FINDINGS.md` (results ledger), `07_G3_RAM_FIX_PLAN.md` §1 (byte split),
`08_LATENCY_RESEARCH.md` (latency levers §A–§E),
`docs/seismic_sequential_serving/01_ARCHITECTURE.md` (mechanisms A/B/C),
`docs/semantic_docid_ingest/` (the sharding-key design §1.4 defers to).
