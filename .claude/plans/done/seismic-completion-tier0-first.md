# SEISMIC completion — Tier 0 (shard-free) first, then the rebuild

## What the verification found (2026-06-30)

The prior check said: shards gone, served path can't load, Tier 0 #1 is "cheap,
cache-warm, do first." **Half right.** What actually happened:

- `/tmp/seismic_testbed/` is **fully gone** — confirmed. The 8 mmap shards
  (`.mmap/`), the G7 source `.index.seismic` files, AND the per-section spool
  jsonl are all wiped. The C2.5 manifest still points all 8 at `/tmp/...` → the
  served path **would RuntimeError** today. This part of the prior analysis is
  correct and is the real deployment blocker (Tier 2 #4).
- **BUT** the SEISMIC *quality* verdict (Tier 0 #1) does **not** need the shards.**
  `seismic_quality_eval.py` loads shards (shard-blocked) — but it is the wrong
  path now. SEISMIC's retrieved top-10 IDs for the **exact same 120 parity
  queries** the Qdrant record uses are already stored in
  `data/eval_results/seismic_g6_rrf_fullcorpus_n120_20260629.json`
  (`seismic_top10`, 120/120 complete, 120/120 queries identical to the parity
  record). Re-judging those stored IDs with the identical Kimi judge + isolated
  cache produces the matched 120-query head-to-head — **no shards, no rebuild.**

### The actual Tier 0 #1 cost (measured, not estimated)
- SEISMIC SPLADE leg, 120 queries × top-10 = 1200 `(judge_key, W-id)` pairs.
- **731 already in the Kimi cache** (shared docs with the Qdrant leg), **469
  NeuralWatt calls needed** ≈ **$0.94, ~10 min.** Genuinely cheap + cache-warm,
  exactly as hoped — just via stored records, not `seismic_quality_eval.py`.
- The comparison baseline is already done:
  `rejudge_kimi_qdrant_n120_20260630_2041.json` → Qdrant SPLADE ndcg@10 = **0.9065**
  (n=120, Kimi-judged). Waiting on the SEISMIC leg.

## Sequencing (deviates from literal instruction — see below)

### Phase A — Tier 0 #1, now (shard-free, ~$1, ~10 min)  ← START HERE
Write `scripts/seismic_testbed/rejudge_seismic_leg_n120.py`: a tiny sibling of
`rejudge_stored_records.py` that reads the G6 fullcorpus record's `seismic_top10`
per query, fetches OpenAlex metadata, judges with `benchmark_llm_judge` in
`neuralwatt` mode against the same isolated `seismic_kimi_judge_cache.json`,
scores NDCG@10 / MRR@10 / P@10(>=2) / mean-grade (identical definition to the
SEISMIC 0.944 eval + the Qdrant rejudge). Output
`data/eval_results/rejudge_kimi_seismic_n120_<ts>.json`. Then print the head-to-head.

Reuses `H.judge_query` / `H.ndcg_at_k` / `H.mrr_at_k` / `H.precision_at_k` and the
existing `fetch_metadata` (copied — no SEISMIC-backend import dep, same as
`rejudge_stored_records.py`). Checks the cache per `(judge_key, W-id)`; only the
469 miss-set hit the API.

### Phase B — Tier 0 #2, G6 fate (methodology, no compute)
Decided *after* seeing Phase A. If the SEISMIC vs Qdrant SPLADE paired delta is
small (SEISMIC leg ≈ Qdrant leg), G6's "mild SEISMIC-under, within noise" finding
holds → formally re-scope the RRF gate to the paired-delta interpretation (docs
already lean there) and record the SEM bound. If Phase A surfaces a real gap,
escalate to the n≥400 commitment. Record the decision in `docs/THIN_CLIENT_SWAP.md`
+ the G6 results doc the same session (per same-commit doc rule). **Needs your
call once the number is in** — I'll present, you decide.

### Phase C — Tier 2 #4, the rebuild (multi-hour, 25–60 GB RAM)  ← needs buy-in
The actual deployment blocker. `/tmp` data is gone but the upstream 150M corpus
**survives** at `data/thinclient_index/spool_backup` (123 GB, 5 sections,
verified). Rebuild chain, **all serial** (two concurrent stages OOM the 32 GB host):
1. `shard_spool.py` × 5 sections → 8 section-shards each
2. `build_plan01_150m_shards.py` → 8 global shards (~18.8M docs, G2-locked defaults,
   abort-rss 20 GB) — ~18 min/shard × 8 ≈ 2.5 hr
3. `convert_shard_to_mmap.py` (c1a bin **exists**, verified) → 8 `.mmap/` dirs, ~7 min

**The fix that matters:** output to a **persistent** path, not `/tmp` —
`data/seismic_150m/{jsonl,index}` (under the 230 GB `data/thinclient_index` volume
which has headroom; will verify free space before starting). Patch the two manifests'
paths to match. Verify the rebuild reproduces overlap@10 ≈ 0.9967.

This is gated on your go-ahead — it's hours of wall-clock and hogs the host.

### Phase D — Tier 1 #3, sequential-backend efficacy (blocked by Phase C)
`serve_footprint_bench.py --federation {parallel,sequential}` on the rematerialized
shards. Measures RAM/swap/latency — decides whether 150M serves on current
hardware (cheapest demo path). Currently UNMEASURED.

## Deviation from your literal instruction — flagging for sign-off
You wrote Tier 0 #1 as "Re-run `seismic_quality_eval.py` on the matched 120-query
file." I'm proposing **not** to do that, because it loads the gone shards (would
block on Phase C / force a 2.5-hr rebuild before any quality answer). The
stored-records path produces the *exact same* matched 120-query verdict for $1 in
10 min, independent of the shards. Same Kimi judge, same cache, same scoring
definition — just reading SEISMIC's already-stored retrieved IDs instead of
re-retrieving. The only thing it can't do is catch a retrieval drift since the G6
run, but that run was 2026-06-29 and the IDs are authoritative for that build.

## Non-goals this session (deferred to later sessions per your roadmap)
- Tier 2 #5 (boot-time pre-fault + encoder warm-up) — after Phase C/D land a
  measured serving path.
- Tier 2 #6 (wire into monthly rebuild pipeline).
- Tier 3 #7/#8 (default flip, deploy config).
