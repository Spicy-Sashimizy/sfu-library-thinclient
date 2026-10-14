#!/usr/bin/env python3
"""
> **CLOSED KILLED 2026-06-26** — SEISMIC federated mmap took the slot; evidence for docs/archive/sparse_engine_project/

mmap-BMP spike — P2 STEP 1: build a persona-sized `.bmp` from spool_backup.

Loads ONE section from `spool_backup/` and builds it via the stock
`SectionBuilder` directly (NOT the era-splitting CLI), so we get a single
`sections/<section>/splade_NNN.bmp` set sized for the cold-cache gate.

WHY: the 1M test shards (~109 MB) fit page cache, so they only prove
correctness+RAM+warm. P2 needs a persona index that, with `drop_caches`,
measures true cold page-fault latency (gate G3b).

No GPU/SPLADE needed — `sparse_field` is pre-baked into every slice doc; the
builder only quantizes float→int8 on the fly (QUANT_SCALE=70, bsize=256,
identical to the serving build).

Isolation (do not touch the serving MCP):
  - Builds into an EXTERNAL index-root under the ext4 overlay (fast many-small
    writes), NOT the project .venv / data serve path.
  - Reads the spool from the 9p C: mount where it already lives (read-only-ish).
  - `--keep-spool` is implicit — this script never deletes slices.

Run from repo root (serving venv has bmp + tantivy + zstandard):
    .venv/bin/python3 spike/mmap_bmp/build_persona_bmp.py \
        --section med_bio \
        --index-root /tmp/persona_bench \
        --spool-root data/thinclient_index/spool_backup
"""
import argparse, glob, json, logging, sys, time, os
from pathlib import Path

sys.path.insert(0, "src")
from lib.thinclient.builder import (  # noqa: E402
    SectionBuilder, open_meta_db, DEFAULT_BMP_SHARD_DOCS, BMP_BLOCK_SIZE, QUANT_SCALE)
from scripts.build_thinclient_index import iter_slice  # noqa: E402

log = logging.getLogger("persona_build")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--section", default="med_bio")
    ap.add_argument("--index-root", default="/tmp/persona_bench",
                    help="external ext4 dir (NOT the serving data/ path)")
    ap.add_argument("--spool-root", default="data/thinclient_index/spool_backup")
    ap.add_argument("--bmp-shard-docs", type=int, default=DEFAULT_BMP_SHARD_DOCS)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    spool_dir = Path(args.spool_root) / args.section
    slices = sorted(glob.glob(str(spool_dir / "slice_*.jsonl.zst")))
    assert slices, f"no slices at {spool_dir}"
    root = Path(args.index_root)
    root.mkdir(parents=True, exist_ok=True)
    log.info("persona build: section=%s slices=%d root=%s bsize=%d shard_docs=%d quant=%d",
             args.section, len(slices), root, BMP_BLOCK_SIZE, args.bmp_shard_docs, QUANT_SCALE)

    meta = open_meta_db(root)
    b = SectionBuilder(root, args.section, hot=False, meta_db=meta,
                       bmp_shard_docs=args.bmp_shard_docs)

    for i, sl in enumerate(slices):
        b.begin_slice()
        t_slice = time.perf_counter()
        n = 0
        for doc in iter_slice(Path(sl)):
            b.add(doc)
            n += 1
            if n % 250_000 == 0:
                log.info("  slice %d/%d: %s docs (%.0f docs/s)", i + 1, len(slices), n,
                         n / max(1e-6, time.perf_counter() - t_slice))
        st = b.slice_checkpoint()
        log.info("slice %d/%d done: %s docs, next_shard=%d (%.0fs)",
                 i + 1, len(slices), n, st["next_shard"], time.perf_counter() - t_slice)

    info = b.finish()
    info["section"] = args.section
    info["index_root"] = str(root)
    info["bsize"] = BMP_BLOCK_SIZE
    info["quant_scale"] = QUANT_SCALE
    info["built_utc"] = "2026-06-26"
    out = root / f"persona_{args.section}_build.json"
    json.dump(info, open(out, "w"), indent=2)
    print("\nPERSONA_BUILD_OK")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
