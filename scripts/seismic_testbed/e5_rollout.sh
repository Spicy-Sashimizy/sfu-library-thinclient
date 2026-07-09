#!/usr/bin/env bash
# E5 rollout — derive block_walk_canonical perm + convert every dv shard to
# its .dotvbyte.e5.mmap twin, serially (bounded RAM). shard1 already done +
# gated. Rule Zero: sources read-only; e5 dirs are NEW.
# Doc: docs/seismic_150m_testbed/13_E5_FORWARD_REORDER_DESIGN.md §4.
set -euo pipefail
cd /workspaces/sfu-library-thinclient
P=data/seismic_150m/index/plan01
BIN=spike/seismic_upstream/target/release/reorder_mmap_shard
PY=.venv/bin/python3

# shard1 already converted + gated (E5_ALL_GATES_PASS 2026-07-09); skip it.
for n in 0 2 3 4 5 6 7; do
  S="global_shard${n}of8"
  src="$P/${S}.dotvbyte.mmap"
  dst="$P/${S}.dotvbyte.e5.mmap"
  perm="$P/e5_perms/${S}.block_walk_canonical.perm.bin"
  echo "=== [$(date +%H:%M:%S)] shard $n: derive perm ==="
  $PY scripts/seismic_testbed/e5_derive_order.py --shard "$S" --order block_walk_canonical
  echo "=== [$(date +%H:%M:%S)] shard $n: convert ==="
  if [ -d "$dst" ]; then echo "  $dst exists — skipping convert"; else
    $BIN --src-mmap-dir "$src" --dst-mmap-dir "$dst" --perm-file "$perm" \
         --order-name block_walk_canonical --sanity-docs 2000
  fi
done
echo "=== [$(date +%H:%M:%S)] all shards converted ==="
