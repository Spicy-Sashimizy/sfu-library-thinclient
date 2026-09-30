# Format v3 — in-place-updatable dv-v2 shard (encoder/decoder spec)

> **CLOSED MEASURED 2026-09-30** — the pre-registered GO rule of `06_INPLACE_SPIKE_PLAN.md` read NO-GO: bar S0-1 measured a long-list dead-slot coverage of **0.019** (95 % CI 0.018–0.020) against 0.80. In one quarter 27 % of shard 0's docs are updated and 15 % more are new while deletions free 6 %, and a list cannot grow, so dead-slot reuse cannot absorb the churn (`inplace_s0_20260930.json`). Nothing in-place replaces it: updates stay with delta generations (`docs/delta_ingest/`). The v3 encoder/decoder is exact (B1 460/460, +1.3 % per query) and the +tail variant was built, but they remove the wrong obstacle. Full record: `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` results table and §"NO-GO 2026-09-30". Not current; do not resume.

**Status:** CLOSED MEASURED 2026-09-30

**State: B1 HAS RUN; revision 6 (2026-09-30, +tail v3.1) is BUILT and its read path tested 2026-09-30 03:48Z (`data/eval_results/inplace_tail_read_20260930.json`: synthetic fixture PASS 460/460, shard-0 zero-patch parity PASS 460/460; STAGE1_ENCODER_FINDINGS.md §"+tail read path"). B1 HAS RUN — PASS 460/460 on 2026-09-29 21:50Z (`data/eval_results/inplace_b_20260929.json`, key `B1`; findings `spike/archive/inplace_update/STAGE1_ENCODER_FINDINGS.md`). Everything the updater, A2b unit reader and `+tail` use remains DESIGN unless a revision below says built and measured.** Original state line: DESIGN until bar B1 runs. Written 2026-09-29, before any encoder or
decoder code existed, by the encoder/decoder agent of session
`session_01W21GKQhsdhoE9jbxQScFr5`. Started ahead of the GO gate of
`docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` at the owner's request; scope is
the encoder, the decoder and bar B1 only (no bit updater, no eviction, no
epoch-publish logic beyond reading the header). Every number below is either
read from the shard-0 manifest (cited) or marked *est.*; the posting-word
spare-bit numbers are an upper bound from the manifest until the encoder's
full scan (§2.3) replaces them.

Inputs this spec respects (read 2026-09-29): brief
`docs/archive/inplace_update/05_INPLACE_BIT_UPDATE_BRIEF_2026-09-29.md` §2 with both
notes, `04_IMMUTABILITY_RESEARCH.md` §"Addendum 2026-09-29" (esp.
"Consequences for brief 05"), plan `06_…` incl. its addendum. Design facts
honoured: postings are `offset:48,len:16` and store no weight; SEISMIC block
summaries are approximations, not upper bounds; epoch rollback is sound only
for content already dead at the published epoch; readers load mutable fields
atomically; the per-query cost of the added checks is measured (B1), not
assumed.

---

## 1. Base format (what v3 starts from)

The served shard-0 directory
`data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap`
(staged byte-identical at `/var/tmp/seismic_stage/…`; `manifest.json` compared
equal 2026-09-29). Writer/reader: `spike/seismic_upstream/src/mmap_io.rs`
(`convert_f16_dir_to_dotvbyte`, `MmapSeismicIndexDotVByte`,
`read_posting_lists`); scoring loop `src/mmap_index.rs`.

| File | Bytes (shard 0) | Content | v3 mutability |
|---|---|---|---|
| `manifest.json` | 21,878,891 | JSON; per-list slice lengths; `forward_format="dotvbyte_fixedu8"`, `forward_format_version=2` | rewritten by the encoder (§5), then frozen |
| `config.json` | 312 | build config (G2: n_postings 3500, max_fraction 1.5, α 0.4) | frozen |
| `forward_offsets.bin` | 150,394,584 | `usize[n_docs+1]` CSR word offsets into `forward_data.bin` | frozen (see §3.4) |
| `forward_data.bin` | 3,853,883,944 | `u64` words, DotVByte records, dv-v2 envelope (`u16 n`, `f16 vmax`, gaps, end-anchored u8 values tail) | holes only (§3.4) |
| `forward_encoder.bin` | 114,834 | bincode `DotVByteFixedU8Encoder` (component remap) | frozen |
| `posting_lists.bin` | 1,159,211,728 | per list: packed postings `u64`, block offsets, EF offsets, summary ids, u8 values, f32 minimums/quants, u16 component ids | posting WORDS only (§2); everything else frozen |
| `token_to_id_map.bin` | 645,849 | bincode map | frozen |
| `document_mapping_{strings,offsets}.bin` | 206,749,517 / 150,394,584 | row → `"W<n>"` slab | frozen (override in §3.5) |

Shard-0 facts from `manifest.json` (read 2026-09-29): 18,799,322 docs;
28,702 posting lists (= vocabulary; list index = component id), 26,613
non-empty (2,089 empty lists have 0 postings, 0 blocks, `block_offsets_len`
0); 40,361,159 postings; longest list 5,250 (= the cap 3,500 × 1.5);
3,206,978 blocks, at most 483 per list; `forward_data_words` 481,735,493;
`forward_nnz` 1,647,141,424; `forward_page_aligned` false;
`forward_reordered` `block_walk_canonical`.

The `hotset_*.json` files in the source dir are serving sidecars, not index
files; the encoder does not copy them.

---

## 2. Posting word (the free-slot flag and the epoch tag)

### 2.1 v2 word (unchanged meaning of the low 48 bits)

`PackedPostingBlock` (`posting_list.rs`): `n = (start << 16) | len`, `start`
= word offset of the doc's record in `forward_data.bin` (48-bit field), `len`
= record length in words (16-bit field). No weight is stored.

### 2.2 v3 word

```
bit 63        FREE   free-slot flag
bits 48..62   TAG    15-bit epoch tag
bits 16..47   START  32-bit word offset into forward_data.bin
bits  0..15   LEN    16-bit record length in words (unchanged)
```

Decoder masks (the "three masks"):
1. `FREE = w >> 63`
2. `TAG  = (w >> 48) & 0x7FFF`
3. `START = (w >> 16) & 0xFFFF_FFFF`, `LEN = w & 0xFFFF`

**Visibility at published epoch E:** `visible(w, E) = (TAG <= E) XOR FREE`.

| Slot state | FREE | TAG | START/LEN | visible at E |
|---|---|---|---|---|
| base posting | 0 | 0 | base record | always |
| inserted in the batch that publishes e+1 | 0 | e+1 | new record | iff E ≥ e+1 |
| deleted in the batch that publishes e+1 | 1 | e+1 | OLD record, retained | iff E < e+1 (still live at e) |
| dead since an epoch ≤ E | 1 | ≤ E | stale | never |

A delete writes only bits 48..63 (the old START/LEN stay), so an epoch-e
reader still scores the old content until the flip. An insert may only target
a slot that is dead at the published epoch (row 4); this is the only case in
which "a crash mid-batch leaves epoch e serving" holds
(`04_…` addendum §D). Eviction of a live posting and same-batch reuse of a
slot freed in that batch are NOT representable by this word alone; they need
an undo record or must be refused (updater's choice, out of scope here; B7
names what is built).

With zero patches every word has FREE = 0 and TAG = 0, and the header epoch is
0, so every slot is visible and START/LEN equal the v2 fields: the v3
`posting_lists.bin` is byte-identical to v2. The encoder verifies that bits
48..63 of every v2 word are zero (i.e. every START < 2^32) and aborts
otherwise.

Consequences of the narrower START: `forward_data.bin` may grow to 2^32 words
(32 GiB) before the format breaks; shard 0 uses 481,735,493 words (11.2 % of
that). The 15-bit TAG allows 32,767 publishes before a rebuild must reset all
tags to 0 (the compactor of brief §2.8 does this by construction).

### 2.3 Spare bits: brief claim vs this shard

Brief §1.5 claimed "~20 spare bits/posting" and "~30 spare bits/doc offset".

- Offset field (48 bits): every START < `forward_data_words` = 481,735,493 <
  2^29 (manifest), so START needs **≤ 29 bits → ≥ 19 spare bits** in the
  offset field. Upper bound from the manifest. **Measured 2026-09-29 (full
  scan of 40,361,159 posting words, encoder report in
  `data/eval_results/inplace_b_20260929.json` `B1.encoder.spare_bits`): max
  START = 357,641,117 words → 29 bits → 19 spare bits in the 48-bit field**
  (every posting ends at or before word 357,641,134; the forward records
  beyond it, up to word 481,735,493, are not referenced by any posting).
- Length field (16 bits): **measured max LEN = 74 words → 7 bits → 9 spare
  bits** (min LEN 4 words; bit-width histogram 3:1,407 / 4:964,352 /
  5:31,634,386 / 6:6,843,603 / 7:917,411 postings).
- **True spare bits per posting word, measured: 64 − 29 − 7 = 28** (brief
  claim ~20). v3 uses 16 (FREE + TAG); START keeps 32 − 29 = 3 bits of
  headroom (8× the largest START in use). Zero words had bits 48..63 set.
- True spare bits per posting word = 64 − bits(max START) − bits(max LEN);
  v3 uses 16 of them (FREE + TAG) and keeps the rest as START headroom.
- `forward_offsets.bin` entries: values ≤ 481,735,493 → 29 bits → 35 spare
  bits per 8-byte entry (measured: max 481,735,493, 29 bits). v3 does **not** use them: the array is a CSR
  (record extents are `offsets[i]..offsets[i+1]`) that `id_from_range`
  binary-searches, so tagging entries would break both.

---

## 3. Side files (new in v3)

All integers little-endian. All mutable fields are naturally aligned, 1 or 8
bytes wide, and written with single aligned stores. The v3 reader maps side
files read-only and loads every mutable field with an atomic load
(`Relaxed`; header fields `Acquire`).

### 3.1 `inplace_header.bin` — dual header, epoch record (written LAST)

8,192 bytes = two 4,096-byte pages; slot s ∈ {0, 1} is the first 128 bytes
of page s (a torn sector write of one slot cannot damage the other). Record
(widened from 64 to 128 bytes on 2026-09-29, before any code ran, to reserve
the A2b fields of §3.6):

| Off | Type | Field |
|---|---|---|
| 0 | u64 | magic = `b"SFUIPV3\0"` read as LE u64 |
| 8 | u32 | format version = 3 |
| 12 | u32 | slot index (0 or 1; must equal the page) |
| 16 | u64 | epoch |
| 24 | u64 | n_docs (must equal the manifest) |
| 32 | u64 | n_posting_lists (must equal the manifest) |
| 40 | u64 | n_blocks_total (Σ `n_summaries`, must equal the manifest) |
| 48 | u64 | FNV-1a-64 of the `manifest.json` bytes (binds header to manifest) |
| 56 | u64 | posting-heap bytes used (bump pointer) — reserved for A2b, DESIGN; 0 |
| 64 | u64 | forward tail words used — reserved (tail append), DESIGN; 0 |
| 72..120 | u64 × 6 | reserved, 0 |
| 120 | u64 | FNV-1a-64 of bytes 0..120 of this record |

Reader: a slot is valid iff every check above holds; the published epoch E is
the epoch of the valid slot with the larger epoch (tie → slot 0). No valid
slot → the directory is rejected. The reader snapshots E once per query
(start of `search`) and uses it for the whole traversal.

Writer protocol (for the updater; not built here): write data → `fsync`
(Windows: `FlushViewOfFile` + `FlushFileBuffers`) → write the inactive slot
`(e+1) & 1` with epoch e+1, checksum field last → `fsync` the header. A torn
or half-written slot fails its checksum and readers keep the other slot.
Grace period: content freed at epoch f may be overwritten only after every
query that snapshotted an epoch < f has finished (queries are ms-long; the
updater waits a fixed drain interval after each flip, *est.* ≥ 10 s). This
also covers the inactive inflation bank (§3.2).

Encoder: writes slot 0 with epoch 0 and slot 1 all-zero (invalid), after
every other file is written and synced, then syncs the header and the
directory. A crash during encoding leaves no valid header → clean rejection.

### 3.2 `block_inflation.bin` — per-block inflation byte, two banks

`2 × n_blocks_total` bytes (6,413,956 B for shard 0). Bank b ∈ {0, 1}
occupies bytes `[b × n_blocks_total, (b+1) × n_blocks_total)`. Inside a bank,
blocks are list-major: list t's block j is at `base[t] + j` with
`base[t] = Σ_{t' < t} n_summaries(t')` (computed at load from the manifest;
not stored).

Code c → multiplier: c = 0 → 1.0; 1 ≤ c ≤ 254 → `1 + c/32` (exact in f32);
c = 255 → SATURATED: the block's bound is +∞ (always evaluated). This
differs from S0-3's simulation rule ("code ∈ 0..255, > 255 saturated") by
one code: 255 here is the saturation marker, so the largest finite
multiplier is 1 + 254/32 = 8.9375.

Reader at epoch E reads bank `E & 1`. Scoring loop: for block b of list t
with summary dot `d`, the skip test and the first term's sort key use
`d' = (c == 255) ? +∞ : d × m(c)`. With c = 0, `d × 1.0f32` is bit-identical
to `d` (IEEE 754), which is what B1 tests.

Why two banks (a decision the brief left open): brief §2.4 has one byte per
block; `04_…` addendum §D shows a raised inflation byte cannot be rolled back
and changes what an epoch-e reader visits. The updater writes only the
inactive bank (copying the active bank into it first), so epoch-e readers
never see epoch-e+1 inflation. Cost: n_blocks_total extra bytes.

Scope limit restated: a scalar multiplier cannot cover a component absent
from the block's α-pruned summary (`blind_mass`, S0-3), and SEISMIC
summaries are not upper bounds, so "recall cannot drop" stays DESIGN ONLY.

### 3.3 `list_min.bin` — per-list minimum side array (updater-only)

`n_posting_lists × u64` (229,616 B for shard 0). Entry for list t:

```
bits  0..31  f32 bits of the minimum weight of term t over the live slots
bits 32..47  slot index (position in the list's packed postings) of that minimum
bits 48..62  epoch at which the entry was computed (0 at encode)
bit  63      EMPTY (list has no live slot; other bits 0)
```

Weight = the value the engine scores: the dv-v2 dequantized value of
component t in the doc's record (`decode_vector`, u8/255 × vmax), not the
f16 twin value. Ties → lowest slot index. The slot index fits 16 bits
because every list has ≤ 5,250 slots (the encoder asserts < 65,536). The
encoder computes every entry by decoding the record of every posting of every
list (§5). Readers never read this file.

### 3.4 `forward_free.bin` — forward-heap free list (updater-only)

```
header (64 B):  u64 magic b"SFUFFL3\0" | u32 version 3 | u32 n_classes (16)
                | u64 epoch | u64 n_entries_total | u64 capacity_total
                | u64 reserved | u64 reserved | u64 FNV-1a-64 of bytes 0..56
class table:    16 × 32 B { u32 min_words | u32 max_words | u64 count
                            | u64 capacity | u64 byte_offset_of_entries }
entries:        u64 = hole START:32 (bits 0..31) | hole LEN:16 (bits 32..47)
                      | epoch freed:15 (bits 48..62) | bit 63 reserved
```

Size classes (words, inclusive): 1–8, 9–12, 13–16, 17–20, 21–24, 25–28,
29–32, 33–40, 41–48, 49–64, 65–96, 97–128, 129–192, 193–256, 257–512,
513–65,535 (mean record 25.6 words = 481,735,493 / 18,799,322).
A hole may be used only if `epoch freed ≤ E` and the grace period (§3.1)
has passed. Encoder: header + class table only, every count and capacity 0
(576 B). Readers never read this file; the single-writer updater may rewrite
it by write-new + rename.

Hole reuse keeps `forward_offsets.bin` frozen: a new record of `n ≤ h`
words is written into a hole `[s, s+h)` that was doc row r's record, padded
INSIDE the record (zero words between the gap bytes and the end-anchored
u8 values tail, the E7 Fix #5 mechanism; the dv-v2 envelope shares
`from_unchecked_slice_inner`, which locates the values tail from the slice
end). Its postings carry START = s, LEN = h, so `id_from_range` resolves
them to row r exactly (it asserts `offsets[r+1] == s+h`). The new doc
therefore takes row r; its external id comes from §3.5. Unverified for
dv-v2 records: the updater must decode-verify padded records (not B1).
Records that fit no hole need a tail-append path with a pre-reserved,
already-mapped region (out of scope; v3.0 reserves none).

### 3.5 `row_id_override.bin` — external id of a reused row

`n_docs × u64` (150,394,576 B apparent size), created with `set_len`
(sparse: no blocks allocated at encode). Entry 0 = no override (the id comes
from the frozen doc-mapping slab); otherwise bit 63 = 1 and bits 0..62 =
the numeric part of the OpenAlex work id, rendered `"W<n>"`. Shard-0 ids are
all `"W"` + decimal (first entries checked 2026-09-29; the encoder checks
all and reports the maximum, which must be < 2^63). Read once per returned
winner (k′ per query), never in the scoring loop. A row is overridden only
while every posting that reaches it is invisible at E (the row's old doc is
dead at E, the new postings are tagged e+1), so no epoch tag is needed.

### 3.6 Reserved for arm A2b (copy-on-write list re-encode) — DESIGN

Added 2026-09-29 on the coordinator's instruction after
`06_…` "Addendum 2026-09-29 (second)" pre-registered arm A2b as
supplementary. Nothing here is used by B1 except the directory check the
decoder performs (below), whose cost B1 measures. The write unit is the
LIST: `scripts/archive/inplace_update/eval_inplace_w1_writeunit.py` (W1) records why —
a block's summary entries are spread over the list's component-major
Elias-Fano/bitfield summary, and no on-disk field names a list in v2 (a
list's location is the prefix walk of JSON manifest lengths done at load),
so v3 must add an indirection table. W1's results file is the evidence;
this section follows its code-derived verdict.

- **`list_dir.bin`** — `2 × n_posting_lists × u64` (459,232 B for shard 0),
  two banks selected by `E & 1` like the inflation banks. Entry = byte
  offset of list t's unit in the unified posting address space:
  `[0, len(posting_lists.bin))` = `posting_lists.bin`,
  `[len, len + reserve)` = `posting_heap.bin`. The encoder writes the
  NATIVE offset (start of the list's packed postings in
  `posting_lists.bin`) into both banks. A2b publishes a rewritten list by
  writing the inactive bank's entry (one aligned 8-byte store) and flipping
  the header epoch, so all lists of a batch switch together and an epoch-e
  reader never sees a half-published batch.
- **`posting_heap.bin`** — sparse file, apparent size = the reserve
  (encoder default: `len(posting_lists.bin)` rounded up to 4 KiB =
  1,159,213,056 B for shard 0, *est.* one full rewrite of every list
  before compaction), no blocks allocated at encode, mapped read-only at
  load so units written later are visible without a re-mmap. Bump pointer
  = header field 56.
- **A2b unit** (written by the updater into the heap; not built): 8-byte
  aligned; 256-byte header `{u64 magic b"SFUL2B3\0", u32 list id, u32 epoch
  written, u64 body bytes, 23 × u64 = the list's PostingListManifest scalars
  in manifest order, u64 FNV-1a-64 of header[0..248] ‖ body}`; body = the
  native slice sequence with the native alignment rules. The per-unit
  checksum lives in the unit header.
- **`list_crc.bin`** — `n_posting_lists × u64` (229,616 B), FNV-1a-64 of
  each native list's bytes `[packed-postings start, end of its last
  slice)`; the integrity check for native lists that whole-file checksums
  lose once A2 slot writes exist. Updater/verifier only; the decoder does
  not check it per query.
- **`posting_free.bin`** — 64-byte header (`u64 magic b"SFUPFL3\0"`, u32
  version 3, zeros, u64 FNV-1a-64 of bytes 0..56) and no entries at encode;
  entries (DESIGN) are 16 B `{u64 byte offset, u64 byte length:48 | epoch
  freed:15}`. A2b frees nothing before compaction (old units stay
  allocated), so this list exists to hold heap space freed by a compactor.
- **Decoder check (built, measured by B1).** Per query term (≤ 64 per
  query; not per block or per posting): one `Acquire` load of the active
  bank's `list_dir` entry, compared with the in-memory native offset. Equal
  → the load-time list view is used; not equal → the query fails with an
  explicit "A2b unit, this decoder build reads native lists only" error
  (the A2b unit parser is not built).

**Cost of carrying both A2 and A2b in one format (shard 0):** 688,848 B
allocated (`list_dir.bin` + `list_crc.bin`) + 64 B (`posting_free.bin`) +
64 B more per header slot, the sparse heap's address-space reservation
(1.16 GB virtual, 0 B allocated at encode), and one load + compare per
query term in the decoder. B1's mask-cost run measures the decoder cost
with this check included. A2 and A2b are alternative arms on separate
copies; a copy served by A2b does not also take A2 slot writes on the
same list (the updater's rule, DESIGN).

---

## 4. Version stamp and rejection by a v2 reader

`manifest.json` of a v3 directory: the v2 manifest with
`forward_format_version = 3` and a new object `inplace_v3`:

```json
"inplace_v3": {
  "format": "sfu_inplace_v3", "version": 3,
  "record_envelope_version": 2,
  "posting_word": {"free_bit": 63, "tag_shift": 48, "tag_bits": 15,
                   "start_shift": 16, "start_bits": 32, "len_bits": 16},
  "n_blocks_total": 3206978,
  "inflation": {"file": "block_inflation.bin", "banks": 2,
                "code_saturated": 255, "multiplier": "1 + code/32"},
  "side_files": ["inplace_header.bin", "block_inflation.bin",
                 "list_min.bin", "forward_free.bin", "row_id_override.bin",
                 "list_dir.bin", "list_crc.bin", "posting_heap.bin",
                 "posting_free.bin"],
  "a2b_reserved": {"list_dir": {...}, "list_crc": {...},
                   "posting_heap": {"reserve_bytes": ..., "base": ...},
                   "posting_free": {...}, "status": "reserved for A2b, DESIGN"},
  "source": {"dir": "...", "manifest_fnv64": "..."}
}
```

`forward_format` stays `"dotvbyte_fixedu8"`. The v2 reader
(`MmapSeismicIndexDotVByte::from_mmap`) accepts only versions 1 and 2 and
fails with `dotvbyte dir has forward_format_version 3; this reader supports
1 (FixedU8Q) and 2 (per-doc scale) — rebuild the reader` — an explicit load
error, never a silent mis-decode of tagged words. The B1 harness asserts this
against the served `.so`. The v3 reader requires `forward_format_version ==
3`, `inplace_v3.version == 3`, `record_envelope_version == 2` (it then
decodes records as dv-v2, per-doc scale on), all nine side files with the
sizes above, and a valid header; anything else is a load error.

Overloading `forward_format_version` (until now the record-envelope version)
is deliberate: it is the only field every deployed reader checks. The
envelope version moves to `inplace_v3.record_envelope_version`.

---

## 5. Encoder (v2 → v3, zero patches)

Input: a COPY of the dv-v2 shard dir on local disk; output: a new dir
(must not exist). Steps, in order:
1. Validate the source manifest (`dotvbyte_fixedu8`, version 2, no knn).
2. Copy the eight index files of §1 verbatim.
3. Walk `posting_lists.bin` with the reader's alignment rules; for every
   word check bits 48..63 == 0 and START + LEN ≤ `forward_data_words`;
   record max START, max LEN and their bit widths (§2.3), and check each
   list's `block_offsets` against its posting count.
4. Compute `list_min.bin` (rayon over lists; one record decode per posting;
   the component must be present in the record, else abort).
5. Compute `list_crc.bin`; write `list_dir.bin` (native offsets, both
   banks), `posting_heap.bin` (sparse reserve), `posting_free.bin` (empty),
   `block_inflation.bin` (zeros, both banks), `forward_free.bin` (empty),
   `row_id_override.bin` (sparse zeros); scan the doc-mapping slab (all ids
   `W<digits>`, max < 2^63).
6. Write `manifest.json` (§4).
7. `fsync` every file and the directory; then write `inplace_header.bin`
   (§3.1), `fsync` it and the directory.
8. Return a JSON report (sizes, timings, spare-bit measurements).

## 6. Decoder (v3 reader)

`MmapSeismicIndexInplaceV3`: the dv-v2 reader's load path (same mmaps, same
`read_posting_lists`) plus the header, the inflation banks and the override
array. Traversal = the v2 traversal verbatim except:
- once per query: E = published epoch (§3.1), bank = E & 1;
- per query term: `list_dir` check (§3.6);
- per list: block dots from the unchanged summary code, then `d'` (§3.2)
  for the skip test and for the first term's sort order;
- per posting (both the prefetch pass and the scoring pass, both M8 paths):
  atomic load of the word, `visible(w, E)` check, masked START/LEN;
- per winner: `row_id_override` check before the doc-mapping slab.

Built as a new link in the patch chain (`spike/archive/inplace_update/patches/seismic_upstream_inplace_v3.patch`,
fork-local commit on `spike/seismic_upstream`), to a side path, loaded
explicitly by the harness. The served `.so` is never rebuilt or replaced.

## 7. What B1 tests (from plan 06, not restated as a bar here)

v3 decoder on the v3 copy with zero patches vs A0 (the served dv-v2 shard 0
through the served `.so`): top-k′ (k′ = 200) doc ids and f32 score bits, E8
recall-max params (all terms, query_cut = len(terms), heap_factor 0.8,
sorted first term), 460 queries QA ∪ QT ∪ QD; plus the addendum's per-query
cost of the masks and multiply (v3 vs v2 decoder, same build, same content).

## 8. Open points (not decided by this spec)

- Eviction and same-batch reuse: undo record vs refusal (updater).
- Tail append without re-mmap (pre-reserved mapped capacity).
- Epoch-tag reset cadence vs the 32,767 limit (compactor).
- Whether a per-list "all clean" flag should let the decoder skip the masks
  (would lower the measured cost; not built, so B1 measures the worst case).

---

## Revision 2026-09-29 — after coordinator review 2026-09-29

Source: `spike/archive/inplace_update/FORMAT_V3_REVIEW_2026-09-29.md` (R1–R9, N1–N6).
All accepted; none changes what B1 tests (zero patches). Where a rule below
conflicts with §1–§8 above, this revision wins. Only R4 and the `readers.bin`
file are in the B1 encoder/decoder build; everything else is an obligation on
the updater (DESIGN).

**R1 — recovery of an aborted batch (updater, before every batch).** Words
tagged `TAG > E` can only come from a batch that never flipped the header
(the single writer writes `TAG = E+1` only). Before starting a batch the
updater scans every posting word and neutralises them: FREE = 0 (aborted
insert into a slot that was dead at E) → set FREE = 1, TAG = E, START/LEN
left as written (the slot is dead at E either way); FREE = 1 (aborted delete
mark on a slot live at E; START/LEN were never touched) → set FREE = 0,
TAG = 0 (live base-equivalent). Then the inactive banks of
`block_inflation.bin` and `list_dir.bin` are recopied from the active banks
(R2), `list_min.bin` / `forward_free.bin` are rebuilt if their epoch ≠ E
(R5), and any `row_id_override.bin` entry of a row whose postings are all
dead at E is cleared. Skipping an epoch number is not a recovery (bank
selection is `E & 1`). Scan cost: one pass over 40.4 M words (323 MB) per
batch, *est.* < 1 s warm; unmeasured.

**R2 — `list_dir.bin` bank copy.** Same rule as the inflation banks (§3.2):
before writing the batch for e+1 the updater copies the active bank `e & 1`
into the inactive bank `(e+1) & 1`, then writes the changed entries. Without
the copy a list rewritten at e+1 would revert at e+2. Updater test required:
rewrite a list at e+1, publish e+2 without touching it, read it back.

**R3 — reader table replaces the fixed drain.** The "≥ 10 s drain" of §3.1
is **UNSAFE on this host** (measured query times 8–29 s, review R3) and is
withdrawn. Reuse rule: content freed at epoch f (a slot, a forward hole, an
inactive bank, a superseded A2b unit) may be overwritten only when every
active reader-table slot holds an epoch ≥ f. File `readers.bin`, created by
the encoder (16,384 B, zeros): 256 slots × 64 B `{u64 pid (0 = free), u64
epoch snapshot (u64::MAX = idle), u64 query-start ns, u64 heartbeat ns, 32 B
reserved}`. A reader claims a slot at load (CAS on pid), stores its E
(Release) before the traversal and u64::MAX after; the updater reads all
slots (Acquire) and treats a slot whose pid is not alive as free. DESIGN:
the B1 decoder does not claim slots (the two stores per query are not in
B1's mask-cost number; B3 must include them if built). B7's concurrent-reader
arm must include a deliberately slow reader.

**R4 — epoch bound (built, in the B1 decoder).** A header slot whose epoch
exceeds 32,767 (`V3_TAG_MASK`) is invalid (`slot_epoch` returns None), so
`visible()` is never evaluated against an epoch the 15-bit TAG cannot
express. The updater must refuse to publish epoch 32,768; a rebuild resets
all tags.

**R5 — side-file crash ordering.** `list_min.bin` and `forward_free.bin`
(and `posting_free.bin`) are written for e+1 BEFORE the header flip, each
stamped with epoch e+1 (`list_min` per entry bits 48..62, the free lists in
their header), and synced with the data. A reader of these files (only the
updater) trusts one only when its epoch equals the published E; otherwise it
rebuilds it by scan (minima: decode every live posting of the list; forward
free list: rows whose postings are all dead at E, minus rows with an
override; posting free list: units superseded at epochs ≤ min reader epoch).
Consequence: a crash after the side-file write but before the flip leaves
files stamped e+1 against E = e → rebuilt, never trusted; no double
allocation, no leak beyond one rebuild.

**R6 — writer I/O path.** The updater stores through a `MAP_SHARED`
read-write mapping of the same files the readers map (aligned 8-byte stores
for posting words, list_dir and override entries; 1-byte stores for
inflation codes; the header record as 16 stores with the checksum last),
then `msync(MS_SYNC)` (Windows: `FlushViewOfFile` + `FlushFileBuffers`). No
`pwrite`/`WriteFile` on mapped files. Local files only (04 addendum §D).

**R7 — posting-heap reuse (A2b, DESIGN).** A unit superseded at epoch f goes
to `posting_free.bin` once every reader-table epoch is ≥ f+1 (R3), instead
of waiting for compaction. B4 for A2b reports heap bytes per batch and
batches-to-exhaustion. The 1× reserve is *est.*; W1's per-list byte
distribution (`data/eval_results/inplace_writeunit_<date>.json`) sizes it.

**R8 — A2b read path cost (A2b, DESIGN).** A rewritten list needs its view
(EF offsets, bitfields, slices) built from the unit header. The decoder
caches views keyed by (list, unit offset) with a bounded cache, or B3 for
A2b reports the per-term build cost. B1 cannot observe it (every list is
native).

**R9 — row reuse vs the rest of the stack (updater design, open).** Not
checked here whether ordinals/livedocs (`src/lib/thinclient/ordinals.py`,
`delta_layer.py`), hotset sidecars or the E5 reorder map index by shard row.
If any does, row reuse (§3.4–§3.5) must be restricted or those maps updated.
Open until checked in code, before B6.

**Notes adopted.** N2: the publish is a 128-byte checksummed record (LMDB
pattern), not one 8-byte store. N5: FNV-1a-64 is a checksum, not a CRC.
N3, N4, N6 accepted as stated in the review.

---

## Revision 3 — 2026-09-29, after the updater design review (U1–U4) and plan 06 addenda (third, fourth)

Written before any B1 number exists; B1 is unchanged (the B1 build is fork
commit `a3173d1`, which only creates `readers.bin` as 16,384 zero bytes and
never reads it). Where this revision conflicts with anything above, it wins.

### 3.R1 `readers.bin` — the single reader table (replaces the R3 slot layout)

One file, one layout, used by the decoder, the updater crate and the Python
harness helper (the updater's `reader_table.bin` is withdrawn). 256 slots ×
64 bytes, 8-byte aligned words, little-endian, all accessed atomically:

| Word | Off | Field |
|---|---|---|
| 0 | 0 | `pid` of the owner (0 = free); claimed by CAS 0 → pid (SeqCst) |
| 1 | 8 | `pidns` = inode of `/proc/self/ns/pid` of the owner (0 = unknown) |
| 2 | 16 | `epoch` registered (u64::MAX = held but idle) |
| 3 | 24 | `lease` = last refresh, CLOCK_BOOTTIME ns |
| 4 | 32 | `boot` = first 8 bytes of `/proc/sys/kernel/random/boot_id` (hex-decoded) of the owner |
| 5 | 40 | `gen` = claim generation, incremented by the owner at each claim |
| 6 | 48 | query start, CLOCK_BOOTTIME ns (diagnostic) |
| 7 | 56 | reserved, 0 |

**Reader protocol.** Claim: CAS word 0 from 0 to pid; then store pidns,
boot, gen+1, lease = now, epoch = u64::MAX. Register: read E from the header,
store `epoch = E` (SeqCst), full fence, re-read the header; if the published
epoch changed, store the new E and repeat (store-then-load; the Dekker pair
with the updater's flip-then-scan). Refresh: the reader stores `lease = now`
at registration and again whenever at least 10 s have passed, checked once
per query term (≤ 64 checks per query). On every refresh it re-reads word 0
and word 5; if either changed its slot was reclaimed as stale and the query
fails (it can no longer prove content under it is protected). End of query:
store `epoch = u64::MAX`, then `pid = 0`.

**Lease length L = 120 s** (measured queries on this host reach 29 s; the
refresh interval is 10 s, so a live reader's lease is at most ~10 s + one
list's traversal old).

**Staleness rule (updater and any scanner).** A slot with `pid != 0` is
STALE iff `boot` differs from the scanner's boot id, OR `now − lease > L`.
Pid liveness may shortcut to STALE only when the slot's `pidns` is non-zero
and equals the scanner's own pidns and `kill(pid, 0)` returns ESRCH. A
different or unknown pidns never shortcuts. A scanner may free a stale slot
only by CAS on word 0 from the observed pid to 0 after re-reading word 5
unchanged. **Reuse gate:** content freed at epoch f may be overwritten only
when every non-stale slot with `epoch != u64::MAX` has `epoch ≥ f`.

CLOCK_BOOTTIME is chosen because it is system-wide (not per pid namespace),
monotonic, and counts suspend; `boot` makes slots from a previous boot
stale instead of eternally fresh.

### 3.R2 Writer I/O (replaces R6, answers U4)

Required: **reader-reachable words** (posting words, `list_dir` entries,
`row_id_override` entries, inflation codes, header records, reader-table
words) are written by aligned atomic stores through a `MAP_SHARED`
mapping. **Bytes no reader can reach at the published epoch** (forward
holes, heap units and tail records before their flip, side files read only
by the updater) may be written through the mapping or with `pwrite` on
Linux local files — one page cache, so either is coherent with the readers'
mappings; durability is `fsync`/`msync(MS_SYNC)` of the file either way.
On Windows the path must be the mapping for every byte (mapped views are not
coherent with `WriteFile`, 04 addendum §D). Results files name the path
used. No 9p/SMB/remote files.

### 3.R3 A2b unit header (corrects §3.6: 24 scalars, not 23)

`PostingListManifest` has 24 fields. Unit header, 256 bytes, little-endian:

| Off | Type | Field |
|---|---|---|
| 0 | u64 | magic `b"SFUL2B3\0"` |
| 8 | u32 | list id |
| 12 | u32 | epoch written |
| 16 | u64 | body bytes |
| 24 | u64 × 24 | scalars in declaration order: packed_postings_words, block_offsets_len, n_summaries, dim, has_component_ids (0/1), component_ids_len, values_len, minimums_len, quants_len, summaries_ids_field_width, summaries_ids_n_bits, summaries_ids_n_words, ef_high_bits_n_bits, ef_high_bits_n_words, ef_low_bits_field_width, ef_low_bits_n_bits, ef_low_bits_n_words, ef_low_len, ef_universe, ef_num_vals, inv_n_sets, inv_block_inventory_len, inv_subblock_inventory_len, inv_overflow_positions_len |
| 216 | u64 × 4 | reserved, 0 |
| 248 | u64 | FNV-1a-64 over header[0..248] ‖ body |

Unit offset (the `list_dir` value) = `len(posting_lists.bin)` + byte
offset in `posting_heap.bin`, 8-aligned. Body = the native slice sequence
with the native alignment rules relative to the body start (which is
8-aligned); body bytes = the scalars' walk length rounded up to 8.

**Decoder rules for a unit (built after B1):** the unit's own scalars are
authoritative (`n_summaries` may differ from the manifest: an emptied block
is removed); the checksum is verified once per (list, offset) and the view
is cached under that key (new offset = new key, never modified in place;
stale keys dropped only when neither bank names them); **inflation is not
applied** to a list served from a unit (A2b has no inflation byte: the
decoder uses an all-zero code slice of the unit's block count); `block_base`
of every list stays pinned to the manifest (the native lists' inflation
slices never move; a unit list's native inflation bytes are simply unused);
posting words inside a unit are v3 words (masks apply). A unit that fails
any check fails the query with an explicit error, never a partial read.

### 3.R4 Forward tail append (`+tail` variant) — DESIGN, decoder after the A2b read path

- **Region.** The v3.1 encoder extends `forward_data.bin` by
  `tail_reserve_words` zero words with `set_len` (sparse; *est.* default
  10 % of the base words = 48.2 M words / 385 MB apparent for shard 0, 0 B
  allocated) and records `inplace_v3.forward_tail = {base_words,
  reserve_words, reserve_rows}`; `forward_data_words` in the manifest stays
  the base count. The reader maps the whole file (base + reserve), so tail
  records need no re-mmap. Bump pointer = header field 64 (tail words
  used), published only by the header flip.
- **Rows.** Tail records are appended in order, so rows beyond the base
  extend the CSR monotonically: row `n_docs_base + j` spans
  `[offsets[n_docs_base + j], offsets[n_docs_base + j + 1])` with
  `offsets[n_docs_base] = base_words`. `forward_offsets.bin` is extended by
  `reserve_rows` sparse zero entries (`set_len`); the number of published
  tail rows is **header field 72** (0 at encode). The decoder resolves a
  winner's range with the vectorium `id_from_range` over the BASE slice
  `offsets[0..=n_docs_base]` when START < base_words, and by binary search
  over `offsets[n_docs_base ..= n_docs_base + tail_rows_published]` when
  START ≥ base_words (the unpublished zero entries are never searched).
- **External ids.** `row_id_override.bin` is extended by `reserve_rows`
  sparse entries; a tail row must carry an override (no slab string
  exists), else the query fails for that winner with an explicit error.
- **START values in the tail.** A posting may name a tail record only if
  it is published by the same flip as the record (A2: TAG = e+1; A2b: in
  the unit of the inactive `list_dir` bank). The decoder does not bound
  START per posting (the flip publishes both together); unit build and the
  updater's recovery scan check START + LEN ≤ base_words + tail words used.
- **Crash before the flip.** Tail bytes and rows beyond the published
  counters are unreachable: no visible posting names them (R1 recovery
  neutralises TAG > E words; the inactive `list_dir` bank is recopied), and
  the next batch writes from the published bump pointer, overwriting them.
- **Header record additions (within the reserved words):** field 64 =
  forward tail words used, field 72 = tail rows published. Both 0 at
  encode; covered by the existing record checksum.

---

## Revision 4 — 2026-09-29, reader-table slot aligned with the updater (supersedes 3.R1's word table)

The updater agent's proposal (relayed by the coordinator) is adopted; it
keeps the original R3 words 0–3 in place and fills the reserved words. The
protocol and reuse gate of 3.R1 stand with the field names below; only the
offsets, the clock and the lease default change. B1 unaffected.

| Word | Off | Field |
|---|---|---|
| 0 | 0 | `pid` of the owner (0 = free); claimed by CAS 0 → pid (SeqCst) |
| 1 | 8 | `epoch` registered (u64::MAX = held but idle) |
| 2 | 16 | query start, CLOCK_MONOTONIC ns (diagnostic) |
| 3 | 24 | `heartbeat` = last refresh, CLOCK_MONOTONIC ns |
| 4 | 32 | `pidns` = inode of `/proc/self/ns/pid` (0 = unknown) |
| 5 | 40 | `lease` length in ns (0 = the updater default, 600 s) |
| 6 | 48 | `boot` = first 8 bytes of `/proc/sys/kernel/random/boot_id` |
| 7 | 56 | `gen` = claim generation (owner increments at each claim) |

- **Clock:** CLOCK_MONOTONIC (system-wide, not per pid namespace; restarts
  at boot, hence `boot`: a slot whose `boot` differs from the scanner's is
  stale).
- **Staleness (updater):** clear a slot only when (`pidns` equals the
  updater's own AND `kill(pid, 0)` = ESRCH) OR (`heartbeat` ≠ 0 AND now −
  `heartbeat` > lease) OR `boot` differs. A slot with `pidns` = 0 and
  `heartbeat` = 0 is never cleared (the updater waits, then aborts on its
  reader timeout). Clearing is CAS on word 0 after re-reading `gen`.
- **Cost of the 600 s default:** a reader that died in ANOTHER pid namespace
  blocks reuse for up to 10 minutes. A live query longer than its lease
  without a heartbeat would be treated as dead — so the decoder refreshes
  `heartbeat` during traversal, checked once per query term (≤ 64 per
  query), whenever ≥ 10 s have passed since the last refresh, and writes
  `lease` = 0 (default). On a refresh it re-reads `pid` and `gen`; if
  either changed, the query fails.
- **Unit header (c):** revision 3's §3.R3 table is the canonical layout: 24
  scalars, offsets 24..216, in manifest JSON key order, which is the
  declaration order of `PostingListManifest` (`mmap_io.rs`); serde writes
  the keys in that order (checked against `posting_lists[0]` of the staged
  shard-0 manifest, 2026-09-29).
- **Writer I/O:** 3.R2 stands; the updater's path (MAP_SHARED + msync for
  every file a reader maps, `write()` only for files no reader maps) is
  within it.

---

## Revision 5 — 2026-09-29, live-index guard (owner requirement)

Added before the queued B1 job reached its encode step (the job was stopped
while still waiting for the latency lock, having written nothing, and
requeued after this revision). B1's tested behaviour is unchanged; its
encoder now also carries the guard (B1 build source = fork `c7b4b54` =
`a3173d1` + guard, patch `spike/archive/inplace_update/patches/seismic_upstream_inplace_v3_b1_guard.patch`;
the A2b line = `c704e5d`, patch `spike/archive/inplace_update/patches/seismic_upstream_inplace_v3_guard.patch`).

**Where the encoder's input copy comes from (§5).** The dv-v2 input is a
byte copy of the read-only source of record
`data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap` made by
`cp --reflink=never` of its nine index files into
`/home/vscode/work/inplace_update/stage1/v2copy` (local disk), sizes compared
and `manifest.json` byte-compared against the source; the source is only read
(never moved, renamed or written) and the copy is then made read-only
(`chmod a-w`). The served stage dir `/var/tmp/seismic_stage` is never read by
the copy step.

**Encoder guard (built).**
1. Output canonicalised; refused unless under `/home/vscode/work/inplace_update/`
   (and not equal to it); refused if it is, or is inside, `<repo>/data/`,
   `/var/tmp/seismic_stage`, or any `mmap_dir` named in
   `/var/tmp/seismic_stage/staged_manifest.json`,
   `data/thinclient_index/manifest.json` or
   `data/seismic_150m/index/plan01/manifest.json`; refused if it overlaps the
   input; refused if it already exists. The input is only opened for reading.
2. Sentinel `.inplace_work_copy` (JSON: canonical output path, canonical
   source path, FNV-1a-64 of the source `manifest.json`) is the first file
   written. The A2b fixture (and the updater, per its design) refuses any
   target without a sentinel naming that same canonical path.
3. Every copied file is a byte copy (read/write loop, no `copy_file_range`,
   no reflink, no hard link, no symlink), checked after the copy: regular
   file, `nlink == 1`, (device, inode) different from the source.

**Harness guard (built).** `spike/archive/inplace_update/guard.py`: every harness
process sets `SFU_SEISMIC_STAGE_DIR`, `SFU_META_STAGE_DIR`, `SFU_DELTA_ROOT`
to the empty string and compares a size + mtime listing of
`data/seismic_150m` and `/var/tmp/seismic_stage` with
`/home/vscode/work/inplace_update/baseline_20260929T2015Z/*.tsv` at start and
end (stage `staged_manifest.json` / `.staged_ok` excepted), aborting on any
difference; the reports go into the results files. The side-built `.so` is
extracted from its wheel into `stage1/so_v3` / `stage1/so_a2b` and loaded by
`sys.path` prepend with an assertion on `seismic.__file__`; nothing is
installed into or written under `.venv/`.

---

## Revision 6 — 2026-09-30, `+tail` as built (format v3.1: encoder, decoder, fixture)

Written 2026-09-30 by the encoder/decoder agent BEFORE the tail code was
written (the coordinator's brief of 2026-09-30, item 5). Implements §3.R4;
where a rule below differs from §3.R4 it is a deliberate deviation and is
listed under "Deviations". Nothing here changes the posting-word layout,
`list_dir`, `readers.bin`, or the header record beyond fields 64 and 72.
Test status: BUILT (fork `d7cbae1`, patch
`spike/archive/inplace_update/patches/seismic_upstream_inplace_v3_tail.patch`) and tested 2026-09-30 03:48Z,
`data/eval_results/inplace_tail_read_20260930.json` — synthetic tail fixture
vs native oracle PASS 460/460 (406 queries with a tail doc in the top-200),
shard-0 v3.1 zero-patch parity vs A0 PASS 460/460; details in
`STAGE1_ENCODER_FINDINGS.md` §"+tail read path". The tail WRITE side is the
updater agent's; its cost is unmeasured here.

**Naming.** "v3.1" = a v3 directory whose manifest carries
`inplace_v3.forward_tail`. `forward_format_version` stays 3 and
`inplace_v3.version` stays 3 (the v2 reader's rejection and the v3 decoder's
version checks are unchanged); the manifest additionally carries
`inplace_v3.minor = 1`. A v3.1 directory with zero tail rows decodes
identically to v3 (zero-patch parity, tested).

**Encoder options** (`convert_dv_v2_to_inplace_v3_with(src, dst,
heap_reserve, tail_reserve_words, tail_reserve_rows)`, pylib
`inplace_v3_convert(src, dst, heap_reserve=None, tail_reserve_words=None,
tail_reserve_rows=None)`):

- `tail_reserve_words` default = `base_words / 10` rounded UP to a multiple
  of 512 words (so the apparent end of `forward_data.bin` is 4 KiB
  aligned); `tail_reserve_rows` default = `n_docs / 10` rounded UP to a
  multiple of 512 entries. An explicit 0 for both gives the v3.0 layout (no
  extension; the key is still written with zero reserves). Shard 0
  (481,735,493 words, 18,799,322 docs): 48,173,568 words = 385,388,544 B
  apparent, 1,880,064 rows = 15,040,512 B apparent per extended array
  (numbers from the formula; the encode report of the v3.1 copy is the
  record).
- Extension by `set_len` AFTER the byte copy and the encoder's scans, so
  the copied prefix is byte-identical to the source (checked by the parity
  harness): `forward_data.bin` → `8 × (base_words + reserve_words)` B,
  `forward_offsets.bin` → `8 × (n_docs + 1 + reserve_rows)` B,
  `row_id_override.bin` → `8 × (n_docs + reserve_rows)` B (created at that
  size). No block is allocated for the reserve.
- Manifest: `forward_data_words` and `forward_offsets_len` STAY the base
  counts (`base_words`, `n_docs + 1`); new key
  `inplace_v3.forward_tail = {base_words, reserve_words, reserve_rows,
  offsets_entries_on_disk: n_docs + 1 + reserve_rows, override_entries_on_disk:
  n_docs + reserve_rows, tail_words_used_field: 64, tail_rows_published_field:
  72}`.
- Header fields (both slots, 0 at encode, inside the record's checksummed
  bytes 0..120): **tail words used = u64 at record offset 64** (file byte
  64 in slot 0, 4,160 in slot 1); **tail rows published = u64 at record
  offset 72** (file byte 72 / 4,168). Record offsets 80..120 stay reserved.

**Decoder (`MmapSeismicIndexInplaceV3`).**

- Load: `forward_tail` absent → `base_words = forward_data_words`,
  reserves 0 (a v3.0 dir loads unchanged). Size checks: `forward_data.bin`
  = `8 × (base_words + reserve_words)`, `forward_offsets.bin` = `8 × (n_docs
  + 1 + reserve_rows)`, `row_id_override.bin` = `8 × (n_docs +
  reserve_rows)`; `base_words` must equal `forward_data_words`.
- The wrapped dv-v2 reader's CSR view is the BASE prefix
  `offsets[0..=n_docs]` (`forward_offsets_len` entries) so `id_from_range`
  and `len()` (= `n_docs`) see only base rows; its data view is the whole
  mapped `forward_data.bin` (base + reserve), so `get_with_range` reaches
  tail records without a re-mmap. The v3 decoder keeps the full offsets
  slice for the tail search.
- Header slot validity adds: `tail words used ≤ reserve_words` and `tail
  rows published ≤ reserve_rows`, else the slot is invalid (a v3.0 dir has
  both 0 and reserves 0). `(E, tail words used, tail rows published)` are
  read from the SAME 128-byte record snapshot (16 `Acquire` loads, checksum
  verified) once per query at `begin_query`; the registration loop re-reads
  the whole triple until the epoch is stable.
- Winner resolution: START < `base_words` → the base CSR
  (`id_from_range`, unchanged); START ≥ `base_words` → binary search of
  START over `offsets[n_docs .. n_docs + tail_rows_published]` (the
  published tail starts; `offsets[n_docs] = base_words`), the hit `j` gives
  row `n_docs + j`, and `offsets[n_docs + j + 1]` must equal the range end,
  else the query fails with an explicit error (never a panic, never a
  silent row). Unpublished entries are never searched.
- External id of a tail row: `row_id_override.bin[n_docs + j]` must be
  non-zero, else the query fails with an explicit error (`doc_id_checked`;
  the pylib `search*` methods return that error instead of the numeric
  fallback used for base rows).
- Bound: the A2b unit build checks every unit posting `START + LEN ≤
  base_words + tail words used` of the epoch snapshotted for the query
  (previously `≤ forward_data_words`). Native posting words are not
  bounded per posting (§3.R4).
- New diagnostics: `inplace_tail_info()` → `(base_words, reserve_words,
  reserve_rows, tail_words_used, tail_rows_published)`; the existing
  `inplace_header_info()` tuple is unchanged.

**Fixture (`inplace_v3_tail_fixture(v3_dir, doc_ids, oracle_dir)`, Rust
`tail_fixture_append`), offline, on a work copy at epoch 0 with zero patches:**

1. Resolves each requested base doc id (slab string) to its row `r`; for
   the j-th one copies the record words `data[offsets[r]..offsets[r+1]]` to
   tail start `base_words + used` (pwrite; the record bytes are identical,
   so the dv-v2 decode and the score are bit-identical), sets
   `offsets[n_docs + j + 1] = base_words + used + len`, and sets
   `row_id_override[n_docs + j] = (1 << 63) | (max_base_id + 1 + j)` (a
   fresh `W<n>` id above every base id).
2. Walks every posting word of every list; every word whose START equals
   `offsets[r]` of a duplicated doc is rewritten (aligned 8-byte pwrite)
   to `TAG = 1, FREE = 0, START = its tail start, LEN unchanged`. So ALL
   postings of the base doc move: the base row `r` is unreachable at E = 1
   and the tail copy is visible exactly at E ≥ 1.
3. Publishes by writing header slot 1 = epoch 1, tail words used, tail
   rows = N (checksum last), after `fsync` of the data files; slot 0 stays
   epoch 0. Bank 1 of `list_dir` / `block_inflation` is what the encoder
   wrote (native / zero), so E = 1 serves every list natively.
4. Oracle: a dv-v2 dir carrying the same content natively: base forward
   words + the tail records appended (`forward_data_words` += used),
   `forward_offsets.bin` = base + N real entries, the doc-mapping slab
   extended with the N fresh ids, `posting_lists.bin` = the rewritten
   words with TAG cleared (v2 words), manifest = the v3 manifest without
   `inplace_v3`, `forward_format_version = 2`, `n_docs`, `forward_offsets_len`,
   `forward_nnz` updated. The base rows `r` remain in the oracle's forward
   with no posting, exactly as in the v3 copy.
5. Report: N, rows, fresh ids, tail words used, words repointed (total and
   per doc; a doc with 0 postings is refused), oracle path.

**Harness** `scripts/archive/inplace_update/eval_inplace_tail_read.py` (synthetic
160,347-doc shard, 460 queries, side build only, cores 8–15, no latency
lock; as built the zero-patch reference for the synthetic shard is the same
side build's v2 decoder on the unconverted copy, there being no served A0 for
it): baseline on the v3.1 copy at epoch 0 → choose the N = 64 base docs
that appear most often in the baseline top-200 lists → fixture → v3.1
decoder on the fixture (E = 1) vs the v2 decoder on the oracle: ordered
top-200 doc ids + f32 score bits identical on 460/460 = PASS; non-vacuity =
number of queries with ≥ 1 fresh (tail) id in their top-200 and number of
queries whose result changed vs the epoch-0 baseline, both must be > 0;
plus the epoch-0 baseline must equal the zero-patch results (v3.1 vs the
v2 decoder on the unconverted copy). Shard 0: zero-patch parity of the
v3.1 conversion of `stage1/v2copy` vs A0 (served `.so` on `stage1/v2copy`),
460/460, same as B1's definition.

**Deviations from §3.R4 (decided before coding):**

- D1 `forward_offsets_len` stays the base count and the wrapped reader's
  CSR is truncated to it (§3.R4 said only that `forward_data_words` stays
  the base count).
- D2 Reserve defaults are rounded up to 512-entry multiples (page-aligned
  apparent ends); §3.R4 said "10 %".
- D3 Header slots with tail counters above the reserves are INVALID (an
  added validity rule; §3.R4 had none).
- D4 A manifest without `forward_tail` is accepted as reserve 0 (backward
  compatibility with `stage1/v3` and the A2b line; §3.R4 assumed the key).
- D5 The fixture publishes epoch 1 (slot 1) and TAG = 1 on the repointed
  words rather than patching at epoch 0 like the A2b fixture; it does not
  update `list_min.bin` / `forward_free.bin` (updater-only, stamped epoch 0
  → R5 says rebuild, never trust).
- D6 The unit-build bound uses the tail words used of the query's
  snapshot; a cached unit keeps the bound it was built under (units are
  immutable and the bound only grows).
- D7 (found 2026-09-30 05:17Z, fork `328bf51`) The A2b fixture's oracle
  takes the BASE prefixes of `forward_data.bin` / `forward_offsets.bin`,
  never byte copies: a v2 reader given the sparse tail reserve panics in
  `id_from_range`. Rule for any oracle or v2 export of a v3.1 dir.
