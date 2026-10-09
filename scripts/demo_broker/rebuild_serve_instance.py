#!/usr/bin/env python3
"""Rebuild the OCI serve instance from its preserved boot volume + index volume.

Oracle terminated the E5.Flex serve instance at the end of the trial grace
period (2026-10-03) but left `SFU-thin-serverhosted-150M (Boot Volume)`,
`sfu-demo-idxvol`, the VCN/subnet, the `sfu-serve-locked` NSG and the reserved
public IP `sfu-demo-public-ip` in place. This launches a new instance from that
boot volume on the same private IP, re-attaches the index volume
(paravirtualized), re-assigns the reserved public IP, and prints the new
instance OCID for `OCI_INSTANCE_OCID` in the broker's demo.env.

Run on the broker box, from the broker directory (it reuses the broker's own
request signing; no `oci` SDK):

    python3 rebuild_serve_instance.py                     # plan + preflight only
    python3 rebuild_serve_instance.py --execute           # launch (starts billing)
    python3 rebuild_serve_instance.py --execute --write-env   # + update demo.env
    python3 rebuild_serve_instance.py --execute --hand-to-broker --notify   # unattended

Needs a pay-as-you-go tenancy: on a free/expired-trial tenancy the E5 core
limit is 0 and the preflight refuses (exit 2, nothing changed). The launched
instance is RUNNING and billed until it is stopped, and the broker only tracks
compute it believes it woke — so `--hand-to-broker` (what the unattended
trigger `rebuild_trigger.sh` uses) writes the new OCID into the env file,
restarts `sfu-broker`, and records the launch in the broker state as an
on-demand wake the moment the launch call returns. From then on the broker's
idle reaper and daily/monthly killswitches bound the spend even if a later
step here fails. It then attaches the index volume and soft-reboots the guest
so it comes up with the volume mounted. `rebuild.launched` (the new OCID) is
written right after the launch call so the trigger never launches twice.

MEASURED 2026-10-06 (one real run via the trigger, 19:45 UTC): launch to
RUNNING 30 s, attach 20 s, whole script 57 s, serve /health ~2 min after the
launch call — table in README.md, section "2026-10-06 revival".
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BOOT_VOLUME_NAME = "SFU-thin-serverhosted-150M (Boot Volume)"
INDEX_VOLUME_NAME = "sfu-demo-idxvol"
NSG_NAME = "sfu-serve-locked"
PUBLIC_IP_NAME = "sfu-demo-public-ip"
INSTANCE_NAME = "SFU-thin-serverhosted-150M"
LAUNCHED_MARKER = "rebuild.launched"
SHAPE = "VM.Standard.E5.Flex"
CORE_LIMIT = "standard-e5-core-count"
MEMORY_LIMIT = "standard-e5-memory-count"


def load_env(path: str) -> None:
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k] = v.split(" #")[0].strip()


def q(s: str) -> str:
    return urllib.parse.quote(s, safe="")


class Api:
    def __init__(self, client, cfg):
        self.c, self.cfg = client, cfg
        self.core = f"https://iaas.{cfg.oci_region}.oraclecloud.com/20160918"
        self.limits = f"https://limits.{cfg.oci_region}.oci.oraclecloud.com/20190729"

    def call(self, method: str, url: str, body: dict | None = None):
        from oci_client import sign_headers
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in sign_headers(method, url, data, key_id=self.c.key_id,
                                 private_key=self.c._private_key()).items():
            req.add_header(k, v)
        req.add_header("accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise SystemExit(f"OCI {method} {url.split('?')[0]} -> {e.code}: "
                             f"{e.read().decode(errors='replace')[:600]}")

    def one(self, path: str, name: str, what: str) -> dict:
        hits = [x for x in self.call("GET", f"{self.core}{path}")
                if x.get("displayName") == name
                and x.get("lifecycleState") not in ("TERMINATED", "TERMINATING")]
        if len(hits) != 1:
            raise SystemExit(f"expected exactly one {what} named {name!r}, found {len(hits)}")
        return hits[0]

    def wait(self, path: str, want: str, timeout_s: int = 900) -> dict:
        t0 = time.time()
        while True:
            r = self.call("GET", f"{self.core}{path}")
            state = r.get("lifecycleState")
            print(f"  {path.split('/')[1]}: {state} ({time.time() - t0:.0f}s)", flush=True)
            if state == want:
                return r
            if state in ("TERMINATED", "TERMINATING", "FAULTY") or time.time() - t0 > timeout_s:
                raise SystemExit(f"gave up waiting for {want}: {state}")
            time.sleep(10)


def write_env_ocid(env_file: str, iid: str) -> None:
    backup = f"{env_file}.bak-pre-rebuild-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(env_file, backup)
    lines = open(env_file).read().splitlines()
    lines = [f"OCI_INSTANCE_OCID={iid}" if ln.startswith("OCI_INSTANCE_OCID=") else ln for ln in lines]
    open(env_file, "w").write("\n".join(lines) + "\n")
    print(f"{env_file} updated (backup {backup})")


def hand_to_broker(cfg, iid: str) -> None:
    """Make the running broker own this launch: its reaper/killswitches now apply."""
    subprocess.run(["sudo", "-n", "systemctl", "restart", "sfu-broker"], check=True)
    time.sleep(5)
    from state import StateStore
    store = StateStore(cfg.state_path)
    store.mark_booting(iid)
    store.set_on_demand(True)
    print("broker restarted on the new OCID; launch recorded as an on-demand wake")


def tell(cfg, enabled: bool, title: str, message: str) -> None:
    print(f"{title}: {message}")
    if enabled:
        from notify import notify
        notify(cfg, title, message)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default="demo.env")
    ap.add_argument("--ocpus", type=float, default=8)
    ap.add_argument("--memory-gb", type=float, default=64)
    ap.add_argument("--private-ip", default="", help="default: OCI_INSTANCE_IP from the env file")
    ap.add_argument("--ssh-authorized-key", default="",
                    help="public key line for the ubuntu user (the boot volume already carries one)")
    ap.add_argument("--execute", action="store_true", help="launch for real (starts billing)")
    ap.add_argument("--write-env", action="store_true",
                    help="after launch, rewrite OCI_INSTANCE_OCID in the env file (backup kept)")
    ap.add_argument("--hand-to-broker", action="store_true",
                    help="implies --write-env; restart sfu-broker and record the launch as an "
                         "on-demand wake, then soft-reboot the guest once the volume is attached")
    ap.add_argument("--notify", action="store_true", help="push the outcome through the broker notifier")
    args = ap.parse_args()

    load_env(args.env_file)
    from cloud import make_cloud_client
    from config import CONFIG
    api = Api(make_cloud_client(CONFIG), CONFIG)
    comp = CONFIG.oci_compartment_id or CONFIG.oci_tenancy_ocid
    private_ip = args.private_ip or CONFIG.oci_instance_ip
    cq = f"compartmentId={q(comp)}"

    boot = api.one(f"/bootVolumes?{cq}", BOOT_VOLUME_NAME, "boot volume")
    vol = api.one(f"/volumes?{cq}", INDEX_VOLUME_NAME, "index volume")
    nsg = api.one(f"/networkSecurityGroups?{cq}", NSG_NAME, "NSG")
    pub = api.one(f"/publicIps?scope=REGION&lifetime=RESERVED&{cq}", PUBLIC_IP_NAME, "reserved public IP")
    subnets = api.call("GET", f"{api.core}/subnets?{cq}")
    if len(subnets) != 1:
        raise SystemExit(f"expected one subnet, found {len(subnets)}")
    subnet, ad = subnets[0], boot["availabilityDomain"]

    problems = []
    if boot["lifecycleState"] != "AVAILABLE" or vol["lifecycleState"] != "AVAILABLE":
        problems.append(f"volumes not AVAILABLE: boot={boot['lifecycleState']} index={vol['lifecycleState']}")
    if api.call("GET", f"{api.core}/bootVolumeAttachments?{cq}&availabilityDomain={q(ad)}"
                       f"&bootVolumeId={q(boot['id'])}"):
        problems.append("the boot volume is already attached to an instance")
    if any(x.get("displayName") == INSTANCE_NAME and x.get("lifecycleState") != "TERMINATED"
           for x in api.call("GET", f"{api.core}/instances?{cq}")):
        problems.append(f"an instance named {INSTANCE_NAME!r} already exists")
    if api.call("GET", f"{api.core}/privateIps?subnetId={q(subnet['id'])}&ipAddress={q(private_ip)}"):
        problems.append(f"private IP {private_ip} is already in use")
    if pub.get("lifecycleState") != "AVAILABLE":
        problems.append(f"reserved public IP is {pub.get('lifecycleState')}, not AVAILABLE")
    for limit, need in ((CORE_LIMIT, args.ocpus), (MEMORY_LIMIT, args.memory_gb)):
        avail = api.call("GET", f"{api.limits}/services/compute/limits/{limit}/resourceAvailability"
                                f"?compartmentId={q(CONFIG.oci_tenancy_ocid)}&availabilityDomain={q(ad)}")
        if (avail.get("available") or 0) < need:
            problems.append(f"{limit}: available {avail.get('available')} < {need} "
                            "(tenancy not pay-as-you-go yet?)")

    print(f"plan: launch {SHAPE} {args.ocpus:g} OCPU / {args.memory_gb:g} GB in {ad}")
    print(f"  boot volume   {boot['displayName']} ({boot['sizeInGBs']} GB)")
    print(f"  index volume  {vol['displayName']} ({vol['sizeInGBs']} GB), paravirtualized")
    print(f"  private IP    {private_ip} in {subnet['displayName']}, NSG {nsg['displayName']}")
    print(f"  public IP     {pub['ipAddress']} ({pub['displayName']})")
    for p in problems:
        print(f"PREFLIGHT FAIL: {p}")
    if problems:
        return 2
    if not args.execute:
        print("preflight OK — re-run with --execute to launch (starts billing)")
        return 0

    body = {
        "availabilityDomain": ad,
        "compartmentId": comp,
        "displayName": INSTANCE_NAME,
        "shape": SHAPE,
        "shapeConfig": {"ocpus": args.ocpus, "memoryInGBs": args.memory_gb},
        "sourceDetails": {"sourceType": "bootVolume", "bootVolumeId": boot["id"]},
        "createVnicDetails": {"subnetId": subnet["id"], "privateIp": private_ip,
                              "assignPublicIp": False, "nsgIds": [nsg["id"]]},
    }
    if args.ssh_authorized_key:
        body["metadata"] = {"ssh_authorized_keys": args.ssh_authorized_key}
    inst = api.call("POST", f"{api.core}/instances", body)
    iid = inst["id"]
    open(LAUNCHED_MARKER, "w").write(iid + "\n")
    print(f"launched {iid}")
    try:
        if args.write_env or args.hand_to_broker:
            write_env_ocid(args.env_file, iid)
        if args.hand_to_broker:
            hand_to_broker(CONFIG, iid)
        api.wait(f"/instances/{q(iid)}", "RUNNING")

        att = api.call("POST", f"{api.core}/volumeAttachments",
                       {"type": "paravirtualized", "instanceId": iid, "volumeId": vol["id"],
                        "displayName": f"{INDEX_VOLUME_NAME}-attach"})
        api.wait(f"/volumeAttachments/{q(att['id'])}", "ATTACHED")

        pips = api.call("GET", f"{api.core}/privateIps?subnetId={q(subnet['id'])}&ipAddress={q(private_ip)}")
        api.call("PUT", f"{api.core}/publicIps/{q(pub['id'])}", {"privateIpId": pips[0]["id"]})
        print(f"public IP {pub['ipAddress']} -> {private_ip}")

        if args.hand_to_broker:
            api.call("POST", f"{api.core}/instances/{q(iid)}?action=SOFTRESET")
            print("SOFTRESET issued so the guest boots with the index volume attached")
    except (SystemExit, Exception) as e:
        tell(CONFIG, args.notify, "Duck Library serve rebuild INCOMPLETE",
             f"instance {iid[-8:]} was launched and is billed, but a later step failed: {str(e)[:300]}")
        raise

    print(f"OCI_INSTANCE_OCID={iid}")
    if args.hand_to_broker:
        tell(CONFIG, args.notify, "Duck Library serve box rebuilt",
             f"{SHAPE} {args.ocpus:g}/{args.memory_gb:g} launched from the preserved disks and handed "
             f"to the broker (idle stop {CONFIG.idle_minutes} min, monthly cap "
             f"{CONFIG.max_runtime_hours_per_month:g} h)")
    else:
        print("the instance is RUNNING and billed and the broker is NOT tracking it: the index volume "
              "was attached after boot, so stop + start it once, verify /health, then leave it stopped")
    return 0

if __name__ == "__main__":
    sys.exit(main())
