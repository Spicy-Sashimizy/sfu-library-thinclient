#!/usr/bin/env bash
# Off-BMP Qdrant ingest watchdog — ONE check-and-heal pass. Idempotent; meant to
# be called on an interval (e.g. via /loop ~15m).
#
# Failure mode it guards (observed 2026-06-19): _parallel_worker upserts with
# wait=True and no retry. When Qdrant goes status=red the upsert blocks past the
# 600s gRPC timeout and the worker process dies; the parent's pool.map_async can't
# detect a dead child, so it logs aggregate stats for hours while N/8 workers are
# gone. A full parent relaunch resumes every worker from its checkpoint cleanly
# (proven 2026-06-20: workers 0/1/7 went 190k -> 2.5M after restart), so the cheap
# fix is: detect a stalled/dead parent and relaunch. No edit to the live job.
#
# Exit prints one WATCHDOG_* token on stdout for the caller to branch on.
set -uo pipefail

ROOT=/workspaces/sfu-library-thinclient
CKPT=$ROOT/data/qdrant_spike/ckpt/splade_150m
ING_LOG=$ROOT/logs/qdrant_ingest_150m.log
QD_LOG=$ROOT/logs/qdrant_offbmp.log
WD_LOG=$ROOT/logs/bmp_watchdog.log
SENTINEL=$ROOT/data/qdrant_spike/.wd_last_launch
TARGET=150400000
STALL_SECS=720    # 12 min without a checkpoint write on a non-complete worker = stalled
GRACE_SECS=1200   # 20 min after a (re)launch: workers seek to resume_line w/o writing ckpts

log(){ echo "$(date '+%F %T') $*" >> "$WD_LOG"; }

ensure_qdrant(){
  if curl -s -m 5 http://localhost:6333/collections/splade_150m | grep -q '"status"'; then return 0; fi
  log "qdrant down -> starting"
  ( cd "$ROOT/data/qdrant_spike" && \
    QDRANT__STORAGE__STORAGE_PATH="$ROOT/data/qdrant_spike/storage" HOME=/home/vscode \
    nohup "$ROOT/.tools/qdrant/qdrant" >> "$QD_LOG" 2>&1 & )
  for _ in $(seq 1 30); do
    sleep 6
    curl -s -m 5 http://localhost:6333/collections/splade_150m | grep -q '"status"' && { log "qdrant up"; return 0; }
  done
  log "ERROR: qdrant did not come up"; return 1
}

launch_ingest(){
  ensure_qdrant || return 1
  ( cd "$ROOT" && HOME=/home/vscode \
    nohup .venv/bin/python3 scripts/spike_qdrant_sparse.py build-spool-par \
      --n 250000000 --collection splade_150m --workers 8 --batch 1000 --segments 24 --opt-threads 8 \
      >> "$ING_LOG" 2>&1 & )
  date +%s > "$SENTINEL"
  log "ingest (re)launched"
}

points=$(curl -s -m 5 http://localhost:6333/collections/splade_150m \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['points_count'])" 2>/dev/null || echo 0)

# --- done? all workers complete OR target reached ---
allcomplete=1
for f in "$CKPT"/worker_*.json; do grep -q '"complete": true' "$f" 2>/dev/null || allcomplete=0; done
if [ "$allcomplete" = 1 ] || [ "${points:-0}" -ge "$TARGET" ]; then
  log "DONE points=$points target=$TARGET allcomplete=$allcomplete"
  echo "WATCHDOG_DONE points=$points"; exit 0
fi

# --- dead parent? relaunch (crash recovery) ---
if ! pgrep -f "spike_qdrant_sparse.py build-spool-par" >/dev/null; then
  log "parent NOT running (points=$points) -> relaunch"
  launch_ingest
  echo "WATCHDOG_RELAUNCHED_DEAD_PARENT points=$points"; exit 0
fi

# --- inside post-launch grace? skip stall detection (seek writes no ckpts) ---
now=$(date +%s)
if [ -f "$SENTINEL" ]; then
  since=$(( now - $(cat "$SENTINEL") ))
  if [ "$since" -lt "$GRACE_SECS" ]; then
    log "healthy (grace ${since}s) points=$points"
    echo "WATCHDOG_HEALTHY_GRACE points=$points"; exit 0
  fi
fi

# --- stalled worker? non-complete checkpoint not written in STALL_SECS ---
stalled=""
for f in "$CKPT"/worker_*.json; do
  grep -q '"complete": true' "$f" 2>/dev/null && continue
  age=$(( now - $(stat -c %Y "$f") ))
  [ "$age" -gt "$STALL_SECS" ] && stalled="$stalled $(basename "$f")(${age}s)"
done
if [ -n "$stalled" ]; then
  # Emit the token FIRST: the kill path can perturb this script's signals, so the
  # caller must learn the decision before anything destructive runs.
  echo "WATCHDOG_RESTARTED_STALL points=$points stalled:$stalled"
  log "STALLED:$stalled -> kill parent + relaunch"
  pkill -f "spike_qdrant_sparse.py build-spool-par"; sleep 8
  pkill -9 -f "spike_qdrant_sparse.py build-spool-par" 2>/dev/null
  launch_ingest
  exit 0
fi

log "healthy points=$points (parent alive, checkpoints fresh)"
echo "WATCHDOG_HEALTHY points=$points"; exit 0
