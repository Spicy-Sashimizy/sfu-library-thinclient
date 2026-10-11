"""Substantial-change gate: restore tag + tests + function inventory before a commit.

Lifecycle: library
Doc: docs/infrastructure/SCRIPT_HYGIENE_POLICY.md

A staged change is SUBSTANTIAL when any of these holds (thresholds are env
overridable): ``SFU_PREFLIGHT_MIN_FILES`` files touched (default 10),
``SFU_PREFLIGHT_MIN_LINES`` lines added+deleted (default 500), or any delete
or rename of a code file under src/, scripts/, spike/ or web/. A substantial
commit is allowed only when ``.claude/.preflight_stamp.json`` records a
passing ``run`` over exactly the staged tree (``git write-tree``), and the
restore tag that run created or reused is still an ancestor of HEAD.

  preflight.py assess                 say whether the staged change is substantial, and why
  preflight.py tag [--slug S]         ensure a fresh restore tag (pre-<slug>-<date>) at HEAD, pushed when a remote exists
  preflight.py run [--slug S] [--accept-removals FILE]
                                      tag + tests + symbol inventory vs the tag, then write the stamp; FILE is a
                                      triage record JSON whose ``removed_symbols`` are the sanctioned protected
                                      removals (SCRIPT_HYGIENE_POLICY.md §3; also ``SFU_PREFLIGHT_ACCEPT``)
  preflight.py check [--destructive]  exit 1 when a substantial commit (or a destructive command) lacks a valid tag/stamp
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STAMP = REPO / ".claude" / ".preflight_stamp.json"
TOOLS = REPO / "scripts" / "repo_tools"
CODE_EXT = (".py", ".sh", ".mjs", ".js", ".ps1", ".bat", ".rs", ".html", ".css", ".jsx")
PROTECTED_PREFIX = ("src/", "scripts/", "spike/", "web/")
DEFAULT_TESTS = [
    "scripts/tests/test_script_placement.py",
    "scripts/tests/test_doc_status.py",
    "src/tests",
]
TAG_MAX_AGE_H = 24


def _git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=check)


def assess() -> dict:
    status = _git("diff", "--cached", "--name-status", "-M").stdout.strip().splitlines()
    numstat = _git("diff", "--cached", "--numstat", "-M").stdout.strip().splitlines()
    files = len(status)
    lines = 0
    for row in numstat:
        a, d = row.split("\t")[:2]
        lines += (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
    risky = []
    for row in status:
        code, *paths = row.split("\t")
        if code[0] in "DR" and any(p.startswith(PROTECTED_PREFIX) and p.endswith(CODE_EXT) for p in paths):
            risky.append(row)
    min_files = int(os.environ.get("SFU_PREFLIGHT_MIN_FILES", 10))
    min_lines = int(os.environ.get("SFU_PREFLIGHT_MIN_LINES", 500))
    reasons = []
    if files >= min_files:
        reasons.append(f"{files} files staged (>= {min_files})")
    if lines >= min_lines:
        reasons.append(f"{lines} lines changed (>= {min_lines})")
    if risky:
        reasons.append(f"{len(risky)} delete/rename of code under {'/'.join(p.rstrip('/') for p in PROTECTED_PREFIX)}")
    return {"files": files, "lines": lines, "risky": risky, "substantial": bool(reasons), "reasons": reasons}


def _tags_at_ancestors() -> list[tuple[str, str, dt.datetime]]:
    out = []
    for line in _git("for-each-ref", "--format=%(refname:short)\t%(objectname)\t%(creatordate:iso-strict)", "refs/tags/pre-*").stdout.splitlines():
        name, obj, when = line.split("\t")
        commit = _git("rev-parse", f"{name}^{{commit}}").stdout.strip()
        if _git("merge-base", "--is-ancestor", commit, "HEAD").returncode == 0:
            try:
                ts = dt.datetime.fromisoformat(when)
            except ValueError:
                ts = dt.datetime.fromtimestamp(0, dt.timezone.utc)
            out.append((name, commit, ts))
    return out


def fresh_tag() -> str | None:
    now = dt.datetime.now(dt.timezone.utc)
    head = _git("rev-parse", "HEAD").stdout.strip()
    best = None
    for name, commit, ts in _tags_at_ancestors():
        if commit == head or (now - ts) <= dt.timedelta(hours=TAG_MAX_AGE_H):
            if best is None or ts > best[1]:
                best = (name, ts)
    return best[0] if best else None


def ensure_tag(slug: str | None) -> str:
    existing = fresh_tag()
    if existing:
        return existing
    slug = re.sub(r"[^a-z0-9]+", "-", (slug or "change").lower()).strip("-") or "change"
    stamp = dt.datetime.now(dt.timezone.utc)
    name = f"pre-{slug}-{stamp:%Y-%m-%d}"
    if _git("rev-parse", "--verify", "--quiet", f"refs/tags/{name}").returncode == 0:
        name = f"pre-{slug}-{stamp:%Y-%m-%d-%H%M}"
    _git("tag", "-a", name, "-m", f"Restore point before a substantial change ({slug}); created by scripts/repo_tools/preflight.py", check=True)
    if _git("remote").stdout.strip():
        push = _git("push", "origin", name)
        if push.returncode != 0:
            print(f"preflight: tag {name} created locally; push failed: {push.stderr.strip()}", file=sys.stderr)
    print(f"preflight: restore tag {name}")
    return name


def run(slug: str | None, accept: str | None = None) -> int:
    tag = ensure_tag(slug)
    accept = accept or os.environ.get("SFU_PREFLIGHT_ACCEPT") or None
    tests = os.environ.get("SFU_PREFLIGHT_TESTS", " ".join(DEFAULT_TESTS)).split()
    py = sys.executable
    t = subprocess.run([py, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests], cwd=REPO, capture_output=True, text=True)
    test_tail = "\n".join(t.stdout.strip().splitlines()[-3:])
    print(test_tail)
    inv_cmd = [py, "-I", str(TOOLS / "symbol_inventory.py"), "diff", "--base", tag]
    if accept:
        inv_cmd += ["--accept", accept]
    inv = subprocess.run(inv_cmd, cwd=REPO, capture_output=True, text=True)
    try:
        inv_report = json.loads(inv.stdout)
    except json.JSONDecodeError:
        inv_report = {"error": inv.stdout[-500:]}
    ok = t.returncode == 0 and inv.returncode == 0
    stamp = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "head": _git("rev-parse", "HEAD").stdout.strip(),
        "tree": _git("write-tree").stdout.strip(),
        "tag": tag,
        "tests": tests,
        "tests_rc": t.returncode,
        "tests_tail": test_tail,
        "symbols_rc": inv.returncode,
        "removed_protected": inv_report.get("removed_protected", {}),
        "accepted_removals": inv_report.get("accepted_removals", {}),
        "accept_file": accept,
        "removed_evidence": inv_report.get("removed_evidence", {}),
        "assess": assess(),
        "ok": ok,
    }
    STAMP.parent.mkdir(exist_ok=True)
    STAMP.write_text(json.dumps(stamp, indent=1))
    if inv_report.get("removed_evidence"):
        print(f"preflight: {len(inv_report['removed_evidence'])} evidence-family symbol removal(s) (allowed; record them in the ledger)")
    if inv_report.get("accepted_removals"):
        print(f"preflight: {len(inv_report['accepted_removals'])} protected removal(s) accepted from {accept}")
    if not ok:
        print(f"preflight: FAILED (tests rc={t.returncode}, symbols rc={inv.returncode}); stamp written with ok=false", file=sys.stderr)
        if inv_report.get("removed_protected"):
            print("protected symbols removed: " + ", ".join(list(inv_report["removed_protected"])[:20]), file=sys.stderr)
        return 1
    print(f"preflight: OK; stamp covers staged tree {stamp['tree'][:12]} (tag {tag})")
    return 0


def check(destructive: bool) -> int:
    if destructive:
        tag = fresh_tag()
        if tag:
            return 0
        print("preflight: destructive command without a fresh restore tag; run `scripts/repo_tools/preflight.py tag --slug <what>` first", file=sys.stderr)
        return 1
    a = assess()
    if not a["substantial"]:
        return 0
    why = "; ".join(a["reasons"])
    if not STAMP.exists():
        print(f"preflight: substantial change ({why}) but no preflight stamp; run `.venv/bin/python3 scripts/repo_tools/preflight.py run --slug <what>` after staging, then commit", file=sys.stderr)
        return 1
    s = json.loads(STAMP.read_text())
    tree = _git("write-tree").stdout.strip()
    problems = []
    if not s.get("ok"):
        problems.append("last preflight run FAILED")
    if s.get("tree") != tree:
        problems.append("staged tree changed since the last preflight run")
    if s.get("tag") and _git("merge-base", "--is-ancestor", f"{s['tag']}^{{commit}}", "HEAD").returncode != 0:
        problems.append(f"restore tag {s['tag']} is not an ancestor of HEAD")
    if problems:
        print(f"preflight: substantial change ({why}); " + "; ".join(problems) + ". Re-run `.venv/bin/python3 scripts/repo_tools/preflight.py run --slug <what>` with the final staged set, then commit.", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("assess")
    for name in ("tag", "run"):
        p = sub.add_parser(name)
        p.add_argument("--slug")
        if name == "run":
            p.add_argument("--accept-removals")
    c = sub.add_parser("check")
    c.add_argument("--destructive", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "assess":
        a = assess()
        print(json.dumps(a, indent=1))
        return 0
    if args.cmd == "tag":
        ensure_tag(args.slug)
        return 0
    if args.cmd == "run":
        return run(args.slug, args.accept_removals)
    return check(args.destructive)


if __name__ == "__main__":
    sys.exit(main())
