"""Cloud-provider selection for the broker's control plane (`DEMO_CLOUD`).

One tiny factory, same shape as `dial.make_dial`. The broker talks to whichever
client this returns through a four-method provider-neutral protocol — the only
cloud calls it makes:

    wake() -> compute_id        bring the compute up  (DO: create droplet from
                                snapshot · OCI: instance action START)
    sleep(compute_id) -> None   take the compute down (DO: destroy droplet, keep
                                volume · OCI: instance action SOFTSTOP)
    compute_ip(compute_id)      address to /health-poll and reverse-proxy to
    compute_active(compute_id)  provider-side "running" (NOT app /health-ready)

`DEMO_CLOUD` defaults to **do**, so nothing changes for the existing DO deploy
until it is flipped to `oci`. DO→OCI mapping table:
`docs/deprecated/oci_demo/OCI_DEMO_DEPLOYMENT.md` §4.

Semantic difference worth remembering: on DO the compute id is *created* state
(None when destroyed); on OCI the instance always exists and its OCID is static
config (`OCI_INSTANCE_OCID`) — the broker's stored id means only "the compute is
supposed to be up", and `sleep("")` still targets the configured OCID.
"""
from __future__ import annotations


class CloudError(RuntimeError):
    """Unknown/unusable cloud provider selection."""


def make_cloud_client(config):
    """Build the cloud client `DEMO_CLOUD` asks for (do|oci)."""
    kind = (getattr(config, "cloud", "do") or "do").strip().lower()
    if kind == "do":
        from do_client import DOClient
        return DOClient(config)
    if kind == "oci":
        from oci_client import OCIClient
        return OCIClient(config)
    raise CloudError(f"unknown DEMO_CLOUD {kind!r} (do|oci)")
