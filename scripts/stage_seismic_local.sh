#!/usr/bin/env bash
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
