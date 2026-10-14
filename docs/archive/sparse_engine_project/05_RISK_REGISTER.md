# 05 · Risk Register

> **CLOSED MEASURED 2026-06-26** — the bespoke sparse engine was MEASURED & STOPPED 2026-06-26 (verdict STOP in `07_INTEGRATION_PLAN.md` §8: pruning linear in corpus, ~50 GB inverted side at 150M). SEISMIC federated mmap took the slot (promoted 2026-07-06, `docs/archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md`); the FORMAT-WALL result is kept. Not current; do not resume.

**Status:** CLOSED MEASURED 2026-06-26

> **CLOSED — line MEASURED & STOPPED 2026-06-26.** Written while the mmap-BMP /
> `immsparse` engine was a live option. At the 150M target scale the bespoke engine
> loses to FOSS (pruning linear in corpus; inverted-side RAM ~7.6× the Qdrant floor).
> Historical design context only — current verdict in `README.md` + `07_INTEGRATION_PLAN.md` §8.

Each risk lists the **cheapest experiment that retires it** and the **gate** that
catches it. Ordered by kill-probability × cost.

| # | Risk | Likelihood | Impact | Cheapest retiring experiment | Gate |
|---|---|---|---|---|---|
| R1 | **Cold-cache faults dominate** — term-major helps but block-eval seeks make cold p95 blow up | **Med** | **Kill** | P2: measure cold p95 on a >cache `.bmp`; `madvise(WILLNEED)`/prefetch as a cheap mitigation before deciding | G3b |
| R2 | **mmap doesn't actually drop RssAnon** — fork still copies into RAM (zero-copy views harder than hoped) | Med | Kill | P1: `RssAnon` after load via `/proc/self/status`; if not ~0, the deserializer still allocates | G2 |
| R3 | **Zero-copy fork is invasive** — BMP's structs assume owned `Vec`; rework is large | Med | Cost/Schedule | P1: timebox the fork to 2 days; if the buffer swap isn't localized, escalate (or pivot to Option B / OpenSearch+SEISMIC) | (P1 effort) |
| R4 | **Correctness drift** — zero-copy/endianness/alignment changes scores | Low | Kill | P1: byte-identical diff vs stock baseline (already scaffolded) | G1 |
| R5 | **150M doesn't extrapolate** — section-scale looked fine, full corpus regresses (segment count, fault amplification) | Med | Major | P4: full-150M serve + latency-vs-RAM curve; keep `max_segment`-style knobs | G5a/c |
| R6 | **Quality regression at system level** despite identical leg | Low | Kill | P3/P4: re-run B1/B2 parity (overlap@10=1.0, RRF |Δ|<0.005) | G4/G5b |
| R7 | **Ownership/maintenance burden** — a forked Rust engine to maintain (wheels, CVEs, BMP upstream drift) | High | Strategic | decide at spin-off: is owning it worth it vs Infinity/OpenSearch+SEISMIC off-the-shelf? | (spin-off) |
| R8 | **Per-arch wheels** (the original BMP gap: no mac-arm64/linux-aarch64) | High | Cost | P5: maturin CI for the 3 target arches; vendor/pin | G6 |
| R9 | **Lance integration scope creep** (Option B) | Med | Schedule | keep B optional; A delivers the cure without it; only do B if G-UNIFIED earns its cost | G7 |
| R10 | **SATA/non-NVMe deploy** makes cold p95 worse than the NVMe spike | Low | Cost | P2/P4: state NVMe as a deploy requirement; measure on target FS | G3b/G5c |

## The two risks that actually decide the project
- **R2 (RAM)** and **R1 (cold p95)** are the whole bet. Both are retired in P1–P2,
  *here*, in ~2–4 days, for the cost of one Rust fork. Everything after is execution.
- **R7 (ownership)** is the strategic counterweight: even if the engine works, owning
  a custom Rust search engine is a real long-term cost. The honest alternative if R7
  outweighs the win is **Infinity** (no-JVM, off-the-shelf, you don't maintain it) or
  **OpenSearch+SEISMIC** (JVM, zero new code). Decide R7 explicitly at spin-off, with
  the P1/P2 numbers in hand.

## Cheapest path to a confident kill
Run P0→P2. If R1 or R2 fail, you have killed "the dream engine" with measured numbers
in ~half a week, created no new repo, and the fallback paths (per-persona Qdrant local;
Infinity / OpenSearch+SEISMIC server) are unchanged and already specced in
`docs/archive/qdrant_vs_lucene_assessment/`.
</content>
