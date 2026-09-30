"""O19 (docs/delta_ingest/02_DESIGN.md §3.1): tantivy's query parser rejects an
upper-case operator word such as ``IN`` in the BM25F leg's query text. The leg
now lower-cases the sanitised text; with the default (lower-casing) tokenizer
this changes no hit."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lib.thinclient.retriever import bm25f_query_text  # noqa: E402


def _tiny_index():
    import tantivy
    sb = tantivy.SchemaBuilder()
    sb.add_text_field("title", stored=False, index_option="freq")
    sb.add_text_field("abstract", stored=False, index_option="freq")
    sb.add_text_field("id", stored=True)
    schema = sb.build()
    idx = tantivy.Index(schema)
    w = idx.writer()
    docs = [("1", "Advances in machine learning", "deep models"),
            ("2", "Sleep and memory", "a study in mice"),
            ("3", "Machine translation", "advances and limits")]
    for i, t, a in docs:
        w.add_document(tantivy.Document(id=i, title=t, abstract=a))
    w.commit()
    idx.reload()
    return idx


def _hits(idx, text):
    q = idx.parse_query(text, ["title", "abstract"])
    return sorted(idx.searcher().search(q, 10).hits, key=lambda h: (-h[0], str(h[1])))


def test_upper_case_operator_word_parses():
    idx = _tiny_index()
    with pytest.raises(ValueError):
        idx.parse_query("advances IN machine learning", ["title"])
    idx.parse_query(bm25f_query_text("advances IN machine learning"), ["title"])


def test_sanitiser_unchanged_apart_from_case():
    raw = "Deep-Learning IN Medicine: a (2019) meta-analysis"
    old = "".join(c if c.isalnum() or c.isspace() else " " for c in raw)
    assert bm25f_query_text(raw) == old.lower()


def test_hits_identical_to_mixed_case_query():
    idx = _tiny_index()
    for raw in ["Advances in Machine Learning", "SLEEP and MEMORY in mice",
                "machine translation LIMITS"]:
        old = "".join(c if c.isalnum() or c.isspace() else " " for c in raw)
        assert _hits(idx, bm25f_query_text(raw)) == _hits(idx, old)
