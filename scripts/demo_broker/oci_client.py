"""Oracle Cloud Infrastructure control wrapper — START/STOP ONE persistent instance.

The OCI port of `do_client.py` (mapping table: `docs/infrastructure/
OCI_DEMO_DEPLOYMENT.md` §4). It is deliberately *simpler* than the DO client
because OCI pauses OCPU+RAM billing on a stopped instance (§0), so:

  * wake  = `POST /20160918/instances/<ocid>?action=START`   (no create, no seed)
  * sleep = `POST /20160918/instances/<ocid>?action=SOFTSTOP`(no destroy)

The instance, its boot volume and its block volume **always exist**: the OCID is
static config (`OCI_INSTANCE_OCID`), never created/destroyed state. Everything
the broker keeps in `state.py` under `droplet_id` is therefore just "is the
compute supposed to be up", and `stop_instance("")` still targets the configured
OCID so the daily killswitch can fire even after a state loss.

STOP vs SOFTSTOP: OCI's `STOP` is a hard power-off (immediate, may lose unflushed
guest state); `SOFTSTOP` sends an ACPI shutdown, waits, then powers off. We
default to **SOFTSTOP** (clean unmount of the 150 GB index volume) and keep
`STOP` available as the documented fallback via `OCI_STOP_ACTION=STOP` for a
guest that hangs on shutdown. Both stop compute billing; per §0/§8 a guest-OS
`shutdown` does NOT — never sleep the box that way.

Dry-run by default (cfg.live=False), exactly like `do_client.py`: every mutating
call is LOGGED, not sent, and returns a plausible fake, so the whole broker can
be exercised without an OCI tenancy.

Auth is OCI API-key request signing (IETF draft-cavage HTTP Signatures):
RSA-SHA256 over `(request-target) date host` (+ `x-content-sha256 content-type
content-length` on POST/PUT), keyId `<tenancy>/<user>/<fingerprint>`. stdlib
urllib for HTTP + `cryptography` for the RSA signature — the full `oci` SDK is
NOT a dependency (heavy tree; the broker box is a 1 GB free-tier VM). The key
material comes from broker config/env (`OCI_KEY_FILE`), never from an implicit
read of `~/.oci/config`.

**IMPLEMENTED, EFFICACY UNMEASURED (2026-08-19): mock-tested only — no OCI API
call has ever been made from this code (no tenancy exists yet).**
"""
from __future__ import annotations

import base64
import email.utils
import hashlib
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from scheduler import DropletStatus

log = logging.getLogger("demo_broker.oci")

_API = "/20160918"

_STATE_MAP = {
    "RUNNING": DropletStatus.UP,
    "STARTING": DropletStatus.BOOTING,
    "PROVISIONING": DropletStatus.BOOTING,
    "MOVING": DropletStatus.BOOTING,
    "CREATING_IMAGE": DropletStatus.BOOTING,
    "STOPPING": DropletStatus.DOWN,
    "STOPPED": DropletStatus.DOWN,
    "TERMINATING": DropletStatus.DOWN,
    "TERMINATED": DropletStatus.DOWN,
}

_SIGN_GET = ("(request-target)", "date", "host")
_SIGN_BODY = _SIGN_GET + ("x-content-sha256", "content-type", "content-length")
_BODY_METHODS = ("POST", "PUT", "PATCH")


class OCIError(RuntimeError):
    pass


def load_private_key(path: str, passphrase: str = ""):
    """Load the OCI API-signing key (PEM). Raises OCIError with an actionable message."""
    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError as e:  # pragma: no cover - env-dependent
        raise OCIError("OCI signing needs `cryptography` "
                       "(.venv/bin/python3 -m pip install cryptography)") from e
    try:
        with open(path, "rb") as fh:
            return serialization.load_pem_private_key(
                fh.read(), password=passphrase.encode() if passphrase else None)
    except OSError as e:
        raise OCIError(f"cannot read OCI_KEY_FILE {path!r}: {e}") from e
    except (ValueError, TypeError) as e:
        raise OCIError(f"OCI_KEY_FILE {path!r} is not a usable PEM key: {e}") from e


def signing_string(method: str, url: str, headers: dict, names: tuple[str, ...]) -> str:
    """The draft-cavage signing string for `names`, in order."""
    parts = urllib.parse.urlsplit(url)
    target = parts.path + (f"?{parts.query}" if parts.query else "")
    out = []
    for n in names:
        v = f"{method.lower()} {target}" if n == "(request-target)" else headers[n]
        out.append(f"{n}: {v}")
    return "\n".join(out)


def sign_headers(method: str, url: str, body: bytes | None, *, key_id: str,
                 private_key, date: str | None = None) -> dict[str, str]:
    """Return the headers (date/host/authorization[+content-*]) for a signed request.

    Pure and deterministic given `date` — that is the unit-test seam
    (test_oci_client.py verifies the signature with the matching public key).
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    m = method.upper()
    hdrs = {
        "date": date or email.utils.formatdate(usegmt=True),
        "host": urllib.parse.urlsplit(url).netloc,
    }
    if m in _BODY_METHODS:
        raw = body or b""
        hdrs["x-content-sha256"] = base64.b64encode(hashlib.sha256(raw).digest()).decode()
        hdrs["content-type"] = "application/json"
        hdrs["content-length"] = str(len(raw))
        names = _SIGN_BODY
    else:
        names = _SIGN_GET
    sig = base64.b64encode(private_key.sign(
        signing_string(m, url, hdrs, names).encode(),
        padding.PKCS1v15(), hashes.SHA256())).decode()
    hdrs["authorization"] = (
        'Signature version="1",keyId="%s",algorithm="rsa-sha256",'
        'headers="%s",signature="%s"' % (key_id, " ".join(names), sig))
    return hdrs


def lifecycle_status(state: str | None) -> DropletStatus:
    """Map an OCI instance lifecycleState to the broker's DropletStatus.

    Unknown/None states are treated as DOWN — the conservative direction: the
    broker will try to wake (idempotent START) rather than assume it is serving.
    """
    return _STATE_MAP.get((state or "").upper(), DropletStatus.DOWN)


class OCIClient:
    """Same surface the broker needs from DOClient, on OCI START/STOP semantics."""

    def __init__(self, cfg):
        self.cfg = cfg
        self._key = None

    @property
    def key_id(self) -> str:
        return f"{self.cfg.oci_tenancy_ocid}/{self.cfg.oci_user_ocid}/{self.cfg.oci_fingerprint}"

    def _private_key(self):
        if self._key is None:
            if not self.cfg.oci_key_file:
                raise OCIError("OCI_KEY_FILE unset (no API signing key)")
            self._key = load_private_key(self.cfg.oci_key_file, self.cfg.oci_key_passphrase)
        return self._key

    def _endpoint(self) -> str:
        return f"https://iaas.{self.cfg.oci_region}.oraclecloud.com"

    def _req(self, method: str, path: str, body: dict | None = None) -> dict | list:
        url = f"{self._endpoint()}{path}"
        data = json.dumps(body).encode() if body is not None else (
            b"" if method.upper() in _BODY_METHODS else None)
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in sign_headers(method, url, data, key_id=self.key_id,
                                 private_key=self._private_key()).items():
            req.add_header(k, v)
        req.add_header("accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise OCIError(f"OCI {method} {path} -> {e.code}: "
                           f"{e.read().decode(errors='replace')}") from e
        except urllib.error.URLError as e:
            raise OCIError(f"OCI {method} {path} unreachable: {e}") from e

    def _instance_id(self, instance_id: str = "") -> str:
        """The target OCID: the caller's, else the static config one (§4: it never changes)."""
        iid = instance_id or self.cfg.oci_instance_id
        if not iid:
            if not self.cfg.live:
                return "dry-run-instance"
            raise OCIError("OCI_INSTANCE_OCID unset (nothing to START/STOP)")
        return iid

    def _action(self, instance_id: str, action: str) -> None:
        self._req("POST", f"{_API}/instances/{urllib.parse.quote(instance_id, safe='')}"
                          f"?action={action}")

    def start_instance(self) -> str:
        """START the persistent demo instance. Returns its OCID (static config)."""
        iid = self._instance_id()
        if not self.cfg.live:
            log.warning("[DRY-RUN] instance action START %s", iid)
            return iid
        self._action(iid, "START")
        log.info("START issued for instance %s (%s)", iid, self.cfg.oci_region)
        return iid

    def stop_instance(self, instance_id: str = "") -> None:
        """SOFTSTOP (default) the instance — compute billing ends, volumes persist.

        An empty `instance_id` still targets the configured OCID: unlike a DO
        droplet there is nothing to look up, so the killswitch must be able to
        fire even if broker state was lost.
        """
        action = (self.cfg.oci_stop_action or "SOFTSTOP").upper()
        if action not in ("SOFTSTOP", "STOP"):
            raise OCIError(f"OCI_STOP_ACTION {action!r} must be SOFTSTOP or STOP")
        iid = self._instance_id(instance_id)
        if not self.cfg.live:
            log.warning("[DRY-RUN] instance action %s %s (volumes kept)", action, iid)
            return
        self._action(iid, action)
        log.info("%s issued for instance %s (boot+block volumes kept)", action, iid)

    def instance_state(self, instance_id: str = "") -> str | None:
        """Raw OCI lifecycleState (RUNNING / STOPPED / STARTING / STOPPING / ...)."""
        if not self.cfg.live:
            return "RUNNING"
        res = self._req("GET", f"{_API}/instances/"
                               f"{urllib.parse.quote(self._instance_id(instance_id), safe='')}")
        return res.get("lifecycleState")

    def instance_status(self, instance_id: str = "") -> DropletStatus:
        return lifecycle_status(self.instance_state(instance_id))

    def instance_active(self, instance_id: str = "") -> bool:
        """OCI-side 'running' (not the same as the app's /health-ready)."""
        return self.instance_status(instance_id) == DropletStatus.UP

    def instance_ip(self, instance_id: str = "") -> str | None:
        """The address the broker proxies to.

        Default path is the config short-circuit `OCI_INSTANCE_IP`: the instance
        persists, so its private IP is stable and worth zero API calls per proxied
        request. The VNIC-attachment lookup is the fallback for when it is unset.
        """
        if self.cfg.oci_instance_ip:
            return self.cfg.oci_instance_ip
        if not self.cfg.live:
            return "127.0.0.1"
        if not self.cfg.oci_compartment_id:
            raise OCIError("set OCI_INSTANCE_IP (preferred) or OCI_COMPARTMENT_OCID "
                           "(needed to list VNIC attachments)")
        iid = self._instance_id(instance_id)
        q = urllib.parse.urlencode({"compartmentId": self.cfg.oci_compartment_id,
                                    "instanceId": iid})
        atts = self._req("GET", f"{_API}/vnicAttachments?{q}")
        for att in atts if isinstance(atts, list) else []:
            if att.get("lifecycleState") != "ATTACHED" or not att.get("vnicId"):
                continue
            vnic = self._req("GET", f"{_API}/vnics/"
                                    f"{urllib.parse.quote(att['vnicId'], safe='')}")
            ip = vnic.get("privateIp") or vnic.get("publicIp")
            if ip:
                return ip
        return None

    def wake(self) -> str:
        return self.start_instance()

    def sleep(self, compute_id: str = "") -> None:
        self.stop_instance(compute_id)

    def compute_ip(self, compute_id: str = "") -> str | None:
        return self.instance_ip(compute_id)

    def compute_active(self, compute_id: str = "") -> bool:
        return self.instance_active(compute_id)
