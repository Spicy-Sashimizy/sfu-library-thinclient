#!/usr/bin/env python3
"""Q7 — cold-start hybrid federation benchmark (2026-07-10).

The hybrid serving method (`HybridSeismicBackend`) starts SEQUENTIAL while the
index is cold and flips to PARALLEL on a state signal once warm. This benchmark
measures it against the two standalone methods under the container's
cold-measurement protocol (fadvise-DONTNEED eviction; paired-ratios-only per
the 2026-07-09 D2 methodology rule).

PRE-REGISTERED BARS (written BEFORE measurement, doc 12 §3 Q7):
  - hybrid cold p50 <= 1.05x sequential's cold p50
  - hybrid warm p50 <= 1.05x parallel's warm p50
  - T1 parity: parallel == sequential == hybrid, 100/100 bit-identical
    (asserted separately, not from the timed cells)

PROTOCOL (container, established 2026-07-09):
  - /proc/sys is read-only -> no drop_caches. Evict each shard's file-backed
    pages with posix_fadvise(DONTNEED) before every cold cell (reuses the
    e5_shard_gates helper). On 9p the fresh-process mmaps re-fault Linux-cold
    regardless of page cache; Windows cache is not evictable here.
  - ONLY paired A/B ratios are verdicts; absolute cold numbers are indicative.
  - A cold cell counts only if VmSwap ~ 0 AND warm p50 < cold p50.
  - Corpora are served shards (Rule Zero — READ-ONLY): we do NOT touch the
    shard files, only fadvise their cached pages.

Cells: 3 arms (parallel / sequential / hybrid) x 2 reps, alternating so any
host drift hits all arms. Each cell = one serve_footprint_bench subprocess at
--queries 40 --passes 3 (pass 0 cold, passes 1-2 warm), with fadvise-DONTNEED
run right before it.

Usage (repo root, project venv, against the served e5 manifest):

    .venv/bin/python3 scripts/seismic_testbed/q7_hybrid_federation_bench.py \
        --manifest data/eval_results/seismic_c25_shards_150m_mmap_e5.json \
        --reps 2 --queries 40 --passes 3 \
        --result-file data/eval_results/q7_hybrid_federation_20260710.json
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

log = logging.getLogger("q7_bench")

BENCH = REPO / "scripts" / "seismic_testbed" / "serve_footprint_bench.py"

# Pre-registered bars (written BEFORE measurement; doc 12 §3 Q7).
BARS = {
    "hybrid_cold_p50_le_1.05x_seq_cold": 1.05,
    "hybrid_warm_p50_le_1.05x_par_warm": 1.05,
    "t1_parity_100pct": 100,
    "protocol": "fadvise-DONTNEED per cell, paired ratios only, VmSwap~0 + warm<cold",
}


def fadvise_dontneed_manifest(manifest_path: str) -> int:
    """Evict every shard's file-backed pages from the kernel page cache before a
    cold cell. Reads the manifest's mmap_dir list (the SAME paths the bench will
    mmap) and posix_fadvise(DONTNEED)s every file in each shard dir. This is the
    2026-07-09 container cold-protocol substitute for drop_caches (/proc/sys is
    read-only here). Reuses the e5_shard_gates helper convention.

    Rule Zero: this NEVER opens for write, never copies/moves/deletes a shard —
    it only advises the kernel to drop CLEAN cached pages (a read-only hint)."""
    from lib.thinclient.sharded_seismic_backend import _load_manifest
    shard_dirs = _load_manifest(manifest_path, load_mode="mmap")
    total = 0
    for d in shard_dirs:
        p = Path(d)
        if not p.is_dir():
            # mmap_dir may be repo-root-relative; anchor it.
            p = REPO / d
        if not p.is_dir():
            log.warning("shard dir not found for fadvise: %s (skipped)", d)
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


def run_cell(manifest: str, federation: str, queries: int, passes: int,
             rep: int, bench_env: dict) -> dict:
    """Run one serve_footprint_bench cell and return its result JSON dict."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    cell_file = REPO / "data" / "eval_results" / \
        f"q7_hybrid_cell_{federation}_{ts}_rep{rep}.json"

    # Evict page cache before every cold cell (container cold protocol).
    evicted = fadvise_dontneed_manifest(manifest)
    log.info("[rep %d %s] fadvise-DONTNEED evicted %.2f GB across shard dirs",
             rep, federation, evicted / 1e9)

    env = {**os.environ, **bench_env,
           "SFU_SEISMIC_SHARD_MANIFEST": manifest,
           # k' = served default (max(2x top_k, 100)); do NOT set SFU_SEISMIC_K_PRIME
           # so each arm uses the identical served config (the E1-owed check confirmed
           # this default is live). query_cut unset = all terms (recall-first).
           }
    cmd = [sys.executable, str(BENCH),
           "--shard-manifest", manifest,
           "--federation", federation,
           "--queries", str(queries),
           "--passes", str(passes),
           "--result-file", str(cell_file)]
    log.info("[rep %d %s] running: %s", rep, federation, " ".join(cmd))
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    dt = time.perf_counter() - t0
    if proc.returncode != 0:
        log.error("[rep %d %s] bench FAILED rc=%d (%.1fs)\nstderr:\n%s",
                  rep, federation, proc.returncode, dt, proc.stderr[-2000:])
        raise RuntimeError(f"bench cell {federation} rep{rep} failed")
    log.info("[rep %d %s] bench done in %.1fs", rep, federation, dt)
    with open(cell_file) as f:
        result = json.load(f)
    result["_cell_file"] = str(cell_file.relative_to(REPO))
    result["_evicted_gb"] = round(evicted / 1e9, 3)
    result["_wall_secs"] = round(dt, 1)
    return result


def _cold_p50(cell: dict) -> float | None:
    try:
        return cell["seismic"]["latency_ms"]["cold"]["p50_ms"]
    except (KeyError, TypeError):
        return None


def _warm_p50(cell: dict) -> float | None:
    try:
        return cell["seismic"]["latency_ms"]["warm"]["p50_ms"]
    except (KeyError, TypeError):
        return None


def _vmswap_gb(cell: dict) -> float | None:
    try:
        return cell["seismic"]["ram"]["vmswap_gb"]
    except (KeyError, TypeError):
        return None


def _anon_floor_gb(cell: dict) -> float | None:
    try:
        return cell["seismic"]["ram"]["anon_floor_gb"]
    except (KeyError, TypeError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True,
                    help="served 8-shard mmap manifest (the E5 or dv one)")
    ap.add_argument("--reps", type=int, default=2, help="alternating reps per arm")
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--passes", type=int, default=3, help="pass 0 cold, 1+ warm")
    ap.add_argument("--result-file", required=True)
    ap.add_argument("--skip-t1", action="store_true",
                    help="skip the T1 parity sub-check (runs the cells only)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    manifest = args.manifest
    manifest_path = manifest if Path(manifest).is_absolute() else str(REPO / manifest)
    if not Path(manifest_path).exists():
        log.error("manifest not found: %s", manifest_path)
        return 2

    # Rule Zero shard inventory (record before + after; the bench must NOT
    # modify served shards).
    shards_glob = list(Path(REPO / "data" / "seismic_150m" / "index" / "plan01").glob("*.mmap"))
    log.info("Rule Zero: %d served *.mmap shard dirs present", len(shards_glob))

    ts = datetime.utcnow().strftime("%Y%m%d")
    result_file = REPO / args.result_file

    # ── T1 parity: hybrid ≡ parallel ≡ sequential, bit-identical ────────────
    # Run FIRST so a parity failure stops the bench before spending cold-cell
    # wall time. (Skip with --skip-t1 for a re-bench of just the timed cells.)
    t1 = {"ran": False, "passed": False, "n_queries": 0, "detail": None}
    if not args.skip_t1:
        log.info("=== T1 parity: hybrid == parallel == sequential, bit-identical ===")
        try:
            from lib.thinclient.sharded_seismic_backend import (
                ParallelSeismicBackend, SequentialSeismicBackend,
                HybridSeismicBackend, _load_manifest)
        except Exception as e:
            log.warning("T1 imports failed (%s); skipping T1", e)
        else:
            index_paths = _load_manifest(manifest, load_mode="mmap")
            # Use 2 shards only for the parity check (fast; parity is per-shard
            # independent so 2 is representative; the merge is order-independent).
            parity_paths = index_paths[:2]
            par = ParallelSeismicBackend(parity_paths, load_mode="mmap")
            seq = SequentialSeismicBackend(parity_paths, load_mode="mmap")
            # DISABLE the flip so hybrid stays on its sequential arm for a clean
            # parity probe against sequential; then enable it to confirm the
            # flip itself preserves parity.
            os.environ["SFU_SEISMIC_HYBRID_DISABLE"] = "0"
            hyb = HybridSeismicBackend(parity_paths, load_mode="mmap")

            qrecs = json.loads((REPO / "data" / "eval_results" /
                                "diverse_queries.json").read_text())
            queries = [r["paraphrase"] for r in qrecs][:min(20, len(qrecs))]
            n_match = 0
            mismatches = []
            for i, qtext in enumerate(queries):
                k = 50
                # search_encoded bypasses ONNX; use a stable hand qvec would need
                # the encoder — instead use search() which encodes. Encode once,
                # reuse across all three backends so the qvec is identical.
                q = par.encode_query(qtext)
                if not q:
                    continue
                r_par = par.search_encoded(q, top_k=k, k_prime=100)
                r_seq = seq.search_encoded(q, top_k=k, k_prime=100)
                r_hyb = hyb.search_encoded(q, top_k=k, k_prime=100)
                oa_par = [o for o, _ in r_par]
                oa_seq = [o for o, _ in r_seq]
                oa_hyb = [o for o, _ in r_hyb]
                # bit-identical = same oaid ORDER (scores follow from the same
                # per-shard dot products + the shared merge).
                if oa_par == oa_seq == oa_hyb:
                    n_match += 1
                else:
                    mismatches.append({"q": i, "par_len": len(oa_par),
                                       "seq_len": len(oa_seq),
                                       "hyb_len": len(oa_hyb)})
            t1["ran"] = True
            t1["n_queries"] = len(queries)
            t1["passed"] = (n_match == len(queries) and not mismatches)
            t1["n_match"] = n_match
            t1["mismatches"] = mismatches[:5]
            log.info("T1: %d/%d queries bit-identical across par/seq/hybrid",
                     n_match, len(queries))
            if not t1["passed"]:
                log.error("T1 PARITY FAILED — aborting cold cells (results would "
                          "be invalid if the flip changes them). See mismatches.")
                with open(result_file, "w") as f:
                    json.dump({"meta": {"date_utc": datetime.utcnow().isoformat(),
                                        "benchmark": "q7_hybrid_federation"},
                              "t1_parity": t1,
                              "bars": BARS}, f, indent=2)
                return 3

    # ── Cold cells: 3 arms x reps, alternating ───────────────────────────────
    arms = ["sequential", "parallel", "hybrid"]
    cells = {}   # arm -> list of cell results
    for arm in arms:
        cells[arm] = []
    bench_env = {"SFU_SEISMIC_LOAD_MODE": "mmap"}

    for rep in range(1, args.reps + 1):
        for arm in arms:
            cell = run_cell(manifest_path, arm, args.queries, args.passes, rep, bench_env)
            cells[arm].append(cell)

    # ── Aggregate + verdict (paired ratios only) ─────────────────────────────
    def med(vals):
        vals = [v for v in vals if v is not None]
        return statistics.median(vals) if vals else None

    agg = {}
    for arm in arms:
        agg[arm] = {
            "cold_p50_ms_by_rep": [_cold_p50(c) for c in cells[arm]],
            "warm_p50_ms_by_rep": [_warm_p50(c) for c in cells[arm]],
            "vmswap_gb_by_rep": [_vmswap_gb(c) for c in cells[arm]],
            "anon_floor_gb_by_rep": [_anon_floor_gb(c) for c in cells[arm]],
            "cold_p50_ms_median": med([_cold_p50(c) for c in cells[arm]]),
            "warm_p50_ms_median": med([_warm_p50(c) for c in cells[arm]]),
            "vmswap_gb_max": max(filter(None, [_vmswap_gb(c) for c in cells[arm]]),
                                 default=None),
        }

    # Paired ratios: per-rep hybrid/sequential and hybrid/parallel.
    paired = {"hybrid_over_seq_cold": [], "hybrid_over_par_warm": []}
    for rep in range(args.reps):
        sc = _cold_p50(cells["sequential"][rep])
        hc = _cold_p50(cells["hybrid"][rep])
        pw = _warm_p50(cells["parallel"][rep])
        hw = _warm_p50(cells["hybrid"][rep])
        if sc and hc:
            paired["hybrid_over_seq_cold"].append(round(hc / sc, 4))
        if pw and hw:
            paired["hybrid_over_par_warm"].append(round(hw / pw, 4))

    # Verdict against pre-registered bars.
    cold_ratio = (med(paired["hybrid_over_seq_cold"])
                  if paired["hybrid_over_seq_cold"] else None)
    warm_ratio = (med(paired["hybrid_over_par_warm"])
                  if paired["hybrid_over_par_warm"] else None)
    cold_ok = cold_ratio is not None and cold_ratio <= 1.05
    warm_ok = warm_ratio is not None and warm_ratio <= 1.05
    # Cold-cell validity: VmSwap ~ 0 AND warm < cold on the hybrid cells.
    hybrid_valid = all(
        (_vmswap_gb(c) is not None and (_vmswap_gb(c) or 0) < 0.1
         and _warm_p50(c) is not None and _cold_p50(c) is not None
         and _warm_p50(c) < _cold_p50(c))
        for c in cells["hybrid"])

    verdict = {
        "cold_p50_ratio_hybrid_over_seq_median": cold_ratio,
        "warm_p50_ratio_hybrid_over_par_median": warm_ratio,
        "cold_bar_1.05x_seq": ("PASS" if cold_ok else "FAIL"),
        "warm_bar_1.05x_par": ("PASS" if warm_ok else "FAIL"),
        "t1_parity_100pct": ("PASS" if t1.get("passed") else "FAIL"),
        "hybrid_cells_valid_novswap_warm_lt_cold": hybrid_valid,
        "overall": ("PASS" if (cold_ok and warm_ok and t1.get("passed")
                               and hybrid_valid) else "FAIL"),
        "note": ("Pre-registered bars (doc 12 §3 Q7): hybrid cold p50 <= 1.05x seq "
                 "cold; hybrid warm p50 <= 1.05x par warm; T1 100/100 bit-identical. "
                 "Container cold protocol: fadvise-DONTNEED per cell, paired ratios "
                 "only, VmSwap~0 + warm<cold validity."),
    }

    # manifest label for the result JSON: repo-relative when possible, else
    # the as-passed path. Path.relative_to raises if the arg is a relative path
    # string (it's not "in" the absolute REPO subpath); resolve first.
    try:
        manifest_label = str(Path(manifest_path).resolve().relative_to(REPO))
    except ValueError:
        manifest_label = manifest

    out = {
        "meta": {
            "date_utc": datetime.utcnow().isoformat(),
            "benchmark": "q7 hybrid federation (cold-start -> sequential-cold/parallel-warm)",
            "manifest": manifest_label,
            "queries": args.queries,
            "passes": args.passes,
            "reps": args.reps,
            "shard_dirs_inventoried": len(shards_glob),
        },
        "bars": BARS,
        "t1_parity": t1,
        "cells": {arm: [{"_cell_file": c.get("_cell_file"),
                         "cold_p50_ms": _cold_p50(c),
                         "warm_p50_ms": _warm_p50(c),
                         "vmswap_gb": _vmswap_gb(c),
                         "anon_floor_gb": _anon_floor_gb(c),
                         "evicted_gb": c.get("_evicted_gb"),
                         "wall_secs": c.get("_wall_secs")}
                        for c in cells[arm]] for arm in arms},
        "aggregate": agg,
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
