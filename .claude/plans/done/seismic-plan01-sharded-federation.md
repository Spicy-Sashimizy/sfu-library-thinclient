# Plan 01 — Sharded build + federated query (the lossless no-JVM, on-box path)

**Created 2026-06-28**, following the user's pivot from Plan 02 to Plan 01 after a
live measurement (this session) refuted Plan 02's "no new code" serve premise.

## Why we are here (the gate that forced this plan)

Plan 02 was the cheapest path to G6 — **until I measured it on the live `seismic`
package this session:**

- **Stock `SeismicIndex.load()` is NOT mmap.** Control experiment on the saved 2M
  baseline index (`/tmp/seismic_testbed/index/med_bio_2m.index.seismic`):
  baseline RssAnon 0.006 GB → after `.load()` RssAnon **1.706 GB**, RssFile
  **0.007 GB** (flat). It deserializes the whole index into **owned anonymous RAM**
  = Path A (912 B/doc → ~137 GB @150M). The memory note "pyseismic has no load API"
  is stale (0.4.0 `.so` gained `.load()`), but `.load()` is a vanilla deserialize,
  not the Path C reader.
- **The real mmap reader exists only as a gitignored Rust bin** (C2's
  `MmapSeismicIndex`), never wired into Python (C2.5 was explicitly deprioritized).
  So Plan 02's serve step "Load K shards mmap'd (Path C mode)" is false for stock
  code.
- **Plan 02's build step needs a ≥56 GB host** that I cannot provision from inside
  this 31.3 GB WSL2 container (`.wslconfig` is a Windows-side edit; cloud box
  needs provisioning).

**Plan 01 is the only plan whose build half is genuinely achievable on this 32 GB
box with stock code** — shard so each build is ~9–11 GB, one at a time. Its serve
half still needs mmap at *full 150M scale*, BUT the federation logic + the one
quality gate can be validated at *persona scale now* using stock `.load()`
(persona indexes fit in RAM; mmap only matters at 150M). That de-risks the whole
plan before any big-box dependency.

## The goal (unchanged across all plans)

Unblock the **G6 RRF parity** gate — the only remaining quality escape. G2 leg-level
is 0.479 (< 0.95, non-tunable on every index lever); G6 asks whether RRF absorbs
that divergence at the *system* level. The judged docs span the full 30M/150M corpus
(no 2M slice captures enough) → only a full-corpus leg can resolve G6. Sharding is
what makes a full-corpus **build** fit our RAM.

**Honest framing (preserved from the docs):** sharding does NOT fix 0.479 quality.
It changes *feasibility*, not the verdict. If sharded G6 also fails, the KILL basis
is complete.

---

## Scope of THIS plan (what I will build now, on this 31 GB box)

Two pieces, both persona-scale, both no-big-host, both stock-code:

### Piece A — Sharded spool splitter (deterministic hash partition)

Add `--shard k/K --hash-seed S` to `scripts/seismic_testbed/spool_to_seismic_jsonl.py`
(or a thin wrapper `shard_spool.py` that reuses its `iter_slice`).

- Hash `openalex_id` → `shard_id = xxh64(oaid + seed) % K`. xxhash is NOT in the venv
  (verified); use Python's `hashlib.blake2b(..., digest_size=8)` as a stable,
  dependency-free 64-bit hash (deterministic across processes — `blake2b` is seeded,
  unlike the built-in `hash()`). Document the hash choice in the manifest.
- Emits `med_bio_shard{0..K-1}.jsonl` + per-shard `.manifest.json` (docs, nnz,
  hash seed, K). Hash-partition (not range) keeps nnz balanced → even build-RAM.
- **Reuse, don't fork:** the splitter is the only genuinely new file; it calls the
  existing `iter_slice` + JSONL writer verbatim.

### Piece B — Federated serve wrapper (the one new code artifact)

New file `scripts/seismic_testbed/seismic_federated.py`:

- `ShardedSeismicBackend`: loads K shards (stock `SeismicIndex.load()` for now — fine
  at persona scale), holds `(idx_0..idx_{K-1})`.
- `search(query_vec, top_k, k_prime, query_cut, heap_factor)`:
  - Fan-out: `idx_i.search(query_id? …)` across all K shards. **Problem:** `search()`
    takes a `query_id` (a doc *in the index*), not an arbitrary query vector — the G2
    harness uses query-doc lookups, but G6 uses encoded SPLADE qvecs. I will check
    whether `batch_search` / a vector-input path exists; if `search` is strictly
    `query_id`-keyed, the federated search must issue each encoded query against each
    shard's id space (the persona harness already does doc-id-keyed lookup, so this is
    a known shape, not a blocker). **Resolve this in implementation, don't assume.**
  - Each shard returns local top-`k'` (default `k' = 4×k`, per the doc's over-fetch
    guidance). SEISMIC scores are inner products on a **shared SPLADE vocabulary** →
    per-shard scores are directly comparable → **merge by raw score, take global top-k**
    (no normalization).
  - Returns `[(oaid, score), ...]` — the exact shape `SeismicBackend.search` returns,
    so it drops into the existing G2/G6 harnesses via the `SFU_SPLADE_BACKEND=seismic`
    shim with a `SHARDED` manifest path.
- Thread fan-out with `concurrent.futures` (shards are CPU-bound; one thread per shard
  is enough at K=8; avoid GIL contention since the `.so` releases the GIL during C-level
  search).

### Piece C — The pre-registered federation-safety gate (the real reason to do this now)

`scripts/seismic_testbed/g_federation_overlap.py` — the make-or-break measurement:

- Build **two configs over the SAME ~4M med_bio docs**:
  - `1×4M` — single index (the reference).
  - `2×2M` — two hash-partitioned shards, federated query.
- Compute overlap@10 of (2-shard federated top-k) vs (1-shard single top-k) over the
  G2 query set, reusing `eval_seismic_parity.overlap()`.
- **Pre-registered verdict (from the doc):** overlap ≥ 0.98 → federation is
  result-safe (proceed to 150M build); < 0.95 → fan-out itself perturbs results,
  shard count must drop. Record to `data/eval_results/seismic_federation_overlap_4m.json`.
- This is the ONE quality variable Plan 01 introduces (per-shard pruning/k-means vs
  global). It must clear before any G6 result on the sharded index is trusted.

---

## What is OUT of scope for this plan (stated plainly)

- **The 150M build itself** — needs each shard built at ~9–11 GB, serially. The 5
  spool sections are 123 GB compressed (~150M docs). Building all 8 shards is a
  multi-hour run I will NOT start in this plan; it is gated on Piece B + C green
  and on a decision about where to land ~58 GB of index on disk (700 GB free,
  fine) and whether serve uses mmap. I will leave a concrete `shards.json` manifest
  schema + a one-command build queue script so the 150M build is a turnkey next step.
- **The mmap serve path (C2.5)** — at 150M, stock `.load()` would put K × ~1.7 GB =
  ~13.5 GB anon on K=8 (persona) and the *full* Path-A floor (~137 GB) on the real
  150M index → **cannot serve 150M on 32 GB without the mmap reader**. This is the
  same dependency Plan 02 hit. Plan 01 defers it: federation + the overlap gate are
  validated with stock RAM-resident shards at *persona scale* (fits), and the 150M
  serve step carries the same C2.5 precondition as Plan 02. **I will not hide this**
  — it stays in the doc's risks + as a named gate (G8-serve) before any 150M G6 run.

## Sequencing & gates

1. `git pull` → **Piece A** (splitter + `--shard`) → commit.
2. **Piece B** (`seismic_federated.py`) → commit.
3. **Piece C** (federation overlap @ 4M, 2-vs-1) → record result → commit.
   - Gate: overlap ≥ 0.98 → green; else stop and report.
4. **Doc sync (mandatory per CLAUDE.md same-commit / session-end rule):**
   - Update `docs/seismic_150m_testbed/build_plans/01_*.md` Status: DESIGN →
     PARTIAL (federation + overlap gate measured; persona scale; 150M build + C2.5
     serve unblocked-not-done), with the live `.load()`-is-not-mmap finding folded in
     (it affects Plan 02's serve step too — note there).
   - Add a row to `06_FINDINGS.md` with date 2026-06-28, the overlap number, and the
     measured `.load()` RAM result.
5. (Out of this plan) 150M build + C2.5 → G6 run.

## Files I will create / edit

| File | Action |
|---|---|
| `scripts/seismic_testbed/shard_spool.py` | **new** — `--shard k/K` hash splitter (reuses `iter_slice`) |
| `scripts/seismic_testbed/seismic_federated.py` | **new** — `ShardedSeismicBackend` + fan-out/merge |
| `scripts/seismic_testbed/g_federation_overlap.py` | **new** — 2-vs-1 overlap gate @ 4M |
| `docs/seismic_150m_testbed/build_plans/01_*.md` | edit — status + `.load()` finding |
| `docs/seismic_150m_testbed/06_FINDINGS.md` | edit — federation overlap result row |

All runs write to `/tmp/seismic_testbed/...` (external ext4, mirrors the spike
isolation convention) and results to `data/eval_results/`. No changes to the serving
`src/lib/thinclient/` path in this plan (the federation is testbed-only until green).

## Git workflow (mandatory per CLAUDE.md)

pull → (Edit) → `git add <specific files>` → commit → push, per piece. Never
`git add .` (working tree has multi-GB runtime state). Doc updates ship same-commit
or same-session-push.

## Success criteria for THIS plan (not the full G6)

1. `med_bio` sharded into K shards deterministically (reproducible hash).
2. `ShardedSeismicBackend` returns merged top-k; parity-check: federated-2shard
   top-k == single-2M top-k when both see the SAME data (a sanity assertion, not
   the quality gate).
3. **2-shard-vs-1-shard overlap@10 ≥ 0.98 on 4M med_bio** — the pre-registered
   federation-safety gate. Recorded + committed.
4. Docs updated with the measured overlap + the live `.load()` finding.

If (3) fails (overlap < 0.95), I stop and report — do not proceed to a 150M build
on a federation that perturbs results.
