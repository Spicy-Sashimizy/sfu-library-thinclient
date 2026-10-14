"""Function/class inventory of the Python tree, and the diff of two revisions.

Lifecycle: library
Doc: docs/infrastructure/SCRIPT_HYGIENE_POLICY.md

Each symbol is keyed ``<file basename>::<qualified name>`` so a file moved
with ``git mv`` keeps every symbol; only a symbol that exists in the base
revision and in no file of the target revision counts as REMOVED. Protected
scopes (``source/`` — ``src/`` before 2026-10-13 — ``web/``, ``scripts/`` outside the evidence families
``experiments/``, ``seismic_testbed/``, ``archive/``) fail the check on any
removal; removals elsewhere are reported for the triage ledger and do not
fail unless ``--strict`` is given. ``--accept FILE`` names a triage record
(JSON with a ``removed_symbols`` list of these keys): protected removals
listed there are accepted and reported under ``accepted_removals`` instead
of failing, which is the only sanctioned way to delete a function under a
protected scope (SCRIPT_HYGIENE_POLICY.md §3).

Usage:
  symbol_inventory.py dump [--ref REF]            JSON inventory of a revision (default: working tree)
  symbol_inventory.py diff --base REF [--head REF] [--strict] [--accept FILE]   removed/added symbols, exit 1 on unaccepted protected removals
"""

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCOPES = ("source/", "src/", "scripts/", "spike/", "web/")
EVIDENCE_FAMILIES = ("scripts/experiments/", "scripts/seismic_testbed/", "scripts/archive/", "spike/")


def _git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, check=False).stdout


def _py_files(ref: str | None) -> list[str]:
    listing = _git("ls-tree", "-r", "--name-only", ref) if ref else _git("ls-files")
    return [p for p in listing.decode().split("\n") if p.endswith(".py") and p.startswith(SCOPES)]


def _source(ref: str | None, rel: str) -> bytes:
    if ref:
        return _git("show", f"{ref}:{rel}")
    try:
        return (REPO / rel).read_bytes()
    except OSError:
        return b""


def _symbols(src: bytes) -> list[str]:
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return []
    out: list[str] = []

    def walk(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                out.append(name)
                if isinstance(child, ast.ClassDef):
                    walk(child, name + ".")

    walk(tree)
    return out


def inventory(ref: str | None) -> dict[str, list[str]]:
    inv: dict[str, list[str]] = {}
    for rel in _py_files(ref):
        base = Path(rel).name
        for sym in _symbols(_source(ref, rel)):
            inv.setdefault(f"{base}::{sym}", []).append(rel)
    return inv


def protected(rel: str) -> bool:
    return rel.startswith(("source/", "src/", "web/", "scripts/")) and not rel.startswith(EVIDENCE_FAMILIES)


def load_accepted(path: str | None) -> set[str]:
    if not path:
        return set()
    data = json.loads(Path(path).read_text())
    keys = data.get("removed_symbols", data) if isinstance(data, dict) else data
    return set(keys)


def is_accepted(key: str, accepted: set[str]) -> bool:
    """True when ``key`` is accepted by name."""
    return key in accepted


def diff(base: str, head: str | None, strict: bool, accept: str | None = None) -> int:
    b, h = inventory(base), inventory(head)
    removed = {k: v for k, v in b.items() if k not in h}
    added = sorted(k for k in h if k not in b)
    accepted = load_accepted(accept)
    prot_all = {k: v for k, v in removed.items() if any(protected(p) for p in v)}
    prot = {k: v for k, v in prot_all.items() if not is_accepted(k, accepted)}
    acc = {k: v for k, v in prot_all.items() if is_accepted(k, accepted)}
    evid = {k: v for k, v in removed.items() if k not in prot_all}
    report = {
        "base": base, "head": head or "WORKTREE",
        "symbols_base": len(b), "symbols_head": len(h),
        "added": len(added),
        "removed_protected": {k: v for k, v in sorted(prot.items())},
        "accepted_removals": {k: v for k, v in sorted(acc.items())},
        "accept_file": accept,
        "removed_evidence": {k: v for k, v in sorted(evid.items())},
    }
    print(json.dumps(report, indent=1))
    if prot or (strict and evid):
        print(f"symbol_inventory: {len(prot)} protected removal(s), {len(evid)} evidence-family removal(s)", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--ref")
    f = sub.add_parser("diff")
    f.add_argument("--base", required=True)
    f.add_argument("--head")
    f.add_argument("--strict", action="store_true")
    f.add_argument("--accept", help="triage record JSON whose removed_symbols are accepted protected removals")
    args = ap.parse_args(argv)
    if args.cmd == "dump":
        print(json.dumps(inventory(args.ref), indent=1, sort_keys=True))
        return 0
    return diff(args.base, args.head, args.strict, args.accept)


if __name__ == "__main__":
    sys.exit(main())
