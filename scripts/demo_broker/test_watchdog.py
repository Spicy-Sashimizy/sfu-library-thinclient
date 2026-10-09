"""Unit tests for the pure `evaluate` transition logic of watchdog.py."""
from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from watchdog import evaluate

TZ = ZoneInfo("America/Vancouver")


def _cur(state="RUNNING", health=True, broker=True, err=""):
    return {"state": state, "api_error": err, "health": health, "broker": broker}


def _ev(prev, cur, hour=12, hb=9, thr=2):
    return evaluate(prev, cur, now_local=datetime(2026, 9, 7, hour, 0, tzinfo=TZ),
                    heartbeat_hour=hb, fail_threshold=thr)


class TestEvaluate(unittest.TestCase):
    def test_first_run_arms_without_heartbeat(self):
        st, alerts = _ev({}, _cur())
        self.assertEqual([a[0] for a in alerts], ["Duck Library watchdog armed"])
        self.assertEqual(st["last_state"], "RUNNING")
        self.assertEqual(st["heartbeat_day"], "2026-09-07")

    def test_steady_state_is_silent(self):
        st, _ = _ev({}, _cur())
        st, alerts = _ev(st, _cur())
        self.assertEqual(alerts, [])

    def test_running_to_stopped_is_urgent_and_recovers(self):
        st, _ = _ev({}, _cur())
        st, alerts = _ev(st, _cur(state="STOPPED", health=False))
        self.assertEqual(len(alerts), 1)
        self.assertIn("instance is STOPPED", alerts[0][0])
        self.assertEqual(alerts[0][2], "urgent")
        st, alerts = _ev(st, _cur(state="STOPPED", health=False))
        self.assertEqual(alerts, [])
        st, alerts = _ev(st, _cur())
        self.assertEqual([a[0] for a in alerts], ["Duck Library: instance back to RUNNING"])

    def test_health_alert_needs_threshold_then_recovery(self):
        st, _ = _ev({}, _cur())
        st, alerts = _ev(st, _cur(health=False))
        self.assertEqual(alerts, [])
        st, alerts = _ev(st, _cur(health=False))
        self.assertEqual([a[0] for a in alerts], ["Duck Library: serve /health down"])
        st, alerts = _ev(st, _cur(health=False))
        self.assertEqual(alerts, [])
        st, alerts = _ev(st, _cur())
        self.assertEqual([a[0] for a in alerts], ["Duck Library: serve /health back"])

    def test_broker_down_alerts_even_when_instance_stopped(self):
        st, _ = _ev({}, _cur())
        st, _ = _ev(st, _cur(state="STOPPED", health=False, broker=False))
        st, alerts = _ev(st, _cur(state="STOPPED", health=False, broker=False))
        self.assertEqual([a[0] for a in alerts], ["Duck Library: broker /health down"])

    def test_api_failures_do_not_forget_last_state(self):
        st, _ = _ev({}, _cur())
        st, alerts = _ev(st, _cur(state=None, err="timeout"))
        self.assertEqual(alerts, [])
        st, alerts = _ev(st, _cur(state=None, err="timeout"))
        self.assertEqual([a[0] for a in alerts], ["Duck Library: OCI API unreachable"])
        self.assertEqual(st["last_state"], "RUNNING")
        st, alerts = _ev(st, _cur())
        self.assertEqual([a[0] for a in alerts], ["Duck Library: OCI API back"])

    def test_heartbeat_once_per_day_after_hour(self):
        st, _ = _ev({}, _cur())
        st["heartbeat_day"] = "2026-09-06"
        st, alerts = _ev(st, _cur(), hour=8)
        self.assertEqual(alerts, [])
        st, alerts = _ev(st, _cur(), hour=9)
        self.assertEqual([a[0] for a in alerts], ["Duck Library watchdog heartbeat"])
        self.assertEqual(alerts[0][2], "min")
        st, alerts = _ev(st, _cur(), hour=10)
        self.assertEqual(alerts, [])

    def test_heartbeat_disabled(self):
        st, _ = _ev({}, _cur())
        st["heartbeat_day"] = "2026-09-06"
        st, alerts = _ev(st, _cur(), hb=-1)
        self.assertEqual(alerts, [])


if __name__ == "__main__":
    unittest.main()
