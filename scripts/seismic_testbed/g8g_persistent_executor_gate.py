#!/usr/bin/env python3
"""G8g: persistent-executor gate (doc 08 §A4 follow-up, 2026-07-08).

G8f attributed the served traverse leg: at k'=200, 38.3 ms p50 = max-shard
10.1 + scheduling overhead 27.7 + merge 0.26 — the scheduling term being
`ParallelSeismicBackend._fan_out` constructing a fresh `ThreadPoolExecutor`
per query (8 thread spawns/teardowns per search). The fix under gate: a
persistent per-backend executor created once in `__init__` and reused by
every `_fan_out`.

Three legs, all on the promoted served path (dv manifest, load_mode=mmap,
served defaults k'=max(2*top_k,100)=100, heap_factor=0.8, top_k=50):

  (a) Result identity, n=100 — the served `search_encoded` (persistent-
      executor fan-out) must return a merged top-50 BIT-IDENTICAL to a
      serial per-shard loop over the same shards + the same `_merge_topk`.
      Real-corpus complement to the synth-scale T1 suite.
  (b) G8f instrumented profile (identical arithmetic — imports G8f's
      `instrumented_search`/`summarize`), 3 warm passes, n=100: expect
      `sched_overhead_ms_p50` to collapse from 27.7 ms.
  (c) G8e end-to-end encode/traverse split via `search_with_timing`,
      3 warm passes: the headline served warm p50 to compare against
      G8e's 64.2 ms (measured at the pre-flip k'=200 default).

Bars (pre-registered): (a) 100/100 identical; (b) sched_overhead_ms_p50
< 5 ms. Comparison baselines: G8f k100 arm traverse 26.0 ms p50 (per-query
executor, same k'=100), G8e total 64.2 ms (k'=200 era).
Rule Zero: read-only over shard dirs.
"""
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from e6_forward_codec_proto import load_queries  # noqa: E402
from g8f_shardmerge_profile_kprime import (  # noqa: E402
    HEAP_FACTOR, TOP_K, instrumented_search, p50, summarize)

import lib.opensearch_retriever  # noqa: F401,E402  torch first (ENOMEM lesson)
from lib.thinclient.sharded_seismic_backend import (  # noqa: E402
    ParallelSeismicBackend, _load_manifest, _merge_topk, _prepare_query)

MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_dotvbyte.json"
N_QUERIES = 100
WARM_PASSES = 3
RESULT = REPO / f"data/eval_results/g8g_persistent_executor_gate_{time.strftime('%Y%m%d')}.json"


def serial_reference(be, q):
    """Serial per-shard loop + the same shared `_merge_topk`, served defaults —
    the executor-free reference for the identity leg."""
    qcomp, qvals, qc, kp = _prepare_query(q, TOP_K, be._string_dtype, None, None)
    per_shard = [idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                            k=kp, query_cut=qc, heap_factor=HEAP_FACTOR)
                 for idx in be.shards]
    return _merge_topk(per_shard, TOP_K)


def main():
    t0 = time.time()
    queries = load_queries(N_QUERIES, REPO / "data/eval_results/diverse_queries.json")
    paths = _load_manifest(str(MANIFEST), load_mode="mmap")
    be = ParallelSeismicBackend(paths, load_mode="mmap")
    n_shards = len(be.shards)

    encoded = [be.encode_query(q) for q in queries]
    assert all(encoded), "a query failed to encode"

    # (a) identity: served fan-out vs serial reference, n=100
    mismatches = 0
    for q in encoded:
        if be.search_encoded(q, TOP_K) != serial_reference(be, q):
            mismatches += 1
    identity = {"n_queries": N_QUERIES, "mismatches": mismatches,
                "verdict": "IDENTICAL" if mismatches == 0 else "MISMATCH"}
    print(f"identity: {json.dumps(identity)}", flush=True)

    # (b) G8f-identical instrumented profile at the served default k' (=100)
    print("warm-up pass (unrecorded)...", flush=True)
    for q in encoded:
        instrumented_search(be, q, None)
    rows = []
    for p in range(1, WARM_PASSES + 1):
        for q in encoded:
            _out, row = instrumented_search(be, q, None)
            rows.append(row)
        print(f"profile pass {p} done", flush=True)
    profile = summarize(rows, n_shards)
    print(json.dumps(profile, indent=1), flush=True)

    # (c) G8e end-to-end split (encode + traverse) via search_with_timing
    e2e = []
    for p in range(1, WARM_PASSES + 1):
        for q in queries:
            _res, enc_ms, trv_ms = be.search_with_timing(q, TOP_K)
            e2e.append((enc_ms, trv_ms))
        print(f"e2e pass {p} done", flush=True)
    warm = {"encode_ms_p50": p50([r[0] for r in e2e]),
            "traverse_ms_p50": p50([r[1] for r in e2e]),
            "total_ms_p50": p50([r[0] + r[1] for r in e2e]),
            "total_ms_p95": round(sorted(r[0] + r[1] for r in e2e)
                                  [int(round(0.95 * (len(e2e) - 1)))], 2)}
    warm["encode_share"] = round(warm["encode_ms_p50"] / warm["total_ms_p50"], 3)

    gate_pass = mismatches == 0 and profile["sched_overhead_ms_p50"] < 5.0
    res = {"meta": {"date": time.strftime("%Y-%m-%d"),
                    "script": "scripts/seismic_testbed/g8g_persistent_executor_gate.py",
                    "backend": "ParallelSeismicBackend(load_mode=mmap), persistent "
                               "per-backend executor (this gate's change)",
                    "manifest": str(MANIFEST.relative_to(REPO)),
                    "n_queries": N_QUERIES, "top_k": TOP_K,
                    "k_prime": "served default max(2*top_k,100) = 100",
                    "heap_factor": HEAP_FACTOR,
                    "warm_passes_recorded": WARM_PASSES,
                    "environment": "devcontainer (16 cores, drvfs); warm-only",
                    "baselines": {"g8f_k100_traverse_ms_p50": 26.0,
                                  "g8f_k200_sched_overhead_ms_p50": 27.7,
                                  "g8e_total_ms_p50_at_k200": 64.2},
                    "bars": "identity 100/100 AND sched_overhead_ms_p50 < 5"},
           "identity": identity,
           "profile": profile,
           "warm_e2e": warm,
           "gate_verdict": "PASS" if gate_pass else "FAIL"}
    res["meta"]["wall_seconds"] = round(time.time() - t0, 1)
    RESULT.write_text(json.dumps(res, indent=2))
    print(json.dumps(warm))
    print(f"gate_verdict: {res['gate_verdict']}")
    print(f"result -> {RESULT}")


if __name__ == "__main__":
    main()
