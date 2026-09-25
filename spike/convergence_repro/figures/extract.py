#!/usr/bin/env python3
"""Figure data for the convergence-artifact write-up (2026-09-12).

Reads only committed result JSONs under data/eval_results/ and emits one
compact figures_data.json consumed by figures.html (the published figure
set). Nothing here re-measures; every number is a field of a recorded cell.

    .venv/bin/python3 spike/convergence_repro/figures/extract.py

Figures (numbering as in the write-up plan, 2026-09-12):
  1  R1 ladder (2026-07-14): per-pass majflt + p50 by cap — the observation.
  2  R2 fine ladder (2026-07-14): pass-3 p50 vs cap (non-monotone) beside
     converged p50 vs cap (monotone).
  3  R3 (2026-07-15/16): between-pass cachestat residency, 12 vs 16 GB.
  4  Tier-2/3 (2026-09-01): real stack, classic vs MGLRU, per-pass p50 and
     the converged state by cap (the cliff displacement).
  5  Tier-2/3 reclaim anatomy at 28 GB: workingset activate vs refault.
  6  Tier-1d (2026-09-05): synthetic hot-set residency + majflt per pass,
     classic vs MGLRU at 1.5 GiB, both seeds, plus the 8 GiB control.
  7  Tier-1d characterization (2026-09-06): floor ratio vs h and vs cap.
  8  Regime map (drawn 2026-09-13): every measured cell of figures 1 to 7
     placed on a cap-over-hot-set axis, per host lane, with the artifact
     band between the lower and upper regime boundaries.
"""
import glob
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ER = REPO / "data" / "eval_results"
OUT = Path(__file__).resolve().parent / "figures_data.json"


def load(p):
    return json.loads(Path(p).read_text())


def cap_gb(label):
    m = re.match(r"cap?([0-9.]+)g", label)
    return float(m.group(1)) if m else float(label.rstrip("g"))


def fig1():
    out = []
    for p in sorted(glob.glob(str(ER / "r1_cap*g_20260714.json"))):
        name = Path(p).name
        if "pin16" in name or "f5rel" in name:
            continue
        d = load(p)
        out.append({
            "cap_gb": cap_gb(d["cap"]),
            "passes": [{"pass": x["pass"], "p50_ms": x["p50_ms"], "majflt": x["majflt"]}
                       for x in d["per_pass"]],
        })
    out.sort(key=lambda r: r["cap_gb"])
    return out


def fig2():
    out = []
    for p in sorted(glob.glob(str(ER / "r2_cap*_20260714.json"))):
        d = load(p)
        rep = 2 if "rep2" in Path(p).name else 1
        pp = d["per_pass"]
        p3 = next((x for x in pp if x["pass"] == 3), None)
        out.append({
            "cap_gb": cap_gb(d["cap"]), "rep": rep,
            "pass3_p50_ms": p3["p50_ms"] if p3 else None,
            "pass3_majflt": p3["majflt"] if p3 else None,
            "converged": d["convergence"]["converged"],
            "kind": d["convergence"]["kind"],
            "passes_to_converge": d["convergence"].get("passes_to_converge"),
            "conv_p50_ms": d["converged_state"]["p50_ms"],
            "conv_majflt": d["converged_state"]["majflt"],
            "passes": [{"pass": x["pass"], "p50_ms": x["p50_ms"], "majflt": x["majflt"]} for x in pp],
        })
    out.sort(key=lambda r: (r["cap_gb"], r["rep"]))
    return out


def fig3():
    j = load(ER / "_r3_join_analysis.json")
    cells = {}
    for k, c in j["cells"].items():
        cells[k] = {
            "residue_maps": c["(a)_residue_maps"],
            "active_file_by_pass_gb": [round(v / 1e9, 3) for v in c["(c)_active_file_by_pass"]],
            "refault_count_sampled": c["(c)_refault_count"],
            "pass3_skew_max_over_mean": c["(b)_pass3_skew_max_over_mean"],
        }
    v = j["expectation_verdicts"]["3_sort_pictured"]
    return {"cells": cells, "verdict": v["verdict"], "evidence": v["evidence"],
            "note_16g": "16g live-tracer drain observer-perturbed (final 13.43 GB); the pre-fix dead-tracer 16g cell drained to 10.93 GB"}


def t23_cells():
    out = []
    for p in sorted(glob.glob(str(ER / "t23[ab]_*_cap*g_*20260901.json"))):
        d = load(p)
        name = Path(p).name
        m = re.search(r"_rep(\d)_", name)
        pp = d["per_pass"]
        out.append({
            "file": name, "phase": d["phase"], "arm": d["arm"], "cap_gb": cap_gb(d["cap"]),
            "rep": int(m.group(1)) if m else 0,
            "converged": d["convergence"]["converged"], "kind": d["convergence"]["kind"],
            "passes_to_converge": d["convergence"].get("passes_to_converge"),
            "conv_p50_ms": d["converged_state"]["p50_ms"], "conv_majflt": d["converged_state"]["majflt"],
            "passes": [{
                "pass": x["pass"], "p50_ms": x["p50_ms"], "majflt": x["majflt"],
                "pgscan": x["cg_delta"]["pgscan"],
                "ws_refault": x["cg_delta"]["workingset_refault_file"],
                "ws_activate": x["cg_delta"]["workingset_activate_file"],
                "active_file_gb": round(x["cg_gauges"]["active_file"] / 1e9, 3),
                "file_gb": round(x["cg_gauges"]["file"] / 1e9, 3),
            } for x in pp],
        })
    return out


def t1d_load(pattern):
    return [load(p) for p in sorted(glob.glob(str(ER / pattern)))]


def floor_of(cell):
    ps = cell["passes"]
    tail = [x["majflt"] for x in ps[-3:]]
    return sum(tail) / len(tail)


def t1d_series(cell):
    return [{"pass": x["pass"], "majflt": x["majflt"], "hot_resident_pct": x.get("hot_resident_pct"),
             "wall_s": x["wall_s"]} for x in cell["passes"]]


def fig6():
    out = {"judged": [], "control": []}
    for arm in ("classic", "mglru"):
        for seed in (2027, 8128):
            c = t1d_load(f"t1d_{arm}_hotset-0.20-0.80_frac92_cap1.5g_seed{seed}_20260905.json")[0]
            out["judged"].append({"arm": arm, "seed": seed, "cap_gib": 1.5, "floor": round(floor_of(c), 1),
                                  "hot_resident_pct_after_seed": c["hot_resident_pct_after_seed"],
                                  "passes": t1d_series(c)})
        c = t1d_load(f"t1d_{arm}_hotset-0.20-0.80_frac92_cap8g_seed2027_20260905.json")[0]
        out["control"].append({"arm": arm, "seed": 2027, "cap_gib": 8, "floor": round(floor_of(c), 1),
                               "passes": t1d_series(c)})
    return out


def fig7():
    rows_h = []
    for h in ("0.05", "0.10", "0.20", "0.40"):
        c = t1d_load(f"t1d_classic_hotset-{h}-0.80_frac92_cap1.5g_seed2027_2026090[56].json")[0]
        m = t1d_load(f"t1d_mglru_hotset-{h}-0.80_frac92_cap1.5g_seed2027_2026090[56].json")[0]
        fc, fm = floor_of(c), floor_of(m)
        rows_h.append({"h": float(h), "cap_gib": 1.5, "classic_floor": round(fc, 1), "mglru_floor": round(fm, 1),
                       "ratio": round(fm / fc, 3),
                       "classic_hot_res_end": c["passes"][-1].get("hot_resident_pct"),
                       "mglru_hot_res_end": m["passes"][-1].get("hot_resident_pct")})
    rows_cap = []
    for cap, seed in (("0.75", 2027), ("1.5", 2027), ("2.5", 1729), ("4", 2027), ("8", 2027)):
        c = t1d_load(f"t1d_classic_hotset-0.20-0.80_frac92_cap{cap}g_seed{seed}_2026090[56].json")[0]
        m = t1d_load(f"t1d_mglru_hotset-0.20-0.80_frac92_cap{cap}g_seed{seed}_2026090[56].json")[0]
        fc, fm = floor_of(c), floor_of(m)
        rows_cap.append({"cap_gib": float(cap), "h": 0.20, "seed": seed, "classic_floor": round(fc, 1),
                         "mglru_floor": round(fm, 1), "ratio": round(fm / fc, 3) if fc else None,
                         "classic_hot_res_end": c["passes"][-1].get("hot_resident_pct"),
                         "mglru_hot_res_end": m["passes"][-1].get("hot_resident_pct")})
    return {"vs_h": rows_h, "vs_cap": rows_cap, "bar": 1.30, "noise_band": 0.16,
            "floor_rule": "mean majflt of the last 3 of 12 passes (t1d_bar_inputs.py)"}


FIG8_HOSTS = {
    "wsl_r12": {
        "lane": 1, "unit": "GB",
        "title": "WSL2 6.18, classic LRU",
        "sub": "R1/R2 ladders, 2026-07-14",
        "hot_set": 10.1, "anon": 1.2, "footprint": 19.4,
        "lower": 11.3, "upper": 19.4,
        "lower_measured": True, "upper_measured": False,
        "lower_label": "hot set + anon 11.3 GB",
        "upper_label": "bracketed 17 to 24 GB",
        "hot_src": "R3 12 GB cell drained to 10.13 GB; R2 12 GB converged rssfile 9.94 GB",
        "footprint_src": "R2 24 GB cell after pass 1: cgroup file 18.17 GB + anon 1.2 GB",
    },
    "oci_t23": {
        "lane": 2, "unit": "GB",
        "title": "OCI E5 62 GiB, kernel 6.17",
        "sub": "Tier-2/3, 2026-09-01",
        "hot_set": 13.76, "anon": 1.0, "footprint": 29.1,
        "lower": 14.8, "upper": 29.1,
        "lower_measured": False, "upper_measured": True,
        "lower_label": "predicted 14.8 GB, unmeasured below 25 GB",
        "upper_label": "measured 29.1 GB",
        "cliff": 28.5, "cliff_label": "MGLRU cliff 28.5 GB",
        "hot_src": "converged active_file at 30 GB",
        "footprint_src": "30 GB fits with zero scan; 29 GB barely trims",
        "ticks": [{"x": 16.0, "label": "small-machine 16 GB: converged once, thrashed once (no JSON)"}],
    },
    "wsl_t1d": {
        "lane": 3, "unit": "GiB",
        "title": "Synthetic Tier-1d, both arms",
        "sub": "WSL2, 2026-09-05/06",
        "hot_set": 1.0, "anon": 0.0, "footprint": 6.75,
        "lower": 1.0, "upper": 6.75,
        "lower_measured": True, "upper_measured": True,
        "lower_label": "hot set 1.0 GiB",
        "upper_label": "footprint 6.75 GiB",
        "hot_src": "h = 0.20 of R = 5 GiB",
        "footprint_src": "R 5 GiB + L 1.75 GiB",
        "refs": [{"x": 5.0, "label": "|R| 5 GiB"}],
    },
}

NEAR_ZERO = 2500
SPIKE = 5.0
T1D_NOISE = 1.16


def classify(family, cell):
    """Outcome bucket for one measured cell (or, for Tier-1d, one arm pair).

    fits      converged near-zero (majflt/pass <= 2500) inside 3 passes with
              no pass >= 2 running more than 5x the converged p50.
    transient converged near-zero but the sort is visible in the window:
              passes_to_converge > 3, or a pass >= 2 above 5x the floor.
              For R1 (fixed 3 passes, no convergence rule) also the cell whose
              pass-3 majflt is still under half of pass 1 -- still descending.
    plateau   sustained thrash: convergence kind is plateau, or for R1 a
              pass-3 majflt above 2500 that is no longer descending.
    divergent Tier-1d cap whose MGLRU/classic floor ratio clears the +-16%
              pre-registered noise margin.
    pressured Tier-1d cap with no divergence: the hot set does not fit
              (0.75 GiB) or memory is loose (4 GiB).

    family is "r1" (fixed window), "conv" (R2 and Tier-2/3 cells, which carry
    a convergence verdict) or "t1d" (a floor-ratio row from fig7 vs_cap).
    """
    if family == "r1":
        ps = {x["pass"]: x for x in cell["passes"]}
        p1, p2, p3 = ps[1], ps[2], ps[3]
        if p3["majflt"] <= NEAR_ZERO:
            return "fits" if p2["p50_ms"] <= SPIKE * p3["p50_ms"] else "transient"
        return "transient" if p3["majflt"] < 0.5 * p1["majflt"] else "plateau"
    if family == "conv":
        if cell["kind"] == "plateau" or not cell["converged"]:
            return "plateau"
        ptc = cell.get("passes_to_converge") or 99
        floor = cell["conv_p50_ms"]
        spiked = any(x["p50_ms"] > SPIKE * floor for x in cell["passes"] if x["pass"] >= 2)
        return "transient" if (ptc > 3 or spiked) else "fits"
    if family == "t1d":
        if max(cell["classic_floor"], cell["mglru_floor"]) <= NEAR_ZERO:
            return "fits"
        return "divergent" if (cell["ratio"] or 0) > T1D_NOISE else "pressured"
    raise ValueError(family)


def _gnum(v):
    return "%g" % v


def fig8(f1, f2, t23, f7):
    """Every cell of figures 1 to 7 as a point on cap / measured-hot-set."""
    hosts = sorted(FIG8_HOSTS.values(), key=lambda h: h["lane"])
    hot = {h["lane"]: h["hot_set"] for h in hosts}
    pts = []

    def add(lane, cap, arm, outcome, label, source, row):
        pts.append({"lane": lane, "cap_gb": cap, "norm": round(cap / hot[lane], 4),
                    "arm": arm, "outcome": outcome, "label": label,
                    "source": source, "row": row})

    for c in f1:
        add(1, c["cap_gb"], "classic", classify("r1", c),
            "R1 " + _gnum(c["cap_gb"]) + " GB",
            "r1_cap" + _gnum(c["cap_gb"]) + "g_20260714.json", -1)
    for c in f2:
        rep = "_rep2" if c["rep"] == 2 else ""
        add(1, c["cap_gb"], "classic", classify("conv", c),
            "R2 " + _gnum(c["cap_gb"]) + " GB, rep " + str(c["rep"]),
            "r2_cap" + _gnum(c["cap_gb"]) + "g" + rep + "_20260714.json", 1)
    for c in t23:
        add(2, c["cap_gb"], c["arm"], classify("conv", c),
            "phase " + c["phase"] + " " + _gnum(c["cap_gb"]) + " GB"
            + (", rep " + str(c["rep"]) if c["rep"] else ""),
            c["file"], -1 if c["arm"] == "classic" else 1)
    for r in f7["vs_cap"]:
        outcome = classify("t1d", r)
        for arm in ("classic", "mglru"):
            cap = _gnum(r["cap_gib"])
            add(3, r["cap_gib"], arm, outcome,
                cap + " GiB, seed " + str(r["seed"]) + ", floor "
                + _gnum(round(r[arm + "_floor"])),
                "t1d_" + arm + "_hotset-0.20-0.80_frac92_cap" + cap
                + "g_seed" + str(r["seed"]) + "_20260905.json",
                -1 if arm == "classic" else 1)

    seen = {}
    for p in pts:
        k = (p["lane"], p["row"], p["cap_gb"])
        p["jit"] = seen.get(k, 0)
        seen[k] = p["jit"] + 1
    return {"hosts": hosts, "points": pts, "x_min": 0.5, "x_max": 10,
            "near_zero": NEAR_ZERO, "spike": SPIKE, "noise": T1D_NOISE,
            "rule": "x = cap / measured hot set; outcome by classify() in extract.py"}


def main():
    data = {
        "generated": "2026-09-12",
        "fig1_r1": fig1(),
        "fig2_r2": fig2(),
        "fig3_r3": fig3(),
        "fig45_t23": t23_cells(),
        "fig6_t1d": fig6(),
        "fig7_t1d_char": fig7(),
    }
    data["fig8_regime"] = fig8(data["fig1_r1"], data["fig2_r2"],
                               data["fig45_t23"], data["fig7_t1d_char"])
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    print(OUT, OUT.stat().st_size // 1024, "KB")
    print("fig1 caps", [r["cap_gb"] for r in data["fig1_r1"]])
    print("fig2 cells", len(data["fig2_r2"]))
    print("fig45 cells", len(data["fig45_t23"]))
    for r in data["fig7_t1d_char"]["vs_h"]:
        print("h", r["h"], r["classic_floor"], r["mglru_floor"], r["ratio"])
    for r in data["fig7_t1d_char"]["vs_cap"]:
        print("cap", r["cap_gib"], r["classic_floor"], r["mglru_floor"], r["ratio"])
    pts = data["fig8_regime"]["points"]
    print("fig8 points", len(pts))
    for lane in (1, 2, 3):
        lp = [p for p in pts if p["lane"] == lane]
        kinds = {}
        for p in lp:
            kinds[p["outcome"]] = kinds.get(p["outcome"], 0) + 1
        print("  lane", lane, len(lp), kinds)


if __name__ == "__main__":
    main()
