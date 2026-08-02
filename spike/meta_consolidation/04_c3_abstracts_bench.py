#!/usr/bin/env python3
"""C3 spike — retire `abstracts.sqlite`'s SQLite envelope, keep its codec.

C3 proposes: move the ~32 KB zstd blocks out of SQLite into a flat block file,
and move the locator (`id -> block, offset, len`) into tantivy fast fields.
The trained per-script dictionaries and the block layout are UNCHANGED -- only
the SQLite envelope goes. That is why C3 was called "safe by construction".

Critically, **C1's failure mode does not apply here.** C1 died on a x10 section
fan-out: an approximate leg's candidate list is not section-partitioned, so
every one of 10 tantivy indexes had to be asked for every id. Abstracts are
different -- only HOT sections carry them, and in this index exactly one does
(`social_sciences__recent`, 13.47 GB). The locator lookup is x1. So C3 has to
be measured on its own merits rather than inheriting C1's verdict.

C3 splits into two independent claims, measured separately:

  (a) SIZE   how much of the 13.47 GB is locator + page slack rather than
             compressed abstract payload? That is C3's ceiling.
  (b) SPEED  is the SQLite locator lookup even a meaningful share of
             `AbstractStore.fetch()`, next to the block read and the zstd
             decompress? If not, C3 cannot help latency and is purely a size
             play.

For (b) this script decomposes the REAL `AbstractStore.fetch()` on the REAL
store into its three stages, and times the C3 replacement for the stage C3
actually changes -- the locator -- against the production tantivy index for
that same section. Nothing is extrapolated from a toy corpus: the C1 spike
measured the same code path 96x faster at spike scale than in production, so
subset-built arms are not trustworthy here.

Everything is opened READ-ONLY.

    .venv/bin/python3 spike/meta_consolidation/04_c3_abstracts_bench.py
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

log = logging.getLogger("c3bench")

SECTION = "social_sciences__recent"
SEC_DIR = ROOT / "data" / "thinclient_index" / "sections" / SECTION
ABS_DB = SEC_DIR / "abstracts.sqlite"
TANTIVY_DIR = SEC_DIR / "tantivy"


def reservoir_sample_ids(db: sqlite3.Connection, k: int, seed: int) -> list[str]:
    """Unbiased ids by streaming the PK index.

    Sampling a contiguous prefix (`LIMIT k`) would draw ids that share blocks,
    giving the block cache an unrealistically easy time. Reservoir sampling
    over the full 23.4M-row index costs one pass (~30 s) and scatters ids
    across blocks the way a real rerank candidate list does.
    """
    rng = random.Random(seed)
    res: list[str] = []
    t0 = time.perf_counter()
    for n, (doc_id,) in enumerate(db.execute("SELECT id FROM docs"), 1):
        if len(res) < k:
            res.append(doc_id)
        else:
            j = rng.randrange(n)
            if j < k:
                res[j] = doc_id
    log.info("reservoir-sampled %d ids from %d rows in %.0fs",
             len(res), n, time.perf_counter() - t0)
    return res


class Stages:
    """The three stages inside AbstractStore.fetch(), timed separately."""

    def __init__(self, cache_mb: int = 64):
        import zstandard
        self.db = sqlite3.connect(f"file:{ABS_DB}?mode=ro", uri=True,
                                  check_same_thread=False)
        if cache_mb:
            self.db.execute(f"PRAGMA cache_size=-{cache_mb * 1024}")
        names = json.loads(self.db.execute(
            "SELECT v FROM meta WHERE k='dicts'").fetchone()[0])

        def _zdict(key: str):
            row = self.db.execute("SELECT v FROM meta WHERE k=?",
                                  (key,)).fetchone()
            return zstandard.ZstdCompressionDict(row[0]) if row else None

        plain = zstandard.ZstdDecompressor()
        latin = _zdict("zdict_latin")
        self.dctxs = {}
        for i, name in enumerate(names):
            zd = _zdict(f"zdict_{name}") or latin
            self.dctxs[i] = (zstandard.ZstdDecompressor(dict_data=zd)
                             if zd else plain)

    def locator(self, ids: list[str]) -> list[tuple]:
        """Stage 1 — the ONLY stage C3 replaces."""
        out = []
        for s in range(0, len(ids), 500):
            chunk = ids[s:s + 500]
            marks = ",".join("?" * len(chunk))
            out += self.db.execute(
                f"SELECT id, b, off, n FROM docs WHERE id IN ({marks})",
                chunk).fetchall()
        return out

    def blocks_raw(self, locs: list[tuple]) -> dict:
        """Stage 2 — fetch the distinct compressed blocks (C3 keeps these bytes,
        it only moves them out of SQLite into a flat file)."""
        out = {}
        for b in {l[1] for l in locs}:
            out[b] = self.db.execute(
                "SELECT d, z FROM blocks WHERE b=?", (b,)).fetchone()
        return out

    def decompress(self, blocks: dict) -> dict:
        """Stage 3 — unchanged by C3."""
        return {b: self.dctxs.get(d, self.dctxs[0]).decompress(z)
                for b, (d, z) in blocks.items()}

    def full(self, ids: list[str]) -> dict:
        locs = self.locator(ids)
        raw = self.blocks_raw(locs)
        pay = self.decompress(raw)
        return {i: pay[b][off:off + n].decode("utf-8")
                for i, b, off, n in locs}


class TantivyLocator:
    """C3's replacement for stage 1, on the REAL production section index.

    The production schema has `id` stored+raw but no b/off/n fast fields, so
    this times the part C3 cannot avoid -- resolving `id -> DocAddress` via the
    term dictionary. The subsequent `fast_field_values` read is columnar and
    O(1) per doc; it is NOT the term-dictionary traversal that dominated C1.
    """

    def __init__(self):
        import tantivy
        self.tantivy = tantivy
        idx = tantivy.Index.open(str(TANTIVY_DIR))
        idx.reload()
        self.searcher = idx.searcher()
        self.schema = idx.schema

    def locate(self, ids: list[str]) -> int:
        q = self.tantivy.Query.term_set_query(self.schema, "id", ids)
        return len(self.searcher.search(q, len(ids)).hits)


def flatfile_probe(sizes, reps, warmup, chunk, seed) -> dict:
    """Floor cost of C3's flat block file, measured without building one.

    C3 moves the compressed blocks out of SQLite into a flat file read by
    offset. The read cost of that design is "one pread of ~chunk bytes at a
    random offset in a file this size" -- which can be measured on any file of
    the right size, including `abstracts.sqlite` itself. The bytes returned are
    meaningless (a random offset is not a block boundary); only the I/O cost is,
    and that is what differs between the two designs.

    Building an actual 13.5 GB flat file to measure this would risk the trap
    that broke the C1 spike: a smaller file would sit in page cache and read
    artificially fast. Probing a file that is already the production size
    avoids that.

    The real design also needs a block -> offset table, but at 1.06M blocks x
    8 B that is ~8.5 MB, RAM-resident, and adds nothing per read.
    """
    import os
    sz = ABS_DB.stat().st_size
    fd = os.open(str(ABS_DB), os.O_RDONLY)
    rng = random.Random(seed)
    out = {"chunk_bytes": chunk, "file_bytes": sz, "sizes": {}}
    try:
        def burst(k):
            offs = [rng.randrange(0, sz - chunk) for _ in range(k)]
            t0 = time.perf_counter()
            for o in offs:
                os.pread(fd, chunk, o)
            return (time.perf_counter() - t0) * 1000

        for k in sizes:
            for _ in range(warmup):
                burst(k)
            s = sorted(burst(k) for _ in range(reps))
            p50 = statistics.median(s)
            out["sizes"][str(k)] = {"p50_ms": round(p50, 2),
                                    "per_block_ms": round(p50 / k, 3),
                                    "min_ms": round(s[0], 2),
                                    "max_ms": round(s[-1], 2)}
    finally:
        os.close(fd)
    return out


def timeit(fn, arglists, reps, warmup):
    for i in range(warmup):
        fn(arglists[i % len(arglists)])
    s = []
    for i in range(reps):
        t0 = time.perf_counter()
        fn(arglists[i % len(arglists)])
        s.append((time.perf_counter() - t0) * 1000)
    s.sort()
    return {"reps": reps, "p50_ms": round(statistics.median(s), 2),
            "mean_ms": round(statistics.fmean(s), 2),
            "min_ms": round(s[0], 2), "max_ms": round(s[-1], 2)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sizes", type=int, nargs="+", default=[10, 50, 100],
                    help="rerank candidate counts (hot path is top ~50-100)")
    ap.add_argument("--reps", type=int, default=9)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--pool", type=int, default=30000)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")

    st = Stages()
    pool = reservoir_sample_ids(st.db, args.pool, args.seed)
    tv = TantivyLocator()

    report = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "section": SECTION,
              "abstracts_bytes": ABS_DB.stat().st_size,
              "pool_ids": len(pool), "seed": args.seed, "results": {}}

    rng = random.Random(args.seed + 1)
    for size in args.sizes:
        need = args.reps + args.warmup
        picks = rng.sample(pool, size * need)
        id_lists = [picks[i * size:(i + 1) * size] for i in range(need)]

        loc_lists = [st.locator(L) for L in id_lists]
        blk_lists = [st.blocks_raw(l) for l in loc_lists]

        e = {
            "sqlite_locator":   timeit(st.locator, id_lists, args.reps, args.warmup),
            "sqlite_blocks":    timeit(st.blocks_raw, loc_lists, args.reps, args.warmup),
            "decompress":       timeit(st.decompress, blk_lists, args.reps, args.warmup),
            "full_fetch":       timeit(st.full, id_lists, args.reps, args.warmup),
            "tantivy_locator":  timeit(tv.locate, id_lists, args.reps, args.warmup),
        }
        e["locator_share_of_full_pct"] = (
            round(100 * e["sqlite_locator"]["p50_ms"] / e["full_fetch"]["p50_ms"], 1)
            if e["full_fetch"]["p50_ms"] else None)
        e["tantivy_over_sqlite_locator"] = (
            round(e["tantivy_locator"]["p50_ms"] / e["sqlite_locator"]["p50_ms"], 2)
            if e["sqlite_locator"]["p50_ms"] else None)
        e["distinct_blocks_touched"] = len(blk_lists[0])
        report["results"][str(size)] = e

        log.info("k=%-4d full %.2f ms = locator %.2f + blocks %.2f + unzip %.2f "
                 "| locator is %s%% of fetch | tantivy locator %.2f ms (%sx)",
                 size, e["full_fetch"]["p50_ms"], e["sqlite_locator"]["p50_ms"],
                 e["sqlite_blocks"]["p50_ms"], e["decompress"]["p50_ms"],
                 e["locator_share_of_full_pct"], e["tantivy_locator"]["p50_ms"],
                 e["tantivy_over_sqlite_locator"])

    avg_block = 10472   # measured: sum(length(z))/count(*) over blocks
    report["flatfile_probe"] = flatfile_probe(
        args.sizes, args.reps, args.warmup, avg_block, args.seed + 2)
    for k, v in report["flatfile_probe"]["sizes"].items():
        sq = report["results"][k]["sqlite_blocks"]["p50_ms"]
        report["results"][k]["flatfile_over_sqlite_blocks"] = (
            round(v["p50_ms"] / sq, 3) if sq else None)
        log.info("k=%-4s flat-file blocks %.2f ms vs sqlite blocks %.2f ms "
                 "-> %.2fx faster (%.2f ms/block vs %.2f)",
                 k, v["p50_ms"], sq, sq / v["p50_ms"] if v["p50_ms"] else 0,
                 v["per_block_ms"], sq / int(k))

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"c3_abstracts_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    log.info("results -> %s", out)


if __name__ == "__main__":
    main()
