#!/usr/bin/env bash
set -u
cd /workspaces/sfu-library-thinclient

PORT=${SFU_DEMO_STAGING_PORT:-8183}
TS=$(date -u +%Y%m%d_%H%M%S)
OUT=data/eval_results/wi11_overload_${TS}.json
WLOG=data/eval_results/_wi11_watchdog.log
rm -f data/eval_results/_deployprep_watchdog_report.json

echo "=== WI-11 overload-shed proof ($(date -u +%H:%M:%SZ)) port ${PORT} ==="
SFU_DEMO_WATCHDOG=1 SFU_DEMO_STAGING_PORT=$PORT SFU_SKIP_BMP=1 \
  SFU_DEMO_WARMUP=1 SFU_DEMO_WARMUP_N=24 SFU_DEMO_WARMUP_TOPK=10 \
  SFU_SEISMIC_PREFLOOR_HOTSET=1 \
  SFU_DEMO_WATCHDOG_WAIT_WARM=1 SFU_DEMO_WATCHDOG_COLD_GRACE_S=600 \
  SFU_DEMO_OVERLOAD_SHED=1 SFU_DEMO_MAX_INFLIGHT=16 SFU_DEMO_ACCEPT_QUEUE=16 \
  SFU_DEMO_QUEUE_WAIT_S=1 SFU_DEMO_RETRY_AFTER_S=2 \
  SFU_DEMO_WATCHDOG_PYTHON=/workspaces/sfu-library-thinclient/.venv/bin/python3 \
  .venv/bin/python3 scripts/archive/demo_dependability/watchdog.py \
    --port $PORT --max-restarts 5 --fail-fast > "$WLOG" 2>&1 &
WD_PID=$!
echo "watchdog pid $WD_PID (log $WLOG)"

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
echo "--- /health (gate config) ---"
curl -s -m 5 http://127.0.0.1:$PORT/health | .venv/bin/python3 -m json.tool 2>/dev/null | grep -E "status|overload|warm|inflight" | head

python3 - <<PY
import json, time, os, concurrent.futures as cf, urllib.request, urllib.error, statistics
PORT = $PORT
TS = "$TS"
QUERIES = []
for r in json.loads(open("data/eval_results/diverse_queries.json").read()):
    p = r.get("paraphrase")
    if p and p not in QUERIES:
        QUERIES.append(p)
    if len(QUERIES) >= 20:
        break
def one_req(q, timeout=20.0):
    body = json.dumps({"query": q, "top_k": 10}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/search", data=body,
                                 method="POST", headers={"Content-Type":"application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ms = (time.perf_counter()-t0)*1000
            return {"ok": True, "status": resp.status, "ms": ms}  # 200 = served
    except urllib.error.HTTPError as e:
        ms = (time.perf_counter()-t0)*1000
        # a 429 is a CLEAN SHED (the gate working — NOT a failure, NOT a success);
        # 5xx is a real failure (collapse-shaped).
        if e.code == 429:
            return {"ok": False, "status": 429, "ms": ms, "shed": True}
        return {"ok": False, "status": e.code, "ms": ms, "collapse": True,
                "error": f"HTTP {e.code}"}
    except Exception as e:
        ms = (time.perf_counter()-t0)*1000
        # a timeout / ConnectionResetError = a collapse (the bad case)
        return {"ok": False, "status": 0, "ms": ms, "collapse": True,
                "error": f"{type(e).__name__}:{str(e)[:40]}"}
def cell(conc, per_level=40, timeout=20.0):
    lat=[]; status_hist={}; collapse=0; ok=0; sheds=0
    t0=time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=conc) as pool:
        futs=[pool.submit(one_req, QUERIES[i%len(QUERIES)], timeout) for i in range(per_level)]
        for f in cf.as_completed(futs):
            r=f.result()
            status_hist[r["status"]] = status_hist.get(r["status"],0)+1
            if r["ok"]:
                ok+=1; lat.append(r["ms"])            # 200-served → latency sample
            elif r.get("shed"):
                sheds+=1                                 # clean 429 (not a collapse)
            elif r.get("collapse"):
                collapse+=1                              # timeout / reset / 5xx
    wall=(time.perf_counter()-t0)*1000
    lat.sort()
    def pct(p): return lat[min(int(len(lat)*p/100),len(lat)-1)] if lat else None
    return {"concurrency":conc,"total_requests":per_level,"ok":ok,"sheds":sheds,
            "collapse":collapse,"status_hist":status_hist,
            "latency_ms":{"p50":round(pct(50),1) if lat else None,
                          "p95":round(pct(95),1) if lat else None},
            "wall_ms":round(wall,0),
            "throughput_qps":round(per_level/(wall/1000),1) if wall else 0}
print("=== phase 1: pre-overload baseline c=4 ===", flush=True)
pre = cell(4)
print(f"  c=4: p50={pre['latency_ms']['p50']} p95={pre['latency_ms']['p95']} "
      f"ok={pre['ok']}/{pre['total_requests']} status={pre['status_hist']}", flush=True)
print("=== phase 2: OVERLOAD c=128 (4× the c=32 knee) ===", flush=True)
over = cell(128, per_level=200, timeout=20.0)
print(f"  c=128: p50={over['latency_ms']['p50']} p95={over['latency_ms']['p95']} "
      f"ok={over['ok']} sheds(429)={over['sheds']} collapse={over['collapse']}/{over['total_requests']} "
      f"status={over['status_hist']} qps={over['throughput_qps']}", flush=True)
print("=== phase 3: post-overload recovery c=4 ===", flush=True)
time.sleep(2)  # let the gate drain
post = cell(4)
print(f"  c=4: p50={post['latency_ms']['p50']} p95={post['latency_ms']['p95']} "
      f"ok={post['ok']}/{post['total_requests']} status={post['status_hist']}", flush=True)

# ── bar evaluation (pre-registered) ──────────────────────────────────────────
# (a) accepted-request p95 during overload ≤ ~3× the pre-overload scale (bounded
#     tail, NOT ∞ — the gate keeps accepted requests' latency bounded).
# (b) shed = CLEAN 429s: the gate's contract is that overload is shed via HTTP
#     429, NOT via a timeout/connection-reset collapse. Bar = the gate catches
#     the OVERWHELMING majority as clean 429s (sheds > collapse) AND the residual
#     collapse (socket-backlog overflow / accepted-then-slow client timeout) is a
#     small minority (≤5%) — the documented edge, not a cliff. collapse==0 is the
#     ideal; ≤5% is the honest pre-registered bar (a raised backlog gets it low but
#     the socket layer can't be made exactly 0 under an 8×-gate-depth burst).
# (c) post-overload p50 returns to within 1.5× the pre-overload baseline.
pre_p50 = pre['latency_ms']['p50'] or 1
over_p95 = over['latency_ms']['p95'] or 0
post_p50 = post['latency_ms']['p50'] or 1
collapse_frac = over['collapse'] / max(over['total_requests'], 1)
bars = {
  "a_accepted_p95_bounded": over_p95 <= 3.0 * max(pre_p50, 1),
  "b_sheds_clean_429s_collapse_minority": over['sheds'] > 0 and over['sheds'] > over['collapse']
      and collapse_frac <= 0.05,
  "c_recovery_to_baseline": post_p50 <= 1.5 * pre_p50,
}
verdict = "PASS" if all(bars.values()) else "FAIL"
result = {"meta": {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "port": PORT, "gate": {"max_inflight":16,"accept_queue":16,"on":True}},
          "pre_overload": pre, "overload": over, "post_overload": post,
          "pre_p50": pre_p50, "over_p95": over_p95, "post_p50": post_p50,
          "bars": bars, "verdict": verdict}
json.dump(result, open(f"data/eval_results/wi11_overload_${TS}.json","w"), indent=2)
print(f"\n=== WI-11 VERDICT: {verdict} ===", flush=True)
print(f"  bars: {bars}", flush=True)
print(f"  pre p50={pre_p50} over p95={over_p95} (a bounded) post p50={post_p50} (c recovery)", flush=True)
print(f"  overload: ok={over['ok']} sheds(429)={over['sheds']} collapse={over['collapse']}", flush=True)
print(f"result: data/eval_results/wi11_overload_${TS}.json", flush=True)
PY

kill $WD_PID 2>/dev/null; wait $WD_PID 2>/dev/null
echo "DONE."
