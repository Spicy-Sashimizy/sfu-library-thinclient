# Plan — SEISMIC C2.5: pyo3 mmap reader (the 150M-serve unblock)

Branch: `spike/mmap-bmp` (continue; all SEISMIC work lives here).
Created: 2026-06-28, as the next step after Plan 01 Step 2 (G7 build COMPLETE).

## Why this is the next step (not G6, not C2)

State after Plan 01 Step 2:
- **G7 ✅** — the full 150M corpus is built as K=8 shards on disk
  (`/tmp/seismic_testbed/index/plan01/global_shard{0..7}of8.index.seismic`,
  ~8.3 GB each, 66.26 GB total), serially on this 32 GB box.
- **Federation gate ✅** — 2-shard-vs-1-shard overlap@10 = 0.9967 (result-safe).
- **`seismic_federated.py` shipped** but loads shards via **stock
  `seismic.SeismicIndex.load(fp)`** = Path A (owned anon RAM). That is fine at
  persona scale (K×~1.7 GB fits 32 GB) but **cannot serve 150M on 32 GB**:
  stock `.load()` deserializes the whole index into anon RAM (912 B/doc →
  ~137 GB @150M). Measured 2026-06-28 (RssAnon 1.706 GB on the 2M index).

The **C2 mmap reader already exists and KEEPS_GATE** (`seismic_c2_mmap_metadata_close.json`:
anon Δ +0.041 GB ≈ 0, file-resident 96% of index, parity bit-identical, latency
0.97× path-A). It lives in `spike/seismic_upstream/src/mmap_io.rs` as
`MmapSeismicIndex` — but it is reached **only from a Rust bin**. The Python
serving layer (`seismic_federated.py` → `lib.thinclient.seismic_backend`) cannot
call it. **That wiring gap is C2.5**, and it is the single precondition between
"150M indexes exist on disk" and "150M is servable on 32 GB". G8 (served 150M
RAM + latency) and the real G6 (RRF parity on the sharded 150M leg) are gated on
it. Until C2.5 lands, every serve-side gate is structurally unmeasurable.

The venv's `seismic` package is **already the spike fork**
(`/workspaces/sfu-library-thinclient/.venv/lib/python3.11/site-packages/seismic/`,
built via maturin with `features = ["default","python"]`), exposing
`SeismicIndex`/`SeismicIndexRaw`/`SeismicIndexDotVByte`. So C2.5 = add one new
pyclass mirroring those, rebuild, reinstall — **no new Python-side architecture**.

## The implementation contract (verified against code this session)

`MmapSeismicIndex` (in `spike/seismic_upstream/src/mmap_io.rs:349`) already has:

| Rust method | Signature | Source |
|---|---|---|
| `from_mmap(dir: &Path)` | `Result<Self, io::Error>` | mmap_io.rs:412 |
| `search_raw(comps: &[String], vals: &[f32], k, query_cut, heap_factor, n_knn, first_sorted)` | `Vec<ScoredVectorDotProduct>` | mmap_io.rs:599 |
| `doc_id(doc_idx: usize)` | `Option<&'static str>` | mmap_io.rs:739 |
| `len()` / `dim()` / `n_doc_mapping()` | `usize` | (forward proxy) |

`ScoredVectorDotProduct = ScoredItemGeneric<DotProduct, VectorId>` where
`VectorId = u64`. The owned path's `remap_doc_ids` (inverted_index_wrapper.rs:193)
shows the exact translation to replicate:

```rust
let score_id_pairs: Vec<(f32, usize)> = results
    .into_iter()
    .map(|r| (r.distance.distance(), r.vector as usize))   // DotProduct::distance() -> f32
    .collect();
// doc_id from mapping if present, else internal_id.to_string()
```

So the pyo3 `search` returns `Vec<(String, f32, String)>` = `(query_id, score,
doc_id)` — **byte-identical shape** to `PySeismicIndex.search` (pylib/mod.rs:504),
so `seismic_federated.py`/`SeismicBackend` need zero changes to consume it.

Input contract matches too: `search_raw` resolves token **strings** through
`self.token_to_id_map` (owned, O(vocab), ~628 KB — the one allowed owned piece),
identically to the owned `search`. So the binding accepts the same
`np.array([str], dtype=seismic.get_seismic_string())` + `np.array([f32])` query
inputs the federated wrapper already produces. (The c2 bin's "doesn't carry the
token map" comment refers to a numeric-ID *test* workload, not the reader.)

## Scope of THIS plan

### Piece A — the `MmapIndex` pyclass (the one new Rust artifact)

New file `spike/seismic_upstream/src/pylib/mmap_index.rs`:

- `#[pyclass(name = "MmapSeismicIndex")] struct PyMmapIndex { idx: MmapSeismicIndex }`
- `#[pymethods]`:
  - `#[new] fn new(dir: &str) -> PyResult<Self>` → wraps `MmapSeismicIndex::from_mmap`,
    mapping `io::Error` → `PyErr` (clean error if the dir isn't an mmap layout).
  - `#[pyo3(signature=(query_id, query_components, query_values, k, query_cut, heap_factor, n_knn=0, sorted=true))]`
    `fn search<'py>(&self, query_id: String, qcomps: PyReadonlyArrayDyn<PyFixedUnicode<MAX_TOKEN_LEN>>, qvals: PyReadonlyArrayDyn<f32>, k, query_cut, heap_factor, n_knn, sorted) -> Vec<(String, f32, String)>`
    — converts numpy arrays → `Vec<String>`/`Vec<f32>`, calls `self.idx.search_raw`,
    remaps each `ScoredVectorDotProduct` via `r.distance.distance()` + `self.idx.doc_id(r.vector as usize)`,
    falling back to `r.vector.to_string()` when `doc_id` is `None` (mirrors `remap_doc_ids`).
  - `fn len(&self) -> usize`, `fn dim(&self) -> usize` (parity harness reads `idx.len`/`idx.dim`).
- Register in `lib.rs` `#[pymodule] fn seismic`: `m.add_class::<PyMmapIndex>()?;` behind
  `#[cfg(feature = "python")]`, alongside the existing `PySeismicIndex`.

This is a **standalone pyclass**, deliberately NOT macro-generated via
`impl_seismic_index!`: the mmap reader has a different construction (`from_mmap`,
not `build`/`load`) and a different inner type, so it doesn't fit the macro.
Hand-written keeps it ~80 lines and avoids perturbing the owned-path macro.

### Piece B — build + reinstall the spike fork into the venv

- `cd spike/seismic_upstream && maturin develop --release` (maturin not in venv
  → install it first: `sudo .venv/bin/python3 -m pip install maturin`, per the
  CLAUDE.md venv-install rule). This rebuilds `libseismic.so` with the python
  feature + the new class and installs it over the site-packages `.so`.
- Verify: `.venv/bin/python3 -c "import seismic; print('MmapSeismicIndex' in dir(seismic))"`
  → `True`.

### Piece C — end-to-end validation at persona scale (the gate)

New script `scripts/seismic_testbed/c25_mmap_serve_validate.py`:

1. Load the **already-converted** mmap dir `/tmp/seismic_testbed/mmap_c2/` via
   `seismic.MmapSeismicIndex(dir)` — no conversion needed (the dir persists from
   the C2 run). This is the cheap/fast validation: the 2M persona index already
   exists in mmap layout on disk.
2. Load the stock Path-A `SeismicIndex.load(med_bio_2m.index.seismic)` as the
   reference.
3. Run the same ~30 deterministic persona queries through both; assert:
   - **parity bit-identical**: same doc-ids in the same order, scores within 1e-4
     (reuses the C2-cached workload shape — `eval_seismic_parity.py` queries).
   - **floor**: read `/proc/self/status` RssAnon/RssFile before/after `MmapSeismicIndex`
     construction → assert RssAnon delta ≈ 0 (< 0.1 GB) and RssFile ≈ index size,
     re-confirming C2's KEEPS_GATE at the Python boundary (not just the Rust bin).
4. Emit `data/eval_results/seismic_c25_mmap_serve_validate.json`
   (`parity_ok`, `floor_anon_delta_gb`, `floor_file_gb`, `latency_p50_ms`,
    `verdict`: `C2.5 MMAP_SERVE_READY` iff parity + floor hold).

This is the make-or-break: C2 was measured from a Rust bin; C2.5 confirms the
**same floor holds when constructed from `Python`** (no hidden re-materialization
through the pyo3 boundary, no owned copy in the wrapper). If parity or floor
breaks at the Python boundary, that is the real blocker and is reported, not
hidden.

### Piece D — wire `seismic_federated.py` to use the mmap loader (the actual 150M unblock)

In `scripts/seismic_testbed/seismic_federated.py` (current line ~74-91 loads via
stock `SeismicIndex.load`), add a loader switch:
- `--load-mode {stock,mmap}` (default still `stock` — backward-compatible; the
  federation-overlap gate and all persona results stay reproducible on `stock`).
- `mmap` mode: for each shard path `X.index.seismic`, look for a sibling
  `X.mmap/` dir (the converted layout); if present, load via
  `seismic.MmapSeismicIndex(X.mmap)`; if absent, raise a clean `RuntimeError`
  naming the missing conversion (never silent fallback to `stock` — that would
  silently re-introduce the Path-A floor). Add the `SFU_SEISMIC_LOAD_MODE` env
  hook so the served `SeismicBackend`/`retriever.py` path can also pick it up
  later (gate behind an env var, NOT wired into a live served path here —
  testbed-only, per the Plan 01 docstring convention).
- No change to fan-out/merge — `MmapSeismicIndex.search` returns the identical
  `(query_id, score, doc_id)` tuple shape, so the merge-by-raw-score path is
  untouched.

D is the small wiring; the actual `X.mmap/` dirs for the 150M shards do **not**
exist yet (each shard is a stock `.index.seismic`). The conversion step is a
driver, below — but it is the one multi-hour piece and I will not start it
until C+D are green.

### Piece E — the 150M shard-to-mmap conversion driver (turnkey, NOT run in C2.5)

New script `scripts/seismic_testbed/convert_shard_to_mmap.py` (one shard at a
time, like `build_plan01_154m_shards.py`):
- For one stock shard: `load_index` (~9.9 GB peak, fits 32 GB serially — same as
  the G7 build peak) → `write_mmap_index` → `MmapSeismicIndex::from_mmap` parity
  assert against the stock `search_raw` → drop owned, `malloc_trim`.
- Expose via Python by *calling the Rust bin* `c1a_mmap_index` (which already
  does load→write→from_mmap→parity) per shard — **reuse, don't re-implement in
  Python**. The driver just queues 8 of those runs with an RSS kill-watcher
  (>20 GB abort), mirroring `build_plan01_150m_shards.py`.
- Per-shard mmap output → `/tmp/seismic_testbed/index/plan01/global_shard{0..7}of8.mmap/`
  (~8.3 GB each flat). Total ~66 GB, within the 635 GB free.
- Emit `data/eval_results/seismic_c25_shards_150m_mmap.json` (per-shard
  conversion RSS, floor, parity; totals).

**E ships as runnable code + doc, but the 8-shard conversion RUN is gated on
C green + a fresh disk-space/RAM check, the same way Plan 01 gated the build
run.** I will commit the driver but not start the multi-hour conversion until
the validation gate clears and you say go. (Honest framing: E is what makes 150M
*servable*; C+D are what proves it'll work.)

## Sequencing & gates (this plan)

1. `git pull` → **A** (pyclass) → build → commit.
2. **B** (maturin reinstall) → `import` smoke → commit the rebuild artifact if
   the installed `.so` is tracked (it is NOT tracked under git — only confirm).
3. **C** (persona mmap serve validate, 2M) → record JSON → commit.
   - Gate: parity bit-identical AND floor_anon_delta < 0.1 GB AND RssFile > 50%
     of on-disk → `MMAP_SERVE_READY`; else STOP and report (a Python-boundary
     re-materialization would be the real blocker).
4. **D** (`seismic_federated.py --load-mode mmap`) → re-run the federation
   overlap gate in mmap mode (same 929k shards, but you'd need converted 929k
   mmap dirs). Cheap subset: convert just the 929k shards and re-run
   `g_federation_overlap.py` mmap-mode → assert overlap@10 still ≥ 0.98. commit.
5. **E** driver committed (turnkey), conversion run **NOT started** here.
6. **Doc sync** (mandatory, same-commit / session-end per CLAUDE.md):
   - `02_GO_NO_GO_GATES.md` G8 row → `⬜` stays but gains a C2.5-READY note +
     the serve-precondition status; G6 row keeps its INCONCLUSIVE note with the
     "now unblocked pending C2.5 → E run" qualifier.
   - `build_plans/01_SHARDED_BUILD_FEDERATED_QUERY.md` "serve half pending C2.5"
     → update to "C2.5 pyo3 binding shipped + validated persona; 150M shard
     conversion driver shipped (turnkey); 150M serve run pending E".
   - `06_FINDINGS.md` → new row: C2.5 (date, parity, floor, latency, result file).
   - `07_G3_RAM_FIX_PLAN.md` → §4.4 append: C2.5 closes the Python-serving gap.
   - Memory `seismic-testbed-p1-p2-results.md` + `c1-mmap-fork-scope.md`:
     mark C2.5 done, C2.5-no-longer-blocks-150M-serve once green.

## Files I will create / edit

| File | Action |
|---|---|
| `spike/seismic_upstream/src/pylib/mmap_index.rs` | **new** — `PyMmapIndex` pyclass |
| `spike/seismic_upstream/src/pylib/mod.rs` | edit — `pub mod mmap_index;` + `pub use …PyMmapIndex;` |
| `spike/seismic_upstream/src/lib.rs` | edit — register `PyMmapIndex` in `#[pymodule]` |
| `scripts/seismic_testbed/c25_mmap_serve_validate.py` | **new** — persona mmap parity+floor gate |
| `scripts/seismic_testbed/seismic_federated.py` | edit — `--load-mode mmap` switch (default stock) |
| `scripts/seismic_testbed/convert_shard_to_mmap.py` | **new** — turnkey per-shard conversion driver (c1a bin under the hood) |
| `docs/seismic_150m_testbed/02_GO_NO_GO_GATES.md` | edit — G8/G6 precondition notes |
| `docs/seismic_150m_testbed/build_plans/01_*.md` | edit — serve-half status |
| `docs/seismic_150m_testbed/06_FINDINGS.md` | edit — C2.5 result row |
| `docs/seismic_150m_testbed/07_G3_RAM_FIX_PLAN.md` | edit — §4.4 C2.5 append |
| `data/eval_results/seismic_c25_mmap_serve_validate.json` | **new** (result) |
| `memory/seismic-testbed-p1-p2-results.md`, `c1-mmap-fork-scope.md` | edit |

All runs use `/tmp/seismic_testbed/...` (external ext4 spike isolation). No change
to the live served `src/lib/thinclient/` path (C2.5 is testbed-only until green;
the served retriever wiring is a separate, later, env-gated step).

## Success criteria for THIS plan (not the full G8/G6)

1. `import seismic; seismic.MmapSeismicIndex` is constructible from a converted
   mmap dir.
2. `seismic_c25_mmap_serve_validate.json`: parity bit-identical to Path-A on the
   2M persona index, RssAnon Δ < 0.1 GB, RssFile > 50% of on-disk. `MMAP_SERVE_READY`.
3. `seismic_federated.py --load-mode mmap` loads mmap-mode shards; federation
   overlap@10 on the 929k shards still ≥ 0.98 (federation result-safe under mmap).
4. `convert_shard_to_mmap.py` driver shipped + documented; the 8-shard 150M run
   is a turnkey next step, NOT started here.
5. Docs + memory reflect C2.5 status.

If (2) fails (parity or floor breaks at the Python boundary), I STOP and report —
do not proceed to D/E on a binding that re-materializes the floor.
