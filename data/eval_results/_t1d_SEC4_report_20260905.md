# Tier-1d §4 calibration window — 2026-09-05 — report from host-ops session

For the session lead (was sfu-library-thinclient-9c [fee8c9] — that session died
when the hygiene reboot killed the devcontainer; report left here instead).
Commit: `9ac830a37d955ce0e56122ea6c3993d90c0be831` (local; push pending user).

## Step A — soundness/control gate (STRICT_SOUNDNESS=1, cap 8G): CLEAN

- Both arms: `soundness_pass1_majflt_eq_deficit: true` (identity kind
  `skew_reachable_deficit`, reachable deficit 39031 == pass-1 majflt).
- Trajectories bit-identical across arms (39031 → 1206 over 12 passes),
  `converged_first_pass: 10`, hot_touch_frac 0.7996 ≈ m.
- S-capband `cap > |R|` control point: MGLRU/classic ratio **1.000**.

## Step B — calibration matrix (seed 1729, hotset:0.20:0.80, frac92, 12 passes)

Steady floor = mean majflt of last 3 passes.

| cap | classic floor | mglru floor | ratio m/c | note |
|---|---|---|---|---|
| 2.5G (headline) | 222,994 | 263,316 | 1.181 | neither converged; classic floor noisy (last-6 range ~170k–270k) |
| 4.0G | 105,444 | 109,369 | 1.037 | inside Tier-1c uniform band 1.013–1.034 → no skew divergence at the already-measured cap; both arms plateau ~89–90k passes 3–10, then BOTH uptick to ~131–135k at pass 11/12 (possible late-window noise, see deviations) |
| 1.5G | 334,614 | 482,621 | **1.442** | the clear divergence: classic descends 521k → ~335k (refault-activation stabilising the hot set); mglru PINNED at ~483k from pass 2 (hot-set churn). Whole-R residency ~28% both arms. Max cell wall 890s < CELL_TIMEOUT 1800s → no thrash-timeout, rung stands |

Per-pass majflt trajectories:

- cap2.5g classic: 350012 216615 282583 273172 213699 257556 196497 174597 172382 170474 230370 268139
- cap2.5g mglru:   352328 218009 291975 272323 229239 306763 246574 258792 289756 243052 277906 268990
- cap4g   classic: 148159  92426  89524  88917  88639  89044  89182  89245  89234  88615  92819 134899
- cap4g   mglru:   150848  93459  90281  89647  90143  90249  90185  90622  90457  89856 107173 131077
- cap1.5g classic: 521660 479689 441403 343292 305676 351455 336287 327918 341071 333912 331998 337933
- cap1.5g mglru:   528327 490046 483465 483723 483807 483383 482844 482988 483831 482476 482794 482592

## Validity checklist

- All 12 arm toggles asserted (0x0000 / 0x0007 per arm in runlog); no RESIDUE,
  no ARM TOGGLE FAILED, no shed cells; `RESTORED: lru_gen=0x0007` on both
  windows, exit rc=0.
- Every cell wrote its JSON inside CELL_TIMEOUT (max wall 890s of 1800s).
- Skew draw matches h/m: hot_touch_frac 0.7996–0.8002 every pass; Step A
  histogram hot mean 4.00 touches/page vs cold 0.25.
- GAP for T1d-7 readout 4: the cell JSONs carry whole-R `resident_pct` but no
  per-hot-set residency field — "measured hot-set residency under each cap" is
  not directly extractable. Consider adding it to t1d_cell.py before §5 freezes.

## Deviations to record in §4

1. Hygiene gate: `.wslconfig` experiment profile applied (fixed memory=56GB,
   processors=8, pageReporting=false, kernel v6) + full `wsl --shutdown` +
   relaunch BEFORE the window. This killed the devcontainer session
   (unavoidable: the prior boot had `Free page reporting enabled` in dmesg, so
   no valid window existed without a reboot; user approved).
2. Even with pageReporting=false verifiably applied (VM size changed to 56GB),
   dmesg STILL prints `Free page reporting enabled` at boot. The file-based
   gate passes; whether this WSL build honours the key at the hv_balloon level
   is an open validity question for the pre-reg.
3. Noise: ALL claudebox containers (thinclient stack, sfu-library-mcp stack,
   pommels, nextdash, googlecal) left RUNNING during both windows, per
   instruction. The pass-11/12 uptick at cap4g (both arms) and the classic
   cap2.5g floor noise may reflect this.
4. Windows launched from the host-ops session via systemd-run in the Ubuntu
   distro, with a wsl.exe keep-alive client holding the distro. First Step A
   attempt died at t+15s to WSL distro idle-termination (runlog 13:07 —
   trap RESTORED cleanly; no artefacts).
5. `git push` / `git pull --rebase` are permission-blocked in the host-ops
   session: commit 9ac830a3 is LOCAL until the user pushes. The checkout was
   also not pulled pre-run (same block) — verified post-79cf8a04/67a282fd by
   content (ARM TOGGLE FAILED string, t1d_cell.py present).
6. `.wslconfig` still carries the experiment profile (inert until next boot)
   in case §4's one allowed adjustment needs a re-run; revert to the everyday
   32GB block is pending.

§4 recording, RESULTS.md, and the §5 freeze are the session lead's, per
HOST_RUN.md T1d-9 — nothing beyond raw cells + runlog was committed.
