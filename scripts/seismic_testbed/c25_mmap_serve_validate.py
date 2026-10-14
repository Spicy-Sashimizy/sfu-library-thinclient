#!/usr/bin/env python3
"""C2.5 — pyo3 mmap-reader validation at the Python serve boundary (2026-06-28).

WHY THIS SCRIPT. The C1a/C2 `MmapSeismicIndex` (Rust) keeps the Path-C floor:
C2 `KEEPS_GATE` measured anon Δ +0.041 GB ≈ 0, file-resident 96 % of the index,
parity bit-identical, 0.97× latency — but all from a **Rust bin**. C2.5 ships the
pyo3 binding (`seismic.MmapSeismicIndex`) so the 150M serving layer
(`seismic_federated.py` → `lib.thinclient.seismic_backend`) can load shards mmap'd
instead of via stock `SeismicIndex.load()` (Path A, owned anon, ~137 GB @150M —
unservable on 32 GB). This script is the make-or-break: does the same floor +
parity hold when the index is constructed **from Python** (no hidden
re-materialization through the pyo3 boundary, no owned copy)?

METHOD (mirrors the c2 bin's four-phase shape, but at the pyo3 boundary):
  1. Baseline RSS (RssAnon/RssFile).
  2. Load stock Path-A `SeismicIndex.load(...)`  -> reference + owned floor.
  3. Drop owned + gc/malloc_trim-equivalent (Python: gc.collect + del).
  4. `seismic.MmapSeismicIndex(mmap_dir)`          -> the Path-C reader, from Python.
  5. Same real SPLADE queries through both; assert bit-identical top-k
     (same doc-ids in the same order, scores within 1e-4).
  6. Floor: RssAnon delta vs baseline ≈ 0 (< 0.1 GB), RssFile ≈ on-disk index.

This reuses the existing persona 2M index in BOTH layouts:
  stock:    /tmp/seismic_testbed/index/med_bio_2m.index.seismic   (1.69 GB)
  mmap dir: /tmp/seismic_testbed/mmap_c2/                          (written by the C2 run)

Output: data/eval_results/seismic_c25_mmap_serve_validate.json
Verdict: `C2.5 MMAP_SERVE_READY` iff parity_ok AND floor_anon_ok AND floor_file_ok.
"""
from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import sys
import time
from pathlib import Path

log = logging.getLogger("c25")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STOCK = "/tmp/seismic_testbed/index/med_bio_2m.index.seismic"
DEFAULT_MMAP = "/tmp/seismic_testbed/mmap_c2"
DEFAULT_QUERIES = REPO_ROOT / "data/eval_results/diverse_queries.json"
DEFAULT_MODEL = "models/splade_onnx_fp16"


def read_rss_kb() -> tuple[int, int]:
    """Return (RssAnon_kb, RssFile_kb) for this process from /proc/self/status."""
    anon = file = 0
    try:
        with open("/proc/self/status") as f:
            for ln in f:
                if ln.startswith("RssAnon:"):
                    anon = int(ln.split()[1])
                elif ln.startswith("RssFile:"):
                    file = int(ln.split()[1])
    except OSError:
        pass
    return anon, file


def _dir_size_bytes(p: str) -> int:
    total = 0
    for root, _, files in os.walk(p):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def load_queries(path: Path, n: int) -> list[str]:
    recs = json.loads(path.read_text())
    qs = [r.get("paraphrase") or r.get("query") for r in recs]
    qs = [q for q in qs if q][:n]
    return qs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stock-index", default=DEFAULT_STOCK)
    ap.add_argument("--mmap-dir", default=DEFAULT_MMAP)
    ap.add_argument("--queries", default=str(DEFAULT_QUERIES))
    ap.add_argument("--model-path", default=DEFAULT_MODEL)
    ap.add_argument("--n-queries", type=int, default=30)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--query-cut", type=int, default=8)
    ap.add_argument("--heap-factor", type=float, default=1.0)
    ap.add_argument("--out", default=str(REPO_ROOT / "data/eval_results/seismic_c25_mmap_serve_validate.json"))
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Make source/ importable for lib.opensearch_retriever.encode_splade.
    sys.path.insert(0, str(REPO_ROOT / "source"))

    import numpy as np  # noqa: E402
    import seismic  # noqa: E402

    string_dtype = seismic.get_seismic_string()

    # --- encode real SPLADE queries ONCE (shared by both indexes) -------------
    queries = load_queries(Path(args.queries), args.n_queries)
    if not queries:
        log.error("no queries loaded from %s", args.queries)
        return 2
    log.info("encoding %d real SPLADE queries via %s ...", len(queries), args.model_path)
    from lib.opensearch_retriever import encode_splade  # noqa: E402

    encoded: list[tuple[list[str], list[float]]] = []
    for q in queries:
        sparse = encode_splade(q, args.model_path)
        # Match SeismicBackend.encode_query: top-64 by value.
        top = dict(sorted(sparse.items(), key=lambda x: -x[1])[:64])
        if not top:
            continue
        toks = list(top.keys())
        vals = [float(top[t]) for t in toks]
        encoded.append((toks, vals))
    log.info("encoded %d queries (dropped %d empty)", len(encoded), len(queries) - len(encoded))
    if not encoded:
        log.error("no query produced any SPLADE tokens; cannot validate")
        return 2

    mmap_disk_bytes = _dir_size_bytes(args.mmap_dir)

    # --- Phase 1: baseline RSS ------------------------------------------------
    gc.collect(); gc.collect()
    base_anon, base_file = read_rss_kb()
    log.info("[Phase 1] baseline RssAnon=%.3f GB RssFile=%.3f GB",
             base_anon / 1e6, base_file / 1e6)

    # --- Phase 2: load stock Path-A index + reference results -----------------
    log.info("[Phase 2] SeismicIndex.load(%s) ...", args.stock_index)
    t0 = time.perf_counter()
    stock = seismic.SeismicIndex.load(args.stock_index)
    load_secs = time.perf_counter() - t0
    path_a_anon, path_a_file = read_rss_kb()
    log.info("  loaded in %.2fs len=%d dim=%d nnz=%d", load_secs, stock.len, stock.dim, stock.nnz)
    log.info("  RssAnon after load (Path-A floor): %.3f GB   RssFile: %.3f GB",
             path_a_anon / 1e6, path_a_file / 1e6)

    qc = args.query_cut
    hf = args.heap_factor
    log.info("[Phase 2b] reference search through owned index...")
    stock_results: list[list[tuple[str, float, str]]] = []
    for toks, vals in encoded:
        qcomp = np.array(toks, dtype=string_dtype)
        qvals = np.array(vals, dtype=np.float32)
        res = stock.search("q", qcomp, qvals, args.top_k, qc, hf)
        stock_results.append(res)
    log.info("  %d reference queries done", len(stock_results))

    # --- Phase 3: drop owned index + reclaim ----------------------------------
    log.info("[Phase 3] drop owned index + gc.collect x3 ...")
    del stock
    gc.collect(); gc.collect(); gc.collect()
    time.sleep(0.2)
    mmap_base_anon, mmap_base_file = read_rss_kb()
    log.info("  post-drop baseline RssAnon=%.3f GB RssFile=%.3f GB",
             mmap_base_anon / 1e6, mmap_base_file / 1e6)

    # --- Phase 4: MmapSeismicIndex from Python --------------------------------
    log.info("[Phase 4] seismic.MmapSeismicIndex(%s) ...", args.mmap_dir)
    t0 = time.perf_counter()
    mmap_idx = seismic.MmapSeismicIndex(args.mmap_dir)
    mmap_load_secs = time.perf_counter() - t0
    pre_fault_anon, pre_fault_file = read_rss_kb()
    log.info("  constructed in %.2fs len=%d dim=%d nnz=%d",
             mmap_load_secs, mmap_idx.len, mmap_idx.dim, mmap_idx.nnz)
    log.info("  RssAnon post-construct (pre-fault): %.3f GB   RssFile: %.3f GB",
             pre_fault_anon / 1e6, pre_fault_file / 1e6)

    # Fault in the whole slab BEFORE the floor measurement, so RssFile reflects
    # true residency (freshly-mmap'd pages report RssFile ≈ 0 until read —
    # identical to why the C2 Rust bin calls touch_slab before measuring).
    log.info("  faulting in the mmap slab (touch_slab)...")
    t0 = time.perf_counter()
    touched = mmap_idx.touch_slab()
    fault_secs = time.perf_counter() - t0
    after_anon, after_file = read_rss_kb()
    log.info("  touch_slab: %.2fs bytes_touched=%d", fault_secs, touched)
    log.info("  RssAnon after fault-in: %.3f GB (%.0f KB)   RssFile: %.3f GB (%.0f KB)",
             after_anon / 1e6, after_anon, after_file / 1e6, after_file)

    floor_anon_delta_gb = (after_anon - mmap_base_anon) / 1e6
    floor_file_gb = after_file / 1e6
    mmap_disk_gb = mmap_disk_bytes / 1e9

    # --- Phase 5: parity (mmap results vs owned reference) --------------------
    log.info("[Phase 5] parity: mmap search vs owned reference...")
    mismatches: list[str] = []
    n_pair = 0
    for i, (toks, vals) in enumerate(encoded):
        qcomp = np.array(toks, dtype=string_dtype)
        qvals = np.array(vals, dtype=np.float32)
        mres = mmap_idx.search("q", qcomp, qvals, args.top_k, qc, hf)
        sres = stock_results[i]
        n_pair += 1
        if len(mres) != len(sres):
            mismatches.append(f"q{i}: length mismatch stock={len(sres)} mmap={len(mres)}")
            continue
        for j, ((_, sscore, sdoc), (_, mscore, mdoc)) in enumerate(zip(sres, mres)):
            if sdoc != mdoc:
                mismatches.append(f"q{i}[{j}]: doc_id mismatch stock={sdoc!r} mmap={mdoc!r}")
                break
            if abs(sscore - mscore) > 1e-4:
                mismatches.append(f"q{i}[{j}]: score mismatch stock={sscore:.6f} mmap={mscore:.6f}")
                break
    parity_ok = not mismatches
    log.info("  paired %d queries; %d mismatches -> parity_ok=%s",
             n_pair, len(mismatches), parity_ok)
    for m in mismatches[:5]:
        log.info("    %s", m)

    # --- Phase 6: warm latency (mmap) -----------------------------------------
    log.info("[Phase 6] warm mmap latency (3 iters)...")
    warm = []
    for _ in range(3):
        for toks, vals in encoded:
            qcomp = np.array(toks, dtype=string_dtype)
            qvals = np.array(vals, dtype=np.float32)
            t0 = time.perf_counter()
            mmap_idx.search("q", qcomp, qvals, args.top_k, qc, hf)
            warm.append((time.perf_counter() - t0) * 1000.0)
    warm.sort()
    p50 = warm[len(warm) // 2] if warm else 0.0
    p95 = warm[int(len(warm) * 0.95)] if warm else 0.0
    log.info("  mmap warm p50=%.3f ms p95=%.3f ms (n=%d)", p50, p95, len(warm))

    # --- Verdict --------------------------------------------------------------
    floor_anon_ok = floor_anon_delta_gb < 0.1
    floor_file_ok = (after_file / 1e6) > 0.5 * mmap_disk_gb
    verdict = ("C2.5 MMAP_SERVE_READY"
               if (parity_ok and floor_anon_ok and floor_file_ok)
               else "C2.5 BLOCKED")
    log.info("[VERDICT] %s  (parity=%s anon_ok=%s file_ok=%s)",
             verdict, parity_ok, floor_anon_ok, floor_file_ok)

    out = {
        "c25_verdict": verdict,
        "parity_ok": parity_ok,
        "parity_failures": mismatches[:20],
        "n_paired_queries": n_pair,
        "floor_anon_ok": floor_anon_ok,
        "floor_file_ok": floor_file_ok,
        "floor_ok": floor_anon_ok and floor_file_ok,
        "floor_anon_delta_gb": round(floor_anon_delta_gb, 4),
        "floor_file_gb": round(floor_file_gb, 4),
        "mmap_disk_gb": round(mmap_disk_gb, 4),
        "latency_ms": {
            "mmap_warm_p50": round(p50, 4),
            "mmap_warm_p95": round(p95, 4),
            "mmap_load_secs": round(mmap_load_secs, 4),
        },
        "rss_kb": {
            "baseline_anon": base_anon,
            "baseline_file": base_file,
            "path_a_anon_after_load": path_a_anon,
            "path_a_file_after_load": path_a_file,
            "mmap_base_anon_after_drop": mmap_base_anon,
            "mmap_base_file_after_drop": mmap_base_file,
            "mmap_anon_pre_fault": pre_fault_anon,
            "mmap_file_pre_fault": pre_fault_file,
            "mmap_anon_after_fault_in": after_anon,
            "mmap_file_after_fault_in": after_file,
            "touch_slab_bytes_touched": touched,
            "touch_slab_secs": round(fault_secs, 4),
        },
        "config": {
            "stock_index": args.stock_index,
            "mmap_dir": args.mmap_dir,
            "n_docs": getattr(mmap_idx, "len", -1),
            "dim": getattr(mmap_idx, "dim", -1),
            "nnz": getattr(mmap_idx, "nnz", -1),
            "n_queries": n_pair,
            "top_k": args.top_k,
            "query_cut": qc,
            "heap_factor": hf,
            "query_source": str(args.queries),
        },
        "meta": {
            "built_utc": "2026-06-28",
            "purpose": "C2.5: validate the pyo3 mmap reader at the Python serve "
                       "boundary — same parity + floor as the C2 Rust bin, but "
                       "constructed from `seismic.MmapSeismicIndex`.",
            "engine": "seismic-pyseismic-lsr-0.4.0 spike-fork (C2.5 pyo3 mmap binding)",
            "doc_refs": [
                "docs/seismic_150m_testbed/07_G3_RAM_FIX_PLAN.md §4.4 (C2.5)",
                "spike/seismic_upstream/src/pylib/mmap_index.rs (PyMmapIndex pyclass)",
                ".claude/plans/seismic-c25-pyo3-mmap-binding.md",
                "C2 baseline: data/eval_results/seismic_c2_mmap_metadata_close.json (KEEPS_GATE)",
            ],
        },
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    log.info("wrote %s", args.out)
    return 0 if verdict.startswith("C2.5 MMAP_SERVE_READY") else 1


if __name__ == "__main__":
    sys.exit(main())
