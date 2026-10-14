"""CrossRef enrichment of normalized work metadata before a Zotero save.

Input is the flat metadata dict produced by ``openalex.normalize_work`` /
``fetch_crossref_work``; ``enrich_metadata_from_crossref`` fills missing
authors/date/source from CrossRef. The APA/MLA/Chicago/BibTeX/RIS formatters
left with the citation and export MCP tools (owner decision 2026-10-12).
"""

import logging

logger = logging.getLogger("sfu_library_mcp")


def enrich_metadata_from_crossref(metadata: dict) -> dict:
    """Fill in missing citation fields using CrossRef API.

    Only called when key fields (authors, date, source) are missing
    and a DOI is available. Returns the same metadata dict, enriched.
    """
    doi = metadata.get("doi", "")
    if not doi:
        return metadata

    missing_authors = not metadata.get("authors")
    missing_date = not metadata.get("date")
    missing_source = not metadata.get("source")

    if not (missing_authors or missing_date or missing_source):
        return metadata

    try:
        from lib.openalex import fetch_crossref_work
        cr = fetch_crossref_work(doi)
    except Exception:
        return metadata

    if not cr:
        return metadata

    logger.info("Enriching metadata from CrossRef for DOI %s", doi)

    if missing_authors and cr.get("authors"):
        metadata["authors"] = cr["authors"]
        metadata["creators"] = cr["authors"]
    if missing_date and cr.get("date"):
        metadata["date"] = cr["date"]
    if missing_source and cr.get("source"):
        metadata["source"] = cr["source"]

    for field in ("volume", "issue", "spage", "epage", "pages", "publisher"):
        if not metadata.get(field) and cr.get(field):
            metadata[field] = cr[field]

    return metadata
