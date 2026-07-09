#!/usr/bin/env python3
"""G8e: encode-vs-traverse split of the SERVED federated dv path (doc 08 §A4).

Answers the un-attributed question left open since G8b: of the ~65 ms
full-corpus warm p50, how much is SPLADE query encode vs the 8-shard fan-out
traversal (traverse_ms includes fan-out + merge)? G8b timed only the total;
its warm min (39.1 ms) ≈ the known encode p50 (~39-41 ms), suggesting encode
is half or more of every warm query — this run measures it directly on the
promoted serving path (ParallelSeismicBackend, dv manifest, load_mode=mmap,
`search_with_timing`).

Conventions: G8b (40 diverse queries, top_k=50, served defaults for
query_cut/heap_factor/k'; 1 cold + 3 warm passes). Container run — absolute
latencies are container-grade (drvfs, 16 cores), the SPLIT is the deliverable.
Rule Zero: read-only over shard dirs.
"""
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from e6_forward_codec_proto import load_queries, read_rss  # noqa: E402

import lib.opensearch_retriever  # noqa: F401,E402  torch first (ENOMEM lesson)
from lib.thinclient.sharded_seismic_backend import (  # noqa: E402
    ParallelSeismicBackend, _load_manifest)

MANIFEST = REPO / "data/eval_results/seismic_c25_shards_150m_mmap_dotvbyte.json"
N_QUERIES = 40
TOP_K = 50
WARM_PASSES = 3
RESULT = REPO / f"data/eval_results/g8e_encode_traverse_split_{time.strftime('%Y%m%d')}.json"


def pctl(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def summarize(rows):
    enc = [r[0] for r in rows]
    trv = [r[1] for r in rows]
    tot = [r[0] + r[1] for r in rows]
    return {"encode_ms": {"p50": round(statistics.median(enc), 2),
                          "p95": round(pctl(enc, 95), 2)},
            "traverse_ms": {"p50": round(statistics.median(trv), 2),
                            "p95": round(pctl(trv, 95), 2)},
            "total_ms": {"p50": round(statistics.median(tot), 2),
                         "p95": round(pctl(tot, 95), 2)},
            "encode_share_of_total_p50": round(
                statistics.median(enc) / statistics.median(tot), 3),
            "n": len(rows)}


def main():
    t0 = time.time()
    queries = load_queries(N_QUERIES, REPO / "data/eval_results/diverse_queries.json")
    paths = _load_manifest(str(MANIFEST), load_mode="mmap")
    rss0 = read_rss()
    be = ParallelSeismicBackend(paths, load_mode="mmap")

    passes = []
    for p in range(1 + WARM_PASSES):
        rows = []
        for q in queries:
            _res, enc_ms, trv_ms = be.search_with_timing(q, TOP_K)
            rows.append((enc_ms, trv_ms))
        passes.append(summarize(rows))
        label = "cold(as-found)" if p == 0 else f"warm{p}"
        print(f"pass {p} [{label}]: {json.dumps(passes[-1])}", flush=True)

    warm_rows = passes[1:]
    warm = {"encode_ms_p50": round(statistics.median(
                [w["encode_ms"]["p50"] for w in warm_rows]), 2),
            "traverse_ms_p50": round(statistics.median(
                [w["traverse_ms"]["p50"] for w in warm_rows]), 2),
            "total_ms_p50": round(statistics.median(
                [w["total_ms"]["p50"] for w in warm_rows]), 2)}
    warm["encode_share"] = round(warm["encode_ms_p50"] / warm["total_ms_p50"], 3)

    res = {"meta": {"date": time.strftime("%Y-%m-%d"),
                    "script": "scripts/seismic_testbed/g8e_encode_traverse_split.py",
                    "backend": "ParallelSeismicBackend(load_mode=mmap) via search_with_timing",
                    "manifest": str(MANIFEST.relative_to(REPO)),
                    "n_queries": N_QUERIES, "top_k": TOP_K,
                    "passes": 1 + WARM_PASSES,
                    "environment": "devcontainer (16 cores, drvfs) — split is the "
                                   "deliverable, absolute ms are container-grade",
                    "cold_note": "pass 0 is as-found page-cache state, not a "
                                 "drop_caches cold",
                    "wall_seconds": None},
           "rss_before": rss0, "rss_after_load": read_rss(),
           "per_pass": passes, "warm_summary": warm}
    res["meta"]["wall_seconds"] = round(time.time() - t0, 1)
    RESULT.write_text(json.dumps(res, indent=2))
    print(json.dumps(warm))
    print(f"result -> {RESULT}")


if __name__ == "__main__":
    main()
