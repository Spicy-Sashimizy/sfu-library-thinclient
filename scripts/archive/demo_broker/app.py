"""NAS demo broker — FastAPI gateway (always-on) in front of the on-demand DO droplet.

Responsibilities (docs/deprecated/oci_demo/HYBRID_DEMO_DEPLOYMENT.md §2A + multi-tenant ext):
  * /start?t=<invite>  per-person link -> isolated session + access info, notify owner
  * /status            JSON readiness for the waiting room to poll
  * /mcp[/...]         per-session bearer-gated reverse-proxy with rate caps,
                       visitor tool-blocking (no Zotero writes), durable event log
  * /admin/report      owner-token-gated usage + debug report
  * /health            broker self-health
  * background loop    hot/cold schedule + idle reaper + killswitch (scheduler.decide)

Account-free: each invitee is identified by an unguessable token in their link; no
sign-ups, and no OpenAlex key needed (OpenAlex is keyless — one shared server-side
polite-pool identity, protected by per-session rate caps). Engine-agnostic; runs in
DRY-RUN until DEMO_BROKER_LIVE=1 (no DO spend).

Run:  uvicorn app:app --host 0.0.0.0 --port 8088
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from architecture_page import ARCHITECTURE_HTML
from cloud import make_cloud_client
from config import CONFIG
from dial import DialError, make_dial
from notify import notify
from scheduler import Action, DropletStatus, decide
from state import StateStore
from tenants import TenantStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("demo_broker.app")

os.makedirs(os.path.dirname(CONFIG.log_path) or ".", exist_ok=True)
_jsonl = logging.getLogger("demo_broker.events")
_jsonl.setLevel(logging.INFO)
_jsonl.addHandler(logging.handlers.RotatingFileHandler(
    CONFIG.log_path, maxBytes=20_000_000, backupCount=10))


def jlog(**fields) -> None:
    fields["ts"] = time.time()
    _jsonl.info(json.dumps(fields))


app = FastAPI(title="Duck Library demo broker")
dial = make_dial(CONFIG)
store = StateStore(CONFIG.state_path)
tenants = TenantStore(CONFIG.state_path)
cloud = make_cloud_client(CONFIG)
_stop = threading.Event()

_session_ips: dict[str, set[str]] = {}


def _now() -> datetime:
    from datetime import datetime as _dt
    return _dt.now(CONFIG.zone)


def _droplet_health_ready() -> bool:
    did = store.droplet_id()
    if not did:
        return False
    ip = cloud.compute_ip(did)
    if not ip:
        return False
    try:
        with urllib.request.urlopen(f"http://{ip}:{CONFIG.droplet_port}/health",
                                    timeout=CONFIG.health_timeout_s) as r:
            return r.status == 200
    except Exception:
        return False


def _boot(reason: str, on_demand: bool) -> None:
    if not store.acquire_wake_lock():
        log.info("wake suppressed (single-flight lock held): %s", reason)
        return
    try:
        log.info("BOOT (%s, on_demand=%s)", reason, on_demand)
        did = cloud.wake()
        store.mark_booting(did)
        store.set_on_demand(on_demand)
        tenants.record(None, "droplet", "wake", detail=reason)
        jlog(event="wake", reason=reason, on_demand=on_demand)
    finally:
        store.release_wake_lock()


def _destroy(reason: str) -> None:
    if CONFIG.pin_running:
        log.warning("SLEEP suppressed by DEMO_PIN_RUNNING (%s)", reason)
        jlog(event="reap_suppressed", reason=reason)
        return
    did = store.droplet_id()
    log.info("SLEEP (%s) compute=%s", reason, did)
    cloud.sleep(did or "")
    store.mark_down(_now())
    tenants.record(None, "droplet", "reap", detail=reason)
    jlog(event="reap", reason=reason)


def _scheduler_loop() -> None:
    while not _stop.is_set():
        try:
            now = _now()
            if store.snapshot(now).status == DropletStatus.BOOTING and _droplet_health_ready():
                store.mark_up()
                log.info("droplet healthy -> UP")
            if store.snapshot(now).status == DropletStatus.UP \
                    and not _droplet_health_ready() \
                    and not cloud.compute_active(store.droplet_id() or ""):
                log.warning("stored UP but compute inactive + health down "
                            "-> reconciling to DOWN (external stop?)")
                store.mark_down(now)
                jlog(event="reconcile_down", reason="stored UP, cloud inactive")
            st = store.snapshot(now)
            d = decide(now, st, CONFIG)
            if d.action == Action.BOOT:
                _boot(d.reason, on_demand=False)
            elif d.action == Action.DESTROY:
                _destroy(d.reason)
        except Exception:
            log.exception("scheduler tick failed")
        _stop.wait(CONFIG.poll_seconds)


@app.on_event("startup")
def _startup() -> None:
    mode = "LIVE" if CONFIG.live else "DRY-RUN"
    if CONFIG.cloud == "oci":
        target, region = CONFIG.oci_instance_id or "(no OCID)", CONFIG.oci_region
    else:
        target, region = CONFIG.do_size, CONFIG.do_region
    log.info("broker starting in %s mode; cloud=%s target=%s region=%s "
             "window=%02d-%02d days=%s notify=%s",
             mode, CONFIG.cloud, target, region, CONFIG.business_start_hour,
             CONFIG.business_end_hour, sorted(CONFIG.business_days),
             CONFIG.notify_kind if CONFIG.notify_webhook else "off")
    for p in CONFIG.validate():
        log.warning("config: %s", p)
    threading.Thread(target=_scheduler_loop, daemon=True, name="scheduler").start()


@app.on_event("shutdown")
def _shutdown() -> None:
    _stop.set()


@app.get("/health")
def health(request: Request):
    if _session_from_cookie(request) is not None:
        return _proxy_web(request, "health", b"")
    st = store.snapshot(_now())
    return {"status": "ok", "mode": "live" if CONFIG.live else "dry-run",
            "droplet": st.status.value, "runtime_hours_today": round(st.runtime_hours_today, 3),
            "idle_minutes": st.idle_minutes}


@app.get("/status")
def status():
    st = store.snapshot(_now())
    return {"ready": st.status == DropletStatus.UP, "droplet": st.status.value}


def _client_ip(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or request.client.host


@app.get("/start", response_class=HTMLResponse)
def start(request: Request, t: str = ""):
    sess = tenants.open_session(t) if t else None
    if sess is None:
        tenants.record(None, "start", "denied", status=403, detail=f"bad invite token from {_client_ip(request)}")
        jlog(event="start_denied", ip=_client_ip(request))
        raise HTTPException(status_code=403, detail="invalid, revoked, or missing invite link")

    st = store.snapshot(_now())
    if st.status == DropletStatus.DOWN:
        _boot(f"on-demand /start ({sess.name})", on_demand=True)

    ip = _client_ip(request)
    known = _session_ips.setdefault(sess.session_id, set())
    is_share = bool(known) and ip not in known
    known.add(ip)

    tenants.record(sess.session_id, "start", "session_start", detail=sess.name)
    jlog(event="session_start", session=sess.session_id, name=sess.name, ip=ip)
    notify(CONFIG, "Duck Library demo started",
           f"{sess.name} connected ({_now():%Y-%m-%d %H:%M %Z}) — session {sess.session_id}")

    if is_share:
        jlog(event="link_shared", session=sess.session_id, name=sess.name,
             shared_to_ip=ip, known_ips=len(known))
        notify(CONFIG, "Duck Library link shared",
               f"{sess.name}'s invite link was forwarded — new visitor from {ip} "
               f"({len(known)} unique IPs on this session so far)")

    mcp_url = f"{CONFIG.public_base.rstrip('/')}/mcp"
    resp = HTMLResponse(_waiting_room(mcp_url, sess.bearer))
    resp.set_cookie(SESSION_COOKIE, sess.bearer, httponly=True, secure=True,
                    samesite="lax", max_age=7 * 86400)
    return resp


_active_searches: dict[str, int] = {}
_active_kind = {"gui": 0, "mcp": 0}
_active_lock = threading.Lock()
_crowd_notify_ts = [0.0]


def _search_slot_acquire(session_id: str, name: str, kind: str) -> bool:
    """One shared budget with an MCP-priority reserve (work-conserving).

    MCP draws from the full budget. GUI is capped at (max - reserved) while
    any MCP call is in flight, and borrows the full budget when MCP is idle.
    No preemption: if GUI has borrowed everything the instant an MCP call
    lands, that call 429s once and regains its reserve as searches finish.
    """
    with _active_lock:
        total = _active_kind["gui"] + _active_kind["mcp"]
        if total >= CONFIG.max_concurrent_searches:
            return False
        if kind == "gui":
            gui_cap = (CONFIG.max_concurrent_searches if _active_kind["mcp"] == 0
                       else CONFIG.max_concurrent_searches - CONFIG.mcp_reserved_slots)
            if _active_kind["gui"] >= gui_cap:
                return False
        _active_kind[kind] += 1
        _active_searches[session_id] = _active_searches.get(session_id, 0) + 1
        distinct = len(_active_searches)
        crowd = (CONFIG.concurrent_notify_at > 0
                 and distinct >= CONFIG.concurrent_notify_at
                 and time.time() - _crowd_notify_ts[0] >= CONFIG.concurrent_notify_cooldown_s)
        if crowd:
            _crowd_notify_ts[0] = time.time()
    if crowd:
        jlog(event="crowd", concurrent_sessions=distinct)
        notify(CONFIG, "Duck Library demo crowd",
               f"{distinct} people searching simultaneously (latest: {name})")
    return True


def _search_slot_release(session_id: str, kind: str) -> None:
    with _active_lock:
        _active_kind[kind] = max(0, _active_kind[kind] - 1)
        n = _active_searches.get(session_id, 0) - 1
        if n <= 0:
            _active_searches.pop(session_id, None)
        else:
            _active_searches[session_id] = n


def _busy_429(sess, kind: str):
    tenants.record(sess.session_id, kind, "blocked", status=429, detail="global concurrency cap")
    jlog(event="busy", session=sess.session_id, name=sess.name,
         cap=CONFIG.max_concurrent_searches)
    raise HTTPException(status_code=429, detail="the demo is at capacity right now; "
                        "please retry in a few seconds",
                        headers={"Retry-After": "5"})


def _rpc_info(body: bytes) -> tuple[bool, str | None]:
    """Parse the JSON-RPC body → (is_tool_call, blocked_tool_or_None).

    Only `tools/call` is a billable query. Protocol messages (initialize,
    tools/list, notifications/*) must NOT count toward the rate caps, or the MCP
    handshake every session performs would exhaust its own quota.
    """
    if not body:
        return False, None
    try:
        msg = json.loads(body)
    except Exception:
        return False, None
    is_call = False
    blocked = None
    for m in (msg if isinstance(msg, list) else [msg]):
        if isinstance(m, dict) and m.get("method") == "tools/call":
            is_call = True
            name = (m.get("params") or {}).get("name")
            if name in CONFIG.blocked_tools:
                blocked = name
    return is_call, blocked


def _proxy(request: Request, subpath: str, body: bytes) -> Response:
    auth = request.headers.get("authorization", "")
    bearer = auth[7:] if auth.startswith("Bearer ") else ""
    sess = tenants.session_by_bearer(bearer) if bearer else None
    if sess is None:
        raise HTTPException(status_code=401, detail="missing/invalid session bearer; open your /start link")

    is_call, blocked = _rpc_info(body)
    if blocked:
        tenants.bump(sess.session_id, blocked=1)
        tenants.record(sess.session_id, blocked, "blocked", status=403)
        jlog(event="blocked", session=sess.session_id, tool=blocked, name=sess.name)
        raise HTTPException(status_code=403, detail=f"tool '{blocked}' is disabled in the demo")

    if is_call:
        ok, why = tenants.rate_ok(sess.session_id, CONFIG.session_rate_window_s,
                                  CONFIG.session_rate_max, CONFIG.session_daily_max)
        if not ok:
            tenants.record(sess.session_id, "ratelimit", "blocked", status=429, detail=why)
            jlog(event="ratelimited", session=sess.session_id, why=why)
            raise HTTPException(status_code=429, detail=f"rate limit: {why}")

    if is_call and not _search_slot_acquire(sess.session_id, sess.name, "mcp"):
        _busy_429(sess, subpath)
    did = store.droplet_id()
    if store.snapshot(_now()).status != DropletStatus.UP or not did:
        if is_call:
            _search_slot_release(sess.session_id, "mcp")
        raise HTTPException(status_code=503, detail="compute warming; retry shortly (see /start)")

    ip = cloud.compute_ip(did)
    url = f"http://{ip}:{CONFIG.droplet_port}/{subpath}"
    upreq = urllib.request.Request(url, data=body or None, method=request.method)
    for h in ("content-type", "accept", "mcp-session-id"):
        if h in request.headers:
            upreq.add_header(h, request.headers[h])
    upreq.add_header("X-Demo-Session", sess.session_id)
    t0 = time.perf_counter()
    try:
        resp = urllib.request.urlopen(upreq, timeout=CONFIG.upstream_timeout_s)
    except Exception as e:
        if is_call:
            _search_slot_release(sess.session_id, "mcp")
        dt = (time.perf_counter() - t0) * 1000
        tenants.bump(sess.session_id, error=1)
        tenants.record(sess.session_id, subpath, "error", status=502, latency_ms=dt, detail=str(e)[:500])
        jlog(event="error", session=sess.session_id, detail=str(e)[:500])
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")

    code = resp.status
    ctype = resp.headers.get("content-type", "application/json")
    fwd = {h: resp.headers[h] for h in ("mcp-session-id", "cache-control") if h in resp.headers}

    def _stream():
        try:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                yield chunk
        finally:
            resp.close()
            if is_call:
                _search_slot_release(sess.session_id, "mcp")
            dt = (time.perf_counter() - t0) * 1000
            store.touch_activity()
            if is_call:
                tenants.bump(sess.session_id, query=1)
            tenants.record(sess.session_id, subpath, "query" if is_call else "mcp",
                           status=code, latency_ms=dt)
            jlog(event="query" if is_call else "mcp", session=sess.session_id,
                 name=sess.name, status=code, latency_ms=round(dt, 1))
            if is_call and CONFIG.notify_on_query:
                notify(CONFIG, "Duck Library demo query", f"{sess.name}: {subpath} ({code}, {dt:.0f}ms)")

    return StreamingResponse(_stream(), status_code=code, media_type=ctype, headers=fwd)


SESSION_COOKIE = "duck_session"

WEB_BLOCKED_SUBPATHS = {"api/unpack"}
WEB_BILLABLE_SUBPATHS = {"api/search"}


def _session_from_cookie(request: Request):
    b = request.cookies.get(SESSION_COOKIE, "")
    return tenants.session_by_bearer(b) if b else None


def _proxy_web(request: Request, subpath: str, body: bytes) -> Response:
    """Cookie-gated reverse-proxy for the browser GUI (/app static + /api).

    Same trust boundary as _proxy: nothing upstream is reachable without a live
    invite session. Static assets are not recorded (noise); /api/search counts
    as a billable query under the shared rate caps; api/unpack is blocked.
    """
    sess = _session_from_cookie(request)
    if sess is None:
        auth = request.headers.get("authorization", "")
        bearer = auth[7:] if auth.startswith("Bearer ") else ""
        sess = tenants.session_by_bearer(bearer) if bearer else None
    if sess is None:
        if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(url="/", status_code=303)
        raise HTTPException(status_code=401, detail="no session; open your /start invite link first")

    if subpath in WEB_BLOCKED_SUBPATHS:
        tenants.bump(sess.session_id, blocked=1)
        tenants.record(sess.session_id, subpath, "blocked", status=403)
        jlog(event="blocked", session=sess.session_id, tool=subpath, name=sess.name)
        raise HTTPException(status_code=403, detail="index management is disabled in the demo")

    is_query = subpath in WEB_BILLABLE_SUBPATHS
    if is_query:
        ok, why = tenants.rate_ok(sess.session_id, CONFIG.session_rate_window_s,
                                  CONFIG.session_rate_max, CONFIG.session_daily_max)
        if not ok:
            tenants.record(sess.session_id, "ratelimit", "blocked", status=429, detail=why)
            jlog(event="ratelimited", session=sess.session_id, why=why)
            raise HTTPException(status_code=429, detail=f"rate limit: {why}")

    if is_query and not _search_slot_acquire(sess.session_id, sess.name, "gui"):
        _busy_429(sess, subpath)
    did = store.droplet_id()
    if store.snapshot(_now()).status != DropletStatus.UP or not did:
        if is_query:
            _search_slot_release(sess.session_id, "gui")
        raise HTTPException(status_code=503, detail="compute warming; retry shortly (see /start)")

    ip = cloud.compute_ip(did)
    url = f"http://{ip}:{CONFIG.droplet_port}/{subpath}"
    if request.url.query:
        url += f"?{request.url.query}"
    upreq = urllib.request.Request(url, data=body or None, method=request.method)
    for h in ("content-type", "accept"):
        if h in request.headers:
            upreq.add_header(h, request.headers[h])
    upreq.add_header("X-Demo-Session", sess.session_id)
    t0 = time.perf_counter()
    try:
        resp = urllib.request.urlopen(upreq, timeout=CONFIG.upstream_timeout_s)
    except urllib.error.HTTPError as e:
        resp = e
    except Exception as e:
        if is_query:
            _search_slot_release(sess.session_id, "gui")
        dt = (time.perf_counter() - t0) * 1000
        tenants.bump(sess.session_id, error=1)
        tenants.record(sess.session_id, subpath, "error", status=502, latency_ms=dt, detail=str(e)[:500])
        jlog(event="error", session=sess.session_id, detail=str(e)[:500])
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")

    code = resp.status
    ctype = resp.headers.get("content-type", "application/octet-stream")
    fwd = {"cache-control": "private, no-store"}
    is_api = subpath.startswith("api/")

    def _stream():
        try:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                yield chunk
        finally:
            resp.close()
            if is_query:
                _search_slot_release(sess.session_id, "gui")
            if is_api:
                dt = (time.perf_counter() - t0) * 1000
                store.touch_activity()
                if is_query:
                    tenants.bump(sess.session_id, query=1)
                tenants.record(sess.session_id, subpath, "query" if is_query else "web",
                               status=code, latency_ms=dt)
                jlog(event="query" if is_query else "web", session=sess.session_id,
                     name=sess.name, path=subpath, status=code, latency_ms=round(dt, 1))
                if is_query and CONFIG.notify_on_query:
                    notify(CONFIG, "Duck Library demo query", f"{sess.name}: {subpath} ({code}, {dt:.0f}ms)")

    return StreamingResponse(_stream(), status_code=code, media_type=ctype, headers=fwd)


@app.get("/app")
@app.get("/app/{subpath:path}")
async def app_static(request: Request, subpath: str = ""):
    return _proxy_web(request, f"app/{subpath}" if subpath else "app", b"")


@app.api_route("/api/{subpath:path}", methods=["GET", "POST"])
async def api_proxy(request: Request, subpath: str):
    return _proxy_web(request, f"api/{subpath}", await request.body())


@app.api_route("/mcp", methods=["GET", "POST"])
async def mcp_root(request: Request):
    return _proxy(request, "mcp", await request.body())


@app.api_route("/mcp/{subpath:path}", methods=["GET", "POST"])
async def mcp_sub(request: Request, subpath: str):
    return _proxy(request, f"mcp/{subpath}", await request.body())


@app.get("/admin/report")
def admin_report(request: Request, since_hours: float = 24.0):
    tok = request.headers.get("x-admin-token", "") or request.query_params.get("admin", "")
    if not CONFIG.admin_token or tok != CONFIG.admin_token:
        raise HTTPException(status_code=403, detail="admin token required")
    st = store.snapshot(_now())
    rep = tenants.report(since_s=since_hours * 3600)
    rep["droplet"] = {"status": st.status.value, "runtime_hours_today": round(st.runtime_hours_today, 3),
                      "est_cost_today_usd": round(st.runtime_hours_today * 0.50, 2)}
    return rep


def _require_admin(request: Request) -> None:
    tok = request.headers.get("x-admin-token", "") or request.query_params.get("admin", "")
    if not CONFIG.admin_token or tok != CONFIG.admin_token:
        raise HTTPException(status_code=403, detail="admin token required")


@app.get("/admin/dial")
def admin_dial_status(request: Request):
    _require_admin(request)
    if dial is None:
        raise HTTPException(status_code=404, detail="dial disabled (DEMO_DIAL_BACKEND=off)")
    try:
        return dial.status().to_json()
    except DialError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/admin/dial")
def admin_dial_set(request: Request, gb: float | None = None, off: bool = False):
    """Set MemoryHigh to ?gb=<rung> (MemoryMax follows at +guard), or ?off=1."""
    _require_admin(request)
    if dial is None:
        raise HTTPException(status_code=404, detail="dial disabled (DEMO_DIAL_BACKEND=off)")
    if off == (gb is not None):
        raise HTTPException(status_code=422, detail="pass exactly one of ?gb=<rung> or ?off=1")
    try:
        st = dial.off() if off else dial.set_high(gb)
    except DialError as e:
        tenants.record(None, "dial", "error", status=400, detail=str(e)[:500])
        jlog(event="dial_error", detail=str(e)[:500])
        raise HTTPException(status_code=400, detail=str(e))
    tenants.record(None, "dial", "dial_set", detail="off" if off else f"{gb}G")
    jlog(event="dial_set", rung="off" if off else gb, status=st.to_json())
    return st.to_json()


def _waiting_room(mcp_url: str, bearer: str) -> str:
    return _WAITING_ROOM.replace("__MCP_URL__", mcp_url).replace("__BEARER__", bearer)


_STYLE = """<style>
:root{--acc:#0e7c66;--acc2:#15a385;--bg:#f6f4f1;--card:#ffffff;--ink:#1d1d1f;--mut:#6e6e73;
--line:#e4e0da;--code:#f0ede8;--ok:#1a7f37}
@media(prefers-color-scheme:dark){:root{--bg:#161514;--card:#211f1e;--ink:#f0eeec;--mut:#9d9a96;
--line:#393634;--code:#2c2a28;--ok:#4ac26b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
-webkit-font-smoothing:antialiased;min-height:100vh}
.bar{height:4px;background:linear-gradient(90deg,var(--acc),var(--acc2))}
.wrap{max-width:46rem;margin:0 auto;padding:2.5rem 1.25rem 4rem}
.brand{display:flex;align-items:baseline;gap:.6rem;margin-bottom:2rem}
.brand .mark{font-weight:800;letter-spacing:.02em;color:var(--acc);font-size:1.05rem}
.brand .div{color:var(--line)}.brand .lib{color:var(--mut);font-size:.95rem}
h1{font-size:1.7rem;line-height:1.25;margin:0 0 .5rem;font-weight:700}
.sub{color:var(--mut);margin:0 0 2rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:1.5rem;margin:1rem 0;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.prog{height:8px;border-radius:99px;background:var(--code);overflow:hidden;margin:1rem 0 .75rem}
.prog>div{height:100%;width:2%;border-radius:99px;background:linear-gradient(90deg,var(--acc),var(--acc2));
transition:width .9s ease}
.stat{display:flex;align-items:center;gap:.6rem;color:var(--mut);font-size:.95rem}
.spin{width:.9rem;height:.9rem;border:2px solid var(--line);border-top-color:var(--acc);
border-radius:50%;animation:s 1s linear infinite;flex:none}
@keyframes s{to{transform:rotate(360deg)}}
.hint{color:var(--mut);font-size:.85rem;margin-top:1rem}
.okbadge{display:inline-flex;align-items:center;gap:.45rem;color:var(--ok);font-weight:600}
.bigbtn{display:inline-block;background:linear-gradient(90deg,var(--acc),var(--acc2));color:#fff;
font:600 1.05rem system-ui;text-decoration:none;border-radius:10px;padding:.8rem 1.6rem}
.bigbtn:hover{filter:brightness(1.08)}
.field{margin:1.1rem 0 0}.field label{display:block;font-size:.8rem;font-weight:600;
text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin-bottom:.35rem}
.copyrow{display:flex;gap:.5rem;align-items:stretch}
.copyrow code{flex:1;background:var(--code);border:1px solid var(--line);border-radius:8px;
padding:.55rem .7rem;font-size:.85rem;word-break:break-all;font-family:ui-monospace,Menlo,monospace}
.copyrow button{flex:none;border:1px solid var(--line);background:var(--card);color:var(--ink);
border-radius:8px;padding:0 .9rem;font:600 .85rem system-ui;cursor:pointer}
.copyrow button:hover{border-color:var(--acc);color:var(--acc)}
ol.steps{margin:.75rem 0 0;padding-left:1.25rem}ol.steps li{margin:.4rem 0}
.foot{color:var(--mut);font-size:.85rem;margin-top:2.5rem;border-top:1px solid var(--line);
padding-top:1rem}a{color:var(--acc)}
</style>"""

_SHELL_TOP = ("<!doctype html><html lang=en><head><meta charset=utf-8>"
              "<meta name=viewport content='width=device-width,initial-scale=1'><link rel=icon href=\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#129414;</text></svg>\">"
              "<title>__TITLE__</title>" + _STYLE + "</head><body><div class=bar></div>"
              "<div class=wrap><div class=brand><span class=mark>&#129414; Duck Library</span>"
              "<span class=div>|</span><span class=lib>Semantic Search Demo</span></div>")

_WAITING_ROOM = _SHELL_TOP.replace("__TITLE__", "Duck Library demo — your access") + """
<div id=wait>
<h1>Preparing your private search session</h1>
<p class=sub>150 million scholarly works, searched semantically. The index server
wakes on demand — this usually takes about 90&nbsp;seconds.</p>
<div class=card>
<div class=stat><span class=spin id=sp></span><span id=msg>Requesting compute&hellip;</span></div>
<div class=prog><div id=pb></div></div>
<div class=stat style=font-size:.85rem><span id=eta>Estimated: under 2 minutes</span></div>
</div>
<p class=hint>Keep this tab open — your access details appear here the moment the
server is warm.</p>
</div>
<div class=card style="margin-top:1rem;border-color:var(--acc);background:color-mix(in srgb,var(--card) 92%,var(--acc))">
<b style="font-size:.9rem">&#128269; While you wait &mdash; how does this work?</b>
<p style="margin:.4rem 0 .75rem;color:var(--mut);font-size:.875rem">
150&nbsp;million documents searched via a federated 8-shard SPLADE index, BM25F lexical
retrieval, and a cross-encoder reranker &mdash; all on a single on-demand VM.
</p>
<a href="/architecture" target="_blank" style="color:var(--acc);font-weight:600;font-size:.9rem;text-decoration:none">
Explore the live architecture diagram &#8594;
</a>
</div>

<div id=ready style=display:none>
<h1><span class=okbadge>&#10003; Ready</span> — your private access</h1>
<p class=sub>Search in your browser, or connect the collection to Claude.</p>
<div class=card style=text-align:center>
<a class=bigbtn href=/app/suite.html>Open the search GUI &rarr;</a>
<p class=hint style=margin-top:.9rem>Your session travels with this browser tab &mdash; no login needed.</p>
</div>
<details style="margin:1rem 0">
<summary style="cursor:pointer;font-weight:600;padding:.25rem 0">Prefer Claude? Connect via MCP instead</summary>
<div class=card>
<div class=field><label>Step 1 &mdash; Connector URL</label>
<div class=copyrow><code id=cu>__MCP_URL__</code><button onclick=cp('cu',this)>Copy</button></div></div>
<div class=field><label>Step 3 &mdash; Header value (your access token)</label>
<div class=copyrow><code id=cb>Bearer __BEARER__</code><button onclick=cp('cb',this)>Copy</button></div></div>
</div>
<div class=card>
<b>Connect it to Claude &mdash; exact steps</b>
<ol class=steps>
<li>Open <b>claude.ai &rarr; Settings &rarr; Connectors &rarr; Add custom connector</b></li>
<li>Paste the <b>Connector URL</b> above into the URL field</li>
<li>Under <b>Authentication</b>, choose <b>None</b></li>
<li>Under <b>Additional request headers</b>, set:<br>
&nbsp;&nbsp;<b>Header name:</b> <code>Authorization</code><br>
&nbsp;&nbsp;<b>Header value:</b> copy the token above (the full <code>Bearer&nbsp;&hellip;</code> string)</li>
<li>Save the connector, start a new chat, and ask a research question</li>
</ol>
</div>
</details>
</div>
<p class=foot>This link is personal to you &mdash; please don't share it. Usage is
rate-limited and logged for the duration of the demo.</p>
<script>
var t0=Date.now(),EXPECT=95e3;
function cp(id,btn){var el=document.getElementById(id);
 (navigator.clipboard?navigator.clipboard.writeText(el.textContent):Promise.reject())
 .then(function(){btn.textContent='Copied!';setTimeout(function(){btn.textContent='Copy'},1500)})
 .catch(function(){var r=document.createRange();r.selectNode(el);
  getSelection().removeAllRanges();getSelection().addRange(r)});}
function setmsg(m){document.getElementById('msg').textContent=m}
async function poll(){
 var pct=Math.min(94,(Date.now()-t0)/EXPECT*100);
 document.getElementById('pb').style.width=pct+'%';
 try{var r=await fetch('/status');var j=await r.json();
  if(j.ready){document.getElementById('pb').style.width='100%';
   setTimeout(function(){document.getElementById('wait').style.display='none';
    document.getElementById('ready').style.display='block'},600);return;}
  if(j.droplet==='booting')setmsg('Booting the index server\\u2026');
  else if(j.droplet==='up')setmsg('Warming the search index\\u2026');
  else setmsg('Requesting compute\\u2026');
  if(Date.now()-t0>EXPECT)document.getElementById('eta').textContent=
   'Taking a little longer than usual \\u2014 hang tight';
 }catch(e){setmsg('Waiting\\u2026')}
 setTimeout(poll,3000);}
poll();
</script></div></body></html>"""

_LANDING = _SHELL_TOP.replace("__TITLE__", "Duck Library — Semantic Search Demo") + """
<h1>Semantic search across 150 million scholarly works</h1>
<p class=sub>A research demo: full-collection semantic + keyword search served as an
MCP connector for Claude and other AI clients.</p>
<div class=card><b>Access is by personal invite link.</b>
<p style=margin:.5rem 0 0>If you received an invitation, open the full link from your
email (it looks like <code>/start?t=&hellip;</code>). If the link doesn't work or you'd
like access, contact the person who invited you.</p></div>
<p class=foot>Compute scales to zero between sessions &mdash; your first visit may take
about 90 seconds to warm up. &middot; <a href="/architecture">See how the search works</a></p>
</div></body></html>"""

_NOT_FOUND = _SHELL_TOP.replace("__TITLE__", "Page not found — Duck Library demo") + """
<h1>That page doesn't exist</h1>
<p class=sub>Check that you opened your complete invite link (it ends with
<code>/start?t=&hellip;</code>).</p>
<p class=foot><a href=/>About this demo</a></p>
</div></body></html>"""


_arch_rate: dict[str, list[float]] = {}
_arch_lock = threading.Lock()
_ARCH_RATE_MAX = 5


@app.post("/arch-search")
async def arch_search(request: Request):
    """Proxy an unauthenticated search from /architecture to the serve box."""
    ip = _client_ip(request)
    now = time.time()
    with _arch_lock:
        window = [t for t in _arch_rate.get(ip, []) if now - t < 60]
        if len(window) >= _ARCH_RATE_MAX:
            raise HTTPException(status_code=429, detail="too many requests; try again shortly",
                                headers={"Retry-After": "15"})
        window.append(now)
        _arch_rate[ip] = window

    did = store.droplet_id()
    if store.snapshot(_now()).status != DropletStatus.UP or not did:
        raise HTTPException(status_code=503, detail="search backend not ready")

    body = await request.body() or b'{"query":""}'
    compute_ip = cloud.compute_ip(did)
    url = f"http://{compute_ip}:{CONFIG.droplet_port}/api/search"
    upreq = urllib.request.Request(url, data=body, method="POST")
    upreq.add_header("content-type", "application/json")
    upreq.add_header("X-Demo-Session", "arch-explore")
    t0 = time.perf_counter()
    try:
        resp = urllib.request.urlopen(upreq, timeout=CONFIG.upstream_timeout_s)
        data = resp.read()
        resp.close()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")
    dt = (time.perf_counter() - t0) * 1000
    store.touch_activity()
    jlog(event="arch_search", ip=ip, latency_ms=round(dt, 1))
    return JSONResponse(json.loads(data), headers={"cache-control": "private, no-store"})


@app.get("/architecture", response_class=HTMLResponse)
def architecture():
    """Public explainer: federated query trace visualization — no auth required."""
    return HTMLResponse(ARCHITECTURE_HTML)


@app.get("/")
def landing():
    return HTMLResponse(_LANDING)


@app.exception_handler(404)
async def html_404(request: Request, exc: HTTPException):
    if "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(_NOT_FOUND, status_code=404)
    return JSONResponse({"detail": getattr(exc, "detail", "Not Found")}, status_code=404)
