# convergence_repro — BUILD NOTES

**Built 2026-08-31 by an Opus 5 subagent. BUILD ONLY — no bar verdict is
claimed here.** The SCALE=1 ladder and the judgement of the five
pre-registered bars belong to the session lead (`PREREGISTRATION.md`
"Deliverables").

---

## 1. TL;DR for the reviewer

| item | status |
|---|---|
| `Dockerfile`, `jobs/repeat.fio`, `jobs/laydown.fio`, `cell.sh`, `run_ladder.sh`, `analyze.py` | written, syntax-clean |
| cell protocol (preflight / evict+verify / load / N passes) | **executed end-to-end, 10 cells** |
| fio one-invocation-equals-one-pass | **verified exactly** (majflt = 262,144 = 1024 MiB / 4 KiB) |
| majflt + ms/fault + clat p50/p95 capture | **verified under real faults** |
| `vmtouch -e` eviction + verification + abort-on-failure | **verified** (0.0000 % residency; abort path exercised) |
| cgroup `memory.stat` readability | **verified readable**, cgroup **v2** |
| `analyze.py` table + all 5 bar evaluators | **run without error on smoke data** |
| `docker build` / `docker run --memory=…` / named volume | **NOT executed — impossible in this dev container** (§3) |

**The one thing the reviewer must know:** the environment fact supplied with
the build task — *"`docker` CLI is available and can run sibling containers"* —
**is false for this dev container.** The CLI binary exists but there is no
usable daemon and the container lacks `CAP_SYS_ADMIN`, so no capped cell could
be run here. The harness is written for the docker path as specified; the
mechanics were validated through a documented **`--local` (uncapped) backend**
added for exactly that purpose. Details and evidence in §3.

---

## 2. What was built

```
spike/convergence_repro/
├── Dockerfile          debian:bookworm-slim + fio, vmtouch, procps, time,
│                       python3, coreutils  ->  image `convrepro:latest`
├── jobs/laydown.fio    deterministic, NON-SPARSE creation of R and L
├── jobs/repeat.fio     the repeat-set pass: ONE fio invocation == ONE pass
├── cell.sh             the in-container cell driver; emits one JSON on stdout
├── run_ladder.sh       host-side orchestrator (image, named volume, 5 rungs)
├── analyze.py          per-pass table + the 5 pre-registered bars
└── BUILD_NOTES.md      this file
```

### Sizes and rungs

`SCALE` (default `1.0`) scales both files: `R = 5120 MiB × SCALE`,
`L = 1792 MiB × SCALE` (5 GiB / 1.75 GiB, `L/R = 0.35`, `D = 6.75 GiB`).
Rung caps are the pre-registered ones: fits 10 g, marginal 7 g, boundary
5.75 g, thrash 3.75 g, deep 2.75 g.

**Cap-scaling choice (the documented decision the task asked for).** Caps
scale by the same factor as the files, and a **fixed headroom is added on
top**:

```
cap_MiB = round(base_GiB × 1024 × SCALE) + HEADROOM_MiB
HEADROOM_MiB = 0    when SCALE >= 1.0      (the pre-registered caps, verbatim)
             = 256  when SCALE <  1.0      (~0.25 GiB, as specified)
```

Rationale: the pre-registration sizes the caps against **file demand only**
("fio process anon is negligible — recorded as a deliberate difference"). At
SCALE=1 fio's ~50 MB anon is under 2 % of even the 2.75 g deep cap, so the
caps are used verbatim and the numbers in the results match the
pre-registration exactly. Below SCALE=1 that anon footprint stops being
negligible (at SCALE=0.2 the deep rung would be 563 MiB), so headroom is added
**on top of** the scaled cap rather than taken out of it — which is what keeps
the quantity that actually governs the regime, the file budget
`cap_file = cap − headroom`, scaling exactly with R and L. The ratios
`cap_file/R` and `cap_file/D` are therefore identical at every scale.
Override with `--headroom-mib`. Note that the JSON's `files.R_over_cap` /
`files.D_over_cap` are computed against the **whole** cap, so at SCALE=1
(headroom 0) they read exactly as pre-registered — boundary
`R_over_cap = 5120/5888 = 0.870`, i.e. cap = 1.15×R — while at reduced scale
they are diluted by the headroom (0.714 for boundary at SCALE=0.2). The
undiluted quantity there is `R / (cap − headroom)`, which is scale-invariant.

### Determinism

`randrepeat=1` plus a fixed `randseed` (default `20260831`, `--seed`) in both
job files. `norandommap=0` (fio's default random map) makes `io_size == size`
a true single pass over every block exactly once, in the same seeded-random
order in every pass and every cell. Verified: `io_kbytes` is exactly R on every
pass of every cell.

### Metrics per pass

`clat_ns` p50/p95/p99/mean, wall time, `majflt`/`minflt` (GNU `time -v`),
`ms_per_fault`, R and L residency (`vmtouch`), and cgroup `memory.stat`
**deltas** for `pgscan`, `pgsteal`, `workingset_refault_file`,
`workingset_activate_file` plus end-of-pass `active_file`, `inactive_file`,
`memory.current` and `memory.swap.current`. Each pass also records
`t_start_epoch` / `t_end_epoch` (used by the host-side cgroup fallback, §5).

### Modes and convergence rule

`--mode fixed3` runs exactly `--passes` (default 3). `--mode converge` runs up
to `--max-passes` (default 12) and stops when either

* `majflt_n < 1 % of majflt_1` → `converge_reason=majflt_below_1pct_of_pass1`, or
* two **consecutive** pass-to-pass majflt steps are each within ±10 %
  → `converge_reason=plateau_within_10pct_x2`,

subject to a floor of `--min-passes` (default 3) so the fixed-window bars
always have pass-3 data. **Both branches were exercised** (§4).

### Swap

Cells run `--memory=X --memory-swap=X`. `cell.sh` reads
`memory.swap.current` after every pass; any non-zero value sets
`swap_confounded: true` and `analyze.py` prints the cell as
*recorded-not-concluded* (the R1 / G8 §A1 rule).

### Abort semantics

`exit 2` preflight (missing file, wrong size, sparse file), `exit 3` eviction
did not take, `exit 4` fio failed. All three were exercised (§4).

---

## 3. PROBE RESULTS (all measured 2026-08-31 in this dev container)

| probe | result |
|---|---|
| kernel | `6.18.33.2-microsoft-standard-WSL2` |
| `/sys/kernel/mm/lru_gen/enabled` | **absent** → classic two-list LRU, exactly the regime the pre-registration targets |
| cgroup version | **v2** (`stat -fc %T /sys/fs/cgroup` → `cgroup2fs`); controllers include `memory` |
| `memory.stat` readable in-container | **YES** — `active_file`, `inactive_file`, `pgscan`, `pgsteal`, `workingset_refault_file`, `workingset_activate_file` all present; `memory.swap.current` and `memory.max` readable |
| `/sys/fs/cgroup` mount options | **`ro`** — read-only |
| `CapBnd` / `CapEff` (as root) | `0000000000a80425fb` — **no `CAP_SYS_ADMIN`** |
| remount cgroupfs rw | **permission denied** |
| `unshare -Ur` (user namespaces) | **operation not permitted** |
| `vmtouch -e` eviction | **works**, verified `Resident Pages: 0/65536 0%` |
| workspace filesystem | `/workspaces/sfu-library-thinclient` = **v9fs (9p)** — confirmed; no benchmark data was ever written there |
| root filesystem | `overlay`, 759 GB free — benchmark data used `/var/tmp/convrepro_data` |
| swap device present on host | yes, 16 GiB (`/dev/sdc`), unused (0) |
| RAM | 56 GiB total, ~53 GiB free during the runs |

> **AMENDMENT 2026-09-05 — the kernel row above is now HISTORICAL.** The table
> records the box as it was on 2026-08-31 and is correct as history; two rows
> no longer describe the running system. The WSL2 VM now boots a **custom
> kernel**: `uname -r` = `6.18.33.2-microsoft-standard-WSL2+` (trailing `+`;
> the 2026-08-31 stock kernel had none), built with `CONFIG_LRU_GEN=y`,
> `CONFIG_LRU_GEN_ENABLED=y`, `CONFIG_LRU_GEN_WALKS_MMU=y`. Therefore
> `/sys/kernel/mm/lru_gen/enabled` is **present and reads `0x0007`** — MGLRU is
> compiled in *and* default-ON, i.e. this box's everyday reclaim policy is now
> MGLRU, not the classic two-list LRU this spike was originally scoped to.
> Measured 2026-09-05 from the dev container. VM memory is 56 GB fixed with
> ~54 GB available.
>
> What this does and does not change:
> * **Nothing about the committed Tier-1 / Tier-1b / ES cells.** They ran on
>   2026-08-31 under the stock classic-LRU kernel, exactly as their JSONs and
>   §6's "WSL2 / classic-LRU only" limitation record. They are not invalidated
>   and must not be re-judged against the new kernel.
> * **§6's limitation is lifted for NEW work only:** the MGLRU arm
>   (publication-gate item 3) is now available locally, which is what unblocks
>   the Tier-1d windows.
> * **The dev container still cannot run capped cells** — re-verified
>   2026-09-05: `/sys/fs/cgroup` is still `ro`, `/sys` is mounted read-only so
>   `lru_gen/enabled` is readable but **not writable** from here, and
>   `/proc/sys/vm/drop_caches` is root-only (container uid 1000, `CapEff: 0`).
>   Tier-1d windows run as root **in the Ubuntu WSL2 distro** via
>   `t1d_wsl2_orchestrator.sh`; see the Tier-1d section of `HOST_RUN.md`.
> * The console capture in §4.3 below (`kernel : …WSL2`, `lru_gen : absent`) is
>   a verbatim 2026-08-31 artefact and is left untouched for the same reason.

### Why docker could not be used here (the failed-environment-fact detail)

Reproducible chain of evidence:

1. `/var/run/docker.sock` **does not exist**; no docker daemon on any TCP port;
   `host.docker.internal` unreachable on 2375/2376.
2. `.devcontainer/devcontainer.json` does declare the
   `ghcr.io/devcontainers/features/docker-in-docker:2` feature, and
   `/usr/bin/dockerd` is installed — so the daemon was *meant* to be available.
3. Starting it by hand fails on `Failed to create bridge docker0 via netlink:
   operation not permitted`. With `--bridge=none --iptables=false
   --ip6tables=false` the daemon **does** come up (`API listen on
   /var/run/docker.sock`, cgroup driver `cgroupfs`, cgroup version 2).
4. But it cannot do anything useful:
   * `docker pull` **crashes the daemon** — a Go/OpenSSL FIPS bug in the
     msft-golang build (`OSSL_PARAM_BLD_push_octet_string: passed a null
     parameter` inside `crypto/tls/internal/tls13.ExpandLabel`) during the
     TLS 1.3 handshake. `GOFIPS=0`, `GOLANG_FIPS=0` and `GODEBUG=fips140=off`
     did not suppress it.
   * More fundamentally, **any** container start fails at image unpack:
     `failed to mount … fstype: bind … operation not permitted`. Bind mounts,
     cgroup creation and `mount` all require `CAP_SYS_ADMIN`, which the
     container does not have (see the `CapBnd` row above), and
     `/sys/fs/cgroup` is mounted read-only and cannot be remounted.
5. Therefore `docker run --memory=X` — the entire cell mechanism — **cannot
   run in this dev container under any configuration.** The daemon was stopped
   again after probing; nothing was left running.

The original R1 ladder has the same shape: `r1_ram_ladder.py`'s docstring says
*"This process does NOT cap itself — the orchestrator wraps it"* — i.e. the
orchestrator ran on the **host**, not inside a dev container. `run_ladder.sh`
is written for that same host-side position and is what the reviewer should
run.

---

## 4. SMOKE VALIDATION (what was actually executed)

Because docker was unavailable, `run_ladder.sh` gained a **`--local`
backend**: it lays the files down on the overlay filesystem
(`/var/tmp/convrepro_data`, never 9p — the script *refuses* a 9p path) and
runs `cell.sh` directly with **no memory cap**. Such cells are stamped
`cap_enforced: false`, and `analyze.py` refuses to issue a bar verdict for
them. This validates every part of the harness **except** cap enforcement.

Commands run:

```bash
bash spike/convergence_repro/run_ladder.sh --smoke --local
bash spike/convergence_repro/run_ladder.sh --smoke --local --mode converge
python3 spike/convergence_repro/analyze.py --dir data/eval_results
```

10 cells (5 rungs × 2 modes) at SCALE=0.2 (R = 1024 MiB, L = 358 MiB),
written to `data/eval_results/convrepro_<rung>_<mode>_smoke_nocap_20260831.json`.
All 10 are well-formed JSON. Full output in §4.3.

### 4.1 Checklist the task asked me to confirm

| check | result |
|---|---|
| all 5 cells produce well-formed JSON | **YES** — 10/10 parse, both modes |
| eviction verification works | **YES** — `post_evict_resident_pct` = `0.0000` on R and L in every cell; the abort path fires correctly when the threshold is violated |
| majflt nonzero on pass 1 | **see 4.2** — 0 in the uncapped protocol cells (*physically correct*), **262,144 in the cold-start validation cell** |
| fio clat parses | **YES** — p50/p95/p99/mean, cold **158.72 µs** vs warm **0.28 µs** |
| memory.stat fields resolve | **YES, in-container** — no host-side fallback needed on this host |
| analyze.py renders the table | **YES** — table + all 5 bar evaluators, exit 0 |

### 4.2 Why pass-1 majflt is 0 in the uncapped cells, and how majflt was really validated

In the protocol the load phase reads L **and R** sequentially before pass 1.
With **no cap** and 53 GiB free, nothing is ever reclaimed, so R is 100 %
resident when the first fio pass starts and the pass takes **zero** major
faults. That is the physically correct result for an uncapped cell — and it is
the same signal the pre-registration *predicts for the fits rung* (bar 5:
"reclaim never runs"). It is not a harness defect; it is the absence of the
cap.

To prove the majflt / clat path really works, `cell.sh` has a **validation-only**
knob `SKIP_LOAD=1` (loudly documented in the source, stamped
`load_phase.skipped: true` in the JSON, and never used by a protocol cell):
it omits the load so pass 1 starts on a fully evicted R.

```
SKIP_LOAD=1 run_ladder.sh --smoke --local --rungs boundary --out-dir <scratch>

  pass 1: majflt=262,144  minflt=2,768   wall=43.02 s  ms/fault=0.1641
          p50=158,720 ns  p95=201,728 ns  io_kb=1,048,576
  pass 2: majflt=0        minflt=19,162  wall=0.557 s  p50=282 ns  io_kb=1,048,576
  pass 3: majflt=0        minflt=19,154  wall=0.555 s  p50=282 ns  io_kb=1,048,576
```

This is the single most important validation in the build:

* **262,144 = 1024 MiB ÷ 4 KiB, exactly.** One fio invocation is exactly one
  full pass over R, and `majflt` is an exact count of the pass's miss set —
  no fault-around, no double counting, no short pass.
* `io_kbytes` is exactly R on **every** pass, warm or cold.
* `ms_per_fault` = 0.164 ms is a plausible random-4K service cost, and is
  reported alongside the counts as `04_CONVERGENCE_ARTIFACT.md` §4b requires.
* cold→warm p50 separation is 563×, so the clat parse is real.
* The majflt trajectory `262,144 → 0 → 0` is the convergence-to-zero shape the
  experiment is built to observe.

### 4.2b Convergence-rule and abort-path exercises

| exercise | result |
|---|---|
| convergence rule A (`majflt < 1 % of pass-1`) | fired: `converged=True, reason=majflt_below_1pct_of_pass1, passes_run=3` on the cold-start converge cell (262,144 → 0 → 0) |
| convergence rule B (plateau ±10 % ×2) | fired: `converged=True, reason=plateau_within_10pct_x2` on the uncapped converge cells (0 → 0 → 0) |
| `MIN_PASSES=3` floor | respected — neither rule terminated at pass 2 |
| eviction-failed abort | `exit 3`, `FATAL: eviction did NOT take (…) — cell aborted` |
| size-mismatch preflight abort | `exit 2`, `FATAL: R.bin is 1073741824 B, expected 5368709120 B` |
| missing-file preflight abort | `exit 2`, `FATAL: missing data file …/R.bin` |

### 4.3 Smoke run — analyze.py output (2026-08-31, SCALE=0.2, caps NOT enforced)

```
======================================================================================================================
convergence_repro — synthetic repro of the fixed-window convergence inversion (PREREGISTRATION.md)
======================================================================================================================
cells loaded : 10  (boundary, deep, fits, marginal, thrash)
modes        : converge, fixed3
scale(s)     : [0.2]   caps enforced: False
kernel       : 6.18.33.2-microsoft-standard-WSL2
lru_gen      : absent   (absent = classic two-list LRU, the regime this spike targets)
cgroup       : v2  readable in-container: True
fio randseed : 20260831

======================================================================================================================
MODE: fixed3
======================================================================================================================
     rung    cap pass   p50 us   p95 us  wall s    majflt  ms/flt    pgscanD     wsrfD actfile MiB  R res%  L res%
----------------------------------------------------------------------------------------------------------------------
     fits    10g    1     0.26     0.58    0.45         0       -          0         0       529.5   100.0   100.0
     fits    10g    2     0.26     0.58    0.44         0       -          0         0       529.5   100.0   100.0
     fits    10g    3     0.26     0.58    0.44         0       -          0         0       529.6   100.0   100.0
    -> passes_run=3 converged=False (n/a_fixed_window) evictOK R=0.0% L=0.0%  [CAP NOT ENFORCED]
----------------------------------------------------------------------------------------------------------------------
 marginal     7g    1     0.25     0.57    0.44         0       -          0         0       529.7   100.0   100.0
 marginal     7g    2     0.25     0.57    0.44         0       -          0         0       529.7   100.0   100.0
 marginal     7g    3     0.25     0.58    0.44         0       -          0         0       529.7   100.0   100.0
    -> passes_run=3 converged=False (n/a_fixed_window) evictOK R=0.0% L=0.0%  [CAP NOT ENFORCED]
----------------------------------------------------------------------------------------------------------------------
 boundary  5.75g    1     0.26     0.59    0.44         0       -          0         0       529.7   100.0   100.0
 boundary  5.75g    2     0.25     0.58    0.44         0       -          0         0       529.7   100.0   100.0
 boundary  5.75g    3     0.25     0.58    0.44         0       -          0         0       529.7   100.0   100.0
    -> passes_run=3 converged=False (n/a_fixed_window) evictOK R=0.0% L=0.0%  [CAP NOT ENFORCED]
----------------------------------------------------------------------------------------------------------------------
   thrash  3.75g    1     0.25     0.58    0.44         0       -          0         0       529.7   100.0   100.0
   thrash  3.75g    2     0.25     0.58    0.44         0       -          0         0       529.7   100.0   100.0
   thrash  3.75g    3     0.25     0.58    0.44         0       -          0         0       529.7   100.0   100.0
    -> passes_run=3 converged=False (n/a_fixed_window) evictOK R=0.0% L=0.0%  [CAP NOT ENFORCED]
----------------------------------------------------------------------------------------------------------------------
     deep  2.75g    1     0.26     0.58    0.44         0       -          0         0       529.7   100.0   100.0
     deep  2.75g    2     0.26     0.59    0.45         0       -          0         0       529.8   100.0   100.0
     deep  2.75g    3     0.25     0.58    0.44         0       -          0         0       529.9   100.0   100.0
    -> passes_run=3 converged=False (n/a_fixed_window) evictOK R=0.0% L=0.0%  [CAP NOT ENFORCED]
----------------------------------------------------------------------------------------------------------------------
```

(The converge-mode table is identical in shape; every rung reports
`converged=True (plateau_within_10pct_x2)` at pass 3 because with no cap the
majflt sequence is 0 → 0 → 0.)

```
======================================================================================================================
PRE-REGISTERED BARS — *** MECHANICS CHECK ONLY, NOT A BAR VERDICT ***
  Reason: scale(s) [0.2] != [1.0]; cap_enforced=false on at least one cell
  The bars are judged by the session lead on a SCALE=1 docker ladder with caps enforced.
======================================================================================================================

BAR 1: Inversion at the fixed pass-3 window (boundary p50 < marginal p50, marginal majflt still falling)
  VERDICT: FAIL (mechanics — NOT a bar verdict)
    pass-3 p50: boundary=0.0003 ms  marginal=0.0003 ms  -> inversion ratio 1.00x  (NO)
    marginal majflt trajectory: 0 -> 0 -> 0  falling=False  still>1%-of-pass1=False

BAR 2: Same destination, not Belady (marginal & boundary both converge in <=12 passes to steady p50s within +/-10%)
  VERDICT: PASS (mechanics — NOT a bar verdict)
    marginal: converged=True in 3 passes (plateau_within_10pct_x2) steady p50=0.0003 ms final majflt=0
    boundary: converged=True in 3 passes (plateau_within_10pct_x2) steady p50=0.0003 ms final majflt=0
    steady-p50 spread = 0.0% (bar: <=10%)

BAR 3: Cliff: thrash+deep stay flat-and-large (pass3 majflt >= 0.8x pass2) with steady p50 >= 10x converged; every rung >= boundary converges
  VERDICT: FAIL (mechanics — NOT a bar verdict)
    converged reference p50 = 0.0003 ms (mean of converged marginal+boundary (converge mode))
    thrash: majflt p2=0 p3=0 (p3/p2=n/a, bar>=0.80 -> False); steady p50=0.0003 ms = 1.0x converged (bar>=10x -> False); converged=True
    deep: majflt p2=0 p3=0 (p3/p2=n/a, bar>=0.80 -> False); steady p50=0.0003 ms = 1.0x converged (bar>=10x -> False); converged=True
    fits: converged=True in 3 passes
    marginal: converged=True in 3 passes
    boundary: converged=True in 3 passes

BAR 4: Pressure-scaled aging: pass-1 cgroup pgscan monotone non-decreasing as caps descend fits -> deep
  VERDICT: PASS (mechanics — NOT a bar verdict)
    pass-1 pgscan delta: fits=0  marginal=0  boundary=0  thrash=0  deep=0
    monotone non-decreasing = True

BAR 5: The sort-not-needed datum: at the fits rung active_file stays << R (est. < 0.25 x R) through all passes
  VERDICT: FAIL (mechanics — NOT a bar verdict)
    R = 1024 MiB; bar = active_file < 256 MiB
      pass 1: active_file = 529.5 MiB (0.517 x R) OVER
      pass 2: active_file = 529.5 MiB (0.517 x R) OVER
      pass 3: active_file = 529.6 MiB (0.517 x R) OVER

======================================================================================================================
OVERALL: MECHANICS CHECK — no bar verdict issued.
======================================================================================================================
```

**Read the PASS/FAIL marks above as "the evaluator ran and produced a number",
nothing more.** Every one of them is a consequence of there being no cap:
with 53 GiB of free RAM nothing faults, so bars 1 and 3 have no signal to find
and bar 2's "both converged, 0 % spread" is trivially true. Bar 5's
`active_file = 529 MiB` is the **dev container's whole cgroup** — it counts
every file this container has cached, not just R; inside a real capped cell the
cgroup contains only the fio process and the number is meaningful. Bar 4's
all-zero `pgscan` is the same story: no pressure, no scanning.

---

## 5. Deviations from the spec, and why

1. **`--local` (uncapped) backend added to `run_ladder.sh`.** Not in the spec.
   Added because docker cannot run in this dev container (§3) and the task
   required end-to-end smoke validation. Cells are stamped
   `cap_enforced: false` and `analyze.py` hard-refuses a bar verdict on them.
   The reviewer should never use it for a real ladder.
2. **`SKIP_LOAD=1` validation knob in `cell.sh`.** Not in the spec. The only
   way to exercise the majflt path without a cap (§4.2). Stamped
   `load_phase.skipped: true`; never set by a protocol run.
3. **`fio` and `vmtouch` were `apt-get install`ed into this dev container.**
   The task said fio "belongs in the benchmark container image, not here" —
   that instruction assumed docker would work. With docker unavailable, this
   was the only route to any real validation. Nothing was installed into the
   project venv (the binding CLAUDE.md rule); these are system apt packages
   only: `fio vmtouch procps time`. Remove with
   `sudo apt-get remove -y fio vmtouch` if the container should be pristine.
   The `convrepro:latest` image installs its own copies regardless.
4. **Cell JSON is emitted on stdout between `===CONVREPRO_JSON_BEGIN/END===`
   fences**, not written to a mounted output directory. This avoids needing a
   second writable mount into the cell and works identically for
   `docker run` and `docker logs`. `run_ladder.sh` extracts it.
5. **`fadvise_hint` left at fio's default (1).** This puts `MADV_RANDOM` on the
   mapping, disabling fault-around, so exactly one major fault occurs per
   missing 4 KiB block. That is what makes `majflt` an exact miss counter
   (verified: 262,144 for a 1 GiB R). The real stack does **not** call
   fadvise and does get fault-around, so its per-fault cost and count are not
   directly comparable — which is fine, the pre-registration already declares
   the comparison qualitative and says ms/fault is "reported, not compared".
   Recorded here as a deliberate difference.
6. **`--network=none` on every cell and prep container.** Not in the spec;
   removes a noise source and needs nothing.
7. **Headroom policy** (§2) — the spec asked for a documented choice; this is it.

---

## 6. Known limitations

* **Nothing about cap enforcement has been executed.** The docker path
  (`docker build`, named-volume create/populate, `docker run --memory`, the
  between-cell re-evict container, the cap-verification warning, the host-side
  cgroup sampler) is written and syntax-clean but **never ran**. Expect to
  debug it on first use. The cap-verification step exists precisely to catch a
  silent failure here: `cell.sh` reads its own `memory.max` and
  `run_ladder.sh` warns if it does not equal what `--memory` implied.
* **The host-side cgroup fallback is untested.** On this host `memory.stat`
  *is* readable inside the cell, so the fallback never triggered. If the
  reviewer's host reports `cgroup probe: unreadable`, the orchestrator runs
  cells detached and polls the container's cgroup at 0.5 s; `analyze.py`
  reconstructs per-pass deltas from `t_start_epoch`/`t_end_epoch`. Treat that
  path as unproven.
* **`docker pull` may fail on a Docker-Desktop-adjacent daemon** with the
  msft-golang FIPS TLS crash described in §3.4. On a normal Linux docker host
  this does not occur.
* **Cell wall time at SCALE=1.** A cold pass over 5 GiB at the measured
  0.164 ms/fault is roughly 3–4 minutes; the load phase adds sequential reads
  of 6.75 GiB. Budget ~10–20 min per fixed-3 cell and considerably more for a
  12-pass converge cell at the thrash/deep rungs, where every pass stays cold.
  The full converge ladder could run for a few hours.
* **The box must stay quiet.** These are page-cache measurements on a shared
  56 GiB pool. Do not run other heavy work in parallel (the R2 host-noise
  lesson). The pre-registration also asks for replication at the marginal and
  boundary rungs — that is a reviewer action, e.g. re-run
  `--rungs marginal,boundary` and compare.
* **WSL2 / classic-LRU only**, as the pre-registration already records. Native
  Linux and MGLRU arms are publication-gate items 2–3.
* The smoke JSONs left in `data/eval_results/` are `*_smoke_nocap_*` and carry
  `cap_enforced: false`; they are mechanics artefacts, not results. Delete
  them or leave them — `analyze.py` will refuse a verdict as long as they are
  in the glob, so **filter them out when analysing a real run** (see §7).

---

## 7. Exact commands for the reviewer

Run these **from the docker host** (a shell where `docker info` works), from
the repo root. Keep the box otherwise quiet.

### (a) Build the image and populate the volume (idempotent)

```bash
cd /workspaces/sfu-library-thinclient
bash spike/convergence_repro/run_ladder.sh --build-only
```

### (b) The full fixed-3 ladder at SCALE=1 (the headline table)

```bash
bash spike/convergence_repro/run_ladder.sh --mode fixed3
```

Writes `data/eval_results/convrepro_<rung>_fixed3_<YYYYMMDD>.json` for
fits, marginal, boundary, thrash, deep. Watch the per-cell line
`cap verified in-cell: memory.max=…` — if it warns instead, the cap did not
land and the run is void.

### (c) The convergence-mode ladder (max 12 passes)

```bash
bash spike/convergence_repro/run_ladder.sh --mode converge
```

Writes `convrepro_<rung>_converge_<YYYYMMDD>.json`. This is the long one.

### (d) Analyse and judge the bars

```bash
# real run only — exclude the smoke artefacts
python3 spike/convergence_repro/analyze.py \
    --dir data/eval_results --glob 'convrepro_*_20260901.json'
```

Substitute the actual date tag. The header must read
`scale(s) : [1.0]   caps enforced: True` and the bars section must **not** say
MECHANICS CHECK — if it does, smoke JSONs are still in the glob.

Bars 1, 4 and 5 are judged from the fixed-3 cells; bars 2 and 3 need the
converge cells, so run both ladders before the final verdict.

### Useful variants

```bash
# fast mechanics re-check of the whole pipeline (~5 min, no bar verdict)
bash spike/convergence_repro/run_ladder.sh --smoke

# replicate just the two cells the pre-registration asks to replicate
bash spike/convergence_repro/run_ladder.sh --mode fixed3 --rungs marginal,boundary

# the pre-declared tuning knob, if marginal converges before pass 3:
#   grow L, or move the marginal cap toward exactly 1.00 x D.
# Any tuned values MUST be reported as tuned and the bars re-judged on fresh cells.
bash spike/convergence_repro/run_ladder.sh --mode fixed3 --rungs marginal --headroom-mib 0
#   (L is set by L_BASE_MIB in run_ladder.sh; the marginal cap by RUNG_GIB[marginal])

# force a fresh deterministic laydown (e.g. after changing SCALE or the seed)
bash spike/convergence_repro/run_ladder.sh --force-laydown --mode fixed3
```

### Cleanup

```bash
docker volume rm convrepro_data     # frees ~6.75 GiB
docker rmi convrepro:latest
```

---

## 8. Efficacy status (CLAUDE.md new-module rule)

**IMPLEMENTED, EFFICACY UNMEASURED.** This harness has been *validated for
mechanics* (§4) but has produced **no** result bearing on the five
pre-registered bars, because no memory-capped cell has ever been run. The
numbers in §4 measure the harness, not the phenomenon. When the session lead
runs the SCALE=1 ladder, the measured numbers, the absolute date, the eval
script paths (`spike/convergence_repro/run_ladder.sh`,
`spike/convergence_repro/analyze.py`) and the result paths
(`data/eval_results/convrepro_*.json`) must be recorded in this directory's
`RESULTS.md` and pointed to from
`docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`,
per `PREREGISTRATION.md` "Deliverables".

---

# 9. EARLY-SORT ARM — added 2026-08-31 (second Opus 5 build pass)

**BUILD ONLY.** Implements `PREREGISTRATION_EARLYSORT.md` (the §5.3 "skip the
sort" claim: `guided` = map-guided F5 analogue, `blind` = map-blind
`memory.reclaim` analogue). No ES bar verdict is claimed here — the SCALE=1
capped run and the ES-1..ES-5 judgement belong to the session lead. Everything
in §§1–8 above still stands unchanged.

## 9.1 What changed, file by file

### `cell.sh`

* New knob **`EARLY_SORT`** (`none` | `guided` | `blind`, default `none`),
  validated in preflight (`exit 2` on an unknown value). Applied in a new
  phase **3b, strictly between the load phase and pass 1**.
* **`EARLY_SORT=none` is a no-op.** No vmtouch, no cgroup write, no extra log
  line, no extra timing — the Tier-1 cell protocol is byte-for-byte what it was.
  Verified by re-running a baseline cell with the new script (§9.3).
* `guided`: `vmtouch -e "$L_FILE"` (L **only** — R is never named), wall-timed,
  then residency of **both** R and L. Verification (L ≤ `EVICT_MAX_PCT`, 1%) is
  **non-fatal**: a miss sets `early_sort.early_sort_failed=true` with a reason
  and the passes still run (the data is still informative), per the task spec.
* `blind`: probes, in order — cgroup is v2 → `memory.reclaim` exists → it is
  writable (`-w`, which is false on a read-only cgroupfs) — then writes L's
  **exact byte count** to it. Captures wall time, bytes requested, exit code and
  the write's stderr, `memory.current` before/after, and post-action residency
  of R and L. A non-zero write (the EAGAIN-shaped partial-reclaim return) is
  recorded as `early_sort_failed` **with rc + message and is never an abort** —
  it is a result. Any failed probe stamps `blocked: true` + `blocked_reason`
  (including the cgroup mount options) and the cell then behaves exactly as a
  `none` cell while still emitting the JSON.
* Override `ES_RECLAIM_FILE` (default `$CG_ROOT/memory.reclaim`) for hosts that
  expose the cell's cgroup elsewhere; `ES_CGROUP_WRITE_GRANT` is a free-text
  note from the orchestrator recorded verbatim.
* A cgroup snapshot is taken **after** the action (`cg_after_es`), so the JSON
  carries `pgscan`/`pgsteal` deltas and `active_file`/`inactive_file`
  before→after **across the early-sort action itself**.

### JSON (schema still `convrepro/cell/1` — the change is purely additive)

New top-level `early_sort` object, present on **every** cell (mode `"none"` with
null measurements for baselines). Cells written before this pass have no such
key at all; `analyze.py` treats a missing object as mode `none`, so the existing
2026-08-31 smoke JSONs pair correctly without regeneration.

```
early_sort: { mode, applied, blocked, blocked_reason, early_sort_failed,
              failed_reason, action_wall_s, method, target_path,
              bytes_requested, write_rc, write_stderr, cgroup_write_grant,
              post_action_resident_pct_R/_L, post_action_resident_pages_R/_L,
              memory_current_before/_after, bytes_freed_observed,
              cgroup_delta_over_action{ pgscan_delta, pgsteal_delta,
                                        active_file_before/_after,
                                        inactive_file_before/_after } }
```

### `run_ladder.sh`

* `--early-sort none|guided|blind` threads `EARLY_SORT` into every cell, in both
  the docker and the `--local` backend.
* `--es-matrix` runs the pre-registered matrix by re-invoking itself once per
  leg (so each leg gets normal image/volume/laydown handling), forwarding every
  other flag verbatim:
  `fixed3 × {guided,blind} × {fits,marginal,boundary,thrash}` then
  `converge × {guided} × {marginal,boundary}` — 10 cells. It does **not** re-run
  baselines (see §9.4).
* Filenames: `convrepro_es_<esmode>_<rung>_<cellmode>[_smoke][_nocap]_<date>.json`.
  Baseline (`none`) cells keep their existing names byte-for-byte.
* `RUN_LABEL` deliberately does **not** encode the early-sort mode, so an ES
  cell and its baseline share a run label and can be paired.
* `--es-privileged` / `--no-es-privileged` (default: ON, and applied to **blind
  cells only**) — see §9.5, this is the one thing the reviewer must decide before
  the host run.
* One `early_sort:` summary line per ES cell on stderr (mode, applied/blocked,
  wall, post-action R/L residency, bytes requested/freed, reason).
* `--help` now prints the whole banner (the old `sed '2,40p'` truncated it).

### `analyze.py`

* `by_rung()` gained an `es` filter defaulting to `"none"`. **This is load-
  bearing:** without it an ES cell could displace a Tier-1 baseline in the
  table and in bars 1–5, since they share rung + mode. The Tier-1 table and the
  5 Tier-1 bars now see baseline cells **only**; their output on the pre-existing
  smoke set is identical to §4.3 above (checked line by line).
* New EARLY-SORT section, **inert unless the glob holds a cell with
  `early_sort.mode != "none"`**: per-ES-mode tables (with the action line under
  each cell), bars ES-1..ES-4, and the ES-5 exploratory table.
* **Pairing rule (never cross-run).** Cells are grouped by
  `(run_label with the cell-mode token stripped, generated_utc date)`. An ES cell
  is only ever compared with a `none` cell from that same group. Stripping the
  mode token is what lets a `fixed3` ES cell use the `converge` baseline of the
  *same ladder* as its steady reference; a different day or a different scale
  never matches. If >1 run in the glob carries ES cells, only the largest is
  judged and the others are named and explicitly *not* judged.
* Steady reference for ES-1/ES-2 is the same-run **`none` converge** cell.
  Fallbacks (guided converge, or a `none` fixed3 last pass) are printed with the
  numbers but marked `[NOT SCORED]` and force the bar to `NO DATA` — comparing
  the guided arm against itself would be circular.
* ES-2's reduction is `1 − excess_guided/excess_none` with
  `excess = Σ_{p=1..3} max(0, p50_p − steady)`. Judged at **marginal and
  boundary**; fits/thrash are printed `[informational]` (ES-4 is what governs
  those two rungs). A zero baseline excess makes the ratio **undefined** →
  `NO DATA` with an explanation, never a silent FAIL.
* `cap_enforced:false` / `scale != 1.0` triggers exactly the same
  MECHANICS-CHECK refusal for the ES bars as for the Tier-1 bars, with the same
  `(mechanics — NOT a bar verdict)` stamp on every verdict.

## 9.2 Smoke validation (executed 2026-08-31, `--local`, SCALE=0.2, NO cap)

```bash
bash spike/convergence_repro/run_ladder.sh --smoke --local --es-matrix
python3 spike/convergence_repro/analyze.py --dir data/eval_results
```

10 ES cells written to `data/eval_results/convrepro_es_*_smoke_nocap_20260831.json`
(guided × {fits,marginal,boundary,thrash} fixed3; blind × the same; guided ×
{marginal,boundary} converge). All 10 parse; `analyze.py` exits 0 on the mixed
20-cell glob (10 baseline + 10 ES) and still refuses every verdict.

**Guided — works, and the eviction is exactly what it should be:**

| datum | value |
|---|---|
| action wall time | **4.2 – 6.8 ms** (per cell, R = 1024 MiB / L = 358 MiB) |
| L residency, load → post-action | **100.0 % → 0.0 %** |
| R residency, post-action | **100.0 %** (untouched — only L was named) |
| `memory.current` drop over the action | **374.4 – 375.8 MB** vs L = 375,390,208 B — i.e. the freed bytes *are* L, to within a MB |
| `inactive_file` drop over the action | same magnitude; `active_file` unchanged |
| L residency during passes 1–3 | **0.0 %** — nothing re-faults L (no pass ever reads it) |
| pass-1 majflt | **0**, p50 ≈ 0.25 µs — physically correct with **no cap** and 53 GiB free: R was never reclaimed, so there is nothing for the early sort to save. Identical to the baseline cells (§4.2). |

So the guided arm's *mechanism* is fully verified here (the right file, only that
file, wall-timed, residency and cgroup accounting recorded); its *effect* is
necessarily zero without a cap and can only be measured on the host run.

**Blind — BLOCKED in this dev container, exactly as designed:**

```
early_sort: mode=blind blocked wall=0.0s R=None% L=None% freed=None req=375390208
  reason=memory.reclaim not writable at /sys/fs/cgroup/memory.reclaim
         (cgroup mount opts: ro,nosuid,nodev,noexec,relatime)
```

on all four rungs; `analyze.py` renders `BLOCKED … — ran as a 'none' cell` under
each cell and in the ES-5 table's *blind state* column. Probe detail:
`/sys/fs/cgroup/memory.reclaim` **exists** (mode `--w-------`, root:root — the
kernel interface is present on 6.18.33.2-microsoft-standard-WSL2) but the whole
cgroupfs is mounted `ro` (§3), so no write is possible here under any user.

**The two non-blocked blind branches were exercised via `ES_RECLAIM_FILE`**
(stand-in targets, mechanics only — these probes were not kept as results):

| target | result |
|---|---|
| a writable regular file | `applied=true blocked=false failed=false rc=0 wall=1.4 ms`; the file received exactly `375390208`; residency + `memory.current` before/after captured |
| `/dev/full` (guaranteed write error) | `applied=true blocked=false early_sort_failed=true rc=1 write_stderr="printf: write error: No space left on device"`, wall + residency still captured, **cell continued and emitted JSON** — this is the shape a partial-reclaim EAGAIN will take |
| a non-existent path | `blocked=true` ("memory.reclaim absent …") |

**Guard tests on the pairing rule** (scratch copies, not committed):

* ES cells + baselines stamped a *different date* → ES-2/3/4 `NO DATA`
  ("no `none` cell in this run"), ES-1 `NO DATA` with `[NOT SCORED: steady
  reference is a fallback]`. No cross-run pairing occurred.
* Two runs both carrying ES cells → `!! 2 distinct runs carry early-sort cells;
  judging ONLY the largest`, the other named and not judged.
* Glob of ES cells only (no baselines) → every Tier-1 and ES bar `NO DATA`,
  exit 0, no traceback.

## 9.3 Proof the `none` path is unchanged

A baseline cell re-run with the new `cell.sh` produced the **same filename** and
a JSON whose only difference from the committed 2026-08-31 file is the additive
`early_sort` object (`mode:"none"`, `applied:false`, all measurements null);
`grep -ci 'early sort' <cell log>` = **0** — the phase emits nothing at all. The
Tier-1 table and all 5 Tier-1 bar outputs on the existing smoke set are
character-identical to §4.3.

## 9.4 Exact host-side commands for the full ES run

From the docker host, repo root, quiet box. **Order matters** and everything
must land on the **same date tag** — `analyze.py` never pairs across runs.

```bash
cd /workspaces/sfu-library-thinclient

# (a) image + volume, if not already built
bash spike/convergence_repro/run_ladder.sh --build-only

# (b) THE BASELINES FIRST — the `none` ladders. --es-matrix does NOT run these,
#     and without them every ES bar is NO DATA.
bash spike/convergence_repro/run_ladder.sh --mode fixed3
bash spike/convergence_repro/run_ladder.sh --mode converge

# (c) the pre-registered early-sort matrix (10 cells:
#     fixed3 x {guided,blind} x {fits,marginal,boundary,thrash}
#     + converge x guided x {marginal,boundary})
bash spike/convergence_repro/run_ladder.sh --es-matrix

# (d) analyse — substitute the real date tag; this glob catches BOTH the
#     baseline and the convrepro_es_* files, which is what pairing needs.
python3 spike/convergence_repro/analyze.py \
    --dir data/eval_results --glob 'convrepro_*_20260901.json'
```

Header must read `scale(s) : [1.0]   caps enforced: True` and neither bars
section may say MECHANICS CHECK. Useful variants:

```bash
# one arm only
bash spike/convergence_repro/run_ladder.sh --mode fixed3 --early-sort guided \
     --rungs marginal,boundary
# deliberately record the blocked blind path (no privileged cells)
bash spike/convergence_repro/run_ladder.sh --mode fixed3 --early-sort blind \
     --rungs marginal --no-es-privileged
# fast mechanics re-check of the whole ES pipeline (~10 min, no verdict)
bash spike/convergence_repro/run_ladder.sh --smoke --es-matrix
```

Cost: the ES matrix is 10 more cells on top of the Tier-1 ladders. At SCALE=1
budget the same per-cell time as §6 (~10–20 min per fixed-3 cell, more for the
converge cells) — call it a few hours for (b)+(c) together.

## 9.5 THE BLIND ARM — what the reviewer must know BEFORE the host run

1. **Docker mounts `/sys/fs/cgroup` read-only, so an ordinary cell cannot write
   its own `memory.reclaim`.** Left alone, every blind cell would record
   `blocked` and the arm would produce nothing. `run_ladder.sh` therefore adds
   **`--privileged` to blind cells only** (default ON; `--no-es-privileged`
   turns it off). Privileged makes the cgroup mount read-write; `--memory` /
   `--memory-swap` are still real cgroup limits and the existing in-cell
   `memory.max` verification still runs and must still be watched. **Recorded
   deliberate difference: blind cells run privileged, guided and `none` cells do
   not.** If the reviewer's policy forbids privileged containers, run
   `--no-es-privileged`; a BLOCKED blind arm is an outcome the pre-registration
   explicitly allows ("recorded BLOCKED, not failed"). This flag was **not
   exercisable here** (no docker daemon, §3) — treat it as unproven and check
   the first blind cell's `early_sort` block before letting the matrix run on.
2. **Page-cache charging.** `memory.reclaim` only reclaims memory charged to
   *that* cgroup. R's and L's pages are charged to whichever cgroup first
   faulted them in, so the between-cell re-eviction (already in the docker
   backend) is what guarantees the cell itself charges them. If a blind cell
   ever reports a large `bytes_requested` with a near-zero
   `bytes_freed_observed` **and** R/L still 100 % resident, suspect charging to
   another cgroup, not a kernel-policy result.
3. **A non-zero write rc is data, not an error.** Partial proactive reclaim
   returns an errno (typically EAGAIN); the cell records
   `early_sort_failed=true`, `write_rc`, `write_stderr` and carries on. Do not
   read that as a harness failure — read it as "the kernel could not free
   everything asked".
4. **Cost asymmetry is part of the ledger.** Guided costs ~5 ms (a `vmtouch -e`
   by name). Blind's `action_wall_s` is real reclaim work in the caller's
   context and will be far larger; both are recorded, and the write-up should
   compare them.
5. **What ES-5 is actually asking.** At the moment of the action, L and R have
   identical reference bits, so any blind success comes from inactive-list order
   alone. The decisive numbers are `post_action_resident_pct_R` vs `…_L` in the
   ES-5 table: **R high + L low** = order protected the repeat set; both roughly
   equally cut = the kernel took the repeat set down with the residue.
6. Kernel floor: `memory.reclaim` is cgroup **v2** and **≥ 5.19**. Present on
   this WSL2 6.18 kernel. On a v1 host the arm records blocked with that reason.

## 9.6 Deviations added by this pass (on top of §5)

8. **`--privileged` on blind cells** (default ON, `--no-es-privileged` to
   disable) — not in the pre-registration; without it the blind arm cannot be
   attempted at all under docker. See §9.5.1.
9. **`ES_RECLAIM_FILE` override in `cell.sh`** — not in the spec; the only way
   to exercise the non-blocked blind branches where no writable cgroup exists
   (§9.2). Never set by a protocol run; when it is set, the JSON's
   `early_sort.target_path` shows the substituted path.
10. **ES-2 is judged at marginal + boundary**, with fits/thrash printed
    informationally. The pre-registration text does not name rungs for ES-2;
    ES-4 already governs fits and thrash, and those rungs have no transient to
    reduce. Recorded as an interpretation, not a silent choice.
11. **An undefined ES-2 reduction (zero baseline excess) is `NO DATA`, not
    FAIL**, with the reason printed.
12. **ES-1/ES-2 refuse to score against a fallback steady reference** (anything
    other than the same run's `none` converge cell). The number is still shown.
13. Smoke filenames keep the `_smoke_nocap_` infix inside the pre-registered ES
    name, i.e. `convrepro_es_<esmode>_<rung>_<cellmode>_smoke_nocap_<date>.json`;
    a real run has no infix and matches the spec's name exactly.

## 9.7 Efficacy status for the ES arm (CLAUDE.md new-module rule)

**IMPLEMENTED, EFFICACY UNMEASURED.** The guided arm's mechanism is verified
(right file, only that file, wall-timed, residency + cgroup accounting recorded);
the blind arm's write path is verified only against stand-in targets and is
**BLOCKED on every real cell run so far**. No ES cell has ever run under a memory
cap, so ES-1..ES-5 have no result of any kind. The numbers in §9.2 measure the
harness, not the claim. On completion the session lead records measured
numbers + absolute date + result paths (`data/eval_results/convrepro_es_*.json`)
in this directory's `RESULTS.md` and points
`docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`
§5.3 at them.

---

# 10. TIER-1b BUILD (2026-08-31)

Built by an Opus subagent in the dev container on **2026-08-31**, strictly to
`PREREGISTRATION_TIER1B.md` (written before this code, per the repo's
write-before-run convention), which inherits everything not restated from
`PREREGISTRATION.md` and `PREREGISTRATION_EARLYSORT.md`. Motivation:
`RESULTS.md` — Tier-1 FAILED because its L-then-R load made R the
most-recently-loaded population, so under any cap > R the load itself performed
the "sort" and no convergence transient could exist.

**Nothing in this section touches a judged Tier-1 artifact.** The committed
`convrepro_*_20260831.json` cells and the Tier-1/ES verdicts in `RESULTS.md` are
frozen. See §10.6 for the one consequence of that which the reader must
internalise.

## 10.1 What changed, file by file

### `cell.sh`

* **Interleaved load (prereg Change 1).** New `LOAD_ORDER` env knob, default
  `interleaved` — THE Tier-1b protocol. R and L are cut into **64-MiB chunks**
  and merged into ONE deterministic proportional round-robin sweep. The
  schedule is pure-integer Bresenham: with `n_r` R-chunks and `n_l` L-chunks,
  step `k` in `[1, n_r+n_l]` emits an L chunk iff
  `floor(k*n_l/(n_r+n_l)) > floor((k-1)*n_l/(n_r+n_l))`. That emits exactly
  `n_l` L chunks spread as evenly as integers allow. At SCALE=1: 80 R + 28 L =
  108 chunks, schedule
  `RRRLRRRLRRRLRRRLRRRLRRRLRRLRRRL…RRRLRRRLRRL` (28 `L`s). Chunks are read with
  `dd bs=1M skip=<chunk*64> count=64`; the final chunk of each file is short by
  construction and `dd` simply stops at EOF. The loop asserts it emitted
  exactly `n_r`/`n_l` chunks and aborts the cell otherwise.
  **64 MiB is a declared constant** (prereg wording), so it is a `readonly`
  shell variable with *no* environment override — it cannot be quietly tuned.
* **Exploratory order arm.** `LOAD_ORDER=r_then_l` (the pre-registered arm) and
  `LOAD_ORDER=l_then_r` (the Tier-1 order, for reference) do whole-file reads
  and are stamped `load_phase.order_arm = true`.
* **JSON.** `load_phase` gained `load_order`, `order_arm`, `chunk_mib`,
  `n_chunks_R`, `n_chunks_L`, the full `schedule` string, `load_wall_s`, and
  post-load residency of **both** files as percentage *and* pages
  (`post_load_resident_pages_R/L`, `total_pages_R/L`). Top level gained
  `"protocol": "tier1b"`. The `schema` string is deliberately **unchanged**
  (`convrepro/cell/1`) and every addition is optional, so `analyze.py` still
  loads the frozen Tier-1 cells.
* **Defect D3 — the convergence rule.** `converged` now requires the plateau
  (±10% pass-to-pass, twice in a row) **AND** a final-pass majflt < 1% of
  pass-1's, or exactly 0. Tier-1 accepted either half alone, which is why
  deep's flat ~1.31M majflt/pass was scored "converged". `converge_reason` is
  now e.g. `plateau_within_10pct_x2_and_majflt_zero`.

### `run_ladder.sh`

* **Rungs (prereg Change 2).** `RUNG_GIB` = fits 10, **marginal 6.25**,
  boundary 5.75, thrash 3.75, deep 2.75. Tier-1's tuned `6.64` is retired: it
  was calibrated against the broken load order. Every rung below `fits` now
  sits below D = 6.75 GiB, so the load actually evicts. The calibration gate
  (marginal ∈ [6.0, 6.5], ≤3 steps; then L → 2.5 GiB once) is documented in the
  comment above the table and in `HOST_RUN.md`; nothing else may be tuned.
* **Defect D1 — file naming.** Real cells are `convrepro_t1b_*`; any cell that
  can never be bar evidence (`--smoke` or uncapped `--local`) is written under
  the prefix **`convrepro_mech_`**. The documented analyze glob
  `convrepro_t1b_*_<date>.json` therefore cannot match a mechanics cell no
  matter what date it carries — the exclusion is *structural*, which is exactly
  what Tier-1's glob was not (its smoke files shared the date tag and had to be
  filtered by an explicit file list on the day).
* **Defect D2 — `--build-only`.** It used to `exit 0` after the image build,
  before the volume laydown, despite the "image + volume" label. It now falls
  through and exits after the laydown (both backends).
* **New flags.** `--load-order interleaved|r_then_l|l_then_r`, and `--order-arm`
  — the pre-registered shortcut that runs exactly one cell: marginal rung,
  fixed3, `r_then_l`. `LOAD_ORDER` is threaded into both the docker (`-e`) and
  `--local` backends and appears in the filename as `_orderr_then_l`.

### `analyze.py`

* **Bars 1b–4b re-specified** per the prereg. **Every latency comparison moved
  from clat p50 to clat p95** (Tier-1's lesson: the synthetic's median is
  page-cache-hit-dominated even while thrashing — thrash p50 was 3.4×
  converged at ~600k faults/pass). p50 is still printed, explicitly marked
  "context only, NOT judged".
  - **1b** gained the explicit PRECONDITION `marginal pass-1 majflt > 0`, and
    prints the marginal cell's load order + post-load residency next to it.
  - **2b** uses the fixed convergence rule and steady **p95** within ±10%.
  - **3b** uses steady p95 ≥ 10× the converged reference p95.
  - **4b** clamps pass-1 pgscan values below **4096 pages (16 MiB)** to a
    single "~0" tier before the monotonicity test, and prints raw and clamped
    rows. Tier-1 failed bar 4 on a 512-page wiggle between two rungs that had
    no pressure at all.
  - **5** unchanged (fits `active_file` < 0.25×R).
* **`converged` is recomputed, not trusted.** `converged_fixed(cell)` applies
  the D3 rule to the cell's own per-pass majflt, so cells written by the *old*
  `cell.sh` are judged by the same rule as new ones, and any disagreement with
  the stored field is printed loudly (`[!! cell JSON says converged=True … —
  re-judged by the FIXED D3 rule]`). A `fixed3` cell never self-reports
  convergence, so that case is annotated rather than flagged as a mismatch.
* **ES bars ES-1..ES-4 and the ES-5 table** take the same p95 substitution
  (`transient_excess` and `es_steady_ref` are now p95-based) and use the fixed
  convergence rule for their "trusted steady reference" test.
* **Order-arm cells are excluded from every table and bar by construction**
  (`by_rung` and `es_pick` drop `load_phase.order_arm` cells) and get their own
  `EXPLORATORY ORDER ARM` section, printed next to the interleaved cell of the
  same rung/mode for contrast. No verdict is ever issued there.
* **Legacy Tier-1 cells** (no `load_phase.load_order`) load and print
  correctly, are labelled `l_then_r(legacy-tier1)`, and trigger a loud header
  banner saying the Tier-1b bars are not the frozen Tier-1 verdict.
* **Default `--glob` is now `convrepro_t1b_*.json`** (D1).

### `HOST_RUN.md`

Rewritten for Tier-1b: the Tier-1 → Tier-1b diff table, the new run sequence
(including `--order-arm`), the D1-consistent glob **with its acceptance
criterion stated as structural**, the exhaustive Tier-1b calibration gate, an
added validity check (`load_order: "interleaved"`, 80/28 chunks, 108-char
schedule, and `post_load_resident_pct_R < 100` at every rung below `fits` — if
R comes back 100% resident, Tier-1's failure mode has returned: stop and report,
do not tune), and a new **Windows-host-gotchas** section covering the three
problems hit on the 2026-08-31 run: the Windows-Store `python3` App-Execute
stub shadowing the real interpreter, `/c/`-style path translation (`cygpath`),
and MSYS argument mangling vs the docker build context / `-v` / `--entrypoint`
(`MSYS_NO_PATHCONV=1`, `MSYS2_ARG_CONV_EXCL`, the `//data` double-slash escape).

## 10.2 Smoke / mechanics validation (executed 2026-08-31, `--local`, SCALE=0.2, NO cap)

Docker is still unavailable in this dev container (`docker info` fails) and
`/sys/fs/cgroup` is mounted `ro`, so **no capped cell was run here** — that is
host-side work, per the pre-registration. 17 mechanics cells were written to
`data/eval_results/convrepro_mech_*_20260831.json` (+ `.json.log`).

**Interleaved load — verified.** At SCALE=0.2 (R=1024 MiB → 16 chunks,
L=358 MiB → 6 chunks) the cell log shows:

```
[cell marginal] load phase: INTERLEAVED sweep, 64 MiB chunks, R=16 L=6 (total 22)
[cell marginal] load schedule: RRRLRRRLRRLRRRLRRRLRRL
[cell marginal] post-load residency: R=100.0000% (262144/262144 pages)  L=100.0000% (91648/91648 pages)
```

and the JSON carries `load_order: "interleaved"`, `chunk_mib: 64`,
`n_chunks_R: 16`, `n_chunks_L: 6`, the schedule string, and both files'
post-load residency in percent and pages. The SCALE=1 schedule was verified
separately to be 108 characters with exactly 28 `L`s.

**Order arm — verified.** `--order-arm` wrote
`convrepro_mech_marginal_fixed3_orderr_then_l_smoke_nocap_20260831.json` with
`load_order: "r_then_l"`, `order_arm: true`; `analyze.py` kept it out of every
table and bar and reported it in the ORDER ARM section beside the interleaved
marginal cell.

**Early-sort paths — verified under the new naming.** guided applied cleanly at
all four rungs (L → 0.0% resident, R → 100%, ~7 ms); blind recorded
`blocked = true` with reason "memory.reclaim not writable … (cgroup mount opts:
ro,…)" — the pre-registration explicitly allows BLOCKED, and `--privileged`
(host-side) is what unblocks it.

**Defect D1 — verified structurally.** With 17 `convrepro_mech_*` cells on
disk, `ls data/eval_results/convrepro_t1b_*` matches **zero** files. The
documented bar glob cannot pull a mechanics cell in.

**Defect D3 — verified end-to-end.** A `converge` cell run with the pre-declared
`SKIP_LOAD=1` validation knob (`convrepro_mech_deep_converge_smoke_nocap_…`,
stamped `load_phase.skipped: true`, never bar evidence):

| pass | wall s | majflt |
|---|---|---|
| 1 | 43.83 | **262,144** (= 1 GiB / 4 KiB exactly) |
| 2 | 0.56 | 0 |
| 3 | 0.56 | 0 |
| 4 | 0.57 | 0 |

`converged at pass 4 (plateau_within_10pct_x2_and_majflt_zero)`. Under the
Tier-1 rule this cell would have stopped at **pass 3** on the low-fault branch
alone; requiring the plateau as well is exactly the D3 change, and it is
observable in the pass count.

**Defect D3 on the frozen Tier-1 data — verified.** Running the new
`analyze.py` over the frozen Tier-1 cells re-judges the deep converge cell:
`converged=False (final majflt 1,309,238 is not <1% of pass-1 992,981)
[!! cell JSON says converged=True (plateau_within_10pct_x2)]`. That is the
thrashing plateau D3 was written to reject, and it moves bar 3b's "neither
converges" clause in the *correct* direction.

**Analyze end-to-end — verified.** `analyze.py --glob 'convrepro_mech_*.json'`
loaded all 17 cells, printed the fixed3 and converge tables, the five Tier-1b
bars, the ES section and the ORDER ARM section, and correctly stamped
`*** MECHANICS CHECK ONLY, NOT A BAR VERDICT ***` with the reason
`scale(s) [0.2] != [1.0]; cap_enforced=false on at least one cell`.

## 10.3 What the smoke could NOT show, and why

**A nonzero pass-1 majflt under the actual (non-skipped) interleaved load is
mechanically impossible in this container, and its absence here is NOT
evidence about Tier-1b.** The whole mechanism under test is *reclaim*: pass 1
starts with R partially non-resident only because the load-time evictions hit
the sweep head. With no memory cap (`/sys/fs/cgroup` is `ro`, no docker
daemon) and 46 GiB free against a SCALE=0.2 demand of 1.35 GiB, the kernel
never reclaims anything, so both files come back 100% resident after the load
at every rung — exactly what the smoke shows, for all five rungs, both orders.
The `SKIP_LOAD=1` cell above is the only local way to drive the majflt/latency
capture path, and it proves the *plumbing* (262,144 faults counted, ms/fault,
clat, cgroup deltas, the D3 rule) but says nothing about the load order.

Consequence for the reviewer: **the first real evidence that Change 1 works is
the host-side SCALE=1 fixed3 marginal cell.** The validity check to run first is
`load_phase.post_load_resident_pct_R < 100` at every rung below `fits`, then
bar 1b's precondition (`marginal pass-1 majflt > 0`). Both are called out in
`HOST_RUN.md`.

## 10.4 Deviations from the pre-registration

**None substantive.** Three implementation choices are recorded so they are not
mistaken for silent liberties:

1. **`SKIP_LOAD=1` was used for one smoke cell.** It is the pre-existing
   validation knob from §5 deviation 2, not a new one; the cell is stamped
   `load_phase.skipped: true` and is named `convrepro_mech_*`, so it is
   excluded from the bar glob twice over. It is mechanics evidence only.
2. **`LOAD_ORDER=l_then_r` exists in addition to the pre-registered
   `r_then_l`.** The prereg names only the R-then-L arm; the Tier-1 order is
   kept selectable so the triptych (L→R / interleaved / R→L) can be completed
   on one box if the session lead wants it. It is stamped `order_arm: true`
   like the other arm and is never judged. `--order-arm` runs only the
   pre-registered `r_then_l` cell.
3. **The mechanics prefix is `convrepro_mech_`, not a date-tag change.** The
   prereg says "smoke/mechanics cells get a distinct tag that the documented
   analyze glob excludes by construction" without fixing the mechanism; a
   prefix satisfies "by construction" more strongly than an infix or a date
   would (an infix tag still matches `convrepro_t1b_*`).

## 10.5 Known limitations (unchanged from §6 unless noted)

* **No capped cell has been executed for Tier-1b.** Everything about cap
  enforcement, load-time eviction, and therefore the entire artifact under
  test is untested until the host run. The interleaved load has been exercised
  only where nothing gets evicted.
* Cell wall time grows slightly: the interleaved load is 108 `dd` invocations
  per cell at SCALE=1 instead of 2. Measured overhead at SCALE=0.2 (22 dd's,
  warm cache): 0.398 s total load wall. Negligible against a multi-minute cell.
* All other §6 limitations (untested host-side cgroup sampler, WSL2/classic-LRU
  only, quiet-box requirement, `docker pull` FIPS TLS crash) stand.

## 10.6 Reading the new analyze.py against the FROZEN Tier-1 cells

`analyze.py` is now the **Tier-1b** tool. Pointing it at the frozen Tier-1
cells does **not** reproduce the Tier-1 verdicts recorded in `RESULTS.md`, and
must never be quoted as if it did — the bars themselves were re-specified
(p50 → p95, the bar-1b precondition, the bar-4b clamp). Measured 2026-08-31,
for the record only: on the 20 frozen Tier-1 cells the Tier-1b bars read
1b FAIL, 2b FAIL, 3b PASS, 4b PASS, 5 PASS (Tier-1's frozen verdict was
1 FAIL, 2 PASS, 3 FAIL, 4 FAIL, 5 PASS). Bars 3b/4b flip to PASS because the
tail metric and the noise-floor clamp were introduced precisely to fix
bar-design faults §4 of RESULTS.md diagnosed; 2b flips to FAIL on a 12.1% p95
spread between two zero-fault cells. **None of this is a Tier-1b result** —
those cells were produced under a different load protocol, which the tool now
says out loud in its header. The frozen Tier-1 verdict stands as written.

## 10.7 Efficacy status (CLAUDE.md new-module rule)

> **UPDATED 2026-08-31 — MEASURED.** The SCALE=1 capped host run completed
> (cells committed `3729df30`; verbatim analyze output
> `data/eval_results/HOST_ANALYZE_t1b_20260831.txt`). Verdicts:
> **Tier-1b OVERALL FAIL** (bars 1b/2b/3b FAIL, 4b/5 PASS) and **ES OVERALL
> FAIL** (ES-1/ES-2 NO DATA, ES-3 FAIL, ES-4 PASS). The harness itself was
> sound: the interleaved load produced post-load R < 100% at every rung below
> `fits` (92.34 / 84.84 / 54.96 / 40.00), the calibration gate was never used,
> and `analyze.py` reproduces the host report byte-identically in-container.
> Headline numbers: marginal/boundary majflt trajectories self-similar scaled
> 1.98x by initial deficit; pass-3 inversion ratio 0.04x against a predicted
> 2–20x; guided early-sort cuts fault work 75.2% / 74.7% (its theoretical
> maximum); blind reclaim is net-harmful on fault work at all four rungs.
> Full verdicts and the metric/bar-design findings: `RESULTS.md`, Tier-1b
> sections 8–17. The paragraph below is the pre-run status, kept for the
> record.

**IMPLEMENTED, EFFICACY UNMEASURED (status as of the pre-run build).** The Tier-1b harness's *mechanics* are
verified (interleaved schedule, both-file residency capture, order arm, D1/D2/D3
fixes, p95 bars, analyze end-to-end) — see §10.2 for what was measured, with
what numbers, on which date, and where the raw cells are. The *claim* under
test (bars 1b–5, ES-1..ES-5) has **no result of any kind**: no Tier-1b cell has
ever run under a memory cap. On completion the session lead records measured
numbers + absolute date + result paths
(`data/eval_results/convrepro_t1b_*_<date>.json`) in this directory's
`RESULTS.md` and points
`docs/session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`
at them.

## 10.8 Defect D4 — image staleness (found on the host run, fixed after it)

`run_ladder.sh` gated the image build on `[ -z "$(docker images -q "$IMAGE")" ]`
— tag exists, skip build — with no staleness check. `cell.sh` and `jobs/` are
baked into `convrepro:latest` by `COPY`, so any host checkout that had already
built a Tier-1 image would have run the Tier-1b ladder with **Tier-1's
`cell.sh`**: interleaved load absent, order arm absent, and the cells would
carry no `protocol: tier1b` stamp.

Caught by the host session before any Tier-1b cell ran. It hand-rebuilt
(`3801e4026241` -> `c1689cfc2775`) and verified the new `cell.sh` in-image
first; all 21 committed cells carry `protocol: tier1b`, so **the 2026-08-31
run is unaffected**.

Fix (2026-08-31, after the run): the build inputs (`Dockerfile`, `cell.sh`,
`jobs/*.fio`) are hashed to a 16-hex-char digest, stamped on the image as the
label `convrepro.build_hash`, and compared via `docker image inspect` on every
invocation; a mismatch (or a missing label, i.e. any pre-fix image) forces a
rebuild and says so. `HOST_RUN.md` gains the operator-visible wording so a
stale checkout is detectable from the first log line. No cell JSON schema
change: the existing `protocol` field is already the per-cell ground truth.
