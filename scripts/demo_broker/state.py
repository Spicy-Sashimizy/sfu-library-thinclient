"""Durable broker state — sqlite KV with single-flight wake lock + daily runtime
accounting. Survives a NAS reboot so the killswitch budget cap can't be reset by
bouncing the process.

The runtime accumulator is keyed by local-tz calendar day; `runtime_hours_today`
= persisted accrual for today + live delta since the current boot. That feeds the
killswitch in scheduler.decide().
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime

from scheduler import BrokerState, DropletStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


class _Rows:
    """Materialized query result standing in for a sqlite3 cursor."""

    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class LockedDB:
    """Serialize ALL access to one sqlite connection shared across FastAPI's
    request thread pool. A shared `check_same_thread=False` connection is NOT
    safe for truly concurrent calls — the 2026-08-21 saturation battery hit
    `sqlite3.InterfaceError: bad parameter or other API misuse` (a 500) the
    first time two /api/search requests raced. Rows are materialized inside
    the lock so no cursor outlives it."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = threading.RLock()

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, f):
        self._conn.row_factory = f

    def execute(self, sql: str, params=()) -> _Rows:
        with self._lock:
            return _Rows(self._conn.execute(sql, params).fetchall())

    def executescript(self, script: str) -> None:
        with self._lock:
            self._conn.executescript(script)


class StateStore:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._db = LockedDB(sqlite3.connect(path, isolation_level=None, check_same_thread=False))
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)

    def get(self, k: str, default=None):
        row = self._db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, k: str, v) -> None:
        self._db.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                         (k, json.dumps(v)))

    def acquire_wake_lock(self, ttl_s: int = 600) -> bool:
        now = time.time()
        held = self.get("wake_lock")
        if held and now - held < ttl_s:
            return False
        self.set("wake_lock", now)
        return True

    def release_wake_lock(self) -> None:
        self.set("wake_lock", 0)

    def mark_booting(self, droplet_id: str | None = None) -> None:
        self.set("status", DropletStatus.BOOTING.value)
        self.set("booted_at", time.time())
        self.set("droplet_id", droplet_id)
        self.touch_activity()

    def mark_up(self, droplet_id: str | None = None) -> None:
        self.set("status", DropletStatus.UP.value)
        if droplet_id is not None:
            self.set("droplet_id", droplet_id)
        if not self.get("booted_at"):
            self.set("booted_at", time.time())

    def mark_down(self, now: datetime) -> None:
        self._accrue_runtime(now)
        self.set("status", DropletStatus.DOWN.value)
        self.set("booted_at", 0)
        self.set("droplet_id", None)
        self.set("on_demand_session", False)

    def touch_activity(self) -> None:
        self.set("last_activity", time.time())

    def set_on_demand(self, flag: bool) -> None:
        self.set("on_demand_session", bool(flag))

    def _accrue_runtime(self, now: datetime) -> None:
        booted_at = self.get("booted_at") or 0
        if not booted_at:
            return
        day = now.date().isoformat()
        if self.get("runtime_day") != day:
            self.set("runtime_day", day)
            self.set("runtime_seconds", 0.0)
        elapsed = max(0.0, time.time() - booted_at)
        self.set("runtime_seconds", (self.get("runtime_seconds") or 0.0) + elapsed)
        month = day[:7]
        if self.get("runtime_month") != month:
            self.set("runtime_month", month)
            self.set("runtime_month_seconds", 0.0)
        self.set("runtime_month_seconds", (self.get("runtime_month_seconds") or 0.0) + elapsed)
        self.set("booted_at", time.time())

    def runtime_hours_today(self, now: datetime) -> float:
        day = now.date().isoformat()
        accrued = (self.get("runtime_seconds") or 0.0) if self.get("runtime_day") == day else 0.0
        booted_at = self.get("booted_at") or 0
        if booted_at:
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            live = max(0.0, time.time() - max(booted_at, midnight))
        else:
            live = 0.0
        return (accrued + live) / 3600.0

    def runtime_hours_month(self, now: datetime) -> float:
        """Hours the compute has run this calendar month (accrued + the live stretch)."""
        month = now.date().isoformat()[:7]
        accrued = (self.get("runtime_month_seconds") or 0.0) if self.get("runtime_month") == month else 0.0
        booted_at = self.get("booted_at") or 0
        if booted_at:
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
            live = max(0.0, time.time() - max(booted_at, month_start))
        else:
            live = 0.0
        return (accrued + live) / 3600.0

    def snapshot(self, now: datetime) -> BrokerState:
        status = DropletStatus(self.get("status", DropletStatus.DOWN.value))
        last = self.get("last_activity")
        idle = (time.time() - last) / 60.0 if (last and status == DropletStatus.UP) else None
        booted_at = self.get("booted_at") or 0
        session = (time.time() - booted_at) / 60.0 if (booted_at and status != DropletStatus.DOWN) else None
        return BrokerState(
            status=status,
            idle_minutes=idle,
            runtime_hours_today=self.runtime_hours_today(now),
            on_demand_session=bool(self.get("on_demand_session", False)),
            runtime_hours_month=self.runtime_hours_month(now),
            session_minutes=session,
        )

    def droplet_id(self) -> str | None:
        return self.get("droplet_id")
