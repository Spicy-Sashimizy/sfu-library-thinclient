# Forking BMP to mmap (the only code change the spike needs)

> **CLOSED KILLED 2026-06-26** — SEISMIC federated mmap took the slot; evidence for docs/archive/sparse_engine_project/

Goal: make `bmp.Searcher` read its `.bmp` file via `mmap` instead of
`load_into_memory`, so `RssAnon` stays ~0 and the OS pages the index in/out as
reclaimable page cache. **Source-checked layout (`src/index/posting_list.rs`):
block-max is TERM-MAJOR and contiguous per term, so this is a buffer-source swap,
not an algorithm change** (see `docs/archive/qdrant_vs_lucene_assessment/ARCHITECTURE_EXPLAINER.md` §6).

## Isolation (do not break the serving MCP)
- Build into a **throwaway venv**, NEVER the project `.venv` (that one IS the MCP
  runtime; a forked wheel would shadow the real `bmp` used by `SFU_SPLADE_BACKEND=bmp`).
- Keep the clone + Rust `target/` under the scratchpad, not in this repo's git.

```bash
SCRATCH=/tmp/claude-1000/-workspaces-sfu-library-thinclient/<session>/scratchpad
python3 -m venv $SCRATCH/mmapbmp-venv
$SCRATCH/mmapbmp-venv/bin/pip install maturin
git clone https://github.com/pisa-engine/BMP $SCRATCH/BMP   # Apache-2.0
```

## The change
1. `Cargo.toml`: add `memmap2 = "0.9"`.
2. Index load (where the `.bmp` is currently read into `Vec<u8>` / deserialized —
   the `Searcher::from_path`/`load` path):
   - Replace the owning `Vec<u8>` buffers behind `BlockData::Raw(Vec<u8>)` /
     `Compressed(...)` and the forward-index/postings buffers with an `Mmap`:
     ```rust
     let file = std::fs::File::open(path)?;
     let mmap = unsafe { memmap2::Mmap::map(&file)? };   // &[u8] view, paged by OS
     // optional: mmap.advise(memmap2::Advice::Random) for the block-eval seeks
     ```
   - Have the deserializer build its structs as **zero-copy views/offsets into the
     mmap'd `&[u8]`** (slices), rather than `read_to_end` + owned `Vec`. The
     term-major `range_maxes` lists stay contiguous, so each is a sub-slice.
   - Keep the search code path unchanged — it already iterates per-term contiguous
     block-max runs and accumulates into a small block-score array.
3. `maturin build --release` → `pip install` the wheel into `$SCRATCH/mmapbmp-venv`.

## Validate
```bash
# STEP 1 (stock, serving venv) — record the baseline once:
.venv/bin/python3 spike/mmap_bmp/record_baseline.py

# STEP 2 (forked venv) — correctness + RAM + latency gates:
MMAP_BMP_SITE=$SCRATCH/mmapbmp-venv/lib/python3.11/site-packages \
  $SCRATCH/mmapbmp-venv/bin/python3 spike/mmap_bmp/compare_fork.py
```

## Status of the cheap probe (2026-06-25)
**Ran the "mmap the file + deserialize from the slice" probe. Outcome — measured:**
- **Build works:** maturin release build (nightly 1.98, pyo3 0.21.2, CPython 3.11;
  system python is 3.13 which pyo3 0.21 rejects — must pin
  `PYO3_PYTHON=<venv>/bin/python3`). Wheel: manylinux_2_34_x86_64.
- **G1 correctness PASS (50/50 byte-identical)** over the 5 1M-section shards
  (`BMP_LOAD=mmap`). So the mmap read path is faithful — risk R4 retired.
- **G2 RAM FAIL (RssAnon 1.86 GB on a 606 MB shard, with one Searcher live).**
  `bincode::deserialize_from` *unconditionally* materializes the nested
  `BlockForwardIndex.data: Vec<Vec<(u16, Vec<(u8,u8)>)>>` as owned anonymous RAM;
  reading from an mmap'd slice does not avoid that allocation. **The cheap
  buffer-source swap does NOT cure the anon floor — risk R2 confirmed.**

**Therefore:** the clean G2 win requires the **flat-layout rewrite** (bincode →
mmap-friendly layout + lazy per-block decode + a matching builder), i.e. risk R3
(invasive). The probe isolated exactly that — the anon bytes are deserialize
output, not `read()` output. Decide R3-vs-kill next; see
`03_GO_NO_GO_GATES.md` decision log.

## R3 flat-layout rewrite — DONE (2026-06-25), G2 CURED ✅

Committed to the rewrite. New modules in the fork (full patch at
`spike/mmap_bmp/R3_fork.patch`, applies clean to a fresh upstream clone):

- `src/index/flat.rs` — flat `.bmflat` format (header + per-block offset table +
  flat forward region + compact inverted region), `FlatIndex::open` mmap-backed
  reader, `get_block(i)` decodes one block transiently, `write_flat`
  transcoder (reuses the stock bincode loader as source — no corpus re-encode).
- `src/flat_search.rs` — mirrors `b_search_verbose` but calls `flat.get_block`
  instead of indexing an owned `forward_index.data[block]`; **`block_score` is
  reused unchanged → G1 identical-by-construction.**
- Python wiring: `bmp.transcode_to_flat(src.bmp, dst.bmflat)` +
  `Searcher(BMP_LOAD=flat)`.

**Measured (eval: `spike/mmap_bmp/compare_flat.py`, results in decision log):**
- **G1 PASS 50/50 byte-identical** (5 shards × 10 q, k=50).
- **G2 PASS — RssAnon peak 0.535 GB across all 5 shards** (vs 1.86 GB stock-mmap
  / 1.98 GB load-into-RAM), flat in corpus size. **The floor is cured.**
- **G3 degraded (signal, not HARD at P1):** p50 ≈ 67 ms vs stock 4.7 ms (~14×),
  p95 ≈ 330 ms. R1 decode + page-fault cost; 1M shards fit cache so this is
  decode/access overhead, not true cold-fault. P2 measures/mitigates.
- Disk bonus: flat 0.74–0.77× stock bincode size (880 MB vs 1165 MB across the 5).

The make-or-break R2 bet is **won**. Next gate: P2 cold-p95 at section scale
(build a persona-sized `.bmflat` from `spool_backup`, drop caches, measure).

## Cold-cache (G3) at section scale
The 1M shards (~113 MB) fit page cache, so they only test correctness+RAM+warm.
For the real cold-p95, build a persona-sized `.bmp` from `spool_backup` (the
builder is in `src/lib/thinclient/builder.py`) so it does NOT fully fit cache,
then before each cold pass:
```bash
sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'   # needs sudo (available per CLAUDE.md)
```
and compare cold p50/p95 vs warm and vs the live Qdrant `measure` numbers.

## If the fork is non-trivial
If zero-copy deserialization is too invasive for a spike, a cheaper first probe:
`mmap` the file and `madvise(WILLNEED)` then let the existing loader read from the
mmap'd slice — this won't get RssAnon fully to 0 but shows the cold-fault behavior.
The clean win needs true zero-copy views; budget accordingly.
</content>
