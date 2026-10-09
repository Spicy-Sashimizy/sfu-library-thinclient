"""Tests for durable state: runtime accounting (incl. the midnight-clamp fix) and
the single-flight wake lock. Pure stdlib.

    python3 scripts/demo_broker/test_state.py
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from state import StateStore

TZ = ZoneInfo("America/Vancouver")


class TestRuntimeAccounting(unittest.TestCase):
    def setUp(self):
        self.store = StateStore(os.path.join(tempfile.mkdtemp(), "s.db"))

    def test_midnight_clamp_does_not_overcount(self):
        self.store.set("status", "up")
        self.store.set("booted_at", time.time() - 30 * 3600)
        self.store.set("runtime_day", "1999-01-01")
        self.store.set("runtime_seconds", 999999)
        h = self.store.runtime_hours_today(datetime.now(TZ))
        self.assertLess(h, 24.0)
        self.assertGreaterEqual(h, 0.0)

    def test_fresh_boot_today_counts_live(self):
        self.store.mark_booting("d1")
        self.store.mark_up("d1")
        self.store.set("booted_at", time.time() - 3600)
        self.store.set("runtime_day", datetime.now(TZ).date().isoformat())
        h = self.store.runtime_hours_today(datetime.now(TZ))
        self.assertGreater(h, 0.9)
        self.assertLess(h, 1.2)

    def test_month_accrues_across_wakes_and_days(self):
        now = datetime.now(TZ)
        self.store.set("runtime_month", now.date().isoformat()[:7])
        self.store.set("runtime_month_seconds", 3 * 3600.0)
        self.store.mark_booting("d1")
        self.store.set("booted_at", time.time() - 1800)
        self.assertAlmostEqual(self.store.runtime_hours_month(now), 3.5, delta=0.05)
        self.store.mark_down(now)
        self.assertAlmostEqual(self.store.runtime_hours_month(now), 3.5, delta=0.05)
        self.assertAlmostEqual(self.store.snapshot(now).runtime_hours_month, 3.5, delta=0.05)

    def test_session_minutes_count_from_the_wake(self):
        now = datetime.now(TZ)
        self.assertIsNone(self.store.snapshot(now).session_minutes)
        self.store.mark_booting("d1")
        self.store.set("booted_at", time.time() - 1800)
        self.assertAlmostEqual(self.store.snapshot(now).session_minutes, 30.0, delta=0.5)
        self.store.mark_up("d1")
        self.store.touch_activity()
        self.assertAlmostEqual(self.store.snapshot(now).session_minutes, 30.0, delta=0.5)
        self.store.mark_down(now)
        self.assertIsNone(self.store.snapshot(now).session_minutes)

    def test_month_rolls_over(self):
        self.store.set("runtime_month", "1999-01")
        self.store.set("runtime_month_seconds", 999999.0)
        self.assertEqual(self.store.runtime_hours_month(datetime.now(TZ)), 0.0)


class TestWakeLock(unittest.TestCase):
    def setUp(self):
        self.store = StateStore(os.path.join(tempfile.mkdtemp(), "s.db"))

    def test_single_flight(self):
        self.assertTrue(self.store.acquire_wake_lock())
        self.assertFalse(self.store.acquire_wake_lock())
        self.store.release_wake_lock()
        self.assertTrue(self.store.acquire_wake_lock())


if __name__ == "__main__":
    unittest.main(verbosity=2)
