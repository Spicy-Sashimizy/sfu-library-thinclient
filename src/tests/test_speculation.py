"""Tests for searchbar keystroke speculation (deployprep WI-18, 2026-07-18).

Covers the owner-audited contract terms (see ``lib/speculation.py`` header):
  term 2 — predictor before literal (unambiguous / ambiguous / no-match /
           short-input; the literal fallback is param-gated);
  term 3 — guards suppress speculation when warming / degraded / cache-off /
           shed, or typed text below min length;
  term 4 — single-slot: a newer speculation while the slot is busy is DROPPED
           (not queued); a speculation-path exception never propagates;
  term 5 — speculative executions are marked ``speculative:true`` in the
           serve query log (the flag reaches the logger via a contextvar).
"""

import asyncio
import os

import pytest

for _v in ("SFU_SEARCH_SPECULATE", "SFU_RESULT_CACHE", "SFU_ACTIVE_PROFILE",
           "SFU_ENV", "SFU_SPECULATE_LITERAL", "SFU_SPECULATE_MIN_LEN",
           "SFU_SPECULATE_MIN_RATIO"):
    os.environ.pop(_v, None)
os.environ["SFU_SEARCH_SPECULATE"] = "1"
os.environ["SFU_RESULT_CACHE"] = "1"

import importlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import result_cache  # noqa: E402
importlib.reload(result_cache)
from lib import speculation  # noqa: E402
importlib.reload(speculation)


@pytest.fixture(autouse=True)
def _clean_state():
    """Each test starts with zeroed counters + a rebuilt pool, and the result
    cache cleared so a prior test's stores don't make a speculation a free hit
    instead of a fresh store."""
    speculation.reset_counters_for_test()
    speculation.reset_pool_for_test()
    result_cache.get_cache().clear() if result_cache.is_enabled() else None
    yield
    speculation.reset_counters_for_test()
    speculation._set_speculative(None)


class TestPredictor:
    def config_pool(self, monkeypatch, pool):
        """Override the candidate pool with a fixed test set (so the predictor
        is exercised against known inputs, independent of the live JSX/seeds)."""
        monkeypatch.setattr(speculation, "candidate_pool", lambda: list(pool))

    def test_unambiguous_prefix_predicts_full(self, monkeypatch):
        self.config_pool(monkeypatch, [
            "machine learning for molecular property prediction",
            "climate change adaptation policy",
        ])
        p = speculation.predict("machine learning for molecular")
        assert p.mode == "predicted"
        assert p.reason == "unambiguous"
        assert result_cache._norm_query(p.query) == \
            result_cache._norm_query("machine learning for molecular property prediction")

    def test_unambiguous_subword_match(self, monkeypatch):
        """Typing from the candidate's 2nd word onward still predicts (term 2:
        the user can be mid-sentence)."""
        self.config_pool(monkeypatch, ["machine learning for drug discovery"])
        p = speculation.predict("learning for drug")
        assert p.mode == "predicted"
        assert p.query == "machine learning for drug discovery"

    def test_ambiguous_prefix_no_speculation(self, monkeypatch):
        """Two candidates share a prefix → don't guess (term 2: 'sufficiently
        unambiguous match exists')."""
        self.config_pool(monkeypatch, [
            "machine learning for drug discovery",
            "machine learning for protein folding",
        ])
        p = speculation.predict("machine learning for")
        assert p.mode == "none"
        assert p.reason == "ambiguous"

    def test_no_match_no_literal_when_disabled(self, monkeypatch):
        self.config_pool(monkeypatch, ["something entirely different"])
        monkeypatch.setenv("SFU_SPECULATE_LITERAL", "0")
        speculation.reset_pool_for_test()
        p = speculation.predict("quantum entanglement theory")
        assert p.mode == "none"
        assert p.reason == "no-match"

    def test_no_match_literal_fallback_when_enabled(self, monkeypatch):
        self.config_pool(monkeypatch, ["something entirely different"])
        monkeypatch.setenv("SFU_SPECULATE_LITERAL", "1")
        speculation.reset_pool_for_test()
        p = speculation.predict("quantum entanglement theory")
        assert p.mode == "literal"
        assert p.reason == "literal-fallback"
        assert p.query == result_cache._norm_query("quantum entanglement theory")

    def test_force_literal_overrides_predictor(self, monkeypatch):
        """WI-19b: request-level force_literal skips the predictor entirely and
        speculates the literal typed text — even when the predictor WOULD have
        matched a pool candidate (predictor mode). Lets the bench measure the
        novel-query (literal) leg without an env/restart flip between legs."""
        self.config_pool(monkeypatch, ["machine learning for drug discovery"])
        monkeypatch.setenv("SFU_SPECULATE_LITERAL", "0")
        speculation.reset_pool_for_test()
        p_pred = speculation.predict("machine learning for")
        assert p_pred.mode == "predicted"
        p_lit = speculation.predict("machine learning for", force_literal=True)
        assert p_lit.mode == "literal"
        assert p_lit.reason == "literal-forced"
        assert p_lit.query == result_cache._norm_query("machine learning for")

    def test_force_literal_respects_min_len(self, monkeypatch):
        """force_literal still honors the min-length guard (no point
        speculating a too-short prefix under either mode)."""
        self.config_pool(monkeypatch, ["machine learning for drug discovery"])
        monkeypatch.setenv("SFU_SPECULATE_MIN_LEN", "8")
        speculation.reset_pool_for_test()
        p = speculation.predict("machi", force_literal=True)
        assert p.mode == "none"
        assert p.reason == "short-input"

    def test_short_input_suppressed(self, monkeypatch):
        """Below min length (default ≥8 chars after normalize) → none."""
        self.config_pool(monkeypatch, ["machine learning for drug discovery"])
        monkeypatch.setenv("SFU_SPECULATE_MIN_LEN", "8")
        speculation.reset_pool_for_test()
        p = speculation.predict("machi")
        assert p.mode == "none"
        assert p.reason == "short-input"

    def test_full_candidate_typed_is_not_a_prediction(self, monkeypatch):
        """Typing the FULL candidate is already the real query — nothing to add
        (predicting it adds no information; min_ratio gate excludes it)."""
        self.config_pool(monkeypatch, ["machine learning for drug discovery"])
        p = speculation.predict("machine learning for drug discovery")
        assert p.mode == "none"

    def test_min_len_env_override(self, monkeypatch):
        self.config_pool(monkeypatch, ["machine learning for drug discovery"])
        monkeypatch.setenv("SFU_SPECULATE_MIN_LEN", "3")
        speculation.reset_pool_for_test()
        p = speculation.predict("machine learning")
        assert p.mode == "predicted"

    def test_predictor_is_deterministic(self, monkeypatch):
        """Term 2: string matching + ordered pool tiebreak — NO ML. Same input
        + same pool → same output, every call."""
        self.config_pool(monkeypatch, [
            "machine learning for drug discovery",
            "machine learning for protein folding",
        ])
        results = [speculation.predict("machine learning for") for _ in range(5)]
        assert all(r.mode == results[0].mode for r in results)
        assert all(r.reason == results[0].reason for r in results)


class TestGuards:
    def test_warming_suppresses(self, monkeypatch):
        monkeypatch.setenv("SFU_SEARCH_SPECULATE", "1")
        monkeypatch.setenv("SFU_RESULT_CACHE", "1")
        speculation.reset_pool_for_test()
        r = speculation.schedule(
            typed="machine learning for molecular", limit=50,
            warm=False, degraded=False, shed=False)
        assert r["status"] == "suppressed"
        assert r["reason"] == "warming"
        assert speculation.counters()["suppressed_by_guard"] == 1
        assert speculation.counters()["fired"] == 0

    def test_degraded_suppresses(self, monkeypatch):
        r = speculation.schedule(
            typed="machine learning for molecular", limit=50,
            warm=True, degraded=True, shed=False)
        assert r["status"] == "suppressed"
        assert r["reason"] == "degraded"

    def test_cache_off_suppresses(self, monkeypatch):
        monkeypatch.setenv("SFU_RESULT_CACHE", "0")
        importlib.reload(result_cache)
        importlib.reload(speculation)
        try:
            r = speculation.schedule(
                typed="machine learning for molecular", limit=50,
                warm=True, degraded=False, shed=False)
            assert r["status"] == "suppressed"
            assert r["reason"] == "cache-off"
        finally:
            monkeypatch.setenv("SFU_RESULT_CACHE", "1")
            importlib.reload(result_cache)
            importlib.reload(speculation)
            speculation.reset_pool_for_test()

    def test_shed_suppresses(self, monkeypatch):
        r = speculation.schedule(
            typed="machine learning for molecular", limit=50,
            warm=True, degraded=False, shed=True)
        assert r["status"] == "suppressed"
        assert r["reason"] == "shed"

    def test_gate_off_suppresses_as_cache_off(self, monkeypatch):
        monkeypatch.setenv("SFU_SEARCH_SPECULATE", "0")
        importlib.reload(speculation)
        try:
            r = speculation.schedule(
                typed="machine learning for molecular", limit=50,
                warm=True, degraded=False, shed=False)
            assert r["status"] == "suppressed"
        finally:
            monkeypatch.setenv("SFU_SEARCH_SPECULATE", "1")
            importlib.reload(speculation)
            speculation.reset_pool_for_test()


class TestSingleSlot:
    def test_busy_slot_drops_newer_speculation(self, monkeypatch):
        """A newer speculation while the slot is busy is DROPPED, not queued."""
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_backend(pred, *, limit):
            from lib import tools
            started.set()
            await release.wait()
            return False

        monkeypatch.setattr(speculation, "_speculate_search", _slow_backend)
        monkeypatch.setattr(speculation, "candidate_pool", lambda: [
            "machine learning for drug discovery", "climate change BC fisheries"])
        speculation.reset_pool_for_test()

        async def run():
            r1 = speculation.schedule(typed="machine learning for drug", limit=50,
                                       warm=True, degraded=False, shed=False)
            assert r1["status"] == "fired"
            await asyncio.wait_for(started.wait(), timeout=2.0)
            r2 = speculation.schedule(typed="climate change BC", limit=50,
                                      warm=True, degraded=False, shed=False)
            assert r2["status"] == "dropped-busy"
            assert r2["reason"] == "slot-busy"
            release.set()
            await asyncio.sleep(0.05)

        asyncio.run(run())
        cnt = speculation.counters()
        assert cnt["fired"] == 1
        assert cnt["dropped_busy"] == 1

    def test_speculation_exception_does_not_propagate(self, monkeypatch):
        """Term 4: any speculation-path exception falls through silently."""
        async def _boom(pred, *, limit):
            raise RuntimeError("speculation backend exploded")

        monkeypatch.setattr(speculation, "_speculate_search", _boom)
        monkeypatch.setattr(speculation, "candidate_pool", lambda: [
            "machine learning for drug discovery"])
        speculation.reset_pool_for_test()

        async def run():
            r = speculation.schedule(typed="machine learning for drug", limit=50,
                                     warm=True, degraded=False, shed=False)
            assert r["status"] == "fired"
            await asyncio.sleep(0.05)

        asyncio.run(run())
        assert speculation.counters()["fired"] == 1


class TestLogMarking:
    def test_speculative_contextvar_default_none(self):
        assert speculation._speculative() is None

    def test_set_speculative_round_trip(self):
        speculation._set_speculative(True)
        try:
            assert speculation._speculative() is True
        finally:
            _reset_var()

    def test_wire_marks_log_entries_speculative(self, monkeypatch):
        """The patched logger stamps the request's speculative flag onto each
        serve-query-log entry (term 5). Verifies against a REAL QueryLogger
        instance (the patched .log lives on the QueryLogger class, so the test
        instance must be a QueryLogger for the patch to run)."""
        speculation.wire_speculative_log()
        from lib import serve_query_log as _sql
        _sql.QueryLogger.reset_for_test()
        lg = _sql.QueryLogger(path="data/eval_results/_test_speculation_log.jsonl",
                              max_bytes=1024 * 1024, buffer=8192,
                              store_raw=False, enabled=True)
        monkeypatch.setattr(_sql.QueryLogger, "get", classmethod(lambda cls: lg))
        try:
            speculation._set_speculative(True)
            try:
                _sql.log_serve_query(query="q", k=10, mode="federated")
            finally:
                _reset_var()
            speculation._set_speculative(None)
            try:
                _sql.log_serve_query(query="q2", k=10, mode="federated")
            finally:
                _reset_var()
            e1 = lg._q.get_nowait()
            e2 = lg._q.get_nowait()
            assert e1["speculative"] is True
            assert e2["speculative"] is None
        finally:
            lg.close()
            _sql.QueryLogger.reset_for_test()


def _reset_var():
    """Reset the speculative contextvar to None (tests can't reach the token
    from _set_speculative's return easily here; this clears it)."""
    from lib import speculation as _s
    _s._SPEC_VAR.set(None)


class TestApiSearchRouteReturns:
    def _app(self, monkeypatch, *, cache_on):
        """Build the Starlette app with search_academic_structured mocked so we
        exercise the REAL api_search control flow (the return paths) without
        the retrieval stack. The cache env is set per the cache_on flag."""
        monkeypatch.setenv("SFU_RESULT_CACHE", "1" if cache_on else "0")
        monkeypatch.setenv("SFU_SEARCH_SPECULATE", "0")
        monkeypatch.setenv("SFU_HTTP_WARMUP", "0")
        importlib.reload(result_cache)
        importlib.reload(speculation)
        import sfu_library_mcp_http as http_mod
        importlib.reload(http_mod)
        http_mod._WARMUP_STATE["state"] = "warm"
        async def _mock_search(args):
            return {"results": [{"id": "R1", "title": "mock result",
                                  "authors": ["A"], "year": 2024}],
                    "notes": [], "meta": {"count": 1}}
        monkeypatch.setattr(http_mod, "search_academic_structured", _mock_search)
        from lib import tools
        monkeypatch.setattr(tools, "search_academic_structured", _mock_search)
        return http_mod

    def test_cache_on_miss_returns_200_with_body(self, monkeypatch):
        """HOST-NOTE-W8-2 #2: a cache-ON MISS must return 200 + a result body
        (the dropped-return regression 500'd this path)."""
        http_mod = self._app(monkeypatch, cache_on=True)
        from starlette.testclient import TestClient
        client = TestClient(http_mod._starlette)
        r = client.post("/api/search",
                        json={"query": "a novel cache-cold query " + "xyz",
                              "limit": 10})
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body.get("results"), "result body must be non-empty"

    def test_cache_off_returns_200_with_body(self, monkeypatch):
        """HOST-NOTE-W8-2 #2: a cache-OFF request must return 200 + a result
        body (the dropped-return regression 500'd EVERY non-hit search, and
        cache-off is all-non-hit by construction)."""
        http_mod = self._app(monkeypatch, cache_on=False)
        from starlette.testclient import TestClient
        client = TestClient(http_mod._starlette)
        r = client.post("/api/search", json={"query": "any query", "limit": 10})
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"
        assert r.json().get("results"), "result body must be non-empty"

    def test_cache_on_hit_returns_200(self, monkeypatch):
        """Sanity: the hit path (the only path that worked during the
        regression window) still returns 200 + the cached body."""
        http_mod = self._app(monkeypatch, cache_on=True)
        from starlette.testclient import TestClient
        client = TestClient(http_mod._starlette)
        client.post("/api/search", json={"query": "hit-probe query", "limit": 10})
        r = client.post("/api/search", json={"query": "hit-probe query", "limit": 10})
        assert r.status_code == 200
        assert r.json().get("results")
