"""Unit tests for the thin-client stack: builder -> retriever -> packer.

Self-contained (synthetic 3000-doc corpus, no network, no models): the BM25F
leg and filters run the real tantivy path.

Run:  .venv/bin/python3 -m pytest source/tests/test_thinclient.py -q
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.thinclient.abstracts import AbstractStore, AbstractStoreWriter  # noqa: E402
from lib.thinclient.builder import (SectionBuilder, encode_meta_id,  # noqa: E402
                                    open_meta_db)
from lib.thinclient.packer import pack_section, unpack_section  # noqa: E402
from lib.thinclient.retriever import ThinClientRetriever, _normalize_filters  # noqa: E402
from lib.thinclient.sections import classify_doc  # noqa: E402

TOPICS = {
    "med_bio": ("cancer therapy clinical patient gene", "tumor immunotherapy"),
    "cs_math": ("algorithm optimization graph network", "machine learning model"),
}


def make_docs(n: int = 3000) -> list[dict]:
    docs = []
    for i in range(n):
        sec, (words, extra) = list(TOPICS.items())[i % 2]
        docs.append({
            "id": f"W{i:06d}",
            "title": f"{extra} study {i}",
            "abstract": f"A paper about {words}. Sample {i} with details on {extra}.",
            "publication_year": 2015 + (i % 10),
            "type": "article" if i % 3 else "review",
            "is_oa": bool((i // 2) % 2),
            "doi": f"10.1/{i}",
        })
    return docs


@pytest.fixture(scope="module")
def index_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("tc_index")
    meta = open_meta_db(root)
    builders = {}
    counts = {}
    for d in make_docs():
        sec = classify_doc(d["title"], d["abstract"])
        if sec not in builders:
            builders[sec] = SectionBuilder(root, sec, hot=True, meta_db=meta)
        builders[sec].add(d)
        counts[sec] = counts.get(sec, 0) + 1
    infos = {s: b.finish() for s, b in builders.items()}
    meta.close()
    manifest = {"sections": {s: {"state": "live", "docs": i["docs"]}
                             for s, i in infos.items()}}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root


def test_sections_disjoint_and_complete(index_root):
    """meta.sqlite has been a two-table store since 9a6d1952 (meta v2): ids that
    round-trip through encode_meta_id go to `docs` (INTEGER PK), the rest to
    `docs_other` (TEXT PK). Completeness is the sum of both."""
    import sqlite3
    db = sqlite3.connect(str(index_root / "meta.sqlite"))
    counts = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("docs", "docs_other")}
    assert sum(counts.values()) == 3000
    expected_numeric = sum(1 for d in make_docs()
                           if encode_meta_id(d["id"]) is not None)
    assert counts["docs"] == expected_numeric
    assert counts["docs_other"] == 3000 - expected_numeric
    per: dict[str, int] = {}
    for table in ("docs", "docs_other"):
        for section, n in db.execute(
                f"SELECT section, COUNT(*) FROM {table} GROUP BY section"):
            per[section] = per.get(section, 0) + n
    assert sum(per.values()) == 3000 and len(per) >= 2


def test_bm25f_search_and_filters(index_root):
    r = ThinClientRetriever(index_root=str(index_root), remote_abstracts=False)
    assert r.is_available()
    hits = r.search("cancer immunotherapy tumor", top_k=10, mode="bm25f")
    assert hits and all(h["title"] for h in hits)
    assert all(set(h) >= {"doi", "openalex_id", "title", "abstract", "score",
                          "publication_year", "year", "date", "type", "is_oa",
                          "source"} for h in hits)
    filtered = r.search("cancer immunotherapy tumor", top_k=10, mode="bm25f",
                        filters={"publication_year": "2020-2024"})
    assert filtered
    assert all(2020 <= h["publication_year"] <= 2024 for h in filtered)
    oa = r.search("cancer therapy", top_k=10, mode="bm25f",
                  filters={"is_oa": True})
    assert oa and all(h["is_oa"] for h in oa)


@pytest.mark.parametrize("backend", ["bmp", "seismc", "opensearch"])
def test_unknown_splade_backend_raises(index_root, monkeypatch, backend):
    """The BMP fall-through was removed 2026-10-11 and the Qdrant leg
    2026-10-12: any SFU_SPLADE_BACKEND other than 'seismic' (the retired
    'bmp', or a typo) raises instead of silently returning an empty SPLADE
    leg, and search() does not swallow it. The builder no longer writes
    splade_*.bmp shards."""
    monkeypatch.setenv("SFU_SPLADE_BACKEND", backend)
    r = ThinClientRetriever(index_root=str(index_root), remote_abstracts=False)
    with pytest.raises(ValueError,
                       match=r"SFU_SPLADE_BACKEND=.*'seismic' is the only supported value"):
        r._splade_leg("cancer therapy", 10, None)
    with pytest.raises(ValueError, match="'seismic' is the only supported value"):
        r.search("cancer therapy", top_k=10, mode="splade")
    assert not list((index_root / "sections").glob("*/splade_*"))
    assert "bmp_shards" not in r.metrics()


def test_qdrant_splade_backend_removed(index_root, monkeypatch):
    """The Qdrant rollback leg was removed 2026-10-12 (owner decision; code on
    branch archive/bmp-qdrant): SFU_SPLADE_BACKEND=qdrant now fails loud at
    the first query with a message naming the removal, and the retriever no
    longer carries a Qdrant client or reads the SFU_SPLADE_QDRANT_* gates."""
    monkeypatch.setenv("SFU_SPLADE_BACKEND", "qdrant")
    r = ThinClientRetriever(index_root=str(index_root), remote_abstracts=False)
    with pytest.raises(ValueError,
                       match=r"'qdrant' was removed 2026-10-12 \(branch archive/bmp-qdrant\)"):
        r._splade_leg("cancer therapy", 10, None)
    with pytest.raises(ValueError, match="'qdrant' was removed 2026-10-12"):
        r.search("cancer therapy", top_k=10, mode="splade")
    assert not hasattr(r, "_qdrant_client")
    assert not hasattr(r, "_splade_leg_qdrant")


def test_abstract_sidecar_roundtrip(index_root):
    """The v1 per-doc `abs` table became the v3 block-addressed `docs` table in
    d978ba38 (clustered 32 KB blocks + per-script zstd dicts)."""
    stores = list((index_root / "sections").glob("*/abstracts.sqlite"))
    assert stores
    store = AbstractStore(stores[0])
    import sqlite3
    db = sqlite3.connect(str(stores[0]))
    some_ids = [row[0] for row in db.execute("SELECT id FROM docs LIMIT 5")]
    out = store.fetch(some_ids)
    assert len(out) == 5 and all(v.startswith("A paper about") for v in out.values())


def test_hydrate_fills_abstracts_locally(index_root):
    r = ThinClientRetriever(index_root=str(index_root), remote_abstracts=False)
    hits = r.search("graph optimization algorithm", top_k=5, mode="bm25f")
    assert hits and all(h["abstract"] for h in hits)


def test_rrf_fusion_shape(index_root):
    r = ThinClientRetriever(index_root=str(index_root), remote_abstracts=False)
    r._load()
    r._splade_leg = lambda q, k, f: [(h["openalex_id"], 1.0) for h in
                                     r.search(q, k, mode="bm25f")][::-1]
    fused = r.search_rrf("machine learning network model", top_k=10)
    assert fused and fused[0]["source"] == "thinclient_rrf"
    assert fused == sorted(fused, key=lambda d: -d["score"])


def test_pack_unpack_parity(index_root):
    r = ThinClientRetriever(index_root=str(index_root), remote_abstracts=False)
    section = r.live_sections()[0]
    before = [(h["openalex_id"], round(h["score"], 6))
              for h in r.search("cancer therapy clinical", top_k=10, mode="bm25f")]

    info = pack_section(index_root, section)
    assert info["ratio"] > 1.0
    assert not (index_root / "sections" / section).exists()

    out = unpack_section(index_root, section)
    assert out["parity_checksum_ok"] is True

    r2 = ThinClientRetriever(index_root=str(index_root), remote_abstracts=False)
    after = [(h["openalex_id"], round(h["score"], 6))
             for h in r2.search("cancer therapy clinical", top_k=10, mode="bm25f")]
    assert before == after


def test_filter_normalization():
    f = _normalize_filters({"publication_year": "2018-2022", "type": "article",
                            "open_access.is_oa": "true"})
    assert f == {"year_range": (2018, 2022), "type": "article", "is_oa": True}
    assert _normalize_filters({"from_publication_date": "2019-05-01"}) == {
        "year_range": (2019, 3000)}
    assert _normalize_filters(None) is None
    assert _normalize_filters({}) is None


class _CountingDenseCache:
    """Stand-in warm cache: records every `enqueue` batch, contributes no rows."""

    def __init__(self):
        self.enqueued: list[list[str]] = []

    def enqueue(self, results):
        self.enqueued.append([d["openalex_id"] for d in results])

    def metadata_rows(self, ids):
        return {}

    def info(self):
        return {"docs": 0}


def _memo_retriever(index_root, remote_calls, meta_calls):
    """Retriever whose abstracts all come from a stubbed OpenAlex fetch and
    whose SPLADE leg is the BM25F leg reversed + shifted, so the two legs
    overlap heavily but not totally."""
    r = ThinClientRetriever(index_root=str(index_root), remote_abstracts=True)
    r._load()
    r._abstract_stores = {}
    r._dense_cache = _CountingDenseCache()

    def fake_remote(ids):
        remote_calls.append(list(ids))
        return {i: f"remote abstract {i}" for i in ids if int(i[1:]) % 5}

    real_meta = r._meta_rows

    def counting_meta(ids):
        meta_calls.append(list(ids))
        return real_meta(ids)

    r._fetch_remote_abstracts = fake_remote
    r._meta_rows = counting_meta
    r._splade_leg = lambda q, k, f: [(d, 1.0) for d, _ in
                                     r._bm25f_leg(q, k + 4, f)][::-1][:k]
    return r


def test_hydrate_memo_parity_with_unmemoised_path(index_root, monkeypatch):
    """Lever #0: search_rrf / search_rrf_detailed output is byte-identical with
    the per-request hydrate memo on vs the old per-leg hydrate path, and the
    warm-cache enqueue still fires once per leg with the same batches."""
    import contextlib
    q = "machine learning network model"
    r_on = _memo_retriever(index_root, [], [])
    on_fused = r_on.search_rrf(q, top_k=10, with_provenance=True)
    on_detail = r_on.search_rrf_detailed(q, top_k=10)
    on_enq = list(r_on._dense_cache.enqueued)

    r_off = _memo_retriever(index_root, [], [])
    monkeypatch.setattr(r_off, "hydrate_scope", contextlib.nullcontext)
    off_fused = r_off.search_rrf(q, top_k=10, with_provenance=True)
    off_detail = r_off.search_rrf_detailed(q, top_k=10)
    off_enq = list(r_off._dense_cache.enqueued)

    assert on_fused and json.dumps(on_fused) == json.dumps(off_fused)
    on_detail.pop("leg_latency_ms")
    off_detail.pop("leg_latency_ms")
    assert json.dumps(on_detail) == json.dumps(off_detail)
    assert on_enq == off_enq and len(on_enq) == 4
    legs = on_detail["legs"]
    assert set(legs["bm25f"]) & set(legs["splade"])
    assert set(legs["bm25f"]) != set(legs["splade"])


def test_hydrate_memo_fetches_shared_ids_once(index_root):
    """An id surfaced by both legs is meta-looked-up and remote-fetched once
    per request — including ids the remote fetch had no abstract for."""
    remote_calls: list[list[str]] = []
    meta_calls: list[list[str]] = []
    r = _memo_retriever(index_root, remote_calls, meta_calls)
    out = r.search_rrf_detailed("machine learning network model", top_k=10)
    legs = out["legs"]
    shared = set(legs["bm25f"]) & set(legs["splade"])
    assert shared
    remote_ids = [i for call in remote_calls for i in call]
    assert sorted(remote_ids) == sorted(set(legs["bm25f"]) | set(legs["splade"]))
    hydrate_meta = meta_calls
    assert len(hydrate_meta) == 2
    assert not set(hydrate_meta[1]) & set(hydrate_meta[0])
    misses = [i for i in shared if not int(i[1:]) % 5]
    for i in misses:
        assert remote_ids.count(i) == 1


def test_hydrate_memo_does_not_leak_across_requests(index_root):
    """The memo lives only inside one request: a second identical request
    re-fetches every id (no stale abstracts), plain `search()` outside a scope
    is unmemoised, and one retriever's scope never serves another retriever."""
    from lib.thinclient.retriever import _HYDRATE_MEMO
    remote_calls: list[list[str]] = []
    r = _memo_retriever(index_root, remote_calls, [])
    q = "machine learning network model"
    r.search_rrf(q, top_k=10)
    first = sorted(i for call in remote_calls for i in call)
    assert _HYDRATE_MEMO.get() is None
    remote_calls.clear()
    r.search_rrf(q, top_k=10)
    assert sorted(i for call in remote_calls for i in call) == first

    remote_calls.clear()
    a = r.search(q, top_k=5, mode="bm25f")
    b = r.search(q, top_k=5, mode="bm25f")
    assert a == b and len(remote_calls) == 2

    other_calls: list[list[str]] = []
    r2 = _memo_retriever(index_root, other_calls, [])
    remote_calls.clear()
    with r.hydrate_scope():
        r.search(q, top_k=5, mode="bm25f")
        r2.search(q, top_k=5, mode="bm25f")
        r2.search(q, top_k=5, mode="bm25f")
        r.search(q, top_k=5, mode="bm25f")
    assert len(remote_calls) == 1 and len(other_calls) == 2
    assert _HYDRATE_MEMO.get() is None


def test_hydrate_memo_remote_exception_propagates_and_is_not_memoised(index_root):
    """A non-RequestException from the remote fetch propagates out of the leg
    exactly as before, and the failed ids are not marked as seen."""
    calls: list[list[str]] = []
    r = _memo_retriever(index_root, calls, [])
    boom = {"on": True}

    def flaky(ids):
        calls.append(list(ids))
        if boom["on"]:
            raise RuntimeError("remote down")
        return {i: "ok" for i in ids}

    r._fetch_remote_abstracts = flaky
    q = "machine learning network model"
    with r.hydrate_scope():
        with pytest.raises(RuntimeError):
            r.search(q, top_k=5, mode="bm25f")
        boom["on"] = False
        hits = r.search(q, top_k=5, mode="bm25f")
    assert all(h["abstract"] == "ok" for h in hits)
    assert calls[0] == calls[1]


_FAKE_KEY = "test-key-not-a-real-secret"


def _remote_only_retriever(index_root, **kwargs):
    """Retriever with no local abstract sidecars, so every hit's abstract
    must come from the remote path."""
    r = ThinClientRetriever(index_root=str(index_root), remote_abstracts=True,
                            **kwargs)
    r._load()
    r._abstract_stores = {}
    return r


def _forbid_requests_get(monkeypatch):
    import requests

    def _boom(*a, **k):
        raise AssertionError("requests.get must not be called")
    monkeypatch.setattr(requests, "get", _boom)


def test_injected_fetcher_replaces_direct_requests(index_root, monkeypatch):
    """With a fetcher injected the retriever never calls requests.get and
    the fetcher's abstracts reach the hits."""
    _forbid_requests_get(monkeypatch)
    calls: list[list[str]] = []

    def fetcher(ids):
        calls.append(list(ids))
        return {i: f"fetched {i}" for i in ids}

    r = _remote_only_retriever(index_root, remote_abstract_fetcher=fetcher)
    hits = r.search("machine learning network model", top_k=5, mode="bm25f")
    assert hits and all(h["abstract"] == f"fetched {h['openalex_id']}" for h in hits)
    assert len(calls) == 1


def test_injected_fetcher_exception_degrades_to_no_abstract(index_root, monkeypatch):
    _forbid_requests_get(monkeypatch)

    def fetcher(ids):
        raise RuntimeError("client blew up")

    r = _remote_only_retriever(index_root, remote_abstract_fetcher=fetcher)
    hits = r.search("machine learning network model", top_k=5, mode="bm25f")
    assert hits and all(h["abstract"] == "" for h in hits)


def test_remote_abstracts_false_never_calls_fetcher(index_root, monkeypatch):
    _forbid_requests_get(monkeypatch)
    calls: list = []
    r = ThinClientRetriever(index_root=str(index_root), remote_abstracts=False,
                            remote_abstract_fetcher=lambda ids: calls.append(ids) or {})
    r._load()
    r._abstract_stores = {}
    assert r.search("machine learning network model", top_k=5, mode="bm25f")
    assert calls == []


def test_tracker_blocked_client_fetcher_yields_empty_abstracts(index_root, monkeypatch, tmp_path):
    """The real OpenAlexClient at its daily limit blocks the abstract fetch
    before any HTTP call; the search still returns, abstracts empty."""
    from lib.openalex import OpenAlexClient
    _forbid_requests_get(monkeypatch)
    client = OpenAlexClient(api_key=_FAKE_KEY, daily_call_limit=3,
                            tracker_path=str(tmp_path / "calls.json"))
    client._tracker._date = client._tracker._today()
    client._tracker._count = 3
    r = _remote_only_retriever(index_root,
                               remote_abstract_fetcher=client.fetch_abstracts_by_ids)
    hits = r.search_rrf("machine learning network model", top_k=5)
    assert hits and all(h["abstract"] == "" for h in hits)
    assert client.budget_status()["calls_today"] == 3


def test_hydrate_scope_fetches_once_per_id_via_injected_fetcher(index_root):
    """Lever #0 memo still holds with the injected fetcher: across the RRF
    legs each id is sent to the fetcher at most once per request."""
    calls: list[list[str]] = []

    def fetcher(ids):
        calls.append(list(ids))
        return {i: "x" for i in ids if int(i[1:]) % 5}

    r = _remote_only_retriever(index_root, remote_abstract_fetcher=fetcher)
    r._splade_leg = lambda q, k, f: [(d, 1.0) for d, _ in
                                     r._bm25f_leg(q, k + 4, f)][::-1][:k]
    detail = r.search_rrf_detailed("machine learning network model", top_k=10)
    sent = [i for c in calls for i in c]
    assert len(sent) == len(set(sent))
    legs = detail["legs"]
    assert set(sent) == set(legs["bm25f"]) | set(legs["splade"])


def _capture_direct_params(monkeypatch):
    import requests
    seen: list[dict] = []

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"results": []}

    def fake_get(url, params=None, timeout=None, **kw):
        seen.append(dict(params or {}))
        return _Resp()
    monkeypatch.setattr(requests, "get", fake_get)
    return seen


def test_direct_fallback_sends_api_key_when_given(index_root, monkeypatch):
    seen = _capture_direct_params(monkeypatch)
    r = ThinClientRetriever(index_root=str(index_root), openalex_mailto="a@b.c",
                            openalex_api_key=_FAKE_KEY)
    r._fetch_remote_abstracts(["W1", "W2"])
    assert len(seen) == 1
    assert seen[0].get("api_key") == _FAKE_KEY and "mailto" not in seen[0]


def test_direct_fallback_without_key_keeps_old_call_shape(index_root, monkeypatch):
    seen = _capture_direct_params(monkeypatch)
    r = ThinClientRetriever(index_root=str(index_root), openalex_mailto="a@b.c")
    r._fetch_remote_abstracts(["W1", "W2"])
    assert seen == [{
        "filter": "openalex_id:W1|W2",
        "per-page": "2",
        "select": "id,abstract_inverted_index",
        "mailto": "a@b.c",
    }]


def test_direct_fallback_error_log_redacts_key(index_root, monkeypatch, caplog):
    import logging

    import requests

    def fake_get(url, params=None, timeout=None, **kw):
        raise requests.ConnectionError(
            f"Max retries exceeded with url: /works?filter=x&api_key={params['api_key']}")
    monkeypatch.setattr(requests, "get", fake_get)
    r = ThinClientRetriever(index_root=str(index_root), openalex_api_key=_FAKE_KEY)
    with caplog.at_level(logging.WARNING, logger="sfu_library_mcp"):
        assert r._fetch_remote_abstracts(["W1"]) == {}
    assert "remote abstract fetch failed" in caplog.text
    assert _FAKE_KEY not in caplog.text


def test_tools_wires_retriever_to_shared_openalex_client(index_root, monkeypatch):
    """lib.tools builds the thin-client retriever with the configured key and
    the shared OpenAlexClient's budgeted abstract fetch."""
    import lib.tools as tools
    from lib.config import ServerConfig

    cfg = ServerConfig(search_backend="thinclient",
                       thinclient_index_root=str(index_root),
                       openalex_api_key=_FAKE_KEY, openalex_mailto="a@b.c")

    class _Client:
        def fetch_abstracts_by_ids(self, ids):
            return {}

    client = _Client()
    monkeypatch.setattr(tools, "_get_config", lambda: cfg)
    monkeypatch.setattr(tools, "_get_openalex", lambda: client)
    monkeypatch.setattr(tools, "_federated_router", None)
    monkeypatch.setattr(tools, "_thinclient_retriever", None)
    r = tools._get_thinclient_retriever()
    assert isinstance(r, ThinClientRetriever)
    assert r.openalex_api_key == _FAKE_KEY
    assert r.remote_abstract_fetcher == client.fetch_abstracts_by_ids
