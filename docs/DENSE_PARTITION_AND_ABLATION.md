# Dense ANN leg — payload partition + keep/drop assessment (2026-08-17)

**Status: CURRENT.** Two questions, answered separately:

1. **Can the OCI demo payload ship without the dense leg?** Yes — verified, and
   there is now a single env gate for it (`SFU_DENSE_LEG=0`). §1–§3.
2. **Should it?** The recorded dense wins were measured on an index that was
   **built to contain the eval's answers** — measured 2026-08-17 at **90.3%
   ground-truth coverage vs 0.399% for a random subset of the same size, 226×
   enrichment**. Those numbers are an **upper bound**, not production benefit,
   and the standard query set **cannot** settle keep/drop because it has **zero
   held-out topics**. §4–§6. A **fresh 120-topic judged set was built 2026-08-18**
   (§7) whose dense-pool contamination is **17.98% vs the standard set's 90.3%**;
   **the ablation itself is still NOT RUN.**

Related: `DENSE_WARMCACHE_RESEARCH.md` (the warm cache's design),
`THIN_CLIENT_SWAP.md` (architecture, engine table, storage table),
`infrastructure/OCI_DEMO_DEPLOYMENT.md` §2 + `infrastructure/PORTABLE_STACK_MANIFEST.md`
(the payload tables this partition feeds).

---

## 1. The dense partition — exactly what is excludable

Measured on disk 2026-08-17 (`du -sb`, `find -printf %s`):

| Path | Bytes | Size | Excludable? |
|---|---:|---:|---|
| `data/thinclient_index/dense/b1.usearch` | 117,902,704 | 112.4 MiB | **yes** — static seed, 600k × 384d binary (b1 Hamming) |
| `data/thinclient_index/dense/rescore_int8.npy` | 230,400,128 | 219.7 MiB | **yes** — 600k × 384 int8 rescore memmap |
| `data/thinclient_index/dense/ids.json` | 8,987,842 | 8.6 MiB | **yes** — usearch row → OpenAlex id |
| **Excludable dense partition** | **357,290,674** | **340.7 MiB ≈ 0.357 GB** | **the optional payload component** |
| `data/thinclient_index/dense/delta.sqlite` (+`-wal`, `-shm`) | 16,666,920 | 15.9 MiB | **runtime state, never shipped** — warm-cache delta, 20,520 docs as of 2026-08-17; rebuilt from queries |
| `dense/` total on disk | 373,961,690 | 356.6 MiB ≈ 0.374 GB | |

**There is no `dense_cache/` directory.** The warm cache lives *inside* `dense/`
as `delta.sqlite` (`dense_cache.DenseWarmCache.__init__` → `self.dir = Path(dense_dir)`,
and `retriever._load` passes it `self.root / "dense"`). `THIN_CLIENT_SWAP.md`'s
index-layout listing claimed a separate `dense_cache/` directory; corrected
2026-08-17 in the same commit as this doc (code is the source of truth).

### The query encoder is NOT part of the partition

`models/sfu-academic-embed-v5/` (3.34 GB on disk; **134,504,132 B = 128.3 MiB
serving-essential**, the rest is `checkpoints/` training state that the serve
path never opens) is **shared, not dense-only**:

- dense leg — `retriever.dense_search` → `lib.opensearch_retriever.encode_dense`
- **embed rerank** — `lib.reranker._compute_semantic_scores` → `lib.embedding`
  → the same `models/sfu-academic-embed-v5` default (`lib/config.py:52`), and
  `lib/tools.py:103` passes `use_embedding=True` **unconditionally**

So dropping the dense leg does **not** let the payload drop the model, the
`sentence-transformers` dependency, or `torch`. `PORTABLE_STACK_MANIFEST.md`
delta item #6 attributes the CUDA-torch dependency to "the dense encoder" — it
is really the *shared* embed encoder; dropping only the dense leg does not
close that item. Dropping the model would additionally require disabling embed
rerank, which is a separate decision with its own (unmeasured) quality cost.

### Env gates

| Var | Default | Effect |
|---|---|---|
| `SFU_DENSE_LEG` | **`0` (OFF) since 2026-08-18** — was `1` from 2026-08-17 | **only the literal `1` enables the whole leg** (static seed *and* warm cache; same only-`"1"`-enables shape as `SFU_ABSTRACTS_PREFAULT`). Flipped after the §7 ablation measured the 0.4%-coverage leg significantly *harmful* (Δ nDCG@10 −0.0077, CI excludes 0); operator direction: stay off until the **full corpus** is dense-encoded and the leg re-measures positive. |
| `SFU_DENSE_WARMCACHE` | `1` (on) | `0` disables only the query-driven warm cache; the static seed still serves. **Inert while the leg itself is off** — the warm cache only constructs when `SFU_DENSE_LEG=1`. |

`SFU_DENSE_LEG=1` is **byte-identical to the pre-gate path** — the gate is one
`and` added to each of the two existing conditionals in `retriever._load`.
`metrics()` reports `dense_leg_enabled` so a deploy can *prove* which optional
components are live (an absent `dense/` and a disabled leg both report
`dense_vectors: 0`, so the vector count alone cannot distinguish them).

**Demo payload recipe — dense excluded:** omit the three files above from the
upload; since 2026-08-18 **no env var is needed** (off is the default). Saves
0.357 GB of payload (0.3% of the ~108 GB served total — the partition matters
for *cleanliness and per-query cost*, not for disk).

---

## 2. Graceful degradation — VERIFIED 2026-08-17

`THIN_CLIENT_SWAP.md` line 27 claims per-leg isolation ("bm25f + dense still
serve if the encoder dies"). The **inverse** — seismic/BM25F serve cleanly with
no dense leg — is now verified and pinned by regression tests
(`scripts/tests/test_thinclient_stack.py`, **26 passed 2026-08-17** — 19 at the
gate commit `1ebfd78`, +7 with the §7 prerequisites):

`test_serves_with_no_dense_dir` — index root with **no `dense/` at all**:

- `_dense is None`, `_dense_cache is None`, `is_available()` true;
- `search()` (BM25F/SPLADE) returns results normally;
- `dense_search()` returns `[]` **before encoding the query** — the early return
  at `retriever.py` "`if not self._dense and not (cache and cache.info()["docs"])`"
  precedes `encode_dense`, so a missing leg costs no encoder time;
- **five repeat `dense_search()` calls emit zero log records** — no per-query
  error spam (other legs may warn once for their own reasons, e.g. an ambient
  `SFU_SPLADE_BACKEND=seismic` with no shard manifest falling back to BM25F;
  that is a different leg's degradation path and the test scopes around it);
- `search_rrf(include_dense=True)` returns a **fused ranking over the surviving
  legs** (`include_dense and self._dense` short-circuits);
- the `dense` leg never appears in a per-leg metrics **window**
  (`_leg_snapshot_for_log` / `_leg_delta_for_log`), i.e. it consumed no time;
- `reload()` round-trips with `dense_vectors: 0`.

`test_dense_leg_env_gate` — `SFU_DENSE_LEG=0`, warm cache left at its default:

- no seed, no warm cache, `metrics()["dense_leg_enabled"] is False`;
- **`dense/` is not re-created**, and `encode_dense` is monkeypatched to raise —
  it is never called;
- unsetting the var restores the default-on warm cache.

### Why absence alone was SAFE but not FREE (the reason the gate exists)

`DenseWarmCache.__init__` calls `self.dir.mkdir(parents=True, exist_ok=True)`.
With the warm cache default-ON, a payload shipped *without* `dense/` would
**re-create the directory**, open a fresh `delta.sqlite`, and — on the first
query that surfaced any doc — start a background thread that loads the 128 MB
bi-encoder and encodes every surfaced doc (`_hydrate` → `enqueue`). That is the
full encoder cost with **zero static coverage to fuse it against**, plus writes
into an index root the deploy meant to be read-only. `SFU_DENSE_LEG=0` is the
clean off switch.

---

## 3. Cost per query — the search is cheap, the ENCODE is unmeasured

`_record_leg("dense", ms)` times the whole leg as **one fused number** (encode +
usearch search + int8 rescore + post-filter), because `dense_search` starts its
`t0` *before* `encode_dense`. No captured run in `data/eval_results/` records a
served dense-leg latency at all, and none splits the stages.

What *is* measured:

| Number | Source | What it covers |
|---:|---|---|
| **0.34 ms/query** | `data/eval_results/thin_client_poc.json` (usearch b1 + rescore, 100k docs) | search + rescore only, **no query encode** |
| **3.5 ms/query** | `dense_compression_eval.json` `binary_flat+rescore`, 600k | faiss brute-force binary; the no-rescore arm is 2.9 ms, so **rescore ≈ +0.6 ms** |
| 0.04–0.13 ms/query | `dense_compression_eval.json` HNSW arms, 600k | ANN search alone |
| ~87 docs/s CPU @ batch 32 | `DENSE_WARMCACHE_RESEARCH.md` | **doc-side** warm-cache encode throughput, *not* single-query latency |

So the ANN + rescore half of the leg is **sub-millisecond to a few ms** — cheap
next to the SEISMIC leg (warm p50 ≈ 47–65 ms) and irrelevant next to the
filter stage (4.0 ms staged / 222.2 ms on 9p).

**The unmeasured term is the CPU query encode, and it is almost certainly the
dominant one.** For scale: the SPLADE leg's encode is measured at **p50 ≈ 20–23
ms** and is 31–37% of that leg's total; the dense bi-encoder is a comparable
BERT-small forward pass. A dense-leg cost of *tens of ms per query* is the
honest expectation, but it is **UNMEASURED** — any specific figure today is
*est.* only, and the §7 ablation must split it.

Two observations that argue the tail is worse than the mean:
`DEMO_DEPENDABILITY.md` records a **real dense-leg timeout in the wild** on a
cold diverse query (`degraded=['dense']` appearing in a warm batch without any
injected fault), and its fault-injection table shows whole-query times of
~3.7 s in the regime where the dense leg is exercised.

---

## 4. Evidence FOR keeping the dense leg

Two recorded evals, 360 query records / 120 LLM-judged topics, judge threshold
grade ≥ 2, gain `2^grade − 1`:

**`data/eval_results/dense_poc_eval.json`** — retrieval-only, RRF k=60,
2-leg `RRF(BM25F+SPLADE)` vs 3-leg `+dense`:

| Stratum | nDCG@10 2-leg | nDCG@10 3-leg | Δ | recall@50 2-leg → 3-leg |
|---|---:|---:|---:|---|
| keyword (120) | 0.5221 | 0.7239 | **+0.2018** | 0.8425 → 0.9029 |
| natural (240) | 0.2091 | 0.5469 | **+0.3378** | 0.3371 → 0.7457 |
| overall (360) | 0.3135 | 0.6059 | **+0.2924** | 0.5056 → 0.7981 |

**`data/eval_results/pipeline_dense_comparison.json`** — the same contrast run
**through the production rerank** (embed → cross-encoder), headline = final
reranked top-10:

| Stratum | final nDCG@10 A (bm25f+splade) | final nDCG@10 B (+dense) | Δ |
|---|---:|---:|---:|
| keyword | 0.6841 | 0.7012 | +0.0171 |
| natural | 0.3015 | 0.4714 | **+0.1699** |
| overall | 0.4290 | 0.5480 | **+0.1190** |

The **directional** reading is the credible part and it is consistent: the
benefit **survives reranking** rather than being an artifact the cross-encoder
would have recovered anyway, and it is **concentrated in natural-language
queries** (+0.1699 vs +0.0171 post-rerank) — which is exactly the traffic shape
an MCP/chat client produces.

---

## 5. Evidence AGAINST — the pool contains the answers (measured 2026-08-17)

**The 600k dense pool was constructed as "judged docs (guaranteed) + random
distractors"** — `scripts/experiments/dense_indexer_poc.py` ("Build the doc
pool: judged first (guaranteed), then distractors"), and the **served** index is
built from that exact pool: `scripts/build_thinclient_index.py` →
`DENSE_VECS = data/dense_compression/vectors_600k.npy`.

Measured against the *served* `data/thinclient_index/dense/ids.json`
(script: `scripts/experiments/dense_pool_contamination.py`; result:
`data/eval_results/dense_pool_contamination_20260817.json`):

| Quantity | Value |
|---|---:|
| Served dense vectors | 600,000 (**0.399%** of 150,413,098) |
| Relevant judged docs (grade ≥ 2) over the query set | 2,107 |
| …present in the served dense pool | **1,903 = 90.3%** |
| All judged docs in pool | 3,390 / 4,034 = 84.0% |
| **Enrichment vs a random 600k subset** | **226×** |
| Topics fully covered / partially / **held-out (zero relevant in pool)** | 50 / 70 / **0** |

Consequences:

1. **The deltas in §4 are an UPPER bound on production benefit, not a lower
   bound.** In those evals the dense leg searched a 250×-smaller haystack that
   had been seeded with ~90% of the answers, while BM25F/SPLADE searched all
   150M. The repo's own scripts disagree about this in their printed caveats —
   `eval_pipeline.py` says "Absolute deltas are therefore **OPTIMISTIC / an
   upper bound**, NOT production magnitudes", `eval_dense_poc.py` says dense's
   contribution "is a **LOWER BOUND**". For the *deployed* configuration
   `eval_pipeline.py` is right and `eval_dense_poc.py` is wrong: "lower bound"
   would only hold if the subset were an unbiased sample, and at 226×
   enrichment it emphatically is not.
2. **The RRF vote is biased toward the POC subset by construction.** RRF awards
   `1/(k+rank)` on the dense leg's *own* ranking, with no notion of whether
   those docs are globally competitive. At 0.399% coverage, for a query whose
   good answers are not in the pool, the leg still returns its 50 best local
   matches and still votes for them — injecting subset-local documents into the
   fused top-k. Whether that *displaces* better lexical hits is the open
   question, and it is unmeasured.
3. **The standard query set cannot decide keep/drop.** Zero of 120 topics have
   no relevant doc in the pool, so there is **no held-out stratum**. An ablation
   run on `diverse_queries.json` would re-measure the oracle, not the leg.

Note the distractor fill was not a random sample either — it was a plain
OpenSearch scroll (`dense_indexer_poc.py`, `SCROLL_BATCH = 1000`, no sort/seed),
i.e. **index order**. The "0.399% for a random subset" row is therefore the
*counterfactual* (what an unbiased same-size subset would have covered), not a
description of how the distractors were drawn.

### The two gaps that make the vote-bias question unanswerable today

- **No dense∩other-leg overlap has ever been measured.** Every recorded
  complementarity figure is BM25F∩SPLADE only (`avg_bm25f_splade_overlap@50`
  ≈ 5.2–6.2 across all `thinclient_parity_*.json`). `thin_client_poc.json` says
  why: "dense leg uses the dense-POC corpus so it is benchmarked separately".
- **`search_rrf` discarded leg provenance** (fixed 2026-08-17, see §7
  "Prerequisites"). It accumulated `scores[did] += 1/(RRF_K + rank)` and kept
  only `by_id.setdefault(did, doc)`, so *which* leg surfaced a fused result was
  thrown away. The dense-vote share of the final top-k could not have been
  recorded even incidentally. Provenance is now recordable opt-in; **it has
  still never been measured on the served index** — the metric is unblocked,
  not collected.

Related: the parity harness already runs dense-free — `run_parity_safe.sh` and
`eval_thinclient_parity.py` phase A hard-set `SFU_DENSE_WARMCACHE=0`, so every
recorded 150M parity number is effectively an **arm-A-like** configuration
already (static seed still loaded, warm cache off).

### Not evidence of corpus-level benefit (do not conflate)

`THIN_CLIENT_SWAP.md`'s engine table cites "validated **R@10 0.996**" for the
dense row. That is **binary-vs-float rescore fidelity** — how well b1 Hamming +
int8 rescore reproduces exact fp32 ranking **within the covered 600k subset**
(`dense_compression_eval.json` `ann_recall@10_vs_exact`). It says the
compression is lossless-enough; it says **nothing** about whether the leg helps
retrieval over 150M docs. Same for the warm cache: the four "Success metrics"
in `DENSE_WARMCACHE_RESEARCH.md` are all **UNMEASURED** — the 20,520 accumulated
delta docs have never been evaluated for recall contribution.

---

## 6. Assessment + recommendation

**Honest summary.** The dense leg has a real, reranking-surviving,
natural-language-shaped quality signal *on a 600k index that contained 90% of
the answers*. It has **no measurement at all** at its deployed 0.4% coverage,
and **no recorded per-query cost**. The two facts the decision needs — benefit
on queries the pool was not built around, and ms per query — are both missing.

**Precedent already set, without a quality argument.** The Windows social-science
handout **already strips the dense leg**
(`infrastructure/PORTABLE_SOCSCI_WINDOWS_BUNDLE.md`: "dense leg + v5 encoder …
**0 (stripped)**", `SFU_DENSE_*` disabled, `scripts/portable_socsci/02_assemble_data.py`
"Trimmed manifest … dense stripped"). But that doc frames the strip purely as a
size decision and calls the ~3.5 GiB saving disappointingly small — **nobody has
ever measured what stripping it costs in quality.** This doc is where that gap
gets named rather than inherited.

**The open decision this feeds.** `LOCALIZED_DEPLOYMENT_PLAN.md` §8 decision #6
("Add the dense-ANN retrieval leg?") has been **open since 2026-05-24** with the
exact precondition this doc restates: re-measure at full index scale, not the
600k subset, and against NL-seeded judgments. The full-corpus dense index was
never built, so #6 has never been closable. §7 is the cheaper substitute —
it decides *ship/don't ship the 0.4% leg* without requiring the full encode.

**Recommendation (2026-08-17):**

- **Keep the leg in the codebase and default-ON.** Nothing measured says it
  hurts, and the code path is proven-safe in both directions.
- **Ship the OCI demo payload WITHOUT the dense partition by default**
  (`SFU_DENSE_LEG=0`, omit the three files). Rationale: 0.4% static coverage
  cannot be described honestly to a demo audience as "the dense leg", the
  RRF vote is subset-biased, the per-query encoder cost is real and unmeasured,
  and the payload saving (0.357 GB) is a rounding error either way — the
  argument is *honesty and latency*, not disk. Ship **with** it only for a demo
  that deliberately shows dense retrieval on the POC-covered subset, and say so.
- **Do not cite the §4 numbers as production benefit** anywhere. They are upper
  bounds on an oracle-enriched pool. Cite them as "directional, on the POC
  subset".
- **Revisit after the §7 ablation.** If the held-out delta is inside noise, drop
  the leg from the payload permanently and reclaim the encoder time; if it
  holds, the case for **encoding the full corpus** (not for shipping 0.4%) is
  what gets made.

> **RESOLVED 2026-08-18 — the §7 ablation ran; the answer is worse than
> "inside noise": Δ_all = −0.0077 (95% CI [−0.0153, −0.0001]), significantly
> NEGATIVE, with no coverage band positive.** The payload drop is now permanent
> and measured, not precautionary (§7 "RESULT"). The 2026-08-17 recommendation
> above stands with one hardening: "nothing measured says it hurts" is no
> longer true — the served 0.4% leg measurably hurts final quality by spending
> RRF votes on documents the reranker discards (15.6% of fused top-10 →
> 2.46% of final top-10) while displacing relevant lexical docs
> (Δ recall@50 = −0.028). Keep-in-codebase remains reasonable; default-ON is
> now an open question for the operator, not this doc.
>
> **Question answered 2026-08-18 (operator direction): the leg is now DEFAULT
> OFF in code** (`SFU_DENSE_LEG` unset ⇒ off; only the literal `1` enables) —
> to stay off until the full corpus is dense-encoded (not the 600k snippet)
> and the leg re-measures positive. See §1 "Env gates".

---

## 7. Pre-registered ablation — RRF with vs without the dense leg

**RUN 2026-08-18 — VERDICT: DROP from the payload.** Both arms executed under
the amended (Option 2, operator-signed, committed pre-arm in `6e84656`) decision
rule; the dense leg's delta is not merely inside noise but **significantly
negative**. Full numbers in "RESULT — MEASURED 2026-08-18" below. *(The
paragraph that follows is the pre-run state, kept for the record.)*

This ablation was scoped to follow the 2026-08-17
150M parity eval, which owned machine I/O. That eval completed
(commit `0ca7fce`), the fresh judged query set was built 2026-08-18
(§"Query set" below), and the degenerate-stratum protocol amendment was signed
off and committed before any arm ran (see §"Query set" → "the pre-registered
binary stratification came out DEGENERATE").

### RESULT — MEASURED 2026-08-18: the dense leg HURTS final quality

Arms run per the §"Command" block (240 forms / 120 topics each,
`--rerank embed+ce`, `SFU_DENSE_WARMCACHE=0` both arms, fresh process each,
absolute `--index-root`, the §7 judge cache). Integrity gates passed in both
arms: 240/240 records, `bm25f∩splade@50` = **5.53** in each arm (= the pooling
run's 5.53; a BM25F fallback reads 50), arm A `dense_vectors=0` / arm B
`dense_vectors=600000`.

Analysis: `scripts/experiments/dense_ablation_analysis.py` (paired bootstrap
over topics, 10k resamples, seed 20260818; per-topic = mean of the topic's two
forms, which share one gradebook) →
`data/eval_results/dense_ablation_analysis_20260818.json`. Arm records:
`dense_ablation_A_nodense_20260818.json`, `dense_ablation_B_dense_20260818.json`.

**Primary (amended rule):** final post-rerank nDCG@10, B − A, all 120 topics:

| Measure | Value |
|---|---|
| arm A (no dense) mean final nDCG@10 | **0.7215** |
| arm B (dense) mean final nDCG@10 | **0.7138** |
| **Δ_all (B − A)** | **−0.0077**, 95% CI **[−0.0153, −0.0001]** — CI excludes 0, on the *negative* side |
| dose-response check, `c ≤ 0.10` (24 topics) | Δ **−0.0184**, CI [−0.0362, −0.0018] — also significantly negative |
| strict-4 HELD-OUT (as originally pre-registered) | Δ +0.0129, CI [−0.0193, +0.0429] — n=4, uninformative, reported for the record |

Δ by coverage band (no band is significantly positive; the only significant
band is negative):

| Band | n | Δ | 95% CI |
|---|---:|---:|---|
| `c == 0` | 4 | +0.0129 | [−0.0193, +0.0429] |
| `0 < c ≤ 0.05` | 3 | −0.0120 | [−0.0430, +0.0115] |
| `0.05 < c ≤ 0.10` | 17 | **−0.0269** | [−0.0483, −0.0067] |
| `0.10 < c ≤ 0.25` | 72 | −0.0022 | [−0.0118, +0.0071] |
| `0.25 < c ≤ 0.50` | 24 | −0.0135 | [−0.0310, +0.0036] |

**Verdict under the amended rule: DROP.** KEEP required Δ_all ≥ +0.02 with the
CI excluding 0 *and* a positive low-coverage point estimate; the measurement
fails both, with the CI excluding 0 in the wrong direction. The dose-response
prediction resolved *against* the leg: there is no coverage regime in which it
helps.

**Secondary.** Retrieval-only: Δ nDCG@10 −0.0051 and Δ recall@50 −0.0277 —
adding the dense leg *displaces* relevant lexical docs from the fused top-50
(its injections are near-disjoint: `dense∩bm25f@50` = 0.17, `dense∩splade@50`
= 0.15, arm B). **Dense-vote share@10**: **15.6%** of the *fused* (pre-rerank)
top-10 were dense-only docs (`eval_pipeline` summary, `rrf_legs`-based), but
only **2.46%** of the *final* post-rerank top-10 — the cross-encoder rejects
~84% of the dense-only injections, which is the §5 vote-bias worry observed
directly: the leg spends fusion votes on documents the reranker then discards,
and net quality goes down.

**Cost (context, not needed for the verdict).** Warm dense-leg p50 **61.9 ms**
/ p95 117.4 ms; the **first** query paid **16,741 ms** (encoder + memmap cold
load — same shape as the §8 smoke's 128 s observation, smaller because the
model files were OS-cached). ⚠ Protocol deviation, recorded: the "page cache
dropped between arms" step was impossible in this container
(`/proc/sys/vm/drop_caches` read-only; uniform pre-warm also impossible —
118 GB index vs 56 GB RAM). Quality metrics are unaffected (`SFU_DENSE_WARMCACHE=0`,
fresh process per arm as specified), but **cross-arm latency comparisons are
biased** (arm B ran second, over a page cache arm A had warmed — e.g. its
splade p50 reads 149 ms vs arm A's 609 ms) and MUST NOT be quoted as an
ablation latency result. The dense leg's *own* timings above are unaffected by
arm order (nothing dense-side was pre-warmed).

**What DROP means here (per §6):** the OCI demo payload ships **without** the
dense partition (`SFU_DENSE_LEG=0`, omit the three `dense/` files) — now backed
by measurement, not just the honesty/latency argument. The leg and its gate
stay in the codebase (proven-safe in both directions); the case for *full-corpus*
dense encoding is a separate question this measurement does not close, but the
0.4%-coverage leg as served is measured harmful and is done.

**The completed parity run is already an arm-A-equivalent record.** It queried
**only bm25f + splade** (per-query keys `bm25f`/`splade`/`lat_bm25f_ms`/
`lat_splade_ms`; no dense list at all) with `warmcache: "0"`:

- `data/eval_results/thinclient_parity_seismic_e8dv2_20260817.json` —
  **2-leg `tc_rrf` nDCG@10 = 0.5369** over 38 judged queries (40 requested,
  top_k 50), `avg_bm25f_splade_overlap@50 = 5.35`;
- `data/eval_results/parity_record_tc_seismic_e8dv2_20260817.json` — the
  per-query top-50 lists, so **arm B can be scored against this cached record
  without re-running arm A** for the retrieval-only metric.

⚠️ **Directional observation, not a comparison** (different query count,
engine and era, so the numbers are NOT directly comparable): the dense POC
measured its +0.2924 against a 2-leg baseline of **0.3135**; the served 2-leg
stack today records **0.5369**. Much of the headroom dense was credited with
filling has since been taken by the SEISMIC E8 SPLADE leg. This is a reason to
expect the ablation delta to be **smaller** than the POC's, and a reason to run
it before spending anything more on dense.

**Pre-registered before any data is collected, so the decision rule cannot be
chosen after seeing the result.**

### Query set (the part that matters) — **BUILT 2026-08-18**

`data/eval_results/diverse_queries.json` **cannot be used alone** — 0 held-out
topics (§5). The requirement was a **fresh judged set**:

- ≥ 100 new topics, drawn from the same subject spread, **judged after** the set
  is drawn (same LLM-judge protocol, grade ≥ 2 = relevant, gain `2^grade − 1`);
- each topic classified by `scripts/experiments/dense_pool_contamination.py`
  into **HELD-OUT** (zero relevant docs in `dense/ids.json`) vs **IN-POOL**;
- **the HELD-OUT stratum is the decision stratum.** The IN-POOL stratum is
  reported for contrast only and must never be quoted as production benefit;
- keyword vs natural-language paraphrase pairs kept, since §4's only robust
  finding is that the effect is natural-language-shaped.

**That set now exists** (`scripts/experiments/dense_ablation_queryset.py`,
stages `draw → pool → hydrate → judge → finalize`). **The ablation itself is
still NOT RUN** — nothing below is an ablation result; these are query-set
construction statistics.

| Property | Value |
|---|---|
| Topics | **120 new**, over the **same 49 SFU subjects** as `diverse_queries.json` with **identical per-subject counts** (asserted at draw time) |
| Disjointness | **0 reuse** of the 120 old `judge_key`s (asserted; the draw hard-fails on reuse) |
| Query records | **240** = 1 keyword form + 1 natural-language paraphrase per topic |
| Draw committed **before** any retrieval/judgment | commit `e205269`, `dense_ablation_topics_20260817.json` |
| Pool depth | top-**50** per leg (bm25f, splade, dense) **plus** the fused top-50, per query form; the topic's pool is the union over **both** forms |
| Pool size | **25,614 unique docs**; per-form mean 144.2; **per-topic mean 216.0** (min 162, max 273) |
| Judged pairs | **25,919** (topic × pooled doc) |
| Judge | **`claude-haiku-4-5-20251001`** via the `claude` CLI subprocess (the `benchmark_llm_judge.py` backend), 0–3 topical relevance, prompt template `sha256:7141d7866e71a03d` |
| Judged on | the **natural-language** form of each topic; cache key is the keyword form (= `judge_key`), so both forms share one gradebook |
| Grade histogram | 0: 8,729 · 1: 6,019 · 2: 4,643 · 3: 6,528 → **11,171 relevant** (grade ≥ 2) |
| Abstracts | AbstractStore sidecars first; **58.1%** of pooled docs were title-only locally (bm25f 64.1% / splade 52.0% / dense 57.2% — **not** a dense-leg bias), an OpenAlex backfill added 12,052 abstracts → **11.0%** title-only, flagged per doc in the qrels |

**The pooling retrieval was untimed and single-arm (dense ON). Its recorded
`lat_*_ms` are incidental and MUST NOT be quoted as ablation latency.**

**The SPLADE leg was PROVEN real before anything was judged.** `bm25f∩splade@50`
= **5.53** mean over all 240 forms, against the parity run's 5.35
(`thinclient_parity_seismic_e8dv2_20260817.json`); a silent BM25F fallback reads
**50**. The `pool` stage aborts if a probe query exceeds 25.

**Contamination fell 5× — the point of the exercise.** Fraction of relevant
judged docs sitting inside the served 600k dense pool: **17.98%** on this set vs
**90.3%** on `diverse_queries.json` (§5). No topic exceeds 50% coverage, where
the old set had **50/120 topics at 100%**.

#### ⚠ The pre-registered binary stratification came out DEGENERATE

Applying the §7 rule literally (`scripts/experiments/dense_pool_contamination.py`:
HELD-OUT = **zero** grade-≥2 docs in `dense/ids.json`):

| Stratum | Topics |
|---|---:|
| **HELD-OUT** (the pre-registered decision stratum) | **4** |
| IN-POOL (contrast only) | 116 |
| No relevant doc judged at all | 0 |

**4 is not a usable decision stratum, and drawing more topics cannot fix it.**
The rule was written when the only judged docs came from bm25f/splade/rrf/
OpenAlex — the dense leg's own output was never in the pool, so "zero relevant
docs in the pool" was reachable. §7 requirement 3 (correctly) makes the pool the
union of what **both** arms could surface, which puts ~100 dense-pool docs per
topic in front of the judge; a semantic retriever over 600k academic papers
nearly always surfaces at least **one** relevant paper, so a strict zero is
close to unreachable. The observed rate is 4/120 = 3.3%, so even the 200-topic
cap would yield ≈ 7 — the shortfall is **structural, not a sample-size problem**,
which is why the draw was not extended.

What replaces it is a **graded** measure — per-topic dense-pool coverage
(fraction of a topic's relevant docs inside `dense/ids.json`), recorded per topic
in the qrels:

| Coverage band | Topics |
|---|---:|
| `== 0` (strict HELD-OUT) | 4 |
| `0 < c ≤ 0.05` | 3 |
| `0.05 < c ≤ 0.10` | 17 |
| `0.10 < c ≤ 0.25` | 72 |
| `0.25 < c ≤ 0.50` | 24 |
| `c > 0.50` | 0 |

median 0.168, mean 0.176.

**This is a change to a pre-registered protocol and therefore needs sign-off
BEFORE an arm is run, not after.** Three options, for the operator to choose:

1. **Low-coverage stratum** — decide on `c ≤ 0.10` (**24 topics**). Closest in
   spirit to "held-out"; still under the 30-topic power target.
2. **Dose-response over all 120 topics** — run every topic and report Δ by
   coverage band. If the dense benefit is real rather than oracle-driven it must
   **not** vanish as coverage → 0. This is the only option that uses the full
   set, and its prediction is falsifiable.
3. **Strict-4** — report as pre-registered and declare the ablation
   underpowered.

**ADOPTED 2026-08-18: Option 2 — dose-response over all 120 topics.** Operator
sign-off obtained in-session (explicit choice among the three options above)
**before any arm was run**. The amended decision rule is spelled out in
"Metrics + decision rule" below; the original HELD-OUT rule is preserved there,
marked superseded.

#### Files (absolute date 2026-08-18)

| File | Contents |
|---|---|
| `data/eval_results/dense_ablation_queries.json` | the 240-record query set `eval_pipeline.py --queries` accepts (`judge_key`, `query_type`, `stratum` per entry) |
| `data/eval_results/dense_ablation_qrels_20260817.json` | per-topic judgments: grade, `gain = 2^grade − 1`, `relevant`, `in_dense_pool`, `title_only`, plus per-topic `dense_pool_coverage` |
| `data/eval_results/dense_ablation_judge_cache_20260817.json` | the judge cache (`judge_key||openalex_id → grade`) — pass it as `--judge-cache` |
| `data/eval_results/dense_ablation_topics_20260817.json` | the draw (committed before judging) |
| `data/eval_results/dense_ablation_pool_20260817.json` | the pooling record: per-form leg top-50s, fused list, `rrf_legs`, env |
| `data/eval_results/dense_ablation_pool_docs_20260817.json` | title+abstract for every pooled doc (what the judge saw) |
| `data/eval_results/dense_ablation_queryset_20260817.json` | provenance/summary |

#### First dense-leg overlap ever measured on the served index

A by-product of pooling, and the gap §5 named as unmeasured
("no dense∩other-leg overlap has ever been measured"), over 240 query forms:

| Pair | overlap@50 (mean) |
|---|---:|
| bm25f ∩ splade | 5.53 |
| **dense ∩ bm25f** | **0.175** |
| **dense ∩ splade** | **0.142** |

The dense leg is **nearly disjoint** from both lexical legs — it contributes
almost entirely novel documents to the fusion. That is *consistent with* either
reading of §5 (genuine complementarity, or subset-local documents injected into
the fused top-k) and **settles neither**; the arms decide that.

### Arms

Identical queries, `top_k`, filters, rerank path; one variable.

| Arm | Config |
|---|---|
| **A** | `SFU_DENSE_LEG=0` — RRF(BM25F + SPLADE) |
| **B** | dense on — RRF(BM25F + SPLADE + dense). *Was "default" when the arms ran 2026-08-18; since the post-verdict default flip, a re-run must set `SFU_DENSE_LEG=1` explicitly or arm B silently becomes arm A.* |

Run each arm in its own process (the retriever has no `close()`; same discipline
as `scripts/run_parity_safe.sh`), page cache dropped between arms, warm cache
pinned off (`SFU_DENSE_WARMCACHE=0`) in **both** arms so the delta is the static
leg only and B is reproducible.

### Metrics + decision rule

**Primary (decides keep/drop) — AMENDED 2026-08-18, Option 2 adopted with
operator sign-off before any arm ran (the original HELD-OUT-stratum rule is
superseded because that stratum came out degenerate at 4 topics; see above):**
final **post-rerank nDCG@10 over ALL 120 topics**, B − A, paired bootstrap over
topics, 10k resamples, plus a dose-response check across the per-topic
dense-pool-coverage bands.

- **KEEP** requires BOTH:
  1. Δ_all ≥ **+0.02** with the 95% CI excluding 0, AND
  2. the benefit must **not vanish as coverage → 0**: Δ on the low-coverage
     topics (`c ≤ 0.10`, 24 topics) has a **positive point estimate**. (n=24 is
     under the 30-topic power target, so no CI bar is set on this check — but a
     ≤ 0 point estimate there means the measured benefit is concentrated in
     contaminated topics and is treated as oracle-driven.)
- **DROP from the payload** if the overall 95% CI includes 0 (benefit
  indistinguishable from noise → the leg costs latency and buys nothing at 0.4%
  coverage), or Δ_all < 0, or the dose-response check (2) fails.
- Δ_all ≥ +0.02 with a CI including 0 → underpowered, extend the query set; do
  not round up to "keep".
- Reported alongside (not decisive): Δ per coverage band (`==0`, `≤0.05`,
  `≤0.10`, `≤0.25`, `≤0.50`) with per-band bootstrap CIs, and the strict-4
  HELD-OUT Δ as originally pre-registered.

*Original pre-registered rule (superseded 2026-08-18, kept for the record):*
primary was post-rerank nDCG@10 on the HELD-OUT stratum, B − A, paired
bootstrap 10k, KEEP if Δ ≥ +0.02 with the 95% CI excluding 0 — unusable as
written because HELD-OUT = 4 topics (structural; see the stratification note
above).

**Secondary (reported, not decisive):** retrieval-only nDCG@10 and recall@50;
**dense-vote share** = fraction of final top-10 docs whose only contributing leg
was dense — the direct measure of the §5 vote-bias worry. Its prerequisite code
change **landed 2026-08-17** (see "Prerequisites" below): the recorded
`rrf_legs` field gives the contributing legs per fused doc, so dense-vote share
is `fraction of the top-10 whose rrf_legs == {"dense": …}` computed offline from
an arm file. Also report **dense∩bm25f / dense∩splade overlap@50**
(`summarize_thinclient` emits both), which has never been measured for any leg
pair involving dense. Plus IN-POOL-stratum deltas, for contrast only.

**Cost (reported alongside, and decisive if quality is a tie):** per-leg p50/p95
ms from `_record_leg` / `serve_query_log`, **split into query-encode vs
usearch-search vs int8-rescore vs post-filter**, plus arm-level end-to-end p50/p95.
A quality tie plus a non-trivial encode cost ⇒ drop.

### Command

```bash
# The 2026-08-17 parity eval has released the machine (commit 0ca7fce), and the
# fresh judged query set exists (2026-08-18). Rebuild/extend it only if needed:
#   .venv/bin/python3 scripts/experiments/dense_ablation_queryset.py finalize

# 1) arm A — dense leg off
SFU_DENSE_LEG=0 SFU_DENSE_WARMCACHE=0 \
  .venv/bin/python3 scripts/experiments/eval_pipeline.py \
    --queries data/eval_results/dense_ablation_queries.json \
    --judge-cache data/eval_results/dense_ablation_judge_cache_20260817.json \
    --index-root /workspaces/sfu-library-thinclient/data/thinclient_index \
    --top-k 50 --rerank embed+ce \
    --out data/eval_results/dense_ablation_A_nodense_<YYYYMMDD>.json

# 2) arm B — dense leg on, fresh process. (SFU_DENSE_LEG=1 was NOT needed when
#    the arms ran 2026-08-18 — the leg was default-on then. Since the
#    post-verdict flip it is REQUIRED, or this "arm B" silently reruns arm A.)
SFU_DENSE_LEG=1 SFU_DENSE_WARMCACHE=0 \
  .venv/bin/python3 scripts/experiments/eval_pipeline.py \
    --queries data/eval_results/dense_ablation_queries.json \
    --judge-cache data/eval_results/dense_ablation_judge_cache_20260817.json \
    --index-root /workspaces/sfu-library-thinclient/data/thinclient_index \
    --top-k 50 --rerank embed+ce \
    --out data/eval_results/dense_ablation_B_dense_<YYYYMMDD>.json
```

**Two things in that command are load-bearing and were not in the pre-2026-08-18
version of it:**

1. **`--judge-cache` must be passed.** `eval_pipeline.py` defaults to
   `llm_judge_cache.json`, which holds the **contaminated** set's judgments and
   knows **nothing** about these 120 topics — an arm run without the flag scores
   every query against an empty gradebook and silently reports nDCG 0.
2. **`--index-root` must be ABSOLUTE.** `retriever._seismic_backend` only falls
   back to the default E8 dv-v2 shard manifest when its root **equals**
   `<repo>/data/thinclient_index`; a relative path fails that comparison, so
   `SFU_SPLADE_BACKEND=seismic` raises and the SPLADE leg **silently degrades to
   BM25F** (`bm25f∩splade@50 = 50`, i.e. one leg counted twice). This is the
   actual cause of the §8 smoke run's fake SPLADE leg.

`--rerank` defaults to `none` (a cheap retrieval-only record, no model loads);
the PRIMARY metric above is post-rerank, so the decisive arms must pass
`--rerank embed+ce`.

### Prerequisites — IMPLEMENTED 2026-08-17 (the ablation itself is still NOT RUN)

Both are code-only + synthetic-test changes; **no ablation measurement was
taken**, and the remaining blocker is unchanged: a **fresh judged query set**
with a HELD-OUT stratum.

**P1 — RRF leg provenance** (`src/lib/thinclient/retriever.py`). `search_rrf`
gained an **opt-in** `with_provenance: bool = False`; the default return shape
is exactly what it was, so every existing caller (serve path, `leg_breaker`'s
guardian — which fuses independently anyway, `portable_socsci/04_verify_serve`,
`wi8_portable_manifest`) is untouched. With the flag on, each returned doc
carries one extra key:

```python
{"openalex_id": "W…", "score": 0.0492…, "source": "thinclient_rrf",
 "rrf_legs": {"bm25f": 2, "splade": 1, "dense": 7}}   # leg → 1-based rank in that leg
```

`rrf_legs` is insertion-ordered in the fusion order (bm25f → splade → dense);
a leg that did not run is simply absent. A new
`search_rrf_detailed(query, top_k, filters, include_dense) -> {"results",
"legs", "leg_latency_ms"}` returns the same fused list **plus** each leg's own
pre-fusion ranking and its wall ms, from ONE retrieval pass — the shape an
offline analysis needs for leg-overlap@50 and per-leg cost. Fusion itself moved
into `_rrf_fuse` / `_rrf_legs`; the accumulation order, the float arithmetic and
the sort are unchanged. **Bit-identical ranking is a hard requirement and is
pinned by tests**, not asserted by inspection:
`test_rrf_provenance_is_opt_in_and_ranking_neutral` (synthetic, exact `==` on
the fused floats) and `test_search_rrf_ranking_unchanged_with_provenance` (the
real tantivy+BMP served path).

**P2 — `eval_pipeline.py` retargeted at the thin client**
(`scripts/experiments/eval_pipeline.py`). New `--engine {thinclient,opensearch}`,
**default `thinclient`**, driving `ThinClientRetriever.search_rrf_detailed` over
`--index-root` (default `data/thinclient_index`) with
`--queries/--top-k/--rerank/--out` (`--diverse-queries`/`--output` kept as
aliases). The OpenSearch-era behavior is preserved verbatim behind
`--engine opensearch` and warns that it is deprecated for this container; its
`REPO_ROOT` was also off by one directory since the script moved into
`experiments/`, so the legacy path could not have run as written.

The arms are selected **purely by environment** — the script never forces a leg
on or off; `SFU_DENSE_LEG` / `SFU_DENSE_WARMCACHE` are honored by
`retriever._load` and merely *recorded* (`config.env`,
`config.dense_leg_enabled`, `config.dense_vectors`, `arm: A_nodense|B_dense`),
so an arm file proves which arm produced it. Per-query record (key style follows
`parity_record_tc_seismic_e8dv2_20260817.json`, so arm B joins against the
cached 2-leg record): `query`, `judge_key`, `query_type`, optional `stratum`,
`bm25f`/`splade`/`dense` ranked id lists, `lat_<leg>_ms`, `rrf`, `rrf_scores`,
`rrf_legs`, and `final`/`lat_final_ms` when `--rerank != none`. A dense-free arm
emits **no `dense` key and no `dense` entry in any `rrf_legs`** — pinned by
`test_dense_leg_off_produces_no_dense_provenance`. nDCG@10, recall@50,
dense-vote share and leg-overlap@50 are all computable from those lists without
re-running retrieval; `summarize_thinclient` recomputes them inline as a
convenience (unit-tested on a hand-built record) but **the lists are the source
of truth**.

Verification 2026-08-17 (light only, per the chunk's scope — **no ablation
measurement**): `scripts/tests/test_thinclient_stack.py` **26 passed** (19 → 26,
+7 new); `scripts/tests/test_serve_query_log.py` 13 passed; two end-to-end smoke
runs of the new CLI — one on a synthetic 600-doc index root, one on the real
`data/thinclient_index` (see §8). Both prerequisites are therefore
**IMPLEMENTED; the thing they enable is UNMEASURED** — no ablation number
exists, and the blocker is still the fresh judged query set.

Record the ablation result in this section when it runs, with the absolute date,
the results-file paths, and the decision the rule produced.

---

## 8. Changelog

- **2026-08-18 (post-verdict)** — **`SFU_DENSE_LEG` DEFAULT FLIPPED to OFF**
  (operator direction, following the DROP verdict): unset ⇒ off, only the
  literal `1` enables; warm cache thereby inert by default. Stays off until
  the full corpus is dense-encoded and re-measured. §1 env-gates table + §6
  note updated; `test_dense_leg_env_gate` now pins default-off and
  only-"1"-enables (26/26 pass).
- **2026-08-18 (latest)** — §7 **ABLATION RUN — VERDICT: DROP.** Both arms
  executed (240 forms / 120 topics each, `--rerank embed+ce`,
  `SFU_DENSE_WARMCACHE=0`, fresh processes, integrity gates passed). Δ_all
  final nDCG@10 = **−0.0077**, 95% CI [−0.0153, −0.0001] — significantly
  negative; low-coverage (c≤0.10) Δ = −0.0184, also significantly negative; no
  band positive. Reranker rejects ~84% of dense-only fused-top-10 injections;
  Δ recall@50 = −0.028. Files: `dense_ablation_{A_nodense,B_dense,analysis}_20260818.json`,
  analysis script `scripts/experiments/dense_ablation_analysis.py`. Deviation
  recorded: page-cache drop between arms impossible in-container → cross-arm
  latency comparisons biased, quality unaffected. §6 updated (RESOLVED note).
- **2026-08-18 (later)** — §7 **PROTOCOL AMENDMENT ADOPTED: Option 2,
  dose-response over all 120 topics.** Operator chose it explicitly among the
  three recorded options; the amended decision rule (Δ_all ≥ +0.02 with 95% CI
  excluding 0 **and** a positive point estimate on the `c ≤ 0.10` low-coverage
  topics) was written into "Metrics + decision rule" and **committed before any
  arm was executed**. The ablation is unblocked; still NOT RUN as of this entry.
- **2026-08-18** — §7 **QUERY SET BUILT** (`scripts/experiments/dense_ablation_queryset.py`;
  **the ablation is still NOT RUN** — no arm was executed, no A-vs-B number
  exists, and nothing in this entry is an ablation result).
  - **The draw was committed before any judgment** (commit `e205269`): 120 new
    topics over the same 49 SFU subjects as `diverse_queries.json` with
    identical per-subject counts, 0 reuse of its `judge_key`s (both asserted at
    draw time), each with a keyword form + a natural-language paraphrase → 240
    query records.
  - **Pooling** (TREC-style, untimed, full 3-leg config so the pool holds what
    *either* arm could surface): top-50 per leg + fused top-50 per form, union
    over both forms per topic → **25,614 unique docs**, per-topic pool mean
    **216.0**. `search_rrf_detailed` + `rrf_legs` provenance recorded.
    `SFU_DENSE_WARMCACHE=0` throughout, so nothing was written into the served
    index root.
  - **SPLADE leg proven real before judging**: `bm25f∩splade@50` = **5.53** mean
    over 240 forms vs the parity run's 5.35 (a silent BM25F fallback reads 50);
    the `pool` stage aborts above 25.
  - **Judged** 25,919 pairs with **`claude-haiku-4-5-20251001`** via the
    `claude` CLI subprocess, 0–3 topical relevance on the **natural-language**
    form, prompt template `sha256:7141d7866e71a03d`, gain `2^grade − 1`. Grades
    0/1/2/3 = 8,729 / 6,019 / 4,643 / 6,528 → **11,171 relevant**. Abstracts:
    sidecars (58.1% title-only, evenly across legs) + OpenAlex backfill → 11.0%
    title-only, flagged per doc.
  - **Contamination fell 5×**: **17.98%** of relevant docs inside the served
    600k dense pool vs **90.3%** for `diverse_queries.json`; no topic above 50%
    coverage where the old set had 50/120 at 100%.
  - **The pre-registered binary stratification came out DEGENERATE — 4 HELD-OUT
    topics**, and this is structural, not sample size (rate 3.3% ⇒ ≈7 even at
    the 200-topic cap), because §7 requirement 3 correctly puts the dense leg's
    own top-50 in the judged pool. Recorded with the graded per-topic
    dense-pool-coverage bands and **three amendment options for operator
    sign-off**; none adopted here. **This is now the ablation's blocker.**
  - **First dense-leg overlap ever measured on the served index** (the gap §5
    named): dense∩bm25f@50 = **0.175**, dense∩splade@50 = **0.142** — nearly
    disjoint from both lexical legs. Settles neither §5 reading.
  - **Bug found and fixed in the judge harness** (would have silently corrupted
    the qrels): a reply that parsed as JSON but whose keys matched none of the
    batch ids counted as success, so every paper fell through to grade 0 with
    nothing logged. Two transient service windows wrote exactly that for 55 and
    then 25 **consecutive** topics — the contiguity in draw order is what
    exposed it as an outage rather than a content result. Now a majority of the
    batch ids must come back, an all-zero topic is retried in-run and then
    warned about, and `--repair` re-judges all-zero topics. Final state: **0
    all-zero topics of 120.**
  - **Doc correction (code is source of truth):** the §7 smoke entry below
    blamed a missing `SFU_SEISMIC_SHARD_MANIFEST` for its fake SPLADE leg. An
    unset manifest is fine — `_seismic_backend` defaults to the E8 dv-v2
    manifest. The real cause is a **relative `--index-root`**, which fails that
    default's absolute-path equality test. The §7 command block now pins an
    absolute root **and** `--judge-cache` (whose default,
    `llm_judge_cache.json`, knows none of these 120 topics and would score every
    arm nDCG 0).

- **2026-08-17** — doc created. `SFU_DENSE_LEG` gate + graceful-degradation
  tests landed in commit `1ebfd78` (`src/lib/thinclient/retriever.py`,
  `scripts/tests/test_thinclient_stack.py`; the gate was authored for this doc
  and was absorbed into that commit by a concurrent staging race in the shared
  working tree — the content is intact and pushed). Contamination measured:
  `scripts/experiments/dense_pool_contamination.py` →
  `data/eval_results/dense_pool_contamination_20260817.json`. Ablation **NOT
  RUN** — blocker is a fresh judged query set, no longer the machine.
- **2026-08-17** — §7 **PREREQUISITES IMPLEMENTED** (code + synthetic tests
  only; **the ablation itself is still NOT RUN**, same blocker: a fresh judged
  query set with a HELD-OUT stratum).
  - P1 opt-in RRF leg provenance — `src/lib/thinclient/retriever.py`
    (`search_rrf(..., with_provenance=True)` → `rrf_legs`;
    `search_rrf_detailed()` → `results` + per-leg rankings + per-leg ms).
    Default return shape unchanged; bit-identical ranking pinned by
    `test_rrf_provenance_is_opt_in_and_ranking_neutral` and
    `test_search_rrf_ranking_unchanged_with_provenance`.
  - P2 `scripts/experiments/eval_pipeline.py` retargeted at the thin client
    (`--engine thinclient` default, `--queries/--index-root/--top-k/--rerank/--out`;
    the OpenSearch path preserved behind `--engine opensearch`, warned as
    deprecated). Arms selected by `SFU_DENSE_LEG`/`SFU_DENSE_WARMCACHE` only,
    and recorded in the output.
  - Tests: `scripts/tests/test_thinclient_stack.py` **26 passed** (was 19; +7:
    synthetic provenance, ranking-neutrality ×2, `search_rrf_detailed`,
    `SFU_DENSE_LEG=0` ⇒ no dense provenance, and 2 for the harness's pure
    functions). `scripts/tests/test_serve_query_log.py` 13 passed. (The legacy
    `src/tests/test_thinclient.py` has 3 failures — `test_sections_disjoint_and_complete`,
    `test_splade_leg_via_bmp`, `test_abstract_sidecar_roundtrip` — verified
    **pre-existing** by stashing the change and re-running; unrelated to RRF.)
  - **SMOKE ONLY, decides nothing:** one 3-query run against the real
    `data/thinclient_index`, arm B (`SFU_DENSE_WARMCACHE=0`, dense leg default-on,
    `dense_vectors=600000`, `--rerank none`, top_k 50) →
    `data/eval_results/dense_ablation_smoke_B_20260817.json`. It proves the
    surface end-to-end (3/3 queries recorded, all three legs + `rrf_legs`
    present). **Do not quote its numbers**: n=3, and the SPLADE leg fell back to
    BM25F (hence `bm25f_splade_overlap@50 = 50`, i.e. the two legs were the same
    leg). *(Cause corrected 2026-08-18 — it was NOT "the ambient env had no
    `SFU_SEISMIC_SHARD_MANIFEST`" as this entry originally said: an unset
    manifest is fine, `_seismic_backend` defaults to the E8 dv-v2 manifest. The
    real cause is a **relative** `--index-root`, which fails that default's
    absolute-path equality test. With an absolute root the leg is real —
    `bm25f∩splade@50` = 5.53 over the 240 §7 pooling forms.)* Two
    observations worth keeping as *directional, unreplicated*: the FIRST dense
    leg call cost **128,781 ms** (cold model load + cold 112 MiB usearch/int8
    memmap off 9p) against **176 ms** warm on the next query — consistent with
    §3's "the encode is the unmeasured dominant term" and with the wild dense
    timeout in `DEMO_DEPENDABILITY.md`; and `dense_vote_share@10 = 0.0` with
    `dense∩bm25f overlap@50 = 5` on the one keyword query — the first
    dense-involving overlap number ever recorded here, on 3 queries.
