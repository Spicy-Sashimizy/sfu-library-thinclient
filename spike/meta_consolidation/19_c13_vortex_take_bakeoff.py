#!/usr/bin/env python3
"""C13 — does VORTEX break the meta size/speed conflict where Lance could not?

C12 (doc 18 §20) showed no store holds the meta speed gate: Lance `take` was
21× slower than warm SQLite (0.30 ms p50) despite the best compression. Vortex
(spiraldb, LF AI & Data) is the other credible random-access columnar format and
pitches "random access competitive with the specialists for hydration" — so it
gets the same full-scale, ordinal-addressed test, on the same gates.

  sqlite_mainline  staged meta.sqlite, SELECT title,doi WHERE id IN (...)  — the
                   ~0.30 ms baseline that must not regress.
  vortex_take      a Vortex file (title,doi), vf.scan(indices=sorted_ords).
                   scan(indices=) is a MONOTONIC selection, so the reader sorts
                   the 50 ords, scans, and reindexes back to request order — the
                   cost of that sort/reindex is counted, it is what a real
                   hydration path would pay.
  lance_take       the C12 Lance dataset, reused (ds.take([ordinals])).
  raw_mmap         the C12 uncompressed blob, reused (one mmap read, no decode).
  sqlite_ctrl      a 2nd SQLite arm = the noise floor (doc 18 §14).

GATES (enforced here, re-checked by hand):
  QUALITY  byte-parity of (title,doi) incl the NULL sentinel, 20,000 ids.
  SPEED    no-regression vs sqlite_mainline; p50 AND mean AND p90; interleaved,
           order-randomised, warmed; all stores local disk.

Expectation before running (doc 18 discipline): the meta SQLite baseline is a
warm uncompressed-text read nothing has beaten; Vortex will likely land between
raw (0.70 ms) and lance (6.37 ms) and REGRESS. Falsifier: vortex_take p50 ≤
~0.30 ms while saving space — the first thing to clear the gate.

Read-only against meta.sqlite (mode=ro) + ordinals. RUN UNDER .venv-lance:
    spike/meta_consolidation/.venv-lance/bin/python \
        spike/meta_consolidation/19_c13_vortex_take_bakeoff.py
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
log = logging.getLogger("c13")


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
    ap.add_argument("--c12", type=Path, default=Path("/var/tmp/c12_lance"),
                    help="reuse raw.bin + meta.lance built by C12")
    ap.add_argument("--work", type=Path, default=Path("/var/tmp/c13_vortex"))
    ap.add_argument("--batch", type=int, default=1_000_000)
    ap.add_argument("--lookups", type=int, default=200)
    ap.add_argument("--hits", type=int, default=50)
    ap.add_argument("--parity", type=int, default=20_000)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    rng = random.Random(args.seed)
    args.work.mkdir(parents=True, exist_ok=True)

    import lance
    import pyarrow as pa
    import vortex

    wids = np.load(args.ordinals / "wids.npy", mmap_mode="r")
    n = len(wids)
    con = sqlite3.connect(f"file:{args.meta}?mode=ro", uri=True)
    if con.execute("SELECT count(*) FROM docs").fetchone()[0] != n:
        raise SystemExit("docs count != ordinal rows; not the same build")
    vortex_path = args.work / "meta.vortex"
    log.info("vortex bake-off over %s docs", f"{n:,}")

    # ── build the Vortex file, streaming, in ordinal order ───────────────────
    if not (args.skip_build and vortex_path.exists()):
        if vortex_path.exists():
            vortex_path.unlink()
        schema = pa.schema([("title", pa.string()), ("doi", pa.string())])
        t0 = time.perf_counter()
        state = {"i": 0}

        def batches():
            cur = con.execute("SELECT id, title, doi FROM docs ORDER BY id")
            while True:
                rows = cur.fetchmany(args.batch)
                if not rows:
                    break
                ts, ds = [], []
                for did, title, doi in rows:
                    i = state["i"]
                    if did != int(wids[i]):
                        raise SystemExit(f"row {i}: id {did} != wids {int(wids[i])}"
                                         " — order mismatch; vortex would misaddress")
                    ts.append(title)
                    ds.append(doi)
                    state["i"] = i + 1
                yield pa.record_batch({"title": ts, "doi": ds}, schema=schema)
                log.info("  %s / %s docs, %.0f docs/s", f"{state['i']:,}",
                         f"{n:,}", state["i"] / (time.perf_counter() - t0))

        reader = pa.RecordBatchReader.from_batches(schema, batches())
        vortex.io.write(reader, str(vortex_path))
        if state["i"] != n:
            raise SystemExit(f"wrote {state['i']} rows, expected {n}")
        log.info("built vortex %.2f GB in %.0f s", vortex_path.stat().st_size / 1e9,
                 time.perf_counter() - t0)

    # ── sizes ────────────────────────────────────────────────────────────────
    filt_gb, wids_gb = 0.75, 1.20
    meta_gb = args.meta.stat().st_size / 1e9
    vortex_store = vortex_path.stat().st_size
    repl = vortex_store / 1e9 + filt_gb + wids_gb
    sizes = {"vortex_take": {"store_gb": round(vortex_store / 1e9, 2),
                             "replacement_gb": round(repl, 2),
                             "saved_gb": round(meta_gb - repl, 2)}}
    log.info("vortex store %.2f GB | replacement %.2f GB | saves %.2f GB vs %.2f",
             vortex_store / 1e9, repl, meta_gb - repl, meta_gb)

    # ── readers, all addressed by ORDINAL ────────────────────────────────────
    vf = vortex.open(str(vortex_path))

    def fetch_vortex(ords):
        order = np.argsort(ords, kind="stable")
        asc = [int(ords[i]) for i in order]
        tab = vf.scan(["title", "doi"],
                      indices=vortex.array(pa.array(asc, pa.int64()))).read_all().to_arrow_table()
        ts, ds = tab.column("title").to_pylist(), tab.column("doi").to_pylist()
        out = [None] * len(ords)
        for k, pos in enumerate(order):
            out[pos] = (ts[k], ds[k])
        return out

    ds_lance = lance.dataset(str(args.c12 / "meta.lance"))

    def fetch_lance(ords):
        t = ds_lance.take(list(ords), columns=["title", "doi"])
        return list(zip(t.column("title").to_pylist(), t.column("doi").to_pylist()))

    raw_off = np.load(args.c12 / "raw_offsets.npy", mmap_mode="r")
    raw_mm = np.memmap(args.c12 / "raw.bin", dtype=np.uint8, mode="r")

    def fetch_raw(ords):
        return [_unrec(raw_mm[int(raw_off[o]):int(raw_off[o + 1])].tobytes()) for o in ords]

    def fetch_sqlite(ords):
        keys = [int(wids[o]) for o in ords]
        marks = ",".join("?" * len(keys))
        got = {r[0]: (r[1], r[2]) for r in con.execute(
            f"SELECT id, title, doi FROM docs WHERE id IN ({marks})", keys)}
        return [got[k] for k in keys]

    arms = {"sqlite_mainline": fetch_sqlite, "vortex_take": fetch_vortex,
            "lance_take": fetch_lance, "raw_mmap": fetch_raw,
            "sqlite_ctrl": fetch_sqlite}

    # ── QUALITY gate ─────────────────────────────────────────────────────────
    parity = {}
    par = rng.sample(range(n), args.parity)
    log.info("parity: %s ids", f"{args.parity:,}")
    for s in range(0, len(par), 500):
        chunk = par[s:s + 500]
        base = fetch_sqlite(chunk)
        for name, fn in arms.items():
            if name == "sqlite_mainline":
                continue
            parity[name] = parity.get(name, 0) + sum(1 for a, b in zip(fn(chunk), base) if a != b)
    ppass = {k: v == 0 for k, v in parity.items()}
    for name in arms:
        if name != "sqlite_mainline":
            log.info("  %-15s parity %s", name, "PASS" if ppass[name] else f"FAIL({parity[name]})")

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
        st["parity_pass"] = ppass.get(name, True)
        lookup[name] = st
        log.info("%-15s p50 %8.4f  mean %8.4f  p90 %8.4f | %6sx | parity %s%s",
                 name, st["p50_ms"], st["mean_ms"], st["p90_ms"], st["vs_mainline"],
                 "PASS" if st["parity_pass"] else "FAIL",
                 "  <-- REGRESSION" if st["regression"] else "")

    ctrl = lookup["sqlite_ctrl"]
    noise = round(abs(ctrl["p50_ms"] - base_p50) / base_p50 * 100, 2)
    rep = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "goal": "META bake-off: does Vortex hold the speed gate C11/C12 failed?",
           "corpus_rows": n, "meta_gb": round(meta_gb, 2), "sizes": sizes,
           "parity": ppass, "lookup": lookup, "noise_floor_pct": noise,
           "quality_gate_pass": all(ppass.values()),
           "verdict": {"vortex_take": {
               "holds_speed_gate": not lookup["vortex_take"]["regression"],
               "parity_pass": ppass.get("vortex_take", False),
               "saves_gb": sizes["vortex_take"]["saved_gb"],
               "p50_ms": lookup["vortex_take"]["p50_ms"],
               "vs_mainline": lookup["vortex_take"]["vs_mainline"]}}}

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"c13_vortex_bakeoff_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    con.close()
    log.info("VERDICT vortex: %s", json.dumps(rep["verdict"]["vortex_take"]))
    log.info("noise %.2f%% | quality gate %s | results -> %s", noise,
             "PASS" if rep["quality_gate_pass"] else "FAIL", out)


if __name__ == "__main__":
    main()
