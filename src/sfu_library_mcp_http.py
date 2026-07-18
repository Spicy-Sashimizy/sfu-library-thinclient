"""
SFU Library MCP Server — Streamable HTTP Transport.

Production entry point serving the same MCP server over HTTP
instead of stdio. Used for remote access from Claude Desktop via mcp-remote.

Endpoints:
  POST /mcp        — MCP JSON-RPC (Streamable HTTP transport)
  GET  /mcp        — SSE stream for server-initiated messages
  GET  /health     — Health check (returns {"status": "ok", "tools": <count>})
  GET  /analytics  — Research-analytics dashboard data bundle (Phase N GUI tracking).
                     Optional ?panel=<name> for a single panel.
  POST /engagement — Record click-through / engagement events (one or a batch).
"""

import asyncio
import contextlib
import json
import os
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool, TextContent

from lib.logging_setup import setup_logging
from lib.config import load_config, validate_config
from lib import result_cache
from lib import speculation
from lib.tools import (
    TOOL_DEFINITIONS,
    get_tool_definitions,
    handle_tool_call,
    search_academic_structured,
)

# Static web GUI (the SFU Library Suite). Served read-only at /app.
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

config = load_config()
logger = setup_logging(level=config.log_level, log_file=config.log_file)

for warning in validate_config(config):
    logger.warning("Config: %s", warning)

mcp_server = Server("sfu-library")


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return await get_tool_definitions()


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    return await handle_tool_call(name, arguments)


# ── Startup warmup (WI-6 lesson: /health "up" ≠ /search warm) ────────────────
# The retrieval stack lazy-loads on first /api/search: SEISMIC shard mmaps,
# SPLADE ONNX, dense bi-encoder, cross-encoder — measured 2m24s cold
# (2026-07-18). One background thread runs a real structured search at startup
# so (a) every model loads sequentially (no concurrent-load meta-tensor race,
# see lib/hf_load_lock.py) and (b) /health can report `warm`, which
# web/lib/api.js already consumes for the Search UI's warming state.
# Gate: SFU_HTTP_WARMUP=0 disables (then `warm` is reported true immediately,
# matching the pre-warmup contract where the field was absent).
_WARMUP_STATE = {"state": "disabled"}  # disabled | warming | warm | failed


# ── Result cache ↔ serve query log bridge (WI-17, contract term 5) ──────────
# The cache-hit signal must reach the wave-2 serve query log. On a MISS the
# real search runs inside search_academic_structured (which already calls
# log_serve_query); that call doesn't know about the cache, so a context-local
# default is installed and read there to stamp cache_hit=False. On a HIT the
# search never runs, so api_search logs the hit entry itself below.
#
# HOST-NOTE-W7-1 fix (2026-07-18): MUST use contextvars.ContextVar, NOT
# threading.local. All asyncio requests run on ONE event-loop thread, so a
# threading.local is effectively a process-global — under concurrent requests,
# request A's `finally: reset` could clear the value while request B is between
# its set and its log_serve_query, mislabeling B's cache_hit. A ContextVar is
# asyncio-task-scoped: each request's task has its own value, set on entry and
# reset via the token on exit, so concurrent tasks never see each other's flag.
import contextvars as _contextvars
_CACHE_HIT_VAR: _contextvars.ContextVar = _contextvars.ContextVar("sfu_cache_hit", default=None)
_CACHE_HIT_TOKEN: _contextvars.ContextVar = _contextvars.ContextVar("sfu_cache_hit_token", default=None)


def _set_thread_cache_hit(value: bool | None):
    """Set the request's cache-hit flag on the active asyncio context. A
    ContextVar is copied per-task, so each concurrent request's task has its own
    value — no cross-contamination (the threading.local bug HOST-NOTE-W7-1
    flagged). Returns the reset token (unused by the current callers; kept for a
    future explicit-with-token reset if needed)."""
    return _CACHE_HIT_VAR.set(value)


def _thread_cache_hit() -> bool | None:
    return _CACHE_HIT_VAR.get()


def _wire_cache_hit_log() -> None:
    """Install the cache-hit logger so result_cache.note_cache_hit() sets the
    context var the serve query log reads, AND teach the log to read it."""
    try:
        result_cache.set_cache_hit_logger(_set_thread_cache_hit)
        from lib import serve_query_log as _sql
        _orig_log = _sql.QueryLogger.log

        def _patched_log(self, *, cache_hit=None, **kw):
            if cache_hit is None:
                cache_hit = _thread_cache_hit()  # stamp from the active request
            return _orig_log(self, cache_hit=cache_hit, **kw)

        _sql.QueryLogger.log = _patched_log
    except Exception:
        logger.exception("WI-17 cache-hit log wiring failed (non-fatal)")


_wire_cache_hit_log()


# A small subject-diverse battery (not one query): each distinct query faults a
# different region of the SEISMIC forward index, so running several pre-warms a
# broader slice of the hot working set into page cache. On a native FS those
# pages STAY resident (measured 2026-07-18: warm p50 ~82 ms, holds across
# passes), so real user queries increasingly hit warm instead of paying the
# first-touch cold fault. On a slow 9p mount pages don't hold regardless, so
# keep the battery small (bounded startup cost; SFU_HTTP_WARMUP=0 disables).
_WARMUP_QUERIES = [
    "information retrieval evaluation methods",
    "deep learning neural network architecture",
    "climate change adaptation policy",
    "molecular biology gene expression",
    "quantum computing algorithms",
    "public health epidemiology intervention",
]


def _run_warmup() -> None:
    t0 = time.monotonic()
    try:
        logger.info("Startup warmup: loading retrieval stack + faulting hot set "
                    "(%d queries) ...", len(_WARMUP_QUERIES))
        for q in _WARMUP_QUERIES:
            asyncio.run(search_academic_structured({"query": q, "limit": 5}))
        _WARMUP_STATE["state"] = "warm"
        logger.info("Startup warmup complete in %.1fs", time.monotonic() - t0)
    except Exception:
        # Serve anyway: first real query pays the cold load instead.
        _WARMUP_STATE["state"] = "failed"
        logger.exception("Startup warmup failed; first query will be cold")


# ── Post-warmup result-cache pre-seed (deployprep WI-17b, 2026-07-18) ───────
# Runs STRICTLY AFTER the warmup battery completes (contract term 6) and
# sequentially (concurrency 1) — never a parallel burst on the single-GPU
# cross-encoder (the same GPU the served search path uses). Plants the live-
# review demo's own queries into the result cache so the first human keystroke
# on each lands a cache HIT, not a cold retrieval. Idempotent: re-running (or
# re-priming via scripts/prime_result_cache.py) primes MISSES ONLY — a resident
# query returns from the cache (bump hit, zero retrieval work). Gate:
# SFU_CACHE_PRESEED=0 disables (default ON — same staging-on posture as the
# result cache itself; a no-op when SFU_RESULT_CACHE=0).
_PRESEED_STATE = {"state": "disabled"}  # disabled | pending | primed | failed


def _collect_preseed_queries() -> list[str]:
    """The demo seed list: the live landing-page examples (read from their
    SOURCE web/src/search.jsx so the seeds track the landing screen even when
    the JSX examples change without a rebuild) + the owner-extensible list in
    data/eval_results/demo_seed_queries.txt. De-duplicated, order preserved.
    Replicates scripts/prime_result_cache.py's collection so the on-start and
    offline primers plant identical keys."""
    import re as _re
    from pathlib import Path as _Path
    seen, out = set(), []
    repo = Path(__file__).resolve().parents[1]
    jsx = repo / "web" / "src" / "search.jsx"
    seeds_file = repo / "data" / "eval_results" / "demo_seed_queries.txt"
    landing: list[str] = []
    if jsx.exists():
        src = jsx.read_text(encoding="utf-8")
        m = _re.search(
            r'\[([^\]]*indigenous knowledge systems in climate adaptation'
            r'[^\]]*)\]\.map\(ex\s*=>', src, _re.DOTALL)
        if m:
            landing = _re.findall(r'"([^"]+)"', m.group(1))
    file_queries: list[str] = []
    if seeds_file.exists():
        for line in seeds_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            file_queries.append(line)
    for q in landing + file_queries:
        nq = " ".join(q.split())
        if not nq or nq.casefold() in seen:
            continue
        seen.add(nq.casefold())
        out.append(q)
    return out


def _run_cache_preseed() -> None:
    """Background primer: wait for warmup to finish, then prime the cache
    sequentially. The cache must be enabled (SFU_RESULT_CACHE) and pre-seed
    must be enabled (SFU_CACHE_PRESEED); otherwise a no-op."""
    cache_enabled = result_cache.is_enabled()
    preseed_enabled = os.environ.get("SFU_CACHE_PRESEED", "1") != "0"
    if not (cache_enabled and preseed_enabled):
        _PRESEED_STATE["state"] = "disabled"
        logger.info("cache pre-seed: skipped (cache_enabled=%s, "
                    "SFU_CACHE_PRESEED=%s)", cache_enabled, preseed_enabled)
        return
    _PRESEED_STATE["state"] = "pending"
    # Wait for warmup to complete (strict ordering — term 6). The warmup thread
    # is a daemon; if it failed, priming would run cold — still safe (the
    # search path answers cold), but skip priming then to avoid a startup burst
    # paying the cold load redundantly with the warmup battery.
    while _WARMUP_STATE["state"] == "warming":
        time.sleep(1.0)
    if _WARMUP_STATE["state"] == "failed":
        _PRESEED_STATE["state"] = "failed"
        logger.info("cache pre-seed: skipped (warmup failed; priming would "
                    "redundantly pay the cold load)")
        return
    seeds = _collect_preseed_queries()
    t0 = time.monotonic()
    planted = 0
    logger.info("cache pre-seed: planting %d demo seed queries (sequential, "
                "post-warmup) ...", len(seeds))
    # Match the demo's default request shape (limit=50, no filters) so the
    # planted cache key matches a real landing-screen click. Routed through
    # result_cache.read_through — the SAME cache path api_search takes — so each
    # prime populates the cache identically to a real first hit (NOT a bare
    # search_academic_structured call, which would bypass the cache wrapper).
    limit = 50
    warm = _WARMUP_STATE["state"] != "warming"
    for q in seeds:
        try:
            _, hit = asyncio.run(result_cache.read_through(
                {"query": q, "limit": limit},
                search_academic_structured, warm=warm, degraded=False))
            planted += 1
            if hit:
                logger.debug("cache pre-seed: %r already resident (hit)", q)
        except Exception:
            logger.exception("cache pre-seed: query failed (non-fatal): %r", q)
    cnt = result_cache.counters()
    _PRESEED_STATE["state"] = "primed"
    logger.info("cache pre-seed: complete in %.1fs (%d/%d planted; cache "
                "resident=%d, miss=%d, store=%d, hit=%d)",
                time.monotonic() - t0, planted, len(seeds),
                cnt["resident"], cnt["miss"], cnt["store"], cnt["hit"])


async def health_check(request: Request) -> JSONResponse:
    state = _WARMUP_STATE["state"]
    return JSONResponse({
        "status": "ok",
        "tools": len(TOOL_DEFINITIONS),
        # warming → false (GUI shows its warming message); warm/failed/disabled
        # → true (the server answers, possibly cold — same as before warmup).
        "warm": state != "warming",
        "warmup": state,
        # Result cache hit/miss/store/bypass + resident count (WI-17). The
        # enabled flag reflects SFU_RESULT_CACHE so an operator can confirm the
        # one-env rollback took.
        "result_cache": result_cache.counters(),
        # Post-warmup pre-seed primer state (WI-17b): disabled | pending | primed
        # | failed. pending = waiting for warmup to finish before planting.
        "cache_preseed": _PRESEED_STATE["state"],
        # Searchbar keystroke speculation (WI-18): fired / dropped-busy /
        # suppressed-by-guard / predicted-vs-literal / stores, following the
        # result_cache counter shape. ``enabled`` reflects SFU_SEARCH_SPECULATE
        # (default OFF — owner flips the default, not the build).
        "speculation": speculation.counters(),
    })


async def analytics(request: Request) -> JSONResponse:
    """Read-only analytics bundle for the research-analytics GUI."""
    from lib.analytics import build_analytics_bundle
    panel = request.query_params.get("panel")
    try:
        return JSONResponse(build_analytics_bundle(panel))
    except Exception as e:
        logger.exception("Analytics bundle failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def engagement(request: Request) -> JSONResponse:
    """Capture click-through / engagement events (single object or batch)."""
    from lib.engagement import record_engagement
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    n = record_engagement(payload)
    return JSONResponse({"recorded": n})


# ── GUI REST endpoints (consumed by web/lib/api.js) ──────────────────────────
# Thin JSON wrappers so the browser never has to drive the MCP JSON-RPC
# handshake. Each reuses the existing tool logic. The GUI degrades to mock data
# on any non-2xx, so these stay simple and surface real errors as 5xx.

def _tool_json(result) -> dict:
    """Parse the first TextContent of a tool result as JSON (tools that emit
    JSON), else wrap the raw text under {'text': ...}."""
    if not result:
        return {}
    text = getattr(result[0], "text", "") or ""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return {"text": text}


def _log_cache_served_hit(args: dict, data: dict) -> None:
    """Record a cache-hit query in the wave-2 serve query log (WI-17). On a hit
    the retrieval path is skipped, so the in-search log_serve_query call never
    fires; this mirrors its oaid/k capture so repeat-traffic analysis sees the
    cache-served requests too. Non-blocking + exception-safe: logging can never
    fail a search."""
    try:
        from lib.serve_query_log import log_serve_query, QueryLogger
        if not QueryLogger.get().enabled:
            return
        limit = max(1, min(args.get("limit", 10), 50))
        oaids = [r.get("openalex_id") or r.get("doi") or ""
                 for r in (data.get("results") or [])[:limit]]
        log_serve_query(
            query=args.get("query", ""), k=limit, mode="federated",
            leg_ms={}, n_results=len(data.get("results") or []),
            result_oaids=oaids, filtered=False, cache_hit=True,
        )
    except Exception:
        logger.debug("cache-served hit log failed (non-fatal)")


async def api_search(request: Request) -> JSONResponse:
    """Structured academic search for the GUI result cards.

    Read-through result cache (deployprep WI-17, 2026-07-18): on a request we
    check the versioned cache → on a miss we run ``search_academic_structured``
    and store the result IFF it is a clean, non-degraded success (contract
    term 3 — never cache errors/429s/degraded/cold-first-contact responses).
    A cache failure can never fail a search: every cache op is wrapped so any
    exception falls through to the normal path. One-env rollback:
    ``SFU_RESULT_CACHE=0`` disables the whole cache path (default ON in
    staging — owner-granted exception for this wave only).
    """
    try:
        args = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if not isinstance(args, dict) or not args.get("query"):
        return JSONResponse({"error": "missing 'query'"}, status_code=400)

    cache_enabled = result_cache.is_enabled()
    cache = result_cache.get_cache() if cache_enabled else None
    key = result_cache.make_cache_key(args) if cache is not None else None

    # ── read-through: cache hit? ─────────────────────────────────────────────
    if cache is not None and key is not None:
        try:
            cached = cache.get(key)
        except Exception:
            # A cache read failure must never fail a search — fall through to a
            # normal uncached run (and stop using the cache for this process).
            logger.exception("result cache get failed; bypassing cache")
            cached = None
            cache = None  # NB: local only; process cache is left intact
        if cached is not None:
            result_cache.bump("hit")
            result_cache.note_cache_hit(True)
            # The search never ran, so the wave-2 log wouldn't record this query.
            # Log the hit here so repeat-traffic analysis sees the cache-served
            # requests too (cache_hit=True, no leg latencies — retrieval skipped).
            _log_cache_served_hit(args, cached)
            return JSONResponse(cached)

    # ── cache miss: run the real search ──────────────────────────────────────
    if cache is not None:
        result_cache.bump("miss")
        # Stash the miss flag on this thread so the in-search log_serve_query
        # call (which doesn't know about the cache) records cache_hit=False.
        result_cache.note_cache_hit(False)
    try:
        data = await search_academic_structured(args)
    except Exception as e:
        logger.exception("GUI search failed")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        _set_thread_cache_hit(None)  # don't leak across requests/threads

    # ── store only on a clean, non-degraded success ──────────────────────────
    # The WI-9 leg-breaker flag (router.last_degraded) and the WI-13 BM25F
    # silent-fallback both surface as a degraded note on the response; warmup
    # must be complete so we don't freeze a half-loaded cold state for the TTL.
    degraded = False
    try:
        from lib.tools import _get_federated_router
        router = _get_federated_router()
        degraded = bool(getattr(router, "last_degraded", False))
    except Exception:
        degraded = False  # router unavailable → treat as not-degraded (cache ok)
    warm = _WARMUP_STATE["state"] != "warming"
    cacheable = result_cache.is_cacheable_response(data, degraded=degraded, warm=warm)
    if cache is not None and cacheable and key is not None:
        try:
            cache.put(key, data)
            result_cache.bump("store")
        except Exception:
            # Store failure is non-fatal — the response is still returned fresh.
            logger.exception("result cache put failed; returning fresh result")
    elif cache is not None and not cacheable:
        result_cache.bump("bypass")  # deliberately not cached (bad/degraded)
    return JSONResponse(data)


async def api_speculate(request: Request) -> JSONResponse:
    """Searchbar keystroke speculation (deployprep WI-18, 2026-07-18).

    The client's debounced typing fires this with the partial typed text.
    The server runs the term-3 guards (warming / degraded / cache-off / shed)
    + the predictor (term 2) and, if a prediction is unambiguous, fire-and-
    forgets ONE speculative backend query through the SAME read-through result
    cache + key recipe a real ``api_search`` uses (term 1) — single-slot, a
    newer speculation while busy is DROPPED (term 4). The handler returns
    immediately with the decision + counters; a real Enter never waits on
    speculation bookkeeping.

    Gate: ``SFU_SEARCH_SPECULATE`` (default OFF — owner flips the default).
    The benchmark enables it per arm; the build ships a measured ON/OFF
    recommendation. This endpoint is harmless when the gate is OFF: it runs
    the guards, hits the cache-off suppression, bumps the counter, returns —
    no speculative backend query is ever fired (term 3 + term 4).
    """
    try:
        args = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if not isinstance(args, dict) or not args.get("query"):
        return JSONResponse({"error": "missing 'query'"}, status_code=400)
    typed = args["query"]
    limit = max(1, min(int(args.get("limit", 50)), 50))
    # Term-3 guards: read the live serve state the cache path itself uses.
    warm = _WARMUP_STATE["state"] != "warming"
    degraded = False
    shed = False
    try:
        from lib.tools import _get_federated_router
        router = _get_federated_router()
        degraded = bool(getattr(router, "last_degraded", False))
        # WI-11 overload/shed: the same router exposes a shedding flag if the
        # shed path armed. Absent ⇒ not shedding (the flag was added WI-11).
        shed = bool(getattr(router, "shedding", False))
    except Exception:
        degraded = False
    result = speculation.schedule(
        typed=typed, limit=limit, warm=warm, degraded=degraded, shed=shed)
    return JSONResponse(result)


async def api_index_status(request: Request) -> JSONResponse:
    """Index metrics + pack state + unpack jobs (for the Index Manager app)."""
    try:
        result = await handle_tool_call("get_index_status", {})
        return JSONResponse(_tool_json(result))
    except Exception as e:
        logger.exception("GUI index_status failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_personas(request: Request) -> JSONResponse:
    """Persona registry + live/cold section lists (for the Index Manager app)."""
    try:
        result = await handle_tool_call("list_personas", {})
        return JSONResponse(_tool_json(result))
    except Exception as e:
        logger.exception("GUI personas failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_unpack(request: Request) -> JSONResponse:
    """Kick off a background section unpack (for the Index Manager app)."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    section = (payload or {}).get("section", "")
    if not section:
        return JSONResponse({"error": "missing 'section'"}, status_code=400)
    try:
        result = await handle_tool_call("request_section_unpack", {"section": section})
        return JSONResponse({"ok": True, "message": getattr(result[0], "text", "") if result else ""})
    except Exception as e:
        logger.exception("GUI unpack failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def app_root(request: Request) -> RedirectResponse:
    """/app -> the suite shell."""
    return RedirectResponse(url="/app/suite.html")


session_manager = StreamableHTTPSessionManager(
    app=mcp_server,
    json_response=True,
    stateless=True,
)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with session_manager.run():
        if os.environ.get("SFU_HTTP_WARMUP", "1") != "0":
            _WARMUP_STATE["state"] = "warming"
            threading.Thread(target=_run_warmup, name="startup-warmup",
                             daemon=True).start()
        # Post-warmup result-cache pre-seed (WI-17b): the primer thread waits
        # for warmup to complete internally, so it's safe to start alongside.
        # SFU_CACHE_PRESEED=0 disables; no-op when SFU_RESULT_CACHE=0.
        if os.environ.get("SFU_CACHE_PRESEED", "1") != "0":
            threading.Thread(target=_run_cache_preseed,
                             name="cache-preseed", daemon=True).start()
        yield


_routes = [
    Route("/health", health_check, methods=["GET"]),
    Route("/analytics", analytics, methods=["GET"]),
    Route("/engagement", engagement, methods=["POST"]),
    Route("/api/search", api_search, methods=["POST"]),
    Route("/api/speculate", api_speculate, methods=["POST"]),
    Route("/api/index_status", api_index_status, methods=["GET"]),
    Route("/api/personas", api_personas, methods=["GET"]),
    Route("/api/unpack", api_unpack, methods=["POST"]),
    Route("/app", app_root, methods=["GET"]),
]

# Serve the static web GUI only if the bundle is present (keeps the server
# usable in headless/index-only deployments that don't ship the GUI).
if WEB_DIR.is_dir():
    _routes.append(Mount("/app", app=StaticFiles(directory=str(WEB_DIR), html=True)))
    logger.info("Serving web GUI from %s at /app", WEB_DIR)
else:
    logger.info("Web GUI dir %s not found; /app disabled", WEB_DIR)

_starlette = Starlette(lifespan=lifespan, routes=_routes)


async def app(scope, receive, send):
    if scope["type"] == "http" and scope.get("path", "").rstrip("/") == "/mcp":
        await session_manager.handle_request(scope, receive, send)
    else:
        await _starlette(scope, receive, send)


def main():
    host = os.environ.get("MCP_HTTP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_HTTP_PORT", "8080"))
    logger.info("Starting SFU Library MCP HTTP server on %s:%d", host, port)
    logger.info("Tools available: %d", len(TOOL_DEFINITIONS))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
