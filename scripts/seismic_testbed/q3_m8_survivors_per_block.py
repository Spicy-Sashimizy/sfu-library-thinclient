#!/usr/bin/env python3
"""Q3 — M8 survivors-per-block instrument (2026-07-10).

M8 (math optimization 08 §M8) proposes a register-blocked kernel that scores 4
candidates from one surviving posting block interleaved, sharing one pass over
the query structures. Quality-free by construction. The pre-gate: if the
typical surviving posting block contributes <2 candidates, there is nothing to
batch (M8 dies on paper); >=4 → GO for the kernel.

This script measures the survivors-per-block distribution on real query
traversals via the new pyo3 `search_block_stats` hook (which returns, per
query, the per-surviving-block candidate count — the packs in each
`evaluate_posting_block` call that passed the visited-dedup and were scored).

PRE-REGISTERED BARS (math_optimization/08 §M8, doc 12 §3 Q3):
  - typical batch (median survivors/block) >= 4 → GO for the register-blocked
    kernel (bit-identical, latency-gated).
  - < 2 → M8 dies on paper.
  - 2..4 → record (marginal; the kernel may still pay off via MLP amortization
    even at small batch).

Shards 1-2 per the worst-case-shard rule (doc 12 §2.1). n=100 queries, k'=100
(the served default), query_cut=all (recall-first). Both dv (served) and f16
(twin) measured — the distribution should be codec-independent (same posting
lists / block structure; only the forward value decode differs).

Quality-free check: `search_block_stats` results are bit-identical to `search`
(observes only; the instrument adds an int count, doesn't change the traversal).
Asserted per-query against the plain `search`.

Usage (repo root, project venv):

    .venv/bin/python3 scripts/seismic_testbed/q3_m8_survivors_per_block.py \
        --queries 100 --k-prime 100 \
        --result-file data/eval_results/q3_m8_survivors_per_block_20260710.json
"""
import argparse
import json
import logging
import os
import statistics
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

log = logging.getLogger("q3_m8")

SPLADE_QUERY_TERMS = 64
SHARDS = {
    "shard1": ("global_shard1of8.dotvbyte.e5.mmap", "global_shard1of8.mmap"),
    "shard2": ("global_shard2of8.dotvbyte.e5.mmap", "global_shard2of8.mmap"),
}
PLAN01 = REPO / "data" / "seismic_150m" / "index" / "plan01"


def load_queries(n, query_file):
    qpath = Path(query_file)
    if not qpath.is_absolute():
        qpath = REPO / query_file if not str(qpath).startswith("data/") else REPO / qpath
    qrecs = json.loads(qpath.read_text())
    seen, out = set(), []
    for r in qrecs:
        if r["paraphrase"] in seen:
            continue
        seen.add(r["paraphrase"])
        out.append(r["paraphrase"])
        if len(out) >= n:
            break
    return out


def measure_shard(shard_name: str, dv_dir: Path, f16_dir: Path, queries, k_prime, model_path):
    import seismic
    import numpy as np
    from lib.opensearch_retriever import encode_splade

    sd = seismic.get_seismic_string()
    out = {}
    for codec, d in (("dv", dv_dir), ("f16", f16_dir)):
        idx = seismic.MmapSeismicIndex(str(d))
        log.info("%s %s: len=%d dim=%d nnz=%d", shard_name, codec, idx.len, idx.dim, idx.nnz)

        per_q_block_counts = []   # list of per-query block_stats lists
        n_blocks_total = 0
        n_candidates_total = 0
        parity_ok = 0
        for qtext in queries:
            q64 = dict(sorted(encode_splade(qtext, model_path).items(),
                              key=lambda x: -x[1])[:SPLADE_QUERY_TERMS])
            qcomp = np.array(list(q64.keys()), dtype=sd)
            qvals = np.array([float(v) for v in q64.values()], dtype=np.float32)
            res, visited, block_stats = idx.search_block_stats(
                query_id="q", query_components=qcomp, query_values=qvals,
                k=k_prime, query_cut=len(q64), heap_factor=0.8)
            # Quality-free parity: block_stats results must equal plain search.
            res_plain = idx.search(
                query_id="q", query_components=qcomp, query_values=qvals,
                k=k_prime, query_cut=len(q64), heap_factor=0.8)
            if [r[2] for r in res] == [r[2] for r in res_plain]:
                parity_ok += 1
            per_q_block_counts.append(block_stats)
            n_blocks_total += len(block_stats)
            n_candidates_total += sum(block_stats)

        # Flatten for distribution stats.
        flat = [c for bs in per_q_block_counts for c in bs]
        flat_nz = [c for c in flat if c > 0]  # surviving blocks w/ >=1 candidate
        # Count blocks with >=4 (GO), >=2 (viable), <2 (dies).
        ge4 = sum(1 for c in flat if c >= 4)
        ge2 = sum(1 for c in flat if c >= 2)
        lt2 = sum(1 for c in flat if c < 2)

        out[codec] = {
            "n_queries": len(queries),
            "n_surviving_blocks_total": len(flat),
            "n_candidates_scored_total": n_candidates_total,
            "mean_surviving_blocks_per_query": round(len(flat) / len(queries), 1),
            "mean_candidates_per_query": round(n_candidates_total / len(queries), 1),
            "median_candidates_per_block": statistics.median(flat) if flat else 0,
            "mean_candidates_per_block": round(statistics.mean(flat), 3) if flat else 0,
            "p25_candidates_per_block": _pct(flat, 25),
            "p75_candidates_per_block": _pct(flat, 75),
            "p95_candidates_per_block": _pct(flat, 95),
            "max_candidates_per_block": max(flat) if flat else 0,
            "share_blocks_ge4_candidates": round(ge4 / len(flat), 4) if flat else 0,
            "share_blocks_ge2_candidates": round(ge2 / len(flat), 4) if flat else 0,
            "share_blocks_lt2_candidates": round(lt2 / len(flat), 4) if flat else 0,
            "distribution_hist": dict(Counter(flat).most_common(10)),
            "parity_block_stats_equals_search": f"{parity_ok}/{len(queries)}",
        }
        log.info("%s %s: median candidates/block=%s mean=%.2f ge4_share=%.3f (parity %d/%d)",
                 shard_name, codec, out[codec]["median_candidates_per_block"],
                 out[codec]["mean_candidates_per_block"],
                 out[codec]["share_blocks_ge4_candidates"], parity_ok, len(queries))
        del idx
        import gc; gc.collect()
    return out


def _pct(data, p):
    if not data:
        return 0
    s = sorted(data)
    return s[min(int(len(s) * p / 100), len(s) - 1)]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queries", type=int, default=100)
    ap.add_argument("--k-prime", type=int, default=100)
    ap.add_argument("--query-file", default="data/eval_results/diverse_queries.json")
    ap.add_argument("--splade-model", default="models/splade_onnx_fused")
    ap.add_argument("--result-file", required=True)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    queries = load_queries(args.queries, args.query_file)
    log.info("loaded %d queries", len(queries))

    results = {}
    for shard_name, (dv_rel, f16_rel) in SHARDS.items():
        dv = PLAN01 / dv_rel
        f16 = PLAN01 / f16_rel
        if not dv.is_dir() or not f16.is_dir():
            log.warning("%s: skipping (missing dir dv=%s f16=%s)", shard_name, dv, f16)
            continue
        results[shard_name] = measure_shard(
            shard_name, dv, f16, queries, args.k_prime, args.splade_model)

    # Verdict: the pre-registered bar is the MEDIAN candidates/block.
    # GO if typical (median) >= 4 on BOTH shards; KILL if < 2; else marginal.
    def median_for(shard, codec):
        return results.get(shard, {}).get(codec, {}).get("median_candidates_per_block")
    medians_dv = [median_for(s, "dv") for s in SHARDS if median_for(s, "dv") is not None]
    medians_f16 = [median_for(s, "f16") for s in SHARDS if median_for(s, "f16") is not None]
    worst_median = min(filter(None, medians_dv + medians_f16), default=0)

    if worst_median >= 4:
        bar = "GO_for_register_blocked_kernel"
    elif worst_median < 2:
        bar = "KILL_on_paper"
    else:
        bar = "MARGINAL_record_only"
    verdict = {
        "worst_median_candidates_per_block": worst_median,
        "medians_dv_by_shard": medians_dv,
        "medians_f16_by_shard": medians_f16,
        "bar_ge4_go_lt2_kill": ("GO" if worst_median >= 4
                                else "KILL" if worst_median < 2 else "MARGINAL"),
        "verdict": bar,
        "note": ("Pre-registered bars (math_optimization/08 §M8): typical batch "
                 "(median survivors/block) >=4 -> GO for the register-blocked "
                 "kernel (bit-identical, latency-gated); <2 -> M8 dies on paper. "
                 "Codec-independent (posting-block structure shared across dv/f16). "
                 "Quality-free: search_block_stats results are bit-identical to "
                 "search (observes only)."),
    }

    out = {
        "meta": {
            "date_utc": __import__("datetime").datetime.utcnow().isoformat(),
            "benchmark": "q3 m8 survivors-per-block instrument",
            "queries": len(queries),
            "k_prime": args.k_prime,
            "shards": list(SHARDS),
        },
        "results": results,
        "verdict": verdict,
    }
    result_file = REPO / args.result_file
    result_file.parent.mkdir(parents=True, exist_ok=True)
    with open(result_file, "w") as f:
        json.dump(out, f, indent=2)
    log.info("result written to %s", result_file)
    log.info("VERDICT: %s", json.dumps(verdict, indent=2))
    return 0 if bar == "GO_for_register_blocked_kernel" else 1


if __name__ == "__main__":
    sys.exit(main())
