#!/usr/bin/env python3
"""C1 spike, part 3 — the only measurement that actually decides C1.

Parts 1 and 2 ran on a 207,973-doc spike corpus whose metadata DB is 39 MB.
That fits entirely in RAM, so BOTH arms were served from page cache and the
comparison measured CPU, not the storage hierarchy. Production is not like
that:

    data/thinclient_index/meta.sqlite            24.9 GB
    sections/<name>/tantivy                       4.1 GB each x 10

At that size a random candidate list misses cache on essentially every id, and
the ranking between the two arms is decided by how many cold page faults each
one takes -- which is exactly what the spike could not see. Measured on the
production DB 2026-08-02: 398 ms for 1000 ids, vs the spike's 4.15 ms. A 96x
gap between spike and production on the SAME code path means spike-scale
numbers cannot be extrapolated in either direction.

So this script re-runs the C1 comparison against the REAL index:

  sqlite_postfilter   production meta.sqlite (24.9 GB), retriever._meta_rows shape
  tantivy_fanout      term_set_query on `id` across the 10 REAL section indexes

Everything is opened READ-ONLY. `meta.sqlite` via `mode=ro`; the tantivy
sections via `tantivy.Index.open`, which is the identical call
`retriever._load` already makes at line 378 -- this adds no access the serving
path does not already perform. Nothing under `data/` is written.

    .venv/bin/python3 spike/meta_consolidation/03_c1_production_scale.py
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "source"))

log = logging.getLogger("c1prod")

INDEX = ROOT / "data" / "thinclient_index"
SECTIONS = ["cs_math__archive", "cs_math__recent", "med_bio__archive",
            "med_bio__recent", "other__archive", "other__recent",
            "phys_eng__archive", "phys_eng__recent",
            "social_sciences__archive", "social_sciences__recent"]


def sample_real_ids(db: sqlite3.Connection, want: int, seed: int,
                    budget_s: float = 600.0) -> list[int]:
    """Random EXISTING rowids, found by probing the PK rather than scanning.

    `SELECT ... LIMIT n OFFSET random` would scan a 24.9 GB table; probing
    random integers in [min,max] and keeping the hits costs one PK lookup each.
    """
    lo = db.execute("SELECT min(id) FROM docs").fetchone()[0]
    hi = db.execute("SELECT max(id) FROM docs").fetchone()[0]
    rng = random.Random(seed)
    found: list[int] = []
    t0 = time.perf_counter()
    while len(found) < want and time.perf_counter() - t0 < budget_s:
        cand = [rng.randint(lo, hi) for _ in range(2000)]
        marks = ",".join("?" * len(cand))
        found += [r[0] for r in db.execute(
            f"SELECT id FROM docs WHERE id IN ({marks})", cand)]
    log.info("sampled %d real ids in %.1fs (rowid range %d..%d)",
             len(found), time.perf_counter() - t0, lo, hi)
    return found[:want]


class ProdSqlite:
    def __init__(self, cache_mb: int):
        self.db = sqlite3.connect(
            f"file:{INDEX / 'meta.sqlite'}?mode=ro", uri=True,
            check_same_thread=False)
        if cache_mb:
            self.db.execute(f"PRAGMA cache_size=-{cache_mb * 1024}")

    def rows(self, int_ids: list[int]) -> dict:
        out = {}
        for s in range(0, len(int_ids), 500):
            chunk = int_ids[s:s + 500]
            marks = ",".join("?" * len(chunk))
            for r in self.db.execute(
                    f"SELECT id, year, type, is_oa FROM docs "
                    f"WHERE id IN ({marks})", chunk):
                out[r[0]] = r
        return out


class ProdTantivy:
    def __init__(self, sections: list[str]):
        import tantivy
        self.tantivy = tantivy
        self.sections = {}
        for s in sections:
            p = INDEX / "sections" / s / "tantivy"
            if not p.exists():
                log.warning("missing section index: %s", p)
                continue
            idx = tantivy.Index.open(str(p))   # same call as retriever._load:378
            idx.reload()
            self.sections[s] = {"searcher": idx.searcher(), "schema": idx.schema}
        log.info("opened %d production section indexes", len(self.sections))

    def rows(self, str_ids: list[str]) -> dict:
        out = {}
        limit = len(str_ids)
        for h in self.sections.values():
            q = self.tantivy.Query.term_set_query(h["schema"], "id", str_ids)
            for _s, a in h["searcher"].search(q, limit).hits:
                out[h["searcher"].doc(a)["id"][0]] = True
        return out


def timeit(fn, id_lists, reps, warmup):
    for i in range(warmup):
        fn(id_lists[i % len(id_lists)])
    s = []
    for i in range(reps):
        t0 = time.perf_counter()
        fn(id_lists[i % len(id_lists)])
        s.append((time.perf_counter() - t0) * 1000)
    s.sort()
    return {"reps": reps, "p50_ms": round(statistics.median(s), 2),
            "mean_ms": round(statistics.fmean(s), 2),
            "min_ms": round(s[0], 2), "max_ms": round(s[-1], 2)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sizes", type=int, nargs="+", default=[100, 500, 1000])
    ap.add_argument("--reps", type=int, default=7)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--pool", type=int, default=20000,
                    help="how many real ids to sample. Must be >> sizes*reps or "
                         "reps overlap and the arms warm each other up")
    ap.add_argument("--cache-mb", type=int, nargs="+", default=[0, 64, 1024])
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")

    probe = sqlite3.connect(f"file:{INDEX / 'meta.sqlite'}?mode=ro", uri=True)
    pool = sample_real_ids(probe, args.pool, args.seed)
    probe.close()
    if len(pool) < max(args.sizes) * 2:
        ap.error(f"only sampled {len(pool)} ids; need >= {max(args.sizes)*2}")

    tv = ProdTantivy(SECTIONS)
    report = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "meta_sqlite_bytes": (INDEX / "meta.sqlite").stat().st_size,
              "sections_opened": len(tv.sections), "pool_ids": len(pool),
              "seed": args.seed, "results": {}}

    rng = random.Random(args.seed + 1)
    for size in args.sizes:
        need = args.reps + args.warmup
        if len(pool) >= size * need:
            # Disjoint slices: no id is reused across reps, so nothing warms.
            picks = rng.sample(pool, size * need)
            id_lists = [picks[i * size:(i + 1) * size] for i in range(need)]
            disjoint = True
        else:
            id_lists = [rng.sample(pool, size) for _ in range(need)]
            disjoint = False
        str_lists = [["W" + str(i) for i in L] for L in id_lists]

        entry = {"disjoint_reps": disjoint, "sqlite": {}}
        for cache_mb in args.cache_mb:
            sq = ProdSqlite(cache_mb)
            r = timeit(sq.rows, id_lists, args.reps, args.warmup)
            entry["sqlite"][f"cache_{cache_mb}mb"] = r
            log.info("size=%-5d sqlite cache=%-5s p50=%9.2f ms (min %.2f max %.2f)",
                     size, f"{cache_mb}MB", r["p50_ms"], r["min_ms"], r["max_ms"])

        rt = timeit(tv.rows, str_lists, args.reps, args.warmup)
        entry["tantivy_fanout"] = rt
        log.info("size=%-5d tantivy x%d fan-out  p50=%9.2f ms (min %.2f max %.2f)",
                 size, len(tv.sections), rt["p50_ms"], rt["min_ms"], rt["max_ms"])

        # Coverage sanity: how many of the requested ids each arm actually found.
        sq = ProdSqlite(args.cache_mb[-1])
        entry["coverage"] = {"requested": size,
                             "sqlite_found": len(sq.rows(id_lists[0])),
                             "tantivy_found": len(tv.rows(str_lists[0]))}
        log.info("size=%-5d coverage: %s", size, entry["coverage"])

        best = min(v["p50_ms"] for v in entry["sqlite"].values())
        entry["tantivy_over_best_sqlite"] = (round(rt["p50_ms"] / best, 2)
                                             if best else None)
        report["results"][str(size)] = entry

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"c1_production_scale_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    log.info("results -> %s", out)


if __name__ == "__main__":
    main()
