#!/usr/bin/env python3
"""WI-3 (deployprep 2026-07-16) — staging serve wrapper for the dependability
harness. STAGING ONLY.

A deliberately tiny in-process HTTP server wrapping the ThinClientRetriever's
3-leg (BM25F + SPLADE + dense, RRF-fused) search — the thing the watchdog keeps
alive, the health-check probes, and the load-driver hammers. Intentionally NOT
the full MCP/Starlette server: minimal surface, stdlib only, fast cold-start,
clearly staging (it exists only so the dependability harness has a real serving
process to make dependable, on the hardware we already have, no provisioning).

Endpoints:
  GET  /health      → {"status":"ok", "legs":{bm25f,splade,dense}, "federation":...,
                        "pid":...}  — all three legs exercised + federation mode reported
  POST /search      → {"query":..,"top_k":50} → {"results":[{doi,title,...}],"ms":..}

The serving process is what a stranger's demo traffic hits; the watchdog
(deployprep_watchdog.py) launches THIS as a subprocess and restarts it if it
dies/wedges. Run standalone for manual smoke; the harness runs it managed.

Owner constraints (2026-07-16): staging/prep only; no public deploy, no spend.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

PORT = int(os.environ.get("SFU_DEMO_STAGING_PORT", "8159"))
TOP_K_DEFAULT = 50


def _build_retriever():
    from lib.thinclient.retriever import ThinClientRetriever
    # Empty index_root → the retriever defaults to data/thinclient_index (the
    # real serving root; retriever.py:151). SFU_THINCLIENT_INDEX_ROOT overrides.
    root = os.environ.get("SFU_THINCLIENT_INDEX_ROOT", "")
    r = ThinClientRetriever(index_root=root)
    return r


_retriever = None


def _get_retriever():
    global _retriever
    if _retriever is None:
        _retriever = _build_retriever()
    return _retriever


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # quiet (the harness logs its own load results)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._health()
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.startswith("/search"):
            self._search()
        else:
            self._json(404, {"error": "not found"})

    def _health(self):
        try:
            r = _get_retriever()
            avail = r.is_available()
            # Lightweight: report leg AVAILABILITY + the federation mode in effect,
            # NOT a full 3-leg search each call (a cold 3-leg probe is ~minutes when
            # the seismic shards first fault; the load driver's /search is the real
            # exercise). The watchdog's request-timeout catches a hung process; a
            # wedged-leg would show here as `available=False` (is_available loads +
            # checks sections). The dense leg's presence is reported from config.
            dense_present = bool(getattr(r, "_dense", None))
            fed = r._seismic_federation_mode() if hasattr(r, "_seismic_federation_mode") else ""
            self._json(200, {"status": "ok" if avail else "degraded",
                             "available": avail,
                             "legs": {
                                 "bm25f": {"configured": True,
                                           "ok": bool(getattr(r, "_sections", None))},
                                 "splade": {"configured": r._splade_backend,
                                            "federation": fed},
                                 "dense": {"configured": dense_present,
                                           "ok": dense_present},
                             },
                             "federation": fed,
                             "backend": getattr(r, "_splade_backend", ""),
                             "pid": os.getpid()})
        except Exception as e:
            self._json(503, {"status": "error", "error": str(e)[:200]})

    def _search(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b""
            args = json.loads(raw) if raw else {}
        except Exception:
            return self._json(400, {"error": "invalid JSON body"})
        q = (args.get("query") or "").strip()
        if not q:
            return self._json(400, {"error": "missing 'query'"})
        top_k = max(1, min(int(args.get("top_k", TOP_K_DEFAULT)), 100))
        try:
            r = _get_retriever()
            t0 = time.perf_counter()
            results = r.search_rrf(q, top_k=top_k, include_dense=True)
            ms = (time.perf_counter() - t0) * 1000
            # minimal card shape (enough for the load driver to count results)
            cards = [{"doi": x.get("doi", ""), "openalex_id": x.get("openalex_id", ""),
                      "title": (x.get("title") or "")[:80],
                      "year": x.get("publication_year")}
                     for x in results[:top_k]]
            self._json(200, {"results": cards, "count": len(cards),
                             "ms": round(ms, 1)})
        except Exception as e:
            self._json(500, {"error": str(e)[:200]})


def main():
    # Touch the retriever once at startup so /health's first call is warm; if the
    # index can't load, exit non-zero so the watchdog sees a clean start-failure
    # (not a zombie that answers 503 forever — that's the "wedged" state to catch).
    try:
        _get_retriever()
    except Exception as e:
        print(f"staging_serve: FATAL index load failed: {e}", file=sys.stderr, flush=True)
        sys.exit(2)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"staging_serve: listening on 127.0.0.1:{PORT} (pid {os.getpid()})",
          flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
