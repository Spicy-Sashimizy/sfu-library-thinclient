"""
Duck Library MCP Server — Streamable HTTP Transport.

Production entry point serving the same MCP server over HTTP
instead of stdio. Used for remote access from Claude Desktop via mcp-remote.

Endpoints:
  POST /mcp        — MCP JSON-RPC (Streamable HTTP transport)
  GET  /mcp        — SSE stream for server-initiated messages
  GET  /health     — Health check (returns {"status": "ok", "tools": <count>})
  GET  /analytics  — Research-analytics dashboard data bundle (Phase N GUI tracking).
                     Optional ?panel=<name> for a single panel.
  POST /engagement — Record click-through / engagement events (one or a batch).
  POST /api/search_stream — SSE draft → final search (SFU_SEARCH_DRAFT_STREAM).
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
    reset_metric_session,
    search_academic_structured,
    set_metric_session,
)

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
    token = set_metric_session(_mcp_http_session_id())
    try:
        return await handle_tool_call(name, arguments)
    finally:
        reset_metric_session(token)


def _mcp_http_session_id() -> str | None:
    """The ``mcp-session-id`` header of the current MCP HTTP request, if any.

    Never raises: outside a request, or when the client sent no header
    (this server runs the session manager stateless), returns None so the
    metrics log falls back to the per-process session id.
    """
    try:
        request = mcp_server.request_context.request
        headers = getattr(request, "headers", None)
        if headers is None:
            return None
        value = headers.get("mcp-session-id")
        return str(value)[:64] if value else None
    except Exception:
        return None


_WARMUP_STATE = {"state": "disabled"}


import contextvars as _contextvars
_CACHE_HIT_VAR: _contextvars.ContextVar = _contextvars.ContextVar("sfu_cache_hit", default=None)


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
                cache_hit = _thread_cache_hit()
            return _orig_log(self, cache_hit=cache_hit, **kw)

        _sql.QueryLogger.log = _patched_log
    except Exception:
        logger.exception("WI-17 cache-hit log wiring failed (non-fatal)")


_wire_cache_hit_log()


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
        _WARMUP_STATE["state"] = "failed"
        logger.exception("Startup warmup failed; first query will be cold")


_PRESEED_STATE = {"state": "disabled"}


def _collect_preseed_queries() -> list[str]:
    """The demo seed list: the live landing-page examples (read from their
    SOURCE web/src/search.jsx so the seeds track the landing screen even when
    the JSX examples change without a rebuild) + the owner-extensible list in
    data/eval_results/demo_seed_queries.txt. De-duplicated, order preserved.
    Replicates scripts/prime_result_cache.py's collection so the on-start and
    offline primers plant identical keys."""
    import re as _re
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
        "warm": state != "warming",
        "warmup": state,
        "sequential": _sequential_mode(),
        "search_draft_stream": _draft_stream_enabled(),
        "result_cache": result_cache.counters(),
        "cache_preseed": _PRESEED_STATE["state"],
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

    cache, key, cached = _search_cache_lookup(args)
    if cached is not None:
        return JSONResponse(cached)
    return await _search_cache_miss(args, cache, key)


def _search_cache_lookup(args: dict):
    """The read-through cache probe shared by ``api_search`` and
    ``api_search_stream``: returns ``(cache, key, cached)``. On a hit the hit
    counters, the cache-hit context flag and the serve-log row are recorded
    here, exactly once; ``cache`` is ``None`` when the cache is off or a get
    failed."""
    cache_enabled = result_cache.is_enabled()
    cache = result_cache.get_cache() if cache_enabled else None
    key = result_cache.make_cache_key(args) if cache is not None else None

    if cache is not None and key is not None:
        try:
            cached = cache.get(key)
        except Exception:
            logger.exception("result cache get failed; bypassing cache")
            cached = None
            cache = None
        if cached is not None:
            result_cache.bump("hit")
            result_cache.note_cache_hit(True)
            _log_cache_served_hit(args, cached)
            return cache, key, cached
    return cache, key, None


async def _search_cache_miss(args: dict, cache, key) -> JSONResponse:
    """The miss half of the read-through: run ``search_academic_structured``,
    store the result iff cacheable, and return the exact response
    ``api_search`` sends."""
    if cache is not None:
        result_cache.bump("miss")
        result_cache.note_cache_hit(False)
    try:
        data = await search_academic_structured(args)
    except Exception as e:
        logger.exception("GUI search failed")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        _set_thread_cache_hit(None)

    degraded = False
    try:
        from lib.tools import _get_federated_router
        router = _get_federated_router()
        degraded = bool(getattr(router, "last_degraded", False))
    except Exception:
        degraded = False
    warm = _WARMUP_STATE["state"] != "warming"
    cacheable = result_cache.is_cacheable_response(data, degraded=degraded, warm=warm)
    if cache is not None and cacheable and key is not None:
        try:
            cache.put(key, data)
            result_cache.bump("store")
        except Exception:
            logger.exception("result cache put failed; returning fresh result")
    elif cache is not None and not cacheable:
        result_cache.bump("bypass")
    return JSONResponse(data)


_FALSY_ENV = ("", "0", "false", "False", "off", "OFF")


def _sequential_mode() -> bool:
    return os.environ.get("SFU_SEQUENTIAL_MODE", "0") not in _FALSY_ENV


def _draft_stream_enabled() -> bool:
    """``SFU_SEARCH_DRAFT_STREAM`` (default OFF) and never under
    ``SFU_SEQUENTIAL_MODE``."""
    on = os.environ.get("SFU_SEARCH_DRAFT_STREAM", "0").strip().lower() in (
        "1", "true", "yes", "on")
    return on and not _sequential_mode()


def _draft_filters(args: dict) -> dict:
    """The OpenAlex-style filter dict ``search_academic_structured`` builds
    from the same args, so the draft leg sees the final path's filters."""
    filters: dict[str, str] = {}
    year_from = args.get("year_from")
    year_to = args.get("year_to")
    if year_from and year_to:
        filters["publication_year"] = f"{year_from}-{year_to}"
    elif year_from:
        filters["from_publication_date"] = f"{year_from}-01-01"
    elif year_to:
        filters["to_publication_date"] = f"{year_to}-12-31"
    if args.get("open_access_only"):
        filters["open_access.is_oa"] = "true"
    if args.get("type"):
        filters["type"] = args["type"]
    return filters


def _draft_payload(args: dict) -> dict | None:
    """The BM25F-leg draft (lever #2 of docs/SPECULATIVE_RETRIEVAL_UPGRADES.md):
    the thin-client retriever's public ``search(mode="bm25f")``, hydrated by
    the retriever itself, labelled preliminary. ``None`` when there is no
    thin-client retriever or the federated path is off (the final would not
    be a local fusion). Never cached."""
    from lib import tools as _tools
    from lib.validators import sanitize_search_query
    if not _tools._get_features().get("federated_search_enabled"):
        return None
    tc = _tools._get_thinclient_retriever()
    if tc is None:
        return None
    query = sanitize_search_query(args.get("query", ""))
    if not query:
        return None
    try:
        limit = max(1, min(int(args.get("limit", 10)), 50))
    except (TypeError, ValueError):
        limit = 10
    results = tc.search(query, top_k=limit, mode="bm25f",
                        filters=_draft_filters(args) or None)
    return {"results": list(results)[:limit], "meta": {"count": len(results)},
            "notes": [], "preliminary": True}


def _sse(event: str, data: str) -> bytes:
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


async def api_search_stream(request: Request):
    """Draft → final search stream for the GUI (lever #2, gate
    ``SFU_SEARCH_DRAFT_STREAM``, default OFF; 404 when off or under
    ``SFU_SEQUENTIAL_MODE``).

    Server-sent events on a POST: ``event: draft`` carries the BM25F-leg
    results (``preliminary: true``) as soon as that leg has hydrated;
    ``event: final`` carries bytes identical to the ``POST /api/search`` body
    for the same args, produced by the same cache read-through
    (``_search_cache_lookup`` / ``_search_cache_miss``). A cache hit emits
    only ``final``. A draft that would arrive after the final is dropped.
    A failed final is sent as ``event: error`` with the ``/api/search`` error
    body. The draft never touches the result cache.
    """
    if not _draft_stream_enabled():
        return JSONResponse({"error": "search draft stream disabled"}, status_code=404)
    try:
        args = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if not isinstance(args, dict) or not args.get("query"):
        return JSONResponse({"error": "missing 'query'"}, status_code=400)

    from starlette.responses import StreamingResponse

    cache, key, cached = _search_cache_lookup(args)

    async def _events():
        if cached is not None:
            yield _sse("final", JSONResponse(cached).body.decode("utf-8"))
            return
        final_task = asyncio.ensure_future(_search_cache_miss(args, cache, key))
        loop = asyncio.get_event_loop()
        draft_future = loop.run_in_executor(None, _draft_payload, args)
        draft_future.add_done_callback(
            lambda f: f.cancelled() or f.exception())
        done, _ = await asyncio.wait({final_task, draft_future},
                                     return_when=asyncio.FIRST_COMPLETED)
        if draft_future in done and not final_task.done():
            try:
                draft = draft_future.result()
            except Exception:
                logger.debug("search draft leg failed (non-fatal)", exc_info=True)
                draft = None
            if draft is not None:
                try:
                    yield _sse("draft", JSONResponse(draft).body.decode("utf-8"))
                except Exception:
                    logger.debug("search draft encode failed (non-fatal)", exc_info=True)
        resp = await final_task
        event = "final" if resp.status_code == 200 else "error"
        yield _sse(event, resp.body.decode("utf-8"))

    return StreamingResponse(
        _events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
    force_literal = bool(args.get("force_literal"))
    warm = _WARMUP_STATE["state"] != "warming"
    degraded = False
    shed = False
    try:
        from lib.tools import _get_federated_router
        router = _get_federated_router()
        degraded = bool(getattr(router, "last_degraded", False))
        shed = bool(getattr(router, "shedding", False))
    except Exception:
        degraded = False
    result = speculation.schedule(
        typed=typed, limit=limit, warm=warm, degraded=degraded, shed=shed,
        force_literal=force_literal)
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
    Route("/api/search_stream", api_search_stream, methods=["POST"]),
    Route("/api/index_status", api_index_status, methods=["GET"]),
    Route("/api/personas", api_personas, methods=["GET"]),
    Route("/api/unpack", api_unpack, methods=["POST"]),
    Route("/app", app_root, methods=["GET"]),
]

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
    logger.info("Starting Duck Library MCP HTTP server on %s:%d", host, port)
    logger.info("Tools available: %d", len(TOOL_DEFINITIONS))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
