#!/usr/bin/env python3
"""C9 — prove the SHIPPED abstract locator reader, not a harness reimplementation.

C8 (doc 18 §16) measured a *harness* `fetch_ordinal` + `OrdinalLocator` at
5.53x p50 with byte-parity. This turns that into a shipped-code result:
`abstracts.py` now has `build_ordinal_locator` + `AbstractLocator` + the
fail-closed identity gate, and `AbstractStore.fetch()` routes through the
locator automatically when it is present and its identity is proven. Every arm
below calls the SHIPPED `AbstractStore.fetch` — the thing that will actually
serve — so no reimplementation can flatter the result.

    mainline      sqlite blocks + sqlite `docs` locator   (no .flat beside it)
    flat_only     flat blocks.bin + sqlite `docs` locator (N5 as shipped)
    flat_ordinal  flat blocks.bin + ordinal locator       (SQLite-free lookup)
    mainline_ctrl a second mainline store — the per-run noise floor (doc 18 §14)

**Goal is CONSOLIDATION** gated on the operator constraint (2026-08-03):
serving performance must be IDENTICAL to mainline — faster is a bonus, slower
is a failure. Byte-parity against `mainline` on every trial is the hard gate.

§14 discipline: all stores on LOCAL DISK (stage the source first), arms
interleaved with order randomised per trial, every arm warmed, p50 AND mean AND
p90 reported (the locator win is a near-constant few ms, so a single multiple
overstates it).

    .venv/bin/python3 spike/meta_consolidation/15_c9_shipped_locator_reader.py \
        --src /var/tmp/abs_stage/abstracts.sqlite [--skip-flat]
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
sys.path.insert(0, str(ROOT / "source"))

log = logging.getLogger("c9")

# The flat sidecar files that make up the payload store, minus the locator —
# `flat_only` mirrors these so it attaches the flat blocks but keeps SQLite for
# the block index.
_FLAT_PAYLOAD_FILES = ("blocks.bin", "block_offsets.npy", "block_lengths.npy",
                       "block_dictids.npy", "flat_store.json")


def _stat(samples: list[float]) -> dict:
    s = sorted(samples)
    return {"n": len(s), "p50_ms": round(statistics.median(s), 4),
            "mean_ms": round(statistics.fmean(s), 4),
            "p90_ms": round(s[min(len(s) - 1, int(0.9 * len(s)))], 4)}


def _link_dir(link_dir: Path, src: Path, flat_files: tuple | None) -> Path:
    """A directory holding a symlink to `src` (so AbstractStore opens the same
    bytes) and, if `flat_files` is given, a `.flat/` with symlinks to just those
    files — letting one 11 GB blocks.bin back several arms without copies."""
    link_dir.mkdir(parents=True, exist_ok=True)
    sqlite_link = link_dir / "abstracts.sqlite"
    if not sqlite_link.exists():
        os.symlink(src, sqlite_link)
    if flat_files is not None:
        flat_src = src.with_suffix(src.suffix + ".flat")
        flat_link = link_dir / "abstracts.sqlite.flat"
        flat_link.mkdir(exist_ok=True)
        for name in flat_files:
            dst = flat_link / name
            if not dst.exists():
                os.symlink(flat_src / name, dst)
    return sqlite_link


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path,
                    default=Path("/var/tmp/abs_stage/abstracts.sqlite"))
    ap.add_argument("--work", type=Path, default=Path("/var/tmp/c9_locator"))
    ap.add_argument("--trials", type=int, default=200)
    ap.add_argument("--hits", type=int, default=50, help="ids per fetch (top_k)")
    ap.add_argument("--parity-sample", type=int, default=20_000)
    ap.add_argument("--skip-flat", action="store_true",
                    help="reuse an existing .flat sidecar (must carry flat_store.json)")
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    rng = random.Random(args.seed)

    from lib.thinclient.abstracts import (AbstractStore, build_flat_sidecar,
                                          build_ordinal_locator)
    from lib.thinclient.retriever import _fstype_for_path

    src = args.src
    flat_dir = src.with_suffix(src.suffix + ".flat")
    fstype = _fstype_for_path(str(src))
    if fstype not in ("overlay", "ext4", "xfs", "btrfs", "tmpfs"):
        log.warning("src is on %s — doc 18 §14: a 9p baseline flatters every "
                    "arm ~50x. Stage to local disk first.", fstype)

    rep = {
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "goal": ("CONSOLIDATION: the SHIPPED AbstractStore ordinal-locator "
                 "reader (abstracts.py), measured through fetch()."),
        "gate": "NO-REGRESSION vs mainline (operator constraint 2026-08-03)",
        "src": str(src), "src_bytes": src.stat().st_size, "src_fstype": fstype,
        "arms": {}, "parity": {}, "sizes": {},
    }

    # ── flat sidecar (N5) + ordinal locator, both via SHIPPED build code ─────
    if args.skip_flat and (flat_dir / "flat_store.json").exists():
        log.info("reusing flat sidecar %s (carries flat_store.json)", flat_dir)
        rep["flat_build"] = "reused"
    else:
        log.info("building flat sidecar via shipped build_flat_sidecar()")
        t0 = time.perf_counter()
        info = build_flat_sidecar(src)
        info["seconds"] = round(time.perf_counter() - t0, 1)
        rep["flat_build"] = info
        log.info("  flat sidecar: %d blocks, %.2f GB, id=%s, %.0f s",
                 info["blocks"], info["bytes"] / 1e9, info["flat_store_id"],
                 info["seconds"])

    log.info("building ordinal locator via shipped build_ordinal_locator()")
    t0 = time.perf_counter()
    loc_info = build_ordinal_locator(src, flat_dir)
    loc_info["seconds"] = round(time.perf_counter() - t0, 1)
    rep["locator_build"] = loc_info
    log.info("  locator: %s rows, %.1f MB (%.2f B/doc), skipped_non_wid=%d, "
             "dtypes %s, %.0f s", f"{loc_info['rows']:,}",
             loc_info["bytes"] / 1e6, loc_info["bytes_per_doc"],
             loc_info["skipped_non_wid"], loc_info["dtypes"], loc_info["seconds"])

    # ── the four arms, each a real AbstractStore on a real directory ─────────
    if args.work.exists():
        shutil.rmtree(args.work)
    mainline_src = _link_dir(args.work / "mainline", src, None)
    ctrl_src = _link_dir(args.work / "mainline_ctrl", src, None)
    flatonly_src = _link_dir(args.work / "flatonly", src, _FLAT_PAYLOAD_FILES)

    st_mainline = AbstractStore(mainline_src)
    st_ctrl = AbstractStore(ctrl_src)
    st_flatonly = AbstractStore(flatonly_src)
    st_flatord = AbstractStore(src)            # real .flat has the locator

    # Assert each arm is actually in the state its name claims — a silent
    # mis-wiring here would void the whole comparison.
    assert st_mainline._flat is None and st_mainline._locator is None, "mainline not plain"
    assert st_flatonly._flat is not None and st_flatonly._locator is None, "flat_only wrong"
    assert st_flatord._flat is not None and st_flatord._locator is not None, "flat_ordinal has no locator"
    log.info("arms: mainline(sqlite) flat_only(flat+sqlite-loc) "
             "flat_ordinal(flat+ordinal) ctrl(sqlite#2) — all wired")

    arms = {"mainline": st_mainline.fetch, "flat_only": st_flatonly.fetch,
            "flat_ordinal": st_flatord.fetch, "mainline_ctrl": st_ctrl.fetch}

    # ── id pool across the whole store ───────────────────────────────────────
    db = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    pool = [r[0] for r in db.execute(
        "SELECT id FROM docs ORDER BY random() LIMIT ?",
        (max(args.parity_sample, args.trials * args.hits),))]
    db.close()
    log.info("id pool: %s", f"{len(pool):,}")

    # ── byte-parity gate: every arm must equal mainline, per chunk ───────────
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
        log.info("  %-14s parity %s", name,
                 "PASS" if mism[name] == 0 else f"FAIL({mism[name]})")

    # ── latency: interleaved, order randomised per trial, every arm warmed ───
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
        # Compare UNROUNDED medians (doc 18 §16: rounding once made mainline
        # flag itself as a regression against itself).
        st["regression"] = bool(statistics.median(samples[name]) > base_p50)
        rep["arms"][name] = st
        log.info("%-14s p50 %8.4f ms  mean %8.4f  p90 %8.4f | %.2fx mainline%s",
                 name, st["p50_ms"], st["mean_ms"], st["p90_ms"],
                 st["vs_mainline"] or 0,
                 "  <-- REGRESSION" if st["regression"] else "")

    ctrl = rep["arms"]["mainline_ctrl"]
    noise = abs(ctrl["p50_ms"] - base_p50) / base_p50 * 100
    rep["noise_floor_pct"] = round(noise, 2)
    log.info("noise floor (mainline vs mainline_ctrl): %.2f%% of p50", noise)

    # ── consolidation arithmetic ─────────────────────────────────────────────
    flat_bytes = sum(p.stat().st_size for p in flat_dir.iterdir()
                     if p.name in _FLAT_PAYLOAD_FILES[:4])
    loc_bytes = loc_info["bytes"]
    rep["sizes"] = {
        "abstracts_sqlite_gb": round(rep["src_bytes"] / 1e9, 2),
        "flat_blocks_gb": round(flat_bytes / 1e9, 2),
        "ordinal_locator_gb": round(loc_bytes / 1e9, 3),
        "replacement_gb": round((flat_bytes + loc_bytes) / 1e9, 2),
        "saved_gb": round((rep["src_bytes"] - flat_bytes - loc_bytes) / 1e9, 2),
        "note": ("replacement = blocks.bin + loc_*.npy; the `meta` table (zstd "
                 "dicts) is NOT yet rehomed, so abstracts.sqlite is still "
                 "load-bearing — this measures the READER, not deletion."),
    }
    rep["parity_overall_pass"] = all(v["pass"] for v in rep["parity"].values())

    out = args.out or (ROOT / "data" / "eval_results" /
                       f"c9_locator_reader_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    fo, ml = rep["arms"]["flat_ordinal"], rep["arms"]["mainline"]
    p50x = fo["vs_mainline"]
    meanx = round(ml["mean_ms"] / fo["mean_ms"], 3) if fo["mean_ms"] else 0
    p90x = round(ml["p90_ms"] / fo["p90_ms"], 3) if fo["p90_ms"] else 0
    rep["arms"]["flat_ordinal"]["vs_mainline_mean"] = meanx
    rep["arms"]["flat_ordinal"]["vs_mainline_p90"] = p90x
    out.write_text(json.dumps(rep, indent=2))
    log.info("SHIPPED flat_ordinal vs mainline: p50 %.3fx / mean %.3fx / p90 "
             "%.3fx; parity %s; noise %.2f%%", p50x, meanx, p90x,
             "PASS" if rep["parity_overall_pass"] else "FAIL", noise)
    log.info("results -> %s", out)


if __name__ == "__main__":
    main()
