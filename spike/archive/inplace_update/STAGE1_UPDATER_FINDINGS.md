# Stage 1: bit updater and benchmark harness, findings

> **CLOSED MEASURED 2026-09-30** — the pre-registered GO rule of `06_INPLACE_SPIKE_PLAN.md` read NO-GO: bar S0-1 measured a long-list dead-slot coverage of **0.019** (95 % CI 0.018–0.020) against 0.80. In one quarter 27 % of shard 0's docs are updated and 15 % more are new while deletions free 6 %, and a list cannot grow, so dead-slot reuse cannot absorb the churn (`inplace_s0_20260930.json`). Nothing in-place replaces it: updates stay with delta generations (`docs/delta_ingest/`). The v3 encoder/decoder is exact (B1 460/460, +1.3 % per query) and the +tail variant was built, but they remove the wrong obstacle. Full record: `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` results table and §"NO-GO 2026-09-30". Not current; do not resume.

**Status:** CLOSED MEASURED 2026-09-30

**State as of 2026-09-30, 05:30Z: `+tail` (FORMAT_V3 §3.R4 / rev. 6) and
A2b heap reuse (R7) are BUILT (crate `d456f4a3`, harness `1d069329`, design
`70fe49f4`), tested (31/31 crate tests) and measured on SYNTHETIC shards plus
one INDICATIVE run on the v3.1 copy of shard 0 — see §"+tail and heap reuse
(2026-09-30)" below; their bar-quality B2/B4/B7 runs are the coordinator's to
queue. B4 (RECORDED) ran on the real shard-0 v3 copy on 2026-09-29/30; B2,
B5 and B7 for the base arms are running in the queue (`stage2/real_run2.sh`);
B3 and B6 NOT RUN (decoder pieces missing / held by owner).** Earlier state
line, kept for the record (2026-09-30, 00:30Z): B4 has run on the real
shard-0 v3 copy; B2, B5 and B7 queued. Earlier still, kept for
the record: 2026-09-29, 21:30Z: code built and tested; NO BAR RESULT
EXISTED. Every number below is either a crate test outcome or a SYNTHETIC-shard
run. Synthetic runs are labelled as such and are not bar results. B2–B7 on the
real shard 0 have **NOT RUN**, because the encoder agent's v3 copy of shard 0
(`/home/vscode/work/inplace_update/stage1/v3`) does not exist yet: its job is
queued behind the latency lock. A queued job (`stage2/real_run.sh`) waits for
that copy and then runs B2, B5, B4 and B7 under the lock. This note is updated
if it completes.

This work was started ahead of the GO gate of
`docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` at the owner's request. GO may
still read NO-GO.

## What exists

| Item | Path | Commits |
|---|---|---|
| Design, DESIGN only (R1–R9, U1–U7, as-built revision) | `spike/archive/inplace_update/UPDATER_DESIGN.md` | `586e04ab`, `af930c45`, `947724e9` |
| Updater crate (lib + CLI `inplace-updater`) | `spike/archive/inplace_update/updater/` | `a12a4788`, `95b5a5ae` (write guard), `03fd6cee`, `9993c0a5`; `d456f4a3` (+tail, heap reuse, 2026-09-30) |
| Crate tests (18 + 13, synthetic v3 / v3.1 shards built by the crate) | `spike/archive/inplace_update/updater/tests/updater.rs`, `tests/tail_heap.rs` | same |
| Benchmark harness B2–B7, committed before any measured run | `scripts/archive/inplace_update/eval_inplace_bench.py` | `1afce433`, `df464826`, then `57a6e746`/`852d2614` (bug fixes, before any real run); `1d069329` (+tail arms, R7 fields, env overrides, 2026-09-30) |
| SYNTHETIC results (labelled) | `data/eval_results/inplace_b_updater_synthetic_20260929.json`; `inplace_b_updater_synthetic_20260930.json` + `inplace_b_updater_synthetic_r7off_20260930.json` (+tail, heap reuse) | `3af751bc`; 2026-09-30 |
| INDICATIVE run on the v3.1 copy of shard 0 (not a bar) | `data/eval_results/inplace_b_updater_indicative_v31_20260930.json` | 2026-09-30 |

Build: nightly (vectorium needs it), `-C target-cpu=x86-64-v3`,
`CARGO_TARGET_DIR=/home/vscode/work/inplace_update/stage2/target`, 2 cores. All
18 tests pass (last run 2026-09-29 ~21:15Z, commit `9993c0a5` + rebuild):
- the arms A2, A2-2p (both sub-variants), A2b one-flip, A2b-2p (both);
- R1 aborted batch then a different batch (4 crash points × 3 arms);
- R2 for list_dir and for the inflation banks;
- R3 slow reader blocks reuse, and a lease reclaim with heartbeats off (the
  reader's query fails) versus on (not reclaimed, the updater waits);
- R4 epoch bound;
- R5 in both side-file orders;
- power-loss replay (100 cuts × 2 models × 2 arms, exact-search check +
  verify after recovery);
- write guard: protected roots, symlink, hard link, missing and foreign
  sentinel, 9p detection;
- the encode-identity of every synthetic list.

**Real-shard structural check (read-only, not a bar):** rewriting each of the
first 2,000 posting lists of the served shard-0 dv-v2 file with the crate's A2b
encoder (`identity-v2`) reproduced 2,000/2,000 lists byte for byte, manifest
scalars included (2026-09-29, 2 cores). The full check then ran under the
lock (job `stage2/job_identity.sh`, binary `stage2/inplace-updater.identity`,
2026-09-29 21:51Z): **28,702/28,702 lists identical**, result file
`/home/vscode/work/inplace_update/stage2/identity_full.json` =
`{"first_mismatches":[],"identical":28702,"lists_checked":28702}`. Both are
console/scratch results (no results file under `data/eval_results/`), cited
as a check, not a measurement.

## Decisions recorded (and where they bind)

- **Safety rule:** dead-at-epoch only, no undo record (UPDATER_DESIGN D1). Every
  apply report names it. Cost, stated for arm A2 as frozen (one flip): from a
  fresh v3 copy the first batch absorbs **zero** inserts. Holes and dead slots
  exist only after a batch has freed them. SYNTHETIC B2: A2 placed 0 of 2,500
  offered docs, and all 32,796 offered postings were dropped as unplaced. In
  SYNTHETIC B4, each later quarter placed every offered doc (2,375 / 2,256 /
  2,142), using the previous quarter's frees.
- **A2b one flip also places zero on the first batch.** Posting space comes from
  the heap tail, but forward records still need holes and FORMAT_V3 has no
  built tail append. The coordinator accepted this (plan 06 Addendum fourth,
  `+tail` variant: DESIGN, not built).
- **A2-2p (supplementary)** absorbs the first batch. `old-at-free` placed
  2,500/2,500 SYNTHETIC docs, with a gap between flips of 0.05 s (A2) / 0.51 s
  (A2b-2p) on the synthetic shard. `old-at-fill` has no gap but placed only
  1,000/2,500, because updated docs' old rows become supply only for the next
  batch.
- **Slot order = `sim.py`:** dead slots are filled in ascending slot order by
  new postings in descending weight order, so A2's placement is the one S0-2 and
  S0-3 simulated.
- **Hybrid rule not applied** (every list in place; plan 06 Addendum fourth
  records the deviation). Drops are reported by list-length decile.
- **Reuse gate:** `readers.bin`, reuse iff freed epoch ≤ oldest live reader
  epoch. Registration re-reads the header. Dead readers are cleared by lease
  (600 s default), same-namespace pid liveness, or boot id.
- **Writer I/O:** MAP_SHARED atomic stores + msync/fdatasync. write()+rename only
  for `forward_free.bin`.

## SYNTHETIC results (not bar results)

File: `data/eval_results/inplace_b_updater_synthetic_20260929.json`.
- Shard: 20,000 docs, dim 2,000, list cap 200, block 8, heap reserve 6 × the
  posting file.
- Batches: 1,000 deletes + 2,000 updates + 500 inserts, then 3 more synthetic
  quarters.
- Host: shared, 2 cores, not under the latency lock. Wall times are indicative
  only.
- Binaries: B2/B4/B7 were built from `03fd6cee`; B5 from `95b5a5ae` (identical
  apply logic for A2; A2b units were then built inline).
- Protected-tree baseline check at start and end of every subcommand: 0
  differences.

**B7 (crash safety):** 100/100 on each of SIGKILL, power-loss "drop", and
power-loss 4 KiB "pages" for A2, A2b, A2-2p/old-at-free, A2-2p/old-at-fill and
A2b-2p/old-at-free. The checker is the crate's exact reference search, not the
v3 decoder:
- (a) epoch;
- (b) bit-identical top-200 versus clean references per epoch;
- (c) a slow and a fast registered reader, 53,816–162,664 reader queries per
  arm, all equal to the reference at their registered epoch;
- power-loss trials also passed recovery + verify.

**B2 (apply cost, median of 3):**

| Arm | Wall (s) | Device bytes | Logical bytes | Placed / offered |
|---|---|---|---|---|
| A2 | 0.045 | 6,238,208 | 321,328 | 0 / 2,500 |
| A2-2p/old-at-free | 0.122 | 13,582,336 | 699,729 | 2,500 / 2,500 |
| A2-2p/old-at-fill | 0.135 | 12,898,304 | 496,346 | 1,000 / 2,500 |
| A2b | 0.429 | 10,149,888 | 4,989,512 | 0 / 2,500 |
| A2b-2p/old-at-free | 0.939 | 22,298,624 | 10,475,072 | 2,500 / 2,500 |
| A2b-2p/old-at-fill | 0.817 | 22,425,600 | 10,535,720 | 1,000 / 2,500 |

There is no A1 on the synthetic shard. Device bytes are 10–40× the logical
bytes: dirtied 4 KiB pages versus 8-byte stores (U7).

**B4 (storage, R7):**
- A2 and A2-2p grow by < 1 % allocated after four quarters: holes reused, no
  new files.
- A2b consumed 4.93 MB of heap per quarter, which is ≈ 1 × the synthetic
  posting file per batch. At the spec's real-shard reserve (1 × the posting
  file) that is **≈ 1 batch to exhaustion** (*est.* by proportion, not
  measured on the real shard).
- A2b-2p rewrites each list twice per batch (≈ 10.2 MB/quarter). It exhausted
  the 6× synthetic reserve at quarter 3, and the epoch was refused before any
  write.

**B5 (publish):**
- Header write start to first header poll that sees the new epoch: 0.07–2.3 ms
  (A2), 0.23–0.90 ms (A2b), over 5 reps. The reader is a header poll, not the
  decoder.
- Residency kept: 1.000 in every rep for A2 and A2-2p.
- A2b: rep 0 kept 0.5367 (then 1.000 × 4). The rep-0 drop is **unexplained**;
  by the pre-registered rule it reads FAIL on this synthetic run.


## Real shard 0: B4 (storage, RECORDED) — `data/eval_results/inplace_b_updater_20260929.json` key `B4`

Run 2026-09-29 23:54–00:09Z under the latency lock, harness at `ef48050d`,
on a copy (`stage2/work_*`) of the encoder's v3 copy of shard 0
(`stage1/v3`, prep-copy 23:25Z). Protected-tree baseline check at start and
end: 0 differences. Doc set: the Stage-0 ENCODED SUBSAMPLE (32,155 upserts:
8,465 updates + 23,690 new) + 1,131,292 deletions — **not the full quarter**.

**What "synthetic_reuse: true" means for quarters 2–4.** Q2–Q4 are NOT
real later quarters: each deletes 1,139,757 base ids sampled uniformly from
the still-live ids (seed `inplace-q<k>`, count = Q1 deletions + Q1
updates) and INSERTS the same 32,155 Q1 vectors again under fresh ids
(10^12·k + j); they contain no updates. They can be read only as "how much
of a fixed demand the mechanism absorbs once freed space exists, and how the
files grow"; they say nothing about the demand, overlap or quality of a real
quarter, and the demand is repeated vectors, not new text.

| Arm | Batch | Docs offered / placed / unplaced (no hole / no surviving posting) | Postings offered / inserted / dropped capacity / dropped unplaced / evicted | Wall (s) | Device bytes | Logical bytes |
|---|---|---|---|---|---|---|
| A2 (frozen, one flip) | Q1 | 32,155 / **0** / 32,155 / 0 | 2,999,413 / **0** / 0 / 2,999,413 / 0 | 20.1 | 672,399,360 | 34,793,104 |
| A2 | Q2 (reuse) | 32,155 / 29,334 / 0 / 2,821 | 2,999,413 / 916,338 / 2,083,075 / 0 / 0 | 20.7 | 649,138,176 | 51,637,909 |
| A2 | Q3 / Q4 (reuse) | 29,971 / 29,913 placed | 913,012 / 903,033 inserted | 14.5 / 14.2 | 681,709,568 / 693,923,840 | 60,780,960 / 69,519,623 |
| A2-2p/old-at-free | Q1 | 32,155 / 29,651 / 0 / 2,504 | 2,999,413 / 929,614 / 2,069,799 / 0 / 13,276 | 26.9 | 2,529,525,760 | 58,497,186 |
| A2-2p/old-at-free | Q2–Q4 (reuse) | 30,565 / 30,403 / 30,324 placed | 976,384 / 961,087 / 951,440 inserted; evicted 52,550 / 48,551 / 44,517 | 31.4 / 35.3 / 37.6 | 2.03 / 1.80 / 1.78 GB | 71.3 / 88.8 / 106.4 MB |
| A2b (one flip) | Q1 | 32,155 / **0** / 32,155 / 0 | 2,999,413 / 0 / 0 / 2,999,413 / 0 | 230.2 | 1,100,206,080 | 1,098,170,392 |
| A2b | Q2 | — | **FAILED: "posting heap exhausted: epoch 2 needs 1,073,778,640 B at bump 1,088,655,296 > reserve 1,159,213,056 (R7); nothing of this epoch was written"** | | | |

Storage (st_size / allocated of every file of the arm's dir): before
6,860,241,413 / 5,544,255,488 B. A2 after Q1–Q4: 6,895,986,925 /
5,599,121,408 (+0.99 % allocated, from forward_free.bin and row overrides).
A2-2p after Q1–Q4: 6,895,829,053 / 5,599,653,888. A2b after Q1: allocated
6,643,900,416 (+1.10 GB, the heap units). A2b heap: 1,088,655,296 B for one
batch of the reserve's 1,159,213,056 → batches-to-exhaustion from empty
**1.06** (R7 measured on the real shard: one batch that deletes ~6 % of
the shard touches 24,771 of 26,613 non-empty lists, and the list is the
write unit).

**Findings stated plainly.**
- Frozen A2, batch 1: 0 of 32,155 documents placed, all 2,999,413 offered
  postings dropped as unplaced (no hole exists before a batch frees one).
  A2b one flip: the same 0 (forward records need holes).
- Once freed space exists (A2 Q2–Q4, A2-2p): ~29–30.5 k of 32,155 docs
  placed, but only 0.90–0.98 M of 3.00 M postings inserted — **≈ 68–70 %
  dropped for capacity.** Split:
  - A2 (one flip) never evicts: every capacity drop is "no dead slot left in
    that list at the published epoch" (2,083,075 in Q2).
  - A2-2p evicts; its drops (2,069,799 in Q1) are all postings for which the
    list had no dead slot AND the new weight was ≤ the weight of the
    survivor it would replace (eviction refused on weight); only 13,276
    postings won an eviction in Q1.
  - By list-length decile (decile = list length × 10 / (5,250 + 1), decile 9
    = lists of ≥ 4,725 slots, i.e. at or near the cap), A2 Q2 dropped
    [421,936, 111,087, 81,978, 65,531, 52,944, 39,082, 29,557, 50,335,
    30,975, **1,199,650**] and inserted [63,421, 61,830, 64,161, 52,617,
    46,794, 48,472, 41,426, 37,514, 37,296, 462,807]: 58 % of the drops are
    in capped lists (demand far above the dead slots a ~6 % deletion rate
    frees there, and new weights below the capped list's minimum), 20 % in
    the shortest decile (lists of < 525 slots with almost no dead slots).
  - 2,184–2,821 placed docs had no surviving posting at all and were
    unplaced again (counted `docs_unplaced_no_posting`).
- `blind_components` ≈ 1.0e8 per batch: counted per (inserted posting, doc
  component) pair whose component is absent from the target block's summary
  — i.e. ≈ 110 of a doc's components per inserted posting are invisible to
  that block's α-pruned summary and cannot be covered by the inflation byte
  (the known SEISMIC scope limit, N4 / S0-3 `blind_mass`). 198,845 blocks had
  their inflation code raised in A2 Q2; none saturated.
- A2-2p device bytes 2.53 GB vs A2's 0.67 GB for similar logical bytes
  (58 MB vs 35 MB): A2-2p issues two synced epochs per batch; the FILL
  epoch's stores (930 k posting words, 29.7 k records scattered over the
  3.85 GB forward file, list_min) land largely on 4 KiB pages the FREE
  epoch already dirtied and synced, so pages are written back twice, and the
  FILL records touch pages A2 Q1 never touches (A2 Q1 writes only delete
  marks). This attribution is INFERRED from the write pattern, not
  separately measured (write_bytes counts dirtied pages; U7).
- A2b 230 s vs A2 20 s: A2b rewrites 24,771 whole lists (1.09 GB of units:
  decode of the summary, the removal, the exact summary rebuild of every
  changed block — which decodes every member record of that block — EF/
  bitfield re-encode, and 1.09 GB of copies into the heap), single-threaded
  in the current crate; A2 issues 3.18 M 8-byte stores. The split between
  rebuild CPU and write time was not instrumented (the apply report does not
  separate them); `phases[0].write_s` = 226 s covers both.

## Bars on the real shard

| Bar | A2 | A2b | Why not |
|---|---|---|---|
| B2 | QUEUED | QUEUED | first attempt 2026-09-29 23:54Z aborted at start by the baseline guard: 721 files unreadable (stat failures on the 9p mount; the coordinator re-checked at 00:15Z: nothing changed). Guard now separates MISSING (5 retries over ~2 min) from CHANGED (abort at once), `1da6c0e5`; re-queued |
| B3 | NOT RUN | NOT RUN | NOT RUN — held by owner 2026-09-30 pending host-level protection of data/seismic_150m; also needs the v3 decoder behind `search_rrf` (A2) and the A2b unit read path (assigned to the encoder agent after B1) |
| B4 | RECORDED (above) | RECORDED (above; heap exhausted at Q2) | — |
| B5 | QUEUED | QUEUED | same 23:54Z abort (406 unreadable files); re-queued; the timing reader is a header poll, not the decoder |
| B6 | NOT RUN | NOT RUN | NOT RUN — held by owner 2026-09-30 pending host-level protection of data/seismic_150m; also needs decoder + A3 build; A3 is wired in the harness (`--with-a3`), never run |
| B7 | QUEUED | QUEUED | also queued: A2-2p/old-at-free, A2-2p/old-at-fill; SIGKILL + power-loss drop + power-loss pages, 100 each; checker = exact reference search (`--decoder` refuses until a decoder check is wired) |

**Doc set the real runs will use** (`stage2/docs/docset.json`):
- The Stage-0 ENCODED SUBSAMPLE of 7 part files: 32,155 upserts, of which 8,465
  are in-base updates and 23,690 are new.
- Plus 1,131,292 deletions (the full deleted_ids window, which starts
  2026-08-14).
- **Not the full quarter.** Any real-shard number is on this doc set and must
  say so.

## +tail and heap reuse (2026-09-30)

Built by the updater agent on 2026-09-30 after the real-shard B4 above
exposed the two gaps (0 of 32,155 placed on a fresh copy; A2b heap exhausted
after 1.06 batches). Code: crate `d456f4a3` (design in `UPDATER_DESIGN.md`
"Revision 2026-09-30"), harness `1d069329`. Format: `FORMAT_V3.md` §3.R4 and
revision 6 (the encoder agent's v3.1 as-built spec). Everything in this
section is either a crate test outcome, a SYNTHETIC run, or the INDICATIVE
run on the v3.1 copy of shard 0; **no bar-quality number exists yet** —
B2/B4/B7 for the `+tail` arms are the coordinator's to queue under the lock.
Status of each piece: IMPLEMENTED; efficacy measured only as stated below.

### What was built (one screen)

- **`+tail`** (any arm, CLI suffix `-tail`; harness arms `<arm>+tail`): a
  record that fits no hole is appended at the published tail bump (header
  field 64), takes row `n_docs + tail rows published` (field 72), gets its
  `forward_offsets.bin[row+1]` and `row_id_override.bin[row]` entries, and
  its postings name the tail START (A2: TAG = e+1; A2b: inside the unit).
  Both counters are published only by the flip; the reserve is checked at
  plan time and an exhausted reserve refuses the batch before any write.
  Placement order is as built (holes best-fit first; per-list plan
  unchanged); tail space is assigned only to documents that keep at least
  one posting after the per-list plan.
- **Heap reuse (R7)**: units superseded by a flip become `posting_free.bin`
  entries stamped with that epoch; a phase may reuse an entry iff its epoch
  ≤ the epoch its reader gate established (oldest live reader ≥ e_pub), so a
  unit superseded by the flip to e is reusable from the batch that publishes
  e+2 on. Best fit after coalescing, remainder returned, bump otherwise; the
  side file is rewritten before every flip and rebuilt by scan when its
  epoch ≠ E. `--heap-reuse 0` restores bump-only.
- **Two corrections the new tests forced** (UPDATER_DESIGN revision
  2026-09-30 T3): recovery now clears the overrides of dead rows only when
  the reader table shows every live reader at ≥ E (a reader at e−1 could
  still resolve a row that died at e; on a tail row the symptom was
  `u64::MAX`, on a base row it was silently the slab id), and a row's id is
  live iff the row has a visible posting (or never had one and is not a
  hole).

### Crate tests (2026-09-30, `tests/tail_heap.rs`, 13 new; 31/31 pass with the 18 earlier ones)

`t_tail_open_identity`, `t_tail_a2` (delete batch first, then three
batches: tail, hole reuse, tail-row hole reuse; exact reference search vs an
independent scorer over the model vectors at every epoch),
`t_tail_a2_fresh_copy_still_places_zero`, `t_tail_a2b`, `t_tail_two_phase`
(old-at-free and old-at-fill), `t_tail_reserve_exhaustion_refused` (no op
written, file hashes unchanged, A2 semantics without `+tail` unchanged),
`t_tail_r1_aborted_then_different_batch` (5 crash fractions + the op before
and after the header sync, A2+tail and A2b+tail),
`t_tail_power_loss_replay_and_restore` (100 cuts × drop/pages × A2+tail,
A2b+tail, A2-2p+tail; restore reproduces every pristine file byte for
byte), `t_tail_verify_catches_bad_counters`, `t_heap_reuse_extends_life`
(3× heap: bump-only refuses batch 4, reuse runs 30 batches, trusted free
list == scan), `t_heap_reuse_two_phase_and_tail`,
`t_heap_free_rebuild_after_crash` (crash after the `.next` write: trusted;
after the rename / directory fsync: rebuilt), `t_heap_reuse_slow_reader_blocks`
(a registered reader at epoch 2 traverses units while batches 3–4 reuse and
free; every reader result equals the epoch-2 reference; batch 4 waits and
defers the override clearing).

### SYNTHETIC results (not bar results)

Files: `data/eval_results/inplace_b_updater_synthetic_20260930.json` (B4, B2,
B7) and `inplace_b_updater_synthetic_r7off_20260930.json` (B4 with
`--no-heap-reuse`). Shard: 20,000 docs, dim 2,000, cap 200, block 8, seed 0,
heap reserve **3×** the posting file = 14,938,112 B, tail reserve 60,000
words / 4,000 rows (`synth-prep --tail-words 60000 --tail-rows 4000
--heap-factor 3 --batches 14`). Batches q1..q14 as the harness generates them
(5 % deletes, 10 % updates, 2.5 % inserts of the live set: q1 = 1,000 / 2,000
/ 500, so 2,500 documents offered; later batches shrink with the live set).
Run 2026-09-30 04:10–04:24Z on cores 8–15 (`taskset`), no latency lock,
host shared with the queue's real-shard B2/B7 on cores 0–7: wall times are
indicative only. Protected-tree baseline check at start and end of every
subcommand: 0 differences. Verify is not run by the harness; the same
mechanism under `cargo test` verifies after every batch.

**R7 heap reuse, B4-style batches to exhaustion (A2b, one flip):**

| | Reuse OFF (`--no-heap-reuse`) | Reuse ON (default) |
|---|---|---|
| Batches accepted (cap 14) | **3**; q4 refused: "posting heap exhausted: epoch 4 needs 252,560 B (unit of list 61: 4,104 B) with 0 B reusable and bump 14,689,632 of reserve 14,938,112 (R7); nothing of this epoch was written" | **14 / 14** |
| Bump growth per batch (B) | 4,932,808 / 4,901,056 / 4,855,768 | 4,932,808 / 4,901,056 / then **0** for q3..q14 (bump frozen at 9,833,864 = 65.8 % of the reserve) |
| Bytes reused per batch (B) | 0 | 0 / 0 / 4,855,768 / 4,794,000 / … / 4,181,760 (q3..q14; every batch reuses the space its predecessor's flip freed, minus the shrinking unit sizes) |
| Bytes superseded per batch (B) | 0 / 4,932,808 / 4,901,056 | 0 / 4,932,808 / 4,901,056 / … / 4,240,328 |
| Free bytes after the last accepted batch | 9,833,864 (never reusable) | 5,652,104 (fragmentation: the units shrink with the doc set, the remainders accumulate) |
| Allocated bytes of the dir after the last accepted batch | 22,818,816 (q3) | 17,989,632 (q14) |
| Batches to exhaustion from empty | 3.05 (harness estimate reserve / mean bump) | not reached in 14; bump growth is 0 after batch 2, so the linear estimate (21.3) is not meaningful — steady state needs the live units plus one batch of superseded units, here 2 batches' worth = 0.66 × the 3× reserve |

Placement and posting counts are identical between the two runs for every
accepted batch (e.g. q2: 2,375 placed, 29,497 inserted, 2,091 dropped, 15
evicted; q3: 2,256 / 27,647 / 2,778 / 669): reuse changes where units are
written, not what they contain.

**`+tail`, B4-style (14 batches, docs placed via hole / via tail):**

| Arm | q1 (2,500 offered) | q2..q14 | Tail used after q14 |
|---|---|---|---|
| A2b+tail | **2,500 / 2,500 placed, all via tail** (0 holes exist); 28,295 inserted / 4,501 dropped capacity / 1,208 evicted; 12,361 tail words, 2,500 tail rows | every batch places every offered doc via holes (2,375 … 1,283), tail 0 | 12,361 words (20.6 % of 60,000), 2,500 rows (62.5 % of 4,000) |
| A2+tail (frozen one flip) | **0 / 2,500 placed** (no slot dead at E: 32,796 of 32,796 postings dropped for capacity, so no doc keeps a posting and none reaches the tail) | all via holes (2,375 … 1,283) | 0 / 0 |
| A2-2p/old-at-free+tail | 2,500 / 2,500 via holes (deletes + updated-old = 3,000 holes ≥ demand); 28,295 / 4,501 / 1,208 | all via holes | 0 / 0 |

With reuse on, A2b+tail also ran 14/14 (bump 5,335,632 + 5,220,752 then 0;
reused 5,124,056 … 4,307,344). Allocated bytes after q1 for A2b+tail:
13,438,976 (of which tail records: forward_data.bin +98,304, offsets
+16,384, override +20,480).

**B2 (`+tail` arms, median of 3, q1, indicative wall):**

| Arm | Wall (s) | Device bytes | Logical bytes | Placed hole / tail of 2,500 |
|---|---|---|---|---|
| A2+tail | 0.075 | 6,242,304 | 321,392 | 0 / 0 |
| A2b+tail | 0.594 | 11,452,416 | 5,531,288 | 0 / 2,500 |
| A2-2p/old-at-free+tail | 0.175 | 13,590,528 | 699,857 | 2,500 / 0 |
| A2b-2p/old-at-free+tail | 0.967 | 22,306,816 | 10,475,216 | 2,500 / 0 |

**B7 (`+tail` arms, 100 trials each, checker = the exact reference
search):** A2b+tail PASS 100/100 SIGKILL, 100/100 power-loss drop, 100/100
power-loss pages, 104,184 registered reader queries (slow + fast reader
processes) all equal to their epoch's reference, 0 errors; A2-2p/old-at-free+tail
PASS 100/100 × 3, 61,096 reader queries. Caveat: with T_apply = 0.61 s
(A2b+tail) / 0.22 s and the flip as the last write, every SIGKILL trial and
power-loss cut observed the pre-flip epoch (0; for the 2p arm 0 or 1, never
2). The post-flip tail state (published counters, tail rows resolved) is
covered by the crate's replay test, whose cuts land on both sides of every
flip.

### INDICATIVE run on the v3.1 copy of shard 0 (not a bar; host shared, timings invalid)

File: `data/eval_results/inplace_b_updater_indicative_v31_20260930.json`
(key `B4`, 2 batches). Source: the encoder agent's v3.1 copy
`/home/vscode/work/inplace_update/stage3/encoder/v3_1` (encode report
`stage3/encoder/encode_report_v3_1.json`: reserve 48,173,568 tail words /
1,880,064 tail rows, `forward_data.bin` 4,239,272,488 B apparent), copied
with `cp -r --sparse=always` into `stage3/updater/pristine` (2026-09-30
04:04:17–04:04:29Z), one work copy per arm. Batch Q1 = `stage2/docs/q1.sfubat`
(the Stage-0 ENCODED SUBSAMPLE: 32,155 upserts, 8,465 in-base updates +
23,690 new, plus 1,131,292 deletions — NOT the full quarter), Q2 =
`q2.sfubat` (`synthetic_reuse: true`, see above). Run 04:04:29–04:16:58Z,
cores 8–15, no latency lock, concurrently with the queue's real-shard B2/B7
(cores 0–7) and the synthetic chain above: **every wall time below is
invalid as a measurement**. Protected-tree baseline: 0 differences at start
and end. Storage before (v3.1, every arm): st_size 7,275,711,357 B,
allocated 5,544,255,488 B — the same allocated bytes as the v3.0 copy of
2026-09-29 (the reserves are sparse).

| Arm | Batch | Docs offered / placed (hole + tail) / unplaced | Postings offered / inserted / dropped capacity / evicted | Tail words / rows used | Heap bump (B) | Wall (s, invalid) | Device / logical bytes |
|---|---|---|---|---|---|---|---|
| A2+tail (frozen) | Q1 | 32,155 / **0** (0 + 0) / 32,155 no surviving posting | 2,999,413 / **0** / 2,999,413 / 0 | 0 / 0 | — | 24.1 | 888,401,920 / 34,804,456 |
| A2+tail | Q2 (reuse) | 32,155 / 29,334 (29,334 + 0) / 2,821 | 2,999,413 / 916,338 / 2,083,075 / 0 | 0 / 0 | — | 24.8 | 980,029,440 / 51,637,973 |
| A2b+tail (one flip) | Q1 | 32,155 / **29,651 (0 + 29,651)** / 2,504 | 2,999,413 / 929,614 / 2,069,799 / 13,276 | **818,900 / 29,651** (1.70 % / 1.58 % of the reserve) | 1,116,106,896 of 1,159,213,056 (96.3 %) | 496.9 (plan 28.9, write 463.9) | 1,136,312,320 / 1,132,686,960 |
| A2b+tail | Q2 | **REFUSED before any write:** "posting heap exhausted: epoch 2 needs 43,128,440 B (unit of list 418: 132,544 B) with 0 B reusable and bump 1,116,106,896 of reserve 1,159,213,056 (R7); nothing of this epoch was written" | | | | | |
| A2-2p/old-at-free+tail | Q1 | 32,155 / 29,651 (29,651 + 0) / 2,504 | 2,999,413 / 929,614 / 2,069,799 / 13,276 | 0 / 0 | — | 35.8 (gap 8.65) | 1,705,005,056 / 58,497,314 |
| A2-2p/old-at-free+tail | Q2 (reuse) | 32,155 / 30,565 (30,565 + 0) / 1,590 | 2,999,413 / 976,384 / 2,023,029 / 52,550 | 0 / 0 | — | 43.0 (gap 9.34) | 1,627,660,288 / 71,284,782 |

Storage after (st_size / allocated, B): A2+tail after Q1..Q2 7,293,708,301 /
5,572,894,720 (+28.6 MB allocated: `forward_free.bin` 17,997,824,
`row_id_override.bin` 7,434,240, `block_inflation.bin` 3,207,168);
A2b+tail after Q1 7,284,864,255 / 6,680,100,864 (+1,135.8 MB: `posting_heap.bin`
1,117,786,112, `forward_data.bin` +6,561,792 = the 818,900 tail words,
`forward_offsets.bin` +237,568, `row_id_override.bin` 2,097,152,
`forward_free.bin` 9,154,560); A2-2p+tail after Q1..Q2 7,293,521,965 /
5,578,997,760.

**Findings stated plainly.**
- The placement, insertion, drop and eviction counts of every arm are
  IDENTICAL to the 2026-09-29 real-shard B4 (A2 Q1 0 / Q2 29,334 and
  916,338; A2-2p Q1 29,651 and 929,614 / 13,276 evicted): `+tail` and heap
  reuse change where bytes go, not the plan.
- **Frozen A2 still places 0 of 32,155 with `+tail`**: on a fresh copy no
  slot is dead, all 2,999,413 offered postings are dropped for capacity,
  and a document without a surviving posting never reaches the tail. The
  first-batch obstacle of the frozen arm is posting slots, not forward
  records.
- **A2b one flip places 29,651 of 32,155 on the first batch with `+tail`**
  (was 0), all via the tail; the 2,504 unplaced lost every posting to
  capacity. That costs 1.70 % of the tail-word reserve and 1.58 % of the
  tail-row reserve; from the second batch on the 1.13 M deletions per
  quarter leave more holes than documents, so the tail is not touched
  (Q2–Q14 of the synthetic run, Q2 of the 2p arm here).
- **Heap reuse cannot rescue A2b on the 1× reserve**: batch 1 leaves the
  bump at 96.3 %, batch 2 supersedes batch-1 units but may only reuse space
  freed at epochs ≤ 1 (there is none), so it is refused as before. Reuse
  pays only when the reserve holds two batches of units (synthetic 3×
  reserve: 14/14 batches, bump frozen at 66 %). For this doc set that is
  ≈ 2 × 1.12 GB ≈ 2.2 GB, i.e. a ≥ 2× reserve (`posting_heap.bin` apparent
  size, sparse); reported to the encoder agent as a format question.
- The A2b+tail Q1 write of 464 s (vs 230 s under the lock on 2026-09-29) is
  the shared host; not a measurement.

### Open points and format questions (for the encoder agent / coordinator)

1. `posting_free.bin` header: the updater stores `u64 epoch` at offset 16
   and `u64 n_entries` at offset 24 of the 64-byte header (§3.6 leaves them
   as zeros); entries are `{u64 unified offset, u64 len:48 | epoch:15}`.
2. Heap reserve default: a 1× reserve cannot reach steady-state reuse for a
   batch that rewrites ~94 % of the lists; ≥ 2× is needed (sparse, so the
   apparent size only).
3. Decoder unit-view cache (§3.R3): with reuse `(list, offset)` recurs over
   time; the cache must validate the unit header's `epoch written` on each
   hit or key by `(list, offset, epoch written)`.
4. Override clearing of dead rows is now reader-gated; a decoder/fixture
   that clears overrides itself must apply the same gate.

## Open items and known issues

- The A2b B5 residency drop on synthetic rep 0 is unexplained.
- `+tail` and heap reuse are built and tested (above); their B2/B4/B7 on the
  v3.1 copy under the lock have not run.
- The non-local-filesystem refusal is only tested as fs-type classification
  (no allow-listed network path exists).
- Real-shard B7 cost is *est.* 20 s per power-loss trial (recover + verify scan
  40 M words). Two primary arms × 300 trials may not fit the remaining wall time
  after the lock frees.
