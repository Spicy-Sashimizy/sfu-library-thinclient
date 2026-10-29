"""Federated search router — Option C (Federated Hybrid).

Routes queries between live OpenAlex API and local OpenSearch index:
  - Date filters starting inside federated_recency_days, or lying entirely past the
    local index's coverage end, or explicit temporal cues → LIVE_API
  - Date filters the local index fully covers never route live by date
  - A live-leg failure falls back to the local route (last_live_fallback)
  - Zero-coverage subjects (no local index data) → LIVE_API (Q2.1)
  - Soft-live subjects (OpenAlex beats local RRF) → LIVE_API unless overridden (Q2.2)
  - Historical queries → LOCAL_INDEX

DOI deduplication uses normalized DOI strings (no https://doi.org/ prefix) as keys.
RRF fusion formula: score = Σ 1 / (k + rank_i) where k=60.
"""

import contextlib
import functools
import logging
import re
from datetime import date, timedelta
from enum import Enum
from typing import Any

from lib import speculative_rerank

logger = logging.getLogger("sfu_library_mcp")

_CUE_WORDS = r"recent|latest|new|current|this year|last year|emerging"


@functools.lru_cache(maxsize=4)
def _cues_for_year(year: int) -> re.Pattern:
    return re.compile(rf"\b({_CUE_WORDS}|{year - 1}|{year})\b", re.IGNORECASE)


def temporal_cues(today: date | None = None) -> re.Pattern:
    """Temporal-cue regex for a given day: the fixed cue words plus the current and
    previous calendar years, so the year cues follow the calendar instead of a literal."""
    return _cues_for_year((today or date.today()).year)


def _parse_bound(text: Any, end: bool) -> date | None:
    text = str(text or "").strip()
    if not text:
        return None
    try:
        if len(text) >= 10:
            return date.fromisoformat(text[:10])
        year = int(text[:4])
        return date(year, 12, 31) if end else date(year, 1, 1)
    except ValueError:
        return None


def requested_range(filters: dict) -> tuple[date | None, date | None]:
    """(start, end) publication dates asked for by OpenAlex-style filters.

    Reads ``publication_year`` (``"2024"`` or ``"2020-2024"``) first, then
    ``from_publication_date`` / ``to_publication_date``. Either bound is None
    when the filters leave it open.
    """
    lo = hi = None
    py = filters.get("publication_year")
    if py:
        a, sep, b = str(py).partition("-")
        lo = _parse_bound(a, False)
        hi = _parse_bound(b if sep else a, True)
    if lo is None:
        lo = _parse_bound(filters.get("from_publication_date"), False)
    if hi is None:
        hi = _parse_bound(filters.get("to_publication_date"), True)
    return lo, hi

_RRF_K = 60

ALWAYS_LIVE_SUBJECTS = {
    "Theatre", "Music", "Urban Studies", "Applied Legal Studies",
    "Publishing", "Management & Organizational Studies", "Accounting",
    "Forensics", "Statistics & Actuarial Science",
    "Sustainable Energy Engineering (SEE)",
    "Sustainable Community Development",
    "Visual Arts", "Public Policy",
    "Molecular Biology & Biochemistry", "Global Health",
}

SOFT_LIVE_SUBJECTS = {
    "Anthropology",
}

_SUBJECT_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Theatre", ("theatre", "theater", "playwright", "stagecraft", "dramaturgy", "scenography")),
    ("Music", ("music", "musical", "composer", "symphony", "orchestra", "string quartet", "opera", "ethnomusicology")),
    ("Urban Studies", ("urban studies", "urban planning", "city planning", "gentrification", "urbanism")),
    ("Applied Legal Studies", ("legal studies", "paralegal", "law and society", "access to justice")),
    ("Publishing", ("publishing industry", "book publishing", "scholarly publishing", "editorial workflow")),
    ("Management & Organizational Studies", ("organizational behavior", "organisational behaviour", "management studies", "organizational studies", "human resource management")),
    ("Accounting", ("accounting", "auditing", "financial reporting", "bookkeeping", "gaap")),
    ("Forensics", ("forensic", "forensics", "criminalistics")),
    ("Statistics & Actuarial Science", ("actuarial", "actuarial science", "biostatistics")),
    ("Sustainable Energy Engineering (SEE)", ("sustainable energy engineering", "renewable energy engineering", "photovoltaic engineering")),
    ("Sustainable Community Development", ("sustainable community development", "community development", "sustainable communities")),
    ("Visual Arts", ("visual arts", "painting", "sculpture", "printmaking", "studio art")),
    ("Public Policy", ("public policy", "policy analysis", "policy evaluation", "governance policy")),
    ("Molecular Biology & Biochemistry", ("molecular biology", "biochemistry", "enzyme kinetics", "protein folding", "gene expression")),
    ("Global Health", ("global health", "public health", "epidemiology", "health systems")),
    ("Anthropology", ("anthropology", "anthropological", "ethnography", "kinship", "zooarchaeology", "ethnographic")),
]


def detect_subject(query: str) -> str:
    """Heuristically map a raw query to a routing-relevant SFU subject name.

    Returns the matched subject (one of ALWAYS_LIVE_SUBJECTS / SOFT_LIVE_SUBJECTS)
    or "" if no high-signal keyword matched. This is intentionally conservative:
    it exists only to wake the subject-aware routing rules (Q2.1/Q2.2) for the
    zero-coverage and soft-live subjects, not to classify every query.
    """
    if not query:
        return ""
    lowered = query.lower()
    for subject, keywords in _SUBJECT_KEYWORDS:
        for kw in keywords:
            if " " in kw:
                if kw in lowered:
                    return subject
            elif re.search(rf"\b{re.escape(kw)}\b", lowered):
                return subject
    return ""


class SearchSource(str, Enum):
    LIVE_API = "live_api"
    LOCAL_INDEX = "local_index"
    LOCAL_RRF = "local_rrf"


def _normalize_doi(doi: str) -> str:
    """Strip URL prefix from DOI for deduplication."""
    if not doi:
        return ""
    for prefix in ("https://doi.org/", "http://doi.org/"):
        if doi.startswith(prefix):
            return doi[len(prefix):]
    return doi


def _rrf_merge(
    primary: list[dict],
    secondary: list[dict],
    top_k: int,
) -> list[dict]:
    """Merge two ranked lists with Reciprocal Rank Fusion, deduplicating by DOI.

    primary docs (typically live API) take precedence for metadata when DOI overlaps.
    """
    scores: dict[str, float] = {}
    by_doi: dict[str, dict] = {}

    def _key(doc: dict) -> str:
        return _normalize_doi(doc.get("doi", "")) or doc.get("openalex_id", "") or doc.get("title", "")

    for rank, doc in enumerate(primary, start=1):
        k = _key(doc)
        if k:
            scores[k] = scores.get(k, 0.0) + 1.0 / (_RRF_K + rank)
            if k not in by_doi:
                by_doi[k] = doc

    for rank, doc in enumerate(secondary, start=1):
        k = _key(doc)
        if k:
            scores[k] = scores.get(k, 0.0) + 1.0 / (_RRF_K + rank)
            if k not in by_doi:
                by_doi[k] = doc

    ranked = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    merged = []
    for k in ranked[:top_k]:
        doc = dict(by_doi[k])
        doc["rrf_score"] = scores[k]
        merged.append(doc)
    return merged


class FederatedSearchRouter:
    """Route academic queries between live OpenAlex API and local OpenSearch.

    Instantiated with references to both backends so it can be tested with mocks.
    """

    def __init__(
        self,
        openalex_client: Any,
        opensearch_retriever: Any,
        recency_days: int = 30,
        local_rrf_enabled: bool = True,
    ):
        self._openalex = openalex_client
        self._opensearch = opensearch_retriever
        self.recency_days = recency_days
        self.local_rrf_enabled = local_rrf_enabled
        self.last_degraded = False
        self.last_live_fallback = False

    def local_coverage_end(self) -> date | None:
        """Newest publication date the local index can hold, from the retriever's
        ``coverage_end()``; None when the retriever has none or it does not return a date."""
        fn = getattr(self._opensearch, "coverage_end", None)
        if fn is None:
            return None
        try:
            out = fn()
        except Exception:
            return None
        return out if isinstance(out, date) else None

    def route(
        self,
        query: str,
        filters: dict,
        subject_hint: str = "",
        prefer_local: bool = False,
    ) -> SearchSource:
        """Determine which backend(s) to query.

        Rules (evaluated in order; the date rules read publication_year,
        from_publication_date and to_publication_date via requested_range):
        1a. requested range starts after the local index's coverage end → LIVE_API
        1b. requested range ends on or before the coverage end → date rules skipped
        1c. requested range starts within recency_days of today → LIVE_API
            (1a/1b need a retriever with ``coverage_end()``; otherwise only 1c runs)
        2. Temporal cue words in query (incl. current/previous year) → LIVE_API
        3. subject_hint in ALWAYS_LIVE_SUBJECTS (zero local coverage) → LIVE_API (Q2.1)
        4. subject_hint in SOFT_LIVE_SUBJECTS → LIVE_API unless prefer_local (Q2.2)
        5. Everything else → LOCAL_RRF (when local_rrf_enabled) else LOCAL_INDEX

        Args:
            query: raw query string
            filters: OpenAlex-style filter dict (e.g. from_publication_date, type)
            subject_hint: detected SFU subject area for the query (e.g. "Theatre").
                Empty string means no subject was detected and subject-aware rules
                are skipped. tools.py passes ``detect_subject(query)`` here.
            prefer_local: when True, overrides the SOFT_LIVE_SUBJECTS preference and
                keeps soft-live subjects on the local route. Has no effect on the
                hard ALWAYS_LIVE_SUBJECTS list (those have no usable local data).
        """
        today = date.today()
        lo, hi = requested_range(filters)
        if lo is not None or hi is not None:
            coverage_end = self.local_coverage_end()
            end = hi if hi is not None else today
            if coverage_end is not None and lo is not None and lo > coverage_end:
                return SearchSource.LIVE_API
            fully_covered = coverage_end is not None and end <= coverage_end
            if (not fully_covered and lo is not None
                    and lo >= today - timedelta(days=self.recency_days)):
                return SearchSource.LIVE_API

        if temporal_cues(today).search(query):
            return SearchSource.LIVE_API

        if subject_hint in ALWAYS_LIVE_SUBJECTS:
            return SearchSource.LIVE_API

        if subject_hint in SOFT_LIVE_SUBJECTS and not prefer_local:
            return SearchSource.LIVE_API

        return SearchSource.LOCAL_RRF if self.local_rrf_enabled else SearchSource.LOCAL_INDEX

    def search(
        self,
        query: str,
        filters: dict,
        top_k: int = 50,
        force_source: SearchSource | None = None,
        subject_hint: str = "",
        prefer_local: bool = False,
    ) -> list[dict]:
        """Dispatch to the routed source; LOCAL_RRF fuses BM25F + SPLADE with RRF and DOI dedup.

        Args:
            query: raw query string
            filters: OpenAlex-style filter dict (e.g. from_publication_date, type)
            top_k: maximum results to return
            force_source: override automatic routing when set
            subject_hint: detected SFU subject area, forwarded to route() for the
                Q2.1/Q2.2 subject-aware rules.
            prefer_local: forwarded to route() — overrides the soft-live preference.
        """
        source = force_source or self.route(
            query, filters, subject_hint=subject_hint, prefer_local=prefer_local
        )

        live_results: list[dict] = []
        local_results: list[dict] = []
        self.last_degraded = False
        self.last_live_fallback = False

        if source == SearchSource.LIVE_API:
            try:
                data = self._openalex.search_works(
                    query, filters=filters, per_page=top_k
                )
                live_results = data.get("results", [])
            except Exception:
                logger.exception("FederatedSearchRouter: live API search failed; falling back to the local route")
                self.last_live_fallback = True
                source = (SearchSource.LOCAL_RRF if self.local_rrf_enabled
                          else SearchSource.LOCAL_INDEX)

        if source == SearchSource.LOCAL_INDEX:
            try:
                local_results = self._opensearch.search(
                    query, top_k=top_k, filters=filters
                )
            except Exception:
                logger.exception("FederatedSearchRouter: local OpenSearch search failed")
                if source == SearchSource.LOCAL_INDEX:
                    self.last_degraded = True

        if source == SearchSource.LOCAL_RRF:
            bm25f_results: list[dict] = []
            splade_results: list[dict] = []
            bm25f_ok = splade_ok = False
            draft = None
            scope = getattr(self._opensearch, "hydrate_scope", contextlib.nullcontext)
            with scope():
                try:
                    bm25f_results = self._opensearch.search(
                        query, top_k=top_k, mode="bm25f", filters=filters
                    )
                    bm25f_ok = True
                except Exception:
                    logger.exception("FederatedSearchRouter: BM25F search failed")
                if speculative_rerank.is_enabled():
                    draft = speculative_rerank.on_draft(query, bm25f_results, top_k)
                try:
                    splade_results = self._opensearch.search(
                        query, top_k=top_k, mode="splade", filters=filters
                    )
                    splade_ok = True
                except Exception:
                    logger.exception("FederatedSearchRouter: SPLADE search failed")
            if not bm25f_ok and not splade_ok:
                self.last_degraded = True
            merged = _rrf_merge(bm25f_results, splade_results, top_k)
            if draft is not None:
                speculative_rerank.bind(draft, merged)
            return merged

        if source == SearchSource.LIVE_API:
            return live_results[:top_k]
        if source == SearchSource.LOCAL_INDEX:
            return local_results[:top_k]

        return []
