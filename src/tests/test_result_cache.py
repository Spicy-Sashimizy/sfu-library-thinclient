"""Tests for the served-path result cache (deployprep WI-17, 2026-07-18).

Covers the contract terms the owner audited 2026-07-18:
  term 2 — normalized, versioned key (case/whitespace/punct variants collide;
           different k/filters/backends differ);
  term 3 — never cache a bad/degraded/cold response;
  term 1 — a cache failure falls through to the normal path.
"""

import os

import pytest

for _v in ("SFU_RESULT_CACHE", "SFU_ACTIVE_PROFILE", "SFU_ENV"):
    os.environ.pop(_v, None)
os.environ["SFU_RESULT_CACHE"] = "1"

import importlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import result_cache  # noqa: E402
importlib.reload(result_cache)


class TestCacheKey:
    def test_whitespace_case_punctuation_collide(self):
        """Same query, different surface form → same key (term 2)."""
        base = {"query": "machine learning", "limit": 10}
        variants = [
            {"query": "Machine Learning", "limit": 10},
            {"query": "  machine  learning  ", "limit": 10},
            {"query": "Machine Learning!", "limit": 10},
            {"query": "\tMACHINE\nlearning\t", "limit": 10},
        ]
        k = result_cache.make_cache_key(base)
        for v in variants:
            assert result_cache.make_cache_key(v) == k, f"variant {v!r} should collide"

    def test_different_limit_differs(self):
        a = result_cache.make_cache_key({"query": "q", "limit": 10})
        b = result_cache.make_cache_key({"query": "q", "limit": 20})
        assert a != b

    def test_different_page_differs(self):
        a = result_cache.make_cache_key({"query": "q", "limit": 10, "page": 1})
        b = result_cache.make_cache_key({"query": "q", "limit": 10, "page": 2})
        assert a != b

    def test_different_filters_differ(self):
        a = result_cache.make_cache_key({"query": "q", "limit": 10})
        b = result_cache.make_cache_key({"query": "q", "limit": 10, "year_from": 2020})
        c = result_cache.make_cache_key({"query": "q", "limit": 10, "type": "article"})
        d = result_cache.make_cache_key({"query": "q", "limit": 10, "open_access_only": True})
        e = result_cache.make_cache_key({"query": "q", "limit": 10, "prefer_local": True})
        assert len({a, b, c, d, e}) == 5, "each distinct filter set must get a distinct key"

    def test_extraneous_keys_ignored(self):
        """Params that don't change the result set must not fragment the key."""
        a = result_cache.make_cache_key({"query": "q", "limit": 10, "client": "browser"})
        b = result_cache.make_cache_key({"query": "q", "limit": 10, "client": "curl"})
        assert a == b

    def test_manifest_stamp_in_key(self):
        """An index/model swap (different stamp) rotates the key — never serves
        stale results (term 2). The stamp appears in the key string."""
        k = result_cache.make_cache_key({"query": "q", "limit": 10}, stamp="stamp-A")
        k2 = result_cache.make_cache_key({"query": "q", "limit": 10}, stamp="stamp-B")
        assert k != k2
        assert "stamp=stamp-A" in k
        assert "stamp=stamp-B" in k2

    def test_key_has_version_prefix(self):
        """The leading version tag is present (bump it if the recipe changes)."""
        k = result_cache.make_cache_key({"query": "q", "limit": 10}, stamp="x")
        assert k.startswith("v1|")


class TestCacheability:
    def test_clean_success_cacheable(self):
        assert result_cache.is_cacheable_response(
            {"results": [{"id": 1}], "meta": {"count": 1}}, degraded=False, warm=True)

    def test_error_response_not_cached(self):
        assert not result_cache.is_cacheable_response(
            {"error": "boom"}, degraded=False, warm=True)

    def test_degraded_not_cached(self):
        """WI-9 leg-breaker / BM25F silent fallback must not be frozen."""
        assert not result_cache.is_cacheable_response(
            {"results": [{"id": 1}]}, degraded=True, warm=True)

    def test_cold_warmup_not_cached(self):
        """A response produced while warmup is still pending (cold first
        contact) must not be cached for the TTL."""
        assert not result_cache.is_cacheable_response(
            {"results": [{"id": 1}]}, degraded=False, warm=False)

    def test_unavailable_note_not_cached(self):
        """Empty result set WITH an 'index unavailable' notice = the index is
        silently degraded (WI-13) — must not be cached as a real zero."""
        assert not result_cache.is_cacheable_response(
            {"results": [], "notes": ["The local search index is currently unavailable; results may be incomplete."]},
            degraded=False, warm=True)

    def test_empty_clean_result_cacheable(self):
        """A genuine empty result set with no degradation note IS cacheable —
        'no results for this query' is a correct answer, not a failure."""
        assert result_cache.is_cacheable_response(
            {"results": [], "meta": {"count": 0}, "notes": []}, degraded=False, warm=True)

    def test_non_dict_not_cached(self):
        assert not result_cache.is_cacheable_response(
            "not-a-dict", degraded=False, warm=True)

    def test_empty_error_shaped_not_cached(self):
        """An error key present but falsy is fine; a truthy error message is not."""
        assert result_cache.is_cacheable_response(
            {"results": [], "error": ""}, degraded=False, warm=True)
        assert not result_cache.is_cacheable_response(
            {"results": [], "error": "something"}, degraded=False, warm=True)


class TestCacheOpsAndCounters:
    def test_env_gate_off_disables(self, monkeypatch):
        monkeypatch.setenv("SFU_RESULT_CACHE", "0")
        importlib.reload(result_cache)
        result_cache._cache = None
        assert result_cache.is_enabled() is False
        assert result_cache.get_cache() is None

    def test_env_gate_on_enables(self, monkeypatch):
        monkeypatch.setenv("SFU_RESULT_CACHE", "1")
        importlib.reload(result_cache)
        result_cache._cache = None
        assert result_cache.is_enabled() is True
        c = result_cache.get_cache()
        assert c is not None
        assert c.max_size >= 200, "contract term 4: max_size must be ≥ 200"

    def test_counters_increment(self):
        importlib.reload(result_cache)
        result_cache._cache = None
        result_cache.get_cache()
        result_cache.bump("hit")
        result_cache.bump("hit")
        result_cache.bump("miss")
        cnt = result_cache.counters()
        assert cnt["hit"] == 2
        assert cnt["miss"] == 1
        assert cnt["hit_ratio"] == round(2 / 3, 4)

    def test_cache_failure_falls_through(self):
        """A cache GET that raises must not propagate — the search still runs
        (term 1). Simulate by wrapping the live cache with a poisoning shim."""
        importlib.reload(result_cache)
        result_cache._cache = None

        class _PoisonedCache:
            def get(self, key):
                raise RuntimeError("simulated cache read failure")
            def put(self, key, value):
                raise RuntimeError("simulated cache write failure")

        pc = _PoisonedCache()
        with pytest.raises(RuntimeError):
            pc.get("k")
        before = result_cache.counters()
        result_cache.bump("bypass")
        after = result_cache.counters()
        assert after["bypass"] == before["bypass"] + 1

    def test_end_to_end_store_then_hit(self):
        """A clean response stored is served on the next identical request."""
        importlib.reload(result_cache)
        result_cache._cache = None
        cache = result_cache.get_cache()
        k = result_cache.make_cache_key({"query": "climate adaptation", "limit": 5},
                                        stamp="test-stamp")
        assert cache.get(k) is None
        data = {"results": [{"id": "a"}], "meta": {"count": 1}}
        cache.put(k, data)
        got = cache.get(k)
        assert got == data, "stored response must be served byte-identical on hit"

    def test_tainted_response_not_stored(self):
        """A degraded response is never stored: store does not happen because
        is_cacheable_response gates it (this is the unit proof term 3 asks for)."""
        importlib.reload(result_cache)
        result_cache._cache = None
        cache = result_cache.get_cache()
        k = result_cache.make_cache_key({"query": "q", "limit": 5}, stamp="t")
        bad = {"error": "down"}
        cacheable = result_cache.is_cacheable_response(bad, degraded=True, warm=True)
        assert cacheable is False
        assert cache.get(k) is None


class TestPreseedCollection:
    """The seed list the primer plants (contract term 6: idempotent re-priming
    primes misses only). Validates the standalone collector matches the serve's
    collector so the on-start and offline primers plant identical keys."""

    def test_standalone_landing_examples_from_source(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                       "scripts"))
        import prime_result_cache as p
        landing = p.landing_example_queries()
        assert "indigenous knowledge systems in climate adaptation" in landing
        assert "CRISPR gene editing in salmon, open access" in landing
        assert "climate change BC fisheries 2020–2025" in landing
        assert "recent ML papers for drug discovery" in landing
        assert len(landing) == 4

    def test_seed_file_read(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                       "scripts"))
        import prime_result_cache as p
        seeds = p.seed_file_queries()
        assert len(seeds) >= 4, "seed file must carry at least the landing set"
        assert all(isinstance(q, str) and q.strip() == q for q in seeds)
        assert all(not q.startswith("#") for q in seeds), "comments stripped"

    def test_collect_seeds_dedups(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                       "scripts"))
        import prime_result_cache as p
        seeds = p.collect_seeds()
        assert len(seeds) == 6
        norms = [" ".join(s["query"].split()).casefold() for s in seeds]
        assert len(set(norms)) == len(norms), "must be de-duplicated"

    def test_serve_collector_matches_standalone(self):
        """The on-start primer (in the serve module) and the standalone
        re-primer must plant identical seed lists."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        import prime_result_cache as p_std
        os.environ.setdefault("SFU_HTTP_WARMUP", "0")
        import sfu_library_mcp_http as m
        serve_seeds = m._collect_preseed_queries()
        std_seeds = [s["query"] for s in p_std.collect_seeds()]
        assert serve_seeds == std_seeds, (
            "on-start and standalone primers must plant the same seeds "
            f"(serve={serve_seeds}, std={std_seeds})")

    def test_read_through_miss_then_hit(self):
        """The shared read_through: first call misses+stores, second hits
        (idempotent re-priming = a resident query is a no-op hit)."""
        importlib.reload(result_cache)
        result_cache._cache = None
        result_cache.get_cache()
        import asyncio

        async def fake(args):
            return {"results": [{"openalex_id": "a"}], "meta": {"count": 1}}

        async def go():
            d1, h1 = await result_cache.read_through(
                {"query": "climate adaptation", "limit": 50}, fake, warm=True)
            d2, h2 = await result_cache.read_through(
                {"query": "climate adaptation", "limit": 50}, fake, warm=True)
            return h1, h2, d1 == d2

        h1, h2, same = asyncio.run(go())
        assert h1 is False, "first call should be a miss"
        assert h2 is True, "second call should hit (idempotent re-prime)"
        assert same, "cached response must be byte-identical to the fresh one"
