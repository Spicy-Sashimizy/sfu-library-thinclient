#!/usr/bin/env bash
# Install the repo's local git hooks from the tracked copies in scripts/repo_tools/hooks/
# (pre-commit: large-file guard + gitleaks + script placement policy + substantial-change
# gate; a pre-push hook is installed too when one is present). Idempotent; a differing
# installed hook is backed up as <hook>.bak.<timestamp> first.
# Why a script: on 2026-10-10 core.hooksPath pointed at a directory that no longer
# existed, so git ran NO hooks for months.
# Usage: scripts/repo_tools/install_git_hooks.sh
# One-time overrides at commit/push: ALLOW_BIG=1 SKIP_GITLEAKS=1 SKIP_PLACEMENT=1 SKIP_PREFLIGHT=1
set -euo pipefail
REPO="$(git rev-parse --show-toplevel)"
HOOKS="$REPO/.git/hooks"
SRC="$REPO/scripts/repo_tools/hooks"
if hp="$(git -C "$REPO" config --get core.hooksPath 2>/dev/null)"; then
  if [ ! -d "$hp" ]; then
    echo "core.hooksPath=$hp does not exist; unsetting so $HOOKS is used"
    git -C "$REPO" config --unset core.hooksPath
  else
    echo "core.hooksPath=$hp is set; hooks below go to $HOOKS and will NOT run until it is unset" >&2
  fi
fi
mkdir -p "$HOOKS"
for h in pre-commit pre-push; do
  [ -f "$SRC/$h" ] || continue
  if [ -f "$HOOKS/$h" ] && ! cmp -s "$SRC/$h" "$HOOKS/$h"; then
    cp "$HOOKS/$h" "$HOOKS/$h.bak.$(date +%Y%m%d%H%M%S)"
    echo "install_git_hooks: previous $h backed up next to it"
  fi
  cp "$SRC/$h" "$HOOKS/$h"
  chmod +x "$HOOKS/$h"
done
echo "installed from $SRC into $HOOKS"
