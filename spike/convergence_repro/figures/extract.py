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
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    print(OUT, OUT.stat().st_size // 1024, "KB")
    print("fig1 caps", [r["cap_gb"] for r in data["fig1_r1"]])
    print("fig2 cells", len(data["fig2_r2"]))
    print("fig45 cells", len(data["fig45_t23"]))
    for r in data["fig7_t1d_char"]["vs_h"]:
        print("h", r["h"], r["classic_floor"], r["mglru_floor"], r["ratio"])
    for r in data["fig7_t1d_char"]["vs_cap"]:
        print("cap", r["cap_gib"], r["classic_floor"], r["mglru_floor"], r["ratio"])


if __name__ == "__main__":
    main()
