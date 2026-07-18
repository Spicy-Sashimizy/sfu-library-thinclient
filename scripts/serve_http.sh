#!/usr/bin/env bash
# Canonical launcher for the SFU Library HTTP serve (GUI at /app + REST API +
# MCP at /mcp). Portable: repo-relative, no machine-specific paths, safe to
# call from systemd / a DO droplet's process manager / a dev shell.
#
#   ExecStart=/path/to/repo/scripts/serve_http.sh
#
# Env (all optional): MCP_HTTP_HOST (default 0.0.0.0), MCP_HTTP_PORT (default
# 8080), SFU_HTTP_WARMUP=0 to skip the startup warmup, SFU_RESULT_CACHE=0 to
# disable the read-through result cache (deployprep WI-17; default ON in
# staging — owner-granted exception for that wave only; one-env rollback),
# SFU_CACHE_PRESEED=0 to skip the post-warmup cache pre-seed primer, plus
# SFU_SEARCH_SPECULATE=1 to enable searchbar keystroke speculation (deployprep
# WI-18; default OFF — owner reviews the measured efficacy + flips the default,
# not this script; speculates through the SAME result cache, no second cache),
# plus every SFU_* knob documented in docs/THIN_CLIENT_SWAP.md. Requires the repo
# venv at .venv (falls back to python3 on PATH so a droplet with a
# system-wide install of src/requirements.txt also works).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO_ROOT/.venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"

cd "$REPO_ROOT/src"
exec "$PY" sfu_library_mcp_http.py
