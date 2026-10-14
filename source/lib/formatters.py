"""Text formatters for MCP tool output.

Turns OpenAlex results, library-database registry entries and Semantic
Scholar papers into the plain-text blocks the MCP tools return.
"""


def format_openalex_results(data: dict, query: str = "") -> str:
    """Format OpenAlex search results for display."""
    results = data.get("results", [])
    meta = data.get("meta", {})
    total = meta.get("count", len(results))

    if not results:
        return "No results found."

    output = [f"Found {total:,} total results\n", "=" * 60 + "\n"]

    for i, work in enumerate(results, 1):
        title = work.get("title", "No title")
        authors = work.get("authors", [])
        author_str = "; ".join(authors[:3])
        if len(authors) > 3:
            author_str += f" et al. (+{len(authors) - 3} more)"
        date = work.get("date", "")
        source = work.get("source", "")
        doi = work.get("doi", "")
        is_oa = work.get("is_oa", False)
        cited = work.get("cited_by_count", 0)
        topics = work.get("topics", [])
        abstract = work.get("abstract", "")
        openalex_id = work.get("openalex_id", "")

        output.append(f"{i}. {title}\n")
        if author_str:
            output.append(f"   Authors: {author_str}\n")
        if date:
            output.append(f"   Date: {date}\n")
        if source:
            output.append(f"   Source: {source}\n")
        if doi:
            output.append(f"   DOI: {doi}\n")
        if topics:
            output.append(f"   Topics: {', '.join(topics[:4])}\n")
        output.append(f"   Open Access: {'Yes' if is_oa else 'No'}")
        if cited:
            output.append(f"  |  Cited by: {cited}")
        output.append("\n")
        if abstract:
            snippet = abstract[:250]
            if len(abstract) > 250:
                snippet += "..."
            output.append(f"   Abstract: {snippet}\n")
        if openalex_id:
            output.append(f"   ID: {openalex_id}\n")
        output.append("\n")

    if query:
        output.append(f"--- Search: {query} ---\n")

    return "".join(output)


def format_library_database(doc: dict) -> str:
    """Format a single library database-registry record."""
    name = doc.get("name", "Unknown")
    description = doc.get("description", "")
    url = doc.get("url", "")
    provider = doc.get("provider", "")
    subjects = doc.get("subjects", [])
    content_types = doc.get("contentTypes", [])
    is_free = doc.get("free") is True or str(doc.get("free", "")).lower() == "true"
    needs_proxy = doc.get("proxy") is True or str(doc.get("proxy", "")).lower() == "true"
    public_note = doc.get("publicNote", "")

    lines = [f"**{name}**"]
    if provider:
        lines.append(f"Provider: {provider}")
    if content_types:
        ct = content_types if isinstance(content_types, list) else [content_types]
        lines.append(f"Type: {', '.join(ct)}")
    if subjects:
        s = subjects if isinstance(subjects, list) else [subjects]
        lines.append(f"Subjects: {', '.join(s[:5])}")
    lines.append(f"Access: {'Free' if is_free else 'Duck Library subscription'}" +
                 (" (EZProxy required)" if needs_proxy else ""))
    if url:
        lines.append(f"URL: {url}")
    if description:
        snippet = description[:200] + ("..." if len(description) > 200 else "")
        lines.append(f"Description: {snippet}")
    if public_note:
        lines.append(f"Note: {public_note}")
    return "\n".join(lines)


def format_library_databases_list(docs: list[dict], query: str = "") -> str:
    """Format a list of library database-registry records."""
    if not docs:
        return "No databases found."

    header = f"Found {len(docs)} database(s)"
    if query:
        header += f" for '{query}'"
    output = [header + "\n", "=" * 60 + "\n"]

    for i, doc in enumerate(docs, 1):
        output.append(f"{i}. {format_library_database(doc)}\n\n")

    return "".join(output)


def format_semantic_scholar_papers(papers: list[dict], label: str = "Results") -> str:
    """Format Semantic Scholar paper list."""
    if not papers:
        return "No results found."

    output = [f"{label} ({len(papers)})\n", "=" * 60 + "\n"]
    for i, p in enumerate(papers, 1):
        title = p.get("title", "No title")
        authors = "; ".join(p.get("authors", [])[:3])
        year = p.get("year", "")
        doi = p.get("doi", "")
        cited = p.get("citation_count", 0)
        tldr = p.get("tldr", "")
        oa_pdf = p.get("open_access_pdf", "")

        output.append(f"{i}. {title}\n")
        if authors:
            output.append(f"   Authors: {authors}\n")
        if year:
            output.append(f"   Year: {year}\n")
        if doi:
            output.append(f"   DOI: {doi}\n")
        if cited:
            output.append(f"   Cited by: {cited}\n")
        if tldr:
            output.append(f"   TLDR: {tldr}\n")
        if oa_pdf:
            output.append(f"   PDF: {oa_pdf}\n")
        output.append("\n")

    return "".join(output)
