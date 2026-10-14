"""L4 premise test (docs/delta_ingest/09_M4_FOLLOWUP_PREREGISTRATION.md §2 L4).

A tantivy-py `Query` parsed by one `Index` must be valid on another `Index`
with an identical schema: searching index B with a query parsed by index A
returns exactly the hits (ids, order, float scores) of the query parsed by B.
Both indexes are real `SectionBuilder` sections (the served schema) built in a
tmp tree with different documents, so their term statistics differ. Then the
`_bm25f_leg` gate `SFU_BM25F_PARSE_ONCE=1` must return the same list as the
gate unset, with and without a year-range filter.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

tantivy = pytest.importorskip("tantivy")

from lib.thinclient.builder import SectionBuilder, open_meta_db  # noqa: E402
from lib.thinclient.retriever import ThinClientRetriever, bm25f_query_text  # noqa: E402

WORDS = ("quantum policy election river protein graph neural market climate "
         "soil vaccine theorem galaxy language ethics trade").split()

QUERIES = ["quantum policy", "neural graph language models", "climate soil river",
           "vaccine protein trade ethics", "galaxy theorem", "market IN election",
           "nonexistentterm", "policy policy policy", "Climate-Change & Soil (2020)"]


def _doc(i: int, salt: int) -> dict:
    w = [WORDS[(i * 7 + salt + k * 3) % len(WORDS)] for k in range(4 + i % 5)]
    return {"id": f"W{salt}{i:05d}", "title": " ".join(w[:3]),
            "abstract": " ".join(w + w[: i % 3]), "publication_year": 2000 + (i + salt) % 27,
            "type": "article", "is_oa": (i + salt) % 2 == 0, "doi": f"10.1/{salt}.{i}"}


def _section(root: Path, name: str, n: int, salt: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    meta = open_meta_db(root)
    b =SectionBuilder(root, name, hot=True, meta_db=meta)
    for i in range(n):
        b.add(_doc(i, salt))
    b.finish()
    meta.commit()
    meta.close()
    return root / "sections" / name / "tantivy"


def _search(idx, qt, qa, top_k=50, year=None):
    q = tantivy.Query.boolean_query([
        (tantivy.Occur.Should, tantivy.Query.boost_query(qt, 3.0)),
        (tantivy.Occur.Should, qa)])
    if year is not None:
        q = tantivy.Query.boolean_query([
            (tantivy.Occur.Must, q),
            (tantivy.Occur.Must, tantivy.Query.range_query(
                idx.schema, "year", tantivy.FieldType.Integer, year[0], year[1]))])
    s = idx.searcher()
    return [(s.doc(a)["id"][0], float(sc)) for sc, a in s.search(q, top_k).hits]


@pytest.fixture(scope="module")
def two_indexes(tmp_path_factory):
    root = tmp_path_factory.mktemp("parse_once")
    a = tantivy.Index.open(str(_section(root / "a", "physics__recent", 400, 1)))
    b = tantivy.Index.open(str(_section(root / "b", "biology__archive", 250, 5)))
    a.reload()
    b.reload()
    return a, b


def test_schemas_identical(two_indexes):
    a, b = two_indexes
    assert a.schema == b.schema


@pytest.mark.parametrize("year", [None, (2015, 2026)])
@pytest.mark.parametrize("raw", QUERIES)
def test_query_parsed_on_other_index_is_valid(two_indexes, raw, year):
    a, b = two_indexes
    text = bm25f_query_text(raw)
    own = _search(b, b.parse_query(text, ["title"]), b.parse_query(text, ["abstract"]), year=year)
    foreign = _search(b, a.parse_query(text, ["title"]), a.parse_query(text, ["abstract"]), year=year)
    assert foreign == own
    if raw != "nonexistentterm":
        assert own or year is not None


def _retriever(root: Path, monkeypatch, gate: str | None) -> ThinClientRetriever:
    if gate is None:
        monkeypatch.delenv("SFU_BM25F_PARSE_ONCE", raising=False)
    else:
        monkeypatch.setenv("SFU_BM25F_PARSE_ONCE", gate)
    monkeypatch.delenv("SFU_DELTA_ROOT", raising=False)
    r = ThinClientRetriever(root)
    r._load()
    return r


def test_bm25f_leg_gate_parity(tmp_path, monkeypatch):
    for k, (name, salt) in enumerate((("physics__recent", 1), ("physics__archive", 2),
                                      ("biology__recent", 3), ("biology__archive", 4))):
        _section(tmp_path, name, 150 + 40 * k, salt)
    off = _retriever(tmp_path, monkeypatch, None)
    on = _retriever(tmp_path, monkeypatch, "1")
    assert off._bm25f_parse_once is False and on._bm25f_parse_once is True
    for raw in QUERIES:
        for f in (None, {"year_range": (2015, 2026)}):
            assert on._bm25f_leg(raw, 100, f) == off._bm25f_leg(raw, 100, f)


def test_gate_only_literal_one(tmp_path, monkeypatch):
    _section(tmp_path, "physics__recent", 50, 1)
    for v in ("", "0", "true", "yes"):
        assert _retriever(tmp_path, monkeypatch, v)._bm25f_parse_once is False
