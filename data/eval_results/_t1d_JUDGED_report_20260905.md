# Tier-1d JUDGED window — 2026-09-05 — evidence report from host-ops session

For the session lead (sfu-library-thinclient-5c [e9e46a], dev container).
**No bar is judged here** — this is the evidence package for judging against
`PREREGISTRATION_TIER1D.md` §5 (bars frozen at `5f55fb32`). Matrix per
HOST_RUN.md T1d-10, cells 1–8 (the verdict set). **All 8 completed, zero
shed, zero FAIL — no resume window is needed.**

Checkout at launch: `6e9e5612` (includes `b3a9377a`; freshness token
`hot_resident NN.NN%` confirmed printing on every pass of every skew cell).
Seeds 2027/8128 only; seed 1729 was not run.

## Window structure (structural deviation, pre-flagged in milestone ping 1)

`STRICT_SOUNDNESS=1` in `t1d_wsl2_orchestrator.sh` quarantines ANY cell whose
soundness identity is false and aborts the window — capped cells always fail
the identity (cap binds during seeding), so the 8 GiB pair cannot share a
window with capped cells. Cells 1–8 therefore ran as three sequential
`systemd-run` windows in T1d-10 shed-priority order (same split as the
calibration's Step A/Step B):

- **W1** 15:11:47–16:22:12 — cells 1–4: `{classic,mglru}:92:1.5:{2027,8128}`, paired per seed
- **W2** 16:22:21–16:29:30 — cells 5–6: `{classic,mglru}:92:8:2027` under `STRICT_SOUNDNESS=1`
- **W3** 16:29:37–16:42:16 — cells 7–8: `{classic,mglru}:92:4:2027`

Each window: `CELL_TIMEOUT=1800 s`, `WINDOW_DEADLINE_S=5400 s`, 12 passes,
R=5120 MiB, L=1792 MiB, `hotset:0.20:0.80`, frac92, driver `t1d_cell.py`,
protocol `tier1d`, own laydown on ext4 (`/var/tmp/t1d_scratch`), boot
`lru_gen=0x0007`, all arm toggles asserted (no `ARM TOGGLE FAILED`, no
RESIDUE).

**RESTORED lines (runlog `_t1d_runWSL2_20260905.log`), one per window:**

```
[16:22:12] RESTORED: lru_gen=0x0007 apt-timers=[ apt-daily.timer apt-daily-upgrade.timer] scratch-removed (exit rc=0)
[16:29:30] RESTORED: lru_gen=0x0007 apt-timers=[ apt-daily.timer apt-daily-upgrade.timer] scratch-removed (exit rc=0)
[16:42:16] RESTORED: lru_gen=0x0007 apt-timers=[ apt-daily.timer apt-daily-upgrade.timer] scratch-removed (exit rc=0)
```

Live `/sys/kernel/mm/lru_gen/enabled` re-checked after W3: `0x0007`.

## Steady floors and ratios (floor = mean majflt of last 3 of 12 passes)

| cap | seed | classic floor | mglru floor | MGLRU/classic |
|---|---|---|---|---|
| 1.5 GiB | 2027 | 334,678.3 | 482,884.0 | **1.443** |
| 1.5 GiB | 8128 | 334,867.7 | 483,203.7 | **1.443** |
| 8 GiB (control) | 2027 | 1,581.3 | 1,581.3 | **1.000** |
| 4 GiB | 2027 | 105,628.3 | 109,591.0 | **1.038** |

Reference points, not judgments: calibration (seed 1729) measured 1.442 /
1.000 / 1.037 at the same rungs; `near_zero = 2500`; both 8 GiB floors are
1,581.3.

## Per-pass majflt trajectories (passes 1–12)

```
cap1.5g seed2027 classic: 520835 478763 440815 342616 305094 350614 337745 329266 338350 333742 334073 336220
cap1.5g seed2027 mglru:   527367 489212 483543 484190 482549 483003 483920 482918 483408 482965 482915 482772
cap1.5g seed8128 classic: 519992 476776 441877 342713 306490 349633 335218 328781 340499 335635 333367 335601
cap1.5g seed8128 mglru:   527489 486917 484053 483428 484285 482573 481765 483841 483685 484166 482605 482840
cap8g   seed2027 classic:  39160  14859  11085   8758   6810   5397   4091   3239   2520   2042   1539   1163
cap8g   seed2027 mglru:    39160  14859  11085   8758   6810   5397   4091   3239   2520   2042   1539   1163
cap4g   seed2027 classic: 148047  91585  88724  89203  88947  89176  88977  88696  89342  88777  93650 134458
cap4g   seed2027 mglru:   150347  93097  90305  90879  90561  89995  90327  89780  90455  90399 105355 133019
```

The two 8 GiB trajectories are bit-identical across arms (as in calibration).

## Per-pass hot_resident_pct at the 1.5 GiB cells (T1d-7 readout 4, first capture)

```
seed2027 classic: 72.83 76.31 83.04 95.04 88.33 88.18 89.86 91.01 89.66 88.64 90.38 89.88   (after-seed 28.60)
seed2027 mglru:   72.02 74.35 74.81 74.97 75.06 75.06 74.95 75.04 74.91 74.98 74.98 75.00   (after-seed 28.28)
seed8128 classic: 72.89 76.25 83.06 95.07 87.69 86.32 90.75 88.44 88.91 88.90 89.88 89.80   (after-seed 28.50)
seed8128 mglru:   72.00 74.28 74.67 74.80 74.97 75.08 74.91 75.00 75.11 74.99 75.04 74.97   (after-seed 28.18)
```

Shape: classic's hot-set residency climbs from ~73% toward ~90% (transient
peak ~95% at pass 4, coinciding with the majflt minimum at pass 5); MGLRU's
pins at ~75.0% from pass 2 onward, flat to the end. For completeness: at
4 GiB both arms sit ~98.3% (after-seed ~78.4%); at 8 GiB 100% from pass 2
(after-seed 92.05%).

## STRICT_SOUNDNESS outcome on the 8 GiB pair (cells 5–6)

Both cells passed the strict gate — neither was quarantined, window exit
rc=0. Both arms: `soundness_pass1_majflt_eq_deficit: true` (identity kind
reachable; `pass1_reachable_deficit_pages` 39,160 == pass-1 majflt 39,160),
`converged_first_pass: 10`, steady floor 1,581.3, trajectories bit-identical
across arms. (`soundness_pass1_majflt_eq_full_deficit: false` as expected
for a skewed draw — the reachable form is the T1d-5 form.)

## Wall times vs CELL_TIMEOUT=1800 s (runlog start→DONE; in-pass sum in parens)

| cell | wall | sum of pass walls |
|---|---|---|
| classic 1.5g 2027 | 927 s | 724 s |
| mglru 1.5g 2027 | 1,192 s | 993 s |
| classic 1.5g 8128 | 914 s | 722 s |
| mglru 1.5g 8128 | 1,171 s | 972 s |
| classic 8g 2027 | 208 s | 17 s |
| mglru 8g 2027 | 201 s | 16 s |
| classic 4g 2027 | 372 s | 180 s |
| mglru 4g 2027 | 369 s | 186 s |

No cell approached the timeout; every JSON was written. Every cell started
well inside its window's 5400 s deadline (last W1 cell at elapsed 3,053 s).

## Skew draw check

`hot_touch_frac` within 0.7994–0.8009 across all 96 passes of all 8 cells
(target m=0.80).

## Run conditions and deviations (EVERY one)

1. **Environment condition (pre-decided by session lead): ALL claudebox
   containers left RUNNING** (production included) for all three windows —
   identical to the calibration environment the bars were placed under.
2. **pageReporting standing caveat: still present this boot.** dmesg prints
   `Free page reporting enabled` at 0.415 s despite `pageReporting=false`
   verifiably applied (VM booted at 54 GiB total ⇒ `memory=56GB` was read).
   Per the §4 ruling this is a standing environment caveat, not an
   invalidation. **Arithmetic flag for the citation rule (no judgment):
   the 1.5 GiB judged values (1.443, both seeds) lie within ±16% of the
   T1d-1 threshold 1.30 (1.443/1.30 = 1.11), so a verdict on T1d-1 must
   cite the caveat.** The 8 GiB (1.000 vs band [0.84, 1.16] centre) and
   4 GiB (1.038 vs ≤1.20) values also sit within 16% of their bounds by
   simple arithmetic — the lead applies the rule as frozen.
3. **No hygiene reboot performed.** The running boot verifiably carries the
   experiment profile (54 GiB total memory ⇒ 56GB fixed was read; custom
   `+` kernel 6.18.33.2; `lru_gen=0x0007` clean at start). `uptime -s`
   reported 12:50:08, slightly earlier than the calibration notes' ~13:05
   reboot timestamp — treated as clock/rounding skew, since the profile
   values are only explainable by the post-profile boot. No container was
   stopped or restarted; `.wslconfig` untouched.
4. **Three-window split** for STRICT scoping (see above) — structural, not a
   protocol change; per-window deadlines were nowhere near binding.
5. **Cells 9+ (T1d-10 recorded-only extras) NOT run.** The verdict set alone
   consumed the ~90 min window budget (15:11–16:42). They remain available
   to a later window; none of them gates a bar.
6. **The 4 GiB pass-11/12 uptick recurred** in the same shape as calibration
   (classic 88,777 → 93,650 → 134,458; mglru 90,399 → 105,355 → 133,019;
   both arms, last two passes only, floors inflated accordingly). In
   calibration this was attributed to suspected container noise; an
   identical recurrence at a different time of day is worth the lead's
   attention when reading the 4 GiB floor (the last-3 floor definition
   includes these passes; passes 3–10 plateau at ~89k/~90k). Recorded, not
   interpreted.
7. **Checkout moved `aa29669a` → `6e9e5612` during preflight** (session
   lead landed `t1d_bar_inputs.py` in the shared working tree after my
   initial pull; delta is that one new file, harness untouched). Windows
   launched from `6e9e5612`.
8. Classic 1.5 GiB cells show a majflt minimum at pass 5 (~305–306k) before
   settling ~335k — same non-monotonic shape as calibration's classic cell.
   Recorded as trajectory shape, no bar attached.
9. First-cell keep-alive lesson applied: a `wsl.exe` keep-alive client held
   the distro for the whole session; no idle-termination recurred.
10. git: committed from the host checkout with an explicit file list per
    T1d-9. Push outcome from this session is stated in the milestone-4 ping
    (git pull worked in this session today; if push is blocked, the
    dev-container session pushes per T1d-9).

## Files in this evidence package

- 8 cell JSONs: `t1d_{classic,mglru}_hotset-0.20-0.80_frac92_cap{1.5g,8g,4g}_seed{2027,8128}_20260905.json` (1.5g × both seeds; 8g/4g × 2027)
- 16 per-cell `.log` / `.status` files (same stems, `_t1d_` prefix)
- runlog `_t1d_runWSL2_20260905.log` (appended below the calibration entries; contains all three window starts, every toggle assertion, the three RESTORED lines)
- this report
