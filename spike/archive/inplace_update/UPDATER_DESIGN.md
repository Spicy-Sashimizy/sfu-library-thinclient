# Bit updater for format v3: arms A2 and A2b (design)

> **CLOSED MEASURED 2026-09-30** — the pre-registered GO rule of `06_INPLACE_SPIKE_PLAN.md` read NO-GO: bar S0-1 measured a long-list dead-slot coverage of **0.019** (95 % CI 0.018–0.020) against 0.80. In one quarter 27 % of shard 0's docs are updated and 15 % more are new while deletions free 6 %, and a list cannot grow, so dead-slot reuse cannot absorb the churn (`inplace_s0_20260930.json`). Nothing in-place replaces it: updates stay with delta generations (`docs/delta_ingest/`). The v3 encoder/decoder is exact (B1 460/460, +1.3 % per query) and the +tail variant was built, but they remove the wrong obstacle. Full record: `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` results table and §"NO-GO 2026-09-30". Not current; do not resume.

**Status:** CLOSED MEASURED 2026-09-30

**State: DESIGN. Written 2026-09-29, before any updater code existed**, by the
bit-updater + benchmark-harness agent of session
`session_01W21GKQhsdhoE9jbxQScFr5`. It was started ahead of the GO gate of
`docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` at the owner's request, and GO
may still read NO-GO. Nothing here is measured. Every cost is *est.* until a
results file under `data/eval_results/inplace_b_updater_<UTCDATE>.json` cites
it.

Inputs (read in full on 2026-09-29):
- `spike/archive/inplace_update/FORMAT_V3.md` at `2fd85ae2`: the 128-byte header record and the A2b reservations.
- `spike/archive/inplace_update/FORMAT_V3_REVIEW_2026-09-29.md` (R1–R9, N1–N6).
- Plan 06 with both addenda.
- Brief 05, its two notes and addendum P2.
- `04_IMMUTABILITY_RESEARCH.md` §"Addendum 2026-09-29".
- The encoder/decoder at fork commit `2b5c7df` (`src/inplace_v3.rs`, `v3_visible` in `src/mmap_index.rs`).

Where the review and the spec disagree, this design follows the review and
says so.

Code: `spike/archive/inplace_update/updater/` (Rust crate `inplace_updater`, library
and CLI `inplace-updater`). Harness:
`scripts/archive/inplace_update/eval_inplace_bench.py`.

---

## 0. Decisions in one screen

| # | Decision | Why |
|---|---|---|
| D1 | **A2 writes only into content that is dead at the published epoch. No undo record.** | An undo record gives rollback after a crash. It does not give B7(c): an eviction or a same-batch slot reuse changes what a concurrent epoch-e reader sees before the flip. A new record written into the hole of a doc that epoch e still serves can be torn-read and mis-decoded. Only the dead-at-epoch rule satisfies (a), (b) and (c). |
| D2 | **Arm A2 (frozen, primary) = ONE epoch flip** (`--phases one`). Under D1, a batch fills only slots and holes dead at the epoch it starts from. A fresh v3 copy has none, so A2's first batch absorbs **zero** inserts, and every later batch absorbs only the previous batches' frees. That count is recorded as the result of the pre-registered arm (plan 06, Addendum third). **Variant A2-2p (supplementary, `--phases two`)** = a FREE epoch e+1, then a FILL epoch e+2. It has two sub-variants for where an UPDATED doc's old postings are marked: `old-at-free` (marked in flip 1; the doc is absent from the SEISMIC leg between the flips) and `old-at-fill` (marked in flip 2 together with the insert of the new version; no gap, but those slots and that hole become supply only for the next batch). | The frozen arm is run as defined. The variant shows what the safety rule costs: a second flip, a wait on the reader table, and (old-at-free) a gap. |
| D3 | **Reuse is gated by a reader table, not a timer** (R3). Content freed at epoch f is reused iff f ≤ min(epoch of every registered live reader). | At E = f a word with FREE=1, TAG=f is invisible ((f≤f) XOR 1 = 0). The review's "freed before the oldest reader" (<) would deadlock the FILL phase under steady traffic. See §6. |
| D4 | **Mechanism B is planned per list as top-cap** over (survivors ∪ new), cap = the list's slot count. | The brief's sequential rule (dead slot, else evict the minimum if smaller, else drop) with dead slots treated as −∞ is streaming top-k. Its result does not depend on insert order (up to ties), so it can be planned up front and the evictions can go into the FREE epoch. |
| D5 | **A2b write unit = the LIST** (W1, spec §3.6). **Primary A2b = one flip**: each touched list is rewritten once into the heap tail. **A2b-2p** (supplementary) rewrites a list twice: without the removed postings in the FREE epoch, then with the inserts in the FILL epoch, using the same sub-variants as A2-2p. | Posting space for A2b is the heap tail, so no freed posting space is needed. The FORWARD RECORDS of new and updated docs still need holes (tail append is not built, spec §3.4). So single-flip A2b from a fresh copy also places zero new records. Its lists lose the deleted and updated-old postings and gain nothing. This is raised with the coordinator 2026-09-29. An A2b copy never takes A2 slot writes. |
| D6 | **Hybrid rule not applied in the gated runs** (`--hybrid-min-slots 0`, every list in place). Postings of lists below a cut-off can be spilled to a side file and counted (`--hybrid-min-slots N`), but nothing serves the spill. | The delta-buffer half of the hybrid rule needs a serving path that merges a doc's short-list postings from the delta layer with its long-list postings in the base. That path does not exist. Running "in place for long lists only" with the rest silently dropped would score quality the hybrid design never intended. The per-list-length breakdown of drops is recorded so the hybrid effect can be read off. Deviation from plan 06 §"Hard rules", stated in every results file. |
| D7 | **Doc weights = dv-v2 dequantized values of the NEW record** (`u8/255 · vmax`), obtained by encoding with the shard's `DotVByteFixedU8Encoder` (per-doc scale) and decoding the result. | This is the value the engine scores and the value `list_min.bin` holds (spec §3.3). |

---

## 1. Batch format (input)

A little-endian binary file `*.sfubat` written by the harness. The updater
never reads Python pickles.

```
header 32 B : u64 magic b"SFUBAT1\0" | u32 version 1 | u32 flags 0
              | u64 n_records | u64 FNV-1a-64 of the body
record      : u8 op (1 = DELETE, 2 = UPSERT) | u8[3] 0 | u32 nnz
              | u64 ext_id (numeric OpenAlex id, W stripped, < 2^63)
              | nnz × u16 component (token id, ascending, unique)
              | pad to 4 | nnz × f32 value (> 0)
              | pad to 8
```

- **DELETE** removes the doc `ext_id` if it is live in the shard, otherwise it is a counted no-op.
- **UPSERT of an id that is live** is an update: a delete of the old doc plus an insert of the new vector.
- **UPSERT of an id that is not live** is an insert.
- Records are applied in file order. The harness writes them in ingest order (`updated_date`, then id), as plan 06 fixes for A1. A later record for the same id supersedes an earlier one within the batch: last record wins, and the earlier record is counted as superseded.

**ID resolution.** At open, the updater builds `id → row` from the frozen
doc-mapping slab, overlaid by `row_id_override.bin`. Rows in the forward free
list (holes) are excluded. Checks: every live id maps to exactly one live
row, and a duplicate aborts the batch.

---

## 2. Plan (computed once per batch, before any write)

Inputs: the open v3 dir, the published epoch E, and the batch.

1. **Resolve.** The set of old rows `R_del` is: deleted docs, plus the old
   rows of updated docs. The set of new docs `N_doc` is: updated docs plus
   inserted docs, each with its vector.

2. **Encode.** For each new doc: the dv-v2 record (n words) via
   `push_encoded_per_doc`, decoded back into dequantized weights (D7).
   Components not in the shard's vocabulary (≥ dim) are dropped and counted.

3. **Place records (Mechanism A).** The hole supply for the FILL epoch is:
   the holes in `forward_free.bin`, plus the rows the FREE epoch frees
   (`R_del` and fully-evicted rows, see step 5). That is A2-2p. A2 (one
   flip) uses only holes already dead at E, and `old-at-fill` leaves the
   updated-old rows out of this batch's supply.
   - Docs are placed in batch order. Each takes the **best-fit hole**: the smallest h ≥ n, ties to the lowest START.
   - A doc with no fitting hole is **unplaced**. It is counted, and none of its postings are written. Tail append is not built (spec §3.4). Unplaced docs are what would go to the delta buffer. The results record them as lost to A2 (not served).

4. **Per list t, in ascending t (the term-sorted apply).** Inputs:
   - S = the slots visible at E whose row is not in R_del.
   - D = the slots dead at E, plus the slots of R_del rows. The latter are dead after the FREE epoch. A2 (one flip) excludes them, and `old-at-fill` excludes the updated-old ones.
   - N = (placed doc, weight) pairs with a weight on t.
   - cap = |S| + |D| = the list length (lists never grow).

   Then:
   - If |N| ≤ |D|, every n ∈ N is inserted. No weight of S is needed.
   - Else, sort N by weight, descending. The first |D| take the dead slots. The rest are compared against m = min(list_min[t] if its slot survives, the inserted weights). If max(rest) ≤ m, the rest are dropped and nothing is decoded. Otherwise S is decoded: the weight of t is read from each survivor's record, ≤ 5,250 record decodes. Final = top-cap(S ∪ N), ties to the existing posting. Evicted = S \ Final. Dropped = N \ Final.
   - A2 (one flip) never evicts. An evicted slot could only be refilled in a later batch, so the posting would be lost now for nothing. Overflow is dropped.

5. **Rows left with no posting.** A placed doc whose postings were all
   dropped is unplaced, and its hole goes back to the supply. A base doc whose
   postings were all evicted is freed: its row becomes a hole in the FREE
   epoch. This keeps one definition of a hole everywhere, which §5.3's
   rebuild relies on: a row that has ≥ 1 posting, all of them dead.
   Evicted-everywhere docs cannot be retrieved in any case.

6. **Slot choice (A2 only).** Each inserted posting (weight order) takes the
   dead slot whose block needs the smallest inflation code for this doc
   (§3.3). Ties go to the larger summary dot with the doc (the nearest
   cluster by summary), then to the lowest slot.

7. **list_min.** The new minimum over Final (weight, lowest slot on ties).
   It is recomputed by decoding only when the old minimum's slot was freed and
   S was not already decoded. An empty list gets bit 63.

The plan is held in memory. Its size is O(#new postings + #freed postings);
all Q1 in-place postings are *est.* ≤ a few hundred MB.

---

## 3. Arm A2: writes

### 3.1 FREE epoch (publishes e+1)

1. **Pre-batch** (§5): recovery scan, then the reader-table gate for the
   inactive banks: wait until oldest ≥ E.
2. Copy the active inflation bank E&1 into the inactive bank (E+1)&1, and do
   the same for `list_dir` (R2). A2 never changes list_dir, but the inactive
   bank must equal the active one.
3. For every freed slot (update-old, delete, eviction), store one aligned
   8-byte word into the `MAP_SHARED` mapping of `posting_lists.bin`:
   `w' = 1<<63 | (e+1)<<48 | (w & 0xFFFF_FFFF_FFFF)`. START/LEN are kept, so
   the word stays visible at e (spec §2.2, row 3).
4. Write `list_min.bin` entries whose value changes in this epoch (epoch
   field e+1). Write `forward_free.bin.next` = the free list at e+1: old
   holes plus the freed rows, entry epoch e+1, header epoch e+1. Then fsync
   the next file and the directory.
5. Sync `posting_lists.bin` (msync MS_SYNC + fsync) and the inactive banks.
6. **Flip:** write header slot (e+1)&1 with epoch e+1, the checksum word stored
   last. Then msync + fsync the header.
7. Post-flip: rename `forward_free.bin.next` → `forward_free.bin`, then fsync
   the directory (R5, §5.2).

### 3.2 FILL epoch (publishes e+2)

1. Gate: wait until oldest reader ≥ e+1. This covers the FREE epoch's frees
   (f = e+1), the old holes (f ≤ e), and the inactive bank (E+1)&1 = e&1 that
   readers at e used.
2. Copy the active banks (e+1)&1 into (e+2)&1 (R2).
3. **Forward records:** for each placed doc, pwrite its record into its hole
   [s, s+h), padded to h words INSIDE the record (zero words just before the
   end-anchored u8 values tail, spec §3.4). Each padded record is verified by
   decoding it and comparing with the unpadded decode; a mismatch aborts
   before any posting is written. No reader can reach these bytes (§6).
4. **row_id_override:** an 8-byte atomic store `1<<63 | ext_id` at each
   reused row. The row is dead at e+1 and its new postings carry TAG e+2, so
   no visible posting reaches it (spec §3.5).
5. **Posting words:** for each insert, store
   `w' = (e+2)<<48 | START=s<<16 | LEN=h` into its dead slot (FREE=1,
   TAG ≤ e+1 before the store). Old or new, the word is invisible at e+1, and
   the store is a single 8-byte atomic, so it cannot tear.
6. **Inflation** in bank (e+2)&1: `code_b := max(code_b, ceil((ratio−1)·32))`,
   where ratio = max over c ∈ summary(b) ∩ doc of max(old_c, w_c)/old_c.
   Here old_c is the on-disk dequantized summary value; the summary itself is
   never written in A2. Codes > 254 are stored as 255 (saturated). Components
   of the doc that are absent from summary(b) are counted and summed as
   `blind_components` / `blind_mass`, as in S0-3. This is the rule
   `spike/archive/inplace_update/sim.py` uses, except that code 255 is the saturation
   marker (spec §3.2).
7. `list_min.bin` entries (epoch e+2). `forward_free.bin.next` = the free list
   minus the holes consumed. fsync both.
8. Sync forward_data, row_id_override, posting_lists and the inactive banks.
   Flip to e+2 and sync. Rename next → forward_free.bin and fsync the
   directory.

### 3.3 Arm A2 proper (one flip) and the A2-2p sub-variants

**A2 (the frozen arm)** is one epoch e+1 that does the §3.1 writes and the
§3.2 writes (FREE marks, then records, overrides, words, inflation, one
flip), with three restrictions:
- Holes and slots must be dead at E: f ≤ E and f ≤ the oldest reader.
- No evictions (an evicted slot could not be refilled before the next batch).
- This batch's frees become supply from the next batch on.

**A2-2p `old-at-free`** is §3.1 then §3.2 exactly as written.

**A2-2p `old-at-fill`** differs in one place: the old slots of UPDATED docs
are not marked in the FREE epoch. They are marked (FREE=1, TAG=e+2) in the
FILL epoch, next to the insert of the new version. That is a tag-only write,
so it is rollback-safe. Those slots and the old hole join the free list with
f = e+2, and only the next batch can use them. True deletions and evictions
are still marked in flip 1.

For both sub-variants the harness records the gap (FREE flip → FILL flip
wall time) and scores B6's overlap vs A3 at e+1 and at e+2.

---

## 4. Arm A2b: list rewrite into `posting_heap.bin`

The same plan (§2, steps 1–5 and 7) decides the surviving postings. Only the
placement and the summary differ.

### 4.1 Unit (spec §3.6)

- 8-byte aligned at `heap_base + bump`, with `heap_base = len(posting_lists.bin)` in the unified address space.
- Header: 256 bytes, `{u64 magic b"SFUL2B3\0", u32 list id, u32 epoch written, u64 body bytes, 23 × u64 PostingListManifest scalars in manifest order, u64 FNV-1a-64 of header[0..248] ‖ body}`. The 23 scalars are serialised in `PostingListManifest` field order, with bool and u8 fields widened to u64.
- Body: the native slice sequence (packed postings, block offsets, EF high words, three inventories, EF low words, summaries_ids words, values, minimums, quants, optional component ids). Alignment is computed relative to the body start (the body start is 8-aligned, so every alignment ≤ 8 holds in absolute terms).

### 4.2 Rewriting list t

1. **Decode:** the words, block offsets, and the summary as per-block raw entries (component, u8 code) plus the per-block (min, quant).
2. **Remove** freed postings (FREE epoch) or add inserts (FILL epoch).
   - An insert goes to the block with the largest dot(dequantized summary_b, doc), ties to the lowest block. The build's k-means centroids are not stored, so the summary stands in for the nearest centroid.
   - Within a block, old postings keep their order and new postings are appended.
   - A block left empty is removed, so n_summaries can shrink. The unit's scalars are authoritative, and the decoder must not apply `block_inflation` to a unit list (asked of the spec owner 2026-09-29).
3. **Summaries:**
   - An **unchanged block** keeps its raw (codes, min, quant) byte-for-byte.
   - A **changed block** gets the build's `energy_preserving_summary`: component-wise max over the block's docs, sorted by value, prefix until the mass reaches 0.4 of the total (inclusive), re-sorted by component. It is quantised with the build's `quantize` (min, (max−min)/255, round).
   - Input values are the served dv-v2 dequantized values of the member records. The build used the f16 source values, so a changed block's summary can differ from what a fresh build of the same members would produce, by ≤ 1 u8 quantum of the record values (*est.*). Stated in results as `a2b_summary_input = "dv-v2 dequantized"`.
4. **Offsets/strategy:** the build's rule. The sparse strategy (component_ids plus EF over offsets) is used iff `estimate_sparse_space < estimate_dense_space` (toolkit `EliasFano::estimate_space_bits`). EF, BitField and inventories are built with `toolkit_fork` exactly as `QuantizedSummary::from` does, and serialised as `mmap_io.rs` `write_mmap_index` does.
5. **Identity check (a built-in test):** rewriting a list with no change must reproduce its native bytes exactly, for every non-empty list of the shard. This checks the encoder against the build's writer on real lists (§8, T-A2b-ID).

### 4.3 Writes per epoch

**A2b (primary, one flip):** one rewrite per touched list, carrying both
removals and inserts, published by one flip. Forward records go only into
holes dead at E (D5).

**A2b-2p:** a FREE-epoch rewrite, then a FILL-epoch rewrite, with the
sub-variants of §3.3.

Each epoch:

1. Gate on the reader table. Copy the active `list_dir` bank into the inactive bank (R2).
2. pwrite the units at `bump`, `bump + …`. They are beyond the published bump pointer, so unreachable.
3. Sync `posting_heap.bin`.
4. Store the inactive-bank entry of each rewritten list (8-byte atomic). Sync `list_dir.bin`.
5. The FILL epoch also does the forward record, override and free-list steps of §3.2 (steps 3–4 and 7).
6. **Flip:** the header carries the new epoch AND the new bump pointer (field 56). Sync.

- A unit superseded at epoch f becomes unreachable once the oldest reader is ≥ f. It is **not freed** in this build: `posting_free.bin` stays empty, so the heap grows until compaction.
- B4 reports heap bytes consumed per batch and **batches-to-exhaustion** = remaining reserve / bytes per batch (R7).
- If the heap is exhausted, the batch fails at plan time. Nothing is written.

---

## 5. Recovery and side-file crash ordering (R1, R2, R5)

This runs at the start of **every** batch (`recover`), before the plan. Its
own writes are ordinary and complete before the batch's first write.

### 5.1 Posting words (R1)

- **Scope:** every native list (A2 copies). A2b copies never modify native words, and units beyond the published bump are ignored.
- **Aborted delete mark** (FREE=1, TAG > E): restore FREE=0, TAG=0. START/LEN were never touched. TAG=0 ≤ E keeps the slot visible, which is its state at E.
- **Aborted insert** (FREE=0, TAG > E): write FREE=1, TAG=E. The slot was dead at E, and TAG=E keeps it dead: (E≤E) XOR 1 = 0.
- Each fix is an 8-byte atomic store. Sync, then log the counts.
- Without this step the next batch, which also publishes E+1, would publish the aborted batch's writes (review R1).

### 5.2 Side files (R5)

- **`forward_free.bin`** is trusted iff its header epoch == E.
  - If `forward_free.bin.next` exists with epoch == E, the crash hit between the flip and the rename. Roll forward: rename, then fsync the directory.
  - A `.next` with epoch > E is from an aborted batch. Delete it.
  - If `forward_free.bin` has epoch > E (replaced before a flip that never completed: the "replace-then-flip" order, which the updater never uses but tests inject), or if no valid file has epoch E, **rebuild by scan** (§5.3).
- **`list_min.bin`:** every entry whose epoch field is > E is recomputed from the postings visible at E, by decoding the list's records.
- **Inflation and `list_dir`:** the inactive banks are overwritten from the active ones at the start of each epoch (R2), so aborted inactive-bank writes are never published.
- **row_id_override / forward_data / heap past bump:** the aborted batch wrote only into rows that are holes at E, and into heap bytes past the published bump. These are unreachable at E, and the next reuse overwrites them. `id → row` ignores hole rows (§1).

### 5.3 Free-list rebuild by scan

Postings are mapped to rows through `forward_offsets.bin` (START → row by
binary search, then check that `offsets[r+1] == START+LEN`).

- A row is a hole iff it has ≥ 1 posting and every posting of it is dead at E. Its freed epoch is the max TAG of those postings.
- This is exact except for one case: a hole whose dead slots have all been reused since it was freed has no posting left. The scan cannot see it, and it is **leaked** (safe: never double-allocated).
- The rebuild reports the leak as `rebuild_lost_holes` = |trusted − rebuilt| when a trusted copy exists to compare with (tests only).

### 5.4 Crash windows, write by write

| Crash after… | State at reopen (E) | Reader sees | Updater recovery |
|---|---|---|---|
| FREE marks, before sync | E = e; some words FREE=1/TAG=e+1 | old words, visible (row 3) | §5.1 restores FREE=0 |
| list_min/.next written | E = e | unaffected (updater-only) | entries > E recomputed; .next deleted |
| header slot partially written | E = e (torn slot fails its checksum) | epoch e | as above |
| flip done, before rename | E = e+1 | epoch e+1 | .next rolled forward |
| FILL records/overrides written | E = e+1 | unaffected (holes unreachable) | nothing to undo |
| FILL words written | E = e+1; words TAG=e+2, FREE=0 | invisible at e+1 | §5.1 sets FREE=1, TAG=e+1 |
| A2b units written | E = e; bump unchanged | old lists | nothing (bytes past bump) |
| A2b inactive dir entries | E = e | active bank only | overwritten from the active bank |

---

## 6. Reader table (R3)

File `reader_table.bin`, an updater/harness side file that is not in
FORMAT_V3 and that the v3 decoder does not read. It holds 4 KiB header plus
1,024 slots × 16 B `{u64 pid_and_flag, u64 epoch}`, mapped `MAP_SHARED`.

**Reader protocol** (Rust `ReaderGuard` in the crate; a Python helper with the
same protocol in the harness, for processes that call the real decoder; plan
06, Addendum third):
1. Claim a free slot with a CAS on `pid_and_flag` (0 → pid | 1<<63).
2. Read the header's published epoch E1 and store `epoch = E1` (SeqCst).
3. **Re-read** the header's published epoch E2 (SeqCst). If E2 ≠ E1, store
   E2 and repeat. The loop exits when a store is confirmed by the re-read.
4. Run the query. The decoder snapshots the header itself, after step 3, so
   its epoch is ≥ the registered one.
5. Clear the slot on exit. A long-lived reader may keep its slot and
   re-register per query.

**Updater:** after each flip, and before any reuse or inactive-bank write:
1. SeqCst fence after the header store.
2. Scan the table. oldest = the min epoch over occupied slots.
3. **Dead reader:** a slot whose pid fails `kill(pid, 0)` with ESRCH is
   cleared and counted (`stale_reader_slots`). This is pid liveness, not a
   lease. PID reuse by an unrelated process can only make the updater wait
   longer, never shorter.
4. If no slot is occupied, oldest = +∞.
5. The gate condition is polled every 5 ms up to `--reader-timeout` (default
   600 s). A timeout aborts the batch before its next write. After a flip,
   that is a clean publish with fewer inserts reported.

**Why the re-read closes the race:**
- If the reader's confirmed store happened before the updater's scan, the
  updater sees it.
- If it happened after, then the reader's re-read (SeqCst after its store)
  also came after the updater's header store (SeqCst before its scan). The
  reader then read the new epoch and registered at it.

This is the store-then-load pattern on both sides (Dekker). B7(c) includes a
slow reader AND readers started continuously during the flips.

**Deviation from the review's wording:** the review says "nothing freed at or
after the oldest published epoch is reused". This design reuses content
freed at f when f ≤ oldest, because at E = f that content is already
invisible (N1's table, row 4). The strict rule deadlocks the FILL epoch under
continuous traffic.

A fixed `--grace-seconds` (default 0) can be added on top of the table.
B7(c) runs a deliberately slow reader (§8, T-R3).

---

## 7. Invariants (`verify`, run after every test batch and every measured batch)

| Id | Invariant |
|---|---|
| I1 | Exactly one header slot has the max epoch E, and it is valid. The other slot is invalid or older. E ≤ 32,767 (R4: the updater refuses to publish past it). |
| I2 | Every posting word: START+LEN ≤ forward_data_words, and no TAG > E. |
| I3 | Every visible posting of list t resolves to a row r with `offsets[r] == START`, `offsets[r+1] == START+LEN`. Its record decodes (padded or not) and contains component t with weight > 0. |
| I4 | No row is both a hole (free list) and reached by a visible posting. |
| I5 | Within a list, no row is reached by two visible postings. |
| I6 | `list_min[t]` equals the recomputed minimum over visible slots (EMPTY iff none). Its epoch is ≤ E. |
| I7 | Inflation active bank: for every visible posting inserted by the updater, code_b ≥ the required code of its doc (§3.2 step 6). Codes are never lowered. |
| I8 | Free list: magic, checksum, epoch == E. Every entry lies in its size class and is a real row extent. No duplicates. Counts sum to the header total. |
| I9 | Every live ext id maps to exactly one live row. Every override row is live. |
| I10 | A2b: every active `list_dir` entry is native or a valid unit (magic, checksum, list id, bounds < heap_base + bump). The unit parses. I3/I5 hold on unit postings. Block offsets are monotone and end at the posting count. The summary decodes, and every block id is < n_summaries. |
| I11 | Model equivalence (tests only): the set of visible (list, ext id) pairs equals the naive model of §2 applied to the same batch. |

---

## 8. Tests (crate `cargo test`, synthetic v3 shards the crate builds itself)

The synthetic shard builder follows FORMAT_V3.md and the dv-v2 layout.
- Records: vectorium `DotVByteFixedU8Encoder` with per-doc scale.
- Lists: top-cap truncation.
- Blocks: fixed-size chunks.
- Summaries: the §4.2 encoder.
- Side files: exactly as `convert_dv_v2_to_inplace_v3` writes them (list_min, list_crc, list_dir, empty free lists, header slot 0 at epoch 0).

It does not depend on the encoder agent's converter.

| Test | What |
|---|---|
| T-open | The builder output passes I1–I10 at epoch 0. |
| T-A2-2p | Two-phase batch (both sub-variants) (deletes, updates, inserts, forced evictions and drops). Reopen, then I1–I11. Records decode through padding. |
| T-A2 | A2 (one flip) from epoch 0 absorbs 0 inserts. A second batch absorbs into the first batch's frees. |
| T-A2b | The same batch through A2b, then I1–I11. |
| T-A2b-ID | Rewriting an unchanged list reproduces its bytes. Also run read-only on the first 2,000 lists of a real shard, outside the lock, 2 cores. |
| T-R1 | Batch X aborted after its data writes and before the flip (fault injection at every write index class). Batch Y ≠ X then runs and publishes. Nothing of X is visible and I11 holds for Y alone. The same for A2b. |
| T-R2 | A2b rewrites list t at the FREE/FILL epochs. A following batch that does not touch t publishes. t still reads as rewritten. The same for inflation codes under A2. |
| T-R3 | A slow reader thread registers at e and keeps traversing. The updater publishes e+1 and must block before the FILL reuse until the reader leaves. Every traversal of the reader equals the epoch-e reference. |
| T-R5a | Order "flip then replace": crash after the flip, before the rename. Reopen rolls `.next` forward, and the free list is exact. |
| T-R5b | Order "replace then flip" (injected): the free list at e+1 is in place, then a crash before the flip. Reopen detects epoch > E and rebuilds by scan. No hole is double-allocated in a following batch, and `rebuild_lost_holes` is recorded. |
| T-R4 | Publishing epoch 32,768 is refused. |
| T-PL | Power-loss replay on a synthetic shard: record all writes, cut at 100 random points, keep only the writes durable before the cut, reopen, check (a)/(b). This is the same machinery B7 uses. |

---

## 9. Benchmark mapping (bars B2–B7, harness)

Bars are defined in plan 06 and are not restated here. The harness copies
them verbatim into its docstring before any run. Results go to
`data/eval_results/inplace_b_updater_<UTCDATE>.json`, keys `B2`…`B7`, arms
A2 and A2b side by side. The encoder agent writes B1 into
`inplace_b_<UTCDATE>.json`, and this file never touches it.

- **Write mechanism, named in every results file:**
  - `safety = "dead-at-epoch only, no undo record"`.
  - `arm = A2 | A2-2p/old-at-free | A2-2p/old-at-fill | A2b | A2b-2p/…`.
  - `reuse_gate = "reader table, f <= oldest"`.
  - `writer_io = "MAP_SHARED atomic 8-byte stores for reader-reachable words; pwrite for unreachable bytes; msync(MS_SYNC)+fsync"` (R6).
- **B2:** for A2 and A2b, the apply includes both epochs and the reader-table waits. Wall time with and without the waits. Bytes from `/proc/<pid>/io` `write_bytes` of the updater process.
- **B4 (A2b):** heap bytes per batch and batches-to-exhaustion (R7).
- **B5:** the flip is a 128-byte checksummed record (N2). It publishes the SEISMIC leg only (N3).
- **B7 SIGKILL arm:**
  - The updater runs with a pre-image log, and a uniform-random time in [0, T_apply] is drawn per trial. Reopen with the v3 decoder, then (a)/(b).
  - (c) comes from concurrent reader processes registered in the reader table, including a slow one (R3).
  - The copy is restored from the pre-image log and checked against the pristine hash before the next trial.
- **B7 power-loss arm:**
  - One recorded apply logs every write (file, offset, bytes), every fsync/msync (file), and every rename/create with its directory fsync.
  - For 100 random cut points, the crash image is the pristine copy plus exactly the writes made durable before the cut: a write to file f is durable iff an fsync of f completed after it and before the cut; a rename is durable iff a directory fsync followed it.
  - Reopen, (a)/(b), then restore.
  - A supplementary variant, never part of the verdict, also keeps each un-synced write with p = 0.5, to model early writeback.

---

## 10. Not handled (stated, not hidden)

- **Tail append:** records that fit no hole are unplaced, not served.
- **The hybrid spill** is not served (D6).
- **Heap reuse** of superseded A2b units: not built. `posting_free.bin` stays empty (R7).
- **Compaction and tag reset:** at 32,767 epochs the updater refuses to publish (R4).
- **Concurrency:** single writer only. There is no lock against a second updater beyond an `flock` on `inplace_header.bin`.
- **Platform:** Windows, 9p, SMB, and mixed mmap + `ReadFile` are unsupported (R6, `04` §D).
- **Summaries in A2 are never written.** A component absent from a block's summary is blind (N4), and only code 255 makes a zero-dot block visible.
- **R8 (A2b per-term parse cost)** is the decoder's. B3 for A2b needs a decoder that reads units, which does not exist at `2b5c7df` (it refuses them). Requested from the spec owner 2026-09-29.
- **Consistency across legs:** only the SEISMIC leg is updated. BM25F, meta and abstracts are not (N3).

## 11. R1–R9 cross-reference

| Review item | Handled by |
|---|---|
| R1 aborted batch published later | §5.1 recovery scan before every batch; T-R1 |
| R2 list_dir reverts | §3.1 step 2, §3.2 step 2, §4.3 step 1 (copy active → inactive); T-R2 |
| R3 fixed grace | §6 reader table; T-R3; B7(c) slow reader |
| R4 tag width | I1; publish refused past 32,767; T-R4 |
| R5 side-file ordering | §5.2 (write-before-flip, trusted iff epoch == E, roll-forward / rebuild); T-R5a/b |
| R6 writer I/O path | §9 `writer_io`; `MAP_SHARED` atomic stores |
| R7 heap exhaustion | §4.3 accounting; B4 batches-to-exhaustion; heap reuse not built |
| R8 A2b read cost | decoder-side; requested; B3-A2b blocked until then |
| R9 row reuse vs row-keyed serving state | §12 |

## 12. R9: is anything in serving keyed by shard row?

Checked in code 2026-09-29, read-only, at the working tree of that date.
Conclusion: **nothing in serving is keyed by shard row**, so row reuse stays
enabled for every arm.

- The Python binding converts a row to its external id inside Rust before
  Python sees a result: `spike/seismic_upstream/src/pylib/mmap_index.rs`
  `search` returns `(qid, score, doc_id string)` at :338 and :371–372, via
  `doc_id_string` at :589–595.
  - For the InplaceV3 path this checks `row_id_override.bin` first
    (`src/inplace_v3.rs` :639–647).
  - No Python API returns row ints; the only ints are sizes.
- `src/lib/thinclient/ordinals.py`: ordinals are meta.sqlite rows resolved
  from the W-id string (`lookup` :125–140). Not shard rows.
- `src/lib/thinclient/delta_layer.py` livedocs: `base_dead` (:112–121) and
  `shard_result_filter` (:136–161) resolve the SEISMIC result's W-id string
  to an ordinal. The masks are keyed on W-ids.
- Hotset sidecars (`hotset_*.json`): 4 KiB page extents of
  `forward_data.bin` (`sharded_seismic_backend.py` :926–933, :984–991). A
  reused row can make them stale for residency only, never for attribution.
  They are version-checked on `forward_reordered` and `forward_data_words`
  (:510–524).
- E5 reorder map: used only by the offline converter (`reorder_mmap_dir`,
  `mmap_io.rs` :2378–2400), which also rewrote the slab. Not read at
  serving.
- Caveat: only the v3 reader honours `row_id_override.bin`. A dv-v2
  (DotVByte) reader opening an updated copy would report the old W-id. It
  cannot do that, because it rejects `forward_format_version` 3 (spec §4).

---

## Revision 2026-09-29 (after `UPDATER_DESIGN_REVIEW_2026-09-29.md`, U1–U7, and plan 06 Addendum fourth)

Where this revision conflicts with §0–§12 above, the revision wins. It was
written before any updater code was committed.

**U1 — one reader table.** `reader_table.bin` is withdrawn. The crate's
`ReaderGuard`, the harness's Python helper and the updater all use the
spec's `readers.bin`: 256 slots × 64 B, created by the encoder. Slot layout:
`{u64 pid (0 = free), u64 epoch snapshot (u64::MAX = idle), u64 query-start
ns, u64 heartbeat ns, 32 B reserved}`. The reserved bytes are proposed for
U2, via the coordinator, as:
- `reserved[0..8]` = the reader's pid-namespace id, the inode of
  `/proc/self/ns/pid`;
- `reserved[8..16]` = lease length in ns (0 = the updater default).

A reader:
1. Claims a slot by CAS on pid (0 → pid).
2. Stores its E (SeqCst).
3. Re-reads the header, and re-stores until the two agree (Addendum third).
4. Stores u64::MAX when idle.
5. Refreshes the heartbeat at least every lease/4 while it holds a non-idle
   epoch, from a background thread (Rust `ReaderGuard`, Python helper).

**U2 — dead-reader detection valid across pid namespaces.** A slot is
treated as dead only if one of these holds:
- (a) its namespace id equals the updater's AND `kill(pid, 0)` returns
  ESRCH;
- (b) its heartbeat is older than its lease. The default lease is 600 s,
  above the 8–29 s queries measured on this host. Clocks are
  `CLOCK_MONOTONIC`, which is shared by containers on one kernel.

A slot with namespace id 0 (a reader that does not record one, e.g. an
older decoder build) is never cleared by pid. It is cleared only by the
lease, and only if its heartbeat is non-zero. A slot with heartbeat 0 and
namespace 0 is treated as live forever, and the updater waits up to
`--reader-timeout`, then aborts. This errs toward waiting, never toward
reusing under a reader.

**U3 — unplaced documents.** Every arm reports documents offered / placed /
unplaced and postings inserted / dropped / evicted. B6 is scored on the full
offered doc set. `+tail` is not built until the spec defines the region.

**U4 — writer I/O path: what runs.** This follows the revised spec (R6):
- ALL stores into files that readers map go through a `MAP_SHARED`
  read-write mapping:
  - posting words, list_dir, override entries and header words: aligned
    8-byte atomic stores;
  - inflation codes: 1-byte stores;
  - forward records written into holes, and A2b units in the heap: plain
    copies into the mapping (unreachable bytes, so atomicity is not needed).
- Then `msync(MS_SYNC)` of the dirty range, plus `fsync`.
- `pwrite`/`write()` is used only for files no reader maps:
  `forward_free.bin` (write-new + rename), the op log and the pre-image log.

This replaces §9's `writer_io` wording, and results files name exactly this.

**U5 — power-loss arm, two models, both in the verdict.**
- (i) Every un-synced write is lost.
- (ii) Each un-synced 4 KiB PAGE of each file is independently kept with
  p = 0.5 (seeded); a kept page holds its content as of the cut.

A write op is "synced" iff an msync/fsync of its file completed after it
and before the cut. New files and renames are durable iff a directory fsync
followed them before the cut. 100 cut points per model. This replaces §9's
"supplementary variant".

**R5 re-aligned with the revised spec.** `forward_free.bin` and
`list_min.bin` are written for e+1 BEFORE the flip and synced with the
data:
- `forward_free.bin`: write-new, fsync, rename, directory fsync.
- `list_min.bin`: in-place entries stamped with epoch e+1.

The updater trusts `forward_free.bin` only when its epoch == E, and
otherwise rebuilds it by scan (§5.3). The spec's rule adds that rows
carrying an override are excluded unless they are dead; R1's recovery
clears overrides of rows whose postings are all dead at E, and those rows
are then ordinary holes. The `.next` roll-forward of §3.1 step 7 / §5.2 is
withdrawn.

The two orders tested (T-R5a/b) now both land on "epoch ≠ E → rebuild":
- (a) replace, then crash before the flip: the file is stamped e+1 while
  E = e;
- (b) flip, then replace (injected order), then crash between: the file is
  stamped e−1 while E = e+1... or e while E = e+1.

In both, the tests check that no hole is double-allocated and that the
leak is bounded (`rebuild_lost_holes`).

**U6 — D6 deviation** is recorded in plan 06 Addendum fourth. No change
here.

**U7 — B2 bytes.** B2 reports two byte counts:
- device bytes, `/proc/<pid>/io` `write_bytes` (the bar's number);
- logical bytes, the sum of the lengths of all stores and writes the
  updater issued (the op log's total).

**Unit header field count (spec §3.6 says "23 × u64").** PostingListManifest
has **24** scalars; checked against the shard-0 manifest keys on 2026-09-29.
The unit header is laid out as:
- bytes 0..8: magic;
- 8..12: list;
- 12..16: epoch;
- 16..24: body bytes;
- 24..216: the 24 scalars;
- 216..248: zeros;
- 248..256: FNV-1a-64 over header[0..248] ‖ body.

Reported to the coordinator for the spec.

---

## Revision 2026-09-29 (as built, crate commits a12a4788 … 95b5a5ae and after)

These are the places where the code differs from §0–§12 or makes them
concrete. All were written before any real-shard run.

1. **Slot choice (A2, §2 step 6).** Dead slots are filled in ascending slot
   order by the new postings in descending weight order (ties by id), and
   evicting inserts take the evicted slots in ascending weight order. This is
   exactly what `spike/archive/inplace_update/sim.py` does for S0-2/S0-3, so A2's
   placement matches the Stage-0 simulation. The "smallest inflation code"
   choice of §2 step 6 is **not built**. It would cost one summary dot per
   candidate block per posting, and it would diverge from S0-3.
2. **Rows evicted from every list** become holes stamped with the batch's
   first epoch. They are not supply for the same batch: placement runs before
   the per-list plan.
3. **A2b heap check.** Every unit of an epoch is built in memory and
   size-checked BEFORE the first write of that epoch. On exhaustion the epoch
   writes nothing and the batch fails with "posting heap exhausted … (R7)". In
   A2b-2p this means the FREE epoch may have published already. B4 records the
   failing quarter instead of crashing.
4. **A2b unit words** carry TAG = 0, FREE = 0: the whole unit is reachable only
   at epochs ≥ the one that published it. New postings go to the block with the
   largest summary dot (ties to the lowest block). A list with no blocks that
   receives an insert gets one new block.
5. **Every changed A2b block** has its summary recomputed from the served
   (dv-v2 dequantised) values of its members. Unchanged blocks keep their raw
   (codes, min, quant) byte for byte. Rewriting an unchanged list reproduces
   the native bytes. This was checked on all synthetic lists (test
   `t_open_identity`) and read-only on the served shard 0: first 2,000 lists
   2,000/2,000 identical (CLI `identity-v2`, 2026-09-29, 2 cores), then all
   28,702 lists 28,702/28,702 identical (job `stage2/job_identity.sh`, binary
   `stage2/inplace-updater.identity`, 2026-09-29 21:51Z, console/scratch
   result `/home/vscode/work/inplace_update/stage2/identity_full.json`
   = `{"first_mismatches":[],"identical":28702,"lists_checked":28702}`; not
   a bar).
6. **Reader table** (`readers.bin`, spec revision 4 layout):
   - Heartbeat every lease/4 from a background thread. The default lease is
     600 s, and `check()` runs per list in the reference search.
   - Slot clearing is a gen-checked CAS.
   - Dead-reader rules: same pid namespace + ESRCH, lease expiry, or boot-id
     mismatch.
7. **Write guard** (owner requirement, `src/guard.rs`): see the module doc.
   Every write path passes through it.
8. **Record padding.** The dv record's SIMD values tail is `n_packs × 8` bytes
   (N = u8::BITS lanes). Zero words go right before it. Every padded record is
   decode-verified before any posting names it.

---

## Revision 2026-09-30 (+tail and heap reuse, as built; crate commit d456f4a3, harness 1d069329)

Written 2026-09-30 after the real-shard B4 of 2026-09-29/30 showed the two
gaps this revision closes: a fresh v3 copy placed 0 of 32,155 documents on
the first batch (forward records need holes), and A2b exhausted its 1×
heap reserve after 1.06 batches (R7). Both pieces are built against
`FORMAT_V3.md` §3.R4 and revision 6 (the encoder agent's as-built v3.1
spec) and tested on synthetic v3.1 shards the crate builds
(`tests/tail_heap.rs`, 13 tests; the 18 earlier tests unchanged in
behaviour; 31/31 pass, 2026-09-30). Efficacy numbers live in
`STAGE1_UPDATER_FINDINGS.md`; nothing here is a bar result. Where this
revision conflicts with §0–§12 or the earlier revisions, it wins.

### T1 `+tail` forward append (every arm; CLI arm suffix `-tail`, `--tail`)

- **Placement order is unchanged.** Records still take the best-fit hole
  first (smallest sufficient hole, lowest START; §2 step 3). A document
  that fits no hole becomes a *tail candidate* instead of unplaced. The
  per-list plan (§2 step 4, slot order = `sim.py`: ascending dead slots,
  descending weight) runs exactly as before on placed docs and tail
  candidates alike; capacity drops still apply. Only AFTER the per-list
  plan are tail candidates with ≥ 1 surviving posting given tail space, in
  batch order, so a document whose postings were all dropped for capacity
  consumes no tail words or rows (it is `docs_unplaced_no_posting`, as a
  hole-placed one would be).
- **Consequence for frozen A2 (one flip):** on a fresh copy no slot is dead
  at E, so every offered posting is dropped for capacity, no document keeps
  a posting, and `+tail` places nothing (test
  `t_tail_a2_fresh_copy_still_places_zero`). `+tail` removes the
  forward-record obstacle only; the posting-slot obstacle of the frozen
  arm remains. A2b+tail and the two-phase arms place every document with
  a surviving posting on the first batch.
- **Where a tail record goes:** START = `base_words` + tail words used
  (header field 64), LEN = the record's own length (no padding), row =
  `n_docs` + tail rows published (field 72) + j; the updater writes
  `forward_offsets.bin[row + 1] = START + LEN` (the file is now mapped
  writable, `store::F::Offs`, and its entries beyond the published rows are
  unreachable) and `row_id_override.bin[row] = 1<<63 | ext_id` (the
  extended array). Postings name the tail START with TAG = the flip's
  epoch (A2) or inside the unit of the inactive `list_dir` bank (A2b). Both
  counters are published only by the header flip: `write_header(epoch,
  bump, tail_words, tail_rows)`; the FREE flip of a two-phase batch
  republishes the old counters, the FILL flip the new ones.
- **Crash before the flip:** the unpublished tail bytes, offsets entries
  and overrides are unreachable (no visible posting names them; R1
  neutralises TAG > E words; the inactive `list_dir` bank is recopied) and
  the next batch writes from the published bump, overwriting them. Tested
  at 5 crash fractions + the op before and after the header sync for
  A2+tail and A2b+tail (`t_tail_r1_aborted_then_different_batch`) and by
  power-loss replay, 100 cuts × 2 models × 3 arms
  (`t_tail_power_loss_replay_and_restore`).
- **Reserve exhaustion:** checked at plan time, before the batch's first
  write: "forward tail exhausted: batch needs W tail words / R tail rows at
  (used, rows) > reserve (…); nothing of this batch was written". A v3.0
  directory (no `forward_tail` key, rev. 6 D4) has reserve 0, so a `+tail`
  arm on it is refused the moment a record needs the tail.
- **Verify additions:** I2 bounds every visible word by `base_words` +
  published tail words (and every word by the file); the tail CSR is
  checked (`offsets[n_docs] == base_words`, entries strictly increasing up
  to `offsets[n_docs + tail_rows] == base_words + tail_words`, 0 words iff
  0 rows); I9 requires an override on every visible tail row; header slots
  whose counters exceed the reserves are invalid (rev. 6 D3) and
  `write_header` refuses them.
- **Restore and power-loss replay:** every tail write goes through the op
  log (`F::Fwd`, `F::Offs`, `F::Ovr`, `F::Hdr`), so `plsim::restore` and
  the crash images cover the extended files; `t_tail_power_loss_replay_and_restore`
  checks that a restore after a full apply reproduces every file of the
  pristine copy byte for byte.
- **Synthetic v3.1 shards:** `synth::SynthParams { tail_words, tail_rows }`
  (CLI `synth --tail-words W --tail-rows R`) extends the three files with
  `set_len` and writes `inplace_v3.forward_tail = {base_words,
  reserve_words, reserve_rows, offsets_entries_on_disk,
  override_entries_on_disk, tail_words_used_field: 64,
  tail_rows_published_field: 72}` and `inplace_v3.minor = 1` (rev. 6). The
  key is written with zero reserves for a v3.0-layout synthetic shard.

### T2 A2b heap reuse (R7; `posting_free.bin`; `--heap-reuse 0` = the old bump-only behaviour)

- **What is freed, when:** a unit named by the `from` bank of a phase that
  rewrites the same list is superseded by that phase's flip; it becomes an
  entry `{unified byte offset, length, epoch freed = the flip's epoch}`.
  Nothing in `posting_lists.bin` is ever freed (native lists are not heap
  space).
- **Reuse gate = the reader-table gate.** An entry is reusable in a phase
  iff its epoch ≤ the epoch that phase's gate established
  (`oldest live reader ≥ e_pub`, §6/U1–U2). So a unit superseded by the
  flip to e is reusable from the phase that publishes e+2 on (the phase
  publishing e+1 waits for readers ≥ e only). Steady state therefore needs
  heap space for the live units PLUS the last batch's superseded units:
  with the encoder's 1× reserve and a batch that rewrites ~94 % of the
  lists (real Q1: 1.09 GB of 1.16 GB), the SECOND batch is still refused
  (it cannot reuse yet) and reuse only pays from the third batch on if the
  first two fit. A ≥ 2× reserve is needed for steady-state reuse on such
  batches (format question, reported).
- **Allocator (the simplest sound one):** reusable entries are coalesced
  when adjacent (the merged entry keeps the max epoch), then each unit
  takes the BEST FIT (smallest sufficient entry, lowest offset on ties);
  the remainder returns to the list with the entry's epoch; a unit that
  fits no entry is bump-allocated past the published bump pointer.
  Allocation is done in memory for every unit of the epoch before the
  first write, so exhaustion still refuses the epoch with nothing written
  ("posting heap exhausted: … with N B reusable and bump B of reserve R").
  Best fit was chosen over size classes because units of one list keep a
  similar size across rewrites, so the just-freed unit of the same size is
  the natural fit; no fragmentation study was done (the synthetic 14-batch
  run shows the free space growing 4.9 → 5.7 MB while the units shrink with
  the doc set, see the findings).
- **Side file, R5:** `posting_free.bin` is rewritten (write-new + rename +
  directory fsync) for e+1 BEFORE every flip, of every arm (A2 arms
  re-stamp the unchanged entries), stamped e+1 in its header; recovery
  trusts it iff its epoch == E, else rebuilds it by scan: `[heap_base,
  heap_base + bump)` minus the extents of the units the active bank names,
  gaps coalesced, every gap stamped E (the most conservative freed epoch).
  The rebuild leaks nothing it can see but forgets the finer epochs (a
  rebuilt list is reusable only once every reader is at E). Tested:
  crash after the `.next` write (old file trusted), after the rename and
  after the directory fsync (rebuilt), then two more batches with reuse
  (`t_heap_free_rebuild_after_crash`); trusted list == scan after 14
  batches (`t_heap_reuse_extends_life`).
- **Verify I12:** the list parses, epoch == E, entries 8-aligned inside
  `[heap_base, heap_base + bump)`, no two entries overlap, no entry epoch
  > E, and no unit named by the active bank overlaps an entry.
- **Layout decision (format question):** the 64-byte header of §3.6 has no
  epoch field; the updater puts `u64 epoch` at offset 16 and `u64
  n_entries` at offset 24 (the encoder's all-zero header reads as epoch 0,
  no entries), entry = `{u64 offset in the UNIFIED posting address space
  (same origin as list_dir), u64 length:48 | epoch freed:15}`.
- **Decoder consequence (format question, reported to the encoder agent):**
  with reuse, `(list, unit offset)` is no longer unique over time: list t
  can be served again from an offset it used before. A view cache keyed by
  `(list, offset)` (§3.R3 decoder rules) must validate the unit header's
  `epoch written` (offset 12) on every hit, or key by `(list, offset, epoch
  written)`. The crate's own reference reader parses the unit on every
  view and is unaffected.

### T3 Recovery and liveness corrections found by the new tests

- **Override clearing is gated on the reader table.** §5.2 / R1 cleared
  the override of every row without a visible posting at E at the start of
  a batch. A reader registered at an epoch < E may still resolve such a
  row (it died at E), so the clearing now happens only when every live
  reader holds an epoch ≥ E (`recover(sh, Some(&table))`); otherwise it is
  deferred and counted (`overrides_clear_deferred`). Before this fix the
  effect on a base row was a silently wrong id (the slab id instead of the
  override); on a tail row it was `u64::MAX`, which is how
  `t_heap_reuse_slow_reader_blocks` found it. Verify counts overrides on
  dead rows as information (`overrides_on_dead_rows`), not a violation:
  no reader at E can observe them, a reader-gated recovery clears them and
  a reuse overwrites them.
- **Live id = a row with a visible posting at E**, or a base row that
  never had a posting (every component truncated by the list cap) and is
  not a hole (its id stays addressable so a delete or update can free its
  row). Rows whose postings are all dead — holes, leaked holes, tail rows
  whose doc is gone — carry no live id. Previously "not in the free list"
  stood in for liveness; that mapped leaked holes and (with tail rows) rows
  without any id.

### T4 Not handled (stated)

- Tail compaction: a deleted tail row is a hole like any other (its record
  extent is reusable through `forward_free.bin`, tested in `t_tail_a2`
  batch 3); tail words are never given back to the bump pointer.
- Heap fragmentation is not compacted; a unit larger than every free entry
  bumps. No size-class or buddy scheme.
- The reuse of a hole or a unit within the same batch that freed it is
  still not representable (D1).
- The decoder-side cache validation of T2 is not the updater's to build.
