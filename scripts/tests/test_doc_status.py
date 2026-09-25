"""Enforces the closed-tracks policy (.claude/CLAUDE.md, 2026-09-25).

A superseded spike was dispatched as pending work on 2026-09-25 because its
index row still read "SCAFFOLD, UNMEASURED". These four checks make that
impossible to repeat:

  (a) every live doc declares a `**Status:**` from the fixed vocabulary;
  (b) nothing CLOSED sits outside `docs/archive/` or `docs/deprecated/`;
  (c) no Active table of `docs/README.md` names a closed track;
  (d) every open-work heading in a live doc carries a dated reconciliation.

"Live" means `docs/**/*.md` outside `docs/archive/` and `docs/deprecated/`.
Failures name every offending file, so one run tells you the whole list.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
NOT_LIVE = ("archive", "deprecated")
STATUS_WINDOW = 8

OWNED_BY_OTHER_AGENTS = frozenset()
"""Files another agent is editing right now; they are skipped by (a), (b) and
(d) so a concurrent session is not blamed for a line it has not written yet.

THIS SET MUST BE EMPTIED once those agents add their `**Status:**` (and, where
the doc has an open-work heading, `Reconciled <date>`) lines. An exemption that
outlives its owner is exactly the stale-optimism hole these tests close.

EMPTIED 2026-09-25: the three dense/ordinals docs carry `**Status:** ACTIVE`
and are now checked like every other live doc.
"""

STATUS_RE = re.compile(
    r"^\*\*Status:\*\* ("
    r"ACTIVE"
    r"|DEFERRED \d{4}-\d{2}-\d{2} \([^)]+\)"
    r"|CLOSED (?:MEASURED|SUPERSEDED|DEAD|KILLED) \d{4}-\d{2}-\d{2}"
    r")( .*)?$"
)

CLOSED_MARKERS = ("SUPERSEDED", "DEAD", "KILLED", "CLOSED-UNRUNNABLE")
"""Matched case-sensitively: these are status tokens, and this repo writes them
in caps. Lowercase prose ("partially superseded") is a description, not a
verdict, and must not fail an Active row."""

NOT_CURRENT_RE = re.compile(r"not current", re.IGNORECASE)
HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
OPEN_WORK_RE = re.compile(r"next steps?|backlog|roadmap|open items|to ?do|pending",
                          re.IGNORECASE)
RECONCILED_RE = re.compile(r"Reconciled \d{4}-\d{2}-\d{2}")
RECONCILED_WINDOW = 15


def _live_docs():
    out = []
    for p in sorted(DOCS.rglob("*.md")):
        rel = p.relative_to(REPO).as_posix()
        if p.relative_to(DOCS).parts[0] in NOT_LIVE:
            continue
        if rel in OWNED_BY_OTHER_AGENTS:
            continue
        out.append((rel, p.read_text(encoding="utf-8").split("\n")))
    return out


def _status_of(lines):
    for line in lines[:STATUS_WINDOW]:
        m = STATUS_RE.match(line)
        if m:
            return m.group(1)
    return None


def test_owned_files_exemption_is_still_justified():
    """Every exempted path must still exist; a stale entry silently un-guards a
    doc that was renamed or deleted."""
    missing = [rel for rel in sorted(OWNED_BY_OTHER_AGENTS)
               if not (REPO / rel).is_file()]
    assert not missing, (
        "OWNED_BY_OTHER_AGENTS names paths that no longer exist; drop them:\n  "
        + "\n  ".join(missing))


def test_every_live_doc_declares_a_status():
    bad = [rel for rel, lines in _live_docs() if _status_of(lines) is None]
    assert not bad, (
        f"{len(bad)} live doc(s) have no `**Status:**` line from the closed-tracks "
        f"vocabulary in their first {STATUS_WINDOW} lines "
        "(ACTIVE | DEFERRED <date> (<why>) | CLOSED <MEASURED|SUPERSEDED|DEAD|KILLED> "
        "<date>):\n  " + "\n  ".join(bad))


def test_no_closed_doc_lives_outside_archive_or_deprecated():
    bad = [f"{rel} -> {status}" for rel, lines in _live_docs()
           if (status := _status_of(lines)) and status.startswith("CLOSED")]
    assert not bad, (
        "CLOSED docs must move to docs/archive/ (research record) or "
        "docs/deprecated/ (obsolete infra) in the same commit that closes them:\n  "
        + "\n  ".join(bad))


def _index_rows_by_section():
    sections = {}
    heading = None
    for line in (DOCS / "README.md").read_text(encoding="utf-8").split("\n"):
        m = HEADING_RE.match(line)
        if m:
            heading = m.group(1).strip()
            continue
        if heading and line.startswith("|") and not set(line) <= set("|- :"):
            sections.setdefault(heading, []).append(line)
    return sections


def test_active_tables_of_the_index_name_no_closed_track():
    """Pending-work triage reads only the Active tables, so a closed track
    surviving in one is the exact failure this policy exists to prevent."""
    offenders = []
    for heading, rows in _index_rows_by_section().items():
        if "Active" not in heading:
            continue
        for row in rows:
            hits = [m for m in CLOSED_MARKERS if m in row]
            if NOT_CURRENT_RE.search(row):
                hits.append("not current")
            if hits:
                offenders.append(f"[{heading}] {', '.join(hits)} in: {row[:120]}")
    assert not offenders, (
        "docs/README.md Active table(s) name a closed track; move the row to the "
        "Closed-tracks table:\n  " + "\n  ".join(offenders))


def test_open_work_headings_carry_a_reconciled_date():
    """A "next steps" / backlog / roadmap section with no dated reconciliation is
    how a finished arc keeps reading as pending work."""
    offenders = []
    for rel, lines in _live_docs():
        for i, line in enumerate(lines):
            m = HEADING_RE.match(line)
            if not m or not OPEN_WORK_RE.search(m.group(1)):
                continue
            window = lines[i + 1:i + 1 + RECONCILED_WINDOW]
            if not any(RECONCILED_RE.search(w) for w in window):
                offenders.append(f"{rel}:{i + 1} {m.group(1)[:80]}")
    assert not offenders, (
        f"open-work heading(s) with no `Reconciled <date>` line within "
        f"{RECONCILED_WINDOW} lines below:\n  " + "\n  ".join(offenders))
