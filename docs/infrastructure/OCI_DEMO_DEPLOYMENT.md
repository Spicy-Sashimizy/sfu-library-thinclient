# OCI demo deployment — free-tier landing box + scale-to-zero 150M compute

**Status:** ACTIVE (reopened 2026-10-06; closed 2026-09-25 → 2026-10-06)

> **REOPENED 2026-10-06** (was CLOSED DEAD 2026-09-25): the owner upgraded the tenancy to Pay As You Go on
> 2026-10-06; the serve instance was rebuilt from its preserved disks, click-wake and the one-hour stop are
> measured (`scripts/demo_broker/README.md` §"2026-10-06 revival"), and this doc is live again. The
> 2026-09-25 closure text that follows is kept as the record of that closure.
>
> **CLOSED DEAD 2026-09-25 (record)** — cloud access ended: the OCI E5 62 GiB host and every DigitalOcean droplet are gone and will not return; nothing replaces the public demo. Serving is local-WSL2-only — see `docs/THIN_CLIENT_SWAP.md` §"What runs here now". Kept as a deployment record; not current.

> **UPDATE 2026-10-06 (written before the upgrade landed; see the REOPENED banner above).** The owner is upgrading the OCI
> tenancy to Pay As You Go. Verified over the API on 2026-10-06: the tenancy still exists (still
> `FREE_TRIAL`, E5 core limit 0 at the time of writing); the Always-Free broker box is RUNNING and
> serving `/health`; Oracle TERMINATED the E5 serve instance on 2026-10-03 (end of the grace period)
> but kept its 100 GB boot volume, the 200 GB `sfu-demo-idxvol`, the VCN/subnet, the `sfu-serve-locked`
> NSG and the reserved public IP. So the "gone for good / no tenancy left" statements below were wrong
> about the tenancy, the broker box and the disks. The live broker was switched the same day to
> click-only wake (`DEMO_BUSINESS_DAYS=` empty), 60 min idle stop, unpinned, 10 h/day and **55 h/month**
> runtime caps (the owner's CAD 40/month ceiling), and a self-disabling timer on the broker box
> (`rebuild_trigger.sh`) rebuilds the serve instance from the preserved disks as soon as the upgrade
> lands. **It landed and the trigger fired 2026-10-06 19:45 UTC: the tenancy is Pay As You Go, the E5
> serve instance is rebuilt from the preserved disks, serving, and under the broker's reaper and caps**
> (measured numbers in the README named below). The first invite-click wake and the first real idle
> stop are not measured yet — this track stays CLOSED in the index until the commit that records
> them, which also moves these docs and `scripts/demo_broker/` out of the closed trees. Details:
> `scripts/demo_broker/README.md` §"2026-10-06 revival".

> **STATUS 2026-09-25: CLOUD ACCESS ENDED**
>
> The operator no longer has access to any cloud instances. The OCI E5 62 GiB
> demo host described below is **gone and will not return** (nor will any
> DigitalOcean droplet), so the public demo, its invite links, the broker VM,
> the watchdog timer and the ntfy alerting on it are **no longer running**. The
> demo broker (`scripts/demo_broker/`) is **dormant** — the code is kept, but
> there is no instance for it to start, stop, pin, reap, or watch. Everything
> below dated 2026-08/2026-09 (including the "RUNNING", "DEPLOYED LIVE", "24/7
> schedule", `DEMO_PIN_RUNNING=1` and watchdog-alerting status lines) describes
> a system that no longer exists.
>
> Every remaining item is **CLOSED-UNRUNNABLE**, not pending — there is no host
> left to run it on: the **killswitch 25 h-cap trigger test** (§9 Phase 4/5),
> the **WI-12 soak bar (a) re-run**, the **idle-stop threshold** choice, the
> **tenancy upgrade to Pay As You Go** (`DEMO_PAYG_PLAN.md`), and **Phase 6**.
> The §11 invite-minting runbook and the §10 dry-run measurements are history.
>
> All work from 2026-09-25 onward runs on the **local WSL2 host only** (31 GB
> RAM, 16 cores, kernel 6.18 WSL2, MGLRU enabled, cgroup v2). Read everything
> below as history and design rationale, not as a runnable plan.

**Date:** 2026-08-06 · **Status:** ADOPTED (operator, 2026-08-18, x86) —
**DEPLOYED LIVE 2026-08-20**, public at `demo.vancitylandscaper.com`
2026-08-21, **24/7 schedule since 2026-08-21** · **Trial ENDED 2026-09-04** (not
upgraded; grace period to 2026-10-03). **Status 2026-09-07:** the E5 box is
grandfathered and still RUNNING, but the tenancy's `standard-e5-core-count`
limit is now 0 (used 8), so any stop is permanent — a START would be refused.
Broker runs with `DEMO_PIN_RUNNING=1` (never issues a stop) until an upgrade
to Pay As You Go or Oracle's reclamation. Metered cost since 2026-09-04: CAD 0.
`watchdog.py` (systemd timer on the Micro, 5 min) pushes to ntfy if the
instance leaves RUNNING or the serve/broker health fails, plus a daily heartbeat.

Goal: a public tech demo of the **full 150M thin-client stack**, CPU-only,
on Oracle Cloud — heavy compute billed **only while a visitor session runs**
(later flipped to 24/7 by owner request, §9 Phase 3).

The resident free-tier ARM alternative (`OCI_FREE_TIER_RESIDENT_DEMO.md`) is
**SHELVED** — its aarch64 ports are not pursued; its WI-3 cgroup `MemoryHigh`
dial IS adopted. This doc supersedes `HYBRID_DEMO_DEPLOYMENT.md` (DO plan,
DEPRECATED) for the cloud/wake/cost layer and reuses its engine-independent
parts: the broker (`scripts/demo_broker/`), token landing + waiting room +
idle reaper + killswitch, the abstract live-fetch decision, the int8 rerank
research. Sizing draws on `docs/archive/bmp_decommission_plan/DO_SIZING.md`; current
warm numbers are `DEMO_DEPENDABILITY.md` §WI-7. Broker/dial code constraints:
`docs/CODE_INVARIANTS_SCRIPTS.md`. Numbers marked *est.* are list-price
extrapolations; payload sizes and list prices below were measured/confirmed
2026-08-06 unless dated otherwise.

---

## 0. Why OCI

**A stopped OCI VM pauses compute (OCPU + memory) billing; you pay only for
storage. `START` on click.** (OCI docs, *Resource Billing for Stopped
Instances*.) So scale-to-zero = STOP one persistent instance — no
destroy/re-seed as on DO, where a droplet bills until destroyed. Boot +
block volume persist across stops: wake = boot + warm (~2–4 min planned;
87 s measured), not boot + copy 108 GB.

> ⚠ Stop via the OCI Console/API/SDK, *not* a guest-OS `shutdown` — an
> OS-level shutdown leaves the instance billed.

---

## 1. Architecture — the two-box split

```
invite link ─▶ https://demo.<domain>/start?t=<token>
                     │  (always-on, FREE — E2.1.Micro 1 GB)
                     ├─ validate token (rejects drive-bys → protects credit)
                     ├─ single-flight: OCI instance action START  (150M box)
                     ├─ waiting-room page polls the 150M box /health
                     └─ when warm: reverse-proxy the stable URL ─▶ 150M box :8080
                                          │
   idle reaper (free box): no queries for N min ─▶ instance action STOP
   hard killswitch (cron): daily runtime cap    ─▶ force STOP (budget backstop)
```

| Box | Always on? | Cost | Job |
|---|---|---|---|
| **Landing/broker** | Yes | **$0** (Always-Free E2.1.Micro 1 GB; broker <256 MB) | landing page, stable URL, START on valid token, /health poll, reverse proxy, idle reap, killswitch |
| **150M instance** | STOPped between sessions (24/7 since 2026-08-21) | billed START→STOP | boots on trigger, warms hot set, serves federated search + CPU rerank |

---

## 2. Instance sizing

> **SUPERSEDED NUMBERS 2026-08-19:** this table is the 2026-08-06
> measurement — the real manifest run measured **126.33 GB / 872 files**
> (`sections/` grew to 56.13 GB after the 2026-08-17 flat abstract sidecar;
> both abstract stores ship; `--sqlite-free-abstracts` = 112.86 GB). Current
> numbers: §8/§9 and `scripts/data/demo_payload_manifest.json`. 126.33 GB is
> tight on a 150 GB volume (a 200 GB volume was provisioned).

| Component | Size (2026-08-06) | Notes |
|---|---|---|
| SEISMIC served shards (`*.dotvbyte.e5.v2.mmap`, 8) | 42 GB | the E8 dv-v2 set |
| `meta.sqlite` | 24 GB | filter + hydrate |
| `sections/` (tantivy + hot-section abstract sidecar) | 42 GB | |
| `dense/` | 0.357 GB | **OPTIONAL — EXCLUDED by default** (ablation DROP verdict 2026-08-18; `SFU_DENSE_LEG` default OFF; serving verified safe with no `dense/`; the v5 query encoder is shared with embed-rerank and stays regardless). Evidence: `DENSE_PARTITION_AND_ABLATION.md` |
| **Served total** | ~108 GB | + code + models + venv ≈ ~120 GB upload |

RAM model (`docs/archive/bmp_decommission_plan/DO_SIZING.md`, engine-updated): disk holds the index; RAM governs
latency — full-150M fitting tier wants **≥64 GB**.

| Shape | Configuration | Native module | Verdict |
|---|---|---|---|
| VM.Standard.E4.Flex | 8 OCPU/64 GB | portable `seismic_x86_64_v3.so`, no recompile | recommended in the 2026-08-06 plan |
| VM.Standard.E5.Flex | 8 OCPU/64 GB | same `.so` | **what actually runs (2026-08-20): E4/E3 were OUT_OF_HOST_CAPACITY in ca-toronto-1; E5 ~$0.336/hr** |
| VM.Standard.A1.Flex (ARM) | 8 OCPU/64 GB | needs an aarch64 `.so` build (not built) | cheaper once built |

- **Index on local block volume (NVMe-backed), never OCI File Storage/NFS**
  — the 9p lesson (`THIN_CLIENT_SWAP.md`): SEISMIC mmaps the forward index;
  on local disk a cold-tail query faults ~2.5–3.9 s once then holds warm, versus
  8–17 s re-faulting on a network FS.
- `scripts/serve_http.sh` under systemd; `SFU_SEISMIC_FEDERATION` is
  FS-aware (parallel on native disk).

---

## 3. Scale-to-zero mechanics

| Phase | State | Billed? |
|---|---|---|
| Between sessions | STOPped | compute NO / storage yes |
| Broker fires START | provisioning → running | yes, from here |
| Boot (~60–90 s) + warmup (~1–2 min) | running, not yet serving | yes |
| Serving | running | yes |
| Idle N min → reaper STOP | stopping → stopped | compute ends |

The billed window is the whole running period, so the real cost unit is
**per cold visit** (§5).

---

## 4. Broker: DO → OCI call mapping

Everything except the cloud-control calls is reused (token landing, waiting
room, /health poll, proxy, single-flight lock, reaper, killswitch,
`mint_invite.py`, ntfy). STOP/START replaces create/destroy + re-seed.

| Broker action | DO (old) | OCI (new) |
|---|---|---|
| Wake | create droplet from snapshot + attach volume | `instance action START` (instance persists) |
| Sleep | **destroy** droplet (keep volume) | `instance action STOP` |
| Persist index | detach/re-attach volume | volumes simply persist |
| Firewall | DO firewall | NSG: `:8080` from broker private IP only |
| Health gate / killswitch | unchanged | unchanged |

Auth unchanged: bearer token on `/mcp` + secret hostname; Zotero-write
blocked at the proxy.

### 4.1 Port status — BUILT 2026-08-19; live-validated 2026-08-20

`scripts/demo_broker/oci_client.py` (draft-cavage RSA-SHA256 signing over
`(request-target) date host` + content headers on POST; stdlib +
`cryptography`, deliberately NOT the `oci` SDK on the 1 GB broker box;
configuration from `OCI_*` environment only, never `~/.oci`), `cloud.py` factory on
**`DEMO_CLOUD` (default `do`)**, broker-neutral protocol
`wake()/sleep()/compute_ip()/compute_active()`. Environment:
`OCI_TENANCY_OCID`, `OCI_USER_OCID`, `OCI_FINGERPRINT`, `OCI_KEY_FILE`,
`OCI_KEY_PASSPHRASE`, `OCI_REGION` (default `ca-toronto-1`),
`OCI_INSTANCE_OCID`, `OCI_INSTANCE_IP`, `OCI_COMPARTMENT_OCID`,
`OCI_STOP_ACTION` — see `demo.env.example`; validated only when
`DEMO_CLOUD=oci` AND LIVE. Tests: `test_oci_client.py` 33 mocked tests;
broker suite 83 passed 2026-08-19. First live call 2026-08-20: read-only
signed GET vnicAttachments → HTTP 200.

OCI-specific semantics: the instance is static configuration (killswitch fires
even after broker state loss — `sleep("")` still targets
`OCI_INSTANCE_OCID`); `instance_ip()` short-circuits to `OCI_INSTANCE_IP`
(zero API calls per proxied request), VNIC lookup is the fallback; unknown
lifecycle states count as down → idempotent re-START.

---

## 5. Cost model

List prices (confirmed 2026-08-06): E4.Flex $0.0255/OCPU-hr +
$0.0015/GB-hr → **~$0.30/hr at 8/64** ($0.15 at 4/32); A1 ≈ $0.22/hr at
8/64; block volume ≈ $0.0255/GB-mo. The deployed E5.Flex runs
**~$0.336/hr USD** (measured billed rate CAD 0.4823/instance-hr, §10).

**Standing storage — billed 24/7 whether running or stopped:**
~150 GB block volume ≈ ~$4–6/mo *est.* (verify at deploy).
> **CORRECTED 2026-09-01 (billed lines, Usage API):** the 200 GB Always-Free
> block allotment went to the two BOOT volumes (~141 GB); the 200 GB
> `sfu-demo-idxvol` is billed in full — **CAD 0.359/day ≈ CAD 11/mo**,
> accruing even while the instance is stopped. The scale-to-zero floor is
> therefore CAD 0.36/day, not $0. The free landing box: **$0** (confirmed
> billed CAD 0.00 across 269.9 OCPU-hours). Evidence:
> `data/eval_results/oci_billing_20260901/`.

**Per cold visit** — boot + warm + usage + idle-hold: at a 20-min idle
timeout, minimum billed session ≈ 25 min ≈ **$0.12–0.15** (plan est.;
billed-line verified 2026-09-01 at **USD 0.129 / CAD 0.185**, §10).
Mitigations: token-gated START, idle timeout, single-flight lock.

Illustrative 30-day scale-to-zero run (~8 h/day up): ~240 h × $0.30 ≈ ~$72
compute + ~$5 storage — inside the $300 credits.

---

## 6. Free tier — two different things

- **$300 credits, 30 days.** VERIFIED live 2026-08-20 on the owner's tenancy:
  `paymentModel: FREE_TRIAL`, window **2026-08-05 → 2026-09-03** (Oracle's
  own offer; DO's trial is $200). ~$0.30/hr ⇒ $300 ≈ ~1,000 instance-hours.
- **Always Free (forever).** ⚠ Oracle cut the free Ampere allotment
  4 OCPU/24 GB → **2 OCPU/12 GB in June 2026**. Current: 2 OCPU/12 GB A1 +
  200 GB block + 2× E2.1.Micro (1 GB). Runs the broker forever; 12 GB
  cannot hold the 64 GB stack, and ARM needs the aarch64 `.so`.

(Optional elegance, not the plan: serve an instant `social_sciences` subset
off the free A1 while the 150M warms — needs the aarch64 build.)

---

## 7. Warm-up — what actually gets warm

No 108 GB preload. On START the warmup battery (`SFU_HTTP_WARMUP`, 6
subject-diverse queries) + prefault-hotset fault the hot working set
resident (~3.07 GB hot-set-80; ~16 GB full SEISMIC working set); measured
prefault effect: cold p95 **4.66 s → 1.67 s (~2.8×)** (disk_streaming F6).
The rest pages on demand from local NVMe (one-time ~2.5–3.9 s cold-tail
faults). CPU rerank is a non-issue: torch CE scores the 20-pair batch in
**25.5 ms p50** on 16 cores (2026-08-19,
`data/eval_results/ce_v1_inversion_check_20260819_1920.json`); the int8
ONNX export's 19× was per-pair batch=1 and is ~11× SLOWER at batch-20
(288 ms) — opt-in only (`SFU_CE_ONNX=1`, default OFF).

---

## 8. Gotchas

- Stop via API/Console, not guest `shutdown` (billing continues).
- A1 capacity is scarce; idle Always-Free instances can be reclaimed.
- x86 `.so` is a no-op; ARM is a real build.
- **One-time ~126 GB upload** — manifest-driven, resumable:
  `scripts/demo_broker/seed_oci_volume.sh` (moved back from `scripts/archive/demo_dependability/` 2026-10-11; rsync `--partial --append-verify --inplace`,
  retry/backoff, `--verify`, `--bwlimit`) over
  `scripts/demo_broker/build_demo_payload_manifest.py`'s manifest — the single definition of
  the payload (exclusions: ablated dense leg, `dense/delta.sqlite`,
  non-served shard variants, `packed/`, `.venv/`, training checkpoints).
  **Measured payload 2026-08-19**: **126.33 GB / 872 files** — served
  shards 44.41 GB, `meta.sqlite` 24.91 GB, `sections/` 56.13 GB, models
  0.87 GB, `.so` 0.005 GB, code 0.009 GB; `.venv` rebuilt on target.
  `--sqlite-free-abstracts` (drop the superseded 13.47 GB
  `abstracts.sqlite` where a verified `.flat` exists) → **112.86 GB**.

  > **Manifest regenerated 2026-10-12:** commit `e0364607` regenerated
  > `scripts/data/demo_payload_manifest.json` with the unchanged generator (no `--hash`) because the 2026-08-19 snapshot listed 31 code paths deleted or moved by the 2026-10-11 codebase triage. The new manifest is **1043 files, 126.332 GB (117.655 GiB)** with zero missing paths; every data component (served shards 96 files / 44.407 GB, shard manifest 1, `meta.sqlite` 3 / 24.908 GB, `sections/` 383 / 56.127 GB, models 33 / 0.873 GB, portable `.so` 3) is byte-identical to the 2026-08-19 run, and only `code` changed (353 files / 0.009 GB to 524 files / 0.011 GB, from files added since August and the 31 removed paths). The 2026-08-19 figures above remain the record of the seed that actually ran; the next seed run uses the regenerated manifest.

- **Abstracts:** only `social_sciences__recent` has local sidecars; the
  rest live-fetch from OpenAlex at rerank (~1 batched call/query) —
  accepted 2026-08-18 (polite pool suffices; trade = ~200–500 ms +
  OpenAlex-up dependency). Backfill design DEFERRED:
  `docs/ABSTRACT_SIDECAR_BACKFILL.md`.
- First click after a stop is ~2–4 min to serving (measured 87–94 s) —
  waiting room covers it.
- **NDCG parity at 150M MEASURED 2026-08-17 — gate CLOSED**: `tc_rrf`
  nDCG@10 **0.5369** over 38 judged queries; versus Qdrant-era Δ −0.0076, 95%
  CI [−0.0189, +0.0041]; versus BMP-era Δ −0.0064, CI [−0.0198, +0.0067] —
  both indistinguishable
  (`data/eval_results/thinclient_parity_seismic_e8dv2_20260817.json`).
  Dense leg ablated 2026-08-18: Δ −0.0077, CI excludes 0 — ships in no
  payload.

---

## 9. Build phases — all DONE through Phase 5 core

**Phase 0 — account (DONE 2026-08-20):** the owner's tenancy, home region
`ca-toronto-1` (matched the code default), API signing key generated
locally (`~/.oci/sfu_demo_api_key.pem`, public half to Console, fingerprint
`5f:6b:...:71:22`), auth in gitignored `scripts/demo_broker/demo.env`,
live read-only signed GET validated (HTTP 200). Trial verified via
organizations ListSubscriptions: FREE_TRIAL, 2026-08-05 → 2026-09-03 —
the window was already half spent at deploy. Credit balance is
Console-only.

**Phase 1 — seed (DONE 2026-08-20, MEASURED):** instance
`SFU-thin-serverhosted-150M` = **E5.Flex 8 OCPU/64 GB** (E4/E3
OUT_OF_HOST_CAPACITY in ca-toronto-1 per the live computeCapacityReports
API; ~$0.336/hr versus E4's $0.30), Ubuntu 24.04, 100 GB boot + **200 GB
`sfu-demo-idxvol`** ext4 at `/mnt/idxvol`, reserved public IP. Transfer:
126.33 GB / 872 files at **24–34 MB/s (~1.6 h wire)**; survived one
source-host sleep and one overnight STOP (auto-resume; `--append-verify`
re-skims at ~155 MB/s); final `--verify`: **byte-identical**. The old
Qdrant/DO `seed_demo_volume.sh` retired to `scripts/archive/`.

**Phase 2 — configure in place (DONE 2026-08-20; no image needed):**
Python **3.11.15** deadsnakes (`pyseismic_lsr` wheel + `.so` are cp311),
venv at `/mnt/idxvol/.venv` from the development 159-package pin with **torch
2.6.0+cpu**, `/opt/sfu-library-thinclient → /mnt/idxvol` symlink so the
stock `sfu-serve.service` installs unedited (starts on wake), polite-pool
keys as root-only EnvironmentFile — **no Zotero creds on the box**. First
OCI serve (informal n=4): warmup 55.7 s; cold-tail 4.48 s; fresh queries
1.5–2.0 s; page cache 60 GB resident. The WI-3 `MemoryHigh` dial
(`dial.py` + `/admin/dial`) was built against the unit 2026-08-18.

**Phase 3 — broker live (DONE, in stages):**
- 2026-08-20: broker on Always-Free E2.1.Micro `sfu-demo-broker` (private
  10.0.0.80, reserved public **<broker-ip>** — where the Cloudflare
  `demo.` record points), own venv, `sfu-broker.service`, `DEMO_CLOUD=oci`
  + `DEMO_BROKER_LIVE=1`. First real control calls verified: schedule
  wake, reconcile wake, idle-reaper SOFTSTOP. Invite flow works publicly.
- 2026-08-21 DNS+TLS: Cloudflare A `demo.vancitylandscaper.com` →
  <broker-ip>, **Proxied**; zone SSL **Flexible** (edge HTTPS, origin
  port 80 via persisted iptables `REDIRECT 80→8080`). ⚠ Flexible = CF→
  origin hops (incl. bearers) travel plain HTTP; upgrade path = Origin CA
  cert + Configuration Rule scoping Full(strict) to `demo.` only — never
  flip the zone-wide mode (shared with the main site). Broker UI redesign
  same day (`e081f63`).
- 2026-08-21: GUI rebrand SFU → **Duck Library** (`4c7ec0c`; broker HTML
  only — never `source/`, tool names, or the `"sfu-library"` server name;
  **extended 2026-10-10** to the MCP tool surface, the architecture page's
  model labels, ntfy titles and systemd `Description=` lines — unit file
  names and the server name unchanged; the broker box needs a redeploy +
  `daemon-reload` to pick it up; ledger
  `REBRAND_DUCK_LIBRARY_2026-10-10.md`);
  `/start` logs `CF-Connecting-IP` (`fb96e67`); **schedule flipped to
  24/7** (window 0→24 days 0–6, killswitch cap 10→25 h; prior configuration in
  `demo.env.bak-business-hours`) — ~$8.06/day, ~$109 through trial end.
- 2026-08-21: **browser GUI exposed, invite-gated** (`541fe53`) —
  `/start` sets a Secure+HttpOnly `duck_session` cookie; broker proxies
  `/app/*` + `/api/*` behind it (no session → 303/401; `api/unpack` 403;
  `api/search` rate-capped + tracked); `/health` returns the serve shape
  to GUI sessions. Live-verified end-to-end. Suite shell rebranded too
  (`8ac7ba1`, owner-approved `web/` exception — visible strings only,
  identifiers kept; deployed to `/mnt/idxvol/web`). **Cache-gate fix
  (`4c0cc4c`):** CF edge-cached `/app/*.js` past the cookie gate → proxy
  forces `Cache-Control: private, no-store` (verified BYPASS).
- 2026-08-21: **global concurrency switch** (`711a986`) — billable
  searches (GUI + MCP) share `DEMO_MAX_CONCURRENT_SEARCHES` slots
  (default 6, under the serve's 8-slot semaphore); beyond → 429 +
  Retry-After: 5; owner ntfy at ≥2 concurrent sessions (10-min cooldown).
  **Saturation battery MEASURED**: waves 4/6/10 → exactly 6 served +
  4×429 at n=10; recovery 6/6, zero leaked slots; ntfy fired once; 0
  errors; burst p50 8–9 s at cap. **Mixed GUI+MCP wave**: 5+5 → 6 served
  + 4×429 across BOTH paths (one shared budget). **MCP-priority reserve
  (`211856a`) MEASURED**: `DEMO_MCP_RESERVED_SLOTS=2` — GUI borrows all 6
  when MCP idle (8 GUI → 6 served); 1 MCP + 6 GUI → exactly 4 GUI + 2×429;
  no preemption. **Battery-found bug fixed (`c4bb9fd`)**: shared
  `check_same_thread=False` sqlite conns raced under real concurrency
  (InterfaceError → 500) — all store access serialized via `LockedDB`;
  86/86 tests.
- 2026-08-21: **owner ntfy pipeline restored** — `<ntfy-host>`
  was an unproxied A record at the home WAN IP (unreachable) and then
  deny-all 403'd token-less publishes. Fixed: CNAME onto the existing CF
  tunnel (ingress `http://<nas-ip>:30280`), ntfy token for the
  `monitor` user into `DEMO_NOTIFY_TOKEN` (backup:
  `demo.env.bak-pre-ntfy-token`). Third failure mode (`90b77a8`): CF
  Browser Integrity Check 403s python-urllib's default UA (error 1010) —
  `notify.py` sends `Mozilla/5.0 (compatible; DuckLibraryBroker/1.0)`.
  End-to-end verified.
- 2026-08-21: **stale CF PoP cache root-caused** (`33e6185`, `90b77a8`) —
  PoPs that cached `lib/api.js?v=duck3` before the no-store fix served a
  copy predating `normalizeResult`'s `doi` field (Access button "boots
  back to search"). Zone token lacks cache-purge permission → fix is URL
  rotation `?v=duck3`→`?v=duck4` on all versioned assets. Serving-tree
  note: the serve runs from `/mnt/idxvol/src`, so **`WEB_DIR` =
  `/mnt/idxvol/web`** — deploy web assets there, not (only) `/opt`.

**Phase 4 — safety (DONE 2026-08-20; reaper live-tested, daily-cap trigger
untested):** per-VNIC NSGs — `sfu-broker-public` (8080/80/443 world) and
`sfu-serve-locked` (8080 from **10.0.0.80/32 only**), verified
public→serve unreachable; instance iptables mirror it (persisted). Idle
reaper fired a real SOFTSTOP → STOPPED → schedule re-woke. The killswitch
shares `_destroy()` with the reaper (STOP path proven); its 25 h-cap
*trigger* has not fired live. **Scheduler bug fixed (`5d97700`):** stored
UP was trusted forever — out-of-band stops were never detected; the loop
now reconciles against `compute_active()` + health each poll (watched
live: `reconcile_down` → START same tick).

**Phase 5 — dry run (CORE NUMBERS MEASURED 2026-08-20, §10):** wake 87 s;
warm p50 1.71 s; 5/10/15 concurrency held; dial verified. 2026-08-21: MCP
smoke over the public domain — invite click → `ready:true` in **94 s**,
`initialize` (`sfu-library 1.26.0`), `tools/list`, real `search_academic`;
first post-wake query ~9.8 s (n=1). Remaining: killswitch-trigger test,
WI-12 soak bar (a) re-run.

**Phase 6 (optional):** aarch64 `.so` for a free-A1 subset tier;
full-corpus dense leg; more abstract sidecars.

### GUI result paging / infinite scroll (2026-09-01) — DONE client-side

Backlog item (owner-requested 2026-08-21) closed; server untouched.
Constraints measured in `source/lib/tools.py::search_academic_structured`:

- `limit` is clamped server-side to **≤ 50** — the hard ceiling per query.
- `page` is parsed but **only the direct-OpenAlex branch forwards it**
  (1-indexed upstream); the federated path ignores it. Sending `page` from
  the client is unsafe: no-op federated, double offset on OpenAlex.
- So the GUI pages by **cumulative fetch + client-side merge**: page N
  requests `limit = N × PAGE_SIZE`, no `page` key; `SFUApi.mergePages`
  dedupes by result id and appends the new tail. `PAGE_SIZE = 10`,
  `MAX_PAGES = 5` → the 50 cap. `hasMore` is derived (short page ⇒
  exhausted; page 5 ⇒ stop), never assumed.
- Each scroll page is a real `/api/search` (own result-cache key — `limit`
  differs) and counts against session rate caps. First paint got cheaper
  (top-k 10); reaching 50 results costs 5 queries.
- Sequential/queue mode keeps one-shot behavior (queue worker asks limit
  50, scroll-append disabled) — a scroll can't smuggle a concurrent query
  past the queue.
- `search.jsx`: IntersectionObserver on a sentinel (`rootMargin: 300px`,
  root = results container); keyboard-reachable "Load more results" button
  always rendered as the no-IntersectionObserver fallback.
- If the federated path ever honors `page` server-side: send `page` +
  flat `limit = PAGE_SIZE`, drop the cumulative slice; `mergePages` and
  the observer stay.

Deploy note: `lib/api.js` + `search.js` changed → versioned assets rotated
**`?v=duck4` → `?v=duck5`** (the CF-PoP stale-copy trap). Not deployed by
this change. Efficacy: **IMPLEMENTED, EFFICACY UNMEASURED** on live
traffic; headless only — `verify_web_jsdom.mjs` **42/0** (24 pre-existing
+ 18 new), `verify_web_progress.mjs` **18/0**, 2026-09-01.

---

## 10. Efficacy — measured numbers

> **2026-10-06 (after the rebuild on Pay As You Go):** click-wake → serve health 21.8 s, broker UP 27.9 s,
> warm 295 s (warm-up 272.1 s versus 60.2 s below — the hot-set fault is bound by the 200 GB volume's ~130 MB/s
> ceiling and the stack loads more models now); one-hour session stop verified (60.9 min → STOPPED in ~65 s).
> Full table: `scripts/demo_broker/README.md` §"2026-10-06 revival". The rows below are the 2026-08-20 numbers.

**First serve session (2026-08-20, E5.Flex 8/64):** seed 24–34 MB/s with
two verified resume events; warmup 55.7 s; first cold-tail 4.48 s, then
1.5–2.0 s fresh (informal n=4); two full STOP/START cycles survived.

| Metric | Measured | Notes |
|---|---|---|
| Wake START → fully-warm serving | **87 s** (boot 10 + service 16 + warmup 60.2) | click→serving ≈ 1.5 min |
| Warm fresh-query battery | **p50 1.71 s / p95 1.99 s** (n=20, subject-diverse) | incl. live OpenAlex fetch + CE rerank |
| Concurrent 5/10/15 clients | per-req p50 8.3/5.5/6.9 s; wall 10.3/9.1/13.1 s; 0 failures | from the broker box in-VCN |
| MemoryHigh dial spot-check | 4G rung: memory.current 7.4G→1.7G; fresh query 3.1 s → **21.7/11.4/3.6 s**; clean release | VERIFIED under real systemd |
| $/cold-visit (**billed-line VERIFIED 2026-09-01**, Usage API hourly lines) | **USD 0.129 / CAD 0.185** per 23-min cold visit | Schedule-era (08-20→08-21) hourly billing shows stopped hours at exactly CAD 0.0000 — scale-to-zero premise verified. Measured rate CAD 0.4823/instance-hr = USD 0.336 at Oracle's own CAD 1.4354 list ratio. **The tenancy bills CAD**: credit draw is CAD 0.17–0.18/cold visit. 24/7 era (since 08-21): CAD 11.93/day measured (USD 8.31) versus USD 8.06 expected — the 3.1% gap is the billed idxvol (§5 correction). CAD 133.85 consumed through 09-01; trial expiry 2026-09-03 binds, not credit balance. Evidence: `data/eval_results/oci_billing_20260901/` |
| Concurrent-dial collision (2026-08-21) | 2 conflicting `set` + 20 interleaved writes: **0 errors, serialized at systemd, silent last-writer-wins** (loser's readback shows winner's rung). Live effect via public `/mcp`: baseline 3.6–4.7 s → 4G rung 12–23 s → off: 5.5–8.8 s refault tail then 2.1–3.7 s | one global dial per box — per-person RAM impossible; add a version/lock if multi-operator dialing ever matters |

⚠ **Page-cache ownership caveat (measured both ways 2026-08-20):** the
dial governs only cache **charged to the serve cgroup**. After an SSH
rsync (seed/verify) touched the files first: memory.current 6.9G against
60G system cache, a 24G rung evicted nothing; after fresh boot+warmup the
same dial bit hard. Valid ladder runs require service-faulted cache — run
after a STOP/START, never after a seed/verify.

Still unmeasured: the daily-killswitch *trigger* (its STOP path is the
reaper's, which fired live) and the WI-12 sustained soak.

**Cross-encoder verdict chain (all 2026-08-19):** int8 ONNX wired opt-in
(`SFU_CE_ONNX=1`, tests in `source/tests/test_reranker_onnx_ce.py`) but at
serve shape torch v1 = **25.5 ms versus int8 288 ms** → torch stays default;
the 19× per-pair figure must not be used for serve sizing. Same audit's
junk-promotion finding: v1 promotes injected off-topic docs into top-5 at
**24.4% versus base ms-marco 3.8%**. Judged serve-path eval
(`eval_ce_v1_vs_base.py`, `ce_v1_vs_base_judged_20260819_2124.json`; fresh
2026-08-18 set, 120 topics × 2 forms, 4,800 candidates, 0 unjudged):
nDCG@10 **none 0.7139 · v1 0.7904 · base 0.8069**; paired v1−base
**−0.0165, 95% CI [−0.0281, −0.0051]** — base significantly better (the
old +0.064 v1 win was on the 90.3%-contaminated original set). Both CEs
beat no-CE (v1 +0.0766, base +0.0931). **Recommendation: serve base.**
Flip = `SFU_CE_MODEL_PATH` (default unchanged = v1); if flipped, ship a
local ~90 MB snapshot of `cross-encoder/ms-marco-MiniLM-L-6-v2` in
`models/` (no HF download at first query). **DECISION PENDING (operator).**

---

## 11. Ops runbook — minting invite links (verified 2026-08-21)

Invites live in the broker's sqlite on the **broker VM**
(`ubuntu@<broker-ip>` — NOT the serve box). Each invite is a personal
`/start?t=inv_…` URL; clicking mints/reuses that person's isolated session
(rate caps + owner ntfy per session-start).

```bash
# from the devcontainer (key: ~/.ssh/sfu_demo_oci)
ssh -i ~/.ssh/sfu_demo_oci ubuntu@<broker-ip>

# on the broker VM — env must be loaded so DEMO_PUBLIC_BASE etc. are set
cd ~/demo_broker && set -a && . ./demo.env && set +a

~/broker-venv/bin/python3 mint_invite.py --name "Prof Jane Doe"   # one link
~/broker-venv/bin/python3 mint_invite.py --name "Workshop" --count 20
~/broker-venv/bin/python3 mint_invite.py --list                   # audit
~/broker-venv/bin/python3 mint_invite.py --revoke inv_xxx         # kill one
```

- Use the invitee's real name — it appears in session logs and ntfy pushes.
- Re-clicking reuses the session (no new credit burn); `--revoke` is the
  only cutoff.
- One-liner: `ssh -i ~/.ssh/sfu_demo_oci ubuntu@<broker-ip> "cd
  ~/demo_broker && set -a && . ./demo.env && set +a &&
  ~/broker-venv/bin/python3 mint_invite.py --name 'NAME'"`
- `scripts/demo_broker/README.md` documents the same CLI against the old
  NAS/DO layout; this section is the current OCI procedure.

## 12. Source docs

`HYBRID_DEMO_DEPLOYMENT.md` (DEPRECATED DO plan) ·
`docs/archive/bmp_decommission_plan/DO_SIZING.md` (RAM→latency model) ·
`DEMO_DEPENDABILITY.md` §WI-7 (warm/concurrency numbers) ·
`docs/THIN_CLIENT_SWAP.md` (engines, 9p lesson, warmup/prefault) ·
`PORTABLE_SOCSCI_WINDOWS_BUNDLE.md` (subset tier) · OCI
[price list](https://www.oracle.com/cloud/price-list/) ·
[stopped-instance billing](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/resource-billing-stopped-instances.htm) ·
[Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).
