"""Per-section artifact builder: tantivy (BM25F) + sidecars.

One pass over a section's doc stream produces:
  sections/<name>/tantivy/        lexical index (title/abstract indexed-only,
                                  freq index option = the validated positions-off
                                  lossless lever; year/type/is_oa fast fields)
  sections/<name>/abstracts.sqlite  hot sections only (zstd-dict sidecar)
  rows into the global meta.sqlite  (id -> title/doi/year/type/is_oa/section)

The SPLADE leg is not built here: SEISMIC shards are built by spike/delta_ingest.
The BMP shard emission (splade_NNN.bmp) was removed 2026-10-11; the owner
keeps that code. Progress files written before then may
carry a `next_shard` key; it is ignored.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger("sfu_library_mcp")

TANTIVY_WRITER_HEAP = 512_000_000
META_WAL_TRUNCATE_DOCS = int(os.environ.get("SFU_META_WAL_TRUNCATE_DOCS", "250000"))


META_SCHEMA = (
    "PRAGMA journal_mode=WAL; PRAGMA synchronous=OFF;"
    "CREATE TABLE IF NOT EXISTS docs ("
    "  id INTEGER PRIMARY KEY, title TEXT, doi TEXT, year INTEGER,"
    "  type TEXT, is_oa INTEGER, section TEXT);"
    "CREATE TABLE IF NOT EXISTS docs_other ("
    "  id TEXT PRIMARY KEY, title TEXT, doi TEXT, year INTEGER,"
    "  type TEXT, is_oa INTEGER, section TEXT);"
)


def encode_meta_id(doc_id: str) -> int | None:
    """'W2031234567' -> 2031234567, or None when the id wouldn't round-trip
    (no W prefix, non-digits, leading zero) and must stay TEXT."""
    if len(doc_id) > 1 and doc_id[0] == "W":
        digits = doc_id[1:]
        if digits.isdigit() and digits[0] != "0":
            return int(digits)
    return None


def open_meta_db(index_root: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(Path(index_root) / "meta.sqlite"))
    db.executescript(META_SCHEMA)
    return db


class SectionBuilder:
    """Streaming builder for one section. Call add(doc) repeatedly, then finish()."""

    def __init__(self, index_root: Path, section: str, hot: bool,
                 meta_db: sqlite3.Connection,
                 resume_state: dict | None = None):
        import tantivy

        from lib.thinclient.abstracts import AbstractStoreWriter

        self.section = section
        self.hot = hot
        self.dir = Path(index_root) / "sections" / section
        self.dir.mkdir(parents=True, exist_ok=True)
        self._meta = meta_db
        self._meta_batch: list[tuple] = []
        self._meta_batch_other: list[tuple] = []

        tantivy_dir = self.dir / "tantivy"
        tantivy_dir.mkdir(exist_ok=True)
        schema = (tantivy.SchemaBuilder()
                  .add_text_field("id", stored=True, tokenizer_name="raw")
                  .add_text_field("title", stored=False, index_option="freq")
                  .add_text_field("abstract", stored=False, index_option="freq")
                  .add_integer_field("year", stored=False, indexed=True, fast=True)
                  .add_text_field("doctype", stored=False, tokenizer_name="raw")
                  .add_boolean_field("is_oa", stored=False, indexed=True)
                  .build())
        self._tantivy = tantivy.Index(schema, path=str(tantivy_dir))
        self._writer = self._tantivy.writer(heap_size=TANTIVY_WRITER_HEAP)
        self._tantivy_mod = tantivy

        self._abstracts = (AbstractStoreWriter(self.dir / "abstracts.sqlite")
                           if hot else None)
        self.count = (resume_state or {}).get("count", 0)
        self._last_wal_truncate = self.count
        self._probe_tantivy = False
        self._skip_tantivy_slice = False

    def begin_slice(self, probe_tantivy: bool = False) -> None:
        """Arm the duplicate-commit probe for the first re-fed slice on resume."""
        self._probe_tantivy = probe_tantivy
        self._skip_tantivy_slice = False

    def _tantivy_has(self, doc_id: str) -> bool:
        self._tantivy.reload()
        q = self._tantivy.parse_query(f'id:"{doc_id}"', ["id"])
        return bool(self._tantivy.searcher().search(q, 1).hits)

    def add(self, doc: dict) -> None:
        """doc keys: id (openalex W-id), title, abstract, publication_year,
        type, is_oa, doi. Other keys are ignored."""
        doc_id = doc["id"]
        title = doc.get("title") or ""
        abstract = doc.get("abstract") or ""
        year = int(doc.get("publication_year") or 0)
        dtype = doc.get("type") or ""
        is_oa = bool(doc.get("is_oa"))

        if self._probe_tantivy:
            self._probe_tantivy = False
            self._skip_tantivy_slice = self._tantivy_has(doc_id)
            if self._skip_tantivy_slice:
                logger.info("section %s: slice already committed to tantivy "
                            "(crash hit the checkpoint window) — skipping "
                            "tantivy re-adds for this slice", self.section)
        if not self._skip_tantivy_slice:
            self._writer.add_document(self._tantivy_mod.Document(
                id=doc_id, title=title, abstract=abstract,
                year=year, doctype=dtype, is_oa=is_oa,
            ))

        if self._abstracts is not None:
            self._abstracts.add(doc_id, abstract)

        nid = encode_meta_id(doc_id)
        row = (nid if nid is not None else doc_id, title, doc.get("doi") or "",
               year, dtype, int(is_oa), self.section)
        (self._meta_batch if nid is not None
         else self._meta_batch_other).append(row)
        if len(self._meta_batch) + len(self._meta_batch_other) >= 5_000:
            self._flush_meta()
        self.count += 1
        if self.count - self._last_wal_truncate >= META_WAL_TRUNCATE_DOCS:
            self._flush_meta()
            self._meta.commit()
            self._meta.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._last_wal_truncate = self.count

    def _flush_meta(self) -> None:
        self._meta.executemany(
            "INSERT OR REPLACE INTO docs VALUES (?,?,?,?,?,?,?)", self._meta_batch)
        self._meta_batch.clear()
        if self._meta_batch_other:
            self._meta.executemany(
                "INSERT OR REPLACE INTO docs_other VALUES (?,?,?,?,?,?,?)",
                self._meta_batch_other)
            self._meta_batch_other.clear()

    def slice_checkpoint(self) -> dict:
        """Make everything added so far durable at a spool-slice boundary and
        return the state the worker persists in its progress file.

        The tantivy commit goes LAST: everything before it is idempotent on
        re-feed, so the only crash window needing the resume probe is the
        few ms between this commit and the worker's progress write — keep
        the slow steps (abstracts zstd-19 flush) out of it."""
        if self._abstracts is not None:
            self._abstracts.checkpoint()
        self._flush_meta()
        self._meta.commit()
        self._meta.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self._writer.commit()
        self._skip_tantivy_slice = False
        return {"count": self.count}

    def finish(self) -> dict:
        self._flush_meta()
        self._meta.commit()
        self._writer.commit()
        self._writer.wait_merging_threads()
        n_abs = self._abstracts.finish() if self._abstracts else 0
        size = sum(f.stat().st_size for f in self.dir.rglob("*") if f.is_file())
        info = {
            "docs": self.count,
            "abstracts_stored": n_abs,
            "live_bytes": size,
            "hot": self.hot,
        }
        logger.info("section %s built: %s", self.section, info)
        return info


def build_dense_leg(index_root: Path, vectors_npy: Path, ids_json: Path) -> dict:
    """Build the usearch dense leg from precomputed fp32 vectors.

    Validated recipe (docs/archive/COMPRESSION_EVAL_RESULTS.md): binary sign codes in
    a usearch b1 Hamming index (32x), int8 rescore matrix memmapped from disk,
    4-20x over-fetch + exact rescore => R@10 0.975-0.996 vs exact.
    """
    import json

    import numpy as np
    from usearch.index import Index

    dense_dir = Path(index_root) / "dense"
    dense_dir.mkdir(parents=True, exist_ok=True)

    X = np.load(vectors_npy, mmap_mode="r").astype(np.float32)
    ids = json.loads(Path(ids_json).read_text())
    assert len(ids) == len(X), f"ids ({len(ids)}) != vectors ({len(X)})"

    bits = np.packbits((X > 0).astype(np.uint8), axis=1)
    index = Index(ndim=X.shape[1], dtype="b1", metric="hamming")
    index.add(np.arange(len(X), dtype=np.uint64), bits)
    index.save(str(dense_dir / "b1.usearch"))

    np.save(dense_dir / "rescore_int8.npy",
            np.clip(np.round(X * 127.0), -127, 127).astype(np.int8))
    (dense_dir / "ids.json").write_text(json.dumps(ids))
    info = {"vectors": len(X), "dim": int(X.shape[1]),
            "b1_bytes": (dense_dir / "b1.usearch").stat().st_size,
            "rescore_bytes": (dense_dir / "rescore_int8.npy").stat().st_size}
    logger.info("dense leg built: %s", info)
    return info
