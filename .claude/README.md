# .claude/ — the development harness (how the work was run, not how to use the software)

This directory configures the AI-assisted workflow the project was built with
(Claude Code). It is kept in git because the docs and commit history refer to
it, and because the house rules it carries are the project's contribution
guide. Nothing here is imported by the software.

| Path | What |
|---|---|
| `CLAUDE.md` | the house rules every contributor (human or agent) follows: git workflow, doc-freshness and measured-claims discipline, venv, closed-tracks policy, no inline comments |
| `settings.json` | tool permissions (the big index files are read-denied) and hooks |
| `hooks/` | four hooks wired in `settings.json`: `doc_sync_check.sh` (Stop: blocks a session end that changed code but no docs), `big_file_read_guard.sh` (PreToolUse Read), `script_placement_guard.sh` (PreToolUse Write/Edit: new scripts need a family directory + `Lifecycle:` line), `substantial_change_gate.sh` (PreToolUse Bash: preflight gate before substantial commits). `settings.json` also wires an inline `SessionStart` command that records HEAD into `.session_start_head` for `doc_sync_check.sh` |
| `plans/` | the plan for in-flight work (none at 2026-10-13); `plans/done/` is the ledger of executed plans (19 plans + its `README.md`) with the doc that records each outcome |
| `prompts/` | reusable task prompts — local only (gitignored), not present in a clone |
| `settings.local.json` | per-machine permission overrides — local only (gitignored), not present in a clone |
| `.session_start_head`, `.preflight_stamp.json` | runtime state written by the `SessionStart` hook and `scripts/repo_tools/preflight.py` — local only (gitignored) |

Directory-scoped `CLAUDE.md` files (`source/lib/thinclient/`, `data/`, `scripts/`,
`web/`, `spike/`) carry local rules and load automatically when working there.
