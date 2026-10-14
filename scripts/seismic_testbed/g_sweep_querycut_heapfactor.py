#!/usr/bin/env python3
"""SEISMIC testbed — §C1 sweep: query_cut × heap_factor (FREE latency lever).

`docs/seismic_150m_testbed/08_LATENCY_RESEARCH.md` §C1 (the prioritized next
step #3): the served SEISMIC backend runs **all 64 query terms**
(`query_cut=len(tokens)`) + `heap_factor=0.8` — recall-first while G2 was open.
SEISMIC's MS MARCO best-configs use a *small* `query_cut` and lower
`heap_factor` for big latency wins at modest recall cost. This script sweeps
`query_cut ∈ {10,15,20}` × `heap_factor ∈ {0.6,0.7,0.8}` (+ the all-terms/
hf=0.8 baseline reference) and records the **latency-vs-overlap@10 Pareto** —
pure query-time knobs, zero rebuild, zero extra RAM.

**Why this is free + clean (no hardware gate):** absolute latency is
swap-confounded on the G8 box, but overlap@10-vs-baseline and the
encode-vs-traverse *split* are not. So we stage the Pareto now and pick a config
when a real (no-swap) host appears. The baseline is the recall-maximizing run
(all-terms, hf=0.8); each cell's overlap@10 is its top-10 agreement with the
baseline — a self-relative recall measure, NOT vs a live Qdrant (which isn't
running here and isn't needed for the lever study).

**Encode/traverse split (§A4, shipped efce80e):** per cell we time the warm
`encode_query` (SPLADE ONNX fp16) and the traversal SEPARATELY (the §D suspect
— the encoder, not the fan-out, is the warm latency mass). Warm encode is ~17 ms
at fp16 on this box; traversal is ~1.7–8.3 ms. The cold model load (~76 s on
this box) is amortized by a one-query warmup before timing any cell.

Run from repo root (project venv):

    .venv/bin/python3 scripts/seismic_testbed/g_sweep_querycut_heapfactor.py \
        --index-path data/thin_client_poc/seismic_idx \
        --queries 60 \
        --result-file data/eval_results/seismic_sweep_c1_querycut_heapfactor.json
"""
import argparse
import json
import logging
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import seismic_backend  # noqa: E402  (the single-index SeismicBackend under test)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("c1_sweep")

TOP_K = 50                # matches eval_seismic_parity.py (overlap computed @10, fetch @50)
OVERLAP_K = 10
WARMUP_REPEATS = 5        # per-cell traverse repeats for a stable p50

# The §C1 grid + the recall-first baseline reference (all-terms, hf=0.8).
QUERY_CUTS = [10, 15, 20]
HEAP_FACTORS = [0.6, 0.7, 0.8]
BASELINE_QUERY_CUT = None  # None == len(tokens) (all 64 terms) — the recall-max reference
BASELINE_HEAP_FACTOR = 0.8


def load_queries(n: int, qpath: Path) -> list[dict]:
    """The documented 34/60-common query set (eval_seismic_parity.load_queries)."""
    records = json.loads(qpath.read_text())
    out, seen = [], set()
    for rec in records:
        if rec["paraphrase"] not in seen:
            seen.add(rec["paraphrase"])
            out.append(rec)
        if len(out) >= n:
            break
    return out


def overlap(a: list[str], b: list[str], k: int = OVERLAP_K) -> float:
    return len(set(a[:k]) & set(b[:k])) / max(min(len(b), k), 1)


def run_cell(sb, qcomp, qvals, n_terms, query_cut, heap_factor, warm_enc):
    """One (qc, hf) cell across NO repeat (the query is already a warm qcomp/qvals
    pair). Returns (top10_ids, traverse_ms_p50, enc_ms_warm). enc_ms is the
    pre-computed warm encode of THIS query; traversal is timed WARMUP_REPEATS
    times and we take the p50."""
    qc = query_cut if query_cut is not None else n_terms
    ts = []
    res = []
    for _ in range(WARMUP_REPEATS):
        t0 = time.perf_counter()
        res = sb.index.search(query_id="q", query_components=qcomp, query_values=qvals,
                              k=TOP_K, query_cut=qc, heap_factor=heap_factor)
        ts.append((time.perf_counter() - t0) * 1000)
    top10 = [doc_id for (_qid, _dist, doc_id) in res[:OVERLAP_K]]
    return top10, statistics.median(ts), warm_enc


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index-path", default="data/thin_client_poc/seismic_idx",
                    help="saved SEISMIC index stem (.index.seismic)")
    ap.add_argument("--queries", type=int, default=60,
                    help="number of diverse queries to sweep over")
    ap.add_argument("--model-path", default="models/splade_onnx_fp16")
    ap.add_argument("--query-workload",
                    default=str(REPO / "data/eval_results/diverse_queries.json"))
    ap.add_argument("--result-file", default=None)
    args = ap.parse_args()

    qpath = Path(args.query_workload)
    assert qpath.exists(), f"query workload missing: {qpath}"
    queries = load_queries(args.queries, qpath)
    log.info("loaded %d queries from %s", len(queries), qpath)

    sb = seismic_backend.SeismicBackend(args.index_path, args.model_path)
    log.info("loaded index len=%d dim=%d nnz=%d", sb.index.len, sb.index.dim, sb.index.nnz)

    # === warmup: cold model load (~76s at fp16) amortized away before timing ===
    log.info("warming encoder + index (cold model load amortized here)...")
    t0 = time.perf_counter()
    for rec in queries[:max(3, len(queries) // 4)]:
        sb.encode_query(rec["paraphrase"])
    log.info("warmup done in %.1fs", time.perf_counter() - t0)

    # === baseline (all-terms, hf=0.8): the recall-max reference each cell is measured against ===
    log.info("baseline: query_cut=all-terms, heap_factor=%.1f", BASELINE_HEAP_FACTOR)
    base_top10_by_q = []   # per-query baseline top-10 ids (the self-relative recall ref)
    base_traverse = []
    base_encode = []
    for rec in queries:
        q = rec["paraphrase"]
        t0 = time.perf_counter(); ql = sb.encode_query(q); enc_ms = (time.perf_counter() - t0) * 1000
        toks = list(ql.keys()); vals = [float(v) for v in ql.values()]
        import numpy as np
        qcomp = np.array(toks, dtype=sb._string_dtype); qv = np.array(vals, dtype=np.float32)
        top10, trav_ms, _ = run_cell(sb, qcomp, qv, len(toks),
                                     BASELINE_QUERY_CUT, BASELINE_HEAP_FACTOR, enc_ms)
        base_top10_by_q.append(top10); base_traverse.append(trav_ms); base_encode.append(enc_ms)
    log.info("baseline traverse p50(mean)=%.3fms warm-encode p50(mean)=%.2fms",
             statistics.mean(base_traverse), statistics.mean(base_encode))

    # === the §C1 grid ===
    grid = []   # list of cell summaries
    for qc in QUERY_CUTS:
        for hf in HEAP_FACTORS:
            ovs, trvs, encs = [], [], []
            for i, rec in enumerate(queries):
                q = rec["paraphrase"]
                # re-encode warm per query (cheap ~17ms) so encode_ms is in the cell stat
                t0 = time.perf_counter(); ql = sb.encode_query(q); enc_ms = (time.perf_counter() - t0) * 1000
                import numpy as np
                toks = list(ql.keys()); vals = [float(v) for v in ql.values()]
                qcomp = np.array(toks, dtype=sb._string_dtype); qv = np.array(vals, dtype=np.float32)
                top10, trav_ms, _ = run_cell(sb, qcomp, qv, len(toks), qc, hf, enc_ms)
                ovs.append(overlap(top10, base_top10_by_q[i]))
                trvs.append(trav_ms); encs.append(enc_ms)
            cell = {
                "query_cut": qc, "heap_factor": hf,
                "overlap@10_vs_base": round(statistics.mean(ovs), 4),
                "overlap@10_min": round(min(ovs), 4),
                "traverse_ms_p50": round(statistics.mean(trvs), 3),
                "warm_encode_ms_mean": round(statistics.mean(encs), 2),
                "traverse_speedup_vs_base": round(
                    statistics.mean(base_traverse) / statistics.mean(trvs), 2),
                "n_queries": len(queries),
            }
            grid.append(cell)
            log.info("qc=%-3d hf=%.1f  overlap@10=%.4f  trav_p50=%.3fms (%.2fx)  enc=%.1fms",
                     qc, hf, cell["overlap@10_vs_base"], cell["traverse_ms_p50"],
                     cell["traverse_speedup_vs_base"], cell["warm_encode_ms_mean"])

    summary = {
        "meta": {
            "engine": "seismic-pyseismic-lsr-0.5.0",
            "purpose": "08_LATENCY_RESEARCH.md §C1: query_cut×heap_factor latency-vs-overlap@10 Pareto",
            "measured_utc": time.strftime("%Y-%m-%d", time.gmtime()),
            "index": {"path": args.index_path, "docs": sb.index.len,
                      "dim": sb.index.dim, "nnz": sb.index.nnz},
            "model": args.model_path,
            "n_queries": len(queries),
            "top_k_fetch": TOP_K, "overlap_k": OVERLAP_K,
            "warmup_repeats_per_cell": WARMUP_REPEATS,
            "note": ("overlap@10 is vs the all-terms/hf=0.8 baseline (self-relative recall), "
                     "NOT vs a live Qdrant. Absolute latency is swap-confounded off a clean host; "
                     "the encode/traverse split + relative recall are the clean signals here."),
        },
        "baseline": {
            "query_cut": "all-terms", "heap_factor": BASELINE_HEAP_FACTOR,
            "traverse_ms_p50": round(statistics.mean(base_traverse), 3),
            "warm_encode_ms_mean": round(statistics.mean(base_encode), 2),
            "n_queries": len(queries),
        },
        "grid": grid,
        "pareto_winners": sorted(
            [c for c in grid if c["overlap@10_vs_base"] >= 0.99],
            key=lambda c: c["traverse_ms_p50"])[:3],
    }
    rpath = (Path(args.result_file) if args.result_file
             else REPO / f"data/eval_results/seismic_sweep_c1_querycut_heapfactor_{int(time.time())}.json")
    rpath.parent.mkdir(parents=True, exist_ok=True)
    json.dump(summary, open(rpath, "w"), indent=2)
    log.info("wrote %s", rpath)
    print(json.dumps({"baseline_traverse_ms": summary["baseline"]["traverse_ms_p50"],
                      "best_pareto": summary["pareto_winners"][:1],
                      "result_file": str(rpath)}))


if __name__ == "__main__":
    main()
