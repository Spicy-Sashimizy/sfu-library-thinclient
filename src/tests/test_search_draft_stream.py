"""Tests for the lever-#2 draft → final search stream (``POST
/api/search_stream``, gate ``SFU_SEARCH_DRAFT_STREAM``, 2026-09-25).

Covers: gate off / sequential → 404 and ``/health`` advertises the gate; a
cache miss streams ``draft`` then ``final``; the ``final`` payload is
byte-identical to the ``POST /api/search`` body; a cache hit emits only
``final``; the draft is never stored in the result cache; the JSON route's
output is unchanged by the helper refactor.
"""

import asyncio
import importlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import result_cache  # noqa: E402
from lib import speculation  # noqa: E402

FINAL = {"results": [{"id": "F1", "openalex_id": "W1", "title": "final one é",
                      "authors": ["A"], "year": 2024},
                     {"id": "F2", "openalex_id": "W2", "title": "final two",
                      "authors": ["B"], "year": 2023}],
         "notes": [], "meta": {"count": 2}}


class FakeRetriever:
    def __init__(self):
        self.calls = []

    def search(self, query, top_k=50, mode=None, filters=None):
        self.calls.append({"query": query, "top_k": top_k, "mode": mode,
                           "filters": filters})
        return [{"openalex_id": "W9", "title": "draft nine", "score": 3.0,
                 "source": "thinclient"},
                {"openalex_id": "W1", "title": "final one é", "score": 2.0,
                 "source": "thinclient"}]


def _parse_sse(text):
    events = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        ev, data = None, None
        for line in block.split("\n"):
            if line.startswith("event: "):
                ev = line[len("event: "):]
            elif line.startswith("data: "):
                data = line[len("data: "):]
        events.append((ev, data))
    return events


def _app(monkeypatch, *, gate="1", cache_on=True, sequential="0",
         final_delay=0.05, retriever=None):
    monkeypatch.setenv("SFU_SEARCH_DRAFT_STREAM", gate)
    monkeypatch.setenv("SFU_SEQUENTIAL_MODE", sequential)
    monkeypatch.setenv("SFU_RESULT_CACHE", "1" if cache_on else "0")
    monkeypatch.setenv("SFU_SEARCH_SPECULATE", "0")
    monkeypatch.setenv("SFU_HTTP_WARMUP", "0")
    monkeypatch.setenv("SFU_CACHE_PRESEED", "0")
    importlib.reload(result_cache)
    importlib.reload(speculation)
    import sfu_library_mcp_http as http_mod
    importlib.reload(http_mod)
    http_mod._WARMUP_STATE["state"] = "warm"
    calls = {"n": 0}

    async def _mock_search(args):
        calls["n"] += 1
        await asyncio.sleep(final_delay)
        return json.loads(json.dumps(FINAL))

    monkeypatch.setattr(http_mod, "search_academic_structured", _mock_search)
    from lib import tools
    monkeypatch.setattr(tools, "search_academic_structured", _mock_search)
    fake = retriever if retriever is not None else FakeRetriever()
    monkeypatch.setattr(tools, "_get_thinclient_retriever", lambda: fake)
    monkeypatch.setattr(tools, "_get_features",
                        lambda: {"federated_search_enabled": True})

    class _Router:
        last_degraded = False
    monkeypatch.setattr(tools, "_get_federated_router", lambda: _Router())
    from starlette.testclient import TestClient
    return http_mod, TestClient(http_mod._starlette), fake, calls


def test_gate_off_returns_404_and_health_reports_false(monkeypatch):
    http_mod, client, fake, calls = _app(monkeypatch, gate="0")
    r = client.post("/api/search_stream", json={"query": "q", "limit": 10})
    assert r.status_code == 404
    assert client.get("/health").json()["search_draft_stream"] is False
    assert fake.calls == [] and calls["n"] == 0


def test_sequential_mode_disables_stream(monkeypatch):
    http_mod, client, fake, calls = _app(monkeypatch, gate="1", sequential="1")
    r = client.post("/api/search_stream", json={"query": "q", "limit": 10})
    assert r.status_code == 404
    h = client.get("/health").json()
    assert h["sequential"] is True and h["search_draft_stream"] is False


def test_gate_on_health_advertises(monkeypatch):
    http_mod, client, fake, calls = _app(monkeypatch)
    assert client.get("/health").json()["search_draft_stream"] is True


def test_missing_query_400(monkeypatch):
    http_mod, client, fake, calls = _app(monkeypatch)
    assert client.post("/api/search_stream", json={"limit": 10}).status_code == 400


def test_miss_streams_draft_then_final(monkeypatch):
    http_mod, client, fake, calls = _app(monkeypatch)
    r = client.post("/api/search_stream",
                    json={"query": "draft probe", "limit": 10, "year_from": 2020})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.text)
    assert [e for e, _ in events] == ["draft", "final"]
    draft = json.loads(events[0][1])
    assert draft["preliminary"] is True
    assert [d["openalex_id"] for d in draft["results"]] == ["W9", "W1"]
    assert fake.calls[0]["mode"] == "bm25f"
    assert fake.calls[0]["top_k"] == 10
    assert fake.calls[0]["filters"] == {"from_publication_date": "2020-01-01"}
    assert "preliminary" not in json.loads(events[1][1])


def test_final_bytes_equal_api_search_body(monkeypatch):
    http_mod, client, fake, calls = _app(monkeypatch, cache_on=False)
    args = {"query": "parity probe", "limit": 10}
    ref = client.post("/api/search", json=args)
    events = _parse_sse(client.post("/api/search_stream", json=args).text)
    final = [d for e, d in events if e == "final"]
    assert len(final) == 1
    assert final[0].encode("utf-8") == ref.content


def test_cache_hit_skips_draft(monkeypatch):
    http_mod, client, fake, calls = _app(monkeypatch, cache_on=True)
    args = {"query": "hit probe stream", "limit": 10}
    first = _parse_sse(client.post("/api/search_stream", json=args).text)
    assert [e for e, _ in first] == ["draft", "final"]
    n_draft_calls = len(fake.calls)
    hits_before = result_cache.counters()["hit"]
    second = _parse_sse(client.post("/api/search_stream", json=args).text)
    assert [e for e, _ in second] == ["final"]
    assert len(fake.calls) == n_draft_calls
    assert calls["n"] == 1
    assert result_cache.counters()["hit"] == hits_before + 1
    assert second[0][1] == first[1][1]
    assert client.post("/api/search", json=args).content == second[0][1].encode("utf-8")


def test_draft_never_cached(monkeypatch):
    http_mod, client, fake, calls = _app(monkeypatch, cache_on=True)
    args = {"query": "draft not cached", "limit": 10}
    client.post("/api/search_stream", json=args)
    cached = result_cache.get_cache().get(result_cache.make_cache_key(args))
    assert cached == FINAL
    assert "preliminary" not in cached


def test_final_before_draft_drops_draft(monkeypatch):
    import threading
    gate = threading.Event()

    class SlowRetriever(FakeRetriever):
        def search(self, *a, **kw):
            gate.wait(2.0)
            return super().search(*a, **kw)

    http_mod, client, fake, calls = _app(monkeypatch, final_delay=0.0,
                                         retriever=SlowRetriever())
    r = client.post("/api/search_stream", json={"query": "fast final", "limit": 10})
    gate.set()
    assert [e for e, _ in _parse_sse(r.text)] == ["final"]


def test_no_thinclient_retriever_final_only(monkeypatch):
    http_mod, client, fake, calls = _app(monkeypatch)
    from lib import tools
    monkeypatch.setattr(tools, "_get_thinclient_retriever", lambda: None)
    events = _parse_sse(client.post("/api/search_stream",
                                    json={"query": "no tc", "limit": 10}).text)
    assert [e for e, _ in events] == ["final"]


def test_draft_failure_is_non_fatal(monkeypatch):
    class BadRetriever(FakeRetriever):
        def search(self, *a, **kw):
            raise RuntimeError("leg down")

    http_mod, client, fake, calls = _app(monkeypatch, retriever=BadRetriever())
    events = _parse_sse(client.post("/api/search_stream",
                                    json={"query": "bad draft", "limit": 10}).text)
    assert [e for e, _ in events] == ["final"]


def test_final_error_emits_error_event(monkeypatch):
    http_mod, client, fake, calls = _app(monkeypatch, cache_on=False)

    async def _boom(args):
        await asyncio.sleep(0.05)
        raise RuntimeError("boom")

    monkeypatch.setattr(http_mod, "search_academic_structured", _boom)
    events = _parse_sse(client.post("/api/search_stream",
                                    json={"query": "err", "limit": 10}).text)
    assert events[-1][0] == "error"
    assert json.loads(events[-1][1]) == {"error": "boom"}


def test_api_search_json_route_unchanged(monkeypatch):
    """The helper refactor leaves ``POST /api/search`` byte-for-byte as it was:
    miss → the search dict rendered by JSONResponse; hit → the same bytes."""
    http_mod, client, fake, calls = _app(monkeypatch, cache_on=True)
    from starlette.responses import JSONResponse
    args = {"query": "unchanged route", "limit": 10}
    miss = client.post("/api/search", json=args)
    hit = client.post("/api/search", json=args)
    assert miss.status_code == hit.status_code == 200
    assert miss.content == JSONResponse(FINAL).body == hit.content
    assert fake.calls == []
    assert client.post("/api/search", json={"limit": 1}).status_code == 400
