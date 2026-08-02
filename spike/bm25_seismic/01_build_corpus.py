#!/usr/bin/env python3
"""BM25-through-SEISMIC spike — step 1: extract a self-contained text corpus.

The spike asks whether SEISMIC (a generic sparse-vector MIPS index, currently
fed SPLADE vectors) can also serve BM25-weighted sparse vectors without losing
search quality. To answer that we need a corpus where we can compute BOTH legs
ourselves: exact BM25F (brute force + tantivy) and BM25-through-SEISMIC.

Source: `sections/social_sciences__recent` — the only section whose abstract
sidecar is unpacked on this host, and the section that carries most of the SFU
eval queries' subject areas (Indigenous Studies, Labour Studies, Canadian
Studies). Titles come from `meta.sqlite` (v2 INTEGER-PK W-ids + `docs_other`
TEXT overflow); abstracts from the v3 script-bucketed zstd block store.

Sampling is BLOCK-SEQUENTIAL (first `--blocks` blocks of the v3 store), not
random: the store is written in spool/build order, and a sequential read
decompresses each 32 KB block exactly once instead of paying a random-access
fault per doc. Docs with no title or no abstract are dropped (BM25F needs both
fields); the counts are reported so the drop rate is visible, never silent.

READ-ONLY on everything under `data/` (opened with `mode=ro`). Output goes to
the spike dir, not the serving index.

    .venv/bin/python3 spike/bm25_seismic/01_build_corpus.py \
        --blocks 9000 --out spike/bm25_seismic/work/corpus.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import time
from pathlib import Path

import zstandard

ROOT = Path(__file__).resolve().parents[2]
SECTION_DIR = ROOT / "data" / "thinclient_index" / "sections" / "social_sciences__recent"
ABS_DB = SECTION_DIR / "abstracts.sqlite"
META_DB = ROOT / "data" / "thinclient_index" / "meta.sqlite"

log = logging.getLogger("bm25seismic.corpus")


def open_abstract_store(path: Path):
    """Return (connection, {dict_id: ZstdDecompressor}) for a v3 block store.

    Mirrors `lib.thinclient.abstracts.AbstractStore.__init__` rather than
    importing it, because we read the store sequentially by block instead of
    through the point-lookup `fetch()` API.
    """
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    tables = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "blocks" in tables, f"{path} is not a v3 block store (tables={tables})"

    def zdict(key: str):
        row = db.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
        return zstandard.ZstdCompressionDict(row[0]) if row else None

    names = json.loads(db.execute(
        "SELECT v FROM meta WHERE k='dicts'").fetchone()[0])
    latin = zdict("zdict_latin")
    plain = zstandard.ZstdDecompressor()
    dctxs = {}
    for i, name in enumerate(names):
        zd = zdict(f"zdict_{name}") or latin
        dctxs[i] = zstandard.ZstdDecompressor(dict_data=zd) if zd else plain
    log.info("abstract store v3: %d dicts (%s)", len(dctxs), ",".join(names))
    return db, dctxs


def fetch_titles(meta: sqlite3.Connection, oaids: list[str]) -> dict[str, str]:
    """meta.sqlite v2: numeric W-ids live in `docs` (INTEGER PK), everything
    else in the `docs_other` TEXT overflow table. Query both."""
    out: dict[str, str] = {}
    numeric, other = [], []
    for oid in oaids:
        if oid.startswith("W") and oid[1:].isdigit():
            numeric.append(int(oid[1:]))
        else:
            other.append(oid)
    for tbl, keys, fmt in (("docs", numeric, lambda k: f"W{k}"),
                           ("docs_other", other, lambda k: k)):
        for i in range(0, len(keys), 900):
            chunk = keys[i:i + 900]
            marks = ",".join("?" * len(chunk))
            for pk, title in meta.execute(
                    f"SELECT id, title FROM {tbl} WHERE id IN ({marks})", chunk):
                if title:
                    out[fmt(pk)] = title
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--blocks", type=int, default=9000,
                    help="how many 32 KB abstract blocks to read (~30 docs each)")
    ap.add_argument("--max-docs", type=int, default=0, help="0 = no cap")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).parent / "work" / "corpus.jsonl")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s")
    args.out.parent.mkdir(parents=True, exist_ok=True)

    db, dctxs = open_abstract_store(ABS_DB)
    meta = sqlite3.connect(f"file:{META_DB}?mode=ro", uri=True)

    t0 = time.perf_counter()
    n_docs = n_no_title = n_no_abs = 0
    title_chars = abs_chars = 0
    with open(args.out, "w") as fout:
        # `docs` is indexed on `id` only — there is NO index on `b`, so a
        # per-window `WHERE b BETWEEN ?` costs a full scan of a ~45M-row table
        # each time (measured: ~7k docs/min). Take ONE scan, bucket by block.
        log.info("scanning docs table for blocks < %d (single pass)…", args.blocks)
        by_block: dict[int, list] = {}
        scanned = 0
        for oaid, b, off, n in db.execute("SELECT id, b, off, n FROM docs"):
            scanned += 1
            if b < args.blocks:
                by_block.setdefault(b, []).append((oaid, off, n))
            if scanned % 5_000_000 == 0:
                log.info("  scanned %dM rows, kept %d blocks",
                         scanned // 1_000_000, len(by_block))
        log.info("scan done: %d rows, %d blocks kept", scanned, len(by_block))

        for b0 in range(0, args.blocks, 200):
            b1 = min(b0 + 200, args.blocks)
            # Decompress each block once, then join its doc slices against
            # meta.sqlite in a single batched lookup.
            payloads: dict[int, bytes] = {}
            for b, d, z in db.execute(
                    "SELECT b, d, z FROM blocks WHERE b >= ? AND b < ?", (b0, b1)):
                payloads[b] = dctxs.get(d, dctxs[0]).decompress(z)
            rows = [(oaid, b, off, n) for b in range(b0, b1)
                    for (oaid, off, n) in by_block.get(b, ())]
            titles = fetch_titles(meta, [r[0] for r in rows])
            for oaid, b, off, n in rows:
                payload = payloads.get(b)
                if payload is None:
                    continue
                abstract = payload[off:off + n].decode("utf-8", "replace").strip()
                title = titles.get(oaid, "").strip()
                if not title:
                    n_no_title += 1
                    continue
                if not abstract:
                    n_no_abs += 1
                    continue
                fout.write(json.dumps({"id": oaid, "title": title,
                                       "abstract": abstract}) + "\n")
                n_docs += 1
                title_chars += len(title)
                abs_chars += len(abstract)
                if args.max_docs and n_docs >= args.max_docs:
                    break
            if args.max_docs and n_docs >= args.max_docs:
                break
            if b1 % 2000 == 0:
                log.info("  blocks %d/%d  docs=%d", b1, args.blocks, n_docs)

    dt = time.perf_counter() - t0
    manifest = {
        "corpus": str(args.out),
        "source_section": "social_sciences__recent",
        "blocks_read": args.blocks,
        "docs": n_docs,
        "dropped_no_title": n_no_title,
        "dropped_no_abstract": n_no_abs,
        "mean_title_chars": round(title_chars / n_docs, 1) if n_docs else 0,
        "mean_abstract_chars": round(abs_chars / n_docs, 1) if n_docs else 0,
        "on_disk_mb": round(args.out.stat().st_size / 1e6, 2),
        "build_seconds": round(dt, 1),
        "sampling": "block-sequential from block 0 (build order, not random)",
    }
    (args.out.with_suffix(".manifest.json")).write_text(json.dumps(manifest, indent=2))
    log.info("wrote %s", args.out)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
