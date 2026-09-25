#!/usr/bin/env bash
set -u
cd /workspaces/sfu-library-thinclient

PORT=${SFU_DEMO_UPDATE_PORT:-8197}          # a STAGING port (NOT the 8159/8180 demo ports)
QUERIES=${SFU_DEMO_UPDATE_GATE_QUERIES:-6}  # smoke-query count for the gate
WARMUP_N=${SFU_DEMO_WARMUP_N:-12}
BASE_MANIFEST=${SFU_DEMO_UPDATE_BASE_MANIFEST:-data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json}
TS=$(date -u +%Y%m%d_%H%M%S)
FIXDIR=data/eval_results/_fixtures
WATCHDOG_LOG=data/eval_results/_wi13_watchdog_${TS}.log
VENV=.venv/bin/python3

GRACE=600

TIMELINE_FILE=""
_SMOKE_DETAIL_F=/tmp/_wi13_smoke_detail_${TS}
: > "$_SMOKE_DETAIL_F"
init_timeline () {
  TIMELINE_FILE=data/eval_results/wi13_update_${ARM}_${TS}.json
  echo "{" > /tmp/_wi13_tl_${TS}_${ARM}
  echo "  \"arm\": \"$ARM\", \"start_utc\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\", \"port\": $PORT," >> /tmp/_wi13_tl_${TS}_${ARM}
  echo "  \"base_manifest\": \"$BASE_MANIFEST\", \"smoke_queries\": $QUERIES," >> /tmp/_wi13_tl_${TS}_${ARM}
  echo "  \"events\": [" >> /tmp/_wi13_tl_${TS}_${ARM}
  _first=1
}
event () {  # event <stage> <status> <detail>
  local stage="$1" status="$2" detail="$3"
  local ts; ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  local ms; ms=$(date -u +%s%3N 2>/dev/null || python3 -c 'import time;print(int(time.time()*1000))')
  if [ $_first -eq 1 ]; then _first=0; else echo "    ," >> /tmp/_wi13_tl_${TS}_${ARM}; fi
  printf '    {"t":"%s","ms":%s,"stage":"%s","status":"%s","detail":%s}\n' \
    "$ts" "$ms" "$stage" "$status" "$(printf '%s' "$detail" | $VENV -c 'import sys,json;print(json.dumps(sys.stdin.read()))')" \
    >> /tmp/_wi13_tl_${TS}_${ARM}
  echo "  [$stage] $status — $detail"
}
finish_timeline () {  # finish_timeline <overall> <downtime_ms_or_null> <rolled_back_bool>
  local overall="$1" downtime="$2" rb="$3"
  echo "  ]," >> /tmp/_wi13_tl_${TS}_${ARM}
  echo "  \"overall\": \"$overall\", \"downtime_ms\": ${downtime:-null}, \"rolled_back\": $rb," >> /tmp/_wi13_tl_${TS}_${ARM}
  echo "  \"end_utc\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" >> /tmp/_wi13_tl_${TS}_${ARM}
  echo "}" >> /tmp/_wi13_tl_${TS}_${ARM}
  cp /tmp/_wi13_tl_${TS}_${ARM} "$TIMELINE_FILE"
}

health_json () { curl -s -m 5 http://127.0.0.1:$PORT/health 2>/dev/null \
  | $VENV -c "import sys,json;
try:
 d=json.load(sys.stdin); print(d.get('status'), d.get('warm'))
except Exception: print('ERR','ERR',file=sys.stderr)" 2>/dev/null || echo "ERR ERR"; }

launch_watchdog () {  # launch_watchdog <manifest_env_value>   (the staged manifest path, or BASE for baseline)
  local MANIFEST="$1"
  rm -f data/eval_results/_deployprep_watchdog_report.json
  env SFU_SEISMIC_SHARD_MANIFEST="$MANIFEST" \
      SFU_DEMO_WATCHDOG=1 SFU_DEMO_STAGING_PORT=$PORT \
      SFU_SKIP_BMP=1 SFU_DEMO_WATCHDOG_COLD_GRACE_S=$GRACE \
      SFU_DEMO_WARMUP=1 SFU_DEMO_WARMUP_N=$WARMUP_N \
      SFU_DEMO_WATCHDOG_WAIT_WARM=1 \
      SFU_DEMO_UPDATE_VERIFY_SEISMIC=1 \
      SFU_DEMO_WATCHDOG_PYTHON=/workspaces/sfu-library-thinclient/.venv/bin/python3 \
      $VENV scripts/archive/demo_dependability/watchdog.py \
        --port $PORT --max-restarts 4 --fail-fast > "$WATCHDOG_LOG" 2>&1 &
  WD_PID=$!
  echo "$WD_PID"
}

wait_warm () {  # wait_warm <deadline_s>  → echoes "ok"/"timeout"
  local deadline="$1" i
  for i in $(seq 1 "$deadline"); do
    HJ=$(health_json)
    if [ "$HJ" = "ok True" ]; then echo ok; return 0; fi
    sleep 1
  done
  echo timeout
}

smoke_gate () {  # smoke_gate  → echoes "pass"/"fail"
  local ok=0 fail=0 q
  for q in "climate change adaptation policy" "graph neural networks" \
           "political economy welfare states" "deep learning protein structure" \
           "coastal cities sea level rise" "machine learning fairness"; do
    [ $((ok+fail)) -ge $QUERIES ] && break
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 30 -X POST \
      http://127.0.0.1:$PORT/search -H 'Content-Type: application/json' \
      -d "{\"query\":\"$q\",\"top_k\":5}" 2>/dev/null || echo 000)
    if [ "$code" = "200" ]; then ok=$((ok+1)); else fail=$((fail+1)); fi
  done
  local SEIS; SEIS=$(curl -s -m 30 http://127.0.0.1:$PORT/verify 2>/dev/null \
    | $VENV -c "import sys,json;
try: d=json.load(sys.stdin); print(d.get('seismic_loaded'))
except Exception: print('ERR')" 2>/dev/null || echo ERR)
  if [ "$fail" -eq 0 ] && [ "$ok" -ge 1 ] && [ "$SEIS" = "True" ]; then
    echo "search=$ok ok/$fail fail, seismic_loaded=$SEIS" > "$_SMOKE_DETAIL_F"
    echo pass
  elif [ "$SEIS" = "False" ]; then
    echo "seismic_loaded=False — SEISMIC silently fell back to BM25F; the new shard set did NOT load" > "$_SMOKE_DETAIL_F"
    echo fail
  else
    echo "search=$ok ok/$fail fail, seismic_loaded=$SEIS" > "$_SMOKE_DETAIL_F"
    echo fail
  fi
}

stop_watchdog () {  # stop_watchdog <wd_pid>
  local wd="$1"
  kill "$wd" 2>/dev/null || true
  sleep 2
  pkill -f "staging_serve.py" 2>/dev/null || true   # belt-and-suspenders, only the staging serve
  wait "$wd" 2>/dev/null || true
}

sha256_file () { sha256sum "$1" 2>/dev/null | awk '{print $1}'; }

run_update_arm () {
  ARM="$1"; local NEW_MANIFEST="$2"; local EXPECT_RB="$3"
  init_timeline
  event setup started "arm=$ARM base=$(basename $BASE_MANIFEST) new=$(basename $NEW_MANIFEST) expect_rollback=$EXPECT_RB"

  local WD
  WD=$(launch_watchdog "$BASE_MANIFEST")
  event baseline_watchdog_launched running "wd_pid=$WD manifest=$(basename $BASE_MANIFEST)"
  local R; R=$(wait_warm 620)
  if [ "$R" != "ok" ]; then
    event baseline_warm FAILED "wait_warm=$R (watchdog log tail: $(tail -3 $WATCHDOG_LOG 2>/dev/null | tr '\n' ' '))"
    stop_watchdog "$WD"
    finish_timeline ABORTED null false
    return 1
  fi
  local PRE=$(smoke_gate)
  event baseline_warm ok "wait_warm ok; pre-gate smoke=$PRE ($(cat "$_SMOKE_DETAIL_F"))"
  if [ "$PRE" != "pass" ]; then
    event baseline_smoke FAILED "pre-update gate on base manifest did not pass; aborting (no flip attempted)"
    stop_watchdog "$WD"
    finish_timeline ABORTED null false
    return 1
  fi

  local NEW_SHA; NEW_SHA=$(sha256_file "$NEW_MANIFEST")
  if [ -z "$NEW_SHA" ]; then
    event checksum_verify FAILED "new manifest $NEW_MANIFEST absent — ABORT before flip"
    stop_watchdog "$WD"
    finish_timeline ABORTED null false
    return 1
  fi
  event checksum_verify ok "new_manifest_sha256=${NEW_SHA:0:16} (stage-beside: the old manifest is untouched; flip is env-only)"

  local FLIP_T0; FLIP_T0=$(date -u +%s%3N 2>/dev/null || python3 -c 'import time;print(int(time.time()*1000))')
  stop_watchdog "$WD"
  event flip_started running "stopped baseline serve; relaunching watchdog with SFU_SEISMIC_SHARD_MANIFEST=$(basename $NEW_MANIFEST)"
  WD=$(launch_watchdog "$NEW_MANIFEST")
  event new_watchdog_launched running "wd_pid=$WD (wait-warm ON, cold_grace=${GRACE}s)"

  R=$(wait_warm 620)
  local FLIP_T1; FLIP_T1=$(date -u +%s%3N 2>/dev/null || python3 -c 'import time;print(int(time.time()*1000))')
  local DOWNTIME=$((FLIP_T1 - FLIP_T0))
  if [ "$R" = "ok" ]; then
    local G; G=$(smoke_gate)
    event new_gate ok "post-flip wait_warm=ok smoke=$G ($(cat "$_SMOKE_DETAIL_F")) (downtime=${DOWNTIME}ms = the warm-restart + re-warm window)"
    if [ "$G" = "pass" ]; then
      event commit ok "gate PASS on new version — update committed, NO rollback"
      stop_watchdog "$WD"
      finish_timeline PASS "$DOWNTIME" false
      return 0
    else
      event new_smoke FAILED "post-flip /health warm but smoke FAILED ($(cat "$_SMOKE_DETAIL_F")) — triggering auto-rollback"
    fi
  else
    event new_gate FAILED "post-flip wait_warm=$R (serve failed to warm on the new version — watchdog log: $(grep -E 'DIED|rc=|FAIL-FAST|FATAL' $WATCHDOG_LOG 2>/dev/null | tail -2 | tr '\n' ' ')) — triggering auto-rollback"
  fi

  if [ "${SFU_DEMO_UPDATE_NO_ROLLBACK:-0}" = "1" ]; then
    event rollback SKIPPED "SFU_DEMO_UPDATE_NO_ROLLBACK=1 — rollback disabled for debugging"
    stop_watchdog "$WD"
    finish_timeline FAIL_ATTEMPTED_NO_ROLLBACK "$DOWNTIME" false
    return 1
  fi
  event rollback_started running "AUTO-ROLLBACK: stopping new-version serve, flipping back to $(basename $BASE_MANIFEST) (old manifest+shards still present — stage-beside discipline)"
  stop_watchdog "$WD"
  WD=$(launch_watchdog "$BASE_MANIFEST")
  R=$(wait_warm 620)
  if [ "$R" = "ok" ]; then
    local RG; RG=$(smoke_gate)
    event rollback_gate ok "post-rollback wait_warm=ok smoke=$RG ($(cat "$_SMOKE_DETAIL_F"))"
    if [ "$RG" = "pass" ]; then
      event rollback_committed ok "serve re-serving on the PRIOR version (baseline restored) — rollback SUCCESSFUL, demo ends SERVING"
      stop_watchdog "$WD"
      finish_timeline PASS_ROLLED_BACK "$DOWNTIME" true
      return 0
    else
      event rollback_smoke FAILED "post-rollback smoke FAILED ($(cat "$_SMOKE_DETAIL_F")) — serve not restored (manual intervention needed)"
      stop_watchdog "$WD"
      finish_timeline FAIL_ROLLBACK_BROKEN "$DOWNTIME" true
      return 1
    fi
  else
    event rollback_gate FAILED "post-rollback wait_warm=$R — serve did not re-warm on prior version"
    stop_watchdog "$WD"
    finish_timeline FAIL_ROLLBACK_BROKEN "$DOWNTIME" true
    return 1
  fi
}

mkdir -p "$FIXDIR"

SUCCESS_MANIFEST="$FIXDIR/wi13_staged_new_manifest_${TS}.json"
cp "$BASE_MANIFEST" "$SUCCESS_MANIFEST"
$VENV - "$SUCCESS_MANIFEST" "$TS" <<'PY'
import json, sys
p, ts = sys.argv[1], sys.argv[2]
d = json.loads(open(p).read())
d["wi13_staged_copy"] = f"staging fixture for WI-13 update_demo.sh ({ts}); a copy of the served e5_v2 manifest modeling the manifest_flip_only / .so-rebuild update class (shards resident → fast re-warm). A real cross-version flip points SFU_SEISMIC_SHARD_MANIFEST at a genuinely-new manifest (e.g. e5_v1 on the ladder); the update FLOW is identical."
open(p, "w").write(json.dumps(d, indent=2))
PY

BROKEN_MANIFEST="$FIXDIR/wi13_broken_manifest_${TS}.json"
$VENV - "$BROKEN_MANIFEST" "$BASE_MANIFEST" "$TS" <<'PY'
import json, os, sys, shutil
from pathlib import Path
out, base, ts = sys.argv[1], sys.argv[2], sys.argv[3]
REPO = Path("/workspaces/sfu-library-thinclient")
d = json.loads(open(base).read())
fx = REPO / "data/eval_results/_fixtures" / f"wi13_truncated_shard0_{ts}.mmap"
if fx.exists():
    shutil.rmtree(fx)
fx.mkdir(parents=True)
# copy shard0's REAL manifest.json (READ-ONLY on the real shard — this is a
# read of the versioned pointer, not the shard data) + a TRUNCATED data blob.
src_manifest = REPO / d["shards"][0]["mmap_dir"] / "manifest.json"
if src_manifest.exists():
    shutil.copy(src_manifest, fx / "manifest.json")
(fx / "data.bin").write_bytes(b"\x00" * 16)
(fx / "index.bin").write_bytes(b"\xde\xad\xbe\xef")
# repoint shard0 at the truncated fixture; the other 7 shards stay real so the
# fault is isolated to shard0 (a load-fault the WI-10 boundary would also catch).
d["shards"][0]["mmap_dir"] = str(fx.relative_to(REPO))
d["wi13_broken_fixture"] = f"shard0 mmap_dir repointed at a truncated fixture ({fx.name}); the pyo3 reader raises on load → serve exits non-zero → gate FAILS → auto-rollback. The other 7 shards are real (isolate the fault to shard0). Staging fixture {ts}."
open(out, "w").write(json.dumps(d, indent=2))
print(f"wrote broken fixture manifest {out} (shard0 → {fx})")
PY

echo "============================================================"
echo " WI-13 update_demo.sh — staging proofs (port $PORT, $(date -u +%H:%M:%SZ))"
echo "   success arm: flip base → staged copy (manifest_flip_only class)"
echo "   broken  arm: flip base → corrupt shard0 fixture (auto-rollback)"
echo "============================================================"

echo ""; echo "=== ARM 1: success (expect commit, no rollback) ==="
run_update_arm success "$SUCCESS_MANIFEST" 0 \
  && echo "SUCCESS arm: PASS (committed, no rollback)" \
  || echo "SUCCESS arm: did NOT commit as expected (see timeline)"

$VENV - "$BASE_MANIFEST" <<'PY' 2>/dev/null || true
import json, os, ctypes
m = json.load(open(__import__("sys").argv[1]))
libc = ctypes.CDLL("libc.so.6", use_errno=True)
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
            libc.posix_fadvise(fd, ctypes.c_long(0), ctypes.c_long(sz), 4)
            os.close(fd); n += 1
        except OSError: pass
print(f"fadvise-DONTNEED applied to {n} shard files (cool between arms)")
PY

echo ""; echo "=== ARM 2: broken (expect gate FAIL + auto-rollback to serving) ==="
run_update_arm broken "$BROKEN_MANIFEST" 1 \
  && echo "BROKEN arm: PASS (auto-rolled back to serving)" \
  || echo "BROKEN arm: rollback did NOT restore serving (see timeline)"

echo ""; echo "=== WI-13 summary ($(date -u +%H:%M:%SZ)) ==="
for ARM in success broken; do
  F=$(ls -t data/eval_results/wi13_update_${ARM}_${TS}.json 2>/dev/null | head -1)
  [ -z "$F" ] && { echo "  $ARM: (no timeline)"; continue; }
  echo "  $ARM ($F):"
  $VENV - "$F" <<'PY' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
print(f"    overall={d.get('overall')} rolled_back={d.get('rolled_back')} downtime_ms={d.get('downtime_ms')}")
# the gate verdict events are the bars:
for e in d.get("events", []):
    if e["stage"] in ("new_gate", "new_smoke", "rollback_gate", "rollback_committed", "commit", "checksum_verify"):
        print(f"    [{e['stage']}] {e['status']} — {e['detail'][:90]}")
PY
done
echo "DONE."
