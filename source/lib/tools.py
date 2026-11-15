"""MCP tool definitions and handler dispatch."""

import asyncio
import contextvars
import json
import logging
import os
import re
import tempfile
import time
from typing import Any

import requests
from mcp.types import Tool, TextContent

from lib.citations import enrich_metadata_from_crossref
from lib.config import load_config, ServerConfig
from lib.formatters import (
    format_openalex_results,
    format_library_databases_list,
    format_library_database,
    format_semantic_scholar_papers,
)
from lib.reranker import (
    rerank_results,
    rerank_with_crossencoder,
    _CE_CANDIDATE_POOL,
)
from lib.config import SERVER_VERSION
from lib.validators import sanitize_search_query
from lib.zotero import (
    PDF_MAX_BYTES, ZoteroClient, ZoteroError, download_pdf, fetch_zotero_item_types, is_pdf_file,
)

logger = logging.getLogger("sfu_library_mcp")

_request_semaphore = asyncio.Semaphore(8)

_config: ServerConfig | None = None


def _get_config() -> ServerConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _get_features() -> dict[str, bool]:
    return _get_config().features


def _retrieval_top_k(limit: int) -> int:
    """How many candidates to retrieve before reranking.

    When reranking is on, fetch a wider pool than the caller's `limit` so the
    reranker (and especially the cross-encoder second pass) has docs from rank
    11-N to promote (item #4). When reranking is off, fetch exactly `limit`.
    """
    features = _get_features()
    if not features.get("rerank_enabled"):
        return limit
    wide = features.get("crossencoder_enabled")
    pool = _CE_CANDIDATE_POOL if wide else limit
    return max(limit, pool)


def _maybe_rerank(docs: list[dict], query: str, limit: int) -> list[dict]:
    """Apply reranking pipeline if enabled; always returns at most `limit` docs.

    With ``SFU_SEARCH_SPECULATIVE_RERANK=1`` the unchanged pipeline runs inside
    ``speculative_rerank.consume`` so model calls identical to the BM25F
    draft's reuse the drafted result (byte-identical output by construction).
    """
    from lib import speculative_rerank
    if speculative_rerank.is_enabled():
        with speculative_rerank.consume(docs):
            return _maybe_rerank_impl(docs, query, limit)
    return _maybe_rerank_impl(docs, query, limit)


def _maybe_rerank_impl(docs: list[dict], query: str, limit: int) -> list[dict]:
    """The rerank pipeline behind ``_maybe_rerank``.

    Stage 1 (rerank_enabled):  embedding cosine ± RRF fusion.
    Stage 2 (crossencoder_enabled): cross-encoder second pass on top-20 Stage 1 results.
    Each stage can be toggled independently via SFU_FEATURE_* env vars.
    Falls back to original order if any stage errors.
    """
    features = _get_features()
    if not features.get("rerank_enabled"):
        return docs[:limit]
    try:
        cfg = _get_config()
        model_path = cfg.embedding_model_path or None
        ce_enabled = features.get("crossencoder_enabled")
        stage1_limit = max(limit, _CE_CANDIDATE_POOL) if ce_enabled else limit
        reranked = rerank_results(
            docs,
            query,
            stage1_limit,
            use_embedding=True,
            use_rrf=features.get("rrf_enabled", False),
            embedding_model_path=model_path,
        )
        if ce_enabled:
            reranked = rerank_with_crossencoder(reranked, query, limit)
        return reranked
    except Exception:
        logger.exception("Reranker failed, falling back to original order")
        return docs[:limit]


def _log_query(query: str, results: list[dict], latency_ms: float, handler: str) -> None:
    """Append a structured query log entry to the JSONL query log.

    Captures (query, ranked results, latency, feature flags) for downstream
    offline relevance analysis.  Writes are synchronous but bounded to a single line
    append; failures are silently swallowed so search is never interrupted.

    Enable via:  SFU_FEATURE_QUERY_LOG_ENABLED=true  SFU_QUERY_LOG_PATH=/path/to/query_log.jsonl
    """
    config = _get_config()
    if _get_features().get("engagement_log_enabled") and results:
        try:
            from lib.engagement import log_impressions
            log_impressions("server", query, results)
        except Exception:
            logger.debug("Impression logging failed (non-fatal)")
    if not _get_features().get("query_log_enabled"):
        return
    log_path = config.query_log_path
    if not log_path:
        return
    try:
        import datetime
        from pathlib import Path
        features = _get_features()
        entry = {
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "query": query,
            "handler": handler,
            "latency_ms": round(latency_ms, 1),
            "flags": {
                "rrf": features.get("rrf_enabled", False),
                "crossencoder": features.get("crossencoder_enabled", False),
            },
            "model_version": SERVER_VERSION,
            "results": [
                {
                    "rank": i + 1,
                    "doi": r.get("doi", ""),
                    "title": (r.get("title") or "")[:120],
                    "cited_by_count": r.get("cited_by_count", 0),
                    "year": r.get("publication_year"),
                    "type": r.get("type", ""),
                    "abstract_len": len(r.get("abstract") or ""),
                }
                for i, r in enumerate(results[:10])
            ],
        }
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        logger.debug("Query log write failed (non-fatal)")


_zotero_client: ZoteroClient | None = None
_openalex_client = None
_sfu_registry = None
_access_resolver = None
_s2_client = None


def _get_zotero_client() -> ZoteroClient:
    global _zotero_client
    if _zotero_client is None:
        _zotero_client = ZoteroClient(_get_config())
    return _zotero_client


def _get_openalex() -> "OpenAlexClient":
    global _openalex_client
    if _openalex_client is None:
        from lib.openalex import OpenAlexClient
        cfg = _get_config()
        _openalex_client = OpenAlexClient(
            mailto=cfg.openalex_mailto,
            api_key=cfg.openalex_api_key,
            daily_call_limit=cfg.openalex_daily_call_limit,
            tracker_path=cfg.openalex_tracker_path,
        )
    return _openalex_client


_federated_router = None
_LIVE_FALLBACK_NOTE = ("The live OpenAlex search failed; these results come from the "
                       "local index, which may not include the newest work.")
_thinclient_retriever = None


def _get_thinclient_retriever():
    """The live ThinClientRetriever, or None on a non-thinclient backend."""
    _get_federated_router()
    return _thinclient_retriever


def _get_federated_router() -> "FederatedSearchRouter":
    global _federated_router, _thinclient_retriever
    if _federated_router is None:
        from lib.federated_search import FederatedSearchRouter
        cfg = _get_config()
        if cfg.search_backend == "thinclient":
            from lib.thinclient.retriever import ThinClientRetriever
            retriever = ThinClientRetriever(
                index_root=cfg.thinclient_index_root,
                splade_model_path=cfg.splade_model_path,
                openalex_mailto=cfg.openalex_mailto,
                query_log_path=(cfg.query_log_path
                                if cfg.features.get("query_log_enabled") else ""),
                openalex_api_key=cfg.openalex_api_key,
                remote_abstract_fetcher=_get_openalex().fetch_abstracts_by_ids,
            )
            _thinclient_retriever = retriever
        else:
            raise RuntimeError(
                f"SFU_SEARCH_BACKEND={cfg.search_backend}: only 'thinclient' is served; "
                "the OpenSearch backend was decommissioned 2026-06-11"
            )
        _federated_router = FederatedSearchRouter(
            openalex_client=_get_openalex(),
            opensearch_retriever=retriever,
            recency_days=cfg.federated_recency_days,
            local_rrf_enabled=cfg.features.get("local_rrf_enabled", True),
        )
    return _federated_router


def _get_registry() -> "SFUDatabaseRegistry":
    global _sfu_registry
    if _sfu_registry is None:
        from lib.sfu_databases import SFUDatabaseRegistry
        cfg = _get_config()
        _sfu_registry = SFUDatabaseRegistry(
            cache_ttl=cfg.sfu_db_registry_cache_ttl,
            cache_file=cfg.sfu_db_registry_cache_file,
        )
    return _sfu_registry


def _get_resolver() -> "AccessResolver":
    global _access_resolver
    if _access_resolver is None:
        from lib.access_resolver import AccessResolver
        _access_resolver = AccessResolver(
            registry=_get_registry(),
            unpaywall_email=_get_config().unpaywall_email,
        )
    return _access_resolver


def _get_s2() -> "SemanticScholarClient":
    global _s2_client
    if _s2_client is None:
        from lib.semantic_scholar import SemanticScholarClient
        _s2_client = SemanticScholarClient(api_key=_get_config().semantic_scholar_api_key)
    return _s2_client


_work_cache: dict[str, dict] = {}


def _cache_works(works: list[dict]) -> None:
    for w in works:
        doi = w.get("doi", "")
        openalex_id = w.get("openalex_id", "")
        if doi:
            _work_cache.pop(doi, None)
            _work_cache[doi] = w
        if openalex_id:
            _work_cache.pop(openalex_id, None)
            _work_cache[openalex_id] = w
        if len(_work_cache) > 500:
            for k in list(_work_cache)[:len(_work_cache) - 500]:
                del _work_cache[k]


def _lookup_work(doi_or_id: str) -> dict | None:
    return _work_cache.get(doi_or_id)


_METRIC_IDS_TOP_K = 10

_metric_ids_var: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "sfu_metric_ids", default=None)
_metric_session_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sfu_metric_session", default=None)


def _new_process_session_id() -> str:
    """Per-process short random id, same style as serve_query_log._rand_id."""
    import secrets
    return secrets.token_hex(4)


_PROCESS_SESSION_ID = _new_process_session_id()


def set_metric_session(session_id: str | None) -> contextvars.Token:
    """Bind the metrics-log ``session`` for the current task (HTTP transport).

    Returns the token for ``reset_metric_session``. A falsy id leaves the
    per-process id in effect.
    """
    return _metric_session_var.set(session_id or None)


def reset_metric_session(token: contextvars.Token) -> None:
    _metric_session_var.reset(token)


def _metric_session() -> str:
    return _metric_session_var.get() or _PROCESS_SESSION_ID


def _work_metric_id(work: dict) -> str:
    """Normalized DOI when present, else the OpenAlex id (else S2 paperId)."""
    from lib.openalex import normalize_doi
    doi = normalize_doi(work.get("doi") or "")
    if doi:
        return doi
    return str(work.get("openalex_id") or work.get("paperId") or work.get("paper_id") or "")


def _note_metric_ids(ids: list[str]) -> None:
    """Attach ids to the metrics-log line of the tool call in progress.

    Side channel only: the handler's returned text is untouched. No-op when
    called outside ``handle_tool_call``.
    """
    holder = _metric_ids_var.get()
    if holder is None:
        return
    holder[:] = [i for i in ids if i][:_METRIC_IDS_TOP_K]


def _note_result_ids(works: list[dict] | None) -> None:
    _note_metric_ids([_work_metric_id(w) for w in (works or [])[:_METRIC_IDS_TOP_K]])


def _note_doc_id(doi: str) -> None:
    from lib.openalex import normalize_doi
    _note_metric_ids([normalize_doi(doi)])


def _record_metric(tool_name: str, latency: float, success: bool,
                   ids: list[str] | None = None) -> None:
    _persist_metric(tool_name, latency, success, ids=ids)


def _persist_metric(tool_name: str, latency: float, success: bool,
                    ids: list[str] | None = None) -> None:
    """Append one metric entry to the JSONL metrics log if configured.

    Enable via: SFU_METRICS_LOG_PATH=/path/to/metrics.jsonl
    Each line: {ts, tool, latency_ms, success, server_version, session, ids}
    ``session``: per-process random id, or the MCP HTTP session id when bound
    via ``set_metric_session``. ``ids``: ranked top-10 result ids for search
    tools, ``[normalize_doi(arg)]`` for doc-level tools, else null.
    Failures are silently swallowed so a bad log path never breaks a tool call.
    """
    config = _get_config()
    log_path = config.metrics_log_path
    if not log_path:
        return
    try:
        import datetime
        from pathlib import Path
        entry = {
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "tool": tool_name,
            "latency_ms": round(latency * 1000, 1),
            "success": success,
            "server_version": SERVER_VERSION,
            "session": _metric_session(),
            "ids": list(ids)[:_METRIC_IDS_TOP_K] if ids else None,
        }
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        logger.debug("Metrics log write failed (non-fatal)")


def _ensure_zotero_auth() -> list[TextContent] | None:
    if not _get_features().get("zotero_enabled", True):
        return [TextContent(type="text", text="Zotero integration is disabled.")]
    try:
        zot = _get_zotero_client()
        if not zot.ensure_authenticated():
            return [TextContent(type="text", text=(
                "Zotero authentication failed. Check SFU_ZOTERO_API_KEY and SFU_ZOTERO_USER_ID."
            ))]
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero auth error: {e}")]
    return None


TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="search_academic",
        description=(
            "Search 250M+ scholarly works via OpenAlex (articles, books, datasets, theses). "
            "Returns titles, authors, DOIs, open-access status, citation counts, and abstracts.\n\n"
            "FILTERS (all optional):\n"
            "- year_from / year_to: publication year range (e.g. year_from=2020)\n"
            "- open_access_only: true to limit to freely available papers\n"
            "- type: 'article', 'book', 'dataset', 'dissertation', 'preprint'\n\n"
            "TIPS:\n"
            "- Use the returned DOI with save_to_zotero or get_full_text_link\n"
            "- For citations/references of a specific paper use get_citations / get_references\n"
            "- For biomedical literature add search_biomedical for PubMed coverage\n"
            "- For work newer than the local index, put 'recent', 'latest' or the current year "
            "in the query text; a year range that lies past the local index also searches live"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Results to return (default 10, max 50)", "default": 10},
                "page": {"type": "integer", "description": "Page number (default 1)", "default": 1},
                "year_from": {"type": "integer", "description": "Earliest publication year"},
                "year_to": {"type": "integer", "description": "Latest publication year"},
                "open_access_only": {"type": "boolean", "description": "Limit to open-access works", "default": False},
                "type": {
                    "type": "string",
                    "description": "Work type filter",
                    "enum": ["article", "book", "dataset", "dissertation", "preprint"],
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="search_by_author",
        description=(
            "Find scholarly works by a specific author via OpenAlex. "
            "Use 'LastName, FirstName' or just the last name. "
            "Returns works with DOIs you can use for citations and Zotero."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "author": {"type": "string", "description": "Author name (best: 'LastName, FirstName')"},
                "limit": {"type": "integer", "description": "Results to return (default 10)", "default": 10},
            },
            "required": ["author"],
        },
    ),
    Tool(
        name="search_by_doi",
        description=(
            "Look up a specific work by its DOI. Returns full metadata including "
            "title, authors, abstract, open-access status, and citations. "
            "Use this when you have a DOI and want full details."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "doi": {"type": "string", "description": "DOI (with or without https://doi.org/ prefix)"},
            },
            "required": ["doi"],
        },
    ),
    Tool(
        name="search_by_topic",
        description=(
            "Search for works by academic topic or concept via OpenAlex. "
            "Good for broad discipline-level discovery. "
            "For narrower keyword searches use search_academic instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Academic topic or concept (e.g. 'machine learning', 'climate change')"},
                "limit": {"type": "integer", "description": "Results to return (default 10)", "default": 10},
                "open_access_only": {"type": "boolean", "description": "Limit to open-access works", "default": False},
            },
            "required": ["topic"],
        },
    ),
    Tool(
        name="get_citations",
        description=(
            "Get papers that cite a given work, via Semantic Scholar. "
            "Useful for forward citation tracking. "
            "Provide the DOI (preferred) or a Semantic Scholar paper ID."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "doi": {"type": "string", "description": "DOI of the paper to find citations for"},
                "limit": {"type": "integer", "description": "Max citations to return (default 20)", "default": 20},
            },
            "required": ["doi"],
        },
    ),
    Tool(
        name="get_references",
        description=(
            "Get the reference list of a paper (papers it cites), via Semantic Scholar. "
            "Useful for backward citation tracking. "
            "Provide the DOI."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "doi": {"type": "string", "description": "DOI of the paper whose references to fetch"},
                "limit": {"type": "integer", "description": "Max references to return (default 20)", "default": 20},
            },
            "required": ["doi"],
        },
    ),
    Tool(
        name="get_paper_summary",
        description=(
            "Get an AI-generated one-sentence summary (TLDR) of a paper from Semantic Scholar. "
            "Provide the DOI."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "doi": {"type": "string", "description": "DOI of the paper"},
            },
            "required": ["doi"],
        },
    ),
    Tool(
        name="find_open_access",
        description=(
            "Check whether a free full-text copy of a paper is available anywhere, "
            "using Unpaywall. Searches PubMed Central, institutional repositories, "
            "author websites, and legal preprint servers. Provide the DOI."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "doi": {"type": "string", "description": "DOI to check for open-access availability"},
            },
            "required": ["doi"],
        },
    ),
    Tool(
        name="get_full_text_link",
        description=(
            "Get the best available access URL for a paper. "
            "Tries in order: open-access copy, Unpaywall, Duck Library subscription (with EZProxy if needed), "
            "then falls back to the DOI link. "
            "Library users can authenticate via EZProxy in their browser."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "doi": {"type": "string", "description": "DOI of the paper"},
            },
            "required": ["doi"],
        },
    ),
    Tool(
        name="browse_library_databases",
        description=(
            "Browse or search Duck Library's subscribed databases and electronic resources. "
            "Returns database names, descriptions, subjects, content types, and access URLs. "
            "Use this to discover which specialized databases the library subscribes to for a given subject."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term (database name or keyword)"},
                "subject": {"type": "string", "description": "Filter by subject area (e.g. 'Psychology', 'Chemistry')"},
                "content_type": {
                    "type": "string",
                    "description": "Filter by content type (e.g. 'Full-text database', 'Datasets', 'Ebook collection')",
                },
                "free_only": {"type": "boolean", "description": "Show only freely accessible databases", "default": False},
                "limit": {"type": "integer", "description": "Max results (default 20)", "default": 20},
            },
            "required": [],
        },
    ),
    Tool(
        name="check_library_access",
        description=(
            "Check whether Duck Library subscribes to a specific database or resource. "
            "Provide the database name, publisher, or URL. "
            "Returns subscription status and EZProxy information."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Database or resource name to check (e.g. 'JSTOR', 'Nature', 'Web of Science')"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="search_biomedical",
        description=(
            "Search biomedical and life sciences literature via Europe PMC "
            "(43M+ records from PubMed, PMC, and preprints). "
            "Complements search_academic for health sciences, medicine, and biology."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Biomedical search query"},
                "limit": {"type": "integer", "description": "Results to return (default 10)", "default": 10},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="save_to_zotero",
        description=(
            "Save a paper to the user's Zotero library. "
            "Provide a DOI to auto-fetch metadata, OR supply raw fields (title, authors, year, etc.) "
            "directly when no DOI is available. "
            "Automatically checks for duplicates. Optionally specify a collection name."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "doi": {"type": "string", "description": "DOI of the paper (optional if raw fields are provided)"},
                "collection_name": {"type": "string", "description": "Zotero collection name (created if it doesn't exist)"},
                "parent_collection": {"type": "string", "description": "Parent collection name for nested collections"},
                "title": {"type": "string", "description": "Paper/book title (used when no DOI is available)"},
                "authors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Author names in 'Last, First' format",
                },
                "year": {"type": "string", "description": "Publication year"},
                "item_type": {
                    "type": "string",
                    "description": (
                        "Any valid Zotero item type, e.g. 'journalArticle', 'computerProgram', "
                        "'thesis', 'blogPost'. Full list: https://api.zotero.org/itemTypes. "
                        "When given, it overrides the type looked up from the DOI; omit it to keep that type "
                        "(manual saves without a DOI default to 'document')."
                    ),
                },
                "journal": {"type": "string", "description": "Journal or publication name (articles)"},
                "publisher": {"type": "string", "description": "Publisher or studio name"},
                "volume": {"type": "string", "description": "Volume number"},
                "issue": {"type": "string", "description": "Issue number"},
                "pages": {"type": "string", "description": "Page range (e.g. '123-145')"},
                "isbn": {"type": "string", "description": "ISBN"},
                "issn": {"type": "string", "description": "ISSN"},
                "url": {"type": "string", "description": "URL"},
                "editors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Editor names in 'Last, First' format (book sections)",
                },
                "book_title": {"type": "string", "description": "Containing book title (book sections)"},
                "edition": {"type": "string", "description": "Edition (e.g. '3rd')"},
                "institution": {"type": "string", "description": "University or issuing institution (theses, reports)"},
                "degree_type": {
                    "type": "string",
                    "enum": ["doctoral", "masters"],
                    "description": "Thesis type (doctoral or masters)",
                },
                "conference_name": {"type": "string", "description": "Conference name (conference papers)"},
                "conference_location": {"type": "string", "description": "Conference location (conference papers)"},
                "report_number": {"type": "string", "description": "Report or document number"},
                "version": {"type": "string", "description": "Software version number"},
                "accessed_date": {"type": "string", "description": "Date accessed in ISO format (webpages, e.g. '2024-03-15')"},
            },
            "required": [],
        },
    ),
    Tool(
        name="batch_save_to_zotero",
        description=(
            "Save multiple papers to Zotero at once using their DOIs. "
            "Checks each for duplicates and skips items already in the library."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "dois": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of DOIs to save (max 20)",
                },
                "collection_name": {"type": "string", "description": "Zotero collection name"},
                "parent_collection": {"type": "string", "description": "Parent collection name"},
            },
            "required": ["dois", "collection_name"],
        },
    ),
    Tool(
        name="list_zotero_collections",
        description="List all collections in the user's Zotero library with item counts.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="search_zotero",
        description=(
            "Search the user's existing Zotero library. Use this BEFORE saving to check for "
            "duplicates, and to answer questions about what the user already has saved. "
            "Returns titles, authors, dates, types, DOIs, collections, and tags."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query to find items in the Zotero library"},
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 20, max: 100)",
                    "default": 20,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="get_zotero_collection_items",
        description=(
            "List all items in a specific Zotero collection. Use to browse what's already "
            "saved in a collection or to help the user review their saved research."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "collection_name": {"type": "string", "description": "Name of the Zotero collection to list items from"},
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of items to return (default: 50, max: 100)",
                    "default": 50,
                },
            },
            "required": ["collection_name"],
        },
    ),
    Tool(
        name="get_zotero_status",
        description="Check Zotero API connection, credentials, and permissions.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="attach_pdf_to_zotero",
        description=(
            "Attach a PDF to an existing Zotero item as a stored file. Get item_key from "
            "search_zotero or get_zotero_collection_items ('Zotero Key'). Give pdf_url (arXiv "
            "/abs/ links are converted to /pdf/) or file_path (a path visible to the MCP server, "
            "not the user's own computer). Skips items that already have a PDF unless force=true."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "item_key": {"type": "string", "description": "Zotero key of the parent item"},
                "pdf_url": {"type": "string", "description": "http(s) URL of the PDF"},
                "file_path": {"type": "string", "description": "PDF path on the MCP server's filesystem"},
                "filename": {
                    "type": "string",
                    "description": "Attachment file name (default: derived from the item title)",
                },
                "force": {
                    "type": "boolean",
                    "description": "Attach even if the item already has a PDF (default: false)",
                    "default": False,
                },
            },
            "required": ["item_key"],
        },
    ),
    Tool(
        name="export_zotero_citations",
        description=(
            "Have Zotero format references from the user's library for a write-up. Give "
            "item_keys (from search_zotero / get_zotero_collection_items 'Zotero Key', max 50) "
            "OR collection_name. format: 'bib' (formatted bibliography, default), 'citation' "
            "(in-text citations), 'bibtex', 'biblatex', 'ris', or 'csljson'. style is a CSL "
            "style id from the Zotero Style Repository (default 'apa'; e.g. 'ieee', "
            "'chicago-author-date', 'modern-language-association', "
            "'association-for-computing-machinery') and applies to bib/citation only. Read-only."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "item_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 50,
                    "description": "Zotero item keys (8 characters, e.g. 'ABCD2345'); max 50",
                },
                "collection_name": {
                    "type": "string",
                    "description": "Name of a Zotero collection to export instead of item_keys",
                },
                "format": {
                    "type": "string",
                    "enum": ["bib", "citation", "bibtex", "biblatex", "ris", "csljson"],
                    "description": "Output format (default: bib)",
                    "default": "bib",
                },
                "style": {
                    "type": "string",
                    "description": "CSL style id for bib/citation (default: apa)",
                    "default": "apa",
                },
                "locale": {
                    "type": "string",
                    "description": "Citation locale for bib/citation (default: en-US)",
                    "default": "en-US",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max items when exporting a collection (default: 50, max: 100)",
                    "default": 50,
                },
            },
        },
    ),
    Tool(
        name="get_zotero_annotations",
        description=(
            "Read the user's own highlights, underlines, and comments on a Zotero item's PDF/EPUB/"
            "snapshot attachments, in reading order and grouped by attachment. Each annotation "
            "gives type, highlighted text, the user's comment, page label, color, and tags. "
            "item_key may be the parent item or one attachment ('Zotero Key' from search_zotero)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "item_key": {"type": "string", "description": "Zotero key of a parent item or an attachment"},
                "limit": {
                    "type": "integer",
                    "description": "Maximum annotations to return across all attachments (default: 200, max: 1000)",
                    "default": 200,
                },
            },
            "required": ["item_key"],
        },
    ),
    Tool(
        name="get_zotero_notes",
        description=(
            "Read the user's notes attached to a Zotero item, as plain text (HTML stripped). "
            "item_key may be a parent item, one of its attachments (notes of the parent are "
            "returned), or a note itself."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "item_key": {"type": "string", "description": "Zotero key of a parent item, attachment, or note"},
            },
            "required": ["item_key"],
        },
    ),
    Tool(
        name="get_zotero_fulltext",
        description=(
            "Read the full text Zotero indexed for an item's attachment (PDF/EPUB/HTML), paged by "
            "characters. Full text exists only if Zotero desktop indexed the file and synced it; "
            "otherwise the tool says nothing is indexed. item_key may be the parent item (first "
            "indexed attachment is used) or a specific attachment. Page with offset/max_chars."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "item_key": {"type": "string", "description": "Zotero key of a parent item or an attachment"},
                "offset": {
                    "type": "integer",
                    "description": "Character offset to start reading from (default: 0)",
                    "default": 0,
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to return (default: 20000, max: 100000)",
                    "default": 20000,
                },
            },
            "required": ["item_key"],
        },
    ),
    Tool(
        name="add_zotero_note",
        description=(
            "Add a child note to an existing Zotero item. Get item_key from search_zotero or "
            "get_zotero_collection_items ('Zotero Key'). The note is plain text or simple Markdown "
            "(# headings, - / 1. lists, **bold**, *italic*, `code`, [text](https://...) links); "
            "it is HTML-escaped and stored as Zotero note HTML. Returns the new note's key."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "item_key": {"type": "string", "description": "Zotero key of the parent item"},
                "note": {"type": "string", "description": "Note text (plain text or simple Markdown)"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags to put on the note",
                },
            },
            "required": ["item_key", "note"],
        },
    ),
    Tool(
        name="update_zotero_item",
        description=(
            "Edit an existing Zotero item's fields, creators, or item type. Field names are Zotero "
            "field names (title, date, DOI, publicationTitle, abstractNote, extra, ...); unknown "
            "fields for the item's type are refused, not dropped. creators replaces the whole "
            "author list. Changing item_type drops fields the new type does not have and reports "
            "them. Fails cleanly if the item was changed elsewhere since it was read. Notes and "
            "attachments cannot be edited here."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "item_key": {"type": "string", "description": "Zotero key of the item to edit"},
                "fields": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Zotero field name -> new value (empty string clears a field)",
                },
                "creators": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Replacement author list, each 'Last, First'",
                },
                "item_type": {
                    "type": "string",
                    "description": "New Zotero item type (e.g. journalArticle, book, preprint)",
                },
            },
            "required": ["item_key"],
        },
    ),
    Tool(
        name="modify_zotero_collections",
        description=(
            "Add Zotero items to, or remove them from, a collection (matched by name, "
            "case-insensitive). With action=add the collection is created if missing unless "
            "create_if_missing=false. Items are not deleted by remove; they just leave the "
            "collection. Up to 50 item keys per call."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "item_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 50,
                    "description": "Zotero item keys (max 50)",
                },
                "collection_name": {"type": "string", "description": "Collection name"},
                "action": {"type": "string", "enum": ["add", "remove"], "description": "add or remove"},
                "create_if_missing": {
                    "type": "boolean",
                    "description": "For action=add: create the collection if it does not exist (default: true)",
                    "default": True,
                },
            },
            "required": ["item_keys", "collection_name", "action"],
        },
    ),
    Tool(
        name="modify_zotero_tags",
        description=(
            "Add and/or remove tags on Zotero items (exact, case-sensitive tag match). Give at "
            "least one of add or remove. Up to 50 item keys per call; reports per item."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "item_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 50,
                    "description": "Zotero item keys (max 50)",
                },
                "add": {"type": "array", "items": {"type": "string"}, "description": "Tags to add"},
                "remove": {"type": "array", "items": {"type": "string"}, "description": "Tags to remove"},
            },
            "required": ["item_keys"],
        },
    ),
    Tool(
        name="trash_zotero_item",
        description=(
            "Move Zotero items to the trash (recoverable with restore_zotero_item; nothing is "
            "permanently deleted). Get keys from search_zotero, list_unfiled_zotero_items or "
            "get_zotero_collection_items ('Zotero Key'). Child notes/attachments go to the trash "
            "with their parent. Reports each item's title so the user can confirm what moved."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "item_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 50,
                    "description": "Zotero item keys to move to the trash (max 50)",
                },
            },
            "required": ["item_keys"],
        },
    ),
    Tool(
        name="restore_zotero_item",
        description=(
            "Restore Zotero items from the trash to the library (their collections and child "
            "items come back with them). Get keys from list_zotero_trash."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "item_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 50,
                    "description": "Zotero item keys to restore from the trash (max 50)",
                },
            },
            "required": ["item_keys"],
        },
    ),
    Tool(
        name="list_zotero_trash",
        description="List items in the Zotero trash, most recently modified first (title, type, key, date modified).",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of items to return (default: 50, max: 100)",
                    "default": 50,
                },
            },
        },
    ),
    Tool(
        name="list_unfiled_zotero_items",
        description=(
            "List top-level Zotero items that are in no collection ('Unfiled Items'), newest "
            "first. Scans at most the 1000 most recently added top-level items and says so if "
            "that cap was hit. Trashed items are excluded unless include_trashed=true."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of unfiled items to return (default: 50, max: 100)",
                    "default": 50,
                },
                "include_trashed": {
                    "type": "boolean",
                    "description": "Also include unfiled items that are in the trash (default: false)",
                    "default": False,
                },
            },
        },
    ),
    Tool(
        name="advanced_search_zotero",
        description=(
            "Filtered search of the user's Zotero library (top-level items): quick-search text, "
            "tags, item types, sort order, paging. Give at least one of query, tags, item_types. "
            "Tag syntax per entry: 'a || b' = a OR b, '-a' = NOT a; separate entries are ANDed. "
            "item_types: listed types are ORed; or give exactly one '-type' to exclude it. "
            "Reports the total match count so you can page with start."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Quick-search text (phrase match)"},
                "qmode": {
                    "type": "string",
                    "enum": ["titleCreatorYear", "everything"],
                    "description": "titleCreatorYear (default) or everything (also all fields and full text)",
                    "default": "titleCreatorYear",
                },
                "tags": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Tag filters, ANDed; each may use 'a || b' (OR) or '-a' (NOT)",
                },
                "item_types": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Zotero item types to include (ORed), e.g. journalArticle, book; or one '-type' to exclude",
                },
                "sort": {
                    "type": "string",
                    "enum": ["dateAdded", "dateModified", "date", "title", "creator"],
                    "description": "Sort field (default: dateModified)",
                    "default": "dateModified",
                },
                "direction": {
                    "type": "string", "enum": ["asc", "desc"],
                    "description": "Sort direction (default: desc)", "default": "desc",
                },
                "include_trashed": {
                    "type": "boolean", "description": "Include items in the trash (default: false)", "default": False,
                },
                "limit": {"type": "integer", "description": "Results per page (default: 25, max: 100)", "default": 25},
                "start": {"type": "integer", "description": "Offset of the first result (default: 0)", "default": 0},
            },
        },
    ),
    Tool(
        name="get_zotero_recent_changes",
        description=(
            "What changed in the user's Zotero library. Without since_version: the current library "
            "version and the most recently modified items. With since_version (a version returned "
            "earlier): items and collections changed since then, items/collections deleted since "
            "then, and the new library version to pass next time."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "since_version": {"type": "integer", "description": "Library version from a previous call"},
                "limit": {"type": "integer", "description": "Items to list (default: 25, max: 100)", "default": 25},
            },
        },
    ),
    Tool(
        name="manage_zotero_collection",
        description=(
            "Create, rename, or move a Zotero collection (no deletion). create: collection_name is "
            "the new name, optional parent_collection. rename: collection_name -> new_name. move: "
            "collection_name under parent_collection ('' = make top-level). Collections may be "
            "named or given by key; refuses duplicate sibling names and moves into its own subtree."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "rename", "move"]},
                "collection_name": {
                    "type": "string",
                    "description": "Existing collection (name or key) for rename/move; the new name for create",
                },
                "new_name": {"type": "string", "description": "New name (rename only)"},
                "parent_collection": {
                    "type": "string",
                    "description": "Parent collection name or key (create: optional; move: required, '' = top level)",
                },
            },
            "required": ["action", "collection_name"],
        },
    ),
    Tool(
        name="get_zotero_library_stats",
        description=(
            "Overview of the user's Zotero library: item, attachment, note and trash counts, items "
            "per collection, top tags, and item-type breakdown (from a scan of up to 1000 items)."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="find_zotero_duplicates",
        description=(
            "Report likely duplicate items in the user's Zotero library, grouped by DOI, ISBN, or "
            "normalized title + year (scans up to 2000 top-level items). Report only: merging is "
            "done in Zotero desktop's Duplicate Items pane (the Web API has no merge)."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="list_zotero_tags",
        description="List the tags in the user's Zotero library with item counts, most used first.",
        inputSchema={
            "type": "object",
            "properties": {
                "filter": {"type": "string", "description": "Only tags containing this text (case-insensitive)"},
                "limit": {"type": "integer", "description": "Maximum tags (default: 100, max: 500)", "default": 100},
            },
        },
    ),
    Tool(
        name="get_index_status",
        description=(
            "Status of the local thin-client search index: live/packed sections, "
            "per-leg latency metrics, dense-vector coverage, manifest metadata, "
            "and any running section-unpack jobs."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="list_personas",
        description=(
            "List available index personas (hot-section profiles) and which "
            "sections are currently live vs cold (packed) in the local index."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="request_section_unpack",
        description=(
            "Unpack a cold (packed) section of the local index in the background "
            "so it becomes searchable. Returns immediately; poll get_index_status "
            "for completion (large sections can take minutes to hours). The index "
            "hot-reloads automatically when the unpack finishes."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "section": {"type": "string",
                            "description": "Section name (see list_personas)"},
            },
            "required": ["section"],
        },
    ),
    Tool(
        name="reload_index",
        description=(
            "Hot-reload the local thin-client index from disk (zero-downtime swap "
            "after a rebuild, unpack, or migration). In-flight queries finish on "
            "the old index."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
]


_tool_definitions_cache: list[Tool] | None = None


async def get_tool_definitions() -> list[Tool]:
    """Return tool definitions with the item_type enum populated from the Zotero API.

    On first call, fetches all valid item types from https://api.zotero.org/itemTypes
    (no auth required) and patches the item_type property in save_to_zotero
    with a live enum. Result is cached for the process lifetime.
    Falls back to TOOL_DEFINITIONS with a plain string type if the API is unavailable.
    """
    global _tool_definitions_cache
    if _tool_definitions_cache is not None:
        return _tool_definitions_cache

    item_types: list[str] = await asyncio.get_event_loop().run_in_executor(
        None, fetch_zotero_item_types
    )

    if not item_types:
        _tool_definitions_cache = TOOL_DEFINITIONS
        return _tool_definitions_cache

    dynamic_item_type = {
        "type": "string",
        "enum": item_types,
        "description": (
            f"Any valid Zotero item type ({len(item_types)} types fetched live from "
            "https://api.zotero.org/itemTypes). "
            "E.g. 'journalArticle', 'computerProgram', 'thesis', 'blogPost'. "
            "When given, it overrides the type looked up from the DOI; omit it to keep that type "
            "(manual saves without a DOI default to 'document')."
        ),
    }

    patched: list[Tool] = []
    for tool in TOOL_DEFINITIONS:
        if tool.name == "save_to_zotero":
            props = {**tool.inputSchema["properties"], "item_type": dynamic_item_type}
            patched.append(Tool(
                name=tool.name,
                description=tool.description,
                inputSchema={**tool.inputSchema, "properties": props},
            ))
        else:
            patched.append(tool)

    _tool_definitions_cache = patched
    return _tool_definitions_cache


async def handle_tool_call(
    name: str,
    arguments: dict[str, Any],
) -> list[TextContent]:
    """Dispatch a tool call by name and record its latency/success metric.

    Handler exceptions are caught and returned as an error ``TextContent``.
    """
    start_time = time.time()
    success = True
    ids_holder: list[str] = []
    ids_token = _metric_ids_var.set(ids_holder)
    try:
        result = await _dispatch_tool(name, arguments)
        return result
    except Exception as e:
        success = False
        logger.error("Tool %s failed: %s", name, e, exc_info=True)
        return [TextContent(type="text", text=f"Error in {name}: {str(e)}")]
    finally:
        _metric_ids_var.reset(ids_token)
        _record_metric(name, time.time() - start_time, success, ids=ids_holder or None)


_unpack_jobs: dict[str, dict] = {}
_unpack_jobs_lock = None


def _jobs_lock():
    global _unpack_jobs_lock
    if _unpack_jobs_lock is None:
        import threading
        _unpack_jobs_lock = threading.Lock()
    return _unpack_jobs_lock


def _require_thinclient():
    tc = _get_thinclient_retriever()
    if tc is None:
        return None, [TextContent(type="text", text=(
            "The local thin-client index is not active "
            "(SFU_SEARCH_BACKEND must be 'thinclient'; the OpenSearch backend was "
            "decommissioned 2026-06-11)."))]
    return tc, None


async def _handle_get_index_status(args: dict[str, Any]) -> list[TextContent]:
    tc, err = _require_thinclient()
    if err:
        return err
    from lib.thinclient.packer import status as pack_status

    def _collect() -> dict:
        out = {"metrics": tc.metrics(), "pack": pack_status(tc.root)}
        with _jobs_lock():
            out["unpack_jobs"] = {k: dict(v) for k, v in _unpack_jobs.items()}
        return out

    out = await asyncio.get_event_loop().run_in_executor(None, _collect)
    return [TextContent(type="text", text=json.dumps(out, indent=2, default=str))]


async def _handle_list_personas(args: dict[str, Any]) -> list[TextContent]:
    from lib.thinclient.sections import (ERA_BOUNDARY_YEAR, PERSONAS,
                                         SECTION_NAMES, SUBSECTION_NAMES)
    tc = _get_thinclient_retriever()
    live = []
    if tc is not None:
        try:
            live = tc.live_sections()
        except Exception:
            pass
    known = SUBSECTION_NAMES if any("__" in s for s in live) else SECTION_NAMES
    out = {
        "personas": PERSONAS,
        "sections": SECTION_NAMES,
        "era_subsections": SUBSECTION_NAMES,
        "era_boundary_year": ERA_BOUNDARY_YEAR,
        "live_sections": live,
        "cold_sections": [s for s in known if s not in live],
        "active_profile": _get_config().active_profile,
    }
    return [TextContent(type="text", text=json.dumps(out, indent=2))]


async def _handle_request_section_unpack(args: dict[str, Any]) -> list[TextContent]:
    tc, err = _require_thinclient()
    if err:
        return err
    from lib.thinclient.sections import SECTION_NAMES, SUBSECTION_NAMES
    section = args.get("section", "")
    valid = SUBSECTION_NAMES + SECTION_NAMES
    if section not in valid:
        return [TextContent(type="text", text=(
            f"Unknown section '{section}'. Valid: {', '.join(valid)}"))]
    if section in tc.live_sections():
        return [TextContent(type="text", text=f"Section '{section}' is already live.")]
    with _jobs_lock():
        job = _unpack_jobs.get(section)
        if job and job.get("state") == "running":
            return [TextContent(type="text", text=(
                f"Unpack of '{section}' already running (started {job['started']})."))]
        _unpack_jobs[section] = {"state": "running",
                                 "started": time.strftime("%Y-%m-%dT%H:%M:%S")}

    def _run() -> None:
        try:
            from lib.thinclient.packer import unpack_section
            info = unpack_section(tc.root, section)
            tc.reload()
            with _jobs_lock():
                _unpack_jobs[section].update(state="done", info=info)
            logger.info("section %s unpacked and index reloaded", section)
        except Exception as exc:
            with _jobs_lock():
                _unpack_jobs[section].update(state="failed", error=str(exc))
            logger.error("section %s unpack failed: %s", section, exc, exc_info=True)

    import threading
    threading.Thread(target=_run, daemon=True, name=f"unpack-{section}").start()
    return [TextContent(type="text", text=(
        f"Unpacking '{section}' in the background (large sections can take a "
        "while). Poll get_index_status; the index hot-reloads on completion."))]


async def _handle_reload_index(args: dict[str, Any]) -> list[TextContent]:
    tc, err = _require_thinclient()
    if err:
        return err
    info = await asyncio.get_event_loop().run_in_executor(None, tc.reload)
    return [TextContent(type="text", text=json.dumps({"reloaded": info}, indent=2))]


async def _dispatch_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    dispatch = {
        "search_academic": _handle_search_academic,
        "search_by_author": _handle_search_by_author,
        "search_by_doi": _handle_search_by_doi,
        "search_by_topic": _handle_search_by_topic,
        "get_citations": _handle_get_citations,
        "get_references": _handle_get_references,
        "get_paper_summary": _handle_get_paper_summary,
        "find_open_access": _handle_find_open_access,
        "get_full_text_link": _handle_get_full_text_link,
        "browse_library_databases": _handle_browse_library_databases,
        "check_library_access": _handle_check_library_access,
        "browse_sfu_databases": _handle_browse_library_databases,
        "check_sfu_access": _handle_check_library_access,
        "search_biomedical": _handle_search_biomedical,
        "save_to_zotero": _handle_save_to_zotero,
        "batch_save_to_zotero": _handle_batch_save_to_zotero,
        "list_zotero_collections": _handle_list_zotero_collections,
        "search_zotero": _handle_search_zotero,
        "get_zotero_collection_items": _handle_get_zotero_collection_items,
        "get_zotero_status": _handle_get_zotero_status,
        "attach_pdf_to_zotero": _handle_attach_pdf_to_zotero,
        "export_zotero_citations": _handle_export_zotero_citations,
        "get_zotero_annotations": _handle_get_zotero_annotations,
        "get_zotero_notes": _handle_get_zotero_notes,
        "get_zotero_fulltext": _handle_get_zotero_fulltext,
        "add_zotero_note": _handle_add_zotero_note,
        "update_zotero_item": _handle_update_zotero_item,
        "modify_zotero_collections": _handle_modify_zotero_collections,
        "modify_zotero_tags": _handle_modify_zotero_tags,
        "trash_zotero_item": _handle_trash_zotero_item,
        "restore_zotero_item": _handle_restore_zotero_item,
        "list_zotero_trash": _handle_list_zotero_trash,
        "list_unfiled_zotero_items": _handle_list_unfiled_zotero_items,
        "advanced_search_zotero": _handle_advanced_search_zotero,
        "get_zotero_recent_changes": _handle_get_zotero_recent_changes,
        "manage_zotero_collection": _handle_manage_zotero_collection,
        "get_zotero_library_stats": _handle_get_zotero_library_stats,
        "find_zotero_duplicates": _handle_find_zotero_duplicates,
        "list_zotero_tags": _handle_list_zotero_tags,
        "get_index_status": _handle_get_index_status,
        "list_personas": _handle_list_personas,
        "request_section_unpack": _handle_request_section_unpack,
        "reload_index": _handle_reload_index,
    }
    handler = dispatch.get(name)
    if handler is None:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    return await handler(arguments)


def _openalex_unavailable_reason() -> str | None:
    """Return a human-readable reason string if OpenAlex cannot serve requests, else None."""
    oa = _get_openalex()
    budget = oa.budget_status()
    if isinstance(budget, dict) and budget.get("exhausted") is True:
        return (
            f"OpenAlex daily budget exhausted ({budget['calls_today']:,}/{budget['daily_limit']:,} calls). "
            "Budget resets at local midnight."
        )
    if getattr(oa, "circuit_open", False) is True:
        return "OpenAlex is temporarily unavailable (circuit breaker open after repeated failures)."
    return None


async def _s2_fallback(query: str, limit: int, reason: str) -> list[TextContent]:
    """Search Semantic Scholar and return results with a degradation notice."""
    logger.warning("OpenAlex fallback to S2: %s", reason)
    async with _request_semaphore:
        papers = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _get_s2().search_papers(query, limit=limit),
        )
    notice = f"[Note: {reason} Showing results from Semantic Scholar (reduced coverage).]\n\n"
    _note_result_ids(papers)
    if not papers:
        return [TextContent(type="text", text=notice + "No results found.")]
    return [TextContent(
        type="text",
        text=notice + format_semantic_scholar_papers(papers, query),
    )]


async def _handle_search_academic(args: dict) -> list[TextContent]:
    query = sanitize_search_query(args.get("query", ""))
    if not query:
        return [TextContent(type="text", text="Empty search query.")]
    limit = max(1, min(args.get("limit", 10), 50))
    page = max(args.get("page", 1), 1)

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
    work_type = args.get("type", "")
    if work_type:
        filters["type"] = work_type

    if _get_features().get("federated_search_enabled"):
        from lib.federated_search import detect_subject
        subject_hint = detect_subject(query)
        prefer_local = bool(args.get("prefer_local"))
        t0 = time.monotonic()
        router = _get_federated_router()
        fetch_k = _retrieval_top_k(limit)
        async with _request_semaphore:
            results = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: router.search(
                    query, filters, top_k=fetch_k,
                    subject_hint=subject_hint, prefer_local=prefer_local,
                ),
            )
        if results:
            _cache_works(results)
            results = _maybe_rerank(results, query, limit)
        _log_query(query, results, (time.monotonic() - t0) * 1000, "search_academic_federated")
        _note_result_ids(results)
        data = {"results": results, "meta": {"count": len(results)}}
        text = format_openalex_results(data, query)
        if getattr(router, "last_live_fallback", False):
            text = "[Note: " + _LIVE_FALLBACK_NOTE + "]\n\n" + text
        if getattr(router, "last_degraded", False):
            text = (
                "[Note: the local search index is currently unavailable; "
                "results may be incomplete.]\n\n" + text
            )
        if _thinclient_retriever is not None:
            try:
                hint = _thinclient_retriever.cold_section_hint(query)
            except Exception:
                hint = None
            if hint:
                text = (
                    f"[Note: this query maps to the '{hint}' section, which is "
                    f"cold (packed) in the local index — local results may be "
                    f"incomplete. request_section_unpack('{hint}') brings it "
                    "live.]\n\n" + text
                )
        return [TextContent(type="text", text=text)]

    unavailable = _openalex_unavailable_reason()
    if unavailable:
        return await _s2_fallback(query, limit, unavailable)

    async with _request_semaphore:
        data = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _get_openalex().search_works(
                query, filters=filters, per_page=_retrieval_top_k(limit), page=page
            ),
        )

    if not data.get("results"):
        fallback_reason = _openalex_unavailable_reason()
        if fallback_reason or _get_openalex().circuit_open:
            reason = fallback_reason or "OpenAlex returned no results (possible outage)."
            return await _s2_fallback(query, limit, reason)

    t0 = time.monotonic()
    if data.get("results"):
        _cache_works(data["results"])
        data["results"] = _maybe_rerank(data["results"], query, limit)
    _log_query(query, data.get("results", []), (time.monotonic() - t0) * 1000, "search_academic")
    _note_result_ids(data.get("results"))
    return [TextContent(type="text", text=format_openalex_results(data, query))]


async def search_academic_structured(args: dict) -> dict:
    """Structured (JSON-friendly) variant of search_academic for the web GUI.

    Mirrors _handle_search_academic's retrieval logic but returns
    {"results": [<work dict>...], "meta": {"count": N}, "notes": [str...]}
    instead of formatted text, so the GUI can render result cards. The MCP text
    tool above is intentionally left untouched.
    """
    query = sanitize_search_query(args.get("query", ""))
    if not query:
        return {"results": [], "meta": {"count": 0}, "notes": ["Empty search query."]}
    limit = max(1, min(args.get("limit", 10), 50))
    page = max(args.get("page", 1), 1)

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
    work_type = args.get("type", "")
    if work_type:
        filters["type"] = work_type

    notes: list[str] = []

    if _get_features().get("federated_search_enabled"):
        from lib.federated_search import detect_subject
        subject_hint = detect_subject(query)
        prefer_local = bool(args.get("prefer_local"))
        t0 = time.monotonic()
        router = _get_federated_router()
        fetch_k = _retrieval_top_k(limit)
        _tc = _get_thinclient_retriever()
        _leg_before = _tc._leg_snapshot_for_log() if _tc is not None else {}
        async with _request_semaphore:
            results = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: router.search(
                    query, filters, top_k=fetch_k,
                    subject_hint=subject_hint, prefer_local=prefer_local,
                ),
            )
        if results:
            _cache_works(results)
            results = _maybe_rerank(results, query, limit)
        total_ms = (time.monotonic() - t0) * 1000
        _log_query(query, results, total_ms, "search_academic_gui")
        try:
            from lib.serve_query_log import log_serve_query
            leg_ms = (_tc._leg_delta_for_log(_leg_before)
                      if _tc is not None else {})
            leg_ms["total"] = round(total_ms, 2)
            log_serve_query(
                query=query, k=fetch_k, mode="federated",
                backend=(_tc._splade_backend if _tc is not None else ""),
                federation=(_tc._seismic_federation_mode()
                            if _tc is not None else ""),
                leg_ms=leg_ms,
                n_results=len(results),
                result_oaids=[r.get("openalex_id") or r.get("doi") or ""
                              for r in results[:fetch_k]],
                filtered=bool(filters),
            )
        except Exception:
            logger.debug("serve query-log emit failed (non-fatal)")
        if getattr(router, "last_live_fallback", False):
            notes.append(_LIVE_FALLBACK_NOTE)
        if getattr(router, "last_degraded", False):
            notes.append("The local search index is currently unavailable; results may be incomplete.")

        if _thinclient_retriever is not None:
            try:
                hint = _thinclient_retriever.cold_section_hint(query)
            except Exception:
                hint = None
            if hint:
                notes.append(
                    f"This query maps to the '{hint}' section, which is cold (packed) "
                    f"in the local index — local results may be incomplete.")
        return {"results": results[:limit], "meta": {"count": len(results)}, "notes": notes}

    unavailable = _openalex_unavailable_reason()
    if unavailable:
        return await _s2_fallback_structured(query, limit, unavailable)

    async with _request_semaphore:
        data = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _get_openalex().search_works(
                query, filters=filters, per_page=_retrieval_top_k(limit), page=page
            ),
        )
    if not data.get("results"):
        fallback_reason = _openalex_unavailable_reason()
        if fallback_reason or _get_openalex().circuit_open:
            reason = fallback_reason or "OpenAlex returned no results (possible outage)."
            return await _s2_fallback_structured(query, limit, reason)

    t0 = time.monotonic()
    results = data.get("results", [])
    if results:
        _cache_works(results)
        results = _maybe_rerank(results, query, limit)
    _log_query(query, results, (time.monotonic() - t0) * 1000, "search_academic_gui")
    return {"results": results[:limit], "meta": {"count": data.get("meta", {}).get("count", len(results))}, "notes": notes}


async def _s2_fallback_structured(query: str, limit: int, reason: str) -> dict:
    """Semantic Scholar fallback returning normalized dicts for the GUI."""
    logger.warning("OpenAlex fallback to S2 (gui): %s", reason)
    try:
        async with _request_semaphore:
            papers = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _get_s2().search_papers(query, limit=limit))
    except Exception as exc:  # pragma: no cover
        logger.warning("S2 structured fallback failed: %s", exc)
        papers = []
    results = [{
        "title": p.get("title", ""),
        "authors": p.get("authors", []),
        "year": p.get("year"),
        "doi": p.get("doi", ""),
        "cited_by_count": p.get("citation_count", 0),
        "tldr": p.get("tldr", ""),
        "abstract": p.get("abstract", ""),
        "is_oa": bool(p.get("open_access_pdf")),
        "oa_url": p.get("open_access_pdf", ""),
        "source": p.get("venue", ""),
        "type": "article",
    } for p in (papers or [])]
    return {
        "results": results,
        "meta": {"count": len(results)},
        "notes": [f"{reason} Showing results from Semantic Scholar (reduced coverage)."],
    }


async def _handle_search_by_author(args: dict) -> list[TextContent]:
    author = args.get("author", "").strip()
    if not author:
        return [TextContent(type="text", text="No author name provided.")]
    limit = max(1, min(args.get("limit", 10), 50))

    async with _request_semaphore:
        data = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _get_openalex().search_works(
                query=author,
                filters={"authorships.author.display_name.search": author},
                per_page=limit,
            ),
        )

    if data.get("results"):
        _cache_works(data["results"])
    _note_result_ids(data.get("results"))
    return [TextContent(type="text", text=format_openalex_results(data, f"author:{author}"))]


async def _handle_search_by_doi(args: dict) -> list[TextContent]:
    doi = args.get("doi", "").strip()
    if not doi:
        return [TextContent(type="text", text="No DOI provided.")]
    _note_doc_id(doi)

    work = _lookup_work(doi)
    if not work:
        async with _request_semaphore:
            work = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _get_openalex().get_work_by_doi(doi),
            )

    if not work:
        from lib.openalex import fetch_crossref_work
        async with _request_semaphore:
            work = await asyncio.get_event_loop().run_in_executor(
                None, lambda: fetch_crossref_work(doi)
            )

    if not work:
        return [TextContent(type="text", text=f"No record found for DOI: {doi}")]

    _cache_works([work])
    data = {"results": [work], "meta": {"count": 1}}
    return [TextContent(type="text", text=format_openalex_results(data, doi))]


async def _handle_search_by_topic(args: dict) -> list[TextContent]:
    topic = args.get("topic", "").strip()
    if not topic:
        return [TextContent(type="text", text="No topic provided.")]
    limit = max(1, min(args.get("limit", 10), 50))

    unavailable = _openalex_unavailable_reason()
    if unavailable:
        return await _s2_fallback(topic, limit, unavailable)

    filters: dict[str, str] = {}
    if args.get("open_access_only"):
        filters["open_access.is_oa"] = "true"

    async with _request_semaphore:
        data = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _get_openalex().search_works(
                query=topic,
                filters=filters or None,
                sort="cited_by_count:desc",
                per_page=limit,
            ),
        )

    if not data.get("results"):
        fallback_reason = _openalex_unavailable_reason()
        if fallback_reason or _get_openalex().circuit_open:
            reason = fallback_reason or "OpenAlex returned no results (possible outage)."
            return await _s2_fallback(topic, limit, reason)

    t0 = time.monotonic()
    if data.get("results"):
        _cache_works(data["results"])
        data["results"] = _maybe_rerank(data["results"], topic, limit)
    _log_query(topic, data.get("results", []), (time.monotonic() - t0) * 1000, "search_by_topic")
    _note_result_ids(data.get("results"))
    return [TextContent(type="text", text=format_openalex_results(data, topic))]


async def _handle_get_citations(args: dict) -> list[TextContent]:
    doi = args.get("doi", "").strip()
    if not doi:
        return [TextContent(type="text", text="No DOI provided.")]
    _note_doc_id(doi)
    limit = max(1, min(args.get("limit", 20), 100))

    async with _request_semaphore:
        papers = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _get_s2().get_citations(f"DOI:{doi}", limit=limit),
        )

    if not papers:
        return [TextContent(type="text", text=f"No citing papers found for DOI: {doi}")]
    return [TextContent(type="text", text=format_semantic_scholar_papers(papers, f"Papers citing {doi}"))]


async def _handle_get_references(args: dict) -> list[TextContent]:
    doi = args.get("doi", "").strip()
    if not doi:
        return [TextContent(type="text", text="No DOI provided.")]
    _note_doc_id(doi)
    limit = max(1, min(args.get("limit", 20), 100))

    async with _request_semaphore:
        papers = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _get_s2().get_references(f"DOI:{doi}", limit=limit),
        )

    if not papers:
        return [TextContent(type="text", text=f"No references found for DOI: {doi}")]
    return [TextContent(type="text", text=format_semantic_scholar_papers(papers, f"References of {doi}"))]


async def _handle_get_paper_summary(args: dict) -> list[TextContent]:
    doi = args.get("doi", "").strip()
    if not doi:
        return [TextContent(type="text", text="No DOI provided.")]
    _note_doc_id(doi)

    async with _request_semaphore:
        tldr = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _get_s2().get_tldr(f"DOI:{doi}"),
        )

    if not tldr:
        return [TextContent(type="text", text=f"No TLDR available for DOI: {doi}")]
    return [TextContent(type="text", text=f"TLDR for {doi}:\n\n{tldr}")]


async def _handle_find_open_access(args: dict) -> list[TextContent]:
    doi = args.get("doi", "").strip()
    if not doi:
        return [TextContent(type="text", text="No DOI provided.")]
    _note_doc_id(doi)

    from lib.openalex import normalize_doi
    doi_norm = normalize_doi(doi)

    resolver = _get_resolver()

    async with _request_semaphore:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: resolver._check_unpaywall(doi_norm),
        )

    doi_url = f"https://doi.org/{doi_norm}"
    if result:
        output = [
            "Open Access: AVAILABLE",
            f"URL: {result['url']}",
        ]
        if result.get("version"):
            output.append(f"Version: {result['version']}")
        if result.get("host_type"):
            output.append(f"Host: {result['host_type']}")
        output.append(f"DOI: {doi_url}")
    else:
        work = _lookup_work(doi_norm)
        if work and work.get("is_oa") and work.get("oa_url"):
            output = [
                "Open Access: AVAILABLE (via OpenAlex)",
                f"URL: {work['oa_url']}",
                f"DOI: {doi_url}",
            ]
        else:
            output = [
                "Open Access: NOT FOUND",
                f"No freely available copy found via Unpaywall for {doi}.",
                f"DOI: {doi_url}",
            ]

    return [TextContent(type="text", text="\n".join(output))]


async def _handle_get_full_text_link(args: dict) -> list[TextContent]:
    doi = args.get("doi", "").strip()
    if not doi:
        return [TextContent(type="text", text="No DOI provided.")]
    _note_doc_id(doi)

    from lib.openalex import normalize_doi
    doi_norm = normalize_doi(doi)

    work = _lookup_work(doi_norm)
    if not work:
        async with _request_semaphore:
            work = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _get_openalex().get_work_by_doi(doi_norm),
            )
        if work:
            _cache_works([work])

    is_oa = (work or {}).get("is_oa", False)
    oa_url = (work or {}).get("oa_url", "")
    publisher = (work or {}).get("publisher", "")
    source_url = (work or {}).get("oa_url", "") or f"https://doi.org/{doi_norm}"

    async with _request_semaphore:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _get_resolver().resolve(
                doi=doi_norm,
                source_url=source_url,
                publisher=publisher,
                is_oa=is_oa,
                oa_url=oa_url,
            ),
        )

    access_labels = {
        "oa": "Open Access",
        "unpaywall": "Open Access (Unpaywall)",
        "ezproxy": "Duck Library Subscription (EZProxy login required)",
        "direct": "Duck Library Subscription (direct access)",
        "doi_fallback": "DOI link (may require personal/institutional access)",
    }

    output = [
        "=" * 50,
        "FULL TEXT ACCESS",
        "=" * 50,
        f"Access type: {access_labels.get(result['access_type'], result['access_type'])}",
        f"URL: {result['access_url']}",
    ]
    if result.get("db_name"):
        output.append(f"Database: {result['db_name']}")
    if result.get("proxy_needed"):
        output.append("Note: Click the URL above and log in with your library credentials.")
    if result.get("doi_url") and result["doi_url"] != result["access_url"]:
        output.append(f"DOI fallback: {result['doi_url']}")

    return [TextContent(type="text", text="\n".join(output))]


async def _handle_browse_library_databases(args: dict) -> list[TextContent]:
    query = args.get("query", "")
    subject = args.get("subject", "")
    content_type = args.get("content_type", "")
    free_only = args.get("free_only", False)
    limit = max(1, min(args.get("limit", 20), 100))

    registry = _get_registry()
    async with _request_semaphore:
        docs = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: registry.search(
                query=query,
                subject=subject,
                content_type=content_type,
                free_only=free_only,
                limit=limit,
            ),
        )

    return [TextContent(type="text", text=format_library_databases_list(docs, query))]


async def _handle_check_library_access(args: dict) -> list[TextContent]:
    name = args.get("name", "").strip()
    if not name:
        return [TextContent(type="text", text="No database name provided.")]

    registry = _get_registry()
    async with _request_semaphore:
        docs = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: registry.search(query=name, limit=5),
        )

    if not docs:
        output = [
            f"Duck Library Access Check: '{name}'",
            "Result: NOT FOUND in the library database registry.",
            "The library may not subscribe to this resource, or it may be listed under a different name.",
        ]
    else:
        output = [
            f"Duck Library Access Check: '{name}'",
            f"Result: FOUND — {len(docs)} matching database(s)\n",
        ]
        for doc in docs:
            output.append(format_library_database(doc))
            output.append("")

    return [TextContent(type="text", text="\n".join(output))]


async def _handle_search_biomedical(args: dict) -> list[TextContent]:
    if not _get_features().get("europe_pmc_enabled", False):
        args_copy = dict(args)
        args_copy["query"] = args.get("query", "")
        return await _handle_search_academic(args_copy)

    query = args.get("query", "").strip()
    if not query:
        return [TextContent(type="text", text="No query provided.")]
    limit = max(1, min(args.get("limit", 10), 25))

    pmc_ids: list[str] = []
    async with _request_semaphore:
        data = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _fetch_europe_pmc(query, limit, ids_out=pmc_ids),
        )
    _note_metric_ids(pmc_ids)

    return [TextContent(type="text", text=data)]


def _fetch_europe_pmc(query: str, limit: int, ids_out: list[str] | None = None) -> str:
    try:
        resp = requests.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": query, "resultType": "core", "format": "json", "pageSize": limit},
            headers={"User-Agent": "SFULibraryMCP/1.0"},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        results = payload.get("resultList", {}).get("result", [])
        if not results:
            return "No results found in Europe PMC."
        total = payload.get("hitCount", len(results))
        if ids_out is not None:
            ids_out.extend(
                (r.get("doi") or (f"pmid:{r['pmid']}" if r.get("pmid") else ""))
                for r in results[:_METRIC_IDS_TOP_K])
        lines = [f"Europe PMC: {total:,} results for '{query}'\n", "=" * 60 + "\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "No title")
            authors = r.get("authorString", "")
            year = r.get("pubYear", "")
            doi = r.get("doi", "")
            pmid = r.get("pmid", "")
            abstract = (r.get("abstractText", "") or "")[:200]
            lines.append(f"{i}. {title}\n")
            if authors:
                lines.append(f"   Authors: {authors[:100]}\n")
            if year:
                lines.append(f"   Year: {year}\n")
            if doi:
                lines.append(f"   DOI: {doi}\n")
            if pmid:
                lines.append(f"   PMID: {pmid}\n")
            if abstract:
                lines.append(f"   Abstract: {abstract}...\n")
            lines.append("\n")
        return "".join(lines)
    except Exception as e:
        logger.error("Europe PMC request failed: %s", e)
        return f"Europe PMC search failed: {e}"


async def _fetch_work_metadata(doi: str) -> dict | None:
    """Fetch work metadata by DOI using cache → OpenAlex → CrossRef."""
    from lib.openalex import normalize_doi
    doi_norm = normalize_doi(doi)
    work = _lookup_work(doi_norm) or _lookup_work(doi)
    if work:
        return work

    work = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: _get_openalex().get_work_by_doi(doi_norm),
    )
    if work:
        _cache_works([work])
        return work

    from lib.openalex import fetch_crossref_work
    work = await asyncio.get_event_loop().run_in_executor(
        None, lambda: fetch_crossref_work(doi_norm)
    )
    if work:
        _cache_works([work])
    return work


_KNOWN_RESOURCE_TYPES: dict[str, str] = {
    "journalArticle": "article",   "article": "article",
    "magazineArticle": "magazine_article",   "magazine_article": "magazine_article",
    "newspaperArticle": "newspaper_article", "newspaper_article": "newspaper_article",
    "blogPost": "article",         "forumPost": "article",
    "book": "book",
    "bookSection": "book_section", "book_section": "book_section",
    "dictionaryEntry": "book_section", "encyclopediaArticle": "book_section",
    "conferencePaper": "conference_paper", "conference_paper": "conference_paper",
    "thesis": "thesis",
    "webpage": "webpage",
    "computerProgram": "software", "software": "software",
    "report": "report",
    "dataset": "dataset",
    "film": "film",
    "videoRecording": "video",     "video": "video",   "tvBroadcast": "video",
    "audioRecording": "audio",     "audio": "audio",
    "radioBroadcast": "audio",     "podcast": "audio",
    "patent": "patent",
    "presentation": "presentation",
    "document": "other",  "manuscript": "other", "letter": "other",
    "email": "other",     "interview": "other",  "instantMessage": "other",
    "hearing": "other",   "bill": "other",       "case": "other",
    "statute": "other",   "map": "other",        "artwork": "other",
    "other": "other",
}


def _resolve_resource_type(item_type: str) -> str:
    """Map any Zotero item type string to an internal formatting category.

    Uses the explicit mapping table for known types and keyword heuristics
    for any type returned by the Zotero API that isn't listed there.
    """
    if item_type in _KNOWN_RESOURCE_TYPES:
        return _KNOWN_RESOURCE_TYPES[item_type]
    lower = item_type.lower()
    if any(w in lower for w in ("article", "news", "blog", "forum", "post", "review")):
        return "article"
    if any(w in lower for w in ("book", "chapter", "encyclopedia", "dictionary", "section")):
        return "book"
    if any(w in lower for w in ("thesis", "dissertation")):
        return "thesis"
    if any(w in lower for w in ("conference", "proceedings", "symposium")):
        return "conference_paper"
    if any(w in lower for w in ("report", "manual", "brief", "technical", "whitepaper")):
        return "report"
    if any(w in lower for w in ("software", "program", "computer", "code", "app")):
        return "software"
    if any(w in lower for w in ("web", "page", "site", "online")):
        return "webpage"
    if any(w in lower for w in ("film", "movie", "cinema")):
        return "film"
    if any(w in lower for w in ("video", "tv", "television", "broadcast")):
        return "video"
    if any(w in lower for w in ("audio", "podcast", "radio", "music", "sound")):
        return "audio"
    if "patent" in lower:
        return "patent"
    if any(w in lower for w in ("presentation", "slide", "poster", "talk")):
        return "presentation"
    if any(w in lower for w in ("dataset", "data")):
        return "dataset"
    return "other"


def _build_manual_metadata(args: dict) -> dict:
    """Build a metadata dict from raw tool input fields (no DOI lookup needed)."""
    item_type = args.get("item_type", "document")
    resource_type = _resolve_resource_type(item_type)
    return {
        "title": args.get("title", ""),
        "authors": args.get("authors") or [],
        "creators": args.get("authors") or [],
        "editors": args.get("editors") or [],
        "date": args.get("year", ""),
        "source": args.get("journal", "") or args.get("source", ""),
        "publisher": args.get("publisher", ""),
        "doi": args.get("doi", ""),
        "isbn": args.get("isbn", ""),
        "issn": args.get("issn", ""),
        "volume": args.get("volume", ""),
        "issue": args.get("issue", ""),
        "pages": args.get("pages", ""),
        "spage": "",
        "epage": "",
        "resource_type": resource_type,
        "url": args.get("url", ""),
        "edition": args.get("edition", ""),
        "book_title": args.get("book_title", ""),
        "institution": args.get("institution", ""),
        "degree_type": args.get("degree_type", ""),
        "conference_name": args.get("conference_name", ""),
        "conference_location": args.get("conference_location", ""),
        "report_number": args.get("report_number", ""),
        "version": args.get("version", ""),
        "accessed_date": args.get("accessed_date", ""),
    }


async def _handle_save_to_zotero(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    doi = args.get("doi", "").strip()
    collection_name = args.get("collection_name", "")
    parent_collection = args.get("parent_collection", "")

    if doi:
        async with _request_semaphore:
            metadata = await _fetch_work_metadata(doi)
        if not metadata:
            return [TextContent(type="text", text=f"Could not retrieve metadata for DOI: {doi}")]
        metadata = await asyncio.get_event_loop().run_in_executor(
            None, enrich_metadata_from_crossref, metadata
        )
    elif args.get("title", "").strip():
        metadata = _build_manual_metadata(args)
    else:
        return [TextContent(type="text", text="Provide a DOI or at minimum a title to save to Zotero.")]

    requested_type = (args.get("item_type") or "").strip()
    if requested_type:
        valid_types = await asyncio.get_event_loop().run_in_executor(None, fetch_zotero_item_types)
        if valid_types and requested_type not in valid_types:
            return [TextContent(type="text", text=(
                f"'{requested_type}' is not a Zotero item type. Valid types: {', '.join(sorted(valid_types))}"
            ))]
        metadata["zotero_item_type"] = requested_type
    zot = _get_zotero_client()

    try:
        dup = zot.check_duplicate(metadata)
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero error during duplicate check: {e}")]

    if dup["is_duplicate"]:
        return [TextContent(type="text", text=(
            "=" * 50 + "\nALREADY IN ZOTERO\n" + "=" * 50 +
            f"\nThis item is already in your Zotero library ({dup['match_type']} match).\n"
            f"\nExisting item:\n{dup.get('existing_item_summary', 'N/A')}"
        ))]

    zotero_item = zot.metadata_to_zotero_item(metadata)
    collection_key = None
    if collection_name:
        try:
            parent_key = zot.find_or_create_collection(parent_collection) if parent_collection else None
            collection_key = zot.find_or_create_collection(collection_name, parent_key=parent_key)
        except ZoteroError as e:
            return [TextContent(type="text", text=f"Zotero collection error: {e}")]

    try:
        item_key = zot.create_item(zotero_item, collection_key)
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Failed to create Zotero item: {e}")]

    output = ["=" * 50, "SAVED TO ZOTERO", "=" * 50,
              f"\nTitle: {metadata.get('title', 'Unknown')}", f"Zotero Key: {item_key}"]
    if collection_name:
        output.append(f"Collection: {collection_name}")
    return [TextContent(type="text", text="\n".join(output))]


async def _handle_batch_save_to_zotero(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    dois = args.get("dois", [])[:20]
    collection_name = args.get("collection_name", "")
    parent_collection = args.get("parent_collection", "")

    if not dois:
        return [TextContent(type="text", text="No DOIs provided.")]

    zot = _get_zotero_client()
    collection_key = None
    if collection_name:
        try:
            parent_key = zot.find_or_create_collection(parent_collection) if parent_collection else None
            collection_key = zot.find_or_create_collection(collection_name, parent_key=parent_key)
        except ZoteroError as e:
            return [TextContent(type="text", text=f"Zotero collection error: {e}")]

    saved, skipped, failed = 0, 0, 0
    details = []

    for doi in dois:
        async with _request_semaphore:
            metadata = await _fetch_work_metadata(doi)
        if not metadata:
            details.append(f"  {doi}: FAILED — could not retrieve metadata")
            failed += 1
            continue

        metadata = await asyncio.get_event_loop().run_in_executor(
            None, enrich_metadata_from_crossref, metadata
        )
        title_short = metadata.get("title", "Unknown")[:60]

        try:
            dup = zot.check_duplicate(metadata)
        except ZoteroError:
            dup = {"is_duplicate": False}

        if dup["is_duplicate"]:
            details.append(f"  {title_short}: SKIPPED — already in Zotero ({dup['match_type']} match)")
            skipped += 1
            continue

        try:
            zot.create_item(zot.metadata_to_zotero_item(metadata), collection_key)
            details.append(f"  {title_short}: SAVED")
            saved += 1
        except ZoteroError as e:
            details.append(f"  {title_short}: FAILED — {e}")
            failed += 1

    output = [
        "=" * 50, "BATCH SAVE TO ZOTERO", "=" * 50,
        f"\nCollection: {collection_name or '(none)'}",
        f"Results: {saved} saved, {skipped} skipped, {failed} failed\n",
    ] + details
    return [TextContent(type="text", text="\n".join(output))]


async def _handle_list_zotero_collections(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    zot = _get_zotero_client()
    try:
        collections = zot.list_collections()
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero error: {e}")]

    if not collections:
        return [TextContent(type="text", text="No collections found in your Zotero library.")]

    output = ["=" * 50, f"ZOTERO COLLECTIONS ({len(collections)})", "=" * 50, ""]
    for c in collections:
        parent = f" (in: {c['parent_key']})" if c.get("parent_key") else ""
        output.append(f"  {c['name']} — {c['num_items']} items{parent}")
        output.append(f"    Key: {c['key']}")
    return [TextContent(type="text", text="\n".join(output))]


def _format_zotero_items(heading: str, items: list[dict], zot: ZoteroClient) -> list[TextContent]:
    output = ["=" * 50, heading, "=" * 50, ""]
    for i, item in enumerate(items, 1):
        output.append(f"--- Item {i} ---")
        output.append(zot.format_item_summary(item))
        output.append("")
    return [TextContent(type="text", text="\n".join(output))]


async def _handle_search_zotero(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    query = args.get("query", "")
    limit = min(args.get("limit", 20), 100)
    if not query:
        return [TextContent(type="text", text="No search query provided.")]

    zot = _get_zotero_client()
    try:
        items = zot.search_items(query, limit)
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero search error: {e}")]

    if not items:
        return [TextContent(type="text", text=f"No items found in Zotero for '{query}'.")]
    return _format_zotero_items(f"ZOTERO SEARCH: '{query}' ({len(items)} results)", items, zot)


async def _handle_get_zotero_collection_items(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    collection_name = args.get("collection_name", "")
    limit = min(args.get("limit", 50), 100)
    if not collection_name:
        return [TextContent(type="text", text="No collection name provided.")]

    zot = _get_zotero_client()
    try:
        collection_key = zot.find_collection_by_name(collection_name)
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero error: {e}")]
    if not collection_key:
        return [TextContent(type="text", text=f"Collection '{collection_name}' not found in Zotero.")]

    try:
        items = zot.get_collection_items(collection_key, limit)
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero error: {e}")]

    if not items:
        return [TextContent(type="text", text=f"No items in collection '{collection_name}'.")]
    return _format_zotero_items(f"ZOTERO COLLECTION: '{collection_name}' ({len(items)} items)", items, zot)


async def _handle_get_zotero_status(args: dict) -> list[TextContent]:
    if not _get_features().get("zotero_enabled", True):
        return [TextContent(type="text", text="Zotero integration is disabled.")]

    try:
        result = _get_zotero_client().verify_credentials()
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero error: {e}")]

    output = ["=" * 50, "ZOTERO STATUS", "=" * 50]
    if result["valid"]:
        access = result.get("access", {})
        output += [
            "\nCredentials: VALID",
            f"Username: {result.get('username', 'N/A')}",
            f"User ID: {result.get('userID', 'N/A')}",
            "\nPermissions:",
            f"  Library access: {access.get('library', False)}",
            f"  File access: {access.get('files', False)}",
            f"  Notes access: {access.get('notes', False)}",
            f"  Write access: {access.get('write', False)}",
        ]
    else:
        output += ["\nCredentials: INVALID", f"Reason: {result.get('message', 'Unknown')}"]
    return [TextContent(type="text", text="\n".join(output))]


def _attachment_filename(requested: str, title: str) -> str:
    base = requested or title or "attachment"
    base = re.sub(r"\.pdf$", "", base, flags=re.I)
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", base).strip()[:120].strip() or "attachment"
    return f"{base}.pdf"


async def _handle_attach_pdf_to_zotero(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    item_key = (args.get("item_key") or "").strip()
    pdf_url = (args.get("pdf_url") or "").strip()
    file_path = (args.get("file_path") or "").strip()
    if not item_key:
        return [TextContent(type="text", text="No item_key provided.")]
    if bool(pdf_url) == bool(file_path):
        return [TextContent(type="text", text="Provide exactly one of pdf_url or file_path.")]

    zot = _get_zotero_client()
    loop = asyncio.get_event_loop()
    try:
        item = await loop.run_in_executor(None, zot.get_item, item_key)
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero error: {e}")]
    if not item:
        return [TextContent(type="text", text=f"No Zotero item with key '{item_key}'.")]
    data = item.get("data", {})
    if data.get("itemType") in ("attachment", "note"):
        return [TextContent(type="text", text=f"Item '{item_key}' is a {data['itemType']}, not a parent item.")]
    title = data.get("title", "")

    if not args.get("force"):
        try:
            existing = await loop.run_in_executor(None, zot.get_pdf_attachments, item_key)
        except ZoteroError as e:
            return [TextContent(type="text", text=f"Zotero error: {e}")]
        if existing:
            names = ", ".join(a.get("filename") or a.get("title") or a.get("key", "") for a in existing)
            return [TextContent(type="text", text=(
                f"'{title}' already has a PDF ({names}). Nothing attached; pass force=true to add another."
            ))]

    filename = _attachment_filename(args.get("filename", ""), title)
    with tempfile.TemporaryDirectory(prefix="duck_zotero_") as tmp:
        upload_path = os.path.join(tmp, filename)
        try:
            if pdf_url:
                size = await loop.run_in_executor(None, download_pdf, pdf_url, upload_path)
            else:
                if not os.path.isfile(file_path):
                    return [TextContent(type="text", text=f"File not found on the MCP server: {file_path}")]
                size = os.path.getsize(file_path)
                if size > PDF_MAX_BYTES:
                    return [TextContent(type="text", text=f"File exceeds {PDF_MAX_BYTES // (1024 * 1024)} MB limit.")]
                if not is_pdf_file(file_path):
                    return [TextContent(type="text", text=f"Not a PDF (no %PDF header): {file_path}")]
                os.symlink(os.path.abspath(file_path), upload_path)
            await loop.run_in_executor(None, zot.attach_file, item_key, upload_path)
        except ZoteroError as e:
            return [TextContent(type="text", text=f"Attach failed: {e}")]

    output = [
        "=" * 50, "PDF ATTACHED TO ZOTERO", "=" * 50,
        f"\nItem: {title or item_key}",
        f"Zotero Key: {item_key}",
        f"File: {filename} ({size / (1024 * 1024):.1f} MB)",
        f"Source: {pdf_url or file_path}",
    ]
    return [TextContent(type="text", text="\n".join(output))]


_ZOTERO_KEY_RE = re.compile(r"^[A-Z0-9]{8}$")
_CSL_STYLE_RE = re.compile(r"^(?:[a-z0-9][a-z0-9._-]{0,127}|https://\S{1,500})$")
_CSL_LOCALE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
_CITATION_FORMAT_LABELS = {
    "bib": "BIBLIOGRAPHY",
    "citation": "IN-TEXT CITATIONS",
    "bibtex": "BIBTEX EXPORT",
    "biblatex": "BIBLATEX EXPORT",
    "ris": "RIS EXPORT",
    "csljson": "CSL-JSON EXPORT",
}


def _parse_citation_item_keys(raw) -> tuple[list[str], str | None]:
    if raw is None:
        return [], None
    if isinstance(raw, str):
        raw = [k for k in re.split(r"[\s,]+", raw) if k]
    if not isinstance(raw, list):
        return [], "item_keys must be an array of Zotero item keys."
    keys: list[str] = []
    for k in raw:
        key = str(k).strip().upper()
        if not _ZOTERO_KEY_RE.match(key):
            return [], f"Invalid Zotero item key: '{k}' (expected 8 letters/digits, e.g. 'ABCD2345')."
        if key not in keys:
            keys.append(key)
    if len(keys) > 50:
        return [], f"Too many item keys ({len(keys)}); the maximum is 50 per request."
    return keys, None


async def _handle_export_zotero_citations(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    item_keys, key_err = _parse_citation_item_keys(args.get("item_keys"))
    if key_err:
        return [TextContent(type="text", text=key_err)]
    collection_name = (args.get("collection_name") or "").strip()
    if bool(item_keys) == bool(collection_name):
        return [TextContent(type="text", text="Provide exactly one of item_keys or collection_name.")]

    fmt = str(args.get("format") or "bib").strip().lower()
    if fmt not in _CITATION_FORMAT_LABELS:
        return [TextContent(type="text", text=(
            f"Unsupported format '{fmt}'. Use one of: {', '.join(_CITATION_FORMAT_LABELS)}."
        ))]
    style = str(args.get("style") or "apa").strip()
    if not _CSL_STYLE_RE.match(style):
        return [TextContent(type="text", text=(
            f"Invalid style '{style}'. Use a CSL style id such as 'apa', 'ieee', or 'chicago-author-date'."
        ))]
    locale = str(args.get("locale") or "en-US").strip()
    if not _CSL_LOCALE_RE.match(locale):
        return [TextContent(type="text", text=f"Invalid locale '{locale}'. Use a tag such as 'en-US' or 'fr-FR'.")]
    try:
        limit = max(1, min(int(args.get("limit", 50)), 100))
    except (TypeError, ValueError):
        return [TextContent(type="text", text="limit must be an integer between 1 and 100.")]

    zot = _get_zotero_client()
    loop = asyncio.get_event_loop()
    collection_key = None
    if collection_name:
        try:
            collection_key = await loop.run_in_executor(None, zot.find_collection_by_name, collection_name)
        except ZoteroError as e:
            return [TextContent(type="text", text=f"Zotero error: {e}")]
        if not collection_key:
            return [TextContent(type="text", text=f"Collection '{collection_name}' not found in Zotero.")]

    try:
        entries = await loop.run_in_executor(
            None,
            lambda: zot.export_citations(
                item_keys=item_keys or None,
                collection_key=collection_key,
                fmt=fmt,
                style=style,
                locale=locale,
                limit=limit,
            ),
        )
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero citation export error: {e}")]

    source = f"collection '{collection_name}'" if collection_name else f"{len(item_keys)} item key(s)"
    if not entries:
        return [TextContent(type="text", text=(
            f"Zotero returned no {fmt} output for {source}. Check the keys exist and are "
            "regular items (notes and attachments have no citation)."
        ))]

    header = [
        "=" * 50,
        f"ZOTERO {_CITATION_FORMAT_LABELS[fmt]} ({len(entries)} entries)",
        f"Source: {source}",
    ]
    if fmt in ("bib", "citation"):
        header.append(f"Style: {style} | Locale: {locale}")
    if item_keys and len(entries) < len(item_keys):
        header.append(
            f"Note: {len(item_keys) - len(entries)} key(s) produced no entry "
            "(unknown key, note, or attachment)."
        )
    header.append("=" * 50)

    if fmt == "csljson":
        body = json.dumps(entries, indent=2, ensure_ascii=False)
    elif fmt == "citation":
        body = "\n".join(entries)
    else:
        body = "\n\n".join(entries)
    return [TextContent(type="text", text="\n".join(header) + "\n\n" + body)]


def _attachment_label(att: dict) -> str:
    name = att.get("filename") or att.get("title") or "attachment"
    content_type = att.get("contentType") or "unknown type"
    return f"{name} ({content_type}, key {att.get('key', '')})"


def _format_annotation(ann: dict) -> str:
    page = ann.get("annotationPageLabel")
    kind = ann.get("annotationType") or "annotation"
    color = ann.get("annotationColor")
    head = f"[p. {page}] " if page else ""
    head += kind + (f" ({color})" if color else "")
    text = (ann.get("annotationText") or "").strip()
    if text:
        head += f': "{text}"'
    lines = [head]
    comment = (ann.get("annotationComment") or "").strip()
    if comment:
        lines.append(f"  Comment: {comment}")
    tag_line = _tag_line(ann)
    if tag_line:
        lines.append(f"  {tag_line}")
    return "\n".join(lines)


def _tag_line(entry: dict) -> str:
    tags = [t.get("tag", "") for t in entry.get("tags") or [] if t.get("tag")]
    return f"Tags: {', '.join(tags)}" if tags else ""


async def _resolve_reading_item(item_key: str):
    zot = _get_zotero_client()
    loop = asyncio.get_event_loop()
    try:
        resolved = await loop.run_in_executor(None, zot.resolve_reading_attachments, item_key)
    except ZoteroError as e:
        return None, [TextContent(type="text", text=f"Zotero error: {e}")]
    if resolved is None:
        return None, [TextContent(type="text", text=f"No Zotero item with key '{item_key}'.")]
    if resolved[0].get("itemType") == "note":
        return None, [TextContent(type="text", text=(
            f"Item '{item_key}' is a note; use get_zotero_notes to read it."
        ))]
    return resolved, None


async def _handle_get_zotero_annotations(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    item_key = (args.get("item_key") or "").strip()
    if not item_key:
        return [TextContent(type="text", text="No item_key provided.")]
    try:
        limit = max(1, min(int(args.get("limit") or 200), 1000))
    except (TypeError, ValueError):
        limit = 200

    resolved, err = await _resolve_reading_item(item_key)
    if err:
        return err
    data, attachments = resolved
    title = data.get("title") or item_key
    if not attachments:
        return [TextContent(type="text", text=f"'{title}' has no file attachments, so no annotations.")]

    zot = _get_zotero_client()
    loop = asyncio.get_event_loop()
    output = ["=" * 50, f"ZOTERO ANNOTATIONS: {title}", "=" * 50]
    remaining = limit
    shown_total = 0
    truncated = False
    for att in attachments:
        if remaining <= 0:
            truncated = True
            break
        try:
            annotations = await loop.run_in_executor(None, zot.get_annotations, att.get("key", ""))
        except ZoteroError as e:
            output.append(f"\n## {_attachment_label(att)}\nZotero error: {e}")
            continue
        output.append(f"\n## {_attachment_label(att)}: {len(annotations)} annotations")
        if len(annotations) > remaining:
            truncated = True
        shown = annotations[:remaining]
        output += [_format_annotation(ann) for ann in shown]
        shown_total += len(shown)
        remaining -= len(shown)
    if shown_total == 0:
        output.append("\nNo annotations found on these attachments.")
    if truncated:
        output.append(f"\n(Stopped at limit={limit}; raise limit to see more.)")
    return [TextContent(type="text", text="\n".join(output))]


async def _handle_get_zotero_notes(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    item_key = (args.get("item_key") or "").strip()
    if not item_key:
        return [TextContent(type="text", text="No item_key provided.")]

    zot = _get_zotero_client()
    loop = asyncio.get_event_loop()
    try:
        item = await loop.run_in_executor(None, zot.get_item, item_key)
        if not item:
            return [TextContent(type="text", text=f"No Zotero item with key '{item_key}'.")]
        data = item.get("data", {})
        item_type = data.get("itemType")
        title = data.get("title") or item_key
        notes: list[dict] = []
        if item_type == "note":
            notes = [data]
            title = f"note {item_key}"
        elif item_type == "attachment":
            if (data.get("note") or "").strip():
                notes.append({"key": item_key, "note": data["note"], "dateModified": data.get("dateModified", "")})
            parent = data.get("parentItem")
            if parent:
                notes += await loop.run_in_executor(None, zot.get_child_notes, parent)
        else:
            notes = await loop.run_in_executor(None, zot.get_child_notes, item_key)
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero error: {e}")]

    if not notes:
        return [TextContent(type="text", text=f"'{title}' has no notes.")]
    output = ["=" * 50, f"ZOTERO NOTES: {title} ({len(notes)})", "=" * 50]
    for i, note in enumerate(notes, 1):
        modified = note.get("dateModified", "")
        suffix = f", modified {modified}" if modified else ""
        output.append(f"\n## Note {i} (key {note.get('key', '')}{suffix})")
        output.append(ZoteroClient.note_html_to_text(note.get("note", "")) or "(empty note)")
        tag_line = _tag_line(note)
        if tag_line:
            output.append(tag_line)
    return [TextContent(type="text", text="\n".join(output))]


async def _handle_get_zotero_fulltext(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    item_key = (args.get("item_key") or "").strip()
    if not item_key:
        return [TextContent(type="text", text="No item_key provided.")]
    try:
        offset = max(0, int(args.get("offset") or 0))
        max_chars = max(1, min(int(args.get("max_chars") or 20000), 100000))
    except (TypeError, ValueError):
        return [TextContent(type="text", text="offset and max_chars must be integers.")]

    resolved, err = await _resolve_reading_item(item_key)
    if err:
        return err
    data, attachments = resolved
    title = data.get("title") or item_key
    if not attachments:
        return [TextContent(type="text", text=f"'{title}' has no file attachments, so no full text.")]

    zot = _get_zotero_client()
    loop = asyncio.get_event_loop()
    found = None
    unindexed: list[str] = []
    for att in attachments:
        try:
            fulltext = await loop.run_in_executor(None, zot.get_fulltext, att.get("key", ""))
        except ZoteroError as e:
            return [TextContent(type="text", text=f"Zotero error: {e}")]
        if fulltext:
            found = (att, fulltext)
            break
        unindexed.append(_attachment_label(att))

    if not found:
        return [TextContent(type="text", text=(
            f"No full text is indexed for '{title}'. Checked: {'; '.join(unindexed)}. "
            "Full text exists only after Zotero desktop indexes the file and syncs it; "
            "get_zotero_annotations and get_zotero_notes may still have the user's reading."
        ))]

    att, fulltext = found
    content = fulltext.get("content", "")
    total = len(content)
    if offset >= total:
        return [TextContent(type="text", text=f"offset {offset} is past the end of the text ({total} characters).")]
    end = min(offset + max_chars, total)
    if "totalPages" in fulltext or "indexedPages" in fulltext:
        coverage = f"Indexed pages: {fulltext.get('indexedPages', '?')} of {fulltext.get('totalPages', '?')}"
    else:
        coverage = f"Indexed chars: {fulltext.get('indexedChars', '?')} of {fulltext.get('totalChars', '?')}"
    output = [
        "=" * 50, f"ZOTERO FULL TEXT: {title}", "=" * 50,
        f"Attachment: {_attachment_label(att)}",
        coverage,
        f"Characters {offset}-{end} of {total}",
    ]
    if end < total:
        output.append(f"More text: call again with offset={end}")
    output += ["-" * 50, content[offset:end]]
    return [TextContent(type="text", text="\n".join(output))]


_ZOTERO_BATCH_MAX = 50


def _string_list(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    seen: list[str] = []
    for v in value:
        s = str(v).strip() if v is not None else ""
        if s and s not in seen:
            seen.append(s)
    return seen


def _clip(value: str, width: int = 80) -> str:
    value = value.replace("\n", " ")
    return value if len(value) <= width else value[: width - 1] + "…"


async def _handle_add_zotero_note(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    item_key = (args.get("item_key") or "").strip()
    note = args.get("note") or ""
    if not item_key:
        return [TextContent(type="text", text="No item_key provided.")]
    if not note.strip():
        return [TextContent(type="text", text="No note text provided.")]
    tags = _string_list(args.get("tags"))

    zot = _get_zotero_client()
    note_html = ZoteroClient.note_to_html(note)
    loop = asyncio.get_event_loop()
    try:
        note_key = await loop.run_in_executor(None, zot.add_note, item_key, note_html, tags)
    except ValueError as e:
        return [TextContent(type="text", text=str(e))]
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero error: {e}")]

    output = [
        "=" * 50, "NOTE ADDED TO ZOTERO", "=" * 50,
        f"\nParent Key: {item_key}",
        f"Note Key: {note_key}",
        f"Length: {len(note)} chars",
    ]
    if tags:
        output.append(f"Tags: {', '.join(tags)}")
    return [TextContent(type="text", text="\n".join(output))]


async def _handle_update_zotero_item(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    item_key = (args.get("item_key") or "").strip()
    fields = args.get("fields") or {}
    creators = args.get("creators")
    item_type = (args.get("item_type") or "").strip() or None
    if not item_key:
        return [TextContent(type="text", text="No item_key provided.")]
    if not isinstance(fields, dict):
        return [TextContent(type="text", text="fields must be an object of Zotero field name -> value.")]
    if creators is not None:
        if isinstance(creators, str):
            creators = [creators]
        if not isinstance(creators, list):
            return [TextContent(type="text", text="creators must be a list of 'Last, First' strings.")]
        creators = [str(c) for c in creators if c is not None]
    if not fields and creators is None and not item_type:
        return [TextContent(type="text", text="Nothing to change: give fields, creators, or item_type.")]

    zot = _get_zotero_client()
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, zot.update_item_fields, item_key, fields, creators, item_type)
    except ValueError as e:
        return [TextContent(type="text", text=str(e))]
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Update failed: {e}")]

    if not result["written"]:
        return [TextContent(type="text", text=(
            f"No changes: '{result['title'] or item_key}' already has those values. Nothing written."
        ))]
    output = [
        "=" * 50, "ZOTERO ITEM UPDATED", "=" * 50,
        f"\nItem: {result['title'] or item_key}",
        f"Zotero Key: {result['key']}",
        f"Type: {result['item_type']}",
        "\nChanges:",
    ]
    for field, before, after in result["changes"]:
        output.append(f"  {field}: {_clip(before) or '(empty)'} -> {_clip(after) or '(empty)'}")
    if result["dropped"]:
        output.append(f"\nDropped (not valid for {result['item_type']}):")
        for field, old in result["dropped"]:
            output.append(f"  {field}: {_clip(old)}")
    return [TextContent(type="text", text="\n".join(output))]


async def _handle_modify_zotero_collections(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    item_keys = _string_list(args.get("item_keys"))
    name = (args.get("collection_name") or "").strip()
    action = (args.get("action") or "").strip().lower()
    if not item_keys:
        return [TextContent(type="text", text="No item_keys provided.")]
    if len(item_keys) > _ZOTERO_BATCH_MAX:
        return [TextContent(type="text", text=f"Too many item_keys ({len(item_keys)}); max {_ZOTERO_BATCH_MAX} per call.")]
    if not name:
        return [TextContent(type="text", text="No collection_name provided.")]
    if action not in ("add", "remove"):
        return [TextContent(type="text", text="action must be 'add' or 'remove'.")]
    create = args.get("create_if_missing", True) if action == "add" else False

    zot = _get_zotero_client()
    loop = asyncio.get_event_loop()
    try:
        if create:
            collection_key = await loop.run_in_executor(None, zot.find_or_create_collection, name)
        else:
            collection_key = await loop.run_in_executor(None, zot.find_collection_by_name, name)
        if not collection_key:
            return [TextContent(type="text", text=f"Collection '{name}' not found in Zotero.")]
        rows = await loop.run_in_executor(None, zot.modify_item_collections, item_keys, collection_key, action)
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero error: {e}")]

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    verb = "ADD TO" if action == "add" else "REMOVE FROM"
    output = [
        "=" * 50, f"ZOTERO COLLECTION {verb}: '{name}'", "=" * 50,
        f"\nCollection Key: {collection_key}",
        "Summary: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
        "",
    ]
    for r in rows:
        label = _clip(r["title"], 60) if r["title"] else ""
        detail = f" ({r['detail']})" if r["detail"] else ""
        output.append(f"  [{r['status']}] {r['key']}{' — ' + label if label else ''}{detail}")
    return [TextContent(type="text", text="\n".join(output))]


async def _handle_modify_zotero_tags(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    item_keys = _string_list(args.get("item_keys"))
    add = _string_list(args.get("add"))
    remove = _string_list(args.get("remove"))
    if not item_keys:
        return [TextContent(type="text", text="No item_keys provided.")]
    if len(item_keys) > _ZOTERO_BATCH_MAX:
        return [TextContent(type="text", text=f"Too many item_keys ({len(item_keys)}); max {_ZOTERO_BATCH_MAX} per call.")]
    if not add and not remove:
        return [TextContent(type="text", text="Give at least one tag in add or remove.")]
    both = sorted(set(add) & set(remove))
    if both:
        return [TextContent(type="text", text=f"Tag(s) in both add and remove: {', '.join(both)}.")]

    zot = _get_zotero_client()
    loop = asyncio.get_event_loop()
    try:
        rows = await loop.run_in_executor(None, zot.modify_item_tags, item_keys, add, remove)
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero error: {e}")]

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    output = [
        "=" * 50, "ZOTERO TAGS UPDATED", "=" * 50,
        f"\nAdd: {', '.join(add) or '-'}",
        f"Remove: {', '.join(remove) or '-'}",
        "Summary: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
        "",
    ]
    for r in rows:
        label = _clip(r["title"], 60) if r["title"] else ""
        parts = []
        if r["added"]:
            parts.append("+" + ", +".join(r["added"]))
        if r["removed"]:
            parts.append("-" + ", -".join(r["removed"]))
        if r["detail"]:
            parts.append(r["detail"])
        tail = f" ({'; '.join(parts)})" if parts else ""
        output.append(f"  [{r['status']}] {r['key']}{' — ' + label if label else ''}{tail}")
    return [TextContent(type="text", text="\n".join(output))]


def _cleanup_item_line(item: dict) -> str:
    title = item.get("title") or "(untitled)"
    parts = [f"- {title} [{item.get('item_type') or 'unknown'}] Zotero Key: {item.get('key', '')}"]
    if item.get("parent_item"):
        parts.append(f"child of {item['parent_item']}")
    if item.get("num_children"):
        parts.append(f"{item['num_children']} child item(s)")
    if item.get("date_modified"):
        parts.append(f"modified {item['date_modified']}")
    return " | ".join(parts)


def _cleanup_limit(args: dict, default: int = 50) -> int:
    try:
        value = int(args.get("limit", default))
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, 100))


def _cleanup_item_keys(args: dict) -> list[str]:
    raw = args.get("item_keys") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(k).strip() for k in raw if str(k).strip()]


async def _run_trash_change(args: dict, restore: bool) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    keys = _cleanup_item_keys(args)
    if not keys:
        return [TextContent(type="text", text="No item_keys provided.")]
    if len(keys) > ZoteroClient.TRASH_BATCH_MAX:
        return [TextContent(type="text", text=(
            f"At most {ZoteroClient.TRASH_BATCH_MAX} item keys per call (got {len(keys)})."
        ))]

    zot = _get_zotero_client()
    loop = asyncio.get_event_loop()
    fn = zot.restore_items if restore else zot.trash_items
    try:
        result = await loop.run_in_executor(None, fn, keys)
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero error: {e}")]

    heading = "ZOTERO RESTORE FROM TRASH" if restore else "ZOTERO MOVE TO TRASH"
    output = ["=" * 50, heading, "=" * 50]
    if result["changed"]:
        output.append(f"\n{'Restored' if restore else 'Moved to trash'} ({len(result['changed'])}):")
        output += [_cleanup_item_line(i) for i in result["changed"]]
        if not restore and any(i.get("num_children") for i in result["changed"]):
            output.append("Child notes/attachments are hidden with their parent and come back if it is restored.")
    if result["skipped"]:
        label = "Not in the trash, left unchanged" if restore else "Already in the trash, left unchanged"
        output.append(f"\n{label} ({len(result['skipped'])}):")
        output += [_cleanup_item_line(i) for i in result["skipped"]]
        if restore and any(i.get("parent_item") for i in result["skipped"]):
            output.append("A child item shown here is hidden because its parent is trashed; restore the parent key.")
    if result["not_found"]:
        output.append(f"\nNot found in the library ({len(result['not_found'])}): {', '.join(result['not_found'])}")
    if result["failed"]:
        output.append(f"\nFailed ({len(result['failed'])}):")
        output += [f"{_cleanup_item_line(i)} | error: {i.get('error', '')}" for i in result["failed"]]
    if not restore and result["changed"]:
        output.append("\nNothing was permanently deleted; use restore_zotero_item to undo.")
    return [TextContent(type="text", text="\n".join(output))]


async def _handle_trash_zotero_item(args: dict) -> list[TextContent]:
    return await _run_trash_change(args, restore=False)


async def _handle_restore_zotero_item(args: dict) -> list[TextContent]:
    return await _run_trash_change(args, restore=True)


async def _handle_list_zotero_trash(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    limit = _cleanup_limit(args)
    zot = _get_zotero_client()
    loop = asyncio.get_event_loop()
    try:
        items = await loop.run_in_executor(None, zot.list_trash, limit)
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero error: {e}")]

    if not items:
        return [TextContent(type="text", text="The Zotero trash is empty.")]
    output = ["=" * 50, f"ZOTERO TRASH ({len(items)} items)", "=" * 50, ""]
    output += [_cleanup_item_line(i) for i in items]
    if len(items) >= limit:
        output.append(f"\nShowing the first {limit}; more may be in the trash.")
    return [TextContent(type="text", text="\n".join(output))]


async def _handle_list_unfiled_zotero_items(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    limit = _cleanup_limit(args)
    include_trashed = bool(args.get("include_trashed", False))
    zot = _get_zotero_client()
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, zot.list_unfiled_items, limit, include_trashed)
    except ZoteroError as e:
        return [TextContent(type="text", text=f"Zotero error: {e}")]

    items = result["items"]
    scope = "including trashed" if include_trashed else "excluding trashed"
    output = ["=" * 50, f"ZOTERO UNFILED ITEMS ({len(items)} found, {scope})", "=" * 50, ""]
    if items:
        for i in items:
            line = _cleanup_item_line(i)
            output.append(f"{line} | IN TRASH" if i.get("deleted") else line)
    else:
        output.append("No unfiled top-level items found.")
    output.append(f"\nScanned {result['scanned']} top-level items, newest first.")
    if result["cap_hit"]:
        output.append(
            f"Scan cap of {ZoteroClient.UNFILED_SCAN_CAP} items reached; older unfiled items "
            "were not checked (use search_zotero to find a specific one)."
        )
    elif len(items) >= limit:
        output.append(f"Stopped at limit={limit}; more unfiled items may exist.")
    return [TextContent(type="text", text="\n".join(output))]



_ZLIB_SORTS = ("dateAdded", "dateModified", "date", "title", "creator")
_ZLIB_STATS_SCAN_CAP = 1000
_ZLIB_DUPLICATE_SCAN_CAP = 2000
_ZLIB_DUPLICATE_GROUPS_SHOWN = 100


def _zlib_text(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def _zlib_int(args: dict, key: str, default: int, lo: int, hi: int) -> int:
    """Read an integer argument, falling back to `default` and clamping to [lo, hi]."""
    try:
        value = int(args.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _zlib_str_list(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [v.strip() for v in (value or []) if isinstance(v, str) and v.strip()]


async def _zlib_run(fn, *args, **kwargs):
    return await asyncio.get_event_loop().run_in_executor(None, lambda: fn(*args, **kwargs))


def _zlib_collection_path(key: str, by_key: dict) -> str:
    """'Parent / Child' path for a collection key (cycle-safe)."""
    names, seen = [], set()
    while key and key in by_key and key not in seen:
        seen.add(key)
        names.append(by_key[key]["name"])
        key = by_key[key].get("parent_key") or ""
    return " / ".join(reversed(names)) or "(top level)"


def _zlib_resolve_collection(collections: list[dict], ref: str) -> tuple:
    """Resolve a collection by exact key, else by case-insensitive name. Returns (collection, error)."""
    ref = (ref or "").strip()
    by_key = {c["key"]: c for c in collections}
    if ref in by_key:
        return by_key[ref], None
    matches = [c for c in collections if c["name"].lower() == ref.lower()]
    if not matches:
        return None, f"Collection '{ref}' not found in Zotero."
    if len(matches) > 1:
        listing = "; ".join(f"{_zlib_collection_path(c['key'], by_key)} (key {c['key']})" for c in matches)
        return None, f"Collection name '{ref}' is ambiguous: {listing}. Pass the key instead."
    return matches[0], None


def _zlib_sibling_clash(collections: list[dict], name: str, parent_key: str, exclude_key: str = "") -> dict | None:
    for c in collections:
        if c["key"] != exclude_key and (c.get("parent_key") or "") == (parent_key or "") \
                and c["name"].lower() == name.lower():
            return c
    return None


async def _handle_advanced_search_zotero(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    query = (args.get("query") or "").strip()
    tags = _zlib_str_list(args.get("tags"))
    types = _zlib_str_list(args.get("item_types"))
    if not (query or tags or types):
        return _zlib_text("Provide at least one of query, tags, or item_types.")
    qmode = args.get("qmode") or "titleCreatorYear"
    if qmode not in ("titleCreatorYear", "everything"):
        return _zlib_text("qmode must be 'titleCreatorYear' or 'everything'.")
    sort = args.get("sort") or "dateModified"
    if sort not in _ZLIB_SORTS:
        return _zlib_text(f"sort must be one of: {', '.join(_ZLIB_SORTS)}.")
    direction = args.get("direction") or "desc"
    if direction not in ("asc", "desc"):
        return _zlib_text("direction must be 'asc' or 'desc'.")
    excluded = [t for t in types if t.startswith("-")]
    included = [t for t in types if not t.startswith("-")]
    if excluded and (included or len(excluded) > 1):
        return _zlib_text(
            "item_types: list the types to include, or give exactly one '-type' to exclude (not both)."
        )
    item_type = excluded[0] if excluded else " || ".join(included)
    top_level = not any(t in ("attachment", "note") for t in included)
    limit = _zlib_int(args, "limit", 25, 1, 100)
    start = _zlib_int(args, "start", 0, 0, 10**9)

    zot = _get_zotero_client()
    try:
        items, total = await _zlib_run(
            zot.advanced_search, query=query, qmode=qmode, tags=tags, item_type=item_type,
            sort=sort, direction=direction, include_trashed=bool(args.get("include_trashed")),
            limit=limit, start=start, top_level=top_level,
        )
    except ZoteroError as e:
        return _zlib_text(f"Zotero search error: {e}")

    filters = []
    if query:
        filters.append(f"query='{query}' ({qmode})")
    if tags:
        filters.append("tags: " + " AND ".join(f"[{t}]" for t in tags))
    if item_type:
        filters.append(f"itemType: {item_type}")
    if args.get("include_trashed"):
        filters.append("including trash")
    if not items:
        return _zlib_text(f"No Zotero items match {'; '.join(filters)}.")
    total_txt = str(total) if total is not None else "unknown"
    output = ["=" * 50,
              f"ZOTERO ADVANCED SEARCH: results {start + 1}-{start + len(items)} of {total_txt}",
              "=" * 50, f"Filters: {'; '.join(filters)}", f"Sorted by {sort} {direction}", ""]
    for i, item in enumerate(items, start + 1):
        output.append(f"--- Item {i} ---")
        output.append(zot.format_item_summary(item))
        output.append("")
    if total is not None and start + len(items) < total:
        output.append(f"More results: call again with start={start + len(items)}.")
    return _zlib_text("\n".join(output).rstrip())


async def _handle_get_zotero_recent_changes(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    limit = _zlib_int(args, "limit", 25, 1, 100)
    since = args.get("since_version")
    if since is not None and since != "":
        try:
            since = int(since)
        except (TypeError, ValueError):
            return _zlib_text("since_version must be an integer library version.")
        if since < 0:
            return _zlib_text("since_version must be >= 0.")
    else:
        since = None

    zot = _get_zotero_client()
    try:
        changes = await _zlib_run(zot.get_recent_changes, since, limit)
    except ZoteroError as e:
        return _zlib_text(f"Zotero error: {e}")
    version = changes.get("library_version")

    if since is None:
        recent = changes.get("recent") or []
        output = ["=" * 50, f"ZOTERO RECENT CHANGES: {len(recent)} most recently modified items", "=" * 50,
                  f"Current library version: {version} (pass since_version={version} next time "
                  "to see only later changes)", ""]
        for i, item in enumerate(recent, 1):
            output.append(f"--- Item {i} ---")
            output.append(zot.format_item_summary(item))
            output.append("")
        return _zlib_text("\n".join(output).rstrip())

    item_versions = changes.get("items") or {}
    coll_versions = changes.get("collections") or {}
    deleted = changes.get("deleted") or {}
    output = ["=" * 50, f"ZOTERO CHANGES SINCE VERSION {since}", "=" * 50,
              f"New library version: {version} (pass since_version={version} next time)", ""]
    if not item_versions and not coll_versions and not any(deleted.get(k) for k in deleted):
        output.append("No changes.")

    if item_versions:
        ordered = sorted(item_versions, key=lambda k: -int(item_versions[k] or 0))
        shown = ordered[:min(limit, 50)]
        try:
            raw = await _zlib_run(zot.get_items_by_keys, shown)
        except ZoteroError as e:
            return _zlib_text(f"Zotero error: {e}")
        by_key = {i.get("data", {}).get("key", i.get("key")): i.get("data", {}) for i in raw}
        output.append(f"Changed items: {len(item_versions)}" +
                      (f" (showing the {len(shown)} newest)" if len(shown) < len(item_versions) else ""))
        for k in shown:
            d = by_key.get(k, {})
            kind = d.get("itemType", "?")
            title = d.get("title") or d.get("filename") or (re.sub(r"<[^>]+>", "", d.get("note", ""))[:60]
                                                             if kind == "note" else "")
            parent = f", child of {d['parentItem']}" if d.get("parentItem") else ""
            trashed = ", in trash" if d.get("deleted") else ""
            output.append(f"  [{kind}] {title or '(untitled)'} (key {k}, v{item_versions[k]}{parent}{trashed})")
        output.append("")

    if coll_versions:
        try:
            colls, _ = await _zlib_run(zot.list_all_collections)
        except ZoteroError as e:
            return _zlib_text(f"Zotero error: {e}")
        names = {c["key"]: c for c in colls}
        output.append(f"Changed collections: {len(coll_versions)}")
        for k in sorted(coll_versions, key=lambda k: -int(coll_versions[k] or 0)):
            path = _zlib_collection_path(k, names) if k in names else "(not readable)"
            output.append(f"  {path} (key {k}, v{coll_versions[k]})")
        output.append("")

    for label, field in (("Deleted items", "items"), ("Deleted collections", "collections"),
                         ("Deleted tags", "tags"), ("Deleted saved searches", "searches")):
        values = deleted.get(field) or []
        if values:
            shown_vals = ", ".join(str(v) for v in values[:100])
            more = f" (+{len(values) - 100} more)" if len(values) > 100 else ""
            output.append(f"{label} ({len(values)}): {shown_vals}{more}")
    return _zlib_text("\n".join(output).rstrip())


async def _handle_manage_zotero_collection(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    action = (args.get("action") or "").strip()
    name = (args.get("collection_name") or "").strip()
    if action not in ("create", "rename", "move"):
        return _zlib_text("action must be 'create', 'rename', or 'move' (collection deletion is not supported).")
    if not name:
        return _zlib_text("No collection_name provided.")
    parent_ref = args.get("parent_collection")
    if action == "rename" and not (args.get("new_name") or "").strip():
        return _zlib_text("rename needs new_name.")
    if action == "move" and parent_ref is None:
        return _zlib_text("move needs parent_collection (use '' to make it top-level).")

    zot = _get_zotero_client()
    try:
        collections, library_version = await _zlib_run(zot.list_all_collections)
    except ZoteroError as e:
        return _zlib_text(f"Zotero error: {e}")
    by_key = {c["key"]: c for c in collections}

    parent = None
    if parent_ref is not None and str(parent_ref).strip():
        parent, err = _zlib_resolve_collection(collections, str(parent_ref))
        if err:
            return _zlib_text(f"Parent: {err}")
    parent_key = parent["key"] if parent else ""
    where = _zlib_collection_path(parent_key, by_key) if parent_key else "the top level"

    try:
        if action == "create":
            clash = _zlib_sibling_clash(collections, name, parent_key)
            if clash:
                return _zlib_text(f"A collection named '{clash['name']}' already exists at {where} "
                                  f"(key {clash['key']}). Nothing created.")
            data = await _zlib_run(zot.create_collection_checked, name, parent_key, library_version)
            return _zlib_text(f"Created collection '{data.get('name', name)}' at {where} "
                              f"(key {data.get('key', '')}).")

        target, err = _zlib_resolve_collection(collections, name)
        if err:
            return _zlib_text(err)
        old_path = _zlib_collection_path(target["key"], by_key)

        if action == "rename":
            new_name = args["new_name"].strip()
            if new_name == target["name"]:
                return _zlib_text(f"'{old_path}' already has that name. Nothing changed.")
            clash = _zlib_sibling_clash(collections, new_name, target.get("parent_key") or "", target["key"])
            if clash:
                return _zlib_text(f"A sibling collection named '{clash['name']}' already exists "
                                  f"(key {clash['key']}). Nothing renamed.")
            await _zlib_run(zot.update_collection_checked, target["key"], {"name": new_name})
            return _zlib_text(f"Renamed '{old_path}' to '{new_name}' (key {target['key']}).")

        if (target.get("parent_key") or "") == parent_key:
            return _zlib_text(f"'{old_path}' is already at {where}. Nothing moved.")
        ancestor, seen = parent_key, set()
        while ancestor and ancestor not in seen:
            if ancestor == target["key"]:
                return _zlib_text(f"Cannot move '{old_path}' under itself or one of its subcollections.")
            seen.add(ancestor)
            ancestor = by_key.get(ancestor, {}).get("parent_key") or ""
        clash = _zlib_sibling_clash(collections, target["name"], parent_key, target["key"])
        if clash:
            return _zlib_text(f"{where} already has a collection named '{clash['name']}' "
                              f"(key {clash['key']}). Nothing moved.")
        await _zlib_run(zot.update_collection_checked, target["key"], {"parentCollection": parent_key or False})
        return _zlib_text(f"Moved '{old_path}' to {where} (key {target['key']}).")
    except ZoteroError as e:
        return _zlib_text(f"Collection {action} failed: {e}")


def _zlib_collect_stats(zot: ZoteroClient) -> dict:
    scan, scan_total, capped = zot.scan_top_items(_ZLIB_STATS_SCAN_CAP)
    collections, _ = zot.list_all_collections()
    tags, tag_total, _ = zot.list_tags("", 15)
    return {
        "top_items": scan_total,
        "all_items": zot.count_results("/items"),
        "attachments": zot.count_results("/items", {"itemType": "attachment"}),
        "notes": zot.count_results("/items", {"itemType": "note"}),
        "trash": zot.count_results("/items/trash"),
        "collections": collections,
        "tags": tags,
        "tag_total": tag_total,
        "scan": scan,
        "scan_total": scan_total,
        "scan_capped": capped,
    }


async def _handle_get_zotero_library_stats(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    zot = _get_zotero_client()
    try:
        s = await _zlib_run(_zlib_collect_stats, zot)
    except ZoteroError as e:
        return _zlib_text(f"Zotero error: {e}")

    def n(v):
        return "unknown" if v is None else str(v)

    output = ["=" * 50, "ZOTERO LIBRARY STATS", "=" * 50,
              f"Top-level items: {n(s['top_items'])}",
              f"All items (incl. attachments and notes): {n(s['all_items'])}",
              f"Attachments: {n(s['attachments'])}",
              f"Notes: {n(s['notes'])}",
              f"In trash: {n(s['trash'])}", ""]

    types: dict[str, int] = {}
    for item in s["scan"]:
        t = item.get("data", {}).get("itemType", "unknown")
        types[t] = types.get(t, 0) + 1
    scope = (f"first {len(s['scan'])} of {n(s['scan_total'])} top-level items, capped"
             if s["scan_capped"] else f"all {len(s['scan'])} top-level items")
    output.append(f"Item types ({scope}):")
    for t, count in sorted(types.items(), key=lambda kv: (-kv[1], kv[0])):
        output.append(f"  {t}: {count}")
    output.append("")

    colls = s["collections"]
    by_key = {c["key"]: c for c in colls}
    output.append(f"Collections ({len(colls)}):")
    for c in sorted(colls, key=lambda c: _zlib_collection_path(c["key"], by_key).lower()):
        output.append(f"  {_zlib_collection_path(c['key'], by_key)}: {c['num_items']} items")
    if not colls:
        output.append("  (none)")
    output.append("")

    output.append(f"Top tags (of {n(s['tag_total'])} distinct):")
    for t in s["tags"]:
        output.append(f"  {t['tag']}: {n(t['num_items'])} items")
    if not s["tags"]:
        output.append("  (none)")
    return _zlib_text("\n".join(output))


def _zlib_norm_doi(value: str) -> str:
    m = re.search(r"10\.\d{4,9}/\S+", value or "", flags=re.I)
    return m.group(0).lower().rstrip(".,;)]") if m else ""


def _zlib_isbn13(token: str) -> str:
    token = token.upper()
    if re.fullmatch(r"97[89]\d{10}", token):
        return token
    if re.fullmatch(r"\d{9}[\dX]", token):
        core = "978" + token[:9]
        check = (10 - sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core)) % 10) % 10
        return core + str(check)
    return ""


def _zlib_norm_isbns(value: str) -> set[str]:
    tokens = re.split(r"[\s,;]+", (value or "").replace("-", ""))
    return {i for i in (_zlib_isbn13(t) for t in tokens) if i}


def _zlib_norm_title(title: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFKD", title or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return " ".join(re.sub(r"[\W_]+", " ", text).split())


def _zlib_duplicate_groups(items: list[dict]) -> list[tuple]:
    """Group raw items by DOI, then ISBN, then normalized title + year.

    Returns [(signal, value, [raw items])]. A group whose members were all already
    reported together under an earlier signal is dropped.
    """
    buckets: dict[tuple, list] = {}
    for item in items:
        d = item.get("data", {})
        if d.get("itemType") in ("attachment", "note", "annotation"):
            continue
        extra_doi = next((ln for ln in (d.get("extra") or "").splitlines() if ln.lower().startswith("doi:")), "")
        doi = _zlib_norm_doi(d.get("DOI", "")) or _zlib_norm_doi(extra_doi)
        if doi:
            buckets.setdefault(("DOI", doi), []).append(item)
        for isbn in sorted(_zlib_norm_isbns(d.get("ISBN", ""))):
            buckets.setdefault(("ISBN", isbn), []).append(item)
        title = _zlib_norm_title(d.get("title", ""))
        if len(title) >= 4:
            year = re.search(r"\b(\d{4})\b", d.get("date") or "")
            label = f"{title} ({year.group(1) if year else 'no year'})"
            buckets.setdefault(("title+year", label), []).append(item)

    groups, reported = [], []
    for signal in ("DOI", "ISBN", "title+year"):
        for (sig, value), members in buckets.items():
            if sig != signal or len(members) < 2:
                continue
            keys = {m.get("data", {}).get("key", m.get("key")) for m in members}
            if len(keys) < 2 or any(keys <= r for r in reported):
                continue
            reported.append(keys)
            groups.append((signal, value, members))
    return groups


async def _handle_find_zotero_duplicates(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    zot = _get_zotero_client()
    try:
        items, total, capped = await _zlib_run(zot.scan_top_items, _ZLIB_DUPLICATE_SCAN_CAP)
        collections, _ = await _zlib_run(zot.list_all_collections)
    except ZoteroError as e:
        return _zlib_text(f"Zotero error: {e}")
    by_key = {c["key"]: c for c in collections}

    groups = _zlib_duplicate_groups(items)
    scope = (f"the first {len(items)} of {total if total is not None else 'unknown'} top-level items (capped)"
             if capped else f"all {len(items)} top-level items")
    output = ["=" * 50, f"ZOTERO DUPLICATE REPORT: {len(groups)} likely duplicate groups", "=" * 50,
              f"Scanned {scope}. Report only: the Zotero Web API has no merge operation. Merge "
              "duplicates in Zotero desktop (Duplicate Items in the left pane).", ""]
    if not groups:
        output.append("No duplicates found by DOI, ISBN, or title + year.")
    for i, (signal, value, members) in enumerate(groups[:_ZLIB_DUPLICATE_GROUPS_SHOWN], 1):
        output.append(f"--- Group {i}: same {signal} = {value} ---")
        for m in members:
            d = m.get("data", {})
            colls = ", ".join(_zlib_collection_path(k, by_key) for k in d.get("collections", [])) or "unfiled"
            children = m.get("meta", {}).get("numChildren", 0)
            output.append(
                f"  {d.get('key', '')}: {d.get('title') or '(untitled)'} [{d.get('itemType', '')}] "
                f"date={d.get('date') or '-'} added={(d.get('dateAdded') or '')[:10]} "
                f"child attachments/notes={children} collections={colls}"
            )
        output.append("")
    if len(groups) > _ZLIB_DUPLICATE_GROUPS_SHOWN:
        output.append(f"(+{len(groups) - _ZLIB_DUPLICATE_GROUPS_SHOWN} more groups not shown)")
    return _zlib_text("\n".join(output).rstrip())


async def _handle_list_zotero_tags(args: dict) -> list[TextContent]:
    auth_err = _ensure_zotero_auth()
    if auth_err:
        return auth_err

    filter_text = (args.get("filter") or "").strip()
    limit = _zlib_int(args, "limit", 100, 1, 500)
    zot = _get_zotero_client()
    try:
        tags, total, capped = await _zlib_run(zot.list_tags, filter_text, limit)
    except ZoteroError as e:
        return _zlib_text(f"Zotero error: {e}")

    scope = f" containing '{filter_text}'" if filter_text else ""
    if not tags:
        return _zlib_text(f"No Zotero tags{scope}.")
    count = f"{len(tags)} of {total}" if capped and total is not None else str(len(tags))
    output = ["=" * 50, f"ZOTERO TAGS{scope} ({count})", "=" * 50, ""]
    for t in tags:
        kind = " (automatic)" if t.get("type") == 1 else ""
        num = t["num_items"] if t["num_items"] is not None else "?"
        output.append(f"  {t['tag']} — {num} items{kind}")
    if capped:
        output.append(f"\nShowing the {len(tags)} most used; raise limit (max 500) or use filter for more.")
    return _zlib_text("\n".join(output))
