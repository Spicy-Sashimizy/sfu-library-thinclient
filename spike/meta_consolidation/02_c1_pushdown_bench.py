#!/usr/bin/env python3
"""C1 spike, part 2 — test C1's ACTUAL claim, not the weaker reading of it.

`01_c1_lookup_bench.py` measured C1 as a *metadata-lookup replacement*: fetch
the same rows tantivy-side instead of SQLite-side, then filter in Python
exactly as today. C1 lost 3.6-6.7x there. But that is the weaker reading of
what C1 proposed. The stronger one, and the one actually written down, is:

    "removes SQLite from the hot path AND the Python post-filter mask on both
     approximate legs"

Removing the *mask* means the filter stops being a Python loop over fetched
rows and becomes part of the tantivy query -- a `Must` conjunction of
`term_set_query(id, candidates)` with the filter predicates. Then the hits ARE
the survivors, no rows are fetched for documents that fail the filter, and the
work scales with the surviving set rather than the candidate set.

That is a genuinely different algorithm from what part 1 timed, and part 1's
verdict does not cover it. This script times it.

Three arms, same ids, same filter, same corpus:

  sqlite_postfilter   production today: retriever._meta_rows + _post_filter
  tantivy_lookup      part 1's arm: fan-out, fetch rows, filter in Python
  tantivy_pushdown    C1 proper: filter inside the query, fetch only survivors

Also fixes two methodology gaps in part 1:

  * **fast fields were declared but never read.** Part 1 called `searcher.doc()`
    (row-oriented stored docstore) for every hit. `Searcher.fast_field_values`
    does batched columnar reads and is what "stored + fast fields" was supposed
    to mean. Timed here as `--hydrate fast`.
  * **warm-cache bias.** Part 1 reused one id list across all repetitions, so
    both arms ran fully warm. `--fresh-ids` draws a new sample per repetition.

Writes ONLY under this spike's `work/` dir; reads the stores built by part 1.

    .venv/bin/python3 spike/meta_consolidation/02_c1_pushdown_bench.py
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
sys.path.insert(0, str(ROOT / "src"))

sys.path.insert(0, str(Path(__file__).parent))
from importlib import import_module  # noqa: E402

_p1 = import_module("01_c1_lookup_bench")
SECTIONS = _p1.SECTIONS
encode_meta_id = _p1.encode_meta_id

log = logging.getLogger("c1pushdown")

# A filter with realistic selectivity. synth_meta spreads year uniformly over
# 1990-2025, type over 4 values, is_oa 50/50 -> this keeps ~ (16/36)*(1/4)*(1/2)
# = ~5.6% of candidates, the shape of a genuinely selective library filter.
FILTERS = {
    "selective":  {"year_range": (2010, 2025), "type": "article", "is_oa": 1},
    "loose":      {"year_range": (1990, 2025)},
}


class SqlitePostFilter:
    """Production today: batched PK fetch, then the Python mask."""

    def __init__(self, path: Path, cache_mb: int = 64):
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True,
                                  check_same_thread=False)
        if cache_mb:
            self.db.execute(f"PRAGMA cache_size=-{cache_mb * 1024}")

    def survivors(self, ids: list[str], f: dict) -> set[str]:
        rows: dict[str, tuple] = {}
        enc: dict[int, str] = {}
        other: list[str] = []
        for s in ids:
            n = encode_meta_id(s)
            (other.append(s) if n is None else enc.__setitem__(n, s))

        def _query(table: str, keys: list, back: dict | None) -> None:
            for start in range(0, len(keys), 500):
                chunk = keys[start:start + 500]
                marks = ",".join("?" * len(chunk))
                for row in self.db.execute(
                        f"SELECT id, year, type, is_oa FROM {table} "
                        f"WHERE id IN ({marks})", chunk):
                    did = back[row[0]] if back is not None else row[0]
                    rows[did] = row

        if enc:
            _query("docs", list(enc), enc)
        if other:
            _query("docs_other", other, None)

        keep = set()
        for did, row in rows.items():
            _, year, dtype, is_oa = row
            if f.get("year_range"):
                lo, hi = f["year_range"]
                if not (year and lo <= year <= hi):
                    continue
            if f.get("type") and dtype != f["type"]:
                continue
            if f.get("is_oa") and not is_oa:
                continue
            keep.add(did)
        return keep


class TantivyArm:
    def __init__(self, root: Path):
        import tantivy
        self.tantivy = tantivy
        self.sections = {}
        for s in SECTIONS:
            idx = tantivy.Index.open(str(root / s))
            idx.reload()
            self.sections[s] = {"searcher": idx.searcher(), "schema": idx.schema}

    # -- part 1's algorithm: fetch everything, filter in Python ---------------
    def lookup_then_filter(self, ids: list[str], f: dict,
                           hydrate: str = "stored") -> set[str]:
        keep = set()
        limit = len(ids)
        for h in self.sections.values():
            q = self.tantivy.Query.term_set_query(h["schema"], "id", ids)
            hits = h["searcher"].search(q, limit).hits
            if not hits:
                continue
            addrs = [a for _s, a in hits]
            if hydrate == "fast":
                # Columnar batch reads for the numerics. `id` and `doctype` are
                # text, which fast_field_values does not support, so the id
                # still costs one stored read per hit -- that limit is the
                # finding, not a bug in this arm.
                years = h["searcher"].fast_field_values("year", addrs)
                oas = h["searcher"].fast_field_values("is_oa", addrs)
                for i, a in enumerate(addrs):
                    doc = h["searcher"].doc(a)
                    if not _passes(years[i], doc["doctype"][0], oas[i], f):
                        continue
                    keep.add(doc["id"][0])
            else:
                for a in addrs:
                    doc = h["searcher"].doc(a)
                    if not _passes(doc["year"][0], doc["doctype"][0],
                                   doc["is_oa"][0], f):
                        continue
                    keep.add(doc["id"][0])
        return keep

    # -- C1 proper: the filter IS the query ----------------------------------
    def pushdown(self, ids: list[str], f: dict) -> set[str]:
        T = self.tantivy
        Occur = T.Occur
        keep = set()
        limit = len(ids)
        for h in self.sections.values():
            schema = h["schema"]
            subs = [(Occur.Must, T.Query.term_set_query(schema, "id", ids))]
            if f.get("year_range"):
                lo, hi = f["year_range"]
                subs.append((Occur.Must, T.Query.range_query(
                    schema, "year", T.FieldType.Integer, lo, hi)))
            if f.get("type"):
                subs.append((Occur.Must, T.Query.term_query(
                    schema, "doctype", f["type"])))
            if f.get("is_oa"):
                subs.append((Occur.Must, T.Query.term_query(
                    schema, "is_oa", 1)))
            q = T.Query.boolean_query(subs)
            for _s, a in h["searcher"].search(q, limit).hits:
                keep.add(h["searcher"].doc(a)["id"][0])
        return keep


def _passes(year, dtype, is_oa, f: dict) -> bool:
    if f.get("year_range"):
        lo, hi = f["year_range"]
        if not (year and lo <= year <= hi):
            return False
    if f.get("type") and dtype != f["type"]:
        return False
    if f.get("is_oa") and not is_oa:
        return False
    return True


def timeit(fn, id_lists: list[list[str]], reps: int, warmup: int) -> dict:
    for i in range(warmup):
        fn(id_lists[i % len(id_lists)])
    samples = []
    for i in range(reps):
        ids = id_lists[i % len(id_lists)]
        t0 = time.perf_counter()
        fn(ids)
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    return {"reps": reps,
            "p50_ms": round(statistics.median(samples), 3),
            "mean_ms": round(statistics.fmean(samples), 3),
            "p95_ms": round(samples[min(len(samples) - 1,
                                        int(0.95 * len(samples)))], 3),
            "min_ms": round(samples[0], 3), "max_ms": round(samples[-1], 3)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    here = Path(__file__).parent
    ap.add_argument("--corpus", type=Path,
                    default=ROOT / "spike" / "bm25_seismic" / "work" / "corpus.jsonl")
    ap.add_argument("--work", type=Path, default=here / "work")
    ap.add_argument("--sizes", type=int, nargs="+", default=[100, 500, 1000, 2000])
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--fresh-ids", action="store_true",
                    help="draw a new id sample per repetition (kills warm-cache bias)")
    ap.add_argument("--sqlite-cache-mb", type=int, default=64)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")

    sqlite_path = args.work / "meta.sqlite"
    tantivy_root = args.work / "tantivy_meta"
    if not sqlite_path.exists() or not tantivy_root.exists():
        ap.error("stores missing — run 01_c1_lookup_bench.py --build first")

    all_ids = [rec["id"] for rec in _p1.iter_corpus(args.corpus)]
    rng = random.Random(args.seed)
    sql = SqlitePostFilter(sqlite_path, args.sqlite_cache_mb)
    tv = TantivyArm(tantivy_root)

    report = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "corpus": str(args.corpus), "seed": args.seed,
              "fresh_ids_per_rep": args.fresh_ids,
              "sqlite_cache_mb": args.sqlite_cache_mb,
              "sections": len(SECTIONS), "filters": FILTERS, "results": {}}

    for fname, f in FILTERS.items():
        report["results"][fname] = {}
        for size in args.sizes:
            n_lists = (args.reps + args.warmup) if args.fresh_ids else 1
            id_lists = [rng.sample(all_ids, size) for _ in range(n_lists)]
            probe = id_lists[0]

            # Correctness gate: all three arms must agree on the survivor set.
            a_set = sql.survivors(probe, f)
            b_set = tv.lookup_then_filter(probe, f, "stored")
            c_set = tv.pushdown(probe, f)
            d_set = tv.lookup_then_filter(probe, f, "fast")
            parity = {"sqlite_survivors": len(a_set),
                      "selectivity": round(len(a_set) / size, 4),
                      "lookup_matches": a_set == b_set,
                      "pushdown_matches": a_set == c_set,
                      "fastfield_matches": a_set == d_set}
            if not all((parity["lookup_matches"], parity["pushdown_matches"],
                        parity["fastfield_matches"])):
                log.warning("PARITY FAIL %s size=%d: %s", fname, size, parity)

            arms = {
                "sqlite_postfilter": timeit(
                    lambda i: sql.survivors(i, f), id_lists, args.reps, args.warmup),
                "tantivy_lookup_stored": timeit(
                    lambda i: tv.lookup_then_filter(i, f, "stored"),
                    id_lists, args.reps, args.warmup),
                "tantivy_lookup_fastfield": timeit(
                    lambda i: tv.lookup_then_filter(i, f, "fast"),
                    id_lists, args.reps, args.warmup),
                "tantivy_pushdown": timeit(
                    lambda i: tv.pushdown(i, f), id_lists, args.reps, args.warmup),
            }
            base = arms["sqlite_postfilter"]["p50_ms"]
            ratios = {k: (round(v["p50_ms"] / base, 2) if base else None)
                      for k, v in arms.items()}
            report["results"][fname][str(size)] = {
                "parity": parity, "arms": arms, "vs_sqlite": ratios}
            log.info("%-10s size=%-5d sel=%.1f%% | sqlite %.2f | lookup %.2f | "
                     "fastfield %.2f | pushdown %.2f ms  (pushdown %sx sqlite)",
                     fname, size, 100 * parity["selectivity"], base,
                     arms["tantivy_lookup_stored"]["p50_ms"],
                     arms["tantivy_lookup_fastfield"]["p50_ms"],
                     arms["tantivy_pushdown"]["p50_ms"],
                     ratios["tantivy_pushdown"])

    tag = "freshids" if args.fresh_ids else "warm"
    out = args.out or (ROOT / "data" / "eval_results" /
                       f"c1_pushdown_{tag}_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    log.info("results -> %s", out)


if __name__ == "__main__":
    main()
