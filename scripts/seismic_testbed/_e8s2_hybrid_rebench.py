#!/usr/bin/env python3
"""E8 Stage 2 hybrid-arm re-bench at higher reps to resolve the 2-rep cold miss
(hybrid cold 1.16x on 2 reps, wide spread 783/899 ms). Reuses q7's EXACT cell
protocol (fadvise-DONTNEED + serve_footprint_bench), hybrid arm only, alternating
v2.e5 / v1.e5 per rep so any host drift hits both (paired same-run ratios only)."""
import json, sys, statistics, time
from pathlib import Path

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))
from q7_hybrid_federation_bench import run_cell, _cold_p50, _warm_p50, _vmswap_gb

V2 = "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"
V1 = "data/eval_results/seismic_c25_shards_150m_mmap_e5.json"
REPS, QUERIES, PASSES = 6, 100, 3
bench_env = {"SFU_SEISMIC_LOAD_MODE": "mmap"}

rows = {"v2": [], "v1": []}
for rep in range(1, REPS + 1):
    for tag, man in [("v2", V2), ("v1", V1)]:
        cell = run_cell(man, "hybrid", QUERIES, PASSES, rep, bench_env)
        rows[tag].append({"rep": rep, "cold_p50": _cold_p50(cell),
                          "warm_p50": _warm_p50(cell), "vmswap": _vmswap_gb(cell)})
        print("rep {} {} hybrid: cold {} warm {} vmswap {}".format(
            rep, tag, _cold_p50(cell), _warm_p50(cell), _vmswap_gb(cell)), flush=True)

def med(xs):
    return statistics.median([x for x in xs if x is not None])

v2c, v1c = med([r["cold_p50"] for r in rows["v2"]]), med([r["cold_p50"] for r in rows["v1"]])
v2w, v1w = med([r["warm_p50"] for r in rows["v2"]]), med([r["warm_p50"] for r in rows["v1"]])
cold_ratio, warm_ratio = v2c / v1c, v2w / v1w
swap_ok = all((r["vmswap"] or 0) <= 0.1 for r in rows["v2"] + rows["v1"])

out = {
    "purpose": "E8 Stage 2 hybrid-arm re-bench (higher reps) to resolve the 2-rep cold miss",
    "measured_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
    "reps": REPS, "queries": QUERIES, "passes": PASSES,
    "protocol": "q7 cell protocol reused (fadvise-DONTNEED, alternating v2/v1, paired)",
    "per_rep": rows,
    "v2_cold_p50_median": round(v2c, 1), "v1_cold_p50_median": round(v1c, 1),
    "hybrid_cold_ratio_v2_over_v1": round(cold_ratio, 4),
    "v2_warm_p50_median": round(v2w, 1), "v1_warm_p50_median": round(v1w, 1),
    "hybrid_warm_ratio_v2_over_v1": round(warm_ratio, 4),
    "vmswap_ok": swap_ok,
    "bars": {"cold_p50": "<=1.10x", "warm_p50": "<=1.05x"},
    "cold_bar_pass": bool(cold_ratio <= 1.10),
    "warm_bar_pass": bool(warm_ratio <= 1.05),
}
json.dump(out, open("data/eval_results/e8_stage2_hybrid_rebench_20260713.json", "w"), indent=2)
print("HYBRID RE-BENCH ({} reps): cold ratio {:.4f} (bar<=1.10 {}) | warm ratio {:.4f} (bar<=1.05 {}) | swap_ok {}".format(
    REPS, cold_ratio, "PASS" if cold_ratio <= 1.10 else "FAIL",
    warm_ratio, "PASS" if warm_ratio <= 1.05 else "FAIL", swap_ok))
