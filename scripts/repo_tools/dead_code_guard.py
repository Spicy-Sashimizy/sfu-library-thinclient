"""Unreferenced-symbol guard for the product tree (source/ and web/lib), with an allowlist.

Lifecycle: library
Doc: docs/infrastructure/SCRIPT_HYGIENE_POLICY.md

Every ``def``/``class`` in product Python (``source/`` outside ``source/tests/``)
and every top-level ``function``/``window.X.y = `` export in ``web/lib/*.js``
must be referenced by name somewhere other than its own definition line:
inside its own file (a second occurrence of the identifier), or in another
tracked file under ``source/ scripts/ spike/ web/ deploy/ .claude/`` that is
not a test and not under an ``archive/`` directory. A symbol whose only
references are tests is reported as TEST-ONLY; one with no reference at all
as DEAD. Both fail the guard unless ``dead_code_allow.json`` (next to this
file) names them with a reason; allowlist entries that no longer match a
symbol also fail, so the list cannot go stale. Keys are
``<repo path>::<qualified name>`` and may use ``fnmatch`` wildcards.

Usage:
  dead_code_guard.py            exit 1 and list the offenders
  dead_code_guard.py --report   JSON of every symbol with its reference split (never fails)
"""

import argparse
import ast
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ALLOW = Path(__file__).resolve().with_name("dead_code_allow.json")
REF_SCOPES = ("source/", "scripts/", "spike/", "web/", "deploy/", ".claude/")
PRODUCT_PY = ("source/",)
PRODUCT_JS = ("web/lib/",)
TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
JS_DEF = re.compile(r"^\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|^\s*window\.(?:SFUApi|SFUMock|SFUUI)\.([A-Za-z_$][\w$]*)\s*=", re.M)


def _tracked() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", *[s.rstrip("/") for s in REF_SCOPES]], capture_output=True, check=False).stdout
    return [p for p in out.decode().split("\0") if p]


def is_test(rel: str) -> bool:
    name = Path(rel).name
    return "/tests/" in rel or name.startswith("test_") or name.startswith("verify_") or rel.startswith("scripts/gui_testbed/")


def is_archive(rel: str) -> bool:
    return "/archive/" in rel or rel.startswith("archive/")


def py_symbols(src: bytes) -> list[tuple[str, str, int]]:
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return []
    out: list[tuple[str, str, int]] = []

    def walk(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not (child.name.startswith("__") and child.name.endswith("__")):
                    out.append((prefix + child.name, child.name, child.lineno))
                if isinstance(child, ast.ClassDef):
                    walk(child, prefix + child.name + ".")

    walk(tree)
    return out


def js_symbols(text: str) -> list[tuple[str, str, int]]:
    out = []
    for m in JS_DEF.finditer(text):
        name = m.group(1) or m.group(2)
        out.append((name, name, text.count("\n", 0, m.start()) + 1))
    return out


def scan() -> list[dict]:
    files = _tracked()
    texts: dict[str, str] = {}
    for rel in files:
        if is_archive(rel) or rel.endswith((".png", ".jpg", ".gif", ".ico", ".woff", ".woff2", ".zst", ".bin", ".npy", ".sqlite")):
            continue
        try:
            texts[rel] = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    tokens: dict[str, set[str]] = {rel: set(TOKEN.findall(t)) for rel, t in texts.items()}
    counts: dict[str, dict[str, int]] = {}
    rows: list[dict] = []
    for rel, text in texts.items():
        if rel.startswith(PRODUCT_PY) and rel.endswith(".py") and not is_test(rel):
            syms = py_symbols(text.encode())
        elif rel.startswith(PRODUCT_JS) and rel.endswith(".js"):
            syms = js_symbols(text)
        else:
            continue
        if rel not in counts:
            counts[rel] = {}
        for qual, name, lineno in syms:
            if name not in counts[rel]:
                counts[rel][name] = len(re.findall(r"\b" + re.escape(name) + r"\b", text))
            own_uses = counts[rel][name] - sum(1 for q, n, _ in syms if n == name)
            live, tests = [], []
            for other, toks in tokens.items():
                if other == rel or name not in toks:
                    continue
                (tests if is_test(other) else live).append(other)
            status = "LIVE" if live or own_uses > 0 else ("TEST-ONLY" if tests else "DEAD")
            rows.append({"key": f"{rel}::{qual}", "file": rel, "symbol": qual, "line": lineno, "own_uses": own_uses,
                         "live": sorted(live), "tests": sorted(tests), "status": status})
    return rows


def load_allow() -> dict[str, str]:
    return json.loads(ALLOW.read_text()) if ALLOW.exists() else {}


def allowed(key: str, allow: dict[str, str]) -> bool:
    return any(fnmatch.fnmatchcase(key, pat) for pat in allow)


def offenders(rows: list[dict], allow: dict[str, str]) -> tuple[list[dict], list[str]]:
    bad = [r for r in rows if r["status"] != "LIVE" and not allowed(r["key"], allow)]
    keys = {r["key"] for r in rows}
    stale = [pat for pat in allow if not any(fnmatch.fnmatchcase(k, pat) for k in keys)]
    return bad, stale


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)
    rows = scan()
    if args.report:
        print(json.dumps(rows, indent=1))
        return 0
    bad, stale = offenders(rows, load_allow())
    for r in bad:
        print(f"{r['status']:9s} {r['file']}:{r['line']} {r['symbol']}  tests={len(r['tests'])}")
    for pat in stale:
        print(f"STALE-ALLOW {pat}")
    print(f"dead_code_guard: {len(rows)} symbols, {len(bad)} unreferenced, {len(stale)} stale allowlist entries")
    return 1 if bad or stale else 0


if __name__ == "__main__":
    sys.exit(main())
