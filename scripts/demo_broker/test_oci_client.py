"""Unit tests for the OCI cloud-control port (no network, no real keys).

    .venv/bin/python3 -m pytest scripts/demo_broker/test_oci_client.py

Every HTTP call is intercepted by patching `oci_client.urllib.request.urlopen`
(the same seam do_client would use), so nothing here can reach OCI — which is
the point: **no OCI API call has ever been made** (no tenancy exists,
2026-08-19). Signing is exercised against a throwaway RSA key generated in
setUpClass and verified with its own public half.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from cloud import CloudError, make_cloud_client  # noqa: E402
from do_client import DOClient  # noqa: E402
from oci_client import (OCIClient, OCIError, lifecycle_status,  # noqa: E402
                        load_private_key, sign_headers, signing_string)
from scheduler import DropletStatus  # noqa: E402

_DATE = "Thu, 19 Aug 2026 12:00:00 GMT"
_OCID = "ocid1.instance.example-11"


class _Cfg:
    """Minimal stand-in for config.Config (the broker only reads attributes)."""
    cloud = "oci"
    live = True
    oci_tenancy_ocid = "ocid1.tenancy.oc1..t"
    oci_user_ocid = "ocid1.user.oc1..u"
    oci_fingerprint = "aa:bb:cc"
    oci_key_file = ""
    oci_key_passphrase = ""
    oci_region = "ca-toronto-1"
    oci_instance_id = _OCID
    oci_instance_ip = ""
    oci_compartment_id = ""
    oci_stop_action = "SOFTSTOP"
    do_token = "t"


class _Resp:
    """Context-manager stand-in for the urlopen return."""

    def __init__(self, payload):
        self._raw = json.dumps(payload).encode() if payload is not None else b""

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _rsa_key():
    from cryptography.hazmat.primitives.asymmetric import rsa
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class TestSigning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = _rsa_key()

    def _parse_auth(self, auth: str) -> dict:
        self.assertTrue(auth.startswith("Signature "))
        out = {}
        for kv in auth[len("Signature "):].split(","):
            k, v = kv.split("=", 1)
            out[k] = v.strip('"')
        return out

    def test_get_header_structure_and_verifiable_signature(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        url = f"https://iaas.ca-toronto-1.oraclecloud.com/20160918/instances/{_OCID}"
        h = sign_headers("GET", url, None, key_id="t/u/aa:bb:cc",
                         private_key=self.key, date=_DATE)
        self.assertEqual(h["date"], _DATE)
        self.assertEqual(h["host"], "iaas.ca-toronto-1.oraclecloud.com")
        self.assertNotIn("x-content-sha256", h)
        a = self._parse_auth(h["authorization"])
        self.assertEqual(a["version"], "1")
        self.assertEqual(a["keyId"], "t/u/aa:bb:cc")
        self.assertEqual(a["algorithm"], "rsa-sha256")
        self.assertEqual(a["headers"], "(request-target) date host")
        expect = (f"(request-target): get /20160918/instances/{_OCID}\n"
                  f"date: {_DATE}\nhost: iaas.ca-toronto-1.oraclecloud.com")
        self.assertEqual(signing_string("GET", url, h, ("(request-target)", "date", "host")),
                         expect)
        self.key.public_key().verify(base64.b64decode(a["signature"]), expect.encode(),
                                     padding.PKCS1v15(), hashes.SHA256())

    def test_post_signs_body_headers_and_query_in_request_target(self):
        url = (f"https://iaas.ca-toronto-1.oraclecloud.com/20160918/instances/"
               f"{_OCID}?action=START")
        h = sign_headers("POST", url, b"", key_id="k", private_key=self.key, date=_DATE)
        self.assertEqual(h["content-length"], "0")
        self.assertEqual(h["content-type"], "application/json")
        self.assertEqual(h["x-content-sha256"],
                         "47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=")
        a = self._parse_auth(h["authorization"])
        self.assertEqual(a["headers"],
                         "(request-target) date host x-content-sha256 "
                         "content-type content-length")
        self.assertIn(f"(request-target): post /20160918/instances/{_OCID}?action=START",
                      signing_string("POST", url, h, tuple(a["headers"].split())))

    def test_signature_is_deterministic_for_fixed_inputs(self):
        url = "https://iaas.ca-toronto-1.oraclecloud.com/20160918/instances/x"
        a = sign_headers("GET", url, None, key_id="k", private_key=self.key, date=_DATE)
        b = sign_headers("GET", url, None, key_id="k", private_key=self.key, date=_DATE)
        self.assertEqual(a["authorization"], b["authorization"])

    def test_load_private_key_roundtrip_and_errors(self):
        from cryptography.hazmat.primitives import serialization
        pem = self.key.private_bytes(serialization.Encoding.PEM,
                                     serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption())
        path = os.path.join(tempfile.mkdtemp(), "key.pem")
        with open(path, "wb") as fh:
            fh.write(pem)
        self.assertIsNotNone(load_private_key(path))
        with self.assertRaises(OCIError):
            load_private_key(os.path.join(tempfile.mkdtemp(), "nope.pem"))
        bad = os.path.join(tempfile.mkdtemp(), "bad.pem")
        with open(bad, "w") as fh:
            fh.write("not a key")
        with self.assertRaises(OCIError):
            load_private_key(bad)

    def test_client_signs_with_configured_key_file(self):
        from cryptography.hazmat.primitives import serialization
        path = os.path.join(tempfile.mkdtemp(), "key.pem")
        with open(path, "wb") as fh:
            fh.write(self.key.private_bytes(serialization.Encoding.PEM,
                                            serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()))
        cfg = _Cfg()
        cfg.oci_key_file = path
        c = OCIClient(cfg)
        self.assertEqual(c.key_id, "ocid1.tenancy.oc1..t/ocid1.user.oc1..u/aa:bb:cc")
        with mock.patch("oci_client.urllib.request.urlopen",
                        return_value=_Resp({})) as up:
            c.start_instance()
        req = up.call_args.args[0]
        self.assertIn("Signature version=\"1\"", req.get_header("Authorization"))
        self.assertIn(c.key_id, req.get_header("Authorization"))

    def test_missing_key_file_raises(self):
        with self.assertRaises(OCIError):
            OCIClient(_Cfg())._private_key()


class _LiveClientCase(unittest.TestCase):
    """Base: a LIVE client whose signing is stubbed out (signing tested above)."""

    def setUp(self):
        self.cfg = _Cfg()
        self.c = OCIClient(self.cfg)
        self.c._key = object()
        p = mock.patch("oci_client.sign_headers", return_value={"authorization": "sig"})
        p.start()
        self.addCleanup(p.stop)

    def _urlopen(self, *payloads):
        m = mock.patch("oci_client.urllib.request.urlopen",
                       side_effect=[_Resp(p) for p in payloads])
        up = m.start()
        self.addCleanup(m.stop)
        return up

    @staticmethod
    def _url(call):
        return call.args[0].full_url

    @staticmethod
    def _method(call):
        return call.args[0].get_method()


class TestActions(_LiveClientCase):
    def test_start_issues_action_start(self):
        up = self._urlopen({})
        self.assertEqual(self.c.start_instance(), _OCID)
        self.assertEqual(self._method(up.call_args), "POST")
        self.assertEqual(
            self._url(up.call_args),
            "https://iaas.ca-toronto-1.oraclecloud.com/20160918/instances/"
            f"{_OCID}?action=START")

    def test_stop_defaults_to_softstop(self):
        up = self._urlopen({})
        self.c.stop_instance(_OCID)
        self.assertTrue(self._url(up.call_args).endswith("?action=SOFTSTOP"))

    def test_stop_action_override_to_hard_stop(self):
        self.cfg.oci_stop_action = "STOP"
        up = self._urlopen({})
        self.c.stop_instance(_OCID)
        self.assertTrue(self._url(up.call_args).endswith("?action=STOP"))

    def test_bad_stop_action_refused_before_any_call(self):
        self.cfg.oci_stop_action = "TERMINATE"
        up = self._urlopen({})
        with self.assertRaises(OCIError):
            self.c.stop_instance(_OCID)
        up.assert_not_called()

    def test_stop_without_id_falls_back_to_static_ocid(self):
        """OCI has nothing to look up — the killswitch must fire after state loss."""
        up = self._urlopen({})
        self.c.stop_instance("")
        self.assertIn(_OCID, self._url(up.call_args))

    def test_missing_ocid_raises_in_live_mode(self):
        self.cfg.oci_instance_id = ""
        with self.assertRaises(OCIError):
            self.c.start_instance()

    def test_http_error_becomes_ocierror(self):
        m = mock.patch("oci_client.urllib.request.urlopen",
                       side_effect=urllib.error.HTTPError(
                           "u", 404, "Not Found", {}, io.BytesIO(b'{"code":"NotFound"}')))
        m.start()
        self.addCleanup(m.stop)
        with self.assertRaises(OCIError):
            self.c.start_instance()

    def test_unreachable_becomes_ocierror(self):
        m = mock.patch("oci_client.urllib.request.urlopen",
                       side_effect=urllib.error.URLError("dns"))
        m.start()
        self.addCleanup(m.stop)
        with self.assertRaises(OCIError):
            self.c.instance_state()


class TestLifecycle(_LiveClientCase):
    def test_state_read_from_get_instance(self):
        up = self._urlopen({"lifecycleState": "STOPPED"})
        self.assertEqual(self.c.instance_state(), "STOPPED")
        self.assertEqual(self._method(up.call_args), "GET")
        self.assertTrue(self._url(up.call_args).endswith(f"/20160918/instances/{_OCID}"))

    def test_state_mapping(self):
        for state in ("RUNNING", "running"):
            self.assertEqual(lifecycle_status(state), DropletStatus.UP)
        for state in ("STARTING", "PROVISIONING", "MOVING", "CREATING_IMAGE"):
            self.assertEqual(lifecycle_status(state), DropletStatus.BOOTING)
        for state in ("STOPPING", "STOPPED", "TERMINATING", "TERMINATED", "", None, "WAT"):
            self.assertEqual(lifecycle_status(state), DropletStatus.DOWN)

    def test_active_only_when_running(self):
        self._urlopen({"lifecycleState": "RUNNING"})
        self.assertTrue(self.c.compute_active(_OCID))
        self._urlopen({"lifecycleState": "STARTING"})
        self.assertFalse(self.c.compute_active(_OCID))


class TestInstanceIP(_LiveClientCase):
    def test_config_short_circuit_makes_no_api_call(self):
        self.cfg.oci_instance_ip = "10.0.0.7"
        up = self._urlopen({})
        self.assertEqual(self.c.compute_ip(_OCID), "10.0.0.7")
        up.assert_not_called()

    def test_vnic_fallback(self):
        self.cfg.oci_compartment_id = "ocid1.compartment.oc1..c"
        up = self._urlopen(
            [{"lifecycleState": "DETACHED", "vnicId": "v0"},
             {"lifecycleState": "ATTACHED", "vnicId": "ocid1.vnic.oc1..v1"}],
            {"privateIp": "10.0.0.9", "publicIp": "203.0.113.5"})
        self.assertEqual(self.c.instance_ip(_OCID), "10.0.0.9")
        self.assertIn("/20160918/vnicAttachments?", self._url(up.call_args_list[0]))
        self.assertIn("instanceId=", self._url(up.call_args_list[0]))
        self.assertTrue(self._url(up.call_args_list[1]).endswith(
            "/20160918/vnics/ocid1.vnic.oc1..v1"))

    def test_vnic_fallback_no_attachment_returns_none(self):
        self.cfg.oci_compartment_id = "ocid1.compartment.oc1..c"
        self._urlopen([])
        self.assertIsNone(self.c.instance_ip(_OCID))

    def test_fallback_without_compartment_raises(self):
        with self.assertRaises(OCIError):
            self.c.instance_ip(_OCID)


class TestDryRun(unittest.TestCase):
    def setUp(self):
        self.cfg = _Cfg()
        self.cfg.live = False
        self.c = OCIClient(self.cfg)
        m = mock.patch("oci_client.urllib.request.urlopen",
                       side_effect=AssertionError("dry-run must not call OCI"))
        self.up = m.start()
        self.addCleanup(m.stop)

    def test_start_stop_send_nothing(self):
        self.assertEqual(self.c.wake(), _OCID)
        self.c.sleep(_OCID)
        self.up.assert_not_called()

    def test_placeholder_id_when_no_ocid_configured(self):
        self.cfg.oci_instance_id = ""
        self.assertEqual(self.c.wake(), "dry-run-instance")

    def test_state_and_ip_are_plausible_fakes(self):
        self.assertEqual(self.c.instance_state(), "RUNNING")
        self.assertTrue(self.c.compute_active())
        self.assertEqual(self.c.compute_ip(_OCID), "127.0.0.1")

    def test_configured_ip_wins_even_in_dry_run(self):
        self.cfg.oci_instance_ip = "10.0.0.7"
        self.assertEqual(self.c.compute_ip(_OCID), "10.0.0.7")


class TestFactory(unittest.TestCase):
    def test_default_is_digitalocean(self):
        cfg = _Cfg()
        del cfg.__class__.cloud
        try:
            self.assertIsInstance(make_cloud_client(cfg), DOClient)
        finally:
            _Cfg.cloud = "oci"

    def test_explicit_do(self):
        cfg = _Cfg()
        cfg.cloud = "do"
        self.assertIsInstance(make_cloud_client(cfg), DOClient)

    def test_oci_selected(self):
        cfg = _Cfg()
        cfg.cloud = "OCI "
        self.assertIsInstance(make_cloud_client(cfg), OCIClient)

    def test_unknown_provider_raises(self):
        cfg = _Cfg()
        cfg.cloud = "aws"
        with self.assertRaises(CloudError):
            make_cloud_client(cfg)

    def test_config_default_is_do(self):
        env = {k: v for k, v in os.environ.items() if k != "DEMO_CLOUD"}
        with mock.patch.dict(os.environ, env, clear=True):
            import importlib
            import config as config_mod
            self.assertEqual(importlib.reload(config_mod).Config().cloud, "do")

    @classmethod
    def tearDownClass(cls):
        import importlib
        import config as config_mod
        importlib.reload(config_mod)

    def test_both_clients_expose_the_protocol(self):
        for cls in (DOClient, OCIClient):
            for meth in ("wake", "sleep", "compute_ip", "compute_active"):
                self.assertTrue(callable(getattr(cls, meth)), f"{cls.__name__}.{meth}")


class TestConfigValidate(unittest.TestCase):
    def _cfg(self, **env):
        import importlib
        import config as config_mod
        with mock.patch.dict(os.environ, env, clear=False):
            return importlib.reload(config_mod).Config()

    def test_live_oci_reports_missing_auth_not_do_ids(self):
        probs = " ".join(self._cfg(DEMO_CLOUD="oci", DEMO_BROKER_LIVE="1",
                                   DEMO_LINK_TOKEN="x").validate())
        self.assertIn("OCI_TENANCY_OCID", probs)
        self.assertIn("OCI_INSTANCE_OCID", probs)
        self.assertNotIn("DEMO_DO_SNAPSHOT_ID", probs)

    def test_unknown_cloud_flagged(self):
        self.assertTrue(any("DEMO_CLOUD" in p for p in
                            self._cfg(DEMO_CLOUD="gcp", DEMO_LINK_TOKEN="x").validate()))

    @classmethod
    def tearDownClass(cls):
        import importlib
        import config as config_mod
        importlib.reload(config_mod)


if __name__ == "__main__":
    unittest.main(verbosity=2)
