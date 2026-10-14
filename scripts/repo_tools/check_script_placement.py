"""Placement and lifecycle checker for code files in this repository.

Lifecycle: library
Doc: docs/infrastructure/SCRIPT_HYGIENE_POLICY.md

One checker, three callers: the git pre-commit hook (``--staged``), the
Claude Code PreToolUse write guard (``--paths`` with ``--content``), and the
pytest suite (``--all``). Placement rules apply to every file; the lifecycle
header is required only for files that are not in the grandfather tree (the
tag named by ``SFU_PLACEMENT_BASELINE_REF``, default
``pre-rust-core-and-script-triage-2026-10-11``), so the 2026-10-11 backlog is
triaged by ledger, not by a failing hook.

Exit status 1 when any violation is found; each line of output is
``<path>: <reason>``.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASELINE_REF_DEFAULT = "pre-rust-core-and-script-triage-2026-10-11"
CODE_EXT = {".py", ".sh", ".mjs", ".js", ".ps1", ".bat", ".rs", ".ipynb"}
HEADER_WINDOW = 20

SCRIPTS_ROOT_ALLOW = {
    "serve_http.sh",
    "stage_seismic_local.sh",
    "build_thinclient_index.py",
    "build_flat_blocks.py",
    "snapshot_downloader.py",
    "run_parity_safe.sh",
    "eval_thinclient_parity.py",
    "prime_result_cache.py",
    "sweep_stray_tantivy_files.py",
    "setup_cloudflare_mcp.sh",
    "build_web.mjs",
    "verify_web_jsdom.mjs",
    "verify_web_progress.mjs",
    "e2e_sweep.mjs",
}
SCRIPTS_FAMILIES = {
    "archive", "data", "demo_broker", "experiments", "gui_testbed",
    "portable_linux", "portable_socsci", "repo_tools", "reproduce",
    "seismic_testbed", "tests",
}
LIFECYCLE_EXEMPT_FAMILIES = {"archive", "data", "tests"}
SRC_ROOT_ALLOW = {"sfu_library_mcp_http.py", "sfu_library_mcp_server.py"}
SRC_FAMILIES = {"lib", "tests"}
SPIKE_ROOT_NONCODE_OK = {".md", ".patch", ".toml", ".txt"}

LIFECYCLES = ("operator", "library", "tool", "harness", "one-off")
LIFECYCLE_RE = re.compile(r"^\s*Lifecycle:\s*(operator|library|tool|harness|one-off)\s*$", re.M)
RESULTS_RE = re.compile(r"^\s*Results:\s*\S", re.M)
DOC_RE = re.compile(r"^\s*Doc:\s*docs/\S+", re.M)
BANNER_RE = re.compile(r"\b(CLOSED|SUPERSEDED|ARCHIVED)\b")


def _git(*args: str) -> str:
    out = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    if out.returncode != 0:
        return ""
    return out.stdout


def grandfather_tree() -> set[str]:
    ref = os.environ.get("SFU_PLACEMENT_BASELINE_REF", BASELINE_REF_DEFAULT)
    listing = _git("ls-tree", "-r", "--name-only", ref)
    if not listing:
        listing = _git("ls-tree", "-r", "--name-only", "HEAD")
    return set(listing.split())


def head_lines(rel: str, content: str | None) -> str:
    if content is not None:
        return "\n".join(content.splitlines()[:HEADER_WINDOW])
    p = REPO / rel
    try:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            return "".join(fh.readline() for _ in range(HEADER_WINDOW))
    except OSError:
        return ""


def check_placement(rel: str) -> list[str]:
    parts = Path(rel).parts
    ext = Path(rel).suffix
    out: list[str] = []
    if len(parts) == 1:
        if ext in CODE_EXT:
            out.append("code file at the repository root; put it in source/, scripts/<family>/ or spike/<track>/")
        return out
    top = parts[0]
    if top == "scripts":
        if len(parts) == 2:
            if ext in CODE_EXT and parts[1] not in SCRIPTS_ROOT_ALLOW:
                out.append("new file at scripts/ root; the root holds only the operator entry points listed in scripts/README.md, so put it in a family directory")
        elif parts[1] not in SCRIPTS_FAMILIES and ext in CODE_EXT:
            out.append(f"unknown scripts family '{parts[1]}'; allowed: {', '.join(sorted(SCRIPTS_FAMILIES))}")
    elif top == "source":
        if len(parts) == 2:
            if ext in CODE_EXT and parts[1] not in SRC_ROOT_ALLOW:
                out.append("new file at source/ root; serving code goes in source/lib/ (or source/lib/thinclient/), tests in source/tests/")
        elif parts[1] not in SRC_FAMILIES and ext in CODE_EXT:
            out.append(f"unknown src subdirectory '{parts[1]}'; allowed: {', '.join(sorted(SRC_FAMILIES))}")
    elif top == "spike":
        if len(parts) == 2 and ext not in SPIKE_ROOT_NONCODE_OK:
            out.append("file at spike/ root; a spike lives in its own spike/<track>/ directory (root keeps README, CLAUDE.md and patches)")
    return out


def check_lifecycle(rel: str, content: str | None) -> list[str]:
    parts = Path(rel).parts
    out: list[str] = []
    head = head_lines(rel, content)
    if parts[0] in ("scripts", "spike") and len(parts) >= 3 and parts[1] == "archive":
        if Path(rel).suffix in CODE_EXT | {".md"} and not BANNER_RE.search(head):
            out.append("added under archive/ without a CLOSED/SUPERSEDED banner in the first 20 lines (closed-tracks policy)")
        return out
    if parts[0] != "scripts" or Path(rel).suffix != ".py":
        return out
    if len(parts) >= 3 and parts[1] in LIFECYCLE_EXEMPT_FAMILIES:
        return out
    m = LIFECYCLE_RE.search(head)
    if not m:
        out.append("new script without a 'Lifecycle: operator|library|tool|harness|one-off' line in its module docstring (first 20 lines)")
        return out
    kind = m.group(1)
    at_root = len(parts) == 2
    if kind == "operator" and not at_root:
        out.append("Lifecycle: operator is reserved for scripts/ root entry points listed in scripts/README.md")
    if kind != "operator" and at_root:
        out.append("scripts/ root files must be Lifecycle: operator")
    if kind == "one-off":
        if not (len(parts) >= 3 and parts[1] == "experiments"):
            out.append("Lifecycle: one-off is allowed only under scripts/experiments/ (evidence); scratch work stays out of the repo")
        if not RESULTS_RE.search(head):
            out.append("one-off script must name its results file ('Results: data/eval_results/...') in the docstring")
        if not DOC_RE.search(head):
            out.append("one-off script must name the doc that records its outcome ('Doc: docs/...')")
    if kind == "harness" and not DOC_RE.search(head):
        out.append("harness must name the doc that cites it ('Doc: docs/...')")
    return out


def check(rel: str, content: str | None, new: bool) -> list[str]:
    problems = check_placement(rel)
    if new:
        problems += check_lifecycle(rel, content)
    return problems


def staged_added() -> list[str]:
    return [p for p in _git("diff", "--cached", "--name-only", "--diff-filter=A").split() if p]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--staged", action="store_true", help="files added in the git index")
    g.add_argument("--paths", nargs="+", help="explicit repo-relative or absolute paths")
    g.add_argument("--all", action="store_true", help="every tracked file")
    ap.add_argument("--content", help="file holding the would-be content of the single --paths entry; '-' reads stdin")
    args = ap.parse_args(argv)

    grandfathered = grandfather_tree()
    content = None
    if args.content:
        content = sys.stdin.read() if args.content == "-" else Path(args.content).read_text(encoding="utf-8", errors="replace")

    if args.staged:
        targets = [(p, True) for p in staged_added()]
    elif args.all:
        targets = [(p, p not in grandfathered) for p in _git("ls-files").split() if p]
    else:
        targets = []
        for p in args.paths:
            rel = os.path.relpath(os.path.abspath(p), REPO) if os.path.isabs(p) else p
            rel = rel.replace(os.sep, "/")
            if rel.startswith(".."):
                continue
            targets.append((rel, rel not in grandfathered))

    failures = 0
    for rel, new in targets:
        for reason in check(rel, content if len(targets) == 1 else None, new):
            print(f"{rel}: {reason}")
            failures += 1
    if failures:
        print(f"{failures} placement/lifecycle violation(s); policy: docs/infrastructure/SCRIPT_HYGIENE_POLICY.md", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
