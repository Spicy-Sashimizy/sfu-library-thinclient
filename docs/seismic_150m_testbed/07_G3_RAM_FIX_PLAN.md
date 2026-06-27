# 07 · G3 RAM-Fix Plan — getting SEISMIC off the anonymous heap

> **Status:** PLAN, executing (2026-06-27). G3 measured ❌ FAIL on Path A
> (RAM-resident, 912 B/doc → 137 GB @150M). This doc is the worklist to cure it.
> Numbers below are MEASURED unless marked `est.`. Cross-referenced against
> upstream + 2026 literature (sources at bottom). **Step A + C0 + C0.5 + C1a + C2 DONE**:
> no upstream on-disk mode (escape hatch closed; C0.5 shows the fork is *cheap* —
> mmap compressed-as-is, no POD restructure), C0 FORMAT-WALL **PASSED** (§4.1),
> C0.5 compressed-decode **PASSED at 1.07×** (§4.2 → both format hazards cleared),
> C1a FAILS on FLOOR (§4.3) but proved the borrow path is arithmetic-correct, and
> **C2 PASSES on FLOOR** (§4.4): the metadata-slab close drops the anon residual
> to +0.041 GB and dense fault-in moves 1.647 GB (96%) of the 1.708 GB index into
> reclaimable file cache, with parity ✓ and latency 0.97×. **G3 is structurally
> cured on the no-JVM Path C.** The G2 quality sweeps then ran (2026-06-27,
> `06_FINDINGS.md` §"G2 param-sweep" + §"G2 n_postings sweep"): overlap@10 is
> **frozen at 0.479** across BOTH pruning-lever axes — the per-list-cap axis
> (`max_fraction`/`doc_cut`/`summary_energy`) **and** the global-budget axis
> (`n_postings`, swept to the selection-saturated ceiling where every posting is
> selected). Per-query top-10 **bit-identical** across all configs → the 0.479 gap
> is the query-time approximation floor (summary-skip + in-block coordinate
> traversal), **not** posting retention; **no index-time knob reclaims it.** The
> G2 *quality* risk is now the live open problem (separate from the cured G3
> floor). Next: `centroid_fraction` (clustering density — not a posting-retention
> lever; untested, unlikely to move top-10), or the looser G6 RRF system gate;
> C2.5 (pyo3 loader) is deprioritized until quality clears.
> Path B (OpenSearch+SEISMIC) remains the documented fallback but is no longer the
> default.

---

## 0. The one-paragraph framing (read this first)

G3 "fails like BMP" only at the surface (both sit in anonymous RAM). The cause is
different and that difference is the whole reason this is fixable: **BMP's broken
axis was the algorithm** (pruning linear in corpus — storage can't fix that);
**SEISMIC's broken axis is only *where the bytes live*** (G4 proved its pruning is
sub-linear). A storage problem has a storage fix. This plan executes that fix and
brackets it against the two fallbacks.

---

## 1. What the measurement actually says (the byte breakdown decides everything)

From `data/eval_results/seismic_ram_floor_persona_2m.json` (2M med_bio index,
total on-disk 1.658 GB, ~100% resident as anon after load):

| Component | Bytes | % of index | Note |
|---|---|---|---|
| **summaries** (per-block 8-bit sketch vectors) | **731 MB** | **44%** | the elephant; already 8-bit quantized (see §3) |
| forward_index (docID → sparse vec) | 628 MB | 38% | the DotVByte target (see §3) |
| packed_postings | 275 MB | 17% | |
| block_offsets | 24 MB | 1% | |

Two conclusions fall straight out of the split and **both kill cheaper plans**:

1. **"mmap the forward index only" is DEAD.** `01_ARCHITECTURE.md` floated leaving
   the pruning side resident and mmap'ing only the forward index. But forward is
   only 38%; that leaves 62% (~85 GB @150M `est.`) anon. **Path C must mmap the
   WHOLE index**, summaries included.
2. **The summaries (44%) are the single biggest target** — larger than the forward
   index. Any fix that ignores them barely moves the floor.

---

## 2. Cross-referenced reality check (what changed after going to the sources)

Two assumptions from the prior session were **corrected** by checking upstream +
the 2026 papers. This is why the plan below is ordered the way it is.

| Prior assumption | Reality (2026-06-26, sourced) | Effect on plan |
|---|---|---|
| "Upstream may have shipped an on-disk/mmap mode (R-OBSOLETE) — could be free" | ❌ **Not shipped.** TusKANNy README documents only in-RAM variants (standard / compressed-DotVByte / LargeVocabulary). The ECIR-2025 paper still lists "indexes that cannot fit in main memory" as *future work*. | **Path C fork is still required.** The free escape hatch is closed (re-confirm before build — still cheap to recheck). |
| "Quantize the summaries — cheap build-side win on the 44%" | ⚠️ **Already done.** SEISMIC summaries are **8-bit scalar quantized by default**; defaults are summary-energy α=0.4 and centroids = 1/10 posting length. | No free summary win. Remaining build levers (α↓, n_postings↓) **shrink the floor but trade directly against G2 quality** — see the tension in §5. |
| (new, not previously known) | ✅ **DotVByte forward-index compression is already in the public Seismic library** (the "compressed" index variant): **12–22% forward-index reduction, latency within ~20%, negligible recall loss** (arXiv 2602.05445). | A genuine **free floor-reducer** to test (build flag, no fork). Modest (~12–15% of the 38% forward slab) and still RAM-resident, but stacks with Path C. |

---

## 3. The fix menu, cheapest → most work

### Step A — (free, ~30 min) Re-confirm no upstream on-disk mode + pin versions
The single cheapest possible cure is "upstream already did it." Confirmed *not*
shipped as of today, but re-check at build time (it's a logged R-OBSOLETE
obligation). Concretely:
- `pip index versions pyseismic-lsr` and read the changelog past 0.5.0.
- Re-fetch the README + `docs/` for any `mmap` / `from_file` / `on_disk` API.
- **Exit:** if a native on-disk loader exists → measure its RssAnon delta; if it
  cures the floor, **G3 is solved with zero fork** and Steps C/D are moot.

**RESULT (2026-06-26):** Step A done. Pinned to **`pyseismic-lsr` 0.4.0** venved
(dist-info), built from upstream commit `7782a13` (`v0.4.0-1-g7782a13`,
2026-04-08). The README documents exactly three in-RAM variants —
`SeismicIndex`, `SeismicIndexDotVByte` (the shipped compressed/DotVByte variant,
free lever from §2/Step B1), `SeismicIndexLV` (>65K vocab) — and **zero**
on-disk/mmap/`from_file` loaders; the only build path is `SeismicIndex.build(jsonl)`.
**Escape hatch stays closed → Step C fork remains required.**
(`n.b.` `measure_seismic_ram.py` and the persona JSON `meta.engine` string
say `0.5.0` — that is **stale**; the installed/build version is 0.4.0. A
docstring/version-string tidy is a trailing cleanup, not blocking.)

### Step B — (cheap, build-side) Free floor-reducers that need no fork
Rebuild the persona index with the shipped compression variant and measure the new
RssAnon floor (re-run `measure_seismic_ram.py`):
- **B1 — compressed/DotVByte variant** (forward index): `est.` 12–22% off the
  628 MB forward slab → ~75–140 MB saved → floor `est.` 912 → ~860 B/doc. Free,
  latency within ~20%.
- **B2 — summary-energy α sweep** (summaries are 44%): lower α below 0.4 shrinks
  the 731 MB summary slab the most of any single lever. **But α also drives G2
  recall** — this is the G2/G3 tension (§5), so sweep α jointly with the G2 harness,
  not in isolation.
- **Reality:** B-class levers **shrink** the floor; they do **not** cure it. Even a
  generous 25% total cut leaves ~103 GB @150M `est.` — still ≫ Qdrant's 6.55 GB.
  Their real value is (a) buying headroom and (b) shrinking whatever Path C must
  later mmap. **They are not a substitute for Step C.**

### Step C — (the real fix) Path C: mmap the WHOLE index, zero-decode
Fork SEISMIC's storage layer so **all four** components (forward + packed_postings
+ block_offsets + summaries) are written to immutable `memmap2` + `bytemuck` flat
files and read **zero-decode**. RAM floor → **~0 anon, page-cache-resident
(reclaimable)** — identical in kind to how tantivy already serves the lexical leg
(44.8 GB on disk, ~45 MB RSS). This is the only option that structurally cures the
floor (moves bytes from non-reclaimable anon to reclaimable file cache).

**Scope (set by the §1 split):** whole index, not forward-only. Substrate = raw
`memmap2`+`bytemuck` flat files (this project already measured that path at the
latency target: FORMAT-WALL flip 696 ms → 25.63 ms, `sparse_engine_project`
G1 / `R3v2_delta.patch`). Term dict = mmap'd `fst`. See `01_ARCHITECTURE.md` Path C
substrate table — `redb` is the fallback if hand-rolled offsets get painful.

**Two hazards to respect (both already logged):**
- **FORMAT-WALL (the make-or-break).** "mmap'd" ≠ "fast." Every hot structure —
  *especially the 731 MB of summaries the traversal scores first* — must be laid out
  zero-decode (`bytemuck::cast_slice` over the mmap), not a `take()`-materialize that
  re-creates the 696 ms decode. SEISMIC has more surface than BMP (summary vectors +
  clustered blocks + truncated postings + forward vectors), so more structures must
  be got right. **Note:** the shipped DotVByte forward format decodes-in-registers via
  SIMD — evaluate whether its compressed bytes can be mmap'd-and-SIMD-decoded (cache
  resident) vs. whether zero-decode `bytemuck` POD is the safer forward layout. This
  is a measured sub-decision inside Step C, not an assumption.
- **R-OWN.** A SEISMIC storage fork = the mmap layout + per-arch wheels + tracking
  upstream forever (G9 build-vs-buy). This is the real cost; weigh against Step D.

### Step D — (fallback) Path B: OpenSearch + SEISMIC
JVM, but **bounded heap = RAM cured today, no fork.** OS 3.3+ ships SEISMIC as a
Lucene sparse index; we already run OS 3.7. Loses the no-JVM goal but it *works*.
This is the honest bracket if Step C's ownership math doesn't close. Keep it warm as
the comparison, don't discard it.

---

## 4. Recommended sequence + decision gates

```
A. recheck upstream on-disk  ──found?──► measure floor ──cured?──► DONE (no fork)
        │ not found                                       │ no
        ▼                                                 ▼
B. build-flag floor-reducers (DotVByte + α sweep, w/ G2)  │
        │ measure new floor (still ≫ target, expected)    │
        ▼                                                 │
C. Path C spike: mmap WHOLE index, zero-decode  ◄─────────┘
   ├─ C0   FORMAT-WALL micro-bench on summaries (zero-decode vs take) ✅ 1.30× (§4.1)
   ├─ C0.5 real compressed-decode (EliasFano+BitField, the C0 caveat) ✅ 1.07× (§4.2)
   ├─ C1a  real-index mmap writer/reader integration gate — ❌ FAILS FLOOR (§4.3)
   │       parity ✓ + latency 1.01× hold; borrows ARE zero-copy for index bulk
   │       (~80% cured) BUT §6 anon≈0 NOT met: +0.186 GB metadata residual +
   │       43% slab fault-in. Cure gap = C2, not a format/algorithm failure.
   └─ C2  close the C1a gaps: mmap the metadata slab (flat doc_mapping string
         slab + dense fault-in via madvise(WILLNEED|SEQUENTIAL)) ✅ PASS (§4.4)
        │ anon residual +0.041 GB, file-resident 1.647 GB / 1.708 GB (96%).
        ▼
D. G2 quality sweep + Python mmap-loader integration (C2.5)
   Fallback (only if C2 had failed): Path B OpenSearch+SEISMIC — RAM cured, lose no-JVM
```

**The cheapest *informative* next run is C0** — a FORMAT-WALL micro-benchmark on the
summary structure alone (44% of the floor, the hardest zero-decode surface). It
decides Path C feasibility for a fraction of the full-fork cost. Do A and B first
(both near-free, hours not days), but C0 is the gate that says whether the no-JVM
goal lives or dies.

---

## 4.1 C0 RESULT — MEASURED 2026-06-26 (the gate is open)

Ran: `scripts/seismic_testbed/c0_format_wall_summary_bench.py`
→ `data/eval_results/seismic_c0_formatwall_persona.json`

**WHAT:** the FORMAT-WALL micro-bench on the summary structure in isolation
(§3 C0). Two readers over an identical faithful-shape summary slab, SAME fixed
work budget (30 queries × 64 terms, so the G4 pruning confound can't hide behind
corpus growth): TREATMENT = zero-decode (`np.frombuffer` re-cast over the mmap,
the Python analogue of `bytemuck::cast_slice`); CONTROL = per-query
`np.copy`/materialize (the re-creator of the BMP 696 ms wall). Cold via
`posix_fadvise(DONTNEED)` (`03_BENCHMARK_METHODOLOGY.md:42`). Parity assert:
zero-decode == materialize (arithmetic twins, like R3-v2 G1) — PASSES.

**NUMBERS (p50 / p95, ms):**

| reader | warm | cold |
|---|---|---|
| zero-decode (Path C cure) | **20.87** / 29.33 | **20.87** / 26.29 |
| materialize (FORMAT-WALL) | 28.99 / 33.52 | 27.22 / 38.52 |

FORMAT-WALL gap = **1.30×** (cold zero-decode beats cold materialize).
RAM after: RssAnon **0.037 GB**, RssFile **0.174 GB** (slab carried by
reclaimable file cache, anon ≈ 0 in kind — the cure shape holds).

**VERDICT: `C0 PATH_C_FEASIBLE`** — zero-decode holds the ~20% latency budget vs
warm materialize AND beats cold materialize by 1.30×. The make-or-break hazard
of §3 (a 731 MB summary slab decoded per query) does **not** rebuild the wall
when the layout is flat POD read zero-decode. **Proceed to C1**: build the mmap
writer/reader for all 4 SEISMIC components.

**Provenance caveat (bounds the result):** the slab is FAITHFUL-SHAPE, not real
SEISMIC summary bytes — pyseismic 0.4.0 exposes no per-block summary dump
(`QuantizedSummary` is private). It reproduces the upstream hot fields at the
right widths + access pattern (`values:u8`, `summary_ids`/`offsets` modeled as
flat u32 = the *best case* for zero-decode, since the real `EliasFano`/`BitField`
add per-query `select()`/fetch cost this bench does NOT pay). So C0 says "the
layout axis is decoupled in the best case"; the real compressed
offsets/summaries_ids decode cost is a C1 sub-decision to measure, not assumed
away. This is a latency/format bench, NOT a G2/recall bench (that is §5).

> **RESOLVED by C0.5 (2026-06-26, §4.2):** the real compressed-format decode
> cost (the caveat above) was measured and does **not** re-create the wall
> (1.07× the zero-decode floor, within budget). C0's best-case caveat is
> retired; see §4.2.

---

## 4.2 C0.5 RESULT — MEASURED 2026-06-26 (compressed format holds; R-OWN is cheap)

Ran: `spike/seismic_upstream/src/bin/c0_5_compressed_decode.rs` (real
`toolkit::EliasFano` + `BitField`, the exact upstream structs — *not* a
reimplementation)
→ `data/eval_results/seismic_c0_5_compressed_decode_persona.json`

**WHAT:** the C0 caveat — "the real `EliasFano`/`BitField` compressed formats
add per-query `select()`/`get_bits` decode cost C0's flat-u32 best case did NOT
pay" — measured directly. Three readers over an identical faithful-shape slab,
SAME fixed work budget (30 q × 64 terms):
- **COMPRESSED** = the upstream format: real `EliasFano.select()` per query term
  (`DArray.select1` block-inventory walk) + real `BitField.get_unchecked()` per
  value scored (shift/mask over the packed `BitVector`). This is the literal
  `QuantizedSummary::distances()` path (`quantized_summary.rs:64-160`).
- **ZERO_DECODE** = C0's flat-u32 floor (the best case).
- **MATERIALIZE** = the per-query-copy FORMAT-WALL control.
Parity assert: COMPRESSED == ZERO_DECODE (arithmetic twins) — PASSES.

**NUMBERS (release build, persona-scale slab matching C0, warm p50/p95, ms):**

| reader | warm p50 | warm p95 |
|---|---|---|
| compressed (real upstream) | **4.82** | 6.31 |
| zero-decode (C0 floor) | 4.51 | 5.17 |
| materialize (FORMAT-WALL) | 4.75 | 5.24 |

**COMPRESSED-vs-ZERO_DECODE = 1.07×** — the real compressed-format decode adds
only 7% over the zero-decode floor, **within the 1.2× budget**.

**VERDICT: `C0.5 COMPRESSED_HOLDS`** — `DArray.select1` + `BitField.get_bits`
per-query decode does **not** re-create the FORMAT-WALL on the real format. This
**retires C0's best-case caveat** and, decisively for the §3 R-OWN hazard,
**lowers the fork scope: the fork can mmap the compressed index *as-is* — no
POD restructure of `offsets`/`summaries_ids` required (cheap R-OWN)**, not the
expensive restructure-to-POD path the caveat left open. **Proceed to C1** with
the upstream compressed format preserved; the mmap layer is a *page-source swap*
(bytes anon → file cache), not a *format rewrite*.

**Why C0 (Python, cold page-fault axis) and C0.5 (Rust, decode-cost axis) are
complementary, not redundant:** C0 proved the page-fault/zero-decode-on-mmap axis
holds (cold 20.87 ms, gap 1.30× vs materialize); C0.5 proves the compressed-
*decode* axis holds (warm 4.82 ms, 1.07× vs flat). Together they cover both
hazards §3 names: "mmap'd ≠ fast" (C0, page faults) and "encoded bytes that
decode per query" (C0.5, compressed format). Both pass → C1 is de-risked on
format. **Neither is a G2/recall bench** (that's §5) and Neither is a real-index
end-to-end latency bench (that's C2/G5).

**Caveat that remains:** still FAITHFUL-SHAPE synthetic over real structs —
the workload is random-term, not the real query distribution, and there's no
true cold axis here (no mmap eviction; C0 owned cold). The real-index C2 run is
the final confirmation; C0.5 narrows the remaining risk to *integration* (can
the mmap file-cache swap be wired into `SeismicIndex` without breaking the
search path), not *format*.

---

## 4.3 C1a RESULT — MEASURED 2026-06-27 (borrow path works; §6 floor gate FAILS)

Ran: `spike/seismic_upstream/src/bin/c1a_mmap_index.rs` — the C0.5-deferred
*integration* axis: build the real mmap writer/reader for all four SEISMIC
components, run it over the REAL 2M persona index (`med_bio_2m.index.seismic`,
the same one `seismic_ram_floor_persona_2m.json` measured at 912 B/doc anon),
parity-assert vs the owned Path-A index, and measure the §6 floor (RssAnon≈0,
RssFile=index) + latency end-to-end.
→ `data/eval_results/seismic_c1a_mmap_persona.json`

**WHAT:** a standalone Rust spike (gitignored with the rest of `spike/`; the
owned `SeismicIndex` search path is untouched) with three additive fork pieces:
- `toolkit_fork`: `DArrayView<'a>` + `EliasFanoView<'a>` + `InventoriesView<'a>`
  (borrow-backed, the ONLY structurally-hard piece — `EliasFano.high_bits:
  DArray` was pinned to owned `BitVector` upstream; `BitField` could already
  borrow via `BitFieldGeneric<&[u64]>`). `EliasFanoView::select` is copied
  verbatim from `EliasFano::select`; parity-twin-unittest PASSES (toolkit's
  80 tests still green).
- `vectorium_fork`: `MmapSparseStorage<'a,E>` — borrow-backed `SparseStorage`
  for the forward index (38% of the floor).
- `seismic/src/mmap_index.rs` + `mmap_io.rs`: `MmapQuantizedSummary` /
  `MmapPostingList` / `MmapInvertedIndex` (borrowed, `distances()`/`search()`
  copied verbatim from `quantized_summary.rs:64-160` + `posting_list.rs`) +
  `write_mmap_index` (raw `bytemuck::cast_slice` flat files, NOT bincode) +
  `MmapSeismicIndex::from_mmap` reader.

**The four-phase bin (§6-honest, post floor-fix):** (1) load the owned bincode
index → Path-A floor RssAnon = **1.782 GB**; capture owned search reference +
warm latency; (2) `write_mmap_index`; (1.5) **drop the owned index + `malloc_trim`
→ RssAnon falls to baseline 0.007 GB** (proves the Path-A anon WAS the owned
index, cleanly freed); (3) build `MmapSeismicIndex`, `touch_slab()` to fault
in the four components, measure; (4) parity + latency + verdict.

**NUMBERS (release, real 2M persona index):**

| axis | result | §6 gate | pass? |
|---|---|---|---|
| **parity** (30 queries, owned == mmap) | doc_ids identical, scores within 1e-4 ε | must hold | ✅ |
| **latency** mmap warm p50 / p95 | **0.097 ms** / 0.205 ms | ≤ 1.2× path_a | ✅ |
| latency path_a warm p50 / p95 | 0.096 ms / 0.212 ms | (anchor) | — |
| `mmap_vs_path_a_lat_x` | **1.013×** | ≤ 1.2 | ✅ |
| **floor anon** (post-fault-in) | 0.193 GB = **+0.186 GB vs baseline** | ≈0 (≤ 0.085 GB) | ❌ |
| **floor file** (post-fault-in) | 0.741 GB = **43% of 1.71 GB index** | >50% of index | ❌ |

**VERDICT: `C1a FAILS_GATE — failing axis: FLOOR/ANON`** (and FLOOR/FILE).

**What the FAIL actually says (this is the important part — not a dead end):**
The mmap borrow path **works and is arithmetic-correct** (parity ✓ — the copied-
verbatim `distances`/`search` bodies produce bit-identical results; latency 1.01× —
the FORMAT-WALL C0/C0.5 de-risked did NOT re-emerge in integration). It cures
**~80% of the Path-A floor** (912 B/doc → ~93 B/doc anon, and 0.74 GB of the slab
moved into reclaimable file cache — vs 2.4 MB resident before the `touch_slab`
fault-in fix, which is what the first (wrong) C1a run measured). C1a's two
remaining gaps, both C2-scoped and neither a format/algorithm failure:

1. **+0.186 GB anon metadata residual.** The reader loads three things the borrow
   path does NOT mmap: the `document_mapping` (`Box<[String]>`, 2M entries), the
   `token_to_id_map` (`HashMap`, 27896 entries), and the `Box<[MmapPostingList]>`
   array (27896 entries). These are O(n_docs)/O(vocab) owned metadata, ~93 B/doc
   at 2M scale — far below Path A's 912 B/doc but NOT the §6 "≈0" target. **C2
   cure:** mmap the `document_mapping` as a flat UTF-8 string slab with
   `n_docs+1` byte offsets (no per-doc `String` allocation), keep the vocab-level
   `token_to_id_map` owned (<1 MB), and leave the `Box<[MmapPostingList]>` array
   owned (O(vocab), ~3 MB).
2. **43% slab fault-in (file-resident 0.741 GB vs 1.71 GB index).** The `touch_slab`
   4 KB-stride scan faulted only ~44% of pages; the kernel evicts hot pages under
   the scan. This is a **fault-in-strategy artifact**, not a structural floor
   problem — a denser sequential read or a `madvise(SEQUENTIAL/WILLNEED)` would
   fault the rest. Reported honestly: the §6 `RssFile≈index` gate is NOT met at
   this fault-in density; C2 must prove dense residency.

**Why this is a USEFUL fail, not a setback:** §3's R-OWN fork-scope question
("is the fork cheap — mmap-as-is, no POD restructure?") is **answered YES** —
the three forks are additive `*View`/`*Mmap*` types, the compressed byte format
is preserved, no POD restructure of `EliasFano`/`BitField` was needed (C0.5's
prediction held). The remaining work is metadata-slab mmap + fault-in tuning
(C2), NOT a fork redesign. The decision tree routes to **Step D (Path B)** only
if C2 *cannot* close the floor; Path B stays warm as the lever, not the default.

**Caveats:** (1) spike-only `Box::leak` of the `Mmap` into `&'static [u8]`
(documented in `mmap_io.rs`; a wired-in serve path uses `owning_ref`/`self_cell`).
(2) **2M is the persona scale, not 150M** — the §6 150M servability claim awaited
C2's real-scale run + projection. See §4.4: the metadata residual dropped to
+0.041 GB (mostly the O(vocab) posting-list array + token map, not O(n_docs)),
so the 150M projection is no longer a linear ~7 GB doc-mapping tail.
(3) Latency is warm-only here; C2 owns the cold axis (`posix_fadvise DONTNEED`).
(4) The 2.7M-bincode `path_a` warm p50 (0.096 ms) was measured right after load
without the mmap fault-in, so the mmap-vs-path_a comparison is fair (both warm,
same workload, same 90 samples).

---

## 4.4 C2 RESULT — MEASURED 2026-06-27 (metadata-slab close PASSES §6 floor gate)

Ran: `spike/seismic_upstream/src/bin/c2_mmap_metadata_close.rs` — close the two
C1a gaps over the same real 2M persona index.
→ `data/eval_results/seismic_c2_mmap_metadata_close.json`

**WHAT changed vs C1a:**
- `document_mapping` is no longer decoded into `Box<[String]>` (2M individual
  heap allocations, ~120 MB anon). It is now written as a flat UTF-8 bytes file
  (`document_mapping_strings.bin`) plus an offsets file
  (`document_mapping_offsets.bin`) and read zero-copy via a single mmap. A
  doc-mapping sanity sample (indices 0, n/2, n-1) passes against the owned map.
- `touch_slab` is rewritten from a per-list 4 KB-stride scan to a dense,
  file-by-file sequential pass with `madvise(WILLNEED|SEQUENTIAL)`. The first
  attempt used a plain `u64` accumulator and the compiler optimized away the
  loads (0.01s over 1.7 GB, RssFile unchanged); it now uses an `AtomicU64` per
  file so the reads are observable.

**NUMBERS (release, real 2M persona index):**

| axis | result | §6 gate | pass? |
|---|---|---|---|
| **parity** (30 queries, owned == mmap) | doc_ids identical, scores within 1e-4 ε | must hold | ✅ |
| **latency** mmap warm p50 / p95 | **0.041 ms** / 0.100 ms | ≤ 1.2× path_a | ✅ |
| latency path_a warm p50 / p95 | 0.043 ms / 0.081 ms | (anchor) | — |
| `mmap_vs_path_a_lat_x` | **0.971×** | ≤ 1.2 | ✅ |
| **floor anon** (post-fault-in) | 0.049 GB = **+0.041 GB vs baseline** | ≈0 (≤ 0.085 GB) | ✅ |
| **floor file** (post-fault-in) | 1.647 GB = **96% of 1.71 GB index** | >50% of index | ✅ |

**VERDICT: `C2 KEEPS_GATE — parity OK; floor cured`.**

**What the PASS actually says:** the no-JVM Path C is structurally viable. The
whole 1.71 GB persona index lives in reclaimable file cache (RssFile), while the
non-reclaimable anon floor is +0.041 GB — a **43× reduction** vs the original
Path-A 1.782 GB floor. The remaining anon is the small owned tail (token map +
`Box<[MmapPostingList]>` array), not O(n_docs). Per-doc anon at 2M is now
~21 B/doc; even if it scaled linearly with vocab/corpus bookkeeping it would
remain ≪ the 31.6 GB host budget at 150M.

**Next work from here (not in C2):**
1. **G2 quality sweep — DONE 2026-06-27** (see `06_FINDINGS.md` §"G2 param-sweep" + §"G2 n_postings sweep"):
   overlap@10 is **invariant at 0.479** across BOTH axes. Sweep #1 (`max_fraction`):
   1.5→5.0→10.0, `doc_cut` 15→1, `summary_energy` 0.4→0.9 (index 1.69→5.28 GB; per-query
   overlap bit-identical across configs). Sweep #2 (`n_postings`): 3500→7000→14000 to the
   **selection-saturated ceiling** (N3 budget 390.5M > 153M total postings `idx.nnz` → every
   posting selected; only the per-list cap still binds the hottest lists, and sweep #1 proved
   that cap irrelevant to top-10). Per-query overlap **bit-identical** to P0 (programmatic:
   N1==P0 AND N3==P0). Both pruning-lever axes are proven **inert** — the §5 tension's G2 side
   does not yield to either `max_fraction` or `n_postings`; the divergence is in the score
   approximation (summary-skip + in-block traversal), not posting-list retention.
   **G2 is not closed** — escapes remain (`centroid_fraction`, clustering density — not a
   posting-retention lever, untested, unlikely to move top-10; looser G6 RRF system gate).
2. **C2.5 Python mmap-loader integration** — expose `MmapSeismicIndex::from_mmap`
   through pyo3 so `measure_seismic_ram.py` can run the §6 measurement and the
   serving path can load mmap'd indexes directly. (Diminished priority now that
   G2 quality is the live risk, not the mmap floor — but still needed if G6/untested
   levers pass and Path C ships.)
3. **Cold-axis validation** — re-run with `posix_fadvise(DONTNEED)` on the mmap
   files to confirm the cold fault-in latency budget.

Path B (OpenSearch+SEISMIC) remains documented as a fallback but is no longer the
honest default: the no-JVM goal's floor problem is solved.

---

## 5. The tension you must hold (why tuning alone cannot win)

G2 recovery wants **more** postings / less pruning / higher α (bigger index → worse
G3). G3 wants **fewer/smaller** structures (→ risks worse G2). **You cannot tune
your way to both at Path A.** That is the proof the no-JVM goal is *structurally*
dependent on Path C: move the bytes to mmap so the floor stops mattering, then let
G2 spend its byte budget freely on quality. The α/n_postings sweep is the G2 lever;
the mmap move is the G3 lever; **they are different fixes and you need both.**

> **UPDATE 2026-06-27 (post-G2-sweeps #1 + #2):** the "spend the byte budget on quality"
> half of this was tested on BOTH lever axes and the G2 side did **not** cooperate. Sweep #1
> (`06_FINDINGS.md` §"G2 param-sweep", the per-list-cap axis) spent freely — `max_fraction`
> 1.5→10.0, `summary_energy` (α) 0.4→0.9, `doc_cut` 15→1, index 1.69→5.28 GB — and overlap@10
> stayed frozen at 0.479 (per-query bit-identical). Sweep #2 (§"G2 n_postings sweep", the
> global-budget axis — `n_postings` to the selection-saturated ceiling where every posting is
> selected): overlap@10 again frozen at 0.479, per-query **bit-identical** to P0. So the
> tension framing holds in the *G3 direction* (smaller index → flat-or-worse G2) but **the G2
> direction does not yield for free on EITHER axis**: no index-time pruning/approx knob recovers
> quality. The G2 escape, if any, is `centroid_fraction` (clustering density — not a
> posting-retention lever; untested, unlikely to move top-10) or the looser G6 system gate —
> not any axis §5 named. This *strengthens* the Path-C-is-the-fix story for the **G3/RAM axis**
> (which C2 solved) and *separates* the quality risk as its own open problem (now a query-time
> approximation floor, structural to SEISMIC's block-summaries design).

---

## 6. Exit criteria (when is G3 "fixed")

| | Target | Source of truth |
|---|---|---|
| RssAnon delta after load | ≈ 0 (page-cache/RssFile carries the index) | `measure_seismic_ram.py` re-run |
| Per-doc anon floor | ≤ Qdrant-class O(10s) B/doc, not O(100s) | same |
| 150M projection | servable on the 31.6 GB host (anon ≪ RAM) | projection in the probe |
| Latency not regressed by the format | within ~20% of in-RAM Path A | FORMAT-WALL bench / G5 |
| G2 not sacrificed to get there | overlap@10 unchanged vs the chosen build config — **CONFIRMED unchanged at 0.479 across the param sweep (2026-06-27)**, i.e. the storage move traded nothing for the floor, but 0.479 itself remains below the 0.95 B1 bar (a separate, open quality problem, not a G3 exit criterion) | `eval_seismic_parity.py` + `g2_param_sweep.py` |

G3 is fixed only when **anon ≈ 0 AND latency held AND G2 not traded away** — all
three, measured, same config.

---

## 7. Sources (cross-referenced 2026-06-26)

- TusKANNy/seismic README — confirms in-RAM variants only, **no mmap/on-disk mode**:
  https://github.com/TusKANNy/seismic/blob/main/README.md
- SEISMIC (SIGIR 2024) "Efficient Inverted Indexes…" — blocks + summary vectors,
  **8-bit quantized summaries**, α=0.4, centroids=1/10: https://arxiv.org/pdf/2404.18812
- Scalability to 138M (ECIR 2025) — pruning validated at scale; **"indexes that
  cannot fit in main memory" still future work**: https://arxiv.org/pdf/2501.11628
- **Forward Index Compression for LSR (arXiv 2602.05445)** — **DotVByte shipped in
  public Seismic**, 12–22% forward-index reduction, latency within ~20%:
  https://arxiv.org/html/2602.05445
- Superblock-based sparse retrieval (arXiv 2602.02883) — adjacent efficiency work to
  watch: https://arxiv.org/html/2602.02883
- This project's own evidence: `data/eval_results/seismic_ram_floor_persona_2m.json`
  (the split), `sparse_engine_project` FORMAT-WALL flip 696→25.63 ms (`R3v2_delta.patch`).
