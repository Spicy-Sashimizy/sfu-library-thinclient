"""Tier 2: a headless Claude Code invocation for the whole-document /
structural review.

Invoked only on escalation or on a timer. This is where tools and a stronger
model earn their cost: the process can call the PaperQA2 index, Vale, the
metrics store and the thin client's search endpoint through MCP, and writes
one consolidated comment.

Flags verified against ``claude --help`` (Claude Code 2.1.312, 2026-10-29):
``-p/--print``, ``--output-format json``, ``--model``, ``--max-turns``,
``--allowedTools``, ``--mcp-config``, ``--append-system-prompt``,
``--json-schema``. Bill through an API key (ANTHROPIC_API_KEY in the
environment of the subprocess); do not run an automated backend on a consumer
subscription login.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .models import ParagraphReport

REVIEW_PROMPT = """You are the escalation reviewer for a drift-auditing tool. A cheaper first pass flagged the paragraphs below as drifting from the writer's base of truth (their reference corpus and their measured numbers). You have tools; use them to verify, do not guess.

Tasks:
1. Re-check each flagged claim against the evidence. Say which first-pass verdicts you confirm and which you overturn.
2. Look for structural drift the per-paragraph pass cannot see: the document's framing moving away from what the evidence supports, terminology shifting, numbers that are individually right but combined into a wrong conclusion.
3. Write ONE consolidated comment for the writer: what drifted, what the base of truth says instead (cite ids), and the smallest edit that reguides the text. Plain prose, under 250 words.

Flagged paragraphs and first-pass reports (JSON):
"""


def claude_available() -> bool:
    return shutil.which("claude") is not None


def run_escalation(reports: list[ParagraphReport], model: str = "claude-fable-5-1",
                   max_turns: int = 12, mcp_config: str | Path | None = None,
                   allowed_tools: list[str] | None = None, timeout: int = 900,
                   extra_context: str = "") -> str:
    if not claude_available():
        return "[tier2 skipped: `claude` CLI not on PATH]"
    payload = json.dumps([r.summary() for r in reports], ensure_ascii=False, indent=1)
    prompt = REVIEW_PROMPT + payload
    if extra_context:
        prompt += "\n\nAdditional context:\n" + extra_context
    cmd = ["claude", "-p", "--output-format", "json", "--model", model, "--max-turns", str(max_turns)]
    if mcp_config:
        cmd += ["--mcp-config", str(mcp_config)]
    if allowed_tools:
        cmd += ["--allowedTools", *allowed_tools]
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "[tier2 timed out]"
    if proc.returncode != 0:
        return f"[tier2 failed rc={proc.returncode}] {proc.stderr[-800:]}"
    try:
        data = json.loads(proc.stdout)
        return str(data.get("result") or data)
    except json.JSONDecodeError:
        return proc.stdout.strip()
