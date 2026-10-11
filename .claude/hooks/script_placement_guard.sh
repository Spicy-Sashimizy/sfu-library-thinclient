#!/usr/bin/env bash
# PreToolUse(Write|Edit) hook: placement + lifecycle policy for NEW files.
# Existing files are grandfathered (edits pass); a Write/Edit that would create
# a file is checked by scripts/repo_tools/check_script_placement.py with the
# would-be content, and denied with the policy reason when it fails.
# Policy: docs/infrastructure/SCRIPT_HYGIENE_POLICY.md
set -u
input=$(cat 2>/dev/null || true)
fp=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[ -n "$fp" ] || exit 0
[ -e "$fp" ] && exit 0
root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
case "$fp" in "$root"/*) ;; *) exit 0 ;; esac
py="$root/.venv/bin/python3"; [ -x "$py" ] || py=python3
content=$(printf '%s' "$input" | jq -r '.tool_input.content // .tool_input.new_string // empty' 2>/dev/null)
result=$(printf '%s' "$content" | "$py" -I "$root/scripts/repo_tools/check_script_placement.py" --paths "$fp" --content - 2>/dev/null)
rc=$?
if [ "$rc" -ne 0 ]; then
  jq -n --arg r "$result" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: ("Blocked by the script placement/lifecycle policy (docs/infrastructure/SCRIPT_HYGIENE_POLICY.md):\n" + $r + "\nScratch work belongs in the session scratchpad, not the repo. A tracked script needs a family directory and a docstring with Lifecycle:/Doc: (and Results: for one-off).")
    }
  }'
fi
exit 0
