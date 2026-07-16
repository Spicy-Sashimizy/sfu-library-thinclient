#!/usr/bin/env bash
# WI-4 gate orchestration: native + v3 + v2 variants × shards 1+2 (worst-case),
# n=100 (the promotable bar, math/05). Then join each variant vs native for the
# overlap@10 + warm-ratio verdict. The served production .so is NEVER touched —
# variants load by explicit sys.path prepend (portable_so/{v3,v2}/seismic/).
set -u
cd /workspaces/sfu-library-thinclient
export SFU_SEISMIC_PREFLOOR=2
V=3
for SHARD in 1 2; do
  for VAR in native v3 v2; do
    OUT=data/eval_results/wi4_topk_${VAR}_shard${SHARD}.json
    echo "=== WI-4 $VAR shard$SHARD (n=100) $(date -u +%H:%M:%SZ) → $OUT ==="
    .venv/bin/python3 scripts/seismic_testbed/wi4_portable_cpu_gates.py \
      --variant $VAR --shard $SHARD --queries 100 2>&1 | tail -2
  done
done
echo "=== computing verdicts (variant vs native, per shard) ==="
for VAR in v3 v2; do
  for SHARD in 1 2; do
    .venv/bin/python3 scripts/seismic_testbed/wi4_portable_cpu_gates.py \
      --variant $VAR --compute-ratios \
      data/eval_results/wi4_topk_${VAR}_shard${SHARD}.json \
      data/eval_results/wi4_topk_native_shard${SHARD}.json 2>&1 | tail -16
    echo "---"
  done
done
echo "=== WI-4 gate orchestration DONE $(date -u +%H:%M:%SZ) ==="
