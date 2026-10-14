"""Search-query sanitization for the MCP tools (HTML and null-byte stripping,
length and boolean-operator caps)."""

import re
import logging

logger = logging.getLogger("sfu_library_mcp")

MAX_QUERY_LENGTH = 1000


def sanitize_search_query(query: str) -> str:
    """Sanitize a search query to prevent injection and XSS.

    Backward-compatible wrapper around sanitize_search_query_advanced().

    Args:
        query: Raw user search query.

    Returns:
        Sanitized query string.
    """
    return sanitize_search_query_advanced(query)


_MAX_BOOLEAN_OPERATORS = 30


def sanitize_search_query_advanced(query: str) -> str:
    """Sanitize a search query while preserving boolean search syntax.

    Preserves:
    - Double quotes (phrase search)
    - Boolean operators AND, OR, NOT (uppercase only)
    - Wildcards ? and *

    Still strips:
    - HTML tags
    - Null bytes
    - Collapses whitespace, enforces max length

    Args:
        query: Raw user search query.

    Returns:
        Sanitized query string safe for search APIs.
    """
    if not query:
        return ""

    sanitized = query.replace("\x00", "")

    sanitized = re.sub(r"<[^>]*>", "", sanitized)

    if len(sanitized) > MAX_QUERY_LENGTH:
        sanitized = sanitized[:MAX_QUERY_LENGTH]
        logger.warning("Query truncated to %d characters", MAX_QUERY_LENGTH)

    sanitized = re.sub(r"\s+", " ", sanitized).strip()

    bool_count = len(re.findall(r'\b(?:AND|OR|NOT)\b', sanitized))
    if bool_count > _MAX_BOOLEAN_OPERATORS:
        parts = re.split(r'(\b(?:AND|OR|NOT)\b)', sanitized)
        kept: list[str] = []
        op_count = 0
        for part in parts:
            if re.fullmatch(r'AND|OR|NOT', part):
                op_count += 1
                if op_count > _MAX_BOOLEAN_OPERATORS:
                    break
            kept.append(part)
        sanitized = "".join(kept).strip()
        logger.warning("Query truncated to %d boolean operators", _MAX_BOOLEAN_OPERATORS)

    return sanitized
