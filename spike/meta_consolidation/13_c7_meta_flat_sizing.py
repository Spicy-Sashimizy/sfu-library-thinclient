#!/usr/bin/env python3
"""C7 — can `meta.sqlite` be DELETED? Size and speed of a flat title/DOI store.

**The goal here is CONSOLIDATION, not latency.** Doc 17 §13 promised "separate
storage databases 4 -> 0, SQLite leaves the container entirely". Doc 18 §13 then
rejected the title/DOI half of that on *latency* grounds -- `hydrate_meta` is
4.1% of the query, so replacing it could not pay for itself. That rejection was
correct against a latency objective and **irrelevant against a consolidation
objective**: the question is not "how much faster", it is "does this let us drop
a 24.9 GB SQLite database, and what does it cost in bytes".

`meta.sqlite` is `docs(id INTEGER PRIMARY KEY, title, doi, year, type, is_oa,
section)`. The filter fields -- `year`, `type`, `is_oa`, `section` -- are
ALREADY flat ordinal columns (doc 18 §12, 0.75 GB). `docs_other` is **empty**
(0 rows, measured 2026-08-03), so the TEXT-overflow path costs nothing. So
deleting `meta.sqlite` reduces to exactly one question: **what does a flat,
ordinal-indexed `title` + `doi` store cost?**

**THE GATE IS NO-REGRESSION, NOT SPEEDUP** (operator constraint, 2026-08-03):
consolidation must leave serving performance *identical to mainline*. It does
not need to be faster. It must not be slower. That constraint is what decides
between the two designs measured here, because they trade size against speed in
opposite directions:

  design A  `raw`     fixed-width offsets into an uncompressed mmap'd blob.
                      A lookup is one random read. Big, but as fast as a
                      page-cache hit gets.
  design B  `zstd`    the shipped abstracts-v3 pattern: ~32 KB blocks in
                      ORDINAL order, zstd-19 with a trained dictionary, one
                      `(start_ordinal, file_offset)` entry per block. Much
                      smaller, but a lookup must decompress a whole block, and
                      50 scattered hits touch ~50 different blocks.
  design C  `perdoc`  the shipped abstracts-**v1/v2** pattern: each record
                      compressed on its own against the same trained dict,
                      u64 offsets like design A. A lookup decompresses 115
                      bytes, not 32 KB. Added 2026-08-03 after the first run
                      measured B at 16x mainline: block amplification is
                      ~284 docs decompressed to read one, and `_hydrate`'s ids
                      are scattered, so the block design's whole advantage is
                      unreachable here. Abstracts can afford blocks because a
                      1.5 KB abstract amortises them; a 115 B record cannot.

Design B is also what doc 17 §13 called "C3's locator problem solved without
tantivy or SQLite": because records sit in ordinal order, the locator is one
small per-block array rather than a per-doc `(block, off, len)` triple. That is
the difference between a ~5 MB locator and a ~1.2 GB one, and it is only
available *because* ordinals exist.

**Baseline is the real one.** Every measurement is compared against the shipped
`retriever._meta_rows` SQLite path on the SAME ids, and titles/DOIs must match
it exactly -- a smaller store that returns different strings is not a result.
The SQLite side reads the STAGED copy (local disk), which per doc 18 §14 is what
production actually looks like; measuring against the 9p copy would flatter
these designs by a factor of ~50 and reproduce exactly the mistake §14 corrects.

This script MEASURES ONLY. It builds its stores under `--work` and writes no
production artifact. `meta.sqlite` is opened `mode=ro`.

    .venv/bin/python3 spike/meta_consolidation/13_c7_meta_flat_sizing.py \
        --meta /var/tmp/meta_stage/meta.sqlite --sample 1000000
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import shutil
import sqlite3
import statistics
import struct
import sys
import time
from pathlib import Path

import numpy as np
import zstandard

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "source"))

CORPUS_ROWS = 150_413_098          # doc 18 §12, measured
DICT_SIZE = 112 * 1024             # abstracts.py:49
COMPRESSION_LEVEL = 19             # abstracts.py:50
BLOCK_TARGET = 32 * 1024           # abstracts.py:51
TRAIN_TARGET_DOCS = 20_000         # abstracts.py:52

log = logging.getLogger("c7")


def _rec(title: str | None, doi: str | None) -> bytes:
    """One record: title and doi, NUL-separated. Both are nullable in the
    schema, and a NULL must survive the round trip distinguishably from an
    empty string, or hydrate would start reporting '' where mainline reports
    None. Sentinel: a lone 0xFF byte."""
    t = b"\xff" if title is None else title.encode("utf-8")
    d = b"\xff" if doi is None else doi.encode("utf-8")
    return t + b"\x00" + d


def _unrec(buf: bytes) -> tuple[str | None, str | None]:
    t, _, d = buf.partition(b"\x00")
    return (None if t == b"\xff" else t.decode("utf-8"),
            None if d == b"\xff" else d.decode("utf-8"))


def _stat(samples: list[float]) -> dict:
    s = sorted(samples)
    return {"n": len(s), "p50_ms": round(statistics.median(s), 4),
            "mean_ms": round(statistics.fmean(s), 4),
            "p90_ms": round(s[min(len(s) - 1, int(0.9 * len(s)))], 4)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meta", type=Path,
                    default=Path("/var/tmp/meta_stage/meta.sqlite"),
                    help="staged (local-disk) meta.sqlite — NOT the 9p copy")
    ap.add_argument("--work", type=Path,
                    default=Path("/var/tmp/c7_meta_flat"))
    ap.add_argument("--sample", type=int, default=1_000_000,
                    help="total rows to build the trial stores from")
    ap.add_argument("--runs", type=int, default=20,
                    help="contiguous windows spread across the id space; >1 "
                         "because id IS the W-id, so a head sample is all "
                         "oldest works and biases the size projection")
    ap.add_argument("--lookups", type=int, default=200,
                    help="lookup trials; each fetches --hits ids")
    ap.add_argument("--hits", type=int, default=50,
                    help="ids per lookup — production top_k")
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    rng = random.Random(args.seed)
    args.work.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(f"file:{args.meta}?mode=ro", uri=True)

    # ── pull contiguous runs spread across the WHOLE id space ───────────────
    # Contiguous runs, not one head run and not a random scatter:
    #   * contiguity is required, or design B's block layout (records in
    #     ordinal order) is not reproduced and its locator is mispriced;
    #   * spread is required, because `id` IS the numeric W-id, so the first
    #     N rows are the OLDEST OpenAlex works. The first run of this spike
    #     sampled the head and got 115.1 B/doc; title length, language mix and
    #     DOI patterns all drift with work age, so a head sample would bias
    #     every size projection here. Measured over `--runs` windows instead.
    lo_id, hi_id = con.execute("SELECT min(id), max(id) FROM docs").fetchone()
    per_run = max(1, args.sample // args.runs)
    log.info("reading %d runs x %s rows spread over id %d..%d",
             args.runs, f"{per_run:,}", lo_id, hi_id)
    t0 = time.perf_counter()
    rows: list = []
    for r in range(args.runs):
        start = lo_id + (hi_id - lo_id) * r // args.runs
        rows.extend(con.execute(
            "SELECT id, title, doi FROM docs WHERE id >= ? ORDER BY id LIMIT ?",
            (start, per_run)).fetchall())
    rows.sort(key=lambda x: x[0])
    log.info("  read %s rows in %.1f s", f"{len(rows):,}",
             time.perf_counter() - t0)
    if len(rows) < args.sample * 0.9:
        log.warning("only %d rows available", len(rows))

    ids = [r[0] for r in rows]
    recs = [_rec(r[1], r[2]) for r in rows]
    raw_bytes = sum(len(b) for b in recs)
    n = len(recs)
    log.info("payload: %.1f MB raw, mean %.1f B/doc",
             raw_bytes / 1e6, raw_bytes / n)

    rep = {
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "goal": ("CONSOLIDATION: can meta.sqlite be deleted? Doc 18 §13 "
                 "rejected this on latency grounds, which is the wrong "
                 "objective for a consolidation goal."),
        "gate": ("NO-REGRESSION vs mainline SQLite, not speedup (operator "
                 "constraint 2026-08-03). Must not be slower; need not be "
                 "faster."),
        "corpus_rows": CORPUS_ROWS,
        "sample_rows": n,
        "meta_path": str(args.meta),
        "meta_bytes": args.meta.stat().st_size,
        "docs_other_rows": con.execute(
            "SELECT count(*) FROM docs_other").fetchone()[0],
        "payload_raw_bytes_per_doc": round(raw_bytes / n, 2),
        "designs": {}, "lookup": {}, "parity": {},
    }

    # ── design A: uncompressed blob + u64 offsets ───────────────────────────
    a_blob = args.work / "a_raw.bin"
    with a_blob.open("wb") as fh:
        offs = np.zeros(n + 1, dtype=np.uint64)
        pos = 0
        for i, b in enumerate(recs):
            offs[i] = pos
            fh.write(b)
            pos += len(b)
        offs[n] = pos
    np.save(args.work / "a_offsets.npy", offs)
    a_payload = a_blob.stat().st_size
    a_locator = (args.work / "a_offsets.npy").stat().st_size
    rep["designs"]["raw"] = {
        "payload_bytes_per_doc": round(a_payload / n, 3),
        "locator_bytes_per_doc": round(a_locator / n, 3),
        "total_bytes_per_doc": round((a_payload + a_locator) / n, 3),
        "projected_total_gb": round((a_payload + a_locator) / n * CORPUS_ROWS / 1e9, 2),
        "note": "u64 offsets; a lookup is one mmap random read, no decompress",
    }

    # ── design B: 32 KB zstd-dict blocks in ordinal order ───────────────────
    # Dictionary trained on a sample of records, exactly as abstracts.py does.
    train = [recs[i] for i in rng.sample(range(n), min(TRAIN_TARGET_DOCS, n))]
    log.info("training zstd dictionary on %d records", len(train))
    zdict = zstandard.train_dictionary(DICT_SIZE, train)
    cctx = zstandard.ZstdCompressor(level=COMPRESSION_LEVEL, dict_data=zdict)

    b_blob = args.work / "b_blocks.bin"
    block_start_ord: list[int] = []     # first ordinal in each block
    block_file_off: list[int] = []      # byte offset of each block
    log.info("packing ~%d KB blocks at zstd-%d", BLOCK_TARGET // 1024,
             COMPRESSION_LEVEL)
    t0 = time.perf_counter()
    with b_blob.open("wb") as fh:
        buf: list[bytes] = []
        buf_bytes = 0
        first = 0

        def flush(first_ord: int, items: list[bytes]) -> None:
            if not items:
                return
            # Block layout: u32 count, then u32 end-offsets, then payloads.
            # End-offsets (not start) so record i is [end[i-1], end[i]) with a
            # single implicit 0 — one less field to get wrong.
            ends, acc = [], 0
            for it in items:
                acc += len(it)
                ends.append(acc)
            head = struct.pack("<I", len(items)) + struct.pack(
                f"<{len(ends)}I", *ends)
            block_start_ord.append(first_ord)
            block_file_off.append(fh.tell())
            fh.write(cctx.compress(head + b"".join(items)))

        for i, b in enumerate(recs):
            if buf_bytes + len(b) > BLOCK_TARGET and buf:
                flush(first, buf)
                buf, buf_bytes, first = [], 0, i
            buf.append(b)
            buf_bytes += len(b)
        flush(first, buf)
    log.info("  packed %d blocks in %.1f s", len(block_start_ord),
             time.perf_counter() - t0)

    starts = np.asarray(block_start_ord, dtype=np.int64)
    boffs = np.asarray(block_file_off, dtype=np.int64)
    np.save(args.work / "b_block_start.npy", starts)
    np.save(args.work / "b_block_off.npy", boffs)
    b_payload = b_blob.stat().st_size
    b_locator = (starts.nbytes + boffs.nbytes)
    b_dict = len(zdict.as_bytes())
    rep["designs"]["zstd_blocks"] = {
        "blocks": len(starts),
        "docs_per_block": round(n / len(starts), 1),
        "payload_bytes_per_doc": round(b_payload / n, 3),
        "locator_bytes_per_doc": round(b_locator / n, 4),
        "dict_bytes": b_dict,
        "total_bytes_per_doc": round((b_payload + b_locator) / n, 3),
        "projected_total_gb": round(
            ((b_payload + b_locator) / n * CORPUS_ROWS + b_dict) / 1e9, 2),
        "note": ("ordinal-ordered blocks => locator is one (start,off) pair "
                 "PER BLOCK, not per doc — doc 17 §13's 'C3 locator solved "
                 "without tantivy or SQLite'. A lookup decompresses a block."),
    }

    # ── design C: per-record zstd against the same trained dict ─────────────
    # Same locator as design A (u64 offsets); only the payload differs. This is
    # the abstracts v1/v2 shape, and it exists because design B's block
    # amplification (~284 docs decompressed per lookup) is fatal for records
    # this small.
    c_blob = args.work / "c_perdoc.bin"
    with c_blob.open("wb") as fh:
        c_offs = np.zeros(n + 1, dtype=np.uint64)
        pos = 0
        for i, b in enumerate(recs):
            c_offs[i] = pos
            enc = cctx.compress(b)
            fh.write(enc)
            pos += len(enc)
        c_offs[n] = pos
    np.save(args.work / "c_offsets.npy", c_offs)
    c_payload = c_blob.stat().st_size
    c_locator = (args.work / "c_offsets.npy").stat().st_size
    rep["designs"]["zstd_perdoc"] = {
        "payload_bytes_per_doc": round(c_payload / n, 3),
        "locator_bytes_per_doc": round(c_locator / n, 3),
        "dict_bytes": b_dict,
        "total_bytes_per_doc": round((c_payload + c_locator) / n, 3),
        "projected_total_gb": round(
            ((c_payload + c_locator) / n * CORPUS_ROWS + b_dict) / 1e9, 2),
        "note": ("abstracts v1/v2 shape: one record decompressed per lookup, "
                 "not a 32 KB block; same u64 locator as `raw`"),
    }

    # ── lookup: the no-regression gate ──────────────────────────────────────
    # Trials fetch `--hits` ids drawn from the sampled range, mirroring a
    # production `_hydrate` on top_k results. Ids are scattered, which is the
    # hard case for design B: ~50 hits touch ~50 distinct blocks.
    trials = [rng.sample(range(n), args.hits) for _ in range(args.lookups)]

    a_off = np.load(args.work / "a_offsets.npy", mmap_mode="r")
    a_mm = np.memmap(a_blob, dtype=np.uint8, mode="r")

    def fetch_raw(ords: list[int]) -> list[tuple]:
        out = []
        for o in ords:
            lo, hi = int(a_off[o]), int(a_off[o + 1])
            out.append(_unrec(a_mm[lo:hi].tobytes()))
        return out

    dctx = zstandard.ZstdDecompressor(dict_data=zdict)
    b_fh = b_blob.open("rb")
    b_end = b_payload

    def fetch_zstd(ords: list[int]) -> list[tuple]:
        out = []
        for o in ords:
            bi = int(np.searchsorted(starts, o, side="right")) - 1
            lo = int(boffs[bi])
            hi = int(boffs[bi + 1]) if bi + 1 < len(boffs) else b_end
            b_fh.seek(lo)
            raw = dctx.decompress(b_fh.read(hi - lo))
            cnt = struct.unpack_from("<I", raw, 0)[0]
            ends = struct.unpack_from(f"<{cnt}I", raw, 4)
            base = 4 + 4 * cnt
            j = o - int(starts[bi])
            s = 0 if j == 0 else ends[j - 1]
            out.append(_unrec(raw[base + s: base + ends[j]]))
        return out

    def fetch_sqlite(ords: list[int]) -> list[tuple]:
        keys = [ids[o] for o in ords]
        marks = ",".join("?" * len(keys))
        got = {r[0]: (r[1], r[2]) for r in con.execute(
            f"SELECT id, title, doi FROM docs WHERE id IN ({marks})", keys)}
        return [got[k] for k in keys]

    c_off = np.load(args.work / "c_offsets.npy", mmap_mode="r")
    c_mm = np.memmap(c_blob, dtype=np.uint8, mode="r")

    def fetch_perdoc(ords: list[int]) -> list[tuple]:
        out = []
        for o in ords:
            lo, hi = int(c_off[o]), int(c_off[o + 1])
            out.append(_unrec(dctx.decompress(c_mm[lo:hi].tobytes())))
        return out

    arms = {"sqlite_mainline": fetch_sqlite, "raw": fetch_raw,
            "zstd_blocks": fetch_zstd, "zstd_perdoc": fetch_perdoc}
    for name, fn in arms.items():            # warm each arm
        for t in trials[:10]:
            fn(t)

    samples: dict[str, list[float]] = {k: [] for k in arms}
    mismatch = {k: 0 for k in arms}
    for t in trials:
        order = list(arms)
        rng.shuffle(order)                   # interleaved, randomised per trial
        got = {}
        for name in order:
            t0 = time.perf_counter()
            got[name] = arms[name](t)
            samples[name].append((time.perf_counter() - t0) * 1000)
        base = got["sqlite_mainline"]
        for name in arms:
            if got[name] != base:
                mismatch[name] += 1

    base_p50 = statistics.median(samples["sqlite_mainline"])
    for name in arms:
        st = _stat(samples[name])
        st["vs_mainline"] = (round(st["p50_ms"] / base_p50, 3)
                             if base_p50 else None)
        st["regression"] = bool(st["p50_ms"] > base_p50)
        rep["lookup"][name] = st
        rep["parity"][name] = {"trials": len(trials),
                               "mismatches": mismatch[name],
                               "pass": mismatch[name] == 0}
        log.info("%-16s p50 %7.4f ms (%.2fx mainline) | parity %s", name,
                 st["p50_ms"], st["vs_mainline"] or 0,
                 "PASS" if mismatch[name] == 0 else f"FAIL({mismatch[name]})")

    b_fh.close()

    # ── the consolidation arithmetic ────────────────────────────────────────
    filt_gb = 0.75          # doc 18 §12: year+dtype+is_oa+section columns
    wids_gb = 1.20          # doc 18 §12
    for name in ("raw", "zstd_blocks", "zstd_perdoc"):
        d = rep["designs"][name]
        d["meta_sqlite_replacement_gb"] = round(
            d["projected_total_gb"] + filt_gb + wids_gb, 2)
        d["vs_meta_sqlite_gb"] = round(
            rep["meta_bytes"] / 1e9 - d["meta_sqlite_replacement_gb"], 2)
    rep["note_existing_ordinal_artifacts_gb"] = {
        "filter_columns": filt_gb, "wids": wids_gb,
        "source": "doc 18 §12 (already built, 1.96 GB total)"}

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"c7_meta_flat_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    log.info("results -> %s", out)
    for name in ("raw", "zstd_blocks", "zstd_perdoc"):
        d = rep["designs"][name]
        log.info("%-12s projected %5.2f GB payload+locator | full replacement "
                 "%5.2f GB vs meta.sqlite %.2f GB (saves %.2f)", name,
                 d["projected_total_gb"], d["meta_sqlite_replacement_gb"],
                 rep["meta_bytes"] / 1e9, d["vs_meta_sqlite_gb"])
    shutil.rmtree(args.work, ignore_errors=True)   # trial stores are disposable


if __name__ == "__main__":
    main()
