#!/usr/bin/env python3
"""WI-4 (deployprep 2026-07-16) — portable-CPU build gate reclear.

Today's served `.so` is `target-cpu=native` — it cannot ship to end users (native
= this exact CPU; a different host may lack the instructions → SIGILL). This
builds `x86-64-v3` (AVX2+FMA+BMI1/2) and `x86-64-v2` (SSE4.2+SSSE3) variants
and re-runs the established E7 gates (math_optimization/05: worst-case-shard +
n≥100) vs the native build, on the served e5_v2 shards:

  - **gate a (parity):** overlap@10 of the variant's top-10 vs the native .so's
    top-10, n≥100 queries, on shard 1 AND shard 2 (the worst-case shards, G8d
    §7.6). A CPU-target change that reorders FMA could alter float rounding →
    different top-k; this gate must be ≥0.99 (the promotable bar). *est.*: the
    v3 build uses the SAME packed SIMD as native (objdump: 100 vfmadd / 13979
    ymm vs native 76/15392) → parity should hold bit-identical or near.
  - **gate b (warm latency):** variant warm traverse p50 / native warm traverse
    p50, ≤1.07× (the E7 bar). v3 ≈ native (same FMA path); v2 (SSE2-ish, no
    FMA / no 256-bit) expected slower.

DO NOT overwrite the production .so — variants live beside it at
`spike/seismic_upstream/target/portable_so/{v3,v2}/seismic/...so`, loadable by
prepending that dir to sys.path (an explicit path/env, never the venv default).

Method: parity needs BOTH .so versions' top-k on the SAME shard + queries. They
can't coexist in one process (one `import seismic`), so this runs the variant in
one subprocess and the native reference in another, writing each one's per-query
top-10 oaids to JSON, then a parent step computes overlap@10. The warm-latency
ratio is measured in-process per variant (variant vs a native reference cell),
both via the E7 `run_pass` cold+warm pattern.

Usage (variant):
    SFU_SEISMIC_PREFLOOR=2 .venv/bin/python3 scripts/seismic_testbed/wi4_portable_cpu_gates.py \\
        --variant v3 --output-dir data/eval_results
Then the native reference + the join:
    .venv/bin/python3 scripts/seismic_testbed/wi4_portable_cpu_gates.py \\
        --variant v3 --compute-ratios data/eval_results/wi4_topk_v3_shard1.json ...
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

TOP_K = 50
K_PRIME = 100     # served default G8f
HEAP_FACTOR = 0.8
SPLADE_QUERY_TERMS = 64
WARM_REPEATS = 15   # E7 reclear footing (stable per-query median)
N_QUERIES = 100

VARIANT_DIRS = {
    "v3": REPO / "spike/seismic_upstream/target/portable_so/v3",
    "v2": REPO / "spike/seismic_upstream/target/portable_so/v2",
    "native": REPO / ".venv/lib/python3.11/site-packages",  # the served .so
}


def load_queries(n, qpath):
    records = json.loads(qpath.read_text())
    out, seen = [], set()
    for rec in records:
        p = rec["paraphrase"]
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
        if len(out) >= n:
            break
    return out


def read_majflt():
    return int(Path("/proc/self/stat").read_text().split()[11])


def run_variant_topk(variant_dir, variant_label, shard_dir, queries, model_path, out_json):
    """Subprocess: load the variant .so (path-prepended), run cold+warm passes,
    write per-query top-10 oaids + warm traverse stats to out_json. This runs
    in its own process so the variant `seismic` doesn't collide with a native
    `seismic` in the parent."""
    script = f"""
import sys, json, os
sys.path.insert(0, {str(variant_dir)!r})
sys.path.insert(0, 'src')
sys.path.insert(0, 'scripts/seismic_testbed')
import numpy as np
import seismic as _s
idx = _s.MmapSeismicIndex({str(shard_dir)!r})
from lib.opensearch_retriever import encode_splade
from e7_dotvbyte_gates import run_pass  # reuse the E7 cold+warm helper
qs = {json.dumps(queries)}
per_q = []
for q in qs:
    sp = encode_splade(q, {str(model_path)!r})
    sp = dict(sorted(sp.items(), key=lambda x:-x[1])[:{SPLADE_QUERY_TERMS}])
    per_q.append(sp)
string_dtype = _s.get_seismic_string()
prefloor = int(os.environ.get('SFU_SEISMIC_PREFLOOR','0') or 0)
# cold+warm (run_pass returns cell + per-query top-k' oaids)
cell, tops = run_pass(idx, string_dtype, per_q, {variant_label!r}, {WARM_REPEATS}, {K_PRIME}, prefloor)
# capture top-10 (the overlap@10 bar) — re-search warm (pages now resident).
top10 = []
for terms in per_q:
    qcomp = np.array(list(terms.keys()), dtype=string_dtype)
    qvals = np.array([float(v) for v in terms.values()], dtype=np.float32)
    res = idx.search(query_id='q', query_components=qcomp, query_values=qvals,
                     k={K_PRIME}, query_cut=len(terms), heap_factor={HEAP_FACTOR})
    top10.append([d for (_q,_s,d) in res[:10]])
out = {{'cell': cell, 'top10': top10, 'shard': {str(shard_dir)!r}, 'variant': {variant_label!r}}}
open({str(out_json)!r},'w').write(json.dumps(out))
print('wrote', {str(out_json)!r}, 'warm p50', cell.get('warm_traverse_ms_p50'))
"""
    env = dict(os.environ)
    proc = subprocess.run([str(REPO / ".venv/bin/python3"), "-c", script],
                          cwd=str(REPO), env=env, capture_output=True, text=True,
                          timeout=900)
    if proc.returncode != 0:
        print("STDERR:", proc.stderr[-2000:], file=sys.stderr)
        raise RuntimeError(f"variant subprocess failed rc={proc.returncode}")
    return json.loads(Path(out_json).read_text())


def overlap_at_k(ref, cand, k=10):
    """mean overlap@10: |ref[:10] ∩ cand[:10]| / 10, per query, averaged."""
    if not ref or not cand:
        return None, None
    overlaps = []
    for r, c in zip(ref, cand):
        rs = set(list(r)[:k])
        cs = set(list(c)[:k])
        overlaps.append(len(rs & cs) / k)
    return statistics.mean(overlaps), min(overlaps)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", choices=["v3", "v2", "native"], required=True)
    ap.add_argument("--shard", default="1", choices=["1", "2", "both"])
    ap.add_argument("--queries", type=int, default=N_QUERIES)
    ap.add_argument("--model-path", default="models/splade_onnx_fused")
    ap.add_argument("--query-workload",
                    default=str(REPO / "data/eval_results/diverse_queries.json"))
    ap.add_argument("--output-dir", default=str(REPO / "data/eval_results"))
    ap.add_argument("--compute-ratios", nargs="+", default=None,
                    help="paths to (variant_json native_json) pairs to compute the "
                         "overlap@10 + warm ratio WITHOUT running (the join step)")
    args = ap.parse_args()
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    # ── join step: compute overlap@10 + warm ratio from two pre-written JSONs ──
    if args.compute_ratios:
        assert len(args.compute_ratios) == 2, "pass <variant_json> <native_json>"
        v = json.loads(Path(args.compute_ratios[0]).read_text())
        n = json.loads(Path(args.compute_ratios[1]).read_text())
        ov_mean, ov_min = overlap_at_k(n["top10"], v["top10"], k=10)
        warm_ratio = v["cell"]["warm_traverse_ms_p50"] / n["cell"]["warm_traverse_ms_p50"]
        verdict = {
            "variant": args.variant,
            "shard": v.get("shard"),
            "gate_a_parity": {"overlap@10_mean": round(ov_mean, 4),
                              "overlap@10_min": round(ov_min, 4),
                              "n_queries": len(v["top10"]),
                              "bar": ">= 0.99", "pass": ov_mean >= 0.99},
            "gate_b_warm_latency": {"variant_warm_p50_ms": v["cell"]["warm_traverse_ms_p50"],
                                    "native_warm_p50_ms": n["cell"]["warm_traverse_ms_p50"],
                                    "ratio": round(warm_ratio, 4),
                                    "bar": "<= 1.07", "pass": warm_ratio <= 1.07},
            "variant_cell": v["cell"], "native_cell": n["cell"],
        }
        vf = outdir / f"wi4_verdict_{args.variant}_{Path(v.get('shard','')).name}.json"
        vf.write_text(json.dumps(verdict, indent=2))
        print(json.dumps(verdict, indent=2))
        print(f"\nverdict written to {vf}")
        return 0

    # ── run step: produce the variant (or native reference) top-k JSON ──
    queries = load_queries(args.queries, Path(args.query_workload))
    variant_dir = str(VARIANT_DIRS[args.variant])
    shards = ["1", "2"] if args.shard == "both" else [args.shard]
    for s in shards:
        shard_dir = str(REPO / f"data/seismic_150m/index/plan01/global_shard{s}of8.dotvbyte.e5.v2.mmap")
        out_json = str(outdir / f"wi4_topk_{args.variant}_shard{s}.json")
        print(f"=== variant {args.variant} shard {s} (n={len(queries)} q) → {out_json} ===", flush=True)
        run_variant_topk(variant_dir, args.variant, shard_dir, queries,
                         args.model_path, out_json)
        print(f"wrote {out_json}", flush=True)
    return 0


if __name__ == "__main__":
    main()

