#!/usr/bin/env python3
"""R2: fine convergence ladder — convergence-terminated capped cells with
kernel-level reclaim instrumentation (2026-07-14).

R1 follow-up (backlog §R2; docs/session_2026-07-14_f6_corrections_r1_ladder/
04_CONVERGENCE_ARTIFACT.md §5): a fixed 3-pass window truncates the transient
near the working-set boundary, so R2 runs passes until the majflt trajectory
converges, and snapshots the container's cgroup-v2 `memory.stat` between
passes — direct observation of the reclaim machinery (pgscan/pgsteal rate,
workingset_refault_file, active_file) doing the residue-vs-repeat-set sort.

Convergence rule (pre-registered in backlog §R2): after >= --min-passes,
CONVERGED when either
  (a) majflt_p <= --near-zero-majflt                          -> "near_zero"
  (b) |majflt_p - majflt_{p-1}| / majflt_{p-1} < --plateau-rel
      on two consecutive passes                               -> "plateau"
otherwise stops UNCONVERGED at --max-passes                   -> "maxpass".

This process does NOT cap itself — r2_host_orchestrator.sh wraps it in a
memory-capped sibling container and drops the shared WSL2 page cache before
each cell (without that, a prior cell's residency leaks into pass 1 and the
cell is invalid — pass-1 majflt sanity floor is checked by the verifier).

E7b/R1 lessons kept: pre-encoded queries (no torch/ORT in-cap), VmSwap>0 =>
swap-confounded flag, empty results => exit 3 never a latency record.

Usage (inside the capped sibling container, from repo root):
  .venv/bin/python3 scripts/seismic_testbed/r2_convergence_ladder.py \
      --cap-label 12g --result-file data/eval_results/r2_cap12g_20260714.json
"""
import argparse
import json
import logging
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("r2")

MANIFEST = "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"
ENCODED = "data/eval_results/e7b_encoded_queries.json"

CG = Path("/sys/fs/cgroup")
# monotonic counters -> recorded as per-pass deltas
CG_COUNTERS = ("pgfault", "pgmajfault", "pgscan", "pgsteal",
               "pgscan_kswapd", "pgscan_direct",
               "pgsteal_kswapd", "pgsteal_direct",
               "workingset_refault_file", "workingset_activate_file",
               "workingset_restore_file", "workingset_nodereclaim")
# gauges -> recorded as absolutes at pass end
CG_GAUGES = ("anon", "file", "file_mapped", "active_file", "inactive_file",
             "unevictable")
# global kernel counters (shared WSL2 kernel — host-noise caveat applies)
VMSTAT_KEYS = ("pgscan_kswapd", "pgscan_direct", "pgsteal_kswapd",
               "pgsteal_direct", "pgmajfault", "workingset_refault_file",
               "workingset_activate_file")


def read_majflt() -> int:
    return int(Path("/proc/self/stat").read_text().split()[11])


def read_vm() -> dict:
    out = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        for k in ("VmRSS", "VmSwap", "RssFile", "RssAnon"):
            if line.startswith(k + ":"):
                out[k.lower() + "_kb"] = int(line.split()[1])
    return out


def read_cgstat() -> dict:
    """This container's cgroup-v2 memory.stat (+ memory.current), or {}."""
    try:
        d = {}
        for line in (CG / "memory.stat").read_text().splitlines():
            k, _, v = line.partition(" ")
            d[k] = int(v)
        d["memory_current"] = int((CG / "memory.current").read_text())
        return d
    except (OSError, ValueError) as e:
        log.warning("cgroup memory.stat unreadable: %s", e)
        return {}


def read_vmstat() -> dict:
    try:
        d = {}
        for line in Path("/proc/vmstat").read_text().splitlines():
            k, _, v = line.partition(" ")
            if k in VMSTAT_KEYS:
                d[k] = int(v)
        return d
    except OSError:
        return {}


def deltas(now: dict, prev: dict, keys) -> dict:
    return {k: now[k] - prev[k] for k in keys if k in now and k in prev}


def pctl(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap-label", required=True,
                    help="external cap this cell runs under (e.g. 12g) — "
                         "recorded and cross-checked against memory.max")
    ap.add_argument("--min-passes", type=int, default=3)
    ap.add_argument("--max-passes", type=int, default=12)
    ap.add_argument("--near-zero-majflt", type=int, default=2500)
    ap.add_argument("--plateau-rel", type=float, default=0.10)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--result-file", required=True)
    args = ap.parse_args()

    try:
        memory_max = (CG / "memory.max").read_text().strip()
    except OSError:
        memory_max = "unreadable"
    log.info("R2 cell cap=%s (cgroup memory.max=%s): min %d / max %d passes, "
             "near-zero %d, plateau <%.0f%% x2", args.cap_label, memory_max,
             args.min_passes, args.max_passes, args.near_zero_majflt,
             args.plateau_rel * 100)

    from lib.thinclient.sharded_seismic_backend import HybridSeismicBackend

    terms = json.loads((REPO / ENCODED).read_text())["terms"][:args.queries]

    cg_preload = read_cgstat()
    t0 = time.perf_counter()
    sb = HybridSeismicBackend.from_manifest(str(REPO / MANIFEST),
                                            load_mode="mmap")
    load_s = time.perf_counter() - t0
    cg_postload = read_cgstat()
    cg_prev = cg_postload
    vmstat_prev = read_vmstat()
    log.info("loaded in %.1fs  vm=%s", load_s, read_vm())

    passes = []
    empty = 0
    converged_kind = "maxpass"
    plateau_streak = 0
    prev_majflt = None
    for p in range(args.max_passes):
        lat, mf0 = [], read_majflt()
        t_pass = time.perf_counter()
        for q in terms:
            t = time.perf_counter()
            res = sb.search_encoded(q, args.top_k)
            lat.append((time.perf_counter() - t) * 1000.0)
            if not res:
                empty += 1
        majflt = read_majflt() - mf0
        cg_now = read_cgstat()
        vmstat_now = read_vmstat()
        rec = {"pass": p + 1,
               "p50_ms": round(statistics.median(lat), 2),
               "p95_ms": round(pctl(lat, 95), 2),
               "mean_ms": round(statistics.mean(lat), 2),
               "max_ms": round(max(lat), 2),
               "majflt": majflt,
               "ms_per_fault": round(sum(lat) / majflt, 4) if majflt else None,
               "wall_s": round(time.perf_counter() - t_pass, 1),
               "vm": read_vm(),
               "cg_delta": deltas(cg_now, cg_prev, CG_COUNTERS),
               "cg_gauges": {k: cg_now[k] for k in CG_GAUGES if k in cg_now},
               "memory_current": cg_now.get("memory_current"),
               "vmstat_global_delta": deltas(vmstat_now, vmstat_prev,
                                             VMSTAT_KEYS)}
        passes.append(rec)
        cg_prev, vmstat_prev = cg_now, vmstat_now
        log.info("pass %d: p50 %.0f ms majflt %d (%.3f ms/flt) pgscan %s "
                 "ws_refault %s wall %.0fs", p + 1, rec["p50_ms"], majflt,
                 (sum(lat) / majflt) if majflt else 0.0,
                 rec["cg_delta"].get("pgscan", "n/a"),
                 rec["cg_delta"].get("workingset_refault_file", "n/a"),
                 rec["wall_s"])

        if prev_majflt is not None and prev_majflt > 0 and \
                abs(majflt - prev_majflt) / prev_majflt < args.plateau_rel:
            plateau_streak += 1
        else:
            plateau_streak = 0
        prev_majflt = majflt
        if p + 1 >= args.min_passes:
            if majflt <= args.near_zero_majflt:
                converged_kind = "near_zero"
                break
            if plateau_streak >= 2:
                converged_kind = "plateau"
                break

    if empty:
        log.error("%d empty results — serving path broken under this cap; "
                  "refusing to write a latency record (F6 lesson)", empty)
        sys.exit(3)

    final = passes[-1]
    swap_kb = max(p["vm"].get("vmswap_kb", 0) for p in passes)
    out = {"probe": "r2_convergence_ladder", "date": time.strftime("%Y-%m-%d"),
           "cap": args.cap_label, "cgroup_memory_max": memory_max,
           "manifest": MANIFEST, "queries": len(terms), "top_k": args.top_k,
           "load_s": round(load_s, 1),
           "prefault_gate": __import__("os").environ.get(
               "SFU_SEISMIC_PREFLOOR_HOTSET", "0"),
           "convergence": {
               "converged": converged_kind != "maxpass",
               "kind": converged_kind,
               "passes_to_converge": len(passes),
               "rule": {"min_passes": args.min_passes,
                        "max_passes": args.max_passes,
                        "near_zero_majflt": args.near_zero_majflt,
                        "plateau_rel": args.plateau_rel}},
           "converged_state": {"p50_ms": final["p50_ms"],
                               "p95_ms": final["p95_ms"],
                               "majflt": final["majflt"],
                               "ms_per_fault": final["ms_per_fault"]},
           "cg_load_delta": deltas(cg_postload, cg_preload, CG_COUNTERS),
           "cg_postload_gauges": {k: cg_postload[k] for k in CG_GAUGES
                                  if k in cg_postload},
           "per_pass": passes,
           "swap_confounded": swap_kb > 0,
           "vmswap_kb_max": swap_kb}
    Path(args.result_file).write_text(json.dumps(out, indent=2))
    log.info("wrote %s  converged=%s(%s) in %d passes  final p50 %.0f ms%s",
             args.result_file, out["convergence"]["converged"],
             converged_kind, len(passes), final["p50_ms"],
             "  ** SWAP-CONFOUNDED **" if swap_kb else "")


if __name__ == "__main__":
    main()
