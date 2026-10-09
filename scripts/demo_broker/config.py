"""Demo broker config — all knobs are env-driven so the NAS deploy needs no code edits.

Loaded once at startup. Safe defaults are conservative for the $200 credit:
dry-run is ON by default (no DO API spend until DEMO_BROKER_LIVE=1), the hard
daily killswitch is the budget backstop, and the business-hours window keeps the
droplet hot 09:00-17:00 weekdays only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo


def _b(name: str, default: bool) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _read_secret(val: str) -> str:
    """Allow a secret env var to be a literal value OR a path to a secret file
    (so the broker can reuse the monitor's gitignored secret files on the NAS)."""
    if val and os.path.isfile(val):
        try:
            return open(val).read().strip()
        except OSError:
            return ""
    return val


def _days(name: str, default: str) -> frozenset[int]:
    raw = os.environ.get(name, default)
    out: set[int] = set()
    for tok in raw.replace(" ", "").split(","):
        if not tok:
            continue
        out.add(int(tok))
    return frozenset(out)


@dataclass(frozen=True)
class Config:
    cloud: str = field(default_factory=lambda: os.environ.get("DEMO_CLOUD", "do").strip().lower())

    do_token: str = field(default_factory=lambda: os.environ.get("DIGITALOCEAN_ACCESS_TOKEN", ""))
    do_region: str = field(default_factory=lambda: os.environ.get("DEMO_DO_REGION", "tor1"))
    do_size: str = field(default_factory=lambda: os.environ.get("DEMO_DO_SIZE", "g-16vcpu-64gb"))
    do_snapshot_id: str = field(default_factory=lambda: os.environ.get("DEMO_DO_SNAPSHOT_ID", ""))
    do_volume_id: str = field(default_factory=lambda: os.environ.get("DEMO_DO_VOLUME_ID", ""))
    do_droplet_name: str = field(default_factory=lambda: os.environ.get("DEMO_DO_DROPLET_NAME", "sfu-demo"))
    do_firewall_id: str = field(default_factory=lambda: os.environ.get("DEMO_DO_FIREWALL_ID", ""))

    oci_tenancy_ocid: str = field(default_factory=lambda: os.environ.get("OCI_TENANCY_OCID", ""))
    oci_user_ocid: str = field(default_factory=lambda: os.environ.get("OCI_USER_OCID", ""))
    oci_fingerprint: str = field(default_factory=lambda: os.environ.get("OCI_FINGERPRINT", ""))
    oci_key_file: str = field(default_factory=lambda: os.environ.get("OCI_KEY_FILE", ""))
    oci_key_passphrase: str = field(
        default_factory=lambda: _read_secret(os.environ.get("OCI_KEY_PASSPHRASE", "")))
    oci_region: str = field(default_factory=lambda: os.environ.get("OCI_REGION", "ca-toronto-1"))
    oci_instance_id: str = field(default_factory=lambda: os.environ.get("OCI_INSTANCE_OCID", ""))
    oci_instance_ip: str = field(default_factory=lambda: os.environ.get("OCI_INSTANCE_IP", ""))
    oci_compartment_id: str = field(
        default_factory=lambda: os.environ.get("OCI_COMPARTMENT_OCID", ""))
    oci_stop_action: str = field(
        default_factory=lambda: os.environ.get("OCI_STOP_ACTION", "SOFTSTOP").strip().upper())

    live: bool = field(default_factory=lambda: _b("DEMO_BROKER_LIVE", False))
    pin_running: bool = field(default_factory=lambda: _b("DEMO_PIN_RUNNING", False))
    link_token: str = field(default_factory=lambda: os.environ.get("DEMO_LINK_TOKEN", ""))
    bearer_token: str = field(default_factory=lambda: os.environ.get("DEMO_BEARER_TOKEN", ""))
    admin_token: str = field(default_factory=lambda: os.environ.get("DEMO_ADMIN_TOKEN", ""))

    public_base: str = field(default_factory=lambda: os.environ.get("DEMO_PUBLIC_BASE", "https://demo.example.org"))
    session_rate_max: int = field(default_factory=lambda: _i("DEMO_SESSION_RATE_MAX", 30))
    session_rate_window_s: int = field(default_factory=lambda: _i("DEMO_SESSION_RATE_WINDOW_S", 60))
    session_daily_max: int = field(default_factory=lambda: _i("DEMO_SESSION_DAILY_MAX", 500))
    max_concurrent_searches: int = field(default_factory=lambda: _i("DEMO_MAX_CONCURRENT_SEARCHES", 6))
    mcp_reserved_slots: int = field(default_factory=lambda: _i("DEMO_MCP_RESERVED_SLOTS", 2))
    concurrent_notify_at: int = field(default_factory=lambda: _i("DEMO_CONCURRENT_NOTIFY_AT", 2))
    concurrent_notify_cooldown_s: int = field(default_factory=lambda: _i("DEMO_CONCURRENT_NOTIFY_COOLDOWN_S", 600))
    blocked_tools: frozenset[str] = field(
        default_factory=lambda: frozenset(
            os.environ.get("DEMO_BLOCKED_TOOLS", "save_to_zotero,batch_save_to_zotero").replace(" ", "").split(",")))

    notify_webhook: str = field(default_factory=lambda: os.environ.get("DEMO_NOTIFY_WEBHOOK", ""))
    notify_kind: str = field(default_factory=lambda: os.environ.get("DEMO_NOTIFY_KIND", "ntfy"))
    notify_token: str = field(default_factory=lambda: _read_secret(os.environ.get("DEMO_NOTIFY_TOKEN", "")))
    notify_on_query: bool = field(default_factory=lambda: _b("DEMO_NOTIFY_ON_QUERY", False))

    log_path: str = field(default_factory=lambda: os.environ.get("DEMO_LOG_PATH", "data/demo_broker/broker.jsonl"))

    tz: str = field(default_factory=lambda: os.environ.get("DEMO_TZ", "America/Vancouver"))
    business_start_hour: int = field(default_factory=lambda: _i("DEMO_BUSINESS_START_HOUR", 9))
    business_end_hour: int = field(default_factory=lambda: _i("DEMO_BUSINESS_END_HOUR", 17))
    business_days: frozenset[int] = field(default_factory=lambda: _days("DEMO_BUSINESS_DAYS", "0,1,2,3,4"))
    prewarm_minutes: int = field(default_factory=lambda: _i("DEMO_PREWARM_MINUTES", 5))

    idle_minutes: int = field(default_factory=lambda: _i("DEMO_IDLE_MINUTES", 20))
    max_session_minutes: int = field(default_factory=lambda: _i("DEMO_MAX_SESSION_MINUTES", 0))
    max_runtime_hours_per_day: float = field(default_factory=lambda: _f("DEMO_MAX_RUNTIME_HOURS_PER_DAY", 10.0))
    max_runtime_hours_per_month: float = field(
        default_factory=lambda: _f("DEMO_MAX_RUNTIME_HOURS_PER_MONTH", 0.0))
    poll_seconds: int = field(default_factory=lambda: _i("DEMO_POLL_SECONDS", 60))

    dial_backend: str = field(default_factory=lambda: os.environ.get("DEMO_DIAL_BACKEND", "off"))
    dial_unit: str = field(default_factory=lambda: os.environ.get("DEMO_DIAL_UNIT", "sfu-serve.service"))
    dial_cgroup_dir: str = field(default_factory=lambda: os.environ.get("DEMO_DIAL_CGROUP_DIR", ""))
    dial_min_gb: float = field(default_factory=lambda: _f("DEMO_DIAL_MIN_GB", 4.0))
    dial_max_gb: float = field(default_factory=lambda: _f("DEMO_DIAL_MAX_GB", 64.0))
    dial_guard_mb: int = field(default_factory=lambda: _i("DEMO_DIAL_GUARD_MB", 1536))

    droplet_port: int = field(default_factory=lambda: _i("DEMO_DROPLET_PORT", 8080))
    health_timeout_s: float = field(default_factory=lambda: _f("DEMO_HEALTH_TIMEOUT_S", 3.0))
    upstream_timeout_s: float = field(default_factory=lambda: _f("DEMO_UPSTREAM_TIMEOUT_S", 300.0))
    state_path: str = field(default_factory=lambda: os.environ.get("DEMO_STATE_PATH", "data/demo_broker/state.db"))

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)

    def validate(self) -> list[str]:
        """Return a list of human-readable problems; empty == ready for LIVE."""
        problems: list[str] = []
        if self.cloud not in ("do", "oci"):
            problems.append(f"DEMO_CLOUD={self.cloud!r} unknown (do|oci)")
        if self.live and self.cloud == "do":
            if not self.do_token:
                problems.append("DIGITALOCEAN_ACCESS_TOKEN unset (required in LIVE mode)")
            if not self.do_snapshot_id:
                problems.append("DEMO_DO_SNAPSHOT_ID unset (no image to boot)")
            if not self.do_volume_id:
                problems.append("DEMO_DO_VOLUME_ID unset (no index volume to attach)")
        if self.live and self.cloud == "oci":
            for name, val in (("OCI_TENANCY_OCID", self.oci_tenancy_ocid),
                              ("OCI_USER_OCID", self.oci_user_ocid),
                              ("OCI_FINGERPRINT", self.oci_fingerprint),
                              ("OCI_KEY_FILE", self.oci_key_file),
                              ("OCI_INSTANCE_OCID", self.oci_instance_id)):
                if not val:
                    problems.append(f"{name} unset (required in LIVE mode on OCI)")
            if self.oci_key_file and not os.path.isfile(self.oci_key_file):
                problems.append(f"OCI_KEY_FILE {self.oci_key_file!r} does not exist")
            if not self.oci_instance_ip and not self.oci_compartment_id:
                problems.append("set OCI_INSTANCE_IP (preferred) or OCI_COMPARTMENT_OCID "
                                "(VNIC-attachment IP lookup)")
            if self.oci_stop_action not in ("SOFTSTOP", "STOP"):
                problems.append(f"OCI_STOP_ACTION={self.oci_stop_action!r} must be SOFTSTOP or STOP")
        if not self.link_token:
            problems.append("DEMO_LINK_TOKEN unset (anyone could wake the droplet)")
        if self.business_end_hour <= self.business_start_hour:
            problems.append("DEMO_BUSINESS_END_HOUR must be > DEMO_BUSINESS_START_HOUR")
        return problems


CONFIG = Config()
