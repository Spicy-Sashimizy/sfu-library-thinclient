#!/usr/bin/env bash
# WI-7 (deployprep wave 2, 2026-07-17) — warm-state concurrent capacity sweep.
# STAGING ONLY (127.0.0.1, no public deploy, no spend). NUMBERS ONLY — no provisioning.
#
# WI-3's baseline sweep measured the COLD floor (~4-6 s p50 over a 20-query diverse
# working set — honest but NOT the demo's steady state: a warmed serve answers at
# sub-100 ms, WI-1 parallel warm p50 47 ms). WI-7 pre-warms the serve (the WI-6
# hook) then re-runs the concurrency sweep 1/4/8/16 (+32 if stable) → the demo's
# REAL warm capacity figure + the input the DO-sizing doc needs.
#
# Method: launch the serve under the watchdog WITH the WI-6 warmup hook ON (so
# /health warm=true), wait for warm, then run the load_driver baseline sweep +
# sample majflt before/after each level (warm verification: majflt≈0 means the
# working set is resident, NOT cold re-faulting). The watchdog stays ON for the
# sweep (the capacity figure is under supervision, the demo's real shape).
#
# Owner constraints: no deploy, no spend, no served-default flip (warmup hook is
# staging-env-gated, off by default). Numbers recorded in DEMO_DEPENDABILITY.md +
# a pointer row in DO_SIZING.md if the warm figures change its assumptions.
set -u
cd /workspaces/sfu-library-thinclient

PORT=${SFU_DEMO_STAGING_PORT:-8181}
TS=$(date -u +%Y%m%d_%H%M%S)
OUT=data/eval_results/wi7_warm_capacity_${TS}.json
WLOG=data/eval_results/_wi7_watchdog.log
rm -f data/eval_results/_deployprep_watchdog_report.json

echo "=== WI-7 warm-capacity sweep ($(date -u +%H:%M:%SZ)) port ${PORT} ==="
# Launch the watchdog + staging serve WITH the WI-6 warmup hook (F6 hotset prefault
# + warmup query set), wait-warm ON, generous cold grace for the cold load + warmup.
SFU_DEMO_WATCHDOG=1 SFU_DEMO_STAGING_PORT=$PORT SFU_SKIP_BMP=1 \
  SFU_DEMO_WARMUP=1 SFU_DEMO_WARMUP_N=${SFU_DEMO_WARMUP_N:-24} \
  SFU_DEMO_WARMUP_TOPK=${SFU_DEMO_WARMUP_TOPK:-10} \
  SFU_SEISMIC_PREFLOOR_HOTSET=1 \
  SFU_DEMO_WATCHDOG_WAIT_WARM=1 SFU_DEMO_WATCHDOG_COLD_GRACE_S=600 \
  SFU_DEMO_WATCHDOG_PYTHON=/workspaces/sfu-library-thinclient/.venv/bin/python3 \
  .venv/bin/python3 scripts/demo_dependability/watchdog.py \
    --port $PORT --max-restarts 5 --fail-fast > "$WLOG" 2>&1 &
WD_PID=$!
echo "watchdog pid $WD_PID (log $WLOG)"

# Wait for warm=true (the WI-6 hook completed — sweep measures warm steady state).
# Parse JSON with python (robust to whitespace — json.dumps adds a space).
READY=0
for i in $(seq 1 600); do
  W=$(curl -s -m 5 http://127.0.0.1:$PORT/health 2>/dev/null \
    | .venv/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('warm'))" 2>/dev/null)
  if [ "$W" = "True" ]; then
    READY=1; echo "serve WARM after ${i}s ($(date -u +%H:%M:%SZ))"; break
  fi
  sleep 1
done
if [ $READY -ne 1 ]; then
  echo "ERROR: serve never warm in 600s; watchdog log tail:"; tail -25 "$WLOG"
  kill $WD_PID 2>/dev/null; exit 1
fi

SERVE_PID=$(pgrep -f "staging_serve.py" | head -1)
echo "staging_serve pid: ${SERVE_PID:-NONE}"

# Pre-sweep majflt baseline (warm state — should be ~0 delta over the sweep if
# the working set stayed resident; the WI-7 H1 bar).
majflt_now () {
  local pid="$1"
  # field 10 of /proc/<pid>/stat = cumulative major faults
  awk '{print "majflt="$10}' /proc/$pid/stat 2>/dev/null
  grep -E '^VmRSS|^VmSwap|^RssAnon' /proc/$pid/status 2>/dev/null | tr '\n' ' '
  echo
}

echo "--- pre-sweep warm footprint ---"
majflt_now "$SERVE_PID" | tee data/eval_results/_wi7_prewarm_${TS}.stat

# The sweep: 1/4/8/16 (+32 if stable). WI-3 used --per-level 40 --queries 20; WI-7
# uses the same shape so the cold (WI-3) vs warm (WI-7) comparison is direct, plus
# majflt bookends per level. capture per-level majflt delta inline.
LEVELS="${WI7_LEVELS:-1,4,8,16,32}"
echo "--- warm concurrency sweep (levels: $LEVELS) ---"
python3 - <<PY
import subprocess, json, time, os, re
PORT = $PORT
LEVELS = [int(x) for x in "$LEVELS".split(",")]
SERVE_PID = "$SERVE_PID"
def majflt():
    try:
        parts = open(f"/proc/{SERVE_PID}/stat").read().split()
        return int(parts[9])  # field 10 (0-indexed 9)
    except Exception:
        return None
def rss():
    try:
        for l in open(f"/proc/{SERVE_PID}/status"):
            if l.startswith(("VmRSS:","VmSwap:","RssAnon:")):
                print("  ", l.strip())
    except Exception: pass
pre = majflt()
result = {"meta": {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "port": PORT, "levels": LEVELS, "warm": True,
                   "warmup_hook": "SFU_DEMO_WARMUP=1 + SFU_SEISMIC_PREFLOOR_HOTSET=1"},
          "pre_sweep_majflt": pre, "levels": []}
for c in LEVELS:
    print(f"=== warm concurrency={c} ===", flush=True)
    before = majflt()
    p = subprocess.run([".venv/bin/python3", "scripts/demo_dependability/load_driver.py",
        "--port", str(PORT), "--concurrency", str(c), "--queries", "20",
        "--per-level", "40", "--top-k", "10", "--timeout", "30",
        "--result-file", f"data/eval_results/_wi7_cell_c{c}_${TS}.json"],
        capture_output=True, text=True, cwd=".")
    after = majflt()
    cell = None
    try:
        d = json.load(open(f"data/eval_results/_wi7_cell_c{c}_${TS}.json"))
        cell = (d.get("baseline") or [None])[0]
    except Exception as e:
        cell = {"load_error": str(e)[:120]}
    print(p.stdout[-300:])
    if cell:
        lm = cell.get("latency_ms", {}) if isinstance(cell, dict) else {}
        print(f"  c={c}: p50={lm.get('p50')} p95={lm.get('p95')} "
              f"errs={cell.get('errors')}/{cell.get('completed')} "
              f"qps={cell.get('throughput_qps')} majflt_delta={None if (before is None or after is None) else (after-before)}",
              flush=True)
    result["levels"].append({"concurrency": c, "majflt_before": before,
                             "majflt_after": after, "cell": cell})
rss()
result["post_sweep_majflt"] = majflt()
json.dump(result, open("$OUT", "w"), indent=2)
print(f"\\nWARM CAPACITY RESULT -> $OUT")
PY

echo "=== RESULT ==="
.venv/bin/python3 -m json.tool "$OUT" 2>/dev/null | head -40
echo "--- watchdog log tail ---"; tail -10 "$WLOG"
kill $WD_PID 2>/dev/null; wait $WD_PID 2>/dev/null
echo "DONE."
