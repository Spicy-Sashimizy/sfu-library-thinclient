"""Dead-code guard backstop (docs/infrastructure/SCRIPT_HYGIENE_POLICY.md §7, 2026-10-11).

Every def/class in product Python (source/ outside source/tests/) and every
top-level function or window.SFU* export in web/lib/*.js must be referenced
from live code (its own file beyond the definition, or a non-test, non-archive
tracked file). Symbols only tests reach, or nothing reaches, fail unless
scripts/repo_tools/dead_code_allow.json names them with a reason; stale
allowlist entries fail too. The checker is scripts/repo_tools/dead_code_guard.py;
this test is the backstop for a clone without the hooks and the record of the
2026-10-11 codebase triage's end state (docs/infrastructure/CODEBASE_TRIAGE_2026-10-11.md).
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "repo_tools"))

import dead_code_guard  # noqa: E402


def test_product_tree_has_no_unreferenced_symbols():
    rows = dead_code_guard.scan()
    assert len(rows) > 400, "scan found implausibly few symbols; the tokenizer or scopes regressed"
    bad, stale = dead_code_guard.offenders(rows, dead_code_guard.load_allow())
    msg = "\n".join(f"{r['status']} {r['file']}:{r['line']} {r['symbol']}" for r in bad)
    assert not bad, f"unreferenced product symbols (remove them or allowlist with a reason):\n{msg}"
    assert not stale, f"stale dead_code_allow.json entries: {stale}"


def test_allowlist_entries_carry_reasons():
    allow = dead_code_guard.load_allow()
    for key, reason in allow.items():
        assert "::" in key, key
        assert isinstance(reason, str) and len(reason) >= 15, f"{key}: reason too short"


def test_guard_detects_a_planted_dead_symbol(tmp_path, monkeypatch):
    rows = dead_code_guard.scan()
    planted = dict(rows[0], key="source/lib/planted.py::never_called", status="DEAD", live=[], tests=[], own_uses=0)
    bad, _ = dead_code_guard.offenders(rows + [planted], {})
    assert any(r["key"] == "source/lib/planted.py::never_called" for r in bad)
    assert json.dumps(planted)
