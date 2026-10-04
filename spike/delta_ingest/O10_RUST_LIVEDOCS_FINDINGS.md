# O10 — Rust gather-time livedocs skip

**Status:** ACTIVE

Open issue O10 (`docs/delta_ingest/02_DESIGN.md` §3.1 row O10, §4 item 3):
the livedocs filter is a Python per-shard post-filter costing 6.5 / 10.6 ms p50
per query (empty / synthetic bitset, 2026-09-29,
`data/eval_results/delta_ingest_livedocs_20260929.json`) next to a ~65 ms warm
traverse. This spike builds the Rust gather-time skip on a fork branch, side
loads it, and measures parity, correctness and cost.

- Fork branch: `livedocs-skip` in `spike/seismic_upstream/` (off `main`
  2c4d863; `main`, `inplace-v3`, `b1-guard` untouched). Commits: see §5.
- Patch (outer repo): `spike/delta_ingest/patches/seismic_livedocs_skip.patch`
  (`git format-patch main..livedocs-skip`). `seismic_upstream_fork.patch` is NOT
  regenerated.
- Harness: `scripts/experiments/eval_delta_ingest_o10_rust_livedocs.py`.
- Results: `data/eval_results/delta_ingest_O10_rust_livedocs_20261001.json`.
- Side builds + work files: `/home/vscode/work/delta_ingest/rust/`
  (`so/branch`, `so/ctl`, `build.sh`). The installed `.so` (sha256 6263…d6c6,
  2026-08-10) was never replaced.

## 1. How livedocs works today (code reading, 2026-10-01)

- Bitset: one bit per base ordinal (`src/lib/thinclient/livedocs.py`; ordinal =
  dense address over the base `meta.sqlite`, sorted by W-id number). Written by
  `spike/delta_ingest/livedocs.py` at publish, named in `generations.json`.
- Serving: `DeltaLayer.attach_seismic` installs `shard_result_filter` as the
  backend's `_shard_result_filter`; `search_encoded` calls every shard with
  k' = max(2·top_k, 100) (= 100 at top_k 50), then the filter maps each
  result's W-id string to an ordinal (`OrdinalSpace.lookup`: string parse +
  `searchsorted` over 150M wids) and tests the bit; base shards drop dead ids
  and JSON-`deleted` ids, delta shards apply the newest-copy rule. Then
  `_merge_topk`.
- So the delivered Python path is **"search k' then filter"**, with NO extra
  over-fetch: a shard that loses d candidates contributes k'−d. The 2026-09-29
  R1 measured ≤ 3 drops per shard at 0.1 % density, and every query stayed
  certified exact at top-50 (101/101).
- The served shards are `MmapSeismicIndex` over dv-v2 E5 dirs
  (`MmapSeismicIndexDotVByte::search_raw` → `search_raw_visited` in
  `src/mmap_io.rs`; posting scan `MmapPostingList::search` /
  `sort_and_search` / `evaluate_posting_block` in `src/mmap_index.rs`).
  Postings store packed FORWARD RANGES, not doc ids; the traversal dedups
  candidates by `visited.insert(range.start)` and maps winners back to doc
  indices only at the end (`id_from_range`, a binary search over offsets).

## 2. Design

**Where the skip happens — gather time, by seeding `visited`.** A dead doc is
represented by its forward-range start, the exact key of the traversal's dedup
set. `search_raw_skip` initialises `visited` with the shard's dead starts, so
each dead candidate fails its first `visited.insert` and is neither prefetched,
decoded, scored nor pushed — on both the M8 batch and the scalar block loop.
The posting-block loop is shared and unchanged: no new instruction runs per
candidate. The cost is O(D) inserts per query per shard (D = dead docs in
that shard), paid once at query start. This differs from the 2026-09-29
design-only sketch (thread a tombstone check through `evaluate_posting_block`):
that adds a per-candidate test in the hot loop; seeding `visited` adds none.

**Zero cost when no bitset is passed.** `search_raw_skip` is a separate Rust
body (a copy of `search_raw_visited` that differs only in the `visited`
initialisation). `search` / `search_raw` / `search_raw_visited` keep their
exact source; the no-livedocs path is not a flag test on a shared body, it is
the untouched function. Proof attempts: §4 P1 (bit parity) and C1 (timing,
plus a disassembly comparison of the served search symbol between a control
build of `main` and the branch build with identical toolchain and flags).

**API (pyo3, `MmapSeismicIndex`, dotvbyte shards; f16 raises
NotImplementedError):**

| call | when | cost |
|---|---|---|
| `doc_indices_for_ids(ids) -> list[int]` (−1 = not in shard) | once per mask publish, per shard | one linear pass over the doc-mapping slab |
| `dead_set(doc_indices) -> MmapDeadSet` | once per mask publish, per shard | O(D log D) (range lookup, sort, dedup) |
| `search_skip(qid, comps, vals, k, query_cut, heap_factor, dead, sorted=True)` | per query | `search` + O(D) seeding |

`MmapDeadSet` is an opaque frozen object bound to the shard instance it was
built from (forward-data base address; a set from another shard or another
load is refused with ValueError, never applied). Reload = build new sets and
swap the Python reference (the old set is dropped when no query holds it); no
locks in Rust. Empty docs (zero-length range, start equal to the next doc's
start) are excluded from the set — they never appear in a posting list and
seeding them would kill a live neighbour. The bitset reaches Rust as doc-id
strings → shard-local indices, not as a borrowed bitset buffer: the bitset is
over the BASE ordinal space (sorted W-ids) while shard docs are addressed by
shard-local index, and the shards carry no ordinal map; a per-shard
`local → ordinal` u32 array (75 MB/shard) would let Rust read the `.liv` mmap
directly but is a build-time artefact that does not exist yet.

**Semantics — which "equivalent" is it?** Dead docs never take heap slots, so
the per-shard result is k' LIVE docs, and the heap threshold that drives block
skipping is computed over live docs only. That is the approximate search of an
index from which the dead docs were removed (block summaries still include
them; they are upper bounds, so block skipping can only become more
permissive). It is NOT bit-identical to "search k' then filter" (the delivered
Python path): the skip returns k' live results where the filter returns k'−d,
and the skip's lower heap threshold can admit blocks the unmasked search
skipped. On an exhaustive traversal it equals "exact search then filter" at
depth k' exactly (Rust unit test `livedocs_skip_exact_and_bound`); on the
served approximate traversal it is measured against an exact-then-filter
reference (search k=2000, filter, truncate to k') in §4 S1.

## 3. Results (measured 2026-10-01, served shard 0)

All runs: served shard 0 `global_shard0of8.dotvbyte.e5.v2.mmap`, read from the
local staged copy `/var/tmp/seismic_stage/…` (all 12 files `cmp`-identical to
`data/seismic_150m/index/plan01/…`, 2026-10-01 ~16:50Z); queries = the M9 file
(120 topics + 100 diverse, top-64 SPLADE terms, encoded once 2026-10-01
04:13Z, enc sha256 db648ae5…; copy `/home/vscode/work/delta_ingest/rust/queries.json`);
child interpreters `/home/vscode/work/venv_local/bin/python3`, `taskset -c
8-15`, side `.so` first on `sys.path`. Builds: `maturin build --release`,
`RUSTFLAGS=-C target-cpu=x86-64-v3`, nightly toolchain of 2026-10-01; branch
`.so` sha256 57b2cc31…, control (fork `main` 2c4d863, same toolchain/flags)
sha256 d011fd18…; installed `.so` 62639335…d6c6 (untouched). Harness
`scripts/experiments/eval_delta_ingest_o10_rust_livedocs.py`; results
`data/eval_results/delta_ingest_O10_rust_livedocs_20261001.json` (written by
its `finalize` subcommand from the work files under
`/home/vscode/work/delta_ingest/rust/`).

| item | what | result | bar | verdict |
|---|---|---|---|---|
| Rust unit test | `livedocs_skip_exact_and_bound` (120-doc dv-v2 index; exhaustive traversal) | skip == exact-then-filter at depth k, both M8 gate settings and both entry points; empty set == `search_raw`; foreign set refused; pruned 16-term query returns 0 dead | all asserts | PASS |
| P1 no-bitset parity | branch `.so` `search` vs installed `.so` `search`, k=200, query_cut=len(terms), heap 0.8 | **220/220 byte-identical** (json of (doc, score)) | 220/220 | **PASS** |
| P1b | branch `search_skip` with an EMPTY dead set vs branch `search` | **220/220 byte-identical** | 220/220 | **PASS** |
| P1c | control `.so` (main 2c4d863, v3) vs installed | 220/220 byte-identical | report | — |
| disassembly | ctl vs branch `.so`, normalised `objdump` (RIP-relative displacements and symbol comments stripped) | `MmapSeismicIndexDotVByte::search_raw_visited` (3,654 B), `MmapPostingList::search` (778 B), `sort_and_search` (1,031 B), `evaluate_posting_block` (1,118 instr.) **instruction-identical**; the pyo3 `PyMmapIndex::search` wrapper is NOT (4,734 → 4,811 B; `__pymethod_search__` 2,076 → 2,435 B): argument-extraction glue inlined differently; a per-call constant, never per candidate | report | traversal identical; wrapper differs |
| S1 F1 synth | 0.1 % random base ordinals (2026-09-29 fixture, popcount 150,415; 18,884 in shard 0), k'=100, heap 0.8 | 0 dead returned (220 queries); only 15 queries had a dead id in the unmasked top-100; skip vs Python filter: top-10 identical 220/220, Python list a prefix of the skip list 220/220 | 0 dead | **PASS** |
| S1 F2 bite | F1 + top-3 shard-0 ids of every query (popcount 150,884; 19,353 in shard 0) | 0 dead returned; every query had dead ids in the unmasked top-100 (1,099 total, Python list min length 86); skip vs Python: overlap@10 mean 0.99909 (min 0.9), top-10 identical 218/220, Python list a prefix of the skip list 190/220 | 0 dead | **PASS** |
| S1 vs deep reference | search k=2000, Python filter, truncate to 100 | F1: overlap@10 skip 0.97955 = Python 0.97955 (top-10 identical 186 both); F2: skip 0.97545 vs Python 0.97455 (top-10 identical 179 vs 177) | report | skip ≥ Python |
| reload cost | `doc_indices_for_ids` (150k W-ids, one pass over the 18.8M-doc slab) + `dead_set` | 0.28–0.45 s + 0.003–0.045 s per shard (shared lock, indicative) | report | — |
| C1 cost, run 1 | shared lock, SERVE shared job concurrent; 220 queries × 2 reps × 2 rounds; arms in FIXED order plain → filter → skip | F1: plain 4.012 ms, plain + Python filter 4.538, skip 3.463 p50; ctl plain 3.693 (branch/ctl 1.086). F2: plain 2.945, plain + filter 3.355, skip 2.486; ctl 3.164 (0.931) | — | **INVALID / indicative** |

Reading of the deep-reference row: the k=2000 reference uses a bigger heap, so
it prunes less; the ~0.975–0.98 overlap is the k'=100 approximation of SEISMIC
itself and is the same for both paths. The skip is "approximate search over
the live docs", never worse than the Python filter here.

**What the numbers do NOT show.** C1 run 1 is invalid by declaration (shared
lock, a concurrent job) and biased: skip always ran right after plain on the
same query, on a warmer cache, which is why skip < plain. The branch/ctl ratio
swings 1.086 ↔ 0.931 between two fixtures run minutes apart, i.e. this run
cannot resolve a 1 % difference. Python filter cost here is ONE shard
(100 candidates, warm ordinal arrays on local disk): 0.41–0.51 ms p50, ×8
shards ≈ 3.3–4.1 ms *est.*, vs the 2026-09-29 8-shard 6.5 / 10.6 ms. No
exclusive-lock timing exists. **Efficacy: IMPLEMENTED, EFFICACY UNMEASURED.**

Queued (not run at the time of writing): the order-alternating cost arm
(skip-first / plain-first per rep, 4 reps × 2 rounds, F1 and F2) under a
SHARED lock — `/home/vscode/work/delta_ingest/rust/rust_cost_queue.sh`, log
`rust_cost_queue.log`; it ends by running `finalize`, which folds
`C1_cost.shared_F1b` / `shared_F2b` into the results JSON. Those numbers will
also be INVALID/indicative (shared lock).

## 4. What an operator must do to ship it

1. Owner decision first: the no-livedocs path is proven bit-identical in
   results (P1) and instruction-identical in the traversal, but the pyo3
   wrapper changed by inlining, so a per-query timing on an exclusive lock
   (ctl vs branch `.so`, plain `search`, alternating processes — the harness
   `cost` arm, run under `flock -x` on a quiet host) is still owed against
   the 2026-09-30 bar (no per-query cost on the serving path).
2. Apply `spike/delta_ingest/patches/seismic_livedocs_skip.patch` (or merge
   fork branch `livedocs-skip`, 620f1d2) onto fork `main`, rebuild with
   `RUSTFLAGS='-C target-cpu=x86-64-v3' maturin build --release -i <venv python>`
   (doc 10 §7.7; never `develop`, never native), install the wheel into
   `.venv` and the local mirror `/home/vscode/work/venv_local`, and regenerate
   `seismic_upstream_fork.patch`.
3. Gates to rerun on the swapped `.so`: the WI-4 parity/warm gates
   (`scripts/seismic_testbed/wi4_portable_cpu_gates.py`), the delta-ingest
   livedocs G1/G2 (`scripts/experiments/eval_delta_ingest_livedocs_bitset.py`),
   this harness's `parity` and `skip` arms.
4. Wire the Python hook (design below; NOT written): until then, the new API
   is unused and serving keeps the Python filter.

**Python hook — DESIGN ONLY (not written).** Gate `SFU_DELTA_RUST_SKIP`
(proposed, default OFF). In `DeltaLayer.attach_seismic`: when the gate is on
and every base-origin shard has `search_skip`, build per-shard dead sets
(livedocs set bits → `ordinals.wids` → `"W<n>"` → `doc_indices_for_ids` →
`dead_set`, ~0.3–0.5 s per shard at reload) and install them as
`backend._shard_dead_sets` (by shard position; `None` for delta shards);
otherwise fall back to today's filter. In `search_encoded` (both bodies in
`sharded_seismic_backend.py`), a shard with a dead set calls `search_skip`;
the per-shard filter still runs, but on base shards with a dead set it only
checks JSON `deleted` (set membership, no ordinal lookup); delta shards keep
the newest-copy rule. Not written in this wave because it needs a call-site
change in two `search_encoded` bodies of a shared file other agents were
editing, and it would be dead code until the `.so` is swapped (step 2).
Rows for `docs/ENV_GATES.md` / `docs/CODE_INVARIANTS.md` go in with that
change, not before.

**Scaling limit (design).** Seeding costs O(D) hash inserts per query per
shard (D ≈ 18.9k here). At much higher densities (a quarterly delta with
millions of base deletes before fold-in) this grows linearly; the alternative
is a per-candidate check in the block loop (cost independent of D, but it
touches the hot loop and needs its own monomorphised copy). UNMEASURED beyond
D ≈ 19k per shard.

## 5. Commits

- Fork `spike/seismic_upstream`, branch `livedocs-skip`: 620f1d2 (off `main`
  2c4d863; `main`, `inplace-v3`, `b1-guard` untouched).
- Outer repo: 479e3d2c (harness + design draft), 75150aca (patch export),
  3c7b8b92 (cost-arm order alternation), and the results/findings commit that
  adds this section.
