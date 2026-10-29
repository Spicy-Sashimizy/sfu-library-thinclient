#!/usr/bin/env bash
# One-time setup in a fresh container. Run from the spike root.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e ".[dev,google]"
# Optional, heavy (PaperQA2 + Zotero + local embeddings):
#   pip install -e ".[paperqa]"
# Optional: Vale prose linter — https://vale.sh/docs/install
cp -n config.example.toml config.toml || true
cp -n .env.example .env || true
mkdir -p secrets corpus_pdfs reports
echo "edit config.toml and .env, then: scripts/run_offline_demo.sh"
