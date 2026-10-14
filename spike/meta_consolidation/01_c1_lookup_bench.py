#!/usr/bin/env python3
"""C1 spike — is `id -> DocId` via tantivy cheap enough to retire meta.sqlite?

C1 (see docs/seismic_150m_testbed/17_BM25_THROUGH_SEISMIC_SPIKE.md) proposes
moving the metadata rows out of `meta.sqlite` and into tantivy stored + fast
fields, which would remove SQLite from the hot path AND remove the Python
post-filter mask that both approximate legs (SEISMIC, usearch) are forced
through today.

The assumption most likely to break, and the ONLY thing this script measures:

    today  one SQLite PK hit per id, batched 500-at-a-time (retriever._meta_rows)
    C1     one `term_set_query` on the raw `id` field per SECTION -- x10, because
           a ranked list from an approximate leg is not section-partitioned, so
           every section index must be asked for every id

Two workloads, because they cost differently and C1 needs both:

  filter  year/type/is_oa only -- the post-filter mask. The hot one: it runs on
          EVERY approximate-leg query, over the over-fetched candidate list.
  hydrate full row (title/doi/year/type/is_oa/section) -- runs once per query on
          the final top-k.

Writes ONLY under this spike's `work/` dir. `data/thinclient_index/` is never
opened, not even read-only; the serving index is untouched.

    .venv/bin/python3 spike/meta_consolidation/01_c1_lookup_bench.py --build
    .venv/bin/python3 spike/meta_consolidation/01_c1_lookup_bench.py --bench
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import shutil
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "source"))

from lib.thinclient.builder import encode_meta_id  # noqa: E402

log = logging.getLogger("c1bench")

# The production section set (data/thinclient_index/sections/), so the fan-out
# factor is the real one rather than a round number.
SECTIONS = [
    "cs_math__archive", "cs_math__recent",
    "med_bio__archive", "med_bio__recent",
    "other__archive", "other__recent",
    "phys_eng__archive", "phys_eng__recent",
    "social_sciences__archive", "social_sciences__recent",
]

# meta.sqlite's schema, copied from builder.META_SCHEMA's shape (v2: INTEGER PK
# + a TEXT docs_other overflow table).
META_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
  id INTEGER PRIMARY KEY, title TEXT, doi TEXT, year INTEGER,
  type TEXT, is_oa INTEGER, section TEXT);
CREATE TABLE IF NOT EXISTS docs_other (
  id TEXT PRIMARY KEY, title TEXT, doi TEXT, year INTEGER,
  type TEXT, is_oa INTEGER, section TEXT);
"""

DOCTYPES = ["article", "preprint", "book-chapter", "dataset"]


def iter_corpus(path: Path):
    with open(path) as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def synth_meta(doc_id: str, title: str) -> dict:
    """Deterministic stand-in metadata.

    The spike corpus carries only id/title/abstract. What this script times is
    the COST of the lookup -- rows touched, index probes, fan-out -- which
    depends on row shape and cardinality, not on the values being real. Derived
    from a hash of the id so a rebuild reproduces byte-identical rows.
    """
    h = int(hashlib.blake2b(doc_id.encode(), digest_size=8).hexdigest(), 16)
    return {
        "id": doc_id,
        "title": title,
        "doi": f"10.{1000 + h % 9000}/{doc_id.lower()}",
        "year": 1990 + h % 36,
        "type": DOCTYPES[h % len(DOCTYPES)],
        "is_oa": (h >> 7) & 1,
        "section": SECTIONS[h % len(SECTIONS)],
    }


def dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


# ── build ────────────────────────────────────────────────────────────────────

def build_sqlite(corpus: Path, out: Path) -> dict:
    """The baseline: today's meta.sqlite, same schema, same v2 id encoding."""
    if out.exists():
        out.unlink()
    for suf in ("-wal", "-shm"):
        p = out.with_name(out.name + suf)
        if p.exists():
            p.unlink()
    db = sqlite3.connect(str(out))
    db.executescript(META_SCHEMA)
    t0 = time.perf_counter()
    n_int = n_txt = 0
    batch_int: list[tuple] = []
    batch_txt: list[tuple] = []
    for rec in iter_corpus(corpus):
        m = synth_meta(rec["id"], rec["title"])
        row = (m["title"], m["doi"], m["year"], m["type"], m["is_oa"], m["section"])
        enc = encode_meta_id(m["id"])
        if enc is None:
            batch_txt.append((m["id"],) + row)
        else:
            batch_int.append((enc,) + row)
        if len(batch_int) >= 10_000:
            db.executemany("INSERT OR REPLACE INTO docs VALUES (?,?,?,?,?,?,?)", batch_int)
            n_int += len(batch_int)
            batch_int.clear()
        if len(batch_txt) >= 10_000:
            db.executemany("INSERT OR REPLACE INTO docs_other VALUES (?,?,?,?,?,?,?)", batch_txt)
            n_txt += len(batch_txt)
            batch_txt.clear()
    if batch_int:
        db.executemany("INSERT OR REPLACE INTO docs VALUES (?,?,?,?,?,?,?)", batch_int)
        n_int += len(batch_int)
    if batch_txt:
        db.executemany("INSERT OR REPLACE INTO docs_other VALUES (?,?,?,?,?,?,?)", batch_txt)
        n_txt += len(batch_txt)
    db.commit()
    db.execute("ANALYZE")
    db.commit()
    db.close()
    return {"path": str(out), "docs_rows": n_int, "docs_other_rows": n_txt,
            "build_seconds": round(time.perf_counter() - t0, 1),
            "on_disk_mb": round(dir_size(out) / 1e6, 2)}


def build_tantivy(corpus: Path, out_dir: Path) -> dict:
    """C1: the same rows as tantivy stored + fast fields, one index per section.

    Schema is builder.py's, PLUS the meta columns. `id` gains fast=True (C4 --
    it is what dense/ids.json holds today) and title/doi/section are stored so
    hydration can read them back without SQLite.
    """
    import tantivy
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    schema = (tantivy.SchemaBuilder()
              .add_text_field("id", stored=True, fast=True, tokenizer_name="raw")
              .add_text_field("title", stored=True, index_option="freq")
              .add_text_field("abstract", stored=False, index_option="freq")
              .add_text_field("doi", stored=True, tokenizer_name="raw")
              .add_integer_field("year", stored=True, indexed=True, fast=True)
              .add_text_field("doctype", stored=True, fast=True, tokenizer_name="raw")
              .add_integer_field("is_oa", stored=True, indexed=True, fast=True)
              .add_text_field("section", stored=True, tokenizer_name="raw")
              .build())

    t0 = time.perf_counter()
    indexes, writers, counts = {}, {}, {}
    for s in SECTIONS:
        d = out_dir / s
        d.mkdir(parents=True)
        idx = tantivy.Index(schema, path=str(d))
        indexes[s] = idx
        # 10 concurrent writers: keep each heap modest so the build fits in RAM.
        writers[s] = idx.writer(heap_size=64 * 1024 * 1024)
        counts[s] = 0

    for rec in iter_corpus(corpus):
        m = synth_meta(rec["id"], rec["title"])
        s = m["section"]
        writers[s].add_document(tantivy.Document(
            id=m["id"], title=m["title"], abstract=rec["abstract"], doi=m["doi"],
            year=m["year"], doctype=m["type"], is_oa=m["is_oa"], section=s))
        counts[s] += 1

    for s in SECTIONS:
        writers[s].commit()
        indexes[s].reload()

    return {"index_dir": str(out_dir), "sections": counts,
            "docs": sum(counts.values()),
            "build_seconds": round(time.perf_counter() - t0, 1),
            "on_disk_mb": round(dir_size(out_dir) / 1e6, 2)}


# ── the two arms ─────────────────────────────────────────────────────────────

class SqliteArm:
    """retriever._meta_rows, reproduced (chunk 500, docs + docs_other split).

    `cache_size` matters more than anything else this script measures. At
    SQLite's default (2000 pages / ~2 MB) the pages touched by a >~470-id
    candidate list do not fit, so every repetition re-reads them through the
    container's overlay filesystem, where a page read is a syscall rather than
    a memory hit: measured 2026-08-02, 199 ms at 1000 ids vs 3.6 ms with a
    64 MB cache, on the same file. Benchmarking C1 against the default would
    have handed the tantivy arm a 55x head start that has nothing to do with
    C1.
    """

    def __init__(self, path: Path, cache_mb: int = 64):
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True,
                                  check_same_thread=False)
        if cache_mb:
            self.db.execute(f"PRAGMA cache_size=-{cache_mb * 1024}")

    def rows(self, ids: list[str], cols: str) -> dict[str, tuple]:
        out: dict[str, tuple] = {}

        def _query(table: str, keys: list, back: dict | None) -> None:
            for start in range(0, len(keys), 500):
                chunk = keys[start:start + 500]
                marks = ",".join("?" * len(chunk))
                for row in self.db.execute(
                        f"SELECT id, {cols} FROM {table} WHERE id IN ({marks})", chunk):
                    did = back[row[0]] if back is not None else row[0]
                    out[did] = (did,) + tuple(row[1:])

        enc: dict[int, str] = {}
        other: list[str] = []
        for s in ids:
            n = encode_meta_id(s)
            (other.append(s) if n is None else enc.__setitem__(n, s))
        if enc:
            _query("docs", list(enc), enc)
        if other:
            _query("docs_other", other, None)
        return out


class TantivyArm:
    """C1: term_set_query on the raw `id` field, fanned out across 10 sections."""

    def __init__(self, root: Path):
        import tantivy
        self.tantivy = tantivy
        self.sections = {}
        for s in SECTIONS:
            idx = tantivy.Index.open(str(root / s))
            idx.reload()
            self.sections[s] = {"index": idx, "searcher": idx.searcher(),
                                "schema": idx.schema}

    def rows(self, ids: list[str], fields: list[str]) -> dict[str, tuple]:
        out: dict[str, tuple] = {}
        limit = len(ids)
        for s, h in self.sections.items():
            q = self.tantivy.Query.term_set_query(h["schema"], "id", ids)
            hits = h["searcher"].search(q, limit).hits
            for _score, addr in hits:
                doc = h["searcher"].doc(addr)
                did = doc["id"][0]
                out[did] = (did,) + tuple(doc[f][0] for f in fields)
        return out


# ── bench ────────────────────────────────────────────────────────────────────

FILTER_COLS_SQL = "year, type, is_oa"
FILTER_FIELDS_TV = ["year", "doctype", "is_oa"]
FULL_COLS_SQL = "title, doi, year, type, is_oa, section"
FULL_FIELDS_TV = ["title", "doi", "year", "doctype", "is_oa", "section"]


def timeit(fn, reps: int, warmup: int) -> dict:
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    return {
        "reps": reps,
        "p50_ms": round(statistics.median(samples), 3),
        "mean_ms": round(statistics.fmean(samples), 3),
        "p95_ms": round(samples[min(len(samples) - 1, int(0.95 * len(samples)))], 3),
        "min_ms": round(samples[0], 3),
        "max_ms": round(samples[-1], 3),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    here = Path(__file__).parent
    ap.add_argument("--corpus", type=Path,
                    default=ROOT / "spike" / "bm25_seismic" / "work" / "corpus.jsonl")
    ap.add_argument("--work", type=Path, default=here / "work")
    ap.add_argument("--build", action="store_true", help="build both stores")
    ap.add_argument("--bench", action="store_true", help="run the timing comparison")
    ap.add_argument("--sizes", type=int, nargs="+", default=[100, 1000],
                    help="candidate-list sizes to time")
    ap.add_argument("--reps", type=int, default=30)
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--sqlite-cache-mb", type=int, default=64,
                    help="cache_size for the SQLite arm (0 = SQLite's ~2MB default)")
    ap.add_argument("--out", type=Path, default=None,
                    help="results JSON (default: data/eval_results/c1_meta_lookup_<ts>.json)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    args.work.mkdir(parents=True, exist_ok=True)
    if not (args.build or args.bench):
        ap.error("pass --build and/or --bench")

    report = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "corpus": str(args.corpus), "seed": args.seed,
              "sections": len(SECTIONS)}

    sqlite_path = args.work / "meta.sqlite"
    tantivy_root = args.work / "tantivy_meta"

    if args.build:
        log.info("building SQLite baseline (production meta.sqlite schema)…")
        report["build_sqlite"] = build_sqlite(args.corpus, sqlite_path)
        log.info("sqlite: %s", report["build_sqlite"])
        log.info("building %d tantivy section indexes with meta fields…", len(SECTIONS))
        report["build_tantivy"] = build_tantivy(args.corpus, tantivy_root)
        log.info("tantivy: %s", report["build_tantivy"])
        (args.work / "build_report.json").write_text(json.dumps(report, indent=2))

    if not args.bench:
        return

    if not sqlite_path.exists() or not tantivy_root.exists():
        ap.error("stores missing — run with --build first")

    # Sample ids the way an approximate leg produces them: scattered across all
    # sections, in no particular order. That is what forces the x10 fan-out.
    all_ids = [rec["id"] for rec in iter_corpus(args.corpus)]
    rng = random.Random(args.seed)

    sql_arm = SqliteArm(sqlite_path, cache_mb=args.sqlite_cache_mb)
    sql_default = SqliteArm(sqlite_path, cache_mb=0)  # today's untuned config
    tv_arm = TantivyArm(tantivy_root)
    report["sqlite_cache_mb"] = args.sqlite_cache_mb

    report["workloads"] = {}
    for size in args.sizes:
        ids = rng.sample(all_ids, size)

        # Correctness gate first: if the arms disagree, the timings are noise.
        sql_full = sql_arm.rows(ids, FULL_COLS_SQL)
        tv_full = tv_arm.rows(ids, FULL_FIELDS_TV)
        parity = {
            "sqlite_rows": len(sql_full), "tantivy_rows": len(tv_full),
            "ids_requested": size,
            "same_id_set": set(sql_full) == set(tv_full),
        }
        mismatched = [i for i in sql_full
                      if i in tv_full and sql_full[i] != tv_full[i]]
        parity["rows_identical"] = not mismatched
        parity["example_mismatch"] = (
            {"id": mismatched[0], "sqlite": sql_full[mismatched[0]],
             "tantivy": tv_full[mismatched[0]]} if mismatched else None)
        if not (parity["same_id_set"] and parity["rows_identical"]):
            log.warning("PARITY FAIL at size=%d: %s", size, parity)

        w = {"parity": parity}
        for name, sql_cols, tv_fields in (
                ("filter_mask", FILTER_COLS_SQL, FILTER_FIELDS_TV),
                ("full_hydrate", FULL_COLS_SQL, FULL_FIELDS_TV)):
            a = timeit(lambda: sql_arm.rows(ids, sql_cols), args.reps, args.warmup)
            d = timeit(lambda: sql_default.rows(ids, sql_cols), args.reps, args.warmup)
            b = timeit(lambda: tv_arm.rows(ids, tv_fields), args.reps, args.warmup)
            w[name] = {"sqlite_tuned": a, "sqlite_default_cache": d,
                       "tantivy_fanout": b,
                       "tantivy_over_sqlite": round(b["p50_ms"] / a["p50_ms"], 2)
                       if a["p50_ms"] else None,
                       "cache_pragma_speedup": round(d["p50_ms"] / a["p50_ms"], 2)
                       if a["p50_ms"] else None}
            log.info("size=%-5d %-13s sqlite(tuned) %.3f | sqlite(default) %.3f | "
                     "tantivy x10 %.3f ms -> tantivy/sqlite %sx",
                     size, name, a["p50_ms"], d["p50_ms"], b["p50_ms"],
                     w[name]["tantivy_over_sqlite"])
        report["workloads"][str(size)] = w

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"c1_meta_lookup_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    log.info("results -> %s", out)


if __name__ == "__main__":
    main()
