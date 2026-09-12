# Pre-registration DRAFT — T1d-FG: does MGLRU-FG fix the isolated flaw?

**Date:** 2026-09-06 · **Status: DRAFT — awaiting the user's go on the kernel
build; bars NOT frozen; no cell may be graded against this doc yet.**

## 1. Why (the collision of two timelines)

Tier-1d proved, with frozen bars and fresh-seed replicates, that MGLRU's
missing refault re-promotion costs 1.443× in steady major-fault floor under
skewed access at `hot-set < cap < |R|`
(`RESULTS.md` §23–25; mechanism photographed: classic's hot set climbs
73%→90% resident, MGLRU's pins at 75.0%).

Independently, **MGLRU-FG** ("frequency-guided workingset promotion +
refault distance support", RFC by Kairui Song, Tencent, May 2026, targeting
mm-unstable — LWN: https://lwn.net/Articles/1070902/) proposes to give MGLRU
exactly the capability whose absence we measured: refault-distance-driven
re-activation of refaulting pages. Their motivating numbers (LevelDB +41%,
MongoDB YCSB +16.8%) are our workload's shape.

This spike evaluates the RFC against our isolated mechanism: **does the
1.443 collapse toward 1.0 under an FG kernel?** Either answer is a
contribution — a pre-registered independent validation (or refutation) of a
live kernel RFC, on the testbed that isolated the flaw it targets — and is
worth reporting to the upstream thread whichever way it falls.

## 2. What is tested (one question, three readouts)

Same driver, same orchestrator, same seeds, same cell specs as the judged
T1d window — the ONLY moved variable is the kernel's MGLRU implementation.

1. **The ratio:** FG-MGLRU/classic steady-floor ratio at cap 1.5 GiB,
   `hotset:0.20:0.80`, frac92, seeds 2027 and 8128 — vs the stock-kernel
   1.443/1.443.
2. **The mechanism readout:** per-pass `hot_resident_pct` — does FG's hot
   set climb like classic's (73→90%) instead of pinning at 75.0%?
3. **The control:** cap 8 GiB STRICT pair — identity must stay exact and
   the ratio 1.000 on the FG kernel too (an FG kernel that breaks the
   uncapped control invalidates the window, not the RFC).

## 3. Run matrix and time budget

| step | what | wall estimate |
|---|---|---|
| B1 | Obtain the RFC series (lore.kernel.org mbox for the MGLRU-FG posting), apply onto the box's custom WSL2 kernel tree, resolve rebase conflicts | 1–3 h (the big unknown — the RFC targets mm-unstable; our base is 6.18.x. If it does not apply with modest effort, STOP and record that as the result of step B1) |
| B2 | Build + install the FG kernel image for WSL2, `.wslconfig` kernel= swap, `wsl --shutdown` + boot check (`dmesg`, `lru_gen` present, min_ttl file present) | ~1 h (compile ~30–60 min on the box; the reboot KILLS all dev-container sessions — schedule like the calibration hygiene reboot, user-approved) |
| C1 | Step-A control: cap 8G STRICT pair, seed 2027 | ~15 min |
| C2 | The verdict-shaped matrix: `{classic,fg-mglru}:92:1.5:{2027,8128}:hotset:0.20:0.80` (4 cells) | ~80 min (judged-window walls: 914–1,192 s/cell) |
| C3 | Optional spot checks if the window allows: h=0.10 pair (~25 min); `MIN_TTL_MS` interaction cell (~20 min) | ~45 min |
| — | **Total measurement window (C1+C2)** | **~95 min — one standard window** |
| — | **Total including build** | **one evening, dominated by B1 risk** |

Labeling: FG cells must be distinguishable from stock-kernel cells — the
orchestrator run under the FG kernel gets `DATE=<date>fg` (or an equivalent
label suffix agreed before the window) so no filename ever collides with a
stock-kernel cell; the runlog records `uname -r` per window either way.

## 4. Decision-rule sketch (to be frozen in its own commit before the window)

Drafted intent, calibrated from the judged baselines:

- **FG-1 (fix confirmed):** ratio ≤ **1.16** (inside the ±16% noise band)
  in both replicates, with the control clean. Headline: the RFC eliminates
  the measured penalty.
- **FG-2 (partial):** 1.16 < ratio < 1.30 — improvement outside noise but
  a residual penalty; report the number.
- **FG-3 (no fix / regression):** ratio ≥ 1.30 (the stock-kernel bar) —
  the RFC does not address this regime; report upstream with trajectories.
- Mechanism readout (`hot_resident_pct`) is recorded, not gated.

## 5. Non-interference and provenance

- N-series discipline verbatim from Tier-1d (window lock, apt-guard, trap
  restore, containers policy stated in the report, no `data/seismic_150m/`).
- **Kernel provenance recorded in the report:** RFC mbox message-id + hash,
  base tree + commit, config diff from the current custom kernel, and
  `uname -r` of every window. The stock kernel image is kept installed for
  rollback; `.wslconfig` kernel= line reverted after the spike unless the
  user chooses otherwise.
- Patch application and kernel build are host-side ops (the code-work
  policy applies: an agent does the build mechanics; the session lead
  records everything).

## 6. Efficacy (per CLAUDE.md)

Cells → `data/eval_results/t1d_*fg*.json` (committed); verdicts + numbers +
absolute dates → a T1d-FG section of RESULTS.md; if FG-1 holds, the
`THIN_CLIENT_SWAP.md` kernel-LRU paragraph gains a dated note that the
penalty is fixed by a pending upstream RFC (with the LWN/lore link), in the
same push. Upstream report to the RFC thread drafted for the user's review
either way (the user decides whether/how to send it).
