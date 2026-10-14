#!/usr/bin/env python3
"""Tier-2/3: convergence ladder cell on the native-Linux OCI serve box
(PREREGISTRATION_TIER23.md phase A; publication-gate items 2-3).

Adapted from r2_convergence_ladder.py (judged R2 driver, untouched) with the
native-host differences:
  * the cell is capped by a systemd-run scope, not a docker sibling, so the
    cgroup-v2 dir is resolved from /proc/self/cgroup instead of assuming the
    namespace root /sys/fs/cgroup;
  * the kernel arm is recorded AND verified: --arm classic requires
    /sys/kernel/mm/lru_gen/enabled == 0x0000, --arm mglru requires nonzero.
    Mismatch exits 4 before touching the index (a mis-toggled cell must not
    produce a plausible-looking record);
  * uname + lru_gen state land in the result JSON.

Convergence rule, counters, and the F6 empty-result refusal are byte-for-byte
the R2 semantics (min/max passes, near-zero OR plateau x2).

Usage (as root inside the capped scope, repo root = /mnt/idxvol):
  systemd-run --scope -p MemoryMax=12G -- timeout 6000 \
      /mnt/idxvol/.venv/bin/python3 \
      scripts/seismic_testbed/t23_convergence_ladder.py --arm mglru \
      --cap-label 12g --result-file data/eval_results/t23a_mglru_cap12g.json
"""
import argparse
import errno
import json
import logging
import os
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("t23")

MANIFEST = "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"
ENCODED = "data/eval_results/e7b_encoded_queries.json"
LRU_GEN = Path("/sys/kernel/mm/lru_gen/enabled")

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


def own_cgroup_dir() -> Path:
    """The cgroup-v2 dir this process is charged to (native host, no ns)."""
    line = Path("/proc/self/cgroup").read_text().strip()
    # cgroup v2: single line "0::/system.slice/run-uNNN.scope"
    rel = line.split("::", 1)[1] if "::" in line else "/"
    return Path("/sys/fs/cgroup") / rel.lstrip("/")


CG = own_cgroup_dir()


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
    """This scope's cgroup-v2 memory.stat (+ memory.current), or {}."""
    try:
        d = {}
        for line in (CG / "memory.stat").read_text().splitlines():
            k, _, v = line.partition(" ")
            d[k] = int(v)
        d["memory_current"] = int((CG / "memory.current").read_text())
        return d
    except (OSError, ValueError) as e:
        log.warning("cgroup memory.stat unreadable at %s: %s", CG, e)
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


def postload_reclaim(nbytes: int) -> dict:
    """L3 one-shot nudge: write nbytes to this scope's memory.reclaim.

    spike/archive/smallmachine_levers/PREREGISTRATION.md §2 L3 / §5 gap 1. A short write
    or EAGAIN/EBUSY is memory.reclaim's normal way of saying the kernel could
    not free the whole request — that is data, not a failure, so it is
    recorded in write_status and never raised.
    """
    pre = read_cgstat()
    payload = str(nbytes).encode()
    t0 = time.perf_counter()
    try:
        fd = os.open(str(CG / "memory.reclaim"), os.O_WRONLY)
        try:
            n = os.write(fd, payload)
        finally:
            os.close(fd)
        status = "ok" if n == len(payload) else \
            "short_write:%d/%d" % (n, len(payload))
    except OSError as e:
        status = "%s: %s" % (errno.errorcode.get(e.errno, e.errno), e.strerror)
    except Exception as e:
        status = "%s: %s" % (type(e).__name__, e)
    elapsed = time.perf_counter() - t0
    post = read_cgstat()
    return {"requested_bytes": nbytes,
            "freed_bytes": (pre["memory_current"] - post["memory_current"])
            if "memory_current" in pre and "memory_current" in post else None,
            "write_status": status,
            "pre_gauges": {k: pre[k] for k in CG_GAUGES if k in pre},
            "post_gauges": {k: post[k] for k in CG_GAUGES if k in post},
            "elapsed_s": round(elapsed, 3)}


def deltas(now: dict, prev: dict, keys) -> dict:
    return {k: now[k] - prev[k] for k in keys if k in now and k in prev}


def pctl(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=("mglru", "classic"),
                    help="kernel arm; verified against lru_gen/enabled")
    ap.add_argument("--cap-label", required=True,
                    help="external cap this cell runs under (e.g. 12g) — "
                         "recorded and cross-checked against memory.max")
    ap.add_argument("--min-passes", type=int, default=3)
    ap.add_argument("--max-passes", type=int, default=12)
    ap.add_argument("--near-zero-majflt", type=int, default=2500)
    ap.add_argument("--plateau-rel", type=float, default=0.10)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--postload-reclaim-bytes", type=int, default=0,
                    help="L3 lever: bytes written to the scope's "
                         "memory.reclaim after load, before pass 1 "
                         "(0 = lever off, no JSON key emitted)")
    ap.add_argument("--result-file", required=True)
    ap.add_argument("--phase", default="A", choices=("A", "B"))
    args = ap.parse_args()

    try:
        lru_gen = LRU_GEN.read_text().strip()
    except OSError:
        lru_gen = "absent"
    mglru_on = lru_gen not in ("absent", "") and int(lru_gen, 0) != 0
    if args.arm == "mglru" and not mglru_on or \
            args.arm == "classic" and mglru_on:
        log.error("arm=%s but lru_gen/enabled=%s — toggle mismatch, "
                  "refusing to run the cell", args.arm, lru_gen)
        sys.exit(4)

    try:
        memory_max = (CG / "memory.max").read_text().strip()
    except OSError:
        memory_max = "unreadable"
    log.info("T23 cell arm=%s lru_gen=%s cap=%s (cgroup=%s memory.max=%s): "
             "min %d / max %d passes, near-zero %d, plateau <%.0f%% x2, "
             "postload_reclaim_bytes=%d",
             args.arm, lru_gen, args.cap_label, CG, memory_max,
             args.min_passes, args.max_passes, args.near_zero_majflt,
             args.plateau_rel * 100, args.postload_reclaim_bytes)

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

    reclaim = None
    if args.postload_reclaim_bytes:
        reclaim = postload_reclaim(args.postload_reclaim_bytes)
        log.info("postload reclaim: requested %d freed %s status=%s (%.2fs)",
                 reclaim["requested_bytes"], reclaim["freed_bytes"],
                 reclaim["write_status"], reclaim["elapsed_s"])
        # Rebaseline so pass-1 deltas are query-only: the reclaim step's own
        # scan/steal activity is deliberately excluded from pass 1 (its
        # residency effect is captured in reclaim pre/post_gauges).
        cg_prev = read_cgstat()
        vmstat_prev = read_vmstat()

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
    out = {"probe": "t23_convergence_ladder", "phase": args.phase,
           "date": time.strftime("%Y-%m-%d"),
           "arm": args.arm, "lru_gen_enabled": lru_gen,
           "uname": " ".join(os.uname()),
           "cap": args.cap_label, "cgroup_memory_max": memory_max,
           "cgroup_dir": str(CG),
           "manifest": MANIFEST, "queries": len(terms), "top_k": args.top_k,
           "load_s": round(load_s, 1),
           "prefault_gate": os.environ.get("SFU_SEISMIC_PREFLOOR_HOTSET", "0"),
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
    if reclaim is not None:
        out["postload_reclaim"] = reclaim
    Path(args.result_file).write_text(json.dumps(out, indent=2))
    log.info("wrote %s  converged=%s(%s) in %d passes  final p50 %.0f ms%s",
             args.result_file, out["convergence"]["converged"],
             converged_kind, len(passes), final["p50_ms"],
             "  ** SWAP-CONFOUNDED **" if swap_kb else "")


if __name__ == "__main__":
    main()
