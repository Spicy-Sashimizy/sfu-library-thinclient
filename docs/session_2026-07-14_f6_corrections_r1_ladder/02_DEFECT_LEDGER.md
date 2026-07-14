# 02 · Defect ledger — six defects, one day (2026-07-14)

All six were found by refusing to trust a number that looked too good, then
following the raw evidence. Fix commits: **2203d9b** (#1–#5), backend edits in
the R1 session for **#6** (shared `_coalesce_extents`). Every defect below
lists the evidence file a future reader can re-check.

---

## #1 — F6 gate skipped the eager SPLADE load → 100% query failure

- **Symptom:** F6 bench cells recorded cold p95 30 ms; `encode_ms` and
  `traverse_ms` **0.0 for all 300 samples**; RSS peak 1.78 GB (vs 17.6 GB in
  any real cell); load_seconds 88.6 (vs 2.8 baseline).
  Evidence: `q7_hybrid_cell_hybrid_20260714_041325_rep1.json` (invalid,
  committed in 0b4e9c3, superseded).
- **Diagnosis:** every per-query call raised
  `ImportError: onnxruntime and transformers are required for SPLADE
  encoding` (repro'd with 2-query run, stderr captured); both packages import
  fine standalone → canned message masking an environment-state failure.
- **Mechanism:** commit 77636b7 added an eager SPLADE load *gated to pin-on
  only* (`SFU_SEISMIC_MLOCK_FLOOR` / `PIN_BUDGET_GB`), because running the
  .so hooks before ORT's first dlopen breaks it. Commit 67b1f0b added the F6
  prefault under `SFU_SEISMIC_PREFLOOR_HOTSET=1` — same interaction, gate not
  extended. Prefault-on + pin-off ⇒ eager load skipped ⇒ ORT import after
  the hook ⇒ per-query ImportError.
- **Fix:** include `SFU_SEISMIC_PREFLOOR_HOTSET` in the eager-load condition
  (`sharded_seismic_backend.py`, `_pin_on`).
- **Verified:** gate-ON 2-query run — encode 32.5 ms real, traversal real.

## #2 — Bench harness scored failed queries as 0 ms successes

- **Symptom:** a cell where 300/300 queries failed was written as a
  valid-looking (and spectacular) result.
- **Mechanism:** `serve_footprint_bench.py` `query_seismic_timed` caught all
  exceptions → `log.warning` + `return [], 0.0, 0.0`; nothing downstream
  checked result emptiness.
- **Fix:** count empty results; **>20% empty ⇒ log.error + exit(3)** (refuse
  to write); nonzero ⇒ warning + `empty_results` field in the cell JSON;
  `f6_prefault_hotset_bench.py` additionally refuses to aggregate any cell
  with `empty_results > 0`.
- **Note:** the first guard version (all-failed only) was insufficient —
  defect #5's cells failed 298/300 and slipped past it; threshold tightened
  to 20% the same night.

## #3 — `prefault_ranges` returns a checksum, logged as "GB touched"

- **Symptom:** `prefault_hotset: ... touched 0.00 GB (33433 extents)` while
  prefaulting was actually working.
- **Mechanism:** `touch_bytes` (mmap_io.rs:1147) returns an anti-DCE
  **checksum** (sum of one byte per page — added because the compiler
  optimized away an earlier unobserved read loop); `prefault_ranges`
  (mmap_io.rs:1815) accumulates that checksum and the Python side divided it
  by 1e9 as if it were bytes.
- **Fix (Python-side):** log the submitted extent bytes (`acc`); checksum
  discarded. Rust return-semantics cleanup deferred to the next .so rebuild.

## #4 — MADV_SEQUENTIAL per extent → VMA-split saturation

- **Symptom (three faces):** (a) `MemoryError` reading a 21 MB manifest.json
  with 55 GB free (shards 5 and 7, two different runs); (b) parallel arm
  dead: `SEISMIC query failed: can't start new thread` for every query after
  the hybrid flip at query 3 (⇒ 298/300 empty — queries 1–2 ran sequential);
  (c) prefault mysteriously "working" yet cells poisoned.
- **Mechanism:** each `madvise(MADV_SEQUENTIAL)` on a sub-range **splits a
  VMA** (advice is stored per-VMA). ~33k extents/shard × 8 shards ≈ 264k
  splits ⇒ saturated `vm.max_map_count` = **262,144** (measured exactly:
  `/proc/self/maps` count == the sysctl). Past the limit every `mmap` fails
  process-wide: pthread stacks (⇒ can't start new thread), malloc arena
  extension (⇒ MemoryError on a small read).
- **Fix:** gap-coalesce extents before submission — merge across gaps of 32
  pages, escalating ×4 to ≤4096, until ≤2048 ranges/shard. Gap pages get
  faulted too (cheap adjacent reads, excluded from hot-byte accounting).
- **Verified:** post-fix load+prefault = **14,457 VMAs** (5.5% of limit),
  thread spawn OK, real search returns 10 results.
- **External precedent:** kernel patch def5efe0 ("mm, madvise: fail with
  ENOMEM when splitting vma will hit max_map_count", 2017) — see
  `05_EXTERNAL_PRECEDENTS.md`. The 262,144 value itself is the
  Elasticsearch/OpenSearch-mandated setting inherited by this container.

## #5 — F6 wrapper aggregated poisoned cells (298/300 failures)

- **Symptom:** the *second* invalid F6 result: cold p50 15–19 ms — below the
  ~32 ms encode cost, physically impossible; `empty_results: 298` in both
  cells; the two real samples were queries 1–2 (pre-flip, sequential arm).
- **Mechanism:** defect #4's thread failure killed only the parallel arm;
  2 successes defeated the all-failed guard; the wrapper aggregated anyway.
- **Fix:** the 20% threshold (see #2) + wrapper hard-refuses `empty_results
  > 0`.
- **Lesson recorded:** *silence is not success; a partial success can launder
  a broken cell.* Every guard threshold should assume adversarial luck.

## #6 — Per-extent mlock: same VMA saturation in the F3 pin path

- **Symptom:** first pin-ON R1 cells (8 GB / 6 GB): shards 0–3 pinned
  0.18–0.20 GB each, shard 4 `pinned 0.00 GB`, shard 5 crashed at
  `load_hotset_and_pin` line 566 (`manifest.json` read_text →
  MemoryError-class).
- **Mechanism:** `mlock` sets VM_LOCKED per range ⇒ splits VMAs exactly like
  #4; ~33k locked ranges/shard saturated the map table after ~4 shards.
  Undetected earlier because the Phase-5 T1 check pinned only **2 shards**
  (≈66k VMAs — under the limit). "Mechanism-verified at small scale" ≠ safe
  at full scale.
- **Fix:** shared module-level `_coalesce_extents()` used by BOTH the pin
  loader and the prefault; pin loader restructured two-pass (all sidecar +
  manifest reads before the first mlock); post-coalesce budget re-trim
  (locked gap pages are a hard commitment — trim tail extents until ≤110%
  of the per-shard budget, keeping the no-OOM promise honest).
- **Verified:** coalescer unit-tested (40k scattered extents → ≤2048,
  coverage preserved); pin-ON cells relaunched (results pending at the time
  of writing — see backlog R1 section for the outcome).

---

## The meta-defect

Five of six defects were invisible to the process that created them because
the *measurement layer itself* was broken (swallowed exceptions, no results
validation) — and the resulting numbers were **flattering**, which suppresses
suspicion. The durable countermeasures shipped tonight: empty-result guards
at two layers, `empty_results` in every cell JSON, result-parity harness
(`scripts/seismic_testbed/seismic_result_parity.py`), and the review rule that
any improvement a mechanism cannot physically explain (prefault speeding up
*warm* queries) is treated as a measurement bug until proven otherwise.
