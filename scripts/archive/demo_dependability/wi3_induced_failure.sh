#!/usr/bin/env bash
# CLOSED DEAD 2026-09-25 — demo-dependability WI harness for the OCI deployment that was gone on 2026-09-25 (docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md); evidence kept, bars live in source at pinned commits
set -u
cd /workspaces/sfu-library-thinclient
PORT=${SFU_DEMO_STAGING_PORT:-8170}
WATCHDOG_LOG=data/eval_results/_deployprep_watchdog.log
WATCHDOG_REPORT=data/eval_results/_deployprep_watchdog_report.json
LOAD_FAIL=data/eval_results/wi3_load_failure_$(date -u +%Y%m%d_%H%M%S).json
rm -f "$WATCHDOG_REPORT"

echo "=== WI-3 induced-failure orchestration (port $PORT) $(date -u +%H:%M:%SZ) ==="

SFU_DEMO_WATCHDOG=1 SFU_DEMO_STAGING_PORT=$PORT SFU_SKIP_BMP=1 \
  .venv/bin/python3 scripts/archive/demo_dependability/watchdog.py \
    --port $PORT --max-restarts 5 --fail-fast > "$WATCHDOG_LOG" 2>&1 &
WD_PID=$!
echo "watchdog pid $WD_PID (log $WATCHDOG_LOG)"

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

SERVE_PID=$(pgrep -f "staging_serve.py" | head -1)
echo "staging_serve pid: ${SERVE_PID:-NONE}"
if [ -z "$SERVE_PID" ]; then echo "ERROR: no staging_serve pid found"; kill $WD_PID; exit 1; fi

.venv/bin/python3 scripts/archive/demo_dependability/load_driver.py \
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
