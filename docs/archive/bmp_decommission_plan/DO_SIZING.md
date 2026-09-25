# DigitalOcean Droplet Sizing for the Qdrant SPLADE Demo

> **CLOSED SUPERSEDED 2026-07-06** — the BMP->Qdrant decommission was overtaken by the SEISMIC promotion (`docs/SEISMIC_ARCHIVE_SPLIT.md`; SEISMIC is the served SPLADE engine since 2026-07-06). Its DigitalOcean SKU/price tables are additionally unrunnable as of 2026-09-25 (cloud access ended, no droplet will ever be rented); only the measured RAM->latency model survives as evidence. Not current; do not resume.

**Status:** CLOSED SUPERSEDED 2026-07-06

> **STATUS 2026-09-25: CLOUD ACCESS ENDED** — on top of the 2026-08-06
> deprecation below, there is now **no cloud target at all**: the operator has no
> access to any cloud instances, the OCI E5 62 GiB demo host and every
> DigitalOcean droplet are gone and will not return, and the demo broker
> (`scripts/archive/demo_broker/`) is **dormant**. No droplet will be rented, so the SKU
> table, the monthly prices and the "recommended demo droplet" row are
> **CLOSED-UNRUNNABLE**, not pending decisions. The measured RAM→latency *sizing
> model* stays valid and is now applied to the **local WSL2 host only** (31 GB
> RAM, 16 cores, kernel 6.18 WSL2, MGLRU enabled, cgroup v2).

> **⚠ DEPRECATED for the cloud target 2026-08-06 — the demo moved to Oracle
> Cloud (OCI).** The **RAM→latency sizing MODEL** in this doc is still valid and
> is cited by `docs/deprecated/oci_demo/OCI_DEMO_DEPLOYMENT.md` §2, but the
> **DigitalOcean droplet SKUs, prices, and the Qdrant engine** here are
> superseded: the SPLADE leg is SEISMIC (see the 2026-07-17 POINTER below), and
> the deployment target is OCI (E4.Flex x86 / A1.Flex ARM), not DO. Use the OCI
> doc for shape + price; use this doc only for the sizing *reasoning*.

Derived from **measured** page-cache behaviour (NOT an estimate). Source numbers
are in `docs/THIN_CLIENT_SWAP.md` (Off-BMP section, 2026-06-19/2021) and the
ops table in `METRICS_CATALOG.md`. BMP-decommission plan Workstream C5.

> **POINTER 2026-07-17 (deployprep WI-7):** the SPLADE serving leg has since
> switched to **SEISMIC** (federated mmap, the 2026-07-06 promotion; Qdrant is
> now an env-gated fallback). The Qdrant-era numbers below (p50 545–861 ms cold,
> ~66 ms 30M-warm) **do not apply to the SEISMIC served path** — see
> `docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md` §WI-7: the SEISMIC warm
> diverse-query p50 on the dev container's 9p mount is 3.3–10.3 s (9p-fault-
> bound, working set not fully resident), 0% errors at concurrency 1–32,
> throughput 0.4→2.9 qps. The sizing model's *spirit* still holds (RAM must hold
> the working set for warm p50), but the engine + the warm numbers are
> SEISMIC's, not Qdrant's. A native-ext4 host with RAM ≥ the ~16 GB working set
> delivers the SEISMIC warm p50 in the tens-of-ms range (WI-1 parallel warm p50
> 47 ms). This doc is retained as the Qdrant-era sizing record; the SEISMIC
> numbers are the current source of truth.

## The RAM model (measured)

Qdrant `on_disk=true` sparse splits memory into two pools with different scaling:

| Pool | What it holds | Scaling | Measured (150M) |
|---|---|---|---|
| **Anonymous RAM** | per-point bookkeeping: id/version trackers, soft-delete bitsets, sparse-index offsets | **~linear in point count** (~43 B/point) | **6.55 GB** RssAnon at rest |
| **Page cache (RssFile)** | the mmap'd posting lists on disk | **scales with available RAM** (OS keeps hot working-set resident; reclaims under pressure) | 1.78 GB at rest; climbs to ~17 GB under query load on the 23 GB host |

**Key measured facts:**
- At **150M** the index is **205 GB on disk**. On a 23 GB host only **~7% is
  page-cacheable**, so SPLADE posting-list reads are disk-bound → **p50 545–861 ms,
  p95 3.4–4.5 s** (`measure_150m_postfix`). This is the RAM-bound number, NOT a
  steady-state serving number.
- At **30M** the index is **~40 GB on disk** (~5× smaller) and **near the RAM
  line**: warm steady-state **p50 ~66 ms, p95 ~86 ms** (`measure_par30_warm`).
  This is the fitting-tier number a correctly-sized droplet delivers.
- Anon is **structural** (config cannot remove it; only fewer points / more RAM /
  sharding can) — so even with unlimited disk you still need ≥ the anon floor.

**Plainly:** to keep latency in the fitting-tier range the droplet's RAM must
comfortably hold (anon floor) + (enough page cache to warm the working set of
the on-disk index). Disk holds the full index; RAM governs latency.

## Sizing recommendations

| Corpus tier | Docs | Index on disk | Anon floor (RAM) | **Min RAM for fitting-tier p50** | Disk | Notes |
|---|---|---|---|---|---|---|
| **30M (demo)** | 30,000,000 | ~40 GB | ~1.3 GB | **16 GB** (32 GB for headroom) | ≥ 60 GB | Reported measured p50 ~66 ms; the recommended demo tier |
| **60M** | 60,000,000 | ~80 GB | ~2.6 GB | **32 GB** | ≥ 110 GB | 2× the 30M working set |
| **150M (full)** | 150,413,098 | 205 GB | 6.55 GB | **≥ 64 GB** (page-cache enough of 205 GB to be non-RAM-bound; 128 GB for low p95) | ≥ 250 GB | Disk-bound unless ~half the index caches resident |

### Recommended droplet (demo) — derived, not gouged

For the **30M tech-demo corpus**, the smallest droplet that keeps p50 in the fitting-tier
range (~66 ms) and leaves headroom for the SPLADE query encoder (ONNX fp16, cold 6.1 s /
warm ~45 ms — set `SFU_SPLADE_MODEL_PATH=models/splade_onnx_fp16` (2026-07-09:
the code default is now the faster `models/splade_onnx_fused`, so no env var
needed — doc `seismic_150m_testbed/08` §D) + a boot-time warm-up
query so no user pays the cold load):

> **32 GB RAM / 60 GB+ NVMe disk, dedicated to Qdrant + the thin-client server.**
> This page-caches the ~40 GB 30M index with room for anon + encoder; expect warm p50
> ~66 ms. Don't share the host with OpenSearch/LLM inference — anon + page cache want
> all available RAM.

For the **full 150M corpus** the droplet must be a server-class box: **64–128 GB RAM
/ 250 GB+ NVMe**, accepting that p95 stays in the hundreds-of-ms-to-seconds range until
the index warms. This is the same conclusion the SWAP doc reaches: "to hit ~66 ms at 150M
needs materially more RAM (page-cache a larger fraction of 205 GB) or a smaller/more-
compressed index."

## Cost / latency trade-off (candidate DO droplet sizes)

Approx monthly pricing (DigitalOcean published; verify at deploy time) vs expected
SPLADE p50 at the 30M demo tier. Latency expectations derived from the measured
RAM→latency relationship, *est.* for the tiers we did not directly measure:

| Droplet | RAM | Disk | 30M SPLADE p50 (exp.) | Full-150M? | ~$/mo | Verdict |
|---|---|---|---|---|---|---|
| Premium Intel, 16 GB | 16 GB | 50 GB NVMe | ~66–90 ms (est.) | no (RAM-bound, p50 seconds) | ~96 | Cheapest viable demo tier |
| **Premium AMD, 32 GB** | **32 GB** | **100 GB NVMe** | **~66 ms (fitting)** | **no** | **~192** | **Recommended demo droplet** |
| Premium AMD, 64 GB | 64 GB | 200 GB NVMe | ~66 ms, full warm | borderline (p50 ~500 ms+, est.) | ~384 | On-ramp to full-150M |
| Premium AMD, 128 GB | 128 GB | 300 GB NVMe | ~66 ms | yes (p95 still warm-dependent) | ~768 | Full-150M serving tier |
| Higher / dedicated | 256 GB+ | 400 GB+ NVMe | ~66 ms | yes, low p95 | ~1500+ | Overkill unless full-150M prod |

- Disk floor: **≥ the index size + ~10%** (30M ≈ 40 GB; full 150M ≈ 205 GB). NVMe
  matters — the index is read on every uncached query, and SATA SSD p95 tails are far
  worse than the measured NVMe numbers.
- The `splade_par30` collection (the 30M validation artifact) already exists in the
  running Qdrant — the demo can serve it with **zero re-ingest** by pointing
  `SFU_SPLADE_QDRANT_COLLECTION=splade_par30`.
- Same-host caveat (it bit the 23 GB dev box): if RAM is tight under query load, the
  OOM killer can SIGKILL Qdrant with no panic line — install
  `scripts/archive/qdrant-serve.supervisor.conf` (serve-only, `autorestart=true`) so a crash
  self-recovers, and give Qdrant a dedicated box (no contending anon pressure).

## What this rules out

- A **4–8 GB "small" droplet** cannot serve even 30M — anon alone (~1.3 GB) plus the
  encoder plus OS leaves no page-cache budget; it would behave like the 23 GB host at
  150M (disk-bound seconds) or OOM under load.
- **Full 150M on a ≤32 GB box** is explicitly a non-goal: the 205 GB index is only
  ~7% cacheable there, so latency is seconds, not the demo target.
