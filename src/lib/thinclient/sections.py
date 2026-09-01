"""Hot/cold section vocabulary + classifier.

Ported from scripts/experiments/eval_sectioned_index.py (the measured 1M-doc eval). The live
corpus has no concepts metadata, so sections are derived from title+abstract
text. Assignment is PRIORITY-ORDERED DISJOINT: a doc lands in the first section
whose vocabulary matches it; `other` catches everything unmatched — mirroring
the OpenSearch `multi_match` OR-of-terms matchers used in the eval (standard
analyzer = lowercase word tokens, no stemming).
"""

from __future__ import annotations

import re

SECTIONS: list[tuple[str, str]] = [
    ("social_sciences",
     "political politics policy sociology economic economics social society "
     "education psychology law legal governance democracy election cultural "
     "anthropology history philosophy geography business management finance"),
    ("med_bio",
     "patient clinical disease cancer tumor cell gene protein medical health "
     "therapy treatment diagnosis biology biological neural brain immune "
     "infection molecular genetic physiology pharmacology"),
    ("phys_eng",
     "quantum physics material chemical chemistry molecular energy optical "
     "thermal mechanical engineering electron magnetic photon nanoparticle "
     "semiconductor fluid mechanics structural"),
    ("cs_math",
     "algorithm software computational machine learning network data model "
     "computer programming optimization mathematical theorem matrix graph "
     "statistical simulation"),
]

OTHER = "other"
SECTION_NAMES: list[str] = [name for name, _ in SECTIONS] + [OTHER]

ERA_BOUNDARY_YEAR = 2010
ERAS = ("recent", "archive")


def era_of(year: int | None) -> str:
    return "recent" if year and year >= ERA_BOUNDARY_YEAR else "archive"


def subsection_name(base: str, year: int | None) -> str:
    return f"{base}__{era_of(year)}"


def base_section(name: str) -> str:
    """'social_sciences__recent' -> 'social_sciences' (era-less names pass through)."""
    return name.split("__", 1)[0]


SUBSECTION_NAMES: list[str] = [f"{b}__{e}" for b in SECTION_NAMES for e in ERAS]

PERSONAS: dict[str, list[str]] = {
    "political_science": ["social_sciences__recent"],
    "political_science_historical": ["social_sciences__archive"],
    "computer_science": ["cs_math__recent"],
    "computer_science_historical": ["cs_math__archive"],
    "health_science": ["med_bio__recent"],
    "health_science_historical": ["med_bio__archive"],
    "interdisciplinary_cogsci": ["med_bio__recent", "cs_math__recent",
                                 "social_sciences__recent"],
    "contemporary": [f"{b}__recent" for b in SECTION_NAMES],
    "historical": [f"{b}__archive" for b in SECTION_NAMES],
    "all_hot": SUBSECTION_NAMES,
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SECTION_VOCABS: list[tuple[str, frozenset[str]]] = [
    (name, frozenset(vocab.split())) for name, vocab in SECTIONS
]


def classify_doc(title: str | None, abstract: str | None) -> str:
    """Return the section for a doc: first section whose vocab intersects the
    lowercase word tokens of title+abstract, else `other`."""
    tokens = set(_TOKEN_RE.findall(f"{title or ''} {abstract or ''}".lower()))
    for name, vocab in _SECTION_VOCABS:
        if tokens & vocab:
            return name
    return OTHER


def classify_query(query: str) -> str:
    """Best-effort section hint for a QUERY (used for cold-section unpack
    hints / routing telemetry — never for filtering results)."""
    return classify_doc(query, None)
