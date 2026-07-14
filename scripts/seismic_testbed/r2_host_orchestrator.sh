#!/usr/bin/env bash
# R2 host orchestrator — runs the fine convergence ladder (backlog §R2).
#
# Runs on the WINDOWS HOST (Git Bash), NOT inside the dev container: the app
# container has no docker daemon and read-only cgroups (E7b finding,
# HOST_PROMPT_E7B_RAMCAP.md), so memory-capped cells must be sibling
# containers launched from here. The in-container GLM drive session
# (_r2_convergence_drive_prompt.md) verifies/commits cells as they land —
# this script only executes them and writes status files.
#
# Per rung: (1) drop the shared WSL2 page cache via a privileged throwaway
# container — WITHOUT this, the previous cell's residency leaks into pass 1
# and poisons the cold fill (cgroup charging is first-toucher); (2) run the
# capped sibling with the R2 driver; (3) write DONE/FAIL(rc) status.
#
# Usage (from repo root on the host):
#   bash scripts/seismic_testbed/r2_host_orchestrator.sh
set -u
export MSYS_NO_PATHCONV=1

HOSTREPO="C:/Users/<user>/claudebox-projects/sfu-library-thinclient"
CREPO="/workspaces/sfu-library-thinclient"
IMG="claudebox-sfu-library-thinclient-app"
EV="$HOSTREPO/data/eval_results"
DATE=$(date +%Y%m%d)
CELL_TIMEOUT=6000          # 100 min in-container hard stop per cell

# marginal band fine sweep, then anchors, then replicates (rep2:) at key rungs
RUNGS="${1:-17 16 15 14 13 12 11 10 9 24 6 rep2:16 rep2:13 rep2:11}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

for R in $RUNGS; do
  SUF=""
  G="$R"
  case "$R" in rep2:*) G="${R#rep2:}"; SUF="_rep2";; esac
  LABEL="cap${G}g${SUF}"
  STATUS="$EV/_r2_${LABEL}.status"
  CLOG="$EV/_r2_${LABEL}_drive.log"
  RESULT="data/eval_results/r2_${LABEL}_${DATE}.json"

  log "=== rung $LABEL ==="
  echo "RUNNING $(date -u +%FT%TZ)" > "$STATUS"

  log "dropping shared WSL2 page cache (cold-start purity)"
  docker run --rm --privileged alpine \
    sh -c 'sync; echo 1 > /proc/sys/vm/drop_caches' \
    || { log "drop_caches FAILED — aborting ladder (cells would be contaminated)";
         echo "FAIL drop_caches $(date -u +%FT%TZ)" > "$STATUS"; exit 1; }

  docker run --rm --name "r2cell_${LABEL}" \
    --memory="${G}g" --memory-swap="${G}g" \
    -v "${HOSTREPO}:${CREPO}" -w "${CREPO}" \
    -e SFU_SEISMIC_PREFLOOR_HOTSET=1 \
    "$IMG" timeout "$CELL_TIMEOUT" .venv/bin/python3 \
      scripts/seismic_testbed/r2_convergence_ladder.py \
      --cap-label "${G}g" --result-file "$RESULT" \
    > "$CLOG" 2>&1
  RC=$?

  if [ "$RC" -eq 0 ] && [ -s "$HOSTREPO/$RESULT" ]; then
    echo "DONE $(date -u +%FT%TZ) $RESULT" > "$STATUS"
    log "rung $LABEL DONE -> $RESULT"
  else
    echo "FAIL rc=$RC $(date -u +%FT%TZ)" > "$STATUS"
    log "rung $LABEL FAIL rc=$RC (124=timeout, 3=empty-results) — continuing"
  fi
done

{
  echo "ALLDONE $(date -u +%FT%TZ)"
  echo "rungs: $RUNGS"
  for f in "$EV"/_r2_cap*.status; do echo "$(basename "$f"): $(cat "$f")"; done
} > "$EV/_r2_ladder.ALLDONE"
log "=== ladder complete — wrote _r2_ladder.ALLDONE ==="
