# Plan: Promote ShardedSeismicBackend into the served package + run/record G8

**Date:** 2026-06-29 · **Branch:** `spike/mmap-bmp`

Closes the literal "make SEISMIC serve the real 150M corpus" gap. Today the live
retriever wires only the **single** `SeismicBackend` (Path-A, RAM-resident) — the
150M serve needs the **federated** `ShardedSeismicBackend` (K shards, mmap), which
lives only in `scripts/seismic_testbed/`. So `SFU_SPLADE_BACKEND=seismic` against
the real 150M corpus cannot work today. All prerequisites exist: the 8 converted
mmap shards are intact on disk (`/tmp/seismic_testbed/index/plan01/global_shard{0..7}of8.mmap`,
7.8 GB each, 66 GB total) + the C2.5 manifest `data/eval_results/seismic_c25_shards_150m_mmap.json`.

---

## Step 1 — Promote `ShardedSeismicBackend` into `src/lib/thinclient/`

**New file** `src/lib/thinclient/sharded_seismic_backend.py`:

- Move `ShardedSeismicBackend`, `_EncoderShim`, and `_load_manifest` here verbatim
  from `scripts/seismic_testbed/seismic_federated.py` (they are already self-contained
  except `import seismic` + `from lib.thinclient.seismic_backend import SeismicBackend/SPLADE_QUERY_TERMS`,
  both reachable since `src/` will already be on the path in the served package).
- Add a classmethod `ShardedSeismicBackend.from_manifest(manifest_path, *, splade_model_path, load_mode)`:
  reads the JSON, accepts **either** shape the codebase already produces —
  `{"shards":[{"index_path":...}]}` (G7/C2.5 manifests) **or** `{"shard_indexes":[...]}`
  (built-index manifest) **or** a bare JSON list — and constructs. This absorbs
  the `_load_manifest` helper logic as the canonical loader (so the served path
  and the testbed share one truth).
- Keep the load-mode gate **exactly as-is**: `mmap` raises a clean `RuntimeError`
  if the sibling `.mmap/` dir is absent — **never** a silent Path-A fallback (that
  silently re-introduces the ~137 GB anon floor). Default `load_mode="stock"` for
  persona-scale reproducibility stays in the **constructor**; the served path will
  pass `mmap` explicitly (see Step 2).
- `search()` signature unchanged — identical to the single `SeismicBackend.search`
  shape `list[tuple[str,float]]` so RRF + parity harness stay byte-compatible.
  Adds the federated-only kwargs already present (`k_prime`, `query_cut`, `heap_factor`).

**Testbed back-compat shim** — edit `scripts/seismic_testbed/seismic_federated.py`:
replace the class/helper definitions with a re-export `from lib.thinclient.sharded_seismic_backend
import ShardedSeismicBackend, _EncoderShim` (mirrors the existing
`scripts/seismic_testbed/seismic_backend.py` shim pattern). The CLI `main()` + module
docstring stay so all testbed scripts (`g6_rrf_parity_fullcorpus.py`,
`serve_footprint_bench.py`, `g_federation_overlap.py`, `reconcile_legoverlap.py`)
keep `from seismic_federated import ShardedSeismicBackend` unchanged.

---

## Step 2 — Wire `_seismic_backend()` to the federated manifest + mmap gate

Edit `src/lib/thinclient/retriever.py`:

- `_seismic_backend()` (line 565): add a manifest branch **before** the single-index
  branch. Resolution order:
  1. `SFU_SEISMIC_SHARD_MANIFEST` set → `ShardedSeismicBackend.from_manifest(...)`
     with `load_mode=os.environ.get("SFU_SEISMIC_LOAD_MODE","mmap")`.
     **Default `mmap`** for the served federated path — the promotion's whole
     point is serving 150M, which needs Path-C; if `.mmap/` dirs are missing it
     raises the clean RuntimeError rather than silent Path-A. (Operators who want
     Path-A persona-scale pass `SFU_SEISMIC_LOAD_MODE=stock`.)
  2. else `SFU_SEISMIC_INDEX` set → existing single `SeismicBackend` (unchanged).
  3. else → existing clean `RuntimeError`.
- Thread federated params into `_splade_leg_seismic` (line 581): read
  `SFU_SEISMIC_K_PRIME` (default `4×top_k`), `SFU_SEISMIC_QUERY_CUT`,
  `SFU_SEISMIC_HEAP_FACTOR` (default 0.8) from env; pass into `.search()`.
  Single-backend path ignores k_prime (its `.search` doesn't take it) — so gate
  on `isinstance(backend, ShardedSeismicBackend)` for the k_prime kwarg, or give
  the single backend a no-op k_prime kwarg. **Chosen:** add `k_prime=None` to
  `SeismicBackend.search` as a no-op kwarg (ignored) so both backends share one
  call signature — simpler than isinstance branching in the retriever.
- Update the `self._seismic = None` field comment (line 169) — no longer "single only".

---

## Step 3 — Run + record G8

Run (project venv, swap-contaminated 32 GB host → **RAM is the trustworthy half,
latency gets a swap caveat**):

```
SFU_SEISMIC_LOAD_MODE=mmap .venv/bin/python3 \
  scripts/seismic_testbed/serve_footprint_bench.py \
  --shard-manifest data/eval_results/seismic_c25_shards_150m_mmap.json \
  --queries 40 --result-file data/eval_results/seismic_g8_150m_serve_20260629.json
```

- Records: SEISMIC RssAnon + Pss_Anon + VmRSS + VmSwap (TRUE anon floor =
  RssAnon+VmSwap) vs Qdrant PID RAM, p50/p95/mean latency. Qdrant is running
  (PID 112) so the Qdrant comparison point is live.
- **Expected:** ~7.5 GB resident anon + reclaimable page cache (Path C), anon
  floor ≈ 0 by construction. If VmSwap is non-trivial, the TRUE-floor number is
  the honest one (the bench already computes it).
- **Latency caveat (item #3):** swap is 15/16 Gi used → the box is thrashing,
  so latency p50 will be inflated and is **not** representative; flag it in the
  result + docs. Encode-vs-traversal split is uninstrumented → note as TODO,
  do not block.
- Commit the result JSON + log.

---

## Step 4 — Doc sync (same-commit, per CLAUDE.md)

- `docs/seismic_150m_testbed/02_GO_NO_GO_GATES.md`: G8 row ⬜RUNNABLE → ⬜/✅
  measured (RAM number + latency-with-swap-caveat), absolute date 2026-06-29,
  result-file path. Add a note that the served package now hosts
  `ShardedSeismicBackend` (so the gate is reachable via `SFU_SPLADE_BACKEND=seismic`).
- `docs/seismic_150m_testbed/06_FINDINGS.md`: G8 section with the numbers.
- `docs/THIN_CLIENT_SWAP.md`: add `SFU_SEISMIC_SHARD_MANIFEST` /
  `SFU_SEISMIC_LOAD_MODE` / `SFU_SEISMIC_K_PRIME` et al. to the env-var section;
  note the served SEISMIC SPLADE leg (mmap, sharded) exists behind
  `SFU_SPLADE_BACKEND=seismic`.
- `docs/README.md`: no new doc file added (no index change needed) — verify only.
- `grep -rn 'SFU_SEISMIC_INDEX' docs/ src/ scripts/` to catch stale single-only refs.

---

## Verification

- `python3 -c "from lib.thinclient.sharded_seismic_backend import ShardedSeismicBackend"`
  imports clean from `src/`.
- Smoke: `from seismic_federated import ShardedSeismicBackend` still works
  (testbed scripts unchanged) — re-export shim.
- G8 result JSON written + committed; G8 gate row updated same commit.

## Out of scope (explicitly deferred)

- Encode-vs-traversal latency instrumentation (item #3) — needs a clean no-swap host
  regardless; G8 RAM is the deciding half and records cleanly here.
- G6 meaningful re-run (item #4) — blocked on n≳400 judged set; no change.
- G5 persona latency / G9 ownership — untouched.
