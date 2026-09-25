# Semantic Doc-ID at Ingest — research + spike trail

**Status:** DEFERRED 2026-09-25 (DESIGN ONLY / UNMEASURED since 2026-06-30; no code was ever written) — **DESIGN ONLY / UNMEASURED. Nothing here is implemented.** This folder
captures a hypothesis explored on 2026-06-30: assigning **autoregressive,
hierarchical, semantic document IDs at ingest time on the host**, and using
those IDs as the routing key for an LSM-style stack of **immutable** sparse
segments over the SEISMIC/BMP leg.

This is a *thinking trail*, not a commitment. The headline recommendation is in
[`03_GO_NO_GO.md`](03_GO_NO_GO.md). Read that first if you only have a minute.

## Files

| Doc | What it is |
|---|---|
| [`00_CONCEPT_AND_CONTEXT.md`](00_CONCEPT_AND_CONTEXT.md) | The full idea trail: generative retrieval (DSI/NCI/SEAL) applicability, MoE applicability, "Meaning A vs B" of autoregressive doc-IDs, and the two hard constraints (any-hardware/elastic, immutable sparse leg). |
| [`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) | The design that survives the constraints: ID-as-routing-address, the immutable-segment LSM loop, elastic prefix-depth sharding, interaction with the existing sharding + mmap infra. |
| [`02_SPIKE_PLAN.md`](02_SPIKE_PLAN.md) | Stage-1 spike: what to build (rule-based ID, no ML), what to measure (resident-set vs segment count, query fan-out, flush latency), success/kill criteria. |
| [`03_GO_NO_GO.md`](03_GO_NO_GO.md) | Simplified should/should-not + explicit GOs and NO-GOs. The decision page. |
| [`DECISION_TRAIL.md`](DECISION_TRAIL.md) | Dated log of how the conclusion was reached, including the Lucene reality-check that shrank the novelty. |

## One-paragraph summary

The auto-updater the idea wants is **buildable and forward-only** — but only the
narrow "assign a stable semantic ID at ingest" part is novel. The
immutable-segment / flush / merge / NRT / mmap machinery it rides on **is
Lucene, feature-for-feature**, and we already left Lucene (the 150M OpenSearch
baseline) for JVM/footprint reasons. So the defensible value collapses to two
things Lucene does *not* do — a **stable hierarchical semantic ID** and
**elastic prefix-depth resharding** — and the real risk lives entirely in one
place: whether LSM's many-small-segments habit wrecks the mmap page-cache that
the whole thin-client thesis depends on. That single tension is what a spike
must measure before any code ships.
