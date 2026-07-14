#!/usr/bin/env python3
"""F6 (2026-07-14): cold-start prefault-hotset-at-load bench — Phase 6.

The phase that EXISTS to move the cold p95 number (doc 03 §3
"cold-start-sensitive" row). At load, prefault (NOT mlock) the F2 sidecar's hot
extents via the new `prefault_ranges` pyo3 hook (Q9-style WILLNEED|SEQUENTIAL +
page-stride read into the page cache, reclaimable). Re-run the Q7 hybrid
cold/warm benchmark with prefault ON vs the E8 v2 baseline (measured 2026-07-13,
`_e8s2_q7_federated_v2_20260713.json`): hybrid cold p50 783-899 ms / p95
4.6-4.9 s; warm p50 115-120 ms / p95 177-182 ms. Report the cold p95 delta
explicitly — it is the number this phase exists to move.

Reuses q7's EXACT cell protocol (fadvise-DONTNEED + serve_footprint_bench) so
numbers are directly comparable.

NOTE (host-gating, recorded honestly): the dev container's cold p95 here is
container-disk-bound (the 62 GB index faults from drvfs/9p), which is a COLD
fault regime but NOT the 32 GB-host warm≈cold re-fault regime. A prefault at
load warms the page cache ONCE; under fadvise-DONTNEED per cell it is evicted
before each cold cell — so the cold-cell delta may be SMALL here (the hotset is
prefaulted at process load, but the cold-cell protocol evicts it). The real win
is on the FIRST cold query of a fresh process WITHOUT eviction (process-cold
warmup) — recorded as the targeted measurement.
"""
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from q7_hybrid_federation_bench import run_cell, _cold_p50, _warm_p50, _vmswap_gb  # noqa: E402

MANIFEST = "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"
REPS = 2
QUERIES = 100
PASSES = 3
# The E8 v2 Q7 baseline (measured 2026-07-13, to beat).
BASELINE = {
    "hybrid_cold_p50_median_ms": 840.93,
    "hybrid_cold_p95_ms_lo": 4600.0,  # 4.6 s
    "hybrid_cold_p95_ms_hi": 4900.0,  # 4.9 s
    "hybrid_warm_p50_median_ms": 117.61,
    "hybrid_warm_p95_ms_lo": 177.0,
    "hybrid_warm_p95_ms_hi": 182.0,
    "source": "_e8s2_q7_federated_v2_20260713.json",
}


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def cell_cold_p95(cell: dict) -> float | None:
    s = cell.get("seismic", {}).get("latency_ms", {})
    c = s.get("cold") or {}
    return c.get("p95_ms")


def cell_warm_p95(cell: dict) -> float | None:
    s = cell.get("seismic", {}).get("latency_ms", {})
    w = s.get("warm") or {}
    return w.get("p95_ms")


def main():
    bench_env = {"SFU_SEISMIC_LOAD_MODE": "mmap",
                 "SFU_SEISMIC_PREFLOOR_HOTSET": "1"}  # F6 ON
    cells = []
    for rep in range(1, REPS + 1):
        cell = run_cell(MANIFEST, "hybrid", QUERIES, PASSES, rep, bench_env)
        # Refuse poisoned cells (2026-07-14): the invalid F6 run aggregated
        # cells where 298-300/300 queries were swallowed no-ops. exit(3) in
        # serve_footprint_bench catches >20%-failed; this belt-and-braces check
        # catches any nonzero count that slips through as a warning.
        empty = cell.get("seismic", {}).get("empty_results", 0)
        if empty:
            raise RuntimeError(
                f"rep{rep} cell has {empty} empty/failed queries — not a valid "
                f"latency measurement; fix the serving path first "
                f"(cell: {cell.get('_cell_file')})")
        cells.append({
            "cold_p50": _cold_p50(cell), "warm_p50": _warm_p50(cell),
            "cold_p95": cell_cold_p95(cell), "warm_p95": cell_warm_p95(cell),
            "vmswap": _vmswap_gb(cell), "file": cell.get("_cell_file"),
        })
        log(f"rep{rep}: cold p50 {_cold_p50(cell):.0f}ms p95 {cell_cold_p95(cell):.0f}ms | "
            f"warm p50 {_warm_p50(cell):.0f}ms p95 {cell_warm_p95(cell):.0f}ms")

    colds = [c["cold_p50"] for c in cells if c["cold_p50"]]
    colds_p95 = [c["cold_p95"] for c in cells if c["cold_p95"]]
    warms = [c["warm_p50"] for c in cells if c["warm_p50"]]
    warms_p95 = [c["warm_p95"] for c in cells if c["warm_p95"]]
    out = {
        "probe": "f6_prefault_hotset_bench",
        "date": time.strftime("%Y-%m-%d"),
        "manifest": MANIFEST,
        "gate": "SFU_SEISMIC_PREFLOOR_HOTSET=1 (prefault hot extents at load, "
               "reclaimable — Q9-style WILLNEED|SEQUENTIAL + page stride)",
        "n_queries": QUERIES, "reps": REPS, "passes": PASSES,
        "cells": cells,
        "aggregate": {
            "cold_p50_median": statistics.median(colds) if colds else None,
            "cold_p95_median": statistics.median(colds_p95) if colds_p95 else None,
            "warm_p50_median": statistics.median(warms) if warms else None,
            "warm_p95_median": statistics.median(warms_p95) if warms_p95 else None,
        },
        "baseline_e8v2_q7": BASELINE,
        "cold_p95_delta_ms": (statistics.median(colds_p95) - BASELINE["hybrid_cold_p95_ms_lo"])
                             if colds_p95 else None,
        "caveat": "Container cold regime (drvfs/9p fault) — NOT the 32 GB-host "
                  "warm=cold re-fault regime. fadvise-DONTNEED per cold cell "
                  "evicts the prefaulted hotset, so the cold-CELL delta may be "
                  "small; the real win is the FIRST cold query of a fresh process "
                  "(process-cold warmup, no eviction) — recorded as targeted.",
    }
    out_path = REPO / "data" / "eval_results" / (
        "f6_prefault_hotset_" + time.strftime("%Y%m%d") + ".json")
    out_path.write_text(json.dumps(out, indent=2, default=str))
    log(f"wrote {out_path}")
    log(f"cold p95 median: {out['aggregate']['cold_p95_median']:.0f} ms "
        f"(baseline {BASELINE['hybrid_cold_p95_ms_lo']:.0f}-{BASELINE['hybrid_cold_p95_ms_hi']:.0f} ms)")


if __name__ == "__main__":
    main()
