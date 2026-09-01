"""Tests for cache module."""

import threading
import time

import pytest

from lib.cache import ResponseCache


class TestResponseCache:
    def test_put_and_get(self):
        cache = ResponseCache(ttl=60)
        cache.put("key1", {"data": "value"})
        assert cache.get("key1") == {"data": "value"}

    def test_cache_miss(self):
        cache = ResponseCache()
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        cache = ResponseCache(ttl=0)
        cache.put("key1", "value")
        time.sleep(0.01)
        assert cache.get("key1") is None

    def test_eviction_at_max_size(self):
        cache = ResponseCache(ttl=60, max_size=3)
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.put("k3", "v3")
        cache.put("k4", "v4")
        assert cache.get("k1") is None
        assert cache.get("k4") == "v4"
        assert cache.size <= 3

    def test_lru_eviction_order(self):
        cache = ResponseCache(ttl=60, max_size=3)
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.put("k3", "v3")
        cache.get("k1")
        cache.put("k4", "v4")
        assert cache.get("k1") == "v1"
        assert cache.get("k2") is None

    def test_memory_bounds(self):
        cache = ResponseCache(ttl=60, max_size=1000, max_memory_mb=0)
        cache.put("k1", "x" * 100)
        cache.put("k2", "y" * 100)
        assert cache.size <= 1

    def test_clear(self):
        cache = ResponseCache()
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.clear()
        assert cache.size == 0
        assert cache.get("k1") is None

    def test_overwrite_existing_key(self):
        cache = ResponseCache()
        cache.put("k1", "old")
        cache.put("k1", "new")
        assert cache.get("k1") == "new"

    def test_make_key(self):
        cache = ResponseCache()
        key = cache.make_key("search", "machine learning", 10, "rank")
        assert key == "search:machine learning:10:rank"

    def test_thread_safety(self):
        cache = ResponseCache(ttl=60, max_size=100)
        errors = []

        def writer(tid):
            try:
                for i in range(50):
                    cache.put(f"t{tid}_k{i}", f"value_{i}")
            except Exception as e:
                errors.append(e)

        def reader(tid):
            try:
                for i in range(50):
                    cache.get(f"t{tid}_k{i}")
            except Exception as e:
                errors.append(e)

        threads = []
        for tid in range(4):
            threads.append(threading.Thread(target=writer, args=(tid,)))
            threads.append(threading.Thread(target=reader, args=(tid,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_size_property(self):
        cache = ResponseCache()
        assert cache.size == 0
        cache.put("k1", "v1")
        assert cache.size == 1
        cache.put("k2", "v2")
        assert cache.size == 2
