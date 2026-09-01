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

**Back-compat selector.** `ShardedSeismicBackend(federation="parallel"|"sequential"|"hybrid")`
remains as a thin `__new__` selector that returns the matching concrete class — kept
so the three load-bearing parity harnesses that construct
`ShardedSeismicBackend(index_paths, load_mode="mmap")` with NO federation kwarg keep
working unchanged (their bit-identical G6/overlap results must not cascade-break).
New code should construct the concrete class directly. `"hybrid"` (Q7, 2026-07-10)
returns the cold-start hybrid class; it is NOT the selector default (parallel stays
the default so the load-bearing parity harnesses' bit-identical results hold).

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
import os
import threading
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("sharded_seismic_backend")


def _shard_fault_boundary_on() -> bool:
    """ON → a shard that fails to load OR fails to search (throws / times out) is
    marked failed + skipped instead of killing the whole federation. Owner ask
    2026-07-17: any 1 of 8 shards down must leave the other 7 serving. Default
    OFF = pre-WI-10 behavior (preserves the load-bearing T1 parity harnesses)."""
    return os.environ.get("SFU_SEISMIC_SHARD_FAULT_BOUNDARY", "0") == "1"


def _shard_search_timeout_s() -> float:
    """Per-shard search timeout (seconds). A shard whose `.search` exceeds this is
    treated as failed (the hung-shard case). Default 30s (generous — a 9p cold
    shard can take seconds; the timeout is a safety net for a WEDGED shard, not a
    slow-but-healthy one)."""
    try:
        return float(os.environ.get("SFU_SEISMIC_SHARD_SEARCH_TIMEOUT_S", "30"))
    except ValueError:
        return 30.0


def _shard_reprobe_s() -> float:
    """Cooldown before a failed shard is re-probed (re-admitted to the federation
    on the next search). Mirrors the leg-breaker cooldown."""
    try:
        return float(os.environ.get("SFU_SEISMIC_SHARD_REPROBE_S", "10"))
    except ValueError:
        return 10.0


class _ShardFaultTracker:
    """Per-shard fault state shared by the LOAD boundary (marks a shard that fails
    to load) and the SEARCH boundary (marks a shard that throws/times out during
    `.search`). A failed shard returns `[]` for its search results and is omitted
    from the federation's contribution; after the reprobe cooldown, one search is
    allowed through as a probe (a success re-admits, a fail re-arms the cooldown).

    The tracker holds NO scores and NO results — only fail counts + timestamps.
    It never touches `_merge_topk` (the shared pure merge), so a faulted federation
    still merges the SURVIVING shards' results by the same order-independent
    merge. T1-unaffected: the merge is unchanged; only which per-shard results
    feed it differs, and only under an explicit fault (OFF → no change at all).

    Hash sharding makes a lost shard a BOUNDED ~1/8 recall loss with no score-
    comparability issue (doc 09: calibration unnecessary by construction — each
    shard is a disjoint doc-id hash partition, scored in one shared vocab space)."""

    __slots__ = ("fails", "opened_at", "probe_pending", "last_reason", "_lock")

    def __init__(self):
        self.fails = 0
        self.opened_at: float | None = None
        self.probe_pending = False
        self.last_reason: str | None = None
        self._lock = threading.Lock()

    def is_failed(self) -> bool:
        """True if this shard should be SKIPPED this search (failed + still in the
        reprobe cooldown, or a probe is already in flight). When the cooldown has
        elapsed, sets probe_pending and returns False (HALF-OPEN: let this search
        through as the probe)."""
        with self._lock:
            if self.opened_at is None:
                return False
            if self.probe_pending:
                return True
            if time.monotonic() - self.opened_at >= _shard_reprobe_s():
                self.probe_pending = True
                return False
            return True

    def on_success(self):
        with self._lock:
            self.fails = 0
            self.opened_at = None
            self.probe_pending = False
            self.last_reason = None

    def on_fail(self, reason: str):
        with self._lock:
            if self.probe_pending:
                self.opened_at = time.monotonic()
                self.probe_pending = False
                self.last_reason = reason
                return
            self.fails += 1
            self.last_reason = reason
            self.opened_at = time.monotonic()


def _shard_name(idx, idx_path: str, position: int) -> str:
    """A stable human name for a shard (its manifest path stem, or its position).
    Used in `degraded_shards` so the response names WHICH shard is down."""
    base = Path(idx_path).name
    if base:
        for suf in (".mmap", ".index.seismic"):
            if base.endswith(suf):
                base = base[: -len(suf)]
                break
        return base
    return f"shard_{position}"


_REPO_ROOT = Path(__file__).resolve().parents[3]


class _EncoderShim:
    """Borrows `lib.opensearch_retriever.encode_splade` so we share the exact
    query encoder of the Qdrant/BMP legs without loading a throwaway SEISMIC
    index (which `SeismicBackend.__init__` would)."""

    def __init__(self, splade_model_path: str):
        self.splade_model_path = splade_model_path

    def encode_splade(self, query: str) -> dict:
        from lib.opensearch_retriever import encode_splade
        return encode_splade(query, self.splade_model_path)


def _coalesce_extents(extents, max_extents: int = 2048, gap0: int = 32):
    """Merge sorted (page_start, page_len) extents across small gaps until
    ≤ max_extents remain (gap escalates ×4 up to 4096 pages).

    VMA-SPLIT CAP (2026-07-14): both MADV_SEQUENTIAL (prefault) and mlock
    (pin) split a VMA per distinct range — ~33k extents/shard × 8 shards
    saturated vm.max_map_count (262,144 measured), after which mmap fails
    process-wide: mlock_ranges returns 0, read_text() raises MemoryError,
    thread spawn dies. Gap pages included by a merge get faulted/locked too
    (cheap adjacent bytes); callers must re-check byte budgets after."""
    gap, merged = gap0, [list(e) for e in extents]
    while True:
        out = []
        for s, ln in merged:
            if out and s <= out[-1][0] + out[-1][1] + gap:
                out[-1][1] = max(out[-1][0] + out[-1][1], s + ln) - out[-1][0]
            else:
                out.append([s, ln])
        merged = out
        if len(merged) <= max_extents or gap > 4096:
            break
        gap *= 4
    return [tuple(e) for e in merged]


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
                expected = data.get("n_shards")
                if expected is not None and len(records) != expected:
                    raise RuntimeError(
                        f"manifest {p} declares n_shards={expected} but carries "
                        f"{len(records)} shard records — refusing a partial corpus")
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
    fp = p if p.endswith(".index.seismic") else f"{p}.index.seismic"
    if not fp or not Path(fp).exists():
        fp = p if Path(p).exists() else fp
    log.info("federated: loading shard (stock) %s", fp)
    idx = seismic_module.SeismicIndex.load(fp)
    log.info("  loaded len=%d dim=%d nnz=%d", idx.len, idx.dim, idx.nnz)
    return idx


def _resolve_mmap_dir(p: str, load_mode: str) -> str | None:
    """F3 (2026-07-14): resolve the `.mmap/` dir for a shard path (the same
    derivation `_load_one_shard` uses internally), so the hot-set sidecar
    loader can find `<shard>.mmap/hotset_*.json`. Returns None for stock mode
    or an unresolvable stem. Relative paths are re-anchored at repo root."""
    if load_mode != "mmap":
        return None
    if not p:
        return None
    if not Path(p).is_absolute() and not Path(p).exists():
        p = str(_REPO_ROOT / p)
    if p.endswith(".mmap") and Path(p).is_dir():
        return p
    stem = p[:-len(".index.seismic")] if p.endswith(".index.seismic") else p
    return f"{stem}.mmap"


def _mlock_floor_mode() -> str:
    """F4-rescoped (2026-08-17): decode `SFU_SEISMIC_MLOCK_FLOOR`.

      `0` / unset  → "off"   (DEFAULT — byte-identical to the pre-F4 path)
      `1`          → "floor" (the RESCOPED structural navigation floor,
                              budget-capped; see `mlock_structural_floor`)
      `full`       → "legacy" (the 2026-07-14 over-scoped whole-slab mlock:
                              posting_lists + doc-mapping + forward_offsets =
                              1.67 GB/shard × 8 ≈ 13.4 GB. Retained ONLY so the
                              original measurement is reproducible; NOT a
                              min-RAM setting.)

    Anything else is treated as "off" with a warning (fail safe, never pin
    gigabytes because of a typo)."""
    v = os.environ.get("SFU_SEISMIC_MLOCK_FLOOR", "0").strip().lower()
    if v in ("0", "", "off", "false"):
        return "off"
    if v == "1":
        return "floor"
    if v in ("full", "legacy", "slabs"):
        return "legacy"
    log.warning("SFU_SEISMIC_MLOCK_FLOOR=%r not one of 0/1/full — floor mlock OFF", v)
    return "off"


_PL_LAYOUT = (
    ("packed_postings_words",        8, 8, "DATA"),
    ("block_offsets_len",            8, 8, "NAV"),
    ("ef_high_bits_n_words",         8, 8, "NAV"),
    ("inv_block_inventory_len",      8, 8, "NAV"),
    ("inv_subblock_inventory_len",   2, 2, "NAV"),
    ("inv_overflow_positions_len",   8, 8, "NAV"),
    ("ef_low_bits_n_words",          8, 8, "NAV"),
    ("summaries_ids_n_words",        8, 8, "DATA"),
    ("values_len",                   1, 1, "DATA"),
    ("minimums_len",                 4, 4, "DATA"),
    ("quants_len",                   4, 4, "DATA"),
    ("component_ids_len",            2, 2, "DATA"),
)


def _postings_nav_runs(mmap_dir: str) -> tuple[list[tuple[int, int]], int]:
    """F4-rescoped (2026-08-17): the byte ranges of the posting-list NAVIGATION
    metadata inside `<shard>.mmap/posting_lists.bin`, one contiguous run per
    posting list (`block_offsets .. ef_low_bits` are adjacent in the layout, so
    each list contributes exactly ONE range — see `_PL_LAYOUT`).

    Returns `(runs, walked_len)` where `runs` is a list of `(offset, length)`
    and `walked_len` is the total byte length the walk consumed. The caller
    MUST check `walked_len == os.path.getsize(posting_lists.bin)` and refuse on
    mismatch — a layout drift would otherwise mlock the wrong bytes (harmless
    to results, since mlock is residency-only, but silently useless).

    Measured shard0 (150M dv-v2, 2026-08-17): 28,702 runs, 153.1 MB of nav out
    of 1,159.2 MB of posting_lists (13.2%); the DATA components (packed
    postings 322.9 MB + summary ids 305.2 MB + values 295.7 MB + minimums/
    quants 25.6 MB + component_ids 56.5 MB) are NOT included."""
    man = json.loads((Path(mmap_dir) / "manifest.json").read_text())
    cursor = 0
    runs: list[tuple[int, int]] = []
    for plm in man.get("posting_lists", []):
        nav_start = nav_end = None
        for key, size, align, role in _PL_LAYOUT:
            if key == "component_ids_len" and not plm.get("has_component_ids"):
                continue
            cursor += (align - (cursor % align)) % align
            if role == "NAV":
                if nav_start is None:
                    nav_start = cursor
                nav_end = cursor + plm[key] * size
            cursor += plm[key] * size
        if nav_start is not None and nav_end > nav_start:
            runs.append((nav_start, nav_end - nav_start))
    return runs, cursor


def _mapping_base_addr(file_path: str) -> int | None:
    """F4-rescoped (2026-08-17): the virtual base address at which THIS process
    mapped `file_path` (the Rust reader's `leak_mmap` of a whole slab file), read
    from `/proc/self/maps`. `base = vma_start − vma_file_offset`, so a mapping
    already split into several VMAs (by an earlier `madvise`/`mlock`) still
    resolves to the same base. Returns None when the file is not mapped (or on a
    non-Linux host) — the caller degrades to a logged no-op, never a crash."""
    try:
        target = os.path.realpath(file_path)
        with open("/proc/self/maps") as fh:
            for ln in fh:
                parts = ln.rstrip("\n").split(None, 5)
                if len(parts) < 6:
                    continue
                path = parts[5].strip()
                if path.endswith(" (deleted)"):
                    path = path[:-len(" (deleted)")]
                if path != target:
                    continue
                start = int(parts[0].split("-")[0], 16)
                return start - int(parts[2], 16)
    except OSError:
        pass
    return None


def _mlock_addr_ranges(base: int, ranges) -> int:
    """F4-rescoped (2026-08-17): `mlock(2)` the given (offset, length) ranges of
    the mapping at `base`, via ctypes. Returns the bytes successfully locked.

    Residency-only: `mlock` never changes a byte the scorer reads → T1
    bit-identical by construction. Degrades to a partial/zero lock (logged once)
    when the kernel refuses — ENOMEM = RLIMIT_MEMLOCK exhausted, EPERM = no
    CAP_IPC_LOCK — exactly like the .so hooks' no-op fallback: an unprivileged
    process pins less, it never crashes."""
    import ctypes
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.mlock.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        libc.mlock.restype = ctypes.c_int
    except OSError as exc:      # pragma: no cover — non-glibc host
        log.warning("mlock_structural_floor: libc unavailable (%s) — no-op", exc)
        return 0
    locked = 0
    failures = 0
    first_errno = 0
    for off, length in ranges:
        if libc.mlock(ctypes.c_void_p(base + off), ctypes.c_size_t(length)) == 0:
            locked += length
        else:
            failures += 1
            if not first_errno:
                first_errno = ctypes.get_errno()
    if failures:
        log.warning("mlock_structural_floor: %d/%d ranges refused by the kernel "
                    "(first errno %d: %s) — locked %.1f MB, degrading to a "
                    "partial pin (no-OOM contract, never a crash)",
                    failures, len(ranges), first_errno,
                    os.strerror(first_errno) if first_errno else "?",
                    locked / 1e6)
    return locked


def _memavailable_gb() -> float:
    """F3 (2026-07-14): MemAvailable in GB, read from /proc/meminfo. The no-OOM
    budget check pins against this (minus the floor + headroom). Returns a very
    large number on non-Linux (pin budget uncapped — the caller still honors the
    operator's SFU_SEISMIC_PIN_BUDGET_GB dial)."""
    try:
        with open("/proc/meminfo") as f:
            for ln in f:
                if ln.startswith("MemAvailable:"):
                    return int(ln.split()[1]) / (1024 ** 2)
    except OSError:
        pass
    return float("inf")


def _hotset_version_mismatch(sidecar_vk: dict, shard_man: dict) -> str | None:
    """F2 (2026-07-14): the loader's refuse-and-log contract. A sidecar is only
    valid against the shard that generated it — an E8 reconversion (v1→v2) or a
    re-reorder invalidates the page→touch mapping. Returns a human description
    of the first mismatching key, or None if all keys agree (absent keys on
    either side are skipped, not flagged — only PRESENT-but-DIFFERENT is a
    mismatch; the F1 generator emits the keys it read from this same manifest,
    so a present-but-different value is a real reconversion)."""
    for key in ("forward_format", "forward_format_version",
                "forward_reordered", "forward_data_words"):
        if key in sidecar_vk and key in shard_man:
            if sidecar_vk[key] != shard_man[key]:
                return (f"{key}: sidecar={sidecar_vk[key]!r} "
                        f"shard={shard_man[key]!r}")
    return None


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

    federation: str = ""

    def __init__(self, index_paths: list[str], splade_model_path: str = "models/splade_onnx_fused",
                 load_mode: str = "stock"):
        import seismic
        from lib.thinclient.seismic_backend import SeismicBackend
        if load_mode not in ("stock", "mmap"):
            raise ValueError(f"load_mode must be 'stock' or 'mmap', got {load_mode!r}")
        self._seismic = seismic
        self._string_dtype = seismic.get_seismic_string()
        self._backend_proto = SeismicBackend
        self.splade_model_path = splade_model_path
        self.load_mode = load_mode
        self._encoder = _EncoderShim(splade_model_path)
        self.shards = []
        self._shard_mmap_dirs = []
        self._shard_faults: list[_ShardFaultTracker] = []
        self._shard_names: list[str] = []
        self._shard_paths = list(index_paths)
        self._fault_boundary = _shard_fault_boundary_on()
        for i, p in enumerate(index_paths):
            if self._fault_boundary:
                tr = _ShardFaultTracker()
                self._shard_faults.append(tr)
                self._shard_names.append(_shard_name(None, p, i))
                try:
                    idx = _load_one_shard(self._seismic, p, self.load_mode)
                    self.shards.append(idx)
                except Exception as exc:
                    tr.on_fail(f"load: {type(exc).__name__}: {str(exc)[:120]}")
                    log.error("WI-10: shard %s FAILED to load (%s) — marking down, "
                              "federation continues with the surviving shards",
                              self._shard_names[-1], tr.last_reason)
                    self.shards.append(None)
                self._shard_mmap_dirs.append(_resolve_mmap_dir(p, self.load_mode))
            else:
                idx = _load_one_shard(self._seismic, p, self.load_mode)
                self.shards.append(idx)
                self._shard_mmap_dirs.append(_resolve_mmap_dir(p, self.load_mode))

        self._floor_prefaulted = False
        if load_mode == "mmap" and os.environ.get("SFU_SEISMIC_PREFLOOR_AT_LOAD", "0") == "1":
            self.prefault_floor(include_forward_offsets=True)

        self._floor_mlocked = False
        self._floor_mlocked_bytes = 0
        self._hotset_pinned_gb = 0.0
        _floor_mode = _mlock_floor_mode()
        _pin_on = (load_mode == "mmap" and (
            _floor_mode != "off"
            or os.environ.get("SFU_SEISMIC_PREFLOOR_HOTSET", "0") == "1"
            or float(os.environ.get("SFU_SEISMIC_PIN_BUDGET_GB", "0") or "0") > 0))
        if _pin_on:
            from lib.opensearch_retriever import encode_splade
            encode_splade("initialize thread pools", self.splade_model_path)
        if load_mode == "mmap":
            if _floor_mode == "floor":
                self.mlock_structural_floor()
            elif _floor_mode == "legacy":
                log.warning("SFU_SEISMIC_MLOCK_FLOOR=full — the OVER-SCOPED "
                            "whole-slab floor pin (~1.67 GB/shard); this is the "
                            "2026-07-14 reproduction path, NOT a min-RAM setting")
                self.mlock_floor(include_forward_offsets=True)
            budget_env = os.environ.get("SFU_SEISMIC_PIN_BUDGET_GB", "0")
            try:
                pin_budget_gb = float(budget_env)
            except ValueError:
                log.warning("SFU_SEISMIC_PIN_BUDGET_GB=%r not numeric — pin tier OFF",
                            budget_env)
                pin_budget_gb = 0.0
            if pin_budget_gb > 0:
                self.load_hotset_and_pin(pin_budget_gb)
            if os.environ.get("SFU_SEISMIC_PREFLOOR_HOTSET", "0") == "1":
                pf_budget = pin_budget_gb if pin_budget_gb > 0 else 1.6
                self.prefault_hotset(pf_budget)


    def prefault_floor(self, include_forward_offsets: bool = True) -> int:
        """Touch each shard's structural floor (posting-lists + doc-mapping, +
        forward_offsets when requested) once so the cold-query majflt charges only
        forward-data. Returns total bytes touched across shards. Delegates to
        each shard's pyo3 `prefault_floor` (the C2.5 hook, Fix #4). No-op (returns
        0) on shards without the hook (older .so) — degrades cleanly, never a
        raise (the no-silent-breakage contract). Q9 2026-07-10."""
        import time
        t0 = time.perf_counter()
        total = 0
        for idx in self.shards:
            fn = getattr(idx, "prefault_floor", None)
            if fn is None:
                log.debug("prefault_floor: shard lacks the hook (older .so?) — skipped")
                continue
            total += int(fn(include_forward_offsets))
        self._floor_prefaulted = True
        log.info("prefault_floor: touched %.2f GB across %d shards in %.1fs "
                 "(include_forward_offsets=%s)",
                 total / 1e9, len(self.shards),
                 (time.perf_counter() - t0), include_forward_offsets)
        return total

    def mlock_structural_floor(self, budget_mb: float | None = None,
                               max_ranges_per_shard: int = 2048) -> int:
        """F4-RESCOPED (2026-08-17): mlock ONLY the posting-list **navigation**
        metadata — per list, the contiguous `block_offsets + Elias-Fano offsets
        (high/low bits) + DArray inventories` run (`_PL_LAYOUT` NAV rows) — of
        each shard's `posting_lists.bin`. Gate `SFU_SEISMIC_MLOCK_FLOOR=1`.

        WHY THE RESCOPE (the 13.4 GB → ~20 MB/shard correction). The 2026-07-14
        `mlock_floor` locks whole SLABS: posting_lists (1.16 GB) + doc-mapping
        strings/offsets (0.36 GB) + forward_offsets (0.15 GB) = 1.67 GB/shard ×
        8 = **~13.4 GB** — which defeats the min-RAM goal the pin tier exists
        for. The doc-03/11 target of a "~20 MB true floor (Q9's ~5,000 pages)"
        was itself a unit error: doc 10 §7.3 measured 5,093 *major faults*, and
        states in the same row that those faults carry **~1.27 GB** of pages
        (readahead amortizes ~64 pages/fault) — 5,093 × 4 KiB = 20 MB was never
        a measured residency. There is therefore no 20 MB slab to lock; what
        DOES exist is a small always-traversed structural subset *inside*
        posting_lists.bin: the navigation runs, 153.1 MB/shard = 13.2% of the
        slab (measured 2026-08-17, shard0 dv-v2). This method pins a
        budget-capped, largest-run-first slice of exactly that, and nothing
        else — no data extents, no doc-mapping, no forward slabs.

        Dials + guards:
          - `SFU_SEISMIC_MLOCK_FLOOR_MB` — TOTAL budget across shards, default
            **160 MB** (= 20 MB/shard at 8 shards). Split evenly per shard.
          - no-OOM guard (the `load_hotset_and_pin` pattern): the effective
            budget is capped at `MemAvailable − 1.0 GB` headroom.
          - VMA-split cap: ≤ `max_ranges_per_shard` locked ranges (each `mlock`
            splits a VMA; ~33k ranges/shard saturated `vm.max_map_count` in the
            F3/F6 runs — see `_coalesce_extents`). Ranges are page-aligned then
            merged; if still over the cap, the smallest are dropped.
          - layout check: the `_PL_LAYOUT` walk must reproduce
            `posting_lists.bin`'s byte length exactly, else the shard is
            SKIPPED with an error (never mlock bytes we cannot name).
          - selection = largest nav run first, i.e. the longest posting lists =
            the most frequent terms (a size proxy for query-term frequency —
            HEURISTIC, efficacy unmeasured).

        Residency-only ⇒ T1 bit-identical by construction. Returns total bytes
        locked (0 ⇒ nothing mappable/lockable — a logged no-op, never a
        crash)."""
        import time
        t0 = time.perf_counter()
        if budget_mb is None:
            raw = os.environ.get("SFU_SEISMIC_MLOCK_FLOOR_MB", "160")
            try:
                budget_mb = float(raw)
            except ValueError:
                log.warning("SFU_SEISMIC_MLOCK_FLOOR_MB=%r not numeric — using 160", raw)
                budget_mb = 160.0
        headroom_gb = 1.0
        avail_gb = _memavailable_gb()
        cap_mb = max(0.0, (avail_gb - headroom_gb) * 1000.0)
        effective_mb = min(budget_mb, cap_mb)
        if effective_mb <= 0:
            log.warning("mlock_structural_floor: budget 0 after MemAvailable cap "
                        "(avail %.1f GB − %.1f headroom) — floor pin OFF (no-OOM)",
                        avail_gb, headroom_gb)
            return 0
        n_shards = max(1, len(self.shards))
        per_shard_budget = int(effective_mb * 1e6 / n_shards)
        log.info("mlock_structural_floor: budget %.1f MB total (requested %.1f; "
                 "MemAvailable %.1f GB − %.1f headroom) → %.1f MB/shard over %d shards",
                 effective_mb, budget_mb, avail_gb, headroom_gb,
                 per_shard_budget / 1e6, n_shards)
        total = 0
        for shard_dir in self._shard_mmap_dirs:
            if not shard_dir:
                log.debug("mlock_structural_floor: shard mmap_dir unknown — skipped")
                continue
            pl_path = Path(shard_dir) / "posting_lists.bin"
            if not pl_path.is_file():
                log.warning("mlock_structural_floor: %s absent — shard skipped", pl_path)
                continue
            try:
                runs, walked = _postings_nav_runs(shard_dir)
            except (OSError, KeyError, ValueError) as exc:
                log.error("mlock_structural_floor: manifest walk failed for %s (%s)"
                          " — shard skipped", shard_dir, exc)
                continue
            pl_size = pl_path.stat().st_size
            if walked != pl_size:
                log.error("mlock_structural_floor: REFUSING %s — layout walk "
                          "consumed %d B but posting_lists.bin is %d B (reader "
                          "layout drifted from _PL_LAYOUT); shard skipped",
                          shard_dir, walked, pl_size)
                continue
            base = _mapping_base_addr(str(pl_path))
            if base is None:
                log.warning("mlock_structural_floor: %s is not mapped in this "
                            "process (load_mode!=mmap or non-Linux) — shard skipped",
                            pl_path)
                continue
            take: list[tuple[int, int]] = []
            acc = 0
            for off, length in sorted(runs, key=lambda r: -r[1]):
                pg_start = (off // 4096) * 4096
                pg_end = min(pl_size, -(-(off + length) // 4096) * 4096)
                nbytes = pg_end - pg_start
                if acc + nbytes > per_shard_budget and acc > 0:
                    break
                take.append((pg_start, nbytes))
                acc += nbytes
            take.sort()
            merged: list[list[int]] = []
            for start, length in take:
                if merged and start <= merged[-1][0] + merged[-1][1]:
                    merged[-1][1] = max(merged[-1][0] + merged[-1][1],
                                        start + length) - merged[-1][0]
                else:
                    merged.append([start, length])
            if len(merged) > max_ranges_per_shard:
                merged = sorted(sorted(merged, key=lambda r: -r[1])[:max_ranges_per_shard])
            locked = _mlock_addr_ranges(base, [(s, ln) for s, ln in merged])
            total += locked
            log.info("mlock_structural_floor: %s locked %.1f MB in %d ranges "
                     "(nav floor %.1f MB total in this shard; budget %.1f MB)",
                     Path(shard_dir).name, locked / 1e6, len(merged),
                     sum(ln for _, ln in runs) / 1e6, per_shard_budget / 1e6)
        self._floor_mlocked = total > 0
        self._floor_mlocked_bytes = total
        log.info("mlock_structural_floor: locked %.1f MB across %d shards in %.1fs "
                 "(RESCOPED navigation floor — NOT the 13.4 GB whole-slab pin)",
                 total / 1e6, len(self.shards), time.perf_counter() - t0)
        return total

    def mlock_floor(self, include_forward_offsets: bool = True) -> int:
        """F4 LEGACY / OVER-SCOPED (2026-07-14; superseded 2026-08-17 by
        `mlock_structural_floor`). mlocks each shard's whole floor SLABS (the
        same ones `prefault_floor` touches: posting_lists 1.16 GB + doc-mapping
        0.36 GB + optional forward_offsets 0.15 GB = 1.67 GB/shard ⇒ **~13.4 GB
        across the 8 150M shards**). That is a hard RAM commitment ~9× the
        6 GB localized deploy's entire budget, so this path is reachable only
        via `SFU_SEISMIC_MLOCK_FLOOR=full`, kept so the 2026-07-14 measurement
        stays reproducible. `=1` now runs the rescoped navigation floor.

        Call AFTER prefault_floor so pages are faulted in first. Returns total
        bytes locked across shards (0 ⇒ mlock denied — no-op, not crash).
        T1-untouched (residency only). Doc 03 §2 F4."""
        import time
        t0 = time.perf_counter()
        total = 0
        for idx in self.shards:
            fn = getattr(idx, "mlock_floor", None)
            if fn is None:
                log.debug("mlock_floor: shard lacks the hook (older .so?) — skipped")
                continue
            total += int(fn(include_forward_offsets))
        self._floor_mlocked = True
        self._floor_mlocked_bytes = total
        log.info("mlock_floor: locked %.2f GB across %d shards in %.1fs "
                 "(include_forward_offsets=%s)",
                 total / 1e9, len(self.shards),
                 (time.perf_counter() - t0), include_forward_offsets)
        return total

    def load_hotset_and_pin(self, budget_gb: float,
                            budget_name: str | None = None) -> float:
        """F3 (Phase 3): per shard, load the F2 hot-set sidecar and mlock its
        extents, budget-capped at min(budget_gb, MemAvailable − floor − headroom).
        Largest-coverage extents first (the sidecar is already sorted by touch
        count desc, then coalesced; this fn takes extents in order until the
        per-shard budget is reached). The no-OOM guarantee: the budget check
        refuses to pin past MemAvailable minus the floor + a headroom margin.

        Sidecar lookup: `<shard>.mmap/hotset_<budget_name>.json`; if
        `budget_name` is None it's derived from budget_gb ({gb:.1f}gb → nearest
        of hot50_1.6gb / hot80_4.2gb / full_touched). The loader REFUSES-AND-LOGS
        on version-key mismatch (the F2 contract: E8 reconversion must fail loud,
        not pin garbage). T1-untouched (residency only). Doc 03 §2 F3.

        Returns total GB pinned across shards (0 ⇒ sidecar missing/mismatched or
        mlock denied — the pin tier degrades to no-op, never a crash)."""
        import json as _json
        import time
        budget_aliases = {
            1.6: "hot50_1.6gb", 4.2: "hot80_4.2gb",
        }
        if budget_name is None:
            budget_name = budget_aliases.get(round(budget_gb, 1), "full_touched")
        avail_gb = _memavailable_gb()
        floor_gb = 1.5
        headroom_gb = 1.0
        cap_gb = max(0.0, avail_gb - floor_gb - headroom_gb)
        effective_budget_gb = min(budget_gb, cap_gb)
        log.info("mlock_ranges: budget %.2f GB (requested %.2f); MemAvailable %.1f GB "
                 "− floor %.1f − headroom %.1f → cap %.2f GB; sidecar=%s",
                 effective_budget_gb, budget_gb, avail_gb, floor_gb, headroom_gb,
                 cap_gb, budget_name)
        if effective_budget_gb <= 0:
            log.warning("mlock_ranges: pin budget 0 after MemAvailable cap "
                        "(avail %.1f − %.1f − %.1f) — pin tier OFF (no-OOM)",
                        avail_gb, floor_gb, headroom_gb)
            self._hotset_pinned_gb = 0.0
            return 0.0

        t0 = time.perf_counter()
        per_shard_budget_bytes = int(effective_budget_gb * 1e9 / max(1, len(self.shards)))
        total_bytes = 0
        plan = []
        for idx, shard_dir in zip(self.shards, self._shard_mmap_dirs):
            mlock_fn = getattr(idx, "mlock_ranges", None)
            if mlock_fn is None:
                log.debug("mlock_ranges: shard lacks the hook (older .so?) — skipped")
                continue
            if not shard_dir:
                log.debug("mlock_ranges: shard mmap_dir unknown — sidecar load skipped")
                continue
            sidecar_path = Path(shard_dir) / f"hotset_{budget_name}.json"
            if not sidecar_path.is_file():
                log.warning("mlock_ranges: sidecar absent %s — pin skipped for this shard "
                            "(run f1_hotset_generator.py)", sidecar_path)
                continue
            sc = _json.loads(sidecar_path.read_text())
            if sc.get("schema") != "seismic.hotset.v1":
                log.warning("mlock_ranges: %s schema %r != seismic.hotset.v1 — skipped",
                            sidecar_path, sc.get("schema"))
                continue
            vk = sc.get("version_keys", {})
            shard_man_path = Path(shard_dir) / "manifest.json"
            shard_man = _json.loads(shard_man_path.read_text())
            miss = _hotset_version_mismatch(vk, shard_man)
            if miss:
                log.error("mlock_ranges: REFUSING to pin %s — version-key mismatch: %s "
                          "(the shard was re-converted since the sidecar was generated; "
                          "re-run f1_hotset_generator.py). Pin tier OFF for this shard.",
                          sidecar_path, miss)
                continue
            extents = sc.get("extents", [])
            acc = 0
            take = []
            for (page_start, page_len) in extents:
                nbytes = page_len * 4096
                if acc + nbytes > per_shard_budget_bytes and acc > 0:
                    break
                take.append((page_start, page_len))
                acc += nbytes
            take = _coalesce_extents(take)
            while take and sum(ln for _, ln in take) * 4096 > per_shard_budget_bytes * 1.1:
                take = take[:-1]
            plan.append((Path(shard_dir).name, mlock_fn, take))
        for shard_name, mlock_fn, take in plan:
            locked = int(mlock_fn(take))
            total_bytes += locked
            log.info("mlock_ranges: %s pinned %.2f GB (%d coalesced extents; budget %.2f GB)",
                     shard_name, locked / 1e9, len(take),
                     per_shard_budget_bytes / 1e9)
        self._hotset_pinned_gb = total_bytes / 1e9
        log.info("mlock_ranges: pinned %.2f GB total across %d shards in %.1fs",
                 self._hotset_pinned_gb, len(self.shards),
                 (time.perf_counter() - t0))
        return self._hotset_pinned_gb

    def prefault_hotset(self, budget_gb: float,
                        budget_name: str | None = None) -> float:
        """F6 (Phase 6): PREFFAULT (not mlock) the F2 sidecar's hot extents
        into the kernel page cache at LOAD so the first queries hit a
        pre-warmed hot set (the cold-p95 lever). Unlike `load_hotset_and_pin`,
        pages stay kernel-RECLAIMABLE (no mlock, no OOM risk, no CAP_IPC_LOCK
        needed). Gate: `SFU_SEISMIC_PREFLOOR_HOTSET=1`. Budget split =
        budget_gb/8 per shard (same global-coverage semantics as F1). T1-untouched
        (residency only — a fault-in read of read-only data). Doc 03 §3
        "cold-start-sensitive" row. Returns GB prefaulted."""
        import json as _json
        import time
        budget_aliases = {1.6: "hot50_1.6gb", 4.2: "hot80_4.2gb"}
        if budget_name is None:
            budget_name = budget_aliases.get(round(budget_gb, 1), "full_touched")
        t0 = time.perf_counter()
        per_shard_budget_bytes = int(budget_gb * 1e9 / max(1, len(self.shards)))
        total_bytes = 0
        plan = []
        for idx, shard_dir in zip(self.shards, self._shard_mmap_dirs):
            pf_fn = getattr(idx, "prefault_ranges", None)
            if pf_fn is None or not shard_dir:
                log.debug("prefault_hotset: shard lacks prefault_ranges/dir — skipped")
                continue
            sidecar_path = Path(shard_dir) / f"hotset_{budget_name}.json"
            if not sidecar_path.is_file():
                log.warning("prefault_hotset: sidecar absent %s — skipped", sidecar_path)
                continue
            sc = _json.loads(sidecar_path.read_text())
            if sc.get("schema") != "seismic.hotset.v1":
                continue
            shard_man = _json.loads((Path(shard_dir) / "manifest.json").read_text())
            miss = _hotset_version_mismatch(sc.get("version_keys", {}), shard_man)
            if miss:
                log.error("prefault_hotset: REFUSING %s — version-key mismatch: %s "
                          "(re-run f1_hotset_generator.py)", sidecar_path, miss)
                continue
            extents = sc.get("extents", [])
            acc = 0
            take = []
            for (page_start, page_len) in extents:
                nbytes = page_len * 4096
                if acc + nbytes > per_shard_budget_bytes and acc > 0:
                    break
                take.append((page_start, page_len))
                acc += nbytes
            take = _coalesce_extents(take)
            plan.append((Path(shard_dir).name, pf_fn, take, acc))
        for shard_name, pf_fn, take, acc in plan:
            pf_fn(take)
            total_bytes += acc
            log.info("prefault_hotset: %s prefaulted %.2f GB (%d extents)",
                     shard_name, acc / 1e9, len(take))
        gb = total_bytes / 1e9
        log.info("prefault_hotset: touched %.2f GB total across %d shards in %.1fs",
                 gb, len(self.shards), (time.perf_counter() - t0))
        return gb

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
        methods return the same global top-k (bit-identical, same `k'` over-fetch).

        WI-10 (2026-07-17): when `SFU_SEISMIC_SHARD_FAULT_BOUNDARY=1`, each
        `_search_one` runs under a per-shard timeout + the fault tracker: a shard
        that throws or times out returns `[]` (no federation contribution) + is
        marked failed for the reprobe cooldown. The OTHER shards still serve →
        "one shard down, seven serve." When OFF (default) the path is unchanged
        (byte-identical to pre-WI-10: a thrown search propagates as before)."""
        if not q:
            return []
        qcomp, qvals, qc, kp = _prepare_query(q, top_k, self._string_dtype,
                                               query_cut, k_prime)

        def _search_one(idx):
            return idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                              k=kp, query_cut=qc, heap_factor=heap_factor)

        if not self._fault_boundary:
            per_shard = self._fan_out(_search_one)
            return _merge_topk(per_shard, top_k)
        per_shard = self._fan_out(self._guarded_search_one(_search_one))
        return _merge_topk([r if r is not None else [] for r in per_shard], top_k)

    def _guarded_search_one(self, _search_one):
        """Wrap `_search_one` so each shard's search is fault-bounded: a None
        shard (failed at load) or a thrown/timed-out search → `[]` + a recorded
        fault. Used ONLY when the fault boundary is ON (else `_search_one` runs
        bare, byte-identical to pre-WI-10). Returns a closure `_search_one(idx)`
        with the SAME signature so `_fan_out` (parallel OR sequential) is unchanged
        — the fence is the same in BOTH methods (the cascade property)."""
        timeout = _shard_search_timeout_s()

        def _guarded(idx):
            pos = id(idx)
            tr = None
            for i, s in enumerate(self.shards):
                if i < len(self._shard_faults) and s is idx:
                    tr = self._shard_faults[i]
                    break
            if idx is None or tr is None:
                return []
            if tr.is_failed():
                return []
            try:
                fut = self._probe_executor.submit(_search_one, idx)
                res = fut.result(timeout=timeout)
                tr.on_success()
                return res
            except cf.TimeoutError:
                tr.on_fail("search_timeout")
                log.warning("WI-10: shard search TIMEOUT (>%ss) → marked down",
                            timeout)
                return []
            except Exception as exc:
                tr.on_fail(f"search: {type(exc).__name__}: {str(exc)[:100]}")
                log.warning("WI-10: shard search failed (%s) → marked down",
                            tr.last_reason)
                return []
        return _guarded

    def degraded_shards(self) -> list[str]:
        """Names of shards currently marked failed (the steady-state degraded
        set). Surfaced to `/health` + the WI-10 proof. Empty when the boundary is
        OFF (no shards are ever marked)."""
        if not self._fault_boundary:
            return []
        out = []
        for name, tr in zip(self._shard_names, self._shard_faults):
            if tr.is_failed():
                out.append(name)
        return sorted(out)

    def fault_status(self) -> list[dict]:
        """Per-shard fault state (for /health + the proof harness). Empty list
        when the boundary is OFF."""
        if not self._fault_boundary:
            return []
        out = []
        for i, (name, tr) in enumerate(zip(self._shard_names, self._shard_faults)):
            with tr._lock:
                out.append({"shard": name, "position": i,
                            "loaded": self.shards[i] is not None,
                            "failed": tr.opened_at is not None,
                            "fails": tr.fails,
                            "last_reason": tr.last_reason})
        return out

    @property
    def _probe_executor(self):
        """A small persistent executor for the guarded search's per-shard timeout
        (created lazily, once; reused). Only used when the fault boundary is ON."""
        if getattr(self, "_pe", None) is None:
            self._pe = cf.ThreadPoolExecutor(max_workers=max(1, len(self.shards)),
                                              thread_name_prefix="shard-fault-probe")
        return self._pe

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
            release = getattr(idx, "release_pages", None)
            if release is not None:
                release()
            else:
                log.debug("sequential: shard has no release_pages(); "
                          "mechanism (B) skipped (older .so?)")
        return out


class HybridSeismicBackend(_SeismicBackendBase):
    """Cold-start hybrid serving method (Q7, 2026-07-10): serve SEQUENTIALLY
    while the index is cold, FLIP to PARALLEL once it is warm. Captures both
    regimes: sequential wins cold (2159 vs 2687 ms parallel cold p50 — the
    8-way cold fan-out contends on the 9p/disk channel at 1.34 GB peak vs
    25.2 GB; measured `e5_fullcorpus_cold_container_*.json` 2026-07-09), and
    parallel wins warm (80–101 ms vs sequential 367 ms — max-of-shards ≪
    sum-of-shards once pages are resident).

    The flip is a STATE SIGNAL, not a timer (pre-registered 2026-07-10, see
    doc 12 §3 Q7 + `SESSION_PROMPT_OPEN_QUEUE.md`). Two signals, both
    pre-registered before any measurement:

      - Signal A (the real signal): flip to parallel once `traverse_ms` drops
        below `flip_threshold` for `flip_consecutive` (2) consecutive queries,
        where `flip_threshold` = the geometric mean of the first
        `warmup_for_threshold` (2) cold queries' traverse_ms × `warm_frac`
        (0.25) — i.e. once traversal has fallen to under a quarter of its cold
        cost (the warm regime). The threshold is derived from the cold queries
        themselves, so it self-scales per host/index without a magic constant.
      - Signal B (the dumb control): flip after exactly `flip_after_n`
        (3) queries. Held as the control arm — isolates "the state signal
        triggers at the right time" from "any fixed count would've been
        fine." Selected by env (`SFU_SEISMIC_HYBRID_SIGNAL=count`).

    A flip is triggered as soon as EITHER armed signal fires (OR semantics):
    signal A catches the genuine warm transition early; signal B is the
    backstop that guarantees a flip even if signal A's threshold is never
    crossed (e.g. a host whose warm is still > cold×0.25).

    **The flip CANNOT change results** (load-bearing, like parallel≡sequential):
    both `_fan_out_sequential` and `_fan_out_parallel` feed the SAME shared pure
    `_merge_topk` with identical per-shard results (the encoded qvec is shared
    across shards → scores in one dot-product space → order-independent merge).
    So a query served on the flip boundary — sequential for query N, parallel
    for query N+1 — still returns the bit-identical top-k. Asserted by the T1
    parity test (extended to hybrid in `test_seismic_sequential.py`).

    Implementation — the hybrid owns BOTH fan-outs and switches at the
    top-level `_fan_out` (the only per-query behavior the base defers). No
    new merge, no new mutable state crossing the method boundary beyond the
    flip counter + threshold (thread-safe via a lock so a concurrent caller
    can't observe a torn flip). The `_executor` is constructed eagerly (cheap)
    so the warm arm has zero setup latency at flip time.

    Env knobs (all pre-registered, opt-in; defaults are the pre-registered
    values so an unset env reproduces the intended hybrid behavior):
      SFU_SEISMIC_HYBRID_SIGNAL   = adaptive|count  (default adaptive = signal A
                                                  + B backstop; count = B only)
      SFU_SEISMIC_HYBRID_WARM_FRAC   warm/cold traverse ratio threshold
                                                  (default 0.25)
      SFU_SEISMIC_HYBRID_FLIP_N      count-arm query count (default 3)
      SFU_SEISMIC_HYBRID_WARMUP      cold queries that seed the threshold
                                                  (default 2)
      SFU_SEISMIC_HYBRID_CONSEC      consecutive warm queries to flip (default 2)
      SFU_SEISMIC_HYBRID_DISABLE     =1 force parallel from query 1 (the
                                                  hybrid machinery off but the
                                                  class still usable — A/B control)
    """

    federation = "hybrid"

    def __init__(self, index_paths: list[str], splade_model_path: str = "models/splade_onnx_fused",
                 load_mode: str = "stock"):
        super().__init__(index_paths, splade_model_path=splade_model_path,
                         load_mode=load_mode)
        self._executor = cf.ThreadPoolExecutor(
            max_workers=max(1, len(self.shards)),
            thread_name_prefix="seismic-shard")

        env = os.environ.get
        self._signal = env("SFU_SEISMIC_HYBRID_SIGNAL", "adaptive").strip().lower()
        if self._signal not in ("adaptive", "count"):
            raise ValueError(
                f"SFU_SEISMIC_HYBRID_SIGNAL must be 'adaptive' or 'count', "
                f"got {self._signal!r}")
        self._warm_frac = float(env("SFU_SEISMIC_HYBRID_WARM_FRAC", "0.25"))
        self._flip_after_n = int(env("SFU_SEISMIC_HYBRID_FLIP_N", "3"))
        self._warmup_for_threshold = int(env("SFU_SEISMIC_HYBRID_WARMUP", "2"))
        self._consec_needed = int(env("SFU_SEISMIC_HYBRID_CONSEC", "2"))
        self._force_parallel = env("SFU_SEISMIC_HYBRID_DISABLE", "0") == "1"

        self._query_count = 0
        self._flip_threshold = None
        self._cold_traverse_samples = []
        self._consecutive_warm = 0
        self._flipped = self._force_parallel
        self._lock = threading.Lock()
        if self._force_parallel:
            log.info("hybrid: DISABLED (force_parallel from query 1)")


    def _fan_out_parallel(self, _search_one) -> list:
        return list(self._executor.map(_search_one, self.shards))

    def _fan_out_sequential(self, _search_one) -> list:
        out = []
        for idx in self.shards:
            out.append(_search_one(idx))
            release = getattr(idx, "release_pages", None)
            if release is not None:
                release()
            else:
                log.debug("hybrid(seq): shard has no release_pages(); "
                          "mechanism (B) skipped (older .so?)")
        return out

    def _maybe_flip(self, traverse_ms: float):
        """Update the adaptive signal + count backstop; flip to parallel when
        either fires. Called once per query under the lock. traverse_ms is the
        just-measured per-query traverse wall — the flip DECISION is made from
        it, but the flip itself never touches results (the merge is shared)."""
        if self._flipped:
            return
        self._query_count += 1

        if (self._signal == "adaptive"
                and len(self._cold_traverse_samples) < self._warmup_for_threshold):
            self._cold_traverse_samples.append(traverse_ms)
            if len(self._cold_traverse_samples) == self._warmup_for_threshold:
                product = 1.0
                for s in self._cold_traverse_samples:
                    product *= max(s, 1e-6)
                import math
                cold = math.exp(math.log(product) / len(self._cold_traverse_samples))
                self._flip_threshold = cold * self._warm_frac
                log.info("hybrid(adaptive): cold geomean %.1f ms × %.2f = "
                         "flip_threshold %.1f ms (flip after %d consec warm)",
                         cold, self._warm_frac, self._flip_threshold,
                         self._consec_needed)

        if self._signal == "adaptive" and self._flip_threshold is not None:
            if traverse_ms < self._flip_threshold:
                self._consecutive_warm += 1
                if self._consecutive_warm >= self._consec_needed:
                    self._flipped = True
                    log.info("hybrid(adaptive): FLIP seq→par at query %d "
                             "(%d consecutive warm < %.1f ms)",
                             self._query_count, self._consecutive_warm,
                             self._flip_threshold)
            else:
                self._consecutive_warm = 0

        if self._query_count >= self._flip_after_n and not self._flipped:
            self._flipped = True
            log.info("hybrid(count-backstop): FLIP seq→par at query %d "
                     "(>= %d)", self._query_count, self._flip_after_n)

    def _fan_out(self, _search_one) -> list:
        if self._force_parallel:
            return self._fan_out_parallel(_search_one)
        with self._lock:
            use_parallel = self._flipped
        if use_parallel:
            return self._fan_out_parallel(_search_one)
        return self._fan_out_sequential(_search_one)

    def search_encoded(self, q: dict[str, float], top_k: int,
                       query_cut: int | None = None,
                       heap_factor: float = 0.8,
                       k_prime: int | None = None) -> list[tuple[str, float]]:
        """Same as the base `search_encoded`, but records the per-query traverse
        time so the adaptive signal can evaluate the flip. The flip decision is
        made from traverse_ms here (not in `_fan_out`, which can't time itself);
        the merge (`_merge_topk`) is the shared pure one, so results are
        bit-identical to parallel/sequential regardless of which arm ran."""
        if not q:
            return []
        qcomp, qvals, qc, kp = _prepare_query(q, top_k, self._string_dtype,
                                               query_cut, k_prime)

        def _search_one(idx):
            return idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                              k=kp, query_cut=qc, heap_factor=heap_factor)

        import time
        t0 = time.perf_counter()
        per_shard = self._fan_out(_search_one)
        traverse_ms = (time.perf_counter() - t0) * 1000.0
        if not self._force_parallel:
            with self._lock:
                self._maybe_flip(traverse_ms)
        return _merge_topk(per_shard, top_k)

    def search_with_timing(self, query: str, top_k: int,
                           query_cut: int | None = None,
                           heap_factor: float = 0.8,
                           k_prime: int | None = None,
                           ) -> tuple[list[tuple[str, float]], float, float]:
        """`search()` but returns (results, encode_ms, traverse_ms). Overridden
        only so the adaptive flip sees the SAME traverse_ms the bench records —
        the base impl ts `search_encoded` which already calls `_maybe_flip`, so
        the override just reuses it (no double-flip: the flip is idempotent)."""
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


class ShardedSeismicBackend(_SeismicBackendBase):
    """Back-compat selector — NOT a serving method. `__new__` returns the matching
    concrete serving class (`ParallelSeismicBackend` default |
    `SequentialSeismicBackend` | `HybridSeismicBackend`), so an instance is always
    one of the real methods. Kept so every existing call site keeps working
    unchanged:

      - `ShardedSeismicBackend(index_paths, load_mode="mmap")`  → parallel (default)
      - `ShardedSeismicBackend(..., federation="sequential")`  → sequential
      - `ShardedSeismicBackend(..., federation="hybrid")`     → hybrid (Q7)
      - `ShardedSeismicBackend.from_manifest(manifest, ...)`    → parallel (default)

    New code should construct `ParallelSeismicBackend` / `SequentialSeismicBackend`
    / `HybridSeismicBackend` directly. The three load-bearing parity harnesses
    (`g6_rrf_parity_fullcorpus.py`, `reconcile_legoverlap.py`,
    `serve_footprint_bench.py`) use this selector without a `federation` kwarg —
    their bit-identical G6/overlap results depend on the default staying `parallel`.
    """

    federation = "parallel"

    def __new__(cls, index_paths: list[str], splade_model_path: str = "models/splade_onnx_fused",
                load_mode: str = "stock", federation: str = "parallel"):
        if federation not in ("parallel", "sequential", "hybrid"):
            raise ValueError(
                f"federation must be 'parallel', 'sequential', or 'hybrid', "
                f"got {federation!r}")
        if federation == "sequential":
            concrete = SequentialSeismicBackend
        elif federation == "hybrid":
            concrete = HybridSeismicBackend
        else:
            concrete = ParallelSeismicBackend
        return concrete(index_paths, splade_model_path=splade_model_path, load_mode=load_mode)
