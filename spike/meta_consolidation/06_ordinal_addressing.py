#!/usr/bin/env python3
"""C6 — ordinal addressing: the consolidation that is FASTER, not merely equal.

Every consolidation attempt in §10-§12 lost, and all of them lost the same way:
they kept `W-id` as the address and swapped the thing that SEARCHES for it.

    meta.sqlite  B-tree descent per id      0.4  ms/id   (baseline, §10.3)
    tantivy      fst term-dictionary walk   27-54x worse (§10.3, §11)
    Lance        BTREE scalar index         1.15-1.72x   (§12)

A `W-id` is a sparse 64-bit integer with no relationship to where the row sits,
so resolving one is inherently a *search*. Doing that ~1000x per query in Python
is where the ~400 ms post-filter mask comes from.

C6 changes the address instead of the searcher. Give every doc a global ordinal
`0..N` at build time and:

  * the filter mask becomes a numpy fancy-index into mmap'd columnar arrays --
    an array INDEX, not a search;
  * `W-id -> ordinal`, still needed for direct lookups by id, becomes ONE
    vectorised binary search over a sorted array instead of k independent page
    faults.

Note the direction. C1 failed going `id -> DocId` (fst traversal). C6 goes
`DocId -> ordinal -> metadata`, which is columnar the whole way and never
touches a term dictionary -- and §11's addendum already measured that tantivy's
fast-field reads are not the bottleneck, only the term dictionary is.

The structural win is residency: the filter columns for 150M docs are ~0.75 GB
and the W-id index ~1.2 GB, so ~1.95 GB stays permanently in RAM where 24.9 GB
never can. That is why this is not a caching fluke.

Measures PRIMITIVES at true production scale (150M), not an end-to-end system.
Writes only to a scratch dir. Nothing under `data/` is opened.

    .venv/bin/python3 spike/meta_consolidation/06_ordinal_addressing.py
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]

# Measured production baselines, data/eval_results/c1_production_scale_20260802_0529.json
SQLITE_BASELINE_MS = {100: 38.68, 500: 203.43, 1000: 400.83}

# year int16, type int8, is_oa uint8, section int8 -- exactly the columns
# retriever._post_filter reads.
COLUMNS = [("year", np.int16), ("dtype", np.int8),
           ("is_oa", np.uint8), ("section", np.int8)]


def build_columns(d: Path, n: int) -> dict:
    d.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    for name, dt in COLUMNS:
        p = d / f"{name}.npy"
        if p.exists():
            continue
        a = np.lib.format.open_memmap(str(p), mode="w+", dtype=dt, shape=(n,))
        step = 10_000_000
        for s in range(0, n, step):
            k = min(step, n - s)
            a[s:s + k] = np.random.randint(0, 100, size=k).astype(dt)
        a.flush()
        del a
    total = sum((d / f"{nm}.npy").stat().st_size for nm, _ in COLUMNS)
    return {"bytes": total, "build_s": round(time.perf_counter() - t0, 1)}


def build_wid_index(d: Path, n: int) -> tuple[np.ndarray, dict]:
    """Sorted int64 W-ids. Built from cumulative random gaps so the max lands
    near production's 7.14e9 without an O(range) allocation."""
    p = d / "wids.npy"
    t0 = time.perf_counter()
    if p.exists():
        ids = np.load(str(p), mmap_mode="r")
    else:
        gaps = np.random.default_rng(1).integers(1, 96, size=n, dtype=np.int64)
        ids = np.cumsum(gaps)
        del gaps
        np.save(str(p), ids)
        ids = np.load(str(p), mmap_mode="r")
    return ids, {"bytes": p.stat().st_size, "max_id": int(ids[-1]),
                 "build_s": round(time.perf_counter() - t0, 1)}


def bench(fn, make_arg, reps, warmup):
    for _ in range(warmup):
        fn(make_arg())
    s = []
    for _ in range(reps):
        arg = make_arg()
        t0 = time.perf_counter()
        fn(arg)
        s.append((time.perf_counter() - t0) * 1000)
    s.sort()
    return {"reps": reps, "p50_ms": round(statistics.median(s), 4),
            "min_ms": round(s[0], 4), "max_ms": round(s[-1], 4)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=int, default=150_000_000)
    ap.add_argument("--sizes", type=int, nargs="+", default=[100, 500, 1000, 5000])
    ap.add_argument("--reps", type=int, default=15)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--scratch", type=Path,
                    default=Path(os.environ.get("TMPDIR", "/tmp")) / "c6_ordinal")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    n = args.rows
    rep = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": n,
           "sqlite_baseline_ms": SQLITE_BASELINE_MS,
           "baseline_source": "data/eval_results/c1_production_scale_20260802_0529.json",
           "caveat": "PRIMITIVES at 150M, not an end-to-end system"}

    print(f"building {n:,} ordinal columns…", flush=True)
    rep["columns"] = build_columns(args.scratch, n)
    print(f"  {rep['columns']['bytes']/1e9:.2f} GB", flush=True)
    print("building sorted W-id index…", flush=True)
    ids, wmeta = build_wid_index(args.scratch, n)
    rep["wid_index"] = wmeta
    print(f"  {wmeta['bytes']/1e9:.2f} GB, max={wmeta['max_id']:,}", flush=True)
    rep["resident_total_gb"] = round(
        (rep["columns"]["bytes"] + wmeta["bytes"]) / 1e9, 2)

    cols = {nm: np.load(str(args.scratch / f"{nm}.npy"), mmap_mode="r")
            for nm, _ in COLUMNS}
    rng = np.random.default_rng(7)

    def mask(ords):
        y = cols["year"][ords]
        t = cols["dtype"][ords]
        o = cols["is_oa"][ords]
        return np.flatnonzero((y > 50) & (t < 40) & (o > 0))

    rep["results"] = {}
    for k in args.sizes:
        m = bench(mask, lambda: rng.integers(0, n, k), args.reps, args.warmup)
        b = bench(lambda q: np.searchsorted(ids, q),
                  lambda: np.sort(ids[rng.integers(0, n, k)]),
                  args.reps, args.warmup)
        # correctness: binary search must land on the exact row
        probe = np.sort(ids[rng.integers(0, n, k)])
        ok = bool(np.all(ids[np.searchsorted(ids, probe)] == probe))
        e = {"ordinal_mask": m, "wid_to_ordinal": b, "binary_search_exact": ok}
        base = SQLITE_BASELINE_MS.get(k)
        if base:
            e["mask_speedup_vs_sqlite"] = round(base / m["p50_ms"], 1)
            e["lookup_speedup_vs_sqlite"] = round(base / b["p50_ms"], 1)
        rep["results"][str(k)] = e
        print(f"k={k:<6} mask {m['p50_ms']:8.3f} ms | wid->ord "
              f"{b['p50_ms']:8.3f} ms | exact={ok}"
              + (f" | vs sqlite {base} ms: mask {e['mask_speedup_vs_sqlite']}x, "
                 f"lookup {e['lookup_speedup_vs_sqlite']}x" if base else ""),
              flush=True)

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"c6_ordinal_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    print("results ->", out, flush=True)


if __name__ == "__main__":
    main()
