"""Exhaustive tests for the hot/cold decision core (budget safety).

Pure-stdlib (unittest) so it runs anywhere with no installs:
    python3 -m pytest scripts/demo_broker/test_scheduler.py
    python3 scripts/demo_broker/test_scheduler.py
"""
from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace

from scheduler import Action, BrokerState, DropletStatus, budget_exhausted, decide, in_business_window


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


class TestSessionLimit(unittest.TestCase):
    def test_session_limit_stops_an_active_session(self):
        st = BrokerState(status=DropletStatus.UP, on_demand_session=True, idle_minutes=0.1,
                         session_minutes=60.0)
        d = decide(MON_1701, st, cfg(max_session_minutes=60))
        self.assertEqual(d.action, Action.DESTROY)
        self.assertIn("session limit", d.reason)

    def test_session_limit_applies_while_booting(self):
        st = BrokerState(status=DropletStatus.BOOTING, on_demand_session=True, session_minutes=61.0)
        self.assertEqual(decide(MON_1701, st, cfg(max_session_minutes=60)).action, Action.DESTROY)

    def test_under_session_limit_survives(self):
        st = BrokerState(status=DropletStatus.UP, on_demand_session=True, idle_minutes=0.1,
                         session_minutes=59.9)
        self.assertEqual(decide(MON_1701, st, cfg(max_session_minutes=60)).action, Action.NONE)

    def test_zero_session_limit_means_idle_only(self):
        st = BrokerState(status=DropletStatus.UP, on_demand_session=True, idle_minutes=0.1,
                         session_minutes=600.0)
        self.assertEqual(decide(MON_1701, st, cfg()).action, Action.NONE)
        self.assertEqual(decide(MON_1701, st, cfg(max_session_minutes=0)).action, Action.NONE)

    def test_session_limit_does_not_cut_the_hot_window(self):
        st = BrokerState(status=DropletStatus.UP, on_demand_session=True, session_minutes=600.0)
        self.assertEqual(decide(MON_10AM, st, cfg(max_session_minutes=60)).action, Action.NONE)


class TestMonthlyCap(unittest.TestCase):
    def test_month_cap_destroys_running_box(self):
        st = BrokerState(status=DropletStatus.UP, on_demand_session=True, idle_minutes=1,
                         runtime_hours_month=55.0)
        d = decide(MON_1701, st, cfg(max_runtime_hours_per_month=55.0))
        self.assertEqual(d.action, Action.DESTROY)
        self.assertIn("monthly cap", d.reason)

    def test_month_cap_applies_while_booting(self):
        st = BrokerState(status=DropletStatus.BOOTING, on_demand_session=True, runtime_hours_month=60.0)
        self.assertEqual(decide(MON_1701, st, cfg(max_runtime_hours_per_month=55.0)).action, Action.DESTROY)

    def test_under_month_cap_survives(self):
        st = BrokerState(status=DropletStatus.UP, on_demand_session=True, idle_minutes=1,
                         runtime_hours_month=54.9)
        self.assertEqual(decide(MON_1701, st, cfg(max_runtime_hours_per_month=55.0)).action, Action.NONE)

    def test_zero_month_cap_means_no_cap(self):
        st = BrokerState(status=DropletStatus.UP, on_demand_session=True, idle_minutes=1,
                         runtime_hours_month=999.0)
        self.assertEqual(decide(MON_1701, st, cfg(max_runtime_hours_per_month=0.0)).action, Action.NONE)
        self.assertEqual(decide(MON_1701, st, cfg()).action, Action.NONE)

    def test_spent_budget_blocks_business_hours_boot(self):
        st = BrokerState(status=DropletStatus.DOWN, runtime_hours_month=55.0)
        d = decide(MON_10AM, st, cfg(max_runtime_hours_per_month=55.0))
        self.assertEqual(d.action, Action.NONE)
        st = BrokerState(status=DropletStatus.DOWN, runtime_hours_today=10.0)
        self.assertEqual(decide(MON_10AM, st, cfg()).action, Action.NONE)

    def test_budget_exhausted_reasons(self):
        c = cfg(max_runtime_hours_per_month=55.0)
        self.assertEqual(budget_exhausted(BrokerState(), c), "")
        self.assertIn("monthly", budget_exhausted(BrokerState(runtime_hours_month=55.0), c))
        self.assertIn("daily", budget_exhausted(BrokerState(runtime_hours_today=10.0), c))


if __name__ == "__main__":
    unittest.main(verbosity=2)
