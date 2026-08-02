#!/usr/bin/env python3
"""C5 research spike — can Lance replace `meta.sqlite` as the key->row store?

Doc 17 §9 surveyed LanceDB and parked it: "the best structural fit for a static
thin-client index **if issue #1930 ever lands**". Re-checked 2026-08-02: #1930
(sparse vectors / SPLADE) is still OPEN, so Lance cannot host the SPLADE leg and
SEISMIC stays either way. That makes §9's all-or-nothing framing the wrong
question.

The right question, given §10-§11: those sections established that the whole
consolidation programme turns on ONE property --

    a SQLite PK hit costs ~0.4 ms/id at 150M rows;
    tantivy's term-dictionary lookup for the same ids costs 27-60x more.

tantivy lost because an fst traversal is not a key->row index. Lance's entire
design claim is random access in columnar storage, via BTREE scalar indexes --
structurally what SQLite's PK gives and what tantivy's fst does not. So Lance
could plausibly absorb the STORAGE roles (metadata, abstracts, locator,
dense/ids.json, dense vectors) even though it cannot absorb the SPLADE leg:

    today          tantivy . SQLite(x3) . usearch . SEISMIC   = 4 technologies
    Lance variant  tantivy . Lance      . SEISMIC             = 3

This script measures the one number that decides it: **Lance key lookup vs
SQLite PK lookup, same rows, same machine.** Vendor benchmarks compare Lance to
Parquet, which is a scan-optimised format and a meaningless baseline for point
lookups; and Lance's own docs warn that without a secondary index "scanning
through the key column ... adds more than 10 ms".

Scale honesty (the lesson of §10.3, where spike-scale was 96x off production):
building a 150M-row / 24.9 GB Lance dataset is not affordable here, so both
stores are built at the SAME reduced row count and only the RATIO is claimed.
Absolute latencies will be optimistic for BOTH arms because a smaller dataset
sits in page cache. The ratio is the transferable quantity; it is applied to the
measured production SQLite number as an explicitly-labelled projection.

Schema mirrors production: `docs.id` is INTEGER (docs_other measured empty at
150M, §10.3), so the key is int64 in both arms.

    spike/meta_consolidation/.venv-lance/bin/python \
        spike/meta_consolidation/05_lance_vs_sqlite_lookup.py --rows 20000000 --build --bench
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sqlite3
import statistics
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).parent / "work_lance"

DOCTYPES = ["article", "preprint", "book-chapter", "dataset"]
SECTIONS = ["cs_math__archive", "cs_math__recent", "med_bio__archive",
            "med_bio__recent", "other__archive", "other__recent",
            "phys_eng__archive", "phys_eng__recent",
            "social_sciences__archive", "social_sciences__recent"]

META_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
  id INTEGER PRIMARY KEY, title TEXT, doi TEXT, year INTEGER,
  type TEXT, is_oa INTEGER, section TEXT);
"""


def gen_batch(start: int, n: int, rng: random.Random):
    """One arrow-ready batch of production-shaped metadata rows."""
    ids, titles, dois, years, types, oas, secs = [], [], [], [], [], [], []
    for i in range(start, start + n):
        # ids are sparse like real W-ids (production max ~7.14e9 over 150M rows)
        did = i * 47 + 108
        ids.append(did)
        titles.append(f"Study {did} on the effects of factor {did % 997} "
                      f"in controlled settings across multiple cohorts")
        dois.append(f"10.{1000 + did % 9000}/w{did}")
        years.append(1990 + did % 36)
        types.append(DOCTYPES[did % 4])
        oas.append(did & 1)
        secs.append(SECTIONS[did % 10])
    return ids, titles, dois, years, types, oas, secs


def build_sqlite(path: Path, rows: int, batch: int = 500_000) -> dict:
    if path.exists():
        path.unlink()
    db = sqlite3.connect(str(path))
    db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + META_SCHEMA)
    rng = random.Random(0)
    t0 = time.perf_counter()
    done = 0
    while done < rows:
        n = min(batch, rows - done)
        ids, titles, dois, years, types, oas, secs = gen_batch(done, n, rng)
        db.executemany("INSERT INTO docs VALUES (?,?,?,?,?,?,?)",
                       zip(ids, titles, dois, years, types, oas, secs))
        done += n
        print(f"  sqlite {done:,}/{rows:,}", flush=True)
    db.commit()
    db.close()
    return {"path": str(path), "rows": rows,
            "build_s": round(time.perf_counter() - t0, 1),
            "bytes": path.stat().st_size}


def build_lance(path: Path, rows: int, batch: int = 500_000) -> dict:
    import lance
    import pyarrow as pa
    if path.exists():
        shutil.rmtree(path)
    schema = pa.schema([("id", pa.int64()), ("title", pa.string()),
                        ("doi", pa.string()), ("year", pa.int32()),
                        ("type", pa.string()), ("is_oa", pa.int8()),
                        ("section", pa.string())])
    rng = random.Random(0)
    t0 = time.perf_counter()
    done, ds = 0, None
    while done < rows:
        n = min(batch, rows - done)
        ids, titles, dois, years, types, oas, secs = gen_batch(done, n, rng)
        tbl = pa.table({"id": ids, "title": titles, "doi": dois, "year": years,
                        "type": types, "is_oa": oas, "section": secs},
                       schema=schema)
        ds = lance.write_dataset(tbl, str(path),
                                 mode="overwrite" if done == 0 else "append")
        done += n
        print(f"  lance {done:,}/{rows:,}", flush=True)
    build_s = time.perf_counter() - t0
    t1 = time.perf_counter()
    ds.create_scalar_index("id", index_type="BTREE")
    idx_s = time.perf_counter() - t1
    size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return {"path": str(path), "rows": rows, "build_s": round(build_s, 1),
            "btree_index_s": round(idx_s, 1), "bytes": size}


class SqliteArm:
    def __init__(self, path: Path, cache_mb: int = 64):
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        if cache_mb:
            self.db.execute(f"PRAGMA cache_size=-{cache_mb*1024}")

    def rows(self, ids):
        out = {}
        for s in range(0, len(ids), 500):
            c = ids[s:s+500]
            m = ",".join("?" * len(c))
            for r in self.db.execute(
                    f"SELECT id, year, type, is_oa FROM docs WHERE id IN ({m})", c):
                out[r[0]] = r
        return out


class LanceArm:
    def __init__(self, path: Path):
        import lance
        self.ds = lance.dataset(str(path))

    def rows(self, ids):
        lst = ",".join(str(i) for i in ids)
        t = self.ds.to_table(columns=["id", "year", "type", "is_oa"],
                             filter=f"id IN ({lst})")
        return {r["id"]: r for r in t.to_pylist()}


def timeit(fn, lists, reps, warmup):
    for i in range(warmup):
        fn(lists[i % len(lists)])
    s = []
    for i in range(reps):
        t0 = time.perf_counter()
        fn(lists[i % len(lists)])
        s.append((time.perf_counter() - t0) * 1000)
    s.sort()
    return {"reps": reps, "p50_ms": round(statistics.median(s), 2),
            "mean_ms": round(statistics.fmean(s), 2),
            "min_ms": round(s[0], 2), "max_ms": round(s[-1], 2)}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=int, default=20_000_000)
    ap.add_argument("--sizes", type=int, nargs="+", default=[100, 1000])
    ap.add_argument("--reps", type=int, default=9)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    WORK.mkdir(parents=True, exist_ok=True)
    sq_path, ln_path = WORK / "meta.sqlite", WORK / "meta.lance"
    report = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": args.rows,
              "note": "ratio is the claim; absolute ms optimistic vs 150M production"}

    if args.build:
        print("building lance…", flush=True)
        report["lance_build"] = build_lance(ln_path, args.rows)
        print(report["lance_build"], flush=True)
        print("building sqlite…", flush=True)
        report["sqlite_build"] = build_sqlite(sq_path, args.rows)
        print(report["sqlite_build"], flush=True)
        (WORK / "build_report.json").write_text(json.dumps(report, indent=2))

    if not args.bench:
        return

    sq, ln = SqliteArm(sq_path), LanceArm(ln_path)
    rng = random.Random(args.seed)
    report["results"] = {}
    for size in args.sizes:
        need = args.reps + args.warmup
        lists = [[rng.randrange(args.rows) * 47 + 108 for _ in range(size)]
                 for _ in range(need)]
        a, b = sq.rows(lists[0]), ln.rows(lists[0])
        parity = {"sqlite_rows": len(a), "lance_rows": len(b),
                  "same_ids": set(a) == set(b)}
        e = {"parity": parity,
             "sqlite": timeit(sq.rows, lists, args.reps, args.warmup),
             "lance": timeit(ln.rows, lists, args.reps, args.warmup)}
        e["lance_over_sqlite"] = (round(e["lance"]["p50_ms"] / e["sqlite"]["p50_ms"], 2)
                                  if e["sqlite"]["p50_ms"] else None)
        report["results"][str(size)] = e
        print(f"k={size:<5} sqlite {e['sqlite']['p50_ms']:8.2f} ms | "
              f"lance {e['lance']['p50_ms']:8.2f} ms | lance/sqlite "
              f"{e['lance_over_sqlite']}x | parity {parity['same_ids']}", flush=True)

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"c5_lance_vs_sqlite_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print("results ->", out, flush=True)


if __name__ == "__main__":
    main()
