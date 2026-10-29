from __future__ import annotations

from typing import Protocol

from ..models import Evidence


class Retriever(Protocol):
    name: str

    def retrieve(self, query: str, k: int = 5) -> list[Evidence]: ...


class ChainedRetriever:
    """Try retrievers in order; fall through to the next when one returns fewer
    than ``min_hits`` results. Used as "Zotero / lit review first, thin client
    second"."""

    name = "chained"

    def __init__(self, retrievers: list[Retriever], min_hits: int = 1):
        self.retrievers = retrievers
        self.min_hits = min_hits

    def retrieve(self, query: str, k: int = 5) -> list[Evidence]:
        collected: list[Evidence] = []
        for r in self.retrievers:
            try:
                hits = r.retrieve(query, k)
            except Exception as e:  # a failing leg never fails the audit
                hits = [Evidence(id=f"{r.name}:error", text=str(e), source=r.name, score=0.0,
                                 meta={"error": True})]
            collected.extend(h for h in hits if not h.meta.get("error"))
            if len(collected) >= self.min_hits:
                break
        return collected[:k]
