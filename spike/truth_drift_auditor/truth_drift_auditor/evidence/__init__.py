"""Evidence retrievers. Every retriever implements ``retrieve(query, k) -> list[Evidence]``.

- local_text: dependency-free token-overlap scorer over a directory of .md/.txt
  files (offline tests, and a literature review before PaperQA2 is set up)
- paperqa: PaperQA2 manual mode over Zotero PDFs + the literature review
- thinclient: the SFU library thin client's POST /api/search (150M works + live OpenAlex)
"""
from .base import Retriever, ChainedRetriever  # noqa: F401
