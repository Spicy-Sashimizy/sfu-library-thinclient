# Storage-DB consolidation — feasibility & bespoke proposal

**Date:** 2026-08-04 · **Status:** aggregate of C1–C13 (all MEASURED) + a bespoke
proposal (DESIGN ONLY, UNMEASURED). Canonical running record is
`docs/seismic_150m_testbed/18_ORDINAL_ADDRESSING_DESIGN.md` §1–§21; this file is
the one-page synthesis and the C14 go/no-go.

**One-line result:** the thin client ships **four** storage databases;
`abstracts.sqlite` has been **removed** (SQLite-free serving, −1.92 GB, shipped);
`meta.sqlite` was chased to a full-scale number across every store shape and
**cannot be consolidated under the no-regression gate** — it stays. Reachable
target is **4 → 3**, not the 4 → 2 the C7/C8 pairing implied.

---

## 1. Every test, aggregated

The gate throughout: **byte-parity + no-regression vs staged SQLite on local
disk** (operator constraint 2026-08-03). Latencies are the 50-id hydration path
unless noted. Every row cites its results file under `data/eval_results/`.

| Test | Swapped | Size | Speed | Verdict | Results file |
|---|---|---|---|---|---|
| Search structures (§1, 1000 ids @150M) | how a sparse W-id is resolved | — | SQLite B-tree **400.8 ms** · tantivy FST 897.7 ms · Lance BTREE **255.1 ms** | all *search*, none *address* | `c1_production_scale_*` |
| **C1** | `meta.sqlite` → tantivy stored + fast fields | neutral | 2.6× worse @1000 ids | ❌ not adopted | `c1_meta_lookup_*`, `c1_pushdown_*` |
| **N7 / §14** | `meta.sqlite` 9p → local disk | — | 222 → **4.0 ms** (55×, no code change) | filesystem was the cost | `n7_fs_control_*` |
| **§12 ordinals** | filter columns → mmap arrays | 24.9 GB → **1.96 GB** resident | filter stage 4.0 → 1.5 ms | ✅ **space lever (filters only)** | `n3_ordinal_build_*`, `n4_postfilter_*` |
| **N5** | abstract payload → flat `blocks.bin` | −2.2 GB | 2.89× (9p) / 1.21× (disk) | ✅ shipped | `n5_flat_blocks_*` |
| **C8** | abstract locator → ordinal arrays | −1.90 GB | 5.53× p50 (**cold-cache**) | payoff real, magnitude inflated | `c8_abs_locator_*` |
| **C9** | ↑ through the *shipped* `fetch()` | −1.90 GB | **1.18×**, no regression, parity | ✅ shipped | `c9_locator_reader_*` |
| **C10** | serve with `abstracts.sqlite` **deleted** | −1.92 GB | 1.19×, `_db=None`, parity | ✅ **abstracts REMOVED** | `c10_sqlite_free_*` |
| **C5** | `meta.sqlite` → **Lance** (scalar index) | 1.73× smaller | **1.15–1.72× slower** | ❌ rejected | `c5_lance_vs_sqlite_*`, `c5_lance_real_titles_*` |
| **C7** | meta title/DOI → perdoc-zstd (**1M sample**) | −10.22 GB | 0.70× (**page-cache artifact**) | misleading — see C11 | `c7_meta_flat_*` |
| **C11** | ↑ at **full 150.4M** | −10.64 GB | **28.7 ms = 87× slower** | ❌ dead | `c11_meta_store_20260804_0031` |
| **C12** | full bake-off (raw / perdoc / Lance-`take`) | raw 17.68 · perdoc 12.32 · **Lance 10.80** GB | raw 2.3× · perdoc 7.2× · **Lance 21×** slower | ❌ all fail the gate | `c12_lance_bakeoff_20260804_0046` |
| **C13** | **Vortex** | **9.31 GB (best of all)** | **12.14 ms = 27× (worst of all)** | ❌ fails the gate | `c13_vortex_bakeoff_20260804_0159` |

**Consolidation scorecard:** `abstracts.sqlite` **removed** (4 → 3);
`meta.sqlite` **stays**; `dense/ids.json` + `dense/delta.sqlite` unbuilt /
likely-unreachable.

---

## 2. Why `meta.sqlite` cannot be consolidated — five root causes

1. **The baseline is a fast, uncompressed, warm read (~0.3 ms).** meta SQLite
   returns title/DOI straight from a page-cache-resident B-tree, no decode —
   ~10× cheaper than the abstract path (3.5 ms). Abstracts consolidated
   *because* their baseline was slow (decompression-bound); meta can't *because*
   its baseline is cheap.
2. **Row-vs-column mismatch.** Hydration is a whole-row point-gather of ~50
   scattered docs. Row stores (SQLite) fetch a doc in one place; column stores
   (Lance/Vortex) pay per-column read + Arrow materialisation per gather.
   Hydration is the wrong workload for columnar.
3. **Compression ⇄ decode is a hard, measured tradeoff.** Store size and gather
   latency are **inversely correlated** end to end: Vortex 9.31 GB → 27×, Lance
   10.80 → 21×, zstd 12.32 → 7×, raw 17.68 → 2.3×. Every GB saved costs latency.
4. **Page-fault physics at scale.** A 9–18 GB store is not fully resident; 50
   scattered reads become 50 cold faults. The 1M-sample tests fit in cache and
   lied — the 96× extrapolation trap (C7 0.70× → C11 87×).
5. **Ordinals do not help hydration.** Ordinal addressing killed the *filter*
   stage search (year/type as arrays, §12). Hydration needs the actual title/DOI
   **bytes** — it is I/O + decode bound, not addressing-bound. No address trick
   removes a byte read.

---

## 3. Specs / pain points / modules per store

| Store | Modules | Strengths | Pain points |
|---|---|---|---|
| **SQLite** (row B-tree, incumbent) | `docs(INTEGER PK + docs_other TEXT)`; abstracts `blocks/docs/meta` | warm read ~0.3 ms; row-oriented (whole-row point access); mature | 24.9 GB (largest); addressing is a *search* (400 ms cold at scale from 9p); WAL/-shm |
| **Lance** 9.0.0 (columnar, Rust) | ~64 MB fragments; BTREE scalar index; `take([rowid])` | O(1)-ish positional take; good compression (10.8 GB); multimodal (vectors) | **15–21× slower** 50-id gather (fragment + Arrow overhead); scalar index is a searcher (255 ms) |
| **Vortex** 0.83.0 (columnar, Rust) | `FsstArray`, FastLanes bit-pack; `VortexFile.scan(indices=)` | **best compression** (9.31 GB); Arrow-native; already uses FSST | **27× slower (worst)**; `scan(indices=)` requires **ascending** indices (monotonic selection, not a gather); pre-1.0 |
| **raw mmap** (bespoke, C12) | `blob + u64 offsets` | closest latency (2.3×); trivial; no decode | saves ~nothing (17.68 GB); Python-per-record overhead |
| **perdoc-zstd** (bespoke, C11) | `blob + u64 offsets + trained dict` | −10.64 GB; ordinal-indexed | **7–87× slower** (zstd decode + faults) |

---

## 4. BESPOKE PROPOSAL — FSST row-store (C14) · DESIGN ONLY, UNMEASURED

> **Efficacy: UNMEASURED. Every number in this section marked *est.* is a
> projection from external benchmarks, not a result. It becomes a claim only
> after C14 measures it at full scale.**

### The gap in the frontier

Every failed meta attempt used **heavy decode** (zstd, Vortex cascades) or **no
compression** (raw), and the two off-the-shelf options used a **column** layout.
No test combined the three things the workload actually wants:

- **FSST codec** — [Boncz et al., VLDB 2020](https://www.vldb.org/pvldb/vol13/p2649-boncz.pdf):
  **~3.6 GB/s decode**, SIMD (1.3× on top), *designed for* "fast random access +
  independent decompression of individual strings", ~2× ratio on text. The
  **opposite** tradeoff from zstd/Vortex — ratio sacrificed for random-access
  speed. (Vortex *has* FSST but buries it under columnar scan/materialisation
  overhead; the proposal is to use FSST *without* that overhead.) Already cited
  in `docs/LEXICAL_STORAGE_RESEARCH.md`.
- **Row-oriented mmap substrate** — either the shipped abstract-flat pattern
  (`os.pread` + ordinal offset, `abstracts.py`) or **LMDB**
  ([~9× SQLite random-read throughput](https://en.wikipedia.org/wiki/Lightning_Memory-Mapped_Database),
  mmap zero-copy read path).
- **Resident** — the droplet already keeps `meta.sqlite` (24.9 GB) warm, so a
  ~9 GB FSST store is *fully* resident → RAM-speed reads, faults gone.

### Projected outcome (*est.*, unmeasured)

- **Size — strong.** FSST ~2× on text → title/DOI store *est.* **~8–9 GB**,
  replacement ~10–11 GB (+ §12 filter cols 0.75 + wids 1.20), **saving *est.*
  ~14 GB** — the largest of any design, comparable to Vortex, but with cheap
  decode.
- **Speed — plausible, NOT proven, and it hinges on a compiled reader.** The
  measured floor for a *Python* mmap-row reader is C12's **raw = 0.70 ms (2.3×
  slower)** — and that is *before* FSST decode. That 0.70 ms is mostly 50×
  Python per-record overhead (numpy slice + `tobytes` + `partition`), not I/O.
  To clear SQLite's ~0.3 ms the 50-record gather + FSST decode must run in **one
  C/Rust call** (FSST's C library, or LMDB's C get-path with a batch cursor) —
  the way SQLite runs its `IN` query in C.

### Verdict: 🟡 CONDITIONAL — worth ONE bounded gate-spike, ~1-in-3 odds

The only untested design with a real shot, and the physics support it (near-free
decode + resident + row-oriented + read headroom). **But the honest probability
of clearing the STRICT "identical latency" gate is ~30–40%** — the realistic
risk is that even a good FSST-row reader lands at 1.5–2× and fails the operator's
no-regression bar, like everything else, just closer.

**Also weigh:** meta consolidation is a **disk-space** lever (~14 GB), not a
latency one — the droplet serves from local disk and meta is already warm (§14).
The question is whether ~14 GB of droplet disk is worth a spike with a ~60%
chance of "nothing clears the bar."

### C14 spike scope (if green-lit) — with a hard kill criterion

1. Build an FSST title/DOI store at full 150.4M, **row-oriented**, ordinal-keyed,
   with the fail-closed identity gate (reuse `abstracts.py`'s pattern + the
   ordinal space).
2. **Measure through a *compiled* gather** — FSST C-lib binding, or an LMDB
   batch cursor. A Python-per-record reader is a guaranteed fail and must NOT be
   the thing measured.
3. Gate: **p50 ≤ warm-SQLite p50 at full scale**, byte-parity (incl. NULL
   sentinel), §14 discipline (local disk, interleaved, warmed, noise floor).
4. **Kill criterion:** if the compiled FSST-row reader cannot hit ≤ ~0.3 ms
   resident at 150M, meta consolidation is **definitively closed** — no further
   codec/columnar attempts. Record it and stop.

### Do NOT reopen (already measured, do not repeat)

- perdoc-zstd, raw mmap, Lance `take`, Vortex `scan(indices=)` — all measured at
  full scale, all regress (C11–C13). Only a **compiled FSST row-store** is new.
- Lance/Vortex as *engines* or as the meta store — rejected on both the
  scalar-index and positional-take axes.
