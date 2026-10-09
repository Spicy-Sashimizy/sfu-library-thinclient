"""End-to-end broker wiring test (dry-run, no DO spend) via FastAPI TestClient.

Requires fastapi + httpx (present in the project venv):
    .venv/bin/python3 -m pytest scripts/demo_broker/test_app.py
Skips cleanly if fastapi/httpx are absent (e.g. system python).
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest

_HAVE = all(importlib.util.find_spec(m) for m in ("fastapi", "httpx"))


@unittest.skipUnless(_HAVE, "needs fastapi+httpx (project venv)")
class TestBrokerWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["DEMO_STATE_PATH"] = os.path.join(tempfile.mkdtemp(), "state.db")
        os.environ["DEMO_LOG_PATH"] = os.path.join(tempfile.mkdtemp(), "b.jsonl")
        os.environ["DEMO_ADMIN_TOKEN"] = "adm"
        os.environ["DEMO_MAX_RUNTIME_HOURS_PER_MONTH"] = "55"
        from fastapi.testclient import TestClient
        import app
        cls.app = app
        cls.c = TestClient(app.app)

    def test_zz_budget_refuses_wake(self):
        app, c = self.app, self.c
        now = app._now()
        tok = app.tenants.mint_invite("Budget Test")
        app.store.mark_down(now)
        app.store.set("runtime_month", now.date().isoformat()[:7])
        app.store.set("runtime_month_seconds", 56 * 3600.0)
        try:
            r = c.get("/start", params={"t": tok})
            self.assertEqual(r.status_code, 503)
            self.assertEqual(app.store.snapshot(now).status.value, "down")
            self.assertEqual(c.get("/health").json()["max_runtime_hours_per_month"], 55.0)
        finally:
            app.store.set("runtime_month_seconds", 0.0)
        self.assertEqual(c.get("/start", params={"t": tok}).status_code, 200)
        self.assertEqual(app.store.snapshot(now).status.value, "booting")
        app.store.mark_down(now)
        app.store.set("runtime_month_seconds", 0.0)

    def test_full_flow(self):
        app, c = self.app, self.c
        tok = app.tenants.mint_invite("Prof Test")

        self.assertEqual(c.get("/start", params={"t": "inv_bad"}).status_code, 403)
        r = c.get("/start", params={"t": tok})
        self.assertEqual(r.status_code, 200)
        self.assertIn("/mcp", r.text)

        bearer = app.tenants.open_session(tok).bearer
        self.assertEqual(c.post("/mcp", content=b"{}").status_code, 401)

        blk = c.post("/mcp", headers={"Authorization": f"Bearer {bearer}"},
                     content=b'{"method":"tools/call","params":{"name":"save_to_zotero"}}')
        self.assertEqual(blk.status_code, 403)

        ok = c.post("/mcp", headers={"Authorization": f"Bearer {bearer}"},
                    content=b'{"method":"tools/call","params":{"name":"search"}}')
        self.assertEqual(ok.status_code, 503)

        self.assertEqual(c.get("/admin/report").status_code, 403)
        rep = c.get("/admin/report", headers={"x-admin-token": "adm"}).json()
        self.assertEqual(rep["sessions"], 1)
        self.assertEqual(rep["events_by_kind"].get("blocked"), 1)
        self.assertEqual(rep["events_by_kind"].get("session_start"), 1)

    def test_web_gui_gating(self):
        app = self.app
        from fastapi.testclient import TestClient
        c = TestClient(app.app, base_url="https://testserver")
        r = c.get("/app/suite.html", headers={"accept": "text/html"}, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/"))
        self.assertEqual(c.post("/api/search", content=b"{}").status_code, 401)
        tok = app.tenants.mint_invite("GUI Test")
        r = c.get("/start", params={"t": tok})
        self.assertIn(app.SESSION_COOKIE + "=", r.headers.get("set-cookie", ""))
        self.assertIn("/app/suite.html", r.text)
        self.assertEqual(c.post("/api/unpack", content=b"{}").status_code, 403)
        self.assertEqual(c.post("/api/search", content=b"{}").status_code, 503)
        self.assertEqual(c.get("/app/suite.html").status_code, 503)
        self.assertIn("runtime_hours_today", TestClient(app.app).get("/health").json())

    def test_global_concurrency_switch(self):
        app = self.app
        from fastapi.testclient import TestClient
        c = TestClient(app.app, base_url="https://testserver")
        tok = app.tenants.mint_invite("Crowd Test")
        c.get("/start", params={"t": tok})
        bearer = app.tenants.open_session(tok).bearer
        old = app.CONFIG.max_concurrent_searches
        object.__setattr__(app.CONFIG, "max_concurrent_searches", 0)
        try:
            r = c.post("/api/search", content=b'{"query":"x"}')
            self.assertEqual(r.status_code, 429)
            self.assertEqual(r.headers.get("retry-after"), "5")
            r = c.post("/mcp", headers={"Authorization": f"Bearer {bearer}"},
                       content=b'{"method":"tools/call","params":{"name":"search"}}')
            self.assertEqual(r.status_code, 429)
            r = c.post("/mcp", headers={"Authorization": f"Bearer {bearer}"},
                       content=b'{"method":"tools/list"}')
            self.assertEqual(r.status_code, 503)
        finally:
            object.__setattr__(app.CONFIG, "max_concurrent_searches", old)
        self.assertEqual(app._active_searches, {})

    def test_mcp_priority_reserve(self):
        app = self.app
        acquire, release = app._search_slot_acquire, app._search_slot_release
        self.assertEqual(app._active_kind, {"gui": 0, "mcp": 0})
        try:
            for i in range(6):
                self.assertTrue(acquire(f"g{i}", "g", "gui"), i)
            self.assertFalse(acquire("g6", "g", "gui"))
            self.assertFalse(acquire("m0", "m", "mcp"))
            for i in range(6):
                release(f"g{i}", "gui")
            self.assertTrue(acquire("m0", "m", "mcp"))
            for i in range(4):
                self.assertTrue(acquire(f"g{i}", "g", "gui"), i)
            self.assertFalse(acquire("g4", "g", "gui"))
            self.assertTrue(acquire("m1", "m", "mcp"))
            self.assertFalse(acquire("m2", "m", "mcp"))
            for i in range(4):
                release(f"g{i}", "gui")
            release("m0", "mcp"); release("m1", "mcp")
        finally:
            pass
        self.assertEqual(app._active_kind, {"gui": 0, "mcp": 0})
        self.assertEqual(app._active_searches, {})

    def test_pin_running_suppresses_destroy(self):
        import dataclasses
        app = self.app
        calls = []

        class _Cloud:
            def sleep(self, did=""):
                calls.append(did)

        orig_cloud, orig_cfg = app.cloud, app.CONFIG
        app.cloud = _Cloud()
        try:
            app.store.mark_up("pinned-box")
            app.CONFIG = dataclasses.replace(orig_cfg, pin_running=True)
            app._destroy("killswitch test")
            self.assertEqual(calls, [])
            self.assertEqual(app.store.snapshot(app._now()).status, app.DropletStatus.UP)
            app.CONFIG = orig_cfg
            app._destroy("killswitch test")
            self.assertEqual(calls, ["pinned-box"])
            self.assertEqual(app.store.snapshot(app._now()).status, app.DropletStatus.DOWN)
        finally:
            app.cloud, app.CONFIG = orig_cloud, orig_cfg

    def test_rpc_info_classification(self):
        app = self.app
        self.assertEqual(app._rpc_info(b'{"method":"tools/call","params":{"name":"search"}}'), (True, None))
        self.assertEqual(
            app._rpc_info(b'{"method":"tools/call","params":{"name":"save_to_zotero"}}'),
            (True, "save_to_zotero"))
        self.assertEqual(app._rpc_info(b'{"method":"initialize"}'), (False, None))
        self.assertEqual(app._rpc_info(b'{"method":"tools/list"}'), (False, None))
        self.assertEqual(app._rpc_info(b""), (False, None))
        self.assertEqual(app._rpc_info(b"not json"), (False, None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
