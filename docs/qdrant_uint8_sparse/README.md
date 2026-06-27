# qdrant_uint8_sparse/ — Qdrant sparse uint8 quantization spike ("move 1")

**Opened 2026-06-27.** The cheapest fallback after the SEISMIC spike arced toward KILL
on quality (`../seismic_150m_testbed/06_FINDINGS.md`). Question: does quantizing the
Qdrant SPLADE sparse leg **f32 → uint8** (the sparse-index `datatype` knob) ease the
150M RAM/latency wall **on a host we already have**, while holding RRF NDCG@10 at 0.560?

No new engine, no JVM, no fork — a build-time config change on the live stack.

## Status: SCAFFOLD — nothing measured yet

- ✅ **Verified un-actioned** (2026-06-27): the live Qdrant sparse build
  (`scripts/spike_qdrant_sparse.py:159`) uses `on_disk=True` but **no `datatype=`** →
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
   stored `sparse_field` (no re-encode) — extend `scripts/spike_qdrant_sparse.py` with a
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
