"""Enforces the script placement + lifecycle policy (docs/infrastructure/SCRIPT_HYGIENE_POLICY.md, 2026-10-11).

Three callers share one checker (scripts/repo_tools/check_script_placement.py):
the git pre-commit hook, the Claude Code write guard, and this test. The test
is the backstop for a commit made with the hook skipped or from a clone that
never ran install_git_hooks.sh: (a) the whole tracked tree satisfies the placement
rules and every post-baseline script carries its lifecycle header; (b) the
checker still rejects the shapes the policy forbids, so a silent regression in
the checker cannot pass as a clean tree.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "scripts" / "repo_tools" / "check_script_placement.py"
ONE_OFF_OK = '"""Eval X.\n\nLifecycle: one-off\nResults: data/eval_results/x.json\nDoc: docs/X.md\n"""\n'


def _run(*args: str, content: str | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-I", str(CHECKER), *args]
    if content is not None:
        cmd += ["--content", "-"]
    return subprocess.run(cmd, input=content, capture_output=True, text=True, cwd=REPO)


def test_tracked_tree_satisfies_policy():
    r = _run("--all")
    assert r.returncode == 0, r.stdout + r.stderr


def test_rejects_new_file_at_scripts_root():
    assert _run("--paths", "scripts/new_tool.py").returncode == 1


def test_rejects_script_without_lifecycle_header():
    assert _run("--paths", "scripts/experiments/eval_new.py", content="import os\n").returncode == 1


def test_accepts_one_off_in_experiments_with_results_and_doc():
    assert _run("--paths", "scripts/experiments/eval_new.py", content=ONE_OFF_OK).returncode == 0


def test_rejects_one_off_outside_experiments():
    assert _run("--paths", "scripts/seismic_testbed/eval_new.py", content=ONE_OFF_OK).returncode == 1


def test_rejects_code_at_src_and_repo_root():
    assert _run("--paths", "src/helper.py").returncode == 1
    assert _run("--paths", "quick_fix.py").returncode == 1


def test_grandfathered_file_passes_without_header():
    assert _run("--paths", "scripts/experiments/eval_pipeline.py").returncode == 0
