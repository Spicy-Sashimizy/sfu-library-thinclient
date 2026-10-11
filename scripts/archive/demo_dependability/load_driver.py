#!/usr/bin/env python3
# CLOSED DEAD 2026-09-25 — demo-dependability WI harness for the OCI deployment that was gone on 2026-09-25 (docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md); evidence kept, bars live in source at pinned commits
"""WI-3 (deployprep 2026-07-16) — concurrent load-test driver for the staging
serve. STAGING ONLY.

Drives N concurrent clients (concurrency 1/4/8/16) against `staging_serve.py`
`/search` over a fixed query set, reporting per-concurrency p50/p95/mean
latency + error rate (+ the encode/traverse attribution is inside the serve's
own `ms`). Then, optionally, an induced-failure arm: a mid-load SIGKILL of the
serving process so the watchdog's recovery time is measured under realistic
strangers'-traffic conditions.

The 'dependability' verdict (the drive prompt's deliverable):
  - baseline: p50/p95/error-rate per concurrency level (does the demo hold up
    under 1/4/8/16 concurrent strangers?)
  - failure: kill the serving PID mid-load → measure (i) how many requests error
    during the dead window, (ii) the watchdog's recovery time (from the
    watchdog's report — the probe-fail→restart→healthy cycle).

Owner constraints (2026-07-16): staging/prep only; runs against 127.0.0.1 only;
no public deploy, no spend.
"""
import argparse
import concurrent.futures as cf
import json
import os
import statistics
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _post_search(port: int, query: str, top_k: int, timeout: float) -> dict:
    """One client request. Returns {ok, ms, count, error}."""
    url = f"http://127.0.0.1:{port}/search"
    body = json.dumps({"query": query, "top_k": top_k}).encode()
    t0 = time.perf_counter()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
            ms = (time.perf_counter() - t0) * 1000
            return {"ok": True, "ms": ms, "count": data.get("count", 0)}
    except Exception as e:
        return {"ok": False, "ms": (time.perf_counter() - t0) * 1000,
                "count": 0, "error": f"{type(e).__name__}: {str(e)[:60]}"}


def percentile(data, p):
    if not data:
        return None
    s = sorted(data)
    return s[min(int(len(s) * p / 100), len(s) - 1)]


def load_cell(port: int, concurrency: int, queries: list[str], top_k: int,
              total_requests: int, timeout: float) -> dict:
    """Run `total_requests` requests at `concurrency` concurrency. Each client
    round-robins the query set so the working set is shared (strangers' traffic
    shape), not all the same query."""
    latencies = []
    errors = 0
    completed = 0
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = []
        for i in range(total_requests):
            q = queries[i % len(queries)]
            futs.append(pool.submit(_post_search, port, q, top_k, timeout))
        for f in cf.as_completed(futs):
            r = f.result()
            completed += 1
            if r["ok"]:
                latencies.append(r["ms"])
            else:
                errors += 1
    wall = (time.perf_counter() - t0) * 1000
    ok_lat = latencies
    return {
        "concurrency": concurrency,
        "total_requests": total_requests,
        "completed": completed,
        "errors": errors,
        "error_rate": round(errors / completed, 4) if completed else 1.0,
        "latency_ms": {
            "p50": round(percentile(ok_lat, 50), 1) if ok_lat else None,
            "p95": round(percentile(ok_lat, 95), 1) if ok_lat else None,
            "mean": round(statistics.mean(ok_lat), 1) if ok_lat else None,
            "min": round(min(ok_lat), 1) if ok_lat else None,
            "max": round(max(ok_lat), 1) if ok_lat else None,
        },
        "wall_ms": round(wall, 0),
        "throughput_qps": round(completed / (wall / 1000), 1) if wall else 0,
    }


def induce_failure(port: int, queries: list[str], top_k: int, concurrency: int,
                   timeout: float, kill_pid: int | None, kill_after_s: float,
                   duration_s: float) -> dict:
    """Run a load for `duration_s` at `concurrency`; at `kill_after_s` SIGKILL the
    serving PID (or its pgid) and KEEP firing → count the dead-window errors until
    the watchdog's restart brings the serve back. The FIRST successful response
    after the kill = recovery point (client-visible).
    Returns the failure-arm cell. The watchdog's own recovery (death→restart→
    healthy-probe) is read from its `_deployprep_watchdog_report.json` separately."""
    import signal
    latencies = []
    errors = 0
    dead_window_errors = 0
    recovered_at = None
    killed_at = None
    killed = False
    t_start = time.perf_counter()
    end = t_start + duration_s
    kill_deadline = t_start + kill_after_s
    qi = 0

    with cf.ThreadPoolExecutor(max_workers=concurrency) as pool:
        in_flight = set()
        for _ in range(concurrency):
            in_flight.add(pool.submit(_post_search, port, queries[qi % len(queries)],
                                      top_k, timeout)); qi += 1
        while True:
            now = time.perf_counter()
            if not killed and now >= kill_deadline and kill_pid is not None:
                try:
                    os.killpg(os.getpgid(kill_pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    try:
                        os.kill(kill_pid, signal.SIGKILL)
                    except Exception:
                        pass
                killed = True
                killed_at = now
            done_now = {f for f in in_flight if f.done()}
            in_flight -= done_now
            for f in done_now:
                r = f.result()
                if r["ok"]:
                    latencies.append(r["ms"])
                    if killed and recovered_at is None:
                        recovered_at = time.perf_counter()
                else:
                    errors += 1
                    if killed and recovered_at is None:
                        dead_window_errors += 1
            while len(in_flight) < concurrency and time.perf_counter() < end:
                in_flight.add(pool.submit(_post_search, port, queries[qi % len(queries)],
                                          top_k, timeout)); qi += 1
            if time.perf_counter() >= end and not in_flight:
                break
            if not done_now:
                time.sleep(0.01)

    recovery_ms = round((recovered_at - killed_at) * 1000, 0) if (killed and recovered_at and killed_at) else None
    return {
        "concurrency": concurrency,
        "duration_s": duration_s,
        "kill_at_s": kill_after_s,
        "killed_pid": kill_pid,
        "killed": killed,
        "total_ok": len(latencies),
        "total_errors": errors,
        "dead_window_errors": dead_window_errors,
        "first_client_recovery_ms_after_kill": recovery_ms,
        "latency_ms_ok": {
            "p50": round(percentile(latencies, 50), 1) if latencies else None,
            "p95": round(percentile(latencies, 95), 1) if latencies else None,
            "n": len(latencies),
        },
    }


def load_queries(n, qpath):
    records = json.loads(qpath.read_text())
    out, seen = [], set()
    for rec in records:
        p = rec["paraphrase"]
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
        if len(out) >= n:
            break
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8159)
    ap.add_argument("--concurrency", default="1,4,8,16",
                    help="comma-separated concurrency levels")
    ap.add_argument("--queries", type=int, default=20,
                    help="query set size (round-robinned)")
    ap.add_argument("--per-level", type=int, default=40,
                    help="total requests per concurrency level")
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--query-workload",
                    default=str(REPO / "data" / "eval_results" / "diverse_queries.json"))
    ap.add_argument("--result-file", default=None)
    ap.add_argument("--induce-failure", action="store_true",
                    help="run the induced-failure arm (kill serve mid-load; "
                         "requires --serve-pid and a running watchdog)")
    ap.add_argument("--serve-pid", type=int, default=None,
                    help="the staging_serve PID to SIGKILL (induce-failure arm)")
    ap.add_argument("--kill-after-s", type=float, default=3.0)
    ap.add_argument("--duration-s", type=float, default=20.0)
    args = ap.parse_args()

    queries = load_queries(args.queries, Path(args.query_workload))
    print(f"loaded {len(queries)} queries; targeting 127.0.0.1:{args.port}", flush=True)

    result = {"meta": {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "port": args.port, "queries": len(queries), "top_k": args.top_k},
              "baseline": [], "induced_failure": None}
    if not args.induce_failure:
        for c in [int(x) for x in args.concurrency.split(",")]:
            print(f"=== baseline concurrency={c} ({args.per_level} requests) ===", flush=True)
            cell = load_cell(args.port, c, queries, args.top_k, args.per_level, args.timeout)
            result["baseline"].append(cell)
            print(f"  p50/p95: {cell['latency_ms']['p50']}/{cell['latency_ms']['p95']} ms "
                  f"errors {cell['errors']}/{cell['completed']} ({cell['error_rate']:.1%}) "
                  f"qps {cell['throughput_qps']}", flush=True)
    else:
        print(f"=== induced failure: kill serve pid {args.serve_pid} after "
              f"{args.kill_after_s}s, run {args.duration_s}s ===", flush=True)
        cell = induce_failure(args.port, queries, args.top_k, 8, args.timeout,
                              args.serve_pid, args.kill_after_s, args.duration_s)
        result["induced_failure"] = cell
        print(f"  killed={cell['killed']} dead_window_errors={cell['dead_window_errors']} "
              f"first_client_recovery_ms={cell['first_client_recovery_ms_after_kill']}", flush=True)

    rf = (Path(args.result_file) if args.result_file else
          REPO / "data" / "eval_results" /
          f"wi3_load_{'failure' if args.induce_failure else 'baseline'}_"
          f"{time.strftime('%Y%m%d_%H%M%S')}.json")
    rf.write_text(json.dumps(result, indent=2))
    print(f"\nresult: {rf}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
