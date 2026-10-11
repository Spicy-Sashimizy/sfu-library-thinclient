#!/usr/bin/env python3
# CLOSED DEAD 2026-09-25 — demo-dependability WI harness for the OCI deployment that was gone on 2026-09-25 (docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md); evidence kept, bars live in source at pinned commits
"""WI-3 (deployprep 2026-07-16) — staging serve watchdog. STAGING ONLY.

A process supervisor for the staging serve wrapper (`staging_serve.py`). It
launches the serve as a subprocess, polls its `/health` endpoint with a
timeout, and restarts it on (a) process death (subprocess return) or
(b) a wedged process (health probe times out N times consecutively). It only
ever manages a process IT started (PID tracked on launch); it will NEVER
adopt or kill a process it didn't spawn — so it cannot fight the container
supervisor or a real demo's process manager. Kill-switch:
`SFU_DEMO_WATCHDOG=0` disables; staging-default-on.

Owner constraints (2026-07-16): staging/prep only; no public deploy, no spend.
Designed so the "dependability" verdict is measurable locally: kill the serve
mid-load → the watchdog detects + restarts within a measured recovery time.

This is NOT a production supervisor (no systemd/supervisord replacement) — it's
the in-container measurement harness for "does the demo survive strangers'
traffic unattended?" The recovery-time number is the deliverable.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SERVE = REPO / "scripts" / "demo_dependability" / "staging_serve.py"
DEFAULT_PORT = 8159
HEALTH_TIMEOUT = float(os.environ.get("SFU_DEMO_WATCHDOG_HEALTH_TIMEOUT", "8"))
WEDGE_RESTART_AFTER = int(os.environ.get("SFU_DEMO_WATCHDOG_WEDGE_N", "3"))
POLL_INTERVAL = float(os.environ.get("SFU_DEMO_WATCHDOG_POLL", "1.0"))
COLD_GRACE_S = float(os.environ.get("SFU_DEMO_WATCHDOG_COLD_GRACE_S", "150"))


def _staging_on() -> bool:
    """ON in staging, OFF in production unless opted in (defense-in-depth, same
    semantics as serve_query_log: a forgotten prod env does NOT start a watchdog)."""
    e = os.environ.get("SFU_DEMO_WATCHDOG", "")
    if e:
        return e.strip().lower() in ("1", "true", "yes", "on")
    profile = os.environ.get("SFU_ACTIVE_PROFILE", "default")
    env = os.environ.get("SFU_ENV", "")
    return profile.lower() != "production" and env.lower() != "production"


def health_probe(port: int, timeout: float = HEALTH_TIMEOUT) -> tuple[bool, float, str]:
    """GET /health. Returns (ok, elapsed_ms, status_text). A timeout/false
    return is the 'wedged' signal the watchdog restarts on."""
    url = f"http://127.0.0.1:{port}/health"
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            ms = (time.perf_counter() - t0) * 1000
            ok = 200 <= resp.status < 300
            return ok, ms, f"HTTP {resp.status} {body[:80]}"
    except Exception as e:
        return False, (time.perf_counter() - t0) * 1000, f"probe-fail: {type(e).__name__}: {str(e)[:80]}"


def warm_probe(port: int, timeout: float = HEALTH_TIMEOUT) -> tuple[bool, bool, float, str]:
    """WI-6: GET /health and parse `warm`. Returns (ok, warm, elapsed_ms, text).
    `ok` = HTTP 2xx (process up); `warm` = the WI-6 warmup phase completed (a
    real /search will answer warm, not cold-fault). When the serve runs without
    the warmup hook (SFU_DEMO_WARMUP unset), /health reports warm=<availability>
    so this degrades to the WI-3 up-only semantics. A watchdog that WAITS for
    warm declares recovery only when a stranger's first post-restart query
    won't hit the cold lazy-load — the gap WI-3 surfaced (829 dead-window errs)."""
    url = f"http://127.0.0.1:{port}/health"
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            ms = (time.perf_counter() - t0) * 1000
            ok = 200 <= resp.status < 300
            warm = False
            try:
                warm = bool(json.loads(body).get("warm"))
            except Exception:
                warm = ok
            return ok, warm, ms, f"HTTP {resp.status} warm={warm} {body[:60]}"
    except Exception as e:
        return False, False, (time.perf_counter() - t0) * 1000, \
            f"probe-fail: {type(e).__name__}: {str(e)[:80]}"


def _wait_warm_enabled() -> bool:
    """WI-6: when ON, the watchdog waits for /health `warm=true` (not just ok)
    before declaring recovery. Gate `SFU_DEMO_WATCHDOG_WAIT_WARM=1`. Default
    OFF preserves WI-3's up-only recovery semantics + the 2.4 s number."""
    return os.environ.get("SFU_DEMO_WATCHDOG_WAIT_WARM", "0") == "1"


def _launch(port: int, log_fh, env_overrides: dict | None = None) -> subprocess.Popen:
    env = dict(os.environ)
    env["SFU_DEMO_STAGING_PORT"] = str(port)
    if env_overrides:
        env.update(env_overrides)
    py = os.environ.get("SFU_DEMO_WATCHDOG_PYTHON",
                        str(REPO / ".venv" / "bin" / "python3"))
    p = subprocess.Popen(
        [py, str(SERVE)],
        stdout=log_fh, stderr=subprocess.STDOUT, cwd=str(REPO), env=env,
        start_new_session=True)
    return p


def _wait_healthy(port: int, deadline_s: float = 120.0) -> tuple[bool, float]:
    """Poll /health until ok (or warm, if WI-6 wait-warm is ON) or deadline.
    Returns (ok, elapsed_ms). The serve's first /health after a (re)start may
    take ~minutes (cold shard load) — the generous deadline reflects the real
    stranger-facing recovery window. With WI-6 wait-warm, recovery is declared
    only once /health reports warm=true (the startup warmup completed) — so a
    stranger's first post-restart /search answers warm, not at the cold floor."""
    wait_warm = _wait_warm_enabled()
    if wait_warm:
        deadline_s = max(deadline_s, 600.0)
    t0 = time.perf_counter()
    became_ok_at = None
    while time.perf_counter() - t0 < deadline_s:
        if wait_warm:
            ok, warm, _, _ = warm_probe(port, timeout=HEALTH_TIMEOUT)
            if ok and became_ok_at is None:
                became_ok_at = (time.perf_counter() - t0) * 1000
            if ok and warm:
                return True, (time.perf_counter() - t0) * 1000
        else:
            ok, _, _ = health_probe(port, timeout=HEALTH_TIMEOUT)
            if ok:
                return True, (time.perf_counter() - t0) * 1000
        time.sleep(0.5)
    if wait_warm and became_ok_at is not None:
        return False, became_ok_at
    return False, (time.perf_counter() - t0) * 1000


def _write_report(report: dict):
    """Persist the watchdog report (the recovery-time deliverable) so the
    induced-failure orchestration can read it after the watchdog exits."""
    path = REPO / "data" / "eval_results" / "_deployprep_watchdog_report.json"
    try:
        path.write_text(json.dumps(report, indent=2))
    except OSError:
        pass


def run_watchdog(port: int, max_restarts: int, fail_fast: bool) -> dict:
    """Launch + supervise the staging serve, restarting on death/wedge. Returns a
    report dict with restart count + recovery times (the dependability number)."""
    log_path = REPO / "data" / "eval_results" / "_deployprep_watchdog.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(log_path, "a", buffering=1)
    report = {"port": port, "restarts": [],
              "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    print(f"watchdog: launching staging_serve on port {port} (log {log_path})", flush=True)
    p = _launch(port, log_fh)
    launch_time = time.monotonic()
    wedge_streak = 0
    restart_count = 0
    def _term(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _term)
    try:
        while True:
            ret = p.poll()
            if ret is not None:
                if fail_fast and restart_count >= max_restarts:
                    print(f"watchdog: process exited (rc={ret}) — max_restarts "
                          f"{max_restarts} hit, FAIL-FAST exiting", flush=True)
                    report["died_no_restart"] = {"rc": ret, "restart_count": restart_count}
                    break
                print(f"watchdog: process DIED (rc={ret}) at "
                      f"{time.strftime('%H:%M:%S')} — restarting", flush=True)
                restart_count += 1
                p = _launch(port, log_fh)
                launch_time = time.monotonic()
                ok, wait_ms = _wait_healthy(port)
                report["restarts"].append({"cause": "process_death", "rc": ret,
                                           "recovery_ms": round(wait_ms, 0),
                                           "healthy_after_restart": ok})
                print(f"watchdog: recovery {'OK' if ok else 'TIMEOUT'} in "
                      f"{wait_ms:.0f} ms", flush=True)
                wedge_streak = 0
                if fail_fast and restart_count >= max_restarts:
                    break
                continue
            in_cold_grace = (time.monotonic() - launch_time) < COLD_GRACE_S
            ok, ms, status = health_probe(port)
            if ok:
                wedge_streak = 0
            else:
                if in_cold_grace:
                    wedge_streak = 0
                    print(f"watchdog: health not-up yet (cold grace, "
                          f"{COLD_GRACE_S - (time.monotonic() - launch_time):.0f}s "
                          f"left) ({ms:.0f}ms {status})", flush=True)
                else:
                    wedge_streak += 1
                    print(f"watchdog: health FAIL #{wedge_streak}/{WEDGE_RESTART_AFTER} "
                          f"({ms:.0f}ms {status})", flush=True)
                if wedge_streak >= WEDGE_RESTART_AFTER:
                    print(f"watchdog: WEDGED — health failed {wedge_streak}× — "
                          f"SIGKILL + restart", flush=True)
                    restart_count += 1
                    try:
                        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        p.kill()
                    try:
                        p.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    p = _launch(port, log_fh)
                    launch_time = time.monotonic()
                    ok, wait_ms = _wait_healthy(port)
                    report["restarts"].append(
                        {"cause": "wedged", "recovery_ms": round(wait_ms, 0),
                         "healthy_after_restart": ok})
                    print(f"watchdog: recovery {'OK' if ok else 'TIMEOUT'} in "
                          f"{wait_ms:.0f} ms", flush=True)
                    wedge_streak = 0
                    if fail_fast and restart_count >= max_restarts:
                        break
                    continue
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("watchdog: stopping (SIGTERM/KeyboardInterrupt) — tearing down serve",
              flush=True)
    finally:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
        log_fh.close()
        report["restart_count"] = restart_count
        report["stopped"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _write_report(report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--max-restarts", type=int, default=10,
                    help="stop after this many restarts (the harness uses a small "
                         "N to bound the induced-failure measurement)")
    ap.add_argument("--fail-fast", action="store_true",
                    help="exit after max-restarts (else supervise forever)")
    args = ap.parse_args()
    if not _staging_on():
        print("watchdog: OFF (SFU_DEMO_WATCHDOG=0 or production default)", flush=True)
        return 0
    report = run_watchdog(args.port, args.max_restarts, args.fail_fast)
    print(f"\nwatchdog report: {report}", flush=True)
    _write_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
