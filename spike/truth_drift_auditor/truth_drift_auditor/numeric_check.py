"""Deterministic numeric drift check: numbers written in a paragraph versus the
metrics store, routed through configured aliases (phrase -> metrics path).

No model is involved. This is the first thing that runs on every changed
paragraph and the only stage whose verdict is exact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Alias
from .metrics_store import MetricsStore
from .models import NumericFinding

# number with optional thousands separators, decimals, unicode minus, and a unit
_NUM_RE = re.compile(
    r"(?P<sign>[-−–+]?)\s*(?P<num>\d{1,3}(?:[,  ]\d{3})+|\d+)(?P<dec>\.\d+)?\s*"
    r"(?P<unit>%|percent|GB|GiB|MB|MiB|KB|TB|ms|µs|us|μs|s\b|×|x\b)?",
    re.UNICODE,
)
_UNIT_NORMALISE = {
    "percent": "%", "gib": "GB", "mib": "MB", "µs": "us", "μs": "us", "×": "x",
}
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class NumericMention:
    value: float
    unit: str
    quote: str
    start: int
    end: int


def extract_numbers(text: str) -> list[NumericMention]:
    out: list[NumericMention] = []
    for m in _NUM_RE.finditer(text):
        num = m.group("num").replace(",", "").replace(" ", "").replace(" ", "")
        dec = m.group("dec") or ""
        try:
            value = float(num + dec)
        except ValueError:
            continue
        if m.group("sign") in ("-", "−", "–"):
            value = -value
        unit = (m.group("unit") or "").strip()
        unit = _UNIT_NORMALISE.get(unit.lower(), unit)
        out.append(NumericMention(value, unit, m.group(0).strip(), m.start(), m.end()))
    return out


def _phrase_span(alias: Alias, sentence: str) -> tuple[int, int] | None:
    """Where the alias phrase matches in the sentence (None = no match)."""
    if alias.phrase.startswith("re:"):
        m = re.search(alias.phrase[3:], sentence, re.I)
        return m.span() if m else None
    i = sentence.lower().find(alias.phrase.lower())
    return (i, i + len(alias.phrase)) if i >= 0 else None


def _distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    """0 when the spans overlap, else the gap between them."""
    if a[0] < b[1] and b[0] < a[1]:
        return 0
    return b[0] - a[1] if b[0] >= a[1] else a[0] - b[1]


def check_paragraph(text: str, store: MetricsStore, aliases: list[Alias]) -> list[NumericFinding]:
    """For each sentence that mentions an alias phrase, compare every number with a
    compatible unit against the alias' expected value. Sign is compared on
    magnitude for percentages written as "17.6 % smaller" vs "-17.6".
    """
    findings: list[NumericFinding] = []
    for sentence in _SENT_SPLIT.split(text):
        mentions = extract_numbers(sentence)
        if not mentions:
            continue
        for alias in aliases:
            span = _phrase_span(alias, sentence)
            if span is None:
                continue
            expected = store.get(alias.path)
            if expected is None:
                continue
            candidates = [m for m in mentions if (not alias.unit) or m.unit == alias.unit]
            if not candidates:
                continue
            # the number the sentence attaches to the phrase: nearest to (or inside) the
            # phrase match; ties broken by closeness to the expected magnitude
            best = min(candidates, key=lambda m: (_distance(span, (m.start, m.end)),
                                                  abs(abs(m.value) - abs(expected))))
            denom = abs(expected) if expected else 1.0
            rel = abs(abs(best.value) - abs(expected)) / denom
            findings.append(NumericFinding(
                phrase=alias.phrase, quote=best.quote, written=best.value,
                expected=expected, unit=alias.unit or best.unit, path=alias.path,
                rel_error=round(rel, 4), ok=rel <= alias.tolerance_rel,
            ))
    return findings
