#!/usr/bin/env python3
"""E8 Stage 2 federated quality gate a: corpus-mean overlap@10 vs f16.
Aggregates the 8 per-shard e8_stage2_shard{k} result JSONs (pre-registered
bar: corpus-mean >= 0.995 AND no shard < 0.99). Writes a federated result JSON."""
import json, glob, statistics, time

rows = []
for K in range(8):
    fs = sorted(glob.glob(f"data/eval_results/e8_stage2_shard{K}_*.json"))
    d = json.load(open(fs[-1]))
    g = d["gates"]["a_quality"]
    rows.append({"shard": K, "v2": g["overlap@10_v2_vs_f16"],
                 "dv1": g["overlap@10_dv1_vs_f16"], "v2_min": g["overlap@10_v2_min"],
                 "file": fs[-1]})

v2m = statistics.mean(r["v2"] for r in rows)
v2min = min(r["v2"] for r in rows)
dv1m = statistics.mean(r["dv1"] for r in rows)
gate = (v2m >= 0.995) and (v2min >= 0.99)

out = {
    "purpose": "E8 Stage 2 federated quality gate a (corpus-mean overlap@10 vs f16)",
    "measured_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
    "per_shard": rows,
    "corpus_mean_overlap_v2": round(v2m, 5),
    "corpus_min_overlap_v2": round(v2min, 4),
    "corpus_mean_overlap_dv1_baseline": round(dv1m, 5),
    "improvement_vs_dv1": round(v2m - dv1m, 5),
    "bar": "corpus-mean >= 0.995 AND no shard < 0.99",
    "gate_a_federated_pass": bool(gate),
}
json.dump(out, open("data/eval_results/e8_stage2_federated_quality_20260713.json", "w"), indent=2)

for r in rows:
    print("  shard{s}: v2 {v:.4f} (min {m:.2f}) | dv1 {d:.4f}".format(
        s=r["shard"], v=r["v2"], m=r["v2_min"], d=r["dv1"]))
print("CORPUS MEAN v2={:.5f} min={:.4f} | dv1 baseline={:.5f} | +{:.4f}".format(
    v2m, v2min, dv1m, v2m - dv1m))
print("GATE a (federated): {}  (bar: mean>=0.995, no shard<0.99)".format(
    "PASS" if gate else "FAIL"))
