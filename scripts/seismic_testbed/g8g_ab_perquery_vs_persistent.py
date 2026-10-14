#!/usr/bin/env python3
"""G8g-AB: same-run A/B — per-query vs persistent ThreadPoolExecutor fan-out.

The first G8g gate run (g8g_persistent_executor_gate.py, 2026-07-08) FAILED
its pre-registered bar (sched_overhead_ms_p50 10.26, bar < 5) and its
between-run comparison to G8f was confounded: today's per-shard walls ran ~2x
G8f's (max-shard 12.25 vs 6.26 ms at the same k'=100), so the environment
drifted between runs. This script removes the confound: BOTH fan-out arms run
in the SAME process over the SAME warm page cache, interleaved per query —
  A: per-query executor (the pre-fix `_fan_out`: fresh ThreadPoolExecutor
     constructed per call, replicated locally), and
  B: persistent executor (the shipped `be._fan_out`, pool built in __init__).
Everything else identical (same encoded qvecs, served defaults k'=100,
heap_factor=0.8, top_k=50, same timed callable, same `_merge_topk`).

The A-minus-B traverse p50 delta is THE measured efficacy of the persistent
executor. No pass/fail bar — this is the attribution measurement the doc 08
§A4 `*est.* -20 ms` claim gets replaced with. Rule Zero: read-only.
"""
import concurrent.futures as cf
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from e6_forward_codec_proto import load_queries  # noqa: E402
from g8f_shardmerge_profile_kprime import HEAP_FACTOR, TOP_K, p50, summarize  # noqa: E402

import lib.opensearch_retriever  # noqa: F401,E402  torch first (ENOMEM lesson)
from lib.thinclient.sharded_seismic_backend import (  # noqa: E402
    ParallelSeismicBackend, _load_manifest, _merge_topk, _prepare_query)

MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_dotvbyte.json"
N_QUERIES = 100
WARM_PASSES = 3
RESULT = REPO / f"data/eval_results/g8g_ab_perquery_vs_persistent_{time.strftime('%Y%m%d')}.json"


def perquery_fan_out(be, fn):
    """The PRE-FIX `ParallelSeismicBackend._fan_out` verbatim (fresh executor
    per call) — arm A's fan-out."""
    with cf.ThreadPoolExecutor(max_workers=len(be.shards)) as ex:
        return list(ex.map(fn, be.shards))


def instrumented(be, q, fan_out):
    """g8f's instrumented_search with the fan-out injectable."""
    qcomp, qvals, qc, kp = _prepare_query(q, TOP_K, be._string_dtype, None, None)

    def timed_one(idx):
        t = time.perf_counter()
        r = idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                       k=kp, query_cut=qc, heap_factor=HEAP_FACTOR)
        return (time.perf_counter() - t) * 1000.0, r

    t0 = time.perf_counter()
    walls_results = fan_out(timed_one)
    fanout_ms = (time.perf_counter() - t0) * 1000.0
    shard_ms = [w for (w, _r) in walls_results]
    t0 = time.perf_counter()
    out = _merge_topk([r for (_w, r) in walls_results], TOP_K)
    merge_ms = (time.perf_counter() - t0) * 1000.0
    return out, {"shard_ms": shard_ms, "fanout_ms": fanout_ms, "merge_ms": merge_ms,
                 "traverse_ms": fanout_ms + merge_ms}


def main():
    t0 = time.time()
    queries = load_queries(N_QUERIES, REPO / "data/eval_results/diverse_queries.json")
    paths = _load_manifest(str(MANIFEST), load_mode="mmap")
    be = ParallelSeismicBackend(paths, load_mode="mmap")
    n_shards = len(be.shards)
    arms = {"A_perquery": lambda fn: perquery_fan_out(be, fn),
            "B_persistent": be._fan_out}

    encoded = [be.encode_query(q) for q in queries]
    assert all(encoded), "a query failed to encode"

    print("warm-up pass (unrecorded, both arms)...", flush=True)
    for q in encoded:
        for fan in arms.values():
            instrumented(be, q, fan)

    rows = {a: [] for a in arms}
    mismatches = 0
    for p in range(1, WARM_PASSES + 1):
        for q in encoded:
            outs = {}
            # interleave arms per query so drift hits both equally
            for arm, fan in arms.items():
                out, row = instrumented(be, q, fan)
                rows[arm].append(row)
                outs[arm] = out
            if outs["A_perquery"] != outs["B_persistent"]:
                mismatches += 1
        print(f"pass {p} done", flush=True)

    summary = {arm: summarize(rows[arm], n_shards) for arm in arms}
    delta = {k: round(summary["A_perquery"][k] - summary["B_persistent"][k], 2)
             for k in ("traverse_ms_p50", "fanout_ms_p50", "sched_overhead_ms_p50",
                       "max_shard_ms_p50", "mean_shard_ms_p50")}
    # paired per-row traverse delta (rows are aligned: same query, same pass)
    paired = [a["traverse_ms"] - b["traverse_ms"]
              for a, b in zip(rows["A_perquery"], rows["B_persistent"])]
    delta["traverse_ms_paired_delta_p50"] = round(statistics.median(paired), 2)

    res = {"meta": {"date": time.strftime("%Y-%m-%d"),
                    "script": "scripts/seismic_testbed/g8g_ab_perquery_vs_persistent.py",
                    "backend": "ParallelSeismicBackend(load_mode=mmap); arm A = pre-fix "
                               "per-query executor replica, arm B = shipped persistent "
                               "executor; interleaved per query, same process",
                    "manifest": str(MANIFEST.relative_to(REPO)),
                    "n_queries": N_QUERIES, "top_k": TOP_K,
                    "k_prime": "served default max(2*top_k,100) = 100",
                    "heap_factor": HEAP_FACTOR,
                    "warm_passes_recorded": WARM_PASSES,
                    "environment": "devcontainer (16 cores, drvfs); warm-only",
                    "purpose": "unconfounded efficacy of the persistent executor "
                               "(A minus B = what per-query pool construction cost)"},
           "identity_across_arms": {"n_paired": len(paired) // WARM_PASSES,
                                    "mismatches": mismatches},
           "profile": summary,
           "delta_A_minus_B": delta}
    res["meta"]["wall_seconds"] = round(time.time() - t0, 1)
    RESULT.write_text(json.dumps(res, indent=2))
    print(json.dumps(summary, indent=1))
    print(json.dumps(delta))
    print(f"result -> {RESULT}")


if __name__ == "__main__":
    main()
