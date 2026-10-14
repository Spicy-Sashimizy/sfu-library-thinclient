#!/usr/bin/env python3
"""N5 — C3's block half, built for real: flat zstd block file + parity gate.

Doc 17 §11 measured C3 as a SPLIT verdict:

  * locator -> tantivy  : REJECTED, 27-54x slower on that stage
  * blocks  -> flat file: 3.81-3.88x faster on the stage that is 93% of the cost

but the flat-file arm was a FLOOR measurement (random `pread` of the average
block size against a file of production size), not a built store. §11 explicitly
listed "build the flat file for one section, re-measure fetch() end-to-end, and
gate on byte-parity" as required before shipping. This does that.

Design (exactly §11's verdict, nothing more):

  blocks.bin        concatenated compressed block payloads, byte-identical to
                    what `blocks.z` holds today -- the trained per-script zstd
                    dictionaries and the ~32 KB block layout are UNTOUCHED.
                    §11: payload is 83% of the store; losing the codec would
                    cost more than the envelope saves.
  block_index.npy   b -> (offset, length, dict_id), a dense array indexed by
                    block id. Block ids are sparse in production, so missing
                    slots carry offset = -1.
  dicts.json        the `meta` table's trained dictionaries, copied verbatim.
  locator           STAYS IN SQLITE. §11 measured that moving it is a
                    regression; N5 deliberately does not touch it.

The parity gate is the point of the exercise: every abstract returned by the
new reader must be **byte-identical** to what `AbstractStore.fetch` returns
today. Latency that is not byte-identical is not a result.

Source `abstracts.sqlite` is opened READ-ONLY. Output goes to the spike work
dir (gitignored). Nothing under `data/` is written.

    .venv/bin/python3 spike/meta_consolidation/08_n5_flat_block_store.py --build
    .venv/bin/python3 spike/meta_consolidation/08_n5_flat_block_store.py --gate --bench
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sqlite3
import statistics
import sys
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np
import zstandard

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "source"))

log = logging.getLogger("n5")

SECTION = "social_sciences__recent"
SRC = ROOT / "data" / "thinclient_index" / "sections" / SECTION / "abstracts.sqlite"
WORK = Path(__file__).parent / "work_n5"
BLOCK_CACHE = 64          # mirrors AbstractStore's reader cache exactly


def _open_ro(path: Path, cache_mb: int = 64) -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    if cache_mb:
        db.execute(f"PRAGMA cache_size=-{cache_mb * 1024}")
    return db


# ── build ────────────────────────────────────────────────────────────────────

def build(src: Path, out: Path, flush_every: int = 50_000) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    db = _open_ro(src, cache_mb=256)

    names = json.loads(db.execute("SELECT v FROM meta WHERE k='dicts'").fetchone()[0])
    dicts = {}
    for n in names:
        row = db.execute("SELECT v FROM meta WHERE k=?", (f"zdict_{n}",)).fetchone()
        if row:
            dicts[n] = row[0].hex()
    (out / "dicts.json").write_text(json.dumps({"names": names, "dicts": dicts}))
    log.info("copied %d trained dictionaries: %s", len(dicts), names)

    max_b = db.execute("SELECT max(b) FROM blocks").fetchone()[0]
    n_slots = max_b + 1
    offsets = np.full(n_slots, -1, dtype=np.int64)
    lengths = np.zeros(n_slots, dtype=np.int32)
    dict_ids = np.zeros(n_slots, dtype=np.int8)

    t0 = time.perf_counter()
    pos = 0
    n = 0
    with open(out / "blocks.bin", "wb", buffering=1 << 22) as fout:
        # Stream in b order: sequential on both sides, no 13 GB in RAM.
        for b, d, z in db.execute("SELECT b, d, z FROM blocks ORDER BY b"):
            fout.write(z)
            offsets[b] = pos
            lengths[b] = len(z)
            dict_ids[b] = d
            pos += len(z)
            n += 1
            if n % flush_every == 0:
                log.info("  %d blocks, %.2f GB", n, pos / 1e9)
    np.save(out / "block_offsets.npy", offsets)
    np.save(out / "block_lengths.npy", lengths)
    np.save(out / "block_dictids.npy", dict_ids)

    idx_bytes = sum((out / f).stat().st_size for f in
                    ("block_offsets.npy", "block_lengths.npy", "block_dictids.npy"))
    return {"blocks": n, "slots": n_slots,
            "blocks_bin_bytes": (out / "blocks.bin").stat().st_size,
            "index_bytes": idx_bytes,
            "build_s": round(time.perf_counter() - t0, 1)}


# ── readers ──────────────────────────────────────────────────────────────────

class FlatStore:
    """C3's block half: locator from SQLite, payload from the flat file."""

    def __init__(self, src: Path, flat: Path, cache_mb: int = 64):
        self.db = _open_ro(src, cache_mb)          # locator only
        meta = json.loads((flat / "dicts.json").read_text())
        plain = zstandard.ZstdDecompressor()
        latin = meta["dicts"].get("latin")
        latin_d = (zstandard.ZstdCompressionDict(bytes.fromhex(latin))
                   if latin else None)
        self.dctxs = {}
        for i, name in enumerate(meta["names"]):
            h = meta["dicts"].get(name)
            zd = (zstandard.ZstdCompressionDict(bytes.fromhex(h)) if h else latin_d)
            self.dctxs[i] = (zstandard.ZstdDecompressor(dict_data=zd) if zd else plain)
        self.off = np.load(flat / "block_offsets.npy", mmap_mode="r")
        self.len = np.load(flat / "block_lengths.npy", mmap_mode="r")
        self.did = np.load(flat / "block_dictids.npy", mmap_mode="r")
        self.fd = os.open(str(flat / "blocks.bin"), os.O_RDONLY)
        self._cache: OrderedDict[int, bytes] = OrderedDict()

    def _block(self, b: int) -> bytes:
        hit = self._cache.get(b)
        if hit is not None:
            self._cache.move_to_end(b)
            return hit
        z = os.pread(self.fd, int(self.len[b]), int(self.off[b]))
        payload = self.dctxs.get(int(self.did[b]), self.dctxs[0]).decompress(z)
        self._cache[b] = payload
        if len(self._cache) > BLOCK_CACHE:
            self._cache.popitem(last=False)
        return payload

    def fetch(self, ids: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for s in range(0, len(ids), 500):
            chunk = ids[s:s + 500]
            marks = ",".join("?" * len(chunk))
            for doc_id, b, off, n in self.db.execute(
                    f"SELECT id, b, off, n FROM docs WHERE id IN ({marks})", chunk):
                out[doc_id] = self._block(b)[off:off + n].decode("utf-8")
        return out


def production_store():
    from lib.thinclient.abstracts import AbstractStore
    return AbstractStore(SRC)


def reservoir_ids(db: sqlite3.Connection, k: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    res: list[str] = []
    for n, (doc_id,) in enumerate(db.execute("SELECT id FROM docs"), 1):
        if len(res) < k:
            res.append(doc_id)
        else:
            j = rng.randrange(n)
            if j < k:
                res[j] = doc_id
    return res


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
            "min_ms": round(s[0], 2), "max_ms": round(s[-1], 2)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--gate", action="store_true", help="byte-parity gate")
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--gate-n", type=int, default=20000)
    ap.add_argument("--sizes", type=int, nargs="+", default=[10, 50, 100])
    ap.add_argument("--reps", type=int, default=9)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--pool", type=int, default=30000)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    rep = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"), "section": SECTION,
           "source_bytes": SRC.stat().st_size}

    if args.build:
        log.info("extracting blocks -> flat file (source is read-only)…")
        rep["build"] = build(SRC, args.work)
        log.info("built: %s", rep["build"])
        (args.work / "build_report.json").write_text(json.dumps(rep, indent=2))

    if not (args.gate or args.bench):
        return

    flat = FlatStore(SRC, args.work)
    prod = production_store()
    pool = reservoir_ids(flat.db, args.pool, args.seed)
    log.info("sampled %d ids", len(pool))

    if args.gate:
        rng = random.Random(args.seed + 5)
        ids = rng.sample(pool, min(args.gate_n, len(pool)))
        t0 = time.perf_counter()
        a = prod.fetch(ids)
        b = flat.fetch(ids)
        same_keys = set(a) == set(b)
        mismatch = [i for i in a if a[i] != b.get(i)]
        g = {"ids_checked": len(ids), "production_returned": len(a),
             "flat_returned": len(b), "same_id_set": same_keys,
             "byte_identical": (not mismatch), "n_mismatched": len(mismatch),
             "example": (mismatch[:3] if mismatch else None),
             "seconds": round(time.perf_counter() - t0, 1)}
        rep["parity_gate"] = g
        if same_keys and not mismatch:
            log.info("PARITY GATE PASS — %d ids byte-identical", len(ids))
        else:
            log.error("PARITY GATE FAIL — %s", g)

    if args.bench:
        rng = random.Random(args.seed + 1)
        rep["bench"] = {}
        for k in args.sizes:
            need = args.reps + args.warmup
            picks = rng.sample(pool, k * need)
            lists = [picks[i * k:(i + 1) * k] for i in range(need)]
            p = timeit(prod.fetch, lists, args.reps, args.warmup)
            f = timeit(flat.fetch, lists, args.reps, args.warmup)
            e = {"production_sqlite": p, "flat_block_file": f,
                 "speedup": round(p["p50_ms"] / f["p50_ms"], 2) if f["p50_ms"] else None}
            rep["bench"][str(k)] = e
            log.info("k=%-5d production %.2f ms | flat %.2f ms | %.2fx faster",
                     k, p["p50_ms"], f["p50_ms"], e["speedup"])

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"n5_flat_blocks_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    log.info("results -> %s", out)


if __name__ == "__main__":
    main()
