# Tier-1d CHARACTERIZATION windows — 2026-09-05/06 — evidence report from host-ops session

For the session lead (dev container). **Everything here is recorded-only under
the frozen §5 — no verdicts, nothing below can change a T1d bar.** Matrices per
HOST_RUN.md **T1d-11** (priorities 1–6), **T1d-13**, **T1d-14** (pri 1 + the
pri-2 fallback, both triggered), **T1d-15**, and **T1d-16**. Seed 2027 only.
Outputs feed the three open gaps (synthetic inversion, amplification chain,
skew threshold) plus the two follow-on questions the night itself generated
(residue sorting, min_ttl rescue).

**Bottom line: 20 of 26 attempted cells completed with full JSONs; the 6
sheds are ALL fault-around cells, all rc=124 at exactly CELL_TIMEOUT=1800 s,
and that uniform failure is itself the S-faultaround readout.**

## Checkout / tree-state record

- Pulled to `8ec9a314` at preflight (T1d-11 requirement `bcea5928` verified in
  orchestrator source: `fa:` tail + fa+STRICT refusal).
- The shared /mnt/c tree's HEAD was moved by the dev-container side several
  times during the night (as in T1d-10): driver commit `7bc29b30` (hotsetc,
  additive-only, hotset path untouched — diff reviewed here) landed ~17:03,
  i.e. W1 executed from a `67bd9f`-era tree, not `8ec9a314`. Later
  between-window pulls reached `c3fe1ffd` (before W5), `4cb5afe9` (before W6),
  and the tree stood at `c8f9b137` when the T1d-16 windows ran. No harness
  file relevant to a running window changed mid-window; pulls were done only
  between windows with the runlog stashed around them.
- Freshness tokens all verified: `fault-around=ON` on every fa cell-start
  line; `warm-l=ON` on every wl cell-start line plus
  `L warmed as residue: 458752/458752 pages resident (100.0000%)` in the wl
  cell logs; `min_ttl_ms=<val> for this window (boot value 0, restored on
  exit)` + `RESTORED ... min_ttl_ms=0` on both T1d-16 windows.

## Window structure (all `systemd-run`, CELL_TIMEOUT=1800 s, WINDOW_DEADLINE_S=5400 s, no STRICT anywhere)

| window | unit | when | cells | outcome |
|---|---|---|---|---|
| W1 | t1d-char-w1 | 17:07:44–18:22:07 | T1d-11 pri 1 (frac70) + pri 2 (fa frac92 pair) | 1 DONE, 2 FAIL rc=124 |
| W2 | t1d-char-w2 | 18:24:08–19:08:17 | pri 3 (h=0.10 pair) + pri 4 (h=0.05 pair) | 4/4 DONE |
| W3 | t1d-char-w3 | 19:09:02–20:56:12 | pri 5 (h=0.40 pair) + pri 6 (0.75G pair) | 4/4 DONE (no shed) |
| W4 | t1d-char-w4 | 20:57:39–21:08:36 | T1d-13 (classic 6.5/7.5/7G) | 3/3 DONE |
| W5 | t1d-char-w5 | 21:09:40–22:09:58 | T1d-14 pri 1 (cold-start fa 1.5G pair) | 2 FAIL rc=124 |
| W5b | t1d-char-w5b | 22:11:39–23:11:57 | T1d-14 pri 2 fallback (cold-start fa 2.5G pair) | 2 FAIL rc=124 |
| W6 | t1d-char-w6 | 23:12:20–23:38:53 | T1d-15 (six wl: cells) | 6/6 DONE |
| W7a | t1d-char-w7a | 23:40:25–23:59:17 | T1d-16 MIN_TTL_MS=1000, mglru 1.5G | DONE |
| W7b | t1d-char-w7b | 00:00:16–00:19:30 (2026-09-06) | T1d-16 MIN_TTL_MS=4000, mglru 1.5G | DONE |

Every window ended `RESTORED: lru_gen=0x0007 ... (exit rc=0)`; the two T1d-16
windows additionally echo `min_ttl_ms=0` (boot value) in their RESTORED lines.
Runlogs: `_t1d_runWSL2_20260905.log` (W1–W7a, appended below the calibration
and judged entries) and `_t1d_runWSL2_20260906.log` (W7b — **date rolled over
mid-T1d-16**, so the ttl4000 files carry the 20260906 stamp).

## Steady floors and ratios (floor = mean majflt of last 3 of 12 passes)

Reference: judged baseline at this rung (T1d-10) classic 334,678.3 / mglru
482,884.0 → **1.443**; Tier-1c uniform noise floor ±16%.

### T1d-2 sweep + sub-hot-set (cap 1.5G unless noted, frac92, m=0.80)

| h (hot set) | cap | classic floor | mglru floor | MGLRU/classic |
|---|---|---|---|---|
| 0.05 (256 MiB) | 1.5G | 212,056.3 | 242,654.7 | **1.144** |
| 0.10 (512 MiB) | 1.5G | 220,041.0 | 310,562.7 | **1.411** |
| 0.20 (1 GiB) — judged ref | 1.5G | 334,678.3 | 482,884.0 | **1.443** |
| 0.40 (2 GiB > cap) | 1.5G | 678,079.0 | 765,387.3 | **1.129** |
| 0.20 (1 GiB > cap) | 0.75G | 747,213.0 | 834,555.0 | **1.117** |

The divergence is a **peaked curve**: it needs a hot set big enough to be
contested, small enough to fit. End-state hot residency tells the mechanism:
classic climbs to ~90–100% wherever the hot set fits (h≤0.20) while mglru
churns lower (h=0.10: classic ~90–100% vs mglru ~86–94%); when the hot set
exceeds the cap both arms sit at ~44–58% and the gap collapses.

### S-inversion companion (T1d-11 pri 1)

`classic:70:1.5:2027` floor **334,564.7** ≈ judged frac92's 334,678.3; seed
deficits 935,800 vs 936,651; trajectories identical within noise (fixed-pass
comparison: pass-2 478,374 vs 478,763; pass-3 441,690 vs 440,815). The
deficit-form manipulation is **inoperative under a binding cap** — both cells
seed to the same cap-determined ~28.6% residency. (This measurement triggered
T1d-13.)

### T1d-13 cap-pair inversion cells (classic only, no residue)

Caps 6.5 / 7 / 7.5 G: all three trajectories **bit-identical to each other and
to the judged 8G control** (39160 14859 11085 8758 6810 5397 4091 3239 2520
2042 1539 1163; floor 1,581.3; converged_first_pass 10; walls ~210–215 s). At
any cap > |R| the no-residue synthetic has no transient at all — the cap
never binds (seed deficit 104,858 everywhere, hot_after_seed 92.05%). No
cap-vs-cap comparison is possible without a residue. (This triggered T1d-15.)

### T1d-15 residue inversion (wl: cells — L warmed to 100% as residue before seeding)

| cell | majflt trajectory | floor | l_resident_pct pass1→pass12 |
|---|---|---|---|
| classic 5.5G wl | bit-identical to 8G control | 1,581.3 | 36.6 → 23.1 |
| classic 6G wl | bit-identical | 1,581.3 | 65.2 → 51.7 |
| classic 6.5G wl | bit-identical | 1,581.3 | 93.7 → 80.2 |
| classic 8G wl (control) | bit-identical | 1,581.3 | 100.0 → 100.0 |
| mglru 6.5G wl | bit-identical | 1,581.3 | 92.8 → 79.3 |
| mglru 5.5G wl | bit-identical | 1,581.3 | 35.7 → 22.2 |

**Negative on the inversion, cleanly:** R's fault behavior is completely
unaffected by the residue at every cap (identical majflt AND identical
per-pass walls, pass-2/3 comparison flat across the 5.5-vs-6.5 pair). The
residue *is* displaced — most of it during R's seed (pass-1 l_res% already at
the cap-determined level), then a slow monotonic decline — but the
displacement is costless to R. Arm contrast near-nil: mglru's l_res% runs
~0.9–1.0 points *below* classic at both caps (mglru demotes the residue
marginally MORE here, contra the §22 expectation).

### T1d-16 min_ttl_ms (mglru:92:1.5:2027, vs min_ttl=0 baseline 482,884.0)

| min_ttl_ms | floor | hot_resident_pct | verdict-free readout |
|---|---|---|---|
| 0 (judged baseline) | 482,884.0 | pinned ~75.0 | — |
| 1000 | 483,013.7 | pinned ~75.0 (71.97 pass 1 → 75.0) | **no effect** |
| 4000 | 483,021.7 | pinned ~75.0 (71.98 pass 1 → 75.0) | **no effect** |

Trajectories match the baseline pass-for-pass within noise (pass 1 ~527.3k,
settling ~483k). At this rung the knob neither rescues nor backfires — the
75.0% hot-residency pin is untouched. **Stock MGLRU is not rescuable by
min_ttl_ms configuration at the divergence rung.** Run under the user's
no-time-cap guidance, which superseded the run-book's "only if it fits the
3-hour budget" line.

## S-faultaround: the fa branch (T1d-11 pri 2 + T1d-14 pri 1 + fallback)

**All six fa cells failed rc=124 at exactly 1800 s with zero pass lines:**

| cell | form | log evidence |
|---|---|---|
| classic/mglru fa frac92 1.5G | seeded | 2-line logs: banner + "R mapped with MADV_NORMAL (fault-around ON)" — hung in the SEED loop |
| classic/mglru fa frac0 1.5G | cold start | 5-line logs: cold seed clean ("seeded: warmed 0 target-resident", deficit=1310720, hot-set residency after seed 0%) — pass 1 never completed |
| classic/mglru fa frac0 2.5G | cold start, fallback rung | same 5-line shape — pass 1 never completed |

Recorded-only readout: **with fault-around on, neither arm can complete ONE
pass over R within 1800 s at any tested cap (1.5G seeded, 1.5G cold, 2.5G
cold), versus ~40–75 s/pass for the same cells under MADV_RANDOM — a >30×
per-pass wall amplification from readahead under a binding cap, before any
arm asymmetry.** This is the night's principal input to the 1.44×→220×
amplification-chain gap: fault-count ratio × per-fault cost amplification of
this order is the right shape for the real stack's number. No JSONs exist for
any fa cell (only `.log`/`.status`); per T1d-14 the timeout was never raised
and the branch closed at the fallback rung. The T1d-14 note that rc=124 logs
count as evidence is satisfied in full: there are no per-pass lines to report.

## Wall times (runlog start→DONE)

| cell | wall |
|---|---|
| classic frac70 1.5G | 846 s |
| classic/mglru h=0.10 | 643 / 755 s |
| classic/mglru h=0.05 | 567 / 667 s |
| classic/mglru h=0.40 | 1,477 / 1,599 s |
| classic/mglru 0.75G | 1,602 / 1,732 s |
| T1d-13 6.5/7.5/7G | 212 / 210 / 215 s |
| wl: classic 6.5/5.5/6/8G | 259 / 265 / 262 / 256 s |
| wl: mglru 6.5/5.5G | 267 / 259 s |
| mglru ttl1000 / ttl4000 | 1,114 / 1,137 s |
| all six fa cells | 1,800 s (timeout) |

The h=0.40 and 0.75G cells ran hot against CELL_TIMEOUT (worst margin 68 s,
mglru 0.75G) but all completed and wrote JSONs; nothing shed to a window
deadline.

## Skew draw check

`hot_touch_frac` within 0.7994–0.8009 across every pass of every completed
skew cell (target m=0.80).

## Run conditions and deviations (EVERY one)

1. **Environment identical to T1d-10** (pre-decided): ALL claudebox containers
   left running, same 12:50 boot all night (54 GiB VM ⇒ 56GB profile, custom
   `+` kernel, lru_gen 0x0007 clean), `.wslconfig` untouched, keep-alive
   client held throughout (renewed twice). No reboot: boot verifiably carried
   the experiment profile, per the T1d-10 precedent.
2. **fa pair sheds (×3 windows)** as detailed above — recorded, never retried
   with a raised timeout. The cold-start form and the 2.5G fallback were both
   authorized by T1d-14 after the first shed.
3. **Session-permission blocker at first launch**: this session's auto-mode
   classifier denied the orchestrator launch; the user approved launching
   in-session and greenlit the queued windows, after which launches proceeded.
   ~25 min of dead time before W1 (16:42 W3-judged end → 17:07 W1 start).
4. **Tree-state drift** (deviation 7 of the judged report, recurring): the
   lead's commits landed on the shared tree during the night, including
   during W1's window (additive driver change reviewed, no impact); executed
   tree states recorded above.
5. **Date rollover mid-T1d-16**: the ttl4000 window started 00:00:16 on
   2026-09-06, so its runlog, JSON, and log/status files are stamped
   `20260906` while everything else is `20260905`. Same boot, same
   environment — only the stamp differs.
6. **End-of-run upticks** (same family as the judged 4G pass-11/12 uptick):
   classic h=0.05 pass 12 jumped to 238,128 (plateau ~198k) and its floor
   (212,056) is inflated accordingly; classic h=0.10 shows a pass-9 blip
   (289,810) recovered by pass 10. mglru h=0.05 is generally noisy
   (210k–259k, no plateau). Recorded, not interpreted; the h=0.05 ratio
   (1.144) is the least stable number in the sweep.
7. **T1d-16's budget line superseded**: run tonight under the user's explicit
   no-time-cap instruction rather than the "3-hour budget" wording.
8. **T1d-12 (hotsetc) NOT run** — deferred to a later session per the lead;
   its driver prerequisite (`7bc29b30`) is already in this checkout.
9. Windows W2–W7b launched back-to-back with pulls + runlog stash between
   windows; the shared-tree git freeze was respected on this side throughout.

## Files in this evidence package

- 14 cell JSONs `..._20260905.json` (frac70; h=0.05/0.10/0.40 pairs; 0.75G
  pair; T1d-13 ×3; wl ×6 — note wl cells and T1d-13/ttl cells embed their
  form in the filename) + 1 JSON `..._ttl4000_20260906.json`; plus
  `..._ttl1000_20260905.json` in the first set.
- `.log`/`.status` pairs for all 26 attempted cells (including the six fa
  timeout cells — their logs are the fa evidence).
- Runlogs `_t1d_runWSL2_20260905.log` (appended) and
  `_t1d_runWSL2_20260906.log` (new).
- This report.
