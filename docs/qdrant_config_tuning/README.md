# Qdrant config-tuning — tuning the SPLADE leg we're shipping on

**Status:** ACTIVE, measure-first. Created 2026-06-26.
**Scope owner:** this directory. Do not conflate with the lines below.

## What this line is — and is not

This is the line that asks: **now that the custom-engine spike is dead and we
are shipping SPLADE on Qdrant, what config/levers actually move the RAM and
latency numbers — measured, not assumed?**

The previous research turn (2026-06-26) concluded two things this directory acts on:

1. The no-JVM immutable-engine spike is **MEASURED & STOPPED** — it does not beat
   FOSS at the 150M scale that justifies owning it. We are **shipping on Qdrant**.
   (See `docs/sparse_engine_project/README.md` for the STOP verdict — that line
   is closed; we do not touch it here.)
2. Qdrant itself is **already near-optimal**: the active config (`on_disk=true`
   sparse + `on_disk_payload=true`) is already the maintainers' recommended
   large-scale path (compressed mmap'd postings + bitpacked f16 indices). The
   **6.55 GB anonymous-RAM floor is structural** — it's the per-point id tracker
   Qdrant treats as required-resident — not a misconfiguration we can toggle away.

So the work here is narrow and evidence-first: **confirm** the floor (is part of
it just appendable-segment overhead the compressed id tracker can reclaim?),
**lock** the compressed-mmap datatype explicitly so we never silently regress,
**add** the latency env the large-scale guide recommends for page-cache-bound
serving, and **correct** the earlier over-optimistic `uint8` claim.

## Why a separate directory (not folded into an existing one)

Three lines of thought already exist around Qdrant, and each has a distinct
question. Mixing config-tuning into any of them would contaminate that
line's decision trail:

| Directory | Its question | Relation to this line |
|---|---|---|
| `docs/qdrant_vs_lucene_assessment/` | "Should we swap *off* Qdrant back to Lucene/OpenSearch?" | Answered 2026-06-25 → keep Qdrant. This line is the downstream "ok, keep it — tune it" follow-on. **It also carries the uint8 claim we correct here.** |
| `docs/bmp_decommission_plan/` | "How do we migrate BMP→Qdrant + size the demo droplet?" | The migration itself. Its `DO_SIZING.md` RAM model is **correct** (anon is structural, ~43 B/pt) and this line confirms/reuses those numbers. |
| `docs/sparse_engine_project/` | "Should we build a competing no-JVM engine?" | **STOPPED 2026-06-26.** The dead elder brother of this line. Untouched here. |

This directory is the fourth: **"What config moves Qdrant's RAM/latency, measured?"**

## Files

- **`README.md`** (this file) — charter, scope, source-of-truth.
- **`MEASURE_FIRST.md`** — the live baseline state (verified this session) + the
  A1 force-optimize design and its measured result once run.
- **`CONFIG_LEVERS.md`** — research-confirmed: what each config actually does
  (datatype, on_disk, async_scorer, segment number), what the anon floor is
  and isn't, and the **corrected** uint8 stance (the real index-shrink lever is
  SPLADE doc-term pruning, not a smaller per-value type).

## Source-of-truth for these numbers

1. **The code is always right** (binding project rule). If a doc here contradicts
   a live `/collections` config dump or `/proc/<pid>/status`, the live value wins
   and the doc is fixed in the same session.
2. `docs/bmp_decommission_plan/DO_SIZING.md` owns the **RAM model** (anon floor
   ~43 B/pt, page-cache scaling). This directory *consumes* those numbers and
   adds config-side evidence; it does not re-derive them.
3. Measured numbers supersede older ones; superseded claims get a dated pointer
   never a silent edit (see the uint8 corrections in `CONFIG_LEVERS.md` and the
   banners on the assessment docs).
