"""Dependency-free retriever over a directory of Markdown / text files.

Chunks on blank lines, scores by weighted token overlap (IDF-like), returns the
top-k chunks as Evidence with id ``<file>#<chunk>``. Good enough for the
offline demo and for a literature review you already have as text; PaperQA2
replaces it for PDFs and real ranking.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from ..models import Evidence

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9\-]+|\d+(?:\.\d+)?")
_STOP = set("the a an and or of to in on for with by is are was were be been that this these those it its as at from into than then which who whom whose what when where why how not no we our they their you your i he she".split())


def _tokens(s: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(s) if t.lower() not in _STOP]


class LocalTextRetriever:
    name = "local"

    def __init__(self, directory: str | Path, exts: tuple[str, ...] = (".md", ".txt")):
        self.directory = Path(directory)
        self.chunks: list[tuple[str, str]] = []  # (id, text)
        self.df: Counter = Counter()
        self._load(exts)

    def _load(self, exts) -> None:
        for f in sorted(self.directory.rglob("*")):
            if f.suffix.lower() not in exts or not f.is_file():
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            for i, chunk in enumerate(p.strip() for p in re.split(r"\n\s*\n", text)):
                if len(chunk) < 40:
                    continue
                cid = f"{f.relative_to(self.directory)}#{i}"
                self.chunks.append((cid, chunk))
                self.df.update(set(_tokens(chunk)))
        self.n = max(1, len(self.chunks))

    def retrieve(self, query: str, k: int = 5) -> list[Evidence]:
        q = Counter(_tokens(query))
        if not q:
            return []
        scored = []
        for cid, text in self.chunks:
            ct = Counter(_tokens(text))
            score = 0.0
            for tok, qf in q.items():
                if tok in ct:
                    idf = math.log(1 + self.n / (1 + self.df[tok]))
                    score += idf * min(qf, ct[tok])
            if score > 0:
                scored.append((score, cid, text))
        scored.sort(reverse=True)
        return [Evidence(id=cid, text=text, source=self.name, score=round(s, 3))
                for s, cid, text in scored[:k]]
