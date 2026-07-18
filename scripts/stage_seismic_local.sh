#!/usr/bin/env bash
# Stage the 150M SEISMIC shard set onto a fast LOCAL filesystem.
#
# Why: SEISMIC serves by mmap'ing the forward index. On a 9p / virtiofs / NFS
# mount each random page fault costs ~0.5 ms (measured 9p 2026-07-18:
# ~1830 faults/s), so a query faulting ~15k pages takes ~8 s AND page cache
# does not hold — every distinct query re-faults cold. On a native local FS the
# same faults run ~160-240x faster (~300k/s) and stay resident (the WI-1 warm
# p50 ~47 ms path).
#
# WHEN YOU NEED THIS:
#   - WSL2 dev container: the repo lives on a 9p bind mount (C:\ passthrough) →
#     stage to the container's native overlay (e.g. /var/tmp/seismic_stage).
#   - Any host where the index arrives on a network/passthrough mount.
# WHEN YOU DON'T:
#   - A DO droplet (or any box) whose index already sits on local block storage.
#     Serving reads it at native speed directly; skip staging.
#
# Usage:
#   scripts/stage_seismic_local.sh [STAGE_DIR]        # default /var/tmp/seismic_stage
# Then serve with:
#   export SFU_SEISMIC_STAGE_DIR=<STAGE_DIR>          # serve auto-restages (idempotent)
# or point SFU_SEISMIC_SHARD_MANIFEST at <STAGE_DIR>/staged_manifest.json.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE_DIR="${1:-/var/tmp/seismic_stage}"
SRC="$REPO_ROOT/data/seismic_150m/index/plan01"

mkdir -p "$STAGE_DIR"
shopt -s nullglob
shards=("$SRC"/*.dotvbyte.e5.v2.mmap)
[ ${#shards[@]} -gt 0 ] || { echo "No e5.v2 shard dirs under $SRC" >&2; exit 1; }

echo "Staging ${#shards[@]} shard dirs -> $STAGE_DIR"
for d in "${shards[@]}"; do
  name="$(basename "$d")"
  dst="$STAGE_DIR/$name"
  if [ -d "$dst" ] && [ "$(du -sb "$dst" | cut -f1)" = "$(du -sb "$d" | cut -f1)" ]; then
    echo "  = $name already staged, skipping"
  else
    echo "  + copying $name ..."
    cp -r "$d" "$STAGE_DIR/"
  fi
done
echo "Done. Serve with: export SFU_SEISMIC_STAGE_DIR=$STAGE_DIR"
