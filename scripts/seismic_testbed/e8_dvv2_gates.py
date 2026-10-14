#!/usr/bin/env python3
"""E8 Stage-1 gates — the dv-v2 (per-doc value scale) shard vs its f16 twin
and its dv-v1 twin, same queries. Pre-registered in doc 12 §3 Q1 (bars fixed
before Stage 1 was built; Stage 0 proxy GO 0.997/0.993 on shards 1–2):

  (a) quality — overlap@10 (v2 vs the f16 twin) ≥ 0.99, n=100 diverse queries,
                recall-max params (all terms, query_cut=all, hf=0.8, k'=200).
                The dv-v1-vs-f16 overlap is recorded alongside for the
                improvement delta (v1 measured 0.985/0.984 on shards 1–2).
  (b) size    — v2 on-disk bytes within ±2% of the dv-v1 dir.
  (c) latency — v2 warm traverse p50 ≤ 1.05× dv v1 (same build-order layout;
                the only kernel change is the per-doc dequant scale).
  (d) T1      — sequential mechanism-B invariant on the v2 dir: a scored pass
                after release_pages()+fadvise(DONTNEED) is bit-identical to
                the warm pass (hard_mismatches == 0 AND tie_swaps == 0 — same
                process, same tie-breaks, so full bit-identity is required).

All three dirs must be twins of the SAME shard (cardinality asserted). Both
timed arms alternate order across reps with true page-cache eviction — the
`e5_shard_gates.py` method. Cold p50 / majflt ratios are recorded for
information; the Stage-1 latency BAR is warm-only (cold locality parity with
dv v1 is expected — same record walk, +2 bytes/record head).

Run from repo root (once per shard):

    SFU_SEISMIC_PREFLOOR=2 .venv/bin/python3 scripts/seismic_testbed/e8_dvv2_gates.py \
        --f16-dir data/seismic_150m/index/plan01/global_shard1of8.mmap \
        --dv1-dir data/seismic_150m/index/plan01/global_shard1of8.dotvbyte.mmap \
        --v2-dir  data/seismic_150m/index/plan01/global_shard1of8.dotvbyte.v2.mmap \
        --queries 100
"""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from e6_forward_codec_proto import load_queries, read_rss  # noqa: E402
from e5_shard_gates import (  # noqa: E402  (E5/E7 conventions)
    fadvise_dontneed_dir, run_cold_pass, scored_pass, tie_aware_compare,
)

TOP_K_PRIME = 200
OVERLAP_K = 10
HEAP_FACTOR = 0.8
SPLADE_QUERY_TERMS = 64
REPS = 3


def dir_bytes(d: Path) -> int:
    return sum(os.path.getsize(d / f) for f in os.listdir(d))


def overlap_at_k(a_scored, b_scored, k=OVERLAP_K):
    ovs = [len({d for d, _ in a[:k]} & {d for d, _ in b[:k]}) / k
           for a, b in zip(a_scored, b_scored)]
    return statistics.mean(ovs), min(ovs)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--f16-dir", required=True)
    ap.add_argument("--dv1-dir", required=True)
    ap.add_argument("--v2-dir", required=True)
    ap.add_argument("--queries", type=int, default=100)
    ap.add_argument("--k-prime", type=int, default=TOP_K_PRIME)
    ap.add_argument("--model-path", default="models/splade_onnx_fp16")
    ap.add_argument("--query-workload",
                    default=str(REPO / "data/eval_results/diverse_queries.json"))
    ap.add_argument("--result-file", default=None)
    args = ap.parse_args()
    assert args.queries <= 100, "audit rule: <=100 queries"
    prefloor = int(os.environ.get("SFU_SEISMIC_PREFLOOR", "0") or 0)

    from lib.opensearch_retriever import encode_splade  # torch first (ENOMEM lesson)
    import seismic

    string_dtype = seismic.get_seismic_string()
    f16 = seismic.MmapSeismicIndex(args.f16_dir)
    dv1 = seismic.MmapSeismicIndex(args.dv1_dir)
    v2 = seismic.MmapSeismicIndex(args.v2_dir)
    assert f16.forward_format == "f16", f16.forward_format
    assert dv1.forward_format == "dotvbyte_fixedu8", dv1.forward_format
    assert v2.forward_format == "dotvbyte_fixedu8_v2", v2.forward_format
    assert f16.len == dv1.len == v2.len, "doc cardinality drift across twins"
    assert f16.nnz == dv1.nnz == v2.nnz, "nnz drift across twins"

    queries = load_queries(args.queries, Path(args.query_workload))
    per_q_terms = []
    for q in queries:
        sparse = encode_splade(q, args.model_path)
        per_q_terms.append(dict(sorted(sparse.items(),
                                       key=lambda x: -x[1])[:SPLADE_QUERY_TERMS]))
    print(f"[e8-gates] {len(queries)} queries encoded; twins loaded "
          f"({f16.len} docs)", flush=True)

    # ---- (a) quality: warm scored passes, overlap@10 vs the f16 twin ----
    f16_scored = scored_pass(f16, string_dtype, per_q_terms, args.k_prime)
    dv1_scored = scored_pass(dv1, string_dtype, per_q_terms, args.k_prime)
    v2_scored = scored_pass(v2, string_dtype, per_q_terms, args.k_prime)
    v2_ov, v2_ov_min = overlap_at_k(v2_scored, f16_scored)
    dv1_ov, dv1_ov_min = overlap_at_k(dv1_scored, f16_scored)
    print(f"[e8-gates] overlap@10 vs f16: v2 {v2_ov:.4f} (min {v2_ov_min:.2f}), "
          f"dv1 {dv1_ov:.4f} (min {dv1_ov_min:.2f})", flush=True)

    # ---- (d) T1: mechanism-B bit-identity on the v2 dir ----
    released = v2.release_pages()
    assert released > 0, "v2 release_pages covered no ranges"
    evicted = fadvise_dontneed_dir(Path(args.v2_dir))
    assert evicted > 0, "v2 fadvise covered no bytes"
    v2_cold_scored = scored_pass(v2, string_dtype, per_q_terms, args.k_prime)
    t1_hard = t1_swaps = 0
    for a, b in zip(v2_scored, v2_cold_scored):
        h, s = tie_aware_compare(a, b)
        t1_hard += h
        t1_swaps += s
    print(f"[e8-gates] T1 seq-vs-warm: hard={t1_hard} swaps={t1_swaps}", flush=True)

    # ---- (c) latency: dv1 vs v2 timed cells, alternating order, true eviction ----
    cells = {"dv1": [], "v2": []}
    arms = {"dv1": (dv1, args.dv1_dir), "v2": (v2, args.v2_dir)}
    for rep in range(REPS):
        order = ["dv1", "v2"] if rep % 2 == 0 else ["v2", "dv1"]
        for label in order:
            idx, shard_dir = arms[label]
            cell, _tops = run_cold_pass(idx, shard_dir, string_dtype, per_q_terms,
                                        f"{label}_rep{rep}", 5, args.k_prime,
                                        prefloor)
            cells[label].append(cell)
            print(f"[e8-gates] {label} rep{rep}: cold p50 "
                  f"{cell['cold_traverse_ms_p50']} ms, warm p50 "
                  f"{cell['warm_traverse_ms_p50']} ms, majflt "
                  f"{cell['majflt_cold_pass']}", flush=True)

    med = lambda arm, k: statistics.median(c[k] for c in cells[arm])
    warm_ratio = med("v2", "warm_traverse_ms_p50") / med("dv1", "warm_traverse_ms_p50")
    cold_ratio = med("v2", "cold_traverse_ms_p50") / med("dv1", "cold_traverse_ms_p50")
    dv1_majflt, v2_majflt = med("dv1", "majflt_cold_pass"), med("v2", "majflt_cold_pass")
    majflt_ratio = (v2_majflt / dv1_majflt) if dv1_majflt else None

    # ---- (b) size ----
    dv1_b, v2_b = dir_bytes(Path(args.dv1_dir)), dir_bytes(Path(args.v2_dir))
    size_delta = (v2_b - dv1_b) / dv1_b

    gates = {
        "a_quality": {"overlap@10_v2_vs_f16": round(v2_ov, 4),
                      "overlap@10_v2_min": round(v2_ov_min, 4),
                      "overlap@10_dv1_vs_f16": round(dv1_ov, 4),
                      "bar": ">= 0.99", "pass": v2_ov >= 0.99},
        "b_size": {"dv1_bytes": dv1_b, "v2_bytes": v2_b,
                   "delta_pct": round(100 * size_delta, 3),
                   "bar": "abs <= 2%", "pass": abs(size_delta) <= 0.02},
        "c_latency": {"warm_p50_ratio": round(warm_ratio, 4), "bar": "<= 1.05",
                      "pass": warm_ratio <= 1.05},
        "d_t1": {"hard_mismatches": t1_hard, "tie_swaps": t1_swaps,
                 "bar": "hard == 0 and swaps == 0", "pass": t1_hard == 0 and t1_swaps == 0},
    }
    verdict = ("E8_STAGE1_ALL_GATES_PASS" if all(g["pass"] for g in gates.values())
               else "E8_STAGE1_GATE_FAIL: " + ",".join(k for k, g in gates.items()
                                                       if not g["pass"]))
    out = {
        "meta": {"purpose": "E8 Stage-1 gates — dv-v2 per-doc value scale, doc 12 §3 Q1",
                 "measured_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
                 "f16_dir": args.f16_dir, "dv1_dir": args.dv1_dir,
                 "v2_dir": args.v2_dir, "n_queries": len(queries),
                 "k_prime": args.k_prime, "heap_factor": HEAP_FACTOR,
                 "prefloor": prefloor, "reps": REPS, "rss": read_rss()},
        "cells": cells,
        "ratios": {"warm_p50": round(warm_ratio, 4), "cold_p50": round(cold_ratio, 4),
                   "majflt_cold": (round(majflt_ratio, 4)
                                   if majflt_ratio is not None else None)},
        "gates": gates, "verdict": verdict,
    }
    result = Path(args.result_file) if args.result_file else \
        REPO / f"data/eval_results/e8_dvv2_stage1_{time.strftime('%Y%m%d_%H%M')}.json"
    result.write_text(json.dumps(out, indent=2))
    print(json.dumps({"verdict": verdict, "gates": {k: g["pass"] for k, g in gates.items()},
                      **out["ratios"]}, indent=2))
    print(f"result -> {result}")


if __name__ == "__main__":
    main()
