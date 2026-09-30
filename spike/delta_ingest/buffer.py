"""L0 warm buffer — the only MUTABLE tier (Lucene/Vespa "memory index" role).

Two halves, both fed from the ledger's generation-0 records:
  - a small tantivy index (`<delta_root>/buffer/tantivy`) that the ingest
    process writes with delete-by-term + add + commit. tantivy is mutable
    off-the-shelf; the serving process reopens it on commit (meta.json watch).
  - an exact sparse scorer (`ExactSparseBuffer`) rebuilt in RAM from the same
    records — brute-force dot product over an inverted dict. Exact, so no
    SEISMIC build params matter at this size; cost is linear in postings hit.

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


class ExactSparseBuffer:
    """Brute-force sparse scorer over the buffer's SPLADE vectors.
    `search(qvec, k)` returns [(id, dot)] in the same score space as SEISMIC's
    f16 scores (exact vs SEISMIC's block-approximate), so the retriever can
    merge them by score before RRF."""

    def __init__(self):
        self.ids: list[str] = []
        self.postings: dict[str, list[tuple[int, float]]] = {}
        self._pos: dict[str, int] = {}
        self.deleted: set[int] = set()

    def __len__(self) -> int:
        return len(self.ids) - len(self.deleted)

    def add(self, doc_id: str, vec: dict[str, float]) -> None:
        if doc_id in self._pos:
            self.remove(doc_id)
        i = len(self.ids)
        self.ids.append(doc_id)
        self._pos[doc_id] = i
        for t, w in vec.items():
            if w > 0:
                self.postings.setdefault(t, []).append((i, float(w)))

    def remove(self, doc_id: str) -> None:
        i = self._pos.pop(doc_id, None)
        if i is not None:
            self.deleted.add(i)

    def search(self, qvec: dict[str, float], k: int) -> list[tuple[str, float]]:
        if not self.ids:
            return []
        acc: dict[int, float] = {}
        for t, qw in qvec.items():
            plist = self.postings.get(t)
            if not plist:
                continue
            for i, w in plist:
                acc[i] = acc.get(i, 0.0) + qw * w
        best = sorted(((s, i) for i, s in acc.items() if i not in self.deleted), reverse=True)[:k]
        return [(self.ids[i], s) for s, i in best]
