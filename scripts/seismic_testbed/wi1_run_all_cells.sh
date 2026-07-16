#!/usr/bin/env bash
# WI-1 orchestration: 4 cells, alternating arms (E5 protocol).
# rep1 parallel -> rep1 sequential (parity vs rep1-parallel) ->
# rep2 parallel -> rep2 sequential (parity vs rep2-parallel).
# Cold eviction is per-process; each cell is a fresh process so pass-0 is
# naturally Linux-cold on 9p (doc 13 §5). Out-of-process per arm = uncontaminated.
set -u
cd /workspaces/sfu-library-thinclient
PY=.venv/bin/python3
DATE=$(date -u +%Y%m%d_%H%M%S)
OUT=data/eval_results
SLUG="wi1_seq_vs_par_${DATE}"
mkdir -p "$OUT"

echo "=== WI-1 A/B orchestrator start $SLUG (UTC $(date -u +%H:%M:%SZ)) ==="

for REP in 1 2; do
  PAR_JSON="$OUT/${SLUG}_parallel_rep${REP}.json"
  echo "--- rep $REP PARALLEL (fresh process) $(date -u +%H:%M:%SZ) ---"
  $PY scripts/seismic_testbed/wi1_seq_vs_par_federation.py \
    --federation parallel --rep "$REP" \
    --splade-model models/splade_onnx_fused \
    --result-file "$PAR_JSON"

  SEQ_JSON="$OUT/${SLUG}_sequential_rep${REP}.json"
  echo "--- rep $REP SEQUENTIAL (parity vs rep${REP} parallel) $(date -u +%H:%M:%SZ) ---"
  $PY scripts/seismic_testbed/wi1_seq_vs_par_federation.py \
    --federation sequential --rep "$REP" \
    --splade-model models/splade_onnx_fused \
    --parity-ref "$PAR_JSON" \
    --result-file "$SEQ_JSON"
done

echo "=== WI-1 A/B orchestrator DONE $(date -u +%H:%M:%SZ) ==="
echo "results: ${SLUG}_* under $OUT"
