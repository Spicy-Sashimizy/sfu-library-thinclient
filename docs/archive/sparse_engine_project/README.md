# Sparse Engine Project — testbed for an immutable, no-JVM, unified search engine

> **CLOSED MEASURED 2026-06-26** — the bespoke sparse engine was MEASURED & STOPPED 2026-06-26 (verdict STOP in `07_INTEGRATION_PLAN.md` §8: pruning linear in corpus, ~50 GB inverted side at 150M). SEISMIC federated mmap took the slot (promoted 2026-07-06, `docs/archive/seismic_archive_split/SEISMIC_ARCHIVE_SPLIT.md`); the FORMAT-WALL result is kept. Not current; do not resume.

**Status:** CLOSED MEASURED 2026-06-26

**Status:** KILLED → RE-OPENED (provisional) → **MEASURED & STOPPED (2026-06-26).**
The zero-decode tiebreaker (R3-v2, `bytemuck::cast_slice` + `flat_block_score`)
flipped P2's G3a RED — warm p50 **696 ms → 25.63 ms** on a 4-shard subset, below
qdrant's 66 ms, G1 byte-identical, **FORMAT-WALL proven** (the wall was the compact
format, not Block-Max). **But the §4 follow-ons that gated any re-open have now been
measured (not flagged), and both kill it at the 150M target scale that is the entire
reason to own the engine:** (1) pruning is **linear in corpus** — worst-query
`blocks_scored/num_blocks` stays ~0.95 across a 2.15× corpus jump, so the win was
zero-decode making scoring-everything cheap, not selectivity → ~557K block-scores/query
projected at 150M; (2) the forward-only RAM cure is half-built — the inverted side is
~334 B/doc (gc-persistent), projecting to **~50 GB at 150M — ~7.6× the Qdrant 6.55 GB
floor it was built to replace.** **Verdict (§8 of `07_INTEGRATION_PLAN.md`): STOP the
BMP line; keep `immsparse` + FORMAT-WALL as a recorded research result; ship the thin
client on Qdrant (already GREEN at persona).** If 150M-single-collection ever becomes
a hard requirement, the measured row-6 result says pivot to **SEISMIC**, not more BMP
work. · **Owner:** TBD · Decision record: `07_INTEGRATION_PLAN.md`; gates:
`03_GO_NO_GO_GATES.md`; tiebreaker: `06_NEXT_STEPS_ZERO_DECODE.md`.

This is a **fully separate** doc set for building (or killing) the engine the
assessment identified as the only thing that *cures* the 150M sparse-RAM problem
while staying no-JVM: a sparse leg with **immutable, mmap'd postings** (page-cache
resident, no per-point anon floor), unified with a lexical (tantivy) and dense
(usearch/Lance) leg. Working name: **`immsparse`** (immutable sparse).

> Why this exists: see `docs/archive/qdrant_vs_lucene_assessment/` — Qdrant's mutable
> per-point anon floor (6.55 GB, rising) is the 150M root cause; Lucene/OpenSearch
> cures it but is JVM; no production no-JVM engine unifies lexical+sparse+immutable
> today (LanceDB stores sparse but has no sparse index). The mmap-BMP source check
> (`ARCHITECTURE_EXPLAINER.md` §6) says the algorithm doesn't forbid the cure.

## The one-sentence bet
Take BMP's measured-good Block-Max sparse algorithm, make its postings **mmap'd /
immutable** (cure the anon floor), and unify it with tantivy lexical + dense in one
no-JVM store — delivering the current stack's quality (+0.111 NDCG@10 over
OpenSearch) at 150M **without** Qdrant's RAM wall or a JVM.

## Documents
| Doc | What |
|---|---|
| `00_VISION_AND_GOALS.md` | what we're building, the goals it must hit, explicit non-goals |
| `01_ARCHITECTURE.md` | the design: mmap-Block-Max sparse + tantivy + dense, storage substrate options (standalone vs Lance), data layout, access pattern |
| `02_IMPLEMENTATION_PLAN.md` | phased plan P0→P5, each phase's deliverable + exit gate |
| `03_GO_NO_GO_GATES.md` | the concrete pass/fail numbers at every gate (kill criteria) |
| `04_BUILD_AND_GATHER.md` | inventory: what code/data/tools to create vs already have |
| `05_RISK_REGISTER.md` | risks, mitigations, and the cheapest experiment that retires each |
| `DECISION_TRAIL.md` | the Q→finding→forced-move chain (2026-06-25 session) that converged on the mmap-BMP (+ optional Lance) build |
| `WHY_NO_FOSS.md` | build-vs-buy (Risk R7): why no off-the-shelf no-JVM engine covers this exact lexical+sparse+immutable intersection |
| `06_NEXT_STEPS_ZERO_DECODE.md` | **the one cheap experiment that could flip the kill** — zero-decode forward layout as the format-wall vs real-wall tiebreaker; corrects the "decode wall is intrinsic" framing |
| `07_INTEGRATION_PLAN.md` | **the LIVE forward plan (post zero-decode).** Rewritten phased plan after the FORMAT-WALL flip: the proven-vs-open ledger, the re-affirmed build-vs-buy gate-zero, what to weigh before going forward (pruning confound, SEISMIC, ecosystem moving underneath), and P3a/b/c gating prerequisites before any spin-off. Supersedes the forward-looking parts of `02`. |

## Current state
- **P0 Baseline — DONE (2026-06-25).** Complete 5-shard stock-BMP baseline +
  saved query vectors at `spike/archive/mmap_bmp/out/{baseline,qvecs}.json` (1M-section
  shards, 10 SPLADE queries, k=50). Had been incomplete (1/5 shards) before the
  re-baseline; `compare_fork.py` was patched to skip shards absent from the
  baseline instead of fabricating G1 mismatches.
- **P1 (the fork) — GATE GREEN (2026-06-25):** BMP cloned to ext4 scratch
  (`/tmp/bmp-fork-work`, gitignored). P1-cheap-probe (mmap+deserialize) confirmed
  R2 (didn't cure the floor); then committed to the **R3 flat-layout rewrite** —
  new `src/index/flat.rs` (flat serializer + mmap lazy reader) + `src/flat_search.rs`
  (reuses `block_score` unchanged). Fork patch: `spike/archive/mmap_bmp/R3_fork.patch`
  (applies clean to upstream). **G1 PASS (50/50 byte-identical); G2 PASS
  (RssAnon 0.535 GB across all 5 shards, flat in corpus — the floor is cured);
  G3 latency 67 ms vs stock 4.7 ms (R1 decode cost surfacing — a SIGNAL gate at
  P1, HARD only at P2).** The make-or-break R2 bet is won. See
  `03_GO_NO_GO_GATES.md` decision log.
- **P2 (cold-p95) — DONE (2026-06-26): GATE RED (G3a FAIL).** Built a persona-sized
  `med_bio` (23.4M docs → 16 shards → 17.8 GB `.bmp` → 9.0 GB `.bmflat`) from
  `spool_backup` (`spike/archive/mmap_bmp/build_persona_bmp.py`), transcoded via the R3 fork,
  measured via `spike/archive/mmap_bmp/measure_p2_cold.py`. **G3b PASS** (cold/warm = 1.04 — the
  cold-fault bet was *won*; cost is decode, not page faults) but **G3a FAIL** (warm p50
  696 ms vs qdrant section-scale 66 ms, ~10× — decode-bound, scales worse-than-linear:
  1M shard 67 ms → ~625k-doc persona shard ~174 ms). Per the kill criteria a HARD-gate
  fail → **stop; do NOT spin off `immsparse`; do NOT proceed to P3.** Bonus: **G2
  regresses at scale** — R3 cured only the *forward* index; the *inverted* side it left
  owned (`documents: Vec<String>` + `range_maxes: Vec<PostingList>`, both `.to_vec()` in
  `FlatIndex::from_mmap`) scales with corpus → 8.26 GB anon on 16 persona shards
  (0.5 GB/shard vs 0.535 GB for all 5 at 1M). Result:
  `data/eval_results/p2_coldp95_med_bio_4shard.json`. Full verdict: `03_GO_NO_GO_GATES.md`.
- Everything needed for P0–P2 *was* in this container (cargo 1.96, test `.bmp`,
  `spool_backup` 123 GB, live Qdrant baseline, measure harness). **Spin-off does NOT
  happen — P2 went RED (v1).** Fallback paths: per-persona Qdrant locally; Infinity or
  OpenSearch+SEISMIC server (`docs/archive/qdrant_vs_lucene_assessment/`).
- **P2 zero-decode re-test — DONE (2026-06-26): FORMAT-WALL, the kill was premature.**
  On the R3 fork, re-laid-out the forward region as `#[repr(C)]` POD (`FlatPair` +
  `TermEntry`) read via `bytemuck::cast_slice` (zero decode, zero alloc) and scored with
  a faithful `flat_block_score` twin of `block_score` (`spike/archive/mmap_bmp/R3v2_delta.patch`).
  Same 4-shard med_bio subset, same `posix_fadvise` cold mode as the 696 ms run.
  **G3a flips: warm p50 696 ms → 25.63 ms (≤ qdrant 66 ms); G1 byte-identical (50/50 @1M +
  40/40 @persona); anon 1.976 GB/4 shards; cold/warm 1.49 (G3b still won).** The wall was
  R3-v1's compact format (decode per query), NOT the Block-Max algorithm. **⚠️ Caveat:**
  the #blocks-scored confound fires hard (max 7424 ≈ full block count) — pruning touches
  O(corpus) blocks/query; the win is real but fragile at larger scale. §4 follow-ons
  (inverted-side mmap, native parallel shard search, P3/G4) still gate any re-open.
  Result: `data/eval_results/p2_zerodecode_med_bio_4shard.json`. Full verdict:
  `03_GO_NO_GO_GATES.md` decision log.
</content>
