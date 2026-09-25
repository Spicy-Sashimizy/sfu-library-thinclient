# Build Plan 02 — Build-once on a bigger host, serve mmap on 32 GB

**Status:** DEFERRED 2026-09-25 (DESIGN, unbuilt since 2026-06-28) — DESIGN (created 2026-06-28, unbuilt). **Solves:** the 150M build-RAM
wall as a **one-time** operation, with **no new code** and **no JVM**. This is the
cheapest path to a measurable G6 if any ≥56 GB box is reachable.

> **2026-06-28 correction (measured): the "no new code" serve premise is FALSE.**
> Stock `SeismicIndex.load()` is **not** mmap — control experiment on the saved 2M
> index: baseline RssAnon 0.006 GB → after `.load()` RssAnon **1.706 GB**, RssFile
> **0.007 GB** (flat). It deserializes into owned anonymous RAM = Path A (→137 GB
> @150M), the exact wall this plan claims to avoid. The serve steps below say "Load
> the index in mmap / Path C mode," but stock code has no such mode — the real mmap
> reader (`MmapSeismicIndex`, C2) exists only as a gitignored Rust bin, never wired
> to Python (C2.5 deprioritized). So **serving 150M mmap'd on 32 GB requires the C2.5
> pyo3 wiring** (new code), not just `.load()`. The build half (steps 1–3) is
> unaffected; only the serve half has this hole. See `06_FINDINGS.md` 2026-06-28
> "stock `.load()` is NOT mmap" row. (Plan 01's serve step carries the same hole.)


## The idea in one line

Build (the RAM-hard step) and serve (the RAM-easy step, once mmap'd) **do not have
to be the same machine.** Build the monolithic 150M index once on a host with enough
RAM, then serve the resulting on-disk index on the 32 GB WSL2 box via mmap (Path C),
where page cache hydrates candidate vectors on demand.

## Why it works (measured)

- **Build is the only RAM-hard step.** Stock `SeismicIndex.build()` holds the
  ~47 GB forward index + clustering scratch resident → ~55–63 GB peak at 150M.
- **Serving is already cured.** Path C measured **+0.041 GB anonymous RAM,
  96 % file-backed** — the forward index serves from disk via mmap; resident anon is
  ~Σ(inverted index) ≈ small. A 32 GB box serves a 150M mmap'd index without OOM
  (page cache does the rest; under-provisioned cache costs latency, not crashes).

## The build host

Two ways to get ≥56 GB for the one-time build:

**Option A — bump the WSL2 cap (no extra hardware; host has 64 GB).**
Edit `C:\Users\<you>\.wslconfig` on the Windows host:

```ini
[wsl2]
memory=54GB      # of the 64 GB host; leaves ~10 GB for Windows
swap=24GB
```

Then `wsl --shutdown` and reopen. Gives ~78 GB addressable — a ~57 GB peak build
fits in physical RAM with the tail safely in swap. **Caveat:** don't run heavy
Windows workloads during the build; 10 GB host headroom is tight.

**Option B — a transient cloud/loan box** (≥64 GB, e.g. an r-class VM for a few
hours). Build, copy the on-disk index back, discard the box. SEISMIC's own authors
built on 64–124 GB machines, so this is the designed-for configuration.

## Build steps

1. On the build host, generate the full 150M JSONL from the spool
   (`spool_to_seismic_jsonl.py`, no `--limit`) — ~123 GB compressed spool → JSONL.
2. `build_persona_seismic.py` with DEFAULTS (parity config: n_postings 3500,
   centroid_fraction 0.1, summary_energy 0.4, max_fraction 1.5, doc_cut 15). Record
   peak_rss / build_seconds / on_disk_gb — this is also the **first true measured
   150M build point** (replaces the projection in G7).
3. Copy the on-disk index directory (~58 GB projected: 7.70 GB at 20M × 7.5) to the
   32 GB serving box.

## Serve steps

1. Load the index in **mmap / Path C mode** on the 32 GB box.
2. Confirm resident anon RAM (expect single-digit GB) and run a warm-latency probe.
3. Wire into the RRF harness for G6.

## RAM / latency budget

- **Build host:** ~55–63 GB peak (one-time). Fits ≥56 GB. ✅
- **Serve (32 GB box):** resident anon small (Path C); ~24 GB page cache for the
  ~58 GB on-disk index → ~40 % hot-set cached → cache-miss reads on the rest.
  Latency higher than a fully-RAM-resident index but **functional, no OOM**. *est.*

## Risks / honest caveats

- **Latency under tight page cache is UNMEASURED at 150M.** 32 GB caching a 58 GB
  index means real disk reads on cold candidates. Must benchmark; if p95 is
  unacceptable, either provision more serving RAM or move to Plan 01 (sharding
  reduces the per-query hot set).
- **WSL2 Option A starves Windows** during the build window — schedule accordingly.
- **One-time, not repeatable cheaply.** Every re-index (param change, corpus update)
  re-incurs the big-box build. If re-indexing is frequent, Plan 01 (always-32 GB) is
  structurally better.
- **Does NOT fix quality.** Same 0.479 as single-index G2. Unblocks G6 only.

## Success criteria

1. 150M index built (first *measured*, non-projected G7 point: real peak RSS +
   on-disk size recorded in `02_GO_NO_GO_GATES.md` / `06_FINDINGS.md`).
2. Serves on the 32 GB box via mmap with resident anon ≤ ~10 GB, no OOM.
3. Warm p50/p95 latency measured and recorded.
4. **G6 RRF parity run completes on the 150M leg** — the goal.

## Provenance

Relies on Path C (mmap) measured in `06_FINDINGS.md`, the forward-floor build-RAM
analysis (2026-06-28 session), and the `.wslconfig` headroom of the 64 GB host.
Simplest of the four plans; preferred when a build host exists.
