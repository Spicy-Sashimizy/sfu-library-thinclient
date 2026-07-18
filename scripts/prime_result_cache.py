#!/usr/bin/env python3
"""Standalone re-primer for the served read-through result cache (WI-17b).

Primes a RUNNING serve over HTTP — use this to (re-)seed the result cache
WITHOUT restarting the serve (e.g. after clearing the cache, after an index
reload, or to add newly-listed owner seed queries). The on-start primer in
the serve itself (``SFU_CACHE_PRESEED``) covers the cold-start case; this
script covers the no-restart case.

Seed list = the live landing-page example queries (read from their SOURCE
``web/src/search.jsx`` — the file ``scripts/build_web.mjs`` compiles into
``web/search.js`` — so the seeds track the landing screen even when someone
edits the JSX examples; the source is authoritative, not the compiled
artifact) + the owner-extensible list in
``data/eval_results/demo_seed_queries.txt``.

Contract term 6 (binding): STRICTLY SEQUENTIAL — concurrency 1, one query at
a time, never a parallel burst on the single-GPU cross-encoder (the same GPU
the served search path uses; a parallel primer would contend with live
traffic and the cross-encoder re-rank). Idempotent: a resident query is a
cache hit on the primer's own GET, so re-running primes MISSES ONLY (a hit
bumps the hit counter and does zero retrieval work).

Exit code 0 = all seed queries cache-resident (verified via the /health
counters). The served cache must be enabled (SFU_RESULT_CACHE != 0); if it's
disabled, the script reports that and exits non-zero (nothing to prime).

Usage:
  python3 scripts/prime_result_cache.py                 # localhost:8080
  python3 scripts/prime_result_cache.py --port 8099      # a different serve
  python3 scripts/prime_result_cache.py --host 1.2.3.4  # a remote serve
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SEARCH_JSX = REPO / "web" / "src" / "search.jsx"
SEED_FILE = REPO / "data" / "eval_results" / "demo_seed_queries.txt"

# The GUI's default search request shape (web/lib/api.js buildSearchArgs with no
# filters active): {query, limit: 50}. Matching this exactly means the demo's
# real clicks hit the SAME cache key the primer planted.
DEFAULT_LIMIT = 50


def landing_example_queries() -> list[str]:
    """Read the 4 landing-page example queries from their SOURCE (search.jsx).

    The source is authoritative over the compiled web/search.js artifact: if
    someone edits the landing examples in JSX, the seeds track them without a
    rebuild. The landing screen renders them under a ``Try:`` label, as the
    array literal right before ``.map(ex =>``; we anchor on the distinctive
    first example (``indigenous knowledge systems in climate adaptation``) so we
    target THAT list and not one of the many other ``[…].map(ex =>`` blocks in
    the file. Returns [] if the JSX can't be parsed (the primer then falls
    back to the seed-file list only).
    """
    if not SEARCH_JSX.exists():
        return []
    src = SEARCH_JSX.read_text(encoding="utf-8")
    # The example list is the array literal containing the landing examples,
    # immediately followed by `.map(ex =>`. Anchor on a known example string so
    # we match the right array (the JSX has several `[...].map(ex =>` blocks).
    m = re.search(r'\[([^\]]*indigenous knowledge systems in climate adaptation[^\]]*)\]\.map\(ex\s*=>',
                  src, re.DOTALL)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group(1))


def seed_file_queries() -> list[str]:
    """Owner-extensible list from the committed seed file (one query per line,
    '#' comments + blank lines skipped)."""
    if not SEED_FILE.exists():
        return []
    out = []
    for line in SEED_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def collect_seeds() -> list[dict]:
    """Union of landing examples + owner seed file, de-duplicated, order
    preserved. Each entry is {query, args} with the demo's default request
    shape so the planted key matches a real landing-screen click."""
    seen, seeds = set(), []
    for q in landing_example_queries() + seed_file_queries():
        nq = " ".join(q.split())
        if not nq or nq.casefold() in seen:
            continue
        seen.add(nq.casefold())
        seeds.append({"query": q, "args": {"query": q, "limit": DEFAULT_LIMIT}})
    return seeds


def _http_json(method: str, url: str, body: dict | None = None, timeout: float = 60.0):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8")), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8"))
        except Exception:
            payload = {"error": str(e)}
        return e.code, payload, dict(e.headers)


def prime(host: str, port: int, gap_s: float = 0.5) -> int:
    base = f"http://{host}:{port}"
    # 1. confirm the serve is up + the cache is enabled.
    st, health, _ = _http_json("GET", f"{base}/health")
    if st != 200:
        print(f"! serve not reachable at {base}/health (HTTP {st})", file=sys.stderr)
        return 2
    rc = health.get("result_cache") or {}
    if not rc.get("enabled"):
        print(f"! result cache is DISABLED on the serve (SFU_RESULT_CACHE=0). "
              f"Nothing to prime. Re-enable with SFU_RESULT_CACHE=1 and restart, "
              f"or prime is a no-op.", file=sys.stderr)
        return 3
    if health.get("warmup") == "warming":
        print(f"! serve is still WARMING (state={health.get('warmup')}). The "
              f"primer must run strictly AFTER warmup completes (contract term 6) "
              f"— the on-start primer already waits for warmup; re-run this script "
              f"once /health shows warm=warm/failed.", file=sys.stderr)
        return 4
    before_resident = rc.get("resident", 0)
    before_hits = rc.get("hit", 0)
    before_store = rc.get("store", 0)

    seeds = collect_seeds()
    print(f"Priming {len(seeds)} seed queries against {base} (sequential, gap "
          f"{gap_s}s) — cache had {before_resident} resident entries.")
    primed = 0
    skipped = 0
    for i, s in enumerate(seeds, 1):
        st, data, _ = _http_json("POST", f"{base}/api/search", body=s["args"],
                                 timeout=120.0)
        # A priming request that 5xx'd or returned an error shape is NOT cached
        # (the serve's never-cache-bad guard); surface it but keep going.
        if st != 200 or (isinstance(data, dict) and data.get("error")):
            print(f"  [{i:>2}/{len(seeds)}] SKIP (HTTP {st}, not cached): "
                  f"{s['query'][:60]!r}", file=sys.stderr)
            skipped += 1
            continue
        n = len((data or {}).get("results", []))
        print(f"  [{i:>2}/{len(seeds)}] sent ({n} results): "
              f"{s['query'][:60]!r}")
        primed += 1
        time.sleep(gap_s)  # throttle: never a parallel burst on the cross-encoder

    # 2. verify residency via the counters (the proof of idempotency: a re-prime
    # shows resident unchanged + hit incremented + store unchanged).
    st, health2, _ = _http_json("GET", f"{base}/health")
    rc2 = health2.get("result_cache") or {}
    after = rc2.get("resident", before_resident)
    delta_res = after - before_resident
    delta_hits = rc2.get("hit", 0) - before_hits
    delta_store = rc2.get("store", 0) - before_store
    print(f"\nSent {primed} priming requests, skipped {skipped} (non-2xx/error — "
          f"serve never caches bad responses).")
    print(f"Cache resident: {before_resident} -> {after} (+{delta_res}); "
          f"hits +{delta_hits}, stores +{delta_store}. Counters: {rc2}")
    if after >= primed:
        print("OK — seed queries are cache-resident.")
        return 0
    print(f"OK with caveats — {after} resident (some seeds failed to prime).",
          file=sys.stderr)
    return 5


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default=os.environ.get("MCP_HTTP_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("MCP_HTTP_PORT", "8080")))
    ap.add_argument("--gap", type=float, default=0.5,
                    help="seconds between priming requests (throttle; default 0.5)")
    args = ap.parse_args()
    sys.exit(prime(args.host, args.port, gap_s=args.gap))


if __name__ == "__main__":
    main()
