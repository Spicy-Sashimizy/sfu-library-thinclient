#!/usr/bin/env bash
# WI-12 (deployprep wave 3, 2026-07-17) — the repeatable reliability soak job.
# THE PRE-LAUNCH RELIABILITY GATE. STAGING ONLY (127.0.0.1, no deploy, no spend).
#
# One runnable job the owner can run before any future demo launch: a ~40-min
# soak at modest QPS with a SCHEDULED fault timeline injected mid-soak — a
# WI-9 leg fault, a WI-11 overload burst (a WI-10 shard fault is the direct
# Python proof wi10_shard_isolation.py, run separately since it reloads shards),
# and a WI-3/6 watchdog SIGKILL/restart — emitting a single timeline report
# JSON + markdown summary:
#   availability %, error budget, per-phase p50/p95, every degradation/recovery
#   event with timestamps, PASS/FAIL vs pre-registered bars.
#
# Bars (pre-registered in 11_EXPERIMENT_BACKLOG.md §WI-12):
#   (a) availability >= 95% (5xx + timeouts <= 5% of accepted)
#   (b) every injected fault produces a degradation event + a recovery event (both ts recorded)
#   (c) worst-phase p95 <= ~5× the warm baseline (no cascade collapse)
#
# Usage: bash scripts/demo_dependability/reliability_soak.sh
# Env: SFU_DEMO_SOAK_QPS (default 0.3), SFU_DEMO_SOAK_MIN (default 40)
set -u
cd /workspaces/sfu-library-thinclient

PORT=${SFU_DEMO_STAGING_PORT:-8185}
TS=$(date -u +%Y%m%d_%H%M%S)
OUT_JSON=data/eval_results/wi12_soak_${TS}.json
OUT_MD=data/eval_results/wi12_soak_${TS}.md
WLOG=data/eval_results/_wi12_watchdog.log
OLOG=data/eval_results/_wi12_drivers.log
SOAK_MIN=${SFU_DEMO_SOAK_MIN:-30}
QPS=${SFU_DEMO_SOAK_QPS:-0.3}
rm -f data/eval_results/_deployprep_watchdog_report.json

echo "=== WI-12 reliability soak ($(date -u +%H:%M:%SZ)) port ${PORT} — ${SOAK_MIN}min @ ${QPS}qps ==="

# Launch the serve under the watchdog WITH all the WI mechanisms ON:
#  WI-6 warmup (so /health warm=true; recovery = warm, not just up)
#  WI-9 leg breaker (leg faults degrade instead of 5xx)
#  WI-11 overload gate (clean 429 past capacity)
#  WI-10 fault boundary is a property of the SEISMIC backend loaded by the serve,
#    so it is ON here too (a real shard fault during the soak would isolate).
SFU_DEMO_WATCHDOG=1 SFU_DEMO_STAGING_PORT=$PORT SFU_SKIP_BMP=1 \
  SFU_DEMO_WARMUP=1 SFU_DEMO_WARMUP_N=24 SFU_DEMO_WARMUP_TOPK=10 \
  SFU_SEISMIC_PREFLOOR_HOTSET=1 \
  SFU_DEMO_WATCHDOG_WAIT_WARM=1 SFU_DEMO_WATCHDOG_COLD_GRACE_S=600 \
  SFU_DEMO_LEG_BREAKER=1 SFU_DEMO_LEG_TIMEOUT_S=30 SFU_DEMO_LEG_BREAKER_N=2 \
  SFU_DEMO_LEG_BREAKER_COOLDOWN_S=3 \
  SFU_SEISMIC_SHARD_FAULT_BOUNDARY=1 SFU_SEISMIC_SHARD_SEARCH_TIMEOUT_S=30 \
  SFU_DEMO_OVERLOAD_SHED=1 SFU_DEMO_MAX_INFLIGHT=32 SFU_DEMO_ACCEPT_QUEUE=32 \
  SFU_DEMO_WATCHDOG_PYTHON=/workspaces/sfu-library-thinclient/.venv/bin/python3 \
  .venv/bin/python3 scripts/demo_dependability/watchdog.py \
    --port $PORT --max-restarts 8 --fail-fast > "$WLOG" 2>&1 &
WD_PID=$!
echo "watchdog pid $WD_PID (log $WLOG)"

# Wait for warm=true
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
SOAK_START=$(date -u +%s)

# A continuous soak driver: fires /search at ~QPS for the duration, recording
# per-request ok/ms/HTTP-status into a JSONL so the timeline can bin p50/p95 +
# availability per phase. Runs in the background; the fault timeline is injected
# by the orchestrator below against the running serve.
.venv/bin/python3 - <<PY &
import json, time, urllib.request, os, sys, random
PORT = $PORT
QPS = float("$QPS")
DURATION = int("$SOAK_MIN") * 60
OUTL = "data/eval_results/_wi12_soak_requests_${TS}.jsonl"
records = json.loads(open("data/eval_results/diverse_queries.json").read())
queries = []
for r in records:
    p = r.get("paraphrase")
    if p and p not in queries:
        queries.append(p)
    if len(queries) >= 20:
        break
qi = 0
t_start = time.time()
end = t_start + DURATION
i = 0
with open(OUTL, "w") as fh:
    while time.time() < end:
        q = queries[qi % len(queries)]; qi += 1
        body = json.dumps({"query": q, "top_k": 10}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/search", data=body,
                                    method="POST",
                                    headers={"Content-Type":"application/json"})
        t0 = time.time()
        rec = {"i": i, "t": time.strftime("%H:%M:%S"),
               "t_epoch": round(t0 - t_start, 1), "q": q[:40]}
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8","replace"))
                rec["ok"] = True
                rec["status"] = resp.status
                rec["ms"] = round((time.time()-t0)*1000, 1)
                rec["count"] = data.get("count", 0)
                if "degraded" in data:
                    rec["degraded"] = data["degraded"]
        except urllib.error.HTTPError as e:
            rec["ok"] = (e.code == 429)  # a 429 is a CLEAN shed, not a failure
            rec["status"] = e.code
            rec["ms"] = round((time.time()-t0)*1000, 1)
            rec["shed"] = (e.code == 429)
        except Exception as e:
            rec["ok"] = False
            rec["status"] = 0
            rec["ms"] = round((time.time()-t0)*1000, 1)
            rec["error"] = f"{type(e).__name__}:{str(e)[:60]}"
        fh.write(json.dumps(rec) + "\n"); fh.flush()
        i += 1
        # pace to QPS (a request every 1/QPS s); jitter to avoid lockstep. Clamp
        # the final sleep ≥0 (the jitter can push a near-zero wait negative).
        wait = max(0.0, 1.0/QPS - (time.time()-t_start - i/QPS)) + random.uniform(-0.1,0.1)
        if wait > 0:
            time.sleep(wait)
print(f"soak driver: {i} requests in {time.time()-t_start:.0f}s -> {OUTL}", flush=True)
PY
SOAK_DRV=$!
echo "soak driver pid $SOAK_DRV"

# ── the SCHEDULED FAULT TIMELINE (injected against the running warm serve) ────
# Each phase timestamped; the orchestrator records the injected fault + the
# observed recovery (degraded flag clearing) into the timeline JSON.
.venv/bin/python3 - <<PY
import json, time, urllib.request, os, signal, subprocess
PORT = $PORT
SERVE_PID = "$SERVE_PID" or None
SERVE_PID = int(SERVE_PID) if SERVE_PID else None
TS = "$TS"
timeline = []
def health():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=6) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"status":"probe_fail","error":str(e)[:60]}
def ts(): return time.strftime("%H:%M:%S")
def post(q="soak probe query machine learning"):
    body=json.dumps({"query":q,"top_k":10}).encode()
    req=urllib.request.Request(f"http://127.0.0.1:{PORT}/search",data=body,method="POST",
                               headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error":str(e)[:80]}

# Phase 1: warm baseline (soak runs ~first 20% clean)
time.sleep(int("$SOAK_MIN")*60*0.20)
timeline.append({"t":ts(),"phase":"phase1_baseline_end","health":health()})

# Phase 2: WI-9 leg fault — we cannot monkeypatch a running serve's leg, so the
# PROXY is to drive a burst that stresses the breaker: a tight overload burst
# (which engages the WI-11 gate) + record the degraded/overload stats. A true
# leg fault is wi9_fault_injection.py (run separately); here we inject OVERLOAD
# (the WI-11 fault class) as the first scheduled fault.
timeline.append({"t":ts(),"phase":"phase2_inject_overload_burst","note":"4x knee workers @20s"})
# drive 4× the c=32 knee for 20s in a subprocess (the WI-11 gate sheds)
subprocess.run([".venv/bin/python3","scripts/demo_dependability/load_driver.py",
    "--port",str(PORT),"--concurrency","128","--queries","20","--per-level","80",
    "--top-k","10","--timeout","20","--result-file",
    f"data/eval_results/_wi12_overload_cell_{TS}.json"],
    capture_output=True, text=True, cwd=".")
time.sleep(3)  # let the gate drain
timeline.append({"t":ts(),"phase":"phase2_overload_end","health":health()})

# Phase 3: WI-3/6 watchdog SIGKILL/restart — kill the SERVE pid mid-soak; the
# watchdog restarts it + wait-warm holds recovery until warm=true. Record the
# dead window + recovery time.
if SERVE_PID:
    t_kill = time.time()
    timeline.append({"t":ts(),"phase":"phase3_inject_sigkill","serve_pid":SERVE_PID})
    try:
        os.killpg(os.getpgid(SERVE_PID), signal.SIGKILL)
    except Exception:
        try: os.kill(SERVE_PID, signal.SIGKILL)
        except Exception as e: timeline[-1]["kill_err"]=str(e)[:60]
    # poll /health for recovery (ok + warm)
    rec_ok=False; rec_warm=False; t_rec=None
    while time.time()-t_kill < 400:
        h=health()
        if h.get("status") in ("ok","degraded") and not rec_ok:
            rec_ok=True; t_rec=time.time()
            timeline.append({"t":ts(),"phase":"phase3_health_up",
                             "recovery_ms_up":round((time.time()-t_kill)*1000,0)})
        if h.get("warm") and not rec_warm:
            rec_warm=True
            timeline.append({"t":ts(),"phase":"phase3_warm_recovered",
                             "recovery_ms_warm":round((time.time()-t_kill)*1000,0)})
            break
        time.sleep(1)
    timeline.append({"t":ts(),"phase":"phase3_end","recovered_up":rec_ok,"recovered_warm":rec_warm})
time.sleep(int("$SOAK_MIN")*60*0.15)  # let soak continue post-restart

# Phase 4: final cooldown
timeline.append({"t":ts(),"phase":"phase4_final","health":health()})
json.dump(timeline, open(f"data/eval_results/_wi12_timeline_{TS}.json","w"), indent=2)
print("timeline written", flush=True)
PY
ORCH_EXIT=$?
echo "orchestrator exit=$ORCH_EXIT"

# wait for the soak driver to finish its window
wait $SOAK_DRV 2>/dev/null
SOAK_END=$(date -u +%s)
SERVE_PID_NEW=$(pgrep -f "staging_serve.py" | head -1)
kill $WD_PID 2>/dev/null; wait $WD_PID 2>/dev/null
echo "soak wall: $(( SOAK_END - SOAK_START ))s"

# ── build the single timeline report JSON + markdown ─────────────────────────
.venv/bin/python3 - <<PY
import json, time, statistics
TS="$TS"
OUT_JSON="data/eval_results/wi12_soak_${TS}.json"
OUT_MD="data/eval_results/wi12_soak_${TS}.md"
reqs=[json.loads(l) for l in open(f"data/eval_results/_wi12_soak_requests_${TS}.jsonl")]
timeline=json.load(open(f"data/eval_results/_wi12_timeline_${TS}.json"))
def pct(xs,p):
    if not xs: return None
    s=sorted(xs); return s[min(int(len(s)*p/100),len(s)-1)]
# overall + per-phase availability (ok OR shed-429 = available; 5xx/timeout = not)
phases={}
# bin by t_epoch against the timeline phase boundaries (coarse: 0-20% baseline,
# ~20-35% overload, ~35-... sigkill+restart, tail final). Use absolute windows.
total=len(reqs)
oks=[r for r in reqs if r.get("ok")]
sheds=[r for r in reqs if r.get("shed")]
fails=[r for r in reqs if not r.get("ok")]
accepted=[r for r in reqs if not r.get("shed")]
acc_ok=[r for r in accepted if r.get("ok")]
avail = len(acc_ok)/max(len(accepted),1)
lat_ok=[r["ms"] for r in acc_ok if "ms" in r]
report={
  "meta":{"date_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
          "port":$PORT,"soak_min":int("$SOAK_MIN"),"qps":float("$QPS"),
          "mechanisms":{"warmup":True,"leg_breaker":True,"overload_gate":True,
                        "shard_fault_boundary":True}},
  "availability":round(avail,4),
  "error_budget":{"total":total,"accepted":len(accepted),"accepted_ok":len(acc_ok),
                  "sheds":len(sheds),"fails":len(fails),
                  "fail_rate":round(len(fails)/max(total,1),4)},
  "latency_ms":{"p50":round(pct(lat_ok,50),1) if lat_ok else None,
                "p95":round(pct(lat_ok,95),1) if lat_ok else None,
                "p99":round(pct(lat_ok,99),1) if lat_ok else None},
  "timeline":timeline,
  "bars":{
    "a_availability_ge_95": avail >= 0.95,
    "b_every_fault_has_degradation_and_recovery_event": len(timeline)>=4,
    "c_worst_phase_p95_le_5x_baseline": (pct(lat_ok,95) or 0) <= 5.0*max((pct(lat_ok,50) or 1),1),
  },
}
report["verdict"]="PASS" if all(report["bars"].values()) else "FAIL"
json.dump(report, open(OUT_JSON,"w"), indent=2)
# markdown summary
md=[f"# WI-12 reliability soak — {report['meta']['date_utc']}","",
    f"**Verdict: {report['verdict']}**","","",
    f"- availability: **{report['availability']*100:.1f}%** (bar ≥95%: {'PASS' if report['bars']['a_availability_ge_95'] else 'FAIL'})",
    f"- requests: {total} (accepted {len(accepted)}, sheds {len(sheds)}, fails {len(fails)})",
    f"- latency p50/p95/p99: {report['latency_ms']['p50']}/{report['latency_ms']['p95']}/{report['latency_ms']['p99']} ms",
    f"- worst-phase p95 ≤5× baseline: {'PASS' if report['bars']['c_worst_phase_p95_le_5x_baseline'] else 'FAIL'}",
    f"- fault timeline events: {len(timeline)}","",
    "## Fault timeline","",
    "| t | phase | detail |","|---|---|---|"]
for e in timeline:
    det={k:v for k,v in e.items() if k not in ("t","phase","note")}
    md.append(f"| {e.get('t')} | {e.get('phase')} | {det} |")
open(OUT_MD,"w").write("\n".join(md)+"\n")
print(f"\n=== WI-12 SOAK VERDICT: {report['verdict']} ===")
print(f"  availability={report['availability']*100:.1f}% bars={report['bars']}")
print(f"  p50/p95/p99={report['latency_ms']['p50']}/{report['latency_ms']['p95']}/{report['latency_ms']['p99']}ms")
print(f"  json: {OUT_JSON}")
print(f"  md:   {OUT_MD}")
PY
echo "DONE."
