# Pre-registration DRAFT — WSL2 re-host: the ragged-edge convergence split + F5 residue eviction, on this host's own band

**Date:** 2026-09-25 · **Status: DRAFT — awaiting the operator's freeze; no
cell may run.** Freeze requires, each in its own commit: (a) the §6 gaps
closed (F5 `.so` rebuilt and verified on the served binary, driver flag,
orchestrator), (b) the §5 calibration window executed and its anchor/mechanism
facts recorded **here**, (c) the §7 bars frozen. Nothing in §7 is judgeable
before that.

---

## 1. Why this document exists (the host loss)

As of **2026-09-25** the operator has **no access to any cloud host**. The
**OCI E5, 62 GiB, kernel 6.17.0-1018-oracle, no swap** box that produced every
Tier-2/3 cell (`PREREGISTRATION_TIER23.md`, `RESULTS.md` §§18–22) and every
small-machine lever cell (`spike/archive/smallmachine_levers/PREREGISTRATION.md`
phases A′/A″) is **permanently gone**. The only host is this WSL2 machine:
**31 GB RAM total** (26 GB available at idle, ~5 GB used before any cell),
16 GB swap, 16 cores, kernel `6.18.33.2-microsoft-standard-WSL2+`,
`/sys/kernel/mm/lru_gen/enabled` = `0x0007` (both arms toggleable), cgroup v2 —
the host that ran R1/R2/R3 and all of Tier-1d.

Two OCI questions were left open when the host died. This document re-poses
the part of them that **can** be asked on this host, and says plainly which
part cannot.

### 1.1 What is NOT in this document (CLOSED-UNRUNNABLE)

Recorded so no reader mistakes this pre-registration for a replication:

- `t23c_mglru_cap28g_rep2`, the AMEND1 classic descent (24/22/20/18/16 GB),
  and therefore bars **B1x/B5x** — dead. `PREREGISTRATION_TIER23_AMEND1.md`
  is a draft that can never be frozen.
- The small-machine bars **S1–S5** and the **34 GB** big-RAM regression
  control — dead; 34 GB is 3 GB above this host's *total* RAM.
- The OCI lane of the write-up's **figure 8** at 16 GB — dead; the run-4
  cells timed out leaving no JSON and the host that would back-fill them is
  gone.

The arithmetic, in one line each: the OCI two-population footprint is
**29.1 GB = 93.9% of this host's 31 GB total**, so the "everything fits"
control cannot exist here; a **28 GB cap leaves 3 GB** for the kernel, the dev
container and the orchestrator while idle already consumes ~5 GB
(31 − 5 = **26 GB < 28 GB**, so the cap is looser than the RAM available to
fill it); and decisively, **cap 28 GB is 8.6 GB above this host's own 19.4 GB
footprint** — the whole OCI ladder (25–30 GB) sits in this host's
"nothing-is-evicted, nothing-sorts" regime, where by construction every arm
looks alike. Full statement:
`docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`,
Addendum 2026-09-25.

### 1.2 What IS in this document (RE-HOSTABLE)

Two arms, both living entirely inside **this host's own band**:

- **W-split** — the *question* behind the dead 16 GB figure, re-posed on this
  host's constants: **is there a rung just above the hot set where the real
  stack converges sometimes and thrashes sometimes, and what is the split?**
  The OCI evidence died at n=2 (one converge, one thrash, sml phase A″ run 4).
  Here it gets n=5.
- **W-f5** — the **F5 `release_pages_except`** residue-eviction lever on the
  real stack, which has **never been measured on any host**
  (`04_CONVERGENCE_ARTIFACT.md` §5.3: the 2026-07-14 16 GB cell was a NULL
  with a diagnosed scope bug; the bug is FIXED IN CODE, fork `2c4d863`, and
  **no `.so` was rebuilt** — the served binary still carries the pre-fix hook).

**This is a re-posing, not a replication.** Every rung, bar and denominator
below is derived from *this* host's measured constants. No number here is
comparable cell-for-cell with an OCI number, and no verdict here supersedes
a Tier-2/3 verdict.

---

## 2. Measured constants this design builds on (this host)

From R1/R2/R3 (2026-07-14/15/16), as pinned in the regime-map table of
`04_CONVERGENCE_ARTIFACT.md` ("Regime map definitions (2026-09-13)"):

| quantity | value | evidence |
|---|---|---|
| hot set (re-touched population) | **10.1 GB** | R3 12 GB cell drained to 10.13 GB; R2 12 GB converged rssfile 9.94 GB |
| anon | **1.2 GB** | R2 24 GB post-pass-1 accounting |
| **lower boundary** (hot set + anon) | **11.3 GB** | below it no policy converges — capacity arithmetic |
| **footprint / upper boundary** (both populations + anon) | **19.4 GB** | R2 24 GB after pass 1: cgroup file 18.17 GB + anon 1.2 GB; bracketed — 17 GB sorts, 24 GB fits, nothing measured between |
| the ragged edge | **between 10 and 11 GB** | R2: 11 GB converges (18 ms), 10 GB plateaus (1.42 s) |
| steady p50 reference | **~19–22 ms** | R1 §1; every cap ≥12 GB reaches it |
| near-zero threshold | **2,500 majflt/pass** | driver rule, unchanged across every tier |

**Do not carry OCI constants into this document.** The OCI stack's hot set is
13.76 GB against this host's 10.1 GB on the *same* 150M manifest
(`data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json`) — a **1.36×**
difference the record does not explain (host, codec revision and serving
config all moved between 2026-07-14 and 2026-09-01). That unexplained gap is
itself a reason no cap number transfers between the two hosts.

**Host-budget ceiling (hard).** Usable RAM for a capped cell is
31 − ~5 = **26 GB**. This pre-registration declares a hard ceiling of
**24 GB** and uses nothing above **22 GB**, leaving ≥9 GB for the kernel, the
dev container, the orchestrator and the OS at the highest rung
(22 + 5 = 27 of 31 GB, 4 GB slack).

---

## 3. Arms (levers)

- **L0 — baseline.** The Tier-2/3 / R2 protocol as-is: normal load, no
  mitigation. `SFU_SEISMIC_PREFLOOR_HOTSET=1` (residue-bearing load — the
  production load path, and the population F5 exists to remove).
- **F5 — map-guided residue eviction.** After load, before pass 1, call the
  fork's `release_pages_except(<hot-set sidecar>)` so the residue is evicted
  **by name** rather than learned by reclaim. Production analogue: startup
  hygiene eviction that knows which pages matter. Fork `2c4d863`
  (`spike/seismic_upstream/src/mmap_io.rs` + `src/pylib/mmap_index.rs`;
  patches `spike/seismic_upstream_fork.patch`,
  `spike/seismic_upstream_f5_scope_fix.patch`). **Unmeasured on the real
  stack on any host.**
- **L3 — map-blind one-shot reclaim** (comparison arm only, already shipped as
  `t23_convergence_ladder.py --postload-reclaim-bytes N`). Included so F5's
  map-*guided* advantage over a map-*blind* nudge is measurable on this host;
  L3's own mechanism is already confirmed on the real stack (sml run 4:
  requested 14.00 GiB, **freed 15.04 GB in 2.81 s, status=ok**).

---

## 4. Ladder (frozen rung list — fits a 31 GB host with headroom)

| rung | regime on this host | role |
|---|---|---|
| **9 GB** | below the 11.3 GB lower boundary | **floor falsification** — no lever may converge |
| **10 GB** | below the lower boundary | **plateau anchor** (R2: 1.42 s) |
| **11 GB** | at the lower boundary | **edge rung A** — the split question |
| **12 GB** | just inside the band | **edge rung B** — the split question |
| **13 GB** | inside the band | **converge anchor** |
| 14 / 16 / 18 GB | inside the band (11.3–19.4) | F5 efficacy rungs |
| **22 GB** | above the 19.4 GB footprint | **above-footprint control** + determinism control |

Nothing above 22 GB; hard ceiling 24 GB (§2). Worst case concurrent RAM =
22 GB cap + ~5 GB host baseline = **27 of 31 GB**.

**Rung provenance.** The OCI question was asked at 16 GB because the OCI floor
was 14.8 GB (16/14.8 = 1.08×). Scaled onto this host's 11.3 GB floor that is
**12.2 GB**, which is why edge rung B is 12 GB; edge rung A is 11 GB because
R2 already bracketed the edge between 10 and 11. The two edge rungs bracket
the scaled analogue from both sides, and the placement is bound **before** any
cell runs so it cannot be chosen post-hoc.

---

## 5. Calibration window (exploratory; bars NOT frozen)

One window, single cells, no replicates, no bar may be quoted from it. Its
output lands in a dated `### §5 RECORD` subsection **here**, and the §4 rung
list may be adjusted **once**, recorded, before freeze (the Tier-1d/Tier-2-3
one-shot rule).

1. **Anchor check** — L0 classic at 10 and 13 GB. Do R2's 2026-07-15 anchors
   still hold on the 2026-09-25 boot (31 GB profile, kernel 6.18.33.2+,
   MGLRU-default-on)? If either anchor has moved, **the constants in §2 have
   drifted and the whole rung list is re-derived before freeze.**
2. **Above-footprint control** — L0 classic at 22 GB: near-zero from pass 2,
   steady p50 within ±16% of the 19–22 ms reference, `pgscan` ≈ 0.
3. **F5 mechanism check** — F5 classic at 16 GB: verify (a) released bytes
   ≈ footprint − hot set ≈ **9.3 GB**, (b) **RssFile actually falls** by
   approximately that much (the 2026-07-14 NULL reported "released 16.45 GB"
   with RssFile unchanged — that accounting bug is what the scope fix and the
   corrected byte accounting address, and this check is the regression test),
   (c) what leaves is **residue, not hot set**: post-F5 `hot_resident_pct`
   ≥ 90% of its pre-F5 value.
4. **Wall-time budgeting** — record per-cell wall at 11/12 GB so §9's window
   budget is real rather than estimated.

---

## 6. Gaps to close before freeze (each its own commit)

1. **F5 `.so` rebuilt and served.** Build the fork at `2c4d863` (or later)
   **portable**: `-C target-cpu=x86-64-v3`, **never** `target-cpu=native`
   (`spike/CLAUDE.md`; v3 is the portable target, gates recleared
   2026-07-17). Verify on the *served* binary, not the source tree, that
   `release_pages_except` covers all mapped slabs (the Rust test
   `release_pages_except_covers_all_slabs` is the synthetic proof:
   dotvbyte 9,600 B → 42,554 B, f16 4,200 B → 41,354 B; the real-stack proof
   is §5 check 3).
2. **Driver flag** `--f5-release-except <sidecar path>` in a `wslrh_` clone of
   `r2_convergence_ladder.py`, recording `requested_bytes`, `released_bytes`,
   `write_status`, `elapsed_s` and RssFile/`hot_resident_pct` pre and post
   into the cell JSON — the same shape as the existing
   `--postload-reclaim-bytes` block, so F5 and L3 are directly comparable.
3. **Orchestrator** `wslrh_orchestrator.sh` — a `t1d_wsl2_orchestrator.sh` /
   t23b clone with: per-cell arm toggle and **trap-restore of
   `lru_gen=0x0007`**, any-date SKIP resume, per-cell protocol verification
   with **quarantine-and-abort on mismatch**, deadline shed, and the §8
   swap check.
4. **§5 calibration executed** and recorded here.
5. **§7 bars frozen** in their own commit, after 1–4.

---

## 7. Bars (TO BE FROZEN after §5 — drafted intent only)

Bar-design lessons adopted verbatim from Tier-1b / Tier-2/3 / Tier-1d: **no
strictly-monotone clauses** (zero-ties killed B4), **no gauge thresholds with
arm-dependent semantics** (`active_file` killed B4's second clause), **±16%
noise floor**, every bar names its **cells and its denominator**, and every
magnitude claim is magnitude-weighted. Additionally, from the ES-2 failure:
**no bar may demand more than the mechanism's physical ceiling.**

### W1 — the split (the headline). Measurement bar; all outcomes pre-bound.

At each edge rung (**11 and 12 GB**), arm **classic**, lever **L0**:
**5 independent cold replicates** each. For each rung record
`k` = number of replicates that reach near-zero (≤2,500 majflt/pass) within
12 passes. Readings, bound now:

- `k = 5` → the rung is **deterministic-converge**.
- `k = 0` → the rung is **deterministic-thrash**.
- `1 ≤ k ≤ 4` → **SPLIT CONFIRMED** at that rung; the point estimate is `k/5`
  reported with a Wilson 95% interval, and the OCI observation
  ("L41/classic/16 G converges non-deterministically") is reproduced *in
  kind* on a second host and a second set of constants.

**The falsifiable content** (so W1 is a test and not a tautology): the
pre-registered claim is *there exists a rung among {11, 12 GB} with
1 ≤ k ≤ 4*. If both rungs return `k ∈ {0, 5}`, the claim is **REFUTED** and
the recorded headline is "the ragged-edge split does not reproduce on this
host at the scaled rungs" — which retires the phenomenon rather than deferring
it.

### W2 — anchors (validity control; W1 is void without it)

L0 classic at **10 GB** plateaus in **both** replicates (steady majflt ≥ 10×
the near-zero threshold) and at **13 GB** reaches near-zero in **≤ 4 passes**
in both. If either anchor fails, §2's constants have drifted, the rung
placement is invalid, and **the window is void** — no W1 reading may be
quoted from it.

### W3 — arm contrast at the edge (recorded, no threshold)

The W1 protocol repeated at the rung that W1 finds most informative (declared
at freeze as: the rung with `k` nearest 2.5, else 12 GB), arm **mglru**,
5 replicates. `k_mglru` is reported beside `k_classic`. The §22 mechanism
predicts MGLRU converts the split into deterministic thrash (it never
re-promotes refaulting pages, so the hot set never stabilises); recorded
**whichever way it falls**, no pass/fail.

### W4 — F5 efficacy (the lever's first real-stack measurement)

Over the band rungs **12 / 14 / 16 / 18 GB**, arm **classic**, ×2 replicates,
at every rung where L0 shows a **visible sort** (some pass ≥ 2 whose p50 is
> 5× the converged p50 — the figure-8 classifier constant) or fails to
converge: **F5 cuts total major-fault work to convergence by ≥ 50%** versus
L0 at the same rung, in **both** replicates, magnitude-weighted, with the L0
denominator named per rung.

**Why 50% and not 80%.** The Tier-1b ES-2 bar asked for ≥80% and was
**unreachable by construction**: pages that were never loaded must be read
once, so the mechanism's physical ceiling is ~75% (measured: −75.2% at the
marginal rung, −74.7% at boundary, both landing exactly on the irreducible
floor). A 50% bar sits clear of the ±16% noise floor and clear of the
ceiling.

### W5 — F5 does not regress the above-footprint case

At **22 GB** (above the 19.4 GB footprint, where nothing is evicted and the
lever should be a no-op), ×2 replicates: F5's steady p50 within **±16%** of
L0-22G, and **no pass slower than L0's same pass by more than 16%**. F5's
load-time cost (the release call's own wall, §5 check 3 measured it) is
**recorded, not barred**.

### W6 — floor falsification (pre-declared expected outcome)

At **9 GB** (below the 11.3 GB lower boundary), **no lever** — L0, F5 or L3 —
achieves near-zero. This is the expected outcome and is recorded as a control.
**If F5 rescues 9 GB, the floor model is wrong and that is the headline
finding of the window**, superseding W4.

### W7 — F5 vs L3 (map-guided vs map-blind; recorded, no threshold)

At the W4 rung with the largest L0 sort, one L3 cell per replicate with
`--postload-reclaim-bytes` set to the same byte count F5 released. Does
knowing *which* pages to drop beat dropping *that many* pages? Recorded
whichever way; sml run 4 already showed L3 alone does not rescue the OCI
prod-load path at its edge rung, so a null here is an informative replication.

---

## 8. Non-interference (HARD BARS)

- **N1 — cap ceiling.** No cgroup cap above **24 GB**; no rung above 22 GB.
  The orchestrator refuses a cap outside the §4 list.
- **N2 — read-only data.** `data/seismic_150m/` is IRREPLACEABLE and
  READ-ONLY, always. `data/thinclient_index/` is read-only for every cell.
  No cell writes anywhere but `data/eval_results/`.
- **N3 — single-window exclusivity.** This working tree is shared by several
  agents. A window may start only when **no other page-cache-heavy run is in
  flight against `data/thinclient_index`**; the orchestrator takes a lock file
  and refuses to start if one is held. Concurrent cgroup-cap ladders corrupt
  both runs.
- **N4 — restore.** Trap-restore `lru_gen` to **`0x0007`** and remove the cell
  scope on every exit path, including SIGINT and deadline shed. A window that
  cannot restore is a defect, recorded as one.
- **N5 — timeouts are never raised mid-window.** `CELL_TIMEOUT` is fixed at
  freeze (draft intent: **2,400 s**). A shed cell is recorded with its
  `.log`/`.status` as evidence and is **never retried at a raised timeout**
  (the T1d-14 rule; §28's eight fault-around sheds are the precedent — the
  shed *is* the readout).
- **N6 — swap quarantine (new on this host; the OCI box had no swap).** This
  host has **16 GB of swap**. Any cell whose `VmSwap > 0` at any pass boundary
  is **quarantined and excluded from every bar** — a swapping cell measures
  the swap subsystem, not page-cache reclaim, and no OCI cell could ever have
  done so. The existing `r2_convergence_ladder.py` VmSwap rule is adopted
  verbatim and extended to abort the window on a second occurrence.
- **N7 — single-host clause (replaces Tier-2/3's OCI trial-horizon N7).**
  There is no fallback host. If this host is lost, this line **closes** —
  recorded as closed-unrunnable, not deferred to a host that does not exist.
- **N8 — protocol pin.** Every cell JSON records its lever arm
  (`lever: "L0"|"F5"|"L3"`), its `prefault_gate`, its arm/`lru_gen` readback,
  its `memory.max` readback, and for F5/L3 the requested/released bytes.
  Mismatch → quarantine the cell and abort the window.

---

## 9. Output schema (to be pinned at freeze)

One JSON per cell, committed, at:

```
data/eval_results/wslrh_<lever>_<arm>_cap<N>g_rep<k>_<YYYYMMDD>.json
```

Schema = the `t23_convergence_ladder.py` cell schema unchanged (per-pass
`p50_ms`, `p95_ms`, `mean_ms`, `max_ms`, `majflt`, `ms_per_fault`, `wall_s`,
`vm`, `cg_delta` over the cgroup counters, `cg_gauges`, `memory_current`,
`vmstat_global_delta`; plus `load_s`, `manifest`, `queries`, `top_k`,
`converged_kind`), **plus** a `rehost` block:

```json
"rehost": {
  "host": {"total_ram_gb": 31, "kernel": "6.18.33.2-microsoft-standard-WSL2+",
           "lru_gen_enabled": "0x0007", "swap_total_gb": 16, "cores": 16},
  "constants": {"hot_set_gb": 10.1, "anon_gb": 1.2,
                "lower_boundary_gb": 11.3, "footprint_gb": 19.4,
                "source": "R1/R2/R3 2026-07-14/15/16"},
  "lever": "L0|F5|L3",
  "cap_gb": 12, "arm": "classic|mglru", "replicate": 1,
  "f5_release": {"requested_bytes": 0, "released_bytes": 0,
                 "write_status": "ok", "elapsed_s": 0.0,
                 "rssfile_pre": 0, "rssfile_post": 0,
                 "hot_resident_pct_pre": null, "hot_resident_pct_post": null},
  "vmswap_max_kb": 0,
  "classification": "near-zero|transient|plateau|timeout"
}
```

`classification` uses the write-up's figure-8 classifier constants verbatim:
near-zero = 2,500 majflt/pass; *transient* = converged but with some pass ≥ 2
whose p50 exceeds 5× the converged p50; *plateau* = never near-zero.

**Replicate identity.** The real-stack driver replays a **fixed** 40-query
mix (`data/eval_results/e7b_encoded_queries.json`, first 40 pre-encoded
terms, `--top-k 50`, `--queries 40`) — there is **no seed knob**, so
replicates are not seeded variants: they are **independent cold cells**,
identical by construction, and what varies between them is cold-fault
ordering. That is precisely the variable W1 measures. Independence is
enforced by a fresh process and a fresh cgroup scope per cell, with the cell
order fixed in advance by a permutation drawn from **seed 20260925** and
written into the frozen cell list, so run-order drift cannot be chosen
post-hoc.

---

## 10. Determinism bars

- **D1 — control reproducibility.** Two back-to-back **22 GB L0 classic**
  cells (above the footprint; nothing under test) must **classify
  identically**, both be near-zero, and have converged p50 within **±16%** of
  each other. If the no-pressure control is not reproducible, this host is too
  noisy to measure a converge/thrash split and **the window is void** — W1 is
  unreadable, not "inconclusive".
- **D2 — F5 accounting determinism.** Two **22 GB F5** cells must report
  `released_bytes` within **±1%** of each other and identical `write_status`.
  The 2026-07-14 NULL's headline defect was a byte count that did not
  correspond to any residency change; a lever whose own accounting is not
  reproducible cannot carry W4.
- **D3 — schema fingerprint.** Every committed cell JSON validates against the
  §9 schema; a missing or renamed field is a harness defect recorded in
  `RESULTS.md`, never silently accepted.

---

## 11. Budget

Rough, to be replaced by §5's measured walls before freeze. Converging cells
at 12–22 GB are minutes (R2: 18 ms steady, ≤5 passes); plateau and split-loss
cells run to the 2,400 s cell timeout.

| block | cells | est. wall |
|---|---|---|
| §5 calibration | 5 | ~1 h |
| W1 (11 and 12 GB × 5 reps, classic L0) | 10 | ~2–4 h (timeout-dominated if k is low) |
| W2 anchors (10, 13 GB × 2) | 4 | ~1.5 h |
| W3 (one rung × 5 reps, mglru) | 5 | ~1–2 h |
| W4 (12/14/16/18 GB × L0,F5 × 2 reps) | 16 | ~3–5 h |
| W5 (22 GB × L0,F5 × 2) + D1/D2 | 4 (shared) | ~0.5 h |
| W6 (9 GB × L0,F5,L3) | 3 | ~2 h (all expected to time out) |
| W7 (one rung × L3 × 2) | 2 | ~0.5 h |

Deadline-bounded orchestrator, verdict-critical cells first (W2 anchors → W1
→ W4), any-date SKIP resume so a shed window resumes rather than restarts.

---

## 12. Efficacy recording (per `.claude/CLAUDE.md`)

Cells land in `data/eval_results/wslrh_*.json` (committed). Verdicts, numbers
and **absolute dates** go into a new `RESULTS.md` section (this is the same
research line, so it stays in `spike/convergence_repro/RESULTS.md`, numbered
after §32) **and** into a dated addendum of
`docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`,
in the same push as the cells. Every quoted number names its cell file and its
denominator. Until a window runs, **F5's real-stack efficacy remains
"IMPLEMENTED, EFFICACY UNMEASURED"** wherever it is mentioned, and the
ragged-edge split remains an OCI observation that has not been reproduced on a
second host.

The write-up's **figure 8** gains a third host lane only after W1/W2 record
cells with result JSONs — the small-machine OCI annotation stays an
annotation forever, because those cells left no JSON and their host is gone.

---

## 13. Relation to the documents this one does not supersede

- `PREREGISTRATION_TIER23.md` and its judged verdicts (B1–B5, 2026-09-01) —
  **untouched**. Judged harnesses and judged bars are never edited
  retroactively, and no cell here is comparable to one there.
- `PREREGISTRATION_TIER23_AMEND1.md` — CLOSED-UNRUNNABLE 2026-09-25; this
  document is **not** its replacement. AMEND1 asked where the *OCI* classic
  cliff sits; that question has no answer now and no answer here.
- `spike/archive/smallmachine_levers/PREREGISTRATION.md` — its phase-A′/A″ records
  stand as OCI evidence; its S1–S5 bars are closed-unrunnable. W1 re-poses one
  of its questions on different constants and does **not** discharge its bars.
- `PREREGISTRATION_TIER1D.md` / `PREREGISTRATION_TIER1E.md` — the synthetic
  line, caps ≤ 8 GiB, unaffected by the host loss and independent of this
  document.
