# 00 · Vision & Goals

**Status:** ACTIVE

## What we are deciding

Whether **SEISMIC** can serve the SPLADE sparse leg at **150M** with:
1. a **cured RAM floor** (no Qdrant-style rising anon; no BMP-style load-into-RAM),
2. **no JVM** (unlike OpenSearch+SEISMIC),
3. **quality at parity** with the current stack (RRF NDCG@10 ≈ 0.560, still +0.111
   over OpenSearch), and
4. **acceptable latency** on a host we can actually afford (not ≥64 GB just to stop
   thrashing, the way Qdrant-150M needs).

…and, if it can, whether owning that integration beats the off-the-shelf
alternatives (accept the JVM via OpenSearch+SEISMIC, or size a bigger Qdrant box).

## Why SEISMIC and not "more BMP"

The prior project killed the bespoke mmap-BMP engine on **two measured axes**
(`archive/sparse_engine_project/03_GO_NO_GO_GATES.md`):

| Axis | mmap-BMP result | SEISMIC |
|---|---|---|
| **Pruning at scale** | ❌ **linear in corpus** — WAND prunes ~nothing on 64-term SPLADE (worst query scored 95% of all blocks) → ~557K block-scores/q @150M | ✅ **designed to prune** (geometric blocks + summary vectors), **validated at 138M** |
| **RAM cure** | ❌ half-built (inverted side ~334 B/doc → ~50 GB @150M) | ❓ **open** — FOSS implementation is RAM-resident; cure is the work |
| **No-JVM / embeddable** | ✅ (Rust fork) | ✅ (pure Rust, MIT, `pyseismic-lsr`) |

SEISMIC trades BMP's fatal-and-unfixable axis (pruning) for an *open* one (RAM). That
is a strictly better starting position — you don't rebuild the hard algorithmic part.

## Goals (must-hit, priority order)

1. **G-RAM — cure the floor.** Sparse-leg resident RAM **flat in corpus** and
   materially below Qdrant's 6.55 GB @150M; ideally page-cache-resident (~0 anon),
   the way an mmap'd inverted index is. *This is the whole reason to move.*
2. **G-QUALITY — no regression.** Top-k overlap@10 and RRF NDCG@10 within noise of
   the current Qdrant stack (B1 overlap, B2 RRF |Δ|<0.005); still > OpenSearch.
3. **G-SCALE — actually 150M.** Build + serve the full corpus on a host we have or
   can justify; no OOM during build/optimize; latency in a usable band.
4. **G-NOJVM — no JVM, embeddable.** Runs as a library next to tantivy/usearch; no
   new server process class. (OpenSearch+SEISMIC is the fallback that *loses* this.)
5. **G-OPS — low ownership cost.** Reuse the stored SPLADE `sparse_field` (no
   re-encode); immutable monthly-rebuild model; minimal forked code to maintain.

## Non-goals (explicit)

- **Live upserts / true mutability.** Immutable rebuild + swap, like today's build.
- **Beating SOTA QPS.** Parity with the measured stack is the bar.
- **Touching the persona/laptop tier.** Qdrant is GREEN there; out of scope.
- **Unifying all three legs into one store.** RRF fuses *result lists*; the legs stay
  separate engines (tantivy + SEISMIC + usearch). Single-store unification is a
  non-goal here — it was the optional G7 that never earned its cost.

## Definition of success / kill

- **GO (full):** G-RAM + G-QUALITY + G-SCALE all green on a path that keeps G-NOJVM →
  SEISMIC becomes the 150M sparse leg; write the integration + decision record.
- **GO (conditional):** quality + pruning hold but the RAM cure needs a real mmap
  substrate build → escalate to the build-vs-buy decision (R-OWN) with numbers in hand.
- **NO-GO:** SEISMIC standalone is RAM-resident with no cheap cure **and** the
  mmap-substrate build is not worth owning → fall back to **OpenSearch+SEISMIC**
  (accept the JVM, zero new code, bounded heap) or **size a bigger Qdrant host**.
  Document the number; sunk cost capped at the failed gate.
