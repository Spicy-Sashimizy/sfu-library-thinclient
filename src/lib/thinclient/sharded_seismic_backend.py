"""Federated SEISMIC SPLADE-leg backend (served path, env-gated behind
`SFU_SPLADE_BACKEND=seismic` + `SFU_SEISMIC_SHARD_MANIFEST`).

The serving layer for the sharded 150M build (Plan 01). Loads K SEISMIC shards
and federates a query across all of them, merging by raw score. This is the
backend the live `ThinClientRetriever` SPLADE leg instantiates to serve SEISMIC
against the real 150M corpus — promoted out of the testbed
(`scripts/seismic_testbed/seismic_federated.py`) so `SFU_SPLADE_BACKEND=seismic`
against the served package actually works. The testbed module re-exports these
names for back-compat (its parity/overlap harnesses `from seismic_federated
import ShardedSeismicBackend` unchanged).

**One system, two DISTINCT serving methods.** The same 8 immutable C2 mmap shards
are served by two independent classes, pickable per deployment:

- `ParallelSeismicBackend` — **server-side.** A persistent per-backend
  `ThreadPoolExecutor` (created once at construction; measured −2.3 ms traverse
  p50 vs the old per-query construction, G8g A/B 2026-07-08) fans the query out
  to all shards at once. Latency ≈ the slowest shard; resident working set ≈ all
  shards (~66 GB at 150M). Best on a host with RAM ≥ the resident set.
- `SequentialSeismicBackend` — **localized, RAM-efficient.** Searches shards one
  at a time, keeping only ~one shard's pages faulted in at any instant; the kernel
  reclaims idle shards' file-backed mmap pages under memory pressure. Latency ≈ Σ
  per-shard time; peak resident ≈ ~1 shard → fits a RAM-constrained host WITHOUT
  swapping. Mechanism (A) of `docs/seismic_sequential_serving/01_ARCHITECTURE.md`
  (pure Python, no Rust change; the optional `MADV_DONTNEED`/`mlock` mechanisms
  (B)/(C) are documented future hooks). See `docs/seismic_sequential_serving/`.

**Why distinct classes, not a branch (cascade design).** The classes are fully
distinct: NO inheritance, NO shared mutable instance state. A parallel thread bug
in `ParallelSeismicBackend._fan_out` physically cannot reach a
`SequentialSeismicBackend` instance, and vice versa. The genuinely-common machinery
(shard loading, manifest parsing, the score-merge, the SPLADE encoder) lives in
**pure module-level helpers** (`_load_one_shard`, `_load_manifest`, `_merge_topk`,
`_prepare_query`, `_EncoderShim`) — ONE copy each, so the shared logic cannot
silently drift between the two methods. The only thing a method owns is its
`_fan_out` (and the thin `search`/`encode_query`/`search_with_timing` wrappers).
For this system whose correctness story is "both methods return bit-identical
top-k," silent divergence is the most dangerous cascade; a single shared pure
merge (not a duplicated one) is what prevents it.

**Result-equivalence (load-bearing).** Because every shard shares one SPLADE
vocabulary and the identical encoded qvec is issued to each, per-shard scores
live in the same dot-product space → merging by raw score is **order-
independent**. `SequentialSeismicBackend` therefore produces a global top-k
**bit-identical** to `ParallelSeismicBackend` (same `k'` over-fetch) — a serving
change with zero quality impact. Asserted as a hard equality test (T1 in
`docs/seismic_sequential_serving/03_TESTING.md`).

**Back-compat selector.** `ShardedSeismicBackend(federation="parallel"|"sequential")`
remains as a thin `__new__` selector that returns the matching concrete class — kept
so the three load-bearing parity harnesses that construct
`ShardedSeismicBackend(index_paths, load_mode="mmap")` with NO federation kwarg keep
working unchanged (their bit-identical G6/overlap results must not cascade-break).
New code should construct the concrete class directly.

**Load mode (load-bearing gate).** `load_mode="mmap"` (Path C) loads each shard
from a converted sibling `X.mmap/` dir (produced by `convert_shard_to_mmap.py`);
it raises a clean `RuntimeError` if a dir is absent — **never** a silent Path-A
fallback (which would silently re-introduce the ~137 GB anon floor that G3
killed). The served federated path defaults to `mmap` (the whole point of
serving 150M is Path-C; see `retriever._seismic_backend()`). `load_mode="stock"`
(Path-A owned anon) stays the constructor default for persona-scale
reproducibility of the overlap gate + all prior bit-identical results.

NOTE on stock `.load()` (measured 2026-06-28): `SeismicIndex.load()` deserializes
into *owned anonymous RAM* (1.7 GB → RssAnon 1.706 GB) — Path A, NOT mmap. At
150M, stock `.load()` would put ~137 GB × the sharded total in RAM → unaffordable
on a 32 GB host. C2.5 (MMAP_SERVE_READY) shipped the pyo3 mmap reader
(`seismic.MmapSeismicIndex`): anon Δ 0.0 GB, 96% file-resident, parity
bit-identical.

`search()` mirrors `SeismicBackend.search() -> [(oaid, score)]` (plus the
federated-only `k_prime` over-fetch kwarg, which the single-backend `search`
accepts as a no-op so both backends share one call signature). Returns
`list[tuple[str, float]]` — byte-compatible with the Qdrant/BMP/single-SEISMIC
legs, so RRF fusion + `record-tc` records join on `oaid` unchanged.
"""
import concurrent.futures as cf
import json
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("sharded_seismic_backend")

# Manifests record shard paths relative to the repo root (e.g.
# `data/seismic_150m/index/plan01/...`); the serving process's cwd is not
# guaranteed to be the repo root (MCP server launch), so relative paths that
# don't resolve from cwd are anchored here.
_REPO_ROOT = Path(__file__).resolve().parents[3]


# ── shared pure helpers ──────────────────────────────────────────────────────
# ONE copy each. Pure functions / stateless tools shared by BOTH serving classes.
# Keeping them here (not duplicated, not on a base class) is the cascade design:
# the score-merge cannot drift between the two methods, and no instance state
# crosses the method boundary.


class _EncoderShim:
    """Borrows `lib.opensearch_retriever.encode_splade` so we share the exact
    query encoder of the Qdrant/BMP legs without loading a throwaway SEISMIC
    index (which `SeismicBackend.__init__` would)."""

    def __init__(self, splade_model_path: str):
        self.splade_model_path = splade_model_path

    def encode_splade(self, query: str) -> dict:
        from lib.opensearch_retriever import encode_splade
        return encode_splade(query, self.splade_model_path)


def _load_manifest(manifest_path: str, load_mode: str = "stock") -> list[str]:
    """A Plan-01 shard manifest lists built shard index paths; but the splitter's
    manifest lists the *jsonl* inputs, not the built .index.seismic. So this helper
    accepts EITHER:
      - a manifest.json with a 'shards' key (G7/C2.5 build+convert manifests;
        each shard record carries `index_path`, and C2.5 records ALSO carry
        `mmap_dir`), or
      - a manifest.json with a 'shard_indexes' key (built-index manifest), or
      - a plain JSON list of index paths, or
      - a comma-separated string of index paths.
    The build step (build_persona_seismic.py per shard) produces the .index.seismic
    files; the overlap-gate harness assembles the path list.

    `load_mode="mmap"` prefers each shard's `mmap_dir` field when present (the C2.5
    converted-shard manifest) — this decouples the served mmap location from the
    G7 source's `index_path`, which may live on volatile scratch (`/tmp`). Only
    when no `mmap_dir` is recorded does it fall back to `index_path`, whose stem
    the loader derives `.mmap/` from."""
    p = Path(manifest_path)
    if not p.exists() and not Path(manifest_path).is_absolute():
        p = _REPO_ROOT / manifest_path
    if p.exists() and p.suffix == ".json":
        data = json.load(open(p))
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if "shards" in data and isinstance(data["shards"], list):
                records = data["shards"]
                # A partially-converted manifest must fail loudly, never serve a
                # partial corpus (guard added 2026-07-06; same contract as the
                # mmap no-silent-fallback rule).
                expected = data.get("n_shards")
                if expected is not None and len(records) != expected:
                    raise RuntimeError(
                        f"manifest {p} declares n_shards={expected} but carries "
                        f"{len(records)} shard records — refusing a partial corpus")
                # C2.5 records carry BOTH index_path and mmap_dir; mmap_dir is the
                # authoritative served path (persistent, post /tmp-wipe-safe).
                if load_mode == "mmap":
                    out = [s.get("mmap_dir") for s in records if s.get("mmap_dir")]
                    if out:
                        if len(out) != len(records):
                            missing = [s.get("shard") for s in records
                                       if not s.get("mmap_dir")]
                            raise RuntimeError(
                                f"manifest {p}: {len(out)}/{len(records)} shard "
                                f"records carry mmap_dir (shards {missing} lack it)"
                                " — refusing to silently serve a partial corpus")
                        return out
                # G7/stock shape: shard records carry `index_path`.
                out = [s.get("index_path") for s in records if s.get("index_path")]
                if out:
                    if len(out) != len(records):
                        missing = [s.get("shard") for s in records
                                   if not s.get("index_path")]
                        raise RuntimeError(
                            f"manifest {p}: {len(out)}/{len(records)} shard records "
                            f"carry index_path (shards {missing} lack it)"
                            " — refusing to silently serve a partial corpus")
                    return out
            if "shard_indexes" in data:
                return list(data["shard_indexes"])
    return [s.strip() for s in manifest_path.split(",") if s.strip()]


def _load_one_shard(seismic_module, p: str, load_mode: str):
    """Load one shard by `load_mode` (pure: takes the seismic module + the mode,
    no instance state). `mmap` requires a `.mmap/` dir (produced by
    convert_shard_to_mmap.py); it raises a clean RuntimeError if absent — NEVER
    silent-fallback to stock, which would re-introduce the Path-A anon floor and
    silently break the 32 GB serve budget.

    `p` in mmap mode may be EITHER:
      - a `.mmap/` dir directly (the C2.5 manifest's `mmap_dir` field — the
        authoritative persistent path), or
      - a stock `X.index.seismic` path or `X` stem whose sibling `X.mmap/` dir
        the loader derives (G7-manifest fallback).

    Relative paths that don't resolve from the process cwd are re-anchored at
    the repo root (manifests record repo-root-relative paths; the MCP server's
    cwd is not guaranteed to be the repo root)."""
    if not Path(p).is_absolute() and not Path(p).exists():
        anchored = _REPO_ROOT / p
        if anchored.exists():
            p = str(anchored)
    if load_mode == "mmap":
        if p.endswith(".mmap") and Path(p).is_dir():
            mmap_dir = p
        else:
            # Stock `X.index.seismic` or stem → sibling `X.mmap/` dir.
            stem = p[:-len(".index.seismic")] if p.endswith(".index.seismic") else p
            mmap_dir = f"{stem}.mmap"
        if not Path(mmap_dir).is_dir():
            raise RuntimeError(
                f"load_mode=mmap but converted mmap dir not found: {mmap_dir}\n"
                f"  (stock shard {p} — run scripts/seismic_testbed/"
                f"convert_shard_to_mmap.py to produce {mmap_dir}/ first)")
        log.info("federated: loading shard (mmap) %s", mmap_dir)
        idx = seismic_module.MmapSeismicIndex(mmap_dir)
        log.info("  mmap'd len=%d dim=%d nnz=%d", idx.len, idx.dim, idx.nnz)
        return idx
    # stock Path-A (owned anon) — default, fine at persona scale.
    fp = p if p.endswith(".index.seismic") else f"{p}.index.seismic"
    if not fp or not Path(fp).exists():
        fp = p if Path(p).exists() else fp
    log.info("federated: loading shard (stock) %s", fp)
    idx = seismic_module.SeismicIndex.load(fp)
    log.info("  loaded len=%d dim=%d nnz=%d", idx.len, idx.dim, idx.nnz)
    return idx


def _prepare_query(q: dict[str, float], top_k: int, string_dtype,
                    query_cut: int | None, k_prime: int | None):
    """Build the SEISMIC search inputs from a sparse query dict (pure). Returns
    `(qcomp, qvals, qc, kp)` — the numpy token/value arrays, the effective
    query_cut, and the per-shard over-fetch k'.

    Default k' = max(2×top_k, 100) — flipped from 4×top_k on 2026-07-08 (G8f):
    at the served top_k=50 shape, k'=100 vs the old 200 is recall-safe on the
    MERGED federated top-k (overlap@10 0.999, overlap@50 0.994, n=100) and
    1.47× faster federated traverse (38.3 → 26.0 ms p50);
    `data/eval_results/g8f_shardmerge_profile_kprime_20260708.json`. The floor
    of 100 keeps small-top_k requests at or above their pre-flip candidate
    depth (e.g. top_k=10: old 40 → new 100); top_k > 50 halves its over-fetch
    (measured only at top_k=50 — the E1 mechanism, a sooner-full heap raising
    the block-skip threshold, is top_k-independent, *est.* for other shapes)."""
    tokens = list(q.keys())
    values = [float(v) for v in q.values()]
    qc = query_cut if query_cut is not None else len(tokens)
    qcomp = np.array(tokens, dtype=string_dtype)
    qvals = np.array(values, dtype=np.float32)
    kp = k_prime if k_prime is not None else max(top_k * 2, 100)
    return qcomp, qvals, qc, kp


def _merge_topk(per_shard_results: list, top_k: int) -> list[tuple[str, float]]:
    """Merge per-shard `[(query_id, dist, doc_id)]` result lists into a global
    top-k of `[(oaid, score)]`, by raw inner-product score. SHARED by both
    serving methods — order-independent, so parallel (max-of-shards) and
    sequential (sum-of-shards) produce bit-identical top-k for the same per-shard
    results. Assumed by the T1 result-equivalence test (do not change the sort
    key / de-dup / truncation without re-running T1).

    SEISMIC returns distance = inner-product score (higher = better, per the
    single-index backend's `float(dist)` pass-through) → sort descending. De-dup
    by doc_id defensively (a doc can't be in two shards)."""
    merged: list[tuple[str, float]] = []
    for res in per_shard_results:
        for (_qid, dist, doc_id) in res:
            merged.append((doc_id, float(dist)))
    merged.sort(key=lambda x: -x[1])
    seen = set()
    out = []
    for oaid, score in merged:
        if oaid in seen:
            continue
        seen.add(oaid)
        out.append((oaid, score))
        if len(out) >= top_k:
            break
    return out


# ── the two distinct serving classes ─────────────────────────────────────────


class _SeismicBackendBase:
    """NOT a serving method — the shared CONSTRUCTION + thin-wrapper shell for
    the two concrete serving classes. This is a private base that holds only
    construction-time state (shards, encoder) and the trivial encode/search
    wrappers that are identical across methods. It does NOT hold any per-query
    mutable state and does NOT implement `_fan_out` (the one thing that differs).
    Both concrete classes set `federation` as a class attribute.

    (Cascade note: this is a narrow construction-shell, not a behavior base —
    `_fan_out` is the ONLY per-query behavior, and it lives on each concrete
    class, so a subclass cannot silently violate a merge invariant it doesn't
    own. The shared merge is the pure module fn `_merge_topk`, not a method here.)"""

    federation: str = ""          # set by each concrete subclass

    def __init__(self, index_paths: list[str], splade_model_path: str = "models/splade_onnx_fused",
                 load_mode: str = "stock"):
        import seismic
        from lib.thinclient.seismic_backend import SeismicBackend
        if load_mode not in ("stock", "mmap"):
            raise ValueError(f"load_mode must be 'stock' or 'mmap', got {load_mode!r}")
        self._seismic = seismic
        self._string_dtype = seismic.get_seismic_string()
        self._backend_proto = SeismicBackend  # for encode_query (shared encoder)
        self.splade_model_path = splade_model_path
        self.load_mode = load_mode
        # Cheap shared encoder object just for encode_query (its __init__ loads a
        # SEISMIC index we DON'T want); so we don't instantiate it — we borrow the
        # method via a thin stand-in below.
        self._encoder = _EncoderShim(splade_model_path)
        self.shards = []
        for p in index_paths:
            idx = _load_one_shard(self._seismic, p, self.load_mode)
            self.shards.append(idx)

    @classmethod
    def from_manifest(cls, manifest_path: str, *, splade_model_path: str = "models/splade_onnx_fused",
                      load_mode: str = "stock"):
        """Build from a shard manifest. Accepts EITHER:
          - a manifest.json with a 'shards' key (G7/C2.5 build+convert manifests;
            each shard record carries `index_path`), or
          - a manifest.json with a 'shard_indexes' key (built-index manifest), or
          - a plain JSON list of index paths, or
          - a comma-separated string of index paths.
        The build step (build_persona_seismic.py per shard) produces the
        .index.seismic files; the convert step (convert_shard_to_mmap.py) the
        sibling .mmap/ dirs; this loader just assembles the path list.

        `load_mode` selects Path-A stock vs Path-C mmap; the serving method is
        chosen by which concrete class you call this on (Parallel vs Sequential)."""
        index_paths = _load_manifest(manifest_path, load_mode=load_mode)
        if not index_paths:
            raise RuntimeError(f"no shard indexes parsed from manifest {manifest_path}")
        return cls(index_paths, splade_model_path=splade_model_path, load_mode=load_mode)

    def encode_query(self, query: str) -> dict[str, float]:
        # Split out so the encoder path is testable / matchable independently.
        from lib.thinclient.seismic_backend import SPLADE_QUERY_TERMS
        sparse = self._encoder.encode_splade(query)
        if not sparse:
            return {}
        return dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])

    def search(self, query: str, top_k: int,
               query_cut: int | None = None,
               heap_factor: float = 0.8,
               k_prime: int | None = None) -> list[tuple[str, float]]:
        """Federated search: fan the qvec across all K shards, merge by score.
        k_prime = per-shard over-fetch (default max(2×top_k, 100), G8f
        2026-07-08). Returns global top-k
        [(oaid, score)]. Same return shape as SeismicBackend.search for harness
        compatibility. Serving method = `self._fan_out` (parallel vs sequential)."""
        q = self.encode_query(query)
        if not q:
            return []
        return self.search_encoded(q, top_k, query_cut=query_cut,
                                   heap_factor=heap_factor, k_prime=k_prime)

    def search_encoded(self, q: dict[str, float], top_k: int,
                       query_cut: int | None = None,
                       heap_factor: float = 0.8,
                       k_prime: int | None = None) -> list[tuple[str, float]]:
        """Traversal only — the `search` step with the SPLADE encode factored out.
        Prepares the query, fans it out (parallel or serial per the concrete
        class's `_fan_out`), merges by score. Same return shape + merge as `search`.

        Serving method is `self._fan_out`: `ParallelSeismicBackend` fans out via a
        `ThreadPoolExecutor` (latency ≈ max shard); `SequentialSeismicBackend`
        searches shards one at a time (latency ≈ Σ shards, bounded resident set).
        The downstream `_merge_topk` is SHARED and order-independent, so both
        methods return the same global top-k (bit-identical, same `k'` over-fetch)."""
        if not q:
            return []
        qcomp, qvals, qc, kp = _prepare_query(q, top_k, self._string_dtype,
                                               query_cut, k_prime)

        def _search_one(idx):
            return idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                              k=kp, query_cut=qc, heap_factor=heap_factor)

        per_shard = self._fan_out(_search_one)
        return _merge_topk(per_shard, top_k)

    def _fan_out(self, _search_one) -> list:
        """Run `_search_one` across all shards. Overridden by each concrete class
        — this is the ONLY per-query behavior that differs between the methods."""
        raise NotImplementedError

    def search_with_timing(self, query: str, top_k: int,
                           query_cut: int | None = None,
                           heap_factor: float = 0.8,
                           k_prime: int | None = None,
                           ) -> tuple[list[tuple[str, float]], float, float]:
        """`search()` but returns (results, encode_ms, traverse_ms) so the serve
        bench can attribute per-query latency to the SPLADE encode vs the SEISMIC
        fan-out traversal SEPARATELY (item-#3). Uses `time.perf_counter` walls;
        identical merge to `search`/`search_encoded`. Returns traverse_ms=0.0 when
        the query fails to encode (nothing to traverse)."""
        import time
        t0 = time.perf_counter()
        q = self.encode_query(query)
        encode_ms = (time.perf_counter() - t0) * 1000.0
        if not q:
            return [], encode_ms, 0.0
        t0 = time.perf_counter()
        out = self.search_encoded(q, top_k, query_cut=query_cut,
                                  heap_factor=heap_factor, k_prime=k_prime)
        traverse_ms = (time.perf_counter() - t0) * 1000.0
        return out, encode_ms, traverse_ms


class ParallelSeismicBackend(_SeismicBackendBase):
    """Server-side serving method: K shards searched CONCURRENTLY via a
    `ThreadPoolExecutor`. Latency ≈ the slowest shard (max-of-shards); resident
    working set ≈ all shards. Best on a host with RAM ≥ the resident set.

    The pyseismic `.so` releases the GIL during C-level search, so the
    ThreadPoolExecutor gets real parallelism despite the GIL. Building more shards
    than cores just queues — no RSS stacking (shards are loaded once at startup).

    The executor is PERSISTENT: created once at construction, reused by every
    query (2026-07-08). Measured efficacy — same-process interleaved A/B vs the
    old per-query `ThreadPoolExecutor(...)` construction (G8g, n=100×3 warm,
    served k'=100 shape, results bit-identical across arms,
    `data/eval_results/g8g_ab_perquery_vs_persistent_20260708.json`): traverse
    p50 26.4 → 22.8 ms, paired per-query delta −2.3 ms. Real but modest — the
    G8f "scheduling overhead" was mostly NOT pool construction: per-query
    thread spawns staggered the 8 shard searches (each ran less contended,
    max-shard 6.4 ms), while the persistent pool overlaps them genuinely
    (max-shard 12.9 ms of memory-bandwidth contention) yet still lowers the
    total wall. The executor is per-INSTANCE state (never shared with a
    SequentialSeismicBackend, preserving the no-shared-mutable-state cascade
    property) and construction-time only — no per-query mutation. Concurrent
    callers share the K workers (submissions queue; `ThreadPoolExecutor` is
    thread-safe). Idle workers park on the work queue between queries; the
    interpreter joins them at exit, so no explicit shutdown is required."""

    federation = "parallel"

    def __init__(self, index_paths: list[str], splade_model_path: str = "models/splade_onnx_fused",
                 load_mode: str = "stock"):
        super().__init__(index_paths, splade_model_path=splade_model_path,
                         load_mode=load_mode)
        # max(1, …): a zero-shard backend must stay constructible (the selector
        # contract tests build one); ThreadPoolExecutor rejects max_workers=0.
        self._executor = cf.ThreadPoolExecutor(
            max_workers=max(1, len(self.shards)),
            thread_name_prefix="seismic-shard")

    def _fan_out(self, _search_one) -> list:
        return list(self._executor.map(_search_one, self.shards))


class SequentialSeismicBackend(_SeismicBackendBase):
    """Localized, RAM-efficient serving method: search shards ONE AT A TIME so
    only ~one shard's pages are faulted in at any instant, then release that shard's
    pages before touching the next (mechanism B, `MADV_DONTNEED`) → peak resident ≈
    ~1 shard, not ~K (fits a RAM-constrained host WITHOUT swapping). Latency ≈
    Σ per-shard time. No thread pool: GIL is irrelevant (no parallelism sought).

    Mechanisms (A) + (B) of `docs/seismic_sequential_serving/01_ARCHITECTURE.md`:
    (A) is the serial loop (pure Python); (B) is the hard `release_pages` after
    each shard (the C2.5 pyo3 `MmapSeismicIndex.release_pages()` hook, shipped
    2026-06-30 — turns the ~1-shard bound from a kernel-reclaim heuristic into a
    HARD guarantee). Mechanism (C) mlock/MADV_RANDOM is still a design-only future
    hook. Result-equivalent to `ParallelSeismicBackend` (bit-identical top-k, same
    `k'` over-fetch) because `_merge_topk` is order-independent — asserted by T1;
    the re-fault after `MADV_DONTNEED` returns identical data (asserted by the
    mechanism-B re-fault test). Under this method, `search_with_timing`'s
    traverse_ms is the sum of per-shard times (T6 attribution in
    `docs/seismic_sequential_serving/03_TESTING.md`).

    The parallel path (`ParallelSeismicBackend`) NEVER calls `release_pages` — its
    working set is meant to stay resident — so the `.so` rebuild that added the hook
    changes only the sequential path. Stock / older-`.so` mmap shards that lack the
    hook degrade cleanly to a no-op + debug log (the loader's no-silent-breakage
    contract), never a raise."""

    federation = "sequential"

    def _fan_out(self, _search_one) -> list:
        out = []
        for idx in self.shards:
            out.append(_search_one(idx))
            # Mechanism (B): MADV_DONTNEED each shard's file-backed slabs right after
            # its search so its resident pages are evicted before the next shard is
            # faulted in → peak resident ~= 1 shard, hard-guaranteed (not kernel-
            # reclaim timing). Guarded so stock shards / an older .so without the
            # pyo3 hook degrade to a no-op + debug log, never a raise (the shard is
            # still searched correctly; only the eager eviction is skipped).
            release = getattr(idx, "release_pages", None)
            if release is not None:
                release()
            else:
                log.debug("sequential: shard has no release_pages(); "
                          "mechanism (B) skipped (older .so?)")
        return out


# ── back-compat selector ─────────────────────────────────────────────────────


class ShardedSeismicBackend(_SeismicBackendBase):
    """Back-compat selector — NOT a serving method. `__new__` returns the matching
    concrete serving class (`ParallelSeismicBackend` default | `SequentialSeismicBackend`),
    so an instance is always one of the two real methods. Kept so every existing
    call site keeps working unchanged:

      - `ShardedSeismicBackend(index_paths, load_mode="mmap")`  → parallel (default)
      - `ShardedSeismicBackend(..., federation="sequential")`  → sequential
      - `ShardedSeismicBackend.from_manifest(manifest, ...)`    → parallel (default)

    New code should construct `ParallelSeismicBackend` / `SequentialSeismicBackend`
    directly. The three load-bearing parity harnesses (`g6_rrf_parity_fullcorpus.py`,
    `reconcile_legoverlap.py`, `serve_footprint_bench.py`) use this selector without
    a `federation` kwarg — their bit-identical G6/overlap results depend on the
    default staying `parallel`.
    """

    federation = "parallel"   # selector default; the instance's real class sets its own

    def __new__(cls, index_paths: list[str], splade_model_path: str = "models/splade_onnx_fused",
                load_mode: str = "stock", federation: str = "parallel"):
        if federation not in ("parallel", "sequential"):
            raise ValueError(
                f"federation must be 'parallel' or 'sequential', got {federation!r}")
        concrete = ParallelSeismicBackend if federation == "parallel" else SequentialSeismicBackend
        return concrete(index_paths, splade_model_path=splade_model_path, load_mode=load_mode)
