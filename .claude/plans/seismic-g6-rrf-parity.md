# Plan — SEISMIC G6 RRF system-level parity (the load-bearing quality escape)

Branch: `spike/mmap-bmp` (continue on it; all SEISMIC work lives here).

## Why this run, and what it decides

`02_GO_NO_GO_GATES.md`: "G2/G6 fail → KILL SEISMIC." G2 **failed** (overlap@10 0.479
vs ≥0.95) and is now proven **non-tunable on every index-time pruning lever** (sweeps
#1 `max_fraction` + #2 `n_postings` to the selection-saturated ceiling, both bit-identical
to 0.4794). Two escapes from KILL remain: `centroid_fraction` (cheap, low-expectation —
not a posting-retention lever) and **G6 RRF system parity** — the load-bearing one.

G6 ≠ G2. G2 is the *leg-level* bar (SEISMIC-vs-Qdrant candidate overlap ≥0.95, strict).
G6 is the *system-level* bar: with SEISMIC as the SPLADE leg inside the live
`RRF(BM25F, SPLADE)` stack, does LLM-judged NDCG@10 stay within **±0.005 of 0.560**?
RRF is rank-fusion — a leg whose candidate set diverges at 0.479 can *still* fuse to
near-identical NDCG as long as the relevant docs appear somewhere in each leg's top-k.
So the 0.479 does **not** auto-foreclose G6. This run measures whether that holds.

## Locked decisions (user-confirmed)

1. **Judging regime = cached judge** — reuse `llm_judge_cache.json` via
   `eval_thinclient_parity.py compare` (the exact regime that produced 0.560, so the
   ±0.005 bar is apples-to-apples). Offline-capable — Qdrant/OS down + no API key do not
   block. **Side-fix (same-commit, per CLAUDE.md doc-freshness):** `03_BENCHMARK_METHODOLOGY.md`
   row-G6 names `benchmark_llm_judge.py` as the G6 instrument; that's a fresh Haiku judge
   that did NOT produce 0.560. That's the same conflation class the `b2-baseline-provenance`
   memory flagged. Fix the row to name the actual instrument (`eval_thinclient_parity.py compare`
   over the cached judge) AND keep `benchmark_llm_judge.py` as an optional stronger
   cross-check with an explicit "requires API key + OpenSearch; re-judge baseline too" caveat.
2. **Corpus scope = persona 2M, matched scope** — both treatment and baseline legs search
   the SAME ~2M med_bio oaids (the SEISMIC index's doc set), 34-common queries. Honest
   2M-vs-2M. **0.560 is full-corpus; it is a DIRECTIONAL anchor for the persona run, not the
   matched anchor** — the persona-matched anchor is the recorded persona Qdrant-SPLADE RRF
   number, computed this run. Report both: persona-matched |Δ| (the gate verdict) AND the
   persona-vs-fullcorpus relation (context, caveat).

## The measurement, precisely

- **Treatment:** `RRF_k60( persona_BM25F_leg, persona_SEISMIC_splade_leg )` NDCG@10 (34-common).
- **Baseline:** `RRF_k60( persona_BM25F_leg, persona_Qdrant_splade_leg )` NDCG@10 (34-common),
  same BM25F leg, same oaids, same judge — re-recorded (G2's cache saved only top-10; RRF fuses top-50).
- **Bar:** |treatment − baseline| < 0.005 (the persona-matched G6 bar). Plus directional
  compare to 0.560. "Degrade paths intact" = report BM25F-only and leg-level NDCG too, so a
  SEISMIC-leg regression can't hide behind RRF gains.

## Provenance (resolved this session, do NOT re-conflate)

The "0.560" the gate bars against = **thin-client (qdrant SPLADE), 34-common-subset mean =
0.5597 → 0.560**, source `data/eval_results/thinclient_parity_qdrant_20260625_0001.json`
(2026-06-25). The all-39 headline is 0.5378. The BMP-SPLADE twin is 0.561 (34-common) /
0.5368 (39). The ±0.005 bar is **narrower than** the 0.024 spread between the two valid subset
numbers — which is exactly why judging regime + corpus scope had to be pinned first.

## Environment (measured this session)

- Persona 2M SEISMIC index on disk + loadable: `/tmp/seismic_testbed/index/med_bio_2m.index.seismic` (1.69 GB). Built-from jsonl at `/tmp/seismic_testbed/jsonl/med_bio_2000000.jsonl` — `{id, vector}` only (no text).
- `SFU_SPLADE_BACKEND` env already read at `retriever.py:162`, switches on `"qdrant"` (default). Adapter exists at `scripts/seismic_testbed/seismic_backend.py` (standalone shim, **not yet wired into `ThinClientRetriever`** — its docstring says so).
- `llm_judge_cache.json` present; cached-judge path needs no API/Qdrant/OS.
- `record-tc` (`eval_thinclient_parity.py:177`) calls `retriever.search(q, TOP_K=50, mode="splade")`; `compare` re-fuses `rrf([bm25f, splade])` + scores via cached judge → **the treatment record is a one-env-var-flip + one-wiring if SEISMIC is bound**.
- Qdrant binary present: `.tools/qdrant/qdrant`. Collections on disk: `splade_par30` (34 GB), `splade_150m` (168 GB). **Qdrant is currently DOWN.**
- Persona BM25F: `data/thinclient_index/sections/med_bio__{archive,recent}` exist (sectioned), but no **built tantivy** persona index — builder is `src/lib/thinclient/builder.py` (`SectionBuilder`, reads `spool_backup` slices for text).
- Host RAM: 31G total, **9G available, 0 free** — the shared-gaming constraint from the BMP memory. Qdrant `splade_par30` bring-up is RAM-tense; sequence heavy steps singly.

## Steps

### A. Provenance + doc-freshness fix (cheap, first, same-commit as the wiring)
- A1. Fix `03_BENCHMARK_METHODOLOGY.md` §3 row-G6 instrument: `eval_thinclient_parity.py compare` (cached judge = 0.560 regime) as primary; demote `benchmark_llm_judge.py` to "optional stronger cross-check — requires ANTHROPIC_API_KEY + OpenSearch; must re-judge the 0.560 baseline under the same fresh regime for ±0.005 to be comparable." Add a provenance line stating 0.560 = qdrant-SPLADE 34-common (0.5597), not the all-39 headline (0.5378). (This is the `b2-baseline-provenance` doc-drift the memory was written to prevent.)
- A2. Verify `0.560`'s source file (`thinclient_parity_qdrant_20260625_0001.json`) still reproduces the number from its stored legs offline (no Qdrant) — proves the baseline record is reusable as the matched-anchor's BM25F+SPLADE leg source if Qdrant can't be brought up.

### B. Wire SEISMIC as a `ThinClientRetriever` SPLADE backend (the gating code change)
- B1. In `src/lib/thinclient/retriever.py`, where `SFU_SPLADE_BACKEND` is read (`:162`) and the `"qdrant"` branch lives (`:566`), add a `"seismic"` branch that instantiates `SeismicBackend` (import from `scripts/seismic_testbed/seismic_backend.py`, or relocate the class under `src/lib/thinclient/` so it's importable by the served retriever — decide: relocate + re-export, since serving paths shouldn't import from `scripts/`).
- B2. SEISMIC needs the index path + model path (config/env: `SFU_SEISMIC_INDEX` → default `/tmp/seismic_testbed/index/med_bio_2m`). Wire so an unset index path raises a clean `RuntimeError` (mirrors the existing `SFU_LOAD_MEM_FLOOR_GB` clean-error pattern), never a silent fallback.
- B3. `SeismicBackend.search` must return the same shape `retriever.search(..., mode="splade")` expects (`list[dict]` with `openalex_id` + `score`), so RRF fusion (`search_rrf`) and `record-tc` records are byte-compatible with the Qdrant leg. Confirm the id it returns (`openalex_id` string) joins on the parity harness's `oaid`.
- B4. Never wire into a live served path here — this is the testbed adapter behind an env gate. Add a docstring line: "testbed-only; not a served Path-A-GO decision."

### C. Arm the persona BM25F leg (the matched-2M scope requirement)
- C1. Build a persona tantivy (BM25F) index over the ~2M med_bio the SEISMIC index holds, sourcing `title`+`abstract` from `data/thinclient_index/spool_backup/med_bio/slice_*.jsonl.zst` via `src/lib/thinclient/builder.py` (`SectionBuilder`). The corpus must be the **same oaids** as the SEISMIC index (assert set-equality against `/tmp/seismic_testbed/jsonl/med_bio_2000000.jsonl` ids, like G2's scope-assert at `eval_seismic_parity.py:210`).
- C2. RAM-tense host: build with throttled writer (`nice -n 19`, modest heap), single pass; if OOM-risky, build from a 2M subset of slices. Record build time/RSS as a sidecar (informs G9 cost later).
- C3. **Fork if C is heavy:** if a full 2M persona tantivy build is blocked by RAM/time this session, the cheap-first alternative is `--max-queries` smoke (e.g. 10 queries) to prove the pipeline end-to-end before the full 34. Mark full-34 as the gated completion.

### D. Record the two parity legs (offline compare-friendly)
- D1. **Treatment record:** `SFU_SPLADE_BACKEND=seismic` + `SFU_SEISMIC_INDEX=.../med_bio_2m`, `record-tc --index-root <persona index root> --queries 34` → records BM25F + SEISMIC-splade top-50 per query.
- D2. **Baseline record:** same BM25F leg (same index-root), Qdrant-SPLADE leg scoped to the SAME 2M med_bio oaids. **Sub-fork on Qdrant availability:**
   - If Qdrant bring-up is feasible (`.tools/qdrant/qdrant` + `splade_par30`, 9G free is tight): start it throttled, use the G2 scoping path (deep over-fetch 500k + client-side med_bio filter, per `eval_seismic_parity.py:97-160`), record top-50 → `record-tc`.
   - If Qdrant bring-up is NOT feasible this session (RAM): **record the persona Qdrant-SPLADE top-50 is the one step that needs live Qdrant** — defer D2 to a follow-up, and in the meantime run G6 **treatment vs the full-corpus 0.560 directional anchor only**, clearly labelled "baseline leg pending Qdrant bring-up." Do NOT emit a PASS/FAIL verdict against the persona bar without the persona baseline.
- D3. `compare --tc-record <treatment> --tc-record <baseline-as-second>` — actually: `compare` joins a `tc-record` against an `os-record`; for matched-tc-vs-matched-tc I may need a small adaptation, OR compute persona RRF NDCG@10 for both records inline. Confirm the `compare` shape supports two tc records; if not, extend `_summarize` minimally to accept a second tc record as the matched baseline (keep the existing os-join path intact).

### E. Score + verdict (cached judge, 34-common)
- E1. Compute, for treatment and baseline: `tc_rrf_ndcg@10` mean (34-common), BM25F-only NDCG, and per-leg NDCG. Write `data/eval_results/seismic_g6_rrf_persona_2m.json` with the 03 §3 result-file slot schema (`meta`/`g6_verdict`/per-query).
- E2. **G6 verdict logic** (honest, two-sided):
   - persona-matched: `PASS` iff |treatment_rrf − baseline_rrf| < 0.005 (34-common) AND leg-NDCG delta not catastrophic.
   - directional vs 0.560: report |treatment − 0.560| as CONTEXT only, labelled "persona 2M vs full-corpus anchor — not the gate bar."
   - If D2 was deferred (no Qdrant): verdict = `INCOMPLETE — treatment recorded, persona baseline pending Qdrant bring-up` (never a silent PASS).
- E3. "Degrade paths intact": explicitly report BM25F-only NDCG (the non-SEISMIC floor) so a SEISMIC win that's just BM25F carrying the query is visible.

### F. Doc + memory sync (same-commit per CLAUDE.md)
- F1. `02_GO_NO_GO_GATES.md` row-G6: fill the Measured column with the verdict + date + result-file path.
- F2. `06_FINDINGS.md`: add a "G6 RRF parity" section (date, numbers, script, result file) and update the open-gates list + current-one-line-status.
- F3. `03_BENCHMARK_METHODOLOGY.md` row-G6 result-file slot pointed at `seismic_g6_rrf_persona_2m.json`.
- F4. Update memory `seismic-testbed-p1-p2-results.md` with the G6 outcome; update `MEMORY.md` index line if the headline flips (KILL-hold → G6-green, or → KILL).

## Risks / honest caveats (pre-registered)
- **Persona ≠ full-corpus.** The persona-matched bar is the honest gate; 0.560 is directional. A persona PASS does not certify 150M serving quality — G7/G8 own that.
- **Qdrant bring-up under 9G free is the live risk for the matched baseline** (D2). If it blocks, ship the treatment record + an INCOMPLETE verdict rather than a false PASS — the CLAUDE.md efficacy rule forbids unlabelled optimism.
- **`compare` may not natively join two tc records** (D3) — a small harness extension, kept additive.
- A persona G6 PASS that leaves G2 at 0.479 means **the leg diverges but RRF absorbs it** — a legitimate "system survives" result, but it does not un-fail G2; both get reported as their own gates.
