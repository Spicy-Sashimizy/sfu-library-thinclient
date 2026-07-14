#!/usr/bin/env python3
"""Q9 — startup floor prefault benchmark (2026-07-10).

At backend load, touch each shard's small structural slabs (posting-lists +
doc-mapping + forward_offsets — the ~1.52 GB / ~5,000-page constant floor
E7 Fix #4 identified) so the first real query pays only forward-data faults.
This is ONCE-AT-LOAD, distinct from the REFUTED per-range query-time WILLNEED
(doc 10 Fix #3 — per-query, kernel-ignored + syscall overhead).

PRE-REGISTERED BARS (written BEFORE measurement, doc 12 §3 Q9):
  - cold-pass p50 >= 1.15x FASTER with prefault ON (else KILL)
    i.e. prefault_cold_p50 <= cold_p50 / 1.15
  - load-time increase <= ~5 s
  - warm p50 ratio (ON/OFF) <= 1.05 (no warm regression)
  - zero anon growth (touch, don't copy)

PROTOCOL (container, 2026-07-09): fadvise-DONTNEED eviction before every cold
cell; paired ratios only (Rule 5); a cold cell counts only if VmSwap ~ 0 AND
warm p50 < cold p50. Rule Zero: the served shards are READ-ONLY (fadvise is a
read-only kernel hint; prefault_floor reads the slabs in place).

Cells: parallel federation (the served path), 2 arms (prefault OFF / ON) x 2
reps, alternating. Each cell = serve_footprint_bench subprocess at
--queries 40 --passes 3, SFU_SEISMIC_PREFLOOR_AT_LOAD=0|1 set per arm, with
fadvise-DONTNEED before each.

NOTE on the cold-cell subtlety: serve_footprint_bench does ONE warmup query
before the timed cold pass. The prefault happens at load (before warmup), so
the warmup query faults forward-data only (the floor is already warm). The cold
pass therefore measures forward-data faulting under both arms — the prefault
advantage shows up as fewer majflt in the floor slabs (which the ON arm already
touched). The paired cold-p50 ratio is the verdict.

Usage (repo root, project venv):

    .venv/bin/python3 scripts/seismic_testbed/q9_floor_prefault_bench.py \
        --manifest data/eval_results/seismic_c25_shards_150m_mmap_e5.json \
        --reps 2 --queries 40 --passes 3 \
        --result-file data/eval_results/q9_floor_prefault_20260710.json
"""
import argparse
import json
import logging
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

log = logging.getLogger("q9_bench")

BENCH = REPO / "scripts" / "seismic_testbed" / "serve_footprint_bench.py"

BARS = {
    "cold_p50_ON_at_least_1.15x_faster": 1.15,
    "load_time_increase_le_5s": 5.0,
    "warm_p50_ratio_ON_over_OFF_le_1.05": 1.05,
    "zero_anon_growth": "touch not copy",
    "protocol": "fadvise-DONTNEED per cell, paired ratios, VmSwap~0 + warm<cold",
}


def fadvise_dontneed_manifest(manifest_path: str) -> int:
    """Evict every shard's file-backed pages before a cold cell (container
    cold-protocol substitute for drop_caches; reuses the Q7/e5 convention)."""
    from lib.thinclient.sharded_seismic_backend import _load_manifest
    shard_dirs = _load_manifest(manifest_path, load_mode="mmap")
    total = 0
    for d in shard_dirs:
        p = Path(d)
        if not p.is_absolute():
            p = REPO / d
        if not p.is_dir():
            continue
        for f in sorted(os.listdir(p)):
            fp = p / f
            if not fp.is_file():
                continue
            fd = os.open(fp, os.O_RDONLY)
            try:
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
                total += os.path.getsize(fp)
            finally:
                os.close(fd)
    return total


def run_cell(manifest: str, prefloor_at_load: bool, queries: int, passes: int,
             rep: int) -> dict:
    """Run one serve_footprint_bench cell with prefault ON or OFF."""
    arm = "ON" if prefloor_at_load else "OFF"
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    cell_file = REPO / "data" / "eval_results" / \
        f"q9_prefloor_{arm}_{ts}_rep{rep}.json"

    evicted = fadvise_dontneed_manifest(manifest)
    log.info("[rep %d %s] fadvise-DONTNEED %.2f GB", rep, arm, evicted / 1e9)

    env = {**os.environ,
           "SFU_SEISMIC_SHARD_MANIFEST": manifest,
           "SFU_SEISMIC_LOAD_MODE": "mmap",
           "SFU_SEISMIC_FEDERATION": "parallel",  # the served path
           "SFU_SEISMIC_PREFLOOR_AT_LOAD": "1" if prefloor_at_load else "0",
           }
    cmd = [sys.executable, str(BENCH),
           "--shard-manifest", manifest,
           "--federation", "parallel",
           "--queries", str(queries),
           "--passes", str(passes),
           "--result-file", str(cell_file)]
    log.info("[rep %d %s] running prefault=%s", rep, arm, arm)
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    dt = time.perf_counter() - t0
    if proc.returncode != 0:
        log.error("[rep %d %s] FAILED rc=%d\nstderr:\n%s",
                  rep, arm, proc.returncode, proc.stderr[-1500:])
        raise RuntimeError(f"bench cell {arm} rep{rep} failed")
    log.info("[rep %d %s] done in %.1fs", rep, arm, dt)
    with open(cell_file) as f:
        result = json.load(f)
    result["_cell_file"] = str(cell_file.relative_to(REPO))
    result["_wall_secs"] = round(dt, 1)
    return result


def _cold_p50(cell: dict):
    try:
        return cell["seismic"]["latency_ms"]["cold"]["p50_ms"]
    except (KeyError, TypeError):
        return None


def _warm_p50(cell: dict):
    try:
        return cell["seismic"]["latency_ms"]["warm"]["p50_ms"]
    except (KeyError, TypeError):
        return None


def _vmswap(cell: dict):
    try:
        return cell["seismic"]["ram"]["vmswap_gb"]
    except (KeyError, TypeError):
        return None


def _anon_floor(cell: dict):
    try:
        return cell["seismic"]["ram"]["anon_floor_gb"]
    except (KeyError, TypeError):
        return None


def _load_secs(cell: dict):
    try:
        return cell["seismic"]["load_seconds"]
    except (KeyError, TypeError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--result-file", required=True)
    ap.add_argument("--from-cells", action="store_true",
                    help="recover the aggregate from saved cell JSONs instead of "
                         "rerunning the cold cells (recovery path for a wrapper "
                         "crash at write-time)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    manifest = args.manifest
    manifest_path = manifest if Path(manifest).is_absolute() else str(REPO / manifest)
    if not Path(manifest_path).exists():
        log.error("manifest not found: %s", manifest_path)
        return 2

    result_file = REPO / args.result_file

    # If --from-cells is set, recover the aggregate from saved cell JSONs (the
    # wrapper can crash at write-time on the relative_to bug; the cells survive).
    if args.from_cells:
        import glob
        cells = {"OFF": [], "ON": []}
        for rep in (1, 2):
            for arm in ("OFF", "ON"):
                fs = sorted(glob.glob(str(REPO / "data" / "eval_results"
                           / f"q9_prefloor_{arm}_*_rep{rep}.json")))
                if not fs:
                    log.error("missing cell: q9_prefloor_%s_*_rep%d.json", arm, rep)
                    return 2
                cells[arm].append(json.load(open(fs[0])))
        log.info("recovered %d OFF + %d ON cells from disk", len(cells["OFF"]), len(cells["ON"]))
    else:
        cells = {"OFF": [], "ON": []}
        for rep in range(1, args.reps + 1):
            for arm in ("OFF", "ON"):
                cell = run_cell(manifest_path, arm == "ON", args.queries, args.passes, rep)
                cells[arm].append(cell)

    def med(vals):
        vals = [v for v in vals if v is not None]
        return statistics.median(vals) if vals else None

    # Paired ratios per rep (the verdict): cold speedup = OFF_cold / ON_cold
    paired = {"cold_speedup_OFF_over_ON": [], "warm_ratio_ON_over_OFF": [],
              "load_delta_ON_minus_OFF_s": []}
    for rep in range(args.reps):
        oc = _cold_p50(cells["OFF"][rep])
        nc = _cold_p50(cells["ON"][rep])
        ow = _warm_p50(cells["OFF"][rep])
        nw = _warm_p50(cells["ON"][rep])
        ol = _load_secs(cells["OFF"][rep])
        nl = _load_secs(cells["ON"][rep])
        if oc and nc:
            paired["cold_speedup_OFF_over_ON"].append(round(oc / nc, 4))
        if ow and nw:
            paired["warm_ratio_ON_over_OFF"].append(round(nw / ow, 4))
        if ol is not None and nl is not None:
            paired["load_delta_ON_minus_OFF_s"].append(round(nl - ol, 2))

    cold_speedup = med(paired["cold_speedup_OFF_over_ON"])
    warm_ratio = med(paired["warm_ratio_ON_over_OFF"])
    load_delta = med(paired["load_delta_ON_minus_OFF_s"])
    anon_OFF = med([_anon_floor(c) for c in cells["OFF"]])
    anon_ON = med([_anon_floor(c) for c in cells["ON"]])
    anon_growth = (anon_ON - anon_OFF) if (anon_OFF is not None and anon_ON is not None) else None

    cold_ok = cold_speedup is not None and cold_speedup >= 1.15
    load_ok = load_delta is not None and load_delta <= 5.0
    warm_ok = warm_ratio is not None and warm_ratio <= 1.05
    zero_anon = anon_growth is not None and abs(anon_growth) < 0.05  # ~0 GB
    cells_valid = all(
        (_vmswap(c) is not None and (_vmswap(c) or 0) < 0.1
         and _warm_p50(c) is not None and _cold_p50(c) is not None
         and _warm_p50(c) < _cold_p50(c))
        for c in cells["ON"] + cells["OFF"])

    verdict = {
        "cold_speedup_OFF_over_ON_median": cold_speedup,
        "warm_p50_ratio_ON_over_OFF_median": warm_ratio,
        "load_time_delta_ON_minus_OFF_s_median": load_delta,
        "anon_floor_growth_GB": anon_growth,
        "bar_cold_1.15x_faster": "PASS" if cold_ok else "FAIL",
        "bar_load_le_5s": "PASS" if load_ok else "FAIL",
        "bar_warm_le_1.05x": "PASS" if warm_ok else "FAIL",
        "bar_zero_anon_growth": "PASS" if zero_anon else "FAIL",
        "cells_valid_novswap_warm_lt_cold": cells_valid,
        "overall": ("PASS" if (cold_ok and load_ok and warm_ok and zero_anon
                               and cells_valid) else "FAIL"),
        "note": ("Pre-registered bars (doc 12 §3 Q9): cold >= 1.15x faster with "
                 "prefault ON; load +<=5s; warm ratio <=1.05; zero anon growth. "
                 "ONCE-AT-LOAD, distinct from refuted per-query WILLNEED (doc 10 "
                 "Fix #3)."),
    }

    out = {
        "meta": {
            "date_utc": datetime.utcnow().isoformat(),
            "benchmark": "q9 startup floor prefault",
            "manifest": manifest,
            "queries": args.queries, "passes": args.passes, "reps": args.reps,
        },
        "bars": BARS,
        "cells": {arm: [{"_cell_file": c.get("_cell_file"),
                         "cold_p50_ms": _cold_p50(c), "warm_p50_ms": _warm_p50(c),
                         "load_seconds": _load_secs(c),
                         "vmswap_gb": _vmswap(c),
                         "anon_floor_gb": _anon_floor(c),
                         "wall_secs": c.get("_wall_secs")}
                        for c in cells[arm]] for arm in ("OFF", "ON")},
        "paired_ratios": paired,
        "verdict": verdict,
    }
    with open(result_file, "w") as f:
        json.dump(out, f, indent=2)
    log.info("result written to %s", result_file)
    log.info("VERDICT: %s", json.dumps(verdict, indent=2))
    return 0 if verdict["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
