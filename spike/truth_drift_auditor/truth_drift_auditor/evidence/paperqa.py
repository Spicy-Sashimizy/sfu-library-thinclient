"""PaperQA2 retriever (manual, non-agentic mode) over Zotero PDFs and the
literature review.

IMPLEMENTED, UNTESTED in this container (paper-qa is not installed here). The
API surface below follows the PaperQA2 README read on 2026-10-29
(`Docs`, `Settings`, `agent_type="fake"`, `aadd`, `aget_evidence`,
`session.contexts[i].context / .text.text / .text.name / .score`). Verify
against the installed version's docstrings before the first run; the names are
the most likely points of breakage.

Why PaperQA2 (docs/01_RESEARCH_2026-10-29.md §replacements): Apache-2.0,
pushed 2026-10-26, native Zotero ingestion, PDF/Office/Markdown parsing, local
embeddings, Anthropic/Ollama/LiteLLM model backends.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from ..models import Evidence


class PaperQARetriever:
    name = "paperqa"

    def __init__(self, llm: str = "claude-haiku-5-5", summary_llm: str | None = None,
                 embedding: str = "sparse", evidence_k: int = 8, index_dir: str | None = None,
                 skip_summary: bool = True):
        try:
            from paperqa import Docs, Settings  # type: ignore
            from paperqa.settings import AgentSettings, AnswerSettings  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ImportError("pip install 'paper-qa[zotero,local]'") from e
        self._Docs = Docs
        self.settings = Settings(
            llm=llm,
            summary_llm=summary_llm or llm,
            embedding=embedding,                      # "sparse" = keyword only, no model call
            agent=AgentSettings(agent_type="fake"),   # fixed search->gather->answer, no agent
            answer=self._answer_settings(AnswerSettings, evidence_k, skip_summary),
        )
        self.docs = Docs()
        self.index_dir = index_dir

    @staticmethod
    def _answer_settings(AnswerSettings, evidence_k: int, skip_summary: bool):
        """``evidence_skip_summary=True`` keeps the retrieval leg model-free: raw
        chunks ranked by the (sparse or dense) embedding only, no per-chunk LLM
        summary/score. Falls back silently if the installed version lacks the field."""
        try:
            return AnswerSettings(evidence_k=evidence_k, answer_max_sources=evidence_k,
                                  evidence_skip_summary=skip_summary)
        except TypeError:
            return AnswerSettings(evidence_k=evidence_k, answer_max_sources=evidence_k)

    # ---- ingestion ---------------------------------------------------------
    async def aadd_directory(self, directory: str | Path,
                             exts: tuple[str, ...] = (".pdf", ".md", ".txt", ".docx", ".html")) -> int:
        n = 0
        for f in sorted(Path(directory).rglob("*")):
            if f.suffix.lower() in exts and f.is_file():
                await self.docs.aadd(str(f), docname=f.stem, settings=self.settings)
                n += 1
        return n

    async def aadd_zotero(self, limit: int = 200, query: str | None = None,
                          library_type: str = "user") -> int:
        """Pull PDFs attached to Zotero items. Needs ZOTERO_USER_ID and
        ZOTERO_API_KEY (read access) in the environment — Zotero *web* API."""
        from paperqa.contrib import ZoteroDB  # type: ignore
        if not os.environ.get("ZOTERO_USER_ID") or not os.environ.get("ZOTERO_API_KEY"):
            raise RuntimeError("set ZOTERO_USER_ID and ZOTERO_API_KEY")
        zot = ZoteroDB(library_type=library_type)
        n = 0
        kwargs = {"limit": limit}
        if query:
            kwargs.update({"q": query, "qmode": "everything"})
        for item in zot.iterate(**kwargs):
            if getattr(item, "pdf", None) is None:
                continue
            await self.docs.aadd(item.pdf, docname=item.key, settings=self.settings)
            n += 1
        return n

    def add_directory(self, directory: str | Path) -> int:
        return asyncio.run(self.aadd_directory(directory))

    def add_zotero(self, **kw) -> int:
        return asyncio.run(self.aadd_zotero(**kw))

    # ---- retrieval ---------------------------------------------------------
    async def aretrieve(self, query: str, k: int = 5) -> list[Evidence]:
        session = await self.docs.aget_evidence(query, settings=self.settings)
        out: list[Evidence] = []
        for c in getattr(session, "contexts", [])[:k]:
            text_obj = getattr(c, "text", None)
            raw = getattr(text_obj, "text", "") if text_obj is not None else ""
            name = getattr(text_obj, "name", "") if text_obj is not None else ""
            out.append(Evidence(
                id=name or f"paperqa#{len(out)}",
                text=(getattr(c, "context", "") or raw)[:2000],
                source=self.name, score=float(getattr(c, "score", 0) or 0),
                meta={"raw_excerpt": raw[:500]},
            ))
        return out

    def retrieve(self, query: str, k: int = 5) -> list[Evidence]:
        return asyncio.run(self.aretrieve(query, k))
