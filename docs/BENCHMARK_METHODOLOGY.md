# Benchmark Methodology: Old vs New

**Last updated:** 2026-06-18  
**Context:** Explains why the citation-count benchmark was replaced and how the LLM-judged method works; plus the 150M thin-client-vs-OpenSearch parity method and measured results (see last section).

---

## The Problem: Citation Count Was Marking Its Own Homework

The original benchmark (`scripts/ndcg_splade_eval.py`, result at `data/eval_results/ndcg_splade_eval_20260515_0420.json`) used **OpenAlex `cited_by_count`** as the relevance signal.

### How it worked (old method)

1. Run query against local OpenSearch → get 10 results from BM25F, SPLADE, RRF
2. For each returned paper, call the OpenAlex API to fetch its `cited_by_count`
3. Treat citation count as a relevance score (higher citations = more relevant)
4. Compute NDCG@10 from those citation scores

### Why this was wrong

**Bug 1 — Fame ≠ fit.**  
Citation count measures how famous a paper is globally, not how relevant it is to the query. A 1988 paper with 5,000 citations is not more relevant to "Northern Gateway pipeline environmental assessment BC" than a 2022 paper with 40 citations that directly addresses it. SFU's niche subjects (Indigenous Studies, Labour Studies, Canadian Studies, Latin American Studies) structurally produce papers with low citation counts — they are small disciplines. SPLADE was correctly finding relevant papers and being penalized for returning them.

**Bug 2 — search_by_topic was tautological.**  
`search_by_topic` sorts OpenAlex results by `cited_by_count:desc`. If you then grade performance by `cited_by_count`, you are measuring whether the sort worked — not whether results are topically relevant. OpenAlex's own sort scores NDCG ≈ 1.0 by definition. Any local retriever that returns a different ordering (finding more relevant but less famous papers) scores lower. This is textbook circular evaluation.

### The numerical evidence

Same 120 queries, same retrieval methods. Only the grading signal changed:

| Method | Old NDCG (citation proxy) | New NDCG (LLM judge) | Ratio |
|--------|--------------------------|---------------------|-------|
| SPLADE mean | 0.2586 | 0.6534 | **2.5× understated** |
| RRF mean | 0.2724 | 0.6362 | **2.3× understated** |
| Old max score | 0.6569 | 1.0000 | ceiling was capped |

**6 queries scored below 0.05 NDCG under the old method.**  
When the LLM judged those same queries for topical relevance, average score was **0.817**.  
The most extreme case: `Canadian documentary film Indigenous representation` scored **0.000** (papers not famous enough) but **0.986** (papers perfectly on-topic).

---

## The New Method: TREC-Style LLM Judging

**Script:** `scripts/benchmark_llm_judge.py`  
**Judge backends (`--judge`):**
- `claude` (default) — `claude-haiku-4-5-20251001` via `claude -p` subprocess (no API key needed — uses Claude Code session)
- `ollama` — local Ollama REST, free (`--ollama-model`, `--ollama-url`)
- `neuralwatt` (added 2026-06-29) — OpenAI-compatible `POST {NEURALWATT_BASE_URL}/chat/completions`, reads `NEURALWATT_API_KEY` / `NEURALWATT_BASE_URL` / `NEURALWATT_MODEL` from `.env`. Use a `-flex` model id (e.g. `kimi-k2.7-code-flex`) for NeuralWatt's discounted async tier. **`NEURALWATT_MAX_TOKENS` default = 2048** (was 512 — Kimi is a reasoning model; the 512 budget was exhausted by reasoning → empty `content`); raise it for larger batches. `_call_neuralwatt` raises a retryable error on null/empty content (with `finish_reason` + max_tokens hint) rather than crashing. Note: NeuralWatt is OpenAI-compatible ONLY (the Anthropic Messages API `/v1/messages` returns HTTP 403), so the `claude` CLI cannot be pointed at it — this backend is for re-baking `llm_judge_cache.json` only, not for routing the CLI. **Re-bake / agreement study 2026-06-29** (`scripts/seismic_testbed/kimi_vs_haiku_rebake.py`): re-judged a stratified 10-query / 343-pair sample with `kimi-k2.7-code-flex` against the existing Haiku cache (read-only; never writes it). **Kimi ≠ Haiku regime:** exact agreement only 50.1%, within-1 75.8%; Kimi mean grade 1.74 vs Haiku 2.01 (Kimi ~0.27 stricter); 35/181 (19%) of Haiku-grade-3 docs Kimi marked grade-0 → a full Kimi re-judge would shift NDCG, so it is NOT a drop-in swap for the Haiku cache G6 commits against. Result `data/eval_results/kimi_vs_haiku_rebake_20260629.json`. **Wired to SEISMIC 2026-06-30** (`scripts/seismic_testbed/seismic_quality_eval.py`): routes the neuralwatt/Kimi judge onto the SEISMIC 150M mmap retrieval path (not OpenSearch) + OpenAlex metadata, with an **isolated Kimi cache** (`seismic_kimi_judge_cache.json`; the Haiku `llm_judge_cache.json` is never touched). First result (120 q, 100% metadata coverage): **SEISMIC NDCG@10 0.944 / MRR@10 0.996 / P@10(≥2) 0.773** (`seismic_quality_kimi_20260630_084905.json`; see `seismic_150m_testbed/06_FINDINGS.md` 2026-06-30 row). Kimi-judged → NOT directly comparable to the Haiku baseline numbers below.  
**Results:** `data/eval_results/benchmark_llm_judge_final.json`  
**Report:** `data/eval_results/benchmark_report_final.md`

### How it works

1. **Retrieve** top-10 results from all four methods per query: BM25F, SPLADE, RRF, OpenAlex relevance sort
2. **Pool** — merge unique papers across all methods into one pool of ~25-30 papers per query (TREC-style pooling so no method is disadvantaged)
3. **Judge** — Claude Haiku reads each paper's title + abstract and scores it 0-3:
   - 3 = perfectly relevant (directly answers the query)
   - 2 = highly relevant (strongly related)
   - 1 = marginally relevant (tangential)
   - 0 = not relevant
4. **Cache** — all judgments written to `data/eval_results/llm_judge_cache.json` — reruns are free
5. **Score** — NDCG@10, MRR@10, P@10(≥2) computed per method using the Haiku scores as ground truth

### Why this beats citation count

- **Independent judge:** Haiku cannot favor any retriever because it sees papers without knowing which method returned them
- **Topical relevance, not fame:** Haiku reads the actual content and decides if it answers the query
- **No tautology:** The judge is completely decoupled from the sort logic of any retriever
- **Works for niche subjects:** Haiku can assess relevance of a 2023 paper on Musqueam land rights just as well as a 2001 paper on protein folding

### Performance

- 4 parallel subprocess workers → ~5-8 min for all 120 queries (cold)
- Cached reruns → ~1-2 min (cache hit rate ~100%)
- Cost: $0 additional — uses Claude Code's existing session

---

## Key Takeaway

The old benchmark made local search *look* worse than it was by 2.3-2.5×. The LLM-judged benchmark reveals that SPLADE and RRF are finding highly topically relevant papers on 32 of 34 subjects with local index coverage. The low mean NDCG (0.63-0.65) is caused by 15 zero-coverage subjects scoring 0.0, not by retrieval failing on covered subjects.

---

## Running the parity eval at 150M (the RAM wall + how to get numbers anyway)

`scripts/eval_thinclient_parity.py` compares the thin-client stack against the
OpenSearch baseline. The hard constraint at 150M is RAM, and the cause is
specific: **BMP (the SPLADE engine, 0.2.6) has no mmap mode** — `bmp.Searcher`
deserializes each `*.bmp` shard into **anonymous RAM at a measured 3.07×** its
on-disk size (probe 2026-06-17: 569 MB shard → 1747 MB resident; ratio holds
12 MB–569 MB). The full 150M SPLADE leg is **68.6 GB on disk → ~211 GB resident**
(NOT the "~104 GB mmap" earlier docs claimed — that 104 GB is on-disk total;
tantivy/`meta.sqlite`/dense are genuinely mmap/paged and stay ~0 resident). So
even one engine cannot be held in a single process on the 24 GB host (capped via
`.wslconfig` 2026-06-17), let alone both.

`retriever._load()` now samples `MemAvailable` before each shard and aborts with
a clean `RuntimeError` (gate `SFU_LOAD_MEM_FLOOR_GB`, default 1.5) instead of
being SIGKILLed mid-construction. The legacy `combined` single-process mode is
refused by default for the same reason.

### Section-shard-wave eval — gets 150M numbers on the 24 GB host (added 2026-06-17)

`scripts/eval_parity_section_waves.py run` produces a record-tc-schema file
without ever holding the SPLADE set in one process. It exploits the fact that the
legs **already merge across sections/shards by plain score-concatenation**:

- **BM25F** runs on tantivy (mmap, ~0 resident) in one pass via the retriever's
  `SFU_SKIP_BMP=1` flag (load tantivy/meta/dense, skip BMP). Output is identical
  to `record-tc`'s bm25f field (same code path).
- **SPLADE/BMP** scores are corpus-independent dot products, so each shard's
  top-K is recorded in a **fresh process per wave** (the only way to free BMP
  RAM — the retriever has no `close()`), and merged offline. First-fit-decreasing
  bin-packs shards into waves under `--resident-budget-gb` (default 8).

This is **exact, not approximate** — validated 2026-06-17 on `data/thinclient_1m`:
wave-merged output is byte-for-byte identical to a direct full `record-tc` on both
legs, all queries. The OpenSearch side is recorded separately (`record-os`, its
own container, low RAM) and joined by `compare` (pure offline set-math + judge
cache, no engine live). Time-, not RAM-, bound: it reads the 68.6 GB BMP set once.

```bash
# thin-client record on a small host (≈43 min at 150M, 27 waves, 8 GB budget):
scripts/eval_parity_section_waves.py run --index-root data/thinclient_index \
    --queries 40 --resident-budget-gb 8 --output <tc_record.json>
# OpenSearch baseline (separate process):
scripts/eval_thinclient_parity.py record-os --baseline-url <url> --queries 40 --output <os_record.json>
# join → summary:
scripts/eval_thinclient_parity.py compare --tc-record <tc_record.json> --os-record <os_record.json> --output <summary.json>
```

The `run_parity_safe.sh` record-then-replay split (one engine per process, page-
cache drops, `MemAvailable` preflight, in-loop mem-floor guard) only helps once a
single process can hold one whole engine (~232 GB for the current load-into-memory
BMP — an eval-path figure, **not** a serving-host recommendation; see the
serving-RAM box in `STORAGE_BUDGET_150M.md`). At 24 GB its `record-tc` still OOMs
in `_load()`, so use the wave eval instead.

### MEASURED 150M parity (2026-06-18, first full-corpus run)

40 diverse queries, LLM-judged NDCG@10 (same judge cache + method as above),
thin-client (full `data/thinclient_index`) vs the 150M OpenSearch baseline.
Thin-client recorded via section-shard-waves (27 waves, 8 GB budget, ~43 min,
min RAM 15.4 GB available, peak swap 2.1 GB — no OOM).

**NDCG@10 on the common judged set** (34 queries with a judged doc in *both*
engines — apples-to-apples, equal denominator):

| Metric | Thin-client (150M) | OpenSearch (150M) | Δ |
|---|---|---|---|
| RRF NDCG@10 | **0.561** | 0.449 | **+0.112** (tc better) |
| Per-query wins | **29 / 34** | 5 / 34 | tc wins 85% |

Overlap@50 vs OpenSearch baseline (agreement, not quality — different engines):
bm25f **0.532**, splade **0.399**, rrf **0.476**.

As-reported means (unequal denominators, for the record): tc_rrf 0.537 (39 judged
queries) / os_rrf 0.449 (34); recomputed on the common 34 for fairness above.
NDCG coverage is judge-cache-limited (34/40 queries gradable). **Latency is NOT
comparable** across these runs (different hardware; tc splade latency is
reconstructed encode+search, hydration excluded) — reported in the summary for
completeness only, not as a head-to-head.

Records: `data/eval_results/thinclient_parity_waves_150m.json` (summary),
`parity_record_tc_waves_150m.json` (tc), `parity_record_os_20260618_0028.json`
(os). Full architecture context: `THIN_CLIENT_SWAP.md`; serving-RAM math:
`STORAGE_BUDGET_150M.md`.

## BMP↔Qdrant live-index fidelity gate + presentation metrics suite (added 2026-06-24)

BMP-decommission (see `docs/bmp_decommission_plan/PLAN.md`) added two new
metric families, recorded here per the new-module efficacy rule.

### Live-index quant fidelity (Workstream B1)

**WHAT:** Is the live production Qdrant index a faithful replacement for BMP's
8-bit block-max scoring? The f32 (Qdrant) leg is now scored against the **live
`splade_150m` collection** (the exact serving index) instead of an in-memory
recompute, so the gate uses the real index. BMP-quant and Qdrant-f32 are compared
on overlap@10/@50, Kendall-τ, and head-to-head NDCG@10 over the union universe.

**NUMBERS (30M in-memory gate, 2026-06-19, the prior baseline):** overlap@10
**0.9875**, overlap@50 **0.9885**, Kendall-τ **0.9716**, NDCG@10 f32 **0.8681**
vs quant **0.8681** (Δ **0.0000**) — engines tie exactly. Gate (overlap@10 ≥ 0.98,
τ ≥ 0.97, |Δ| ≤ 0.005) **PASSES**. Structural backstop: Qdrant sparse search is
exact; BMP is block-max approximate (WAND), so recall(qdrant) ≥ recall(bmp).

**Live-150M run (2026-06-24, MEASURED):** true head-to-head on the live
`splade_150m` index's own retrieved set — Qdrant returns the live top-cand hits
with their STORED f32 vectors (`with_vectors=True`), and the query is scored
against those SAME docs BOTH as raw f32 (Qdrant's exact scoring) AND as BMP ×70
8-bit (`min(255,max(1,round(w*70)))` doc + `max(1,round(w*70))` query top-64) —
isolating the quantization-reordering risk on the exact production index.
**overlap@10 = 1.0000, overlap@50 = 1.0000, Kendall-τ = 1.0000, NDCG@10 Δ =
0.0000** (f32 0.6039 = quant 0.6039 over 14 judged-coverage queries), across all
40 eval queries. Gate **PASSES** at 150M on the live index — the BMP ×70 8-bit
quant and Qdrant f32 produce identical orderings on the production index's
retrieved set. Corpus-size-independent by construction, so this generalizes.

**Script:** `scripts/eval_quant_fidelity.py --live-qdrant`.
**Result files:** `data/eval_results/quant_fidelity_30mscan.json` (in-mem
baseline), `quant_fidelity_live_150m_20260624_2345.json` (live). **Date:**
2026-06-24 (live), 2026-06-19 (in-mem baseline).

### End-to-end RRF quality, qdrant backend (Workstream B2)

**WHAT:** Does the qdrant backend preserve the thin-client's RRF quality at
150M, and is it RRF-indistinguishable from the BMP backend? The retriever was
pointed at the live `splade_150m` Qdrant on_disk sparse collection
(`SFU_SPLADE_BACKEND=qdrant`) and recorded BM25F+SPLADE ids over the SAME 40
diverse queries / corpus / judge cache / RRF k=60 as the BMP baseline
(`thinclient_parity_waves_150m.json`), then compared offline against the
OpenSearch record. The qdrant run is OOM-safe on the 24 GB host because the
leg serves from disk (no ~211 GB BMP load) — a side-benefit that makes the
full-corpus record-tc path viable for the first time.

**NUMBERS (150M-live, 2026-06-25, MEASURED):** tc-qdrant RRF NDCG@10 = **0.5378**
(39 judged headline) and **0.560** (34-query common subset — apples-to-apples
with OpenSearch's 34-judged denominator) vs the BMP baseline 0.5368 / 0.561.
**|Δ| = +0.0010 (39-judged) / −0.0009 (34-common)** → the two SPLADE backends
are RRF-indistinguishable at 150M (< 0.001 on both subsets). The OpenSearch win
is preserved identically: tc beats OS **+0.111** (common-34), **wins 29/34**
— the same win count as the BMP baseline. Per-leg overlap@50 vs OS unchanged
within noise (bm25f 0.532, splade 0.395, rrf 0.475). B2 gate (RRF qdrant vs
BMP within noise + still beats OS) **PASSES**.

**Script:** `scripts/eval_thinclient_parity.py compare` (record-tc via
`SFU_SPLADE_BACKEND=qdrant`).
**Result files:** `data/eval_results/thinclient_parity_qdrant_20260625_0001.json`
(compare summary, provenance-stamped), `parity_record_tc_qdrant_20260625_0001.json`
(tc record vs the live index). Baselines: `thinclient_parity_waves_150m.json`
(BMP backend) + `parity_record_os_20260618_0028.json` (OpenSearch).
**Date:** 2026-06-25.

### Presentation metrics aggregator + catalog (Workstream C1)

**WHAT:** One consolidated, presentation-ready metrics suite comparable to the
`sfu-library-mcp-training` baselines (same NDCG@10/MRR@10/P@10 definitions,
RRF k=60, `claude-haiku-4-5-20251001` judge + reused cache). Every number is
labeled with metric/k/corpus/source-file/absolute-date and tagged
`comparable-to-training` vs `new` (parity/ops, no training equivalent).

**NUMBERS:** 42 metrics cataloged, **all `measured`** (no est./unmeasured false
claims) — quality (BM25F/SPLADE/RRF/OpenAlex NDCG@10/MRR@10/P@10 + the B2
tc-qdrant vs BMP-vs-OS RRF rows), parity (BMP-vs-Qdrant overlap/τ/NDCG-Δ +
tc-vs-OS overlap@50 for both backends), ops (Qdrant latency p50/p95 at 150M
RAM-bound + 30M fitting-tier, resident RAM, on-disk size, ingest throughput).
Canonical ledger: `data/eval_results/METRICS_CATALOG.json`.

**Script:** `scripts/build_presentation_metrics.py --rebuild`.
**Result files:** `data/eval_results/METRICS_CATALOG.json`,
`presentation_metrics_<date>.json`. **Rendered:** `docs/bmp_decommission_plan/
{PRESENTATION_METRICS.md, METRICS_CATALOG.md}`. **Date:** 2026-06-24.
