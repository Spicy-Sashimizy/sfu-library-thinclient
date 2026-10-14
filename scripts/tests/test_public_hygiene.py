"""Public-tree hygiene pins.

These fail the suite when a common leak class appears:
- an evidence JSON under data/eval_results/ carries an environment dump with
  a secret-bearing or identifying key;
- .gitleaks.toml stops extending the default rules or grows a blanket
  allowlist over data/, README or CLAUDE files;
- a tracked text file carries a Windows/Linux home path with a real username.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "data" / "eval_results"
SENSITIVE_KEY = re.compile(r"(API_KEY|_TOKEN|SECRET|PASSWORD|_AUTH$|USER_ID|TUNNEL|HOSTNAME)", re.I)
HOME_PATH = re.compile(r"(?:Users[/\\]+|/home/)([A-Za-z][A-Za-z0-9_.-]{2,})(?=[/\\])")
HOME_ALLOW = {"<user>", "vscode", "root", "ubuntu", "opc"}
SKIP = re.compile(r"(^|/)(vendor|node_modules|archive)/|\.(png|jpg|gif|ico|woff2?|ttf|npz|npy|gz|zst|bin|so|pyd|pdf)$")


def tracked(prefix: str = ".") -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "--", prefix], capture_output=True, text=True)
    return [p for p in out.stdout.split("\n") if p]


def _walk_env_blocks(obj, path, found):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "env" and isinstance(v, dict):
                for ek, ev in v.items():
                    if SENSITIVE_KEY.search(ek) and ev not in ("", None, "0", "1", 0, 1, False, True):
                        found.append(f"{path}.env.{ek}")
            _walk_env_blocks(v, f"{path}.{k}", found)
    elif isinstance(obj, list):
        for i, x in enumerate(obj):
            _walk_env_blocks(x, f"{path}[{i}]", found)


def test_eval_results_env_dumps_carry_no_sensitive_keys():
    offenders = []
    for rel in tracked("data/eval_results"):
        if not rel.endswith(".json"):
            continue
        p = REPO / rel
        if p.stat().st_size > 50_000_000:
            continue
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        found: list[str] = []
        _walk_env_blocks(obj, rel, found)
        offenders.extend(found)
    assert not offenders, "env dumps with secret-bearing/identifying keys:\n" + "\n".join(offenders[:20])


def test_gitleaks_config_extends_defaults_and_has_no_blanket_allowlist():
    s = (REPO / ".gitleaks.toml").read_text()
    assert re.search(r"^\[extend\]\s*\nuseDefault\s*=\s*true", s, re.M), ".gitleaks.toml must extend the default rules"
    tail = s.split("\n[allowlist]", 1)[1]
    for bad in (r"data/.*\.json", r"data/.*\.jsonl", r"README\.md", r"CLAUDE\.md", r"server\.py", r"\.env\.example", r"\.env\.template"):
        assert bad not in tail, f"global allowlist must not carry {bad!r}"


def test_tracked_text_has_no_real_home_paths():
    hits = {}
    for rel in tracked():
        if SKIP.search(rel) or rel == "scripts/tests/test_public_hygiene.py":
            continue
        p = REPO / rel
        if not p.is_file():
            continue
        try:
            head = p.open("rb").read(8192)
        except OSError:
            continue
        if b"\0" in head:
            continue
        text = p.read_bytes().decode("utf-8", errors="ignore")
        for m in HOME_PATH.findall(text):
            if m not in HOME_ALLOW:
                hits.setdefault(m, []).append(rel)
    assert not hits, f"home paths with usernames: { {k: v[:3] for k, v in hits.items()} }"
