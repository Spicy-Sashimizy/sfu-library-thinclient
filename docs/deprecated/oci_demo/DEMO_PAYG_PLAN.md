# Demo post-trial plan — keep the invite links usable on PAYG after 2026-09-03

> **CLOSED DEAD 2026-09-25** — cloud access ended: there is no tenancy left to move to PAYG; the whole §6 open-items ledger is unrunnable. Serving is local-WSL2-only — see `docs/THIN_CLIENT_SWAP.md` §"What runs here now". Kept as a deployment record; not current.

**Status:** CLOSED DEAD 2026-09-25

> **STATUS 2026-09-25: CLOUD ACCESS ENDED**
>
> The operator no longer has access to any cloud instances. The OCI E5 62 GiB
> demo host is gone and any DigitalOcean droplets are gone; neither will return.
> The demo broker (`scripts/archive/demo_broker/`) is therefore **dormant** — the code is
> kept, but there is no instance for it to start, stop, pin, or reap.
>
> Every open item in this doc is **CLOSED-UNRUNNABLE**, not pending — there is no
> host left to run it on. That covers the whole §6 ledger: the **tenancy-upgrade
> decision**, the **killswitch 25 h cap test**, the **idle-stop threshold
> choice**, the **cold-store sync** (nothing left to exit from), the **NAS-specs
> option C** evaluation, and the **A1/aarch64 feasibility check**. The PAYG /
> scale-to-zero / scale-to-free options (§1–§5) are moot for the same reason.
>
> All work from 2026-09-25 onward runs on the **local WSL2 host only** (31 GB
> RAM, 16 cores, kernel 6.18 WSL2, MGLRU enabled, cgroup v2). Read everything
> below as history and design rationale, not as a runnable plan.

**Status: PLANNING (2026-09-01). Decision owner: user. The tenancy-upgrade
decision must land before 2026-09-03 (trial expiry).** Costs below marked
**measured** come from `data/eval_results/oci_billing_20260901/` (commit
`ba073c3b`); everything else is *est.*

## 0. What expiry does if nothing is decided

- The E5.Flex serve box and its 196 GB index volume are **trial-credit
  resources**: at expiry they stop billing-eligibility and are reclaimed
  (OCI policy: paused at expiry, deleted after a grace period — *est.
  ~30 days, verify in console before relying on it*).
- **Always-free resources survive** on the free account: the landing/broker
  box keeps running, so the links themselves keep resolving — they would
  just have nothing to wake.
- Net: without action, demo dead on 2026-09-03; with only option B (cold
  store) done, demo dead but rebuildable.

## 1. Option A — PAYG upgrade + scale-to-zero (RECOMMENDED; mechanics already built)

Upgrade the tenancy to pay-as-you-go (console, card on file; upgrading
itself costs nothing and removes the expiry). Then run the demo in the
scale-to-zero mode the broker was designed for
(`docs/deprecated/oci_demo/OCI_DEMO_DEPLOYMENT.md` §3–4, live-validated
2026-08-20): box **stopped by default** (a stopped OCI VM bills storage
only — measured CAD 0.359/day), broker `instance action START` on invite
click, killswitch stops it after idle.

Measured cost model:

| State | Cost |
|---|---|
| Idle floor (box stopped, volume kept) | **CAD 0.359/day ≈ 10.9/mo** (measured) |
| Hot runtime | **CAD 0.482/hr** (measured) |
| Cold visit (boot→warm ~23 min) | **CAD 0.185/visit** (measured) |
| Reference: 24/7 always-on | CAD 11.93/day ≈ 358/mo (measured) |

Example envelopes (*est.*): 2 h hot/day ≈ CAD 40/mo; weekday
business-hours (8 h × 22 d) ≈ CAD 96/mo; museum-piece (a few visits/mo)
≈ CAD 12–15/mo.

Work items (most already pending in the campaign):
1. User: tenancy upgrade in console (before 2026-09-03).
2. Killswitch-trigger test (the pending 25 h cap item) — the budget
   backstop must be proven before unattended PAYG.
3. Idle-stop policy: pick idle-minutes threshold (broker already tracks
   `idle_minutes`; current session shows the plumbing live).
4. Landing-page boot UX is already built (warmup status surfaced).

## 2. Option B — TrueNAS as COLD STORE (do regardless, pairs with A)

One-time (then periodic) sync of `/mnt/idxvol` payload + web build
(~126 GB) to the TrueNAS box. Free (local disk + electricity).

- **Yes as disaster recovery / exit insurance:** if OCI is ever dropped or
  the volume lost, the demo is rebuildable without re-deriving from the
  dev tree. Replaces an OCI Object Storage backup (*est.* ~CAD 5/mo
  avoided).
- **No as a launch-time data source:** restoring 126 GB from a
  residential uplink per wake is hours-to-days — incompatible with a
  23 min boot budget. The block volume's CAD 0.36/day is what buys the
  fast wake; keep it.
- Initial sync before 2026-09-03 uses OCI's egress while the box is
  free-to-run (egress first 10 TB/mo free — *est.*, verify); bandwidth
  bound by the NAS's downlink.

## 3. Option C — TrueNAS as LAUNCH SITE (serve the demo from the NAS)

Serve the thin-client stack from TrueNAS SCALE (Linux, containers) behind
a Cloudflare tunnel (pattern already proven for ntfy). Cost ≈ 0.

- RAM reality: full two-population footprint is 29.1 GB (measured), but
  the smallmachine-levers spike (phase A′ running 2026-09-01) is testing
  exactly the levers — no-residue load + warmup — that shrink the serving
  need toward the 13.8 GB hot set + ~1 GB anon. If S1 passes, ~16–20 GB
  of free NAS RAM serves the full 150M index (*est.* until phase B).
- **NAS specs (measured over SSH 2026-09-02):** x86_64, 4 cores, 23 GiB
  RAM with only ~6 GiB available (apps resident), ~1.9 TB free on MAIN
  (existing `MAIN/sfu-library-mcp` dataset). Consequence: parallel
  serving (needs ≥25 GB cold) is OUT; option C is viable ONLY in
  sequential-federation mode (WI-1 measured peak RssFile 0.023× parallel
  ≈ sub-GB; warm p50 5.29×) — decided by the phase A″ L4/L41 cells.
  Still needed from user: uplink bandwidth, and whether ~6 GiB may be
  reserved for a serving container.
- Broker fit: `DEMO_CLOUD` abstraction exists (do|oci); a "local/NAS"
  driver (wake = nothing or container start) is new but small code.
- Role if adopted: default tier for casual visits (free, always-warm),
  with OCI PAYG as the burst/fallback tier. Availability caveat: home
  power/network becomes demo uptime.

## 4. Option D — OCI always-free A1 (ARM, 4 OCPU / 24 GB) — park for later

This resurrects the shelved `OCI_FREE_TIER_RESIDENT_DEMO.md` design
(operator-shelved 2026-08-18 in favor of the x86 plan) with two things
that have changed since: the levers spike may shrink the serving
footprint into 24 GB, and its WI-3 memory dial (`scripts/archive/demo_broker/dial.py`)
was already built. Free forever, survives on a free account. 24 GB < 29.1 GB footprint but
> the 14.8 GB hot-set floor, so it is viable **only** with the L1/warmup
levers (in measurement now) **and** an aarch64 rebuild of the seismic
`.so` (nontrivial — x86-64-v3 is the current portability target). Also
the phone-ISA stepping stone for the Stage-2 stretch goal. Post-trial
experiment; do not block the 09-03 decision on it.

## 5. Recommendation

1. **Now:** Option A tenancy upgrade (reversible, idle floor ~CAD 11/mo)
   — this alone keeps the links alive on PAYG.
2. **Before 09-03 regardless of A:** Option B initial cold-store sync
   (exit insurance while egress is free-tier).
3. **After the levers spike lands:** evaluate C (NAS default tier) and D
   (A1 free tier) with measured lever numbers; either can later demote
   the E5 box to burst-only and cut the recurring cost toward zero.

## 6. Open items ledger

| Item | Owner | Deadline |
|---|---|---|
| Tenancy upgrade decision | user | 2026-09-03 |
| Killswitch 25 h cap test | session | before unattended PAYG |
| Cold-store sync to TrueNAS | session (needs NAS reachable/ssh) | before 2026-09-03 |
| NAS specs (CPU/RAM/disk/uplink) for option C | user | when convenient |
| Idle-stop threshold choice | user | with A |
| A1/aarch64 feasibility check | session | post-trial |
