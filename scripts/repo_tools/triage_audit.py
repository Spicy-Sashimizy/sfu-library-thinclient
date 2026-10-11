"""Audit triage ledgers against the repository (Fable audit step of a triage wave).

Lifecycle: harness
Doc: docs/infrastructure/SCRIPT_HYGIENE_POLICY.md

Reads every ledger table under a ledger directory (default: the 2026-10-11
script triage; ``--ledger-dir`` selects another wave) and re-derives, from
git, what the classification agents claimed:

FILE rows (tables with ``Path`` and ``Class`` columns): (1) coverage, every
tracked file under the audited scopes (``--scope``, default ``scripts``) has
exactly one row; (2) for every DEAD row, zero live references outside the
file (basename and module stem, over tracked docs, scripts, spike, web, src,
deploy, .claude, pytest.ini, CONTRIBUTING.md, README.md; hits inside
``archive/``, ``docs/deprecated/``, the ledgers and the 2026-10-10 audit
reports are reported but do not count), no mention in
data/eval_results/INDEX.md, not a scripts/ root entry point, and the recorded
last-commit hash matches; (3) for every MISPLACED, ARCHIVE, GATED-ORPHAN or
TEST-ONLY row, the current reference split so the applying commit can repoint
every citation; (4) every file under an archive/ family carries a closed
banner.

SYMBOL rows (tables that also have a ``Symbol`` column): the symbol exists
in the file at HEAD, and its word-bounded references across the code scopes
are split into live / test / archive-only. A DEAD symbol must have no live
and no test reference; a TEST-ONLY symbol no live reference. Any row whose
class claim the evidence contradicts is a failure.

Writes data/eval_results/<out>_<date>.json and prints a summary. Exit 1 when
any DEAD or TEST-ONLY claim fails or coverage is incomplete.
"""

import argparse
import ast
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER_DIR = REPO / "docs" / "infrastructure" / "script_triage_2026-10-11"
REF_SCOPES = ["docs", "scripts", "spike", "web", "src", "deploy", ".claude", "pytest.ini", "CONTRIBUTING.md", "README.md"]
CODE_SCOPES = ["scripts", "spike", "web", "src", "deploy", ".claude", "pytest.ini"]
ROOT_ALLOW_SRC = REPO / "scripts" / "repo_tools" / "check_script_placement.py"
BANNER_RE = re.compile(r"\b(CLOSED|SUPERSEDED|ARCHIVED)\b")
NON_LIVE = ("/archive/", "docs/deprecated/", "docs/archive/", "repo_reorg_2026-10-10_audit_reports/", "_triage_2026-10-11/", "TRIAGE_2026-10-11.md")
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
PATH_RE = re.compile(r"`?((?:src|scripts|spike|web|deploy|docs|models|scaffold|\.claude)/[^`\s|]+|[A-Za-z0-9_.\-]+\.(?:txt|ini|cff|md|yml|yaml|toml|json|gitignore|gitattributes))`?")


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True).stdout


def parse_ledgers(ledger_dir: Path) -> tuple[list[dict], list[dict]]:
    files: list[dict] = []
    symbols: list[dict] = []
    for md in sorted(ledger_dir.glob("*.md")):
        header: list[str] | None = None
        for line in md.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.startswith("|"):
                header = None if header and not line.strip() else header
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if header is None:
                if "Path" in cells and "Class" in cells:
                    header = cells
                continue
            if set(cells[0]) <= set("-: "):
                continue
            if len(cells) < len(header):
                cells += [""] * (len(header) - len(cells))
            row = dict(zip(header, cells))
            row["_ledger"] = md.name
            m = PATH_RE.match(row.get("Path", "").strip())
            if not m:
                continue
            row["Path"] = m.group(1)
            if "Symbol" in header:
                idents = [t for t in re.findall(r"`([^`]+)`", row["Symbol"]) if IDENT_RE.fullmatch(t)]
                raw = row["Symbol"].strip("`").strip()
                row["Symbol"] = idents[0] if idents else (raw if IDENT_RE.fullmatch(raw) else "")
                row["_idents"] = idents or ([raw] if IDENT_RE.fullmatch(raw) else [])
                symbols.append(row)
            else:
                files.append(row)
    return files, symbols


def _split(hits: list[str], rel: str) -> dict[str, list[str]]:
    out = {"live": [], "tests": [], "archive_only": []}
    for h in hits:
        if not h or h == rel:
            continue
        if any(tag in h for tag in NON_LIVE):
            out["archive_only"].append(h)
        elif "/tests/" in h or Path(h).name.startswith("test_"):
            out["tests"].append(h)
        else:
            out["live"].append(h)
    return out


def references(rel: str) -> dict[str, dict[str, list[str]]]:
    base = Path(rel).name
    stem = Path(rel).stem
    out: dict[str, dict[str, list[str]]] = {}
    for needle in sorted({base, stem} if len(stem) > 3 else {base}):
        hits = _git("grep", "-l", "-F", needle, "--", *REF_SCOPES).split("\n")
        out[needle] = _split(hits, rel)
    return out


def symbol_exists(rel: str, qual: str) -> bool:
    p = REPO / rel
    if not p.exists():
        return False
    if rel.endswith(".py"):
        try:
            tree = ast.parse(p.read_bytes())
        except (SyntaxError, ValueError):
            return False
        names: set[str] = set()

        def walk(node, prefix=""):
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(prefix + ch.name)
                    if isinstance(ch, ast.ClassDef):
                        walk(ch, prefix + ch.name + ".")

        walk(tree)
        return qual in names or qual.split(".")[-1] in {n.split(".")[-1] for n in names}
    text = p.read_text(errors="replace")
    return re.search(r"\b" + re.escape(qual.split(".")[-1]) + r"\b", text) is not None


def symbol_references(rel: str, qual: str) -> dict[str, list[str]]:
    name = qual.split(".")[-1]
    hits = _git("grep", "-l", "-w", "-F", name, "--", *CODE_SCOPES).split("\n")
    split = _split(hits, rel)
    split["docs"] = [h for h in _git("grep", "-l", "-w", "-F", name, "--", "docs").split("\n") if h and not any(t in h for t in NON_LIVE)]
    return split


def root_allowlist() -> set[str]:
    src = ROOT_ALLOW_SRC.read_text()
    block = src.split("SCRIPTS_ROOT_ALLOW = {", 1)[1].split("}", 1)[0]
    return set(re.findall(r'"([^"]+)"', block))


def _cls(row: dict) -> str:
    c = row.get("Class", "").strip().strip("*").strip()
    return c.split()[0].upper().rstrip(",;") if c else "UNCLASSIFIED"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger-dir", default=str(DEFAULT_LEDGER_DIR))
    ap.add_argument("--scope", nargs="+", default=["scripts"], help="tracked path prefixes the ledgers must cover")
    ap.add_argument("--out", default="script_triage_audit")
    args = ap.parse_args(argv)
    ledger_dir = Path(args.ledger_dir)
    if not ledger_dir.is_absolute():
        ledger_dir = REPO / ledger_dir

    files, symbols = parse_ledgers(ledger_dir)
    tracked_all = {p for p in _git("ls-files").split("\n") if p}
    tracked = {p for p in tracked_all if any(p == s or p.startswith(s.rstrip("/") + "/") for s in args.scope)}
    applied = [r for r in files if _cls(r) in ("DELETED", "MOVED")]
    files = [r for r in files if r not in applied]
    ledgered = {r["Path"] for r in files}
    dup = sorted({p for p in ledgered if sum(1 for r in files if r["Path"] == p) > 1})
    coverage = {"tracked": len(tracked), "ledgered": len(ledgered),
                "missing_from_ledgers": sorted(tracked - ledgered),
                "ledgered_but_untracked": sorted(p for p in ledgered - tracked_all),
                "ledgered_out_of_scope": sorted(p for p in (ledgered & tracked_all) - tracked), "duplicates": dup}
    allow = root_allowlist()
    index_md = REPO / "data" / "eval_results" / "INDEX.md"
    index_text = index_md.read_text(errors="replace") if index_md.exists() else ""

    dead_checks, repoint, banner_missing, by_class = [], [], [], {}
    for r in files:
        cls = _cls(r)
        by_class[cls] = by_class.get(cls, 0) + 1
        rel = r["Path"]
        if cls == "DEAD":
            refs = references(rel)
            n_live = sum(len(v["live"]) + len(v["tests"]) for v in refs.values())
            head_hash = _git("log", "-1", "--format=%h", "--", rel).strip()
            claimed = re.findall(r"\b[0-9a-f]{7,40}\b", " ".join(r.values()))
            hash_ok = any(head_hash.startswith(c[:7]) or c.startswith(head_hash) for c in claimed)
            in_index = Path(rel).name in index_text
            is_root = rel.startswith("scripts/") and len(Path(rel).parts) == 2 and Path(rel).name in allow
            ok = n_live == 0 and not in_index and not is_root and hash_ok and (REPO / rel).exists()
            dead_checks.append({"path": rel, "ledger": r["_ledger"], "refs": refs, "n_live_refs": n_live,
                                "in_eval_index": in_index, "root_entry_point": is_root,
                                "last_commit": head_hash, "hash_recorded": hash_ok, "pass": ok})
        elif cls in ("MISPLACED", "ARCHIVE", "GATED-ORPHAN", "TEST-ONLY", "REVIEW", "OWNER-DECISION"):
            refs = references(rel)
            repoint.append({"path": rel, "class": cls, "ledger": r["_ledger"], "proposed": r.get("Proposed action", ""),
                            "n_live_refs": sum(len(v["live"]) for v in refs.values()), "refs": refs})
        if "/archive/" in rel and Path(rel).suffix in (".py", ".sh", ".md", ".mjs", ".js"):
            try:
                with (REPO / rel).open(errors="replace") as fh:
                    head = "".join(fh.readline() for _ in range(20))
            except OSError:
                head = ""
            if not BANNER_RE.search(head):
                banner_missing.append(rel)

    symbol_checks = []
    for r in symbols:
        cls = _cls(r)
        rel, qual = r["Path"], r["Symbol"]
        if not qual:
            symbol_checks.append({"path": rel, "symbol": r.get("Symbol", ""), "class": cls, "ledger": r["_ledger"], "exists": None,
                                  "n_live": None, "n_tests": None, "n_docs": None, "refs": {}, "proposed": r.get("Proposed action", ""),
                                  "pass": True, "note": "no identifier in the Symbol cell; not mechanically checkable"})
            continue
        exists = symbol_exists(rel, qual)
        refs = symbol_references(rel, qual) if exists else {"live": [], "tests": [], "archive_only": [], "docs": []}
        if cls == "DEAD":
            ok = exists and not refs["live"] and not refs["tests"]
        elif cls == "TEST-ONLY":
            ok = exists and not refs["live"]
        else:
            ok = exists or cls in ("DUPLICATE", "REVIEW", "ACTIVE", "DYNAMIC", "GATED", "GATED-ORPHAN", "OWNER-DECISION")
        symbol_checks.append({"path": rel, "symbol": qual, "class": cls, "ledger": r["_ledger"], "exists": exists,
                              "n_live": len(refs["live"]), "n_tests": len(refs["tests"]), "n_docs": len(refs["docs"]),
                              "refs": refs, "proposed": r.get("Proposed action", ""), "pass": ok})

    report = {
        "date": dt.date.today().isoformat(), "ledger_dir": str(ledger_dir.relative_to(REPO)), "scope": args.scope,
        "ledgers": sorted(p.name for p in ledger_dir.glob("*.md")),
        "rows": len(files), "applied_rows": [r["Path"] for r in applied], "by_class": by_class, "coverage": coverage,
        "dead": dead_checks, "dead_failures": [d["path"] for d in dead_checks if not d["pass"]],
        "repoint": repoint, "archive_missing_banner": sorted(banner_missing),
        "symbols": symbol_checks, "symbol_rows": len(symbol_checks),
        "symbol_by_class": {c: sum(1 for s in symbol_checks if s["class"] == c) for c in sorted({s["class"] for s in symbol_checks})},
        "symbol_failures": [f"{s['path']}::{s['symbol']}" for s in symbol_checks if not s["pass"]],
    }
    out = REPO / "data" / "eval_results" / f"{args.out}_{report['date']}.json"
    out.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ("rows", "by_class", "coverage", "dead_failures", "archive_missing_banner",
                                              "symbol_rows", "symbol_by_class", "symbol_failures")}, indent=1))
    print(f"repoint rows: {len(repoint)}; dead rows: {len(dead_checks)}; report: {out.relative_to(REPO)}")
    bad = (report["dead_failures"] or coverage["missing_from_ledgers"] or coverage["ledgered_but_untracked"]
           or dup or report["symbol_failures"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
