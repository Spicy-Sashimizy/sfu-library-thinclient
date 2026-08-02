#!/usr/bin/env bash
# Wait for the SEISMIC stage to finish, then run N6 — smoke first, then full.
#
# The smoke run exists to calibrate: if a staged warm query is slow, the full
# sweep's 400+ searches would run for an hour, and it is better to find that
# out from 6 searches than from a hung sweep. It also proves the parity gate
# passes before spending the time.
set -u
cd /workspaces/sfu-library-thinclient

export SFU_SEISMIC_STAGE_DIR=/var/tmp/seismic_stage
PY=.venv/bin/python3
H=spike/meta_consolidation/11_n6_whole_query_latency.py
W=spike/meta_consolidation/work_ordinals_full
STAGE_PID="${1:-}"

if [ -n "$STAGE_PID" ]; then
  echo "N6: waiting for stage pid $STAGE_PID"
  # `kill -0` succeeds for a ZOMBIE, and nohup'd processes here reparent to
  # init which does not reap them — so a plain kill -0 loop waits forever on
  # work that finished. Treat Z as exited. (Cost 40 min of wall clock the
  # first time; the staging itself had completed in 7.)
  while kill -0 "$STAGE_PID" 2>/dev/null; do
    st=$(awk '/^State:/{print $2}' "/proc/$STAGE_PID/status" 2>/dev/null)
    [ "$st" = "Z" ] && break
    sleep 15
  done
fi
echo "N6: stage complete ($(du -sh /var/tmp/seismic_stage | cut -f1)) — starting smoke"

$PY "$H" --work "$W" --modes splade --top-k 50 \
    --queries 3 --reps 1 --warmup 2 \
    --out data/eval_results/n6_smoke.json
rc=$?
if [ $rc -ne 0 ]; then echo "N6 SMOKE FAILED rc=$rc"; exit $rc; fi
echo "N6: smoke OK — starting full sweep"

$PY "$H" --work "$W" --modes splade bm25f --top-k 10 50 100 \
    --queries 12 --reps 3 --warmup 5
rc=$?
echo "N6 FULL EXIT rc=$rc"
exit $rc
