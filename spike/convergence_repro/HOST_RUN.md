# HOST RUN — TIER-1b convergence ladder + early-sort arm + order arm (paste-ready)

Paste everything below the `---` into a Claude Code instance (or follow it by
hand) running **directly on the host** — NOT inside the dev container. Verified
2026-08-31 (and identically 2026-07-03 for E7b/R1): the dev container has no
usable docker daemon, `/sys/fs/cgroup` is read-only, and no memory cap can be
enforced there. Run where `docker info` succeeds.

> **2026-09-05 — this file now carries two run-books.** Everything down to
> "Afterwards — commit from the host checkout" is the original **Tier-1b**
> docker-ladder run-book (unchanged, still correct for Tier-1b). The
> **Tier-1d §4 calibration window** is a different experiment on a different
> harness (no docker, native `systemd-run`, run as **root inside the Ubuntu
> WSL2 distro**) and has its own section at the bottom:
> [Tier-1d §4 calibration window](#tier-1d-4-calibration-window--2026-09-05-wsl2-distro-as-root).

Written 2026-08-31 for **Tier-1b**. Pre-registrations (bars are FROZEN — read
before running): `PREREGISTRATION_TIER1B.md` (bars 1b–4b + unchanged bar 5, the
new rungs, the interleaved load, the order arm), inheriting from
`PREREGISTRATION.md` and `PREREGISTRATION_EARLYSORT.md` (ES-1..ES-5, now judged
on p95). Why Tier-1 failed: `RESULTS.md`. Exact per-command reference:
`BUILD_NOTES.md` §7 (Tier-1), §9 (ES arm), §10 (Tier-1b).

---

## ⚠️ RULE ZERO — safety

- Get the repo on the host: `git clone
  https://github.com/Spicy-Sashimizy/sfu-library-thinclient` (or `git pull`
  an existing host checkout). Branch `sfu-library-thinclient`.
- Benchmark data lives ONLY in the docker named volume the script creates.
  **Never** touch `data/seismic_150m/` (irreplaceable, read-only, not needed
  by this experiment at all). Result JSONs go under `data/eval_results/`.
- The caps wrap ONLY the benchmark cells (`docker run --rm --memory=X
  --memory-swap=X`). Do not stop/restart the dev containers.
- **Keep the box quiet for the whole run** (R2's host-noise lesson): no
  builds, no browsers hammering, no other benchmarks. Budget ~10–20 min per
  fixed-3 cell at SCALE=1, more for 12-pass converge cells at thrash/deep —
  plan for several hours total. Tier-1b's interleaved load is ~108 × 64 MiB
  `dd` calls per cell instead of two whole-file reads; the extra process
  overhead is a few seconds, not minutes.
- Blind ES cells run `--privileged` BY DESIGN (only way to a writable
  `memory.reclaim`; guided/none cells do not). If policy forbids that, use
  `--no-es-privileged` — blind cells then record BLOCKED, which the
  pre-registration explicitly allows. Decide before the matrix, and check
  the FIRST blind cell's `early_sort` JSON block before letting it run on.

## What is different from the Tier-1 host run

| | Tier-1 | Tier-1b |
|---|---|---|
| load | L then R, whole files | **interleaved**: 64-MiB chunks of R and L in one Bresenham round-robin sweep |
| marginal cap | 7g → tuned 6.64g | **6.25g** (0.93×D — a real 0.5 GiB deficit) |
| bars | clat **p50** | clat **p95** everywhere; bar 1b has a majflt>0 precondition; bar 4b clamps pgscan < 4096 pages |
| converged | plateau **or** low-fault | plateau **and** low-fault (defect D3) |
| result files | `convrepro_*` | `convrepro_t1b_*`; mechanics cells are `convrepro_mech_*` |
| extra cell | — | one exploratory **order arm** (marginal, fixed3, R-then-L) |

## Run sequence (same day, same label — ES bars refuse cross-run baselines)

```bash
cd <host-checkout>/sfu-library-thinclient
bash spike/convergence_repro/run_ladder.sh --build-only          # image AND volume (D2 fixed)
bash spike/convergence_repro/run_ladder.sh --mode fixed3         # Tier-1b headline, 5 rungs
bash spike/convergence_repro/run_ladder.sh --mode converge       # Tier-1b steady state
bash spike/convergence_repro/run_ladder.sh --es-matrix           # 10 early-sort cells
bash spike/convergence_repro/run_ladder.sh --order-arm           # 1 exploratory order-arm cell
python3 spike/convergence_repro/analyze.py \
    --dir data/eval_results --glob 'convrepro_t1b_*_<today>.json'
```

**Image staleness (defect D4, fixed 2026-08-31 AFTER the Tier-1b run).** The
first `run_ladder.sh` invocation prints either `building convrepro:latest
(build_hash ...)`, `image ... is STALE ... rebuilding`, or `image ... already
present and current (build_hash ...)`. Any other wording means the checkout
predates the D4 fix and the build may be skipped while `cell.sh` is stale —
`docker rmi convrepro:latest` before running, or the ladder can silently
execute an older protocol. Confirm the first cell's JSON carries the expected
`protocol` value regardless.

**Acceptance criterion for the analyze command (defect D1 fixed).** The glob
`convrepro_t1b_*` cannot match a mechanics cell: `run_ladder.sh` writes every
smoke / uncapped-`--local` cell under the prefix `convrepro_mech_` instead, so
the exclusion is structural rather than something the operator has to remember
(Tier-1's bug was exactly that — its smoke files shared the date tag and had to
be filtered by hand). The report header must read
`scale(s) : [1.0]   caps enforced: True` and the bars section must **not** say
MECHANICS CHECK. If it does, a mechanics cell was passed explicitly.

The order-arm cell is written as `convrepro_t1b_marginal_fixed3_orderr_then_l_
<today>.json`, carries `load_phase.order_arm: true`, and `analyze.py` keeps it
out of every table and bar by construction — it appears only in the
"EXPLORATORY ORDER ARM" section at the end of the report.

## ⚠️ CALIBRATION GATE — check after the fixed3 ladder, before anything else

Pre-authorized and **exhaustive** (PREREGISTRATION_TIER1B.md Change 2):

1. Check the marginal fixed3 cell. The Tier-1b design needs **pass-1 majflt > 0
   with a falling trajectory over passes 1→3** (that is bar 1b's precondition,
   and post-load residency of R should be < 100%). If marginal's transient is
   shorter than 2 passes (e.g. pass-2 majflt already ≈ 0):
2. The marginal cap may move inside **[6.0g, 6.5g], at most 3 steps**. There is
   no cap flag — edit the `RUNG_GIB` table in `run_ladder.sh` (search for
   `[marginal]=6.25`), then re-run
   `bash spike/convergence_repro/run_ladder.sh --mode fixed3 --rungs marginal`
   (and later the marginal converge + ES cells at the same value).
3. If the transient is still < 2 passes after 3 steps, **L may be grown once to
   2.5 GiB** (`L_BASE_MIB=2560`; D → 7.5 GiB, caps re-derived from the same
   ratios) and **all cells re-run fresh**.
4. Nothing else may be tuned. Report every tuned value as tuned; move pre-tune
   cells to `data/eval_results/tuning_history/` before re-running so they are
   not overwritten.

## Per-cell validity checklist (any failure ⇒ cell is recorded-not-concluded)

- `cap_enforced: true` and `cap_bytes_in_force` matches the rung
- `swap_confounded: false` on every pass
- `eviction.post_evict_resident_pct_*` ≤ 1
- `load_phase.load_order: "interleaved"` on every judged cell, with
  `n_chunks_R`/`n_chunks_L` = 80/28 at SCALE=1 and a `schedule` string of 108
  characters containing exactly 28 `L`s
- `load_phase.post_load_resident_pct_R` **< 100** at every rung below `fits` —
  if R is 100% resident after the load, the load sorted the data for the kernel
  and Tier-1's failure mode has returned; stop and report, do not tune
- ES guided cells: `early_sort.post_action_resident_pct_L` ≈ 0 with R ~100
- ES blind cells: if `bytes_freed` ≈ 0 AND R+L still ~100% resident, the
  reclaim hit another cgroup's cache — see BUILD_NOTES §9.5 point 2

## ⚠️ Windows-host gotchas (all three hit the 2026-08-31 Tier-1 run)

If the host is Windows (Git Bash / MSYS2 / Docker Desktop), these bite before
anything else does. All were solved on-run; keep them for future host runs.

1. **The Windows-Store `python3` stub shadows the real interpreter.** Windows
   ships `%LOCALAPPDATA%\Microsoft\WindowsApps\python3.exe`, an App-Execute
   alias that opens the Microsoft Store and exits 9009 instead of running
   anything. `run_ladder.sh` and `analyze.py` both call `python3`.
   Detect: `python3 -c 'print(1)'` prints nothing / opens the Store, or
   `type -a python3` lists a `WindowsApps` path first.
   Fix (either):
   ```bash
   # a) point at a real interpreter for the whole session
   alias python3=/c/Python312/python.exe        # or: python3(){ py -3 "$@"; }
   # b) turn the alias off: Settings > Apps > Advanced > App execution aliases
   #    -> disable "python.exe" and "python3.exe"
   ```
   Verify with `python3 -c "import json,sys; print(sys.executable)"` BEFORE the
   first cell — a stub only fails at the JSON-extraction step, after a cell has
   already burned its wall time.
2. **`/c/`-style paths vs Windows paths.** Git Bash presents `C:\foo` as
   `/c/foo`. The docker CLI on Windows is a native Windows binary and does not
   understand `/c/...`; the shell scripts do. Two consequences:
   - always `cd` into the checkout and use the repo-relative invocations above
     (they resolve through `BASH_SOURCE`, which stays MSYS-side);
   - if you must hand docker a host path, translate it first:
     `cygpath -w "$PWD"` (or `cygpath -m` for forward slashes).
   Nothing in this harness bind-mounts a host path — the data lives in a docker
   **named volume** precisely so this never has to be solved.
3. **MSYS path mangling vs the docker build context and `-v`/`-e` arguments.**
   MSYS rewrites any argument that *looks* like a Unix absolute path into a
   Windows path before the Windows binary sees it. `-v convrepro_data:/data`
   becomes `-v convrepro_data:C:/Program Files/Git/data`, and
   `--entrypoint /bin/sh` becomes `--entrypoint C:/Program Files/Git/bin/sh` —
   both fail with confusing "invalid mount"/"no such file" errors.
   Fixes, in order of preference:
   ```bash
   export MSYS_NO_PATHCONV=1      # simplest: disable it for the whole session
   MSYS2_ARG_CONV_EXCL='*' bash spike/convergence_repro/run_ladder.sh ...
   docker run -v convrepro_data://data ... //bin/sh    # double-slash escape
   ```
   `MSYS_NO_PATHCONV=1` is the recommended one — set it once, before
   `--build-only`, and leave it set for the whole run. The double-slash form
   works but has to be applied to *every* in-container path, which is easy to
   get wrong halfway through a matrix.

## Afterwards — commit from the host checkout

```bash
git add data/eval_results/convrepro_t1b_*_<today>.json   # explicit list — NEVER git add . / -A
git commit -m "convrepro TIER-1b SCALE=1 host run <today>: ladder + ES matrix + order arm (raw cells)"
git push
```

Then report back in the dev-container session: the analyze.py output plus
any calibration/tuning actions taken. Bar verdicts and RESULTS.md are
written by the session lead in the dev container, not here.

---

# TIER-1d §4 calibration window — 2026-09-05 (WSL2 distro, as root)

Paste everything in this section into a Claude Code instance (or follow it by
hand) running **as root inside the Windows host's Ubuntu WSL2 distro** — NOT in
the dev container, NOT on the OCI box. Written 2026-09-05.

Read first: `PREREGISTRATION_TIER1D.md` — **bars are DRAFT and NOT frozen.**
This window is `§4 CALIBRATION`, explicitly exploratory. Its output is
calibration evidence recorded back into §4, not a bar verdict. Nothing here
freezes §5.

## T1d-0. Scope: Tier-1d runs LOCALLY, the OCI box is not used

Every Tier-1d window runs on **this machine** (Windows host → Ubuntu WSL2
distro). There is **no OCI dependency** for §4 or for situations S-skew,
S-skewsweep, S-capband, S-faultaround, S-inversion. The pre-reg's N7 trial-
horizon clause (OCI billing after 2026-09-03) therefore does **not** gate this
window — it never touches the OCI box.

The one OCI-gated item is **§6 gap 3, the real-access-histogram probe**, and
through it situation **S-realprofile** (§3.6). Both stay **parked**: no
histogram, no S-realprofile, and S-realprofile remains marked *est.* until
that probe runs somewhere. Do not attempt to substitute a synthetic histogram
for it.

## T1d-1. Kernel upgrade CONFIRMED — measured 2026-09-05 on this box

This is what unblocked the local Tier-1d windows. Both arms are now available
on hardware we control, which was previously an OCI-only capability
(publication-gate items 2–3).

| fact | value (measured 2026-09-05) |
|---|---|
| kernel (`uname -r`) | `6.18.33.2-microsoft-standard-WSL2+` (note the trailing `+` — custom build; the stock kernel has no `+` and no MGLRU) |
| `CONFIG_LRU_GEN` | `y` — MGLRU compiled in |
| `CONFIG_LRU_GEN_ENABLED` | `y` — **and default-ON at boot** |
| `CONFIG_LRU_GEN_WALKS_MMU` | `y` |
| `/sys/kernel/mm/lru_gen/enabled` | **`0x0007`** at boot (all three caps) |
| VM memory | 56 GB fixed, ~54 GB available |

**The consequence that matters for the protocol:** the box's everyday reclaim
policy is now **MGLRU**, so the `mglru` arm is the *production* setting and the
`classic` arm (`lru_gen=n`) is the one that deviates. Earlier drafts assumed a
`0x0000` default-off boot; that assumption is dead. `t1d_wsl2_orchestrator.sh`
was corrected for it on 2026-09-05 (commit `79cf8a04`): the restore target is
no longer blindly adopted from the start value (`0x0000` at start now means
*residue from an aborted classic cell*, and is warned + overridden), and the
per-arm toggle is asserted after the write, because on a `0x0007` boot a
silently-failed `echo n` runs a "classic" cell under MGLRU and voids the
comparison. If the orchestrator you are running does not contain the string
`ARM TOGGLE FAILED`, your checkout predates that fix — `git pull` first.

## ⚠️ T1d-2. Why this CANNOT run in the dev container

Verified 2026-08-31 (BUILD_NOTES §3) and **re-verified 2026-09-05**, from
inside the dev container:

| probe | result |
|---|---|
| `docker info` | fails — **no usable docker daemon** |
| `/sys/fs/cgroup` mount options | `ro,nosuid,nodev,noexec` — **read-only**, so **no memory cap can be enforced** |
| `/sys` (hence `/sys/kernel/mm/lru_gen/enabled`) | mounted **read-only**: `echo 7 > .../lru_gen/enabled` → `read-only file system`. The LRU arm cannot be selected. (Value is *readable*: `0x0007`.) |
| `/proc/sys/vm/drop_caches` | mode `--w-------`, root-owned; the container runs as uid 1000 with `CapEff: 0` — not writable, and the write is VM-global anyway |

So: **graded/capped cells cannot execute in the dev container at all** — not
slowly, not with a workaround. The dev container's role in Tier-1d is limited
to (a) uncapped soundness/histogram validation of the driver, and (b) reading
the JSONs and writing verdicts. **The windows run as root in the Ubuntu WSL2
distro via `t1d_wsl2_orchestrator.sh`.** A further reason the toggle must
happen distro-side: `lru_gen` and `drop_caches` are **VM-global** — one kernel
is shared with every docker-desktop container.

## T1d-3. Preconditions — the `.wslconfig` hygiene gate

The orchestrator **refuses to start** unless `C:\Users\<user>\.wslconfig` passes.
Hyper-V ballooning / page-reporting hands guest pages back to Windows behind the
kernel's back, which is a direct confound for a paging experiment. Required in
`[wsl2]`:

```ini
[wsl2]
memory=56GB              ; a FIXED size must be present (any absent memory= fails the gate)
processors=8             ; not gated, but pin it so the box is reproducible
pageReporting=false      ; MUST be exactly this
; autoMemoryReclaim      ; MUST be absent, or exactly: autoMemoryReclaim=disabled
kernel=C:\\Users\\<user>\\...\\bzImage   ; the custom kernel — without it, no MGLRU
```

Editing `.wslconfig` requires `wsl --shutdown` (from a Windows shell) and a
relaunch before it takes effect. After relaunching, re-confirm the kernel:

```bash
uname -r                                  # must end in '+'
cat /sys/kernel/mm/lru_gen/enabled        # must print 0x0007
```

`ALLOW_UNCLEAN_WSLCONFIG=1` exists as an override. It is for **smoke tests
only** — cells produced under it are recorded not-gradable, and the override is
written into the runlog. Do not use it for the calibration window.

## T1d-4. Quiet the box

`lru_gen` and `drop_caches` are VM-global, so anything else running in the VM is
noise in the measurement (R2's host-noise lesson, and the reason Tier-1c stopped
`sfu-serve`; there is no `sfu-serve` on this host, hence this manual step).

1. **Windows side**, per the orchestrator header: run
   `Stop-NonAlwaysOnContainers.ps1` (operator-side helper; it is not in this
   repo). If you do not have it, the equivalent from any shell that can reach
   the docker-desktop daemon is: stop every container that is not marked
   always-on — e.g. `docker ps -q | xargs -r docker stop` if nothing on the box
   is load-bearing at that moment. **The dev container is one of these** — do
   not run this window from a Claude session hosted in a container you are
   about to stop.
2. No builds, no indexing, no browser hammering, for the whole ~90 min window.
3. The orchestrator freezes `apt-daily{,-upgrade}.timer` itself and restores
   them in the trap; you do not need to.

## T1d-5. Launch (from the Ubuntu WSL2 distro, as root)

```bash
# get a root shell in the DISTRO (from a Windows shell):
#   wsl -d Ubuntu -u root
# or from a normal distro shell: sudo -i

REPO=/mnt/c/Users/<user>/claudebox-projects/sfu-library-thinclient
cd "$REPO" && git pull                    # must include commit 79cf8a04 or later
git rev-parse --abbrev-ref HEAD           # expect: sfu-library-thinclient
python3 -c 'import numpy; print("numpy ok")'   # apt-get install python3-numpy if missing
```

Two things about paths, both deliberate:

- `$REPO` lives on `/mnt/c` (drvfs). That is fine and intended — result JSONs
  land in the Windows checkout, so the same files are visible to the dev
  container session afterwards.
- `DATADIR` **must not** be on `/mnt/*`; the orchestrator refuses it. The
  default `/var/tmp/t1d_scratch` is on the distro ext4 rootfs, which is the
  whole point (drvfs/9p does not model local-filesystem mmap/mincore/majflt
  semantics). Leave it alone.

**Step A — soundness / control gate (~15 min).** Two uncapped-equivalent cells
(cap 8 GiB > R+L = 6.75 GiB) under `STRICT_SOUNDNESS=1`. This is the T1d-5
identity gate (pass-1 majflt == seed deficit) *and* the S-capband `cap > |R|`
control point (both arms should converge in one pass). Run it **first**: if the
skew draw is broken, it fails here in minutes instead of poisoning 90 minutes of
capped cells.

```bash
sudo systemd-run --unit=t1d-gate --collect -p TimeoutStopSec=300 \
  --setenv=STRICT_SOUNDNESS=1 \
  --setenv=WINDOW_DEADLINE_S=1800 \
  --setenv="CELLS=classic:92:8:1729:hotset:0.20:0.80 mglru:92:8:1729:hotset:0.20:0.80" \
  bash /mnt/c/Users/<user>/claudebox-projects/sfu-library-thinclient/spike/convergence_repro/t1d_wsl2_orchestrator.sh
```

**Step B — the calibration matrix (~90 min).** Only after Step A is clean.

```bash
sudo systemd-run --unit=t1d-orch --collect -p TimeoutStopSec=300 \
  --setenv="CELLS=classic:92:2.5:1729:hotset:0.20:0.80 mglru:92:2.5:1729:hotset:0.20:0.80 classic:92:4:1729:hotset:0.20:0.80 mglru:92:4:1729:hotset:0.20:0.80 classic:92:1.5:1729:hotset:0.20:0.80 mglru:92:1.5:1729:hotset:0.20:0.80" \
  bash /mnt/c/Users/<user>/claudebox-projects/sfu-library-thinclient/spike/convergence_repro/t1d_wsl2_orchestrator.sh
```

`CELL_TIMEOUT` (1800 s) and `WINDOW_DEADLINE_S` (5400 s) are already the
defaults for Step B — do not pass them unless you are deliberately changing
them. Plain `sudo bash <path-to-orchestrator>` also works for an attended run;
the `systemd-run` form is preferred so the window survives the shell going away.

⚠️ **`systemd-run` starts a clean environment.** `sudo CELLS=... systemd-run …`
silently does NOT reach the orchestrator — the variable is consumed by the
outer shell and the unit runs the built-in default matrix. Every override must
go through `--setenv=`, quoted as above because `CELLS` contains spaces.

Watch it:

```bash
journalctl -u t1d-orch -f
tail -f /mnt/c/.../sfu-library-thinclient/data/eval_results/_t1d_runWSL2_20260905.log
ls    /mnt/c/.../sfu-library-thinclient/data/eval_results/t1d_*_20260905.json
```

Cost note: the trap deletes `$DATADIR` on exit, so Step B re-lays down R+L
(~6.75 GiB of writes, a couple of minutes) rather than reusing Step A's. That is
intentional (clean scratch per window); just budget for it.

## T1d-6. The PROPOSED calibration matrix — NOT frozen bars

**Status: RUN 2026-09-05 exactly as proposed** (recorded in
`PREREGISTRATION_TIER1D.md` §4; raw cells `9ac830a3`). For the next window
use **T1d-10** — the judged matrix against the frozen bars — not this one.

**Status when written: PROPOSED.** §4 pre-authorizes adjusting the rungs **once**, and this
matrix is a starting point derived from the pre-reg, not a pre-registered bar.
Whatever is actually run gets recorded back into §4 of
`PREREGISTRATION_TIER1D.md` before §5 is frozen.

Derivation, all from the pre-reg: R = 5 GiB, L = 1.75 GiB, hot fraction
`h = 0.20` with mass `m = 0.80` (§2's primary hot-set model) ⇒ **hot set ≈ 1.0
GiB**. The regime that only skew creates is `hot-set < cap < |R|` (§2), i.e.
caps strictly between **1 GiB and 5 GiB**; the candidates below sample that band
at ~1.5 / 2.5 / 4.0 GiB, both arms, one seed.

| # | cell spec | cap | regime | why this rung |
|---|---|---|---|---|
| 1–2 | `{classic,mglru}:92:2.5:1729:hotset:0.20:0.80` | 2.5 GiB | band centre | Hot 1.0 GiB fits with ~1.5 GiB of headroom for cold-tail churn — the cleanest place for classic's refault-activation to stabilise the hot set while MGLRU keeps churning it. **The headline cell**; run first so the deadline can never shed it. |
| 3–4 | `{classic,mglru}:92:4:1729:hotset:0.20:0.80` | 4.0 GiB | band, upper edge | Exactly Tier-1c run 2's headline cap, so this is a **direct skew-vs-uniform contrast at a cap already measured** (uniform: MGLRU/classic 1.013–1.034, no asymmetry). Any divergence here is attributable to skew alone. |
| 5–6 | `{classic,mglru}:92:1.5:1729:hotset:0.20:0.80` | 1.5 GiB | band, lower edge | Tightest cap that still nominally clears the hot set. **Known risk:** 1.0 GiB hot set + the driver's own anon footprint is close to 1.5 GiB, so this may in practice land in S-capband's `cap < hot-set` regime (thrash both arms). If it does, that is itself a calibration readout — raise this rung to 2.0 GiB. |

Fields: `fracPct=92` (seeded pass-1 residency, an 8% ≈ 0.4 GiB deficit) and
`seed=1729` are carried from Tier-1c unchanged so the only moved variable is
skew. `PASSES=12`, `CELL_TIMEOUT=1800 s` (§4: Tier-1c's 900 s truncated capped
cells before a steady floor was written — a converging Tier-1d cell must have
time to *write its JSON*). Window `WINDOW_DEADLINE_S=5400 s` ⇒ the ~90 min §4
window. Six cells against that deadline is deliberately more than will
certainly fit: cells are shed in order from the end, so the ordering above is
the priority order.

If the window sheds mid-pair (one arm of a rung ran, the other did not),
**re-run the same command later** — the orchestrator's any-date SKIP sees the
existing JSON and completes only the missing arm.

Skew tail syntax is `arm:fracPct:capGiB:seed:hotset:0.20:0.80`; everything after
the seed is passed verbatim to the driver as `--skew hotset:0.20:0.80`.

## T1d-7. What to read out, and the ONE adjustment §4 allows

Record for each cell (source: the per-cell JSON under `data/eval_results/`):

- per-pass **majflt** trajectory and the **steady floor** it settles to;
- the **MGLRU/classic floor ratio** at each cap (Tier-1c's uniform baseline was
  1.013–1.034 with a ±16% noise floor — that is the number skew has to beat);
- whether the cell **finished inside `CELL_TIMEOUT` with a written JSON** (§4
  names this as an explicit purpose of the window);
- **measured hot-set residency** under each cap — this is what actually places
  the critical cap, versus the arithmetic estimate above;
- the **skew histogram check** (§6 gap 1): the realised draw matches `h/m` to
  tolerance;
- the runlog's `RESTORED: lru_gen=…` line — it must read `0x0007`.

§4 pre-authorizes adjusting the rungs **once**, and nothing else: move the
critical cap within **[1.5, 4.5] GiB**; change `h` within
**{0.05, 0.10, 0.20, 0.40}** (§3.2's sweep values); raise `CELL_TIMEOUT` if a
converging cell was truncated. Report every tuned value **as tuned**, and move
pre-tune cells to `data/eval_results/tuning_history/` before re-running so they
are not overwritten (the Tier-1b convention above). Then record the outcome in
§4 of the pre-reg. **§5 bars are frozen in their own separate commit, after
that — never in the same breath as the calibration run.**

## T1d-8. Driver status (read before you are surprised by the log)

The skew driver **`t1d_cell.py` landed 2026-09-05 in commit `67a282fd`** (§6 gap
1) — it takes `--skew hotset:h:m` or `--skew zipf:s` and stamps
`"protocol": "tier1d"`, which is what the matrices above expect. The
orchestrator selects it automatically when present, and **falls back to
`t1c_cell.py` in smoke-test mode** when it is absent — which now means only one
thing: **your checkout predates `67a282fd`.** The fallback prints:

```
NOTICE: t1d_cell.py absent — smoke-test mode with t1c_cell.py (protocol tier1c, no skew cells)
```

In that mode the protocol stamp is `tier1c`, the WSL2 window machinery can be
exercised end-to-end with uniform-access cells, and **any cell spec carrying a
skew tail is a hard CONFIG ERROR (exit 2)** — so the matrices above simply will
not run. If you see that NOTICE, `git pull` (you are behind `67a282fd`); do not
strip the skew tails to make it run, because a uniform-access matrix is
Tier-1c, which has already been answered (negative).

## T1d-9. Afterwards — commit from the distro checkout

```bash
cd /mnt/c/Users/<user>/claudebox-projects/sfu-library-thinclient
git pull --rebase
git add data/eval_results/t1d_*_20260905.json      # explicit list — NEVER git add . / -A
git commit -m "Tier-1d SEC-4 calibration window 20260905 (WSL2 local): raw cells"
git push
```

Then report back in the dev-container session: the per-cell floors, the
MGLRU/classic ratios, and any rung adjustment taken. The §4 record in
`PREREGISTRATION_TIER1D.md`, the RESULTS.md Tier-1d section, and the §5 freeze
are written by the session lead in the dev container, not here.

## T1d-10. The JUDGED window — bars FROZEN at `5f55fb32` (2026-09-05)

The calibration (T1d-6) is done and recorded; this is the matrix the frozen
§5 bars are judged from. Same launch mechanics as T1d-5, same window
discipline, `CELL_TIMEOUT=1800 s`, `WINDOW_DEADLINE_S=5400 s`. **Pull first
and confirm the pull reaches `b3a9377a` or later** — the driver now prints
`hot_resident NN.NN%` on every skew pass; if the runlog lacks that token the
checkout is stale and the window's JSONs will be missing a frozen readout.
**Seeds 2027 and 8128 ONLY** — 1729 is calibration-burned and cannot satisfy
a bar. Shed-priority order:

| # | cell spec | judges |
|---|---|---|
| 1–4 | `{classic,mglru}:92:1.5:{2027,8128}:hotset:0.20:0.80` | T1d-1 + T1d-1b, both replicates |
| 5–6 | `{classic,mglru}:92:8:2027:hotset:0.20:0.80` under `STRICT_SOUNDNESS=1` | T1d-3 control + T1d-5 validity gate |
| 7–8 | `{classic,mglru}:92:4:2027:hotset:0.20:0.80` | T1d-3 upper band |
| 9+ | if time remains: `{classic,mglru}:92:1.5:2027:hotset:{0.05,0.10,0.40}:0.80` (T1d-2 sweep), `{classic,mglru}:92:0.75:2027:hotset:0.20:0.80` (sub-hot-set), the 1.5 GiB pair with `--fault-around`, `classic:70:1.5:2027:hotset:0.20:0.80` (S-inversion companion to cell 1) | recorded, not pass/fail |

Cells 1–8 are the verdict set; a window that sheds any of 1–8 completes them
in a resume window (any-date SKIP) before anything is judged. Afterwards:
commit per T1d-9 (explicit file list), report back, and the session lead
judges against `PREREGISTRATION_TIER1D.md` §5 and writes the RESULTS.md
Tier-1d section. `.wslconfig` still carries the experiment profile from the
calibration window, so no hygiene reboot is needed unless dmesg shows the
boot is stale (T1d-3's gate).

> **T1d-10 STATUS: RUN AND JUDGED 2026-09-05** — all 8 verdict cells
> completed (evidence `47f0a7c3`), verdicts recorded (`95409c11`):
> T1d-1/1b/3 PASS, T1d-5 valid. The next window is **T1d-11**.

## T1d-11. CHARACTERIZATION windows — the recorded-only cells 9+ (no verdicts)

> **T1d-11/13/14/15/16 STATUS: RUN 2026-09-05/06, READOUTS RECORDED** —
> evidence `226adecc` (20/26 cells; all six fa cells shed rc=124 — that is
> the S-faultaround readout), CHAR report
> `data/eval_results/_t1d_CHAR_report_20260905.md`, session-lead readouts
> RESULTS.md §26–29.
> **T1d-12/17 STATUS: RUN 2026-09-06, READOUTS RECORDED, LINE SETTLED** —
> evidence `00a528ea` (8/10 cells; the fa:hotsetc pair shed rc=124, making
> fa sheds 8-for-8), CHAR report
> `data/eval_results/_t1d_CHAR_report_20260906.md`, readouts RESULTS.md
> §30–31. **No window remains queued in the Tier-1d line.** Pending host
> follow-up: `.wslconfig` revert 56 GB → 32 GB (user timing).

Every cell here is **recorded-only under the frozen §5** — nothing below can
change a T1d verdict; the outputs feed the three open characterization gaps
(synthetic inversion, the 1.44×→220× amplification chain, the skew
threshold). Same mechanics as T1d-10 (`CELL_TIMEOUT=1800 s`,
`WINDOW_DEADLINE_S=5400 s`, seed 2027, keep-alive client, containers left
running, no reboot unless the boot is stale). **Pull first — the checkout
must reach `bcea5928`** (the orchestrator's `fa:` tail; an older checkout
hard-errors on the fault-around specs below with CONFIG ERROR, or worse,
runs them without `--fault-around` — the freshness token is the
`fault-around=ON` phrase in the cell-start runlog line). **No
`STRICT_SOUNDNESS` anywhere in T1d-11** (the fa cells would be
mis-quarantined; the orchestrator now refuses that combination).

Priority order (shed from the end; ~11 cells ≈ 3 h ⇒ plan 2–3 sequential
windows; stopping after any priority tier is fine — say so in the report):

| pri | cell spec(s) | gap it feeds | notes |
|---|---|---|---|
| 1 | `classic:70:1.5:2027:hotset:0.20:0.80` | **S-inversion (T1d-4)** | pairs with the judged `classic:92:1.5:2027` cell; the readout is the fixed pass-3 comparison of the two trajectories |
| 2 | `{classic,mglru}:92:1.5:2027:fa:hotset:0.20:0.80` | **S-faultaround (§3.4)** | initial state is cap-determined, not seeded (§6 gap 2) — expect `resident ~100%` after seed and identity n/a; judged on the steady floor only |
| 3 | `{classic,mglru}:92:1.5:2027:hotset:0.10:0.80` | **T1d-2 sweep** | h=0.10 first — hot set 0.5 GiB, the nearest bracket to the threshold question |
| 4 | `{classic,mglru}:92:1.5:2027:hotset:0.05:0.80` | T1d-2 sweep | |
| 5 | `{classic,mglru}:92:1.5:2027:hotset:0.40:0.80` | T1d-2 sweep | hot set 2 GiB > cap ⇒ expect both-arm thrash (an S-capband data point too) |
| 6 | `{classic,mglru}:92:0.75:2027:hotset:0.20:0.80` | sub-hot-set regime | cap < hot set; may run hot against `CELL_TIMEOUT` — if a cell times out, record the shed and do NOT retry with a raised timeout (that is a §4-class change) |

Afterwards: commit per T1d-9 (explicit list), leave
`_t1d_CHAR_report_<YYYYMMDD>.md` next to the results (floors, ratios,
trajectories, hot_resident, walls, deviations — same shape as the judged
report), report back. The session lead records the readouts in RESULTS.md;
no bars are involved.

A **second characterization window** (clustered-hot-set arm, feeding the
amplification chain) is queued as **T1d-12** below — runnable back-to-back
with T1d-11 in the same host session if the box is free.

## T1d-12. CHARACTERIZATION window — clustered hot set × readahead (recorded-only)

The amplification-chain 2×2: hot-set LAYOUT (scattered vs clustered) ×
READAHEAD (MADV_RANDOM vs fault-around). Two of the four corners already
exist — scattered/random is the judged T1d-10 pair, scattered/readahead is
T1d-11 priority 2 — so this window runs the two clustered corners. **Pull
must reach `7bc29b30`** (driver kind `hotsetc`; freshness token: the runlog
prints `hot layout CLUSTERED: 8 extents @…` after the skew line). Same
mechanics and conditions as T1d-11; recorded-only, no verdicts, no
`STRICT_SOUNDNESS`.

| pri | cell spec(s) | corner |
|---|---|---|
| 1 | `{classic,mglru}:92:1.5:2027:hotsetc:0.20:0.80` | clustered / no readahead — pure layout effect in reclaim |
| 2 | `{classic,mglru}:92:1.5:2027:fa:hotsetc:0.20:0.80` | clustered / readahead — the compounding cell, the arm the real stack most resembles |

Four cells ≈ 60–80 min, one window. Readout: the four-corner floor/ratio
table (does clustering alone move the 1.44×? does clustering+readahead
compound it toward the real stack's ~220× direction?). Report into the same
`_t1d_CHAR_report_<YYYYMMDD>.md` as T1d-11 (or its own if run separately);
commit per T1d-9.

## T1d-13. CHARACTERIZATION cells — the inversion, cap-pair form (recorded-only)

Why: the T1d-11 priority-1 cell measured that the drafted S-inversion
manipulation is **inoperative under a sub-|R| cap** — frac92 and frac70 both
seed to the same cap-determined ~28% residency (seed deficits 936,651 vs
935,800; trajectories identical within noise). The initial state cannot be
chosen by the seed when the cap binds, exactly as §6 gap 2 found for
fault-around. The real-stack inversion (B3) was never deficit-vs-deficit —
it was **cap-vs-cap inside the band where both caps reach the same steady
state** (26 vs 28 GB), with the sort scheduled earlier at the tighter cap.
The synthetic analog samples the unexplored band around the two-population
working set (R 5 GiB + L 1.75 GiB ≈ 6.75 GiB + driver anon):

| pri | cell spec(s) | purpose |
|---|---|---|
| 1 | `classic:92:6.5:2027:hotset:0.20:0.80` | just-below-footprint rung |
| 2 | `classic:92:7.5:2027:hotset:0.20:0.80` | just-above-footprint rung |
| 3 | `classic:92:7:2027:hotset:0.20:0.80` | midpoint, if time allows |

Readout: fixed pass-2/pass-3 majflt + wall comparison across the pair — does
the tighter cap converge faster at the fixed window (the B3 signature)?
Expect fast cells (the 8 GiB cells ran ~3.5 min). Classic arm only —
recorded-only, appendable to the end of any T1d-11/12 window without
re-planning; checkout needs nothing newer than T1d-11's `8ec9a314`.

## T1d-14. CHARACTERIZATION cells — fault-around retry, cold-start form (recorded-only)

Why: T1d-11 priority 2 (the fa pair at frac92/1.5 G) timed out at
`CELL_TIMEOUT=1800 s` **inside the seeding loop** — both cells logged the
MADV_NORMAL mapping line and then nothing: warming 92% of R page-by-page
*through readahead* under a 1.5 GiB cap thrashes before pass 1 exists.
Correctly recorded as shed, not retried with a raised timeout. The §6 gap-2
finding already says a fault-around cell's initial state is cap-determined,
not seeded — so the seed loop is pure waste for fa cells and the honest form
is a **cold start**: `fracPct=0` warms nothing (the driver skips the touch
loop entirely) and pass 1 begins from the cap-determined cold state.

| pri | cell spec(s) | notes |
|---|---|---|
| 1 | `{classic,mglru}:0:1.5:2027:fa:hotset:0.20:0.80` | the S-faultaround pair, cold-start form |
| 2 | `{classic,mglru}:0:2.5:2027:fa:hotset:0.20:0.80` | fallback rung ONLY if pri 1 times out again — looser cap, milder thrash |

If a cell still cannot finish 12 passes in 1800 s, record the shed (no
raised timeout — §4-class change) — and note that the per-pass lines in the
cell `.log` ARE evidence for a recorded-only readout even when rc=124 leaves
no JSON: report whatever passes were logged. No STRICT anywhere (the
orchestrator refuses fa+STRICT). Checkout: needs `bcea5928`+ (already
satisfied by any T1d-11 checkout).

## T1d-15. CHARACTERIZATION cells — the inversion WITH a residue (recorded-only)

Why: T1d-13's three cap-bracket cells came back **bit-identical to each
other and to the 8 GiB control** — at any cap > |R| the synthetic has no
transient at all, because L is laid down cold and never touched: there is
**no residue population to sort out**, and the real inversion (B3) IS
residue sorting (RESULTS.md §22: a no-residue load kills the artifact at
every cap — every synthetic cell so far has unknowingly been the no-residue
form). The driver now has `--warm-l` (commit `403f6503`): all of L touched
before R is seeded, mapping kept alive — a 1.75 GiB load-time residue the
cap must evict while R re-converges, with per-pass `l_resident_pct`
recording the sort. Orchestrator tail token `wl:` (commit `da51bd40`;
freshness token: `warm-l=ON` in the cell-start line, and an
`L warmed as residue:` line in the cell log). **Pull to `da51bd40`+ before
this window.**

R 5 GiB + L 1.75 GiB = 6.75 GiB total demand; the ladder places caps so the
residue must be partially or wholly displaced while R (deficit 0.4 GiB)
converges:

| pri | cell spec(s) | pressure on the residue |
|---|---|---|
| 1 | `classic:92:6.5:2027:wl:hotset:0.20:0.80` and `classic:92:5.5:2027:wl:hotset:0.20:0.80` | the B3-analog pair: ~0.25 GiB vs ~1.25 GiB of demand over cap — fixed pass-2/3 window compares them |
| 2 | `classic:92:6:2027:wl:hotset:0.20:0.80` | midpoint rung |
| 3 | `mglru:92:6.5:2027:wl:hotset:0.20:0.80` and `mglru:92:5.5:2027:wl:hotset:0.20:0.80` | the arm contrast on residue sorting — §22 says MGLRU never demotes the residue |
| 4 | `classic:92:8:2027:wl:hotset:0.20:0.80` | uncapped-equivalent control (everything fits; should replicate the non-wl 8 GiB trajectory) |

Six cells, expect minutes each at these loose caps (T1d-13 ran ~3.5 min) —
though the 5.5 GiB rungs carry real pressure and may run longer. One window.
Readout: fixed pass-2/pass-3 majflt + wall across the priority-1 pair (the
inversion question: does the TIGHTER cap sort the residue earlier and look
better at the fixed window?), plus the `l_resident_pct` trajectories (the
sort photographed) and the classic-vs-mglru residue contrast. Recorded-only,
no STRICT, report into the CHAR report; commit per T1d-9.

## T1d-16. CHARACTERIZATION cells — MGLRU's own knob: `min_ttl_ms` (recorded-only)

Why: MGLRU ships a documented anti-thrash knob this project has never
touched — `/sys/kernel/mm/lru_gen/min_ttl_ms` guarantees each generation a
minimum lifetime before eviction. The question: is stock MGLRU rescuable
**by configuration alone** at the divergence rung, before anyone reaches for
kernel patches? The min_ttl=0 baseline already exists (the judged
`mglru:92:1.5:2027` cell, floor 482,884).

Mechanics: `MIN_TTL_MS` is a **window-level env** on the orchestrator
(commit `6b6b2ae8` — sysfs is VM-global, so one value per window; labels
gain `_ttl<ms>`; boot value restored in the trap and echoed in the RESTORED
line). **Pull to `6b6b2ae8`+.** Two mini-windows, one cell each:

| # | window env | cell spec | expected wall |
|---|---|---|---|
| 1 | `MIN_TTL_MS=1000` | `mglru:92:1.5:2027:hotset:0.20:0.80` | ~20 min |
| 2 | `MIN_TTL_MS=4000` | `mglru:92:1.5:2027:hotset:0.20:0.80` | ~20 min |

~45–50 min total with window overhead. **Run tonight ONLY if it fits the
remaining budget after W6** (user's 3-hour guidance); otherwise it queues
with T1d-12 for the next session — say which in the report. Readout: floor
vs the 482,884 baseline and vs classic's 334,678 (does min_ttl pull the
mglru floor down toward classic — ratio toward ≤1.16 — or does protecting
young generations at a bound cap backfire the way mlock pinning did?), plus
the `hot_resident_pct` trajectory (does the 75.0% pin lift?). Recorded-only,
no STRICT.

## T1d-17. CHARACTERIZATION cells — the inversion, COLD-START residue form (recorded-only)

Why: T1d-15's residue form came back negative, and RESULTS.md §27 records
the mechanism: the direct seed (`frac92`) displaces the residue
**synchronously during setup**, so the sort is finished before pass 1 and
its cost never lands inside the measured window. The real B3 arrangement is
the opposite — identical initial state at every cap, with the sort
scheduled by pressure *inside* the fixed window (§22). The synthetic analog
of that arrangement is already expressible with the current driver and
orchestrator, **no code changes**: `frac0` (R laid down cold, T1d-14's
cold-start form) combined with `wl:` (L warmed to 100% as residue,
T1d-15's flag). Pass 1 then loads R via the skewed draw while the cap
forces L's displacement concurrently — the sort happens in-window and its
timing is pressure-proportional, which is the ingredient every prior form
lacked. Checkout needs nothing newer than `da51bd40` (already present).

Same mechanics as T1d-15 (no STRICT — frac0 identity is trivially the full
deficit but the fa-style caution costs nothing; `MADV_RANDOM` throughout,
i.e. NOT the fa form — readahead stays off so walls stay bounded). R 5 GiB
cold + L 1.75 GiB warm; same cap ladder as T1d-15:

| pri | cell spec(s) | question |
|---|---|---|
| 1 | `classic:0:6.5:2027:wl:hotset:0.20:0.80` and `classic:0:5.5:2027:wl:hotset:0.20:0.80` | the B3-analog pair, corrected form: fixed pass-2/pass-3 majflt + wall — does the TIGHTER cap now look better at the fixed window? |
| 2 | `classic:0:8:2027:wl:hotset:0.20:0.80` | control: everything fits, no displacement — the no-pressure trajectory the pair is read against |
| 3 | `classic:0:6:2027:wl:hotset:0.20:0.80` | midpoint rung |
| 4 | `{mglru}:0:6.5:2027:wl:...` and `{mglru}:0:5.5:2027:wl:...` | arm contrast on in-window residue sorting (does MGLRU's missing refault-activation finally bite on the residue?) |

Six cells; pass-1 walls will exceed T1d-15's (a full 5 GiB cold load per
cell) but nothing here needs a raised CELL_TIMEOUT at these loose caps
(*est.* — if a cell sheds at 1800 s, record the shed, do not retry with a
raised timeout). Readout: the pri-1 fixed-window comparison (the inversion
itself), `l_resident_pct` per pass (is displacement now spread across
passes rather than complete at pass 1 — the §27 signature reversed?), and
`hot_resident_pct`. Recorded-only, no verdicts; report into a CHAR report;
commit per T1d-9. If the inversion appears, judging it as a verdict — and
any standalone small-scale demo derived from it — requires a fresh
pre-registration first (Tier-1e).
