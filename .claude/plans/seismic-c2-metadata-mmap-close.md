# Plan: SEISMIC testbed — C2 close the C1a metadata floor gaps

Branch: `spike/mmap-bmp`
Owner: Claude Code
Date: 2026-06-27

## Context and why C2 (not G2) is the next highest-value step

C1a measured a **FAILS_GATE** verdict on the §6 floor axis (`RssAnon ≈ 0`).
However, the useful finding was that the structurally hard part of the SEISMIC
mmap fork is *already done*: toolkit `DArrayView`/`EliasFanoView` (the piece the
`c1-mmap-fork-scope` memory still lists as a deferred "BLOCKER") is built,
parity-proven, and the `MmapSeismicIndex` search path produces bit-identical
results at 1.013× latency over the real 2M persona index.

The two remaining gaps are both **metadata/surface artifacts**, not format or
algorithm failures:

1. **+0.186 GB anon metadata residual** — dominated by `document_mapping: Box<[String]>`
   (2M individual String heap allocations). It is O(n_docs); uncured it projects
   to ~7 GB @150M. It is also **not on the search hot path** (`search_raw` resolves
   doc IDs via `forward.id_from_range`, not the map), so curing it is pure floor
   accounting with zero quality/latency risk.
2. **43% slab fault-in** — `touch_slab`'s 4 KB-stride scan only faults ~44% of
   pages because early pages are evicted while later ones are faulted in. A denser
   sequential pass fixes this.

C2 is decision-dispositive for the no-JVM goal: if it closes the floor, Path C
wins and Step D (OpenSearch+SEISMIC, lose no-JVM) stays only a documented
fallback. G2 (α/n_postings sweep) is more valuable *after* the floor is moved to
mmap, because tuning before the floor is movable means optimizing against a
constraint that is about to disappear (07 §5).

## Scope of this plan

Implement the C2 cure in Rust, re-measure the §6 floor on the real 2M persona
index, and record the result. **Python exposure of the mmap loader** (so
`measure_seismic_ram.py` can run it) is intentionally a follow-up (C2.5) — C2
stays focused on the floor-close. The plan doc will be updated to clarify this
ordering.

## Proposed implementation

### 1. Metadata-slab mmap for `document_mapping`

Current (C1a):

```rust
// spike/seismic_upstream/src/mmap_io.rs:352
doc_mapping: Option<Box<[String]>>,
```

The C1a writer serializes this as a `Vec<String>` via bincode; the C1a reader
decodes it back into 2M `String`s, each with heap overhead. On disk:
`document_mapping.bin` is 38 MB; in RAM it costs ~90–120 MB because every String
is a 24-byte struct + allocation header.

Change:

- Add a new flat file `document_mapping_strings.bin` written as the concatenation
  of all doc IDs' UTF-8 bytes (no per-string heap allocation on read).
- Add `document_mapping_offsets.bin` as a `&[usize]` slab of
  `(start, end)` offsets per doc.
- In `MmapSeismicIndex::from_mmap`, mmap both files and hold:
  `doc_strings: &'static [u8]` and `doc_offsets: &'static [(usize, usize)]`.
- Provide `MmapSeismicIndex::doc_id(doc_idx) -> Option<&str>` returning a
  string slice directly from the mmap without allocation.
- Keep `Box<[String]>` out of the struct entirely.

This removes the O(n_docs) per-doc allocation tail from anon RAM. The token map
remains a small owned `HashMap` (~628 KB on disk; O(vocab)).

### 2. Dense fault-in / reclaimability

Current (C1a):

```rust
pub fn touch_slab(&self) -> u64 {
    // per-list chunked reads at 4 KB–8 KB strides across four components
}
```

The per-list stride pattern only achieves 43% RssFile because the kernel evicts
early pages while later pages are being read.

Change:

- For each mmap'd file (`forward_offsets.bin`, `forward_components.bin`,
  `forward_values.bin`, `posting_lists.bin`, `document_mapping_strings.bin`,
  `document_mapping_offsets.bin`), call `madvise(mmap.as_ptr(), len, MADV_WILLNEED)`
  followed by `MADV_SEQUENTIAL` (advisory) before a single dense reducing pass
  over the entire byte range.
- Do the pass file-by-file, not interleaved per-posting-list, to keep each file's
  pages resident long enough for the kernel to account them as `RssFile`.
- Keep a checksum-style accumulator so the reads are not optimized away.

Goal: RssFile ≈ index size (>90%) after `touch_slab`.

### 3. Add `c2_mmap_metadata_close.rs` bin

Mirror C1a's four-phase measurement, same JSON schema, but with the C2 reader
and dense fault-in:

1. Load owned Path-A `SeismicIndex`.
2. Run deterministic persona queries for parity reference + owned warm latency.
3. `write_mmap_index` (new flat doc-mapping layout).
4. Drop owned index + `malloc_trim` until RssAnon baseline is stable.
5. Build `MmapSeismicIndex::from_mmap`.
6. Dense fault-in.
7. Measure RssAnon/RssFile.
8. Run same queries through mmap, assert parity, measure warm latency.
9. Emit `data/eval_results/seismic_c2_mmap_metadata_close.json`.

Gates (same as C1a):

- parity_ok == true (doc_ids identical, scores ε < 1e-4).
- floor_anon_ok: |RssAnon_delta| < max(5% index_size, 0.1 GB).
- floor_file_ok: RssFile_resident > 50% of on-disk index size.
- latency_ok: mmap_p50 ≤ 1.2 × path_a_p50.

Expected improvement vs C1a:

- floor_anon_delta drops from +0.186 GB to ≲ +0.05 GB (mostly the `Box<[MmapPostingList]>`
  array + token map).
- floor_file_ok flips from false to true.

### 4. Update `07_G3_RAM_FIX_PLAN.md`

Add §4.4 (C2 RESULT) with:

- What changed vs C1a.
- Measured numbers and the new verdict.
- The 150M projection if floor cured.
- Path-B fallback decision: if C2 passes, proceed to G2 and Python integration;
  if C2 still fails, the §4 tree routes to Step D.

Also fix the stale claim in the doc that says C2 must use an `fst`-backed
`doc_map`. The flat string slab is sufficient; `fst`-backed compression is an
optional later optimization if the projected doc map becomes large, not required
for C2.

### 5. Update stale memory

`memory/c1-mmap-fork-scope.md` still lists `DArray`/`EliasFano` as a deferred
"BLOCKER" needing toolkit genericization. That work shipped with C1a. Correct
the memory to say it is **resolved** and C2's remaining blocker is the
metadata-slab mmap, not the toolkit genericization.

## Files touched

- `spike/seismic_upstream/src/mmap_io.rs`
- `spike/seismic_upstream/src/bin/c2_mmap_metadata_close.rs`
- `spike/seismic_upstream/Cargo.toml` (add `[[bin]]` entry)
- `docs/seismic_150m_testbed/07_G3_RAM_FIX_PLAN.md` (add §4.4, fix §3/§4 language)
- `data/eval_results/seismic_c2_mmap_metadata_close.json` (new result)
- `memory/c1-mmap-fork-scope.md` (correct the stale blocker claim)

## Out of scope (explicit)

- pyo3/Python exposure of `MmapSeismicIndex` — this is C2.5. C2's measurement
  comes from the Rust bin; `measure_seismic_ram.py` cannot run the mmap path
  until the pyo3 binding is added.
- G2 α/n_postings sweep — scheduled after C2 proves the floor can be moved.
- `fst` doc-map compression — not needed for C2. If the flat string slab at 150M
  is still too large, `fst` is a future lever.
- Re-running at 150M — host RAM limits this; C2 will extrapolate honestly from
  the 2M persona measurement as C1a did.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Dense fault-in still reports <50% RssFile because kernel accounting is per-page but pages are evicted | Single-file sequential pass; `MADV_WILLNEED` before; read the whole file once; no interleaving; report both `RssFile` and `Pss_File` if needed |
| Document mapping strings are not UTF-8 (upstream uses `String`) | Write UTF-8 bytes; on read, use `std::str::from_utf8`; assert for the spike; the persona data is UTF-8 doc IDs |
| Parity breaks because doc-map removal or new layout changes search path | doc_map is not used by `search_raw`; parity assert covers any accidental change |
| The `Box<[MmapPostingList]>` array itself becomes the new anon floor | It is O(vocab) (~28K entries, ~3 MB), not O(n_docs). Acceptable; if it shows up >0.05 GB we can move it into a borrowed slab too |

## Success criteria

C2 passes iff:

1. `seismic_c2_mmap_metadata_close.json` shows `parity_ok: true` and
   `latency_ok: true`.
2. `floor_anon_ok: true` (anon delta within 5% of index size or 0.1 GB).
3. `floor_file_ok: true` (RssFile > 50% of index size after dense fault-in).

If (2) or (3) still fails, the result is reported honestly and §4 routes to
Step D.
