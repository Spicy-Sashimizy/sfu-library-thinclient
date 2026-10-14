"""L0 warm buffer — the only MUTABLE tier (Lucene/Vespa "memory index" role).

Fed from the ledger's generation-0 records:
  - a small tantivy index (`<delta_root>/buffer/tantivy`) that the ingest
    process writes with delete-by-term + add + commit. tantivy is mutable
    off-the-shelf; the serving process reopens it on commit (meta.json watch).
  - the exact sparse half is scored serving-side: `lib/thinclient/
    delta_layer._ExactSparse` rebuilds it in RAM from the same records
    (brute-force dot product over an inverted dict). The ingest-side twin
    `ExactSparseBuffer` had no caller and was removed 2026-10-11.

Freezing (generation build) moves records to gen N, after which the buffer
copies are deleted here. Buffer size is bounded by `flush_docs` in the CLI.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .records import DocRecord

log = logging.getLogger("delta_ingest.buffer")

BUFFER_SECTION = "delta_buffer"


def _schema():
    import tantivy
    return (tantivy.SchemaBuilder()
            .add_text_field("id", stored=True, tokenizer_name="raw")
            .add_text_field("title", stored=False, index_option="freq")
            .add_text_field("abstract", stored=False, index_option="freq")
            .add_integer_field("year", stored=False, indexed=True, fast=True)
            .add_text_field("doctype", stored=False, tokenizer_name="raw")
            .add_boolean_field("is_oa", stored=False, indexed=True)
            .build())


class BufferWriter:
    """Single writer (tantivy lockfile enforces it). Same schema as
    `SectionBuilder` so the retriever's BM25F leg treats it as a section."""

    def __init__(self, delta_root: Path):
        import tantivy
        self.dir = Path(delta_root) / "buffer" / BUFFER_SECTION / "tantivy"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._tantivy = tantivy
        self.index = tantivy.Index(_schema(), path=str(self.dir))
        self.writer = self.index.writer(heap_size=64_000_000)

    def upsert(self, records: list[DocRecord]) -> None:
        for r in records:
            self.writer.delete_documents_by_term("id", r.id)
            d = r.builder_doc()
            self.writer.add_document(self._tantivy.Document(
                id=d["id"], title=d["title"], abstract=d["abstract"],
                year=int(d["publication_year"] or 0), doctype=d["type"], is_oa=d["is_oa"]))

    def delete(self, ids: list[str]) -> None:
        for wid in ids:
            self.writer.delete_documents_by_term("id", wid)

    def ids(self) -> set[str]:
        """Every doc id in the committed buffer index (bounded by the buffer
        size: gen 0 plus the last frozen generation)."""
        self.index.reload()
        s = self.index.searcher()
        if not s.num_docs:
            return set()
        hits = s.search(self._tantivy.Query.all_query(), s.num_docs).hits
        return {s.doc(a)["id"][0] for _, a in hits}

    def retain_only(self, keep: set[str]) -> int:
        """O2 BM25F residual: delete every buffered doc not in `keep` and
        commit. Called after a freeze with keep = buffer view (gen 0 +
        building) + the just-frozen generation, so the frozen docs stay
        searchable until serving reloads, and older frozen generations are
        garbage-collected (serving drops buffer hits outside its buffer view,
        `DeltaLayer.keep_hit`)."""
        gone = sorted(self.ids() - keep)
        self.delete(gone)
        self.commit()
        return len(gone)

    def commit(self) -> int:
        stamp = self.writer.commit()
        self.writer.wait_merging_threads()
        self.writer = self.index.writer(heap_size=64_000_000)
        return stamp

    def close(self) -> None:
        try:
            self.writer.commit()
            self.writer.wait_merging_threads()
        except Exception:  # noqa: BLE001
            pass
