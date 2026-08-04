#!/usr/bin/env python3
"""C8 — delete `abstracts.sqlite`: replace its LOCATOR with ordinal arrays.

**Goal is CONSOLIDATION** (doc 17 §13's "4 -> 0"), gated on the operator
constraint of 2026-08-03: **serving performance must be IDENTICAL to mainline**
— not faster, not slower.

### What is already done, and what is not

Doc 18 §9 (N5) moved the abstract **payload** out of SQLite into a flat
`blocks.bin` and measured **2.89×**. That code is SHIPPED: `abstracts.py`
has `build_flat_sidecar()` and `AbstractStore._open_flat()`, and a store is
served flat the moment its `<name>.flat/` sidecar exists. **But no section has
one built**, so none of it is realised today.

N5 also **deliberately left the locator in SQLite** (§9), because doc 17 §11
measured moving it into tantivy as a **27–54× regression**. That decision is why
N5 is a latency lever and not a space lever, and why `abstracts.sqlite` survives
even with a flat sidecar: the `docs` table is still the only way to find a
doc's bytes.

So `abstracts.sqlite` = `blocks` (payload, N5 solves) + `docs` (locator,
UNSOLVED) + `meta` (dictionaries, tiny). This spike does the locator.

### Why ordinals should win here, when tantivy lost

    CREATE TABLE docs (id TEXT PRIMARY KEY, b INTEGER, off INTEGER, n INTEGER)

**23,398,073 rows keyed by a TEXT W-id.** That is precisely the sparse-key
lookup this whole investigation is about (doc 18 §1): resolving `W2803642969`
is a *search* through a B-tree over 23.4M variable-length text keys. The
ordinal replacement is a `searchsorted` over a sorted int64 array plus three
array reads — the same trick that took `_post_filter` from 222 ms to 1.5 ms.
tantivy lost this job because it is a *search engine* being asked to do random
access; flat arrays are the right tool and were never tried.

**Section-local ordinals, not the global ones.** Only 23.4M of the corpus's
150.4M docs are in this section, so a global-ordinal-indexed array would be
84% empty (150.4M x 12 B = 1.8 GB of mostly holes). A section-local sorted
W-id array costs 23.4M x 8 B and is searched the same way. The global ordinal
space is untouched and unrequired here — this consolidation does NOT depend on
adopting ordinal addressing for the filter stage.

### Arms (all three return the same bytes or the run is void)

    mainline      abstracts.sqlite blocks + abstracts.sqlite locator
    flat_only     flat blocks.bin  + abstracts.sqlite locator   (= N5 as shipped)
    flat_ordinal  flat blocks.bin  + ordinal arrays             (= sqlite deletable)

`flat_only` is not decoration: it separates the payload win (already measured)
from the locator win (measured here), so neither can be credited to the other.
That is the §14 lesson — a two-variable change cannot be attributed.

Byte-parity against `mainline` on every trial is the gate. Abstract text that
differs is not a result no matter how fast it is.

Read-only against `data/`. Builds its artifacts under `--work`.

    .venv/bin/python3 spike/meta_consolidation/14_c8_abstract_ordinal_locator.py \
        --src /var/tmp/abs_stage/abstracts.sqlite
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
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

log = logging.getLogger("c8")


def _stat(samples: list[float]) -> dict:
    s = sorted(samples)
    return {"n": len(s), "p50_ms": round(statistics.median(s), 4),
            "mean_ms": round(statistics.fmean(s), 4),
            "p90_ms": round(s[min(len(s) - 1, int(0.9 * len(s)))], 4)}


def encode_wid(s: str) -> int | None:
    """`W123` -> 123, mirroring `builder.encode_meta_id`'s leading-zero
    rejection. Doc 18's first real bug was two encoders disagreeing on leading
    zeros, which aliased one document onto another and PASSED the verification
    read. Any id this returns None for keeps its SQLite path."""
    if len(s) > 1 and s[0] == "W":
        d = s[1:]
        if d.isdigit() and d[0] != "0":
            return int(d)
    return None


def build_ordinal_locator(src: Path, out: Path) -> dict:
    """Sorted section-local W-id array + parallel (b, off, n) columns.

    dtypes are chosen from the MEASURED maxima, not assumed: `off` is bounded
    by the ~32 KB block target and `n` by the longest abstract, and guessing
    either would silently truncate. Every column is verified full-length before
    it is written, per doc 18 §12's truncation lesson (a short column filters
    against whatever the shorter array holds instead of erroring).
    """
    out.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        n_rows = db.execute("SELECT count(*) FROM docs").fetchone()[0]
        mx_b, mx_off, mx_n = db.execute(
            "SELECT max(b), max(off), max(n) FROM docs").fetchone()
        log.info("locator: %s rows, max b=%d off=%d n=%d",
                 f"{n_rows:,}", mx_b, mx_off, mx_n)

        off_dt = np.uint16 if mx_off < 2 ** 16 else np.uint32
        n_dt = np.uint16 if mx_n < 2 ** 16 else np.uint32
        b_dt = np.uint32 if mx_b < 2 ** 32 else np.uint64

        wids = np.zeros(n_rows, dtype=np.int64)
        bs = np.zeros(n_rows, dtype=b_dt)
        offs = np.zeros(n_rows, dtype=off_dt)
        ns = np.zeros(n_rows, dtype=n_dt)

        i = 0
        skipped: list[str] = []
        for did, b, off, n in db.execute("SELECT id, b, off, n FROM docs"):
            w = encode_wid(did)
            if w is None:
                skipped.append(did)      # keeps the SQLite path; must be 0
                continue
            wids[i], bs[i], offs[i], ns[i] = w, b, off, n
            i += 1
        if skipped:
            log.warning("%d ids are not plain W-numbers (e.g. %s) — an ordinal "
                        "locator cannot address them", len(skipped), skipped[:3])
        wids, bs, offs, ns = wids[:i], bs[:i], offs[:i], ns[:i]

        order = np.argsort(wids, kind="stable")   # searchsorted needs sorted
        wids, bs, offs, ns = wids[order], bs[order], offs[order], ns[order]
        if not np.all(np.diff(wids) > 0):
            raise SystemExit("W-ids are not strictly increasing after sort — "
                             "duplicate ids would make the lookup ambiguous")
        for name, arr in (("wids", wids), ("b", bs), ("off", offs), ("n", ns)):
            if len(arr) != i:
                raise SystemExit(f"{name} is {len(arr)}, expected {i}")
            np.save(out / f"{name}.npy", arr)
    finally:
        db.close()
    total = sum((out / f"{k}.npy").stat().st_size
                for k in ("wids", "b", "off", "n"))
    return {"rows": int(i), "skipped_non_wid": len(skipped),
            "bytes": total, "bytes_per_doc": round(total / max(i, 1), 2),
            "dtypes": {"b": str(np.dtype(b_dt)), "off": str(np.dtype(off_dt)),
                       "n": str(np.dtype(n_dt))},
            "max": {"b": int(mx_b), "off": int(mx_off), "n": int(mx_n)}}


class OrdinalLocator:
    """`W-id -> (block, offset, length)` by binary search over int64."""

    def __init__(self, path: Path):
        self.wids = np.load(path / "wids.npy", mmap_mode="r")
        self.b = np.load(path / "b.npy", mmap_mode="r")
        self.off = np.load(path / "off.npy", mmap_mode="r")
        self.n = np.load(path / "n.npy", mmap_mode="r")
        self.rows = len(self.wids)
        for name in ("b", "off", "n"):
            if len(getattr(self, name)) != self.rows:
                raise SystemExit(f"{name}.npy length != wids length")

    def lookup(self, ids: list[str]):
        nums = np.empty(len(ids), dtype=np.int64)
        valid = np.zeros(len(ids), dtype=bool)
        for i, s in enumerate(ids):
            w = encode_wid(s)
            if w is not None:
                nums[i], valid[i] = w, True
        pos = np.clip(np.searchsorted(self.wids, nums), 0, self.rows - 1)
        found = valid & (self.wids[pos] == nums)   # verification read
        return pos, found


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path,
                    default=Path("/var/tmp/abs_stage/abstracts.sqlite"))
    ap.add_argument("--work", type=Path, default=Path("/var/tmp/c8_locator"))
    ap.add_argument("--trials", type=int, default=150)
    ap.add_argument("--hits", type=int, default=50, help="ids per fetch")
    ap.add_argument("--parity-sample", type=int, default=20_000)
    ap.add_argument("--skip-flat", action="store_true",
                    help="reuse an existing .flat sidecar")
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    rng = random.Random(args.seed)

    from lib.thinclient.abstracts import AbstractStore, build_flat_sidecar
    from lib.thinclient.retriever import _fstype_for_path

    src = args.src
    flat_dir = src.with_suffix(src.suffix + ".flat")

    rep = {
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "goal": ("CONSOLIDATION: delete abstracts.sqlite. N5 (doc 18 §9) moved "
                 "the payload out; this moves the LOCATOR out, which is what "
                 "actually removes the database."),
        "gate": "NO-REGRESSION vs mainline (operator constraint 2026-08-03)",
        "src": str(src), "src_bytes": src.stat().st_size,
        "src_fstype": _fstype_for_path(str(src)),
        "arms": {}, "parity": {}, "sizes": {},
    }

    # ── build the flat payload sidecar (N5, shipped code) ───────────────────
    if args.skip_flat and flat_dir.is_dir():
        log.info("reusing flat sidecar %s", flat_dir)
    else:
        log.info("building flat sidecar (N5) — 11.13 GB / ~1.06M blocks "
                 "measured 2026-08-02")
        t0 = time.perf_counter()
        info = build_flat_sidecar(src)
        log.info("  flat sidecar: %d blocks, %.2f GB in %.0f s",
                 info["blocks"], info["bytes"] / 1e9, time.perf_counter() - t0)
        rep["flat_build"] = info | {"seconds": round(time.perf_counter() - t0, 1)}

    # ── build the ordinal locator ───────────────────────────────────────────
    log.info("building ordinal locator")
    t0 = time.perf_counter()
    loc_info = build_ordinal_locator(src, args.work)
    loc_info["seconds"] = round(time.perf_counter() - t0, 1)
    rep["locator_build"] = loc_info
    log.info("  locator: %s rows, %.1f MB (%.2f B/doc), dtypes %s, %.0f s",
             f"{loc_info['rows']:,}", loc_info["bytes"] / 1e6,
             loc_info["bytes_per_doc"], loc_info["dtypes"], loc_info["seconds"])

    # ── the three arms ──────────────────────────────────────────────────────
    # `mainline` must NOT see the flat sidecar, or it stops being the baseline.
    # AbstractStore attaches it purely by directory existence, so the baseline
    # store is opened from a directory where that sidecar is not visible.
    plain_dir = args.work / "plain"
    plain_dir.mkdir(parents=True, exist_ok=True)
    plain_src = plain_dir / "abstracts.sqlite"
    if not plain_src.exists():
        os.symlink(src, plain_src)     # same bytes, no .flat/ beside it

    st_mainline = AbstractStore(plain_src)
    st_flat = AbstractStore(src)
    if st_flat._flat is None:
        raise SystemExit(f"{flat_dir} did not attach — flat arm is not flat")
    if st_mainline._flat is not None:
        raise SystemExit("baseline arm attached a flat sidecar; not a baseline")
    log.info("arms ready: mainline flat=%s | flat_only flat=%s",
             st_mainline._flat is not None, st_flat._flat is not None)

    loc = OrdinalLocator(args.work)

    def fetch_ordinal(ids: list[str]) -> dict[str, str]:
        """flat blocks + ordinal locator — the SQLite-free path."""
        pos, found = loc.lookup(ids)
        out: dict[str, str] = {}
        miss: list[str] = []
        for i, did in enumerate(ids):
            if not found[i]:
                miss.append(did)
                continue
            p = int(pos[i])
            blk = st_flat._block(int(loc.b[p]))
            o, ln = int(loc.off[p]), int(loc.n[p])
            out[did] = blk[o:o + ln].decode("utf-8")
        if miss:
            # Ids with no ordinal keep the old path rather than vanishing —
            # doc 18 §12 hazard 2. Must be empty here; recorded if not.
            out.update(st_flat.fetch(miss))
        return out

    arms = {"mainline": st_mainline.fetch, "flat_only": st_flat.fetch,
            "flat_ordinal": fetch_ordinal}

    # ── id pool ─────────────────────────────────────────────────────────────
    db = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    pool = [r[0] for r in db.execute(
        "SELECT id FROM docs ORDER BY random() LIMIT ?",
        (max(args.parity_sample, args.trials * args.hits),))]
    db.close()
    log.info("id pool: %s", f"{len(pool):,}")

    # ── byte-parity gate ────────────────────────────────────────────────────
    log.info("parity: %s ids", f"{args.parity_sample:,}")
    par = pool[:args.parity_sample]
    mism = {k: 0 for k in arms}
    for s in range(0, len(par), 500):
        chunk = par[s:s + 500]
        base = arms["mainline"](chunk)
        for name in arms:
            if name == "mainline":
                continue
            if arms[name](chunk) != base:
                mism[name] += 1
    for name in arms:
        rep["parity"][name] = {"ids": len(par), "mismatched_chunks": mism[name],
                               "pass": mism[name] == 0}
        log.info("  %-13s parity %s", name,
                 "PASS" if mism[name] == 0 else f"FAIL({mism[name]})")

    # ── latency: interleaved, order randomised per trial ────────────────────
    trials = [rng.sample(pool, args.hits) for _ in range(args.trials)]
    for name, fn in arms.items():
        for t in trials[:10]:
            fn(t)                                    # warm each arm
    samples: dict[str, list[float]] = {k: [] for k in arms}
    for t in trials:
        order = list(arms)
        rng.shuffle(order)
        for name in order:
            t0 = time.perf_counter()
            fn = arms[name]
            fn(t)
            samples[name].append((time.perf_counter() - t0) * 1000)

    base_p50 = statistics.median(samples["mainline"])
    for name in arms:
        st = _stat(samples[name])
        st["vs_mainline"] = round(base_p50 / st["p50_ms"], 3) if st["p50_ms"] else None
        # Compare UNROUNDED medians. `_stat` rounds to 4 dp, and comparing the
        # rounded value against the unrounded baseline made `mainline` flag
        # itself as a regression against itself (observed 2026-08-03).
        st["regression"] = bool(statistics.median(samples[name]) > base_p50)
        rep["arms"][name] = st
        log.info("%-13s p50 %8.3f ms | %.2fx mainline%s", name, st["p50_ms"],
                 st["vs_mainline"] or 0, "  <-- REGRESSION" if st["regression"] else "")

    # ── the consolidation arithmetic ────────────────────────────────────────
    flat_bytes = sum(p.stat().st_size for p in flat_dir.iterdir()) if flat_dir.is_dir() else 0
    rep["sizes"] = {
        "abstracts_sqlite_gb": round(rep["src_bytes"] / 1e9, 2),
        "flat_blocks_gb": round(flat_bytes / 1e9, 2),
        "ordinal_locator_gb": round(loc_info["bytes"] / 1e9, 3),
        "replacement_gb": round((flat_bytes + loc_info["bytes"]) / 1e9, 2),
        "saved_gb": round((rep["src_bytes"] - flat_bytes - loc_info["bytes"]) / 1e9, 2),
        "note": ("replacement = blocks.bin + locator arrays; the `meta` table "
                 "(zstd dictionaries, ~KB) still has to be carried somewhere, "
                 "and is NOT counted here — see the doc's not-settled list"),
    }
    rep["parity_overall_pass"] = all(v["pass"] for v in rep["parity"].values())

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"c8_abs_locator_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    log.info("abstracts.sqlite %.2f GB -> blocks %.2f GB + locator %.3f GB "
             "= %.2f GB (saves %.2f GB)", rep["sizes"]["abstracts_sqlite_gb"],
             rep["sizes"]["flat_blocks_gb"], rep["sizes"]["ordinal_locator_gb"],
             rep["sizes"]["replacement_gb"], rep["sizes"]["saved_gb"])
    log.info("results -> %s (parity %s)", out,
             "PASS" if rep["parity_overall_pass"] else "FAIL")


if __name__ == "__main__":
    main()
