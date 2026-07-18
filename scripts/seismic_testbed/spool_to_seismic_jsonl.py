#!/usr/bin/env python3
"""SEISMIC testbed — P1: stream the stored SPLADE `sparse_field` to SEISMIC jsonl.

`docs/seismic_150m_testbed/03_BENCHMARK_METHODOLOGY.md` §1: "No re-encoding.
SEISMIC is fed the *already-stored* SPLADE vectors." This converter reads the
`sparse_field` (dict {token: float weight}, int8 impacts stored as float) from
each doc in `spool_backup/<section>/slice_*.jsonl.zst` and emits SEISMIC's
native jsonl format:

    {"id": <str>, "vector": {<token>: <float>, ...}}

so `SeismicIndex.build(jsonl_path)` can index them with no re-encode. Per the
upstream `docs/RunExperiments.md` data format + the verified build path in the
plan (id may be int|str; vector is a token→score dict).

Reproduces the BMP probe's 0.93M vs 2.0M med_bio split: `--limit N` caps the
doc count across slices (same mechanism `build_thinclient_index.py
--limit` uses), so SEISMIC's G4 pruning run probes the SAME corpora BMP did →

Memory-bounded: streams each zst slice with an 8 MiB read buffer (the
`iter_slice` shape from `scripts/build_thinclient_index.py`), never holding a
full slice in RAM — the 31.6 GB host has ~7 GB free and a 2.86 GB compressed
slice decompresses far past that.

Isolation (mirror `spike/archive/mmap_bmp/build_persona_bmp.py`): writes to an
EXTERNAL ext4 dir, NOT the serving `data/` path; never deletes spool slices.

Run from repo root (project venv — has zstandard + orjson):

    .venv/bin/python3 scripts/seismic_testbed/spool_to_seismic_jsonl.py \\
        --section med_bio \\
        --out-dir /tmp/seismic_testbed/jsonl \\
        --limit 929000        # the 0.93M sub-shard (mirrors BMP splade_001)

    # 2.0M sub-shard (mirrors BMP splade_000):
    .venv/bin/python3 scripts/seismic_testbed/spool_to_seismic_jsonl.py \\
        --section med_bio --out-dir /tmp/seismic_testbed/jsonl \\
        --limit 2000000 --tag 2m
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import zstandard

try:
    import orjson
    _loads = orjson.loads
except ImportError:  # orjson is in the serving venv; fall back if absent
    _loads = json.loads

log = logging.getLogger("spool2seismic")


def iter_slice(path: Path):
    """Stream a zstd-compressed jsonl slice line-by-line. Memory-bounded:
    never holds the decompressed slice in RAM (a 2.86 GB compressed med_bio
    slice decompresses far past the ~7 GB free on the 31.6 GB host). Mirrors
    `scripts/build_thinclient_index.iter_slice`."""
    dctx = zstandard.ZstdDecompressor()
    with open(path, "rb") as fh, dctx.stream_reader(fh) as reader:
        buf = b""
        while True:
            chunk = reader.read(8 << 20)
            if not chunk:
                break
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for ln in lines:
                if ln:
                    yield _loads(ln)
        if buf.strip():
            yield _loads(buf)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--section", default="med_bio")
    ap.add_argument("--spool-root", default="data/thinclient_index/spool_backup")
    ap.add_argument("--out-dir", required=True,
                    help="external ext4 dir (NOT the serving data/ path)")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap docs across slices (reproduces BMP 0.93M / 2.0M split)")
    ap.add_argument("--tag", default=None,
                    help="filename tag (default: limit, e.g. 929000 -> med_bio_929000.jsonl)")
    ap.add_argument("--slices", type=int, default=None,
                    help="optional: only first N slices (None=all)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    spool_dir = Path(args.spool_root) / args.section
    slices = sorted(spool_dir.glob("slice_*.jsonl.zst"))
    assert slices, f"no slices at {spool_dir}"
    if args.slices:
        slices = slices[:args.slices]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = args.tag or (str(args.limit) if args.limit else "all")
    out = out_dir / f"{args.section}_{tag}.jsonl"

    # Count distinct non-empty vectors + total terms seen (report empties, don't drop silently).
    n = 0
    n_empty = 0
    n_terms = 0
    max_terms = 0
    t0 = time.perf_counter()
    log.info("spool->seismic: section=%s slices=%d limit=%s -> %s",
             args.section, len(slices), args.limit, out)
    with open(out, "w") as fout:
        for sp in slices:
            if args.limit is not None and n >= args.limit:
                break
            log.info("  %s", sp.name)
            remaining = (args.limit - n) if (args.limit is not None) else None
            for rec in iter_slice(sp):
                if remaining is not None and n >= args.limit:
                    break
                sparse = rec.get("sparse_field")
                if not sparse:
                    n_empty += 1
                    continue
                doc_id = rec.get("openalex_id") or rec.get("id")
                if doc_id is None:
                    # An id-less record can't be joined back to meta; skip loudly.
                    n_empty += 1
                    continue
                # The stored sparse_field IS the SPLADE vector (int8 impacts as
                # float). Pass through unchanged — NO re-encode.
                fout.write(json.dumps({"id": doc_id, "vector": sparse}))
                fout.write("\n")
                n += 1
                nt = len(sparse)
                n_terms += nt
                if nt > max_terms:
                    max_terms = nt
            if remaining is not None and n >= args.limit:
                break
            log.info("    running docs=%d", n)

    dt = time.perf_counter() - t0
    avg_terms = (n_terms / n) if n else 0
    log.info("wrote %s: %d docs, %d empty/skipped, avg_terms=%.1f max_terms=%d "
             "in %.1fs (%.0f docs/s)",
             out, n, n_empty, avg_terms, max_terms, dt, n / dt if dt else 0)
    size_gb = out.stat().st_size / 1e9
    log.info("on-disk %.3f GB", size_gb)
    # Emit a sidecar manifest the builder can read (avoids re-stat/parse).
    mpath = out.with_suffix(".manifest.json")
    json.dump({
        "jsonl": str(out),
        "section": args.section,
        "docs": n,
        "empty_skipped": n_empty,
        "avg_terms_per_doc": round(avg_terms, 2),
        "max_terms_per_doc": max_terms,
        "on_disk_gb": round(size_gb, 4),
        "limit": args.limit,
        "slices_used": [s.name for s in slices],
        "built_utc": "2026-06-26",
        "source": "spool_backup sparse_field (NO re-encode)",
    }, open(mpath, "w"), indent=2)
    print(json.dumps({"jsonl": str(out), "docs": n, "size_gb": round(size_gb, 4),
                      "avg_terms": round(avg_terms, 2), "max_terms": max_terms}))


if __name__ == "__main__":
    main()
