#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO_ROOT/.venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"

cd "$REPO_ROOT/src"
exec "$PY" sfu_library_mcp_http.py
