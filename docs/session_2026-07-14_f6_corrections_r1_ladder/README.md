# Session record — 2026-07-13/14: E8 status → GLM drive → F6 corrections → R1 RAM-ladder

**Status:** ACTIVE

**Created 2026-07-14.** Verbatim-fidelity record of the overnight operator
session (2026-07-13 ~21:00 UTC → 2026-07-14 ~08:00 UTC): the questions asked,
the answers given, every defect found, every number measured, and the external
literature located. Written because this session (a) invalidated and corrected
a committed benchmark result, (b) found six defects in one day's autonomous
work, and (c) produced the first controlled RAM-pressure curve for the served
stack — the reasoning deserves a durable record, not just commit messages.

| file | contents |
|---|---|
| `01_CHRONICLE.md` | Chronological Q&A record of the whole session — operator questions (quoted), answers given, decisions made, with timestamps and commit SHAs |
| `02_DEFECT_LEDGER.md` | The six defects: symptom → diagnosis → mechanism → fix → verification, each with evidence file paths |
| `03_MEASUREMENT_TABLES.md` | Every table produced this session: E8 status, attention-span mapping, invalid-vs-corrected F6, trust audit, R1 ladder |
| `04_CONVERGENCE_ARTIFACT.md` | The non-monotonic convergence artifact: the observation, the mechanism, the literature anchoring (WiOpt 2022 / Che-Fagin / MGLRU / sequential flooding), and why it is NOT Belady's anomaly |
| `05_EXTERNAL_PRECEDENTS.md` | Web-research findings: documented precedents for every phenomenon seen tonight (kernel patch def5efe0, TMO/senpai, Aquifer, Neo4j, ES/OS max_map_count lore) |
> **Live thread (2026-09-01):** `04_CONVERGENCE_ARTIFACT.md` has grown dated
> addenda past this session — Tier-1 and Tier-1b synthetic repro both FAILED
> (2026-08-31, recorded; reading = access-structure dependence), and the
> Tier-2/3 real-stack MGLRU repro is pre-registered with phase A in flight
> (harness + records: `spike/convergence_repro/`). Read the artifact's addenda
> before quoting its status.

| `06_KERNEL_PAGE_RECLAIM_INTERNALS.md` | The precise "how does the kernel actually decide" write-up: not-LRU (accessed bit → 2Q double-clock → shadow-entry refault feedback → pressure-scaled aging), the "binary choice vs accumulated state" correction, MGLRU's explicit PID controller, academic lineage (CLOCK/2Q/LIRS/CLOCK-Pro/ARC), verified topology (WSL2 kernel 6.18.33.1, lru_gen absent → classic two-list), and the one-line mapping of each mechanism to this session's measurements |

## One-paragraph summary

The E8 dv-v2 flip landed and a GLM 5.2 drive session (via claude-code-router →
NeuralWatt, launched in the dev container) executed the disk-streaming program
Phases 0–6, committing a headline "cold p95 4.6 s → 30 ms (~150×)" that a
corrections pass proved was **300/300 silently-failed queries scored as 0 ms
no-ops**. Five defects were fixed and the honest number measured: **cold p95
4.66 s → 1.67 s (~2.8×), parity 10/10** (`f6_prefault_hotset_20260714.json` vs
`f6_gateoff_baseline_20260714.json`, fix commit 2203d9b, corrections 43c090e).
A trust audit then killed a second false attribution (warm 117→54 ms was CPU
contention, not the .so rebuild — 1919855). The R1 RAM-ladder (E7b's method on
the full 150M 8-shard stack) measured the working set at **~15.5 GB** and the
thrash floor between 12 and 8 GB (`r1_cap*_20260714.json`, 331d8da/65f786b),
surfaced defect #6 (mlock VMA-split saturation, same class as #4), and produced
the convergence artifact documented in `04_`. Pin-ON (F3) and release-except
(F5) cells were queued; their results land in the backlog R1 section when done.

## Verbatim-fidelity caveat

`01_CHRONICLE.md` quotes operator questions as typed (including typos) and
reproduces the substance and numbers of every answer. It is a faithful digest,
not a keystroke transcript; where an answer is compressed, the compression is
noted and the full data lives in the referenced result files.
