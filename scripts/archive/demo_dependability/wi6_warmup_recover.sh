#!/usr/bin/env bash
set -u
cd /workspaces/sfu-library-thinclient

PORT=${SFU_DEMO_STAGING_PORT:-8180}
DURATION=${WI6_DURATION_S:-40}        # long enough to span kill + warm recovery
KILL_AFTER=${WI6_KILL_AFTER_S:-4.0}
CONCURRENCY=${WI6_CONCURRENCY:-8}
NQUERIES=${WI6_QUERIES:-12}
WARMUP_N=${SFU_DEMO_WARMUP_N:-24}
TS=$(date -u +%Y%m%d_%H%M%S)

run_arm () {
  local ARM="$1"            # before | after
  local EXTRA_ENV="$2"      # env to export for THIS arm's serve+watchdog
  local OUT=data/eval_results/wi6_recover_${ARM}_${TS}.json
  local WLOG=data/eval_results/_wi6_watchdog_${ARM}.log
  local WREP=data/eval_results/_wi6_watchdog_report_${ARM}.json
  rm -f "$WREP" data/eval_results/_deployprep_watchdog_report.json

  local GRACE=480
  if [ "$ARM" = "after" ]; then GRACE=600; fi

  echo "=== WI-6 arm=${ARM} ($(date -u +%H:%M:%SZ)) port ${PORT} ==="
  echo "    env: ${EXTRA_ENV:-<none>}  cold_grace=${GRACE}s"

  env $EXTRA_ENV \
    SFU_DEMO_WATCHDOG=1 SFU_DEMO_STAGING_PORT=$PORT \
    SFU_SKIP_BMP=1 SFU_DEMO_WATCHDOG_COLD_GRACE_S=$GRACE \
    SFU_DEMO_WATCHDOG_PYTHON=/workspaces/sfu-library-thinclient/.venv/bin/python3 \
    .venv/bin/python3 scripts/archive/demo_dependability/watchdog.py \
      --port $PORT --max-restarts 5 --fail-fast > "$WLOG" 2>&1 &
  local WD_PID=$!
  echo "    watchdog pid $WD_PID (log $WLOG)"

  local READY=0 i
  health_json () { curl -s -m 5 http://127.0.0.1:$PORT/health 2>/dev/null \
    | .venv/bin/python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status'), d.get('warm'))" 2>/dev/null; }
  for i in $(seq 1 600); do
    HJ=$(health_json)
    if [ "$ARM" = "after" ]; then
      if [ "$HJ" = "ok True" ]; then READY=1; break; fi
    else  # before
      if [ "$HJ" = "ok True" ] || [ "$HJ" = "ok False" ]; then
        curl -s -m 60 -X POST http://127.0.0.1:$PORT/search \
          -H 'Content-Type: application/json' \
          -d '{"query":"climate change adaptation policy","top_k":10}' >/dev/null 2>&1
        READY=1; break
      fi
    fi
    sleep 1
  done
  if [ $READY -ne 1 ]; then
    echo "ERROR: arm ${ARM} serve not ready in 600s; watchdog log tail:"; tail -20 "$WLOG"
    kill $WD_PID 2>/dev/null; return 1
  fi
  echo "    ready after ${i}s ($(date -u +%H:%M:%SZ))"

  local SERVE_PID
  SERVE_PID=$(pgrep -f "staging_serve.py" | head -1)
  if [ -z "$SERVE_PID" ]; then echo "ERROR: no staging_serve pid"; kill $WD_PID; return 1; fi
  echo "    staging_serve pid: $SERVE_PID"

  grep -E 'majflt|VmRSS|VmSwap' /proc/$SERVE_PID/status 2>/dev/null \
    > data/eval_results/_wi6_prekill_${ARM}_${TS}.stat || true
  cat /proc/$SERVE_PID/stat 2>/dev/null \
    | awk '{print "majflt_field10="$10}' >> data/eval_results/_wi6_prekill_${ARM}_${TS}.stat || true

  .venv/bin/python3 scripts/archive/demo_dependability/load_driver.py \
    --port $PORT --induce-failure --serve-pid "$SERVE_PID" \
    --kill-after-s "$KILL_AFTER" --duration-s "$DURATION" \
    --concurrency "$CONCURRENCY" --queries "$NQUERIES" \
    --top-k 10 --timeout 30 --result-file "$OUT"

  sleep 3
  kill $WD_PID 2>/dev/null
  wait $WD_PID 2>/dev/null
  cp data/eval_results/_deployprep_watchdog_report.json "$WREP" 2>/dev/null || true
  echo "=== ${ARM}: watchdog report ==="
  cat "$WREP" 2>/dev/null | .venv/bin/python3 -m json.tool 2>/dev/null | head -30 || true
  echo "=== ${ARM}: failure cell ==="
  .venv/bin/python3 -m json.tool "$OUT" 2>/dev/null | head -30 || true
}

run_arm before "" || echo "before arm FAILED"

echo "=== cooling page cache between arms (fadvise-DONTNEED seismic shards) ==="
.venv/bin/python3 - <<'PY' 2>/dev/null || true
import json, os, ctypes
m = json.load(open("data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"))
libc = ctypes.CDLL("libc.so.6", use_errno=True)
POSIX_FADV_DONTNEED = 4
n = 0
for s in m["shards"]:
    d = s.get("mmap_dir")
    if not d: continue
    if not os.path.isabs(d): d = os.path.join("/workspaces/sfu-library-thinclient", d)
    if not os.path.isdir(d): continue
    for fn in os.listdir(d):
        p = os.path.join(d, fn)
        if not os.path.isfile(p): continue
        try:
            fd = os.open(p, os.O_RDONLY)
            sz = os.fstat(fd).st_size
            libc.posix_fadvise(fd, ctypes.c_long(0), ctypes.c_long(sz), POSIX_FADV_DONTNEED)
            os.close(fd); n += 1
        except OSError: pass
print(f"fadvise-DONTNEED applied to {n} shard files")
PY

run_arm after "SFU_DEMO_WARMUP=1 SFU_DEMO_WARMUP_N=$WARMUP_N SFU_SEISMIC_PREFLOOR_HOTSET=1 SFU_DEMO_WATCHDOG_WAIT_WARM=1" \
  || echo "after arm FAILED"

echo ""
echo "=== WI-6 summary ($(date -u +%H:%M:%SZ)) ==="
for ARM in before after; do
  F=$(ls -t data/eval_results/wi6_recover_${ARM}_${TS}.json 2>/dev/null | head -1)
  W=data/eval_results/_wi6_watchdog_report_${ARM}.json
  echo "--- ${ARM} ($F) ---"
  .venv/bin/python3 - "$F" "$W" <<'PY' 2>/dev/null || true
import json, sys
f, w = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(f))
    c = (d.get("induced_failure") or {})
    print(f"  load: dead_window_errors={c.get('dead_window_errors')} "
          f"first_client_recovery_ms={c.get('first_client_recovery_ms_after_kill')} "
          f"total_ok={c.get('total_ok')}")
except Exception as e: print("  load cell:", e)
try:
    r = json.load(open(w))
    rs = r.get("restarts", [])
    if rs:
        rr = rs[-1]
        print(f"  watchdog: cause={rr.get('cause')} recovery_ms={rr.get('recovery_ms')} "
              f"healthy_after_restart={rr.get('healthy_after_restart')}")
except Exception as e: print("  watchdog:", e)
PY
done
echo "DONE."
