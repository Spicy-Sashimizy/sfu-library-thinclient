#!/usr/bin/env python3
"""N4 — swap `_post_filter` to the ordinal path, gated on byte-parity.

Doc 18 §7 N4, as restaged by §10: **no rebuild of anything.** The legs keep
emitting W-ids exactly as they do today; the ordinal path converts them with one
vectorised binary search and then masks against mmap'd columnar arrays. So this
is purely a swap of the filter stage, and it can be gated against the live
retriever without touching tantivy, SEISMIC, usearch, or the build.

Two arms over the SAME candidate ids and the SAME filter:

  production  ThinClientRetriever._post_filter -> _meta_rows -> meta.sqlite
  ordinal     np.searchsorted(wids, ids) -> fancy-index year/dtype/is_oa arrays

**The gate is parity, not speed.** The surviving id sets must be identical, in
the same order (the legs' rank order must be preserved). A faster filter that
returns a different result set is not a result.

Artifacts come from `09_n3_build_ordinals.py`. If that ran with `--limit`, only
the first N docs by ascending id have ordinals, so candidate ids are drawn from
that covered range — stated in the report rather than silently ignored.

Read-only on `meta.sqlite`.

    .venv/bin/python3 spike/meta_consolidation/10_n4_postfilter_parity.py
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sqlite3
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "source"))

META = ROOT / "data" / "thinclient_index" / "meta.sqlite"
WORK = Path(__file__).parent / "work_ordinals"
log = logging.getLogger("n4")


class ProductionFilter:
    """retriever._meta_rows + _post_filter, reproduced exactly (retriever.py
    :988-1044). Same chunking, same column order, same predicate order."""

    def __init__(self, cache_mb: int = 64):
        self.db = sqlite3.connect(f"file:{META}?mode=ro", uri=True,
                                  check_same_thread=False)
        if cache_mb:
            self.db.execute(f"PRAGMA cache_size=-{cache_mb * 1024}")

    def post_filter(self, ranked: list[tuple[str, float]], f: dict):
        ids = [d for d, _ in ranked]
        rows = {}
        from lib.thinclient.builder import encode_meta_id
        enc, other = {}, []
        for s in ids:
            n = encode_meta_id(s)
            (other.append(s) if n is None else enc.__setitem__(n, s))

        def _q(table, keys, back):
            for st in range(0, len(keys), 500):
                chunk = keys[st:st + 500]
                marks = ",".join("?" * len(chunk))
                for row in self.db.execute(
                        f"SELECT id, title, doi, year, type, is_oa, section "
                        f"FROM {table} WHERE id IN ({marks})", chunk):
                    did = back[row[0]] if back is not None else row[0]
                    rows[did] = (did,) + tuple(row[1:])

        if enc:
            _q("docs", list(enc), enc)
        if other:
            _q("docs_other", other, None)

        keep = []
        for did, score in ranked:
            row = rows.get(did)
            if row is None:
                continue
            _, _, _, year, dtype, is_oa, _ = row
            if f.get("year_range"):
                lo, hi = f["year_range"]
                if not (year and lo <= year <= hi):
                    continue
            if f.get("type") and dtype != f["type"]:
                continue
            if f.get("is_oa") and not is_oa:
                continue
            keep.append((did, score))
        return keep


class OrdinalFilter:
    """The ordinal path: binary search, then a vectorised mask."""

    def __init__(self, work: Path):
        self.wids = np.load(work / "wids.npy", mmap_mode="r")
        self.year = np.load(work / "year.npy", mmap_mode="r")
        self.dtype = np.load(work / "dtype.npy", mmap_mode="r")
        self.is_oa = np.load(work / "is_oa.npy", mmap_mode="r")
        codes = json.loads((work / "codes.json").read_text())
        self.type_codes = codes["type"]
        self.n = codes["rows"]

    def post_filter(self, ranked: list[tuple[str, float]], f: dict):
        # W-id string -> numeric, mirroring builder.encode_meta_id
        nums = np.fromiter((int(d[1:]) for d, _ in ranked),
                           dtype=np.int64, count=len(ranked))
        pos = np.searchsorted(self.wids, nums)
        pos_c = np.clip(pos, 0, self.n - 1)
        found = self.wids[pos_c] == nums          # reject ids not in the index

        ok = found.copy()
        if f.get("year_range"):
            lo, hi = f["year_range"]
            y = self.year[pos_c]
            ok &= (y >= lo) & (y <= hi) & (y != 0)
        if f.get("type"):
            code = self.type_codes.get(f["type"], -999)
            ok &= self.dtype[pos_c] == code
        if f.get("is_oa"):
            ok &= self.is_oa[pos_c] != 0
        # rank order preserved: ranked is walked in order, mask applied in place
        return [ranked[i] for i in np.flatnonzero(ok)]


def timeit(fn, args_list, reps, warmup):
    for i in range(warmup):
        fn(*args_list[i % len(args_list)])
    s = []
    for i in range(reps):
        t0 = time.perf_counter()
        fn(*args_list[i % len(args_list)])
        s.append((time.perf_counter() - t0) * 1000)
    s.sort()
    return {"reps": reps, "p50_ms": round(statistics.median(s), 3),
            "min_ms": round(s[0], 3), "max_ms": round(s[-1], 3)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--sizes", type=int, nargs="+", default=[100, 500, 1000, 2000])
    ap.add_argument("--reps", type=int, default=9)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--gate-trials", type=int, default=200)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")

    ordinal = OrdinalFilter(args.work)
    prod = ProductionFilter()
    covered = int(ordinal.n)
    log.info("ordinal artifacts cover %d docs (id range %d..%d)",
             covered, int(ordinal.wids[0]), int(ordinal.wids[-1]))

    rng = random.Random(args.seed)
    FILTERS = {
        "year_only": {"year_range": (2010, 2025)},
        "year_type": {"year_range": (2010, 2025), "type": "article"},
        "year_type_oa": {"year_range": (2010, 2025), "type": "article", "is_oa": 1},
    }

    rep = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "ordinal_docs_covered": covered,
           "note": "candidate ids drawn from the ordinal-covered id range",
           "filters": FILTERS, "gate": {}, "bench": {}}

    def make_ranked(k):
        idx = rng.sample(range(covered), k)
        return [("W" + str(int(ordinal.wids[i])), 1.0 / (r + 1))
                for r, i in enumerate(sorted(idx))]

    # ── parity gate ──────────────────────────────────────────────────────────
    all_ok = True
    for fname, f in FILTERS.items():
        mismatches = 0
        for _ in range(args.gate_trials):
            ranked = make_ranked(rng.choice([50, 200, 1000]))
            a = prod.post_filter(ranked, f)
            b = ordinal.post_filter(ranked, f)
            if a != b:                      # list equality: ids, scores AND order
                mismatches += 1
        ok = mismatches == 0
        all_ok &= ok
        rep["gate"][fname] = {"trials": args.gate_trials, "mismatches": mismatches,
                              "pass": ok}
        log.info("PARITY %-14s %s (%d trials, %d mismatches)",
                 fname, "PASS" if ok else "FAIL", args.gate_trials, mismatches)
    rep["gate_overall_pass"] = all_ok

    # ── latency ──────────────────────────────────────────────────────────────
    f = FILTERS["year_type_oa"]
    for k in args.sizes:
        need = args.reps + args.warmup
        lists = [(make_ranked(k), f) for _ in range(need)]
        p = timeit(prod.post_filter, lists, args.reps, args.warmup)
        o = timeit(ordinal.post_filter, lists, args.reps, args.warmup)
        e = {"production_sqlite": p, "ordinal": o,
             "speedup": round(p["p50_ms"] / o["p50_ms"], 1) if o["p50_ms"] else None}
        rep["bench"][str(k)] = e
        log.info("k=%-5d production %8.2f ms | ordinal %7.3f ms | %sx",
                 k, p["p50_ms"], o["p50_ms"], e["speedup"])

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"n4_postfilter_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    log.info("results -> %s  (gate %s)", out, "PASS" if all_ok else "FAIL")


if __name__ == "__main__":
    main()
