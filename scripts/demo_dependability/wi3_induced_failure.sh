#!/usr/bin/env bash
# WI-3 induced-failure orchestration: run the staging serve UNDER the watchdog,
# fire a concurrency-8 load, kill the serve mid-load, measure the watchdog's
# recovery (death -> restart -> first healthy probe) + the client-visible dead
# window. STAGING ONLY (127.0.0.1, no public deploy, no spend).
#
# Why the watchdog manages the serve (not a bare launch): the deliverable is
# "does the watchdog detect + restart a killed serve" — so the serve must be a
# child of the watchdog for the kill->restart->recover cycle to be measured.
# The load driver kills the SERVE pid (passed via --serve-pid), not the watchdog.
set -u
cd /workspaces/sfu-library-thinclient
PORT=${SFU_DEMO_STAGING_PORT:-8170}
WATCHDOG_LOG=data/eval_results/_deployprep_watchdog.log
WATCHDOG_REPORT=data/eval_results/_deployprep_watchdog_report.json
LOAD_FAIL=data/eval_results/wi3_load_failure_$(date -u +%Y%m%d_%H%M%S).json
rm -f "$WATCHDOG_REPORT"

echo "=== WI-3 induced-failure orchestration (port $PORT) $(date -u +%H:%M:%SZ) ==="

# 1. Launch the watchdog (manages the staging serve). fail-fast so it exits
#    after a bounded number of restarts (we kill the serve + let it restart once,
#    then stop). max-restarts 5 bounds a thrash loop.
SFU_DEMO_WATCHDOG=1 SFU_DEMO_STAGING_PORT=$PORT SFU_SKIP_BMP=1 \
  .venv/bin/python3 scripts/demo_dependability/watchdog.py \
    --port $PORT --max-restarts 5 --fail-fast > "$WATCHDOG_LOG" 2>&1 &
WD_PID=$!
echo "watchdog pid $WD_PID (log $WATCHDOG_LOG)"

# 2. Wait for the serve to come up (watchdog launches it; /health responds).
#    The cold first-health can take ~2min (shards + ONNX session cold-load).
READY=0
for i in $(seq 1 180); do
  if curl -s -m 5 http://127.0.0.1:$PORT/health >/dev/null 2>&1; then
    READY=1; break
  fi
  sleep 1
done
if [ $READY -ne 1 ]; then
  echo "ERROR: serve did not become healthy in 180s; watchdog log:"; tail -20 "$WATCHDOG_LOG"
  kill $WD_PID 2>/dev/null; exit 1
fi
echo "serve healthy after ${i}s ($(date -u +%H:%M:%SZ))"

# 3. Find the staging_serve PID the watchdog launched (its child).
SERVE_PID=$(pgrep -f "staging_serve.py" | head -1)
echo "staging_serve pid: ${SERVE_PID:-NONE}"
if [ -z "$SERVE_PID" ]; then echo "ERROR: no staging_serve pid found"; kill $WD_PID; exit 1; fi

# 4. Run the induced-failure load: concurrency 8 for 30s, kill the serve at 3s.
.venv/bin/python3 scripts/demo_dependability/load_driver.py \
  --port $PORT --induce-failure --serve-pid "$SERVE_PID" \
  --kill-after-s 3.0 --duration-s 30 --concurrency 8 --queries 12 \
  --top-k 10 --timeout 15 --result-file "$LOAD_FAIL"

echo "=== load done; reading watchdog recovery report ($(date -u +%H:%M:%SZ)) ==="
sleep 3
kill $WD_PID 2>/dev/null
wait $WD_PID 2>/dev/null

echo "=== WATCHDOG REPORT ==="
cat "$WATCHDOG_REPORT" 2>/dev/null || echo "(no report written — check $WATCHDOG_LOG)"
echo ""
echo "=== LOAD FAILURE CELL ==="
cat "$LOAD_FAIL" 2>/dev/null | .venv/bin/python3 -m json.tool 2>/dev/null | head -25
echo "=== watchdog log tail ==="
tail -15 "$WATCHDOG_LOG"
