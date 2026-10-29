#!/usr/bin/env bash
# Runs the whole pipeline with no API keys (fake tier 1, local text retriever).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
echo "== metrics store"; $PY -m truth_drift_auditor.cli metrics stats
echo; echo "== aliases resolved"; $PY -m truth_drift_auditor.cli metrics aliases
echo; echo "== coverage probe (pilot step 1)"; $PY -m truth_drift_auditor.cli probe-coverage --draft fixtures/drafts/sample_draft.md
echo; echo "== batch audit, offline (pilot step 3 dry run)"; $PY -m truth_drift_auditor.cli batch --draft fixtures/drafts/sample_draft.md --offline
echo; echo "== judged-set score, offline (pilot step 2 harness)"; $PY -m truth_drift_auditor.cli eval --judged eval/judged_set.example.jsonl --offline
