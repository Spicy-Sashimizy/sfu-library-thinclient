# delta_ingest/ — source-agnostic trickle updates over the immutable base

**Status:** ACTIVE

**Opened 2026-09-29.** The served 150M index is frozen at the 2026-06-16 build;
its two rebuild inputs (the OpenSearch source, the 131 GB spool) are gone
(`THIN_CLIENT_SWAP.md` §Migration, `README.md` backlog). This track is the
answer to "how do we add or change documents without rebuilding the pool and
the eight SEISMIC shards", for ANY source (OpenAlex snapshot/API, arXiv,
Zotero, a JSONL/CSV of anything), at any ingest rate (a CPU laptop trickling
thousands of docs an hour or a GPU server freezing millions per generation).

It realises Stage 1 of the DEFERRED `semantic_docid_ingest/` design (its rule
was "build only when ingest becomes real"): rule-based section ids, a mutable
warm buffer, immutable delta generations, background compaction — without the
learned semantic id, which that track keeps.

| Doc | What |
|---|---|
| `01_RESEARCH.md` | Online research 2026-09-29 (OpenAlex incremental mechanics post-Walden; how Lucene/Vespa/Quickwit/Milvus/Qdrant/FreshDiskANN update immutable indexes; SEISMIC has no insert/merge; tantivy-py mutability; zstd dictionary drift) + the bespoke-vs-off-the-shelf verdict |
| `02_DESIGN.md` | The built design: canonical `DocRecord` + adapters, three tiers (L0 mutable buffer, L1 immutable generations, L2 base), newest-wins masks, compaction, resource profiles, **the engine-interaction matrix** (what every served engine does with a delta, and what it costs), **immutability efficiency issues** and their planned fixes |
| `03_SPIKE_PLAN.md` | Pre-registered measurements + bars M1–M8, the phase order, out-of-scope list, and the **2026-09-29 addendum**: M7 first, livedocs in scope, M9 twin-rebuild and M10 9-shard pilot pre-registered, results table |
| `04_IMMUTABILITY_RESEARCH.md` | Research conclusions 1–6 on updating immutable indexes and the full source list, every source marked [read]/[snippet]/inferred; measured contradictions noted beside conclusions 2 and 4 |
| `04_HANDOFF_2026-09-29.md` | Dated dispatch record 2026-09-29: items A–H with their outcome and commit |
| `../archive/inplace_update/` (`05`–`07`) | In-place bit-update spike (brief, pre-registration + results table, handover), **CLOSED MEASURED 2026-09-30**: its GO rule read NO-GO on S0-1 (long-list dead-slot coverage 0.019 vs 0.80). Not current; see `docs/README.md` Closed tracks |
| `08_INPLACE_POSTMORTEM_RESEARCH_2026-09-30.md` | Post-mortem literature pass 2026-09-30 (Opus research agent, every claim tagged [read]/[snippet]/inferred with URLs): with list growth — not slot reuse — as the obstacle, is any in-place route left? Verdict: nothing beats the delta layer at 27 % + 15 % quarterly churn; three candidates for the next pre-registration — (1) overlay-scored updates (old postings route, replacement vector scores; −65 % delta-shard docs *est.*), (2) posting-layer-only fold-in from the unchanged forward file, (3) SPFresh-style block maintenance (design only). Also flags the re-encode nnz mismatch (122.5 vs 87.6 nnz/doc) to verify first. **DESIGN ONLY, EFFICACY UNMEASURED** |

Code: `spike/delta_ingest/` (ingest side, CLI) · `src/lib/thinclient/delta_layer.py`
(serving reader, gate `SFU_DELTA_ROOT`, default OFF) · retriever hooks in
`retriever.py` · tests `scripts/tests/test_delta_ingest.py`.

**State 2026-09-29: IMPLEMENTED; serving efficacy UNMEASURED; gate default
OFF.** Synthetic end-to-end passes (buffer → generation → second generation →
compaction, newest-wins, deletes, SEISMIC delta-shard chain through c1a +
dotvbyte on 200 docs). Measured 2026-09-29 (`03_SPIKE_PLAN.md` addendum):
- M7 churn filter **FAIL** — touched:must-encode ≈1.15:1 and ≈2.61:1 (*est.*)
  vs a < 3:1 falsification bar; the ledger cannot filter base docs.
- M6 throughput RECORDED — adapter→buffer 402.9 (laptop) / 2,560.9
  (desktop_gpu) docs/s; ingest peak RSS 6.74 GB on both profiles.
- Livedocs bitset IMPLEMENTED (Python per-shard filter) — G1/G2 **PASS,
  PARTIAL 101/120 topics**; Rust gather-time skip DESIGN ONLY.
- Result-cache delta stamp (R1) DONE.
- Twin-shard rebuild (M9) — build chain measured, parity **FAIL** (0.9858 /
  0.9870 vs 0.99); SEISMIC-leg fold-in UNVERIFIED.
- M1 gate-off parity **PASS on the clean run** (fused + final top-10 120/120),
  1 pass per arm (plan fixes 2), measured on aa0fc405 — which predates C's
  livedocs serving code (6f5dd471). A first empty-root run FAILED as recorded
  (final 0/120) and is attributed to ENOMEM on `.venv` imports from the 9p
  mount (root cause unverified; `02_DESIGN.md` §3.1 O12).
- M4 read amplification **FAIL** (27.7 ms p50 per live generation vs +8;
  compaction half NOT MEASURED) and M5 reload **PASS** (≤ 1.8 s, first query
  ≤ 1.82× warm) — measured 2026-09-29/30, folded into `03_SPIKE_PLAN.md`
  2026-09-30 (`spike/delta_ingest/M4_M5_FINDINGS.md`).
- M8 sidecar ratio **RECORDED 2026-09-30**, lever not triggered (0.31–0.36× the
  base on corpus (b), which is 90% duplicate dataset abstracts; 1.47–1.51× on
  article-like subsets, base-dict reuse makes it worse). O1/O3/O9 **FIXED
  2026-09-30**; O2, O13 open (`02_DESIGN.md` §3.1).
- Base-hash seed (O4) **BUILT + MEASURED 2026-09-30, PASS**: seeded, the ledger
  reproduces M7's exact proxy (3.959:1 / 3.408:1 among in-base docs); M7's FAIL
  stands (whole-partition ≈ 1.01–1.16:1, mostly new works). O5/O6 fixed; full
  seed *est.* ~24.6 h; O14–O17 opened (`02_DESIGN.md` §3.1).
- **M2 PASS** and **M3 PASS** 2026-09-30 (partial N: 1,352/2,000 queries,
  350/600 titles): delta-shard recall ratio 1.159 at k=10, overlap vs exact
  0.9968–1.0, 0 mask leaks; 1/1,200 fused top-10 slots displaced, median
  rank change 0, delta copies score 0.982× their base copy (T1 reversed).
  Promotion rule: gate stays OFF on **M4 alone**.
- Still open: M2/M3 at full N; M4 compaction
  half + sequential federation; M1 on a second pass and on post-6f5dd471
  code; 9-shard pilot NOT RUN; the M4 follow-up pre-registration.
  Serving latency/quality claims in `02_DESIGN.md` stay *est.*
