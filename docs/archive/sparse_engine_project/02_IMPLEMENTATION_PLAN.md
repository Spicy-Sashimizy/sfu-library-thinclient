# 02 · Implementation Plan (phased, gated)

> **CLOSED MEASURED 2026-06-26** — the bespoke sparse engine was MEASURED & STOPPED 2026-06-26 (verdict STOP in `07_INTEGRATION_PLAN.md` §8: pruning linear in corpus, ~50 GB inverted side at 150M). SEISMIC federated mmap took the slot (promoted 2026-07-06, `docs/SEISMIC_ARCHIVE_SPLIT.md`); the FORMAT-WALL result is kept. Not current; do not resume.

**Status:** CLOSED MEASURED 2026-06-26

> **CLOSED — line MEASURED & STOPPED 2026-06-26.** P2's RED was flipped to
> **FORMAT-WALL** by the zero-decode tiebreaker (`06_NEXT_STEPS_ZERO_DECODE.md`), which
> re-opened the line provisionally. The §4 follow-ons that gated re-open were then
> measured (P3a/P3b) and **both fail at the 150M target scale**: pruning is linear in
> corpus and the inverted-side RAM projects to ~7.6× the Qdrant floor. **Final verdict:
> STOP** — no repo spun off; thin client ships on Qdrant. See `07_INTEGRATION_PLAN.md`
> §8 (decision record) and `README.md`. This doc is retained as the historical
> P0→P2 record only.

Each phase has a **deliverable** and an **exit gate** (full pass/fail numbers in
`03_GO_NO_GO_GATES.md`). Stop at any failed HARD gate.

| Phase | Deliverable | Exit gate (summary) | Where | ~Effort |
|---|---|---|---|---|
| **P0 · Baseline** | stock-BMP top-k/RSS/latency recorded (`spike/archive/mmap_bmp/record_baseline.py`) | baseline.json + qvecs.json produced | here, branch | ✅ done 2026-06-25, 5 shards |
| **P1 · Fork builds & is correct** | BMP forked to `memmap2`; wheel in throwaway venv | **G1 correctness** byte-identical top-k vs P0 + **G2 RAM** RssAnon ~0 | here, branch | ✅ G1+G2 PASS 2026-06-25 (R3 flat rewrite); G3 signal degraded |
| **P2 · Cold-p95 at scale** | persona-sized `.bmp` from `spool_backup`; cold/warm measured | **G3 latency** cold p95 ≤ ~2–3× warm AND warm p50 ≤ Qdrant on same data | here, branch | ✅ done 2026-06-26 — **RED** (G3b PASS, G3a FAIL) |
| **— SPIN-OFF DECISION —** | go/no-go on building the engine | P1+P2 green → new repo/container; else **KILL** | — | — |
| **P3 · Engine MVP** | `immsparse` lib: mmap loader + per-section build + `SFU_SPLADE_BACKEND=immsparse` serving | **G4** end-to-end RRF on a section == current stack quality; serve degrade-to-BM25F works | spun-off repo | 1–2 wk |
| **P4 · 150M validation** | full-150M `.bmp` set served via mmap; OOM-safe | **G5** 150M serves at ~0 anon floor; latency curve vs RAM (matches/beats Qdrant); B1/B2 parity re-pass | spun-off repo | 1–2 wk |
| **P5 · Productionize / (opt) Lance unify** | packaging for both tiers; optional Lance substrate (Option B) | **G6** packaged, reproducible build; (opt) unified-store gate | spun-off repo | 2–4 wk |

## Phase detail

### P0 — Baseline (DONE: scaffold runs)
`record_baseline.py` encodes real SPLADE queries, runs stock `bmp.Searcher` over the
test `.bmp` shards, records top-k (ids+scores), RSS, latency, and persists the query
vectors. This is the ground truth P1 diffs against.

### P1 — Fork builds & is correct
Apply `spike/archive/mmap_bmp/FORK_BMP.md` (swap `Vec` read → `Mmap`, zero-copy views).
`compare_fork.py` replays P0's qvecs and checks G1 (identical top-k) + G2 (RssAnon
~0). **This is the make-or-break phase** — if results differ or RAM doesn't drop,
the fork is wrong or the idea is dead.

### P2 — Cold-p95 at scale (DONE 2026-06-26: RED → **re-tested FORMAT-WALL 2026-06-26**)
> **🔄 Re-test superseded the RED:** the zero-decode tiebreaker (`06_NEXT_STEPS_ZERO_DECODE.md`)
> dropped warm p50 from **696 ms → 25.63 ms** on the same 4-shard subset — below qdrant 66 ms,
> G1 byte-identical, anon 1.976 GB. The wall was R3-v1's compact format, not the algorithm.
> The RED below is the R3-v1 (decode-per-query) record; the v2 re-test re-opens the build
> *provisionally* (§4 follow-ons still gate). See `03_GO_NO_GO_GATES.md` decision log.

Built a persona-sized `med_bio` (23.4M docs → 16 shards → 17.8 GB `.bmp` → 9.0 GB
`.bmflat`) from `spool_backup` via `spike/archive/mmap_bmp/build_persona_bmp.py`; transcoded
via the R3 fork; measured cold/warm via `spike/archive/mmap_bmp/measure_p2_cold.py`. Result:
**G3b PASS** (cold/warm = 1.04 — the cold-fault bet was won; cost is decode, not faults),
but **G3a FAIL** (warm p50 696 ms vs qdrant 66 ms, ~10× — decode-bound, scales worse
than linear). Bonus: **G2 regresses at scale** (8.26 GB anon / 16 shards — R3 cured only
the forward index; the owned inverted side scales with corpus). Clean 4-shard subset
used for the latency numbers to avoid swap contamination from the full 8.3 GB anon
loading concurrently with live qdrant on the 31 GB host. See gate decision log in
`03_GO_NO_GO_GATES.md`.

### Spin-off decision
P1+P2 green = the cure is real and buildable → create a dedicated repo/container
(`immsparse`) with its own CI (maturin wheel per-arch), and continue P3+ there.
**Red = stop; the assessment's pragmatic paths stand.**
**(2026-06-26: RED. G3a failed → do NOT spin off `immsparse`; do NOT proceed to P3.)**

### P3 — Engine MVP
Wrap the mmap loader as a small library; add per-section build; wire
`SFU_SPLADE_BACKEND=immsparse` into the retriever (drop-in). Validate one full
section end-to-end (RRF + degrade-to-BM25F).

### P4 — 150M validation
Build/serve the full 150M as mmap'd sections; re-run the B1 (parity) + B2 (RRF
quality) gates from the decommission plan, plus the latency-vs-RAM curve from
`QDRANT_150M_BENCHMARK_PLAN.md`. Confirm ~0 anon floor at 150M.

### P5 — Productionize (+ optional Lance)
Per-arch wheels, reproducible build, hot/cold packaging integration, docs. Optionally
implement Option B (Lance substrate) for true unification — only if G-UNIFIED is
worth the cost after P4 proves the engine.
</content>
