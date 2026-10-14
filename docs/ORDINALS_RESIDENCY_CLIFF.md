# Ordinals residency cliff — pre-registration + result (2026-09-25)

**Status:** ACTIVE — pre-registered 2026-09-25 (bars frozen before the first
cell ran), measured the same day; §7 verdict REFUTED.

The question is doc `seismic_150m_testbed/18_ORDINAL_ADDRESSING_DESIGN.md` §14
"not settled" **#5**, quoted verbatim because it is the bar:

> **The residency cliff is unmeasured, and it is the only remaining case for
> this module.** Staged SQLite at 4.0 ms assumes the hot B-tree pages stay
> cached. What happens to that 4.0 ms as available page cache shrinks — and
> whether ordinals' 1.5 ms holds while it degrades — decides whether ordinal
> addressing is worth anything at all.

`THIN_CLIENT_SWAP.md` states the mechanism being tested: ordinals do not
replace `meta.sqlite`, so their **1.96 GB is additive** to its **24.9 GB**;
what they buy is that the filter stage's page-cache working set shrinks from a
randomly-descended 24.9 GB B-tree to 1.96 GB of arrays. If that is worth
anything, the SQLite arm must fall off a cliff under a cap the ordinal arm
survives.

Related: `seismic_150m_testbed/18_ORDINAL_ADDRESSING_DESIGN.md` (design, §14's
filesystem correction), `THIN_CLIENT_SWAP.md` (filter-stage paragraph),
`spike/convergence_repro/` (the cap-ladder cell protocol this borrows).

---

## 1. What is measured

The filter stage only — `retriever._post_filter` — over candidate lists
captured once from real `search()` calls, replayed identically to both arms.
This is §14's own method, and it is what keeps the cap meaningful: a process
that also holds the 42 GB of staged SEISMIC shards and the tantivy sections
would spend the cap on them.

| arm | `_ordinals` | `meta.sqlite` | working set under test |
|---|---|---|---|
| `sqlite` | `None` | staged, local disk | 24.9 GB B-tree, random descents |
| `ordinals` | `OrdinalSpace` on staged arrays | staged, local disk (fallback only) | 1.955 GB of mmap'd columns |

Both arms run the **shipped** `_post_filter`, including the ordinal arm's
SQLite fallback for ids with no ordinal. Both artifacts are on **local disk**
(`/var/tmp`, overlayfs). That is not a detail: §14's whole lesson is that
measuring ordinals against `meta.sqlite`-on-9p misattributes a filesystem win
to the addressing change, and in this container
`data/thinclient_index/` **is** 9p (`v9fs`, re-verified 2026-09-25).

### Ordinal-space authorisation

`data/thinclient_index/manifest.json` carries **no** `ordinal_space_id`, so
`load_if_enabled` fails closed and ordinals cannot be switched on by environment here.
The harness therefore constructs `OrdinalSpace(dir, {"ordinal_space_id": ...})`
directly — the same call `load_if_enabled` makes — and **proves the pairing
first** rather than asserting it: `ordinal_space.json`'s recorded source
identity must equal the on-disk `meta.sqlite` exactly. Verified 2026-09-25:

```
bytes     24,908,001,280 == 24,908,001,280
mtime_ns  1,781,573,592,207,934,800 == 1,781,573,592,207,934,800
space_id  7012d0ed-52a2-4899-a8ec-f188e53b8cf3
```

A mismatch aborts the run. The index manifest is **not** edited — enabling
ordinals globally would change what every other process on this working tree
serves.

## 2. How the cap is applied, and why not the way `convergence_repro` does it

`spike/convergence_repro/HOST_RUN.md` applies caps with `docker run
--memory=X --memory-swap=X` **on the host**, and says plainly that the dev
container "has no usable docker daemon, `/sys/fs/cgroup` is read-only, and no
memory cap can be enforced there". Re-verified inside this container
2026-09-25:

- no `docker` binary; no `systemd-run`; no `vmtouch`; no `fio`
- `/sys/fs/cgroup` mounted `cgroup2 (ro,...)`; `mount -o remount,rw` → EPERM
- `CapEff` = `0` unprivileged and `0x00000000a80425fb` under `sudo` — **no
  CAP_SYS_ADMIN** either way
- `/proc/sys/vm/drop_caches` not writable

As of 2026-09-25 the OCI and DO hosts are gone, so there is no other machine to
run this on. The cap is therefore applied the only way left:

- **cap** = an **mlock'd anonymous balloon** in a child process, sized so that
  `MemAvailable` lands on the rung. Each rung records the `MemAvailable`
  actually observed (`cap_effective_gib`) rather than trusting the arithmetic.
- **evict** = `posix_fadvise(POSIX_FADV_DONTNEED)` per file (the `vmtouch -e`
  analogue), verified with `mincore(2)`; global `drop_caches` is never used.
- **residency** = `mincore(2)` over the mapped artifact, before and after each
  arm.
- **faults** = `majflt` from `/proc/self/stat`, per pass.

Everything else follows `convergence_repro/cell.sh`'s cell shape: preflight →
record host state → evict and verify → timed passes with per-pass majflt.

**This is a weaker instrument than `memory.max` and is recorded as such.** A
cgroup cap bounds the cgroup's own page cache; an mlock'd balloon bounds the
*machine's* free memory, so the kernel's reclaim decisions are global and other
tenants' pages compete. Conclusions are drawn from the shape of the two curves
against the same instrument, not from absolute ms.

## 3. Query set, ladder, seed

- **Queries**: 40 drawn with seed **20260925** from `data/sfu_eval_queries.json`
  (120 human SFU eval queries), `mode=splade`, `top_k=50`, filters
  `{year_range: (2010, 2025), type: "article"}` → `OVERFETCH_FILTERED=10` ⇒
  **500 candidates per query**, the same stage size §14 reports (4.0 ms / 1.5 ms
  at 500 candidates). Captured once by
  `scripts/experiments/eval_ordinals_cliff_capture.py`; the ladder never
  re-runs a search engine.
- **Ladder** (`MemAvailable` during the cell, 6 rungs, bracketing both working
  sets): **24, 16, 10, 6, 3, 1.5 GiB**. 24 GiB ≳ the 24.9 GB B-tree, 1.5 GiB
  ≲ the 1.955 GB of arrays.
- **Passes**: 3 per arm per rung. Pass 1 is the cold transient (immediately
  after a verified eviction); **the bars are judged on pass 3**.
- **Arm order**: `sqlite` then `ordinals` within every rung, each preceded by a
  full eviction of **both** artifacts with residency verified ≈ 0, so neither
  arm can inherit the other's resident pages. Order is not randomised because
  the eviction removes the effect randomisation would control for.
- **Floor**: the balloon never takes `MemAvailable` below 3 GiB of headroom
  beyond the rung; a rung that cannot be reached is recorded as such rather
  than being approximated.

## 4. Pre-registered bars (FROZEN before the run)

Let `S(c)` / `O(c)` be the pass-3 p95 filter-stage ms at effective cap `c`, and
`c_hi` / `c_lo` the largest / smallest reached rung.

| bar | statement | decides |
|---|---|---|
| **B1** | `S(c_lo) / S(c_hi) >= 3` | a cliff exists for SQLite in the measured range |
| **B2** | `O(c_lo) / O(c_hi) <= 1.5` | ordinals hold across the same range |
| **B3** | `(S(c_lo)/O(c_lo)) >= 2 * (S(c_hi)/O(c_hi))` | the ordinal advantage GROWS as memory shrinks |
| **B4** | pass-3 `majflt_sqlite(c_lo) >= 10 * majflt_ordinals(c_lo)` | the cliff is page faults, not CPU |
| **B5** | 0 kept-list mismatches between arms, every rung, every query | the run is admissible at all |

**Verdict rule, fixed in advance.** B5 is a gate: a single mismatch voids the
run. Given B5: **SUPPORTED** iff B1 ∧ B2 ∧ B3; **REFUTED** iff B1 fails (no
cliff ⇒ §14 #5 resolves against the module); **PARTIAL** otherwise, and a
partial result does not license adopting ordinals.

## 5. Known confounds, recorded before the numbers exist

1. **The box is not quiet.** Five other agents hold this working tree and run
   their own Python. `convergence_repro`'s RULE ZERO asks for a quiet box and
   it cannot be honoured. Reported, not corrected for.
2. **Balloon ≠ cgroup cap** (§2). Absolute ms are not comparable with §14's
   4.0 / 1.5 ms, which were taken uncapped on a 56 GB host.
3. **`MemAvailable` is an estimate**, and mlock'd anon pages change what the
   kernel counts as reclaimable. The rung labels are targets; the recorded
   `cap_effective_gib` is the measurement.
4. **The SQLite arm's B-tree residency is workload-shaped**: 40 queries × 500
   candidates touch a small fraction of 150,413,098 rows, so the *hot* set is
   far smaller than 24.9 GB. This biases **against** finding a cliff, which is
   the safe direction for a bar that has to justify a module.
5. **Quiet-host gate, added 2026-09-25 after the warm-cache run was
   contaminated.** Every cell blocks until the 1-minute load average is ≤ 3.0
   and no other Python benchmark is running (`--require-quiet`, default 3.0);
   the gate's outcome, the wait, and the load are recorded per arm. A cell that
   times out waiting is recorded `quiet: false` and is not silently promoted to
   a clean measurement. The warm-cache metric-3 run earlier the same day was
   taken at `load1 = 11.5` and produced the giveaway that the instrument was
   measuring the host, not the cache — cache-ON came out *faster* than
   cache-OFF, which is impossible.

## 6. Commands

```bash
# 1) capture the candidate lists once (loads the full retriever)
.venv/bin/python3 scripts/experiments/eval_ordinals_cliff_capture.py \
    --n 40 --top-k 50 --seed 20260925 \
    --out data/eval_results/ordinals_cliff_candidates_20260925.json

# 2) the ladder (stages meta.sqlite ~24.9 GB + the arrays ~1.96 GB to /var/tmp)
.venv/bin/python3 scripts/experiments/eval_ordinals_cliff.py \
    --candidates data/eval_results/ordinals_cliff_candidates_20260925.json \
    --caps-gib 24,16,10,6,3,1.5 --passes 3 --require-quiet 3.0 \
    --out data/eval_results/ordinals_cliff_20260925.json
```

## 7. RESULT — MEASURED 2026-09-25: **REFUTED**

**Verdict by the §4 rule: B5 passes (the run is admissible), B1 fails ⇒
REFUTED.** There is no residency cliff for the staged-SQLite filter stage
anywhere in a ladder that runs from 23.97 GiB of available page cache down to
**1.86 GiB — below the ordinal arrays' own 1.955 GB**. §14 "not settled" #5
was *the only remaining case for this module*, and it resolves against it.

- **Script**: `scripts/experiments/eval_ordinals_cliff.py` (+
  `eval_ordinals_cliff_capture.py`)
- **Results**: `data/eval_results/ordinals_cliff_20260925.json`
  (candidates: `ordinals_cliff_candidates_20260925.json`; the D1-confounded
  first run is kept as `ordinals_cliff_d1confounded_20260925.json`)
- **N**: 6 rungs × 2 arms × 3 passes = 36 timed passes; each pass = 40 queries
  × 500 candidates = **20,000 candidate resolutions**
- **Date**: 2026-09-25

### Pass-3 (steady state), the statistic the bars are judged on

| effective cap (GiB) | SQLite p50 | SQLite p95 | ordinals p50 | ordinals p95 | p95 ratio | parity |
|---:|---:|---:|---:|---:|---:|:--:|
| 23.97 | 3.057 | 3.615 | 0.932 | 1.007 | 3.59× | ✓ |
| 15.96 | 2.831 | 3.030 | 0.944 | 0.986 | 3.07× | ✓ |
| 9.96 | 2.966 | 3.903 | 0.970 | 1.038 | 3.76× | ✓ |
| 5.98 | 2.798 | 2.850 | 0.974 | 1.051 | 2.71× | ✓ |
| 3.78 | 2.786 | 2.942 | 0.940 | 1.003 | 2.93× | ✓ |
| 1.86 | 3.184 | 4.484 | 1.077 | 1.196 | 3.75× | ✓ |

All twelve cells passed the quiet-host gate (max `load1` **2.56** on 16 cores,
no other Python benchmark running). `ids_without_ordinal = 0` at every rung, so
the ordinal arm never fell back to SQLite — it is a pure ordinal measurement.

### The bars

| bar | measured | |
|---|---|:--:|
| **B1** `S(c_lo)/S(c_hi) ≥ 3` | 4.484 / 3.615 = **1.240** | **FAIL** |
| **B2** `O(c_lo)/O(c_hi) ≤ 1.5` | 1.196 / 1.007 = **1.188** | **PASS** |
| **B3** `(S/O)(c_lo) ≥ 2·(S/O)(c_hi)` | 3.749 versus 7.180 | **FAIL** |
| **B4** majflt ratio ≥ 10 at `c_lo` | 0 versus 0 — **VOID**, see below | — |
| **B5** parity, every rung, every query | **0 mismatches / 240 comparisons** | **PASS** |

**B4 was a bad instrument and the pre-registration is what makes that
visible.** SQLite reads `meta.sqlite` with buffered `pread`, which never
generates a *major fault*, so `majflt` cannot see the SQLite arm's page-cache
misses at all — it read 0 at every rung including the cold passes that cost
125 ms. The ordinal arm, being `mmap`'d, reports honestly (291–570 majflt on
the cold pass, 0 once resident). The bar is recorded VOID rather than scored;
the SQLite arm's misses would need `/proc/self/io` or block-layer counters.

### The number that actually settles it: the working set was never 24.9 GB

`mincore(2)` over each artifact at the end of every arm, identical at all six
rungs:

| arm | resident after the passes | of | share |
|---|---:|---:|---:|
| SQLite | **122.7 MB** | 24,908,001,280 B `meta.sqlite` | **0.49%** |
| ordinals | **1,643.9 MB** | 1,955,372,324 B of arrays | **84.1%** |

**`THIN_CLIENT_SWAP.md` had the mechanism backwards.** It said ordinals shrink
the filter stage's page-cache working set "from a randomly-descended 24.9 GB
B-tree to 1.96 GB of arrays". Measured, the filter stage's *hot* set inside
that 24.9 GB file is **122.7 MB** — the B-tree's interior nodes plus the leaves
20,000 ids actually land on — while `OrdinalSpace.lookup`'s `searchsorted` over
the 1.2 GB `wids` array plus the column gathers pulls **1,643.9 MB** resident.
**Adopting ordinals makes the filter stage's resident set 13.4× LARGER, not
12.7× smaller.** That is why no cap in this ladder hurts SQLite: 122.7 MB fits
in every rung, including the 1.86 GiB one.

### What ordinals DO win, measured here: the cold transient

Pass 1 runs immediately after a verified eviction of both artifacts:

| effective cap (GiB) | 23.97 | 15.96 | 9.96 | 5.98 | 3.78 | 1.86 |
|---|---:|---:|---:|---:|---:|---:|
| SQLite p50 (ms) | 132.5 | 135.7 | 129.5 | 117.2 | 122.0 | 120.1 |
| ordinals p50 (ms) | 1.48 | 1.58 | 1.73 | 1.66 | 1.61 | 2.18 |
| ratio | 90× | 86× | 75× | 71× | 76× | 55× |

**55–90× on the first pass after eviction**, because 20,000 scattered 4 KiB
`pread`s cost far more wall time than faulting the arrays in with readahead.
It is a one-shot cost — by pass 2 SQLite is back to ~2.9 ms — so it prices
*process restarts and post-eviction recovery*, not steady-state serving. This
is a real and previously unrecorded ordinals win, and it is on a different axis
from the one §14 #5 asked about. It does not rescue the module on its own:
buying an 80× faster first pass with 1.5 GB of extra permanent residency is the
opposite of the trade the module was proposed for.

### Defect found and fixed mid-run (D1)

The first ladder (kept as `ordinals_cliff_d1confounded_20260925.json`) ran with
**up to 1,525.8 MB of stale ordinal arrays resident during the SQLite arm**:
`posix_fadvise(DONTNEED)` cannot drop pages a live mapping still holds, and the
previous arm's `OrdinalSpace` was still referenced. The bias was *against* the
SQLite arm (it was measured with part of its cap stolen) and SQLite still did
not move, so the refutation was never at risk; the run was repeated anyway with
each arm dropping its retriever, `OrdinalSpace` and SQLite connection and
forcing a `gc` before the next eviction. In the repeated run the SQLite arm
shows **0.0 MB** of ordinal residency at every rung.

### What this does NOT settle

1. **A bigger hot set.** 40 queries × 500 candidates is one workload. A query
   mix that scattered over a much larger slice of the 150M rows would grow the
   122.7 MB and could, in principle, reach a cap. Nothing here measures that,
   and confound §5.4 flagged the direction in advance.
2. **Concurrency.** Single-threaded, one filter stage at a time; `_meta_lock`
   contention is untouched.
3. **`_hydrate`.** Still SQLite in both arms (doc 18 §11 "not settled #3").
4. **The balloon is not a cgroup cap** (§2). The curves are compared against
   the same instrument; the absolute ms are this host's.

### Consequence for the module

`ordinals.py` stays as it is — inert, default-OFF, fail-closed. §14 #5's own
framing ("decides whether ordinal addressing is worth anything at all") plus
this measurement means the honest status is: **the residency argument for
ordinals is refuted on the measured workload, and the module's only measured
advantage is a one-shot 55–90× cold-start win bought with 13.4× more resident
memory.** No default changed.
