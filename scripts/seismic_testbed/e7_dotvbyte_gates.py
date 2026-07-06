#!/usr/bin/env python3
"""SEISMIC testbed — E7 gates: the compressed (DotVByteFixedU8) forward vs the
f16 forward, same shard, same queries. The pre-registered implementation gates
from `docs/seismic_150m_testbed/10_FORWARD_COMPRESSION_DESIGN.md` §5:

  (a) PARITY   — overlap@10 (dotvbyte vs f16 top-10) ≥ 0.99, 40 diverse queries,
                 recall-max params (all terms, query_cut=all, hf=0.8, k'=200).
  (b) LATENCY  — dotvbyte warm traverse p50 ≤ 1.07× f16 (the C0.5 decode envelope).
  (c) PAGES    — dotvbyte cold-pass majflt ≤ 0.55× f16 (the interleave+compression
                 claim: ~1 page/candidate instead of ~2 — 09 audit §3.2 / E6 §3).

Method mirrors E1 (`e1_kprime_df_sweep.py`): per cell `release_pages()`
(mechanism B) → cold pass (majflt delta + cold ms) → WARM_REPEATS warm p50.
Both indexes are loaded via the SAME Python class (`seismic.MmapSeismicIndex`
dispatches on the manifest's `forward_format`) — which is itself part of what
this gate exercises.

RAM discipline: ONE shard (two layouts of it), mmap load only, ≤100 queries,
RSS probes recorded.

Run from repo root:

    .venv/bin/python3 scripts/seismic_testbed/e7_dotvbyte_gates.py \
        --f16-dir data/seismic_150m/index/plan01/global_shard0of8.mmap \
        --dv-dir  data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.mmap \
        --queries 40
"""
import argparse
import json
import logging
import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("e7_gates")

TOP_K = 50
OVERLAP_K = 10
K_PRIME = 200
HEAP_FACTOR = 0.8
WARM_REPEATS = 5
SPLADE_QUERY_TERMS = 64

from e6_forward_codec_proto import load_queries, read_rss  # noqa: E402  (E1/E6 conventions)


def read_majflt() -> int:
    return int(Path("/proc/self/stat").read_text().split()[11])


def run_pass(idx, string_dtype, per_q_terms, label, warm_repeats, k_prime, prefloor):
    """release pages → (optional floor prefault) → cold pass → warm repeats.

    Returns (cell, per-query top-k'). When `prefloor` is true, the posting-list +
    doc-mapping floor is faulted in AFTER release_pages() and BEFORE the mj0
    baseline — the cold-pass majflt delta then charges ONLY the forward-codec
    faults, which is what the gate-c 0.55 bar models (E7 Fix #4). Default off
    preserves the pre-registered footing (majflt_cold includes the floor)."""
    released = idx.release_pages()
    assert released > 0, f"{label}: release_pages covered no ranges"
    prefloor_bytes = 0
    if prefloor:
        # prefloor=2 (E7 Fix #5B) also prefaults forward_offsets.bin — the
        # winner-id-resolution slab, symmetric in both layouts and not part of
        # the per-candidate codec read the gate-c bar models. prefloor=1 is the
        # Fix #4 footing (posting lists + doc mapping only), bit-unchanged.
        prefloor_bytes = idx.prefault_floor(include_forward_offsets=(prefloor >= 2))
        assert prefloor_bytes > 0, f"{label}: prefault_floor covered no ranges"
    mj0 = read_majflt()
    cold_ms, tops = [], []
    for terms in per_q_terms:
        qcomp = np.array(list(terms.keys()), dtype=string_dtype)
        qvals = np.array([float(v) for v in terms.values()], dtype=np.float32)
        t0 = time.perf_counter()
        res = idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                         k=k_prime, query_cut=len(terms), heap_factor=HEAP_FACTOR)
        cold_ms.append((time.perf_counter() - t0) * 1000)
        tops.append([d for (_q, _s, d) in res])
    mj_cold = read_majflt() - mj0
    warm_ms = []
    for terms in per_q_terms:
        qcomp = np.array(list(terms.keys()), dtype=string_dtype)
        qvals = np.array([float(v) for v in terms.values()], dtype=np.float32)
        reps = []
        for _ in range(warm_repeats):
            t0 = time.perf_counter()
            idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                       k=k_prime, query_cut=len(terms), heap_factor=HEAP_FACTOR)
            reps.append((time.perf_counter() - t0) * 1000)
        warm_ms.append(statistics.median(reps))
    return {
        "label": label,
        "cold_traverse_ms_p50": round(statistics.median(cold_ms), 2),
        "warm_traverse_ms_p50": round(statistics.median(warm_ms), 3),
        "warm_traverse_ms_mean": round(statistics.mean(warm_ms), 3),
        "majflt_cold_pass": mj_cold,
        "prefloor_bytes": prefloor_bytes,
    }, tops


def dir_bytes(d: Path) -> int:
    return sum(os.path.getsize(d / f) for f in os.listdir(d))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--f16-dir",
                    default="data/seismic_150m/index/plan01/global_shard0of8.mmap")
    ap.add_argument("--dv-dir",
                    default="data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.mmap")
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--k-prime", type=int, default=K_PRIME,
                    help="top-k' scored per query (default=%d = the E1/E6 recall-max "
                         "footing). Lower values are a DIFFERENT operating point, "
                         "reported as 'different footing', not a same-bar reclear."
                    % K_PRIME)
    ap.add_argument("--model-path", default="models/splade_onnx_fp16")
    ap.add_argument("--query-workload",
                    default=str(REPO / "data/eval_results/diverse_queries.json"))
    ap.add_argument("--result-file", default=None)
    ap.add_argument("--warm-repeats", type=int, default=WARM_REPEATS,
                    help="per-query warm-search reps that get medianed (p50). "
                         "Default=%d preserves the pre-registered footing; raising it "
                         "stabilizes the median without changing the bar." % WARM_REPEATS)
    ap.add_argument("--build-label", default="unspecified",
                    help="recorded in the result json 'build' block; tags this run's "
                         "build config for attribution across reclear arms.")
    args = ap.parse_args()
    assert args.queries <= 100, "audit rule: <=100 queries"

    # E7 Fix #4 (2026-07-03): floor prefault strips the constant posting-list +
    # doc-mapping floor from the cold-pass majflt delta so gate-c charges ONLY
    # forward-codec faults (what the 0.55 bar models). Env-gated; default off
    # preserves the pre-registered footing. See mmap_io.rs::prefault_floor.
    # E7 Fix #5B (2026-07-03): "2" additionally prefaults forward_offsets.bin
    # (the symmetric winner-id-resolution slab; completes the calibration).
    prefloor = int(os.environ.get("SFU_SEISMIC_PREFLOOR", "0") or 0)

    # torch import first — the peak-RSS moment (E6 ENOMEM lesson).
    from lib.opensearch_retriever import encode_splade

    import seismic
    string_dtype = seismic.get_seismic_string()
    rss_pre = read_rss()
    f16 = seismic.MmapSeismicIndex(args.f16_dir)
    dv = seismic.MmapSeismicIndex(args.dv_dir)
    assert f16.forward_format == "f16" and dv.forward_format == "dotvbyte_fixedu8", \
        (f16.forward_format, dv.forward_format)
    assert f16.len == dv.len and f16.nnz == dv.nnz, "doc/nnz cardinality mismatch"
    rss_loaded = read_rss()
    log.info("loaded f16 + dotvbyte twins: %d docs, rss=%s", f16.len, rss_loaded)

    queries = load_queries(args.queries, Path(args.query_workload))
    log.info("encoding %d queries...", len(queries))
    per_q_terms = []
    for q in queries:
        sparse = encode_splade(q, args.model_path)
        per_q_terms.append(dict(sorted(sparse.items(), key=lambda x: -x[1])[:SPLADE_QUERY_TERMS]))

    f16_cell, f16_tops = run_pass(f16, string_dtype, per_q_terms, "f16", args.warm_repeats, args.k_prime, prefloor)
    log.info("f16:      warm p50 %.2f ms, cold p50 %.0f ms, majflt %d",
             f16_cell["warm_traverse_ms_p50"], f16_cell["cold_traverse_ms_p50"],
             f16_cell["majflt_cold_pass"])
    dv_cell, dv_tops = run_pass(dv, string_dtype, per_q_terms, "dotvbyte", args.warm_repeats, args.k_prime, prefloor)
    log.info("dotvbyte: warm p50 %.2f ms, cold p50 %.0f ms, majflt %d",
             dv_cell["warm_traverse_ms_p50"], dv_cell["cold_traverse_ms_p50"],
             dv_cell["majflt_cold_pass"])

    ovs = [len(set(a[:OVERLAP_K]) & set(b[:OVERLAP_K])) / OVERLAP_K
           for a, b in zip(dv_tops, f16_tops)]
    ov10, ov10_min = statistics.mean(ovs), min(ovs)

    warm_ratio = dv_cell["warm_traverse_ms_p50"] / f16_cell["warm_traverse_ms_p50"]
    majflt_ratio = (dv_cell["majflt_cold_pass"] / f16_cell["majflt_cold_pass"]
                    if f16_cell["majflt_cold_pass"] else float("nan"))

    gates = {
        "a_parity": {"overlap@10_mean": round(ov10, 4), "overlap@10_min": round(ov10_min, 4),
                     "bar": ">= 0.99", "pass": ov10 >= 0.99},
        "b_latency": {"warm_p50_ratio": round(warm_ratio, 3), "bar": "<= 1.07",
                      "pass": warm_ratio <= 1.07},
        "c_pages": {"majflt_cold_ratio": round(majflt_ratio, 3), "bar": "<= 0.55",
                    "pass": majflt_ratio <= 0.55},
    }
    verdict = ("E7_ALL_GATES_PASS" if all(g["pass"] for g in gates.values())
               else "E7_GATE_FAIL: " + ",".join(k for k, g in gates.items() if not g["pass"]))

    f16_b, dv_b = dir_bytes(Path(args.f16_dir)), dir_bytes(Path(args.dv_dir))
    summary = {
        "meta": {
            "purpose": "E7 implementation gates — dotvbyte compressed forward vs f16, "
                       "10_FORWARD_COMPRESSION_DESIGN.md §5",
            "measured_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
            "f16_dir": args.f16_dir, "dv_dir": args.dv_dir,
            "n_queries": len(queries), "k_prime": args.k_prime, "heap_factor": HEAP_FACTOR,
            "warm_repeats": WARM_REPEATS,
            "params_note": "recall-max: all terms passed, query_cut=all, k'=200 "
                           "(the E1/E6 baseline convention)",
            "rss": {"pre_load": rss_pre, "post_load": rss_loaded, "end": read_rss()},
            "build_label": args.build_label,
            "prefloor_on": prefloor,
        },
        "on_disk_bytes": {"f16": f16_b, "dotvbyte": dv_b,
                          "ratio": round(f16_b / dv_b, 3)},
        "f16": f16_cell,
        "dotvbyte": dv_cell,
        "gates": gates,
        "verdict": verdict,
    }
    rpath = (Path(args.result_file) if args.result_file
             else REPO / f"data/eval_results/seismic_e7_dotvbyte_gates_{time.strftime('%Y%m%d_%H%M')}.json")
    json.dump(summary, open(rpath, "w"), indent=2)
    log.info("wrote %s", rpath)
    print(json.dumps({"verdict": verdict, "gates": gates,
                      "on_disk_ratio": summary["on_disk_bytes"]["ratio"],
                      "result_file": str(rpath)}))


if __name__ == "__main__":
    main()
