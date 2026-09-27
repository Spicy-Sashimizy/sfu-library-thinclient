"""N2 — MPHF viability for ordinal addressing (doc 18 §7 N2): orchestrator.

Runs the Rust harness (src/main.rs) end to end on the real 150,413,098 W-ids and
adds a numpy `searchsorted` baseline (the lookup `src/lib/thinclient/ordinals.py`
actually ships), then writes one results JSON.

Every step that allocates GBs or streams GBs from disk runs under
`flock /tmp/sfu_latency_measure.lock` so it never overlaps other agents' timed
latency runs; the lock is held per step, not for the whole run.

Usage (see README.md):
    .venv/bin/python3 spike/n2_mphf/run_n2.py \
        --wids /tmp/claude-1000/n2_mphf/wids.npy \
        --work /tmp/claude-1000/n2_mphf/full \
        --out data/eval_results/n2_mphf_viability_2026-09-27.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
LOCK = "/tmp/sfu_latency_measure.lock"
BIN = Path("/tmp/claude-1000/n2_mphf/target/release/n2_mphf")
ARMS = ["bsearch", "mphf_only", "mphf_keys", "mphf_perm_wids", "mphf_fp8", "mphf_fp16"]
LOCKCMD = [] if os.environ.get("N2_NO_LOCK") == "1" else ["flock", LOCK]
BAR_BYTES = 100 * 1000 * 1000
BAR_NS = 100.0


def run_locked(args: list[str]) -> tuple[dict, float, int]:
    """Run the harness under the shared measurement lock; return (json, wall_s, child maxrss kB)."""
    before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    t_wait = time.time()
    t = None
    cmd = [*LOCKCMD, "sh", "-c", 'echo LOCKED >&2; exec "$@"', "sh", str(BIN), *args]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in p.stderr:
        if line.strip() == "LOCKED" and t is None:
            t = time.time()
            print(f"  lock acquired after {t - t_wait:.1f}s: {' '.join(args[:1])} {args[-1]}", flush=True)
        else:
            sys.stderr.write(line)
    out = p.stdout.read()
    rc = p.wait()
    wall = time.time() - (t or t_wait)
    if rc != 0:
        raise SystemExit(f"harness failed rc={rc}: {args}")
    after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return json.loads(out.strip().splitlines()[-1]), wall, max(after, before)


def evict(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(fd)


def pctl(a: np.ndarray) -> dict:
    return {
        "p50_ns": float(np.percentile(a, 50)),
        "p99_ns": float(np.percentile(a, 99)),
        "mean_ns": float(a.mean()),
    }


def numpy_baseline(wids_path: Path, work: Path, n_single: int) -> dict:
    """ordinals.py's shipped path: np.searchsorted over the mmap'd sorted array, then
    an equality check at the landing position (the verification read). Timed per call
    for batch=1 (one id) and batch=1000 (≈ the k=1000 candidate case), cold and warm."""
    hits = np.fromfile(work / "q_hit.u64", dtype=np.int64)
    misses = np.fromfile(work / "q_miss.u64", dtype=np.int64)
    res: dict = {}

    def one_pass(w, q, batch, limit):
        q = q[:limit]
        times = []
        found = 0
        rows = len(w)
        for i in range(0, len(q), batch):
            b = q[i:i + batch]
            t0 = time.perf_counter_ns()
            pos = np.clip(np.searchsorted(w, b), 0, rows - 1)
            ok = w[pos] == b
            t1 = time.perf_counter_ns()
            found += int(ok.sum())
            times.append((t1 - t0) / len(b))
        return np.asarray(times), found

    for batch, limit in ((1, n_single), (1000, len(hits))):
        key = f"batch{batch}"
        res[key] = {"n_keys": limit}
        for label, q in (("hits", hits), ("misses", misses)):
            evict(wids_path)
            w = np.load(wids_path, mmap_mode="r")
            t, f = one_pass(w, q, batch, limit)
            res[key].setdefault("cold", {})[label] = {**pctl(t), "accepted": f}
            del w
        w = np.load(wids_path, mmap_mode="r")
        one_pass(w, hits, batch, limit)
        for label, q in (("hits", hits), ("misses", misses)):
            t, f = one_pass(w, q, batch, limit)
            res[key].setdefault("warm", {})[label] = {**pctl(t), "accepted": f}
        del w
    res["note"] = ("per-CALL time divided by batch size, perf_counter_ns; batch=1 includes the "
                   "full numpy dispatch overhead per id, which is what a per-id caller would pay")
    return res


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def info_bound_bytes(n: int, universe: int) -> float:
    """log2 C(U, n) / 8: the minimum bytes ANY exact membership structure over n keys
    drawn from a universe of U values can use (static set, worst case)."""
    lg = (math.lgamma(universe + 1) - math.lgamma(n + 1) - math.lgamma(universe - n + 1)) / math.log(2)
    return lg / 8


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wids", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--nq", type=int, default=1_000_000)
    ap.add_argument("--seed", type=int, default=20260927)
    ap.add_argument("--numpy-single", type=int, default=200_000)
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--numpy-only", action="store_true", help="internal: run the numpy baseline, print JSON")
    a = ap.parse_args()
    if a.numpy_only:
        print(json.dumps(numpy_baseline(a.wids, a.work, a.numpy_single)))
        return
    a.work.mkdir(parents=True, exist_ok=True)

    rep: dict = {
        "experiment": "N2 MPHF viability for ordinal addressing (doc 18 §7 N2)",
        "date": "2026-09-27",
        "host": {
            "cpu": next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), "?"),
            "cores": os.cpu_count(),
            "mem_total_gb": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9, 1),
            "kernel": platform.release(),
            "fs_of_work_dir": "overlay (local disk, not 9p)",
        },
        "library": {"name": "ptr_hash (PtrHash, Groot Koerkamp, SEA 2025)", "version": "2.1.1", "license": "MIT",
                    "serialization": "epserde 0.13.1 (file-backed mmap via Deserialize::mmap)",
                    "hasher": "ptr_hash::hash::Xxh3Int", "rustc": subprocess.run(
                        [str(Path.home() / ".cargo/bin/rustc"), "--version"], capture_output=True, text=True).stdout.strip(),
                    "rustflags": "-C target-cpu=x86-64-v3, opt-level=3, lto=thin, codegen-units=1"},
        "input": {"path": str(a.wids), "source": "spike/meta_consolidation/work_ordinals_full/wids.npy (byte copy, sha256 verified)",
                  "sha256": sha256(a.wids)},
    }
    w = np.load(a.wids, mmap_mode="r")
    n = int(len(w))
    lo, hi = int(w[0]), int(w[-1])
    del w
    rep["input"].update({"n_keys": n, "key_min": lo, "key_max": hi})

    if not a.skip_build:
        print("build ...", flush=True)
        b, wall, rss = run_locked(["build", str(a.wids), str(a.work)])
        b["wall_s_incl_process"] = round(wall, 2)
        b["peak_rss_kb_child"] = rss
        rep["build"] = b
        print("payload ...", flush=True)
        p, wall, rss = run_locked(["payload", str(a.wids), str(a.work)])
        p["wall_s_incl_process"] = round(wall, 2)
        rep["payload"] = p
        print("genq ...", flush=True)
        g, wall, _ = run_locked(["genq", str(a.wids), str(a.work), str(a.nq), str(a.seed)])
        rep["queries"] = g
    else:
        prev = json.loads(a.out.read_text())
        rep.update({k: prev[k] for k in ("build", "payload", "queries")})

    rep["arms"] = {}
    for arm in ARMS:
        print(f"bench {arm} ...", flush=True)
        r, wall, rss = run_locked(["bench", str(a.wids), str(a.work), arm])
        r["wall_s"] = round(wall, 2)
        rep["arms"][arm] = r

    print("numpy baseline ...", flush=True)
    t0 = time.time()
    np_out = subprocess.run([*LOCKCMD, sys.executable, __file__, "--numpy-only", "--wids", str(a.wids),
                             "--work", str(a.work), "--out", str(a.out), "--numpy-single", str(a.numpy_single)],
                            check=True, capture_output=True, text=True).stdout
    rep["numpy_searchsorted_baseline"] = json.loads(np_out.strip().splitlines()[-1])
    rep["numpy_searchsorted_baseline"]["wall_s"] = round(time.time() - t0, 1)

    mphf_bytes = rep["build"]["mphf_bytes"]
    bound = info_bound_bytes(n, hi - lo + 1)
    summary = {}
    for arm, r in rep["arms"].items():
        exact = arm in ("bsearch", "mphf_keys", "mphf_perm_wids")
        worst_warm = max(r["warm"]["hits"]["p50_ns"], r["warm"]["misses"]["p50_ns"])
        worst_warm_p99 = max(r["warm"]["hits"]["p99_ns"], r["warm"]["misses"]["p99_ns"])
        summary[arm] = {
            "exact_membership": exact if arm != "mphf_only" else False,
            "on_disk_bytes": r["on_disk_bytes"],
            "warm_resident_bytes": r["warm_resident"]["page_cache"]["total_resident_bytes"],
            "warm_p50_ns_worst_of_hit_miss": worst_warm,
            "warm_p99_ns_worst_of_hit_miss": worst_warm_p99,
            "warm_throughput_ns_hits": r["warm"]["hits"]["throughput_loop_ns_per_key"],
            "miss_false_accept_rate": r["correctness"]["miss_false_accept_rate"],
            "hits_not_found_or_wrong": r["correctness"]["hits_not_found_or_wrong"],
            "size_bar_pass": r["on_disk_bytes"] <= BAR_BYTES,
            "latency_bar_pass_warm_p50": worst_warm <= BAR_NS,
        }
    rep["summary"] = summary
    rep["bar"] = {"bytes_max": BAR_BYTES, "ns_per_key_max": BAR_NS,
                  "source": "doc 18 §7 N2, pre-registered 2026-08-02: <=100 MB and <=100 ns/key end-to-end incl. verification read"}
    rep["information_theoretic_floor"] = {
        "universe": hi - lo + 1, "n": n,
        "min_bytes_any_exact_membership_structure": round(bound),
        "bits_per_key": round(bound * 8 / n, 3),
        "note": "log2 C(U,n)/8 over U = key_max-key_min+1; no exact structure (MPHF+keys, Elias-Fano, "
                "succinct bitmap, ...) can store this set in fewer bytes, so a <=100 MB exact answer is impossible",
    }
    exact_mphf = [s for k, s in summary.items() if k in ("mphf_keys", "mphf_perm_wids")]
    rep["verdict"] = {
        "result": "FAIL" if not any(s["size_bar_pass"] and s["latency_bar_pass_warm_p50"] for s in exact_mphf) else "PASS",
        "mphf_alone_bytes": mphf_bytes,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(rep, indent=2) + "\n")
    print(json.dumps(rep["summary"], indent=1))
    print(json.dumps(rep["verdict"]))


if __name__ == "__main__":
    main()
