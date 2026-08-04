#!/usr/bin/env python3
"""C10 — serve a section with `abstracts.sqlite` DELETED (doc 18 §18).

§17 shipped the ordinal locator so block lookups stop touching SQLite. Two
things still tied the store to `abstracts.sqlite`: the trained zstd dicts (read
from the `meta` table at open) and `AbstractStore.__init__` connecting to the
file at all. This spike proves both are gone: dicts are rehomed beside
`blocks.bin`, and `AbstractStore` opens a store whose `.sqlite` file does not
exist, holding no SQLite connection.

    mainline      sqlite blocks + sqlite `docs`          (abstracts.sqlite only)
    flat_ordinal  flat blocks + ordinal locator          (sqlite present)
    sqlite_free   flat blocks + ordinal locator + dicts  (NO abstracts.sqlite)
    mainline_ctrl second mainline — the noise floor (doc 18 §14)

Gate: byte-parity vs mainline on every trial AND no regression (operator
constraint 2026-08-03). `sqlite_free` must additionally hold `_db is None`.

    .venv/bin/python3 spike/meta_consolidation/16_c10_sqlite_free_serving.py \
        --src /var/tmp/abs_stage/abstracts.sqlite
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import shutil
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

log = logging.getLogger("c10")


def _stat(samples: list[float]) -> dict:
    s = sorted(samples)
    return {"n": len(s), "p50_ms": round(statistics.median(s), 4),
            "mean_ms": round(statistics.fmean(s), 4),
            "p90_ms": round(s[min(len(s) - 1, int(0.9 * len(s)))], 4)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path,
                    default=Path("/var/tmp/abs_stage/abstracts.sqlite"))
    ap.add_argument("--work", type=Path, default=Path("/var/tmp/c10_sqlite_free"))
    ap.add_argument("--trials", type=int, default=200)
    ap.add_argument("--hits", type=int, default=50)
    ap.add_argument("--parity-sample", type=int, default=20_000)
    ap.add_argument("--skip-flat", action="store_true")
    ap.add_argument("--seed", type=int, default=23)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    rng = random.Random(args.seed)

    from lib.thinclient.abstracts import (AbstractStore, build_flat_sidecar,
                                          build_ordinal_locator, dump_dict_sidecar)
    from lib.thinclient.retriever import _fstype_for_path

    src = args.src
    flat_dir = src.with_suffix(src.suffix + ".flat")
    rep = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "goal": "serve with abstracts.sqlite DELETED (doc 18 §18)",
           "gate": "byte-parity + no-regression vs mainline",
           "src": str(src), "src_fstype": _fstype_for_path(str(src)),
           "arms": {}, "parity": {}}

    # ── build the full flat store via shipped code (blocks + dicts + locator) ─
    if args.skip_flat and (flat_dir / "flat_store.json").exists():
        log.info("reusing flat sidecar; re-dumping dicts + locator for a "
                 "consistent identity")
        dump_dict_sidecar(src, flat_dir)
    else:
        log.info("build_flat_sidecar (now also rehomes dicts)")
        info = build_flat_sidecar(src)      # writes blocks.bin, flat_store.json, dicts
        log.info("  flat: %d blocks, %.2f GB, id=%s", info["blocks"],
                 info["bytes"] / 1e9, info["flat_store_id"])
    loc = build_ordinal_locator(src, flat_dir)
    log.info("  locator: %s rows, skipped_non_wid=%d", f"{loc['rows']:,}",
             loc["skipped_non_wid"])
    dmeta = json.loads((flat_dir / "dicts.json").read_text())
    log.info("  dicts rehomed: %d files (%s)", len(dmeta["files"]), dmeta["format"])

    # ── arm directories (symlinks; no big-file copies) ───────────────────────
    if args.work.exists():
        shutil.rmtree(args.work)

    def link_plain(name: str) -> Path:
        d = args.work / name
        d.mkdir(parents=True)
        os.symlink(src, d / "abstracts.sqlite")        # no .flat -> sqlite path
        return d / "abstracts.sqlite"

    # sqlite_free: the flat sidecar with NO abstracts.sqlite beside it.
    free_dir = args.work / "sqlite_free"
    free_flat = free_dir / "abstracts.sqlite.flat"
    free_flat.mkdir(parents=True)
    for p in flat_dir.iterdir():
        os.symlink(p, free_flat / p.name)
    free_path = free_dir / "abstracts.sqlite"          # deliberately absent

    st_mainline = AbstractStore(link_plain("mainline"))
    st_ctrl = AbstractStore(link_plain("mainline_ctrl"))
    st_flatord = AbstractStore(src)                    # sqlite present + flat + locator
    st_free = AbstractStore(free_path)                 # abstracts.sqlite absent

    assert st_mainline._db is not None and st_mainline._flat is None, "mainline not plain"
    assert st_flatord._locator is not None, "flat_ordinal has no locator"
    assert st_free._sqlite_free and st_free._db is None, "sqlite_free still holds a db"
    assert st_free._locator is not None and st_free._flat is not None, "free arm not fully flat"
    log.info("arms wired; sqlite_free: _db=%s _flat=%s _locator=%d rows",
             st_free._db, st_free._flat is not None, st_free._locator.rows)

    arms = {"mainline": st_mainline.fetch, "flat_ordinal": st_flatord.fetch,
            "sqlite_free": st_free.fetch, "mainline_ctrl": st_ctrl.fetch}

    # ── id pool: only W-number ids, since a deleted sqlite has no docs_other
    # fallback — this is exactly the skipped_non_wid==0 precondition in action.
    db = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    pool = [r[0] for r in db.execute(
        "SELECT id FROM docs ORDER BY random() LIMIT ?",
        (max(args.parity_sample, args.trials * args.hits),))]
    db.close()
    log.info("id pool: %s", f"{len(pool):,}")

    # ── byte-parity gate ─────────────────────────────────────────────────────
    par = pool[:args.parity_sample]
    mism = {k: 0 for k in arms}
    for s in range(0, len(par), 500):
        chunk = par[s:s + 500]
        base = arms["mainline"](chunk)
        for name in arms:
            if name != "mainline" and arms[name](chunk) != base:
                mism[name] += 1
    for name in arms:
        rep["parity"][name] = {"ids": len(par), "mismatched_chunks": mism[name],
                               "pass": mism[name] == 0}
        log.info("  %-14s parity %s", name,
                 "PASS" if mism[name] == 0 else f"FAIL({mism[name]})")

    # ── latency: interleaved, order randomised, every arm warmed ─────────────
    trials = [rng.sample(pool, args.hits) for _ in range(args.trials)]
    for fn in arms.values():
        for t in trials[:10]:
            fn(t)
    samples: dict[str, list[float]] = {k: [] for k in arms}
    for t in trials:
        order = list(arms)
        rng.shuffle(order)
        for name in order:
            fn = arms[name]
            t0 = time.perf_counter()
            fn(t)
            samples[name].append((time.perf_counter() - t0) * 1000)

    base_p50 = statistics.median(samples["mainline"])
    for name in arms:
        st = _stat(samples[name])
        st["vs_mainline"] = round(base_p50 / st["p50_ms"], 3) if st["p50_ms"] else None
        st["regression"] = bool(statistics.median(samples[name]) > base_p50)
        rep["arms"][name] = st
        log.info("%-14s p50 %8.4f  mean %8.4f  p90 %8.4f | %.2fx%s", name,
                 st["p50_ms"], st["mean_ms"], st["p90_ms"], st["vs_mainline"] or 0,
                 "  <-- REGRESSION" if st["regression"] else "")

    ctrl = rep["arms"]["mainline_ctrl"]
    rep["noise_floor_pct"] = round(abs(ctrl["p50_ms"] - base_p50) / base_p50 * 100, 2)
    rep["parity_overall_pass"] = all(v["pass"] for v in rep["parity"].values())
    rep["locator_build"], rep["dicts"] = loc, dmeta
    rep["sizes"] = {
        "abstracts_sqlite_gb": round(src.stat().st_size / 1e9, 2),
        "flat_blocks_gb": round((flat_dir / "blocks.bin").stat().st_size / 1e9, 2),
        "ordinal_locator_gb": round(loc["bytes"] / 1e9, 3),
        "dicts_mb": round(sum((flat_dir / f).stat().st_size
                              for f in dmeta["files"]) / 1e6, 2) if dmeta["files"] else 0.0,
    }

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"c10_sqlite_free_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    fr = rep["arms"]["sqlite_free"]
    log.info("SQLite-FREE serving: parity %s, p50 %.3fx mainline, noise %.2f%%, "
             "_db=None confirmed", "PASS" if rep["parity_overall_pass"] else "FAIL",
             fr["vs_mainline"], rep["noise_floor_pct"])
    log.info("results -> %s", out)


if __name__ == "__main__":
    main()
