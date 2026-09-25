"""Exhaustive tests for the hot/cold decision core (budget safety).

Pure-stdlib (unittest) so it runs anywhere with no installs:
    python3 -m pytest scripts/archive/demo_broker/test_scheduler.py
    python3 scripts/archive/demo_broker/test_scheduler.py
"""
from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace

from scheduler import Action, BrokerState, DropletStatus, decide, in_business_window


def cfg(**over):
    base = dict(
        business_start_hour=9,
        business_end_hour=17,
        business_days=frozenset({0, 1, 2, 3, 4}),
        prewarm_minutes=5,
        idle_minutes=20,
        max_runtime_hours_per_day=10.0,
    )
    base.update(over)
    return SimpleNamespace(**base)


MON_10AM = datetime(2026, 6, 15, 10, 0)
MON_0856 = datetime(2026, 6, 15, 8, 56)
MON_0850 = datetime(2026, 6, 15, 8, 50)
MON_1701 = datetime(2026, 6, 15, 17, 1)
SAT_NOON = datetime(2026, 6, 20, 12, 0)


class TestWindow(unittest.TestCase):
    def test_weekday_midday_is_hot(self):
        self.assertTrue(in_business_window(MON_10AM, start_hour=9, end_hour=17,
                                           business_days=frozenset({0, 1, 2, 3, 4})))

    def test_prewarm_opens_early(self):
        kw = dict(start_hour=9, end_hour=17, business_days=frozenset({0, 1, 2, 3, 4}))
        self.assertTrue(in_business_window(MON_0856, prewarm_minutes=5, **kw))
        self.assertFalse(in_business_window(MON_0850, prewarm_minutes=5, **kw))

    def test_close_is_exact(self):
        kw = dict(start_hour=9, end_hour=17, business_days=frozenset({0, 1, 2, 3, 4}))
        self.assertFalse(in_business_window(MON_1701, prewarm_minutes=5, **kw))

    def test_weekend_is_cold(self):
        self.assertFalse(in_business_window(SAT_NOON, start_hour=9, end_hour=17,
                                            business_days=frozenset({0, 1, 2, 3, 4})))


class TestDecide(unittest.TestCase):
    def test_business_hours_boots_when_down(self):
        d = decide(MON_10AM, BrokerState(status=DropletStatus.DOWN), cfg())
        self.assertEqual(d.action, Action.BOOT)

    def test_prewarm_boots_when_down(self):
        d = decide(MON_0856, BrokerState(status=DropletStatus.DOWN), cfg())
        self.assertEqual(d.action, Action.BOOT)

    def test_business_hours_idle_does_not_reap(self):
        st = BrokerState(status=DropletStatus.UP, idle_minutes=60)
        d = decide(MON_10AM, st, cfg())
        self.assertEqual(d.action, Action.NONE)

    def test_after_hours_no_session_destroys(self):
        st = BrokerState(status=DropletStatus.UP, on_demand_session=False)
        d = decide(SAT_NOON, st, cfg())
        self.assertEqual(d.action, Action.DESTROY)

    def test_after_hours_active_session_survives(self):
        st = BrokerState(status=DropletStatus.UP, on_demand_session=True, idle_minutes=5)
        d = decide(SAT_NOON, st, cfg())
        self.assertEqual(d.action, Action.NONE)

    def test_after_hours_idle_reaper_destroys(self):
        st = BrokerState(status=DropletStatus.UP, on_demand_session=True, idle_minutes=25)
        d = decide(SAT_NOON, st, cfg())
        self.assertEqual(d.action, Action.DESTROY)

    def test_after_hours_down_stays_down(self):
        d = decide(SAT_NOON, BrokerState(status=DropletStatus.DOWN), cfg())
        self.assertEqual(d.action, Action.NONE)

    def test_killswitch_overrides_business_hours(self):
        st = BrokerState(status=DropletStatus.UP, idle_minutes=0, runtime_hours_today=10.5)
        d = decide(MON_10AM, st, cfg())
        self.assertEqual(d.action, Action.DESTROY)
        self.assertIn("killswitch", d.reason)

    def test_killswitch_applies_while_booting(self):
        st = BrokerState(status=DropletStatus.BOOTING, runtime_hours_today=11.0)
        d = decide(SAT_NOON, st, cfg())
        self.assertEqual(d.action, Action.DESTROY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
