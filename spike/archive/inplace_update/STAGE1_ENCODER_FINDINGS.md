# Stage 1 encoder/decoder findings — format v3, bar B1, measurement W1

> **CLOSED MEASURED 2026-09-30** — the pre-registered GO rule of `06_INPLACE_SPIKE_PLAN.md` read NO-GO: bar S0-1 measured a long-list dead-slot coverage of **0.019** (95 % CI 0.018–0.020) against 0.80. In one quarter 27 % of shard 0's docs are updated and 15 % more are new while deletions free 6 %, and a list cannot grow, so dead-slot reuse cannot absorb the churn (`inplace_s0_20260930.json`). Nothing in-place replaces it: updates stay with delta generations (`docs/delta_ingest/`). The v3 encoder/decoder is exact (B1 460/460, +1.3 % per query) and the +tail variant was built, but they remove the wrong obstacle. Full record: `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` results table and §"NO-GO 2026-09-30". Not current; do not resume.

**Status:** CLOSED MEASURED 2026-09-30

Written 2026-09-30 by the encoder/decoder agent (session
`session_01W21GKQhsdhoE9jbxQScFr5`). Run AHEAD of the GO gate of
`docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` at the owner's request; the GO
rule is unaffected. Every number below cites its results file. Format spec:
`spike/archive/inplace_update/FORMAT_V3.md`.

## B1 — zero-patch parity: PASS 460/460

Results: `data/eval_results/inplace_b_20260929.json`, key `B1` (measured
2026-09-29 21:50Z, harness `scripts/archive/inplace_update/eval_inplace_b1_parity.py`,
committed `35a42f26` before the run; guard wiring `dd522d7a`).

| Quantity | Value |
|---|---|
| Verdict | **PASS**: 460/460 queries identical, ordered top-200 doc ids AND f32 score bit patterns vs A0 |
| Per set | QA 240/240, QT 120/120, QD 100/100 |
| A0 | served `.so` (`.venv`, sha256 `62639335…`) on a byte copy of served shard 0 (`data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap`) |
| v3 decoder | side-built `.so` (sha256 `c70f58f4…`, `-C target-cpu=x86-64-v3`) on the encoder's v3 conversion of that copy, epoch 0, 0 non-zero inflation codes, 0 non-native lists |
| Build control | same side `.so`, v2 path, on the v2 copy vs A0: 460/460 identical |
| v2 reader on the v3 dir | rejected: `OSError … forward_format_version 3; this reader supports 1 (FixedU8Q) and 2 (per-doc scale) — rebuild the reader` |
| Copied index files v2 → v3 | all 8 byte-identical (incl. `posting_lists.bin`: zero-patch v3 posting words = v2 words) |
| Params | k = k′ = 200, query_cut = len(terms), heap_factor 0.8, sorted first term, M8 unset |
| Live-index guard | start and end listings of `data/seismic_150m` (320 files) and `/var/tmp/seismic_stage` (96 files) identical to the 2026-09-29T20:15Z baseline |

Build provenance: the side `.so` was built from fork commit `c7b4b54` =
`a3173d1` (encoder + decoder, `spike/archive/inplace_update/patches/seismic_upstream_inplace_v3.patch`) plus
the live-index guard on the converter
(`spike/archive/inplace_update/patches/seismic_upstream_inplace_v3_b1_guard.patch`). The results file's
`builds.side_v3.patch` field names only the first patch; the guard patch
changes the encoder's output checks, not the decoder.

### Mask cost (plan 06 addendum: reported, not gated)

Same side build, same content (v3 copy vs v2 copy), one process, both dirs
warmed, 1 discarded + 2 measured passes, per-query order alternated
(`B1.mask_cost`):

| | v2 decoder | v3 decoder |
|---|---|---|
| p50 per query | 2.837 ms | 2.876 ms |
| p95 per query | 4.694 ms | 4.660 ms |
| mean | 2.959 ms | 2.991 ms |

Per-query ratio v3/v2: median 1.0108, mean **1.0128 (95 % bootstrap CI
1.0091–1.0164)**; per-query difference median +0.030 ms, mean +0.032 ms.

What the number includes: the atomic load + FREE/TAG/START masks +
visibility XOR on every posting (both passes), the inflation-code load and
multiply per block, the `list_dir` load + compare per query term, and the
header read (two 128-byte records, two FNV checksums) per query.
**It excludes reader registration in `readers.bin` and the A2b unit path**:
neither exists in the B1 build (registration was added later, plan 06
addendum third says its cost is first reported in B3; with zero patches
every list is native, so the unit path cannot be exercised). Their costs are
measured separately (below, when available). Single shard, warm cache,
latency lock held; not the end-to-end `search_rrf` latency of B3.

## Spare bits — measured (encoder report, `B1.encoder.spare_bits`)

Full scan of 40,361,159 posting words of shard 0:
- max START 357,641,117 words → **29 bits**; max LEN **74 words → 7 bits**
  (min 4);
- **28 spare bits per posting word** (brief §1.5 claimed ~20); 0 words had
  any of bits 48..63 set;
- v3 uses 16 of them (FREE + 15-bit TAG); the 32-bit START keeps 3 bits
  (8×) of headroom;
- `forward_offsets.bin` entries: max 481,735,493 → 29 bits → 35 spare, not
  used by v3 (CSR, binary-searched);
- postings reference forward words only up to 357,641,134 of 481,735,493.

Encoder (`B1.encoder`): 36.1 s total for shard 0 (copy 18.7 s, posting scan
0.12 s, per-list minima 16.4 s decoding every posting's record, checksums
0.15 s); side files allocated: inflation 6,413,956 B, list_dir 459,232 B,
list_min 229,616 B, list_crc 229,616 B, readers 16,384 B, header 8,192 B,
free lists 640 B; sparse (0 allocated): `posting_heap.bin` 1,159,213,056 B and
`row_id_override.bin` 150,394,576 B apparent. Doc ids: all `W<digits>`, max
7,143,275,721 (33 bits).

## W1 — write unit of arm A2b: LIST

Results: `data/eval_results/inplace_writeunit_20260929.json` (measured
2026-09-29 21:48Z, harness `scripts/archive/inplace_update/eval_inplace_w1_writeunit.py`,
committed `ea264b6a` before the run). Structural measurement, not an efficacy
result.

- **Write unit: LIST** (rule: BLOCK if separable, else LIST). Code facts:
  the summary is component-major — one Elias-Fano offsets sequence per list
  over all components, one `summaries_ids` bitfield and one u8 `values`
  array per list — so re-encoding one block's summary shifts every later
  entry. Data: **0 of 3,203,940 blocks** (in lists with ≥ 2 blocks) have
  contiguous summary entries; a block's entries span a median 97.4 % of its
  list's summary section; all 23,575 multi-block lists interleave blocks.
- **Offset flip:** no on-disk field names a list in the v2 format (a list's
  location is the prefix walk of JSON manifest lengths at load), and a
  block is named by entries of a dense prefix array plus Elias-Fano runs;
  neither can be published by one 8-byte store → format v3 carries an
  indirection table (`list_dir.bin`, two banks; FORMAT_V3.md §3.6).
- Bytes per non-empty list (26,613 lists): whole list p50 21,528 B, p90
  138,494, p99 159,572, max 179,736, total 1,159,144,880; postings p50 4,960
  B (max 42,000); summary section p50 15,664 B (max 134,064). Per block
  (3,206,978): postings p50 72 B (max 41,736), attributable summary p50 160
  B (max 2,834).
- **Correction to the results file:** `offset_flip.LIST.consequence` says
  "~23 manifest scalars"; the per-list manifest has **24** scalars
  (FORMAT_V3.md revision 3 §3.R3 is canonical).

## A2b unit read path, reader registration

Built after B1 (fork line `a6fd0a1` → `c704e5d` → `3157a95`). The first build
(2026-09-29 21:51Z, in the same locked job as B1) FAILED to compile: `gen`
is a reserved keyword in Rust edition 2024 (6 errors, all that identifier);
fixed in `3157a95` and requeued. Test harness
`scripts/archive/inplace_update/eval_inplace_a2b_read.py` (committed `acb16db9`, guard
`dd522d7a`, before any run).

**Results: `data/eval_results/inplace_a2b_read_20260930.json` (measured
2026-09-30 04:11Z, queued job under the latency lock, cores 0–7; synthetic
160,347-doc shard, 22,167 lists, 3,758,807 postings; encoder 3.3 s). File
verdict: `FAIL` — the harness's PASS rule requires parity AND a non-zero
change count, and the change count is 0 (vacuous fixture); the read path
itself returned no wrong result.** Recorded exactly as the file says:

| Quantity | Value |
|---|---|
| Fixture | list 742 (in 250 of the 460 queries, 329 blocks) rewritten as a heap unit with block 164 dropped: 3,837 → 3,832 postings, 329 → 328 blocks, unit body 122,176 B + 256 B header at unified offset 78,998,640 (native list 122,352 B); native inflation codes of the list's 329 blocks poisoned to 255 |
| Decoder state | `inplace_header_info` (0, –, 329 non-zero inflation codes, 1 non-native list); registration on (`readers.bin mapped read-write`); unit cache 1 entry after the queries |
| Parity, unit vs native-splice oracle | **460/460 identical**, first difference none |
| Non-vacuity | queries changed vs the zero-patch baseline: **0** → verdict `FAIL` (the 5 dropped postings of block 164 reached no query's top-200; the unit path, the 328-block summary and the ignored poisoned inflation were exercised on 250 queries but the check cannot distinguish "unit read correctly" from "unit never consulted" for the top-200) |
| `readers.bin` after the queries | every slot free (`[]`) |
| Registration cost | 297.4 ns per (register + unregister), `bench_registration(100000)` |
| Unit build cost | 125,950 ns per uncached build incl. checksum, of which checksum alone 123,183 ns (`bench_unit_build(742, 200)`, 122 KB unit) |
| First touch vs cached | median +0.178 ms, mean +0.166 ms per query (n = 40 queries containing list 742; unit cache cleared before the first touch) |
| Registration on vs off, paired | median +1.83 µs, mean +1.93 µs per query (n = 460, 1 discarded + 2 measured passes, ABBA) |
| Live-index guard | start and end listings (320 / 96 files) identical to the baseline |
| Wall | 15.5 s |

### Non-vacuous rerun — PASS 460/460, 4 queries changed

Results: `data/eval_results/inplace_a2b_read_20260930b.json` (measured
2026-09-30 05:21Z; harness `853e5b12`, committed before the run; work root
`/home/vscode/work/inplace_update/stage3/encoder/a2b`, cores 8–15, latency
lock NOT taken — it was held by B7). **The 04:11Z run above stays the cost
record**; every timing of this rerun is host shared, indicative only.

Why the first rerun was still vacuous: dropping the block of list 742 whose
docs appear most in the baseline top-200 (block 82, 92 postings, docs in
282 queries' top-200) changed 0 queries (`inplace_a2b_read_20260930b.json`
was overwritten by the final run; the intermediate result was parity
460/460, changed 0) — SEISMIC scores a doc's full record once ANY query
term's list reaches it, so removing one path leaves the score untouched.
The fixture therefore now drops the (list, block) pair maximising the
number of baseline queries with a top-200 doc reached ONLY through that
list (no other query term holds the doc): list 7110 (6 blocks, 79 postings,
in 6 queries), block 5 (33 postings), predicted 4 affected queries (12
sole-path (query, doc) pairs).

| Quantity | Value |
|---|---|
| Fixture | list 7110 rewritten as a heap unit without block 5: 79 → 46 postings, 6 → 5 blocks, unit body 2,112 B + 256 B header at unified offset 78,998,640 (native list 3,232 B); the list's 6 native inflation codes poisoned to 255 |
| Decoder state | `inplace_header_info` (0, –, 6, 1); registration on; unit cache 1 |
| Parity, unit vs native-splice oracle | **460/460 identical**, first difference none |
| Non-vacuity | **4 queries changed** vs the zero-patch baseline (= the 4 predicted) → verdict **PASS** |
| `readers.bin` after the queries | every slot free (`[]`) |
| Live-index guard | start and end listings (320 / 96 files) identical to the baseline |
| Build | fork `328bf51` (= `d7cbae1` + the fixture fix below), side `.so` sha256 `e887cafd…`; the v3 copy is a v3.1 dir (tail reserve 378,880 words / 16,384 rows, unused) |
| Wall | 19.1 s |

Fixture fix found by this rerun (fork `328bf51`, in
`spike/archive/inplace_update/patches/seismic_upstream_inplace_v3_tail.patch`): on a v3.1 dir the A2b
fixture byte-copied `forward_data.bin` / `forward_offsets.bin` into the
oracle, so the v2 reader saw the sparse tail reserve appended to its CSR and
panicked in `id_from_range` (first attempt of this rerun, 05:17Z); the
oracle's forward files are now the base prefixes. The +tail results above
are unaffected (their oracle is written by the tail fixture, which already
truncates).

## +tail read path (format v3.1) — PASS, synthetic fixture 460/460 and shard-0 zero-patch parity 460/460

Results: `data/eval_results/inplace_tail_read_20260930.json` (measured
2026-09-30 03:48Z, keys `synthetic` and `shard0`; harness
`scripts/archive/inplace_update/eval_inplace_tail_read.py`, committed `e8f85d1c` before
the run; spec `FORMAT_V3.md` revision 6, committed `c4caac6c` before the
code). Identity tests, not a pre-registered bar. Build: fork commit
`d7cbae1` on top of `3157a95` (patch
`spike/archive/inplace_update/patches/seismic_upstream_inplace_v3_tail.patch`), side `.so` sha256
`a0870b75…`, `-C target-cpu=x86-64-v3`, cores 8–15, latency lock NOT taken;
served `.so` sha256 `62639335…` (A0). Every time below is "host shared, not
a measurement".

### Synthetic shard (160,347 docs, M4 generation `delta_g0001`)

| Quantity | Value |
|---|---|
| Encoder (defaults) | base_words 3,784,984; reserve 378,880 words / 16,384 rows (10 %, rounded up to 512); 3.4 s wall |
| Extended files (apparent → allocated) | `forward_data.bin` 30,279,872 → 33,310,912 B, allocated 30,281,728; `forward_offsets.bin` 1,282,784 → 1,413,856 B, allocated 1,286,144; `row_id_override.bin` 1,413,848 B apparent, 0 allocated |
| Copied prefix / other files | both forward files byte-identical to the source over the source length; the other 6 copied files byte-identical |
| **Zero-patch parity of the v3.1 layout** | v3.1 decoder at epoch 0 vs the v2 decoder on the unconverted copy (same side build): **460/460** (QA 240, QT 120, QD 100); header (0, –, 0, 0), tail (used 0, rows 0), `len` 160,347 |
| Fixture | 64 base docs (the most frequent in the epoch-0 top-200 lists: 166 … 63 occurrences) copied to the tail: 2,455 tail words used, 64 rows published, records 16–70 words; 8,054 posting words repointed (47–246 per doc) in 2,653 lists, TAG = 1; header slot 1 = epoch 1; fresh ids W7213221598…; oracle n_docs 160,411; 0.85 s wall |
| **v3.1 on the fixture (E = 1) vs v2 on the oracle** | **PASS 460/460** (QA 240, QT 120, QD 100), ordered top-200 doc ids and f32 score bits |
| Non-vacuity | 406/460 queries have ≥ 1 tail doc in their top-200 (5,186 tail hits in all); 406 queries changed vs the epoch-0 baseline; 0 old ids of moved docs returned |
| Decoder state | `inplace_header_info` (0, 1, 0, 0); `inplace_tail_info` (3,784,984, 378,880, 16,384, 2,455, 64); `len` stays 160,347 (base rows); every `readers.bin` slot free after the queries; registration on |
| Indicative p50 | v3.1 tail 1.460 ms, v2 oracle 1.391 ms per query — host shared, not a measurement |

### Shard 0 (v3.1 conversion of `stage1/v2copy`, zero patches)

The v3.1 copy for the updater agent:
`/home/vscode/work/inplace_update/stage3/encoder/v3_1/` (sentinel
`.inplace_work_copy` names it and its source `stage1/v2copy`, source manifest
FNV `e14c71a12c610f65`); encode report
`/home/vscode/work/inplace_update/stage3/encoder/encode_report_v3_1.json`.

| Quantity | Value |
|---|---|
| Encoder | 45.3 s total (copy 25.1 s, posting scan 0.17 s, list minima 17.4 s, ids 0.41 s, crc 0.16 s, side files + sync 1.06 s); spare bits unchanged from B1 (max START 357,641,117, max LEN 74) |
| Tail reserve (defaults) | base_words 481,735,493; reserve 48,173,568 words / 1,880,064 rows |
| Extended files (apparent → allocated) | `forward_data.bin` 3,853,883,944 → 4,239,272,488 B, allocated 3,853,893,632; `forward_offsets.bin` 150,394,584 → 165,435,096 B, allocated 150,396,928; `row_id_override.bin` 165,435,088 B apparent, 0 allocated; directory 6.8 GB apparent / 5.2 GB allocated |
| Copied prefix / other files | forward files byte-identical over the source length; other 6 files byte-identical |
| **Zero-patch parity vs A0** | v3.1 decoder (side `.so`) on the v3.1 copy vs the served `.so` on `stage1/v2copy`: **PASS 460/460** (QA 240, QT 120, QD 100), ids + f32 score bits |
| Decoder state | header (0, –, 0, 0); tail (481,735,493, 48,173,568, 1,880,064, 0, 0); `len` 18,799,322 |
| Indicative p50 | A0 2.963 ms, v3.1 2.723 ms — host shared, not a measurement (cache state differs between the two subprocesses) |
| Live-index guard | start and end listings of `data/seismic_150m` (320 files) and `/var/tmp/seismic_stage` (96 files) identical to the 2026-09-29T20:15Z baseline |

What is NOT measured here: the per-query cost of the tail path on a large
tail (the fixture has 64 rows; the binary search is over the published rows
only), the updater's write side (built by the updater agent against
revision 6), and the A2b unit bound against `base_words + tail words used`
(no unit exists in these dirs: exercised only by the unchanged bound check
on a native dir). Those are IMPLEMENTED, EFFICACY UNMEASURED.
