"""MCP tool definitions and handler dispatch."""

import asyncio
import contextvars
import json
import logging
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
from lib.zotero import ZoteroClient, ZoteroError, fetch_zotero_item_types

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
                        "'thesis', 'blogPost'. Full list: https://api.zotero.org/itemTypes"
                    ),
                    "default": "document",
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
            "E.g. 'journalArticle', 'computerProgram', 'thesis', 'blogPost'."
        ),
        "default": "document",
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


