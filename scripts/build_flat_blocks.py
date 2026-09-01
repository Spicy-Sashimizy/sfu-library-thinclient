#!/usr/bin/env python3
"""Production build path for the N5 flat abstract block store (doc 18 §9, §16-§18).

`lib/thinclient/abstracts.py` has shipped every *piece* since 2026-08-03 —
`build_flat_sidecar` (payloads -> `blocks.bin`), `build_ordinal_locator`
(the `docs` B-tree -> sorted `loc_*.npy`), `dump_dict_sidecar` (the trained
zstd dicts out of the `meta` table) and the reader that serves all three —
but nothing in the repo CALLED them for a served section. Doc 18 §17 lists
that gap as the sole remaining blocker ("No build-time path"). This script is
that path: it drives the three shipped builders for one section, proves the
result byte-identical to the v3 SQLite store it was derived from, and only
then publishes it under the name the reader looks for.

Safety contract (why this is not just three function calls in a row):

  * **Additive only.** The source `abstracts.sqlite` is opened READ-ONLY by
    every builder; nothing under `data/thinclient_index/` is modified or
    deleted. Reverting a section is `rm -rf <section>/abstracts.sqlite.flat`.
  * **Staged publish.** The sidecar is built in `abstracts.sqlite.flat.building/`
    and `os.rename`d to `abstracts.sqlite.flat/` only after verification passes.
    The reader attaches a sidecar on directory *existence*, so a crashed build
    must never leave that name half-populated: `AbstractStore._open_flat` only
    falls back to the v3 blocks table on `OSError` (a *missing* file), and a
    TRUNCATED `block_*.npy` raises `ValueError` out of `np.load`, which nothing
    catches. Staging removes that window entirely.
  * **Never overwrites.** If the published sidecar already exists the build
    refuses and points at `verify`; removing it is an explicit operator step.
  * **Resumable at stage granularity.** Each stage (flat / dicts / locator) is
    a single sequential pass whose completion is provable from the stamp it
    writes last, so a rerun re-validates and skips what is already good. That
    is the right granularity: measured, the whole build is ~2-15 min per
    section (see `plan`), so sub-stage checkpointing would buy minutes and cost
    a correctness surface.

Verification (`--verify-ids`, default 20,000 — the gate doc 18 §9/§16/§17 used):
four readers over the SAME sampled ids, all constructed from the SHIPPED
`AbstractStore` through symlink views, so no read path is re-implemented here:

  | arm           | what it exercises                                   |
  |---------------|-----------------------------------------------------|
  | `v3`          | the oracle: SQLite blocks + SQLite `docs`           |
  | `flat_docs`   | `blocks.bin` + SQLite `docs` (sidecar minus locator)|
  | `flat_ordinal`| `blocks.bin` + `loc_*.npy` (what will be served)    |
  | `sqlite_free` | as above with NO `abstracts.sqlite` at all (§18)    |

Every arm must be byte-identical to `v3` (the `sqlite_free` arm is compared on
the ids the ordinal locator can address — non-W-number ids have no fallback
there by design, hazard 2). `--verify-blocks` adds a container-level check:
random blocks `pread` out of `blocks.bin` must equal the `z` BLOB in the source
table byte for byte, with the same dict id.

Ids are sampled as contiguous windows spread across the whole rowid range, not
a head slice: doc 18 §16 records a head-sampled measurement that was 23% wrong
and inverted a verdict, because `id` is the numeric W-id and its head is the
oldest works.

    .venv/bin/python3 scripts/build_flat_blocks.py plan
    .venv/bin/python3 scripts/build_flat_blocks.py build --section social_sciences__recent
    .venv/bin/python3 scripts/build_flat_blocks.py verify --section social_sciences__recent

After a PASS the section serves flat automatically (no env gate — the sidecar's
existence is the switch). Deleting `abstracts.sqlite` is a SEPARATE, operator-only
step and is legal only when the report says `sqlite_deletable: true`.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import shutil
import sqlite3
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lib.thinclient.abstracts import (  # noqa: E402
    DICTS_STAMP, FLAT_ID_KEY, FLAT_STAMP, LOCATOR_STAMP, AbstractStore,
    _encode_wid, build_flat_sidecar, build_ordinal_locator, dump_dict_sidecar)

log = logging.getLogger("flatbuild")

DEFAULT_INDEX_ROOT = REPO / "data" / "thinclient_index"
ABSTRACTS = "abstracts.sqlite"
FLAT_SUFFIX = ".flat"
STAGING_SUFFIX = ".flat.building"

KNOWN_ARTIFACTS = {
    "blocks.bin", "blocks.bin.partial", "block_offsets.npy",
    "block_lengths.npy", "block_dictids.npy", FLAT_STAMP, LOCATOR_STAMP,
    DICTS_STAMP, "loc_wids.npy", "loc_b.npy", "loc_off.npy", "loc_n.npy",
}
KNOWN_PREFIXES = ("zdict_",)

RATE_LOCAL_MB_S = 13470433280 / 114.9 / 1e6
RATE_9P_MB_S = 13470433280 / 878.0 / 1e6
SIDECAR_SIZE_RATIO = 0.90


def section_dirs(index_root: Path) -> list[Path]:
    root = Path(index_root) / "sections"
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


def survey(index_root: Path) -> list[dict]:
    """Every section that has (or could have) a flat sidecar, smallest first.

    stat() only — safe to run while another job owns the machine's I/O."""
    rows = []
    for sdir in section_dirs(index_root):
        src = sdir / ABSTRACTS
        flat = sdir / (ABSTRACTS + FLAT_SUFFIX)
        stage = sdir / (ABSTRACTS + STAGING_SUFFIX)
        if not src.exists() and not flat.is_dir():
            continue
        size = src.stat().st_size if src.exists() else 0
        rows.append({
            "section": sdir.name,
            "dir": str(sdir),
            "src": str(src) if src.exists() else None,
            "src_bytes": size,
            "published": flat.is_dir(),
            "staging": stage.is_dir(),
            "est_sidecar_bytes": int(size * SIDECAR_SIZE_RATIO),
            "est_flat_s_9p": round(size / 1e6 / RATE_9P_MB_S, 1) if size else None,
            "est_flat_s_local": round(size / 1e6 / RATE_LOCAL_MB_S, 1) if size else None,
        })
    return sorted(rows, key=lambda r: r["src_bytes"])


def cmd_plan(args) -> int:
    rows = survey(args.index_root)
    if not rows:
        print(f"no sections with {ABSTRACTS} under {args.index_root}")
        return 0
    free = shutil.disk_usage(args.index_root).free
    print(f"index root : {args.index_root}")
    print(f"free space : {free / 1e9:.1f} GB\n")
    print(f"{'section':32} {'sqlite':>10} {'sidecar est':>12} "
          f"{'flat est (9p)':>14}  state")
    total = 0
    for r in rows:
        state = ("PUBLISHED" if r["published"]
                 else "staging present" if r["staging"] else "not built")
        if not r["published"]:
            total += r["est_sidecar_bytes"]
        print(f"{r['section']:32} {r['src_bytes'] / 1e9:9.2f}G "
              f"{r['est_sidecar_bytes'] / 1e9:11.2f}G "
              f"{(r['est_flat_s_9p'] or 0) / 60:12.1f}m  {state}")
    print(f"\nadditional disk needed for the unbuilt sections: {total / 1e9:.2f} GB "
          f"(free: {free / 1e9:.1f} GB)")
    print("\nbuild smallest-first:")
    for r in rows:
        if not r["published"] and r["src"]:
            print(f"  .venv/bin/python3 scripts/build_flat_blocks.py build "
                  f"--section {r['section']}")
    print("\nNOTE: the sidecar is ADDITIVE — the section holds both the sqlite "
          "store and the sidecar until an operator deletes abstracts.sqlite "
          "(legal only when the build report says sqlite_deletable: true).")
    return 0


def _load_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def flat_stage_state(stage: Path, src: Path) -> tuple[bool, str]:
    import numpy as np

    stamp = _load_json(stage / FLAT_STAMP)
    if stamp is None:
        return False, "no flat_store.json"
    blocks = stage / "blocks.bin"
    if not blocks.exists():
        return False, "blocks.bin missing"
    if blocks.stat().st_size != stamp.get("bytes"):
        return False, (f"blocks.bin is {blocks.stat().st_size} B but the stamp "
                       f"declares {stamp.get('bytes')}")
    st = src.stat()
    rec = stamp.get("source", {})
    if rec.get("bytes") != st.st_size or rec.get("mtime_ns") != st.st_mtime_ns:
        return False, ("built from a different source (size/mtime differ) — "
                       "the locator would certify a false pairing")
    slots = stamp.get("slots")
    for name in ("block_offsets", "block_lengths", "block_dictids"):
        try:
            arr = np.load(stage / f"{name}.npy", mmap_mode="r")
        except (OSError, ValueError) as exc:
            return False, f"{name}.npy unreadable ({exc})"
        if len(arr) != slots:
            return False, f"{name}.npy holds {len(arr)}, stamp declares {slots}"
    return True, "ok"


def dicts_stage_state(stage: Path, flat_id: str | None) -> tuple[bool, str]:
    meta = _load_json(stage / DICTS_STAMP)
    if meta is None:
        return False, "no dicts.json"
    if meta.get(FLAT_ID_KEY) != flat_id:
        return False, "dicts.json identity != blocks identity"
    for f in meta.get("files", []):
        p = stage / f
        if not p.exists() or p.stat().st_size == 0:
            return False, f"dict {f} missing or empty"
    return True, "ok"


def locator_stage_state(stage: Path, flat_id: str | None) -> tuple[bool, str]:
    import numpy as np

    stamp = _load_json(stage / LOCATOR_STAMP)
    if stamp is None:
        return False, "no locator.json"
    if stamp.get(FLAT_ID_KEY) != flat_id:
        return False, "locator.json identity != blocks identity"
    rows = stamp.get("rows")
    for name in ("wids", "b", "off", "n"):
        try:
            arr = np.load(stage / f"loc_{name}.npy", mmap_mode="r")
        except (OSError, ValueError) as exc:
            return False, f"loc_{name}.npy unreadable ({exc})"
        if len(arr) != rows:
            return False, f"loc_{name}.npy holds {len(arr)}, stamp declares {rows}"
    return True, "ok"


def _guard_staging(stage: Path) -> None:
    """Refuse to reuse a directory that holds anything this script didn't write."""
    if not stage.exists():
        return
    if not stage.is_dir():
        raise SystemExit(f"{stage} exists and is not a directory")
    strays = [p.name for p in stage.iterdir()
              if p.name not in KNOWN_ARTIFACTS
              and not p.name.startswith(KNOWN_PREFIXES)]
    if strays:
        raise SystemExit(
            f"{stage} holds files this script did not write ({strays[:5]}); "
            f"refusing to touch it. Move it aside and rerun.")


def sample_ids(src: Path, n: int, windows: int = 20, seed: int = 17) -> list[str]:
    """`n` ids drawn as `windows` contiguous rowid runs spread across the table.

    Doc 18 §16: sampling the head of `id` (= the numeric W-id, so the OLDEST
    works) measured 115.1 B/doc against a true 142.1 — 23% off, and it inverted
    a verdict. Contiguous windows across the whole range, never a head slice.
    """
    db = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        mx = db.execute("SELECT max(rowid) FROM docs").fetchone()[0] or 0
        if mx == 0:
            return []
        per = max(1, n // max(1, windows))
        rng = random.Random(seed)
        out: dict[str, None] = {}
        for _ in range(windows):
            start = rng.randint(1, max(1, mx - per))
            rows = db.execute(
                "SELECT id FROM docs WHERE rowid >= ? ORDER BY rowid LIMIT ?",
                (start, per)).fetchall()
            for (doc_id,) in rows:
                out[doc_id] = None
            if len(out) >= n:
                break
        return list(out)[:n]
    finally:
        db.close()


def sample_block_ids(src: Path, n: int, seed: int = 23) -> list[int]:
    db = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        mx = db.execute("SELECT max(b) FROM blocks").fetchone()[0]
        cnt = db.execute("SELECT count(*) FROM blocks").fetchone()[0]
        if not cnt:
            return []
        rng = random.Random(seed)
        if cnt <= n:
            return [r[0] for r in db.execute("SELECT b FROM blocks")]
        picks: set[int] = set()
        guard = 0
        while len(picks) < n and guard < n * 20:
            guard += 1
            cand = rng.randint(0, mx)
            row = db.execute(
                "SELECT b FROM blocks WHERE b >= ? ORDER BY b LIMIT 1",
                (cand,)).fetchone()
            if row:
                picks.add(row[0])
        return sorted(picks)
    finally:
        db.close()


@contextmanager
def reader_views(src: Path, flat_dir: Path, tmp_root: Path):
    """Four `AbstractStore`s over the same bytes, built from symlink views.

    The reader discovers a sidecar by NAME (`<store>.flat` beside the store),
    so arms are made by arranging symlinks, never by patching the reader. The
    v3 arm gets a directory with no `.flat` sibling and is therefore the exact
    shipped SQLite path — the oracle every other arm is compared against.
    """
    tmp_root.mkdir(parents=True, exist_ok=True)
    views: dict[str, AbstractStore] = {}

    v3 = tmp_root / "v3"
    v3.mkdir()
    os.symlink(src, v3 / ABSTRACTS)
    views["v3"] = AbstractStore(v3 / ABSTRACTS)

    fd_dir = tmp_root / "flat_docs"
    (fd_dir / (ABSTRACTS + FLAT_SUFFIX)).mkdir(parents=True)
    os.symlink(src, fd_dir / ABSTRACTS)
    for p in flat_dir.iterdir():
        if p.name == LOCATOR_STAMP or p.name.startswith("loc_"):
            continue
        os.symlink(p, fd_dir / (ABSTRACTS + FLAT_SUFFIX) / p.name)
    views["flat_docs"] = AbstractStore(fd_dir / ABSTRACTS)

    fo_dir = tmp_root / "flat_ordinal"
    fo_dir.mkdir()
    os.symlink(src, fo_dir / ABSTRACTS)
    os.symlink(flat_dir, fo_dir / (ABSTRACTS + FLAT_SUFFIX))
    views["flat_ordinal"] = AbstractStore(fo_dir / ABSTRACTS)

    free = tmp_root / "sqlite_free"
    free.mkdir()
    os.symlink(flat_dir, free / (ABSTRACTS + FLAT_SUFFIX))
    views["sqlite_free"] = AbstractStore(free / ABSTRACTS)

    try:
        yield views
    finally:
        for s in views.values():
            db = getattr(s, "_db", None)
            if db is not None:
                db.close()
            f = getattr(s, "_flat", None)
            if f:
                try:
                    os.close(f["fd"])
                except OSError:
                    pass


def verify_reads(src: Path, flat_dir: Path, tmp_root: Path, n_ids: int,
                 chunk: int = 2000, seed: int = 17) -> dict:
    """Byte-parity of every serving arm against the v3 SQLite oracle."""
    if n_ids <= 0:
        return {"skipped": True, "pass": True, "ids_checked": 0}
    ids = sample_ids(src, n_ids, seed=seed)
    rep: dict = {"ids_checked": len(ids), "arms": {}, "pass": True}
    if not ids:
        rep["pass"] = False
        rep["error"] = "docs table is empty — nothing to verify"
        return rep

    addressable = [i for i in ids if _encode_wid(i) is not None]
    rep["addressable_ids"] = len(addressable)
    with reader_views(src, flat_dir, tmp_root) as views:
        stats = {k: {"returned": 0, "mismatched": 0, "missing": 0,
                     "examples": []} for k in views if k != "v3"}
        v3_returned = 0
        for s in range(0, len(ids), chunk):
            part = ids[s:s + chunk]
            truth = views["v3"].fetch(part)
            v3_returned += len(truth)
            part_addr = [i for i in part if _encode_wid(i) is not None]
            for name, store in views.items():
                if name == "v3":
                    continue
                want_ids = part_addr if name == "sqlite_free" else part
                want = {i: truth[i] for i in want_ids if i in truth}
                st = stats[name]
                try:
                    got = store.fetch(want_ids)
                except Exception as exc:       # noqa: BLE001 — any raise is a FAIL
                    st["errors"] = st.get("errors", 0) + len(want_ids)
                    if len(st["examples"]) < 3:
                        st["examples"].append({"id": want_ids[0] if want_ids else None,
                                               "why": f"{type(exc).__name__}: {exc}"})
                    continue
                st["returned"] += len(got)
                for i, text in want.items():
                    if i not in got:
                        st["missing"] += 1
                        if len(st["examples"]) < 3:
                            st["examples"].append({"id": i, "why": "absent"})
                    elif got[i] != text:
                        st["mismatched"] += 1
                        if len(st["examples"]) < 3:
                            st["examples"].append({"id": i, "why": "bytes differ"})
        rep["v3_returned"] = v3_returned
        for name, st in stats.items():
            st["pass"] = (st["mismatched"] == 0 and st["missing"] == 0
                          and not st.get("errors"))
            rep["pass"] &= st["pass"]
            rep["arms"][name] = st
        rep["locator_attached"] = views["flat_ordinal"]._locator is not None
        rep["sqlite_free_has_no_db"] = views["sqlite_free"]._db is None
        rep["pass"] &= bool(rep["locator_attached"]) and rep["sqlite_free_has_no_db"]
    return rep


def verify_blocks(src: Path, flat_dir: Path, n: int, seed: int = 23) -> dict:
    """Container-level check: `pread(blocks.bin)` == the source `z` BLOB.

    Independent of the codec and of every reader — if this passes, the payload
    move is a faithful copy whatever the dictionaries do.
    """
    import numpy as np

    bs = sample_block_ids(src, n, seed=seed)
    rep = {"blocks_checked": len(bs), "mismatched": 0, "examples": [],
           "pass": True}
    if not bs:
        return rep
    off = np.load(flat_dir / "block_offsets.npy", mmap_mode="r")
    ln = np.load(flat_dir / "block_lengths.npy", mmap_mode="r")
    did = np.load(flat_dir / "block_dictids.npy", mmap_mode="r")
    fd = os.open(str(flat_dir / "blocks.bin"), os.O_RDONLY)
    db = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        for s in range(0, len(bs), 500):
            part = bs[s:s + 500]
            marks = ",".join("?" * len(part))
            for b, d, z in db.execute(
                    f"SELECT b, d, z FROM blocks WHERE b IN ({marks})", part):
                o = int(off[b])
                bad = None
                if o < 0:
                    bad = "hole in block_offsets (block never written)"
                elif int(ln[b]) != len(z):
                    bad = f"length {int(ln[b])} != {len(z)}"
                elif int(did[b]) != d:
                    bad = f"dict id {int(did[b])} != {d}"
                elif os.pread(fd, len(z), o) != z:
                    bad = "payload bytes differ"
                if bad:
                    rep["mismatched"] += 1
                    if len(rep["examples"]) < 3:
                        rep["examples"].append({"b": b, "why": bad})
    finally:
        db.close()
        os.close(fd)
    rep["pass"] = rep["mismatched"] == 0
    return rep


def resolve_src(args) -> tuple[str, Path]:
    if args.src:
        src = Path(args.src)
        return src.parent.name, src
    if not args.section:
        raise SystemExit("--section or --src is required")
    src = Path(args.index_root) / "sections" / args.section / ABSTRACTS
    return args.section, src


def preflight(src: Path, stage: Path) -> dict:
    if not src.exists():
        raise SystemExit(f"{src} does not exist")
    db = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "blocks" not in tables or "docs" not in tables:
            raise SystemExit(
                f"{src} is not a v3 store (tables={sorted(tables)}); the flat "
                f"sidecar is derived from `blocks` + `docs`.")
        fmt = db.execute("SELECT v FROM meta WHERE k='format'").fetchone()
    finally:
        db.close()
    size = src.stat().st_size
    need = int(size * SIDECAR_SIZE_RATIO * 1.10)
    free = shutil.disk_usage(stage.parent).free
    if free < need:
        raise SystemExit(
            f"insufficient disk: the sidecar needs ~{need / 1e9:.1f} GB "
            f"(source {size / 1e9:.1f} GB x {SIDECAR_SIZE_RATIO} + 10% headroom) "
            f"but only {free / 1e9:.1f} GB is free at {stage.parent}")
    return {"src_bytes": size, "format": (fmt[0] if fmt else None),
            "free_bytes_before": free, "est_sidecar_bytes": need}


def build_section(src: Path, *, verify_ids: int = 20_000, verify_blocks_n: int = 500,
                  do_verify: bool = True, force: bool = False,
                  keep_staging: bool = False, tmp_root: Path | None = None) -> dict:
    """Build, verify and publish the flat sidecar for one section.

    Returns the build report (also written to data/eval_results by `main`).
    """
    src = Path(src)
    final = src.with_suffix(src.suffix + FLAT_SUFFIX)
    stage = src.with_suffix(src.suffix + STAGING_SUFFIX)
    rep: dict = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "section": src.parent.name, "src": str(src),
                 "published_dir": str(final), "staging_dir": str(stage),
                 "stages": {}, "pass": False}

    if final.exists():
        raise SystemExit(
            f"{final} already exists — refusing to overwrite a published "
            f"sidecar. Run `verify --section {src.parent.name}` to re-check it, "
            f"or remove the directory deliberately and rerun.")

    rep["preflight"] = preflight(src, stage)
    _guard_staging(stage)
    if force and stage.exists():
        log.info("--force: discarding staging %s", stage)
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)

    partial = stage / "blocks.bin.partial"
    if partial.exists():
        log.info("removing %s left by an interrupted run (%.2f GB)",
                 partial.name, partial.stat().st_size / 1e9)
        partial.unlink()

    ok, why = flat_stage_state(stage, src)
    t0 = time.perf_counter()
    if ok:
        log.info("stage flat: SKIP (already complete)")
        rep["stages"]["flat"] = {"skipped": True, "reason": why}
    else:
        log.info("stage flat: building blocks.bin (%s)", why)
        info = build_flat_sidecar(src, stage)
        info["seconds"] = round(time.perf_counter() - t0, 1)
        info["skipped"] = False
        rep["stages"]["flat"] = info
        ok, why = flat_stage_state(stage, src)
        if not ok:
            raise SystemExit(f"flat stage finished but does not validate: {why}")
    flat_stamp = _load_json(stage / FLAT_STAMP) or {}
    flat_id = flat_stamp.get(FLAT_ID_KEY)

    ok, why = dicts_stage_state(stage, flat_id)
    if ok:
        log.info("stage dicts: SKIP (already complete)")
        rep["stages"]["dicts"] = {"skipped": True, "reason": why}
    else:
        log.info("stage dicts: rehoming zstd dictionaries (%s)", why)
        t0 = time.perf_counter()
        meta = dump_dict_sidecar(src, stage)
        meta["seconds"] = round(time.perf_counter() - t0, 1)
        meta["skipped"] = False
        rep["stages"]["dicts"] = meta
        ok, why = dicts_stage_state(stage, flat_id)
        if not ok:
            raise SystemExit(f"dict stage finished but does not validate: {why}")

    ok, why = locator_stage_state(stage, flat_id)
    if ok:
        log.info("stage locator: SKIP (already complete)")
        rep["stages"]["locator"] = {"skipped": True, "reason": why}
    else:
        log.info("stage locator: building loc_*.npy (%s)", why)
        t0 = time.perf_counter()
        stamp = build_ordinal_locator(src, stage)
        stamp["seconds"] = round(time.perf_counter() - t0, 1)
        stamp["skipped"] = False
        rep["stages"]["locator"] = stamp
        ok, why = locator_stage_state(stage, flat_id)
        if not ok:
            raise SystemExit(f"locator stage finished but does not validate: {why}")
    loc_stamp = _load_json(stage / LOCATOR_STAMP) or {}

    rep["sizes"] = _sizes(src, stage)
    rep["skipped_non_wid"] = loc_stamp.get("skipped_non_wid")
    rep["sqlite_deletable"] = (loc_stamp.get("skipped_non_wid") == 0
                               and (stage / DICTS_STAMP).exists())

    if do_verify:
        tmp = Path(tmp_root or tempfile.mkdtemp(prefix="flatverify_")) / "views"
        if tmp.exists():
            shutil.rmtree(tmp)
        try:
            t0 = time.perf_counter()
            rep["verify_reads"] = verify_reads(src, stage, tmp, verify_ids)
            rep["verify_reads"]["seconds"] = round(time.perf_counter() - t0, 1)
            rep["verify_blocks"] = verify_blocks(src, stage, verify_blocks_n)
        finally:
            shutil.rmtree(tmp.parent, ignore_errors=True)
        rep["pass"] = bool(rep["verify_reads"]["pass"]
                           and rep["verify_blocks"]["pass"])
        if not rep["pass"]:
            log.error("VERIFY FAILED — not publishing. staging kept at %s", stage)
            rep["published"] = False
            return rep
        log.info("verify PASS: %d ids byte-identical on every arm, %d blocks "
                 "byte-identical", rep["verify_reads"]["ids_checked"],
                 rep["verify_blocks"]["blocks_checked"])
    else:
        rep["pass"] = None
        log.warning("verification SKIPPED (--no-verify) — publishing unverified")

    os.rename(stage, final)
    rep["published"] = True
    log.info("published %s — the section now serves flat (delete the directory "
             "to revert)", final)
    if not keep_staging:
        rep["staging_dir"] = None
    return rep


def _sizes(src: Path, flat_dir: Path) -> dict:
    def _b(name):
        p = flat_dir / name
        return p.stat().st_size if p.exists() else 0
    loc = sum(_b(f"loc_{k}.npy") for k in ("wids", "b", "off", "n"))
    idx = sum(_b(f"block_{k}.npy") for k in ("offsets", "lengths", "dictids"))
    dicts = sum(p.stat().st_size for p in flat_dir.glob("zdict_*"))
    blocks = _b("blocks.bin")
    return {"abstracts_sqlite_bytes": src.stat().st_size,
            "blocks_bin_bytes": blocks, "block_index_bytes": idx,
            "locator_bytes": loc, "dicts_bytes": dicts,
            "sidecar_total_bytes": blocks + idx + loc + dicts,
            "delta_vs_sqlite_bytes": (blocks + idx + loc + dicts)
                                     - src.stat().st_size}


def cmd_build(args) -> int:
    section, src = resolve_src(args)
    rep = build_section(src, verify_ids=args.verify_ids,
                        verify_blocks_n=args.verify_blocks,
                        do_verify=not args.no_verify, force=args.force,
                        keep_staging=args.keep_staging)
    _write_report(args, rep, f"flat_build_{section}")
    return 0 if rep.get("pass") is not False else 1


def cmd_verify(args) -> int:
    section, src = resolve_src(args)
    flat = src.with_suffix(src.suffix + FLAT_SUFFIX)
    if not flat.is_dir():
        stage = src.with_suffix(src.suffix + STAGING_SUFFIX)
        if stage.is_dir():
            log.warning("no published sidecar; verifying the staging dir %s", stage)
            flat = stage
        else:
            raise SystemExit(f"{flat} does not exist — build it first")
    rep = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%S"), "section": section,
           "src": str(src), "flat_dir": str(flat), "mode": "verify-only"}
    stamp = _load_json(flat / FLAT_STAMP) or {}
    fid = stamp.get(FLAT_ID_KEY)
    for name, (ok, why) in {
            "flat": flat_stage_state(flat, src),
            "dicts": dicts_stage_state(flat, fid),
            "locator": locator_stage_state(flat, fid)}.items():
        rep.setdefault("stage_state", {})[name] = {"ok": ok, "why": why}
    tmp = Path(tempfile.mkdtemp(prefix="flatverify_")) / "views"
    try:
        rep["verify_reads"] = verify_reads(src, flat, tmp, args.verify_ids)
        rep["verify_blocks"] = verify_blocks(src, flat, args.verify_blocks)
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    rep["sizes"] = _sizes(src, flat)
    loc = _load_json(flat / LOCATOR_STAMP) or {}
    rep["skipped_non_wid"] = loc.get("skipped_non_wid")
    rep["sqlite_deletable"] = (loc.get("skipped_non_wid") == 0
                               and (flat / DICTS_STAMP).exists())
    rep["pass"] = bool(rep["verify_reads"]["pass"] and rep["verify_blocks"]["pass"])
    log.info("verify %s: %s", section, "PASS" if rep["pass"] else "FAIL")
    _write_report(args, rep, f"flat_verify_{section}")
    return 0 if rep["pass"] else 1


def _write_report(args, rep: dict, prefix: str) -> None:
    out = (Path(args.report) if args.report else
           REPO / "data" / "eval_results" /
           f"{prefix}_{time.strftime('%Y%m%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2))
    log.info("report -> %s", out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--index-root", type=Path, default=DEFAULT_INDEX_ROOT)
        p.add_argument("--section", help="section directory name")
        p.add_argument("--src", help="path to an abstracts.sqlite (overrides "
                                     "--section; for tests/staged copies)")
        p.add_argument("--verify-ids", type=int, default=20_000,
                       help="ids in the byte-parity gate (0 disables the read "
                            "gate; the doc 18 gate is 20,000)")
        p.add_argument("--verify-blocks", type=int, default=500,
                       help="blocks in the container-level byte check")
        p.add_argument("--report", help="write the JSON report here")

    p = sub.add_parser("plan", help="stat-only survey + the exact build commands")
    p.add_argument("--index-root", type=Path, default=DEFAULT_INDEX_ROOT)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("build", help="build + verify + publish one section")
    common(p)
    p.add_argument("--force", action="store_true",
                   help="discard an existing staging dir and rebuild it")
    p.add_argument("--no-verify", action="store_true",
                   help="publish without the parity gate (NOT recommended)")
    p.add_argument("--keep-staging", action="store_true")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("verify", help="re-check an already-built sidecar")
    common(p)
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
