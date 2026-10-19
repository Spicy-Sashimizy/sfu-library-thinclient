#!/usr/bin/env python3
"""Per-script zstd dictionary effect measured on the PRODUCTION abstract sidecar.

Track: spike/dict_effect_at_scale (timed information-retrieval spike, NOT
product code; imports nothing from source/, reads the sidecar files only).
Results: data/eval_results/dict_effect_at_scale_2026-10-19.json
Doc: docs/STORAGE_BUDGET_150M.md, spike/dict_effect_at_scale/README.md

Why: the dictionary lever was only ever measured on a 20,000-abstract sample
(scripts/experiments/eval_text_compression.py, eval_per_language_dicts.py,
2026-06-11) and the docs projected that sample ratio to "64.7 -> 52.9 GB at
150M". This script measures the real thing: EVERY block of the served hot
section's flat sidecar (`abstracts.sqlite.flat/`), read-only.

Per block: pread the compressed bytes, decompress with the shipped per-script
dictionary (parity: recompressing with the same dictionary at the same level
must reproduce the stored bytes byte-for-byte; a non-identical block is
additionally round-tripped), then recompress the raw payload at zstd-19 under
four arms:
    a  shipped per-script dictionary (what is on disk)
    b  no dictionary
    c  one shared dictionary trained here on a mixed 20,000-doc sample drawn
       uniformly over the section's docs (same trainer, same 112 KB size)
    d  the latin bucket's dictionary applied to every bucket
Records bytes per arm, decode time per arm per block, docs per block (from the
ordinal locator), per-bucket and whole-section totals, and projects the per-doc
figures to the 150.4M-doc corpus (marked est.: the hot section's script mix is
not the corpus's).

Cold sections: the nine packed sections were built with `abstracts_stored: 0`
(cold policy: abstracts come from the OpenAlex API at rerank time), so there
are no cold blocks to sample. `--cold-scan-only` streams every packed
archive's member list (~10 min single-threaded over 84 GB; run it concurrently
with the census) into `<out>_cold_scan.json`; the census embeds that file when
it exists so the gap is evidence in the results file, not an assertion.

Decode timings are taken while all 16 hardware threads run zstd-19
compression, so they are "under full compression load", not serving latency.

Run (16-thread host, ~55 min for the 1,062,917-block hot section):
    .venv/bin/python3 spike/dict_effect_at_scale/eval_dict_effect_at_scale.py \
        --cold-scan-only &
    .venv/bin/python3 spike/dict_effect_at_scale/eval_dict_effect_at_scale.py \
        --procs 16
Smoke test:
    .venv/bin/python3 spike/dict_effect_at_scale/eval_dict_effect_at_scale.py \
        --limit-blocks 2000 --out /tmp/smoke.json
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import multiprocessing as mp
import os
import platform
import socket
import tarfile
import time
from pathlib import Path

import numpy as np
import zstandard

REPO_ROOT = Path(__file__).resolve().parents[2]

# Mirrors of the production constants in source/lib/thinclient/abstracts.py
# (DICT_SIZE, COMPRESSION_LEVEL, BLOCK_TARGET, TRAIN_TARGET_DOCS, FLAT_STAMP,
# DICTS_STAMP). Copied, not imported: this spike must not touch mainline code.
DICT_SIZE = 112 * 1024
COMPRESSION_LEVEL = 19
BLOCK_TARGET = 32 * 1024
TRAIN_TARGET_DOCS = 20_000
FLAT_STAMP = "flat_store.json"
DICTS_STAMP = "dicts.json"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("eval_dict_effect_at_scale")

DATE = "2026-10-19"
SEED = 20261019
HOT_SECTION = "social_sciences__recent"
INDEX_ROOT = REPO_ROOT / "data/thinclient_index"
FLAT_DIR = INDEX_ROOT / "sections" / HOT_SECTION / "abstracts.sqlite.flat"
OUT = REPO_ROOT / f"data/eval_results/dict_effect_at_scale_{DATE}.json"
CORPUS_DOCS = 150_413_098
ARMS = ("a_shipped", "b_nodict", "c_shared", "d_latin")
ROW_DTYPE = np.dtype([
    ("block", np.uint32), ("dict_id", np.uint8), ("docs", np.uint16),
    ("raw", np.uint32), ("stored", np.uint32),
    ("a_shipped", np.uint32), ("b_nodict", np.uint32),
    ("c_shared", np.uint32), ("d_latin", np.uint32),
    ("identical", np.uint8), ("roundtrip_ok", np.uint8),
    ("dec_us_a", np.uint16), ("dec_us_b", np.uint16),
    ("dec_us_c", np.uint16), ("dec_us_d", np.uint16),
    ("enc_us_total", np.uint32),
])

_W: dict = {}


def _rel(p: Path) -> str:
    return str(p.relative_to(REPO_ROOT) if p.is_relative_to(REPO_ROOT) else p)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_flat(flat_dir: Path) -> dict:
    stamp = json.loads((flat_dir / FLAT_STAMP).read_text())
    dmeta = json.loads((flat_dir / DICTS_STAMP).read_text())
    if dmeta["flat_store_id"] != stamp["flat_store_id"]:
        raise RuntimeError("dicts.json / flat_store.json identity mismatch")
    names = list(dmeta["names"])
    dict_bytes = {}
    for n in names:
        p = flat_dir / f"zdict_{n}"
        dict_bytes[n] = p.read_bytes() if p.exists() else None
    if dict_bytes.get("latin") is None:
        raise RuntimeError("no latin dictionary in the sidecar")
    offsets = np.load(flat_dir / "block_offsets.npy")
    lengths = np.load(flat_dir / "block_lengths.npy")
    dict_ids = np.load(flat_dir / "block_dictids.npy")
    loc_b = np.load(flat_dir / "loc_b.npy")
    loc_off = np.load(flat_dir / "loc_off.npy")
    loc_n = np.load(flat_dir / "loc_n.npy")
    docs_per_block = np.bincount(loc_b, minlength=len(offsets)).astype(np.int64)
    valid = np.nonzero(offsets >= 0)[0]
    if int(len(valid)) != int(stamp["blocks"]):
        raise RuntimeError("block count disagrees with flat_store.json")
    return {"stamp": stamp, "names": names, "dict_bytes": dict_bytes,
            "offsets": offsets, "lengths": lengths, "dict_ids": dict_ids,
            "loc_b": loc_b, "loc_off": loc_off, "loc_n": loc_n,
            "docs_per_block": docs_per_block, "valid": valid}


def _dctx_for(names, dict_bytes):
    latin = zstandard.ZstdCompressionDict(dict_bytes["latin"])
    out = {}
    for n in names:
        raw = dict_bytes.get(n)
        zd = zstandard.ZstdCompressionDict(raw) if raw else latin
        out[n] = zstandard.ZstdDecompressor(dict_data=zd)
    return out


def train_shared_dict(flat: dict, seed: int, n_docs: int) -> dict:
    rng = np.random.default_rng(seed)
    n_total = len(flat["loc_b"])
    pick = np.sort(rng.choice(n_total, size=n_docs, replace=False))
    blocks = flat["loc_b"][pick]
    order = np.argsort(blocks, kind="stable")
    pick, blocks = pick[order], blocks[order]
    dctx = _dctx_for(flat["names"], flat["dict_bytes"])
    fd = os.open(str(FLAT_DIR / "blocks.bin"), os.O_RDONLY)
    samples, composition = [], {}
    t0 = time.perf_counter()
    try:
        cur_b, raw = -1, b""
        for i, b in zip(pick, blocks):
            b = int(b)
            if b != cur_b:
                zb = os.pread(fd, int(flat["lengths"][b]), int(flat["offsets"][b]))
                name = flat["names"][int(flat["dict_ids"][b])]
                raw = dctx[name].decompress(zb)
                cur_b = b
            off, n = int(flat["loc_off"][i]), int(flat["loc_n"][i])
            samples.append(raw[off:off + n])
            composition[name] = composition.get(name, 0) + 1
    finally:
        os.close(fd)
    t_read = time.perf_counter() - t0
    t0 = time.perf_counter()
    zdict = zstandard.train_dictionary(DICT_SIZE, samples)
    t_train = time.perf_counter() - t0
    data = zdict.as_bytes()
    logger.info("shared dict: %d samples from %d blocks, %d bytes, train %.1fs",
                len(samples), len(set(blocks.tolist())), len(data), t_train)
    return {"bytes": data, "n_samples": len(samples),
            "n_blocks_touched": int(len(set(blocks.tolist()))),
            "sample_bytes": int(sum(len(s) for s in samples)),
            "composition_by_bucket": composition,
            "read_secs": round(t_read, 2), "train_secs": round(t_train, 2),
            "sha256": _sha256(data), "dict_id": zdict.dict_id()}


def _worker_init(flat_dir: str, names: list, dict_bytes: dict,
                 shared: bytes) -> None:
    _W["fd"] = os.open(str(Path(flat_dir) / "blocks.bin"), os.O_RDONLY)
    _W["names"] = names
    _W["dctx"] = _dctx_for(names, dict_bytes)
    latin = zstandard.ZstdCompressionDict(dict_bytes["latin"])
    shared_zd = zstandard.ZstdCompressionDict(shared)
    _W["cctx_a"] = {}
    for n in names:
        raw = dict_bytes.get(n)
        zd = zstandard.ZstdCompressionDict(raw) if raw else latin
        _W["cctx_a"][n] = zstandard.ZstdCompressor(level=COMPRESSION_LEVEL,
                                                   dict_data=zd)
    _W["has_own_dict"] = {n: dict_bytes.get(n) is not None for n in names}
    _W["cctx_b"] = zstandard.ZstdCompressor(level=COMPRESSION_LEVEL)
    _W["cctx_c"] = zstandard.ZstdCompressor(level=COMPRESSION_LEVEL,
                                            dict_data=shared_zd)
    _W["cctx_d"] = zstandard.ZstdCompressor(level=COMPRESSION_LEVEL,
                                            dict_data=latin)
    _W["dctx_b"] = zstandard.ZstdDecompressor()
    _W["dctx_c"] = zstandard.ZstdDecompressor(dict_data=shared_zd)
    _W["dctx_d"] = zstandard.ZstdDecompressor(dict_data=latin)


def _us(t0: float) -> int:
    return min(int((time.perf_counter() - t0) * 1e6), 65535)


def _run_chunk(task) -> np.ndarray:
    blocks, offs, lens, dids, docs = task
    rows = np.zeros(len(blocks), dtype=ROW_DTYPE)
    fd = _W["fd"]
    for i in range(len(blocks)):
        b, off, ln, did = int(blocks[i]), int(offs[i]), int(lens[i]), int(dids[i])
        name = _W["names"][did]
        zb = os.pread(fd, ln, off)
        for _ in range(5):
            if len(zb) == ln:
                break
            time.sleep(0.5)
            zb = os.pread(fd, ln, off)
        if len(zb) != ln:
            raise RuntimeError(f"short read on block {b}")
        t0 = time.perf_counter()
        raw = _W["dctx"][name].decompress(zb)
        dec_a = _us(t0)
        t_enc = time.perf_counter()
        za = _W["cctx_a"][name].compress(raw)
        identical = za == zb
        roundtrip_ok = identical or _W["dctx"][name].decompress(za) == raw
        zb_ = _W["cctx_b"].compress(raw)
        zc = _W["cctx_c"].compress(raw)
        latin_is_own = name == "latin" or not _W["has_own_dict"][name]
        zd = za if latin_is_own else _W["cctx_d"].compress(raw)
        enc_us = int((time.perf_counter() - t_enc) * 1e6)
        t0 = time.perf_counter(); _W["dctx_b"].decompress(zb_); dec_b = _us(t0)
        t0 = time.perf_counter(); _W["dctx_c"].decompress(zc); dec_c = _us(t0)
        if latin_is_own:
            dec_d = dec_a
        else:
            t0 = time.perf_counter(); _W["dctx_d"].decompress(zd); dec_d = _us(t0)
        rows[i] = (b, did, min(int(docs[i]), 65535), len(raw), ln,
                   len(za), len(zb_), len(zc), len(zd),
                   int(identical), int(roundtrip_ok),
                   dec_a, dec_b, dec_c, dec_d, enc_us)
    return rows


def run_hot(flat: dict, shared: bytes, procs: int, chunk: int,
            limit: int | None) -> np.ndarray:
    valid = flat["valid"]
    if limit:
        rng = np.random.default_rng(SEED + 1)
        valid = np.sort(rng.choice(valid, size=min(limit, len(valid)),
                                   replace=False))
    tasks = []
    for s in range(0, len(valid), chunk):
        bl = valid[s:s + chunk]
        tasks.append((bl, flat["offsets"][bl], flat["lengths"][bl],
                      flat["dict_ids"][bl], flat["docs_per_block"][bl]))
    logger.info("hot: %d blocks in %d chunks on %d procs", len(valid),
                len(tasks), procs)
    ctx = mp.get_context("fork")
    out, done, t0 = [], 0, time.perf_counter()
    with ctx.Pool(procs, initializer=_worker_init,
                  initargs=(str(FLAT_DIR), flat["names"], flat["dict_bytes"],
                            shared)) as pool:
        for rows in pool.imap_unordered(_run_chunk, tasks):
            out.append(rows)
            done += len(rows)
            if len(out) % 20 == 0 or done == len(valid):
                el = time.perf_counter() - t0
                logger.info("hot: %d/%d blocks, %.0fs, eta %.0fs", done,
                            len(valid), el, el / done * (len(valid) - done))
    rows = np.concatenate(out)
    rows.sort(order="block")
    return rows


def _pct(a: np.ndarray, q: float) -> float:
    return float(np.percentile(a, q)) if len(a) else float("nan")


def _bucket_table(rows: np.ndarray, names: list, flat: dict) -> dict:
    table = {}
    for did, name in enumerate(names):
        r = rows[rows["dict_id"] == did]
        if not len(r):
            continue
        docs = int(r["docs"].sum())
        raw = int(r["raw"].sum())
        ent = {"dict_id": did, "has_own_dict": flat["dict_bytes"].get(name) is not None,
               "blocks": int(len(r)), "docs": docs, "raw_bytes": raw,
               "stored_bytes": int(r["stored"].sum()),
               "raw_bytes_per_doc": round(raw / docs, 2) if docs else None,
               "arms": {}}
        for arm in ARMS:
            tot = int(r[arm].sum())
            ent["arms"][arm] = {
                "bytes": tot,
                "bytes_per_block": round(tot / len(r), 1),
                "bytes_per_doc": round(tot / docs, 2) if docs else None,
                "ratio_raw_over_arm": round(raw / tot, 4) if tot else None,
                "pct_vs_b_nodict": round(100.0 * (tot / int(r["b_nodict"].sum()) - 1), 2),
                "decode_us_mean": round(float(r["dec_us_" + arm[0]].mean()), 1),
                "decode_us_p50": round(_pct(r["dec_us_" + arm[0]], 50), 1),
                "decode_us_p99": round(_pct(r["dec_us_" + arm[0]], 99), 1),
            }
        ent["parity"] = {"identical": int(r["identical"].sum()),
                         "roundtrip_ok": int(r["roundtrip_ok"].sum()),
                         "blocks": int(len(r))}
        ent["encode_us_per_block_mean"] = round(float(r["enc_us_total"].mean()), 1)
        table[name] = ent
    return table


def _totals(rows: np.ndarray) -> dict:
    docs = int(rows["docs"].sum())
    raw = int(rows["raw"].sum())
    out = {"blocks": int(len(rows)), "docs": docs, "raw_bytes": raw,
           "stored_bytes": int(rows["stored"].sum()),
           "raw_bytes_per_doc": round(raw / docs, 2), "arms": {}}
    nod = int(rows["b_nodict"].sum())
    for arm in ARMS:
        tot = int(rows[arm].sum())
        out["arms"][arm] = {
            "bytes": tot, "gb": round(tot / 1e9, 3),
            "bytes_per_doc": round(tot / docs, 2),
            "ratio_raw_over_arm": round(raw / tot, 4),
            "pct_vs_b_nodict": round(100.0 * (tot / nod - 1), 2),
            "saved_vs_b_nodict_bytes": nod - tot,
            "decode_us_mean": round(float(rows["dec_us_" + arm[0]].mean()), 1),
            "decode_us_p50": round(_pct(rows["dec_us_" + arm[0]], 50), 1),
            "decode_us_p99": round(_pct(rows["dec_us_" + arm[0]], 99), 1),
        }
    return out


def scan_cold_archives(index_root: Path) -> dict:
    status = json.loads((index_root / "build_status.json").read_text())
    out = {}
    for name in sorted(status.get("sections_packed", [])):
        archive = index_root / "packed" / f"{name}.tar.zst"
        info = status.get("section_info", {}).get(name, {})
        ent = {"archive": str(archive.relative_to(REPO_ROOT)),
               "archive_bytes": archive.stat().st_size if archive.exists() else None,
               "build_status_docs": info.get("docs"),
               "build_status_abstracts_stored": info.get("abstracts_stored"),
               "build_status_hot": info.get("hot")}
        live_dir = index_root / "sections" / name
        ent["live_dir_entries"] = (sorted(p.name for p in live_dir.iterdir())
                                   if live_dir.is_dir() else None)
        t0 = time.perf_counter()
        members, abstract_members, total = 0, [], 0
        try:
            dctx = zstandard.ZstdDecompressor(max_window_size=2 ** 27)
            with open(archive, "rb") as fh, dctx.stream_reader(fh) as zr, \
                    tarfile.open(fileobj=io.BufferedReader(zr, buffer_size=8 << 20),
                                 mode="r|") as tar:
                for m in tar:
                    members += 1
                    total += m.size
                    if "abstracts" in m.name:
                        abstract_members.append({"name": m.name, "size": m.size})
            ent["scan_error"] = None
        except Exception as exc:
            ent["scan_error"] = f"{type(exc).__name__}: {exc}"
        ent.update({"members": members, "member_bytes_total": total,
                    "abstract_members": abstract_members,
                    "scan_secs": round(time.perf_counter() - t0, 1),
                    "abstract_blocks_available": bool(abstract_members)})
        logger.info("cold scan %s: %d members, %d abstract members", name,
                    members, len(abstract_members))
        out[name] = ent
    return out


def main() -> None:
    global FLAT_DIR
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--flat-dir", type=Path, default=FLAT_DIR)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--procs", type=int, default=os.cpu_count() or 8)
    ap.add_argument("--chunk", type=int, default=500)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--train-docs", type=int, default=TRAIN_TARGET_DOCS)
    ap.add_argument("--limit-blocks", type=int, default=None)
    ap.add_argument("--cold-scan-only", action="store_true")
    ap.add_argument("--no-rows", action="store_true")
    args = ap.parse_args()
    FLAT_DIR = args.flat_dir
    cold_path = args.out.with_name(args.out.stem + "_cold_scan.json")

    if args.cold_scan_only:
        t0 = time.perf_counter()
        cold = scan_cold_archives(INDEX_ROOT)
        cold_path.parent.mkdir(parents=True, exist_ok=True)
        cold_path.write_text(json.dumps({
            "date": DATE, "scan_secs": round(time.perf_counter() - t0, 1),
            "status": ("NOT MEASURABLE: every packed section was built with "
                       "abstracts_stored == 0 (cold policy: no sidecar), so "
                       "there are no cold blocks to sample"),
            "any_abstract_blocks": any(v["abstract_blocks_available"]
                                       for v in cold.values()),
            "any_scan_error": any(v["scan_error"] for v in cold.values()),
            "sections": cold}, indent=2))
        logger.info("wrote %s", cold_path)
        return

    lock = Path("/tmp/sfu_latency_measure.lock")
    try:
        lock_fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(f"{lock} is held by another benchmark; refusing to run")
    os.write(lock_fd, f"eval_dict_effect_at_scale pid {os.getpid()}\n".encode())
    os.close(lock_fd)
    try:
        _census(args, cold_path)
    finally:
        lock.unlink(missing_ok=True)


def _census(args, cold_path: Path) -> None:
    t_start = time.perf_counter()
    flat = load_flat(FLAT_DIR)
    names = flat["names"]
    logger.info("flat store %s: %d blocks, %d docs, dicts %s",
                flat["stamp"]["flat_store_id"], len(flat["valid"]),
                len(flat["loc_b"]), names)

    shared = train_shared_dict(flat, args.seed, args.train_docs)
    rows = run_hot(flat, shared["bytes"], args.procs, args.chunk,
                   args.limit_blocks)
    hot_secs = time.perf_counter() - t_start
    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows_path = args.out.with_name(args.out.stem + "_hot_blocks.npz")
    dict_path = args.out.with_name(args.out.stem + "_shared.zdict")
    if not args.no_rows:
        np.savez_compressed(rows_path, rows=rows)
        dict_path.write_bytes(shared["bytes"])
        logger.info("saved per-block rows %s", rows_path)
    locator_meta = json.loads((FLAT_DIR / "locator.json").read_text())
    build_status = json.loads((INDEX_ROOT / "build_status.json").read_text())
    cap = 65535
    decode_capped = {arm: int((rows["dec_us_" + arm[0]] >= cap).sum())
                     for arm in ARMS}

    bucket_table = _bucket_table(rows, names, flat)
    totals = _totals(rows)
    parity = {"blocks": int(len(rows)),
              "identical_to_store": int(rows["identical"].sum()),
              "roundtrip_ok": int(rows["roundtrip_ok"].sum()),
              "stored_bytes_equal_arm_a": bool(totals["stored_bytes"] == totals["arms"]["a_shipped"]["bytes"]),
              "non_identical_blocks_first_20": rows["block"][rows["identical"] == 0][:20].tolist(),
              "roundtrip_failures_first_20": rows["block"][rows["roundtrip_ok"] == 0][:20].tolist(),
              "criterion": ("pass requires every block's recompression with "
                            "its shipped dictionary to equal the stored bytes; "
                            "roundtrip_ok is reported as the weaker fallback"),
              "pass": bool(rows["identical"].all()),
              "roundtrip_pass": bool(rows["roundtrip_ok"].all())}
    census = args.limit_blocks is None
    docs_in_rows = totals["docs"]
    projection = {"basis": ("every block of the hot section (census: no "
                            "sampling interval)" if census else
                            "SMOKE-TEST SUBSET — not a census"),
                  "hot_section_docs": int(len(flat["loc_b"])),
                  "corpus_docs": CORPUS_DOCS,
                  "method": ("arm bytes_per_doc from the hot section x "
                             "150,413,098 docs; est. — assumes the whole corpus "
                             "has the hot section's script mix and raw "
                             "bytes/doc"),
                  "interval": None,
                  "interval_note": ("no cold-section abstract blocks exist to "
                                    "sample (see cold_sections), so no "
                                    "bootstrap interval is possible; the hot "
                                    "figure is exact"),
                  "arms_gb_at_150m_est": {
                      arm: round(totals["arms"][arm]["bytes_per_doc"] * CORPUS_DOCS / 1e9, 2)
                      for arm in ARMS}}
    projection["dict_saving_vs_nodict_gb_at_150m_est"] = round(
        projection["arms_gb_at_150m_est"]["b_nodict"]
        - projection["arms_gb_at_150m_est"]["a_shipped"], 2)
    projection["prior_projection_2026_06_11"] = {
        "claim": "64.7 -> 52.9 GB at 150M (351.8 B/doc from a 20k sample)",
        "measured_hot_a_shipped_bytes_per_doc": totals["arms"]["a_shipped"]["bytes_per_doc"],
        "measured_hot_raw_bytes_per_doc": totals["raw_bytes_per_doc"],
        "sample_raw_bytes_per_doc_2026_06_11": 1203}

    result = {
        "date": DATE, "script": "spike/dict_effect_at_scale/eval_dict_effect_at_scale.py",
        "config": {
            "seed": args.seed, "host": socket.gethostname(),
            "cpu": platform.processor() or os.uname().machine,
            "cpu_count": os.cpu_count(), "procs": args.procs, "chunk": args.chunk,
            "python": platform.python_version(),
            "zstandard": zstandard.__version__,
            "zstd": ".".join(map(str, zstandard.ZSTD_VERSION)),
            "zstd_level": COMPRESSION_LEVEL, "dict_size": DICT_SIZE,
            "block_target": BLOCK_TARGET, "train_docs": args.train_docs,
            "limit_blocks": args.limit_blocks,
            "hot_section": HOT_SECTION, "flat_dir": str(FLAT_DIR),
            "flat_store_id": flat["stamp"]["flat_store_id"],
            "blocks_per_bucket": {n: int((flat["dict_ids"][flat["valid"]] == i).sum())
                                  for i, n in enumerate(names)},
            "shipped_dicts": {n: ({"bytes": len(b), "sha256": _sha256(b)} if b
                                  else None) for n, b in flat["dict_bytes"].items()},
            "shared_dict": {k: v for k, v in shared.items() if k != "bytes"},
            "arms": {"a_shipped": "the block's shipped per-script dictionary",
                     "b_nodict": "zstd-19, no dictionary",
                     "c_shared": "one 112 KB dictionary trained on a mixed "
                                 "20k-doc sample drawn uniformly over all "
                                 "buckets (differs from a in two ways at "
                                 "once: shared vs per-script, and a uniform "
                                 "random sample vs each bucket's first 20k "
                                 "docs in ingest order)",
                     "d_latin": "the latin dictionary applied to every bucket "
                                "(equals a for latin and for buckets that "
                                "shipped without their own dictionary)"},
        },
        "hot": {"section": HOT_SECTION, "census": census,
                "per_bucket": bucket_table, "totals": totals,
                "parity": parity, "wall_secs_incl_load_and_train": round(hot_secs, 1),
                "docs_in_measured_blocks": docs_in_rows,
                "locator": {"rows": locator_meta.get("rows"),
                            "skipped_non_wid": locator_meta.get("skipped_non_wid"),
                            "built_utc": locator_meta.get("built_utc")},
                "build_status_abstracts_stored": build_status.get(
                    "section_info", {}).get(HOT_SECTION, {}).get("abstracts_stored"),
                "doc_count_note": ("build_status abstracts_stored counts every "
                                   "add() including re-adds whose blocks "
                                   "finish() later deleted (the empty slots); "
                                   "the locator rows are the served docs"),
                "decode_timing_note": ("measured under full 16-thread zstd-19 "
                                       "compression load, not serving latency; "
                                       "dec_us_d equals dec_us_a for latin-dict "
                                       "blocks"),
                "decode_us_capped_at_65535": decode_capped},
        "whole_database_projection": projection,
        "timings": {"hot_wall_secs": round(hot_secs, 1),
                    "shared_dict_train_secs": shared["train_secs"]},
    }
    if cold_path.exists():
        result["cold_sections"] = json.loads(cold_path.read_text())
        result["cold_sections"]["file"] = _rel(cold_path)
    else:
        result["cold_sections"] = {"status": f"not scanned: {cold_path.name} "
                                             "absent (run --cold-scan-only)"}
    result["timings"]["total_wall_secs"] = round(time.perf_counter() - t_start, 1)
    if not args.no_rows:
        result["hot"]["per_block_rows"] = _rel(rows_path)
        result["config"]["shared_dict"]["path"] = _rel(dict_path)
    args.out.write_text(json.dumps(result, indent=2))
    logger.info("wrote %s", args.out)
    a, b = totals["arms"]["a_shipped"], totals["arms"]["b_nodict"]
    logger.info("hot totals: raw %.2f GB, shipped %.3f GB (%.1f B/doc), nodict "
                "%.3f GB, dict saving %.1f%%; parity %s",
                totals["raw_bytes"] / 1e9, a["gb"], a["bytes_per_doc"], b["gb"],
                -a["pct_vs_b_nodict"], "PASS" if parity["pass"] else "FAIL")


if __name__ == "__main__":
    main()
