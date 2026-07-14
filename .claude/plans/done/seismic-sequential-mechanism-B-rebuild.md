# Plan: Sequential path mechanism (B) — the .so rebuild (parallel path stays working)

**Context (user, 2026-06-30):** "the parallel path is currently on pause — you can
rebuild while making sure afterwards the parallel path is still working while you
work on the sequential path." I.e. the door is open to the `.so`-rebuild-dependent
work I previously deferred: mechanism **(B) `MADV_DONTNEED`** — release each shard's
pages after its search so the ~1-shard resident bound under sequential serving is a
**hard guarantee**, not "kernel-might-reclaim." The non-negotiable: the parallel path
must keep working afterward.

## Feasibility confirmed by code read

- `PyMmapIndex` (pyclass, `mmap_index.rs:53`) holds a `MmapSeismicIndex` which stores
  every component as a `&'static [u8]` leaked from `memmap2::Mmap` (`leak_mmap`).
- `touch_slab` already calls `libc::madvise(ptr, len, MADV_WILLNEED|SEQUENTIAL)` via
  the existing `touch_bytes` helper (`mmap_io.rs:749`) — **`libc` is already a dep**,
  no new dependency needed. A `release_pages` mirror calling `libc::MADV_DONTNEED` is
  ~15 lines following the IDENTICAL safety reasoning (`bytes.as_ptr() as *mut c_void`).
- `MADV_DONTNEED` discards clean resident pages but keeps the virtual mapping → a
  later `search` re-faults from the file and returns correct data (the `madvise(2)`
  contract, cited in `05_RESEARCH_SOURCES.md`). `search_raw` reads through the same
  leaked slices, so this is safe.
- Build: `maturin develop` (maturin 1.14.1 in the venv) rebuilds `libseismic.so` and
  drops it into `.venv/.../site-packages/seismic/`. No new infra.

## Non-disruption to the parallel path (the core requirement)

Mechanism (B) is **strictly additive** to the shared `.so`:
- NEW pyo3 method `PyMmapIndex.release_pages(&self) -> u64` on the mmap reader ONLY.
- `ParallelSeismicBackend` NEVER calls it → its `search` path is unchanged in
  behavior (the index object, the mmap, the search_raw call — all byte-identical).
  The `.so` rebuild is the only shared-artifact change, and parallel results depend
  on `search`/`new`/`touch_slab`, none of which I edit.
- The release is SEQENTIAL-class-local: `SequentialSeismicBackend._fan_out` calls
  `idx.release_pages()` after each shard's search (guarded with `hasattr` so the
  connonical mmap reader API isn't assumed; stock shards / old .so → no-op fallback,
  described in a log line, never a raise). Parallel's `_fan_out` is untouched.
- The C1/C2 doc-mapping GOTCHA (converted shards MUST be C2-layout) is unchanged —
  release_pages operates on whatever slices `MmapSeismicIndex` already holds.

## Changes

### 1. `spike/seismic_upstream/src/mmap_io.rs` — `MmapSeismicIndex::release_pages`
Mirror `touch_slab`'s structure: walk each file-backed slice the reader holds
(forward offsets/components/values, `posting_lists.bin`, doc-mapping strings/
offsets), and `libc::madvise(ptr, len, MADV_DONTNEED)` each. Return a byte count
(non-zero ⇒ the call covered real ranges) for parity with `touch_slab`'s
checksum-style contract. Reuse a `release_bytes(&[u8])` helper mirroring `touch_bytes`
minus the fault-in read (DONTNEED only). Doc-comment cites `madvise(2)` + the design
doc + the spike-only-leak safety note.

### 2. `spike/seismic_upstream/src/pylib/mmap_index.rs` — expose `release_pages`
Add `pub fn release_pages(&self) -> u64 { self.idx.release_pages() }` to the
`#[pymethods] impl PyMmapIndex`, with a docstring (drops resident pages of this
shard's mmap footprint; subsequent searches re-fault from file → results unchanged;
mechanism B for `docs/seismic_sequential_serving/`). Purely additive — `search`/
`new`/`touch_slab`/getattr untouched.

### 3. `src/lib/thinclient/sharded_seismic_backend.py` — call it from sequential only
In `SequentialSeismicBackend._fan_out`, after each shard's `_search_one(idx)`,
`if hasattr(idx, "release_pages"): idx.release_pages()` (guarded → stock shards /
older .so skip cleanly via a debug log, never raise). `ParallelSeismicBackend._fan_out`
is NOT modified — the non-disruption contract. Docstring notes mechanism (B) now
/shipped (was: "future hook").

### 4. `scripts/tests/test_seismic_sequential.py` — mechanism (B) guard
Add a test (skips without the toolchain, like the T1 fixture): build+convert a
shard, search it sequentially twice — the result of the 2nd search MUST equal the
1st (re-fault after DONTNEED returns identical data — the safety property). Plus
assert `hasattr(MmapSeismicIndex, "release_pages")` so a stale .so fails loudly.
(A RAM-drop assertion needs the 150M box + a RAM probe — that's bench-time, not
unit-test; noted as design-only here, same as T2/T3.)

### 5. Docs + memory (same-commit)
- `01_ARCHITECTURE.md`: mechanism (B) flips from "unimplemented future hook" →
  "SHIPPED for the sequential class" (parallel still doesn't use it).
- `00_VISION`/`README`/`docs/README` index: status stays IMPLEMENTED, mechanism A+B
  now shipped; efficacy still unmeasured (150M latency); mechanism (C) mlock still
  design-only.
- Memory `seismic-sequential-serving-shipped.md`: B/C "deferred" line → B shipped.

## Verification (the "parallel path still works" proof)
1. `maturin develop` rebuilds the .so (cargo release).
2. `pytest scripts/tests/test_served_seismic_path.py` (4/4 — parallel path + served
   gates; proves the rebuild didn't change parallel behavior).
3. `pytest scripts/tests/test_seismic_sequential.py` (T1 bit-identical + new
   mechanism-B re-fault test + cascade guard + selector).
4. Import smoke: `seismic.MmapSeismicIndex` has `release_pages`.

## Git workflow (per CLAUDE.md)
Pull → edit each file → stage ONLY that file → commit → push. The `.so` itself is a
build artifact (not committed); the venv .so is replaced by `maturin develop`. (The
`target/` build cache is multi-GB runtime state — never staged.)
