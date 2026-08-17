# OCI free-tier RESIDENT demo — "scale-to-free" + visitor-triggered RAM boost + a live cgroup dial

**Date:** 2026-08-17 · **Status:** **DESIGN / RESEARCHED 2026-08-17 — NOTHING
BUILT, NOTHING MEASURED ON OCI. No OCI resource has been provisioned.**

This is a **variant** of `OCI_DEMO_DEPLOYMENT.md` (2026-08-06), which remains the
canonical plan. It does not replace it. It answers one question the canonical
plan leaves open: *what if the 150M stack never stops?*

> **The idea.** Instead of a parked landing page in front of a `STOP`ped 64 GB
> box, run the **entire 150M stack permanently** on the Always-Free Ampere A1
> allotment (2 OCPU / 12 GB), answering **slowly but always**, at **$0/month**.
> The invite link lands on a demo that is *already alive*. A visitor who wants it
> fast clicks **"turn up the RAM"**, which resizes the instance to a paid A1
> config, billed only while boosted; the idle reaper resizes back **down to the
> free config** instead of stopping. **Scale-to-free, not scale-to-zero.**
> Layered on top: a **live cgroup RAM dial** (`systemd MemoryMax`) that
> demonstrates the RAM→latency curve *without any resize at all*.

Every number below that is not a directly-quoted OCI list price or a
repo-measured value is marked **\*est.\***.

---

## 1. Architecture

```
                       ┌──────────────────────────────────────────────────┐
invite link ──────────▶│  A1.Flex "resident" box   2 OCPU / 12 GB  = $0   │
https://demo.<dom>/    │  ALWAYS RUNNING. Full 150M stack, mmap'd.        │
                       │  serve_http.sh under systemd  →  :8080           │
                       │  cgroup dial: MemoryHigh/MemoryMax on the unit   │
                       └──────────────────────────────────────────────────┘
                              │  answers immediately, DEGRADED (§5)
                              │
   visitor clicks "turn up the RAM"
                              ▼
                       broker (E2.1.Micro, $0) → OCI API: UpdateInstance
                              shapeConfig { ocpus: N, memoryInGBs: M }
                              ⚠ instance REBOOTS (§2.1)  →  waiting room (§6)
                              ▼
                       ┌──────────────────────────────────────────────────┐
                       │  same box, boosted   (2/32, 4/32 or 8/64)        │
                       │  billed on the DELTA only, per hour (§4)         │
                       │  MemoryMax ladder demo: 64→32→16→8 GB, LIVE (§3) │
                       └──────────────────────────────────────────────────┘
                              │
   idle N min ─────▶ broker resizes DOWN to 2 OCPU / 12 GB (never STOP)
   daily killswitch ─▶ force resize DOWN (budget backstop)
```

Two boxes, as in the canonical plan, but with different jobs:

| Box | State | Cost | Job |
|---|---|---|---|
| **Broker / landing** — E2.1.Micro (1 GB) | always on | **$0** (Always Free, 2 instances) | token gate, "turn up the RAM" button, `UpdateInstance` calls, `/health` poll, waiting room during the resize reboot, idle reaper, killswitch, reverse proxy |
| **150M resident** — A1.Flex | **always on**, resized up/down | **$0 parked**, ~$0.03–$0.14/boosted-hr (§4) | serves the full 150M all the time; degraded when parked, fast when boosted |

**The one structural change vs the canonical plan:** the reaper's terminal state
is *smaller*, not *off*. There is no cold start, no dead loading screen, and no
"the demo is down right now" failure mode. There is instead a permanent,
honest, *slow* demo.

---

## 2. Verified OCI facts (all URLs accessed **2026-08-17**)

### 2.1 A1.Flex resize semantics — **in place, but it reboots**

From [Changing the Shape of an Instance](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/resizinginstances.htm):

> "For both Linux and Windows images, you can change the number of OCPUs and the
> amount of memory allocated to a flexible shape."

> "If the instance is running when you change the shape, it is rebooted as part
> of the change shape operation."

- **OCPU and memory are independently adjustable in place** on a flex shape —
  you do not create a new instance, and boot + block volumes are untouched.
- **There is no live/hot resize.** The instance reboots. A graceful guest
  shutdown first is recommended but not required.
- **Capacity is not guaranteed at resize time.** The same page directs you to
  `CreateComputeCapacityReport` to check capacity *before* resizing, and states
  that if service limits are insufficient "the instance retains the original
  shape."
- **Oracle does not document a reboot duration.** The canonical plan's
  "~2–4 min" is a boot-time estimate; for this design the honest figure is
  **reboot + index load + warmup**, which is longer — see §6. ***est.***

**Consequence for the design:** "turn up the RAM" is a *reboot*, not a knob.
Every boost costs the visitor a waiting room. This is the single biggest
architectural cost of the idea — and the reason §3's cgroup dial exists as a
*separate*, zero-downtime lever.

### 2.2 Billing at the free/paid boundary — **netted out, as an hour pool**

From [Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm):

> "All tenancies get the first **1,500 OCPU hours and 9,000 GB hours per month**
> for free for VM instances using the VM.Standard.A1.Flex shape, which has an Arm
> processor. For Always Free tenancies, this is equivalent to 2 OCPUs and 12 GB
> of memory."

> "All tenancies receive a total of **200 GB of Block Volume storage**, and five
> volume backups included in the Always Free resources."

From [Free Tier overview](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm):

> "Remember that Oracle doesn't charge for Always Free resources after you
> upgrade, and **will only charge you for resource usage above the Always Free
> limits**."

**This is the answer to "is the free allotment netted out?" — yes, and it is
netted out as a *monthly hour pool*, not as an instance-shape exemption.** The
allotment is 1,500 OCPU-hr + 9,000 GB-hr/month. A boosted instance is not
"a paid instance"; it simply draws from the pool faster and bills the excess.

**A1 list price** ([Ampere A1 Compute](https://www.oracle.com/cloud/compute/arm/),
read 2026-08-17 — the oracle.com pricing pages returned **HTTP 403** to direct
fetch, so this figure comes from the indexed page text and **must be re-verified
in the OCI Console before any spend**): **$0.01 per OCPU-hour** and **$0.0015
per GB-hour**, all regions.

> ⚠ **This corrects `OCI_DEMO_DEPLOYMENT.md` §5**, which cites "A1.Flex ≈
> $0.015/OCPU-hr". The current published figure is **$0.01/OCPU-hr**. Both docs
> should be reconciled against the Console at deploy time; the canonical plan's
> A1 row is conservative, so its conclusions do not change.

**PAYG upgrade is a hard prerequisite.** A non-upgraded Free Tier account cannot
hold paid resources past the trial ("Paid resources that were provisioned with
your credits during your free trial are reclaimed by Oracle unless you upgrade
your account"). Boosting above 2/12 without an upgrade is not a billing question
— it is simply unavailable.

**Ambiguity, recorded honestly:** the June-2026 halving (4 OCPU/24 GB → 2/12,
i.e. 3,000/18,000 → 1,500/9,000 hours) was made by a silent doc edit around
**2026-06-15** with no announcement
([InfoQ, 2026-07](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/);
[TerminalBytes](https://terminalbytes.com/oracle-cloud-free-tier-changes-2026/)).
Oracle support has given **contradictory answers** about whether PAYG tenancies
retain the old 3,000/18,000 pool. The doc text says "All tenancies get the first
1,500…". **This design assumes 1,500/9,000 (the pessimistic, documented
reading).** If PAYG really retains 3,000/18,000, every cost number in §4 gets
*better*, never worse.

### 2.3 Capacity and reclamation

- **"Out of capacity" is a real, common failure mode for A1.Flex** — it is the
  single most-reported OCI free-tier problem, with an ecosystem of retry scripts
  built around it (e.g. [hitrov/oci-arm-host-capacity](https://github.com/hitrov/oci-arm-host-capacity)).
  Resizing **up** is a capacity request like any other and can fail; the docs'
  own mitigation is to poll `CreateComputeCapacityReport` first.
- **Capacity reservations exist but destroy the $0 premise.** From
  [Capacity Reservations](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/reserve-capacity.htm):
  "Unused reserved capacity is billed at 85%. Instances created against a
  capacity reservation are billed at 100%." Reserving 8 OCPU/64 GB continuously
  ≈ 0.85 × (8×$0.01 + 64×$0.0015) × 744 h ≈ **$111/month \*est.\*** — i.e. worse
  than just running the canonical plan's box. **Rejected.**
- **Idle reclamation.** [Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
  says: "Idle **Always Free** compute instances may be reclaimed by Oracle.
  Oracle will deem virtual machine and bare metal compute instances as idle if,
  during a 7-day period, the following are true: CPU utilization for the 95th
  percentile is less than 20%; Network utilization is less than 20%; Memory
  utilization is less than 20% *(applies to A1 shapes only)*." The doc does not
  state a PAYG exemption in that section; community consensus (and the fact that
  the policy is scoped to "Always Free" instances) is that upgrading to PAYG
  removes the risk. **Two independent defences apply here anyway:**
  1. This design *requires* a PAYG upgrade for boost (§2.2).
  2. **A resident 150M serve is not idle by the stated test.** The memory
     criterion alone disqualifies it: the mmap'd working set keeps A1 memory
     utilization far above 20% permanently. Ironically, the resident design is
     *more* reclamation-proof than the canonical plan's parked box.

### 2.4 Two shape facts that bite (and one that helps)

From [Compute Shapes](https://docs.oracle.com/en-us/iaas/Content/Compute/References/computeshapes.htm),
`VM.Standard.A1.Flex`:

| Property | Value | Why it matters here |
|---|---|---|
| OCPU range | 1 – 76 | 1 OCPU = 1 Ampere Altra hardware thread (no SMT doubling) |
| Memory range | 1 – 472 GB, **max 64 GB per OCPU** | **2 OCPU may hold up to 128 GB** → a *RAM-only* boost is legal (§4). This is the fact that makes "turn up the **RAM**" literal. |
| Local storage | **Block storage only — no local NVMe** | ⚠ **The index pages over network-attached block storage, not local NVMe.** |
| Network | 1 Gbps/OCPU, max 40 Gbps | at 2 OCPU the box has 2 Gbps for *both* client traffic and block-volume I/O |

> ⚠ **The "local NVMe" premise needs correcting.** `OCI_DEMO_DEPLOYMENT.md` §2
> says "Index on the instance's local block volume (NVMe-backed)". OCI Block
> Volume is **network-attached**; A1.Flex has no local NVMe at all. Per-fault
> cost is therefore *network storage latency*, not local-NVMe latency.
> [Block Volume Performance](https://docs.oracle.com/en-us/iaas/Content/Block/Concepts/blockvolumeperformance.htm):
> Balanced (VPU 10, the default) = 60 IOPS/GB, max 25,000 IOPS/volume;
> Lower Cost (VPU 0) = 2 IOPS/GB, max 3,000 IOPS, and "you might not see the
> same latency performance… you might also see a greater variance in latency".
> **Corollary the brief's premise got backwards: OCI numbers are NOT
> automatically better than the dev container's 9p.** The repo's measured
> per-fault service cost on 9p was **0.33–0.36 ms** (R1, §3). Whether a Balanced
> block volume beats that is **UNKNOWN and UNMEASURED**. A 150 GB Balanced
> volume caps at 9,000 IOPS ***est.*** — which, in the thrash regime this design
> lives in, is a first-order constraint, not a footnote.

---

## 3. The cgroup dial — the part that needs no cloud at all

### 3.1 Mechanics (verified against the kernel + systemd docs)

The serve is a single process: `scripts/serve_http.sh` `exec`s
`src/sfu_library_mcp_http.py` (uvicorn, `:8080`), so under
`ExecStart=/path/to/repo/scripts/serve_http.sh` the Python process **inherits the
unit's cgroup directly**. One `MemoryMax=`/`MemoryHigh=` on that unit caps the
process holding every seismic mmap *and its page cache*.

- **The dial is live.** `systemctl set-property --runtime <unit> MemoryHigh=32G`
  applies immediately, without restarting the service; `--runtime` writes to
  `/run/systemd/system.control/` and does not survive a reboot (omit it to
  persist via `/etc/systemd/system.control/`). This is exactly what a demo
  wants: a slider that takes effect between two queries.
- **Page cache IS charged to the cgroup.** [cgroup-v2 kernel docs](https://docs.kernel.org/admin-guide/cgroup-v2.html):
  the memory controller tracks "Userland memory — **page cache** and anonymous
  memory", kernel data structures, and socket buffers. Because this workload's
  cost is ~93% file-backed page cache (14.3 GB file-backed vs 1.1 GB anon —
  §3.2), the dial genuinely governs the working set. This is not a toy limit; it
  is *the* limit.
- **Use `MemoryHigh`, not `MemoryMax`, as the demo dial.** Kernel docs:
  `memory.high` — "the processes of the cgroup are throttled and put under heavy
  reclaim pressure", and breaching it "**never invokes the OOM killer**".
  `memory.max` — "if memory usage reaches this limit and cannot be reduced, the
  **OOM killer is invoked** in the cgroup." A demo that OOM-kills the serve in
  front of a visitor is a failed demo. **Recommended:**
  `MemoryHigh=<dial>` + `MemoryMax=<dial + ~1.5 GB guard>` + `MemorySwapMax=0`
  — the ladder rung is enforced by reclaim, and `MemoryMax` is only a backstop.
  (`MemorySwapMax=0` matters: the repo's whole R1/R2 ladder was measured
  swap-forbidden, `swap_confounded: false`, `vmswap_kb_max: 0` in every cell — a
  swap-enabled dial measures something else entirely.)

### 3.2 What the dial demonstrates — the in-repo evidence

**R1 RAM ladder** (2026-07-14, driver `scripts/seismic_testbed/r1_ram_ladder.py`,
result files `data/eval_results/r1_cap{48,32,24,16,12,8,6}g_20260714.json`,
tabulated in `docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` §R1 and
`docs/session_2026-07-14_f6_corrections_r1_ladder/03_MEASUREMENT_TABLES.md` T4).
Full 150M, 8-shard hybrid federation, prefault ON / pin OFF, 40 pre-encoded
queries × 3 passes, **traversal only** (no ORT in the capped process):

| cgroup cap | cold pass p50 / p95 | pass-3 p50 (majflt) | regime |
|---|---|---|---|
| 48 GB | 576 / 1227 ms | 18 ms (0) | fits |
| 32 GB | 605 / 1275 ms | 18 ms (0) | fits |
| 24 GB | 584 / 1279 ms | 19 ms (0) | fits |
| 16 GB | 942 / 2176 ms | 135 ms (15k) | marginal — **still converging**, not a steady state |
| 12 GB | 1855 / 4589 ms | 22 ms (2.4k) | boundary with hysteresis |
| **8 GB** | 3392 / 7211 ms | **2135 ms (261k)** | sustained thrash |
| **6 GB** | 4802 / 10949 ms | **4924 ms (550k)** | sustained thrash |

> **Correction to the framing this design was commissioned with:** the
> "steady p50 ~4.9 s" cell is the **6 GB** rung, not 8 GB. The 8 GB rung is
> **~2.1 s**. Both are "do not ship", but the numbers must be attached to the
> right rungs.

**R2 fine ladder** (same day, 1 GB rungs 17→9 GB + anchors, convergence-
terminated, cells `data/eval_results/r2_cap*_20260714.json`, summary
`data/eval_results/_r2_ladder_summary.md`) is the sharper instrument and gives
**the number this whole design turns on**:

> **The cliff is measured, between 10 and 11 GB.** Every cap **≥ 11 GB**
> converges to a flat **17.9–18.9 ms**; every cap **≤ 10 GB** plateaus in
> sustained thrash (**10 GB ≈ 1.4 s, 9 GB ≈ 1.8 s, 6 GB ≈ 5.8 s**).

The mechanism is documented at page granularity in
`docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`
(R3 per-page ledger, 2026-07-16): working set ≈ **14.3 GB file-backed + 1.1 GB
anon ≈ 15.5 GB**; the **repeat set** that must stay resident drains to
**10.13 GB**; below it, "no sorting can fit 10–11 GB into 6.9 GB."

**Quality is invariant under the dial.** 40/40 bit-identical top-10 (ids +
scores) vs the uncapped reference across all three stressed cells
(`r1_results_{cap8g_pin16,cap6g_pin16,cap16g_f5rel}.json` vs
`r1_results_uncapped_ref.json`). **This is what makes the dial a good demo:
the answers do not change, only the time to get them.** That is a much better
story than "the small config is worse."

**The two residency levers, correctly named** (the repo's F-numbering):

| Lever | Env gate | What it does | Measured |
|---|---|---|---|
| **F6 prefault-hotset** | `SFU_SEISMIC_PREFLOOR_HOTSET=1` | prefaults (not mlocks) the hot extents into page cache at load | **cold p95 4.66 s → 1.67 s (~2.8×)**, cold p50 ~1.5×, warm unchanged (2026-07-14, `f6_prefault_hotset_20260714.json` vs `f6_gateoff_baseline_20260714.json`). **The recommended-ON lever.** |
| **F4 mlock-floor** | `SFU_SEISMIC_MLOCK_FLOOR=1`, `SFU_SEISMIC_MLOCK_FLOOR_MB` (default 160) | mlocks only the posting-list *navigation* floor (block_offsets + Elias-Fano + DArray inventories) | **RESCOPED 2026-08-17**: 160 MB across 8 shards, warm p50 62.17 → 63.35 ms = **1.019×** (bar ≤1.05× PASS), parity 10/10, `VmRSS` +0.12 GB (`f4_floor_ab_verdict_20260817.json`). **Default stays 0** — proven *free and bit-identical*, **not proven useful**: the pressure bar (zero navigation re-faults under a RAM cap) is **NOT MEASURED**. |
| F3 pin-tier | `SFU_SEISMIC_PIN_BUDGET_GB` | mlocks the hot-set sidecar | **REFUTED as a thrash rescue** — neutral at 8 GB, **~35% WORSE at 6 GB** (steady p50 4.9 → 6.6 s, per-fault cost +26%), `r1_cap{8,6}g_pin16_20260714.json`. **Keep 0.** |

**F4 is the one lever this design could actually promote.** Its unmeasured bar
— "does pinning the navigation floor stop navigation-page re-faults under memory
pressure?" — is *exactly the regime the parked 12 GB box lives in*, and the dev
container "has no RAM cap" so the bar was never testable there
(`THIN_CLIENT_SWAP.md`). **A `MemoryHigh` dial makes that bar testable for the
first time, in-container, for free.** See §8, WI-2.

### 3.3 Two honest caveats on all of the above

1. **All cap-ladder numbers are dev-container measurements on a 9p mount**
   (WSL2 drvfs/9p; `06_KERNEL_PAGE_RECLAIM_INTERNALS.md`). The *shape* of the
   curve (a cliff at the repeat set; flat above it) is a property of the working
   set and transfers. The *absolute milliseconds* do not — and per §2.4, an OCI
   network block volume is **not obviously faster** than 9p for random 4 KB
   faults. **OCI-side numbers remain UNMEASURED.**
2. **`MemoryMax` was not the instrument for R1/R2/R3.** Those cells used sibling
   Docker containers (`--memory=Xg --memory-swap=Xg`). The only repo experiment
   that used `systemd-run --scope` with `MemoryMax`/`MemorySwapMax=0` is the
   older E7b single-shard sweep (2026-07-03,
   `docs/seismic_150m_testbed/10_FORWARD_COMPRESSION_DESIGN.md` §, cells
   `e7b_global_shard0of8*_cap{4G,6G,8G}.json`). Both are cgroup-v2 memory limits
   on the same kernel mechanism, so the ladder is expected to reproduce under
   `MemoryHigh` — **expected, not verified.**
3. **The ladder is traversal-only.** The real serve additionally holds the ONNX
   SPLADE encoder, the embed model, the tantivy `sections/` index (42 GB) and
   `meta.sqlite` (24 GB) — all of which compete for the *same* page cache. The
   full-stack working set is therefore **larger than 15.5 GB**, by an unmeasured
   amount. Every 12 GB estimate in §5 is pessimistic-side for that reason.

---

## 4. Cost model

### 4.1 The pool arithmetic (this is the non-obvious part)

The Always-Free A1 grant is **1,500 OCPU-hr + 9,000 GB-hr per month**. A
permanently-resident 2 OCPU / 12 GB box consumes:

| Month length | OCPU-hr used | GB-hr used | Headroom left |
|---|---|---|---|
| 28 days (672 h) | 1,344 / 1,500 | 8,064 / 9,000 | 156 OCPU-hr, 936 GB-hr |
| 30 days (720 h) | 1,440 / 1,500 | 8,640 / 9,000 | 60 OCPU-hr, 360 GB-hr |
| **31 days (744 h)** | **1,488 / 1,500** | **8,928 / 9,000** | **12 OCPU-hr, 72 GB-hr** |

**A 24/7 resident 2/12 box is exactly free — with almost nothing to spare.**
(The grant appears to have been sized precisely for that: 1,500 ÷ 744 = 2.02
OCPU; 9,000 ÷ 744 = 12.1 GB.) Boosting therefore consumes the *last* of the pool
almost immediately.

For **B** boosted hours in a 744-hour month at 8 OCPU / 64 GB:

- OCPU-hr = 2(744−B) + 8B = 1,488 + 6B → free while **B ≤ 2.0 h**
- GB-hr = 12(744−B) + 64B = 8,928 + 52B → free while **B ≤ 1.38 h** ← binding

> **≈1.4 boosted hours/month are free in a 31-day month** (≈6.9 h in a 30-day
> month, ≈18 h in February). After that the marginal cost of a boosted hour is
> **6 × $0.01 + 52 × $0.0015 = $0.138/hr \*est.\***

### 4.2 Boost targets — pick by what the visitor is buying

| Boost target | Legal? | Marginal $/hr past the pool ***est.*** | RAM verdict vs the measured ladder |
|---|---|---|---|
| **2 OCPU / 32 GB** ("RAM-only") | ✅ (≤64 GB per OCPU) | **$0.030** | above the 11 GB cliff, above the 24 GB "comfortable" rung — but still 2 cores |
| **2 OCPU / 64 GB** | ✅ | **$0.078** | the canonical plan's RAM on free-tier cores |
| **4 OCPU / 32 GB** | ✅ | **$0.050** | **best value: 24 GB "comfortable" cleared, 2× cores** |
| **8 OCPU / 64 GB** | ✅ | **$0.138** | the canonical plan's shape |

*(Marginal = the delta over the parked 2/12 baseline, once the monthly pool is
exhausted. Add ~$0.0? for the boot-volume performance tier if raised above the
free default — unverified.)*

**Design note worth keeping:** because A1.Flex allows up to **64 GB per OCPU**,
"turn up the RAM" can be *literally and only* a RAM change (2/12 → 2/32 → 2/64).
That is the purest expression of the user's idea and the cheapest boost
available — and it isolates the demo's variable to exactly the one the repo has
a measured ladder for.

### 4.3 Per-session cost vs the canonical plan

| | Canonical plan (`OCI_DEMO_DEPLOYMENT.md`) | This design |
|---|---|---|
| Cost unit | **per cold visit** (boot + warm + use + idle-hold, all billed) | **per boosted hour**, and only past ~1.4 free hours/month |
| Parked cost | $0 compute (instance STOPped) | **$0** compute (instance running, inside the grant) |
| Minimum billed session | ~25 min @ ~$0.30/hr ≈ **$0.12–0.15** | 30-min boost @ 4/32 ≈ **$0.025 \*est.\***; @ 8/64 ≈ **$0.069 \*est.\*** |
| Visits that never boost | still bill (~$0.12–0.15 each — the whole warm-up is billed) | **$0** — they are served by the parked box |
| Storage | ~150 GB block ≈ $4–6/mo, or $0 inside the 200 GB grant | same, and this design must fit the grant to stay $0 (§7) |
| 30-day illustrative | ~240 instance-hr × $0.30 ≈ **~$72** | ~20 boosted hr/mo @ 4/32 ≈ **~$1.00 \*est.\***; @ 8/64 ≈ **~$2.75 \*est.\*** |

**The cost story is dramatically better, and it is better for a structural
reason, not a pricing trick:** the canonical plan bills the *warm-up* on every
cold visit, and warm-up is most of a short visit. This design pays warm-up once,
forever, out of the free grant.

---

## 5. Fit check — what 2 OCPU / 12 GB actually buys ***(all est.)***

### 5.1 RAM

| Consumer | Size | Source |
|---|---|---|
| Guest OS + systemd + sshd | 0.4–0.6 GB ***est.*** | — |
| Serve anon floor | **1.1 GB** measured | `THIN_CLIENT_SWAP.md` ("TRUE anon floor 1.1 GB vs Qdrant 16.99 GB"); R1 JSONs `rssanon_kb` 1.13–1.18 GiB every cell |
| ONNX SPLADE query encoder | ~0.7 GB ***est.*** | `disk_streaming_research/03_MIN_RAM_DESIGN_MAP.md` (explicitly marked *est.*) |
| Embed model (`sfu-academic-embed-v5`, shared with rerank) | ~0.5 GB ***est.*** | `OCI_DEMO_DEPLOYMENT.md` §2 (128 MB bi-encoder + torch runtime) |
| **Left for page cache** | **≈ 9.2–9.5 GB \*est.\*** | |

**≈9.2–9.5 GB of page cache sits *below* the measured 10–11 GB cliff.** The
parked box is therefore in the **sustained-thrash regime by construction** — it
is not "marginal", it is on the wrong side of a cliff the repo has measured with
1 GB resolution. R2's neighbouring rungs are **10 GB ≈ 1.4 s** and **9 GB ≈
1.8 s** traversal p50 (9p, traversal-only).

**Expected end-to-end p50 on the parked box, marked \*est.\*:**

| Query class | p50 ***est.*** | Reasoning |
|---|---|---|
| Repeat of a cached query | **tens of ms** | the read-through result cache (`SFU_RESULT_CACHE`, default ON in staging) bypasses the whole stack |
| Query inside the prefaulted hot set (F6 ON) | **~1–2 s** ***est.*** | traversal near the 10 GB rung + encode + BM25F + hydrate |
| Diverse / cold-tail query | **~3–8 s** ***est.*** | traversal thrash + `meta.sqlite` and `sections/` faulting against the same starved cache (§3.3 caveat 3) + network block-volume fault cost (§2.4) |

For calibration, the repo's most similar *whole-stack* measurement — WI-7,
pre-warmed, 9p, on a 56 GB host — read **warm p50 3.3 s at concurrency 1**
(`wi7_warm_capacity_20260717_011753.json`), explicitly because "the working set
is **NOT fully resident**". The parked A1 is the same failure mode with less
RAM. **A 12 GB box will not be a sub-second demo, and the design must not
pretend otherwise. That is the point: the parked state is the honest
RAM-limited regime, and the boost button is how you leave it.**

### 5.2 CPU / concurrency

- **2 OCPU = 2 Ampere Altra hardware threads** (1 OCPU = 1 thread; no SMT
  doubling on this shape).
- Per query the box must run: ONNX SPLADE encode → 8-shard seismic traversal
  (the `.so` releases the GIL during `search`, so it *can* use both cores) →
  tantivy BM25F → RRF → int8 ONNX cross-encoder rerank (measured p50 5.96 ms
  x86; **ARM cost UNMEASURED**) → sqlite hydrate.
- **Concurrency ceiling est.: ~1–2 in-flight queries, ~0.2–0.5 qps.** WI-7
  measured throughput saturating at ~2.9 qps on a 56 GB x86 host; 2 ARM cores
  with a thrashing cache will be well below that. ***est.***
- **Mitigation is already built:** WI-11 overload shed (clean `429` +
  `Retry-After` past capacity) and WI-9 leg circuit-breaker + `degraded` flag —
  both env-gated OFF by default today. **This design should ship them ON**, with
  a max-in-flight of 1–2. A queue that says "you're 3rd in line, or boost the
  RAM to skip the queue" is a *better* demo than a spinner.

### 5.3 Storage — fits the 200 GB grant, with no room for updates

| Item | Size |
|---|---|
| Served payload (SEISMIC dv-v2 42 GB + `meta.sqlite` 24 GB + `sections/` 42 GB) | **~108 GB** (measured 2026-08-06) |
| Code + models + venv | ~12 GB |
| Boot volume (OCI minimum 50 GB) | ~50 GB |
| **Total** | **~170 GB of the 200 GB grant** |

Fits — **with ~30 GB of headroom, which is not enough for the WI-13 update
flow.** `update_demo.sh` stages new artifacts *beside* the live ones before
flipping the manifest; the repo's own delta-class table puts an E8
re-conversion at **~26 GB** and an encoder distill at **~1 GB**. A seismic
re-conversion would land right at the edge of the grant. **Either accept
in-place (non-rollbackable) updates on this tier, or budget a paid block volume
at ~$0.0255/GB-mo for the delta.** Also unverified: whether the Always-Free
200 GB is restricted to a particular VPU level — the default is Balanced (VPU
10) and the free-tier docs are silent on it.

---

## 6. The resize-window UX

Because a boost **reboots** the instance (§2.1), the visitor-facing sequence is:

```
t=0     visitor clicks "Turn up the RAM"  (broker holds a single-flight lock)
t+0s    broker: CreateComputeCapacityReport for the target config
        └─ no capacity? → fall back down the ladder (8/64 → 4/32 → 2/32)
           └─ all fail? → say so plainly, keep serving parked. Never a dead page.
t+2s    broker: UpdateInstance shapeConfig{ocpus,memoryInGBs}   → instance REBOOTS
t+~90s  guest boots            *est.*
t+~2m   systemd starts serve_http.sh, seismic mmap load          *est.*
t+~4m   F6 prefault-hotset + warmup battery faults the hot set   *est.*
t+4–8m  /health green at the boosted size → proxy flips, session continues
```

**Honest total: ~4–8 minutes \*est.\***, not 2–4. The canonical plan's "~2–4 min"
covers boot + warm on a box whose page cache is already sized for the job; here
the same warm-up must run and the repo's own comparable warm-up took **310.5 s**
(WI-6 hook) on a fast host.

**What the waiting room shows — and this is the design's best idea:** the wait is
*not* dead time, because **the parked box was already answering**. Options, in
increasing order of elegance:

1. **Keep the parked session alive until the last moment.** The broker holds the
   pre-boost session's results on screen; the resize is announced, not imposed
   ("your box is being rebuilt — 8 GB → 64 GB — this takes about 5 minutes").
2. **Show the ladder that is about to be climbed.** Render the R1/R2 curve (§3.2)
   with a marker moving from the parked rung to the boosted rung as `/health`
   reports the new size. The visitor watches the exact number they are buying.
3. **Serve the wait from the free E2.1.Micro** with the cached results of the
   queries they already ran, so the page is never empty.

**And the zero-downtime alternative that avoids all of this:** once boosted, the
**cgroup dial needs no reboot at all**. `systemctl set-property --runtime
sfu-serve.service MemoryHigh=32G` re-tightens the cap between two queries. So
the demo has **two** RAM controls with very different characters:

| Control | Latency to take effect | What it proves |
|---|---|---|
| **Instance resize** (buy the RAM) | **reboot, ~4–8 min \*est.\*** | that the free tier really is the constraint, and money removes it |
| **cgroup `MemoryHigh` ladder** (spend the RAM) | **instant, no restart** | the RAM→latency curve, live, on one box: 64 → 32 → 16 → 8 GB, with **bit-identical results at every rung** (§3.2) |

**Recommendation:** boost once at the start of a session to a config with
headroom (4 OCPU / 32 GB), then make the *visible* demo the cgroup ladder. The
visitor gets one wait, then a slider that responds in seconds. This also lets
the demo show *degradation* — 32 → 16 → 8 GB — which a resize-down cannot do
without another reboot.

---

## 7. Risk register

| # | Risk | Severity | Mitigation / status |
|---|---|---|---|
| R1 | **No aarch64 build of the seismic `.so` exists.** The entire design is blocked on it. | **BLOCKER** | §8 WI-1. Cross-compile *type-check* already passes on both aarch64 targets (2026-07-03); a real build + parity run does not exist. |
| R2 | **Boost fails with "out of capacity"** at the moment a visitor asks. | High | Capacity-report pre-check; fallback ladder 8/64 → 4/32 → 2/32; region chosen for A1 availability; **never a dead page** — parked serving continues. Capacity reservation is priced out (§2.3). |
| R3 | **PAYG billing surprise.** The free pool is ~exhausted by the resident baseline (§4.1); a boost left on burns ~$0.14/hr ≈ **$100/mo**. | High | Hard daily killswitch (resize DOWN, not STOP); idle reaper at 10 min; OCI Budget alert at $5; token-gated boost button; the reaper's failure mode must be "resize down", verified by test. |
| R4 | **Free-tier terms move again.** The 4/24 → 2/12 cut was made silently and is still ambiguous for PAYG (§2.2). | Medium | Design must tolerate the allotment shrinking again — the cgroup dial means a smaller box degrades rather than breaks. Re-verify allotment + price in Console before deploy. |
| R5 | **Parked latency is bad enough to be a bad demo** (§5.1: seconds, not milliseconds). | Medium-High | Frame it as the feature (RAM-limited regime, honest); ship the result cache ON so canned demo queries are instant; ship WI-11 shed + a queue message; make the boost button prominent. **If the parked p50 measures >8 s on diverse queries, this design should be abandoned in favour of the canonical plan.** |
| R6 | **Network block volume, not local NVMe** (§2.4) — per-fault cost may be no better than the dev container's 9p, which is where every ladder number came from. | Medium-High | **UNMEASURED. Must be the first thing a dry run measures** (§8 WI-4). Consider Higher Performance VPU 20 for the index volume — but that bills, breaking $0. |
| R7 | **200 GB grant leaves no room for stage-beside updates** (§5.3). | Medium | Accept in-place updates on the free tier, or attach a paid delta volume during update windows only. |
| R8 | **Idle reclamation** of the Always-Free instance. | Low | PAYG upgrade (required anyway) + the box fails the <20%-memory idle test by construction (§2.3). |
| R9 | **`onnxruntime_gpu` is installed, and it is x86-only.** | Medium | The ARM payload must switch to the CPU `onnxruntime` package (which does publish aarch64 wheels). Runtime already uses `CPUExecutionProvider` only, so this is a packaging change, not a code change. |
| R10 | **Reboot mid-session** loses in-flight state and any un-persisted session context. | Low | Broker holds session state; the pre-boost transcript is re-rendered after the flip. |
| R11 | **A1 is 2 Gbps total at 2 OCPU**, shared between client traffic and block-volume paging. | Low-Medium | Boost raises it (1 Gbps/OCPU). Unmeasured whether it binds. |

---

## 8. Prerequisite work items (ordered)

**WI-1 — the aarch64 `seismic` build. BLOCKER; everything else waits.**
Source: `spike/seismic_upstream/` (fork of TusKANNy/seismic, `pyseismic-lsr`
0.4.0, pyo3 0.26 + maturin, path-deps `vectorium_fork` @ c484687 and
`toolkit_fork` @ 024acc4). What is already true:

- **Cross-compile type-check PASSES on both aarch64 targets** (2026-07-03,
  `docs/math_optimization/06_PREGATE_RESULTS.md`): `cargo +nightly check --target
  aarch64-unknown-linux-gnu` → clean in 35.61 s; `aarch64-apple-darwin` → clean
  in 1m00s. The kernel is `std::simd`-based and **not x86-locked at source**
  (`04_ISA_PORTABILITY_RULES.md`).
- The only x86 intrinsic site is `avx2_pshufb` in `swizzle.rs:130-134`, already
  dual-cfg-guarded; it **compiles out on aarch64** and falls through to a scalar
  arm. So aarch64 is *correct* but has a **known scalar gap** where x86 has
  `vpshufb` — a performance cliff of unknown size on the SVB gap decode.
  ***est.: needs measuring, not guessing.***

What remains, and it is not trivial:

1. Install the aarch64 cross-linker (`aarch64-linux-gnu-gcc`) — `cargo check`
   type-checks without linking; a real `.so` needs a linker.
2. `maturin build --release --target aarch64-unknown-linux-gnu` (or build
   natively on the A1 box itself, which is simpler and probably the right call).
3. Decide `-C target-cpu`: portable baseline vs `neoverse-n1`/ARMv8.2+ to get
   FP16-FMA, or ARMv8.4+ for `UDOT`/`SDOT`. **Never bake it into
   `.cargo/config.toml`** (Rule 3). The x86 precedent is WI-4's portable
   `x86-64-v3` build, which ships *instead of* the `target-cpu=native` one.
4. Run **Stage 4 aarch64 parity** (`docs/math_optimization/05_TESTING_PROTOCOL.md`)
   — the T1 harness (`scripts/tests/test_seismic_sequential.py`) is pure Python
   and runs unchanged once the `.so` exists. Bar: bit-identical top-10 vs the
   x86 reference, per the WI-4 precedent (overlap@10 1.0).
5. Measure the aarch64 warm p50 against x86 — the WI-4 bar was ≤1.07×. Expect
   worse on ARM; record it honestly rather than assuming parity.

**WI-2 — port the rest of the payload to aarch64.** Every binary wheel in the
current venv is x86_64-only. Upstream aarch64 availability, checked on PyPI
2026-08-17:

| Package | In venv now | aarch64 wheels upstream? |
|---|---|---|
| `usearch` 2.25.3 | x86_64 only | ✅ yes (`manylinux_2_26_aarch64` / `2_28_aarch64`) |
| `tantivy` 0.26.0 | x86_64 only | ✅ yes (`manylinux2014_aarch64`) |
| `onnxruntime` | installed as **`onnxruntime_gpu` 1.26.0** (x86_64 only) | ⚠ **must switch to the CPU `onnxruntime` package**, which does ship aarch64 wheels. Runtime already pins `providers=["CPUExecutionProvider"]`, so no code change. NEON support is expected but **UNVERIFIED for the int8 cross-encoder** — the 19× int8 speedup (p50 114 → 5.96 ms) was measured on x86 and **does not transfer by assumption**. |
| `torch` / `sentence-transformers` | CUDA x86 builds | ✅ CPU aarch64 wheels exist (`manylinux_2_28_aarch64`); CUDA builds obviously do not |
| `numpy` 2.4.3 | x86_64 only | ✅ yes |
| `pyseismic-lsr` | x86_64 only, **not in any requirements file** | ❌ WI-1 |

**WI-3 — the cgroup dial, built and measured in-container FIRST (no cloud).**
Write the systemd unit + the `set-property --runtime` dial + a `/dial` control
in the broker, and re-run the R1/R2 ladder under `MemoryHigh` on the dev
container. This costs nothing, needs no ARM build, and delivers three things:
(a) verifies the ladder reproduces under `MemoryHigh` rather than Docker
`--memory` (§3.3 caveat 2); (b) **finally makes F4's unmeasured pressure bar
testable** (§3.2); (c) produces the demo asset itself. **This is the highest
value-per-risk item in the whole doc and should be done regardless of whether
the OCI design proceeds.**

**WI-4 — OCI dry run** (only after WI-1/2). Measure, in this order: per-fault
cost on a Balanced block volume vs the 9p baseline of 0.33–0.36 ms; parked p50
at 2/12 for cached / hot-set / diverse query classes; the real resize→serving
wall-clock; boosted p50 at 4/32 and 8/64; resize-DOWN reliability under the
reaper; actual $/boosted-hour from the OCI bill.

**WI-5 — broker changes**: `UpdateInstance` (not `START`/`STOP`) for both
directions; capacity pre-check + fallback ladder; the "turn up the RAM" button
and its token gate; the ladder-visualisation waiting room; the `MemoryHigh`
dial endpoint; killswitch that resizes DOWN.

---

## 9. Decision — this design vs `OCI_DEMO_DEPLOYMENT.md`

### What it wins

1. **Zero wake latency, and no dead-page failure mode.** The invite link always
   lands on something that answers. The canonical plan's worst case — visitor
   arrives, `START` fails or takes 4 minutes, they leave — cannot happen.
2. **The RAM-limited story becomes the DEFAULT state, not a slide.** The repo's
   single most distinctive body of measured work is the R1/R2/R3 ladder and the
   convergence artifact. In this design the demo *is* that work: the visitor is
   standing on the wrong side of a cliff the repo measured to 1 GB resolution,
   and the button moves them across it.
3. **Bit-identical answers at every rung** (40/40 top-10 parity under pressure)
   turns "small config" from an apology into a claim: *the quality is invariant;
   only the latency is bought.*
4. **Cost drops by roughly an order of magnitude** and, more importantly,
   changes *shape*: visitors who never boost cost **$0**, whereas in the
   canonical plan every cold visit bills a full warm-up (~$0.12–0.15).
5. **The cgroup dial is a zero-downtime, zero-cloud demo asset** that can be
   built and measured *today*, in-container, and is useful even if OCI never
   happens.
6. **More reclamation-proof than the parked box** — a resident serve fails the
   idle test by construction (§2.3).

### What it loses

1. **The aarch64 `.so` becomes a hard blocker.** The canonical plan's
   recommended shape (E4.Flex x86) runs today's `.so` with no recompile. This
   design cannot start until WI-1 lands, and WI-1 has a known scalar-fallback
   gap of unmeasured cost.
2. **Boost is a reboot, mid-session, ~4–8 min \*est.\*** — *worse* than the
   canonical plan's cold start, because it interrupts a visitor who was already
   engaged rather than one who is still reading the landing page.
3. **Capacity risk moves onto the critical path.** The canonical plan's `START`
   of an existing instance is a much smaller capacity ask than resizing an A1 up
   to 8/64 on demand in a region where A1 is famously contended.
4. **The parked experience is genuinely slow** (§5.1: seconds, plausibly many).
   "Always answerable" is only a win if the answers arrive before people leave.
   **This is the assumption the whole design rests on, and it is UNMEASURED.**
5. **No local NVMe on A1** (§2.4) — the canonical plan's "fast local disk paging
   covers the long tail" premise is weaker here (and, on inspection, needs
   re-checking in the canonical plan too).
6. **Free-tier terms are a moving target** with no announcements (§2.2 R4);
   building the demo's economics on them is building on sand.

### Verdict

**Adopt WI-3 now; keep the OCI variant as a researched alternative, gated on
WI-1 and on one measurement.**

- **Do WI-3 (the cgroup dial) immediately and unconditionally.** It is free, it
  needs no ARM build and no cloud, it makes the repo's best measured story
  interactive, and it closes F4's outstanding pressure bar. Its value does not
  depend on any of this doc's OCI conclusions being right.
- **Do not commit to the resident-OCI design until WI-1 (aarch64 `.so` +
  Stage-4 parity) is done and one number is measured: the parked p50 on diverse
  queries at 2 OCPU / 12 GB.** If it lands under ~3 s, this design is clearly
  better than the canonical plan and should replace it. If it lands over ~8 s,
  "always answerable" is a fiction and the canonical plan's honest loading
  screen wins.
- **If it proceeds, boost to 4 OCPU / 32 GB, not 8/64** ($0.05 vs $0.138/hr
  marginal ***est.***, and 32 GB already clears the measured "comfortable"
  rung), and make the *visible* demo the cgroup ladder rather than repeated
  resizes.
- **`OCI_DEMO_DEPLOYMENT.md` remains canonical** until all of the above resolves.

---

## 10. Efficacy — NOTHING MEASURED ON OCI

Per repo rules: **no OCI resource has been provisioned and no number in this doc
was measured on OCI.** Everything numeric here is one of:

- **Measured in-repo on other hardware** (dev container, WSL2, 9p mount) — the
  R1/R2/R3 ladders, F4/F6 levers, WI-3/WI-6/WI-7 harness numbers, payload sizes.
  Cited to file and date throughout.
- **Quoted from OCI documentation** accessed 2026-08-17 (§11), with the A1 unit
  price flagged as read from an indexed page after the pricing site returned
  HTTP 403 to direct fetch — **re-verify in Console before spend**.
- **An estimate** — every such value carries ***est.***

Open gates before this design could be called ready: WI-1 aarch64 parity;
WI-3 `MemoryHigh` ladder reproduction + F4 pressure bar; WI-4's six OCI
measurements (§8). Also inherited, unchanged from the canonical plan: **NDCG
parity at full 150M is UNMEASURED** (`THIN_CLIENT_SWAP.md`).

---

## 11. Sources

**OCI documentation, all accessed 2026-08-17:**
- [Changing the Shape of an Instance](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/resizinginstances.htm) — flex resize in place; reboot required; capacity report
- [Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) — allotments; idle-reclamation criteria
- [Always Free Resource Reference](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm) — "All tenancies get the first 1,500 OCPU hours and 9,000 GB hours per month for free"; 200 GB block
- [Oracle Cloud Infrastructure Free Tier](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm) — PAYG upgrade; reclamation of paid trial resources
- [Compute Shapes](https://docs.oracle.com/en-us/iaas/Content/Compute/References/computeshapes.htm) — A1.Flex ranges, 64 GB/OCPU max, **block storage only (no local NVMe)**, 1 Gbps/OCPU
- [Block Volume Performance](https://docs.oracle.com/en-us/iaas/Content/Block/Concepts/blockvolumeperformance.htm) — VPU tiers, IOPS/GB, Balanced default
- [Capacity Reservations](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/reserve-capacity.htm) — 85% billing on unused reserved capacity
- [Ampere A1 Compute](https://www.oracle.com/cloud/compute/arm/) — $0.01/OCPU-hr, $0.0015/GB-hr *(page returned HTTP 403 to direct fetch; figure read from indexed text — re-verify)*
- [OCI Price List](https://www.oracle.com/cloud/price-list/) *(HTTP 403 on 2026-08-17)*

**Free-tier change coverage (2026), accessed 2026-08-17:**
- [InfoQ — Oracle Quietly Halves Free Tier Ampere A1 Compute Limits](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/) — docs changed ~2026-06-15, no announcement, PAYG status contradictory
- [TerminalBytes — Oracle Cloud free tier 2026](https://terminalbytes.com/oracle-cloud-free-tier-changes-2026/) — 3,000/18,000 → 1,500/9,000
- [hitrov/oci-arm-host-capacity](https://github.com/hitrov/oci-arm-host-capacity) — evidence of the A1 out-of-capacity ecosystem

**Linux / systemd, accessed 2026-08-17:**
- [cgroup v2 kernel docs](https://docs.kernel.org/admin-guide/cgroup-v2.html) — `memory.high` throttles and never OOM-kills; `memory.max` invokes the cgroup OOM killer; page cache is charged to the cgroup
- `systemctl set-property [--runtime]` — applies immediately without a service restart; `--runtime` does not persist across reboot

**PyPI wheel availability, checked 2026-08-17:** `usearch` 2.26.0, `tantivy`
0.26.0, `torch` 2.13.0 all publish manylinux aarch64 wheels; `onnxruntime-gpu`
does not (CPU `onnxruntime` does).

**In-repo (the measured evidence this design cites):**
- `docs/infrastructure/OCI_DEMO_DEPLOYMENT.md` — the canonical plan this amends
- `docs/THIN_CLIENT_SWAP.md` — recommended serving config, RAM sizing, F4/F6 levers, anon floor
- `docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` §R1/§R2/§R3, §F3–F6
- `docs/session_2026-07-14_f6_corrections_r1_ladder/` (03 measurement tables, 04 convergence artifact, 06 kernel page-reclaim internals)
- `docs/disk_streaming_research/03_MIN_RAM_DESIGN_MAP.md` — fixed costs, hot-set curve
- `docs/infrastructure/DEMO_DEPENDABILITY.md` §WI-3/§WI-7 — concurrency + the "≥16 GB free" caveat
- `docs/math_optimization/04_ISA_PORTABILITY_RULES.md`, `05_TESTING_PROTOCOL.md`, `06_PREGATE_RESULTS.md` — the aarch64 story
- `docs/infrastructure/PORTABLE_STACK_MANIFEST.md` — pinned wheel inventory
- Result files: `data/eval_results/r1_cap*_20260714.json`, `r2_cap*_20260714.json`, `r3_cap*_instr_*.json`, `_r2_ladder_summary.md`, `f6_prefault_hotset_20260714.json`, `f6_gateoff_baseline_20260714.json`, `f4_floor_ab_{off,on,verdict}_20260817.json`, `wi7_warm_capacity_20260717_011753.json`
