# disk_streaming_research/ — cross-project study of disk-streaming serving

**Created 2026-07-13. Status: RESEARCH + BUILT (2026-07-14) — F1–F6 hooks
shipped, env-gated OFF by default (kill-switch, not on the served path unless
an operator sets the dial). Doc 03 §5 carries the per-phase MEASURED status.**

This directory holds research into how external projects stream parameters /
experts from disk, mapped onto our own mmap-based SEISMIC sparse-index
streaming code. It exists to capture transferable techniques for the open
G8/sequential-latency risk — and, just as importantly, to record which of
those techniques we have *already* measured-and-refuted here so we don't
re-spend the work.

It is intentionally a **separate, standalone directory** from
`seismic_150m_testbed/`: the testbed holds the measured gates and executed
experiments for the 150M SEISMIC leg, while this directory holds external
literature/mapping research that *informs* that testbed's backlog. Candidate
experiments proposed here, if adopted, get pre-registered into
`seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` before any run.

## Documents

| Doc | What |
|---|---|
| `01_CROSS_PROJECT_RESEARCH.md` | The core research doc: **colibrì** (primary analogue — 744B MoE streamed from disk in ~25 GB RAM), **sluice**, **KTransformers**, **VibeBlade** surveyed + mapped onto our mmap SEISMIC code. The honest map of what mirrors colibrì, what's MISSING (software LRU/pin tier + PILOT lookahead), what's already REFUTED here (per-query WILLNEED, MADV_RANDOM), and ranked candidate experiments (skew-telemetry → LRU+pin → async PILOT prefetch → pread foundation). |
| `02_METHOD_VERIFICATION_AND_INTEGRATION.md` | **2026-07-13 follow-up**: claim-by-claim online verification of doc 01 (READMEs + colibrì `c/glm.c` — all core claims CONFIRMED; one anecdote unverified), two corrections (shard-granularity wrong; candidate #1 needs no Rust), the CIDR-2022 `pread`-vs-mmap literature anchor, a candidate→module integration map (hooks, EINVAL gotcha, E8 Stage-2 sequencing), estimated uplifts + worth-deving verdicts, and the **Q12 access-skew probe** (pre-registered, measured — the gate for the whole track). |
| `03_MIN_RAM_DESIGN_MAP.md` | **2026-07-13 design → 2026-07-14 BUILD + MEASURED**: the assembled min-RAM combo — three residency tiers (mlock'd floor+hot-set / reclaimable page cache / streamed), the most effective form of each function F1–F9 (telemetry, sidecar, pin, release-except, prefault-hotset-at-load; PILOT/pread/userspace-LRU explicitly omitted with reasons), per-deploy-shape RAM budgets, and the post-gate build order. **Build gates both PASSED 2026-07-14** (Q12b production-shaped hot-set probe **GO** hot-set-80 3.07 GB; E8 dv-v2 served). F1–F6 built; Phase 5 T1 20/20 bit-identical with pin ON; Phase 6 prefault-hotset-at-load cold p95 4.66 s → 1.67 s (**~2.8×**, corrected 2026-07-14 — the initial "30 ms/~150×" record was invalid, all bench queries had silently failed; see doc 03 §5.6 correction + fix commit 2203d9b). F3/F4 latency A/B host-gated (32 GB-host regime); F4 over-scoped (13.4 GB floor pin — needs rescoping to the ~20 MB true floor). §5 build-order lines carry per-phase MEASURED status. |

## Source-of-truth / cross-references

- The disk-streaming code being mapped lives in
  `spike/seismic_upstream/src/mmap_io.rs` (Rust mmap reader, `release_pages`,
  `prefault_floor`, `touch_bytes`, `leak_mmap_advise`) and
  `src/lib/thinclient/sharded_seismic_backend.py` (Python parallel/sequential/
  hybrid serving backends).
- Refuted-lever provenance + the recorded open risks live in
  `seismic_150m_testbed/` (esp. `06_FINDINGS.md`, `08_LATENCY_RESEARCH.md`,
  `10_FORWARD_COMPRESSION_DESIGN.md`, `11_EXPERIMENT_BACKLOG.md`) and
  `seismic_sequential_serving/`. Cross-check there before quoting any number.
- Per the freshness rule: every external number in `01_CROSS_PROJECT_RESEARCH.md`
  is from the upstream projects' own docs (labeled literature, not our runs);
  our candidate experiments stay UNMEASURED until run.
