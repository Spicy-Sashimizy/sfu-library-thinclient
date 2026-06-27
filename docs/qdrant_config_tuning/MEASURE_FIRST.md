# Measure-first: the live Qdrant anon floor (remedy A1)

**Date:** 2026-06-26 · **Method:** live probe of the running Qdrant on the dev host.
All numbers below were **verified by read-only probe this session**, not assumed.

## A1 — the cheapest, highest-leverage test in the research

The research turn's headline remedy for the 6.55 GB anon floor is:

> **Verify the floor was measured on fully-optimized immutable segments.** The
> ~2× compressed id tracker (Qdrant PR #6023) only applies to *immutable*
> segments; appendable segments hold the *uncompressed* id-tracker map in RAM.
> If the 6.55 GB was captured right after the parallel build (segments still
> appendable), force a full optimize and re-measure RssAnon — possibly roughly
> halving the floor.

The **live collection is in exactly that state**, which makes A1 runnable now:

## Verified live baseline (2026-06-26)

| Signal | Value | Probed via |
|---|---|---|
| Qdrant process | pid 112, `/workspaces/.../.tools/qdrant/qdrant` | `pgrep` |
| Live RSS (pid 112) | ~4.5 GB | `ps` o rss |
| `splade_150m` points | **150,413,098** | `GET /collections/splade_150m` |
| `splade_150m` optimizer_status | **`ok`** | `GET /collections/splade_150m` |
| `splade_150m` status | **`grey`** ← the signal | `GET /collections/splade_150m` |
| `splade_150m` sparse index config | `{"on_disk": true}` only — **no `datatype` set** (defaults f32 raw on disk) | `GET /collections/splade_150m` config |
| `splade_150m` `default_segment_number` | 24 | live config |
| `splade_par30` (30M demo tier) | 30,000,000 pts, `status: green`, `opt: ok` | `GET /collections/splade_par30` |
| Qdrant client lib | `SparseIndexParams(datatype=Datatype{FLOAT32,UINT8,FLOAT16})` available | `.venv` introspection |

**`status: grey` + `optimizer_status: ok`** means: optimization has *settled*
(the optimizer isn't actively rewriting at this instant) **but the collection
is not yet fully green** — i.e. it built via parallel upsert into appendable
segments and the final immutable-segment compaction may not be complete, so the
uncompressed id-tracker map is likely still resident. **That is the exact
precondition A1 needs.**

## The measurement design (script: `scripts/measure_qdrant_floor.py`)

Mirrors the structure of `spike/mmap_bmp/measure_p3a_inverted_floor.py`
(baseline → action → re-measure → JSON with verdict), but on the *Qdrant* side:

1. **Snapshot before.** Read `RssAnon` (and `RssFile`, `VmRSS`) from
   `/proc/<qdrant-pid>/status` — anon is the structural floor, file is page
   cache. Record `status` (grey) + `optimizer_status`.
2. **Force a full optimize** on `splade_150m` via the `update_collection` /
   `create_field_index`-style or optimizer trigger that converts appendable →
   immutable segments, with a low `default_segment_number`. (Use the client's
   `update_collection(optimizers_config=...)` to nudge, then poll.)
3. **Poll** every 30s until `optimizer_status: ok` **AND** `status: green`,
   with a timeout cap (the 150M compaction may take minutes — record the actual
   wall-clock, never assert a win without the wait).
4. **Snapshot after.** Re-read `RssAnon`/`RssFile`; compute deltas; call
   `gc`-equivalent (no Python GC applies to the Rust process — instead, for the
   before/after to be honest we record RSS at rest after the optimize settles,
   i.e. no query load).
5. **Verdict JSON** → `data/eval_results/qdrant_floor_optimize.json`:
   before/after anon, before/after file, status transitions, wall-clock, and the
   projection (per-point anon before vs after, ×150.4M).

## What each outcome means

- **Anon roughly halves** → part of the 6.55 GB floor was appendable-segment
  overhead the compressed id tracker (PR #6023) reclaims once segments go
  immutable. The floor is *partly reclaimable*; the doc's "structural" framing
  gets a dated nuance: "structural **at steady green** = X GB; the earlier 6.55
  included Y GB of appendable overhead."
- **Anon unchanged** → confirms the floor is structural at green too; A1 is
  ruled out and the only remaining levers are **point-count reduction** (product
  call) and **index shrink via SPLADE pruning** (the B2 lever, see
  `CONFIG_LEVERS.md`). Either way the result is recorded either way — no
  "should work" without numbers (binding efficacy rule).

## Run state (2026-06-26) — STOPPED, INCONCLUSIVE, decision deferred

Ran live against `splade_150m` with `--force`. Recorded before-snapshot
(`data/eval_results/qdrant_floor_optimize.json`): **status grey, RssAnon 4.31 GB
(~28.7 B/pt)**. Nudged `indexing_threshold=0` + 8 opt threads → collection went
**grey → yellow** (compaction started as designed) **but did NOT reach
`status=green` within the 30-min hard cap** (user closed out for the night).

**Why this is inconclusive, not a result:** the after-snapshot was never captured
because 150M never settled to green in-window. Measuring anon *during* an in-flight
compaction would record the **build-time spike** (Qdrant RSS rose 4.3 → peak
~24.9 → eased to ~17.3 GB — *transient*, not the floor), so it was deliberately
*not* claimed as a before/after. The aggressive `indexing_threshold=0` nudge was
**reverted to default (20000)** so Qdrant settles the in-flight pass on its own
rather than churning overnight. No floor claim is updated by this run.

**Host safety note (from the run):** on the 31 GB dev host, RSS climbed toward,
but stayed below, the wall during compaction; `DO_SIZING.md` warns the OOM
killer can SIGKILL Qdrant silently under such pressure. A future re-run that aims
for green must (a) budget ≥ 1h for 150M and watch RSS, or (b) **first run A1 on
the green-native `splade_par30` (30M)**, where optimize-to-green is fast and the
PR #6023 immutable-compression question can be answered cheaply before tying up
the 150M box for an hour.

**Before-snapshot that DID land:** anon floor at `status=grey` ≈ **4.31 GB /
~28.7 B/pt** — lower than the 6.55 GB peak the DO_SIZING model references,
consistent with anon being point-count-linear and the 6.55 having been a
peak-under-load figure. This is a real, recorded number; only the *reclaim* half
of A1 is outstanding.

## A1 RESULT (2026-06-26, splade_par30 — the cheap path) — STRUCTURAL

Re-ran A1's reclaim half on the green-native `splade_par30` (30M), per the
deferred plan above — optimize-to-green is near-instant on an already-green
collection, so this answers the "is there any reclaimable slack at green?"
half cheaply before committing the 150M box for ≥1h.

- **What was measured:** process-level `RssAnon` before vs after a
  `indexing_threshold=0` force-optimize nudge on `splade_par30`.
- **Numbers:** RssAnon **16.969 → 16.969 GB, Δ = +0.00 GB** (within noise).
  Status stayed `green/ok`, `waited_s = 0` (nothing to compact — already
  immutable/green). `restored_ok = true` (config returned to its original
  `indexing_threshold=10000` afterward; the run is reversible/clean).
- **Verdict:** **STRUCTURAL** — at green, force-recompaction reclaims nothing.
  Consistent with the per-point id-tracker floor being required-resident on
  immutable segments, not appendable-overhead.
- **Eval script:** `scripts/measure_qdrant_floor.py` (`--collection splade_par30 \
  --force`; the run also fixed two bugs in this script — see commit c24d551:
  the restore path threw `NameError: models` and silently left the collection
  mutated; now captures+restores the *original* optimizer config in a finally).
- **Results file:** `data/eval_results/qdrant_floor_optimize_par30.json`.
- **Date:** 2026-06-26.

### Two confounds — read the par30 result as a CONTROL, not a direct grey→green test

1. **par30 was already `green` before the nudge.** It never spent time in the
   grey→green transition that is the actual 150M question. So this run shows
   "no reclaimable slack at green" — it does *not* directly measure the grey→green
   reclaim that PR #6023's compressed tracker would unlock. To test that directly
   you'd need a collection that is genuinely `grey` (appendable segments resident)
   going to `green` under the nudge. par30 is the cheap structural *control*.
2. **`anon_b_per_pt: 565.6` in the JSON is NOT a real per-point number.** The
   script reads total `/proc/<pid>/status` RssAnon for the *whole Qdrant process*,
   which serves **both** `splade_par30` and `splade_150m` (pid 1668988). At
   measurement time the process anon (~16.97 GB) was dominated by the 150M
   collection, not par30's 30M points — so dividing by 30M is meaningless. The
   *delta* (≈0) is the only honest signal here, not the absolute per-point. A
   true per-collection attribution needs an isolated one-collection Qdrant
   process or Qdrant's internal memory metrics, not process RSS.

### What this leaves open

The grey→green reclaim on a genuinely-grey 150M collection is **still unmeasured**
— par30 was green-native, so it could not test that transition. The right next
experiment is to run A1 `--force` on `splade_150m` itself, but it needs a ≥1h
green-wait with host-pressure monitoring (RSS climbs toward the OOM wall during
the build-time compaction spike; see the 150M STOPPED record above). Until that
run completes, A1's grey→green half remains INCONCLUSIVE; only the green-native
control is settled (no slack at green).

### Host-RAM reality check (2026-06-26) — the 150M grey→green run is BLOCKED, not deferred

A live read on the dev host this session shows the 150M grey→green run is **not
just deferred, it is blocked by available RAM** on the 31.6 GB host:

| Signal | Value | Source |
|---|---|---|
| `splade_150m` resting state | `grey`, `optimizer_status: ok`, idle (`update_queue: 0`) | `GET /collections/splade_150m` |
| Qdrant process RssAnon at idle | **17.38 GB**, flat (private-dirty, not reclaimable; Swap 0) | `/proc/<pid>/smaps_rollup` |
| Host MemTotal | 31.6 GB | `/proc/meminfo` |
| Host MemAvailable | **8.77 GB** | `/proc/meminfo` |
| 150M on-disk footprint | 168 GB (mmap working set that faults in during compaction) | `du` |
| Historical compaction spike (this host) | anon 4.3 → 24.9 GB peak (+20.6 GB) | prior 150M attempt record |
| Historical 150M OOMs | repeated `Out of memory (os error 12)`, free → 1.8 GB, 2026-06-19→20 | `logs/qdrant_offbmp.log` |

**Why this blocks the run now:** the prior 4.3→24.9 GB spike was measured from a
**4.3 GB** resting baseline. Today's resting baseline is **17.4 GB** (the process
now holds both collections' partially-optimized segments + resident id-tracker
anon). Projected peak on a force-optimize ≈ 17.4 + 20.6 = **~38 GB**, against a
31.6 GB host with only 8.77 GB available — i.e. **over the wall before it starts**.
Swap (11.75 GB free) would absorb some, but the historical OOMs show swap *does*
get exhausted under sustained 150M compaction → SIGKILL. `DO_SIZING.md`'s silent-
OOM warning is **proven real on this host** (the 2026-06-19/20 `os error 12` log
lines), not theoretical.

**Consequence:** running A1 `--force` on `splade_150m` unattended now would very
likely re-OOM (supervisord would restart Qdrant cleanly — verified: a clean
restart at 2026-06-26T18:08 recovered both collections 100%, no corruption — but
the run produces no after-snapshot, same failure mode as the 30-min-cap attempt).
To actually measure the grey→green reclaim, one of these must hold first:
(a) the 31 GB host gets more RAM (>≈48 GB) for headroom, **or**
(b) 150M is rebuilt smaller (point-count reduction) so the resting floor drops
    below ~4 GB again, leaving room for the compaction spike, **or**
(c) an isolated single-collection Qdrant process is used to test the grey→green
    transition cleanly (e.g. par30 only, with a *deliberate* appendable-segment
    upsert to force grey, then A1 `--force`) — **but see the noise-floor caveat
    below: a small appendable segment's reclaim is below the measurement floor, so
    this only works if the appendable segment is LARGE (which reintroduces RAM
    cost). Not a free lunch.**

### Why option (c) is NOT the easy out it first appears (noise-floor + the right instrument)

An earlier draft suggested option (c) as "the cheapest unblocked path." Closer
analysis this session shows it is **below the measurement noise floor** as stated:

- The PR #6023 reclaim signal is the uncompressed id-tracker of an **appendable**
  segment returning to RAM-availability when that segment compacts to immutable.
- Upserting a *small* batch (~50k pts) into par30 creates one appendable segment
  whose id-tracker is **KB-MB in size** — and we are measuring against a process
  whose baseline is **17.4 GB anon / 22 GB jemalloc-resident**, with normal
  jemalloc-arena churn on the order of MB. A KB-MB reclaim is indistinguishable
  from allocator noise on these gauges.
- Making the appendable segment large enough to resolve (≫50 MB of id-tracker ≈
  millions of points) reintroduces real RAM cost — collapsing back into the same
  headroom problem that blocks the 150M run, just on par30.

**The right instrument (added this session):** `scripts/measure_qdrant_floor.py`
now captures Qdrant's `/metrics` jemalloc gauges — `memory_resident_bytes`,
`memory_active_bytes`, `memory_retained_bytes` — in both before/after snapshots,
in addition to OS `/proc` RssAnon. These are **Qdrant-allocator-internal** and
**collection-agnostic**: a compaction that returns pages to the OS drops them
immediately, regardless of which collection held them, and they do *not* lag the
way OS RssAnon does (the kernel reclaims freed anon lazily). So this is the sharp
lens for when a *measurable* target exists. Baseline values recorded live
(2026-06-26, idle): `memory_resident_bytes` ≈ **22.20 GB**, `memory_active_bytes`
≈ **22.07 GB** (vs OS `RssAnon` ≈ 16.98 GB, `VmRSS` ≈ 23.40 GB — the gap between
jemalloc-resident and OS-anon is the file-backed/non-jemalloc portion).

**Net:** the instrument is now correct and sharper; the target is still not
unblocked-measurable on this 31 GB host. The grey→green half of A1 stays
INCONCLUSIVE pending (a) a bigger host, or (b) a smaller 150M rebuild that drops
the resting floor enough to leave headroom for the spike.

## What each outcome means (still the decision frame when re-run completes)
