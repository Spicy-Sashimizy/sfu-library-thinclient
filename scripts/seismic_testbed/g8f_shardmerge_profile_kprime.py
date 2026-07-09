#!/usr/bin/env python3
"""G8f: (a) per-shard vs merge attribution inside the served traverse leg;
(b) the federated-level k'=200 vs k'=100 gate doc 09 §4 left open.

Follow-up to G8e (2026-07-08): warm p50 64.2 ms = encode 20.0 (31%) +
traverse 43.7 (69%), while a single shard's warm traverse is ~3-6 ms — this
run attributes the 43.7 ms: per-shard search walls (timed inside the fan-out
threads), fan-out wall (max-shard + scheduling), and `_merge_topk` wall.

Second job: E1 measured k' 200→100 recall-safe (overlap@10 0.995) + 1.41×
on ONE shard at n=40 — not promotable (leg-overlap only, n<100). This run
measures the MERGED federated top-k overlap between k'=200 and k'=100 arms
at n=100 (standing rule: n>=100 for any promotable overlap gate), plus the
federated latency effect.

Method: instrumented replica of `search_encoded` built from the backend's own
pure parts (`_prepare_query` → `be._fan_out(timed callable)` → `_merge_topk`)
— arithmetic identical to serving, only timers added. Queries pre-encoded once
(encode split already measured, G8e). Warm-up pass unrecorded, then 3 recorded
warm passes per arm. top_k=50, query_cut=all, heap_factor=0.8 (served shape).

Bars (pre-registered): merged overlap@10 mean (k'=100 vs k'=200 reference)
>= 0.99 -> FLIP the served default `max(top_k*4, top_k)` -> `max(top_k*2, 100)`
(k'=100 at the measured top_k=50 point; the floor of 100 keeps small-top_k
requests at or above their current candidate depth). < 0.99 -> keep 4x,
record, stop. Rule Zero: read-only over shard dirs.
"""
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from e6_forward_codec_proto import load_queries  # noqa: E402

import lib.opensearch_retriever  # noqa: F401,E402  torch first (ENOMEM lesson)
from lib.thinclient.sharded_seismic_backend import (  # noqa: E402
    ParallelSeismicBackend, _load_manifest, _merge_topk, _prepare_query)

MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_dotvbyte.json"
N_QUERIES = 100
TOP_K = 50
HEAP_FACTOR = 0.8
ARMS = {"k200": 200, "k100": 100}   # k200 = served baseline (4x50)
WARM_PASSES = 3
RESULT = REPO / f"data/eval_results/g8f_shardmerge_profile_kprime_{time.strftime('%Y%m%d')}.json"


def instrumented_search(be, q, k_prime):
    """search_encoded with timers; returns (top_k results, row dict)."""
    qcomp, qvals, qc, kp = _prepare_query(q, TOP_K, be._string_dtype, None, k_prime)

    def timed_one(idx):
        t = time.perf_counter()
        r = idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                       k=kp, query_cut=qc, heap_factor=HEAP_FACTOR)
        return (time.perf_counter() - t) * 1000.0, r

    t0 = time.perf_counter()
    walls_results = be._fan_out(timed_one)
    fanout_ms = (time.perf_counter() - t0) * 1000.0
    shard_ms = [w for (w, _r) in walls_results]
    t0 = time.perf_counter()
    out = _merge_topk([r for (_w, r) in walls_results], TOP_K)
    merge_ms = (time.perf_counter() - t0) * 1000.0
    row = {"shard_ms": shard_ms, "fanout_ms": fanout_ms, "merge_ms": merge_ms,
           "traverse_ms": fanout_ms + merge_ms}
    return out, row


def p50(xs):
    return round(statistics.median(xs), 2)


def summarize(rows, n_shards):
    return {"traverse_ms_p50": p50([r["traverse_ms"] for r in rows]),
            "fanout_ms_p50": p50([r["fanout_ms"] for r in rows]),
            "max_shard_ms_p50": p50([max(r["shard_ms"]) for r in rows]),
            "mean_shard_ms_p50": p50([statistics.mean(r["shard_ms"]) for r in rows]),
            "sched_overhead_ms_p50": p50([r["fanout_ms"] - max(r["shard_ms"])
                                          for r in rows]),
            "merge_ms_p50": p50([r["merge_ms"] for r in rows]),
            "per_shard_ms_p50": [p50([r["shard_ms"][i] for r in rows])
                                 for i in range(n_shards)],
            "n_rows": len(rows)}


def main():
    t0 = time.time()
    queries = load_queries(N_QUERIES, REPO / "data/eval_results/diverse_queries.json")
    paths = _load_manifest(str(MANIFEST), load_mode="mmap")
    be = ParallelSeismicBackend(paths, load_mode="mmap")
    n_shards = len(be.shards)

    encoded = [be.encode_query(q) for q in queries]
    assert all(encoded), "a query failed to encode"

    print("warm-up pass (unrecorded)...", flush=True)
    for q in encoded:
        instrumented_search(be, q, ARMS["k200"])

    rows = {a: [] for a in ARMS}
    tops = {a: [] for a in ARMS}   # merged results from the first recorded pass
    for p in range(1, WARM_PASSES + 1):
        for arm, kp in ARMS.items():
            for qi, q in enumerate(encoded):
                out, row = instrumented_search(be, q, kp)
                rows[arm].append(row)
                if p == 1:
                    tops[arm].append([d for (d, _s) in out])
        print(f"pass {p} done", flush=True)

    summary = {arm: summarize(rows[arm], n_shards) for arm in ARMS}
    ov10 = [len(set(a[:10]) & set(b[:10])) / 10
            for a, b in zip(tops["k100"], tops["k200"])]
    ov50 = [len(set(a[:50]) & set(b[:50])) / 50
            for a, b in zip(tops["k100"], tops["k200"])]
    overlap = {"overlap@10_mean": round(statistics.mean(ov10), 4),
               "overlap@10_min": round(min(ov10), 4),
               "overlap@50_mean": round(statistics.mean(ov50), 4),
               "n_queries": N_QUERIES}
    speedup = round(summary["k200"]["traverse_ms_p50"]
                    / summary["k100"]["traverse_ms_p50"], 3)
    flip = overlap["overlap@10_mean"] >= 0.99

    res = {"meta": {"date": time.strftime("%Y-%m-%d"),
                    "script": "scripts/seismic_testbed/g8f_shardmerge_profile_kprime.py",
                    "backend": "ParallelSeismicBackend(load_mode=mmap), instrumented "
                               "replica of search_encoded (same pure parts)",
                    "manifest": str(MANIFEST.relative_to(REPO)),
                    "n_queries": N_QUERIES, "top_k": TOP_K,
                    "heap_factor": HEAP_FACTOR, "arms": ARMS,
                    "warm_passes_recorded": WARM_PASSES,
                    "environment": "devcontainer (16 cores, drvfs); warm-only",
                    "bars": "overlap@10 mean (k100 merged vs k200 merged) >=0.99 "
                            "-> flip served default to max(top_k*2, 100)"},
           "profile": summary,
           "kprime_gate": {"overlap": overlap,
                           "traverse_speedup_p50_k200_over_k100": speedup,
                           "flip_verdict": "FLIP" if flip else "KEEP_4X"}}
    res["meta"]["wall_seconds"] = round(time.time() - t0, 1)
    RESULT.write_text(json.dumps(res, indent=2))
    print(json.dumps(summary, indent=1))
    print(json.dumps(res["kprime_gate"]))
    print(f"result -> {RESULT}")


if __name__ == "__main__":
    main()
