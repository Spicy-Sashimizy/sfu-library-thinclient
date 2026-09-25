#!/usr/bin/env python3
"""Lever #4 (term-prefix block prefetch while typing) — A/B harness.

Status when written (2026-09-25): NOT RUN. The host page cache was reserved by
another agent's measurement, so this script was written and syntax-checked
only; its results are PENDING. Pre-registration is
`docs/SPECULATIVE_RETRIEVAL_UPGRADES.md` §4 row 4.

What it measures, per query, on the served SEISMIC mmap shards:

    cold_none      evict, then traverse the final query              (control)
    cold_prefetch  evict, advise the typed-prefix plan, wait
                   --lead-ms (simulated typing gap), then traverse   (lever)
    warm_none      index already resident, traverse                  (RAM arm)
    warm_prefetch  index already resident, advise, wait, traverse    (RAM arm)

The RAM-resident pair is REQUIRED by the doc: `docs/ORDINALS_RESIDENCY_CLIFF.md`
predicts no gain once the working set is in page cache, so a warm delta
outside noise would mean the harness is measuring something else (syscall
cost, thread contention). Arms rotate per query so no arm always runs first.

Metrics: traverse p50/p95 per arm (the `search_encoded` wall, SPLADE encode
excluded and done once per query up front), major faults per traverse, bytes
advised per search, and wasted bytes per search = advised bytes that fall
outside the final query's own (uncapped) posting-list plan. Waste is a plan
intersection, not a page-level measurement: the pages the traversal actually
touches depend on which blocks survive and are not observable from Python.

Eviction between cold trials reuses the ordinals-cliff ladder approach
(`scripts/experiments/eval_ordinals_cliff.py`): per-file
`posix_fadvise(POSIX_FADV_DONTNEED)` on each shard file, verified with
`mincore(2)` on `posting_lists.bin`, a quiet-host gate before each query, and
an optional mlock'd balloon ladder (`--caps-gib`) that shrinks the page cache
the run can use. Because the Rust reader keeps its own mapping of each file,
mapped pages are first dropped with the shard's `release_pages()`
(MADV_DONTNEED, mechanism B; `e5_shard_gates.fadvise_dontneed_dir` order).
A global `drop_caches` is never used.

Run later (only when the host page cache is free for this measurement):

    .venv/bin/python3 scripts/experiments/eval_block_prefetch.py \
        --confirm-host-free --shards 0 --n 40 \
        --out data/eval_results/block_prefetch_ab_<date>.json

`--shards all` federates all eight shards (needs the full ~66 GB converted
set on local disk; the single-shard default keeps the run inside RAM).
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_ordinals_cliff as cliff  # ladder: evict / resident_bytes / wait_quiet / Balloon

GIB = 1 << 30
DEFAULT_MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"
DEFAULT_QUERIES = REPO / "data/eval_results/diverse_queries.json"
ARMS = ("cold_none", "cold_prefetch", "warm_none", "warm_prefetch")


def load_queries(path: Path, n: int) -> list[str]:
    blob = json.loads(path.read_text())
    out, seen = [], set()
    for row in blob:
        q = row.get("original_query") if isinstance(row, dict) else str(row)
        if q and q not in seen and len(q.split()) >= 2:
            seen.add(q)
            out.append(q)
        if len(out) >= n:
            break
    return out


def typed_prefix(query: str, frac: float) -> str:
    """The first ceil(frac × words) words, followed by a space (so every word
    in it counts as finished for `completed_words`); never the whole query."""
    words = query.split()
    k = max(1, min(len(words) - 1, math.ceil(frac * len(words))))
    return " ".join(words[:k]) + " "


def pctl(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, int(p * (len(s) - 1)))] if s else float("nan")


def covered_bytes(plan, ref) -> int:
    """Bytes of `plan` that fall inside any range of `ref` (same file)."""
    by_file: dict[str, list[tuple[int, int]]] = {}
    for p, o, n in ref:
        by_file.setdefault(p, []).append((o, o + n))
    tot = 0
    for p, o, n in plan:
        for a, b in by_file.get(p, ()):
            lo, hi = max(o, a), min(o + n, b)
            if hi > lo:
                tot += hi - lo
    return tot


def shard_files(dirs: list[str]) -> list[Path]:
    out = []
    for d in dirs:
        for f in sorted(os.listdir(d)):
            p = Path(d) / f
            if p.is_file() and p.suffix == ".bin":
                out.append(p)
    return out


def evict_all(backend, dirs: list[str]) -> dict:
    released = 0
    for idx in backend.shards:
        if idx is not None and hasattr(idx, "release_pages"):
            released += int(idx.release_pages() or 0)
    for p in shard_files(dirs):
        cliff.evict(p)
    pl_res = sum(max(0, cliff.resident_bytes(Path(d) / "posting_lists.bin")) for d in dirs)
    return {"released_ranges": released, "posting_lists_resident_after": pl_res}


def traverse(backend, q, top_k: int) -> tuple[float, int, list]:
    mf0 = cliff.majflt()
    t0 = time.perf_counter()
    res = backend.search_encoded(q, top_k)
    return (time.perf_counter() - t0) * 1000.0, cliff.majflt() - mf0, res


def build_backend(manifest: str, shards: str, federation: str, stage_dir: str = ""):
    from lib.thinclient.sharded_seismic_backend import (ParallelSeismicBackend,
                                                        SequentialSeismicBackend,
                                                        _load_manifest)
    paths = _load_manifest(manifest, load_mode="mmap")
    if shards != "all":
        keep = [int(x) for x in shards.split(",")]
        paths = [paths[i] for i in keep]
    if stage_dir:
        staged = []
        for p in paths:
            cand = Path(stage_dir) / Path(p).name
            staged.append(str(cand) if (cand / ".staged_ok").is_file() else p)
        paths = staged
    cls = SequentialSeismicBackend if federation == "sequential" else ParallelSeismicBackend
    return cls(paths, splade_model_path=str(REPO / "models/splade_onnx_fused"), load_mode="mmap")


def run_rung(backend, pf, dirs, queries, args, rung: dict) -> None:
    per_arm = {a: {"ms": [], "majflt": [], "advised": [], "wasted": [], "plan_ms": []}
               for a in ARMS}
    parity_bad = 0
    for qi, final in enumerate(queries):
        if args.require_quiet:
            rung.setdefault("quiet_gate", []).append(
                cliff.wait_quiet(args.require_quiet, args.quiet_timeout))
        q = backend.encode_query(final)
        if not q:
            continue
        prefix = typed_prefix(final, args.prefix_frac)
        t0 = time.perf_counter()
        plan = pf.plan_prefetch(prefix)
        plan_ms = (time.perf_counter() - t0) * 1000.0
        ref = pf.plan_for_terms(list(q.keys()), max_bytes=1 << 62)
        advised = sum(n for _, _, n in plan)
        wasted = advised - covered_bytes(plan, ref)
        if qi % 2 == 0:
            order = ("cold_none", "cold_prefetch", "warm_none", "warm_prefetch")
        else:
            order = ("cold_prefetch", "cold_none", "warm_prefetch", "warm_none")
        results = {}
        for arm in order:
            gc.collect()
            if arm.startswith("cold"):
                ev = evict_all(backend, dirs)
                rung.setdefault("evictions", []).append(ev)
            else:
                traverse(backend, q, args.top_k)
            if arm.endswith("prefetch"):
                pf.issue_prefetch(plan)
                time.sleep(args.lead_ms / 1000.0)
            ms, mf, res = traverse(backend, q, args.top_k)
            results[arm] = [d for d, _ in res]
            a = per_arm[arm]
            a["ms"].append(ms)
            a["majflt"].append(mf)
            a["advised"].append(advised if arm.endswith("prefetch") else 0)
            a["wasted"].append(wasted if arm.endswith("prefetch") else 0)
            a["plan_ms"].append(plan_ms if arm.endswith("prefetch") else 0.0)
        if len({tuple(v) for v in results.values()}) != 1:
            parity_bad += 1
        print(f"  q{qi:03d} " + " ".join(f"{a}={per_arm[a]['ms'][-1]:.1f}ms" for a in ARMS)
              + f" advised={advised/1e6:.1f}MB wasted={wasted/1e6:.1f}MB", flush=True)
    rung["parity"] = {"queries": len(queries), "mismatches": parity_bad,
                      "pass": parity_bad == 0}
    rung["arms"] = {}
    for arm, a in per_arm.items():
        rung["arms"][arm] = {
            "n": len(a["ms"]),
            "traverse_p50_ms": round(statistics.median(a["ms"]), 2) if a["ms"] else None,
            "traverse_p95_ms": round(pctl(a["ms"], 0.95), 2) if a["ms"] else None,
            "majflt_p50": statistics.median(a["majflt"]) if a["majflt"] else None,
            "advised_bytes_mean": round(statistics.fmean(a["advised"])) if a["advised"] else 0,
            "wasted_bytes_mean": round(statistics.fmean(a["wasted"])) if a["wasted"] else 0,
            "plan_ms_p50": round(statistics.median(a["plan_ms"]), 2) if a["plan_ms"] else None,
            "per_query_ms": [round(x, 2) for x in a["ms"]],
        }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--confirm-host-free", action="store_true",
                    help="required: this evicts shard files from the page cache")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--shards", default="0", help="comma list of shard indices, or 'all'")
    ap.add_argument("--federation", default="sequential", choices=("sequential", "parallel"))
    ap.add_argument("--stage-dir", default="/var/tmp/seismic_stage",
                    help="use a .staged_ok local-disk copy of each shard when present "
                         "(the served dev-container path; '' to read data/seismic_150m)")
    ap.add_argument("--queries", default=str(DEFAULT_QUERIES))
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--prefix-frac", type=float, default=0.6,
                    help="fraction of the final query's words typed when the prefetch fires")
    ap.add_argument("--lead-ms", type=float, default=300.0,
                    help="typing gap between the prefetch and the submit")
    ap.add_argument("--max-mb", type=float, default=None,
                    help="SFU_BLOCK_PREFETCH_MAX_MB for the run (default: module default)")
    ap.add_argument("--caps-gib", default="",
                    help="optional page-cache ladder, e.g. '16,8,4' (mlock'd balloon)")
    ap.add_argument("--floor-gib", type=float, default=3.0)
    ap.add_argument("--require-quiet", type=float, default=3.0)
    ap.add_argument("--quiet-timeout", type=float, default=5400.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if not args.confirm_host_free:
        raise SystemExit("refusing to run without --confirm-host-free: this evicts the "
                         "SEISMIC shard files from the shared page cache")

    os.environ["SFU_BLOCK_PREFETCH"] = "1"
    if args.max_mb is not None:
        os.environ["SFU_BLOCK_PREFETCH_MAX_MB"] = str(args.max_mb)
    from lib.thinclient import block_prefetch as bp

    backend = build_backend(args.manifest, args.shards, args.federation, args.stage_dir)
    dirs = [d for d in backend._shard_mmap_dirs if d]
    pf = bp.BlockPrefetcher(dirs, encode_fn=backend.encode_query, load_mode="mmap")
    queries = load_queries(Path(args.queries), args.n)
    layouts = pf.layouts()

    mi0 = cliff.meminfo()
    report = {
        "what": "lever #4 term-prefix block prefetch — cold/warm A/B",
        "date": time.strftime("%Y-%m-%d"),
        "script": "scripts/experiments/eval_block_prefetch.py",
        "pre_registration": "docs/SPECULATIVE_RETRIEVAL_UPGRADES.md §4 row 4",
        "manifest": args.manifest, "stage_dir": args.stage_dir, "shards": args.shards, "federation": args.federation,
        "shard_dirs": dirs, "layouts_loaded": len(layouts),
        "n_queries": len(queries), "top_k": args.top_k,
        "prefix_frac": args.prefix_frac, "lead_ms": args.lead_ms,
        "max_bytes": bp.max_bytes_from_env(),
        "env": {k: v for k, v in os.environ.items() if k.startswith("SFU_")},
        "eviction": "release_pages() then per-file posix_fadvise DONTNEED, mincore-verified "
                    "(eval_ordinals_cliff ladder); never drop_caches",
        "waste_definition": "advised bytes outside the final query's uncapped posting-list plan",
        "host": {"mem_total_bytes": mi0["MemTotal"],
                 "mem_available_at_start": mi0["MemAvailable"],
                 "kernel": os.uname().release},
        "rungs": [],
    }
    caps = [float(x) for x in args.caps_gib.split(",") if x.strip()] or [None]
    balloon = cliff.Balloon()
    try:
        for cap in caps:
            rung: dict = {"cap_gib": cap}
            if cap is not None:
                balloon.release()
                mi = cliff.meminfo()
                want = int(mi["MemAvailable"] - cap * GIB)
                hard = int(mi["MemAvailable"] - args.floor_gib * GIB)
                rung["balloon"] = balloon.set(max(0, min(want, hard)))
                time.sleep(3.0)
            rung["mem_available"] = cliff.meminfo()["MemAvailable"]
            print(f"== rung cap={cap} MemAvailable={rung['mem_available']/GIB:.2f} GiB", flush=True)
            run_rung(backend, pf, dirs, queries, args, rung)
            ev = rung.pop("evictions", [])
            rung["eviction_summary"] = {
                "n": len(ev),
                "posting_lists_resident_after_max": max(
                    (e["posting_lists_resident_after"] for e in ev), default=0)}
            report["rungs"].append(rung)
            Path(args.out).write_text(json.dumps(report, indent=1) + "\n")
    finally:
        balloon.release()
        pf.close()
    for rung in report["rungs"]:
        print(json.dumps({"cap_gib": rung["cap_gib"],
                          **{a: {k: rung["arms"][a][k] for k in
                                 ("traverse_p50_ms", "traverse_p95_ms", "majflt_p50",
                                  "wasted_bytes_mean")} for a in ARMS},
                          "parity": rung["parity"]}, indent=1))


if __name__ == "__main__":
    main()
