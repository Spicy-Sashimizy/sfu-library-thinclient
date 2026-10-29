"""The audit pipeline: deterministic -> tier 1 -> (escalation) -> tier 2.

``Auditor.audit_paragraph`` is the unit of work (one changed paragraph).
``Auditor.audit_document`` runs batch mode over a Markdown/text file, which is
the pilot's first mode (docs/04_PILOT_PLAN.md step 3) — the Google Docs
watcher just feeds the same function.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .config import Config
from .evidence.base import Retriever
from .metrics_store import MetricsStore
from .models import Paragraph, ParagraphReport
from .numeric_check import check_paragraph
from .tier1_haiku import VerdictClient
from .vale_runner import run_vale, vale_available


def split_paragraphs(text: str) -> list[Paragraph]:
    out: list[Paragraph] = []
    pos = 0
    for i, raw in enumerate(re.split(r"\n\s*\n", text)):
        chunk = raw.strip()
        start = text.find(raw, pos)
        pos = start + len(raw) if start >= 0 else pos
        if not chunk or chunk.startswith("#"):
            continue
        out.append(Paragraph(index=i, text=chunk, start=start, end=start + len(raw),
                             sha1=hashlib.sha1(chunk.encode("utf-8")).hexdigest()))
    return out


@dataclass
class EscalationPolicy:
    low_confidence: float = 0.7
    min_contradicted_in_window: int = 2
    window: int = 5                 # paragraphs
    numeric_mismatch_escalates: bool = False


@dataclass
class Auditor:
    store: MetricsStore
    retriever: Optional[Retriever]
    tier1: Optional[VerdictClient]
    config: Config
    tier2: Optional[Callable[[list[ParagraphReport]], str]] = None
    policy: EscalationPolicy = field(default_factory=EscalationPolicy)
    evidence_k: int = 5
    use_vale: bool = True
    _recent: list[ParagraphReport] = field(default_factory=list)

    def audit_paragraph(self, para: Paragraph) -> ParagraphReport:
        rep = ParagraphReport(paragraph=para)
        # 1. deterministic
        rep.numeric = check_paragraph(para.text, self.store, self.config.aliases)
        if self.use_vale and vale_available():
            rep.vale = run_vale(para.text, self.config.path("vale.config"))
        notes = []
        for f in rep.numeric:
            tag = "OK" if f.ok else "MISMATCH"
            notes.append(f"{tag}: '{f.quote}' written for '{f.phrase}'; measured {f.expected}{f.unit} "
                         f"({f.path}); rel error {f.rel_error}")
        # 2. evidence
        if self.retriever is not None:
            try:
                rep.evidence = self.retriever.retrieve(para.text, self.evidence_k)
            except Exception as e:
                rep.errors.append(f"retrieval: {e}")
        # 3. tier 1
        if self.tier1 is not None:
            try:
                r = self.tier1.verdict(para.text, rep.evidence, notes)
                rep.claims = r.claims
                rep.tier1_usage = r.usage
                rep.escalate, rep.escalate_reason = r.escalate, r.escalate_reason
                if r.refused:
                    rep.errors.append("tier1 refused")
            except Exception as e:
                rep.errors.append(f"tier1: {e}")
        # 4. escalation policy (tool-side, independent of the model's own flag)
        self._recent = (self._recent + [rep])[-self.policy.window:]
        contradicted = [c for c in rep.claims if c.verdict == "CONTRADICTED"]
        if any(c.confidence < self.policy.low_confidence for c in contradicted):
            rep.escalate, rep.escalate_reason = True, (rep.escalate_reason or "low-confidence contradiction")
        n_window = sum(1 for r in self._recent if any(c.verdict == "CONTRADICTED" for c in r.claims))
        if n_window >= self.policy.min_contradicted_in_window:
            rep.escalate, rep.escalate_reason = True, (rep.escalate_reason or f"{n_window} contradicted paragraphs in window")
        if self.policy.numeric_mismatch_escalates and any(not f.ok for f in rep.numeric):
            rep.escalate, rep.escalate_reason = True, (rep.escalate_reason or "numeric mismatch")
        # 5. tier 2
        if rep.escalate and self.tier2 is not None:
            try:
                rep.tier2 = self.tier2([r for r in self._recent if r.drifted or r is rep])
            except Exception as e:
                rep.errors.append(f"tier2: {e}")
        return rep

    def audit_document(self, path: str | Path) -> list[ParagraphReport]:
        text = Path(path).read_text(encoding="utf-8")
        return [self.audit_paragraph(p) for p in split_paragraphs(text)]
