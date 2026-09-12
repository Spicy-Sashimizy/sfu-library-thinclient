"""Read-only liveness watchdog for the OCI demo (systemd timer on the broker Micro).

Every run probes three signals and pushes to the owner's ntfy channel only on
change: the demo instance's OCI lifecycleState (control plane), the serve box's
/health (data plane), and the broker's own /health on this box. Alerts fire on
RUNNING -> anything else, on `fail_threshold` consecutive health failures, on
recovery, and once per local day as a heartbeat so a silent watchdog is itself
noticed. It NEVER issues an instance action; the only side effects are one
JSON state file and outbound notifications. `evaluate` is pure and unit-tested.

Run once by hand:  python3 watchdog.py
Install:           systemd/sfu-watchdog.service + sfu-watchdog.timer
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from notify import _post, build_payload

log = logging.getLogger("demo_broker.watchdog")

OK_STATE = "RUNNING"


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def state_path_for(cfg) -> str:
    return os.environ.get("DEMO_WATCHDOG_STATE_PATH") or os.path.join(
        os.path.dirname(cfg.state_path) or ".", "watchdog.json")


def _http_ok(url: str, timeout: float) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def probe(cfg) -> dict:
    state, err = None, ""
    try:
        from oci_client import OCIClient
        state = OCIClient(cfg).instance_state()
    except Exception as e:
        err = repr(e)[:200]
    ip = cfg.oci_instance_ip.split()[0] if cfg.oci_instance_ip else ""
    health = bool(ip) and _http_ok(f"http://{ip}:{cfg.droplet_port}/health", cfg.health_timeout_s)
    broker = _http_ok("http://127.0.0.1:8080/health", cfg.health_timeout_s)
    return {"state": state, "api_error": err, "health": health, "broker": broker}


def evaluate(prev: dict, cur: dict, *, now_local: datetime, heartbeat_hour: int,
             fail_threshold: int) -> tuple[dict, list[tuple[str, str, str]]]:
    """Pure. Return (state to persist, alerts as (title, message, ntfy priority))."""
    alerts: list[tuple[str, str, str]] = []
    nxt = dict(prev)
    nxt["last_run"] = now_local.isoformat(timespec="seconds")
    state = cur.get("state")
    summary = (f"instance={state or 'unknown'} serve_health={'ok' if cur['health'] else 'DOWN'} "
               f"broker={'ok' if cur['broker'] else 'DOWN'}")

    if not prev:
        alerts.append(("Duck Library watchdog armed", summary, "default"))

    api_fail = 0 if state else int(prev.get("api_fail", 0)) + 1
    nxt["api_fail"] = api_fail
    if api_fail == fail_threshold:
        alerts.append(("Duck Library: OCI API unreachable",
                       f"{api_fail} consecutive failures: {cur.get('api_error', '')}", "high"))
    elif api_fail == 0 and int(prev.get("api_fail", 0)) >= fail_threshold:
        alerts.append(("Duck Library: OCI API back", summary, "default"))

    if state:
        last = prev.get("last_state")
        if last and last != state:
            if state == OK_STATE:
                alerts.append(("Duck Library: instance back to RUNNING", summary, "default"))
            else:
                alerts.append((f"Duck Library: instance is {state}",
                               f"was {last}. {summary}", "urgent"))
        nxt["last_state"] = state

    for key, label in (("health", "serve /health"), ("broker", "broker /health")):
        cnt_key, flag_key = f"{key}_fail", f"{key}_alerted"
        cnt = 0 if cur[key] else int(prev.get(cnt_key, 0)) + 1
        nxt[cnt_key] = cnt
        if cnt == fail_threshold and (key == "broker" or (state or OK_STATE) == OK_STATE):
            alerts.append((f"Duck Library: {label} down",
                           f"{cnt} consecutive failures. {summary}", "high"))
            nxt[flag_key] = True
        elif cnt == 0 and prev.get(flag_key):
            alerts.append((f"Duck Library: {label} back", summary, "default"))
            nxt[flag_key] = False

    day = now_local.date().isoformat()
    if heartbeat_hour >= 0 and prev and prev.get("heartbeat_day") != day \
            and now_local.hour >= heartbeat_hour:
        alerts.append(("Duck Library watchdog heartbeat", summary, "min"))
        nxt["heartbeat_day"] = day
    elif not prev:
        nxt["heartbeat_day"] = day
    return nxt, alerts


def send(cfg, title: str, message: str, priority: str) -> None:
    if not cfg.notify_webhook:
        log.info("[no webhook] %s — %s", title, message)
        return
    body, headers = build_payload(cfg.notify_kind, title, message, cfg.notify_token)
    if "Priority" in headers:
        headers["Priority"] = priority
        headers["Tags"] = "rotating_light" if priority in ("urgent", "high") else "books"
    _post(cfg.notify_webhook, body, headers)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from config import CONFIG
    path = state_path_for(CONFIG)
    try:
        with open(path) as f:
            prev = json.load(f)
    except (FileNotFoundError, ValueError):
        prev = {}
    cur = probe(CONFIG)
    now_local = datetime.now(ZoneInfo(CONFIG.tz))
    nxt, alerts = evaluate(prev, cur, now_local=now_local,
                           heartbeat_hour=_i("DEMO_WATCHDOG_HEARTBEAT_HOUR", 9),
                           fail_threshold=_i("DEMO_WATCHDOG_FAIL_THRESHOLD", 2))
    for title, message, priority in alerts:
        log.warning("ALERT [%s] %s — %s", priority, title, message)
        send(CONFIG, title, message, priority)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(nxt, f)
    os.replace(tmp, path)
    log.info("probe %s alerts=%d state_file=%s", json.dumps(cur), len(alerts), path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
