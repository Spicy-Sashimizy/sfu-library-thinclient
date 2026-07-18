#!/usr/bin/env python3
"""WI-3 (deployprep 2026-07-16) — staging serve wrapper for the dependability
harness. STAGING ONLY.  WI-6 (2026-07-17) adds the startup-warmup hook.

A deliberately tiny in-process HTTP server wrapping the ThinClientRetriever's
3-leg (BM25F + SPLADE + dense, RRF-fused) search — the thing the watchdog keeps
alive, the health-check probes, and the load-driver hammers. Intentionally NOT
the full MCP/Starlette server: minimal surface, stdlib only, fast cold-start,
clearly staging (it exists only so the dependability harness has a real serving
process to make dependable, on the hardware we already have, no provisioning).

Endpoints:
  GET  /health      → {"status":"ok", "legs":{bm25f,splade,dense}, "federation":...,
                        "warm":..., "pid":...}  — all three legs + federation mode +
                        WI-6 WARMUP STATE (so the watchdog waits for warm, not just up)
  POST /search      → {"query":..,"top_k":50} → {"results":[{doi,title,...}],"ms":..}

The serving process is what a stranger's demo traffic hits; the watchdog
(deployprep_watchdog.py) launches THIS as a subprocess and restarts it if it
dies/wedges. Run standalone for manual smoke; the harness runs it managed.

WI-6 startup-warmup hook (2026-07-17): the WI-3 gap was that `/health` returning
"up" in 2.4 s ≠ `/search` being warm — the seismic backend lazy-loads on first
`/search`, so the first post-restart stranger query paid the cold-mmap-fault
floor (829 dead-window errors, 0 client OK in WI-3's kill test). The hook runs
a startup warmup phase that FAULTS THE FORWARD PAGES real queries touch *before*
the serve answers strangers, then reports `warm: true` on `/health` so the
watchdog declares recovery only when a real query will be served warm. REUSES
prior art, does not reinvent:
  - F6 hotset prefault (`SFU_SEISMIC_PREFLOOR_HOTSET=1`, the existing
    `prefault_ranges` pyo3 hook over the F2 hotset sidecar) — gated env, the
    backend constructor already calls it; here it's just turned on at warmup.
  - a fixed warmup query set replayed through `search_rrf` (the Q9-was-refuted
    lever's live cousin: query-replay faults the forward data the floor touch
    does not, per F6's own caveat about first-process-cold).
The Q9 floor prefault (`SFU_SEISMIC_PREFLOOR_AT_LOAD`) is deliberately NOT relied
on — REFUTED 2026-07-10 (cold p50 ratio 1.025 ON/OFF, all bars FAIL). The hook
is staging-env-gated + OFF BY DEFAULT (no served-default flip): set
`SFU_DEMO_WARMUP=1` (plus optionally `SFU_DEMO_WARMUP_N`, `SFU_DEMO_WARMUP_TOPK`,
`SFU_SEISMIC_PREFLOOR_HOTSET=1`). Default-off = byte-identical to WI-3 behavior.

Owner constraints (2026-07-16): staging/prep only; no public deploy, no spend.
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
# WI-9 (wave 3): the leg guardian lives beside this serve wrapper (same pkg).
sys.path.insert(0, str(REPO / "scripts" / "demo_dependability"))

PORT = int(os.environ.get("SFU_DEMO_STAGING_PORT", "8159"))
TOP_K_DEFAULT = 50

# ── WI-6 warmup state (read by /health; written once by the warmup phase) ────
# warm: None = warmup disabled (WI-3 behavior, /health reports warm via the
#                 legacy "available && legs ok" check, unchanged)
#       "pending" = warmup phase requested, not yet completed (serve is UP and
#                   answers but the first /search may be cold — the watchdog
#                   MUST wait for "warm" before declaring recovery)
#       "warm"   = warmup phase completed; /search answers warm.
#       "failed" = warmup phase errored (logged); /health still reports up so
#                  the watchdog doesn't loop, but warm=false signals the cold gap.
_warmup_lock = threading.Lock()
_warmup_state = {"warm": None, "started_at": None, "finished_at": None,
                 "duration_ms": None, "queries_run": 0, "error": None}


def _warmup_enabled() -> bool:
    """ON only when explicitly env-gated. Default OFF = WI-3 behavior (the
    served path is never changed by this hook; a staging run opts in)."""
    return os.environ.get("SFU_DEMO_WARMUP", "0") == "1"


def _load_warmup_queries(n: int) -> list[str]:
    """Load a fixed warmup query set from the diverse-queries workload
    (round-robbin across subjects so the touched forward pages span shards — a
    stranger-facing working set, not one repeated query). Bounded to `n`."""
    qpath = Path(os.environ.get(
        "SFU_DEMO_WARMUP_WORKLOAD",
        str(REPO / "data" / "eval_results" / "diverse_queries.json")))
    try:
        recs = json.loads(qpath.read_text())
    except Exception as e:
        print(f"staging_serve warmup: WARN could not load workload {qpath}: {e}",
              file=sys.stderr, flush=True)
        return []
    out, seen = [], set()
    for rec in recs:
        p = rec.get("paraphrase")
        if not p or p in seen:
            continue
        seen.add(p)
        out.append(p)
        if len(out) >= n:
            break
    return out


def _run_warmup(retriever):
    """WI-6 startup warmup phase: fault the forward pages real queries touch.

    Runs a bounded warmup query set through `search_rrf` (the full 3-leg path,
    so BM25F + SEISMIC + dense + hydration all fault forward data) at a small
    top_k. Composes with F6 hotset prefault if `SFU_SEISMIC_PREFLOOR_HOTSET=1`
    (the backend ctor already ran it — that touches structural hot extents;
    these queries touch the forward data the floor touch does not). Synchronous:
    called from main() before serve_forever(), so no thread races the lazy
    seismic load (the WI-3 lazy `_seismic_backend()` is single-threaded here)."""
    n = int(os.environ.get("SFU_DEMO_WARMUP_N", "24"))
    topk = int(os.environ.get("SFU_DEMO_WARMUP_TOPK", "10"))
    queries = _load_warmup_queries(n)
    with _warmup_lock:
        _warmup_state["started_at"] = time.time()
        _warmup_state["warm"] = "pending"
    if not queries:
        with _warmup_lock:
            _warmup_state["warm"] = "failed"
            _warmup_state["error"] = "no warmup queries loaded"
        return
    t0 = time.perf_counter()
    ran = 0
    err = None
    try:
        for q in queries:
            try:
                retriever.search_rrf(q, top_k=topk, include_dense=True)
                ran += 1
            except Exception as e:
                # a single query failing doesn't abort warmup (a bad paraphrase
                # shouldn't block the serve coming up); record + continue.
                err = f"{type(e).__name__}: {str(e)[:120]}"
                print(f"staging_serve warmup: query {ran+1} failed: {err}",
                      file=sys.stderr, flush=True)
    finally:
        dur = (time.perf_counter() - t0) * 1000
        with _warmup_lock:
            _warmup_state["finished_at"] = time.time()
            _warmup_state["duration_ms"] = round(dur, 0)
            _warmup_state["queries_run"] = ran
            # warm = at least one warmup query completed (forward pages faulted).
            _warmup_state["warm"] = "warm" if ran > 0 else "failed"
            if err and ran == 0:
                _warmup_state["error"] = err
        print(f"staging_serve warmup: {ran}/{len(queries)} queries in "
              f"{dur/1000:.1f}s → warm={_warmup_state['warm']}", flush=True)


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


# ── WI-11 (wave 3): overload protection — shed, don't collapse ───────────────
# Env-gated OFF by default (= wave-2 unbounded behavior). When ON, a bounded
# in-flight semaphore + a bounded accept queue: requests beyond the queue are
# shed with a clean HTTP 429 + Retry-After (NEVER an unbounded pileup → no
# connection-reset/timeout cliff past capacity). The WI-7 warm knee (~2.9 qps)
# is the staging-default max-inflight basis; knobs derived from it.
import threading as _threading

def _overload_on() -> bool:
    return os.environ.get("SFU_DEMO_OVERLOAD_SHED", "0") == "1"

def _max_inflight() -> int:
    # default 2× the WI-7 warm-knee workers (the serve held 0% errors at c=32;
    # a 64-slot gate sheds well past that knee without a cliff). Caller-overridable.
    try:
        return int(os.environ.get("SFU_DEMO_MAX_INFLIGHT", "64"))
    except ValueError:
        return 64

def _accept_queue() -> int:
    try:
        return int(os.environ.get("SFU_DEMO_ACCEPT_QUEUE", "64"))
    except ValueError:
        return 64

def _retry_after_s() -> int:
    try:
        return int(os.environ.get("SFU_DEMO_RETRY_AFTER_S", "2"))
    except ValueError:
        return 2

# the gate: a BoundedSemaphore (in-flight slots) + a queue-size cap. A request
# that arrives when in-flight == max AND the accept queue is full is shed (429).
# A request that fits the queue waits briefly for a slot; one that would exceed
# the queue is shed immediately. Built lazily so OFF = zero overhead.
_OVERLOAD_LOCK = _threading.Lock()
_overload_gate = None  # (semaphore, queue_size, queue_cap, stats)

def _get_overload_gate():
    global _overload_gate
    if not _overload_on():
        return None
    with _OVERLOAD_LOCK:
        if _overload_gate is None:
            sem = _threading.BoundedSemaphore(_max_inflight())
            _overload_gate = {"sem": sem, "inflight": 0, "inflight_lock": _threading.Lock(),
                              "queue_cap": _accept_queue(), "stats": {"shed": 0, "accepted": 0}}
        return _overload_gate

def _overload_acquire() -> bool:
    """Try to acquire an in-flight slot. Returns True if accepted (caller must
    release), False if shed (caller returns 429). The accept queue: wait up to
    `queue_cap` other acquirers; if still no slot, shed."""
    g = _get_overload_gate()
    if g is None:
        return True  # gate OFF → always accept (wave-2 behavior)
    # non-blocking first: a free slot takes it immediately (the common warm case)
    if g["sem"].acquire(blocking=False):
        with g["inflight_lock"]:
            g["inflight"] += 1
        return True
    # no free slot → this would queue; if we're already at the queue cap, SHED
    # (don't pile up unboundedly). The shed is a clean 429, not a timeout.
    with g["inflight_lock"]:
        queued = g["inflight"]  # inflight includes those holding + queued-so-far
    if queued >= g["queue_cap"]:
        g["stats"]["shed"] += 1
        return False
    # blocking acquire (brief wait for a slot) — bounded by the queue cap above
    if g["sem"].acquire(timeout=float(os.environ.get("SFU_DEMO_QUEUE_WAIT_S", "1"))):
        with g["inflight_lock"]:
            g["inflight"] += 1
        return True
    g["stats"]["shed"] += 1
    return False

def _overload_release():
    g = _get_overload_gate()
    if g is None:
        return
    g["sem"].release()
    with g["inflight_lock"]:
        g["inflight"] -= 1
        g["stats"]["accepted"] += 1

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
        # WI-11: the overload gate is applied to /search POSTs (the expensive
        # path); /health is always answered (so the watchdog never mis-reads a
        # shed storm as a wedged serve). Acquire/release around the handler.
        if self.path.startswith("/health"):
            self._health()
        elif self.path.startswith("/verify") and \
                os.environ.get("SFU_DEMO_UPDATE_VERIFY_SEISMIC", "0") == "1":
            # WI-13: the update gate's SEISMIC-served check. /health reports
            # `legs.splade.configured="seismic"` whether or not the shards
            # actually LOADED — the retriever silently falls back to the BM25F
            # leg when a shard's mmap fails, so `status:ok` does NOT mean the
            # new index is serving. The update flow must catch a silently-
            # degraded SEISMIC (else it would commit a broken update). This
            # endpoint forces the lazy seismic load + reports it: the gate
            # asserts `seismic_loaded=True` on the new version. Gated OFF by
            # default (byte-identical to wave-3 behavior unless the updater
            # opts in). NOT a published demo endpoint — an internal gate signal.
            self._verify()
        else:
            self._json(404, {"error": "not found"})

    def _verify(self):
        """WI-13 update-gate signal: did the SEISMIC backend actually LOAD on
        this serve? Forces the lazy `_seismic_backend()` load (the same lazy-
        load /search triggers) + reports `_seismic is not None`. A broken shard
        set → the pyo3 from_mmap fails, `_seismic` stays None, the retriever
        serves BM25F only → `seismic_loaded=False` → the update gate FAILS →
        auto-rollback. `/health` alone can't catch this: it reports
        `legs.splade.configured="seismic"` whether or not the shards loaded."""
        try:
            r = _get_retriever()
            # FORCE the lazy seismic load (the method populates self._seismic).
            # A plain `r._seismic` read returns None without loading; calling
            # _seismic_backend() is what search_rrf does to trigger the mmap.
            if getattr(r, "_splade_backend", "") == "seismic":
                r._seismic_backend()  # raises if the shard set won't load
            seismic_loaded = r._seismic is not None
            self._json(200, {
                "seismic_loaded": seismic_loaded,
                "splade_backend": getattr(r, "_splade_backend", ""),
                "available": r.is_available(),
            })
        except Exception as e:
            # a load exception = the new version is broken → gate fails
            self._json(200, {"seismic_loaded": False, "load_error": str(e)[:200]})

    def do_POST(self):
        if self.path.startswith("/search"):
            # WI-11 overload gate: shed with a clean 429 + Retry-After when past
            # capacity, instead of an unbounded pileup → no connection-reset cliff.
            if not _overload_acquire():
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", str(_retry_after_s()))
                body = json.dumps({"error": "overload: try again later",
                                   "retry_after_s": _retry_after_s()}).encode()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            try:
                self._search()
            finally:
                _overload_release()
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
            with _warmup_lock:
                wu = dict(_warmup_state)
            # WI-6: when warmup is enabled, "warm" is the watchdog's real recovery
            # signal — UP alone (avail + legs ok) is NOT enough, because /search
            # lazy-loads the seismic backend on first call (the 829-dead-window
            # gap). When warmup is disabled (None), `warm` falls back to the
            # legacy availability check so WI-3 behavior + numbers reproduce.
            if wu["warm"] is None:
                warm = bool(avail)
            else:
                warm = (wu["warm"] == "warm")
            # WI-9: the leg guardian's breaker states. When the breaker is OFF
            # (SFU_DEMO_LEG_BREAKER unset), no guardian is built → status stays the
            # legacy ok/avail-only shape (wave-1 behavior). When ON, a tripped leg
            # shows its consec_fails + open flag here so the monitor sees a
            # DEGRADED serve (amber: up but a leg is down), not green and not dead.
            from leg_breaker import get_guardian
            guardian = get_guardian(r)
            degraded_legs = []
            breaker_states = None
            if guardian is not None:
                breaker_states = guardian.states_snapshot()
                degraded_legs = guardian.degraded_legs()
            # /health status: 'ok' fully up; 'degraded' (WI-9) when a leg breaker
            # is OPEN (the serve answers but from fewer legs); 'error' if the
            # index itself is unavailable (the legacy 503 path below).
            if not avail:
                status = "error"
            elif degraded_legs:
                status = "degraded"
            else:
                status = "ok"
            body = {"status": status,
                    "available": avail,
                    "warm": warm,
                    "warmup": wu,
                    "degraded_legs": degraded_legs,
                    "leg_breaker": breaker_states,
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
                    "pid": os.getpid()}
            # WI-11: overload-gate stats (when the gate is ON): in-flight + shed
            # count + accepted, so /health shows the shed rate under load. OFF →
            # absent (wave-2 health shape, byte-identical).
            g = _get_overload_gate()
            if g is not None:
                with g["inflight_lock"]:
                    body["overload"] = {"inflight": g["inflight"],
                                        "max_inflight": _max_inflight(),
                                        "accept_queue": _accept_queue(),
                                        "stats": dict(g["stats"])}
            self._json(200, body)
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
            # WI-9: when the leg breaker is ON, route through the guardian — each
            # leg runs under a per-leg timeout + circuit breaker, a failed/open leg
            # is dropped from the RRF, and the response carries a `degraded:[legs]`
            # flag the proof harness asserts on. OFF (default) = the retriever's own
            # search_rrf, byte-identical to wave-1 behavior (no `degraded` field).
            from leg_breaker import get_guardian
            guardian = get_guardian(r)
            t0 = time.perf_counter()
            degraded = None
            if guardian is not None:
                d = guardian.search_rrf_degraded(q, top_k=top_k, include_dense=True)
                results = d["results"]
                degraded = d.get("degraded")
            else:
                results = r.search_rrf(q, top_k=top_k, include_dense=True)
            ms = (time.perf_counter() - t0) * 1000
            # minimal card shape (enough for the load driver to count results)
            cards = [{"doi": x.get("doi", ""), "openalex_id": x.get("openalex_id", ""),
                      "title": (x.get("title") or "")[:80],
                      "year": x.get("publication_year")}
                     for x in results[:top_k]]
            resp = {"results": cards, "count": len(cards), "ms": round(ms, 1)}
            if degraded is not None:
                resp["degraded"] = degraded
            self._json(200, resp)
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
    # WI-6 startup warmup (optional). /health's first call is now BOTH up AND
    # (if SFU_DEMO_WARMUP=1) warm — the watchdog's "recovered" means a real
    # /search will answer warm. Default off = WI-3 behavior. The watchdog must
    # WAIT for `warm` (the watchdog helper _wait_warm) so a stranger arriving
    # the instant after restart doesn't hit the cold lazy-load.
    if _warmup_enabled():
        print(f"staging_serve: WI-6 warmup ON "
              f"(SFU_SEISMIC_PREFLOOR_HOTSET="
              f"{os.environ.get('SFU_SEISMIC_PREFLOOR_HOTSET','0')})", flush=True)
        _run_warmup(_get_retriever())
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    # WI-11: when the overload gate is ON, raise the socket listen backlog so a
    # burst of concurrent connections doesn't get refused at the socket (the
    # default request_queue_size=5 → under a c=128 burst the kernel refuses some
    # connections before the gate sees them, surfacing as ConnectionResetError
    # collapses that aren't the gate's clean 429). The backlog seats the burst;
    # the gate then sheds cleanly via 429. OFF → default backlog (unchanged).
    if _overload_on():
        srv.request_queue_size = max(_max_inflight() + _accept_queue(), 128)
    print(f"staging_serve: listening on 127.0.0.1:{PORT} (pid {os.getpid()})",
          flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
