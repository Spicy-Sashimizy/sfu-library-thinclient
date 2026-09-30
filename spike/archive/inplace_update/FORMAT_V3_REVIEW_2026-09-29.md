# Review of FORMAT_V3.md — coordinator, 2026-09-29

> **CLOSED MEASURED 2026-09-30** — the pre-registered GO rule of `06_INPLACE_SPIKE_PLAN.md` read NO-GO: bar S0-1 measured a long-list dead-slot coverage of **0.019** (95 % CI 0.018–0.020) against 0.80. In one quarter 27 % of shard 0's docs are updated and 15 % more are new while deletions free 6 %, and a list cannot grow, so dead-slot reuse cannot absorb the churn (`inplace_s0_20260930.json`). Nothing in-place replaces it: updates stay with delta generations (`docs/delta_ingest/`). The v3 encoder/decoder is exact (B1 460/460, +1.3 % per query) and the +tail variant was built, but they remove the wrong obstacle. Full record: `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` results table and §"NO-GO 2026-09-30". Not current; do not resume.

**Status:** CLOSED MEASURED 2026-09-30

Reviewed: `spike/archive/inplace_update/FORMAT_V3.md` at commit `2fd85ae2`, read in
full. Review by reading only: nothing here is measured, no code was run.
`UPDATER_DESIGN.md` did not exist yet and is not covered.

Verdict: the posting word, the dual header, the two-bank inflation file and
the v2-rejection rule are sound for B1 (zero patches). The defects below are
all on the UPDATE path; none changes what B1 tests. R1–R3 can serve wrong
results and must be settled before any updater run on a real shard.

## Defects (would serve wrong results)

**R1. An aborted batch is published by the next batch.** A batch that
publishes epoch e+1 tags its writes e+1. If it crashes before the header
flip, epoch e keeps serving (correct), but the words tagged e+1 stay in the
file. The next batch also publishes e+1, and at its flip the aborted batch's
inserts become visible and its delete marks take effect. The spec has no
recovery step. Fix: before any batch, the updater scans for `TAG > E` and
neutralises those words (an aborted insert → `FREE=1, TAG ≤ E`; an aborted
delete mark → `FREE=0, TAG ≤ E`, START/LEN were never touched), and does the
same for the side files (R5). Skipping an epoch number instead is not
available: bank selection is `E & 1`, so e+2 would reuse bank e.

**R2. `list_dir.bin` reverts a rewritten list one epoch later.** §3.6 writes
only the INACTIVE bank's entry. A list rewritten in the batch for e+1 is
recorded in bank (e+1)&1; bank e&1 still holds the old offset. The batch for
e+2 publishes bank e&1 again, so the list silently returns to its
pre-rewrite content unless it happens to be rewritten again. §3.2 states the
needed rule for inflation ("copying the active bank into it first"); §3.6
does not. Fix: same rule for `list_dir.bin`, stated in the spec, and covered
by an updater test that rewrites a list at e+1, publishes e+2 without
touching it, and reads it back.

**R3. The grace period is a fixed wait, and this host exceeds it.** §3.1:
content freed at epoch f may be overwritten "after a fixed drain interval,
est. ≥ 10 s", on the premise that queries are ms-long. Measured here:
`search_rrf` p95 8.29–8.89 s (`data/eval_results/warmcache_metric3_isolated_20260925.json`),
cold SEISMIC traversals 8–9 s on 9p (2026-07-18), M4 pilots 8–29 s per
query. A reader that snapshotted E before a flip can still be traversing
when the updater reuses a slot, a hole, or the inactive bank. A time-based
grace is a guess about the slowest reader. Fix: a reader table (LMDB-style:
each reader process publishes the epoch it is reading in a shared slot; the
updater reuses nothing freed at or after the oldest published epoch), or
restrict reuse to content freed at least two published epochs ago AND wait
on the reader table. Until one exists, B7's "concurrent reader sees clean
results" arm must include a deliberately slow reader.

## Gaps (unspecified, needed before the updater is trusted)

**R4. Tag/epoch width mismatch is not checked.** TAG is 15 bits, the header
epoch 64. `visible()` compares them directly, so an epoch above 32,767 makes
every tagged slot compare as old. The reader should reject a header whose
epoch exceeds 32,767 rather than rely on the compactor having run.

**R5. Side files have no crash ordering against the header.**
`list_min.bin` is one bank, mutated in place; `forward_free.bin` is
replaced by rename; both carry an epoch but no rule says which wins after a
crash. Free list renamed before the flip and then a crash: holes consumed by
a batch that never published are lost (leak). Flip before the rename and
then a crash: the old free list hands out holes that are now live (double
allocation → a live record overwritten). Needed: the order (free list and
minima are written for e+1 BEFORE the flip, and are only trusted when their
epoch equals the header's; otherwise rebuilt by scan), stated in the spec.

**R6. The writer's I/O path is not stated.** The research addendum (§D)
found mapped views and `WriteFile`/`pwrite` are coherent only through the
same mechanism on Windows. The spec says readers use atomic loads on a
mapping but not that the writer stores through a `MAP_SHARED` mapping too.
State it; B7 should name the path used.

**R7. `posting_heap.bin` is sized for one rewrite and nothing is freed
before compaction.** Reserve = `len(posting_lists.bin)` (1.16 GB) = every
list rewritten once. A2b rewrites a whole list (tens of KB) for any change
to it, and the long lists of common terms are touched by nearly every
batch. With trickle batches the heap is exhausted after roughly as many
batches as it takes to touch the long lists once each — a handful, not a
quarter (*est.*, unmeasured; W1's per-list byte distribution and S0-1's
per-list demand give the real figure). A unit superseded at epoch f is
unreachable once no reader is below f (R3's reader table), so it can go to
`posting_free.bin` then instead of waiting for compaction. B4 for A2b
should report heap bytes consumed per batch and batches-to-exhaustion.

**R8. A2b read path has an unpriced per-term cost.** For a rewritten list
the decoder must parse the unit header and build the list view (Elias-Fano
offsets, bitfield, slices) at query time; the native path does this once at
load. Either cache views keyed by (list, offset), or B3 for A2b measures the
rebuild per term. B1 cannot see this cost: with zero patches every list is
native.

**R9. Row reuse changes what a shard row means to the rest of the stack.**
§3.4–§3.5 give a reused row a new external id through
`row_id_override.bin`. Serving also resolves documents through an ordinal
space and a livedocs bitset keyed on BASE ordinals
(`src/lib/thinclient/ordinals.py`, `delta_layer.py`), hotset sidecars and the
E5 reorder map. Not verified in this review: whether any of them is indexed
by shard row rather than by W-id. If one is, a reused row is attributed to
the old document there. To be checked in code and written into the updater
design before B6.

## Notes (no change required for B1)

- N1. `visible(w, E) = (TAG <= E) XOR FREE` was checked against all four
  rows of the table and against insert-then-delete of the same slot in
  later batches; correct as long as the only readers are at E (R3).
- N2. The header flip is a 128-byte record validated by checksum, not "one
  aligned 8-byte store" as the brief put it. That is the LMDB pattern and is
  fine; B5 should describe it as such.
- N3. The flip publishes the SEISMIC leg only. BM25F sections, `meta.sqlite`
  and the abstract sidecar still take the document through the delta layer,
  so an in-place publish is not by itself a consistent view across legs.
  B5's comparison with `reload_index` should say which legs each side
  covers.
- N4. c = 255 (always visit) is the only inflation code that helps a block
  whose summary dot is 0 for the query; every finite multiplier leaves 0 at
  0. Already within the spec's stated scope limit; relevant to how S0-3's
  supplementary recall number is read.
- N5. FNV-1a-64 detects torn records adequately; it is not a CRC and gives
  no burst-error guarantee. Acceptable for a spike.
- N6. Hole reuse uses a hole whole (LEN = h, padded inside the record); no
  splitting, so absorbed demand depends on the size-class match. S0-1 counts
  posting slots, not forward holes — forward-hole supply is unmeasured.
