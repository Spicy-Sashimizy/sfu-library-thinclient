#!/usr/bin/env bash
# PreToolUse(Bash) hook: the substantial-change gate (docs/infrastructure/SCRIPT_HYGIENE_POLICY.md).
#  - `git commit`: deny when the staged change is substantial (>=10 files, >=500 lines,
#    or any delete/rename of code) and no passing preflight run covers the staged tree.
#  - destructive commands (reset --hard, checkout -- ., clean -f, push --force, branch -D,
#    rm -rf outside /tmp, git rm -r): deny unless a restore tag <24 h old is an ancestor of HEAD.
# The denial text tells the agent exactly which preflight command to run, so the
# tag + tests happen without the owner asking.
set -u
input=$(cat 2>/dev/null || true)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -n "$cmd" ] || exit 0
root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
py="$root/.venv/bin/python3"; [ -x "$py" ] || py=python3
pf="$root/scripts/repo_tools/preflight.py"
[ -f "$pf" ] || exit 0

deny() {
  jq -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

if printf '%s' "$cmd" | grep -qE '(^|[;&|[:space:]])git[[:space:]]+(-C[[:space:]]+\S+[[:space:]]+)?commit([[:space:]]|$)'; then
  if ! out=$("$py" -I "$pf" check 2>&1); then
    deny "Substantial-change gate: $out
Run (after staging the FINAL file set):  .venv/bin/python3 scripts/repo_tools/preflight.py run --slug <short-name>
It creates/reuses a restore tag, runs the fast tests + the function inventory against the tag, and stamps the staged tree; then re-issue the commit. Never bypass with SKIP_PREFLIGHT unless the owner says so."
  fi
fi

if printf '%s' "$cmd" | grep -qE 'git[[:space:]]+(reset[[:space:]]+--hard|checkout[[:space:]]+--[[:space:]]+\.|clean[[:space:]]+-[a-zA-Z]*f|push[[:space:]]+.*(--force|-f([[:space:]]|$))|branch[[:space:]]+-D|rm[[:space:]]+-r)|(^|[;&|[:space:]])rm[[:space:]]+-[a-zA-Z]*r[a-zA-Z]*[[:space:]]+'; then
  case "$cmd" in *"/tmp/"*|*scratchpad*) ;; *)
    if ! out=$("$py" -I "$pf" check --destructive 2>&1); then
      deny "Destructive command without a fresh restore tag: $out
Run:  .venv/bin/python3 scripts/repo_tools/preflight.py tag --slug <short-name>   (creates and pushes pre-<slug>-<date> at HEAD), then re-issue the command."
    fi
  esac
fi
exit 0
