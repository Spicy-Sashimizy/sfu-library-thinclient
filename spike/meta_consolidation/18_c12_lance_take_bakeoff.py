#!/usr/bin/env python3
"""C12 — can ANY consolidating store hold the meta speed gate at full 150.4M?

C11 (doc 18 §19) killed the perdoc-zstd title/DOI store: -10.64 GB but 87x
SLOWER than staged SQLite, because meta's SQLite baseline is a fast, warm,
UNCOMPRESSED text read (0.331 ms) and a 12.3 GB compressed store is not
resident, so 50 scattered ids become 50 cold page-faults + 50 decompressions.

This is the bake-off §19 #1 queued, at FULL scale, addressed by ORDINAL:

  sqlite_mainline  staged meta.sqlite, SELECT title,doi WHERE id IN (...)  — the
                   0.33 ms baseline that must not regress.
  lance_take       a Lance dataset (title,doi columns), ds.take([ordinals]).
                   C5 (doc 17) rejected Lance on its BTREE *scalar index* — a
                   searcher — and NEVER measured positional take, which is
                   Lance's actual random-access path and IS ordinal addressing.
                   That is the number that changed.
  raw_mmap         uncompressed title\\x00doi blob + u64 offsets, one mmap read,
                   NO decompress. The only design that can match SQLite's read,
                   and it saves ~nothing (-0.39 GB, §15) — included to make the
                   size/speed conflict concrete.
  perdoc_zstd      the C11 store, reused. The 87x loser, for reference.
  sqlite_ctrl      a 2nd SQLite arm = the noise floor (doc 18 §14).

GATES, both enforced here and re-checked by hand:
  QUALITY  byte-parity of (title, doi) incl the NULL sentinel, 20,000 ids, every
           arm identical to sqlite_mainline or the run is void.
  SPEED    no-regression vs sqlite_mainline; p50 AND mean AND p90; interleaved,
           order-randomised per trial, every arm warmed; all stores on LOCAL
           DISK (§14). A store that beats SQLite but returns different strings,
           or matches strings but regresses latency, FAILS.

Read-only against meta.sqlite (mode=ro) and the ordinal arrays. Builds under
--work. RUN UNDER .venv-lance (it has lance/pyarrow/zstandard):

    spike/meta_consolidation/.venv-lance/bin/python \
        spike/meta_consolidation/18_c12_lance_take_bakeoff.py
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sqlite3
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def _fstype(path: str) -> str | None:
    """Minimal inline of retriever._fstype_for_path — avoids importing the
    thinclient package (and its tantivy/bmp deps) under .venv-lance."""
    try:
        target = os.path.realpath(path)
        best_mp, best_type = "", None
        with open("/proc/mounts") as fh:
            for line in fh:
                p = line.split()
                if len(p) >= 3 and (target == p[1] or target.startswith(p[1].rstrip("/") + "/")):
                    if len(p[1]) >= len(best_mp):
                        best_mp, best_type = p[1], p[2]
        return best_type
    except OSError:
        return None


def _rec(title, doi) -> bytes:
    t = b"\xff" if title is None else title.encode("utf-8")
    d = b"\xff" if doi is None else doi.encode("utf-8")
    return t + b"\x00" + d


def _unrec(buf: bytes):
    t, _, d = buf.partition(b"\x00")
    return (None if t == b"\xff" else t.decode("utf-8"),
            None if d == b"\xff" else d.decode("utf-8"))


def _stat(samples):
    s = sorted(samples)
    return {"n": len(s), "p50_ms": round(statistics.median(s), 4),
            "mean_ms": round(statistics.fmean(s), 4),
            "p90_ms": round(s[min(len(s) - 1, int(0.9 * len(s)))], 4)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meta", type=Path, default=Path("/var/tmp/meta_stage/meta.sqlite"))
    ap.add_argument("--ordinals", type=Path, default=Path("/var/tmp/ordinals_stage"))
    ap.add_argument("--perdoc", type=Path, default=Path("/var/tmp/c11_meta_store"),
                    help="reuse the C11 store as the perdoc_zstd arm")
    ap.add_argument("--work", type=Path, default=Path("/var/tmp/c12_lance"))
    ap.add_argument("--batch", type=int, default=2_000_000, help="lance append batch")
    ap.add_argument("--lookups", type=int, default=200)
    ap.add_argument("--hits", type=int, default=50)
    ap.add_argument("--parity", type=int, default=20_000)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    import logging
    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("c12")
    rng = random.Random(args.seed)
    args.work.mkdir(parents=True, exist_ok=True)

    import lance
    import pyarrow as pa
    import zstandard

    wids = np.load(args.ordinals / "wids.npy", mmap_mode="r")
    n = len(wids)
    con = sqlite3.connect(f"file:{args.meta}?mode=ro", uri=True)
    if con.execute("SELECT count(*) FROM docs").fetchone()[0] != n:
        raise SystemExit("docs count != ordinal rows; not the same build")
    log.info("bake-off over %s docs | meta on %s", f"{n:,}", _fstype(str(args.meta)))

    raw_blob = args.work / "raw.bin"
    raw_offs = args.work / "raw_offsets.npy"
    lance_path = args.work / "meta.lance"

    if not (args.skip_build and raw_blob.exists() and lance_path.exists()):
        if lance_path.exists():
            shutil.rmtree(lance_path)
        schema = pa.schema([("title", pa.string()), ("doi", pa.string())])
        offsets = np.zeros(n + 1, dtype=np.uint64)
        t0 = time.perf_counter()
        pos = i = 0
        bt, bd = [], []          # pyarrow batch buffers
        raw_tmp = args.work / "raw.bin.partial"
        log.info("single streaming pass: raw blob + lance dataset, ordinal order")
        with open(raw_tmp, "wb", buffering=1 << 22) as fh:
            for did, title, doi in con.execute(
                    "SELECT id, title, doi FROM docs ORDER BY id"):
                if did != int(wids[i]):
                    raise SystemExit(f"row {i}: id {did} != wids {int(wids[i])} — "
                                     f"order mismatch; ordinals would misaddress")
                offsets[i] = pos
                b = _rec(title, doi)
                fh.write(b)
                pos += len(b)
                bt.append(title)
                bd.append(doi)
                i += 1
                if len(bt) >= args.batch:
                    lance.write_dataset(
                        pa.table({"title": bt, "doi": bd}, schema=schema),
                        str(lance_path), mode=("append" if lance_path.exists() else "create"))
                    bt, bd = [], []
                    log.info("  %s / %s docs, raw %.2f GB, %.0f docs/s", f"{i:,}",
                             f"{n:,}", pos / 1e9, i / (time.perf_counter() - t0))
        if bt:
            lance.write_dataset(pa.table({"title": bt, "doi": bd}, schema=schema),
                                str(lance_path), mode=("append" if lance_path.exists() else "create"))
        offsets[n] = pos
        np.save(raw_offs, offsets)
        raw_tmp.rename(raw_blob)
        log.info("built raw %.2f GB + lance in %.0f s", pos / 1e9, time.perf_counter() - t0)

    # ── sizes ────────────────────────────────────────────────────────────────
    def _dirsize(p: Path) -> int:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    filt_gb, wids_gb = 0.75, 1.20
    raw_store = raw_blob.stat().st_size + raw_offs.stat().st_size
    lance_store = _dirsize(lance_path)
    perdoc_store = ((args.perdoc / "title_doi.bin").stat().st_size
                    + (args.perdoc / "title_doi_offsets.npy").stat().st_size
                    + (args.perdoc / "title_doi.zdict").stat().st_size)
    meta_gb = args.meta.stat().st_size / 1e9
    sizes = {}
    for name, store_b in (("raw_mmap", raw_store), ("lance_take", lance_store),
                          ("perdoc_zstd", perdoc_store)):
        repl = store_b / 1e9 + filt_gb + wids_gb
        sizes[name] = {"store_gb": round(store_b / 1e9, 2),
                       "replacement_gb": round(repl, 2),
                       "saved_gb": round(meta_gb - repl, 2)}
    log.info("sizes: %s", json.dumps(sizes))

    # ── readers, all addressed by ORDINAL ────────────────────────────────────
    raw_off = np.load(raw_offs, mmap_mode="r")
    raw_mm = np.memmap(raw_blob, dtype=np.uint8, mode="r")

    def fetch_raw(ords):
        return [_unrec(raw_mm[int(raw_off[o]):int(raw_off[o + 1])].tobytes()) for o in ords]

    ds = lance.dataset(str(lance_path))

    def fetch_lance(ords):
        t = ds.take(list(ords), columns=["title", "doi"])
        return list(zip(t.column("title").to_pylist(), t.column("doi").to_pylist()))

    pd_off = np.load(args.perdoc / "title_doi_offsets.npy", mmap_mode="r")
    pd_mm = np.memmap(args.perdoc / "title_doi.bin", dtype=np.uint8, mode="r")
    pd_dctx = zstandard.ZstdDecompressor(
        dict_data=zstandard.ZstdCompressionDict((args.perdoc / "title_doi.zdict").read_bytes()))

    def fetch_perdoc(ords):
        return [_unrec(pd_dctx.decompress(pd_mm[int(pd_off[o]):int(pd_off[o + 1])].tobytes()))
                for o in ords]

    def fetch_sqlite(ords):
        keys = [int(wids[o]) for o in ords]
        marks = ",".join("?" * len(keys))
        got = {r[0]: (r[1], r[2]) for r in con.execute(
            f"SELECT id, title, doi FROM docs WHERE id IN ({marks})", keys)}
        return [got[k] for k in keys]

    arms = {"sqlite_mainline": fetch_sqlite, "lance_take": fetch_lance,
            "raw_mmap": fetch_raw, "perdoc_zstd": fetch_perdoc,
            "sqlite_ctrl": fetch_sqlite}

    # ── QUALITY gate ─────────────────────────────────────────────────────────
    parity = {}
    par_ords = rng.sample(range(n), args.parity)
    log.info("parity: %s ids", f"{args.parity:,}")
    for s in range(0, len(par_ords), 500):
        chunk = par_ords[s:s + 500]
        base = fetch_sqlite(chunk)
        for name, fn in arms.items():
            if name == "sqlite_mainline":
                continue
            mm = sum(1 for a, b in zip(fn(chunk), base) if a != b)
            parity[name] = parity.get(name, 0) + mm
    parity_pass = {k: (v == 0) for k, v in parity.items()}
    for name in arms:
        if name != "sqlite_mainline":
            log.info("  %-15s parity %s", name,
                     "PASS" if parity_pass[name] else f"FAIL({parity[name]})")

    # ── SPEED gate ───────────────────────────────────────────────────────────
    trials = [rng.sample(range(n), args.hits) for _ in range(args.lookups)]
    for fn in arms.values():
        for t in trials[:10]:
            fn(t)
    samples = {k: [] for k in arms}
    for t in trials:
        order = list(arms)
        rng.shuffle(order)
        for name in order:
            fn = arms[name]
            t0 = time.perf_counter()
            fn(t)
            samples[name].append((time.perf_counter() - t0) * 1000)

    base_p50 = statistics.median(samples["sqlite_mainline"])
    lookup = {}
    for name in arms:
        st = _stat(samples[name])
        st["vs_mainline"] = round(base_p50 / st["p50_ms"], 3) if st["p50_ms"] else None
        st["regression"] = bool(statistics.median(samples[name]) > base_p50)
        st["parity_pass"] = parity_pass.get(name, True)
        lookup[name] = st
        log.info("%-15s p50 %8.4f  mean %8.4f  p90 %8.4f | %6sx | parity %s%s",
                 name, st["p50_ms"], st["mean_ms"], st["p90_ms"], st["vs_mainline"],
                 "PASS" if st["parity_pass"] else "FAIL",
                 "  <-- REGRESSION" if st["regression"] else "")

    ctrl = lookup["sqlite_ctrl"]
    noise = round(abs(ctrl["p50_ms"] - base_p50) / base_p50 * 100, 2)
    rep = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "goal": "META bake-off: can lance_take or raw_mmap hold the speed gate C11 failed?",
           "corpus_rows": n, "meta_gb": round(meta_gb, 2), "meta_fstype": _fstype(str(args.meta)),
           "sizes": sizes, "parity": parity_pass, "lookup": lookup,
           "noise_floor_pct": noise,
           "quality_gate_pass": all(parity_pass.values()),
           "verdict": {name: {
               "holds_speed_gate": not lookup[name]["regression"],
               "parity_pass": lookup[name].get("parity_pass", True),
               "saves_gb": sizes.get(name, {}).get("saved_gb"),
           } for name in ("lance_take", "raw_mmap", "perdoc_zstd")}}

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"c12_lance_bakeoff_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    con.close()
    log.info("VERDICT: %s", json.dumps(rep["verdict"]))
    log.info("noise %.2f%% | quality gate %s | results -> %s", noise,
             "PASS" if rep["quality_gate_pass"] else "FAIL", out)


if __name__ == "__main__":
    main()
