# Duck Library demo broker (NAS-side, always-on)

> **CLOSED DEAD 2026-09-25** — cloud access ended: the OCI E5 host and every
> DigitalOcean droplet are gone for good, so there is no instance for this
> broker to start, stop, pin, reap or watch. Archived with its docs
> (`docs/deprecated/oci_demo/`). Nothing replaces it; serving is local-WSL2-only.
> Kept as an implementation record — never pending, never dispatched.

## 2026-10-06 revival (owner decision; rebuilt, click-wake and one-hour stop MEASURED)

The owner upgraded the OCI tenancy to Pay As You Go, so the banner above is being reversed. State
verified over the OCI API on 2026-10-06, before the upgrade landed:

- Broker box (`sfu-demo-broker`, Always-Free E2.1.Micro) RUNNING; `sfu-broker` + `sfu-watchdog.timer` active.
- Serve instance TERMINATED by Oracle 2026-10-03 08:44 UTC (grace period end); its OCID now 404s. Until
  the config change below the 24/7 window made the broker retry START every 60 s (2,795 failed calls).
- Preserved: `SFU-thin-serverhosted-150M (Boot Volume)` 100 GB, `sfu-demo-idxvol` 200 GB, VCN/subnet,
  NSG `sfu-serve-locked`, reserved public IP `sfu-demo-public-ip` (unassigned). No re-seed needed.
- Tenancy still `FREE_TRIAL` (expired) with E5 core limit 0, so nothing paid can launch until the upgrade lands.

Done on the live broker 2026-10-06 (previous env kept as `demo.env.bak-24x7-pinned-20261006`, previous
code in `_bak_20261006/`):

- **Click-only wake:** `DEMO_BUSINESS_DAYS=` (empty) — no hot window, so the compute starts only on a
  valid `/start?t=` invite click. **Stop one hour after the wake** (`DEMO_MAX_SESSION_MINUTES=60`, new,
  owner request 2026-10-06 20:00 UTC: counted from the wake call, not extended by activity, so one wake
  = one billed hour and 55 h/month = 55 wakes; a visitor still active at the hour is cut off and must
  click the link again). `DEMO_IDLE_MINUTES=60` stays as the idle reaper behind it. `DEMO_PIN_RUNNING=0`.
- **Spend ceiling CAD 40/month (owner, 2026-10-06):** an OCI budget only alerts, so the cap is enforced
  here — `DEMO_MAX_RUNTIME_HOURS_PER_MONTH=55` (new) plus `DEMO_MAX_RUNTIME_HOURS_PER_DAY=10`.
  55 h × CAD 0.4823/h = 26.53, + storage CAD 0.359/day × 31 = 11.13 → **CAD 37.66**, leaving ~CAD 2.3
  for stop lag (runtime is counted to the stop request, billing runs to STOPPED). Rates are the billed
  figures of 2026-09-01 (`data/eval_results/oci_billing_20260901/`), pre-tax; a price change moves the
  dollars, not the hours. At the cap: running compute is stopped, `/start` answers 503, ntfy fires.
- **OCI budget `sfu-demo-spend-watch`:** 40/month, MONTHLY reset on day 1, whole tenancy (set by the
  owner); added an ACTUAL 100 % alert rule (`spend-budget-reached`) beside the existing 1/25/100/250 and
  forecast rules. Alert-only.
- **Rebuild trigger:** `rebuild_trigger.sh` via `systemd/sfu-rebuild-trigger.{service,timer}` runs
  `rebuild_serve_instance.py --execute --hand-to-broker --notify` every 5 min; the preflight exits 2
  untouched while the E5 limit is 0, and the trigger disables itself once `rebuild.launched` exists.
  The rebuild launches E5.Flex 8 OCPU/64 GB from the preserved boot volume on 10.0.0.174, hands the
  new OCID to the broker (env rewrite + restart + state = on-demand wake, so the reaper and caps apply
  from the first minute), attaches the index volume (paravirtualized), re-assigns the reserved public
  IP and soft-reboots the guest.

**Rebuild MEASURED 2026-10-06 (one run, the real one; evidence = `rebuild_trigger.launch-*.log` and
`rebuild_trigger.log` on the broker box, journal of `sfu-broker`):**

| Step | Measured (UTC) |
|---|---|
| Upgrade visible to the API (E5 limit > 0) | between the 19:40:04 tick (still 0) and the 19:45 tick |
| Launch call → instance RUNNING | 19:45:06 → 30 s |
| Index volume attach (paravirtualized) | ATTACHED in 20 s |
| Rebuild script end (public IP re-assigned, SOFTRESET issued, rc=0) | 19:46:03 — 57 s total; trigger disabled itself |
| Serve `/health` 200 after the soft reboot; broker `BOOTING → UP` | by 19:47:06; 19:47:07 — ~2 min after the launch call |
| Serve `warm=true` | by 19:51:36 — ~4.4 min after first health (5 s poll); vs 60.2 s on 2026-08-20 — first boot after a re-attach, single sample |
| Guest | `LABEL=idxvol /mnt/idxvol ext4 defaults,nofail,_netdev` mounted as `/dev/sdb`, 128 G used of 196 G; `sfu-serve` enabled + active; 62 GiB RAM |
| Public `/arch-search` (fresh queries, informal n=5, incl. Cloudflare + broker hop) | 24.2 s, 21.8 s (first two after warm), then 9.8 s, 2.18 s, 2.07 s; 10 results each |

**Session-limit stop and click-wake MEASURED 2026-10-06 (one cycle each; evidence = `sfu-broker` journal,
`broker.jsonl`, the serve box's `sfu-serve` journal):**

| Step | Measured (UTC) |
|---|---|
| First real stop (`DEMO_MAX_SESSION_MINUTES=60`) | SLEEP at 20:46:02 = 60.9 min after the 19:45 wake; SOFTSTOP issued 20:46:03; Oracle `STOPPED` by 20:47:08; broker accounted 1.014 h |
| Click-wake of the STOPPED instance (test invite, from the broker box) | click 20:47:36 → serve `/health` 200 at **21.8 s** → broker UP at **27.9 s** → serve `warm=true` at **295 s** |
| Serve warm-up breakdown (`sfu-serve` journal) | SPLADE ONNX 38 s → embedding model +122 s → cross-encoder +2 s → hot-set fault (6 queries) +110 s = **272.1 s**; vs 60.2 s on 2026-08-20 |
| First queries after warm (`/arch-search` from the broker box) | 48.9 s, 11.5 s, 8.3 s (then ~2 s once warm, see the public-path rows above) |
| Index volume ceiling (`/dev/sdb`, O_DIRECT) | seq 1 MiB QD1 114 MB/s, QD8 **132 MB/s**; random 4 KiB QD1 0.30 ms / 3,320 IOPS, QD16 35,140 IOPS; read_ahead 2048 KB. 200 GB Balanced (10 VPU) is throughput-bound: 13.8 GB hot set ÷ 130 MB/s ≈ 106 s, which is the hot-set row above |
| Owner test stop (manual `sleep` + `mark_down`, nobody else connected) | SOFTSTOP → `STOPPED` in ~40 s; month runtime after both cycles 1.17 h |

Reading: a wake now costs a visitor **~5 min to warm and a slow first query**, not the 1.5 min of 2026-08-20.
The volume delivers above its nominal 96 MB/s, so the attachment type is not the limit; the serve stack
loads more at startup than in August (embedding model + cross-encoder + hot set) and the hot-set fault is
disk-throughput-bound. Levers, none executed (owner's call, all cost money or RAM): a larger or
higher-VPU volume (throughput scales with size/VPU), a smaller warm-up hot set, or keeping the box up
longer. The waiting-room estimate was changed from "under 2 minutes" to "about 5 minutes" (app.py).
Still unmeasured: a real monthly-cap stop (unit-tested only); the broker's own session_start → warm
timing seen by a real visitor through Cloudflare.

Always-on FastAPI gateway that fronts **on-demand cloud compute** running the
thin-client MCP server, with a **hot 09:00–17:00 weekday / cold after-hours**
schedule to protect the credit. Companion build for
`docs/deprecated/oci_demo/HYBRID_DEMO_DEPLOYMENT.md` §0/§2A.

**Two cloud back ends** (`DEMO_CLOUD`, default `do`):

| `DEMO_CLOUD` | Wake | Sleep | Notes |
|---|---|---|---|
| `do` (default) | create droplet from snapshot + attach volume | **destroy** droplet (volume kept) | the original DigitalOcean path, unchanged |
| `oci` | `instance action START` on ONE **persistent** instance | `instance action SOFTSTOP` (`STOP` fallback) | nothing is created/destroyed/re-seeded; volumes persist — `docs/infrastructure/OCI_DEMO_DEPLOYMENT.md` §0/§4 |

`cloud.py` is the factory; both clients expose the same four-method protocol
(`wake` / `sleep` / `compute_ip` / `compute_active`). **The OCI client went
LIVE 2026-08-20: deployed on the Always-Free broker box, first real START /
SOFTSTOP / reconcile-wake cycles verified against the tenancy
(`docs/infrastructure/OCI_DEMO_DEPLOYMENT.md` §9 Phases 3–5).**

**Engine-agnostic** — it brokers a droplet, not a search engine, so it was built
during (and is unaffected by) the BMP→Qdrant `on_disk` migration.

## Status: scaffold, DRY-RUN by default

No DigitalOcean API call is made until `DEMO_BROKER_LIVE=1`. In dry-run, boots /
destroys are **logged, not sent**, so the full control plane (schedule, single-flight
wake, waiting room, proxy, reaper, killswitch) can be exercised without spend.

The budget-safety decision core (`scheduler.py`) is pure and **unit-tested**:

```bash
python3 scripts/demo_broker/test_scheduler.py   # 13 tests, no deps
```

## Files

| File | Role |
|---|---|
| `scheduler.py` | **Pure** hot/cold + idle-reaper + killswitch decision core (no I/O) |
| `state.py` | sqlite state: single-flight wake lock + per-day runtime accounting |
| `do_client.py` | DigitalOcean v2 wrapper (boot-from-snapshot / attach-volume / destroy); dry-run default |
| `oci_client.py` | **OCI wrapper** — START/SOFTSTOP one persistent instance, lifecycle-state map, IP short-circuit; API-key request signing (draft-cavage RSA-SHA256, stdlib urllib + `cryptography`, no `oci` SDK); dry-run default |
| `cloud.py` | provider factory: `DEMO_CLOUD=do` (default) \| `oci` → the `wake`/`sleep`/`compute_ip`/`compute_active` protocol |
| `config.py` | env-driven config + `validate()` preflight |
| `tenants.py` | per-person invites + sessions + durable events + rate caps (sqlite) |
| `notify.py` | push/webhook notifier (ntfy/Slack/Discord/generic); pure `build_payload` |
| `mint_invite.py` | CLI to mint/list/revoke per-person invite links |
| `rebuild_serve_instance.py` | rebuild the terminated serve instance from its preserved boot + index volumes (plan/preflight by default; `--execute`; `--hand-to-broker`) — 2026-10-06, unmeasured |
| `rebuild_trigger.sh` + `systemd/sfu-rebuild-trigger.{service,timer}` | self-disabling 5-min trigger that runs the rebuild once the tenancy can launch paid shapes |
| `app.py` | FastAPI: `/start` (invite+access info), `/status`, `/mcp` (per-session proxy), `/admin/report`, `/admin/dial`, `/health`, scheduler thread |
| `dial.py` | **WI-3 memory dial** (`docs/deprecated/oci_demo/OCI_FREE_TIER_RESIDENT_DEMO.md` §3): live `MemoryHigh` rungs on the serve cgroup — systemd (`set-property --runtime`) or raw cgroup-v2 backend + CLI |
| `watchdog.py` + `systemd/sfu-watchdog.{service,timer}` | read-only liveness watchdog → ntfy (see Watchdog section) |
| `systemd/sfu-serve.service` | serve unit the dial targets: `MemorySwapMax=0` pinned (the ladder was measured swap-forbidden), rungs applied at runtime |
| `test_scheduler.py` / `test_tenants.py` / `test_app.py` / `test_dial.py` / `test_oci_client.py` | decision core / tenancy / end-to-end wiring / dial backends + endpoint / OCI signing + START-STOP + factory (all HTTP mocked) |

### The memory dial (`/admin/dial`, default OFF)

`DEMO_DIAL_BACKEND=systemd` (unit: `DEMO_DIAL_UNIT`, default `sfu-serve.service`)
or `=cgroup` (`DEMO_DIAL_CGROUP_DIR`); rung bounds `DEMO_DIAL_MIN_GB`/`MAX_GB`
(4/64), `MemoryMax` backstop = rung + `DEMO_DIAL_GUARD_MB` (1536). Admin-token
gated: `GET /admin/dial` = status, `POST /admin/dial?gb=12` = set a rung,
`POST /admin/dial?off=1` = release. **Built + unit-tested 2026-08-18 (18 tests,
fake cgroup dir / captured systemctl argv); the R1/R2 ladder has NOT been
re-run under `MemoryHigh` — this dev container cannot host it (no systemd,
read-only cgroupfs, no docker socket; probed 2026-08-18) — so ladder-under-
MemoryHigh remains EFFICACY UNMEASURED until the OCI Phase-5 dry run.**

## Run (dry-run, locally)

```bash
sudo /workspaces/sfu-library-thinclient/.venv/bin/python3 -m pip install fastapi uvicorn  # NAS: into the venv
cd scripts/demo_broker
DEMO_LINK_TOKEN=test uvicorn app:app --host 0.0.0.0 --port 8088
# then: curl 'http://localhost:8088/start?t=test'   (logs a [DRY-RUN] boot)
#       curl  http://localhost:8088/health
```

## Schedule policy

- **Weekday 09:00–17:00 (local `DEMO_TZ`)**: droplet kept HOT; idle reaper suppressed.
  Pre-warm `DEMO_PREWARM_MINUTES` (5) before the open so 09:00 is already serving.
- **After hours / weekends**: scale-to-zero. A valid `/start?t=` click wakes it
  on demand; the idle reaper destroys it after `DEMO_IDLE_MINUTES` (20).
- **Hard daily killswitch**: `DEMO_MAX_RUNTIME_HOURS_PER_DAY` (10) force-destroys
  regardless of state — the budget backstop (≤ ~$124 worst case on the 64 GB tier).
- **`DEMO_PIN_RUNNING=1`** turns both of the above into log-only decisions. Use it
  when a stop would be irreversible (post-trial grace period, paid-shape limit 0).

## Watchdog (read-only, ntfy)

`watchdog.py` runs from `systemd/sfu-watchdog.timer` every 5 min on the broker
Micro. It probes the instance's OCI lifecycleState, the serve box's `/health`,
and the broker's own `/health`, and pushes to `DEMO_NOTIFY_WEBHOOK` only on
change: RUNNING → anything (urgent), `DEMO_WATCHDOG_FAIL_THRESHOLD` (2)
consecutive health failures (high), recovery, and one heartbeat per local day
after `DEMO_WATCHDOG_HEARTBEAT_HOUR` (9; `-1` disables). It never issues an
instance action. State: `DEMO_WATCHDOG_STATE_PATH` (default `watchdog.json`
beside the state db). Deployed live 2026-09-07. Limit: if the Micro itself is
reclaimed nothing fires — the heartbeat going missing is the signal.

## Env vars (all optional; safe defaults)

| Var | Default | Meaning |
|---|---|---|
| `DEMO_BROKER_LIVE` | `0` | `1` = make real cloud API calls (spend) |
| `DEMO_CLOUD` | `do` | cloud provider: `do` \| `oci` |
| `DIGITALOCEAN_ACCESS_TOKEN` | — | DO API token (already in repo `.env`) |
| `DEMO_DO_SIZE` | `g-16vcpu-64gb` | droplet tier (re-sized for Qdrant; see §0) |
| `DEMO_DO_REGION` | `tor1` | DO region |
| `DEMO_DO_SNAPSHOT_ID` | — | pre-baked image id (Phase 2) |
| `DEMO_DO_VOLUME_ID` | — | persistent index volume id (Phase 1) |
| `DEMO_DO_FIREWALL_ID` | — | firewall locking `:8080` to the NAS IP |
| `OCI_TENANCY_OCID` / `OCI_USER_OCID` / `OCI_FINGERPRINT` / `OCI_KEY_FILE` | — | OCI API-key signing identity (`OCI_KEY_PASSPHRASE` optional; literal or secret-file path) |
| `OCI_REGION` | `ca-toronto-1` | OCI region (endpoint `iaas.<region>.oraclecloud.com`) |
| `OCI_INSTANCE_OCID` | — | the ONE persistent demo instance — **static config, never created/destroyed** |
| `OCI_INSTANCE_IP` | — | its stable private IP; the default proxy path (no API call per request) |
| `OCI_COMPARTMENT_OCID` | — | only for the VNIC-attachment IP fallback when `OCI_INSTANCE_IP` is unset |
| `OCI_STOP_ACTION` | `SOFTSTOP` | `SOFTSTOP` (ACPI shutdown → power off) or `STOP` (hard, fallback) |
| `DEMO_LINK_TOKEN` | — | required token on `/start` (protects credit) |
| `DEMO_BEARER_TOKEN` | — | bearer required on `/mcp` proxy |
| `DEMO_TZ` | `America/Vancouver` | schedule timezone |
| `DEMO_BUSINESS_START_HOUR` / `_END_HOUR` | `9` / `17` | hot window |
| `DEMO_BUSINESS_DAYS` | `0,1,2,3,4` | Mon–Fri (0=Mon) |
| `DEMO_PREWARM_MINUTES` | `5` | boot lead before window open |
| `DEMO_IDLE_MINUTES` | `20` | after-hours idle reaper threshold |
| `DEMO_MAX_SESSION_MINUTES` | `0` | fixed session length: stop an on-demand wake this many minutes after the wake call regardless of activity (`0` = off, idle reaper only) (2026-10-06; live value 60) |
| `DEMO_MAX_RUNTIME_HOURS_PER_DAY` | `10` | hard killswitch cap; once spent, `/start` and the hot window also refuse to wake (2026-10-06) |
| `DEMO_MAX_RUNTIME_HOURS_PER_MONTH` | `0` | calendar-month runtime cap (`0` = off): stops running compute and refuses wakes for the rest of the month (2026-10-06; live value 55) |
| `DEMO_PIN_RUNNING` | `0` | `1` = the broker never issues a stop: reaper and killswitch decisions are logged (`reap_suppressed`) but not actuated. Set 2026-09-07 on the live broker: the trial expired 2026-09-04 and the tenancy's E5 limit is now 0, so a stopped box could never be started again |
| `DEMO_POLL_SECONDS` | `60` | scheduler tick interval |
| `DEMO_WATCHDOG_HEARTBEAT_HOUR` | `9` | watchdog daily heartbeat hour (local `DEMO_TZ`); `-1` disables |
| `DEMO_WATCHDOG_FAIL_THRESHOLD` | `2` | consecutive failed probes before a health alert |
| `DEMO_WATCHDOG_STATE_PATH` | `<state dir>/watchdog.json` | watchdog transition state |
| `DEMO_PUBLIC_BASE` | `https://demo.example.org` | public base URL for minted invite links |
| `DEMO_ADMIN_TOKEN` | — | token gating `GET /admin/report` |
| `DEMO_NOTIFY_WEBHOOK` | — | push URL (ntfy/Slack/Discord/Pushover/generic) |
| `DEMO_NOTIFY_KIND` | `ntfy` | `ntfy` \| `slack` \| `discord` \| `json` |
| `DEMO_NOTIFY_ON_QUERY` | `0` | `1` = notify on every query (default: session-start + errors only) |
| `DEMO_SESSION_RATE_MAX` | `30` | max requests per session per window |
| `DEMO_SESSION_RATE_WINDOW_S` | `60` | rate window (seconds) |
| `DEMO_SESSION_DAILY_MAX` | `500` | max requests per session per 24h |
| `DEMO_BLOCKED_TOOLS` | `save_to_zotero,batch_save_to_zotero` | MCP tools blocked for visitors |
| `DEMO_LOG_PATH` | `data/demo_broker/broker.jsonl` | durable rotating JSONL event log |

## Multi-tenant access (per-person, account-free)

Each invitee gets an unguessable token baked into their email link — no sign-ups,
**and no OpenAlex key**: OpenAlex is keyless, so the droplet uses one shared
server-side polite-pool identity and per-session rate caps stop any one visitor
exhausting it. Clicking a link mints/reuses that person's isolated session with its
own `/mcp` bearer, so usage is attributed and isolated per person.

```bash
# mint a personal link (email the printed URL to the invitee)
DEMO_PUBLIC_BASE=https://demo.<domain> python3 mint_invite.py --name "Prof Jane Doe"
python3 mint_invite.py --name "Workshop seat" --count 20   # batch
python3 mint_invite.py --list
python3 mint_invite.py --revoke inv_xxx
```

**Flow:** click `/start?t=<token>` → validates invite → (boots droplet if down) →
returns the personal connector URL + `Bearer` token → **notifies the owner** (push
webhook) → all `/mcp` calls are bearer-gated, rate-capped, visitor-tool-blocked,
and recorded.

### Notifications
Set `DEMO_NOTIFY_WEBHOOK` to any push sink. Owner is notified on **session start**
and **errors** by default (`DEMO_NOTIFY_ON_QUERY=1` for every query). Generic ntfy:
`DEMO_NOTIFY_WEBHOOK=https://ntfy.sh/your-secret-topic DEMO_NOTIFY_KIND=ntfy`.

`DEMO_NOTIFY_TOKEN` adds `Authorization: Bearer` for **auth-locked ntfy** and may be
a literal `tk_...` **or a path to a secret file** (so the broker can reuse an
existing secret without copying it).

**This deployment reuses the existing NAS `sfu-ntfy` server** (verified 2026-06-19,
push accepted on topic `<ntfy-topic>`, which the owner's phone already
subscribes to). The token is `rw`-scoped to `sfu-truenas-*`, so the demo publishes
to that same topic. Env for the NAS broker (no secret in git — read the monitor's
existing file):
```bash
DEMO_NOTIFY_KIND=ntfy
DEMO_NOTIFY_WEBHOOK=https://<ntfy-host>/<ntfy-topic>
DEMO_NOTIFY_TOKEN=/mnt/MAIN/sfu-library-mcp/monitor/secrets/notify_token   # file path
```
To split demo alerts onto their own topic (`sfu-truenas-demo`), mint a token on the
NAS: `sudo docker exec sfu-ntfy ntfy access <user> 'sfu-truenas-*' rw` already
covers it — just change the topic in the webhook URL.

Manual test push: `python3 notify.py "hello"` (uses the env above).

### Durable tracking + debug + reports
- **sqlite** (`invites`/`sessions`/`events` tables, in the broker state db) survives
  NAS reboots — per-person query/error/blocked counts + every event with latency +
  upstream status.
- **JSONL** mirror (`DEMO_LOG_PATH`, rotating) for raw debug grepping.
- **`GET /admin/report?since_hours=24`** (header `x-admin-token: <DEMO_ADMIN_TOKEN>`):
  events-by-kind, per-person usage, recent errors, droplet runtime + est. cost today.

### Safety caps (enforced at the broker, no droplet change)
- **Zotero writes blocked** for visitors (`save_to_zotero`/`batch_save_to_zotero`)
  by inspecting the JSON-RPC `tools/call` name → 403.
- **Per-session rate + daily caps** → 429, protecting the shared OpenAlex pool.
  Counted **per `tools/call` (search)** only — the MCP handshake
  (initialize/tools/list/notifications) is exempt so it can't exhaust the quota.
- The proxy **forwards `Mcp-Session-Id`** back to the client and **streams**
  responses (handles MCP SSE), not buffered — needs live validation in Phase 5.

### Tests
```bash
python3 test_scheduler.py   # 13 — hot/cold decision core
python3 test_tenants.py     # 13 — invites/sessions/rate caps/events/notify
.venv/bin/python3 test_app.py   # 1  — full /start->/mcp->/admin wiring (dry-run)
.venv/bin/python3 -m pytest scripts/demo_broker/ -q   # 83 passed (2026-08-19)
```

## Deploying on the NAS + Cloudflare hostname (Phase 3)

`<nas-user>` has no sudo/docker — run the broker as a user process (it only needs
Python + fastapi/uvicorn, ~256 MB):
```bash
# on the NAS, in the copied scripts/demo_broker/
python3 -m pip install --user fastapi uvicorn          # one-time
mkdir -p /mnt/MAIN/sfu-library-mcp/demo_broker
cp demo.env.example demo.env && $EDITOR demo.env        # fill DO ids when ready
set -a; . ./demo.env; set +a
nohup python3 -m uvicorn app:app --host 0.0.0.0 --port 8088 \
      >/mnt/MAIN/sfu-library-mcp/demo_broker/uvicorn.log 2>&1 &
curl -s localhost:8088/health    # {"status":"ok","mode":"dry-run",...}
```

**Cloudflare hostname** `demo.<domain>` → NAS broker `:8088` (same Cloudflare→NPM
chain as ntfy; creds in repo `.env`). This is a **live DNS change — run it yourself
when ready** (it points a public name at the broker; do it after the broker is up):
- NPM → New Proxy Host: `demo.<domain>` → `http://<nas-ip>:8088`, enable
  Websockets, request SSL. **Or** Cloudflare Tunnel public hostname →
  `http://<nas-ip>:8088`.
- Then set `DEMO_PUBLIC_BASE=https://demo.<domain>` in `demo.env` and restart.
- Lock it down: the broker already enforces per-session bearer + admin token; add a
  Cloudflare WAF rule if you also want IP/header gating (see REMOTE_MCP_ACCESS.md).

`demo.env.example` ships the verified ntfy + schedule + caps; only the DO ids
(snapshot/volume/firewall, Phase 1/2) are left blank.

## Not yet done (needs the migration / Phase 1–2 artifacts)

- Real snapshot + volume IDs (`DEMO_DO_SNAPSHOT_ID` / `_VOLUME_ID`) — Phase 1/2.
- Cloudflare hostname `demo.<domain>` → this gateway (`scripts/setup_cloudflare_mcp.sh`
  pattern) — Phase 3.
- Live dry-run → real boot timing measurement — Phase 5.
- Wiring the droplet's MCP server to the Qdrant sparse leg (post-migration GO).
