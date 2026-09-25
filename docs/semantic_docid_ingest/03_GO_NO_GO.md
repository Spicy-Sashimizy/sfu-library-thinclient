# 03 — Should we consider this? (the decision page)

**Status:** DEFERRED 2026-09-25 (DESIGN ONLY / UNMEASURED since 2026-06-30; no code was ever written) — **RECOMMENDATION, DESIGN-ONLY EVIDENCE (2026-06-30).**

## Simplified: what the idea actually is

> Give every incoming document a **stable, hierarchical, semantic ID** computed
> at ingest on the host (forward-only, any CPU). Use that ID as the **routing
> address** into an LSM-style stack of **immutable** SEISMIC segments — new docs
> buffer in RAM, flush into small immutable segments, and merge in the
> background. Cut shards at any ID-prefix depth to scale from laptop to 150M.

## Why it *should* be considered

- **It fits the constraints instead of fighting them.** Immutability *selects
  for* an LSM design; the semantic ID is the natural routing key it needs.
- **It is forward-only.** Assignment never retrains — it sidesteps the
  catastrophic-forgetting problem that kills generative retrieval as an updater.
- **It is the only clean answer to "scale up *and* down on any hardware."**
  Elastic prefix-depth sharding is a property Lucene/ES structurally lack.
- **Most of it is battle-tested.** The LSM/merge/NRT/mmap machinery is Lucene
  prior art to port (`04_LUCENE_BORROW.md`), not invent — low design risk.
- **It generalises something you already built** (`sections.py` is a depth-2
  hand-coded version), so it composes with the existing stack, not against it.
- **It can ship without ML** (Stage 1 uses rule-based IDs), de-risking the
  any-hardware promise before any model is trained.

## Why it *should not* (or not yet)

- **The novelty is narrow.** After the Lucene haircut, only two things are new:
  the stable semantic ID and elastic prefix-sharding. If neither earns a
  *measured* win, this is a large amount of segment-lifecycle plumbing for
  little gain.
- **The mmap tension is real and unproven.** LSM wants many small files; the
  mmap thesis wants few big ones. If TieredMergePolicy + prefix-locality can't
  keep RSS/latency bounded, the idea is incompatible with the serving thesis —
  and this is **untested**.
- **You may already have "good enough."** Warm cache + monthly rebuild +
  section classifier is a working auto-updater today. This adds locality and
  elasticity, **not a new capability** — quantify the gap before paying for it.
- **It improves organisation, not recall, by itself.** Any quality win waits on
  Stage 2's learned tree, which carries its own drift/versioning cost.
- **SEISMIC has no cheap merge.** Every compaction is a localised rebuild — a
  real, recurring CPU cost the spike must price.

## GO

- **GO** to run **Stage 1 spike only** (`02_SPIKE_PLAN.md`): rule-based IDs +
  immutable-segment LSM loop, measuring **RSS-vs-segment-count, query fan-out,
  p95 latency, flush + compaction cost, cross-host ID reproducibility** against
  the current full-rebuild baseline.
- **GO** to **port, not reinvent**, the Lucene mechanisms in
  `04_LUCENE_BORROW.md` §1–§5 (commit point, RAM-flush, TieredMergePolicy,
  liveDocs, NRT/madvise).
- **GO** to keep the **W-id canonical** and treat semantic-id as a sidecar
  routing key.

## NO-GO

- **NO-GO** on Meaning A — autoregressive *retrieval* that learns new docs by
  updating weights (DSI++). Out of proven scale, breaks updates/filters/latency.
- **NO-GO** on a generative leg over the **full 150M** (only ever a bounded hot
  subset, and not part of this spike).
- **NO-GO** on the **learned tree (Stage 2)** until Stage 1 passes its mmap
  gate — train no model before the architecture is proven survivable.
- **NO-GO** on **borrowing Lucene's docid or routing** (`04_LUCENE_BORROW.md`
  §6) — they are the opposite of the idea's only novel parts.
- **NO-GO** on shipping any of it to the serving path **without measured
  numbers** (per the repo's efficacy rule): no "should improve X" in docs.
- **NO-GO** on touching the lexical/dense legs — sparse-leg only.

## One-line verdict

**Worth a Stage-1 spike, not a build commitment.** The architecture is sound and
mostly borrowed; the entire bet rides on whether LSM's small-segment habit
survives the mmap page-cache — measure that one thing first, and let it decide.
