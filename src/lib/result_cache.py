"""Read-through result cache for the served GUI search path (deployprep WI-17).

Reuses :class:`lib.cache.ResponseCache` (TTL + LRU + memory-bounded, already
thread-safe) — this module adds the served-path concerns:

  * a NORMALIZED, VERSIONED cache key so semantically-identical requests hit the
    same entry while an index/model swap never serves a stale result;
  * the read-through: cache get → on miss run the underlying search → store →
    return, with any cache exception swallowed so a cache failure can NEVER
    fail a search;
  * the "never cache a bad response" guard (errors, exception payloads, empty
    error-shaped bodies, shed/429, or any response produced while the serving
    path is degraded — the WI-9 leg-breaker flag, the BM25F silent-fallback,
    or warmup still pending);
  * hit/miss/store/bypass counters surfaced in ``/health`` and a ``cache_hit``
    boolean added to the wave-2 serve query log by the caller.

Env gate (one-env rollback — owner-granted exception for this wave ONLY):
  SFU_RESULT_CACHE  default ON for the staging serve (``=0`` fully disables).
Gate logic lives in :func:`is_enabled` — staging detection mirrors
:mod:`lib.serve_query_log` so the two stays-on-in-staging gates behave alike.

KEY RECIPE (contract term 2). The key is built in a FIXED field order from::

    v1 | <norm_query> | limit=<a> | page=<b> | year_from=<c> | year_to=<d> |
    oa=<e> | type=<f> | prefer_local=<g> | stamp=<manifest_built>@<engines>

where ``norm_query`` is casefolded + whitespace-collapsed (so "Machine
Learning!" and "machine  learning" collide), the request parameters are
exactly the ones ``api_search`` forwards into ``search_academic_structured``
and that change the result set, and ``stamp`` is the served index's manifest
``built`` timestamp + ``engines`` blob — an index/model swap therefore cannot
serve a stale response (different stamp → different key → always a miss).
Only parameters that affect the result set are hashed; e.g. ``page`` is
included because it selects a different result page even for an identical
query+limit.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from lib.cache import ResponseCache

log = logging.getLogger("result_cache")

_DEFAULT_TTL = int(os.environ.get("SFU_RESULT_CACHE_TTL", str(6 * 3600)))
_DEFAULT_MAX_SIZE = int(os.environ.get("SFU_RESULT_CACHE_MAX_SIZE", "256"))
_DEFAULT_MAX_MEM_MB = int(os.environ.get("SFU_RESULT_CACHE_MAX_MEM_MB", "64"))


_stamp_cache: tuple[str, str] | None = None


def _manifest_stamp() -> str:
    """A stable identity for the *currently served* index + model stack.

    Built from the thinclient manifest's ``built`` timestamp + ``engines`` blob
    so an index rebuild (new ``built``) or a model swap (new ``engines``)
    invalidates every cached entry by rotating the key. Read once per process
    (an index swap mid-process goes through ``retriever.reload()``, after which
    a serve restart is the norm — re-reading per-query would be needlessly
    hot-path expensive). Returns ``"unknown"`` when no thinclient retriever is
    wired (the OpenAlex-only path), which is still a stable, cacheable identity.
    """
    global _stamp_cache
    try:
        from lib.tools import _get_thinclient_retriever
        tc = _get_thinclient_retriever()
        if tc is None:
            return "openalex-only"
        manifest = tc._manifest() or {}
        built = str(manifest.get("built", "?"))
        engines = str(manifest.get("engines", "?"))
        return f"{built}@{engines}"
    except Exception:
        return "unknown"


def is_enabled() -> bool:
    """``SFU_RESULT_CACHE=0`` fully disables (one-env rollback). Default ON in
    staging, OFF only for an explicit production profile — mirrors
    :func:`lib.serve_query_log._staging_default` so the two staging-on gates
    stay consistent. Owner-granted exception to the no-served-default-flip rule
    for THIS wave only (deployprep WI-17, 2026-07-18)."""
    explicit = os.environ.get("SFU_RESULT_CACHE")
    if explicit is not None:
        return explicit.strip().lower() in ("1", "true", "yes", "on")
    profile = os.environ.get("SFU_ACTIVE_PROFILE", "default")
    env = os.environ.get("SFU_ENV", "")
    return profile.lower() != "production" and env.lower() != "production"


_cache: ResponseCache | None = None
_counters: dict[str, int] = {"hit": 0, "miss": 0, "store": 0, "bypass": 0}


def get_cache() -> ResponseCache | None:
    """The process-wide cache, lazily constructed. ``None`` when the env gate
    is OFF — callers should call :func:`is_enabled` before the cache path; this
    returns the live object only for diagnostics/priming."""
    global _cache
    if not is_enabled():
        return None
    if _cache is None:
        _cache = ResponseCache(
            ttl=_DEFAULT_TTL,
            max_size=_DEFAULT_MAX_SIZE,
            max_memory_mb=_DEFAULT_MAX_MEM_MB,
        )
    return _cache


def bump(key: str) -> None:
    """Increment a hit/miss/store/bypass counter. Public so the serve wiring
    can bump without reaching into the module dict."""
    _counters[key] = _counters.get(key, 0) + 1


def counters() -> dict:
    """Snapshot for ``/health``: hit/miss/store/bypass + resident size + the
    env gate state (so an operator can confirm ``SFU_RESULT_CACHE=0`` took)."""
    size = _cache.size if _cache is not None else 0
    total = sum(_counters.values())
    hits, misses = _counters["hit"], _counters["miss"]
    return {
        "enabled": is_enabled(),
        **{k: _counters[k] for k in ("hit", "miss", "store", "bypass")},
        "resident": size,
        "hit_ratio": round(hits / max(hits + misses, 1), 4),
    }


_KEY_FIELDS = ("limit", "page", "year_from", "year_to",
               "open_access_only", "type", "prefer_local")


def _norm_query(q: str) -> str:
    """casefold + collapse whitespace + strip outer punctuation + quotes. Mirrors
    :func:`lib.serve_query_log._normalize_query` so a repeat query the wave-2
    log dedupes as one subject also cache-collides as one entry (``"Machine
    Learning!"`` and ``"  machine  learning  "`` → same key)."""
    q = (q or "").casefold().strip().strip("'\".,;:!?()[]")
    return " ".join(q.split())


def make_cache_key(args: dict[str, Any], stamp: str | None = None) -> str:
    """Build the versioned cache key for one ``api_search`` request.

    ``args`` is the raw request body as ``api_search`` received it. Only the
    request parameters that change the result set participate; extraneous keys
    in ``args`` are ignored. Two semantically-identical requests produce the same
    key regardless of whitespace/case differences in the query text.
    """
    nq = _norm_query(args.get("query", ""))
    parts = [nq]
    for fld in _KEY_FIELDS:
        parts.append(f"{fld}={args.get(fld, '')}")
    parts.append(f"stamp={stamp or _manifest_stamp()}")
    return "v1|" + "|".join(parts)


def is_cacheable_response(data: dict, *, degraded: bool, warm: bool) -> bool:
    """True only for a clean, non-degraded success — contract term 3.

    Never caches: errors/exceptions (the ``{"error": ...}`` shape), empty
    error-shaped payloads, a response produced while the serving path is
    degraded (the WI-9 leg-breaker flag / BM25F silent fallback), or one
    produced while warmup is still pending (a cold first contact would freeze
    a transiently-slow or half-loaded state for the TTL — worse than no cache).
    """
    if not warm:
        return False
    if degraded:
        return False
    if not isinstance(data, dict):
        return False
    if data.get("error"):
        return False
    notes = data.get("notes") or []
    if (not data.get("results")
            and any("unavailable" in str(n).lower() or "degraded" in str(n).lower()
                    or "incomplete" in str(n).lower() for n in notes)):
        return False
    return True


_log_cache_hit = lambda hit: None  # noqa: E731


def set_cache_hit_logger(fn) -> None:
    """Wire the serve query-log's ``cache_hit`` field. Called once at serve
    import; tests can leave the no-op default or install their own."""
    global _log_cache_hit
    _log_cache_hit = fn


async def read_through(args: dict, search_fn, *, warm: bool, degraded: bool = False) -> tuple[Any, bool]:
    """The cache-side read-through shared by the on-start pre-seed primer (and
    usable by any in-process caller). Returns ``(data, hit)`` where ``hit`` is
    True when the response came from the cache (no retrieval work done) and
    False when it ran the real search. ``search_fn(args)`` is the underlying
    async search callable (its result is awaited).

    When the cache is disabled, this is a pure passthrough (always a miss,
    retrieval runs, ``hit=False``). Every cache op is wrapped so a cache failure
    can never fail a search: an exception in get → falls through to search; an
    exception in put → the fresh result is still returned. A bad/degraded/cold
    response is stored never (contract term 3). ``api_search`` keeps its own
    inline read-through because it must read the router's ``last_degraded`` flag
    post-search and build the HTTP response; the primer (priming warm against a
    healthy stack) passes ``degraded=False`` — a silent BM25F fallback still
    won't cache because ``is_cacheable_response`` checks the degradation note.
    """
    cache = get_cache() if is_enabled() else None
    key = make_cache_key(args) if cache is not None else None
    if cache is not None and key is not None:
        try:
            cached = cache.get(key)
        except Exception:
            cached = None
            cache = None
        if cached is not None:
            bump("hit")
            note_cache_hit(True)
            return cached, True
    if cache is not None:
        bump("miss")
        note_cache_hit(False)
    data = await search_fn(args)
    cacheable = is_cacheable_response(data, degraded=degraded, warm=warm)
    if cache is not None and cacheable and key is not None:
        try:
            cache.put(key, data)
            bump("store")
        except Exception:
            pass
    elif cache is not None and not cacheable:
        bump("bypass")
    return data, False


def note_cache_hit(hit: bool) -> None:
    _log_cache_hit(bool(hit))


__all__ = [
    "is_enabled", "get_cache", "counters", "bump",
    "make_cache_key", "is_cacheable_response", "read_through",
    "note_cache_hit", "set_cache_hit_logger",
    "_norm_query", "_manifest_stamp",
]
