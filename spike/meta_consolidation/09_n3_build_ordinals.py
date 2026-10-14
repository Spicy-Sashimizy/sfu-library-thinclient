#!/usr/bin/env python3
"""N3 — build the real ordinal artifacts from the real 150M `meta.sqlite`.

Doc 18 §7 N3. This is the build-time half of ordinal addressing, done at true
production scale rather than simulated: one pass over `data/thinclient_index/
meta.sqlite` assigning a global ordinal `0..N-1` to every document and emitting
the columnar artifacts the serving path would mmap.

**The ids come out sorted for free.** `docs` is `id INTEGER PRIMARY KEY`, so a
plain `SELECT ... FROM docs` scans in ascending id order. Assigning ordinals in
scan order therefore makes `ordinal -> W-id` monotonically increasing, which is
exactly the precondition `np.searchsorted` needs for the reverse `W-id ->
ordinal` direction. No separate sort, no separate index.

(§10.3 measured `docs_other` — the TEXT overflow for ids that do not round-trip
— as holding **zero** rows at 150M, so a single pass over `docs` is complete.
The script asserts this rather than assuming it.)

Emitted, all ordinal-indexed:

    wids.npy      int64  ordinal -> W-id numeric  (sorted; doubles as the
                         W-id -> ordinal index via binary search)
    year.npy      int16
    dtype.npy     int8   dictionary-encoded, mapping in codes.json
    is_oa.npy     uint8
    section.npy   int8   dictionary-encoded, mapping in codes.json

Read-only on `meta.sqlite`. Output to the spike work dir (gitignored).

    .venv/bin/python3 spike/meta_consolidation/09_n3_build_ordinals.py
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "source"))
from lib.thinclient.ordinals import write_stamp  # noqa: E402

META = ROOT / "data" / "thinclient_index" / "meta.sqlite"
WORK = Path(__file__).parent / "work_ordinals"

log = logging.getLogger("n3")

SENTINEL_YEAR = 0
SENTINEL_CODE = -1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--batch", type=int, default=1_000_000)
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after N rows (0 = all). For smoke runs only.")
    ap.add_argument("--rows", type=int, default=0,
                    help="known row count of `docs`, used only to pre-size the "
                         "output arrays. Supplying it skips `SELECT count(*)`, "
                         "which is a full scan of the 24.9 GB table and cost 14 "
                         "minutes on the first 150M attempt (doc 18 §11). "
                         "Over-estimating is safe (arrays are truncated to the "
                         "rows actually read); under-estimating is refused.")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    args.work.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(f"file:{META}?mode=ro", uri=True)
    db.execute("PRAGMA cache_size=-262144")

    n_other = db.execute("SELECT count(*) FROM docs_other").fetchone()[0]
    if n_other:
        raise SystemExit(f"docs_other holds {n_other} rows — the single-pass "
                         f"assumption is invalid; handle the TEXT overflow first")
    log.info("docs_other empty — single pass over docs is complete")

    if args.limit:
        n_rows, sizing = args.limit, "--limit"
    elif args.rows:
        n_rows, sizing = args.rows, "--rows (count scan skipped)"
    else:
        t_count = time.perf_counter()
        n_rows = db.execute("SELECT count(*) FROM docs").fetchone()[0]
        sizing = f"SELECT count(*) ({time.perf_counter() - t_count:.0f}s)"
    log.info("assigning ordinals to %d docs (sizing: %s)", n_rows, sizing)

    wids = np.empty(n_rows, dtype=np.int64)
    years = np.empty(n_rows, dtype=np.int16)
    dtypes = np.empty(n_rows, dtype=np.int8)
    oas = np.empty(n_rows, dtype=np.uint8)
    sects = np.empty(n_rows, dtype=np.int8)

    type_codes: dict[str, int] = {}
    sect_codes: dict[str, int] = {}

    sql = "SELECT id, year, type, is_oa, section FROM docs"
    if args.limit:
        sql += f" LIMIT {args.limit}"
    cur = db.execute(sql)

    t0 = time.perf_counter()
    i = 0
    last_id = -1
    monotonic = True
    while True:
        rows = cur.fetchmany(args.batch)
        if not rows:
            break
        if i + len(rows) > n_rows:
            # Only reachable via an under-estimating --rows: without this the
            # `i >= n_rows` break below would silently emit a TRUNCATED ordinal
            # space, and a missing tail is invisible at query time (ids simply
            # fail the `found` check). Refuse instead.
            raise SystemExit(
                f"--rows={n_rows} is too small: docs holds at least "
                f"{i + len(rows)} rows. Re-run with a correct or larger "
                f"--rows, or omit it to pay the count scan.")
        for did, year, dtype, is_oa, section in rows:
            if did <= last_id:
                monotonic = False
            last_id = did
            wids[i] = did
            years[i] = year if year is not None else SENTINEL_YEAR
            if dtype is None:
                dtypes[i] = SENTINEL_CODE
            else:
                c = type_codes.get(dtype)
                if c is None:
                    c = len(type_codes)
                    type_codes[dtype] = c
                dtypes[i] = c
            oas[i] = 1 if is_oa else 0
            if section is None:
                sects[i] = SENTINEL_CODE
            else:
                c = sect_codes.get(section)
                if c is None:
                    c = len(sect_codes)
                    sect_codes[section] = c
                sects[i] = c
            i += 1
        log.info("  %d/%d (%.0f%%) %.0fs", i, n_rows, 100 * i / n_rows,
                 time.perf_counter() - t0)
        if i >= n_rows:
            break

    assign_s = time.perf_counter() - t0
    log.info("assigned %d ordinals in %.0fs (%.0f docs/s); monotonic=%s",
             i, assign_s, i / assign_s, monotonic)
    if not monotonic:
        raise SystemExit("ids were NOT ascending — ordinal->W-id is not sorted, "
                         "so binary search is invalid. Sort before emitting.")

    if i < n_rows:   # short read (LIMIT or a concurrent change)
        wids, years, dtypes = wids[:i], years[:i], dtypes[:i]
        oas, sects = oas[:i], sects[:i]

    t1 = time.perf_counter()
    for name, arr in (("wids", wids), ("year", years), ("dtype", dtypes),
                      ("is_oa", oas), ("section", sects)):
        np.save(args.work / f"{name}.npy", arr)
    codes = {"type": type_codes, "section": sect_codes,
             "sentinel_code": SENTINEL_CODE, "sentinel_year": SENTINEL_YEAR,
             "rows": int(i)}
    (args.work / "codes.json").write_text(json.dumps(codes, indent=2))
    # Bind these arrays to the meta.sqlite they were built from. Without this
    # the retriever refuses to load them at all — a stale pairing returns the
    # WRONG document silently (doc 18 §6 risk 1).
    stamp = write_stamp(args.work, i, codes, META)
    log.info("ordinal_space_id %s — copy it into manifest.json under "
             "'ordinal_space_id' to authorise serving", stamp["ordinal_space_id"])
    write_s = time.perf_counter() - t1

    sizes = {p.name: p.stat().st_size for p in args.work.glob("*.npy")}
    total = sum(sizes.values())
    rep = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "rows": int(i), "row_count_source": sizing,
           "assign_seconds": round(assign_s, 1),
           "docs_per_s": round(i / assign_s), "write_seconds": round(write_s, 1),
           "monotonic_ids": monotonic, "artifact_bytes": sizes,
           "artifact_total_bytes": total,
           "filter_columns_bytes": sum(v for k, v in sizes.items()
                                       if k != "wids.npy"),
           "type_cardinality": len(type_codes),
           "section_cardinality": len(sect_codes),
           "meta_sqlite_bytes": META.stat().st_size}
    log.info("artifacts %.2f GB (filter columns %.2f GB, wids %.2f GB) "
             "vs meta.sqlite %.2f GB",
             total / 1e9, rep["filter_columns_bytes"] / 1e9,
             sizes.get("wids.npy", 0) / 1e9, rep["meta_sqlite_bytes"] / 1e9)

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"n3_ordinal_build_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    log.info("results -> %s", out)


if __name__ == "__main__":
    main()
