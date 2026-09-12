# Tier-1d CHARACTERIZATION windows — 2026-09-06 — evidence report from host-ops session

For the session lead (dev container). **Everything here is recorded-only under
the frozen §5 — no verdicts, nothing below can change a T1d bar.** Matrices per
HOST_RUN.md **T1d-17** (all six cells) and **T1d-12** (all four cells). Seed
2027 only. These were the last two queued windows of the Tier-1d line.

**Bottom line: 8 of 10 attempted cells completed with full JSONs; the 2 sheds
are the fa:hotsetc pair, both rc=124 at exactly CELL_TIMEOUT=1800 s inside the
seeding loop — the same uniform S-faultaround signature as all six 20260905 fa
sheds, now extended to the clustered layout. T1d-17's answer is a clean
negative with the mechanism photographed: the residue sort now happens
in-window and is pressure-proportional (the §27 signature reversed, as
designed), but reclaim victimizes L exclusively — R's majflt trajectory is
bit-identical across all four caps and BOTH arms, so no inversion appears at
the fixed window. T1d-12's answer: clustering alone moves nothing — the
four-corner ratio is 1.443 (scattered, judged) vs 1.443 (clustered).**

## Checkout / tree-state record

- W1 (T1d-17) launched from `0ac5f482` (T1d-17 prereq `da51bd40` and T1d-12
  prereq `7bc29b30` both ancestors; worktree clean apart from the untracked
  `_t1d_ALLDONE_20260906` marker).
- `df648676` (E8 `--hotset-switch-pass` in t1d_cell.py, additive) landed on
  the shared tree at 12:16:23 local — 8 min into W1 — so W1 cells 1–2 ran the
  pre-edit driver and cells 3–6 the post-edit one; container-side verification
  (reported before W2 launch) found the edit byte-identical-inert on all 10
  queued cell shapes apart from wall_s. W2 (T1d-12) ran wholly from the
  committed `df648676` state per the container session's instruction; no
  uncommitted driver edits present at either launch.
- Freshness tokens all verified: `warm-l=ON` on all six W1 cell-start lines
  plus `L warmed as residue: 458752/458752 pages resident (100.0000%)` in the
  wl cell logs; `hot layout CLUSTERED: 8 extents @…` in the hotsetc cell logs;
  `fault-around=ON` on both fa cell-start lines.

## Window structure (both `systemd-run` unit t1d-orch, CELL_TIMEOUT=1800 s, WINDOW_DEADLINE_S=5400 s, no STRICT anywhere)

| window | when | cells | outcome |
|---|---|---|---|
| W1 (T1d-17) | 12:08:41–12:34:46 | classic:0:{6.5,5.5,8,6}:wl + mglru:0:{6.5,5.5}:wl | 6/6 DONE, no shed (walls 255–276 s/cell) |
| W2 (T1d-12) | 12:36:02–14:09:44 | {classic,mglru}:92:1.5:hotsetc, then {classic,mglru}:92:1.5:fa:hotsetc | 2 DONE + 2 FAIL rc=124 |

Both windows ended `RESTORED: lru_gen=0x0007 ... (exit rc=0)`; boot
`lru_gen=0x0007` throughout, same hygiene-profile boot (56 GB fixed,
pageReporting=false, kernel 6.18.33.2+). Containers left running per T1d-11
mechanics. Runlog: `_t1d_runWSL2_20260906.log`. NB the earlier entries in the
same runlog (00:00–00:19) are the 20260905 night's W7b (min_ttl 4000), already
committed in `226adecc`.

## T1d-17 — the inversion, cold-start residue form: NEGATIVE, mechanism recorded

All six cells share **bit-identical majflt trajectories** (and walls identical
within noise) — across caps 5.5/6/6.5/8 GiB and across BOTH arms:

```
pass:    1       2       3       4      5      6      7      8      9      10     11     12
majflt:  488890  185803  140584  109937 85255  66498  51716  40144  31411  24512  19104  14938
wall_s:  ~77     ~29     ~22     ~18    ~14    ~11    ~8     ~7     ~5     ~4     ~3     ~2.4
```

(Fixed-window comparison, the pri-1 question: pass-2 185,803 / pass-3 140,584
everywhere — the TIGHTER cap looks neither better nor worse; the trajectories
are indistinguishable to the last fault. No steady floor is reached by pass 12;
the frac0 draw is still faulting its cold tail, declining ~0.78×/pass.)

Meanwhile `l_resident_pct` shows the sort DID move in-window and IS
pressure-proportional — the §27 complaint (sort finished before pass 1) is
fixed by construction and observably so:

| cap | L residue trajectory (pass 1 → 12) | end state |
|---|---|---|
| 8G (control) | 100% flat | 100.0% |
| 6.5G | 100% through p9, then 98.1 → 93.9 → 90.7 | 90.7% |
| 6G | 100% through p6, then declines | 62.5% |
| 5.5G | 100% through p4, then declines steadily | 33.9% (classic) / 33.1% (mglru) |

`hot_resident_pct` hits 100% by pass 3 and stays there in every cell.

**Reading**: with R loaded cold through the skewed draw while the cap forces
L's displacement concurrently, reclaim (classic AND mglru) victimizes the
never-retouched L pages exclusively and never evicts R — so the displacement
has zero majflt/wall cost to R and the B3 fixed-window inversion signature
does not reproduce. The arm contrast on residue sorting is also null: the
l_resident trajectories match across arms to ~1 pp (mglru DOES demote the
residue here, unlike §22's real-stack observation). Per HOST_RUN.md T1d-17,
any further pursuit of the inversion needs a fresh pre-registration
(Tier-1e); nothing here is judged.

## T1d-12 — the amplification-chain four-corner table

Floors = mean majflt of last 3 of 12 passes, rung 1.5 GiB, frac92, seed 2027,
h=0.20 m=0.80:

| layout \ readahead | MADV_RANDOM | fault-around |
|---|---|---|
| scattered (judged T1d-10) | classic 334,678.3 / mglru 482,884.0 → **1.443** | SHED (both arms, 20260905) |
| clustered (this window) | classic 334,788.3 / mglru 482,963.0 → **1.443** | SHED (both arms, rc=124 at 1800 s) |

- Clustered floors replicate the scattered floors to **0.03%** in both arms;
  fixed-pass values match too (classic pass-2/3: 478,044/440,798 clustered vs
  478,763/440,815 scattered). End-state hot residency likewise (classic ~90%,
  mglru pinned at 75.0%). **Clustering alone moves the 1.44× not at all** —
  reclaim on this kernel is layout-blind at this rung under MADV_RANDOM.
- The compounding corner (clustered+readahead, the arm the real stack most
  resembles) is **unmeasurable in this harness at this rung**: both cells died
  in the seeding loop after the `R mapped with MADV_NORMAL (fault-around ON)`
  line with zero per-pass lines logged — the identical signature as all six
  20260905 fa sheds (scattered frac92, cold-start 1.5G, cold-start 2.5G). Per
  the standing rule the sheds are recorded, not retried with a raised timeout.
  Eight-for-eight uniform fa sheds across layouts, frac forms, and caps up to
  2.5G is itself the S-faultaround readout: readahead under a binding cap
  thrashes before the measurement can begin, dominating any layout effect.

## Deviations

None. No cell was retried; no timeout raised; no STRICT anywhere; containers
untouched; both windows single-shot with all queued cells attempted. The
`_t1d_ALLDONE_20260906` marker is re-touched by each window's exit and was not
used as a done signal (systemd unit state was the authority).

## Files (this report's evidence set)

- 6× `t1d_{classic,mglru}_wl-hotset-0.20-0.80_frac0_cap{5.5,6,6.5,8}g_seed2027_20260906.json` (+ `.log`/`.status` each)
- 2× `t1d_{classic,mglru}_hotsetc-0.20-0.80_frac92_cap1.5g_seed2027_20260906.json` (+ `.log`/`.status` each)
- 2× `_t1d_{classic,mglru}_fa-hotsetc-0.20-0.80_frac92_cap1.5g_seed2027_20260906.{log,status}` (sheds — no JSON)
- `_t1d_runWSL2_20260906.log` (appended)
