# SESSION PROMPT — open-queue worker: cold-path + quality levers (paste-ready)

Paste everything below the `---` into a Claude Code session in the dev
container (`/workspaces/sfu-library-thinclient`). It walks the open items of
`docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` §3 (Q7 first, per the
2026-07-10 queue extension). **Doc 12 is the source of truth** — if this file
and doc 12 disagree, doc 12 wins; update whichever is stale in the same
commit you notice it.

---

You are working the SEISMIC 150M open queue. Work items IN ORDER; each item
is take-one-finish-one: implement → measure against the pre-registered bars →
record the verdict in the named doc → commit → only then take the next item.
Do not start an item you cannot finish measuring in-session; leave a dated
"IN PROGRESS" note in doc 12 §3 if interrupted.

## Standing rules (binding — violations invalidate the session)

1. **Rule Zero — served shards are irreplaceable, READ-ONLY.**
   `data/seismic_150m/index/plan01/global_shard{0..7}of8.dotvbyte{,.e5}.mmap`
   are never copied/moved/re-converted/deleted. New artifacts go to NEW dirs.
   `du -sb` inventory before AND after any session that touches shard paths.
2. **Git workflow:** `git pull` before edits; explicit `git add <files>`
   (NEVER `git add .` — the tree carries multi-GB runtime state); commit +
   push immediately after each logical unit. Branch: `spike/mmap-bmp`.
3. **Venv:** `.venv/bin/python3` for everything; sudo pip installs target the
   venv only.
4. **Pre-registration:** write the bars BEFORE looking at results (they are
   already written below — do not move them after the fact). "Should improve
   X" is forbidden in docs; every claim gets numbers + result-file path +
   absolute date, or is marked `*est.*`/UNMEASURED.
5. **Cold-measurement protocol (this container, established 2026-07-09):**
   `/proc/sys` is read-only → no `drop_caches`; use full-inventory
   `posix_fadvise(DONTNEED)` eviction before every cold cell. Fresh-process
   mmaps on 9p re-fault Linux-cold regardless of page cache. Windows-side
   cache is not evictable here → **only paired A/B ratios are verdicts;
   absolute cold numbers are indicative only.** A cold cell counts only if
   its JSON shows VmSwap ≈ 0 AND warm p50 < cold p50.
6. **Only same-process interleaved (or alternating-cell) A/Bs are promotable
   evidence** on this container (D2 methodology rule, 2026-07-09).
7. **Refuted levers — do NOT re-propose:** MADV_RANDOM, per-query
   MADV_WILLNEED, page-aligned/padded records, THP, readahead tuning
   (drvfs), hot/cold-first walk orders, per-doc single-term ordering keys,
   meta-DB ordering keys, df term-subsets, query_cut < all at 150M,
   dynamic-int8 query encoder, FastGelu, ORT thread pinning/spin-off,
   int6 forward (revival only via Q4/M2b).
8. **Same-commit doc rule:** the doc named in each item is updated in the
   same commit as the measurement (doc 12 §3 verdict line + the item's
   detail doc + doc 06 ledger row for measured results).

## The queue (take topmost unblocked)

### 1) Q7 — cold-start hybrid federation (sequential-cold → parallel-warm)

The cheapest unclaimed serving win; basis measured 2026-07-09
(`data/eval_results/e5_fullcorpus_cold_container_*.json`): sequential cold
p50 2159 ms < parallel 2687 ms (VmRSS 1.34 vs 25.2 GB); warm inverts
(parallel 80–101 ms ≪ sequential 367 ms).

- Implement `--federation hybrid` in the sharded backend
  (`src/lib/thinclient/sharded_seismic_backend.py`) + plumb through
  `scripts/seismic_testbed/serve_footprint_bench.py`. Start sequential;
  flip to parallel on a **state signal** (pre-register it before measuring:
  e.g. per-query traverse ms dropping below a threshold for 2 consecutive
  queries; include a fixed query-count arm as the dumb control). The flip
  cannot change results — both modes are bit-identical already.
- **Bars:** hybrid cold p50 ≤ 1.05× sequential cold; hybrid warm p50 ≤
  1.05× parallel warm; T1 parallel≡sequential≡hybrid 100/100.
- **Eval:** 3-arm alternating cells (parallel/sequential/hybrid × 2 reps),
  fadvise-DONTNEED before each, `--queries 40 --passes 3`. Results
  `data/eval_results/q7_hybrid_federation_*.json`.
- **Record in:** doc 12 §3 Q7 + doc 06 row; if promoted to served default,
  `docs/THIN_CLIENT_SWAP.md` same commit (env-var gate + rollback note).

### 2) E1-owed — federated k' check is ALREADY PAID (verify, don't redo)

2026-07-08 G8f flipped the served default to `max(2×top_k, 100)` after the
federated gate passed (merged overlap@10 0.999). Before working any latency
item, confirm the flip is still live in `retriever.py`/env docs — this is a
freshness check, not new work. If a doc still says k'=200 default, fix it in
the same commit.

### 3) Q9 — startup floor prefault (load-time; composes with Q7)

- Background thread at backend load touches the small structural files
  (forward_offsets, doc-mapping offsets/strings, summaries) — NOT
  forward_data. This is once-at-load, distinct from the refuted per-query
  WILLNEED (doc 10 Fix #3); record that distinction in the verdict.
- **Bars:** cold-pass p50 ≥ 1.15× faster with prefault ON (else KILL);
  load-time increase ≤ ~5 s; warm p50 ratio ≤ 1.05; zero anon growth.
- **Eval:** ON/OFF alternating cold cells × 2 reps, same protocol.
  Results `data/eval_results/q9_floor_prefault_*.json`. Doc 12 §3 Q9 +
  doc 06 row.

### 4) Q8 — posting-side cold-fault attribution → sim (sim before ANY converter)

- **Stage 0a:** one cold run per arm WITHOUT `PREFLOOR` prefaulting;
  attribute majflt per file (mincore snapshots of each mapped file, or
  per-file fadvise + delta). **Bar: posting-side share ≥ ~25% of residual
  cold faults → Stage 0b; below → KILL on paper** (record the share in
  doc 12 §3 Q8 — a small share is itself the finding).
- **Stage 0b (only on 0a GO):** Q6-methodology page-touch sim of a
  co-access ordering of posting blocks on real per-query block-touch sets
  (extend the fork's `search_visited` capture if block ids aren't already
  derivable). **Bar: worst-shard unique-page ratio ≤ 0.60 else KILL** —
  readahead absorption under-realizes adjacency wins (Fix #5A lesson), so
  demand a decisive sim margin before any Rust.
- No converter work in this session regardless of outcome — sim verdict only.

### 5) Q3 — M8 survivors-per-block instrument (quality-free, ~20 lines)

- Counter in the traverse path (or offline from posting-block stats):
  average candidates contributed per surviving posting block.
- **Bars (`docs/math_optimization/08` §M8):** typical batch ≥4 → GO for the
  register-blocked kernel (bit-identical, latency-gated); <2 → M8 dies on
  paper. Record in math 08 §M8 + doc 12 §3 Q3.

### 6) Q1 — E8 dv-v2 per-doc scale, Stage 1 (Rust; the quality-recovery lever)

- Stage 0 GO already measured (0.997/0.993 vs FixedU8Q 0.985/0.984).
  Stage 1 = v2 encoder/loader in `spike/vectorium_fork` (format-version
  bump, cross-version load rejection), convert shards 1–2 ONLY into new
  dirs, gate a vs f16 twins at n=100.
- **Bars:** both shards ≥0.99; size within ±2% of dv v1; warm p50 ≤ 1.05×;
  T1 green.
- **Stage 2 (full corpus) note:** ride ONE rewrite — fold the E5 perm into
  the same conversion pass (doc 13 §3, converter takes `perm` as input) so
  the corpus is rewritten once. Stage 2 is host-tier/long-job; do not start
  it casually in-session.

### 7) Q4 → Q5 — M2b pre-gate, then M6 (lossy; stay demoted)

- Q4: `m2_pregate_query_integer_dot.py` at 7-bit/i32, n=100, shards 1–2;
  ≥0.99 both shards → kernel behind `SFU_SEISMIC_M2_INT6` plumbing; else
  record and STOP (the FAIL also kills Q5's quality leg).
- Q5 (only on Q4 PASS): cpuid inventory first (`lscpu | grep -i vnni`).

### 8) Host-tier batch (NOT this container — queue for the next host session)

H5 sequential dv @6G cap; federated-merge dv-vs-f16 overlap (two-pass
method idea, unvalidated); absolute nDCG for the dv leg (after Q1 Stage 2);
optional true-disk-cold absolute numbers for E5
(`HOST_PROMPT_E5_FULLCORPUS_COLD.md`, now optional — ratio already
confirmed in-container 0.569×).

### 9) Q10 — delta-shard ingest: PARKED

Design is settled (doc 13 §3: new docs → small shard 9, federation already
merges K shards, fold in at next rebuild). Build NOTHING until a real
ingest requirement lands.

## Session end

Re-read doc 12 §3 against what was actually measured; every touched item
gets a dated verdict line. Doc 06 gets one row per measured result. Push
everything. If a result flips a served default, `docs/THIN_CLIENT_SWAP.md`
is updated in the same commit — no exceptions.
