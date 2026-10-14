#!/usr/bin/env python3
"""The ordinals residency cliff — filter stage under a page-cache ladder.

Pre-registration: `docs/ORDINALS_RESIDENCY_CLIFF.md` (written BEFORE this ran).
The open question is doc `seismic_150m_testbed/18_ORDINAL_ADDRESSING_DESIGN.md`
§14 "not settled" #5: staged SQLite's 4.0 ms filter stage assumes the hot B-tree
pages stay cached; what happens to it as available page cache shrinks, and does
the ordinal path's 1.5 ms hold while it degrades?

**How the cap is applied on THIS host.** `spike/convergence_repro/` applies its
caps with `docker run --memory=X` (HOST_RUN.md: the dev container "has no usable
docker daemon, /sys/fs/cgroup is read-only, and no memory cap can be enforced
there"). Re-verified 2026-09-25 inside this container: no `docker` binary,
`/sys/fs/cgroup` mounted `ro`, `CapEff` has no CAP_SYS_ADMIN even under sudo, no
`systemd-run`, no `vmtouch`, no `fio`. Since the cloud hosts are gone there is
nowhere else to run it, so the cap is applied the only way left: an **mlock'd
anonymous balloon** in a child process shrinks the page cache the benchmark can
use, and each rung records the page cache actually available
(`MemAvailable`) rather than trusting the arithmetic. The cell protocol
(preflight → record → evict-and-verify → load → timed passes, majflt per pass)
is kept from `spike/convergence_repro/cell.sh`; the enforcement mechanism is
what differs, and that difference is stated in the results.

Per-file eviction replaces `vmtouch -e` with `posix_fadvise(POSIX_FADV_DONTNEED)`
and residency is verified with `mincore(2)`; global `drop_caches` is never used
(it is not writable here and would evict other tenants' pages anyway).

Arms, both served off LOCAL disk (`/var/tmp`, overlay) so the addressing scheme
is the only difference — doc 18 §14's whole lesson is that measuring ordinals
against SQLite-on-9p misattributes a filesystem win:

    sqlite    retriever._post_filter with _ordinals=None, staged meta.sqlite
    ordinals  retriever._post_filter with _ordinals=OrdinalSpace(staged arrays)

Both run the SHIPPED `_post_filter`, including the ordinal arm's SQLite fallback
for ids with no ordinal. Parity is the gate: the two arms must return identical
kept lists on every query, in every rung, or the numbers mean nothing.
"""
from __future__ import annotations

import argparse
import ctypes
import gc
import json
import mmap
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

GIB = 1 << 30
FILTERS = {"year_range": (2010, 2025), "type": "article"}
_ARRAY_FILES = ("wids.npy", "year.npy", "dtype.npy", "is_oa.npy",
                "section.npy", "ordinal_space.json")

BALLOON_SRC = """
# CLIFF_BALLOON — the quiet-host gate must not count this as another benchmark
import ctypes, mmap, os, signal, sys
n = int(sys.argv[1])
buf = mmap.mmap(-1, n, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS)
libc = ctypes.CDLL("libc.so.6", use_errno=True)
addr = ctypes.addressof(ctypes.c_char.from_buffer(buf))
rc = libc.mlock(ctypes.c_void_p(addr), ctypes.c_size_t(n))
if rc != 0:
    step = 4096
    for off in range(0, n, step):
        buf[off] = 1
print("READY rc=%d pid=%d" % (rc, os.getpid()), flush=True)
signal.pause()
"""


def loadavg() -> dict:
    a, b, c, procs, _ = Path("/proc/loadavg").read_text().split()
    return {"load1": float(a), "load5": float(b), "load15": float(c),
            "running": procs, "t": time.strftime("%Y-%m-%dT%H:%M:%S")}


def other_benchmarks() -> list[str]:
    me = os.getpid()
    out = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit() or int(d.name) == me:
            continue
        try:
            cmd = (d / "cmdline").read_bytes().replace(b"\x00", b" ").decode()
        except OSError:
            continue
        if "python" not in cmd or "claude" in cmd.lower():
            continue
        if any(x in cmd for x in ("supervisord", "eval_ordinals_cliff",
                                  "CLIFF_BALLOON")):
            continue
        out.append(cmd.strip()[:160])
    return out


def wait_quiet(max_load1: float, timeout_s: float) -> dict:
    """Quiet-host gate, applied before EVERY cell: a cell timed against another
    agent's benchmark measures that benchmark."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        la, others = loadavg(), other_benchmarks()
        if la["load1"] <= max_load1 and not others:
            return {"quiet": True, "waited_s": round(time.time() - t0, 1),
                    "loadavg": la, "other_python": []}
        time.sleep(20)
    la, others = loadavg(), other_benchmarks()
    return {"quiet": False, "waited_s": round(time.time() - t0, 1),
            "loadavg": la, "other_python": others}


def meminfo() -> dict:
    out = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, _, v = line.partition(":")
        out[k] = int(v.split()[0]) * 1024
    return out


def majflt() -> int:
    fields = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()
    return int(fields[9])


def evict(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(fd)


def resident_bytes(path: Path) -> int:
    size = path.stat().st_size
    if size == 0:
        return 0
    fd = os.open(str(path), os.O_RDONLY)
    try:
        mm = mmap.mmap(fd, size, access=mmap.ACCESS_COPY)
    finally:
        os.close(fd)
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        pagesize = os.sysconf("SC_PAGE_SIZE")
        npages = (size + pagesize - 1) // pagesize
        vec = (ctypes.c_ubyte * npages)()
        addr = ctypes.addressof(ctypes.c_char.from_buffer(mm))
        rc = libc.mincore(ctypes.c_void_p(addr), ctypes.c_size_t(size), vec)
        if rc != 0:
            return -1
        import numpy as np
        return int((np.frombuffer(vec, dtype=np.uint8) & 1).sum()) * pagesize
    finally:
        mm.close()


class Balloon:
    def __init__(self):
        self.proc = None
        self.bytes = 0

    def set(self, nbytes: int) -> dict:
        self.release()
        if nbytes <= 0:
            return {"requested_bytes": 0, "ready": "none"}
        p = subprocess.Popen([sys.executable, "-c", BALLOON_SRC, str(nbytes)],
                             stdout=subprocess.PIPE, text=True)
        line = p.stdout.readline().strip()
        self.proc, self.bytes = p, nbytes
        return {"requested_bytes": nbytes, "ready": line}

    def release(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
            self.bytes = 0
            time.sleep(1.0)


def stage(src: Path, dst: Path) -> dict:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        return {"path": str(dst), "bytes": dst.stat().st_size, "copied": False}
    t0 = time.time()
    tmp = dst.with_suffix(dst.suffix + f".tmp-{os.getpid()}")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)
    return {"path": str(dst), "bytes": dst.stat().st_size, "copied": True,
            "copy_s": round(time.time() - t0, 1)}


def build_retriever(meta_path: Path):
    from lib.thinclient.retriever import ThinClientRetriever
    r = ThinClientRetriever(index_root=str(REPO / "data/thinclient_index"),
                            remote_abstracts=False)
    conn = sqlite3.connect(f"file:{meta_path}?mode=ro&immutable=1", uri=True,
                           check_same_thread=False)
    cols = {row[1]: (row[2] or "").upper()
            for row in conn.execute("PRAGMA table_info(docs)")}
    r._meta = conn
    r._meta_path = meta_path
    r._meta_numeric = cols.get("id", "").startswith("INT")
    r._ordinals = None
    r._dense_cache = None
    r._loaded = True
    return r, conn


def run_pass(r, queries, arm_kept: list) -> dict:
    per_query = []
    mf0 = majflt()
    t0 = time.perf_counter()
    kept_all = []
    for qi, q in enumerate(queries):
        scores = q.get("scores") or [1.0 / (j + 1)
                                     for j in range(len(q["candidates"]))]
        ranked = list(zip(q["candidates"], scores))
        t1 = time.perf_counter()
        kept = r._post_filter(ranked, dict(FILTERS))
        per_query.append((time.perf_counter() - t1) * 1000.0)
        kept_all.append([d for d, _ in kept])
    wall = (time.perf_counter() - t0) * 1000.0
    arm_kept.append(kept_all)
    s = sorted(per_query)
    return {"n_queries": len(per_query),
            "p50_ms": round(statistics.median(s), 3),
            "p95_ms": round(s[min(len(s) - 1, int(0.95 * (len(s) - 1)))], 3),
            "mean_ms": round(statistics.fmean(s), 3),
            "max_ms": round(s[-1], 3),
            "wall_ms": round(wall, 1),
            "majflt": majflt() - mf0}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--ordinals-src",
                    default=str(REPO / "spike/meta_consolidation/work_ordinals_full"))
    ap.add_argument("--meta-src",
                    default=str(REPO / "data/thinclient_index/meta.sqlite"))
    ap.add_argument("--stage-dir", default="/var/tmp/cliff_stage")
    ap.add_argument("--caps-gib", default="24,16,10,6,3,1.5")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--require-quiet", type=float, default=3.0,
                    help="per-cell gate: 1-min loadavg ceiling (0 disables)")
    ap.add_argument("--quiet-timeout", type=float, default=5400.0)
    ap.add_argument("--floor-gib", type=float, default=3.0,
                    help="never balloon below this much MemAvailable headroom")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    blob = json.loads(Path(args.candidates).read_text())
    queries = blob["queries"]

    stage_dir = Path(args.stage_dir)
    meta_dst = stage_dir / "meta.sqlite"
    ord_dst = stage_dir / "ordinals"
    ord_dst.mkdir(parents=True, exist_ok=True)

    staged = {"meta": stage(Path(args.meta_src), meta_dst), "ordinals": {}}
    for name in _ARRAY_FILES:
        staged["ordinals"][name] = stage(Path(args.ordinals_src) / name,
                                         ord_dst / name)

    from lib.thinclient.ordinals import OrdinalSpace
    from lib.thinclient.retriever import _fstype_for_path

    stamp = json.loads((ord_dst / "ordinal_space.json").read_text())
    src_stat = Path(args.meta_src).stat()
    pairing = {
        "ordinal_space_id": stamp["ordinal_space_id"],
        "stamp_source_bytes": stamp["source"]["bytes"],
        "stamp_source_mtime_ns": stamp["source"]["mtime_ns"],
        "meta_bytes": src_stat.st_size, "meta_mtime_ns": src_stat.st_mtime_ns,
        "bytes_match": stamp["source"]["bytes"] == src_stat.st_size,
        "mtime_match": stamp["source"]["mtime_ns"] == src_stat.st_mtime_ns,
        "manifest_has_stamp": "ordinal_space_id" in json.loads(
            (REPO / "data/thinclient_index/manifest.json").read_text()),
    }
    if not (pairing["bytes_match"] and pairing["mtime_match"]):
        raise SystemExit("ordinal arrays are NOT paired with this meta.sqlite — "
                         "refusing to measure a stale ordinal space")

    mi0 = meminfo()
    caps = [float(x) for x in args.caps_gib.split(",")]
    report = {
        "what": "ordinals residency cliff — filter stage under a page-cache ladder",
        "date": "2026-09-25",
        "script": "scripts/experiments/eval_ordinals_cliff.py",
        "pre_registration": "docs/ORDINALS_RESIDENCY_CLIFF.md",
        "candidates_file": args.candidates,
        "n_queries": len(queries),
        "candidates_per_query": queries[0]["n_candidates"] if queries else 0,
        "filters": FILTERS,
        "passes_per_arm": args.passes,
        "caps_gib": caps,
        "staged": staged,
        "ordinal_pairing": pairing,
        "cap_mechanism": ("mlock'd anonymous balloon in a child process; no "
                          "cgroup memory.max is reachable from this container "
                          "(cgroup ro, no CAP_SYS_ADMIN, no docker, no "
                          "systemd-run) and no other host exists as of "
                          "2026-09-25"),
        "host": {
            "kernel": os.uname().release,
            "mem_total_bytes": mi0["MemTotal"],
            "mem_available_at_start": mi0["MemAvailable"],
            "swap_total_bytes": mi0.get("SwapTotal", 0),
            "mglru": Path("/sys/kernel/mm/lru_gen/enabled").read_text().strip()
            if Path("/sys/kernel/mm/lru_gen/enabled").exists() else "absent",
            "cgroup_version": "v2" if Path("/sys/fs/cgroup/cgroup.controllers").exists() else "v1",
            "meta_staged_fstype": _fstype_for_path(str(meta_dst)),
            "ordinals_staged_fstype": _fstype_for_path(str(ord_dst)),
            "meta_src_fstype": _fstype_for_path(args.meta_src),
        },
        "quiet_gate_max_load1": args.require_quiet,
        "loadavg_at_start": loadavg(),
        "other_python_at_start": other_benchmarks(),
        "rungs": [],
    }
    print(json.dumps(report["host"], indent=1), flush=True)

    balloon = Balloon()
    array_paths = [ord_dst / n for n in _ARRAY_FILES if n.endswith(".npy")]
    try:
        for cap in caps:
            balloon.release()
            time.sleep(3.0)
            mi = meminfo()
            want = int(mi["MemAvailable"] - cap * GIB)
            hard = int(mi["MemAvailable"] - args.floor_gib * GIB)
            nbytes = max(0, min(want, hard))
            bstat = balloon.set(nbytes)
            time.sleep(3.0)
            mi_after = meminfo()
            rung = {"cap_gib": cap, "balloon": bstat,
                    "mem_available_after_balloon": mi_after["MemAvailable"],
                    "cap_effective_gib": round(mi_after["MemAvailable"] / GIB, 2),
                    "mlocked_bytes": mi_after.get("Mlocked", 0),
                    "arms": {}}
            print(f"== cap {cap} GiB: balloon {nbytes/GIB:.2f} GiB, "
                  f"MemAvailable now {mi_after['MemAvailable']/GIB:.2f} GiB",
                  flush=True)

            kept_by_arm = {}
            for arm in ("sqlite", "ordinals"):
                gc.collect()
                if args.require_quiet:
                    rung.setdefault("quiet_gate", {})[arm] = wait_quiet(
                        args.require_quiet, args.quiet_timeout)
                    print(f"   [{arm}] quiet_gate "
                          f"{json.dumps(rung['quiet_gate'][arm])}", flush=True)
                evict(meta_dst)
                for p in array_paths:
                    evict(p)
                res0 = {"meta": resident_bytes(meta_dst),
                        "ordinals": sum(resident_bytes(p) for p in array_paths)}
                r, conn = build_retriever(meta_dst)
                if arm == "ordinals":
                    r._ordinals = OrdinalSpace(
                        ord_dst, {"ordinal_space_id": stamp["ordinal_space_id"]})
                arm_kept: list = []
                passes = []
                for _ in range(args.passes):
                    passes.append(run_pass(r, queries, arm_kept))
                    print(f"   [{arm}] pass {len(passes)}: "
                          f"p50={passes[-1]['p50_ms']} p95={passes[-1]['p95_ms']} "
                          f"majflt={passes[-1]['majflt']}", flush=True)
                res1 = {"meta": resident_bytes(meta_dst),
                        "ordinals": sum(resident_bytes(p) for p in array_paths)}
                unresolved = None
                if arm == "ordinals":
                    tot = 0
                    for q in queries:
                        _, found = r._ordinals.lookup(q["candidates"])
                        tot += int((~found).sum())
                    unresolved = tot
                conn.close()
                r._ordinals = None
                r._meta = None
                del r
                gc.collect()
                kept_by_arm[arm] = arm_kept[-1]
                rung["arms"][arm] = {
                    "passes": passes,
                    "loadavg_after": loadavg(),
                    "resident_before_bytes": res0,
                    "resident_after_bytes": res1,
                    "ids_without_ordinal": unresolved,
                }

            a, b = kept_by_arm["sqlite"], kept_by_arm["ordinals"]
            mism = sum(1 for x, y in zip(a, b) if x != y)
            rung["parity"] = {"queries": len(a), "mismatches": mism,
                              "pass": mism == 0}
            print(f"   parity mismatches={mism}", flush=True)
            report["rungs"].append(rung)
            Path(args.out).write_text(json.dumps(report, indent=1) + "\n")
    finally:
        balloon.release()

    for rung in report["rungs"]:
        s = rung["arms"]["sqlite"]["passes"][-1]
        o = rung["arms"]["ordinals"]["passes"][-1]
        rung["summary"] = {
            "cap_effective_gib": rung["cap_effective_gib"],
            "sqlite_p50_ms": s["p50_ms"], "sqlite_p95_ms": s["p95_ms"],
            "ordinals_p50_ms": o["p50_ms"], "ordinals_p95_ms": o["p95_ms"],
            "p95_ratio_sqlite_over_ordinals": round(o["p95_ms"] and
                                                    s["p95_ms"] / o["p95_ms"], 3),
            "sqlite_majflt": s["majflt"], "ordinals_majflt": o["majflt"],
        }
    report["loadavg_at_end"] = loadavg()
    Path(args.out).write_text(json.dumps(report, indent=1) + "\n")
    print("WROTE", args.out, flush=True)
    print(json.dumps([r["summary"] for r in report["rungs"]], indent=1))


if __name__ == "__main__":
    main()
