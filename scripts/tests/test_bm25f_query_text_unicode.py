"""O19 follow-up 2026-10-01 (docs/delta_ingest/02_DESIGN.md §3.1;
spike/delta_ingest/FIXES_20261001_WAVE3.md): real titles that still made
tantivy's query parser raise after the 2026-09-30 lower-casing fix, and the
case-variant repeat rule that made lower-casing change hits.

- Unicode whitespace (NBSP, U+2005, ...) passes `str.isspace()` but is not a
  separator in tantivy's query grammar -> syntax error (384 of 50,000 sample
  titles).
- `'İ'.lower()` is 'i' + U+0307 (combining dot), which the grammar rejects;
  keeping 'İ' lets the field tokenizer lower-case it exactly as at index
  time (55 of 50,000).
- A query whose every token exceeds tantivy's 40-byte token limit (long CJK
  runs) raises "Only excluding terms given"; the BM25F leg must return no hits
  instead of raising out of search (5 of 50,000).
- Case-variant repeats ("How ... how") were two identical term clauses before
  lower-casing (double weight); now one, like a same-case repeat.
Synthetic tmp indexes only."""
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from lib.thinclient.retriever import bm25f_query_text  # noqa: E402


def _schema_index(path=None):
    import tantivy
    sb = tantivy.SchemaBuilder()
    sb.add_text_field("id", stored=True, tokenizer_name="raw")
    sb.add_text_field("title", stored=False, index_option="freq")
    sb.add_text_field("abstract", stored=False, index_option="freq")
    return tantivy.Index(sb.build(), path=path)


def _parses(idx, text):
    idx.parse_query(text, ["title"])
    idx.parse_query(text, ["abstract"])


@pytest.mark.parametrize("raw", [
    "Seeing a World Unmade, and Making a World (Out) of Remains: W.S. Merwin",
    "PWE-083 Prevalence of opioid therapy in patients",
    "unraveling the U-shaped relationship between　things",
])
def test_unicode_whitespace_parses(raw):
    _parses(_schema_index(), bm25f_query_text(raw))


def test_dotted_capital_i_parses_and_matches_index_token():
    import tantivy
    idx = _schema_index()
    w = idx.writer(15_000_000)
    w.add_document(tantivy.Document(id="t1", title="BİR İSTANBUL ÇEVİRİ ÇALIŞMASI"))
    w.add_document(tantivy.Document(id="t2", title="another paper"))
    w.commit()
    idx.reload()
    text = bm25f_query_text("Bir İstanbul çevirisi")
    _parses(idx, text)
    hits = idx.searcher().search(idx.parse_query(text, ["title"]), 5).hits
    assert [idx.searcher().doc(a)["id"][0] for _, a in hits] == ["t1"]


def test_case_variant_repeat_is_one_clause():
    idx = _schema_index()
    n = lambda t: len(re.findall("TermQuery", repr(idx.parse_query(t, ["title"]))))  # noqa: E731
    assert n(bm25f_query_text("How do teams know how")) == n("how do teams know how") == 4


def test_ascii_output_equals_plain_lower():
    raw = "Deep-Learning IN Medicine: a (2019) meta-analysis AND Other THINGS"
    old = "".join(c if c.isalnum() or c.isspace() else " " for c in raw)
    assert bm25f_query_text(raw) == old.lower()


def test_all_tokens_too_long_returns_no_hits(tmp_path, monkeypatch):
    from lib.thinclient.builder import SectionBuilder, open_meta_db
    from lib.thinclient.retriever import ThinClientRetriever
    root = tmp_path / "index"
    root.mkdir()
    meta = open_meta_db(root)
    b = SectionBuilder(root, "social_sciences__recent", hot=True, meta_db=meta)
    for i in range(1, 40):
        b.add({"id": f"W{i}", "title": f"paper {i}", "abstract": "text", "publication_year": 2020,
               "type": "article", "is_oa": False, "doi": ""})
    b.finish()
    meta.commit()
    meta.close()
    (root / "manifest.json").write_text(json.dumps({"sections": {}, "persona": "all_hot"}))
    monkeypatch.delenv("SFU_DELTA_ROOT", raising=False)
    monkeypatch.setenv("SFU_SPLADE_BACKEND", "seismic")
    tc = ThinClientRetriever(index_root=str(root), remote_abstracts=False)
    tc._load()
    q = "道徳教育のための異文化間対話 : 宗教観に関する自己意識の重要性"
    assert tc._bm25f_leg(q, 10, None) == []
    assert [d for d, _ in tc._bm25f_leg("paper 7", 10, None)][:1] == ["W7"]
