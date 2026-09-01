#!/usr/bin/env python3
# Tier-2/3 EXPLORATORY mechanism probe (not a bar tool; frozen bars judged
# only via t23b_bar_inputs.py). Digs into WHY the fixed-window artifact is
# non-monotonic in cap: per-pass reclaim split (kswapd vs direct),
# workingset refaults, active/inactive balance, and the load phase itself,
# across arms and rungs. Reads t23b_* (phase B) and t23a_* (phase A,
# context only) cells.
import glob, json, re, sys

date = sys.argv[1] if len(sys.argv) > 1 else "20260901"
GB = 1 << 30

def load(pattern):
    out = {}
    for p in sorted(glob.glob(pattern)):
        m = re.search(r"(t23[ab])_(classic|mglru)_cap(\d+)g(?:_rep(\d+))?_", p)
        if not m:
            continue
        out[(m.group(1), m.group(2), int(m.group(3)), int(m.group(4) or 1))] = json.load(open(p))
    return out

cells = load(f"data/eval_results/t23b_*_{date}.json")
cells.update(load(f"data/eval_results/t23a_*_{date}.json"))

print("=== LOAD PHASE (does the DB load itself branch on cap?) ===")
print(f"{'cell':28s} {'load_s':>7s} {'ld_majflt':>9s} {'ld_pgscan':>10s} "
      f"{'file_GB':>8s} {'mapped_GB':>9s} {'anon_GB':>7s} {'actf_GB':>8s}")
for (tier, arm, cap, rep), d in sorted(cells.items()):
    g = d.get("cg_postload_gauges") or {}
    ld = d.get("cg_load_delta") or {}
    if not g:
        continue
    print(f"{tier}_{arm}_cap{cap}_r{rep:<10d} {d['load_s']:>7} {ld.get('pgmajfault',0):>9d} "
          f"{ld.get('pgscan',0):>10d} {g['file']/GB:>8.2f} {g['file_mapped']/GB:>9.2f} "
          f"{g['anon']/GB:>7.2f} {g['active_file']/GB:>8.3f}")

print("\n=== PER-PASS RECLAIM ANATOMY (phase-B cells) ===")
for (tier, arm, cap, rep), d in sorted(cells.items()):
    if tier != "t23b":
        continue
    print(f"\n{arm} cap{cap} rep{rep}  (prefault_gate={d.get('prefault_gate')})")
    print(f"  {'pass':>4s} {'majflt':>7s} {'p50_ms':>8s} {'scan_kswpd':>10s} {'scan_drct':>10s} "
          f"{'steal':>9s} {'ws_refault':>10s} {'ws_activ':>9s} {'ws_restore':>10s} "
          f"{'actf_GB':>8s} {'inactf_GB':>9s} {'rssfile_GB':>10s}")
    for pp in d["per_pass"]:
        cg = pp["cg_delta"]; ga = pp["cg_gauges"]; vm = pp["vm"]
        print(f"  {pp['pass']:>4d} {pp['majflt']:>7d} {pp['p50_ms']:>8.1f} "
              f"{cg.get('pgscan_kswapd',0):>10d} {cg.get('pgscan_direct',0):>10d} "
              f"{cg.get('pgsteal',0):>9d} {cg.get('workingset_refault_file',0):>10d} "
              f"{cg.get('workingset_activate_file',0):>9d} {cg.get('workingset_restore_file',0):>10d} "
              f"{ga['active_file']/GB:>8.3f} {ga['inactive_file']/GB:>9.3f} "
              f"{vm['rssfile_kb']*1024/GB:>10.2f}")

print("\n=== FIXED-WINDOW NON-MONOTONICITY TABLE (classic, pass 2 vs pass-1 work) ===")
print(f"{'cap':>4s} {'p1_majflt':>9s} {'p1_pgscan':>10s} {'p1_steal':>9s} "
      f"{'p2_majflt':>9s} {'p2_p50':>8s} {'p2_refault':>10s} {'final_actf_GB':>13s}")
for (tier, arm, cap, rep), d in sorted(cells.items()):
    if tier != "t23b" or arm != "classic" or rep != 1:
        continue
    p1 = d["per_pass"][0]
    p2 = next((x for x in d["per_pass"] if x["pass"] == 2), None)
    if not p2:
        continue
    print(f"{cap:>4d} {p1['majflt']:>9d} {p1['cg_delta']['pgscan']:>10d} "
          f"{p1['cg_delta']['pgsteal']:>9d} {p2['majflt']:>9d} {p2['p50_ms']:>8.1f} "
          f"{p2['cg_delta'].get('workingset_refault_file',0):>10d} "
          f"{d['per_pass'][-1]['cg_gauges']['active_file']/GB:>13.3f}")
