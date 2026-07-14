# C1a — SEISMIC Path-C mmap validation spike (full scope, incl. toolkit fork)

> Parent doc: `docs/seismic_150m_testbed/07_G3_RAM_FIX_PLAN.md` §4 gate C1.
> Predecessors: C0 (FORMAT-WALL, ✅ 1.30×) + C0.5 (compressed-decode, ✅ 1.07×) BOTH
> PASSED → C1 de-risked on *format*. C1a now measures the *integration* axis C0.5
> explicitly deferred ("can the mmap file-cache swap be wired into
> `SeismicIndex` without breaking the search path"), full scope per user decision:
> reach the §6 `RssAnon ≈ 0` target in one shot, including the toolkit fork.

## The fork-scope truth this spike validates (code-derived, 2026-06-27)

C0.5 said "lowers the fork scope: mmap the compressed index *as-is* — a
page-source swap, not a format rewrite." That holds for the **byte format**. The
per-component integration cost (read off the pinned upstream checkout
`spike/seismic_upstream`, toolkit@024acc4, vectorium@c484687):

| Component | % floor | Zero-copy path | Fork needed |
|---|---|---|---|
| `packed_postings` `Box<[PackedPostingBlock{u64}]>` | 17% | `bytemuck::cast_slice` | — (seismic read path already slice-accesses) |
| `block_offsets` `Box<[usize]>` | 1% | `bytemuck::cast_slice` | — |
| forward_index `SparseDatasetGeneric<E,S: SparseStorage<E>>` | 38% | `SparseStorage` trait is pluggable (`AsRef<[T]>` assoc types); add a borrow-backed `MmapSparseStorage` | vectorium-fork |
| `summaries` `QuantizedSummary` | 44% | `values/mins/quants/component_ids` flat POD ✅; `summaries_ids:BitField` ✅ toolkit already has `BitFieldGeneric<&[u64]>`+`from_raw_parts`; **`offsets:EliasFano`→`high_bits:DArray<false>`→`bv:BitVector` is pinned owned + `Inventories` owned `Box<[T]>`** | **toolkit-fork (the one real lift)** |

Free fallback (`IndexSerializer` bincode `save_index`/`load_index`,
vectorium lib.rs:156) is a **dead end**: serde-decode allocates every Vec →
re-materializes anon floor → defeats G3.

## Goal (the C2 gate, ahead of time)

Prove on the **real 2M persona index** (`data/thin_client_poc/seismic_idx.index.seismic`,
the same one `seismic_ram_floor_persona_2m.json` measured at 912 B/doc anon):

1. **Parity (correctness gate):** mmap'd index `search()` results == in-RAM
   `SeismicIndex.search()` results, same queries (arithmetic-identical, like
   R3-v2 G1 / C0.5 parity assert). Non-negotiable.
2. **Floor (the whole point):** RssAnon delta-after-load ≈ 0; RssFile ≈ index
   size (bytes moved anon→reclaimable file cache). vs Path A 912 B/doc anon.
3. **Latency held:** mmap p50 within ~1.2× of in-RAM Path A (the C0.5 budget).
4. **Exit criteria from 07 §6** (anon≈0 AND latency held AND G2 not traded — the
   last is §5/G2, out of scope here; C1a owns the first two).

## What I build (single Rust bin, the C0/C0.5 pattern)

`spike/seismic_upstream/src/bin/c1a_mmap_index.rs` (+ `[[bin]]` in Cargo.toml;
spike/ is gitignored like c0_5). Standalone — does NOT touch the serving venv or
the pylib bindings (validation spike, not wired-in serve yet; that's C1b/C2).

### Depends (add to spike-only Cargo.toml, accept the specialist caveat below)
- `memmap2 = "0.9"` (cached 0.9.11 in cargo registry — no network)
- `bytemuck = "1.23"` (cached 1.25.0; already transitive via vectorium)
- reuse existing: `toolkit` (git), `vectorium` (git rev=c484687), `serde_json`.

### The three forks (committed in `spike/seismic_upstream/` — a fork checkout, not upstream PRs)

**Fork 1 — vectorium: borrow-backed `MmapSparseStorage`** (cures forward 38%)
- Add `MmapSparseStorage<E>` impl `SparseStorage<E>` with
  `type Offsets=…/Components=…/Values=…` backed by `&[u8]` mmap slabs via
  `bytemuck::cast_slice` (offsets `&[usize]`, components `&[C]`, values `&[V]`).
  No mutation; mirrors `ImmutableSparseStorage` API surface exactly.
- Because vectorium is a **git dep** (`Cargo.toml` pins rev=c484687), the fork is
  a vendored `spike/vectorium_fork/` source-dep (path = ...) carrying this one
  struct + impl. Pin + reason in Cargo.toml comment, like the existing c484687
  pin note in the instrumented README.

**Fork 2 — toolkit: borrow-backed `DArray`/`EliasFano`** (cures summaries 44% offsets — the one real lift)
- `DArray` (darray.rs:82) currently owns `bv: BitVector` + `Inventories{box[...]}`.
- Add a `DArrayView<'a>` (or genericize `DArray<const S: bool, V=…>` minimally)
  whose `bv` is `BitVectorGeneric<&'a [u64]>` (toolkit already supports this —
  `BitSlice<'a>` alias + `from_raw_parts` exist) and whose `Inventories` borrow
  `&[i64]/&[u16]/&[usize]`. Re-implement `select` over the borrowed `bv` (the
  `SelectBin`/`select` body is storage-agnostic; it calls `self.bv.get_word`).
- Add `EliasFanoView<'a>` over it exposing `select(k)` (the only method
  `QuantizedSummary::distances` calls, quantized_summary.rs:85-86,128-129).
- Vendored `spike/toolkit_fork/` source-dep (toolkit is a git dep) — SAME pattern
  as the vectorium fork, SAME pin-and-reason comment.

**Fork 3 — seismic: `MmapInvertedIndex` + a `SeismicIndex::from_mmap`** (the wiring)
- A `MmapQuantizedSummary<C>` mirroring `QuantizedSummary`'s fields but with
  borrowed `BitField`/`EliasFanoView`/`&[u8]`/`&[f32]` over one `memmap2::Mmap`
  + per-component offsets; `distances()` body copied verbatim from
  `quantized_summary.rs:64-160` (only the field accesses change, the arithmetic
  is identical → that IS the parity argument).
- A `MmapPostingList` over borrowed `&[PackedPostingBlock]` + `&[usize]` +
  `MmapQuantizedSummary`; `search`/`sort_and_search` copied from posting_list.rs.
- A `MmapInvertedIndex` over `MmapSparseStorage` forward index +
  `Box<[MmapPostingList]>`, exposing `search(...)` matching
  `InvertedIndexBase::search`'s traversal (the G4-instrumented
  `search_inner` if we want the candidate count too, optional).
- **Writer:** `fn write_mmap_index(index: &SeismicIndex, dir: &Path)` that, from
  a built in-RAM `SeismicIndex`, serializes the four components to flat files
  (NOT bincode — raw `bytemuck::cast_slice`/`to_ne_bytes` runs, + a small
  manifest of offsets/widths; the compressed `EliasFano`/`BitField` serialize via
  their existing serde-to-bytes into contiguous file regions the reader maps).
  This is the "page-source swap" writer C0.5 predicted: format preserved.

### The bin (`c1a_mmap_index.rs`) — four phases, parity-gated
1. **Build in-RAM** the persona index via the existing build path
   (`SeismicIndex::from_json` over the persona SPLADE jsonl that
   `build_persona_seismic.py` produces — reuse, don't re-build infra).
2. **Write** the mmap flat layout with `write_mmap_index`.
3. **Drop** the in-RAM index (so anon frees), **mmap** it back via
   `SeismicIndex::from_mmap` (the fork's reader), keep one `Mmap` handle alive.
4. **Parity + measure:**
   - parity: run N persona queries through both the in-RAM index (rebuild or hold
     a second copy) and the mmap index; assert top-k doc_ids + scores
     bit-identical (allow float epsilon for the bytemuck-vs-Owned path — but they
     should be exact twins since distances() arithmetic is copied verbatim).
   - floor: read `/proc/self/status` RssAnon/RssFile before-load (baseline),
     after-mmap (the cure), vs the ram_floor_persona_2m.json Path-A numbers.
   - latency: timed query loop, warm + cold (`posix_fadvise(DONTNEED)` via
     `libc`/raw, the C0 cold axis) p50/p95, vs Path A.
- Result JSON → `data/eval_results/seismic_c1a_mmap_persona.json` (schema mirrors
  the C0/C0.5 result JSONs: meta + config + latency_ms{path_a, mmap}{warm,cold} +
  rss{anon,file} + parity_ok + c1a_verdict).

## Gate decision (written into 07 as a new §4.3)
- **C1a KEEPS_GATE if:** parity PASSES AND RssAnon-after-mmap ≈ Path-A-baseline
  (≈0 delta) AND mmap warm p50 ≤ 1.2× Path-A warm p50 → **proceed to C2**
  (wire into the pylib bindings + the `seismic_backend.py` serve path;
  re-run `measure_seismic_ram.py` for the official §6 anon number at persona +
  the projection to 150M).
- **C1a FAILS_GATE if:** parity fails (fix bug, this is a spike so cheap to
  retry), OR anon didn't drop (a borrow path is secretly copying — debug), OR
  latency > 1.2× (the FORMAT-WALL re-emerged in integration; re-examine which
  component, this is exactly what C0/C0.5 de-risked but C2 confirms). On floor
  or latency fail → the §4 decision tree routes to **Step D (Path B,
  OpenSearch+SEISMIC)** as the fallback; do NOT silently fall through.

## Docs (same-commit rule, CLAUDE.md binding)
- `07_G3_RAM_FIX_PLAN.md`: new §4.3 "C1a RESULT" (mirror §4.1/§4.2 structure),
  update the §4 decision-gate diagram + top status banner to "C1a done".
- `docs/README.md`: no new doc, but the fork-scope finding amends the 07 entry.
- This C1a is a SPIKE over the real index but still a new module → efficacy rule
  applies: record WHAT/NUMBERS/eval-script/results-file/ABSOLUTE DATE in §4.3.
  Unmeasured claims marked `*est.*`.

## Why this shape (not lighter, not heavier)
- **Single bin, not wired-in** keeps it a "fraction-of-full-fork-cost
  informative gate" — the C0/C0.5 methodology. C1b (wire into pylib + serve) only
  if C1a KEEPS_GATE, so a FAIL costs a day not a week.
- **The three forks are additive `*View`/`*Mmap*` types**, not rewrites of the
  owned structs → upstream-mergeable in principle (reduces long-term R-OWN),
  and the owned `SeismicIndex` search path is untouched (no risk to what serves
  today during the spike).
- **Parity via copied-arithmetic**, not a new algorithm → if it diverges, the
  bug is in the wiring (cast/offset), not logic, and is fast to localize.

## Open / risk
- The `DArray`/`EliasFano` borrow fork is the one technically novel piece
  (toolkit pinned to owned). C0.5 already measured the *decode cost* of the real
  `EliasFano.select` + `BitField.get_unchecked` at 1.07× — so the arithmetic is
  proven fast; C1a only adds "can we point it at an mmap slab instead of an owned
  Vec," which is a borrow-checker/layout problem, not a perf unknown.
- If vendoring the toolkit/vectorium forks as path-deps proves fiddly in the
  spike build, fallback: copy the two needed structs into the seismic fork
  (duplication, acceptable for a validation spike; note it).
- 150M is still projection; C1a runs at 2M persona size (the same size C0/C0.5
  and the ram floor used). The 150M servability claim awaits C2's real-scale run.
