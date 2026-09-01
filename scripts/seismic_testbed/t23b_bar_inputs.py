#!/usr/bin/env python3
# Tier-2/3 phase-B bar-input extractor (PREREGISTRATION_TIER23.md s7, bars
# frozen at 1a87aac3). Reads data/eval_results/t23b_*_<date>.json and prints
# every quantity the frozen B1-B5 bars name, per cell. Judgment itself is
# recorded in the pre-reg doc, not here.
import glob, json, re, sys

date = sys.argv[1] if len(sys.argv) > 1 else "20260901"
cells = {}
for p in sorted(glob.glob(f"data/eval_results/t23b_*_{date}.json")):
    m = re.search(r"t23b_(classic|mglru)_cap(\d+)g_rep(\d+)_", p)
    if not m:
        continue
    d = json.load(open(p))
    key = (m.group(1), int(m.group(2)), int(m.group(3)))
    cells[key] = d
    if d.get("prefault_gate") != "1":
        print(f"PROTOCOL VIOLATION {key}: prefault_gate={d.get('prefault_gate')}")
        sys.exit(2)

for (arm, cap, rep), d in sorted(cells.items()):
    conv = d["convergence"]
    pp = d["per_pass"]
    traj = " ".join(str(x["majflt"]) for x in pp)
    p2 = next((x for x in pp if x["pass"] == 2), None)
    last = pp[-1]
    print(f"{arm:7s} cap{cap:2d} rep{rep} kind={conv['kind']:<10s} "
          f"passes={conv['passes_to_converge'] if conv['converged'] else '-'} "
          f"load_s={d['load_s']:<6} majflt_traj=[{traj}]")
    print(f"        pass1: pgscan={pp[0]['cg_delta']['pgscan']} majflt={pp[0]['majflt']} p50={pp[0]['p50_ms']}")
    if p2:
        print(f"        pass2: p50={p2['p50_ms']} majflt={p2['majflt']}")
    print(f"        final: p50={last['p50_ms']} majflt={last['majflt']} "
          f"active_file={last['cg_gauges']['active_file']} "
          f"conv_state_majflt={d['converged_state']['majflt'] if d.get('converged_state') else None}")
