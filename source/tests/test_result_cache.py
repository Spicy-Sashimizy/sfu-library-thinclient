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


def _key_at_46ec1182(args, stamp=None, tc=None):
    """Verbatim pre-change recipe (make_cache_key + _manifest_stamp at commit
    46ec1182) with the retriever lookup inlined; the gate-off oracle."""
    def manifest_stamp():
        try:
            if tc is None:
                return "openalex-only"
            manifest = tc._manifest() or {}
            built = str(manifest.get("built", "?"))
            engines = str(manifest.get("engines", "?"))
            return f"{built}@{engines}"
        except Exception:
            return "unknown"
    q = (args.get("query", "") or "").casefold().strip().strip("'\".,;:!?()[]")
    parts = [" ".join(q.split())]
    for fld in ("limit", "page", "year_from", "year_to",
                "open_access_only", "type", "prefer_local"):
        parts.append(f"{fld}={args.get(fld, '')}")
    parts.append(f"stamp={stamp or manifest_stamp()}")
    return "v1|" + "|".join(parts)


class _FakeTC:
    def __init__(self, manifest, delta=None, has_delta_attr=True):
        self._m = manifest
        if has_delta_attr:
            self._delta = delta

    def _manifest(self):
        if isinstance(self._m, Exception):
            raise self._m
        return self._m


_REPRESENTATIVE_ARGS = [
    {"query": "machine learning", "limit": 10},
    {"query": "  Machine  Learning! ", "limit": 10, "page": 2},
    {"query": "climate adaptation", "limit": 50, "year_from": 2015, "year_to": 2020,
     "open_access_only": True, "type": "article", "prefer_local": True},
    {"query": "über straße 日本", "limit": 5, "client": "curl"},
    {"query": "", "limit": 0},
    {"query": "q"},
]


def _install_tc(monkeypatch, tc):
    import types
    fake = types.ModuleType("lib.tools")
    fake._get_thinclient_retriever = lambda: tc
    monkeypatch.setitem(sys.modules, "lib.tools", fake)


class TestDeltaStampR1:
    """R1 (docs/delta_ingest/02_DESIGN.md): the key carries the delta layer's
    identity when SFU_DELTA_ROOT loaded one, and is byte-identical otherwise."""

    @pytest.mark.parametrize("tc_kind", ["none", "no_delta_attr", "delta_none", "manifest_raises",
                                         "empty_manifest"])
    def test_gate_off_keys_byte_identical_to_46ec1182(self, monkeypatch, tc_kind):
        manifest = {"built": "2026-07-06T00:00:00", "engines": {"sparse": "seismic"}}
        tc = {"none": None,
              "no_delta_attr": _FakeTC(manifest, has_delta_attr=False),
              "delta_none": _FakeTC(manifest, delta=None),
              "manifest_raises": _FakeTC(RuntimeError("boom")),
              "empty_manifest": _FakeTC({})}[tc_kind]
        _install_tc(monkeypatch, tc)
        for args in _REPRESENTATIVE_ARGS:
            for stamp in (None, "explicit-stamp"):
                new = result_cache.make_cache_key(args, stamp=stamp)
                old = _key_at_46ec1182(args, stamp=stamp, tc=tc)
                assert new.encode("utf-8") == old.encode("utf-8"), (tc_kind, args, stamp)

    def _layer(self, root, stamp):
        from lib.thinclient.delta_layer import DeltaLayer
        root.mkdir(parents=True, exist_ok=True)
        (root / "generations.json").write_text(
            '{"format": 1, "stamp": "%s", "generations": [], "mask": {}}' % stamp)
        return DeltaLayer(root)

    def test_buffer_path_matches_delta_layer(self):
        from lib.thinclient.delta_layer import BUFFER_SECTION
        assert result_cache._DELTA_BUFFER_FILES[2][1] == BUFFER_SECTION

    def test_delta_on_key_carries_stamp_and_differs_from_gate_off(self, monkeypatch, tmp_path):
        manifest = {"built": "b", "engines": "e"}
        layer = self._layer(tmp_path / "delta", "g0001-1000")
        _install_tc(monkeypatch, _FakeTC(manifest, delta=layer))
        args = {"query": "q", "limit": 10}
        on = result_cache.make_cache_key(args)
        off = _key_at_46ec1182(args, tc=_FakeTC(manifest, delta=None))
        assert on != off
        assert on.startswith(off + "@delta=g0001-1000#")
        assert result_cache.make_cache_key(args) == on, "unchanged layer must keep hitting"

    def test_publish_and_reload_rotates_key(self, monkeypatch, tmp_path):
        manifest = {"built": "b", "engines": "e"}
        args = {"query": "q", "limit": 10}
        tc = _FakeTC(manifest, delta=self._layer(tmp_path / "delta", "g0001-1000"))
        _install_tc(monkeypatch, tc)
        k1 = result_cache.make_cache_key(args)
        tc._delta = self._layer(tmp_path / "delta", "g0002-1005")
        k2 = result_cache.make_cache_key(args)
        tc._delta = self._layer(tmp_path / "delta", "g0002-1005")
        k3 = result_cache.make_cache_key(args)
        assert len({k1, k2, k3}) == 3, "a new generation, and a same-second republish, must both rotate"

    def test_buffer_writes_rotate_key(self, monkeypatch, tmp_path):
        import os as _os
        root = tmp_path / "delta"
        layer = self._layer(root, "g0001-1000")
        _install_tc(monkeypatch, _FakeTC({"built": "b", "engines": "e"}, delta=layer))
        args = {"query": "q", "limit": 10}
        keys = [result_cache.make_cache_key(args)]
        (root / "ledger.sqlite").write_bytes(b"x" * 10)
        keys.append(result_cache.make_cache_key(args))
        (root / "ledger.sqlite-wal").write_bytes(b"y")
        keys.append(result_cache.make_cache_key(args))
        meta = root / "buffer" / "delta_buffer" / "tantivy" / "meta.json"
        meta.parent.mkdir(parents=True)
        meta.write_text("{}")
        keys.append(result_cache.make_cache_key(args))
        _os.utime(meta, ns=(1, 1))
        keys.append(result_cache.make_cache_key(args))
        assert len(set(keys)) == len(keys), keys

    def test_delta_stamp_never_raises(self, tmp_path):
        class Bare:
            pass
        s = result_cache._delta_stamp(Bare())
        assert s.startswith("-#") and s.endswith("~-,-,-")
