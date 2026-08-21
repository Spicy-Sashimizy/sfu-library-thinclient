"""Unit tests for the WI-3 memory dial (no kernel, no systemd needed).

    .venv/bin/python3 -m pytest scripts/demo_broker/test_dial.py

CgroupBackend is exercised against a tmpdir of fake cgroup-v2 files (the
designed test seam); SystemdBackend against a captured fake runner. The
endpoint test drives /admin/dial through the FastAPI TestClient with the dial
instance swapped in directly, so it composes with test_app.py's import-time
CONFIG regardless of test order.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from dial import (GB, CgroupBackend, DialError, MemoryDial,  # noqa: E402
                  SystemdBackend, make_dial)

_HAVE_WEB = all(importlib.util.find_spec(m) for m in ("fastapi", "httpx"))


def _fake_cgroup(high="max", mx="max", cur="1073741824", swap="0") -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "memory.high").write_text(high)
    (d / "memory.max").write_text(mx)
    (d / "memory.current").write_text(cur)
    (d / "memory.swap.max").write_text(swap)
    return d


class TestCgroupBackend(unittest.TestCase):
    def test_set_and_status_roundtrip(self):
        d = _fake_cgroup()
        dial = MemoryDial(CgroupBackend(d), 4, 64, 1536)
        st = dial.set_high(12)
        self.assertEqual(st.high_bytes, 12 * GB)
        self.assertEqual(st.max_bytes, 12 * GB + 1536 * 1024 ** 2)
        self.assertEqual((d / "memory.high").read_text(), str(12 * GB))
        self.assertEqual(st.current_bytes, GB)
        self.assertEqual(st.swap_max_bytes, 0)
        self.assertEqual(st.to_json()["memory_high"], "12.00G")

    def test_off_writes_max(self):
        d = _fake_cgroup(high=str(8 * GB), mx=str(9 * GB))
        st = MemoryDial(CgroupBackend(d), 4, 64, 1536).off()
        self.assertIsNone(st.high_bytes)
        self.assertIsNone(st.max_bytes)
        self.assertEqual((d / "memory.high").read_text(), "max")
        self.assertEqual(st.to_json()["memory_high"], "off")

    def test_fractional_rung(self):
        d = _fake_cgroup()
        st = MemoryDial(CgroupBackend(d), 4, 64, 1536).set_high(10.5)
        self.assertEqual(st.high_bytes, int(10.5 * GB))

    def test_bounds_refused_and_nothing_written(self):
        d = _fake_cgroup(high="max")
        dial = MemoryDial(CgroupBackend(d), 4, 64, 1536)
        for bad in (3.9, 65, 0, -8):
            with self.assertRaises(DialError):
                dial.set_high(bad)
        self.assertEqual((d / "memory.high").read_text(), "max")

    def test_not_a_cgroup_dir(self):
        dial = MemoryDial(CgroupBackend(tempfile.mkdtemp()), 4, 64, 1536)
        with self.assertRaises(DialError):
            dial.set_high(12)


class TestSystemdBackend(unittest.TestCase):
    def _runner(self, out="", rc=0):
        calls = []

        def run(argv, capture_output, text):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, rc, stdout=out, stderr="")
        return run, calls

    def test_set_property_argv(self):
        run, calls = self._runner()
        MemoryDial(SystemdBackend("sfu-serve.service", run), 4, 64, 1536) \
            .backend.set(12 * GB, 13 * GB)
        self.assertEqual(calls[0][:4],
                         ["systemctl", "set-property", "--runtime", "sfu-serve.service"])
        self.assertIn(f"MemoryHigh={12 * GB}", calls[0])
        self.assertIn(f"MemoryMax={13 * GB}", calls[0])

    def test_off_sends_infinity(self):
        run, calls = self._runner()
        SystemdBackend("u.service", run).set(None, None)
        self.assertIn("MemoryHigh=infinity", calls[0])
        self.assertIn("MemoryMax=infinity", calls[0])

    def test_status_parses_show_and_normalises_infinity(self):
        out = (f"MemoryHigh={12 * GB}\nMemoryMax=infinity\n"
               f"MemoryCurrent={2 * GB}\nMemorySwapMax=0\n")
        run, _ = self._runner(out=out)
        st = SystemdBackend("u.service", run).status()
        self.assertEqual(st.high_bytes, 12 * GB)
        self.assertIsNone(st.max_bytes)
        self.assertEqual(st.current_bytes, 2 * GB)
        self.assertEqual(st.swap_max_bytes, 0)

    def test_status_normalises_2p63_sentinel(self):
        run, _ = self._runner(out=f"MemoryHigh={2**63 - 1}\n")
        self.assertIsNone(SystemdBackend("u.service", run).status().high_bytes)

    def test_systemctl_failure_raises(self):
        run, _ = self._runner(rc=1)
        with self.assertRaises(DialError):
            SystemdBackend("u.service", run).status()


class TestMakeDial(unittest.TestCase):
    class _Cfg:
        dial_backend = "off"
        dial_unit = "sfu-serve.service"
        dial_cgroup_dir = ""
        dial_min_gb, dial_max_gb, dial_guard_mb = 4.0, 64.0, 1536

    def test_off_returns_none(self):
        self.assertIsNone(make_dial(self._Cfg()))

    def test_cgroup_needs_dir(self):
        cfg = self._Cfg()
        cfg.dial_backend = "cgroup"
        with self.assertRaises(DialError):
            make_dial(cfg)

    def test_unknown_backend(self):
        cfg = self._Cfg()
        cfg.dial_backend = "wat"
        with self.assertRaises(DialError):
            make_dial(cfg)


@unittest.skipUnless(_HAVE_WEB, "needs fastapi+httpx (project venv)")
class TestDialEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("DEMO_STATE_PATH", os.path.join(tempfile.mkdtemp(), "state.db"))
        os.environ.setdefault("DEMO_LOG_PATH", os.path.join(tempfile.mkdtemp(), "b.jsonl"))
        os.environ["DEMO_ADMIN_TOKEN"] = "adm"
        from fastapi.testclient import TestClient
        import app
        cls.app = app
        cls.c = TestClient(app.app)
        cls.adm = {"x-admin-token": os.environ.get("DEMO_ADMIN_TOKEN", "adm")}
        # test_app.py may have imported app first with a different token env;
        # read the live one off the imported CONFIG so both orders pass.
        cls.adm = {"x-admin-token": app.CONFIG.admin_token}

    def setUp(self):
        self.app.dial = MemoryDial(CgroupBackend(_fake_cgroup()), 4, 64, 1536)

    def test_requires_admin(self):
        self.assertEqual(self.c.get("/admin/dial").status_code, 403)

    def test_disabled_404(self):
        self.app.dial = None
        self.assertEqual(self.c.get("/admin/dial", headers=self.adm).status_code, 404)

    def test_status_set_off_flow(self):
        j = self.c.get("/admin/dial", headers=self.adm).json()
        self.assertEqual(j["memory_high"], "off")
        j = self.c.post("/admin/dial?gb=12", headers=self.adm).json()
        self.assertEqual(j["high_bytes"], 12 * GB)
        j = self.c.post("/admin/dial?off=1", headers=self.adm).json()
        self.assertEqual(j["memory_high"], "off")

    def test_bounds_400(self):
        self.assertEqual(self.c.post("/admin/dial?gb=2", headers=self.adm).status_code, 400)

    def test_gb_xor_off_422(self):
        self.assertEqual(self.c.post("/admin/dial", headers=self.adm).status_code, 422)
        self.assertEqual(
            self.c.post("/admin/dial?gb=12&off=1", headers=self.adm).status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
