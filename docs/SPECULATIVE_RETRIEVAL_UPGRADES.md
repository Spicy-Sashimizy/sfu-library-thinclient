# Speculative retrieval — draft/verify upgrades for the thin-client search path

**Status:** ACTIVE

Written 2026-09-25 from a cloud-session analysis (session_014FpgxBveYndPQDX4tVxPTe),
reshaped the same day against the serving code and the serve query-log. Both
gating measurements are MEASURED 2026-09-25 (§3 from the serve log, §3b from a
120-topic pass over the serving index); #0 is IMPLEMENTED and MEASURED
2026-09-27 (3 × 3-pass A/B: parity 120/120 every pass, duplicate hydrate
3.98% → 0, hydrate p50 −1.4 ms vs the ~7 ms *est.*; kept, it is free), #2 is IMPLEMENTED behind a default-OFF gate and DEFERRED
(overlap@10 0.433 < ~0.7), #4 is **CLOSED MEASURED 2026-09-25** (cold −4.4%
< 20% bar, warm slower; code archived, §4 row 4), #1 is IMPLEMENTED and
MEASURED 2026-09-25 in a 3 × 3-pass A/B (§4 row 1, §6 step 4): byte-parity
360/360, CE reuse 55%, but it **fails the 128 ms cache-miss p50 bar** (≈ 80 ms
attributable, total p50 not reduced), so its gate stays OFF; #5 and #6 are
DEFERRED (§4b).
Open operator decisions are in §7. All benefit figures are *est.* unless a
results file is named.

## 1. The analogy, made precise

Speculative decoding runs a cheap *draft* model ahead of the expensive *target*
model, verifies the draft's proposals in one parallel pass, keeps the accepted
prefix, and guarantees the output distribution is unchanged. The thin-client
search path has the same shape once the unit of work is chosen correctly:

| Speculative decoding | This search path |
|---|---|
| Draft model | The BM25F leg (tantivy). It is the cheapest leg and already runs first. |
| Target model | The rest of the pipeline: SPLADE/SEISMIC leg → RRF → per-candidate work → cross-encoder (CE). |
| A drafted token | One unit of **per-(query, candidate) work**: hydrate (meta row + abstract, with an OpenAlex round-trip for misses), the stage-1 embedding of the candidate text, and the CE pair score. Each is a pure function of (query, doc) and independent of the rest of the pool. |
| Verification | Set membership. When the fused pool is known, a drafted candidate that is in it keeps its precomputed work; one that is not is discarded. No rejection sampling is needed because the ranker never depends on *which* candidates were speculated. |
| Acceptance rate | overlap@k between the BM25F top-k and the fused RRF top-k. |
| "Same distribution" guarantee | The final response is byte-identical to the non-speculative path. Any lever that changes the output is not speculation and is out of scope here (row 8 of the table). |

Two consequences follow directly from the analogy:

- **Speed-up is bounded by acceptance × overlapped work**, exactly as in decoding. So the two numbers that decide everything are the acceptance rate (measurement a) and how much of the wall-clock is per-candidate work that could have started early (measurement b).
- **Draft quality only affects speed, never correctness.** A low-overlap query wastes the speculated work and pays nothing else. That is why the levers below carry "Output risk: none" and why the WI-18 result-cache speculation was the wrong target: an exact-match cache has an acceptance rate of 0 or 1 per query, and it measured 0 in literal mode (`data/eval_results/speculation_ab_2026-07-28.json`). Candidates, not result sets, are the drafted tokens.

## 2. The serving path as it runs (verified in code 2026-09-25)

Both the GUI (`search_academic_structured`) and the MCP tool
(`_handle_search_academic`) in `src/lib/tools.py` go through the same
`FederatedSearchRouter.search` in LOCAL_RRF mode:

1. `ThinClientRetriever.search(mode="bm25f")` runs the leg, records the leg
   ms, **then hydrates its own top-k** (`_hydrate` → `fetch_abstracts`:
   sidecars first, OpenAlex for misses, 50 ids per request, 15 s timeout).
2. `ThinClientRetriever.search(mode="splade")` does the same, serially,
   hydrating its own top-k. Candidates present in both legs are hydrated twice.
3. `_rrf_merge` (federated_search.py) fuses the two lists, k=60.
4. `_maybe_rerank`: stage 1 encodes the query plus every pooled candidate's
   title+abstract with the local embedding model (`compute_similarity`) and
   builds the composite; stage 2 scores the RRF top-20 with the CE
   (`rerank_with_crossencoder`, `_CE_CANDIDATE_POOL` = 20); LambdaMART when on.

The serve query-log (`src/lib/serve_query_log.py`) records `leg_ms.bm25f`,
`leg_ms.splade`, `leg_ms.dense` and `leg_ms.total`. The leg figures stop
**before** hydrate; `total` spans router.search plus `_maybe_rerank`. So
`total − Σ legs` is, by construction, hydrate ×2 + RRF merge + stage-1
embedding + CE + LambdaMART + executor hand-off. That difference is the
"~1.8 s gap" the original analysis could not attribute, and it was already on
disk.

## 3. Measurement (b), first cut — MEASURED 2026-09-25

Script: `scripts/experiments/speculation_gap_from_serve_log.py`. Results:
`data/eval_results/speculation_gap_from_serve_log_2026-09-25.json`. Input:
`data/eval_results/serve_query_log.jsonl`, 2,260 rows; 1,037 result-cache hits,
249 rows without leg timings and 14 warm-up rows (a leg alone > 10 s) excluded,
leaving 960 served cache-miss searches from 2026-07-18 and 2026-07-28.

| Bucket | n | total p50 | legs p50 | gap p50 | gap p95 | gap share p50 |
|---|---|---|---|---|---|---|
| 2026-07-18 user | 375 | 2,698 ms | 1,744 ms | 1,049 ms | 1,428 ms | 0.38 |
| 2026-07-18 speculative (WI-18) | 92 | 2,396 ms | 1,187 ms | 1,149 ms | 1,460 ms | 0.47 |
| 2026-07-28 user | 277 | 2,282 ms | 1,009 ms | 1,240 ms | 1,622 ms | 0.53 |
| 2026-07-28 speculative (WI-18) | 216 | 1,951 ms | 683 ms | 1,235 ms | 1,824 ms | 0.64 |
| **all** | **960** | **2,429 ms** | **1,320 ms** | **1,150 ms** | **1,618 ms** | **0.46** |

What this settles:

- The unattributed part of a cache miss is **~1.15 s p50, ~1.6 s p95**, not
  1.8 s; the 1.8 s estimate assumed warm engine legs, and the July legs were not
  warm (p50 0.7–1.7 s).
- The gap is **stable while the legs vary 2.5×** across buckets. A stable
  ~1.1–1.2 s with a tight p95 is the signature of a fixed post-retrieval
  pipeline cost, not of I/O tail or OpenAlex retry variance. That is the best
  case for speculation: it is per-candidate work that can start the moment
  the draft leg returns.
- Roughly **half of every cache miss** is therefore work that speculation can
  overlap with the SPLADE/SEISMIC leg, before any cold/warm engine gains.

What it does not settle: the split of the gap between hydrate, stage-1
embedding and CE. The CE pass alone is 25.5 ms for 20 pairs on 16 cores
(`docs/THIN_CLIENT_SWAP.md`), so hydrate and the stage-1 embedding of up to
40 candidate texts dominate *est.*; the split is step 2 below. The July rows
also predate the 2026-08 SEISMIC warm-cache work, so the leg figures are not
current; only the gap is being used from them.

Engine reference points (`data/eval_results/f4_floor_ab_on_20260817.json`,
SEISMIC 8-shard mmap, 100 queries × 3 passes): warm p50 63 ms / p95 95 ms;
cold p50 968 ms / p95 6.8 s. Result-cache hit 5 ms; cache-on miss p50 1,979 ms;
cache-off cold p50 3,081 ms (`speculation_ab_2026-07-28.json` arms B, D, A).

## 3b. Measurement (a) and gap split — MEASURED 2026-09-25

**What.** One offline replay of the served path per topic, run twice back to
back (run 1 "first", run 2 "repeat" = warm, primary). The objects came from
`lib.tools._get_federated_router()` (same env, same flags as serving), and each
run followed `search_academic_structured`: `router.search(top_k=20)` forced to
LOCAL_RRF → `_cache_works` → `_maybe_rerank(fused, q, 10)`. Timers were
monkeypatched in the harness process only. Leg ms come from the same
`_record_leg` counters the serve log diffs, so the gap below matches the serve
log's definition. Provenance came from `_rrf_fuse(..., with_provenance=True)`,
the fusion `search_rrf_detailed` uses, applied to the captured leg lists, so no
second retrieval was needed. Its top-20 set equals the served DOI-keyed
`_rrf_merge` set on 116/120 topics (DOI dedup), and the order matches on 114.
Overlaps below use the **served** fused list.

- Dataset: the 120 `topics[*].natural` queries of
  `data/eval_results/dense_ablation_qrels_20260817.json`. 8/120 would route to
  LIVE_API if served; they were forced to LOCAL_RRF like the rest.
- Config (recorded in the results file): `rerank_enabled`, `crossencoder_enabled`, `rrf_enabled`
  (container env `SFU_FEATURE_RRF_ENABLED=true`; the code default is off);
  `lambdamart_enabled` **off**; SEISMIC backend, federation `parallel`,
  `SFU_SEISMIC_STAGE_DIR=/var/tmp/seismic_stage`; index
  `data/thinclient_index` (tantivy + meta.sqlite on 9p); torch device **cuda**
  for the stage-1 embedding and the CE; fetch_k 20, limit 10.
- Scripts: `scripts/experiments/speculation_acceptance_rate.py` (the single
  index pass) and `scripts/experiments/speculation_gap_split.py` (analysis of
  the raw file, no index).
- Results: `data/eval_results/speculation_acceptance_rate_2026-09-25.json`,
  `data/eval_results/speculation_gap_split_2026-09-25.json`, raw per-run
  records `data/eval_results/speculation_pass_raw_2026-09-25.jsonl`.
- Rankings were deterministic: run 1 and run 2 produced identical fused and
  final lists on 120/120 topics.

**Acceptance (a), n = 120**

| Metric | mean | median | p10 | ≥ 0.5 | ≥ 0.7 |
|---|---|---|---|---|---|
| overlap@20, BM25F top-20 vs served fused top-20 (acceptance for #1/#3) | **0.550** | 0.55 | 0.50 | **100%** | 2.5% |
| overlap@10, BM25F top-10 vs post-CE top-10 (gate for #2) | **0.433** | 0.40 | 0.20 | 45.8% | **9.2%** |
| context: BM25F top-10 vs fused top-10 (pre-CE) | 0.537 | 0.50 | 0.50 | 96.7% | 8.3% |
| context: fused top-10 vs post-CE top-10 | 0.557 | 0.50 | 0.40 | 85.0% | 21.7% |
| context: BM25F top-20 vs SPLADE top-20 | 0.080 | 0.05 | 0.00 | 0% | — |

Provenance of the 2,400 fused top-20 slots (`rrf_legs`): BM25F only 47.0%,
SPLADE only 45.1%, both legs 8.0%. On natural-language queries the two legs
barely overlap. With disjoint legs, RRF k=60 interleaves them, so each leg's
top ~10 lands in the fused top-20. That puts acceptance@20 at 0.50 **by
construction**, plus about half the leg overlap. It is not evidence that the
BM25F draft is good.

**Gap split (step 2).** The gap is `total − (bm25f leg + splade leg)`, the
serve log's definition. Warm = run 2 (primary); first = run 1.

| Stage | warm p50 | warm p95 | warm share of gap | first p50 | first p95 | first share |
|---|---|---|---|---|---|---|
| hydrate, BM25F leg | 85 ms | 99 ms | 28.5% | 180 ms | 220 ms | 31.8% |
| hydrate, SPLADE leg | 85 ms | 103 ms | 28.3% | 180 ms | 238 ms | 33.6% |
| · of which OpenAlex remote (both legs) | 165 ms | 188 ms | **54.9%** | 168 ms | 200 ms | 30.3% |
| · of which local abstract sidecars (both legs) | ~4 ms | ~6 ms | ~1% | ~166 ms | — | ~29% |
| · of which meta rows (both legs) | ~1.4 ms | ~2 ms | <1% | ~27 ms | — | ~5% |
| stage-1 embedding (`_compute_semantic_scores`, 20 docs) | 63 ms | 205 ms | 29.1% | 123 ms | 370 ms | 28.4% |
| stage-1 composite (rest of `rerank_results`) | 0.4 ms | 0.6 ms | 0.2% | 0.2 ms | 0.7 ms | 0.1% |
| CE (`rerank_with_crossencoder`, 20 pairs) | 36 ms | 86 ms | 13.9% | 31 ms | 76 ms | 5.9% |
| `_rrf_merge` + `_cache_works` + unattributed | < 0.2 ms | < 0.5 ms | < 0.1% | < 1 ms | 2 ms | 0.2% |
| LambdaMART | flag off | — | 0 | — | — | 0 |
| **gap** | **276 ms** | **453 ms** | 100% | **525 ms** | **823 ms** | 100% |
| legs (BM25F + SPLADE) | 2,580 ms | 4,133 ms | — | 5,722 ms | 8,314 ms | — |
| · BM25F leg | 2,195 ms | 3,360 ms | — | 3,489 ms | 5,493 ms | — |
| · SPLADE leg | 355 ms | 1,130 ms | — | 2,015 ms | 3,692 ms | — |
| total | 2,876 ms | 4,460 ms | — | 6,265 ms | 9,019 ms | — |

Shares are aggregate (Σ stage / Σ gap). Sub-row shares are approximate
(sum of the per-leg means). Per-query median shares are in the results file.

- **The remote-abstract call failed on every query.** 2,929 ids were sent to
  OpenAlex (p50 26 per query) and **0 were returned**. Every call got
  HTTP 429: the anonymous daily budget for this IP was exhausted, and
  `_fetch_remote_abstracts` sends `mailto` but no API key. So ~165 ms of the
  warm gap is two failed round trips, and those candidates reach the CE
  without an abstract. The serve log's July remote cost (when the fetch
  returned data) cannot be reproduced on this host today.
- **Duplicate hydrate:** 191 of 4,800 hydrated ids (**4.0%**) were hydrated
  twice. That is a mean of 1.6 per query (p95 5), and 75/120 queries had at
  least one. Lever #0 saves ~4% of hydrate, *est.* ~7 ms warm.
- **The gap here is ~0.28 s p50, not the serve log's ~1.15 s (§3).** The
  cause of the difference is not established by this run. Candidate causes:
  the CUDA-resident embedding and CE, 20 vs up to 40 pooled texts, and the
  remote call now failing fast instead of fetching.
- **On this host the BM25F "draft" leg is the slowest leg** (2.2 s warm p50
  vs SPLADE 0.36 s). That breaks the §1 premise that the draft is the cheap
  leg that runs first. The likely cause is tantivy/meta on 9p plus
  concurrent agents on the same host (not isolated). Because the legs run
  serially BM25F → SPLADE, lever #1 can only overlap speculated work with
  the SPLADE leg (~355 ms warm p50).

**Decisions under the §4/§6 bars**

- **#1 / #3 proceed on the letter of the bar.** Acceptance@20 = 0.55 ≥ ~0.5,
  and 100% of topics are ≥ 0.5. However, the 0.5 is structural (disjoint
  legs, see above), and the overlappable work is small. The ceiling is
  acceptance × speculated work: 0.55 × (stage-1 88 ms + CE 42 ms warm means),
  plus the BM25F leg's own ~86 ms hydrate moved off the critical path. That
  is **≈ 0.16 s per cache miss *est.*, ≈ 5% of the 2.9 s warm total**, and
  more than half of it is the failing OpenAlex call. Step 4 should carry this
  ceiling into its pre-registered bar. Fixing the remote-abstract 429 is not a
  speculation lever, but the numbers make it the largest single item in the
  gap.
- **#2 (SSE draft → final swap) does not proceed.** overlap@10 vs the post-CE
  top-10 = 0.43 mean, and only 9.2% of topics are ≥ 0.7, against a bar of
  ~0.7. Step 5 stays unmet.
- **#0 (hydrate once)** is still correct but worth ~4% of hydrate. Do it only
  if it falls out of #1's plumbing.
  *Measured 2026-09-27 (§4 row 0): duplicates 3.98% of hydrated ids, hydrate
  p50 −1.4 ms.*

## 4. Levers, by draft/verify role

| # | Lever | Draft/verify role | Applies to | Benefit (*est.* unless noted) | Output risk | Gate | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | **Speculative per-candidate work** | Draft = BM25F top-20; speculated work = hydrate + stage-1 embedding + CE pair score; verify = membership in RRF top-20 | GUI + MCP | Up to acceptance × ~1.15 s per cache miss (§3); the largest lever on the table | None by construction (per-candidate reuse over fixed-shape scoring, §5 risk 1) | (a) acceptance ≥ ~0.5 at k=20 | **IMPLEMENTED 2026-09-25, MEASURED 2026-09-25 (multi-pass A/B): parity bar MET, p95 bar MET, p50 bar FAILED → gate stays OFF.** Early draft CE (commit 6d83760a): the draft's CE batch now starts on its own thread at draft start, alongside the stage-1 draft, instead of after it. A/B: `scripts/experiments/eval_speculative_multipass_ab.py`, `data/eval_results/speculative_multipass_ab_2026-09-25.json`; 120 `natural` topics, warm-up then OFF/ON interleaved × 3 (360 requests per arm), serving flags, CUDA, remote abstracts from the harness memo (0 OpenAlex calls). **Parity:** every pass final and fused list byte-identical to the first OFF pass, 120/120 in all 6 passes. **Reuse per ON pass (identical all 3):** CE hits 1,323/2,399 candidates drafted (55.1%, was 194 = 8% before early CE), stage-1 hits 1,323/2,399 (55.1%), i.e. both at the acceptance ceiling (1,321 accepted); drafts that never ran a CE batch 0/120 (was 102/120); `real_ce_waited` 0; `draft_ce_covered` 120. **Attributable (pooled p50, OFF → ON):** stage-1 stage 229.5 → 184.8 ms (−44.7), CE stage 42.9 → 15.8 ms (−27.1), `_maybe_rerank` 282.7 → 202.9 ms (**−79.8 ms**). **Total cache miss (pooled p50/p95):** OFF 5,031 / 7,130 ms, ON 5,155 / 7,132 ms: p50 **+125 ms (worse)**, p95 ratio 1.0002 (bar ≤ 1.05, met); per pass p50 OFF 5,137 / 5,001 / 5,163, ON 5,194 / 5,162 / 5,078 ms. Retrieval (the legs) is 4.8–4.9 s of the ~5.0 s and moved +97 ms pooled p50 ON vs OFF, larger than the whole attributable saving, so the total cannot resolve an 80 ms effect. **Verdict vs the 128 ms bar: FAIL** on both readings (attributable 80 ms < 128 ms; total p50 not reduced). The CE is now fully reused where the draft is accepted, and stage-1's remainder (≈ 9 of 20 docs) still costs one fixed-shape batch; the ceiling at 55% acceptance is below the bar. `cache_hit`/`speculative` counters untouched (WI-18 and result-cache counters unchanged across the run; unit-tested). `cache_hit`/`speculative` counters untouched by construction (tested). `src/lib/speculative_rerank.py` behind `SFU_SEARCH_SPECULATIVE_RERANK` (literal `1`, default OFF). Spike commit 829d8062 reused whole calls only (exact-batch memoisation); since the owner accepted fixed-shape batching (§7 item 1) every drafted (query, doc) stage-1/CE score is reused whenever that candidate is in the fused pool, and only the remainder is scored. Fixed shape (both paths): CE (10, 256) with per-row pooler/classifier head, embedder (11, 256), dummy rows fill short batches, cosine via exactly-rounded `math.fsum`. Bit-identity MEASURED 2026-09-25: alone / batch-of-20 / mixed / reversed / shuffled / 7-pair remainder all bit-identical for both models on CPU (torch threads 1, 8, 16, and identical across thread counts) and CUDA (`scripts/experiments/ce_batch_invariance_check.py --mode fixed`, `data/eval_results/ce_batch_invariance_fixed_{cpu_t1,cpu_t8,cpu_t16,cuda}_2026-09-25.json`, `ce_batch_invariance_fixed_cpu_threads_compare_2026-09-25.json`; legacy contrast `ce_batch_invariance_legacy_{cpu_t8,cuda}_2026-09-25.json`). Hydrate is not speculated (the BM25F leg arrives hydrated) |
| 3 | Speculative hydrate only | #1 without embedding/CE; verify = membership | GUI + MCP | The hydrate share of the gap (unknown until step 2) | None | as #1 | Not needed: risk 1 resolved by fixed-shape scoring (§5 risk 1, 2026-09-25), so #1 keeps per-candidate embedding/CE reuse. As of 2026-09-25 the served BM25F leg already arrives hydrated and #0 dedups the second leg's hydrate, so #3 has nothing left to speculate on the router path unless hydrate moves out of `ThinClientRetriever.search` |
| 0 | Hydrate once per request | Not speculation: memoise `fetch_abstracts`/`_meta_rows` across legs so candidates in both legs are not hydrated twice | GUI + MCP | The duplicated-hydrate share; free | None (fused output byte-identical, fixture-tested) | none | **IMPLEMENTED 2026-09-25, MEASURED 2026-09-27 (multi-pass A/B): parity MET, saving ≈ 1.4 ms p50 per cache miss, below the ~7 ms *est.*; kept (free, output byte-identical, 3.9% fewer remote-abstract ids).** A/B: `scripts/experiments/eval_hydrate_once_ab.py`, `data/eval_results/hydrate_once_ab_2026-09-27.json`; 120 `natural` topics, ON warm-up then OFF/ON ABBA-interleaved (OFF, ON, ON, OFF, OFF, ON; 360 requests per arm), serving flags (`SFU_SEARCH_SPECULATIVE_RERANK` unset = OFF), CUDA, run under `/tmp/sfu_latency_measure.lock`. OFF = the retriever instance's `hydrate_scope` replaced by `contextlib.nullcontext` (pre-#0 path); ON = current code. Remote abstracts: per-id stub (the 2026-09-25 list-keyed memo is gone and would answer the arms differently), **0 OpenAlex calls**, so remote wall time is not in the hydrate figures; the remote saving is reported as ids. **Parity:** fused and final lists byte-identical to the first OFF pass, 120/120 in all 6 passes. **Calls per request (both arms):** `_hydrate` 2.0, `_meta_rows` 2.0, `fetch_abstracts` 2.0, remote 1.958 — #0 does not remove a call, it shrinks the second leg's id list. **Ids per pass OFF → ON:** `_meta_rows`/`fetch_abstracts` 4,800 → 4,609 (−191), remote 2,929 → 2,816 (−113, −3.9%); duplicate-hydrate share **3.98% → 0** (191/4,800, identical to §3b's 4.0%; mean 1.59 duplicate ids per request, p95 5, 75/120 topics with ≥ 1). **Hydrate stage (both legs, pooled p50/p95):** OFF 130.2 / 171.3 ms → ON 128.8 / 165.9 ms (**−1.4 / −5.5 ms**); per pass p50 OFF 130.2 / 131.6 / 128.6, ON 127.6 / 129.7 / 128.1 ms; paired per-topic median-over-passes OFF − ON: median 2.2 ms, mean 0.6 ms, ON faster on 71/120. **Total cache miss (pooled p50/p95):** OFF 4,960 / 6,872 ms → ON 4,850 / 6,836 ms (−111 / −35 ms), but retrieval (the legs, which #0 does not touch) moved −71 ms p50 in the same direction and the paired per-topic total delta has median 15.6 ms, mean −10.2 ms, ON faster on 61/120: the total cannot resolve a ~1 ms effect, so the attributable figure is the hydrate stage. **Verdict vs the ~7 ms *est.*:** the duplicate share is exactly as estimated (4%) but the time saved is ~1.4 ms, not ~7 ms: hydrate cost is not per-id linear (the second call on a shorter list costs about the same), and the §3b estimate included failing OpenAlex round trips that #0 does not remove (remote calls per request unchanged). `cache_hit`/`speculative` counters untouched (WI-18, result-cache and speculative-rerank counters identical before/after the run). `ThinClientRetriever.hydrate_scope()` (commit c9974a35); `search_rrf`/`search_rrf_detailed` are scoped. The serving GUI/MCP path is covered as of commit 829d8062: `FederatedSearchRouter.search` (LOCAL_RRF) runs both legs inside `getattr(retriever, "hydrate_scope", nullcontext)()` (fixture test `test_router_enters_hydrate_scope_once_per_local_rrf_request`). Invariants: `docs/CODE_INVARIANTS.md` §retriever "Hydrate once per request" |
| 2 | BM25F draft → final swap (SSE) | Draft *shown*, not just computed: emit BM25F+hydrate at ~50 ms labelled preliminary, swap to the final list only when idle; pin a hovered card | GUI only | Time-to-first-card ~2 s → ~50 ms; time-to-final unchanged | None to results; visible reshuffle when draft ≠ final; off under `SFU_SEQUENTIAL_MODE` | (a) overlap@10 vs the post-CE top-10 ≥ ~0.7; reshuffle rate | **IMPLEMENTED 2026-09-25, EFFICACY UNMEASURED** behind `SFU_SEARCH_DRAFT_STREAM` (default OFF): `POST /api/search_stream` + GUI idle-only swap (`docs/CODE_INVARIANTS.md` §"Draft → final search stream"). Stays OFF until (a) clears ~0.7 and the step-5 bars are measured **Gate stays OFF — measurement (a) 2026-09-25: overlap@10 vs post-CE top-10 = 0.433 mean (9.2% of topics ≥ 0.7), below the ~0.7 bar (§3b); DEFERRED until a better draft leg exists.** |
| 4 | Term-prefix block prefetch while typing | Draft = SPLADE terms of the typed prefix; speculated work = `madvise(WILLNEED)` on their SEISMIC blocks; verify = the final query reuses the terms | GUI (typing signal) | Cold traverse 968 → toward 63 ms for terms already typed | None | Cold-vs-warm p50 with/without; wasted I/O; **must include a RAM-resident arm** where the ordinals-cliff result predicts a no-op (`docs/ORDINALS_RESIDENCY_CLIFF.md`) | **CLOSED MEASURED 2026-09-25** — cold traverse gain 4.4% (paired median) vs the ≥ 20% bar, and the RAM-resident arm is slower, not neutral. Run: shard 0 (staged local disk), n=40, prefix = first 60% of words, 300 ms lead, cap 32 MiB, sequential federation, per-file fadvise eviction (mincore-verified 0 B resident), parity 40/40. Traverse p50/p95: cold_none 1658.9/2460.3 ms, cold_prefetch 1590.3/1911.1 ms (paired Δ median −65 ms, better on 36/40); warm_none 27.9/45.6 ms, warm_prefetch 35.6/54.8 ms (paired Δ median +6.5 ms, worse on 38/40; this arm also carries the 300 ms idle gap, so the regression is advice cost and/or the gap, not isolated). Major faults p50 cold 465.5 → 447.5 (−4%), warm 0 → 0. Advised 5.87 MB/search, wasted 1.59 MB/search (27%), plan (prefix SPLADE encode) p50 22.2 ms. Why: the reachable unit is posting lists (~6 MB); the cold wall is dominated by forward-index pages (~85% of bytes) that cannot be planned. Results `data/eval_results/block_prefetch_ab_2026-09-25.json`; harness archived to `scripts/archive/eval_block_prefetch.py`, module + tests to `spike/archive/block_prefetch/` (no live path imported it; gate removed, `docs/ENV_GATES.md`). |
| 5 | Session-level prefetch | Draft = a search's top-10; speculated work = warm their follow-up payloads | MCP | Abstracts/full-text: none, already served (§4b); TLDR/references: one S2 round trip per follow-up, *est.* | **Can change output**: prefetch calls share the S2 client's circuit breaker and 429 backoff with user calls (§4b) | Trace analysis: how often a follow-up touches the previous top-10 — **UNMEASURABLE 2026-09-25, n=0** (§4b) | **DEFER 2026-09-25** (no follow-up traces exist; needs the `ids` field of §4b first) |
| 6 | Partial result + continuation handle | Draft returned to the *agent* with a job id; verify = the agent decides whether to wait | MCP | Agent proceeds on the draft | Non-deterministic agent behaviour; eval noise | Traces showing multi-search sessions where a rough first pass changes the next query — **none exist 2026-09-25**: 0 MCP search sessions in any trace; result overlap not computable from `result_fp` (§4b) | **DEFER 2026-09-25** (needs MCP-path search traces with unhashed top-10 ids) |
| 7 | Speculative SPLADE encode | — | — | ~20 ms max | — | — | Skip |
| 8 | Early-exit on leg agreement | Not speculation: skips the target model | — | — | **Changes output** | — | Don't |
| 9 | Draft into the result cache (WI-18 literal) | Wrong unit of work (result set, not candidate) | GUI | — | — | Measured 2026-07-28: 0% hit | Dead |

MCP note: a tool call is one request and one result, so #2 and #6 are the only
levers that change the client contract. #0, #1, #3 and #5 are server-internal
overlap with identical output and cut MCP wall-clock as much as GUI wall-clock.

## 4b. MCP follow-up traces — MEASURED 2026-09-25

Script: `scripts/experiments/mcp_followup_trace_analysis.py`. Results:
`data/eval_results/mcp_followup_trace_analysis_2026-09-25.json`. Read-only;
no index access.

**Trace sources on disk (all of them):**

| Source | Rows | Tool name | Session | Doc/result ids | MCP follow-up calls |
|---|---|---|---|---|---|
| Serve query-log `data/eval_results/serve_query_log.jsonl` | 2,267 | no | per process | `result_fp` only (sha1 of ranked list) | 0 — written only by GUI `search_academic_structured` and the HTTP result-cache hit path; MCP text handlers never call `log_serve_query` |
| Metrics log `logs/mcp_metrics.jsonl` (`SFU_METRICS_LOG_PATH`) | 3 (2026-06-08, all `search_academic`) | yes | no | no | 0 |
| Engagement log `logs/engagement_log.jsonl` (backs `web/src/analytics.jsx`) | file absent | — | — | — | 0 |
| tools query log (`SFU_FEATURE_QUERY_LOG_ENABLED`) | no path configured, no file | handler | no | top-10 DOI | 0 (searches only) |
| `data/eval_results/*` (Playwright/eval drives) | no file names any of `get_paper_summary` / `get_references` / `get_full_text_link` | — | — | — | 0 |

**Q1, follow-up hits the previous top-10: UNMEASURABLE, n=0.** No trace
records a follow-up tool call with its doc id. One field fixes it: `ids` on the
`_persist_metric` line (search tools: ranked top-10 `openalex_id`/`doi`;
doc-level tools: `normalize_doi()` of the argument). Under stdio one process is
one client conversation; for HTTP also add a per-process `session`, as the serve
log already mints.

**Q2, second search in a short window: harness data only.** Serve log,
speculative rows excluded: 1,958 submitted searches, 35 sessions (14 with ≥ 2
searches), 1,923 consecutive pairs; 1,911 pairs (99.4%) within 30 s, 1,424 of
them with a different query, 2 of those with an identical `result_fp`. The
multi-search sessions are the 2026-07-18 and 2026-07-28 speculation A/B
benchmark processes replaying topic lists through `/api/search`, so gaps and
query order describe the driver, not agent refinement. Jaccard is not
computable: only the fingerprint is logged, so unequal fingerprints can mean
any overlap in [0, 1). Note: `serve_query_log.py`'s docstring says `result_fp`
hashes the *sorted* id list; the code hashes the list in rank order.

**Q3, does `_cache_works` already serve follow-ups (from `src/lib/tools.py`):**

- `get_full_text_link` calls `_lookup_work` first. Every search handler calls
  `_cache_works` on the full `fetch_k` list before rerank, so a top-10
  follow-up already hits the cache with no remote call. `find_open_access`
  uses the same cache on its Unpaywall-miss path. **#5 is moot for these.**
- `get_paper_summary` never reads the works cache or any abstract. It always
  calls Semantic Scholar `get_tldr`. `get_references` always calls S2
  `get_references`. Neither is cached anywhere, so abstract prefetch would do
  nothing for them. The only thing #5 could warm is 10 remote S2 calls per
  search.
- Those calls share `SemanticScholarClient`'s circuit breaker and 429 backoff
  with user calls, so prefetch traffic can open the breaker and turn a real
  `get_paper_summary` into "No TLDR available". That breaks the
  identical-output requirement unless the prefetch gets its own client and
  breaker. It also spends S2 budget on follow-ups at a rate nobody has
  measured.

**Verdicts:** #5 **DEFER** and #6 **DEFER**. Nothing was built:
`src/lib/session_prefetch.py` was not written and there is no
`SFU_SESSION_PREFETCH` gate. Reopen either lever only after the metrics-log
`ids` field (plus `session` for HTTP) has collected real MCP sessions, and
after Q1 shows a top-10 follow-up rate high enough to pay for the S2 calls.

**Q1 instrumentation — IMPLEMENTED 2026-09-25 (commit 38e0c531), data not yet
collected.** Every `SFU_METRICS_LOG_PATH` line (`tools._persist_metric`, both
transports) now carries `session` and `ids`. `session` is a per-process 8-hex
id (`secrets.token_hex(4)`, the `serve_query_log._rand_id` style); the HTTP
`call_tool` uses the request's `mcp-session-id` header instead when one is
sent. The session manager runs `stateless=True`, so HTTP lines usually share
the process id, and only stdio gives one id per conversation for sure. `ids`
holds the ranked top-10 (after rerank) for `search_academic`,
`search_by_author`, `search_by_topic`, the S2 fallback and Europe-PMC
`search_biomedical`: `normalize_doi(doi)`, else `openalex_id` (Europe PMC:
DOI, else `pmid:<n>`). Doc-level tools (`get_paper_summary`,
`get_references`, `get_full_text_link`, plus `get_citations`,
`find_open_access`, `search_by_doi`) log `[normalize_doi(arg)]`. Every other
tool logs `null`. Handlers pass ids through a ContextVar that
`handle_tool_call` sets, so tool text output is byte-identical (pinned by
`test_output_text_unchanged_by_metrics_log` in `src/tests/test_metrics_log.py`;
55/55 pass across `test_metrics_log.py` + `test_tools_unit.py`, 2026-09-25).
Q1 becomes: per `session`, the fraction of doc-level calls whose `ids[0]` is
in the `ids` of the most recent earlier search line. Levers #5/#6 stay DEFER
until real MCP sessions have been logged with
`SFU_METRICS_LOG_PATH=logs/mcp_metrics.jsonl` and that rate has been measured.

## 5. Risks specific to this pipeline

1. **Batch invariance of pair scores.** #1 reuses CE scores computed in a
   batch of 20 drafted candidates inside a final ranking that would otherwise
   have been scored in one batch of 20 fused candidates. Torch CE outputs can
   differ at floating-point level with batch composition (padding length), so
   byte-parity may fail even though the model is deterministic. Mitigations,
   in order of preference: score in fixed-shape batches (pad to a constant
   length) and verify parity on the 120-topic set; or re-score the whole pool
   whenever any drafted candidate was rejected, keeping only the hydrate and
   embedding overlap (#3). The same question applies to the stage-1 embedding.
   **MEASURED 2026-09-25 — the risk is real but small**
   (`scripts/experiments/ce_batch_invariance_check.py`,
   `data/eval_results/ce_batch_invariance_2026-09-25.json`): the serving torch
   CE scores the same pair differently alone vs in a batch of 20 (max |Δ|
   7.0e-6) and the stage-1 embedder likewise (max |Δ| 1.8e-7); two batches
   padded to the same longest length are bit-identical, so the variance is
   padding length, not order. No ranking changed in the sample, but
   byte-parity of per-candidate reuse cannot be guaranteed without fixed-shape
   padding on both paths. **OPERATOR DECISION**: accept fixed-shape batching
   (a one-time ~1e-6 change to gate-off scores, to be checked for zero ranking
   changes on the 120-topic set) and unlock per-candidate reuse, or keep the
   whole-batch design below and accept that reuse only fires when the fused
   pool equals the draft.
   **RESOLVED 2026-09-25 by fixed-shape scoring (owner decision, §7 item 1)**,
   replacing the spike's exact-batch memoisation (commit 829d8062). Both
   paths score in constant tensors: CE `(_CE_BATCH=10, 256)`, stage-1
   embedder `(_EMBED_BATCH=11, 256)`, short batches filled with dummy rows
   whose outputs are discarded; the CE's pooler + classifier run per row
   (on CPU a small-M GEMM gave rows 8–9 of a 10-row batch different bits,
   9.5e-7); cosine is `math.fsum` of float64 products. 256 is both models'
   configured max length, so nothing is truncated that the old path kept.
   **Bit-identity MEASURED 2026-09-25**: every arm (alone, batch of 20, mixed,
   reversed, shuffled, 7-pair remainder) bit-identical for both models on
   CPU at torch threads 1 / 8 / 16 — and identical across those thread
   counts, so no thread pin is needed — and on CUDA
   (`data/eval_results/ce_batch_invariance_fixed_*_2026-09-25.json`). The
   old path on the same text differs by up to 2.4e-6 (CE) / 1.8e-7
   (embedder) (`ce_batch_invariance_legacy_{cpu_t8,cuda}_2026-09-25.json`).
   Tests pin it with shape-sensitive fakes that keep parity only under fixed
   shape (`src/tests/test_speculative_rerank.py`); contract in
   `docs/CODE_INVARIANTS.md` §reranker "Fixed-shape scoring". **120-topic
   ranking parity MEASURED 2026-09-25**: 0/120 topics change top-10 order
   (max |Δ| CE 9.2e-6, stage-1 3.9e-7) and gate-on is byte-identical to
   gate-off on 120/120 (`data/eval_results/fixed_shape_parity_2026-09-25.json`). On CUDA the CE head runs batched
   (bit-identical there); the per-row head is CPU-only.
2. **Side effects inside hydrate.** `_hydrate` enqueues results into the dense
   warm cache (`self._dense_cache.enqueue`). Speculative hydrate must enqueue
   once per request, not once per draft plus once per final. Record as an
   invariant in `docs/CODE_INVARIANTS.md` when built.
3. **CE slot contention.** The WI-18 contract is single-slot CE. Speculated CE
   on the draft must not delay the final CE; if it does, #3 is the fallback.
4. **Cache honesty.** Speculated work must not flip `cache_hit` or the
   `speculative` flag semantics the serve log and the WI-18 counters rely on.

## 6. Plan, in order

| Step | What | Serving code? | Output | Status |
|---|---|---|---|---|
| 0 | Attribute the gap from the serve log | No | §3 | **DONE 2026-09-25** |
| 1 | **Acceptance rate**: on the 120-topic set (`data/eval_results/dense_ablation_qrels_20260817.json`, field `natural`), run `ThinClientRetriever.search_rrf_detailed` (returns each leg's ranking plus the fused list in one pass) and compute overlap@20 (BM25F vs RRF top-20 = acceptance for #1/#3) and overlap@10 vs the post-CE top-10 via `_maybe_rerank` (for #2). Report mean, p10 and the fraction of topics ≥ 0.5. | No | `scripts/experiments/speculation_acceptance_rate.py`, results under `data/eval_results/` | **MEASURED 2026-09-25** (§3b) |
| 2 | **Gap split**: replay the same 120 topics through `search_academic_structured` with perf counters around hydrate, stage-1 and CE (offline, dev container with the index) | No | Results file; decides #1 vs #3 | **MEASURED 2026-09-25** (§3b) |
| 3 | Implement #0 (hydrate once per request) with byte-parity test | Yes, small | Parity on 120 topics; gap delta | **IMPLEMENTED 2026-09-25, MEASURED 2026-09-27 (§4 row 0):** 120-topic parity 120/120 in all 6 passes (fused + final), duplicate-hydrate share 3.98% → 0, hydrate stage pooled p50 130.2 → 128.8 ms (−1.4 ms; p95 −5.5 ms), total cache-miss delta not resolvable (legs vary ±70 ms), 0 OpenAlex calls (`scripts/experiments/eval_hydrate_once_ab.py`, `data/eval_results/hydrate_once_ab_2026-09-27.json`). Saving below the ~7 ms *est.*; kept because it is free and byte-identical. Parity + call-count + no-leak also pinned on the synthetic fixture (`test_hydrate_memo_*`, `src/tests/test_thinclient.py`); router LOCAL_RRF path scoped in commit 829d8062 |
| 4 | Spike #1 (or #3 if risk 1 bites) behind `SFU_SEARCH_SPECULATIVE_RERANK`, default OFF. Pre-registered bars: byte-parity 100% vs OFF on the 120 topics; cache-miss p50 drop ≥ 0.8 × (acceptance × step-2 overlappable ms); p95 not worse than +5%; no change to `cache_hit` counters | Yes | A/B results file, `docs/THIN_CLIENT_SWAP.md` §serving path, `docs/ENV_GATES.md` | **IMPLEMENTED 2026-09-25, MEASURED 2026-09-25 (multi-pass A/B): parity bar MET, p95 bar MET, p50 bar FAILED → gate stays OFF.** Early draft CE (commit 6d83760a): the draft's CE batch now starts on its own thread at draft start, alongside the stage-1 draft, instead of after it. A/B: `scripts/experiments/eval_speculative_multipass_ab.py`, `data/eval_results/speculative_multipass_ab_2026-09-25.json`; 120 `natural` topics, warm-up then OFF/ON interleaved × 3 (360 requests per arm), serving flags, CUDA, remote abstracts from the harness memo (0 OpenAlex calls). **Parity:** every pass final and fused list byte-identical to the first OFF pass, 120/120 in all 6 passes. **Reuse per ON pass (identical all 3):** CE hits 1,323/2,399 candidates drafted (55.1%, was 194 = 8% before early CE), stage-1 hits 1,323/2,399 (55.1%), i.e. both at the acceptance ceiling (1,321 accepted); drafts that never ran a CE batch 0/120 (was 102/120); `real_ce_waited` 0; `draft_ce_covered` 120. **Attributable (pooled p50, OFF → ON):** stage-1 stage 229.5 → 184.8 ms (−44.7), CE stage 42.9 → 15.8 ms (−27.1), `_maybe_rerank` 282.7 → 202.9 ms (**−79.8 ms**). **Total cache miss (pooled p50/p95):** OFF 5,031 / 7,130 ms, ON 5,155 / 7,132 ms: p50 **+125 ms (worse)**, p95 ratio 1.0002 (bar ≤ 1.05, met); per pass p50 OFF 5,137 / 5,001 / 5,163, ON 5,194 / 5,162 / 5,078 ms. Retrieval (the legs) is 4.8–4.9 s of the ~5.0 s and moved +97 ms pooled p50 ON vs OFF, larger than the whole attributable saving, so the total cannot resolve an 80 ms effect. **Verdict vs the 128 ms bar: FAIL** on both readings (attributable 80 ms < 128 ms; total p50 not reduced). The CE is now fully reused where the draft is accepted, and stage-1's remainder (≈ 9 of 20 docs) still costs one fixed-shape batch; the ceiling at 55% acceptance is below the bar. `cache_hit`/`speculative` counters untouched (WI-18 and result-cache counters unchanged across the run; unit-tested). `cache_hit`/`speculative` counters untouched by construction (tested). Spike #1 in commit 829d8062 (exact-batch memoisation), switched to per-candidate reuse after §7 item 1 (commit 73e0af8c + follow-up), early draft CE in commit 6d83760a. Earlier one-pass figures (`fixed_shape_parity_2026-09-25.json`: CE reuse 8%, ≈ 92 ms attributable, total p50 5,454 → 5,045 ms) are superseded by the multi-pass A/B above. Lever #1 only clears the bar with a better draft (higher acceptance) or a larger overlappable stage; not pursued further as of 2026-09-25 |
| 5 | Spike #2 (SSE draft + final) only if step 1's overlap@10 ≥ ~0.7. Bars: time-to-first-card, time-to-final unchanged ±5%, final byte-parity vs cache-off, reshuffle rate | Yes | Code: `src/sfu_library_mcp_http.py::api_search_stream`, `web/lib/api.js` (`searchStream`, `createDraftSwapController`, `draftStreamStats`); tests `src/tests/test_search_draft_stream.py` 13/13, `scripts/verify_web_jsdom.mjs` 74/74. A/B results file still owed | **IMPLEMENTED 2026-09-25, EFFICACY UNMEASURED** (gate OFF); enabling stays conditional on step 1 overlap@10 ≥ ~0.7 and the bars **Gate stays OFF — measurement (a) 2026-09-25: overlap@10 vs post-CE top-10 = 0.433 mean (9.2% of topics ≥ 0.7), below the ~0.7 bar (§3b); DEFERRED until a better draft leg exists.** |
| 6 | #4 per its gate; #5 DEFERRED 2026-09-25 (§4b, no MCP follow-up traces) | Yes | as above | AFTER 4. #4: **CLOSED MEASURED 2026-09-25** — cold traverse −4.4% (bar ≥ 20%), warm arm slower (§4 row 4, `data/eval_results/block_prefetch_ab_2026-09-25.json`); code archived, never wire `/api/speculate` to it |

Steps 1 and 2 need the index mounted in the dev container and no serving
changes. Nothing after step 2 should start until the acceptance rate is known:
if it is low, #1 collapses to #3 and the ceiling is the hydrate share alone.

## 7. Open operator decisions (2026-09-25)

1. **RESOLVED 2026-09-25 — fixed-shape batching for per-candidate reuse**
   (§5 risk 1). Owner accepted; implemented on both paths (CE (10, 256),
   embedder (11, 256), dummy-row fill). Outcome: 0/120 topics change top-10
   order vs the old scoring (max |Δ| CE 9.2e-6), gate-on byte-identical to
   gate-off 120/120, CE stage 1.29× the old p50 (within the 1.5× bar),
   stage-1 stage 1.45×. Lever #1 reuse rises to 55% of candidates for
   stage-1 but only 8% for the CE (drafts lose the race), ≈ 92 ms p50
   attributable saving per cache miss (`data/eval_results/fixed_shape_parity_2026-09-25.json`). **Update 2026-09-25 (commit 6d83760a, early draft CE +
   multi-pass A/B, §4 row 1):** CE reuse rose to 55.1% (the acceptance
   ceiling), attributable saving −79.8 ms p50 on `_maybe_rerank`, total
   cache-miss p50 not reduced (+125 ms, inside leg variance); p50 bar FAILED,
   parity and p95 bars met; gate stays OFF
   (`data/eval_results/speculative_multipass_ab_2026-09-25.json`).
2. **RESOLVED 2026-09-25 (commit 6dab7e6f) — OpenAlex abstract fetch in the
   retriever sent no API key** (found by §3b). Owner decision: route it
   through `lib.openalex`. `lib.tools` now builds the retriever with
   `remote_abstract_fetcher=_get_openalex().fetch_abstracts_by_ids` and
   `openalex_api_key=cfg.openalex_api_key`, so the fetch sends the key and is
   covered by the daily tracker (≤ 2 tracker calls per served cache miss,
   successful responses only), the shared circuit breaker and the 5-minute
   cache; it runs with `max_retries=0` so a 429 never sleeps in a live query
   (contract: `docs/EXTERNAL_API_CONTRACT.md`). **Smoke test 2026-09-25**
   (1 HTTP request, ids W2741809807 + W1775749144, configured key): HTTP
   **200**, both abstracts returned, 525 ms wall for the single cold call.
   **Expected effect on the gap — *est.*, not re-measured:** the ~165 ms warm
   of failed 429 round-trips per cache miss (§3b, 2,929 ids requested, 0
   returned) is no longer spent failing; the candidates now reach the CE
   WITH abstracts. Whether latency drops is open: a successful keyed fetch
   returns payload and may cost as much as or more than the failed calls
   (one cold sample: 525 ms incl. TLS). Re-measure by re-running the §3b
   pass (`scripts/experiments/speculation_acceptance_rate.py`): it builds the
   retriever via `lib.tools._get_federated_router()`, so it now picks up the
   keyed client path, and its timing wrapper on `_fetch_remote_abstracts`
   still sits on the dispatch point. Note the rerun will spend up to ~2
   tracker calls per topic against the 900/day limit.

