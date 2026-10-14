#!/usr/bin/env python3
"""R3 instrument 6 (2026-07-16; doc 15 §5/§2): the convergence-terminated
capped-cell driver for the kernel-ledger spike. EXTENDS r2_convergence_ladder.py
with the single thing R3 adds at the driver layer:

  1. pass-boundary CLOCK_MONOTONIC ns timestamps in the result JSON, so the
     join (r3_join_analysis.py) can slice the bpftrace ledger (instrument 1)
     and refault stream (instrument 3) by pass — which extents were
     evicted/faulted-back in pass k, attributing to that pass's queries.
  2. an optional --cachestat-between-passes flag that snaps r3_cachestat_map
     (instrument 4) between every pass, writing _r3_cachestat_<label>_<pass>.json
     (the "kernel still sorting" residue maps of 04-doc §2 / doc 15 §1 #3).

Convergence rules, served shape, pre-encoded queries, swap/empty discipline,
cgroup/vmstat instrumentation, and the result-JSON schema are UNCHANGED from
R2 (inherited wholesale) — R3 only ADDS timestamps + the between-pass map
hook. The uninstrumented CONTROL cells run this same driver WITHOUT a tracer
attached (and optionally --cachestat off for parity); the instrumented cells
run it with the host orchestrator's --pid=host bpftrace container attached.
Latency is ONLY ever quoted from control cells (doc 15 §4).

Usage (inside the capped sibling container, from repo root):
  # control cell:
  .venv/bin/python3 scripts/seismic_testbed/r3_kernel_ledger_driver.py \
      --cap-label 12g --result-file data/eval_results/r3_cap12g_ctrl_20260716.json
  # instrumented cell (cachestat between passes):
  .venv/bin/python3 scripts/seismic_testbed/r3_kernel_ledger_driver.py \
      --cap-label 12g --result-file data/eval_results/r3_cap12g_instr_20260716.json \
      --cachestat-between-passes --cell-label 12g_instr
"""
import argparse
import json
import logging
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("r3")

MANIFEST = "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"
ENCODED = "data/eval_results/e7b_encoded_queries.json"

CG = Path("/sys/fs/cgroup")
CG_COUNTERS = ("pgfault", "pgmajfault", "pgscan", "pgsteal",
               "pgscan_kswapd", "pgscan_direct",
               "pgsteal_kswapd", "pgsteal_direct",
               "workingset_refault_file", "workingset_activate_file",
               "workingset_restore_file", "workingset_nodereclaim")
CG_GAUGES = ("anon", "file", "file_mapped", "active_file", "inactive_file",
             "unevictable")
VMSTAT_KEYS = ("pgscan_kswapd", "pgscan_direct", "pgsteal_kswapd",
               "pgsteal_direct", "pgmajfault", "workingset_refault_file",
               "workingset_activate_file")


def clock_ns() -> int:
    """CLOCK_MONOTONIC ns — the join's ledger-slice key. (time.monotonic_ns()
    is CLOCK_MONOTONIC on Linux; matches bpftrace's nsecs base enough for
    pass-window slicing — both are boot-relative monotonic ns.)"""
    return time.monotonic_ns()


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


def deltas(now, prev, keys):
    return {k: now[k] - prev[k] for k in keys if k in now and k in prev}


def pctl(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def snap_cachestat(label: str, pass_idx: int):
    """Invoke instrument 4 between passes — the residue map. Best-effort:
    failures (cgroup/permission noise) are logged, NOT fatal (the cell still
    completes; the join falls back to the ledger's ADD/DEL stream)."""
    try:
        subprocess.run(
            [str(REPO / ".venv/bin/python3"),
             "scripts/seismic_testbed/r3_cachestat_map.py",
             "--label", f"{label}_pass{pass_idx}", "--mode", "auto"],
            cwd=str(REPO), check=False, timeout=120,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        log.info("  cachestat map pass %d snapped", pass_idx)
    except subprocess.TimeoutExpired:
        log.warning("  cachestat map pass %d timed out (skipped)", pass_idx)
    except Exception as e:
        log.warning("  cachestat map pass %d failed: %s", pass_idx, e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap-label", required=True,
                    help="external cap this cell runs under (e.g. 12g)")
    ap.add_argument("--cell-label", default=None,
                    help="label for between-pass artifacts; defaults to "
                         "<cap-label>_<mode> derived from --result-file stem")
    ap.add_argument("--min-passes", type=int, default=3)
    ap.add_argument("--max-passes", type=int, default=12)
    ap.add_argument("--near-zero-majflt", type=int, default=2500)
    ap.add_argument("--plateau-rel", type=float, default=0.10)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--result-file", required=True)
    ap.add_argument("--cachestat-between-passes", action="store_true",
                    help="snap r3_cachestat_map between every pass (the "
                         "residue map). Slow; off for control cells.")
    args = ap.parse_args()

    # derive cell label from result-file stem if not given (e.g.
    # r3_cap12g_instr_20260716.json → 12g_instr)
    cell_label = args.cell_label
    if not cell_label:
        stem = Path(args.result_file).stem   # r3_cap12g_instr_20260716
        body = stem[stem.startswith("r3_") and 3 or 0:]  # cap12g_instr_20260716
        cell_label = body.rsplit("_20", 1)[0] if "_20" in body else body

    try:
        memory_max = (CG / "memory.max").read_text().strip()
    except OSError:
        memory_max = "unreadable"
    log.info("R3 cell cap=%s label=%s (cgroup memory.max=%s): min %d / max %d "
             "passes, near-zero %d, plateau <%.0f%% x2, cachestat-between=%s",
             args.cap_label, cell_label, memory_max, args.min_passes,
             args.max_passes, args.near_zero_majflt, args.plateau_rel * 100,
             args.cachestat_between_passes)

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
    # pass-0 boundary = post-load, pre-pass-1 — the slice start for pass 1
    pass_boundaries = [clock_ns()]
    log.info("loaded in %.1fs  vm=%s  pass0_boundary_ns=%d", load_s,
             read_vm(), pass_boundaries[0])
    if args.cachestat_between_passes:
        snap_cachestat(cell_label, 0)   # residue map right after load

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
        # pass-(p+1) boundary = end-of-pass CLOCK_MONOTONIC ns
        pass_end_ns = clock_ns()
        majflt = read_majflt() - mf0
        cg_now = read_cgstat()
        vmstat_now = read_vmstat()
        rec = {"pass": p + 1,
               "pass_start_ns": pass_boundaries[-1],
               "pass_end_ns": pass_end_ns,
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
               "vmstat_global_delta": deltas(vmstat_now, vmstat_prev, VMSTAT_KEYS)}
        passes.append(rec)
        pass_boundaries.append(pass_end_ns)
        cg_prev, vmstat_prev = cg_now, vmstat_now
        log.info("pass %d: p50 %.0f ms majflt %d (%.3f ms/flt) pgscan %s "
                 "ws_refault %s wall %.0fs  [%d→%d ns]", p + 1, rec["p50_ms"],
                 majflt, (sum(lat) / majflt) if majflt else 0.0,
                 rec["cg_delta"].get("pgscan", "n/a"),
                 rec["cg_delta"].get("workingset_refault_file", "n/a"),
                 rec["wall_s"], rec["pass_start_ns"], rec["pass_end_ns"])
        if args.cachestat_between_passes and p + 1 < args.max_passes:
            snap_cachestat(cell_label, p + 1)   # residue map at pass boundary

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
    out = {"probe": "r3_kernel_ledger_driver",
           "date": time.strftime("%Y-%m-%d"),
           "cap": args.cap_label, "cell_label": cell_label,
           "cgroup_memory_max": memory_max,
           "manifest": MANIFEST, "queries": len(terms), "top_k": args.top_k,
           "load_s": round(load_s, 1),
           "prefault_gate": __import__("os").environ.get(
               "SFU_SEISMIC_PREFLOOR_HOTSET", "0"),
           "cachestat_between_passes": args.cachestat_between_passes,
           # pass_boundaries[i] = boundary BEFORE pass i+1; the LAST entry is
           # post-final-pass. The join slices ledger ns into
           # [boundaries[i], boundaries[i+1]) = pass i+1's window.
           "pass_boundaries_ns": pass_boundaries,
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
