#!/usr/bin/env python3
"""deployprep WI-17c-fix — OFF-vs-ON result-cache byte-parity (host NOTE-W7-2).

The pre-registered contract bar B = "a cached response is byte-identical to a
FRESH uncached run of the same normalized query (cache OFF vs ON, same query)."
The original WI-17c measure_B only proved round-trip identity (cache hit ==
stored), NOT OFF-vs-ON. This script captures the fresh responses once (run it
against a cache-OFF serve) and the cached responses once (run it against a
cache-ON serve), writing each to a JSON file; a third invocation compares them.

Protocol (the serve restarts happen OUTSIDE this script — the operator starts
the serve with the desired SFU_RESULT_CACHE env):
  1. Start serve with SFU_RESULT_CACHE=0 (cache OFF), wait warm.
  2. Run `eval_result_cache_parity.py --mode capture --tag off --port <p>`
       → writes data/eval_results/result_cache_parity_off.json (fresh responses).
  3. Stop serve, restart with SFU_RESULT_CACHE=1 (cache ON) + warmup + primer.
  4. Run `eval_result_cache_parity.py --mode capture --tag on --port <p>`
       → writes result_cache_parity_on.json (the 2nd request each is a cache hit;
       the 1st request primes so the 2nd is the cached value).
  5. Run `eval_result_cache_parity.py --mode compare`
       → prints per-query parity + updates result_cache_ab_2026-07-18.json with
         a B2_off_vs_on section.

Parity = parsed JSON equality of the result set + meta + notes (the cache
stores and returns the EXACT dict the fresh path produced; re-serialization is
round-trip-stable for the JSON types here, so parsed equality ⇔ byte-identical).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SEED_FILE = REPO / "data" / "eval_results" / "demo_seed_queries.txt"
AB_JSON = REPO / "data" / "eval_results" / "result_cache_ab_2026-07-18.json"
DEFAULT_LIMIT = 50


def seed_queries() -> list[str]:
    out = []
    if SEED_FILE.exists():
        for line in SEED_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    # de-dup preserving order
    seen, dedup = set(), []
    for q in out:
        nq = " ".join(q.split()).casefold()
        if nq not in seen:
            seen.add(nq)
            dedup.append(q)
    return dedup


def http(method, url, body=None, timeout=120.0):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode())


def wait_warm(base, timeout=400):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            st, h = http("GET", f"{base}/health")
            if h.get("warmup") in ("warm", "failed", "disabled"):
                return h
        except Exception:
            pass
        time.sleep(2)
    return None


def capture(base: str, tag: str):
    h = wait_warm(base)
    if not h:
        print("! serve did not warm", file=sys.stderr)
        sys.exit(2)
    rc_enabled = (h.get("result_cache") or {}).get("enabled", False)
    print(f"Capturing {tag} responses (cache_enabled={rc_enabled}, "
          f"warmup={h.get('warmup')})")
    seeds = seed_queries()
    out = {"tag": tag, "cache_enabled": rc_enabled, "responses": []}
    for q in seeds:
        args = {"query": q, "limit": DEFAULT_LIMIT}
        # OFF: one request, the fresh path. ON: TWO requests — the first primes
        # (stores), the second is the cached value we compare against OFF.
        st1, d1 = http("POST", f"{base}/api/search", body=args)
        if rc_enabled:
            st2, d2 = http("POST", f"{base}/api/search", body=args)  # the cache hit
            payload = d2
        else:
            payload = d1
        out["responses"].append({"query": q, "status": st1 if not rc_enabled else st2,
                                 "data": payload})
        n = len((payload or {}).get("results", []))
        print(f"  {q[:55]!r:58} {n} results")
    path = REPO / "data" / "eval_results" / f"result_cache_parity_{tag}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"→ {path}")
    # also stash the env state for the compare step
    out["_path"] = str(path)
    return out


def compare():
    off_path = REPO / "data" / "eval_results" / "result_cache_parity_off.json"
    on_path = REPO / "data" / "eval_results" / "result_cache_parity_on.json"
    if not off_path.exists() or not on_path.exists():
        print("! need both result_cache_parity_off.json and _on.json", file=sys.stderr)
        sys.exit(2)
    off = json.loads(off_path.read_text())
    on = json.loads(on_path.read_text())
    assert off.get("cache_enabled") is False, "off capture was not cache-OFF!"
    assert on.get("cache_enabled") is True, "on capture was not cache-ON!"
    rows = []
    all_pass = True
    off_map = {r["query"]: r for r in off["responses"]}
    on_map = {r["query"]: r for r in on["responses"]}
    print("OFF-vs-ON byte-parity (cached == fresh-uncached):")
    for q in off_map:
        d_off = off_map[q]["data"]
        d_on = on_map.get(q, {}).get("data")
        equal = d_off == d_on
        # Detailed diff if mismatch (which top-level keys differ)
        diff = None
        if not equal:
            diff = {k: ("off=%r on=%r" % (d_off.get(k), d_on.get(k)))
                    for k in set(d_off) | set(d_on) if d_off.get(k) != d_on.get(k)}
        rows.append({"query": q, "parity": equal, "diff": diff})
        all_pass = all_pass and equal
        print(f"  {q[:55]!r:58} {'PASS' if equal else 'FAIL'}"
              + (f"  diff={diff}" if diff else ""))
    # Merge into the AB JSON as B2_off_vs_on
    ab = json.loads(AB_JSON.read_text())
    ab["B2_off_vs_on"] = {
        "method": "serve restart SFU_RESULT_CACHE=0 (fresh path) vs =1 (cache hit); "
                  "parsed-JSON equality of result set + meta + notes",
        "all_parity": all_pass,
        "rows": rows,
    }
    ab["bars"]["B_off_vs_on_parity"] = all_pass
    AB_JSON.write_text(json.dumps(ab, indent=2, ensure_ascii=False))
    print(f"\nAll parity: {'PASS' if all_pass else 'FAIL'} → updated {AB_JSON}")
    print(f"bar B_off_vs_on_parity = {all_pass}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["capture", "compare"], required=True)
    ap.add_argument("--tag", default="off", help="capture tag (off|on)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8099)
    a = ap.parse_args()
    if a.mode == "compare":
        compare()
    else:
        capture(f"http://{a.host}:{a.port}", a.tag)


if __name__ == "__main__":
    main()
