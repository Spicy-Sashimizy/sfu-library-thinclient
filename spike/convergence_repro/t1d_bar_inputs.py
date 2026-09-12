#!/usr/bin/env python3
"""Tier-1d bar inputs — mechanical extraction against the FROZEN section-5 bars.

Frozen 2026-09-05 in PREREGISTRATION_TIER1D.md section 5 (commit 5f55fb32);
this tool is committed BEFORE any judged cell exists (the t23b_bar_inputs.py
convention: the verdict arithmetic is pinned pre-data). It prints bar inputs
and clause outcomes; the VERDICTS are recorded by the session lead in
RESULTS.md, not by this script.

Usage:
    .venv/bin/python3 spike/convergence_repro/t1d_bar_inputs.py <YYYYMMDD>

Reads data/eval_results/t1d_*_<date>.json (validation cells excluded). Judged
seeds are {2027, 8128}; seed 1729 is calibration-burned and is shown as
corroboration only, never as a bar input.

Frozen constants (do not edit without a pre-reg amendment):
    steady floor       = mean majflt of the last 3 of 12 passes
    T1d-1  ratio bar   = MGLRU floor / classic floor >= 1.30 at cap1.5g,
                         BOTH seeds 2027 and 8128
    T1d-1b descent     = classic floor <= 0.75 x classic pass-1 majflt
    T1d-1b pinned      = every MGLRU pass 2-12 within +/-5% of the pass-2-12 mean
    T1d-3  control     = cap8g seed 2027: both floors <= near_zero, both
                         converged, ratio in [0.84, 1.16]
    T1d-3  upper band  = cap4g seed 2027: ratio <= 1.20
    T1d-5  validity    = every identity-applicable cap8g cell has
                         soundness_pass1_majflt_eq_deficit true; else the
                         window is INVALID in toto
    caveat margin      = a judged value within +/-16% of its threshold must
                         cite the section-4 pageReporting caveat
"""
import glob
import json
import os
import sys

JUDGED_SEEDS = (2027, 8128)
BURNED_SEED = 1729
RATIO_BAR = 1.30
DESCENT_BAR = 0.75
PIN_TOL = 0.05
CONTROL_BAND = (0.84, 1.16)
UPPER_BAND_MAX = 1.20
CAVEAT_MARGIN = 0.16
PRIMARY_SKEW = "hotset:0.20:0.80"


def floor_of(cell):
    mf = [p["majflt"] for p in cell["passes"]]
    return sum(mf[-3:]) / 3.0


def near(value, threshold):
    if threshold == 0:
        return False
    return abs(value / threshold - 1.0) <= CAVEAT_MARGIN


def caveat(value, threshold):
    return "  << within +/-16% of threshold: MUST cite the pageReporting caveat" \
        if near(value, threshold) else ""


def load(date):
    cells = {}
    pat = os.path.join("data", "eval_results", "t1d_*_%s.json" % date)
    for path in sorted(glob.glob(pat)):
        base = os.path.basename(path)
        if base.startswith("t1d_validation"):
            continue
        with open(path) as fh:
            d = json.load(fh)
        if d.get("protocol") != "tier1d":
            print("SKIP (protocol %r): %s" % (d.get("protocol"), base))
            continue
        skew = (d.get("skew") or {}).get("spec", "uniform")
        key = (d["arm"], d["cap_label"], int(d["seed"]), skew,
               bool(d.get("fault_around")))
        if key in cells:
            print("WARNING: duplicate cell for %s (keeping first): %s"
                  % (key, base))
            continue
        d["_file"] = base
        cells[key] = d
    return cells


def get(cells, arm, cap, seed, skew=PRIMARY_SKEW, fa=False):
    return cells.get((arm, cap, seed, skew, fa))


def pair_ratio(cells, cap, seed, skew=PRIMARY_SKEW):
    c = get(cells, "classic", cap, seed, skew)
    m = get(cells, "mglru", cap, seed, skew)
    if c is None or m is None:
        return None, c, m
    fc = floor_of(c)
    return (floor_of(m) / fc if fc else float("inf")), c, m


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    date = sys.argv[1]
    cells = load(date)
    if not cells:
        sys.exit("no tier1d cells found for date %s" % date)

    print("=== Tier-1d bar inputs, date %s — bars frozen at 5f55fb32 ===" % date)
    print("cells loaded: %d" % len(cells))
    burned = sorted(k for k in cells if k[2] == BURNED_SEED)
    if burned:
        print("NOTE: %d cell(s) at calibration-burned seed %d — corroboration "
              "only, excluded from every bar below" % (len(burned), BURNED_SEED))

    print("\n--- T1d-5 (validity gate: uncapped identity on cap8g cells) ---")
    t1d5_ok, t1d5_seen = True, False
    for key, d in sorted(cells.items()):
        if key[1] != "cap8g" or key[2] == BURNED_SEED:
            continue
        t1d5_seen = True
        if not d.get("soundness_identity_applicable", True):
            print("  %s: identity not applicable (fault-around) — skipped" % d["_file"])
            continue
        ok = bool(d.get("soundness_pass1_majflt_eq_deficit"))
        t1d5_ok &= ok
        print("  %s: identity %s (pass-1 majflt %d, reachable deficit %s)"
              % (d["_file"], "OK" if ok else "FAILED",
                 d["passes"][0]["majflt"], d.get("pass1_reachable_deficit_pages")))
    if not t1d5_seen:
        t1d5_ok = False
        print("  NO judged cap8g cells found — gate not computable")
    print("  T1d-5: %s" % ("PASSED — window valid" if t1d5_ok
                           else "NOT PASSED — WINDOW INVALID IN TOTO, no bar below may be judged"))

    print("\n--- T1d-1 (headline: ratio >= %.2f at cap1.5g, both judged seeds) ---" % RATIO_BAR)
    t1d1_flags = []
    for seed in JUDGED_SEEDS:
        ratio, c, m = pair_ratio(cells, "cap1.5g", seed)
        if ratio is None:
            print("  seed %d: MISSING cell(s) (classic %s, mglru %s) — not computable"
                  % (seed, "ok" if c else "MISSING", "ok" if m else "MISSING"))
            t1d1_flags.append(None)
            continue
        ok = ratio >= RATIO_BAR
        t1d1_flags.append(ok)
        print("  seed %d: classic floor %.0f, mglru floor %.0f, ratio %.3f -> %s%s"
              % (seed, floor_of(c), floor_of(m), ratio,
                 "clears bar" if ok else "BELOW BAR", caveat(ratio, RATIO_BAR)))
    if all(f is True for f in t1d1_flags):
        print("  T1d-1 inputs: bar met in BOTH replicates")
    elif any(f is None for f in t1d1_flags):
        print("  T1d-1 inputs: INCOMPLETE")
    else:
        print("  T1d-1 inputs: bar NOT met in both replicates")

    print("\n--- T1d-1b (mechanism shape at cap1.5g) ---")
    for seed in JUDGED_SEEDS:
        c = get(cells, "classic", "cap1.5g", seed)
        m = get(cells, "mglru", "cap1.5g", seed)
        if c is not None:
            p1 = c["passes"][0]["majflt"]
            frac = floor_of(c) / p1 if p1 else float("inf")
            ok = frac <= DESCENT_BAR
            print("  seed %d classic descent: floor/pass1 = %.3f (bar <= %.2f) -> %s%s"
                  % (seed, frac, DESCENT_BAR, "ok" if ok else "FAILS",
                     caveat(frac, DESCENT_BAR)))
        else:
            print("  seed %d classic descent: MISSING cell" % seed)
        if m is not None:
            tail = [p["majflt"] for p in m["passes"][1:]]
            mean = sum(tail) / len(tail)
            dev = max(abs(v / mean - 1.0) for v in tail) if mean else float("inf")
            ok = dev <= PIN_TOL
            print("  seed %d mglru pinned: max |dev| of passes 2-12 = %.4f (bar <= %.2f) -> %s"
                  % (seed, dev, PIN_TOL, "ok" if ok else "FAILS"))
        else:
            print("  seed %d mglru pinned: MISSING cell" % seed)

    print("\n--- T1d-3 (regime specificity, seed %d) ---" % JUDGED_SEEDS[0])
    seed = JUDGED_SEEDS[0]
    ratio, c, m = pair_ratio(cells, "cap8g", seed)
    if ratio is None:
        print("  cap8g control: MISSING cell(s)")
    else:
        conv = c.get("converged") and m.get("converged")
        floors_ok = (floor_of(c) <= c["near_zero"] and floor_of(m) <= m["near_zero"])
        in_band = CONTROL_BAND[0] <= ratio <= CONTROL_BAND[1]
        print("  cap8g: floors %.0f/%.0f (near_zero %d), converged %s/%s, ratio %.3f in [%.2f,%.2f]: %s%s"
              % (floor_of(c), floor_of(m), c["near_zero"],
                 c.get("converged"), m.get("converged"), ratio,
                 CONTROL_BAND[0], CONTROL_BAND[1],
                 "ok" if (conv and floors_ok and in_band) else "FAILS",
                 caveat(ratio, CONTROL_BAND[1])))
    ratio4, c4, m4 = pair_ratio(cells, "cap4g", seed)
    if ratio4 is None:
        print("  cap4g band: MISSING cell(s)")
    else:
        ok = ratio4 <= UPPER_BAND_MAX
        print("  cap4g: ratio %.3f (bar <= %.2f) -> %s%s"
              % (ratio4, UPPER_BAND_MAX, "ok" if ok else "FAILS",
                 caveat(ratio4, UPPER_BAND_MAX)))

    print("\n--- T1d-2 (skew sweep, recorded whichever way) ---")
    sweep = sorted({k[3] for k in cells
                    if k[1] == "cap1.5g" and k[3].startswith("hotset:")
                    and k[2] in JUDGED_SEEDS})
    for spec in sweep:
        h = float(spec.split(":")[1])
        for seed in JUDGED_SEEDS:
            ratio, c, m = pair_ratio(cells, "cap1.5g", seed, spec)
            if ratio is not None:
                print("  h=%.2f seed %d: ratio %.3f (>= %.2f: %s)"
                      % (h, seed, ratio, RATIO_BAR, ratio >= RATIO_BAR))

    print("\n--- Recorded-only cells present (no bars) ---")
    for key, d in sorted(cells.items()):
        if key[4] or key[1] not in ("cap1.5g", "cap4g", "cap8g") \
                or d["resident_frac_target"] != 0.92:
            print("  %s (arm=%s cap=%s frac=%s fault_around=%s)"
                  % (d["_file"], key[0], key[1],
                     d["resident_frac_target"], key[4]))

    print("\n--- Readout (not a bar): hot-set residency at cap1.5g ---")
    for key, d in sorted(cells.items()):
        if key[1] != "cap1.5g" or key[3] != PRIMARY_SKEW or key[4]:
            continue
        hr = [p.get("hot_resident_pct") for p in d["passes"]]
        if any(v is None for v in hr):
            print("  %s: hot_resident_pct ABSENT (pre-b3a9377a driver?)" % d["_file"])
        else:
            print("  %s: %s" % (d["_file"], " ".join("%.1f" % v for v in hr)))

    print("\nVerdicts are recorded by the session lead in RESULTS.md; this "
          "output is the bar-input evidence, not a verdict.")


if __name__ == "__main__":
    main()
