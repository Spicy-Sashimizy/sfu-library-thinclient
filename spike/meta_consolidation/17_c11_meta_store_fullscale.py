#!/usr/bin/env python3
"""C11 — the meta.sqlite GATE: build C7's title/DOI store at FULL 150.4M and measure.

C7 (doc 18 §15) measured a `zstd_perdoc` title/DOI store at a 1M-row sample and
projected -10.22 GB at 0.70x mainline. §15's own NOT-SETTLED #1 says that 0.70x
is **not a result**: it is a 1M-doc, page-cache-resident extrapolation, and this
project has been wrong on exactly that class of extrapolation by 96x (the filter
stage: 4.15 ms at 208k docs, 400 ms at 150M). Size extrapolates linearly and is
trustworthy; latency does not. So before any MetaStore reader is written, the
store has to be BUILT at full scale and its latency re-measured, staged, with
§14 arm discipline. That is this script, and nothing else.

The winning design (C7 §15): each `title\\x00doi` record compressed on its own
against one trained zstd-19 dict, u64 offsets, indexed by the GLOBAL ordinal
(doc 18 §12) — records stream in `docs.id` order, which IS ordinal order, so
`offsets[ordinal]` addresses the record with no per-doc key stored here. The
store therefore binds to the ordinal space's identity, not its own.

Streaming build: never holds the corpus in RAM (only the u64 offsets, 1.2 GB).
Verifies streamed id == wids[ordinal] as it goes — if the meta table and the
ordinal space ever disagree on order, every offset addresses the wrong record,
which is doc 18 §6 risk 1 and must fail the build, not ship.

Read-only against meta.sqlite (mode=ro) and the ordinal arrays. Builds under
--work; this MEASURES, it does not wire anything.

    .venv/bin/python3 spike/meta_consolidation/17_c11_meta_store_fullscale.py \
        --meta /var/tmp/meta_stage/meta.sqlite --ordinals /var/tmp/ordinals_stage
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
import zstandard

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "source"))

DICT_SIZE = 112 * 1024
COMPRESSION_LEVEL = 19
TRAIN_TARGET_DOCS = 20_000

log = logging.getLogger("c11")


def _rec(title, doi) -> bytes:
    """title\\x00doi, with a lone 0xFF sentinel for SQL NULL so it round-trips
    distinguishably from '' (mainline reports None, not '')."""
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
    ap.add_argument("--work", type=Path, default=Path("/var/tmp/c11_meta_store"))
    ap.add_argument("--level", type=int, default=COMPRESSION_LEVEL)
    ap.add_argument("--lookups", type=int, default=200)
    ap.add_argument("--hits", type=int, default=50)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    rng = random.Random(args.seed)
    args.work.mkdir(parents=True, exist_ok=True)

    from lib.thinclient.retriever import _fstype_for_path

    wids = np.load(args.ordinals / "wids.npy", mmap_mode="r")
    n = len(wids)
    log.info("ordinal space: %s rows, meta on %s, ordinals on %s", f"{n:,}",
             _fstype_for_path(str(args.meta)), _fstype_for_path(str(args.ordinals)))

    con = sqlite3.connect(f"file:{args.meta}?mode=ro", uri=True)
    docs_other = con.execute("SELECT count(*) FROM docs_other").fetchone()[0]
    n_docs = con.execute("SELECT count(*) FROM docs").fetchone()[0]
    if n_docs != n:
        raise SystemExit(f"docs has {n_docs} rows but the ordinal space has {n} "
                         f"— they are not the same build; offsets would misalign")

    blob = args.work / "title_doi.bin"
    offs_path = args.work / "title_doi_offsets.npy"
    dict_path = args.work / "title_doi.zdict"

    rep = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "goal": "META GATE: full-150.4M title/DOI store latency (convert §15's extrapolation)",
           "gate": "no-regression vs staged meta.sqlite; size ~= §15 projection",
           "meta_path": str(args.meta), "meta_bytes": args.meta.stat().st_size,
           "meta_fstype": _fstype_for_path(str(args.meta)),
           "corpus_rows": n, "docs_other_rows": docs_other, "level": args.level}

    if not (args.skip_build and blob.exists() and offs_path.exists()):
        # ── train the dict on a spread sample (id IS the W-id: a head sample is
        # the oldest works and biases title length / DOI patterns — §15) ──────
        lo_id, hi_id = con.execute("SELECT min(id), max(id) FROM docs").fetchone()
        train = []
        for r in range(20):
            start = lo_id + (hi_id - lo_id) * r // 20
            train.extend(_rec(t, d) for _, t, d in con.execute(
                "SELECT id, title, doi FROM docs WHERE id >= ? ORDER BY id LIMIT ?",
                (start, TRAIN_TARGET_DOCS // 20)))
        log.info("training zstd dict on %d records", len(train))
        zdict = zstandard.train_dictionary(DICT_SIZE, train)
        dict_path.write_bytes(zdict.as_bytes())
        cctx = zstandard.ZstdCompressor(level=args.level, dict_data=zdict)

        # ── stream the full build, verifying ordinal order as we go ──────────
        log.info("streaming build of %s records at zstd-%d", f"{n:,}", args.level)
        offsets = np.zeros(n + 1, dtype=np.uint64)
        t0 = time.perf_counter()
        pos = i = 0
        tmp = args.work / "title_doi.bin.partial"
        with open(tmp, "wb", buffering=1 << 22) as fh:
            for did, title, doi in con.execute(
                    "SELECT id, title, doi FROM docs ORDER BY id"):
                if did != int(wids[i]):
                    raise SystemExit(
                        f"row {i}: docs.id {did} != wids[{i}] {int(wids[i])} — "
                        f"the meta table and the ordinal space disagree on "
                        f"order; every offset past here addresses the wrong "
                        f"record (doc 18 §6 risk 1). Build ABORTED.")
                offsets[i] = pos
                enc = cctx.compress(_rec(title, doi))
                fh.write(enc)
                pos += len(enc)
                i += 1
                if i % 5_000_000 == 0:
                    log.info("  %s / %s docs, %.2f GB, %.0f docs/s", f"{i:,}",
                             f"{n:,}", pos / 1e9, i / (time.perf_counter() - t0))
        if i != n:
            raise SystemExit(f"streamed {i} docs but ordinal space has {n}")
        offsets[n] = pos
        np.save(offs_path, offsets)
        tmp.rename(blob)
        secs = time.perf_counter() - t0
        rep["build"] = {"seconds": round(secs, 1), "docs_per_s": round(n / secs),
                        "payload_bytes": int(pos)}
        log.info("built %.2f GB payload in %.0f s (%.0f docs/s)", pos / 1e9, secs, n / secs)

    # ── sizes + the consolidation arithmetic ─────────────────────────────────
    payload = blob.stat().st_size
    locator = offs_path.stat().st_size
    dict_b = dict_path.stat().st_size
    filt_gb, wids_gb = 0.75, 1.20                 # doc 18 §12 (already built)
    store_gb = (payload + locator + dict_b) / 1e9
    replacement_gb = store_gb + filt_gb + wids_gb
    rep["sizes"] = {
        "title_doi_payload_gb": round(payload / 1e9, 3),
        "offsets_locator_gb": round(locator / 1e9, 3),
        "dict_mb": round(dict_b / 1e6, 3),
        "payload_bytes_per_doc": round(payload / n, 2),
        "title_doi_store_gb": round(store_gb, 2),
        "meta_replacement_gb": round(replacement_gb, 2),
        "meta_sqlite_gb": round(rep["meta_bytes"] / 1e9, 2),
        "saved_gb": round(rep["meta_bytes"] / 1e9 - replacement_gb, 2),
        "note": "replacement = title/doi store + §12 filter cols (0.75) + wids (1.20)",
    }
    log.info("SIZE: store %.2f GB + filter 0.75 + wids 1.20 = %.2f GB replaces "
             "meta.sqlite %.2f GB (saves %.2f GB)", store_gb, replacement_gb,
             rep["meta_bytes"] / 1e9, rep["sizes"]["saved_gb"])

    # ── the latency GATE: perdoc store vs staged meta.sqlite, §14 discipline ──
    zdict = zstandard.ZstdCompressionDict(dict_path.read_bytes())
    dctx = zstandard.ZstdDecompressor(dict_data=zdict)
    off = np.load(offs_path, mmap_mode="r")
    mm = np.memmap(blob, dtype=np.uint8, mode="r")

    def fetch_store(ords):
        out = []
        for o in ords:
            lo, hi = int(off[o]), int(off[o + 1])
            out.append(_unrec(dctx.decompress(mm[lo:hi].tobytes())))
        return out

    def fetch_sqlite(ords):
        keys = [int(wids[o]) for o in ords]
        marks = ",".join("?" * len(keys))
        got = {r[0]: (r[1], r[2]) for r in con.execute(
            f"SELECT id, title, doi FROM docs WHERE id IN ({marks})", keys)}
        return [got[k] for k in keys]

    def fetch_ctrl(ords):                          # a 2nd sqlite arm = noise floor
        return fetch_sqlite(ords)

    arms = {"sqlite_mainline": fetch_sqlite, "meta_store": fetch_store,
            "sqlite_ctrl": fetch_ctrl}
    trials = [rng.sample(range(n), args.hits) for _ in range(args.lookups)]
    for fn in arms.values():
        for t in trials[:10]:
            fn(t)

    samples = {k: [] for k in arms}
    mism = {k: 0 for k in arms}
    for t in trials:
        order = list(arms)
        rng.shuffle(order)
        got = {}
        for name in order:
            t0 = time.perf_counter()
            got[name] = arms[name](t)
            samples[name].append((time.perf_counter() - t0) * 1000)
        for name in arms:
            if got[name] != got["sqlite_mainline"]:
                mism[name] += 1

    base_p50 = statistics.median(samples["sqlite_mainline"])
    for name in arms:
        st = _stat(samples[name])
        st["vs_mainline"] = round(base_p50 / st["p50_ms"], 3) if st["p50_ms"] else None
        st["regression"] = bool(statistics.median(samples[name]) > base_p50)
        st["parity_pass"] = mism[name] == 0
        rep.setdefault("lookup", {})[name] = st
        log.info("%-16s p50 %7.4f  mean %7.4f  p90 %7.4f | %.2fx | parity %s%s",
                 name, st["p50_ms"], st["mean_ms"], st["p90_ms"],
                 st["vs_mainline"] or 0, "PASS" if mism[name] == 0 else f"FAIL({mism[name]})",
                 "  <-- REGRESSION" if st["regression"] else "")
    ctrl = rep["lookup"]["sqlite_ctrl"]
    rep["noise_floor_pct"] = round(abs(ctrl["p50_ms"] - base_p50) / base_p50 * 100, 2)
    rep["parity_overall_pass"] = mism["meta_store"] == 0
    con.close()

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"c11_meta_store_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    ms = rep["lookup"]["meta_store"]
    log.info("GATE: meta_store parity %s, p50 %.3fx mainline%s, noise %.2f%%; "
             "saves %.2f GB", "PASS" if rep["parity_overall_pass"] else "FAIL",
             ms["vs_mainline"], " (REGRESSION)" if ms["regression"] else "",
             rep["noise_floor_pct"], rep["sizes"]["saved_gb"])
    log.info("results -> %s", out)


if __name__ == "__main__":
    main()
