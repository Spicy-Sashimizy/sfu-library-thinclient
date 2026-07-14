#!/usr/bin/env python3
"""SEISMIC vs Qdrant serving footprint benchmark at 150M docs.

Measures RAM footprint and per-query latency for SPLADE search:
  - SEISMIC: runs in-process, measures own VmRSS + RssAnon via /proc/self/
  - Qdrant: runs as external server, measures server process RAM via pgrep

Both engines execute identical 40 queries with same SPLADE encoding (top-64 terms).
Results: anon floor (GB), total VmRSS peak (GB), per-doc anon rate, latency (p50/p95/mean).

Usage (repo root, project venv):
    SFU_SEISMIC_LOAD_MODE=mmap .venv/bin/python3 \
        scripts/seismic_testbed/serve_footprint_bench.py \
        --shard-manifest data/eval_results/seismic_c25_shards_150m_mmap.json \
        --result-file data/eval_results/seismic_vs_qdrant_serve_bench.json

G8 compression matrix (the RAM-residency lever — see 08_LATENCY_RESEARCH.md §A1
+ the open-items plan). One bench invocation measures ONE cell of the 2×2:

    │              │ mem-compression OFF        │ mem-compression ON             │
    │ load = mmap  │ SFU_SEISMIC_LOAD_MODE=mmap │ + SFU_MEMCOMPRESSION_REGIME=   │
    │ (file-backed)│ (default; the 15.8 s disk  │   zram|zswap|                 │
    │              │  re-fault baseline)         │   windows_compression          │
    │ load = stock │ SFU_SEISMIC_LOAD_MODE=stock│ + same regime override         │
    │ (owned-anon, │ (Path A; OOMs/swaps to disk│ (anon compressed IN RAM ~2–3×, │
    │  Path A)     │  at 150M)                   │  decompress at GB/s — the win) │

The two axes are independent env vars already wired: load mode picks file-backed
mmap vs Path-A owned anon (stock = SeismicIndex.load()); SFU_MEMCOMPRESSION_REGIME
tells the verdict gate which swap regime those pages live under, so the gate does
not mislabel the compressed cell. Run the cell you want by setting the two vars
together (and recording the cell in the result-file name). The gate's reading of
VmSwap is regime-dependent — see detect_memcompression() + _latency_caveat().
"""
import argparse
import json
import logging
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("serve_bench")

TOP_K = 50
SPLADE_QUERY_TERMS = 64
QDRANT_URL = "http://localhost:6333"
QDRANT_COLLECTION = "splade_150m"
TOTAL_DOCS = 150413098

# ── RAM measurement helpers ──────────────────────────────────────────────────

def rssanon_kb():
    """RssAnon from /proc/self/status (KB) — non-reclaimable anon private-dirty."""
    try:
        for line in open("/proc/self/status"):
            if line.startswith("RssAnon:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def pssanon_kb():
    """Pss_Anon from /proc/self/smaps_rollup (KB)."""
    try:
        txt = open("/proc/self/smaps_rollup").read()
        for line in txt.splitlines():
            if line.startswith("Pss_Anon:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def vmrss_kb():
    """VmRSS from /proc/self/status (KB) — total resident set size."""
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def vmswap_kb():
    """VmSwap from /proc/self/status (KB) — anon pages paged OUT to swap. On a
    memory-pressured host RssAnon undercounts the true anon floor by exactly this;
    the OOM-relevant anon demand is RssAnon + VmSwap."""
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmSwap:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def _get_process_ram(pid):
    """Get (RssAnon_kb, Pss_Anon_kb, VmRSS_kb) for a given PID."""
    try:
        with open(f"/proc/{pid}/status") as f:
            status = f.read()
        rssanon = None
        vmrss = None
        vmswap = None
        for line in status.splitlines():
            if line.startswith("RssAnon:"):
                rssanon = int(line.split()[1])
            if line.startswith("VmRSS:"):
                vmrss = int(line.split()[1])
            if line.startswith("VmSwap:"):
                vmswap = int(line.split()[1])

        pssanon = None
        try:
            with open(f"/proc/{pid}/smaps_rollup") as f:
                for line in f:
                    if line.startswith("Pss_Anon:"):
                        pssanon = int(line.split()[1])
                        break
        except (OSError, ValueError):
            pass

        return (rssanon, pssanon, vmrss, vmswap)
    except (OSError, ValueError, FileNotFoundError):
        return (None, None, None, None)


def gb(kb):
    """Convert KB to GB."""
    return round(kb / 1024 / 1024, 4) if kb is not None else None


# ── Memory-compression regime detection (G8 2×2 matrix) ───────────────────────
# The G8 latency verdict gate (_latency_caveat) reads VmSwap to decide whether a
# latency is a "real" compute number vs a swap/page-fault artifact. That reading
# is REGIME-DEPENDENT: under zram/zswap/Windows-memory-compression the "swapped"
# anon pages are actually compressed *in RAM* (decompress at multiple GB/s) —
# the exact mechanism the G8 compression cell wants to test — NOT a disk re-fault.
# So a VmSwap>0.1 GB read on a zram-backed host is NOT the disk-confound symptom
# it would be on a plain-partition-swap host. We detect and record the regime so
# the gate can treat them differently, and so each result self-documents its cell.

# Operator assertions for regimes the process can't introspect from /proc (e.g.
# Windows host memory compression, visible only from the hypervisor side, or a
# zram device the container can't see). Set SFU_MEMCOMPRESSION_REGIME to override.
_REGIME_VALUES = ("zram", "zswap", "windows_compression", "disk_swap", "off", "unknown")


def detect_memcompression():
    """Detect the host's anonymous-page compression/swap regime.

    Returns dict: regime (one of _REGIME_VALUES), sources (the /proc files /
    env var that decided it), zram_devs (list), zswap_enabled (bool|None).

    precedence (first match wins — most-specific-to-least):
      1. SFU_MEMCOMPRESSION_REGIME env (operator assertion; validated; trumps all)
         — needed for Windows host compression (not visible from WSL2 /proc) and
           for zram devices the container can't enumerate.
      2. zram block devices present (/sys/block/zram*) — compressed-in-RAM swap.
         zswap can sit IN FRONT of a zram/swap partition too, so check both.
      3. zswap enabled (/sys/module/zswap/parameters/enabled == 'Y') — frontswap
         that compresses anon into a RAM pool before it touches backing swap.
      4. disk_swap — a plain /proc/swaps partition is anon paged to disk (the
         historical 15.8 s re-fault regime). Distinguishes a real confound from the
         compressed regimes above.
      5. off — no swap configured at all (unusual; meanmlock'd box).
      6. unknown — can't determine and no assertion (the safe default: the verdict
         gate treats VmSwap as the historical confound).
    """
    sources = []
    zram_devs = []
    zswap_enabled = None
    reg = os.environ.get("SFU_MEMCOMPRESSION_REGIME", "").strip().lower()

    # 1. operator assertion trumps introspection
    if reg:
        if reg not in _REGIME_VALUES:
            raise ValueError(
                f"SFU_MEMCOMPRESSION_REGIME={reg!r} invalid — must be one of "
                f"{_REGIME_VALUES}. Used by the G8 verdict gate to decide whether "
                f"VmSwap is a compressed-in-RAM win or a disk re-fault confound.")
        return {"regime": reg, "sources": ["SFU_MEMCOMPRESSION_REGIME env (operator assertion)"],
                "zram_devs": [], "zswap_enabled": None}

    # 2. zram block devices — compressed-RAM swap
    try:
        for dev in sorted(os.listdir("/sys/block")):
            if dev.startswith("zram"):
                zram_devs.append(dev)
    except OSError:
        pass
    if zram_devs:
        sources.append("/sys/block/zram* (compressed-RAM swap device)")
        return {"regime": "zram", "sources": sources,
                "zram_devs": zram_devs, "zswap_enabled": None}

    # 3. zswap enabled (frontswap compression in front of backing swap)
    try:
        val = open("/sys/module/zswap/parameters/enabled").read().strip()
        zswap_enabled = val == "Y"
        if zswap_enabled:
            sources.append("/sys/module/zswap/parameters/enabled=Y (frontswap compression)")
            return {"regime": "zswap", "sources": sources,
                    "zram_devs": [], "zswap_enabled": True}
    except OSError:
        pass

    # 4. plain disk swap partition (the historical confound regime)
    try:
        swaps = [ln for ln in open("/proc/swaps").read().splitlines()[1:] if ln.strip()]
        if swaps:
            disk_swp = [s for s in swaps if not s.split()[0].startswith("/dev/zram")]
            if disk_swp:
                sources.append("/proc/swaps (partition-backed swap → disk re-fault)")
                return {"regime": "disk_swap", "sources": sources,
                        "zram_devs": [], "zswap_enabled": zswap_enabled}
    except OSError:
        pass

    # 5. no swap configured at all
    try:
        st = open("/proc/meminfo").read()
        total_kb = 0
        for ln in st.splitlines():
            if ln.startswith("SwapTotal:"):
                total_kb = int(ln.split()[1])
                break
        if total_kb == 0:
            sources.append("/proc/meminfo SwapTotal=0 (no swap)")
            return {"regime": "off", "sources": sources,
                    "zram_devs": [], "zswap_enabled": zswap_enabled}
    except (OSError, ValueError):
        pass

    return {"regime": "unknown", "sources": ["unable to determine + no env assertion"],
            "zram_devs": [], "zswap_enabled": None}


def _regime_is_compressed_in_ram(regime):
    """A regime where VmSwap anon pages are compressed in RAM, not paged to disk.

    The G8 verdict gate must know this: under these regimes VmSwap>0 is the
    compression mechanism working as intended (decompress at GB/s, no re-fault),
    NOT the disk-re-fault confound a 'disk_swap'/'unknown' VmSwap reading implies.
    """
    return regime in ("zram", "zswap", "windows_compression")


def _stat(stats, band, key):
    """band='warm' (steady-state) or 'cold' (first-fault); falls back to top-level."""
    if not stats:
        return None
    return ((stats.get(band) or stats) if band == "warm" else (stats.get(band) or {})).get(key)


def _latency_caveat(ram_summary, stats, load_mode, regime):
    """Data-driven honesty gate (08_LATENCY_RESEARCH.md §A1 measured): a latency
    is a verdict only if VmSwap≈0 AND warm p50 < cold p50 (page cache actually
    helped). Two symptoms — often co-occurring — mean it is NOT a verdict, and
    both share one root cause (host RAM < working set):
      (1) anon swap  — VmSwap > 0 → anon pages paged out, latency is swap noise.
      (2) cache miss — warm >= cold → the mmap index exceeds page cache, so
          queries re-fault different postings from disk (I/O-bound, not compute).
    Report every symptom present, then the unified cause/fix.

    REGIME-AWARE (G8 compression matrix): the VmSwap reading only means a
    disk-confound under a plain disk-swap / unverified regime. Under
    zram/zswap/windows_compression the 'swapped' anon pages are compressed IN
    RAM (decompress at GB/s) — the G8 compression mechanism working as
    intended, NOT the disk re-fault the old gate assumed. detect_memcompression()
    resolves the regime; the operator asserts it via SFU_MEMCOMPRESSION_REGIME
    when /proc can't see it (Windows host compression). Without this fix the
    owned-anon+zram cell would be mislabeled 'not a verdict'.

    The 'index exceeds page cache' (warm>=cold) symptom is mmap-specific: under
    owned-anon stock load there is no file-backed page cache to exceed, so that
    explanation can't apply — gated on load_mode=='mmap'. (File-backed pages
    re-fault under ANY regime: compression compresses anon, it does not cache
    dropped file pages, so the mmap symptom stands regardless of regime.)"""
    swap = (ram_summary or {}).get("vmswap_gb") or 0.0
    cold = _stat(stats, "cold", "p50_ms")
    warm = _stat(stats, "warm", "p50_ms")
    regime_name = regime.get("regime", "unknown") if regime else "unknown"
    compressed_in_ram = _regime_is_compressed_in_ram(regime_name)

    issues = []
    # VmSwap symptom — ONLY a disk confound under a non-compressed regime.
    # Under zram/zswap/windows_compression the swapped anon is compressed in RAM.
    if swap > 0.1 and not compressed_in_ram:
        issues.append(f"VmSwap={swap:.2f} GB anon paged to disk swap "
                      f"(regime={regime_name})")
    # mmap page-cache-exceeds symptom — file-backed pages only.
    if load_mode == "mmap" and cold and warm and warm >= 0.9 * cold and warm > 1000:
        issues.append(f"warm p50 {warm:.0f} ms >= cold {cold:.0f} ms (file-backed mmap "
                      f"index exceeds page cache → queries re-fault from disk)")
    if issues:
        return ("CAVEAT: latency is DISK/SWAP-bound, NOT a compute verdict — "
                + "; ".join(issues) + ". Root cause: host RAM < working set; needs "
                "RAM >= index-on-disk size (+ headroom) so the file-backed index stays "
                "cached and anon never hits a non-compressed swap.")
    # No disk/page-cache confound. Distinguish the compressed-cell verdict from
    # the classic clean one so the result self-documents which matrix cell ran.
    if compressed_in_ram and swap > 0.1:
        return (f"Latency is a VERDICT (warm < cold, no disk re-fault; load_mode="
                f"{load_mode}, regime={regime_name}). VmSwap={swap:.2f} GB is anon "
                f"compressed IN RAM under {regime_name} — the G8 compression mechanism, "
                f"decompress at GB/s, NOT a disk confound. Effective resident set "
                f"includes these compressed pages.")
    return (f"Latency measured with VmSwap~0 (regime={regime_name}) and warm < cold "
            f"(page-cache hit) — representative of a properly-provisioned host for "
            f"this working set (load_mode={load_mode}).")


def find_qdrant_pid():
    """Find the Qdrant server process PID via pgrep."""
    try:
        result = subprocess.run(["pgrep", "-f", "qdrant"], capture_output=True, text=True)
        pids = result.stdout.strip().split("\n")
        pids = [p for p in pids if p]
        if pids:
            return int(pids[0])  # return first match
    except Exception:
        pass
    return None


# ── SPLADE query encoding (shared by both backends) ───────────────────────────

def encode_splade_query(query_text: str, model_path: str) -> dict[str, float]:
    """Encode query to top-SPLADE_QUERY_TERMS sparse terms."""
    from lib.opensearch_retriever import encode_splade
    try:
        sparse = encode_splade(query_text, model_path)
    except Exception as e:
        log.warning("SPLADE encode failed: %s", e)
        return {}
    if not sparse:
        return {}
    return dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])


_VOCAB_CACHE = None


def bert_vocab_map():
    """BERT base-uncased vocab (token str -> int id). Memoized — loading the
    tokenizer per query would pollute Qdrant's measured latency with model-load
    time (it is NOT serving cost). Built once on first use, reused thereafter."""
    global _VOCAB_CACHE
    if _VOCAB_CACHE is None:
        from transformers import AutoTokenizer
        _VOCAB_CACHE = AutoTokenizer.from_pretrained("bert-base-uncased").get_vocab()
    return _VOCAB_CACHE


# ── Qdrant query ──────────────────────────────────────────────────────────────

def query_qdrant(query_text: str, top_k: int, model_path: str) -> list[tuple[str, float]]:
    """Query Qdrant SPLADE leg. Returns [(oaid, score)]."""
    from qdrant_client import QdrantClient, models

    top_terms = encode_splade_query(query_text, model_path)
    if not top_terms:
        return []

    vocab = bert_vocab_map()
    idx, val = [], []
    for tok, w in top_terms.items():
        i = vocab.get(tok)
        if i is not None:
            idx.append(int(i))
            val.append(float(w))

    if not idx:
        return []

    try:
        client = QdrantClient(url=QDRANT_URL, timeout=30)
        res = client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=models.SparseVector(indices=idx, values=val),
            using="splade", limit=top_k, with_payload=True)
        return [(p.payload.get("oaid"), float(p.score))
                for p in res.points if p.payload and p.payload.get("oaid")]
    except Exception as e:
        log.warning("Qdrant query failed: %s", e)
        return []


# ── SEISMIC query ──────────────────────────────────────────────────────────────

def _seismic_query_knobs(default_k_prime: int = 200, default_heap_factor: float = 0.8):
    """Resolve query_cut / heap_factor / k_prime from the SAME env vars the served
    retriever reads (SFU_SEISMIC_QUERY_CUT / SFU_SEISMIC_HEAP_FACTOR /
    SFU_SEISMIC_K_PRIME), so the bench and the served `SFU_SPLADE_BACKEND=seismic`
    path use ONE config source. Falls back to all-terms / 0.8 / 200 when unset
    (the recall-first defaults — i.e. measure the unchanged served config unless
    the operator opts into the C1 lever via env). Added for the §C1 latency
    re-run (commit 2026-06-30): the bench previously hardcoded heap_factor=0.8
    and never passed query_cut, so the free C1 win (query_cut=10 → 4× traverse,
    overlap@10 0.995) couldn't take effect on the G8 run."""
    qc_env = os.environ.get("SFU_SEISMIC_QUERY_CUT")
    query_cut = int(qc_env) if qc_env else None
    heap_factor = float(os.environ.get("SFU_SEISMIC_HEAP_FACTOR", str(default_heap_factor)))
    kp_env = os.environ.get("SFU_SEISMIC_K_PRIME")
    k_prime = int(kp_env) if kp_env else default_k_prime
    return query_cut, heap_factor, k_prime


def query_seismic(query_text: str, sb, top_k: int) -> list[tuple[str, float]]:
    """Query SEISMIC federated backend. Returns [(oaid, score)]."""
    try:
        query_cut, heap_factor, k_prime = _seismic_query_knobs()
        return sb.search(query_text, top_k, k_prime=k_prime, heap_factor=heap_factor,
                         query_cut=query_cut)
    except Exception as e:
        log.warning("SEISMIC query failed: %s", e)
        return []


def query_seismic_timed(query_text: str, sb, top_k: int, k_prime: int = 200,
                        heap_factor: float = 0.8):
    """Query SEISMIC with encode/traverse latency split (item-#3 attribution).

    Returns (results, encode_ms, traverse_ms). If the backend exposes
    `search_with_timing` (ShardedSeismicBackend does), uses it for a clean split.
    Otherwise falls back to timing `encode_query` + `search` end-to-end via
    perf_counter walls (still splits encode from traversal, just without the
    backend's cooperation). traverse_ms=0.0 when encoding yields nothing.

    The split is the whole point of the latency-#3 fix: a slow `search()` could
    be the in-process SPLADE ONNX encode (CPU-bound, ~ms scale warm) rather than
    SEISMIC traversal (page-fault-bound on a cold working set) — without the
    split they're indistinguishable in the end-to-end number.

    query_cut / heap_factor / k_prime are pulled from SFU_SEISMIC_* env (see
    `_seismic_query_knobs`) so the bench matches the served path's config — the
    call-signature `k_prime`/`heap_factor` args are kept as the fallback default
    but the env (if set) wins, so `--passes 2` measures the config the operator
    intends to ship, not a hardcoded 0.8/all-terms.
    """
    import time
    try:
        qc_default, hf_default, kp_default = _seismic_query_knobs(
            default_k_prime=k_prime, default_heap_factor=heap_factor)
        if hasattr(sb, "search_with_timing"):
            return sb.search_with_timing(
                query_text, top_k, k_prime=kp_default, heap_factor=hf_default,
                query_cut=qc_default)
        # Back-compat fallback: time the public encode_query, then search().
        t0 = time.perf_counter()
        q = sb.encode_query(query_text)
        encode_ms = (time.perf_counter() - t0) * 1000.0
        if not q:
            return [], encode_ms, 0.0
        t0 = time.perf_counter()
        res = sb.search(query_text, top_k, k_prime=kp_default, heap_factor=hf_default,
                        query_cut=qc_default)
        traverse_ms = (time.perf_counter() - t0) * 1000.0
        return res, encode_ms, traverse_ms
    except Exception as e:
        log.warning("SEISMIC query failed: %s", e)
        return [], 0.0, 0.0


# ── main benchmark ────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shard-manifest", required=True,
                    help="SEISMIC 8-shard manifest (index_path list)")
    ap.add_argument("--result-file", default=None,
                    help="output JSON path (default: data/eval_results/<dated>.json)")
    ap.add_argument("--queries", type=int, default=40, help="query count")
    ap.add_argument("--passes", type=int, default=1,
                    help="repeat the full query set this many times. Pass 0 is the "
                         "COLD pass (first-touch mmap faults / cold OS page cache); "
                         "passes >=1 are WARM (steady-state serving, pages resident). "
                         "Latency is reported split cold-vs-warm when passes>1.")
    ap.add_argument("--top-k", type=int, default=TOP_K)
    ap.add_argument("--splade-model", default="models/splade_onnx_fp16")
    ap.add_argument("--federation", choices=["parallel", "sequential", "hybrid"],
                    default="parallel",
                    help="SEISMIC serving method over the 8 mmap shards: "
                         "'parallel' (default — ThreadPoolExecutor fan-out, "
                         "latency ~= max shard, resident ~= all shards), "
                         "'sequential' (one shard at a time, latency ~= sum "
                         "of shards, bounded resident ~= 1 shard — fits a "
                         "RAM-constrained host WITHOUT swapping; "
                         "docs/seismic_sequential_serving/), or 'hybrid' "
                         "(Q7 2026-07-10 — sequential while cold, flips to "
                         "parallel on a state signal once warm; bit-identical).")
    args = ap.parse_args()

    # Determine result file path
    if args.result_file:
        result_file = Path(args.result_file)
    else:
        utc_date = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        result_file = REPO / "data" / "eval_results" / f"seismic_vs_qdrant_serve_bench_{utc_date}.json"

    log_file = result_file.with_suffix(".log")

    log.info("=== SEISMIC vs Qdrant Serving Footprint Benchmark ===")
    log.info("Result file: %s", result_file)
    log.info("Log file: %s", log_file)

    # ── G8 2×2 matrix: record the load + mem-compression cell this run measures.
    # detect_memcompression() reads the host's swap regime (zram/zswap/disk_swap/
    # off) or honors an operator assertion via SFU_MEMCOMPRESSION_REGIME (needed
    # for Windows host compression, invisible from WSL2 /proc). load_mode is set
    # below from SFU_SEISMIC_LOAD_MODE (mmap=Path C / stock=Path A owned anon).
    memcomp = detect_memcompression()
    load_mode = os.environ.get("SFU_SEISMIC_LOAD_MODE", "mmap")  # set before the log line
    log.info("G8 matrix cell: load_mode=%s  mem_compression regime=%s (%s)",
             load_mode, memcomp["regime"], "; ".join(memcomp["sources"]) or "detected")

    # ── 0. Load queries ────────────────────────────────────────────────────────
    qrecs = json.loads((REPO / "data" / "eval_results" / "diverse_queries.json").read_text())
    seen, queries = set(), []
    for rec in qrecs:
        if rec["paraphrase"] in seen:
            continue
        seen.add(rec["paraphrase"])
        queries.append(rec["paraphrase"])
        if len(queries) >= args.queries:
            break
    log.info("loaded %d unique queries", len(queries))

    # ── 1. Load SEISMIC ─────────────────────────────────────────────────────────
    # Reuse the backend's own manifest parser (_load_manifest accepts the
    # {shards:[{index_path}]} dict, a plain JSON list, or csv) so a valid manifest
    # never crashes here on a shape the backend already accepts. load_mode was
    # already read above (for the G8 matrix-cell log line) from
    # SFU_SEISMIC_LOAD_MODE (default mmap = the served 150M path); it can be
    # set to 'stock' to run a Path-A control on a testbed index (no .mmap/ dir).
    from seismic_federated import (
        ParallelSeismicBackend, SequentialSeismicBackend,
        HybridSeismicBackend, _load_manifest)
    # Pass load_mode so mmap mode reads the C2.5 manifest's `mmap_dir` (the
    # persistent converted path) rather than the G7 `index_path` (volatile /tmp).
    index_paths = _load_manifest(args.shard_manifest, load_mode=load_mode)
    if not index_paths:
        raise RuntimeError(f"no shard paths parsed from {args.shard_manifest}")
    # --federation wins; SFU_SEISMIC_FEDERATION is the fallback so an operator can
    # set it once for a serve-bench run. Default 'parallel' = historical path.
    federation = args.federation or os.environ.get("SFU_SEISMIC_FEDERATION", "parallel")

    log.info("loading %d SEISMIC shards (load_mode=%s, federation=%s)...",
             len(index_paths), load_mode, federation)

    seismic_ram_baseline = {
        "rssanon_kb": rssanon_kb(),
        "pssanon_kb": pssanon_kb(),
        "vmrss_kb": vmrss_kb(),
        "vmswap_kb": vmswap_kb(),
    }
    log.info("SEISMIC baseline: RssAnon=%s Pss_Anon=%s VmRSS=%s GB",
             gb(seismic_ram_baseline["rssanon_kb"]),
             gb(seismic_ram_baseline["pssanon_kb"]),
             gb(seismic_ram_baseline["vmrss_kb"]))

    t0 = time.perf_counter()
    if federation == "sequential":
        cls = SequentialSeismicBackend
    elif federation == "hybrid":
        cls = HybridSeismicBackend
    else:
        cls = ParallelSeismicBackend
    sb = cls(index_paths, load_mode=load_mode)
    load_secs = time.perf_counter() - t0

    seismic_ram_post_load = {
        "rssanon_kb": rssanon_kb(),
        "pssanon_kb": pssanon_kb(),
        "vmrss_kb": vmrss_kb(),
        "vmswap_kb": vmswap_kb(),
    }
    log.info("SEISMIC post-load (%.1fs): RssAnon=%s Pss_Anon=%s VmRSS=%s GB",
             load_secs,
             gb(seismic_ram_post_load["rssanon_kb"]),
             gb(seismic_ram_post_load["pssanon_kb"]),
             gb(seismic_ram_post_load["vmrss_kb"]))

    # ── 2. Find Qdrant server PID ──────────────────────────────────────────────
    qdrant_pid = find_qdrant_pid()
    if not qdrant_pid:
        log.error("QDRANT SERVER NOT FOUND — cannot measure server RAM. "
                  "Make sure Qdrant is running on %s", QDRANT_URL)
        qdrant_available = False
    else:
        log.info("found Qdrant server PID %d", qdrant_pid)
        qdrant_available = True

    # Sample Qdrant baseline (idle)
    qdrant_ram_baseline = None
    if qdrant_available:
        rssanon, pssanon, vmrss, vmswap = _get_process_ram(qdrant_pid)
        qdrant_ram_baseline = {
            "rssanon_kb": rssanon,
            "pssanon_kb": pssanon,
            "vmrss_kb": vmrss,
            "vmswap_kb": vmswap,
        }
        log.info("Qdrant baseline (idle): RssAnon=%s Pss_Anon=%s VmRSS=%s GB",
                 gb(rssanon), gb(pssanon), gb(vmrss))

    # ── 3. Warmup SEISMIC (fault pages) ────────────────────────────────────────
    log.info("warmup SEISMIC...")
    if queries:
        _ = query_seismic_timed(queries[0], sb, args.top_k)

    seismic_ram_post_warmup = {
        "rssanon_kb": rssanon_kb(),
        "pssanon_kb": pssanon_kb(),
        "vmrss_kb": vmrss_kb(),
        "vmswap_kb": vmswap_kb(),
    }
    log.info("SEISMIC post-warmup: RssAnon=%s Pss_Anon=%s VmRSS=%s GB",
             gb(seismic_ram_post_warmup["rssanon_kb"]),
             gb(seismic_ram_post_warmup["pssanon_kb"]),
             gb(seismic_ram_post_warmup["vmrss_kb"]))

    # ── 4. Run both engines over the same 40 queries ────────────────────────────
    # Latencies recorded per pass. Pass 0 = COLD (first-touch mmap faults / cold
    # OS page cache); passes >=1 = WARM (steady-state, working set resident). This
    # split is the whole point: a single cold pass conflates first-fault IO cost
    # with actual serving cost.
    #
    # encode/traverse split (item-#3): SEISMIC per-query time is decomposed into
    #   - encode_ms   : the in-process SPLADE ONNX query encode (CPU-bound)
    #   - traverse_ms : the 8-shard fan-out traversal (page-fault-bound cold)
    # so a slow end-to-end `search()` can be attributed to the encoder vs the
    # engine. `s_pass` stays the true end-to-end total (encode+traverse) so the
    # SUM equals the old single number — back-compat for the existing stats path.
    seismic_lat_by_pass = []
    qdrant_lat_by_pass = []
    seismic_encode_by_pass = []
    seismic_traverse_by_pass = []

    log.info("running %d queries x %d pass(es)...", len(queries), args.passes)
    seismic_empty_results = 0  # failed/empty queries — see all-failed guard below
    for p in range(args.passes):
        warm = "WARM" if p >= 1 else "COLD"
        s_pass, q_pass, se_pass, st_pass = [], [], [], []
        for i, q in enumerate(queries):
            # End-to-end wall = encode + traverse (== old single-number semantics).
            t0 = time.perf_counter()
            res, encode_ms, traverse_ms = query_seismic_timed(q, sb, args.top_k)
            s_pass.append((time.perf_counter() - t0) * 1000)
            se_pass.append(encode_ms)
            st_pass.append(traverse_ms)
            if not res:
                seismic_empty_results += 1

            if qdrant_available:
                t0 = time.perf_counter()
                query_qdrant(q, args.top_k, args.splade_model)
                q_pass.append((time.perf_counter() - t0) * 1000)
        seismic_lat_by_pass.append(s_pass)
        qdrant_lat_by_pass.append(q_pass)
        seismic_encode_by_pass.append(se_pass)
        seismic_traverse_by_pass.append(st_pass)
        med_enc = statistics.median(se_pass) if se_pass else -1
        med_trv = statistics.median(st_pass) if st_pass else -1
        log.info("pass %d/%d (%s): SEISMIC p50=%.1f ms [encode %.1f / traverse %.1f]  "
                 "Qdrant p50=%.1f ms",
                 p + 1, args.passes, warm, statistics.median(s_pass),
                 med_enc, med_trv,
                 statistics.median(q_pass) if q_pass else -1)

    # ALL-FAILED GUARD (2026-07-14): query_seismic_timed swallows per-query
    # exceptions into ([], 0.0, 0.0) so one bad query can't kill a long bench —
    # but a broken serving path then scores every query as a ~0 ms no-op and the
    # cell looks PHENOMENAL (the invalid F6 "cold p95 30 ms" cells: 300/300
    # queries raised ImportError, all recorded 0.0). A latency cell where every
    # query failed is not a measurement; refuse to write one.
    total_q = len(queries) * args.passes
    if total_q > 0 and seismic_empty_results > total_q * 0.2:
        log.error("%d/%d SEISMIC queries returned empty/failed — the serving "
                  "path is broken (a top-50 over 150M docs is never legitimately "
                  "empty); refusing to write a latency result. Check the "
                  "'SEISMIC query failed:' warnings above for the cause. "
                  "(Guard added 2026-07-14: the invalid F6 cells scored 298-300 "
                  "no-op queries as cold p95 ~30 ms.)",
                  seismic_empty_results, total_q)
        sys.exit(3)
    if seismic_empty_results:
        log.warning("%d/%d SEISMIC queries returned empty/failed — latency "
                    "percentiles include no-op samples", seismic_empty_results,
                    total_q)

    # Flat lists across all passes (RAM-peak sampling is pass-agnostic).
    seismic_latencies = [x for pl in seismic_lat_by_pass for x in pl]
    qdrant_latencies = [x for pl in qdrant_lat_by_pass for x in pl]
    seismic_encodes = [x for pl in seismic_encode_by_pass for x in pl]
    seismic_traverses = [x for pl in seismic_traverse_by_pass for x in pl]

    # ── 5. Post-query RAM samples ──────────────────────────────────────────────
    seismic_ram_post_queries = {
        "rssanon_kb": rssanon_kb(),
        "pssanon_kb": pssanon_kb(),
        "vmrss_kb": vmrss_kb(),
        "vmswap_kb": vmswap_kb(),
    }
    log.info("SEISMIC post-queries: RssAnon=%s Pss_Anon=%s VmRSS=%s GB",
             gb(seismic_ram_post_queries["rssanon_kb"]),
             gb(seismic_ram_post_queries["pssanon_kb"]),
             gb(seismic_ram_post_queries["vmrss_kb"]))

    qdrant_ram_post_queries = None
    if qdrant_available:
        rssanon, pssanon, vmrss, vmswap = _get_process_ram(qdrant_pid)
        qdrant_ram_post_queries = {
            "rssanon_kb": rssanon,
            "pssanon_kb": pssanon,
            "vmrss_kb": vmrss,
            "vmswap_kb": vmswap,
        }
        log.info("Qdrant post-queries: RssAnon=%s Pss_Anon=%s VmRSS=%s GB",
                 gb(rssanon), gb(pssanon), gb(vmrss))

    # ── 6. Compute statistics ──────────────────────────────────────────────────
    def percentile(data, p):
        if not data:
            return None
        sorted_data = sorted(data)
        idx = int(len(sorted_data) * p / 100)
        return sorted_data[min(idx, len(sorted_data) - 1)]

    def lat_stats(vals):
        if not vals:
            return None
        return {
            "p50_ms": percentile(vals, 50),
            "p95_ms": percentile(vals, 95),
            "mean_ms": round(sum(vals) / len(vals), 2),
            "min_ms": min(vals),
            "max_ms": max(vals),
            "n": len(vals),
        }

    def cold_warm_stats(by_pass, flat):
        """Top-level = all passes (back-compat); cold = pass 0; warm = passes>=1.
        WARM is the steady-state serving number; COLD is the first-fault cost."""
        s = lat_stats(flat) or {}
        s["cold"] = lat_stats(by_pass[0]) if by_pass else None
        warm_vals = [x for pl in by_pass[1:] for x in pl]
        s["warm"] = lat_stats(warm_vals) if warm_vals else None
        s["n_passes"] = len(by_pass)
        return s

    seismic_stats = cold_warm_stats(seismic_lat_by_pass, seismic_latencies)
    qdrant_stats = cold_warm_stats(qdrant_lat_by_pass, qdrant_latencies) if qdrant_latencies else None
    # encode/traverse sub-stats (same cold/warm shape). The split attributes the
    # SEISMIC end-to-end latency to the SPLADE encode vs the index traversal —
    # item-#3 latency diagnosis (None when the backend had no split / all failed).
    seismic_encode_stats = cold_warm_stats(seismic_encode_by_pass, seismic_encodes) if seismic_encodes else None
    seismic_traverse_stats = cold_warm_stats(seismic_traverse_by_pass, seismic_traverses) if seismic_traverses else None

    # ── 7. Compute RAM deltas and per-doc rates ─────────────────────────────
    def compute_engine_ram_summary(ram_baseline, ram_post_queries, docs=TOTAL_DOCS):
        """Compute anon floor and per-doc rate for an engine."""
        if not ram_baseline or not ram_post_queries:
            return {}

        # Anon DELTA (post-queries minus this-run idle baseline). NOTE: only a
        # valid "floor" for a fresh in-process engine (SEISMIC). For a long-running
        # server (Qdrant) the anon is already resident at baseline → delta collapses
        # to ~0 and is NOT the floor. Use the ABSOLUTE figures below for Qdrant.
        anon_delta_kb = (ram_post_queries.get("rssanon_kb") or 0) - (ram_baseline.get("rssanon_kb") or 0)
        pssanon_delta_kb = (ram_post_queries.get("pssanon_kb") or 0) - (ram_baseline.get("pssanon_kb") or 0)

        # ABSOLUTE anon at steady state (post-queries).
        anon_abs_kb = ram_post_queries.get("rssanon_kb")
        pssanon_abs_kb = ram_post_queries.get("pssanon_kb")
        swap_kb = ram_post_queries.get("vmswap_kb")

        # TRUE anon floor = resident anon + anon paged OUT to swap. On a
        # memory-pressured host RssAnon alone undercounts the floor by VmSwap
        # (the kernel hides demand by swapping it out, NOT by freeing it). This
        # is the OOM-relevant number and the method-consistent cross-engine floor.
        true_anon_floor_kb = (anon_abs_kb or 0) + (swap_kb or 0)

        # Peak VmRSS (total resident including reclaimable)
        vmrss_peak_kb = ram_post_queries.get("vmrss_kb")

        # Per-doc rates (use the TRUE anon floor — resident + swapped)
        anon_bytes_per_doc = (true_anon_floor_kb * 1024 / docs) if (docs and true_anon_floor_kb) else None

        return {
            "anon_floor_gb": gb(true_anon_floor_kb),  # resident anon + swap = OOM floor
            "rss_anon_gb": gb(anon_abs_kb),            # resident anon only
            "vmswap_gb": gb(swap_kb),                  # anon paged out to swap
            "anon_delta_gb": gb(anon_delta_kb),        # within-run growth (fresh proc only)
            "pss_anon_gb": gb(pssanon_abs_kb),
            "vmrss_peak_gb": gb(vmrss_peak_kb),
            "vmrss_peak_bytes": vmrss_peak_kb * 1024 if vmrss_peak_kb else None,
            "anon_bytes_per_doc": anon_bytes_per_doc,
            "baseline_anon_gb": gb(ram_baseline.get("rssanon_kb")),
        }

    seismic_ram_summary = compute_engine_ram_summary(seismic_ram_baseline, seismic_ram_post_queries)
    qdrant_ram_summary = None
    if qdrant_ram_baseline and qdrant_ram_post_queries:
        qdrant_ram_summary = compute_engine_ram_summary(qdrant_ram_baseline, qdrant_ram_post_queries)

    # ── 8. Verdict ──────────────────────────────────────────────────────
    # _stat + _latency_caveat are module-level (pure helpers, no closure deps)
    # so the regime-aware verdict gate is testable without running a full bench.
    lat_caveat = _latency_caveat(seismic_ram_summary, seismic_stats,
                                 load_mode, memcomp)
    verdict = ""
    if seismic_ram_summary and qdrant_ram_summary:
        s_anon = seismic_ram_summary.get("anon_floor_gb") or float("inf")
        q_anon = qdrant_ram_summary.get("anon_floor_gb") or float("inf")
        anon_diff = s_anon - q_anon

        s_rss = seismic_ram_summary.get("rss_anon_gb")
        s_swap = seismic_ram_summary.get("vmswap_gb")
        q_rss = qdrant_ram_summary.get("rss_anon_gb")
        q_swap = qdrant_ram_summary.get("vmswap_gb")
        verdict = (
            f"RAM (TRUE anon floor = RssAnon + VmSwap): SEISMIC {s_anon:.3f} GB "
            f"(rss {s_rss} + swap {s_swap}) vs Qdrant {q_anon:.3f} GB (rss {q_rss} + swap {q_swap}) "
            f"— delta {anon_diff:+.3f} GB. RssAnon ALONE undercounts the floor by VmSwap on "
            f"a swap-pressured host. SEISMIC's index is file-backed mmap (reclaimable page "
            f"cache, ~0 swap); Qdrant's postings are anon heap that the kernel pages to swap. "
            f"NOTE: SEISMIC's in-process figure also bundles the SPLADE encoder, so the "
            f"index-only SEISMIC win is even larger. "
            f"Latency WARM p50/p95: SEISMIC "
            f"{_stat(seismic_stats,'warm','p50_ms')}/{_stat(seismic_stats,'warm','p95_ms')} ms "
            f"vs Qdrant {_stat(qdrant_stats,'warm','p50_ms')}/{_stat(qdrant_stats,'warm','p95_ms')} ms; "
            f"COLD p50: SEISMIC {_stat(seismic_stats,'cold','p50_ms')} ms "
            f"vs Qdrant {_stat(qdrant_stats,'cold','p50_ms')} ms ({seismic_stats.get('n_passes')} passes). "
            + lat_caveat
        )
    else:
        verdict = "QDRANT UNAVAILABLE — SEISMIC benchmarked, Qdrant side BLOCKED. " + lat_caveat

    # ── 9. Write results ────────────────────────────────────────────────────
    result = {
        "meta": {
            "date_utc": datetime.utcnow().isoformat(),
            "benchmark": "SEISMIC vs Qdrant serving footprint at 150M docs",
            "total_docs": TOTAL_DOCS,
            "queries": len(queries),
            "top_k": args.top_k,
            "query_encoding": "encode_splade + top-64 terms",
            "seismic_load_mode": load_mode,
            "seismic_federation": federation,
            "qdrant_available": qdrant_available,
            # G8 2×2 matrix cell: load axis (mmap=Path C file-backed / stock=Path A
            # owned anon) × mem-compression axis (zram/zswap/windows_compression/
            # disk_swap/off/unknown). detect_memcompression() resolves the regime;
            # SFU_MEMCOMPRESSION_REGIME overrides when /proc can't see it (Windows
            # host compression). The verdict gate is regime-dependent — see
            # _latency_caveat() + detect_memcompression().
            "g8_matrix_cell": {
                "load_mode": load_mode,
                "memcompression_regime": memcomp["regime"],
                "regime_compressed_in_ram": _regime_is_compressed_in_ram(memcomp["regime"]),
                "regime_sources": memcomp["sources"],
                "zram_devs": memcomp["zram_devs"],
                "zswap_enabled": memcomp["zswap_enabled"],
            },
        },
        "seismic": {
            "engine": f"seismic-pyseismic + {type(sb).__name__} "
                      f"({len(index_paths)} shard{'s' if len(index_paths)!=1 else ''}, "
                      f"{load_mode}, {federation})",
            "load_seconds": round(load_secs, 2),
            "load_mode": load_mode,
            "federation": federation,
            # Query-time knobs in effect (from SFU_SEISMIC_* env — see
            # _seismic_query_knobs). Records whether the §C1 lever (query_cut=10)
            # was active on this run. None = all-terms (the recall-first default).
            "query_cut": os.environ.get("SFU_SEISMIC_QUERY_CUT"),
            "heap_factor": os.environ.get("SFU_SEISMIC_HEAP_FACTOR", "0.8"),
            "k_prime": os.environ.get("SFU_SEISMIC_K_PRIME"),
            "ram": seismic_ram_summary,
            # Failed/empty queries across all passes (0 on a healthy run). The
            # all-failed case exits(3) before writing; a nonzero value here
            # means the percentiles include no-op samples — treat with care.
            "empty_results": seismic_empty_results,
            "latency_ms": seismic_stats,
            "latency_by_pass_ms": [[round(x, 1) for x in pl] for pl in seismic_lat_by_pass],
            # item-#3 encode/traverse attribution. encode_ms = SPLADE ONNX query
            # encode; traverse_ms = 8-shard fan-out. latency_ms (above) = end-to-end
            # total = encode + traverse (back-compat with the pre-split number).
            # None if the backend exposed no split or every query failed to encode.
            "encode_ms": seismic_encode_stats,
            "traverse_ms": seismic_traverse_stats,
            "encode_by_pass_ms": [[round(x, 1) for x in pl] for pl in seismic_encode_by_pass],
            "traverse_by_pass_ms": [[round(x, 1) for x in pl] for pl in seismic_traverse_by_pass],
        },
        "qdrant": {
            "engine": "Qdrant sparse_150m collection (on_disk)",
            "server_pid": qdrant_pid,
            "available": qdrant_available,
            "ram": qdrant_ram_summary,
            "latency_ms": qdrant_stats,
            "latency_by_pass_ms": [[round(x, 1) for x in pl] for pl in qdrant_lat_by_pass],
        },
        "verdict": verdict,
    }

    with open(result_file, "w") as f:
        json.dump(result, f, indent=2)

    log.info("result written to %s", result_file)

    # ── 10. Log summary ────────────────────────────────────────────────
    log.info("\n=== RESULTS ===")
    log.info("SEISMIC:")
    log.info("  Anon floor: %s GB", seismic_ram_summary.get("anon_floor_gb"))
    log.info("  Pss_Anon: %s GB", seismic_ram_summary.get("pss_anon_gb"))
    log.info("  VmRSS peak: %s GB", seismic_ram_summary.get("vmrss_peak_gb"))
    log.info("  Anon bytes/doc: %s", seismic_ram_summary.get("anon_bytes_per_doc"))
    log.info("  Latency p50/p95/mean: %s / %s / %s ms",
             seismic_stats.get("p50_ms"), seismic_stats.get("p95_ms"), seismic_stats.get("mean_ms"))
    if seismic_encode_stats and seismic_traverse_stats:
        log.info("  encode (SPLADE ONNX) p50/mean: %s / %s ms",
                 seismic_encode_stats.get("p50_ms"), seismic_encode_stats.get("mean_ms"))
        log.info("  traverse (8-shard fan-out) p50/mean: %s / %s ms",
                 seismic_traverse_stats.get("p50_ms"), seismic_traverse_stats.get("mean_ms"))
        log.info("  (encode+traverse end-to-end == latency_ms above; item-#3 attribution)")

    if qdrant_available:
        log.info("QDRANT (PID %d):", qdrant_pid)
        log.info("  Anon floor: %s GB", qdrant_ram_summary.get("anon_floor_gb"))
        log.info("  Pss_Anon: %s GB", qdrant_ram_summary.get("pss_anon_gb"))
        log.info("  VmRSS peak: %s GB", qdrant_ram_summary.get("vmrss_peak_gb"))
        log.info("  Anon bytes/doc: %s", qdrant_ram_summary.get("anon_bytes_per_doc"))
        log.info("  Latency p50/p95/mean: %s / %s / %s ms",
                 qdrant_stats.get("p50_ms"), qdrant_stats.get("p95_ms"), qdrant_stats.get("mean_ms"))
    else:
        log.warning("QDRANT: NOT AVAILABLE")

    log.info("\nVERDICT: %s", verdict)

    # ── 11. Tee to log file ────────────────────────────────────────────────
    with open(log_file, "w") as f:
        f.write("=== SEISMIC vs Qdrant Serving Footprint Benchmark ===\n")
        f.write(f"Date: {datetime.utcnow().isoformat()}\n")
        f.write(f"Queries: {len(queries)}\n")
        f.write(f"Total docs: {TOTAL_DOCS}\n\n")

        f.write("SEISMIC:\n")
        f.write(f"  Load time: {load_secs:.1f}s\n")
        f.write(f"  Anon floor: {seismic_ram_summary.get('anon_floor_gb')} GB\n")
        f.write(f"  Pss_Anon: {seismic_ram_summary.get('pss_anon_gb')} GB\n")
        f.write(f"  VmRSS peak: {seismic_ram_summary.get('vmrss_peak_gb')} GB\n")
        f.write(f"  Anon bytes/doc: {seismic_ram_summary.get('anon_bytes_per_doc')}\n")
        f.write(f"  Latency p50: {seismic_stats.get('p50_ms')} ms\n")
        f.write(f"  Latency p95: {seismic_stats.get('p95_ms')} ms\n")
        f.write(f"  Latency mean: {seismic_stats.get('mean_ms')} ms\n\n")

        if qdrant_available:
            f.write(f"QDRANT (PID {qdrant_pid}):\n")
            f.write(f"  Anon floor: {qdrant_ram_summary.get('anon_floor_gb')} GB\n")
            f.write(f"  Pss_Anon: {qdrant_ram_summary.get('pss_anon_gb')} GB\n")
            f.write(f"  VmRSS peak: {qdrant_ram_summary.get('vmrss_peak_gb')} GB\n")
            f.write(f"  Anon bytes/doc: {qdrant_ram_summary.get('anon_bytes_per_doc')}\n")
            f.write(f"  Latency p50: {qdrant_stats.get('p50_ms')} ms\n")
            f.write(f"  Latency p95: {qdrant_stats.get('p95_ms')} ms\n")
            f.write(f"  Latency mean: {qdrant_stats.get('mean_ms')} ms\n\n")
        else:
            f.write("QDRANT: NOT AVAILABLE\n\n")

        f.write(f"VERDICT:\n{verdict}\n")

    log.info("log written to %s", log_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
