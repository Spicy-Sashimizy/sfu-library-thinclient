"""Plain dataclasses shared by every stage of the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional
import json

VERDICTS = ("SUPPORTED", "CONTRADICTED", "NO_EVIDENCE", "NOT_CHECKABLE")


@dataclass
class Paragraph:
    index: int
    text: str
    start: int = 0          # char offset in the source document (Google Docs startIndex when known)
    end: int = 0
    sha1: str = ""


@dataclass
class Evidence:
    id: str                 # citation key / openalex id / doi / file#chunk
    text: str
    source: str             # "paperqa" | "thinclient" | "local" | "metrics"
    score: float = 0.0
    meta: dict = field(default_factory=dict)


@dataclass
class NumericFinding:
    phrase: str             # alias phrase that matched
    quote: str              # the number as written in the draft
    written: float
    expected: float
    unit: str
    path: str               # metrics file:dotted.path
    rel_error: float
    ok: bool


@dataclass
class ClaimVerdict:
    quote: str              # verbatim span from the paragraph (located by str.find)
    claim: str
    verdict: str            # one of VERDICTS
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    note: str = ""
    span: Optional[tuple[int, int]] = None


@dataclass
class ParagraphReport:
    paragraph: Paragraph
    numeric: list[NumericFinding] = field(default_factory=list)
    vale: list[dict] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    claims: list[ClaimVerdict] = field(default_factory=list)
    escalate: bool = False
    escalate_reason: str = ""
    tier2: Optional[str] = None
    tier1_usage: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def drifted(self) -> bool:
        if any(not f.ok for f in self.numeric):
            return True
        return any(c.verdict == "CONTRADICTED" for c in self.claims)

    def summary(self) -> dict[str, Any]:
        return {
            "paragraph": self.paragraph.index,
            "drifted": self.drifted,
            "numeric_mismatches": [asdict(f) for f in self.numeric if not f.ok],
            "claims": [asdict(c) for c in self.claims],
            "vale": self.vale,
            "escalate": self.escalate,
            "escalate_reason": self.escalate_reason,
            "tier2": self.tier2,
            "errors": self.errors,
        }

    def to_json(self) -> str:
        return json.dumps(self.summary(), ensure_ascii=False, indent=1)
