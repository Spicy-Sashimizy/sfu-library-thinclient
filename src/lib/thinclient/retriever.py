"""ThinClientRetriever — drop-in replacement for OpenSearchRetriever.

Same public surface (search / dense_search / is_available, same result dict
shape) backed by tantivy + BMP + usearch over a built index root. The
FederatedSearchRouter and reranker need zero changes.

Cross-section score merging:
  - SPLADE (BMP) and dense scores are corpus-independent dot products — exact
    merge across sections/shards.
  - BM25F scores use per-section IDF, so cross-section merge is approximate
    (same caveat as multi-shard OpenSearch; measured 40/80 score-multiset drift
    for 2-shard in docs/archive/COMPRESSION_EVAL_RESULTS.md). RRF fusion downstream is
    rank-based per leg, which absorbs most of the drift.

Filters: tantivy enforces year/type/is_oa natively (fast fields); BMP/usearch
legs over-fetch and post-filter against meta.sqlite (the sidecar-mask pattern
from docs/THIN_CLIENT_STACK_RESEARCH.md).

Abstract policy: hot sections answer locally from the zstd-dict sidecar; ids
missing locally are batch-fetched from the OpenAlex API (inverted-abstract
parser in lib.openalex) when remote_abstracts=True — BEFORE rerank, never
display-only.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from lib.thinclient.sections import ERA_BOUNDARY_YEAR, ERAS, classify_query

logger = logging.getLogger("sfu_library_mcp")

# Per-leg in-memory metrics (reset on restart), mirrors tools._metrics.
_leg_metrics: dict[str, dict] = {}
_metrics_lock = threading.Lock()


def _mem_available_gb() -> float | None:
    """MemAvailable in GiB (kernel's reclaim-aware free estimate), or None if
    /proc/meminfo is unreadable (non-Linux)."""
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable"):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        return None
    return None


# Passthrough/network filesystems where mmap page cache does NOT stay resident,
# so parallel federation's "never release pages" advantage is moot (the pages
# get dropped between queries anyway). There, SequentialSeismicBackend's lower
# RAM floor (releases each shard's slabs after searching it) is the better
# default. On a native local disk (ext4/xfs on a DO droplet) pages DO stay
# resident, so parallel keeps the working set warm (WI-1 warm p50 ~47 ms) and
# sequential would sabotage that by releasing — hence parallel there.
# NOTE: federation mode is roughly latency-NEUTRAL for a genuinely cold fault
# (measured 2026-07-18, page cache dropped: parallel p50 9134 ms vs sequential
# 8747 ms); the real cold-latency lever is the filesystem itself (see
# _stage_shards_local), not this choice.
_SLOW_FEDERATION_FSTYPES = {"9p", "virtiofs", "nfs", "nfs4", "cifs", "smb3", "fuse.sshfs"}


def _fstype_for_path(path: str) -> str | None:
    """Best-effort filesystem type under `path` via the longest matching mount
    in /proc/mounts (Linux only; None elsewhere or on error)."""
    try:
        target = os.path.realpath(path)
        best_mp, best_type = "", None
        with open("/proc/mounts") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mp, fstype = parts[1], parts[2]
                if (target == mp or target.startswith(mp.rstrip("/") + "/")) \
                        and len(mp) > len(best_mp):
                    best_mp, best_type = mp, fstype
        return best_type
    except OSError:
        return None


def _dir_size(path: Path) -> int:
    total = 0
    for dp, _, fns in os.walk(path):
        for fn in fns:
            try:
                total += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return total


def _marker_bytes(dst: Path) -> int:
    """Size of the `.staged_ok` marker (excluded when comparing a staged dir's
    size to its marker-less source)."""
    try:
        return (dst / ".staged_ok").stat().st_size
    except OSError:
        return 0


def _stage_shards_local(manifest_path: str, stage_dir: str) -> str:
    """Copy a manifest's shard mmap dirs to a fast local `stage_dir` and return a
    new manifest path (written under stage_dir) whose `mmap_dir` fields point at
    the staged copies. Idempotent: a shard already present with a matching byte
    size is not re-copied.

    Why: SEISMIC serves by mmap'ing the forward index; on a 9p/virtiofs/NFS mount
    each random page fault costs ~0.5 ms (measured 9p 2026-07-18: ~1830 faults/s),
    so a query that faults ~15 k pages takes ~8 s and page cache does not hold.
    On a native local FS the same faults run ~160–240× faster (~300 k/s) AND stay
    resident — the WI-1 warm p50 ~47 ms path. This is the portable fix: point
    SFU_SEISMIC_STAGE_DIR at native block storage. A DO droplet with the index
    already on its local disk needs no staging (this is a no-op there); it exists
    for hosts where the index arrives on a slow/passthrough mount.
    """
    import shutil
    repo_root = Path(__file__).resolve().parents[3]
    src_p = Path(manifest_path)
    if not src_p.is_absolute() and not src_p.exists():
        src_p = repo_root / manifest_path
    data = json.load(open(src_p))
    shards = data.get("shards") if isinstance(data, dict) else None
    if not shards:
        return manifest_path  # unknown shape — serve as-is
    stage = Path(stage_dir)
    stage.mkdir(parents=True, exist_ok=True)
    for s in shards:
        rel = s.get("mmap_dir")
        if not rel:
            continue
        src = Path(rel)
        if not src.is_absolute():
            src = repo_root / rel
        dst = stage / src.name
        # Cheap idempotency: a `.staged_ok` marker records the source byte size
        # from the completed copy. Skip when it matches — avoids re-walking the
        # 42 GB source tree over a slow mount on every boot (that walk alone can
        # take minutes on 9p). Only compute the source size when the marker is
        # missing/mismatched (i.e. a genuine (re)stage is needed).
        marker = dst / ".staged_ok"
        want = None
        if marker.is_file():
            try:
                want = int(marker.read_text().strip())
            except (OSError, ValueError):
                want = None
        src_sz = _dir_size(src)
        # Adopt an existing correct copy that lacks a marker (e.g. staged by
        # scripts/stage_seismic_local.sh, which uses cp): size-match, then write
        # the marker so future boots skip the source walk.
        if dst.is_dir() and want is None and _dir_size(dst) - _marker_bytes(dst) == src_sz:
            marker.write_text(str(src_sz)); want = src_sz
        if dst.is_dir() and want == src_sz:
            logger.info("SEISMIC stage: %s already staged (%.1f GB), skipping",
                        dst.name, src_sz / 1e9)
        else:
            t0 = time.perf_counter()
            logger.info("SEISMIC stage: copying %s -> %s", src.name, stage)
            if dst.is_dir():
                shutil.rmtree(dst)  # partial/stale copy — start clean
            shutil.copytree(src, dst)
            marker.write_text(str(src_sz))
            logger.info("SEISMIC stage: %s copied (%.1f GB) in %.0fs",
                        dst.name, src_sz / 1e9, time.perf_counter() - t0)
        s["mmap_dir"] = str(dst)  # absolute staged path
    staged_manifest = stage / "staged_manifest.json"
    with open(staged_manifest, "w") as fh:
        json.dump(data, fh)
    return str(staged_manifest)


def _auto_federation_mode(sample_path: str) -> str:
    """Federation default when SFU_SEISMIC_FEDERATION is unset: 'sequential' when
    the shards sit on a slow passthrough FS (see _SLOW_FEDERATION_FSTYPES),
    'parallel' on a native local disk. Portability guard — the serving default is
    correct on both the 9p dev container and a native-ext4 droplet without any
    per-host env tuning. An explicit env var always overrides this."""
    fstype = _fstype_for_path(sample_path)
    if fstype and fstype.lower() in _SLOW_FEDERATION_FSTYPES:
        return "sequential"
    return "parallel"


def _guard_load_mem(next_shard_bytes: int, floor_gb: float, ctx: str) -> None:
    """Abort the load CLEANLY if pulling the next BMP shard would drive
    MemAvailable below `floor_gb`. BMP loads resident (~3.07x on disk), so a big
    shard can swing several GB; we project the shard's resident cost and refuse
    *before* the allocation rather than letting the OOM-killer SIGKILL us mid-
    construction (which leaves no actionable error). See BMP_RESIDENT_RATIO."""
    avail = _mem_available_gb()
    if avail is None:
        return
    projected = next_shard_bytes / 1073741824 * BMP_RESIDENT_RATIO
    if avail - projected < floor_gb:
        raise RuntimeError(
            f"thinclient load aborted at {ctx}: MemAvailable {avail:.1f} GB, "
            f"next BMP shard needs ~{projected:.1f} GB resident "
            f"(~{BMP_RESIDENT_RATIO:.2f}x on disk), which would breach the "
            f"{floor_gb:.1f} GB floor. BMP has no mmap mode; the full 150M "
            f"SPLADE set is ~211 GB resident and cannot serve on this host. "
            f"Raise host RAM, serve fewer sections, or set "
            f"SFU_LOAD_MEM_FLOOR_GB lower to override (will risk OOM-kill).")


def _record_leg(leg: str, ms: float, error: bool = False) -> None:
    with _metrics_lock:
        m = _leg_metrics.setdefault(leg, {"count": 0, "errors": 0, "total_ms": 0.0})
        m["count"] += 1
        m["total_ms"] += ms
        if error:
            m["errors"] += 1


def snapshot_leg_metrics() -> dict:
    """A point-in-time copy of the cumulative per-leg metrics
    ({leg: {count, errors, total_ms}}). The serve query-log (lib.serve_query_log)
    snapshots before+after a served query and diffs total_ms/count to attribute
    end-to-end latency to the BM25F / SPLADE / dense legs individually — the
    per-leg shape the disk-streaming skew analysis needs (which leg's results
    dominate the hot set). Process-global; thread-safe."""
    with _metrics_lock:
        return {leg: dict(m) for leg, m in _leg_metrics.items()}


def leg_metrics_delta(before: dict) -> dict:
    """Diff of cumulative leg total_ms since a `before` snapshot → the per-leg
    ms a single query cost. Returns {leg: ms} for legs that advanced (others
    omitted). The serve-query-log path uses this to emit per-leg latencies
    without the retriever plumbing a callback through every leg."""
    after = snapshot_leg_metrics()
    out = {}
    for leg, m in after.items():
        b = before.get(leg, {"count": 0, "total_ms": 0.0})
        d_ms = m["total_ms"] - b["total_ms"]
        if d_ms > 0:
            out[leg] = round(d_ms, 2)
    return out


# BMP is a load-into-memory engine (no mmap mode in 0.2.6): `bmp.Searcher`
# deserializes each *.bmp shard into ANONYMOUS RAM at a measured ~3.07x its
# on-disk size (probe 2026-06-17, 569 MB shard -> 1747 MB steady-state RSS;
# ratio holds from 12 MB to 569 MB shards). The full 150M SPLADE set is 68.6 GB
# on disk -> ~211 GB resident. _load() builds ALL shards eagerly, so on a host
# that can't hold the set the process is OOM-killed *inside* construction —
# before any per-query mem-floor guard can run. The guard below samples
# MemAvailable before each shard and aborts CLEANLY (RuntimeError) instead, so
# the failure is diagnosable rather than a SIGKILL. Gate: SFU_LOAD_MEM_FLOOR_GB.
BMP_RESIDENT_RATIO = 3.07       # measured anon-RAM expansion of bmp.Searcher
LOAD_MEM_FLOOR_GB = 1.5         # abort load if MemAvailable would drop below this

RRF_K = 60
QUANT_SCALE = 70                # must match builder.QUANT_SCALE (saturation-free)
SPLADE_QUERY_TERMS = 64         # top query terms, same cap as the OpenSearch leg
OVERFETCH = 4                   # sparse/dense over-fetch multiplier (no filters)
OVERFETCH_FILTERED = 10         # ... when post-filtering
# BMP block-max approximation: measured on the 1M build (10 SPLADE queries,
# 64 terms): alpha=0.8 keeps top-50 overlap 1.000 at -29% latency; beta<1.0
# prunes query terms and visibly costs quality (0.5 -> overlap 0.80).
BMP_ALPHA = 0.8
BMP_BETA = 1.0


class ThinClientRetriever:
    """Retriever over a thin-client index root (tantivy + BMP + usearch)."""

    def __init__(
        self,
        index_root: str = "",
        splade_model_path: str = "",
        dense_model_path: str = "",
        remote_abstracts: bool = True,
        openalex_mailto: str = "",
        query_log_path: str = "",
    ):
        repo_root = Path(__file__).resolve().parents[3]
        self.root = Path(index_root or repo_root / "data" / "thinclient_index")
        # SFU_SPLADE_MODEL_PATH lets serving point at a different query encoder
        # without a code change. Default 2026-07-09 (D2): the offline bert-FUSED
        # export (same fp32 weights, exact GELU) — 1.11x encode, merged
        # overlap@10 0.999 vs unfused (doc seismic_150m_testbed/08 §D).
        # Regenerate via scripts/seismic_testbed/d2_ort_fusion_matrix.py;
        # models/splade_onnx is the unfused fallback.
        self.splade_model_path = (splade_model_path or os.environ.get("SFU_SPLADE_MODEL_PATH")
                                  or str(repo_root / "models" / "splade_onnx_fused"))
        self.dense_model_path = dense_model_path or str(repo_root / "models" / "sfu-academic-embed-v5")
        self.remote_abstracts = remote_abstracts
        self.openalex_mailto = openalex_mailto
        self.query_log_path = query_log_path
        self._qlog_lock = threading.Lock()

        self._lock = threading.Lock()
        self._sections: dict[str, dict] = {}   # name -> {tantivy, searcher, bmp:[...]}
        self._abstract_stores: dict[str, Any] = {}
        self._meta: sqlite3.Connection | None = None
        self._meta_numeric = False
        self._meta_lock = threading.Lock()
        self._dense: dict | None = None
        self._dense_cache = None   # query-driven warm cache (dense_cache.py)
        self._loaded = False

        # Serving gate. SFU_SPLADE_BACKEND selects the SPLADE leg engine:
        #   seismic (default) — federated SEISMIC over the 8 dotvbyte mmap shards
        #                      (Path C, anon floor ~0; dv 25.2 GB page-cache
        #                      resident at 150M vs f16's 41.9 GB — the only
        #                      layout that fits this 32 GB container, G8b);
        #   qdrant           — Qdrant on_disk sparse collection (the 2026-06-24
        #                      default; being split into the archival container,
        #                      reachable via SFU_SPLADE_QDRANT_URL — the one-env
        #                      rollback path);
        #   bmp              — load-into-RAM BMP shards (~211 GB resident at 150M,
        #                      forensics only; 150M artifacts deleted 2026-06-25,
        #                      see docs/bmp_decommission_plan/).
        # Default flipped qdrant→seismic 2026-07-06: G6 system parity PASS
        # (paired-delta 2026-06-30 — SEISMIC leg NDCG@10 0.9262 vs Qdrant 0.9065,
        # Δ=+0.0197, 95% CI +0.0098..+0.0297 clears zero, n=120), C2.5
        # MMAP_SERVE_READY, dv full-corpus parity 0.9906 vs f16 (G8d, accepted
        # 2026-07-05; shards 1-2 at 0.985 — E8 is the pre-registered recovery
        # lever). See docs/THIN_CLIENT_SWAP.md + docs/SEISMIC_ARCHIVE_SPLIT.md.
        self._splade_backend = os.environ.get("SFU_SPLADE_BACKEND", "seismic").lower()
        self._splade_qdrant_url = os.environ.get(
            "SFU_SPLADE_QDRANT_URL", "http://localhost:6333")
        self._splade_collection = os.environ.get(
            "SFU_SPLADE_QDRANT_COLLECTION", "splade_150m")
        self._qdrant_client = None   # lazy, only when backend=qdrant
        self._bert_vocab = None      # token->id map shared with the ingest
        self._seismic = None         # lazy, only when backend=seismic (testbed/served-federated)
        self._ordinals = None        # ordinal space, only when SFU_THINCLIENT_ORDINALS is set

    # ── lazy loading ────────────────────────────────────────────────────────

    def _manifest(self) -> dict:
        p = self.root / "manifest.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def _load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            import os

            import tantivy

            from lib.thinclient.abstracts import AbstractStore

            load_floor = float(os.environ.get("SFU_LOAD_MEM_FLOOR_GB",
                                              LOAD_MEM_FLOOR_GB))
            # SFU_SKIP_BMP: load tantivy/meta/dense only, skip the resident BMP
            # shards. The BM25F leg (tantivy, mmap) then runs on hosts too small
            # to hold the ~211 GB SPLADE set — used by the section-wave parity
            # eval, which records the SPLADE leg shard-by-shard in separate
            # processes. See scripts/eval_parity_section_waves.py.
            # backend=qdrant serves SPLADE from Qdrant, so the resident BMP set
            # is never queried — skip it (this is what reclaims the ~211 GB).
            # `import bmp` is deferred to the BMP branch below so the qdrant
            # serving path has NO dependency on the pisa engine being installed
            # (2026-06-25, Workstream D: BMP artifacts decommissioned; the BMP
            # package need not be present on a qdrant-only deploy).
            skip_bmp = (os.environ.get("SFU_SKIP_BMP") == "1"
                        or self._splade_backend in ("qdrant", "seismic"))
            sections_dir = self.root / "sections"
            if sections_dir.is_dir():
                for sdir in sorted(sections_dir.iterdir()):
                    if not (sdir / "tantivy" / "meta.json").exists():
                        continue
                    idx = tantivy.Index.open(str(sdir / "tantivy"))
                    idx.reload()
                    shards = []
                    bmp_paths = [] if skip_bmp else sorted(sdir.glob("splade_*.bmp"))
                    if bmp_paths:
                        import bmp  # deferred: only the BMP branch needs pisa
                    for p in bmp_paths:
                        _guard_load_mem(p.stat().st_size, load_floor,
                                        f"{sdir.name}/{p.name}")
                        vocab_path = p.with_suffix(".vocab.zst")
                        vocab = None
                        if vocab_path.exists():
                            import zstandard
                            try:
                                vocab = set(zstandard.ZstdDecompressor().decompress(
                                    vocab_path.read_bytes()).decode().split("\n"))
                            except Exception as e:
                                # A corrupt sidecar must not take down the whole
                                # index; vocab=None falls back to querying the
                                # shard without the zero-overlap guard.
                                logger.warning("thinclient: bad vocab sidecar %s "
                                               "(%s) — loading shard without it",
                                               vocab_path, e)
                                vocab = None
                        shards.append({"searcher": bmp.Searcher(str(p)),
                                       "vocab": vocab})
                    self._sections[sdir.name] = {
                        "index": idx, "searcher": idx.searcher(),
                        "schema": idx.schema, "bmp": shards,
                    }
                    abs_path = sdir / "abstracts.sqlite"
                    # A consolidated section may have abstracts.sqlite deleted,
                    # served entirely from the flat sidecar (doc 18 §18); open
                    # on the sidecar's presence, not just the SQLite file's.
                    if abs_path.exists() or (sdir / "abstracts.sqlite.flat").is_dir():
                        self._abstract_stores[sdir.name] = AbstractStore(abs_path)
            meta_path = self.root / "meta.sqlite"
            if meta_path.exists():
                self._meta = sqlite3.connect(str(meta_path), check_same_thread=False)
                # v2 schema stores W-ids as INTEGER PRIMARY KEY (+ docs_other
                # TEXT overflow); v1 indexes (e.g. thinclient_1m) are TEXT.
                cols = {r[1]: (r[2] or "").upper() for r in
                        self._meta.execute("PRAGMA table_info(docs)")}
                self._meta_numeric = cols.get("id", "").startswith("INT")
            dense_dir = self.root / "dense"
            if (dense_dir / "b1.usearch").exists():
                import numpy as np
                from usearch.index import Index
                view = Index.restore(str(dense_dir / "b1.usearch"), view=True)
                self._dense = {
                    "index": view,
                    "rescore": np.load(dense_dir / "rescore_int8.npy", mmap_mode="r"),
                    "ids": json.loads((dense_dir / "ids.json").read_text()),
                }
            if os.environ.get("SFU_DENSE_WARMCACHE", "1") != "0":
                try:
                    from lib.thinclient.dense_cache import DenseWarmCache
                    self._dense_cache = DenseWarmCache(
                        dense_dir, seed_ids=(self._dense or {}).get("ids", []),
                        model_path=self.dense_model_path)
                except Exception as exc:
                    logger.warning("dense warm cache unavailable: %s", exc)
                    self._dense_cache = None
            # Ordinal addressing (SFU_THINCLIENT_ORDINALS, default OFF). Raises
            # rather than falling back if it is configured and unusable: the
            # arrays only address the index they were built from, and quietly
            # serving SQLite after being told to serve ordinals would make a
            # misconfiguration look like a performance regression. See
            # lib/thinclient/ordinals.py and doc 18 §6 risk 1.
            from lib.thinclient.ordinals import load_if_enabled
            self._ordinals = load_if_enabled(self.root, self._manifest())

            self._loaded = True
            logger.info("thinclient: loaded %d live sections %s, dense=%s, "
                        "ordinals=%s", len(self._sections),
                        sorted(self._sections), bool(self._dense),
                        self._ordinals.space_id if self._ordinals else False)

    # ── public surface (OpenSearchRetriever-compatible) ─────────────────────

    def is_available(self) -> bool:
        try:
            self._load()
        except Exception as exc:
            logger.warning("thinclient index unavailable: %s", exc)
            return False
        return bool(self._sections)

    def live_sections(self) -> list[str]:
        self._load()
        return sorted(self._sections)

    # ── serve query-log surface (lib.serve_query_log) ──────────────────────────
    # Thin accessors the tools-layer search handler calls to attribute a served
    # query's latency to its legs + record the federation mode. The leg metrics
    # are otherwise in-memory only (reset on restart); these expose a diff window
    # so the serve log gets per-leg ms WITHOUT a callback plumbed through every
    # leg's call path (the least-invasive hook). All three are O(1) + thread-safe.

    def _leg_snapshot_for_log(self) -> dict:
        from lib.thinclient.retriever import snapshot_leg_metrics
        return snapshot_leg_metrics()

    def _leg_delta_for_log(self, before: dict) -> dict:
        from lib.thinclient.retriever import leg_metrics_delta
        return leg_metrics_delta(before)

    @staticmethod
    def _first_manifest_mmap_dir(manifest_path: str) -> str:
        """The first shard's `mmap_dir` (repo-relative) from a shard manifest —
        a representative path for FS-type detection. '' if unreadable."""
        try:
            with open(manifest_path) as fh:
                shards = json.load(fh).get("shards", [])
            return shards[0].get("mmap_dir", "") if shards else ""
        except (OSError, ValueError, KeyError, IndexError):
            return ""

    def _seismic_federation_mode(self) -> str:
        """The SFU_SEISMIC_FEDERATION in effect when the seismic backend served
        (parallel|sequential|hybrid), else '' when a non-seismic backend (qdrant)
        or the seismic leg isn't on the served path. Reflects the FS-aware
        auto-default (2026-07-18) when the env var is unset."""
        if self._splade_backend != "seismic":
            return ""
        env = os.environ.get("SFU_SEISMIC_FEDERATION")
        if env:
            return env.lower()
        # Report the mode the backend actually selected (constructed lazily).
        if self._seismic is not None:
            cls = type(self._seismic).__name__
            if "Sequential" in cls:
                return "sequential"
            if "Parallel" in cls:
                return "parallel"
        return "auto"

    def cold_section_hint(self, query: str,
                          filters: dict | None = None) -> str | None:
        """Sub-section this query classifies to when it is NOT live — i.e.
        results may be missing because the home (sub-)section is packed/absent.
        Era-aware: a year filter that excludes an era suppresses hints for it.
        Used for routing telemetry and client-visible unpack hints."""
        self._load()
        base = classify_query(query)
        if base in self._sections:          # legacy era-less layout
            return None
        f = _normalize_filters(filters)
        for era in ERAS:                    # recent first: the era axis leads
            sub = f"{base}__{era}"
            if sub in self._sections or _era_skip(sub, f):
                continue
            return sub
        return None

    def metrics(self) -> dict:
        """Per-leg latency/error counters + index coverage (for /health)."""
        try:
            self._load()
        except Exception:
            pass
        with _metrics_lock:
            legs = {k: dict(v) for k, v in _leg_metrics.items()}
        for m in legs.values():
            m["avg_ms"] = round(m["total_ms"] / max(m["count"], 1), 1)
            m["total_ms"] = round(m["total_ms"], 1)
        return {
            "legs": legs,
            "live_sections": sorted(self._sections),
            "bmp_shards": {n: len(s["bmp"]) for n, s in self._sections.items()},
            "dense_vectors": len(self._dense["ids"]) if self._dense else 0,
            "dense_warm_cache": (self._dense_cache.info()
                                 if self._dense_cache else None),
            "meta_schema": "v2-numeric" if self._meta_numeric else "v1-text",
            "manifest": self._manifest(),
        }

    def reload(self) -> dict:
        """Atomically re-load the index root (zero-downtime swap after a
        rebuild/unpack). In-flight queries finish on the old objects; the
        swap is a single attribute rebind under the load lock."""
        with self._lock:
            old = (self._sections, self._abstract_stores, self._meta,
                   self._dense, self._dense_cache)
            self._sections, self._abstract_stores = {}, {}
            self._meta, self._dense, self._dense_cache = None, None, None
            self._loaded = False
        try:
            self._load()
        except Exception:
            # Failed swap: restore the previous live objects.
            with self._lock:
                (self._sections, self._abstract_stores, self._meta,
                 self._dense, self._dense_cache) = old
                self._loaded = True
            raise
        if old[2] is not None:
            try:
                old[2].close()
            except sqlite3.Error:
                pass
        if old[4] is not None:
            old[4].close()
        return {"live_sections": sorted(self._sections),
                "dense_vectors": len(self._dense["ids"]) if self._dense else 0}

    def _log_query(self, leg: str, query: str, n: int, ms: float,
                   f: dict | None) -> None:
        if not self.query_log_path:
            return
        try:
            entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "leg": leg,
                     "query": query, "results": n, "latency_ms": round(ms, 1),
                     "filtered": bool(f), "cold_hint": self.cold_section_hint(query)}
            with self._qlog_lock, open(self.query_log_path, "a") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # a bad log path must never break a query

    def search(self, query: str, top_k: int = 50, mode: str | None = None,
               filters: dict | None = None) -> list[dict]:
        """mode: 'bm25f' (default) or 'splade' — same contract as the
        OpenSearch retriever so FederatedSearchRouter can RRF-fuse both."""
        self._load()
        if not self._sections:
            return []
        use_splade = mode == "splade"
        leg = "splade" if use_splade else "bm25f"
        f = _normalize_filters(filters)
        t0 = time.perf_counter()
        try:
            if use_splade:
                ranked = self._splade_leg(query, top_k, f)
            else:
                ranked = self._bm25f_leg(query, top_k, f)
        except Exception:
            _record_leg(leg, (time.perf_counter() - t0) * 1000, error=True)
            raise
        ms = (time.perf_counter() - t0) * 1000
        _record_leg(leg, ms)
        out = self._hydrate(ranked, source="thinclient" if not use_splade
                            else "thinclient_splade")
        self._log_query(leg, query, len(out), ms, f)
        return out

    def dense_search(self, query: str, top_k: int = 50,
                     dense_index: str = "", dense_model_path: str = "",
                     filters: dict | None = None) -> list[dict]:
        """usearch b1 + int8 rescore. Coverage = the dense POC subset until the
        full corpus is encoded (same partial-coverage caveat as the OpenSearch
        dense leg)."""
        self._load()
        cache = self._dense_cache
        if not self._dense and not (cache and cache.info()["docs"]):
            return []
        import numpy as np

        from lib.opensearch_retriever import encode_dense
        t0 = time.perf_counter()
        q = np.asarray(encode_dense(query, dense_model_path or self.dense_model_path),
                       dtype=np.float32)
        f = _normalize_filters(filters)
        fetch = top_k * (OVERFETCH_FILTERED if f else OVERFETCH)
        qbits = np.packbits((q > 0).astype(np.uint8))
        merged: dict[str, float] = {}
        if self._dense:
            hits = self._dense["index"].search(qbits, fetch)
            keys = np.asarray(hits.keys, dtype=np.int64).ravel()
            if keys.size:
                rescore = self._dense["rescore"]
                scores = (rescore[keys].astype(np.float32) / 127.0) @ q
                ids_all = self._dense["ids"]
                for i in range(keys.size):
                    merged[ids_all[int(keys[i])]] = float(scores[i])
        if cache:
            # Warm-cache delta: exact same int8·fp32 scoring — merges by score.
            for did, score in cache.search(qbits, q, fetch):
                if score > merged.get(did, float("-inf")):
                    merged[did] = score
        if not merged:
            return []
        ranked = sorted(merged.items(), key=lambda t: -t[1])
        if f:
            ranked = self._post_filter(ranked, f)
        ms = (time.perf_counter() - t0) * 1000
        _record_leg("dense", ms)
        out = self._hydrate(ranked[:top_k], source="thinclient_dense")
        self._log_query("dense", query, len(out), ms, f)
        return out

    def search_rrf(self, query: str, top_k: int = 50,
                   filters: dict | None = None, include_dense: bool = False) -> list[dict]:
        """Convenience 2/3-leg RRF (k=60) — same fusion the router applies."""
        legs = [self.search(query, top_k, mode="bm25f", filters=filters),
                self.search(query, top_k, mode="splade", filters=filters)]
        if include_dense and self._dense:
            legs.append(self.dense_search(query, top_k, filters=filters))
        scores: dict[str, float] = {}
        by_id: dict[str, dict] = {}
        for leg in legs:
            for rank, doc in enumerate(leg, start=1):
                did = doc["openalex_id"]
                scores[did] = scores.get(did, 0.0) + 1.0 / (RRF_K + rank)
                by_id.setdefault(did, doc)
        out = []
        for did in sorted(scores, key=lambda d: scores[d], reverse=True)[:top_k]:
            doc = dict(by_id[did])
            doc["score"] = scores[did]
            doc["source"] = "thinclient_rrf"
            out.append(doc)
        return out

    # ── legs ─────────────────────────────────────────────────────────────────

    def _bm25f_leg(self, query: str, top_k: int,
                   f: dict | None) -> list[tuple[str, float]]:
        import tantivy
        text = "".join(c if c.isalnum() or c.isspace() else " " for c in query)
        if not text.strip():
            return []
        merged: list[tuple[str, float]] = []
        for name, sec in self._sections.items():
            if _era_skip(name, f):
                continue
            idx, searcher = sec["index"], sec["searcher"]
            qt = idx.parse_query(text, ["title"])
            qa = idx.parse_query(text, ["abstract"])
            clauses = [
                (tantivy.Occur.Should, tantivy.Query.boost_query(qt, 3.0)),
                (tantivy.Occur.Should, qa),
            ]
            q = tantivy.Query.boolean_query(clauses)
            must = [(tantivy.Occur.Must, q)]
            if f and f.get("year_range"):
                lo, hi = f["year_range"]
                must.append((tantivy.Occur.Must, tantivy.Query.range_query(
                    sec["schema"], "year", tantivy.FieldType.Integer, lo, hi)))
            if f and f.get("type"):
                must.append((tantivy.Occur.Must, tantivy.Query.term_query(
                    sec["schema"], "doctype", f["type"])))
            if f and f.get("is_oa"):
                must.append((tantivy.Occur.Must, tantivy.Query.term_query(
                    sec["schema"], "is_oa", True)))
            final = tantivy.Query.boolean_query(must) if len(must) > 1 else q
            for score, addr in searcher.search(final, top_k).hits:
                merged.append((searcher.doc(addr)["id"][0], float(score)))
        merged.sort(key=lambda t: -t[1])
        return merged[:top_k]

    # ── SPLADE query-vector helpers (shared by both backends) ─────────────────

    def _encode_splade_top(self, query: str):
        """Encode the query and return its top-SPLADE_QUERY_TERMS terms, or None
        if the encoder is unavailable/empty (caller degrades to the BM25F leg)."""
        from lib.opensearch_retriever import encode_splade
        try:
            sparse = encode_splade(query, self.splade_model_path)
        except Exception as exc:
            # Missing/corrupt ONNX model must degrade the leg, not the query:
            # RRF still fuses BM25F (+dense) while this leg mirrors BM25F.
            logger.warning("SPLADE encoder failed (%s); falling back to BM25F leg", exc)
            return None
        if not sparse:
            logger.warning("SPLADE encoding empty; falling back to BM25F leg")
            return None
        return dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])

    def _bert_vocab_map(self) -> dict:
        """bert-base-uncased token->id map — the SAME bijection the Qdrant ingest
        used to place doc sparse vectors (scripts/archive/spike_qdrant_sparse._vocab)."""
        if self._bert_vocab is None:
            from transformers import AutoTokenizer
            self._bert_vocab = AutoTokenizer.from_pretrained("bert-base-uncased").get_vocab()
        return self._bert_vocab

    def _qdrant(self):
        if self._qdrant_client is None:
            from qdrant_client import QdrantClient
            self._qdrant_client = QdrantClient(url=self._splade_qdrant_url, timeout=30)
        return self._qdrant_client

    def _splade_leg_qdrant(self, query: str, top_k: int,
                           f: dict | None) -> list[tuple[str, float]]:
        """SPLADE leg served from the Qdrant on_disk sparse collection. Uses the
        raw f32 query (top-64 terms) measured at parity with BMP's 8-bit path
        (eval_quant_fidelity 2026-06-19). Any failure degrades to the BM25F leg,
        matching the encoder-failure contract — RRF still fuses the other legs."""
        from qdrant_client import models
        top_terms = self._encode_splade_top(query)
        if not top_terms:
            return self._bm25f_leg(query, top_k, f)
        vocab = self._bert_vocab_map()
        idx, val = [], []
        for tok, w in top_terms.items():
            i = vocab.get(tok)
            if i is not None:
                idx.append(int(i)); val.append(float(w))
        if not idx:
            return self._bm25f_leg(query, top_k, f)
        fetch = top_k * (OVERFETCH_FILTERED if f else OVERFETCH)
        try:
            res = self._qdrant().query_points(
                collection_name=self._splade_collection,
                query=models.SparseVector(indices=idx, values=val),
                using="splade", limit=fetch, with_payload=True)
        except Exception as exc:
            logger.warning("Qdrant SPLADE leg failed (%s); falling back to BM25F leg", exc)
            return self._bm25f_leg(query, top_k, f)
        merged = [(p.payload.get("oaid"), float(p.score))
                  for p in res.points if p.payload and p.payload.get("oaid")]
        if f:
            merged = self._post_filter(merged, f)
        return merged[:top_k]

    def _seismic_backend(self):
        """Lazy-load the SEISMIC backend ONCE per process.

        Two forms, selected by env:

        - **Federated (served 150M path):** `SFU_SEISMIC_SHARD_MANIFEST` set →
          `ParallelSeismicBackend.from_manifest(...)` or
          `SequentialSeismicBackend.from_manifest(...)` (two distinct serving
          classes, picked by `SFU_SEISMIC_FEDERATION`) with
          `load_mode=SFU_SEISMIC_LOAD_MODE` (default **`mmap`** — Path C). This is
          what makes `SFU_SPLADE_BACKEND=seismic` work against the real 150M
          corpus: 8 mmap'd shards served federated, anon floor ~0 (page-cache
          resident). `mmap` raises a clean RuntimeError if a shard's converted
          `.mmap/` dir is absent — NEVER a silent fallback to stock Path-A (which
          would re-introduce the ~137 GB anon floor G3 killed). Serving method is
          `SFU_SEISMIC_FEDERATION` (default **`parallel`** — the server-side
          `ThreadPoolExecutor` fan-out; `sequential` is the localized, RAM-efficient
          method that searches shards one at a time for a bounded resident working
          set on a RAM-constrained host — `docs/seismic_sequential_serving/`,
          bit-identical results).
        - **Single (testbed/persona):** else `SFU_SEISMIC_INDEX` set → the
          single `SeismicBackend` (Path-A owned anon, RAM-resident — fine at
          persona scale, NOT servable at 150M). Kept for bit-for-bit
          reproducibility of the G2/G6 persona results.

        Since the 2026-07-06 promotion, an UNSET manifest env defaults to the
        E7c dotvbyte manifest (`data/eval_results/
        seismic_c25_shards_150m_mmap_dotvbyte.json`) when that file exists
        AND this retriever serves the real index root (`data/
        thinclient_index`) — so the promoted dev container serves SEISMIC
        with zero env config, while synthetic/test index_roots never silently
        load the 150M corpus.

        Clean error (mirrors the SFU_LOAD_MEM_FLOOR_GB gate) if nothing is
        set and the default manifest is absent, never a silent fallback to
        another leg."""
        if self._seismic is None:
            manifest = os.environ.get("SFU_SEISMIC_SHARD_MANIFEST")
            repo_root = Path(__file__).resolve().parents[3]
            if (not manifest
                    and self.root == repo_root / "data" / "thinclient_index"):
                # Promotion default (2026-07-14 flip, E8 Stage-2 lands): the E8
                # dv-v2 (per-doc value scale) 8-shard manifest over the E5
                # block_walk_canonical layout — quality-IMPROVED vs the E5 dv-v1
                # promotion (per-shard overlap@10 vs f16 0.993–0.997; corpus mean
                # ~0.9955 vs e5/dv1 ~0.9906; +0.67% size, warm p50 ≤1.05×, T1 0/0
                # all 8 shards; Q7 federated 2-rep PASS 2026-07-13, manifest
                # `seismic_c25_shards_150m_mmap_e5_v2.json`; forward_format_version
                # = 2 (dotvbyte_fixedu8_v2)). The E8 flip was operator-signed-off
                # (2026-07-14). Falls back down the ladder: E5 dv-v1
                # (2026-07-09 promotion, block_walk_canonical
                # locality, quality-identical to dv1) → plain dv (2026-07-06
                # promotion) — each only when the newer manifest is absent, so a
                # one-env rollback (`SFU_SEISMIC_SHARD_MANIFEST=<older>`) still
                # reaches every prior served shard set.
                # Gated on the REAL serving root so synthetic/test index_roots
                # never silently pick up the 150M corpus; only used when the
                # file exists so single-index testbeds (SFU_SEISMIC_INDEX) keep
                # working without it. A *set* env var always wins (one-env
                # rollback to any prior manifest) and a missing set path fails
                # loudly downstream.
                eval_dir = repo_root / "data" / "eval_results"
                e5_v2_manifest = eval_dir / "seismic_c25_shards_150m_mmap_e5_v2.json"
                e5_manifest = eval_dir / "seismic_c25_shards_150m_mmap_e5.json"
                dv_manifest = eval_dir / "seismic_c25_shards_150m_mmap_dotvbyte.json"
                if e5_v2_manifest.exists():
                    default_manifest = e5_v2_manifest
                elif e5_manifest.exists():
                    default_manifest = e5_manifest
                else:
                    default_manifest = dv_manifest
                if default_manifest.exists():
                    manifest = str(default_manifest)
            if manifest:
                # Portability/perf: stage shards onto a fast local FS when
                # SFU_SEISMIC_STAGE_DIR is set (serving off a 9p/NFS mount is
                # ~160–240× slower per mmap fault and page cache doesn't hold —
                # measured 2026-07-18). No-op on a droplet whose index is already
                # on local disk. Best-effort: a staging failure logs and serves
                # from the original manifest rather than taking the serve down.
                stage_dir = os.environ.get("SFU_SEISMIC_STAGE_DIR")
                if stage_dir:
                    try:
                        manifest = _stage_shards_local(manifest, stage_dir)
                    except Exception:
                        logger.exception(
                            "SEISMIC stage to %s failed; serving from original "
                            "manifest (slow if on 9p/NFS)", stage_dir)
                load_mode = os.environ.get("SFU_SEISMIC_LOAD_MODE", "mmap")
                # Pick the concrete serving class directly (two distinct methods,
                # no shared mutable instance state — see sharded_seismic_backend.py).
                # Default 'parallel' = the historical server-side fan-out; the env
                # name/default are unchanged so served-path callers don't cascade.
                # Default is FS-aware (portability guard, 2026-07-18): sequential
                # on a slow passthrough FS (9p/virtiofs/nfs — parallel faults
                # contend on one host channel there, ~13× slower cold), parallel
                # on native local disk (droplet ext4). Env always overrides.
                federation = os.environ.get("SFU_SEISMIC_FEDERATION")
                if not federation:
                    sample = repo_root / self._first_manifest_mmap_dir(manifest)
                    federation = _auto_federation_mode(str(sample))
                    logger.info("SEISMIC federation auto-selected '%s' (%s on %s)",
                                federation, _fstype_for_path(str(sample)) or "unknown-fs",
                                sample)
                federation = federation.lower()
                if federation == "sequential":
                    from lib.thinclient.sharded_seismic_backend import SequentialSeismicBackend
                    self._seismic = SequentialSeismicBackend.from_manifest(
                        manifest, splade_model_path=self.splade_model_path,
                        load_mode=load_mode)
                else:
                    from lib.thinclient.sharded_seismic_backend import ParallelSeismicBackend
                    self._seismic = ParallelSeismicBackend.from_manifest(
                        manifest, splade_model_path=self.splade_model_path,
                        load_mode=load_mode)
            else:
                idx = os.environ.get("SFU_SEISMIC_INDEX")
                if not idx:
                    raise RuntimeError(
                        "SFU_SPLADE_BACKEND=seismic requires SFU_SEISMIC_SHARD_MANIFEST "
                        "(federated 150M serve, mmap) or SFU_SEISMIC_INDEX "
                        "(single persona-scale index, path stem or full *.index.seismic)")
                from lib.thinclient.seismic_backend import SeismicBackend
                self._seismic = SeismicBackend(idx, self.splade_model_path)
        return self._seismic

    def _splade_leg_seismic(self, query: str, top_k: int,
                            f: dict | None) -> list[tuple[str, float]]:
        """SPLADE leg served from SEISMIC (testbed single-index, or served
        federated 150M mmap via SFU_SEISMIC_SHARD_MANIFEST — G6/G5/G8). Same
        return shape as the Qdrant leg: [(oaid, score)]. Any failure degrades
        to the BM25F leg, matching the encoder-failure contract so RRF still
        fuses the other legs. SEISMIC is block-summary approximate (overlap@10
        0.479 vs Qdrant at default params), so its recall ≤ Qdrant's by
        construction — this is the G2/G6 quality delta under measurement.

        Federated over-fetch knobs (env, default → max(2×top_k, 100) per-shard,
        G8f 2026-07-08; no-ops for
        the single-index backend, whose `.search` ignores k_prime):
        SFU_SEISMIC_K_PRIME, SFU_SEISMIC_QUERY_CUT, SFU_SEISMIC_HEAP_FACTOR."""
        try:
            k_prime = os.environ.get("SFU_SEISMIC_K_PRIME")
            k_prime = int(k_prime) if k_prime else None
            qc_env = os.environ.get("SFU_SEISMIC_QUERY_CUT")
            query_cut = int(qc_env) if qc_env else None
            heap_factor = float(os.environ.get("SFU_SEISMIC_HEAP_FACTOR", "0.8"))
            # Over-fetch before post-filtering, matching the Qdrant/BMP legs
            # (fixed 2026-07-06: this leg previously fetched exactly top_k and
            # then filtered, thinning filtered results below top_k). The default
            # k' = max(2×fetch, 100) scales with it inside the backend (G8f).
            fetch = top_k * (OVERFETCH_FILTERED if f else 1)
            res = self._seismic_backend().search(
                query, fetch, query_cut=query_cut,
                heap_factor=heap_factor, k_prime=k_prime)
        except Exception as exc:
            logger.warning("SEISMIC SPLADE leg failed (%s); falling back to BM25F leg", exc)
            return self._bm25f_leg(query, top_k, f)
        if f:
            res = self._post_filter(res, f)
        return res[:top_k]

    def _splade_leg(self, query: str, top_k: int,
                    f: dict | None) -> list[tuple[str, float]]:
        if self._splade_backend == "qdrant":
            return self._splade_leg_qdrant(query, top_k, f)
        if self._splade_backend == "seismic":
            return self._splade_leg_seismic(query, top_k, f)
        from lib.opensearch_retriever import encode_splade
        try:
            sparse = encode_splade(query, self.splade_model_path)
        except Exception as exc:
            # Missing/corrupt ONNX model must degrade the leg, not the query:
            # RRF still fuses BM25F (+dense) while this leg mirrors BM25F.
            logger.warning("SPLADE encoder failed (%s); falling back to BM25F leg", exc)
            sparse = None
        if not sparse:
            logger.warning("SPLADE encoding empty; falling back to BM25F leg")
            return self._bm25f_leg(query, top_k, f)
        top_terms = dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])
        qvec = {t: max(1, int(round(w * QUANT_SCALE))) for t, w in top_terms.items()}
        fetch = top_k * (OVERFETCH_FILTERED if f else 1)
        merged: list[tuple[str, float]] = []
        for name, sec in self._sections.items():
            if _era_skip(name, f):
                continue
            for shard in sec["bmp"]:
                # BMP panics (Rust unwrap) when NO query term exists in the
                # shard — skip via the vocab sidecar; guard for old builds.
                q_here = qvec
                if shard["vocab"] is not None:
                    q_here = {t: w for t, w in qvec.items() if t in shard["vocab"]}
                    if not q_here:
                        continue
                try:
                    ids, scores = shard["searcher"].search(
                        q_here, k=fetch, alpha=BMP_ALPHA, beta=BMP_BETA)
                except BaseException as exc:  # pyo3 PanicException subclasses BaseException
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        raise
                    logger.warning("BMP shard search failed in %s: %s", name, exc)
                    continue
                merged.extend(zip(ids, map(float, scores)))
        merged.sort(key=lambda t: -t[1])
        if f:
            merged = self._post_filter(merged, f)
        return merged[:top_k]

    # ── helpers ───────────────────────────────────────────────────────────────

    def _meta_rows(self, ids: list[str]) -> dict[str, tuple]:
        if not ids:
            return {}
        out: dict[str, tuple] = {}
        if self._meta is None:
            if self._dense_cache is not None:
                out.update(self._dense_cache.metadata_rows(ids))
            return out
        # (warm-cache rows for ids missing from meta are filled in below)

        def _query(table: str, keys: list, back: dict | None) -> None:
            for start in range(0, len(keys), 500):
                chunk = keys[start:start + 500]
                marks = ",".join("?" * len(chunk))
                for row in self._meta.execute(
                        f"SELECT id, title, doi, year, type, is_oa, section "
                        f"FROM {table} WHERE id IN ({marks})", chunk):
                    did = back[row[0]] if back is not None else row[0]
                    out[did] = (did,) + tuple(row[1:])

        with self._meta_lock:
            if not self._meta_numeric:
                _query("docs", ids, None)
            else:
                from lib.thinclient.builder import encode_meta_id
                enc: dict[int, str] = {}
                other: list[str] = []
                for s in ids:
                    n = encode_meta_id(s)
                    (other.append(s) if n is None else enc.__setitem__(n, s))
                if enc:
                    _query("docs", list(enc), enc)
                if other:
                    _query("docs_other", other, None)
        if self._dense_cache is not None:
            missing = [i for i in ids if i not in out]
            if missing:
                out.update(self._dense_cache.metadata_rows(missing))
        return out

    def _post_filter(self, ranked: list[tuple[str, float]],
                     f: dict) -> list[tuple[str, float]]:
        """Drop candidates failing the filter, preserving the legs' rank order.

        **What actually costs time here is the filesystem under `meta.sqlite`,
        not the addressing scheme** (doc 18 §14, measured 2026-08-03). At 500
        candidates this stage costs 222.2 ms with `meta.sqlite` on 9p and
        **4.0 ms with the same file on local disk** — 55x for a file copy, no
        code change. The ordinal path reaches 1.5 ms, a further 2.7x on the
        stage but only 2.5 ms (2.0%) of the whole query, which is inside that
        run's +/-4% noise floor and is NOT a claimable win.

        So ordinals are a SPACE lever, not a latency one: they buy the staged
        baseline's latency for 1.96 GB of local disk instead of 24.9 GB. Doc 18
        §11's "120-211x" and §13's "whole-query 3.20x" both measured ordinals
        against SQLite-on-9p and misattributed that filesystem win to the
        addressing change; both sections now carry dated correction banners.

        Note only the SPLADE and dense legs reach here: `_bm25f_leg` pushes
        filters into tantivy as boolean clauses instead.
        """
        if self._ordinals is not None:
            kept, unresolved = self._ordinals.post_filter(ranked, f)
            if not unresolved:
                return kept
            # Docs with no build-time ordinal — warm-cache growth (doc 18 §6
            # risk 3) and anything else outside the build. They MUST go through
            # the SQLite path: dropping them here would silently lose exactly
            # the documents the warm cache exists to surface. Re-walking
            # `ranked` keeps the merged result in the legs' rank order.
            survivors = {d for d, _ in kept}
            survivors |= {d for d, _ in self._post_filter_sqlite(unresolved, f)}
            return [r for r in ranked if r[0] in survivors]
        return self._post_filter_sqlite(ranked, f)

    def _post_filter_sqlite(self, ranked: list[tuple[str, float]],
                            f: dict) -> list[tuple[str, float]]:
        rows = self._meta_rows([d for d, _ in ranked])
        keep = []
        for did, score in ranked:
            row = rows.get(did)
            if row is None:
                continue
            _, _, _, year, dtype, is_oa, _ = row
            if f.get("year_range"):
                lo, hi = f["year_range"]
                if not (year and lo <= year <= hi):
                    continue
            if f.get("type") and dtype != f["type"]:
                continue
            if f.get("is_oa") and not is_oa:
                continue
            keep.append((did, score))
        return keep

    def _hydrate(self, ranked: list[tuple[str, float]], source: str) -> list[dict]:
        ids = [d for d, _ in ranked]
        rows = self._meta_rows(ids)
        abstracts = self.fetch_abstracts(ids)
        results = []
        for did, score in ranked:
            row = rows.get(did)
            title, doi, year, dtype, is_oa = (
                (row[1], row[2], row[3], row[4], bool(row[5])) if row
                else ("", "", None, "", False))
            results.append({
                "doi": doi,
                "openalex_id": did,
                "title": title,
                "abstract": abstracts.get(did, ""),
                "publication_year": year,
                "date": str(year) if year is not None else "",
                "year": year,
                "score": score,
                "source": source,
                "type": dtype,
                "is_oa": is_oa,
            })
        if self._dense_cache is not None and results:
            # Query-driven dense growth: every surfaced doc is a candidate for
            # the warm-cache delta (fire-and-forget; dedup inside).
            self._dense_cache.enqueue(results)
        return results

    def fetch_abstracts(self, ids: list[str]) -> dict[str, str]:
        """Hot-section sidecars first; missing ids via OpenAlex API (cold-section
        policy: fetch BEFORE rerank, ~100 docs ≈ one mget)."""
        out: dict[str, str] = {}
        for store in self._abstract_stores.values():
            missing = [i for i in ids if i not in out]
            if not missing:
                break
            out.update(store.fetch(missing))
        missing = [i for i in ids if i not in out]
        if missing and self.remote_abstracts:
            out.update(self._fetch_remote_abstracts(missing))
        return out

    def _fetch_remote_abstracts(self, ids: list[str]) -> dict[str, str]:
        import requests
        out: dict[str, str] = {}
        try:
            for start in range(0, len(ids), 50):  # OpenAlex max 50 ids per filter
                chunk = ids[start:start + 50]
                params = {
                    "filter": "openalex_id:" + "|".join(chunk),
                    "per-page": str(len(chunk)),
                    "select": "id,abstract_inverted_index",
                }
                if self.openalex_mailto:
                    params["mailto"] = self.openalex_mailto
                r = requests.get("https://api.openalex.org/works", params=params,
                                 timeout=15)
                r.raise_for_status()
                for w in r.json().get("results", []):
                    wid = (w.get("id") or "").rsplit("/", 1)[-1]
                    inv = w.get("abstract_inverted_index")
                    if wid and inv:
                        out[wid] = _invert_abstract(inv)
        except requests.RequestException as exc:
            logger.warning("remote abstract fetch failed (%d ids): %s", len(ids), exc)
        return out


def _invert_abstract(inv: dict[str, list[int]]) -> str:
    """OpenAlex inverted-abstract-index -> plain text."""
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        positions.extend((i, word) for i in idxs)
    positions.sort()
    return " ".join(w for _, w in positions)


def _era_skip(section_name: str, f: dict | None) -> bool:
    """Era pruning — the fast axis: a year-bounded query never needs the other
    era's sub-sections, so they are skipped outright (cross-discipline pruning
    is impossible; cross-era pruning is free)."""
    if not f or not f.get("year_range"):
        return False
    lo, hi = f["year_range"]
    if section_name.endswith("__recent"):
        return hi < ERA_BOUNDARY_YEAR
    if section_name.endswith("__archive"):
        return lo >= ERA_BOUNDARY_YEAR
    return False


def _normalize_filters(filters: dict | None) -> dict | None:
    """OpenAlex-style filter dict -> {year_range, type, is_oa} (mirrors
    OpenSearchRetriever._build_filter_clauses semantics)."""
    if not filters:
        return None

    def _to_year(value) -> int | None:
        try:
            return int(str(value)[:4])
        except (ValueError, TypeError):
            return None

    out: dict = {}
    lo, hi = None, None
    py = filters.get("publication_year")
    if py:
        text = str(py)
        if "-" in text:
            a, _, b = text.partition("-")
            lo, hi = _to_year(a), _to_year(b)
        else:
            lo = hi = _to_year(text)
    fd = filters.get("from_publication_date")
    if fd and lo is None:
        lo = _to_year(fd)
    td = filters.get("to_publication_date")
    if td and hi is None:
        hi = _to_year(td)
    if lo is not None or hi is not None:
        out["year_range"] = (lo if lo is not None else 0,
                             hi if hi is not None else 3000)
    if filters.get("type"):
        out["type"] = filters["type"]
    oa = filters.get("open_access.is_oa", filters.get("is_oa"))
    if oa not in (None, "", False, "false"):
        out["is_oa"] = True
    return out or None
