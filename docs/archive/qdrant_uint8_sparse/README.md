# qdrant_uint8_sparse/ — Qdrant sparse uint8 quantization spike ("move 1")

> **CLOSED SUPERSEDED 2026-09-25** — SEISMIC was promoted as the SPLADE engine 2026-07-06 (`docs/THIN_CLIENT_SWAP.md` §"What runs here now"), so the f32->uint8 Qdrant fallback this spike asks about is moot; Qdrant survives only as an env-gated rollback. Scaffold code left in place, inert and unmeasured. Not current; do not resume.

**Status:** CLOSED SUPERSEDED 2026-09-25

> **SUPERSEDED 2026-09-25.** This spike was opened 2026-06-27 as the fallback
> for the case where SEISMIC was killed on quality. SEISMIC was instead promoted
> as the SPLADE engine on 2026-07-06 (`docs/THIN_CLIENT_SWAP.md` §"What runs
> here now"); Qdrant on_disk survives only as an env-gated rollback, so the
> question this folder asks is moot. Not current; do not resume.
> Code committed 2026-09-25 before the folder was closed and left in place,
> inert: `scripts/archive/qdrant_uint8_sparse/eval_qdrant_uint8_sparse_small.py`,
> `scripts/archive/qdrant_uint8_sparse/test_qdrant_uint8_sparse.py` (17 passing when it lived in `scripts/tests/`; out of the suite since 2026-10-11), and a
> `--sparse-datatype` flag on `scripts/archive/spike_qdrant_sparse.py`.
> Environment fact recorded for whoever reopens it: no Qdrant engine exists on
> this host, and `qdrant_client` local mode ignores sparse `datatype` (stores
> f32), so G-RAM and G-LATENCY are unmeasurable without a real server.

**Opened 2026-06-27.** The cheapest fallback after the SEISMIC spike arced toward KILL
on quality (`../seismic_150m_testbed/06_FINDINGS.md`). Question: does quantizing the
Qdrant SPLADE sparse leg **f32 → uint8** (the sparse-index `datatype` knob) ease the
150M RAM/latency wall **on a host we already have**, while holding RRF NDCG@10 at 0.560?

No new engine, no JVM, no fork — a build-time config change on the live stack.

## Status: SCAFFOLD — nothing measured yet

- ✅ **Verified un-actioned** (2026-06-27): the live Qdrant sparse build
  (`scripts/archive/spike_qdrant_sparse.py:159`) uses `on_disk=True` but **no `datatype=`** →
  values default to f32. No `Datatype.UINT8` anywhere in `src/`/`scripts/`.
- ✅ **Mechanism cross-referenced** against Qdrant's own docs (sparse uint8 supported,
  ~4× searchable-index shrink, original values stay on disk, sparse quantizes in-flight
  so SPLADE needs no manual rescale) — see `00_VISION_AND_GOALS.md`.
- ❌ **G-QUALITY / G-RAM / G-LATENCY: UNMEASURED.**

## Files

| Doc | What it is |
|---|---|
| `00_VISION_AND_GOALS.md` | **Start here** — what we're deciding, verified starting state, online-sourced mechanism + citations, goals/gates, success/kill, evidence ledger |

## Next steps (to build out)

1. Build a uint8 (and a float16) twin of the 30M persona sparse collection from the same
   stored `sparse_field` (no re-encode) — extend `scripts/archive/spike_qdrant_sparse.py` with a
   `--sparse-datatype` flag.
2. Run G-QUALITY (overlap@10 vs f32 + RRF NDCG@10 34-common) and G-RAM/G-LATENCY at 30M.
3. Promote the winning datatype into the live build only if G-QUALITY holds ±0.005; then
   update `STACK_COST_MATRIX.md` (move-1 row est. → measured), `THIN_CLIENT_SWAP.md`,
   `STORAGE_BUDGET_150M.md`.

## Cross-refs

- `../qdrant_vs_lucene_assessment/STACK_COST_MATRIX.md` — where "move 1 (uint8)" is proposed.
- `../qdrant_vs_lucene_assessment/QDRANT_VS_LUCENE_RAM.md` / `FINDINGS.md` — the structural
  6.55 GB anon floor uint8 does **not** remove (only eases page-cache demand).
- `../seismic_150m_testbed/` — the alternative no-JVM engine attempt this falls back from.
